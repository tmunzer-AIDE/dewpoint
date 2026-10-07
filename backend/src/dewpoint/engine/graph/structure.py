# SPDX-License-Identifier: Apache-2.0
"""Structural analysis: node types, ports, edges, acyclicity and loop regions (spec §4.2)."""

import heapq
import uuid
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass

from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.graph.model import Edge, Graph, GraphNode
from dewpoint.engine.registry.catalog import Catalog, NodeTypeSpec
from dewpoint.engine.registry.control import LOOP
from dewpoint.sdk.node import PORT_RE, RESERVED_PORTS

MAX_LOOP_DEPTH = 3
ERROR_PORT = "error"


@dataclass(frozen=True)
class Region:
    loop: uuid.UUID | None  # None is the run's root region
    parent: uuid.UUID | None  # the region containing the loop node (None = root; also None for the root itself)
    members: tuple[uuid.UUID, ...]  # nodes whose innermost region this is, in topological order
    depth: int  # 0 for the root, 1 for a top-level loop body, ...


@dataclass(frozen=True)
class Structure:
    nodes: Mapping[uuid.UUID, GraphNode]
    specs: Mapping[uuid.UUID, NodeTypeSpec]
    ports: Mapping[uuid.UUID, tuple[str, ...]]  # normal ports: static then dynamic ("error" excluded)
    out_edges: Mapping[uuid.UUID, tuple[Edge, ...]]
    in_edges: Mapping[uuid.UUID, tuple[Edge, ...]]
    topo: tuple[uuid.UUID, ...]
    regions: Mapping[uuid.UUID | None, Region]
    region_of: Mapping[uuid.UUID, uuid.UUID | None]
    by_key: Mapping[str, uuid.UUID]

    def chain(self, region: uuid.UUID | None) -> list[uuid.UUID | None]:
        """`region` and every region enclosing it, innermost first, ending with the root (None)."""
        out: list[uuid.UUID | None] = [region]
        while region is not None:
            region = self.regions[region].parent
            out.append(region)
        return out


def _dynamic_ports(node: GraphNode, spec: NodeTypeSpec) -> tuple[list[str], list[Diagnostic]]:
    field = spec.dynamic_ports
    if field is None:
        return [], []
    raw = node.config.get(field)
    bad = Diagnostic(
        code="node.dynamic_ports",
        node=node.id,
        field=f"/{field}",
        message=f"`{field}` must be a list written in the graph, each entry with a unique literal `port` name "
        f"other than {', '.join(sorted({*spec.ports, *RESERVED_PORTS}))}.",
    )
    if not isinstance(raw, list):
        return [], [bad]
    ports: list[str] = []
    for item in raw:
        port = item.get("port") if isinstance(item, dict) else None
        if not isinstance(port, str) or not PORT_RE.fullmatch(port) or port in RESERVED_PORTS:
            return [], [bad]
        if port in spec.ports or port in ports:
            return [], [bad]
        ports.append(port)
    return ports, []


def _topo(nodes: Mapping[uuid.UUID, GraphNode], out_edges: Mapping[uuid.UUID, list[Edge]]) -> list[uuid.UUID]:
    """Kahn's algorithm; ties broken by node key so the order is deterministic."""
    indeg = {i: 0 for i in nodes}
    for edges in out_edges.values():
        for e in edges:
            indeg[e.to.node] += 1
    ready = [(nodes[i].key, i) for i, d in indeg.items() if d == 0]
    heapq.heapify(ready)
    order: list[uuid.UUID] = []
    while ready:
        _, i = heapq.heappop(ready)
        order.append(i)
        for e in out_edges[i]:
            indeg[e.to.node] -= 1
            if indeg[e.to.node] == 0:
                heapq.heappush(ready, (nodes[e.to.node].key, e.to.node))
    return order


