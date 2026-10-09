# SPDX-License-Identifier: Apache-2.0
"""Models declared by a JSON Schema (plugins-3 D23), for nodes generated from data rather than written in Python: a
node's config or output whose shape a provider's description gives. Such a model reports its schema as its JSON
Schema in every mode, validates with it (Draft 2020-12, and the formats a step's output is checked for), and keeps the
value as written, as `root`. Its manifest shows the schema exactly as declared: an object it leaves open stays open,
and the engine taints what it doesn't declare."""

import copy
from collections.abc import Mapping
from typing import Any, ClassVar

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from pydantic import ConfigDict, RootModel, ValidationError, model_validator
from pydantic_core import InitErrorDetails, PydanticCustomError

FORMATS = ("date", "uuid", "email", "ipv4", "ipv6", "regex")  # the formats the worker checks a step's output for
ERROR = "declared_schema"  # the type of each validation error a declared model raises


class DeclaredModel(RootModel[Any]):
    """A model whose schema is declared (`declared_model`), never generated from Python types."""

    model_config = ConfigDict(hide_input_in_errors=True)  # an error's text never holds the value
    declared_schema: ClassVar[Mapping[str, Any]] = {}
    declared_validator: ClassVar[Draft202012Validator | None] = None

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return copy.deepcopy(dict(cls.declared_schema))

    @model_validator(mode="before")
    @classmethod
    def _declared(cls, value: Any) -> Any:
        """Each failing place and its rule's keyword, never the value: a validation message may be shown to users. One
        error for each: jsonschema reports `required` once per missing property (`dependentRequired` per missing
        dependency, `propertyNames` per refused name)."""
        if cls.declared_validator is None:
            raise TypeError("a DeclaredModel is made by declared_model()")
        errors: dict[tuple[tuple[str | int, ...], Any], Any] = {}  # each place and rule, and what's there
        for e in sorted(cls.declared_validator.iter_errors(value), key=lambda e: [str(p) for p in e.absolute_path]):
            errors.setdefault((tuple(e.absolute_path), e.validator), e.instance)
        if errors:
            details = [
                InitErrorDetails(
                    type=PydanticCustomError(ERROR, "Doesn't match the schema's {rule}.", {"rule": rule}),
                    loc=loc,
                    input=instance,
                )
                for (loc, rule), instance in errors.items()
            ]
            raise ValidationError.from_exception_data(cls.__name__, details, hide_input=True)
        return value


def declared_model(
    name: str, schema: Mapping[str, Any], *, formats: tuple[str, ...] = FORMATS, checked: bool = True
) -> type[DeclaredModel]:
    """A model named `name` whose JSON Schema is `schema` (a copy), refused unless it's a valid JSON Schema. A plugin
    generating many may pass `checked=False` (checking a schema against the metaschema is slow) when a test checks its
    manifest as the catalog does: `plugins sync` checks every schema before registering it."""
    if checked:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as e:
            raise ValueError(f"{name}: not a valid JSON Schema ({e.message})") from None
    frozen = copy.deepcopy(dict(schema))
    validator = Draft202012Validator(frozen, format_checker=FormatChecker(formats=formats))
    return type(name, (DeclaredModel,), {"declared_schema": frozen, "declared_validator": validator})
