# SPDX-License-Identifier: Apache-2.0
"""The schedule inventory's cutover (the owner's D15 rulings on the 2b-4b M1 checkpoints), after every writer from
before migration 0040 is gone: a catch-up, in batches, then a short final step that records it (`cut_over`).

- One at a time: a cutover holds the advisory lock `RUNNING` on a connection of its own from its start to its end; a
  second one refuses (`CutoverRunningError`) rather than racing it (the owner's review of checkpoint 4, R4).
- The capture's state is read first (`schedule_inventory_capture()`): off, the cutover refuses before the catch-up;
  changed by the final step (turned off and on again, or replaced), it refuses there, since a schedule added meanwhile
  would have escaped both (R1).
- `catch_up`: every schedule the capture missed given its incarnation 0, and each incarnation 0 its schedule's missed
  count as the old dispatcher last recorded it, `CATCH_UP_BATCH` schedules by id at a time, each batch committed on its
  own, holding no lock a schedule's writer waits for. Resumable: an interrupted catch-up's committed batches stay
  done; run again, it passes over them.
- `record`: the cutover, in one short transaction that holds schedules' writes off while it records, reading no
  schedule (the owner's review of checkpoint 3: done with the catch-up under that lock, its hold grew with the
  schedules). Its lock is waited for at most `LOCK_WAIT` an attempt (a writer queued behind the request waits that,
  and the step's hold once it has the lock); then it gives way, at most `ATTEMPTS` times, `PAUSE_S` apart
  (`InventoryBusyError`: run it again). Its statements are bounded (`STATEMENT_WAIT`), and so is its session's idling
  between them (`IDLE_WAIT`): a client stalled there has its session ended, its lock with it, and nothing recorded
  (the review of checkpoint 5). Its commit waits for no synchronous standby (`synchronous_commit = local`, the owner's
  review of checkpoint 5: no bound above covers that wait); a failover that lost it leaves no cutover recorded, its
  audit entry gone with it (the anchor signs none before the standbys hold it), and it's run again. So its hold is
  those bounds and the local WAL flush, which no timeout bounds.

Every refusal is a `CutoverRefusedError`, said in its message; nothing is recorded by one. Its lock's connection lost
before its end (a network, a restarted pooler; its lock released with it), the outcome stands all the same, an error or
what it recorded, and says so (`CutOver.lock_lost`; the owner's review of checkpoint 5, M2): the unlock's own failure
never takes its place."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from dewpoint.core.audit import service as audit_log

CATCH_UP_BATCH = 1_000  # schedules a catch-up batch takes
LOCK_WAIT = "200ms"  # the final step's wait for its lock, an attempt
STATEMENT_WAIT = "500ms"  # each of the final step's statements at most, its lock's wait included
IDLE_WAIT = "500ms"  # the final step's session idle in its transaction at most (a stalled client): then it's ended
ATTEMPTS = 60  # the final step's attempts while schedules stay busy
PAUSE_S = 1.0  # between them
LOCK_NOT_AVAILABLE = "55P03"
RUNNING = "dewpoint schedule inventory cutover"  # the advisory lock a cutover holds while it runs

log = structlog.get_logger("dewpoint.platform.inventory")


@dataclass(frozen=True)
class CaughtUp:
    """What a catch-up did: schedules given their incarnation 0, incarnation 0s their schedule's count, batches."""

    caught: int = 0
    refreshed: int = 0
    batches: int = 0


@dataclass(frozen=True)
class CutOver:
    """What a cutover did: when it recorded (None: recorded already), its catch-up, and whether its lock's connection
    was lost before its end (`lock_lost`: another cutover may have run beside it; the database records one only)."""

    at: datetime | None
    caught: CaughtUp
    lock_lost: bool = False


class CutoverRefusedError(RuntimeError):
    """The cutover not recorded, for the reason its message gives; run it again once that's settled."""


class CutoverRunningError(CutoverRefusedError):
    """Another cutover holds `RUNNING`."""


class CaptureOffError(CutoverRefusedError):
    """The capture's trigger is off, or gone."""


class CaptureChangedError(CutoverRefusedError):
    """The capture's trigger changed between the catch-up's start and the final step."""


class InventoryBusyError(CutoverRefusedError):
    """Schedules stayed busy through every attempt of the final step."""


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


async def capture(s: AsyncSession) -> str | None:
    """The capture's state now: its trigger's `oid:xmin:tgenabled`; None when it's gone."""
    async with s.begin():
        found: str | None = (await s.execute(text("SELECT schedule_inventory_capture()"))).scalar_one()
    return found


