# SPDX-License-Identifier: Apache-2.0
"""A schedule's items bounded however many Temporal ids it was recorded under (the owner's D16 ruling on the 2b-4b M1
checkpoint; `EARLIER`, an experimental cap, not a time budget): the sync checks at most `EARLIER` earlier incarnations
a visit for a late create, and a tombstone pauses, counts and deletes at most 1 + `EARLIER` a visit, until none is
left; the stray pass reaches every earlier one each hour. Misses keep their five-minute accounting for every
incarnation that may still miss a firing (unpaused once, or from before the migration) until it's verified paused for
its delete, its count recorded, or gone: each is its own item, one describe; the API shows the accounting stale when
one wasn't read within ten minutes. Counted in calls, against the dev server."""

import contextlib
import math
import uuid
from collections.abc import AsyncIterator, Iterator
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
from dewpoint.apps.dispatcher import schedule_sync
from dewpoint.core.db import tenant_scope
from tests.apps.dispatcher.test_leader_deadlines import recorded
from tests.apps.dispatcher.test_schedule_sync import TIMING, incarnations, sync
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


async def test_the_api_shows_the_misses_accounting_stale_when_one_wasnt_read_within_ten_minutes(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
) -> None:
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    await recorded_earlier(owner_sessionmaker, ctx, schedule_id, 1, unpaused=True)
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = now() - interval '11 minutes' "
              "where schedule_id = :s", s=schedule_id)  # fmt: skip

    async def accounted() -> Any:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            return await schedules.accounting(s, schedule_id)

    stale = await accounted()
    assert any(span["reason"] == "misses_stale" for span in stale.uncounted) and not stale.complete
    await only_these_due(owner_sessionmaker, schedule_id)
    await sql(owner_sessionmaker, "update schedule_incarnations set misses_checked_at = null where schedule_id = :s",
              s=schedule_id)  # fmt: skip
    while (await schedule_sync.check_misses(dispatch_sessionmaker, server.client))["checked"]:
        pass
    assert not any(span["reason"] == "misses_stale" for span in (await accounted()).uncounted)
