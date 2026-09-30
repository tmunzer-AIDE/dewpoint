# SPDX-License-Identifier: Apache-2.0
"""What a deployment is, recorded once (engine 2b spec §2.1): its environment and its Temporal namespace never change,
and a process configured for another namespace doesn't start."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dewpoint.core.platform.service import (
    DEVELOPMENT,
    PRODUCTION,
    EnvironmentMismatchError,
    EnvironmentNotRecordedError,
    check_namespace,
    record_environment,
    recorded,
)


async def test_an_environment_is_recorded_once_and_the_same_values_again_change_nothing(
    owner_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with owner_sessionmaker() as s, s.begin():
        assert await recorded(s) is None
        row = await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
        assert (row.environment, row.temporal_namespace, row.production_runs) == (DEVELOPMENT, "dewpoint-dev", False)
    async with owner_sessionmaker() as s, s.begin():
        again = await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
        assert (again.environment, again.temporal_namespace) == (DEVELOPMENT, "dewpoint-dev")


@pytest.mark.parametrize("values", [(PRODUCTION, "dewpoint-dev"), (DEVELOPMENT, "other")])
async def test_a_recorded_environment_never_changes(
    owner_sessionmaker: async_sessionmaker[AsyncSession], values: tuple[str, str]
) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
    with pytest.raises(EnvironmentMismatchError, match="Neither can change"):
        async with owner_sessionmaker() as s, s.begin():
            await record_environment(s, environment=values[0], namespace=values[1])


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE platform_settings SET environment = 'production'",
        "UPDATE platform_settings SET temporal_namespace = 'other'",
        "DELETE FROM platform_settings",
    ],
)
async def test_the_database_refuses_to_change_or_remove_the_record(
    owner_sessionmaker: async_sessionmaker[AsyncSession], statement: str
) -> None:
    """Even the table's owner, bypassing the service: a trigger enforces it. The gate is the one column that changes."""
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=DEVELOPMENT, namespace="dewpoint-dev")
    with pytest.raises(DBAPIError, match="recorded once|never removed"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(statement))
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("UPDATE platform_settings SET production_runs = true"))


async def test_an_unknown_environment_or_an_empty_namespace_is_refused(
    owner_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with owner_sessionmaker() as s, s.begin():
        with pytest.raises(ValueError, match="production` or `development"):
            await record_environment(s, environment="staging", namespace="n")
        with pytest.raises(ValueError, match="can't be empty"):
            await record_environment(s, environment=PRODUCTION, namespace="")


async def test_a_process_starts_only_with_the_recorded_namespace(
    owner_sessionmaker: async_sessionmaker[AsyncSession], worker_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    async with worker_sessionmaker() as s:
        with pytest.raises(EnvironmentNotRecordedError, match="platform init-environment"):
            await check_namespace(s, "default")
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    async with worker_sessionmaker() as s:
        assert (await check_namespace(s, "default")).environment == PRODUCTION
        with pytest.raises(EnvironmentMismatchError, match="configured for `other`"):
            await check_namespace(s, "other")


async def test_the_application_roles_read_the_record_and_never_write_it(
    owner_sessionmaker: async_sessionmaker[AsyncSession],
    api_sessionmaker: async_sessionmaker[AsyncSession],
    dispatch_sessionmaker: async_sessionmaker[AsyncSession],
    worker_sessionmaker: async_sessionmaker[AsyncSession],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    for sessionmaker in (api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, admin_sessionmaker):
        async with sessionmaker() as s:
            assert (await recorded(s)) is not None
        with pytest.raises(DBAPIError, match="permission denied"):
            async with sessionmaker() as s, s.begin():
                await s.execute(text("UPDATE platform_settings SET production_runs = true"))
