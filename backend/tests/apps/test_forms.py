# SPDX-License-Identifier: Apache-2.0
"""A start form's fields (engine 2b spec §7.7): a sensitive field never shows a value its schema holds."""

from dewpoint.apps.forms import form_fields


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
