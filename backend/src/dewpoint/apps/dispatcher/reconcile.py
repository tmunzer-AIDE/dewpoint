# SPDX-License-Identifier: Apache-2.0
"""The reconciler (engine 2b spec §7.6): inside the dispatcher, one leader at a time, it settles what starts left
uncertain, records the end of runs whose workflow closed without their end write, and releases leaked slots; it ends
the sub-runs their root's close left running, once their own execution has closed (`reconcile_subruns`).

It reads across tenants only through `reconcile_candidates()` (ids and a kind), then works tenant-scoped, one
request per transaction, with no transaction open across a call to Temporal. It asks about each request at most once
per `RECHECK`. An uncertain start is found by when it became `starting`, never by its slot, which a quick run's end
write may already have released. A failure it can't classify is logged and isolated, as the dispatcher's are."""

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import dispatch
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.runs import service as runs
from dewpoint.engine.runtime.activities import RunResult
from dewpoint.engine.runtime.execution import CANCELLED, INTERNAL_ERROR, TERMINATED
from dewpoint.engine.runtime.ids import run_workflow_id

log = structlog.get_logger("dewpoint.reconciler")
LEADER_LOCK = "dewpoint:reconciler"
GRACE = timedelta(seconds=30)  # longer than a start's own deadline (dispatch.START_DEADLINE), so none is in flight
RECHECK = timedelta(seconds=30)  # each request asked about at most once in this long
ALERT_AFTER = timedelta(minutes=10)  # an uncertain start still unresolved this long after it was made: an error
BATCH = 50  # requests per pass
MISSING_MAX = timedelta(days=1)  # a sub-run whose history is gone waits twice its last gap each time, up to this
TERMINATED_MESSAGE = "The run's workflow was terminated outside Dewpoint."
FAILED_MESSAGE = "The run's workflow failed outside its own code (engine 2b spec §7.6)."
LIVE = (WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CONTINUED_AS_NEW)  # its successor is starting


class Leader:
    """The reconciler's one leader among the dispatchers: a session-level advisory lock on a connection of its own,
    held while that connection lives. Losing the connection loses the lock; closing drops the connection, so the lock
    is never left on a pooled one."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._connection: AsyncConnection | None = None

    async def leading(self) -> bool:
        if self._connection is not None:
            try:
                await self._connection.execute(text("select 1"))
                await self._connection.commit()
                return True
            except Exception as e:  # the connection, and its lock, are gone
                log.warning("reconciler_leadership_lost", error=type(e).__name__)
                await self.close()
        connection = await self._engine.connect()
        try:
            found = await connection.execute(
                text("select pg_try_advisory_lock(hashtextextended(:k, 0))"), {"k": LEADER_LOCK}
            )
            got = bool(found.scalar())
            await connection.commit()
        except BaseException:
            await connection.invalidate()
            await connection.close()
            raise
        if got:
            self._connection = connection
            return True
        await connection.close()
        return False

    async def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            await connection.invalidate()  # the server ends the session, and its lock with it
            await connection.close()


async def reconcile_once(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings
) -> dict[str, int]:
    """One pass over what needs settling: what happened, counted, for the reconciler's report."""
    async with sessionmaker() as s:
        picked = (
            await s.execute(
                text("select tenant_id, request_id, kind from reconcile_candidates(:grace, :recheck, :n)"),
                {"grace": GRACE, "recheck": RECHECK, "n": BATCH},
            )
        ).all()
    counts: Counter[str] = Counter()
    for tenant_id, request_id, kind in picked:
        try:
            if kind == "starting":
                happened = await _starting(sessionmaker, client, keys, settings, tenant_id, request_id)
            elif kind == "open":
                happened = await _open(sessionmaker, client, tenant_id, request_id)
            else:
                happened = await _slot(sessionmaker, client, tenant_id, request_id)
        except Exception as e:  # a bug or an outage: left as it was, asked about again after RECHECK
            log.error("reconcile_failed", tenant_id=str(tenant_id), request_id=str(request_id), kind=kind,
                      error=type(e).__name__)  # fmt: skip
            counts["error"] += 1
            await _checked_alone(sessionmaker, tenant_id, request_id)
            continue
        counts[happened] += 1
    return dict(counts)


# --- uncertain starts ----------------------------------------------------------------------------------------------


