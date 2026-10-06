# SPDX-License-Identifier: Apache-2.0
"""The longest maximum run duration ever configured (engine 2b spec §6.4's payload floor): the dispatcher, which sets
every run's deadline, records its setting as it starts; the longest recorded is what retiring a key waits on, and a
later, shorter setting never lowers it."""

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher.main import startup
from dewpoint.core.platform.service import longest_run_duration_days


@pytest.mark.usefixtures("development_deployment")
async def test_the_dispatcher_records_its_maximum_run_duration_and_the_longest_stays(
    dispatch_sessionmaker, admin_sessionmaker, owner_sessionmaker, api_settings
) -> None:
    async with admin_sessionmaker() as s:
        assert await longest_run_duration_days(s) is None  # nothing recorded: retirement can't reckon its floor
    for days in (45, 30, 45):
        await startup(dispatch_sessionmaker, api_settings.model_copy(update={"max_run_duration_days": days}))
    async with admin_sessionmaker() as s:
        assert await longest_run_duration_days(s) == 45
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select array_agg(days order by days) from run_duration_limits"))).scalar() == [
            30, 45,
        ]  # fmt: skip
