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
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.api.common.v1 import WorkflowExecution
from temporalio.api.workflowservice.v1 import DescribeNamespaceRequest, GetWorkflowExecutionHistoryRequest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import budget
from dewpoint.core.crypto.retire import RunProof
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.runs import ExecutionEvidence
from dewpoint.engine.runtime.ids import tenant_of

log = structlog.get_logger("dewpoint.dispatcher.evidence")
RECHECK = timedelta(minutes=5)  # an execution open, or not yet shown, is described again after this, at the least
PENDING_MAX = timedelta(days=1)  # one never shown backs off, twice its last gap each time, up to this
RETAINED_FOR = timedelta(days=1)  # when the namespace's retention can't be read: a read one is described again after
BATCH = 50  # rows a pass
CALL_DEADLINE = timedelta(seconds=10)
PAGES = 8  # history pages a visit reads, at most (the owner's D16 ruling: an experimental cap, not a time budget)


@dataclass
class _Reading:
    """A closed run's history, as far as it's read: the run, Temporal's next-page token (None: from its start), the
    children whose start it saw initiated and not yet started (by the initiating event), its latest event's time; what
    the pages read this visit found (every child they showed started, the run it continued as); whether it's done."""

    run_id: str
    token: bytes | None = None
    initiated: dict[int, tuple[str, datetime]] = field(default_factory=dict)
    last: datetime | None = None
    children: list[tuple[str, str | None, datetime]] = field(default_factory=list)
    continued: tuple[str, datetime] | None = None
    done: bool = False

    @classmethod
    def kept(cls, row: ExecutionEvidence) -> "_Reading":
        """Where a row's read stopped."""
        if row.read_run is None:
            raise RuntimeError("A read kept without its run.")  # both are written together
        pending = {int(k): (v[0], datetime.fromisoformat(v[1])) for k, v in (row.read_pending or {}).items()}
        return cls(row.read_run, row.read_token, pending, row.read_last_at)

    def pending(self) -> dict[str, list[str]]:
        return {str(k): [child, at.isoformat()] for k, (child, at) in self.initiated.items()}


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


async def _read_on(client: Client, workflow_id: str, reading: _Reading) -> _Reading:
    """At most `PAGES` more pages of a closed run's history, from where `reading` stopped, each a call of its own."""
    for _ in range(PAGES):
        answer = await client.workflow_service.get_workflow_execution_history(
            GetWorkflowExecutionHistoryRequest(
                namespace=client.namespace,
                execution=WorkflowExecution(workflow_id=workflow_id, run_id=reading.run_id),
                next_page_token=reading.token or b"",
            ),
            timeout=CALL_DEADLINE,
        )
        for event in answer.history.events:
            at = event.event_time.ToDatetime(tzinfo=UTC)
            reading.last = at
            if event.HasField("start_child_workflow_execution_initiated_event_attributes"):
                child = event.start_child_workflow_execution_initiated_event_attributes.workflow_id
                reading.initiated[event.event_id] = (child, at)
            elif event.HasField("child_workflow_execution_started_event_attributes"):
                started = event.child_workflow_execution_started_event_attributes
                _, when = reading.initiated.pop(started.initiated_event_id, ("", at))
                execution = started.workflow_execution
                reading.children.append((execution.workflow_id, execution.run_id, when))
            elif event.HasField("start_child_workflow_execution_failed_event_attributes"):
                reading.initiated.pop(event.start_child_workflow_execution_failed_event_attributes.initiated_event_id,
                                      None)  # fmt: skip
            elif event.HasField("workflow_execution_continued_as_new_event_attributes"):
                reading.continued = (event.workflow_execution_continued_as_new_event_attributes.new_execution_run_id,
                                     at)  # fmt: skip
        reading.token = answer.next_page_token or None
        if reading.token is None:
            if reading.last is None:
                raise RuntimeError("A history without events.")
            reading.done = True
            break
    return reading


async def _history(client: Client, workflow_id: str, run_id: str) -> _Reading:
    """A closed run's history, read whole (the probe's measure of a read)."""
    reading = _Reading(run_id)
    while not reading.done:
        reading = await _read_on(client, workflow_id, reading)
    return reading


async def _after(s: AsyncSession, gap: timedelta, since: datetime | None = None) -> datetime:
    now: datetime = (await s.execute(select(func.statement_timestamp()))).scalar_one()
    return (since or now) + gap


async def _later(s: AsyncSession, gap: timedelta, since: datetime) -> datetime:
    """`since` + `gap`, but never sooner than RECHECK from now (the final review's I3): a read execution's close plus
    the retention can be long past, and a row due again at once would come back on every pass, holding the rest."""
    return max(await _after(s, gap, since), await _after(s, RECHECK))


def _backoff(previous: datetime | None, now: datetime) -> timedelta:
    """How long an execution Temporal didn't show waits before it's described again: RECHECK at first, then twice
    the last gap, up to PENDING_MAX (the final review's I3; it stays pending, never judged)."""
    return RECHECK if previous is None else min(max(RECHECK, 2 * (now - previous)), PENDING_MAX)


