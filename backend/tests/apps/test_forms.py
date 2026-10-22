# SPDX-License-Identifier: Apache-2.0
"""A start form's fields (engine 2b spec §7.7): a sensitive field never shows a value its schema holds. A schema the
form can't read whole gives the fields it can (the 4f-3 design §4.3); a picker is typed with its list's words."""

from typing import Any

import pytest

from dewpoint.apps.forms import form_fields, picker_nodes

SITES = {"plugin": "Acme", "title": "Org sites", "noun": "sites"}
MANIFESTS = {"acme.sites@1": {"config_schema": {"properties": {"site_id": {"type": "string", "x-list": SITES}}}}}
PICKER = {"node": "acme.sites@1", "field": "site_id", "connection": "c0ffee00-0000-4000-8000-000000000001"}


def test_a_sensitive_fields_default_and_enum_are_masked() -> None:
    """Publish refuses both now (#32), but a version published before that is immutable: its form still masks them."""
    schema = {
        "properties": {
            "token": {"type": "string", "x-sensitive": True, "default": "d3fault-secret", "enum": ["s1", "s2"]},
            "site": {"type": ["string", "null"], "default": None},
        },
        "required": ["token"],
    }
    assert form_fields(schema) == [
        {"name": "token", "type": "string", "required": True, "sensitive": True, "default_masked": True,
         "enum_masked": True},
        {"name": "site", "type": ["string", "null"], "required": False, "sensitive": False, "default": None},
    ]  # fmt: skip
    assert "d3fault-secret" not in str(form_fields(schema)) and "s1" not in str(form_fields(schema))


def test_a_schema_without_fields_has_an_empty_form() -> None:
    assert form_fields({}) == [] and form_fields({"type": "object"}) == []


@pytest.mark.parametrize("schema", [{"properties": ["site"]}, {"properties": "site"}, [], "schema", None])
def test_properties_of_another_shape_give_an_empty_form(schema: Any) -> None:
    assert form_fields(schema) == []


def test_a_schema_read_in_part_gives_the_fields_it_can() -> None:
    """A boolean property passes publish (valid JSON Schema), so a published version can hold one."""
    schema = {
        "properties": {
            "flag": True,
            "odd": ["x"],
            "site": {"type": "string", "title": 3, "description": ["d"], "enum": "abc", "default": "lyon"},
        },
        "required": [{"x": 1}, "site", 7],
    }
    assert form_fields(schema) == [
        {"name": "site", "type": "string", "required": True, "sensitive": False, "default": "lyon"},
    ]
    assert form_fields({"properties": {"a": {"type": "string"}}, "required": 3})[0]["required"] is False


def test_a_picker_is_typed_with_its_lists_words() -> None:
    schema = {"properties": {"site": {"type": "string", "x-dewpoint-picker": PICKER}}}
    assert form_fields(schema, MANIFESTS)[0]["picker"] == PICKER | {"list": SITES}
    assert form_fields(schema)[0]["picker"] == PICKER | {"list": None}  # a node type this server doesn't hold


@pytest.mark.parametrize(
    "picker",
    [
        "acme.sites@1",
        {"node": "acme.sites@1", "field": "site_id"},
        PICKER | {"field": 7},
        PICKER | {"extra": "x"},
        None,
    ],
)
def test_a_picker_that_isnt_three_strings_is_left_out(picker: Any) -> None:
    [field] = form_fields({"properties": {"site": {"type": "string", "x-dewpoint-picker": picker}}}, MANIFESTS)
    assert "picker" not in field and field["name"] == "site"


def test_a_list_that_isnt_three_strings_says_nothing() -> None:
    bad = {"acme.sites@1": {"config_schema": {"properties": {"site_id": {"x-list": {"title": 1}}}}}}
    schema = {"properties": {"site": {"type": "string", "x-dewpoint-picker": PICKER}}}
    assert form_fields(schema, bad)[0]["picker"]["list"] is None


def test_the_nodes_a_form_needs_are_its_complete_pickers_whose_ref_reads() -> None:
    schema = {
        "properties": {
            "a": {"type": "string", "x-dewpoint-picker": PICKER},
            "b": {"type": "string", "x-dewpoint-picker": PICKER | {"node": "acme.sites"}},  # no version: unreadable
            "c": {"type": "string", "x-dewpoint-picker": {"node": "acme.other@2"}},
            "d": True,
        }
    }
    assert picker_nodes(schema) == ["acme.sites@1"]
    assert picker_nodes({"properties": []}) == [] and picker_nodes(None) == []
