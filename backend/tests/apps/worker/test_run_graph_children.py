# SPDX-License-Identifier: Apache-2.0
"""Children (spec §6, 2a-3b): loops over more than 100 items run in batches of child workflows, a `run_workflow`
step runs its pinned version as a run of its own, a failed run runs its failure handler once, and every child draws
its iterations from one budget per logical run."""

import asyncio
import dataclasses
import json
from datetime import timedelta
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner

from dewpoint.engine.runtime import execution
from dewpoint.engine.runtime import workflow as run_graph
from dewpoint.engine.runtime.activities import ProjectInput, VersionData
from dewpoint.engine.runtime.scheduler import Scheduler
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.support.graphs import G, cel, ref

ECHO, LOOP, FILTER, RUN, FAIL = "testkit.echo@1", "flow.loop@1", "flow.filter@1", "flow.run_workflow@1", "flow.fail@1"
LISTS = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}
NUMBER = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


def graph(schema: dict[str, Any] | None = None, **outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": schema or LISTS, "outputs": outputs}
    return g


async def finished(env: WorkflowEnvironment, store: MemoryStore, g: G, trigger: dict[str, Any]) -> tuple[Any, Any]:
    async with workers(env.client, store):
        handle = await start(env.client, store, g, trigger)
        result = await asyncio.wait_for(handle.result(), 120)
    return handle, result


async def children_started(handle: Any) -> int:
    history = await handle.fetch_history()
    return sum(e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED for e in history.events)


async def test_a_loop_over_more_than_a_hundred_items_runs_in_batches_and_collects_everything(
    env: WorkflowEnvironment,
) -> None:
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"), count=ref("steps.l.output.count"))
    g.node("a", ECHO, {"value": "from outside"}).node("b", ECHO, {"value": "never read"})
    g.node("l", LOOP, {"items": list(range(250)), "concurrency": 3, "collect": ref("item")})
    g.node("x", ECHO, {"value": ref("steps.a.output.value")}).edge("a", "b").edge("b", "l").edge("l", "x", "body")
    handle, result = await finished(env, store, g, {})
    assert result.status == "succeeded" and result.outputs == {"items": list(range(250)), "count": 250}
    assert result.iterations == 250 and await children_started(handle) == 3  # batches of 100, 100 and 50
    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
    assert sorted(r.iteration_key for r in rows) == sorted(f"l:{i}" for i in range(250))  # the inline keys
    assert {(r.status, r.output_preview["value"]) for r in rows} == {("succeeded", "from outside")}
    history = await handle.fetch_history()
    batches = [
        json.loads(e.start_child_workflow_execution_initiated_event_attributes.input.payloads[0].data)
        for e in history.events
        if e.HasField("start_child_workflow_execution_initiated_event_attributes")
    ]
    assert all(set(b["outer"][0]["results"]) == {"a"} for b in batches)  # only what the body reads goes along


async def test_a_secret_a_batch_learned_is_masked_in_its_parent_too(env: WorkflowEnvironment) -> None:
    """A batch returns the sensitive values it learned: the parent masks them where they reappear, as it would have
    learned them inline."""
    store = MemoryStore()
    g = graph()
    g.node("l", LOOP, {"items": list(range(101)), "collect": ref("steps.s.output.secret_value")})
    g.node("s", "testkit.sensitive@1").node("e", ECHO, {"value": ref("steps.l.output.items")})
    g.edge("l", "s", "body").edge("l", "e", "done")
    handle, result = await finished(env, store, g, {})
    assert result.status == "succeeded"
    [echoed] = [r for r in store.steps(handle.id) if r.node_key == "e"]
    assert "s3cr3t-value" not in json.dumps(echoed.output_preview) and "[redacted]" in json.dumps(echoed.output_preview)


@pytest.mark.parametrize(("policy", "status"), [("continue", "succeeded"), ("stop", "failed")])
async def test_a_failed_item_in_a_batch_follows_the_loops_policy(
    env: WorkflowEnvironment, policy: str, status: str
) -> None:
    store = MemoryStore()
    g = graph(failures=ref("steps.l.output.failures", default=None))
    config = {"items": list(range(150)), "on_item_error": policy}
    g.node("l", LOOP, config).node(
        "s", "testkit.ambiguous_send@1", {"outcome": cel("item == 120 ? 'rejected' : 'sent'")}
    )
    g.edge("l", "s", "body")
    _, result = await finished(env, store, g, {})
    assert result.status == status
    if policy == "continue":
        assert [f["index"] for f in result.outputs["failures"]] == [120]  # in the second batch, by its own index
    else:
        assert result.error["code"] == "testkit.rejected"


async def test_an_item_that_fails_in_a_batch_while_a_sibling_runs_cancels_only_that_sibling(
    env: WorkflowEnvironment,
) -> None:
    store = MemoryStore()
    g = graph(failures=ref("steps.l.output.failures"))
    g.node("l", LOOP, {"items": list(range(150)), "on_item_error": "continue", "concurrency": 10})
    g.node("f", "testkit.ambiguous_send@1", {"outcome": cel("item == 120 ? 'rejected' : 'sent'")})
    g.node("d", "flow.delay@1", {"duration_s": cel("item == 120 ? 3600 : 0")})
    g.edge("l", "f", "body").edge("l", "d", "body")
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.iterations) == ("succeeded", 150)
    assert [f["index"] for f in result.outputs["failures"]] == [120]
    info = await handle.describe()
    assert info.close_time and info.close_time - info.start_time < timedelta(hours=1)  # the delay was cancelled


