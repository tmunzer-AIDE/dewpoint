# SPDX-License-Identifier: Apache-2.0
"""The schedule sync (engine 2b spec §8.2; the owner's rulings on the milestone-3 gate): the reconciler's leader keeps
each Temporal Schedule in step with its row, reading across tenants only through `schedule_candidates()`.

The pinned SDK sends no conflict token (`ScheduleHandle.update()` builds its request without one), so this module
calls the service directly. Each change is: describe the schedule (its conflict token) → read the row's generation and
wanted state → one update with that token, holding the spec, the action (built by the SDK's own conversion, so the codec
seals it under the tenant), the pause state and the note `dewpoint generation <n>` together. Temporal discards an
update whose token a later update made stale, and still answers OK (`test_temporal_contract.py`), so an OK answer is no
evidence: a generation is marked synced only once a fresh describe shows its marker and a transaction confirms that the
row still has that generation and the writer still holds the leadership. A marker absent or different leaves the row
queued, and the next pass starts again.

Each create is under a fresh Temporal schedule id, an incarnation (`schedule_incarnations`, the owner's ruling on the
2b-4a M4 checkpoint): recorded and committed, under the tenant's lifecycle lock with the tenant active, before its one
create call, and never created again. A describe of the current incarnation that finds nothing records the next one.
So a create that lands late does so under an id no describe ever showed, and no update computed before it, an unpause
included, can target it: a schedule deleted and recreated under one id counts its conflict token from 1 again, and an
unpause computed before the deletion would land on the recreation (`test_temporal_erasure_contract.py`). Every
incarnation keeps its schedule's identity: its action's workflow id, its ticks', is the schedule's own. A late create
lands paused and stays so (the owner's reviews). A successor is recorded only under the schedule's own advisory lock,
held exclusively, once a describe made under it finds its predecessor still absent (a create that landed late is then
current, and synced). The sync updates an incarnation only holding that lock shared, from a read made after the
describe whose token the update carries, showing it still current and its schedule live, through the update: so no
successor is committed between that read and the update, and a sync that listed an incarnation as current before its
successor was recorded (or read the schedule before its deletion) can't use a token taken after it was paused for its
delete. The stray check, which describes every incarnation that isn't current, finds it and deletes it.

A create (no token) follows a describe that found nothing; one that finds the schedule already there leaves the row
queued for an update. A schedule is created paused, its note `dewpoint created` (2b-4a M4): only the token-bearing
update that follows, in the same pass or a later one, unpauses it, and an erasure's verified pause makes every update
computed before it stale.

The firings due while it waited paused are missed (D3f): Temporal neither catches them up nor counts them. The sync
accounts for them over persisted spans (`schedule_intervals`, the owner's ruling B), each classified from durable
evidence only, never left out and never shown as a zero it can't prove. Only one update is ever sent with the create's
token, so the first update to land (Temporal discards the others) is what Temporal shows until the sync sends another:
the sync records that landing (its generation, from its note; Temporal's update time; whether it left it paused; the
schedule's generation, read then) and then the incarnation's creation wait, each committed, before it sends any other
update to it. The wait runs from the schedule's creation (its first incarnation) or the incarnation's recording to that
landing. It's certainly missed, counted on the spec that landing wrote, only if the generation, which every change of
the schedule's, its workflow's or its tenant's state raises and which only rises, is the same at the incarnation's
recording (1, for a schedule's first), in the landing's note and once the landing was seen (an edit committed after
the sync read the row makes it land a stale update: the owner's review), and the landing unpaused it; intentionally
disabled if the same but paused; unknown otherwise. Until its span is recorded, the API shows the wait as pending:
open until the landing, then until its count. An incarnation that went (a describe found nothing, so the next one is
recorded) leaves a `lost` span, from its landing (else the start of its wait) to its successor's recording, written
with that recording: possibly missed if it may have fired (an unpause was sent to it, or it landed unpaused), unknown
otherwise; never counted, since seeing it unpaused proves it could fire, not that a tick did. A schedule deleted leaves
a `deleted` span if its incarnation never landed, or wasn't found again at or after the deletion. A count is recorded
on the row (`creation_misses`), audited and alerted on; an uncounted span is audited and alerted on too, and the API
says the schedule's accounting is incomplete.

An incarnation is deleted (a tombstone's, or a stray) only once a describe shows the sync's own pause for its delete
(paused, `dewpoint deleting`) and the count it shows is recorded, committed before the delete: a deleted schedule's
count can't be read again. That pause makes every conflict token taken before it stale, so an unpause a stale writer
holds in flight is discarded (merely paused isn't enough: the owner's review), and paused, Temporal's count of firings
missed past the catch-up window can't grow (`test_temporal_erasure_contract.py`).

The sync holds one transaction, with the tenant's lifecycle lock shared, from its read of the row through its Temporal
calls (each bounded by the call deadline) to its record: an erasure's step 1 waits for it, and a sync after it reads
`erasing`. A tenant that isn't active gets nothing created: its schedules are only paused or deleted.

A deletion's tombstone stays queued until a describe made a call deadline after the deletion finds nothing, so a stale
writer's create, started before the tombstone, can't bring the schedule back unseen; a tick that finds a tombstone
queues it again. The marker is evidence of a Dewpoint update, not of the whole state: editing a
schedule directly in Temporal isn't supported. Missed firings past the catch-up window are Temporal's own count, read
every five minutes for every incarnation, each incarnation's count kept apart, recorded on the schedule, audited and
alerted on.

An action carries no argument: its tick takes its schedule from its workflow id, and holds no payload under a tenant's
data key (the owner's M3 ruling, `apps.tick_contract`). The sync records the data-key version an action synced before
still names, from its own read-back (none for an action it wrote): `keys reencrypt` queues such a schedule, and its
next sync writes the action without its argument."""

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.api.schedule.v1 import SchedulePatch
from temporalio.api.workflowservice.v1 import (
    DeleteScheduleRequest,
    DescribeScheduleRequest,
    ListScheduleMatchingTimesRequest,
    PatchScheduleRequest,
    UpdateScheduleRequest,
)
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.codec import KEY_VERSION
from dewpoint.apps.dispatcher.tick import ADMISSION_QUEUE
from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.schedules import Schedule as Row
from dewpoint.core.models.schedules import ScheduleIncarnation as Incarnation
from dewpoint.core.models.schedules import ScheduleInterval as Span
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.models.workflows import Workflow
from dewpoint.core.tenancy import lifecycle
from dewpoint.engine.runtime.ids import schedule_workflow_id

