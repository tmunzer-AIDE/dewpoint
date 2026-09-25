# SPDX-License-Identifier: Apache-2.0
import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from dewpoint.engine.graph.schemas import (
    PathError,
    allowed_kinds,
    compatible,
    contains_literal,
    element_schema,
    json_types,
    literal_on_path,
    navigate,
    object_schema,
    target_schema,
)
from dewpoint.plugins.flow.nodes import FilterConfig, LoopConfig, SwitchConfig


class Site(BaseModel):
    name: str
    tags: list[str]
    note: str | None = None


class Out(BaseModel):
    site: Site
    sites: list[Site]
    maybe: Site | None = None


OUT = Out.model_json_schema(mode="serialization")


def test_navigate_through_refs_lists_and_optionals() -> None:
    r = navigate(OUT, ["site", "name"])
    assert json_types(r.schema) == {"string"} and not r.conditional
    r = navigate(OUT, ["sites", 0, "tags"])
    assert json_types(r.schema) == {"array"} and r.conditional  # the list may be shorter
    r = navigate(OUT, ["site", "note"])
    assert json_types(r.schema) == {"string"} and r.conditional  # optional and nullable
    assert navigate(OUT, ["maybe", "name"]).conditional
    element = element_schema(navigate(OUT, ["sites"]).schema)
    assert element is not None and json_types(navigate(element, ["name"]).schema) == {"string"}


def test_only_closed_objects_reject_undeclared_fields() -> None:
    closed = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
    with pytest.raises(PathError, match="no field `nope`"):
        navigate(closed, ["nope"])
    with pytest.raises(PathError, match="isn't a list"):
        navigate(OUT, ["site", 0])
    for open_object in (OUT, {"type": "object"}):  # additionalProperties omitted: undeclared fields may exist
        path = ["site", "nope"] if open_object is OUT else ["anything"]
        r = navigate(open_object, path)
        assert r.schema is None and r.conditional


def test_compatibility() -> None:
    assert compatible({"type": "integer"}, {"type": "number"})
    assert not compatible({"type": "string"}, {"type": "boolean"})
    assert compatible(None, {"type": "boolean"}) and compatible({"type": "string"}, {})
    assert compatible({"type": "string"}, {"anyOf": [{"type": "string"}, {"type": "null"}]})
    assert json_types({"enum": ["a", 1]}) == {"string", "integer"}


def test_every_possible_source_type_must_fit_the_target() -> None:
    union = {"type": ["string", "integer"]}
    assert not compatible(union, {"type": "string"})
    assert compatible(union, {"type": ["string", "integer", "null"]})
    assert compatible({"anyOf": [{"type": "integer"}, {"type": "number"}]}, {"type": "number"})
    assert not compatible({"anyOf": [{"type": "string"}, {"type": "null"}]}, {"type": "string"})


def test_composed_objects_keep_each_fields_definitions() -> None:
    text = {"$ref": "#/$defs/Item", "$defs": {"Item": {"type": "string"}}}
    number = {"$ref": "#/$defs/Item", "$defs": {"Item": {"type": "integer"}}}
    schema = object_schema({"a": text, "b": number}, ["a", "b"])
    assert json_types(navigate(schema, ["a"]).schema) == {"string"}
    assert json_types(navigate(schema, ["b"]).schema) == {"integer"}
    assert list(Draft202012Validator(schema).iter_errors({"a": "x", "b": 1})) == []
    assert list(Draft202012Validator(schema).iter_errors({"a": 1, "b": "x"})) != []


def test_markers() -> None:
    loop = LoopConfig.model_json_schema()
    assert literal_on_path(loop, ["concurrency"]) and not literal_on_path(loop, ["items"])
    switch = SwitchConfig.model_json_schema()
    assert contains_literal(switch, target_schema(switch, ["cases"]))  # entries carry literal ports
    assert literal_on_path(switch, ["cases", 0, "port"])
    assert not contains_literal(switch, target_schema(switch, ["cases", 0, "when"]))
    assert allowed_kinds(FilterConfig.model_json_schema(), ["predicate"]) == frozenset({"cel"})
    assert allowed_kinds(loop, ["items"]) is None
