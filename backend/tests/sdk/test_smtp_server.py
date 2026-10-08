# SPDX-License-Identifier: Apache-2.0
"""SDK 0.7.0 (plugins-3 3c-2, D4, D20): a connection type may declare an SMTP server (`SmtpServer`): the config fields
holding its host, port, security (`starttls`, `tls`, `none`) and sender, and optionally a username config field and a
password secret field. The runtime speaks SMTP and applies the password; the plugin never holds it, nor can it name
another server or sender. The SDK and the catalog check the declaration as data; `MAIL_ADDRESS` is the one address
form both the runtime and plugins accept; a definite refusal names its stage and reply code."""

import copy
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.sdk import (
    MAIL_ADDRESS,
    AuthUnavailable,
    ConnectionType,
    HeaderAuth,
    MailRefused,
    ManifestError,
    Plugin,
    RateScope,
    SmtpServer,
    TlsUnavailable,
)
from dewpoint.sdk.version import SDK_VERSION


class MailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    port: int = Field(ge=1, le=65535)
    security: Literal["starttls", "tls", "none"]
    from_address: str
    username: str | None = None


class MailSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = SecretStr("")


class LooseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str
    port: int = 587  # not required
    security: Literal["starttls", "tls", "none", "maybe"]
    from_address: str
    username: str | None = None


SERVER = SmtpServer(host="host", port="port", security="security", sender="from_address", username="username",
                    password="password")  # fmt: skip
SERVER_SCOPE = RateScope("demo.server", config=("host",), capacity=5, refill_per_s=1)
MAIL = ConnectionType("demo", "Demo mail", MailConfig, MailSecret, smtp=SERVER, rate_scopes=(SERVER_SCOPE,))


def plugin(*kinds: ConnectionType) -> Plugin:
    return Plugin("demo", "1.0.0", (), connection_types=kinds)


def test_the_sdk_is_0_7_0() -> None:
    assert SDK_VERSION == "0.7.0"


def test_an_smtp_type_is_data() -> None:
    m = MAIL.manifest()
    assert m["smtp"] == {"host": "host", "port": "port", "security": "security", "sender": "from_address",
                         "username": "username", "password": "password"}  # fmt: skip
    assert m["host"] is None and m["auth"] is None and "stream" not in m
    assert validate_plugin_manifest(plugin(MAIL).manifest()) == []
    assert "smtp" not in ConnectionType("demo", "D", MailConfig, MailSecret).manifest()  # only when declared


def test_an_smtp_type_without_a_login_is_data() -> None:
    relay = SmtpServer(host="host", port="port", security="security", sender="from_address")
    kind = ConnectionType("demo", "Relay", MailConfig, MailSecret, smtp=relay)
    assert kind.manifest()["smtp"]["username"] is None and kind.manifest()["smtp"]["password"] is None
    assert validate_plugin_manifest(plugin(kind).manifest()) == []


def _with(**changes: Any) -> SmtpServer:
    return SmtpServer(**{"host": "host", "port": "port", "security": "security", "sender": "from_address",
                         "username": "username", "password": "password", **changes})  # fmt: skip


@pytest.mark.parametrize(
    ("kind", "problem"),
    [
        (ConnectionType("demo", "D", MailConfig, MailSecret, smtp=_with(host="nope")),
         "smtp host field 'nope' isn't a required config field"),
        (ConnectionType("demo", "D", MailConfig, MailSecret, smtp=_with(sender="username")),
         "smtp sender field 'username' isn't a required config field"),  # optional
        (ConnectionType("demo", "D", LooseConfig, MailSecret, smtp=_with()),
         "smtp port field 'port' isn't a required config field"),
        (ConnectionType("demo", "D", LooseConfig, MailSecret, smtp=SmtpServer("host", "security", "security",
                                                                              "from_address")),
         "smtp security field 'security' may only allow 'none', 'starttls', 'tls'"),
        (ConnectionType("demo", "D", MailConfig, MailSecret, smtp=_with(security="host")),
         "smtp security field 'host' may only allow 'none', 'starttls', 'tls'"),
        (ConnectionType("demo", "D", MailConfig, MailSecret, smtp=_with(password=None)),
         "smtp username and password are named together"),
        (ConnectionType("demo", "D", MailConfig, MailSecret, smtp=_with(username=None)),
         "smtp username and password are named together"),
        (ConnectionType("demo", "D", MailConfig, MailSecret, smtp=_with(password="from_address")),
         "smtp password field 'from_address' isn't a secret field"),
        (ConnectionType("demo", "D", MailConfig, MailSecret, smtp=_with(username="password")),
         "smtp username field 'password' isn't a config field"),
        (ConnectionType("demo", "D", MailConfig, MailSecret, smtp=_with(), auth=HeaderAuth("X-Key", "{password}")),
         "an SMTP type has no HTTP host, auth header or stream"),
    ],
)  # fmt: skip
def test_an_smtp_type_is_checked(kind: ConnectionType, problem: str) -> None:
    with pytest.raises(ManifestError) as raised:
        plugin(kind).manifest()
    assert any(problem in p for p in raised.value.problems), raised.value.problems


