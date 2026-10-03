# SPDX-License-Identifier: Apache-2.0
"""Runs, read-only (spec §8; engine 2b spec §7.7): requests and top-level runs listed together, and one with its steps
and the sub-runs it started (its sub-flows and failure handler). The UI reads this projection, never Temporal history.
A request that hasn't started is shown as its request, never as the row an attempt pre-created. Starting a run is
`run_requests`'s."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
from dewpoint.core.authz.permissions import P
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.runs import Run, RunStep
from dewpoint.core.runs import service

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _when(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _request(r: RunRequest | None) -> dict[str, object] | None:
    return {"status": r.status, "source": r.source, "reason": r.reason} if r is not None else None


def _item(i: service.Listed) -> dict[str, object]:
    return {
        "id": str(i.id),
        "workflow_id": str(i.workflow_id),
        "version_id": str(i.version_id) if i.version_id else None,
        "mode": i.mode,
        "status": i.status,
        "queued_at": _when(i.queued_at),
        "started_at": _when(i.started_at),
        "ended_at": _when(i.ended_at),
        "error": {"code": i.error_code, "message": i.error_message} if i.error_code else None,
        "iterations": i.iterations,
        "kind": i.kind,
        "parent_run_id": None,
        "request": {"status": i.request_status, "source": i.source, "reason": i.reason} if i.request_status else None,
    }


def _unstarted(r: RunRequest) -> dict[str, object]:
    """A request that hasn't started, as the list shows it: its own status, no run yet."""
    return {
        "id": str(r.id),
        "workflow_id": str(r.workflow_id),
        "version_id": str(r.workflow_version_id) if r.workflow_version_id else None,
        "mode": r.mode,
        "status": r.status,
        "queued_at": _when(r.queued_at),
        "started_at": None,
        "ended_at": _when(r.ended_at),
        "error": None,
        "iterations": 0,
        "kind": "run",
        "parent_run_id": None,
        "request": _request(r),
    }


def _run(r: Run) -> dict[str, object]:
    return {
        "id": str(r.id),
        "workflow_id": str(r.workflow_id),
        "version_id": str(r.workflow_version_id),
        "mode": r.mode,
        "status": r.status,
        "queued_at": _when(r.queued_at),
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
    before_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    """Requests and runs, newest first by `(queued_at, id)`. The next page: `before` and `before_id`, the last item's
    `queued_at` and `id`, always together: items can be queued in the same instant, so the time alone would skip
    some."""
    if (before is None) != (before_id is None):
        raise HTTPException(422, detail={"error": "invalid_cursor", "message": "Give before and before_id together."})
    cursor = (before, before_id) if before is not None and before_id is not None else None
    items = await service.list_items(db, workflow_id=workflow_id, before=cursor, limit=limit)
    return [_item(i) for i in items]


@router.get("/t/{tenant_id}/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    """A run with its steps and sub-runs, or a request that hasn't started as itself; with its CSV record (engine 2b
    spec §8.1), when it took a CSV: the mapping, the file's headers, the row count and the skipped rows."""
    request = await db.get(RunRequest, run_id)  # row-level security: the caller's tenant's only
    csv = None
    if request is not None:
        try:
            csv = await claims.read_csv_record(db, ClaimCipher(keys), ctx.tenant_id, request_id=request.id)
        except Exception as e:
            raise key_unusable(e) from None
    if request is not None and request.status != "started":
        return {**_unstarted(request), "steps": [], "children": [], "csv": csv}
    run = await service.get_run(db, run_id)
    if run is None or run.tenant_id != ctx.tenant_id:
        raise HTTPException(404, detail={"error": "not_found"})
    return {
        **_run(run),
        "request": _request(request),
        "steps": [_step(r) for r in await service.run_steps(db, run.id)],
        "children": [_child(c) for c in await service.children(db, run.id)],
        "csv": csv,
    }
