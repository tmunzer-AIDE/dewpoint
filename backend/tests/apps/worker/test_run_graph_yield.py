# SPDX-License-Identifier: Apache-2.0
"""The yield policy inside RunGraph (spec §5.6): one budget per workflow task, however many units share it. A view's
binding is charged as the values it binds, whether the expression then runs here or in `cel.evaluate`; a local
evaluation is charged its stored bounds. When the budget is spent, the work waits for a 1 ms durable timer. An
execution's first workflow task also starts it, so it gets a tenth of the budget."""

import asyncio
from collections import defaultdict
from typing import Any

import pytest
from temporalio import workflow
from temporalio.api.enums.v1 import EventType
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.cel import route
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.engine.runtime import execution
from tests.apps.worker.harness import CATALOG, MemoryStore, run_id_of, start, workers
from tests.engine.cel.test_gate_cost import ADVERSARIAL, AT_CAPS
from tests.support.graphs import G, cel

S = {"type": "string"}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "s": S,
        "needle": S,
        "xs": {"type": "array", "items": {"type": "integer"}},
        "c1": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}},
    },
    "required": ["s", "needle", "xs", "c1"],
}
TRIGGER = {"s": AT_CAPS["s"], "needle": AT_CAPS["needle"], "xs": list(range(450)), "c1": AT_CAPS["c1"]}
TASKS: dict[int, list[tuple[str, int]]] = defaultdict(list)  # history length -> ("bind", nodes) / ("eval", work)


class Recording(route.YieldBudget):
    """Records every charge under the workflow task it was made in (its history length). A replay makes the same
    charges again, for tasks already recorded: those aren't recorded twice."""

    def charge(self, record: Any = None, *, nodes: int = 0, sent: int = 0, structure: int = 0) -> None:
        if not workflow.unsafe.is_replaying():
            task = TASKS[workflow.info().get_current_history_length()]
            if nodes:
                task.append(("bind", nodes))
            if record is not None:
                task.append(("eval", record.work or 0))
        super().charge(record, nodes=nodes, sent=sent, structure=structure)


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> dict[int, list[tuple[str, int]]]:
    """The engine modules are passed through the sandbox, so this reaches RunGraph's budget too."""
    TASKS.clear()
    monkeypatch.setattr(execution, "YieldBudget", Recording)
    return TASKS


def local_cel(monkeypatch: pytest.MonkeyPatch) -> None:
    """What setting `LOCAL_CEL_PROFILE` does in a build (Task 11)."""
    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", CURRENT_CEL_PROFILE)


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


def heaviest_search() -> str:
    """The heaviest substring search that still publishes local: about three quarters of a workflow task's work
    budget per evaluation."""
    best = ""
    for n in range(1, 60):
        g = graph().node("x", "flow.transform@1", {"fields": {"r": cel(ADVERSARIAL["search"](n))}})
        result = validate(g.build(), ValidationContext(catalog=CATALOG, subflows={}))
        if any(d.severity == "error" for d in result.diagnostics) or result.expressions[0].mode != "local":
            break
        best = ADVERSARIAL["search"](n)
    assert best
    return best


async def finished(env: WorkflowEnvironment, store: MemoryStore, g: G, *, cache: int = 1000) -> tuple[Any, Any]:
    async with workers(env.client, store, cache=cache):
        handle = await start(env.client, store, g, TRIGGER)
        return handle, await asyncio.wait_for(handle.result(), 120)


@pytest.mark.parametrize("cache", [1000, 0], ids=["cached", "replaying every task"])
async def test_concurrent_evaluations_share_one_budget_per_workflow_task(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, recorded: dict[int, list[tuple[str, int]]], cache: int
) -> None:
    """Ten iterations run at once, each evaluating about three quarters of the work budget: each workflow task
    evaluates one. Waiting units share one timer and check again once it fires. With no worker cache, every workflow
    task replays the run's history: the budget, keyed on the history length, decides the same way."""
    local_cel(monkeypatch)
    store = MemoryStore()
    g = graph(count=cel("size(steps.l.output.items)"))
    g.node("l", "flow.loop@1", {"items": list(range(20)), "concurrency": 10, "collect": cel("steps.x.output.r")})
    g.node("x", "flow.transform@1", {"fields": {"r": cel(heaviest_search())}}).edge("l", "x", "body")
    handle, result = await finished(env, store, g, cache=cache)
    assert (result.status, result.outputs) == ("succeeded", {"count": 20})
    assert {r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == "x"} == {"local"}
    evaluating = [[w for kind, w in t if kind == "eval"] for t in recorded.values()]
    evaluating = [works for works in evaluating if works]
    assert sum(len(works) for works in evaluating) >= 20 and len(evaluating) >= 10  # the budget split them
    assert all(len(works) == 1 or sum(works) <= route.YIELD_WORK for works in evaluating)


