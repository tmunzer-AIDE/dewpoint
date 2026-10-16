# SPDX-License-Identifier: Apache-2.0
"""Simulating a workflow's draft (B8; the simulation design §6.3): `POST …/draft/simulations` admits a request frozen
on a snapshot of the draft at the revision `If-Match` names, under an `Idempotency-Key`, always `simulate` and
`manual`, and the dispatcher starts it as any run. `{input}` simulates the workflow; `{target}` a step alone with the
values it reads (S2). It needs `workflow.edit` and `run.start`; cancelling is the run's own route (`run.cancel`)."""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import admission, seed_form, step_summary, workflow_ops
from dewpoint.apps.api.responses import (
    DraftSnapshotOut,
    DraftStartFormOut,
    SeedContractOut,
    SimulationOut,
    SimulationStateOut,
    SimulationStepsOut,
    StepInstancesOut,
)
from dewpoint.apps.api.routes.run_requests import (
    INVALID,
    UNAVAILABLE,
    get_keys,
    idempotency_key,
    key_unusable,
    not_past_cutoff,
    request_body,
)
from dewpoint.apps.api.routes.runs import _step, read_back
from dewpoint.apps.api.routes.workflows import _get, _revision
from dewpoint.apps.forms import csv_form, form_fields
from dewpoint.core.authz.permissions import P
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.runs import Run
from dewpoint.core.models.workflows import DraftSnapshot, Workflow
from dewpoint.core.retention import cutoff as retention
from dewpoint.core.workflows.service import DraftConflictError
from dewpoint.engine.graph import seeds
from dewpoint.engine.graph.model import GraphFormatError, parse_graph

router = APIRouter(prefix="/api/v1", tags=["simulations"])


class TargetIn(BaseModel):
    """A step to run alone (S2) and the values it reads, given or absent by pointer (the simulation design §5.2)."""

    model_config = ConfigDict(extra="forbid")
    step_id: uuid.UUID
    values: dict[str, Any] = Field(default_factory=dict)
    absent: list[str] = Field(default_factory=list)


class SimulateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: dict[str, Any] = Field(default_factory=dict)  # the workflow's, as its draft's trigger schema takes it
    target: TargetIn | None = None

    @model_validator(mode="after")
    def _one(self) -> "SimulateIn":
        if self.target is not None and self.input:
            raise ValueError("A step simulated alone takes its values, not the workflow's input.")
        return self


def simulation_body(r: RunRequest) -> dict[str, object]:
    """A draft simulation's request as the API shows it, never its input or seeds."""
    return {
        **request_body(r),
        "draft_snapshot_id": str(r.draft_snapshot_id),
        "draft_revision": r.draft_revision,
        "target_step_id": str(r.target_step_id) if r.target_step_id else None,
        "admission_checks": r.admission_checks or [],
    }


@router.post("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations", status_code=202, response_model=SimulationOut)
async def simulate(
    workflow_id: uuid.UUID,
    body: SimulateIn,
    if_match: str | None = Header(default=None, alias="If-Match"),
    key: str = Depends(idempotency_key),
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT, P.RUN_START)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    revision = _revision(if_match)
    target = body.target
    simulation = admission.Simulation(
        revision,
        target.step_id if target else None,
        dict(target.values) if target else {},
        tuple(target.absent) if target else (),
    )
    try:
        admitted = await admission.admit_draft(db, keys, ctx, workflow_id=workflow_id, idempotency_key=key,
                                               input=body.input, simulation=simulation, settings=settings)  # fmt: skip
    except admission.WorkflowNotFoundError:
        raise HTTPException(404, detail={"error": "not_found"}) from None
    except admission.IdempotencyConflictError:
        raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
    except DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    except admission.DraftInvalidError as e:
        diagnostics = [d.to_json() for d in [*e.blocking, *e.warnings]]
        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics}) from None
    except admission.SeedsRefusedError as e:
        problems = [{"code": p.code, "pointer": p.pointer, "message": p.message} for p in e.problems]
        raise HTTPException(422, detail={"error": e.reason, "problems": problems}) from None
    except admission.AdmissionRefusedError as e:
        refused = INVALID | {admission.TARGET_INVALID, admission.CSV_NOT_SIMULATED}
        status = 503 if e.reason in UNAVAILABLE else 422 if e.reason in refused else 409
        raise HTTPException(status, detail={"error": e.reason, "messages": e.messages}) from None
    except Exception as e:
        raise key_unusable(e) from None
    if not admitted.new:
        await not_past_cutoff(db, ctx, admitted.request)
    return simulation_body(admitted.request)


