# SPDX-License-Identifier: Apache-2.0
"""Proto (engine 2b spec §5.3, workflow-task CPU): a snapshot and a restore run part by part, each part's structural
units charged to the workflow task, so a large one spreads over tasks. Stepping changes nothing of what's encoded or
restored; a restore defers its queued loop steps as it goes, so the first take after it has only the rest."""

import json

from dewpoint.engine.cel.route import STARTUP_SHARE, YIELD_STRUCTURE, YieldBudget
from dewpoint.engine.runtime.scheduler import STRUCTURE_STEP, Scheduler
from tests.engine.runtime.support import program
from tests.support.graphs import G, ref

LOOP = "flow.loop@1"


def siblings(k: int = 60) -> Scheduler:
    """Nested 10 x 10 loops whose body holds k sibling loops: once opened, ~100 iterations queue k loop steps each."""
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


def test_a_snapshot_in_steps_encodes_what_it_encodes_at_once() -> None:
    s = siblings()
    steps = s.encoding()
    parts = []
    while True:
        try:
            parts.append(next(steps))
        except StopIteration as done:
            stepwise = done.value
            break
    assert len(parts) > 2 and sum(parts) > STRUCTURE_STEP
    assert json.dumps(stepwise, sort_keys=True) == json.dumps(s.to_json(), sort_keys=True)


def test_a_restore_in_steps_restores_what_it_restores_at_once_and_defers_the_queued_loop_steps() -> None:
    s = siblings()
    data = json.loads(json.dumps(s.to_json()))
    restored = Scheduler.restoring(s.program, data)
    units = list(_steps(restored.decoding(data)))
    assert len(units) > 2
    assert len(restored._deferred) > 5_000 and not any(restored._iter_loop(i) for i in restored._ready)
    assert json.dumps(restored.to_json(), sort_keys=True) == json.dumps(data, sort_keys=True)
    assert json.dumps(Scheduler.from_json(s.program, data).to_json(), sort_keys=True) == json.dumps(
        data, sort_keys=True
    )


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


def _steps(gen):  # type: ignore[no-untyped-def]
    while True:
        try:
            yield next(gen)
        except StopIteration:
            return
