# SPDX-License-Identifier: Apache-2.0
"""Storage for runs and their per-step projection (engine spec §8). Rows arrive as plain mappings: `core` knows
nothing of the engine. Every write is idempotent, so a retried projection changes nothing twice, and a late
`running` row never overwrites a finished attempt."""

import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.runs import Run, RunStep

MESSAGE_LIMIT = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
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
    """A message or code fit to show: no control characters, at most MESSAGE_LIMIT characters."""
    if message is None:
        return None
    clean = _CONTROL.sub(" ", message)
    return clean if len(clean) <= MESSAGE_LIMIT else clean[: MESSAGE_LIMIT - 1] + "…"


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
    )
    s.add(run)
    await s.flush()
    return run


async def finish_run(
    s: AsyncSession,
    run_id: uuid.UUID,
    *,
    status: str,
    ended_at: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
    iterations: int = 0,
) -> None:
    await s.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(
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
    s: AsyncSession, *, workflow_id: uuid.UUID | None = None, before: datetime | None = None, limit: int = 50
) -> list[Run]:
    """Newest first; `before` pages through older runs."""
    q = select(Run).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
    if workflow_id is not None:
        q = q.where(Run.workflow_id == workflow_id)
    if before is not None:
        q = q.where(Run.started_at < before)
    return list((await s.execute(q)).scalars())


async def run_steps(s: AsyncSession, run_id: uuid.UUID) -> list[RunStep]:
    q = (
        select(RunStep)
        .where(RunStep.run_id == run_id)
        .order_by(RunStep.started_at.nulls_last(), RunStep.iteration_key, RunStep.step_id, RunStep.attempt)
    )
    return list((await s.execute(q)).scalars())
