# SPDX-License-Identifier: Apache-2.0
"""Storage for runs and their per-step projection (engine spec §8). Rows arrive as plain mappings: `core` knows
nothing of the engine. Every write is idempotent, so a retried projection changes nothing twice, and a late
`running` row never overwrites a finished attempt."""

import math
import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, literal, null, or_, select, text, tuple_, union_all, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.runs import ExecutionEvidence, Run, RunStep
from dewpoint.core.retention.cutoff import Cutoff, kept

MESSAGE_LIMIT = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")  # Postgres takes no NUL, and a lone surrogate isn't UTF-8
STEP_FIELDS = (
    "node_key",
    "status",
    "started_at",
    "ended_at",
    "input_preview",
    "output_preview",
    "error_code",
    "error_message",
    "outcome",
    "cel_mode",
)


def sanitize(message: str | None) -> str | None:
    """A message or code fit to show and to store: no control characters, no lone surrogates, at most MESSAGE_LIMIT
    characters."""
    if message is None:
        return None
    clean = _UNSTORABLE.sub("\ufffd", _CONTROL.sub(" ", message))
    return clean if len(clean) <= MESSAGE_LIMIT else clean[: MESSAGE_LIMIT - 1] + "…"


def storable(value: Any) -> Any:
    """A preview Postgres stores as jsonb: NUL and lone surrogates, in strings and keys, become U+FFFD, and a number
    JSON can't hold (NaN, infinity) its name. A refused write would be retried forever, and its run never end."""
    if isinstance(value, str):
        return _UNSTORABLE.sub("\ufffd", value)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {storable(k): storable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [storable(v) for v in value]
    return value


async def insert_run(
    s: AsyncSession,
    *,
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    mode: str,
    started_by: uuid.UUID | None = None,
) -> Run:
    run = Run(
        id=run_id,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        workflow_version_id=version_id,
        mode=mode,
        status="running",
        iterations=0,
        started_by=started_by,
        started_at=func.now(),
    )
    s.add(run)
    await s.flush()
    return run


async def precreate_run(
    s: AsyncSession,
    *,
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    mode: str,
    started_by: uuid.UUID | None,
    queued_at: datetime,
) -> None:
    """A root run's row, written at dispatch before Temporal answers (engine 2b spec §7.3): queued with its request,
    not yet started. An earlier attempt's row is reused: a retried dispatch changes nothing."""
    statement = insert(Run).values(
        id=run_id,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        workflow_version_id=version_id,
        mode=mode,
        status="running",
        iterations=0,
        started_by=started_by,
        queued_at=queued_at,
    )
    await s.execute(statement.on_conflict_do_nothing(index_elements=["id"]))


async def ensure_run(
    s: AsyncSession,
    *,
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    mode: str,
    kind: str,
    parent_run_id: uuid.UUID,
    parent_step_id: uuid.UUID | None,
    parent_iteration_key: str,
    started_at: datetime,
) -> None:
    """A sub-run's own row, written by its first projection: a retried write changes nothing."""
    statement = insert(Run).values(
        id=run_id,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        workflow_version_id=version_id,
        mode=mode,
        status="running",
        started_at=started_at,
        iterations=0,
        kind=kind,
        parent_run_id=parent_run_id,
        parent_step_id=parent_step_id,
        parent_iteration_key=parent_iteration_key,
    )
    await s.execute(statement.on_conflict_do_nothing(index_elements=["id"]))


async def record_attempt(s: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID) -> None:
    """A root's execution evidence for a start attempt, in the caller's transaction, before Temporal is asked (the
    owner's M3 rulings): when it was written is no later than any payload the attempt seals. An attempt reusing its row
    (a retried dispatch) writes it again; one already there stays as it is."""
    await s.execute(
        insert(ExecutionEvidence)
        .values(tenant_id=tenant_id, workflow_id=_root(tenant_id, run_id), started_at=func.statement_timestamp())
        .on_conflict_do_nothing(index_elements=["workflow_id"], index_where=text("run_id IS NULL"))
    )


async def settle_attempt(s: AsyncSession, tenant_id: uuid.UUID, run_id: uuid.UUID, outcome: str) -> None:
    """What a root's start attempt left, in the caller's tenant scope (the owner's M3 rulings):
    - `refused`: Temporal refused it (or throttled it before creating anything): its evidence goes, unless an earlier
      attempt is unproven;
    - `unproven`: Temporal may have taken it (an absence seen at one moment, an uncertain start, a collision's
      execution): kept, unproven. A point-in-time absence doesn't fence a start still in flight, and nothing proves
      a start Temporal never showed didn't land and go unseen: only Temporal showing it, then reading it, settles it."""
    where = (ExecutionEvidence.tenant_id == tenant_id, ExecutionEvidence.workflow_id == _root(tenant_id, run_id),
             ExecutionEvidence.run_id.is_(None))  # fmt: skip
    if outcome == "refused":
        await s.execute(delete(ExecutionEvidence).where(*where, ExecutionEvidence.unproven.is_(False)))
    elif outcome == "unproven":
        await s.execute(update(ExecutionEvidence).where(*where).values(unproven=True))
    else:
        raise ValueError(f"no such attempt outcome: {outcome}")


def _root(tenant_id: uuid.UUID, run_id: uuid.UUID) -> str:
    return f"t:{tenant_id}:run:{run_id}"  # engine.runtime.ids.run_workflow_id, as migration 0039's trigger builds it


async def finish_run(
    s: AsyncSession,
    run_id: uuid.UUID,
    *,
    status: str,
    ended_at: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
    iterations: int = 0,
    if_running: bool = False,
) -> None:
    """A run's end. `if_running`: only if it has none yet, as when a parent writes the end of a child that was
    terminated before it could write its own."""
    query = update(Run).where(Run.id == run_id)
    if if_running:
        query = query.where(Run.status == "running")
    await s.execute(
        query.values(
            status=status,
            ended_at=ended_at,
            error_code=sanitize(error_code),
            error_message=sanitize(error_message),
            iterations=iterations,
        )
    )


async def upsert_steps(s: AsyncSession, tenant_id: uuid.UUID, rows: Iterable[Mapping[str, Any]]) -> None:
    for row in rows:
        values = {
            "tenant_id": tenant_id,
            "run_id": row["run_id"],
            "step_id": row["step_id"],
            "iteration_key": row["iteration_key"],
            "attempt": row["attempt"],
            **{k: row.get(k) for k in STEP_FIELDS},
        }
        values["error_code"] = sanitize(values["error_code"])
        values["error_message"] = sanitize(values["error_message"])
        values["input_preview"] = storable(values["input_preview"])
        values["output_preview"] = storable(values["output_preview"])
        statement = insert(RunStep).values(**values)
        fresh = statement.excluded
        await s.execute(
            statement.on_conflict_do_update(
                index_elements=["run_id", "step_id", "iteration_key", "attempt"],
                set_={k: getattr(fresh, k) for k in STEP_FIELDS},
                where=(RunStep.status == "running") | (fresh.status != "running"),
            )
        )


async def get_run(s: AsyncSession, run_id: uuid.UUID) -> Run | None:
    return await s.get(Run, run_id)


async def list_runs(
    s: AsyncSession,
    *,
    workflow_id: uuid.UUID | None = None,
    before: tuple[datetime, uuid.UUID] | None = None,
    limit: int = 50,
) -> list[Run]:
    """Top-level runs, newest first. The next page starts after the last run of this one: `before` is its start time
    and its id, since runs can start in the same instant. Sub-runs are listed with their parent."""
    q = select(Run).where(Run.parent_run_id.is_(None)).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
    if workflow_id is not None:
        q = q.where(Run.workflow_id == workflow_id)
    if before is not None:
        q = q.where(tuple_(Run.started_at, Run.id) < tuple_(*before))
    return list((await s.execute(q)).scalars())


@dataclass(frozen=True)
class Listed:
    """One item of the runs list (engine 2b spec §7.7): a top-level run, or a request that hasn't started. `status` is
    the run's once its request started (or when it has none, from before 2b-2), else the request's."""

    id: uuid.UUID
    workflow_id: uuid.UUID
    version_id: uuid.UUID | None
    mode: str
    status: str
    queued_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    error_code: str | None
    error_message: str | None
    iterations: int
    kind: str
    request_status: str | None
    source: str | None
    reason: str | None


async def list_items(
    s: AsyncSession,
    *,
    kept_after: Cutoff,
    workflow_id: uuid.UUID | None = None,
    before: tuple[datetime, uuid.UUID] | None = None,
    limit: int = 50,
) -> list[Listed]:
    """Requests and runs together, newest first by `(queued_at, id)`; the next page starts after the last item of this
    one. A request's pre-created row is never shown until its request has started (§7.3): the request is. Nothing past
    the retention cutoff `kept_after` is (§10.1): every run listed is a root, so its own end is its tree's."""
    runs = (
        select(
            Run.id, Run.workflow_id, Run.workflow_version_id.label("version_id"), Run.mode, Run.status, Run.queued_at,
            Run.started_at, Run.ended_at, Run.error_code, Run.error_message, Run.iterations, Run.kind,
            RunRequest.status.label("request_status"), RunRequest.source, RunRequest.reason,
        )
        .outerjoin(RunRequest, RunRequest.id == Run.id)
        .where(Run.parent_run_id.is_(None), or_(RunRequest.id.is_(None), RunRequest.status == "started"),
               kept(Run.ended_at, kept_after))
    )  # fmt: skip
    requests = select(
        RunRequest.id, RunRequest.workflow_id, RunRequest.workflow_version_id.label("version_id"), RunRequest.mode,
        RunRequest.status, RunRequest.queued_at, null().label("started_at"), RunRequest.ended_at,
        null().label("error_code"), null().label("error_message"), literal(0).label("iterations"),
        literal("run").label("kind"), RunRequest.status.label("request_status"), RunRequest.source, RunRequest.reason,
    ).where(RunRequest.status != "started", kept(RunRequest.ended_at, kept_after))  # fmt: skip
    if workflow_id is not None:
        runs, requests = (
            runs.where(Run.workflow_id == workflow_id),
            requests.where(RunRequest.workflow_id == workflow_id),
        )
    both = union_all(runs, requests).subquery()
    q = select(both).order_by(both.c.queued_at.desc(), both.c.id.desc()).limit(limit)
    if before is not None:
        q = q.where(tuple_(both.c.queued_at, both.c.id) < tuple_(*before))
    return [Listed(**row._mapping) for row in await s.execute(q)]


async def children(s: AsyncSession, run_id: uuid.UUID) -> list[Run]:
    """The sub-runs a run started, in the order they started."""
    q = select(Run).where(Run.parent_run_id == run_id).order_by(Run.started_at, Run.id)
    return list((await s.execute(q)).scalars())


async def run_steps(s: AsyncSession, run_id: uuid.UUID) -> list[RunStep]:
    q = (
        select(RunStep)
        .where(RunStep.run_id == run_id)
        .order_by(RunStep.started_at.nulls_last(), RunStep.iteration_key, RunStep.step_id, RunStep.attempt)
    )
    return list((await s.execute(q)).scalars())
