# SPDX-License-Identifier: Apache-2.0
"""What only a real Temporal server shows (2a-3b's handoff), on the dev server: a child an operator terminates
reaches its parent, which settles its whole grant and writes its end; and Temporal suggesting continue-as-new starts
the drain. Time runs for real here: waits are short, and a sleeping child is terminated, not waited for."""

import asyncio
import gc
import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType, WorkflowTaskFailedCause
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import Client, WorkflowHandle, WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from dewpoint.apps.worker.activities import cel_activity
from dewpoint.apps.worker.deployment import set_current
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import cel_queue
from dewpoint.engine.runtime.execution import SUBFLOW_GRANT
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from dewpoint.sdk import Empty, StepContext
from tests.apps.worker.harness import MemoryStore, in_process, run_id_of, start
from tests.apps.worker.test_deployment import build
from tests.apps.worker.test_main import settings
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref
from tests.support.keys import FIXTURE_CONVERTER
from tests.support.plugins.testkit import TESTKIT, EchoOutput, FailN, FailNConfig, SlowEcho, SlowEchoConfig


@asynccontextmanager
async def serving(client: Client, store: MemoryStore, *, grace_s: float | None = None) -> AsyncIterator[None]:
    """A build of this test's own, current: the dev server keeps the deployment's routing between tests. `grace_s`: how
    long its stopping worker lets running attempts finish."""
    this = build("real")
    evaluator = Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process, store)])
    grace = {} if grace_s is None else {"worker_shutdown_grace_s": grace_s}
    async with evaluator, engine_worker(client, store, [TESTKIT], settings(**grace), build=this, identity=this):
        await set_current(client, this)
        yield


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


def sleeper() -> G:
    return graph().node("d", "flow.delay@1", {"duration_s": 3600})


async def child_started(handle: WorkflowHandle[Any, Any]) -> str:
    """The first child's workflow id, once it has started (in real time)."""
    for _ in range(200):
        for e in (await handle.fetch_history()).events:
            if e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED:
                return e.child_workflow_execution_started_event_attributes.workflow_execution.workflow_id
        await asyncio.sleep(0.1)
    raise AssertionError("no child started")


async def test_a_terminated_sub_flow_fails_its_step_and_its_row_records_the_end(dev_env: WorkflowEnvironment) -> None:
    """The parent learns of the termination (the test server never tells it): its step fails with `terminated`
    under its error policy, the child's whole grant stays counted, and the sub-run's row, which the child never
    ended, records the end. It would otherwise stay `running` and hold its references."""
    client, store = dev_env.client, MemoryStore()
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sleeper()))}, on_error="continue")
    async with serving(client, store):
        handle = await start(client, store, g, {})
        child = await child_started(handle)
        await client.get_workflow_handle(child).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "terminated"}, SUBFLOW_GRANT)
    assert store.starts[run_id_of(child)].kind == "subflow"
    end = store.runs[run_id_of(child)]
    assert (end.status, end.error_code, end.iterations) == ("failed", "terminated", SUBFLOW_GRANT)


async def test_a_terminated_batch_fails_its_loop_and_its_whole_grant_stays_used(dev_env: WorkflowEnvironment) -> None:
    client, store = dev_env.client, MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", "flow.loop@1", {"items": list(range(101))}, on_error="continue").node(
        "d", "flow.delay@1", {"duration_s": 3600}
    )
    g.edge("l", "d", "body")
    async with serving(client, store):
        handle = await start(client, store, g, {})
        batch = await child_started(handle)
        await client.get_workflow_handle(batch).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert batch.endswith("/batch:0")
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "terminated"}, 100)


async def test_a_terminated_failure_handler_records_its_end_and_the_runs_stands(dev_env: WorkflowEnvironment) -> None:
    client, store = dev_env.client, MemoryStore()
    g = graph().node("f", "flow.fail@1", {"message": "it went wrong"})
    g.settings["failure_handler"] = str(store.publish(sleeper()))
    async with serving(client, store):
        handle = await start(client, store, g, {})
        handler = await child_started(handle)
        await client.get_workflow_handle(handler).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.error["code"] if result.error else None) == ("failed", "workflow_failed")
    assert result.iterations == SUBFLOW_GRANT  # the handler's whole grant: it never reported
    summary = store.runs[run_id_of(handler)]
    assert store.starts[run_id_of(handler)].kind == "failure_handler"
    assert (summary.status, summary.error_code) == ("failed", "terminated")
    assert store.runs[run_id_of(handle)].status == "failed"


def asks_for_more() -> G:
    """A filter over 1,500 items, more than its first grant of 1,000 iterations, so it asks for more; then a delay."""
    g = graph().node("f", "flow.filter@1", {"items": list(range(1_500)), "predicate": cel("item % 2 == 0")})
    return g.node("d", "flow.delay@1", {"duration_s": 3600}).edge("f", "d")


