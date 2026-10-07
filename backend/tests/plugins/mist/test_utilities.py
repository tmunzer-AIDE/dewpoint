# SPDX-License-Identifier: Apache-2.0
"""One node type per device utility (plugins-3 D27): its config holds the connection, the site, the device, the body
parameters its review permits (within their maxima) and, streaming, its maximum duration; its output is its contract's.
It checks the map (its own operation, its site check, its device check), that the site is the connection's org's and
that the device is of a reviewed type, before anything else is sent. A diagnostic streams and maps an unmet condition
to a retry; a disruptive utility only POSTs and reports the command accepted, its completion unknown."""

import json
import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from dewpoint.plugins.mist import PLUGIN, oas, policy, stream, utilities
from dewpoint.plugins.mist.client import InvalidAnswer, NotFound, SiteOutsideOrg
from dewpoint.plugins.mist.nodes import MistOperation, OperationUnavailable
from dewpoint.sdk import FatalError, MaybeSent, OutcomeUnknownError, RetryableError, node_manifest
from tests.plugins.mist.fakes import ORG, SITE, FakeConnection, FakeHttp, FakeStep, FakeStream, FakeWs, Reply, Sent

DEVICE = "00000000-0000-0000-1000-5c5b350e0060"
SESSION = "9106e908-74dc-4a4f-9050-9c2adcaf44a5"
CHANNEL = f"/sites/{SITE}/devices/{DEVICE}/cmd"


@pytest.fixture(autouse=True)
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stream, "ACK_S", 0.3)
    monkeypatch.setattr(stream, "FIRST_S", 0.3)
    monkeypatch.setattr(stream, "IDLE_S", 0.15)
    monkeypatch.setattr(stream, "BEAT_S", 0.05)


def node(type_: str) -> Any:
    return next(n for n in PLUGIN.nodes if n.type == type_)


def utility_nodes() -> dict[str, Any]:
    return {n.type: n for n in PLUGIN.nodes if issubclass(n, utilities.MistUtility)}


def mist(device_type: str | None = "switch", answer: Reply | None = None, *output: Any) -> tuple[FakeStep, FakeHttp]:
    """A Mist whose site is the org's, whose device is of `device_type`, and whose POST answers `answer` and then
    streams `output` on the device's channel."""
    acked = json.dumps({"event": "channel_subscribed", "channel": CHANNEL})
    ws_stream = FakeStream(lambda text: [acked] if json.loads(text) == {"subscribe": CHANNEL} else [])
    device = {"id": DEVICE, "site_id": SITE, **({"type": device_type} if device_type else {})}

    def script(sent: Sent) -> Reply:
        if (sent.method, sent.url) == ("GET", f"/api/v1/sites/{SITE}"):
            return Reply(200, {"id": SITE, "org_id": ORG})
        if (sent.method, sent.url) == ("GET", f"/api/v1/sites/{SITE}/devices/{DEVICE}"):
            return Reply(200, device)
        if sent.method == "POST":
            for item in output:
                ws_stream.queue(item)
            return answer or Reply(200, {"session": SESSION})
        return Reply(404, {"detail": "not scripted"})

    http = FakeHttp(script)
    return FakeStep(FakeConnection(http, ws=FakeWs(ws_stream))), http


async def run(type_: str, step: FakeStep, **config: Any) -> dict[str, Any]:
    kind = node(type_)
    value = kind.Config.model_validate({"connection": str(step.connection_.id), "site_id": SITE, "device_id": DEVICE,
                                        **config})  # fmt: skip
    return (await kind().run(step, value)).model_dump(mode="json")  # type: ignore[no-any-return]


def line(raw: str) -> dict[str, Any]:
    return {"event": "data", "channel": CHANNEL, "data": {"session": SESSION, "raw": raw}}


