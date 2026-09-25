# SPDX-License-Identifier: Apache-2.0
"""The workflow graph document (`graph_format: 1`)."""

import uuid
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from dewpoint.engine.canonical import sha256_hex
from dewpoint.engine.graph.diagnostics import Diagnostic

KEY_PATTERN = r"^[a-z][a-z0-9_]{0,62}$"
TYPE_REF_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+@[1-9][0-9]{0,3}$"
PORT_PATTERN = r"^[a-z][a-z0-9_]{0,30}$"
MAX_NODES = 500
MAX_EDGES = 2000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Position(_Strict):
    x: float = 0
    y: float = 0


class Options(_Strict):
    timeout_s: float | None = Field(default=None, gt=0, le=86_400)
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    on_error: Literal["fail", "continue", "port"] = "fail"


class GraphNode(_Strict):
    id: uuid.UUID
    key: str = Field(pattern=KEY_PATTERN)
    type: str = Field(pattern=TYPE_REF_PATTERN)
    config: dict[str, Any] = Field(default_factory=dict)
    position: Position = Field(default_factory=Position)
    options: Options = Field(default_factory=Options)


class EdgeFrom(_Strict):
    node: uuid.UUID
    port: str = Field(default="out", pattern=PORT_PATTERN)


class EdgeTo(_Strict):
    node: uuid.UUID


class Edge(_Strict):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    source: EdgeFrom = Field(alias="from")
    to: EdgeTo


def _object_schema() -> dict[str, Any]:
    return {"type": "object"}


def _vars_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


class GraphSettings(_Strict):
    input_schema: dict[str, Any] = Field(default_factory=_object_schema)
    vars_schema: dict[str, Any] = Field(default_factory=_vars_schema)  # every variable declares a default
    outputs: dict[str, Any] = Field(default_factory=dict)  # evaluated when the run succeeds
    failure_handler: uuid.UUID | None = None  # a workflow id, pinned to its active version at publish


class Graph(_Strict):
    graph_format: Literal[1] = 1
    nodes: tuple[GraphNode, ...] = Field(default=(), max_length=MAX_NODES)
    edges: tuple[Edge, ...] = Field(default=(), max_length=MAX_EDGES)
    settings: GraphSettings = Field(default_factory=GraphSettings)


class GraphFormatError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__("; ".join(d.message for d in diagnostics))
        self.diagnostics = diagnostics


def parse_graph(data: Any) -> Graph:
    try:
        return Graph.model_validate(data)
    except ValidationError as e:
        raise GraphFormatError(
            [
                Diagnostic(code="graph.format", field="".join(f"/{p}" for p in err["loc"]), message=err["msg"])
                for err in e.errors()
            ]
        ) from None


def graph_json(graph: Graph) -> dict[str, Any]:
    return graph.model_dump(mode="json", by_alias=True)


def graph_hash(graph: Graph) -> str:
    """The authored graph only. Two versions with equal graph hashes may still run different sub-flow versions."""
    return sha256_hex(graph_json(graph))


def version_hash(
    *,
    graph_hash: str,
    subflow_pins: Mapping[str, str],
    failure_handler_version_id: str | None,
    cel_profile: str,
    engine_abi: int,
) -> str:
    """Identity of an executable version: the graph plus everything resolved at publish that changes what runs.
    Pinned versions are immutable, so the pins identify the whole closure. Audit and integrity checks use this."""
    return sha256_hex(
        {
            "graph_hash": graph_hash,
            "subflow_pins": dict(subflow_pins),
            "failure_handler_version_id": failure_handler_version_id,
            "cel_profile": cel_profile,
            "engine_abi": engine_abi,
        }
    )
