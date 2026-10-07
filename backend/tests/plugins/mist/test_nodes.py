# SPDX-License-Identifier: Apache-2.0
"""One node type per curated Mist operation (plugins-3 D23, D16, D15), generated from the policy map and the vendored
OAS: config (the connection, path values, query, body, a page cap, an update's mode) and output (the 2xx answer)
schemas, the map's side effect and capability; each kind's run through the connection's HTTP."""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.mist import PLUGIN, policy
from dewpoint.plugins.mist.nodes import MistOperation
from dewpoint.plugins.mist.schemas import SCHEMA_LIST, SCHEMA_MAP, SCHEMA_ONE
from dewpoint.sdk import FatalError, Node, node_manifest
from dewpoint.sdk.fields import CONNECTION, LITERAL, SENSITIVE
from tests.plugins.mist.fakes import ORG, SITE, FakeConnection, FakeHttp, FakeStep, Reply, Sent

WLAN = "7b2c4d6e-8f10-4a2b-9c3d-4e5f6a7b8c9d"


def node(type_: str) -> type[Node]:
    return next(n for n in PLUGIN.nodes if n.type == type_)


def walk(schema: Any) -> Iterator[dict[str, Any]]:
    """Every schema object in `schema`, its `$defs` included: schema positions only, never a property's name."""
    stack = [schema]
    while stack:
        here = stack.pop()
        if not isinstance(here, dict):
            continue
        yield here
        for key, value in here.items():
            if key in SCHEMA_ONE:
                stack.append(value)
            elif key in SCHEMA_LIST and isinstance(value, list):
                stack.extend(value)
            elif (key in SCHEMA_MAP or key == "$defs") and isinstance(value, dict):
                stack.extend(value.values())


async def run(type_: str, config: dict[str, Any], script: Any, attempt: int = 1) -> tuple[Any, FakeHttp]:
    http = FakeHttp(script)
    connection = FakeConnection(http)
    kind = node(type_)
    value = kind.Config.model_validate({"connection": str(connection.id), **config})
    out = await kind().run(FakeStep(connection, attempt=attempt), value)  # type: ignore[arg-type]
    return out.model_dump(mode="json"), http


def test_every_allowed_operation_has_its_node_and_no_other() -> None:
    entries = policy.load().entries
    curated = {e.nodes[0]: op for op, e in entries.items() if e.state == "allowed" and e.utility is None}
    generated = {n.type: n for n in PLUGIN.nodes if issubclass(n, MistOperation)}  # a utility's: test_utilities
    assert set(generated) == set(curated)
    for type_, n in generated.items():
        e = entries[curated[type_]]
        assert (n.operation, n.version, n.side_effect.value, n.capabilities) == (  # type: ignore[attr-defined]
            curated[type_],
            1,
            e.side_effect,
            frozenset({e.capability}),
        )
        assert n.credentials == ("mist",)


def test_the_plugin_manifest_passes_the_catalog() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []


def test_a_config_names_the_connection_and_the_path_values_but_never_the_org() -> None:
    schema = node_manifest(node("mist.org_wlans.get"))["config_schema"]
    assert schema["properties"]["connection"][CONNECTION] == "mist" and schema["properties"]["connection"][LITERAL]
    assert schema["properties"]["wlan_id"]["format"] == "uuid"
    assert "org_id" not in schema["properties"] and schema["additionalProperties"] is False
    assert set(schema["required"]) == {"connection", "wlan_id"}
    site = node_manifest(node("mist.site_devices.get"))["config_schema"]
    assert {"site_id", "device_id"} <= set(site["required"])


def test_a_paged_list_takes_a_page_size_and_a_cap_but_not_a_page() -> None:
    schema = node_manifest(node("mist.org_sites.list"))["config_schema"]
    assert set(schema["properties"]["query"]["properties"]) == {"limit"}
    assert schema["properties"]["max_pages"] == {"type": "integer", "minimum": 1, "maximum": 10, "default": 1,
                                                  "title": "Pages, at most"}  # fmt: skip
    insights = node_manifest(node("mist.site_insights.get"))["config_schema"]
    assert "page" in insights["properties"]["query"]["properties"] and "max_pages" not in insights["properties"]
    assert "query" in insights["required"]  # `metrics` is required