@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/snapshots/{snapshot_id}", response_model=DraftSnapshotOut)
async def snapshot(
    workflow_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A draft run's snapshot (B8; the simulation design §6.5), as B4a's read shows a version."""
    found = await db.execute(
        select(DraftSnapshot).where(DraftSnapshot.id == snapshot_id, DraftSnapshot.workflow_id == workflow_id)
    )
    s = found.scalar_one_or_none()
    if s is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return {
        "id": str(s.id),
        "workflow_id": str(s.workflow_id),
        "draft_revision": s.draft_revision,
        "created_at": s.created_at.isoformat(),
        "graph_hash": s.graph_hash,
        "version_hash": s.version_hash,
        "cel_profile": s.cel_profile,
        "engine_abi": s.engine_abi,
        "node_refs": list(s.node_refs),
        "graph": s.graph,
        "expressions": [
            {"node": e.get("node"), "field": e["field"], "mode": e["mode"], "reason": e.get("reason")}
            for e in s.expressions
        ],
    }


@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations", response_model=list[SimulationOut])
async def mine(
    workflow_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=50),
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    """The caller's own latest draft simulations of the workflow, newest first (§6.6): what they started, labelled
    with their revision, never proof of what a submission was (the editor recovers by its own request's key)."""
    await _get(db, ctx, workflow_id)  # a workflow the tenant doesn't have isn't found, as its other reads say
    found = await db.execute(
        select(RunRequest)
        .where(
            RunRequest.workflow_id == workflow_id,
            RunRequest.actor_id == ctx.user.id,
            RunRequest.draft_snapshot_id.is_not(None),
            retention.kept(RunRequest.ended_at, await retention.cutoff(db, ctx.tenant_id)),
        )
        .order_by(RunRequest.queued_at.desc(), RunRequest.id.desc())
        .limit(limit)
    )
    return [simulation_body(r) for r in found.scalars()]


@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}", response_model=SimulationStateOut)
async def state(
    workflow_id: uuid.UUID,
    request_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    """A draft simulation where it is (§6.6), and what it ran with, read back redacted from its own request."""
    r = await simulation_of(db, ctx, workflow_id, request_id)
    run = await db.get(Run, r.id)
    kept, used = await read_back(db, keys, ctx, r)
    return {
        "request": simulation_body(r),
        "run": None if run is None else {
            "status": run.status,
            "queued_at": run.queued_at.isoformat() if run.queued_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
            "error": {"code": run.error_code, "message": run.error_message} if run.error_code else None,
            "iterations": run.iterations,
        },
        "cancel_requested": r.cancel_requested_at is not None,
        "read_back": kept,
        "input": used if r.target_step_id is None else None,
        "seeds": used if r.target_step_id is not None else None,
    }  # fmt: skip


async def simulation_of(
    db: AsyncSession, ctx: TenantContext, workflow_id: uuid.UUID, request_id: uuid.UUID
) -> RunRequest:
    """The workflow's draft simulation `request_id`, within retention; else 404."""
    found = await db.execute(
        select(RunRequest).where(
            RunRequest.id == request_id,
            RunRequest.workflow_id == workflow_id,
            RunRequest.draft_snapshot_id.is_not(None),
        )
    )
    r = found.scalar_one_or_none()
    if r is None or not await retention.request_kept(db, await retention.cutoff(db, ctx.tenant_id), r):
        raise HTTPException(404, detail={"error": "not_found"})
    return r


@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps",
            response_model=SimulationStepsOut)  # fmt: skip
async def simulation_steps(
    workflow_id: uuid.UUID,
    request_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A draft simulation's steps in run order, summarized (§6.6): the tags the editor shows come from here, never
    from a partial page of instances."""
    r = await simulation_of(db, ctx, workflow_id, request_id)
    run = await db.get(Run, r.id)
    summarized = await step_summary.summarize(
        db, None if run is None else run.id, await _steps_of(db, r),
        ended=r.ended_at is not None if run is None else run.status != "running",
        error_code=None if run is None else run.error_code,
    )  # fmt: skip
    return {
        "given": "input" if r.target_step_id is None else "seeded",
        "steps": [
            {"step_id": str(x.step_id), "key": x.key, "type": x.type, "origin": x.origin, "instances": x.instances,
             "statuses": x.statuses, "ports": x.ports, "final": None if x.final is None else _step(x.final)}
            for x in summarized
        ],
    }  # fmt: skip


@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps/{step_id}/instances",
            response_model=StepInstancesOut)  # fmt: skip
async def step_instances(
    workflow_id: uuid.UUID,
    request_id: uuid.UUID,
    step_id: uuid.UUID,
    within: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A step's instances in a draft simulation, one per iteration (its final attempt), in iteration order, paged
    from `offset`; with `within`, only that iteration's (itself and every iteration nested in it)."""
    r = await simulation_of(db, ctx, workflow_id, request_id)
    if str(step_id) not in {n["id"] for n in await _steps_of(db, r)}:
        raise HTTPException(404, detail={"error": "not_found"})
    total, rows = await step_summary.instances(db, r.id, step_id, within=within, offset=offset, limit=limit)
    return {"total": total, "items": [_step(x) for x in rows]}


async def _steps_of(db: AsyncSession, r: RunRequest) -> list[dict[str, Any]]:
    """The steps a simulation ran: its snapshot's, or a step test's target alone."""
    snapshot = await db.get(DraftSnapshot, r.draft_snapshot_id)
    nodes: list[dict[str, Any]] = [] if snapshot is None else snapshot.graph["nodes"]
    return [n for n in nodes if r.target_step_id is None or n["id"] == str(r.target_step_id)]


async def _draft_at(db: AsyncSession, ctx: TenantContext, workflow_id: uuid.UUID, revision: int) -> Workflow:
    """The workflow, its draft at `revision`: else 409 `draft_conflict`, naming the draft's (a form never pairs a new
    revision with an older read)."""
    wf = await _get(db, ctx, workflow_id)
    if wf.draft_revision != revision:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": wf.draft_revision})
    return wf


@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/start-form", response_model=DraftStartFormOut,
            response_model_exclude_unset=True)  # fmt: skip
async def draft_start_form(
    workflow_id: uuid.UUID,
    revision: int = Query(ge=1),
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT, P.RUN_START)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """The draft's input at `revision`, as a form (§7.1): `start-form`'s, which reads only the active version."""
    wf = await _draft_at(db, ctx, workflow_id, revision)
    try:
        graph = parse_graph(wf.draft)
    except GraphFormatError as e:
        diagnostics = [d.to_json() for d in e.diagnostics]
        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics}) from None
    csv = graph.settings.csv
    return {
        "workflow_id": str(wf.id),
        "draft_revision": wf.draft_revision,
        "fields": form_fields(graph.settings.input_schema),
        "csv": csv_form(csv.model_dump(mode="json") if csv is not None else None),
    }


