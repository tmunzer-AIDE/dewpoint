# SPDX-License-Identifier: Apache-2.0
"""Microsoft Teams (plugins-3 3c-1, D18): a connection type whose secret is a Workflows webhook URL (the public cloud's
hosts only), a quota scope a URL, and `teams.send_message`, which posts the message as an Adaptive Card 1.2 in the
documented `{"type": "message", "attachments": [...]}` body, its run data in text runs (which render no markdown),
within 24,000 bytes as sent (Teams documents about 28 KB), cutting and marking what doesn't fit; a 2xx is the flow's
acceptance, anything else unknown."""

from fractions import Fraction
from typing import Any

import httpx
import pytest

from dewpoint.core.connections.declared import DeclaredType, InvalidValueError
from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.teams import BUDGET, PLUGIN, TEAMS, SendMessage, render
from dewpoint.sdk import OutcomeUnknownError, SideEffect
from dewpoint.sdk.messages import Message
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, FakeStep, Reply

LOGIC = ("https://prod-00.westus.logic.azure.com:443/workflows/0a1b2c/triggers/manual/paths/invoke"
         "?api-version=2016-06-01&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=AbCdEf123")  # fmt: skip
PLATFORM = ("https://default0a1b2c.3d.environment.api.powerplatform.com:443/powerautomate/automations/direct"
            "/workflows/0a1b2c/triggers/manual/paths/invoke"
            "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sig=xyz")  # fmt: skip


def sent_size(body: Any) -> int:
    """The bytes httpx sends for the body: the size the budget bounds."""
    return len(httpx.Request("POST", "https://example.com", json=body).content)


def message(**changes: Any) -> Message:
    return Message.model_validate({"text": "Disk full on db-1", **changes})


def declared() -> DeclaredType:
    return DeclaredType.from_manifest("teams", PLUGIN.manifest()["connection_types"][0])


@pytest.mark.parametrize("url", [LOGIC, PLATFORM, LOGIC.replace(":443", "")])
def test_a_workflows_url_of_the_public_cloud_is_taken(url: str) -> None:
    assert declared().secret({"webhook_url": url}) == {"webhook_url": url}


@pytest.mark.parametrize(
    "url",
    [
        LOGIC.replace("https://", "http://"),
        LOGIC.replace("logic.azure.com", "logic.azure.us"),  # a sovereign cloud: not yet
        "https://prod-00.westus.logic.azure.com.evil.example.com/workflows/x?sig=y",
        "https://prod-00.westus.logic.azure.com@evil.example.com/workflows/x?sig=y",
        "https://evil.example.com@prod-00.westus.logic.azure.com/workflows/x?sig=y",
        "https://evil.example.com/prod-00.westus.logic.azure.com/workflows/x?sig=y",
        "https://PROD-00.westus.logic.azure.com/workflows/x?sig=y",
        LOGIC.replace(":443", ":8443"),
        LOGIC + "\n",
        LOGIC + "#frag",
        "https://xxxxx.webhook.office.com/webhookb2/x",  # an O365 connector's: retired
    ],
)
def test_any_other_url_is_refused(url: str) -> None:
    with pytest.raises(InvalidValueError):
        declared().secret({"webhook_url": url})


def test_the_plugin_validates_and_its_node_is_an_ambiguous_send() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert SendMessage.side_effect == SideEffect.AMBIGUOUS and SendMessage.credentials == ("teams",)
    [scope] = TEAMS.rate_scopes
    assert (scope.kind, scope.secret, scope.capacity) == ("teams.tenant", None, 5)


def most_taken(capacity: float, refill_per_s: float, window_s: int) -> int:
    """The most requests a greedy caller gets from a full bucket within a closed window, by the buckets' rule
    (`core.ratelimit.buckets`: `min(capacity, tokens + elapsed * refill)`, one token a request), counted exactly."""
    refill = Fraction(refill_per_s).limit_denominator(10**6)
    taken, now, tokens = 0, Fraction(0), Fraction(capacity)
    while True:
        while tokens >= 1:
            tokens, taken = tokens - 1, taken + 1
        now += (1 - tokens) / refill  # when the next whole token is there
        if now > window_s:
            return taken
        tokens = Fraction(1)


def test_the_scope_never_grants_more_than_25_posts_in_300_seconds() -> None:
    """Teams' 25 flow-bot posts per 300 s, the burst included: a bucket of 5 refilled at 25 per 300 s grants 30 (a
    review of 1e71079, R2)."""
    [scope] = TEAMS.rate_scopes
    assert most_taken(scope.capacity, scope.refill_per_s, 300) <= 25
    assert most_taken(5, 25 / 300, 300) == 30 and most_taken(5, 20 / 300, 300) == 25  # the count itself


@pytest.mark.parametrize("other", [PLATFORM, LOGIC.replace(":443", ""), LOGIC.replace("0a1b2c", "9z8y7x")])
def test_every_flow_of_a_tenant_shares_one_scope(other: str) -> None:
    """The limit is a Teams connection's, which no URL names: flows sharing one would each get a budget if keyed by
    URL, as would one flow's URL spelt two ways (the 3c-1 review, finding 3)."""
    keys = [declared().scopes({}, {"webhook_url": url}, lambda v: f"mac({v})")[0].key for url in (LOGIC, other)]
    assert keys == ["teams.tenant", "teams.tenant"]


