# SPDX-License-Identifier: Apache-2.0
"""What a simulated Mist step answers (plugins-3 D13, as the owner ruled at the 3b-1 checkpoint): a value built from the
schema, every declared property filled to a bounded depth (only the required ones past it) and within a size budget,
with the OAS example's values laid over where they fit. The OAS's examples are incomplete and may be outdated, so the
schema gives the shape and the example only values: each part of the example is checked, and where it doesn't fit,
the schema-built part stays.

Every fixture returned is one the schema accepts, within the size budget: a schema-built value that isn't (an `allOf`
whose merged parts break one of them, a default too large to shrink) gives way to a shallower one, then to one without
defaults; when none is, the operation has no fixture (`FixtureUnavailable`) and isn't simulated.

A fixture fills optional properties a real answer may lack. Publish makes every reference to an optional field carry a
default, which prevents a missing-reference error; but a simulation then takes only the "present" branch, so a
failure on the absent (default) branch goes untested."""

import copy
import json
from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator

DEPTH = 6  # nesting levels whose every declared property is filled; past them, only the required ones
BUDGET = 65_536  # a fixture's JSON, at most: what a step keeps inline (the engine's INLINE_LIMIT); shallower past it
MAX_HOPS = 64  # `$ref`s followed on one path: a schema requiring itself ends there
MAX_REPAIRS = 512  # parts of an example put back to the schema's, at most, before the schema's value is taken whole
_ZERO: dict[str, Any] = {"string": "", "integer": 0, "number": 0, "boolean": False, "null": None}


class FixtureUnavailable(ValueError):  # noqa: N818 - read as "no fixture": the operation isn't simulated
    """No value within the budget satisfies the schema."""


def built(schema: Mapping[str, Any], *, depth: int = DEPTH, defaults: bool = True) -> Any:
    """A value `schema` describes, every declared property filled to `depth` levels: the default where one is given
    (with `defaults`), an array of one element, a union's first branch, else the type's empty value. Not checked:
    `fixture` checks what it returns."""
    return _built(schema, schema, 0, 0, depth, defaults)


def _built(root: Mapping[str, Any], node: Any, level: int, hops: int, depth: int, defaults: bool) -> Any:
    if not isinstance(node, Mapping) or hops > MAX_HOPS:
        return None
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        return _built(root, root.get("$defs", {}).get(ref[len("#/$defs/") :]), level, hops + 1, depth, defaults)
    for key in ("anyOf", "oneOf"):
        if isinstance(node.get(key), list) and node[key]:
            return _built(root, node[key][0], level, hops + 1, depth, defaults)
    if isinstance(node.get("allOf"), list) and node["allOf"]:
        parts = [_built(root, sub, level, hops + 1, depth, defaults) for sub in node["allOf"]]
        objects = [p for p in parts if isinstance(p, dict)]
        return {k: v for p in objects for k, v in p.items()} if objects else parts[0]
    if defaults and "default" in node:
        return copy.deepcopy(node["default"])
    kind = node.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    if kind == "object" or (kind is None and "properties" in node):
        props = node.get("properties", {})
        names = list(props) if level < depth else [n for n in node.get("required", ()) if isinstance(n, str)]
        names += [n for n in node.get("required", ()) if isinstance(n, str) and n not in names]
        return {name: _built(root, props.get(name, {}), level + 1, hops, depth, defaults) for name in names}
    if kind == "array":
        items = node.get("items")
        fits = level < depth and isinstance(items, Mapping)
        return [_built(root, items, level + 1, hops, depth, defaults)] if fits else []
    return _ZERO.get(str(kind))


def overlaid(base: Any, example: Any) -> Any:
    """`example` laid over `base`: objects key by key (undeclared keys kept), each array element over the base's
    first, anything else the example's."""
    if isinstance(base, Mapping) and isinstance(example, Mapping):
        out = copy.deepcopy(dict(base))
        for key, value in example.items():
            out[key] = overlaid(base[key], value) if key in base else copy.deepcopy(value)
        return out
    if isinstance(base, list) and isinstance(example, list):
        return [overlaid(base[0], e) if base else copy.deepcopy(e) for e in example]
    return copy.deepcopy(example)


def _restored(candidate: Any, base: Any, path: list[Any]) -> Any:
    """`candidate` with the part at `path` put back to the base's (dropped where the base has none)."""
    if not path:
        return copy.deepcopy(base)
    key, rest = path[0], path[1:]
    if isinstance(candidate, dict):
        out = dict(candidate)
        if isinstance(base, Mapping) and key in base:
            out[key] = _restored(candidate.get(key), base[key], rest)
        else:
            out.pop(key, None)
        return out
    if isinstance(candidate, list) and isinstance(key, int) and 0 <= key < len(candidate):
        out_list = list(candidate)
        if isinstance(base, list) and base:
            out_list[key] = _restored(candidate[key], base[0], rest)
        else:
            del out_list[key]
        return out_list
    return copy.deepcopy(base)


def _fits(validator: Draft202012Validator, value: Any, budget: int) -> bool:
    return len(json.dumps(value)) <= budget and validator.is_valid(value)


def _base(validator: Draft202012Validator, schema: Mapping[str, Any], budget: int) -> Any:
    """The fullest schema-built value the schema accepts within `budget`: shallower, then without defaults."""
    for defaults in (True, False):
        for depth in range(DEPTH, -1, -1):
            value = built(schema, depth=depth, defaults=defaults)
            if _fits(validator, value, budget):
                return value
    raise FixtureUnavailable()


def fixture(schema: Mapping[str, Any], example: Any, *, budget: int = BUDGET) -> tuple[Any, str]:
    """The fixture `schema` and its example make, and where its values come from: `example` when any part of the
    example stayed, else `schema`. Whatever it returns, the schema accepts and the budget holds; when no such value
    exists, `FixtureUnavailable`."""
    validator = Draft202012Validator(schema)
    base = _base(validator, schema, budget)
    if example is None:
        return base, "schema"
    candidate = overlaid(base, example)
    for _ in range(MAX_REPAIRS):
        errors = list(validator.iter_errors(candidate))
        if not errors:
            if candidate == base or not _fits(validator, candidate, budget):
                return base, "schema"
            return candidate, "example"
        shallowest = min((list(e.absolute_path) for e in errors), key=len)
        candidate = _restored(candidate, base, shallowest)
    return base, "schema"
