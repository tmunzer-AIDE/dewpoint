# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.authz.permissions import P
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.audit import AuditEntry

router = APIRouter(prefix="/api/v1/t/{tenant_id}/audit", tags=["audit"])


@router.get("")
async def list_audit(
    before_seq: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(require(P.AUDIT_VIEW)),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, object]]:
    q = select(AuditEntry).where(AuditEntry.tenant_id == ctx.tenant_id).order_by(AuditEntry.seq.desc()).limit(limit)
    if before_seq:
        q = q.where(AuditEntry.seq < before_seq)
    return [
        {
            "seq": e.seq,
            "at": e.created_at.isoformat(),
            "actor_id": str(e.actor_id) if e.actor_id else None,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "details": e.details,
        }
        for e in (await db.execute(q)).scalars()
    ]
