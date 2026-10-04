# SPDX-License-Identifier: Apache-2.0
"""A JSON pointer (RFC 6901), resolved against a parsed document: where an endpoint's events and ids are, and what a
binding's filter compares."""

import re

INDEX = re.compile(r"0|[1-9][0-9]*")


class PointerError(LookupError):
    """A pointer that doesn't resolve in the document (its text is never quoted: it may carry a value)."""


def resolve(document: object, pointer: str) -> object:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise PointerError("a pointer is empty or starts with '/'")
    value = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and INDEX.fullmatch(token) and int(token) < len(value):
            value = value[int(token)]
        else:
            raise PointerError("the pointer doesn't resolve")
    return value
