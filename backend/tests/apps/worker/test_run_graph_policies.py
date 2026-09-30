# SPDX-License-Identifier: Apache-2.0
"""`RunGraph`: every node kind, every error policy, the limits it enforces, and how a run can end (spec §6, §10)."""

import asyncio
import dataclasses
import uuid
from datetime import timedelta
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner

from dewpoint.engine.canonical import canonical_json
from dewpoint.engine.runtime import nodes
from dewpoint.engine.runtime import workflow as run_graph
from dewpoint.engine.runtime.activities import (
    CEL_EVALUATE,
    ENGINE_QUEUE,
    OUTCOME_UNKNOWN,
    PROJECT,
    ProjectInput,
    RunInput,
)
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import PROJECT_BYTES, RunGraph
from tests.apps.worker.harness import (
    EVALUATOR_ONLY,
    RESULT_TIMEOUT_S,
    TENANT,
    MemoryStore,
    run,
    run_id_of,
    start,
    workers,
)
from tests.support.graphs import G, cel, ref, template
from tests.support.plugins.testkit import SlowSend

ECHO, LOOP, SWITCH = "testkit.echo@1", "flow.loop@1", "flow.switch@1"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "open": {"type": "object"}},
    "required": ["x", "open"],
}
TRIGGER: dict[str, Any] = {"x": 7, "open": {}}


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


