# SPDX-License-Identifier: Apache-2.0
"""`servicenow.create_incident` (plugins-3 3d-2, D22), reconcilable: the incident's `correlation_id` is the config's,
else the step's idempotency key; a retry first asks for it (`reconcile()`), keeping only records whose
`correlation_id` is the step's, because the Table API ignores a query part it can't read. The message model renders
into `short_description` (one line, at most 160 UTF-16 units) and `description` (at most 4,000), cut and reported."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from dewpoint.plugins.servicenow import TABLE, CreateIncident, render_incident
from dewpoint.sdk import FatalError, RetryableError, SideEffect
from tests.plugins.mist.fakes import FakeConnection, FakeHttp, FakeStep, Reply

KEY = "a" * 64
SYS_ID = "9d385017c611228701d22104cc95c371"
CONNECTION = "00000000-0000-0000-0000-000000000001"


@dataclass
class Step(FakeStep):
    def idempotency_key(self) -> str:
        return KEY


def create(**changes: Any) -> Any:
    return CreateIncident.Config.model_validate({"connection": CONNECTION, "text": "Disk full on db-1", **changes})


def connection(script: Any) -> tuple[FakeConnection, FakeHttp]:
    http = FakeHttp(script)
    config = {"instance_url": "https://acme.service-now.com"}
    return FakeConnection(http, config=config, id=uuid.UUID(CONNECTION), type="servicenow"), http


def created(**fields: Any) -> Reply:
    return Reply(201, {"result": {"sys_id": SYS_ID, "number": "INC0010002", "correlation_id": KEY, **fields}})


def test_the_node_is_reconcilable_and_retried_for_half_a_minute() -> None:
    assert CreateIncident.type == "servicenow.create_incident"
    assert CreateIncident.side_effect == SideEffect.RECONCILABLE
    assert CreateIncident.credentials == ("servicenow",)
    r = CreateIncident.retry
    assert (r.max_attempts, r.initial_interval, r.backoff, r.max_interval) == (4, timedelta(seconds=5), 2.0,
                                                                              timedelta(seconds=20))  # fmt: skip


def test_the_message_renders_as_an_incident() -> None:
    link = {"label": "Graph", "url": "https://g.example/1"}
    config = create(title="db-1 disk full", text="2% free", severity="critical",
                    fields=[{"label": "Host", "value": "db-1"}], links=[link])  # fmt: skip
    body, cut = render_incident(config, KEY)
    assert body == {
        "short_description": "db-1 disk full",
        "description": "2% free\n\nHost: db-1\n\nGraph: https://g.example/1",
        "urgency": "1",
        "impact": "1",
        "correlation_id": KEY,
        "correlation_display": "Dewpoint",
    }
    assert cut == []


@pytest.mark.parametrize(("severity", "level"), [("info", "3"), ("success", "3"), ("warning", "2"), ("critical", "1")])
def test_severities_map_to_urgency_and_impact(severity: str, level: str) -> None:
    body, _ = render_incident(create(severity=severity), KEY)
    assert (body["urgency"], body["impact"]) == (level, level)


def test_set_values_win_and_options_go_in_only_when_set() -> None:
    body, _ = render_incident(create(), KEY)
    assert set(body) == {"short_description", "description", "urgency", "impact", "correlation_id",
                         "correlation_display"}  # fmt: skip
    group = "b" * 32
    body, _ = render_incident(create(severity="critical", urgency="3", impact="2", caller_id=SYS_ID,
                                     assignment_group=group, category="network", subcategory="wireless",
                                     contact_type="monitoring", correlation_id="alarm-7:x.y_z",
                                     correlation_display="Mist"), KEY)  # fmt: skip
    assert {k: body[k] for k in ("urgency", "impact", "caller_id", "assignment_group", "category", "subcategory",
                                 "contact_type", "correlation_id", "correlation_display")} == {
        "urgency": "3", "impact": "2", "caller_id": SYS_ID, "assignment_group": group, "category": "network",
        "subcategory": "wireless", "contact_type": "monitoring", "correlation_id": "alarm-7:x.y_z",
        "correlation_display": "Mist"}  # fmt: skip


def test_the_short_description_is_one_line_of_printable_text() -> None:
    body, _ = render_incident(create(title="a\nb\r\nc\vd\x85e f\x00g\th"), KEY)
    assert body["short_description"] == "a b c d e f g h"
    body, _ = render_incident(create(text="first line\nsecond"), KEY)
    assert body["short_description"] == "first line second" and body["description"] == "first line\nsecond"


def test_a_long_title_is_cut_to_160_and_reported_a_long_text_isnt() -> None:
    body, cut = render_incident(create(title="t" * 161), KEY)
    assert len(body["short_description"]) == 160 and body["short_description"].endswith("…") and cut == ["title"]
    body, cut = render_incident(create(title="\U0001f600" * 100), KEY)  # 200 UTF-16 units: Java counts these
    assert len(body["short_description"].encode("utf-16-le")) // 2 <= 160 and cut == ["title"]
    body, cut = render_incident(create(text="x" * 200), KEY)
    assert len(body["short_description"]) == 160 and cut == []  # the whole text is in the description


@pytest.mark.parametrize("fill", ["x", "\U0001f600"])
def test_a_long_description_is_cut_to_4000_utf16_units_and_reported(fill: str) -> None:
    body, cut = render_incident(create(text=fill * 5000), KEY)
    assert len(body["description"].encode("utf-16-le")) // 2 <= 4000 and body["description"].endswith("…")
    assert cut == ["description"]


@pytest.mark.parametrize("value", ["", "a^b", "a b", "a=b", "é", "a" * 101, "a\n", "a,b"])
def test_a_correlation_id_outside_the_safe_set_is_refused(value: str) -> None:
    with pytest.raises(ValidationError):
        create(correlation_id=value)


@pytest.mark.parametrize("field", ["caller_id", "assignment_group"])
@pytest.mark.parametrize("value", ["", "A" * 32, "a" * 31, "a" * 33, "g" * 32, "a" * 32 + "\n"])
def test_a_reference_is_a_sys_id(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        create(**{field: value})


@pytest.mark.parametrize("field", ["category", "subcategory", "contact_type", "correlation_display"])
@pytest.mark.parametrize("value", ["", "a\nb", "a" * 101])
def test_a_choice_is_one_short_line(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        create(**{field: value})


async def run(config: Any, script: Any, attempt: int = 1) -> tuple[Any, FakeHttp]:
    conn, http = connection(script)
    out = await CreateIncident().run(Step(conn, attempt=attempt), config)
    return out.model_dump(mode="json"), http


async def test_a_create_posts_the_incident_and_returns_its_ids() -> None:
    config = create(title="db-1 disk full")
    out, http = await run(config, lambda sent: created())
    [sent] = http.sent
    assert (sent.method, sent.url) == ("POST", TABLE)
    assert sent.params == {"sysparm_fields": "sys_id,number,correlation_id", "sysparm_exclude_reference_link": "true"}
    assert sent.headers == {"Accept": "application/json"}
    assert sent.json == render_incident(config, KEY)[0]
    assert out == {"sys_id": SYS_ID, "number": "INC0010002", "correlation_id": KEY, "truncated": []}


@pytest.mark.parametrize(
    ("status", "error", "code"),
    [(400, FatalError, "servicenow.invalid_request"), (401, FatalError, "servicenow.unauthorized"),
     (403, FatalError, "servicenow.forbidden"), (404, FatalError, "servicenow.not_found"),
     (409, FatalError, "servicenow.refused"), (408, RetryableError, "servicenow.unavailable"),
     (425, RetryableError, "servicenow.unavailable"), (500, RetryableError, "servicenow.unavailable"),
     (503, RetryableError, "servicenow.unavailable"), (200, RetryableError, "servicenow.unexpected"),
     (302, RetryableError, "servicenow.unexpected")],
)  # fmt: skip
async def test_answers(status: int, error: type[Exception], code: str) -> None:
    with pytest.raises(error) as raised:
        await run(create(), lambda sent: Reply(status, {"error": {"message": "secret-looking detail"}}))
    assert raised.value.code == code and "secret-looking" not in str(raised.value)  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "body",
    [None, {}, {"result": []}, {"result": {"sys_id": "x", "number": "INC1"}}, {"result": {"sys_id": SYS_ID}},
     {"result": {"sys_id": SYS_ID, "number": 7}}, {"result": {"sys_id": SYS_ID, "number": ""}},
     {"result": {"sys_id": SYS_ID, "number": "INC 1"}}, {"result": {"sys_id": SYS_ID, "number": "I" * 41}}],
)  # fmt: skip
async def test_a_created_answer_it_cant_read_is_retried_and_reconciled(body: Any) -> None:
    """The record may be stored: the retry's `reconcile()` finds it."""
    with pytest.raises(RetryableError) as raised:
        await run(create(), lambda sent: Reply(201, body))
    assert raised.value.code == "servicenow.unexpected"


