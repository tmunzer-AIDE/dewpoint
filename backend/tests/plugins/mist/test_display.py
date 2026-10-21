# SPDX-License-Identifier: Apache-2.0
"""What the editor shows of a Mist step beyond its rules (editor 4f-2, the Mist step design §4): each config's group
and widget at its root, its body's setting titles. All display metadata, so no contract hash moves: the pinned values
were computed on origin/main 5882c682, before any of it."""

import json
import pathlib
import re
from collections.abc import Iterator
from typing import Any

import pytest

from dewpoint.engine.registry.catalog import contract_hash
from dewpoint.plugins.mist import PLUGIN, oas
from dewpoint.plugins.mist.display import BODY_TERMS, UNION_TITLES, setting_title
from dewpoint.plugins.mist.schemas import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE
from dewpoint.plugins.mist.titles import TERMS, title, words

NODES = {f"{n['type']}@{n['version']}": n for n in PLUGIN.manifest()["nodes"]}
CONFIGS = {ref: n["config_schema"] for ref, n in NODES.items()}
PINNED = json.loads((pathlib.Path(__file__).parent / "contract_hashes.json").read_text())


def _entries(node: Any) -> Iterator[tuple[str, Any]]:
    """Each property entry under `node`, at every depth, with its name."""
    if isinstance(node, list):
        for sub in node:
            yield from _entries(sub)
    elif isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                yield from value.items()
            if key in SCHEMA_MAP and isinstance(value, dict):
                yield from _entries(list(value.values()))
            elif key in SCHEMA_ONE or key in SCHEMA_LIST:
                yield from _entries(value)


def _bodies() -> Iterator[tuple[str, Any]]:
    """Each curated or utility config's body and its `$defs`: the generic API steps' are left out (their body is any
    operation's)."""
    for ref, config in CONFIGS.items():
        if "body" in config["properties"] and not ref.startswith("mist.api."):
            yield ref, [config["properties"]["body"], *config.get("$defs", {}).values()]


def test_the_display_metadata_moves_no_contract_hash() -> None:
    assert {ref: contract_hash(n) for ref, n in NODES.items()} == PINNED


def test_every_step_names_its_group() -> None:
    groups = {ref: config["x-group"] for ref, config in CONFIGS.items()}
    assert {g["plugin"] for g in groups.values()} == {"Mist"}
    assert len({g["title"] for g in groups.values()}) == 85
    assert groups["mist.site_settings.update@1"]["title"] == "Site settings"
    assert groups["mist.org_wlans.create@1"]["title"] == "Org WLANs"
    assert groups["mist.org_wlan_templates.list@1"]["title"] == "Org WLAN templates"
    assert groups["mist.site_devices.bounce_port@1"]["title"] == "Site devices"
    assert groups["mist.const_webhook_topics.list@1"]["title"] == "Webhook topics"
    assert groups["mist.api.read@1"]["title"] == "API"


def test_each_step_of_a_resource_shares_its_group() -> None:
    by_resource: dict[str, set[str]] = {}
    for ref, config in CONFIGS.items():
        by_resource.setdefault(ref.split(".")[1], set()).add(config["x-group"]["title"])
    assert len(by_resource) == 85
    assert all(len(titles) == 1 for titles in by_resource.values())


def test_updates_and_creates_name_their_widget() -> None:
    widgets = {ref: config.get("x-widget") for ref, config in CONFIGS.items()}
    updates = {ref for ref, w in widgets.items() if w == "update"}
    creates = {ref for ref, w in widgets.items() if w == "create"}
    assert len(updates) == 40 and len(creates) == 36
    assert {w for w in widgets.values()} == {None, "update", "create"}
    assert all({"body", "mode", "clear"} <= set(CONFIGS[ref]["properties"]) for ref in updates)
    assert all("body" in CONFIGS[ref]["required"] for ref in creates)
    assert {"mist.site_settings.update@1", "mist.site_devices.update@1", "mist.org_wlans.update@1"} <= updates
    assert {"mist.org_wlans.create@1", "mist.org_device_profiles.create@1"} <= creates
    assert widgets["mist.site_devices.bounce_port@1"] is None
    assert widgets["mist.api.write@1"] is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ssid", "SSID"),
        ("vlan_id", "VLAN ID"),
        ("allowed_vlan_ids", "Allowed VLAN IDs"),
        ("min_rogue_rssi", "Min rogue RSSI"),
        ("acl_tags", "ACL tags"),
        ("auto_upgrade", "Auto upgrade"),
        ("allow_mist", "Allow Mist"),
        ("ap_matching", "AP matching"),
        ("poe_disabled", "PoE disabled"),
        ("dns_servers", "DNS servers"),
        ("ip6", "IPv6"),
        ("radius_config", "RADIUS config"),
        ("use_dot1x", "Use dot1x"),  # as Mist writes it
    ],
)
def test_a_setting_is_titled_by_its_name_in_words(name: str, expected: str) -> None:
    assert setting_title(name) == expected


def test_node_and_path_titles_keep_their_own_terms() -> None:
    """The body's terms stay out of the signed-off titles: `radius` and `vlan` stay lower case there."""
    assert title("vlan_id") == "Vlan ID"
    assert title("getSiteRadiusConfig") == "Get site radius config"
    assert set(TERMS) < set(BODY_TERMS)


def test_every_setting_of_a_body_has_a_title() -> None:
    untitled = sorted({f"{ref}: {name}" for ref, body in _bodies() for name, e in _entries(body) if "title" not in e})
    assert untitled == []


def test_site_settings_titles() -> None:
    config = CONFIGS["mist.site_settings.update@1"]
    rogue = config["$defs"]["site_rogue"]["properties"]
    assert rogue["min_rogue_rssi"]["title"] == "Min rogue RSSI"
    assert rogue["whitelisted_ssids"]["title"] == "Whitelisted SSIDs"


def test_a_device_body_offers_titled_kinds() -> None:
    for ref, union in (
        ("mist.site_devices.update@1", "mist_device"),
        ("mist.org_device_profiles.update@1", "deviceprofile"),
        ("mist.org_device_profiles.create@1", "deviceprofile"),
    ):
        defs = CONFIGS[ref]["$defs"]
        branches = defs[union].get("anyOf") or defs[union]["oneOf"]
        assert defs[union]["title"] == UNION_TITLES[union]
        assert sorted(b["title"] for b in branches) == ["AP", "Gateway", "Switch"]


def test_no_shared_component_gains_a_title() -> None:
    """A title on a component would label every setting reaching it: only the two unions get one."""
    components = oas.document()["components"]["schemas"]
    gained = sorted(
        {
            f"{ref}: {name}"
            for ref, config in CONFIGS.items()
            for name, schema in config.get("$defs", {}).items()
            if name not in UNION_TITLES and schema.get("title") != components.get(name, {}).get("title")
        }
    )
    assert gained == []


def test_every_body_term_is_reached_by_a_setting() -> None:
    """Reachability only, against a misspelled or dead key: the table above pins how each term is written."""
    found = {" ".join(w.lower() for w in words(name)) for _, body in _bodies() for name, _ in _entries(body)}

    def reached(key: str) -> bool:
        return any(re.search(rf"(?:^| ){re.escape(key)}s?(?: |$)", text) for text in found)

    assert [key for key in BODY_TERMS if key not in TERMS and not reached(key)] == []
