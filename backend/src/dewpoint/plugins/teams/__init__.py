# SPDX-License-Identifier: Apache-2.0
"""Microsoft Teams (plugins-3 3c-1, D18): a message to a channel through a Workflows webhook ("When a Teams webhook
request is received"; Office 365 connectors stopped working in May 2026), whose URL is the credential.

The URL is a Workflows URL of the public cloud: a host under `logic.azure.com` or `api.powerplatform.com`
(learn.microsoft.com `power-automate/ip-address-configuration`), https, on 443; the trigger must accept "Anyone":
no authentication header is sent (`connectors/teams`). One quota scope a tenant, 25 posts in 300 seconds with bursts
of 5: Teams limits a flow-bot's posts per Teams connection, which no URL names, so flows sharing one can't be told
apart (D9's fallback, as Slack's).

The message is an Adaptive Card 1.2 (the documented samples' version) in the documented body, `{"type": "message",
"attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": null, "content": …}]}`, in
rich text blocks of text runs, which render no markdown: the title bold, then the text, each field a bold label and
its value, the severity a subtle line; links are `Action.OpenUrl` buttons. Teams documents about 28 KB a message; the
body is kept within 24,000 bytes as sent, cutting the text, then field values, labels and links, each cut marked and
reported.

A send is ambiguous (D20): the trigger's success status isn't documented, so a 2xx is the flow's acceptance
(`accepted`), never proof of the post; any other answer after sending is unknown (D18)."""

import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.sdk import (
    ConnectionType,
    Node,
    OutcomeUnknownError,
    Plugin,
    RateScope,
    SecretUrl,
    SideEffect,
    StepContext,
    connection_field,
)
from dewpoint.sdk.messages import Message, cut

TEAMS_URL = (
    r"https://[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63}){0,8}\.(logic\.azure\.com|api\.powerplatform\.com)(:443)?"
    r"/[^\s#]{1,4000}"
)
BUDGET = 24_000  # bytes of the body, under Teams' documented ~28 KB
# What each value may keep, tighter at each level until the body fits: title characters, text bytes, field value bytes,
# label characters, links kept. The first is the message model's own bounds: nothing cut.
LEVELS = (
    (1000, 160_000, 40_000, 200, 10),
    (1000, 16_000, 2000, 200, 10),
    (500, 8000, 600, 100, 10),
    (200, 4000, 200, 60, 5),
    (100, 1000, 60, 30, 2),
    (60, 200, 20, 20, 0),
)


class TeamsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TeamsSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    webhook_url: SecretStr = Field(max_length=4096)


TEAMS = ConnectionType(
    key="teams",
    label="Microsoft Teams",
    Config=TeamsConfig,
    Secret=TeamsSecret,
    host=SecretUrl("webhook_url", TEAMS_URL),
    rate_scopes=(RateScope("teams.tenant", capacity=5, refill_per_s=25 / 300),),
)


def _runs(*runs: dict[str, Any]) -> dict[str, Any]:
    """A rich text block of text runs, whose text renders verbatim: a TextRun's "Markdown is not supported" (the card
    schema), while a TextBlock's or a fact's would make a `[label](url)` of run data a link."""
    return {"type": "RichTextBlock", "inlines": [{"type": "TextRun", **run} for run in runs]}


def _card(message: Message, title_max: int, text_max: int, value_max: int, label_max: int, links_kept: int
          ) -> tuple[dict[str, Any], list[str]]:  # fmt: skip
    truncated: list[str] = []

    def kept(name: str, value: tuple[str, bool]) -> str:
        if value[1]:
            truncated.append(name)
        return value[0]

    body: list[dict[str, Any]] = []
    if message.title:
        body.append(_runs({"text": kept("title", cut(message.title, title_max)), "weight": "bolder", "size": "medium"}))
    body.append(_runs({"text": kept("text", cut(message.text, text_max, unit="bytes"))}))
    for i, field in enumerate(message.fields):
        label = kept(f"fields[{i}].label", cut(field.label, label_max))
        value = kept(f"fields[{i}].value", cut(field.value, value_max, unit="bytes"))
        body.append(_runs({"text": label, "weight": "bolder"}, {"text": ": "}, {"text": value}))
    body.append(_runs({"text": f"Severity: {message.severity.value}", "isSubtle": True, "size": "small"}))
    card: dict[str, Any] = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard",
                            "version": "1.2", "body": body}  # fmt: skip
    actions = [{"type": "Action.OpenUrl", "title": kept(f"links[{i}].label", cut(link.label, label_max)),
                "url": link.url} for i, link in enumerate(message.links[:links_kept])]  # fmt: skip
    truncated += [f"links[{i}]" for i in range(links_kept, len(message.links))]
    if actions:
        card["actions"] = actions
    attachment = {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": card}
    return {"type": "message", "attachments": [attachment]}, truncated


def _encoded(body: dict[str, Any]) -> bytes:
    """The body as httpx 0.28 sends it (`httpx._content.encode_json`): compact, UTF-8."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def render(message: Message) -> tuple[dict[str, Any], list[str]]:
    """The message as the Workflows trigger's body, within `BUDGET` bytes, and the names of the values it cut."""
    for level in LEVELS:
        body, truncated = _card(message, *level)
        if len(_encoded(body)) <= BUDGET:
            return body, truncated
    return body, truncated  # the last level always fits: the message model bounds every value


class SendConfig(Message):
    connection: uuid.UUID = connection_field("teams")


class SendOutput(BaseModel):
    accepted: bool
    truncated: list[str]


class SendMessage(Node):
    """Posts a message as an Adaptive Card through a Teams Workflows webhook."""

    type = "teams.send_message"
    version = 1
    title = "Send a Teams message"
    description = (
        "Posts a message as an Adaptive Card through a Teams Workflows webhook. The flow's acceptance is reported, "
        "not the post itself; a send that fails after it may have arrived is never retried."
    )
    Config = SendConfig
    Output = SendOutput
    credentials = ("teams",)
    side_effect = SideEffect.AMBIGUOUS

    async def simulate(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        _, truncated = render(config)
        return SendOutput(accepted=True, truncated=truncated)

    async def run(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        body, truncated = render(config)
        connection = await ctx.connection(config.connection)
        answer = await connection.http.request("POST", "", json=body)
        if 200 <= answer.status_code < 300:
            return SendOutput(accepted=True, truncated=truncated)
        raise OutcomeUnknownError(
            "teams.outcome_unknown", "Teams' answer doesn't say whether the flow accepted the message."
        )


PLUGIN = Plugin(name="teams", version="1.0.0", nodes=(SendMessage,), connection_types=(TEAMS,))
