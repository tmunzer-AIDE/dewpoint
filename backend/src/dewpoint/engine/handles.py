# SPDX-License-Identifier: Apache-2.0
"""Handles (engine 2b spec §3.2): `ClaimRef(id, pointer)`, a claim and a JSON pointer into its value, serialized under
a reserved marker key.

A handle carries no taint and asserts nothing: authority comes only from the stored row, checked where the claim is
resolved, in an activity (§3.3). It's bounded: its pointer is at most POINTER_MAX bytes, encoded, so its encoding is at
most HANDLE_MAX; a reference that would make a longer one derives a new claim instead. Data from outside never crosses
into a run as a handle: admission and the activity boundary refuse a value that holds the marker anywhere."""

import json
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any

MARKER = "$claim"
CLAIM_UNAVAILABLE = "claim_unavailable"  # every refusal to read a claim (§3.3): as core.claims.service's
RESERVED = "A value holds the key `$claim`, which only Dewpoint writes: it marks a handle."
MISSING: Any = object()  # what a pointer that addresses nothing reads: a reference's default then applies
POINTER = "pointer"
POINTER_MAX = 256  # bytes, as JSON (spec §15: provisional)


def pointer_bytes(pointer: str) -> int:
    """A pointer's JSON bytes, as the SDK's converter writes a string."""
    return len(json.dumps(pointer))


def escape(token: str | int) -> str:
    """One reference token of a JSON pointer (RFC 6901)."""
    return str(token).replace("~", "~0").replace("/", "~1")


def tokens(pointer: str) -> list[str]:
    """A JSON pointer's reference tokens, unescaped."""
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer.split("/")[1:]] if pointer else []


def _claim_id(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


@dataclass(frozen=True)
class ClaimRef:
    id: str  # a claim's id: a UUID
    pointer: str = ""  # a JSON pointer into the claim's value; "" is the whole value

    def to_json(self) -> dict[str, str]:
        return {MARKER: self.id, POINTER: self.pointer} if self.pointer else {MARKER: self.id}

    @staticmethod
    def of(value: Any) -> "ClaimRef | None":
        """The handle `value` is, in its exact form, or None."""
        if not isinstance(value, dict) or not _claim_id(value.get(MARKER)):
            return None
        if set(value) == {MARKER}:
            return ClaimRef(value[MARKER])
        pointer = value.get(POINTER)
        if set(value) == {MARKER, POINTER} and isinstance(pointer, str) and pointer.startswith("/"):
            return ClaimRef(value[MARKER], pointer)
        return None

    def extend(self, *path: str | int) -> "ClaimRef":
        """A reference further into what this handle addresses: the workflow never reads the claim to follow it."""
        return ClaimRef(self.id, self.pointer + "".join("/" + escape(t) for t in path))

    def too_long(self) -> bool:
        """Past POINTER_MAX: the reference derives a new claim of what it addresses instead (§3.2)."""
        return pointer_bytes(self.pointer) > POINTER_MAX


# The largest handle: the marker, a claim id, and a pointer at POINTER_MAX.
HANDLE_MAX = len(
    json.dumps({MARKER: str(uuid.UUID(int=0)), POINTER: "/" + "x" * (POINTER_MAX - 3)}, separators=(",", ":"))
)


def _children(value: Any) -> Iterator[tuple[str | int, Any]]:
    if isinstance(value, dict):
        yield from value.items()
    elif isinstance(value, list):
        yield from enumerate(value)


def contains_marker(value: Any) -> bool:
    """Whether the marker key appears anywhere in `value`: in a handle, or in a forged or malformed one."""
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict) and MARKER in current:
            return True
        stack.extend(child for _, child in _children(current))
    return False


def handles_in(value: Any, pointer: str = "") -> Iterator[tuple[str, ClaimRef]]:
    """Every handle in `value`, with the pointer where it sits, outermost first; nothing inside a handle."""
    ref = ClaimRef.of(value)
    if ref is not None:
        yield pointer, ref
        return
    for key, child in _children(value):
        yield from handles_in(child, pointer + "/" + escape(key))


NESTING_MAX = 32  # claims nested deeper than this are refused: a claim holds handles only to claims made before it


class NestingError(Exception):
    """Claims nested deeper than NESTING_MAX: a bug, never a value's fault."""


@dataclass(frozen=True)
class StoredClaim:
    value: Any
    sensitive_pointers: tuple[str, ...]  # the tainted pointers inside the value; "" is all of it


@dataclass(frozen=True)
class Resolved:
    value: Any  # plain: every handle inside it resolved; MISSING when the pointer addresses nothing
    tainted: bool


type Fetch = Callable[[str], Awaitable[StoredClaim]]


