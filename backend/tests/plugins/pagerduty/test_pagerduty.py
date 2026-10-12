# SPDX-License-Identifier: Apache-2.0
"""PagerDuty (plugins-3 3d-1, D22): a `pagerduty` connection type (the region's Events API host, the integration key
as the body's `routing_key`, never the plugin's; one quota scope a key, never more than 120 events in 60 s) and three
nodes: `pagerduty.trigger_alert` (keyed: its `dedup_key` is the config's, else the step's idempotency key, so a
retried trigger joins the alert it opened) and `pagerduty.acknowledge_alert`, `pagerduty.resolve_alert`
(idempotent). A 202 is applied, a 400 `pagerduty.invalid_event`, another 4xx `pagerduty.refused`, a 5xx retried."""

from datetime import timedelta
from fractions import Fraction
from typing import Any

import httpx
import pytest

from dewpoint.core.connections.declared import DeclaredType
from dewpoint.engine.registry.catalog import validate_plugin_manifest
from dewpoint.plugins.pagerduty import (
    BUDGET,
    PAGERDUTY,
    PLUGIN,
    AcknowledgeAlert,
    ResolveAlert,
    TriggerAlert,
    render_trigger,
)
from dewpoint.sdk import FatalError, RetryableError, SideEffect
from dewpoint.sdk.manifest import node_manifest
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, FakeStep, Reply

KEY = "a" * 64


def sent_size(body: Any) -> int:
    return len(httpx.Request("POST", "https://example.com", json=body).content)


def trigger(**changes: Any) -> Any:
    return TriggerAlert.Config.model_validate({"connection": "00000000-0000-0000-0000-000000000001",
                                               "text": "Disk full on db-1", **changes})  # fmt: skip


def test_the_plugin_validates_and_its_nodes_side_effects() -> None:
    assert validate_plugin_manifest(PLUGIN.manifest()) == []
    assert TriggerAlert.side_effect == SideEffect.KEYED
    assert AcknowledgeAlert.side_effect == ResolveAlert.side_effect == SideEffect.IDEMPOTENT
    assert all(n.credentials == ("pagerduty",) for n in (TriggerAlert, AcknowledgeAlert, ResolveAlert))
    m = PAGERDUTY.manifest()
    assert m["auth"] == {"kind": "body_field", "field": "routing_key", "secret": "routing_key"}
    assert m["host"] == {"kind": "map", "field": "region",
                         "hosts": {"us": "events.pagerduty.com", "eu": "events.eu.pagerduty.com"}}  # fmt: skip
    assert m["verify"] is False  # checking a key would page someone


def most_taken(capacity: float, refill_per_s: float, window_s: int) -> int:
    refill = Fraction(refill_per_s).limit_denominator(10**6)
    taken, now, tokens = 0, Fraction(0), Fraction(capacity)
    while True:
        while tokens >= 1:
            tokens, taken = tokens - 1, taken + 1
        now += (1 - tokens) / refill
        if now > window_s:
            return taken
        tokens = Fraction(1)


@pytest.mark.parametrize("node", [TriggerAlert, AcknowledgeAlert, ResolveAlert])
def test_an_event_is_retried_for_minutes_as_pagerduty_advises(node: Any) -> None:
    """PagerDuty: retry a 429 or a 5xx "after some time", "preferably with a backoff of a few minutes" (the review's
    M1): 30 s, then 60 s, then 120 s, three and a half minutes in all."""
    retry = node.retry
    assert (retry.max_attempts, retry.initial_interval, retry.backoff, retry.max_interval) == (
        4, timedelta(seconds=30), 2.0, timedelta(minutes=2))  # fmt: skip
    waits = [min(retry.initial_interval * retry.backoff**n, retry.max_interval) for n in range(retry.max_attempts - 1)]
    assert sum(waits, timedelta()) == timedelta(seconds=210)
    assert node_manifest(node)["retry"]["initial_interval_s"] == 30


def test_one_scope_a_key_never_past_120_events_in_60_seconds() -> None:
    [scope] = PAGERDUTY.rate_scopes
    assert (scope.kind, scope.secret) == ("pagerduty.integration", "routing_key")
    assert most_taken(scope.capacity, scope.refill_per_s, 60) <= 120
    declared = DeclaredType.from_manifest("pagerduty", PAGERDUTY.manifest())
    keys = [declared.scopes({"region": "us"}, {"routing_key": k}, lambda v: f"mac({v})")[0].key
            for k in ("k" * 32, "k" * 32, "j" * 32)]  # fmt: skip
    assert keys[0] == keys[1] != keys[2]


