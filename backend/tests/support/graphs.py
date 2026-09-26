# SPDX-License-Identifier: Apache-2.0
"""A tiny graph builder for tests. Node ids derive from keys, so tests refer to nodes by key."""

import uuid
from typing import Any

from dewpoint.engine.graph.model import Graph, parse_graph

NS = uuid.UUID("8f5a3c1e-7d2b-4e6a-9c0d-5b1f2e3a4c6d")


def nid(key: str) -> uuid.UUID:
    return uuid.uuid5(NS, key)


class G:
    def __init__(self) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.edges: list[dict[str, Any]] = []
        self.settings: dict[str, Any] = {}

    def node(self, key: str, type_ref: str, config: dict[str, Any] | None = None, on_error: str = "fail") -> "G":
        self.nodes.append(
            {
                "id": str(nid(key)),
                "key": key,
                "type": type_ref,
                "config": config or {},
                "options": {"on_error": on_error},
            }
        )
        return self

    def edge(self, src: str, dst: str, port: str = "out") -> "G":
        self.edges.append({"from": {"node": str(nid(src)), "port": port}, "to": {"node": str(nid(dst))}})
        return self

    def data(self) -> dict[str, Any]:
        return {"graph_format": 1, "nodes": self.nodes, "edges": self.edges, "settings": self.settings}

    def build(self) -> Graph:
        return parse_graph(self.data())


def ref(path: str, **extra: Any) -> dict[str, Any]:
    return {"$value": {"kind": "ref", "path": path, **extra}}


def cel(expr: str) -> dict[str, Any]:
    return {"$value": {"kind": "cel", "expr": expr}}


def template(*parts: str | dict[str, Any]) -> dict[str, Any]:
    return {"$value": {"kind": "template", "parts": [{"text": p} if isinstance(p, str) else p for p in parts]}}
