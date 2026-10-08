# SPDX-License-Identifier: Apache-2.0
"""Google Chat (plugins-3 3c-1, D18): a message to a space through its incoming webhook, whose URL is the credential.

The URL is Google's documented form only, `https://chat.googleapis.com/v1/spaces/SPACE/messages?key=KEY&token=TOKEN`
(developers.google.com `workspace/chat/quickstart/webhooks`); the key's and token's characters aren't documented, so
they're the URL's unreserved ones, `%` and `=`. One quota scope a space at 1 a second, no burst: Google documents 1
request a second a space, shared by all its webhooks (`limits`), and the URL names the space (D9).

The message is text in Chat's own syntax (`format-messages`): the title bold, then the text, each field a bold label
and its value, links as `<url|label>`, the severity a line. Run data's `<` and `>` become their full-width forms: no
escape is documented, and `<users/all>` would notify the whole space, `<url|text>` make a link of its choosing (a
bare URL is still linked, to itself: `format-messages`). A
message is at most 32,000 bytes; the body is kept within 30,000 bytes as sent, cutting the text, then field values,
labels and links, each cut marked and reported.

A send is ambiguous (D20): a 200 is sent; a 4xx but 429 is Google's refusal; a 429, a 5xx or anything else after
sending is unknown (D10)."""

import json
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
from dewpoint.sdk.messages import Message, cut

QUERY_VALUE = r"[A-Za-z0-9._~%=-]{1,512}"
CHAT_URL = (
    rf"https://chat\.googleapis\.com/v1/spaces/[A-Za-z0-9_-]{{1,64}}/messages\?key={QUERY_VALUE}&token={QUERY_VALUE}"
)
BUDGET = 30_000  # bytes of the body, under Google's documented 32,000 a message
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
NEUTRAL = str.maketrans({"<": "＜", ">": "＞"})


class ChatConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    webhook_url: SecretStr = Field(max_length=2048)


CHAT = ConnectionType(
    key="google_chat",
    label="Google Chat",
    Config=ChatConfig,
    Secret=ChatSecret,
    host=SecretUrl("webhook_url", CHAT_URL),
    rate_scopes=(
        RateScope(
            "google_chat.space",
            secret="webhook_url",  # noqa: S106 - a field's name
            secret_pattern=r"/spaces/([A-Za-z0-9_-]+)/",  # noqa: S106 - the space's part of it
            capacity=1,
            refill_per_s=1.0,
        ),
    ),
)


def _text(message: Message, title_max: int, text_max: int, value_max: int, label_max: int, links_kept: int
          ) -> tuple[str, list[str]]:  # fmt: skip
    truncated: list[str] = []

    def kept(name: str, value: tuple[str, bool]) -> str:
        if value[1]:
            truncated.append(name)
        return value[0]

    text = kept("text", cut(message.text.translate(NEUTRAL), text_max, unit="bytes"))
    head = f"*{kept('title', cut(message.title.translate(NEUTRAL), title_max))}*\n{text}" if message.title else text
    sections = [head]
    fields = [
        f"*{kept(f'fields[{i}].label', cut(f.label.translate(NEUTRAL), label_max))}*: "
        f"{kept(f'fields[{i}].value', cut(f.value.translate(NEUTRAL), value_max, unit='bytes'))}"
        for i, f in enumerate(message.fields)
    ]
    links = [
        f"<{link.url.replace('|', '%7C')}|{kept(f'links[{i}].label', cut(link.label.translate(NEUTRAL), label_max))}>"
        for i, link in enumerate(message.links[:links_kept])
    ]
    truncated += [f"links[{i}]" for i in range(links_kept, len(message.links))]
    sections += ["\n".join(part) for part in (fields, links) if part]
    sections.append(f"Severity: {message.severity.value}")
    return "\n\n".join(sections), truncated


def _encoded(body: dict[str, Any]) -> bytes:
    """The body as httpx 0.28 sends it (`httpx._content.encode_json`): compact, UTF-8."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def render(message: Message) -> tuple[dict[str, Any], list[str]]:
    """The message as the webhook's body, within `BUDGET` bytes, and the names of the values it cut."""
    for level in LEVELS:
        text, truncated = _text(message, *level)
        body = {"text": text}
        if len(_encoded(body)) <= BUDGET:
            return body, truncated
    return body, truncated  # the last level always fits: the message model bounds every value


class SendConfig(Message):
    connection: uuid.UUID = connection_field("google_chat")


class SendOutput(BaseModel):
    sent: bool
    truncated: list[str]


class SendMessage(Node):
    """Posts a message to the webhook's space."""

    type = "google_chat.send_message"
    version = 1
    title = "Send a Google Chat message"
    description = (
        "Posts a message to a Google Chat space through an incoming webhook. A send that fails after it may have"
        " arrived is never retried."
    )
    Config = SendConfig
    Output = SendOutput
    credentials = ("google_chat",)
    side_effect = SideEffect.AMBIGUOUS

    async def simulate(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        _, truncated = render(config)
        return SendOutput(sent=True, truncated=truncated)

    async def run(self, ctx: StepContext, config: SendConfig) -> SendOutput:
        body, truncated = render(config)
        connection = await ctx.connection(config.connection)
        answer = await connection.http.request("POST", "", json=body)
        status = answer.status_code
        if status == 200:
            return SendOutput(sent=True, truncated=truncated)
        if 400 <= status < 500 and status != 429:
            raise FatalError("google_chat.refused", f"Google Chat refused the message (HTTP {status}).")
        raise OutcomeUnknownError(
            "google_chat.outcome_unknown", "Google Chat's answer doesn't say whether the message was posted."
        )


PLUGIN = Plugin(name="google_chat", version="1.0.0", nodes=(SendMessage,), connection_types=(CHAT,))
