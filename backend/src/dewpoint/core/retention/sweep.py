# SPDX-License-Identifier: Apache-2.0
"""The retention sweep (engine 2b spec §10.1, §10.3), as `dewpoint_retention`: each active tenant in turn, under its
scope and its lifecycle lock (shared), in batches that each commit on their own, so a sweep that stops resumes.

What goes, once past the tenant's cutoff: a terminal root's whole tree (its runs and their steps, its claims, grants and
secret index, and its request with its envelope, together), never while any run of it is running or its request is
queued or starting; a terminal request that never started, with its inputs; a terminal event, its endpoint's and its
tenant's retained counters freed under their rows' locks (the lock order: tenant, endpoint, counter, event). Whatever
the cutoff: an expired upload, and a schedule's tombstone once the sync recorded Temporal's schedule gone. Not by the
cutoff, and not counted: a tick's record of its own ids after 31 days (2b-4a M4; identifiers only, the erasure's firing
inventory, kept while Temporal may keep its execution).

One sweep runs at a time; were two ever to, a tenant's batches still delete its trees and requests in turn, never in a
deadlock. Each batch counts what it deleted, in its own transaction, so a sweep that stops loses no count: resumed, it
audits each active tenant once, with counts only, zero counts included. A sweep is recorded (start, end, success, lag),
and its records go after 30 days. The cutoff is reckoned on the database's clock."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope
from dewpoint.core.ingress.counters import lock_tenant_shared
from dewpoint.core.models.retention import RetentionSweep
from dewpoint.core.retention import policy

log = structlog.get_logger("dewpoint.retention")
BATCH = 100
KEPT = timedelta(days=30)  # a sweep's record, then it goes
_LOCK = text("SELECT pg_try_advisory_lock(hashtextextended('dewpoint:retention', 0))")
_UNLOCK = text("SELECT pg_advisory_unlock(hashtextextended('dewpoint:retention', 0))")
_IN_TURN = text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))")
PENDING_REQUESTS = ("queued", "starting")
ENDED_REQUESTS = ("cancelled", "refused", "dead")

_ROOTS = text(
    "SELECT r.id FROM runs r WHERE r.parent_run_id IS NULL AND r.status <> 'running' AND r.ended_at <= :cutoff "
    "AND NOT EXISTS (SELECT 1 FROM runs c WHERE c.root_run_id = r.id AND c.status = 'running') "
    "AND NOT EXISTS (SELECT 1 FROM run_requests q WHERE q.id = r.id AND q.status IN ('queued', 'starting')) "
    "ORDER BY r.ended_at, r.id LIMIT :n"
)
_UNSTARTED = text(
    "SELECT q.id FROM run_requests q WHERE q.status IN ('cancelled', 'refused', 'dead') AND q.ended_at <= :cutoff "
    "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.id = q.id) ORDER BY q.ended_at, q.id LIMIT :n"
)
_CLAIMS = ("claim_grants", "step_outputs", "run_secret_index")  # by the tree's root
_EVENT_ENDPOINT = text(
    "SELECT endpoint_id FROM inbound_events WHERE status <> 'pending' AND ended_at <= :cutoff "
    "ORDER BY endpoint_id LIMIT 1"
)
_EVENTS = text(
    "DELETE FROM inbound_events WHERE id IN (SELECT id FROM inbound_events WHERE endpoint_id = :e "
    "AND status <> 'pending' AND ended_at <= :cutoff ORDER BY ended_at, id LIMIT :n) RETURNING size_bytes"
)
_UPLOADS = text(
    "DELETE FROM csv_uploads WHERE id IN (SELECT id FROM csv_uploads WHERE expires_at <= statement_timestamp() "
    "ORDER BY expires_at, id LIMIT :n)"
)
# The outer condition is checked again on the row a tick may have just queued again (it lowers synced_generation).
_TOMBSTONES = text(
    "DELETE FROM schedules WHERE id IN (SELECT id FROM schedules WHERE deleted_at IS NOT NULL "
    "AND synced_generation = generation ORDER BY id LIMIT :n) AND deleted_at IS NOT NULL "
    "AND synced_generation = generation"
)
FIRINGS_KEPT = timedelta(days=31)  # the platform's longest namespace retention, and a day
_FIRINGS = text(
    "DELETE FROM schedule_firings WHERE (workflow_id, run_id) IN (SELECT workflow_id, run_id FROM schedule_firings "
    "WHERE recorded_at < statement_timestamp() - cast(:kept as interval) LIMIT :n)"
)
_LAG = text(
    "SELECT extract(epoch FROM greatest("
    "(SELECT :cutoff - min(r.ended_at) FROM runs r WHERE r.parent_run_id IS NULL AND r.status <> 'running' "
    "AND r.ended_at <= :cutoff), "
    "(SELECT :cutoff - min(q.ended_at) FROM run_requests q WHERE q.ended_at <= :cutoff "
    "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.id = q.id)), "
    "(SELECT :cutoff - min(e.ended_at) FROM inbound_events e WHERE e.status <> 'pending' AND e.ended_at <= :cutoff), "
    "(SELECT statement_timestamp() - min(c.expires_at) FROM csv_uploads c WHERE c.expires_at <= statement_timestamp()),"
    " interval '0'))"
)


@dataclass
class Swept:
    """What one tenant's sweep deleted: run trees, requests that never started, events, uploads, tombstones; and its
    lag at its end, in seconds."""

    runs: int = 0
    requests: int = 0
    events: int = 0
    csv_uploads: int = 0
    schedules: int = 0
    lag_s: float = field(default=0.0, compare=False)

    def counts(self) -> dict[str, int]:
        return {k: v for k, v in asdict(self).items() if k != "lag_s"}


@dataclass(frozen=True)
class Sweep:
    id: int
    succeeded: bool
    tenants: int
    lag_s: float


async def _cutoff(s: AsyncSession, tenant_id: uuid.UUID) -> datetime:
    days = await policy.runs_days(s, tenant_id)
    at: datetime = (await s.execute(select(func.statement_timestamp() - timedelta(days=days)))).scalar_one()
    return at


async def _after_choosing() -> None:
    """A test's hook: two batches may choose the same rows before either deletes them."""


