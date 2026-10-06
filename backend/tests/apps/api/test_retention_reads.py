# SPDX-License-Identifier: Apache-2.0
"""At its cutoff, data leaves every user-facing read at once, whatever is still stored (engine 2b spec §10.1; ruling D4:
one filter per kind in the shared read paths, a test per path). A run tree's data is due `runs_days` after its root
ended; a terminal request's and a terminal event's, after they ended. Nothing that hasn't ended is ever past it."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service
from tests.apps.api.test_run_requests_api import as_role
from tests.apps.api.test_webhooks_api import _events, keyed_app, made, tenant, url
from tests.apps.test_admission import current

__all__ = ["keyed_app", "tenant"]  # the webhook tests' fixtures: a published open workflow and the tenant's keypair
pytestmark = pytest.mark.usefixtures("development_deployment")
OLD, RECENT = timedelta(days=2), timedelta(hours=1)  # against a retention of 1 day

REFUSED = (
    "insert into run_requests (id, tenant_id, workflow_id, source, mode, idempotency_key, digest, digest_key_version, "
    "status, reason, queued_at, ended_at) values (:i, :t, :w, 'manual', 'live', :k, :d, 1, 'refused', 'input_invalid', "
    "now() - cast(:ago as interval), now() - cast(:ago as interval))"
)


async def _sql(owner: Any, sql: str, **params: Any) -> None:
    async with owner() as s, s.begin():
        await s.execute(text(sql), params)


async def _ended_run(owner: Any, dispatch: Any, ctx: Any, wf: uuid.UUID, ago: timedelta | None,
                     parent: uuid.UUID | None = None) -> uuid.UUID:  # fmt: skip
    """A run that ended `ago` (or is still running), a sub-run of `parent` when given."""
    run = uuid.uuid4()
    async with owner() as s:
        version = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
    if parent is None:
        async with dispatch() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            await service.insert_run(s, run_id=run, tenant_id=ctx.tenant_id, workflow_id=wf, version_id=version,
                                     mode="live")  # fmt: skip
    else:
        await _sql(owner, "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, kind, "
                   "parent_run_id) values (:r, :t, :w, :v, 'live', 'running', 'subflow', :p)",
                   r=run, t=ctx.tenant_id, w=wf, v=version, p=parent)  # fmt: skip
    if ago is not None:
        await _sql(owner, "update runs set status = 'succeeded', queued_at = now() - cast(:ago as interval) - "
                   "interval '1 minute', ended_at = now() - cast(:ago as interval) where id = :r",
                   r=run, ago=ago)  # fmt: skip
    return run


@pytest.fixture
async def aged(tenant, owner_sessionmaker, dispatch_sessionmaker) -> dict[str, Any]:
    """A tenant whose retention is 1 day, with a run tree, a refused request and so on from 2 days and 1 hour ago."""
    ctx, wf = tenant
    await _sql(
        owner_sessionmaker, "insert into tenant_retention (tenant_id, runs_days) values (:t, 1)", t=ctx.tenant_id
    )
    ids: dict[str, Any] = {"ctx": ctx, "wf": wf}
    for name, ago in (("old", OLD), ("recent", RECENT)):
        root = ids[f"{name}_run"] = await _ended_run(owner_sessionmaker, dispatch_sessionmaker, ctx, wf, ago)
        ids[f"{name}_sub"] = await _ended_run(owner_sessionmaker, dispatch_sessionmaker, ctx, wf, ago, parent=root)
        ids[f"{name}_request"] = uuid.uuid4()
        await _sql(owner_sessionmaker, REFUSED, i=ids[f"{name}_request"], t=ctx.tenant_id, w=wf, k=uuid.uuid4().hex,
                   d=b"\x00" * 32, ago=ago)  # fmt: skip
    ids["running"] = await _ended_run(owner_sessionmaker, dispatch_sessionmaker, ctx, wf, None)  # never past it
    await _sql(owner_sessionmaker, "update runs set queued_at = now() - interval '3 days' where id = :r",
               r=ids["running"])  # fmt: skip
    return ids


async def test_the_runs_list_leaves_out_what_passed_its_cutoff(aged, keyed_app, owner_sessionmaker,
                                                               api_settings) -> None:  # fmt: skip
    ctx = aged["ctx"]
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    listed = {item["id"] for item in (await viewer.get(url(ctx, "/runs"), params={"limit": 200})).json()}
    assert listed == {str(aged[k]) for k in ("recent_run", "recent_request", "running")}


@pytest.mark.parametrize(("name", "found"), [("old_run", False), ("old_sub", False), ("old_request", False),
                                             ("recent_run", True), ("recent_sub", True), ("recent_request", True),
                                             ("running", True)])  # fmt: skip
async def test_a_run_a_sub_run_or_a_request_past_its_cutoff_isnt_found(aged, keyed_app, owner_sessionmaker,
                                                                       api_settings, name: str,
                                                                       found: bool) -> None:  # fmt: skip
    ctx = aged["ctx"]
    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
    answer = await viewer.get(url(ctx, f"/runs/{aged[name]}"))
    assert answer.status_code == (200 if found else 404), answer.text
    if name == "recent_run":  # its sub-runs come with it
        assert [c["id"] for c in answer.json()["children"]] == [str(aged["recent_sub"])]


async def test_a_tenants_retention_applies_to_reads_at_once(aged, keyed_app, owner_sessionmaker,
                                                            api_settings) -> None:  # fmt: skip
    """Reads filter by the cutoff whatever is stored: a longer retention shows again what retention hasn't deleted."""
    ctx = aged["ctx"]
    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
    assert (await admin.get(url(ctx, f"/runs/{aged['old_run']}"))).status_code == 404
    assert (await admin.put(url(ctx, "/retention"), json={"runs_days": 30})).status_code == 200
    assert (await admin.get(url(ctx, f"/runs/{aged['old_run']}"))).status_code == 200


