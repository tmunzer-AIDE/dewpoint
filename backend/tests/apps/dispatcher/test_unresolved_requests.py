# SPDX-License-Identifier: Apache-2.0
"""Unresolved requests (2b-4b M4 recovery, task 5; the design's revisions 2 and 3, the owner's rulings 1 to 3).

- Pacing: a spent request left unresolved is described 30 s after it was first noted, then on a doubling gap up to an
  hour (`reconcile.next_look`, which `reconcile_candidates` applies); each look is one error, its recovery item seen
  again, and nothing resolves.
- The owed slot: a late sighting of its live execution, its request settled `started` without its slot, re-reserves it
  even over the tenant's limit, under the run's row lock then the slot's; over the limit, `start_over_limit` is
  recorded and alerted. A terminal one reserves none.
- The late start: a root execution whose request has ended is terminated only on the exact match (the recorded start
  request id on the first run's started event, the request's workflow id, the call naming that run), once, audited,
  alerted and recorded (`late_start`); the blocker becomes `identified`, never gone. A mismatch is alerted only."""

from datetime import timedelta
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio.client import WorkflowExecutionStatus

from dewpoint.apps.dispatcher import dispatch, evidence, reconcile, start_call
from tests.apps.dispatcher.support import begin, reasons
from tests.apps.dispatcher.test_blocker_store import store
from tests.apps.dispatcher.test_blocker_transitions import _landed, _late_started
from tests.apps.dispatcher.test_reconcile import aged, once
from tests.apps.dispatcher.test_start_classification import _sent, _state
from tests.apps.test_admission import admit
from tests.core.erasure.test_fence import erasure_at

pytestmark = pytest.mark.usefixtures("development_deployment")
RETENTION = timedelta(days=1)


async def _spent_unresolved(owner: Any, dsm: Any, settings: Any, request: Any) -> dispatch.Starting:
    """Its sends spent with an attempt unproven: `starting`, without a slot, `start_unresolved` noted."""
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set sends = :n where id = :i"),
                        {"n": start_call.CAP - 1, "i": request.id})  # fmt: skip
    starting = await begin(dsm, request, settings)
    await _sent(owner, request, start_call.CAP, unproven=True)
    assert await dispatch.settle(dsm, starting, dispatch.Outcome("check_unavailable")) == "unresolved"
    return starting


async def _picked(dsm: Any) -> set[Any]:
    async with dsm() as s:
        found = await s.execute(text("select request_id from reconcile_candidates(:g, :r, 50)"),
                                {"g": reconcile.GRACE, "r": reconcile.RECHECK})  # fmt: skip
        return {row.request_id for row in found}


async def _looked(owner: Any, request_id: Any, *, noted_ago: timedelta, looked_ago: timedelta) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set checked_at = now() - cast(:l as interval) where id = :i"),
                        {"l": looked_ago, "i": request_id})  # fmt: skip
        await s.execute(text("update recovery_items set since = now() - cast(:n as interval) where item_id = :i"),
                        {"n": noted_ago, "i": request_id})  # fmt: skip


def test_the_next_look_is_30_seconds_then_doubles_up_to_an_hour() -> None:
    gaps = [reconcile.next_look(None)]
    for _ in range(9):
        gaps.append(reconcile.next_look(gaps[-1]))
    assert [int(g.total_seconds()) for g in gaps] == [30, 60, 120, 240, 480, 960, 1920, 3600, 3600, 3600]


async def test_an_unresolved_spent_request_is_picked_on_the_doubling_schedule(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """After a look whose gap was `previous`, the look before it was `previous` earlier, so the item was noted
    2 x previous - 30 s before the last look (30 s, 60 s, ... after it was noted); the next is due `next_look(previous)`
    after the last, never sooner."""
    _, _, request = queued
    await _spent_unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    await aged(owner_sessionmaker, request.id)
    previous = reconcile.next_look(None)
    for _ in range(8):
        following = reconcile.next_look(previous)
        noted_before_look = 2 * previous - reconcile.RECHECK
        for after, due in ((following - timedelta(seconds=2), False), (following + timedelta(seconds=2), True)):
            await _looked(owner_sessionmaker, request.id, noted_ago=noted_before_look + after, looked_ago=after)
            assert (request.id in await _picked(dispatch_sessionmaker)) is due, (previous, after)
        previous = following


async def test_each_look_is_one_error_its_item_seen_again_and_nothing_resolves(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    await _spent_unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    await aged(owner_sessionmaker, request.id)
    blocker = await store(owner_sessionmaker, request.id)
    seen: list[Any] = []
    for _ in range(3):
        await _looked(owner_sessionmaker, request.id, noted_ago=timedelta(hours=3),
                      looked_ago=timedelta(hours=1, seconds=1))  # fmt: skip
        with structlog.testing.capture_logs() as logs:
            assert await once(dispatch_sessionmaker, env.client, api_settings) == {"unresolved": 1}
            assert await once(dispatch_sessionmaker, env.client, api_settings) == {}  # not due again yet
        assert [e["event"] for e in logs if e["log_level"] == "error"] == ["start_unresolved_at_end"]
        async with owner_sessionmaker() as s:
            last = text("select last_seen_at from recovery_items where item_id = :i and reason = 'start_unresolved'")
            seen.append((await s.execute(last, {"i": request.id})).scalar_one())
    assert seen == sorted(seen) and len(set(seen)) == 3  # it moves
    assert (await _state(owner_sessionmaker, request.id))["status"] == "starting"
    assert set(await reasons(owner_sessionmaker, request.id)) == {"start_unresolved"}
    assert await store(owner_sessionmaker, request.id) == blocker


# --- the owed slot -------------------------------------------------------------------------------------------------


async def _slots(owner: Any, tenant_id: Any) -> list[Any]:
    async with owner() as s:
        return list((await s.execute(text("select run_id from run_slots where tenant_id = :t order by run_id"),
                                     {"t": tenant_id})).scalars())  # fmt: skip


async def test_a_live_late_sighting_reserves_the_owed_slot_even_over_the_limit_and_alerts(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker, api_settings, env
) -> None:
    ctx, wf, request = queued
    starting = await _spent_unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 1) "
                             "on conflict (tenant_id) do update set max_concurrent = 1"),
                        {"t": ctx.tenant_id})  # fmt: skip
    other = (await admit(api_sessionmaker, ctx, wf, key="other")).request
    assert isinstance(await begin(dispatch_sessionmaker, other, api_settings), dispatch.Starting)  # the limit's slot
    handle = await _landed(env, starting, starting.start_request_id)
    try:
        await aged(owner_sessionmaker, request.id)
        with structlog.testing.capture_logs() as logs:
            happened = await once(dispatch_sessionmaker, env.client, api_settings)
        assert happened.get("started") == 1
        assert sorted(await _slots(owner_sessionmaker, ctx.tenant_id)) == sorted([request.id, other.id])  # over it
        assert "start_over_limit" in await reasons(owner_sessionmaker, request.id)
        assert [e["log_level"] for e in logs if e["event"] == "start_over_limit"] == ["error"]
    finally:
        await handle.terminate()


