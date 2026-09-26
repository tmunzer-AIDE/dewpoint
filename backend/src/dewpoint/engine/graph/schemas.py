# SPDX-License-Identifier: Apache-2.0
"""Just enough JSON Schema to type references: navigation, nullability, type compatibility and markers.

Schemas returned by `navigate`, `target_schema` and `element_schema` are *standalone*: they carry the root's
`$defs`, so they can be navigated again on their own."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

from dewpoint.engine.schema_refs import PREFIX, SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE
from dewpoint.sdk.fields import KINDS, LITERAL

Schema = Mapping[str, Any]
_PY_TYPES: tuple[tuple[type, str], ...] = (
    (bool, "boolean"),  # before int: bool is a subclass of int
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (list, "array"),
    (dict, "object"),
    (type(None), "null"),
)


class PathError(ValueError):
    """The path names something the schema says can't exist."""


@dataclass(frozen=True)
class Resolved:
    schema: Schema | None  # None: unknown, any value
    conditional: bool  # may be missing or null at run time


def literal_type(value: Any) -> str:
    for py, name in _PY_TYPES:
        if isinstance(value, py):
            return name
    return "object"


def _deref(root: Schema, schema: Any) -> Schema | None:
    hops = 0
    while isinstance(schema, Mapping) and "$ref" in schema:
        ref = schema["$ref"]
        defs = root.get("$defs")
        if not isinstance(ref, str) or not ref.startswith("#/$defs/") or not isinstance(defs, Mapping) or hops > 32:
            return None
        schema = defs.get(ref[len("#/$defs/") :])
        hops += 1
    return schema if isinstance(schema, Mapping) else None


def _strip_null(schema: Schema) -> tuple[Schema, bool]:
    for key in ("anyOf", "oneOf"):
        options = schema.get(key)
        if isinstance(options, list):
            non_null = [o for o in options if not (isinstance(o, Mapping) and o.get("type") == "null")]
            if len(non_null) == 1 and len(options) > 1 and isinstance(non_null[0], Mapping):
                rest = {k: v for k, v in schema.items() if k != key}
                return {**rest, **non_null[0]}, True
    t = schema.get("type")
    if isinstance(t, list) and "null" in t:
        others = [x for x in t if x != "null"]
        return {**schema, "type": others[0] if len(others) == 1 else others}, True
    return schema, False


def standalone(root: Schema, schema: Schema) -> Schema:
    defs = root.get("$defs")
    if isinstance(defs, Mapping) and "$defs" not in schema:
        return {**schema, "$defs": defs}
    return schema


def json_types(schema: Any) -> frozenset[str] | None:
    """The JSON types a (standalone) schema admits, or None for 'anything'."""
    if not isinstance(schema, Mapping):
        return None
    s = _deref(schema, schema)
    if s is None:
        return None
    if "const" in s:
        return frozenset({literal_type(s["const"])})
    if isinstance(s.get("enum"), list):
        return frozenset(literal_type(v) for v in s["enum"])
    t = s.get("type")
    if isinstance(t, str):
        return frozenset({t})
    if isinstance(t, list):
        return frozenset(x for x in t if isinstance(x, str))
    for key in ("anyOf", "oneOf"):
        options = s.get(key)
        if isinstance(options, list):
            out: set[str] = set()
            for option in options:
                inner = standalone(schema, option) if isinstance(option, Mapping) else option
                types = json_types(inner)
                if types is None:
                    return None
                out |= types
            return frozenset(out)
    return None


def compatible(source: Any, target: Any) -> bool:
    """True when every type the source admits fits the target. Unknown on either side: the runtime check decides."""
    s, t = json_types(source), json_types(target)
    if s is None or t is None:
        return True
    return all(kind in t or (kind == "integer" and "number" in t) for kind in s)


def describe(schema: Any) -> str:
    types = json_types(schema)
    return "any value" if types is None else " or ".join(sorted(types))


def navigate(root: Any, path: Sequence[str | int], start: Any = None) -> Resolved:
    """Follow a reference path through an output schema. Raises PathError for fields a closed schema lacks."""
    if not isinstance(root, Mapping):
        return Resolved(None, bool(path))
    current: Any = root if start is None else start
    conditional = False
    for seg in path:
        schema = _deref(root, current)
        if schema is None:
            return Resolved(None, True)
        schema, nullable = _strip_null(schema)
        schema = _deref(root, schema)
        if schema is None:
            return Resolved(None, True)
        conditional |= nullable
        types = json_types(standalone(root, schema))
        if isinstance(seg, int):
            if types is not None and "array" not in types:
                raise PathError(f"[{seg}] indexes a value that isn't a list")
            items = schema.get("items")
            if not isinstance(items, Mapping) or not items:
                return Resolved(None, True)
            current, conditional = items, True  # the list may be shorter
            continue
        props = schema.get("properties")
        if isinstance(props, Mapping) and seg in props:
            required = schema.get("required")
            if not (isinstance(required, list) and seg in required):
                conditional = True
            current = props[seg]
            continue
        if types is not None and "object" not in types:
            raise PathError(f"`{seg}` reads a field of a value that isn't an object")
        extra = schema.get("additionalProperties")
        if isinstance(extra, Mapping) and extra:
            current, conditional = extra, True
            continue
        if extra is False:  # only a closed object rules the field out; otherwise it may exist
            raise PathError(f"there is no field `{seg}`")
        return Resolved(None, True)
    final = _deref(root, current)
    if final is None:
        return Resolved(None, conditional)
    final, nullable = _strip_null(final)
    resolved = _deref(root, final)
    if resolved is None:
        return Resolved(None, True)
    return Resolved(standalone(root, resolved), conditional or nullable)