log = structlog.get_logger("dewpoint.dispatcher.schedules")
MARK = "dewpoint generation {}"  # the only thing the sync writes into a schedule's note (the owner's ruling)
CREATED = "dewpoint created"  # a schedule's note from its paused create until the update that unpauses it
DELETING = "dewpoint deleting"  # an incarnation's note once paused for its delete: its count, then, is final
BATCH = 50  # schedules a pass
CALL_DEADLINE = timedelta(seconds=10)  # every call to Temporal here is bounded by it
TEMPORAL_REFUSED = "temporal_refused"
SYNC_FAILED = "sync_failed"
STRAYS_EVERY = timedelta(hours=1)  # each incarnation that isn't current, described again (stray_incarnations())
STRAY_RETRY = timedelta(minutes=5)  # one whose describe failed
# A span's class (D3f; the owner's ruling B): counted only when certain; intentionally disabled counts 0
CERTAIN, DISABLED, POSSIBLE, UNKNOWN = "certainly_missed", "intentionally_disabled", "possibly_missed", "unknown"


class _Leader(Protocol):
    async def leading(self) -> bool: ...


@dataclass(frozen=True)
class Described:
    token: bytes
    note: str
    missed: int  # firings Temporal skipped past the catch-up window, ever
    action_key_version: int | None = None  # the data-key version its action's payload names, as the codec wrote it
    paused: bool = False
    created_at: datetime | None = None  # Temporal's: when the schedule was created
    updated_at: datetime | None = None  # Temporal's: when its last update landed


def _action_key_version(answer: Any) -> int | None:
    """The data-key version the schedule's action is sealed under, from its payload's metadata, undecoded: an action
    synced before the tick contract carried the schedule's id, sealed; one written since carries nothing."""
    for payload in answer.schedule.action.start_workflow.input.payloads:
        raw = payload.metadata.get(KEY_VERSION, b"")
        if raw.isdigit() and len(raw) <= 9:  # what the codec writes, and refuses otherwise
            return int(raw)
    return None


@dataclass(frozen=True)
class _Wanted:
    generation: int
    schedule: Schedule | None  # None for a tombstone
    settled: bool = False  # a tombstone deleted at least a call deadline ago, by the database's clock
    active: bool = True  # the tenant's: one that isn't gets nothing created
    deleted_at: datetime | None = None  # a tombstone's


def incarnation_id(tenant_id: uuid.UUID, schedule_id: uuid.UUID, number: int) -> str:
    """The Temporal schedule id of a schedule's incarnation `number`: its own id with `~<n>`; 0, the id itself (the
    sync's before 2b-4a)."""
    base = schedule_workflow_id(str(tenant_id), str(schedule_id))
    return base if number == 0 else f"{base}~{number}"


async def _incarnations(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID,
                        schedule_id: uuid.UUID) -> list[Incarnation]:  # fmt: skip
    async with sessionmaker() as s:
        await tenant_scope(s, tenant_id)
        found = await s.execute(select(Incarnation).where(Incarnation.schedule_id == schedule_id)
                                .order_by(Incarnation.number))  # fmt: skip
        return list(found.scalars())


