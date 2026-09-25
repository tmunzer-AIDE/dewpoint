# SPDX-License-Identifier: Apache-2.0
"""Changing authentication factors: pending TOTP, fresh reauthentication, token rotation, challenge limits."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pyotp
from sqlalchemy import func, select, text

from dewpoint.core.auth import passkeys
from dewpoint.core.auth.users import create_user
from dewpoint.core.models.identity import WebauthnChallenge

PW = "violet-otter-canyon-42"
EMAIL = "fay@corp.test"
CRED = {"id": "Y3JlZA", "rawId": "Y3JlZA", "type": "public-key", "response": {}}


def _secret(uri: str) -> str:
    return parse_qs(urlparse(uri).query)["secret"][0]


def _code(secret: str, steps_ahead: int = 0) -> str:
    totp = pyotp.TOTP(secret)
    return totp.at(totp.timecode(__import__("datetime").datetime.now()) * 30 + 30 * steps_ahead)


async def _active_totp_user(client: httpx.AsyncClient, owner_sessionmaker) -> str:  # type: ignore[no-untyped-def]
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email=EMAIL, password=PW)
    r = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PW})
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    secret = _secret((await client.post("/api/v1/auth/mfa/totp/enroll")).json()["otpauth_uri"])
    r = await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": _code(secret)})
    assert r.status_code == 200 and r.json()["state"] == "active"
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    return secret


async def _age_reauth(owner_sessionmaker) -> None:  # type: ignore[no-untyped-def]
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update sessions set reauth_at = now() - interval '1 hour'"))


async def test_abandoned_totp_setup_keeps_existing_factor(client, owner_sessionmaker) -> None:
    old = await _active_totp_user(client, owner_sessionmaker)
    r = await client.post("/api/v1/auth/mfa/totp/enroll")  # fresh reauth right after confirming
    assert r.status_code == 200 and _secret(r.json()["otpauth_uri"]) != old
    await client.post("/api/v1/auth/logout")  # abandon the new setup

    r = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PW})
    assert r.json()["state"] == "mfa_pending"  # NOT enroll_required: the old factor is still in force
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    r = await client.post("/api/v1/auth/mfa/totp", json={"code": _code(old, 1)})
    assert r.status_code == 200 and r.json()["state"] == "active"


async def test_replacing_totp_requires_fresh_reauthentication(client, owner_sessionmaker) -> None:
    old = await _active_totp_user(client, owner_sessionmaker)
    await _age_reauth(owner_sessionmaker)
    r = await client.post("/api/v1/auth/mfa/totp/enroll")
    assert r.status_code == 403 and r.json() == {"error": "reauth_required"}

    r = await client.post("/api/v1/auth/mfa/totp/reauth", json={"code": _code(old, 1)})
    assert r.status_code == 200
    assert r.json()["csrf_token"] != client.headers["X-CSRF-Token"]
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    new = _secret((await client.post("/api/v1/auth/mfa/totp/enroll")).json()["otpauth_uri"])
    r = await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": _code(new)})
    assert r.status_code == 200
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    await client.post("/api/v1/auth/logout")

    r = await client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PW})
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert (await client.post("/api/v1/auth/mfa/totp", json={"code": _code(old, -1)})).status_code == 401
    assert (await client.post("/api/v1/auth/mfa/totp", json={"code": _code(new, 1)})).status_code == 200


async def test_expired_pending_setup_cannot_be_confirmed(client, owner_sessionmaker) -> None:
    await _active_totp_user(client, owner_sessionmaker)
    new = _secret((await client.post("/api/v1/auth/mfa/totp/enroll")).json()["otpauth_uri"])
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update user_mfa set totp_pending_expires_at = now() - interval '1 second'"))
    r = await client.post("/api/v1/auth/mfa/totp/confirm", json={"code": _code(new)})
    assert r.status_code == 401 and r.json() == {"error": "invalid_code"}


async def test_adding_passkey_when_active_needs_reauth_and_rotates_token(
    client, owner_sessionmaker, monkeypatch
) -> None:
    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **kw: SimpleNamespace(credential_id=b"cred", credential_public_key=b"pk", sign_count=0),
    )
    secret = await _active_totp_user(client, owner_sessionmaker)
    await _age_reauth(owner_sessionmaker)
    r = await client.post("/api/v1/auth/passkeys/register/options")
    assert r.status_code == 403 and r.json() == {"error": "reauth_required"}
    client.headers["X-CSRF-Token"] = (
        await client.post("/api/v1/auth/mfa/totp/reauth", json={"code": _code(secret, 1)})
    ).json()["csrf_token"]
    o = (await client.post("/api/v1/auth/passkeys/register/options")).json()
    old_cookie, old_csrf = client.cookies.get("__Host-dewpoint_session"), client.headers["X-CSRF-Token"]
    r = await client.post(
        "/api/v1/auth/passkeys/register/verify", json={"challenge_id": o["challenge_id"], "credential": CRED}
    )
    assert r.status_code == 200 and r.json()["csrf_token"] != old_csrf
    assert client.cookies.get("__Host-dewpoint_session") != old_cookie  # token rotated
    assert (await client.post("/api/v1/auth/logout")).status_code == 403  # stale CSRF rejected
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert (await client.post("/api/v1/auth/logout")).status_code == 204


async def test_password_change_returns_the_rotated_csrf_token(client, owner_sessionmaker) -> None:
    await _active_totp_user(client, owner_sessionmaker)
    old_csrf = client.headers["X-CSRF-Token"]
    r = await client.post(
        "/api/v1/auth/password", json={"current_password": PW, "new_password": "amber-heron-valley-77"}
    )
    assert r.status_code == 200 and r.json()["csrf_token"] != old_csrf
    assert (await client.post("/api/v1/auth/logout")).status_code == 403
    client.headers["X-CSRF-Token"] = r.json()["csrf_token"]
    assert (await client.post("/api/v1/auth/logout")).status_code == 204


async def test_anonymous_passkey_options_are_rate_limited(client, api_settings) -> None:
    for _ in range(api_settings.passkey_options_per_ip):
        assert (await client.post("/api/v1/auth/passkeys/login/options")).status_code == 200
    r = await client.post("/api/v1/auth/passkeys/login/options")
    assert r.status_code == 429 and r.json() == {"error": "rate_limited"}


async def test_issuing_challenges_purges_expired_ones(owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "insert into webauthn_challenges(challenge, purpose, expires_at) "
                "select 'x', 'authenticate', now() - interval '1 minute' from generate_series(1, 25)"
            )
        )
        await passkeys.authentication_options(s, api_settings, None)
        remaining = (await s.execute(select(func.count()).select_from(WebauthnChallenge))).scalar_one()
    assert remaining == 1


async def test_outstanding_challenges_are_capped(owner_sessionmaker, api_settings, monkeypatch) -> None:
    import pytest

    monkeypatch.setattr(api_settings, "webauthn_challenges_max", 3)
    async with owner_sessionmaker() as s, s.begin():
        for _ in range(3):
            await passkeys.authentication_options(s, api_settings, None)
        with pytest.raises(passkeys.ChallengeCapacityError):
            await passkeys.authentication_options(s, api_settings, None)