async def test_a_switch_takes_its_first_matching_case(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    cases = [{"port": "small", "when": cel("trigger.x < 5")}, {"port": "big", "when": cel("trigger.x > 5")}]
    g = graph(taken=cel("has(steps.b.output) ? 'big' : 'other'")).node("s", SWITCH, {"cases": cases})
    g.node("a", ECHO).node("b", ECHO).node("d", ECHO).edge("s", "a", "small").edge("s", "b", "big")
    g.edge("s", "d", "default")
    async with workers(env.client, store):
        assert (await run(env.client, store, g, TRIGGER)).outputs == {"taken": "big"}


async def test_wait_until_waits_durably_then_transform_shapes_values(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    at = await env.get_current_time() + timedelta(days=2)  # the server's clock, not the host's
    until = at.isoformat()
    g = graph(t=ref("steps.t.output")).node("w", "flow.wait_until@1", {"until": until})
    g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.x * 2"), "label": "fixed"}}).edge("w", "t")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        info = await handle.describe()
    assert result.outputs == {"t": {"double": 14, "label": "fixed"}}
    assert (
        info.close_time and info.close_time >= at
    )  # the instant, reckoned before the run started: not 2 days after it


def failing_loop(on_item_error: str) -> G:
    g = graph(out=ref("steps.l.output", default=None))
    config = {"items": [0, 1, 2], "on_item_error": on_item_error, "collect": ref("item")}
    g.node("l", LOOP, config).node("f", "testkit.ambiguous_send@1", {"outcome": cel("item == 1 ? 'rejected' : 'sent'")})
    return g.edge("l", "f", "body")


async def test_continue_records_failed_items_and_stop_fails_the_loop(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    async with workers(env.client, store):
        kept = await run(env.client, store, failing_loop("continue"), TRIGGER)
        stopped = await run(env.client, store, failing_loop("stop"), TRIGGER)
    assert kept.outputs == {
        "out": {
            "items": [0, None, 2],
            "failures": [{"index": 1, "code": "testkit.rejected", "message": "the receiver rejected the request"}],
            "count": 3,
        }
    }
    assert stopped.status == "failed" and stopped.error and stopped.error["code"] == "testkit.rejected"


async def test_an_iteration_that_fails_while_a_sibling_runs_cancels_only_that_sibling(env: WorkflowEnvironment) -> None:
    """The failed iteration's other step is cancelled, and the loop carries on under `continue`: the run isn't."""
    store = MemoryStore()
    g = graph(out=ref("steps.l.output"))
    g.node("l", LOOP, {"items": [0, 1, 2], "on_item_error": "continue", "collect": ref("item")})
    g.node("f", "testkit.ambiguous_send@1", {"outcome": cel("item == 0 ? 'rejected' : 'sent'")})
    g.node("d", "flow.delay@1", {"duration_s": cel("item == 0 ? 3600 : 0")})
    g.edge("l", "f", "body").edge("l", "d", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), 60)
        info = await handle.describe()
    assert (result.status, result.iterations) == ("succeeded", 3)
    assert [f["index"] for f in result.outputs["out"]["failures"]] == [0]
    assert info.close_time and info.close_time - info.start_time < timedelta(hours=1)  # the delay was cancelled


async def test_the_item_cap_fails_the_loop(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", LOOP, {"items": [1, 2, 3], "item_cap": 2}, on_error="continue")
    g.node("x", ECHO).edge("l", "x", "body")
    async with workers(env.client, store):
        assert (await run(env.client, store, g, TRIGGER)).outputs == {"code": "item_cap_exceeded"}


async def test_a_loop_past_the_runs_iteration_cap_fails(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The run's cap (spec §6): the iteration past it is refused and its loop fails. The run doesn't wait for budget
    nothing could release."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 2)
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", LOOP, {"items": [1, 2, 3]}, on_error="continue")
    g.node("x", ECHO).edge("l", "x", "body")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        result = await asyncio.wait_for(run(env.client, store, g, TRIGGER), 60)
    assert (result.outputs, result.iterations) == ({"code": "iteration_cap_exceeded"}, 2)


async def test_a_failing_collect_fails_its_iteration(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(out=ref("steps.l.output.failures", default=None))
    g.node("l", LOOP, {"items": [1, 0], "on_item_error": "continue", "collect": cel("10 / item")}).node("x", ECHO)
    g.edge("l", "x", "body")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert [(f["index"], f["code"]) for f in result.outputs["out"]] == [(1, "evaluation_error")]  # type: ignore[index]


async def test_a_default_covers_a_missing_value_and_a_failed_expression_fails_the_step(
    env: WorkflowEnvironment,
) -> None:
    store = MemoryStore()
    g = graph(a=ref("steps.a.output.value", default="?"), b=ref("steps.b.error.code", default="none"))
    g.node("a", ECHO, {"value": ref("trigger.open.nothing", default="fallback")})
    g.node("b", ECHO, {"value": cel("trigger.open.nothing")}, on_error="continue")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.outputs == {"a": "fallback", "b": "evaluation_error"}
    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}  # b never reached its activity: it has its row
    assert (rows["b"].attempt, rows["b"].status, rows["b"].error_code) == (1, "failed", "evaluation_error")


async def test_after_continue_a_guard_sees_no_output(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    seen = cel("has(steps.a.output) ? 'output' : has(steps.a.error) ? steps.a.error.code : 'nothing'")
    g = graph(seen=seen, v=ref("steps.a.output", default="d"))
    g.node("a", "testkit.ambiguous_send@1", {"outcome": "rejected"}, on_error="continue")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert result.outputs == {"seen": "testkit.rejected", "v": "d"}


async def test_at_most_a_hundred_steps_are_in_flight(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph()
    for i in range(105):
        g.node(f"e{i}", ECHO, {"value": i})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        history = await handle.fetch_history()
    before_first_completion = 0
    for event in history.events:
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            break
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            before_first_completion += event.activity_task_scheduled_event_attributes.activity_type.name != PROJECT
    assert before_first_completion == 100  # steps; the one projection of their running rows is outside the cap


class SlowStore(MemoryStore):
    async def project(self, data: ProjectInput) -> None:
        await asyncio.sleep(0.5)  # a slow database
        await super().project(data)


async def test_one_projection_is_outstanding_at_a_time(env: WorkflowEnvironment) -> None:
    """Projections count toward the history an execution can add while it drains (spec §6): rows that settle while
    one is outstanding wait for it, and go in the next."""
    store = SlowStore()
    g = graph()
    for i in range(4):  # branches ending 0.3 s apart: each transform settles while the last projection runs
        g.node(f"e{i}", "testkit.slow@1", {"seconds": 0.3 * i}).node(f"t{i}", "flow.transform@1", {"fields": {"i": i}})
        g.edge(f"e{i}", f"t{i}")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        history = await handle.fetch_history()
    outstanding: set[int] = set()
    most = 0
    for event in history.events:
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            if event.activity_task_scheduled_event_attributes.activity_type.name == PROJECT:
                outstanding.add(event.event_id)
                most = max(most, len(outstanding))
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            outstanding.discard(event.activity_task_completed_event_attributes.scheduled_event_id)
    assert most == 1
    keys = sorted(r.node_key for r in store.steps(run_id_of(handle)))
    assert keys == sorted(f"{k}{i}" for k in "et" for i in range(4))


async def test_a_projection_in_flight_takes_no_units_slot(env: WorkflowEnvironment) -> None:
    """Spec §6: 100 units in flight, and besides them one projection. A slow projection is still in flight when 105
    more steps become ready: 99 of them start beside the slow step, so draining can wait on the full cap."""
    store = SlowStore()
    g = graph().node("x", "testkit.slow@1", {"seconds": 1})
    g.node("t0", "flow.transform@1", {"fields": {"a": 1}}).node("t1", "flow.transform@1", {"fields": {"a": 2}})
    g.edge("t0", "t1")  # when t1 settles, the projection of x's first row is in flight
    for i in range(105):
        g.node(f"e{i}", ECHO, {"value": i}).edge("t1", f"e{i}")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        history = await handle.fetch_history()
    kinds = {
        e.event_id: e.activity_task_scheduled_event_attributes.activity_type.name
        for e in history.events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    }
    steps = 0
    for event in history.events:
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            if kinds[event.activity_task_completed_event_attributes.scheduled_event_id] != PROJECT:
                break  # the first step that ended
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            steps += kinds[event.event_id] != PROJECT
    assert steps == 100  # the slow step and 99 others


async def test_the_deadline_cancels_running_work(own_env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("s", "testkit.slow@1", {"seconds": 30})
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, TRIGGER, max_run_duration_s=2)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "deadline_exceeded"
    [row] = store.steps(run_id_of(handle))
    assert row.status == "cancelled"
    assert store.runs[run_id_of(handle)].status == "deadline_exceeded"


async def test_a_cancelled_run_projects_its_end(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("d", "flow.delay@1", {"duration_s": 3600})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.sleep(0.2)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert store.runs[run_id_of(handle)].status == "cancelled"


async def test_a_version_this_build_cannot_run_fails_the_run(env: WorkflowEnvironment) -> None:
    """A version whose node types this build lacks (or that no longer loads): the run fails, and says so."""
    store = MemoryStore()
    version_id = store.add(graph().node("a", ECHO))
    store.versions[version_id] = dataclasses.replace(store.versions[version_id], manifests={})
    run_id = str(uuid.uuid4())
    async with workers(env.client, store):
        handle = await env.client.start_workflow(
            RunGraph.run,
            RunInput(TENANT, run_id, version_id, TRIGGER),
            id=run_workflow_id(TENANT, run_id),
            task_queue=ENGINE_QUEUE,
        )
        result = await asyncio.wait_for(handle.result(), 10)
    assert result.status == "failed" and result.error and result.error["code"] == "version_unusable"
    assert (store.runs[run_id].status, store.runs[run_id].error_code) == ("failed", "version_unusable")
    message = "This build can't run the version (ProgramError); the worker's log has the details."  # no raw text
    assert (result.error["message"], store.runs[run_id].error_message) == (message, message)
    assert store.steps(run_id) == []  # nothing ran


async def test_a_bug_fails_the_run_instead_of_leaving_it_running(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exception in workflow code would fail the workflow task, which Temporal retries forever: the run would
    hang, still `running` in the projection."""

    def broken(ref: str, config: Any) -> nodes.Decision:
        raise RuntimeError("a bug in a control node")

    monkeypatch.setattr(nodes, "decide", broken)  # the sandbox runs its own copy: this test runs outside it
    store = MemoryStore()
    g = graph().node("a", ECHO).node("t", "flow.transform@1", {"fields": {"y": 1}}).edge("a", "t")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), 10)
    message = "The interpreter failed (RuntimeError); the worker's log has the details."  # never the raw text
    assert result.error == {"code": "internal_error", "message": message, "attempt": 1}
    run_id = run_id_of(handle)
    assert store.runs[run_id].status == "failed" and [r.status for r in store.steps(run_id)] == ["succeeded"]


async def test_a_trigger_that_breaks_its_schema_fails_a_step_not_the_workflow(env: WorkflowEnvironment) -> None:
    """2a doesn't validate trigger payloads (2b does). Publish trusted the schema; the run must fail visibly."""
    store = MemoryStore()
    g = graph(v=ref("steps.b.output.value", default="none"))
    g.node("a", ECHO, {"value": ref("trigger.x")}).node("b", ECHO, {"value": cel("trigger.x + 1")}, on_error="continue")
    async with workers(env.client, store):
        missing = await run(env.client, store, g, {"open": {}})
        wrong = await run(env.client, store, g, {"x": "seven", "open": {}})
    assert (missing.status, missing.error and missing.error["code"]) == ("failed", "evaluation_error")
    assert (wrong.status, wrong.outputs) == ("succeeded", {"v": "none"})  # b failed and continued


async def test_a_node_type_this_worker_does_not_serve_fails_its_step(env: WorkflowEnvironment) -> None:
    """The registry lists it, but this worker's plugins don't (a build without the plugin): no hang."""
    store = MemoryStore()
    g = graph(code=ref("steps.a.error.code", default="none")).node("a", ECHO, on_error="continue")
    g.nodes[0]["options"]["max_attempts"] = 2
    async with workers(env.client, store, plugins=()):
        result = await asyncio.wait_for(run(env.client, store, g, TRIGGER), 30)
    assert result.status == "succeeded" and result.outputs == {"code": "node_type_unavailable"}


async def test_a_worker_without_the_run_in_its_cache_replays_it_and_carries_on(env: WorkflowEnvironment) -> None:
    """A restart or a cache eviction mid-run: the next workflow task replays the whole history first. With no cache,
    every task does, so any non-determinism in the interpreter fails this run."""
    store = MemoryStore()
    g = graph(doubled=ref("steps.l.output.items", default=[]), side=cel("has(steps.yes.output) ? 'yes' : 'no'"))
    g.node("c", "flow.if@1", {"condition": cel("trigger.x > 5")}).node("yes", ECHO).node("no", ECHO)
    g.node("l", LOOP, {"items": [1, 2, 3], "concurrency": 2, "collect": cel("item * 2")})
    g.node("x", ECHO, {"value": ref("item")}).node("d", "flow.delay@1", {"duration_s": 3600})
    g.edge("c", "yes", "true").edge("c", "no", "false").edge("yes", "l").edge("l", "x", "body").edge("l", "d", "done")
    async with workers(env.client, store, cache=0):
        result = await run(env.client, store, g, TRIGGER)
    assert result.outputs == {"doubled": [2, 4, 6], "side": "yes"}


async def test_a_timeout_after_an_ambiguous_send_is_never_retried(own_env: WorkflowEnvironment) -> None:
    """Review finding: a start-to-close timeout (or a lost worker) never reaches the node's own error mapping. The
    send may have happened, so an ambiguous node's timed-out attempt is `outcome_unknown` and never repeated."""
    store = MemoryStore()
    g = graph().node("s", "testkit.slow_send@1", {"seconds": 3})
    g.nodes[0]["options"].update(timeout_s=1, max_attempts=3)
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert SlowSend.sent.count(run_id_of(handle)) == 1
    assert result.status == "failed" and result.error and result.error["code"] == "timeout"
    [row] = store.steps(run_id_of(handle))
    assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", "timeout", "outcome_unknown")


async def sent(run_id: str) -> None:
    for _ in range(200):
        if run_id in SlowSend.sent:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the request was never sent")


async def test_a_worker_lost_during_an_ambiguous_attempt_never_repeats_it(own_env: WorkflowEnvironment) -> None:
    """Final review: a worker that shuts down mid-attempt reports a failure the activity never mapped
    (`WorkerShutdown`), and it was taken for the node's own retryable error: the request went out twice."""
    store = MemoryStore()
    g = graph().node("s", "testkit.slow_send@1", {"seconds": 5})
    g.nodes[0]["options"].update(max_attempts=3)
    async with workers(own_env.client, store, cache=0):  # no sticky queue: the next worker takes over at once
        handle = await start(own_env.client, store, g, TRIGGER)
        await sent(run_id_of(handle))
    async with workers(own_env.client, store):  # another worker carries the run on
        result = await asyncio.wait_for(handle.result(), 30)
    assert SlowSend.sent.count(run_id_of(handle)) == 1
    [row] = store.steps(run_id_of(handle))
    assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", "error", "outcome_unknown")
    assert result.status == "failed"


async def test_a_cancelled_ambiguous_attempt_says_its_outcome_is_unknown(own_env: WorkflowEnvironment) -> None:
    """2a-3a's final review, M3: a run cancelled during an ambiguous attempt recorded it `cancelled` only. Its request
    may have been sent: the row says so, as it does for a timeout or a lost worker."""
    store = MemoryStore()
    g = graph().node("s", "testkit.slow_send@1", {"seconds": 5})
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, TRIGGER)
        await sent(run_id_of(handle))  # the attempt has sent its request (its history says so only once it ends)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 30)
    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "s"]
    assert (row.status, row.outcome) == ("cancelled", OUTCOME_UNKNOWN)


async def test_a_timeout_is_retried_when_repeating_is_safe(own_env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("s", "testkit.slow@1", {"seconds": 3})
    g.nodes[0]["options"].update(timeout_s=1, max_attempts=2)
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, TRIGGER)
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert [(r.attempt, r.status, r.error_code, r.outcome) for r in store.steps(run_id_of(handle))] == [
        (1, "failed", "timeout", None),
        (2, "failed", "timeout", None),
    ]


class FlakyStore(MemoryStore):
    """A database that refuses the first `down` writes."""

    down = 3

    async def project(self, data: ProjectInput) -> None:
        if self.down:
            self.down -= 1
            raise ConnectionError("the database went away")
        await super().project(data)


async def test_a_database_outage_never_repeats_an_effect_and_the_rows_catch_up(env: WorkflowEnvironment) -> None:
    """Review finding: rows are written by the projection alone, which retries on its own. A step's effect runs
    once, and no row is left `running` once the database is back."""
    store = FlakyStore()
    g = graph().node("s", "testkit.slow_send@1", {"seconds": 0}).node("t", "flow.transform@1", {"fields": {"n": 1}})
    g.edge("s", "t")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "succeeded" and SlowSend.sent.count(run_id_of(handle)) == 1 and store.down == 0
    assert [(r.node_key, r.status) for r in store.steps(run_id_of(handle))] == [("s", "succeeded"), ("t", "succeeded")]
    assert store.runs[run_id_of(handle)].status == "succeeded"


class BatchStore(FlakyStore):
    """Down for its first writes, and records the size of each projection's rows."""

    def __init__(self) -> None:
        super().__init__()
        self.sizes: list[int] = []

    async def project(self, data: ProjectInput) -> None:
        await super().project(data)
        self.sizes.append(sum(len(canonical_json(dataclasses.asdict(r))) for r in data.steps))


async def test_a_backlog_is_projected_in_bounded_batches(env: WorkflowEnvironment) -> None:
    """Final review: rows that settle while a projection is outstanding all went into the next one. After a database
    outage the catch-up exceeded Temporal's payload limit, and the run could no longer progress."""
    store = BatchStore()
    g = graph().node("l", LOOP, {"items": list(range(40))}).node("e", ECHO, {"value": "x" * 7000})
    g.edge("l", "e", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "succeeded" and store.down == 0
    assert max(store.sizes) <= PROJECT_BYTES < sum(store.sizes)  # the backlog took more than one batch
    assert sorted(r.iteration_key for r in store.steps(run_id_of(handle)) if r.node_key == "e") == sorted(
        f"l:{i}" for i in range(40)
    )


async def test_sensitive_values_never_reach_the_projection(env: WorkflowEnvironment) -> None:
    """Review finding: a nested model's sensitive field sits behind `$ref`, and control steps, templates, plugin inputs
    and messages can all copy a sensitive value into a place no schema marks."""
    store = MemoryStore()
    secret, password = ref("steps.s.output.secret_value"), ref("steps.s.output.login.password")
    g = graph().node("s", "testkit.sensitive@1")
    line = template("key=", {"ref": "steps.s.output.secret_value"})
    g.node("t", "flow.transform@1", {"fields": {"copy": secret, "line": line}})
    g.node("e", ECHO, {"value": password}).node(
        "p", "testkit.ambiguous_send@1", {"outcome": "rejected", "detail": secret}, on_error="continue"
    )
    g.node("f", "flow.fail@1", {"message": template("gave up on ", {"ref": "steps.s.output.login.password"})})
    lookup = cel("{'a': 1}[steps.s.output.secret_value] > 0")  # CEL's message quotes the missing key
    g.node("k", "flow.transform@1", {"fields": {"n": lookup}}, on_error="continue").edge("s", "k").edge("k", "f")
    g.edge("s", "t").edge("s", "e").edge("s", "p").edge("t", "f").edge("e", "f").edge("p", "f")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
    assert rows["s"].output_preview == {
        "public": "visible",
        "secret_value": "[redacted]",
        "login": {"user": "ops", "password": "[redacted]"},
    }
    assert rows["t"].output_preview == {"copy": "[redacted]", "line": "key=[redacted]"}
    assert (rows["e"].input_preview, rows["e"].output_preview) == ({"value": "[redacted]"}, {"value": "[redacted]"})
    assert rows["p"].error_message == "the receiver rejected the request: [redacted]"
    assert rows["f"].error_message == "gave up on [redacted]"
    assert rows["k"].error_message == 'NOT_FOUND: Key not found in map : "[redacted]"'
    assert store.runs[run_id_of(handle)].error_message == "gave up on [redacted]"
    assert result.error and result.error["message"] == "gave up on [redacted]"
    dump = repr(store.rows) + repr(store.runs)
    assert "s3cr3t-value" not in dump and "pa55word" not in dump


async def test_a_sensitive_trigger_field_is_masked_where_it_is_copied(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(key=ref("trigger.api_key"))
    g.settings["input_schema"] = {
        "type": "object",
        "properties": {"api_key": {"type": "string", "x-sensitive": True}},
        "required": ["api_key"],
    }
    g.node("e", ECHO, {"value": template("Bearer ", {"ref": "trigger.api_key"})})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"api_key": "k3y-k3y-k3y"})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    [row] = store.steps(run_id_of(handle))
    assert (row.input_preview, row.output_preview) == ({"value": "Bearer [redacted]"}, {"value": "Bearer [redacted]"})
    assert result.outputs == {"key": "k3y-k3y-k3y"}  # the workflow's own outputs are its contract, not a preview


async def test_a_sensitive_config_value_is_masked_where_it_is_copied_or_echoed(env: WorkflowEnvironment) -> None:
    """Review finding: a node's `x-sensitive` config field is redacted in its own input preview, but a control step
    can copy the same literal, and the node can echo it in its error. Literals are learned when the run starts;
    a value that only the config marks sensitive (here from an unmarked trigger field), before its attempt."""
    store = MemoryStore()
    token, passed = "tok-hunter22", "tok-from-trigger"
    g = graph().node("t", "flow.transform@1", {"fields": {"copy": token}})
    g.node("p", "testkit.ambiguous_send@1", {"outcome": "rejected", "token": token}, on_error="continue")
    echo = {"outcome": "rejected", "token": ref("trigger.open.tok", default="")}
    g.node("q", "testkit.ambiguous_send@1", echo, on_error="continue").edge("t", "p").edge("t", "q")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"x": 7, "open": {"tok": passed}})
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
    assert rows["t"].output_preview == {"copy": "[redacted]"}  # projected before `p` ran
    assert rows["p"].input_preview == {"outcome": "rejected", "token": "[redacted]"}
    assert rows["p"].error_message == rows["q"].error_message == "the receiver rejected the request for [redacted]"
    assert token not in repr(store.rows) + repr(store.runs) and passed not in repr(store.rows) + repr(store.runs)


async def output_evaluation_started(handle: Any) -> None:
    """Wait until the run is evaluating its outputs: their `cel.evaluate` is scheduled."""
    while True:
        for event in (await handle.fetch_history()).events:
            if event.HasField("activity_task_scheduled_event_attributes"):
                if event.activity_task_scheduled_event_attributes.activity_type.name == CEL_EVALUATE:
                    return
        await asyncio.sleep(0.05)


async def test_a_cancel_while_the_outputs_are_evaluated_projects_cancelled(env: WorkflowEnvironment) -> None:
    """Checkpoint-2 finding: the outputs were evaluated outside the run's cancellation handler, so a cancel then
    closed the workflow with nothing projected: the run stayed `running`."""
    store = MemoryStore()
    g = graph(n=cel(f"trigger.x + {EVALUATOR_ONLY}")).node("a", ECHO)
    async with workers(env.client, store, evaluate=None):  # no evaluator: the output's CEL waits for one
        handle = await start(env.client, store, g, TRIGGER, cel_schedule_to_start_s=60)
        await asyncio.wait_for(output_evaluation_started(handle), 10)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 10)
    assert store.runs[run_id_of(handle)].status == "cancelled"


async def test_the_deadline_holds_while_the_outputs_are_evaluated(env: WorkflowEnvironment) -> None:
    """Checkpoint-2 finding: past the deadline, a run waited on its outputs' evaluator and ended as its failure."""
    store = MemoryStore()
    g = graph(n=cel(f"trigger.x + {EVALUATOR_ONLY}")).node("a", ECHO)
    async with workers(env.client, store, evaluate=None):
        handle = await start(env.client, store, g, TRIGGER, max_run_duration_s=1, cel_schedule_to_start_s=5)
        result = await asyncio.wait_for(handle.result(), 10)
    assert (result.status, result.error and result.error["code"]) == ("deadline_exceeded", "deadline_exceeded")
    assert store.runs[run_id_of(handle)].status == "deadline_exceeded"


async def test_a_damaged_output_fails_the_run_as_unusable(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    version_id = store.add(graph(n=ref("trigger.x")).node("a", ECHO))
    damaged = {**store.versions[version_id].graph}
    damaged["settings"] = {**damaged["settings"], "outputs": {"n": {"$value": {"kind": "ref", "path": 5}}}}
    store.versions[version_id] = dataclasses.replace(store.versions[version_id], graph=damaged)
    run_id = str(uuid.uuid4())
    async with workers(env.client, store):
        handle = await env.client.start_workflow(
            RunGraph.run,
            RunInput(TENANT, run_id, version_id, TRIGGER),
            id=run_workflow_id(TENANT, run_id),
            task_queue=ENGINE_QUEUE,
        )
        result = await asyncio.wait_for(handle.result(), 10)
    assert result.error and result.error["code"] == "version_unusable" and store.steps(run_id) == []


class HeldStore(MemoryStore):
    """Holds the run's summary write open until the test lets it go: a cancel can arrive in between."""

    def __init__(self) -> None:
        super().__init__()
        self.writing, self.release = asyncio.Event(), asyncio.Event()

    async def project(self, data: ProjectInput) -> None:
        if data.run is not None and not self.writing.is_set():
            self.writing.set()
            await self.release.wait()
        await super().project(data)


async def test_a_cancel_after_the_run_concluded_leaves_its_outcome(env: WorkflowEnvironment) -> None:
    """A cancel that arrives while the run's end is being written can't unmake that end: the write is repeated and
    the run's own result stands, so the projection and Temporal agree."""
    store = HeldStore()
    g = graph(v=ref("steps.a.output.value")).node("a", ECHO, {"value": 1})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.wait_for(store.writing.wait(), 10)
        await handle.cancel()
        store.release.set()
        result = await asyncio.wait_for(handle.result(), 10)
    assert (result.status, result.outputs, store.runs[run_id_of(handle)].status) == ("succeeded", {"v": 1}, "succeeded")


async def cancel_acted_on(handle: Any) -> None:
    """Until a workflow task after the cancel request has completed: the workflow has acted on the cancel."""
    for _ in range(200):
        kinds = [e.event_type for e in (await handle.fetch_history()).events]
        if EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED in kinds:
            after = kinds[kinds.index(EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED) :]
            if EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED in after:
                return
        await asyncio.sleep(0.05)
    raise AssertionError("the workflow never acted on the cancel")


async def test_a_cancel_acted_on_before_the_end_is_written_still_leaves_its_outcome(env: WorkflowEnvironment) -> None:
    """Final review: the SDK reports the cancel of the awaited end write as an `ActivityError`, unless the write had
    already finished in the same activation. Only `CancelledError` repeated the write, so Temporal closed the run
    `cancelled` while its row said `succeeded`, or stayed `running` if the write never landed."""
    store = HeldStore()
    g = graph(v=ref("steps.a.output.value")).node("a", ECHO, {"value": 1})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.wait_for(store.writing.wait(), 10)
        await handle.cancel()
        await cancel_acted_on(handle)  # the held write outlives the cancel's activation
        store.release.set()
        result = await asyncio.wait_for(handle.result(), 10)
    assert (result.status, result.outputs, store.runs[run_id_of(handle)].status) == ("succeeded", {"v": 1}, "succeeded")


class LoadingStore(MemoryStore):
    """Holds the version's load open until the test lets it go."""

    def __init__(self) -> None:
        super().__init__()
        self.loading, self.release = asyncio.Event(), asyncio.Event()

    async def version(self, tenant_id: str, version_id: str) -> Any:
        self.loading.set()
        await self.release.wait()
        return await super().version(tenant_id, version_id)


async def test_a_cancel_while_the_version_loads_cancels_the_run(env: WorkflowEnvironment) -> None:
    """Final review: the cancel of the version's load arrives as an `ActivityError`, which was taken for a version
    this build can't run (`version_unusable`)."""
    store = LoadingStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, graph().node("a", ECHO, {"value": 1}), TRIGGER)
        await asyncio.wait_for(store.loading.wait(), 10)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 10)
        store.release.set()
    summary = store.runs[run_id_of(handle)]
    assert (summary.status, summary.error_code) == ("cancelled", "cancelled")
