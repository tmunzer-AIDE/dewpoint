# SPDX-License-Identifier: Apache-2.0
"""Runs, read-only (spec §8; engine 2b spec §7.7): requests and top-level runs listed together, and one with its steps
and the sub-runs it started (its sub-flows and failure handler). The UI reads this projection, never Temporal history.
A request that hasn't started is shown as its request, never as the row an attempt pre-created. Starting a run is
`run_requests`'s."""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.responses import RunItemOut
from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
from dewpoint.core.authz.permissions import P
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.runs import Run, RunStep
from dewpoint.core.retention import cutoff as retention
from dewpoint.core.runs import service

router = APIRouter(prefix="/api/v1", tags=["runs"])
# The list's status filter (the runs design §4.2): `waiting` is queued or starting; `didnt_start`, refused or dead
ListedStatus = Literal["waiting", "running", "succeeded", "failed", "deadline_exceeded", "cancelled", "didnt_start"]


def _when(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _id(value: uuid.UUID | None) -> str | None:
    return str(value) if value else None


def _request(r: RunRequest | None) -> dict[str, object] | None:
    return {"status": r.status, "source": r.source, "reason": r.reason} if r is not None else None


def _item(i: service.Listed) -> dict[str, object]:
    return {
        "id": str(i.id),
        "workflow_id": str(i.workflow_id),
        "version_id": _id(i.version_id),
        "draft_snapshot_id": _id(i.draft_snapshot_id),  # a draft simulation's (B8): no version
        "target_step_id": _id(i.target_step_id),
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
        "workflow_name": i.workflow_name,
        "started_by": i.started_by,
        "cancel_requested_at": _when(i.cancel_requested_at),
        "trigger": _trigger(i),
    }


def _trigger(i: service.Listed) -> dict[str, object] | None:
    """Where the request came from (the runs design §4.2): null for a run from before 2b-2, which had no request."""
    if i.source is None:
        return None
    timing = None
    if i.schedule_time_zone is not None:  # the schedule, as it is now; a deleted one's left out
        timing = {"cron": i.schedule_cron, "every_s": i.schedule_every_s, "offset_s": i.schedule_offset_s,
                  "time_zone": i.schedule_time_zone}  # fmt: skip
    return {"source": i.source, "schedule": timing, "endpoint": i.endpoint_name, "rerun_of": _id(i.rerun_of)}


def _unstarted(r: RunRequest) -> dict[str, object]:
    """A request that hasn't started, as the list shows it: its own status, no run yet."""
    return {
        "id": str(r.id),
        "workflow_id": str(r.workflow_id),
        "version_id": _id(r.workflow_version_id),
        "draft_snapshot_id": _id(r.draft_snapshot_id),
        "target_step_id": _id(r.target_step_id),
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
        "version_id": _id(r.workflow_version_id),
        "draft_snapshot_id": _id(r.draft_snapshot_id),
        "target_step_id": _id(r.target_step_id),
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
        "effect": r.effect_preview,  # a control step's port or assignments (4d-1a), masked as its previews are
    }


@router.get("/t/{tenant_id}/runs", response_model=list[RunItemOut])
async def list_runs(
    workflow_id: uuid.UUID | None = None,
    status: ListedStatus | None = None,
    mode: Literal["live", "simulate"] | None = None,
    draft: Literal["exclude", "only", "include"] = "exclude",
    source: Literal["manual", "rerun", "schedule", "webhook", "dev"] | None = None,
    since: datetime | None = None,
    before: datetime | None = None,
    before_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    """Requests and runs, newest first by `(queued_at, id)`. The next page: `before` and `before_id`, the last item's
    `queued_at` and `id`, always together: items can be queued in the same instant, so the time alone would skip
    some. Filtered (the runs design §4.2) by workflow, status (`waiting`: queued or starting; `didnt_start`: refused
    or dead), mode, draft simulations (left out unless `draft` is `only` or `include`), source, and `since`."""
    if (before is None) != (before_id is None):
        raise HTTPException(422, detail={"error": "invalid_cursor", "message": "Give before and before_id together."})
    cursor = (before, before_id) if before is not None and before_id is not None else None
    at = await retention.cutoff(db, ctx.tenant_id)
    items = await service.list_items(db, kept_after=at, workflow_id=workflow_id, status=status, mode=mode,
                                     draft=draft, source=source, since=since, before=cursor, limit=limit)  # fmt: skip
    return [_item(i) for i in items]


@router.get("/t/{tenant_id}/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    """A run with its steps and sub-runs, or a request that hasn't started as itself; with its CSV record (engine 2b
    spec §8.1), when it took a CSV: the mapping, the file's headers, the row count and the skipped rows. A run whose
    tree, or a request that, passed the retention cutoff isn't found (§10.1)."""
    at = await retention.cutoff(db, ctx.tenant_id)
    request = await db.get(RunRequest, run_id)  # row-level security: the caller's tenant's only
    if request is not None and not await retention.request_kept(db, at, request):
        raise HTTPException(404, detail={"error": "not_found"})
    csv = None
    if request is not None:
        try:
            csv = await claims.read_csv_record(db, ClaimCipher(keys), ctx.tenant_id, request_id=request.id)
        except Exception as e:
            raise key_unusable(e) from None
    if request is not None and request.status != "started":
        return {**_unstarted(request), "steps": [], "children": [], "csv": csv}
    run = await service.get_run(db, run_id)
    if run is None or run.tenant_id != ctx.tenant_id or not await retention.run_kept(db, at, run):
        raise HTTPException(404, detail={"error": "not_found"})
    return {
        **_run(run),
        "request": _request(request),
        "steps": [_step(r) for r in await service.run_steps(db, run.id)],
        "children": [_child(c) for c in await service.children(db, run.id)],
        "csv": csv,
    }
