# SPDX-License-Identifier: Apache-2.0
"""An erasure's stages (the 2b-4 outline's steps 2 to 8; `core.models.erasure.Stage`), each `async (Context) -> bool`:
done, or not yet (the pass tries it again later). Each is idempotent: a stage that stops anywhere resumes from what it
recorded. A stage with an effect outside PostgreSQL works through its items, one row per schedule, run or execution,
each found, then requested, then verified by a read-back (a Temporal call can't share a transaction with its marker).

- 20 reconcile: no request still `starting` (the reconciler resolves each, §7.6).
- 31 pause: every Temporal schedule of the tenant, every incarnation each schedule was recorded under (each possible
  create's, tombstones' included), described paused, or absent.
- 32 inventory, before any schedule is deleted: every execution each schedule's describe lists (recent and running),
  every firing the ticks recorded, and every execution visibility finds under the schedules' prefix, each an item of 60.
- 33 unschedule: every schedule deleted, verified by a describe that finds nothing.
- 40 cancel: queued requests and pending events cancelled (`tenant_erased`), their counters released.
- 50 end runs: every running run cancelled in Temporal, verified ended in Dewpoint's projection and closed in Temporal.
  Its workers need the tenant's keys until then.
- 60 executions, entered under the tenant's lifecycle lock taken exclusively (the insert fence holds from here): every
  execution of the tenant enumerated from what's durable (runs, started requests, the run evidence, the ticks'
  records again, step 32's inventory), visibility adding, and each walked through its history (the run it continued
  from and as, every child it started), an open one terminated first; each deleted, verified when describing that
  exact run answers not-found (Temporal deletes asynchronously: one still there is tried again later).
- 70 keys: every data-key version and event keypair deleted: no process can unwrap one again (one that already did
  keeps it in its key cache for at most 5 minutes, `KeyringKeys`), so every remaining ciphertext of the tenant is
  unreadable from then on.
- 80 sweep: every row of the tenant deleted, in committed batches, counted; its tombstone anonymized."""

import contextlib
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client

from dewpoint.apps.erasure import temporal
from dewpoint.core.crypto.keyring import lock_scope
from dewpoint.core.db import tenant_scope
from dewpoint.core.ingress import keys as event_keys
from dewpoint.core.ingress.counters import release
from dewpoint.core.models.erasure import Stage, TenantErasureItem, TenantErasureKnown
from dewpoint.engine.runtime.ids import run_workflow_id

TENANT_ERASED = "tenant_erased"  # the reason a cancel records
BATCH = 100
PLACEHOLDER = "Erased tenant"  # the tombstone's name


@dataclass(frozen=True)
class Context:
    sessionmaker: async_sessionmaker[AsyncSession]
    client: Client
    tenant_id: uuid.UUID
    batch: int = BATCH


@contextlib.asynccontextmanager
async def _scoped(ctx: Context) -> AsyncIterator[AsyncSession]:
    """A transaction in the tenant's scope, committed at its end."""
    async with ctx.sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        yield s


async def _found(s: AsyncSession, ctx: Context, step: Stage, kind: str, found: Iterable[tuple[str, str | None]],
                 source: str) -> None:  # fmt: skip
    rows = [{"tenant_id": ctx.tenant_id, "step": int(step), "kind": kind, "workflow_id": w, "run_id": r,
             "source": source} for w, r in dict.fromkeys(found)]  # fmt: skip
    if rows:
        await s.execute(insert(TenantErasureItem).values(rows).on_conflict_do_nothing())


async def _known(s: AsyncSession, ctx: Context, kind: str, workflow_id: str, run_id: str | None) -> None:
    await s.execute(insert(TenantErasureKnown).values(tenant_id=ctx.tenant_id, kind=kind, workflow_id=workflow_id,
                                                      run_id=run_id).on_conflict_do_nothing())  # fmt: skip


async def _open(ctx: Context, step: Stage, after: int = 0) -> list[TenantErasureItem]:
    async with ctx.sessionmaker() as s:
        found = await s.execute(
            select(TenantErasureItem).where(TenantErasureItem.tenant_id == ctx.tenant_id,
                                            TenantErasureItem.step == int(step),
                                            TenantErasureItem.state != "verified", TenantErasureItem.id > after)
            .order_by(TenantErasureItem.id).limit(ctx.batch)
        )  # fmt: skip
        return list(found.scalars())


