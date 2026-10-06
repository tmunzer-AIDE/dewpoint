# SPDX-License-Identifier: Apache-2.0
import base64
import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from dewpoint.apps.api.main import create_app
from dewpoint.core.config import Settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.core.platform.service import DEVELOPMENT, record_environment

BACKEND = Path(__file__).resolve().parents[1]
TEST_ROLES = [
    "dewpoint_api",
    "dewpoint_ingress",
    "dewpoint_dispatch",
    "dewpoint_worker",
    "dewpoint_admin",
    "dewpoint_auditor",
]


@pytest.fixture(scope="session")
def pg_url() -> str:
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        env = {**os.environ, "DEWPOINT_DATABASE_URL": url}
        subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)
        yield url


@pytest.fixture(scope="session")
async def _test_users(pg_url: str) -> None:
    eng = make_engine(pg_url)
    async with eng.begin() as c:
        for role in TEST_ROLES:
            await c.execute(
                text(
                    f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='t_{role}') "
                    # group roles appear as migrations land
                    f"AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{role}') "
                    f"THEN CREATE ROLE t_{role} LOGIN PASSWORD 'pw' IN ROLE {role}; END IF; END $$"
                )
            )
    await eng.dispose()


def _url_for(pg_url: str, role: str) -> str:
    return f"postgresql+asyncpg://t_{role}:pw@{pg_url.split('@', 1)[1]}"


@pytest.fixture(scope="session")
async def owner_sessionmaker(pg_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(pg_url)
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(scope="session")
async def api_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(_url_for(pg_url, "dewpoint_api"))
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(scope="session")
async def dispatch_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(_url_for(pg_url, "dewpoint_dispatch"))
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(scope="session")
async def worker_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(_url_for(pg_url, "dewpoint_worker"))
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(scope="session")
async def admin_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(_url_for(pg_url, "dewpoint_admin"))
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(scope="session")
async def ingress_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(_url_for(pg_url, "dewpoint_ingress"))
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(scope="session")
async def auditor_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    eng = make_engine(_url_for(pg_url, "dewpoint_auditor"))
    yield make_sessionmaker(eng)
    await eng.dispose()


@pytest.fixture(autouse=True)
async def clean_db(owner_sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncIterator[None]:
    yield
    async with owner_sessionmaker() as s, s.begin():
        tables = (
            await s.execute(
                text(
                    "select string_agg(format('%I', tablename), ',') from pg_tables "
                    "where schemaname='public' and tablename <> 'alembic_version'"
                )
            )
        ).scalar_one()
        if tables:
            await s.execute(text("SET LOCAL session_replication_role = replica"))  # bypass audit triggers
            await s.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def api_settings(pg_url: str, _test_users: None) -> Settings:
    return Settings(
        database_url=_url_for(pg_url, "dewpoint_api"),
        kek_b64=base64.b64encode(b"k" * 32).decode(),
        public_origin="https://testserver",
        rp_id="testserver",
    )


@pytest.fixture
async def app(api_settings: Settings):  # type: ignore[no-untyped-def]
    application = create_app(api_settings)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app):  # type: ignore[no-untyped-def]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://testserver", headers={"X-Dewpoint-Client": "web"}
    ) as c:
        yield c


@pytest.fixture
async def development_deployment(owner_sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """A development deployment on the default namespace: runs are admitted with no gate (engine 2b spec §2.1). The
    record goes with the other rows after each test."""
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=DEVELOPMENT, namespace="default")
