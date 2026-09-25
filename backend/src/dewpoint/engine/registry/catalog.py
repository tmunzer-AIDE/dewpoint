# SPDX-License-Identifier: Apache-2.0
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, TypeGuard

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from dewpoint.engine.canonical import sha256_hex
from dewpoint.engine.registry.control import CONTROL_TYPES
from dewpoint.engine.schema_refs import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE, ref_problems
from dewpoint.sdk.node import MAX_RETRY_ATTEMPTS, PORT_RE, RESERVED_PORTS, TYPE_RE, NodeKind, SideEffect
from dewpoint.sdk.version import SDK_MAJOR

_DISPLAY = frozenset({"title", "description"})  # manifest keys that may change within a version
_SCHEMA_ANNOTATIONS = frozenset({"title", "description", "examples", "x-widget", "x-group"})
_KINDS = {k.value for k in NodeKind}
_SIDE_EFFECTS = {s.value for s in SideEffect}


@dataclass(frozen=True)
class NodeTypeSpec:
    type: str
    version: int
    kind: str
    title: str
    ports: tuple[str, ...]
    dynamic_ports: str | None
    config_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    side_effect: str
    state: str = "active"

    @property
    def ref(self) -> str:
        return f"{self.type}@{self.version}"


def spec_from_manifest(m: Mapping[str, Any], state: str = "active") -> NodeTypeSpec:
    return NodeTypeSpec(
        type=m["type"],
        version=int(m["version"]),
        kind=m["kind"],
        title=m["title"],
        ports=tuple(m["ports"]),
        dynamic_ports=m.get("dynamic_ports"),
        config_schema=m["config_schema"],
        output_schema=m["output_schema"],
        side_effect=m["side_effect"],
        state=state,
    )


def _schema_contract(schema: Any) -> Any:
    """A schema without display annotations. Annotations are dropped only from schema objects, and only schema-valued
    keywords are traversed. Every other value (`default`, `const`, `enum`, `required`, `dependentRequired`, vendor
    `x-*` keys, ...) is kept verbatim, so `dependentRequired: {"title": [...]}` or a property named `title` stays part
    of the contract."""
    if not isinstance(schema, Mapping):
        return schema  # a boolean schema, or a malformed value: hashed verbatim
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _SCHEMA_ANNOTATIONS:
            continue
        if key in SCHEMA_ONE:
            out[key] = _schema_contract(value)
        elif key in SCHEMA_LIST and isinstance(value, list):
            out[key] = [_schema_contract(sub) for sub in value]
        elif key in SCHEMA_MAP and isinstance(value, Mapping):
            out[key] = {name: _schema_contract(sub) for name, sub in value.items()}
        else:
            out[key] = value
    return out


def contract_hash(m: Mapping[str, Any]) -> str:
    """Identity of a node type version's execution contract: every manifest field except display metadata.
    Published versions depend on it, so a registered version's contract may never change (sync refuses)."""
    contract = {k: v for k, v in m.items() if k not in _DISPLAY}
    for key in ("config_schema", "output_schema"):
        contract[key] = _schema_contract(m.get(key))
    return sha256_hex(contract)


class Catalog:
    def __init__(self, specs: Iterable[NodeTypeSpec]) -> None:
        self._by_ref = {s.ref: s for s in specs}

    def get(self, ref: str) -> NodeTypeSpec | None:
        return self._by_ref.get(ref)

    def refs(self) -> list[str]:
        return sorted(self._by_ref)


def _schema_problems(ref: str, label: str, schema: Any) -> list[str]:
    if not isinstance(schema, dict):
        return [f"{ref}: {label} must be an object"]
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        return [f"{ref}: {label} is not a valid JSON Schema ({e.message})"]
    if schema.get("type") != "object":
        return [f"{ref}: {label} must describe an object"]
    return [f"{ref}: {label}: {p}" for p in ref_problems(schema)]


_RETRY_KEYS = frozenset({"max_attempts", "initial_interval_s", "backoff", "max_interval_s", "non_retryable"})


