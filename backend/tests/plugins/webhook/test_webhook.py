# SPDX-License-Identifier: Apache-2.0
"""The generic webhook (plugins-3 3c-1, D18): a connection type whose secret is any https URL (the guard vets its
address at creation and on every connect, D7), a quota scope a host, and two ambiguous sends: `webhook.send_message`
posts the message model as JSON, `webhook.send_json` a body of the workflow's (at most 1 MiB as sent). The answer's
status is the only output: a receiver's body could quote anything."""

from typing import Any

import pydantic
import pytest

from dewpoint.core.connections.declared import DeclaredType, InvalidValueError
from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.webhook import BODY_MAX, PLUGIN, WEBHOOK, SendJson, SendMessage
from dewpoint.sdk import FatalError, OutcomeUnknownError, SideEffect
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, FakeStep, Reply


def declared() -> DeclaredType:
    return DeclaredType.from_manifest("webhook", PLUGIN.manifest()["connection_types"][0])


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.example.com/in/abc?token=x1&b=%20",
        "https://example.com",
        "https://example.com/",
        "https://receiver:8443/events",  # a single label: the guard decides where it resolves
        "https://203.0.113.7/x",
        "https://example.com:65535/a/@b",  # an `@` in the path names no user
        "https://hooks.slack.com.example.com/x",  # another domain's host, however it starts
        "https://chat.googleapis.com.example.com/x",
        "https://api.slack.com/x",
    ],
)
def test_an_https_url_is_taken(url: str) -> None:
    assert declared().secret({"url": url}) == {"url": url}


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/x",  # https only (a secret URL's pattern starts with it)
        "https://user:pass@example.com/x",
        "https://user@example.com/x",
        "https://example.com@evil.example.com/x",
        "https://example.com/x#frag",
        "https://example.com/x\n",
        "https://example.com/a b",
        "https://example.com\\@evil.example.com/",
        "https://Example.com/x",  # lowercase hosts only: one host, one scope
        "https://eXample.com/x",  # else its scope would be keyed by "e"
        "https://example.com:0/x",
        "https://example.com:65536/x",
        "https://example.com?x=1",
        "https://[2001:db8::1]/x",
        "https://example.com./x",
        "https://example.com/<script>",
    ],
)
def test_any_other_url_is_refused(url: str) -> None:
    with pytest.raises(InvalidValueError):
        declared().secret({"url": url})


@pytest.mark.parametrize(
    "url",
    [
        "https://hooks.slack.com/services/T0001/B0002/abcdef",
        "https://hooks.slack.com",
        "https://hooks.slack.com:443/services/x",
        "https://chat.googleapis.com/v1/spaces/AAAA/messages?key=k&token=t",
        "https://prod-00.westus.logic.azure.com:443/workflows/x/triggers/manual/paths/invoke?sig=s",
        "https://logic.azure.com/x",
        "https://default0a.3d.environment.api.powerplatform.com/powerautomate/x",
        "https://xxxxx.webhook.office.com/webhookb2/x",
    ],
)
def test_a_chat_targets_own_url_is_refused(url: str) -> None:
    """Slack's, Google Chat's and Teams' webhooks have their own types, which escape run data and charge the
    provider's scope; through this one a `<!channel>` in run data would reach Slack as it is (the 3c-1 review, 4)."""
    with pytest.raises(InvalidValueError):
        declared().secret({"url": url})


def test_the_quota_scope_is_the_host() -> None:
    [scope] = WEBHOOK.rate_scopes
    assert (scope.kind, scope.secret, scope.capacity, scope.refill_per_s) == ("webhook.host", "url", 5, 1.0)
    urls = ["https://a.example.com/x?t=1", "https://a.example.com:8443/y", "https://b.example.com/x?t=1"]
    keys = [declared().scopes({}, {"url": u}, lambda v: f"mac({v})")[0].key for u in urls]
    assert keys == ["webhook.host:mac(a.example.com)"] * 2 + ["webhook.host:mac(b.example.com)"]