async def _each_open(ctx: Context, step: Stage) -> AsyncIterator[TenantErasureItem]:
    """Every open item of the stage, a batch at a time, those found meanwhile included: a pass reaches each, so an item
    that stays open never holds back the others."""
    after = 0
    while page := await _open(ctx, step, after):
        for item in page:
            yield item
        after = page[-1].id


async def _items(ctx: Context, step: Stage) -> list[TenantErasureItem]:
    async with ctx.sessionmaker() as s:
        found = await s.execute(select(TenantErasureItem).where(
            TenantErasureItem.tenant_id == ctx.tenant_id, TenantErasureItem.step == int(step)
        ).order_by(TenantErasureItem.id))  # fmt: skip
        return list(found.scalars())


async def _mark(ctx: Context, item: TenantErasureItem, state: str, *, known: str | None = None) -> None:
    async with ctx.sessionmaker() as s, s.begin():
        values: dict[str, object] = {"state": state, "attempts": TenantErasureItem.attempts + 1}
        if state == "verified":
            values["verified_at"] = text("statement_timestamp()")
        await s.execute(update(TenantErasureItem).where(TenantErasureItem.id == item.id).values(**values))
        if known is not None:
            await _known(s, ctx, known, item.workflow_id, item.run_id)


async def _all_verified(ctx: Context, step: Stage) -> bool:
    return not await _open(ctx, step)


# 20


async def reconcile(ctx: Context) -> bool:
    async with _scoped(ctx) as s:
        starting: int = (await s.execute(text("SELECT count(*) FROM run_requests WHERE status = 'starting'"))
                         ).scalar_one()  # fmt: skip
    return int(starting) == 0


# 31 to 33


async def _schedules(ctx: Context, step: Stage) -> None:
    """Every Temporal schedule the tenant may have: every incarnation each schedule was ever recorded under (each
    possible create's), its tombstones' included."""
    async with _scoped(ctx) as s:
        ids: list[str] = list((await s.execute(text("SELECT temporal_id FROM schedule_incarnations"))).scalars())
        await _found(s, ctx, step, "schedule", [(i, None) for i in ids], "incarnations")


async def pause(ctx: Context) -> bool:
    await _schedules(ctx, Stage.PAUSE)
    async for item in _each_open(ctx, Stage.PAUSE):
        shown = await temporal.schedule(ctx.client, item.workflow_id)
        if shown is None or shown.paused:
            await _mark(ctx, item, "verified")
        else:
            await temporal.pause_schedule(ctx.client, item.workflow_id)
            await _mark(ctx, item, "requested")  # verified by the next describe
    return await _all_verified(ctx, Stage.PAUSE)


async def inventory(ctx: Context) -> bool:
    """Every firing that can be found, before any schedule is deleted. Not claimed complete (a firing that never ran
    its first activity left no record, and visibility lags): completeness comes from step 9's bound."""
    listed: list[tuple[str, str | None]] = []
    for item in await _items(ctx, Stage.PAUSE):
        shown = await temporal.schedule(ctx.client, item.workflow_id)
        if shown is not None:
            listed.extend(shown.executions)
    visible = await temporal.listed(ctx.client, f"t:{ctx.tenant_id}:sched:")
    async with _scoped(ctx) as s:
        recorded = [(w, r) for w, r in (await s.execute(text("SELECT workflow_id, run_id FROM schedule_firings")))]
        await _found(s, ctx, Stage.EXECUTIONS, "execution", listed, "describe")
        await _found(s, ctx, Stage.EXECUTIONS, "execution", recorded, "firing")
        await _found(s, ctx, Stage.EXECUTIONS, "execution", visible, "visibility")
    return True


