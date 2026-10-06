# SPDX-License-Identifier: Apache-2.0
"""Start-form pickers (plugins-3 D19): a top-level string field of a workflow's input schema may name a node type's
options field and a connection, written literally, so the start form lists that node's options through that
connection. The validator checks the shape and the node; publish checks the connection and records it."""

import uuid
from typing import Any

import pytest

from dewpoint.engine.graph.validate import ValidationContext, ValidationResult, validate
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G
from tests.support.plugins.testkit import TESTKIT

CAT = catalog(PLUGIN, TESTKIT)
CONN = str(uuid.uuid4())
PICKER = {"node": "testkit.pick@1", "field": "site_id", "connection": CONN}


def check(site: dict[str, Any], *, top: dict[str, Any] | None = None) -> ValidationResult:
    g = G().node("e", "testkit.echo@1")
    g.settings = {"input_schema": {"type": "object", "properties": {"site": site}, **(top or {})}}
    return validate(g.build(), ValidationContext(catalog=CAT))


def codes(result: ValidationResult) -> list[tuple[str, str | None]]:
    return [(d.code, d.field) for d in result.diagnostics]


def test_a_picker_is_recorded_with_its_connection_and_the_types_it_may_be() -> None:
    result = check({"type": "string", "x-dewpoint-picker": PICKER})
    assert result.ok, codes(result)
    assert result.pickers == (("site", "testkit.pick@1", "site_id", uuid.UUID(CONN), ("testkit",)),)


FIELD = "/settings/input_schema/properties/site/x-dewpoint-picker"


@pytest.mark.parametrize(
    ("site", "code"),
    [
        ({"type": "string", "x-dewpoint-picker": "testkit.pick@1"}, "picker.invalid"),
        ({"type": "string", "x-dewpoint-picker": {**PICKER, "extra": 1}}, "picker.invalid"),
        ({"type": "string", "x-dewpoint-picker": {**PICKER, "connection": "not-a-uuid"}}, "picker.invalid"),
        ({"type": "string", "x-dewpoint-picker": {k: v for k, v in PICKER.items() if k != "connection"}},
         "picker.invalid"),
        ({"type": "string", "x-dewpoint-picker": {**PICKER, "node": "testkit.nothing@1"}}, "picker.unknown_node"),
        ({"type": "string", "x-dewpoint-picker": {**PICKER, "field": "note"}}, "picker.not_an_options_field"),
        ({"type": "integer", "x-dewpoint-picker": PICKER}, "picker.not_a_string"),
        ({"x-dewpoint-picker": PICKER}, "picker.not_a_string"),
    ],
)  # fmt: skip
def test_a_picker_is_checked(site: dict[str, Any], code: str) -> None:
    result = check(site)
    assert not result.ok and result.pickers == ()
    assert codes(result) == [(code, FIELD)]


def test_a_picker_is_only_a_top_level_field() -> None:
    nested = {"type": "object", "properties": {"inner": {"type": "string", "x-dewpoint-picker": PICKER}}}
    result = check(nested)
    assert [c for c, _ in codes(result)] == ["picker.not_top_level"]
    defs = check({"$ref": "#/$defs/s"}, top={"$defs": {"s": {"type": "string", "x-dewpoint-picker": PICKER}}})
    assert [c for c, _ in codes(defs)] == ["picker.not_top_level"]


def test_a_retired_node_cant_back_a_picker() -> None:
    g = G().node("e", "testkit.echo@1")
    site = {"type": "string", "x-dewpoint-picker": PICKER}
    g.settings = {"input_schema": {"type": "object", "properties": {"site": site}}}
    retired = catalog(PLUGIN, TESTKIT, states={"testkit.pick@1": "retired"})
    result = validate(g.build(), ValidationContext(catalog=retired))
    assert [c for c, _ in codes(result)] == ["picker.unknown_node"]
