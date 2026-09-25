# SPDX-License-Identifier: Apache-2.0
import copy
from typing import Any

import pytest

from dewpoint.engine.canonical import canonical_json
from dewpoint.engine.registry.catalog import Catalog, contract_hash, spec_from_manifest, validate_plugin_manifest
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.plugins.testkit import TESTKIT


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": [2, {"d": 3, "c": 4}]}) == canonical_json({"a": [2, {"c": 4, "d": 3}], "b": 1})
    assert canonical_json({"é": 1}) == '{"é":1}'.encode()


def test_first_party_manifests_validate() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert validate_plugin_manifest(TESTKIT.manifest()) == []


def test_manifest_problems_are_reported() -> None:
    m = copy.deepcopy(TESTKIT.manifest())
    m["nodes"][0]["kind"] = "control"
    m["nodes"][1]["config_schema"] = {"type": 5}
    m["nodes"].append(copy.deepcopy(m["nodes"][2]))
    m["sdk_version"] = "9.0.0"
    problems = validate_plugin_manifest(m)
    assert any("only engine control types" in p for p in problems)
    assert any("not a valid JSON Schema" in p for p in problems)
    assert any("duplicate node type version" in p for p in problems)
    assert any("built for SDK" in p for p in problems)


def test_flow_must_declare_every_control_type() -> None:
    m = copy.deepcopy(PLUGIN.manifest())
    m["nodes"] = [n for n in m["nodes"] if n["type"] != "flow.stop"]
    assert "flow: missing control type flow.stop@1" in validate_plugin_manifest(m)


ECHO = TESTKIT.manifest()["nodes"][0]


def _changed(path: tuple[str, ...], value: Any) -> dict[str, Any]:
    m = copy.deepcopy(ECHO)
    target = m
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return m


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("credentials",), ["mist"]),
        (("capabilities",), ["mist.write"]),
        (("retry", "max_attempts"), 9),
        (("retry", "non_retryable"), ["testkit.bad"]),
        (("timeout_s",), 5.0),
        (("side_effect",), "keyed"),
        (("ports",), ["out", "other"]),
        (("dynamic_ports",), "value"),
        (("kind",), "control"),
        (("config_schema", "properties", "value", "type"), "string"),
        (("config_schema", "properties", "value", "x-dewpoint-literal"), True),
        (("output_schema", "properties", "value", "x-sensitive"), True),
        (("config_schema", "properties", "title"), {"type": "string"}),  # a *property* named title is contract
    ],
)
def test_contract_hash_covers_everything_that_changes_behaviour(path: tuple[str, ...], value: Any) -> None:
    assert contract_hash(_changed(path, value)) != contract_hash(ECHO)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("title",), "Echo (renamed)"),
        (("description",), "Returns its input."),
        (("config_schema", "properties", "value", "title"), "Payload"),
        (("config_schema", "properties", "value", "description"), "Any JSON value."),
        (("config_schema", "properties", "value", "examples"), [1, "a"]),
        (("config_schema", "properties", "value", "x-widget"), "pill-text"),
    ],
)
def test_display_metadata_is_not_part_of_the_contract(path: tuple[str, ...], value: Any) -> None:
    assert contract_hash(_changed(path, value)) == contract_hash(ECHO)


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        (("config_schema", "dependentRequired"), {"title": ["value"]}, {"title": ["other"]}),
        (("config_schema", "properties", "value", "default"), {"title": "a"}, {"title": "b"}),
        (("config_schema", "properties", "value", "const"), {"description": "a"}, {"description": "b"}),
        (("config_schema", "properties", "value", "enum"), [{"title": "a"}], [{"title": "b"}]),
        (("config_schema", "x-dewpoint-note"), {"title": "a"}, {"title": "b"}),
    ],
)
def test_annotation_names_inside_data_are_part_of_the_contract(path: tuple[str, ...], before: Any, after: Any) -> None:
    assert contract_hash(_changed(path, before)) != contract_hash(_changed(path, after))


def test_manifest_schemas_must_use_resolvable_local_refs() -> None:
    m = copy.deepcopy(TESTKIT.manifest())
    m["nodes"][0]["config_schema"]["properties"]["value"] = {"$ref": "https://example.com/value.json"}
    assert any("must name an entry" in p for p in validate_plugin_manifest(m))


def test_catalog_lookup_and_states() -> None:
    cat = Catalog(spec_from_manifest(n, "deprecated") for n in TESTKIT.manifest()["nodes"])
    spec = cat.get("testkit.echo@1")
    assert spec is not None and spec.state == "deprecated" and spec.ref == "testkit.echo@1"
    assert cat.get("testkit.echo@2") is None
    both = catalog(PLUGIN, TESTKIT, states={"flow.if@1": "retired"})
    if_spec = both.get("flow.if@1")
    assert if_spec is not None and if_spec.state == "retired" and if_spec.ports == ("true", "false")
