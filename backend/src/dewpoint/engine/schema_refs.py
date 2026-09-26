# SPDX-License-Identifier: Apache-2.0
"""Dewpoint supports only local `$ref`s (`#/$defs/<name>`) that resolve, and no reference chain that recurses without
descending into the data. Anything else would make validation depend on base-URI rules, network fetches or unbounded
recursion, so it is reported as a problem instead of raising during validation."""

import re
from collections.abc import Iterator, Mapping
from typing import Any

PREFIX = "#/$defs/"
# JSON Pointer escapes (~0 ~1) and percent-encoding would make validators resolve a different name than we look up.
DEF_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
UNSUPPORTED = ("$id", "$anchor", "$dynamicRef", "$dynamicAnchor", "$recursiveRef", "$recursiveAnchor")
_SAME_INSTANCE_LISTS = ("allOf", "anyOf", "oneOf")
_SAME_INSTANCE_ONE = ("not", "if", "then", "else")

# Schema positions (JSON Schema 2020-12): the only keywords whose values are schemas. Everything else is data or a
# non-schema keyword (`default`, `const`, `enum`, `examples`, `required`, `dependentRequired`, vendor `x-*` keys, ...)
# and must be treated verbatim: never searched for `$ref`, never stripped of annotation-like names.
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


def subschemas(schema: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    """(relative JSON pointer, subschema) for every schema-valued keyword of `schema`, and nothing else."""
    for key, value in schema.items():
        if key in SCHEMA_ONE:
            yield f"/{key}", value
        elif key in SCHEMA_LIST and isinstance(value, list):
            for index, sub in enumerate(value):
                yield f"/{key}/{index}", sub
        elif key in SCHEMA_MAP and isinstance(value, Mapping):
            for name, sub in value.items():
                yield f"/{key}/{name}", sub


def _same_instance_refs(node: Any) -> set[str]:
    """Definitions applied to the *same* instance as `node`, so recursion through them consumes no data."""
    if not isinstance(node, Mapping):
        return set()
    out: set[str] = set()
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith(PREFIX):
        out.add(ref[len(PREFIX) :])
    for key in _SAME_INSTANCE_LISTS:
        value = node.get(key)
        if isinstance(value, list):
            for sub in value:
                out |= _same_instance_refs(sub)
    for key in _SAME_INSTANCE_ONE:
        out |= _same_instance_refs(node.get(key))
    dependent = node.get("dependentSchemas")
    if isinstance(dependent, Mapping):
        for sub in dependent.values():
            out |= _same_instance_refs(sub)
    return out


def ref_problems(schema: Any) -> list[str]:
    if not isinstance(schema, Mapping):
        return []
    defs = schema.get("$defs", {})
    if not isinstance(defs, Mapping):
        return ["`$defs` must be an object"]
    problems: list[str] = [
        f"/$defs/{name}: `$defs` names may use only letters, digits, '_', '.' and '-'"
        for name in defs
        if not isinstance(name, str) or not DEF_NAME.match(name)
    ]
    if problems:
        return problems

    def walk(node: Any, path: str) -> None:
        if not isinstance(node, Mapping):
            return  # a boolean schema
        for key in UNSUPPORTED:
            if key in node:
                problems.append(f"{path or '/'}: `{key}` isn't supported")
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith(PREFIX) or ref[len(PREFIX) :] not in defs:
                problems.append(f"{path or '/'}: `$ref` must name an entry of this schema's `$defs` (#/$defs/<name>)")
        for suffix, sub in subschemas(node):  # schema positions only: data such as `default` is never inspected
            walk(sub, path + suffix)

    walk(schema, "")
    if problems:
        return problems
    edges = {name: _same_instance_refs(sub) for name, sub in defs.items()}
    state: dict[str, int] = {}  # 1 = on the current path, 2 = finished

    def cyclic(name: str) -> bool:
        if state.get(name) == 1:
            return True
        if state.get(name) == 2:
            return False
        state[name] = 1
        found = any(cyclic(target) for target in sorted(edges.get(name, ())))
        state[name] = 2
        return found

    for name in sorted(defs):
        if cyclic(name):
            return [f"/$defs/{name}: `$ref` cycle that never descends into the data"]
    return []
