# SPDX-License-Identifier: Apache-2.0
"""Plugin code outside runs and connection types in the SDK (plugins-3 D3, D11, D12): options fields and their hook,
a node's icon, connection types declared by a plugin, and the manifest keys each adds only when set."""

import uuid
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.sdk import (
    CallContext,
    Connection,
    ConnectionType,
    HeaderAuth,
    HostMap,
    ManifestError,
    Node,
    Option,
    OptionsQuery,
    Plugin,
    RateScope,
    UrlField,
    VerifyResult,
    connection_field,
    node_manifest,
    options_field,
)
from dewpoint.sdk.fields import OPTIONS


class PickConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: uuid.UUID = connection_field("demo")
    site_id: str = options_field()
    note: str = ""


class Pick(Node):
    type = "demo.pick"
    version = 1
    title = "Pick"
    Config = PickConfig
    credentials = ("demo",)

    async def run(self, ctx: Any, config: Any) -> BaseModel:
        raise NotImplementedError

    async def options(self, ctx: CallContext, field: str, query: OptionsQuery) -> list[Option]:
        return [Option(value="s1", label="Site 1")]


class Plain(Node):
    type = "demo.plain"
    version = 1
    title = "Plain"

    async def run(self, ctx: Any, config: Any) -> BaseModel:
        raise NotImplementedError


def test_an_options_field_is_marked_and_listed_in_the_manifest() -> None:
    m = node_manifest(Pick)
    assert m["options"] == ["site_id"]
    assert m["config_schema"]["properties"]["site_id"][OPTIONS] is True


def test_a_node_without_options_or_icon_adds_neither_key() -> None:
    m = node_manifest(Plain)
    assert "options" not in m
    assert "icon" not in m


def test_an_options_field_needs_the_hook() -> None:
    class NoHook(Pick):
        type = "demo.no_hook"
        options = Node.options  # type: ignore[assignment]

    with pytest.raises(ManifestError, match="implement options"):
        node_manifest(NoHook)


def test_an_options_field_must_be_top_level() -> None:
    class Inner(BaseModel):
        site_id: str = options_field()

    class NestedConfig(BaseModel):
        inner: Inner

    class Nested(Pick):
        type = "demo.nested"
        Config = NestedConfig

    with pytest.raises(ManifestError, match="options field must be a top-level"):
        node_manifest(Nested)


def test_an_icon_is_a_short_name() -> None:
    class Iconic(Plain):
        icon = "branch"

    assert node_manifest(Iconic)["icon"] == "branch"

    class Bad(Plain):
        icon = "https://example.com/x.svg"

    with pytest.raises(ManifestError, match="icon"):
        node_manifest(Bad)


class DemoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: Literal["eu", "us"]
    org_id: uuid.UUID


class FreeRegionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: str


class OptionalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: Literal["eu", "us"] = "eu"
    org_id: uuid.UUID | None = None


class OptionalSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = SecretStr("default-token")


class DemoSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: SecretStr = Field(min_length=4)


async def _verify(ctx: CallContext, connection: Connection) -> VerifyResult:
    return VerifyResult(ok=True, detail="ok")


DEMO = ConnectionType(
    key="demo",
    label="Demo",
    Config=DemoConfig,
    Secret=DemoSecret,
    auth=HeaderAuth("Authorization", "Token {token}"),
    host=HostMap("region", {"eu": "api.eu.example.com", "us": "api.example.com"}),
    rate_scopes=(
        RateScope("demo.org", config=("region", "org_id"), capacity=50, refill_per_s=1.25),
        RateScope("demo.token", secret="token", capacity=50, refill_per_s=1.25),
    ),
    verify=_verify,
)


def test_a_connection_type_manifest_is_data() -> None:
    m = DEMO.manifest()
    assert {k: v for k, v in m.items() if k not in ("config_schema", "secret_schema")} == {
        "key": "demo",
        "label": "Demo",
        "auth": {"kind": "header", "header": "Authorization", "template": "Token {token}"},
        "host": {"kind": "map", "field": "region", "hosts": {"eu": "api.eu.example.com", "us": "api.example.com"}},
        "rate_scopes": [
            {"kind": "demo.org", "config": ["region", "org_id"], "secret": None, "capacity": 50.0,
             "refill_per_s": 1.25},
            {"kind": "demo.token", "config": [], "secret": "token", "capacity": 50.0, "refill_per_s": 1.25},
        ],
        "verify": True,
    }  # fmt: skip
    assert m["config_schema"]["properties"]["org_id"]["format"] == "uuid"
    assert m["secret_schema"]["properties"]["token"]["x-sensitive"] is True
    assert m["secret_schema"]["additionalProperties"] is False


def test_a_plugin_lists_its_connection_types_only_when_it_has_some() -> None:
    assert "connection_types" not in Plugin("demo", "1.0.0", (Plain,)).manifest()
    m = Plugin("demo", "1.0.0", (Pick,), connection_types=(DEMO,)).manifest()
    assert [t["key"] for t in m["connection_types"]] == ["demo"]


def test_a_plugin_may_declare_only_connection_types() -> None:
    m = Plugin("demo", "1.0.0", (), connection_types=(DEMO,)).manifest()
    assert m["nodes"] == []