async def unschedule(ctx: Context) -> bool:
    """Every schedule stage 31 listed (a reopened erasure's included) deleted."""
    listed = [(i.workflow_id, None) for i in await _items(ctx, Stage.PAUSE)]
    async with _scoped(ctx) as s:
        await _found(s, ctx, Stage.UNSCHEDULE, "schedule", listed, "pause")
    async for item in _each_open(ctx, Stage.UNSCHEDULE):
        if await temporal.schedule(ctx.client, item.workflow_id) is None:
            await _mark(ctx, item, "verified", known="schedule")
        else:
            await temporal.delete_schedule(ctx.client, item.workflow_id)
            await _mark(ctx, item, "requested")
    return await _all_verified(ctx, Stage.UNSCHEDULE)


# 40

_QUEUED = text(
    "UPDATE run_requests SET status = 'cancelled', reason = :r, ended_at = statement_timestamp(), "
    "cancel_requested_at = coalesce(cancel_requested_at, statement_timestamp()) "
    "WHERE id IN (SELECT id FROM run_requests WHERE status = 'queued' LIMIT :n FOR UPDATE SKIP LOCKED) RETURNING id"
)
_EVENTS = text(
    "UPDATE inbound_events SET status = 'cancelled', reason = :r, ended_at = statement_timestamp() "
    "WHERE id IN (SELECT id FROM inbound_events WHERE endpoint_id = :e AND status = 'pending' LIMIT :n) "
    "RETURNING size_bytes"
)


async def cancel(ctx: Context) -> bool:
    async with _scoped(ctx) as s:
        queued: list[uuid.UUID] = list((await s.execute(_QUEUED, {"r": TENANT_ERASED, "n": ctx.batch})).scalars())
        for request_id in queued:
            await s.execute(text("SELECT end_unstarted_run(:i)"), {"i": request_id})  # a row an earlier attempt wrote
    async with _scoped(ctx) as s:  # the lock order: the endpoint's row, the tenant's counter row, the events
        endpoint = (await s.execute(text("SELECT endpoint_id FROM inbound_events WHERE status = 'pending' LIMIT 1"))
                    ).scalar()  # fmt: skip
        if endpoint is not None:
            await s.execute(text("SELECT id FROM webhook_endpoints WHERE id = :e FOR UPDATE"), {"e": endpoint})
            await s.execute(text("SELECT tenant_id FROM tenant_event_counters WHERE tenant_id = :t FOR UPDATE"),
                            {"t": ctx.tenant_id})  # fmt: skip
            ended = await s.execute(_EVENTS, {"r": TENANT_ERASED, "e": endpoint, "n": ctx.batch})
            sizes: list[int] = list(ended.scalars())
            await release(s, ctx.tenant_id, endpoint, sum(sizes), len(sizes))
    async with _scoped(ctx) as s:
        left: int = (await s.execute(text(
            "SELECT (SELECT count(*) FROM run_requests WHERE status = 'queued') "
            "+ (SELECT count(*) FROM inbound_events WHERE status = 'pending')"
        ))).scalar_one()  # fmt: skip
    return int(left) == 0


# 50


async def end_runs(ctx: Context) -> bool:
    async with _scoped(ctx) as s:
        query = text("SELECT id FROM runs WHERE parent_run_id IS NULL AND status = 'running'")
        roots: list[uuid.UUID] = list((await s.execute(query)).scalars())
        found: list[tuple[str, str | None]] = [(run_workflow_id(str(ctx.tenant_id), str(r)), None) for r in roots]
        await _found(s, ctx, Stage.END_RUNS, "run", found, "runs")
    async for item in _each_open(ctx, Stage.END_RUNS):
        root = item.workflow_id.rsplit(":", 1)[1]
        async with _scoped(ctx) as s:
            counted = text("SELECT count(*) FROM runs WHERE root_run_id = :r AND status = 'running'")
            running: int = (await s.execute(counted, {"r": uuid.UUID(root)})).scalar_one()
        shown = await temporal.execution(ctx.client, item.workflow_id, None)
        if int(running) == 0 and (shown is None or not shown.open):
            await _mark(ctx, item, "verified")
        elif item.state == "found" and shown is not None and shown.open:
            await temporal.cancel(ctx.client, item.workflow_id)
            await _mark(ctx, item, "requested")  # it ends through its own end write; a later pass verifies
    return await _all_verified(ctx, Stage.END_RUNS)


# 60