async def filtered(store: MemoryStore, run_id: str) -> None:
    """Until the run's filter has ended, so it has been granted more (its row lands in real time)."""
    for _ in range(200):
        if any(r.node_key == "f" and r.status == "succeeded" for r in store.steps(run_id)):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{run_id}'s filter never ended")


@pytest.mark.parametrize("kind", ["subflow", "failure_handler"])
async def test_a_terminated_sub_run_that_asked_for_more_records_its_whole_grant(
    dev_env: WorkflowEnvironment, kind: str
) -> None:
    """The final review: the row a parent writes for a terminated sub-run recorded its first grant, not all it had
    been granted, which the parent debits (spec §6)."""
    client, store = dev_env.client, MemoryStore()
    child_workflow = str(store.publish(asks_for_more()))
    if kind == "subflow":
        g = graph().node("r", "flow.run_workflow@1", {"workflow_id": child_workflow}, on_error="continue")
    else:
        g = graph().node("x", "flow.fail@1", {"message": "it went wrong"})
        g.settings["failure_handler"] = child_workflow
    async with serving(client, store):
        handle = await start(client, store, g, {})
        child = await child_started(handle)
        await filtered(store, run_id_of(child))
        await client.get_workflow_handle(child).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    sub = run_id_of(child)
    assert store.starts[sub].kind == kind
    assert result.iterations > SUBFLOW_GRANT  # it had been granted more, and the parent debits all of it
    assert (store.runs[sub].error_code, store.runs[sub].iterations) == ("terminated", result.iterations)


async def test_temporal_suggesting_continue_as_new_drains_the_run() -> None:
    """The dev server suggests continuing past 100 history events here (Temporal's default is thousands): the run
    drains and continues as new, long before its own thresholds (2,000 and 4,000), and ends as it would have."""
    args = ["--dynamic-config-value", "limit.historyCount.suggestContinueAsNew=100"]
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"))
    g.node("l", "flow.loop@1", {"items": list(range(40)), "collect": ref("steps.x.output.value")})
    g.node("x", "testkit.echo@1", {"value": ref("item")}).edge("l", "x", "body")
    local = WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args)
    async with await local as env, serving(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 120)
        chain = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"items": list(range(40))}, 40)
    assert len(chain) >= 2 and all(len(h.events) < 2_000 for h in chain)


def strings(*names: str) -> dict[str, Any]:
    return {"type": "object", "properties": {n: {"type": "string"} for n in names}, "required": list(names)}


async def task_failures(handle: WorkflowHandle[Any, Any]) -> list[int]:
    """The causes of every failed workflow task: none, when nothing retried a command Temporal refused."""
    out = []
    async for e in handle.fetch_history_events():
        if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED:
            out.append(e.workflow_task_failed_event_attributes.cause)
    return out


async def cel_requests(handle: WorkflowHandle[Any, Any]) -> list[int]:
    out = []
    async for e in handle.fetch_history_events():
        a = e.activity_task_scheduled_event_attributes
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED and a.activity_type.name == "cel.evaluate":
            out.append(a.workflow_task_completed_event_id)
    return out


async def test_issue_15s_filter_splits_its_request_and_keeps_every_item(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """#15's reproduction: 1,500 items each binding a 3,000-character string made a 3 MB request, whose workflow task
    retried until the run's deadline, or forever. It's split, and every item is evaluated. Each set carries its own
    copy here, as a value that isn't shared would be: a shared one is claimed once (#26)."""
    from dewpoint.engine.runtime import execution

    monkeypatch.setattr(execution, "SHARED_REPEAT", 1 << 62)
    client, store = dev_env.client, MemoryStore()
    g = G()
    g.settings = {"input_schema": strings("s"), "outputs": {"kept": cel("steps.f.output.count")}}
    g.node("f", "flow.filter@1", {"items": list(range(1_500)), "predicate": cel("size(trigger.s) > item")})
    async with serving(client, store):
        handle = await start(client, store, g, {"s": "x" * 3_000})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 1_500})
    assert len(await cel_requests(handle)) >= 3
    assert await task_failures(handle) == []


async def test_a_binding_set_over_the_request_limit_fails_its_step(dev_env: WorkflowEnvironment) -> None:
    """Two 900 KiB strings in one binding set pass 1.75 MiB: the step fails with `input_too_large`; nothing is sent."""
    client, store = dev_env.client, MemoryStore()
    half = 900 * 1024
    g = G()
    g.settings = {"input_schema": strings("a", "b"), "outputs": {"code": ref("steps.t.error.code", default="none")}}
    g.node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.a) + size(trigger.b)")}}, on_error="continue")
    async with serving(client, store):
        handle = await start(client, store, g, {"a": "x" * half, "b": "y" * half})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"})
    assert await cel_requests(handle) == []
    assert await task_failures(handle) == []


