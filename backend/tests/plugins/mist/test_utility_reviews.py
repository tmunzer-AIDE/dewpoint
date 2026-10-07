# SPDX-License-Identifier: Apache-2.0
"""The device utilities' reviews (plugins-3 D27, D28): each of the 30 is allowed to its own node only, with its contract
(the success condition its node promises), its stream mode, the device types it runs on, the body parameters it may
send, their bounds, what repeating it does, and the evidence for each. The 11 disruptive ones are acceptance only and
ambiguous; the 19 diagnostics are repeatable, three with documented terminal evidence, the rest bounded collections;
only an operation whose OAS answer holds a `session` may stream. The utilities D27 holds back reach nothing."""

import dataclasses
import json
from typing import Any

import pytest

from dewpoint.plugins.mist import oas, policy, reviews

DISRUPTIVE = {
    "bounceDevicePort", "cableTestFromSwitch", "clearSiteDeviceMacTable", "clearAllLearnedMacsFromPortOnSwitch",
    "clearBpduErrorsFromPortsOnSwitch", "clearSiteDeviceDot1xSession", "releaseSiteDeviceDhcpLease",
    "releaseSiteSsrDhcpLease", "clearSiteDeviceSession", "clearSiteSsrArpCache", "clearSiteSsrBgpRoutes",
}  # fmt: skip
TERMINAL = {"showSiteDeviceArpTable", "showSiteSsrServicePath", "showSiteSsrAndSrxSessions"}
REST_ONLY = {"bounceDevicePort", "clearAllLearnedMacsFromPortOnSwitch", "clearBpduErrorsFromPortsOnSwitch",
             "releaseSiteDeviceDhcpLease", "clearSiteDeviceSession"}  # fmt: skip
HELD_BACK = {
    "createSiteDeviceShellSession", "getSiteDeviceConfigCmd", "uploadSiteDeviceSupportFile", "zeroizeSiteFipsAllAps",
    "reprovisionSiteOctermDevice", "readoptSiteOctermDevice", "restoreSiteDeviceBackupVersion",
    "toogleSiteDeviceVcRoutingEnginesRole", "startSitePacketCapture", "monitorSiteDeviceTraffic",
    "runSiteSrxTopCommand", "clearSiteDevicePolicyHitCount",
}  # fmt: skip


def utilities() -> dict[str, policy.Entry]:
    return {op: e for op, e in policy.load().entries.items() if e.utility is not None}


def body_properties(op_id: str) -> set[str]:
    """Its body's parameters but its objects, which would carry any keys (review L4)."""
    doc, op = oas.document(), oas.operations()[op_id]
    body = op.spec.get("requestBody")
    if body is None:
        return set()
    schema = oas.resolve(doc, oas.resolve(doc, body)["content"]["application/json"]["schema"])
    return {k for k, v in schema.get("properties", {}).items() if oas.resolve(doc, v).get("type") != "object"}


def answers_a_session(op_id: str) -> bool:
    doc, op = oas.document(), oas.operations()[op_id]
    answer = oas.answer(doc, op)
    return answer is not None and "session" in oas.resolve(doc, answer).get("properties", {})


def test_the_30_utilities_are_reviewed_each_to_its_own_node_only() -> None:
    found = utilities()
    assert len(found) == 30 and len(DISRUPTIVE) == 11
    nodes = [e.nodes for e in found.values()]
    assert all(len(n) == 1 and n[0].startswith("mist.site_devices.") for n in nodes)
    assert len({n[0] for n in nodes}) == 30
    for op_id, e in found.items():
        assert e.method == "POST" and e.scope == "site" and e.evidence, op_id
        assert e.path.startswith("/api/v1/sites/{site_id}/devices/{device_id}/"), op_id
        assert policy.load().allowed(op_id, "mist.api.write") is None, op_id  # never the generic write


def test_the_disruptive_utilities_are_acceptance_only_and_ambiguous() -> None:
    for op_id, e in utilities().items():
        assert e.utility is not None
        if op_id in DISRUPTIVE:
            assert (e.capability, e.side_effect, e.utility.contract, e.utility.stream) == (
                "mist.write", "ambiguous", "acceptance_only", False,
            ), op_id  # fmt: skip
        else:
            assert (e.capability, e.side_effect) == ("mist.diagnose", "idempotent"), op_id
            expected = "stream_terminal_evidence" if op_id in TERMINAL else "bounded_collection"
            assert (e.utility.contract, e.utility.stream) == (expected, True), op_id


