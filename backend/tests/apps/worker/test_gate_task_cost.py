# SPDX-License-Identifier: Apache-2.0
"""Gate 7b (spec §5.6, §5.9): the workflow-task half of gate 7. Each adversarial load of the in-process gate, at its
heaviest form that still publishes local, runs inside RunGraph: a loop of 20 iterations, 10 at a time, evaluating it
in-process. The worker's task executor measures the CPU of every workflow activation, and none may pass the 1 s
target, against Temporal's 10 s workflow-task timeout. Linux (the CEL gate job) is authoritative. Results go to
$DEWPOINT_CEL_GATE_RESULTS/task_cost.json when set, to tune the thresholds."""

import asyncio
import concurrent.futures
import json
import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from dewpoint.apps.worker.activities import cel_activity, engine_activities
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.engine.runtime import execution
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import CATALOG, TESTKIT, MemoryStore, in_process, internal, run_id_of, start
from tests.engine.cel.test_gate_cost import ADVERSARIAL, AT_CAPS, BINDING, TASK_CPU_TARGET_S, WORST
from tests.support.graphs import G, cel
from tests.support.keys import FIXTURE_CONVERTER

S = {"type": "string"}
INTS = {"type": "array", "items": {"type": "integer"}}


def declared(value: dict[str, Any], each: dict[str, Any]) -> dict[str, Any]:
    """A map with every key declared: a position no schema declares is tainted and never runs local (engine 2b spec
    §4.1), so this is how a map at the cap reaches a local expression."""
    return {"type": "object", "properties": dict.fromkeys(sorted(value), each), "additionalProperties": False}


SCHEMA: dict[str, Any] = {  # AT_CAPS, typed as publish sees it: every list a proven list, every position declared
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"mac": S, "type": S},
                "required": ["mac", "type"],
                "additionalProperties": False,
            },
        },
        "m": declared(AT_CAPS["m"], {"type": "integer"}),
        "s": S,
        "needle": S,
        "texts": {"type": "array", "items": S},
        "c1": {"type": "array", "items": INTS},
        "c2": {"type": "array", "items": INTS},
        "dense": declared(AT_CAPS["dense"], INTS),
    },
    "required": ["events", "m", "s", "needle", "texts", "c1", "c2", "dense"],
    "additionalProperties": False,
}


class Timed(concurrent.futures.ThreadPoolExecutor):
    """Runs each workflow activation and records its CPU time: what one workflow task costs the worker."""

    def __init__(self) -> None:
        super().__init__(max_workers=4)
        self.cpu: list[float] = []

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> concurrent.futures.Future[Any]:
        def timed() -> Any:
            started = time.thread_time()
            try:
                return fn(*args, **kwargs)
            finally:
                self.cpu.append(time.thread_time() - started)

        return super().submit(timed)


def graph(expr: str | None = None) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": {}}
    if expr is not None:
        g.node("x", "flow.transform@1", {"fields": {"r": cel(expr)}})
    return g


def publishes_local(expr: str) -> bool:
    result = validate(graph(expr).build(), ValidationContext(catalog=CATALOG, subflows={}))
    return not any(d.severity == "error" for d in result.diagnostics) and result.expressions[0].mode == "local"


def heaviest(template: Callable[[int], str]) -> str:
    """The largest n that still publishes local: it maxes out the work bound (or the expression or pattern length)."""
    best = ""
    for n in range(1, 400):
        if not publishes_local(template(n)):
            break
        best = template(n)
    assert best, template(1)
    return best


def loads() -> Iterator[tuple[str, str]]:
    for i, expr in enumerate(WORST):
        assert publishes_local(expr), expr  # what runs in the evaluator costs the workflow task nothing to measure
        yield f"worst{i}", expr
    for name, template in ADVERSARIAL.items():
        yield name, heaviest(template)
    assert publishes_local(BINDING), BINDING
    yield "binding", BINDING


LOADS = dict(loads())
REPORT: dict[str, Any] = {"profile": CURRENT_CEL_PROFILE, "target_s": TASK_CPU_TARGET_S, "loads": {}}


@pytest.fixture(scope="module", autouse=True)
def report() -> Iterator[None]:
    yield
    if directory := os.environ.get("DEWPOINT_CEL_GATE_RESULTS"):
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "task_cost.json"), "w") as f:
            json.dump(REPORT, f, indent=1, sort_keys=True)


