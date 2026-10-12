# SPDX-License-Identifier: Apache-2.0
"""The Mist device-utility probe (`tests/probes/mist_utilities.py`), offline: its HTTP sends a GET, or a POST to a
diagnostic utility of a chosen device, and nothing else; it runs only the diagnostics a device's type supports; its
report holds outcomes, counts and shapes, never a line of output nor the token."""

import json
from typing import Any

import pytest

from dewpoint.plugins.mist import stream
from dewpoint.sdk import ReadOnly
from tests.plugins.mist.fakes import FakeHttp, FakeStream, Reply, Sent
from tests.probes import mist_utilities

ORG = "9777c1a0-6ef6-11e6-8bbf-02e208b2d34f"
SITE = "0f5e3c1a-9b8d-4e2f-a1b3-c5d7e9f1a3b5"
SWITCH = "00000000-0000-0000-1000-5c5b350e0060"
OTHER = "00000000-0000-0000-1000-aaaaaaaaaaaa"
BASE = "https://api.mist.com"
TOKEN = "tok-" + "z" * 60
SECRET_LINE = "secret-looking device output 10.9.8.7"
DEVICE = f"/api/v1/sites/{SITE}/devices/{SWITCH}"


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream, "ACK_S", 0.3)
    monkeypatch.setattr(stream, "FIRST_S", 0.3)
    monkeypatch.setattr(stream, "IDLE_S", 0.1)
    monkeypatch.setattr(stream, "BEAT_S", 0.05)


def fenced(script: Any) -> tuple[mist_utilities.ProbeHttp, FakeHttp]:
    inner = FakeHttp(script)
    return mist_utilities.ProbeHttp(inner, BASE, TOKEN, [(SITE, SWITCH)]), inner


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("POST", f"{DEVICE}/bounce_port", {"json": {"ports": ["ge-0/0/1"]}}),  # disruptive
        ("POST", f"{DEVICE}/clear_mac_table", {"json": {"port_id": "ge-0/0/1"}}),
        ("POST", f"{DEVICE}/restart", {}),  # not a utility
        ("POST", f"/api/v1/sites/{SITE}/devices/{OTHER}/ping", {"json": {"host": "8.8.8.8"}}),  # another device
        ("POST", f"{DEVICE}/ping?x=1", {"json": {"host": "8.8.8.8"}}),
        ("PUT", DEVICE, {"json": {}}),
        ("DELETE", DEVICE, {}),
        ("GET", DEVICE, {"json": {"a": 1}}),
    ],
)
async def test_the_probes_http_sends_only_a_get_or_a_chosen_devices_diagnostic(
    method: str, path: str, kwargs: dict[str, Any]
) -> None:
    http, inner = fenced(lambda s: Reply(200, {}))
    with pytest.raises(ReadOnly):
        await http.request(method, path, **kwargs)
    assert inner.sent == []


async def test_a_chosen_devices_diagnostic_is_sent_with_the_token() -> None:
    http, inner = fenced(lambda s: Reply(200, {"session": "s"}))
    await http.request("POST", f"{DEVICE}/ping", json={"host": "8.8.8.8"})
    await http.request("GET", f"/api/v1/sites/{SITE}")
    sent = [(s.method, s.url) for s in inner.sent]
    assert sent == [("POST", f"{BASE}{DEVICE}/ping"), ("GET", f"{BASE}/api/v1/sites/{SITE}")]
    assert all(s.headers and s.headers["Authorization"] == f"Token {TOKEN}" for s in inner.sent)


def test_only_diagnostics_are_run_and_only_on_a_type_they_support() -> None:
    switch = {n.type for n in mist_utilities.diagnostics("switch")}
    gateway = {n.type for n in mist_utilities.diagnostics("gateway")}
    assert "mist.site_devices.ping" in switch and "mist.site_devices.show_ospf_neighbors" not in switch
    assert "mist.site_devices.show_ospf_neighbors" in gateway
    every = {n.type for kind in ("ap", "gateway", "switch") for n in mist_utilities.diagnostics(kind)}
    assert not {t for t in every if t.rsplit(".", 1)[1] in ("bounce_port", "cable_test", "clear_macs", "clear_bgp")}
    kinds = ("ap", "gateway", "switch")
    assert all(n.side_effect.value == "idempotent" for kind in kinds for n in mist_utilities.diagnostics(kind))


