# SPDX-License-Identifier: Apache-2.0
"""An event's identity (engine 2b spec §8.3; the owner's rulings on the 2b-3b outline): its dedupe key is an HMAC, under
its endpoint's dedupe-digest key, of the id the sender gave it, typed, so an integer `1` and a string `"1"` are two
ids; a batch-level header id is qualified by the item's index; an event without an id has none, and nothing
deduplicates it. Its content digest, the same key's HMAC of its canonical bytes, tells a duplicate from an id reused
for other content."""

import hashlib
import hmac
import json

import pytest

from dewpoint.core.ingress import identity

KEY = bytes(range(32))


def test_a_pointer_id_is_typed_so_an_integer_and_its_string_differ() -> None:
    as_int = identity.dedupe_key(KEY, "pointer", 1, 0)
    as_str = identity.dedupe_key(KEY, "pointer", "1", 0)
    assert as_int is not None and as_str is not None and as_int != as_str
    assert as_int == hmac.new(KEY, b"event:i:1", hashlib.sha256).digest()
    assert as_str == hmac.new(KEY, b"event:s:1", hashlib.sha256).digest()
    assert identity.dedupe_key(KEY, "pointer", "1", 7) == as_str  # an event's own id: its position doesn't matter


def test_a_header_id_is_qualified_by_the_items_index() -> None:
    first, second = identity.dedupe_key(KEY, "header", "req-9", 0), identity.dedupe_key(KEY, "header", "req-9", 1)
    assert first != second
    assert first == hmac.new(KEY, b"batch:req-9:0", hashlib.sha256).digest()


def test_an_event_without_an_id_has_no_dedupe_key() -> None:
    assert identity.dedupe_key(KEY, "none", None, 0) is None


def test_the_keys_depend_on_the_endpoints_dedupe_key() -> None:
    assert identity.dedupe_key(KEY, "pointer", "a", 0) != identity.dedupe_key(bytes(32), "pointer", "a", 0)


@pytest.mark.parametrize("given", [True, False, 1.5, None, "", "x" * 256, [1], {"id": 1}, 10**300])
def test_an_id_that_isnt_a_short_string_or_integer_is_refused(given: object) -> None:
    with pytest.raises(identity.InvalidEventIdError):
        identity.dedupe_key(KEY, "pointer", given, 0)  # type: ignore[arg-type]


def test_a_header_id_must_be_a_short_string() -> None:
    for given in ("", "x" * 256, 7):
        with pytest.raises(identity.InvalidEventIdError):
            identity.dedupe_key(KEY, "header", given, 0)  # type: ignore[arg-type]


def test_the_content_digest_is_keyed_and_apart_from_any_dedupe_key() -> None:
    digest = identity.content_digest(KEY, b'{"a":1}')
    assert digest == hmac.new(KEY, b'content:{"a":1}', hashlib.sha256).digest()
    assert digest != identity.content_digest(bytes(32), b'{"a":1}')
    assert digest != identity.dedupe_key(KEY, "pointer", '{"a":1}', 0)


def test_canonical_bytes_follow_the_written_procedure() -> None:
    """Keys sorted by code point, no whitespace, strings as parsed (only quotes, backslashes and controls escaped),
    integers in decimal, floats in their shortest round-trip form, UTF-8."""
    event = json.loads('{ "b": 2, "a": [1, 1.0, 1e2, "\\u00e9\\/\\n"] }')
    assert identity.canonical(event) == '{"a":[1,1.0,100.0,"é/\\n"],"b":2}'.encode()


@pytest.mark.parametrize(
    "raw",
    [
        '{"a":1e15}', '{"a":9E15}', '{"a":-1e15}', '{"a":1e9}', '{"a":1e14}', '{"a":1e-5}', '{"a":1e300}',
        '{"a":[' + ",".join(["1e15"] * 150) + "]}", '{"a" : [ 1e14 , 1e15 ]}', '{"a":12345678901234567890}',
        '{"\\u00e9\\/":"\\ud83d\\ude00"}',
    ],
)  # fmt: skip
def test_canonical_bytes_are_at_most_four_and_a_half_times_the_raw_json(raw: str) -> None:
    """The bound the recording function's backstop and the byte bursts are sized by (the owner's M1 review): strings,
    whitespace and integers never grow; a float can, at most from a 4-character `1e15` to the 18 of
    `1000000000000000.0`."""
    assert len(identity.canonical(json.loads(raw))) <= identity.CANONICAL_EXPANSION * len(raw.encode())
