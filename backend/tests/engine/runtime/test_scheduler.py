# SPDX-License-Identifier: Apache-2.0
"""The scheduler's rules (spec §6): readiness, edge resolution, dead paths, error policies, loop iterations."""

from typing import Any

from dewpoint.engine.runtime.scheduler import Failure, NodeState, RunEnd, Scheduler
from tests.engine.runtime.support import name, program
from tests.support.graphs import G

ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"
BOOM = Failure("testkit.boom", "it broke")


def started(g: G) -> Scheduler:
    s = Scheduler(program(g))
    s.start()
    return s


def ready(s: Scheduler) -> list[str]:
    return [name(s, i) for i in s.take_ready()]


def run_all(s: Scheduler) -> list[str]:
    """Succeed every step in the order the scheduler hands them over; loops get two items."""
    order: list[str] = []
    while s.ended is None:
        batch = s.take_ready()
        collects = s.take_collects()
        if not batch and not collects:
            raise AssertionError("stuck: nothing ready, nothing to collect")
        for inst in batch:
            order.append(name(s, inst))
            if s.step(inst).ref == LOOP:
                s.open_loop(inst, ["a", "b"], concurrency=1, stop_on_error=True)
            else:
                s.succeed(inst, {"n": name(s, inst)}, ("true",) if s.step(inst).ref == IF else None)
        for c in collects:
            s.collected(c.loop, c.index, c.index * 10)
    return order


def test_a_chain_runs_in_order_and_the_run_succeeds() -> None:
    s = started(G().node("a", ECHO).node("b", ECHO).node("c", ECHO).edge("a", "b").edge("b", "c"))
    assert run_all(s) == ["a", "b", "c"]
    assert s.ended == RunEnd("succeeded")
    assert s.scopes[()].results["c"] == {"output": {"n": "c"}}


def test_branches_meet_again_in_the_same_scope() -> None:
    """if → A | B → C: with `true`, A runs, B dies, and C runs once, in the root scope."""
    g = (
        G()
        .node("c", IF, {"condition": True})
        .node("a", ECHO)
        .node("b", ECHO)
        .node("j", ECHO)
        .edge("c", "a", "true")
        .edge("c", "b", "false")
        .edge("a", "j")
        .edge("b", "j")
    )
    s = started(g)
    assert run_all(s) == ["c", "a", "j"]
    root = s.scopes[()]
    assert root.nodes[s.program.by_key["b"]] == NodeState.DEAD and "b" not in root.results
    assert s.ended == RunEnd("succeeded")


def test_a_switch_takes_one_port_and_kills_the_rest() -> None:
    cases = [{"port": "x", "when": True}, {"port": "y", "when": True}]
    g = G().node("s", SWITCH, {"cases": cases}).node("x", ECHO).node("y", ECHO).node("d", ECHO)
    g.edge("s", "x", "x").edge("s", "y", "y").edge("s", "d", "default")
    s = started(g)
    [sw] = s.take_ready()
    s.succeed(sw, {}, ("y",))
    assert ready(s) == ["y"]
    states = {k: s.scopes[()].nodes[s.program.by_key[k]] for k in ("x", "d")}
    assert states == {"x": NodeState.DEAD, "d": NodeState.DEAD}


def test_error_port_routes_a_failure_and_records_the_error() -> None:
    g = G().node("a", ECHO, on_error="port").node("ok", ECHO).node("handler", ECHO)
    g.edge("a", "ok").edge("a", "handler", "error")
    s = started(g)
    [a] = s.take_ready()
    s.fail(a, BOOM)
    assert ready(s) == ["handler"]
    assert s.scopes[()].results["a"] == {"error": BOOM.to_json()}
    assert s.scopes[()].nodes[s.program.by_key["ok"]] == NodeState.DEAD


def test_continue_follows_the_normal_edges_without_an_output() -> None:
    s = started(G().node("a", ECHO, on_error="continue").node("b", ECHO).edge("a", "b"))
    [a] = s.take_ready()
    s.fail(a, BOOM)
    assert ready(s) == ["b"]
    assert s.scopes[()].results["a"] == {"error": BOOM.to_json()}  # `has(steps.a.output)` is false (spec §5.3)


def test_an_unhandled_failure_fails_the_run_and_cancels_running_steps() -> None:
    s = started(G().node("a", ECHO).node("b", ECHO))
    a, b = s.take_ready()
    s.fail(a, BOOM)
    assert s.ended == RunEnd("failed", BOOM)
    assert [name(s, i) for i in s.take_cancels()] == ["b"]
    s.succeed(b, {})  # a late result from cancelled work counts for nothing
    assert "b" not in s.scopes[()].results


def loop_graph(**config: Any) -> G:
    g = G().node("l", LOOP, {"items": [1, 2, 3], **config}).node("x", ECHO).node("y", ECHO).node("after", ECHO)
    return g.edge("l", "x", "body").edge("x", "y").edge("l", "after", "done")


