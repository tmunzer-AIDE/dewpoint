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

A create (no token) follows a describe that found nothing; one that finds the schedule already there leaves the row
queued for an update. A deletion's tombstone stays queued until a describe made a call deadline after the deletion
finds nothing, so a stale writer's create, started before the tombstone, can't bring the schedule back unseen; a tick
that finds a tombstone queues it again. The marker is evidence of a Dewpoint update, not of the whole state: editing a
schedule directly in Temporal isn't supported. Missed firings past the catch-up window are Temporal's own count, read
every five minutes, recorded, audited and alerted on."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.api.workflowservice.v1 import DeleteScheduleRequest, DescribeScheduleRequest, UpdateScheduleRequest
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
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.models.workflows import Workflow
from dewpoint.engine.runtime.ids import schedule_workflow_id

log = structlog.get_logger("dewpoint.dispatcher.schedules")
MARK = "dewpoint generation {}"  # the only thing the sync writes into a schedule's note (the owner's ruling)
BATCH = 50  # schedules a pass
CALL_DEADLINE = timedelta(seconds=10)  # every call to Temporal here is bounded by it
TEMPORAL_REFUSED = "temporal_refused"
SYNC_FAILED = "sync_failed"


class _Leader(Protocol):
    async def leading(self) -> bool: ...


@dataclass(frozen=True)
class Described:
    token: bytes
    note: str
    missed: int  # firings Temporal skipped past the catch-up window, ever
    action_key_version: int | None = None  # the data-key version its action's payload names, as the codec wrote it


def _action_key_version(answer: Any) -> int | None:
    """The data-key version the schedule's action is sealed under, from its payload's metadata, undecoded."""
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
    return Described(answer.conflict_token, answer.schedule.state.notes, answer.info.missed_catchup_window,
                     _action_key_version(answer))  # fmt: skip


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


def temporal(row: Row, *, paused: bool) -> Schedule:
    """The Temporal Schedule a row wants, its generation in the note."""
    if row.cron is not None:
        spec = ScheduleSpec(cron_expressions=[row.cron], time_zone_name=row.time_zone)
    else:
        every = timedelta(seconds=row.every_s or 0)
        spec = ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every, offset=timedelta(seconds=row.offset_s))])
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "ScheduleTick", str(row.id), id=schedule_workflow_id(str(row.tenant_id), str(row.id)),
            task_queue=ADMISSION_QUEUE,
        ),
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
        return _Wanted(row.generation, None, bool(settled))
    workflow = await s.get(Workflow, row.workflow_id, populate_existing=True)
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    paused = not row.enabled or workflow is None or not workflow.enabled or tenant is None or tenant.status != "active"
    return _Wanted(row.generation, temporal(row, paused=paused))


async def _record(
    sessionmaker: async_sessionmaker[AsyncSession], leader: _Leader, tenant_id: uuid.UUID, schedule_id: uuid.UUID,
    generation: int, action_key_version: int | None = None,
) -> str:  # fmt: skip
    """The generation marked synced, with the key version its action was read back under (a live schedule's), if the
    row still has it and this writer still leads."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        if not await leader.leading():
            return "not_leading"
        done = await s.execute(
            update(Row)
            .where(Row.id == schedule_id, Row.generation == generation)
            .values(synced_generation=generation, sync_error=None, sync_error_at=None,
                    action_key_version=action_key_version)
        )  # fmt: skip
    return "synced" if done.rowcount else "pending"  # type: ignore[attr-defined]


async def sync_one(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, leader: _Leader, tenant_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> str:  # fmt: skip
    """One schedule brought toward its row: `synced`, `pending` (left queued), `deleting`, `not_leading`, `gone`."""
    temporal_id = schedule_workflow_id(str(tenant_id), str(schedule_id))
    before = await described(client, temporal_id)
    async with sessionmaker() as s, s.begin():
        wanted = await _wanted(s, tenant_id, schedule_id)
    if wanted is None:
        return "gone"
    await _after_read()
    if wanted.schedule is None:  # a tombstone
        if before is not None:
            await _delete(client, temporal_id)
            return "deleting"
        if not wanted.settled:
            return "deleting"  # absent, but a create started before the tombstone could still land
        return await _record(sessionmaker, leader, tenant_id, schedule_id, wanted.generation)
    mark = MARK.format(wanted.generation)
    if before is None:
        if not await _create(client, temporal_id, wanted.schedule):
            return "pending"
    elif before.note != mark:
        await _update(client, temporal_id, wanted.schedule, before.token)
    after = await described(client, temporal_id)  # the read-back: an OK answer proves nothing
    if after is None or after.note != mark:
        return "pending"
    return await _record(sessionmaker, leader, tenant_id, schedule_id, wanted.generation, after.action_key_version)


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
            found = await described(client, schedule_workflow_id(str(tenant_id), str(schedule_id)))
            async with sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant_id)
                row = await s.get(Row, schedule_id, populate_existing=True)
                if row is None:
                    continue
                values: dict[str, Any] = {"misses_checked_at": func.now()}
                if found is not None and found.missed > row.misses:
                    missed = found.missed - row.misses
                    values["misses"] = found.missed
                    log.error("schedule_firings_missed", schedule_id=str(schedule_id), missed=missed)
                    await audit.record(s, tenant_id=tenant_id, actor_id=None, action="schedule.missed",
                                       target_type="schedule", target_id=str(schedule_id),
                                       details={"schedule_id": str(schedule_id), "missed": missed})  # fmt: skip
                    counts["missed"] += missed
                await s.execute(update(Row).where(Row.id == schedule_id).values(**values))
            counts["checked"] += 1
        except Exception as e:
            log.error("schedule_misses_unread", schedule_id=str(schedule_id), error=type(e).__name__)
    return counts
