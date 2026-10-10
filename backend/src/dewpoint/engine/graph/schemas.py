# SPDX-License-Identifier: Apache-2.0
"""Just enough JSON Schema to type references: navigation, nullability, type compatibility and markers.

Schemas returned by `navigate`, `target_schema` and `element_schema` are *standalone*: they carry the root's
`$defs`, so they can be navigated again on their own."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing.exceptions import Unresolvable

from dewpoint.engine.schema_refs import PREFIX, SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE
from dewpoint.engine.taint import CLEAN, Shape
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
    taint: Shape = CLEAN  # which parts are tainted (engine 2b spec §4.1)
    missing: bool = False  # may be absent: `navigate` and the resolver say; elsewhere `conditional` says it all
    nullable: bool = False  # the value itself may be null


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
    members = s.get("allOf")
    if isinstance(members, list):  # every member applies: what they all allow (4c-2a ruling 1)
        common: frozenset[str] | None = None
        for member in members:
            types = json_types(standalone(schema, member)) if isinstance(member, Mapping) else None
            if types is not None:
                common = types if common is None else meet(common, types)
        return common
    return None


def meet(a: frozenset[str], b: frozenset[str]) -> frozenset[str]:
    """The JSON types both allow. An integer is a number: `number` and `integer` meet in `integer`."""
    out = set(a & b)
    if ("integer" in a and "number" in b) or ("number" in a and "integer" in b):
        out.add("integer")
    return frozenset(out)


def compatible(source: Any, target: Any) -> bool:
    """True when every type the source admits fits the target. Unknown on either side: the runtime check decides."""
    s, t = json_types(source), json_types(target)
    if s is None or t is None:
        return True
    return all(kind in t or (kind == "integer" and "number" in t) for kind in s)


def describe(schema: Any) -> str:
    types = json_types(schema)
    return "any value" if types is None else " or ".join(sorted(types))


MAX_ALTERNATIVES = 64  # ways a value may match at one position, duplicates merged; past it, any value
MAX_UNION_DEPTH = 8  # unions and `allOf` nested in one another, unfolded
MAX_STEPS = 4096  # schemas one read unfolds in all, every position counted; past it, any value
Way = tuple[Schema, ...]  # one way a value may match: schemas that all apply to it (a branch, and what surrounds it)


class _Budget:
    """The work one read may do (4c-2a ruling 1): shared by every position it unfolds."""

    def __init__(self) -> None:
        self.left = MAX_STEPS

    def spend(self, n: int = 1) -> bool:
        self.left -= n
        return self.left >= 0


def _key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _merged(ways: list[Way]) -> list[Way]:
    return list({_key(w): w for w in ways}.values())


def _product(left: list[Way], right: list[Way], budget: _Budget) -> list[Way] | None:
    """Every way of both: what one allows and the other allows too (a conjunction)."""
    if not budget.spend(len(left) * len(right)):
        return None
    out = _merged([a + b for a in left for b in right])
    return out if len(out) <= MAX_ALTERNATIVES else None


def _ways(root: Schema, schema: Any, depth: int, budget: _Budget) -> list[Way] | None:
    """The ways a value may match `schema`, each a conjunction of schemas with no union or `allOf` left on top. The
    schema around a union or an `allOf` is kept beside each branch, never overwritten by it."""
    if not budget.spend():
        return None
    s = _deref(root, schema)
    if s is None or depth > MAX_UNION_DEPTH:
        return None
    key = next((k for k in ("allOf", "anyOf", "oneOf") if k in s), None)
    if key is None:
        return [(s,)]
    options = s[key]
    if not isinstance(options, list) or not options:
        return None
    ways = _ways(root, {k: v for k, v in s.items() if k != key}, depth + 1, budget)
    if ways is None:
        return None
    if key == "allOf":  # every member applies
        for option in options:
            member = _ways(root, option, depth + 1, budget)
            ways = None if member is None else _product(ways, member, budget)
            if ways is None:
                return None
        return ways
    branches: list[Way] = []  # one of them applies
    for option in options:
        branch = _ways(root, option, depth + 1, budget)
        if branch is None:
            return None
        branches += branch
    return _product(ways, _merged(branches), budget)


def _types(root: Schema, way: Way) -> frozenset[str] | None:
    """The JSON types a value matching every schema of `way` may have; None: any."""
    out: frozenset[str] | None = None
    for schema in way:
        types = json_types(standalone(root, schema))
        if types is not None:
            out = types if out is None else meet(out, types)
    return out


def alternatives(root: Schema, schemas: Any, budget: _Budget | None = None) -> tuple[list[Way], bool] | None:
    """The ways a value matching every schema of `schemas` (one schema, or a conjunction) may match, and whether it may
    also be null. A way only null is dropped and counted as "may be null"; one no value matches (its types
    contradict) is dropped. A position that is only null gives no way and "may be null": its reader decides. None:
    unknown (a `$ref` that doesn't resolve, an alternative that isn't a schema, an empty union, past the bounds)."""
    budget = budget or _Budget()
    ways: list[Way] = [()]
    for schema in schemas if isinstance(schemas, tuple) else (schemas,):
        found = _ways(root, schema, 0, budget)
        ways = None if found is None else _product(ways, found, budget)  # type: ignore[assignment]
        if ways is None:
            return None
    out: list[Way] = []
    nulls = False
    for way in ways:
        types = _types(root, way)
        if types is not None and not types:
            continue
        if types is not None and "null" in types:
            nulls = True
            if types == {"null"}:
                continue
            way = (*way, {"type": sorted(types - {"null"})})
        out.append(way)
    return out, nulls


def _step(root: Schema, way: Way, seg: str | int) -> tuple[Way, bool] | PathError | None:
    """One way, one segment: the schemas there (all apply) and whether it may be absent; a PathError when this way
    can't hold it; None when it says nothing about it (any value). Object keywords (`properties`, `required`) speak only
    of objects, and `items` only of lists: a field is sure to be there only when the value is sure to be an object."""
    types = _types(root, way)
    if isinstance(seg, int):
        if types is not None and "array" not in types:
            return PathError(f"[{seg}] indexes a value that isn't a list")
        items = tuple(s["items"] for s in way if isinstance(s.get("items"), Mapping) and s["items"])
        return (items, True) if items else None  # the list may be shorter, or the value not a list
    if types is not None and "object" not in types:
        return PathError(f"`{seg}` reads a field of a value that isn't an object")
    surely_object = types == frozenset({"object"})
    declared = tuple(
        s["properties"][seg] for s in way if isinstance(s.get("properties"), Mapping) and seg in s["properties"]
    )
    if declared:
        required = any(isinstance(s.get("required"), list) and seg in s["required"] for s in way)
        return declared, not (required and surely_object)
    extra = tuple(
        s["additionalProperties"]
        for s in way
        if isinstance(s.get("additionalProperties"), Mapping) and s["additionalProperties"]
    )
    if extra:
        return extra, True
    if any(s.get("additionalProperties") is False for s in way):  # only a closed object rules the field out
        return PathError(f"there is no field `{seg}`")
    return None


def navigate(root: Any, path: Sequence[str | int], start: Any = None) -> Resolved:
    """Follow a reference path through an output schema. Raises PathError for a field no alternative can hold.

    Alternatives are followed together, on the safe side (engine-core spec §4.3; 4c-2a ruling 1): the value may be
    anything one of them allows there; it may be missing when one of them may lack it; it is any value when one of them
    says nothing about it. What surrounds a union, and every member of an `allOf`, applies to each of its branches."""
    if not isinstance(root, Mapping):
        return Resolved(None, bool(path), missing=bool(path))
    budget = _Budget()
    frontier: list[Way] = [(root if start is None else start,)]
    missing = False
    for seg in path:
        found: list[Way] = []
        refused: PathError | None = None
        for position in frontier:
            unfolded = alternatives(root, position, budget)
            if unfolded is None:
                return Resolved(None, True, missing=True)
            ways, nullable = unfolded
            missing |= nullable  # a null value has no fields and no items
            for way in ways or [({"type": "null"},)]:  # only null: it refuses the read, as before
                step = _step(root, way, seg)
                if step is None:
                    return Resolved(None, True, missing=True)
                if isinstance(step, PathError):
                    missing, refused = True, refused or step  # when the value is this way, it's missing
                    continue
                found.append(step[0])
                missing |= step[1]
        if not found:
            raise refused or PathError(f"there is no field `{seg}`")
        frontier = _merged(found)
        if len(frontier) > MAX_ALTERNATIVES:
            return Resolved(None, True, missing=True)
    return _end(root, frontier, missing, budget)


def _end(root: Schema, frontier: list[Way], missing: bool, budget: _Budget) -> Resolved:
    schemas: list[Schema] = []
    nullable = False
    for position in frontier:
        known = tuple(s for s in position if _deref(root, s) is not None)
        if not known:  # a boolean schema, or one that doesn't resolve: any value, as before
            return Resolved(None, missing, missing=missing)
        unfolded = alternatives(root, known, budget)
        if unfolded is None:
            return Resolved(None, True, missing=True)
        ways, maybe_null = unfolded
        nullable |= maybe_null
        schemas += [way[0] if len(way) == 1 else {"allOf": list(way)} for way in ways]
    if not schemas:  # only null: null is its value, as before
        return Resolved(standalone(root, {"type": "null"}), missing, missing=missing)
    unique = list({_key(s): s for s in schemas}.values())
    merged = unique[0] if len(unique) == 1 else {"anyOf": unique}
    return Resolved(standalone(root, merged), missing or nullable, missing=missing, nullable=nullable)


Obligation = Literal["optional", "nullable", "non_object"]


def _declared(root: Any, path: Sequence[str | int], start: Any, mode: Obligation) -> tuple[int, ...]:
    """Positions in `path` of declared fields a read can fail at: one that may be absent (`optional`), null
    (`nullable`), or something other than an object (`non_object`: a scalar or a list beside an object, which has no
    fields to read).

    Every way of the value is followed (4c-2a ruling 1). A way that can't be an object, or a closed one without the
    field, lacks it. It stops where the schema stops describing the data: an open way that doesn't declare the field, a
    type it doesn't say, a list index, past the bounds. Data the schema doesn't declare carries no such promise, and
    needs no guard (spec §4.3)."""
    if not isinstance(root, Mapping):
        return ()
    budget = _Budget()
    frontier: list[Way] = [(root if start is None else start,)]
    out: list[int] = []
    for i, seg in enumerate(path):
        if isinstance(seg, int):
            break
        ways: list[Way] = []
        for position in frontier:
            unfolded = alternatives(root, position, budget)
            if unfolded is None:
                return tuple(out)
            ways += unfolded[0]
        fields: list[Way] = []
        absent = False
        for way in ways:
            types = _types(root, way)
            if types is not None and "object" not in types:
                absent = True  # a scalar or a list here: no fields
                continue
            declared = tuple(
                s["properties"][seg] for s in way if isinstance(s.get("properties"), Mapping) and seg in s["properties"]
            )
            if not declared:
                if any(s.get("additionalProperties") is False for s in way):
                    absent = True  # closed without it
                    continue
                return tuple(out)  # open: undeclared from here
            fields.append(declared)
            required = any(isinstance(s.get("required"), list) and seg in s["required"] for s in way)
            absent |= not (required and types == frozenset({"object"}))
        if not fields:
            return tuple(out)
        if mode == "optional":
            flagged = absent
        else:
            flagged = False
            for field in fields:
                found = alternatives(root, field, budget)
                if found is None:
                    continue
                if mode == "nullable":
                    flagged |= found[1]
                else:
                    flagged |= any((t := _types(root, w)) is not None and bool(t - {"object"}) for w in found[0])
        if flagged:
            out.append(i)
        frontier = _merged(fields)
        if len(frontier) > MAX_ALTERNATIVES:
            return tuple(out)
    return tuple(out)


def declared_optional(root: Any, path: Sequence[str | int], start: Any = None) -> tuple[int, ...]:
    """Positions in `path` of fields the schema declares but that may be absent: CEL guards them with `has()`."""
    return _declared(root, path, start, "optional")


def declared_nullable(root: Any, path: Sequence[str | int], start: Any = None) -> tuple[int, ...]:
    """Positions in `path` of fields the schema declares may be null: CEL guards reads below them with `!= null`."""
    return _declared(root, path, start, "nullable")


def declared_non_object(root: Any, path: Sequence[str | int], start: Any = None) -> tuple[int, ...]:
    """Positions in `path` of fields the schema declares may be something other than an object (a scalar or a list,
    beside an object): CEL guards reads below them, `has()` included, with `type(x) == map`."""
    return _declared(root, path, start, "non_object")


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
