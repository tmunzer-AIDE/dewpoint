# SPDX-License-Identifier: Apache-2.0
"""What the dispatcher observes and records each cycle (engine 2b spec §2.7, §10.6; the owner's rulings on 2b-2): the
current build as Temporal reports it, recorded with when it was observed for admission's ABI check, and its own report,
health evidence that claims nothing about 2b-4's readiness gate."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.apps.dispatcher import observe


async def test_the_current_build_is_recorded_with_when_it_was_observed(dispatch_sessionmaker, api_sessionmaker) -> None:
    build = await observe.observe(dispatch_sessionmaker, "dewpoint-0.2.0+abi6")
    assert build is not None and (build.build_id, build.engine_abi) == ("dewpoint-0.2.0+abi6", 6)
    async with api_sessionmaker() as s:  # what admission reads
        row = (await s.execute(text("select build_id, engine_abi, observed_at > now() - interval '5 seconds' "
                                    "from current_build"))).one()  # fmt: skip
    assert tuple(row) == ("dewpoint-0.2.0+abi6", 6, True)


async def test_no_current_build_records_nothing_and_leaves_the_old_record_to_age(
    dispatch_sessionmaker, owner_sessionmaker
) -> None:
    await observe.observe(dispatch_sessionmaker, "dewpoint-0.2.0+abi6")
    assert await observe.observe(dispatch_sessionmaker, None) is None
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from current_build"))).scalar_one() == 1


async def test_the_dispatcher_reports_each_cycle_and_the_admin_reads_it(
    dispatch_sessionmaker, admin_sessionmaker, api_sessionmaker
) -> None:
    instance = uuid.uuid4()
    for dispatched in (1, 3):
        await observe.report(dispatch_sessionmaker, instance, "dewpoint-0.2.0+abi6", {"dispatched": dispatched})
    async with admin_sessionmaker() as s:  # 2b-4's readiness checks read it
        row = (await s.execute(text("select kind, details, reported_at >= started_at from dispatcher_reports"))).one()
    assert tuple(row) == ("dispatcher", {"dispatched": 3}, True)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s:
            await s.execute(text("select count(*) from dispatcher_reports"))
