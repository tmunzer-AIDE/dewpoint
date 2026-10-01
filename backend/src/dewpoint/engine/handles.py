# SPDX-License-Identifier: Apache-2.0
"""Handles (engine 2b spec §3.2): `ClaimRef(id, pointer)`, a claim and a JSON pointer into its value, serialized under
a reserved marker key.

A handle carries no taint and asserts nothing: authority comes only from the stored row, checked where the claim is
resolved, in an activity (§3.3). It's bounded: its pointer is at most POINTER_MAX bytes, encoded, so its encoding is at
most HANDLE_MAX; a reference that would make a longer one derives a new claim instead. Data from outside never crosses
into a run as a handle: admission and the activity boundary refuse a value that holds the marker anywhere."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

MARKER = "$claim"
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
