# SPDX-License-Identifier: Apache-2.0
"""A schedule's tick, admitted (engine 2b spec §8.2): the activity of `ScheduleTick`, in the dispatcher process, as the
dispatch role. Its authority comes from its own workflow id only (the owner's ruling 10): the tenant and the schedule
are parsed from it with the codec's grammar, the argument must name the same schedule, and the row is read by both, in
that tenant's scope.

In one transaction, under the tick key `sched:<schedule_id>:<nominal time>`, so every retry finds what the first
recorded, and decided under the schedule's row lock (the owner's M3 reviews), which a change holds until it commits: a
disable or a delete either commits first and decides the tick, or waits until the tick's request is in. The tick takes
it exclusively: a tick of a deleted schedule writes the row (it queues the tombstone again), and two ticks holding it
shared would each wait to write, a deadlock. The workflow's
admission lock is taken first, shared, as admission takes it: a workflow's change takes it exclusively before it
writes its schedules' generations, so both take the two in the same order.

An enabled schedule's tick is admitted as any durable source is (queued, or a `refused` request with admission's
reason); one whose schedule was disabled before its pause reached Temporal, or deleted (its tombstone), is a `refused`
request (`schedule_paused`, `schedule_deleted`); either way its `run.request` audit entry names the schedule. A tick
of a tenant that isn't active (`erasing`, or `erased`) is an audited skip, never a request.
After those decisions, a newly decided tick strictly past its schedule's catch-up window, by the database's clock read
once it holds the row, is a `refused` request, `schedule_catchup_expired` (the owner's ruling on the whole-branch
review): an outage of the dispatcher or the database longer than the window admits only the firings within it, as
Temporal's own catch-up does after its outages. A tick already recorded keeps what it recorded, and a queued request
never expires. These refusals are reported apart from Temporal's count of the firings it missed (`misses`): each newly
recorded one alerts once (`schedule_tick_expired`), when its transaction has committed, never for a retry that finds it
or an attempt rolled back.
A platform-wide failure (the database, a key) raises, and the workflow retries it without limit (§2.5): a tick still
unadmitted 10 minutes after its time alerts.
Its first act, in a transaction of its own, records its workflow and run ids (`schedule_firings`), a skip included: an
erasure's firing inventory (2b-4a M4). Past its tenant's insert fence the record is refused; the tick still skips, and
alerts (`schedule_tick_unrecorded`).
What the tick carries in Temporal is the tick contract's (`apps.tick_contract`), unsealed: its outcome is reduced to
the contract's codes (`tick_contract.outcome`), its failures to its failure codes, and its request row records the
rest."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.api.enums.v1 import TaskQueueType
from temporalio.api.taskqueue.v1 import TaskQueue
from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest
from temporalio.client import Client
from temporalio.exceptions import ApplicationError

from dewpoint.apps import admission, schedules, tick_contract
from dewpoint.core.audit import service as audit
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.schedules import Schedule
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.tenancy import lifecycle
from dewpoint.core.workflows.service import lock_for_admission
from dewpoint.engine.runtime.ids import schedule_of

log = structlog.get_logger("dewpoint.dispatcher.tick")
ADMISSION_QUEUE = "dewpoint-admission"  # unversioned, outside the engine's Worker Deployment (engine-core §11.11)
TICK = "schedule.tick"
SCHEDULE_PAUSED = "schedule_paused"
SCHEDULE_DELETED = "schedule_deleted"
SCHEDULE_CATCHUP_EXPIRED = "schedule_catchup_expired"
EXPIRED = "dewpoint.tick.expired"  # in the session's `info`: the expiries newly recorded, alerted on commit
LATE = timedelta(minutes=10)  # §15: provisional
TICK_IDENTITY = tick_contract.TICK_IDENTITY
SCHEDULE_UNKNOWN = tick_contract.SCHEDULE_UNKNOWN


@dataclass(frozen=True)
class TickInput:
    schedule_id: str  # the schedule the workflow id names (the workflow derives it from its id)
    key: str  # `sched:<schedule_id>:<nominal time>`
    nominal: str  # the nominal time, UTC, whole seconds: `2026-10-04T09:00:00Z`


async def _after_schedule_locked() -> None:
    """Runs once a tick holds its schedule's row. A no-op; the race tests start a competing change here."""


async def _recorded(s: AsyncSession, key: str) -> bool:
    """Whether a request already holds the tick's key. Under the schedule's row lock, any attempt of this tick that
    decided before has committed, so this sees it."""
    return (await s.execute(select(RunRequest.id).where(RunRequest.idempotency_key == key))).first() is not None


