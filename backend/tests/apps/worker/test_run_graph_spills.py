# SPDX-License-Identifier: Apache-2.0
"""Spilling before failing (engine 2b spec §5.2): a command that wouldn't fit Temporal's payload limit has its largest
values written into size claims first, through `claims.spill`, in chunks under the limit, and carries their handles.
The receiving side reads them: a plugin step resolves them at its boundary, a sub-flow and a failure handler get
grants. The limits are lowered here so small values show it: the payload limit to 50,000 bytes, the inline limit
(what a value may weigh in workflow state) to 10,000."""

import asyncio
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHandle
from temporalio.converter import DataConverter
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.handles import ClaimRef
from dewpoint.engine.runtime import projection, size
from dewpoint.engine.runtime.activities import CLAIMS_SPILL, RunResult
from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
from tests.support.graphs import G, cel, ref, template

LIMIT, INLINE = 50_000, 10_000
BLOB, ECHO, LOOP, RUN = "testkit.blob@1", "testkit.echo@1", "flow.loop@1", "flow.run_workflow@1"
ITEMS = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
    "required": ["items"],
}


@pytest.fixture(autouse=True)
def lowered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(size, "PAYLOAD_BYTES", LIMIT)
    monkeypatch.setattr(size, "INLINE_LIMIT", INLINE)


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


async def finished(
    env: WorkflowEnvironment, store: MemoryStore, g: G, trigger: dict[str, Any] | None = None
) -> tuple[WorkflowHandle[Any, Any], RunResult]:
    async with workers(env.client, store):
        handle = await start(env.client, store, g, trigger or {})
        return handle, await asyncio.wait_for(handle.result(), 60)


async def spills(handle: WorkflowHandle[Any, Any]) -> int:
    return sum(
        e.activity_task_scheduled_event_attributes.activity_type.name == CLAIMS_SPILL
        for e in (await handle.fetch_history()).events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    )


def blobs(g: G, n: int, each: int) -> list[str]:
    """`n` blob steps of `each` characters: inline (under the inline limit), and together past the payload limit."""
    keys = [f"b{k}" for k in range(n)]
    for k in keys:
        g.node(k, BLOB, {"size": each})
    return keys


async def test_a_step_input_too_large_to_send_spills_and_the_step_runs(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(v=ref("steps.e.output.value"))
    keys = blobs(g, 8, 9_000)
    g.node("e", ECHO, {"value": [ref(f"steps.{k}.output.value") for k in keys]})
    for k in keys:
        g.edge(k, "e")
    handle, result = await finished(env, store, g)
    assert result.status == "succeeded", result.error
    echoed = [ClaimRef.of(v) for v in result.outputs["v"]]  # the echo's list holds undeclared items: claimed each
    assert [store.claims[h.id].value for h in echoed if h is not None] == ["x" * 9_000] * 8  # it got them whole
    assert await spills(handle) >= 2  # in chunks under the payload limit
    spilled = [c for c in store.claims.values() if c.kind == "spill"]
    assert spilled and all(c.sensitive_pointers == () and c.owner == run_id_of(handle) for c in spilled)


async def test_a_sub_flow_input_too_large_to_send_spills_and_the_sub_flow_reads_it(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    keys = [f"b{k}" for k in range(8)]
    sub = graph(n=cel(" + ".join(f"size(trigger.{k})" for k in keys)))
    sub.settings["input_schema"] = {
        "type": "object",
        "properties": {k: {"type": "string"} for k in keys},
        "required": keys,
        "additionalProperties": False,
    }
    sub.node("e", ECHO, {"value": 1})
    g = graph(n=ref("steps.r.output.n"))
    blobs(g, 8, 9_000)
    g.node(
        "r", RUN, {"workflow_id": str(store.publish(sub)), "input": {k: ref(f"steps.{k}.output.value") for k in keys}}
    )
    for k in keys:
        g.edge(k, "r")
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"n": 72_000}), result.error
    assert await spills(handle) >= 1


def items(n: int, each: int) -> list[str]:
    return [f"{i:05d}" + "x" * (each - 5) for i in range(n)]


async def test_an_item_too_large_for_a_batch_is_spilled_and_every_item_runs(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(n=ref("steps.l.output.count"))
    g.settings["input_schema"] = ITEMS
    g.node("l", LOOP, {"items": ref("trigger.items")}).node("x", ECHO, {"value": 1}).edge("l", "x", "body")
    trigger = {"items": [*items(120, 10), "y" * (LIMIT // 2), *items(10, 10)]}
    handle, result = await finished(env, store, g, trigger)
    assert (result.status, result.outputs) == ("succeeded", {"n": 131}), result.error
    ran = {r.iteration_key for r in store.steps(run_id_of(handle)) if r.node_key == "x"}
    assert ran == {f"l:{i}" for i in range(131)}


async def test_a_failure_handler_whose_input_is_too_large_gets_it_spilled(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the limits set inconsistently (stored messages up to 60,000 characters, the payload limit just above the
    run's own failed result), a 40,000-character message fits the run's result but not the handler's input: it's
    spilled, granted to the handler, and the handler runs."""
    message = "x" * 40_000
    failed = RunResult("failed", None, {"code": "workflow_failed", "message": message, "attempt": 1}, 0)
    monkeypatch.setattr(projection, "MESSAGE_LIMIT", 60_000)
    monkeypatch.setattr(
        size, "PAYLOAD_BYTES", size.encoded_bytes(failed, DataConverter.default.payload_converter) + 100
    )
    monkeypatch.setattr(size, "INLINE_LIMIT", 65_536)  # the message is a workflow value: it stays inline
    store = MemoryStore()
    g = graph()
    handler = graph().node("h", ECHO, {"value": cel("size(trigger.error.message)")})
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("b", BLOB, {"size": 40_000})
    g.node("f", "flow.fail@1", {"message": template({"ref": "steps.b.output.value"})}).edge("b", "f")
    handle, result = await finished(env, store, g)
    assert result.status == "failed" and result.error is not None and result.error["code"] == "workflow_failed"
    [(child, row)] = store.starts.items()
    assert row.kind == "failure_handler" and store.runs[child].status == "succeeded"
    assert [r.output_preview for r in store.steps(child)] == [{"value": 40_000}]