async def _enumerated(ctx: Context) -> None:
    visible = await temporal.listed(ctx.client, f"t:{ctx.tenant_id}:")
    async with _scoped(ctx) as s:
        ran: list[uuid.UUID] = list((await s.execute(text("SELECT id FROM runs"))).scalars())
        runs: list[tuple[str, str | None]] = [(run_workflow_id(str(ctx.tenant_id), str(r)), None) for r in ran]
        requested: list[uuid.UUID] = list(
            (await s.execute(text("SELECT id FROM run_requests WHERE status = 'started'"))).scalars()
        )
        started: list[tuple[str, str | None]] = [(run_workflow_id(str(ctx.tenant_id), str(r)), None) for r in requested]
        evidence: list[tuple[str, str | None]] = [
            (w, r) for w, r in await s.execute(text("SELECT workflow_id, run_id FROM execution_evidence"))
        ]
        firings: list[tuple[str, str | None]] = [  # again: a tick may record itself until the fence goes up
            (w, r) for w, r in await s.execute(text("SELECT workflow_id, run_id FROM schedule_firings"))
        ]
        for source, found in (("runs", runs), ("requests", started), ("evidence", evidence), ("firing", firings),
                              ("visibility", visible)):  # fmt: skip
            await _found(s, ctx, Stage.EXECUTIONS, "execution", found, source)


async def executions(ctx: Context) -> bool:
    await _enumerated(ctx)
    async for item in _each_open(ctx, Stage.EXECUTIONS):
        if item.run_id is None:  # an id alone: its chain's latest run, if Temporal shows one
            shown = await temporal.execution(ctx.client, item.workflow_id, None)
            if shown is None:
                await _mark(ctx, item, "verified", known="execution")
            else:
                async with _scoped(ctx) as s:
                    await _found(s, ctx, Stage.EXECUTIONS, "execution", [(item.workflow_id, shown.run_id)], "history")
            continue
        shown = await temporal.execution(ctx.client, item.workflow_id, item.run_id)
        if shown is None:
            await _mark(ctx, item, "verified", known="execution")
            continue
        if item.state == "found":
            if shown.open:  # nothing more starts from it once terminated, so its history is then whole
                await temporal.terminate(ctx.client, item.workflow_id, item.run_id)
            read = await temporal.read_run(ctx.client, item.workflow_id, item.run_id)
            chain = [(item.workflow_id, r) for r in (read.previous, read.next) if r]
            async with _scoped(ctx) as s:
                await _found(s, ctx, Stage.EXECUTIONS, "execution", chain, "history")
                await _found(s, ctx, Stage.EXECUTIONS, "execution", read.children, "child")
        await temporal.delete_execution(ctx.client, item.workflow_id, item.run_id)  # again, if it's still there
        await _mark(ctx, item, "requested")
    return await _all_verified(ctx, Stage.EXECUTIONS)


# 70


async def keys(ctx: Context) -> bool:
    async with _scoped(ctx) as s:
        await lock_scope(s, ctx.tenant_id)  # what creating, rotating, retiring and re-sealing take
        await event_keys.lock(s, ctx.tenant_id)  # the keypair lock, exclusively: recording an event takes it shared
        await s.execute(text("DELETE FROM data_keys WHERE tenant_id = :t"), {"t": ctx.tenant_id})
        await s.execute(text("DELETE FROM tenant_event_keys WHERE tenant_id = :t"), {"t": ctx.tenant_id})
    return True


# 80

