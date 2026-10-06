# SPDX-License-Identifier: Apache-2.0
"""SDK 0.4.0 (plugins-3 D12, D17, D23): models declared by a JSON Schema, for nodes generated from data, and a plugin's
triggers, the manifest key added only when set."""

import copy
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.sdk import (
    SDK_VERSION,
    DeclaredModel,
    ManifestError,
    Node,
    Plugin,
    Trigger,
    declared_model,
    dump_output,
    node_manifest,
)

CONFIG = {
    "type": "object",
    "properties": {
        "site_id": {"type": "string", "format": "uuid"},
        "body": {"$ref": "#/$defs/wlan"},
    },
    "required": ["site_id"],
    "additionalProperties": False,
    "$defs": {"wlan": {"type": "object", "properties": {"ssid": {"type": "string", "maxLength": 32}}}},
}
OUTPUT = {"type": "object", "properties": {"id": {"type": "string"}}}
SITE = "6a1d6e2f-3c4b-4a5d-9e8f-0123456789ab"
EVENT = {
    "type": "object",
    "properties": {"topic": {"enum": ["alarms"]}, "events": {"type": "array", "items": {"type": "object"}}},
    "required": ["topic", "events"],
}


def test_the_sdk_is_0_4_0() -> None:
    assert SDK_VERSION == "0.4.0"


def test_a_declared_model_reports_its_schema_in_every_mode() -> None:
    model = declared_model("WlanConfig", CONFIG)
    assert issubclass(model, DeclaredModel) and model.__name__ == "WlanConfig"
    assert model.model_json_schema() == CONFIG
    assert model.model_json_schema(mode="serialization") == CONFIG
    found = model.model_json_schema()
    found["properties"]["site_id"]["type"] = "integer"
    assert model.model_json_schema() == CONFIG  # a copy each time


def test_a_declared_model_validates_with_its_schema_and_keeps_the_value() -> None:
    model = declared_model("WlanConfig", CONFIG)
    value = {"site_id": SITE, "body": {"ssid": "corp", "unknown": 1}}
    assert model.model_validate(value).root == value
    assert model.model_validate(copy.deepcopy(value)).model_dump(mode="json") == value


@pytest.mark.parametrize(
    ("value", "locations"),
    [
        ({"body": {}}, {()}),
        ({"site_id": "not-a-uuid"}, {("site_id",)}),
        ({"site_id": SITE, "body": {"ssid": "x" * 33}}, {("body", "ssid")}),
        ({"site_id": SITE, "extra": 1}, {()}),
        ("text", {()}),
    ],
)
def test_a_declared_model_refuses_what_its_schema_refuses(value: Any, locations: set[tuple[Any, ...]]) -> None:
    model = declared_model("WlanConfig", CONFIG)
    with pytest.raises(ValidationError) as e:
        model.model_validate(value)
    assert {tuple(err["loc"]) for err in e.value.errors()} == locations
    assert all("input" not in err for err in e.value.errors(include_input=False))


def test_an_invalid_schema_is_refused_when_declared() -> None:
    with pytest.raises(ValueError, match="JSON Schema"):
        declared_model("Bad", {"type": "object", "properties": {"a": {"type": "nope"}}})


class Generated(Node):
    type = "demo.generated"
    version = 1
    title = "Generated"
    Config = declared_model("GeneratedConfig", CONFIG)
    Output = declared_model("GeneratedOutput", OUTPUT)

    async def run(self, ctx: Any, config: Any) -> BaseModel:
        return self.Output.model_validate({"id": "a", "more": True})


def test_a_node_declared_by_schema_shows_both_schemas_as_declared() -> None:
    m = node_manifest(Generated)
    assert m["config_schema"] == CONFIG
    assert m["output_schema"] == OUTPUT  # as declared: an open object stays open, its undeclared keys tainted
    assert dump_output(Generated.Output.model_validate({"id": "a", "more": True})) == {"id": "a", "more": True}


TRIGGER = Trigger(
    key="demo.webhook",
    label="Demo webhook",
    auth="bearer",
    topic_pointer="/topic",
    topics={"alarms": EVENT},
)


def test_a_plugin_lists_its_triggers_in_its_manifest_only_when_set() -> None:
    with_trigger = Plugin(name="demo", version="1.0.0", nodes=(Generated,), triggers=(TRIGGER,)).manifest()
    assert with_trigger["triggers"] == [
        {
            "key": "demo.webhook",
            "label": "Demo webhook",
            "endpoint": {"auth": "bearer", "events_pointer": None, "id_source": "none"},
            "topic_pointer": "/topic",
            "topics": {"alarms": EVENT},
        }
    ]
    assert "triggers" not in Plugin(name="demo", version="1.0.0", nodes=(Generated,)).manifest()
    assert validate_plugin_manifest(with_trigger) == []


@pytest.mark.parametrize(
    ("trigger", "problem"),
    [
        (Trigger("other.webhook", "x", "bearer", "/topic", {"a": EVENT}), "must be named"),
        (Trigger("demo.webhook", "", "bearer", "/topic", {"a": EVENT}), "label"),
        (Trigger("demo.webhook", "x", "basic", "/topic", {"a": EVENT}), "auth"),
        (Trigger("demo.webhook", "x", "bearer", "topic", {"a": EVENT}), "pointer"),
        (Trigger("demo.webhook", "x", "bearer", "/topic", {}), "topics"),
        (Trigger("demo.webhook", "x", "bearer", "/topic", {"A b": EVENT}), "topic"),
        (Trigger("demo.webhook", "x", "bearer", "/topic", {"a": {"type": "array"}}), "object"),
        (Trigger("demo.webhook", "x", "bearer", "/topic", {"a": {"type": "nope"}}), "JSON Schema"),
        (Trigger("demo.webhook", "x", "bearer", "/topic", {"a": EVENT}, events_pointer="x"), "pointer"),
    ],
)
def test_a_malformed_trigger_is_refused_by_the_sdk_and_the_catalog(trigger: Trigger, problem: str) -> None:
    with pytest.raises(ManifestError, match=problem):
        Plugin(name="demo", version="1.0.0", nodes=(Generated,), triggers=(trigger,)).manifest()
    good = Plugin(name="demo", version="1.0.0", nodes=(Generated,), triggers=(TRIGGER,)).manifest()
    bad = dict(trigger.manifest())
    assert validate_plugin_manifest({**good, "triggers": [bad]}) != []


@pytest.mark.parametrize(
    "mangle",
    [
        lambda t: {**t, "extra": 1},
        lambda t: {**t, "endpoint": {**t["endpoint"], "id_source": "pointer"}},
        lambda t: {**t, "topics": []},
        lambda t: {k: v for k, v in t.items() if k != "label"},
    ],
)
def test_the_catalog_refuses_a_trigger_received_malformed(mangle: Any) -> None:
    good = Plugin(name="demo", version="1.0.0", nodes=(Generated,), triggers=(TRIGGER,)).manifest()
    assert validate_plugin_manifest({**good, "triggers": [mangle(good["triggers"][0])]}) != []
    assert validate_plugin_manifest({**good, "triggers": []}) != []  # only when set
    assert validate_plugin_manifest({**good, "triggers": [good["triggers"][0]] * 2}) != []  # each key once
