# SPDX-License-Identifier: Apache-2.0
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.sessions import SESSION_COOKIE, csrf_valid, load_session, reauth_fresh
from dewpoint.core.authz.permissions import ROLE_PERMISSIONS, P
from dewpoint.core.config import Settings
from dewpoint.core.db import tenant_scope, user_scope
from dewpoint.core.models.identity import AuthSession, User
from dewpoint.core.models.tenancy import Membership, Tenant
from dewpoint.core.tenancy import lifecycle

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    """One transaction per request. Always declare it as Depends(get_db, scope="function"): the default
    "request" scope commits after the response is sent, so a client could read before its write commits and a
    failed commit would follow a success response. (Mixing scopes would also create two sessions.)"""
    async with request.app.state.sessionmaker() as s, s.begin():
        yield s


async def current_session(
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> AuthSession:
    token = request.cookies.get(SESSION_COOKIE)
    sess = await load_session(db, token, settings) if token else None
    if sess is None:
        raise HTTPException(401, detail={"error": "unauthenticated"})
    if request.method not in SAFE_METHODS and not csrf_valid(sess, request.headers.get("X-CSRF-Token")):
        raise HTTPException(403, detail={"error": "csrf"})
    return sess


async def active_session(sess: AuthSession = Depends(current_session)) -> AuthSession:
    if sess.state != "active":
        raise HTTPException(403, detail={"error": "mfa_required", "state": sess.state})
    return sess


async def current_user(
    sess: AuthSession = Depends(active_session), db: AsyncSession = Depends(get_db, scope="function")
) -> User:
    user = await db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return user


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    user: User
    role: str
    session: AuthSession


async def _after_require() -> None:
    """Runs once a write's request holds the tenant's lifecycle lock and saw it active. A no-op; the race tests pause
    here."""


def require(permission: P) -> Callable[..., Awaitable[TenantContext]]:
    """The caller's role in the tenant, checked for `permission`. A write (any non-safe method) takes the tenant's
    lifecycle lock, shared, in the request's transaction (`get_db`'s, which commits before the response) before it
    reads the tenant, and is refused unless the tenant is active (409 `tenant_erasing`): an erasure's step 1, which
    takes it exclusively, waits for the write to commit, or the write sees `erasing` (the 2b-4 outline's fencing)."""

    async def _dep(
        tenant_id: uuid.UUID,
        request: Request,
        user: User = Depends(current_user),
        sess: AuthSession = Depends(active_session),
        db: AsyncSession = Depends(get_db, scope="function"),
    ) -> TenantContext:
        writes = request.method not in SAFE_METHODS
        if writes:
            await lifecycle.hold_shared(db, tenant_id)
        await user_scope(db, user.id)  # authoritative lookup of the caller's own membership
        row = (
            await db.execute(
                select(Membership.role, Tenant.require_passkey, Tenant.status)
                .join(Tenant, Tenant.id == Membership.tenant_id)
                .where(Membership.tenant_id == tenant_id, Membership.user_id == user.id)
            )
        ).first()
        if row is None:
            raise HTTPException(404, detail={"error": "not_found"})
        role, require_passkey, status = row
        if require_passkey and "passkey" not in sess.auth_methods:
            raise HTTPException(403, detail={"error": "step_up_required"})
        if permission not in ROLE_PERMISSIONS[role]:
            raise HTTPException(403, detail={"error": "forbidden"})
        if writes and status != "active":
            raise HTTPException(409, detail={"error": "tenant_erasing"})
        await tenant_scope(db, tenant_id)  # clears user scope: no widening to the caller's other tenants
        if writes:
            await _after_require()
        return TenantContext(tenant_id=tenant_id, user=user, role=role, session=sess)

    return _dep


async def require_platform_admin(user: User = Depends(current_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(403, detail={"error": "forbidden"})
    return user


def ensure_fresh_reauth(sess: AuthSession, settings: Settings) -> None:
    """Adding or replacing a factor from an active session needs a recently proven second factor.
    A session still enrolling its first factor (enroll_required) has none to prove and is exempt."""
    if sess.state == "active" and not reauth_fresh(sess, settings):
        raise HTTPException(403, detail={"error": "reauth_required"})
