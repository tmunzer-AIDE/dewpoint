# SPDX-License-Identifier: Apache-2.0
"""A schedule's items bounded however many Temporal ids it was recorded under (the owner's D16 ruling on the 2b-4b M1
checkpoint; `EARLIER`, an experimental cap, not a time budget): the sync checks at most `EARLIER` earlier incarnations
a visit for a late create, and a tombstone pauses, counts and deletes at most 1 + `EARLIER` a visit, until none is
left; the stray pass reaches every earlier one each hour. Misses keep their five-minute accounting for every
incarnation that may still miss a firing (unpaused once, or from before the migration) until it's verified paused for
its delete, its count recorded, or gone: each is its own item, one describe; the API shows the accounting stale when
one wasn't read within those five minutes. Counted in calls, against the dev server. Under the passes' soft budget
(the owner's D16 review of checkpoint 3): each item's calls at most its pass's (`budget.CALLS`) on its longest path; a
slow call ends a pass's admission once its item ends, and the next passes take the rest; a pass stopped by a slow item
takes another first next time (slowness injected on the SDK's RPC path, beneath the budget's own timing)."""

import asyncio
import contextlib
import math
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import schedules
from dewpoint.apps.dispatcher import budget, schedule_sync
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import schedule_workflow_id
from tests.apps.dispatcher.test_leader_deadlines import recorded
from tests.apps.dispatcher.test_schedule_sync import TIMING, Leading, incarnations, sync
from tests.apps.test_admission import KEYS, TOKEN, current, published
from tests.core.retention.support import sql
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = pytest.mark.usefixtures("development_deployment")
QUEUE = "bounded-items-nowhere"


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    """A tenant's schedule, enabled: its context, its workflow, its id."""
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        created = await schedules.create(s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
                                         timing=TIMING, mode="live", input={"token": TOKEN}, enabled=True)  # fmt: skip
    return ctx, wf, created.id


@pytest.fixture(autouse=True)
def _owner(owner_sessionmaker: Any) -> Any:
    from tests.apps.dispatcher import test_schedule_sync

    test_schedule_sync.OWNER[:] = [owner_sessionmaker]
    yield
    test_schedule_sync.OWNER.clear()


async def recorded_earlier(owner: Any, ctx: Any, schedule_id: uuid.UUID, n: int, *, unpaused: bool) -> list[str]:
    """`n` later incarnations recorded for the schedule that never landed; `unpaused`: each sent an unpause once (so
    each may have fired). Their ids."""
    made = []
    async with owner() as s, s.begin():
        last = (await s.execute(text("select max(number) from schedule_incarnations where schedule_id = :s"),
                                {"s": schedule_id})).scalar_one()  # fmt: skip
        for number in range(last + 1, last + 1 + n):
            temporal_id = schedule_sync.incarnation_id(ctx.tenant_id, schedule_id, number)
            values = {"i": temporal_id, "t": ctx.tenant_id, "s": schedule_id, "n": number, "u": unpaused}
            await s.execute(
                text(
                    "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, "
                    "unpause_sent_at) values (:i, :t, :s, :n, case when :u then now() end)"
                ),
                values,
            )
            made.append(temporal_id)
    return made


async def landed_late(server: Any, temporal_id: str) -> None:
    """A create of `temporal_id` that landed late: paused, as every create is."""
    action = ScheduleActionStartWorkflow("Nothing", id=f"{temporal_id}-tick", task_queue=QUEUE)
    spec = ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(hours=1))])
    await server.client.create_schedule(
        temporal_id, Schedule(action=action, spec=spec, state=ScheduleState(paused=True))
    )


@contextlib.contextmanager
def described(client: Any) -> Iterator[list[str]]:
    """The schedule ids described while recorded, in order, and every other call by its RPC."""
    cls = type(client.service_client)
    original = cls._rpc_call
    seen: list[str] = []

    async def call(self_: Any, rpc: str, req: Any, resp_type: Any, **kw: Any) -> Any:
        seen.append(req.schedule_id if rpc == "describe_schedule" else rpc)
        return await original(self_, rpc, req, resp_type, **kw)

    cls._rpc_call = call  # type: ignore[method-assign]
    try:
        yield seen
    finally:
        cls._rpc_call = original  # type: ignore[method-assign]


async def only_these_due(owner: Any, schedule_id: uuid.UUID) -> None:
    """Every other test's incarnations read just now: what's due is this schedule's."""
    await sql(owner, "update schedule_incarnations set misses_checked_at = now(), checked_at = now() "
              "where schedule_id <> :s", s=schedule_id)  # fmt: skip


