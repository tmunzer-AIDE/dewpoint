# SPDX-License-Identifier: Apache-2.0
"""The iteration budget at a continue (engine 2b spec §5.3). Queued loop steps share one request: none starts while
the budget waits or asks, and once it decides, a grant starts them in scheduling order and a refusal starts them to
fail at their first iteration, so each one starts or settles. An execution continues only once its budget holds no
waiting need and no child's grant: the quiescence check requires it, and the snapshot refuses otherwise, so neither
travels in a continued input."""

import dataclasses
from typing import Any

import pytest

from dewpoint.engine.runtime.budget import LOCAL, Budget, Need
from dewpoint.engine.runtime.execution import quiescent
from dewpoint.engine.runtime.scheduler import ITERATION_CAP_EXCEEDED, Instance, Scheduler
from tests.engine.runtime.support import program
from tests.support.graphs import G, ref

ECHO, LOOP = "testkit.echo@1", "flow.loop@1"
CHILD = "t:00000000-0000-0000-0000-000000000001:run:00000000-0000-0000-0000-000000000002"


def one_loop() -> Scheduler:
    g = G().node("l", LOOP, {"items": [1, 2, 3], "collect": ref("item")})
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    s = Scheduler(program(g), budget=Budget(10, root=True))
    s.start()
    return s


def test_a_snapshot_refuses_a_waiting_need() -> None:
    s = one_loop()
    s.budget.request(Need(LOCAL, "loop::l", 1, 1))
    with pytest.raises(ValueError, match="budget"):
        s.to_json()


def test_a_snapshot_refuses_a_child_holding_a_grant() -> None:
    s = one_loop()
    s.budget.start_child(CHILD, 5)
    with pytest.raises(ValueError, match="budget"):
        s.to_json()


def test_a_snapshot_is_taken_once_the_budget_holds_neither() -> None:
    s = one_loop()
    s.budget.start_child(CHILD, 5)
    s.budget.settle_child(CHILD, 2)
    budget = s.to_json()["budget"]
    assert budget["waiting"] == [] and budget["reserved"] == {}


def test_an_execution_isnt_quiescent_while_its_budget_waits_or_a_child_holds_a_grant() -> None:
    assert quiescent({}, {}, Budget(10, root=True), [], [])
    waiting = Budget(10, root=True)
    waiting.request(Need(LOCAL, "loop::l", 1, 1))
    assert not quiescent({}, {}, waiting, [], [])
    granted = Budget(10, root=True)
    granted.start_child(CHILD, 1)
    assert not quiescent({}, {}, granted, [], [])


def test_a_sleeping_timer_and_a_projection_leave_an_execution_quiescent() -> None:
    timer = Instance((), next(iter(one_loop().program.steps)))
    tasks: dict[tuple[Any, ...], Any] = {("step", timer): None, ("project", 1): None}
    assert quiescent(tasks, {timer: None}, Budget(10, root=True), [], [])
    assert not quiescent({("step", timer): None}, {}, Budget(10, root=True), [], [])


def siblings(n: int) -> G:
    """Loops 2 deep; the inner body holds `n` sibling loops, each over an echo; every loop continues on error."""
    g = G().node("o", LOOP, {"items": [1]}, on_error="continue").node("m", LOOP, {"items": [1]}, on_error="continue")
    g.edge("o", "m", "body")
    for k in range(n):
        g.node(f"s{k}", LOOP, {"items": [1]}, on_error="continue").node(f"e{k}", ECHO)
        g.edge("m", f"s{k}", "body").edge(f"s{k}", f"e{k}", "body")
    return g


def drain(s: Scheduler, *, refuse_asks: bool = False, child_turns: int = 0) -> dict[str, int]:
    """Run to the end with an exhausted budget: every loop over 3 items, all at once. Asserts at every turn that no
    queued loop step starts while the budget waits or asks, and that waiting needs stay one per started loop at most.
    `refuse_asks`: a child execution's parent refuses every ask. `child_turns`: a child holds half the budget for that
    many turns, unused: under the exact cap, the root's needs wait for it to release."""
    outcome = {"refused": 0, "completed": 0}
    if child_turns:
        s.budget.start_child(CHILD, s.budget.total // 2)
    turn = 0
    while s.ended is None:
        turn += 1
        if child_turns and turn == child_turns:
            s.budget.settle_child(CHILD, 0)
        if s.budget.asking and refuse_asks:
            s.budget.answered(0)
        s.answer_budget()
        assert len(s.budget.waiting) <= len(s.loops), "a queued loop step added a need of its own"
        blocked = bool(s.budget.waiting or s.budget.asking)
        ready = s.take_ready()
        if blocked:
            assert not [i for i in ready if s._iter_loop(i)], "a queued loop step started while the budget waited"
        collects = s.take_collects()
        for inst, result in s.take_settled():
            if s.step(inst).ref == LOOP:
                error = result.get("error")
                outcome["refused" if error and error["code"] == ITERATION_CAP_EXCEEDED else "completed"] += 1
        if not ready and not collects and not s.budget.waiting and not s.budget.asking:
            raise AssertionError("stuck: nothing ready, nothing to collect, and the budget decided everything")
        for inst in ready:
            if s.step(inst).ref == LOOP:
                s.open_loop(inst, [0, 1, 2], concurrency=3, stop_on_error=False)
            else:
                s.succeed(inst, {})
        for c in collects:
            s.collected(c.loop, c.index, c.index)
    return outcome


def test_an_exhausted_root_budget_starts_or_settles_every_queued_loop_step() -> None:
    """§11.2's scale, small: 3 × 3 iterations of 24 sibling loops, a budget of 40 iterations. Each loop starts once
    the budget has decided, and the refused ones fail their first iteration (`iteration_cap_exceeded`)."""
    s = Scheduler(dataclasses.replace(program(siblings(24)), open_scopes_cap=2), budget=Budget(40, root=True))
    s.start()
    outcome = drain(s, child_turns=200)
    assert s.ended is not None and outcome["refused"] > 0
    assert s.iterations <= 40


def test_a_child_whose_asks_are_refused_starts_or_settles_every_queued_loop_step() -> None:
    s = Scheduler(dataclasses.replace(program(siblings(8)), open_scopes_cap=2), budget=Budget(10, root=False))
    s.start()
    outcome = drain(s, refuse_asks=True)
    assert s.ended is not None and outcome["refused"] > 0
