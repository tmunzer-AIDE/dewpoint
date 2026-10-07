# SPDX-License-Identifier: Apache-2.0
"""Each pass's selection moves on past what it tried (the owner's review of the 2b-4b M1 checkpoint 4): a candidate
function took the first items by its own order, and an item that failed, or came back incomplete, kept its place for
good, so fifty of them kept the fifty-first out; reordering within the fifty taken couldn't help. An item a pass tried
now goes behind those it hasn't (rotation: schedules' syncs, misses reads, cancels, recounts; a backoff for an event
whose match failed). Here each pass takes 2 of 3 items that always fail, and takes the third the next time."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import cancels, matching, recount, schedule_sync
from tests.apps.dispatcher.test_schedule_sync import Leading
from tests.apps.test_admission import KEYS
from tests.core.retention.support import request, run, sql, tenant
from tests.probes.test_leader_calls import _events

pytestmark = pytest.mark.usefixtures("development_deployment")


def unavailable() -> RPCError:
    return RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")


def taken(passes: list[list[Any]]) -> tuple[set[Any], set[Any]]:
    return set(passes[0]), set(passes[0]) | set(passes[1])


async def _schedules(owner: Any, n: int) -> list[uuid.UUID]:
    """`n` schedules of one tenant, each with an incarnation sent an unpause, each waiting for its sync, oldest
    first."""
    ctx = await tenant(owner)
    made = []
    for k in range(n):
        schedule_id = uuid.uuid4()
        await sql(owner, "insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, "
                  "generation, synced_generation, updated_at) values (:i, :t, :w, 3600, 'live', '\\x01', :u, 2, 1, "
                  "now() - make_interval(mins => :ago))", i=schedule_id, t=ctx["t"], w=ctx["w"], u=ctx["u"],
                  ago=10 - k)  # fmt: skip
        await sql(owner, "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, "
                  "unpause_sent_at) values (:i, :t, :s, 1, now())", i=f"t:{ctx['t']}:sched:{schedule_id}~1",
                  t=ctx["t"], s=schedule_id)  # fmt: skip
        made.append(schedule_id)
    return made


async def test_the_sync_takes_a_third_schedule_past_two_that_stay_incomplete(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """Two tombstones `deleting` visit after visit, the oldest changes: the next pass takes the third first."""
    made = await _schedules(owner_sessionmaker, 3)
    passes: list[list[Any]] = [[], []]
    current = [0]

    async def deleting(_s: Any, _c: Any, _l: Any, _t: Any, schedule_id: uuid.UUID) -> str:
        passes[current[0]].append(schedule_id)
        return "deleting"

    monkeypatch.setattr(schedule_sync, "sync_one", deleting)
    for current[0] in (0, 1):
        await schedule_sync.sync_schedules(dispatch_sessionmaker, None, Leading(), batch=2)  # type: ignore[arg-type]
    first, both = taken(passes)
    assert first == set(made[:2]) and both == set(made)


async def test_the_misses_pass_takes_a_third_incarnation_past_two_whose_reads_fail(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    await _schedules(owner_sessionmaker, 3)
    async with owner_sessionmaker() as s:
        ids = list(
            (await s.execute(text("select temporal_id from schedule_incarnations order by temporal_id"))).scalars()
        )
    passes: list[list[Any]] = [[], []]
    current = [0]

    async def failing(_c: Any, temporal_id: str) -> Any:
        passes[current[0]].append(temporal_id)
        raise unavailable()

    monkeypatch.setattr(schedule_sync, "described", failing)
    for current[0] in (0, 1):
        await schedule_sync.check_misses(dispatch_sessionmaker, None, batch=2)  # type: ignore[arg-type]
    first, both = taken(passes)
    assert first == set(ids[:2]) and both == set(ids)


class _Client:
    """A client whose every cancel Temporal doesn't answer: each recorded."""

    def __init__(self, passes: list[list[Any]], current: list[int]) -> None:
        self.passes, self.current = passes, current

    def get_workflow_handle(self, workflow_id: str) -> Any:
        client = self

        class Handle:
            async def cancel(self, **kw: Any) -> None:
                client.passes[client.current[0]].append(workflow_id)
                raise unavailable()

        return Handle()


async def test_the_cancels_pass_takes_a_third_request_past_two_whose_cancels_fail(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx = await tenant(owner_sessionmaker)
    made = []
    for k in range(3):
        rid = await request(owner_sessionmaker, ctx, "started", None)
        await run(owner_sessionmaker, ctx, None, run_id=rid)
        await sql(owner_sessionmaker, "update run_requests set cancel_requested_at = now() - make_interval(mins => :a) "
                  "where id = :i", i=rid, a=10 - k)  # fmt: skip
        made.append(rid)
    passes: list[list[Any]] = [[], []]
    current = [0]
    monkeypatch.setattr(cancels, "BATCH", 2)
    for current[0] in (0, 1):
        await cancels.send_cancels(dispatch_sessionmaker, _Client(passes, current))  # type: ignore[arg-type]
    first, both = taken(passes)
    ids = [f"t:{ctx['t']}:run:{rid}" for rid in made]
    assert first == set(ids[:2]) and both == set(ids)


async def test_the_recount_takes_a_third_tenant_past_two_whose_recounts_fail(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    tenants = []
    for _ in range(3):
        ctx = await tenant(owner_sessionmaker)
        await sql(owner_sessionmaker, "insert into tenant_event_counters (tenant_id) values (:t) "
                  "on conflict do nothing", t=ctx["t"])  # fmt: skip
        tenants.append(ctx["t"])
    await sql(owner_sessionmaker, "update tenant_event_counters set recounted_at = now() where tenant_id <> all(:t)",
              t=tenants)  # fmt: skip  # only these three due
    passes: list[list[Any]] = [[], []]
    current = [0]

    async def failing(_s: Any, tenant_id: uuid.UUID) -> int:
        passes[current[0]].append(tenant_id)
        raise RuntimeError("a recount that fails")

    monkeypatch.setattr(recount, "recount_tenant", failing)
    for current[0] in (0, 1):
        await recount.recount_once(dispatch_sessionmaker, batch=2)
    first, both = taken(passes)
    assert len(first) == 2 and both == set(tenants)


async def test_matching_takes_a_third_event_past_two_whose_matches_fail(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, ingress_sessionmaker,
    api_settings, monkeypatch,
) -> None:  # fmt: skip
    """An event whose match fails unexpectedly (a bug, an outage) waits `ERROR_BACKOFF` before it's tried again, so it
    doesn't keep the events after it out."""
    await _events(3, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                  ingress_sessionmaker, api_settings)  # fmt: skip
    async with owner_sessionmaker() as s:
        ids = list((await s.execute(text("select id from inbound_events order by received_at, id"))).scalars())
    passes: list[list[Any]] = [[], []]
    current = [0]

    async def failing(*_a: Any, event_id: uuid.UUID, **_k: Any) -> str:
        passes[current[0]].append(event_id)
        raise RuntimeError("a match that fails")

    monkeypatch.setattr(matching, "match_event", failing)
    for current[0] in (0, 1):
        await matching.match_once(dispatch_sessionmaker, KEYS, matching.Verified(), batch=2)
    first, both = taken(passes)
    assert first == set(ids[:2]) and both == set(ids)
    assert timedelta(0) < matching.ERROR_BACKOFF
