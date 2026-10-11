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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog
from sqlalchemy import exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client

from dewpoint.apps.dispatcher import evidence
from dewpoint.apps.erasure import stages, temporal
from dewpoint.core import blockers
from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.blockers import UnresolvedSend
from dewpoint.core.models.erasure import (
    NamespaceBoundary,
    Stage,
    TargetNamespaceRegistration,
    TargetQualificationInterval,
    TenantErasure,
    TenantErasureItem,
    TenantErasureKnown,
)
from dewpoint.core.models.runs import ExecutionEvidence

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
        await tenant_scope(s, ctx.tenant_id)
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
        await tenant_scope(s, ctx.tenant_id)
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
        await tenant_scope(s, tenant_id)
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
        await audit.record(s, tenant_id=tenant_id, actor_id=None, action="tenant.erasure.incident",
                           target_type="tenant", target_id=str(tenant_id),
                           details={"schedules": len(shown.schedules), "executions": len(shown.executions),
                                    "found": during})  # fmt: skip
    log.error("erasure_incident", tenant=str(tenant_id), schedules=len(shown.schedules),
              executions=len(shown.executions), found=during)  # fmt: skip


async def _complete(ctx: stages.Context, record: TenantErasure, boundary: str) -> None:
    async with ctx.sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        now = await _now(s)
        items = (await s.execute(select(func.count()).select_from(TenantErasureItem)
                                 .where(TenantErasureItem.tenant_id == ctx.tenant_id))).scalar_one()  # fmt: skip
        known = (await s.execute(select(func.count()).select_from(TenantErasureKnown)
                                 .where(TenantErasureKnown.tenant_id == ctx.tenant_id))).scalar_one()  # fmt: skip
        resolved = {str(provenance): int(n) for provenance, n in await s.execute(select(
            TenantErasureKnown.provenance, func.count()
        ).where(
            TenantErasureKnown.tenant_id == ctx.tenant_id,
            TenantErasureKnown.provenance.in_(("gone", "retained_out", "never_created")),
        ).group_by(TenantErasureKnown.provenance))}  # fmt: skip  # each reported apart (tasks 15, gate D)
        await s.execute(update(TenantErasure).where(TenantErasure.tenant_id == ctx.tenant_id).values(
            step=int(Stage.COMPLETE), completed_at=now, failure=None, failed_at=None, attempts=0,
        ))  # fmt: skip
        await s.execute(text("DELETE FROM tenant_erasure_items WHERE tenant_id = :t"), {"t": ctx.tenant_id})
        await s.execute(text("UPDATE tenants SET status = 'erased' WHERE id = :t"), {"t": ctx.tenant_id})
        details: dict[str, object] = {
            "tables": sorted([table, int(n)] for table, n in record.counts.items()),  # pairs: a name isn't a key
            "items": int(items), "known": int(known), "boundary": boundary,
            "gone": int(resolved.get("gone", 0)), "retained_out": int(resolved.get("retained_out", 0)),
            "never_created": int(resolved.get("never_created", 0)),
            "check_after": record.check_after.isoformat() if record.check_after else None,
            "completed_at": now.isoformat(), "backups_until": (now + BACKUPS_KEPT).isoformat(),
        }  # fmt: skip
        await audit.record(s, tenant_id=ctx.tenant_id, actor_id=None, action="tenant.erasure.complete",
                           target_type="tenant", target_id=str(ctx.tenant_id), details=details)  # fmt: skip


