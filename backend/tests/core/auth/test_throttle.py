# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta

from dewpoint.core.auth import throttle


async def test_locks_after_max_failures_then_expires(owner_sessionmaker, api_settings) -> None:
    now = datetime.now(UTC)
    async with owner_sessionmaker() as s, s.begin():
        for _ in range(api_settings.login_max_failures):
            assert not await throttle.is_locked(s, "login_email", "a@x.test", now)
            await throttle.record_failure(s, "login_email", "a@x.test", api_settings, now)
        assert await throttle.is_locked(s, "login_email", "a@x.test", now)
        later = now + timedelta(minutes=api_settings.login_lockout_minutes + 1)
        assert not await throttle.is_locked(s, "login_email", "a@x.test", later)
        await throttle.reset(s, "login_email", "a@x.test")


async def test_ip_threshold_is_separate_and_higher(owner_sessionmaker, api_settings) -> None:
    assert api_settings.login_ip_max_failures > api_settings.login_max_failures
    async with owner_sessionmaker() as s, s.begin():
        for _ in range(api_settings.login_max_failures):
            await throttle.record_failure(s, "login_ip", "192.0.2.7", api_settings)
        assert not await throttle.is_locked(s, "login_ip", "192.0.2.7")
        for _ in range(api_settings.login_ip_max_failures - api_settings.login_max_failures):
            await throttle.record_failure(s, "login_ip", "192.0.2.7", api_settings)
        assert await throttle.is_locked(s, "login_ip", "192.0.2.7")
