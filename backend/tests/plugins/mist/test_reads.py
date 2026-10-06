# SPDX-License-Identifier: Apache-2.0
"""Auxiliary reads (the owner's review of the 3b-1 checkpoint, O2): a request a node sends for an operation other than
its own (the site check's `getSiteInfo`, an update's merge read, a picker's list) is one the map lists for that node's
operation (`reads`) and allows, checked before anything is sent; a site-scope operation can't be allowed unless its site
check is."""

import dataclasses
import uuid
from typing import Any

import pytest

from dewpoint.plugins.mist import PLUGIN, oas, policy, reviews
from dewpoint.sdk import FatalError, OptionsQuery
from tests.plugins.mist.fakes import ORG, SITE, FakeConnection, FakeHttp, FakeStep, Reply

WLAN = "7b2c4d6e-8f10-4a2b-9c3d-4e5f6a7b8c9d"


def node(type_: str) -> Any:
    return next(n for n in PLUGIN.nodes if n.type == type_)


def test_each_allowed_operation_lists_the_reads_it_makes() -> None:
    entries = policy.load().entries
    for op_id, e in entries.items():
        if e.state != "allowed":
            assert e.reads == ()
            continue
        assert all(entries[r].state == "allowed" for r in e.reads), op_id
        assert ("getSiteInfo" in e.reads) == (e.scope == "site"), op_id
    assert entries["updateOrgWlan"].reads == ("getOrgWLAN", "listOrgWlans")  # its merge, its picker
    assert entries["getSiteDevice"].reads == ("getSiteInfo", "listOrgSites")
    assert entries["listOrgWlans"].reads == ()


def test_a_site_operation_cant_be_allowed_without_its_site_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reviews, "HELD", {**reviews.HELD, "getSiteInfo": "held for the test"})
    monkeypatch.setattr(reviews, "CURATED", tuple(r for r in reviews.CURATED if r[0] != "getSiteInfo"))
    with pytest.raises(reviews.ReviewError, match="getSiteInfo"):
        reviews.make_map()


def holding(monkeypatch: pytest.MonkeyPatch, *ops: str) -> None:
    entries = dict(policy.load().entries)
    for op in ops:
        entries[op] = dataclasses.replace(entries[op], state="held", nodes=(), capability=None, scope=None,
                                          side_effect=None, evidence=None, reads=(), reason="held")  # fmt: skip
    found = policy.PolicyMap(policy.load().oas_sha256, entries)
    monkeypatch.setattr(policy, "load", lambda: found)


async def test_a_held_site_check_stops_every_site_node_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    holding(monkeypatch, "getSiteInfo")
    device = str(uuid.uuid4())
    http = FakeHttp({})
    connection = FakeConnection(http)
    for type_, config in (
        ("mist.site_devices.get", {"site_id": SITE, "device_id": device}),
        ("mist.api.read", {"path": f"/api/v1/sites/{SITE}/stats/devices"}),
    ):
        kind = node(type_)
        value = kind.Config.model_validate({"connection": str(connection.id), **config})
        for call in (kind().run, kind().simulate):
            with pytest.raises(FatalError) as e:
                await call(FakeStep(connection), value)
            assert e.value.code == "mist.operation_unavailable", type_
    assert http.sent == []


async def test_a_held_merge_read_stops_a_merge_but_not_a_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    holding(monkeypatch, "getOrgWLAN")
    path = f"/api/v1/orgs/{ORG}/wlans/{WLAN}"
    http = FakeHttp({("PUT", path): Reply(200, {"id": WLAN})})
    connection = FakeConnection(http)
    kind = node("mist.org_wlans.update")
    merge = kind.Config.model_validate({"connection": str(connection.id), "wlan_id": WLAN, "body": {"ssid": "x"}})
    with pytest.raises(FatalError) as e:
        await kind().run(FakeStep(connection), merge)
    assert e.value.code == "mist.operation_unavailable" and http.sent == []
    replace = kind.Config.model_validate(
        {"connection": str(connection.id), "wlan_id": WLAN, "mode": "replace", "body": {"ssid": "x"}}
    )
    await kind().run(FakeStep(connection), replace)
    assert [s.method for s in http.sent] == ["PUT"]


async def test_a_held_list_stops_its_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    holding(monkeypatch, "listOrgWlans")
    connection = FakeConnection(FakeHttp({}))
    with pytest.raises(FatalError) as e:
        await node("mist.org_wlans.get")().options(FakeStep(connection), "wlan_id", OptionsQuery("", connection.id))
    assert e.value.code == "mist.operation_unavailable" and connection.http.sent == []


def test_the_reads_are_the_descriptions_operations() -> None:
    ops = oas.operations()
    assert all(r in ops and ops[r].method == "GET" for e in policy.load().entries.values() for r in e.reads)
