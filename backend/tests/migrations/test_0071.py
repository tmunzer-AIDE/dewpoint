# SPDX-License-Identifier: Apache-2.0
"""Migration 0071 on disposable databases, in a cluster of this module's own (editor 4d-1a, B4b): `run_steps` takes
`skipped` and `not_started` and an `effect_preview`; an upgrade interrupted between its steps goes on from there; its
downgrade refuses while a row records either status or an effect."""

import asyncio
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.migrations.support import copy, downgrade, upgrade
from tests.migrations.test_0053 import _drop, _sql
from tests.probes.migration_locks import seed

ROOTS = 5
STEP = ("INSERT INTO run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, effect_preview) "
        "SELECT tenant_id, id, gen_random_uuid(), '', 1, 'k', $1, $2::jsonb FROM runs LIMIT 1")  # fmt: skip


async def _rows(url: str, query: str, *args: object) -> list[tuple[object, ...]]:
    c = await asyncpg.connect(url)
    try:
        return [tuple(r) for r in await c.fetch(query, *args)]
    finally:
        await c.close()


async def _step(url: str, status: str, effect: str | None = None) -> None:
    c = await asyncpg.connect(url)
    try:
        await c.execute(STEP, status, effect)
    finally:
        await c.close()


@pytest.fixture(scope="module")
def cluster() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url().rsplit("/", 1)[0]


@pytest.fixture(scope="module")
def template(cluster: str) -> str:
    """A seeded database at 0065, as the deployments that run 0071 are."""
    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0065"'))
    upgrade(f"{cluster}/t0065", "0034")
    asyncio.run(seed(f"{cluster}/t0065", ROOTS))
    upgrade(f"{cluster}/t0065", "0065")
    return "t0065"


@pytest.fixture
async def db(cluster: str, template: str) -> AsyncIterator[str]:
    url = await copy(cluster, template)
    yield url
    await _drop(cluster, url.rsplit("/", 1)[1])


async def test_run_steps_take_the_new_statuses_and_an_effect(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0071")
    await _step(db, "skipped")
    await _step(db, "not_started")
    await _step(db, "succeeded", '{"port": "true"}')
    with pytest.raises(asyncpg.CheckViolationError):
        await _step(db, "unknown")
    names = await _rows(db, "SELECT conname FROM pg_constraint WHERE conname LIKE 'run_steps_status%'")
    assert names == [("run_steps_status",)]  # the wider check took the old one's name


async def test_an_upgrade_interrupted_after_the_wider_check_goes_on(db: str) -> None:
    await _sql(db, "ALTER TABLE run_steps ADD COLUMN effect_preview jsonb",
               "ALTER TABLE run_steps ADD CONSTRAINT run_steps_status_0071 CHECK (status IN ('running', 'succeeded', "
               "'failed', 'cancelled', 'skipped', 'not_started')) NOT VALID")  # fmt: skip
    await asyncio.to_thread(upgrade, db, "0071")
    names = await _rows(db, "SELECT conname, convalidated FROM pg_constraint WHERE conname LIKE 'run_steps_status%'")
    assert names == [("run_steps_status", True)]
    await _step(db, "not_started")


async def test_the_downgrade_refuses_while_a_row_records_a_new_status_or_an_effect(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0071")
    for status, effect in (("skipped", None), ("succeeded", '{"port": "false"}')):
        await _step(db, status, effect)
        with pytest.raises(Exception, match="0071 refused"):
            await asyncio.to_thread(downgrade, db, "0065")
        await _sql(db, "DELETE FROM run_steps WHERE status = 'skipped' OR effect_preview IS NOT NULL")
    await asyncio.to_thread(downgrade, db, "0065")
    columns = await _rows(db, "SELECT 1 FROM information_schema.columns WHERE table_name = 'run_steps' "
                              "AND column_name = 'effect_preview'")  # fmt: skip
    assert columns == []
    with pytest.raises(asyncpg.CheckViolationError):  # the old check is back
        await _sql(db, "INSERT INTO run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status) "
                       "SELECT tenant_id, id, gen_random_uuid(), '', 1, 'k', 'skipped' FROM runs LIMIT 1")  # fmt: skip
