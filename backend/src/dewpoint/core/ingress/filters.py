# SPDX-License-Identifier: Apache-2.0
"""A binding's filter (engine 2b spec §8.3): at most 8 typed JSON-pointer equalities on the event, all of which must
hold; none matches every event. No CEL. Equality is of canonical JSON, so it's typed: `1`, `1.0`, `true` and `"1"` are
four values. A filter is checked when it's written: each clause a pointer (RFC 6901, at most 256 characters) and a
scalar value (a string of at most 1,024 characters, a 64-bit integer, a boolean or null; never a float, whose equality
is a question of formatting)."""

from typing import Any

from dewpoint.core.ingress.identity import canonical
from dewpoint.core.ingress.pointer import PointerError, resolve

MAX_CLAUSES = 8
MAX_POINTER_CHARS = 256
MAX_VALUE_CHARS = 1024
INT_RANGE = (-(2**63), 2**63 - 1)


class FilterError(ValueError):
    """A filter that isn't one; the message says what's wrong, never quoting a value."""


def matches(clauses: list[dict[str, Any]], event: object) -> bool:
    for clause in clauses:
        try:
            found = resolve(event, clause["pointer"])
        except PointerError:
            return False
        if canonical(found) != canonical(clause["value"]):
            return False
    return True


def _scalar(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, int):
        return INT_RANGE[0] <= value <= INT_RANGE[1]
    return isinstance(value, str) and len(value) <= MAX_VALUE_CHARS


def validated(given: object) -> list[dict[str, Any]]:
    """`given`, when it's a filter. Raises FilterError."""
    if not isinstance(given, list):
        raise FilterError("A filter is a list of clauses.")
    if len(given) > MAX_CLAUSES:
        raise FilterError(f"A filter has at most {MAX_CLAUSES} clauses.")
    for clause in given:
        if not isinstance(clause, dict) or set(clause) != {"pointer", "value"}:
            raise FilterError("Each clause is exactly a pointer and a value.")
        pointer = clause["pointer"]
        if not isinstance(pointer, str) or not pointer.startswith("/") or len(pointer) > MAX_POINTER_CHARS:
            raise FilterError(f"A clause's pointer starts with '/' and has at most {MAX_POINTER_CHARS} characters.")
        if not _scalar(clause["value"]):
            raise FilterError(
                f"A clause's value is a string of at most {MAX_VALUE_CHARS} characters, a 64-bit integer, a boolean "
                "or null."
            )
    return given
