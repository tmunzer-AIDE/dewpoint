# SPDX-License-Identifier: Apache-2.0
"""Taint (engine 2b spec §4.1): which parts of a value are tainted, decided at publish, per path, never per value.

A `Shape` says it of a value: all of it, none of it, or part by part (fields by name, with a rule for other keys, and
one for list elements). Shapes come from schemas where data enters a run, and travel with the values the validator
resolves: references, transforms, loops' collected items, filters, sub-flows' outputs. From a schema, a position marked
`x-sensitive` is tainted, a map whose keys are marked is tainted whole, and so is any position the schema doesn't
declare: unknown counts as sensitive."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.sensitive import SENSITIVE, children, elements, expand, keys_sensitive

_DEPTH = 32  # deeper than this, a schema is taken as tainted: recursive `$ref`s end here, on the safe side


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
    dropped unless other keys are tainted (there, it's what keeps that field clean)."""
    other = other if other is not None and other.tainted else None
    items = items if items is not None and items.tainted else None
    kept = tuple(sorted((n, f) for n, f in fields if f.tainted or other is not None))
    if other is not None and other.all and all(f.all for _, f in kept):
        return TAINTED
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


def _types(branches: list[Mapping[str, Any]]) -> set[str] | None:
    """The JSON types the branches allow between them; None: any (some branch doesn't say)."""
    out: set[str] = set()
    for b in branches:
        t = b.get("type")
        if t is None:
            if not any(k in b for k in ("const", "enum", "anyOf", "oneOf", "allOf", "$ref")):
                return None
            continue
        out |= set(t) if isinstance(t, list) else {t}
    return out or None


def _may_be(branch: Mapping[str, Any], kind: str) -> bool:
    t = branch.get("type")
    if t is None:
        return not any(k in branch for k in ("const", "enum"))
    return kind in (t if isinstance(t, list) else [t])


def _shape(schemas: list[Any], root: Mapping[str, Any], depth: int) -> Shape:
    if depth > _DEPTH:
        return TAINTED
    branches = [b for s in schemas for b in expand(s, root)]
    if not branches or any(b.get(SENSITIVE) is True for b in branches) or keys_sensitive(branches, root):
        return TAINTED
    types = _types(branches)
    fields: list[tuple[str, Shape]] = []
    other: Shape | None = None
    items: Shape | None = None
    if types is None or "object" in types:
        declared = sorted({k for b in branches if isinstance(b.get("properties"), Mapping) for k in b["properties"]})
        fields = [(k, _shape(children(branches, k), root, depth + 1)) for k in declared]
        if not all(b.get("additionalProperties") is False for b in branches if _may_be(b, "object")):
            other = TAINTED  # keys the schema doesn't declare may exist
    if types is None or "array" in types:
        declares = any(isinstance(b.get("items"), Mapping) or isinstance(b.get("prefixItems"), list) for b in branches)
        if not declares:
            items = TAINTED
        else:
            prefix = max((len(b["prefixItems"]) for b in branches if isinstance(b.get("prefixItems"), list)), default=0)
            for index in range(prefix + 1):
                items = _union(items, _shape(elements(branches, index), root, depth + 1))
    return make(fields, other, items)


def from_schema(schema: Mapping[str, Any] | None, root: Mapping[str, Any] | None = None) -> Shape:
    """The taint of a value `schema` describes (§4.1). No schema at all: tainted, since nothing is declared."""
    if schema is None:
        return TAINTED
    return _shape([schema], root if root is not None else schema, 0)