async def test_large_step_and_sub_flow_inputs_are_paced_under_temporals_message_limit(
    dev_env: WorkflowEnvironment,
) -> None:
    """Engine 2b spec §5.2's per-task invariant at the real limits: three step inputs and two sub-flow inputs of about
    1.6 MiB each become ready together. Sent in one workflow task, they'd pass Temporal's 4 MiB gRPC message limit,
    and Temporal would terminate the run (test_temporal_contract.py); they go out in separate tasks."""
    client, store = dev_env.client, MemoryStore()
    big = 1_600_000
    sub = G()
    sub.settings = {"input_schema": strings("v"), "outputs": {"n": cel("size(trigger.v)")}}
    sub.node("e", "testkit.echo@1", {"value": 1})
    sub_id = str(store.publish(sub))
    g = graph(**{k: ref(f"steps.{k}.output.n") for k in ("r", "s")})
    g.node("b", "testkit.blob@1", {"size": big})
    for k in ("x", "y", "z"):
        g.node(k, "testkit.echo@1", {"value": ref("steps.b.output.value")}).edge("b", k)
    for k in ("r", "s"):
        g.node(k, "flow.run_workflow@1", {"workflow_id": sub_id, "input": {"v": ref("steps.b.output.value")}})
        g.edge("b", k)
    async with serving(client, store):
        handle = await start(client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 120)
    assert (result.status, result.outputs) == ("succeeded", {"r": big, "s": big})
    assert await task_failures(handle) == []


async def test_three_large_requests_are_paced_under_temporals_message_limit(dev_env: WorkflowEnvironment) -> None:
    """Three steps ready together each send about 1.6 MiB. In one workflow task that passes Temporal's 4 MiB gRPC
    message limit, and Temporal terminates the run; paced, they go out in separate tasks (review focus 4)."""
    client, store = dev_env.client, MemoryStore()
    part = 800 * 1024
    g = G()
    g.settings = {
        "input_schema": strings("a", "b"),
        "outputs": {f"n{k}": ref(f"steps.t{k}.output.n") for k in range(3)},
    }
    for k in range(3):
        g.node(f"t{k}", "flow.transform@1", {"fields": {"n": cel(f"size(trigger.a) + size(trigger.b) + {k}")}})
    async with serving(client, store):
        handle = await start(client, store, g, {"a": "x" * part, "b": "y" * part})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {f"n{k}": 2 * part + k for k in range(3)})
    tasks = await cel_requests(handle)
    assert len(tasks) == 3 and len(set(tasks)) == 3
    assert await task_failures(handle) == []


FORCED = WorkflowTaskFailedCause.WORKFLOW_TASK_FAILED_CAUSE_FORCE_CLOSE_COMMAND
UNHANDLED = WorkflowTaskFailedCause.WORKFLOW_TASK_FAILED_CAUSE_UNHANDLED_COMMAND
NONDETERMINISM = WorkflowTaskFailedCause.WORKFLOW_TASK_FAILED_CAUSE_NON_DETERMINISTIC_ERROR
SERVER = "history-service"  # the identity a workflow task failed by the server itself carries


ACTIVITY_ENDS = ("activity_task_completed", "activity_task_failed", "activity_task_timed_out", "activity_task_canceled")


def _named(e: HistoryEvent, scheduled: dict[int, str]) -> str:
    """An event's kind, and the code name it concerns: an activity's type, a timer's id, a signal's name."""
    kind = EventType.Name(e.event_type).removeprefix("EVENT_TYPE_")
    for attrs in ACTIVITY_ENDS:
        if e.HasField(f"{attrs}_event_attributes"):
            return f"{kind} {scheduled.get(getattr(e, f'{attrs}_event_attributes').scheduled_event_id, '?')}"
    if e.HasField("timer_fired_event_attributes"):
        return f"{kind} {e.timer_fired_event_attributes.timer_id}"
    if e.HasField("workflow_execution_signaled_event_attributes"):
        return f"{kind} {e.workflow_execution_signaled_event_attributes.signal_name}"
    return kind