def test_array_query_values_are_left_out() -> None:
    assert (
        "labels"
        not in node_manifest(node("mist.org_usermacs.search"))["config_schema"]["properties"]["query"]["properties"]
    )


def test_an_update_takes_a_partial_body_a_mode_and_fields_to_clear() -> None:
    schema = node_manifest(node("mist.org_wlans.update"))["config_schema"]
    assert schema["properties"]["mode"] == {"enum": ["merge", "replace"], "default": "merge", "title": "Mode"}
    assert "ssid" in schema["properties"]["clear"]["items"]["enum"]
    assert not any("required" in s for s in walk(schema["properties"]["body"])) and not any(
        "required" in s for s in walk(schema["$defs"])
    )
    create = node_manifest(node("mist.org_wlans.create"))["config_schema"]
    assert "body" in create["required"] and "mode" not in create["properties"]


def test_secret_named_fields_are_sensitive_in_config_and_output() -> None:
    m = node_manifest(node("mist.org_psks.create"))
    assert m["config_schema"]["$defs"]["psk"]["properties"]["passphrase"][SENSITIVE] is True
    out = node_manifest(node("mist.org_psks.get"))["output_schema"]
    assert out["properties"]["passphrase"][SENSITIVE] is True
    assert SENSITIVE not in out["properties"]["name"]
    hooks = node_manifest(node("mist.org_webhooks.get"))["output_schema"]
    assert hooks["properties"]["secret"][SENSITIVE] is True


def test_outputs_keep_the_shape_and_drop_what_a_provider_outgrows() -> None:
    for n in PLUGIN.nodes:
        out = node_manifest(n)["output_schema"]
        assert out["type"] == "object"
        for s in walk(out):
            assert not {"format", "enum", "pattern", "oneOf", "minimum", "maxLength", "const", "examples"} & set(s)
            if s.get("additionalProperties") is False:  # only the wrappers the nodes make are closed
                assert set(s.get("properties", {})) in (
                    set(),
                    {"already_absent"},
                    {"results", "total", "truncated"},
                    {"status", "body"},
                )


def test_a_list_answers_its_results_total_and_whether_it_was_cut() -> None:
    out = node_manifest(node("mist.org_sites.list"))["output_schema"]
    assert set(out["required"]) == {"results", "total", "truncated"}
    search = node_manifest(node("mist.org_alarms.search"))["output_schema"]
    assert "next" not in search["properties"] and "truncated" in search["required"]


async def test_a_get_reads_the_object_under_the_connections_org() -> None:
    out, http = await run(
        "mist.org_wlans.get", {"wlan_id": WLAN}, {("GET", f"/api/v1/orgs/{ORG}/wlans/{WLAN}"): Reply(200, {"id": WLAN})}
    )
    assert out == {"id": WLAN} and [s.method for s in http.sent] == ["GET"]


async def test_a_site_scope_node_checks_its_site_first() -> None:
    device = str(uuid.uuid4())
    out, http = await run(
        "mist.site_devices.get",
        {"site_id": SITE, "device_id": device},
        {
            ("GET", f"/api/v1/sites/{SITE}"): Reply(200, {"id": SITE, "org_id": ORG}),
            ("GET", f"/api/v1/sites/{SITE}/devices/{device}"): Reply(200, {"id": device, "type": "ap"}),
        },
    )
    assert out["id"] == device and [s.url for s in http.sent] == [
        f"/api/v1/sites/{SITE}", f"/api/v1/sites/{SITE}/devices/{device}"
    ]  # fmt: skip