def test_only_an_operation_answering_a_session_streams() -> None:
    for op_id, e in utilities().items():
        assert e.utility is not None
        if e.utility.stream:
            assert answers_a_session(op_id), op_id
    assert {op for op in utilities() if not answers_a_session(op)} == REST_ONLY  # resolve_dns: no body, a session


def test_the_permitted_parameters_are_the_bodys_but_the_refresh_ones_and_objects() -> None:
    for op_id, e in utilities().items():
        assert e.utility is not None
        assert set(e.utility.parameters) == body_properties(op_id) - {"interval", "duration"}, op_id
        assert set(e.utility.bounds) <= {*e.utility.parameters, "max_duration_s"}, op_id
    found = utilities()
    assert "interval" not in found["showSiteDeviceArpTable"].utility.parameters  # type: ignore[union-attr]
    assert found["pingFromDevice"].utility.bounds == {"count": 100, "max_duration_s": 240}  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("op_id", "types"),
    [
        ("pingFromDevice", ("ap", "gateway", "switch")), ("cableTestFromSwitch", ("switch",)),
        ("showSiteGatewayOspfNeighbors", ("gateway",)), ("bounceDevicePort", ("gateway", "switch")),
        ("showSiteDeviceBgpSummary", ("gateway", "switch")), ("clearSiteSsrArpCache", ("gateway", "switch")),
        ("showSiteDeviceArpTable", ("gateway", "switch")),
    ],
)  # fmt: skip
def test_device_types_come_from_the_operations_tag_and_description(op_id: str, types: tuple[str, ...]) -> None:
    review = utilities()[op_id].utility
    assert review is not None and review.device_types == types


def test_a_utility_reads_its_site_its_device_and_its_site_pickers_list() -> None:
    """A device inside a site has no picker (3b-1's pickers are the site's and org resources'): its id is typed."""
    for op_id, e in utilities().items():
        assert e.reads == ("getSiteDevice", "getSiteInfo", "listOrgSites"), op_id


def test_the_utilities_d27_holds_back_reach_nothing() -> None:
    entries = policy.load().entries
    for op_id in HELD_BACK:
        assert (entries[op_id].state, entries[op_id].nodes) == ("held", ()), op_id
        assert entries[op_id].reason == reviews.HELD[op_id]
    assert entries["getSiteDeviceZtpPassword"].state == "denied"  # always refused, stricter than held


def _review(op_id: str, **changes: Any) -> tuple[Any, ...]:
    current = next(u for u in reviews.UTILITIES if u.operation == op_id)
    return tuple(dataclasses.replace(current, **changes) if u is current else u for u in reviews.UTILITIES)


@pytest.mark.parametrize(
    ("changed", "problem"),
    [
        (_review("pingFromDevice", parameters=("host", "nope")), "pingFromDevice: parameter 'nope'"),
        (_review("pingFromDevice", bounds={"host": 5, "max_duration_s": 240}), "pingFromDevice: bound 'host'"),
        (_review("pingFromDevice", bounds={"size": 10, "max_duration_s": 240}), "pingFromDevice: bound 'size'"),
        (_review("bounceDevicePort", bounds={"max_duration_s": 60}), "bounceDevicePort: bound 'max_duration_s'"),
        (_review("showSiteDeviceArpTable", parameters=("interval",)), "showSiteDeviceArpTable: parameter 'interval'"),
        (_review("bounceDevicePort", contract="bounded_collection"), "bounceDevicePort: streams"),
        (_review("bounceDevicePort", contract="stream_terminal_evidence"), "bounceDevicePort: streams"),
        (_review("cableTestFromSwitch", contract="bounded_collection"), "cableTestFromSwitch: a disruptive"),
        (_review("pingFromDevice", device_types=("router",)), "pingFromDevice: device type"),
        (_review("pingFromDevice", device_types=()), "pingFromDevice: device type"),
        (_review("pingFromDevice", contract="verified_readback"), "pingFromDevice: contract"),
        (_review("pingFromDevice", node="mist.site_devices.list"), "a duplicate"),
        (_review("pingFromDevice", operation="getSiteDevice"), "getSiteDevice: not a device utility"),
        (_review("pingFromDevice", operation="createSiteDeviceShellSession"), "createSiteDeviceShellSession"),
        (_review("showSiteSsrAndSrxRoutes", parameters=("node", "vrf")), "showSiteSsrAndSrxRoutes: parameter 'node'"),
        (_review("bounceDevicePort", selectors=()), "bounceDevicePort: a disruptive utility names its selector"),
        (_review("bounceDevicePort", selectors=("nope",)), "bounceDevicePort: selector 'nope'"),
        (_review("clearSiteSsrArpCache", selectors=("vlan",)), "clearSiteSsrArpCache: selector 'vlan'"),
        (_review("pingFromDevice", bounds={"size": 70000, "max_duration_s": 240}), "pingFromDevice: bound 'size'"),
    ],
)  # fmt: skip
def test_a_review_that_doesnt_fit_its_operation_fails_the_build(
    monkeypatch: pytest.MonkeyPatch, changed: tuple[Any, ...], problem: str
) -> None:
    monkeypatch.setattr(reviews, "UTILITIES", changed)
    with pytest.raises(reviews.ReviewError) as raised:
        reviews.make_map()
    assert any(problem in p for p in raised.value.problems), raised.value.problems


