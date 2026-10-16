# SPDX-License-Identifier: Apache-2.0
"""A run's steps, for every run (editor 4e-1; the runs design §4.4), `run.view`: the summary per step of the graph it
ran, in run order, with a live run's origins (`may_have_been_sent` before `sent`; nothing for a control step, or a
plugin step that sent nothing) and `not_recorded` where its graph's engine predates B4b; a step's instances, paged,
each naming the sub-run it started; one instance's attempts, first to last, at most a retry policy's most."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import step_summary
from dewpoint.apps.dispatcher import dispatch as dispatch_module
from tests.apps.api.test_run_requests_api import as_role, keyed_app
from tests.apps.api.test_simulation_steps import LOOPED, ended, row
from tests.apps.dispatcher.support import begin, workers
from tests.apps.test_admission import admit, current, published
from tests.apps.test_admission_drafts import drafted, simulate
from tests.support.graphs import nid

pytestmark = pytest.mark.usefixtures("development_deployment")
__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys


def steps(ctx: Any, run_id: uuid.UUID, step: str | None = None, read: str = "instances") -> str:
    base = f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}/steps"
    return base if step is None else f"{base}/{nid(step)}/{read}"


async def started(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any, mode: str = "live") -> Any:
    """A published LOOPED run in `mode`, started, still running, with no step rows yet."""
    await current(dispatch)
    ctx, wf = await published(owner, api, admin, settings, LOOPED)
    request = (await admit(api, ctx, wf, mode=mode, input={})).request
    await workers(owner)
    starting = await begin(dispatch, request, settings)
    assert await dispatch_module.settle(dispatch, starting, dispatch_module.Outcome("started")) == "started"
    return ctx, request.id


@pytest.fixture
async def live(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    return await started(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)


async def origins(client: Any, ctx: Any, run_id: uuid.UUID) -> dict[str, Any]:
    answer = await client.get(steps(ctx, run_id))
    assert answer.status_code == 200, answer.text
    return {s["key"]: s["origin"] for s in answer.json()["steps"]}


async def test_a_live_runs_origins_say_what_was_sent_and_nothing_of_control_steps(
    keyed_app, live, owner_sessionmaker, api_settings
) -> None:
    ctx, run_id = live
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    assert set((await origins(viewer, ctx, run_id)).values()) == {"not_reached_yet"}
    await row(owner_sessionmaker, ctx, run_id, "l", "", 1, "succeeded", at=1)
    await row(owner_sessionmaker, ctx, run_id, "c", "l:0", 1, "succeeded", at=2, port="true")
    await row(owner_sessionmaker, ctx, run_id, "x", "l:0", 1, "failed", at=3)  # it sent nothing
    await row(owner_sessionmaker, ctx, run_id, "x", "l:0", 2, "succeeded", at=4, outcome="applied")
    await row(owner_sessionmaker, ctx, run_id, "d", "", 1, "succeeded", at=5)  # waited: a live run's timer
    await ended(owner_sessionmaker, run_id)
    assert await origins(viewer, ctx, run_id) == {"l": None, "c": None, "x": "sent", "d": None, "t": "didnt_run"}
    await row(owner_sessionmaker, ctx, run_id, "x", "l:1", 1, "cancelled", at=6, outcome="outcome_unknown")
    assert (await origins(viewer, ctx, run_id))["x"] == "may_have_been_sent"  # whatever became of the others


async def test_a_plugin_step_that_sent_nothing_has_no_origin(keyed_app, live, owner_sessionmaker, api_settings) -> None:
    ctx, run_id = live
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    await row(owner_sessionmaker, ctx, run_id, "x", "l:0", 1, "failed", at=3)
    await ended(owner_sessionmaker, run_id, "failed", "boom")
    assert (await origins(viewer, ctx, run_id))["x"] is None


async def test_a_simulated_runs_origins_are_the_simulations(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, run_id = await started(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                                api_settings, mode="simulate")  # fmt: skip
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    await row(owner_sessionmaker, ctx, run_id, "x", "l:0", 1, "succeeded", at=3, outcome="simulated")
    await row(owner_sessionmaker, ctx, run_id, "d", "", 1, "succeeded", at=5, outcome="simulated")
    await ended(owner_sessionmaker, run_id)
    found = await origins(viewer, ctx, run_id)
    assert (found["x"], found["d"], found["t"]) == ("fixture_not_sent", "evaluated_not_waited", "didnt_run")


async def test_a_step_with_no_row_is_not_recorded_when_its_graph_predates_b4b(
    keyed_app, live, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    ctx, run_id = live
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    await row(owner_sessionmaker, ctx, run_id, "l", "", 1, "succeeded", at=1)
    await ended(owner_sessionmaker, run_id)
    monkeypatch.setattr(step_summary, "OUTCOMES_ABI", step_summary.OUTCOMES_ABI + 1)  # its graph's ABI, now older
    assert (await origins(viewer, ctx, run_id))["t"] == "not_recorded"
    monkeypatch.undo()
    assert (await origins(viewer, ctx, run_id))["t"] == "didnt_run"


async def sub_run(owner: Any, parent: uuid.UUID, step: str, iteration: str) -> uuid.UUID:
    """A sub-run the parent's step instance started, as the worker writes one."""
    child = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(text(
            "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, started_at, "
            "ended_at, kind, parent_run_id, root_run_id, parent_step_id, parent_iteration_key) "
            "select :c, tenant_id, workflow_id, workflow_version_id, mode, 'succeeded', queued_at, started_at, now(), "
            "'subflow', id, root_run_id, :s, :k from runs where id = :p"
        ), {"c": child, "p": parent, "s": nid(step), "k": iteration})  # fmt: skip
    return child