async def test_a_site_of_another_org_sends_nothing_more() -> None:
    http = FakeHttp({("GET", f"/api/v1/sites/{SITE}"): Reply(200, {"org_id": "x"})})
    connection = FakeConnection(http)
    kind = node("mist.site.delete")
    value = kind.Config.model_validate({"connection": str(connection.id), "site_id": SITE})
    with pytest.raises(FatalError) as e:
        await kind().run(FakeStep(connection), value)  # type: ignore[arg-type]
    assert e.value.code == "mist.site_outside_org" and [s.method for s in http.sent] == ["GET"]


async def test_a_list_pages_up_to_its_cap() -> None:
    def script(sent: Sent) -> Reply:
        assert sent.params is not None
        page = sent.params["page"]
        return Reply(200, [{"id": page}], {"X-Page-Limit": "1", "X-Page-Page": str(page), "X-Page-Total": "3"})

    out, http = await run("mist.org_sites.list", {"query": {"limit": 1}, "max_pages": 2}, script)
    assert out == {"results": [{"id": 1}, {"id": 2}], "total": 3, "truncated": True}


async def test_a_search_follows_next() -> None:
    path = f"/api/v1/orgs/{ORG}/alarms/search"
    script = {("GET", path): [Reply(200, {"results": [{"id": "a"}], "next": f"{path}?x=1", "total": 2}),
                              Reply(200, {"results": [{"id": "b"}], "total": 2})]}  # fmt: skip
    out, http = await run("mist.org_alarms.search", {"max_pages": 3}, script)
    assert out == {"results": [{"id": "a"}, {"id": "b"}], "total": 2, "truncated": False}


async def test_a_create_posts_its_body() -> None:
    out, http = await run(
        "mist.org_wlans.create",
        {"body": {"ssid": "corp"}},
        {("POST", f"/api/v1/orgs/{ORG}/wlans"): Reply(200, {"id": WLAN, "ssid": "corp"})},
    )
    assert out == {"id": WLAN, "ssid": "corp"} and http.sent[0].json == {"ssid": "corp"}


CURRENT = {
    "id": WLAN,
    "ssid": "corp",
    "auth": {"type": "psk", "pairwise": ["wpa2-ccmp"]},
    "vlan_id": 10,
    "bands": ["24"],
}


async def test_a_merge_update_sends_each_touched_structure_whole() -> None:
    path = f"/api/v1/orgs/{ORG}/wlans/{WLAN}"
    out, http = await run(
        "mist.org_wlans.update",
        {"wlan_id": WLAN, "body": {"auth": {"type": "open"}, "bands": ["5"]}, "clear": ["vlan_id"]},
        {("GET", path): Reply(200, CURRENT), ("PUT", path): Reply(200, {"id": WLAN})},
    )
    assert [s.method for s in http.sent] == ["GET", "PUT"]
    assert http.sent[1].json == {"auth": {"type": "open", "pairwise": ["wpa2-ccmp"]}, "bands": ["5"], "vlan_id": None}


async def test_a_replace_update_sends_only_what_is_set() -> None:
    path = f"/api/v1/orgs/{ORG}/wlans/{WLAN}"
    out, http = await run(
        "mist.org_wlans.update",
        {"wlan_id": WLAN, "mode": "replace", "body": {"auth": {"type": "open"}}, "clear": ["vlan_id"]},
        {("PUT", path): Reply(200, {"id": WLAN})},
    )
    assert [s.method for s in http.sent] == ["PUT"] and http.sent[0].json == {"auth": {"type": "open"}, "vlan_id": None}


async def test_a_field_both_set_and_cleared_sends_nothing() -> None:
    with pytest.raises(FatalError) as e:
        await run("mist.org_wlans.update", {"wlan_id": WLAN, "body": {"vlan_id": 3}, "clear": ["vlan_id"]}, {})
    assert e.value.code == "mist.conflicting_change"


async def test_an_update_with_nothing_to_change_sends_nothing() -> None:
    with pytest.raises(FatalError) as e:
        await run("mist.org_wlans.update", {"wlan_id": WLAN, "body": {}}, {})
    assert e.value.code == "mist.nothing_to_change"


