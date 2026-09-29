# SPDX-License-Identifier: Apache-2.0
"""`GET /runs` pages by (start time, id): `before` and `before_id` name the last run of the previous page, and go
together."""

import uuid

import pytest

from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service
from tests.apps.api.helpers import member_client
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
    params = {"limit": 2, "before": last["started_at"], "before_id": last["id"]}
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
