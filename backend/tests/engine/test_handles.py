# SPDX-License-Identifier: Apache-2.0
"""Handles (engine 2b spec §3.2): `ClaimRef(id, pointer)` under a reserved marker key. A handle carries no taint and
asserts nothing; it's bounded, so a reference that would make its pointer longer than POINTER_MAX derives a new claim
instead; and data from outside is refused when it holds the marker anywhere."""

import json
import uuid
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from dewpoint.engine.handles import (
    HANDLE_MAX,
    MARKER,
    POINTER_MAX,
    ClaimRef,
    contains_marker,
    handles_in,
    pointer_bytes,
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