def test_the_routing_key_is_32_characters() -> None:
    declared = DeclaredType.from_manifest("pagerduty", PAGERDUTY.manifest())
    declared.secret({"routing_key": "R" + "0" * 31})
    for bad in ("k" * 31, "k" * 33):
        with pytest.raises(ValueError):
            declared.secret({"routing_key": bad})


def test_a_trigger_renders_the_message_as_an_events_v2_event() -> None:
    event, cut = render_trigger(trigger(title="db-1 disk", fields=[{"label": "Free", "value": "2%"}],
                                        links=[{"label": "Runbook", "url": "https://wiki.example.com/disk"}],
                                        severity="warning", source="db-1.example.com", component="postgres",
                                        group="db", event_class="disk"), KEY)  # fmt: skip
    assert event == {
        "event_action": "trigger",
        "dedup_key": KEY,
        "payload": {"summary": "db-1 disk", "source": "db-1.example.com", "severity": "warning",
                    "component": "postgres", "group": "db", "class": "disk",
                    "custom_details": {"text": "Disk full on db-1", "fields": [{"label": "Free", "value": "2%"}]}},
        "links": [{"href": "https://wiki.example.com/disk", "text": "Runbook"}],
    }  # fmt: skip
    assert cut == [] and "routing_key" not in event  # the runtime's to add


@pytest.mark.parametrize(("severity", "pagerduty"), [("info", "info"), ("success", "info"), ("warning", "warning"),
                                                     ("critical", "critical")])  # fmt: skip
def test_severities_map(severity: str, pagerduty: str) -> None:
    assert render_trigger(trigger(severity=severity), KEY)[0]["payload"]["severity"] == pagerduty


def test_without_a_title_the_summary_is_the_text_on_one_line_and_options_stay_out() -> None:
    event, _ = render_trigger(trigger(text="Disk full\non db-1"), KEY)
    assert event["payload"] == {"summary": "Disk full on db-1", "source": "dewpoint", "severity": "info",
                                "custom_details": {"text": "Disk full\non db-1"}}  # fmt: skip
    assert "links" not in event


@pytest.mark.parametrize("fill", ["é", "\x01", '"', "\U0001f600"])
def test_the_largest_event_fits_its_budget_cut_and_marked(fill: str) -> None:
    event, cut = render_trigger(trigger(title=fill * 1000, text=fill * 40_000,
                                        fields=[{"label": fill * 200, "value": fill * 10_000}] * 25), KEY)  # fmt: skip
    assert sent_size(event) <= BUDGET <= 512 * 1024
    assert len(event["payload"]["summary"].encode()) <= 1024
    assert "fields[0].value" in cut  # each fill takes 2 to 6 bytes on the wire: the whole event is past the budget


def test_a_summary_is_at_most_1024_bytes_an_ascii_title_whole() -> None:
    event, cut = render_trigger(trigger(title="t" * 1000, text="x" * 2000), KEY)
    assert len(event["payload"]["summary"]) == 1000 and cut == []
    event, cut = render_trigger(trigger(text="x" * 2000), KEY)
    assert len(event["payload"]["summary"]) <= 1024 and event["payload"]["summary"].endswith("…")
    assert cut == []  # the whole text is in the details


@pytest.mark.parametrize("fill", ["é", "\U0001f600"])
def test_a_wide_title_is_cut_to_1024_bytes_and_reported(fill: str) -> None:
    """PagerDuty doesn't say whether its 1024 counts characters, UTF-16 units or bytes: bytes fit all three (the
    review's L5)."""
    event, cut = render_trigger(trigger(title=fill * 1000), KEY)
    summary = event["payload"]["summary"]
    assert len(summary.encode()) <= 1024 and summary.endswith("…") and cut == ["title"]


def test_a_summary_is_one_line_of_printable_text() -> None:
    title = "a\vb\fc\x85d\u2028e\u2029f\x00g\th\x1bi\x7fj\r\nk"
    event, _ = render_trigger(trigger(title=title), KEY)
    assert event["payload"]["summary"] == "a b c d e f g h i j k"