async def reconcile(config: Any, script: Any) -> tuple[Any, FakeHttp]:
    conn, http = connection(script)
    out = await CreateIncident().reconcile(Step(conn, attempt=2), config)
    return (out.model_dump(mode="json") if out is not None else None), http


def found(*records: dict[str, Any]) -> Reply:
    return Reply(200, {"result": list(records)})


async def test_a_retry_finds_the_steps_incident_by_its_correlation_id() -> None:
    record = {"sys_id": SYS_ID, "number": "INC0010002", "correlation_id": KEY}
    out, http = await reconcile(create(), lambda sent: found(record))
    [sent] = http.sent
    assert (sent.method, sent.url, sent.json) == ("GET", TABLE, None)
    assert sent.params == {"sysparm_query": f"correlation_id={KEY}^ORDERBYsys_created_on",
                           "sysparm_fields": "sys_id,number,correlation_id", "sysparm_limit": "10"}  # fmt: skip
    assert out == {"sys_id": SYS_ID, "number": "INC0010002", "correlation_id": KEY, "truncated": []}


async def test_records_of_another_correlation_id_arent_the_steps() -> None:
    """An ignored query part returns other records: none of them is the step's incident."""
    others = [{"sys_id": "b" * 32, "number": "INC1", "correlation_id": ""},
              {"sys_id": "c" * 32, "number": "INC2", "correlation_id": KEY.upper()}]  # fmt: skip
    out, _ = await reconcile(create(), lambda sent: found(*others))
    assert out is None
    mine = {"sys_id": SYS_ID, "number": "INC3", "correlation_id": KEY}
    out, _ = await reconcile(create(), lambda sent: found(*others, mine))
    assert out is not None and out["sys_id"] == SYS_ID


