# SPDX-License-Identifier: Apache-2.0
"""PagerDuty (plugins-3 3d-1, D22): alerts through the Events API v2.

The connection names the service region, whose Events API host the runtime posts to (`events.pagerduty.com`, or
`events.eu.pagerduty.com`; `/v2/enqueue` on both), and holds the integration key, which the runtime puts into each
event as its `routing_key` (`BodyField`): the plugin never holds it. No verify hook: checking a key means sending an
event, which would page someone. One quota scope a key: bursts of 20, then 100 a minute, never more than PagerDuty's
about 120 in any 60 s.

`pagerduty.trigger_alert` is keyed: its `dedup_key` is the config's, else the step's idempotency key, so a retried
trigger joins the alert it opened (one resolved meanwhile opens a new alert: PagerDuty's documented behaviour).
`pagerduty.acknowledge_alert` and `pagerduty.resolve_alert` are idempotent and name the alert by its `dedup_key`.
The trigger renders the message model: `summary` the title, else the text, on one line, at most 1024 characters;
the severity mapped (info and success to info); `source` the config's; `custom_details` the text and the fields;
`links` the message's links; the event within 500,000 bytes as sent (PagerDuty takes 512 KB), cut and reported.

A 202 is applied; a 400 is `pagerduty.invalid_event`, another 4xx `pagerduty.refused`, both fatal; a 5xx is retried
(the runtime waits out a 429's or a 503's short `Retry-After` in the attempt, and retries a 429 without one)."""

import json
import re
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from dewpoint.sdk import (
    BodyField,
    ConnectionType,
    FatalError,
    HostMap,
    HttpResponse,
    Node,
    Plugin,
    RateScope,
    RetryableError,
    SideEffect,
    StepContext,
    connection_field,
)
from dewpoint.sdk.messages import Message, Severity, cut

REGIONS = {"us": "events.pagerduty.com", "eu": "events.eu.pagerduty.com"}
PATH = "/v2/enqueue"
SUMMARY_MAX = 1024
BUDGET = 500_000  # bytes of an event as sent, under PagerDuty's 512 KB
SEVERITIES = {Severity.INFO: "info", Severity.SUCCESS: "info", Severity.WARNING: "warning",
              Severity.CRITICAL: "critical"}  # fmt: skip
# What the text and each field's value may keep, in bytes, tighter at each level until the event fits; the first is
# the message model's own bounds: nothing cut.
LEVELS = ((160_000, 40_000), (100_000, 10_000), (20_000, 2000), (4000, 500))
KEY_TEXT = re.compile(r"[^\x00-\x1f\x7f]{1,255}")  # a dedup_key: at most 255 characters, no control character
NEWLINES = re.compile(r"\r\n|\r|\n")


class PagerDutyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    region: Literal["us", "eu"] = Field(title="Service region", description="Where the PagerDuty account lives.")


class PagerDutySecret(BaseModel):
    model_config = ConfigDict(extra="forbid")
    routing_key: SecretStr = Field(min_length=32, max_length=32, title="Integration key")


PAGERDUTY = ConnectionType(
    key="pagerduty",
    label="PagerDuty",
    Config=PagerDutyConfig,
    Secret=PagerDutySecret,
    auth=BodyField(field="routing_key", secret="routing_key"),  # noqa: S106 - a field's name
    host=HostMap("region", REGIONS),
    rate_scopes=(RateScope("pagerduty.integration", secret="routing_key", capacity=20, refill_per_s=100 / 60),),  # noqa: S106 - a field
)


def _dedup_key(value: str | None) -> str | None:
    if value is not None and not KEY_TEXT.fullmatch(value):
        raise ValueError("1 to 255 characters, no control character")
    return value


def _encoded(body: dict[str, Any]) -> bytes:
    """The event as httpx 0.28 sends it (`httpx._content.encode_json`): compact, UTF-8."""
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


class TriggerConfig(Message):
    connection: uuid.UUID = connection_field("pagerduty")
    source: str = Field("dewpoint", min_length=1, max_length=255, title="Source",
                        description="The affected system, preferably its host name.")  # fmt: skip
    dedup_key: str | None = Field(None, title="Dedup key",
                                  description="Names the alert; the step's own key when empty.")  # fmt: skip
    component: str | None = Field(None, max_length=255, title="Component")
    group: str | None = Field(None, max_length=255, title="Group")
    event_class: str | None = Field(None, max_length=255, title="Class")

    @field_validator("dedup_key")
    @classmethod
    def _key(cls, value: str | None) -> str | None:
        return _dedup_key(value)


