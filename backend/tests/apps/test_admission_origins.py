# SPDX-License-Identifier: Apache-2.0
"""Where a request came from, in plain ids on its row (editor 4e-1; the runs design §4.3): a re-run names the run it
repeats; a schedule's request, admitted or refused, names its schedule. A request by hand names neither."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import admission, schedules
from dewpoint.apps.dispatcher import tick
from dewpoint.core.db import tenant_scope
from tests.apps.test_admission import KEYS, TOKEN, admit, current, published

pytestmark = pytest.mark.usefixtures("development_deployment")


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


async def origins(owner: Any, request_id: uuid.UUID) -> tuple[Any, Any]:
    async with owner() as s:
        found = await s.execute(text("select rerun_of, trigger_id from run_requests where id = :i"), {"i": request_id})
        row = found.one()
        return row.rerun_of, row.trigger_id


async def test_a_rerun_names_the_run_it_repeats_and_a_request_by_hand_names_nothing(
    ready, owner_sessionmaker, api_sessionmaker
) -> None:
    ctx, wf = ready
    first = (await admit(api_sessionmaker, ctx, wf, key="first")).request
    again = (await admit(api_sessionmaker, ctx, wf, key="again", source="rerun",
                         rerun=admission.Rerun(of=first.id, input={"token": TOKEN}))).request  # fmt: skip
    assert await origins(owner_sessionmaker, first.id) == (None, None)
    assert await origins(owner_sessionmaker, again.id) == (first.id, None)


async def schedule(api: Any, ctx: Any, wf: uuid.UUID, *, enabled: bool = True) -> uuid.UUID:
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        created = await schedules.create(
            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
            timing={"cron": "0 9 * * *", "every_s": None, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
            mode="live", input={"token": TOKEN}, enabled=enabled,
        )  # fmt: skip
        return created.id


async def ticked(dispatch: Any, ctx: Any, schedule_id: uuid.UUID) -> uuid.UUID:
    key = tick.tick_key(str(schedule_id), datetime.now(UTC).replace(microsecond=0))[0]
    async with dispatch() as s, s.begin():
        await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id, key=key)
        found = await s.execute(text("select id from run_requests where idempotency_key = :k"), {"k": key})
        return found.scalar_one()


@pytest.mark.parametrize("enabled", [True, False], ids=["admitted", "refused"])
async def test_a_schedules_request_names_its_schedule_admitted_or_refused(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, enabled: bool
) -> None:
    ctx, wf = ready
    schedule_id = await schedule(api_sessionmaker, ctx, wf, enabled=enabled)
    request_id = await ticked(dispatch_sessionmaker, ctx, schedule_id)
    async with owner_sessionmaker() as s:
        status = (await s.execute(text("select status from run_requests where id = :i"), {"i": request_id})).scalar()
    assert status == ("queued" if enabled else "refused")
    assert await origins(owner_sessionmaker, request_id) == (None, schedule_id)
