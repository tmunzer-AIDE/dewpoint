# SPDX-License-Identifier: Apache-2.0
"""The operation-policy map (plugins-3 D28, D24, D14): one generated file with an entry for every operation of the
vendored OAS. Only reviewed operations are allowed (D28 a), each to its curated node and the any-endpoint node of its
method; the owner's held operations, every unreviewed one and every deprecated one reach nothing; the always-refused
routes are denied whatever a review says."""

import json
import re
from pathlib import Path

import pytest

from dewpoint.plugins.mist import oas, policy, reviews
from dewpoint.sdk.node import TYPE_RE

CURATED = {op: (method, path) for op, method, path in json.loads((Path(__file__).parent / "curated.json").read_text())}


def test_the_map_is_what_the_reviews_make() -> None:
    made = reviews.make_map()
    assert policy.load() == policy.PolicyMap.from_data(made)
    assert policy.MAP_FILE.read_text() == reviews.render(made)  # regenerate: python -m dewpoint.plugins.mist.reviews


def test_every_operation_has_one_entry_with_its_method_and_path() -> None:
    entries = policy.load().entries
    assert set(entries) == set(oas.operations())
    for op_id, op in oas.operations().items():
        assert (entries[op_id].method, entries[op_id].path) == (op.method, op.path)


def test_only_the_reviewed_operations_are_allowed() -> None:
    entries = policy.load().entries
    allowed = {op for op, e in entries.items() if e.state == "allowed" and e.utility is None}
    assert allowed == set(CURATED)
    assert {op for op, e in entries.items() if e.utility is not None} == {u.operation for u in reviews.UTILITIES}
    for op_id in allowed:
        e = entries[op_id]
        generic = "mist.api.read" if e.method == "GET" else "mist.api.write"
        assert e.nodes[1:] == (generic,) and TYPE_RE.match(e.nodes[0]) and e.nodes[0].startswith("mist."), op_id
        assert e.capability == ("mist.read" if e.method == "GET" else "mist.write")
        assert e.scope in ("org", "site", "metadata") and e.evidence and e.reason is None
    curated = [entries[op].nodes[0] for op in allowed]
    assert len(set(curated)) == len(curated)


@pytest.mark.parametrize(
    ("method", "kind"),
    [("GET", "none"), ("PUT", "idempotent"), ("DELETE", "idempotent"), ("POST", "ambiguous")],
)
def test_side_effects_follow_the_method_with_their_evidence(method: str, kind: str) -> None:
    """A curated operation's (a utility's is reviewed on its own: test_utility_reviews)."""
    found = [e for e in policy.load().entries.values()
             if e.state == "allowed" and e.method == method and e.utility is None]  # fmt: skip
    assert found and {e.side_effect for e in found} == {kind}
    assert {e.evidence for e in found} == {reviews.EVIDENCE[kind]}


def test_held_unreviewed_and_deprecated_operations_reach_nothing() -> None:
    entries = policy.load().entries
    for op_id, reason in reviews.HELD.items():
        assert (entries[op_id].state, entries[op_id].reason, entries[op_id].nodes) == ("held", reason, ())
    for op_id, op in oas.operations().items():
        e = entries[op_id]
        if op.deprecated:
            assert (e.state, e.reason) == ("denied", "deprecated")
        if e.state != "allowed":
            assert e.nodes == () and e.side_effect is None and e.reason
    assert entries["listOrgApiTokens"].state == "denied"
    assert entries["getOrgPsk"].state == "allowed" and entries["listOrgVpns"].reason == "unreviewed"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/self", "/api/v1/self/apitokens", "/api/v1/msps/{msp_id}/orgs", "/api/v1/login", "/api/v1/logout",
        "/api/v1/register", "/api/v1/recover/verify/{token}", "/api/v1/invite/verify/{token}", "/api/v1/installer/orgs",
        "/api/v1/mobile/verify/{secret}", "/api/v1/utils/test_twilio", "/api/v1/orgs/{org_id}/apitokens",
        "/api/v1/orgs/{org_id}/admins/{admin_id}", "/api/v1/orgs/{org_id}/invites", "/api/v1/orgs/{org_id}/ssos",
        "/api/v1/orgs/{org_id}/ssoroles/{ssorole_id}", "/api/v1/orgs/{org_id}/sdkinvites",
        "/api/v1/orgs/{org_id}/marvisinvites", "/api/v1/orgs/{org_id}/cert", "/api/v1/orgs/{org_id}/crl",
        "/api/v1/orgs/{org_id}/ssl_proxy_cert", "/api/v1/orgs/{org_id}/setting/juniper/link_accounts",
        "/api/v1/orgs/{org_id}/setting/{app_name}/link_accounts/{account_id}",
        "/api/v1/orgs/{org_id}/setting/mist_scep/client_certs", "/api/v1/orgs/{org_id}/setting/mist_nac_crls",
        "/api/v1/orgs/{org_id}/ssr/export_idtokens", "/api/v1/orgs/{org_id}/ssr/register_cmd",
        "/api/v1/sites/{site_id}/devices/{device_id}/request_ztp_password", "/api/v2/orgs/{org_id}", "/api/v1",
        "/orgs/{org_id}", "/api/v1/orgs/{org_id}/../self",
    ],
)  # fmt: skip
def test_account_and_authentication_routes_are_always_refused(path: str) -> None:
    assert policy.refused(path)
    op = next((o for o in oas.operations().values() if o.path == path), None)
    if op is not None:
        assert (policy.load().entries[op.id].state, policy.load().entries[op.id].reason) == ("denied", "always_refused")


@pytest.mark.parametrize(
    "path",
    ["/api/v1/orgs/{org_id}/wlans", "/api/v1/sites/{site_id}/devices/{device_id}", "/api/v1/const/webhook_topics"],
)
def test_resources_are_not_refused(path: str) -> None:
    assert not policy.refused(path)


@pytest.mark.parametrize(
    ("path", "scope"),
    [
        ("/api/v1/orgs/{org_id}", "org"), ("/api/v1/orgs/{org_id}/wlans/{wlan_id}", "org"),
        ("/api/v1/sites/{site_id}", "site"), ("/api/v1/sites/{site_id}/stats", "site"),
        ("/api/v1/const/webhook_topics", "metadata"), ("/api/v1/const/countries", None), ("/api/v1/orgs", None),
        ("/api/v1/sites/{site_id}x", None),
    ],
)  # fmt: skip
def test_scope_classes(path: str, scope: str | None) -> None:
    assert policy.scope_of(path) == scope


def test_a_map_made_from_another_description_is_refused() -> None:
    data = json.loads(policy.MAP_FILE.read_text())
    data["oas_sha256"] = "0" * 64
    with pytest.raises(policy.PolicyUnreadableError):
        policy.PolicyMap.from_data(data)


def test_a_review_of_a_refused_or_deprecated_operation_fails_the_build(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reviews, "CURATED", (*reviews.CURATED, ("listOrgApiTokens", "mist.org_apitokens.list")))
    with pytest.raises(reviews.ReviewError, match="listOrgApiTokens"):
        reviews.make_map()
    monkeypatch.setattr(reviews, "CURATED", (*reviews.CURATED[:-1], ("listOrgAuditLogsLegacy", "mist.x.list")))
    with pytest.raises(reviews.ReviewError, match="listOrgAuditLogsLegacy"):
        reviews.make_map()


def test_the_rendered_map_puts_one_operation_on_a_line() -> None:
    lines = policy.MAP_FILE.read_text().splitlines()
    assert sum(1 for line in lines if re.match(r'^"[A-Za-z0-9_]+": \{"', line)) == len(oas.operations())
