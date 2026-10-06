# SPDX-License-Identifier: Apache-2.0
"""What tenant erasure takes from Temporal (the 2b-4 outline's "Tenant erasure"; 2b-4a M4), measured on the CLI dev
server (Temporal CLI 1.9.1, Server 1.32.0; `test_temporal_contract.py` pins the versions). An upgrade that changes any
of it fails a test here.

- A paused schedule's due firings are neither caught up after its unpause nor counted as missed;
  `ListScheduleMatchingTimes` counts them (D3f: the sync counts what a schedule created paused missed). Paused, its
  count of firings missed past the catch-up window doesn't grow even across an outage longer than the window, where an
  unpaused one's does: the count a paused schedule shows is final (D3f: the sync deletes an incarnation only once it
  shows paused and that count is recorded).
- **The deleted-and-recreated token test FAILS the outline's premise:** a schedule's conflict token counts its updates
  and patches from 1, a deleted schedule's recreation starts again at 1, and an update carrying a token taken from the
  deleted schedule lands on the recreated one, unpausing it. So paused creation under one id doesn't make a late create
  unable to fire. The sync gives each create its own incarnation id instead (the owner's ruling on the M4 checkpoint),
  which `tests/apps/erasure/test_incarnations.py` proves against this race.
- A schedule's describe lists its running workflows under the SKIP and BUFFER_ALL overlap policies, not under
  ALLOW_ALL (2b-3a's): with ALLOW_ALL, a running tick isn't listed by its schedule; recent actions keep the last 10.
- `DeleteWorkflowExecution` removes a running or a closed execution: describing that exact run answers NOT_FOUND, at
  once for a running one, asynchronously for a closed one (10 to 54 s measured here: an erasure retries one still
  present later), and deleting it again answers NOT_FOUND too.
- Visibility finds a tenant's executions by workflow-id prefix (`WorkflowId STARTS_WITH 't:<tenant>:'`)."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

from temporalio import workflow
from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.schedule.v1 import SchedulePatch
from temporalio.api.workflowservice.v1 import (
    DeleteWorkflowExecutionRequest,
    DescribeScheduleRequest,
    DescribeWorkflowExecutionRequest,
    ListScheduleMatchingTimesRequest,
    PatchScheduleRequest,
    UpdateScheduleRequest,
)
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

QUEUE = "temporal-erasure-contract"
A = str(uuid.uuid4())


@workflow.defn
class Waits:
    @workflow.run
    async def run(self) -> None:
        await workflow.wait_condition(lambda: False)


@workflow.defn
class Ends:
    @workflow.run
    async def run(self) -> None:
        return None


@contextlib.asynccontextmanager
async def serving(client: Client) -> AsyncIterator[None]:
    async with Worker(client, task_queue=QUEUE, workflows=[Waits, Ends], workflow_runner=UnsandboxedWorkflowRunner()):
        yield


def every_second(
    schedule_id: str, run: object, *, paused: bool, overlap: ScheduleOverlapPolicy, note: str = ""
) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(run, id=schedule_id, task_queue=QUEUE),  # type: ignore[arg-type]
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=1))]),
        policy=SchedulePolicy(overlap=overlap),
        state=ScheduleState(paused=paused, note=note),
    )


async def describe(client: Client, schedule_id: str):  # type: ignore[no-untyped-def]
    return await client.workflow_service.describe_schedule(
        DescribeScheduleRequest(namespace=client.namespace, schedule_id=schedule_id)
    )


async def update(client: Client, schedule_id: str, schedule: Schedule, token: bytes) -> None:
    await client.workflow_service.update_schedule(
        UpdateScheduleRequest(
            namespace=client.namespace, schedule_id=schedule_id, schedule=await schedule._to_proto(client),
            conflict_token=token, identity="contract", request_id=str(uuid.uuid4()),
        )
    )  # fmt: skip


async def test_a_paused_schedules_due_firings_are_neither_caught_up_nor_counted_but_matching_times_count_them(
    dev_env: WorkflowEnvironment,
) -> None:
    client = dev_env.client
    schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
    async with serving(client):
        await client.create_schedule(schedule_id, every_second(schedule_id, Ends.run, paused=True,
                                                               overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
        await asyncio.sleep(3.2)
        waited = await describe(client, schedule_id)
        assert (waited.info.action_count, waited.info.missed_catchup_window) == (0, 0)
        await update(
            client,
            schedule_id,
            every_second(schedule_id, Ends.run, paused=False, overlap=ScheduleOverlapPolicy.ALLOW_ALL),
            waited.conflict_token,
        )
        unpaused = await describe(client, schedule_id)
        request = ListScheduleMatchingTimesRequest(namespace=client.namespace, schedule_id=schedule_id)
        request.start_time.CopyFrom(unpaused.info.create_time)
        request.end_time.CopyFrom(unpaused.info.update_time)
        matched = len((await client.workflow_service.list_schedule_matching_times(request)).start_time)
        await asyncio.sleep(1.5)
        after = await describe(client, schedule_id)
        await client.get_schedule_handle(schedule_id).delete()
    assert matched >= 3  # due while paused
    assert after.info.missed_catchup_window == 0 and after.info.action_count <= 2  # none of them caught up


async def test_a_paused_schedules_missed_count_doesnt_grow_across_an_outage_longer_than_its_window(tmp_path) -> None:
    """Every 2 s, a 10 s catch-up window, the server down 25 s: the unpaused schedule counts the firings it skipped,
    the paused one counts none."""
    from tests.support.temporal import start_local

    args = ["--db-filename", str(tmp_path / "temporal.db")]
    paused_id, running_id = f"t:{A}:sched:{uuid.uuid4()}", f"t:{A}:sched:{uuid.uuid4()}"

    def every_2s(schedule_id: str, *, paused: bool) -> Schedule:
        return Schedule(
            action=ScheduleActionStartWorkflow(Ends.run, id=schedule_id, task_queue=QUEUE),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=2))]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL, catchup_window=timedelta(seconds=10)),
            state=ScheduleState(paused=paused),
        )

    async with await start_local(dev_server_extra_args=args) as env:
        await env.client.create_schedule(paused_id, every_2s(paused_id, paused=True))
        await env.client.create_schedule(running_id, every_2s(running_id, paused=False))
        for _ in range(100):  # both schedulers running
            if (await describe(env.client, running_id)).info.action_count >= 2:
                break
            await asyncio.sleep(0.2)
    await asyncio.sleep(25)  # past the window
    async with await start_local(dev_server_extra_args=args) as env:
        for _ in range(100):
            running = await describe(env.client, running_id)
            if running.info.missed_catchup_window:
                break
            await asyncio.sleep(0.2)
        await asyncio.sleep(2)  # the paused one's scheduler has caught up too
        paused = await describe(env.client, paused_id)
    assert running.info.missed_catchup_window > 0
    assert (paused.info.missed_catchup_window, paused.info.action_count) == (0, 0)


async def test_a_deleted_and_recreated_schedule_restarts_its_token_so_a_stale_unpause_lands_on_it(
    dev_env: WorkflowEnvironment,
) -> None:
    """The outline's paused-creation protection was to be relied on only once a token taken from a deleted schedule
    never matches a recreated one. It does match: this pins Temporal's behaviour, which incarnation ids work around."""
    client = dev_env.client
    schedule_id = f"t:{A}:sched:{uuid.uuid4()}"

    def wanted(*, paused: bool, note: str) -> Schedule:
        return every_second(schedule_id, Ends.run, paused=paused, overlap=ScheduleOverlapPolicy.ALLOW_ALL, note=note)

    await client.create_schedule(schedule_id, wanted(paused=True, note="created"))
    first = (await describe(client, schedule_id)).conflict_token
    assert first == (1).to_bytes(8, "big")  # it counts from 1
    await client.workflow_service.patch_schedule(PatchScheduleRequest(
        namespace=client.namespace, schedule_id=schedule_id, patch=SchedulePatch(pause="erasing"),
        request_id=str(uuid.uuid4()),
    ))  # fmt: skip
    patched = await describe(client, schedule_id)
    assert patched.conflict_token == (2).to_bytes(8, "big") and patched.schedule.state.notes == "erasing"  # a patch too
    await client.get_schedule_handle(schedule_id).delete()
    await client.create_schedule(schedule_id, wanted(paused=True, note="created"))  # a late create, landing paused
    assert (await describe(client, schedule_id)).conflict_token == first  # it counts from 1 again
    await update(client, schedule_id, wanted(paused=False, note="stale"), first)  # an unpause from before the delete
    landed = await describe(client, schedule_id)
    await client.get_schedule_handle(schedule_id).delete()
    assert (landed.schedule.state.paused, landed.schedule.state.notes) == (False, "stale")  # it landed


