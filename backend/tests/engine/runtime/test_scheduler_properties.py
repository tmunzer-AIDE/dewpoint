# SPDX-License-Identifier: Apache-2.0
"""Spec §10, on random graphs with if/switch/joins/error ports/loops, completed in random orders:
- every node runs or dies exactly once per scope;
- dead paths never run;
- a step runs in its own region's scope, so branches that reconverge meet in the same scope;
- no edge is left pending when a run succeeds, so nothing deadlocks.

The same runs also take snapshots at random points and carry on from them (continue-as-new), and some loops run in
batches whose children report random outcomes (2a-3b). Some run under a small open-iteration cap (engine 2b spec
§5.3): open iteration scopes never pass the cap plus the version's loop depth, and nothing is left stuck. Some run
under a small live-state budget: containers go to claims, which land at random moments, before or after a snapshot;
the counter always equals a recount."""

import dataclasses
import json
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dewpoint.engine.runtime import scheduler as S
from dewpoint.engine.runtime.scheduler import (
    SETTLED,
    Batch,
    BatchOutcome,
    EdgeState,
    Failure,
    Instance,
    NodeState,
    Scheduler,
)
from tests.engine.runtime.support import program
from tests.support.graphs import G

ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"


@st.composite
def graphs(draw: st.DrawFn) -> G:
    g = G()
    count = [0]
    edges: set[tuple[str, str, str]] = set()

    def edge(src: str, dst: str, port: str) -> None:
        if (src, dst, port) not in edges:
            edges.add((src, dst, port))
            g.edge(src, dst, port)

    def block(depth: int, feeds: list[tuple[str, str]]) -> None:
        """One region's nodes. Every node is reached from `feeds` (a loop's body port) or from earlier nodes of
        the block, so the region is exactly the block; the root may also start fresh."""
        outs = list(feeds)
        made: list[str] = []
        needs_error: list[str] = []
        for _ in range(draw(st.integers(1, 4 if depth == 0 else 3))):
            count[0] += 1
            key = f"n{count[0]}"
            kinds = ["echo", "echo", "if", "switch"] + (["loop"] if depth < 2 else [])
            kind = draw(st.sampled_from(kinds))
            on_error = draw(st.sampled_from(["fail", "continue", "port"])) if kind in ("echo", "loop") else "fail"
            if kind == "echo":
                g.node(key, ECHO, {"value": 1}, on_error=on_error)
                ports = ["out"]
            elif kind == "if":
                g.node(key, IF, {"condition": True})
                ports = ["true", "false"]
            elif kind == "switch":
                cases = [{"port": f"c{i}", "when": True} for i in range(draw(st.integers(1, 2)))]
                g.node(key, SWITCH, {"cases": cases})
                ports = [c["port"] for c in cases] + ["default"]
            else:
                g.node(key, LOOP, {"items": [1]}, on_error=on_error)
                ports = ["done"]
            sources = draw(st.lists(st.sampled_from(outs), unique=True, max_size=2)) if outs else []
            if not sources and depth > 0:
                sources = [draw(st.sampled_from(outs))]
            for src, port in sources:
                edge(src, key, port)
            if kind == "loop":
                block(depth + 1, [(key, "body")])
            if on_error == "port":
                needs_error.append(key)
            made.append(key)
            outs += [(key, p) for p in ports]
        for key in needs_error:  # an error port must lead somewhere: a later step, or a new handler
            later = made[made.index(key) + 1 :]
            if later:
                edge(key, draw(st.sampled_from(later)), "error")
            else:
                count[0] += 1
                handler = f"n{count[0]}"
                g.node(handler, ECHO, {"value": 1})
                edge(key, handler, "error")
                made.append(handler)

    block(0, [])
    return g


def _entry_ok(s: Scheduler, inst: Instance) -> bool:
    scope = s.scopes[inst.scope]
    states = [scope.edges[e] for e in s.step(inst).ins if e in scope.edges]
    return all(x != EdgeState.PENDING for x in states) and (not states or EdgeState.LIVE in states)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(graphs(), st.data())
def test_random_runs_keep_the_scheduling_invariants(g: G, data: st.DataObject) -> None:
    budget = data.draw(st.sampled_from([S.LIVE_BUDGET, 150, 500]), label="live budget")
    lowered, S.LIVE_BUDGET = S.LIVE_BUDGET, budget
    try:
        run(g, data)
    finally:
        S.LIVE_BUDGET = lowered


