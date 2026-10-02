# SPDX-License-Identifier: Apache-2.0
"""Engine 2b spec §5.2: every payload the engine sends Temporal, and every result it gets back, stays under Temporal's
payload limit once encoded. Each is checked where it's produced: too large fails its step, its loop or its run with
`payload_too_large`, never a retried or terminated workflow task. A command spills its largest values first
(test_run_graph_spills.py): what's here is what spilling can't rescue, or doesn't apply to. The limit is lowered here
so small values show it; test_real_server.py shows it at the real one."""

import asyncio
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from dewpoint.core.claims import secret_index
from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT
from dewpoint.engine.cel import route
from dewpoint.engine.runtime import projection, size
from dewpoint.engine.runtime.activities import RunResult
from dewpoint.engine.runtime.size import (
    OUTPUTS_TOO_LARGE,
    PAYLOAD_TOO_LARGE,
    RESULT_TOO_LARGE,
    RUN_SNAPSHOT_TOO_LARGE,
    SNAPSHOT_TOO_LARGE,
    STEP_INPUT_TOO_LARGE,
)
from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
from tests.support.graphs import G, cel, nid, ref, template

LIMIT = 50_000
ITEMS = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
    "required": ["items"],
}
BLOB, ECHO, LOOP, RUN = "testkit.blob@1", "testkit.echo@1", "flow.loop@1", "flow.run_workflow@1"


@pytest.fixture(autouse=True)
def lowered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(size, "PAYLOAD_BYTES", LIMIT)


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


async def finished(env: WorkflowEnvironment, store: MemoryStore, g: G) -> tuple[WorkflowHandle[Any, Any], RunResult]:
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        return handle, await asyncio.wait_for(handle.result(), 60)


async def test_a_step_output_too_large_to_record_fails_the_step_once(env: WorkflowEnvironment) -> None:
    """Its node ran: the row says so (`applied`), and nothing repeats it."""
    store = MemoryStore()
    g = graph(code=ref("steps.b.error.code", default="none"))
    g.node("b", BLOB, {"size": LIMIT}, on_error="continue")
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
    [row] = store.steps(run_id_of(handle))
    assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", PAYLOAD_TOO_LARGE, "applied")


async def test_outputs_too_large_to_return_fail_the_run(env: WorkflowEnvironment) -> None:
    """Each output fits; together they don't. The run fails, and its result carries no outputs."""
    store = MemoryStore()
    g = graph(a=ref("steps.a.output.value"), b=ref("steps.b.output.value"))
    g.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("failed", None)
    assert result.error is not None and (result.error["code"], result.error["message"]) == (
        PAYLOAD_TOO_LARGE,
        OUTPUTS_TOO_LARGE,
    )
    summary = store.runs[run_id_of(handle)]
    assert (summary.status, summary.error_code) == ("failed", PAYLOAD_TOO_LARGE)


async def test_a_sub_flow_whose_outputs_are_too_large_fails_its_step(env: WorkflowEnvironment) -> None:
    """The sub-run fails where its result is produced, so its parent's step fails with it."""
    store = MemoryStore()
    sub = graph(a=ref("steps.a.output.value"), b=ref("steps.b.output.value"))
    sub.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(store.publish(sub)), "input": {}}, on_error="continue")
    _, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
    [(child, _)] = store.starts.items()
    assert (store.runs[child].status, store.runs[child].error_code) == ("failed", PAYLOAD_TOO_LARGE)