async def test_a_fail_node_inside_a_batch_ends_the_whole_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph()
    g.node("l", LOOP, {"items": list(range(150))})
    g.node("f", FAIL, {"message": "item 130 is bad"}).node("e", ECHO)
    g.node("i", "flow.if@1", {"condition": cel("item == 130")})
    g.edge("l", "i", "body").edge("i", "f", "true").edge("i", "e", "false")
    _, result = await finished(env, store, g, {})
    assert (result.status, result.error["code"], result.error["message"]) == (
        "failed",
        "workflow_failed",
        "item 130 is bad",
    )


def doubler() -> G:
    """A sub-flow: doubles its input."""
    g = graph(NUMBER, double=ref("steps.t.output.double"))
    g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    return g


async def test_a_sub_flow_is_a_run_of_its_own_and_its_outputs_are_the_steps_output(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    sub = store.publish(doubler())
    g = graph(result=ref("steps.r.output.double"))
    g.node("r", RUN, {"workflow_id": str(sub), "input": {"n": 21}})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.outputs) == ("succeeded", {"result": 42})
    [(child, row)] = store.starts.items()
    step = next(n["id"] for n in g.nodes if n["key"] == "r")
    assert (row.kind, row.parent_run_id, row.parent_step_id, row.parent_iteration_key) == (
        "subflow",
        handle.id,
        step,
        "",
    )
    assert store.runs[child].status == "succeeded"
    assert [r.node_key for r in store.steps(child)] == ["t"]  # the sub-flow's steps are its own run's


async def test_a_failed_sub_flow_fails_its_step_under_the_steps_error_policy(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    broken = graph({"type": "object"})
    broken.node("f", FAIL, {"message": "nope"})
    sub = store.publish(broken)
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub)}, on_error="continue")
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs) == ("succeeded", {"code": "workflow_failed"})


async def test_a_failed_run_runs_its_failure_handler_once_with_the_error(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    handler = graph({"type": "object", "properties": {"error": {"type": "object"}}})
    handler.node("h", ECHO, {"value": ref("trigger.error.code", default="?")})
    handler_id = store.publish(handler)
    g = graph()
    g.settings["failure_handler"] = str(handler_id)
    g.node("f", FAIL, {"message": "it went wrong"})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.error["code"]) == ("failed", "workflow_failed")  # the handler changes nothing
    [(child, row)] = store.starts.items()
    assert (row.kind, row.parent_run_id, row.parent_step_id) == ("failure_handler", handle.id, None)
    assert store.runs[child].status == "succeeded"
    [echoed] = store.steps(child)
    assert echoed.output_preview == {"value": "workflow_failed"}