@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/steps/{step_id}/seeds", response_model=SeedContractOut)
async def seed_contract(
    workflow_id: uuid.UUID,
    step_id: uuid.UUID,
    revision: int = Query(ge=1),
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT, P.RUN_START, P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    """A step's seed contract at `revision` (§5.2, §6.6), the draft validated first as admission validates it (422
    `invalid`, its blocking problems: an invalid draft's contract would miss reads), each entry prefilled from its
    step's own sample where D-s2 allows (run data: `run.view`), else typed, saying why."""
    wf = await _draft_at(db, ctx, workflow_id, revision)
    if workflow_ops.draft_node(wf.draft, step_id) is None:
        raise HTTPException(404, detail={"error": "not_found"})
    checked = await workflow_ops.check_draft(db, ctx.tenant_id, wf.draft, settings)
    sim = await workflow_ops.simulatable(db, ctx, wf, checked)
    if sim.new is None or checked.graph is None or checked.context is None:
        diagnostics = [d.to_json() for d in [*sim.blocking, *sim.warnings]]
        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics})
    contract = await asyncio.to_thread(seeds.contract, checked.graph, checked.context, step_id)
    steps = {n.key: n.id for n in checked.graph.nodes}
    filled = await seed_form.prefills(db, ctx.tenant_id, wf.id, steps, contract,
                                      await retention.cutoff(db, ctx.tenant_id))  # fmt: skip
    return {
        "draft_revision": wf.draft_revision,
        "step_id": str(step_id),
        "refused": contract.refused,
        "entries": [
            {"pointer": e.pointer, "types": list(e.types), "required": e.required, "nullable": e.nullable,
             "sensitive": e.sensitive, "prefill": filled[e.pointer].to_json()}
            for e in contract.entries
        ],
    }  # fmt: skip
