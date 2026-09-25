# SPDX-License-Identifier: Apache-2.0
from types import SimpleNamespace

from dewpoint.core.auth import passkeys
from dewpoint.core.auth.users import create_user

CRED = {"id": "Y3JlZA", "rawId": "Y3JlZA", "type": "public-key", "response": {}}
PW = "violet-otter-canyon-42"


async def test_enroll_passkey_then_passwordless_login(client, owner_sessionmaker, monkeypatch) -> None:
    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **kw: SimpleNamespace(credential_id=b"cred", credential_public_key=b"pk", sign_count=0),
    )
    monkeypatch.setattr(passkeys, "verify_authentication_response", lambda **kw: SimpleNamespace(new_sign_count=1))
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="e@corp.test", password=PW)
    r = await client.post("/api/v1/auth/login", json={"email": "e@corp.test", "password": PW})
    csrf = r.json()["csrf_token"]
    o = (await client.post("/api/v1/auth/passkeys/register/options", headers={"X-CSRF-Token": csrf})).json()
    r = await client.post(
        "/api/v1/auth/passkeys/register/verify",
        headers={"X-CSRF-Token": csrf},
        json={"challenge_id": o["challenge_id"], "credential": CRED, "name": "laptop"},
    )
    assert r.status_code == 200 and r.json()["state"] == "active"
    await client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": r.json()["csrf_token"]})

    o = (await client.post("/api/v1/auth/passkeys/login/options")).json()
    r = await client.post(
        "/api/v1/auth/passkeys/login/verify", json={"challenge_id": o["challenge_id"], "credential": CRED}
    )
    assert r.status_code == 200 and r.json()["state"] == "active"
    me = (await client.get("/api/v1/auth/session")).json()
    assert me["auth_methods"] == ["passkey"]


async def test_passkey_stepup_is_throttled(client, owner_sessionmaker, api_settings, monkeypatch) -> None:
    def _reject(**kw):
        raise ValueError("bad signature")

    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **kw: SimpleNamespace(credential_id=b"cred", credential_public_key=b"pk", sign_count=0),
    )
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="f@corp.test", password=PW)
    csrf = (await client.post("/api/v1/auth/login", json={"email": "f@corp.test", "password": PW})).json()["csrf_token"]
    o = (await client.post("/api/v1/auth/passkeys/register/options", headers={"X-CSRF-Token": csrf})).json()
    csrf = (
        await client.post(
            "/api/v1/auth/passkeys/register/verify",
            headers={"X-CSRF-Token": csrf},
            json={"challenge_id": o["challenge_id"], "credential": CRED},
        )
    ).json()["csrf_token"]
    monkeypatch.setattr(passkeys, "verify_authentication_response", _reject)
    h = {"X-CSRF-Token": csrf}
    for _ in range(api_settings.login_max_failures):
        o = (await client.post("/api/v1/auth/passkeys/stepup/options", headers=h)).json()
        r = await client.post(
            "/api/v1/auth/passkeys/stepup/verify",
            headers=h,
            json={"challenge_id": o["challenge_id"], "credential": CRED},
        )
        assert r.status_code == 401 and r.json() == {"error": "passkey_failed"}
    o = (await client.post("/api/v1/auth/passkeys/stepup/options", headers=h)).json()
    r = await client.post(
        "/api/v1/auth/passkeys/stepup/verify", headers=h, json={"challenge_id": o["challenge_id"], "credential": CRED}
    )
    assert r.status_code == 429 and r.json() == {"error": "locked"}


async def test_list_own_passkeys_without_key_material(client, owner_sessionmaker, monkeypatch) -> None:
    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **kw: SimpleNamespace(credential_id=b"cred", credential_public_key=b"pk", sign_count=0),
    )
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="lister@corp.test", password=PW)
    csrf = (await client.post("/api/v1/auth/login", json={"email": "lister@corp.test", "password": PW})).json()[
        "csrf_token"
    ]
    assert (await client.get("/api/v1/auth/passkeys")).status_code == 403  # enrollment not finished
    o = (await client.post("/api/v1/auth/passkeys/register/options", headers={"X-CSRF-Token": csrf})).json()
    await client.post(
        "/api/v1/auth/passkeys/register/verify",
        headers={"X-CSRF-Token": csrf},
        json={"challenge_id": o["challenge_id"], "credential": CRED, "name": "laptop"},
    )
    listed = (await client.get("/api/v1/auth/passkeys")).json()
    assert [p["name"] for p in listed] == ["laptop"]
    assert set(listed[0]) == {"id", "name", "created_at", "last_used_at"}
