# SPDX-License-Identifier: Apache-2.0
"""JSON Schema markers the engine reads from a node's Config and Output models."""

from typing import Any

from pydantic import Field
from pydantic_core import PydanticUndefined

LITERAL = "x-dewpoint-literal"  # written in the graph, never computed: ports, limits, pinned ids
KINDS = "x-dewpoint-kinds"  # value kinds a field accepts: literal, ref, template, cel
SENSITIVE = "x-sensitive"  # output field kept out of run_steps, previews and samples
CONNECTION = "x-dewpoint-connection"  # a top-level config field naming one of the tenant's connections of this type
OPTIONS = "x-dewpoint-options"  # a top-level config field whose choices the node's options() lists (plugins-3 D3)
VALUE_KINDS = frozenset({"literal", "ref", "template", "cel"})


def literal_only(default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    return Field(default, json_schema_extra={LITERAL: True}, **kwargs)


def value_kinds(*kinds: str, default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    if not kinds or set(kinds) - VALUE_KINDS:
        raise ValueError(f"value_kinds needs one or more of {sorted(VALUE_KINDS)}, got {sorted(kinds)}")
    extra: dict[str, Any] = {**(kwargs.pop("json_schema_extra", None) or {}), KINDS: sorted(kinds)}
    return Field(default, json_schema_extra=extra, **kwargs)


def sensitive(default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    return Field(default, json_schema_extra={SENSITIVE: True}, **kwargs)


def connection_field(type_key: str, **kwargs: Any) -> Any:
    """A config field naming a connection of `type_key` (plugins-3 D6): a literal UUID, top-level only, checked at
    publish against the tenant's connections; the node lists `type_key` in its `credentials`."""
    return Field(json_schema_extra={LITERAL: True, CONNECTION: type_key}, **kwargs)


def options_field(default: Any = PydanticUndefined, **kwargs: Any) -> Any:
    """A config field whose choices the node lists in `options()` (plugins-3 D3), for the editor and start forms:
    top-level only. The choices are suggestions; the field still validates as its type says."""
    return Field(default, json_schema_extra={OPTIONS: True}, **kwargs)
