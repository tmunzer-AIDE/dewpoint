# SPDX-License-Identifier: Apache-2.0
"""Starting runs (engine 2b spec §7.7): a request is admitted in the API's own transaction and the dispatcher starts
it, so the API has no Temporal client. Every start carries an `Idempotency-Key`: an exact retry returns the same
request, another body under the key is a 409. A refusal answers with its code (§9) and fixed messages that never quote
a value: 503 while the deployment can't start runs (or the tenant's key can't be read), 422 for an input, 409 for the
workflow's state. A cancel and a re-run name a request: its id is its run's, if it has one."""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import admission, cancels
from dewpoint.apps.forms import form_fields
from dewpoint.apps.inputs import INPUT_INVALID
from dewpoint.core.authz.permissions import P
from dewpoint.core.claims import service as claims
from dewpoint.core.claims.cipher import ClaimCipher
from dewpoint.core.claims.secret_index import SECRET_INDEX_LIMIT
from dewpoint.core.crypto.keys import KeySource, key_unreadable
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.requests import RunRequest
from dewpoint.core.models.runs import Run
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.engine.handles import NestingError, StoredClaim, resolve_value

router = APIRouter(prefix="/api/v1", tags=["runs"])
KEY_MAX = 255
UNAVAILABLE = {admission.PRODUCTION_RUNS_DISABLED, admission.ENVIRONMENT_NOT_RECORDED, admission.NO_CURRENT_BUILD}
INVALID = {INPUT_INVALID, SECRET_INDEX_LIMIT}
INPUT_NOT_RETAINED = "input_not_retained"


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["live", "simulate"] = "live"


class RerunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["live", "simulate"] | None = None  # the old request's when not given
    input: dict[str, Any] | None = None  # new input; else the original, rebuilt while it's retained


def key_unusable(e: Exception) -> HTTPException:
    """The tenant's key couldn't be read (`key_unreadable`): 503, the request recorded nothing. Anything else raises."""
    if not key_unreadable(e):
        raise e
    return HTTPException(503, detail={"error": "key_unusable"})


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
    db: AsyncSession, keys: KeySource, ctx: TenantContext, workflow_id: uuid.UUID, source: str, body: StartIn, key: str,
    rerun: admission.Rerun | None = None,
) -> RunRequest:  # fmt: skip
    try:
        admitted = await admission.admit_request(
            db, keys, tenant_id=ctx.tenant_id, workflow_id=workflow_id, source=source, actor_id=ctx.user.id,
            mode=body.mode, idempotency_key=key, input=body.input, rerun=rerun,
        )  # fmt: skip
    except admission.WorkflowNotFoundError:
        raise HTTPException(404, detail={"error": "not_found"}) from None
    except admission.IdempotencyConflictError:
        raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
    except admission.AdmissionRefusedError as e:
        status = 503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID else 409
        raise HTTPException(status, detail={"error": e.reason, "messages": e.messages}) from None
    except Exception as e:
        raise key_unusable(e) from None
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


@router.post("/t/{tenant_id}/runs/{request_id}/cancel")
async def cancel_run(
    request_id: uuid.UUID,
    response: Response,
    ctx: TenantContext = Depends(require(P.RUN_CANCEL)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """200, `cancelled`: it was queued. 202, `requested`: recorded, for the dispatcher to apply when its start resolves
    or to send to Temporal. 409 `run_ended`: nothing left to cancel."""
    try:
        happened = await cancels.cancel_request(
            db, tenant_id=ctx.tenant_id, request_id=request_id, actor_id=ctx.user.id
        )
    except cancels.RequestNotFoundError:
        raise HTTPException(404, detail={"error": "not_found"}) from None
    if happened == "ended":
        raise HTTPException(409, detail={"error": "run_ended"})
    request = await db.get(RunRequest, request_id)
    if request is None:
        raise HTTPException(404, detail={"error": "not_found"})
    response.status_code = 200 if happened == "cancelled" else 202
    return {"cancel": happened, "request": request_body(request)}


@router.post("/t/{tenant_id}/runs/{request_id}/rerun", status_code=202)
async def rerun(
    request_id: uuid.UUID,
    body: RerunIn | None = None,
    key: str = Depends(idempotency_key),
    ctx: TenantContext = Depends(require(P.RUN_START)),
    db: AsyncSession = Depends(get_db, scope="function"),
    keys: KeySource = Depends(get_keys),
) -> dict[str, object]:
    """A new admission (source `rerun`) on the workflow's active version, with new input, or else the old request's
    complete input, validated and claimed again under the new request: no old handle is reused. The key is checked
    first: an exact retry returns the request it admitted, whatever retention has removed since; another request under
    the key is a 409. 410 `input_not_retained` when the original input can't be rebuilt: a run from before 2b-2, a
    refused request, an envelope or a claim retention has removed. New input needs none of it."""
    given = body or RerunIn()
    old = await db.get(RunRequest, request_id)  # row-level security: the caller's tenant's only
    run = await db.get(Run, request_id) if old is None else None  # a run 2a started: no request, no envelope
    named = old if old is not None else run
    if named is None:
        raise HTTPException(404, detail={"error": "not_found"})
    workflow_id, mode = named.workflow_id, given.mode or named.mode
    again = admission.Rerun(request_id, given.input)
    try:
        existing = await admission.admitted_under(
            db, keys, tenant_id=ctx.tenant_id, idempotency_key=key, source="rerun", workflow_id=workflow_id,
            mode=mode, rerun=again,
        )  # fmt: skip
    except admission.IdempotencyConflictError:
        raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
    except Exception as e:
        raise key_unusable(e) from None
    if existing is not None:
        return request_body(existing)
    if given.input is not None:
        value = given.input
    elif old is None:
        raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
    else:
        value = await original_input(db, keys, ctx.tenant_id, old)
    start = StartIn(input=value, mode=mode)
    return request_body(await admit(db, keys, ctx, workflow_id, "rerun", start, key, rerun=again))


async def original_input(db: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, old: RunRequest) -> dict[str, Any]:
    """A request's complete input, held in memory only: its envelope read through its own reader and every handle in
    it resolved, as the request that owns the claims (§7.7)."""
    if old.envelope_id is None:  # refused: admission kept no envelope
        raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
    cipher = ClaimCipher(keys)

    async def fetch(claim_id: str) -> StoredClaim:
        stored = await claims.read_request_claim(db, cipher, tenant_id, request_id=old.id, claim_id=uuid.UUID(claim_id))
        return StoredClaim(stored.value, stored.sensitive_pointers)

    try:
        envelope = await claims.read_envelope(db, cipher, tenant_id, request_id=old.id)
        resolved = await resolve_value(envelope, fetch)
    except (claims.EnvelopeUnavailableError, claims.ClaimUnavailableError, NestingError):
        raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED}) from None
    except Exception as e:
        raise key_unusable(e) from None
    if not isinstance(resolved.value, dict):
        raise HTTPException(410, detail={"error": INPUT_NOT_RETAINED})
    return resolved.value