async def _starting(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, keys: KeySource, settings: Settings,
    tenant_id: uuid.UUID, request_id: uuid.UUID,
) -> str:  # fmt: skip
    """A request still `starting` past its grace period: found and verified, `started`; absent from a namespace that
    answers, back in the queue; anything else, left `starting`."""
    handle = client.get_workflow_handle(run_workflow_id(str(tenant_id), str(request_id)))
    try:
        await handle.describe()
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client):
            ref = dispatch.Ref(request_id, tenant_id)
            happened = await dispatch.settle(sessionmaker, ref, dispatch.Outcome("absent"), audited=True)
            if happened != "history_missing":
                return happened
            log.error("start_history_missing", request_id=str(request_id))  # its row ended: an operator recovers it
            await _checked_alone(sessionmaker, tenant_id, request_id)
            return "unresolved"
        return await _unresolved(sessionmaker, tenant_id, request_id, e.status.name)
    except Exception as e:  # a lost connection or a timeout: nothing is known
        return await _unresolved(sessionmaker, tenant_id, request_id, type(e).__name__)
    try:
        expected = await _expected(sessionmaker, keys, settings, tenant_id, request_id)
    except dispatch.KeyUnusableError:
        return await _unresolved(sessionmaker, tenant_id, request_id, "key_unusable")
    if expected is None:
        return "moved"
    outcome = await dispatch.verify(client, expected)
    if outcome.kind == "uncertain":
        return await _unresolved(sessionmaker, tenant_id, request_id, outcome.detail)
    # Started: a closed execution's end is recorded by the next pass, which finds the row still `running`.
    return await dispatch.settle(sessionmaker, expected, outcome, audited=True)


async def _expected(
    sessionmaker: async_sessionmaker[AsyncSession], keys: KeySource, settings: Settings, tenant_id: uuid.UUID,
    request_id: uuid.UUID,
) -> dispatch.Starting | None:  # fmt: skip
    """The start the request would have sent, to verify a found execution against (§7.4); None once it isn't
    `starting`."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        request = (
            await s.execute(select(RunRequest).where(RunRequest.id == request_id, RunRequest.status == "starting"))
        ).scalar_one_or_none()
        if request is None or request.workflow_version_id is None:
            return None
        cipher = ClaimCipher(dispatch.KeyFailures(keys))
        envelope = await claims.read_envelope(s, cipher, tenant_id, request_id=request_id)
        start = dispatch.run_input(request, request.workflow_version_id, envelope, settings)
    return dispatch.Starting(request_id, tenant_id, start)


async def namespace_answers(client: Client) -> bool:
    """Whether the namespace is reachable, so a NOT_FOUND is about the execution (§7.6). Any failure: it isn't known."""
    try:
        await client.workflow_service.describe_namespace(DescribeNamespaceRequest(namespace=client.namespace))
    except Exception:
        return False
    return True