def analyze_structure(graph: Graph, catalog: Catalog) -> tuple[Structure | None, list[Diagnostic]]:
    diags: list[Diagnostic] = []
    nodes: dict[uuid.UUID, GraphNode] = {}
    by_key: dict[str, uuid.UUID] = {}
    for n in graph.nodes:
        if n.id in nodes:
            diags.append(Diagnostic(code="graph.duplicate_id", node=n.id, message="Two steps share this id."))
            continue
        if n.key in by_key:
            diags.append(
                Diagnostic(
                    code="graph.duplicate_key",
                    node=n.id,
                    message=f"Another step is already called `{n.key}`.",
                    fix="Rename one of them.",
                )
            )
            continue
        nodes[n.id] = n
        by_key[n.key] = n.id

    specs: dict[uuid.UUID, NodeTypeSpec] = {}
    ports: dict[uuid.UUID, tuple[str, ...]] = {}
    for n in nodes.values():
        spec = catalog.get(n.type)
        if spec is None:
            diags.append(
                Diagnostic(code="node.unknown_type", node=n.id, message=f"`{n.type}` isn't installed on this platform.")
            )
            continue
        if spec.state == "retired":
            diags.append(
                Diagnostic(
                    code="lifecycle.retired",
                    node=n.id,
                    message=f"`{n.type}` has been retired.",
                    fix="Replace this step.",
                )
            )
        elif spec.state == "deprecated":
            diags.append(
                Diagnostic(
                    code="lifecycle.deprecated",
                    node=n.id,
                    message=f"`{n.type}` is deprecated; new versions can't use it.",
                    fix="Migrate this step to the newer version.",
                )
            )
        specs[n.id] = spec
        dynamic, problems = _dynamic_ports(n, spec)
        diags += problems
        ports[n.id] = (*spec.ports, *dynamic)
    if len(specs) != len(nodes):
        return None, diags  # edges can't be checked without every step's contract

    out_edges: dict[uuid.UUID, list[Edge]] = {i: [] for i in nodes}
    in_edges: dict[uuid.UUID, list[Edge]] = {i: [] for i in nodes}
    seen: set[tuple[uuid.UUID, str, uuid.UUID]] = set()
    for e in graph.edges:
        src, dst = e.source.node, e.to.node
        if src not in nodes or dst not in nodes:
            diags.append(Diagnostic(code="edge.unknown_node", message="An edge points to a step that doesn't exist."))
            continue
        allowed = ports[src] + ((ERROR_PORT,) if nodes[src].options.on_error == "port" else ())
        if e.source.port not in allowed:
            diags.append(
                Diagnostic(
                    code="edge.unknown_port",
                    node=src,
                    message=f"`{nodes[src].key}` has no `{e.source.port}` output.",
                )
            )
            continue
        if src == dst:
            diags.append(Diagnostic(code="edge.self", node=src, message="A step can't connect to itself."))
            continue
        if (src, e.source.port, dst) in seen:
            diags.append(Diagnostic(code="edge.duplicate", node=src, message="This connection exists twice."))
            continue
        seen.add((src, e.source.port, dst))
        out_edges[src].append(e)
        in_edges[dst].append(e)
    for n in nodes.values():
        if n.options.on_error == "port" and not any(e.source.port == ERROR_PORT for e in out_edges[n.id]):
            diags.append(
                Diagnostic(
                    code="node.error_port_unconnected",
                    node=n.id,
                    message="Errors go to the `error` output, but nothing is connected to it.",
                    fix="Connect the error output, or choose another error behaviour.",
                )
            )

    topo = _topo(nodes, out_edges)
    if len(topo) != len(nodes):
        placed = set(topo)
        stuck = sorted(nodes[i].key for i in nodes if i not in placed)
        diags.append(
            Diagnostic(
                code="graph.cycle",
                message=f"These steps form a cycle: {', '.join(stuck)}.",
                fix="Use a Loop step to repeat work.",
            )
        )
        return None, diags

    loops = [i for i in topo if specs[i].ref == LOOP]
    bodies: dict[uuid.UUID, set[uuid.UUID]] = {}
    for loop in loops:
        start = [e.to.node for e in out_edges[loop] if e.source.port == "body"]
        if not start:
            diags.append(
                Diagnostic(
                    code="loop.empty_body", node=loop, message="Nothing is connected to the loop's `body` output."
                )
            )
        body: set[uuid.UUID] = set()
        queue = deque(start)
        while queue:
            v = queue.popleft()
            if v not in body:
                body.add(v)
                queue.extend(e.to.node for e in out_edges[v])
        bodies[loop] = body

    regions_ok = True
    for index, a in enumerate(loops):
        for b in loops[index + 1 :]:
            if bodies[a] & bodies[b] and b not in bodies[a] and a not in bodies[b]:
                diags.append(
                    Diagnostic(
                        code="loop.region_crossing",
                        node=b,
                        message=f"The bodies of loops `{nodes[a].key}` and `{nodes[b].key}` overlap, "
                        "but neither contains the other.",
                        fix="Nest one loop entirely inside the other, or keep their bodies separate.",
                    )
                )
                regions_ok = False
    for loop in loops:
        for v in sorted(bodies[loop], key=lambda i: nodes[i].key):
            for e in in_edges[v]:
                src = e.source.node
                if src in bodies[loop] or (src == loop and e.source.port == "body"):
                    continue
                diags.append(
                    Diagnostic(
                        code="loop.region_entry",
                        node=v,
                        message=f"`{nodes[v].key}` is inside loop `{nodes[loop].key}` but is also reached from "
                        f"`{nodes[src].key}`, outside it.",
                        fix="Connect steps that follow the loop to its `done` output only.",
                    )
                )
                regions_ok = False
    if not regions_ok:
        return None, diags

    containing = {i: [loop for loop in loops if i in bodies[loop]] for i in nodes}
    for loop in loops:
        if 1 + len(containing[loop]) > MAX_LOOP_DEPTH:
            diags.append(
                Diagnostic(
                    code="loop.too_deep", node=loop, message=f"Loops can be nested at most {MAX_LOOP_DEPTH} deep."
                )
            )
            regions_ok = False
    if not regions_ok:
        return None, diags

    region_of: dict[uuid.UUID, uuid.UUID | None] = {
        i: (min(containing[i], key=lambda loop: len(bodies[loop])) if containing[i] else None) for i in nodes
    }
    regions: dict[uuid.UUID | None, Region] = {
        None: Region(loop=None, parent=None, members=tuple(i for i in topo if region_of[i] is None), depth=0)
    }
    for loop in loops:
        regions[loop] = Region(
            loop=loop,
            parent=region_of[loop],
            members=tuple(i for i in topo if region_of[i] == loop),
            depth=1 + len(containing[loop]),
        )
    structure = Structure(
        nodes=nodes,
        specs=specs,
        ports=ports,
        out_edges={k: tuple(v) for k, v in out_edges.items()},
        in_edges={k: tuple(v) for k, v in in_edges.items()},
        topo=tuple(topo),
        regions=regions,
        region_of=region_of,
        by_key=by_key,
    )
    return structure, diags
