# SPDX-License-Identifier: Apache-2.0
"""Slack (plugins-3 3c-1, D18): a message to a channel through an incoming webhook, whose URL is the credential.

The URL is Slack's documented form only, `https://hooks.slack.com/services/T…/B…/…` (docs.slack.dev
`messaging/sending-messages-using-incoming-webhooks`); the channel, user name and icon are the webhook's. One quota
scope a tenant at 1 a second: Slack documents 1 a second for incoming webhooks and about one message a second a
channel, and a URL that names no documented workspace or channel can't key a narrower one (D9).

The message renders as Block Kit within Slack's documented limits (`reference/block-kit/*`): the title a bold line,
the text a section of at most 3,000 characters, fields in sections of at most 10, each at most 2,000, links as
buttons whose text is at most 75, the severity a context line. Every value is escaped (`&`, `<`, `>`) and sent in
`mrkdwn` objects with `verbatim: true` (`messaging/formatting-message-text`), so run data never mentions `@here` or a
channel nor makes a link labelled other than its own URL (`<url|label>`); a bare URL may still become a link to
itself: Slack converts "Regular URLs" in the top-level `text`, the escaped fallback, unless `parse` is `none`, which
isn't documented for incoming webhooks. A value past a limit is cut, before an escape rather than through one, and
marked.

A send is ambiguous (D20): a 200 with the body `ok` is sent; a 4xx is Slack's refusal (400 `invalid_payload`, 403
`action_prohibited`, 404 `channel_not_found`, 410 `channel_is_archived`); a 429, a 5xx, another 200 or anything else
after sending is unknown (D10)."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dewpoint.sdk import (
    ConnectionType,
    FatalError,
    Node,
    OutcomeUnknownError,
    Plugin,
    RateScope,
    SecretUrl,
    SideEffect,
    StepContext,
    connection_field,
)
from dewpoint.sdk.messages import MARK, Message, cut

SLACK_URL = r"https://hooks\.slack\.com/services/T[A-Z0-9]{1,32}/B[A-Z0-9]{1,32}/[A-Za-z0-9]{1,64}"
SECTION_MAX, FIELD_MAX, FIELDS_A_SECTION, BUTTON_MAX, LABEL_MAX = 3000, 2000, 10, 75, 300
ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
REFUSALS = {
    400: ("slack.invalid_payload", "Slack refused the message as invalid."),
    403: ("slack.action_prohibited", "Slack's workspace prohibits this webhook from posting."),
    404: ("slack.channel_not_found", "Slack found no channel for this webhook."),
    410: ("slack.channel_is_archived", "The webhook's channel is archived."),
}


class SlackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SlackSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    webhook_url: SecretStr = Field(max_length=2048)


SLACK = ConnectionType(
    key="slack",
    label="Slack",
    Config=SlackConfig,
    Secret=SlackSecret,
    host=SecretUrl("webhook_url", SLACK_URL),
    rate_scopes=(RateScope("slack.tenant", capacity=3, refill_per_s=1.0),),
)


def fitted(raw: str, limit: int) -> tuple[str, bool]:
    """`raw` escaped, within `limit` characters: cut before an escape rather than through one, and marked."""
    escaped = "".join(ESCAPES.get(c, c) for c in raw)
    if len(escaped) <= limit:
        return escaped, False
    kept: list[str] = []
    size, budget = 0, limit - len(MARK)
    for char in raw:
        part = ESCAPES.get(char, char)
        if size + len(part) > budget:
            break
        kept.append(part)
        size += len(part)
    return "".join(kept) + MARK, True


def _mrkdwn(text: str) -> dict[str, Any]:
    return {"type": "mrkdwn", "text": text, "verbatim": True}


def render(message: Message) -> tuple[dict[str, Any], list[str]]:
    """The message as Slack's webhook body, and the names of the values it cut."""
    truncated: list[str] = []
    blocks: list[dict[str, Any]] = []

    def kept(name: str, value: tuple[str, bool]) -> str:
        if value[1]:
            truncated.append(name)
        return value[0]

    if message.title:
        title = kept("title", fitted(message.title, SECTION_MAX - 2))
        blocks.append({"type": "section", "text": _mrkdwn(f"*{title}*")})
    blocks.append({"type": "section", "text": _mrkdwn(kept("text", fitted(message.text, SECTION_MAX)))})
    fields: list[dict[str, Any]] = []
    for i, f in enumerate(message.fields):
        label = kept(f"fields[{i}].label", fitted(f.label, LABEL_MAX))
        value = kept(f"fields[{i}].value", fitted(f.value, FIELD_MAX - len(label) - 3))
        fields.append(_mrkdwn(f"*{label}*\n{value}"))
    for start in range(0, len(fields), FIELDS_A_SECTION):
        blocks.append({"type": "section", "fields": fields[start : start + FIELDS_A_SECTION]})
    if message.links:
        buttons = [
            {"type": "button", "text": {"type": "plain_text", "text": kept(f"links[{i}].label", cut(link.label,
             BUTTON_MAX)), "emoji": False}, "url": link.url, "action_id": f"link_{i}"}
            for i, link in enumerate(message.links)
        ]  # fmt: skip
        blocks.append({"type": "actions", "elements": buttons})
    blocks.append({"type": "context", "elements": [_mrkdwn(f"Severity: {message.severity.value}")]})
    fallback = f"{message.title}: {message.text}" if message.title else message.text
    return {"text": fitted(fallback, SECTION_MAX)[0], "blocks": blocks}, truncated


class SendConfig(Message):
    connection: uuid.UUID = connection_field("slack")


class SendOutput(BaseModel):
    sent: bool
    truncated: list[str]


class SendMessage(Node):
    """Posts a message to the webhook's channel."""

    type = "slack.send_message"
    version = 1
    title = "Send a Slack message"
    description = (
        "Posts a message to a Slack channel through an incoming webhook. A send that fails after it may have arrived"
        " is never retried."
    )
    Config = SendConfig
    Output = SendOutput
    credentials = ("slack",)
    side_effect = SideEffect.AMBIGUOUS

    async def simulate(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        _, truncated = render(config)
        return SendOutput(sent=True, truncated=truncated)

    async def run(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        payload, truncated = render(config)
        connection = await ctx.connection(config.connection)
        answer = await connection.http.request("POST", "", json=payload)
        status = answer.status_code
        if status == 200 and answer.content == b"ok":  # Slack's documented success; any other 200 proves nothing
            return SendOutput(sent=True, truncated=truncated)
        if status in REFUSALS:
            raise FatalError(*REFUSALS[status])
        if 400 <= status < 500 and status != 429:
            raise FatalError("slack.refused", "Slack refused the message.")
        raise OutcomeUnknownError("slack.outcome_unknown", "Slack's answer doesn't say whether the message was posted.")


PLUGIN = Plugin(name="slack", version="1.0.0", nodes=(SendMessage,), connection_types=(SLACK,))
