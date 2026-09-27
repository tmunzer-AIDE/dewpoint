# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace

from dewpoint.engine.cel import bind, route
from tests.engine.cel.support import make_record

SMALL = bind.measure({"a": 1})
BIG = bind.measure({"a": "x" * 70_000})
P = "cel-cpp-0.1.3/fn-1/cls-1"


def test_routing_is_local_only_when_every_condition_holds() -> None:
    local = make_record("trigger.x == 1")
    assert route.route(local, SMALL, local_profile=P, version_profile=P) == "local"
    assert route.route(local, BIG, local_profile=P, version_profile=P) == "activity"
    assert route.route(local, SMALL, local_profile=None, version_profile=P) == "activity"
    assert route.route(local, SMALL, local_profile="other", version_profile=P) == "activity"
    activity = replace(local, mode="activity")
    assert route.route(activity, SMALL, local_profile=P, version_profile=P) == "activity"


def test_the_yield_budget_uses_stored_bounds_and_a_count() -> None:
    r = replace(make_record("trigger.x == 1"), iterations=15_000, bytes=1024)
    budget = route.YieldBudget()
    assert not budget.must_yield(r)  # a fresh task always runs one evaluation
    budget.charge(r)
    assert budget.must_yield(r)  # 30,000 iterations would pass 20,000
    budget.reset()
    small = replace(r, iterations=0, bytes=0)
    for _ in range(route.YIELD_EVALUATIONS):
        assert not budget.must_yield(small)
        budget.charge(small)
    assert budget.must_yield(small)
    big = replace(r, iterations=0, bytes=route.YIELD_BYTES + 1)
    budget.reset()
    budget.charge(small)
    assert budget.must_yield(big)