@pytest.mark.parametrize("dedup_key", ["", "k" * 256, "a\nb", "a\x00b"])
def test_a_dedup_key_of_another_form_is_refused(dedup_key: str) -> None:
    with pytest.raises(ValueError):
        trigger(dedup_key=dedup_key)
    with pytest.raises(ValueError):
        ResolveAlert.Config.model_validate({"connection": "00000000-0000-0000-0000-000000000001",
                                            "dedup_key": dedup_key})  # fmt: skip


async def run(node: Any, config: dict[str, Any], reply: Reply) -> tuple[Any, FakeHttp]:
    http = FakeHttp(lambda sent: reply)
    connection = FakeConnection(http, config={"region": "us"})
    value = node.Config.model_validate({"connection": str(connection.id), **config})
    out = await node().run(FakeStep(connection), value)
    return out.model_dump(mode="json"), http


async def test_a_trigger_posts_to_enqueue_keyed_by_the_steps_idempotency_key() -> None:
    out, http = await run(TriggerAlert, {"text": "hello"}, Reply(202, {"status": "success", "dedup_key": "k"}))
    [sent] = http.sent
    assert (sent.method, sent.url, sent.headers) == ("POST", "/v2/enqueue", None)
    assert sent.json["dedup_key"] == "k" and out == {"dedup_key": "k", "truncated": []}  # FakeStep's key is "k"


async def test_a_configured_dedup_key_wins() -> None:
    out, http = await run(TriggerAlert, {"text": "hello", "dedup_key": "srv01/HTTP"}, Reply(202, {}))
    assert http.sent[0].json["dedup_key"] == "srv01/HTTP" and out["dedup_key"] == "srv01/HTTP"


@pytest.mark.parametrize(("node", "action"), [(AcknowledgeAlert, "acknowledge"), (ResolveAlert, "resolve")])
async def test_acknowledge_and_resolve_name_the_alert(node: Any, action: str) -> None:
    out, http = await run(node, {"dedup_key": "srv01/HTTP"}, Reply(202, {}))
    assert http.sent[0].json == {"event_action": action, "dedup_key": "srv01/HTTP"}
    assert out == {"dedup_key": "srv01/HTTP"}


@pytest.mark.parametrize(
    ("status", "error", "code"),
    [(400, FatalError, "pagerduty.invalid_event"), (401, FatalError, "pagerduty.refused"),
     (404, FatalError, "pagerduty.refused"), (500, RetryableError, "pagerduty.unavailable"),
     (502, RetryableError, "pagerduty.unavailable"), (503, RetryableError, "pagerduty.unavailable"),
     (408, RetryableError, "pagerduty.unavailable"), (425, RetryableError, "pagerduty.unavailable"),
     (200, RetryableError, "pagerduty.unexpected")],
)  # fmt: skip
@pytest.mark.parametrize("node", [TriggerAlert, ResolveAlert])
async def test_answers(node: Any, status: int, error: type[Exception], code: str) -> None:
    config = {"text": "hello"} if node is TriggerAlert else {"dedup_key": "x"}
    with pytest.raises(error) as raised:
        await run(node, config, Reply(status, {"status": "invalid", "message": "secret-looking detail"}))
    assert raised.value.code == code and "secret-looking" not in str(raised.value)  # type: ignore[attr-defined]


async def test_simulating_renders_and_sends_nothing() -> None:
    http = FakeHttp(lambda sent: Reply(202))
    connection = FakeConnection(http, config={"region": "us"})
    step = FakeStep(connection)
    value = TriggerAlert.Config.model_validate({"connection": str(connection.id), "text": "x", "title": "t" * 1000})
    out = (await TriggerAlert().simulate(step, value)).model_dump(mode="json")  # type: ignore[arg-type]
    assert out == {"dedup_key": "k", "truncated": []} and http.sent == [] and step.opened == []
    value = ResolveAlert.Config.model_validate({"connection": str(connection.id), "dedup_key": "x"})
    out = (await ResolveAlert().simulate(step, value)).model_dump(mode="json")  # type: ignore[arg-type]
    assert out == {"dedup_key": "x"} and http.sent == []
