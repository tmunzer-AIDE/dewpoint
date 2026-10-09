# SPDX-License-Identifier: Apache-2.0
import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from pydantic import BaseModel

from dewpoint.engine.graph import schemas
from dewpoint.engine.graph.schemas import (
    MAX_ALTERNATIVES,
    MAX_STEPS,
    MAX_UNION_DEPTH,
    PathError,
    allowed_kinds,
    compatible,
    contains_literal,
    declared_optional,
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


def test_declared_optional_positions_stop_where_the_schema_stops() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "object", "properties": {"b": {"$ref": "#/$defs/B"}}, "required": ["b"]},
            "open": {"type": "object"},
            "n": {"type": ["object", "null"], "properties": {"x": {"type": "string"}}},
        },
        "required": ["open", "n"],
        "$defs": {"B": {"type": "object", "properties": {"c": {"type": "string"}}}},
    }
    assert declared_optional(schema, ("a", "b", "c")) == (0, 2)  # a optional, b required, c optional (through $ref)
    assert declared_optional(schema, ("open", "anything", "deeper")) == ()  # undeclared: open data
    assert declared_optional(schema, ("n", "x")) == (1,)  # null is a value, not absence: n itself is required
    assert declared_optional(schema, ("a", 0)) == (0,)  # an index ends the walk
    assert declared_optional(None, ("a",)) == ()
    assert declared_optional(schema, ("c",), start=schema["$defs"]["B"]) == (0,)


# Alternatives, read together (4c-2a ruling 1; engine-core spec §4.3).
DEVICES: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {"type": "array", "items": {"$ref": "#/$defs/device"}},
        "total": {"type": ["integer", "null"]},
    },
    "required": ["results", "total"],
    "additionalProperties": False,
    "$defs": {
        "device": {"anyOf": [{"$ref": "#/$defs/ap"}, {"$ref": "#/$defs/switch"}]},
        "ap": {"type": "object", "properties": {"name": {"type": "string"}, "radios": {"type": "array"}}},
        "switch": {"type": "object", "properties": {"name": {"type": "string"}, "ports": {"type": "integer"}}},
    },
}
CLOSED: dict[str, Any] = {
    "anyOf": [
        {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False},
        {"type": "object", "properties": {"b": {"type": "integer"}}, "required": ["b"], "additionalProperties": False},
    ]
}


def test_reads_a_field_every_alternative_declares_as_its_type() -> None:
    r = navigate(DEVICES, ["results", 0, "name"])
    assert json_types(r.schema) == {"string"}
    assert r.missing and r.conditional and not r.nullable  # the list may be shorter; no kind requires a name


def test_a_field_one_open_alternative_doesnt_declare_is_any_value() -> None:
    r = navigate(DEVICES, ["results", 0, "radios"])  # an AP declares it; a switch is open and says nothing
    assert r.schema is None and r.missing


def test_a_field_a_closed_alternative_lacks_may_be_missing() -> None:
    r = navigate(CLOSED, ["a"])
    assert json_types(r.schema) == {"string"} and r.missing and not r.nullable


def test_a_field_no_alternative_holds_is_an_error() -> None:
    with pytest.raises(PathError, match="no field `c`"):
        navigate(CLOSED, ["c"])


def test_a_field_every_alternative_requires_is_always_there() -> None:
    either = {
        "anyOf": [
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        ]
    }
    r = navigate(either, ["id"])
    assert json_types(r.schema) == {"integer", "string"} and not r.conditional


def test_a_union_with_null_is_nullable_whatever_its_size() -> None:
    either = {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]}
    three = {"type": "object", "properties": {"v": either}, "required": ["v"]}
    r = navigate(three, ["v"])
    assert json_types(r.schema) == {"integer", "string"} and r.nullable and not r.missing and r.conditional
    total = navigate(DEVICES, ["total"])
    assert json_types(total.schema) == {"integer"} and total.nullable and not total.missing


