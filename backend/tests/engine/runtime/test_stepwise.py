# SPDX-License-Identifier: Apache-2.0
"""A workflow task's CPU (engine 2b spec §5.3): a snapshot and a restore run part by part, each part's structural units
charged to the workflow task, so a large one spreads over tasks; stepping changes nothing of what's encoded or
restored, and a restore defers its queued loop steps as it goes, so the first take after it has only the rest. A take
takes only what the task's share allows. Units count work deterministically: a replay yields at the same points."""

import json
from collections.abc import Generator
from typing import Any

from dewpoint.engine.cel.route import STARTUP_SHARE, YIELD_STRUCTURE, YieldBudget
from dewpoint.engine.runtime.scheduler import STRUCTURE_STEP, Scheduler
from tests.engine.runtime.support import program
from tests.support.graphs import G, ref

LOOP = "flow.loop@1"


def siblings(k: int = 60) -> Scheduler:
    """Nested 10 x 10 loops whose body holds k sibling loops: once opened, 100 iterations queue k loop steps each."""
    g = G()
    g.node("o", LOOP, {"items": list(range(10)), "concurrency": 10, "collect": ref("item")})
    g.node("m", LOOP, {"items": list(range(10)), "concurrency": 10, "collect": ref("item")}).edge("o", "m", "body")
    for j in range(k):
        g.node(f"s{j}", LOOP, {"items": [1], "concurrency": 1, "collect": ref("item")}).edge("m", f"s{j}", "body")
        g.node(f"x{j}", "testkit.echo@1", {"value": ref("item")}).edge(f"s{j}", f"x{j}", "body")
    s = Scheduler(program(g))
    s.start()
    for _ in range(3):  # open the outer and middle loops' iterations; their bodies queue the sibling loop steps
        for inst in s.take_ready():
            step = s.step(inst)
            if step.key in ("o", "m"):
                s.open_loop(inst, list(step.config["items"]), concurrency=10, stop_on_error=False)
    s.take_settled()
    return s


def run(gen: Generator[int, None, Any]) -> tuple[list[int], Any]:
    parts = []
    while True:
        try:
            parts.append(next(gen))
        except StopIteration as done:
            return parts, done.value


def test_a_snapshot_in_steps_encodes_what_it_encodes_at_once() -> None:
    s = siblings()
    parts, stepwise = run(s.encoding())
    assert len(parts) > 2 and sum(parts) > STRUCTURE_STEP
    assert json.dumps(stepwise, sort_keys=True) == json.dumps(s.to_json(), sort_keys=True)


def test_a_restore_in_steps_restores_what_it_restores_at_once_and_defers_the_queued_loop_steps() -> None:
    s = siblings()
    data = json.loads(json.dumps(s.to_json()))
    restored = Scheduler.restoring(s.program, data)
    parts, _ = run(restored.decoding(data))
    assert len(parts) > 2
    assert len(restored._deferred) > 5_000 and not any(restored._iter_loop(i) for i in restored._ready)
    assert json.dumps(restored.to_json(), sort_keys=True) == json.dumps(data, sort_keys=True)
    assert json.dumps(Scheduler.from_json(s.program, data).to_json(), sort_keys=True) == json.dumps(
        data, sort_keys=True
    )


def test_a_take_takes_only_what_the_task_allows_in_queue_order() -> None:
    g = G()
    for n in range(10):
        g.node(f"a{n}", "testkit.echo@1")
    s = Scheduler(program(g))
    s.start()
    first = s.take_ready(limit=4)
    assert len(first) == 4 and s.taken_last == 4 and s.queued_left()
    rest = s.take_ready()
    assert len(rest) == 6 and not s.queued_left()
    assert sorted(first + rest, key=s.order) == first + rest  # in queue order: a replay takes the same


def test_a_workflow_task_yields_once_its_structural_share_is_spent() -> None:
    budget = YieldBudget()
    assert not budget.must_yield(structure=STRUCTURE_STEP)  # the first part always runs
    budget.charge(structure=YIELD_STRUCTURE - STRUCTURE_STEP)
    assert not budget.must_yield(structure=STRUCTURE_STEP)
    budget.charge(structure=1)
    assert budget.must_yield(structure=STRUCTURE_STEP)
    budget.reset(startup=True)  # an execution's first task gets a tenth for a restore: it also starts the execution
    budget.charge(structure=YIELD_STRUCTURE // STARTUP_SHARE)
    assert budget.must_yield(structure=1)
    assert not budget.must_yield(structure=1, whole=True)  # steps get the whole share: their work is light
