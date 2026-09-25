# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.auth.sessions import SESSION_COOKIE, csrf_valid, load_session
from dewpoint.core.config import Settings
from dewpoint.core.models.identity import AuthSession, User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as s, s.begin():
        yield s


async def current_session(
    request: Request, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings_dep)
) -> AuthSession:
    token = request.cookies.get(SESSION_COOKIE)
    sess = await load_session(db, token, settings) if token else None
    if sess is None:
        raise HTTPException(401, detail={"error": "unauthenticated"})
    if request.method not in SAFE_METHODS and not csrf_valid(sess, request.headers.get("X-CSRF-Token")):
        raise HTTPException(403, detail={"error": "csrf"})
    return sess


async def active_session(sess: AuthSession = Depends(current_session)) -> AuthSession:
    if sess.state != "active":
        raise HTTPException(403, detail={"error": "mfa_required", "state": sess.state})
    return sess


async def current_user(sess: AuthSession = Depends(active_session), db: AsyncSession = Depends(get_db)) -> User:
    user = await db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, detail={"error": "unauthenticated"})
    return user
