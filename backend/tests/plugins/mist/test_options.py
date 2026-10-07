# SPDX-License-Identifier: Apache-2.0
"""Mist pickers (plugins-3 D3, D19): a site-scope node's `site_id`, and an org resource's id where the map allows the
list at its collection's path, list their choices through the connection's read-only HTTP: one page of up to 1,000,
filtered by the typed text, which never enters a path."""

import dataclasses
import uuid
from typing import Any

import pytest

from dewpoint.plugins.mist import PLUGIN, policy
from dewpoint.sdk import FatalError, Node, Option, OptionsQuery, node_manifest
from tests.plugins.mist.fakes import ORG, FakeConnection, FakeHttp, FakeStep, Reply

SITES = [
    {"id": "b2c3d4e5-0000-4000-8000-000000000002", "name": "Paris"},
    {"id": "a1b2c3d4-0000-4000-8000-000000000001", "name": "amsterdam"},
    {"id": "c3d4e5f6-0000-4000-8000-000000000003"},
]


def node(type_: str) -> type[Node]:
    return next(n for n in PLUGIN.nodes if n.type == type_)


async def options(type_: str, field: str, text: str, script: Any) -> tuple[list[Option], FakeHttp]:
    http = FakeHttp(script)
    connection = FakeConnection(http)
    found = await node(type_)().options(FakeStep(connection), field, OptionsQuery(text, connection.id))  # type: ignore[arg-type]
    return found, http


def test_site_scope_nodes_pick_their_site_and_org_nodes_their_resource() -> None:
    assert node_manifest(node("mist.site_devices.get"))["options"] == ["site_id"]
    assert node_manifest(node("mist.org_wlans.update"))["options"] == ["wlan_id"]
    assert node_manifest(node("mist.org_guests.get"))["options"] == ["guest_mac"]
    assert "options" not in node_manifest(node("mist.org_wlans.list"))
    sites = [n for n in PLUGIN.nodes if getattr(n, "scope", None) == "site"]
    assert sites and all("site_id" in node_manifest(n)["options"] for n in sites)


async def test_the_site_picker_lists_the_orgs_sites_by_name() -> None:
    found, http = await options(
        "mist.site_devices.list", "site_id", "", {("GET", f"/api/v1/orgs/{ORG}/sites"): Reply(200, SITES)}
    )
    assert found == [
        Option("a1b2c3d4-0000-4000-8000-000000000001", "amsterdam"),
        Option("c3d4e5f6-0000-4000-8000-000000000003", "c3d4e5f6-0000-4000-8000-000000000003"),
        Option("b2c3d4e5-0000-4000-8000-000000000002", "Paris"),
    ]
    assert [(s.method, s.params) for s in http.sent] == [("GET", {"limit": 1000})]


async def test_the_typed_text_filters_and_never_enters_the_path() -> None:
    found, http = await options(
        "mist.site_devices.list", "site_id", "../PAR", {("GET", f"/api/v1/orgs/{ORG}/sites"): Reply(200, SITES)}
    )
    assert found == []
    found, http = await options(
        "mist.site_devices.list", "site_id", "par", {("GET", f"/api/v1/orgs/{ORG}/sites"): Reply(200, SITES)}
    )
    assert [o.label for o in found] == ["Paris"] and http.sent[0].url == f"/api/v1/orgs/{ORG}/sites"


async def test_a_wlan_is_labelled_by_its_ssid() -> None:
    wlans = [{"id": str(uuid.uuid4()), "ssid": "corp"}]
    found, _ = await options(
        "mist.org_wlans.get", "wlan_id", "", {("GET", f"/api/v1/orgs/{ORG}/wlans"): Reply(200, wlans)}
    )
    assert found == [Option(wlans[0]["id"], "corp")]


@pytest.mark.parametrize("answer", [{"results": []}, [{"name": "no id"}, {"id": 3}, "x"]])
async def test_entries_without_an_id_are_left_out_and_a_non_list_refused(answer: Any) -> None:
    script = {("GET", f"/api/v1/orgs/{ORG}/sites"): Reply(200, answer)}
    if isinstance(answer, list):
        assert (await options("mist.site_devices.list", "site_id", "", script))[0] == []
    else:
        with pytest.raises(FatalError):
            await options("mist.site_devices.list", "site_id", "", script)


async def test_another_field_or_no_connection_lists_nothing() -> None:
    with pytest.raises(FatalError) as e:
        await options("mist.site_devices.list", "query", "", {})
    assert e.value.code == "mist.no_options"
    kind = node("mist.site_devices.list")
    connection = FakeConnection(FakeHttp({}))
    with pytest.raises(FatalError) as e:
        await kind().options(FakeStep(connection), "site_id", OptionsQuery("", None))  # type: ignore[arg-type]
    assert e.value.code == "mist.connection_required"


async def test_a_list_the_map_no_longer_allows_lists_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    held = policy.PolicyMap(
        policy.load().oas_sha256,
        {**policy.load().entries, "listOrgSites": policy.Entry("GET", "/api/v1/orgs/{org_id}/sites", "held",
                                                                reason="unreviewed")},
    )  # fmt: skip
    monkeypatch.setattr(policy, "load", lambda: held)
    with pytest.raises(FatalError) as e:
        await options("mist.site_devices.list", "site_id", "", {})
    assert e.value.code == "mist.operation_unavailable"


async def test_a_picker_never_reads_a_route_that_is_always_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The review's L10: the list a picker reads passes the same check as any node's operation."""
    sites = policy.load().entries["listOrgSites"]
    moved = dataclasses.replace(sites, path="/api/v1/self")
    found = policy.PolicyMap(policy.load().oas_sha256, {**policy.load().entries, "listOrgSites": moved})
    monkeypatch.setattr(policy, "load", lambda: found)
    with pytest.raises(FatalError) as e:
        await options("mist.site_devices.list", "site_id", "", {})
    assert e.value.code == "mist.operation_unavailable"
