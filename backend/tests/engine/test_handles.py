# SPDX-License-Identifier: Apache-2.0
"""Handles (engine 2b spec §3.2): `ClaimRef(id, pointer)` under a reserved marker key. A handle carries no taint and
asserts nothing; it's bounded, so a reference that would make its pointer longer than POINTER_MAX derives a new claim
instead; and data from outside is refused when it holds the marker anywhere."""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dewpoint.engine.handles import (
    HANDLE_MAX,
    MARKER,
    POINTER_MAX,
    ClaimRef,
    InputTooDeepError,
    NestingError,
    StoredClaim,
    contains_marker,
    escape,
    handles_in,
    pointer_bytes,
    resolve_value,
    tokens,
)

CLAIM = str(uuid.UUID(int=7))
token = st.one_of(st.text(max_size=12), st.integers(min_value=0, max_value=10_000))
json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=4)
        | st.dictionaries(st.text(max_size=6).filter(lambda k: k != MARKER), inner, max_size=4)
    ),
    max_leaves=20,
)


def test_a_handle_is_its_marker_and_id_and_a_pointer_only_when_it_has_one() -> None:
    assert ClaimRef(CLAIM).to_json() == {MARKER: CLAIM}
    assert ClaimRef(CLAIM, "/rows/7").to_json() == {MARKER: CLAIM, "pointer": "/rows/7"}


@given(st.lists(token, max_size=6))
def test_a_handle_round_trips_and_its_pointer_spells_each_token(path: list[str | int]) -> None:
    ref = ClaimRef(CLAIM).extend(*path)
    assert ClaimRef.of(json.loads(json.dumps(ref.to_json()))) == ref
    assert tokens(ref.pointer) == [str(t) for t in path]


def test_extending_escapes_slashes_and_tildes() -> None:
    ref = ClaimRef(CLAIM, "/a").extend("b/c", "d~e", 3)
    assert ref.pointer == "/a/b~1c/d~0e/3"


@pytest.mark.parametrize(
    "value",
    [
        {MARKER: CLAIM, "pointer": "/x", "extra": 1},  # anything beside the marker and pointer
        {MARKER: "not-a-uuid"},
        {MARKER: CLAIM, "pointer": "no-leading-slash"},
        {MARKER: 7},
        {"pointer": "/x"},
        [CLAIM],
        CLAIM,
    ],
)
def test_only_the_exact_form_is_a_handle(value: Any) -> None:
    assert ClaimRef.of(value) is None


@given(st.lists(token, max_size=40))
def test_a_handle_within_pointer_max_encodes_within_handle_max(path: list[str | int]) -> None:
    ref = ClaimRef(str(uuid.uuid4())).extend(*path)
    assert ref.too_long() == (pointer_bytes(ref.pointer) > POINTER_MAX)
    if not ref.too_long():
        assert len(json.dumps(ref.to_json(), separators=(",", ":"))) <= HANDLE_MAX


def test_handle_max_is_the_marker_a_claim_id_and_the_longest_pointer() -> None:
    longest = ClaimRef(str(uuid.uuid4()), "/" + "x" * (POINTER_MAX - 3))
    assert pointer_bytes(longest.pointer) == POINTER_MAX and not longest.too_long()
    assert len(json.dumps(longest.to_json(), separators=(",", ":"))) == HANDLE_MAX


@given(json_values)
def test_plain_data_holds_no_marker_and_no_handle(value: Any) -> None:
    assert not contains_marker(value)
    assert list(handles_in(value)) == []


def test_the_marker_is_found_anywhere_and_handles_with_their_positions() -> None:
    a, b = ClaimRef(CLAIM, "/0"), ClaimRef(str(uuid.UUID(int=8)))
    value = {"x": [1, {"y": a.to_json()}], "z": b.to_json()}
    assert contains_marker(value)
    assert dict(handles_in(value)) == {"/x/1/y": a, "/z": b}
    assert contains_marker([{"deep": [{MARKER: "anything"}]}])  # a forged or malformed one too
    assert not contains_marker({"$claims": 1, "marker": MARKER})  # only the key is the marker


def _recursive_handles_in(value: Any, pointer: str = "") -> Iterator[tuple[str, ClaimRef]]:
    """`handles_in` as it was before issue #88: the reference its iterative walk must equal."""
    ref = ClaimRef.of(value)
    if ref is not None:
        yield pointer, ref
        return
    children = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, child in children:
        yield from _recursive_handles_in(child, pointer + "/" + escape(key))


