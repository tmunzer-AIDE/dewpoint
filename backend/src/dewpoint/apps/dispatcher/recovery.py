# SPDX-License-Identifier: Apache-2.0
"""Recovery reasons, recorded (the owner's rulings on the 2b-4b M3 design, rev 1 and 2): an item a pass can't settle,
and why, in `recovery_items`, besides the error it logs. The reason is recorded in the transaction that saw it, since
when, and when it was last seen again. An item that resolves on its own (Temporal answers again, a start is verified)
loses its reasons; an operator's command acts only on an item with its reason recorded."""

import uuid
from collections.abc import Iterable

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.tenancy.lifecycle import FENCED

log = structlog.get_logger("dewpoint.dispatcher")

START_AFTER_END, START_HISTORY_MISSING = "start_after_end", "start_history_missing"
START_UNRESOLVED, RUN_HISTORY_MISSING = "start_unresolved", "run_history_missing"
SLOT_HISTORY_MISSING, SUBRUN_HISTORY_MISSING = "slot_history_missing", "subrun_history_missing"
# A request's: any phase of its reconciliation settling resolves them all
REQUEST = (START_AFTER_END, START_HISTORY_MISSING, START_UNRESOLVED, RUN_HISTORY_MISSING, SLOT_HISTORY_MISSING)

_NOTED = text(
    "INSERT INTO recovery_items (tenant_id, reason, item_id) VALUES (:t, :r, :i) "
    "ON CONFLICT (tenant_id, item_id, reason) DO UPDATE SET last_seen_at = statement_timestamp()"
)
_RESOLVED = text("SELECT recovery_items_clear(:r, :t, :i)")  # by tenant and item, across tenants (0050)


async def noted(s: AsyncSession, tenant_id: uuid.UUID, reason: str, item_id: uuid.UUID) -> None:
    """`reason` seen for the item, in `s`'s transaction (scoped to its tenant): recorded, or seen again. Under a
    savepoint: past an erasure's stage 60 its fence refuses the insert, and the transaction's own write stands (the
    owner's ruling on the M3 checkpoint): the erasure deletes the item anyway."""
    try:
        async with s.begin_nested():
            await s.execute(_NOTED, {"t": tenant_id, "r": reason, "i": item_id})
    except DBAPIError as e:
        if getattr(e.orig, "sqlstate", None) != FENCED:
            raise
        log.info("recovery_reason_fenced", reason=reason)


async def resolved(
    sessionmaker: async_sessionmaker[AsyncSession], reasons: Iterable[str], done: Iterable[tuple[uuid.UUID, uuid.UUID]]
) -> None:  # fmt: skip
    """Each `(tenant, item)` a pass settled loses `reasons`, in one statement (none for none)."""
    pairs = list(done)
    if not pairs:
        return
    try:
        async with sessionmaker() as s, s.begin():
            await s.execute(_RESOLVED, {"r": list(reasons), "t": [t for t, _ in pairs], "i": [i for _, i in pairs]})
    except (DBAPIError, OSError) as e:  # a reason left over: the next pass that settles the item clears it
        log.error("recovery_unresolved", error=type(e).__name__)


SETTLED = 500  # an item's entries cleared a cycle at most, each table's
_SETTLED = text("SELECT work_settled_clear(:n)")


async def settled(sessionmaker: async_sessionmaker[AsyncSession]) -> int:
    """The failure counts, holds and recovery reasons of items that have settled, cleared (the owner's ruling on the
    M3 checkpoint): how many. The database failing clears none: the next cycle does."""
    try:
        async with sessionmaker() as s, s.begin():
            return int((await s.execute(_SETTLED, {"n": SETTLED})).scalar_one())
    except (DBAPIError, OSError) as e:
        log.error("settled_entries_uncleared", error=type(e).__name__)
        return 0
