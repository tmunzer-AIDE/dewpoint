# SPDX-License-Identifier: Apache-2.0
"""A bug in a run's own workflow code, an exception it doesn't expect (the owner's third recovery design, 2b-4b M2):
it fails the run's execution, non-retryable and sanitized, in the workflow task that raised it, with nothing recorded
first. Whoever sees the execution close records the run's end: the reconciler for a root run
(`tests/apps/dispatcher/test_reconcile_runs.py`), the parent for a sub-run or a batch.

Recorded as an `internal_error` end instead, a bug that only the live execution raised (as the `fdb30fb` suite's did)
left commands its replay never makes, and the run's next replay failed on every retry. Failed in the same task, the
failure either stands (the execution is closed, nothing replays it) or its task's completion is refused, and the replay,
which doesn't raise, takes the run's own path."""

import asyncio
import threading
from collections.abc import Callable
from typing import Any

import pytest
from temporalio import workflow
from temporalio.api.enums.v1 import EventType, WorkflowTaskFailedCause
from temporalio.client import WorkflowExecutionStatus, WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from dewpoint.core.runs.service import OUTCOME_UNCONFIRMED
from dewpoint.engine.runtime import execution
from dewpoint.engine.runtime.activities import UnconfirmedBatch
from dewpoint.engine.runtime.execution import INTERNAL_ERROR, SUBFLOW_GRANT
from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, workers
from tests.apps.worker.test_real_server import graph, replays, serving, suspended
from tests.support.graphs import G, nid, ref

CANARY = "canary-in-a-bug-5f1c"  # what the bug's own text quotes: the run's data, say
RUN_BUG = "The interpreter failed (RuntimeError); the worker's log has the details."
BATCH_BUG = "The batch failed (RuntimeError); the worker's log has the details."


def bug_in(monkeypatch: pytest.MonkeyPatch, chosen: Callable[[execution.Execution], bool]) -> list[str]:
    """Every run `chosen` picks raises, in its drive loop, an exception quoting CANARY: once it has started. What
    raised, by workflow type."""
    raised: list[str] = []
    real = execution.Execution._queue_settled

    def settled(self: execution.Execution) -> Any:
        if chosen(self):
            raised.append(workflow.info().workflow_type)
            raise RuntimeError(f"no queue for {CANARY}")
        return real(self)

    monkeypatch.setattr(execution.Execution, "_queue_settled", settled)
    return raised


def echo() -> G:
    return graph(v=ref("steps.e.output.value")).node("e", "testkit.echo@1", {"value": 1})


async def test_a_bug_fails_its_runs_execution_sanitized_and_for_good(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:  # fmt: skip
    """The run's execution fails, non-retryable, with a message of the engine's own (the exception's type), no cause
    and none of the exception's text, in Temporal or the log; its workflow tasks never fail; nothing projected its
    end (whoever sees the execution close records it)."""
    bug_in(monkeypatch, lambda self: workflow.info().workflow_type == "RunGraph")
    store = MemoryStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, echo(), {})
        with pytest.raises(WorkflowFailureError) as failed:
            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    cause = failed.value.cause
    assert isinstance(cause, ApplicationError)
    assert (cause.type, cause.non_retryable, cause.message, cause.cause) == (INTERNAL_ERROR, True, RUN_BUG, None)
    assert CANARY not in (cause.failure.stack_trace if cause.failure else "")
    assert (await handle.describe()).status == WorkflowExecutionStatus.FAILED
    kinds = [e.event_type async for e in handle.fetch_history_events()]
    assert kinds.count(EventType.EVENT_TYPE_WORKFLOW_EXECUTION_FAILED) == 1
    assert EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED not in kinds
    assert CANARY not in (await handle.fetch_history()).to_json() + caplog.text
    end = store.runs.get(run_id_of(handle))
    assert end is None or end.status == "running"