async def test_a_local_filter_evaluates_its_items_within_the_budget(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, recorded: dict[int, list[tuple[str, int]]]
) -> None:
    """A filter's 450 items are 450 evaluations: at most 130 in one workflow task (they used to run all at once)."""
    local_cel(monkeypatch)
    store = MemoryStore()
    g = graph(kept=cel("steps.f.output.count"))
    g.node("f", "flow.filter@1", {"items": cel("trigger.xs"), "predicate": cel("item % 3 == 0")})
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 150})
    assert [r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == "f"] == ["local"]
    counts = [sum(kind == "eval" for kind, _ in t) for t in recorded.values()]
    assert max(counts) <= route.YIELD_EVALUATIONS and sum(counts) >= 450


async def test_binding_is_charged_when_the_evaluator_runs_the_expression(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, recorded: dict[int, list[tuple[str, int]]]
) -> None:
    """A build without local CEL: each of the filter's 20 views still binds `trigger.c1` (16,081 values) in the
    workflow. A workflow task binds up to the budget, and the next view waits for the next task. The run's first task
    binds one: it gets a tenth of the budget, and its first binding always runs."""
    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", None)
    store = MemoryStore()
    g = graph(kept=cel("steps.f.output.count"))
    g.node("f", "flow.filter@1", {"items": list(range(20)), "predicate": cel("size(trigger.c1) > item")})
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 20})
    assert [r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == "f"] == ["activity"]
    binding = [[n for kind, n in t if kind == "bind" and n > 16_000] for t in recorded.values()]  # the 20 views
    binding = [nodes for nodes in binding if nodes]
    assert [len(nodes) for nodes in binding] == [1, 5, 5, 5, 4]  # 4 fit in 65,000 values, the 5th passes it
    assert all(sum(nodes[:-1]) < route.YIELD_NODES for nodes in binding)  # the last one may pass it: then it yields


async def test_an_executions_first_workflow_task_leaves_heavy_cel_to_the_next_one(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, recorded: dict[int, list[tuple[str, int]]]
) -> None:
    """The first workflow task also loads and compiles the version, so it gets a tenth of the budget (spec §5.6): a
    light evaluation runs in it at once, with no timer, and a heavy one waits for the next task."""
    local_cel(monkeypatch)
    store = MemoryStore()
    g = graph(light=cel("steps.a.output.r"), heavy=cel("steps.b.output.r"))
    g.node("a", "flow.transform@1", {"fields": {"r": cel("size(trigger.needle)")}})
    g.node("b", "flow.transform@1", {"fields": {"r": cel(heaviest_search())}})
    handle, result = await finished(env, store, g)
    assert result.status == "succeeded"
    assert {r.cel_mode for r in store.steps(run_id_of(handle))} == {"local"}
    first, *later = [[w for kind, w in recorded[length] if kind == "eval"] for length in sorted(recorded)]
    assert len(first) == 1  # the light one: the heavy one waited
    tenth = route.YIELD_WORK // route.STARTUP_SHARE
    assert first[0] <= tenth
    assert [w for works in later for w in works if w > tenth]  # the heavy one, in a later task


async def test_ready_steps_spread_over_workflow_tasks_by_their_structural_units(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A workflow task's CPU (engine 2b spec §5.3): each step unit charges its work and its view before it starts, and
    a take takes only what the task's share allows. With the share lowered, 60 ready steps (each 1,000 units and 4
    per step of its view) go out over many workflow tasks, not one; every one runs."""
    monkeypatch.setattr(route, "YIELD_STRUCTURE", 12_000)
    store = MemoryStore()
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {}}
    for n in range(60):
        g.node(f"a{n}", "testkit.echo@1", {"value": n})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "succeeded"
    tasks = {
        e.activity_task_scheduled_event_attributes.workflow_task_completed_event_id
        for e in (await handle.fetch_history()).events
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
        and e.activity_task_scheduled_event_attributes.activity_type.name == "testkit.echo.v1"
    }
    assert len(tasks) >= 6  # 60 steps of 1,240 units each (its view: 60 steps): about 9 per task
    assert len(store.steps(run_id_of(handle))) == 60