async def test_none_found_means_the_create_didnt_land() -> None:
    out, _ = await reconcile(create(), lambda sent: found())
    assert out is None


async def test_a_configured_correlation_id_is_the_one_asked_for() -> None:
    record = {"sys_id": SYS_ID, "number": "INC0010002", "correlation_id": "alarm-7"}
    out, http = await reconcile(create(correlation_id="alarm-7"), lambda sent: found(record))
    assert http.sent[0].params["sysparm_query"] == "correlation_id=alarm-7^ORDERBYsys_created_on"
    assert out is not None and out["correlation_id"] == "alarm-7"


@pytest.mark.parametrize(
    "record", [{"sys_id": "x", "number": "INC1", "correlation_id": KEY}, {"sys_id": SYS_ID, "correlation_id": KEY}]
)
async def test_a_matching_record_it_cant_read_is_retried(record: dict[str, Any]) -> None:
    with pytest.raises(RetryableError) as raised:
        await reconcile(create(), lambda sent: found(record))
    assert raised.value.code == "servicenow.unexpected"


@pytest.mark.parametrize(
    "body",
    [None, {}, {"result": {}}, {"result": "x"}, [{"sys_id": SYS_ID, "number": "INC1", "correlation_id": KEY}]],
)
async def test_a_list_it_cant_read_is_retried(body: Any) -> None:
    with pytest.raises(RetryableError):
        await reconcile(create(), lambda sent: Reply(200, body))


@pytest.mark.parametrize(("status", "error"), [(401, FatalError), (403, FatalError), (500, RetryableError)])
async def test_a_failed_search_says_so(status: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        await reconcile(create(), lambda sent: Reply(status))


async def test_simulating_renders_and_sends_nothing() -> None:
    conn, http = connection(lambda sent: created())
    step = Step(conn)
    out = await CreateIncident().simulate(step, create(title="t" * 200))
    assert http.sent == [] and step.opened == []
    assert out.model_dump(mode="json") == {"sys_id": "0" * 32, "number": "INC0000000", "correlation_id": KEY,
                                           "truncated": ["title"]}  # fmt: skip
