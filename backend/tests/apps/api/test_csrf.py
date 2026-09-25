# SPDX-License-Identifier: Apache-2.0
import httpx
from fastapi import APIRouter, Depends

from dewpoint.core.auth.sessions import SESSION_COOKIE, create_session
from dewpoint.core.auth.users import create_user
from dewpoint.core.http import active_session


async def test_unsafe_request_requires_client_header_and_csrf(app, owner_sessionmaker, api_settings) -> None:
    router = APIRouter()

    @router.post("/api/v1/_probe")
    async def probe(_=Depends(active_session)) -> dict[str, bool]:
        return {"ok": True}

    app.include_router(router)
    async with owner_sessionmaker() as s, s.begin():
        u = await create_user(s, email="c@corp.test", password="violet-otter-canyon-42")
        sess, token = await create_session(
            s,
            user_id=u.id,
            state="active",
            methods=["password", "totp"],
            settings=api_settings,
            ip=None,
            user_agent=None,
        )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://testserver", cookies={SESSION_COOKIE: token}
    ) as c:
        assert (await c.post("/api/v1/_probe")).status_code == 403  # no client header
        h = {"X-Dewpoint-Client": "web"}
        assert (await c.post("/api/v1/_probe", headers=h)).status_code == 403  # no csrf
        h["X-CSRF-Token"] = sess.csrf_token
        r = await c.post("/api/v1/_probe", headers=h)
        assert r.status_code == 200 and r.json() == {"ok": True}
