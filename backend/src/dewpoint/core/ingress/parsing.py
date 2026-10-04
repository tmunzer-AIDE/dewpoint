# SPDX-License-Identifier: Apache-2.0
"""A webhook body's strict parsing (engine 2b spec §8.3; the owner's rulings on the 2b-3b outline), so no parser's
leniency decides what an event is: UTF-8 JSON only, and a duplicate key in any object, NaN or an infinity, a number past
binary64's range, an escaped unpaired surrogate, an integer of more than 4,300 digits, or nesting deeper than 64 levels
refuses the whole body. Its events are the body itself, or the array at the endpoint's events pointer: objects only, 1
to 500 of them."""

import json
import math
import re
from collections.abc import Iterable
from typing import Any

from dewpoint.core.ingress.pointer import PointerError, resolve

MAX_EVENTS = 500
# Levels of nesting, the body's own value the first: the engine's limit for a document (engine.graph.model), so an
# event's depth never depends on an interpreter's recursion limit, here or wherever its run's trigger is walked.
MAX_DEPTH = 64
MAX_INT_DIGITS = 4300  # Python's own default limit, held here whatever the interpreter is configured with
# A lone surrogate can only come from an escape: strict UTF-8 decoding refuses an encoded one.
SURROGATE_ESCAPE = re.compile(r"\\u[dD][89a-fA-F]")


class MalformedError(ValueError):
    """A body refused whole: `400 malformed`. Its message is fixed and never quotes the body."""

    def __init__(self) -> None:
        super().__init__("malformed")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    found = dict(pairs)
    if len(found) != len(pairs):
        raise ValueError("a duplicate key")
    return found


def _constant(_: str) -> float:
    raise ValueError("NaN or an infinity")


def _float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("past binary64's range")
    return value


def _int(text: str) -> int:
    if len(text.lstrip("-")) > MAX_INT_DIGITS:
        raise ValueError("an integer past 4,300 digits")
    return int(text)


def _checked(document: object, strings: bool) -> None:
    """At most MAX_DEPTH levels of objects and arrays; with `strings`, every string and key encodes as UTF-8 (no
    unpaired surrogate). Iterative: no recursion limit decides."""
    stack: list[tuple[object, int]] = [(document, 1)]
    while stack:
        value, depth = stack.pop()
        if isinstance(value, (dict, list)) and depth > MAX_DEPTH:
            raise ValueError("nested too deep")
        children: Iterable[object]
        if isinstance(value, dict):
            if strings:
                for key in value:
                    key.encode()
            children = value.values()
        elif isinstance(value, list):
            children = value
        else:
            if strings and isinstance(value, str):
                value.encode()
            continue
        stack.extend((child, depth + 1) for child in children if strings or isinstance(child, (dict, list)))


def parse(body: bytes) -> object:
    try:
        text = body.decode("utf-8")
        document = json.loads(
            text, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float, parse_int=_int
        )
        _checked(document, strings=SURROGATE_ESCAPE.search(text) is not None)
    except (ValueError, RecursionError):  # JSONDecodeError and UnicodeError are ValueErrors
        raise MalformedError from None
    return document


def events_of(document: object, events_pointer: str | None) -> list[dict[str, Any]]:
    if events_pointer is None:
        items = [document]
    else:
        try:
            found = resolve(document, events_pointer)
        except PointerError:
            raise MalformedError from None
        if not isinstance(found, list):
            raise MalformedError
        items = found
    if not 1 <= len(items) <= MAX_EVENTS or not all(isinstance(item, dict) for item in items):
        raise MalformedError
    return items  # type: ignore[return-value]  # each checked a dict above
