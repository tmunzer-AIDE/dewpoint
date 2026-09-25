# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.audit.service import record
from dewpoint.core.auth.users import Email
from dewpoint.core.authz.permissions import P
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.identity import User
from dewpoint.core.models.tenancy import Membership
from dewpoint.core.tenancy import service

router = APIRouter(prefix="/api/v1/t/{tenant_id}/members", tags=["members"])
RoleIn = Literal["owner", "admin", "editor", "operator", "viewer"]


class AddIn(BaseModel):
    email: Email
    role: RoleIn


class RoleChange(BaseModel):
    role: RoleIn


async def _audit(db: AsyncSession, ctx: TenantContext, action: str, user_id: uuid.UUID, role: str | None) -> None:
    await record(
        db,
        tenant_id=ctx.tenant_id,
        actor_id=ctx.user.id,
        action=action,
        target_type="user",
        target_id=str(user_id),
        details={"role": role} if role else None,
    )


def _map(exc: Exception) -> HTTPException:
    if isinstance(exc, service.LastOwnerError):
        return HTTPException(409, detail={"error": "last_owner"})
    if isinstance(exc, service.ActorNotAuthorizedError):
        return HTTPException(403, detail={"error": "forbidden"})
    if isinstance(exc, service.OwnerGrantError):
        return HTTPException(403, detail={"error": "owner_only"})
    return HTTPException(404, detail={"error": "user_not_found"})


@router.get("")
async def list_members(
    ctx: TenantContext = Depends(require(P.MEMBER_VIEW)), db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict[str, str]]:
    rows = await db.execute(
        select(Membership, User.email)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == ctx.tenant_id)
        .order_by(User.email)
    )
    return [{"user_id": str(m.user_id), "email": e, "role": m.role} for m, e in rows.all()]


@router.post("", status_code=201)
async def add(
    body: AddIn,
    ctx: TenantContext = Depends(require(P.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, str]:
    try:
        m = await service.add_member(db, ctx.tenant_id, body.email, body.role, ctx.user.id)
        await db.flush()
    except (service.ActorNotAuthorizedError, service.OwnerGrantError, service.UnknownUserError) as e:
        raise _map(e) from None
    except IntegrityError:
        raise HTTPException(409, detail={"error": "already_member"}) from None
    await _audit(db, ctx, "member.add", m.user_id, m.role)
    return {"user_id": str(m.user_id), "role": m.role}


@router.patch("/{user_id}")
async def change(
    user_id: uuid.UUID,
    body: RoleChange,
    ctx: TenantContext = Depends(require(P.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, str]:
    try:
        m = await service.change_role(db, ctx.tenant_id, user_id, body.role, ctx.user.id)
        await _audit(db, ctx, "member.role_change", user_id, m.role)
    except (
        service.ActorNotAuthorizedError,
        service.LastOwnerError,
        service.OwnerGrantError,
        service.UnknownUserError,
    ) as e:
        raise _map(e) from None
    return {"user_id": str(m.user_id), "role": m.role}


@router.delete("/{user_id}", status_code=204)
async def remove(
    user_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.MEMBER_MANAGE)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    try:
        await service.remove_member(db, ctx.tenant_id, user_id, ctx.user.id)
        await _audit(db, ctx, "member.remove", user_id, None)
    except (
        service.ActorNotAuthorizedError,
        service.LastOwnerError,
        service.OwnerGrantError,
        service.UnknownUserError,
    ) as e:
        raise _map(e) from None
    return Response(status_code=204)
