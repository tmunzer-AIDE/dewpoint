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
        # `$` also matches before a final newline (the owner's review R3 of 3b-2): each name is matched whole
        (_types(lambda t: t.update(key="demo.x\n")), "must be named 'demo' or start with 'demo.'"),
        (_types(lambda t: t["auth"].update(header="Authorization\n")), "auth must be"),
        (_types(lambda t: t["host"]["hosts"].update(eu="api.eu.example.com\n")), "must be a host name"),
        (_types(lambda t: t["rate_scopes"][0].update(kind="demo.org\n")), "must start with 'demo.'"),
    ],
)  # fmt: skip
def test_new_keys_are_checked(manifest: dict[str, Any], problem: str) -> None:
    problems = validate_plugin_manifest(manifest)
    assert any(problem in p for p in problems), problems