def unpermitted_task_failures(events: list[HistoryEvent]) -> list[str]:
    """#16's acceptance permits only the server's own force-close of a slow workflow task (too many events buffered
    during it: the server fails the task to record them, and the next task carries on), once a later task completed.
    Each other failed task: its cause, who failed it, and the events that arrived meanwhile (recorded after the
    failure, before the next task), by kind and code name."""
    scheduled = {e.event_id: e.activity_task_scheduled_event_attributes.activity_type.name for e in events
                 if e.HasField("activity_task_scheduled_event_attributes")}  # fmt: skip
    out = []
    for i, e in enumerate(events):
        if not e.HasField("workflow_task_failed_event_attributes"):
            continue
        failed, later = e.workflow_task_failed_event_attributes, events[i + 1 :]
        recovered = any(x.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED for x in later)
        if failed.cause == FORCED and failed.identity == SERVER and recovered:
            continue
        arrived = []
        for x in later:
            if x.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_SCHEDULED:
                break
            arrived.append(_named(x, scheduled))
        cause = WorkflowTaskFailedCause.Name(failed.cause).removeprefix("WORKFLOW_TASK_FAILED_CAUSE_")
        out.append(f"{cause} by {failed.identity}{'' if recovered else ', never recovered'}: arrived {arrived}")
    return out


async def continued_inputs(client: Client, handle: WorkflowHandle[Any, Any]) -> tuple[list[int], list[int]]:
    """Across a run's continue-as-new chain: each continued run's input, its encoded bytes as Temporal holds them; and
    every failed workflow task's cause."""
    sizes, failures, run_id = [], [], handle.first_execution_run_id
    while run_id:
        this, run_id = client.get_workflow_handle(handle.id, run_id=run_id), None
        async for e in this.fetch_history_events():
            if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED:
                failures.append(e.workflow_task_failed_event_attributes.cause)
            elif e.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW:
                continued = e.workflow_execution_continued_as_new_event_attributes
                sizes.append(sum(len(p.data) for p in continued.input.payloads))
                run_id = continued.new_execution_run_id
    return sizes, failures


def issue_16() -> G:
    """#16's reproduction: nested loops, 10 x 10, each inner iteration 200 parallel steps joined by one transform."""
    g = graph(n=cel("size(steps.o.output.items)"))
    g.node("o", "flow.loop@1", {"items": list(range(10)), "concurrency": 10, "collect": ref("item")})
    g.node("i", "flow.loop@1", {"items": list(range(10)), "concurrency": 10, "collect": ref("item")})
    g.edge("o", "i", "body")
    g.node("j", "flow.transform@1", {"fields": {"v": ref("item")}})
    for n in range(200):
        g.node(f"x{n}", "testkit.echo@1", {"value": ref("item")}).edge("i", f"x{n}", "body").edge(f"x{n}", "j")
    return g


async def replays(handle: WorkflowHandle[Any, Any]) -> list[HistoryEvent]:
    """The run's history, which replays as it ran (a command it doesn't make again fails the replay)."""
    history = await handle.fetch_history()
    replayer = Replayer(workflows=[RunGraph, LoopBatch], data_converter=FIXTURE_CONVERTER)
    await replayer.replay_workflow(WorkflowHistory.from_json(handle.id, history.to_json()))
    return list(history.events)


async def issue_16s_end(client: Client, store: MemoryStore, handle: WorkflowHandle[Any, Any]) -> list[HistoryEvent]:
    """#16's acceptance: its run ends `snapshot_too_large`, nothing continued, its history replays; its events."""
    from dewpoint.engine.runtime.size import SNAPSHOT_TOO_LARGE

    result = await asyncio.wait_for(handle.result(), 120)
    assert result.status == "failed" and result.error is not None and result.error["code"] == SNAPSHOT_TOO_LARGE
    assert store.runs[run_id_of(handle)].error_code == SNAPSHOT_TOO_LARGE
    assert (await continued_inputs(client, handle))[0] == []
    return await replays(handle)


