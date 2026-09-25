# SPDX-License-Identifier: Apache-2.0
"""Shared API test helpers."""

import uuid

import httpx
from sqlalchemy import text

from dewpoint.core.auth.sessions import SESSION_COOKIE, create_session
from dewpoint.core.auth.users import create_user

PW = "violet-otter-canyon-42"


async def session_client(
    app,
    owner_sessionmaker,
    api_settings,
    role: str | None,
    methods=("password", "totp"),
    require_passkey: bool = False,
    platform_admin: bool = False,
):
    tid = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        u = await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW, platform_admin=platform_admin)
        await s.execute(
            text("insert into tenants(id,name,slug,require_passkey) values (:t,'T',:slug,:rp)"),
            {"t": tid, "slug": tid.hex[:12], "rp": require_passkey},
        )
        if role:
            await s.execute(
                text("insert into memberships(tenant_id,user_id,role) values (:t,:u,:r)"),
                {"t": tid, "u": u.id, "r": role},
            )
        sess, token = await create_session(
            s, user_id=u.id, state="active", methods=list(methods), settings=api_settings, ip=None, user_agent=None
        )
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
        cookies={SESSION_COOKIE: token},
        headers={"X-Dewpoint-Client": "web", "X-CSRF-Token": sess.csrf_token},
    )
    return c, tid


async def member_client(app, owner_sessionmaker, api_settings, tenant_id: uuid.UUID, role: str):
    """Another signed-in member of an existing tenant. Returns (client, user_id)."""
    async with owner_sessionmaker() as s, s.begin():
        u = await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW)
        await s.execute(
            text("insert into memberships(tenant_id,user_id,role) values (:t,:u,:r)"),
            {"t": tenant_id, "u": u.id, "r": role},
        )
        sess, token = await create_session(
            s,
            user_id=u.id,
            state="active",
            methods=["password", "totp"],
            settings=api_settings,
            ip=None,
            user_agent=None,
        )
    c = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
        cookies={SESSION_COOKIE: token},
        headers={"X-Dewpoint-Client": "web", "X-CSRF-Token": sess.csrf_token},
    )
    return c, u.id