async def _database_now(s: AsyncSession) -> datetime:
    """The database's clock, read in a statement of its own, after the tick holds its schedule's row."""
    return (await s.execute(select(func.statement_timestamp()))).scalar_one()


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
    `recorded` when its key already holds another outcome of this tick (it was paused then, enabled since). An expiry
    this call newly records is left in `s.info[EXPIRED]`, for the caller to alert on once its transaction commits."""
    await tenant_scope(s, tenant_id)
    await lifecycle.hold_shared(s, tenant_id)  # first, as every writer of tenant data: an erasure's step 1 takes it
    found = await s.get(Schedule, schedule_id, populate_existing=True)  # row-level security: that tenant's only
    if found is None:
        raise ScheduleUnknownError(str(schedule_id))
    await lock_for_admission(s, tenant_id, found.workflow_id)  # a schedule's workflow never changes
    schedule = (
        await s.execute(
            select(Schedule).where(Schedule.id == schedule_id).with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one()  # exclusive, held until the caller commits: never a shared lock it would upgrade  # fmt: skip
    await _after_schedule_locked()
    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
    if tenant is None or tenant.status != "active":  # erasing, or erased: never eligible again
        details: dict[str, object] = {"schedule_id": str(schedule_id), "tick": key, "reason": admission.TENANT_ERASING}
        await audit.record(s, tenant_id=tenant_id, actor_id=None, action="schedule.tick_skipped",
                           target_type="schedule", target_id=str(schedule_id), details=details)  # fmt: skip
        return f"skipped:{admission.TENANT_ERASING}"
    named: dict[str, object] = {"schedule_id": str(schedule_id)}  # its request's audit entry names the schedule
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
                idempotency_key=key, reason=reason, messages=[said], details=named,
            )  # fmt: skip
            return _outcome(refused)
        late = await _database_now(s) - _parsed(key.split(":", 2)[2])
        if late > timedelta(seconds=schedule.catchup_window_s):  # strictly past it: at its edge, still admitted
            new = not await _recorded(s, key)
            expired = await admission.record_refused(
                s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", mode=schedule.mode,
                idempotency_key=key, reason=SCHEDULE_CATCHUP_EXPIRED,
                messages=["The tick is past its schedule's catch-up window."], details=named,
            )  # fmt: skip
            if new and expired.reason == SCHEDULE_CATCHUP_EXPIRED:  # the caller alerts once its transaction commits
                s.info.setdefault(EXPIRED, []).append({"schedule_id": str(schedule_id),
                                                       "late_s": int(late.total_seconds())})  # fmt: skip
            return _outcome(expired)
        cipher = ClaimCipher(keys, purpose=schedules.INPUT_PURPOSE)
        given = json.loads(await cipher.open(str(tenant_id), str(schedule_id), schedule.input))
        admitted = await admission.admit_request(
            s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", actor_id=None,
            mode=schedule.mode, idempotency_key=key, input=given, details=named,
        )  # fmt: skip
    except admission.IdempotencyConflictError:
        return "recorded"
    return _outcome(admitted.request)


_FIRING = text(
    "INSERT INTO schedule_firings (workflow_id, run_id, tenant_id, schedule_id) SELECT :w, :r, :t, :s "
    "WHERE EXISTS (SELECT 1 FROM schedules WHERE id = :s AND tenant_id = :t) ON CONFLICT DO NOTHING"
)


class Ticker:
    """`schedule.tick`, bound to the dispatcher's database and keys."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource) -> None:
        self.sessionmaker, self.keys = sessionmaker, keys

    async def _recorded(self, tenant_id: uuid.UUID, schedule_id: uuid.UUID) -> None:
        """This firing's ids, recorded once, whatever its outcome, if its tenant has the schedule it names (a tick of no
        schedule fails right after, `schedule_unknown`); refused only past its tenant's insert fence."""
        info = activity.info()
        try:
            async with self.sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant_id)
                await s.execute(_FIRING, {"w": info.workflow_id, "r": info.workflow_run_id, "t": tenant_id,
                                          "s": schedule_id})  # fmt: skip
        except DBAPIError as e:
            if getattr(e.orig, "sqlstate", None) != lifecycle.FENCED:
                raise
            log.error("schedule_tick_unrecorded", schedule_id=str(schedule_id))

    @activity.defn(name=TICK)
    async def tick(self, given: TickInput) -> str:
        named = schedule_of(activity.info().workflow_id or "")
        if named is None or named[1] != given.schedule_id or tick_key(named[1], _parsed(given.nominal))[0] != given.key:
            raise ApplicationError("A tick whose workflow id names another schedule.", type=TICK_IDENTITY,
                                   non_retryable=True)  # fmt: skip
        tenant_id, schedule_id = (uuid.UUID(part) for part in named)
        try:
            await self._recorded(tenant_id, schedule_id)
            async with self.sessionmaker() as s, s.begin():
                outcome = await admit_tick(s, self.keys, tenant_id=tenant_id, schedule_id=schedule_id, key=given.key)
            for expiry in s.info.pop(EXPIRED, []):  # committed: an attempt rolled back never gets here
                log.error("schedule_tick_expired", **expiry)
            return tick_contract.outcome(outcome)  # its request row records the reason in full
        except ScheduleUnknownError:
            raise ApplicationError("A tick of no schedule of its tenant.", type=SCHEDULE_UNKNOWN,
                                   non_retryable=True) from None  # fmt: skip
        except Exception as e:
            if datetime.now(UTC) - _parsed(given.nominal) > LATE:
                log.error("schedule_tick_late", schedule_id=str(schedule_id), attempt=activity.info().attempt,
                          error=type(e).__name__)  # fmt: skip
            raise


async def admission_pollers(client: Client) -> list[str]:
    """The identities Temporal shows polling the admission queue, for workflows and for activities: each dispatcher's.
    One without the tick contract's mark (`tick_contract.IDENTITY`) runs ticks as before it."""
    found: list[str] = []
    for kind in (TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW, TaskQueueType.TASK_QUEUE_TYPE_ACTIVITY):
        answer = await client.workflow_service.describe_task_queue(
            DescribeTaskQueueRequest(
                namespace=client.namespace, task_queue=TaskQueue(name=ADMISSION_QUEUE), task_queue_type=kind
            )  # fmt: skip
        )
        found.extend(poller.identity for poller in answer.pollers)
    return found


def _parsed(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
