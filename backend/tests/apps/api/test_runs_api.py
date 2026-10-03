# SPDX-License-Identifier: Apache-2.0
"""`GET /runs` (engine 2b spec §7.7) lists requests and runs together, newest first by one stable key, `(queued_at,
id)`: a request's `queued_at` is when it was created, its run shares its id and `queued_at`, and a run from before 2b
got `queued_at = started_at`. `before` and `before_id` name the last item of the previous page, and go together. A
request that never started is shown as its request, never as the row an attempt pre-created (§7.3)."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import dispatch
from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service
from tests.apps.api.helpers import member_client
from tests.apps.dispatcher.support import begin, workers
from tests.apps.test_admission import TOKEN, admit, current, published
from tests.apps.test_workflow_ops import actor
from tests.support.workflows import seed_workflow


async def test_the_runs_list_pages_past_runs_that_started_in_the_same_instant(
    app, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx = await actor(owner_sessionmaker)
    _, wf, version = await seed_workflow(owner_sessionmaker, tenant_id=ctx.tenant_id)
    async with dispatch_sessionmaker() as s, s.begin():  # one transaction: now() is one instant
        await tenant_scope(s, ctx.tenant_id)
        for _ in range(3):
            await service.insert_run(
                s, run_id=uuid.uuid4(), tenant_id=ctx.tenant_id, workflow_id=wf, version_id=version, mode="live"
            )
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    first = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params={"limit": 2})).json()
    last = first[-1]
    params = {"limit": 2, "before": last["queued_at"], "before_id": last["id"]}
    rest = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params=params)).json()
    assert len({r["id"] for r in first + rest}) == 3


@pytest.mark.parametrize("half", ["before", "before_id"])
async def test_half_a_cursor_is_refused(app, owner_sessionmaker, api_settings, half: str) -> None:
    """The start time alone would skip runs that started in the same instant; an id alone names no position."""
    ctx = await actor(owner_sessionmaker)
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    value = {"before": "2026-09-28T12:00:00+00:00", "before_id": str(uuid.uuid4())}[half]
    response = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params={half: value})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_cursor"


async def listed(app: Any, owner: Any, settings: Any, ctx: Any) -> tuple[Any, list[dict[str, Any]]]:
    viewer, _ = await member_client(app, owner, settings, ctx.tenant_id, "viewer")
    answer = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")
    assert answer.status_code == 200, answer.text
    return viewer, answer.json()


@pytest.mark.usefixtures("development_deployment")
async def test_requests_and_runs_are_listed_together_newest_first(
    app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    async with owner_sessionmaker() as s:
        version = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
    async with dispatch_sessionmaker() as s, s.begin():  # a run 2a started: no request
        await tenant_scope(s, ctx.tenant_id)
        old = await service.insert_run(s, run_id=uuid.uuid4(), tenant_id=ctx.tenant_id, workflow_id=wf,
                                       version_id=version, mode="live")  # fmt: skip
    first = (await admit(api_sessionmaker, ctx, wf, key="a")).request
    starting = await begin(dispatch_sessionmaker, first, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("started")) == "started"
    queued = (await admit(api_sessionmaker, ctx, wf, key="b")).request
    _, items = await listed(app, owner_sessionmaker, api_settings, ctx)
    assert [i["id"] for i in items] == [str(queued.id), str(first.id), str(old.id)]
    assert (items[0]["status"], items[0]["started_at"], items[0]["request"]) == (
        "queued", None, {"status": "queued", "source": "manual", "reason": None},
    )  # fmt: skip
    assert (items[1]["status"], items[1]["request"]["status"]) == ("running", "started")
    assert items[1]["started_at"] is not None and items[1]["queued_at"] == first.queued_at.isoformat()
    assert items[2]["request"] is None and items[2]["queued_at"] == items[2]["started_at"]
    assert TOKEN not in str(items)


@pytest.mark.usefixtures("development_deployment")
async def test_a_request_that_never_started_is_shown_as_its_request_never_as_its_row(
    app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    request = (await admit(api_sessionmaker, ctx, wf)).request
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("refused")) == "refused"
    viewer, items = await listed(app, owner_sessionmaker, api_settings, ctx)  # its pre-created row is `running`
    assert [(i["id"], i["status"], i["started_at"]) for i in items] == [(str(request.id), "queued", None)]
    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}")).json()
    assert (detail["status"], detail["steps"], detail["children"]) == ("queued", [], [])
    async with owner_sessionmaker() as s, s.begin():  # its backoff over
        await s.execute(text("update run_requests set next_attempt_at = now() where id = :i"), {"i": request.id})
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    _, items = await listed(app, owner_sessionmaker, api_settings, ctx)
    assert items[0]["status"] == "starting"
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("collision")) == "dead"
    _, items = await listed(app, owner_sessionmaker, api_settings, ctx)
    assert (items[0]["status"], items[0]["request"]["reason"]) == ("dead", "id_collision")