async def _unresolved(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, request_id: uuid.UUID, detail: str
) -> str:
    """Left `starting`, its slot held; an error once it has been so for ALERT_AFTER."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        since = select(text("statement_timestamp() - starting_at")).select_from(RunRequest)
        age = (await s.execute(since.where(RunRequest.id == request_id))).scalar()  # its slot may be gone already
        await _checked(s, request_id)
    if isinstance(age, timedelta) and age >= ALERT_AFTER:
        log.error("start_unresolved", request_id=str(request_id), detail=detail, age_s=int(age.total_seconds()))
    else:
        log.warning("start_unresolved", request_id=str(request_id), detail=detail)
    return "unresolved"


# --- runs whose workflow closed, and leaked slots ------------------------------------------------------------------


@dataclass(frozen=True)
class Ended:
    status: str
    error_code: str | None = None
    error_message: str | None = None
    iterations: int = 0


async def _open(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> str:
    """A started run whose row is still `running`: once the logical run's latest execution is closed, the end Temporal
    reports is recorded, and its slot released, in one transaction. Its own end write wins: never over an ended row."""
    handle = client.get_workflow_handle(run_workflow_id(str(tenant_id), str(run_id)), result_type=RunResult)
    try:
        described = await handle.describe()  # no run id: the latest execution, past every continue-as-new
    except Exception as e:
        await _missing_or_unanswered(client, e, run_id, "run_history_missing")
        await _checked_alone(sessionmaker, tenant_id, run_id)
        return "unresolved"
    if described.status is None or described.status in LIVE:
        await _checked_alone(sessionmaker, tenant_id, run_id)
        return "running"
    ended = await _ended(handle, described.status, run_id)
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await runs.finish_run(
            s, run_id, status=ended.status, ended_at=described.close_time or datetime.now(UTC),
            error_code=ended.error_code, error_message=ended.error_message, iterations=ended.iterations,
            if_running=True,
        )  # fmt: skip
        await dispatch.release(s, run_id)
        await _checked(s, run_id)
    return "ended"


async def _ended(handle: Any, status: WorkflowExecutionStatus, run_id: uuid.UUID) -> Ended:
    """The end Temporal reports for a closed execution (§7.6)."""
    if status == WorkflowExecutionStatus.COMPLETED:
        result: RunResult = await handle.result()  # the run's own end, which its end write should have recorded
        error = result.error or {}
        return Ended(result.status, error.get("code"), error.get("message"), result.iterations)
    if status == WorkflowExecutionStatus.CANCELED:
        return Ended("cancelled", CANCELLED.code, CANCELLED.message)
    if status == WorkflowExecutionStatus.TERMINATED:
        return Ended("failed", TERMINATED, TERMINATED_MESSAGE)
    log.error("run_execution_failed", run_id=str(run_id), status=status.name)  # Dewpoint sets no execution timeout
    return Ended("failed", INTERNAL_ERROR, FAILED_MESSAGE)


async def _slot(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> str:
    """A slot whose run's row has ended: released only once the logical run's latest execution is closed. Its history
    gone is an alert, never a release (the owner's ruling)."""
    try:
        described = await client.get_workflow_handle(run_workflow_id(str(tenant_id), str(run_id))).describe()
    except Exception as e:
        await _missing_or_unanswered(client, e, run_id, "slot_history_missing")
        await _checked_alone(sessionmaker, tenant_id, run_id)
        return "unresolved"
    if described.status is None or described.status in LIVE:
        log.warning("slot_execution_live", run_id=str(run_id))  # its row ended, its execution didn't
        await _checked_alone(sessionmaker, tenant_id, run_id)
        return "live"
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await dispatch.release(s, run_id)
        await _checked(s, run_id)
    return "released"


async def _missing_or_unanswered(client: Client, e: Exception, run_id: uuid.UUID, missing: str) -> bool:
    """A started run's history Temporal no longer has (NOT_FOUND, from a namespace that answers) is an alert: no outcome
    is invented and no slot released from missing history alone; an operator recovers it (the owner's ruling). Any other
    failure: unanswered this time. Whether it was missing."""
    if isinstance(e, RPCError) and e.status == RPCStatusCode.NOT_FOUND and await namespace_answers(client):
        log.error(missing, run_id=str(run_id))
        return True
    error = e.status.name if isinstance(e, RPCError) else type(e).__name__
    log.warning("reconcile_unanswered", run_id=str(run_id), error=error)
    return False


async def _checked(s: AsyncSession, request_id: uuid.UUID) -> None:
    await s.execute(text("update run_requests set checked_at = statement_timestamp() where id = :i"), {"i": request_id})


async def _checked_alone(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, request_id: uuid.UUID
) -> None:
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await _checked(s, request_id)


# --- sub-runs their root's end left running (the final review's M5) --------------------------------------------------


async def reconcile_subruns(sessionmaker: async_sessionmaker[AsyncSession], client: Client) -> dict[str, int]:
    """Sub-runs still `running` once their root has been ended for GRACE: a parent writes its children's ends, so these
    are what a root's close left (a child it asked to cancel, or a parent gone before writing one). Each one's own
    execution is described when it's due (`runs.next_check_at`), across tenants through `orphan_subruns()` (ids only):
    again after RECHECK, or, its history gone, after twice its last gap, up to MISSING_MAX (fix-pass review R9)."""
    async with sessionmaker() as s:
        picked = (
            await s.execute(
                text("select tenant_id, run_id from orphan_subruns(:grace, :n)"), {"grace": GRACE, "n": BATCH}
            )
        ).all()
    counts: Counter[str] = Counter()
    for tenant_id, run_id in picked:
        try:
            happened = await _subrun(sessionmaker, client, tenant_id, run_id)
        except Exception as e:  # a bug or an outage: left as it was, asked about again after RECHECK
            log.error("reconcile_failed", tenant_id=str(tenant_id), run_id=str(run_id), kind="subrun",
                      error=type(e).__name__)  # fmt: skip
            counts["error"] += 1
            await _subrun_checked_alone(sessionmaker, tenant_id, run_id)
            continue
        counts[happened] += 1
    return dict(counts)


async def _subrun(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> str:
    """Closed: the end Temporal reports, recorded unless the row ended meanwhile. Still live: left running. Its history
    gone: an alert and no end, as for a root (the owner's ruling)."""
    handle = client.get_workflow_handle(run_workflow_id(str(tenant_id), str(run_id)), result_type=RunResult)
    try:
        described = await handle.describe()
    except Exception as e:
        missing = await _missing_or_unanswered(client, e, run_id, "subrun_history_missing")
        await _subrun_checked_alone(sessionmaker, tenant_id, run_id, backoff=missing)
        return "unresolved"
    if described.status is None or described.status in LIVE:
        await _subrun_checked_alone(sessionmaker, tenant_id, run_id)
        return "running"
    ended = await _ended(handle, described.status, run_id)
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await runs.finish_run(
            s, run_id, status=ended.status, ended_at=described.close_time or datetime.now(UTC),
            error_code=ended.error_code, error_message=ended.error_message, iterations=ended.iterations,
            if_running=True,
        )  # fmt: skip
        await _subrun_checked(s, run_id)
    return "ended"


_NEXT = text(
    "update runs set checked_at = statement_timestamp(), next_check_at = statement_timestamp() + "
    "least(greatest(cast(:recheck as interval), 2 * (statement_timestamp() - checked_at)), cast(:max as interval)) "
    "where id = :i"
)


async def _subrun_checked(s: AsyncSession, run_id: uuid.UUID, *, backoff: bool = False) -> None:
    """Asked about now; again after RECHECK, or with `backoff` after twice the last gap (RECHECK at first: greatest()
    skips a null), up to MISSING_MAX."""
    await s.execute(_NEXT, {"recheck": RECHECK, "max": MISSING_MAX if backoff else RECHECK, "i": run_id})


async def _subrun_checked_alone(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, run_id: uuid.UUID, *, backoff: bool = False
) -> None:
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        await _subrun_checked(s, run_id, backoff=backoff)