def _mail(change: Any) -> dict[str, Any]:
    m = plugin(MAIL).manifest()
    change(m["connection_types"][0])
    return m


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (_mail(lambda t: t["smtp"].update(host="nope")), "smtp host field 'nope' isn't a required config field"),
        (_mail(lambda t: t["smtp"].update(extra=1)), "an smtp server needs exactly"),
        (_mail(lambda t: t["smtp"].pop("sender")), "an smtp server needs exactly"),
        (_mail(lambda t: t.update(smtp=[])), "an smtp server needs exactly"),
        (_mail(lambda t: t["config_schema"].update(required=["host", "security", "from_address"])),
         "smtp port field 'port' isn't a required config field"),
        (_mail(lambda t: t["config_schema"]["properties"]["security"].update(enum=["starttls", "maybe"])),
         "may only allow 'none', 'starttls', 'tls'"),
        (_mail(lambda t: t["config_schema"]["properties"]["security"].pop("enum")),
         "may only allow 'none', 'starttls', 'tls'"),
        (_mail(lambda t: t["smtp"].update(password=None)), "smtp username and password are named together"),
        (_mail(lambda t: t["smtp"].update(password="from_address")),
         "smtp password field 'from_address' isn't a secret field"),
        (_mail(lambda t: t["smtp"].update(port=7)), "smtp port field 7 isn't a required config field"),
        (_mail(lambda t: t.update(auth={"kind": "header", "header": "X-Key", "template": "{password}"})),
         "an SMTP type has no HTTP host, auth header or stream"),
    ],
)  # fmt: skip
def test_an_smtp_type_is_checked_as_data(manifest: dict[str, Any], problem: str) -> None:
    problems = validate_plugin_manifest(copy.deepcopy(manifest))
    assert any(problem in p for p in problems), problems


@pytest.mark.parametrize(
    "address",
    ["ops@example.com", "first.last+tag@mail.example.co.uk", "o'brien@example.com", "a_b-c@ex-ample.com",
     "x@" + "d" * 63 + ".com"],
)  # fmt: skip
def test_a_mail_address_is_ascii_dot_atom_at_a_domain(address: str) -> None:
    assert MAIL_ADDRESS.fullmatch(address)


@pytest.mark.parametrize(
    "address",
    ["ops@example", "ops @example.com", '"q"@example.com', "ops@example.com\n", "<ops@example.com>", "ops@-ex.com",
     "ops@ex-.com", ".ops@example.com", "ops.@example.com", "o..ps@example.com", "ops@exa_mple.com", "opé@example.com",
     "ops@example.com,b@example.com", "ops@[127.0.0.1]", "l" * 65 + "@example.com", "x@" + "d" * 64 + ".com",
     "x@" + ".".join(["d" * 63] * 4) + ".com", ""],
)  # fmt: skip
def test_any_other_address_is_refused(address: str) -> None:
    assert not MAIL_ADDRESS.fullmatch(address)


def test_a_refusal_names_its_stage_and_code() -> None:
    refused = MailRefused("rcpt", 550)
    assert (refused.stage, refused.reply, refused.permanent) == ("rcpt", 550, True)
    assert refused.code == "mail_refused"  # the class's fixed code, as every transport failure's
    assert MailRefused("end", 451).permanent is False and "451" in str(MailRefused("end", 451))
    assert issubclass(TlsUnavailable, Exception) and issubclass(AuthUnavailable, Exception)