async def test_a_sub_flow_asks_for_more_than_its_first_grant(env: WorkflowEnvironment) -> None:
    """Its initial grant is 1,000 iterations; a filter over 1,200 items asks its parent for the rest."""
    store = MemoryStore()
    sub = graph(kept=ref("steps.k.output.count"))
    sub.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("item % 2 == 0")})
    sub_id = store.publish(sub)
    g = graph(kept=ref("steps.r.output.kept"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": list(range(1_200))}})
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"kept": 600}, 1_200)


async def test_no_premature_rejection_one_busy_child_among_ten(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §10: with 10 child slots and one busy child, that child can use nearly the whole budget. With a cap of
    300, ten sub-flows run at once; nine filter 1 item, one filters 250, and nothing is refused."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 300)
    store = MemoryStore()
    sub = graph(n=ref("steps.k.output.count"))
    sub.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")})
    sub_id = store.publish(sub)
    g = graph(counts=ref("steps.l.output.items"))
    lists = [[0]] * 4 + [list(range(250))] + [[0]] * 5
    g.node("l", LOOP, {"items": lists, "concurrency": 10, "collect": ref("steps.r.output.n")})
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": ref("item")}}).edge("l", "r", "body")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 120)
    assert result.status == "succeeded", result.error
    assert result.outputs == {"counts": [1, 1, 1, 1, 250, 1, 1, 1, 1, 1]}
    assert result.iterations == 10 + 9 + 250


async def test_a_need_waits_for_an_asking_sub_flow_that_holds_enough(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkpoint-1 review, end to end: with a cap of 10, the sub-flow is granted 6. The run's own filter needs 8,
    and waits while the sub-flow may still release. Then the sub-flow asks for 5 more, reporting the 6 it holds. The
    run refuses the sub-flow, which ends having used nothing, and the filter gets its 8. Before, both were refused."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 10)
    monkeypatch.setattr(execution, "SUBFLOW_GRANT", 6)
    store = MemoryStore()
    sub = graph(n=ref("steps.k.output.count"))
    sub.node("s", "testkit.slow@1", {"seconds": 2})  # it asks once the run's filter is waiting
    sub.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")}).edge("s", "k")
    sub_id = store.publish(sub)
    g = graph(kept=ref("steps.f.output.count"), code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": list(range(11))}}, on_error="continue")
    g.node("s", "testkit.slow@1", {"seconds": 1}).node("f", FILTER, {"items": list(range(8)), "predicate": cel("true")})
    g.edge("s", "f")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 8, "code": "iteration_cap_exceeded"})
    assert result.iterations == 8


async def test_a_need_waits_for_what_an_asking_sub_flows_own_sub_flow_holds(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkpoint-1 re-review, end to end: with a cap of 10, the run grants 6 to `mid`, which grants all 6 to its own
    sub-flow `leaf`. The run's filter needs 8, `mid`'s 7 and `leaf`'s 8. `leaf` asks holding 6, and `mid` asks
    holding nothing itself but reporting its leaf's 6. The run refuses `mid`, whose subtree ends having used nothing,
    and the run's filter gets its 8. Before, `mid` reported 0 and the run refused its filter too."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 10)
    monkeypatch.setattr(execution, "SUBFLOW_GRANT", 6)
    store = MemoryStore()
    leaf = graph(n=ref("steps.k.output.count"))
    leaf.node("s", "testkit.slow@1", {"seconds": 2})  # it asks once both filters above it are waiting
    leaf.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")}).edge("s", "k")
    leaf_id = store.publish(leaf)
    mid = graph(n=ref("steps.k.output.count"))
    mid.node("r", RUN, {"workflow_id": str(leaf_id), "input": {"items": ref("trigger.items")}}, on_error="continue")
    mid.node("s", "testkit.slow@1", {"seconds": 1}).node(
        "k", FILTER, {"items": list(range(7)), "predicate": cel("true")}
    )
    mid.edge("s", "k")
    mid_id = store.publish(mid)
    g = graph(kept=ref("steps.f.output.count"), code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(mid_id), "input": {"items": list(range(8))}}, on_error="continue")
    g.node("s", "testkit.slow@1", {"seconds": 1}).node("f", FILTER, {"items": list(range(8)), "predicate": cel("true")})
    g.edge("s", "f")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 8, "code": "iteration_cap_exceeded"})
    assert result.iterations == 8


