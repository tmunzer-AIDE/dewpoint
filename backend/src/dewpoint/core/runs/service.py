# SPDX-License-Identifier: Apache-2.0
"""Storage for runs and their per-step projection (engine spec §8). Rows arrive as plain mappings: `core` knows
nothing of the engine. Every write is idempotent, so a retried projection changes nothing twice, and a late
`running` row never overwrites a finished attempt."""

import math
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