async def _in_turn(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    """What a batch chose, deleted only once no other batch is deleting the tenant's trees or requests: the later one
    then deletes what is left. Without the sweep's lock (lost, or bypassed), two batches' plans may visit the rows both
    delete in different orders (an index's, the heap's), and each hold a row the other waits for: a deadlock. The role
    can't take row locks here (it can't update these tables): the turn is the transaction's advisory lock."""
    await s.execute(_IN_TURN, {"k": f"dewpoint:retention:{tenant_id}"})


async def _trees(s: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime, n: int) -> tuple[int, int]:
    roots: list[uuid.UUID] = list((await s.execute(_ROOTS, {"cutoff": cutoff, "n": n})).scalars())
    if not roots:
        return 0, 0
    await _after_choosing()
    await _in_turn(s, tenant_id)
    for table in _CLAIMS:
        await s.execute(text(f"DELETE FROM {table} WHERE root_run_id = ANY(:r)"), {"r": roots})  # noqa: S608
    # The request before its envelope (a restricted key), never one still pending: none is, as chosen.
    await s.execute(text("DELETE FROM run_requests WHERE id = ANY(:r)"), {"r": roots})
    await s.execute(text("DELETE FROM run_inputs WHERE root_run_id = ANY(:r)"), {"r": roots})
    deleted = await s.execute(text("DELETE FROM runs WHERE root_run_id = ANY(:r) RETURNING id = root_run_id"),
                              {"r": roots})  # steps go with them; a tree counts once, as its root  # fmt: skip
    return len(roots), sum(1 for (root,) in deleted if root)


async def _unstarted(s: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime, n: int) -> tuple[int, int]:
    ids: list[uuid.UUID] = list((await s.execute(_UNSTARTED, {"cutoff": cutoff, "n": n})).scalars())
    if not ids:
        return 0, 0
    await _after_choosing()
    await _in_turn(s, tenant_id)
    deleted = await s.execute(text("DELETE FROM run_requests WHERE id = ANY(:r) RETURNING id"), {"r": ids})
    count = len(deleted.all())
    for table in ("run_inputs", *_CLAIMS):  # admission's claims and its seeded secret index, rooted at the request
        await s.execute(text(f"DELETE FROM {table} WHERE root_run_id = ANY(:r)"), {"r": ids})  # noqa: S608
    return len(ids), count


async def _events(s: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime, n: int) -> tuple[int, int]:
    endpoint = (await s.execute(_EVENT_ENDPOINT, {"cutoff": cutoff})).scalar()
    if endpoint is None:
        return 0, 0
    await s.execute(text("SELECT id FROM webhook_endpoints WHERE id = :e FOR UPDATE"), {"e": endpoint})
    await s.execute(text("SELECT tenant_id FROM tenant_event_counters WHERE tenant_id = :t FOR UPDATE"),
                    {"t": tenant_id})  # fmt: skip
    sizes: list[int] = list((await s.execute(_EVENTS, {"e": endpoint, "cutoff": cutoff, "n": n})).scalars())
    freed = {"n": len(sizes), "b": sum(sizes)}
    for table, key in (("webhook_endpoints", "id = :e"), ("tenant_event_counters", "tenant_id = :t")):
        await s.execute(text(f"UPDATE {table} SET retained_events = greatest(retained_events - :n, 0), "  # noqa: S608
                             f"retained_bytes = greatest(retained_bytes - :b, 0) WHERE {key}"),
                        {"e": endpoint, "t": tenant_id, **freed})  # fmt: skip
    return len(sizes), len(sizes)


async def _uploads(s: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime, n: int) -> tuple[int, int]:
    done = int((await s.execute(_UPLOADS, {"n": n})).rowcount)  # type: ignore[attr-defined]
    return done, done


async def _tombstones(s: AsyncSession, tenant_id: uuid.UUID, cutoff: datetime, n: int) -> tuple[int, int]:
    done = int((await s.execute(_TOMBSTONES, {"n": n})).rowcount)  # type: ignore[attr-defined]
    return done, done


# A batch: (what it chose, what it deleted). Another batch may have deleted what it chose: it counts only its own.
Batch = Callable[[AsyncSession, uuid.UUID, datetime, int], Awaitable[tuple[int, int]]]
KINDS: tuple[tuple[str, Batch], ...] = (
    ("runs", _trees), ("requests", _unstarted), ("events", _events), ("csv_uploads", _uploads),
    ("schedules", _tombstones),
)  # fmt: skip
COUNTED = tuple(kind for kind, _ in KINDS)


async def _active(s: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """In the tenant's scope, holding its lifecycle lock shared: an erasure, which takes it exclusively, waits."""
    await tenant_scope(s, tenant_id)
    await lock_tenant_shared(s, tenant_id)
    status = (await s.execute(text("SELECT status FROM tenants WHERE id = :t"), {"t": tenant_id})).scalar()
    return status == "active"


async def _counted(s: AsyncSession, sweep_id: int, tenant_id: uuid.UUID, kind: str, n: int) -> None:
    """A batch's deletions added to its tenant's counts for the sweep, in the batch's own transaction."""
    await s.execute(text(f"INSERT INTO retention_sweep_tenants (sweep_id, tenant_id, {kind}) VALUES (:s, :t, :n) "  # noqa: S608
                         f"ON CONFLICT (sweep_id, tenant_id) DO UPDATE SET {kind} = retention_sweep_tenants.{kind} + "
                         f"EXCLUDED.{kind}"), {"s": sweep_id, "t": tenant_id, "n": n})  # fmt: skip


async def sweep_tenant(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, *, batch: int = BATCH,
    sweep_id: int | None = None,
) -> Swept:  # fmt: skip
    """One tenant swept, batch by batch, each kind until a batch chooses nothing (an event batch covers one endpoint);
    then its lag. Within a sweep (`sweep_id`), each batch's deletions are counted in its own transaction."""
    swept = Swept()
    for kind, delete in KINDS:
        while True:
            async with sessionmaker() as s, s.begin():
                if not await _active(s, tenant_id):
                    return swept
                chosen, done = await delete(s, tenant_id, await _cutoff(s, tenant_id), batch)
                if sweep_id is not None and done:
                    await _counted(s, sweep_id, tenant_id, kind, done)
            setattr(swept, kind, getattr(swept, kind) + done)
            if chosen == 0:
                break
    while True:
        async with sessionmaker() as s, s.begin():
            if not await _active(s, tenant_id):
                return swept
            pruned = (await s.execute(_FIRINGS, {"kept": FIRINGS_KEPT, "n": batch})).rowcount  # type: ignore[attr-defined]
        if pruned < batch:
            break
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        swept.lag_s = float((await s.execute(_LAG, {"cutoff": await _cutoff(s, tenant_id)})).scalar_one())
    return swept


async def _audit(sessionmaker: async_sessionmaker[AsyncSession], sweep_id: int, tenant_id: uuid.UUID,
                 lag_s: float | None, *, failed: bool = False) -> None:  # fmt: skip
    """The tenant's one counts-only entry for the sweep, from the counts its batches kept, written with the mark that
    it's written, and whether its sweep failed: never twice, never lost, and a failure kept across a crash."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await s.execute(text("INSERT INTO retention_sweep_tenants (sweep_id, tenant_id) VALUES (:s, :t) "
                             "ON CONFLICT DO NOTHING"), {"s": sweep_id, "t": tenant_id})  # fmt: skip
        row = (await s.execute(text(f"SELECT {', '.join(COUNTED)}, audited_at FROM retention_sweep_tenants "  # noqa: S608
                                    "WHERE sweep_id = :s AND tenant_id = :t FOR UPDATE"),
                               {"s": sweep_id, "t": tenant_id})).one()  # fmt: skip
        if row.audited_at is not None:
            return
        counts: dict[str, object] = {kind: int(getattr(row, kind)) for kind in COUNTED}
        await audit.record(s, tenant_id=tenant_id, actor_id=None, action="retention.sweep",
                           target_type="retention_sweep", target_id=str(sweep_id), details=counts)  # fmt: skip
        await s.execute(text("UPDATE retention_sweep_tenants SET audited_at = clock_timestamp(), lag_s = :lag, "
                             "failed = :failed WHERE sweep_id = :s AND tenant_id = :t"),
                        {"lag": lag_s, "failed": failed, "s": sweep_id, "t": tenant_id})  # fmt: skip


async def _audited(sessionmaker: async_sessionmaker[AsyncSession], sweep_id: int, tenant_id: uuid.UUID) -> bool:
    async with sessionmaker() as s:
        await tenant_scope(s, tenant_id)
        found = await s.execute(text("SELECT 1 FROM retention_sweep_tenants WHERE sweep_id = :s AND tenant_id = :t "
                                     "AND audited_at IS NOT NULL"), {"s": sweep_id, "t": tenant_id})  # fmt: skip
        return found.first() is not None


async def _leftovers(sessionmaker: async_sessionmaker[AsyncSession], sweep_id: int) -> None:
    """Counts its batches kept that aren't audited yet, a tenant's no longer active included (erasing, say): audited
    as they are, nothing more deleted. Not a failure: what retention still owed that tenant is erasure's now."""
    async with sessionmaker() as s:  # ids only, across tenants (M3)
        unaudited = text("SELECT retention_sweep_unaudited(:s)")
        pending: list[uuid.UUID] = list((await s.execute(unaudited, {"s": sweep_id})).scalars())
    for tenant_id in pending:
        await _audit(sessionmaker, sweep_id, tenant_id, None)


async def _close(sessionmaker: async_sessionmaker[AsyncSession], sweep_id: int, *, abandoned: bool = False) -> Sweep:
    """The sweep ended: successful only if no tenant's sweep failed, as kept with its counts (and it wasn't abandoned);
    its tenants and lag from what was audited. Never while counts await their entry. Records older than KEPT go."""
    async with sessionmaker() as s, s.begin():
        audited = text("SELECT * FROM retention_sweep_summary(:s)")  # a summary, across tenants (M3)
        tenants, unaudited, failed, lag = (await s.execute(audited, {"s": sweep_id})).one()
        if unaudited:
            raise RuntimeError("A sweep's kept counts await their audit entries.")
        succeeded = not abandoned and not failed
        ended = {"ended_at": func.clock_timestamp(), "succeeded": succeeded, "tenants": tenants, "lag_s": lag}
        await s.execute(update(RetentionSweep).where(RetentionSweep.id == sweep_id).values(**ended))
        old = text("DELETE FROM retention_sweeps WHERE ended_at < statement_timestamp() - cast(:kept as interval)")
        await s.execute(old, {"kept": KEPT})  # their tenants' rows go with them
    return Sweep(sweep_id, succeeded, int(tenants), float(lag))


async def _sweep(sessionmaker: async_sessionmaker[AsyncSession], batch: int) -> Sweep:
    async with sessionmaker() as s, s.begin():
        unfinished = list((await s.execute(select(RetentionSweep.id).where(RetentionSweep.ended_at.is_(None))
                                           .order_by(RetentionSweep.id.desc()))).scalars())  # fmt: skip
        if unfinished:  # one that stopped before its end: resumed, so its deletions are audited once
            sweep_id = unfinished[0]
            log.info("retention_sweep_resumed", sweep=sweep_id)
        else:
            record = RetentionSweep()
            s.add(record)
            await s.flush()
            sweep_id = record.id
        active = text("SELECT id FROM tenants WHERE status = 'active' ORDER BY id")
        tenants: list[uuid.UUID] = list((await s.execute(active)).scalars())
    for stale in unfinished[1:]:  # older still (never under the lock): their kept counts audited, then ended
        await _leftovers(sessionmaker, stale)
        await _close(sessionmaker, stale, abandoned=True)
    for tenant_id in tenants:
        if await _audited(sessionmaker, sweep_id, tenant_id):
            continue  # done before the sweep stopped
        lag: float | None = None
        failed = False
        try:
            lag = (await sweep_tenant(sessionmaker, tenant_id, batch=batch, sweep_id=sweep_id)).lag_s
        except Exception as e:  # a tenant's failure never stops the others'; what it deleted is still audited
            log.error("retention_tenant_failed", tenant=str(tenant_id), error=type(e).__name__)
            failed = True
        await _audit(sessionmaker, sweep_id, tenant_id, lag, failed=failed)  # failing, it leaves the sweep to resume
    await _leftovers(sessionmaker, sweep_id)
    done = await _close(sessionmaker, sweep_id)
    log.info("retention_swept", sweep=sweep_id, succeeded=done.succeeded, tenants=done.tenants, lag_s=round(done.lag_s))
    return done


async def sweep(sessionmaker: async_sessionmaker[AsyncSession], *, batch: int = BATCH) -> Sweep | None:
    """Every active tenant swept and the sweep recorded; None when another process is sweeping. One sweep runs at a
    time, under a lock its connection holds (a process that dies releases it); a sweep that stopped before its end is
    resumed. A tenant whose sweep fails is logged (its error's type only) and the sweep marked unsuccessful; the others
    are still swept."""
    engine = sessionmaker.kw["bind"]
    async with engine.connect() as holder:
        holder = await holder.execution_options(isolation_level="AUTOCOMMIT")
        if not (await holder.execute(_LOCK)).scalar():
            log.info("retention_sweep_busy")
            return None
        try:
            return await _sweep(sessionmaker, batch)
        finally:
            await holder.execute(_UNLOCK)
