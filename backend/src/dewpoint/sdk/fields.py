# SPDX-License-Identifier: Apache-2.0
"""JSON Schema markers the engine reads from a node's Config and Output models."""

from typing import Any

from pydantic import Field
from pydantic_core import PydanticUndefined

LITERAL = "x-dewpoint-literal"  # written in the graph, never computed: ports, limits, pinned ids
KINDS = "x-dewpoint-kinds"  # value kinds a field accepts: literal, ref, template, cel
SENSITIVE = "x-sensitive"  # output field kept out of run_steps, previews and samples
VALUE_KINDS = frozenset({"literal", "ref", "template", "cel"})


def literal_only(default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    return Field(default, json_schema_extra={LITERAL: True}, **kwargs)


def value_kinds(*kinds: str, default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    if not kinds or set(kinds) - VALUE_KINDS:
        raise ValueError(f"value_kinds needs one or more of {sorted(VALUE_KINDS)}, got {sorted(kinds)}")
    extra: dict[str, Any] = {KINDS: sorted(kinds)}
    return Field(default, json_schema_extra=extra, **kwargs)


def sensitive(default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    return Field(default, json_schema_extra={SENSITIVE: True}, **kwargs)
