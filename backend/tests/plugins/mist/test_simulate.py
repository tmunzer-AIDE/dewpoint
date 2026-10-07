# SPDX-License-Identifier: Apache-2.0
"""Simulate never sends (plugins-3 D13): a Mist node answers its operation's 2xx example from the OAS, shaped as its
output, when it matches the output schema; else a value made from the schema. The step's `simulated` outcome is what
marks it as a fixture."""

import uuid
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from dewpoint.plugins.mist import PLUGIN, policy
from dewpoint.plugins.mist.nodes import MistOperation, fixture_of
from dewpoint.sdk import FatalError, node_manifest
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, FakeStep

WLAN = "7b2c4d6e-8f10-4a2b-9c3d-4e5f6a7b8c9d"


class NoConnection(FakeStep):
    async def connection(self, connection_id: uuid.UUID) -> FakeConnection:
        raise AssertionError("a simulated step opened its connection")


def step() -> NoConnection:
    return NoConnection(FakeConnection(FakeHttp({})))


async def simulate(type_: str, config: dict[str, Any]) -> Any:
    kind = next(n for n in PLUGIN.nodes if n.type == type_)
    value = kind.Config.model_validate({"connection": str(uuid.uuid4()), **config})
    return (await kind().simulate(step(), value)).model_dump(mode="json")  # type: ignore[arg-type]


def test_every_node_simulates_a_value_its_output_schema_accepts() -> None:
    sources: dict[str, int] = {}
    for n in PLUGIN.nodes:
        if not issubclass(n, MistOperation):  # the any-endpoint nodes answer their operation's example
            continue
        schema = node_manifest(n)["output_schema"]
        fixture, source = fixture_of(n)
        assert list(Draft202012Validator(schema).iter_errors(fixture)) == [], n.type
        sources[source] = sources.get(source, 0) + 1
    assert sources == {"example": 181, "schema": 40, "fixed": 41}  # the ledger records why


async def test_a_read_answers_its_example() -> None:
    out = await simulate("mist.org_wlans.get", {"wlan_id": WLAN})
    assert out == fixture_of(next(n for n in PLUGIN.nodes if n.type == "mist.org_wlans.get"))[0]
    assert isinstance(out, dict) and out


async def test_a_list_answers_its_example_as_results() -> None:
    out = await simulate("mist.org_sites.list", {})
    assert set(out) == {"results", "total", "truncated"} and out["truncated"] is False


async def test_a_delete_and_an_action_simulate_their_fixed_answers() -> None:
    assert await simulate("mist.org_wlans.delete", {"wlan_id": WLAN}) == {"already_absent": False}
    assert await simulate("mist.org_alarms.ack", {"alarm_id": WLAN}) == {}


async def test_an_update_refuses_the_same_configs_as_its_run() -> None:
    with pytest.raises(FatalError) as e:
        await simulate("mist.org_wlans.update", {"wlan_id": WLAN, "body": {"ssid": "x"}, "clear": ["ssid"]})
    assert e.value.code == "mist.conflicting_change"


async def test_an_operation_the_map_no_longer_allows_is_not_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    held = policy.PolicyMap(
        policy.load().oas_sha256,
        {**policy.load().entries, "getOrgWLAN": policy.Entry("GET", "/api/v1/orgs/{org_id}/wlans/{wlan_id}", "held",
                                                              reason="unreviewed")},
    )  # fmt: skip
    monkeypatch.setattr(policy, "load", lambda: held)
    with pytest.raises(FatalError) as e:
        await simulate("mist.org_wlans.get", {"wlan_id": WLAN})
    assert e.value.code == "mist.operation_unavailable"
