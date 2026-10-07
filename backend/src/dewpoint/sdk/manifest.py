# SPDX-License-Identifier: Apache-2.0
import math
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from pydantic.json_schema import GenerateJsonSchema
from pydantic_core import core_schema

from dewpoint.sdk.connections import ConnectionType
from dewpoint.sdk.declared import DeclaredModel
from dewpoint.sdk.fields import CONNECTION, OPTIONS
from dewpoint.sdk.node import ICON_RE, MAX_RETRY_ATTEMPTS, PORT_RE, RESERVED_PORTS, TYPE_RE, Node, NodeKind, SideEffect
from dewpoint.sdk.triggers import Trigger, trigger_problems
from dewpoint.sdk.version import SDK_VERSION

PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,40}$")

# JSON Schema 2020-12 keywords whose values are schemas. The engine keeps the same lists (engine/schema_refs.py; a test
# checks they agree): the SDK can't import the engine.
SCHEMA_ONE = frozenset(
    {
        "additionalProperties",
        "items",
        "contains",
        "propertyNames",
        "not",
        "if",
        "then",
        "else",
        "unevaluatedItems",
        "unevaluatedProperties",
        "contentSchema",
    }
)
SCHEMA_LIST = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
SCHEMA_MAP = frozenset({"properties", "patternProperties", "$defs", "dependentSchemas"})


class _SerializedOutput(GenerateJsonSchema):
    """Output schemas describe what serialization emits. Pydantic leaves fields with defaults out of `required`
    (unless a model sets json_schema_serialization_defaults_required), yet model_dump always emits them: a reference
    or a CEL guard must not treat them as possibly missing. TypedDict keys that aren't required, and fields excluded
    conditionally, can be absent from the output, so they keep pydantic's answer."""

    def field_is_required(
        self,
        field: core_schema.ModelField | core_schema.DataclassField | core_schema.TypedDictField,
        total: bool,
    ) -> bool:
        if field["type"] == "typed-dict-field" or field.get("serialization_exclude_if") is not None:
            return super().field_is_required(field, total)
        return True


def dump_output(output: BaseModel) -> dict[str, Any]:
    """The one way a node's output becomes JSON: by alias, as the output schema names it, with every field."""
    return output.model_dump(mode="json", by_alias=True)


_FUNCTION_SERIALIZERS = frozenset({"function-plain", "function-wrap"})
_CONTAINERS = ("model", "dataclass", "typed-dict")


def _pydantic_own(function: Any) -> bool:
    """Pydantic's serializers for its own types (paths, addresses, URLs, secrets…) emit what those types' schemas
    say. Anything else, a plugin's or a third-party type's, has to declare its return type."""
    module = getattr(function, "__module__", None) or ""
    return module == "pydantic" or module.startswith(("pydantic.", "pydantic_core"))


def _serializer_problems(schema: Any) -> list[str]:
    """Where an output's JSON can differ from its generated schema, anywhere inside the output:
    - a model, dataclass or TypedDict that serializes itself (`@model_serializer`) can drop or rename promised fields;
    - a field serializer without a return type (an unannotated `@field_serializer`, a `PlainSerializer` or
      `WrapSerializer` without `return_type`) leaves the field's own type in the schema, whatever it emits."""
    found: set[str] = set()
    seen: set[int] = set()
    stack: list[tuple[Any, str]] = [(schema, "the output")]
    while stack:
        node, where = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, list | tuple):
            stack.extend((item, where) for item in node)
            continue
        if not isinstance(node, dict):
            continue
        kind = node.get("type")
        if kind in _CONTAINERS and node.get("cls") is not None:
            where = node["cls"].__name__
        ser = node.get("serialization")
        if isinstance(ser, dict) and ser.get("type") in _FUNCTION_SERIALIZERS:
            if kind in _CONTAINERS:
                found.add(
                    f"output type {where} uses @model_serializer; outputs must serialize field by field "
                    "(use fields, computed fields or field serializers)"
                )
            elif "return_schema" not in ser and not _pydantic_own(ser.get("function")):
                found.add(
                    f"{where} has a serializer without a declared return type; declare it (`-> str`, or "
                    "`return_type=`) so the output schema says what it emits"
                )
        fields = node.get("fields")
        if isinstance(fields, dict):  # model and TypedDict fields, by name
            stack.extend((field, f"{where}.{name}") for name, field in fields.items())
        elif isinstance(fields, list):  # dataclass fields
            stack.extend((f, f"{where}.{f.get('name')}" if isinstance(f, dict) else where) for f in fields)
        stack.extend((value, where) for key, value in node.items() if key != "fields")
    return sorted(found)