async def _wants_paused(s: AsyncSession, tenant_id: uuid.UUID, row: Row) -> bool:
    workflow = await s.get(Workflow, row.workflow_id, populate_existing=True)
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    active = tenant is not None and tenant.status == "active"
    return not row.enabled or workflow is None or not workflow.enabled or not active


def _generation_in(note: str) -> int | None:
    """The generation a note marks (`dewpoint generation <n>`); None for any other note (`dewpoint created`, the
    erasure's pause)."""
    head, _, tail = note.rpartition(" ")
    return int(tail) if head == MARK.format("").rstrip() and tail.isdigit() and len(tail) <= 18 else None


async def _has(s: AsyncSession, temporal_id: str, kind: str) -> bool:
    found = await s.scalar(select(func.count()).select_from(Span)
                           .where(Span.temporal_id == temporal_id, Span.kind == kind))  # fmt: skip
    return bool(found)


async def _wait_start(s: AsyncSession, found: Incarnation) -> tuple[datetime, bool]:
    """When an incarnation's creation wait began, and whether it's its schedule's first: the schedule's creation for
    its first, its recording otherwise."""
    earlier = await s.scalar(select(func.count()).select_from(Incarnation)
                             .where(Incarnation.schedule_id == found.schedule_id,
                                    Incarnation.number < found.number))  # fmt: skip
    if earlier:
        return found.recorded_at, False
    created = await s.scalar(select(Row.created_at).where(Row.id == found.schedule_id))
    return (created if created is not None else found.recorded_at), True


def _span(found: Incarnation, kind: str, start: datetime, end: datetime, class_: str, reason: str,
          missed: int | None = None) -> Span:  # fmt: skip
    return Span(tenant_id=found.tenant_id, schedule_id=found.schedule_id, temporal_id=found.temporal_id, kind=kind,
                starts_at=start, ends_at=end, class_=class_, missed=missed, reason=reason)  # fmt: skip


async def _creation(s: AsyncSession, client: Client | None, found: Incarnation) -> Span:
    """An incarnation's creation wait, from its start to its first landed update (`landed_at`): certainly missed,
    counted on the spec that update wrote (no other update is sent before this is recorded), only if the generation
    didn't move from its start through that update (the one it was recorded under, the one the update wrote, and the
    schedule's own read once the update was seen, all the same: generations only rise) and the update unpaused it;
    intentionally disabled if the same but paused; unknown otherwise, or if it would be certain but can't be counted
    any more (`client` None: it went)."""
    start, first = await _wait_start(s, found)
    end = found.landed_at or start
    unchanged = (found.generation is not None and found.landed_generation == found.generation
                 and found.landed_row_generation == found.generation
                 and (not first or found.generation == 1))  # fmt: skip
    if not unchanged:
        return _span(found, "creation", start, end, UNKNOWN, "changed_while_waiting")
    if found.landed_paused:
        return _span(found, "creation", start, end, DISABLED, "disabled_while_waiting", 0)
    if client is None:
        return _span(found, "creation", start, end, UNKNOWN, "gone_before_counted")
    missed = len(await _matching(client, found.temporal_id, start, end))
    return _span(found, "creation", start, end, CERTAIN, "created_paused", missed)


async def _went(
    s: AsyncSession, found: Incarnation, kind: str, until: datetime, *, present: bool = False
) -> list[Span]:
    """What an incarnation that went leaves unaccounted, up to `until` (its successor's recording, or its schedule's
    deletion; `present`: a describe found it there at or after the deletion): its creation wait, if it landed and
    wasn't counted (it can't be any more), and the span from its last evidence (its landing; else its wait's start; its
    recording, for one from before the migration) on: possibly missed if it may have fired, unknown otherwise."""
    spans = []
    start, _ = await _wait_start(s, found)
    if found.landed_at is not None and not await _has(s, found.temporal_id, "creation"):
        spans.append(await _creation(s, None, found))
    fired = found.unpause_sent_at is not None or found.landed_paused is False
    class_ = POSSIBLE if fired else UNKNOWN
    if found.backfilled:
        if not present:
            spans.append(_span(found, kind, found.recorded_at, until, UNKNOWN, f"{kind}_from_before_migration"))
    elif found.landed_at is None:
        lost = "lost_after_unpause" if fired else "lost_before_unpause"
        spans.append(_span(found, kind, start, until, class_, "deleted_before_landing" if kind == "deleted" else lost))
    elif not present:
        lost = "lost_after_unpause" if fired else "lost_before_unpause"
        spans.append(_span(found, kind, found.landed_at, until, class_,
                           "gone_before_deletion" if kind == "deleted" else lost))  # fmt: skip
    return spans


