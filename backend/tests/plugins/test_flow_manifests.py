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
