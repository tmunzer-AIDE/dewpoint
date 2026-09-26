# SPDX-License-Identifier: Apache-2.0
import itertools
import uuid
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.graph import liveness as lv
from dewpoint.engine.graph.model import Graph
from dewpoint.engine.graph.structure import analyze_structure
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
