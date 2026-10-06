# SPDX-License-Identifier: Apache-2.0
"""Run executions' evidence (the owner's M3 ruling; migration 0039's `execution_evidence`): what Temporal may still
hold of each run execution, kept until Temporal shows it gone. A terminal row isn't proof that Temporal closed an
execution, and retention deletes rows before Temporal deletes histories, so retiring a key asks Temporal, execution by
execution.

A root's evidence is written with each start attempt, before Temporal is asked; an attempt Temporal may have taken
leaves it `unproven` (an absence seen at one moment doesn't fence a start still in flight). The dispatcher's leader
(`check_evidence`) describes each execution due:
- shown: seen (`seen_at`, checked `checked_at`). Open, it's looked at again later. Closed and not yet read, its history
  is read exactly (Temporal's events, not its visibility, whose lag nothing bounds): its chain's first run (a root's,
  resolved from what Temporal shows), its continuation, and every child it started, each recorded with when it
  started. It's then read, and looked at again once the namespace's retention since its close has passed;
- not shown, read: it's proven gone (its row deleted). Seen and never read: its history went unread, lost (alerted
  on). Never seen: pending, never judged (the owner's M3 rulings). It may still land; or it may have landed while the
  namespace's retention was short, closed and gone unseen, after starting children no one recorded. Nothing proves the
  retention over the time it went unchecked (the value Temporal reports now can't), so nothing settles it but
  Temporal showing it. Both keep every key they could hold.

`prove` is `keys retire`'s: each execution that could hold a version is described again. One open, still retained,
unread, lost or pending keeps the version; one shown gone is proven, and its evidence deleted."""

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.core.crypto.retire import RunProof
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.runs import ExecutionEvidence
from dewpoint.engine.runtime.ids import tenant_of

log = structlog.get_logger("dewpoint.dispatcher.evidence")
RECHECK = timedelta(minutes=5)  # an execution open, or not yet shown, is described again after this
RETAINED_FOR = timedelta(days=1)  # when the namespace's retention can't be read: a read one is described again after
BATCH = 50  # rows a pass
CALL_DEADLINE = timedelta(seconds=10)


@dataclass(frozen=True)
class _Read:
    """One run's history, read: when it closed, every child it started (its workflow id, its run id when Temporal
    showed it started, when its start was initiated), and the run it continued as."""

    run_id: str
    closed: datetime
    children: list[tuple[str, str | None, datetime]]
    continued: tuple[str, datetime] | None