def test_a_value_only_null_stays_a_value() -> None:
    r = navigate({"type": "object", "properties": {"v": {"type": "null"}}, "required": ["v"]}, ["v"])
    assert json_types(r.schema) == {"null"} and not r.conditional  # as before: null is its value


def test_reads_an_index_through_alternative_lists() -> None:
    lists = {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "array", "items": {"type": "integer"}}]}
    r = navigate(lists, [0])
    assert json_types(r.schema) == {"integer", "string"} and r.missing


def test_the_schema_around_a_union_applies_to_each_alternative() -> None:
    around = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "anyOf": [{"required": ["a"]}, {"required": ["a"]}],
    }
    r = navigate(around, ["a"])
    assert json_types(r.schema) == {"string"} and not r.conditional


def test_follows_nested_alternatives_up_to_the_bound_then_says_any_value() -> None:
    def nested(levels: int) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "string"}
        for _ in range(levels):
            schema = {"anyOf": [schema, {"type": "integer"}]}
        return {"type": "object", "properties": {"v": schema}, "required": ["v"]}

    assert json_types(navigate(nested(MAX_UNION_DEPTH), ["v"]).schema) == {"integer", "string"}
    assert navigate(nested(MAX_UNION_DEPTH + 1), ["v"]).schema is None
    wide = {"anyOf": [{"type": "object", "properties": {f"k{i}": {"type": "string"}}}
                      for i in range(MAX_ALTERNATIVES + 1)]}  # fmt: skip
    assert navigate(wide, ["k0"]).schema is None


def test_ends_on_a_definition_that_refers_to_itself() -> None:
    loop = {"$defs": {"node": {"anyOf": [{"$ref": "#/$defs/node"}, {"type": "string"}]}}, "$ref": "#/$defs/node"}
    assert navigate(loop, []).schema is None


def test_declared_optional_reads_through_a_union_only_where_every_alternative_declares() -> None:
    both = {"anyOf": [{"type": "object", "properties": {"x": {"type": "string"}}},
                      {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}]}  # fmt: skip
    assert declared_optional(both, ["x"]) == (0,)
    one = {"anyOf": [{"type": "object", "properties": {"x": {"type": "string"}}}, {"type": "object"}]}
    assert declared_optional(one, ["x"]) == ()  # open data from here (spec §4.3)


def test_reads_a_device_name_as_text_in_every_kind_of_device() -> None:
    """Mist's device list, as its catalog prints it: every kind declares `name` as text and none requires it."""
    from dewpoint.plugins.mist import PLUGIN
    from dewpoint.sdk import node_manifest

    out = node_manifest(next(n for n in PLUGIN.nodes if n.type == "mist.site_devices.list"))["output_schema"]
    name = navigate(out, ["results", 0, "name"])
    assert json_types(name.schema) == {"string"} and name.missing and not name.nullable
    total = navigate(out, ["total"])
    assert json_types(total.schema) == {"integer"} and total.nullable and not total.missing


# A property: whatever the alternatives, a value read along a path is one the answer allows, or the answer says it
# may be missing (never promising less than the data holds).
_LEAVES = st.sampled_from([{"type": "string"}, {"type": "integer"}, {"type": "null"}, {"type": ["string", "null"]}])


def _object(children: st.SearchStrategy[Any]) -> st.SearchStrategy[dict[str, Any]]:
    return st.dictionaries(st.sampled_from("abc"), children, min_size=1, max_size=3).flatmap(
        lambda props: st.sets(st.sampled_from(sorted(props))).map(
            lambda required: {
                "type": "object",
                "properties": props,
                "required": sorted(required),
                "additionalProperties": False,
            }  # fmt: skip
        )
    )


SCHEMAS = st.recursive(
    _LEAVES,
    lambda children: st.one_of(
        _object(children),
        children.map(lambda item: {"type": "array", "items": item}),
        st.lists(children, min_size=2, max_size=3).map(lambda options: {"anyOf": options}),
    ),
    max_leaves=8,
)
_ABSENT = object()


