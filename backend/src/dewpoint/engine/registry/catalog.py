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
from dewpoint.sdk.connections import HEADER_RE, HOST_RE, SCOPE_KIND_RE, TYPE_KEY_RE, template_parts
from dewpoint.sdk.fields import OPTIONS, SENSITIVE
from dewpoint.sdk.node import ICON_RE, MAX_RETRY_ATTEMPTS, PORT_RE, RESERVED_PORTS, TYPE_RE, NodeKind, SideEffect
from dewpoint.sdk.version import SDK_MAJOR

_DISPLAY = frozenset({"title", "description", "icon"})  # manifest keys that may change within a version
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
    options: tuple[str, ...] = ()  # the options fields (plugins-3 D3)
    credentials: tuple[str, ...] = ()  # the connection types it may use (plugins-3 D4)

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
        options=tuple(m.get("options", ())),
        credentials=tuple(m.get("credentials", ())),
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


def marked_below_top(schema: Mapping[str, Any], marker: str) -> bool:
    """Whether `marker` appears anywhere but on a top-level property."""
    stack: list[Any] = [v for k, v in schema.items() if k != "properties"]
    props = schema.get("properties")
    if isinstance(props, Mapping):
        stack += [v for sub in props.values() if isinstance(sub, Mapping) for k, v in sub.items() if k != marker]
    while stack:
        value = stack.pop()
        if isinstance(value, Mapping):
            if marker in value:
                return True
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return False


def _options_problems(ref: str, n: Mapping[str, Any]) -> list[str]:
    """`options` lists exactly the top-level config properties marked as options fields (plugins-3 D3): the API asks
    only for those."""
    schema = n.get("config_schema")
    if not isinstance(schema, Mapping):
        return []
    props = schema.get("properties")
    props = props if isinstance(props, Mapping) else {}
    marked = sorted(p for p, sub in props.items() if isinstance(sub, Mapping) and sub.get(OPTIONS) is True)
    listed = n.get("options", [])
    if (
        not isinstance(listed, list)
        or ("options" in n and not listed)
        or not all(isinstance(f, str) for f in listed)
        or len(set(listed)) != len(listed)
    ):
        return [f"{ref}: options must list config fields, once each"]
    out = [f"{ref}: options field {f!r} isn't a top-level config property marked {OPTIONS}" for f in listed
           if f not in marked]  # fmt: skip
    out += [f"{ref}: config_schema marks {f!r} as an options field, which options doesn't list" for f in marked
            if f not in listed]  # fmt: skip
    if marked_below_top(schema, OPTIONS):
        out.append(f"{ref}: an options field must be a top-level config property")
    return out


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
    icon = n.get("icon")
    if "icon" in n and (not isinstance(icon, str) or not ICON_RE.match(icon)):
        out.append(f"{ref}: icon must name a first-party icon (lowercase letters, digits and dashes)")
    out += _options_problems(ref, n)
    return out


def _props(schema: Any) -> Mapping[str, Any]:
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    return props if isinstance(props, Mapping) else {}


def _auth_problems(name: str, auth: Any, secret_fields: Mapping[str, Any]) -> list[str]:
    if auth is None:
        return []
    template = auth.get("template") if isinstance(auth, Mapping) else None
    if (
        not isinstance(auth, Mapping)
        or set(auth) != {"kind", "header", "template"}
        or auth["kind"] != "header"
        or not isinstance(auth["header"], str)
        or not HEADER_RE.match(auth["header"])
        or not isinstance(template, str)
        or any(c in template for c in "\r\n\0")
    ):
        return [f"{name}: auth must be {{kind: header, header: a header name, template: one line}}"]
    try:
        named = [n for _, n in template_parts(template) if n is not None]
    except ValueError:
        return [f"{name}: auth template may only name fields ({{field}}), with no format spec or conversion"]
    return [f"{name}: auth template names {n!r}, not a secret field" for n in named if n not in secret_fields]


