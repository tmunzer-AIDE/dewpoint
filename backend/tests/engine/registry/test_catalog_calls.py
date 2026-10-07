# SPDX-License-Identifier: Apache-2.0
"""The catalog checks the keys plugins-3 adds when a manifest arrives as data (D11, D12): a node's `icon` and
`options`, and a plugin's `connection_types`. A node's icon is display metadata; its options fields are contract."""

import copy
import uuid
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.engine.registry.catalog import contract_hash, validate_plugin_manifest
from dewpoint.sdk import (
    CallContext,
    Connection,
    ConnectionType,
    HeaderAuth,
    HostMap,
    Node,
    Option,
    OptionsQuery,
    Plugin,
    RateScope,
    StreamEndpoint,
    VerifyResult,
    connection_field,
    options_field,
)


class PickConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: uuid.UUID = connection_field("demo")
    site_id: str = options_field()


class Pick(Node):
    type = "demo.pick"
    version = 1
    title = "Pick"
    icon = "map-pin"
    Config = PickConfig
    credentials = ("demo",)

    async def run(self, ctx: Any, config: Any) -> BaseModel:
        raise NotImplementedError

    async def options(self, ctx: CallContext, field: str, query: OptionsQuery) -> list[Option]:
        return []


class DemoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: Literal["eu", "us"]
    org_id: uuid.UUID


class DemoSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=4)


async def _verify(ctx: CallContext, connection: Connection) -> VerifyResult:
    return VerifyResult(True, "ok")


DEMO = ConnectionType(
    "demo",
    "Demo",
    DemoConfig,
    DemoSecret,
    auth=HeaderAuth("Authorization", "Token {token}"),
    host=HostMap("region", {"eu": "api.eu.example.com", "us": "api.example.com"}),
    rate_scopes=(RateScope("demo.org", config=("region", "org_id")), RateScope("demo.token", secret="token")),
    verify=_verify,
)
MANIFEST = Plugin("demo", "1.0.0", (Pick,), connection_types=(DEMO,)).manifest()


def _with(change: Any) -> dict[str, Any]:
    m = copy.deepcopy(MANIFEST)
    change(m)
    return m


def test_a_manifest_with_options_icons_and_connection_types_validates() -> None:
    assert validate_plugin_manifest(MANIFEST) == []


def test_a_plugin_with_only_connection_types_validates() -> None:
    assert validate_plugin_manifest(Plugin("demo", "1.0.0", (), connection_types=(DEMO,)).manifest()) == []


def _nothing(m: dict[str, Any]) -> None:
    m["nodes"] = []
    del m["connection_types"]


def test_a_plugin_declaring_nothing_is_refused() -> None:
    assert any("declares nothing" in p for p in validate_plugin_manifest(_with(_nothing)))


def test_connection_types_are_listed_only_when_set() -> None:
    assert any("only when set" in p for p in validate_plugin_manifest(_with(lambda m: m.update(connection_types=[]))))


def test_an_icon_is_display_metadata_and_options_are_contract() -> None:
    node = MANIFEST["nodes"][0]
    assert contract_hash({**node, "icon": "flag"}) == contract_hash(node)
    assert contract_hash({k: v for k, v in node.items() if k != "icon"}) == contract_hash(node)
    assert contract_hash({**node, "options": []}) != contract_hash(node)


def _node(change: Any) -> dict[str, Any]:
    return _with(lambda m: change(m["nodes"][0]))


def _types(change: Any) -> dict[str, Any]:
    return _with(lambda m: change(m["connection_types"][0]))


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (_node(lambda n: n.update(icon="https://x/y.svg")), "icon"),
        (_node(lambda n: n.update(icon=5)), "icon"),
        (_node(lambda n: n.update(options=["note"])), "options field 'note'"),
        (_node(lambda n: n.update(options="site_id")), "options must list"),
        (_node(lambda n: n.update(options=["site_id", "site_id"])), "options must list"),
        (_node(lambda n: n.pop("options")), "marks 'site_id'"),
        (_types(lambda t: t.update(key="other")), "connection type 'other'"),
        (_types(lambda t: t.update(label="")), "label"),
        (_types(lambda t: t["config_schema"].update(type=5)), "config_schema"),
        (_types(lambda t: t["config_schema"].update(additionalProperties=True)), "additional properties"),
        (_types(lambda t: t["secret_schema"]["properties"]["token"].pop("x-sensitive")), "x-sensitive"),
        (_types(lambda t: t.update(auth={"kind": "header", "header": "Authorization", "template": "{nope}"})),
         "auth template names 'nope'"),
        (_types(lambda t: t.update(auth={"kind": "basic"})), "auth"),
        (_types(lambda t: t.update(auth={"kind": "header", "header": "Authorization", "template": "{token:x>999999}"})),
         "auth template may only name fields"),
        (_types(lambda t: t.update(auth={"kind": "header", "header": "Authorization", "template": "{token!s}"})),
         "auth template may only name fields"),
        (_types(lambda t: t.update(host={"kind": "map", "field": "region", "hosts": {"eu": "api.example.com"}})),
         "allow exactly the host map's keys"),
        (_types(lambda t: t.update(host={"kind": "map", "field": "region",
                                         "hosts": {"eu": "x/y", "us": "api.example.com"}})), "host 'x/y'"),
        (_types(lambda t: t.update(host={"kind": "url_field", "field": "nope"})), "host field 'nope'"),
        (_types(lambda t: t["rate_scopes"][0].update(kind="other.org")), "must start with 'demo.'"),
        (_types(lambda t: t["rate_scopes"][0].update(config=["nope"])), "names 'nope'"),
        (_types(lambda t: t["rate_scopes"][1].update(secret="nope")), "names 'nope'"),
        (_types(lambda t: t["rate_scopes"][0].update(capacity=0)), "capacity"),
        (_types(lambda t: t["config_schema"].update(required=["org_id"])), "host field 'region' must be required"),
        (_types(lambda t: t["config_schema"].update(required=["region"])),
         "rate scope 'demo.org' names 'org_id', which must be required"),
        (_types(lambda t: t["secret_schema"].update(required=[])),
         "auth template names 'token', which must be required"),
        (_types(lambda t: t.update(verify="yes")), "verify"),
        (_with(lambda m: m["connection_types"].append(copy.deepcopy(m["connection_types"][0]))),
         "duplicate connection type 'demo'"),
    ],
)  # fmt: skip
def test_new_keys_are_checked(manifest: dict[str, Any], problem: str) -> None:
    problems = validate_plugin_manifest(manifest)
    assert any(problem in p for p in problems), problems


