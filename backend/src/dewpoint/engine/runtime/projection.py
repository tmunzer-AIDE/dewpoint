# SPDX-License-Identifier: Apache-2.0
"""Previews for `run_steps` (spec §8). The projection is tenant-readable, so:
- a field its schema marks `x-sensitive` becomes "[redacted]" wherever the schema puts it: behind local `$ref`s, and in
  any branch of `anyOf`, `oneOf` or `allOf` (sensitive in one branch, redacted in all);
- a value the run learned is sensitive (MIN_SECRET characters or more) is masked wherever it reappears, in strings and
  keys: copied by a transform, embedded by a template, echoed by an error message;
- a preview larger than 8 KiB of canonical JSON becomes "[truncated]".

It runs in the workflow. `remember` keeps the learned values in one sorted order, so every replay masks the same way.
Masking catches copies, not transformations: a secret that CEL encodes or slices is no longer the same text."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from dewpoint.engine.canonical import canonical_json

PREVIEW_BYTES = 8 * 1024
REDACTED, TRUNCATED = "[redacted]", "[truncated]"
SENSITIVE = "x-sensitive"
MIN_SECRET = 4  # shorter values would mask ordinary text ("1", "yes") everywhere
_MAX_DEPTH = 64  # a schema that refers to itself ends here

Secrets = tuple[str, ...]


def _resolve(root: Mapping[str, Any], ref: str) -> Any:
    """A local JSON pointer (`#/$defs/Name`); anything else resolves to nothing (schemas are local-only, spec §4.1)."""
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        node = node.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(node, Mapping) else None
    return node


def _branches(schema: Any, root: Mapping[str, Any], depth: int = 0) -> list[Mapping[str, Any]]:
    """`schema` and everything it stands for: its `$ref` followed, its `anyOf`/`oneOf`/`allOf` branches expanded."""
    if not isinstance(schema, Mapping) or depth > _MAX_DEPTH:
        return []
    out: list[Mapping[str, Any]] = [schema]
    ref = schema.get("$ref")
    if isinstance(ref, str):
        out += _branches(_resolve(root, ref), root, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        subs = schema.get(key)
        for sub in subs if isinstance(subs, list) else ():
            out += _branches(sub, root, depth + 1)
    return out


def _children(branches: list[Mapping[str, Any]], key: str) -> list[Any]:
    out: list[Any] = []
    for b in branches:
        props = b.get("properties")
        if isinstance(props, Mapping) and key in props:
            out.append(props[key])
        elif isinstance(b.get("additionalProperties"), Mapping):
            out.append(b["additionalProperties"])
    return out


def _walk(value: Any, schemas: list[Any], root: Mapping[str, Any], found: list[Any] | None) -> Any:
    """The value with its sensitive parts redacted; with `found`, also collects what was redacted."""
    branches = [b for s in schemas for b in _branches(s, root)]
    if any(b.get(SENSITIVE) is True for b in branches):
        if found is not None:
            found.append(value)
        return REDACTED
    if isinstance(value, dict):
        return {k: _walk(v, _children(branches, k), root, found) for k, v in value.items()}
    if isinstance(value, list):
        items = [b["items"] for b in branches if isinstance(b.get("items"), Mapping)]
        return [_walk(v, items, root, found) for v in value]
    return value


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def sensitive_values(value: Any, schema: Mapping[str, Any] | None) -> list[str]:
    """Every string at a position the schema marks sensitive (a whole sensitive object's strings included)."""
    if not schema:
        return []
    found: list[Any] = []
    _walk(value, [schema], schema, found)
    return [s for v in found for s in _strings(v)]


def remember(secrets: Secrets, values: Iterable[str]) -> Secrets:
    """`secrets` with `values` added: longest first, so a longer secret is masked whole before a shorter one inside
    it. The same tuple when nothing is new."""
    fresh = {v for v in values if len(v) >= MIN_SECRET} - set(secrets)
    if not fresh:
        return secrets
    return tuple(sorted({*secrets, *fresh}, key=lambda s: (-len(s), s)))


def mask(value: Any, secrets: Secrets) -> Any:
    """`value` with every learned secret replaced by "[redacted]", in strings and keys, at any depth."""
    if not secrets:
        return value
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        return {mask(k, secrets): mask(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v, secrets) for v in value]
    return value


def location(loc: Sequence[str | int], schema: Mapping[str, Any]) -> str:
    """A validation error's location, as far as the schema declares it. Walking the schema along the location, a part
    is kept only where the schema puts it: a property name at an object, an index at an array. Anything else came
    from the data (a map key, numeric or not; an unknown key) or from the validator (a union's tag), and shows as `*`.
    After a `*`, the walk continues into the map's values."""
    candidates: list[Any] = [schema]
    parts: list[str] = []
    for part in loc:
        branches = [b for c in candidates for b in _branches(c, schema)]
        found: list[Any] = []
        if isinstance(part, str):
            found = [
                b["properties"][part]
                for b in branches
                if isinstance(b.get("properties"), Mapping) and part in b["properties"]
            ]
        elif isinstance(part, int):
            for b in branches:
                prefix = b.get("prefixItems")
                if isinstance(prefix, list) and 0 <= part < len(prefix):
                    found.append(prefix[part])
                elif isinstance(b.get("items"), Mapping):
                    found.append(b["items"])
        if found:
            parts.append(str(part))
            candidates = found
        else:
            parts.append("*")
            candidates = [
                b["additionalProperties"] for b in branches if isinstance(b.get("additionalProperties"), Mapping)
            ]
    return ".".join(parts) or "(root)"


def preview(value: Any, schema: Mapping[str, Any] | None = None, secrets: Secrets = ()) -> Any:
    shown = mask(_walk(value, [schema] if schema else [], schema or {}, None), secrets)
    try:
        size = len(canonical_json(shown))
    except (TypeError, ValueError):
        return TRUNCATED
    return TRUNCATED if size > PREVIEW_BYTES else shown


__all__ = [
    "MIN_SECRET",
    "PREVIEW_BYTES",
    "REDACTED",
    "TRUNCATED",
    "Secrets",
    "location",
    "mask",
    "preview",
    "remember",
    "sensitive_values",
]