def _host_problems(name: str, host: Any, config_fields: Mapping[str, Any]) -> list[str]:
    if host is None:
        return []
    if not isinstance(host, Mapping) or host.get("kind") not in ("map", "url_field"):
        return [f"{name}: host must be {{kind: map, field, hosts}} or {{kind: url_field, field}}"]
    field = host.get("field")
    if not isinstance(field, str) or field not in config_fields:
        return [f"{name}: host field {field!r} isn't a config field"]
    if host["kind"] == "url_field":
        return [] if set(host) == {"kind", "field"} else [f"{name}: host has unknown keys"]
    hosts = host.get("hosts")
    if set(host) != {"kind", "field", "hosts"} or not isinstance(hosts, Mapping) or not hosts:
        return [f"{name}: a host map needs hosts"]
    out = [f"{name}: host {h!r} must be a host name" for h in hosts.values() if not isinstance(h, str)
           or not HOST_RE.match(h)]  # fmt: skip
    prop = config_fields[field]
    enum = prop.get("enum") if isinstance(prop, Mapping) else None
    if not isinstance(enum, list) or sorted(map(str, enum)) != sorted(map(str, hosts)):
        out.append(f"{name}: host field {field!r} must allow exactly the host map's keys")
    return out


def _scope_problems(name: str, key: str, scope: Any, config_fields: Mapping[str, Any],
                    secret_fields: Mapping[str, Any]) -> list[str]:  # fmt: skip
    if not isinstance(scope, Mapping) or set(scope) != {"kind", "config", "secret", "capacity", "refill_per_s"}:
        return [f"{name}: a rate scope must be {{kind, config, secret, capacity, refill_per_s}}"]
    kind, config, secret = scope["kind"], scope["config"], scope["secret"]
    where = f"{name}: rate scope {kind!r}"
    out: list[str] = []
    if not isinstance(kind, str) or not SCOPE_KIND_RE.match(kind) or not kind.startswith(f"{key}."):
        out.append(f"{where} must start with '{key}.'")
    if not isinstance(config, list) or not all(isinstance(c, str) for c in config):
        out.append(f"{where}: config must list config fields")
    else:
        out += [f"{where} names {c!r}, not a config field" for c in config if c not in config_fields]
    if secret is not None and (not isinstance(secret, str) or secret not in secret_fields):
        out.append(f"{where} names {secret!r}, not a secret field")
    if not all(_finite(scope[k]) and scope[k] > 0 for k in ("capacity", "refill_per_s")):
        out.append(f"{where} needs a positive capacity and refill_per_s")
    return out


def _required(schema: Any) -> set[str]:
    found = schema.get("required") if isinstance(schema, Mapping) else None
    return {r for r in found if isinstance(r, str)} if isinstance(found, list) else set()


def _required_problems(name: str, t: Mapping[str, Any]) -> list[str]:
    """The fields the host, the auth template and the rate scopes read are required (see the SDK's rule)."""
    config, secret = _required(t.get("config_schema")), _required(t.get("secret_schema"))
    config_fields, secret_fields = _props(t.get("config_schema")), _props(t.get("secret_schema"))
    out: list[str] = []
    host, auth, scopes = t.get("host"), t.get("auth"), t.get("rate_scopes")
    field = host.get("field") if isinstance(host, Mapping) else None
    if field in config_fields and field not in config:
        out.append(f"{name}: host field {field!r} must be required")
    template = auth.get("template") if isinstance(auth, Mapping) else None
    if isinstance(template, str):
        try:
            named = [n for _, n in template_parts(template) if n is not None]
        except ValueError:
            named = []
        out += [f"{name}: auth template names {n!r}, which must be required" for n in named
                if n in secret_fields and n not in secret]  # fmt: skip
    for scope in scopes if isinstance(scopes, list) else []:
        if not isinstance(scope, Mapping):
            continue
        kind, names = scope.get("kind"), scope.get("config")
        names = names if isinstance(names, list) else []
        out += [f"{name}: rate scope {kind!r} names {n!r}, which must be required" for n in names
                if n in config_fields and n not in config]  # fmt: skip
        if scope.get("secret") in secret_fields and scope.get("secret") not in secret:
            out.append(f"{name}: rate scope {kind!r} names {scope.get('secret')!r}, which must be required")
    return out