def _value(draw: Any, schema: dict[str, Any]) -> Any:
    if "anyOf" in schema:
        return _value(draw, draw(st.sampled_from(schema["anyOf"])))
    kind = schema["type"]
    kind = draw(st.sampled_from(kind)) if isinstance(kind, list) else kind
    if kind == "string":
        return draw(st.text(max_size=2))
    if kind == "integer":
        return draw(st.integers(-3, 3))
    if kind == "null":
        return None
    if kind == "array":
        return [_value(draw, schema["items"]) for _ in range(draw(st.integers(0, 2)))]
    props = schema["properties"].items()
    return {k: _value(draw, sub) for k, sub in props if k in schema["required"] or draw(st.booleans())}


def _paths(schema: dict[str, Any], depth: int) -> list[list[str | int]]:
    if depth == 0:
        return []
    if "anyOf" in schema:
        return [p for option in schema["anyOf"] for p in _paths(option, depth)]
    out: list[list[str | int]] = [["z"]]  # a field nothing declares
    if schema.get("type") == "array":
        out += [[0]] + [[0, *rest] for rest in _paths(schema["items"], depth - 1)]
    for k, sub in schema.get("properties", {}).items():
        out += [[k]] + [[k, *rest] for rest in _paths(sub, depth - 1)]
    return out


def _read(value: Any, path: list[str | int]) -> Any:
    for seg in path:
        if isinstance(seg, int):
            value = value[seg] if isinstance(value, list) and seg < len(value) else _ABSENT
        else:
            value = value.get(seg, _ABSENT) if isinstance(value, dict) else _ABSENT
        if value is _ABSENT:
            return _ABSENT
    return value


_JSON = {bool: "boolean", int: "integer", str: "string", list: "array", dict: "object"}


@settings(max_examples=300, deadline=None)
@given(st.data())
def test_never_promises_less_than_the_data_holds(data: st.DataObject) -> None:
    schema = data.draw(SCHEMAS)
    value = _value(data.draw, schema)
    for path in _paths(schema, 3):
        found = _read(value, path)
        try:
            r = navigate(schema, path)
        except PathError:
            assert found is _ABSENT, (json.dumps(schema), path)  # no alternative can hold it, so no value does
            continue
        if found is _ABSENT:
            assert r.missing, (json.dumps(schema), path)
        elif found is None:
            assert r.nullable or r.schema is None or json_types(r.schema) == {"null"}, (json.dumps(schema), path)
        elif r.schema is not None:
            assert _JSON[type(found)] in (json_types(r.schema) or {_JSON[type(found)]}), (json.dumps(schema), path)


# The review of revision 1: what surrounds a union stays, and the whole read is bounded.
def _valid(schema: dict[str, Any], *witnesses: Any) -> None:
    """A fixture admits data: each witness passes JSON Schema itself (the review of revision 2)."""
    for witness in witnesses:
        assert Draft202012Validator(schema).is_valid(witness), witness


def test_a_field_around_a_union_keeps_its_type() -> None:
    """What surrounds a union applies to each branch beside it, never overwritten by it."""
    around = {
        "type": "object",
        "properties": {"common": {"type": "string"}},
        "required": ["common"],
        "anyOf": [
            {"properties": {"common": {}, "kind": {"const": "a"}, "a": {"type": "integer"}},
             "required": ["kind", "a"], "additionalProperties": False},
            {"properties": {"common": {}, "kind": {"const": "b"}, "b": {"type": "integer"}},
             "required": ["kind", "b"], "additionalProperties": False},
        ],
    }  # fmt: skip
    _valid(around, {"common": "x", "kind": "a", "a": 1}, {"common": "y", "kind": "b", "b": 2})
    common = navigate(around, ["common"])
    assert json_types(common.schema) == {"string"} and not common.conditional
    a = navigate(around, ["a"])
    assert json_types(a.schema) == {"integer"} and a.missing  # the other branch is closed without it


