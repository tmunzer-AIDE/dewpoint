# SPDX-License-Identifier: Apache-2.0
"""What the editor shows of a Mist step beyond its schema's rules (editor 4f-2, the Mist step design §4): its group in
the add-step picker, the widget its config takes, and its settings' titles. All of it is display metadata the contract
hash drops (`x-group`, `x-widget`, `title`), so no step's version changes.

- The group is the step's resource (`mist.<resource>.<action>`), titled; it sits at the config's root, the one place a
  plugin can put it without moving the hash.
- A setting's title is its name in words: Mist's terms as `titles` writes them, and the terms only a body uses (SSID,
  VLAN…), which node and path titles don't take (they stay as signed off: `radius`, `dot1x`). It goes on the setting's
  own entry, never on a shared `$defs` component that other settings reach too.
- A union whose every branch allows one `type` (a device's AP, switch or gateway) titles each branch by that value."""

from collections.abc import Mapping
from typing import Any

from dewpoint.plugins.mist.schemas import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE
from dewpoint.plugins.mist.titles import TERMS, title

PLUGIN_TITLE = "Mist"
# A resource whose name, in words, isn't how the picker should say it.
GROUP_TITLES = {
    "api": "API",
    "const_webhook_topics": "Webhook topics",
    "org_aamw_profiles": "Org AAMW profiles",
    "org_secintel_profiles": "Org SecIntel profiles",
}
# A body's terms, beyond `titles`' own: how Mist writes them.
BODY_TERMS: dict[str, str] = {
    **TERMS,
    **{a: a.upper() for a in (
        "acl bfd cli dscp fqdn http igmp ike ip lacp lan lte mqtt mtu nas nat ntp oob radius sla snmp ssdp ssid stp"
        " tacacs tls ttl usb uuid uwb vlan vrf vrrp wds wpa3"
    ).split()},
    "coa": "CoA",
    "ip6": "IPv6",
    "ipsec": "IPsec",
    "ipv6": "IPv6",
    "mdns": "mDNS",
    "poe": "PoE",
    "pppoe": "PPPoE",
    "qos": "QoS",
    "radsec": "RadSec",
    "voip": "VoIP",
}  # fmt: skip
# A union a body is, titled for the kind it offers ("Kind of device").
UNION_TITLES = {"mist_device": "Device", "deviceprofile": "Device profile"}


def group_title(resource: str) -> str:
    return GROUP_TITLES.get(resource) or title(resource)


def setting_title(name: str) -> str:
    return title(name, BODY_TERMS)


def displayed(type_: str, schema: dict[str, Any], widget: str | None = None) -> dict[str, Any]:
    """`schema`, a step's config, with its group at its root, and its widget when it takes one."""
    schema["x-group"] = {"plugin": PLUGIN_TITLE, "title": group_title(type_.split(".")[1])}
    if widget is not None:
        schema["x-widget"] = widget
    return schema


def titled(schema: dict[str, Any]) -> dict[str, Any]:
    """`schema`, a step's config, with a title on each of its body's settings, at every depth, and on the branches and
    unions of a body that offers kinds."""
    defs = schema.get("$defs", {})
    for name, union in UNION_TITLES.items():
        if name in defs:
            defs[name]["title"] = union
    for node in [schema["properties"].get("body"), *defs.values()]:
        _titled(node, defs)
    return schema


def _titled(node: Any, defs: Mapping[str, Any]) -> None:
    if isinstance(node, list):
        for sub in node:
            _titled(sub, defs)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):
            for name, sub in value.items():
                if isinstance(sub, dict):
                    sub.setdefault("title", setting_title(name))
        if key in ("anyOf", "oneOf") and isinstance(value, list):
            kinds = [kind for branch in value if (kind := _kind(branch, defs)) is not None]
            if kinds and len(kinds) == len(value):
                for branch, kind in zip(value, kinds, strict=True):
                    branch.setdefault("title", setting_title(kind))
        if key in SCHEMA_ONE or key in SCHEMA_LIST or key in SCHEMA_MAP:
            _titled(list(value.values()) if key in SCHEMA_MAP and isinstance(value, dict) else value, defs)


def _kind(branch: Any, defs: Mapping[str, Any]) -> str | None:
    """The one value a union's branch allows its `type`, if it allows one."""
    target = _target(branch, defs)
    kind = _target(target.get("properties", {}).get("type"), defs) if isinstance(target, Mapping) else None
    values = kind.get("enum") if isinstance(kind, Mapping) else None
    return values[0] if isinstance(values, list) and len(values) == 1 and isinstance(values[0], str) else None


def _target(node: Any, defs: Mapping[str, Any]) -> Any:
    seen: set[str] = set()
    while isinstance(node, Mapping) and isinstance(node.get("$ref"), str) and node["$ref"].startswith("#/$defs/"):
        name = node["$ref"][len("#/$defs/") :]
        if name in seen or name not in defs:
            break
        seen.add(name)
        node = defs[name]
    return node
