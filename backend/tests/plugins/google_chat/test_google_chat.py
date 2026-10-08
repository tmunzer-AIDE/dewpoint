# SPDX-License-Identifier: Apache-2.0
"""Google Chat (plugins-3 3c-1, D18): a connection type whose secret is a space's incoming-webhook URL (Google's
documented form only), a quota scope a space (the URL's `spaces/{space}`, 1 a second), and
`google_chat.send_message`, which posts the message as text in Chat's own syntax: run data's `<` and `>` become their
full-width forms, so it never makes a link nor mentions anyone (`<users/all>`); within 30,000 bytes as sent (Google
documents 32,000), cutting and marking what doesn't fit; a 200 is sent, a 4xx Google's refusal, anything else
unknown."""

from typing import Any

import httpx
import pytest

from dewpoint.core.connections.declared import DeclaredType, InvalidValueError
from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.google_chat import BUDGET, CHAT, PLUGIN, SendMessage, render
from dewpoint.sdk import FatalError, OutcomeUnknownError, SideEffect
from dewpoint.sdk.messages import Message
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, FakeStep, Reply

URL = "https://chat.googleapis.com/v1/spaces/AAAAbCd-12_x/messages?key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=a1B2c3D4%3D"


def sent_size(body: Any) -> int:
    return len(httpx.Request("POST", "https://example.com", json=body).content)


def message(**changes: Any) -> Message:
    return Message.model_validate({"text": "Disk full on db-1", **changes})


def declared() -> DeclaredType:
    return DeclaredType.from_manifest("google_chat", PLUGIN.manifest()["connection_types"][0])


def test_a_spaces_webhook_url_is_taken() -> None:
    assert declared().secret({"webhook_url": URL}) == {"webhook_url": URL}


@pytest.mark.parametrize(
    "url",
    [
        URL.replace("https://", "http://"),
        URL.replace("chat.googleapis.com", "chat.googleapis.com.evil.example.com"),
        URL.replace("chat.googleapis.com", "evil.example.com@chat.googleapis.com"),
        URL.replace("chat.googleapis.com", "chat.googleapis.com:443"),
        URL.replace("/v1/", "/v2/"),
        URL.replace("/messages?", "/messages/x?"),
        URL.replace("spaces/AAAAbCd-12_x", "spaces/AAAA/x"),
        URL + "&threadKey=t1",  # a query of the node's: the type declares none (task 2)
        URL + "\n",
        URL + "#frag",
        URL.replace("&token=", "&other="),
        "https://chat.googleapis.com/v1/spaces/AAAA/messages?token=a&key=b",  # the documented order only
    ],
)
def test_any_other_url_is_refused(url: str) -> None:
    with pytest.raises(InvalidValueError):
        declared().secret({"webhook_url": url})


def test_the_quota_scope_is_the_space_one_a_second() -> None:
    [scope] = CHAT.rate_scopes
    assert (scope.kind, scope.secret, scope.capacity, scope.refill_per_s) == (
        "google_chat.space",
        "webhook_url",
        1,
        1.0,
    )
    same = URL.replace("token=a1B2c3D4%3D", "token=zzz")
    other = URL.replace("AAAAbCd-12_x", "BBBB")
    keys = [declared().scopes({}, {"webhook_url": u}, lambda v: f"mac({v})")[0].key for u in (URL, same, other)]
    assert keys == ["google_chat.space:mac(AAAAbCd-12_x)"] * 2 + ["google_chat.space:mac(BBBB)"]


def test_the_plugin_validates_and_its_node_is_an_ambiguous_send() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert SendMessage.side_effect == SideEffect.AMBIGUOUS and SendMessage.credentials == ("google_chat",)


def test_the_body_is_chat_syntax_text() -> None:
    body, cut = render(message(title="db-1", fields=[{"label": "Free", "value": "2%"}],
                               links=[{"label": "Runbook", "url": "https://wiki.example.com/disk"}],
                               severity="warning"))  # fmt: skip
    assert body == {"text": "*db-1*\nDisk full on db-1\n\n*Free*: 2%\n\n<https://wiki.example.com/disk|Runbook>\n\n"
                            "Severity: warning"}  # fmt: skip
    assert cut == []
    assert render(message())[0] == {"text": "Disk full on db-1\n\nSeverity: info"}