def _connection_type_problems(plugin: str, t: Any, seen: set[str]) -> list[str]:
    """The same rules the SDK applies to a ConnectionType (plugins-3 D11), for one received as data."""
    key = t.get("key") if isinstance(t, Mapping) else None
    name = f"connection type {key!r}"
    if not isinstance(key, str) or not TYPE_KEY_RE.match(key) or (key != plugin and not key.startswith(f"{plugin}.")):
        return [f"{name} must be named {plugin!r} or start with '{plugin}.'"]
    assert isinstance(t, Mapping)  # noqa: S101 - a key was read from it
    out: list[str] = []
    if key in seen:
        out.append(f"duplicate connection type {key!r}")
    seen.add(key)
    expected = {"key", "label", "config_schema", "secret_schema", "auth", "host", "rate_scopes", "verify"}
    if set(t) != expected:
        out.append(f"{name}: needs exactly {sorted(expected)}")
    label = t.get("label")
    if not isinstance(label, str) or not 0 < len(label) <= 100:
        out.append(f"{name}: label must be 1-100 characters")
    for which in ("config_schema", "secret_schema"):
        schema = t.get(which)
        found = _schema_problems(name, which, schema)
        if not found and isinstance(schema, Mapping) and schema.get("additionalProperties") is not False:
            found.append(f"{name}: {which} must refuse additional properties")
        out += found
    config_fields, secret_fields = _props(t.get("config_schema")), _props(t.get("secret_schema"))
    for prop, sub in secret_fields.items():
        if not isinstance(sub, Mapping) or sub.get(SENSITIVE) is not True or sub.get("type") != "string":
            out.append(f"{name}: secret field {prop!r} must be an x-sensitive string")
    out += _auth_problems(name, t.get("auth"), secret_fields)
    out += _host_problems(name, t.get("host"), config_fields)
    scopes = t.get("rate_scopes")
    if not isinstance(scopes, list):
        out.append(f"{name}: rate_scopes must be a list")
    else:
        for scope in scopes:
            out += _scope_problems(name, key, scope, config_fields, secret_fields)
    if not isinstance(t.get("verify"), bool):
        out.append(f"{name}: verify must be true or false")
    out += _required_problems(name, t)
    return out


def validate_plugin_manifest(m: Mapping[str, Any]) -> list[str]:
    """Checks a plugin manifest received as data. The SDK already checked first-party classes."""
    name = m.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", name):
        return ["plugin name must be a lowercase identifier"]
    problems: list[str] = []
    if str(m.get("sdk_version", "")).split(".", 1)[0] != SDK_MAJOR:
        problems.append(f"{name}: built for SDK {m.get('sdk_version')!r}; this build provides SDK {SDK_MAJOR}.x")
    nodes, kinds = m.get("nodes"), m.get("connection_types", [])
    if not isinstance(nodes, list) or not isinstance(kinds, list) or ("connection_types" in m and not kinds):
        return [*problems, f"{name}: nodes and connection_types must be lists (connection_types only when set)"]
    if not nodes and not kinds:
        return [*problems, f"{name}: declares nothing: no node and no connection type"]
    seen: set[str] = set()
    for n in nodes:
        problems += _node_problems(name, n if isinstance(n, Mapping) else {}, seen)
    seen_types: set[str] = set()
    for t in kinds:
        problems += _connection_type_problems(name, t, seen_types)
    if name == "flow":
        problems += [f"flow: missing control type {ref}" for ref in sorted(CONTROL_TYPES - seen)]
    return problems
