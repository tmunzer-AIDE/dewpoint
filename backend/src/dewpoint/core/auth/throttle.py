# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.models.identity import AuthThrottle

WINDOW = timedelta(minutes=15)


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
