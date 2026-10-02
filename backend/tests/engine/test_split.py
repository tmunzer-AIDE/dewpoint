# SPDX-License-Identifier: Apache-2.0
"""Splitting a trigger or a sub-flow's input (engine 2b spec §3.5): sensitive values first, every value at an
`x-sensitive` position or one the schema doesn't declare (unknown counts as sensitive); then text that repeats one of
those secrets; then values over 64 KiB; then, while the envelope passes TRIGGER_INLINE, its largest subtree, and the
root last. What's left is the envelope, with handles in place of claims."""

import itertools
import json
import uuid
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dewpoint.engine.handles import ClaimRef, contains_marker, handles_in
from dewpoint.engine.matcher import Matcher
from dewpoint.engine.split import TRIGGER_INLINE, ForgedHandleError, split
from dewpoint.engine.taint import from_schema, tainted_positions

SECRET = {"type": "string", "x-sensitive": True}


def ids() -> Any:
    counter = itertools.count(1)
    return lambda pointer: str(uuid.UUID(int=next(counter)))


def size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":")))


def obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def positions(value: Any, schema: Any) -> list[str]:
    """What splitting claims with taint: where publish's taint (`from_schema`) is whole."""
    return tainted_positions(value, from_schema(schema))


# --- where the sensitive values are ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema", "value", "expected"),
    [
        (obj(name={"type": "string"}, token=SECRET), {"name": "ann", "token": "t0ken"}, ["/token"]),
        (obj(login=obj(user={"type": "string"}, password=SECRET)), {"login": {"user": "u", "password": "p"}},
         ["/login/password"]),
        ({"$defs": {"P": SECRET}, **obj(p={"$ref": "#/$defs/P"})}, {"p": "x"}, ["/p"]),
        (obj(u={"anyOf": [{"type": "string"}, SECRET]}), {"u": "x"}, ["/u"]),  # any branch sensitive
        ({"type": "object", "properties": {"a": {"type": "string"}}}, {"a": "x", "extra": 1}, ["/extra"]),
        ({"type": "object", "additionalProperties": {"type": "string"}}, {"k": "v"}, [""]),  # whole, keys too
        ({"type": "object", "patternProperties": {"^x": {"type": "string"}}}, {"xa": "v"}, [""]),
        (obj(rows={"type": "array"}), {"rows": [1, 2]}, ["/rows/0", "/rows/1"]),  # elements not declared
        (obj(rows={"type": "array", "items": {"type": "integer"}}), {"rows": [1, 2]}, []),
        (obj(t={"type": "array", "prefixItems": [{"type": "integer"}]}), {"t": [1, 2]}, ["/t/0", "/t/1"]),  # one taint
        (obj(u={"anyOf": [obj(token={"type": "string"}), {"type": "object"}]}), {"u": {"token": "t"}}, ["/u"]),
        ({**obj(a={"type": "string"}), "patternProperties": {"^x": {"type": "string"}}}, {"a": "x", "xa": "v"},
         ["/xa"]),
        ({**obj(a={"type": "string"}), "anyOf": [{"required": ["a"]}, {"type": "object"}]}, {"a": "x"}, []),
        (obj(m={"type": "object", "propertyNames": {"x-sensitive": True}}), {"m": {"a": 1}}, ["/m"]),
        ({}, {"a": 1}, [""]),
        (None, {"a": 1}, [""]),  # no schema at all: the whole value
    ],
)  # fmt: skip
def test_sensitive_positions(schema: Any, value: Any, expected: list[str]) -> None:
    """The largest wholly tainted parts: a value no part of which is declared is claimed whole, its keys with it."""
    assert positions(value, schema) == expected


# --- the matcher ----------------------------------------------------------------------------------------------------


def test_the_matcher_finds_and_masks_the_longest_secret_and_ignores_short_ones() -> None:
    matcher = Matcher(["s3cret", "s3cret-key", "abc"])  # "abc" is under 4 characters: never a secret
    assert matcher.found("id s3cret-key and s3cret, abc") == {"s3cret-key", "s3cret"}
    assert matcher.mask("id s3cret-key, abc", "[redacted]") == "id [redacted], abc"
    assert not Matcher([]).found("anything") and Matcher([]).mask("anything", "x") == "anything"


# --- splitting ------------------------------------------------------------------------------------------------------


def test_sensitive_values_are_claimed_with_taint_and_their_strings_are_secrets() -> None:
    schema = obj(name={"type": "string"}, token=SECRET, login=obj(password=SECRET))
    done = split({"name": "ann", "token": "t0ken-1", "login": {"password": "pw-123"}}, schema, ids())
    assert done.envelope["name"] == "ann"
    claims = {c.pointer: c for c in done.claims}
    assert set(claims) == {"/token", "/login/password"} and all(c.tainted for c in claims.values())
    assert ClaimRef.of(done.envelope["token"]) == ClaimRef(claims["/token"].id)
    assert done.secrets == ("pw-123", "t0ken-1")