async def test_a_delete_404_is_absent_only_on_a_retry() -> None:
    path = f"/api/v1/orgs/{ORG}/wlans/{WLAN}"
    out, _ = await run("mist.org_wlans.delete", {"wlan_id": WLAN}, {("DELETE", path): Reply(200)})
    assert out == {"already_absent": False}
    with pytest.raises(FatalError) as e:
        await run("mist.org_wlans.delete", {"wlan_id": WLAN}, {("DELETE", path): Reply(404)})
    assert e.value.code == "mist.not_found"
    out, _ = await run("mist.org_wlans.delete", {"wlan_id": WLAN}, {("DELETE", path): Reply(404)}, attempt=2)
    assert out == {"already_absent": True}


async def test_an_action_posts_and_answers_nothing() -> None:
    alarm = str(uuid.uuid4())
    out, http = await run(
        "mist.org_alarms.ack",
        {"alarm_id": alarm, "body": {"note": "seen"}},
        {("POST", f"/api/v1/orgs/{ORG}/alarms/{alarm}/ack"): Reply(200, {"ignored": True})},
    )
    assert out == {} and http.sent[0].json == {"note": "seen"}


async def test_an_operation_the_map_no_longer_allows_sends_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    held = policy.PolicyMap(
        policy.load().oas_sha256,
        {**policy.load().entries, "getOrgWLAN": policy.Entry("GET", "/api/v1/orgs/{org_id}/wlans/{wlan_id}", "held",
                                                              reason="unreviewed")},
    )  # fmt: skip
    monkeypatch.setattr(policy, "load", lambda: held)
    with pytest.raises(FatalError) as e:
        await run("mist.org_wlans.get", {"wlan_id": WLAN}, {})
    assert e.value.code == "mist.operation_unavailable"


async def test_a_partial_update_of_a_typed_union_needs_no_type() -> None:
    """The review's L7: a device's body is one of an AP's, a switch's or a gateway's; partial, every branch fits."""
    device = str(uuid.uuid4())
    path = f"/api/v1/sites/{SITE}/devices/{device}"
    out, http = await run(
        "mist.site_devices.update",
        {"site_id": SITE, "device_id": device, "mode": "replace", "body": {"name": "ap-2"}},
        {("GET", f"/api/v1/sites/{SITE}"): Reply(200, {"org_id": ORG}), ("PUT", path): Reply(200, {"id": device})},
    )
    assert http.sent[1].json == {"name": "ap-2"}


async def test_an_unpaged_list_that_takes_a_limit_says_when_it_may_be_cut() -> None:
    """The review's L3: a full answer may have more, at the asked limit or Mist's documented default of 100."""
    path = f"/api/v1/sites/{SITE}/stats/clients"
    site = ("GET", f"/api/v1/sites/{SITE}")
    full, _ = await run("mist.site_wireless_client_stats.list", {"site_id": SITE, "query": {"limit": 2}},
                        {site: Reply(200, {"org_id": ORG}), ("GET", path): Reply(200, [{}, {}])})  # fmt: skip
    short, _ = await run("mist.site_wireless_client_stats.list", {"site_id": SITE},
                         {site: Reply(200, {"org_id": ORG}), ("GET", path): Reply(200, [{}] * 99)})  # fmt: skip
    default, _ = await run("mist.site_wireless_client_stats.list", {"site_id": SITE},
                           {site: Reply(200, {"org_id": ORG}), ("GET", path): Reply(200, [{}] * 100)})  # fmt: skip
    assert (full["truncated"], short["truncated"], default["truncated"]) == (True, False, True)


def test_a_merge_update_warns_of_the_race_it_cant_prevent() -> None:
    """The review's L4 (D15): Mist's PUT has no version check, so the warning always shows."""
    assert "overwritten" in node("mist.org_wlans.update").description
    assert "overwritten" not in node("mist.org_wlans.get").description
