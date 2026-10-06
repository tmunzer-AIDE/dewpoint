# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.responses import PasskeyOptionsOut, PasskeyOut, StateOut
from dewpoint.core.audit.service import record
from dewpoint.core.auth import passkeys, throttle
from dewpoint.core.auth.sessions import create_session, elevate, rotate, set_session_cookie
from dewpoint.core.config import Settings
from dewpoint.core.http import active_session, current_session, ensure_fresh_reauth, get_db, get_settings_dep
from dewpoint.core.models.identity import AuthSession, User, WebauthnCredential

router = APIRouter(prefix="/api/v1/auth/passkeys", tags=["auth"])


class VerifyIn(BaseModel):
    challenge_id: uuid.UUID
    credential: dict[str, Any]
    name: str = Field(default="Passkey", max_length=100)


def _state(sess: AuthSession, *allowed: str) -> None:
    if sess.state not in allowed:
        raise HTTPException(409, detail={"error": "wrong_state", "state": sess.state})


async def _session_user(db: AsyncSession, sess: AuthSession) -> User:
    user = await db.get(User, sess.user_id)
    if user is None:  # deleted while signed in
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return user


def _busy() -> HTTPException:
    return HTTPException(429, detail={"error": "rate_limited"})


def _fail() -> HTTPException:
    return HTTPException(401, detail={"error": "passkey_failed"})


async def _elevated(db: AsyncSession, sess: AuthSession, response: Response, settings: Settings) -> dict[str, str]:
    token = await elevate(db, sess, method="passkey", state="active")
    set_session_cookie(response, token, settings)
    return {"state": "active", "csrf_token": sess.csrf_token}


@router.get("", response_model=list[PasskeyOut])
async def list_passkeys(
    sess: AuthSession = Depends(active_session), db: AsyncSession = Depends(get_db, scope="function")
) -> list[dict[str, Any]]:
    """The caller's own passkeys: names and dates only, never key material."""
    rows = await db.execute(
        select(WebauthnCredential)
        .where(WebauthnCredential.user_id == sess.user_id)
        .order_by(WebauthnCredential.created_at)
    )
    return [
        {
            "id": str(c.id),
            "name": c.name,
            "created_at": c.created_at.isoformat(),
            "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
        }
        for c in rows.scalars()
    ]


@router.post("/register/options", response_model=PasskeyOptionsOut)
async def register_options(
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    _state(sess, "enroll_required", "active")
    ensure_fresh_reauth(sess, settings)  # a stolen active session must not be able to plant a lasting factor
    user = await _session_user(db, sess)
    try:
        opts, cid = await passkeys.registration_options(db, user, settings)
    except passkeys.ChallengeCapacityError:
        raise _busy() from None
    return {"options": opts, "challenge_id": str(cid)}


@router.post("/register/verify", response_model=StateOut)
async def register_verify(
    body: VerifyIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    _state(sess, "enroll_required", "active")
    ensure_fresh_reauth(sess, settings)  # re-checked here: the challenge can outlive the reauth window
    user = await _session_user(db, sess)
    try:
        await passkeys.finish_registration(db, user, body.challenge_id, body.credential, body.name, settings)
    except passkeys.PasskeyError:
        raise _fail() from None
    await record(db, tenant_id=None, actor_id=user.id, action="auth.passkey_registered", details={"name": body.name})
    if sess.state == "enroll_required":
        return await _elevated(db, sess, response, settings)
    token = await rotate(db, sess)  # a factor was added: new session and CSRF tokens
    set_session_cookie(response, token, settings)
    return {"state": sess.state, "csrf_token": sess.csrf_token}


@router.post("/login/options", response_model=PasskeyOptionsOut)
async def login_options(
    request: Request,
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    """Anonymous: every call stores a challenge, so issuance is limited per IP and capped platform-wide."""
    ip = request.client.host if request.client else "unknown"
    await throttle.purge_stale(db)
    if not await throttle.consume(db, "challenge_ip", ip, settings.passkey_options_per_ip):
        raise HTTPException(429, detail={"error": "rate_limited"})
    try:
        opts, cid = await passkeys.authentication_options(db, settings, None)
    except passkeys.ChallengeCapacityError:
        raise _busy() from None
    return {"options": opts, "challenge_id": str(cid)}


@router.post("/login/verify", response_model=StateOut)
async def login_verify(
    body: VerifyIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    if await throttle.is_locked(db, "login_ip", ip):
        raise HTTPException(429, detail={"error": "locked"})
    try:
        user = await passkeys.finish_authentication(db, body.challenge_id, body.credential, settings)
    except passkeys.PasskeyError:
        await throttle.record_failure(db, "login_ip", ip, settings)
        await db.commit()
        raise _fail() from None
    sess, token = await create_session(
        db,
        user_id=user.id,
        state="active",
        methods=["passkey"],
        settings=settings,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        reauth=True,  # a user-verified passkey is a second factor
    )
    await record(db, tenant_id=None, actor_id=user.id, action="auth.login", details={"method": "passkey", "ip": ip})
    set_session_cookie(response, token, settings)
    return {"state": "active", "csrf_token": sess.csrf_token}


async def _factor_options(sess: AuthSession, db: AsyncSession, settings: Settings) -> dict[str, Any]:
    try:
        opts, cid = await passkeys.authentication_options(db, settings, sess.user_id)
    except passkeys.ChallengeCapacityError:
        raise _busy() from None
    return {"options": opts, "challenge_id": str(cid)}


async def _factor_verify(
    body: VerifyIn, response: Response, sess: AuthSession, db: AsyncSession, settings: Settings
) -> dict[str, str]:
    key = str(sess.user_id)  # same "mfa_user" budget as TOTP and recovery codes
    if await throttle.is_locked(db, "mfa_user", key):
        raise HTTPException(429, detail={"error": "locked"})
    try:
        await passkeys.finish_authentication(
            db, body.challenge_id, body.credential, settings, expected_user_id=sess.user_id
        )
    except passkeys.PasskeyError:
        await throttle.record_failure(db, "mfa_user", key, settings)
        await db.commit()
        raise _fail() from None
    await throttle.reset(db, "mfa_user", key)
    return await _elevated(db, sess, response, settings)


@router.post("/mfa/options", response_model=PasskeyOptionsOut)
async def mfa_options(
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    _state(sess, "mfa_pending")
    return await _factor_options(sess, db, settings)


@router.post("/mfa/verify", response_model=StateOut)
async def mfa_verify(
    body: VerifyIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    _state(sess, "mfa_pending")
    return await _factor_verify(body, response, sess, db, settings)


@router.post("/stepup/options", response_model=PasskeyOptionsOut)
async def stepup_options(
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, Any]:
    _state(sess, "active")
    return await _factor_options(sess, db, settings)


@router.post("/stepup/verify", response_model=StateOut)
async def stepup_verify(
    body: VerifyIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    _state(sess, "active")
    return await _factor_verify(body, response, sess, db, settings)
