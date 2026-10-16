# SPDX-License-Identifier: Apache-2.0
"""Runs, read-only (spec §8; engine 2b spec §7.7; editor 4e-1): requests and top-level runs listed together, filtered,
and one as itself, its steps read apart (summarized and paged). The UI reads this projection, never Temporal history.
A request that hasn't started is shown as its request, never as the row an attempt pre-created. Starting a run is
`run_requests`'s."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import step_summary
from dewpoint.apps.api.responses import RunAttemptsOut, RunInstancesOut, RunItemOut, RunOut, RunStepsOut
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
        "trigger": _trigger(i.source, i.rerun_of, i),
    }


def _trigger(
    source: str | None, rerun_of: uuid.UUID | None, named: service.Listed | service.Labels
) -> dict[str, object] | None:
    """Where the request came from (the runs design §4.2): null for a run from before 2b-2, which had no request."""
    if source is None:
        return None
    timing = None
    if named.schedule_time_zone is not None:  # the schedule, as it is now; a deleted one's left out
        timing = {"cron": named.schedule_cron, "every_s": named.schedule_every_s, "offset_s": named.schedule_offset_s,
                  "time_zone": named.schedule_time_zone}  # fmt: skip
    return {"source": source, "schedule": timing, "endpoint": named.endpoint_name, "rerun_of": _id(rerun_of)}


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


def _step(r: RunStep, child: uuid.UUID | None = None) -> dict[str, object]:
    """One attempt of a step instance, and the sub-run it started (the runs design §4.4)."""
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
        "child_run_id": _id(child),
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


@router.get("/t/{tenant_id}/runs/{run_id}", response_model=RunOut)
async def get_run(
    run_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    """A run, or a request that hasn't started as itself (the runs design §4.3): what the list says of it, the draft
    revision a draft simulation ran, whether its graph records every step instance's end, the run a sub-run's step
    started it from, and its CSV record (engine 2b spec §8.1) when it took a CSV. Its steps are read apart (§4.4). A run
    whose tree, or a request that, passed the retention cutoff isn't found (§10.1)."""
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
    parent = None
    of: Run | RunRequest
    if request is not None and request.status != "started":
        base, of, actor = _unstarted(request), request, request.actor_id
    else:
        run = await service.get_run(db, run_id)
        if run is None or run.tenant_id != ctx.tenant_id or not await retention.run_kept(db, at, run):
            raise HTTPException(404, detail={"error": "not_found"})
        base, of = {**_run(run), "request": _request(request)}, run
        actor = run.started_by if request is None else request.actor_id  # before 2b-2, a run had no request
        if run.parent_run_id is not None:
            parent = {"run_id": str(run.parent_run_id), "step_id": _id(run.parent_step_id),
                      "iteration_key": run.parent_iteration_key}  # fmt: skip
    source = request.source if request is not None else None
    named = await service.labels(db, workflow_id=of.workflow_id, actor_id=actor, source=source,
                                 trigger_id=request.trigger_id if request is not None else None)  # fmt: skip
    _, abi = await service.graph_of(db, of.workflow_version_id, of.draft_snapshot_id)
    return {
        **base,
        "workflow_name": named.workflow_name,
        "started_by": named.started_by,
        "cancel_requested_at": _when(request.cancel_requested_at) if request is not None else None,
        "trigger": _trigger(source, request.rerun_of if request is not None else None, named),
        "draft_revision": request.draft_revision if request is not None else None,
        "outcomes_recorded": abi is None or abi >= step_summary.OUTCOMES_ABI,
        "parent": parent,
        "csv": csv,
    }


async def _ran(db: AsyncSession, ctx: TenantContext, run_id: uuid.UUID) -> tuple[Run | None, Run | RunRequest]:
    """A run within retention, or a request that hasn't started (no run yet); and the one of them that says what it
    runs. Else 404."""
    at = await retention.cutoff(db, ctx.tenant_id)
    request = await db.get(RunRequest, run_id)  # row-level security: the caller's tenant's only
    if request is not None and not await retention.request_kept(db, at, request):
        raise HTTPException(404, detail={"error": "not_found"})
    if request is not None and request.status != "started":
        return None, request
    run = await service.get_run(db, run_id)
    if run is None or run.tenant_id != ctx.tenant_id or not await retention.run_kept(db, at, run):
        raise HTTPException(404, detail={"error": "not_found"})
    return run, run