@dataclasses.dataclass
class SlowEnds(MemoryStore):
    """A run's end takes a while to write: a sub-run that's cancelled takes that long to report back."""

    async def project(self, data: ProjectInput) -> None:
        if data.run is not None:
            await asyncio.sleep(1)
        await super().project(data)


async def test_a_cancel_while_the_run_waits_for_a_cancelled_sub_flow_to_report_back(env: WorkflowEnvironment) -> None:
    """Found in checkpoint 1's end-to-end test: the run fails, which cancels its running sub-flow, and waits for it to
    report back. A cancel of the run meanwhile reached that wait and cancelled the sub-flow a second time: Temporal
    refused the duplicate request, so the run's workflow task could never complete, and the run hung. The run's
    failure stands, and the sub-flow is cancelled once."""
    store = SlowEnds()
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(store.publish(sleeper()))}, on_error="continue")
    g.node("s", "testkit.slow@1", {"seconds": 1}).node("f", FAIL, {"message": "it went wrong"}).edge("s", "f")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        for _ in range(200):  # until the run has cancelled its sub-flow
            if await child_cancels(handle):
                break
            await asyncio.sleep(0.05)
        await handle.cancel()  # while the sub-flow is still writing its end
        result = await asyncio.wait_for(handle.result(), 30)
    assert (result.status, result.error["code"]) == ("failed", "workflow_failed")
    assert await child_cancels(handle) == 1


async def child_cancels(handle: Any) -> int:
    """How many times the run has asked Temporal to cancel a child."""
    history = await handle.fetch_history()
    return sum(
        e.HasField("request_cancel_external_workflow_execution_initiated_event_attributes") for e in history.events
    )