async def _check(sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, row_id: int,
                 retention: timedelta | None) -> str:  # fmt: skip
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        row = await s.get(ExecutionEvidence, row_id)
        if row is None:
            return "gone"
        workflow_id, run_id, read = row.workflow_id, row.run_id, row.read_at is not None
        reading = _Reading.kept(row) if row.read_token is not None and not read else None
    if reading is None:
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
                previous = row.checked_at
                judged = await _unshown(s, row)
                if judged == "lost":
                    log.error("execution_evidence_lost", evidence=row_id)
                    row.next_check_at = await _after(s, RECHECK)
                else:
                    now = await _after(s, timedelta(0))
                    row.next_check_at = now + _backoff(previous, now)
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
                row.next_check_at = await _later(s, kept, described.close_time)
                return "retained"
        run = run_id or described.raw_description.workflow_execution_info.first_run_id or described.run_id
        reading = _Reading(run)  # the first run, if a root's chain continued: it's closed
    started_from = reading.token
    try:
        reading = await _read_on(client, workflow_id, reading)
    except RPCError as e:
        if e.status == RPCStatusCode.INVALID_ARGUMENT and started_from is not None:
            return await _restarted(sessionmaker, tenant_id, row_id, run_id, started_from)
        if e.status != RPCStatusCode.NOT_FOUND:
            raise
        return await _gone_reading(sessionmaker, tenant_id, row_id, run_id, started_from)
    return await _recorded(sessionmaker, tenant_id, row_id, workflow_id, run_id, started_from, reading, retention)


async def _restarted(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, row_id: int,
                     run_id: str | None, started_from: bytes) -> str:  # fmt: skip
    """A kept page token Temporal refuses (a server that no longer reads it, the review's I6): the read starts over on
    the next pass, from a describe and the first page, rather than failing every pass for good. What the pages read
    before found stays recorded; recording it again changes nothing."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        row = await s.get(ExecutionEvidence, row_id, with_for_update=True, populate_existing=True)
        if row is None or (row.run_id, row.read_at, row.read_token) != (run_id, None, started_from):
            return "moved"
        row.read_token = row.read_run = row.read_pending = row.read_last_at = None
        row.next_check_at = await _after(s, timedelta(0))
    log.warning("execution_evidence_read_restarted", evidence=row_id)
    return "restarted"


async def _gone_reading(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, row_id: int,
                        run_id: str | None, started_from: bytes | None) -> str:  # fmt: skip
    """A history gone before its read ended (retention deleted it): seen, so lost; what it started past the pages read
    is unknown."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        row = await s.get(ExecutionEvidence, row_id, with_for_update=True, populate_existing=True)
        if row is None or (row.run_id, row.read_at, row.read_token) != (run_id, None, started_from):
            return "moved"
        row.read_token = row.read_run = row.read_pending = row.read_last_at = None
        judged = await _unshown(s, row)
        if judged == "lost":
            log.error("execution_evidence_lost", evidence=row_id)
        row.next_check_at = await _after(s, RECHECK)
        return judged


async def _recorded(sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, row_id: int,
                    workflow_id: str, run_id: str | None, started_from: bytes | None, reading: _Reading,
                    retention: timedelta | None) -> str:  # fmt: skip
    """What a visit's pages found, recorded: every child they showed started, and the run it continued as (recorded by
    the visit that read it: a later one may read only an empty last page, the review's I4); then, the read not done,
    where it stopped (`reading`, due again); done, every child only initiated (by its id alone), the row read
    (`read`)."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        row = await s.get(ExecutionEvidence, row_id, with_for_update=True, populate_existing=True)
        if row is None or (row.run_id, row.read_at, row.read_token) != (run_id, None, started_from):
            return "moved"
        found = list(reading.children)
        if reading.continued is not None:
            found.append((workflow_id, *reading.continued))
        if reading.done:
            found += [(child, None, when) for child, when in reading.initiated.values()]  # may have started: its id
        for child, child_run, when in found:
            if tenant_of(child) != str(tenant_id):
                raise RuntimeError("A child of another tenant than its parent's.")  # server-built ids: impossible
            target = ["workflow_id"] if child_run is None else ["workflow_id", "run_id"]
            where = text("run_id IS NULL") if child_run is None else text("run_id IS NOT NULL")
            seen = None if child_run is None else when  # shown started; one only initiated may not have
            await s.execute(insert(ExecutionEvidence).values(tenant_id=tenant_id, workflow_id=child, run_id=child_run,
                                                             started_at=when, seen_at=seen, checked_at=seen)
                            .on_conflict_do_nothing(index_elements=target, index_where=where))  # fmt: skip
        if not reading.done:
            row.read_run, row.read_token, row.read_last_at = reading.run_id, reading.token, reading.last
            row.read_pending = reading.pending()
            row.next_check_at = await _after(s, timedelta(0))  # read on next pass
            return "reading"
        if reading.last is None:
            raise RuntimeError("A history without events.")
        kept = (retention or RETAINED_FOR) + timedelta(minutes=1)
        row.read_token = row.read_run = row.read_pending = row.read_last_at = None
        row.run_id, row.read_at = reading.run_id, await _after(s, timedelta(0))
        row.next_check_at = await _later(s, kept, reading.last)
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
    """One pass over the evidence due, each row on its own (`read`, `reading`, `restarted`, `open`, `retained`, `gone`,
    `pending`, `lost`, `resolved`, `moved`, `failed`); a row that failed is looked at again later. `retention`: the
    namespace's, as Temporal reports it, which only schedules when a read execution is next described (None: a day)."""
    async with sessionmaker() as s:
        due = (await s.execute(text("select tenant_id, id from execution_evidence_due(:n)"), {"n": batch})).all()
    counts: dict[str, int] = {}
    with budget.passing("evidence") as admitted:
        for tenant_id, row_id in admitted(due, key=lambda row: row[1]):
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
    admitted.reported(counts, full=len(due) >= batch)
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
