# SPDX-License-Identifier: Apache-2.0
"""The read-only Mist smoke probe (`tests/probes/mist_smoke.py`), offline: its HTTP sends GET only and applies the
token itself; it resolves ids from lists; it reports statuses, sizes and schema mismatches as declared names and rules,
never a value nor the token."""

import json
from typing import Any

import pytest

from dewpoint.sdk import InvalidRequest, ReadOnly
from tests.plugins.mist.fakes import FakeHttp, Reply, Sent
from tests.probes import mist_smoke

ORG = "9777c1a0-6ef6-11e6-8bbf-02e208b2d34f"
SITE = "0f5e3c1a-9b8d-4e2f-a1b3-c5d7e9f1a3b5"
WLAN = "7b2c4d6e-8f10-4a2b-9c3d-4e5f6a7b8c9d"
BASE = "https://api.mist.com"
TOKEN = "tok-" + "z" * 60
SECRET = "SECRET-PSK-VALUE-123"


def readonly(script: Any) -> tuple[mist_smoke.ReadOnlyHttp, FakeHttp]:
    inner = FakeHttp(script)
    return mist_smoke.ReadOnlyHttp(inner, BASE, TOKEN), inner


@pytest.mark.parametrize(
    ("method", "kwargs"),
    [("POST", {}), ("PUT", {}), ("DELETE", {}), ("GET", {"json": {"a": 1}}), ("GET", {"content": b"x"})],
)
async def test_the_probes_http_sends_nothing_but_a_get(method: str, kwargs: dict[str, Any]) -> None:
    http, inner = readonly(lambda s: Reply(200, {}))
    with pytest.raises(ReadOnly):
        await http.request(method, "/api/v1/self", **kwargs)
    assert inner.sent == []


async def test_the_probes_http_applies_the_token_and_keeps_the_origin() -> None:
    http, inner = readonly(lambda s: Reply(200, {}))
    await http.request("GET", "/api/v1/orgs/x", headers={"Accept": "application/json"}, params={"limit": 1})
    assert inner.sent[0].url == f"{BASE}/api/v1/orgs/x"
    assert inner.sent[0].headers == {"Accept": "application/json", "Authorization": f"Token {TOKEN}"}
    for url in ("https://evil.example/api/v1/x", "//evil.example/x", "http://api.mist.com/api/v1/x"):
        with pytest.raises(InvalidRequest):
            await http.request("GET", url)
    await http.request("GET", f"{BASE}/api/v1/orgs/x/alarms/search?limit=1")  # a search's own next page
    assert len(inner.sent) == 2


def answers(sent: Sent) -> Reply:
    path = sent.url.removeprefix(BASE).split("?", 1)[0]
    found = {
        f"/api/v1/orgs/{ORG}/sites": Reply(200, [{"id": SITE, "name": "lab", "org_id": ORG}]),
        f"/api/v1/sites/{SITE}": Reply(200, {"id": SITE, "org_id": ORG, "name": "lab"}),
        f"/api/v1/orgs/{ORG}/wlans": Reply(200, [{"id": WLAN, "ssid": "corp", "auth": {"type": "psk", "psk": SECRET}}]),
        f"/api/v1/orgs/{ORG}/wlans/{WLAN}": Reply(200, {"id": WLAN, "ssid": 123, "auth": {"psk": SECRET}}),
        f"/api/v1/orgs/{ORG}/psks": Reply(403, {"detail": SECRET}),
    }
    return found.get(path, Reply(404, {"detail": "nope"}))


async def test_a_run_reports_what_it_found_and_never_a_value() -> None:
    http, inner = readonly(answers)
    report = await mist_smoke.probe(
        http, "global_01", ORG, rate=0,
        nodes=["mist.org_sites.list", "mist.org_wlans.list", "mist.org_wlans.get", "mist.org_psks.list",
               "mist.site_devices.get", "mist.site_insights.get", "mist.org_wlans.update"],
    )  # fmt: skip
    ops = {o["node"]: o for o in report["operations"]}
    assert ops["mist.org_sites.list"]["status"] == "ok" and ops["mist.org_wlans.list"]["status"] == "ok"
    wlan = ops["mist.org_wlans.get"]
    assert wlan["status"] == "mismatch" and {"path": "ssid", "rule": "type", "expected": "string",
                                             "found": "integer"} in wlan["mismatches"]  # fmt: skip
    assert ops["mist.org_psks.list"] == {**ops["mist.org_psks.list"], "status": "error", "detail": "mist.forbidden"}
    assert (
        ops["mist.site_devices.get"]["status"] == "skipped" and ops["mist.site_devices.get"]["detail"] == "unresolved"
    )
    assert ops["mist.site_insights.get"]["detail"] == "needs_query"  # its `metrics` query is required
    assert "mist.org_wlans.update" not in ops  # a write: never run
    assert {s.method for s in inner.sent} == {"GET"} and all(s.url.startswith(BASE) for s in inner.sent)
    text = json.dumps(report)
    assert SECRET not in text and TOKEN not in text and "corp" not in text and "lab" not in text
    assert report["summary"] == {"ok": 2, "mismatch": 1, "error": 1, "skipped": 2}


def test_a_mismatch_names_only_declared_fields_and_rules() -> None:
    schema = {
        "type": "object",
        "properties": {"results": {"type": "array", "items": {"type": "object",
                                                               "properties": {"name": {"type": "string"}},
                                                               "required": ["name"]}},
                       "map": {"type": "object", "additionalProperties": {"type": "integer"}}},
    }  # fmt: skip
    value = {"results": [{"other": SECRET}], "map": {"aabbccddeeff": "not-a-number"}}
    found = mist_smoke.mismatches(schema, value)
    assert {"path": "results/*", "rule": "required", "missing": ["name"]} in found
    assert {"path": "map/*", "rule": "type", "expected": "integer", "found": "string"} in found
    assert SECRET not in json.dumps(found) and "aabbccddeeff" not in json.dumps(found)