def _step(value: Any, part: str) -> tuple[Any, bool]:
    """One reference token further into `value`: a key, or a list index without leading zeros."""
    if isinstance(value, dict):
        return (value[part], True) if part in value else (MISSING, False)
    if isinstance(value, list) and part.isdigit() and (part == "0" or not part.startswith("0")):
        index = int(part)
        return (value[index], True) if index < len(value) else (MISSING, False)
    return MISSING, False


def _overlaps(sensitive: tuple[str, ...], path: list[str]) -> bool:
    """Whether a part at `path` lies in a sensitive pointer's subtree or holds one."""
    for pointer in sensitive:
        mark = tokens(pointer)
        shorter = min(len(mark), len(path))
        if mark[:shorter] == path[:shorter]:
            return True
    return False


async def resolve(ref: ClaimRef, fetch: Fetch, depth: int = 0) -> Resolved:
    """What `ref` addresses, read through nested claims, with every handle inside it resolved (§3.3). Tainted when
    any part it read was: the part lies in or holds one of its claim's sensitive pointers, or a nested claim it read
    is tainted (§3.6). `fetch` reads a whole claim, and does the checks: the tenant, and the owner or a grant."""
    if depth > NESTING_MAX:
        raise NestingError("Claims nested too deep.")
    stored = await fetch(ref.id)
    value, path = stored.value, tokens(ref.pointer)
    for i, part in enumerate(path):
        nested = ClaimRef.of(value)
        if nested is not None:  # the pointer goes on inside a claim nested here
            inner = await resolve(nested.extend(*path[i:]), fetch, depth + 1)
            return Resolved(inner.value, inner.tainted or _overlaps(stored.sensitive_pointers, path[:i]))
        value, found = _step(value, part)
        if not found:
            return Resolved(MISSING, _overlaps(stored.sensitive_pointers, path[: i + 1]))
    plain, inner_tainted = await _plain(value, fetch, depth)
    return Resolved(plain, inner_tainted or _overlaps(stored.sensitive_pointers, path))


async def _plain(value: Any, fetch: Fetch, depth: int) -> tuple[Any, bool]:
    """`value` with every handle in it resolved, and whether any of them was tainted."""
    nested = ClaimRef.of(value)
    if nested is not None:
        inner = await resolve(nested, fetch, depth + 1)
        return inner.value, inner.tainted
    if isinstance(value, dict):
        out, tainted = {}, False
        for key, child in value.items():
            out[key], t = await _plain(child, fetch, depth)
            tainted = tainted or t
        return out, tainted
    if isinstance(value, list):
        items, tainted = [], False
        for child in value:
            item, t = await _plain(child, fetch, depth)
            items.append(item)
            tainted = tainted or t
        return items, tainted
    return value, False


def _held(sensitive: tuple[str, ...], path: list[str]) -> bool:
    """Whether a sensitive pointer holds the part at `path`: it is sensitive whole."""
    return any(path[: len(mark)] == mark for mark in (tokens(p) for p in sensitive) if len(mark) <= len(path))


def _rebased(sensitive: tuple[str, ...], path: list[str]) -> tuple[str, ...]:
    """The sensitive pointers of a claim, as they apply to its part at `path`."""
    if _held(sensitive, path):
        return ("",)
    marks = (tokens(p) for p in sensitive)
    return tuple(sorted("".join("/" + escape(t) for t in m[len(path) :]) for m in marks if m[: len(path)] == path))


async def part(ref: ClaimRef, fetch: Fetch, depth: int = 0) -> StoredClaim | None:
    """What `ref` addresses as it's stored: its nested handles kept, and its claim's sensitive pointers re-based onto
    it (all of it, when one holds it). None when the pointer addresses nothing. A derived claim copies it (§3.2)."""
    if depth > NESTING_MAX:
        raise NestingError("Claims nested too deep.")
    stored = await fetch(ref.id)
    value, path = stored.value, tokens(ref.pointer)
    for i, token in enumerate(path):
        nested = ClaimRef.of(value)
        if nested is not None:  # the pointer goes on inside a claim nested here
            inner = await part(nested.extend(*path[i:]), fetch, depth + 1)
            if inner is not None and _held(stored.sensitive_pointers, path[:i]):
                return StoredClaim(inner.value, ("",))
            return inner
        value, found = _step(value, token)
        if not found:
            return None
    return StoredClaim(value, _rebased(stored.sensitive_pointers, path))


async def resolve_value(value: Any, fetch: Fetch) -> Resolved:
    """`value` with every handle in it resolved, and whether any of them was tainted. A handle that addresses nothing
    drops its key from the map holding it, and is MISSING as a whole value."""
    plain, tainted = await _plain(value, fetch, 0)
    return Resolved(_present(plain), tainted)


def _present(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _present(v) for k, v in value.items() if v is not MISSING}
    if isinstance(value, list):
        return [_present(v) for v in value]
    return value
