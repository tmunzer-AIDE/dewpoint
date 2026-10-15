# SPDX-License-Identifier: Apache-2.0
"""Simulating a workflow's draft (B8; the simulation design §6.3): `POST …/draft/simulations` admits a request frozen
on a snapshot of the draft at the revision `If-Match` names, under an `Idempotency-Key`, always `simulate` and
`manual`, and the dispatcher starts it as any run. `{input}` simulates the workflow; `{target}` a step alone with the
values it reads (S2). It needs `workflow.edit` and `run.start`; cancelling is the run's own route (`run.cancel`)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import admission
from dewpoint.apps.api.responses import DraftSnapshotOut, SimulationOut
from dewpoint.apps.api.routes.run_requests import (
    INVALID,
    UNAVAILABLE,
    get_keys,
    idempotency_key,
    key_unusable,
    not_past_cutoff,
    request_body,
)
from dewpoint.apps.api.routes.workflows import _revision
from dewpoint.core.authz.permissions import P
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.workflows import DraftSnapshot
from dewpoint.core.workflows.service import DraftConflictError

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
        status = 503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID | {admission.TARGET_INVALID} else 409
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