@pytest.mark.parametrize(("name", "status"), [("old_request", 404), ("recent_request", 409)])
async def test_a_cancel_of_a_request_past_its_cutoff_isnt_found(aged, keyed_app, owner_sessionmaker, api_settings,
                                                                name: str, status: int) -> None:  # fmt: skip
    ctx = aged["ctx"]
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "operator")
    assert (await operator.post(url(ctx, f"/runs/{aged[name]}/cancel"))).status_code == status


@pytest.mark.parametrize(("ago", "status"), [(OLD, 410), (RECENT, 202)])
async def test_a_rerun_with_the_original_input_ends_at_the_cutoff(aged, keyed_app, owner_sessionmaker, api_settings,
                                                                  dispatch_sessionmaker, ago: timedelta,
                                                                  status: int) -> None:  # fmt: skip
    """Re-runs with the original input stop at the cutoff (§10.1), even while its claims are still stored; a re-run
    with new input needs none of them."""
    ctx, wf = aged["ctx"], aged["wf"]
    await current(dispatch_sessionmaker)
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "operator")
    started = await operator.post(url(ctx, f"/workflows/{wf}/runs"), json={"input": {"site": "a"}, "mode": "live"},
                                  headers={"Idempotency-Key": "k1"})  # fmt: skip
    assert started.status_code == 202, started.text
    old = started.json()["id"]
    assert (await operator.post(url(ctx, f"/runs/{old}/cancel"))).status_code == 200
    await _sql(owner_sessionmaker, "update run_requests set ended_at = now() - cast(:ago as interval) where id = :i",
               i=old, ago=ago)  # fmt: skip
    again = await operator.post(url(ctx, f"/runs/{old}/rerun"), headers={"Idempotency-Key": "r1"})
    assert again.status_code == status, again.text
    fresh = await operator.post(url(ctx, f"/runs/{old}/rerun"), json={"input": {"site": "b"}},
                                headers={"Idempotency-Key": "r2"})  # fmt: skip
    assert fresh.status_code == 202, fresh.text


async def _aged_events(aged: dict[str, Any], keyed_app: Any, owner: Any, settings: Any,
                       ingress: Any) -> tuple[str, dict[str, uuid.UUID]]:  # fmt: skip
    """An endpoint with events that ended 2 days and 1 hour ago, matched and dead, and one still pending since then."""
    ctx = aged["ctx"]
    endpoint = (await made(keyed_app, owner, settings, ctx))["id"]
    ids: dict[str, uuid.UUID] = dict(zip(("old_matched", "recent_matched", "old_dead", "recent_dead", "pending"),
                                         await _events(ingress, ctx, endpoint, 5), strict=True))  # fmt: skip
    for name, (status, ago) in {"old_matched": ("matched", OLD), "recent_matched": ("matched", RECENT),
                                "old_dead": ("dead", OLD), "recent_dead": ("dead", RECENT)}.items():  # fmt: skip
        await _sql(owner, "update inbound_events set status = :s, reason = 'r', ended_at = now() - cast(:ago as "
                   "interval), received_at = now() - interval '3 days' where id = :i",
                   s=status, ago=ago, i=ids[name])  # fmt: skip
    await _sql(
        owner, "update inbound_events set received_at = now() - interval '3 days' where id = :i", i=ids["pending"]
    )
    return endpoint, ids