def element_schema(schema: Schema | None) -> Schema | None:
    """The item schema of a list schema, or None when unknown."""
    if schema is None:
        return None
    types = json_types(schema)
    if types is not None and "array" not in types:
        return None
    try:
        return navigate(schema, [0]).schema
    except PathError:
        return None


def _steps(root: Schema, pointer: Sequence[str | int]) -> list[tuple[Schema, Schema]] | None:
    """For each pointer segment in a *config* schema: the subschema as written and after $ref resolution.
    None when the pointer leaves the schema."""
    out: list[tuple[Schema, Schema]] = []
    current: Schema = root
    for seg in pointer:
        base = _deref(root, _strip_null(current)[0])
        if base is None:
            return None
        if isinstance(seg, int):
            nxt = base.get("items")
        else:
            props = base.get("properties")
            if isinstance(props, Mapping) and seg in props:
                nxt = props[seg]
            else:
                extra = base.get("additionalProperties")
                nxt = extra if isinstance(extra, Mapping) else None
        if not isinstance(nxt, Mapping):
            return None
        resolved = _deref(root, nxt)
        if resolved is None:
            return None
        out.append((nxt, resolved))
        current = resolved
    return out


def target_schema(root: Any, pointer: Sequence[str | int]) -> Schema | None:
    """The schema a value written at `pointer` in a config must satisfy (nullability kept), or None if unknown."""
    if not isinstance(root, Mapping):
        return None
    if not pointer:
        return root
    steps = _steps(root, pointer)
    return standalone(root, steps[-1][1]) if steps else None


def literal_on_path(root: Any, pointer: Sequence[str | int]) -> bool:
    if not isinstance(root, Mapping):
        return False
    steps = _steps(root, pointer) or []
    return any(raw.get(LITERAL) is True or resolved.get(LITERAL) is True for raw, resolved in steps)


def contains_literal(root: Any, schema: Any, _seen: frozenset[str] = frozenset()) -> bool:
    """True when `schema` or anything nested in it must be written literally."""
    if not isinstance(root, Mapping) or not isinstance(schema, Mapping):
        return False
    if schema.get(LITERAL) is True:
        return True
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref not in _seen:
        if contains_literal(root, _deref(standalone(root, schema), {"$ref": ref}), _seen | {ref}):
            return True
    children: list[Any] = []
    props = schema.get("properties")
    if isinstance(props, Mapping):
        children += list(props.values())
    for key in ("items", "additionalProperties"):
        if isinstance(schema.get(key), Mapping):
            children.append(schema[key])
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        if isinstance(schema.get(key), list):
            children += schema[key]
    return any(contains_literal(root, child, _seen) for child in children)


def allowed_kinds(root: Any, pointer: Sequence[str | int]) -> frozenset[str] | None:
    if not isinstance(root, Mapping) or not pointer:
        return None
    steps = _steps(root, pointer)
    if not steps:
        return None
    raw, resolved = steps[-1]
    kinds = raw.get(KINDS, resolved.get(KINDS))
    return frozenset(kinds) if isinstance(kinds, list) else None


def _rename_refs(node: Any, names: Mapping[str, str]) -> Any:
    """Rewrite `#/$defs/<old>` to `#/$defs/<new>` in schema positions. Data (defaults, enums, ...) is copied as is."""
    if not isinstance(node, Mapping):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "$ref" and isinstance(value, str) and value.startswith(PREFIX) and value[len(PREFIX) :] in names:
            out[key] = PREFIX + names[value[len(PREFIX) :]]
        elif key in SCHEMA_ONE:
            out[key] = _rename_refs(value, names)
        elif key in SCHEMA_LIST and isinstance(value, list):
            out[key] = [_rename_refs(sub, names) for sub in value]
        elif key in SCHEMA_MAP and isinstance(value, Mapping):
            out[key] = {name: _rename_refs(sub, names) for name, sub in value.items()}
        else:
            out[key] = value
    return out


def object_schema(props: Mapping[str, Mapping[str, Any]], required: Sequence[str]) -> dict[str, Any]:
    """A closed object schema built from per-field schemas that may each carry their own `$defs`.
    Each field keeps its reference scope: its definitions move under a per-field name (`f<index>.<name>`) and its
    `$ref`s are rewritten to match, so two fields may both define `Item` differently."""
    defs: dict[str, Any] = {}
    fields: dict[str, Any] = {}
    for index, (name, schema) in enumerate(props.items()):
        local = schema.get("$defs")
        names = {key: f"f{index}.{key}" for key in local} if isinstance(local, Mapping) else {}
        fields[name] = _rename_refs({k: v for k, v in schema.items() if k != "$defs"}, names)
        for key, sub in local.items() if isinstance(local, Mapping) else ():
            defs[names[key]] = _rename_refs(sub, names)
    out: dict[str, Any] = {
        "type": "object",
        "properties": fields,
        "required": list(required),
        "additionalProperties": False,
    }
    if defs:
        out["$defs"] = defs
    return out


def widen(schema: Schema | None, default: Any) -> Schema | None:
    """What a reference with a default can produce. When the default itself satisfies the referenced schema, that
    schema still describes every outcome. Otherwise the default adds an *open* alternative of its JSON type, so
    fields of the referenced schema (required ones included) become possibly missing, as they are when the default
    is used."""
    if schema is None or _fits(schema, default):
        return schema
    kind = literal_type(default)
    out: dict[str, Any] = {"anyOf": [{k: v for k, v in schema.items() if k != "$defs"}, {"type": kind}]}
    if "$defs" in schema:
        out["$defs"] = schema["$defs"]
    return out


def _fits(schema: Schema, value: Any) -> bool:
    try:
        return bool(Draft202012Validator(schema).is_valid(value))
    except (SchemaError, Unresolvable):
        return False