def test_every_reviewed_utility_has_its_node_and_no_other() -> None:
    entries = {op: e for op, e in policy.load().entries.items() if e.utility is not None}
    made = utility_nodes()
    assert set(made) == {e.nodes[0] for e in entries.values()}
    for type_, n in made.items():
        e = entries[n.operation]
        assert (n.version, n.side_effect.value, n.capabilities, n.credentials) == (
            1, e.side_effect, frozenset({e.capability}), ("mist",),
        ), type_  # fmt: skip
        assert n.timeout.total_seconds() > (240 + 10 + 30 if e.utility.stream else 0), type_
        assert issubclass(n, MistOperation) and n.method == "POST"


def test_a_utilitys_config_holds_only_what_its_review_permits() -> None:
    ping = node_manifest(node("mist.site_devices.ping"))["config_schema"]
    assert set(ping["properties"]) == {"connection", "site_id", "device_id", "body", "max_duration_s"}
    assert set(ping["properties"]["body"]["properties"]) == {
        "count", "egress_interface", "host", "node", "size", "use_ipv6", "vrf",
    }  # fmt: skip
    assert ping["properties"]["body"]["additionalProperties"] is False
    assert ping["properties"]["body"]["properties"]["count"]["maximum"] == 100
    assert ping["properties"]["body"]["required"] == ["host"] and "body" in ping["required"]
    assert ping["properties"]["max_duration_s"] == {
        "type": "integer", "minimum": 1, "maximum": 240, "default": 60, "title": "Seconds to collect output, at most",
    }  # fmt: skip
    arp = node_manifest(node("mist.site_devices.show_arp"))["config_schema"]
    assert "interval" not in arp["properties"]["body"]["properties"]
    assert "duration" not in arp["properties"]["body"]["properties"]
    bounce = node_manifest(node("mist.site_devices.bounce_port"))["config_schema"]
    assert "max_duration_s" not in bounce["properties"]
    dns = node_manifest(node("mist.site_devices.resolve_dns"))["config_schema"]
    assert "body" not in dns["properties"]


def test_a_count_past_its_maximum_is_refused_at_validation() -> None:
    with pytest.raises(ValueError):
        node("mist.site_devices.ping").Config.model_validate(
            {"connection": str(uuid.uuid4()), "site_id": SITE, "device_id": DEVICE, "body": {"host": "x", "count": 101}}
        )


def test_each_output_is_its_contracts() -> None:
    bounded = node_manifest(node("mist.site_devices.ping"))["output_schema"]
    assert set(bounded["required"]) == {"accepted", "session", "lines", "received", "ended_by", "completion_known",
                                        "truncated"}  # fmt: skip
    assert bounded["properties"]["ended_by"]["enum"] == ["finished", "idle", "max_duration"]
    terminal = node_manifest(node("mist.site_devices.show_arp"))["output_schema"]
    assert terminal["properties"]["ended_by"] == {"const": "finished"}
    assert terminal["properties"]["completion_known"] == {"const": True}
    accepted = node_manifest(node("mist.site_devices.cable_test"))["output_schema"]
    assert accepted["required"] == ["accepted", "completion_known", "session"]
    assert accepted["properties"]["completion_known"] == {"const": False}
    rest_only = node_manifest(node("mist.site_devices.bounce_port"))["output_schema"]
    assert set(rest_only["properties"]) == {"accepted", "completion_known"}


async def test_a_ping_checks_site_and_device_then_streams_its_output() -> None:
    step, http = mist("switch", None, line("64 bytes from 8.8.8.8: seq=1\n"))
    out = await run("mist.site_devices.ping", step, body={"host": "8.8.8.8", "count": 3})
    assert out == {"accepted": True, "session": SESSION, "lines": ["64 bytes from 8.8.8.8: seq=1"], "received": 1,
                   "ended_by": "idle", "completion_known": False, "truncated": False}  # fmt: skip
    assert [(s.method, s.url, s.probe) for s in http.sent] == [
        ("GET", f"/api/v1/sites/{SITE}", True),
        ("GET", f"/api/v1/sites/{SITE}/devices/{DEVICE}", True),
        ("POST", f"/api/v1/sites/{SITE}/devices/{DEVICE}/ping", False),
    ]
    assert http.sent[-1].json == {"host": "8.8.8.8", "count": 3}
    assert step.connection_.ws.stream.closed


