# SPDX-License-Identifier: Apache-2.0
"""Migration 0073 on disposable databases, in a cluster of this module's own (editor 4e-1; the runs design §4.3): a
request's `rerun_of` and `trigger_id`, nullable with no default, null on every request before it; its downgrade drops
them. Its online step is interrupted, bounded and compared with a fresh database by `test_online.py`, as every online
migration's is."""

import asyncio
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.migrations.support import copy, downgrade, upgrade
from tests.migrations.test_0053 import _drop, _sql
from tests.probes.migration_locks import seed

ROOTS = 5
COLUMNS = ("SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_name = "
           "'run_requests' AND column_name IN ('rerun_of', 'trigger_id') ORDER BY column_name")  # fmt: skip


async def _rows(url: str, query: str) -> list[tuple[object, ...]]:
    c = await asyncpg.connect(url)
    try:
        return [tuple(r) for r in await c.fetch(query)]
    finally:
        await c.close()


@pytest.fixture(scope="module")
def cluster() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url().rsplit("/", 1)[0]


@pytest.fixture(scope="module")
def template(cluster: str) -> str:
    """A seeded database at 0072, as the deployments that run 0073 are."""
    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0072"'))
    upgrade(f"{cluster}/t0072", "0034")
    asyncio.run(seed(f"{cluster}/t0072", ROOTS))
    upgrade(f"{cluster}/t0072", "0072")
    return "t0072"


@pytest.fixture
async def db(cluster: str, template: str) -> AsyncIterator[str]:
    url = await copy(cluster, template)
    yield url
    await _drop(cluster, url.rsplit("/", 1)[1])


async def test_a_requests_origins_are_nullable_and_null_before_it(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0073")
    assert await _rows(db, COLUMNS) == [("rerun_of", "YES", None), ("trigger_id", "YES", None)]
    counted = await _rows(db, "SELECT count(*) > 0, count(rerun_of), count(trigger_id) FROM run_requests")
    assert counted == [(True, 0, 0)]


async def test_the_downgrade_drops_them(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0073")
    await _sql(db, "UPDATE run_requests SET rerun_of = gen_random_uuid(), trigger_id = gen_random_uuid()")
    await asyncio.to_thread(downgrade, db, "0072")
    assert await _rows(db, COLUMNS) == []
