# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest

from dewpoint.engine.schema_refs import ref_problems

TREE = {
    "type": "object",
    "properties": {"root": {"$ref": "#/$defs/Node"}},
    "$defs": {
        "Node": {"type": "object", "properties": {"children": {"type": "array", "items": {"$ref": "#/$defs/Node"}}}}
    },
}


def test_local_and_structurally_recursive_refs_are_fine() -> None:
    assert ref_problems(TREE) == []
    assert ref_problems({"type": "object", "properties": {"title": {"type": "string"}}}) == []


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "default": {"$ref": "literal data"}},
        {"type": "object", "properties": {"x": {"const": {"$id": "not-an-id"}}}},
        {"type": "array", "items": {"enum": [{"$ref": "#/nowhere"}]}},
        {"type": "string", "examples": [{"$id": "x", "$ref": "y"}]},
        {"type": "object", "x-dewpoint-note": {"$ref": "vendor data"}},
        {"type": "object", "properties": {"$ref": {"type": "string"}, "$id": {"type": "string"}}},  # property names
        {"type": "object", "dependentRequired": {"$ref": ["x"]}},
    ],
)
def test_data_positions_are_never_treated_as_schemas(schema: dict[str, Any]) -> None:
    assert ref_problems(schema) == []


def test_every_schema_position_is_checked() -> None:
    bad = {"$ref": "https://example.com/s.json"}
    for schema in (
        {"items": bad},
        {"prefixItems": [bad]},
        {"additionalProperties": bad},
        {"patternProperties": {"^x": bad}},
        {"dependentSchemas": {"a": bad}},
        {"if": bad},
        {"unevaluatedProperties": bad},
        {"$defs": {"A": bad}},
    ):
        assert ref_problems(schema), schema


@pytest.mark.parametrize(
    ("schema", "fragment"),
    [
        ({"properties": {"x": {"$ref": "#/$defs/Missing"}}}, "must name an entry"),
        ({"properties": {"x": {"$ref": "https://example.com/s.json"}}}, "must name an entry"),
        ({"properties": {"x": {"$ref": "#"}}}, "must name an entry"),
        ({"$id": "https://example.com/s.json", "type": "object"}, "`$id` isn't supported"),
        ({"$defs": {"A": {"$dynamicAnchor": "a"}}}, "`$dynamicAnchor` isn't supported"),
        ({"$defs": {"A": {"$ref": "#/$defs/B"}, "B": {"$ref": "#/$defs/A"}}}, "cycle"),
        ({"$defs": {"A": {"allOf": [{"$ref": "#/$defs/A"}]}}}, "cycle"),
        ({"$defs": {"A": {"anyOf": [{"type": "string"}, {"not": {"$ref": "#/$defs/A"}}]}}}, "cycle"),
    ],
)
def test_unsupported_references_are_reported(schema: dict[str, Any], fragment: str) -> None:
    problems = ref_problems(schema)
    assert problems and any(fragment in p for p in problems), problems