async def test_a_batch_that_collected_more_than_it_could_return_spills_it(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch of 100 iterations collecting 1,000 characters each: its collection past the inline limit goes to
    segment claims (engine 2b spec §5.3), so its result stays small, and the loop never fails for what it collected.
    (The inline limit is lowered with the payload limit, as they relate in production.)"""
    monkeypatch.setattr(size, "INLINE_LIMIT", 10_000)
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"), n=ref("steps.l.output.count", default=0))
    g.node("l", LOOP, {"items": list(range(150)), "collect": ref("steps.b.output.value")}, on_error="continue")
    g.node("b", BLOB, {"size": 1_000}).edge("l", "b", "body")
    _, result = await finished(env, store, g)
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "none", "n": 150}, 150)
    assert [c for c in store.claims.values() if c.kind == "segment"]


async def children_started(handle: WorkflowHandle[Any, Any]) -> int:
    events = (await handle.fetch_history()).events
    return sum(e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED for e in events)


async def activities_scheduled(handle: WorkflowHandle[Any, Any], name: str) -> int:
    return sum(
        e.activity_task_scheduled_event_attributes.activity_type.name == name
        for e in (await handle.fetch_history()).events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    )


async def test_a_step_input_that_cant_be_spilled_fails_the_step_before_any_attempt(env: WorkflowEnvironment) -> None:
    """Engine 2b spec §5.2: a step's input spills its largest values before it fails (test_run_graph_spills.py). A
    value the workflow made that one spill can't hold, a single string near the limit, still fails the step."""
    store = MemoryStore()
    g = graph(code=ref("steps.e.error.code", default="none"))
    g.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
    joined = template({"ref": "steps.a.output.value"}, {"ref": "steps.b.output.value"})
    g.node("e", ECHO, {"value": joined}, on_error="continue").edge("a", "e").edge("b", "e")
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "e"]
    assert (row.attempt, row.status, row.error_code, row.error_message) == (
        1,
        "failed",
        PAYLOAD_TOO_LARGE,
        STEP_INPUT_TOO_LARGE,
    )
    assert await activities_scheduled(handle, "testkit.echo.v1") == 0  # never sent


def items(n: int, each: int) -> list[str]:
    return [f"{i:05d}" + "x" * (each - 5) for i in range(n)]


async def test_a_batch_is_cut_by_bytes_and_keeps_every_item_in_order(env: WorkflowEnvironment) -> None:
    """A batch carries the trigger too: 150 items of 250 characters each fit about 49 to a batch under the limit, not
    100 (the count cut). Every item is still run once, in order."""
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"))
    g.settings["input_schema"] = ITEMS
    g.node("l", LOOP, {"items": ref("trigger.items"), "collect": ref("steps.x.output.value")})
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    trigger = {"items": items(150, 250)}
    async with workers(env.client, store):
        handle = await start(env.client, store, g, trigger)
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"items": trigger["items"]})
    assert await children_started(handle) > 2  # cut by bytes: the count alone would have made two


async def test_a_snapshot_too_large_to_carry_on_fails_the_run(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2b-1a's promise for continue-as-new (spec §5.3): a clean `snapshot_too_large`, never a retried workflow task."""
    monkeypatch.setattr(size, "SNAPSHOT_BYTES", 5_000)
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"))
    g.node("l", LOOP, {"items": list(range(40)), "collect": ref("steps.x.output.value")})
    g.node("x", ECHO, {"value": "v" * 200}).edge("l", "x", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, checkpoint_events=120)
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "failed" and result.error is not None
    assert (result.error["code"], result.error["message"]) == (SNAPSHOT_TOO_LARGE, RUN_SNAPSHOT_TOO_LARGE)
    assert store.runs[run_id_of(handle)].error_code == SNAPSHOT_TOO_LARGE


async def test_a_batch_whose_snapshot_is_too_large_fails_its_loop(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(size, "SNAPSHOT_BYTES", 5_000)
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", LOOP, {"items": list(range(150)), "collect": ref("steps.x.output.value")}, on_error="continue")
    g.node("x", ECHO, {"value": "v" * 200}).edge("l", "x", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, checkpoint_events=120)
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"code": SNAPSHOT_TOO_LARGE})


async def scheduled_in(handle: WorkflowHandle[Any, Any], name: str) -> list[int]:
    """The workflow task that scheduled each `name` activity, in order."""
    return [
        e.activity_task_scheduled_event_attributes.workflow_task_completed_event_id
        for e in (await handle.fetch_history()).events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
        and e.activity_task_scheduled_event_attributes.activity_type.name == name
    ]


@pytest.mark.parametrize("cache", [1000, 0], ids=["cached", "replaying every task"])
async def test_a_workflow_task_sends_at_most_its_bytes_of_every_command(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, cache: int
) -> None:
    """Engine 2b spec §5.2's per-task invariant, with the budget lowered: three step inputs of about 30 KB, ready
    together, pass a 70 KB budget, so the third waits for the next workflow task; replay decides the same."""
    monkeypatch.setattr(route, "YIELD_SEND_BYTES", 70_000)
    store = MemoryStore()
    g = graph()
    g.node("b", BLOB, {"size": 30_000})
    for k in "xyz":
        g.node(k, ECHO, {"value": ref("steps.b.output.value")}).edge("b", k)
    async with workers(env.client, store, cache=cache):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "succeeded", result.error
    assert {r.node_key for r in store.steps(run_id_of(handle)) if r.status == "succeeded"} == {"b", *"xyz"}
    tasks = await scheduled_in(handle, "testkit.echo.v1")
    assert len(tasks) == 3 and len(set(tasks)) == 2


