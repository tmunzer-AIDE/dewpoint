# SPDX-License-Identifier: Apache-2.0
"""A body's strict parsing and its events (engine 2b spec §8.3; the owner's rulings on the 2b-3b outline and the M2
checks): UTF-8 JSON only; a duplicate key anywhere, NaN or an infinity, a number past binary64's range (`1e400`), an
escaped unpaired surrogate, an integer of more than 4,300 digits, or nesting deeper than 64 levels refuses the whole
body; events are the body itself or the array at the endpoint's events pointer, objects only, 1 to 500 of them."""

import json

import pytest

from dewpoint.core.ingress.parsing import MAX_DEPTH, MAX_EVENTS, MalformedError, events_of, parse
from dewpoint.core.ingress.pointer import PointerError, resolve


def test_a_plain_object_parses() -> None:
    assert parse(b'{"a": [1, 2.5, "x", null, true], "b": {"c": -3}}') == {
        "a": [1, 2.5, "x", None, True], "b": {"c": -3},
    }  # fmt: skip


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("not UTF-8", b'{"a": "\xff"}'),
        ("UTF-16", '{"a": 1}'.encode("utf-16")),
        ("not JSON", b"{'a': 1}"),
        ("trailing data", b'{"a": 1} {"b": 2}'),
        ("empty", b""),
        ("a duplicate key", b'{"a": 1, "a": 1}'),
        ("a nested duplicate key", b'{"a": [{"b": 1, "c": 2, "b": 3}]}'),
        ("NaN", b'{"a": NaN}'),
        ("Infinity", b'{"a": Infinity}'),
        ("-Infinity", b'{"a": -Infinity}'),
        ("overflow", b'{"a": 1e400}'),
        ("negative overflow", b'{"a": [-1e400]}'),
        ("an escaped lone high surrogate", b'{"a": "\\ud800"}'),
        ("an escaped lone low surrogate", b'{"a": ["x\\udc00y"]}'),
        ("a surrogate in a key", b'{"\\udbff": 1}'),
        ("reversed surrogates", b'{"a": "\\udc00\\ud800"}'),
        ("an integer past 4,300 digits", b'{"a": ' + b"9" * 4301 + b"}"),
        ("a negative one", b'{"a": -' + b"9" * 4301 + b"}"),
        ("65 levels", b"[" * 65 + b"]" * 65),
        ("65 levels of objects", b'{"a":' * 64 + b"[]" + b"}" * 64),
        ("far too deep", b"[" * 100_000 + b"]" * 100_000),
        ("far too deep, objects", b'{"a":' * 100_000 + b"1" + b"}" * 100_000),
    ],
)
def test_a_body_is_refused_whole(name: str, body: bytes) -> None:
    with pytest.raises(MalformedError):
        parse(body)


def test_what_strict_parsing_still_accepts() -> None:
    assert parse(b'{"a": "\\ud83d\\ude00"}') == {"a": "\U0001f600"}  # a paired escape is one character
    assert parse(b'{"a": "\\\\ud800"}') == {"a": "\\ud800"}  # an escaped backslash, then text
    assert parse(b'{"a": ' + b"9" * 4300 + b"}") == {"a": int("9" * 4300)}
    assert parse(b'{"a": 1e308, "b": 5e-324, "c": 1e-400}') == {"a": 1e308, "b": 5e-324, "c": 0.0}
    assert parse('{"é": "ü"}'.encode()) == {"é": "ü"}
    assert MAX_DEPTH == 64
    parse(b"[" * 64 + b"]" * 64)
    parse(b'{"a":' * 63 + b"[1]" + b"}" * 63)
    parse(b'{"a":' * 63 + b'["\\ud83d\\ude00"]' + b"}" * 63)  # strings checked too: still 64 levels


def test_the_refusal_quotes_nothing_of_the_body() -> None:
    with pytest.raises(MalformedError) as refused:
        parse(b'{"secret": "canary-7f3a", "secret": 1}')
    assert "canary" not in str(refused.value)
    assert refused.value.__cause__ is None and refused.value.__suppress_context__


def test_without_an_events_pointer_the_body_is_one_event() -> None:
    assert events_of({"a": 1}, None) == [{"a": 1}]
    for document in ([{"a": 1}], "x", 1, None):
        with pytest.raises(MalformedError):
            events_of(document, None)


def test_an_events_pointer_names_an_array_of_objects() -> None:
    document = {"topic": "alarms", "events": [{"id": 1}, {"id": 2}]}
    assert events_of(document, "/events") == [{"id": 1}, {"id": 2}]
    assert events_of([{"id": 1}], "") == [{"id": 1}]
    for bad in ({"events": {"id": 1}}, {"events": []}, {"events": [{"id": 1}, 2]}, {"events": [[]]}, {"other": []}):
        with pytest.raises(MalformedError):
            events_of(bad, "/events")


def test_at_most_500_events() -> None:
    assert len(events_of({"e": [{}] * MAX_EVENTS}, "/e")) == 500
    with pytest.raises(MalformedError):
        events_of({"e": [{}] * (MAX_EVENTS + 1)}, "/e")


def test_a_pointer_resolves_as_rfc_6901_says() -> None:
    document = json.loads('{"a/b": {"m~n": [10, {"x": 1}]}, "": 5, "0": "zero"}')
    assert resolve(document, "") == document
    assert resolve(document, "/a~1b/m~0n/1/x") == 1
    assert resolve(document, "/") == 5
    assert resolve(document, "/0") == "zero"
    for pointer in ("a", "/missing", "/a~1b/m~0n/2", "/a~1b/m~0n/-", "/a~1b/m~0n/01", "/a~1b/m~0n/+1", "/0/x"):
        with pytest.raises(PointerError):
            resolve(document, pointer)
