# SPDX-License-Identifier: Apache-2.0
"""The live-state budget on Temporal (engine 2b spec §5.3, §5.4). Past it, containers are claimed through
`claims.spill` and read back by handle; a result that would pass it is claimed before it merges; and while the state
is past it, a step is sent the 1 KiB floor, so its activity claims what's larger. The budget is lowered so small
values show it. Every run ends with the values its outputs read."""

import asyncio
from typing import Any

import pytest
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.handles import ClaimRef, resolve_value
from dewpoint.engine.runtime import scheduler, size
from dewpoint.engine.runtime.activities import RunResult
from tests.apps.worker.harness import TENANT, MemoryStore, run_id_of, start, workers
from tests.support.graphs import G, cel, ref

BLOB, ECHO, LOOP = "testkit.blob@1", "testkit.echo@1", "flow.loop@1"


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


async def finished(env: WorkflowEnvironment, store: MemoryStore, g: G) -> tuple[WorkflowHandle[Any, Any], RunResult]:
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        return handle, await asyncio.wait_for(handle.result(), 60)


async def read(store: MemoryStore, run_id: str, value: Any) -> Any:
    """`value` with its handles resolved, as the run may read them."""

    async def fetch(claim_id: str) -> Any:
        return await store.fetch(TENANT, run_id, claim_id)

    return (await resolve_value(value, fetch)).value


def spilled(store: MemoryStore) -> list[Any]:
    return [c.value for c in store.claims.values() if c.kind == "spill"]


