# SPDX-License-Identifier: Apache-2.0
"""The trigger schema (engine 2b spec §8.1): one pure function of a version's settings, its `input_schema` plus, for a
version that declares a CSV, `rows` (closed row objects, sensitive columns marked) and `row_count`. Publish types,
taints and checks every `trigger.*` read against it. `rows` and `row_count` are reserved: publish refuses them as input
properties, CSV or not, and a version declaring a CSV can't be a sub-flow's or a failure handler's target, since only a
CSV upload supplies its rows."""

import copy
import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from dewpoint.engine.graph.csv import trigger_schema
from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, ValidationResult, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
ECHO, LOOP, RUN = "testkit.echo@1", "flow.loop@1", "flow.run_workflow@1"
INPUT = {
    "type": "object",
    "properties": {"note": {"type": "string"}},
    "required": ["note"],
    "additionalProperties": False,
}
CSV = {
    "columns": [
        {"header": "Site", "name": "site", "type": "string", "required": True},
        {"header": "VLAN", "name": "vlan", "type": "integer", "default": 1},
        {"header": "Kind", "name": "kind", "type": "enum", "values": ["ap", "switch"]},
        {"header": "MAC", "name": "mac", "type": "mac"},
        {"header": "PSK", "name": "psk", "type": "string", "required": True, "sensitive": True},
    ],
    "max_rows": 500,
}
W, V = uuid.uuid4(), uuid.uuid4()


def check(g: G, **ctx: Any) -> ValidationResult:
    return validate(g.build(), ValidationContext(catalog=CAT, **ctx))


def codes(g: G, **ctx: Any) -> list[tuple[str, str | None]]:
    return [(d.code, d.field) for d in check(g, **ctx).diagnostics]


def with_csv(g: G) -> G:
    g.settings = {"input_schema": INPUT, "csv": CSV}
    return g


def loop(*body: tuple[str, Any]) -> G:
    g = G().node("l", LOOP, {"items": ref("trigger.rows")})
    for key, value in body:
        g.node(key, ECHO, {"value": value}).edge("l", key, "body")
    return with_csv(g)


def test_without_a_csv_the_trigger_schema_is_the_input_schema() -> None:
    assert trigger_schema({"input_schema": INPUT}) == INPUT
    assert trigger_schema({}) == {"type": "object"}


def test_a_csv_adds_closed_typed_rows_and_their_public_count() -> None:
    before = copy.deepcopy(INPUT)
    schema = trigger_schema({"input_schema": INPUT, "csv": CSV})
    assert INPUT == before  # the settings are never changed
    assert schema["required"] == ["note", "rows", "row_count"]
    assert schema["properties"]["note"] == {"type": "string"}
    assert schema["properties"]["row_count"] == {"type": "integer", "minimum": 0, "maximum": 500}
    assert schema["properties"]["rows"] == {
        "type": "array",
        "maxItems": 500,
        "items": {
            "type": "object",
            "properties": {
                "site": {"type": "string", "title": "Site"},
                "vlan": {"type": "integer", "title": "VLAN", "default": 1},
                "kind": {"type": "string", "title": "Kind", "enum": ["ap", "switch"]},
                "mac": {"type": "string", "title": "MAC", "format": "mac"},
                "psk": {"type": "string", "title": "PSK", "x-sensitive": True},
            },
            "required": ["site", "vlan", "psk"],  # a column with a default is always filled in
            "additionalProperties": False,
        },
    }


def test_publish_types_the_rows_their_count_and_each_item() -> None:
    assert codes(loop(("a", ref("item.vlan")), ("b", cel("item.site + ':' + trigger.note")))) == []
    assert codes(with_csv(G().node("a", ECHO, {"value": cel("trigger.row_count > 0")}))) == []
    assert [c for c, _ in codes(loop(("a", ref("item.nope"))))] == ["ref.unknown_field"]
    assert [c for c, _ in codes(loop(("a", ref("item.mac"))))] == ["ref.conditional"]  # an optional column


def test_a_sensitive_column_taints_its_cells_and_nothing_else() -> None:
    result = check(loop(("a", ref("item.psk")), ("b", ref("item.site")), ("c", cel("trigger.row_count"))))
    assert result.ok, result.diagnostics
    # the loop reads the rows whole, so its `items` is tainted (§4.1); their length is public (§4.3)
    assert {(n, f) for n, f in result.tainted_sites} == {(str(nid("a")), "/value"), (str(nid("l")), "/items")}