async def test_misses_read_each_incarnation_that_may_miss_a_firing_on_its_own_every_five_minutes(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """100 incarnations that may have fired (the current one and 99 sent an unpause), 5 that never could (never
    unpaused): a pass reads at most `BATCH` of them, a describe each; two passes read all 100, none of the 5; none is
    due again until five minutes after its read."""
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    await recorded_earlier(owner_sessionmaker, ctx, schedule_id, 99, unpaused=True)
    await recorded_earlier(owner_sessionmaker, ctx, schedule_id, 5, unpaused=False)
    await only_these_due(owner_sessionmaker, schedule_id)
    passes = []
    for _ in range(3):
        with recorded(server.client) as seen:
            done = await schedule_sync.check_misses(dispatch_sessionmaker, server.client)
        passes.append((done["checked"], len(seen)))
    assert passes == [(50, 50), (50, 50), (0, 0)]
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = now() - interval '6 minutes' "
              "where schedule_id = :s", s=schedule_id)  # fmt: skip
    assert (await schedule_sync.check_misses(dispatch_sessionmaker, server.client))["checked"] == 50


async def test_a_tombstone_of_many_incarnations_goes_a_few_a_visit_until_none_is_left(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
) -> None:
    """34 incarnations, 3 of them landed late: each visit describes at most 1 + `EARLIER` not yet retired (pausing,
    then deleting, one found), the least recently checked first, beside the sync's own describe of the current one;
    the tombstone is recorded once every one is verified gone: absent after it was seen, or after the deletion
    settled."""
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    late = await recorded_earlier(owner_sessionmaker, ctx, schedule_id, 33, unpaused=False)
    for temporal_id in late[:3]:
        await landed_late(server, temporal_id)
    await only_these_due(owner_sessionmaker, schedule_id)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        found = await s.get(schedules.Schedule, schedule_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=found)
    await sql(owner_sessionmaker, "update schedules set deleted_at = now() - interval '1 minute' where id = :s",
              s=schedule_id)  # fmt: skip  # its deletion settled: no create can be in flight
    visits = []
    while not visits or visits[-1][0] == "deleting":
        assert len(visits) < 50
        with described(server.client) as seen:
            outcome = await sync(server, dispatch_sessionmaker, ctx, schedule_id)
        visits.append((outcome, list(seen)))
    assert visits[-1][0] == "synced"
    per = 1 + schedule_sync.EARLIER  # incarnations a visit reaches: each a describe, then a pause or a delete
    assert all(sum(c.startswith("t:") for c in calls) <= 1 + per for _, calls in visits)  # and the current one's
    assert all(len(calls) <= 2 + 2 * per for _, calls in visits)
    assert len(visits) >= math.ceil(34 / (1 + schedule_sync.EARLIER))
    async with owner_sessionmaker() as s:
        left = (await s.execute(text("select count(*) from schedule_incarnations where schedule_id = :s and "
                                     "retired_at is null"), {"s": schedule_id})).scalar_one()  # fmt: skip
    assert left == 0


async def test_a_sync_checks_at_most_a_few_earlier_incarnations_a_visit_for_a_late_create(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """20 earlier incarnations none of which landed: the sync's visit describes at most `EARLIER` of them, the newest;
    the stray pass describes every one within the hour."""
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [first] = await incarnations(schedule_id)
    await server.client.get_schedule_handle(first).delete()  # none of them is in Temporal
    made = await recorded_earlier(owner_sessionmaker, ctx, schedule_id, 20, unpaused=False)
    new = [made[-1]]  # the current one before this sync, never landed: the sync incarnates the schedule anew
    with described(server.client) as seen:
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    current = (await incarnations(schedule_id))[-1]
    earlier = [c for c in seen if c.startswith("t:") and c != current and c not in new]
    assert len(earlier) <= schedule_sync.EARLIER and earlier == sorted(earlier, reverse=True)


async def test_the_api_shows_the_misses_accounting_stale_when_one_wasnt_read_within_five_minutes(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
) -> None:
    """The owner's ruling 3: every relevant incarnation read within the five-minute cadence, or the accounting reported
    stale. Stale, never complete, once one's last read is older than five minutes (the owner's review of checkpoint
    3: a grace may govern an alert, never leave an overdue read complete); one never read is stale from its unpause,
    not from its recording (enabled long after it was made, it isn't stale at once)."""
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    await recorded_earlier(owner_sessionmaker, ctx, schedule_id, 1, unpaused=True)

    async def accounted() -> Any:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            return await schedules.accounting(s, schedule_id)

    def stale(found: Any) -> bool:
        return any(span["reason"] == "misses_stale" for span in found.uncounted)

    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = now() - interval '5 minutes 30 "
              "seconds' where schedule_id = :s", s=schedule_id)  # fmt: skip
    found = await accounted()
    assert stale(found) and not found.complete  # overdue
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = now() - interval '4 minutes' "
              "where schedule_id = :s", s=schedule_id)  # fmt: skip
    assert not stale(await accounted())  # read within its five minutes
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = null, recorded_at = now() - "
              "interval '1 hour', unpause_sent_at = now() - interval '1 minute' where schedule_id = :s",
              s=schedule_id)  # fmt: skip
    assert not stale(await accounted())  # enabled a minute ago: due, never read yet
    await only_these_due(owner_sessionmaker, schedule_id)
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = null where schedule_id = :s",
              s=schedule_id)  # fmt: skip
    while (await schedule_sync.check_misses(dispatch_sessionmaker, server.client))["checked"]:
        pass
    assert not stale(await accounted())


