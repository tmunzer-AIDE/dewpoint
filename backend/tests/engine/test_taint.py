# SPDX-License-Identifier: Apache-2.0
"""Taint shapes (engine 2b spec §4.1): which parts of a value are tainted, per path. From a schema, a position marked
`x-sensitive` is tainted, and so is one the schema doesn't declare: unknown counts as sensitive."""

from typing import Any

import pytest

from dewpoint.engine.taint import CLEAN, TAINTED, Shape, from_schema, join

SECRET = {"type": "string", "x-sensitive": True}


def obj(**props: Any) -> dict[str, Any]:
    return {"type": "object", "properties": props, "additionalProperties": False}


def test_a_closed_object_taints_only_its_sensitive_fields() -> None:
    shape = from_schema(obj(name={"type": "string"}, token=SECRET, login=obj(user={"type": "string"}, pw=SECRET)))
    assert shape.tainted  # read whole, it holds secrets
    assert not shape.at(("name",)).tainted and shape.at(("token",)) == TAINTED
    assert not shape.at(("login", "user")).tainted and shape.at(("login", "pw")).tainted
    assert shape.at(("login",)).tainted


@pytest.mark.parametrize(
    ("schema", "path"),
    [
        ({"type": "object", "properties": {"a": {"type": "string"}}}, ("extra",)),  # open: other keys may exist
        ({"type": "object", "additionalProperties": {"type": "string"}}, ("k",)),
        (obj(rows={"type": "array"}), ("rows", 3)),  # elements not declared
        ({}, ("anything",)),
        (None, ()),
    ],
)
def test_a_position_the_schema_doesnt_declare_is_tainted(schema: Any, path: tuple[Any, ...]) -> None:
    assert from_schema(schema).at(path) == TAINTED


def test_list_elements_are_tainted_field_by_field() -> None:
    shape = from_schema(obj(rows={"type": "array", "items": obj(id={"type": "integer"}, card=SECRET)}))
    assert not shape.at(("rows", 0, "id")).tainted and shape.at(("rows", 5, "card")).tainted
    assert shape.at(("rows",)).tainted  # a whole-list read is tainted when any element path is


def test_a_ref_and_a_union_with_a_sensitive_branch_taint() -> None:
    schema = {"$defs": {"S": SECRET}, **obj(a={"$ref": "#/$defs/S"}, u={"anyOf": [{"type": "string"}, SECRET]})}
    shape = from_schema(schema)
    assert shape.at(("a",)) == TAINTED and shape.at(("u",)) == TAINTED


def test_a_map_whose_keys_are_sensitive_is_tainted_whole() -> None:
    assert from_schema(obj(m={"type": "object", "propertyNames": {"x-sensitive": True}})).at(("m",)) == TAINTED


def test_shapes_join_and_round_trip_as_json() -> None:
    a = Shape(fields=(("x", TAINTED),))
    b = Shape(items=TAINTED)
    joined = join(a, b)
    assert joined.at(("x",)) == TAINTED and joined.at((0,)) == TAINTED and not joined.at(("y",)).tainted
    for shape in (CLEAN, TAINTED, joined, from_schema(obj(a=SECRET, b={"type": "integer"}))):
        assert Shape.from_json(shape.to_json()) == shape
    assert CLEAN.to_json() is False and TAINTED.to_json() is True


UNIONS_LEAVING_TOKEN_OPEN = [
    {"anyOf": [obj(token={"type": "string"}), {"type": "object"}]},
    {"oneOf": [obj(token={"type": "string"}), {"type": "object", "additionalProperties": {"type": "string"}}]},
    {"anyOf": [obj(token={"type": "string"}),
               {"type": "object", "patternProperties": {"^t": {"type": "string"}}, "additionalProperties": False}]},
]  # fmt: skip


@pytest.mark.parametrize("union", UNIONS_LEAVING_TOKEN_OPEN)
def test_a_key_one_branch_of_a_union_leaves_undeclared_is_tainted(union: dict[str, Any]) -> None:
    """A value matches one branch of a union: a key one branch declares plain may arrive through another that
    doesn't declare it (spec §3.5)."""
    assert from_schema(obj(u=union)).at(("u", "token")) == TAINTED


@pytest.mark.parametrize(
    "schema",
    [
        {**obj(a={"type": "string"}, b={"type": "string"}), "anyOf": [{"required": ["a"]}, {"required": ["b"]}]},
        {"anyOf": [obj(a={"type": "string"}), obj(a={"type": "integer"}, b={"type": "string"})]},
        {"allOf": [obj(a={"type": "string"}), {"properties": {"a": {"minLength": 1}}}]},
        {"$defs": {"A": obj(a={"type": "string"})}, "$ref": "#/$defs/A", "required": ["a"]},
    ],
)
def test_schemas_applied_together_declare_what_any_of_them_declares(schema: dict[str, Any]) -> None:
    """`allOf`, `$ref` and a union of alternatives applied together narrow a value: what one of them declares, and
    closes, stays plain."""
    assert not from_schema(schema).tainted


def test_a_pattern_neither_declares_nor_closes_a_key() -> None:
    """No regex runs at publish: a key only a pattern admits is undeclared, and a pattern may or may not govern a
    declared key, so only what it marks counts there."""
    by_pattern = {"type": "object", "patternProperties": {"^x": {"type": "string"}}, "additionalProperties": False}
    assert from_schema(by_pattern).at(("xa",)) == TAINTED
    closing = {**obj(k={"type": "object"}), "patternProperties": {"^k": {"type": "object",
                                                                         "additionalProperties": False}}}  # fmt: skip
    assert from_schema(closing).at(("k", "extra")) == TAINTED
    marking = {**obj(k={"type": "string"}), "patternProperties": {"^k": SECRET}}
    assert from_schema(marking).at(("k",)) == TAINTED