async def test_a_bug_only_the_live_execution_raises_never_ends_its_run_when_its_tasks_completion_is_refused(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The `fdb30fb` suite's case, as the design meets it: an exception the live execution raised once, its replay
    never. Here its workflow task's completion, failing the execution, is refused: an event arrived meanwhile (a
    signal), so the server fails the task (`UnhandledCommand`) and the run's next task replays its history. The
    replay doesn't raise: the run takes its own path and succeeds, and its history replays."""
    entered, sent = threading.Event(), threading.Event()
    once: list[bool] = []

    def chosen(self: execution.Execution) -> bool:
        if once or workflow.unsafe.is_replaying() or workflow.info().workflow_type != "RunGraph":
            return False
        once.append(True)
        entered.set()
        sent.wait(1.5)  # the signal recorded before this task completes (under the SDK's 2 s deadlock bound)
        return True

    raised = bug_in(monkeypatch, chosen)
    client, store = dev_env.client, MemoryStore()
    async with serving(client, store):
        handle = await start(client, store, echo(), {})
        assert await asyncio.to_thread(entered.wait, 30)
        await handle.signal("nudge")  # no handler: the event alone matters
        sent.set()
        result = await asyncio.wait_for(handle.result(), 60)
    assert raised == ["RunGraph"]
    assert (result.status, result.outputs) == ("succeeded", {"v": 1}), result
    events = await replays(handle)
    failed = "workflow_task_failed_event_attributes"
    failures = [e.workflow_task_failed_event_attributes.cause for e in events if e.HasField(failed)]
    assert failures == [WorkflowTaskFailedCause.WORKFLOW_TASK_FAILED_CAUSE_UNHANDLED_COMMAND]
    assert not [e for e in events if e.event_type == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_FAILED]


async def test_a_sub_flows_bug_fails_its_step_and_its_parent_records_its_end_and_whole_grant(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """A sub-run's execution failed by its bug: its parent's step fails `internal_error` with the bug's sanitized
    message, the parent writes the sub-run's end (it wrote none), and the sub-run's whole grant stays counted, as a
    terminated sub-run's does; the parent carries on and ends as its policy says."""
    bug_in(monkeypatch, lambda self: workflow.info().workflow_type == "RunGraph" and self.parent is not None)
    store = MemoryStore()
    g = graph(code=ref("steps.r.error.code", default="none"), message=ref("steps.r.error.message", default="none"))
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(echo()))}, on_error="continue")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert (result.status, result.outputs) == ("succeeded", {"code": INTERNAL_ERROR, "message": RUN_BUG}), result
    assert result.iterations == SUBFLOW_GRANT
    [sub] = [s for s in store.starts if s != run_id_of(handle)]
    assert (store.runs[sub].status, store.runs[sub].error_code, store.runs[sub].iterations) == (
        "failed", INTERNAL_ERROR, SUBFLOW_GRANT)  # fmt: skip
    assert store.runs[run_id_of(handle)].status == "succeeded"


