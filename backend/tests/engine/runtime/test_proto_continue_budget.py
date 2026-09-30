# SPDX-License-Identifier: Apache-2.0
"""Proto (engine 2b spec §5.3, the at-continue budget term): an execution continues as new only once its iteration
budget holds no waiting need and no child's grant, so neither travels in a continued input. The quiescence check
enforces it, and the snapshot refuses to be taken otherwise."""

import pytest

from dewpoint.engine.runtime.budget import LOCAL, Budget, Need
from dewpoint.engine.runtime.execution import quiescent
from dewpoint.engine.runtime.scheduler import Instance, Scheduler
from tests.engine.runtime.support import program
from tests.support.graphs import G, ref

CHILD = "t:00000000-0000-0000-0000-000000000001:run:00000000-0000-0000-0000-000000000002"


def one_loop() -> Scheduler:
    g = G()
    g.node("l", "flow.loop@1", {"items": [1, 2, 3], "collect": ref("item")})
    g.node("x", "testkit.echo@1", {"value": ref("item")}).edge("l", "x", "body")
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
    assert s.to_json()["budget"]["waiting"] == [] and s.to_json()["budget"]["reserved"] == {}


def test_an_execution_isnt_quiescent_while_its_budget_waits_or_a_child_holds_a_grant() -> None:
    idle = Budget(10, root=True)
    assert quiescent({}, {}, idle, [], [])
    waiting = Budget(10, root=True)
    waiting.request(Need(LOCAL, "loop::l", 1, 1))
    assert not quiescent({}, {}, waiting, [], [])
    granted = Budget(10, root=True)
    granted.start_child(CHILD, 1)
    assert not quiescent({}, {}, granted, [], [])


def test_a_sleeping_timer_and_a_projection_leave_an_execution_quiescent() -> None:
    timer = Instance((), next(iter(one_loop().program.steps)))
    tasks = {("step", timer): None, ("project", 1): None}
    assert quiescent(tasks, {timer: None}, Budget(10, root=True), [], [])
    assert not quiescent({("step", timer): None}, {}, Budget(10, root=True), [], [])