async def test_results_past_the_budget_are_claimed_and_read_back_whole(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    store = MemoryStore()
    keys = [f"b{k}" for k in range(15)]
    g = graph(**{k: ref(f"steps.{k}.output.value") for k in keys})
    for n, k in enumerate(keys):
        g.node(k, BLOB, {"size": 600 + n})
        if n:
            g.edge(keys[n - 1], k)  # one after another: the result set is claimed again as it grows
    handle, result = await finished(env, store, g)
    assert result.status == "succeeded", result.error
    assert await read(store, run_id_of(handle), result.outputs) == {k: "x" * (600 + n) for n, k in enumerate(keys)}
    forwarding = [v for v in spilled(store) if isinstance(v, dict) and any(ClaimRef.of(x) for x in v.values())]
    assert forwarding  # a later claim of the root's results reads the earlier ones through it


async def test_a_batch_child_reads_a_claimed_result_of_its_enclosing_scope(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    store = MemoryStore()
    g = graph(sizes=ref("steps.l.output.items"))
    g.node("a", BLOB, {"size": 1_500}).node("b", BLOB, {"size": 1_600}).edge("a", "b")
    g.node("l", LOOP, {"items": list(range(150)), "collect": cel("size(steps.a.output.value)")}).edge("b", "l")
    g.node("x", ECHO, {"value": 1}).edge("l", "x", "body")  # `a`'s result is in the root's claim by then
    _, result = await finished(env, store, g)
    assert result.status == "succeeded", result.error
    assert result.outputs == {"sizes": [1_500] * 150}


async def test_a_result_that_would_pass_the_budget_is_claimed_before_it_merges(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both steps were sent under the budget, so their activities kept 2,500 characters inline; the second to merge
    would pass it, so its result is claimed first, and what merges is its handle."""
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    store = MemoryStore()
    g = graph(a=ref("steps.a.output.value"), b=ref("steps.b.output.value"))
    g.node("a", BLOB, {"size": 2_500}).node("b", "testkit.slow_echo@1", {"seconds": 0.5, "value": "y" * 2_500})
    handle, result = await finished(env, store, g)
    assert result.status == "succeeded", result.error
    assert await read(store, run_id_of(handle), result.outputs) == {"a": "x" * 2_500, "b": "y" * 2_500}
    assert "y" * 2_500 in spilled(store)  # claimed alone, before it merged
    assert not [v for v in spilled(store) if isinstance(v, dict) and "a" in v]  # no container needed claiming


async def test_past_the_budget_a_step_is_sent_the_floor_and_its_activity_claims_more(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a budget nothing can bring the state under, every step is sent the 1 KiB floor (engine 2b spec §5.4)."""
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 0)
    store = MemoryStore()
    g = graph(v=ref("steps.b.output.value"))
    g.node("b", BLOB, {"size": 2_000})
    _, result = await finished(env, store, g)
    assert result.status == "succeeded", result.error
    claimed = ClaimRef.of(result.outputs["v"])
    assert claimed is not None and store.claims[claimed.id].value == "x" * 2_000


async def test_an_inline_item_list_past_the_budget_is_claimed_and_the_loop_carries_on(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    store = MemoryStore()
    items = [f"{i:03d}" + "i" * 197 for i in range(20)]
    g = graph(sizes=ref("steps.l.output.items"), n=ref("steps.l.output.count"))
    g.node("l", LOOP, {"items": items, "collect": cel("size(item)")}).node("x", ECHO, {"value": 1})
    g.edge("l", "x", "body")
    _, result = await finished(env, store, g)
    assert result.status == "succeeded", result.error
    assert result.outputs == {"sizes": [200] * 20, "n": 20}
    assert items in spilled(store)  # the list went to a claim; the loop read the rest by handle


async def test_a_list_past_one_spill_is_written_in_parts_and_joined(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Its claim still addresses each item by position (engine 2b spec §5.3)."""
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    monkeypatch.setattr(size, "PAYLOAD_BYTES", 20_000)
    store = MemoryStore()
    items = ["i" * (1_000 + i) for i in range(30)]  # each item its own size: its position shows
    g = graph(sizes=ref("steps.l.output.items"))
    g.settings["input_schema"] = {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "string"}}},
        "required": ["items"],
    }
    g.node("l", LOOP, {"items": ref("trigger.items"), "collect": cel("size(item)")}).node("x", ECHO, {"value": 1})
    g.edge("l", "x", "body")
    async with workers(env.client, store):  # the test's trigger isn't admitted: it starts inline, past one spill
        handle = await start(env.client, store, g, {"items": items})
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "succeeded", result.error
    assert result.outputs == {"sizes": [1_000 + i for i in range(30)]}
    assert items in spilled(store)  # joined from its parts


async def test_a_batched_loop_collecting_past_the_budget_ends_with_one_claim_of_its_items(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each batch writes segments its parent's loop names, and returns its collection; the parent assembles the whole
    list into one claim, read back whole."""
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 3_000)
    store = MemoryStore()
    items = [f"{i:03d}" + "c" * 97 for i in range(150)]
    g = graph(items=ref("steps.l.output.items"), n=ref("steps.l.output.count"))
    g.node("l", LOOP, {"items": items, "collect": ref("item")}).node("x", ECHO, {"value": 1}).edge("l", "x", "body")
    handle, result = await finished(env, store, g)
    assert result.status == "succeeded", result.error
    claimed = ClaimRef.of(result.outputs["items"])
    assert claimed is not None and result.outputs["n"] == 150
    assert await read(store, run_id_of(handle), result.outputs["items"]) == items
    assert [c for c in store.claims.values() if c.kind == "segment"]


async def test_an_inline_loop_whose_values_and_failures_spill_reads_them_back(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every third iteration fails; the others collect 150 characters. Past the budget both collections spill, and
    the loop's output reads back: nulls where iterations failed, and the failures in index order."""
    monkeypatch.setattr(scheduler, "LIVE_BUDGET", 2_000)
    store = MemoryStore()
    g = graph(out=ref("steps.l.output"))
    g.node("l", LOOP, {"items": list(range(40)), "collect": ref("steps.x.output.value"), "on_item_error": "continue",
                       "concurrency": 4})  # fmt: skip
    g.node("x", BLOB, {"size": 150}).node(
        "y", "testkit.slow_echo@1", {"seconds": 0, "value": 1, "fail": cel("index % 3 == 0")}
    )
    g.edge("l", "x", "body").edge("x", "y")
    handle, result = await finished(env, store, g)
    assert result.status == "succeeded", result.error
    got = await read(store, run_id_of(handle), result.outputs["out"])
    failed = [i for i in range(40) if i % 3 == 0]
    assert got["items"] == [None if i in failed else "x" * 150 for i in range(40)]
    assert [f["index"] for f in got["failures"]] == failed and got["count"] == 40
    assert [c for c in store.claims.values() if c.kind == "segment"]
