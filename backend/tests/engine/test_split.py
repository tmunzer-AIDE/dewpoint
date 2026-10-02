# SPDX-License-Identifier: Apache-2.0
"""Splitting a trigger or a sub-flow's input (engine 2b spec §3.5): sensitive values first, every value at an
`x-sensitive` position or one the schema doesn't declare (unknown counts as sensitive); then text that repeats one of
those secrets; then values over 64 KiB; then, while the envelope passes TRIGGER_INLINE, its largest subtree, and the
root last. What's left is the envelope, with handles in place of claims."""

import itertools
import json
import uuid
from typing import Any

import ahocorasick_rs
import pytest
from hypothesis import given
from hypothesis import strategies as st

from dewpoint.engine.handles import ClaimRef, contains_marker, handles_in
from dewpoint.engine.matcher import Matcher
from dewpoint.engine.split import TRIGGER_INLINE, ForgedHandleError, sized, split
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
        ({"type": "object", "additionalProperties": {"type": "string"}}, {"k": "v"}, ["/k"]),
        ({"type": "object", "patternProperties": {"^x": {"type": "string"}}}, {"xa": "v"}, ["/xa"]),
        (obj(rows={"type": "array"}), {"rows": [1, 2]}, ["/rows/0", "/rows/1"]),  # elements not declared
        (obj(rows={"type": "array", "items": {"type": "integer"}}), {"rows": [1, 2]}, []),
        (obj(t={"type": "array", "prefixItems": [{"type": "integer"}]}), {"t": [1, 2]}, ["/t/0", "/t/1"]),  # one taint
        (obj(u={"anyOf": [obj(token={"type": "string"}), {"type": "object"}]}), {"u": {"token": "t"}}, ["/u/token"]),
        ({**obj(a={"type": "string"}), "patternProperties": {"^x": {"type": "string"}}}, {"a": "x", "xa": "v"},
         ["/xa"]),
        ({**obj(a={"type": "string"}), "anyOf": [{"required": ["a"]}, {"type": "object"}]}, {"a": "x"}, []),
        (obj(m={"type": "object", "propertyNames": {"x-sensitive": True}}), {"m": {"a": 1}}, ["/m"]),
        ({}, {"a": 1}, ["/a"]),
        (obj(v={}), {"v": "plain"}, []),  # a declared key of any type: a scalar there is plain, its parts aren't
        (obj(v={}), {"v": {"a": 1}}, ["/v/a"]),
        (obj(v={}), {"v": [1, 2]}, ["/v/0", "/v/1"]),
        (None, {"a": 1}, [""]),  # no schema at all: the whole value
    ],
)  # fmt: skip
def test_sensitive_positions(schema: Any, value: Any, expected: list[str]) -> None:
    """The largest wholly tainted parts: each undeclared key's value, each undeclared element."""
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


def test_text_that_repeats_a_secret_the_run_already_knows_is_claimed_too() -> None:
    """At the activity boundary (§3.6, §3.7): a plain output string holding a string of the run's secret index is
    claimed with taint, as one holding the output's own secret is."""
    done = split({"note": "token=t0k3n-1234 ok", "n": 1}, obj(note={"type": "string"}, n={"type": "integer"}), ids(),
                 known=("t0k3n-1234",))  # fmt: skip
    assert [(c.pointer, c.tainted) for c in done.claims] == [("/note", True)]
    assert done.secrets == ("token=t0k3n-1234 ok",)  # its strings join the index; what the index held, it holds


def test_without_sizes_only_sensitive_text_is_claimed() -> None:
    """A step's output is split for what's sensitive now; spilling what's large comes with sizes (§5.2)."""
    big = "x" * (TRIGGER_INLINE + 10)
    done = split({"big": big, "token": "t0k3n"}, obj(big={"type": "string"}, token=SECRET), ids(), sizes=False)
    assert [(c.pointer, c.tainted) for c in done.claims] == [("/token", True)]
    assert done.envelope["big"] == big


def test_a_handle_is_claimed_already_nothing_under_it_is_listed() -> None:
    held = ClaimRef(str(uuid.UUID(int=9))).to_json()
    assert positions({"token": held, "name": "x"}, obj(token=SECRET, name={"type": "string"})) == []
    assert positions(held, None) == []


def test_the_matcher_builds_an_nfa_so_a_long_secret_costs_its_length() -> None:
    """The automaton's default for few patterns is a DFA, whose construction grows with a long secret's length squared
    (20,000 characters took seconds; a step's output hung). The index holds strings up to 8 MiB, so the matcher
    always builds the contiguous NFA: its cost is the length of what it's given, to build and to scan."""
    assert Matcher.IMPLEMENTATION is ahocorasick_rs.Implementation.ContiguousNFA
    long = "s" * 1_000_000
    assert Matcher([long]).found("x" + long + "x") == {long}


def test_an_envelope_limit_claims_down_to_it() -> None:
    """A step's output is split to the inline threshold the workflow sent (engine 2b spec §5.4), not the trigger's."""
    value = {"a": "x" * 3_000, "b": "y" * 500, "c": 1}
    schema = obj(a={"type": "string"}, b={"type": "string"}, c={"type": "integer"})
    done = split(value, schema, ids(), envelope=1_024)
    assert size(done.envelope) <= 1_024
    assert [c.pointer for c in done.claims] == ["/a"]


