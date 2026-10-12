# SPDX-License-Identifier: Apache-2.0
"""Schedules through the API (engine 2b spec §8.2; the owner's ruling 9): `trigger.manage` (editors and above) writes
them, `workflow.view` reads them. A schedule's timing is checked against Temporal's own reading of cron, its fixed input
against the active version when written (a tick checks it again), and the input is sealed under `schedule.input`, with
the schedule's id as context, and never shown. A workflow that declares a CSV can't be scheduled. Every change raises
the schedule's generation, which the dispatcher's sync follows; deleting leaves a tombstone, so a late tick still finds
what it belonged to."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.inputs import RESERVED_INPUT
from tests.apps.api.test_run_requests_api import as_role
from tests.apps.test_admission import KEYS, TOKEN, published
from tests.apps.test_admission_csv import GRAPH as CSV_GRAPH

pytestmark = pytest.mark.usefixtures("development_deployment")
BODY = {"cron": "0 9 * * 1-5", "time_zone": "Europe/Paris", "input": {"token": TOKEN, "site": "a"}}


@pytest.fixture
def keyed_app(app: Any) -> Any:
    app.state.keys = KEYS
    return app


@pytest.fixture
async def workflow(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings) -> Any:
    return await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)


def schedules_url(ctx: Any, wf: uuid.UUID) -> str:
    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/schedules"


def schedule_url(ctx: Any, schedule_id: str) -> str:
    return f"/api/v1/t/{ctx.tenant_id}/schedules/{schedule_id}"


async def row(owner: Any, schedule_id: str) -> Any:
    async with owner() as s:
        return (await s.execute(text("select * from schedules where id = :i"), {"i": schedule_id})).mappings().one()


async def audited(owner: Any, action: str) -> list[Any]:
    async with owner() as s:
        found = await s.execute(text("select details from audit_log where action = :a"), {"a": action})
        return list(found.scalars())


async def test_an_editor_schedules_a_workflow_its_input_sealed_and_never_shown(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.post(schedules_url(ctx, wf), json=BODY)
    assert answer.status_code == 201, answer.text
    body = answer.json()
    assert {k: body[k] for k in ("cron", "every_s", "time_zone", "catchup_window_s", "mode", "enabled", "generation",
                                 "synced_generation")} == {
        "cron": "0 9 * * 1-5", "every_s": None, "time_zone": "Europe/Paris", "catchup_window_s": 600, "mode": "live",
        "enabled": True, "generation": 1, "synced_generation": 0,
    }  # fmt: skip
    assert "input" not in body and TOKEN not in answer.text
    stored = await row(owner_sessionmaker, body["id"])
    assert TOKEN.encode() not in stored["input"] and stored["deleted_at"] is None
    assert [d["schedule_id"] for d in await audited(owner_sessionmaker, "schedule.create")] == [body["id"]]
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    listed = (await viewer.get(schedules_url(ctx, wf))).json()
    assert [s["id"] for s in listed["schedules"]] == [body["id"]] and TOKEN not in str(listed)
    assert (await viewer.get(schedule_url(ctx, body["id"]))).json()["id"] == body["id"]


async def test_no_schedule_is_created_before_the_inventorys_cutover(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """The owner's review of checkpoint 4 (M5): on any installation, fresh or upgraded, Compose's or not, the API
    creates no schedule before the inventory's cutover is recorded (`dewpoint schedules inventory-cutover`): one
    created then would be captured as if from before migration 0040, its accounting incomplete for good. It refuses
    (503, `schedule_inventory_not_cut_over`), and creates once the cutover is recorded."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    async with owner_sessionmaker() as s, s.begin():
        kept = (await s.execute(text("delete from schedule_inventory_cutover returning at"))).scalar_one()
    try:
        refused = await editor.post(schedules_url(ctx, wf), json=BODY)
        assert (refused.status_code, refused.json()) == (503, {"error": "schedule_inventory_not_cut_over"})
        async with owner_sessionmaker() as s:
            assert (await s.execute(text("select count(*) from schedules"))).scalar_one() == 0
    finally:
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("insert into schedule_inventory_cutover (at) values (:a)"), {"a": kept})
    assert (await editor.post(schedules_url(ctx, wf), json=BODY)).status_code == 201


