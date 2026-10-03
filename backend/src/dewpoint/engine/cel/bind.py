# SPDX-License-Identifier: Apache-2.0
"""Binding for one evaluation (spec §5.3, §5.6): project each root to what the expression reads, check every value
against its declared type, and measure the result against the local caps. Pure and deterministic: the interpreter
calls it inside workflow code.

A handle (engine 2b spec §3.2) is bound as it is: kept whole by a projection, extended by a typed path that goes past
it, and never type-checked here, since its value is the claim's. An expression with a handle among its bindings runs
in `cel.evaluate`, which resolves it and checks the types then (§4.2)."""

import math
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.canonical import canonical_json
from dewpoint.engine.cel import caps
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.record import ExpressionRecord, Projection
from dewpoint.engine.handles import MARKER, ClaimRef, contains_marker


@dataclass(frozen=True)
class ScopeView:
    """What one evaluation site sees, as plain JSON. The interpreter (2a-3) builds it from workflow state.

    `steps` holds every step visible from this scope: `{"output": …}` once it succeeded, `{"error": {…}}` once it
    failed with a handled error, `{}` before either. So `has(steps.a.output)` is the guard for a step that may not
    have run, and a bare `steps.a` never fails."""

    trigger: Mapping[str, Any]
    steps: Mapping[str, Mapping[str, Any]]
    vars: Mapping[str, Any]
    loops: Mapping[str, Mapping[str, Any]]  # enclosing loops: key -> {"item": …, "index": n}
    run: Mapping[str, str]  # id, started_at, now: RFC 3339 UTC strings
    item: Any = None  # the innermost loop's item, or the filter item in a predicate
    index: int | None = None

    def roots(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "trigger": self.trigger,
            "steps": self.steps,
            "vars": self.vars,
            "loops": self.loops,
            "run": self.run,
        }
        if self.index is not None:
            out.update(item=self.item, index=self.index)
        return out


class BindingError(Exception):
    """The values don't match what publish proved about them: the evaluation fails with `type_mismatch`."""


@dataclass
class _Node:
    whole: bool = False
    presence: bool = False
    children: dict[str, "_Node"] | None = None

    def child(self, key: str) -> "_Node":
        if self.children is None:
            self.children = {}
        return self.children.setdefault(key, _Node())


def project(value: Any, projections: list[Projection]) -> Any:
    """The part of a root value the expression can observe: a map keeps only keys on some chain, a chain's end
    keeps its whole value, and a presence test keeps only the key (with a null value). Anything that isn't a map is
    kept whole, so selecting into it fails exactly as it would on the full value."""
    trie = _Node()
    for p in projections:
        node = trie
        for key in p.path[1:]:
            node = node.child(key)
        if p.presence and len(p.path) > 1:
            node.presence = True
        else:
            node.whole = True
    return _prune(value, trie)


def _prune(value: Any, node: _Node) -> Any:
    if node.whole or not isinstance(value, dict) or ClaimRef.of(value) is not None:
        return value
    out: dict[str, Any] = {}
    for key, child in (node.children or {}).items():
        if key in value:
            only_presence = child.presence and not child.whole and not child.children
            out[key] = None if only_presence else _prune(value[key], child)
    return out


def check_json(name: str, value: Any) -> None:
    """Plain JSON only: string keys, finite numbers, and integers the runtime can hold as int64."""
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            if not all(isinstance(k, str) for k in v):
                raise BindingError(f"`{name}` has a map key that isn't text")
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)
        elif isinstance(v, bool) or v is None or isinstance(v, str):
            continue
        elif isinstance(v, int):
            if not T.INT64_MIN <= v <= T.INT64_MAX:
                raise BindingError(f"`{name}` holds a number outside the 64-bit integer range")
        elif isinstance(v, float):
            if not math.isfinite(v):
                raise BindingError(f"`{name}` holds a number that isn't finite")
        else:
            raise BindingError(f"`{name}` holds a {type(v).__name__}, which isn't JSON")


def _at(roots: Mapping[str, Any], name: str) -> Any:
    value: Any = roots
    keys = name.split(".")
    for i, key in enumerate(keys):
        handle = ClaimRef.of(value)
        if handle is not None:
            return handle.extend(*keys[i:]).to_json()
        if not isinstance(value, dict) or key not in value:
            raise BindingError(f"`{name}` is missing")
        value = value[key]
    return value


def _bound(record: ExpressionRecord, roots: Mapping[str, Any], names: Iterable[str]) -> dict[str, Any]:
    by_root: dict[str, list[Projection]] = {}
    for p in record.projections:
        by_root.setdefault(p.path[0], []).append(p)
    out: dict[str, Any] = {}
    for name in names:
        if "." in name:
            value = _at(roots, name)
        elif name in roots:
            value = project(roots[name], by_root[name]) if name in by_root else roots[name]
        else:
            raise BindingError(f"`{name}` isn't available here")
        signature = record.declarations.get(name, T.DYN)
        # a handle conforms to no declared type; the marker is looked for only then: a walk of the whole value, in the
        # workflow task, at every evaluation (CI's gate 7b)
        if not T.conforms(signature, value) and not contains_marker(value):
            raise BindingError(f"`{name}` doesn't match its declared type {signature}")
        check_json(name, value)
        out[name] = value
    return out


def _root(name: str) -> str:
    return name.split(".", 1)[0]


def bind(record: ExpressionRecord, view: ScopeView, *, skip: Collection[str] = ()) -> dict[str, Any]:
    """The expression's bindings for one view. `skip`: roots left out, bound later (a filter's `item` and `index`,
    in the activity that evaluates a filter over claims, engine 2b spec §4.4)."""
    return _bound(record, view.roots(), [n for n in record.idents if _root(n) not in skip])


def bind_item(record: ExpressionRecord, base: Mapping[str, Any], item: Any, index: int) -> dict[str, Any]:
    """`base`, every binding but the item's, with one item's and its index's, bound as `bind` binds them."""
    names = [n for n in record.idents if _root(n) in ("item", "index")]
    return {**base, **_bound(record, {"item": item, "index": index}, names)}


@dataclass(frozen=True)
class Measure:
    total_json: int
    largest_json: int
    longest_list: int
    largest_map: int
    longest_string: int
    nodes: int  # every value bound, containers included: what binding them costs grows with this (spec §5.6)
    handles: bool = False  # a handle, or the marker, anywhere in them: they're never evaluated here (2b spec §4.2)

    @property
    def within_caps(self) -> bool:
        return (
            self.total_json <= caps.TOTAL_JSON
            and self.largest_json <= caps.VALUE_JSON
            and self.longest_list <= caps.LIST_LENGTH
            and self.largest_map <= caps.MAP_ENTRIES
            and self.longest_string <= caps.STRING_BYTES
        )


def measure(bindings: Mapping[str, Any]) -> Measure:
    sizes = [len(canonical_json(v)) for v in bindings.values()]
    lists = maps = strings = nodes = 0
    handles = False
    stack = list(bindings.values())
    while stack:
        v = stack.pop()
        nodes += 1
        if isinstance(v, dict):
            maps = max(maps, len(v))
            handles = handles or MARKER in v
            stack.extend(v.values())
        elif isinstance(v, list):
            lists = max(lists, len(v))
            stack.extend(v)
        elif isinstance(v, str):
            strings = max(strings, len(v.encode()))
    return Measure(sum(sizes), max(sizes, default=0), lists, maps, strings, nodes, handles)
