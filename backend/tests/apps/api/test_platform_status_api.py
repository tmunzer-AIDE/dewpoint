# SPDX-License-Identifier: Apache-2.0
"""The deployment's environment, for the UI's development banner (engine 2b spec §2.1; sub-project 4, B2)."""

import httpx
from sqlalchemy import text

from dewpoint.core.platform.service import PRODUCTION, record_environment
from tests.apps.api.helpers import session_client

STATUS = "/api/v1/platform/status"


async def test_says_nothing_is_recorded_until_it_is(app, owner_sessionmaker, api_settings) -> None:
    c, _ = await session_client(app, owner_sessionmaker, api_settings, None)
    async with c:
        r = await c.get(STATUS)
    assert r.status_code == 200
    assert r.json() == {"environment": None, "production_runs": False}


async def test_names_a_development_deployment(app, owner_sessionmaker, api_settings, development_deployment) -> None:
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        assert (await c.get(STATUS)).json() == {"environment": "development", "production_runs": False}


async def test_says_whether_production_runs_are_on(app, owner_sessionmaker, api_settings) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
        await s.execute(text("UPDATE platform_settings SET production_runs = true"))
    c, _ = await session_client(app, owner_sessionmaker, api_settings, None)
    async with c:
        body = (await c.get(STATUS)).json()
    assert body == {"environment": "production", "production_runs": True}  # never the namespace


async def test_answers_signed_in_sessions_only(app, owner_sessionmaker, api_settings) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://testserver") as anonymous:
        assert (await anonymous.get(STATUS)).status_code == 401
    c, _ = await session_client(app, owner_sessionmaker, api_settings, None)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("UPDATE sessions SET state = 'enroll_required'"))
    async with c:
        assert (await c.get(STATUS)).status_code == 403
