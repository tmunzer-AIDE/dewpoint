# SPDX-License-Identifier: Apache-2.0
"""A run as itself (editor 4e-1; the runs design §4.3, §4.5), `run.view`: what the list says of it, the draft revision
a draft simulation ran, whether its graph records every step instance's end, the run a sub-run was started from, and a
CSV start's file; never its steps, which are read apart, summarized and paged. A cancel's answer, typed."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import step_summary
from dewpoint.engine import ENGINE_ABI
from tests.apps.api.helpers import member_client
from tests.apps.test_admission import TOKEN, admit, current, published
from tests.apps.test_admission_drafts import simulate

pytestmark = pytest.mark.usefixtures("development_deployment")


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def read(app: Any, owner: Any, settings: Any, ctx: Any, run_id: uuid.UUID, role: str = "viewer") -> Any:
    client, _ = await member_client(app, owner, settings, ctx.tenant_id, role)
    return await client.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")


async def test_a_request_shows_what_the_list_says_of_it_and_no_steps(
    app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    request = (await admit(api_sessionmaker, ctx, wf, key="h")).request
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set cancel_requested_at = now() where id = :i"), {"i": request.id})
    answer = await read(app, owner_sessionmaker, api_settings, ctx, request.id)
    assert answer.status_code == 200, answer.text
    run = answer.json()
    assert (run["status"], run["workflow_name"], run["started_by"]) == ("queued", "W", ctx.user.email)
    assert run["trigger"] == {"source": "manual", "schedule": None, "endpoint": None, "rerun_of": None}
    assert run["cancel_requested_at"] is not None
    assert (run["draft_revision"], run["outcomes_recorded"], run["parent"], run["csv"]) == (None, True, None, None)
    assert "steps" not in run and "children" not in run
    assert TOKEN not in answer.text


async def test_a_run_whose_graph_predates_b4b_says_its_ends_arent_all_recorded(
    app, ready, owner_sessionmaker, api_sessionmaker, api_settings, monkeypatch
) -> None:
    ctx, wf = ready
    request = (await admit(api_sessionmaker, ctx, wf, key="h")).request
    monkeypatch.setattr(step_summary, "OUTCOMES_ABI", ENGINE_ABI + 1)  # its graph's ABI, this build's, now older
    assert (await read(app, owner_sessionmaker, api_settings, ctx, request.id)).json()["outcomes_recorded"] is False


async def test_a_draft_simulation_names_the_revision_it_ran(
    app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf = ready
    draft = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN})).request
    run = (await read(app, owner_sessionmaker, api_settings, ctx, draft.id)).json()
    assert (run["mode"], run["draft_revision"]) == ("simulate", 1)
    assert run["draft_snapshot_id"] == str(draft.draft_snapshot_id)


async def test_a_cancel_answers_with_its_request(app, ready, owner_sessionmaker, api_sessionmaker,
                                                api_settings) -> None:  # fmt: skip
    ctx, wf = ready
    request = (await admit(api_sessionmaker, ctx, wf, key="h")).request
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    assert (await viewer.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}/cancel")).status_code == 403
    operator, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
    answer = await operator.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}/cancel")
    assert answer.status_code == 200, answer.text
    assert (answer.json()["cancel"], answer.json()["request"]["status"]) == ("cancelled", "cancelled")
