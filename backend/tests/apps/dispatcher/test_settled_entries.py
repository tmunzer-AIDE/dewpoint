# SPDX-License-Identifier: Apache-2.0
"""An item's failure count, hold or recovery reason goes once the item settles (the owner's ruling on the M3
checkpoint): its kind of work, or the recovery its reason asks for, no longer has an item to act on. A request no longer
queued, starting or open; a slot released; a cancel sent or its run ended; an event no longer pending; a sub-run ended.
The leader clears them every cycle, a bounded number at once, by `work_settled_clear()`; an item still in that state
keeps its rows."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from tests.apps.dispatcher.test_failure_candidates import in_phase, requested_cancel
from tests.core.ingress.support import endpoint, record
from tests.core.retention.support import request, run, sql, tenant

Made = Callable[[Any, dict[str, Any]], Awaitable[uuid.UUID]]


def _phase(phase: str) -> Made:
    async def made(owner: Any, ctx: dict[str, Any]) -> uuid.UUID:
        return await in_phase(owner, ctx, phase)

    return made


async def _queued(owner: Any, ctx: dict[str, Any]) -> uuid.UUID:
    return await request(owner, ctx, "queued", None)


async def _cancel(owner: Any, ctx: dict[str, Any]) -> uuid.UUID:
    return await requested_cancel(owner, ctx)


async def _orphan(owner: Any, ctx: dict[str, Any]) -> uuid.UUID:
    return await run(owner, ctx, None, parent=await run(owner, ctx, timedelta(hours=1)))


SETTLE = {  # how each item settles
    "queued": "update run_requests set status = 'cancelled', reason = 'r', ended_at = now() where id = :i",
    "starting": "update run_requests set status = 'started' where id = :i",
    "open": "update runs set status = 'succeeded', ended_at = now() where id = :i",
    "slot": "delete from run_slots where run_id = :i",
    "cancel": "update run_requests set cancel_sent_at = now() where id = :i",
    "subrun": "update runs set status = 'succeeded', ended_at = now() where id = :i",
}
CASES = [  # (table, its kind or reason, how its item is made, how it settles)
    ("work_failures", "dispatch", _queued, "queued"),
    ("work_failures", "reconcile_starting", _phase("starting"), "starting"),
    ("work_failures", "reconcile_open", _phase("open"), "open"),
    ("work_failures", "reconcile_slot", _phase("slot"), "slot"),
    ("work_failures", "cancel", _cancel, "cancel"),
    ("work_failures", "subrun", _orphan, "subrun"),
    ("recovery_items", "start_after_end", _phase("starting"), "starting"),
    ("recovery_items", "start_history_missing", _phase("starting"), "starting"),
    ("recovery_items", "start_unresolved", _phase("starting"), "starting"),
    ("recovery_items", "run_history_missing", _phase("open"), "open"),
    ("recovery_items", "slot_history_missing", _phase("slot"), "slot"),
    ("recovery_items", "subrun_history_missing", _orphan, "subrun"),
]


async def entry(owner: Any, table: str, name: str, tenant_id: uuid.UUID, item: uuid.UUID) -> None:
    if table == "work_failures":
        await sql(owner, "insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at, held_at) "
                  "values (:t, :n, :i, 7, 'RuntimeError', now(), now())", t=tenant_id, n=name, i=item)  # fmt: skip
    else:
        await sql(owner, "insert into recovery_items (tenant_id, reason, item_id) values (:t, :n, :i)", t=tenant_id,
                  n=name, i=item)  # fmt: skip


async def left(owner: Any, items: list[uuid.UUID]) -> set[uuid.UUID]:
    async with owner() as s:
        both = text(
            "select item_id from work_failures where item_id = any(:i) union "
            "select item_id from recovery_items where item_id = any(:i)"
        )
        found = await s.execute(both, {"i": items})
        return set(found.scalars())


async def cleared(dispatch: Any, n: int = 1_000) -> int:
    async with dispatch() as s, s.begin():
        return int((await s.execute(text("select work_settled_clear(:n)"), {"n": n})).scalar_one())


@pytest.mark.parametrize(("table", "name", "made", "settles"), CASES, ids=[f"{t}-{n}" for t, n, *_ in CASES])
async def test_an_items_entry_goes_once_it_settles_and_stays_while_it_hasnt(
    owner_sessionmaker, dispatch_sessionmaker, table: str, name: str, made: Made, settles: str
) -> None:  # fmt: skip
    ctx = await tenant(owner_sessionmaker)
    settled, live = await made(owner_sessionmaker, ctx), await made(owner_sessionmaker, ctx)
    for item in (settled, live):
        await entry(owner_sessionmaker, table, name, ctx["t"], item)
    await sql(owner_sessionmaker, SETTLE[settles], i=settled)
    assert await cleared(dispatch_sessionmaker) >= 1
    assert await left(owner_sessionmaker, [settled, live]) == {live}


@pytest.mark.usefixtures("development_deployment")
async def test_an_events_count_goes_once_it_is_no_longer_pending(
    owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    t, endpoint_id = await endpoint(owner_sessionmaker)
    settled, live = uuid.uuid4(), uuid.uuid4()
    await record(ingress_sessionmaker, endpoint_id, [(None, None, b"x"), (None, None, b"y")], ids=[settled, live])
    for event in (settled, live):
        await sql(owner_sessionmaker, "insert into work_failures (tenant_id, kind, item_id, errors, last_error, "
                  "due_at) values (:t, 'match', :i, 2, 'RuntimeError', now())", t=t, i=event)  # fmt: skip
    await sql(owner_sessionmaker, "update inbound_events set status = 'dead', reason = 'r', ended_at = now() "
              "where id = :i", i=settled)  # fmt: skip
    assert await cleared(dispatch_sessionmaker) == 1
    assert await left(owner_sessionmaker, [settled, live]) == {live}


async def test_a_cycle_clears_a_bounded_number(owner_sessionmaker, dispatch_sessionmaker) -> None:
    """Each table at most `n` a call: the rest the next."""
    ctx = await tenant(owner_sessionmaker)
    items = [uuid.uuid4() for _ in range(5)]  # requests that don't exist: settled, as gone
    for item in items:
        await entry(owner_sessionmaker, "work_failures", "dispatch", ctx["t"], item)
    assert [await cleared(dispatch_sessionmaker, 2) for _ in range(4)] == [2, 2, 1, 0]