async def test_a_batchs_bug_fails_its_loop_with_its_whole_grant_used(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """A batch's execution failed by its bug: its loop fails `internal_error` with the bug's sanitized message, and the
    batch's whole grant stays used, as a terminated batch's does."""
    bug_in(monkeypatch, lambda self: workflow.info().workflow_type == "LoopBatch")
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"), message=ref("steps.l.error.message", default="none"))
    g.node("l", "flow.loop@1", {"items": list(range(101))}, on_error="continue").node(
        "x", "testkit.echo@1", {"value": ref("item")}
    )
    g.edge("l", "x", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert (result.status, result.outputs) == ("succeeded", {"code": INTERNAL_ERROR, "message": BATCH_BUG}), result
    assert result.iterations == 100


async def test_a_root_runs_bug_cancels_its_sub_run_which_records_its_own_end(
    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """A root run's execution failed while a sub-run sleeps: Temporal asks the sub-run to cancel (its parent close
    policy), and the sub-run ends `cancelled` (its result: a run reports its cancel back), writing its own end; nothing
    is left running."""
    sleeping: list[bool] = []

    def chosen(self: execution.Execution) -> bool:
        return bool(sleeping) and self.parent is None and workflow.info().workflow_type == "RunGraph"

    bug_in(monkeypatch, chosen)
    client, store = dev_env.client, MemoryStore()
    sleeper = graph().node("d", "flow.delay@1", {"duration_s": 3600})
    g = graph().node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sleeper))})
    g.node("s", "flow.delay@1", {"duration_s": 2})  # the root's drive loop runs again after the sub-run sleeps
    async with serving(client, store):
        handle = await start(client, store, g, {})
        [sub] = [s for s in await _children(handle)]
        await suspended(client.get_workflow_handle(sub))
        sleeping.append(True)
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 60)
        child = client.get_workflow_handle(sub)
        for _ in range(100):
            if (await child.describe()).status != WorkflowExecutionStatus.RUNNING:
                break
            await asyncio.sleep(0.1)
    assert (await child.describe()).status == WorkflowExecutionStatus.COMPLETED  # a run reports its cancel back
    assert (await child.result())["status"] == "cancelled"  # untyped: as its JSON
    assert store.runs[run_id_of(sub)].status == "cancelled"


async def _children(handle: Any) -> list[str]:
    for _ in range(200):
        found = [
            e.child_workflow_execution_started_event_attributes.workflow_execution.workflow_id
            async for e in handle.fetch_history_events()
            if e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED
        ]
        if found:
            return found
        await asyncio.sleep(0.1)
    raise AssertionError("no child started")


def running(store: MemoryStore, run_id: str, prefix: str) -> bool:
    """A row of `run_id` under `prefix` (an iteration key, or "" for the run's own steps) is persisted `running`."""
    return any(r.run_id == run_id and r.status == "running" and r.iteration_key.startswith(prefix)
               for r in list(store.rows.values()))  # fmt: skip


