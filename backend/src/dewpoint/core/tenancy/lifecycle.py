# SPDX-License-Identifier: Apache-2.0
"""A tenant's lifecycle lock (engine 2b spec §6.5; the 2b-4 outline's "Fencing in-flight work"): a transaction-scoped
advisory lock every writer of tenant data takes shared, checking `active` in the same transaction as its write (one
whose effect is outside PostgreSQL holds that transaction open across the call), and the erasure takes exclusively to
mark the tenant `erasing` and to enter its fenced stage. So a write either commits before the change or sees it."""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

FENCED = "DPE01"  # the SQLSTATE of an insert refused by the erasure's fence (migration 0040)


class TenantNotActiveError(Exception):
    """The tenant isn't active (erasing, or erased): it takes no new write. The message is fixed."""


def key(tenant_id: uuid.UUID) -> str:
    return f"dewpoint:tenant:{tenant_id}"


async def hold_shared(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": key(tenant_id)})


async def hold_exclusive(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key(tenant_id)})


def calls_key(tenant_id: uuid.UUID) -> str:
    return f"dewpoint:tenant-calls:{tenant_id}"


async def hold_calls_exclusive(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    """The tenant's plugin-call lock, exclusively: an erasure's step 1 takes it before the lifecycle lock, so it waits
    for every plugin call in flight (`calls_allowed`)."""
    await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": calls_key(tenant_id)})


async def calls_allowed(s: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """The tenant's plugin-call lock, shared, then whether the tenant is `active`: a worker holds this transaction open
    from the check through a call's claim, its hook's requests outside PostgreSQL and its answer, so an erasure's step
    1 waits for a call in flight, and a call it finds queued is never run (the owner's review of 2b-4a v5). A lock of
    its own, not the lifecycle lock: a hook's own writes on other connections (a tenant's first rate budget, or key, as
    its answer is sealed) take the lifecycle lock shared in the fence's trigger, and would otherwise queue behind step
    1's exclusive request, which waits for the hook."""
    await s.execute(text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": calls_key(tenant_id)})
    return (await s.execute(text("select tenant_status(:t)"), {"t": tenant_id})).scalar() == "active"


async def is_active(s: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """The lock, shared, then whether the tenant is `active`, read after it: the caller's write must be in this
    transaction."""
    await hold_shared(s, tenant_id)
    return (await s.execute(text("select tenant_status(:t)"), {"t": tenant_id})).scalar() == "active"


async def require_active(s: AsyncSession, tenant_id: uuid.UUID) -> None:
    """The lock, shared, then the tenant's status read after it: raises TenantNotActiveError unless it's `active`.
    The caller's write must be in this transaction. The read goes through `tenant_status()`, a function, which sees
    any tenant's status whatever the role's scope."""
    if not await is_active(s, tenant_id):
        raise TenantNotActiveError("This tenant is being erased: it takes no change.")
