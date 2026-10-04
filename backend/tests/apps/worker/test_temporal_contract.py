# SPDX-License-Identifier: Apache-2.0
"""What 2b's design takes from Temporal itself (engine 2b spec §11.1), pinned to the versions it was measured on. An
upgrade that changes any of it fails a test here, and the spec's premises are verified again before it lands.

Test-only workflows on the CLI dev server, through the tenant codec with fixture keys, two tenants side by side:
- every payload, on every path, is encoded and decoded with a context whose workflow id names its tenant;
- a schedule's `TemporalScheduledStartTime` is whole seconds and the same under replay, and a backfill over a time
  that already fired starts a second execution with the same time;
- a schedule update sent directly with a conflict token that a later update made stale is discarded, not refused: the
  call succeeds and nothing changes, so a writer learns it from the describe that follows (2b-3a's sync);
- the SDK checks a payload's size after the codec;
- a workflow task whose completion passes the gRPC message limit gets its workflow terminated."""

import asyncio
import contextlib
import dataclasses
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import temporalio
from temporalio import activity, workflow
from temporalio.api.common.v1 import Payload
from temporalio.api.enums.v1 import EventType
from temporalio.api.workflowservice.v1 import DescribeScheduleRequest, GetSystemInfoRequest, UpdateScheduleRequest
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleBackfill,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
    WorkflowExecutionStatus,
    WorkflowFailureError,
    WorkflowHandle,
    WorkflowHistory,
)
from temporalio.common import RetryPolicy, SearchAttributeKey
from temporalio.converter import ActivitySerializationContext, DataConverter, SerializationContext
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from dewpoint.apps.codec import TENANT, KeySource, TenantCodec, data_converter
from dewpoint.engine.runtime.ids import run_workflow_id, tenant_of
from dewpoint.engine.runtime.size import CODEC_OVERHEAD
from tests.support.keys import FixtureKeys, opened

SDK, SERVER = "1.33.0", "1.32.0"  # what §11.1 measured
PAYLOAD_LIMIT = 2 * 1024 * 1024  # Temporal's per-payload limit, which the SDK checks
QUEUE = "temporal-contract"
A, B = str(uuid.uuid4()), str(uuid.uuid4())
SCHEDULED = SearchAttributeKey.for_datetime("TemporalScheduledStartTime")
TIMEOUT = timedelta(seconds=10)

CALLS: list[tuple[str, str, str | None]] = []  # (encode or decode, the context's kind, the tenant it names)
TICKS: list[tuple[str, str | None, bool]] = []  # (a tick's workflow id, its TemporalScheduledStartTime, replaying)


class Recording(TenantCodec):
    """The tenant codec, recording each call's context: which paths the SDK gives one to, and whose tenant it names."""

    def __init__(self, keys: KeySource, tenant_id: str | None = None, kind: str = "none") -> None:
        super().__init__(keys, tenant_id)
        self.keys, self.tenant_id, self.kind = keys, tenant_id, kind

    def with_context(self, context: SerializationContext) -> "Recording":
        workflow_id = getattr(context, "workflow_id", None)
        local = isinstance(context, ActivitySerializationContext) and context.is_local
        kind = "local activity" if local else type(context).__name__
        return Recording(self.keys, tenant_of(workflow_id) if workflow_id else None, kind)

    async def encode(self, payloads: Sequence[Payload]) -> list[Payload]:
        CALLS.append(("encode", self.kind, self.tenant_id))
        return await super().encode(payloads)

    async def decode(self, payloads: Sequence[Payload]) -> list[Payload]:
        CALLS.append(("decode", self.kind, self.tenant_id))
        return await super().decode(payloads)


RECORDING = dataclasses.replace(data_converter(FixtureKeys()), payload_codec=Recording(FixtureKeys()))


@activity.defn
async def echo(value: dict[str, Any]) -> dict[str, Any]:
    return value


@activity.defn
async def fail(value: dict[str, Any]) -> dict[str, Any]:
    raise ApplicationError("the activity failed", {"detail": "d"}, non_retryable=True)


