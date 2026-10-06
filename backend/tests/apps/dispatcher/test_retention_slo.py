# SPDX-License-Identifier: Apache-2.0
"""Retention's SLO at dispatch (engine 2b spec §2.3, §10.3): a production deployment starts a run only while retention
is healthy, a successful sweep within the last 24 hours with a lag under 24 hours; otherwise the request waits, queued,
no attempt counted. A development deployment skips the check."""

from datetime import timedelta

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import dispatch
from tests.apps.dispatcher.support import begin, state

SWEEP = (
    "insert into retention_sweeps (started_at, ended_at, succeeded, tenants, lag_s) values "
    "(now() - cast(:ago as interval) - interval '1 minute', now() - cast(:ago as interval), :ok, 1, :lag)"
)
HOUR, DAY = timedelta(hours=1), timedelta(days=1)


@pytest.fixture
async def production(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("alter table platform_settings disable trigger user"))
        await s.execute(text("update platform_settings set environment = 'production', production_runs = true"))
        await s.execute(text("alter table platform_settings enable trigger user"))


@pytest.mark.usefixtures("development_deployment", "production")
@pytest.mark.parametrize(("sweeps", "starts"), [
    ([], False),  # never swept
    ([(DAY + HOUR, True, 0.0)], False),  # its last success is too old
    ([(HOUR, True, DAY.total_seconds())], False),  # it leaves data a day past its cutoff
    ([(HOUR, False, 0.0)], False),  # it failed
    ([(DAY + HOUR, True, 0.0), (HOUR, False, 0.0)], False),  # an old success and a recent failure
    ([(HOUR, True, 3600.0)], True),
    ([(HOUR, True, 0.0), (0.5 * HOUR, False, 0.0)], True),  # a recent success holds through a later failure
])  # fmt: skip
async def test_a_production_start_waits_while_retention_is_unhealthy(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, sweeps: list[tuple[timedelta, bool, float]],
    starts: bool,
) -> None:  # fmt: skip
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        for ago, ok, lag in sweeps:
            await s.execute(text(SWEEP), {"ago": ago, "ok": ok, "lag": lag})
    outcome = await begin(dispatch_sessionmaker, request, api_settings)
    if starts:
        assert isinstance(outcome, dispatch.Starting)
    else:
        assert outcome == dispatch.Waiting("retention_unhealthy")
        assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}


@pytest.mark.usefixtures("development_deployment")
async def test_a_development_deployment_starts_without_a_sweep(queued, dispatch_sessionmaker, api_settings) -> None:
    _, _, request = queued
    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