async def test_a_run_reports_outcomes_and_shapes_never_output_or_the_token() -> None:
    channel = f"/sites/{SITE}/devices/{SWITCH}/cmd"
    socket = FakeStream(lambda text: [json.dumps({"event": "channel_subscribed", "channel": channel})])
    table = {"status": "SUCCESS", "finished": True, "rows": [{"ip": SECRET_LINE}]}

    def mist(sent: Sent) -> Reply:
        path = sent.url.removeprefix(BASE)
        if path == f"/api/v1/sites/{SITE}":
            return Reply(200, {"id": SITE, "org_id": ORG})
        if path == DEVICE:
            return Reply(200, {"id": SWITCH, "type": "switch"})
        if sent.method == "POST":
            raw = json.dumps(table) + '\n"}}' if path.endswith("/show_arp") else SECRET_LINE + "\n"
            socket.queue({"event": "data", "channel": channel, "data": {"session": "s1", "raw": raw}})
            return Reply(200, {"session": "s1"})
        return Reply(404, {})

    http = mist_utilities.ProbeHttp(FakeHttp(mist), BASE, TOKEN, [(SITE, SWITCH)])

    async def opener() -> FakeStream:
        socket.closed = False
        return socket

    only = ["mist.site_devices.ping", "mist.site_devices.show_arp", "mist.site_devices.show_dhcp_leases"]
    report = await mist_utilities.probe(http, opener, "global_01", ORG, [(SITE, SWITCH, "switch")], rate=0,
                                        nodes=only, max_duration_s=1)  # fmt: skip
    text = json.dumps(report)
    assert SECRET_LINE not in text and TOKEN not in text and "10.9.8.7" not in text
    found = {o["node"]: o for o in report["operations"]}
    assert (found["mist.site_devices.ping"]["status"], found["mist.site_devices.ping"]["lines"]) == ("ok", 1)
    arp = found["mist.site_devices.show_arp"]
    assert (arp["status"], arp["ended_by"], arp["tables"], arp["trailing_after_table"]) == ("ok", "finished", 1, 1)
    assert found["mist.site_devices.show_dhcp_leases"]["status"] == "skipped"  # it needs a network to name
    assert report["summary"] == {"ok": 2, "error": 0, "skipped": 1}


def test_a_messages_shape_names_protocol_words_never_values() -> None:
    """The trace that explains `mist.no_output`: each message's event, whether its channel and session are ours, and
    its data's type and key names; never a value."""
    channel = f"/sites/{SITE}/devices/{SWITCH}/cmd"
    ours = json.dumps({"event": "data", "channel": channel, "data": {"session": "s1", "raw": SECRET_LINE}})
    shape = mist_utilities.shape(ours, channel, "s1")
    assert shape == {"event": "data", "keys": ["channel", "data", "event"], "channel": "ours", "data": "dict",
                     "data_keys": ["raw", "session"], "session": "ours"}  # fmt: skip
    nested = json.dumps({"event": "data", "channel": channel.upper(), "data": json.dumps({"session": "x", "raw": "y"})})
    assert mist_utilities.shape(nested, channel, "s1") == {
        "event": "data", "keys": ["channel", "data", "event"], "channel": "ours_case",
        "channel_form": "/{?}/{site}/{?}/{device}/{?}", "data": "str",
        "data_decoded": "dict", "data_keys": ["raw", "session"], "session": "other",
    }  # fmt: skip
    assert mist_utilities.shape("not json", channel, "s1") == {"json": False}
    assert SECRET_LINE not in json.dumps(mist_utilities.shape(ours, channel, "s1"))


def test_a_nested_envelopes_shape_is_traced_one_level_down() -> None:
    channel = f"/sites/{SITE}/devices/{SWITCH}/cmd"
    inner = {"event": "data", "channel": channel, "data": json.dumps({"session": "s1", "raw": SECRET_LINE})}
    outer = json.dumps({"event": "data", "channel": channel, "data": json.dumps(inner)})
    found = mist_utilities.shape(outer, channel, "s1")
    assert found["nested"] == {"event": "data", "keys": ["channel", "data", "event"], "channel": "ours", "data": "str",
                               "data_decoded": "dict", "data_keys": ["raw", "session"], "session": "ours"}  # fmt: skip
    assert SECRET_LINE not in json.dumps(found)


@pytest.mark.parametrize(
    ("named", "form"),
    [
        (f"/sites/{SITE}/devices/{SWITCH}/cmd", "/sites/{site}/devices/{device}/cmd"),
        (f"/devices/{SWITCH}/cmd", "/devices/{device}/cmd"),
        (f"/sites/{SITE}/devices/{SWITCH[-12:]}/cmd", "/sites/{site}/devices/{device_mac}/cmd"),
        ("/sites/7b2c4d6e-8f10-4a2b-9c3d-4e5f6a7b8c9d/devices/aabbccddeeff/cmd", "/sites/{uuid}/devices/{mac}/cmd"),
        ("/sites/x y/Secret.Value", "/sites/{?}/{?}"),
    ],
)
def test_a_channels_form_names_its_parts_never_their_values(named: str, form: str) -> None:
    assert mist_utilities.channel_form(named, SITE, SWITCH) == form


def test_a_traced_message_records_when_it_came() -> None:
    trace = mist_utilities.Trace(channel=f"/sites/{SITE}/devices/{SWITCH}/cmd", session="s1", started=0.0)
    trace.record(json.dumps({"event": "data", "channel": trace.channel, "data": {"session": "s1", "raw": "x"}}))
    assert set(trace.messages[0]) >= {"at"} and isinstance(trace.messages[0]["at"], float)
