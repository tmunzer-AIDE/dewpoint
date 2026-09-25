# SPDX-License-Identifier: Apache-2.0
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _set_scope(session: AsyncSession, tenant: str, user: str) -> None:
    await session.execute(
        text("select set_config('app.tenant_id', :t, true), set_config('app.user_id', :u, true)"),
        {"t": tenant, "u": user},
    )


async def tenant_scope(session: AsyncSession, tenant_id: uuid.UUID | None) -> None:
    """Tenant RLS context for this transaction. Always clears the user-discovery context.
    Call only after the authoritative membership/run check."""
    await _set_scope(session, str(tenant_id) if tenant_id else "", "")


async def user_scope(session: AsyncSession, user_id: uuid.UUID) -> None:
    """User-discovery RLS context (own memberships/tenants only). Always clears the tenant context."""
    await _set_scope(session, "", str(user_id))
