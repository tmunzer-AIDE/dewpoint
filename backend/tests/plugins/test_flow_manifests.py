# SPDX-License-Identifier: Apache-2.0
from typing import Any

from dewpoint.plugins.flow import PLUGIN
from dewpoint.sdk import Plugin
from dewpoint.sdk.fields import KINDS, LITERAL, SENSITIVE
from tests.support.plugins.testkit import TESTKIT


def _nodes(plugin: Plugin) -> dict[str, dict[str, Any]]:
    return {f"{n['type']}@{n['version']}": n for n in plugin.manifest()["nodes"]}


def test_flow_plugin_declares_every_control_node() -> None:
    nodes = _nodes(PLUGIN)
    assert set(nodes) == {
        "flow.if@1",
        "flow.switch@1",
        "flow.loop@1",
        "flow.filter@1",
        "flow.set_variables@1",
        "flow.delay@1",
        "flow.wait_until@1",
        "flow.stop@1",
        "flow.fail@1",
        "flow.run_workflow@1",
        "flow.transform@1",
    }
    assert all(n["kind"] == "control" for n in nodes.values())


def test_control_contracts() -> None:
    n = _nodes(PLUGIN)
    assert n["flow.if@1"]["ports"] == ["true", "false"]
    assert n["flow.switch@1"]["dynamic_ports"] == "cases" and n["flow.switch@1"]["ports"] == ["default"]
    assert n["flow.loop@1"]["ports"] == ["body", "done"]
    assert n["flow.stop@1"]["ports"] == [] and n["flow.fail@1"]["ports"] == []
    loop = n["flow.loop@1"]["config_schema"]["properties"]
    assert loop["concurrency"][LITERAL] is True and loop["item_cap"]["maximum"] == 10_000
    assert n["flow.filter@1"]["config_schema"]["properties"]["predicate"][KINDS] == ["cel"]
    case = n["flow.switch@1"]["config_schema"]["$defs"]["SwitchCase"]["properties"]["port"]
    assert case[LITERAL] is True
    assert n["flow.run_workflow@1"]["config_schema"]["properties"]["workflow_id"][LITERAL] is True


def test_testkit_is_a_valid_plugin() -> None:
    nodes = _nodes(TESTKIT)
    assert nodes["testkit.ambiguous_send@1"]["side_effect"] == "ambiguous"
    assert nodes["testkit.sensitive@1"]["output_schema"]["properties"]["secret_value"][SENSITIVE] is True
    assert nodes["testkit.echo@1"]["output_schema"]["required"] == ["value"]


def test_every_flow_node_has_an_icon() -> None:
    """Flow completion (plugins-3 D19): icons are display metadata, so flow@1's hashes don't move (pinned)."""
    icons = {f"{n['type']}@{n['version']}": n.get("icon") for n in PLUGIN.manifest()["nodes"]}
    assert all(isinstance(icon, str) and icon for icon in icons.values()), icons
    assert len(set(icons.values())) == len(icons)


def test_conditions_are_shown_as_cel() -> None:
    nodes = {n["type"]: n["config_schema"] for n in PLUGIN.manifest()["nodes"]}
    assert nodes["flow.if"]["properties"]["condition"]["x-widget"] == "cel"
    assert nodes["flow.filter"]["properties"]["predicate"]["x-widget"] == "cel"
    assert nodes["flow.switch"]["$defs"]["SwitchCase"]["properties"]["when"]["x-widget"] == "cel"


def _field_titles(schema: dict[str, Any]) -> dict[str, Any]:
    """Each config field's title, a nested model's fields as `Model.field`."""
    out = {name: sub.get("title") for name, sub in schema.get("properties", {}).items()}
    for model, sub in schema.get("$defs", {}).items():
        out |= {f"{model}.{name}": p.get("title") for name, p in sub.get("properties", {}).items()}
    return out


def test_every_config_field_has_a_written_title() -> None:
    """The step drawer labels a field by its title (4c-1), so none is left to pydantic's `Duration S`. Titles are
    display annotations: flow@1's contract hashes don't move (pinned)."""
    found = {n["type"]: _field_titles(n["config_schema"]) for n in PLUGIN.manifest()["nodes"]}
    assert found == {
        "flow.if": {"condition": "Condition"},
        "flow.switch": {"cases": "Cases", "SwitchCase.port": "Port name", "SwitchCase.when": "Condition"},
        "flow.loop": {
            "items": "Items",
            "concurrency": "Items at a time, at most",
            "item_cap": "Items, at most",
            "on_item_error": "When an item fails",
            "collect": "Output for each item",
        },
        "flow.filter": {"items": "Items", "predicate": "Keep an item when"},
        "flow.set_variables": {"assignments": "Variables"},
        "flow.delay": {"duration_s": "Duration, in seconds"},
        "flow.wait_until": {"until": "Date and time"},
        "flow.stop": {},
        "flow.fail": {"message": "Message"},
        "flow.run_workflow": {"workflow_id": "Workflow", "input": "Input"},
        "flow.transform": {"fields": "Fields"},
    }