async def test_a_sub_flow_that_waits_for_its_first_grant_gets_it(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkpoint-2 review: with no initial grant (its parent had nothing unreserved), a sub-flow's loop can't open
    its first iteration, and nothing else runs while the sub-flow asks its parent. That's a wait, not a stuck run:
    the parent's grant opens the iteration. Before, the sub-flow failed with `internal_error`."""
    monkeypatch.setattr(execution, "SUBFLOW_GRANT", 0)
    store = MemoryStore()
    sub = graph(n=ref("steps.l.output.count"))
    sub.node("l", LOOP, {"items": [1]}).node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    sub_id = store.publish(sub)
    g = graph(n=ref("steps.r.output.n", default=None), code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": []}}, on_error="continue")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"n": 1, "code": "none"}, 1)


async def test_a_run_with_nothing_running_and_no_answer_to_wait_for_still_fails(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkpoint-2 review: waiting for a grant isn't stuck, but a run with nothing running and no answer to wait for
    is, and it still ends `internal_error` instead of hanging. The bug here: ready steps are never handed out."""
    monkeypatch.setattr(Scheduler, "take_ready", lambda self: [])
    store = MemoryStore()
    g = graph().node("a", ECHO, {"value": 1})
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {"items": []})
        result = await asyncio.wait_for(handle.result(), 30)
    assert (result.status, result.error["code"]) == ("failed", "internal_error")


async def test_a_batch_that_fails_on_a_bug_writes_its_rows_first(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2a-3b's final review, M3: a batch that fails with `internal_error` wrote nothing it had queued, and its steps'
    rows stayed `running`. It writes them before it fails, as a run does. The bug here: collecting item 50."""
    collected = Scheduler.collected

    def broken(self: Scheduler, loop: Any, index: int, value: Any) -> None:
        if index == 50:
            raise RuntimeError("a bug")
        collected(self, loop, index, value)

    monkeypatch.setattr(Scheduler, "collected", broken)
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", LOOP, {"items": list(range(150)), "collect": ref("item")}, on_error="continue")
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"code": "internal_error"})
    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
    assert len(rows) >= 50 and "running" not in {r.status for r in rows}


async def test_the_cap_holds_across_children(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> None:
    """One cap for the logical run: past it, the child that can't be served fails with `iteration_cap_exceeded`."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 100)
    store = MemoryStore()
    sub = graph(n=ref("steps.k.output.count"))
    sub.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")})
    sub_id = store.publish(sub)
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": list(range(150))}}, on_error="continue")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 120)
    assert (result.status, result.outputs) == ("succeeded", {"code": "iteration_cap_exceeded"})
    assert result.iterations == 0  # the filter's 150 items are all or nothing: none ran (2a-3b's final review, M7)


# --- the plan's Review Focus: inputs a user meets that nothing above covers -------------------------------------


def sleeper() -> G:
    """A sub-flow that waits an hour: it's still running when the test acts on it."""
    g = graph({"type": "object"})
    g.node("d", "flow.delay@1", {"duration_s": 3600})
    return g


async def children_running(handle: Any, n: int) -> None:
    """Wait (in real time: nothing skips it) until `n` children have started."""
    for _ in range(200):
        if await children_started(handle) >= n:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"fewer than {n} children started")


async def test_cancelling_a_run_cancels_its_children_and_each_reports_back(env: WorkflowEnvironment) -> None:
    """A cancel reaches a sub-flow and a loop batch alike: each ends cancelled and returns its result (its usage)
    before the run ends, and the sub-run's own row says `cancelled`."""
    store = MemoryStore()
    sub = store.publish(sleeper())
    g = graph()
    g.node("r", RUN, {"workflow_id": str(sub)})
    g.node("l", LOOP, {"items": list(range(150))}).node("w", "flow.delay@1", {"duration_s": 3600})
    g.edge("l", "w", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await children_running(handle, 2)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 60)
    history = await handle.fetch_history()
    kinds = [e.event_type for e in history.events]
    assert kinds.count(EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED) == 2  # both reported back
    assert kinds.index(EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED) > max(
        i for i, k in enumerate(kinds) if k == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED
    )
    [(child, _)] = store.starts.items()
    assert (store.runs[handle.id].status, store.runs[child].status) == ("cancelled", "cancelled")


async def test_a_batched_loop_inside_a_loop_runs_its_own_batches_per_iteration(env: WorkflowEnvironment) -> None:
    """Batch ids name the enclosing iteration: two outer iterations run two batched inner loops side by side."""
    store = MemoryStore()
    g = graph(counts=ref("steps.outer.output.items"))
    g.node("outer", LOOP, {"items": [0, 1], "concurrency": 2, "collect": ref("steps.inner.output.count")})
    g.node("inner", LOOP, {"items": list(range(150))}).node("x", ECHO, {"value": ref("item")})
    g.edge("outer", "inner", "body").edge("inner", "x", "body")
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"counts": [150, 150]}, 302)
    assert await children_started(handle) == 4
    keys = {r.iteration_key for r in store.steps(handle.id) if r.node_key == "x"}
    assert keys == {f"outer:{o}/inner:{i}" for o in (0, 1) for i in range(150)}


@dataclasses.dataclass
class LaterLoadsUnusable(MemoryStore):
    """The version loads for the run, and fails to compile for anything that loads it later: a batch here."""

    loads: int = 0

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        self.loads += 1
        data = await super().version(tenant_id, version_id)
        return data if self.loads == 1 else dataclasses.replace(data, manifests={})


async def test_a_batch_that_fails_as_a_workflow_fails_its_loop_and_its_whole_grant_stays_used(
    env: WorkflowEnvironment,
) -> None:
    """A child that fails as a workflow never reports its usage (a terminated child is the other case, which the
    time-skipping server never reports to the parent): its loop fails with the child's code, and the run counts the
    child's whole grant (spec §6, settlement)."""
    store = LaterLoadsUnusable()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", LOOP, {"items": list(range(150))}, on_error="continue").node("x", ECHO)
    g.edge("l", "x", "body")
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "version_unusable"}, 100)


async def test_a_sub_flow_the_run_ends_before_it_starts_uses_nothing(env: WorkflowEnvironment) -> None:
    """The run fails in the turn that would start its sub-flow: the start never goes out, and the sub-flow's grant
    comes back whole (reviewed: it was counted as used)."""
    store = MemoryStore()
    g = graph()
    g.node("r", RUN, {"workflow_id": str(store.publish(sleeper()))}).node("f", FAIL, {"message": "at once"})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.iterations, store.runs[handle.id].iterations) == ("failed", 0, 0)
    assert await children_started(handle) == 0


