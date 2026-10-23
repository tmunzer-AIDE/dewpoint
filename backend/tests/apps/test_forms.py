# SPDX-License-Identifier: Apache-2.0
"""A start form's fields (engine 2b spec §7.7): a sensitive field never shows a value its schema holds. A schema the
form can't read whole gives the fields it can (the 4f-3 design §4.3); a picker is typed with its list's words."""

from typing import Any

import pytest

from dewpoint.apps.forms import form_fields, picked_names, picker_nodes

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


def test_a_forms_fields_follow_the_schemas_order() -> None:
    """#144 item 4, option (a): the author's order, kept beside the properties (stored JSON keeps no key order); the
    fields it doesn't list follow, as stored."""
    schema = {"properties": {"b": {"type": "string"}, "a": {"type": "string"}, "c": {"type": "string"}},
              "x-dewpoint-order": ["c", "a"]}  # fmt: skip
    assert [f["name"] for f in form_fields(schema)] == ["c", "a", "b"]


@pytest.mark.parametrize(
    "order",
    [["c", "zz", "a", "c", 7, None], "c", {"c": 1}, None, []],
)
def test_an_order_that_doesnt_match_the_fields_is_read_as_far_as_it_does(order: Any) -> None:
    """Ruled: read tolerantly, never failing the form: a name that isn't a field, a repeat or anything not a name is
    passed over; an order that isn't a list is none."""
    schema = {"properties": {"b": {"type": "string"}, "a": {"type": "string"}, "c": {"type": "string"}},
              "x-dewpoint-order": order}  # fmt: skip
    expected = ["c", "a", "b"] if isinstance(order, list) and order else ["b", "a", "c"]
    assert [f["name"] for f in form_fields(schema)] == expected


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


def test_a_name_is_kept_only_for_a_picker_holding_the_value_it_was_picked_for() -> None:
    """The 4f-3 design §4.1: a picker field, not sensitive, its input the very string the name was picked for."""
    schema = {
        "properties": {
            "site": {"type": "string", "x-dewpoint-picker": PICKER},
            "secret": {"type": "string", "x-sensitive": True, "x-dewpoint-picker": PICKER},
            "plain": {"type": "string"},
        }
    }
    names = {f: {"value": "s1", "label": "Lyon DC"} for f in ("site", "secret", "plain", "gone")}
    given = {"site": "s1", "secret": "s1", "plain": "s1"}
    assert picked_names(schema, given, names) == {"site": {"value": "s1", "label": "Lyon DC"}}
    assert picked_names(schema, {"site": "s2"}, names) == {}
    assert picked_names(schema, {"site": 1}, {"site": {"value": "1", "label": "x"}}) == {}
    assert picked_names({"properties": []}, given, names) == {} and picked_names(schema, given, {}) == {}


def test_a_version_past_the_registrys_integer_is_never_looked_up() -> None:
    """The final review's M5: `@99999999999` reads as a number but no version column holds it (a 500 if asked)."""
    far, last = PICKER | {"node": "acme.sites@99999999999"}, PICKER | {"node": "acme.sites@2147483647"}
    schema = {"properties": {"a": {"type": "string", "x-dewpoint-picker": far},
                             "b": {"type": "string", "x-dewpoint-picker": last}}}  # fmt: skip
    assert picker_nodes(schema) == ["acme.sites@2147483647"]
