# SPDX-License-Identifier: Apache-2.0
"""Bounded retry for a deterministic per-item failure (§7.9; D10(1); the owner's rulings on the 2b-4b M3 design, rev 1
and 2): an item's consecutive unexpected failures, counted for one kind of work, so a hold on one kind never stops
another's work on the same item. A reconciliation's are counted by its request's phase (starting, open, slot): a
request that moved on starts its next phase's count afresh.

After a failure the item waits 1, 2, 4, 8, 16 and then 30 minutes; the 7th consecutive one, about 61 minutes after the
first, holds it, alerting once, until an operator releases it. A success clears its kind's count. What isn't a failure
of the item is never counted: a database or network outage, an uncertain Temporal answer (each keeps its own handling),
and a confirmed refusal or an event's own failure, which the item's attempts count. A failure's record keeps the
error's type, never its text."""

import uuid
from collections.abc import Iterable
from datetime import timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.core.db import tenant_scope, unavailable

log = structlog.get_logger("dewpoint.dispatcher")

DISPATCH, CANCEL, MATCH, SUBRUN = "dispatch", "cancel", "match", "subrun"
RECONCILE = {"starting": "reconcile_starting", "open": "reconcile_open", "slot": "reconcile_slot"}
BOUND = 7
DELAYS = tuple(timedelta(minutes=m) for m in (1, 2, 4, 8, 16, 30))  # after the 1st to the 6th
# Temporal not answering, or answering too late to tell: whatever was asked may yet have happened
UNCERTAIN = frozenset({RPCStatusCode.UNAVAILABLE, RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.RESOURCE_EXHAUSTED,
                       RPCStatusCode.CANCELLED})  # fmt: skip

_FAILED = text(
    "INSERT INTO work_failures AS f (tenant_id, kind, item_id, errors, last_error, due_at) "
    "VALUES (:t, :k, :i, 1, :e, statement_timestamp() + make_interval(secs => :first)) "
    "ON CONFLICT (tenant_id, item_id, kind) DO UPDATE SET errors = f.errors + 1, last_error = EXCLUDED.last_error, "
    "due_at = statement_timestamp() + make_interval(secs => (CAST(:delays AS float8[]))[least(f.errors + 1, :n)]), "
    "held_at = CASE WHEN f.errors + 1 >= :bound THEN coalesce(f.held_at, statement_timestamp()) END "
    "RETURNING errors"
)
_FAILING = text(
    "SELECT DISTINCT item_id FROM work_failures WHERE kind = ANY(:k) AND item_id = ANY(:i) "
    "AND (held_at IS NOT NULL OR due_at > statement_timestamp())"
)
_CLEARED = text("DELETE FROM work_failures WHERE kind = ANY(:k) AND item_id = :i")


def counted(e: BaseException) -> bool:
    """Whether `e` is a failure of the item's own: a bug, or anything unclassified."""
    if unavailable(e) or isinstance(e, TimeoutError):
        return False
    return not (isinstance(e, RPCError) and e.status in UNCERTAIN)


async def failed(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, kind: str, item_id: uuid.UUID,
    error: BaseException,
) -> None:  # fmt: skip
    """`error` stopped `kind`'s work on the item: counted, in a transaction of its own, if it's the item's own."""
    if not counted(error):
        return
    seconds = [d.total_seconds() for d in DELAYS]
    try:
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            errors: int = (await s.execute(_FAILED, {"t": tenant_id, "k": kind, "i": item_id, "e": type(error).__name__,
                                                "first": seconds[0], "delays": seconds, "n": len(seconds),
                                                "bound": BOUND})).scalar_one()  # fmt: skip
    except DBAPIError as e:  # in the item's own handler: never ends the pass
        log.error("failure_unrecorded", kind=kind, item_id=str(item_id), error=type(e).__name__)
        return
    if errors == BOUND:
        log.error(f"{kind}_held", tenant_id=str(tenant_id), item_id=str(item_id), errors=errors,
                  error=type(error).__name__)  # fmt: skip


async def failing(s: AsyncSession, kinds: Iterable[str], item_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Which of the items, in the session's tenant, `kinds`' work leaves for now: held, or not yet due."""
    found = await s.execute(_FAILING, {"k": list(kinds), "i": list(item_ids)})
    return set(found.scalars())


async def cleared(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, kinds: Iterable[str], item_id: uuid.UUID
) -> None:  # fmt: skip
    """`kinds`' work on the item succeeded: their counts go."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await s.execute(_CLEARED, {"k": list(kinds), "i": item_id})