async def test_a_batch_the_run_ends_before_it_starts_uses_nothing(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph()
    g.node("l", LOOP, {"items": list(range(150))}).node("x", ECHO).edge("l", "x", "body")
    g.node("t", "flow.transform@1", {"fields": {"n": 1}}).node("f", FAIL, {"message": "at once"}).edge("t", "f")
    handle, result = await finished(env, store, g, {})  # `f` fails the run in the turn the first batch would start
    assert (result.status, result.iterations, store.runs[handle.id].iterations) == ("failed", 0, 0)
    assert await children_started(handle) == 0


async def test_a_sub_flow_of_a_sub_flow_asks_up_the_chain(env: WorkflowEnvironment) -> None:
    """The inner sub-flow's filter needs more than both grants: it asks its parent, which asks the root."""
    store = MemoryStore()
    inner = graph(kept=ref("steps.k.output.count"))
    inner.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")})
    inner_id = store.publish(inner)
    middle = graph(kept=ref("steps.r.output.kept"))
    middle.node("r", RUN, {"workflow_id": str(inner_id), "input": {"items": ref("trigger.items")}})
    middle_id = store.publish(middle)
    g = graph(kept=ref("steps.r.output.kept"))
    g.node("r", RUN, {"workflow_id": str(middle_id), "input": {"items": list(range(1_500))}})
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"kept": 1_500}, 1_500)


async def test_a_batched_loop_in_a_sub_flow_writes_into_the_sub_run(env: WorkflowEnvironment) -> None:
    """A batch writes into the run that holds its loop: here the sub-run, not the root."""
    store = MemoryStore()
    sub = graph(n=ref("steps.l.output.count"))
    sub.node("l", LOOP, {"items": ref("trigger.items")}).node("x", ECHO, {"value": ref("item")})
    sub.edge("l", "x", "body")
    sub_id = store.publish(sub)
    g = graph(n=ref("steps.r.output.n"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": list(range(150))}})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"n": 150}, 150)
    [(child, _)] = store.starts.items()
    assert len([r for r in store.steps(child) if r.node_key == "x"]) == 150
    assert not [r for r in store.steps(handle.id) if r.node_key == "x"]


# --- the owner's plan review: every end at a child's boundary is recorded ----------------------------------------


@dataclasses.dataclass
class SlowToLoad(MemoryStore):
    """Some versions never finish loading: their run is cancelled while they load."""

    stuck: set[str] = dataclasses.field(default_factory=set)

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        if version_id in self.stuck:
            await asyncio.Event().wait()
        return await super().version(tenant_id, version_id)


async def test_a_sub_flow_whose_version_does_not_load_still_has_its_row(env: WorkflowEnvironment) -> None:
    """A sub-run writes its row before its version loads, so one that ends right there still shows, with its end."""
    store = MemoryStore()
    sub = store.publish(doubler())
    del store.versions[str(store.subflows[sub].version_id)]  # gone: the loader can't find it
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub), "input": {"n": 1}}, on_error="continue")
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs) == ("succeeded", {"code": "version_unusable"})
    [(child, row)] = store.starts.items()
    assert (row.kind, row.workflow_id) == ("subflow", str(sub))
    assert (store.runs[child].status, store.runs[child].error_code) == ("failed", "version_unusable")


async def test_a_sub_flow_cancelled_while_its_version_loads_still_has_its_row(env: WorkflowEnvironment) -> None:
    store = SlowToLoad()
    sub = store.publish(doubler())
    store.stuck.add(str(store.subflows[sub].version_id))
    g = graph()
    g.node("r", RUN, {"workflow_id": str(sub), "input": {"n": 1}})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await children_running(handle, 1)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 60)
    [(child, row)] = store.starts.items()
    assert (row.kind, store.runs[child].status) == ("subflow", "cancelled")