async def check(ctx: stages.Context) -> str:
    """Step 9: `complete`; `reopened` for what the final check found; `returned` through step 60 by the backstop.
    Raises Held while it may not run."""
    async with ctx.sessionmaker() as s:
        await tenant_scope(s, ctx.tenant_id)
        record = (await s.execute(select(TenantErasure).where(TenantErasure.tenant_id == ctx.tenant_id))).scalar_one()
        now = await _now(s)
        unresolved = int((await s.execute(text("SELECT erasure_unresolved(:t)"), {"t": ctx.tenant_id})).scalar_one())
    if unresolved:  # first, whatever else holds (2b-4b M4 recovery, design revision 5 §3): alerted as it starts and
        # as its count changes, its hourly look at info; nothing completes, no item is deleted
        alert = record.failure != "absence_unresolved" or record.absence_unresolved != unresolved
        async with ctx.sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            await s.execute(update(TenantErasure).where(TenantErasure.tenant_id == ctx.tenant_id)
                            .values(absence_unresolved=unresolved))  # fmt: skip
        raise Held("absence_unresolved", alert=alert)
    if record.check_after is None:  # nothing unresolved, no bound: a return missed (the backstop, revision 7 §3)
        log.error("bound_unset", tenant=str(ctx.tenant_id))
        if await resolve(ctx.sessionmaker, ctx.tenant_id, _nothing):
            return "returned"  # never a bound set here: step 60's advance sets it
        raise Held("bound_unset", alert=False)  # something unresolved again, or moved: its next look decides
    if FIRING_BOUND is None:
        raise Held("firing_bound_unproven")
    boundary = await _boundary(ctx, record)
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


