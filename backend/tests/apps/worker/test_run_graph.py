# SPDX-License-Identifier: Apache-2.0
"""`RunGraph` end to end on the time-skipping test server (spec §6, §10 interpreter tests)."""

import asyncio
from typing import Any

from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer

from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, run, run_id_of, start, workers
from tests.support.graphs import G, cel, ref, template

ECHO, IF, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.filter@1"
SET, DELAY, STOP, FAIL = "flow.set_variables@1", "flow.delay@1", "flow.stop@1", "flow.fail@1"
TRANSFORM = "flow.transform@1"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "names": {"type": "array", "items": {"type": "string"}}},
    "required": ["x", "names"],
}
TRIGGER = {"x": 7, "names": ["ap-1", "sw-1", "ap-2"]}


def graph(*, outputs: dict[str, Any] | None = None) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, **({"outputs": outputs} if outputs else {})}
    return g


async def test_values_flow_from_the_trigger_through_steps_to_the_outputs(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"result": ref("steps.b.output.value")})
    g.node("a", ECHO, {"value": ref("trigger.x")})
    g.node("b", ECHO, {"value": template("x=", {"ref": "steps.a.output.value"})}).edge("a", "b")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert (result.status, result.outputs) == ("succeeded", {"result": "x=7"})


async def test_a_cel_branch_runs_one_side_and_projects_control_steps(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"side": cel("has(steps.yes.output) ? 'yes' : 'no'")})
    g.node("c", IF, {"condition": cel("trigger.x > 5")}).node("yes", ECHO, {"value": 1}).node("no", ECHO, {"value": 2})
    g.edge("c", "yes", "true").edge("c", "no", "false")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert (result.status, result.outputs) == ("succeeded", {"side": "yes"})
    rows = {r.node_key: r for r in store.steps(run_id_of(handle))}
    assert rows["c"].status == "succeeded" and rows["c"].cel_mode == "local"  # this build runs its profile in-process
    assert "no" not in rows and store.runs[run_id_of(handle)].status == "succeeded"


async def test_a_loop_collects_per_item_and_a_filter_keeps_matches(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"doubled": ref("steps.l.output.items"), "aps": ref("steps.f.output.items")})
    g.node("l", LOOP, {"items": [1, 2, 3], "concurrency": 2, "collect": cel("item * 2")}).node("x", ECHO)
    g.node("f", FILTER, {"items": ref("trigger.names"), "predicate": cel("item.startsWith('ap-')")})
    g.edge("l", "x", "body").edge("l", "f", "done")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.outputs == {"doubled": [2, 4, 6], "aps": ["ap-1", "ap-2"]}
    assert result.iterations == 3 + 3  # three iterations, three filter items
    rows = [(r.node_key, r.iteration_key, r.status) for r in store.steps(run_id_of(handle))]
    assert sorted(rows) == [
        ("f", "", "succeeded"),
        ("l", "", "succeeded"),
        ("x", "l:0", "succeeded"),
        ("x", "l:1", "succeeded"),
        ("x", "l:2", "succeeded"),
    ]


async def test_variables_are_set_and_read(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"v": ref("vars.count")})
    g.settings["vars_schema"] = {"type": "object", "properties": {"count": {"type": "integer", "default": 0}}}
    g.node("s", SET, {"assignments": {"count": cel("trigger.x + 1")}})
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert result.outputs == {"v": 8}


async def test_retries_follow_the_manifest_and_each_attempt_is_projected(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("f", "testkit.fail_n@1", {"failures": 2})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        assert (await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)).status == "succeeded"
    assert [(r.attempt, r.status, r.error_code) for r in store.steps(run_id_of(handle))] == [
        (1, "failed", "testkit.transient"),
        (2, "failed", "testkit.transient"),
        (3, "succeeded", None),
    ]


