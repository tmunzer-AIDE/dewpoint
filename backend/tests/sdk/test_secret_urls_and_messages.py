# SPDX-License-Identifier: Apache-2.0
"""SDK 0.6.0 (plugins-3 3c-1): a connection type whose base URL is a secret field (`SecretUrl`: an incoming webhook's
URL is the credential, D4's `url` auth), a rate scope keyed by a part of a secret field (`secret_pattern`: a Google
Chat space, D9), and the message model the chat targets render (D18). Each new declaration is data, checked by the SDK
and by the catalog alike."""

import copy
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.sdk import (
    SDK_VERSION,
    ConnectionType,
    ManifestError,
    Plugin,
    RateScope,
    SecretUrl,
)
from dewpoint.sdk.messages import Message, Severity, cut

# matched whole (`re.fullmatch`) where the secret is read: a final newline can't pass as it would with `$`
URL = r"https://chat\.example\.com/v1/spaces/[A-Za-z0-9_-]{1,64}/messages\?key=[A-Za-z0-9_-]{1,128}&token=[A-Za-z0-9_-]{1,256}"


class NoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HookSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    webhook_url: SecretStr = Field(max_length=2048)


class OptionalSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    webhook_url: SecretStr = Field(SecretStr("https://chat.example.com/x"))


SPACE = RateScope("demo.space", secret="webhook_url", secret_pattern=r"/spaces/([A-Za-z0-9_-]+)/", capacity=1,
                  refill_per_s=1)  # fmt: skip
HOOK = ConnectionType("demo", "Demo chat", NoConfig, HookSecret, host=SecretUrl("webhook_url", URL),
                      rate_scopes=(SPACE,))  # fmt: skip


def test_the_sdk_is_0_6_0() -> None:
    assert SDK_VERSION == "0.6.0"


def test_a_secret_url_type_is_data() -> None:
    m = HOOK.manifest()
    assert m["host"] == {"kind": "secret_url", "field": "webhook_url", "pattern": URL}
    assert m["auth"] is None
    assert m["rate_scopes"] == [{"kind": "demo.space", "config": [], "secret": "webhook_url", "capacity": 1.0,
                                 "refill_per_s": 1.0, "secret_pattern": r"/spaces/([A-Za-z0-9_-]+)/"}]  # fmt: skip
    assert validate_plugin_manifest(Plugin("demo", "1.0.0", (), connection_types=(HOOK,)).manifest()) == []


def test_a_scope_without_a_secret_pattern_keeps_its_manifest() -> None:
    plain = RateScope("demo.tenant", capacity=3, refill_per_s=1)
    kind = ConnectionType("demo", "D", NoConfig, HookSecret, host=SecretUrl("webhook_url", URL), rate_scopes=(plain,))
    assert "secret_pattern" not in kind.manifest()["rate_scopes"][0]


@pytest.mark.parametrize(
    ("kind", "problem"),
    [
        (ConnectionType("demo", "D", NoConfig, HookSecret, host=SecretUrl("nope", URL)),
         "host field 'nope' isn't a secret field"),
        (ConnectionType("demo", "D", NoConfig, HookSecret, host=SecretUrl("webhook_url", r"http://.*")),
         "secret URL pattern must start with https://"),
        (ConnectionType("demo", "D", NoConfig, HookSecret, host=SecretUrl("webhook_url", r"https://(unclosed")),
         "secret URL pattern doesn't compile"),
        (ConnectionType("demo", "D", NoConfig, OptionalSecret, host=SecretUrl("webhook_url", URL)),
         "host field 'webhook_url' must be required"),
        (ConnectionType("demo", "D", NoConfig, HookSecret, host=SecretUrl("webhook_url", URL),
                        rate_scopes=(RateScope("demo.x", secret_pattern=r"/spaces/([^/]+)/"),)),
         "rate scope 'demo.x': a secret pattern needs its secret field"),
        (ConnectionType("demo", "D", NoConfig, HookSecret, host=SecretUrl("webhook_url", URL),
                        rate_scopes=(RateScope("demo.x", secret="webhook_url", secret_pattern=r"/spaces/[^/]+/"),)),
         "rate scope 'demo.x': a secret pattern needs exactly one group"),
        (ConnectionType("demo", "D", NoConfig, HookSecret, host=SecretUrl("webhook_url", URL),
                        rate_scopes=(RateScope("demo.x", secret="webhook_url", secret_pattern=r"(unclosed"),)),
         "rate scope 'demo.x': a secret pattern needs exactly one group"),
    ],
)  # fmt: skip
def test_a_secret_url_type_is_checked(kind: ConnectionType, problem: str) -> None:
    with pytest.raises(ManifestError) as raised:
        Plugin("demo", "1.0.0", (), connection_types=(kind,)).manifest()
    assert any(problem in p for p in raised.value.problems), raised.value.problems


