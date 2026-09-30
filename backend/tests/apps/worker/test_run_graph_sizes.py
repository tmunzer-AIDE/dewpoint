# SPDX-License-Identifier: Apache-2.0
"""Engine 2b spec §5.2: every payload the engine sends Temporal, and every result it gets back, stays under Temporal's
payload limit once encoded. Each is checked where it's produced: too large fails its step, its loop or its run with
`payload_too_large`, never a retried or terminated workflow task. The limit is lowered here so small values show it;
test_real_server.py shows it at the real one."""

import asyncio
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime import size
from dewpoint.engine.runtime.activities import RunResult
from dewpoint.engine.runtime.size import (
    OUTPUTS_TOO_LARGE,
    PAYLOAD_TOO_LARGE,
    RUN_SNAPSHOT_TOO_LARGE,
    SNAPSHOT_TOO_LARGE,
    STEP_INPUT_TOO_LARGE,
)
from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
from tests.support.graphs import G, ref

LIMIT = 50_000
ITEMS = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}
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


async def test_a_batch_that_collected_too_much_to_return_fails_its_loop(env: WorkflowEnvironment) -> None:
    """A batch of 100 iterations collecting 1,000 characters each: it reports what it used, and its loop fails; no
    collected item is dropped silently."""
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", LOOP, {"items": list(range(150)), "collect": ref("steps.b.output.value")}, on_error="continue")
    g.node("b", BLOB, {"size": 1_000}).edge("l", "b", "body")
    _, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
    assert result.iterations == 100  # the batch reported what it used


async def children_started(handle: WorkflowHandle[Any, Any]) -> int:
    events = (await handle.fetch_history()).events
    return sum(e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED for e in events)


async def activities_scheduled(handle: WorkflowHandle[Any, Any], name: str) -> int:
    return sum(
        e.activity_task_scheduled_event_attributes.activity_type.name == name
        for e in (await handle.fetch_history()).events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    )


async def test_a_step_input_too_large_to_send_fails_the_step_before_any_attempt(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(code=ref("steps.e.error.code", default="none"))
    g.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
    g.node("e", ECHO, {"value": [ref("steps.a.output.value"), ref("steps.b.output.value")]}, on_error="continue")
    g.edge("a", "e").edge("b", "e")
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


async def test_a_sub_flow_input_too_large_to_send_fails_its_step_and_starts_nothing(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    sub = graph().node("e", ECHO, {"value": 1})
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
    g.node(
        "r",
        RUN,
        {
            "workflow_id": str(store.publish(sub)),
            "input": {"a": ref("steps.a.output.value"), "b": ref("steps.b.output.value")},
        },
        on_error="continue",
    )
    g.edge("a", "r").edge("b", "r")
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": PAYLOAD_TOO_LARGE}, 0)
    assert store.starts == {}  # no sub-run


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


async def test_an_item_too_large_for_a_batch_fails_its_loop_after_the_items_before_it(env: WorkflowEnvironment) -> None:
    """It's never dropped: the loop fails with `payload_too_large` once it reaches it."""
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.settings["input_schema"] = ITEMS
    g.node("l", LOOP, {"items": ref("trigger.items"), "collect": ref("steps.x.output.value")}, on_error="continue")
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    trigger = {"items": [*items(120, 10), "y" * (LIMIT // 2), *items(10, 10)]}
    async with workers(env.client, store):
        handle = await start(env.client, store, g, trigger)
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
    ran = {r.iteration_key for r in store.steps(run_id_of(handle)) if r.node_key == "x"}
    assert ran == {f"l:{i}" for i in range(120)}  # every item before it, and none after


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


async def test_a_failure_handler_whose_input_is_too_large_never_starts_and_says_why(env: WorkflowEnvironment) -> None:
    """Its input carries what the run learned is sensitive, to mask it too: past the limit, the handler's row records
    `payload_too_large`, and the run's own end stands."""
    store = MemoryStore()
    g = graph()
    g.settings["input_schema"] = {
        "type": "object",
        "properties": {"key": {"type": "string", "x-sensitive": True}},
        "required": ["key"],
    }
    g.settings["failure_handler"] = str(store.publish(graph().node("h", ECHO, {"value": 1})))
    g.node("f", "flow.fail@1", {"message": "it went wrong"})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"key": "k" * LIMIT})
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "failed" and result.error is not None and result.error["code"] == "workflow_failed"
    [(child, row)] = store.starts.items()
    assert row.kind == "failure_handler"
    assert (store.runs[child].status, store.runs[child].error_code) == ("failed", PAYLOAD_TOO_LARGE)
    assert store.runs[run_id_of(handle)].status == "failed"
    assert await children_started(handle) == 0  # it was never sent