async def test_an_error_port_handles_a_fatal_failure(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"code": ref("steps.a.error.code", default="none")})
    g.node("a", "testkit.ambiguous_send@1", {"outcome": "rejected"}, on_error="port").node("h", ECHO, {"value": 1})
    g.edge("a", "h", "error")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert (result.status, result.outputs) == ("succeeded", {"code": "testkit.rejected"})


async def test_an_unknown_outcome_is_never_retried_and_fails_the_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("a", "testkit.ambiguous_send@1", {"outcome": "unknown"})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "failed" and result.error == {
        "code": "testkit.timeout_after_send",
        "message": "the request may have been delivered",
        "attempt": 1,
    }
    [row] = store.steps(run_id_of(handle))
    assert (row.attempt, row.outcome) == (1, "outcome_unknown")


async def test_a_reconcilable_step_finds_its_effect_before_retrying(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"found": ref("steps.r.output.found")}).node("r", "testkit.reconcile@1")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert result.outputs == {"found": True}


async def test_timers_are_durable_and_the_deadline_ends_the_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    day = graph().node("d", DELAY, {"duration_s": 86_400}).node("a", ECHO).edge("d", "a")
    long = graph().node("d", DELAY, {"duration_s": 3 * 86_400})
    async with workers(env.client, store):
        assert (await run(env.client, store, day, TRIGGER)).status == "succeeded"
        late = await run(env.client, store, long, TRIGGER, max_run_duration_s=86_400)
    assert (late.status, late.error and late.error["code"]) == ("deadline_exceeded", "deadline_exceeded")


async def test_stop_and_fail_end_the_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    stop = graph(outputs={"n": 1}).node("l", LOOP, {"items": [1, 2]}).node("s", STOP).edge("l", "s", "body")
    fail = graph().node("f", FAIL, {"message": "no, stop"})
    async with workers(env.client, store):
        stopped = await run(env.client, store, stop, TRIGGER)
        failed = await run(env.client, store, fail, TRIGGER)
    assert (stopped.status, stopped.outputs) == ("succeeded", {"n": 1})
    assert failed.status == "failed" and failed.error and failed.error["code"] == "workflow_failed"


async def test_simulation_calls_simulate_and_records_it(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"v": ref("steps.a.output.value")}).node("a", ECHO, {"value": 5})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER, mode="simulate")
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.outputs == {"v": {"simulated": 5}}
    assert [r.outcome for r in store.steps(run_id_of(handle))] == ["simulated"]


async def test_without_an_evaluator_cel_fails_as_profile_unavailable(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("t", TRANSFORM, {"fields": {"y": cel(f"trigger.x * {EVALUATOR_ONLY}")}}, on_error="continue")
    g.settings["outputs"] = {"error": ref("steps.t.error", default="none")}
    async with workers(env.client, store, evaluate=None):
        # the test server doesn't skip schedule-to-start time: a real 2 s stands in for the 10 minutes
        result = await run(env.client, store, g, TRIGGER, cel_schedule_to_start_s=2)
    message = f"No evaluator served `{CURRENT_CEL_PROFILE}` (TimeoutError)."  # never the transport's own text
    assert result.outputs == {"error": {"code": "cel_profile_unavailable", "message": message, "attempt": 1}}


async def test_sensitive_outputs_are_redacted_in_the_projection(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("s", "testkit.sensitive@1")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    [row] = store.steps(run_id_of(handle))
    assert row.output_preview == {
        "public": "visible",
        "secret_value": "[redacted]",
        "login": {"user": "ops", "password": "[redacted]"},
    }


async def test_a_recorded_history_replays(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"doubled": ref("steps.l.output.items", default=[])})
    g.node("c", IF, {"condition": cel("trigger.x > 5")}).node("l", LOOP, {"items": [1, 2], "collect": cel("item + 1")})
    g.node("x", ECHO, {"value": ref("item")}).edge("c", "l", "true").edge("l", "x", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        history = await handle.fetch_history()
    await Replayer(workflows=[RunGraph]).replay_workflow(WorkflowHistory.from_json(handle.id, history.to_json()))