async def test_an_incarnation_is_due_its_read_before_its_accounting_would_turn_stale(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
) -> None:
    """Read 4 minutes 30 seconds ago: not stale yet (five minutes), and due already (`MISSES_DUE`, four), so a pass
    reads it before it would be (the review of checkpoint 4: due and stale at the same five minutes, every schedule
    showed itself incomplete for part of each period)."""
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    await only_these_due(owner_sessionmaker, schedule_id)
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = now() - interval '4 minutes 30 "
              "seconds' where schedule_id = :s", s=schedule_id)  # fmt: skip
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        found = await schedules.accounting(s, schedule_id)
    assert not any(span["reason"] == "misses_stale" for span in found.uncounted)
    assert (await schedule_sync.check_misses(dispatch_sessionmaker, server.client))["checked"] == 1


async def test_an_incarnation_from_before_the_migration_found_absent_is_retired(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """Incarnation 0 (backfilled), never seen, absent from Temporal (its schedule deleted before the migration, or
    replaced since): once the inventory's cutover is recorded, no writer can create its id again (the old dispatcher is
    gone; the new sync numbers from 1), so the misses pass retires it, and it's never due again (the review's I2: it
    was read every five minutes for good)."""
    ctx, _, schedule_id = ready
    base = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    await sql(owner_sessionmaker, "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, "
              "backfilled) values (:i, :t, :s, 0, true)", i=base, t=ctx.tenant_id, s=schedule_id)  # fmt: skip
    await only_these_due(owner_sessionmaker, schedule_id)
    with described(server.client) as seen:
        assert (await schedule_sync.check_misses(dispatch_sessionmaker, server.client))["checked"] == 1
    assert seen == [base]
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = now() - interval '6 minutes' "
              "where schedule_id = :s", s=schedule_id)  # fmt: skip
    assert (await schedule_sync.check_misses(dispatch_sessionmaker, server.client))["checked"] == 0


READ = """SELECT sum(pg_stat_get_xact_tuples_returned(c.oid)) FROM pg_class c
WHERE c.oid = 'schedule_incarnations'::regclass
   OR c.oid IN (SELECT indexrelid FROM pg_index WHERE indrelid = 'schedule_incarnations'::regclass)"""


