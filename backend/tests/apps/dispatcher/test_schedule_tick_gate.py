# SPDX-License-Identifier: Apache-2.0
"""A schedule's ticks while a production deployment's gate is off (engine 2b spec §2.5, §8.2): a tick is a durable
source, so admission records its request, queued; the dispatcher starts nothing while the gate is off, and starts it
once the gate is on. Waiting isn't failing, and a queued request never expires: the catch-up window bounds what
admission takes, not what it has taken (the owner's ruling on the whole-branch review)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from dewpoint.apps import schedules
from dewpoint.apps.dispatcher import dispatch, tick
from dewpoint.core.db import tenant_scope
from dewpoint.core.platform.service import PRODUCTION, record_environment
from tests.apps.dispatcher.support import BUILD, workers
from tests.apps.test_admission import KEYS, TOKEN, current, published
from tests.apps.test_runs import FakeClient


async def test_a_tick_while_the_gate_is_off_is_queued_and_starts_once_it_is_on(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
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
    fired = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)  # three hours ago, inside its window then

    async def when_it_fired(s: Any) -> datetime:
        return fired + timedelta(seconds=5)

    monkeypatch.setattr(tick, "_database_now", when_it_fired)
    async with dispatch_sessionmaker() as s, s.begin():
        outcome = await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=created.id,
                                        key=tick.tick_key(str(created.id), fired)[0])  # fmt: skip
    assert outcome == "queued"
    monkeypatch.undo()  # now three hours past its window, queued: it waits, and starts once the gate is on
    client = FakeClient()
    await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
    assert client.started == []  # the gate is off: it waits, queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update platform_settings set production_runs = true"))
        await s.execute(text("insert into retention_sweeps (ended_at, succeeded, tenants, lag_s) "
                             "values (now(), true, 0, 0)"))  # retention healthy (§10.3)  # fmt: skip
    assert await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD) == {"started": 1}
    async with owner_sessionmaker() as s:
        status = (await s.execute(text("select status from run_requests"))).scalar_one()
    assert status == "started"
