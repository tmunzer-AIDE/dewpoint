# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.responses import CsrfOut, SessionOut, StateOut
from dewpoint.core.audit.service import record
from dewpoint.core.auth import throttle, totp
from dewpoint.core.auth.passwords import hash_password, policy_violations, verify_password
from dewpoint.core.auth.sessions import (
    clear_session_cookie,
    create_session,
    revoke,
    revoke_all,
    rotate,
    set_session_cookie,
)
from dewpoint.core.auth.users import Email, get_user_by_email
from dewpoint.core.config import Settings
from dewpoint.core.http import current_session, current_user, get_db, get_settings_dep
from dewpoint.core.models.identity import AuthSession, User, WebauthnCredential

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
_DUMMY_HASH = hash_password("dewpoint-timing-equalizer")


class LoginIn(BaseModel):
    email: Email
    password: str = Field(min_length=1, max_length=1024)


class PasswordIn(BaseModel):
    current_password: str = Field(max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


async def initial_state(db: AsyncSession, user: User, settings: Settings) -> str:
    has_passkey = (
        await db.execute(select(WebauthnCredential.id).where(WebauthnCredential.user_id == user.id).limit(1))
    ).first() is not None
    if has_passkey or await totp.has_totp(db, user.id):
        return "mfa_pending"
    return "enroll_required" if settings.mfa_required else "active"


@router.post("/login", response_model=StateOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    if await throttle.is_locked(db, "login_email", body.email) or await throttle.is_locked(db, "login_ip", ip):
        raise HTTPException(429, detail={"error": "locked"})
    user = await get_user_by_email(db, body.email)
    ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password) and bool(user and user.is_active)
    if not ok or user is None:
        await throttle.record_failure(db, "login_email", body.email, settings)
        await throttle.record_failure(db, "login_ip", ip, settings)
        await record(
            db,
            tenant_id=None,
            actor_id=user.id if user else None,
            action="auth.login_failed",
            details={"email": body.email.lower(), "ip": ip},
        )
        await db.commit()  # persist failure counters and the audit entry despite the error response
        raise HTTPException(401, detail={"error": "invalid_credentials"})
    await throttle.reset(db, "login_email", body.email)
    state = await initial_state(db, user, settings)
    sess, token = await create_session(
        db,
        user_id=user.id,
        state=state,
        methods=["password"],
        settings=settings,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookie(response, token, settings)
    await record(db, tenant_id=None, actor_id=user.id, action="auth.login", details={"state": state, "ip": ip})
    return {"state": state, "csrf_token": sess.csrf_token}


@router.get("/session", response_model=SessionOut)
async def session_info(
    sess: AuthSession = Depends(current_session), db: AsyncSession = Depends(get_db, scope="function")
) -> dict[str, object]:
    user = await db.get(User, sess.user_id)
    if user is None:  # deleted while signed in
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return {
        "user": {"id": str(user.id), "email": user.email, "is_platform_admin": user.is_platform_admin},
        "state": sess.state,
        "auth_methods": sess.auth_methods,
        "csrf_token": sess.csrf_token,
    }


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> Response:
    await revoke(db, sess)
    clear_session_cookie(response)
    response.status_code = 204
    return response


@router.post("/password", response_model=CsrfOut)
async def change_password(
    body: PasswordIn,
    response: Response,
    user: User = Depends(current_user),
    sess: AuthSession = Depends(current_session),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    """Returns the rotated CSRF token so the client can make its next unsafe request."""
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(401, detail={"error": "invalid_credentials"})
    if v := policy_violations(body.new_password, user.email):
        raise HTTPException(422, detail={"error": "password_policy", "violations": v})
    from datetime import UTC, datetime

    user.password_hash, user.password_changed_at = hash_password(body.new_password), datetime.now(UTC)
    await revoke_all(db, user.id, except_id=sess.id)
    token = await rotate(db, sess)  # a password is not a second factor: rotate, don't elevate
    await record(db, tenant_id=None, actor_id=user.id, action="auth.password_changed")
    set_session_cookie(response, token, settings)
    return {"csrf_token": sess.csrf_token}
