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
    assert budget.must_yield(r)  # 30,000 iterations would pass 13,000
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


def test_the_yield_budget_charges_the_values_each_view_binds() -> None:
    """Binding a view converts every value it binds, a cost the stored bounds don't count: a cheap expression over
    the largest inputs would otherwise bind them 200 times in one workflow task (spec §5.6)."""
    cheap = replace(make_record("trigger.x == 1"), iterations=0, bytes=0, work=0)
    budget = route.YieldBudget()
    assert not budget.must_yield()  # the first binding of a task always runs, however large
    budget.charge(nodes=route.YIELD_NODES - 1)
    assert not budget.must_yield() and not budget.must_yield(cheap)
    budget.charge(cheap, nodes=1)
    assert budget.must_yield()  # the values bound reached the budget: the next view waits for the next task


def test_the_yield_thresholds_are_a_third_below_the_first_ones() -> None:
    """Spec §5.6: gate 7b's first run on Linux took three loads past 1 s per workflow task with 20,000 iterations,
    8 MiB, 4,000,000 work units, 200 evaluations and 100,000 bound values."""
    thresholds = (
        route.YIELD_ITERATIONS,
        route.YIELD_BYTES,
        route.YIELD_WORK,
        route.YIELD_EVALUATIONS,
        route.YIELD_NODES,
    )
    assert thresholds == (13_000, 11 * 512 * 1024, 2_700_000, 130, 65_000)


def test_an_executions_first_workflow_task_gets_a_tenth_of_each_threshold() -> None:
    """That task also starts the execution: it loads and compiles the version, or restores a snapshot (spec §5.6). A
    binding and a light evaluation still run in it, but an evaluation whose bounds pass a tenth waits for the next
    task, which has the whole budget."""
    light = replace(
        make_record("trigger.x == 1"), iterations=10, bytes=10, work=route.YIELD_WORK // route.STARTUP_SHARE
    )
    heavy = replace(light, work=light.work + 1)
    budget = route.YieldBudget()
    budget.reset(startup=True)
    assert not budget.must_yield()  # the first binding of a task always runs
    budget.charge(nodes=10)
    assert not budget.must_yield(light) and budget.must_yield(heavy)
    budget.charge(nodes=route.YIELD_NODES // route.STARTUP_SHARE)
    assert budget.must_yield()  # a tenth of the values the budget binds
    budget.reset()
    budget.charge(nodes=10)
    assert not budget.must_yield(heavy) and not budget.must_yield()


def test_a_workflow_task_sends_at_most_its_request_bytes() -> None:
    """#15: the requests one workflow task sends stay under Temporal's gRPC message limit together. The first always
    goes; sending isn't evaluating, so it spends none of the evaluation budget; the startup share doesn't apply."""
    budget = route.YieldBudget()
    big = route.YIELD_SEND_BYTES - 10
    assert not budget.must_yield(send=big)
    budget.charge(sent=big)
    assert not budget.must_yield(send=10)
    assert budget.must_yield(send=11)
    assert not budget.must_yield(None)  # binding a view isn't held back by requests sent
    budget.reset(startup=True)
    assert not budget.must_yield(send=big)
    budget.charge(sent=big)
    assert budget.must_yield(send=11)