async def test_issue_16s_run_too_large_to_carry_on_fails_never_its_task(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """#16 on the dev server (closed after 2b-1a and 2b-1b; the 2b-4b plan's M2 checks its acceptance): its
    reproduction's run, the snapshot bound lowered under its first snapshot, ends with `snapshot_too_large`, nothing
    continued, and its history replays. No workflow task failed, but the server's own force-close of a slow one, which
    load may cause and the next task recovers (the owner's ruling on the M2 diagnostic); any other is named with what
    arrived meanwhile. At its real bound it carries on, every iteration done, each continued input within
    `SNAPSHOT_MAX` (`tests/probes/test_engine_issues.py`, by hand: about 4 minutes)."""
    from dewpoint.engine.runtime import size

    monkeypatch.setattr(size, "SNAPSHOT_BYTES", 5_000)
    client, store = dev_env.client, MemoryStore()
    async with serving(client, store):
        handle = await start(client, store, issue_16(), checkpoint_events=300, drain_events=600)
        events = await issue_16s_end(client, store, handle)
    assert unpermitted_task_failures(events) == []


async def test_issue_16s_run_ends_the_same_through_the_servers_force_close_of_a_slow_task(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The case #16's acceptance permits, forced: the first four workflow tasks its steps' results reach are each held
    1.2 s, so more than the server's 100 buffered events arrive meanwhile, and the server fails such a task itself.
    The next task carries on: the run ends as it would, and its history replays. Each is held before its activation
    runs, so the SDK's 2 s deadlock bound times the activation alone: held inside it, the activation had 0.8 s left,
    which a busy CI runner overran (the worker's own deadlock failure beside the server's)."""
    from temporalio.worker import _workflow as running

    from dewpoint.engine.runtime import size

    monkeypatch.setattr(size, "SNAPSHOT_BYTES", 5_000)
    real, held = running._WorkflowWorker._handle_activation, []

    async def handled(self: Any, act: Any) -> None:
        if len(held) < 4 and sum(job.HasField("resolve_activity") for job in act.jobs) >= 10:
            held.append(len(act.jobs))
            await asyncio.sleep(1.2)  # the task held, its activation not yet started: no deadlock bound runs
        return await real(self, act)

    monkeypatch.setattr(running._WorkflowWorker, "_handle_activation", handled)
    client, store = dev_env.client, MemoryStore()
    async with serving(client, store):
        handle = await start(client, store, issue_16(), checkpoint_events=300, drain_events=600)
        events = await issue_16s_end(client, store, handle)
    forced = [e for e in events if e.HasField("workflow_task_failed_event_attributes")]
    assert held and forced, (held, forced)
    assert {(e.workflow_task_failed_event_attributes.cause, e.workflow_task_failed_event_attributes.identity)
            for e in forced} == {(FORCED, SERVER)}  # fmt: skip
    assert unpermitted_task_failures(events) == []


async def test_a_run_ending_as_its_running_activity_completes_cancels_it_and_ends(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """A root step fails while a loop's body step runs, and the body's activity completes while the workflow task
    that sees the failure is in flight. Forced, in order: the root fails only once the body runs; the body completes
    only once that task is held, before its activation runs; the task is held until the server no longer has the
    body's activity pending. The run ends, so it cancels the body's activity, which the worker can't know has completed
    (the server holds the completion back for the next task). The server records the cancel and then the completion;
    the body's step ends `cancelled`, the run `failed` with the root's error, and its history replays. Temporal's
    time-skipping test server refuses that cancel (`ACTIVITY_UNKNOWN for scheduledEventId=…`) and the run stalls
    there, its workflow task never completing: a test whose run may end as a quick activity completes needs this
    server."""
    from temporalio.worker import _workflow as running

    BODY = "testkit.slow_echo.v1"  # the body's activity type
    real, real_fail, real_echo = running._WorkflowWorker._handle_activation, FailN.run, SlowEcho.run
    runs: list[WorkflowHandle[Any, Any]] = []
    body_runs, root_held = asyncio.Event(), asyncio.Event()

    async def fail(self: FailN, ctx: StepContext, config: FailNConfig) -> Empty:
        await asyncio.wait_for(body_runs.wait(), 30)
        return await real_fail(self, ctx, config)

    async def echo(self: SlowEcho, ctx: StepContext, config: SlowEchoConfig) -> EchoOutput:
        body_runs.set()
        await asyncio.wait_for(root_held.wait(), 30)
        return await real_echo(self, ctx, config)

    async def completed(handle: WorkflowHandle[Any, Any], activity_type: str) -> None:
        for _ in range(200):
            pending = (await handle.describe()).raw_description.pending_activities
            if not any(p.activity_type.name == activity_type for p in pending):
                return
            await asyncio.sleep(0.05)
        raise AssertionError(f"{activity_type} never completed")

    def root_failed(act: Any) -> bool:  # the only activity that fails is the root's
        return any(j.HasField("resolve_activity") and j.resolve_activity.result.HasField("failed") for j in act.jobs)

    async def handled(self: Any, act: Any) -> None:
        if not root_held.is_set() and root_failed(act):
            root_held.set()  # the body may complete now
            await completed(runs[0], BODY)  # held, its activation not yet started
        return await real(self, act)

    monkeypatch.setattr(FailN, "run", fail)
    monkeypatch.setattr(SlowEcho, "run", echo)
    monkeypatch.setattr(running._WorkflowWorker, "_handle_activation", handled)
    client, store = dev_env.client, MemoryStore()
    g = graph().node("f", "testkit.fail_n@1", {"failures": 10}).node("l", "flow.loop@1", {"items": [0]})
    g.nodes[0]["options"]["max_attempts"] = 1
    g.node("e", "testkit.slow_echo@1", {"seconds": 0, "value": 1}).edge("l", "e", "body")
    async with serving(client, store):
        runs.append(handle := await start(client, store, g, {}))
        result = await asyncio.wait_for(handle.result(), 60)
        events = await replays(handle)
    assert (result.status, result.error["code"] if result.error else None) == ("failed", "testkit.transient")
    [body] = [e.event_id for e in events if e.activity_task_scheduled_event_attributes.activity_type.name == BODY]
    cancel = [
        e.event_id for e in events if e.activity_task_cancel_requested_event_attributes.scheduled_event_id == body
    ]
    done = [e.event_id for e in events if e.activity_task_completed_event_attributes.scheduled_event_id == body]
    assert len(cancel) == len(done) == 1 and cancel[0] < done[0], (cancel, done)  # the race happened, as forced
    assert not any(e.HasField("workflow_task_failed_event_attributes") for e in events)
    rows = {(r.node_key, r.iteration_key, r.attempt): (r.status, r.error_code) for r in store.steps(run_id_of(handle))}
    assert rows == {("f", "", 1): ("failed", "testkit.transient"), ("e", "l:0", 1): ("cancelled", None)}
    assert store.runs[run_id_of(handle)].status == "failed"


async def test_issue_18s_thousand_views_of_a_large_string_end_on_the_dev_server(dev_env: WorkflowEnvironment) -> None:
    """#18 at its real size on the dev server: 1,000 items each binding a 1.8 MiB string ended in a deadlocked workflow
    task, retried, the run without a result. It ends with the step's result (`input_too_large`: the binding set alone
    passes the request limit), no workflow task failed."""
    from tests.apps.worker.test_run_graph_binding import issue_18

    client, store = dev_env.client, MemoryStore()
    async with serving(client, store):
        handle = await start(client, store, issue_18(1_000), {"s": "x" * (1_800 * 1024)})
        result = await asyncio.wait_for(handle.result(), 120)
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"}), result
    assert await task_failures(handle) == []


async def test_issue_26s_filter_over_a_large_plain_string_ends_on_the_dev_server(dev_env: WorkflowEnvironment) -> None:
    """#26 at its real size on the dev server: 1,000 items each sending a copy of a 65,500-character string filled the
    run's history until Temporal terminated it. It ends with the step's result, every item evaluated."""
    from tests.apps.worker.test_run_graph_binding import issue_26

    client, store = dev_env.client, MemoryStore()
    async with serving(client, store):
        handle = await start(client, store, issue_26(1_000), {"s": "x" * 65_500})
        result = await asyncio.wait_for(handle.result(), 120)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 1_000, "code": "none"}), result
    assert await task_failures(handle) == []


async def test_a_fan_out_sharing_cant_shrink_fails_its_step_before_temporals_history_limit(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """#26's backstop (D7: for other large fan-outs): #26's reproduction with every set carrying its own copy, as sets
    whose values aren't shared do. About 64 MB of requests: Temporal terminated the run at its 50 MiB history limit
    (after 30 requests). The step's requests stop once the run's history would pass `HISTORY_GUARD` (32 MiB): its
    remaining items fail with `history_too_large`, the step with them, and the run ends, never terminated."""
    from dewpoint.engine.runtime import execution
    from tests.apps.worker.test_run_graph_binding import issue_26, request_bytes

    monkeypatch.setattr(execution, "SHARED_REPEAT", 1 << 62)
    client, store = dev_env.client, MemoryStore()
    async with serving(client, store):
        handle = await start(client, store, issue_26(1_000), {"s": "x" * 65_500})
        result = await asyncio.wait_for(handle.result(), 120)
    assert (result.status, result.outputs) == ("succeeded", {"kept": -1, "code": "history_too_large"}), result
    sent = await request_bytes(handle)
    print(f"backstop: {len(sent)} requests, {sum(sent):,} bytes sent")
    assert sum(sent) <= execution.HISTORY_GUARD


async def test_an_execution_drains_by_its_historys_bytes_whatever_the_server_suggests(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The review of the M2 checkpoint (M6): the history guard's margin relied on Temporal's suggestion to continue as
    new (a server setting, about 4 MB by default) to stop an execution's other sends; the engine drained by events
    only. It drains once an execution has added `DRAIN_BYTES` of history too (its carried-in state counted out, so a
    continued run never drains at once): lowered to 200 KB, a chain of 20 steps carrying 20 KB each continues as new,
    far below the event thresholds, and ends."""
    from dewpoint.engine.runtime import execution

    monkeypatch.setattr(execution, "DRAIN_BYTES", 200_000)
    client, store = dev_env.client, MemoryStore()
    g = graph(last=ref("steps.x19.output.value"))
    previous = None
    for n in range(20):
        g.node(f"x{n}", "testkit.echo@1", {"value": "v" * 20_000})
        if previous:
            g.edge(previous, f"x{n}")
        previous = f"x{n}"
    async with serving(client, store):
        handle = await start(client, store, g)
        result = await asyncio.wait_for(handle.result(), 120)
    assert result.status == "succeeded", result
    sizes, failures = await continued_inputs(client, handle)
    assert sizes and failures == []


async def suspended(handle: WorkflowHandle[Any, Any]) -> None:
    """Until the run waits on a durable timer (in real time): its workflow task is done, and its worker caches it."""
    for _ in range(200):
        async for e in handle.fetch_history_events():
            if e.event_type == EventType.EVENT_TYPE_TIMER_STARTED:
                return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{handle.id} never waited on a timer")


def left_behind(run_id: str, workflow_type: str) -> Any:
    """The run's own coroutine (or its batch's), still in memory after its worker stopped: suspended where its drive
    loop waits."""
    found = [
        o
        for o in gc.get_objects()
        if inspect.iscoroutine(o)
        and o.cr_code.co_qualname == f"{workflow_type}.run"
        and o.cr_frame is not None
        and getattr(o.cr_frame.f_locals.get("self"), "run_id", None) == run_id
    ]
    assert len(found) == 1, found
    return found[0]


def sleeping_batch() -> G:
    """A loop past one batch (as `test_a_terminated_batch_fails_its_loop...`): its batch, a child, sleeps."""
    g = graph().node("l", "flow.loop@1", {"items": list(range(101))}).node("d", "flow.delay@1", {"duration_s": 3600})
    return g.edge("l", "d", "body")


@pytest.mark.parametrize("workflow_type", ["RunGraph", "LoopBatch"])
async def test_a_run_a_stopped_worker_left_in_memory_never_acts_in_another_run(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, workflow_type: str
) -> None:  # fmt: skip
    """The trigger of the `fdb30fb` suite's #16 failure (2b-4b M2). A worker's shutdown evicts none of the runs it
    cached: each stays in memory, its coroutine suspended in the drive loop. Closed later (by the garbage collector, on
    whichever thread it ran, here at once) while another run's workflow task was active, the drive loop's cleanup
    awaited, the close raised "coroutine ignored GeneratorExit", and the run took that for a bug of its own: it logged
    `run_internal_error` and projected an end through the workflow APIs, which acted in the active run. That run's
    history then held a command its own replay never makes, and its next replay failed (nondeterminism). A run being
    closed now ends at once: nothing logged, nothing sent, the active run's history its own. A batch the same."""
    from temporalio import workflow

    from dewpoint.engine.runtime import execution

    client, stale_store, store = dev_env.client, MemoryStore(), MemoryStore()
    async with serving(client, stale_store):
        if workflow_type == "RunGraph":
            stale = await start(client, stale_store, sleeper(), {})
            await suspended(stale)
        else:
            stale = await start(client, stale_store, sleeping_batch(), {})
            await suspended(client.get_workflow_handle(await child_started(stale)))
    zombie = left_behind(run_id_of(stale), workflow_type)
    raised: list[str] = []
    real = execution.Execution._queue_settled

    def settled(self: Any) -> Any:
        if not raised and workflow.info().workflow_type == "RunGraph":  # inside the active run's workflow task
            raised.append("closed")
            try:
                zombie.close()
            except BaseException as e:  # noqa: BLE001  # what closing it raised, if anything: the finding
                raised.append(type(e).__name__)
        return real(self)

    monkeypatch.setattr(execution.Execution, "_queue_settled", settled)
    g = graph(v=ref("steps.e.output.value")).node("e", "testkit.echo@1", {"value": 1})
    caplog.set_level(logging.WARNING)
    async with serving(client, store):
        handle = await start(client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"v": 1}), result
    try:
        await replays(handle)
        replayed = "clean"
    except Exception as e:  # noqa: BLE001  # how its replay failed: the finding
        replayed = type(e).__name__
    logged = [r.getMessage().split(" ", 1)[0] for r in caplog.records if "_internal_error" in r.getMessage()]
    found = {"closing": raised, "logged": logged, "stale_rows": run_id_of(stale) in store.runs, "replay": replayed}
    assert found == {"closing": ["closed"], "logged": [], "stale_rows": False, "replay": "clean"}


