# SPDX-License-Identifier: Apache-2.0
import pytest
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


def test_unknown_fields_are_errors_on_closed_schemas() -> None:
    with pytest.raises(PathError, match="no field `nope`"):
        navigate(OUT, ["site", "nope"])
    with pytest.raises(PathError, match="isn't a list"):
        navigate(OUT, ["site", 0])
    open_object = navigate({"type": "object"}, ["anything"])
    assert open_object.schema is None and open_object.conditional


def test_compatibility() -> None:
    assert compatible({"type": "integer"}, {"type": "number"})
    assert not compatible({"type": "string"}, {"type": "boolean"})
    assert compatible(None, {"type": "boolean"}) and compatible({"type": "string"}, {})
    assert compatible({"type": "string"}, {"anyOf": [{"type": "string"}, {"type": "null"}]})
    assert json_types({"enum": ["a", 1]}) == {"string", "integer"}


def test_markers() -> None:
    loop = LoopConfig.model_json_schema()
    assert literal_on_path(loop, ["concurrency"]) and not literal_on_path(loop, ["items"])
    switch = SwitchConfig.model_json_schema()
    assert contains_literal(switch, target_schema(switch, ["cases"]))  # entries carry literal ports
    assert literal_on_path(switch, ["cases", 0, "port"])
    assert not contains_literal(switch, target_schema(switch, ["cases", 0, "when"]))
    assert allowed_kinds(FilterConfig.model_json_schema(), ["predicate"]) == frozenset({"cel"})
    assert allowed_kinds(loop, ["items"]) is None
