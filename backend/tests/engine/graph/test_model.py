# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest

from dewpoint.engine.graph.model import MAX_NODES, GraphFormatError, graph_hash, graph_json, parse_graph, version_hash
from tests.support.graphs import G, nid


def test_round_trip_keeps_the_from_alias() -> None:
    g = G().node("a", "testkit.echo@1").node("b", "testkit.echo@1").edge("a", "b").build()
    data = graph_json(g)
    assert data["edges"][0]["from"] == {"node": str(nid("a")), "port": "out"}
    assert parse_graph(data) == g


def test_graph_hash_is_stable_and_sensitive() -> None:
    a = G().node("a", "testkit.echo@1", {"value": 1}).build()
    b = G().node("a", "testkit.echo@1", {"value": 1}).build()
    c = G().node("a", "testkit.echo@1", {"value": 2}).build()
    assert graph_hash(a) == graph_hash(b) != graph_hash(c)


def test_version_hash_covers_what_publish_resolves() -> None:
    base: dict[str, Any] = {
        "graph_hash": "g",
        "subflow_pins": {"node": "v1"},
        "failure_handler_version_id": None,
        "cel_profile": "p",
        "engine_abi": 1,
    }
    h = version_hash(**base)
    for change in (
        {"graph_hash": "g2"},
        {"subflow_pins": {"node": "v2"}},
        {"failure_handler_version_id": "f"},
        {"cel_profile": "p2"},
        {"engine_abi": 2},
    ):
        assert version_hash(**{**base, **change}) != h, change


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"graph_format": 2}, "/graph_format"),
        ({"nodes": [{"id": str(nid("a")), "key": "Bad Key", "type": "testkit.echo@1"}]}, "/nodes/0/key"),
        ({"nodes": [{"id": str(nid("a")), "key": "a", "type": "testkit.echo"}]}, "/nodes/0/type"),
        ({"surprise": True}, "/surprise"),
    ],
)
def test_format_errors_point_at_the_field(data: dict[str, Any], field: str) -> None:
    with pytest.raises(GraphFormatError) as e:
        parse_graph(data)
    assert [d.field for d in e.value.diagnostics] == [field]
    assert all(d.code == "graph.format" for d in e.value.diagnostics)


def test_node_count_is_capped() -> None:
    g = G()
    for i in range(MAX_NODES + 1):
        g.node(f"n{i}", "testkit.echo@1")
    with pytest.raises(GraphFormatError):
        g.build()
