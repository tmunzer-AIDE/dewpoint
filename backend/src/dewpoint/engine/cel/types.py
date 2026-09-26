# SPDX-License-Identifier: Apache-2.0
"""The CEL types Dewpoint declares (spec §5.3), as runtime signatures, and the value checks behind them.

The set is closed: an evaluator request can only name these types, and binding checks every value against its
declared type before any CEL runs."""

from typing import Any

DYN = "dyn"
INT = "int"
STRING = "string"
BOOL = "bool"
MAP = "map<string, dyn>"
LIST = "list<dyn>"
LIST_OF_MAPS = "list<map<string, dyn>>"
LIST_OF_STRINGS = "list<string>"
LIST_OF_BOOLS = "list<bool>"
LIST_OF_LISTS = "list<list<dyn>>"
ELEMENT: dict[str, str] = {
    LIST: DYN,
    LIST_OF_MAPS: MAP,
    LIST_OF_STRINGS: STRING,
    LIST_OF_BOOLS: BOOL,
    LIST_OF_LISTS: LIST,
}
SIGNATURES = frozenset({DYN, INT, STRING, BOOL, MAP, *ELEMENT})
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1


def list_of(element: str) -> str:
    """The list signature for an element signature; unsupported elements become `list<dyn>`."""
    for sig, elem in ELEMENT.items():
        if elem == element:
            return sig
    return LIST


def conforms(signature: str, value: Any) -> bool:
    """True when `value` (plain JSON) has the declared type. Unknown signatures never conform."""
    if signature == DYN:
        return True
    if signature == INT:
        return isinstance(value, int) and not isinstance(value, bool)
    if signature == STRING:
        return isinstance(value, str)
    if signature == BOOL:
        return isinstance(value, bool)
    if signature == MAP:
        return isinstance(value, dict) and all(isinstance(k, str) for k in value)
    element = ELEMENT.get(signature)
    if element is None or not isinstance(value, list):
        return False
    return element == DYN or all(conforms(element, v) for v in value)
