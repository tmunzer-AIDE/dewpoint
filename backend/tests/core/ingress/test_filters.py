# SPDX-License-Identifier: Apache-2.0
"""A binding's filter (engine 2b spec §8.3): at most 8 typed JSON-pointer equalities on the event, all of which must
hold; none matches every event. No CEL. Typed: `1`, `1.0`, `true` and `"1"` are four values. A filter is checked when
it's written: a pointer (RFC 6901, at most 256 characters) and a scalar value (a string of at most 1,024 characters,
an integer, a boolean or null; never a float, whose equality is a formatting question)."""

import pytest

from dewpoint.core.ingress.filters import FilterError, matches, validated

EVENT = {"type": "ap_down", "count": 1, "up": True, "site": {"id": "s-1", "name": None}, "tags": ["a", "b"]}


def test_no_clause_matches_every_event() -> None:
    assert matches([], EVENT)


def test_every_clause_must_hold() -> None:
    assert matches([{"pointer": "/type", "value": "ap_down"}, {"pointer": "/site/id", "value": "s-1"}], EVENT)
    assert not matches([{"pointer": "/type", "value": "ap_down"}, {"pointer": "/site/id", "value": "s-2"}], EVENT)


def test_equality_is_typed() -> None:
    assert matches([{"pointer": "/count", "value": 1}], EVENT)
    assert matches([{"pointer": "/up", "value": True}], EVENT)
    assert matches([{"pointer": "/site/name", "value": None}], EVENT)
    assert matches([{"pointer": "/tags/1", "value": "b"}], EVENT)
    for pointer, value in (("/count", True), ("/count", "1"), ("/up", 1), ("/site/name", False), ("/type", "AP_DOWN")):
        assert not matches([{"pointer": pointer, "value": value}], EVENT), (pointer, value)
    assert not matches([{"pointer": "/count", "value": 1}], {"count": 1.0})


def test_a_pointer_that_doesnt_resolve_doesnt_match() -> None:
    assert not matches([{"pointer": "/missing", "value": None}], EVENT)
    assert not matches([{"pointer": "/tags/5", "value": "a"}], EVENT)


def test_a_valid_filter_is_kept_as_given() -> None:
    given = [{"pointer": "/type", "value": "ap_down"}, {"pointer": "/n", "value": -3}, {"pointer": "/x", "value": None}]
    assert validated(given) == given
    assert validated([]) == []


@pytest.mark.parametrize(
    "given",
    [
        "not a list",
        [{"pointer": "/a", "value": 1}] * 9,
        [{"pointer": "a", "value": 1}],  # not a pointer
        [{"pointer": "/" + "a" * 256, "value": 1}],
        [{"pointer": "/a", "value": 1.5}],
        [{"pointer": "/a", "value": {"b": 1}}],
        [{"pointer": "/a", "value": [1]}],
        [{"pointer": "/a", "value": "x" * 1025}],
        [{"pointer": "/a", "value": 10**30}],  # past a 64-bit integer
        [{"pointer": "/a"}],
        [{"pointer": "/a", "value": 1, "op": "ne"}],
        ["/a"],
    ],
)
def test_an_invalid_filter_is_refused_with_a_reason(given) -> None:
    with pytest.raises(FilterError):
        validated(given)
