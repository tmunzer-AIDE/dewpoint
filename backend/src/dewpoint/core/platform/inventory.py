# SPDX-License-Identifier: Apache-2.0
"""The schedule inventory's cutover (the owner's D15 rulings on the 2b-4b M1 checkpoints), after every writer from
before migration 0040 is gone: a catch-up, in batches, then a short final step that records it.

- `catch_up`: every schedule the capture missed given its incarnation 0, and each incarnation 0 its schedule's missed
  count as the old dispatcher last recorded it, `CATCH_UP_BATCH` schedules by id at a time, each batch committed on its
  own, holding no lock a schedule's writer waits for. Resumable: an interrupted catch-up's committed batches stay
  done; run again, it passes over them.
- `record`: the cutover, in one short transaction that holds schedules' inserts off while it records, reading no
  schedule (the owner's review of checkpoint 3: done with the catch-up under that lock, its hold grew with the
  schedules). Its lock is waited for at most `LOCK_WAIT` an attempt, so a writer queued behind the request waits no
  longer; then it gives way, at most `ATTEMPTS` times, `PAUSE_S` apart."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit import service as audit_log

CATCH_UP_BATCH = 1_000  # schedules a catch-up batch takes
LOCK_WAIT = "200ms"  # the final step's wait for its lock, an attempt
ATTEMPTS = 60  # the final step's attempts while schedules stay busy
PAUSE_S = 1.0  # between them
LOCK_NOT_AVAILABLE = "55P03"


@dataclass(frozen=True)
class CaughtUp:
    """What a catch-up did: schedules given their incarnation 0, incarnation 0s their schedule's count, batches."""

    caught: int = 0
    refreshed: int = 0
    batches: int = 0


class InventoryBusyError(RuntimeError):
    """Schedules stayed busy through every attempt of the final step: nothing recorded; run it again."""


async def _batch(s: AsyncSession, after: uuid.UUID, size: int) -> tuple[uuid.UUID | None, int, int, int]:
    """One batch, committed: the last id it took (None: none left), how many it took, caught up and refreshed."""
    async with s.begin():
        query = text("SELECT last_id, seen, caught, refreshed FROM schedule_inventory_catch_up(:a, :n)")
        found = await s.execute(query, {"a": after, "n": size})
        last, seen, caught, refreshed = found.one()
    return last, int(seen), int(caught), int(refreshed)


async def catch_up(s: AsyncSession) -> CaughtUp:
    """The catch-up, batch by batch, as above. Refused (by the database) once the cutover is recorded."""
    after, done = uuid.UUID(int=0), CaughtUp()
    while True:
        last, seen, caught, refreshed = await _batch(s, after, CATCH_UP_BATCH)
        done = CaughtUp(done.caught + caught, done.refreshed + refreshed, done.batches + 1)
        if last is None or seen < CATCH_UP_BATCH:
            return done
        after = last


async def record(s: AsyncSession, details: dict[str, object]) -> datetime | None:
    """The cutover recorded, audited with `details` in the same transaction: when, or None when it was recorded
    already. `InventoryBusyError` when its lock wasn't had in its attempts; the database refuses while the capture is
    off."""
    for _ in range(ATTEMPTS):
        try:
            async with s.begin():
                await s.execute(text("SELECT set_config('lock_timeout', :w, true)"), {"w": LOCK_WAIT})
                if not (await s.execute(text("SELECT schedule_inventory_cutover_record()"))).scalar_one():
                    return None
                at: datetime = (await s.execute(text("SELECT at FROM schedule_inventory_cutover"))).scalar_one()
                await audit_log.record(s, tenant_id=None, actor_id=None, action="schedules.inventory_cutover",
                                       target_type="platform", target_id="inventory_cutover",
                                       details=details)  # fmt: skip
            return at
        except DBAPIError as e:
            if getattr(e.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
                raise
        await asyncio.sleep(PAUSE_S)
    raise InventoryBusyError(
        f"schedules stayed busy: their lock wasn't had within {LOCK_WAIT} in {ATTEMPTS} attempts; nothing recorded"
    )
