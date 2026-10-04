# SPDX-License-Identifier: Apache-2.0
"""A schedule's ticks while a production deployment's gate is off (engine 2b spec §2.5, §8.2): a tick is a durable
source, so admission records its request, queued; the dispatcher starts nothing while the gate is off, and starts it
once the gate is on. Waiting isn't failing."""

from sqlalchemy import text

from dewpoint.apps import schedules
from dewpoint.apps.dispatcher import dispatch, tick
from dewpoint.core.db import tenant_scope
from dewpoint.core.platform.service import PRODUCTION, record_environment
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import KEYS, TOKEN, current, published
from tests.apps.test_runs import FakeClient


async def test_a_tick_while_the_gate_is_off_is_queued_and_starts_once_it_is_on(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    async with owner_sessionmaker() as s, s.begin():
        await record_environment(s, environment=PRODUCTION, namespace="default")
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        created = await schedules.create(
            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
            timing={"cron": "0 9 * * *", "every_s": None, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
            mode="live", input={"token": TOKEN}, enabled=True,
        )  # fmt: skip
    async with dispatch_sessionmaker() as s, s.begin():
        outcome = await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=created.id,
                                        key=f"sched:{created.id}:2026-10-04T09:00:00Z")  # fmt: skip
    assert outcome == "queued"
    client = FakeClient()
    await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
    assert client.started == []  # the gate is off: it waits, queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update platform_settings set production_runs = true"))
    assert await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD) == {"started": 1}
    async with owner_sessionmaker() as s:
        status = (await s.execute(text("select status from run_requests"))).scalar_one()
    assert status == "started"
