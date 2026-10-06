# SPDX-License-Identifier: Apache-2.0
"""Any endpoint (plugins-3 D14): `mist.api.read` (GET, no side effect) and `mist.api.write` (any other method, always
ambiguous) reach only what the policy map allows them, inside the connection's scope: the org the connection's, a
site checked to be its org's; the always-refused routes refused whatever the map says; path values checked, the query
and the body checked against the operation's description; the answer undeclared, so tainted whole."""

import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from dewpoint.plugins.mist import PLUGIN, policy, routing
from dewpoint.sdk import FatalError, Node, SideEffect, node_manifest
from tests.plugins.mist.fakes import ORG, OTHER_ORG, SITE, FakeConnection, FakeHttp, FakeStep, Reply

WLAN = "7b2c4d6e-8f10-4a2b-9c3d-4e5f6a7b8c9d"


def node(type_: str) -> type[Node]:
    return next(n for n in PLUGIN.nodes if n.type == type_)


async def call(type_: str, config: dict[str, Any], script: Any, *, validated: bool = True) -> tuple[Any, FakeHttp]:
    http = FakeHttp(script)
    connection = FakeConnection(http)
    kind = node(type_)
    raw = {"connection": str(connection.id), **config}
    value = kind.Config.model_validate(raw) if validated else kind.Config.model_construct(raw)
    out = await kind().run(FakeStep(connection), value)  # type: ignore[arg-type]
    return out.model_dump(mode="json"), http


def test_the_two_nodes_and_their_policies() -> None:
    read, write = node("mist.api.read"), node("mist.api.write")
    assert (read.side_effect, read.capabilities) == (SideEffect.NONE, frozenset({"mist.read"}))
    assert (write.side_effect, write.capabilities) == (SideEffect.AMBIGUOUS, frozenset({"mist.write"}))
    out = node_manifest(read)["output_schema"]
    assert out["properties"]["body"] == {} and set(out["required"]) == {"status", "body"}
    assert node_manifest(write)["config_schema"]["properties"]["method"]["enum"] == ["DELETE", "POST", "PUT"]


@pytest.mark.parametrize("org", [ORG, "{org_id}"])
async def test_a_read_reaches_an_allowed_operation_under_the_connections_org(org: str) -> None:
    out, http = await call(
        "mist.api.read",
        {"path": f"/api/v1/orgs/{org}/wlans/{WLAN}", "query": {}},
        {("GET", f"/api/v1/orgs/{ORG}/wlans/{WLAN}"): Reply(200, {"id": WLAN})},
    )
    assert out == {"status": 200, "body": {"id": WLAN}}


async def test_another_org_sends_nothing() -> None:
    with pytest.raises(FatalError) as e:
        await call("mist.api.read", {"path": f"/api/v1/orgs/{OTHER_ORG}/wlans"}, {})
    assert e.value.code == "mist.org_mismatch"


async def test_a_site_path_checks_its_site_first() -> None:
    out, http = await call(
        "mist.api.read",
        {"path": f"/api/v1/sites/{SITE}/stats/devices", "query": {"type": "ap"}},
        {
            ("GET", f"/api/v1/sites/{SITE}"): Reply(200, {"org_id": ORG}),
            ("GET", f"/api/v1/sites/{SITE}/stats/devices"): Reply(200, [{"num_clients": 1}]),
        },
    )
    assert out["body"] == [{"num_clients": 1}] and http.sent[1].params == {"type": "ap"}


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/self", f"/api/v1/orgs/{ORG}/apitokens", f"/api/v1/orgs/{ORG}/vpns", "/api/v1/const/countries",
        f"/api/v1/orgs/{ORG}/wlans/{WLAN}?x=1", f"/api/v1/orgs/{ORG}/wlans/../apitokens", f"/api/v2/orgs/{ORG}",
        f"https://api.mist.com/api/v1/orgs/{ORG}/wlans", f"/api/v1/orgs/{ORG}//wlans", "",
    ],
)  # fmt: skip
async def test_a_path_the_map_doesnt_allow_is_refused_at_publish_and_at_run_time(path: str) -> None:
    with pytest.raises(ValidationError):
        node("mist.api.read").Config.model_validate({"connection": str(uuid.uuid4()), "path": path})
    with pytest.raises(FatalError) as e:
        await call("mist.api.read", {"path": path}, {}, validated=False)
    assert e.value.code in ("mist.route_refused", "mist.operation_unavailable", "mist.invalid_path_value")


