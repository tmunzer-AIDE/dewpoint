# SPDX-License-Identifier: Apache-2.0
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.users import get_user_by_email
from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope, user_scope
from dewpoint.core.models.keys import DataKey
from dewpoint.core.models.tenancy import Membership, Tenant


class LastOwnerError(Exception): ...


class OwnerGrantError(Exception): ...


class UnknownUserError(Exception): ...


class ActorNotAuthorizedError(Exception):
    """The acting user no longer holds a role allowing this change (re-checked under the tenant lock)."""


async def create_tenant(s: AsyncSession, keyring: Keyring, *, name: str, slug: str, owner_id: uuid.UUID) -> Tenant:
    """A tenant, its owner, and its data key: the payload codec only reads keys (engine 2b spec §6.3)."""
    tid = uuid.uuid4()
    await tenant_scope(s, tid)
    tenant = Tenant(id=tid, name=name, slug=slug)
    s.add(tenant)
    await s.flush()
    s.add(Membership(tenant_id=tid, user_id=owner_id, role="owner"))
    await s.flush()
    await keyring.ensure_key(s, tid)
    return tenant


class NotKeyAdminError(PermissionError):
    """`ensure_tenant_keys` in a session whose role can't list every tenant."""


async def ensure_tenant_keys(s: AsyncSession, keyring: Keyring) -> list[uuid.UUID]:
    """A data key for every tenant that has none — tenants created before 2b-1a — and which ones got one. It runs as
    the key admin (`dewpoint_admin`), which lists every tenant under row-level security (migration 0013), as Compose's
    migrate step does. Any other role sees only the tenants it's scoped to, so it's refused rather than find none."""
    if not (await s.execute(text("SELECT pg_has_role(current_user, 'dewpoint_admin', 'USAGE')"))).scalar_one():
        raise NotKeyAdminError("run it as a dewpoint_admin login: it lists every tenant under row-level security.")
    keyed = select(DataKey.id).where(DataKey.tenant_id == Tenant.id).exists()
    created = list((await s.execute(select(Tenant.id).where(~keyed).order_by(Tenant.id))).scalars())
    for tid in created:
        await tenant_scope(s, tid)
        await keyring.ensure_key(s, tid)
    return created


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


async def _lock_tenant(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Serialize every membership change of a tenant, so owner counts and actor roles can't race."""
    await s.execute(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())


async def _lock_and_authorize(s: AsyncSession, tenant_id: uuid.UUID, actor_id: uuid.UUID) -> str:
    """Take the tenant lock, then re-read the actor's role. require() authorized the request earlier, but the
    actor may have been removed or demoted before this lock was acquired; the returned role is authoritative."""
    await _lock_tenant(s, tenant_id)
    role = (
        await s.execute(
            select(Membership.role).where(Membership.tenant_id == tenant_id, Membership.user_id == actor_id)
        )
    ).scalar_one_or_none()
    if role is None or P.MEMBER_MANAGE not in ROLE_PERMISSIONS[role]:
        raise ActorNotAuthorizedError()
    return role


async def _membership(s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    m = (
        await s.execute(
            select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user_id).with_for_update()
        )
    ).scalar_one_or_none()
    if m is None:
        raise UnknownUserError()
    return m


async def add_member(s: AsyncSession, tenant_id: uuid.UUID, email: str, role: str, actor_id: uuid.UUID) -> Membership:
    actor_role = await _lock_and_authorize(s, tenant_id, actor_id)
    if role == "owner" and actor_role != "owner":
        raise OwnerGrantError()
    user = await get_user_by_email(s, email)
    if user is None:
        raise UnknownUserError()
    m = Membership(tenant_id=tenant_id, user_id=user.id, role=role)
    s.add(m)
    await s.flush()
    return m


async def change_role(
    s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, role: str, actor_id: uuid.UUID
) -> Membership:
    actor_role = await _lock_and_authorize(s, tenant_id, actor_id)
    m = await _membership(s, tenant_id, user_id)
    if "owner" in (role, m.role) and actor_role != "owner":
        raise OwnerGrantError()
    if m.role == "owner" and role != "owner" and await _owners(s, tenant_id) <= 1:
        raise LastOwnerError()
    m.role = role
    await s.flush()
    return m


async def remove_member(s: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    actor_role = await _lock_and_authorize(s, tenant_id, actor_id)
    m = await _membership(s, tenant_id, user_id)
    if m.role == "owner":
        if actor_role != "owner":
            raise OwnerGrantError()
        if await _owners(s, tenant_id) <= 1:
            raise LastOwnerError()
    await s.delete(m)
    await s.flush()
