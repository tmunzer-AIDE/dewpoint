# SPDX-License-Identifier: Apache-2.0
"""The retention process's erasure pass (the 2b-4 outline's "A stopped or failed step resumes"): every erasure under
way that an operator hasn't stopped and whose next attempt is due is carried on from its recorded stage, each stage
until one isn't done yet. A stage not done waits (`WAIT`); one that fails records its fixed code, counts the attempt,
backs off (doubling, at most an hour) and alerts (`erasure_step_failed`, its error's type only), never skipping a
stage or an item; a stage still waiting an hour after it was entered alerts on every pass (`erasure_stalled`). Each
move to the next stage is audited, identifiers and counts only; entering stage 60 takes the tenant's lifecycle lock
exclusively, so the insert fence holds from then on for every writer. One process erases at a time, under a lock its
connection holds."""

import uuid
from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client
from temporalio.service import RPCError

from dewpoint.apps.erasure import bound, stages
from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.erasure import Stage, TenantErasure, TenantErasureItem
from dewpoint.core.tenancy import lifecycle

log = structlog.get_logger("dewpoint.erasure")
WAIT = timedelta(seconds=30)  # a stage not done yet is tried again after this
BACKOFF = timedelta(seconds=30)  # a failure's first wait, doubling
BACKOFF_MAX = timedelta(hours=1)
STALLED = timedelta(hours=1)  # a stage still waiting after this alerts on every pass
NAMESPACE_RETENTION_MAX = bound.NAMESPACE_RETENTION_MAX
_LOCK = text("SELECT pg_try_advisory_lock(hashtextextended('dewpoint:erasure', 0))")
_UNLOCK = text("SELECT pg_advisory_unlock(hashtextextended('dewpoint:erasure', 0))")
ORDER = list(Stage)


def failure_code(e: BaseException) -> str:
    """A failure's fixed code: no value, no message."""
    if isinstance(e, RPCError):
        return "temporal_failed"
    if isinstance(e, DBAPIError | OSError):
        return "database_failed" if isinstance(e, DBAPIError) else "unreachable"
    return "stage_failed"


async def _record(s: AsyncSession, tenant_id: uuid.UUID) -> TenantErasure | None:
    return (await s.execute(select(TenantErasure).where(TenantErasure.tenant_id == tenant_id)
                            .execution_options(populate_existing=True))).scalar_one_or_none()  # fmt: skip


async def _moved(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, done: Stage) -> Stage:
    """The erasure moved on from `done`, audited, if it's still there (a compare-and-set on its stage)."""
    following = ORDER[ORDER.index(done) + 1]
    async with sessionmaker() as s, s.begin():
        if following == Stage.EXECUTIONS:  # waits for every writer holding the lock shared; each later one sees it
            await lifecycle.hold_exclusive(s, tenant_id)
        now: datetime = (await s.execute(select(func.statement_timestamp()))).scalar_one()
        values: dict[str, object] = {"step": int(following), "step_at": now, "failure": None, "failed_at": None,
                                     "attempts": 0, "next_attempt_at": now}  # fmt: skip
        if following == Stage.EXECUTIONS:
            values["fenced_at"] = func.coalesce(TenantErasure.fenced_at, now)  # the insert fence, never lifted
        if done == Stage.PAUSE:
            values["paused_at"] = now  # the last schedule verified paused
        if done == Stage.EXECUTIONS:  # every execution found is verified gone: none of them closes after this
            values["latest_close"] = now
            values["check_after"] = now + NAMESPACE_RETENTION_MAX
        moved = await s.execute(
            update(TenantErasure)
            .where(TenantErasure.tenant_id == tenant_id, TenantErasure.step == int(done))
            .values(**values)
        )
        if not moved.rowcount:  # type: ignore[attr-defined]
            return done
        items = await s.execute(select(TenantErasureItem.state, func.count()).where(
            TenantErasureItem.tenant_id == tenant_id, TenantErasureItem.step == int(done)
        ).group_by(TenantErasureItem.state))  # fmt: skip
        details: dict[str, object] = {"step": int(done), "next": int(following),
                                      **{f"items_{state}": n for state, n in items}}  # fmt: skip
        await tenant_scope(s, tenant_id)
        await audit.record(s, tenant_id=tenant_id, actor_id=None, action="tenant.erasure.step", target_type="tenant",
                           target_id=str(tenant_id), details=details)  # fmt: skip
    return following