def _hook(change: Any) -> dict[str, Any]:
    m = Plugin("demo", "1.0.0", (), connection_types=(HOOK,)).manifest()
    change(m["connection_types"][0])
    return m


@pytest.mark.parametrize(
    ("manifest", "problem"),
    [
        (_hook(lambda t: t["host"].update(field="nope")), "host field 'nope' isn't a secret field"),
        (_hook(lambda t: t["host"].update(extra=1)), "a secret URL host must be"),
        (_hook(lambda t: t["host"].pop("pattern")), "a secret URL host must be"),
        (_hook(lambda t: t["host"].update(pattern="http://x")), "secret URL pattern must start with https://"),
        (_hook(lambda t: t["host"].update(pattern="https://(x")), "secret URL pattern doesn't compile"),
        (_hook(lambda t: t["host"].update(pattern=5)), "secret URL pattern must start with https://"),
        (_hook(lambda t: t["secret_schema"].update(required=[])), "host field 'webhook_url' must be required"),
        (_hook(lambda t: t["rate_scopes"][0].update(secret_pattern="/spaces/[^/]+/")),
         "a secret pattern needs exactly one group"),
        (_hook(lambda t: t["rate_scopes"][0].update(secret=None)), "a secret pattern needs its secret field"),
        (_hook(lambda t: t["rate_scopes"][0].update(secret_pattern=5)), "a secret pattern needs exactly one group"),
    ],
)  # fmt: skip
def test_a_secret_url_type_is_checked_as_data(manifest: dict[str, Any], problem: str) -> None:
    problems = validate_plugin_manifest(copy.deepcopy(manifest))
    assert any(problem in p for p in problems), problems


def test_a_message_is_text_with_optional_title_fields_links_and_severity() -> None:
    m = Message.model_validate({"text": "Disk full", "title": "db-1", "fields": [{"label": "Free", "value": "2%"}],
                                "links": [{"label": "Runbook", "url": "https://wiki.example.com/disk"}],
                                "severity": "critical"})  # fmt: skip
    assert (m.severity, m.fields[0].value, m.links[0].url) == (Severity.CRITICAL, "2%", "https://wiki.example.com/disk")
    assert Message.model_validate({"text": "x"}).severity == Severity.INFO


@pytest.mark.parametrize(
    "raw",
    [
        {},  # text is required
        {"text": ""},
        {"text": "x", "links": [{"label": "x", "url": "javascript:alert(1)"}]},
        {"text": "x", "links": [{"label": "x", "url": "https://ok.example.com/\n"}]},
        {"text": "x", "links": [{"label": "x", "url": "ftp://files.example.com/x"}]},
        {"text": "x", "fields": [{"label": "", "value": "v"}]},
        {"text": "x", "severity": "fatal"},
        {"text": "x", "extra": 1},
        {"text": "x", "fields": [{"label": "l", "value": "v"}] * 26},
        {"text": "x", "links": [{"label": "l", "url": "https://a.example.com"}] * 11},
    ],
)
def test_a_message_is_checked(raw: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Message.model_validate(raw)


@pytest.mark.parametrize(
    ("text", "limit", "unit", "expected"),
    [
        ("short", 10, "chars", ("short", False)),
        ("abcdefghij", 10, "chars", ("abcdefghij", False)),
        ("abcdefghijk", 10, "chars", ("abcdefghi…", True)),
        ("ééééé", 6, "bytes", ("é…", True)),  # 2 bytes each; the marker is 3
        ("abc", 3, "bytes", ("abc", False)),
    ],
)
def test_a_value_past_its_limit_is_cut_and_marked(text: str, limit: int, unit: str, expected: tuple[str, bool]) -> None:
    found = cut(text, limit, unit=unit)  # type: ignore[arg-type]
    assert found == expected
    assert (len(found[0]) if unit == "chars" else len(found[0].encode())) <= limit