async def test_a_batchs_bug_closes_its_own_iterations_running_rows_and_no_siblings(
    own_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The owner's ruling: a batch shares its run's id, so its parent closes that batch's iterations alone. Two loops
    run in batches side by side (two items a batch); `a`'s first batch fails on a bug once its rows are persisted
    `running`. The parent closes exactly `a:0` and `a:1`: a row persisted `running` there ends `outcome_unconfirmed`,
    one recorded keeps its outcome, and `b`'s rows end with their own."""
    from dewpoint.engine.runtime import nodes

    monkeypatch.setattr(nodes, "INLINE_ITEMS", 2)
    store = MemoryStore()

    def chosen(self: execution.Execution) -> bool:
        info = workflow.info()
        batch = info.workflow_type == "LoopBatch" and str(nid("a")) in info.workflow_id
        return batch and running(store, self.run_id, "a:")

    bug_in(monkeypatch, chosen)
    g = graph(code=ref("steps.a.error.code", default="none"))
    g.node("a", "flow.loop@1", {"items": [0, 1, 2]}, on_error="continue").node("x", "testkit.slow@1", {"seconds": 5})
    g.node("b", "flow.loop@1", {"items": [0, 1, 2]}).node("y", "testkit.echo@1", {"value": ref("item")})
    g.edge("a", "x", "body").edge("b", "y", "body")
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert (result.status, result.outputs) == ("succeeded", {"code": INTERNAL_ERROR}), result
    assert store.closed_batches == [(run_id_of(handle), UnconfirmedBatch("", "a", 0, 2))]
    rows = {r.iteration_key: (r.status, r.error_code) for r in store.steps(run_id_of(handle)) if r.node_key in "xy"}
    batch = {k: v for k, v in rows.items() if k.startswith("a:")}  # each recorded, or closed unconfirmed: none running
    assert set(batch) <= {"a:0", "a:1"} and ("failed", OUTCOME_UNCONFIRMED) in batch.values(), batch
    assert set(batch.values()) <= {("succeeded", None), ("failed", OUTCOME_UNCONFIRMED)}, batch
    assert {k: v for k, v in rows.items() if k.startswith("b:")} == {f"b:{i}": ("succeeded", None) for i in range(3)}


async def test_a_sub_runs_bug_leaves_none_of_its_steps_running(
    own_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The parent writes the end of a sub-run its bug failed, and that end leaves none of the sub-run's steps
    `running`: a step persisted `running` ends `outcome_unconfirmed`; one whose end was never projected is absent."""
    store = MemoryStore()

    def chosen(self: execution.Execution) -> bool:
        return self.parent is not None and running(store, self.run_id, "")

    bug_in(monkeypatch, chosen)
    sub = graph().node("s", "testkit.slow@1", {"seconds": 5}).node("t", "testkit.slow@1", {"seconds": 1})  # t wakes it
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sub))}, on_error="continue")
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert (result.status, result.outputs) == ("succeeded", {"code": INTERNAL_ERROR}), result
    [sub_run] = [s for s in store.starts if s != run_id_of(handle)]
    rows = {r.node_key: (r.status, r.error_code) for r in store.steps(sub_run)}
    assert rows["s"] == ("failed", OUTCOME_UNCONFIRMED)
    assert rows.get("t", ("succeeded", None)) == ("succeeded", None)  # projected before the bug, or absent


async def test_a_runs_bug_starts_no_failure_handler(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> None:
    """The owner's ruling: an interpreter's crash is an operational failure, not the graph's, and a closed run can't
    supervise a handler's grant and lifetime. A run its bug failed starts no failure handler, though it has one."""
    bug_in(monkeypatch, lambda self: workflow.info().workflow_type == "RunGraph" and self.parent is None)
    store = MemoryStore()
    g = echo()
    g.settings["failure_handler"] = str(store.publish(echo()))
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    kinds = [e.event_type async for e in handle.fetch_history_events()]
    assert EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED not in kinds
    assert [s.kind for s in store.starts.values()] == []


async def test_a_runs_bug_carries_the_iterations_its_interpreter_counted(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The owner's ruling: its end must not show zero for work it used. The failure carries its interpreter's count
    (a loop of three, done before the bug), for whoever records the end to show, unverified."""
    bug_in(monkeypatch, lambda self: workflow.info().workflow_type == "RunGraph" and self.sched.iterations >= 3)
    store = MemoryStore()
    g = graph().node("l", "flow.loop@1", {"items": [0, 1, 2]}).node("x", "testkit.echo@1", {"value": ref("item")})
    g.edge("l", "x", "body").node("d", "flow.delay@1", {"duration_s": 60}).edge("l", "d", "done")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        with pytest.raises(WorkflowFailureError) as failed:
            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    cause = failed.value.cause
    assert isinstance(cause, ApplicationError) and list(cause.details) == [{"iterations": 3}]


async def test_an_ordinary_failure_keeps_its_rows_as_projected(own_env: WorkflowEnvironment) -> None:
    """The owner's ruling: ordinary failures are untouched. A step fails, its sibling (still working) is cancelled, the
    run fails: each row says so, none is `outcome_unconfirmed`."""
    store = MemoryStore()
    g = graph().node("s", "testkit.slow@1", {"seconds": 1}).node("f", "flow.fail@1", {"message": "it went wrong"})
    g.edge("s", "f").node("d", "testkit.slow@1", {"seconds": 30})
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "failed", result
    statuses = {r.node_key: r.status for r in store.steps(run_id_of(handle))}
    assert statuses == {"s": "succeeded", "f": "failed", "d": "cancelled"}
    assert OUTCOME_UNCONFIRMED not in {r.error_code for r in store.steps(run_id_of(handle))}
