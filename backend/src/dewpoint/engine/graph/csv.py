# SPDX-License-Identifier: Apache-2.0
"""A workflow's CSV input (engine 2b spec §8.1): the column types a declaration may use, the platform's caps, and each
type's canonical value. A cell is converted to its column's canonical value once, by admission; a declared default
must already be one, so the version holds exactly what a run would."""

import ipaddress
import math
import re
from collections.abc import Mapping
from typing import Any, Literal

CsvType = Literal["string", "integer", "number", "boolean", "mac", "ip", "cidr", "enum"]
MAX_ROWS = 10_000  # the platform's caps; a declaration may lower them, never raise them
MAX_BYTES = 5 * 1024 * 1024
INT_MIN, INT_MAX = -(2**63), 2**63 - 1  # CEL's int
RESERVED = ("rows", "row_count")  # a trigger's: only admission writes them, from a CSV upload
# The keywords a CSV's input schema may hold at its root: none can refuse the `rows` and `row_count` the trigger
# schema adds there (`additionalProperties` skips declared properties). Any other (a closed `allOf` branch, a `$ref`,
# `propertyNames`, `maxProperties`, `x-sensitive`, ...) could refuse them or taint the public count.
INPUT_ROOT = frozenset(
    {"type", "properties", "required", "additionalProperties", "$defs", "$schema", "$comment"}
    | {"title", "description", "examples", "default", "deprecated", "readOnly", "writeOnly"}
)
_JSON_TYPES = {"integer": "integer", "number": "number", "boolean": "boolean"}  # the others are strings
_JSON_TYPES.update({t: "string" for t in ("string", "mac", "ip", "cidr", "enum")})

_MAC = re.compile(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}")  # the canonical form: lowercase, colon-separated
_MAC_FORMS = (
    re.compile(r"[0-9a-f]{2}([:-])[0-9a-f]{2}(?:\1[0-9a-f]{2}){4}"),  # aa:bb:cc:dd:ee:ff, aa-bb-cc-dd-ee-ff
    re.compile(r"[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}"),  # aabb.ccdd.eeff
    re.compile(r"[0-9a-f]{12}"),  # aabbccddeeff
)
_INTEGER = re.compile(r"[+-]?[0-9]+")  # ASCII digits only: Python's int() also takes other scripts and underscores
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_TRUE, _FALSE = ("true", "yes", "1"), ("false", "no", "0")
# What a cell that doesn't convert gives: fixed codes, never the cell's text (a cell may hold a secret).
CELL_CODES = frozenset(
    {"not_integer", "out_of_range", "not_number", "not_boolean", "not_mac", "not_ip", "not_cidr", "not_in_enum"}
)


def mac(text: str) -> str | None:
    """`text` in lowercase colon form, from any of the usual spellings; None if it isn't a MAC address."""
    lowered = text.lower()
    if not any(form.fullmatch(lowered) for form in _MAC_FORMS):
        return None
    digits = re.sub(r"[:.-]", "", lowered)
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


def ip(text: str) -> str | None:
    """`text` as `ipaddress` writes it (IPv6 compressed and lowercase); None if it isn't an address."""
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        return None


def cidr(text: str) -> str | None:
    """`text` as `ipaddress` writes it; None if it isn't a network, or has host bits set."""
    try:
        return str(ipaddress.ip_network(text, strict=True))
    except ValueError:
        return None


def convert(type_: CsvType, text: str, values: list[str] | None = None) -> tuple[Any, str | None]:
    """A non-empty cell's canonical value, and None; or None and the code saying why it doesn't convert."""
    if type_ == "string":
        return text, None
    if type_ == "integer":
        if not _INTEGER.fullmatch(text):
            return None, "not_integer"
        number = int(text)
        return (number, None) if INT_MIN <= number <= INT_MAX else (None, "out_of_range")
    if type_ == "number":
        real = float(text) if _NUMBER.fullmatch(text) else math.inf
        return (real, None) if math.isfinite(real) else (None, "not_number")
    if type_ == "boolean":
        lowered = text.lower()
        return (lowered in _TRUE, None) if lowered in _TRUE + _FALSE else (None, "not_boolean")
    if type_ == "enum":
        return (text, None) if text in (values or ()) else (None, "not_in_enum")
    converted = {"mac": mac, "ip": ip, "cidr": cidr}[type_](text)
    return (converted, None) if converted is not None else (None, f"not_{type_}")


def is_canonical(type_: CsvType, value: Any, values: list[str] | None = None) -> bool:
    """Whether `value` is a canonical value of `type_`: what converting a cell would give, and nothing else."""
    if type_ == "integer":
        return type(value) is int and INT_MIN <= value <= INT_MAX
    if type_ == "number":
        return type(value) in (int, float)
    if type_ == "boolean":
        return type(value) is bool
    if not isinstance(value, str):
        return False
    if type_ == "enum":
        return value in (values or ())
    if type_ == "mac":
        return _MAC.fullmatch(value) is not None
    if type_ == "ip":
        return ip(value) == value
    if type_ == "cidr":
        return cidr(value) == value
    return True


def _column_schema(column: Mapping[str, Any]) -> dict[str, Any]:
    type_ = column["type"]
    schema: dict[str, Any] = {"type": _JSON_TYPES[type_], "title": column["header"]}
    if type_ in ("mac", "ip", "cidr"):
        schema["format"] = type_  # a hint: admission converted every cell to its canonical form already
    if column.get("values") is not None:
        schema["enum"] = list(column["values"])
    if "default" in column:
        schema["default"] = column["default"]
    if column.get("sensitive"):
        schema["x-sensitive"] = True
    return schema


def trigger_schema(settings: Mapping[str, Any]) -> dict[str, Any]:
    """The schema of a run's trigger, from its version's settings (as the graph document holds them): the
    `input_schema`, plus, when the version declares a CSV, `rows` (each a closed object of its columns, the sensitive
    ones marked, a column with a default always filled in) and `row_count`. Publish types and taints `trigger.*` by
    it, and admission validates and claims by it. `settings` is never changed."""
    schema: dict[str, Any] = dict(settings.get("input_schema") or {"type": "object"})
    csv = settings.get("csv")
    if not csv:
        return schema
    columns = csv["columns"]
    row = {
        "type": "object",
        "properties": {c["name"]: _column_schema(c) for c in columns},
        "required": [c["name"] for c in columns if c.get("required") or "default" in c],
        "additionalProperties": False,
    }
    max_rows = csv.get("max_rows", MAX_ROWS)
    schema["properties"] = {
        **(schema.get("properties") or {}),
        "rows": {"type": "array", "maxItems": max_rows, "items": row},
        "row_count": {"type": "integer", "minimum": 0, "maximum": max_rows},
    }
    schema["required"] = [*(schema.get("required") or ()), *RESERVED]
    return schema