async def test_a_cancel_while_the_failure_handler_runs_leaves_the_run_failed(env: WorkflowEnvironment) -> None:
    """The run's end is decided before its handler starts. A cancel then cancels the handler, which reports back
    with what it used (decision 19), and the run stays `failed`, in Temporal and in its row."""
    store = MemoryStore()
    handler = graph({"type": "object"})
    handler.node("k", FILTER, {"items": list(range(30)), "predicate": cel("true")})  # some work first
    handler.node("d", "flow.delay@1", {"duration_s": 3_600}).edge("k", "d")
    g = graph()
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("f", FAIL, {"message": "it went wrong"})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        child = await settled(store, "k")  # the handler has done its work, and waits
        await handle.cancel()
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.error["code"], result.iterations) == ("failed", "workflow_failed", 30)
    assert (store.runs[handle.id].status, store.runs[handle.id].iterations) == ("failed", 30)
    assert (store.runs[child].status, store.runs[child].iterations) == ("cancelled", 30)


async def settled(store: MemoryStore, key: str) -> str:
    """Wait (in real time) until a sub-run's step `key` has settled: that sub-run's id."""
    for _ in range(200):
        for child in store.starts:
            if any(r.node_key == key for r in store.steps(child)):
                return child
        await asyncio.sleep(0.05)
    raise AssertionError(f"no sub-run settled `{key}`")


@dataclasses.dataclass
class Ordered(MemoryStore):
    """Records the order runs start and end in, as their rows are written."""

    log: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    async def project(self, data: ProjectInput) -> None:
        await super().project(data)
        if data.start is not None:
            self.log.append(("start", data.start.run_id))
        if data.run is not None:
            self.log.append(("end", data.run.run_id))


async def test_a_failed_run_stays_non_terminal_until_its_failure_handler_has_ended(env: WorkflowEnvironment) -> None:
    """Spec §4.5: a non-terminal run's closure keeps the CEL profiles it pins in use. The failed run's row stays
    non-terminal until its handler's own row exists and has ended, so the handler never starts, or runs, with nothing
    holding its profile."""
    store = Ordered()
    handler = graph({"type": "object"})
    handler.node("h", ECHO, {"value": 1})
    g = graph()
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("f", FAIL, {"message": "it went wrong"})
    handle, result = await finished(env, store, g, {})
    [(child, _)] = store.starts.items()
    assert store.log.index(("start", child)) < store.log.index(("end", child)) < store.log.index(("end", handle.id))
    assert (result.status, store.runs[handle.id].status) == ("failed", "failed")


async def test_a_failure_handlers_iterations_count_toward_its_run(env: WorkflowEnvironment) -> None:
    """One budget per logical run: the run's result and its row count what its handler used."""
    store = MemoryStore()
    handler = graph({"type": "object"})
    handler.node("k", FILTER, {"items": list(range(50)), "predicate": cel("true")})
    g = graph()
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("f", FAIL, {"message": "it went wrong"})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.iterations, store.runs[handle.id].iterations) == ("failed", 50, 50)


async def test_a_run_past_its_deadline_runs_its_failure_handler(env: WorkflowEnvironment) -> None:
    """The owner's ruling: `deadline_exceeded` runs the handler too, with a deadline of its own."""
    store = MemoryStore()
    handler = graph({"type": "object"})
    handler.node("h", ECHO, {"value": ref("trigger.error.code", default="?")})
    g = graph()
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("d", "flow.delay@1", {"duration_s": 3 * 86_400})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, max_run_duration_s=86_400)
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "deadline_exceeded"
    [(child, row)] = store.starts.items()
    assert row.kind == "failure_handler"
    assert [r.output_preview for r in store.steps(child)] == [{"value": "deadline_exceeded"}]


async def test_a_cancelled_run_runs_no_failure_handler(env: WorkflowEnvironment) -> None:
    """The owner's ruling: an explicit cancel is not a failure."""
    store = MemoryStore()
    g = graph()
    g.settings["failure_handler"] = str(store.publish(sleeper()))
    g.node("d", "flow.delay@1", {"duration_s": 3_600})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await asyncio.sleep(0.2)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 60)
    assert (store.runs[handle.id].status, store.starts) == ("cancelled", {})
