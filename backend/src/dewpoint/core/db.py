# SPDX-License-Identifier: Apache-2.0
import uuid

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# SQLSTATE classes of a server that doesn't serve: connection exception, insufficient resources, operator intervention
UNAVAILABLE_STATES = ("08", "53", "57")


POOL_SIZE, MAX_OVERFLOW = 5, 10  # a process's connections, at most their sum (SQLAlchemy's own defaults, made explicit)


def make_engine(url: str, *, pool_size: int = POOL_SIZE, max_overflow: int = MAX_OVERFLOW) -> AsyncEngine:
    """An error's text never quotes a statement's parameters (a password's hash, a token, a tenant's data): it's
    shown wherever the error is (a CLI's message, a test's report). It opens at most `pool_size + max_overflow`
    connections."""
    return create_async_engine(url, pool_pre_ping=True, hide_parameters=True, pool_size=pool_size,
                               max_overflow=max_overflow)  # fmt: skip


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def unavailable(e: BaseException) -> bool:
    """Whether `e` says the database didn't answer, never that a statement was wrong: a connection the driver lost
    (SQLAlchemy invalidates it), a server refusing to serve (`UNAVAILABLE_STATES`), the network, or no pooled connection
    in time. A statement's own error (a syntax error, a constraint) is none of them."""
    if isinstance(e, DBAPIError):
        state = getattr(e.orig, "sqlstate", None)
        return e.connection_invalidated or (isinstance(state, str) and state[:2] in UNAVAILABLE_STATES)
    return isinstance(e, (OSError, PoolTimeoutError))


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
