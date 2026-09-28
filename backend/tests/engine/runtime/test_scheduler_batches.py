# SPDX-License-Identifier: Apache-2.0
"""Batched loops (spec §6, 2a-3b): the parent hands out one batch at a time and takes back its results; a batch
child runs one slice of the loop over read-only copies of the loop's enclosing scopes; settled iterations are
pruned; the state survives a snapshot."""

import json

from dewpoint.engine.runtime.budget import Budget
from dewpoint.engine.runtime.resolve import view
from dewpoint.engine.runtime.scheduler import (
    Batch,
    BatchOutcome,
    Failure,
    Instance,
    OuterScope,
    RunEnd,
    Scheduler,
)
from tests.engine.runtime.support import name, program
from tests.support.graphs import G

ECHO, LOOP, FAIL = "testkit.echo@1", "flow.loop@1", "flow.fail@1"
BOOM = Failure("testkit.boom", "it broke")


def loop_graph() -> G:
    g = G().node("a", ECHO).node("l", LOOP, {"items": [1]}).node("x", ECHO).node("after", ECHO)
    return g.edge("a", "l").edge("l", "x", "body").edge("l", "after", "done")


def parent_at_loop(items: int, *, stop: bool = True) -> tuple[Scheduler, Instance]:
    s = Scheduler(program(loop_graph()))
    s.start()
    [a] = s.take_ready()
    s.succeed(a, {"seen": "a"})
    [loop] = s.take_ready()
    s.open_loop(loop, list(range(items)), concurrency=3, stop_on_error=stop, batch=100)
    return s, loop


def test_a_batched_loop_hands_out_one_batch_at_a_time_and_collects_them_in_order() -> None:
    s, loop = parent_at_loop(250)
    assert s.take_ready() == [] and not any(k for k in s.scopes if k)  # no iteration opens in the parent
    starts = []
    for _ in range(3):
        [b] = s.take_batches()
        assert s.take_batches() == []  # the next one waits for this one
        starts.append((b.start, len(b.items)))
        s.batch_done(loop, b.start, BatchOutcome([i * 10 for i in b.items], []))
    assert starts == [(0, 100), (100, 100), (200, 50)]
    assert [name(s, i) for i in s.take_ready()] == ["after"]
    output = s.scopes[()].results["l"]["output"]
    assert output["items"] == [i * 10 for i in range(250)] and output["count"] == 250


def test_a_stopped_batch_fails_the_loop_and_a_failed_batch_too() -> None:
    s, loop = parent_at_loop(150)
    [b] = s.take_batches()
    s.batch_done(
        loop, b.start, BatchOutcome([None] * 100, [{"index": 7, "code": "testkit.boom", "message": "x"}], BOOM)
    )
    assert s.ended is not None and s.ended.failure == BOOM
    s, loop = parent_at_loop(150)
    [b] = s.take_batches()
    s.batch_failed(loop, b.start, Failure("internal_error", "the child failed"))
    assert s.ended is not None and s.ended.failure is not None and s.ended.failure.code == "internal_error"


def test_failed_items_of_every_batch_are_listed_under_continue() -> None:
    s, loop = parent_at_loop(150, stop=False)
    for failed in (7, 120):
        [b] = s.take_batches()
        failures = [{"index": failed, "code": "testkit.boom", "message": "it broke"}]
        s.batch_done(loop, b.start, BatchOutcome([None] * len(b.items), failures))
    output = s.scopes[()].results["l"]["output"]
    assert [f["index"] for f in output["failures"]] == [7, 120]


def child_for(items: list[int], offset: int, *, stop: bool = True, g: G | None = None) -> Scheduler:
    p = program(g or loop_graph())
    s = Scheduler(p, budget=Budget(len(items), root=False))
    outer = [OuterScope((), {"a": {"output": {"seen": "a"}}})]
    s.start_batch(p.by_key["l"], outer, items, offset=offset, concurrency=2, stop_on_error=stop)
    return s


def test_a_batch_child_runs_its_slice_with_the_inline_iteration_keys() -> None:
    s = child_for([100, 101, 102], 100)
    first = s.take_ready()
    assert [name(s, i) for i in first] == ["l:100/x", "l:101/x"]  # the loop's concurrency, in index order
    v = view(s, first[0].scope, trigger={}, variables={}, run={})
    assert v.steps["a"] == {"output": {"seen": "a"}} and v.item == 100 and v.loops["l"] == {"item": 100, "index": 100}
    for inst in first:
        s.succeed(inst, {})
    for c in s.take_collects():
        s.collected(c.loop, c.index, c.index * 2)
    [last] = s.take_ready()
    s.succeed(last, {})
    [c] = s.take_collects()
    s.collected(c.loop, c.index, c.index * 2)
    assert s.ended == RunEnd("succeeded") and s.outcome == BatchOutcome([200, 202, 204], [])
    assert list(s.scopes) == [()]  # every iteration was pruned; the enclosing scope stays


def test_a_failed_iteration_stops_the_slice_or_is_listed() -> None:
    stopping = child_for([5, 6], 5)
    x5, x6 = stopping.take_ready()
    stopping.fail(x5, BOOM)
    assert stopping.outcome is not None and stopping.outcome.stopped == BOOM
    assert [name(stopping, i) for i in stopping.take_cancels()] == ["l:6/x"]
    going_on = child_for([5, 6], 5, stop=False)
    x5, x6 = going_on.take_ready()
    going_on.fail(x5, BOOM)
    going_on.succeed(x6, {})
    [c] = going_on.take_collects()
    going_on.collected(c.loop, c.index, "six")
    assert going_on.outcome == BatchOutcome(
        [None, "six"], [{"index": 5, "code": "testkit.boom", "message": "it broke"}]
    )


def test_a_fail_node_in_a_batch_ends_the_run_not_just_the_slice() -> None:
    g = G().node("a", ECHO).node("l", LOOP, {"items": [1]}).node("f", FAIL, {"message": "no"})
    g.edge("a", "l").edge("l", "f", "body")
    s = child_for([0], 0, g=g)
    [f] = s.take_ready()
    s.finish(f, RunEnd("failed", Failure("workflow_failed", "no")))
    assert s.outcome is None and s.ended == RunEnd("failed", Failure("workflow_failed", "no"))


def test_an_iteration_waits_for_budget_in_a_child_and_the_grant_opens_it() -> None:
    p = program(loop_graph())
    s = Scheduler(p, budget=Budget(1, root=False))
    s.start_batch(p.by_key["l"], [OuterScope((), {})], [0, 1], offset=0, concurrency=2, stop_on_error=True)
    assert [name(s, i) for i in s.take_ready()] == ["l:0/x"]
    answers, ask = s.answer_budget()
    assert answers == [] and ask is not None and ask.need == 1  # it asks its parent for the second
    s.budget.answered(1_000)
    s.answer_budget()
    assert [name(s, i) for i in s.take_ready()] == ["l:1/x"]


def test_a_batched_loop_survives_a_snapshot() -> None:
    s, loop = parent_at_loop(150)
    [b] = s.take_batches()
    s.take_settled()
    s = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json())))
    s.batch_done(loop, b.start, BatchOutcome(list(b.items), []))
    [b2] = s.take_batches()
    assert b2 == Batch(loop, 100, list(range(100, 150)))
