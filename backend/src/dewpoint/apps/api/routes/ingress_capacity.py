# SPDX-License-Identifier: Apache-2.0
"""The deployment's ingress capacity, a platform admin's (the owner's rulings on 2b-4b's M3 checkpoints 2 and 3; D11):
read on an active MFA session; changed with a second factor proven within the reauthentication window, audited in the
change's transaction with that admin's id, the attestation and the readiness it leaves. `dewpoint platform
set-ingress-capacity` asks this API; nothing else changes it. A value left out keeps what it was, `null` unsets it,
`unset` unsets all three; a production deployment whose runs are on keeps a whole capacity (409). Each answer shows the
deployment's outstanding-work limit it makes (the owner's ruling on the M3 checkpoint 4) and what's outstanding now."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.http import active_session, ensure_fresh_reauth, get_db, get_settings_dep, require_platform_admin
from dewpoint.core.models.identity import AuthSession, User
from dewpoint.core.models.platform import PlatformSettings
from dewpoint.core.platform import readiness
from dewpoint.core.platform.service import IngressCapacityRequiredError, set_ingress_capacity
from dewpoint.core.recovery import EVIDENCE_LIMIT

router = APIRouter(prefix="/api/v1/admin/platform", tags=["admin"])


class CapacityIn(BaseModel):
    """The values to change, each `null` to unset it, or `unset` for all three; and how the starts were measured."""

    starts_per_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    headroom: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    queue_wait_s: int | None = Field(default=None, gt=0)
    unset: bool = False
    attestation: str = Field(min_length=1, max_length=EVIDENCE_LIMIT)

    @model_validator(mode="after")
    def _one_way(self) -> "CapacityIn":
        if self.unset and self.model_fields_set & set(readiness.CAPACITY):
            raise ValueError("`unset` unsets all three: give no value with it")
        return self

    def change(self) -> dict[str, float | int | None]:
        if self.unset:
            return dict.fromkeys(readiness.CAPACITY)
        return {name: getattr(self, name) for name in readiness.CAPACITY if name in self.model_fields_set}


# The limit as admission computes it, and the budget's counts, read together
BUDGET = text("SELECT ingress_limit(), outstanding, active FROM ingress_budget WHERE id = 1")


async def _shown(db: AsyncSession, platform: Any) -> dict[str, Any]:
    limit, outstanding, active = (await db.execute(BUDGET)).one()
    return {"starts_per_s": platform.ingress_starts_per_s, "headroom": platform.ingress_headroom,
            "queue_wait_s": platform.ingress_queue_wait_s, "limit": limit, "outstanding": outstanding,
            "active_tenants": active, "problems": readiness.ingress_capacity(platform)}  # fmt: skip


async def _platform(db: AsyncSession) -> PlatformSettings:
    found = await db.get(PlatformSettings, 1, populate_existing=True)
    if found is None:
        raise HTTPException(409, detail={"error": "environment_not_recorded"})
    return found


@router.get("/ingress-capacity")
async def ingress_capacity(
    _: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db, scope="function")
) -> dict[str, Any]:
    """The capacity, the deployment's limit it makes and what's outstanding, and its values still unset (production
    readiness refuses then)."""
    return await _shown(db, await _platform(db))


@router.patch("/ingress-capacity")
async def change_ingress_capacity(
    body: CapacityIn,
    admin: User = Depends(require_platform_admin),
    sess: AuthSession = Depends(active_session),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    """The capacity changed, audited (`platform.ingress_capacity.set`) with the admin's id, the attestation, what it
    was and what it is, and its values still unset."""
    ensure_fresh_reauth(sess, settings)
    await _platform(db)
    try:
        await set_ingress_capacity(db, change=body.change(), attestation=body.attestation, actor_id=admin.id)
    except IngressCapacityRequiredError:
        raise HTTPException(409, detail={"error": "ingress_capacity_required"}) from None
    return await _shown(db, await _platform(db))