def test_reads_every_member_of_an_all_of() -> None:
    both = {"allOf": [{"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]},
                      {"type": "object", "properties": {"b": {"type": "integer"}}}]}  # fmt: skip
    _valid(both, {"a": "x"}, {"a": "x", "b": 1})
    assert json_types(navigate(both, ["a"]).schema) == {"string"} and not navigate(both, ["a"]).conditional
    assert json_types(navigate(both, ["b"]).schema) == {"integer"} and navigate(both, ["b"]).missing
    assert json_types({"allOf": [{"type": ["string", "integer"]}, {"type": "string"}]}) == {"string"}


def test_an_integer_is_a_number() -> None:
    """`number` and `integer` meet in `integer`: 5 passes both (the review of revision 2)."""
    count = {"allOf": [{"type": "number"}, {"type": "integer"}]}
    _valid(count, 5)
    assert json_types(count) == {"integer"}
    holder = {"type": "object", "properties": {"n": count}, "required": ["n"]}
    _valid(holder, {"n": 5})
    n = navigate(holder, ["n"])
    assert json_types(n.schema) == {"integer"} and not n.conditional
    assert compatible(n.schema, {"type": "integer"})


def test_a_field_is_sure_only_on_a_value_sure_to_be_an_object() -> None:
    """Object keywords speak only of objects: a string with `properties` and `required` beside it is still a string
    (the review of revision 2)."""
    text = {"allOf": [{"type": "string"}, {"properties": {"n": {"type": "integer"}}, "required": ["n"]}]}
    _valid(text, "x")
    with pytest.raises(PathError, match="isn't an object"):
        navigate({"type": "object", "properties": {"v": text}, "required": ["v"]}, ["v", "n"])
    mixed = {"type": ["object", "string"], "properties": {"n": {"type": "integer"}}, "required": ["n"]}
    _valid(mixed, {"n": 1}, "x")
    n = navigate({"type": "object", "properties": {"v": mixed}, "required": ["v"]}, ["v", "n"])
    assert json_types(n.schema) == {"integer"} and n.missing  # when the value is the string, there's no `n`
    assert declared_optional({"type": "object", "properties": {"v": mixed}, "required": ["v"]}, ["v", "n"]) == (1,)


def _tree(depth: int, tag: str, required: bool = True) -> dict[str, Any]:
    """Four ways at every level, each leading to its own: 4 ** depth distinct ways at the bottom."""
    if depth == 0:
        return {"const": tag}
    return {"anyOf": [{"type": "object", "properties": {"x": _tree(depth - 1, f"{tag}{i}", required)},
                       "required": ["x"] if required else []} for i in range(4)]}  # fmt: skip


def test_bounds_the_whole_read_not_only_one_position(monkeypatch: pytest.MonkeyPatch) -> None:
    assert json_types(navigate(_tree(2, "t"), ["x", "x"]).schema) == {"string"}  # 16 ways: within the bound
    spent: list[int] = []
    real = schemas._Budget.spend
    monkeypatch.setattr(schemas._Budget, "spend", lambda self, n=1: spent.append(n) or real(self, n))
    assert navigate(_tree(4, "t"), ["x"] * 4).schema is None  # 256 ways: past the bound, any value
    assert sum(spent) <= MAX_STEPS
    spent.clear()
    # it stops at the position where the ways pass 64
    assert declared_optional(_tree(5, "t", required=False), ["x"] * 5) == (0, 1, 2, 3)
    assert sum(spent) <= MAX_STEPS


def test_merges_alternatives_that_are_the_same() -> None:
    same = {"anyOf": [{"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}] * 40}
    deep: dict[str, Any] = {"type": "string"}
    for _ in range(6):
        deep = {"anyOf": [{"type": "object", "properties": {"x": deep}, "required": ["x"]}] * 4}
    assert json_types(navigate(same, ["x"]).schema) == {"string"}
    assert json_types(navigate(deep, ["x"] * 6).schema) == {"string"} and not navigate(deep, ["x"] * 6).conditional