async def test_a_steps_instances_are_paged_each_naming_the_sub_run_it_started(
    keyed_app, live, owner_sessionmaker, api_settings
) -> None:
    ctx, run_id = live
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    for i in range(5):
        await row(owner_sessionmaker, ctx, run_id, "x", f"l:{i}", 1, "succeeded", at=3, outcome="applied")
    child = await sub_run(owner_sessionmaker, run_id, "x", "l:3")
    first = (await viewer.get(steps(ctx, run_id, "x"), params={"limit": 2})).json()
    assert first["total"] == 5 and [i["iteration_key"] for i in first["items"]] == ["l:0", "l:1"]
    page = (await viewer.get(steps(ctx, run_id, "x"), params={"offset": 2, "limit": 2})).json()
    assert [(i["iteration_key"], i["child_run_id"]) for i in page["items"]] == [("l:2", None), ("l:3", str(child))]
    assert (await viewer.get(steps(ctx, run_id, "nope"))).status_code == 404


async def test_one_instances_attempts_come_first_to_last_at_most_a_retry_policys_most(
    keyed_app, live, owner_sessionmaker, api_settings
) -> None:
    ctx, run_id = live
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    for attempt in range(1, step_summary.ATTEMPTS + 2):
        await row(owner_sessionmaker, ctx, run_id, "x", "l:0", attempt, "failed", at=attempt)
    await row(owner_sessionmaker, ctx, run_id, "d", "", 1, "succeeded", at=1)
    answer = (await viewer.get(steps(ctx, run_id, "x", "attempts"), params={"iteration": "l:0"})).json()
    assert [a["attempt"] for a in answer["items"]] == list(range(1, step_summary.ATTEMPTS + 1))
    outside = (await viewer.get(steps(ctx, run_id, "d", "attempts"))).json()  # outside a loop: no iteration
    assert [(a["iteration_key"], a["attempt"]) for a in outside["items"]] == [("", 1)]


async def test_a_request_that_hasnt_started_has_steps_that_havent_run(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    await current(dispatch_sessionmaker)
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, LOOPED)
    request = (await admit(api_sessionmaker, ctx, wf, input={})).request
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    assert set((await origins(viewer, ctx, request.id)).values()) == {"not_reached_yet"}
    assert (await viewer.get(steps(ctx, request.id, "x"))).json() == {"total": 0, "items": []}


async def test_a_draft_simulation_reads_the_same_through_the_runs_route(
    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    await current(dispatch_sessionmaker)
    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOPED)
    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    through_runs = (await viewer.get(steps(ctx, request.id))).json()
    through_drafts = (await viewer.get(
        f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/simulations/{request.id}/steps")).json()  # fmt: skip
    assert through_runs == through_drafts


async def test_another_tenants_run_isnt_found(keyed_app, live, owner_sessionmaker, api_sessionmaker, api_settings,
                                              admin_sessionmaker) -> None:  # fmt: skip
    _, run_id = live
    other, _ = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, other, "viewer")
    for path in (steps(other, run_id), steps(other, run_id, "x"), steps(other, run_id, "x", "attempts")):
        assert (await viewer.get(path)).status_code == 404
