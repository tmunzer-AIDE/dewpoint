# SPDX-License-Identifier: Apache-2.0
"""Where a JSON Schema puts sensitive values (`x-sensitive`), read without running anything on the data: behind local
`$ref`s, in any branch of `anyOf`, `oneOf` or `allOf` (sensitive in one branch, sensitive in all), under any
`patternProperties` schema of its object (no regex runs: over-marking, never a leak), at a tuple's position
(`prefixItems`); a map whose keys are sensitive (`propertyNames`) is sensitive whole.

The projection redacts with it (`engine.runtime.projection`). Claiming (engine 2b spec §3.5) goes further: a value at a
position the schema doesn't declare is sensitive too, since unknown counts as sensitive (`sensitive_positions`)."""

from collections.abc import Mapping
from typing import Any

from dewpoint.engine.handles import escape

SENSITIVE = "x-sensitive"
MIN_SECRET = 4  # a secret's characters, at least: shorter values would match ordinary text ("1", "yes") everywhere
_MAX_DEPTH = 64  # a schema that refers to itself ends here


def _resolve(root: Mapping[str, Any], ref: str) -> Any:
    """A local JSON pointer (`#/$defs/Name`); anything else resolves to nothing (schemas are local-only, spec §4.1)."""
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        node = node.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(node, Mapping) else None
    return node


def expand(schema: Any, root: Mapping[str, Any], depth: int = 0) -> list[Mapping[str, Any]]:
    """`schema` and everything it stands for: its `$ref` followed, its `anyOf`/`oneOf`/`allOf` branches expanded."""
    if not isinstance(schema, Mapping) or depth > _MAX_DEPTH:
        return []
    out: list[Mapping[str, Any]] = [schema]
    ref = schema.get("$ref")
    if isinstance(ref, str):
        out += expand(_resolve(root, ref), root, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        subs = schema.get(key)
        for sub in subs if isinstance(subs, list) else ():
            out += expand(sub, root, depth + 1)
    return out


def patterns(branch: Mapping[str, Any]) -> list[Any]:
    """Every `patternProperties` schema, matched or not: no regex runs on data in the workflow, so a sensitive
    pattern redacts every key's value in its object, declared keys included (over-redaction, never a leak)."""
    patterns = branch.get("patternProperties")
    return list(patterns.values()) if isinstance(patterns, Mapping) else []


def map_values(branches: list[Mapping[str, Any]]) -> list[Any]:
    """The schemas that may govern an undeclared key's value: `additionalProperties` and every pattern."""
    out: list[Any] = []
    for b in branches:
        if isinstance(b.get("additionalProperties"), Mapping):
            out.append(b["additionalProperties"])
        out.extend(patterns(b))
    return out


def children(branches: list[Mapping[str, Any]], key: str) -> list[Any]:
    """The schemas that may govern `key`'s value. JSON Schema applies a declared property and every matching pattern
    together; `additionalProperties` only to keys neither covers."""
    out: list[Any] = []
    for b in branches:
        props = b.get("properties")
        if isinstance(props, Mapping) and key in props:
            out += [props[key], *patterns(b)]
        else:
            out += map_values([b])
    return out


def elements(branches: list[Mapping[str, Any]], index: int) -> list[Any]:
    """The schemas that may govern a list's element `index`: its tuple position (`prefixItems`), and `items`."""
    out: list[Any] = [b["items"] for b in branches if isinstance(b.get("items"), Mapping)]
    for b in branches:
        prefix = b.get("prefixItems")
        if isinstance(prefix, list) and index < len(prefix):
            out.append(prefix[index])
    return out


def keys_sensitive(branches: list[Mapping[str, Any]], root: Mapping[str, Any]) -> bool:
    names = [b["propertyNames"] for b in branches if isinstance(b.get("propertyNames"), Mapping)]
    return any(n.get(SENSITIVE) is True for s in names for n in expand(s, root))


def _declares(branches: list[Mapping[str, Any]], key: str) -> bool:
    return any(isinstance(b.get("properties"), Mapping) and key in b["properties"] for b in branches)


def _declares_element(branches: list[Mapping[str, Any]], index: int) -> bool:
    for b in branches:
        prefix = b.get("prefixItems")
        if isinstance(prefix, list) and index < len(prefix):
            return True
        if isinstance(b.get("items"), Mapping):
            return True
    return False


def _positions(value: Any, schemas: list[Any], root: Mapping[str, Any], pointer: str, out: list[str]) -> None:
    branches = [b for s in schemas for b in expand(s, root)]
    if not branches or any(b.get(SENSITIVE) is True for b in branches):
        out.append(pointer)
        return
    if isinstance(value, dict):
        if keys_sensitive(branches, root):
            out.append(pointer)
            return
        for key, child in value.items():
            at = pointer + "/" + escape(key)
            if _declares(branches, key):
                _positions(child, children(branches, key), root, at, out)
            else:
                out.append(at)  # additionalProperties, a pattern, or nothing: not declared
    elif isinstance(value, list):
        for index, child in enumerate(value):
            at = pointer + "/" + str(index)
            if _declares_element(branches, index):
                _positions(child, elements(branches, index), root, at, out)
            else:
                out.append(at)


def sensitive_positions(value: Any, schema: Mapping[str, Any] | None) -> list[str]:
    """The pointers of `value`'s largest sensitive parts, in document order: at an `x-sensitive` position, or one the
    schema doesn't declare (an undeclared key, a list element no `items` or `prefixItems` covers), or under a map whose
    keys are sensitive. Without a schema, the whole value is ("")."""
    if schema is None:
        return [""]
    out: list[str] = []
    _positions(value, [schema], schema, "", out)
    return out


def empty(value: Any) -> bool:
    """A literal that can't hold a secret: null, or the empty string (an optional credential's usual default)."""
    return value is None or value == ""


def _marked(value: Any, schemas: list[Any], root: Mapping[str, Any], pointer: str, out: list[str]) -> None:
    if empty(value):
        return
    branches = [b for s in schemas for b in expand(s, root)]
    if any(b.get(SENSITIVE) is True for b in branches):
        out.append(pointer)
    elif isinstance(value, dict):
        if keys_sensitive(branches, root):
            out.append(pointer)
            return
        for key, child in value.items():
            _marked(child, children(branches, key), root, pointer + "/" + escape(key), out)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _marked(child, elements(branches, index), root, pointer + "/" + str(index), out)


def marked_positions(value: Any, schema: Mapping[str, Any], root: Mapping[str, Any] | None = None) -> list[str]:
    """The pointers of `value`'s parts, other than `empty` ones, that the schema marks sensitive (`x-sensitive`, or a
    map whose keys are), in document order. An undeclared key follows the schemas that govern it, and isn't sensitive
    for that alone: this is what a workflow author wrote, checked at publish (§3.8). `root` resolves `$ref`s (the
    schema by default)."""
    out: list[str] = []
    _marked(value, [schema], root if root is not None else schema, "", out)
    return out


def is_marked(schema: Mapping[str, Any], path: tuple[str | int, ...], root: Mapping[str, Any] | None = None) -> bool:
    """Whether the position at `path` lies at or under a part the schema marks sensitive."""
    resolve_in = root if root is not None else schema
    schemas: list[Any] = [schema]
    for depth in range(len(path) + 1):
        branches = [b for s in schemas for b in expand(s, resolve_in)]
        if any(b.get(SENSITIVE) is True for b in branches) or (
            depth < len(path) and keys_sensitive(branches, resolve_in)
        ):
            return True
        if depth == len(path):
            return False
        part = path[depth]
        schemas = elements(branches, part) if isinstance(part, int) else children(branches, part)
    return False
