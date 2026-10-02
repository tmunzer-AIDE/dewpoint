# SPDX-License-Identifier: Apache-2.0
"""Splitting a run's input into claims before it starts (engine 2b spec §3.5): a trigger at admission, a sub-flow's
input when its parent starts it. The input was validated against its schema first.

1. **Sensitive values:** every value at an `x-sensitive` position, or at one the schema doesn't declare (unknown counts
   as sensitive), is claimed with taint. Their strings of MIN_SECRET characters or more are the run's first secrets.
2. **Reappearing text:** an untainted string, or a key, that contains one of those secrets is claimed with taint. This
   comes before size claims, which are made after their tainted descendants (§3.5), so a size claim never holds a
   secret in plain text.
3. **Size:** a value larger than SIZE_CLAIM is claimed without taint, after its own large parts, so it holds handles
   where they were.
4. **The envelope:** while the input passes TRIGGER_INLINE (or the limit a step's output is sent with, §5.4), its
   largest remaining part is claimed without taint, ties broken by pointer; a part is worth claiming only if it weighs
   more than the handle that replaces it. The root goes last, and the input is then one handle.

The result is the envelope, with handles in place of claims, and the claims in the order they were made: a claim's
nested handles always name claims made before it. Ids come from the caller (`new_id`): random at admission,
derived where a retry must make the same ones."""

import copy
import json
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.handles import ClaimRef, contains_marker, escape, tokens
from dewpoint.engine.matcher import Matcher
from dewpoint.engine.sensitive import MIN_SECRET
from dewpoint.engine.taint import from_schema, tainted_positions

TRIGGER_INLINE = 65_536  # a run's input envelope, as JSON, at most (spec §15: provisional)
SIZE_CLAIM = 65_536  # a value larger than this, as JSON, is a size claim (§5.1: the local CEL per-value cap)
HANDLE_BYTES = len(json.dumps(ClaimRef(str(uuid.UUID(int=0))).to_json(), separators=(",", ":")))


class ForgedHandleError(ValueError):
    """An input that holds the handle marker: data from outside never crosses into a run as a handle (§3.2)."""


@dataclass(frozen=True)
class Claim:
    id: str
    pointer: str  # where in the input it was claimed from
    value: Any  # may hold handles to claims made before it
    tainted: bool  # the whole value is sensitive; otherwise its taint is its nested claims'


@dataclass(frozen=True)
class Split:
    envelope: Any
    claims: tuple[Claim, ...]
    secrets: tuple[str, ...]  # every string of MIN_SECRET characters or more in a tainted claim: the secret index's


def json_bytes(value: Any) -> int:
    """A value's JSON bytes, as the SDK's converter writes it."""
    return len(json.dumps(value, separators=(",", ":")))


def _strings(value: Any) -> Iterator[str]:
    """A value's strings and keys: never a handle's, whose id and pointer are metadata."""
    if isinstance(value, str):
        yield value
    elif ClaimRef.of(value) is not None:
        return
    elif isinstance(value, Mapping):
        for key, child in value.items():
            yield key
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