STREAM = {
    "kind": "map",
    "field": "region",
    "hosts": {"eu": "ws.eu.example.com", "us": "ws.example.com"},
    "path": "/ws/v1/stream",
    "rate_scopes": [{"kind": "demo.stream", "config": [], "secret": "token", "capacity": 30.0, "refill_per_s": 0.5}],
}


def _streams(change: Any) -> dict[str, Any]:
    def both(t: dict[str, Any]) -> None:
        t["stream"] = copy.deepcopy(STREAM)
        change(t["stream"] if change is not None else t)

    return _types(both)


def test_a_connection_types_stream_validates_as_the_sdk_writes_it() -> None:
    """The stream endpoint (plugins-3 D26), checked as data by the same rules as the SDK's."""
    stream = StreamEndpoint(
        HostMap("region", STREAM["hosts"]), STREAM["path"], (RateScope("demo.stream", secret="token", capacity=30,
                                                                         refill_per_s=0.5),),
    )  # fmt: skip
    kind = ConnectionType("demo", "Demo", DemoConfig, DemoSecret, stream=stream)
    manifest = Plugin("demo", "1.0.0", (), connection_types=(kind,)).manifest()
    assert manifest["connection_types"][0]["stream"] == STREAM
    assert validate_plugin_manifest(manifest) == []


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (_types(lambda t: t.update(stream=None)), "stream must be"),
        (_types(lambda t: t.update(stream="wss://x/")), "stream must be"),
        (_streams(lambda s: s.update(kind="url_field")), "stream must be"),
        (_streams(lambda s: s.update(extra=1)), "stream must be"),
        (_streams(lambda s: s.update(field="nope")), "stream host field 'nope'"),
        (_streams(lambda s: s.update(hosts={"eu": "ws.eu.example.com"})), "stream host field 'region' must allow"),
        (_streams(lambda s: s.update(hosts={"eu": "x/y", "us": "ws.example.com"})), "stream host 'x/y'"),
        (_streams(lambda s: s.update(path="ws")), "stream path"),
        (_streams(lambda s: s.update(path="/ws/../x")), "stream path"),
        (_streams(lambda s: s.update(path="//other.example.com/ws")), "stream path"),
        (_streams(lambda s: s.update(path=5)), "stream path"),
        (_streams(lambda s: s["rate_scopes"][0].update(kind="other.stream")), "must start with 'demo.'"),
        (_streams(lambda s: s["rate_scopes"][0].update(secret="nope")), "names 'nope'"),
        (_streams(lambda s: s.update(rate_scopes="all")), "stream rate_scopes must be a list"),
        (_with(lambda m: (m["connection_types"][0].update(stream=copy.deepcopy(STREAM)),
                          m["connection_types"][0]["config_schema"].update(required=["org_id"]))),
         "stream host field 'region' must be required"),
        (_with(lambda m: (m["connection_types"][0].update(stream=copy.deepcopy(STREAM)),
                          m["connection_types"][0]["secret_schema"].update(required=[]))),
         "rate scope 'demo.stream' names 'token', which must be required"),
    ],
)  # fmt: skip
def test_a_stream_is_checked(manifest: dict[str, Any], problem: str) -> None:
    problems = validate_plugin_manifest(manifest)
    assert any(problem in p for p in problems), problems


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (_streams(lambda s: s.update(path="/ws/v1/stream\n")), "stream path"),
        (_streams(lambda s: s.update(hosts={"eu": "ws.eu.example.com\n", "us": "ws.example.com"})), "stream host"),
        (_types(lambda t: t["host"]["hosts"].update(eu="api.eu.example.com\n")), "host 'api.eu.example.com\\n'"),
    ],
)  # fmt: skip
def test_a_trailing_newline_is_refused_as_data_too(manifest: dict[str, Any], problem: str) -> None:
    problems = validate_plugin_manifest(manifest)
    assert any(problem in p for p in problems), problems
