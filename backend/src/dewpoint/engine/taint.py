# SPDX-License-Identifier: Apache-2.0
"""Taint (engine 2b spec §4.1): which parts of a value are tainted, decided at publish, per path, never per value.

A `Shape` says it of a value: all of it, none of it, or part by part (fields by name, with a rule for other keys, and
one for list elements). Shapes come from schemas where data enters a run, and travel with the values the validator
resolves: references, transforms, loops' collected items, filters, sub-flows' outputs. From a schema, a position marked
`x-sensitive` is tainted, a map whose keys are marked is tainted whole, and so is any position the schema doesn't
declare: unknown counts as sensitive.

A schema is read as the ways a value can match it: `$ref` and `allOf` add schemas a value matches all of, `anyOf` and
`oneOf` split it into alternatives. A position is declared when a schema the value surely matches declares it, so a key
one branch of a union declares and another leaves open is undeclared. Claiming (§3.5) walks the same shape
(`tainted_positions`): a position publish finds plain never holds a claim."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.handles import ClaimRef, escape
from dewpoint.engine.sensitive import SENSITIVE, keys_sensitive, patterns, resolve

_DEPTH = 32  # deeper than this, a schema is taken as tainted: recursive `$ref`s end here, on the safe side
_REFS = 64  # `$ref`s and combinators followed within one position, at most
_WAYS = 64  # more ways than this for a value to match a schema: taken as tainted, on the safe side


@dataclass(frozen=True)
class Shape:
    all: bool = False  # the whole value is tainted
    fields: tuple[tuple[str, "Shape"], ...] = ()  # declared keys, sorted
    other: "Shape | None" = None  # any key not in `fields`; None: clean
    items: "Shape | None" = None  # list elements; None: clean

    def field(self, key: str) -> "Shape":
        if self.all:
            return TAINTED
        for name, shape in self.fields:
            if name == key:
                return shape
        return self.other or CLEAN

    def element(self) -> "Shape":
        return TAINTED if self.all else self.items or CLEAN

    def at(self, path: Sequence[str | int]) -> "Shape":
        """The shape of the part at `path`."""
        shape = self
        for part in path:
            shape = shape.element() if isinstance(part, int) else shape.field(part)
        return shape

    @property
    def tainted(self) -> bool:
        """Whether any part is: what a read of the whole value is."""
        return (
            self.all
            or any(s.tainted for _, s in self.fields)
            or (self.other is not None and self.other.tainted)
            or (self.items is not None and self.items.tainted)
        )

    def to_json(self) -> Any:
        if self.all or not self.tainted:
            return self.all
        out: dict[str, Any] = {}
        if self.fields:
            out["fields"] = {name: s.to_json() for name, s in self.fields}
        if self.other is not None:
            out["other"] = self.other.to_json()
        if self.items is not None:
            out["items"] = self.items.to_json()
        return out

    @staticmethod
    def from_json(data: Any) -> "Shape":
        if isinstance(data, bool):
            return TAINTED if data else CLEAN
        fields = [(k, Shape.from_json(v)) for k, v in data.get("fields", {}).items()]
        other = Shape.from_json(data["other"]) if "other" in data else None
        items = Shape.from_json(data["items"]) if "items" in data else None
        return make(fields, other, items)


CLEAN = Shape()
TAINTED = Shape(all=True)


def make(fields: Sequence[tuple[str, Shape]] = (), other: "Shape | None" = None, items: "Shape | None" = None) -> Shape:
    """A shape in its one normal form, so equal taint compares equal: a clean rule is None, and a clean field is
    dropped unless other keys are tainted (there, it's what keeps that field clean). Only a source makes a shape
    TAINTED: one whose every key is tainted still leaves a scalar or a list in its place plain."""
    other = other if other is not None and other.tainted else None
    items = items if items is not None and items.tainted else None
    kept = tuple(sorted((n, f) for n, f in fields if f.tainted or other is not None))
    return Shape(fields=kept, other=other, items=items)


def _union(a: "Shape | None", b: "Shape | None") -> "Shape | None":
    if a is None:
        return b
    if b is None:
        return a
    return join(a, b)


def join(a: Shape, b: Shape) -> Shape:
    """What's tainted in either."""
    if a.all or b.all:
        return TAINTED
    names = sorted({n for n, _ in a.fields} | {n for n, _ in b.fields})
    return make([(n, join(a.field(n), b.field(n))) for n in names], _union(a.other, b.other), _union(a.items, b.items))


# --- from a schema ------------------------------------------------------------------------------------------------

Way = tuple[Mapping[str, Any], ...]  # schemas a value matches all at once, each by its own keywords


def _ways(schema: Any, root: Mapping[str, Any], depth: int) -> list[Way] | None:
    """The ways a value can match `schema`. None: too many to say (more than _WAYS, or nested past _REFS)."""
    if schema is False:
        return []  # nothing matches
    if not isinstance(schema, Mapping):
        return [()]  # `true` (or nothing usable): no constraint
    if depth > _REFS:
        return None
    together: list[Any] = []
    ref = schema.get("$ref")
    if isinstance(ref, str):
        together.append(resolve(root, ref))
    subs = schema.get("allOf")
    together += subs if isinstance(subs, list) else []
    ways = _all_of(together, root, depth + 1)
    if ways is None:
        return None
    ways = [(schema, *w) for w in ways]
    for key in ("anyOf", "oneOf"):
        subs = schema.get(key)
        if not isinstance(subs, list) or not subs:
            continue
        either: list[Way] = []
        for sub in subs:
            found = _ways(sub, root, depth + 1)
            if found is None:
                return None
            either += found
        ways = [w + e for w in ways for e in either]
        if len(ways) > _WAYS:
            return None
    return ways


def _all_of(schemas: Sequence[Any], root: Mapping[str, Any], depth: int) -> list[Way] | None:
    """The ways a value can match every schema in `schemas`."""
    ways: list[Way] = [()]
    for schema in schemas:
        found = _ways(schema, root, depth)
        if found is None:
            return None
        ways = [w + f for w in ways for f in found]
        if len(ways) > _WAYS:
            return None
    return ways


def _may_be(schema: Mapping[str, Any], kind: str) -> bool:
    t = schema.get("type")
    if t is None:
        return not any(k in schema for k in ("const", "enum"))
    return kind in (t if isinstance(t, list) else [t])


def _closed(schema: Mapping[str, Any]) -> bool:
    """No key beyond its `properties` can be present: a key a pattern admits is undeclared (spec §3.5)."""
    return schema.get("additionalProperties") is False and not patterns(schema)


def _field(way: Way, key: str) -> list[list[Any]]:
    """What may govern `key`'s value in `way`, as alternatives a value matches one of: the schemas that surely apply
    (each declaration, and `additionalProperties` where no pattern could apply instead), alone or with one that may
    (a pattern, which no regex checks here). More schemas at once only declare more, so each alternative adds just
    what its extra schema marks."""
    sure: list[Any] = []
    maybe: list[Any] = []
    for schema in way:
        props = schema.get("properties")
        found = patterns(schema)
        maybe += found
        if isinstance(props, Mapping) and key in props:
            sure.append(props[key])
            continue
        extra = schema.get("additionalProperties", True)
        if extra is False and not found:
            return []  # this schema admits no such key: the value can't hold it this way
        if extra is not False:
            (maybe if found else sure).append(extra)
    return [sure, *([*sure, m] for m in maybe)]


def _items(way: Way, root: Mapping[str, Any], depth: int) -> Shape:
    """The taint of a list's elements, every position joined: a position takes what governs it (a tuple's
    `prefixItems`, `items` after it), and one nothing declares is tainted."""
    longest = max((len(s["prefixItems"]) for s in way if isinstance(s.get("prefixItems"), list)), default=0)
    out = CLEAN
    for index in range(longest + 1):  # the last stands for every position after the tuples
        governing: list[Any] = []
        possible = True
        for schema in way:
            prefix = schema.get("prefixItems")
            prefix = prefix if isinstance(prefix, list) else []
            items = schema.get("items")
            if index < len(prefix):
                governing.append(prefix[index])
            elif items is False:
                possible = False  # no element here
            elif isinstance(items, (Mapping, bool)):
                governing.append(items)
        if possible:
            out = join(out, _shape([governing], root, depth + 1) if governing else TAINTED)
    return out


def _way(way: Way, root: Mapping[str, Any], depth: int) -> Shape:
    if any(s.get(SENSITIVE) is True for s in way) or keys_sensitive(list(way), root):
        return TAINTED
    fields: list[tuple[str, Shape]] = []
    other: Shape | None = None
    items: Shape | None = None
    if all(_may_be(s, "object") for s in way):
        names = sorted({k for s in way if isinstance(s.get("properties"), Mapping) for k in s["properties"]})
        fields = [(k, _shape(_field(way, k), root, depth + 1)) for k in names]
        if not any(_closed(s) for s in way):
            other = TAINTED  # keys no schema declares may exist
    if all(_may_be(s, "array") for s in way):
        items = _items(way, root, depth)
    return make(fields, other, items)


def _shape(alternatives: Sequence[Sequence[Any]], root: Mapping[str, Any], depth: int) -> Shape:
    """The taint of a value that matches all the schemas of one of `alternatives`."""
    if depth > _DEPTH:
        return TAINTED
    out = CLEAN
    for schemas in alternatives:
        ways = _all_of(schemas, root, 0)
        if ways is None:
            return TAINTED
        for way in ways:
            out = join(out, _way(way, root, depth))
            if out.all:
                return out
    return out


def from_schema(schema: Mapping[str, Any] | None, root: Mapping[str, Any] | None = None) -> Shape:
    """The taint of a value `schema` describes (§4.1). No schema at all: tainted, since nothing is declared."""
    if schema is None:
        return TAINTED
    return _shape([[schema]], root if root is not None else schema, 0)


# --- claiming -----------------------------------------------------------------------------------------------------


def _walk(value: Any, shape: Shape, pointer: str, out: list[str]) -> None:
    if ClaimRef.of(value) is not None:
        return  # claimed already
    if shape.all:
        out.append(pointer)
    elif shape.tainted and isinstance(value, dict):
        for key, child in value.items():
            _walk(child, shape.field(key), pointer + "/" + escape(key), out)
    elif shape.tainted and isinstance(value, list):
        for index, child in enumerate(value):
            _walk(child, shape.element(), pointer + "/" + str(index), out)


def tainted_positions(value: Any, shape: Shape) -> list[str]:
    """The pointers of `value`'s largest wholly tainted parts, in document order: what claiming takes with taint
    (§3.5). It walks the shape publish reads, so a position publish finds plain never holds a claim. A handle is
    claimed already: nothing under it is listed, so what a split left must list nothing (§3.6)."""
    out: list[str] = []
    _walk(value, shape, "", out)
    return out
