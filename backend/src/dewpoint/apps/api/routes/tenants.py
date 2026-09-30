# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.deps import get_keyring
from dewpoint.core.audit.service import record
from dewpoint.core.authz.permissions import P
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import TenantContext, current_user, get_db, require, require_platform_admin
from dewpoint.core.models.identity import User
from dewpoint.core.models.tenancy import Tenant
from dewpoint.core.tenancy import service

router = APIRouter(prefix="/api/v1", tags=["tenants"])
SLUG = r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$"


class TenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG)


class TenantPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    require_passkey: bool | None = None


async def _tenant(db: AsyncSession, ctx: TenantContext) -> Tenant:
    t = await db.get(Tenant, ctx.tenant_id)
    if t is None:  # deleted after the membership check in this request
        raise HTTPException(404, detail={"error": "not_found"})
    return t


def _out(t: Tenant, role: str | None = None) -> dict[str, object]:
    d: dict[str, object] = {"id": str(t.id), "name": t.name, "slug": t.slug, "require_passkey": t.require_passkey}
    if role:
        d["role"] = role
    return d


@router.get("/tenants")
async def my_tenants(
    user: User = Depends(current_user), db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict[str, object]]:
    return [_out(t, r) for t, r in await service.list_user_tenants(db, user.id)]


@router.post("/tenants", status_code=201)
async def create(
    body: TenantIn,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db, scope="function"),
    keyring: Keyring = Depends(get_keyring),
) -> dict[str, object]:
    try:
        t = await service.create_tenant(db, keyring, name=body.name, slug=body.slug, owner_id=admin.id)
    except IntegrityError:
        raise HTTPException(409, detail={"error": "slug_taken"}) from None
    await record(
        db,
        tenant_id=t.id,
        actor_id=admin.id,
        action="tenant.create",
        target_type="tenant",
        target_id=str(t.id),
        details={"slug": t.slug},
    )
    return _out(t, "owner")


@router.get("/t/{tenant_id}")
async def get_tenant(
    ctx: TenantContext = Depends(require(P.TENANT_VIEW)), db: AsyncSession = Depends(get_db, scope="function")
) -> dict[str, object]:
    t = await _tenant(db, ctx)
    return _out(t, ctx.role)


@router.patch("/t/{tenant_id}")
async def patch_tenant(
    body: TenantPatch,
    ctx: TenantContext = Depends(require(P.TENANT_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    t = await _tenant(db, ctx)
    if body.name is not None:
        t.name = body.name
    if body.require_passkey is not None:
        t.require_passkey = body.require_passkey
    await db.flush()
    await record(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action="tenant.update",
        target_type="tenant",
        target_id=str(t.id),
        details=body.model_dump(exclude_none=True),
    )
    return _out(t, ctx.role)
