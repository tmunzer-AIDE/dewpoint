# SPDX-License-Identifier: Apache-2.0
"""The deployment's namespace boundary (D3g), a platform admin's (the owner's ruling on the 2b-4b M4 design; D11):
listed on an active MFA session; recorded with a second factor proven within the reauthentication window, tied to the
D12 proof it rests on and to the server and namespace it holds for, audited in the recording's transaction with that
admin's id and the attestation. Only the deployment's recorded namespace, only a development deployment's for now:
production's waits for real-target qualification (409). `dewpoint platform record-namespace-boundary` asks this API
after checking the proof record and asking Temporal; nothing else records one."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.http import active_session, ensure_fresh_reauth, get_db, get_settings_dep, require_platform_admin
from dewpoint.core.models.identity import AuthSession, User
from dewpoint.core.platform.service import BoundaryRefusedError, record_namespace_boundary
from dewpoint.core.recovery import EVIDENCE_LIMIT

router = APIRouter(prefix="/api/v1/admin/platform", tags=["admin"])

SHA256 = r"^sha256:[0-9a-f]{64}$"
LISTED = text("select * from namespace_boundaries_listed()")


class BoundaryIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    namespace: str = Field(min_length=1, max_length=1000)
    namespace_id: str = Field(min_length=1, max_length=200)  # Temporal's id for the namespace
    server_build: str = Field(pattern=SHA256)  # the server binary's
    proof_digest: str = Field(pattern=SHA256)  # the D12 proof record's
    attestation: str = Field(min_length=1, max_length=EVIDENCE_LIMIT)


def _shown(row: Any) -> dict[str, Any]:
    shown = dict(row._mapping)
    for moment in ("verified_at", "lost_at"):
        shown[moment] = shown[moment].isoformat() if shown[moment] is not None else None
    shown["recorded_by"] = str(shown["recorded_by"]) if shown["recorded_by"] is not None else None
    return shown


@router.get("/namespace-boundaries")
async def namespace_boundaries(
    _: User = Depends(require_platform_admin), db: AsyncSession = Depends(get_db, scope="function")
) -> dict[str, Any]:
    """Every boundary recorded, newest first; the erasure's bound relies on the newest not lost."""
    return {"boundaries": [_shown(row) for row in (await db.execute(LISTED)).all()]}


@router.post("/namespace-boundaries", status_code=201)
async def record_boundary(
    body: BoundaryIn,
    admin: User = Depends(require_platform_admin),
    sess: AuthSession = Depends(active_session),
    settings: Settings = Depends(get_settings_dep),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, Any]:
    """The boundary recorded, audited (`platform.namespace_boundary.record`) with the admin's id and its evidence."""
    ensure_fresh_reauth(sess, settings)
    try:
        boundary_id = await record_namespace_boundary(db, evidence=body.model_dump(), actor_id=admin.id)
    except BoundaryRefusedError as e:
        status = 422 if e.code == "boundary_evidence_incomplete" else 409
        raise HTTPException(status, detail={"error": e.code}) from None
    [shown] = [_shown(row) for row in (await db.execute(LISTED)).all() if row.id == boundary_id]
    return shown