with_handles = st.recursive(
    st.none() | st.integers() | st.text(max_size=4) | st.builds(lambda n: ClaimRef(str(uuid.UUID(int=n))).to_json(),
                                                                st.integers(min_value=0, max_value=5)),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=4).filter(lambda k: k != MARKER),
                                                                inner, max_size=4),
    max_leaves=30,
)  # fmt: skip


@given(with_handles)
def test_handles_are_found_as_before_in_the_same_order(value: Any) -> None:
    assert list(handles_in(value)) == list(_recursive_handles_in(value))


def nest(levels: int, leaf: Any = None) -> Any:
    """`levels` objects deep, `leaf` inside the deepest."""
    value: Any = {} if leaf is None else {"leaf": leaf}
    for _ in range(levels - 1):
        value = {"n": value}
    return value


def test_a_handle_is_found_however_deep_it_sits() -> None:
    """Discovery reads stored claims before anything bounds them (issue #88): it never recurses."""
    ref = ClaimRef(CLAIM)
    assert [r for _, r in handles_in(nest(2_000, ref.to_json()))] == [ref]


def _fetching(claims: dict[str, Any]) -> Any:
    async def fetch(claim_id: str) -> StoredClaim:
        return StoredClaim(claims[claim_id], ())

    return fetch


def _id(n: int) -> str:
    return str(uuid.UUID(int=100 + n))


async def test_a_bound_refuses_a_value_built_past_it_at_any_source() -> None:
    """Issue #88: bounded, the resolution stops past `max_depth` levels of the value it builds, never descending
    further, whether the depth is the value's own, a chain of shallow claims or one deep claim."""
    fetch = _fetching({})
    assert (await resolve_value(nest(64), fetch, max_depth=64)).value == nest(64)
    with pytest.raises(InputTooDeepError):
        await resolve_value(nest(65), fetch, max_depth=64)
    with pytest.raises(InputTooDeepError):
        await resolve_value(nest(300), fetch, max_depth=64)
    # 24 claims of 41 levels, each holding the next at its deepest: about 984 levels once expanded
    chain = {_id(i): nest(41, ClaimRef(_id(i + 1)).to_json() if i < 23 else None) for i in range(24)}
    envelope = {"a": {"b": ClaimRef(_id(0)).to_json()}}
    with pytest.raises(InputTooDeepError):
        await resolve_value(envelope, _fetching(chain), max_depth=64)
    with pytest.raises(InputTooDeepError):  # one claim of 2,000 levels
        await resolve_value(envelope, _fetching({_id(0): nest(2_000)}), max_depth=64)


async def test_a_bound_counts_across_claims_from_where_each_handle_sits() -> None:
    claims = {_id(0): nest(31, ClaimRef(_id(1)).to_json()), _id(1): nest(32)}
    within = {"x": ClaimRef(_id(0)).to_json()}  # 1 (the envelope) + 31 (the first claim) + 32 (the second) = 64
    assert (await resolve_value(within, _fetching(claims), max_depth=64)).value["x"]["n"]
    with pytest.raises(InputTooDeepError):
        await resolve_value({"y": within}, _fetching(claims), max_depth=64)


async def test_without_a_bound_resolution_is_as_before() -> None:
    """The other callers (a step's config, a loop's items, a failure's strings) pass no bound: a claimed 65-level
    body resolves as it did."""
    claims = {_id(0): nest(65)}
    assert (await resolve_value({"body": ClaimRef(_id(0)).to_json()}, _fetching(claims))).value == {"body": nest(65)}


async def test_a_claim_chain_past_its_count_is_still_a_nesting_error() -> None:
    chain = {_id(i): {"next": ClaimRef(_id(i + 1)).to_json()} for i in range(40)} | {_id(40): 1}
    with pytest.raises(NestingError):
        await resolve_value(ClaimRef(_id(0)).to_json(), _fetching(chain), max_depth=10_000)


def test_too_deep_is_neither_a_nesting_error_nor_an_unavailable_claim() -> None:
    from dewpoint.core.claims.service import ClaimUnavailableError

    assert not issubclass(InputTooDeepError, NestingError | ClaimUnavailableError)