async def _add(s: AsyncSession, span: Span) -> None:
    """A span recorded (one of each kind an incarnation: a second, raced, is refused, with its count); a count added
    to the schedule's, audited and alerted on; an uncounted span audited and alerted on."""
    s.add(span)
    await s.flush()
    details: dict[str, object] = {"schedule_id": str(span.schedule_id)}
    if span.class_ == CERTAIN and span.missed:
        await s.execute(update(Row).where(Row.id == span.schedule_id)
                        .values(creation_misses=Row.creation_misses + span.missed))  # fmt: skip
        log.error("schedule_firings_missed", schedule_id=str(span.schedule_id), missed=span.missed)
        action, details = "schedule.missed", {**details, "missed": span.missed, "while": span.reason}
    elif span.class_ in (POSSIBLE, UNKNOWN):
        log.error("schedule_firings_unaccounted", schedule_id=str(span.schedule_id), class_=span.class_,
                  reason=span.reason)  # fmt: skip
        action = "schedule.unaccounted"
        details = {**details, "class": span.class_, "reason": span.reason, "from": span.starts_at.isoformat(),
                   "to": span.ends_at.isoformat()}  # fmt: skip
    else:
        return
    await audit.record(s, tenant_id=span.tenant_id, actor_id=None, action=action, target_type="schedule",
                       target_id=str(span.schedule_id), details=details)  # fmt: skip


def _hold(schedule_id: uuid.UUID, *, exclusive: bool) -> Any:
    """The schedule's own lock (transaction-scoped, advisory): every sync transaction that may update one of its
    incarnations holds it shared, from its currency read through its update; a successor is recorded holding it
    exclusively (the owner's review: a successor committed between that read and the update would leave the update
    unpausing an incarnation no longer current)."""
    lock = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    return text(f"select {lock}(hashtextextended(:k, 0))").bindparams(k=f"dewpoint:schedule:{schedule_id}")


async def _incarnate(sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID,
                     schedule_id: uuid.UUID) -> str | None:  # fmt: skip
    """The next incarnation's id, recorded and committed before any create under it, with its schedule's generation,
    and the span the one before it leaves, if the tenant is active, the schedule live, and the one before it is still
    absent when described again under the schedule's lock, held exclusively (no update to it is in progress then, and
    none starts until this commits); None otherwise (a create that landed late is there after all: it's current, and
    the next pass syncs it)."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        if not await lifecycle.is_active(s, tenant_id):
            return None
        row = await s.get(Row, schedule_id, populate_existing=True)
        if row is None or row.deleted_at is not None:
            return None
        await s.execute(_hold(schedule_id, exclusive=True))
        last = await s.scalar(select(Incarnation).where(Incarnation.schedule_id == schedule_id)
                              .order_by(Incarnation.number.desc()).limit(1))  # fmt: skip
        if last is not None and await described(client, last.temporal_id) is not None:
            return None
        generation = await s.scalar(select(Row.generation).where(Row.id == schedule_id))
        number = last.number + 1 if last is not None else 1
        now: datetime = (await s.execute(select(func.now()))).scalar_one()
        temporal_id = incarnation_id(tenant_id, schedule_id, number)
        s.add(Incarnation(temporal_id=temporal_id, tenant_id=tenant_id, schedule_id=schedule_id, number=number,
                          generation=generation, recorded_at=now))  # fmt: skip
        if last is not None and not await _has(s, last.temporal_id, "lost"):
            for span in await _went(s, last, "lost", now):
                await _add(s, span)
    return temporal_id


async def _landing(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, temporal_id: str,
    shown: Described, held: AsyncSession | None = None,
) -> None:  # fmt: skip
    """An incarnation Temporal shows past its create: its first landed update recorded and committed, then its creation
    wait, before any other update is sent to it (a count that fails leaves the landing, and the next pass counts it,
    sending nothing before), with its schedule's generation read then. Nothing for a note no sync update wrote (still
    `dewpoint created`, or paused for a delete or an erasure), or for one from before the migration. Within the sync's
    transaction (`held`), the wait is recorded in it: the insert fence takes the tenant's lifecycle lock shared, which
    another transaction would wait for behind an erasure's step 1, itself waiting for the sync's."""
    if _generation_in(shown.note) is None:
        return
    async with sessionmaker() as s, s.begin():  # an update: the fence doesn't apply
        await tenant_scope(s, tenant_id)
        known = shown.updated_at is not None  # else its time isn't known: neither is its generation's span
        await s.execute(update(Incarnation)
                        .where(Incarnation.temporal_id == temporal_id, Incarnation.landed_at.is_(None),
                               Incarnation.backfilled.is_(False))
                        .values(landed_generation=_generation_in(shown.note) if known else None,
                                landed_row_generation=select(Row.generation).where(Row.id == Incarnation.schedule_id)
                                .scalar_subquery(),
                                landed_at=shown.updated_at if known else func.statement_timestamp(),
                                landed_paused=shown.paused, created_at=shown.created_at))  # fmt: skip
    if held is not None:
        await _counted(held, client, temporal_id)
        return
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await _counted(s, client, temporal_id)


async def _counted(s: AsyncSession, client: Client, temporal_id: str) -> None:
    found = await s.get(Incarnation, temporal_id, populate_existing=True)
    if found is None or found.backfilled or found.landed_at is None or await _has(s, temporal_id, "creation"):
        return
    await _add(s, await _creation(s, client, found))


async def _unpausing(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, temporal_id: str) -> None:
    """Before the first update that unpauses an incarnation is sent: when, committed. An incarnation without it never
    fired (its one create was paused, and only the sync unpauses)."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await s.execute(update(Incarnation).where(Incarnation.temporal_id == temporal_id,
                                                  Incarnation.unpause_sent_at.is_(None))
                        .values(unpause_sent_at=func.statement_timestamp()))  # fmt: skip


