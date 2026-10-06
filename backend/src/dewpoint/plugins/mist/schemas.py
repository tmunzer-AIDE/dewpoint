# SPDX-License-Identifier: Apache-2.0
"""A curated operation's schemas from the vendored OAS (plugins-3 D23, D16): its config (what the request takes) and
its output (the 2xx answer), each one JSON Schema with its own `$defs`, as the engine accepts them.

- References to `#/components/schemas/X` become `#/$defs/X`, with every schema they reach copied in; examples, the
  OAS's own keywords (`discriminator`, `xml`, `externalDocs`) and its `x-` extensions are left out.
- A field named like a secret (`passphrase`, `api_token`, `shared_secret`, …) is `x-sensitive`, in config and output:
  the run's secret index claims it, and a version can't write it as a literal.
- An output keeps its shape (types, properties, required fields, items) and drops what a provider outgrows: value
  constraints (formats, enums, patterns, bounds) and closed objects; `oneOf` becomes `anyOf`, since without their
  constraints more than one branch may match. What the answer holds beyond the schema is tainted, never refused.
- An update's body requires nothing: a merge fills the rest from the current object (D15)."""

import copy
import re
from collections.abc import Mapping
from typing import Any

from dewpoint.sdk.fields import SENSITIVE

SCHEMA_ONE = frozenset(
    {
        "additionalProperties", "items", "contains", "propertyNames", "not", "if", "then", "else", "unevaluatedItems",
        "unevaluatedProperties", "contentSchema",
    }
)  # fmt: skip
SCHEMA_LIST = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
SCHEMA_MAP = frozenset({"properties", "patternProperties", "dependentSchemas"})
COMPONENT = "#/components/schemas/"
DROPPED = frozenset({"examples", "example", "discriminator", "xml", "externalDocs"})
OUTGROWN = frozenset(
    {
        "format", "pattern", "enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
        "minLength", "maxLength", "minItems", "maxItems", "uniqueItems", "minProperties", "maxProperties",
        "multipleOf", "contentEncoding", "contentMediaType",
    }
)  # fmt: skip
# A field is a secret when its name's last word is one of these (words split at `_` and lower-to-upper changes).
SECRET_WORDS = frozenset(
    {"psk", "passphrase", "secret", "password", "token", "community", "key", "keys", "apitoken", "keypair", "kek",
     "mack"}
)  # fmt: skip
SECRET_NAMES = frozenset({"community_name"})
_WORDS = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def secret_name(name: str) -> bool:
    words = [w.lower() for part in name.split("_") for w in _WORDS.findall(part)]
    return name in SECRET_NAMES or (bool(words) and words[-1] in SECRET_WORDS)


def _converted(node: Any, *, output: bool, partial: bool) -> Any:
    if not isinstance(node, Mapping):
        return copy.deepcopy(node)
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in DROPPED or key.startswith("x-") or (output and key in OUTGROWN) or (partial and key == "required"):
            continue
        if output and key in ("additionalProperties", "unevaluatedProperties") and value is False:
            continue
        if key == "$ref":
            if not isinstance(value, str) or not value.startswith(COMPONENT):
                raise ValueError("a reference outside the description's schemas")
            out[key] = "#/$defs/" + value[len(COMPONENT) :]
        elif key in SCHEMA_ONE:
            out[key] = _converted(value, output=output, partial=partial)
        elif key in SCHEMA_LIST and isinstance(value, list):
            out["anyOf" if output and key == "oneOf" else key] = [
                _converted(sub, output=output, partial=partial) for sub in value
            ]
        elif key in SCHEMA_MAP and isinstance(value, Mapping):
            subs = {name: _converted(sub, output=output, partial=partial) for name, sub in value.items()}
            if key == "properties":
                for name, sub in subs.items():
                    if secret_name(name) and isinstance(sub, dict):
                        sub.pop("default", None)
                        sub[SENSITIVE] = True
            out[key] = subs
        else:
            out[key] = copy.deepcopy(value)
    return out


def _reached(doc: Mapping[str, Any], roots: list[Any]) -> list[str]:
    """The component schemas `roots` reach through `$ref`s, sorted."""
    components = doc["components"]["schemas"]
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        here = stack.pop()
        if isinstance(here, Mapping):
            ref = here.get("$ref")
            if isinstance(ref, str) and ref.startswith(COMPONENT):
                name = ref[len(COMPONENT) :]
                if name not in seen:
                    seen.add(name)
                    stack.append(components[name])
            stack.extend(v for k, v in here.items() if k not in DROPPED)
        elif isinstance(here, list):
            stack.extend(here)
    return sorted(seen)


def with_defs(
    doc: Mapping[str, Any], schema: dict[str, Any], roots: list[Any], *, output: bool, partial: bool
) -> dict[str, Any]:
    """`schema` with the `$defs` its `roots` reach, converted the same way."""
    names = _reached(doc, roots)
    if names:
        components = doc["components"]["schemas"]
        schema["$defs"] = {n: _converted(components[n], output=output, partial=partial) for n in names}
    return schema


def converted(node: Any, *, output: bool, partial: bool = False) -> Any:
    return _converted(node, output=output, partial=partial)


def resolved(doc: Mapping[str, Any], node: Any) -> Any:
    """A component schema `node` refers to, followed until it isn't a reference."""
    seen: set[str] = set()
    while isinstance(node, Mapping) and isinstance(node.get("$ref"), str) and node["$ref"].startswith(COMPONENT):
        name = node["$ref"][len(COMPONENT) :]
        if name in seen:
            break
        seen.add(name)
        node = doc["components"]["schemas"][name]
    return node


def top_properties(doc: Mapping[str, Any], node: Any) -> list[str]:
    """The top-level property names of an object schema, across its references and unions."""
    found: set[str] = set()
    stack = [node]
    while stack:
        here = resolved(doc, stack.pop())
        if not isinstance(here, Mapping):
            continue
        found.update(here.get("properties", {}))
        for key in ("allOf", "anyOf", "oneOf"):
            stack.extend(here.get(key, ()))
    return sorted(found)
