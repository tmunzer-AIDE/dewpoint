# SPDX-License-Identifier: Apache-2.0
"""Simulate's fixtures, redesigned (the owner's ruling on the 3b-1 checkpoint): built from the schema, every declared
property filled to a bounded depth and within a size budget, with the OAS example's values laid over where they fit,
each part of the example checked and the schema-built part kept where it doesn't; for curated and generic nodes alike.
The OAS's examples are incomplete and may be outdated, so the schema gives the shape and the example only values."""

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from dewpoint.plugins.mist import PLUGIN, oas, policy
from dewpoint.plugins.mist.api import answer_fixture
from dewpoint.plugins.mist.fixtures import BUDGET, FixtureUnavailable, built, fixture
from dewpoint.plugins.mist.nodes import MistOperation, fixture_of
from dewpoint.sdk import node_manifest

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "a": {"type": "string"},
        "n": {"type": ["integer", "null"]},
        "d": {"type": "string", "default": "on"},
        "b": {"type": "object", "properties": {"c": {"type": "integer"}, "e": {"type": "boolean"}}},
        "l": {"type": "array", "items": {"$ref": "#/$defs/x"}},
        "u": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
    },
    "required": ["a"],
    "$defs": {"x": {"type": "object", "properties": {"y": {"type": "boolean"}, "z": {"type": "string"}}}},
}


def test_every_declared_property_is_filled() -> None:
    assert built(SCHEMA) == {
        "a": "", "n": 0, "d": "on", "b": {"c": 0, "e": False}, "l": [{"y": False, "z": ""}], "u": "",
    }  # fmt: skip


def test_a_recursive_schema_ends_at_the_depth_bound_and_stays_valid() -> None:
    node = {"type": "object", "properties": {"child": {"$ref": "#/$defs/n"}, "v": {"type": "string"}}}
    tree = {"$ref": "#/$defs/n", "$defs": {"n": node}}
    value = built(tree)
    depth = 0
    while isinstance(value, dict) and "child" in value:
        value, depth = value["child"], depth + 1
    assert 0 < depth <= 8
    assert Draft202012Validator(tree).is_valid(built(tree))


def test_the_example_lays_its_values_over_where_they_fit() -> None:
    example = {"a": "real", "b": {"c": "not an integer", "e": True}, "l": [{"y": True}, {"z": "two"}], "extra": 1}
    value, source = fixture(SCHEMA, example)
    assert source == "example"
    assert value == {
        "a": "real", "n": 0, "d": "on", "b": {"c": 0, "e": True}, "u": "", "extra": 1,
        "l": [{"y": True, "z": ""}, {"y": False, "z": "two"}],
    }  # fmt: skip
    assert Draft202012Validator(SCHEMA).is_valid(value)


def test_an_example_that_fits_nowhere_leaves_the_schemas_value() -> None:
    assert fixture(SCHEMA, ["not", "an", "object"]) == (built(SCHEMA), "schema")
    assert fixture(SCHEMA, None) == (built(SCHEMA), "schema")


def curated() -> list[type[MistOperation]]:
    return [n for n in PLUGIN.nodes if issubclass(n, MistOperation)]


def test_every_curated_fixture_is_valid_complete_and_within_budget() -> None:
    sources: dict[str, int] = {}
    for n in curated():
        value, source = fixture_of(n)
        assert list(Draft202012Validator(node_manifest(n)["output_schema"]).iter_errors(value)) == [], n.type
        assert len(json.dumps(value)) <= BUDGET, n.type
        sources[source] = sources.get(source, 0) + 1
    assert sources == {"example": 182, "schema": 39, "fixed": 41}


def test_a_fixture_fills_what_the_example_leaves_out() -> None:
    wlan = next(n for n in curated() if n.type == "mist.org_wlans.get")
    value, _ = fixture_of(wlan)
    declared = set(node_manifest(wlan)["output_schema"]["properties"])
    assert declared <= set(value)  # the OAS's example for a WLAN lists a few fields; the fixture has them all


@pytest.mark.parametrize("node", ["mist.api.read", "mist.api.write"])
def test_every_generic_fixture_fits_its_operations_answer(node: str) -> None:
    doc = oas.document()
    for op_id, entry in policy.load().entries.items():
        if entry.state != "allowed" or node not in entry.nodes:
            continue
        value = answer_fixture(op_id)
        found = oas.answer(doc, oas.operations()[op_id])
        if found is None:
            assert value is None, op_id
            continue
        assert value is not None and len(json.dumps(value)) <= BUDGET, op_id


def test_a_fixture_past_its_budget_is_built_shallower_and_stays_valid() -> None:
    value, source = fixture(SCHEMA, None, budget=40)
    assert source == "schema" and len(json.dumps(value)) <= 40 and value == {"a": ""}  # only the required field
    assert Draft202012Validator(SCHEMA).is_valid(value)


OVERLAPPING = {
    "type": "object",
    "allOf": [
        {"type": "object", "properties": {"a": {"type": "string"}}},
        {"type": "object", "properties": {"a": {"type": "string", "minLength": 2}}},
    ],
}
IMPOSSIBLE = {
    "type": "object",
    "allOf": [
        {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
        {"type": "object", "properties": {"a": {"type": "integer"}}},
    ],
}


def test_an_overlapping_all_of_falls_back_to_a_value_the_schema_accepts() -> None:
    """The owner's review of the redesign: a merged `allOf` can break one branch; every return is checked."""
    value, source = fixture(OVERLAPPING, None)
    assert Draft202012Validator(OVERLAPPING).is_valid(value) and source == "schema"


def test_a_default_that_cant_shrink_gives_way_to_the_types_empty_value() -> None:
    big = {"type": "string", "default": "x" * 100_000}
    assert fixture(big, None, budget=1_000) == ("", "schema")
    nested = {"type": "object", "properties": {"s": big}, "required": ["s"]}
    value, _ = fixture(nested, None, budget=1_000)
    assert value == {"s": ""} and Draft202012Validator(nested).is_valid(value)


def test_a_schema_no_value_within_budget_satisfies_has_no_fixture() -> None:
    with pytest.raises(FixtureUnavailable):
        fixture(IMPOSSIBLE, None)
    with pytest.raises(FixtureUnavailable):
        fixture({"type": "string", "minLength": 2000}, None, budget=1_000)


@pytest.mark.parametrize("example", [None, {"a": "ok"}, {"a": 3}, {"a": "x" * 100_000}, "wrong"])
@pytest.mark.parametrize("schema", [SCHEMA, OVERLAPPING])
def test_every_return_is_valid_and_within_budget(schema: dict[str, Any], example: Any) -> None:
    value, _ = fixture(schema, example, budget=4_096)
    assert Draft202012Validator(schema).is_valid(value) and len(json.dumps(value)) <= 4_096


async def test_a_node_without_a_fixture_cant_be_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    from dewpoint.plugins.mist import fixtures as module
    from dewpoint.plugins.mist import nodes

    def none(*args: Any, **kwargs: Any) -> Any:
        raise FixtureUnavailable()

    monkeypatch.setattr(module, "fixture", none)
    monkeypatch.setattr(nodes, "_FIXTURES", {})
    kind = next(n for n in curated() if n.type == "mist.org_wlans.get")
    value = kind.Config.model_validate(
        {"connection": "6a1d6e2f-3c4b-4a5d-9e8f-0123456789ab", "wlan_id": "7b2c4d6e-8f10-4a2b-9c3d-4e5f6a7b8c9d"}
    )
    with pytest.raises(NotImplementedError):  # the runtime's `simulation_unavailable`
        await kind().simulate(None, value)  # type: ignore[arg-type]