def _closed(schema: Any) -> Any:
    """Pydantic serialization emits only declared fields unless a model allows extras (it then says
    `additionalProperties: true`). Say so in the output schema, so references to undeclared fields are caught."""
    if not isinstance(schema, dict):
        return schema
    out = dict(schema)
    if "properties" in out and "additionalProperties" not in out:
        out["additionalProperties"] = False
    for key, value in out.items():
        if key in SCHEMA_ONE:
            out[key] = _closed(value)
        elif key in SCHEMA_LIST and isinstance(value, list):
            out[key] = [_closed(sub) for sub in value]
        elif key in SCHEMA_MAP and isinstance(value, dict):
            out[key] = {name: _closed(sub) for name, sub in value.items()}
    return out


class ManifestError(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _retry_problems(name: str, node: type[Node]) -> list[str]:
    """A retry policy the engine can actually run (Temporal needs a positive interval and a backoff of at least 1)."""
    r = node.retry
    out: list[str] = []
    if (
        isinstance(r.max_attempts, bool)
        or not isinstance(r.max_attempts, int)
        or not 1 <= r.max_attempts <= MAX_RETRY_ATTEMPTS
    ):
        out.append(f"{name}: retry.max_attempts must be between 1 and {MAX_RETRY_ATTEMPTS}")
    if r.initial_interval.total_seconds() <= 0:
        out.append(f"{name}: retry.initial_interval must be positive")
    if (
        isinstance(r.backoff, bool)
        or not isinstance(r.backoff, int | float)
        or not math.isfinite(r.backoff)
        or r.backoff < 1
    ):
        out.append(f"{name}: retry.backoff must be a finite number ≥ 1")
    if r.max_interval < r.initial_interval:
        out.append(f"{name}: retry.max_interval must be ≥ retry.initial_interval")
    if not all(isinstance(code, str) and code for code in r.non_retryable):
        out.append(f"{name}: retry.non_retryable must list error codes")
    return out


def _nested(schema: dict[str, Any], marker: str) -> bool:
    """Whether `marker` appears anywhere but on a top-level property."""
    top = schema.get("properties", {})
    stack: list[Any] = [(k, v) for k, v in schema.items() if k != "properties"]
    stack += [(k, v) for sub in top.values() if isinstance(sub, dict) for k, v in sub.items() if k != marker]
    while stack:
        key, value = stack.pop()
        if key == marker:
            return True
        if isinstance(value, dict):
            stack.extend(value.items())
        elif isinstance(value, list):
            stack.extend(("", item) for item in value)
    return False


def _connection_problems(name: str, node: type[Node]) -> list[str]:
    """A connection field (plugins-3 D6) is a top-level config property whose type the node lists in `credentials`:
    publish and the worker look for connections only there."""
    schema = node.Config.model_json_schema(mode="validation")
    out: list[str] = []
    for prop, sub in schema.get("properties", {}).items():
        wanted = sub.get(CONNECTION) if isinstance(sub, dict) else None
        if wanted is not None and wanted not in node.credentials:
            out.append(f"{name}: connection field {prop!r} needs {wanted!r} in credentials")
    if _nested(schema, CONNECTION):
        out.append(f"{name}: a connection field must be a top-level config property")
    return out


def options_fields(node: type[Node]) -> list[str]:
    """The node's options fields (plugins-3 D3): top-level config properties marked `options_field`."""
    props = node.Config.model_json_schema(mode="validation").get("properties", {})
    return sorted(prop for prop, sub in props.items() if isinstance(sub, dict) and sub.get(OPTIONS) is True)


def _options_problems(name: str, node: type[Node]) -> list[str]:
    """The API asks for options only for a top-level field the manifest lists, and the node answers them."""
    out: list[str] = []
    if _nested(node.Config.model_json_schema(mode="validation"), OPTIONS):
        out.append(f"{name}: an options field must be a top-level config property")
    if options_fields(node) and node.options is Node.options:
        out.append(f"{name}: a node with options fields must implement options()")
    return out


def _problems(node: type[Node]) -> list[str]:
    missing = [a for a in ("type", "version", "title") if not hasattr(node, a)]
    if missing:
        return [f"{node.__name__}: missing {', '.join(missing)}"]
    name = f"{node.type}@{node.version}"
    out: list[str] = []
    if not TYPE_RE.match(node.type):
        out.append(f"{name}: type must look like 'plugin.name'")
    if isinstance(node.version, bool) or not isinstance(node.version, int) or node.version < 1:
        out.append(f"{name}: version must be an integer ≥ 1")
    if len(set(node.ports)) != len(node.ports):
        out.append(f"{name}: duplicate ports")
    for port in node.ports:
        if not PORT_RE.match(port) or port in RESERVED_PORTS:
            out.append(f"{name}: invalid port {port!r}")
    if node.dynamic_ports is not None and node.dynamic_ports not in node.Config.model_fields:
        out.append(f"{name}: dynamic_ports names unknown config field {node.dynamic_ports!r}")
    out += _retry_problems(name, node)
    out += _connection_problems(name, node)
    out += _options_problems(name, node)
    if node.icon is not None and (not isinstance(node.icon, str) or not ICON_RE.match(node.icon)):
        out.append(f"{name}: icon must name a first-party icon (lowercase letters, digits and dashes)")
    out += [f"{name}: {problem}" for problem in _serializer_problems(node.Output.__pydantic_core_schema__)]
    if node.timeout.total_seconds() <= 0:
        out.append(f"{name}: timeout must be positive")
    if node.kind is NodeKind.ACTION:
        if node.run is Node.run:
            out.append(f"{name}: action nodes must implement run()")
        if node.side_effect is SideEffect.RECONCILABLE and node.reconcile is Node.reconcile:
            out.append(f"{name}: RECONCILABLE nodes must implement reconcile()")
    return out


def _output_schema(output: type[BaseModel]) -> dict[str, Any]:
    """What serialization emits: a model's fields, closed; a declared model's schema as declared (plugins-3 D23)."""
    if issubclass(output, DeclaredModel):
        return output.model_json_schema()
    return _closed(output.model_json_schema(mode="serialization", schema_generator=_SerializedOutput))  # type: ignore[no-any-return]


def node_manifest(node: type[Node]) -> dict[str, Any]:
    problems = _problems(node)
    if problems:
        raise ManifestError(problems)
    r = node.retry
    out: dict[str, Any] = {
        "type": node.type,
        "version": node.version,
        "kind": node.kind.value,
        "title": node.title,
        "description": node.description,
        "ports": list(node.ports),
        "dynamic_ports": node.dynamic_ports,
        "config_schema": node.Config.model_json_schema(mode="validation"),
        "output_schema": _output_schema(node.Output),
        "credentials": list(node.credentials),
        "capabilities": sorted(node.capabilities),
        "side_effect": node.side_effect.value,
        "retry": {
            "max_attempts": r.max_attempts,
            "initial_interval_s": r.initial_interval.total_seconds(),
            "backoff": r.backoff,
            "max_interval_s": r.max_interval.total_seconds(),
            "non_retryable": list(r.non_retryable),
        },
        "timeout_s": node.timeout.total_seconds(),
    }
    # Each only when set, so the hashes of nodes without them don't move (plugins-3 D12).
    if node.icon is not None:
        out["icon"] = node.icon
    if fields := options_fields(node):
        out["options"] = fields
    return out


@dataclass(frozen=True)
class Plugin:
    name: str
    version: str
    nodes: tuple[type[Node], ...]
    connection_types: tuple[ConnectionType, ...] = ()
    triggers: tuple[Trigger, ...] = ()

    def manifest(self) -> dict[str, Any]:
        problems: list[str] = []
        if not PLUGIN_NAME_RE.match(self.name):
            problems.append(f"plugin name {self.name!r} must be a lowercase identifier")
        nodes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for node in self.nodes:
            try:
                m = node_manifest(node)
            except ManifestError as e:
                problems.extend(e.problems)
                continue
            ref = f"{m['type']}@{m['version']}"
            if not m["type"].startswith(f"{self.name}."):
                problems.append(f"{ref}: type must start with '{self.name}.'")
            if ref in seen:
                problems.append(f"{ref}: duplicate node type version")
            seen.add(ref)
            nodes.append(m)
        kinds: list[dict[str, Any]] = []
        for kind in self.connection_types:
            found = kind.problems()
            if kind.key != self.name and not kind.key.startswith(f"{self.name}."):
                found.append(f"connection type {kind.key!r} must be named {self.name!r} or start with '{self.name}.'")
            if any(k["key"] == kind.key for k in kinds):
                found.append(f"duplicate connection type {kind.key!r}")
            problems += found
            if not found:
                kinds.append(kind.manifest())
        triggers: list[dict[str, Any]] = []
        for trigger in self.triggers:
            m = trigger.manifest()
            found = trigger_problems(self.name, m)
            if any(t["key"] == trigger.key for t in triggers):
                found.append(f"duplicate trigger {trigger.key!r}")
            problems += found
            if not found:
                triggers.append(m)
        if not self.nodes and not self.connection_types and not self.triggers:
            problems.append(f"plugin {self.name!r} declares nothing: no node, connection type or trigger")
        if problems:
            raise ManifestError(problems)
        out: dict[str, Any] = {"name": self.name, "version": self.version, "sdk_version": SDK_VERSION, "nodes": nodes}
        if kinds:
            out["connection_types"] = kinds
        if triggers:
            out["triggers"] = triggers
        return out