@activity.defn
async def beat(value: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat({"progress": 1})
    return value


@activity.defn
async def sink(value: str) -> int:
    return len(value)


@workflow.defn
class Child:
    def __init__(self) -> None:
        self.released = False

    @workflow.signal
    def release(self, value: dict[str, Any]) -> None:
        self.released = True

    @workflow.run
    async def run(self, start: dict[str, Any]) -> dict[str, Any]:
        await workflow.execute_activity(echo, {"from": "child"}, start_to_close_timeout=TIMEOUT)
        if not start.get("continued"):
            await workflow.get_external_workflow_handle(start["parent"]).signal("arrived", workflow.info().workflow_id)
            await workflow.wait_condition(lambda: self.released)
            if start.get("continue"):
                workflow.continue_as_new({**start, "continued": True})
        if start.get("fail"):
            raise ApplicationError("the child failed", {"detail": "d"}, non_retryable=True)
        return {"continued": bool(start.get("continued"))}


@workflow.defn
class Parent:
    """Every path a Dewpoint run takes: activities, their failures and heartbeats; a local activity; children started,
    signalled both ways, continued as new and failed; a batch-style child id; continue-as-new."""

    def __init__(self) -> None:
        self.arrived: set[str] = set()

    @workflow.signal(name="arrived")
    def on_arrived(self, child_id: str) -> None:
        self.arrived.add(child_id)

    async def child(self, child_id: str, **start: Any) -> Any:
        me = workflow.info().workflow_id
        handle = await workflow.start_child_workflow(Child.run, {"parent": me, **start}, id=child_id)
        await workflow.wait_condition(lambda: child_id in self.arrived)
        await handle.signal(Child.release, {})
        return await handle

    @workflow.run
    async def run(self, start: dict[str, Any]) -> dict[str, Any]:
        tenant, me = start["tenant"], workflow.info().workflow_id
        await workflow.execute_activity(echo, {"tenant_id": tenant}, start_to_close_timeout=TIMEOUT)
        if start.get("continued"):
            return {"tenant": tenant}
        await workflow.execute_local_activity(echo, {"local": True}, start_to_close_timeout=TIMEOUT)
        try:
            await workflow.execute_activity(
                fail, {}, start_to_close_timeout=TIMEOUT, retry_policy=RetryPolicy(maximum_attempts=1)
            )
        except ActivityError:
            pass
        await workflow.execute_activity(beat, {}, start_to_close_timeout=TIMEOUT, heartbeat_timeout=TIMEOUT)
        await self.child(run_workflow_id(tenant, str(workflow.uuid4())), **{"continue": True})
        await self.child(f"{me}/{uuid.UUID(int=7)}/l:0/batch:0")  # a batch, by the exact grammar
        try:
            await self.child(run_workflow_id(tenant, str(workflow.uuid4())), fail=True)
        except ChildWorkflowError:
            pass
        workflow.continue_as_new({**start, "continued": True})


@workflow.defn
class Failer:
    @workflow.run
    async def run(self, start: dict[str, Any]) -> None:
        raise ApplicationError("the workflow failed", {"detail": "d"}, non_retryable=True)


@workflow.defn
class Tick:
    @workflow.run
    async def run(self, schedule_id: str) -> str | None:
        at = workflow.info().typed_search_attributes.get(SCHEDULED)
        stamp = at.isoformat() if at else None
        TICKS.append((workflow.info().workflow_id, stamp, workflow.unsafe.is_replaying()))
        await workflow.execute_activity(echo, {"at": stamp}, start_to_close_timeout=TIMEOUT)
        return stamp


@workflow.defn
class Sends:
    @workflow.run
    async def run(self, sizes: list[int]) -> list[int]:
        """One activity per size, all scheduled in the same workflow task."""
        sent = [workflow.execute_activity(sink, "x" * n, start_to_close_timeout=TIMEOUT) for n in sizes]
        return list(await asyncio.gather(*sent))


WORKFLOWS = [Parent, Child, Failer, Tick, Sends]


@contextlib.asynccontextmanager
async def serving(client: Client) -> AsyncIterator[None]:
    async with Worker(
        client,
        task_queue=QUEUE,
        workflows=WORKFLOWS,
        activities=[echo, fail, beat, sink],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        yield


async def begin(client: Client, run: Any, arg: Any, tenant: str = A) -> WorkflowHandle[Any, Any]:
    """A run of a test workflow, under a workflow id that names `tenant`, as Dewpoint builds them (spec §6.1)."""
    return await client.start_workflow(run, arg, id=run_workflow_id(tenant, str(uuid.uuid4())), task_queue=QUEUE)


async def histories(client: Client, query: str) -> list[WorkflowHistory]:
    return [
        await client.get_workflow_handle(w.id, run_id=w.run_id).fetch_history()
        async for w in client.list_workflows(query)
    ]


async def test_the_versions_these_checks_were_measured_on(dev_env: WorkflowEnvironment) -> None:
    info = await dev_env.client.workflow_service.get_system_info(GetSystemInfoRequest())
    assert (temporalio.__version__, info.server_version) == (SDK, SERVER)


async def test_every_path_encrypts_under_the_tenant_its_workflow_id_names(dev_env: WorkflowEnvironment) -> None:
    """§11.1, experiment 1: the codec refuses without a tenant, so a path with no context fails its run. Each run's
    calls name only its own tenant, and the recording shows which paths ran: workflow and activity sides, local
    activities, children, signals, continue-as-new, failures with encoded attributes, and a replay of all of it."""
    CALLS.clear()
    client = Client(dev_env.client.service_client, namespace=dev_env.client.namespace, data_converter=RECORDING)
    async with serving(client):
        parents = [await begin(client, Parent.run, {"tenant": t}, t) for t in (A, B)]
        assert await asyncio.gather(*(h.result() for h in parents)) == [{"tenant": A}, {"tenant": B}]
        failer = await begin(client, Failer.run, {})
        try:
            await failer.result()
            raise AssertionError("the workflow didn't fail")
        except WorkflowFailureError as e:  # its message went encrypted, and came back decrypted
            assert isinstance(e.cause, ApplicationError) and e.cause.message == "the workflow failed"
    assert {tenant for _, _, tenant in CALLS} == {A, B}
    assert {(op, kind) for op, kind, _ in CALLS} >= {
        (op, kind)
        for op in ("encode", "decode")
        for kind in ("WorkflowSerializationContext", "ActivitySerializationContext", "local activity")
    }
    CALLS.clear()
    await replay([Parent, Child], await histories(client, "WorkflowType='Parent' OR WorkflowType='Child'"))
    assert CALLS and {tenant for _, _, tenant in CALLS} == {A, B}


async def test_a_schedules_time_is_whole_seconds_the_same_on_replay_and_a_backfill_repeats_it(
    dev_env: WorkflowEnvironment,
) -> None:
    """§11.1, experiment 1: `ScheduleTick` (2b-3) keys its request on `TemporalScheduledStartTime`. Temporal gives it
    in whole seconds, and replay sees the same; a backfill over a time that already fired starts another execution
    with the same time, which the key collapses (spec §8.2). The schedule's own payloads go through the codec too:
    its id names the tenant, as its workflows' ids do."""
    TICKS.clear()
    client = Client(dev_env.client.service_client, namespace=dev_env.client.namespace, data_converter=RECORDING)
    schedule_id = f"t:{B}:sched:{uuid.uuid4()}"
    async with serving(client):
        handle = await client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(Tick.run, schedule_id, id=schedule_id, task_queue=QUEUE),
                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
                state=ScheduleState(paused=True),  # only the backfills fire
            ),
        )
        described = await handle.describe()
        assert isinstance(described.schedule.action, ScheduleActionStartWorkflow)
        [arg] = described.schedule.action.args  # as Temporal holds it: sealed under the schedule's tenant
        assert isinstance(arg, Payload) and arg.metadata[TENANT] == B.encode() and await opened(arg) == schedule_id
        end = described.info.created_at.replace(second=0, microsecond=0)
        start = end - timedelta(minutes=2)
        window = ScheduleBackfill(start_at=start, end_at=end, overlap=ScheduleOverlapPolicy.ALLOW_ALL)
        await handle.backfill(window)
        await ticked(client, 3)
        await handle.backfill(window)  # the same times again, once the first three have ended
        await ticked(client, 6)
        runs = await ticks_of(client, schedule_id)
        await handle.delete()
    times = stamps(replaying=False)
    assert all(t.endswith(":00+00:00") for t in times), times  # whole seconds: whole minutes, here
    assert len(times) == 6 and len(set(times)) == 3  # the second backfill started each time again
    TICKS.clear()
    await replay([Tick], runs)
    assert stamps(replaying=True) == times