async def _nodes(db: AsyncSession, of: Run | RunRequest) -> tuple[list[dict[str, Any]], bool]:
    """The steps a run ran (its graph's, or a step test's target alone), and whether its graph's engine records every
    step instance's end (B4b)."""
    graph, abi = await service.graph_of(db, of.workflow_version_id, of.draft_snapshot_id)
    nodes: list[dict[str, Any]] = [] if graph is None else graph["nodes"]
    target = of.target_step_id
    recorded = abi is None or abi >= step_summary.OUTCOMES_ABI
    return [n for n in nodes if target is None or n["id"] == str(target)], recorded


@router.get("/t/{tenant_id}/runs/{run_id}/steps", response_model=RunStepsOut)
async def run_steps(
    run_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A run's steps in run order, summarized (the runs design §4.4): the tags the UI shows come from here, never from
    a partial page of instances. A request that hasn't started has steps that haven't run."""
    run, of = await _ran(db, ctx, run_id)
    nodes, recorded = await _nodes(db, of)
    ended = run.status != "running" if run is not None else of.ended_at is not None
    summarized = await step_summary.summarize(
        db, None if run is None else run.id, nodes, ended=ended, error_code=None if run is None else run.error_code,
        live=of.mode == "live", recorded=recorded,
    )  # fmt: skip
    singles = [(x.step_id, x.final.iteration_key) for x in summarized if x.final is not None]
    started = await step_summary.children(db, run.id, singles) if run is not None else {}
    return {
        "given": "input" if of.target_step_id is None else "seeded",
        "steps": [
            {"step_id": str(x.step_id), "key": x.key, "type": x.type, "origin": x.origin, "instances": x.instances,
             "statuses": x.statuses, "ports": x.ports,
             "final": None if x.final is None else _step(x.final, started.get((x.step_id, x.final.iteration_key)))}
            for x in summarized
        ],
    }  # fmt: skip


@router.get("/t/{tenant_id}/runs/{run_id}/steps/{step_id}/instances", response_model=RunInstancesOut)
async def step_instances(
    run_id: uuid.UUID,
    step_id: uuid.UUID,
    within: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A step's instances in a run, one per iteration (its final attempt), in iteration order, paged from `offset`;
    with `within`, only that iteration's (itself and every iteration nested in it). Each names the sub-run it
    started."""
    run, of = await _ran(db, ctx, run_id)
    nodes, _ = await _nodes(db, of)
    if str(step_id) not in {n["id"] for n in nodes}:
        raise HTTPException(404, detail={"error": "not_found"})
    if run is None:
        return {"total": 0, "items": []}
    total, rows = await step_summary.instances(db, run.id, step_id, within=within, offset=offset, limit=limit)
    started = await step_summary.children(db, run.id, [(r.step_id, r.iteration_key) for r in rows])
    return {"total": total, "items": [_step(r, started.get((r.step_id, r.iteration_key))) for r in rows]}


@router.get("/t/{tenant_id}/runs/{run_id}/steps/{step_id}/attempts", response_model=RunAttemptsOut)
async def step_attempts(
    run_id: uuid.UUID,
    step_id: uuid.UUID,
    iteration: str = "",
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """One step instance's attempts, first to last: `iteration` is its iteration key (empty outside a loop)."""
    run, of = await _ran(db, ctx, run_id)
    nodes, _ = await _nodes(db, of)
    if str(step_id) not in {n["id"] for n in nodes}:
        raise HTTPException(404, detail={"error": "not_found"})
    if run is None:
        return {"items": []}
    rows = await step_summary.attempts(db, run.id, step_id, iteration)
    started = await step_summary.children(db, run.id, [(step_id, iteration)])
    return {"items": [_step(r, started.get((r.step_id, r.iteration_key))) for r in rows]}