# What the sweep deletes, in an order no key refuses, each `(table, its key)`: a run's steps go with it.
SWEPT: tuple[tuple[str, str], ...] = (
    ("claim_grants", "claim_id, run_id"), ("step_outputs", "id"), ("run_secret_index", "root_run_id"),
    ("run_slots", "run_id"), ("execution_evidence", "id"), ("schedule_firings", "workflow_id, run_id"),
    ("schedule_incarnations", "temporal_id"), ("schedule_intervals", "id"), ("runs", "root_run_id"),
    ("run_requests", "id"), ("run_inputs", "id"), ("inbound_events", "id"),
    ("trigger_bindings", "id"), ("webhook_endpoints", "id"), ("tenant_event_counters", "tenant_id"),
    ("csv_mappings", "workflow_id"), ("csv_uploads", "id"), ("schedules", "id"), ("workflow_versions", "id"),
    ("workflows", "id"), ("plugin_calls", "id"),  # 0042's: an options call names no connection, so nothing cascades
    ("connections", "id"), ("memberships", "id"), ("tenant_retention", "tenant_id"),
    ("tenant_run_limits", "tenant_id"), ("data_keys", "id"), ("tenant_event_keys", "tenant_id, version"),
    ("egress_allowlist", "id"), ("rate_buckets", "tenant_id, scope"), ("rate_scope_keys", "tenant_id"),  # 0041's
)  # fmt: skip
_CHOSEN = {"runs": "SELECT id FROM runs WHERE tenant_id = :t AND parent_run_id IS NULL LIMIT :n"}  # whole trees


async def _batch(s: AsyncSession, tenant_id: uuid.UUID, table: str, key: str, n: int) -> int:
    """One batch of the tenant's rows. Each statement names the tenant as well as its scope, so a table whose
    row-level security lapsed would still lose only the tenant's rows."""
    chosen = _CHOSEN.get(table, f"SELECT {key} FROM {table} WHERE tenant_id = :t LIMIT :n")  # noqa: S608  # fixed
    if table == "workflow_versions":  # a workflow names its active version: unnamed first
        await s.execute(text("UPDATE workflows SET active_version_id = NULL WHERE tenant_id = :t "
                             "AND active_version_id IS NOT NULL"), {"t": tenant_id})  # fmt: skip
    done = await s.execute(text(f"DELETE FROM {table} WHERE tenant_id = :t AND ({key}) IN ({chosen})"),  # noqa: S608
                           {"t": tenant_id, "n": n})  # fmt: skip
    return int(done.rowcount)  # type: ignore[attr-defined]


async def sweep(ctx: Context) -> bool:
    for table, key in SWEPT:
        while True:
            async with _scoped(ctx) as s:
                deleted = await _batch(s, ctx.tenant_id, table, key, ctx.batch)
                if deleted:
                    await s.execute(
                        text("UPDATE tenant_erasures SET counts = jsonb_set(counts, ARRAY[:k], "
                             "to_jsonb(coalesce((counts ->> :k)::bigint, 0) + :d)) WHERE tenant_id = :t"),
                        {"k": table, "d": deleted, "t": ctx.tenant_id},
                    )  # fmt: skip
            if deleted < ctx.batch:
                break
    async with _scoped(
        ctx
    ) as s:  # the retention sweep's own counts, once audited (it audits a leftover on its next sweep)
        await s.execute(text("DELETE FROM retention_sweep_tenants WHERE tenant_id = :t AND audited_at IS NOT NULL"),
                        {"t": ctx.tenant_id})  # fmt: skip
        counted = text("SELECT count(*) FROM retention_sweep_tenants WHERE tenant_id = :t")
        unaudited: int = (await s.execute(counted, {"t": ctx.tenant_id})).scalar_one()
        await s.execute(text("UPDATE tenants SET name = :n, slug = :s WHERE id = :t"),
                        {"n": PLACEHOLDER, "s": f"erased-{ctx.tenant_id}", "t": ctx.tenant_id})  # fmt: skip
    return int(unaudited) == 0 and await swept(ctx)


async def swept(ctx: Context) -> bool:
    """Whether no row of the tenant is left in any table the sweep owns."""
    async with _scoped(ctx) as s:
        for table, _ in SWEPT:
            left = text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE tenant_id = :t)")  # noqa: S608  # fixed names
            if (await s.execute(left, {"t": ctx.tenant_id})).scalar_one():
                return False
    return True


Run = Callable[[Context], Awaitable[bool]]
STAGES: dict[Stage, Run] = {
    Stage.RECONCILE: reconcile, Stage.PAUSE: pause, Stage.INVENTORY: inventory, Stage.UNSCHEDULE: unschedule,
    Stage.CANCEL: cancel, Stage.END_RUNS: end_runs, Stage.EXECUTIONS: executions, Stage.KEYS: keys,
    Stage.SWEEP: sweep,
}  # fmt: skip
