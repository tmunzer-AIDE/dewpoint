# SPDX-License-Identifier: Apache-2.0
"""A start form's fields (engine 2b spec §7.7): the typed top-level fields of a version's `input_schema`, for the UI.
A sensitive field shows its type and whether it's required, never a value the schema holds for it: its default and
its enum are masked. Publish refuses both now (§3.8, #32), but versions published before that are immutable and may
still hold them. A picker (`x-dewpoint-picker`, plugins-3 D19: a node's options field and a connection, checked at
publish) is shown as published; its choices come from `POST …/input-options`. A CSV declaration (§8.1) is described with its columns: a sensitive one has no default and no
values to show, since publish refuses them."""

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


def csv_form(csv: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A version's CSV declaration, as the graph document holds it, for the upload and mapping step."""
    if not csv:
        return None
    columns: list[dict[str, Any]] = []
    for c in csv["columns"]:
        column = {k: c[k] for k in ("header", "name", "type")}
        column |= {"required": bool(c.get("required")), "sensitive": bool(c.get("sensitive"))}
        if "default" in c:  # never on a sensitive column: publish refuses it (§3.8)
            column["default"] = c["default"]
        if c.get("values") is not None:  # never a sensitive column's: publish refuses them (§3.8)
            column["values"] = c["values"]
        columns.append(column)
    return {"max_rows": csv["max_rows"], "max_bytes": csv["max_bytes"], "columns": columns}
