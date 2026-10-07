# SPDX-License-Identifier: Apache-2.0
"""Slack (plugins-3 3c-1, D18): a connection type whose secret is an incoming webhook's URL (its documented form only),
one quota scope a tenant, and `slack.send_message`, which renders the message model as Block Kit within Slack's
limits, escaping every value so run data never mentions `@here` or a channel nor makes a link, cutting and marking a
value past a limit; 200 is sent, a 4xx Slack's refusal, anything else after sending unknown."""

import json
from typing import Any

import pytest

from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.slack import PLUGIN, SLACK, SendMessage, render
from dewpoint.sdk import FatalError, OutcomeUnknownError, SideEffect, node_manifest
from dewpoint.sdk.messages import Message
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, FakeStep, Reply

# The docs' example URL, in parts: written whole, a URL in Slack's form trips secret scanners (push protection).
PARTS = "T00000000/B00000000/" + "X" * 24
HOOK = "https://hooks.slack.com/services/" + PARTS


def message(**changes: Any) -> Message:
    return Message.model_validate({"text": "Disk full on db-1", **changes})


def test_the_connection_type_takes_the_documented_url_only() -> None:
    kind = PLUGIN.manifest()["connection_types"][0]
    assert kind["host"]["kind"] == "secret_url" and kind["auth"] is None
    from dewpoint.core.connections.declared import DeclaredType, InvalidValueError  # noqa: PLC0415

    declared = DeclaredType.from_manifest("slack", kind)
    assert declared.secret({"webhook_url": HOOK}) == {"webhook_url": HOOK}
    for bad in (
        "https://hooks.slack-gov.com/services/" + PARTS,  # GovSlack: undocumented
        "https://hooks.slack.com/" + PARTS,  # no /services/
        "http://hooks.slack.com/services/" + PARTS,
        HOOK + "\n", HOOK + "?x=1", HOOK + "/more",
        "https://evil.example.com/services/" + PARTS,
    ):  # fmt: skip
        with pytest.raises(InvalidValueError):
            declared.secret({"webhook_url": bad})


def test_the_plugin_validates_and_its_node_is_an_ambiguous_send() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert SendMessage.side_effect == SideEffect.AMBIGUOUS and SendMessage.credentials == ("slack",)
    assert [s.kind for s in SLACK.rate_scopes] == ["slack.tenant"]  # one a tenant (D9: the URL names no channel)
    schema = node_manifest(SendMessage)["config_schema"]
    assert {"connection", "text", "title", "fields", "links", "severity"} <= set(schema["properties"])


def test_every_value_is_escaped_in_verbatim_mrkdwn() -> None:
    payload, cut = render(message(title="<!here> & <#C123>", text="ping <!channel> at <https://x.example.com|here>",
                                  fields=[{"label": "<@U1>", "value": "a > b"}]))  # fmt: skip
    texts = [b["text"] for b in payload["blocks"] if "text" in b] + [
        f for b in payload["blocks"] for f in b.get("fields", [])
    ]
    assert texts and all(t["type"] == "mrkdwn" and t["verbatim"] is True for t in texts)
    flat = json.dumps(payload)
    for raw in ("<!here>", "<!channel>", "<#C123>", "<@U1>", "<https://"):
        assert raw not in flat
    assert "&lt;!here&gt; &amp; &lt;#C123&gt;" in flat and "a &gt; b" in flat
    assert "&lt;!channel&gt;" in payload["text"]  # the notification's fallback text too
    assert cut == []


def test_the_title_is_a_bold_line_never_a_header_block() -> None:
    payload, _ = render(message(title="db-1"))
    assert all(b["type"] != "header" for b in payload["blocks"])
    assert payload["blocks"][0]["text"]["text"] == "*db-1*"