async def test_writing_a_schedule_needs_trigger_manage(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
    ctx, wf = workflow
    for role in ("operator", "viewer"):
        client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
        assert (await client.post(schedules_url(ctx, wf), json=BODY)).status_code == 403


@pytest.mark.parametrize(
    ("change", "problems"),
    [
        ({"cron": "0 9 13 * 5"}, [{"field": "cron", "code": "cron_day_fields"}]),
        ({"cron": None, "every_s": 30}, [{"field": "every_s", "code": "interval_too_short"}]),
        ({"time_zone": "Mars/Olympus"}, [{"field": "time_zone", "code": "time_zone_unknown"}]),
        ({"catchup_window_s": 10}, [{"field": "catchup_window_s", "code": "catchup_window"}]),
        ({"offset_s": -1}, [{"field": "offset_s", "code": "interval_offset"}]),  # was a 500: a cron's offset unchecked
        ({"offset_s": 2**31}, [{"field": "offset_s", "code": "interval_offset"}]),
    ],
)
async def test_a_timing_temporal_wouldnt_read_as_written_is_refused(
    keyed_app, workflow, owner_sessionmaker, api_settings, change: dict[str, Any], problems: list[Any]
) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.post(schedules_url(ctx, wf), json=BODY | change)
    assert (answer.status_code, answer.json()) == (422, {"error": "schedule_invalid", "problems": problems})


@pytest.mark.parametrize(
    ("given", "message"),
    [
        ({"token": 7}, None),
        ({"token": TOKEN, "rows": []}, RESERVED_INPUT),
    ],
)
async def test_an_input_the_active_version_refuses_is_refused(
    keyed_app, workflow, owner_sessionmaker, api_settings, given: dict[str, Any], message: str | None
) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    answer = await editor.post(schedules_url(ctx, wf), json=BODY | {"input": given})
    assert (answer.status_code, answer.json()["error"]) == (422, "input_invalid")
    assert message is None or answer.json()["messages"] == [message]
    assert "7" not in answer.json()["messages"][0].split("at ")[-1]


async def test_what_cant_be_scheduled(
    keyed_app, workflow, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    ctx, _ = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    _, other = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    assert (await editor.post(schedules_url(ctx, other), json=BODY)).status_code == 404  # another tenant's
    csv_ctx, csv_wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, CSV_GRAPH)
    csv_editor = await as_role(keyed_app, owner_sessionmaker, api_settings, csv_ctx, "editor")
    answer = await csv_editor.post(schedules_url(csv_ctx, csv_wf), json=BODY)
    assert (answer.status_code, answer.json()) == (409, {"error": "csv_required"})


async def test_every_change_raises_the_generation(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    created = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
    url = schedule_url(ctx, created["id"])
    changed = await editor.patch(url, json={"cron": None, "every_s": 3600, "offset_s": 60})
    assert changed.status_code == 200, changed.text
    assert (changed.json()["cron"], changed.json()["every_s"], changed.json()["generation"]) == (None, 3600, 2)
    disabled = (await editor.patch(url, json={"enabled": False})).json()
    assert (disabled["enabled"], disabled["generation"]) == (False, 3)
    before = (await row(owner_sessionmaker, created["id"]))["input"]
    replaced = (await editor.patch(url, json={"input": {"token": "an0ther-t0ken", "site": "b"}})).json()
    assert replaced["generation"] == 4 and (await row(owner_sessionmaker, created["id"]))["input"] != before
    refused = await editor.patch(url, json={"cron": "@hourly", "every_s": None})
    assert refused.status_code == 422 and (await row(owner_sessionmaker, created["id"]))["generation"] == 4


async def test_deleting_leaves_a_tombstone(keyed_app, workflow, owner_sessionmaker, api_settings) -> None:
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    created = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
    url = schedule_url(ctx, created["id"])
    assert (await editor.delete(url)).status_code == 204
    stone = await row(owner_sessionmaker, created["id"])
    assert stone["deleted_at"] is not None and stone["input"] is None and stone["generation"] == 2
    assert (stone["workflow_id"], stone["mode"]) == (wf, "live")  # what a late tick needs to record its outcome
    assert (await editor.get(url)).status_code == 404
    assert (await editor.patch(url, json={"enabled": True})).status_code == 404
    assert (await editor.delete(url)).status_code == 404
    assert (await editor.get(schedules_url(ctx, wf))).json()["schedules"] == []
    assert [d["schedule_id"] for d in await audited(owner_sessionmaker, "schedule.delete")] == [created["id"]]


@pytest.mark.parametrize("field", ["input", "enabled", "mode", "offset_s", "time_zone", "catchup_window_s"])
async def test_only_the_timings_kind_may_be_patched_to_null(
    keyed_app, workflow, owner_sessionmaker, api_settings, field: str
) -> None:
    """The owner's M3 review: a null for any field but `cron` or `every_s` (which switch the timing's kind) is a 422,
    never a server error, and changes nothing."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    created = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
    answer = await editor.patch(schedule_url(ctx, created["id"]), json={field: None})
    assert (answer.status_code, answer.json()["error"]) == (422, "invalid")
    assert (await row(owner_sessionmaker, created["id"]))["generation"] == 1


async def test_a_schedules_missed_firings_are_counted_only_when_certain_and_its_accounting_says_when_its_incomplete(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """D3f (the owner's ruling, B): `misses` counts what's certain, those Temporal skipped past the catch-up window and
    those due while the schedule, created paused, waited for its first update under one generation; a span the
    evidence can't settle is listed, possibly missed or unknown, with its bounds and its reason, uncounted, as is a wait
    not settled yet (pending: open until the first update lands, then until its count is recorded), and the accounting
    is said incomplete: never a complete-looking zero (2b-4a M4; the owner's reviews)."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    created = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
    assert (created["accounting_complete"], created["uncounted_intervals"]) == (False, [
        {"from": created["created_at"], "to": None, "class": "pending", "reason": "awaiting_first_update"}
    ])  # fmt: skip
    assert created["misses_read_at"] is None  # Temporal's count not read yet
    first = f"t:{ctx.tenant_id}:sched:{created['id']}~1"
    async with owner_sessionmaker() as s, s.begin():  # its first incarnation landed, its wait counted
        await s.execute(
            text("update schedules set misses = 2, creation_misses = 3 where id = :i"),
            {"i": created["id"]},
        )
        await s.execute(
            text(
                "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, generation, "
                "landed_generation, landed_row_generation, landed_at, landed_paused, misses_checked_at) "
                "values (:f, :t, :i, 1, 1, 1, 1, now(), false, now() - interval '1 minute')"
            ),
            {"f": first, "t": ctx.tenant_id, "i": created["id"]},
        )
        await s.execute(
            text(
                "insert into schedule_intervals (tenant_id, schedule_id, temporal_id, kind, starts_at, ends_at, class, "
                "missed, reason) values (:t, :i, :f, 'creation', now() - interval '3 minutes', now(), "
                "'certainly_missed', 3, 'created_paused')"
            ),
            {"f": first, "t": ctx.tenant_id, "i": created["id"]},
        )
        read = (await s.execute(text("select misses_checked_at from schedule_incarnations where temporal_id = :f"),
                                {"f": first})).scalar_one()  # fmt: skip  # its count read a minute ago (D16)
    shown = (await editor.get(schedule_url(ctx, created["id"]))).json()
    assert (shown["misses"], shown["missed_while_created"], shown["accounting_complete"]) == (5, 3, True)
    assert (shown["uncounted_intervals"], shown["misses_read_at"]) == ([], read.isoformat())
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(
            "insert into schedule_intervals (tenant_id, schedule_id, temporal_id, kind, starts_at, ends_at, class, "
            "reason) values (:t, :i, 'x', 'lost', '2026-10-06T08:00:00Z', '2026-10-06T11:00:00Z', 'unknown', "
            "'lost_before_unpause')"), {"t": ctx.tenant_id, "i": created["id"]})  # fmt: skip
    for shown in ((await editor.get(schedule_url(ctx, created["id"]))).json(),
                  (await editor.get(schedules_url(ctx, wf))).json()["schedules"][0]):  # fmt: skip
        assert (shown["misses"], shown["accounting_complete"]) == (5, False)
        assert shown["uncounted_intervals"] == [{"from": "2026-10-06T08:00:00+00:00", "to": "2026-10-06T11:00:00+00:00",
                                                 "class": "unknown", "reason": "lost_before_unpause"}]  # fmt: skip


async def incarnation(owner: Any, ctx: Any, schedule_id: str, number: int, **columns: Any) -> None:
    """A Temporal schedule id the sync recorded for the schedule, as `schedule_incarnations` holds one."""
    values = {"temporal_id": f"t-{schedule_id}-{number}", "tenant_id": ctx.tenant_id, "schedule_id": schedule_id,
              "number": number, "generation": 1} | columns  # fmt: skip
    async with owner() as s, s.begin():
        await s.execute(text(f"insert into schedule_incarnations ({', '.join(values)}) "  # noqa: S608
                             f"values ({', '.join(':' + k for k in values)})"), values)  # fmt: skip


async def test_a_schedule_says_when_its_sync_failed_and_that_nothing_ever_unpaused_it(
    keyed_app, workflow, owner_sessionmaker, api_settings
) -> None:
    """4c-3a ruling 6: the answer says when the sync last failed (an edit doesn't clear a failure, so the editor tells
    an earlier one from the latest edit's), and that nothing ever unpaused it: created paused, only the sync unpauses
    it, recording that first, so with no unpause recorded it has never fired."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    made = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
    assert (made["sync_error"], made["sync_error_at"], made["never_unpaused"]) == (None, None, True)
    await incarnation(owner_sessionmaker, ctx, made["id"], 1)  # recorded, created paused, its unpause not yet sent
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update schedules set sync_error = 'temporal_refused', sync_error_at = now() "
                             "where id = :i"), {"i": made["id"]})  # fmt: skip
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    got = (await viewer.get(schedule_url(ctx, made["id"]))).json()
    stored = await row(owner_sessionmaker, made["id"])
    assert (got["sync_error"], got["sync_error_at"], got["never_unpaused"]) == (
        "temporal_refused", stored["sync_error_at"].isoformat(), True,
    )  # fmt: skip
    listed = (await viewer.get(schedules_url(ctx, wf))).json()["schedules"]
    assert [(s["sync_error_at"], s["never_unpaused"]) for s in listed] == [(stored["sync_error_at"].isoformat(), True)]


@pytest.mark.parametrize(
    "evidence",
    [{"unpause_sent_at": datetime(2026, 10, 10, 8, tzinfo=UTC)}, {"landed_paused": False}, {"backfilled": True}],
    ids=["unpause-sent", "seen-unpaused", "from-before-2b-4a"],
)
async def test_a_schedule_that_may_have_been_unpaused_never_says_otherwise(
    keyed_app, workflow, owner_sessionmaker, api_settings, evidence: dict[str, Any]
) -> None:
    """An unpause sent, an incarnation seen unpaused, or one from before 2b-4a (whose unpauses nobody recorded), on any
    of its incarnations: it may have fired, so `never_unpaused` is false."""
    ctx, wf = workflow
    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
    made = (await editor.post(schedules_url(ctx, wf), json=BODY)).json()
    await incarnation(owner_sessionmaker, ctx, made["id"], 0, **evidence)
    await incarnation(owner_sessionmaker, ctx, made["id"], 1)
    assert (await editor.get(schedule_url(ctx, made["id"]))).json()["never_unpaused"] is False
