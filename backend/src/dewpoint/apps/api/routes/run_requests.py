# SPDX-License-Identifier: Apache-2.0
"""Starting runs (engine 2b spec §7.7): a request is admitted in the API's own transaction and the dispatcher starts
it, so the API has no Temporal client. Every start carries an `Idempotency-Key`: an exact retry returns the same
request, another body under the key is a 409. A refusal answers with its code (§9) and fixed messages that never quote
a value: 503 while the deployment can't start runs, 422 for an input, 409 for the workflow's state."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import admission
from dewpoint.apps.forms import form_fields
from dewpoint.apps.inputs import INPUT_INVALID
from dewpoint.core.authz.permissions import P
from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT
from dewpoint.core.crypto.keys import KeySource
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.workflows import Workflow, WorkflowVersion

router = APIRouter(prefix="/api/v1", tags=["runs"])
KEY_MAX = 255
UNAVAILABLE = {admission.PRODUCTION_RUNS_DISABLED, admission.ENVIRONMENT_NOT_RECORDED, admission.NO_CURRENT_BUILD}
INVALID = {INPUT_INVALID, SECRET_INDEX_LIMIT}


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["live", "simulate"] = "live"


def get_keys(request: Request) -> KeySource:
    return request.app.state.keys  # type: ignore[no-any-return]


def idempotency_key(key: str | None = Header(None, alias="Idempotency-Key")) -> str:
    if not key:
        raise HTTPException(428, detail={"error": "idempotency_key_required"})
    if len(key) > KEY_MAX:
        raise HTTPException(422, detail={"error": "invalid", "fields": ["Idempotency-Key"]})
    return key


def _when(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def request_body(r: RunRequest) -> dict[str, object]:
    """A request as the API shows it: its state and its frozen version, never its input."""
    return {
        "id": str(r.id),
        "workflow_id": str(r.workflow_id),
        "version_id": str(r.workflow_version_id) if r.workflow_version_id else None,
        "mode": r.mode,
        "source": r.source,
        "status": r.status,
        "reason": r.reason,
        "queued_at": _when(r.queued_at),
        "ended_at": _when(r.ended_at),
    }


async def admit(
    db: AsyncSession, keys: KeySource, ctx: TenantContext, workflow_id: uuid.UUID, source: str, body: StartIn, key: str
) -> RunRequest:
    try:
        admitted = await admission.admit_request(
            db, keys, tenant_id=ctx.tenant_id, workflow_id=workflow_id, source=source, actor_id=ctx.user.id,
            mode=body.mode, idempotency_key=key, input=body.input,
        )  # fmt: skip
    except admission.WorkflowNotFoundError:
        raise HTTPException(404, detail={"error": "not_found"}) from None
    except admission.IdempotencyConflictError:
        raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
    except admission.AdmissionRefusedError as e:
        status = 503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID else 409
        raise HTTPException(status, detail={"error": e.reason, "messages": e.messages}) from None
    return admitted.request


@router.post("/t/{tenant_id}/workflows/{workflow_id}/runs", status_code=202)
async def start_run(
    workflow_id: uuid.UUID,
    body: StartIn,
    key: str = Depends(idempotency_key),
    ctx: TenantContext = Depends(require(P.RUN_START)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    """202 with the request, queued for the dispatcher (or as an exact retry finds it now)."""
    return request_body(await admit(db, keys, ctx, workflow_id, "manual", body, key))


@router.get("/t/{tenant_id}/workflows/{workflow_id}/start-form")
async def start_form(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_START)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """The active version's input, as a form: its typed fields, sensitive ones masked. CSV starts come with 2b-3."""
    workflow = await db.get(Workflow, workflow_id)  # row-level security: the caller's tenant's only
    if workflow is None:
        raise HTTPException(404, detail={"error": "not_found"})
    if workflow.active_version_id is None:
        raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
    version = await db.get(WorkflowVersion, workflow.active_version_id)
    if version is None:
        raise HTTPException(409, detail={"error": admission.NOT_ACTIVE})
    return {
        "workflow_id": str(workflow.id),
        "version_id": str(version.id),
        "fields": form_fields(version.input_schema or {}),
        "csv": None,
    }
