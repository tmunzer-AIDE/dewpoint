# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.deps import get_keyring
from dewpoint.core.auth import throttle, totp
from dewpoint.core.auth.sessions import elevate, set_session_cookie
from dewpoint.core.config import Settings
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.http import current_session, ensure_fresh_reauth, get_db, get_settings_dep
from dewpoint.core.models.identity import AuthSession, User

router = APIRouter(prefix="/api/v1/auth/mfa", tags=["auth"])


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


async def _user(db: AsyncSession, sess: AuthSession) -> User:
    user = await db.get(User, sess.user_id)
    if user is None:  # deleted while signing in
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return user


def _require_state(sess: AuthSession, *states: str) -> None:
    if sess.state not in states:
        raise HTTPException(409, detail={"error": "wrong_state", "state": sess.state})


async def _complete(
    db: AsyncSession, sess: AuthSession, response: Response, settings: Settings, method: str
) -> dict[str, str]:
    token = await elevate(db, sess, method=method, state="active")
    set_session_cookie(response, token, settings)
    return {"state": "active", "csrf_token": sess.csrf_token}


async def _second_factor(
    kind: str,
    body: CodeIn,
    response: Response,
    sess: AuthSession,
    db: AsyncSession,
    keyring: Keyring,
    settings: Settings,
) -> dict[str, str]:
    _require_state(sess, "mfa_pending")
    key = str(sess.user_id)
    if await throttle.is_locked(db, "mfa_user", key):
        raise HTTPException(429, detail={"error": "locked"})
    user = await _user(db, sess)
    ok = (
        await totp.verify(db, keyring, user, body.code)
        if kind == "totp"
        else await totp.use_recovery_code(db, user, body.code)
    )
    if not ok:
        await throttle.record_failure(db, "mfa_user", key, settings)
        await db.commit()
        raise HTTPException(401, detail={"error": "invalid_code"})
    await throttle.reset(db, "mfa_user", key)
    return await _complete(db, sess, response, settings, kind)


@router.post("/totp")
async def mfa_totp(
    body: CodeIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    return await _second_factor("totp", body, response, sess, db, keyring, settings)


@router.post("/recovery")
async def mfa_recovery(
    body: CodeIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    return await _second_factor("recovery", body, response, sess, db, keyring, settings)


@router.post("/totp/enroll")
async def enroll(
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    """Stage a new TOTP secret. An existing confirmed factor stays in force until /totp/confirm succeeds."""
    _require_state(sess, "enroll_required", "active")
    ensure_fresh_reauth(sess, settings)
    return {"otpauth_uri": await totp.start_enrollment(db, keyring, await _user(db, sess), settings)}


@router.post("/totp/reauth")
async def reauth(
    body: CodeIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    """Prove the confirmed TOTP again from an active session (before changing factors)."""
    _require_state(sess, "active")
    key = str(sess.user_id)
    if await throttle.is_locked(db, "mfa_user", key):
        raise HTTPException(429, detail={"error": "locked"})
    if not await totp.verify(db, keyring, await _user(db, sess), body.code):
        await throttle.record_failure(db, "mfa_user", key, settings)
        await db.commit()
        raise HTTPException(401, detail={"error": "invalid_code"})
    await throttle.reset(db, "mfa_user", key)
    return await _complete(db, sess, response, settings, "totp")


@router.post("/totp/confirm")
async def confirm(
    body: CodeIn,
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db),
    keyring: Keyring = Depends(get_keyring),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    _require_state(sess, "enroll_required", "active")
    ensure_fresh_reauth(sess, settings)  # re-checked here: the pending secret outlives the reauth window
    key = str(sess.user_id)
    if await throttle.is_locked(db, "mfa_user", key):
        raise HTTPException(429, detail={"error": "locked"})
    codes = await totp.confirm_enrollment(db, keyring, await _user(db, sess), body.code)
    if codes is None:
        await throttle.record_failure(db, "mfa_user", key, settings)
        await db.commit()
        raise HTTPException(401, detail={"error": "invalid_code"})
    await throttle.reset(db, "mfa_user", key)
    out: dict[str, object] = {"recovery_codes": codes}
    out.update(await _complete(db, sess, response, settings, "totp"))
    return out
