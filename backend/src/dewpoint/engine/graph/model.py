# SPDX-License-Identifier: Apache-2.0
"""The workflow graph document (`graph_format: 1`)."""

import math
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
MAX_DEPTH = 64  # nesting of the whole document: far below pydantic's (~254) and jsonschema's (~97 schemas) limits
MAX_VALUES = 2_000  # value envelopes (refs, templates, expressions) per graph: bounds validation work
MAX_DIAGNOSTICS = 20


class _Strict(BaseModel):
    # allow_inf_nan=False: lax mode would otherwise turn the strings "NaN", "inf" or "1e400" into non-finite floats
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


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
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, allow_inf_nan=False)

    source: EdgeFrom = Field(alias="from")
    to: EdgeTo


def _object_schema() -> dict[str, Any]:
    return {"type": "object"}


def _vars_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {}}


class DeclassifySite(_Strict):
    """A decision that may turn tainted input into plain output (engine 2b spec §4.3): a node and its field."""

    node: uuid.UUID
    field: str = Field(max_length=200)


class GraphSettings(_Strict):
    input_schema: dict[str, Any] = Field(default_factory=_object_schema)
    vars_schema: dict[str, Any] = Field(default_factory=_vars_schema)  # every variable declares a default
    outputs: dict[str, Any] = Field(default_factory=dict)  # evaluated when the run succeeds
    failure_handler: uuid.UUID | None = None  # a workflow id, pinned to its active version at publish
    declassify: list[DeclassifySite] = Field(default_factory=list, max_length=200)  # §4.3: listed, never implied


class Graph(_Strict):
    graph_format: Literal[1] = 1
    nodes: tuple[GraphNode, ...] = Field(default=(), max_length=MAX_NODES)
    edges: tuple[Edge, ...] = Field(default=(), max_length=MAX_EDGES)
    settings: GraphSettings = Field(default_factory=GraphSettings)


class GraphFormatError(ValueError):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__("; ".join(d.message for d in diagnostics))
        self.diagnostics = diagnostics


def _escape(key: Any) -> str:
    return str(key).replace("~", "~0").replace("/", "~1")


def _admission_problems(data: Any) -> list[Diagnostic]:
    """Checks every value of the document before anything else touches it, iteratively so no input can exhaust the
    stack. Rejects non-finite numbers (Python's JSON parser accepts NaN, Infinity and 1e400; canonical JSON, the hashes
    and Postgres JSONB don't), nesting deeper than MAX_DEPTH, and more than MAX_VALUES value envelopes."""
    problems: list[Diagnostic] = []
    values = 0
    stack: list[tuple[Any, str, int]] = [(data, "", 1)]
    while stack and len(problems) < MAX_DIAGNOSTICS:
        value, path, depth = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            message = "Numbers must be finite: NaN and infinity aren't valid JSON."
            problems.append(Diagnostic(code="graph.format", field=path or "/", message=message))
            continue
        if not isinstance(value, Mapping | list | tuple):
            continue
        if depth > MAX_DEPTH:
            message = f"Values can be nested at most {MAX_DEPTH} levels deep."
            problems.append(Diagnostic(code="graph.format", field=path or "/", message=message))
            continue
        if isinstance(value, Mapping):
            if "$value" in value:
                values += 1
            stack.extend((item, f"{path}/{_escape(key)}", depth + 1) for key, item in value.items())
        else:
            stack.extend((item, f"{path}/{index}", depth + 1) for index, item in enumerate(value))
    if values > MAX_VALUES:
        message = f"A workflow can hold at most {MAX_VALUES} references, templates and expressions."
        problems.append(Diagnostic(code="graph.format", field="/", message=message))
    return problems


def parse_graph(data: Any) -> Graph:
    problems = _admission_problems(data)
    if problems:
        raise GraphFormatError(sorted(problems, key=lambda d: d.field or ""))
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
