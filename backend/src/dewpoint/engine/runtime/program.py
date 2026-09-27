# SPDX-License-Identifier: Apache-2.0
"""A published version compiled for execution (spec §6): each step with its edges by port, its region and its
topological index, and the expression records by (node, field). Built once per run from the loaded version, and
never changed."""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.graph.model import Graph, parse_graph
from dewpoint.engine.graph.structure import ERROR_PORT, Region, analyze_structure
from dewpoint.engine.graph.values import CelValue, Value, ValueSyntaxError, iter_values, pointer_str
from dewpoint.engine.registry.catalog import Catalog, spec_from_manifest

BODY, DONE = "body", "done"


class ProgramError(ValueError):
    """The version can't be executed. Publish validated it, so this means the stored version is damaged."""


@dataclass(frozen=True)
class Edge:
    index: int
    source: uuid.UUID
    port: str
    target: uuid.UUID


@dataclass(frozen=True)
class Step:
    id: uuid.UUID
    key: str
    ref: str  # type@version
    control: bool  # run by the interpreter (the flow plugin); otherwise an activity named `type.vN`
    region: uuid.UUID | None  # the loop whose body holds it; None for the root region
    topo: int
    on_error: str  # fail | continue | port
    timeout_s: float | None
    max_attempts: int | None
    config: Mapping[str, Any]
    values: tuple[tuple[str, Value], ...]  # every envelope in the config, by JSON pointer, in pointer order
    ports: tuple[str, ...]  # normal ports ("error" excluded)
    out: Mapping[str, tuple[int, ...]]  # edges leaving each port, "error" included when connected
    ins: tuple[int, ...]  # edges arriving, body edges from the step's own loop included


@dataclass(frozen=True)
class Program:
    graph: Graph
    steps: Mapping[uuid.UUID, Step]
    edges: tuple[Edge, ...]
    regions: Mapping[uuid.UUID | None, Region]
    by_key: Mapping[str, uuid.UUID]
    records: Mapping[tuple[str | None, str], ExpressionRecord]
    manifests: Mapping[str, Mapping[str, Any]]  # type@version -> the registered manifest
    cel_profile: str

    def chain(self, region: uuid.UUID | None) -> list[uuid.UUID | None]:
        """`region` and every region enclosing it, innermost first, ending with the root (None)."""
        out: list[uuid.UUID | None] = [region]
        while region is not None:
            region = self.regions[region].parent
            out.append(region)
        return out

    def record(self, step: uuid.UUID | None, field: str) -> ExpressionRecord:
        found = self.records.get((str(step) if step is not None else None, field))
        if found is None:
            raise ProgramError(f"no expression record for {field!r}")
        return found


def compile_program(
    graph_json: Mapping[str, Any],
    manifests: Mapping[str, Mapping[str, Any]],
    expressions: Iterable[Mapping[str, Any]],
    cel_profile: str,
) -> Program:
    graph = parse_graph(graph_json)
    structure, diagnostics = analyze_structure(graph, Catalog(spec_from_manifest(m) for m in manifests.values()))
    errors = [d for d in diagnostics if d.severity == "error"]
    if structure is None or errors:
        raise ProgramError("; ".join(d.message for d in errors) or "the graph can't be analyzed")
    edges = tuple(Edge(i, e.source.node, e.source.port, e.to.node) for i, e in enumerate(graph.edges))
    topo = {n: i for i, n in enumerate(structure.topo)}
    steps: dict[uuid.UUID, Step] = {}
    for node_id in structure.topo:  # a fixed order, so every mapping below is built the same way everywhere
        node = structure.nodes[node_id]
        values: list[tuple[str, Value]] = []
        for pointer, value in iter_values(node.config):
            if isinstance(value, ValueSyntaxError):
                raise ProgramError(f"`{node.key}`: {value.message}")
            values.append((pointer_str(pointer), value))
        out: dict[str, list[int]] = {}
        for e in edges:
            if e.source == node_id:
                out.setdefault(e.port, []).append(e.index)
        steps[node_id] = Step(
            id=node_id,
            key=node.key,
            ref=node.type,
            control=structure.specs[node_id].kind == "control",
            region=structure.region_of[node_id],
            topo=topo[node_id],
            on_error=node.options.on_error,
            timeout_s=node.options.timeout_s,
            max_attempts=node.options.max_attempts,
            config=node.config,
            values=tuple(values),
            ports=structure.ports[node_id],
            out={port: tuple(ids) for port, ids in sorted(out.items())},
            ins=tuple(e.index for e in edges if e.target == node_id),
        )
    records = {(r.node, r.field): r for r in (ExpressionRecord.from_json(x) for x in expressions)}
    for step in steps.values():  # every CEL value needs its record: checked before any step runs
        for field, value in step.values:
            if isinstance(value, CelValue) and (str(step.id), field) not in records:
                raise ProgramError(f"`{step.key}`: no expression record for {field}")
    for path, value in iter_values(graph.settings.outputs, ("settings", "outputs")):
        if isinstance(value, ValueSyntaxError):  # publish refuses these: the stored version is damaged
            raise ProgramError(f"output {pointer_str(path)}: {value.message}")
        if isinstance(value, CelValue) and (None, pointer_str(path)) not in records:
            raise ProgramError(f"no expression record for {pointer_str(path)}")
    return Program(
        graph=graph,
        steps=steps,
        edges=edges,
        regions=structure.regions,
        by_key=dict(structure.by_key),
        records=records,
        manifests=dict(manifests),
        cel_profile=cel_profile,
    )


__all__ = ["BODY", "DONE", "ERROR_PORT", "Edge", "Program", "ProgramError", "Step", "compile_program"]