def test_the_body_is_an_adaptive_card_message() -> None:
    body, cut = render(message(title="db-1", fields=[{"label": "Free", "value": "2%"}],
                               links=[{"label": "Runbook", "url": "https://wiki.example.com/disk"}],
                               severity="warning"))  # fmt: skip
    assert body["type"] == "message" and len(body["attachments"]) == 1
    [attachment] = body["attachments"]
    assert attachment["contentType"] == "application/vnd.microsoft.card.adaptive" and attachment["contentUrl"] is None
    card = attachment["content"]
    assert (card["type"], card["version"]) == ("AdaptiveCard", "1.2")
    assert card["body"] == [
        {"type": "RichTextBlock", "inlines": [{"type": "TextRun", "text": "db-1", "weight": "bolder",
                                               "size": "medium"}]},
        {"type": "RichTextBlock", "inlines": [{"type": "TextRun", "text": "Disk full on db-1"}]},
        {"type": "RichTextBlock", "inlines": [{"type": "TextRun", "text": "Free", "weight": "bolder"},
                                              {"type": "TextRun", "text": ": "}, {"type": "TextRun", "text": "2%"}]},
        {"type": "RichTextBlock", "inlines": [{"type": "TextRun", "text": "Severity: warning", "isSubtle": True,
                                               "size": "small"}]},
    ]  # fmt: skip
    assert card["actions"] == [{"type": "Action.OpenUrl", "title": "Runbook", "url": "https://wiki.example.com/disk"}]
    assert cut == []


@pytest.mark.parametrize("fill", ["é", "\x01", '"', "\U0001f600"])  # 2 bytes, 6 escaped, 2 escaped, 4 bytes
def test_the_largest_message_fits_its_budget_cut_and_marked(fill: str) -> None:
    big = message(title=fill * 1000, text=fill * 40_000, fields=[{"label": fill * 200, "value": fill * 10_000}] * 25,
                  links=[{"label": fill * 200, "url": "https://a.example.com/" + "p" * 1900}] * 10)  # fmt: skip
    body, cut = render(big)
    assert sent_size(body) <= BUDGET <= 28_000
    assert "text" in cut and "fields[0].value" in cut
    card = body["attachments"][0]["content"]
    assert card["body"][1]["inlines"][0]["text"].endswith("…")
    dropped = [name for name in cut if name.startswith("links[") and name.endswith("]")]
    assert len(card.get("actions", [])) + len(dropped) == 10  # every link is sent or reported dropped


def elements(value: Any) -> list[dict[str, Any]]:
    """Every object in the card, depth first."""
    if isinstance(value, list):
        return [found for item in value for found in elements(item)]
    if isinstance(value, dict):
        return [value, *(found for item in value.values() for found in elements(item))]
    return []


def test_run_data_is_never_markdown() -> None:
    """A TextBlock's and a fact's text render markdown (a `[label](url)` is a link: learn.microsoft.com
    `cards-format`); a TextRun's doesn't ("Markdown is not supported", the card schema)."""
    link = "[Reset your password](https://evil.example.com)"
    body, _ = render(message(title=link, text=link, fields=[{"label": link, "value": link}]))
    card = body["attachments"][0]["content"]
    assert {e["type"] for e in elements(card["body"])} == {"RichTextBlock", "TextRun"}
    assert [e["text"] for e in elements(card["body"]) if e["type"] == "TextRun" and link in e["text"]] == [link] * 4


def test_a_message_large_in_its_fields_alone_is_cut_to_fit() -> None:
    body, cut = render(message(text="short", fields=[{"label": "l", "value": "v" * 10_000}] * 25))
    assert sent_size(body) <= BUDGET and "fields[0].value" in cut and "text" not in cut


@pytest.mark.parametrize(
    "changes",
    [
        {"text": "x" * 5000, "fields": [{"label": "a", "value": "b" * 500}] * 5},
        {"text": "x" * 22_000},  # most of the budget in one value
        {"text": "é" * 10_000},  # 20,000 bytes sent, 60,000 if escaped
        {"text": "x", "fields": [{"label": "a", "value": "b" * 9000}] * 2},
    ],
)
def test_a_message_within_the_budget_isnt_cut(changes: dict[str, Any]) -> None:
    body, cut = render(message(**changes))
    assert cut == [] and sent_size(body) <= BUDGET


async def run(reply: Reply | BaseException) -> tuple[Any, FakeHttp]:
    http = FakeHttp(lambda sent: reply)
    connection = FakeConnection(http, config={})
    value = SendMessage.Config.model_validate({"connection": str(connection.id), "text": "hello"})
    out = await SendMessage().run(FakeStep(connection), value)  # type: ignore[arg-type]
    return out.model_dump(mode="json"), http


@pytest.mark.parametrize("status", [200, 202])
async def test_a_2xx_is_the_flows_acceptance_never_delivery(status: int) -> None:
    out, http = await run(Reply(status))
    assert out == {"accepted": True, "truncated": []}
    [sent] = http.sent
    assert (sent.method, sent.url, sent.params, sent.headers) == ("POST", "", None, None)  # no auth header: "Anyone"


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 429, 500, 503])
async def test_anything_else_after_sending_is_unknown(status: int) -> None:
    with pytest.raises(OutcomeUnknownError) as raised:
        await run(Reply(status))
    assert raised.value.code == "teams.outcome_unknown"


async def test_simulating_renders_and_sends_nothing() -> None:
    http = FakeHttp(lambda sent: Reply(202))
    connection = FakeConnection(http, config={})
    step = FakeStep(connection)
    value = SendMessage.Config.model_validate({"connection": str(connection.id), "text": "y" * 40_000})
    out = (await SendMessage().simulate(step, value)).model_dump(mode="json")  # type: ignore[arg-type]
    assert out == {"accepted": True, "truncated": ["text"]} and http.sent == [] and step.opened == []