def event(event_id: int, kind: str, **attrs: Any) -> HistoryEvent:
    """A history event of `kind` (its EventType name, without the prefix), with its attributes' fields."""
    e = HistoryEvent(event_id=event_id, event_type=EventType.Value(f"EVENT_TYPE_{kind}"))
    for field, value in attrs.items():
        target = getattr(e, f"{kind.lower()}_event_attributes")
        if field == "activity_type":
            target.activity_type.name = value
        else:
            setattr(target, field, value)
    return e


def task(start: int, failed: tuple[int, str] | None = None) -> list[HistoryEvent]:
    """A workflow task from `start`: completed, or failed with (cause, identity)."""
    out = [event(start, "WORKFLOW_TASK_SCHEDULED"), event(start + 1, "WORKFLOW_TASK_STARTED")]
    if failed is None:
        return [*out, event(start + 2, "WORKFLOW_TASK_COMPLETED")]
    return [*out, event(start + 2, "WORKFLOW_TASK_FAILED", cause=failed[0], identity=failed[1])]


@pytest.mark.parametrize(
    ("history", "found"),
    [
        (task(1), []),
        ([*task(1, (FORCED, SERVER)), event(4, "TIMER_FIRED", timer_id="7"), *task(5)], []),
        ([*task(1), *task(4, (FORCED, SERVER))], [f"FORCE_CLOSE_COMMAND by {SERVER}, never recovered: arrived []"]),
        ([*task(1, (FORCED, "worker-a")), *task(4)], ["FORCE_CLOSE_COMMAND by worker-a: arrived []"]),
        (
            [
                event(1, "ACTIVITY_TASK_SCHEDULED", activity_type="dewpoint.project"),
                *task(2, (UNHANDLED, SERVER)),
                event(5, "TIMER_FIRED", timer_id="9"),
                event(6, "ACTIVITY_TASK_COMPLETED", scheduled_event_id=1),
                *task(7),
            ],
            [f"UNHANDLED_COMMAND by {SERVER}: arrived {['TIMER_FIRED 9', 'ACTIVITY_TASK_COMPLETED dewpoint.project']}"],
        ),
        ([*task(1, (NONDETERMINISM, "worker-a")), *task(4)], ["NON_DETERMINISTIC_ERROR by worker-a: arrived []"]),
    ],
    ids=["none", "force_close_recovered", "force_close_unrecovered", "force_close_by_a_worker", "unhandled", "nde"],
)
def test_issue_16s_acceptance_permits_only_a_recovered_force_close_by_the_server(
    history: list[HistoryEvent], found: list[str]
) -> None:
    """The owner's ruling on the 2b-4b M2 diagnostic: under load the server may fail a slow workflow task itself, too
    many events buffered during it (`FORCE_CLOSE_COMMAND`, by `history-service`), and the next task carries on. #16's
    acceptance permits that alone, once a later task completed; any other failed task fails it, named with what
    arrived meanwhile (the events recorded after the failure, before the next task: kinds and code names only)."""
    assert unpermitted_task_failures(history) == found


