# SPDX-License-Identifier: Apache-2.0
"""Schedules through the API (engine 2b spec §8.2; the owner's ruling 9): `trigger.manage` (editors and above) writes
them, `workflow.view` reads them. A schedule's timing is checked against Temporal's own reading of cron, its fixed input
against the active version when written (a tick checks it again), and the input is sealed under `schedule.input`, with
the schedule's id as context, and never shown. A workflow that declares a CSV can't be scheduled. Every change raises
the schedule's generation, which the dispatcher's sync follows; deleting leaves a tombstone, so a late tick still finds
what it belonged to."""

import uuid
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