async def _locked(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    """The erasure row's lock, which every transaction deciding a bound or a return takes first: step 60's advance,
    each resolution and the backstop serialize on it (design revision 7 §3)."""
    await s.execute(select(TenantErasure.tenant_id).where(TenantErasure.tenant_id == tenant_id).with_for_update())


async def _return_to_executions(s: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """Called with the erasure row locked, after a resolution (design revision 7 §3): with nothing left unresolved, an
    erasure past step 60 and not completed goes back to step 60 (a compare-and-set), its bound NULL, audited
    `tenant.erasure.resolved` (no incident: its fence stays, `fenced_at` unchanged). Step 60's next advance sets the
    bound, which so starts no earlier than the resolution. A stopped one waits there for its retry. Whether it
    returned."""
    if int((await s.execute(text("SELECT erasure_unresolved(:t)"), {"t": tenant_id})).scalar_one()):
        return False
    step = (await s.execute(select(TenantErasure.step).where(TenantErasure.tenant_id == tenant_id))).scalar()
    now = await _now(s)
    moved = await s.execute(update(TenantErasure).where(
        TenantErasure.tenant_id == tenant_id, TenantErasure.step > int(Stage.EXECUTIONS),
        TenantErasure.completed_at.is_(None),
    ).values(step=int(Stage.EXECUTIONS), step_at=now, next_attempt_at=now, latest_close=None, check_after=None,
             absence_unresolved=0, failure=None, failed_at=None, attempts=0))  # fmt: skip
    if not moved.rowcount:  # type: ignore[attr-defined]
        return False
    await audit.record(s, tenant_id=tenant_id, actor_id=None, action="tenant.erasure.resolved", target_type="tenant",
                       target_id=str(tenant_id), details={"step": step})  # fmt: skip
    log.info("erasure_resolved", tenant=str(tenant_id), step=step)
    return True


async def resolve(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID,
                  apply: Callable[[AsyncSession], Awaitable[bool]]) -> bool:  # fmt: skip
    """A resolution outside step 60 (design revision 7 §3), in one transaction of the tenant's: the erasure row locked
    first, then `apply` (whether it changed anything), then the return through step 60 when nothing is left
    unresolved. Whether it returned."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await _locked(s, tenant_id)
        if not await apply(s):
            return False
        return await _return_to_executions(s, tenant_id)


async def _nothing(_: AsyncSession) -> bool:
    """The backstop's resolution: none of its own, the return alone."""
    return True


async def _late_answers(ctx: stages.Context) -> None:
    """Each blocker of the tenant a late answer may have settled (`blockers.late_settled`), each in its own resolution.
    A blocker `gone` takes its workflow's known id with it (`absent` until then, task 13); one `removed` takes its id
    alone as `never_created`, unless a late start was recorded on it or anything of that id was ever shown
    (`_never_created`). `identified` again names a run the erasure has to handle: alerted."""
    async with ctx.sessionmaker() as s:  # platform-scoped, no row security: the tenant named
        held = (await s.execute(select(UnresolvedSend.request_id, UnresolvedSend.workflow_id).where(
            UnresolvedSend.tenant_id == ctx.tenant_id, UnresolvedSend.state != "identified"
        ))).all()  # fmt: skip
    for request_id, workflow_id in held:

        async def apply(s: AsyncSession, request_id: uuid.UUID = request_id, workflow_id: str = workflow_id) -> bool:
            late = (await s.execute(select(UnresolvedSend.late_start).where(UnresolvedSend.request_id == request_id)
                                    .with_for_update())).first()  # fmt: skip  # read before any removal
            settled = await blockers.late_settled(s, request_id)
            if settled == "gone":
                await stages._known(s, ctx, "execution", workflow_id, None, "gone")
            if settled == "removed" and late is not None and late.late_start is None:
                await _never_created(s, ctx, workflow_id, request_id)
            if settled == "identified":
                log.error("start_identified_late", tenant=str(ctx.tenant_id), request_id=str(request_id))
            elif settled is not None:
                log.info("start_settled_late", tenant=str(ctx.tenant_id), request_id=str(request_id), state=settled)
            return settled is not None

        await resolve(ctx.sessionmaker, ctx.tenant_id, apply)


def _retained_bound(intervals: Sequence[TargetQualificationInterval], registered: datetime, closed: datetime,
                    observed: datetime) -> datetime | None:  # fmt: skip
    """The earliest database time a NOT_FOUND of a run closed at `closed` shows it gone through Temporal's own retention
    (design revision 7 §4; ruling 5): `closed`, plus the highest retention maximum over the intervals covering the
    namespace's life from its registration to `closed` (each with archival off, together without a gap), plus the
    highest jitter maximum over those covering `closed`, plus the highest clock-skew maximum over those covering
    `closed` or the NOT_FOUND (`observed`), at least one covering it. None: an uncovered moment, a value missing
    (NULL), a negative one, no interval, or a close before the registration."""

    def covers(interval: TargetQualificationInterval, at: datetime) -> bool:
        return interval.valid_from <= at <= interval.valid_to

    if closed < registered:  # a run can't close in a namespace not yet registered: contradictory (the owner's item 4)
        return None
    life = sorted((i for i in intervals if i.valid_from <= closed and i.valid_to >= registered),
                  key=lambda i: i.valid_from)  # fmt: skip
    reach = registered
    for interval in life:
        if interval.valid_from > reach:
            return None
        reach = max(reach, interval.valid_to)
    at_close = [i for i in intervals if covers(i, closed)]
    if not any(covers(i, observed) for i in intervals):  # no skew qualified at the NOT_FOUND (the review's finding 2)
        return None
    skewed = [i for i in intervals if covers(i, closed) or covers(i, observed)]
    retention = [r for i in life if i.archival_off is True and (r := i.retention_max) is not None]
    jitter = [j for i in at_close if (j := i.jitter_max) is not None]
    skew = [k for i in skewed if (k := i.clock_skew_max) is not None]
    if not life or reach < closed or (len(retention), len(jitter), len(skew)) != (len(life), len(at_close),
                                                                                  len(skewed)):  # fmt: skip
        return None
    if any(value < timedelta(0) for value in (*retention, *jitter, *skew)):  # it would move the bound earlier
        return None
    return closed + max(retention) + max(jitter) + max(skew)


async def _qualify_retained_out(s: AsyncSession, known: TenantErasureKnown, namespace: str,
                                observed_at: datetime) -> bool:  # fmt: skip
    """A known run gone through Temporal's own retention (design revision 6 §4, revision 7 §4; ruling 5), in a
    resolution's transaction: an exact run Temporal never showed the erasure (`run_not_found`) whose close it reported
    (`closed_at`), no blocker naming its workflow, the namespace's qualification covering it (`_retained_bound`), and
    a NOT_FOUND observed at `observed_at` (database time, read before the describe) at or past that bound. Then
    `retained_out`, audited. Whether it qualified."""
    if (known.kind, known.provenance) != ("execution", "run_not_found") or known.run_id is None:
        return False
    if known.closed_at is None:
        return False
    blocked = exists().where(
        UnresolvedSend.tenant_id == known.tenant_id, UnresolvedSend.workflow_id == known.workflow_id
    )
    if (await s.execute(select(blocked))).scalar():
        return False
    registered = (await s.execute(select(TargetNamespaceRegistration.registered_at)
                                  .where(TargetNamespaceRegistration.namespace == namespace))).scalar()  # fmt: skip
    if registered is None:
        return False
    of_namespace = select(TargetQualificationInterval).where(TargetQualificationInterval.namespace == namespace)
    intervals = list((await s.execute(of_namespace)).scalars())
    bound = _retained_bound(intervals, registered, known.closed_at, observed_at)
    if bound is None or observed_at < bound:
        return False
    now = await _now(s)
    moved = await s.execute(update(TenantErasureKnown).where(
        TenantErasureKnown.id == known.id, TenantErasureKnown.provenance == "run_not_found",
        TenantErasureKnown.closed_at.is_not(None), ~blocked,
    ).values(provenance="retained_out", qualified_at=now))  # fmt: skip
    if not moved.rowcount:  # type: ignore[attr-defined]
        return False
    await audit.record(s, tenant_id=known.tenant_id, actor_id=None, action="tenant.erasure.retained_out",
                       target_type="tenant", target_id=str(known.tenant_id),
                       details={"run_id": known.run_id, "closed_at": known.closed_at.isoformat(),
                                "bound": bound.isoformat(), "observed_at": observed_at.isoformat(),
                                "namespace": namespace})  # fmt: skip
    log.info("erasure_retained_out", tenant=str(known.tenant_id))
    return True


async def _retained_out(ctx: stages.Context) -> None:
    """Each known run of the tenant the erasure never saw, with its close captured (`run_not_found`), described again,
    the database's time read first (the NOT_FOUND that follows is no earlier): a NOT_FOUND qualifies it if it can, in
    its own resolution (task 14). One shown is `found`'s, which reopens the erasure."""
    async with ctx.sessionmaker() as s:
        await tenant_scope(s, ctx.tenant_id)
        held = list((await s.execute(select(TenantErasureKnown).where(
            TenantErasureKnown.tenant_id == ctx.tenant_id, TenantErasureKnown.provenance == "run_not_found",
            TenantErasureKnown.run_id.is_not(None), TenantErasureKnown.closed_at.is_not(None),
        ))).scalars())  # fmt: skip
    for known in held:
        async with ctx.sessionmaker() as s:
            observed = await _now(s)
        if await temporal.execution(ctx.client, known.workflow_id, known.run_id) is not None:
            continue

        async def apply(s: AsyncSession, known: TenantErasureKnown = known, observed: datetime = observed) -> bool:
            return await _qualify_retained_out(s, known, ctx.client.namespace, observed)

        await resolve(ctx.sessionmaker, ctx.tenant_id, apply)


async def _ever_shown(s: AsyncSession, tenant_id: uuid.UUID, workflow_id: str) -> bool:
    """Whether anything of the workflow id was ever shown, or named by a run: a run of it known to the erasure (whatever
    its provenance), its id alone known as anything but `absent`, an item of it but its id alone `absent`, or a run of
    it in the evidence, seen or named. Fail-closed: any of them keeps `never_created` off."""
    known = select(TenantErasureKnown.id).where(
        TenantErasureKnown.tenant_id == tenant_id, TenantErasureKnown.kind == "execution",
        TenantErasureKnown.workflow_id == workflow_id,
        or_(TenantErasureKnown.run_id.is_not(None), TenantErasureKnown.provenance != "absent"),
    )  # fmt: skip
    items = select(TenantErasureItem.id).where(
        TenantErasureItem.tenant_id == tenant_id, TenantErasureItem.workflow_id == workflow_id,
        or_(TenantErasureItem.run_id.is_not(None), TenantErasureItem.state != "absent"),
    )  # fmt: skip
    evidence = select(ExecutionEvidence.id).where(
        ExecutionEvidence.tenant_id == tenant_id, ExecutionEvidence.workflow_id == workflow_id,
        or_(ExecutionEvidence.seen_at.is_not(None), ExecutionEvidence.run_id.is_not(None)),
    )  # fmt: skip
    for found_any in (known, items, evidence):
        if (await s.execute(found_any.limit(1))).first() is not None:
            return True
    return False


async def _never_created(s: AsyncSession, ctx: stages.Context, workflow_id: str, request_id: uuid.UUID) -> None:
    """A blocker removed as "certainly nothing" (every send answered as having created nothing), in its resolution's
    locked transaction: its request-unique id alone never existed, so it holds the erasure no more (the owner's gate-D
    ruling, item 2): its known row `never_created` and its step-60 item settled, audited. Never once anything of that
    id was shown (`_ever_shown`): contradictory, it stays `absent`."""
    if await _ever_shown(s, ctx.tenant_id, workflow_id):
        log.error("start_never_created_contradicted", tenant=str(ctx.tenant_id), request_id=str(request_id))
        return
    await s.execute(update(TenantErasureKnown).where(
        TenantErasureKnown.tenant_id == ctx.tenant_id, TenantErasureKnown.kind == "execution",
        TenantErasureKnown.workflow_id == workflow_id, TenantErasureKnown.run_id.is_(None),
        TenantErasureKnown.provenance == "absent",
    ).values(provenance="never_created"))  # fmt: skip
    await s.execute(update(TenantErasureItem).where(
        TenantErasureItem.tenant_id == ctx.tenant_id, TenantErasureItem.step == int(Stage.EXECUTIONS),
        TenantErasureItem.kind == "execution", TenantErasureItem.workflow_id == workflow_id,
        TenantErasureItem.run_id.is_(None), TenantErasureItem.state == "absent",
    ).values(state="verified", verified_at=func.statement_timestamp()))  # fmt: skip
    await audit.record(s, tenant_id=ctx.tenant_id, actor_id=None, action="tenant.erasure.never_created",
                       target_type="run_request", target_id=str(request_id))  # fmt: skip
    log.info("start_never_created", tenant=str(ctx.tenant_id), request_id=str(request_id))


async def reconcile_erased(sessionmaker: async_sessionmaker[AsyncSession], client: Client) -> dict[str, int]:
    """Every erasure rechecked (`erasures_rechecked`, 0062: completed, or past step 60 with anything unresolved,
    stopped or not): its late answers applied, its runs gone through Temporal's retention qualified, its ids described
    again and its prefix listed: anything found reopens it. On every pass, for good: it detects and repairs a late
    write on its next pass, never keeps absence true between passes."""
    async with sessionmaker() as s:  # ids only, across tenants (M3)
        done: list[uuid.UUID] = list((await s.execute(text("SELECT erasures_rechecked()"))).scalars())
    counts: dict[str, int] = {}
    for tenant_id in done:
        try:
            ctx = stages.Context(sessionmaker, client, tenant_id)
            await _late_answers(ctx)
            await _retained_out(ctx)
            shown = await found(ctx)
        except Exception as e:
            log.error("erasure_unreconciled", tenant=str(tenant_id), error=type(e).__name__)
            counts["failed"] = counts.get("failed", 0) + 1
            continue
        if shown:
            await reopen(sessionmaker, tenant_id, shown, during="reconciliation")
            counts["reopened"] = counts.get("reopened", 0) + 1
    return counts
