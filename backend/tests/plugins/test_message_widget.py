# SPDX-License-Identifier: Apache-2.0
"""The message composer's hint (editor 4f-1; the message composer design §4.1): every step whose config is the SDK's
message carries `x-widget: "message"` at its config's root. It's a display annotation, so no contract hash moves: the
values were computed on origin/main b9549821, before the hint."""

import importlib
from typing import Any

from dewpoint.engine.registry.catalog import contract_hash
from dewpoint.sdk.messages import Message

PINNED = {
    "slack.send_message@1": "66a842a5c32312e78d4f123b338aa4a44d6e0ab26b046684369e2e188e05ccd6",
    "teams.send_message@1": "0f4f484edd9c0b87e082eadbbbbca69eead00c3dd70694067bc8a67c12c8cc7e",
    "google_chat.send_message@1": "4024fcb7b75923c98611211a48e2cce09a3deb6864afe215d676fd3abde9ff57",
    "webhook.send_message@1": "7d1c73c599237c7c84434830b387d916fac57de1f1ac502eb683b3cdfc72ba9e",
    "email.send_message@1": "7617c7f8bea98effea3168a6e2642a93389fabe44e4d3ebb5c1231529c0bf1cd",
    "syslog.send_message@1": "28a01dc562d1e8b3b0899f287e328b03e82f94754a9cb8ca4a92648159874720",
    "pagerduty.trigger_alert@1": "58564ce79266bdb0d5a9f00266d55ae8f161a3cc223c6f157c51b02211cf73a7",
    "servicenow.create_incident@1": "4381278a184282b832f190c8759fc637ac227c331e94c5316ba1bc4eee61d00c",
}
PLUGINS = ("slack", "teams", "google_chat", "webhook", "email", "syslog", "pagerduty", "servicenow")


def _message_nodes() -> dict[str, dict[str, Any]]:
    """Each node whose config holds the message's five properties."""
    nodes: dict[str, dict[str, Any]] = {}
    for name in PLUGINS:
        for node in importlib.import_module(f"dewpoint.plugins.{name}").PLUGIN.manifest()["nodes"]:
            if {"title", "text", "fields", "links", "severity"} <= set(node["config_schema"].get("properties", {})):
                nodes[f"{node['type']}@{node['version']}"] = node
    return nodes


def test_every_message_step_shows_the_composer() -> None:
    nodes = _message_nodes()
    assert set(nodes) == set(PINNED)
    assert {ref: n["config_schema"].get("x-widget") for ref, n in nodes.items()} == dict.fromkeys(PINNED, "message")


def test_the_hint_moves_no_contract_hash() -> None:
    assert {ref: contract_hash(n) for ref, n in _message_nodes().items()} == PINNED


def test_a_config_built_on_the_message_carries_the_hint() -> None:
    """A third-party plugin's config on the SDK's message gets the composer too (built-in widgets only, arch §101)."""

    class Theirs(Message):
        channel: str

    assert Theirs.model_json_schema()["x-widget"] == "message"