async def _missed(s: AsyncSession, tenant_id: uuid.UUID, schedule_id: uuid.UUID, temporal_id: str, shown: int) -> int:
    """Temporal's count of an incarnation's firings missed past its catch-up window, as a describe showed it: recorded
    on it, its increase added to its schedule's, audited and alerted on. The increase."""
    recorded = await s.scalar(select(Incarnation.misses).where(Incarnation.temporal_id == temporal_id)
                              .with_for_update())  # fmt: skip
    if recorded is None or shown <= recorded:
        return 0
    missed = shown - recorded
    await s.execute(update(Incarnation).where(Incarnation.temporal_id == temporal_id).values(misses=shown))
    await s.execute(update(Row).where(Row.id == schedule_id).values(misses=Row.misses + missed))
    log.error("schedule_firings_missed", schedule_id=str(schedule_id), missed=missed)
    await audit.record(s, tenant_id=tenant_id, actor_id=None, action="schedule.missed", target_type="schedule",
                       target_id=str(schedule_id),
                       details={"schedule_id": str(schedule_id), "missed": missed})  # fmt: skip
    return missed


async def _pause(client: Client, schedule_id: str) -> None:
    try:
        await client.workflow_service.patch_schedule(
            PatchScheduleRequest(namespace=client.namespace, schedule_id=schedule_id,
                                 patch=SchedulePatch(pause=DELETING), identity=client.identity,
                                 request_id=str(uuid.uuid4())),
            timeout=CALL_DEADLINE,
        )  # fmt: skip
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise


async def _deletable(s: AsyncSession, client: Client, tenant_id: uuid.UUID, schedule_id: uuid.UUID, temporal_id: str,
                     found: Described) -> bool:  # fmt: skip
    """Whether an incarnation a describe found may be deleted now: only once that describe shows the sync's own pause
    for its delete (paused, `dewpoint deleting`), and the count it shows is already recorded, committed before the
    delete (a deleted schedule's count can't be read again). That pause patch made every conflict token taken before
    it stale, so an update computed earlier, an unpause a stale writer holds in flight included, is discarded, and any
    update landing after it would replace its note; paused, its count can't grow (`test_temporal_erasure_contract.py`).
    Merely paused isn't enough (the owner's review). Otherwise this pauses it, or records its count in `s`, and its
    delete waits for a later pass."""
    if not (found.paused and found.note == DELETING):
        await _pause(client, temporal_id)
        return False
    return not await _missed(s, tenant_id, schedule_id, temporal_id, found.missed)


async def _still_current(s: AsyncSession, schedule_id: uuid.UUID, temporal_id: str) -> bool:
    """Whether `temporal_id` is still its live schedule's current incarnation, read after the describe whose token an
    update to it would carry (the owner's review: a sync that listed it as current may describe it only after a
    successor was recorded and the stray check paused it for its delete, taking a token that pause doesn't fence). A
    successor or a deletion committed before this read is seen; one committed after it comes before any pause for its
    delete, which makes that token stale."""
    live = await s.scalar(select(Row.deleted_at.is_(None)).where(Row.id == schedule_id))
    newest = await s.scalar(select(Incarnation.temporal_id).where(Incarnation.schedule_id == schedule_id)
                            .order_by(Incarnation.number.desc()).limit(1))  # fmt: skip
    return bool(live) and newest == temporal_id


async def _seen(s: AsyncSession, temporal_ids: list[str], at: Any) -> None:
    """Incarnations a describe found, from `at` (taken before it) on."""
    if temporal_ids:
        await s.execute(update(Incarnation).where(Incarnation.temporal_id.in_(temporal_ids)).values(seen_at=at))