async def test_an_always_refused_route_is_refused_whatever_the_map_says(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = dict(policy.load().entries)
    entries["listOrgApiTokens"] = policy.Entry(
        "GET", "/api/v1/orgs/{org_id}/apitokens", "allowed", ("mist.x.list", "mist.api.read"), "mist.read", "org",
        "none", "x",
    )  # fmt: skip
    monkeypatch.setattr(policy, "load", lambda: policy.PolicyMap(policy.load().oas_sha256, entries))
    with pytest.raises(FatalError) as e:
        await call("mist.api.read", {"path": f"/api/v1/orgs/{ORG}/apitokens"}, {}, validated=False)
    assert e.value.code == "mist.route_refused"


async def test_the_most_specific_operation_wins() -> None:
    out, http = await call(
        "mist.api.read",
        {"path": f"/api/v1/orgs/{ORG}/devices/search", "query": {"limit": 5}},
        {("GET", f"/api/v1/orgs/{ORG}/devices/search"): Reply(200, {"results": []})},
    )
    assert http.sent[0].params == {"limit": 5}


async def test_a_path_value_is_checked_against_its_description() -> None:
    path = f"/api/v1/orgs/{ORG}/wlans/not-a-uuid"
    with pytest.raises(ValidationError):  # publish refuses it as a literal
        node("mist.api.read").Config.model_validate({"connection": str(uuid.uuid4()), "path": path})
    with pytest.raises(FatalError) as e:  # and the run, computed
        await call("mist.api.read", {"path": path}, {}, validated=False)
    assert e.value.code == "mist.invalid_path_value"


async def test_a_query_the_operation_doesnt_describe_is_refused() -> None:
    with pytest.raises(FatalError) as e:
        await call("mist.api.read", {"path": f"/api/v1/orgs/{ORG}/wlans", "query": {"secret": "x"}}, {})
    assert e.value.code == "mist.invalid_query"
    with pytest.raises(FatalError) as e:
        await call("mist.api.read", {"path": f"/api/v1/orgs/{ORG}/wlans", "query": {"limit": "many"}}, {})
    assert e.value.code == "mist.invalid_query"


async def test_a_write_reaches_only_its_methods_operation() -> None:
    out, http = await call(
        "mist.api.write",
        {"method": "POST", "path": f"/api/v1/orgs/{ORG}/wlans", "body": {"ssid": "corp"}},
        {("POST", f"/api/v1/orgs/{ORG}/wlans"): Reply(200, {"id": WLAN})},
    )
    assert out == {"status": 200, "body": {"id": WLAN}} and http.sent[0].json == {"ssid": "corp"}
    with pytest.raises(FatalError) as e:
        await call("mist.api.write", {"method": "DELETE", "path": f"/api/v1/orgs/{ORG}/wlans"}, {})
    assert e.value.code == "mist.operation_unavailable"


async def test_a_body_is_checked_against_the_operations_description() -> None:
    with pytest.raises(FatalError) as e:
        await call("mist.api.write", {"method": "POST", "path": f"/api/v1/orgs/{ORG}/wlans", "body": {"ssid": 3}}, {})
    assert e.value.code == "mist.invalid_body"
    with pytest.raises(FatalError) as e:
        await call(
            "mist.api.write", {"method": "DELETE", "path": f"/api/v1/orgs/{ORG}/wlans/{WLAN}", "body": {"a": 1}}, {}
        )
    assert e.value.code == "mist.invalid_body"


async def test_a_read_simulates_its_operations_example_without_sending() -> None:
    kind = node("mist.api.read")
    connection = FakeConnection(FakeHttp({}))
    value = kind.Config.model_validate({"connection": str(connection.id), "path": f"/api/v1/orgs/{ORG}/wlans/{WLAN}"})
    out = (await kind().simulate(FakeStep(connection), value)).model_dump(mode="json")  # type: ignore[arg-type]
    assert out["status"] == 200 and isinstance(out["body"], dict) and connection.http.sent == []


async def test_a_siblings_literal_is_refused_at_publish_and_at_run_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 3b-1 review's H1, for the generic nodes: `suppress` is `unsuppressOrgSuppressedAlarms`'s literal."""
    raw = {"method": "DELETE", "path": f"/api/v1/orgs/{ORG}/alarmtemplates/suppress"}
    with pytest.raises(ValidationError):
        node("mist.api.write").Config.model_validate({"connection": str(uuid.uuid4()), **raw})
    with pytest.raises(FatalError) as e:
        await call("mist.api.write", raw, {}, validated=False)
    assert e.value.code == "mist.invalid_path_value"
    accepts_all = Draft202012Validator({})
    real = routing.checkers

    def lenient(op: str) -> routing.Checkers:
        found = real(op)
        return routing.Checkers({k: accepts_all for k in found.path}, found.query, found.body)

    monkeypatch.setattr(routing, "checkers", lenient)
    with pytest.raises(FatalError) as e:  # even a parameter that would accept it can't reach the other operation
        await call("mist.api.write", raw, {}, validated=False)
    assert e.value.code == "mist.invalid_path_value"
