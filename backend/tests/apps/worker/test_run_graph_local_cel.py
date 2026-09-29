# SPDX-License-Identifier: Apache-2.0
"""Local CEL (spec §5.6, §5.9 rollout): this build evaluates its profile in-process. An expression runs in the
workflow when publish classified it local and the values it reads are within the caps; everything else, and a filter
over more than 1,000 items, goes to `cel.evaluate` on the profile's queue."""

import asyncio
from typing import Any

from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime.activities import CEL_EVALUATE
from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, start, workers
from tests.support.graphs import G, cel, ref

ITEMS = {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "integer"}}}, "required": ["xs"]}


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": ITEMS, "outputs": outputs}
    return g


async def finished(env: WorkflowEnvironment, g: G, xs: list[int]) -> tuple[MemoryStore, str, Any, WorkflowHistory]:
    store = MemoryStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"xs": xs})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        history = await handle.fetch_history()
    return store, handle.id, result, history


def evaluations(history: WorkflowHistory) -> int:
    """The `cel.evaluate` requests the run sent."""
    return sum(
        e.activity_task_scheduled_event_attributes.activity_type.name == CEL_EVALUATE
        for e in history.events
        if e.HasField("activity_task_scheduled_event_attributes")
    )


async def test_cel_this_build_can_run_runs_in_the_workflow(env: WorkflowEnvironment) -> None:
    g = graph(n=ref("steps.t.output.n")).node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.xs) * 2")}})
    store, run_id, result, history = await finished(env, g, [1, 2, 3])
    assert (result.status, result.outputs) == ("succeeded", {"n": 6})
    assert [r.cel_mode for r in store.steps(run_id)] == ["local"] and evaluations(history) == 0


async def test_a_filter_over_more_than_a_thousand_items_goes_to_the_evaluator_in_chunks(
    env: WorkflowEnvironment,
) -> None:
    """Spec §6: up to 1,000 items a filter's predicate may run inline; larger lists go to `cel.evaluate`, 1,000 binding
    sets at a time, however cheap the predicate."""
    g = graph(kept=ref("steps.f.output.count"))
    g.node("f", "flow.filter@1", {"items": cel("trigger.xs"), "predicate": cel("item % 2 == 0")})
    store, run_id, result, history = await finished(env, g, list(range(1_500)))
    assert (result.status, result.outputs) == ("succeeded", {"kept": 750})
    assert [r.cel_mode for r in store.steps(run_id) if r.node_key == "f"] == ["activity"]
    assert evaluations(history) == 2 + 1  # the filter's two chunks, and `items` itself (a list past the caps)


async def test_values_past_the_caps_go_to_the_evaluator(env: WorkflowEnvironment) -> None:
    """A list of 201 items is past the 200-element cap (spec §5.6): the same expression runs in `cel.evaluate`."""
    g = graph(n=ref("steps.t.output.n")).node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.xs) * 2")}})
    store, run_id, result, history = await finished(env, g, list(range(201)))
    assert (result.status, result.outputs) == ("succeeded", {"n": 402})
    assert [r.cel_mode for r in store.steps(run_id)] == ["activity"] and evaluations(history) == 1


async def test_an_expression_only_the_evaluator_runs_goes_to_it(env: WorkflowEnvironment) -> None:
    g = graph(n=ref("steps.t.output.n")).node("t", "flow.transform@1", {"fields": {"n": cel(EVALUATOR_ONLY)}})
    store, run_id, result, history = await finished(env, g, [])
    assert (result.status, result.outputs) == ("succeeded", {"n": 1})
    assert [r.cel_mode for r in store.steps(run_id)] == ["activity"] and evaluations(history) == 1
