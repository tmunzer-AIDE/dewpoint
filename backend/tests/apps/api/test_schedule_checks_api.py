# SPDX-License-Identifier: Apache-2.0
"""A draft that would break the workflow's live schedules is said so, by validate and by publish (4c-3a ruling 7):
nobody can see a schedule's stored input, so the server checks it against the draft's input, by its shape alone, and
says which schedules and why, never what their input holds. A warning: publishing goes ahead."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from dewpoint.apps import schedule_checks
from tests.apps.api.test_run_requests_api import as_role
from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, TOKEN_GRAPH, published
from tests.support.keys import FixtureKeys

pytestmark = pytest.mark.usefixtures("development_deployment")
BODY = {"cron": "0 9 * * 1-5", "time_zone": "Europe/Paris", "input": {"token": TOKEN, "site": "a"}}
BREAKING = SCHEMA | {
    "properties": {"token": {"type": "string", "x-sensitive": True, "maxLength": 3},
                   "site": {"type": "integer"}, "floor": {"type": "integer"}},
    "required": ["token", "floor"],
}  # fmt: skip


@pytest.fixture
def keyed_app(app: Any) -> Any:
    app.state.keys = KEYS
    return app


@pytest.fixture
async def workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
    return await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)


def url(ctx: Any, path: str) -> str:
    return f"/api/v1/t/{ctx.tenant_id}{path}"


async def drafted(editor: Any, ctx: Any, wf: uuid.UUID, settings: dict[str, Any]) -> None:
    revision = (await editor.get(url(ctx, f"/workflows/{wf}"))).json()["draft_revision"]
    saved = await editor.put(url(ctx, f"/workflows/{wf}/draft"), json=TOKEN_GRAPH | {"settings": settings},
                             headers={"If-Match": str(revision)})  # fmt: skip
    assert saved.status_code == 200, saved.text


async def scheduled(editor: Any, ctx: Any, wf: uuid.UUID, body: dict[str, Any] = BODY) -> str:
    made = await editor.post(url(ctx, f"/workflows/{wf}/schedules"), json=body)
    assert made.status_code == 201, made.text
    return str(made.json()["id"])


async def test_validate_says_which_live_schedules_a_draft_would_break_and_why(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """Stored inputs `{"token": …, "site": …}` against a draft that requires `floor` and makes `site` a whole number:
    those two reasons for each, in the draft's own words, the oldest schedule first. `token`'s new `maxLength` is a
    value's content: never checked, never named. A draft both fit lists none; a deleted schedule is never read."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    first = await scheduled(editor, ctx, wf)
    second = await scheduled(editor, ctx, wf, BODY | {"input": {"token": TOKEN, "site": "b"}})
    gone = await scheduled(editor, ctx, wf)
    assert (await editor.delete(url(ctx, f"/schedules/{gone}"))).status_code == 204
    await drafted(editor, ctx, wf, {"input_schema": BREAKING | {"required": ["token"]} | {
        "properties": BREAKING["properties"] | {"site": {"type": "string"}}}})  # fmt: skip
    clean = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert clean["schedule_breaks"] == [] and not [d for d in clean["diagnostics"] if d["code"].startswith("schedule")]
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    why = ["`floor` is required now.", "`site` must be a whole number now."]
    assert body["schedule_breaks"] == [
        {"schedule_id": first, "reasons": why, "more": False},
        {"schedule_id": second, "reasons": why, "more": False},
    ]
    warned = [d for d in body["diagnostics"] if d["code"] == "schedule.input_refused"]
    assert warned == [{"code": "schedule.input_refused", "node": None, "field": "/settings/input_schema", "fix": None,
                       "severity": "warning", "message": schedule_checks.REFUSED.format(n=2, s="s")}]  # fmt: skip
    assert body["valid"] is True and TOKEN not in answer.text