async def test_a_left_behind_runs_pending_units_are_cancelled_when_it_is_closed(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # fmt: skip
    """The owner's review of `8206a3e`: closed, a left-behind run skipped its drive loop's whole cleanup, its clock and
    its outstanding units with it. It cancels them now, without awaiting (nothing it awaited could complete there), and
    still acts on nothing in the active run: here a step's activity and a timer were outstanding."""
    from temporalio import workflow

    from dewpoint.engine.runtime import execution

    client, stale_store, store = dev_env.client, MemoryStore(), MemoryStore()
    stale_graph = graph().node("s", "testkit.slow@1", {"seconds": 600}).node("d", "flow.delay@1", {"duration_s": 3600})
    async with serving(client, stale_store, grace_s=1):
        stale = await start(client, stale_store, stale_graph, {})
        await suspended(stale)
    zombie = left_behind(run_id_of(stale), "RunGraph")
    drive = zombie.cr_await  # the drive loop's own coroutine, where the run waits
    units = {k: t for k, t in drive.cr_frame.f_locals["tasks"].items() if k[0] not in ("project", "cancelled")}
    clock = drive.cr_frame.f_locals["clock"]
    assert {k[0] for k in units} == {"step"} and len(units) == 2 and not clock.done(), units
    raised: list[str] = []
    real = execution.Execution._queue_settled

    def settled(self: Any) -> Any:
        if not raised and workflow.info().workflow_type == "RunGraph":
            raised.append("closed")
            try:
                zombie.close()
            except BaseException as e:  # noqa: BLE001
                raised.append(type(e).__name__)
        return real(self)

    monkeypatch.setattr(execution.Execution, "_queue_settled", settled)
    caplog.set_level(logging.WARNING)
    async with serving(client, store):
        handle = await start(
            client, store, graph(v=ref("steps.e.output.value")).node("e", "testkit.echo@1", {"value": 1}), {}
        )
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"v": 1}), result
    cancelled = {"clock": clock.cancelling() > 0, "units": sorted(t.cancelling() > 0 for t in units.values())}
    logged = [r.getMessage().split(" ", 1)[0] for r in caplog.records if "_internal_error" in r.getMessage()]
    assert (raised, cancelled, logged) == (["closed"], {"clock": True, "units": [True, True]}, [])
    await replays(handle)
