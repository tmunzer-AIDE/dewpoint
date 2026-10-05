# SPDX-License-Identifier: Apache-2.0
"""Per-tenant budgets of a provider's quota scopes (plugins-3 D9, D10).

A request takes one token from every scope its connection names, all or none, each scope's row locked in key order
in one transaction, its refill computed from the database clock. A short wait happens inside the attempt; a longer one
fails `cooldown`: this attempt sent nothing. A provider's `Retry-After` blocks a scope for every run of the tenant,
extending an existing block, never shortening it, and at most an hour ahead."""

import asyncio
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.db import tenant_scope
from dewpoint.core.models.egress import RateBucket

MAX_BLOCK = timedelta(hours=1)


@dataclass(frozen=True)
class Scope:
    """A provider's quota scope as a connection type names it: a key that never holds a secret, and its budget."""

    key: str
    capacity: float
    refill_per_s: float


class CooldownError(Exception):
    """A scope has no token for this attempt within its wait: nothing was sent. `until` is when one is expected."""

    def __init__(self, until: datetime | None) -> None:
        super().__init__("The connection is cooling down: nothing was sent.")
        self.until = until


def _ordered(scopes: Sequence[Scope]) -> list[Scope]:
    return sorted({scope.key: scope for scope in scopes}.values(), key=lambda scope: scope.key)


async def _locked(s: AsyncSession, tenant_id: uuid.UUID, scope: Scope, now: datetime) -> RateBucket:
    await s.execute(
        insert(RateBucket)
        .values(
            tenant_id=tenant_id,
            scope=scope.key,
            capacity=scope.capacity,
            refill_per_s=scope.refill_per_s,
            tokens=scope.capacity,
            refilled_at=now,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "scope"])
    )
    found = await s.execute(
        select(RateBucket)
        .where(RateBucket.tenant_id == tenant_id, RateBucket.scope == scope.key)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return found.scalar_one()


async def _try(s: AsyncSession, tenant_id: uuid.UUID, scopes: Sequence[Scope]) -> tuple[float, datetime | None]:
    now = (await s.execute(select(func.now()))).scalar_one()
    planned: list[tuple[RateBucket, Scope, float]] = []
    wait, until = 0.0, None
    for scope in _ordered(scopes):
        row = await _locked(s, tenant_id, scope, now)
        if row.blocked_until is not None and row.blocked_until > now:
            if (row.blocked_until - now).total_seconds() > wait:
                wait, until = (row.blocked_until - now).total_seconds(), row.blocked_until
            continue
        elapsed = max(0.0, (now - row.refilled_at).total_seconds())
        available = min(scope.capacity, row.tokens + elapsed * scope.refill_per_s)
        if available < 1:
            needed = (1 - available) / scope.refill_per_s
            if needed > wait:
                wait, until = needed, now + timedelta(seconds=needed)
            continue
        planned.append((row, scope, available))
    if wait > 0:
        return wait, until
    for row, scope, available in planned:
        row.capacity, row.refill_per_s = scope.capacity, scope.refill_per_s
        row.tokens, row.refilled_at = available - 1, now
    await s.flush()
    return 0.0, None


async def take(s: AsyncSession, tenant_id: uuid.UUID, scopes: Sequence[Scope]) -> float:
    """Takes a token from every scope, or none: 0 when taken, else the seconds until one could be."""
    wait, _ = await _try(s, tenant_id, scopes)
    return wait


async def acquire(
    sessionmaker: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
    scopes: Sequence[Scope],
    *,
    max_wait_s: float,
    beat: Callable[[], None],
) -> None:
    """A token from every scope, waiting (with `beat` between waits) at most `max_wait_s` in all. Raises
    CooldownError, having sent nothing, when the wait would be longer."""
    waited = 0.0
    while True:
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            wait, until = await _try(s, tenant_id, scopes)
        if wait == 0:
            return
        if waited + wait > max_wait_s:
            raise CooldownError(until)
        beat()
        await asyncio.sleep(wait)
        waited += wait


async def block(s: AsyncSession, tenant_id: uuid.UUID, scopes: Sequence[Scope], until: datetime) -> None:
    """Blocks every scope until `until` (at most an hour ahead), extending an existing block, never shortening it."""
    now = (await s.execute(select(func.now()))).scalar_one()
    capped = min(until, now + MAX_BLOCK)
    for scope in _ordered(scopes):
        row = await _locked(s, tenant_id, scope, now)
        if row.blocked_until is None or row.blocked_until < capped:
            row.blocked_until = capped
    await s.flush()


async def current_cooldowns(s: AsyncSession, tenant_id: uuid.UUID, keys: Sequence[str]) -> dict[str, datetime]:
    """Each scope's current cooldown: a live value that can change, not a record of a failed attempt's deadline."""
    if not keys:
        return {}
    found = await s.execute(
        select(RateBucket.scope, RateBucket.blocked_until).where(
            RateBucket.tenant_id == tenant_id,
            RateBucket.scope.in_(list(keys)),
            RateBucket.blocked_until > func.now(),
        )
    )
    return {scope: until for scope, until in found.all() if until is not None}