async def test_finding_the_misses_candidates_never_reads_the_incarnations_that_cant_miss_a_firing(
    ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """2,000 incarnations never unpaused (a disabled schedule's, say: never read, never retired) beside 60 due: finding
    a pass's 50 reads about as many rows and index entries as it returns, not every one of the 2,000 (the review's I5:
    the index kept them at its head)."""
    ctx, _, schedule_id = ready
    base = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    await sql(owner_sessionmaker, "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, "
              "unpause_sent_at) select :b || '~' || n, :t, :s, n, case when n > 2000 then now() end "
              "from generate_series(1, 2060) n", b=base, t=ctx.tenant_id, s=schedule_id)  # fmt: skip
    await only_these_due(owner_sessionmaker, schedule_id)
    await sql(owner_sessionmaker, "analyze schedule_incarnations")
    async with dispatch_sessionmaker() as s, s.begin():
        picked = (await s.execute(text("select temporal_id from incarnation_miss_candidates(50)"))).all()
        read = (await s.execute(text(READ))).scalar_one()
    assert len(picked) == 50 and read < 200


@contextlib.contextmanager
def slowed(client: Any, late: str, seconds: float, only: Callable[[Any], bool] = lambda req: True) -> Iterator[None]:
    """Each `late` call (of those `only` keeps) answered `seconds` late, beneath the budget's timing."""
    cls = type(client.service_client)
    original = cls._rpc_call

    async def call(self_: Any, rpc: str, req: Any, resp_type: Any, **kw: Any) -> Any:
        if rpc == late and only(req):
            await asyncio.sleep(seconds)
        return await original(self_, rpc, req, resp_type, **kw)

    cls._rpc_call = call  # type: ignore[method-assign]
    try:
        yield
    finally:
        cls._rpc_call = original  # type: ignore[method-assign]


async def test_a_live_schedules_sync_makes_at_most_its_calls_on_its_longest_path(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """Its current incarnation never landed: described, described again under its lock, a new one created, described,
    updated, read back, its creation wait counted; then `EARLIER` earlier ones described, the last of them found
    (landed late), paused: `budget.CALLS["sync"]`, no more."""
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [first] = await incarnations(schedule_id)
    await server.client.get_schedule_handle(first).delete()
    made = await recorded_earlier(owner_sessionmaker, ctx, schedule_id, schedule_sync.EARLIER, unpaused=False)
    await landed_late(server, made[0])  # the oldest of the four the visit reaches
    with described(server.client) as seen:
        assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "pending"
    assert len(seen) == budget.CALLS["sync"], seen


async def test_a_stray_is_paused_then_deleted_each_visit_at_most_its_calls(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    await recorded_earlier(owner_sessionmaker, ctx, schedule_id, 1, unpaused=False)  # the first is no longer current
    await only_these_due(owner_sessionmaker, schedule_id)
    await sql(owner_sessionmaker, "update schedule_incarnations set checked_at = null where schedule_id = :s",
              s=schedule_id)  # fmt: skip
    visits = []
    for _ in range(2):
        with described(server.client) as seen:
            visits.append((await schedule_sync.check_strays(dispatch_sessionmaker, server.client), len(seen)))
    assert visits[0][0].get("held") == 1 and visits[1][0].get("deleted") == 1
    assert [calls for _, calls in visits] == [budget.CALLS["strays"]] * 2


async def test_a_slow_call_ends_the_misses_pass_once_its_item_ends_and_the_next_passes_take_the_rest(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """Every describe answered late: each pass takes one incarnation, reads it to its end (it's not due again), and
    defers the rest; the next passes take them, one each."""
    monkeypatch.setattr(budget, "SLOW_S", 0.05)
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    await recorded_earlier(owner_sessionmaker, ctx, schedule_id, 2, unpaused=True)  # three that may miss a firing
    await only_these_due(owner_sessionmaker, schedule_id)
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = null where schedule_id = :s",
              s=schedule_id)  # fmt: skip
    budget.instrument(server.client)
    with slowed(server.client, "describe_schedule", 0.1):
        passes = [await schedule_sync.check_misses(dispatch_sessionmaker, server.client) for _ in range(4)]
    assert [(p["checked"], p.get("deferred", 0)) for p in passes] == [(1, 2), (1, 1), (1, 0), (0, 0)]


async def test_a_sync_pass_stopped_by_a_slow_schedule_takes_another_first_next_time(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """A tombstone whose deletion keeps it `deleting` visit after visit, and whose calls are slow, comes first in the
    pass's order (the oldest change): the pass takes it and stops. Next time it takes the other schedule first, the
    one it hasn't taken lately, so the slow one never keeps it waiting."""
    monkeypatch.setattr(budget, "SLOW_S", 0.05)
    ctx, wf, slow = ready
    assert await sync(server, dispatch_sessionmaker, ctx, slow) == "synced"
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await s.get(schedules.Schedule, slow))
    async with api_sessionmaker() as s, s.begin():  # added after the deletion: later in the pass's own order
        await tenant_scope(s, ctx.tenant_id)
        made = await schedules.create(s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
                                      timing=TIMING, mode="live", input={"token": TOKEN}, enabled=True)  # fmt: skip
        other = made.id
    prefix = f"t:{ctx.tenant_id}:sched:{slow}"
    budget.instrument(server.client)
    with slowed(server.client, "describe_schedule", 0.1, only=lambda req: req.schedule_id.startswith(prefix)):
        first = await schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading())
        second = await schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading())
    assert first == {"deleting": 1, "deferred": 1}
    assert second.get("synced") == 1  # the other, taken first
    async with owner_sessionmaker() as s:
        synced = (await s.execute(text("select synced_generation = generation from schedules where id = :i"),
                                  {"i": other})).scalar_one()  # fmt: skip
    assert synced
