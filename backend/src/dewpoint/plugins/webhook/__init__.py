# SPDX-License-Identifier: Apache-2.0
"""A generic webhook (plugins-3 3c-1, D18): a POST of JSON to a receiver's URL, which is the credential.

The URL is any https URL with a lowercase host name or IPv4 address, an optional port, and a path and query of RFC
3986's characters, no user, no fragment, and not Slack's, Google Chat's or Teams' webhook host, which have types of
their own; the SSRF guard vets where it resolves on every connect (D7).
A secret URL's pattern starts with https, so a plain-http receiver isn't reachable yet. One quota scope a host, 1 a
second with bursts of 5: a receiver's limits aren't known, and URLs to one host share its budget (D9).

Two sends, both ambiguous (D20): `webhook.send_message` posts the message model as JSON, the same configuration as
the chat targets'; `webhook.send_json` posts a body of the workflow's, never null, at most 1 MiB as sent. The
answer's status is the only output, never its body: a receiver's answer could quote anything. A 2xx is sent; a 4xx
but 429 is the receiver's refusal; a 429, a 5xx or anything else after sending is unknown (D10); no redirect is
followed."""

import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, field_validator

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
from dewpoint.sdk.messages import Message

HOST = r"[a-z0-9-]{1,63}(\.[a-z0-9-]{1,63}){0,126}"
PORT = r"(6553[0-5]|655[0-2][0-9]|65[0-4][0-9]{2}|6[0-4][0-9]{3}|[1-5][0-9]{4}|[1-9][0-9]{0,3})"
PATH = r"/[A-Za-z0-9._~!$&'()*+,;=:@%/?-]{0,4000}"  # RFC 3986's unreserved, sub-delims, ':', '@', '/', '?' and '%'
# Not a host whose webhooks have a type of their own, which escapes run data and charges the provider's scope (the 3c-1
# review, finding 4): Slack's, Google Chat's, Teams' Workflows and the retired Office 365 connectors'.
DEDICATED = (
    r"(?!(hooks\.slack\.com|chat\.googleapis\.com|([a-z0-9-]+\.)*(logic\.azure\.com|api\.powerplatform\.com"
    r"|webhook\.office\.com))([:/]|\Z))"
)
WEBHOOK_URL = rf"https://{DEDICATED}{HOST}(:{PORT})?({PATH})?"
BODY_MAX = 1 << 20  # bytes of a workflow's body as sent


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WebhookSecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: SecretStr = Field(max_length=4096)


WEBHOOK = ConnectionType(
    key="webhook",
    label="Webhook",
    Config=WebhookConfig,
    Secret=WebhookSecret,
    host=SecretUrl("url", WEBHOOK_URL),
    rate_scopes=(
        RateScope(
            "webhook.host",
            secret="url",  # noqa: S106 - a field's name
            secret_pattern=r"^https://([a-z0-9.-]+)",  # noqa: S106 - the host's part of it
            capacity=5,
            refill_per_s=1.0,
        ),
    ),
)


def _encoded(body: Any) -> bytes:
    """The body as httpx 0.28 sends it (`httpx._content.encode_json`): compact, UTF-8, never NaN."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


class SendOutput(BaseModel):
    sent: bool
    status: int | None  # the answer's; none when simulated


async def _post(ctx: StepContext, connection_id: uuid.UUID, body: Any) -> SendOutput:
    connection = await ctx.connection(connection_id)
    answer = await connection.http.request("POST", "", json=body)
    status = answer.status_code
    if 200 <= status < 300:
        return SendOutput(sent=True, status=status)
    if 400 <= status < 500 and status != 429:
        raise FatalError("webhook.refused", f"The receiver refused the request (HTTP {status}).")
    raise OutcomeUnknownError(
        "webhook.outcome_unknown", "The receiver's answer doesn't say whether it took the request."
    )


class SendMessageConfig(Message):
    connection: uuid.UUID = connection_field("webhook")


class SendMessage(Node):
    """Posts the message model as JSON to a webhook."""

    type = "webhook.send_message"
    version = 1
    title = "Send a message to a webhook"
    description = (
        "Posts a message as JSON (title, text, fields, links, severity) to a webhook. Only the answer's status is "
        "kept; a send that fails after it may have arrived is never retried."
    )
    Config = SendMessageConfig
    Output = SendOutput
    credentials = ("webhook",)
    side_effect = SideEffect.AMBIGUOUS

    async def simulate(self, ctx: StepContext, config: SendMessageConfig) -> SendOutput:
        return SendOutput(sent=True, status=None)

    async def run(self, ctx: StepContext, config: SendMessageConfig) -> SendOutput:
        return await _post(ctx, config.connection, config.model_dump(mode="json", exclude={"connection"}))


class SendJsonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: uuid.UUID = connection_field("webhook")
    # Never null: httpx sends `json=None` as no body at all, and `null` as content would need a content type the node
    # can't set (task 2's exact URL; a review of 1e71079, R1).
    body: JsonValue = Field(title="Body", description="The JSON to post, not null, at most 1 MiB.",
                            json_schema_extra={"not": {"type": "null"}})  # fmt: skip

    @field_validator("body")
    @classmethod
    def _bounded(cls, value: JsonValue) -> JsonValue:
        if value is None:
            raise ValueError("the body can't be null")
        try:
            size = len(_encoded(value))
        except ValueError:
            raise ValueError("the body must be JSON") from None
        if size > BODY_MAX:
            raise ValueError("the body is past 1 MiB")
        return value


class SendJson(Node):
    """Posts a body of the workflow's as JSON to a webhook."""

    type = "webhook.send_json"
    version = 1
    title = "Send JSON to a webhook"
    description = (
        "Posts a JSON body to a webhook. Only the answer's status is kept; a send that fails after it may have "
        "arrived is never retried."
    )
    Config = SendJsonConfig
    Output = SendOutput
    credentials = ("webhook",)
    side_effect = SideEffect.AMBIGUOUS

    async def simulate(self, ctx: StepContext, config: SendJsonConfig) -> SendOutput:
        return SendOutput(sent=True, status=None)

    async def run(self, ctx: StepContext, config: SendJsonConfig) -> SendOutput:
        return await _post(ctx, config.connection, config.body)


PLUGIN = Plugin(name="webhook", version="1.0.0", nodes=(SendMessage, SendJson), connection_types=(WEBHOOK,))
