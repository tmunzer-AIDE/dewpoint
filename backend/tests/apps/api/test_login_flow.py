# SPDX-License-Identifier: Apache-2.0
from urllib.parse import parse_qs, urlparse

import pyotp
from sqlalchemy import text

from dewpoint.core.auth.users import create_user

PW = "violet-otter-canyon-42"


async def _seed(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="dana@corp.test", password=PW)


async def test_enroll_then_login_with_totp(client, owner_sessionmaker) -> None:
    await _seed(owner_sessionmaker)
    r = await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})
    assert r.status_code == 200 and r.json()["state"] == "enroll_required"
    csrf = r.json()["csrf_token"]
    uri = (await client.post("/api/v1/auth/mfa/totp/enroll", headers={"X-CSRF-Token": csrf})).json()["otpauth_uri"]
    secret = parse_qs(urlparse(uri).query)["secret"][0]
    r = await client.post(
        "/api/v1/auth/mfa/totp/confirm", json={"code": pyotp.TOTP(secret).now()}, headers={"X-CSRF-Token": csrf}
    )
    body = r.json()
    assert r.status_code == 200 and body["state"] == "active" and len(body["recovery_codes"]) == 10
    csrf = body["csrf_token"]
    assert (await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})).status_code == 204

    r = await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})
    assert r.json()["state"] == "mfa_pending"
    csrf = r.json()["csrf_token"]
    # the same TOTP code must not be accepted twice (replay)
    code = pyotp.TOTP(secret).now()
    r = await client.post("/api/v1/auth/mfa/totp", json={"code": code}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/mfa/recovery", json={"code": body["recovery_codes"][0]}, headers={"X-CSRF-Token": csrf}
    )
    assert r.status_code == 200 and r.json()["state"] == "active"
    me = (await client.get("/api/v1/auth/session")).json()
    assert me["user"]["email"] == "dana@corp.test" and me["auth_methods"] == ["password", "recovery"]


async def test_bad_password_is_generic_and_locks(client, owner_sessionmaker, api_settings) -> None:
    await _seed(owner_sessionmaker)
    for _ in range(api_settings.login_max_failures):
        r = await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": "nope-nope-nope"})
        assert r.status_code == 401 and r.json() == {"error": "invalid_credentials"}
    r = await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})
    assert r.status_code == 429 and r.json() == {"error": "locked"}
    # an unknown account gets the same generic answer; the shared client IP is still under its own higher limit
    r = await client.post("/api/v1/auth/login", json={"email": "ghost@corp.test", "password": PW})
    assert r.status_code == 401 and r.json() == {"error": "invalid_credentials"}


async def test_enrollment_confirm_is_throttled(client, owner_sessionmaker, api_settings) -> None:
    await _seed(owner_sessionmaker)
    csrf = (await client.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})).json()[
        "csrf_token"
    ]
    await client.post("/api/v1/auth/mfa/totp/enroll", headers={"X-CSRF-Token": csrf})
    for _ in range(api_settings.login_max_failures):
        r = await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": "000000"}, headers={"X-CSRF-Token": csrf})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": "000000"}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 429 and r.json() == {"error": "locked"}


async def test_password_change_revokes_other_sessions(app, owner_sessionmaker) -> None:
    import httpx

    await _seed(owner_sessionmaker)
    t = httpx.ASGITransport(app=app)
    h = {"X-Dewpoint-Client": "web"}
    async with (
        httpx.AsyncClient(transport=t, base_url="https://testserver", headers=h) as a,
        httpx.AsyncClient(transport=t, base_url="https://testserver", headers=h) as b,
    ):
        for c in (a, b):
            r = await c.post("/api/v1/auth/login", json={"email": "dana@corp.test", "password": PW})
            c.headers["X-CSRF-Token"] = r.json()["csrf_token"]
        async with owner_sessionmaker() as s, s.begin():  # both sessions completed MFA (not under test here)
            await s.execute(text("update sessions set state = 'active'"))
        r = await a.post(
            "/api/v1/auth/password", json={"current_password": PW, "new_password": "amber-heron-valley-77"}
        )
        assert r.status_code == 200 and "csrf_token" in r.json()
        assert (await b.get("/api/v1/auth/session")).status_code == 401
        assert (await a.get("/api/v1/auth/session")).status_code == 200
