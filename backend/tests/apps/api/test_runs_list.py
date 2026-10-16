# SPDX-License-Identifier: Apache-2.0
"""The runs list's filters and labels (editor 4e-1, B10; the runs design §4.2): by status, over a run's status or an
unstarted request's (`waiting`, `didnt_start` grouping two each); by mode, draft simulations (left out by default),
source and `since`, the cursor paging under them. Each item names its workflow, the email of the person who asked, a
requested cancel, and where it came from: the schedule's timing, the endpoint's name, the run a re-run repeats."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import admission
from dewpoint.apps.dispatcher import dispatch as dispatch_module
from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service
from tests.apps.api.helpers import member_client
from tests.apps.dispatcher.inbound import endpoint
from tests.apps.dispatcher.support import begin, workers
from tests.apps.test_admission import TOKEN, admit, current, published
from tests.apps.test_admission_drafts import simulate
from tests.apps.test_admission_origins import schedule

pytestmark = pytest.mark.usefixtures("development_deployment")


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    async with owner_sessionmaker() as s:
        version = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
    return ctx, wf, version


async def requested(api: Any, ctx: Any, wf: uuid.UUID, key: str, **request: Any) -> uuid.UUID:
    """A request under `key`, as admission left it."""
    return (await admit(api, ctx, wf, key=key, **request)).request.id  # type: ignore[no-any-return]


async def moved(api: Any, owner: Any, dispatch: Any, settings: Any, ctx: Any, wf: uuid.UUID, key: str,
                status: str) -> uuid.UUID:  # fmt: skip
    """A request the dispatcher moved on, as it does: `starting`, `dead`, or `started` and its run `running`; or one
    cancelled before it started."""
    r = (await admit(api, ctx, wf, key=key)).request
    if status == "cancelled":
        async with owner() as s, s.begin():
            await s.execute(text("update run_requests set status = 'cancelled', ended_at = now() where id = :i"),
                            {"i": r.id})  # fmt: skip
        return r.id  # type: ignore[no-any-return]
    starting = await begin(dispatch, r, settings)
    if status != "starting":
        outcome = {"dead": "collision", "started": "started"}[status]
        await dispatch_module.settle(dispatch, starting, dispatch_module.Outcome(outcome))
    return r.id  # type: ignore[no-any-return]


async def ran(api: Any, owner: Any, dispatch: Any, settings: Any, ctx: Any, wf: uuid.UUID, key: str,
              status: str) -> uuid.UUID:  # fmt: skip
    """A request that started a run, which is at `status`: ended as a run ends, its slot given back."""
    request_id = await moved(api, owner, dispatch, settings, ctx, wf, key, "started")
    if status != "running":
        async with dispatch() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            await service.finish_run(s, request_id, status=status, ended_at=datetime.now(UTC))
    return request_id


async def listed(app: Any, owner: Any, settings: Any, ctx: Any, **params: Any) -> list[dict[str, Any]]:
    viewer, _ = await member_client(app, owner, settings, ctx.tenant_id, "viewer")
    answer = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params=params)
    assert answer.status_code == 200, answer.text
    return list(answer.json())


async def test_each_status_filter_picks_its_runs_and_unstarted_requests(
    app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, _ = ready
    await workers(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():  # room for every run this test starts at once
        await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 20)"),
                        {"t": ctx.tenant_id})  # fmt: skip
    made: dict[str, uuid.UUID] = {}
    for status in ("succeeded", "failed", "deadline_exceeded", "cancelled", "running"):  # one slot held at a time
        made[f"run {status}"] = await ran(api_sessionmaker, owner_sessionmaker, dispatch_sessionmaker, api_settings,
                                          ctx, wf, f"x-{status}", status)  # fmt: skip
    for status in ("dead", "starting", "cancelled"):
        made[f"request {status}"] = await moved(api_sessionmaker, owner_sessionmaker, dispatch_sessionmaker,
                                                api_settings, ctx, wf, f"r-{status}", status)  # fmt: skip
    made["request queued"] = await requested(api_sessionmaker, ctx, wf, "r-queued")
    made["request refused"] = await requested(api_sessionmaker, ctx, wf, "r-refused", source="schedule",
                                              input={"token": 7})  # fmt: skip
    expected = {
        "waiting": {"request queued", "request starting"},
        "running": {"run running"},
        "succeeded": {"run succeeded"},
        "failed": {"run failed"},
        "deadline_exceeded": {"run deadline_exceeded"},
        "cancelled": {"request cancelled", "run cancelled"},
        "didnt_start": {"request dead", "request refused"},
    }
    for status, names in expected.items():
        found = {i["id"] for i in await listed(app, owner_sessionmaker, api_settings, ctx, status=status)}
        assert found == {str(made[n]) for n in names}, status
    assert len(await listed(app, owner_sessionmaker, api_settings, ctx)) == len(made)


async def test_mode_source_and_since_filter_and_the_cursor_pages_under_them(
    app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf, _ = ready
    live = [await requested(api_sessionmaker, ctx, wf, f"l{n}") for n in range(3)]
    simulated = await requested(api_sessionmaker, ctx, wf, "s", mode="simulate")
    rerun = await requested(api_sessionmaker, ctx, wf, "rr", source="rerun",
                            rerun=admission.Rerun(of=live[0], input={"token": TOKEN}))  # fmt: skip
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set queued_at = now() - interval '2 days' where id = :i"),
                        {"i": live[0]})  # fmt: skip
        since = (await s.execute(text("select now() - interval '1 day'"))).scalar()

    def ids(items: list[dict[str, Any]]) -> set[str]:
        return {i["id"] for i in items}

    assert ids(await listed(app, owner_sessionmaker, api_settings, ctx, mode="simulate")) == {str(simulated)}
    assert ids(await listed(app, owner_sessionmaker, api_settings, ctx, source="rerun")) == {str(rerun)}
    recent = await listed(app, owner_sessionmaker, api_settings, ctx, since=since.isoformat())
    assert ids(recent) == {str(live[1]), str(live[2]), str(simulated), str(rerun)}
    first = await listed(app, owner_sessionmaker, api_settings, ctx, mode="live", source="manual", limit=2)
    last = first[-1]
    rest = await listed(app, owner_sessionmaker, api_settings, ctx, mode="live", source="manual", limit=2,
                        before=last["queued_at"], before_id=last["id"])  # fmt: skip
    assert [i["id"] for i in first + rest] == [str(i) for i in reversed(live)]


async def test_draft_simulations_are_left_out_unless_asked_for(
    app, ready, owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    ctx, wf, _ = ready
    published_run = await requested(api_sessionmaker, ctx, wf, "p")
    draft = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN})).request.id

    async def ids(**params: Any) -> list[str]:
        return [i["id"] for i in await listed(app, owner_sessionmaker, api_settings, ctx, **params)]

    assert await ids() == [str(published_run)]
    assert await ids(draft="only") == [str(draft)]
    assert await ids(draft="include") == [str(draft), str(published_run)]


async def test_an_item_names_its_workflow_who_asked_a_requested_cancel_and_where_it_came_from(
    app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, _ = ready
    by_hand = await requested(api_sessionmaker, ctx, wf, "h")
    rerun = await requested(api_sessionmaker, ctx, wf, "r", source="rerun",
                            rerun=admission.Rerun(of=by_hand, input={"token": TOKEN}))  # fmt: skip
    schedule_id = await schedule(api_sessionmaker, ctx, wf)
    ticked = await requested(api_sessionmaker, ctx, wf, "t", source="schedule",
                             trigger_id=schedule_id)  # fmt: skip
    endpoint_id = await endpoint(owner_sessionmaker, ctx.tenant_id, ctx.user.id)
    hooked = await requested(api_sessionmaker, ctx, wf, "w", source="webhook",
                             trigger_id=endpoint_id)  # fmt: skip
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set cancel_requested_at = now() where id = :i"), {"i": by_hand})
    items = {i["id"]: i for i in await listed(app, owner_sessionmaker, api_settings, ctx)}
    assert {i["workflow_name"] for i in items.values()} == {"W"}
    hand = items[str(by_hand)]
    assert (hand["started_by"], hand["cancel_requested_at"] is not None) == (ctx.user.email, True)
    assert hand["trigger"] == {"source": "manual", "schedule": None, "endpoint": None, "rerun_of": None}
    assert items[str(rerun)]["trigger"]["rerun_of"] == str(by_hand)
    assert items[str(ticked)]["started_by"] is None
    assert items[str(ticked)]["trigger"]["schedule"] == {"cron": "0 9 * * *", "every_s": None, "offset_s": 0,
                                                         "time_zone": "UTC"}  # fmt: skip
    assert items[str(hooked)]["trigger"]["endpoint"] == "hooks"
    async with owner_sessionmaker() as s, s.begin():  # a deleted schedule, and a request from before 0073
        await s.execute(text("update schedules set deleted_at = now(), input = null where id = :i"), {"i": schedule_id})
        await s.execute(text("update run_requests set trigger_id = null where id = :i"), {"i": hooked})
    items = {i["id"]: i for i in await listed(app, owner_sessionmaker, api_settings, ctx)}
    assert items[str(ticked)]["trigger"] == {"source": "schedule", "schedule": None, "endpoint": None, "rerun_of": None}
    assert items[str(hooked)]["trigger"] == {"source": "webhook", "schedule": None, "endpoint": None, "rerun_of": None}


@pytest.mark.parametrize("params", [{"status": "awaiting_approval"}, {"draft": "yes"}, {"source": "import"}])
async def test_an_unknown_filter_value_is_refused(app, ready, owner_sessionmaker, api_settings, params) -> None:
    ctx, _, _ = ready
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    assert (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params=params)).status_code == 422
