# SPDX-License-Identifier: Apache-2.0
"""Cancels (engine 2b spec §7.7, §7.8): a queued request is cancelled at once, audited, with the row an earlier attempt
wrote; a `starting` one has its cancel recorded and applied when the start resolves (`cancelled` if it didn't start,
sent to Temporal if it did); a started run's cancel is recorded and the dispatcher sends it, once, so the API needs no
Temporal client. The API ends a run's row only for a request it cancelled."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.api.enums.v1 import EventType

from dewpoint.apps import cancels
from dewpoint.apps.dispatcher import cancels as sending
from dewpoint.apps.dispatcher import dispatch
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.support import begin, state

pytestmark = pytest.mark.usefixtures("development_deployment")


async def cancel(api: Any, ctx: Any, request_id: uuid.UUID) -> str:
    async with api() as s, s.begin():
        return await cancels.cancel_request(s, tenant_id=ctx.tenant_id, request_id=request_id, actor_id=ctx.user.id)


async def audited(owner: Any, action: str) -> list[Any]:
    async with owner() as s:
        rows = await s.execute(
            text("select target_id, actor_id, details from audit_log where action = :a order by seq"), {"a": action}
        )
        return [tuple(r) for r in rows]


async def row(owner: Any, run_id: uuid.UUID) -> tuple[Any, ...] | None:
    async with owner() as s:
        found = (await s.execute(text("select status, error_code from runs where id = :i"), {"i": run_id})).first()
        return tuple(found) if found else None


async def starting(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
    found = await begin(dispatch_sessionmaker, request, settings)
    assert isinstance(found, dispatch.Starting)
    return found


async def test_a_queued_request_is_cancelled_at_once(
    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, request = queued
    assert await cancel(api_sessionmaker, ctx, request.id) == "cancelled"
    assert await state(owner_sessionmaker, request.id) == {
        "request": ("cancelled", "user_cancelled", 0), "run": None, "slot": 0,
    }  # fmt: skip
    assert await audited(owner_sessionmaker, "run.request.cancel") == [
        (str(request.id), ctx.user.id, {"reason": "user_cancelled"})
    ]
    assert await begin(dispatch_sessionmaker, request, api_settings) is None  # never dispatched


async def test_a_queued_requests_row_from_an_earlier_attempt_ends_with_it(
    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome("refused")) == "refused"
    assert await row(owner_sessionmaker, request.id) == ("running", None)  # kept, hidden behind the request
    assert await cancel(api_sessionmaker, ctx, request.id) == "cancelled"
    assert await row(owner_sessionmaker, request.id) == ("cancelled", "user_cancelled")


async def test_the_api_ends_no_row_but_a_cancelled_requests(
    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """The API holds no write on `runs`: `end_unstarted_run` ends a row only when its request is `cancelled`."""
    ctx, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome("started")) == "started"
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await s.execute(text("select end_unstarted_run(:i)"), {"i": request.id})
    assert await row(owner_sessionmaker, request.id) == ("running", None)


@pytest.mark.parametrize("outcome", ["refused", "throttled", "absent"])
async def test_a_starting_requests_cancel_is_applied_when_it_doesnt_start(
    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, outcome
) -> None:
    ctx, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    assert await cancel(api_sessionmaker, ctx, request.id) == "requested"
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"  # recorded, not yet applied
    assert await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome(outcome)) == "cancelled"
    after = await state(owner_sessionmaker, request.id)
    assert after["request"][:2] == ("cancelled", "user_cancelled") and after["slot"] == 0
    assert await row(owner_sessionmaker, request.id) == ("cancelled", "user_cancelled")
    assert [a[0] for a in await audited(owner_sessionmaker, "run.cancel.requested")] == [str(request.id)]


async def test_a_started_runs_cancel_is_sent_to_temporal_once(
    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    ctx, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    assert await cancel(api_sessionmaker, ctx, request.id) == "requested"  # while starting
    assert await dispatch.settle(dispatch_sessionmaker, lost, await dispatch.start(env.client, lost)) == "started"
    assert await sending.send_cancels(dispatch_sessionmaker, env.client) == {"sent": 1}
    assert await sending.send_cancels(dispatch_sessionmaker, env.client) == {}
    handle = env.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), str(request.id)))
    kinds = [e.event_type async for e in handle.fetch_history_events()]
    assert EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCEL_REQUESTED in kinds


async def test_a_running_runs_cancel_is_recorded_for_the_dispatcher(
    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    ctx, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, lost, await dispatch.start(env.client, lost)) == "started"
    assert await cancel(api_sessionmaker, ctx, request.id) == "requested"
    assert await cancel(api_sessionmaker, ctx, request.id) == "requested"  # again: one request, one audit entry
    assert len(await audited(owner_sessionmaker, "run.cancel.requested")) == 1
    assert await sending.send_cancels(dispatch_sessionmaker, env.client) == {"sent": 1}


@pytest.mark.parametrize("ended", ["cancelled", "dead", "run_ended"])
async def test_an_ended_request_has_nothing_to_cancel(
    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings, ended
) -> None:
    ctx, _, request = queued
    if ended == "cancelled":
        await cancel(api_sessionmaker, ctx, request.id)
    else:
        lost = await starting(dispatch_sessionmaker, request, api_settings)
        outcome = "collision" if ended == "dead" else "started"
        await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome(outcome))
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update runs set status = 'succeeded', ended_at = now() where id = :i"),
                            {"i": request.id})  # fmt: skip
    assert await cancel(api_sessionmaker, ctx, request.id) == "ended"


async def test_another_tenants_request_cant_be_cancelled(
    queued, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    from tests.apps.test_admission import published

    _, _, request = queued
    other, _ = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    with pytest.raises(cancels.RequestNotFoundError):
        await cancel(api_sessionmaker, other, request.id)
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "queued"