async def namespace_retention(client: Client) -> timedelta | None:
    """The namespace's retention, as Temporal reports it; None when it can't be read."""
    try:
        answer = await client.workflow_service.describe_namespace(
            DescribeNamespaceRequest(namespace=client.namespace), timeout=CALL_DEADLINE
        )
    except Exception as e:  # unreachable, refused: unknown, never assumed
        log.warning("namespace_retention_unread", error=type(e).__name__)
        return None
    ttl = answer.config.workflow_execution_retention_ttl
    return timedelta(seconds=ttl.seconds, microseconds=ttl.nanos // 1000)


class Retention:
    """The namespace's retention for the leader's passes, read at most every `EVERY` (a cycle runs every second)."""

    EVERY = timedelta(minutes=5)

    def __init__(self) -> None:
        self._value: timedelta | None = None
        self._read: float | None = None

    async def __call__(self, client: Client) -> timedelta | None:
        now = time.monotonic()
        if self._read is None or now - self._read >= self.EVERY.total_seconds():
            self._value, self._read = await namespace_retention(client), now
        return self._value


async def _described(client: Client, workflow_id: str, run_id: str | None) -> Any | None:
    """What Temporal shows of the execution (the latest run of its chain without `run_id`); None: nothing."""
    try:
        return await client.get_workflow_handle(workflow_id, run_id=run_id).describe(rpc_timeout=CALL_DEADLINE)
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return None
        raise


def _open(described: Any) -> bool:
    return described.status is None or described.status == WorkflowExecutionStatus.RUNNING


async def _history(client: Client, workflow_id: str, run_id: str) -> _Read:
    """A closed run's history, read whole, page by page."""
    initiated: dict[int, tuple[str, datetime]] = {}
    children: list[tuple[str, str | None, datetime]] = []
    continued: tuple[str, datetime] | None = None
    closed: datetime | None = None
    async for event in client.get_workflow_handle(workflow_id, run_id=run_id).fetch_history_events(
        rpc_timeout=CALL_DEADLINE
    ):
        at = event.event_time.ToDatetime(tzinfo=UTC)
        closed = at
        if event.HasField("start_child_workflow_execution_initiated_event_attributes"):
            child = event.start_child_workflow_execution_initiated_event_attributes.workflow_id
            initiated[event.event_id] = (child, at)
        elif event.HasField("child_workflow_execution_started_event_attributes"):
            started = event.child_workflow_execution_started_event_attributes
            _, when = initiated.pop(started.initiated_event_id, ("", at))
            children.append((started.workflow_execution.workflow_id, started.workflow_execution.run_id, when))
        elif event.HasField("start_child_workflow_execution_failed_event_attributes"):
            initiated.pop(event.start_child_workflow_execution_failed_event_attributes.initiated_event_id, None)
        elif event.HasField("workflow_execution_continued_as_new_event_attributes"):
            continued = (event.workflow_execution_continued_as_new_event_attributes.new_execution_run_id, at)
    if closed is None:
        raise RuntimeError("A history without events.")
    children.extend((child, None, when) for child, when in initiated.values())  # may have started: its id alone
    return _Read(run_id, closed, children, continued)


async def _after(s: AsyncSession, gap: timedelta, since: datetime | None = None) -> datetime:
    now: datetime = (await s.execute(select(func.statement_timestamp()))).scalar_one()
    return (since or now) + gap


async def _check(sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, row_id: int,
                 retention: timedelta | None) -> str:  # fmt: skip
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        row = await s.get(ExecutionEvidence, row_id)
        if row is None:
            return "gone"
        workflow_id, run_id, read = row.workflow_id, row.run_id, row.read_at is not None
    described = await _described(client, workflow_id, run_id)
    asked: datetime | None = None
    kept = (retention or RETAINED_FOR) + timedelta(minutes=1)
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        row = await s.get(ExecutionEvidence, row_id, with_for_update=True, populate_existing=True)
        if row is None or (row.workflow_id, row.run_id, row.read_at is not None) != (workflow_id, run_id, read):
            return "moved"  # a retirement's proof, or another pass, changed it meanwhile
        if described is None:
            if read:
                await s.delete(row)
                return "gone"
            judged = await _unshown(s, row)
            if judged == "lost":
                log.error("execution_evidence_lost", evidence=row_id)
            row.next_check_at = await _after(s, RECHECK)
            return judged
        asked = await _after(s, timedelta(0))
        row.seen_at, row.checked_at = row.seen_at or asked, asked
        if _open(described):
            first = described.raw_description.workflow_execution_info.first_run_id
            if run_id is None and first and first != described.run_id:
                row.run_id = first  # its chain's first run, closed (a later one exists): read next
                row.next_check_at = await _after(s, timedelta(0))
                return "resolved"
            row.next_check_at = await _after(s, RECHECK)
            return "open"
        if read:
            row.next_check_at = await _after(s, kept, described.close_time)
            return "retained"
    run = run_id or described.raw_description.workflow_execution_info.first_run_id or described.run_id
    found = await _history(client, workflow_id, run)  # the first run, if a root's chain continued: it's closed
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        row = await s.get(ExecutionEvidence, row_id, with_for_update=True, populate_existing=True)
        if row is None or (row.run_id, row.read_at) != (run_id, None):
            return "moved"
        recorded = [(child, child_run, when) for child, child_run, when in found.children]
        if found.continued is not None:
            recorded.append((workflow_id, *found.continued))
        for child, child_run, when in recorded:
            if tenant_of(child) != str(tenant_id):
                raise RuntimeError("A child of another tenant than its parent's.")  # server-built ids: impossible
            target = ["workflow_id"] if child_run is None else ["workflow_id", "run_id"]
            where = text("run_id IS NULL") if child_run is None else text("run_id IS NOT NULL")
            seen = None if child_run is None else when  # shown started; one only initiated may not have
            await s.execute(insert(ExecutionEvidence).values(tenant_id=tenant_id, workflow_id=child, run_id=child_run,
                                                             started_at=when, seen_at=seen, checked_at=seen)
                            .on_conflict_do_nothing(index_elements=target, index_where=where))  # fmt: skip
        row.run_id, row.read_at = found.run_id, await _after(s, timedelta(0))
        row.next_check_at = await _after(s, kept, found.closed)
    return "read"


async def _unshown(s: AsyncSession, row: ExecutionEvidence, *, record: bool = True) -> str:
    """An unread execution Temporal doesn't show, in the caller's transaction: `lost` (seen before: its history went
    unread), or `pending` (never seen: it may still land, or have landed and gone unseen; never judged). Recorded on
    its row unless `record` is false."""
    if not record:
        return "lost" if row.seen_at is not None else "pending"
    now: datetime = (await s.execute(select(func.statement_timestamp()))).scalar_one()
    if row.seen_at is not None:
        row.lost_at = now
        return "lost"
    row.checked_at = now
    return "pending"


async def check_evidence(sessionmaker: async_sessionmaker[AsyncSession], client: Client, *,
                         retention: timedelta | None, batch: int = BATCH) -> dict[str, int]:  # fmt: skip
    """One pass over the evidence due, each row on its own (`read`, `open`, `retained`, `gone`, `pending`, `lost`,
    `resolved`, `moved`, `failed`); a row that failed is looked at again later. `retention`: the namespace's, as
    Temporal reports it, which only schedules when a read execution is next described (None: a day)."""
    async with sessionmaker() as s:
        due = (await s.execute(text("select tenant_id, id from execution_evidence_due(:n)"), {"n": batch})).all()
    counts: dict[str, int] = {}
    for tenant_id, row_id in due:
        try:
            outcome = await _check(sessionmaker, client, tenant_id, row_id, retention)
        except Exception as e:
            log.error("execution_evidence_unchecked", evidence=row_id, error=type(e).__name__)
            outcome = "failed"
            try:
                async with sessionmaker() as s, s.begin():
                    await tenant_scope(s, tenant_id)
                    await s.execute(update(ExecutionEvidence).where(ExecutionEvidence.id == row_id)
                                    .values(next_check_at=await _after(s, RECHECK)))  # fmt: skip
            except Exception as again:
                log.error("execution_evidence_unrescheduled", evidence=row_id, error=type(again).__name__)
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def prove(s: AsyncSession, client: Client, tenant_id: uuid.UUID, *, before: datetime | None,
                record: bool = True) -> RunProof:  # fmt: skip
    """What Temporal shows of the tenant's run executions that started before `before` (all, None), in the caller's
    transaction and tenant scope (the key admin's): each shown gone, read, is proven and its evidence deleted; each
    unshown and unread is lost (seen before) or pending (never seen), as the leader finds it. Raises when Temporal can't
    be asked. With `record` false (a dry run) the same proof, writing nothing."""
    query = select(ExecutionEvidence).where(ExecutionEvidence.tenant_id == tenant_id).order_by(ExecutionEvidence.id)
    if before is not None:
        query = query.where(ExecutionEvidence.started_at < before)
    rows = list((await s.execute(query)).scalars())
    counts = {"open": 0, "retained": 0, "unread": 0, "lost": 0, "pending": 0}
    for row in rows:
        if row.lost_at is not None:
            counts["lost"] += 1
            continue
        described = await _described(client, row.workflow_id, row.run_id)
        if described is None:
            if row.read_at is None:
                counts[await _unshown(s, row, record=record)] += 1
            elif record:
                await s.delete(row)
            continue
        if record:
            now = await _after(s, timedelta(0))
            row.seen_at, row.checked_at = row.seen_at or now, now
        if _open(described):
            counts["open"] += 1
        else:
            counts["unread" if row.read_at is None else "retained"] += 1
    await s.flush()
    return RunProof(**counts)