def _on(state: str | None) -> bool:
    return state is not None and state[-1] in ("O", "A")


CAPTURE_OFF = "the capture's trigger (schedules_inventoried) is off, or gone: turn it on, then run the cutover again"
CAPTURE_CHANGED = (
    "the capture's trigger (schedules_inventoried) changed during the catch-up (turned off and on, or replaced), so a "
    "schedule added meanwhile may have escaped it: leave it on, then run the cutover again"
)
BUSY = (
    f"schedules stayed busy: their lock wasn't had within {LOCK_WAIT} in {ATTEMPTS} attempts (a long writer, or an "
    "autovacuum of schedules, which this wait never cancels: wait for it to end, or cancel it); nothing recorded, and "
    "the catch-up's batches stay done: run the cutover again"
)


async def record(s: AsyncSession, state: str | None, details: dict[str, object]) -> datetime | None:
    """The cutover recorded, audited with `details` in the same transaction, the capture still `state`: when, or None
    when it was recorded already. A `CutoverRefusedError` otherwise."""
    for _ in range(ATTEMPTS):
        try:
            async with s.begin():
                await s.execute(text("SELECT set_config('lock_timeout', :w, true), set_config('statement_timeout', :s, "
                                     "true), set_config('idle_in_transaction_session_timeout', :i, true), "
                                     "set_config('synchronous_commit', 'local', true)"),
                                {"w": LOCK_WAIT, "s": STATEMENT_WAIT, "i": IDLE_WAIT})  # fmt: skip
                query = text("SELECT schedule_inventory_cutover_record(:c)")
                outcome: str = (await s.execute(query, {"c": state})).scalar_one()
                if outcome == "recorded_already":
                    return None
                if outcome == "capture_off":
                    raise CaptureOffError(CAPTURE_OFF)
                if outcome == "capture_changed":
                    raise CaptureChangedError(CAPTURE_CHANGED)
                at: datetime = (await s.execute(text("SELECT at FROM schedule_inventory_cutover"))).scalar_one()
                await audit_log.record(s, tenant_id=None, actor_id=None, action="schedules.inventory_cutover",
                                       target_type="platform", target_id="inventory_cutover",
                                       details=details)  # fmt: skip
            return at
        except DBAPIError as e:
            if getattr(e.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
                raise
        await asyncio.sleep(PAUSE_S)
    raise InventoryBusyError(BUSY)


async def cut_over(s: AsyncSession, attested: str) -> CutOver:
    """The whole cutover, as above, audited with `attested`. A `CutoverRefusedError` when it refuses."""
    engine = s.bind
    if not isinstance(engine, AsyncEngine):
        raise TypeError("a cutover's session is bound to an engine")
    key = {"k": RUNNING}
    async with engine.connect() as holder:  # the cutover's own lock, on a connection of its own, to its end
        lock = text("SELECT pg_try_advisory_lock(hashtextextended(:k, 0))")
        held: bool = (await holder.execute(lock, key)).scalar_one()
        await holder.commit()
        if not held:
            raise CutoverRunningError("another inventory cutover is running: wait for it to end, then run it again")
        try:
            at, caught = await _cut_over(s, attested)
        finally:  # an error above stands: an unlock that fails replaces nothing
            lost = not await _unlocked(holder)
    return CutOver(at, caught, lock_lost=lost)


async def _cut_over(s: AsyncSession, attested: str) -> tuple[datetime | None, CaughtUp]:
    async with s.begin():
        if (await s.execute(text("SELECT EXISTS (SELECT 1 FROM schedule_inventory_cutover)"))).scalar():
            return None, CaughtUp()
    state = await capture(s)
    if not _on(state):
        raise CaptureOffError(CAPTURE_OFF)
    caught = await catch_up(s)
    details: dict[str, object] = {"caught_up": caught.caught, "refreshed": caught.refreshed, "attested": attested}
    return await record(s, state, details), caught


async def _unlocked(holder: AsyncConnection) -> bool:
    """The cutover's lock released; False when its connection was lost, the lock released with it."""
    try:
        await holder.execute(text("SELECT pg_advisory_unlock(hashtextextended(:k, 0))"), {"k": RUNNING})
        await holder.commit()
    except DBAPIError as e:
        log.warning("inventory_cutover_lock_lost", error_type=type(e).__name__)
        return False
    return True
