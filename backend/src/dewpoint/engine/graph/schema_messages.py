# SPDX-License-Identifier: Apache-2.0
"""A value's schema problem, said without the value (ledger M25, the owner's ruling): jsonschema's own messages quote
the instance (`'…' is too short`), so a literal written into a field marked sensitive would reach the problems panel and
the API's answers. Each message here is built from the failing keyword and the schema's own constraint; a property is
named by its name, which is structure, never by its value. A keyword without words of its own is named, still without
the value."""

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from dewpoint.engine.graph.values import Pointer

_TYPES = {
    "string": "a string", "integer": "an integer", "number": "a number", "boolean": "true or false",
    "object": "an object", "array": "a list", "null": "null",
}  # fmt: skip
_MANY = 8  # an enum's values said in full up to this many


def _types(value: Any) -> str:
    kinds = [value] if isinstance(value, str) else list(value)
    return " or ".join(_TYPES.get(k, f"`{k}`") for k in kinds)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _names(names: Sequence[str]) -> str:
    return ", ".join(f"`{n}`" for n in names)


def _plural(n: Any, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _extra(e: ValidationError) -> list[str]:
    """The properties `additionalProperties: false` (or `unevaluatedProperties`) refused: the instance's own keys that
    its schema neither declares nor patterns."""
    schema = e.schema if isinstance(e.schema, Mapping) else {}
    declared = set(schema.get("properties") or {})
    patterns = [re.compile(p) for p in schema.get("patternProperties") or {}]
    keys = e.instance.keys() if isinstance(e.instance, Mapping) else ()
    return [k for k in keys if k not in declared and not any(p.search(k) for p in patterns)]


def _names_check(path: list[Any]) -> bool:
    """Whether the schema path passes through `propertyNames` as a keyword (not a property that happens to be named
    so, under `properties`)."""
    return any(seg == "propertyNames" and (i == 0 or path[i - 1] != "properties") for i, seg in enumerate(path))


def explain(e: ValidationError) -> str:  # noqa: PLR0911, PLR0912 - one sentence per keyword
    k, v = e.validator, cast(Any, e.validator_value)  # jsonschema types it Any | Unset; set for any keyword
    if _names_check(list(e.relative_schema_path)):  # a property name's own check reports its own keyword
        return "Has a property whose name its schema doesn't allow."
    if k == "type":
        return f"Must be {_types(v)}."
    if k == "enum":
        values = list(v)
        return (
            f"Must be one of {', '.join(map(_json, values))}." if len(values) <= _MANY else "Must be one of its values."
        )
    if k == "const":
        return f"Must be {_json(v)}."
    if k in ("minLength", "maxLength"):
        return f"Must be at {'least' if k == 'minLength' else 'most'} {_plural(v, 'character')} long."
    if k == "pattern":
        return f"Must match the pattern `{v}`."
    if k == "format":
        return f"Must be a valid {v}."
    bounds = {
        "minimum": "at least", "maximum": "at most",
        "exclusiveMinimum": "greater than", "exclusiveMaximum": "less than",
    }  # fmt: skip
    if k in bounds:
        return f"Must be {bounds[k]} {v}."
    if k == "multipleOf":
        return f"Must be a multiple of {v}."
    if k in ("minItems", "maxItems"):
        return f"Must have at {'least' if k == 'minItems' else 'most'} {_plural(v, 'item')}."
    if k == "uniqueItems":
        return "Must not repeat an item."
    if k == "contains":
        return "Must hold an item its schema asks for."
    if k in ("minProperties", "maxProperties"):
        side = "least" if k == "minProperties" else "most"
        return f"Must have at {side} {v} {'property' if v == 1 else 'properties'}."
    if k == "required":
        present = e.instance.keys() if isinstance(e.instance, Mapping) else ()
        return f"Needs {_names([p for p in v if p not in present])}."
    if k in ("additionalProperties", "unevaluatedProperties"):
        extra = _extra(e)
        return (
            f"Has a property its schema doesn't allow: {_names(extra)}."
            if extra
            else "Has a property it doesn't allow."
        )
    if k == "dependentRequired":
        present = e.instance.keys() if isinstance(e.instance, Mapping) else ()
        for name, needs in v.items():
            missing = [n for n in needs if n not in present]
            if name in present and missing:
                return f"Needs {_names(missing)} beside `{name}`."
        return "Needs a property its schema asks for."
    if k in ("anyOf", "oneOf"):
        # oneOf also fails when the value matches more than one form: then no form's own errors are kept.
        if k == "oneOf" and not e.context:
            return "Matches more than one of the forms its schema allows."
        return "Matches none of the forms its schema allows."
    if k == "not":
        return "Matches a form its schema rules out."
    if k is None:  # the `false` schema: nothing is allowed here
        return "Isn't allowed here."
    return f"Doesn't satisfy its schema's `{k}`."


def problems(schema: Mapping[str, Any], instance: Any) -> list[tuple[Pointer, str]]:
    """Each of `instance`'s schema problems by place, ordered by its path's text, and said once: jsonschema reports
    `required` once per missing property (`dependentRequired` per missing dependency, `propertyNames` per refused
    name), but `explain` words the keyword at its place, not the report, so each of those reports would say the same."""
    found: dict[tuple[Pointer, str], None] = {}
    for e in sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: str(list(e.absolute_path))):
        found.setdefault((tuple(e.absolute_path), explain(e)), None)
    return list(found)
