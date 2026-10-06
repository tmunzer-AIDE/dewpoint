# SPDX-License-Identifier: Apache-2.0
"""A tenant's erasure (engine 2b spec §6.5; the 2b-4 outline's "Tenant erasure"), a platform admin's act (D11's identity
rule): on an active MFA session whose second factor was proven within the reauthentication window, recording that
admin's user id. Starting it needs the tenant's slug typed back. Irreversible once started (D3a): it can be stopped
(the tenant stays `erasing`, every refusal still applies) and retried, never reversed. The retention process carries
it on."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.db import tenant_scope
from dewpoint.core.erasure import service
from dewpoint.core.http import active_session, ensure_fresh_reauth, get_db, get_settings_dep, require_platform_admin
from dewpoint.core.models.erasure import Stage, TenantErasure, TenantErasureItem
from dewpoint.core.models.identity import AuthSession, User

router = APIRouter(prefix="/api/v1/admin/tenants", tags=["admin"])


class ErasureStartIn(BaseModel):
    confirm: str = Field(min_length=1, max_length=63)  # the tenant's slug, typed back


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def _shown(db: AsyncSession, record: TenantErasure) -> dict[str, object]:
    items: dict[str, dict[str, int]] = {}
    counted = await db.execute(
        select(TenantErasureItem.step, TenantErasureItem.state, func.count())
        .where(TenantErasureItem.tenant_id == record.tenant_id)
        .group_by(TenantErasureItem.step, TenantErasureItem.state)
    )
    for step, state, n in counted:
        items.setdefault(str(step), {})[state] = n
    return {
        "tenant_id": str(record.tenant_id), "step": record.step, "step_name": Stage(record.step).name.lower(),
        "requested_by": str(record.requested_by), "requested_at": _iso(record.requested_at),
        "stopped_at": _iso(record.stopped_at), "stopped_by": str(record.stopped_by) if record.stopped_by else None,
        "attempts": record.attempts, "failure": record.failure, "next_attempt_at": _iso(record.next_attempt_at),
        "paused_at": _iso(record.paused_at), "fenced_at": _iso(record.fenced_at),
        "latest_close": _iso(record.latest_close), "check_after": _iso(record.check_after),
        "boundary": record.boundary, "counts": record.counts, "items": items,
        "completed_at": _iso(record.completed_at), "reopened_at": _iso(record.reopened_at),
        "incidents": record.incidents,
    }  # fmt: skip


async def _record(db: AsyncSession, tenant_id: uuid.UUID) -> TenantErasure:
    await tenant_scope(db, tenant_id)  # its tenant's row (the final review's M3)
    found = (await db.execute(select(TenantErasure).where(TenantErasure.tenant_id == tenant_id)
                              .execution_options(populate_existing=True))).scalar_one_or_none()  # fmt: skip
    if found is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return found


@router.post("/{tenant_id}/erasure", status_code=202)
async def start(
    tenant_id: uuid.UUID,
    body: ErasureStartIn,
    admin: User = Depends(require_platform_admin),
    sess: AuthSession = Depends(active_session),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    ensure_fresh_reauth(sess, settings)  # irreversible: a second factor proven just now
    await tenant_scope(db, tenant_id)
    slug = (await db.execute(text("SELECT slug FROM tenants WHERE id = :t"), {"t": tenant_id})).scalar()
    if slug is None:
        raise HTTPException(404, detail={"error": "not_found"})
    if body.confirm != slug:
        raise HTTPException(422, detail={"error": "confirmation_mismatch"})
    try:
        await service.start(db, tenant_id=tenant_id, requested_by=admin.id)
    except service.TenantNotFoundError:
        raise HTTPException(404, detail={"error": "not_found"}) from None
    except service.NotErasableError:
        raise HTTPException(409, detail={"error": "not_erasable"}) from None
    return await _shown(db, await _record(db, tenant_id))


@router.post("/{tenant_id}/erasure/stop")
async def stop(
    tenant_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    try:
        record = await service.stop(db, tenant_id=tenant_id, stopped_by=admin.id)
    except service.NoErasureError:
        raise HTTPException(404, detail={"error": "not_found"}) from None
    await db.flush()
    return await _shown(db, record)


@router.post("/{tenant_id}/erasure/retry")
async def retry(
    tenant_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    try:
        record = await service.retry(db, tenant_id=tenant_id, actor_id=admin.id)
    except service.NoErasureError:
        raise HTTPException(404, detail={"error": "not_found"}) from None
    await db.flush()
    return await _shown(db, record)


@router.get("/{tenant_id}/erasure")
async def shown(
    tenant_id: uuid.UUID,
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    return await _shown(db, await _record(db, tenant_id))