def test_links_are_buttons_and_severity_a_context_line() -> None:
    payload, _ = render(message(links=[{"label": "Runbook", "url": "https://wiki.example.com/disk"}],
                                severity="critical"))  # fmt: skip
    [actions] = [b for b in payload["blocks"] if b["type"] == "actions"]
    [button] = actions["elements"]
    assert button["type"] == "button" and button["text"] == {"type": "plain_text", "text": "Runbook", "emoji": False}
    assert button["url"] == "https://wiki.example.com/disk" and len(button["action_id"]) <= 255
    [context] = [b for b in payload["blocks"] if b["type"] == "context"]
    assert context["elements"][0]["text"] == "Severity: critical"


def test_every_limit_is_cut_and_marked() -> None:
    long = "x" * 3500
    payload, cut = render(message(title="t" * 1000, text=long, fields=[{"label": "l" * 200, "value": "v" * 2100}] * 12,
                                  links=[{"label": "b" * 90, "url": "https://a.example.com"}]))  # fmt: skip
    sections = [b for b in payload["blocks"] if b["type"] == "section"]
    assert all(len(b["text"]["text"]) <= 3000 for b in sections if "text" in b)
    fields = [f for b in sections for f in b.get("fields", [])]
    assert len(fields) == 12 and all(len(f["text"]) <= 2000 for f in fields)
    assert all(len(b.get("fields", [])) <= 10 for b in sections)
    [actions] = [b for b in payload["blocks"] if b["type"] == "actions"]
    assert len(actions["elements"][0]["text"]["text"]) <= 75
    assert len(payload["blocks"]) <= 50 and len(payload["text"]) <= 3000
    assert {"text", "fields[0].value", "links[0].label"} <= set(cut) and "title" not in cut  # the model bounds it
    assert any(t["text"]["text"].endswith("…") for t in sections if "text" in t)


def test_an_escape_is_never_cut_in_half() -> None:
    payload, cut = render(message(text="<" * 2000))  # 4 characters each once escaped
    body = payload["blocks"][0]["text"]["text"]
    assert len(body) <= 3000 and body.endswith("&lt;…") and cut == ["text"]


async def run(reply: Reply | BaseException, **config: Any) -> tuple[Any, FakeHttp]:
    http = FakeHttp(lambda sent: reply)
    connection = FakeConnection(http, config={})
    value = SendMessage.Config.model_validate({"connection": str(connection.id), "text": "hello", **config})
    out = await SendMessage().run(FakeStep(connection), value)  # type: ignore[arg-type]
    return out.model_dump(mode="json"), http


async def test_a_200_is_sent_to_the_connections_url_alone() -> None:
    out, http = await run(Reply(200, raw=b"ok"))
    assert out == {"sent": True, "truncated": []}
    [sent] = http.sent
    assert (sent.method, sent.url, sent.params, sent.headers) == ("POST", "", None, None)
    assert sent.json["text"] == "hello" and sent.json["blocks"]


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, "slack.invalid_payload"), (403, "slack.action_prohibited"), (404, "slack.channel_not_found"),
     (410, "slack.channel_is_archived"), (401, "slack.refused")],
)  # fmt: skip
async def test_a_4xx_is_slacks_refusal(status: int, code: str) -> None:
    with pytest.raises(FatalError) as raised:
        await run(Reply(status, raw=b"some_reason"))
    assert raised.value.code == code


@pytest.mark.parametrize("status", [429, 500, 503, 302, 201])
async def test_anything_else_after_sending_is_unknown(status: int) -> None:
    with pytest.raises(OutcomeUnknownError) as raised:
        await run(Reply(status, raw=b"x"))
    assert raised.value.code == "slack.outcome_unknown"


async def test_simulating_renders_and_sends_nothing() -> None:
    http = FakeHttp(lambda sent: Reply(200, raw=b"ok"))
    connection = FakeConnection(http, config={})
    step = FakeStep(connection)
    value = SendMessage.Config.model_validate({"connection": str(connection.id), "text": "y" * 4000})
    out = (await SendMessage().simulate(step, value)).model_dump(mode="json")  # type: ignore[arg-type]
    assert out == {"sent": True, "truncated": ["text"]} and http.sent == [] and step.opened == []


def test_the_rendered_message_is_json() -> None:
    payload, _ = render(message(fields=[{"label": "a", "value": "b"}]))
    assert json.loads(json.dumps(payload)) == payload
