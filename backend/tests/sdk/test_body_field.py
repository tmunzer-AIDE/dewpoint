# SPDX-License-Identifier: Apache-2.0
"""SDK 0.8.0 (plugins-3 3d-1, D4's `body_field`): a connection type's credentials as one top-level field of a
request's JSON body (PagerDuty's `routing_key`), a required secret field's value the runtime puts there; the plugin
never holds it. The SDK and the catalog check the declaration as data."""

import copy
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.core.connections.declared import DeclaredType
from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.sdk import BodyField, ConnectionType, HostMap, ManifestError, Plugin
from dewpoint.sdk.version import SDK_VERSION


class NoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: str = Field(json_schema_extra={"enum": ["us"]})


class KeySecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    routing_key: SecretStr = Field(min_length=32, max_length=32)


class OptionalSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    routing_key: SecretStr = SecretStr("")


HOSTS = HostMap("region", {"us": "events.example.com"})
KIND = ConnectionType("demo", "Demo events", NoConfig, KeySecret, auth=BodyField("routing_key", "routing_key"),
                      host=HOSTS)  # fmt: skip


def plugin(*kinds: ConnectionType) -> Plugin:
    return Plugin("demo", "1.0.0", (), connection_types=kinds)


def test_the_sdk_is_0_8_0() -> None:
    assert SDK_VERSION == "0.8.0"


def test_a_body_field_is_data() -> None:
    assert KIND.manifest()["auth"] == {"kind": "body_field", "field": "routing_key", "secret": "routing_key"}
    assert validate_plugin_manifest(plugin(KIND).manifest()) == []


def test_the_runtime_reads_the_body_field_from_the_secret_and_sends_no_header() -> None:
    declared = DeclaredType.from_manifest("demo", KIND.manifest())
    secret = {"routing_key": "k" * 32}
    assert declared.credentials(secret) == {} and declared.body_credentials(secret) == {"routing_key": "k" * 32}
    header = DeclaredType.from_manifest("demo", {**KIND.manifest(), "auth": {"kind": "header", "header": "X-Key",
                                                                             "template": "{routing_key}"}})  # fmt: skip
    assert header.body_credentials(secret) == {}


@pytest.mark.parametrize(
    ("kind", "problem"),
    [
        (ConnectionType("demo", "D", NoConfig, KeySecret, auth=BodyField("routing_key", "nope"), host=HOSTS),
         "auth body field's secret 'nope' isn't a required secret field"),
        (ConnectionType("demo", "D", NoConfig, OptionalSecret, auth=BodyField("routing_key", "routing_key"),
                        host=HOSTS),
         "auth body field's secret 'routing_key' isn't a required secret field"),
        (ConnectionType("demo", "D", NoConfig, KeySecret, auth=BodyField("routing key", "routing_key"), host=HOSTS),
         "auth body field 'routing key' must be an identifier"),
        (ConnectionType("demo", "D", NoConfig, KeySecret, auth=BodyField("a.b", "routing_key"), host=HOSTS),
         "auth body field 'a.b' must be an identifier"),
    ],
)  # fmt: skip
def test_a_body_field_is_checked(kind: ConnectionType, problem: str) -> None:
    with pytest.raises(ManifestError) as raised:
        plugin(kind).manifest()
    assert any(problem in p for p in raised.value.problems), raised.value.problems


def _kind(change: Any) -> dict[str, Any]:
    m = plugin(KIND).manifest()
    change(m["connection_types"][0])
    return m


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (_kind(lambda t: t["auth"].update(secret="nope")), "isn't a required secret field"),
        (_kind(lambda t: t["auth"].update(field="a b")), "must be an identifier"),
        (_kind(lambda t: t["auth"].update(extra=1)), "auth must be {kind: header"),
        (_kind(lambda t: t["auth"].pop("secret")), "auth must be {kind: header"),
        (_kind(lambda t: t["auth"].update(kind="query")), "auth must be {kind: header"),
        (_kind(lambda t: t["secret_schema"].update(required=[])), "isn't a required secret field"),
    ],
)  # fmt: skip
def test_a_body_field_is_checked_as_data(manifest: dict[str, Any], problem: str) -> None:
    problems = validate_plugin_manifest(copy.deepcopy(manifest))
    assert any(problem in p for p in problems), problems
