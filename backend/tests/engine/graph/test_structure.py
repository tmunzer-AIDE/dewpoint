# SPDX-License-Identifier: Apache-2.0
from dewpoint.engine.graph.model import Graph
from dewpoint.engine.graph.structure import analyze_structure
from dewpoint.engine.registry.catalog import Catalog
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, nid
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
ECHO = "testkit.echo@1"
LOOP = "flow.loop@1"


def codes(graph: Graph, cat: Catalog = CAT) -> list[str]:
    return [d.code for d in analyze_structure(graph, cat)[1]]


def test_linear_graph() -> None:
    s, diags = analyze_structure(G().node("b", ECHO).node("a", ECHO).edge("a", "b").build(), CAT)
    assert diags == [] and s is not None
    assert s.topo == (nid("a"), nid("b"))
    assert s.regions[None].members == (nid("a"), nid("b"))


def test_duplicate_key() -> None:
    g = G().node("a", ECHO).node("b", ECHO)
    g.nodes[1]["key"] = "a"
    assert codes(g.build()) == ["graph.duplicate_key"]


def test_unknown_type_stops_analysis() -> None:
    s, diags = analyze_structure(G().node("a", "testkit.nope@1").build(), CAT)
    assert s is None and [d.code for d in diags] == ["node.unknown_type"]


def test_ports_and_error_routing() -> None:
    assert codes(G().node("a", ECHO).node("b", ECHO).edge("a", "b", "true").build()) == ["edge.unknown_port"]
    assert codes(G().node("a", ECHO).node("b", ECHO).edge("a", "b", "error").build()) == ["edge.unknown_port"]
    assert codes(G().node("a", ECHO, on_error="port").build()) == ["node.error_port_unconnected"]
    assert codes(G().node("a", ECHO, on_error="port").node("h", ECHO).edge("a", "h", "error").build()) == []


def test_cycle_is_rejected() -> None:
    s, diags = analyze_structure(G().node("a", ECHO).node("b", ECHO).edge("a", "b").edge("b", "a").build(), CAT)
    assert s is None and [d.code for d in diags] == ["graph.cycle"]


def test_switch_dynamic_ports() -> None:
    cases = [{"port": "high", "when": True}, {"port": "low", "when": False}]
    s, diags = analyze_structure(G().node("sw", "flow.switch@1", {"cases": cases}).build(), CAT)
    assert diags == [] and s is not None and s.ports[nid("sw")] == ("default", "high", "low")
    dup = [{"port": "high", "when": True}, {"port": "high", "when": False}]
    assert codes(G().node("sw", "flow.switch@1", {"cases": dup}).build()) == ["node.dynamic_ports"]
    computed = {"$value": {"kind": "ref", "path": "trigger.cases"}}
    assert codes(G().node("sw", "flow.switch@1", {"cases": computed}).build()) == ["node.dynamic_ports"]


def test_nested_loop_regions() -> None:
    g = (
        G()
        .node("outer", LOOP, {"items": [1, 2]})
        .node("inner", LOOP, {"items": [3]})
        .node("x", ECHO)
        .node("y", ECHO)
        .node("z", ECHO)
        .edge("outer", "inner", "body")
        .edge("inner", "x", "body")
        .edge("inner", "y", "done")
        .edge("outer", "z", "done")
    )
    s, diags = analyze_structure(g.build(), CAT)
    assert diags == [] and s is not None
    assert s.region_of[nid("inner")] == nid("outer")
    assert s.region_of[nid("x")] == nid("inner") and s.region_of[nid("y")] == nid("outer")
    assert s.region_of[nid("z")] is None
    assert s.chain(nid("inner")) == [nid("inner"), nid("outer"), None]
    assert s.regions[nid("inner")].depth == 2


def test_region_entry_from_outside_is_rejected() -> None:
    g = (
        G()
        .node("l", LOOP, {"items": [1]})
        .node("a", ECHO)
        .node("c", ECHO)
        .edge("l", "a", "body")
        .edge("a", "c")
        .edge("l", "c", "done")
    )
    assert codes(g.build()) == ["loop.region_entry"]


def test_crossing_regions_are_rejected() -> None:
    g = (
        G()
        .node("l1", LOOP, {"items": [1]})
        .node("l2", LOOP, {"items": [1]})
        .node("a", ECHO)
        .node("b", ECHO)
        .node("m", ECHO)
        .edge("l1", "a", "body")
        .edge("l2", "b", "body")
        .edge("a", "m")
        .edge("b", "m")
    )
    assert "loop.region_crossing" in codes(g.build())


def test_loop_depth_is_capped() -> None:
    g = G()
    for i in range(4):
        g.node(f"l{i}", LOOP, {"items": [1]})
    g.node("leaf", ECHO)
    for i in range(3):
        g.edge(f"l{i}", f"l{i + 1}", "body")
    g.edge("l3", "leaf", "body")
    assert codes(g.build()) == ["loop.too_deep"]


def test_lifecycle_states_are_reported() -> None:
    cat = catalog(PLUGIN, TESTKIT, states={ECHO: "deprecated", "testkit.slow@1": "retired"})
    g = G().node("a", ECHO).node("b", "testkit.slow@1", {"seconds": 1}).build()
    assert codes(g, cat) == ["lifecycle.deprecated", "lifecycle.retired"]
