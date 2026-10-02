# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps import workflow_ops
from dewpoint.core.authz.permissions import P
from dewpoint.core.config import Settings
from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from dewpoint.core.workflows import service
from dewpoint.engine.graph.model import GraphFormatError, parse_graph

router = APIRouter(prefix="/api/v1", tags=["workflows"])
EMPTY_DRAFT: dict[str, Any] = {"graph_format": 1, "nodes": [], "edges": []}


class CreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    draft: dict[str, Any] | None = None


class PatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None


class ActivateIn(BaseModel):
    version_id: uuid.UUID


def _revision(if_match: str | None) -> int:
    if if_match is None:
        raise HTTPException(428, detail={"error": "revision_required"})
    try:
        return int(if_match.strip().strip('"'))
    except ValueError:
        raise HTTPException(400, detail={"error": "bad_revision"}) from None


def _check_format(draft: Any) -> None:
    try:
        parse_graph(draft)
    except GraphFormatError as e:
        raise HTTPException(
            422, detail={"error": "invalid", "diagnostics": [d.to_json() for d in e.diagnostics]}
        ) from None


async def _get(db: AsyncSession, ctx: TenantContext, workflow_id: uuid.UUID, *, for_update: bool = False) -> Workflow:
    wf = await service.get_workflow(db, ctx.tenant_id, workflow_id, for_update=for_update)
    if wf is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return wf


async def _summary(db: AsyncSession, wf: Workflow) -> dict[str, object]:
    await db.refresh(wf)
    active = await service.get_version(db, wf.id, wf.active_version_id) if wf.active_version_id else None
    blocked = await service.blocked_by(db, active) if active else []
    return {
        "id": str(wf.id),
        "name": wf.name,
        "enabled": wf.enabled,
        "draft_revision": wf.draft_revision,
        "active_version_id": str(active.id) if active else None,
        "active_version_number": active.number if active else None,
        "executable": (not blocked) if active else None,
        "blocked_by": blocked,
        "created_at": wf.created_at.isoformat(),
        "updated_at": wf.updated_at.isoformat(),
    }


def _version_out(v: WorkflowVersion, active_id: uuid.UUID | None, blocked: list[str]) -> dict[str, object]:
    return {
        "id": str(v.id),
        "number": v.number,
        "published_at": v.published_at.isoformat(),
        "published_by": str(v.published_by) if v.published_by else None,
        "graph_hash": v.graph_hash,
        "version_hash": v.version_hash,
        "cel_profile": v.cel_profile,
        "node_refs": v.node_refs,
        "active": v.id == active_id,
        "executable": not blocked,
        "blocked_by": blocked,
    }


@router.get("/t/{tenant_id}/workflows")
async def list_workflows(
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)), db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict[str, object]]:
    return [await _summary(db, wf) for wf in await service.list_workflows(db, ctx.tenant_id)]


@router.post("/t/{tenant_id}/workflows", status_code=201)
async def create(
    body: CreateIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    draft = body.draft if body.draft is not None else EMPTY_DRAFT
    _check_format(draft)
    try:
        wf = await service.create_workflow(db, ctx, name=body.name, draft=draft)
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return {**await _summary(db, wf), "draft": wf.draft}


@router.get("/t/{tenant_id}/workflows/{workflow_id}")
async def get_one(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id)
    return {**await _summary(db, wf), "draft": wf.draft}


@router.put("/t/{tenant_id}/workflows/{workflow_id}/draft")
async def put_draft(
    workflow_id: uuid.UUID,
    draft: dict[str, Any] = Body(...),
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    expected = _revision(if_match)
    _check_format(draft)
    wf = await _get(db, ctx, workflow_id)
    try:
        revision = await service.save_draft(db, wf, expected_revision=expected, draft=draft)
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    return {"draft_revision": revision}


@router.patch("/t/{tenant_id}/workflows/{workflow_id}")
async def patch(
    workflow_id: uuid.UUID,
    body: PatchIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id, for_update=True)
    try:
        warnings = await workflow_ops.update(db, ctx, wf, name=body.name, enabled=body.enabled)
    except workflow_ops.NotActivatableError as e:
        diagnostics = [d.to_json() for d in e.errors]
        raise HTTPException(422, detail={"error": "not_enableable", "diagnostics": diagnostics}) from None
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return {**await _summary(db, wf), "warnings": [w.to_json() for w in warnings]}


@router.post("/t/{tenant_id}/workflows/{workflow_id}/validate")
async def validate_draft(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id)
    checked = await workflow_ops.check_draft(db, ctx.tenant_id, wf.draft, settings)
    result = checked.result
    expressions = result.expressions if result is not None else ()
    return {
        "draft_revision": wf.draft_revision,
        "valid": not any(d.severity == "error" for d in checked.diagnostics),
        "diagnostics": [d.to_json() for d in checked.diagnostics],
        # How each CEL value runs, for the editor (spec §5.10): "local" runs inline, "activity" as a separate step.
        "expressions": [{"node": r.node, "field": r.field, "mode": r.mode, "reason": r.reason} for r in expressions],
        # Which values read sensitive data, and what each declassified site reveals (engine 2b spec §4.1, §4.3).
        "taint": {
            "sites": [{"node": n, "field": f} for n, f in (result.tainted_sites if result is not None else ())],
            "declassified": [
                {"node": n, "field": f, "reveals": r} for n, f, r in (result.declassified if result is not None else ())
            ],
        },
    }


@router.post("/t/{tenant_id}/workflows/{workflow_id}/publish", status_code=201)
async def publish(
    workflow_id: uuid.UUID,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    expected = _revision(if_match)
    wf = await _get(db, ctx, workflow_id, for_update=True)
    try:
        out = await workflow_ops.publish(db, ctx, wf, expected_revision=expected, settings=settings)
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    if out.version is None:
        diagnostics = [d.to_json() for d in [*out.errors, *out.warnings]]
        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics})
    return {
        "version_id": str(out.version.id),
        "number": out.version.number,
        "warnings": [d.to_json() for d in out.warnings],
    }


@router.get("/t/{tenant_id}/workflows/{workflow_id}/versions")
async def versions(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    wf = await _get(db, ctx, workflow_id)
    return [
        _version_out(v, wf.active_version_id, await service.blocked_by(db, v))
        for v in await service.list_versions(db, wf.id)
    ]


@router.post("/t/{tenant_id}/workflows/{workflow_id}/activate")
async def activate(
    workflow_id: uuid.UUID,
    body: ActivateIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id, for_update=True)
    version = await service.get_version(db, wf.id, body.version_id)
    if version is None:
        raise HTTPException(404, detail={"error": "not_found"})
    try:
        warnings = await workflow_ops.activate(db, ctx, wf, version)
    except workflow_ops.NotActivatableError as e:
        diagnostics = [d.to_json() for d in e.errors]
        raise HTTPException(422, detail={"error": "not_activatable", "diagnostics": diagnostics}) from None
    return {"active_version_id": str(version.id), "number": version.number, "warnings": [w.to_json() for w in warnings]}