@pytest.mark.parametrize("device_type", ["ap", None])
async def test_a_device_of_another_type_or_none_is_refused_before_anything_is_sent(device_type: str | None) -> None:
    step, http = mist(device_type)
    with pytest.raises(FatalError) as raised:
        await run("mist.site_devices.cable_test", step, body={"port": "ge-0/0/1"})
    assert raised.value.code == "mist.device_type_unsupported"
    assert [s.method for s in http.sent] == ["GET", "GET"]
    assert step.connection_.ws.opened == 0


async def test_a_device_check_that_may_have_been_answered_is_retried() -> None:
    step, http = mist()

    def failing(sent: Sent) -> Reply | BaseException:
        if sent.url.endswith(f"/devices/{DEVICE}"):
            return MaybeSent()
        return Reply(200, {"id": SITE, "org_id": ORG})

    step.connection_.http = FakeHttp(failing)
    with pytest.raises(RetryableError) as raised:
        await run("mist.site_devices.bounce_port", step, body={"ports": ["ge-0/0/1"]})
    assert raised.value.code == "mist.device_check_failed"


async def test_a_device_not_in_the_site_is_not_found() -> None:
    step, _ = mist()
    step.connection_.http = FakeHttp({("GET", f"/api/v1/sites/{SITE}"): Reply(200, {"id": SITE, "org_id": ORG})})
    with pytest.raises(NotFound):
        await run("mist.site_devices.bounce_port", step, body={"ports": ["ge-0/0/1"]})


async def test_a_site_of_another_org_stops_everything() -> None:
    step, http = mist()
    step.connection_.http = FakeHttp({("GET", f"/api/v1/sites/{SITE}"): Reply(200, {"id": SITE, "org_id": "other"})})
    with pytest.raises(SiteOutsideOrg):
        await run("mist.site_devices.ping", step, body={"host": "8.8.8.8"})
    assert step.connection_.ws.opened == 0


async def test_an_unmet_diagnostic_is_retried() -> None:
    step, _ = mist("switch")  # accepted, no output
    with pytest.raises(RetryableError) as raised:
        await run("mist.site_devices.ping", step, body={"host": "8.8.8.8"})
    assert raised.value.code == "mist.no_output"


def test_an_unmet_condition_is_a_retry_only_for_a_repeatable_diagnostic() -> None:
    unmet = stream.no_output()
    retried = utilities.failure(unmet, repeatable=True)
    unknown = utilities.failure(unmet, repeatable=False)
    assert isinstance(retried, RetryableError) and isinstance(unknown, OutcomeUnknownError)
    assert (retried.code, unknown.code) == ("mist.no_output", "mist.no_output")


async def test_a_terminal_table_succeeds_on_its_evidence() -> None:
    table = {"status": "SUCCESS", "finished": True, "rows": [{"ip_address": "192.168.1.1"}]}
    step, _ = mist("gateway", None, line(json.dumps(table)))
    out = await run("mist.site_devices.show_arp", step, body={"node": "node0"})
    assert (out["ended_by"], out["completion_known"]) == ("finished", True)


async def test_a_disruptive_utility_only_posts_and_reports_the_command_accepted() -> None:
    step, http = mist("switch", Reply(200, None))
    out = await run("mist.site_devices.bounce_port", step, body={"ports": ["ge-0/0/1"]})
    assert out == {"accepted": True, "completion_known": False}
    assert step.connection_.ws.opened == 0
    assert http.sent[-1].json == {"ports": ["ge-0/0/1"]}


async def test_an_acceptance_with_a_session_names_it() -> None:
    step, _ = mist("switch", Reply(200, {"session": SESSION}))
    out = await run("mist.site_devices.cable_test", step, body={"port": "ge-0/0/1"})
    assert out == {"accepted": True, "session": SESSION, "completion_known": False}
    assert step.connection_.ws.opened == 0