@pytest.mark.parametrize("key", ["other", "demox", "Demo", "demo.", "demo..x"])
def test_a_connection_type_key_is_the_plugin_name_or_under_it(key: str) -> None:
    kind = ConnectionType(key=key, label="X", Config=DemoConfig, Secret=DemoSecret)
    with pytest.raises(ManifestError, match="connection type"):
        Plugin("demo", "1.0.0", (), connection_types=(kind,)).manifest()


def test_a_sub_key_under_the_plugin_name_is_accepted() -> None:
    kind = ConnectionType(key="demo.webhook", label="X", Config=DemoConfig, Secret=DemoSecret)
    assert Plugin("demo", "1.0.0", (), connection_types=(kind,)).manifest()["connection_types"][0]["key"] == (
        "demo.webhook"
    )


def test_a_plugin_declares_each_connection_type_once() -> None:
    with pytest.raises(ManifestError, match="duplicate connection type"):
        Plugin("demo", "1.0.0", (), connection_types=(DEMO, DEMO)).manifest()


def test_a_plugin_needs_a_node_or_a_connection_type() -> None:
    with pytest.raises(ManifestError, match="declares nothing"):
        Plugin("demo", "1.0.0", ()).manifest()


class PlainSecret(BaseModel):
    token: str


@pytest.mark.parametrize(
    ("kind", "problem"),
    [
        (ConnectionType("demo", "D", DemoConfig, PlainSecret), "secret field 'token' must be a SecretStr"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, auth=HeaderAuth("Authorization", "Token {nope}")),
         "auth template names 'nope'"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, auth=HeaderAuth("Bad Header", "Token {token}")),
         "auth header"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret,
                        auth=HeaderAuth("Authorization", "Bearer {token:>{token}}")),
         "auth template may only name fields"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, auth=HeaderAuth("Authorization", "Bearer {token!r}")),
         "auth template may only name fields"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, auth=HeaderAuth("Authorization", "Bearer {token.x}")),
         "auth template names 'token.x'"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, host=HostMap("nope", {"eu": "api.example.com"})),
         "host field 'nope'"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, host=HostMap("region", {"eu": "https://x/"})),
         "host 'https://x/'"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, host=UrlField("nope")), "host field 'nope'"),
        (ConnectionType("demo", "D", FreeRegionConfig, DemoSecret, host=HostMap("region", {"eu": "api.example.com"})),
         "host field 'region' must allow exactly the host map's keys"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, host=HostMap("region", {"eu": "api.example.com"})),
         "host field 'region' must allow exactly the host map's keys"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, rate_scopes=(RateScope("demo.x", config=("nope",)),)),
         "rate scope 'demo.x' names 'nope'"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, rate_scopes=(RateScope("demo.x", secret="nope"),)),
         "rate scope 'demo.x' names 'nope'"),
        (ConnectionType("demo", "D", OptionalConfig, DemoSecret,
                        host=HostMap("region", {"eu": "api.eu.example.com", "us": "api.example.com"})),
         "host field 'region' must be required"),
        (ConnectionType("demo", "D", OptionalConfig, DemoSecret,
                        rate_scopes=(RateScope("demo.x", config=("org_id",)),)),
         "rate scope 'demo.x' names 'org_id', which must be required"),
        (ConnectionType("demo", "D", DemoConfig, OptionalSecret, auth=HeaderAuth("Authorization", "Token {token}")),
         "auth template names 'token', which must be required"),
        (ConnectionType("demo", "D", DemoConfig, OptionalSecret, rate_scopes=(RateScope("demo.x", secret="token"),)),
         "rate scope 'demo.x' names 'token', which must be required"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, rate_scopes=(RateScope("other.x"),)),
         "rate scope 'other.x' must start with 'demo.'"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret,
                        rate_scopes=(RateScope("demo.x", capacity=0, refill_per_s=1),)), "rate scope 'demo.x'"),
        # `$` also matches before a final newline (the owner's review R3 of 3b-2): each name is matched whole
        (ConnectionType("demo.x\n", "D", DemoConfig, DemoSecret), "key must be a lowercase identifier"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, auth=HeaderAuth("Authorization\n", "Token {token}")),
         "auth header"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret,
                        host=HostMap("region", {"eu": "api.eu.example.com\n", "us": "api.example.com"})),
         "must be a host name"),
        (ConnectionType("demo", "D", DemoConfig, DemoSecret, rate_scopes=(RateScope("demo.x\n"),)),
         "must start with 'demo.'"),
    ],
)  # fmt: skip
def test_a_connection_type_is_checked(kind: ConnectionType, problem: str) -> None:
    with pytest.raises(ManifestError) as raised:
        Plugin("demo", "1.0.0", (), connection_types=(kind,)).manifest()
    assert any(problem in p for p in raised.value.problems), raised.value.problems


def test_a_connection_type_key_fits_a_connections_type_column() -> None:
    """`connections.type` is 64 characters (the 3a-2 review's finding 4)."""
    plugin = "p" * 30
    kind = ConnectionType(key=f"{plugin}.{'x' * 40}", label="X", Config=DemoConfig, Secret=DemoSecret)
    with pytest.raises(ManifestError, match="connection type"):
        Plugin(plugin, "1.0.0", (), connection_types=(kind,)).manifest()