def test_a_spill_claims_parts_no_larger_than_its_bound_and_keeps_handles() -> None:
    """The workflow's own values, spilled before a command goes (engine 2b spec §5.2): nothing in them is sensitive, so
    only size counts. Every part fits one spill chunk, the envelope fits its limit, and a handle already there stays."""
    held = ClaimRef(str(uuid.UUID(int=99))).to_json()
    value = {"list": ["x" * 9_000] * 8, "deep": {"a": {"b": ["y" * 6_000] * 5}}, "held": held, "n": 1}
    done = sized(value, ids(), envelope=2_000, part=10_000)
    assert size(done.envelope) <= 2_000
    assert all(size(c.value) <= 10_000 for c in done.claims)
    assert not any(c.tainted for c in done.claims) and done.secrets == ()
    assert done.envelope["held"] == held
    made: set[str] = set()
    for c in done.claims:  # a claim's handles name claims made before it, or the run's own
        assert {h.id for _, h in handles_in(c.value)} <= made | {held["$claim"]}
        made.add(c.id)


def test_a_spill_of_a_value_that_fits_claims_nothing() -> None:
    done = sized({"a": "x" * 100}, ids(), envelope=2_000, part=10_000)
    assert (done.envelope, done.claims) == ({"a": "x" * 100}, ())


KEY = "sk-k3y-canary-0002"  # a secret the input holds as a key, at a position its schema doesn't declare


def test_a_key_the_schema_doesnt_declare_leaves_the_envelope_inside_a_claim_and_joins_the_secrets() -> None:
    """Review finding C1: a map's keys are data too, and one at a position its schema doesn't declare can be a secret.
    Its value is claimed with taint as before; the map itself is then claimed whole (without taint: its taint is its
    nested claims'), so the key never stays in the envelope, and the key joins the run's secrets."""
    schema = obj(m={"type": "object", "additionalProperties": {"type": "string"}})
    done = split({"m": {KEY: "prod"}}, schema, ids())
    assert KEY not in json.dumps(done.envelope)
    value, keys = done.claims
    assert (value.pointer, value.value, value.tainted) == (f"/m/{KEY}", "prod", True)
    assert (keys.pointer, keys.value, keys.tainted) == ("/m", {KEY: ClaimRef(value.id).to_json()}, False)
    assert done.envelope == {"m": ClaimRef(keys.id).to_json()}
    assert KEY in done.secrets


def test_a_maps_declared_fields_stay_in_its_key_claim_plain_and_innermost_maps_go_first() -> None:
    """The map is claimed whole only because of its undeclared keys: its declared fields stay plain inside the claim,
    so a reference to one reads plain data (§4.1). A map nested in another is claimed before it."""
    inner = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}
    schema = obj(o={"type": "object", "properties": {"name": {"type": "string"}, "inner": inner},
                    "required": ["name", "inner"]})  # fmt: skip
    done = split({"o": {"name": "ann", "inner": {"id": "i1", KEY: "x"}, "extra-key-1": "y"}}, schema, ids())
    assert KEY not in json.dumps(done.envelope) and "extra-key-1" not in json.dumps(done.envelope)
    keyed = [c for c in done.claims if not c.tainted]
    assert [c.pointer for c in keyed] == ["/o/inner", "/o"]  # innermost first
    assert keyed[1].value["name"] == "ann" and ClaimRef.of(keyed[1].value["inner"]) == ClaimRef(keyed[0].id)
    assert keyed[0].value["id"] == "i1"
    assert {KEY, "extra-key-1"} <= set(done.secrets)


def test_a_key_the_schema_doesnt_declare_is_a_secret_before_the_rest_is_checked() -> None:
    """The owner's re-review of C1: keys were collected after the reappearing-text check, so a plain field repeating an
    undeclared key stayed plain in the envelope. The keys join the secrets first: a sibling or a declared field of the
    map itself that repeats one is claimed with taint, and the map is still claimed whole, without taint, for its
    own keys: a reference to a declared field reads plain."""
    open_map = {"type": "object", "properties": {"env": {"type": "string"}}, "additionalProperties": {"type": "string"}}
    schema = obj(c=open_map, note={"type": "string"})
    done = split({"c": {"env": "prod", KEY: "x"}, "note": KEY}, schema, ids())
    assert KEY not in json.dumps(done.envelope) and KEY in done.secrets
    claims = {c.pointer: c for c in done.claims}
    assert (claims["/note"].value, claims["/note"].tainted) == (KEY, True)
    assert (claims["/c"].value["env"], claims["/c"].tainted) == ("prod", False)
    inside = split({"c": {"env": KEY, KEY: "x"}, "note": "n"}, schema, ids())  # the map's own declared field
    claims = {c.pointer: c for c in inside.claims}
    assert (claims["/c/env"].value, claims["/c/env"].tainted) == (KEY, True)
    assert not claims["/c"].tainted and ClaimRef.of(claims["/c"].value["env"]) == ClaimRef(claims["/c/env"].id)
    assert inside.envelope["note"] == "n"


def test_a_closed_object_has_no_key_claim() -> None:
    done = split({"o": {"name": "ann"}}, obj(o=obj(name={"type": "string"})), ids())
    assert done.claims == () and done.envelope == {"o": {"name": "ann"}}
