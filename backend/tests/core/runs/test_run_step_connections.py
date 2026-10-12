# SPDX-License-Identifier: Apache-2.0
"""The connections each step attempt opened (B7; 4c-2a ruling 8): the tenant's alone, written by the worker, read by
the API, gone with their run."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from tests.support.connections import seed_step

INSERT = text(
    "insert into run_step_connections (tenant_id, run_id, step_id, iteration_key, attempt, connection_id, type, name, "
    "revision) values (:t, :r, :s, '', 1, :c, 'testkit', 'Lab', 1)"
)


async def _record(maker: Any, tenant: uuid.UUID, run: uuid.UUID, step: uuid.UUID) -> None:
    async with maker() as s, s.begin():
        await tenant_scope(s, tenant)
        await s.execute(INSERT, {"t": tenant, "r": run, "s": step, "c": uuid.uuid4()})


async def test_the_table_forces_row_level_security(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        flags = (
            await s.execute(
                text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'run_step_connections'")
            )
        ).one()
    assert tuple(flags) == (True, True)


async def test_rows_stay_in_their_tenant(owner_sessionmaker, worker_sessionmaker, api_sessionmaker) -> None:
    a, b = await seed_step(owner_sessionmaker, named=[None]), await seed_step(owner_sessionmaker, named=[None])
    await _record(worker_sessionmaker, a.tenant, a.run, a.step)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, b.tenant)
        assert (await s.execute(text("select count(*) from run_step_connections"))).scalar_one() == 0
        await tenant_scope(s, a.tenant)
        assert (await s.execute(text("select count(*) from run_step_connections"))).scalar_one() == 1
    with pytest.raises(DBAPIError, match="row-level security"):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, a.tenant)
            await s.execute(INSERT, {"t": b.tenant, "r": b.run, "s": b.step, "c": uuid.uuid4()})


async def test_the_api_reads_and_never_writes(owner_sessionmaker, api_sessionmaker) -> None:
    a = await seed_step(owner_sessionmaker, named=[None])
    with pytest.raises(DBAPIError, match="permission denied"):
        await _record(api_sessionmaker, a.tenant, a.run, a.step)


async def test_goes_with_its_run(owner_sessionmaker, worker_sessionmaker) -> None:
    a = await seed_step(owner_sessionmaker, named=[None])
    await _record(worker_sessionmaker, a.tenant, a.run, a.step)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("delete from runs where id = :r"), {"r": a.run})
        assert (await s.execute(text("select count(*) from run_step_connections"))).scalar_one() == 0
