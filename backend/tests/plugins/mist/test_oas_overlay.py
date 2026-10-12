# SPDX-License-Identifier: Apache-2.0
"""The OAS overlay (the owner's request after the read-only smoke run of 2026-10-07): until the upstream description
matches Mist's answers, reviewed patches, each citing that run, are laid over the vendored file when it's read. The
file itself stays pinned; a patch whose target no longer reads as it expects fails loudly, so a re-vendored, fixed
description retires it."""

import copy
import json
from importlib import resources
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from dewpoint.plugins.mist import PLUGIN, oas
from dewpoint.plugins.mist.nodes import MistOperation, fixture_of
from dewpoint.sdk import node_manifest


def node(type_: str) -> type[MistOperation]:
    found = next(n for n in PLUGIN.nodes if n.type == type_)
    assert issubclass(found, MistOperation)
    return found


def schemas(doc: Any) -> Any:
    return doc["components"]["schemas"]


def test_the_vendored_file_is_untouched_and_the_overlay_laid_over_it() -> None:
    raw = oas.parse((resources.files("dewpoint.plugins.mist") / "data" / "mist.openapi.json.gz").read_bytes())
    assert schemas(raw)["psk"]["properties"]["admin_sso_id"]["type"] == "string"
    patched = schemas(oas.document())
    assert patched["psk"]["properties"]["admin_sso_id"]["type"] == ["string", "null"]
    assert patched["response_count"]["properties"]["start"]["type"] == "number"
    assert patched["client_nac"]["properties"]["last_vlan"]["type"] == ["integer", "string"]
    assert "country_code" not in patched["stats_site"]["required"]
    assert {"mxtunnel_status", "wlans"}.isdisjoint(patched["ap_search"]["required"])


def test_every_patch_cites_the_run_that_showed_it() -> None:
    overlay = oas.overlay()
    assert overlay["oas_sha256"] == oas.SHA256 and overlay["patches"]
    assert all(p["evidence"] in overlay["evidence"] for p in overlay["patches"])


def test_a_patch_that_no_longer_applies_fails_loudly() -> None:
    raw = oas.parse((resources.files("dewpoint.plugins.mist") / "data" / "mist.openapi.json.gz").read_bytes())
    overlay = copy.deepcopy(oas.overlay())
    only_psk = {**overlay, "patches": [p for p in overlay["patches"] if p.get("property") == "admin_sso_id"]}
    patched_once = oas.overlaid(copy.deepcopy(raw), only_psk)
    with pytest.raises(oas.OasUnreadableError, match="psk.admin_sso_id"):
        oas.overlaid(patched_once, only_psk)  # already fixed: its expectation no longer holds
    with pytest.raises(oas.OasUnreadableError, match="no longer applies"):
        oas.overlaid(oas.overlaid(copy.deepcopy(raw), overlay), overlay)
    overlay["patches"].append({"schema": "psk", "property": "nowhere", "op": "nullable", "expect": {"type": "string"},
                               "evidence": "smoke-2026-10-07"})  # fmt: skip
    with pytest.raises(oas.OasUnreadableError, match="psk.nowhere"):
        oas.overlaid(copy.deepcopy(raw), overlay)


def fits(type_: str, value: Any) -> list[str]:
    schema = node_manifest(node(type_))["output_schema"]
    return [f"{list(e.absolute_path)} {e.validator}" for e in Draft202012Validator(schema).iter_errors(value)]


def test_the_answers_the_smoke_run_saw_now_fit() -> None:
    psk = {**fixture_of(node("mist.org_psks.get"))[0], "admin_sso_id": None, "email": None, "old_passphrase": None,
           "role": None}  # fmt: skip
    assert fits("mist.org_psks.get", psk) == []
    count = {**fixture_of(node("mist.org_wireless_clients.count"))[0], "start": 1759830000.25, "end": 1759916400.5}
    assert fits("mist.org_wireless_clients.count", count) == []
    template = copy.deepcopy(fixture_of(node("mist.org_network_templates.get"))[0])
    template["port_usages"] = {"trunk": {"reauth_interval": None, "networks": None, "poe_priority": None}}
    template["bgp_config"] = None
    assert fits("mist.org_network_templates.get", template) == []
    stats = {**fixture_of(node("mist.org_site_stats.list"))[0]}
    stats["results"] = [{k: v for k, v in stats["results"][0].items() if k not in ("country_code", "latlng")}]
    assert fits("mist.org_site_stats.list", stats) == []


def test_an_ap_found_by_a_device_search_fits_without_a_type() -> None:
    found = copy.deepcopy(fixture_of(node("mist.org_devices.search"))[0])
    ap = {k: v for k, v in found["results"][0].items() if k not in ("type", "mxtunnel_status", "wlans")}
    found["results"] = [{**ap, "band_24_bandwidth": 20, "band_5_bandwidth": 80, "band_6_bandwidth": 160}]
    assert fits("mist.org_devices.search", found) == []


def test_the_user_mac_search_answers_an_object_with_its_results() -> None:
    search = node("mist.org_usermacs.search")
    assert (search.shape, search.paging) == ("object", None)  # one page as Mist answers it; the query pages
    answer = {"results": [{"id": "7b2c4d6e-8f10-4a2b-9c3d-4e5f6a7b8c9d", "mac": "aabbccddeeff"}], "total": 1,
              "limit": 100, "page": 1, "unknown": True}  # fmt: skip
    assert fits("mist.org_usermacs.search", answer) == []
    assert "page" in node_manifest(search)["config_schema"]["properties"]["query"]["properties"]
    assert json.dumps(oas.operations()["searchOrgUserMacs"].spec["responses"]["200"]).count("UserMacsArray") == 0


def test_the_third_runs_answers_fit_too() -> None:
    """The third smoke run: a retyped field that was a reference (`last_vlan`, `random_mac`) takes the new type only,
    the alarm search's window is fractional, an asset's map may be null."""
    nac = copy.deepcopy(fixture_of(node("mist.org_nac_clients.search"))[0])
    nac["results"] = [{**nac["results"][0], "last_vlan": "10", "random_mac": True}] if nac["results"] else [
        {"last_vlan": "10", "random_mac": True}]  # fmt: skip
    assert fits("mist.org_nac_clients.search", nac) == []
    alarms = {**fixture_of(node("mist.org_alarms.search"))[0], "start": 1759830000.25, "end": 1759916400.5}
    assert fits("mist.org_alarms.search", alarms) == []
    asset = {**fixture_of(node("mist.org_assets.get"))[0], "map_id": None}
    assert fits("mist.org_assets.get", asset) == []