def _event(config: TriggerConfig, key: str, text_max: int, value_max: int) -> tuple[dict[str, Any], list[str]]:
    truncated: list[str] = []
    # A title (at most 1000 characters) always fits; a summary made from the text is cut, losing nothing: the whole
    # text is in the details.
    summary = cut(NEWLINES.sub(" ", config.title or config.text), SUMMARY_MAX)[0]
    text, text_cut = cut(config.text, text_max, unit="bytes")
    if text_cut:
        truncated.append("text")
    details: dict[str, Any] = {"text": text}
    if config.fields:
        fields = []
        for i, f in enumerate(config.fields):
            value, value_cut = cut(f.value, value_max, unit="bytes")
            if value_cut:
                truncated.append(f"fields[{i}].value")
            fields.append({"label": f.label, "value": value})
        details["fields"] = fields
    payload: dict[str, Any] = {"summary": summary, "source": config.source, "severity": SEVERITIES[config.severity]}
    for name, option in (("component", config.component), ("group", config.group), ("class", config.event_class)):
        if option is not None:
            payload[name] = option
    payload["custom_details"] = details
    event: dict[str, Any] = {"event_action": "trigger", "dedup_key": key, "payload": payload}
    if config.links:
        event["links"] = [{"href": link.url, "text": link.label} for link in config.links]
    return event, truncated


def render_trigger(config: TriggerConfig, key: str) -> tuple[dict[str, Any], list[str]]:
    """The trigger event, without its `routing_key` (the runtime's to add), within `BUDGET` bytes, and the names of
    the values it cut."""
    for level in LEVELS:
        event, truncated = _event(config, key, *level)
        if len(_encoded(event)) <= BUDGET:
            return event, truncated
    return event, truncated  # the last level always fits: the message model bounds every value


def _applied(answer: HttpResponse) -> None:
    status = answer.status_code
    if status == 202:
        return
    if status == 400:
        raise FatalError("pagerduty.invalid_event", "PagerDuty refused the event as invalid.")
    if 400 <= status < 500:
        raise FatalError("pagerduty.refused", f"PagerDuty refused the event (HTTP {status}).")
    if status >= 500:
        raise RetryableError("pagerduty.unavailable", f"PagerDuty didn't take the event (HTTP {status}).")
    raise RetryableError("pagerduty.unexpected", f"PagerDuty answered HTTP {status}, not 202.")


class TriggerOutput(BaseModel):
    dedup_key: str
    truncated: list[str]


class TriggerAlert(Node):
    """Opens (or adds to) a PagerDuty alert."""

    type = "pagerduty.trigger_alert"
    version = 1
    title = "Trigger a PagerDuty alert"
    description = (
        "Sends a trigger event to PagerDuty. A retry joins the alert it opened: the event is keyed by its dedup key, "
        "the step's own unless set."
    )
    Config = TriggerConfig
    Output = TriggerOutput
    credentials = ("pagerduty",)
    side_effect = SideEffect.KEYED

    async def simulate(self, ctx: StepContext, config: TriggerConfig) -> TriggerOutput:
        key = config.dedup_key or ctx.idempotency_key()
        _, truncated = render_trigger(config, key)
        return TriggerOutput(dedup_key=key, truncated=truncated)

    async def run(self, ctx: StepContext, config: TriggerConfig) -> TriggerOutput:
        key = config.dedup_key or ctx.idempotency_key()
        event, truncated = render_trigger(config, key)
        connection = await ctx.connection(config.connection)
        _applied(await connection.http.request("POST", PATH, json=event))
        return TriggerOutput(dedup_key=key, truncated=truncated)


class AlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection: uuid.UUID = connection_field("pagerduty")
    dedup_key: str = Field(title="Dedup key", description="The alert's, as the trigger returned it.")

    @field_validator("dedup_key")
    @classmethod
    def _key(cls, value: str) -> str:
        return _dedup_key(value) or value


class AlertOutput(BaseModel):
    dedup_key: str


class _AlertAction(Node):
    action = ""
    Config = AlertConfig
    Output = AlertOutput
    credentials = ("pagerduty",)
    side_effect = SideEffect.IDEMPOTENT

    async def simulate(self, ctx: StepContext, config: AlertConfig) -> AlertOutput:
        return AlertOutput(dedup_key=config.dedup_key)

    async def run(self, ctx: StepContext, config: AlertConfig) -> AlertOutput:
        connection = await ctx.connection(config.connection)
        event = {"event_action": self.action, "dedup_key": config.dedup_key}
        _applied(await connection.http.request("POST", PATH, json=event))
        return AlertOutput(dedup_key=config.dedup_key)


class AcknowledgeAlert(_AlertAction):
    """Acknowledges a PagerDuty alert."""

    type = "pagerduty.acknowledge_alert"
    version = 1
    title = "Acknowledge a PagerDuty alert"
    description = "Acknowledges the open alert with this dedup key; none open, PagerDuty drops it."
    action = "acknowledge"


class ResolveAlert(_AlertAction):
    """Resolves a PagerDuty alert."""

    type = "pagerduty.resolve_alert"
    version = 1
    title = "Resolve a PagerDuty alert"
    description = "Resolves the open alert with this dedup key; none open, PagerDuty drops it."
    action = "resolve"


PLUGIN = Plugin(name="pagerduty", version="1.0.0", nodes=(TriggerAlert, AcknowledgeAlert, ResolveAlert),
                connection_types=(PAGERDUTY,))  # fmt: skip
