# SPDX-License-Identifier: Apache-2.0
from datetime import UTC, datetime, timedelta

from dewpoint.core.auth.sessions import create_session, elevate, load_session, revoke_all
from dewpoint.core.auth.users import create_user


async def _user(s):
    return await create_user(s, email="a@corp.test", password="violet-otter-canyon-42")


async def test_create_load_and_rotate(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await _user(s)
        sess, token = await create_session(
            s,
            user_id=u.id,
            state="mfa_pending",
            methods=["password"],
            settings=api_settings,
            ip="192.0.2.1",
            user_agent="t",
        )
        assert (await load_session(s, token, api_settings)).id == sess.id
        new_token = await elevate(s, sess, method="totp")
        assert new_token != token
        assert await load_session(s, token, api_settings) is None
        loaded = await load_session(s, new_token, api_settings)
        assert loaded.state == "active" and loaded.auth_methods == ["password", "totp"]


async def test_idle_and_absolute_expiry(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await _user(s)
        _, token = await create_session(
            s, user_id=u.id, state="active", methods=["password"], settings=api_settings, ip=None, user_agent=None
        )
        now = datetime.now(UTC)
        assert await load_session(s, token, api_settings, now=now + timedelta(minutes=31)) is None
        assert await load_session(s, token, api_settings, now=now + timedelta(hours=13)) is None


async def test_revoke_all_keeps_current(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        u = await _user(s)
        keep, t1 = await create_session(
            s, user_id=u.id, state="active", methods=[], settings=api_settings, ip=None, user_agent=None
        )
        _, t2 = await create_session(
            s, user_id=u.id, state="active", methods=[], settings=api_settings, ip=None, user_agent=None
        )
        await revoke_all(s, u.id, except_id=keep.id)
        assert await load_session(s, t1, api_settings) is not None
        assert await load_session(s, t2, api_settings) is None