@pytest.mark.parametrize("name", list(LOADS))
async def test_no_workflow_task_passes_the_cpu_target(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    expr = LOADS[name]
    assert publishes_local(expr), expr[:80]
    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", CURRENT_CEL_PROFILE)  # what the build constant does
    store = MemoryStore()
    g = graph().node("l", "flow.loop@1", {"items": list(range(20)), "concurrency": 10})
    g.node("x", "flow.transform@1", {"fields": {"r": cel(expr)}}).edge("l", "x", "body")
    with Timed() as executor:
        async with await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER) as env:
            engine = Worker(
                env.client,
                task_queue=ENGINE_QUEUE,
                workflows=[RunGraph, LoopBatch],
                activities=engine_activities(store, [TESTKIT]),
                workflow_runner=SandboxedWorkflowRunner(),
                workflow_task_executor=executor,
            )
            evaluator = Worker(
                env.client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process, store)]
            )
            async with engine, evaluator, internal(env.client, store):
                handle = await start(env.client, store, g, AT_CAPS)
                result = await asyncio.wait_for(handle.result(), 300)
    assert result.status == "succeeded"
    assert {r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == "x"} == {"local"}
    worst = max(executor.cpu)
    REPORT["loads"][name] = {"expr_chars": len(expr), "tasks": len(executor.cpu), "worst_cpu_s": worst}
    assert worst <= TASK_CPU_TARGET_S, (name, sorted(executor.cpu, reverse=True)[:5])


SHARED: dict[str, tuple[dict[str, Any], str, Any]] = {  # #18: one value every view binds, past the caps and within them
    "past the caps": ({"type": "object", "properties": {"s": S}}, "size(trigger.s) > item", "x" * 65_000),
    "within the caps": ({"type": "object", "properties": {"t": {"type": "array", "items": S}}},
                        "size(trigger.t) > item", ["x" * 16_000] * 4),
}  # fmt: skip


# 30,000 views of two nodes each: nearly a whole node budget (YIELD_NODES) in one task, the per-task worst. About 45 s
# each, so only in the CEL gate job (which sets DEWPOINT_CEL_GATE_RESULTS), not in every suite run (the review of the M2
# checkpoint, M5)
GATE_JOB = pytest.mark.skipif(not os.environ.get("DEWPOINT_CEL_GATE_RESULTS"), reason="the CEL gate job's load")


@pytest.mark.parametrize("items", [1_000, pytest.param(30_000, marks=GATE_JOB)])
@pytest.mark.parametrize("shape", list(SHARED))
async def test_many_views_binding_one_large_value_stay_within_the_cpu_target(
    shape: str, items: int, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """#18's acceptance: gate 7b covers many views binding one large shared value. A filter whose every item binds
    it: past the caps (a plain string as large as a run holds one, 64 KiB), each view's measure is a walk of its
    lengths, and the binding sets go to `cel.evaluate`; within them (four 16,000-character strings), each view's is
    exact, a serialization of about 64 KB, charged by its bytes (`YIELD_BOUND_BYTES`). No workflow task may pass the
    CPU target. Measured on macOS before that charge: 1.8 s at 10,000 items within the caps, a deadlock at 30,000; after
    it, 0.28 s at most for either shape (Linux, the CEL gate job, is authoritative)."""
    schema, predicate, value = SHARED[shape]
    name = "s" if "s" in schema["properties"] else "t"
    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", CURRENT_CEL_PROFILE)  # what the build constant does
    store = MemoryStore()
    g = G()
    g.settings = {"input_schema": {**schema, "required": [name]}, "outputs": {"n": cel("size(steps.f.output.items)")}}
    g.node("f", "flow.filter@1", {"items": list(range(items)), "predicate": cel(predicate)})
    with Timed() as executor:
        async with await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER) as env:
            engine = Worker(
                env.client,
                task_queue=ENGINE_QUEUE,
                workflows=[RunGraph, LoopBatch],
                activities=engine_activities(store, [TESTKIT]),
                workflow_runner=SandboxedWorkflowRunner(),
                workflow_task_executor=executor,
            )
            evaluator = Worker(
                env.client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process, store)]
            )
            async with engine, evaluator, internal(env.client, store):
                handle = await start(env.client, store, g, {name: value})
                result = await asyncio.wait_for(handle.result(), 600)
    assert result.status == "succeeded", result
    worst = max(executor.cpu)
    REPORT["loads"][f"shared {shape} x{items}"] = {"tasks": len(executor.cpu), "worst_cpu_s": worst}
    print(f"shared {shape} x{items}: {len(executor.cpu)} tasks, worst {worst:.3f} s, mode "
          f"{ {r.cel_mode for r in store.steps(run_id_of(handle)) if r.node_key == 'f'} }")  # fmt: skip
    assert worst <= TASK_CPU_TARGET_S, (shape, items, sorted(executor.cpu, reverse=True)[:5])