async def _after_read() -> None:
    """Runs between the row's read and the update. A no-op; the race tests change things here."""


async def described(client: Client, schedule_id: str) -> Described | None:
    try:
        answer = await client.workflow_service.describe_schedule(
            DescribeScheduleRequest(namespace=client.namespace, schedule_id=schedule_id), timeout=CALL_DEADLINE
        )
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return None
        raise
    info = answer.info
    return Described(
        answer.conflict_token, answer.schedule.state.notes, info.missed_catchup_window, _action_key_version(answer),
        answer.schedule.state.paused, info.create_time.ToDatetime(UTC) if info.HasField("create_time") else None,
        info.update_time.ToDatetime(UTC) if info.HasField("update_time") else None,
    )  # fmt: skip


async def _create(client: Client, schedule_id: str, schedule: Schedule) -> bool:
    """False when a schedule is already there: an update, with a token, is the next pass's."""
    try:
        await client.create_schedule(schedule_id, schedule, rpc_timeout=CALL_DEADLINE)
    except ScheduleAlreadyRunningError:
        return False
    return True


async def _update(client: Client, schedule_id: str, schedule: Schedule, token: bytes) -> None:
    await client.workflow_service.update_schedule(
        UpdateScheduleRequest(
            namespace=client.namespace, schedule_id=schedule_id, schedule=await schedule._to_proto(client),
            conflict_token=token, identity=client.identity, request_id=str(uuid.uuid4()),
        ),
        timeout=CALL_DEADLINE,
    )  # fmt: skip


async def _delete(client: Client, schedule_id: str) -> None:
    try:
        await client.workflow_service.delete_schedule(
            DeleteScheduleRequest(namespace=client.namespace, schedule_id=schedule_id, identity=client.identity),
            timeout=CALL_DEADLINE,
        )
    except RPCError as e:
        if e.status != RPCStatusCode.NOT_FOUND:
            raise


async def _matching(client: Client, schedule_id: str, start: datetime, end: datetime) -> list[datetime]:
    """The times the schedule's spec matched in the window, as Temporal computes them."""
    if end <= start:
        return []
    request = ListScheduleMatchingTimesRequest(namespace=client.namespace, schedule_id=schedule_id)
    request.start_time.FromDatetime(start)
    request.end_time.FromDatetime(end)
    answer = await client.workflow_service.list_schedule_matching_times(request, timeout=CALL_DEADLINE)
    return [t.ToDatetime(UTC) for t in answer.start_time]


def created(schedule: Schedule) -> Schedule:
    """What the create writes: the wanted schedule, paused, its note `dewpoint created`."""
    return dataclasses.replace(schedule, state=ScheduleState(paused=True, note=CREATED))


def temporal(row: Row, *, paused: bool) -> Schedule:
    """The Temporal Schedule a row wants, its generation in the note."""
    if row.cron is not None:
        spec = ScheduleSpec(cron_expressions=[row.cron], time_zone_name=row.time_zone)
    else:
        every = timedelta(seconds=row.every_s or 0)
        spec = ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every, offset=timedelta(seconds=row.offset_s))])
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "ScheduleTick", id=schedule_workflow_id(str(row.tenant_id), str(row.id)), task_queue=ADMISSION_QUEUE,
        ),  # no argument: the tick's workflow id names its schedule
        spec=spec,
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL,
                              catchup_window=timedelta(seconds=row.catchup_window_s)),
        state=ScheduleState(paused=paused, note=MARK.format(row.generation)),
    )  # fmt: skip


async def _wanted(s: AsyncSession, tenant_id: uuid.UUID, schedule_id: uuid.UUID) -> _Wanted | None:
    await tenant_scope(s, tenant_id)
    row = await s.get(Row, schedule_id, populate_existing=True)
    if row is None:
        return None
    if row.deleted_at is not None:
        settled = await s.scalar(select(Row.deleted_at < func.statement_timestamp() - CALL_DEADLINE)
                                 .where(Row.id == schedule_id))  # fmt: skip
        return _Wanted(row.generation, None, bool(settled), deleted_at=row.deleted_at)
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    active = tenant is not None and tenant.status == "active"
    paused = await _wants_paused(s, tenant_id, row)
    return _Wanted(row.generation, temporal(row, paused=paused), active=active)