@pytest.mark.parametrize("name", ["rows", "row_count"])
@pytest.mark.parametrize("csv", [False, True])
def test_rows_and_row_count_are_reserved_input_properties(name: str, csv: bool) -> None:
    g = G().node("a", ECHO, {"value": 1})
    g.settings = {"input_schema": {"type": "object", "properties": {name: {"type": "integer"}}}}
    if csv:
        g.settings["csv"] = CSV
    assert codes(g) == [("settings.reserved_name", f"/settings/input_schema/properties/{name}")]


def csv_child(declares_csv: bool) -> SubflowInfo:
    return SubflowInfo(W, V, {"type": "object"}, {"type": "object", "properties": {}}, {}, declares_csv=declares_csv)


def test_a_version_declaring_a_csv_is_no_sub_flows_target() -> None:
    g = G().node("r", RUN, {"workflow_id": str(W), "input": {}})
    assert codes(g, subflows={W: csv_child(False)}) == []
    assert codes(g, subflows={W: csv_child(True)}) == [("subflow.csv_target", "/workflow_id")]


def test_a_version_declaring_a_csv_is_no_failure_handler() -> None:
    g = G().node("a", ECHO, {"value": 1})
    g.settings = {"failure_handler": str(W)}
    assert codes(g, subflows={W: csv_child(False)}) == []
    assert codes(g, subflows={W: csv_child(True)}) == [("subflow.csv_target", "/settings/failure_handler")]


CLOSED = {"properties": {"note": {"type": "string"}}, "additionalProperties": False}


@pytest.mark.parametrize(
    ("root", "keywords"),
    [
        ({"allOf": [CLOSED]}, "allOf"),  # the owner's reproduction: a closed branch refuses `rows`
        ({"anyOf": [CLOSED]}, "anyOf"),
        ({"oneOf": [CLOSED]}, "oneOf"),
        ({"not": {"required": ["rows"]}}, "not"),
        ({"if": {"required": ["note"]}, "then": CLOSED}, "if then"),
        ({"$ref": "#/$defs/closed", "$defs": {"closed": CLOSED}}, "$ref"),
        ({"unevaluatedProperties": False}, "unevaluatedProperties"),
        ({"propertyNames": {"maxLength": 3}}, "propertyNames"),
        ({"maxProperties": 1}, "maxProperties"),
        ({"dependentRequired": {"rows": ["note"]}}, "dependentRequired"),
        ({"x-sensitive": True}, "x-sensitive"),  # would taint the count that's public
    ],
)
def test_a_csv_needs_an_input_schema_that_cant_refuse_its_rows(root: dict[str, Any], keywords: str) -> None:
    """Publish refuses a CSV whose input schema could refuse the generated `rows` and `row_count`, rather than
    publish a workflow no start can satisfy: at its root, only keywords that leave the two keys free."""
    g = G().node("a", ECHO, {"value": 1})
    g.settings = {"input_schema": {"type": "object", **root}}
    assert codes(g) == []  # without a CSV, it's an ordinary schema
    g.settings["csv"] = CSV
    assert codes(g) == [("csv.input_schema", f"/settings/input_schema/{k}") for k in keywords.split()]


ROW = {"site": "paris", "vlan": 1, "psk": "s3cret"}


@pytest.mark.parametrize(
    "root",
    [
        {},
        {"properties": {"note": {"type": "string"}}, "required": ["note"], "additionalProperties": False},
        {"properties": {"note": {"type": "string"}}, "additionalProperties": {"type": "string"}},
        {"title": "T", "description": "D", "$defs": {"s": {"type": "string"}},
         "properties": {"note": {"$ref": "#/$defs/s"}}, "additionalProperties": False},
    ],
)  # fmt: skip
def test_every_input_schema_a_csv_accepts_admits_its_rows(root: dict[str, Any]) -> None:
    """The keywords a CSV's input schema may hold at its root never refuse `rows` and `row_count`: the trigger schema
    accepts the input with the rows admission builds."""
    g = G().node("a", ECHO, {"value": 1})
    g.settings = {"input_schema": {"type": "object", **root}, "csv": CSV}
    assert codes(g) == []
    schema = trigger_schema(g.build().settings.model_dump(mode="json"))
    assert Draft202012Validator(schema).is_valid({"note": "n", "rows": [ROW], "row_count": 1})