async def test_a_stale_schedule_update_is_discarded_and_the_describe_after_it_shows_it(
    dev_env: WorkflowEnvironment,
) -> None:
    """2b-3a's first M3 gate (the owner's correction): SDK 1.33.0's `ScheduleHandle.update()` sends no conflict token,
    so the sync sends `UpdateScheduleRequest` itself, with the token of the `DescribeScheduleResponse` it computed from.
    On this server the token counts the schedule's updates (a firing doesn't move it); an update with the current one
    lands and is seen by the describe at once; one with a token a later update made stale is DISCARDED: the call
    succeeds and nothing changes. So Temporal never lets a stale writer overwrite a newer state, but tells it only
    through the describe that follows, which the sync reads before it records anything. A pause is the update's own
    `state.paused`, under the same token; the action stays sealed under the schedule's tenant."""
    client = Client(dev_env.client.service_client, namespace=dev_env.client.namespace, data_converter=RECORDING)
    schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
    service, namespace = client.workflow_service, client.namespace

    def every(hours: int, *, paused: bool = True) -> Schedule:
        return Schedule(
            action=ScheduleActionStartWorkflow(Tick.run, schedule_id, id=schedule_id, task_queue=QUEUE),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=hours))]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
            state=ScheduleState(paused=paused),
        )

    async def described() -> tuple[bytes, int, bool]:
        answer = await service.describe_schedule(DescribeScheduleRequest(namespace=namespace, schedule_id=schedule_id))
        return answer.conflict_token, answer.schedule.spec.interval[0].interval.seconds, answer.schedule.state.paused

    async def update(schedule: Schedule, token: bytes) -> None:
        await service.update_schedule(
            UpdateScheduleRequest(
                namespace=namespace, schedule_id=schedule_id, schedule=await schedule._to_proto(client),
                conflict_token=token, identity="contract", request_id=str(uuid.uuid4()),
            )
        )  # fmt: skip

    handle = await client.create_schedule(schedule_id, every(1))
    first, _, _ = await described()
    await update(every(2), first)
    second, interval, _ = await described()  # at once: no wait
    assert second != first and interval == 7200
    await update(every(3), first)  # computed from the first describe: stale since the second update
    assert await described() == (second, 7200, True)  # discarded, and the call didn't fail
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    await handle.backfill(ScheduleBackfill(start_at=now - timedelta(minutes=2), end_at=now,
                                           overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
    assert (await described())[0] == second  # a firing isn't an update
    await update(every(3, paused=False), second)
    third, interval, paused = await described()
    assert (third != second, interval, paused) == (True, 10800, False)  # unpaused through the update's state
    action = (await handle.describe()).schedule.action
    assert isinstance(action, ScheduleActionStartWorkflow)
    [arg] = action.args
    assert isinstance(arg, Payload) and arg.metadata[TENANT] == A.encode() and await opened(arg) == schedule_id
    await handle.delete()


async def replay(workflows: list[type], runs: list[WorkflowHistory]) -> None:
    """Every history, replayed through the recording codec: a nondeterminism, or a path without a tenant, raises."""

    async def each() -> AsyncIterator[WorkflowHistory]:
        for run in runs:
            yield run

    replayer = Replayer(workflows=workflows, data_converter=RECORDING, workflow_runner=UnsandboxedWorkflowRunner())
    await replayer.replay_workflows(each())


async def ticks_of(client: Client, schedule_id: str) -> list[WorkflowHistory]:
    return [h for h in await histories(client, "WorkflowType='Tick'") if h.workflow_id.startswith(schedule_id)]


def stamps(*, replaying: bool) -> list[str]:
    """The `TemporalScheduledStartTime` each tick saw, running or replaying."""
    return sorted(s for _, s, r in TICKS if r == replaying and s)


async def ticked(client: Client, n: int) -> None:
    """Until `n` ticks have run to their end."""
    for _ in range(120):
        if len([w for w, _, replaying in TICKS if not replaying]) >= n:
            break
        await asyncio.sleep(0.5)
    for workflow_id, _, replaying in list(TICKS):
        if not replaying:
            await asyncio.wait_for(client.get_workflow_handle(workflow_id).result(), 30)


def plain_bytes(n: int) -> int:
    """What the SDK measures of an `n`-character string's payload before the codec."""
    [p] = DataConverter.default.payload_converter.to_payloads(["x" * n])
    return p.ByteSize()


async def task_failures(handle: WorkflowHandle[Any, Any]) -> list[str]:
    return [
        e.workflow_task_failed_event_attributes.failure.message
        async for e in handle.fetch_history_events()
        if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED
    ]


async def test_the_sdk_checks_a_payloads_size_after_the_codec(dev_env: WorkflowEnvironment) -> None:
    """§11.1, experiment 2: a payload under the limit before the codec, over it once encrypted, fails its workflow
    task, which retries. So a guard counts the codec's overhead (CODEC_OVERHEAD): one that fits with it passes."""
    over = PAYLOAD_LIMIT - 64
    while plain_bytes(over) >= PAYLOAD_LIMIT:
        over -= 1
    fits = over - CODEC_OVERHEAD
    client = dev_env.client
    async with serving(client):
        ok = await begin(client, Sends.run, [fits])
        assert await asyncio.wait_for(ok.result(), 30) == [fits]
        refused = await begin(client, Sends.run, [over])
        failures: list[str] = []
        for _ in range(60):
            failures = await task_failures(refused)
            if failures:
                break
            await asyncio.sleep(0.25)
        await refused.terminate("checked")
    assert plain_bytes(over) < PAYLOAD_LIMIT and failures and "TMPRL1103" in failures[0], failures[:1]


async def test_a_completion_past_the_grpc_limit_gets_its_workflow_terminated(dev_env: WorkflowEnvironment) -> None:
    """§11.1, experiment 2: three commands of 1.5 MiB in one workflow task pass the 4 MiB gRPC message limit; Temporal
    terminates the workflow, with no chance to record an end (spec §5.2's per-task invariant). Two of them fit."""
    big = 1536 * 1024
    client = dev_env.client
    async with serving(client):
        two = await begin(client, Sends.run, [big] * 2)
        assert await asyncio.wait_for(two.result(), 60) == [big] * 2
        three = await begin(client, Sends.run, [big] * 3)
        with contextlib.suppress(WorkflowFailureError):
            await asyncio.wait_for(three.result(), 60)
        status = (await three.describe()).status
    assert status == WorkflowExecutionStatus.TERMINATED


async def test_a_schedules_missed_times_catch_up_after_an_outage_with_their_own_time(tmp_path: Path) -> None:
    """§11.1, experiment 1: a server that was down fires the times it missed when it's back, within the catch-up
    window, each with its own `TemporalScheduledStartTime`, and replay sees the same (the 2b-3 tick's key)."""
    TICKS.clear()
    args = ["--db-filename", str(tmp_path / "temporal.db")]
    schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
    every = timedelta(seconds=5)
    async with await WorkflowEnvironment.start_local(data_converter=RECORDING, dev_server_extra_args=args) as env:
        async with serving(env.client):
            await env.client.create_schedule(
                schedule_id,
                Schedule(
                    action=ScheduleActionStartWorkflow(Tick.run, schedule_id, id=schedule_id, task_queue=QUEUE),
                    spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every)]),
                    policy=SchedulePolicy(catchup_window=timedelta(minutes=1), overlap=ScheduleOverlapPolicy.ALLOW_ALL),
                ),
            )
            await ticked(env.client, 1)
    down = datetime.now(UTC)
    await asyncio.sleep(16)  # about three firings missed
    async with await WorkflowEnvironment.start_local(data_converter=RECORDING, dev_server_extra_args=args) as env:
        async with serving(env.client):
            await ticked(env.client, 4)
            runs = await ticks_of(env.client, schedule_id)
            await env.client.get_schedule_handle(schedule_id).delete()
    times = stamps(replaying=False)
    missed = [t for t in times if datetime.fromisoformat(t) > down]
    assert len(missed) >= 2, times  # each missed time fired, with its own time
    assert all(datetime.fromisoformat(t).microsecond == 0 for t in times)
    TICKS.clear()
    await replay([Tick], runs)
    assert stamps(replaying=True) == times