async def test_events_past_their_cutoff_leave_the_endpoints_list_and_the_dead_list(
    aged, keyed_app, owner_sessionmaker, api_settings, ingress_sessionmaker
) -> None:
    ctx = aged["ctx"]
    endpoint, ids = await _aged_events(aged, keyed_app, owner_sessionmaker, api_settings, ingress_sessionmaker)
    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
    listed = (await admin.get(url(ctx, f"/webhook-endpoints/{endpoint}/events"))).json()["events"]
    assert {e["id"] for e in listed} == {str(ids[k]) for k in ("recent_matched", "recent_dead", "pending")}
    dead = (await admin.get(url(ctx, "/inbound-events/dead"))).json()["events"]
    assert [e["id"] for e in dead] == [str(ids["recent_dead"])]


@pytest.mark.parametrize(("name", "status"), [("old_dead", 404), ("recent_dead", 200)])
async def test_a_cancel_of_an_event_past_its_cutoff_isnt_found(aged, keyed_app, owner_sessionmaker, api_settings,
                                                               ingress_sessionmaker, name: str,
                                                               status: int) -> None:  # fmt: skip
    ctx = aged["ctx"]
    _, ids = await _aged_events(aged, keyed_app, owner_sessionmaker, api_settings, ingress_sessionmaker)
    admin = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "admin")
    assert (await admin.post(url(ctx, f"/inbound-events/{ids[name]}/cancel"))).status_code == status


async def _ended_long_ago(owner: Any, request_id: str, ago: timedelta) -> None:
    await _sql(owner, "update run_requests set ended_at = now() - cast(:ago as interval) where id = :i",
               i=request_id, ago=ago)  # fmt: skip


@pytest.mark.parametrize(("ago", "status"), [(OLD, 410), (RECENT, 202)])
async def test_an_exact_retry_past_the_cutoff_shows_nothing_and_admits_nothing(
    aged, keyed_app, owner_sessionmaker, dispatch_sessionmaker, api_settings, ago: timedelta, status: int
) -> None:
    """The owner's M2 review: deduplication holds while the request is stored, but its state is past the cutoff."""
    ctx, wf = aged["ctx"], aged["wf"]
    await current(dispatch_sessionmaker)
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "operator")
    start = {"json": {"input": {"site": "a"}, "mode": "live"}, "headers": {"Idempotency-Key": "k1"}}
    first = (await operator.post(url(ctx, f"/workflows/{wf}/runs"), **start)).json()
    assert (await operator.post(url(ctx, f"/runs/{first['id']}/cancel"))).status_code == 200
    await _ended_long_ago(owner_sessionmaker, first["id"], ago)
    again = await operator.post(url(ctx, f"/workflows/{wf}/runs"), **start)
    assert again.status_code == status, again.text
    if status == 410:
        assert again.json() == {"error": "request_not_retained"}
    else:
        assert again.json()["id"] == first["id"]
    async with owner_sessionmaker() as s:
        keyed = (await s.execute(text("select count(*) from run_requests where idempotency_key = 'k1'"))).scalar()
    assert keyed == 1


async def test_an_exact_rerun_retry_past_the_cutoff_shows_nothing(
    aged, keyed_app, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf = aged["ctx"], aged["wf"]
    await current(dispatch_sessionmaker)
    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "operator")
    old = (await operator.post(url(ctx, f"/workflows/{wf}/runs"), json={"input": {"site": "a"}},
                               headers={"Idempotency-Key": "k1"})).json()  # fmt: skip
    rerun = (await operator.post(url(ctx, f"/runs/{old['id']}/rerun"), headers={"Idempotency-Key": "r1"})).json()
    assert (await operator.post(url(ctx, f"/runs/{rerun['id']}/cancel"))).status_code == 200
    await _ended_long_ago(owner_sessionmaker, rerun["id"], OLD)
    again = await operator.post(url(ctx, f"/runs/{old['id']}/rerun"), headers={"Idempotency-Key": "r1"})
    assert (again.status_code, again.json()) == (410, {"error": "request_not_retained"})
