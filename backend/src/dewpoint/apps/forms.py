# SPDX-License-Identifier: Apache-2.0
"""A start form's fields (engine 2b spec §7.7): the typed top-level fields of a version's `input_schema`, for the UI.
A sensitive field shows its type and whether it's required, never a value the schema holds for it: its default and
its enum are masked. Publish refuses both now (§3.8, #32), but versions published before that are immutable and may
still hold them. A picker (`x-dewpoint-picker`, plugins-3 D19: a node's options field and a connection, checked at
publish) is shown as published, with the words of the list it reads (`x-list` on the node's field, the 4f-3 design
§4.4); its choices come from `POST …/input-options`. A CSV declaration (§8.1) is described with its columns: a
sensitive one has no default and no values to show, since publish refuses them.

A draft saves any input schema its graph parses, and publish takes a boolean property (valid JSON Schema): the form
gives the fields it can read and leaves the rest out, never failing (the 4f-3 design §4.3)."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.plugins import registry

SENSITIVE = "x-sensitive"
PICKER = "x-dewpoint-picker"
_PICKER_KEYS = frozenset({"node", "field", "connection"})
_LIST_KEYS = frozenset({"plugin", "title", "noun"})


def _properties(schema: Any) -> Mapping[str, Any]:
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    return props if isinstance(props, Mapping) else {}


def _picker(prop: Mapping[str, Any]) -> Mapping[str, str] | None:
    """A picker as the validator takes it: exactly its node, field and connection, each a string."""
    picker = prop.get(PICKER)
    if isinstance(picker, Mapping) and set(picker) == _PICKER_KEYS and all(isinstance(v, str) for v in picker.values()):
        return picker
    return None


def picker_nodes(schema: Any) -> list[str]:
    """The node type versions a form's complete pickers name, each a ref the registry can read (`type@version`)."""
    refs = {p["node"] for prop in _properties(schema).values() if isinstance(prop, Mapping) and (p := _picker(prop))}
    return sorted(r for r in refs if r.rpartition("@")[0] and r.rpartition("@")[2].isdigit())


async def held_manifests(s: AsyncSession, schema: Any) -> dict[str, Mapping[str, Any]]:
    """The manifests of the node types a form's pickers name that this server holds and hasn't retired."""
    rows = await registry.load_node_types(s, picker_nodes(schema))
    return {r.ref: r.manifest for r in rows if r.state != "retired"}


def _listed(manifest: Mapping[str, Any] | None, field: str) -> dict[str, str] | None:
    props = _properties((manifest or {}).get("config_schema"))
    entry = props.get(field)
    listed = entry.get("x-list") if isinstance(entry, Mapping) else None
    if isinstance(listed, Mapping) and set(listed) == _LIST_KEYS and all(isinstance(v, str) for v in listed.values()):
        return dict(listed)
    return None


def form_fields(schema: Any, manifests: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """The form's fields; a picker's `list` from `manifests` (by node ref), null for a node type it doesn't hold."""
    raw = schema.get("required") if isinstance(schema, Mapping) else None
    required = {n for n in raw if isinstance(n, str)} if isinstance(raw, list) else set()
    fields: list[dict[str, Any]] = []
    for name, prop in _properties(schema).items():
        if not isinstance(prop, Mapping):
            continue
        sensitive = bool(prop.get(SENSITIVE))
        field: dict[str, Any] = {"name": name, "type": prop.get("type"), "required": name in required,
                                 "sensitive": sensitive}  # fmt: skip
        for key in ("title", "description"):
            if isinstance(prop.get(key), str):
                field[key] = prop[key]
        if sensitive:
            if "default" in prop:
                field["default_masked"] = True
            if "enum" in prop:
                field["enum_masked"] = True
        else:
            if isinstance(prop.get("enum"), list):
                field["enum"] = prop["enum"]
            if "default" in prop:
                field["default"] = prop["default"]
        if picker := _picker(prop):
            field["picker"] = {**picker, "list": _listed((manifests or {}).get(picker["node"]), picker["field"])}
        fields.append(field)
    return fields


def picked_names(
    schema: Any, input: Mapping[str, Any], names: Mapping[str, Mapping[str, str]]
) -> dict[str, dict[str, str]]:
    """The names a start form picked that fit (the 4f-3 design §4.1): each for a picker of `schema`, not sensitive,
    whose `input` holds the very string it was picked for. The others are dropped: a name is display only."""
    props = _properties(schema)
    kept: dict[str, dict[str, str]] = {}
    for field, name in names.items():
        prop = props.get(field)
        if not isinstance(prop, Mapping) or _picker(prop) is None or prop.get(SENSITIVE):
            continue
        if isinstance(input.get(field), str) and input[field] == name["value"]:
            kept[field] = {"value": name["value"], "label": name["label"]}
    return kept


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