async def test_an_acceptance_whose_answer_lacks_its_session_is_unreadable() -> None:
    step, _ = mist("switch", Reply(200, {}))
    with pytest.raises(InvalidAnswer):
        await run("mist.site_devices.cable_test", step, body={"port": "ge-0/0/1"})


async def test_a_held_device_check_stops_a_utility_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    found = policy.load()
    entries = dict(found.entries)
    entries["getSiteDevice"] = policy.Entry("GET", entries["getSiteDevice"].path, "held", reason="held for the test")
    monkeypatch.setattr(policy, "load", lambda: policy.PolicyMap(found.oas_sha256, entries))
    step, http = mist()
    with pytest.raises(OperationUnavailable):
        await run("mist.site_devices.ping", step, body={"host": "8.8.8.8"})
    assert http.sent == []


async def test_a_held_utility_stops_before_sending(monkeypatch: pytest.MonkeyPatch) -> None:
    found = policy.load()
    entries = dict(found.entries)
    entries["pingFromDevice"] = policy.Entry("POST", entries["pingFromDevice"].path, "held", reason="held")
    monkeypatch.setattr(policy, "load", lambda: policy.PolicyMap(found.oas_sha256, entries))
    step, http = mist()
    with pytest.raises(OperationUnavailable):
        await run("mist.site_devices.ping", step, body={"host": "8.8.8.8"})
    assert http.sent == []


@pytest.mark.parametrize("type_", sorted(t for t in [
    "mist.site_devices.ping", "mist.site_devices.show_arp", "mist.site_devices.bounce_port",
    "mist.site_devices.cable_test", "mist.site_devices.resolve_dns",
]))  # fmt: skip
async def test_simulating_sends_nothing_and_answers_its_output_schema(type_: str) -> None:
    step, http = mist()
    kind = node(type_)
    body = {"ping": {"host": "8.8.8.8"}, "show_arp": {}, "bounce_port": {"ports": ["ge-0/0/1"]},
            "cable_test": {"port": "ge-0/0/1"}, "resolve_dns": None}[type_.rsplit(".", 1)[1]]  # fmt: skip
    config = {"connection": str(step.connection_.id), "site_id": SITE, "device_id": DEVICE,
              **({"body": body} if body is not None else {})}  # fmt: skip
    out = (await kind().simulate(step, kind.Config.model_validate(config))).model_dump(mode="json")
    Draft202012Validator(node_manifest(kind)["output_schema"]).validate(out)
    assert http.sent == [] and step.connection_.ws.opened == 0 and step.opened == []


def test_the_utility_operations_are_reached_by_their_own_path() -> None:
    for type_, n in utility_nodes().items():
        assert oas.operations()[n.operation].path == n.path, type_


def _config(type_: str, body: Any = None) -> dict[str, Any]:
    return {"connection": str(uuid.uuid4()), "site_id": SITE, "device_id": DEVICE,
            **({"body": body} if body is not None else {})}  # fmt: skip


@pytest.mark.parametrize(
    ("type_", "body"),
    [
        ("mist.site_devices.bounce_port", None), ("mist.site_devices.bounce_port", {}),
        ("mist.site_devices.bounce_port", {"ports": []}), ("mist.site_devices.bounce_port", {"ports": ["all"]}),
        ("mist.site_devices.bounce_port", {"ports": ["ge-0/0/1", "ALL"]}), ("mist.site_devices.clear_macs", {}),
        ("mist.site_devices.clear_bpdu_error", {"ports": ["all"]}), ("mist.site_devices.clear_dot1x", {"ports": []}),
        ("mist.site_devices.clear_session", {}), ("mist.site_devices.clear_session", {"session_ids": []}),
        ("mist.site_devices.clear_mac_table", {}), ("mist.site_devices.clear_mac_table", {"vlan_id": "10"}),
        ("mist.site_devices.clear_arp", {}), ("mist.site_devices.clear_arp", {"vrf": "default"}),
        ("mist.site_devices.clear_bgp", {"neighbor": "all", "type": "soft"}),
        ("mist.site_devices.clear_bgp", {"neighbor": "All", "type": "hard"}),
        ("mist.site_devices.release_dhcp_leases", {"port_id": "all"}),
    ],
)  # fmt: skip
def test_a_disruptive_utilitys_whole_device_form_is_refused(type_: str, body: Any) -> None:
    """Review M1: an omitted, empty or `all` selector may mean every port, session or neighbor (D24 holds bulk
    forms)."""
    with pytest.raises(ValueError):
        node(type_).Config.model_validate(_config(type_, body))