async def test_a_draft_that_takes_a_csv_file_breaks_every_schedule(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    sid = await scheduled(editor, ctx, wf)
    csv = {"columns": [{"header": "Site", "name": "site", "type": "string"}]}
    await drafted(editor, ctx, wf, {"input_schema": SCHEMA, "csv": csv})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == [{"schedule_id": sid, "reasons": [schedule_checks.CSV], "more": False}]
    assert [d["field"] for d in body["diagnostics"] if d["code"] == "schedule.input_refused"] == ["/settings/csv"]


async def test_publish_warns_and_publishes(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
    """A warning, never a refusal: the version is published, its answer warns, and the schedule fails at its next
    firing until its input is replaced (the owner chose warn, not refuse)."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    revision = (await editor.get(url(ctx, f"/workflows/{wf}"))).json()["draft_revision"]
    answer = await editor.post(url(ctx, f"/workflows/{wf}/publish"), headers={"If-Match": str(revision)})
    assert answer.status_code == 201, answer.text
    assert [d["message"] for d in answer.json()["warnings"] if d["code"] == "schedule.input_refused"] == [
        schedule_checks.REFUSED.format(n=1, s="")
    ]


async def test_a_schedule_whose_input_cant_be_read_is_counted_unchecked(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """The tenant's key unreadable: validate still answers, the schedules counted unchecked, never refused."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    keyed_app.state.keys = FixtureKeys(missing={str(ctx.tenant_id)})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    assert answer.status_code == 200, answer.text
    assert answer.json()["schedule_breaks"] == []
    assert [d["message"] for d in answer.json()["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=1, s="")
    ]


async def test_the_check_reads_a_bounded_number_of_schedules(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """At most `MAX_CHECKED`, the oldest first; the rest are counted unchecked."""
    monkeypatch.setattr(schedule_checks, "MAX_CHECKED", 2)
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    first = [await scheduled(editor, ctx, wf) for _ in range(3)]
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert [b["schedule_id"] for b in body["schedule_breaks"]] == first[:2]
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=1, s="")
    ]


async def test_a_draft_whose_input_schema_is_wrong_isnt_checked(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """An input schema with an error (here, a type that isn't one) can't be checked against: validate says its error,
    and nothing about the schedules, never a failure of its own."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": {"type": "object", "properties": {"site": {"type": 5}}}})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["valid"] is False and body["schedule_breaks"] == []
    assert not [d for d in body["diagnostics"] if d["code"].startswith("schedule.")]


async def test_publishing_a_csv_draft_warns_at_its_declaration(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    csv = {"columns": [{"header": "Site", "name": "site", "type": "string"}]}
    await drafted(editor, ctx, wf, {"input_schema": SCHEMA, "csv": csv})
    revision = (await editor.get(url(ctx, f"/workflows/{wf}"))).json()["draft_revision"]
    answer = await editor.post(url(ctx, f"/workflows/{wf}/publish"), headers={"If-Match": str(revision)})
    assert answer.status_code == 201, answer.text
    assert [d["field"] for d in answer.json()["warnings"] if d["code"] == "schedule.input_refused"] == ["/settings/csv"]


async def test_validate_reads_nested_fields_references_and_all_of(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """The review of revision 1: a requirement under a reference, or in an `allOf`, breaks every firing as surely as
    one at the root, and validate says so, in the draft's words."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    sid = await scheduled(editor, ctx, wf)
    drafted_schema = {
        "type": "object",
        "properties": {"token": {"type": "string", "x-sensitive": True}, "site": {"$ref": "#/$defs/site"}},
        "$defs": {"site": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}},
        "allOf": [{"required": ["area"]}],
    }
    await drafted(editor, ctx, wf, {"input_schema": drafted_schema})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == [{"schedule_id": sid, "reasons": [
        "`area` is required now.", "`site` must be an object now."], "more": False}]  # fmt: skip
    assert TOKEN not in str(body)


async def test_an_integral_number_fits_a_whole_number(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """The review of revision 1: `2.0` is an integer to JSON Schema and to admission, which stored it; an unchanged
    input never warns about it."""
    floors = SCHEMA | {"properties": SCHEMA["properties"] | {"floor": {"type": "integer"}}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
                              TOKEN_GRAPH | {"settings": {"input_schema": floors}})  # fmt: skip
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf, BODY | {"input": {"token": TOKEN, "floor": 2.0}})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == [] and not [d for d in body["diagnostics"] if d["code"].startswith("schedule.")]


async def test_structure_the_check_cant_read_is_said(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
    """A draft whose input uses structure a shape can't keep (here `not`, and `oneOf`'s one-only rule): the live
    schedules were checked in part, and validate names what wasn't read. No schedule, no warning."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    partly = SCHEMA | {
        "not": {"required": ["site", "area"]},
        "properties": SCHEMA["properties"] | {"site": {"oneOf": [{"type": "string"}, {"const": 1}]}},
    }
    await drafted(editor, ctx, wf, {"input_schema": partly})
    quiet = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert not [d for d in quiet["diagnostics"] if d["code"].startswith("schedule.")]
    await scheduled(editor, ctx, wf)
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == []
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.partly_checked"] == [
        schedule_checks.PARTLY.format(keywords="`not`, `oneOf`")
    ]


async def test_the_schedules_and_their_number_come_from_one_statement(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """The review of revision 1: read apart, a schedule deleted between the rows and their count made the unchecked
    number negative. One statement reads both, in one snapshot."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    seen: list[str] = []

    def on(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        if "FROM schedules" in statement:
            seen.append(statement)

    event.listen(Engine, "before_cursor_execute", on)
    try:
        assert (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).status_code == 200
    finally:
        event.remove(Engine, "before_cursor_execute", on)
    assert len(seen) == 1 and "count(*) OVER ()" in seen[0]


async def test_one_large_input_gives_a_bounded_answer(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """The review of revision 2: a 400 KB stored input (under the 1 MiB request limit) whose 20,000 items all break
    the draft's new item type gave 20,000 reasons, a 909 KB answer for one schedule. Now it gives `MAX_REASONS` and
    says there were more."""
    tagged = SCHEMA | {"properties": SCHEMA["properties"] | {"tags": {"type": "array", "items": {"type": "string"}}}}
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
                              TOKEN_GRAPH | {"settings": {"input_schema": tagged}})  # fmt: skip
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    sid = await scheduled(editor, ctx, wf, BODY | {"input": {"token": TOKEN, "tags": ["abcdefghijklmnopq"] * 20_000}})
    integers = tagged | {"properties": tagged["properties"] | {"tags": {"type": "array", "items": {"type": "integer"}}}}
    await drafted(editor, ctx, wf, {"input_schema": integers})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    (found,) = answer.json()["schedule_breaks"]
    assert (found["schedule_id"], len(found["reasons"]), found["more"]) == (sid, schedule_checks.MAX_REASONS, True)
    assert len(answer.content) < 20_000


async def test_the_stored_input_one_check_reads_is_bounded_in_bytes(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """Counted in sealed bytes, never time: past `MAX_INPUT_BYTES`, the oldest first, the rest are counted unchecked."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    first = await scheduled(editor, ctx, wf)
    await scheduled(editor, ctx, wf)
    async with owner_sessionmaker() as s:
        size = (await s.execute(text("select length(input) from schedules where id = :i"), {"i": first})).scalar_one()
    monkeypatch.setattr(schedule_checks, "MAX_INPUT_BYTES", size + 1)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert [b["schedule_id"] for b in body["schedule_breaks"]] == [first]
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=1, s="")
    ]


async def test_the_check_runs_off_the_event_loop(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """Decoding and checking the stored inputs is CPU work: it runs in a worker thread, never on the event loop."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    threaded: list[str] = []
    real = asyncio.to_thread

    async def recorded(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        threaded.append(getattr(fn, "__name__", ""))
        return await real(fn, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", recorded)
    assert (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()["schedule_breaks"]
    assert "checked_all" in threaded


async def test_past_the_byte_budget_no_stored_input_is_fetched(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """The review of revision 3: the 2 MiB budget was applied after every row's input had been fetched. One statement
    now picks, the oldest first, the schedules whose sealed inputs fit it (by their stored length) and fetches only
    theirs; the others come back as ids, with the live total, in the same snapshot."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    first = await scheduled(editor, ctx, wf)
    second = await scheduled(editor, ctx, wf)
    async with owner_sessionmaker() as s:
        size = (await s.execute(text("select length(input) from schedules where id = :i"), {"i": first})).scalar_one()
        monkeypatch.setattr(schedule_checks, "MAX_INPUT_BYTES", size + 1)
        read = await schedule_checks.read_schedules(s, uuid.UUID(str(wf)))
    assert read.live == 2
    assert [(str(i), sealed is not None) for i, sealed in read.rows] == [(first, True), (second, False)]


async def test_a_check_that_runs_out_of_steps_counts_the_rest_unchecked(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """The step budget, through validate: a check that runs out says how many schedules it didn't check."""
    monkeypatch.setattr(schedule_checks, "MAX_STEPS", 3)
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    await scheduled(editor, ctx, wf)
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == []
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=2, s="s")
    ]


async def test_a_dialect_declared_inside_is_budgeted_through_validate(
    keyed_app, workflow, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """The review of revision 4, through validate: a fitting input beneath a nested `$schema` spends the check's
    steps; when they run out, the schedule is counted unchecked, never silently passed."""
    monkeypatch.setattr(schedule_checks, "MAX_STEPS", 4)
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    await scheduled(editor, ctx, wf)
    dialect = "https://json-schema.org/draft/2020-12/schema"
    nested = SCHEMA | {"properties": {"token": {"$schema": dialect, "type": "string", "x-sensitive": True},
                                      "site": {"$schema": dialect, "type": "string"}}}  # fmt: skip
    await drafted(editor, ctx, wf, {"input_schema": nested})
    body = (await editor.post(url(ctx, f"/workflows/{wf}/validate"))).json()
    assert body["schedule_breaks"] == []
    assert [d["message"] for d in body["diagnostics"] if d["code"] == "schedule.unchecked"] == [
        schedule_checks.UNCHECKED.format(n=1, s="")
    ]


def unchecked(diagnostics: list[dict[str, Any]]) -> list[str]:
    return [d["message"] for d in diagnostics if d["code"] == "schedule.unchecked"]


async def test_a_stored_input_nested_past_the_input_limit_is_a_break_and_publishing_still_succeeds(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """The final review: under a draft whose input recurses through a reference, a stored input nested 300 deep
    raised `RecursionError` out of the check, so validate answered 500, and publish too, its version undone. Since
    issue #88 such an input can't be written (the API refuses it); one stored before (sealed here) is past the input
    limit, which admission refuses at every firing: validate names that schedule a break, publish warns and publishes,
    and nothing is counted unchecked."""
    from dewpoint.apps import schedules

    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings,
                              TOKEN_GRAPH | {"settings": {"input_schema": SCHEMA | {
                                  "properties": SCHEMA["properties"] | {"n": {"type": "object"}}}}})  # fmt: skip
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    schedule_id = await scheduled(editor, ctx, wf)
    deep: dict[str, Any] = {}
    for _ in range(300):
        deep = {"n": deep}
    sealed = await schedules._sealed(KEYS, ctx.tenant_id, uuid.UUID(schedule_id), {"token": TOKEN, "n": deep})
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update schedules set input = :i where id = :id"), {"i": sealed, "id": schedule_id})
    recursive = SCHEMA | {
        "properties": SCHEMA["properties"] | {"n": {"$ref": "#/$defs/n"}},
        "$defs": {"n": {"type": "object", "properties": {"n": {"$ref": "#/$defs/n"}}}},
    }
    await drafted(editor, ctx, wf, {"input_schema": recursive})
    checked = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    assert checked.status_code == 200, checked.text
    assert checked.json()["schedule_breaks"] == [
        {"schedule_id": schedule_id, "reasons": [schedule_checks.TOO_DEEP_STORED], "more": False}
    ]
    assert unchecked(checked.json()["diagnostics"]) == []
    revision = (await editor.get(url(ctx, f"/workflows/{wf}"))).json()["draft_revision"]
    answer = await editor.post(url(ctx, f"/workflows/{wf}/publish"), headers={"If-Match": str(revision)})
    assert answer.status_code == 201, answer.text
    warned = [(d["code"], d["message"]) for d in answer.json()["warnings"] if d["code"].startswith("schedule")]
    assert warned == [("schedule.input_too_deep", schedule_checks.too_deep_schedules(1))]


async def test_a_stored_input_that_doesnt_open_is_counted_unchecked(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """The final review: a sealed input that doesn't open under its tenant and id (a damaged row, or a tenant's data
    keys made again) raised `ClaimUnreadableError` out of the check, and validate and publish answered 500. Like one
    whose key can't be read, it's counted unchecked."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    sid = await scheduled(editor, ctx, wf)
    async with owner_sessionmaker() as s, s.begin():
        sealed = (await s.execute(text("select input from schedules where id = :i"), {"i": sid})).scalar_one()
        await s.execute(text("update schedules set input = :b where id = :i"),
                        {"b": sealed[:-1] + bytes([sealed[-1] ^ 1]), "i": sid})  # fmt: skip
    await drafted(editor, ctx, wf, {"input_schema": BREAKING})
    answer = await editor.post(url(ctx, f"/workflows/{wf}/validate"))
    assert answer.status_code == 200, answer.text
    assert answer.json()["schedule_breaks"] == []
    assert unchecked(answer.json()["diagnostics"]) == [schedule_checks.UNCHECKED.format(n=1, s="")]
