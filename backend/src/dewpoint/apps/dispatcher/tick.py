# SPDX-License-Identifier: Apache-2.0
"""A schedule's tick, admitted (engine 2b spec §8.2): the activity of `ScheduleTick`, in the dispatcher process, as the
dispatch role. Its authority comes from its own workflow id only (the owner's ruling 10): the tenant and the schedule
are parsed from it with the codec's grammar, the argument must name the same schedule, and the row is read by both, in
that tenant's scope.

In one transaction, under the tick key `sched:<schedule_id>:<nominal time>`, so every retry finds what the first
recorded: an enabled schedule's tick is admitted as any durable source is (queued, or a `refused` request with
admission's reason); one whose schedule was disabled before its pause reached Temporal, or deleted (its tombstone), is a
`refused` request (`schedule_paused`, `schedule_deleted`); an `erasing` tenant's is an audited skip, never a request.
A platform-wide failure (the database, a key) raises, and the workflow retries it without limit (§2.5): a tick still
unadmitted 10 minutes after its time alerts."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from dewpoint.apps import admission, schedules
from dewpoint.core.audit import service as audit
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.schedules import Schedule
from dewpoint.core.models.tenancy import Tenant
from dewpoint.engine.runtime.ids import schedule_of

log = structlog.get_logger("dewpoint.dispatcher.tick")
ADMISSION_QUEUE = "dewpoint-admission"  # unversioned, outside the engine's Worker Deployment (engine-core §11.11)
TICK = "schedule.tick"
SCHEDULE_PAUSED = "schedule_paused"
SCHEDULE_DELETED = "schedule_deleted"
LATE = timedelta(minutes=10)  # §15: provisional
TICK_IDENTITY = "tick_identity"
SCHEDULE_UNKNOWN = "schedule_unknown"


@dataclass(frozen=True)
class TickInput:
    schedule_id: str  # the action's argument, which must name the schedule the workflow id does
    key: str  # `sched:<schedule_id>:<nominal time>`
    nominal: str  # the nominal time, UTC, whole seconds: `2026-10-04T09:00:00Z`


class ScheduleUnknownError(Exception):
    """A tick's workflow id names no schedule of its tenant, not even a tombstone: nothing to record it against."""


def tick_key(schedule_id: str, nominal: datetime) -> tuple[str, str]:
    """The tick's key and its nominal time, normalized to UTC at Temporal's precision (whole seconds, §11.1)."""
    stamp = nominal.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"sched:{schedule_id}:{stamp}", stamp


def _outcome(request: RunRequest) -> str:
    return f"refused:{request.reason}" if request.status == "refused" else request.status


async def admit_tick(
    s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, schedule_id: uuid.UUID, key: str
) -> str:
    """The tick's outcome, recorded in the caller's transaction: `queued`, `refused:<reason>`, `skipped:<reason>`, or
    `recorded` when its key already holds another outcome of this tick (it was paused then, enabled since)."""
    await tenant_scope(s, tenant_id)
    schedule = await s.get(Schedule, schedule_id, populate_existing=True)  # row-level security: that tenant's only
    if schedule is None:
        raise ScheduleUnknownError(str(schedule_id))
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    if tenant is None or tenant.status == "erasing":
        details: dict[str, object] = {"schedule_id": str(schedule_id), "tick": key, "reason": admission.TENANT_ERASING}
        await audit.record(s, tenant_id=tenant_id, actor_id=None, action="schedule.tick_skipped",
                           target_type="schedule", target_id=str(schedule_id), details=details)  # fmt: skip
        return f"skipped:{admission.TENANT_ERASING}"
    try:
        if schedule.deleted_at is not None:  # a stale create may have brought it back in Temporal: delete it again
            await s.execute(
                update(Schedule)
                .where(Schedule.id == schedule_id, Schedule.synced_generation == Schedule.generation)
                .values(synced_generation=Schedule.generation - 1)
            )
        if schedule.deleted_at is not None or not schedule.enabled or schedule.input is None:
            reason, said = (
                (SCHEDULE_DELETED, "The schedule was deleted.") if schedule.deleted_at is not None
                else (SCHEDULE_PAUSED, "The schedule is disabled.")
            )  # fmt: skip
            refused = await admission.record_refused(
                s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", mode=schedule.mode,
                idempotency_key=key, reason=reason, messages=[said],
            )  # fmt: skip
            return _outcome(refused)
        cipher = ClaimCipher(keys, purpose=schedules.INPUT_PURPOSE)
        given = json.loads(await cipher.open(str(tenant_id), str(schedule_id), schedule.input))
        admitted = await admission.admit_request(
            s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", actor_id=None,
            mode=schedule.mode, idempotency_key=key, input=given,
        )  # fmt: skip
    except admission.IdempotencyConflictError:
        return "recorded"
    return _outcome(admitted.request)


class Ticker:
    """`schedule.tick`, bound to the dispatcher's database and keys."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource) -> None:
        self.sessionmaker, self.keys = sessionmaker, keys

    @activity.defn(name=TICK)
    async def tick(self, given: TickInput) -> str:
        named = schedule_of(activity.info().workflow_id or "")
        if named is None or named[1] != given.schedule_id or tick_key(named[1], _parsed(given.nominal))[0] != given.key:
            raise ApplicationError("A tick whose workflow id names another schedule.", type=TICK_IDENTITY,
                                   non_retryable=True)  # fmt: skip
        tenant_id, schedule_id = (uuid.UUID(part) for part in named)
        try:
            async with self.sessionmaker() as s, s.begin():
                return await admit_tick(s, self.keys, tenant_id=tenant_id, schedule_id=schedule_id, key=given.key)
        except ScheduleUnknownError:
            raise ApplicationError("A tick of no schedule of its tenant.", type=SCHEDULE_UNKNOWN,
                                   non_retryable=True) from None  # fmt: skip
        except Exception as e:
            if datetime.now(UTC) - _parsed(given.nominal) > LATE:
                log.error("schedule_tick_late", schedule_id=str(schedule_id), attempt=activity.info().attempt,
                          error=type(e).__name__)  # fmt: skip
            raise


def _parsed(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