async def _waits(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, *,
                 failed: BaseException | None = None) -> None:  # fmt: skip
    async with sessionmaker() as s, s.begin():
        record = await _record(s, tenant_id)
        if record is None:
            return
        now: datetime = (await s.execute(select(func.statement_timestamp()))).scalar_one()
        if failed is None:
            record.next_attempt_at = now + WAIT
            if now - record.step_at >= STALLED:  # a run ignoring its cancel, a request left starting
                log.error("erasure_stalled", tenant=str(tenant_id), step=record.step,
                          waited_s=int((now - record.step_at).total_seconds()))  # fmt: skip
            return
        record.attempts += 1
        record.failure, record.failed_at = failure_code(failed), now
        record.next_attempt_at = now + min(BACKOFF * 2 ** min(record.attempts - 1, 7), BACKOFF_MAX)
        log.error("erasure_step_failed", tenant=str(tenant_id), step=record.step, code=record.failure,
                  attempts=record.attempts, error=type(failed).__name__)  # fmt: skip


async def _held(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, held: bound.Held) -> None:
    """Step 9 may not run yet: its fixed reason recorded (no attempt counted), its next look, an alert unless it's only
    waiting for the bound."""
    async with sessionmaker() as s, s.begin():
        now: datetime = (await s.execute(select(func.statement_timestamp()))).scalar_one()
        await s.execute(update(TenantErasure).where(TenantErasure.tenant_id == tenant_id).values(
            failure=held.reason, failed_at=now, next_attempt_at=held.until or now + bound.HOLD,
        ))  # fmt: skip
    if held.alert:
        log.error("erasure_held", tenant=str(tenant_id), reason=held.reason)
    else:
        log.info("erasure_held", tenant=str(tenant_id), reason=held.reason)


async def advance(sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, *,
                  batch: int = stages.BATCH) -> int | None:  # fmt: skip
    """The erasure carried on from its recorded stage until one isn't done (or it's stopped, or past the stages this
    pass runs); its stage then, None without one."""
    ctx = stages.Context(sessionmaker, client, tenant_id, batch)
    while True:
        async with sessionmaker() as s:
            record = await _record(s, tenant_id)
        if record is None or record.stopped_at is not None or record.completed_at is not None:
            return None if record is None else record.step
        stage = Stage(record.step)
        if stage == Stage.BOUND:
            try:
                if await bound.check(ctx) == "reopened":
                    continue
                return Stage.COMPLETE
            except bound.Held as held:
                await _held(sessionmaker, tenant_id, held)
            except Exception as e:
                await _waits(sessionmaker, tenant_id, failed=e)
            return stage
        run = stages.STAGES.get(stage)
        if run is None:
            return stage
        try:
            done = await run(ctx)
        except Exception as e:
            await _waits(sessionmaker, tenant_id, failed=e)
            return stage
        if not done:
            await _waits(sessionmaker, tenant_id)
            return stage
        await _moved(sessionmaker, tenant_id, stage)


async def erase_pass(sessionmaker: async_sessionmaker[AsyncSession], client: Client, *,
                     batch: int = stages.BATCH) -> dict[str, int]:  # fmt: skip
    """Every due erasure carried on; their stages counted (`busy`: another process is erasing)."""
    engine = sessionmaker.kw["bind"]
    async with engine.connect() as holder:
        holder = await holder.execution_options(isolation_level="AUTOCOMMIT")
        if not (await holder.execute(_LOCK)).scalar():
            return {"busy": 1}
        try:
            async with sessionmaker() as s:
                due = list((await s.execute(
                    select(TenantErasure.tenant_id).where(
                        TenantErasure.stopped_at.is_(None), TenantErasure.completed_at.is_(None),
                        TenantErasure.next_attempt_at <= func.statement_timestamp(),
                    ).order_by(TenantErasure.next_attempt_at)
                )).scalars())  # fmt: skip
            counts: dict[str, int] = {}
            for tenant_id in due:
                at = await advance(sessionmaker, client, tenant_id, batch=batch)
                counts[str(at)] = counts.get(str(at), 0) + 1
            return counts
        finally:
            await holder.execute(_UNLOCK)