def test_iterations_run_one_at_a_time_and_collect_in_order() -> None:
    s = started(loop_graph())
    [loop] = s.take_ready()
    s.open_loop(loop, ["a", "b", "c"], concurrency=1, stop_on_error=True)
    seen = []
    for index in range(3):
        [x] = s.take_ready()
        seen.append(name(s, x))
        s.succeed(x, {})
        [y] = s.take_ready()
        s.succeed(y, {})
        [c] = s.take_collects()
        assert (c.index, c.scope) == (index, (("l", index),))
        assert s.scopes[c.scope].item == ["a", "b", "c"][index]
        s.collected(c.loop, c.index, f"v{index}")
    assert seen == ["l:0/x", "l:1/x", "l:2/x"]
    assert ready(s) == ["after"]
    assert s.scopes[()].results["l"] == {"output": {"items": ["v0", "v1", "v2"], "failures": [], "count": 3}}
    assert s.iterations == 3


def test_concurrency_opens_that_many_iterations() -> None:
    s = started(loop_graph())
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2, 3], concurrency=2, stop_on_error=True)
    assert ready(s) == ["l:0/x", "l:1/x"]


def test_continue_on_item_error_records_the_failure_and_a_null_item() -> None:
    s = started(loop_graph())
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2], concurrency=1, stop_on_error=False)
    [x0] = s.take_ready()
    s.fail(x0, BOOM)
    [x1] = s.take_ready()
    assert name(s, x1) == "l:1/x"
    s.succeed(x1, {})
    [y1] = s.take_ready()
    s.succeed(y1, {})
    [c] = s.take_collects()
    s.collected(c.loop, c.index, "ok")
    assert s.scopes[()].results["l"]["output"] == {
        "items": [None, "ok"],
        "failures": [{"index": 0, "code": "testkit.boom", "message": "it broke"}],
        "count": 2,
    }


def test_stop_on_item_error_ends_the_other_iterations_and_fails_the_loop() -> None:
    g = loop_graph()
    g.nodes[0]["options"]["on_error"] = "port"
    g.node("handler", ECHO).edge("l", "handler", "error")
    s = started(g)
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2], concurrency=2, stop_on_error=True)
    x0, x1 = s.take_ready()
    s.fail(x0, BOOM)
    assert [name(s, i) for i in s.take_cancels()] == ["l:1/x"]
    assert ready(s) == ["handler"]
    assert s.scopes[()].results["l"] == {"error": BOOM.to_json()}
    s.succeed(x1, {})  # the cancelled iteration's late result is ignored
    assert s.ended is None


def test_an_inner_loop_that_stops_fails_only_its_outer_iteration() -> None:
    """Policies compose: the inner loop stops on its item's failure and fails, which fails the outer iteration; the
    outer loop continues past it and records it."""
    g = G().node("outer", LOOP, {"items": [1, 2], "on_item_error": "continue"}).node("inner", LOOP, {"items": [1]})
    g.node("x", ECHO).node("after", ECHO)
    g.edge("outer", "inner", "body").edge("inner", "x", "body").edge("outer", "after", "done")
    s = started(g)
    [outer] = s.take_ready()
    s.open_loop(outer, [1, 2], concurrency=1, stop_on_error=False)
    [inner] = s.take_ready()
    s.open_loop(inner, ["p"], concurrency=1, stop_on_error=True)
    [x] = s.take_ready()
    s.fail(x, BOOM)  # the inner loop stops and fails; outer:0 fails with it
    [inner] = s.take_ready()
    assert name(s, inner) == "outer:1/inner"
    s.open_loop(inner, [], concurrency=1, stop_on_error=True)  # outer:1 settles at once
    [collect] = s.take_collects()
    s.collected(collect.loop, collect.index, "second")
    assert ready(s) == ["after"]
    assert s.scopes[()].results["outer"] == {
        "output": {
            "items": [None, "second"],
            "failures": [{"index": 0, "code": BOOM.code, "message": BOOM.message}],
            "count": 2,
        }
    }


def test_nested_loops_open_nested_scopes() -> None:
    g = (
        G()
        .node("outer", LOOP, {"items": [1]})
        .node("inner", LOOP, {"items": [1]})
        .node("x", ECHO)
        .edge("outer", "inner", "body")
        .edge("inner", "x", "body")
    )
    s = started(g)
    [outer] = s.take_ready()
    s.open_loop(outer, [1, 2], concurrency=1, stop_on_error=True)
    [inner] = s.take_ready()
    assert name(s, inner) == "outer:0/inner"
    s.open_loop(inner, ["p", "q"], concurrency=2, stop_on_error=True)
    assert ready(s) == ["outer:0/inner:0/x", "outer:0/inner:1/x"]


def test_an_empty_loop_completes_at_once() -> None:
    s = started(loop_graph())
    [loop] = s.take_ready()
    s.open_loop(loop, [], concurrency=1, stop_on_error=True)
    assert ready(s) == ["after"]
    assert s.scopes[()].results["l"] == {"output": {"items": [], "failures": [], "count": 0}}


def test_the_iteration_cap_fails_the_loop() -> None:
    s = Scheduler(program(loop_graph()), iteration_cap=2)
    s.start()
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2, 3], concurrency=3, stop_on_error=True)
    assert s.ended is not None and s.ended.failure is not None
    assert s.ended.failure.code == "iteration_cap_exceeded"


def test_a_stop_ends_the_run_and_cancels_running_work() -> None:
    s = started(G().node("a", ECHO).node("b", ECHO))
    a, _ = s.take_ready()
    s.succeed(a, {})
    s.end(RunEnd("succeeded", stopped=True))
    assert [name(s, i) for i in s.take_cancels()] == ["b"]
