# SPDX-License-Identifier: Apache-2.0
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.users import get_user_by_email
from dewpoint.core.db import tenant_scope, user_scope
from dewpoint.core.models.tenancy import Membership, Tenant


class LastOwnerError(Exception): ...


class OwnerGrantError(Exception): ...


class UnknownUserError(Exception): ...


async def create_tenant(s: AsyncSession, *, name: str, slug: str, owner_id: uuid.UUID) -> Tenant:
    tid = uuid.uuid4()
    await tenant_scope(s, tid)
    tenant = Tenant(id=tid, name=name, slug=slug)
    s.add(tenant)
    await s.flush()
    s.add(Membership(tenant_id=tid, user_id=owner_id, role="owner"))
    await s.flush()
    return tenant


async def list_user_tenants(s: AsyncSession, user_id: uuid.UUID) -> list[tuple[Tenant, str]]:
    await user_scope(s, user_id)
    rows = await s.execute(
        select(Tenant, Membership.role)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == user_id)
        .order_by(Tenant.name)
    )
    return [(t, r) for t, r in rows.all()]


async def _owners(s: AsyncSession, tenant_id: uuid.UUID) -> int:
    return int(
        (
            await s.execute(
                select(func.count())
                .select_from(Membership)
                .where(Membership.tenant_id == tenant_id, Membership.role == "owner")
            )
        ).scalar_one()
    )


async def add_member(s: AsyncSession, tenant_id: uuid.UUID, email: str, role: str, actor_role: str) -> Membership:
    if role == "owner" and actor_role != "owner":
        raise OwnerGrantError()
    await _lock_tenant(s, tenant_id)
    user = await get_user_by_email(s, email)
    if user is None:
        raise UnknownUserError()
    m = Membership(tenant_id=tenant_id, user_id=user.id, role=role)
    s.add(m)
    await s.flush()
    return m


async def _lock_tenant(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Serialize every membership change of a tenant, so owner counts can't race."""
    await s.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())


async def _membership(s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    await _lock_tenant(s, tenant_id)
    m = (
        await s.execute(
            select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if m is None:
        raise UnknownUserError()
    return m


async def change_role(
    s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, role: str, actor_role: str
) -> Membership:
    m = await _membership(s, tenant_id, user_id)
    if "owner" in (role, m.role) and actor_role != "owner":
        raise OwnerGrantError()
    if m.role == "owner" and role != "owner" and await _owners(s, tenant_id) <= 1:
        raise LastOwnerError()
    m.role = role
    await s.flush()
    return m


async def remove_member(s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, actor_role: str) -> None:
    m = await _membership(s, tenant_id, user_id)
    if m.role == "owner":
        if actor_role != "owner":
            raise OwnerGrantError()
        if await _owners(s, tenant_id) <= 1:
            raise LastOwnerError()
    await s.delete(m)
    await s.flush()
