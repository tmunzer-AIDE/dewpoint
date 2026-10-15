# SPDX-License-Identifier: Apache-2.0
"""D-s2's rules (the simulation design §7.6): a seed is prefilled only from its step's own output, and only from a
sample that is provably what the step output: nothing redacted, cut or claimed, nothing storage couldn't hold."""

import pytest

from dewpoint.apps.seed_form import _ABSENT, _at, faithful, output_of


@pytest.mark.parametrize(
    "value",
    [2, None, "ok", {"a": [1, "two", {"b": None}]}, [], {}, "nano", "information"],
)
def test_a_value_stored_as_it_was_output_is_faithful(value: object) -> None:
    assert faithful(value)


@pytest.mark.parametrize(
    "value",
    [
        "[redacted]",
        "[truncated]",
        {"a": ["[redacted]"]},
        {"$claim": "6f1c0e5e-1d3a-4c55-9a51-8f7f8d5f2c10"},  # a handle: the value itself was claimed
        {"a": {"$claim": "6f1c0e5e-1d3a-4c55-9a51-8f7f8d5f2c10", "pointer": "/x"}},
        {"$claim": "c1", "kind": "string"},  # only Dewpoint writes the key: never a value it can vouch for
        "caf�",  # storage's stand-in for NUL or a lone surrogate
        {"k�": 1},
        "nan",
        "inf",
        {"a": ["-inf"]},  # storage's name for a number JSON can't hold
    ],
)
def test_a_marked_cut_or_unstorable_value_is_never_faithful(value: object) -> None:
    assert not faithful(value)


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("/steps/a/output", ("a", [])),
        ("/steps/a/output/n", ("a", ["n"])),
        ("/steps/a/output/x~1y/z~0w", ("a", ["x/y", "z~w"])),
        ("/steps/a/error/message", None),  # an error path is typed
        ("/steps/a", None),
        ("/trigger/site", None),
        ("/vars/n", None),
        ("/item", None),
    ],
)
def test_only_a_steps_own_output_is_prefilled(pointer: str, expected: tuple[str, list[str]] | None) -> None:
    assert output_of(pointer) == expected


@pytest.mark.parametrize(
    ("output", "path", "expected"),
    [
        ({"a": {"b": [1, 2]}}, ["a", "b", "1"], 2),
        ({"a": None}, ["a"], None),
        ({"a": 1}, ["b"], _ABSENT),
        ({"a": 1}, ["a", "b"], _ABSENT),  # nothing inside a number
        ({"a": [1]}, ["a", "3"], _ABSENT),
        ("[truncated]", ["a"], "[truncated]"),  # a cut preview: the marker, never "not there"
        ({"a": {"$claim": "6f1c0e5e-1d3a-4c55-9a51-8f7f8d5f2c10"}}, ["a", "b"],
         {"$claim": "6f1c0e5e-1d3a-4c55-9a51-8f7f8d5f2c10"}),
    ],
)  # fmt: skip
def test_a_samples_value_is_read_down_its_path_never_through_a_marker(
    output: object, path: list[str], expected: object
) -> None:
    assert _at(output, path) == expected or (_at(output, path) is _ABSENT and expected is _ABSENT)
