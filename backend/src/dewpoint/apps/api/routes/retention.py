# SPDX-License-Identifier: Apache-2.0
"""A tenant's retention (engine 2b spec §10.1): read with `tenant.view`, set with `tenant.manage`, within the platform's
bounds."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.authz.permissions import P
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.retention import policy

router = APIRouter(prefix="/api/v1", tags=["retention"])


class RetentionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    runs_days: int = Field(ge=policy.MIN_RUNS_DAYS, le=policy.MAX_RUNS_DAYS)


@router.get("/t/{tenant_id}/retention")
async def get_retention(
    ctx: TenantContext = Depends(require(P.TENANT_VIEW)), db: AsyncSession = Depends(get_db, scope="function")
) -> dict[str, int]:
    return {"runs_days": await policy.runs_days(db, ctx.tenant_id)}


@router.put("/t/{tenant_id}/retention")
async def set_retention(
    body: RetentionIn,
    ctx: TenantContext = Depends(require(P.TENANT_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, int]:
    await policy.set_runs_days(db, ctx.tenant_id, body.runs_days, actor_id=ctx.user.id)
    return {"runs_days": body.runs_days}