def run(g: G, data: st.DataObject) -> None:
    cap = data.draw(st.sampled_from([None, 1, 2]), label="cap")
    s = Scheduler(dataclasses.replace(program(g), open_scopes_cap=cap), prefix="t:1:run:2")
    s.start()
    spills: list[Any] = []
    running: list[Instance] = []
    collects: list[Any] = []
    batches: list[Batch] = []
    handed: dict[Instance, int] = {}
    while s.ended is None:
        assert s.open_scopes <= s.cap + s.reserve, "open iteration scopes passed the cap and the reservation"
        assert s.live == s.recount(), "the live-state counter drifted from what the state holds"
        cancelled = set(s.take_cancels())
        running = [r for r in running if r not in cancelled]
        batches = [b for b in batches if b.loop not in cancelled]
        # continue-as-new: carry on from a snapshot, taken with work still queued, as drain mode leaves it
        if data.draw(st.integers(0, 7), label="snapshot") == 0 and s.live <= S.LIVE_BUDGET:
            s.take_settled()
            s = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json(check=True))), prefix="t:1:run:2")
        for inst in s.take_ready():
            handed[inst] = handed.get(inst, 0) + 1
            assert handed[inst] == 1, "a step ran twice in one scope"
            assert s.scopes[inst.scope].region == s.step(inst).region, "a step ran outside its region's scope"
            assert _entry_ok(s, inst), "a step ran without a live incoming edge"
            running.append(inst)
        collects += s.take_collects()
        batches += s.take_batches()
        spills += s.take_spills()
        if not running and not collects and not batches and not spills:
            raise AssertionError("stuck: nothing running, nothing to collect, and the run hasn't ended")
        if spills and data.draw(st.integers(0, 2), label="land a claim") == 0:
            sp = spills.pop(data.draw(st.integers(0, len(spills) - 1), label="which claim"))
            s.spilled(sp.owner, sp.which, sp.first)
            continue
        if not running and not collects and not batches:
            continue
        pick = data.draw(st.integers(0, len(running) + len(collects) + len(batches) - 1))
        if pick >= len(running) + len(collects):
            b = batches.pop(pick - len(running) - len(collects))
            how = data.draw(st.sampled_from(["ok", "ok", "item_failed", "stopped", "failed"]), label="batch")
            if how == "failed":
                s.batch_failed(b.loop, b.start, Failure("internal_error", "the child failed"))
                continue
            failures = (
                [{"index": b.start, "code": "testkit.boom", "message": "it broke"}] if how == "item_failed" else []
            )
            stopped = Failure("testkit.boom", "it broke") if how == "stopped" else None
            s.batch_done(b.loop, b.start, BatchOutcome([b.start + i for i in range(len(b.items))], failures, stopped))
            continue
        if pick >= len(running):
            c = collects.pop(pick - len(running))
            if data.draw(st.integers(0, 5), label="collect") == 0:
                s.collect_failed(c.loop, c.index, Failure("evaluation_error", "collect failed"))
            else:
                s.collected(c.loop, c.index, c.index)
            continue
        inst = running.pop(pick)
        step = s.step(inst)
        if step.ref == LOOP:
            items = list(range(data.draw(st.integers(0, 5), label="items")))
            s.open_loop(
                inst,
                items,
                concurrency=data.draw(st.integers(1, 2), label="concurrency"),
                stop_on_error=data.draw(st.booleans(), label="stop"),
                batch=data.draw(st.sampled_from([0, 0, 2]), label="batch"),
            )
        elif step.ref in (IF, SWITCH):
            s.succeed(inst, {}, (data.draw(st.sampled_from(step.ports), label="port"),))
        elif data.draw(st.integers(0, 4), label="outcome") == 0:
            s.fail(inst, Failure("testkit.boom", "it broke"))
        else:
            s.succeed(inst, {"n": "x" * data.draw(st.sampled_from([0, 50, 400, 700]), label="output")})
    # dead steps never ran; every step of a scope that finished normally settled, with no edge left pending
    for scope in s.scopes.values():
        for node_id, state in scope.nodes.items():
            if state == NodeState.DEAD and scope.failure is None:
                assert Instance(scope.key, node_id) not in handed, "a dead step ran"
        if s.ended.status == "succeeded" and scope.failure is None:
            assert all(state in SETTLED for state in scope.nodes.values()), "a step never settled"
            assert EdgeState.PENDING not in scope.edges.values(), "an edge was left pending"
