# SPDX-License-Identifier: Apache-2.0
"""Size claims (engine 2b spec §5.1): a value larger than 64 KiB is claimed where it's produced, by a plugin step's
activity or by `cel.evaluate`, and the workflow holds its handle. A step that reads it gets the whole value, resolved
at its activity's boundary; history never holds it."""

import asyncio
from typing import Any

from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.handles import ClaimRef
from dewpoint.engine.runtime.activities import RunResult
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.support.graphs import G, cel, ref

BLOB, ECHO = "testkit.blob@1", "testkit.echo@1"
ITEMS = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {"type": "integer"}}},
    "required": ["items"],
}


def graph(schema: dict[str, Any] | None = None, **outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": schema or {"type": "object"}, "outputs": outputs}
    return g


async def finished(
    env: WorkflowEnvironment, store: MemoryStore, g: G, trigger: dict[str, Any]
) -> tuple[WorkflowHandle[Any, Any], RunResult]:
    async with workers(env.client, store):
        handle = await start(env.client, store, g, trigger)
        return handle, await asyncio.wait_for(handle.result(), 60)


async def largest_payload(handle: WorkflowHandle[Any, Any]) -> int:
    """The largest payload any event of the run's history holds, encoded."""
    largest = 0
    async for e in handle.fetch_history_events():
        for field in e.ListFields():
            attrs = field[1]
            for name in ("input", "result", "details"):
                payloads = getattr(attrs, name, None)
                for p in getattr(payloads, "payloads", []) or []:
                    largest = max(largest, p.ByteSize())
    return largest


async def test_a_plugin_output_past_64_kib_is_claimed_and_read_whole_by_the_next_step(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(v=ref("steps.e.output.value"))
    g.node("b", BLOB, {"size": 100_000}).node("e", ECHO, {"value": ref("steps.b.output.value")}).edge("b", "e")
    handle, result = await finished(env, store, g, {})
    assert result.status == "succeeded"
    echoed = ClaimRef.of(result.outputs["v"])  # the echo's output is claimed too: it's the whole value again
    assert echoed is not None and store.claims[echoed.id].value == "x" * 100_000
    assert await largest_payload(handle) < 65_536


async def test_a_cel_result_past_64_kib_is_claimed(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(ITEMS, r=ref("steps.t.output.r"))
    g.node("t", "flow.transform@1", {"fields": {"r": cel("trigger.items.map(i, 'abcdefghij')")}})
    handle, result = await finished(env, store, g, {"items": list(range(8_000))})
    assert result.status == "succeeded", result.error
    claimed = ClaimRef.of(result.outputs["r"])
    assert claimed is not None
    held = store.claims[claimed.id]
    assert (held.value, held.sensitive_pointers) == (["abcdefghij"] * 8_000, ())
    assert await largest_payload(handle) < 65_536
