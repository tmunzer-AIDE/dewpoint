# SPDX-License-Identifier: Apache-2.0
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.config import Settings
from dewpoint.core.models.identity import AuthSession

SESSION_COOKIE = "__Host-dewpoint_session"
TOUCH_EVERY = timedelta(seconds=60)


SameSite = Literal["lax", "strict", "none"]


class _CookieResponse(Protocol):
    """The cookie API of a Starlette response, without importing a web framework into core."""

    def set_cookie(
        self,
        key: str,
        value: str = ...,
        *,
        max_age: int | None = ...,
        path: str | None = ...,
        secure: bool = ...,
        httponly: bool = ...,
        samesite: SameSite | None = ...,
    ) -> None: ...

    def delete_cookie(
        self, key: str, *, path: str = ..., secure: bool = ..., httponly: bool = ..., samesite: SameSite | None = ...
    ) -> None: ...


def _hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


async def create_session(
    s: AsyncSession,
    *,
    user_id: uuid.UUID,
    state: str,
    methods: list[str],
    settings: Settings,
    ip: str | None,
    user_agent: str | None,
) -> tuple[AuthSession, str]:
    token, now = secrets.token_urlsafe(32), datetime.now(UTC)
    sess = AuthSession(
        token_hash=_hash(token),
        user_id=user_id,
        state=state,
        auth_methods=list(methods),
        csrf_token=secrets.token_urlsafe(32),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_absolute_hours),
        ip=ip,
        user_agent=(user_agent or "")[:400] or None,
    )
    s.add(sess)
    await s.flush()
    return sess, token


async def load_session(
    s: AsyncSession, token: str, settings: Settings, now: datetime | None = None
) -> AuthSession | None:
    now = now or datetime.now(UTC)
    sess = (await s.execute(select(AuthSession).where(AuthSession.token_hash == _hash(token)))).scalar_one_or_none()
    if sess is None or sess.revoked_at is not None or now >= sess.expires_at:
        return None
    if now - sess.last_seen_at > timedelta(minutes=settings.session_idle_minutes):
        return None
    if now - sess.last_seen_at > TOUCH_EVERY:
        sess.last_seen_at = now
    return sess


async def elevate(s: AsyncSession, sess: AuthSession, *, method: str, state: str = "active") -> str:
    token = secrets.token_urlsafe(32)
    sess.token_hash, sess.state = _hash(token), state
    sess.auth_methods = [*sess.auth_methods, method]
    sess.csrf_token = secrets.token_urlsafe(32)
    await s.flush()
    return token


async def revoke(s: AsyncSession, sess: AuthSession) -> None:
    sess.revoked_at = datetime.now(UTC)
    await s.flush()


async def revoke_all(s: AsyncSession, user_id: uuid.UUID, except_id: uuid.UUID | None = None) -> None:
    q = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if except_id:
        q = q.where(AuthSession.id != except_id)
    await s.execute(q.values(revoked_at=datetime.now(UTC)))


def csrf_valid(sess: AuthSession, header: str | None) -> bool:
    return bool(header) and hmac.compare_digest(sess.csrf_token, header or "")


def set_session_cookie(response: _CookieResponse, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )


def clear_session_cookie(response: _CookieResponse) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
