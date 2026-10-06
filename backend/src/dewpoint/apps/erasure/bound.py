# SPDX-License-Identifier: Apache-2.0
"""Step 9 and what follows completion (the 2b-4 outline's "Why every execution is gone" and "Reconciliation after
completion").

Every execution of the tenant that Dewpoint found was verified gone by stage 60; for the ones it couldn't enumerate,
completeness rests on Temporal's own retention (D3d, the owner's acceptance), which deletes a closed execution once the
namespace's retention has passed since it closed. So the final check may run only after the bound: the latest close
(stage 60's end) plus the platform's longest namespace retention, 30 days, the earliest point, never a deadline. It
also needs:
- the firing bound: that nothing of the tenant fires after the last verified pause, and every tick closed by a known
  time. **Unproven, so no erasure completes** (`firing_bound_unproven`, the owner's ruling on the M4 checkpoint).
  Its first premise now holds: a late create can't be unpaused, since each create is under its own incarnation,
  recorded before the call, and the erasure covers every one (`test_incarnations.py`; under one id it couldn't: a
  recreated schedule counts its conflict token from 1 again, `test_temporal_erasure_contract.py`). Its second
  doesn't: a tick has no execution timeout since M3 (the owner's ruling), and an ALLOW_ALL schedule, which the owner
  keeps, doesn't list its running ticks, so a tick no inventory found has no known close;
- a verified namespace-change boundary (D3g, `namespace_boundaries`), recorded on the erasure; one lost since holds it;
- the namespace's retention, read from Temporal, at most 30 days.
Each hold is recorded with its fixed reason and alerted on (waiting for the bound is no alert). Then the final check:
every execution and schedule found, and every id kept for reconciliation, described again, and a visibility query for
`t:<tenant>:`, must find nothing, and no row or key of the tenant may be left. Anything found reopens the erasure
(alerting, audited): its schedules from stage 31, its executions from stage 60, each with its own bound; the insert
fence stays up. Complete, the tenant is `erased`, the item rows go (the completion's audit entry keeps their counts and
the date backups taken before it expire), and the ids stay for the reconciliation, which describes each on every pass,
for good, and reopens the erasure for anything it finds."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client

from dewpoint.apps.dispatcher import evidence
from dewpoint.apps.erasure import stages, temporal
from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.erasure import (
    NamespaceBoundary,
    Stage,
    TenantErasure,
    TenantErasureItem,
    TenantErasureKnown,
)

log = structlog.get_logger("dewpoint.erasure")
FIRING_BOUND: str | None = None  # what proves no tenant firing after the last verified pause: nothing yet
NAMESPACE_RETENTION_MAX = timedelta(days=30)  # §10.2
BACKUPS_KEPT = timedelta(days=35)  # the guide's longest recommended backup retention
HOLD = timedelta(hours=1)  # a held erasure's next look


class Held(Exception):
    """The final check may not run yet: `reason`, a fixed code; `until`, its next look (else an hour); `alert`."""

    def __init__(self, reason: str, *, until: datetime | None = None, alert: bool = True) -> None:
        super().__init__(reason)
        self.reason, self.until, self.alert = reason, until, alert


@dataclass
class Found:
    schedules: list[str] = field(default_factory=list)
    executions: list[tuple[str, str | None]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.schedules or self.executions)


async def _now(s: AsyncSession) -> datetime:
    now: datetime = (await s.execute(select(func.statement_timestamp()))).scalar_one()
    return now


async def _boundary(ctx: stages.Context, record: TenantErasure) -> str:
    async with ctx.sessionmaker() as s, s.begin():
        current = (await s.execute(select(NamespaceBoundary.name).where(NamespaceBoundary.lost_at.is_(None))
                                   .order_by(NamespaceBoundary.id.desc()).limit(1))).scalar()  # fmt: skip
        if record.boundary is not None:
            if current != record.boundary:
                raise Held("boundary_lost")
            return record.boundary
        if current is None:
            raise Held("boundary_unverified")
        await s.execute(update(TenantErasure).where(TenantErasure.tenant_id == ctx.tenant_id).values(boundary=current))
        return current


async def found(ctx: stages.Context) -> Found:
    """What Temporal still shows of the tenant: every schedule and execution the erasure found or keeps, and anything
    visibility lists under its prefix."""
    async with ctx.sessionmaker() as s:
        items = [(i.kind, i.workflow_id, i.run_id) for i in (await s.execute(
            select(TenantErasureItem).where(TenantErasureItem.tenant_id == ctx.tenant_id,
                                            TenantErasureItem.kind.in_(("schedule", "execution")))
        )).scalars()]  # fmt: skip
        known = [(k.kind, k.workflow_id, k.run_id) for k in (await s.execute(
            select(TenantErasureKnown).where(TenantErasureKnown.tenant_id == ctx.tenant_id)
        )).scalars()]  # fmt: skip
    shown = Found()
    for kind, workflow_id, run_id in dict.fromkeys(items + known):
        if kind == "schedule":
            if await temporal.schedule(ctx.client, workflow_id) is not None:
                shown.schedules.append(workflow_id)
            continue
        execution = await temporal.execution(ctx.client, workflow_id, run_id)
        if execution is not None:
            shown.executions.append((workflow_id, execution.run_id))
    shown.executions.extend(await temporal.listed(ctx.client, f"t:{ctx.tenant_id}:"))
    shown.schedules = list(dict.fromkeys(shown.schedules))
    shown.executions = list(dict.fromkeys(shown.executions))
    return shown


async def reopen(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, shown: Found, *,
                 during: str) -> None:  # fmt: skip
    """The erasure reopened for what was found (`during`: the final check, or the reconciliation): its schedules from
    stage 31, its executions from stage 60, each with its own bound; audited and alerted on. Its fence stays."""
    rows = [{"tenant_id": tenant_id, "step": int(step), "kind": "schedule", "workflow_id": w, "run_id": None,
             "source": during} for w in shown.schedules for step in (Stage.PAUSE, Stage.UNSCHEDULE)]  # fmt: skip
    rows += [{"tenant_id": tenant_id, "step": int(Stage.EXECUTIONS), "kind": "execution", "workflow_id": w,
              "run_id": r, "source": during} for w, r in shown.executions]  # fmt: skip
    async with sessionmaker() as s, s.begin():
        for at in range(0, len(rows), stages.ITEMS_PER_STATEMENT):  # the driver's argument limit (C1)
            chunk = rows[at : at + stages.ITEMS_PER_STATEMENT]
            await s.execute(insert(TenantErasureItem).values(chunk).on_conflict_do_update(
                index_elements=[TenantErasureItem.tenant_id, TenantErasureItem.step, TenantErasureItem.workflow_id,
                                text("coalesce(run_id, '')")],
                set_={"state": "found", "verified_at": None, "source": during},
            ))  # fmt: skip
        now = await _now(s)
        await s.execute(update(TenantErasure).where(TenantErasure.tenant_id == tenant_id).values(
            step=int(Stage.PAUSE if shown.schedules else Stage.EXECUTIONS), step_at=now, completed_at=None,
            reopened_at=now,
            incidents=TenantErasure.incidents + 1, latest_close=None, check_after=None, failure=None, failed_at=None,
            attempts=0, next_attempt_at=now,
        ))  # fmt: skip
        await tenant_scope(s, tenant_id)
        await audit.record(s, tenant_id=tenant_id, actor_id=None, action="tenant.erasure.incident",
                           target_type="tenant", target_id=str(tenant_id),
                           details={"schedules": len(shown.schedules), "executions": len(shown.executions),
                                    "found": during})  # fmt: skip
    log.error("erasure_incident", tenant=str(tenant_id), schedules=len(shown.schedules),
              executions=len(shown.executions), found=during)  # fmt: skip


async def _complete(ctx: stages.Context, record: TenantErasure, boundary: str) -> None:
    async with ctx.sessionmaker() as s, s.begin():
        now = await _now(s)
        items = (await s.execute(select(func.count()).select_from(TenantErasureItem)
                                 .where(TenantErasureItem.tenant_id == ctx.tenant_id))).scalar_one()  # fmt: skip
        known = (await s.execute(select(func.count()).select_from(TenantErasureKnown)
                                 .where(TenantErasureKnown.tenant_id == ctx.tenant_id))).scalar_one()  # fmt: skip
        await s.execute(update(TenantErasure).where(TenantErasure.tenant_id == ctx.tenant_id).values(
            step=int(Stage.COMPLETE), completed_at=now, failure=None, failed_at=None, attempts=0,
        ))  # fmt: skip
        await s.execute(text("DELETE FROM tenant_erasure_items WHERE tenant_id = :t"), {"t": ctx.tenant_id})
        await tenant_scope(s, ctx.tenant_id)
        await s.execute(text("UPDATE tenants SET status = 'erased' WHERE id = :t"), {"t": ctx.tenant_id})
        details: dict[str, object] = {
            "tables": sorted([table, int(n)] for table, n in record.counts.items()),  # pairs: a name isn't a key
            "items": int(items), "known": int(known), "boundary": boundary,
            "check_after": record.check_after.isoformat() if record.check_after else None,
            "completed_at": now.isoformat(), "backups_until": (now + BACKUPS_KEPT).isoformat(),
        }  # fmt: skip
        await audit.record(s, tenant_id=ctx.tenant_id, actor_id=None, action="tenant.erasure.complete",
                           target_type="tenant", target_id=str(ctx.tenant_id), details=details)  # fmt: skip


async def check(ctx: stages.Context) -> str:
    """Step 9: `complete`, or `reopened` for what the final check found. Raises Held while it may not run."""
    async with ctx.sessionmaker() as s:
        record = (await s.execute(select(TenantErasure).where(TenantErasure.tenant_id == ctx.tenant_id))).scalar_one()
        now = await _now(s)
    if FIRING_BOUND is None:
        raise Held("firing_bound_unproven")
    boundary = await _boundary(ctx, record)
    if record.check_after is None:
        raise RuntimeError("An erasure at its bound without one.")
    if now < record.check_after:
        raise Held("bound_not_reached", until=record.check_after, alert=False)
    retention = await evidence.namespace_retention(ctx.client)
    if retention is None:
        raise Held("retention_unread")
    if retention > NAMESPACE_RETENTION_MAX:
        raise Held("retention_above_bound")
    shown = await found(ctx)
    if shown:
        await reopen(ctx.sessionmaker, ctx.tenant_id, shown, during="final_check")
        return "reopened"
    if not await stages.swept(ctx):
        raise Held("rows_left")
    await _complete(ctx, record, boundary)
    return "complete"


async def reconcile_erased(sessionmaker: async_sessionmaker[AsyncSession], client: Client) -> dict[str, int]:
    """Every completed erasure's ids described again, and its prefix listed: anything found reopens it. On every pass,
    for good: it detects and repairs a late write on its next pass, never keeps absence true between passes."""
    async with sessionmaker() as s:
        done = list((await s.execute(select(TenantErasure.tenant_id).where(TenantErasure.completed_at.is_not(None))
                                     .order_by(TenantErasure.tenant_id))).scalars())  # fmt: skip
    counts: dict[str, int] = {}
    for tenant_id in done:
        try:
            shown = await found(stages.Context(sessionmaker, client, tenant_id))
        except Exception as e:
            log.error("erasure_unreconciled", tenant=str(tenant_id), error=type(e).__name__)
            counts["failed"] = counts.get("failed", 0) + 1
            continue
        if shown:
            await reopen(sessionmaker, tenant_id, shown, during="reconciliation")
            counts["reopened"] = counts.get("reopened", 0) + 1
    return counts