async def _record(
    s: AsyncSession, leader: _Leader, schedule_id: uuid.UUID, generation: int, action_key_version: int | None = None,
    seen: str | None = None,
) -> str:  # fmt: skip
    """The generation marked synced, in the sync's transaction, with the key version its action was read back under (a
    live schedule's, if it still names one) and the incarnation its read-back found (`seen`, from the transaction's
    start, before that read), if the row still has it and this writer still leads."""
    if not await leader.leading():
        return "not_leading"
    values: dict[str, Any] = {"synced_generation": generation, "sync_error": None, "sync_error_at": None,
                              "action_key_version": action_key_version}  # fmt: skip
    done = await s.execute(update(Row).where(Row.id == schedule_id, Row.generation == generation).values(**values))
    if not done.rowcount:  # type: ignore[attr-defined]
        return "pending"
    if seen is not None:
        await _seen(s, [seen], func.now())
    return "synced"


async def sync_one(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, leader: _Leader, tenant_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> str:  # fmt: skip
    """One schedule brought toward its row: `synced`, `pending` (left queued), `deleting`, `not_leading`, `gone`."""
    known = await _incarnations(sessionmaker, tenant_id, schedule_id)
    current = known[-1] if known else None
    before = await described(client, current.temporal_id) if current is not None else None  # its token, first
    if current is not None and before is not None:  # its landing and creation wait recorded before any other update
        await _landing(sessionmaker, client, tenant_id, current.temporal_id, before)
    fresh = await _incarnate(sessionmaker, client, tenant_id, schedule_id) if before is None else None  # committed
    async with sessionmaker() as s, s.begin():  # held through the Temporal calls: an erasure's step 1 waits for it
        await tenant_scope(s, tenant_id)
        await lifecycle.hold_shared(s, tenant_id)
        await s.execute(_hold(schedule_id, exclusive=False))  # no successor recorded until it commits
        wanted = await _wanted(s, tenant_id, schedule_id)
        if wanted is None:
            return "gone"
        await _after_read()
        if wanted.schedule is None:  # a tombstone: every incarnation paused, its count read, then deleted
            shown = [(i.temporal_id, await described(client, i.temporal_id)) for i in known]
            live = [listed for listed, found in shown if found is not None]
            for listed, found in shown:
                if found is not None and await _deletable(s, client, tenant_id, schedule_id, listed, found):
                    await _delete(client, listed)
            await _seen(s, live, func.now())  # found at or after the deletion: there until it
            if live or not wanted.settled:
                return "deleting"  # absent, but a create started before the tombstone could still land
            if current is not None and wanted.deleted_at is not None and not await _has(s, current.temporal_id,
                                                                                         "deleted"):  # fmt: skip
                present = current.seen_at is not None and current.seen_at >= wanted.deleted_at
                for span in await _went(s, current, "deleted", wanted.deleted_at, present=present):
                    await _add(s, span)
            return await _record(s, leader, schedule_id, wanted.generation)
        if before is None and not wanted.active:  # a tenant being erased: nothing created
            return await _record(s, leader, schedule_id, wanted.generation)
        mark = MARK.format(wanted.generation)
        temporal_id = current.temporal_id if before is not None and current is not None else fresh
        if temporal_id is None:  # nothing to create under: the tenant or the row changed since
            return "pending"
        if before is None:  # the only create ever sent under this incarnation
            if not await _create(client, temporal_id, created(wanted.schedule)):
                return "pending"
            before = await described(client, temporal_id)
            if before is None:
                return "pending"
        if not await _still_current(s, schedule_id, temporal_id):  # read after the describe whose token it'd carry
            return "pending"
        if before.note != mark:
            if not wanted.schedule.state.paused:  # an update that unpauses it: recorded first, committed
                await _unpausing(sessionmaker, tenant_id, temporal_id)
            await _update(client, temporal_id, wanted.schedule, before.token)
        after = await described(client, temporal_id)  # the read-back: an OK answer proves nothing
        if after is not None:
            await _landing(sessionmaker, client, tenant_id, temporal_id, after, s)
        if after is None or after.note != mark:
            return "pending"
        for stray in [i.temporal_id for i in known if i.temporal_id != temporal_id]:  # a late create of an earlier one
            found = await described(client, stray)
            if found is not None:
                if await _deletable(s, client, tenant_id, schedule_id, stray, found):
                    await _delete(client, stray)
                return "pending"  # its absence is read back by a later pass
        return await _record(s, leader, schedule_id, wanted.generation, after.action_key_version, seen=temporal_id)


async def _failed(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, schedule_id: uuid.UUID, code: str
) -> None:
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await s.execute(update(Row).where(Row.id == schedule_id).values(sync_error=code, sync_error_at=func.now()))


async def sync_schedules(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, leader: _Leader, *, batch: int = BATCH
) -> dict[str, int]:
    """One pass over the queued schedules, each isolated: a failure is recorded with a fixed code, alerted on, and
    retried after a while."""
    async with sessionmaker() as s:
        picked = (
            await s.execute(text("select tenant_id, schedule_id from schedule_candidates(:n)"), {"n": batch})
        ).all()
    counts: dict[str, int] = {}
    for tenant_id, schedule_id in picked:
        try:
            outcome = await sync_one(sessionmaker, client, leader, tenant_id, schedule_id)
        except Exception as e:
            refused = isinstance(e, RPCError) and e.status in (RPCStatusCode.INVALID_ARGUMENT,
                                                                RPCStatusCode.FAILED_PRECONDITION)  # fmt: skip
            code = TEMPORAL_REFUSED if refused else SYNC_FAILED
            log.error("schedule_sync_failed", schedule_id=str(schedule_id), code=code, error=type(e).__name__)
            try:
                await _failed(sessionmaker, tenant_id, schedule_id, code)
            except Exception as again:
                log.error("schedule_sync_unrecorded", schedule_id=str(schedule_id), error=type(again).__name__)
            outcome = "failed"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def check_misses(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, *, batch: int = BATCH
) -> dict[str, int]:
    """Temporal's count of firings missed past each schedule's catch-up window (an outage longer than it), read every
    five minutes: an increase is recorded on the schedule, audited and alerted on, and the API shows it."""
    async with sessionmaker() as s:
        query = text("select tenant_id, schedule_id from schedule_miss_candidates(:n)")
        picked = (await s.execute(query, {"n": batch})).all()
    counts = {"checked": 0, "missed": 0}
    for tenant_id, schedule_id in picked:
        try:
            known = await _incarnations(sessionmaker, tenant_id, schedule_id)
            async with sessionmaker() as s:
                at = await s.scalar(select(func.statement_timestamp()))  # before the describes
            shown = [(i.temporal_id, await described(client, i.temporal_id)) for i in known]
            async with sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant_id)
                row = await s.get(Row, schedule_id, populate_existing=True)
                if row is None:
                    continue
                for temporal_id, found in shown:
                    if found is None:
                        continue
                    await _seen(s, [temporal_id], at)
                    counts["missed"] += await _missed(s, tenant_id, schedule_id, temporal_id, found.missed)
                await s.execute(update(Row).where(Row.id == schedule_id).values(misses_checked_at=func.now()))
            counts["checked"] += 1
        except Exception as e:
            log.error("schedule_misses_unread", schedule_id=str(schedule_id), error=type(e).__name__)
    return counts