async def test_a_schedule_lists_its_running_workflows_unless_its_overlap_allows_all(
    dev_env: WorkflowEnvironment,
) -> None:
    client = dev_env.client
    listed: dict[str, int] = {}
    async with serving(client):
        for overlap in (ScheduleOverlapPolicy.SKIP, ScheduleOverlapPolicy.BUFFER_ALL, ScheduleOverlapPolicy.ALLOW_ALL):
            schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
            await client.create_schedule(
                schedule_id, every_second(schedule_id, Waits.run, paused=False, overlap=overlap)
            )
            await asyncio.sleep(3.5)
            found = await describe(client, schedule_id)
            listed[overlap.name] = len(found.info.running_workflows)
            handle = client.get_schedule_handle(schedule_id)
            await handle.pause()
            await handle.delete()
            async for w in client.list_workflows(f"WorkflowId STARTS_WITH '{schedule_id}-'"):
                with contextlib.suppress(RPCError):
                    await client.get_workflow_handle(w.id, run_id=w.run_id).terminate()
    assert listed == {"SKIP": 1, "BUFFER_ALL": 1, "ALLOW_ALL": 0}


async def test_recent_actions_keep_the_last_ten(dev_env: WorkflowEnvironment) -> None:
    client = dev_env.client
    schedule_id = f"t:{A}:sched:{uuid.uuid4()}"
    async with serving(client):
        await client.create_schedule(schedule_id, every_second(schedule_id, Ends.run, paused=False,
                                                               overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
        await asyncio.sleep(13)
        found = await describe(client, schedule_id)
        await client.get_schedule_handle(schedule_id).delete()
    assert found.info.action_count > 10 and len(found.info.recent_actions) == 10


async def test_a_deleted_execution_running_or_closed_reads_back_not_found_and_visibility_finds_a_tenants_by_prefix(
    dev_env: WorkflowEnvironment,
) -> None:
    client, tenant = dev_env.client, str(uuid.uuid4())
    service, namespace = client.workflow_service, client.namespace
    async with serving(client):
        running = await client.start_workflow(Waits.run, id=f"t:{tenant}:run:{uuid.uuid4()}", task_queue=QUEUE)
        closed = await client.start_workflow(Ends.run, id=f"t:{tenant}:run:{uuid.uuid4()}", task_queue=QUEUE)
        await closed.result()
        for _ in range(100):
            found = {w.id async for w in client.list_workflows(f"WorkflowId STARTS_WITH 't:{tenant}:'")}
            if found == {running.id, closed.id}:
                break
            await asyncio.sleep(0.1)
        assert found == {running.id, closed.id}
        for handle in (running, closed):
            execution = WorkflowExecution(workflow_id=handle.id, run_id=handle.result_run_id or "")
            await service.delete_workflow_execution(
                DeleteWorkflowExecutionRequest(namespace=namespace, workflow_execution=execution)
            )
            for _ in range(240):
                try:
                    await service.describe_workflow_execution(
                        DescribeWorkflowExecutionRequest(namespace=namespace, execution=execution)
                    )
                except RPCError as e:
                    assert e.status == RPCStatusCode.NOT_FOUND
                    break
                await asyncio.sleep(0.5)
            else:
                raise AssertionError(f"still there after 120 s: {handle.id == running.id and 'running' or 'closed'}")
            try:
                await service.delete_workflow_execution(
                    DeleteWorkflowExecutionRequest(namespace=namespace, workflow_execution=execution)
                )
            except RPCError as e:
                assert e.status == RPCStatusCode.NOT_FOUND