async def test_a_terminal_late_sighting_reserves_no_slot(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    ctx, _, request = queued
    starting = await _spent_unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    handle = await _landed(env, starting, starting.start_request_id)
    await handle.terminate()
    await aged(owner_sessionmaker, request.id)
    assert (await once(dispatch_sessionmaker, env.client, api_settings)).get("started") == 1
    assert await _slots(owner_sessionmaker, ctx.tenant_id) == []
    assert "start_over_limit" not in await reasons(owner_sessionmaker, request.id)


# --- the late start ------------------------------------------------------------------------------------------------


async def _audited(owner: Any, request_id: Any) -> int:
    async with owner() as s:
        return int((await s.execute(text("select count(*) from audit_log where action = 'run.request.late_start' "
                                         "and target_id = :i"), {"i": str(request_id)})).scalar_one())  # fmt: skip


async def test_a_late_start_is_terminated_on_the_exact_match_once_audited_and_recorded(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    first = await _late_started(dispatch_sessionmaker, owner_sessionmaker, request, api_settings)
    handle = await _landed(env, first, first.start_request_id)
    try:
        with structlog.testing.capture_logs() as logs:
            await evidence.check_evidence(dispatch_sessionmaker, env.client, retention=RETENTION)
        assert (await handle.describe()).status == WorkflowExecutionStatus.TERMINATED
        assert [e["log_level"] for e in logs if e["event"] == "late_start"] == ["error"]
        assert await _audited(owner_sessionmaker, request.id) == 1
        assert "late_start" in await reasons(owner_sessionmaker, request.id)
        assert (await store(owner_sessionmaker, request.id))[0] == ("identified", False, handle.first_execution_run_id)
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update execution_evidence set next_check_at = now()"))
        await evidence.check_evidence(dispatch_sessionmaker, env.client, retention=RETENTION)
        assert await _audited(owner_sessionmaker, request.id) == 1  # once
    finally:
        if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
            await handle.terminate()


@pytest.mark.parametrize("fenced", [False, True], ids=["active", "erasure stage 60"])
async def test_a_mismatched_late_start_is_recorded_for_an_operator_never_identified_nor_terminated(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env, fenced: bool
) -> None:
    """The owner's ruling (design revision 2, section D): a live execution of an ended request whose first run's started
    event carries another id is alerted and recorded for an operator, durably: on its blocker (unfenced), and as a
    `late_start_unmatched` item where the erasure's fence allows one. Its blocker is never identified, the execution
    never terminated, and the alert is raised once."""
    _, _, request = queued
    first = await _late_started(dispatch_sessionmaker, owner_sessionmaker, request, api_settings)
    if fenced:
        await erasure_at(owner_sessionmaker, request.tenant_id, 60)
    state_before = (await store(owner_sessionmaker, request.id))[0]
    handle = await _landed(env, first, None)  # its started event carries another request id
    try:
        for visit in range(2):
            with structlog.testing.capture_logs() as logs:
                await evidence.check_evidence(dispatch_sessionmaker, env.client, retention=RETENTION)
            assert (await handle.describe()).status == WorkflowExecutionStatus.RUNNING  # never terminated
            alerts = [e["log_level"] for e in logs if e["event"] == "late_start_unmatched"]
            assert alerts == (["error"] if visit == 0 else []), visit
            async with owner_sessionmaker() as s, s.begin():
                await s.execute(text("update execution_evidence set next_check_at = now()"))
        assert (await store(owner_sessionmaker, request.id))[0] == state_before  # never identified
        assert await _audited(owner_sessionmaker, request.id) == 0
        async with owner_sessionmaker() as s:
            record = (await s.execute(text("select late_start, late_start_at is not null from unresolved_sends "
                                           "where request_id = :r"), {"r": request.id})).one()  # fmt: skip
        assert tuple(record) == ("unmatched", True)
        assert ("late_start_unmatched" in await reasons(owner_sessionmaker, request.id)) is not fenced
    finally:
        await handle.terminate()