async def check_strays(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, *, batch: int = BATCH
) -> dict[str, int]:
    """Every incarnation that isn't current (an earlier one of a live schedule, or any of a deleted schedule's, its
    tombstone gone or not), described again every hour, for good (the owner's review of 2b-4a M4): a late create
    lands paused and fires nothing, but stays until found. One found is paused by the sync for its delete and its count
    recorded (`held`), then deleted and alerted on; it's described again on the next pass, its absence read back."""
    async with sessionmaker() as s:
        picked = (
            await s.execute(text("select tenant_id, temporal_id from stray_incarnations(:n)"), {"n": batch})
        ).all()
    counts: dict[str, int] = {}
    for tenant_id, temporal_id in picked:
        try:
            async with sessionmaker() as s:
                at = await s.scalar(select(func.statement_timestamp()))  # before the describe
            found = await described(client, temporal_id)
            ready = False
            if found is not None:  # paused, its count recorded, then deleted, each committed first
                async with sessionmaker() as s, s.begin():
                    await tenant_scope(s, tenant_id)
                    schedule_id = await s.scalar(select(Incarnation.schedule_id)
                                                 .where(Incarnation.temporal_id == temporal_id))  # fmt: skip
                    if schedule_id is not None:
                        ready = await _deletable(s, client, tenant_id, schedule_id, temporal_id, found)
                    await _seen(s, [temporal_id], at)
                if ready:
                    await _delete(client, temporal_id)
                    log.error("schedule_incarnation_stray", tenant=str(tenant_id))
            async with sessionmaker() as s, s.begin():  # one found is described again on the next pass
                await tenant_scope(s, tenant_id)
                await s.execute(update(Incarnation).where(Incarnation.temporal_id == temporal_id)
                                .values(checked_at=None if found else func.now()))  # fmt: skip
            outcome = ("deleted" if ready else "held") if found is not None else "checked"
        except Exception as e:
            log.error("schedule_stray_unchecked", tenant=str(tenant_id), error=type(e).__name__)
            outcome = "failed"
            try:  # retried in five minutes, behind the others: never holding the scan
                async with sessionmaker() as s, s.begin():
                    await tenant_scope(s, tenant_id)
                    await s.execute(update(Incarnation).where(Incarnation.temporal_id == temporal_id)
                                    .values(checked_at=func.now() - STRAYS_EVERY + STRAY_RETRY))  # fmt: skip
            except Exception as again:
                log.error("schedule_stray_unrescheduled", tenant=str(tenant_id), error=type(again).__name__)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts
