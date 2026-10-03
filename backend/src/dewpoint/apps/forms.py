# SPDX-License-Identifier: Apache-2.0
"""A start form's fields (engine 2b spec §7.7): the typed top-level fields of a version's `input_schema`, for the UI.
A sensitive field shows its type and whether it's required, never a value the schema holds for it: its default and
its enum are masked (publish refuses a sensitive literal anyway, §3.8). `x-dewpoint-picker` is passed through for
sub-project 3's pickers."""

from collections.abc import Mapping
from typing import Any

SENSITIVE = "x-sensitive"
PICKER = "x-dewpoint-picker"


def form_fields(schema: Mapping[str, Any]) -> list[dict[str, Any]]:
    required = set(schema.get("required") or ())
    fields: list[dict[str, Any]] = []
    for name, prop in (schema.get("properties") or {}).items():
        sensitive = bool(prop.get(SENSITIVE))
        field: dict[str, Any] = {"name": name, "type": prop.get("type"), "required": name in required,
                                 "sensitive": sensitive}  # fmt: skip
        for key in ("title", "description"):
            if key in prop:
                field[key] = prop[key]
        if sensitive:
            if "default" in prop:
                field["default_masked"] = True
            if "enum" in prop:
                field["enum_masked"] = True
        else:
            for key in ("enum", "default"):
                if key in prop:
                    field[key] = prop[key]
        if PICKER in prop:
            field["picker"] = prop[PICKER]
        fields.append(field)
    return fields