def _finite(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _retry_problems(ref: str, retry: Any) -> list[str]:
    """The same rules the SDK applies to RetryDefaults, for manifests received as data."""
    usable = (
        isinstance(retry, Mapping)
        and set(retry) == _RETRY_KEYS
        and isinstance(retry["max_attempts"], int)
        and not isinstance(retry["max_attempts"], bool)
        and 1 <= retry["max_attempts"] <= MAX_RETRY_ATTEMPTS
        and _finite(retry["initial_interval_s"])
        and retry["initial_interval_s"] > 0
        and _finite(retry["backoff"])
        and retry["backoff"] >= 1
        and _finite(retry["max_interval_s"])
        and retry["max_interval_s"] >= retry["initial_interval_s"]
        and isinstance(retry["non_retryable"], list)
        and all(isinstance(code, str) and code for code in retry["non_retryable"])
    )
    if usable:
        return []
    return [
        f"{ref}: retry must be {{max_attempts: 1-{MAX_RETRY_ATTEMPTS}, initial_interval_s: > 0, backoff: ≥ 1, "
        "max_interval_s: ≥ initial_interval_s, non_retryable: [error codes]}"
    ]


def _dynamic_ports_problems(ref: str, n: Mapping[str, Any]) -> list[str]:
    field = n.get("dynamic_ports")
    if field is None:
        return []
    schema = n.get("config_schema")
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    if isinstance(field, str) and isinstance(props, Mapping) and field in props:
        return []
    return [f"{ref}: dynamic_ports must name a config field"]


def _node_problems(plugin: str, n: Mapping[str, Any], seen: set[str]) -> list[str]:
    t, v = n.get("type"), n.get("version")
    ref = f"{t}@{v}"
    if not isinstance(t, str) or not TYPE_RE.match(t) or not t.startswith(f"{plugin}."):
        return [f"{ref}: type must start with '{plugin}.'"]
    out: list[str] = []
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        out.append(f"{ref}: version must be an integer ≥ 1")
    if ref in seen:
        out.append(f"{ref}: duplicate node type version")
    seen.add(ref)
    title = n.get("title")
    if not isinstance(title, str) or not title:
        out.append(f"{ref}: title must be non-empty text")
    kind = n.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:  # type first: a list or dict is unhashable
        out.append(f"{ref}: unknown kind {kind!r}")
    elif kind == NodeKind.CONTROL and ref not in CONTROL_TYPES:
        out.append(f"{ref}: only engine control types may use kind 'control'")
    ports = n.get("ports")
    if (
        not isinstance(ports, list)
        or len(set(map(str, ports))) != len(ports)
        or any(not isinstance(p, str) or not PORT_RE.match(p) or p in RESERVED_PORTS for p in ports)
    ):
        out.append(f"{ref}: invalid ports")
    side_effect = n.get("side_effect")
    if not isinstance(side_effect, str) or side_effect not in _SIDE_EFFECTS:
        out.append(f"{ref}: unknown side_effect {side_effect!r}")
    out += _schema_problems(ref, "config_schema", n.get("config_schema"))
    out += _schema_problems(ref, "output_schema", n.get("output_schema"))
    out += _dynamic_ports_problems(ref, n)
    out += _retry_problems(ref, n.get("retry"))
    timeout = n.get("timeout_s")
    if not _finite(timeout) or timeout <= 0:
        out.append(f"{ref}: timeout_s must be a positive number")
    return out


def validate_plugin_manifest(m: Mapping[str, Any]) -> list[str]:
    """Checks a plugin manifest received as data. The SDK already checked first-party classes."""
    name = m.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name):
        return ["plugin name must be a lowercase identifier"]
    problems: list[str] = []
    if str(m.get("sdk_version", "")).split(".", 1)[0] != SDK_MAJOR:
        problems.append(f"{name}: built for SDK {m.get('sdk_version')!r}; this build provides SDK {SDK_MAJOR}.x")
    nodes = m.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return [*problems, f"{name}: declares no nodes"]
    seen: set[str] = set()
    for n in nodes:
        problems += _node_problems(name, n if isinstance(n, Mapping) else {}, seen)
    if name == "flow":
        problems += [f"flow: missing control type {ref}" for ref in sorted(CONTROL_TYPES - seen)]
    return problems
