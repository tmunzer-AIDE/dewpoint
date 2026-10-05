# SPDX-License-Identifier: Apache-2.0
"""An event's identity (engine 2b spec §8.3; the owner's rulings on the 2b-3b outline). Its dedupe key is an HMAC,
under its endpoint's dedupe-digest key, of the id its sender gave it, typed (an integer `1` and a string `"1"` are two
ids); a batch-level header id is qualified by the item's index; an event without an id has none, and nothing
deduplicates it. Its content digest, the same key's HMAC of its canonical bytes, tells a duplicate from an id reused for
other content. Ids are never stored: only these digests are."""

import hashlib
import hmac
import json
from typing import Literal

type IdSource = Literal["pointer", "header", "none"]
MAX_ID_CHARS = 255
# Canonical bytes are at most this many times the raw JSON they came from: strings, whitespace and integers never grow,
# and a float grows most from a 4-character `1e15` to the 18 of `1000000000000000.0`. The recording function's
# backstop and the byte bursts are sized by it (the owner's M1 review).
CANONICAL_EXPANSION = 4.5


class InvalidEventIdError(ValueError):
    """An id that isn't a non-empty string, or an integer, of at most 255 characters."""


def _hmac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def _bounded(text: str) -> str:
    if not 0 < len(text) <= MAX_ID_CHARS:
        raise InvalidEventIdError("an event id is 1 to 255 characters")
    return text


def _typed(event_id: object) -> bytes:
    if isinstance(event_id, str):
        return b"s:" + _bounded(event_id).encode()
    if isinstance(event_id, int) and not isinstance(event_id, bool):
        if event_id.bit_length() > 1024:  # far past 255 digits, before `str` (which refuses past 4,300)
            raise InvalidEventIdError("an event id is 1 to 255 characters")
        return b"i:" + _bounded(str(event_id)).encode()
    raise InvalidEventIdError("an event id is a string or an integer")


def dedupe_key(key: bytes, source: IdSource, event_id: str | int | None, index: int) -> bytes | None:
    """The event's dedupe key, or None when its endpoint's events carry no id. Raises InvalidEventIdError."""
    if source == "none":
        return None
    if source == "pointer":
        return _hmac(key, b"event:" + _typed(event_id))
    if not isinstance(event_id, str):
        raise InvalidEventIdError("a request's id is a string")
    return _hmac(key, f"batch:{_bounded(event_id)}:{index}".encode())


def content_digest(key: bytes, canonical: bytes) -> bytes:
    return _hmac(key, b"content:" + canonical)


def canonical(event: object) -> bytes:
    """An event's canonical bytes, one written procedure, so no parser decides identity: object keys sorted by code
    point, no whitespace, strings as parsed (only `"`, the backslash and control characters escaped, no normalization),
    integers in decimal, floats in their shortest round-trip form, encoded as UTF-8. Raises ValueError for NaN or an
    infinity and UnicodeEncodeError for an unpaired surrogate (ingress refuses both before here)."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