@pytest.mark.parametrize(
    ("type_", "body"),
    [
        ("mist.site_devices.bounce_port", {"ports": ["ge-0/0/1", "ge-0/0/2"]}),
        ("mist.site_devices.clear_session", {"session_ids": [SESSION]}),
        ("mist.site_devices.clear_mac_table", {"port_id": "ge-0/0/0.0", "vlan_id": "10"}),
        ("mist.site_devices.clear_arp", {"port_id": "ge-0/0/1", "ip": "10.1.2.3"}),
        ("mist.site_devices.clear_bgp", {"neighbor": "10.250.18.202", "type": "soft"}),
        ("mist.site_devices.release_dhcp_leases", {"port_id": "ge-0/0/3", "macs": ["aabbccddeeff"]}),
    ],
)  # fmt: skip
def test_a_selected_form_is_accepted(type_: str, body: Any) -> None:
    node(type_).Config.model_validate(_config(type_, body))


@pytest.mark.parametrize(
    ("type_", "body"),
    [
        ("mist.site_devices.ping", {"host": "8.8.8.8", "count": 0}),  # 0 is "unlimited" to some pings
        ("mist.site_devices.ping", {"host": "8.8.8.8", "count": -1}),
        ("mist.site_devices.service_ping", {"host": "8.8.8.8", "service": "internet", "count": 0}),
        ("mist.site_devices.traceroute", {"host": "8.8.8.8", "timeout": 0}),
        ("mist.site_devices.ping", {"host": "8.8.8.8; reboot"}),  # free text reaches a device's command line
        ("mist.site_devices.ping", {"host": "8.8.8.8 -c 100000"}),
        ("mist.site_devices.ping", {"host": ""}),
        ("mist.site_devices.show_route", {"vrf": "a b"}),
        ("mist.site_devices.bounce_port", {"ports": ["ge-0/0/1|reboot"]}),
    ],
)  # fmt: skip
def test_bounded_integers_start_at_one_and_free_text_is_a_token(type_: str, body: Any) -> None:
    """Review M2."""
    with pytest.raises(ValueError):
        node(type_).Config.model_validate(_config(type_, body))


def test_a_hostname_an_interface_and_a_prefix_are_tokens() -> None:
    node("mist.site_devices.ping").Config.model_validate(
        _config("", {"host": "dns.google", "egress_interface": "ge-0/0/0.100", "vrf": "mgmt_junos"})
    )
    node("mist.site_devices.show_route").Config.model_validate(_config("", {"prefix": "10.0.0.0/8"}))
    node("mist.site_devices.ping").Config.model_validate(_config("", {"host": "2001:4860:4860::8888"}))


def test_no_permitted_parameter_is_an_object() -> None:
    """Review L4: an object parameter would carry whatever keys it's given (show_route's `node` is one in the OAS)."""
    for type_, n in utility_nodes().items():
        schema = node_manifest(n)["config_schema"]
        for name, prop in schema["properties"].get("body", {}).get("properties", {}).items():
            target = schema.get("$defs", {}).get(prop.get("$ref", "").rsplit("/", 1)[-1], prop)
            assert target.get("type") != "object", (type_, name)
