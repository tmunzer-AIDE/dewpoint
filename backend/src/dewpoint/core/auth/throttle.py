# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.models.identity import AuthThrottle

WINDOW = timedelta(minutes=15)


async def consume(s: AsyncSession, kind: str, key: str, limit: int, now: datetime | None = None) -> bool:
    """Count one use of a rate-limited action in the current window. False once `limit` uses are exceeded."""
    now, key = now or datetime.now(UTC), key.lower()
    await s.execute(
        insert(AuthThrottle).values(kind=kind, key=key, failures=0, window_start=now).on_conflict_do_nothing()
    )
    row = await s.get(AuthThrottle, (kind, key), with_for_update=True)
    if row is None:  # inserted just above; only reachable if the row was deleted concurrently
        raise RuntimeError("auth_throttle row vanished")
    if now - row.window_start > WINDOW:
        row.failures, row.window_start = 0, now
    row.failures += 1
    await s.flush()
    return row.failures <= limit


async def purge_stale(s: AsyncSession, now: datetime | None = None, limit: int = 500) -> int:
    """Delete up to `limit` throttle rows whose window and lockout are both over."""
    now = now or datetime.now(UTC)
    doomed = (
        select(AuthThrottle.kind, AuthThrottle.key)
        .where(
            AuthThrottle.window_start < now - WINDOW,
            (AuthThrottle.locked_until.is_(None)) | (AuthThrottle.locked_until < now),
        )
        .limit(limit)
    )
    result = await s.execute(
        delete(AuthThrottle).where(tuple_(AuthThrottle.kind, AuthThrottle.key).in_(doomed.subquery().select()))
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def is_locked(s: AsyncSession, kind: str, key: str, now: datetime | None = None) -> bool:
    row = await s.get(AuthThrottle, (kind, key.lower()))
    return bool(row and row.locked_until and row.locked_until > (now or datetime.now(UTC)))


async def record_failure(s: AsyncSession, kind: str, key: str, settings: Settings, now: datetime | None = None) -> None:
    now, key = now or datetime.now(UTC), key.lower()
    await s.execute(
        insert(AuthThrottle).values(kind=kind, key=key, failures=0, window_start=now).on_conflict_do_nothing()
    )
    row = await s.get(AuthThrottle, (kind, key), with_for_update=True)
    if row is None:  # inserted just above; only reachable if the row was deleted concurrently
        raise RuntimeError("auth_throttle row vanished")
    if now - row.window_start > WINDOW:
        row.failures, row.window_start, row.locked_until = 0, now, None
    row.failures += 1
    limit = settings.login_ip_max_failures if kind == "login_ip" else settings.login_max_failures
    if row.failures >= limit:
        row.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
    await s.flush()


async def reset(s: AsyncSession, kind: str, key: str) -> None:
    await s.execute(delete(AuthThrottle).where(AuthThrottle.kind == kind, AuthThrottle.key == key.lower()))
