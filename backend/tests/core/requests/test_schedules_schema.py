# SPDX-License-Identifier: Apache-2.0
"""Schedules' table (engine 2b spec §8.2, §14): under forced row-level security, the API's and the dispatcher's within
their tenant. The API writes the wanted state and never deletes (a deletion is a tombstone); the dispatcher writes only
what its sync completed and what Temporal counts. The database keeps a schedule's shape: a cron or an interval, at least
60 s, a bounded catch-up, an input until it's a tombstone, and a synced generation never past its generation."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dewpoint.core.auth.users import create_user
from dewpoint.core.db import tenant_scope
from tests.apps.api.helpers import PW
from tests.support.workflows import seed_workflow

INSERT = text(
    "insert into schedules (id, tenant_id, workflow_id, cron, mode, input, created_by) "
    "values (:id, :t, :w, '0 9 * * *', 'live', '\\x01', :u)"
)


async def schedule(api: Any, owner: Any) -> tuple[uuid.UUID, uuid.UUID]:
    tenant, wf, _ = await seed_workflow(owner)
    async with owner() as s, s.begin():
        user = (await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW)).id
    schedule_id = uuid.uuid4()
    async with api() as s, s.begin():
        await tenant_scope(s, tenant)
        await s.execute(INSERT, {"id": schedule_id, "t": tenant, "w": wf, "u": user})
    return tenant, schedule_id


async def change(maker: Any, tenant: uuid.UUID, statement: str, schedule_id: uuid.UUID) -> None:
    async with maker() as s, s.begin():
        await tenant_scope(s, tenant)
        await s.execute(text(statement), {"i": schedule_id})


async def test_schedules_force_row_level_security(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        query = text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'schedules'")
        assert tuple((await s.execute(query)).one()) == (True, True)


async def test_a_schedule_is_seen_only_within_its_tenant(
    api_sessionmaker, dispatch_sessionmaker, owner_sessionmaker
) -> None:
    tenant, schedule_id = await schedule(api_sessionmaker, owner_sessionmaker)
    other, _ = await schedule(api_sessionmaker, owner_sessionmaker)
    for maker in (api_sessionmaker, dispatch_sessionmaker):
        for scope, seen in ((tenant, 1), (other, 0)):
            async with maker() as s, s.begin():
                await tenant_scope(s, scope)
                found = await s.execute(text("select count(*) from schedules where id = :i"), {"i": schedule_id})
                assert found.scalar_one() == seen


async def test_each_role_writes_only_its_part_and_none_deletes(
    api_sessionmaker, dispatch_sessionmaker, owner_sessionmaker
) -> None:
    tenant, schedule_id = await schedule(api_sessionmaker, owner_sessionmaker)
    await change(api_sessionmaker, tenant, "update schedules set enabled = false, generation = 2 where id = :i",
                 schedule_id)  # fmt: skip
    await change(dispatch_sessionmaker, tenant, "update schedules set synced_generation = 2, misses = 1 where id = :i",
                 schedule_id)  # fmt: skip
    for maker, statement in (
        (dispatch_sessionmaker, "update schedules set cron = '* * * * *' where id = :i"),
        (dispatch_sessionmaker, "update schedules set input = null where id = :i"),
        (api_sessionmaker, "update schedules set synced_generation = 1 where id = :i"),
        (api_sessionmaker, "delete from schedules where id = :i"),
        (dispatch_sessionmaker, "delete from schedules where id = :i"),
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            await change(maker, tenant, statement, schedule_id)


@pytest.mark.parametrize(
    "statement",
    [
        "update schedules set every_s = 3600 where id = :i",  # a cron and an interval
        "update schedules set cron = null where id = :i",  # neither
        "update schedules set cron = null, every_s = 59 where id = :i",
        "update schedules set catchup_window_s = 30 where id = :i",
        "update schedules set input = null where id = :i",  # cleared without a tombstone
        "update schedules set deleted_at = now() where id = :i",  # a tombstone keeping its input
        "update schedules set generation = 0 where id = :i",  # its synced generation (1, set first) past it
    ],
)
async def test_the_database_keeps_a_schedules_shape(api_sessionmaker, owner_sessionmaker, statement) -> None:
    tenant, schedule_id = await schedule(api_sessionmaker, owner_sessionmaker)
    if "generation = 0" in statement:
        await change(owner_sessionmaker, tenant, "update schedules set synced_generation = 1 where id = :i",
                     schedule_id)  # fmt: skip
    with pytest.raises(IntegrityError):
        await change(api_sessionmaker, tenant, statement, schedule_id)
