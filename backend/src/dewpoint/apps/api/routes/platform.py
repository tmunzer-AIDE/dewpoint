# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.http import active_session, get_db
from dewpoint.core.platform.service import recorded

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


@router.get("/status", dependencies=[Depends(active_session)])
async def platform_status(db: AsyncSession = Depends(get_db, scope="function")) -> dict[str, object]:
    """What this deployment is, for the UI's banner (engine 2b spec §2.1: a development deployment says so on every
    screen): its environment, or null before it's recorded, and whether production runs are on. Never the Temporal
    namespace or anything else about the infrastructure."""
    row = await recorded(db)
    return {
        "environment": row.environment if row is not None else None,
        "production_runs": bool(row.production_runs) if row is not None else False,
    }
