# SPDX-License-Identifier: Apache-2.0
"""Where a value written at a position of a schema's instances may land at a part the schema marks sensitive (engine
2b spec §3.8, issue #79), navigated as `is_marked` navigates: a tuple position, a union's branches, a pattern,
`additionalProperties` and a local `$ref` are followed, never one resolved subschema."""

from typing import Any

import pytest

from dewpoint.engine.sensitive import (
    ITEM,
    VALUE,
    is_marked,
    keys_marked,
    marked_positions,
    marked_positions_at,
    may_hold_marked,
)

SECRET = {"type": "string", "x-sensitive": True}
PW = {"type": "object", "properties": {"pw": SECRET, "user": {"type": "string"}}}
KEYS = {"type": "object", "propertyNames": {"x-sensitive": True}}


def under(schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": {"x": schema}}


@pytest.mark.parametrize(
    ("schema", "path", "expected"),
    [
        (under(PW), ("x",), True),  # a property under it
        (under({"type": "object", "patternProperties": {"^p": SECRET}}), ("x",), True),
        (under({"type": "object", "additionalProperties": SECRET}), ("x",), True),
        (under({"type": "array", "items": SECRET}), ("x",), True),
        (under({"type": "array", "prefixItems": [SECRET]}), ("x",), True),
        (under({"anyOf": [{"type": "null"}, PW]}), ("x",), True),
        ({**under({"$ref": "#/$defs/pw"}), "$defs": {"pw": PW}}, ("x",), True),
        ({**under({"type": "object"}), "$defs": {"unused": SECRET}}, ("x",), False),  # a definition nothing reaches
        (under(KEYS), ("x",), True),
        (under({"type": "string"}), ("x",), False),
        (under({"type": "string", "not": SECRET}), ("x",), False),  # `not` marks nothing
        (under({**PW, "x-sensitive": True}), ("x", "user"), True),  # under a part marked whole
        (under({"type": "array", "prefixItems": [PW]}), ("x", 0), True),  # through a tuple position
        (under({"anyOf": [{"type": "object", "properties": {"y": PW}}, {"type": "object"}]}), ("x", "y"), True),
        (under({"type": "array", "prefixItems": [{"type": "string"}, PW]}), ("x", 0), False),
    ],
)  # fmt: skip
def test_may_hold_marked(schema: dict[str, Any], path: tuple[str | int, ...], expected: bool) -> None:
    assert may_hold_marked(schema, path) is expected


@pytest.mark.parametrize(
    ("schema", "path", "expected"),
    [
        (under(KEYS), ("x",), True),
        (under(PW), ("x",), False),  # a key whose value is marked isn't sensitive for that
        (under({**PW, "x-sensitive": True}), ("x",), False),  # nor one of a map at a marked position
        (under({"type": "array", "prefixItems": [KEYS]}), ("x", 0), True),
        (under({"type": "array", "items": KEYS}), ("x",), False),  # its elements' keys, not its own
    ],
)  # fmt: skip
def test_keys_marked(schema: dict[str, Any], path: tuple[str | int, ...], expected: bool) -> None:
    assert keys_marked(schema, path) is expected


TUPLE_SECOND = under({"type": "array", "prefixItems": [{"type": "string"}, SECRET]})
EITHER = under({"properties": {"passphrase": SECRET}, "items": {"type": "integer"}})  # an object or a list


@pytest.mark.parametrize(
    ("schema", "path", "expected"),
    [
        (under({"type": "array", "items": SECRET}), ("x", ITEM), True),
        (TUPLE_SECOND, ("x", ITEM), True),  # any element may be the second
        (under({"type": "array", "items": PW}), ("x", ITEM, "user"), False),
        (under({"type": "array", "items": PW}), ("x", ITEM, "pw"), True),
        (under({"type": "array", "items": {"type": "string"}}), ("x", ITEM), False),
        (under({"type": "object", "additionalProperties": SECRET}), ("x", VALUE), True),
        (under({"type": "object", "patternProperties": {"^p": SECRET}}), ("x", VALUE), True),
        (under({"type": "object", "properties": {"a": {"type": "string"}, "b": SECRET}}), ("x", VALUE), True),
        (under({"type": "object", "properties": {"a": {"type": "string"}}}), ("x", VALUE), False),
        (EITHER, ("x", ITEM), False),  # an element follows `items`, never a property (the fresh review's Mist bodies)
        (EITHER, ("x", VALUE), True),
    ],
)  # fmt: skip
def test_is_marked_at_any_element_or_value(schema: dict[str, Any], path: tuple[Any, ...], expected: bool) -> None:
    """`ITEM`: any element of a list, whose index a concatenation or a macro lost; `VALUE`: any value of a map, under
    a key chosen at run time. Marked if any of them may be."""
    assert is_marked(schema, path) is expected


def test_keys_and_parts_at_any_element() -> None:
    assert keys_marked(under({"type": "array", "items": KEYS}), ("x", ITEM)) is True
    assert keys_marked(under({"type": "array", "items": PW}), ("x", ITEM)) is False
    assert may_hold_marked(under({"type": "array", "items": PW}), ("x", ITEM)) is True
    assert may_hold_marked(under({"type": "array", "items": {"type": "object"}}), ("x", ITEM)) is False


@pytest.mark.parametrize(
    "schema",
    [
        under({"type": "array", "prefixItems": [PW]}),
        under({"anyOf": [{"type": "object", "properties": {"y": PW}}, {"type": "object"}]}),
    ],
)
def test_marked_positions_at_a_tuple_position_or_in_a_union(schema: dict[str, Any]) -> None:
    path: tuple[str | int, ...] = ("x", 0) if "anyOf" not in schema["properties"]["x"] else ("x", "y")
    assert marked_positions_at({"pw": "lit-value", "user": "ops"}, schema, path) == ["/pw"]
    assert marked_positions_at({"user": "ops"}, schema, path) == []


def test_a_written_key_counts_where_keys_are_marked_even_beside_references() -> None:
    """Ruling 7: holes stand for values, never for the keys written beside them. An object made only of references at
    a position marked whole still writes nothing: its keys are structure."""
    assert marked_positions({"k3y-value": None}, KEYS, holes={"/k3y-value"}) == [""]
    assert marked_positions({"k3y-value": 1}, KEYS) == [""]
    assert marked_positions({"user": None, "pw": None}, {**PW, "x-sensitive": True}, holes={"/user", "/pw"}) == []
