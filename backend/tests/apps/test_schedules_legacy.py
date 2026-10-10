# SPDX-License-Identifier: Apache-2.0
"""A schedule from before 2b-4a (the owner's review of D3f's B): nothing of its life before migration 0040 is
evidence for the accounting, so the migration records that span, from its creation to the migration, as unknown
(`before_migration`); the API never shows such a schedule's accounting as complete."""

import asyncio
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from dewpoint.apps import schedules
from dewpoint.core.auth.users import create_user
from dewpoint.core.db import make_engine
from tests.support.workflows import seed_workflow

BACKEND = Path(__file__).parents[2]


@pytest.fixture
def own_cluster() -> Iterator[str]:
    """A PostgreSQL cluster of this test's own (a url of its default database): 0053 runs once per cluster, and the
    session's database has run it."""
    with PostgresContainer("postgres:16-alpine", driver="asyncpg") as pg:
        yield pg.get_connection_url()


async def migrated(url: str, revision: str) -> None:
    env = {**os.environ, "DEWPOINT_DATABASE_URL": url, "DEWPOINT_EXPECTED_DATABASE": url.rsplit("/", 1)[1]}
    migrating = await asyncio.create_subprocess_exec("uv", "run", "alembic", "upgrade", revision, cwd=BACKEND,
                                                     env=env, stdout=asyncio.subprocess.DEVNULL,
                                                     stderr=asyncio.subprocess.DEVNULL)  # fmt: skip
    assert await migrating.wait() == 0


async def test_a_schedule_from_before_the_migration_shows_its_unproven_history_as_unknown(own_cluster: str) -> None:
    fresh = f"legacy_{uuid.uuid4().hex[:12]}"
    admin = create_async_engine(own_cluster, isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'CREATE DATABASE "{fresh}"'))
    url = own_cluster.rsplit("/", 1)[0] + f"/{fresh}"
    engine = make_engine(url)
    try:
        await migrated(url, "0039")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        tenant, workflow, _ = await seed_workflow(maker)
        schedule_id = uuid.uuid4()
        async with maker() as s, s.begin():
            user = (await create_user(s, email=f"{fresh}@corp.test", password="violet-otter-42")).id
            await s.execute(text("insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by, "
                                 "created_at) values (:i, :t, :w, 60, 'live', :c, :u, now() - interval '30 days')"),
                            {"i": schedule_id, "t": tenant, "w": workflow, "u": user, "c": b"x"})  # fmt: skip
        await migrated(url, "head")
        async with maker() as s:  # the database's owner: no tenant scope needed
            created = (await s.execute(text("select created_at from schedules where id = :i"),
                                       {"i": schedule_id})).scalar_one()  # fmt: skip
            recorded = (await s.execute(text("select recorded_at from schedule_incarnations where schedule_id = :i"),
                                        {"i": schedule_id})).scalar_one()  # fmt: skip
            accounted = await schedules.accounting(s, schedule_id)
    finally:
        await engine.dispose()
        async with admin.connect() as c:
            await c.execute(text(f'DROP DATABASE "{fresh}" WITH (FORCE)'))
        await admin.dispose()
    assert not accounted.complete
    assert accounted.uncounted == [
        {"from": created.isoformat(), "to": recorded.isoformat(), "class": "unknown", "reason": "before_migration"}
    ]