@pytest.mark.parametrize(
    "change",
    [
        lambda u: u.update(contract="rest_completion"),  # no node implements it
        lambda u: u.update(stream="yes"),
        lambda u: u.update(device_types=["router"]),
        lambda u: u.update(parameters="host"),
        lambda u: u.update(bounds={"count": "100"}),
        lambda u: u.update(bounds={"count": True}),
        lambda u: u.update(repeat=""),
        lambda u: u.update(extra=1),
        lambda u: u.pop("repeat"),
        lambda u: u.update(selectors=["nope"]),  # not one of its parameters
        lambda u: u.update(selectors="host"),
    ],
)
def test_the_map_reads_a_utility_strictly(change: Any) -> None:
    data = json.loads(policy.MAP_FILE.read_text())
    change(data["operations"]["pingFromDevice"]["utility"])
    with pytest.raises(policy.PolicyUnreadableError, match="pingFromDevice"):
        policy.PolicyMap.from_data(data)


def test_a_map_of_the_previous_version_is_refused() -> None:
    data = json.loads(policy.MAP_FILE.read_text())
    assert data["version"] == policy.VERSION == 2
    data["version"] = 1
    with pytest.raises(policy.PolicyUnreadableError):
        policy.PolicyMap.from_data(data)


def test_no_rest_node_is_made_for_a_utility() -> None:
    """A utility's node is its own (task 8): the curated REST node would POST without its contract."""
    from dewpoint.plugins.mist import nodes  # noqa: PLC0415

    made = {n.operation for n in nodes.build()}
    assert not made & set(utilities())


def test_every_disruptive_utility_names_its_selectors() -> None:
    """Review M1: the parameters that scope a disruptive command, required, never empty or `all`."""
    for op_id, e in utilities().items():
        assert e.utility is not None
        if op_id in DISRUPTIVE:
            assert e.utility.selectors and set(e.utility.selectors) <= set(e.utility.parameters), op_id
        else:
            assert e.utility.selectors == (), op_id


@pytest.mark.parametrize(
    ("op_id", "change"),
    [
        ("pingFromDevice", lambda e: e.update(nodes=[*e["nodes"], "mist.api.write"])),  # the generic write
        ("pingFromDevice", lambda e: e.update(nodes=["mist.api.write"])),
        ("pingFromDevice", lambda e: e.update(nodes=["mist.site_devices.ping", "mist.site_devices.arp"])),
        ("bounceDevicePort", lambda e: e.update(side_effect="idempotent")),  # acceptance only stays ambiguous
        ("bounceDevicePort", lambda e: e.update(capability="mist.diagnose")),
        ("pingFromDevice", lambda e: e.update(capability="mist.write")),  # a disruptive one is acceptance only
        ("pingFromDevice", lambda e: e.update(capability="mist.read")),
        ("pingFromDevice", lambda e: e.update(scope="org")),
        ("pingFromDevice", lambda e: e["utility"].update(bounds={"nope": 5, "max_duration_s": 240})),
        ("bounceDevicePort", lambda e: e["utility"].update(bounds={"max_duration_s": 60})),  # not a stream
        ("bounceDevicePort", lambda e: e["utility"].update(selectors=[])),  # disruptive: its selectors
    ],
)  # fmt: skip
def test_the_map_refuses_an_inconsistent_utility_entry(op_id: str, change: Any) -> None:
    """Review L5: what make_map guarantees is checked again where the map is read: a hand-edited map can't grant
    it."""
    data = json.loads(policy.MAP_FILE.read_text())
    change(data["operations"][op_id])
    with pytest.raises(policy.PolicyUnreadableError, match=op_id):
        policy.PolicyMap.from_data(data)