@pytest.mark.parametrize("raw", ["<users/all>", "<https://evil.example.com|Reset your password>", "a <b> c"])
def test_run_data_never_links_nor_mentions(raw: str) -> None:
    body, _ = render(message(title=raw, text=raw, fields=[{"label": raw, "value": raw}],
                             links=[{"label": raw, "url": "https://wiki.example.com/x"}]))  # fmt: skip
    neutral = raw.replace("<", "＜").replace(">", "＞")
    text = body["text"]
    assert text.count(neutral) == 5 and text.count("<") == text.count(">") == 1  # the link button's own
    assert "<https://wiki.example.com/x|" + neutral + ">" in text


def test_a_links_url_never_ends_its_link_early() -> None:
    body, _ = render(message(links=[{"label": "Runbook", "url": "https://wiki.example.com/a|b"}]))
    assert "<https://wiki.example.com/a%7Cb|Runbook>" in body["text"]


@pytest.mark.parametrize("fill", ["é", "\x01", '"', "<", "\U0001f600"])
def test_the_largest_message_fits_its_budget_cut_and_marked(fill: str) -> None:
    big = message(title=fill * 1000, text=fill * 40_000, fields=[{"label": fill * 200, "value": fill * 10_000}] * 25,
                  links=[{"label": fill * 200, "url": "https://a.example.com/" + "p" * 1900}] * 10)  # fmt: skip
    body, cut = render(big)
    assert sent_size(body) <= BUDGET <= 32_000
    assert "text" in cut and "fields[0].value" in cut
    dropped = [name for name in cut if name.startswith("links[") and name.endswith("]")]
    assert body["text"].count("<https://a.example.com/") + len(dropped) == 10


@pytest.mark.parametrize(
    "changes",
    [
        {"text": "x" * 5000, "fields": [{"label": "a", "value": "b" * 500}] * 5},
        {"text": "x" * 28_000},
        {"text": "é" * 14_000},
        {"text": "x", "fields": [{"label": "a", "value": "b" * 9000}] * 3},
    ],
)
def test_a_message_within_the_budget_isnt_cut(changes: dict[str, Any]) -> None:
    body, cut = render(message(**changes))
    assert cut == [] and sent_size(body) <= BUDGET


def test_a_message_large_in_its_fields_alone_is_cut_to_fit() -> None:
    body, cut = render(message(text="short", fields=[{"label": "l", "value": "v" * 10_000}] * 25))
    assert sent_size(body) <= BUDGET and "fields[0].value" in cut and "text" not in cut


async def run(reply: Reply) -> tuple[Any, FakeHttp]:
    http = FakeHttp(lambda sent: reply)
    connection = FakeConnection(http, config={})
    value = SendMessage.Config.model_validate({"connection": str(connection.id), "text": "hello"})
    out = await SendMessage().run(FakeStep(connection), value)  # type: ignore[arg-type]
    return out.model_dump(mode="json"), http


async def test_a_200_is_sent() -> None:
    out, http = await run(Reply(200, {"name": "spaces/AAAA/messages/m1", "thread": {"name": "spaces/AAAA/threads/t"}}))
    assert out == {"sent": True, "truncated": []}
    [sent] = http.sent
    assert (sent.method, sent.url, sent.params, sent.headers, sent.json) == (
        "POST",
        "",
        None,
        None,
        {"text": "hello\n\nSeverity: info"},
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 413])
async def test_a_4xx_is_googles_refusal(status: int) -> None:
    with pytest.raises(FatalError) as raised:
        await run(Reply(status, {"error": {"code": status, "message": "secret-looking detail", "status": "X"}}))
    assert raised.value.code == "google_chat.refused" and "secret-looking" not in str(raised.value)
    assert not isinstance(raised.value, OutcomeUnknownError)


@pytest.mark.parametrize("status", [201, 202, 204, 302, 429, 500, 503])
async def test_anything_else_after_sending_is_unknown(status: int) -> None:
    with pytest.raises(OutcomeUnknownError) as raised:
        await run(Reply(status))
    assert raised.value.code == "google_chat.outcome_unknown"


async def test_simulating_renders_and_sends_nothing() -> None:
    http = FakeHttp(lambda sent: Reply(200))
    connection = FakeConnection(http, config={})
    step = FakeStep(connection)
    value = SendMessage.Config.model_validate({"connection": str(connection.id), "text": "y" * 40_000})
    out = (await SendMessage().simulate(step, value)).model_dump(mode="json")  # type: ignore[arg-type]
    assert out == {"sent": True, "truncated": ["text"]} and http.sent == [] and step.opened == []
