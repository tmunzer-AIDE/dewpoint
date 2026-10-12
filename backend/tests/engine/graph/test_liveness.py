# SPDX-License-Identifier: Apache-2.0
import dataclasses
import itertools
import uuid
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.graph import liveness as lv
from dewpoint.engine.graph.model import Graph
from dewpoint.engine.graph.structure import analyze_structure
from dewpoint.engine.graph.validate import ValidationContext, conditional_steps, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, nid
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
A, B = uuid.uuid4(), uuid.uuid4()


def test_simplify_merges_complements_and_absorbs() -> None:
    values = {A: ("true", "false"), B: ("x", "y", "z")}
    t, f = frozenset({(A, "true")}), frozenset({(A, "false")})
    assert lv.simplify([t, f], values) == lv.TRUE
    assert lv.simplify([t, t | {(B, "x")}], values) == frozenset({t})
    assert lv.simplify([t | {(A, "false")}], values) == lv.FALSE  # contradictory
    partial = [frozenset({(B, v)}) for v in ("x", "y")]
    assert lv.simplify(partial, values) == frozenset(partial)  # `z` is missing: no merge


def test_implies_and_exclusive() -> None:
    t, f = frozenset({(A, "true")}), frozenset({(A, "false")})
    assert lv.implies(frozenset({t}), frozenset({t}))
    assert not lv.implies(lv.TRUE, frozenset({t}))
    assert lv.implies(frozenset({t}), lv.TRUE) and lv.implies(None, lv.TRUE)
    assert not lv.implies(frozenset({t}), None)
    assert lv.exclusive(frozenset({t}), frozenset({f})) and not lv.exclusive(frozenset({t}), lv.TRUE)


def test_parallel_join_is_live_whenever_its_inputs_are() -> None:
    g = (
        G()
        .node("x", "testkit.echo@1")
        .node("a", "testkit.echo@1")
        .node("b", "testkit.echo@1")
        .node("j", "testkit.echo@1")
    )
    s, _ = analyze_structure(g.edge("x", "a").edge("x", "b").edge("a", "j").edge("b", "j").build(), CAT)
    assert s is not None
    region = lv.analyze_region(s, None)
    assert lv.implies(region.live[nid("j")], region.ok[nid("a")])


@st.composite
def dags(draw: st.DrawFn) -> tuple[list[str], list[tuple[int, int, str]], Graph]:
    n = draw(st.integers(2, 8))
    kinds = draw(st.lists(st.sampled_from(["echo", "if"]), min_size=n, max_size=n))
    g = G()
    for i, kind in enumerate(kinds):
        if kind == "if":
            g.node(f"n{i}", "flow.if@1", {"condition": True})
        else:
            g.node(f"n{i}", "testkit.echo@1")
    edges: set[tuple[int, int, str]] = set()
    for j in range(1, n):
        for i in range(j):
            if draw(st.booleans()):
                port = draw(st.sampled_from(["true", "false"])) if kinds[i] == "if" else "out"
                edges.add((i, j, port))
    for i, j, port in sorted(edges):
        g.edge(f"n{i}", f"n{j}", port)
    return kinds, sorted(edges), g.build()


@settings(max_examples=200, deadline=None)
@given(dags())
def test_liveness_is_sound_against_simulated_runs(case: Any) -> None:
    kinds, edges, graph = case
    s, diags = analyze_structure(graph, CAT)
    assert s is not None and diags == []
    region = lv.analyze_region(s, None)
    ifs = [i for i, k in enumerate(kinds) if k == "if"]
    runs: list[list[bool]] = []
    for choice in itertools.product(["true", "false"], repeat=len(ifs)):
        decision = dict(zip(ifs, choice, strict=True))
        ran = [False] * len(kinds)
        for j in range(len(kinds)):
            incoming = [(i, p) for i, jj, p in edges if jj == j]
            ran[j] = not incoming or any(ran[i] and (kinds[i] == "echo" or decision[i] == p) for i, p in incoming)
        runs.append(ran)
    for c in range(len(kinds)):
        cond = region.live[nid(f"n{c}")]
        if lv.implies(lv.TRUE, cond):
            assert all(r[c] for r in runs), f"n{c} claimed to always run"
        for p in range(c):
            if lv.implies(cond, region.ok[nid(f"n{p}")]):
                assert all(r[p] for r in runs if r[c]), f"n{p} claimed available at n{c}"


# Which steps may not run (4c-2a ruling 3; ledger ruling 70's badge).
def _conditional(g: G) -> set[str]:
    result = validate(g.build(), ValidationContext(catalog=CAT))
    keys = {n["id"]: n["key"] for n in g.nodes}
    return {keys[n] for n in result.conditional_steps}


def test_says_which_steps_a_branch_may_skip() -> None:
    g = (
        G().node("a", "testkit.echo@1", {"value": 1}).node("c", "flow.if@1", {"condition": True})
        .node("t", "testkit.echo@1", {"value": 1}).node("f", "testkit.echo@1", {"value": 1})
        .node("j", "testkit.echo@1", {"value": 1})
        .edge("a", "c").edge("c", "t", port="true").edge("c", "f", port="false").edge("t", "j").edge("f", "j")
    )  # fmt: skip
    assert _conditional(g) == {"t", "f"}  # the join runs whichever way the branch goes


def test_counts_a_loop_bodys_steps_conditional_when_the_loop_is() -> None:
    g = (
        G().node("c", "flow.if@1", {"condition": True}).node("l", "flow.loop@1", {"items": [1, 2]})
        .node("x", "testkit.echo@1", {"value": 1})
        .edge("c", "l", port="true").edge("l", "x", port="body")
    )  # fmt: skip
    assert _conditional(g) == {"l", "x"}


def test_says_a_step_after_an_error_port_may_not_run() -> None:
    g = (
        G().node("a", "testkit.echo@1", {"value": 1}, on_error="port")
        .node("ok", "testkit.echo@1", {"value": 1}).node("bad", "testkit.echo@1", {"value": 1})
        .edge("a", "ok").edge("a", "bad", port="error")
    )  # fmt: skip
    assert _conditional(g) == {"ok", "bad"}


def test_counts_a_step_it_cant_analyse_as_conditional() -> None:
    g = G().node("a", "testkit.echo@1", {"value": 1}).node("b", "testkit.echo@1", {"value": 1}).edge("a", "b")
    s, _ = analyze_structure(g.build(), CAT)
    assert s is not None
    live = {r: lv.analyze_region(s, r) for r in s.regions}
    assert conditional_steps(s, live) == ()
    root = live[None]
    unknown = dataclasses.replace(root, live={**root.live, nid("b"): None})  # too complex to analyse
    assert conditional_steps(s, {**live, None: unknown}) == (nid("b"),)
