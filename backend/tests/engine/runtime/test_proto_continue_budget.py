# SPDX-License-Identifier: Apache-2.0
"""Proto (engine 2b spec §5.3, the at-continue budget term): an execution continues as new only once its iteration
budget holds no waiting need and no child's grant, so neither travels in a continued input. The quiescence check
enforces it, and the snapshot refuses to be taken otherwise."""

import pytest

from dewpoint.engine.runtime import probe as P
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
    assert quiescent({}, {}, idle, [], [], live=0)
    waiting = Budget(10, root=True)
    waiting.request(Need(LOCAL, "loop::l", 1, 1))
    assert not quiescent({}, {}, waiting, [], [], live=0)
    granted = Budget(10, root=True)
    granted.start_child(CHILD, 1)
    assert not quiescent({}, {}, granted, [], [], live=0)


def test_a_sleeping_timer_and_a_projection_leave_an_execution_quiescent() -> None:
    timer = Instance((), next(iter(one_loop().program.steps)))
    tasks = {("step", timer): None, ("project", 1): None}
    assert quiescent(tasks, {timer: None}, Budget(10, root=True), [], [], live=0)
    assert not quiescent({("step", timer): None}, {}, Budget(10, root=True), [], [], live=0)


def collecting(n: int, pad: int) -> Scheduler:
    """One loop whose n iterations each collect about `pad` bytes, all but the last: the loop stays open."""
    g = G()
    g.node("l", "flow.loop@1", {"items": list(range(n)), "concurrency": n, "collect": ref("item")})
    g.node("x", "testkit.echo@1", {"value": ref("item")}).edge("l", "x", "body")
    s = Scheduler(program(g), budget=Budget(1_000, root=True))
    s.start()
    (loop,) = s.take_ready()
    s.open_loop(loop, list(range(n)), concurrency=n, stop_on_error=False)
    for inst in s.take_ready():
        s.succeed(inst, {"value": inst.scope[-1][1]})
    for c in s.take_collects()[:-1]:
        s.collected(c.loop, c.index, {"i": c.index, "pad": "p" * pad})
    s.take_settled()
    return s


def test_a_snapshot_refuses_live_state_over_the_budget_until_its_claims_land(monkeypatch: pytest.MonkeyPatch) -> None:
    """Past the budget, a container is claimed: until the claim lands, its values are still live, and a continued
    input holding them would pass the bound (§5.3 counts LIVE_BUDGET, no more)."""
    monkeypatch.setattr(P, "LIVE_BUDGET", 4_000)
    s = collecting(10, 1_000)
    assert s.live > P.LIVE_BUDGET
    with pytest.raises(ValueError, match="live-state budget"):
        s.to_json()
    for sp in s.take_spills():
        s.spilled(sp.loop, sp.which, sp.first, 0)
    assert s.live <= P.LIVE_BUDGET
    s.to_json()


def test_an_execution_isnt_quiescent_while_its_live_state_is_over_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(P, "LIVE_BUDGET", 4_000)
    assert quiescent({}, {}, Budget(10, root=True), [], [], live=4_000)
    assert not quiescent({}, {}, Budget(10, root=True), [], [], live=4_001)
