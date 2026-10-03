# SPDX-License-Identifier: Apache-2.0
"""Previews for `run_steps` (spec §8). The projection is tenant-readable, so:
- a field its schema marks `x-sensitive` becomes "[redacted]" wherever the schema puts it: behind local `$ref`s, in
  any branch of `anyOf`, `oneOf` or `allOf` (sensitive in one branch, redacted in all), under any `patternProperties`
  schema of its object (declared keys included: JSON Schema applies both) and at a tuple's position (`prefixItems`);
  a map whose keys are sensitive (`propertyNames`) is redacted whole;
- a sensitive value never reaches the workflow (engine 2b spec §3.6): a handle stands where it was, and the
  project activity masks every row against the run tree's secret index (§3.7) before writing it;
- a preview larger than 8 KiB of canonical JSON becomes "[truncated]";
- every row the workflow queues holds what storage will write (`storable`, `sanitize`): the workflow sizes each
  projection by the rows it sends, and a character strict UTF-8 can't encode would fail that in workflow code.

It runs in the workflow."""

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from dewpoint.engine.canonical import canonical_json
from dewpoint.engine.sensitive import (
    SENSITIVE,
    children,
    elements,
    expand,
    keys_sensitive,
    map_values,
    patterns,
)

PREVIEW_BYTES = 8 * 1024
MESSAGE_LIMIT = 500  # characters of a stored code or message
REDACTED, TRUNCATED = "[redacted]", "[truncated]"

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")  # Postgres takes no NUL, and a lone surrogate isn't UTF-8


def _walk(value: Any, schemas: list[Any], root: Mapping[str, Any]) -> Any:
    """The value with its sensitive parts redacted."""
    branches = [b for s in schemas for b in expand(s, root)]
    if any(b.get(SENSITIVE) is True for b in branches):
        return REDACTED
    if isinstance(value, dict):
        if keys_sensitive(branches, root):  # the keys are the secret: the whole map goes
            return REDACTED
        return {k: _walk(v, children(branches, k), root) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, elements(branches, i), root) for i, v in enumerate(value)]
    return value


def location(loc: Sequence[str | int], schema: Mapping[str, Any]) -> str:
    """A validation error's location, as far as the schema declares it. Walking the schema along the location, a part
    is kept only where the schema puts it: a property name at an object, an index at an array. Anything else came
    from the data (a map key, numeric or not; an unknown key) or from the validator (a union's tag), and shows as `*`.
    After a `*`, the walk continues into the map's values."""
    candidates: list[Any] = [schema]
    parts: list[str] = []
    for part in loc:
        branches = [b for c in candidates for b in expand(c, schema)]
        found: list[Any] = []
        if isinstance(part, str):
            found = [
                c
                for b in branches
                if isinstance(b.get("properties"), Mapping) and part in b["properties"]
                for c in (b["properties"][part], *patterns(b))
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
            candidates = map_values(branches)
    return ".".join(parts) or "(root)"


def sanitize(message: str | None) -> str | None:
    """A code or message as storage writes it (`core.runs.service.sanitize`; a test holds the two equal): no control
    characters, no lone surrogates, at most MESSAGE_LIMIT characters."""
    if message is None:
        return None
    clean = _UNSTORABLE.sub("\ufffd", _CONTROL.sub(" ", message))
    return clean if len(clean) <= MESSAGE_LIMIT else clean[: MESSAGE_LIMIT - 1] + "…"


def storable(value: Any) -> Any:
    """A value as storage writes it to jsonb (`core.runs.service.storable`; a test holds the two equal): NUL and lone
    surrogates, in strings and keys, become U+FFFD, and a number JSON can't hold (NaN, infinity) its name."""
    if isinstance(value, str):
        return _UNSTORABLE.sub("\ufffd", value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {storable(k): storable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [storable(v) for v in value]
    return value


def preview(value: Any, schema: Mapping[str, Any] | None = None) -> Any:
    shown = _walk(value, [schema] if schema else [], schema or {})
    try:
        size = len(canonical_json(shown))
    except (TypeError, ValueError):
        return TRUNCATED
    return TRUNCATED if size > PREVIEW_BYTES else shown


__all__ = [
    "MESSAGE_LIMIT",
    "PREVIEW_BYTES",
    "REDACTED",
    "TRUNCATED",
    "location",
    "preview",
    "sanitize",
    "storable",
]