def _without_handles(value: Any) -> Any:
    if ClaimRef.of(value) is not None:
        return None
    if isinstance(value, dict):
        return {k: _without_handles(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_without_handles(v) for v in value]
    return value


class _Splitter:
    def __init__(self, value: Any, new_id: Callable[[str], str]) -> None:
        self.doc, self.new_id = copy.deepcopy(value), new_id
        self.claims: list[Claim] = []

    def _parent(self, pointer: str) -> tuple[Any, str | int]:
        parts = tokens(pointer)
        node = self.doc
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        last = parts[-1]
        return node, int(last) if isinstance(node, list) else last

    def claim(self, pointer: str, *, tainted: bool) -> None:
        if pointer == "":
            value, self.doc = self.doc, None
        else:
            node, key = self._parent(pointer)
            value = node[key]
        made = Claim(self.new_id(pointer), pointer, value, tainted)
        self.claims.append(made)
        handle = ClaimRef(made.id).to_json()
        if pointer == "":
            self.doc = handle
        else:
            node[key] = handle

    def reappearing(self, matcher: Matcher) -> list[str]:
        """The pointers of strings, and of objects whose keys, contain a secret: never inside a handle."""
        found: list[str] = []

        def walk(value: Any, pointer: str) -> None:
            if ClaimRef.of(value) is not None:
                return
            if isinstance(value, str):
                if matcher.found(value):
                    found.append(pointer)
            elif isinstance(value, dict):
                if any(matcher.found(k) for k in value):
                    found.append(pointer)
                    return
                for k, child in value.items():
                    walk(child, pointer + "/" + escape(k))
            elif isinstance(value, list):
                for i, child in enumerate(value):
                    walk(child, pointer + "/" + str(i))

        walk(self.doc, "")
        return found

    def by_size(self, value: Any, pointer: str) -> int:
        """Claims every part larger than SIZE_CLAIM, innermost first, below `pointer`; returns `value`'s size after."""
        if ClaimRef.of(value) is not None:
            return json_bytes(value)
        if isinstance(value, dict):
            for k in list(value):
                at = pointer + "/" + escape(k)
                if self.by_size(value[k], at) > SIZE_CLAIM:
                    self.claim(at, tainted=False)
        elif isinstance(value, list):
            for i in range(len(value)):
                at = pointer + "/" + str(i)
                if self.by_size(value[i], at) > SIZE_CLAIM:
                    self.claim(at, tainted=False)
        return json_bytes(value)

    def envelope(self, limit: int) -> None:
        total = json_bytes(self.doc)
        if total <= limit:
            return
        children: list[tuple[str | int, Any]] = (
            list(self.doc.items()) if isinstance(self.doc, dict) else list(enumerate(self.doc))
            if isinstance(self.doc, list) else []
        )  # fmt: skip
        sized = [(json_bytes(child), "/" + escape(key)) for key, child in children if ClaimRef.of(child) is None]
        for weight, pointer in sorted(sized, key=lambda wp: (-wp[0], wp[1])):
            if total <= limit:
                return
            if weight <= HANDLE_BYTES:
                break
            self.claim(pointer, tainted=False)
            total -= weight - HANDLE_BYTES
        if total > limit:
            self.claim("", tainted=False)


def split(
    value: Any,
    schema: Mapping[str, Any] | None,
    new_id: Callable[[str], str],
    *,
    known: Iterable[str] = (),
    sizes: bool = True,
    handles: bool = False,
    envelope: int = TRIGGER_INLINE,
) -> Split:
    """`value` (a validated trigger or sub-flow input, or an activity's result) as its envelope and its claims
    (above). `known`: the run's secrets so far (its secret index, §3.7): text that repeats one is claimed too.
    `sizes` False: only what's sensitive is claimed. `handles`: the value may hold the run's own handles (a sub-flow's
    input, from its parent, §3.4), left where they are; any other use of the marker is still refused. `envelope`: the
    envelope's limit, the trigger's or the inline threshold a step's output is split to (§5.4)."""
    if contains_marker(_without_handles(value) if handles else value):
        raise ForgedHandleError("An input that holds the handle marker.")
    s = _Splitter(value, new_id)
    for pointer in tainted_positions(value, from_schema(schema)):
        s.claim(pointer, tainted=True)
    secrets = {t for c in s.claims for t in _strings(c.value) if len(t) >= MIN_SECRET}
    if ClaimRef.of(s.doc) is None:
        for pointer in s.reappearing(Matcher(secrets | set(known))):
            s.claim(pointer, tainted=True)
            secrets |= {t for t in _strings(s.claims[-1].value) if len(t) >= MIN_SECRET}
        if sizes:
            s.by_size(s.doc, "")
            s.envelope(envelope)
    return Split(s.doc, tuple(s.claims), tuple(sorted(secrets)))