def test_text_that_repeats_a_secret_is_claimed_with_taint_and_short_text_never() -> None:
    schema = obj(token=SECRET, note={"type": "string"}, pin=SECRET, tag={"type": "string"})
    done = split({"token": "abcd-1234", "note": "it was abcd-1234!", "pin": "123", "tag": "123"}, schema, ids())
    reappeared = [c for c in done.claims if c.pointer == "/note"]
    assert reappeared and reappeared[0].tainted
    assert done.envelope["tag"] == "123"  # "123" is under 4 characters: not a secret


def test_a_value_over_64_kib_is_claimed_without_taint_after_its_sensitive_parts() -> None:
    schema = obj(doc=obj(a={"type": "string"}, b={"type": "string"}, key=SECRET))
    done = split({"doc": {"a": "x" * 40_000, "b": "x" * 40_000, "key": "k3y-value"}}, schema, ids())
    order = [c.pointer for c in done.claims]
    assert order == ["/doc/key", "/doc"]  # each part fits; together they don't, so the whole goes after its secret
    doc = done.claims[1]
    assert not doc.tainted and size(doc.value) > 65_536
    assert ClaimRef.of(doc.value["key"]) == ClaimRef(done.claims[0].id) and "k3y-value" not in json.dumps(doc.value)


def test_the_innermost_part_over_64_kib_goes_first() -> None:
    done = split({"doc": {"body": "x" * 70_000, "n": 1}}, obj(doc=obj(body={"type": "string"}, n={"type": "integer"})),
                 ids())  # fmt: skip
    assert [c.pointer for c in done.claims] == ["/doc/body"] and done.envelope["doc"]["n"] == 1


def test_while_the_envelope_is_too_large_its_largest_subtrees_go_ties_by_pointer() -> None:
    fields = {f"f{i:02d}": "y" * 10_000 for i in range(12)}  # 12 x 10 KB: past 64 KiB, each under it
    schema = obj(**{k: {"type": "string"} for k in fields})
    done = split(fields, schema, ids())
    assert size(done.envelope) <= TRIGGER_INLINE
    claimed = [c.pointer for c in done.claims]
    assert claimed == [f"/f{i:02d}" for i in range(len(claimed))]  # equal sizes: by pointer
    assert len(claimed) == 6 and not any(c.tainted for c in done.claims)


def test_when_no_subtree_is_worth_claiming_the_root_is_claimed_last() -> None:
    many = {f"k{i:05d}": i for i in range(9_000)}  # small entries: a handle each would weigh more
    schema = {"type": "object", "properties": {k: {"type": "integer"} for k in many}}
    done = split(many, schema, ids())
    assert [c.pointer for c in done.claims] == [""]
    assert ClaimRef.of(done.envelope) == ClaimRef(done.claims[0].id)


def test_a_value_holding_the_marker_is_refused() -> None:
    with pytest.raises(ForgedHandleError):
        split({"a": {"$claim": str(uuid.UUID(int=1))}}, obj(a={"type": "object"}), ids())


plain = st.recursive(
    st.integers() | st.text(max_size=8),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.sampled_from("abcxyz"), inner, max_size=3),
    max_leaves=12,
)
SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "string"}, "b": {"type": "array", "items": {"type": "integer"}}, "s": SECRET,
                   "o": {"type": "object", "properties": {"x": SECRET, "y": {"type": "integer"}}}},
}  # fmt: skip


@given(st.dictionaries(st.sampled_from("abcosxyz"), plain, max_size=6))
def test_nothing_plain_is_left_at_a_sensitive_or_undeclared_position(value: dict[str, Any]) -> None:
    done = split(value, SCHEMA, ids())
    by_id = {c.id: c for c in done.claims}
    for pointer in positions(value, SCHEMA):
        # walk the envelope down the pointer: a handle to a tainted claim stands at or above it
        node, parts = done.envelope, [p for p in pointer.split("/")[1:]]
        while ClaimRef.of(node) is None:
            assert parts, pointer
            node = node[parts.pop(0)] if isinstance(node, dict) else node[int(parts.pop(0))]
        claim = by_id[ClaimRef.of(node).id]  # type: ignore[union-attr]
        assert claim.tainted or any(by_id[r.id].tainted for _, r in handles_in(claim.value)), pointer
    assert not contains_marker(without_handles(done.envelope))  # no marker but the handles it made
    assert {r.id for _, r in handles_in(done.envelope)} <= set(by_id)


def without_handles(value: Any) -> Any:
    if ClaimRef.of(value) is not None:
        return None
    if isinstance(value, dict):
        return {k: without_handles(v) for k, v in value.items()}
    if isinstance(value, list):
        return [without_handles(v) for v in value]
    return value