SECRET = "testkit.secret_blob@1"


async def test_a_step_whose_secrets_would_pass_the_index_bound_fails(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Engine 2b spec §3.7: a run tree's secret index is bounded, and shared by its sub-flows and batches. The step
    whose sensitive output would pass the bound fails once (its node ran, so its outcome stands), its output goes
    nowhere, and the index keeps what it had."""
    monkeypatch.setattr(secret_index, "MAX_BYTES", 5_000)
    store = MemoryStore()
    g = graph(code=ref("steps.b.error.code", default="none"))
    g.node("a", SECRET, {"seed": "a", "size": 3_000})
    g.node("b", SECRET, {"seed": "b", "size": 3_000}, on_error="continue").edge("a", "b")
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": SECRET_INDEX_LIMIT})
    assert store.index_of[run_id_of(handle)] == {"a" + "s" * 2_999}
    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "b"]
    assert (row.status, row.error_code, row.outcome, row.output_preview) == (
        "failed",
        SECRET_INDEX_LIMIT,
        "applied",
        None,
    )


def sensitive_child(store: MemoryStore) -> str:
    child = G()
    child.settings = {
        "input_schema": {"type": "object", "properties": {"s": {"type": "string", "x-sensitive": True}},
                         "required": ["s"], "additionalProperties": False},
        "outputs": {},
    }  # fmt: skip
    child.node("e", ECHO, {"value": 1})
    return str(store.publish(child))


@pytest.mark.parametrize("path", ["cel", "filter", "sub_flow"])
async def test_secrets_past_the_index_bound_fail_their_step_with_its_code_on_every_path(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    """The review's I4: §3.7's bound fails the step that would pass it with `secret_index_limit`, never retried, on
    every path that extends the index: a CEL result read from sensitive data (claimed with taint), a filter's kept
    items under a sensitive predicate, a sub-flow's sensitive input."""
    monkeypatch.setattr(secret_index, "MAX_BYTES", 5_000)
    store = MemoryStore()
    g = graph(code=ref("steps.b.error.code", default="none"))
    g.node("a", SECRET, {"seed": "a", "size": 3_000})  # indexed: 3,000 of the 5,000 bytes
    if path == "cel":
        g.node("b", "flow.transform@1", {"fields": {"v": cel("steps.a.output.token + 'x'")}}, on_error="continue")
    elif path == "filter":
        g.settings["declassify"] = [{"node": str(nid("b")), "field": "/predicate"}]
        kept = {"items": ["q" * 2_500, "r" * 2_500], "predicate": cel("size(steps.a.output.token) > 0")}
        g.node("b", "flow.filter@1", kept, on_error="continue")
    else:
        g.node("p", BLOB, {"size": 3_000}).edge("a", "p")
        sub = {"workflow_id": sensitive_child(store), "input": {"s": ref("steps.p.output.value")}}
        g.node("b", RUN, sub, on_error="continue").edge("p", "b")
    g.edge("a", "b")
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": SECRET_INDEX_LIMIT}), result.error
    assert store.index_of[run_id_of(handle)] == {"a" + "s" * 2_999}  # nothing past the bound was added


async def test_a_result_past_the_limit_anyway_ends_the_run_as_a_bug(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every final result is checked, a failure's too. With the limits set inconsistently (a 6,000-byte payload limit,
    and stored messages up to 10,000 characters), a step's 5,500-character output fits in its result, but a failure's
    message built from it doesn't fit in the failed run's: the run ends `internal_error`, with no outputs, rather than
    retry its workflow task."""
    monkeypatch.setattr(size, "PAYLOAD_BYTES", 6_000)
    monkeypatch.setattr(projection, "MESSAGE_LIMIT", 10_000)
    store = MemoryStore()
    g = graph().node("a", BLOB, {"size": 5_500})
    g.node("f", "flow.fail@1", {"message": template({"ref": "steps.a.output.value"}, "n" * 400)}).edge("a", "f")
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("failed", None)
    assert result.error is not None and (result.error["code"], result.error["message"]) == (
        "internal_error",
        RESULT_TOO_LARGE,
    )
    assert store.runs[run_id_of(handle)].error_code == "internal_error"
