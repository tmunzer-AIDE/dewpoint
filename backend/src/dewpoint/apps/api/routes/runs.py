# SPDX-License-Identifier: Apache-2.0
"""Runs, read-only (spec §8): the list of top-level runs, and one run with its steps and the sub-runs it started (its
sub-flows and failure handler). The UI reads this projection, never Temporal history. Starting runs isn't public
until 2b."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.authz.permissions import P
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.runs import Run, RunStep
from dewpoint.core.runs import service

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _when(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _run(r: Run) -> dict[str, object]:
    return {
        "id": str(r.id),
        "workflow_id": str(r.workflow_id),
        "version_id": str(r.workflow_version_id),
        "mode": r.mode,
        "status": r.status,
        "started_at": _when(r.started_at),
        "ended_at": _when(r.ended_at),
        "error": {"code": r.error_code, "message": r.error_message} if r.error_code else None,
        "iterations": r.iterations,
        "kind": r.kind,
        "parent_run_id": str(r.parent_run_id) if r.parent_run_id else None,
    }


def _child(r: Run) -> dict[str, object]:
    return {
        **_run(r),
        "parent_step_id": str(r.parent_step_id) if r.parent_step_id else None,
        "parent_iteration_key": r.parent_iteration_key,
    }


def _step(r: RunStep) -> dict[str, object]:
    return {
        "step_id": str(r.step_id),
        "key": r.node_key,
        "iteration_key": r.iteration_key,
        "attempt": r.attempt,
        "status": r.status,
        "started_at": _when(r.started_at),
        "ended_at": _when(r.ended_at),
        "input": r.input_preview,
        "output": r.output_preview,
        "error": {"code": r.error_code, "message": r.error_message} if r.error_code else None,
        "outcome": r.outcome,
        "cel_mode": r.cel_mode,
    }


@router.get("/t/{tenant_id}/runs")
async def list_runs(
    workflow_id: uuid.UUID | None = None,
    before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    return [_run(r) for r in await service.list_runs(db, workflow_id=workflow_id, before=before, limit=limit)]


@router.get("/t/{tenant_id}/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    run = await service.get_run(db, run_id)
    if run is None or run.tenant_id != ctx.tenant_id:
        raise HTTPException(404, detail={"error": "not_found"})
    return {
        **_run(run),
        "steps": [_step(r) for r in await service.run_steps(db, run.id)],
        "children": [_child(c) for c in await service.children(db, run.id)],
    }