def test_the_plugin_validates_and_its_nodes_are_ambiguous_sends() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    for node in (SendMessage, SendJson):
        assert node.side_effect == SideEffect.AMBIGUOUS and node.credentials == ("webhook",)


async def run(node: Any, config: dict[str, Any], reply: Reply) -> tuple[Any, FakeHttp]:
    http = FakeHttp(lambda sent: reply)
    connection = FakeConnection(http, config={})
    value = node.Config.model_validate({"connection": str(connection.id), **config})
    out = await node().run(FakeStep(connection), value)
    return out.model_dump(mode="json"), http


async def test_the_message_is_sent_as_json() -> None:
    link = {"label": "Runbook", "url": "https://wiki.example.com/disk"}
    config = {"title": "db-1", "text": "Disk full", "fields": [{"label": "Free", "value": "2%"}], "links": [link],
              "severity": "warning"}  # fmt: skip
    out, http = await run(SendMessage, config, Reply(200))
    assert out == {"sent": True, "status": 200}
    [sent] = http.sent
    assert (sent.method, sent.url, sent.params, sent.headers) == ("POST", "", None, None)
    assert sent.json == config


async def test_a_message_without_its_options_is_sent_whole() -> None:
    _, http = await run(SendMessage, {"text": "hi"}, Reply(204))
    assert http.sent[0].json == {"title": None, "text": "hi", "fields": [], "links": [], "severity": "info"}


@pytest.mark.parametrize("body", [{"event": "x", "n": [1, 2.5, None, True]}, [1, "a"], "plain", 7, None])
async def test_a_body_of_the_workflows_is_sent_as_it_is(body: Any) -> None:
    out, http = await run(SendJson, {"body": body}, Reply(202))
    assert out == {"sent": True, "status": 202} and http.sent[0].json == body


def test_a_body_past_its_bound_is_refused_before_sending() -> None:
    with pytest.raises(pydantic.ValidationError):
        SendJson.Config.model_validate({"connection": "00000000-0000-0000-0000-000000000001",
                                        "body": {"x": "é" * (BODY_MAX // 2)}})  # fmt: skip
    SendJson.Config.model_validate({"connection": "00000000-0000-0000-0000-000000000001",
                                    "body": {"x": "e" * (BODY_MAX - 100)}})  # fmt: skip


def test_a_body_must_be_json() -> None:
    with pytest.raises(pydantic.ValidationError):
        SendJson.Config.model_validate({"connection": "00000000-0000-0000-0000-000000000001", "body": float("nan")})


@pytest.mark.parametrize("status", [200, 201, 202, 204, 299])
async def test_a_2xx_is_sent_with_its_status(status: int) -> None:
    out, _ = await run(SendJson, {"body": {}}, Reply(status, {"echo": "secret-looking detail"}))
    assert out == {"sent": True, "status": status}


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 413, 422])
async def test_a_4xx_is_the_receivers_refusal(status: int) -> None:
    with pytest.raises(FatalError) as raised:
        await run(SendJson, {"body": {}}, Reply(status, {"error": "secret-looking detail"}))
    assert raised.value.code == "webhook.refused" and "secret-looking" not in str(raised.value)
    assert not isinstance(raised.value, OutcomeUnknownError)


@pytest.mark.parametrize("status", [100, 301, 302, 307, 429, 500, 502, 503])
async def test_anything_else_after_sending_is_unknown(status: int) -> None:
    with pytest.raises(OutcomeUnknownError) as raised:
        await run(SendMessage, {"text": "hi"}, Reply(status))
    assert raised.value.code == "webhook.outcome_unknown"


@pytest.mark.parametrize(("node", "config"), [(SendMessage, {"text": "hi"}), (SendJson, {"body": {"a": 1}})])
async def test_simulating_sends_nothing_and_names_no_status(node: Any, config: dict[str, Any]) -> None:
    http = FakeHttp(lambda sent: Reply(200))
    connection = FakeConnection(http, config={})
    step = FakeStep(connection)
    value = node.Config.model_validate({"connection": str(connection.id), **config})
    out = (await node().simulate(step, value)).model_dump(mode="json")
    assert out == {"sent": True, "status": None} and http.sent == [] and step.opened == []
