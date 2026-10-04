# SPDX-License-Identifier: Apache-2.0
"""A schedule's tick admitted (engine 2b spec §8.2; the owner's rulings 9 and 10): in one transaction, as the dispatch
role, under the tick key `sched:<schedule_id>:<nominal time>`, so every retry of a tick finds what the first recorded.
No tick is silently dropped: an enabled schedule's is a request (queued, or refused as admission refuses a durable
source); a schedule disabled before its pause reached Temporal gives a `refused` request (`schedule_paused`), a deleted
one's tombstone one (`schedule_deleted`); an `erasing` tenant's is an audited skip, never a request."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import schedules
from dewpoint.apps.dispatcher import tick
from dewpoint.core.db import tenant_scope
from tests.apps.test_admission import KEYS, SCHEMA, TOKEN, count, current, published
from tests.apps.test_admission_csv import full_input
from tests.apps.test_workflow_ops import publish, save, update
from tests.support.graphs import G

pytestmark = pytest.mark.usefixtures("development_deployment")
KEY = "sched:{}:2026-10-04T09:00:00Z"


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        created = await schedules.create(
            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
            timing={"cron": "0 9 * * *", "every_s": None, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
            mode="simulate", input={"token": TOKEN, "site": "a"}, enabled=True,
        )  # fmt: skip
    return ctx, wf, created.id


async def ticked(dispatch: Any, ctx: Any, schedule_id: uuid.UUID) -> str:
    async with dispatch() as s, s.begin():
        return await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
                                     key=KEY.format(schedule_id))  # fmt: skip


async def requests(owner: Any) -> list[Any]:
    async with owner() as s:
        found = await s.execute(text("select * from run_requests order by queued_at"))
        return list(found.mappings())


async def changed(owner: Any, schedule_id: uuid.UUID, statement: str) -> None:
    async with owner() as s, s.begin():
        await s.execute(text(statement), {"i": schedule_id})


async def test_an_enabled_schedules_tick_is_a_request_under_its_key(
    ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, wf, schedule_id = ready
    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "queued"
    [r] = await requests(owner_sessionmaker)
    assert (r["source"], r["actor_id"], r["mode"], r["workflow_id"], r["idempotency_key"]) == (
        "schedule", None, "simulate", wf, KEY.format(schedule_id),
    )  # fmt: skip
    assert await full_input(dispatch_sessionmaker, ctx, r["id"]) == {"token": TOKEN, "site": "a"}
    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "queued"  # a retry: the same request
    assert await count(owner_sessionmaker, "run_requests") == 1


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("update schedules set enabled = false where id = :i", "schedule_paused"),
        ("update schedules set input = null, deleted_at = now() where id = :i", "schedule_deleted"),
    ],
)
async def test_a_paused_or_deleted_schedules_tick_is_a_refused_request(
    ready, owner_sessionmaker, dispatch_sessionmaker, statement, reason
) -> None:
    ctx, wf, schedule_id = ready
    await changed(owner_sessionmaker, schedule_id, statement)
    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == f"refused:{reason}"
    [r] = await requests(owner_sessionmaker)
    assert (r["status"], r["reason"], r["workflow_id"], r["envelope_id"]) == ("refused", reason, wf, None)
    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == f"refused:{reason}"
    assert await count(owner_sessionmaker, "run_requests") == 1


async def test_a_disabled_workflows_tick_is_refused_as_admission_refuses_it(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, wf, schedule_id = ready
    await update(api_sessionmaker, ctx, wf, enabled=False)
    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "refused:workflow_disabled"


async def test_an_input_the_active_version_no_longer_takes_is_a_refused_request(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, schedule_id = ready
    stricter = {**SCHEMA, "required": ["token", "region"],
                "properties": {**SCHEMA["properties"], "region": {"type": "string"}}}  # fmt: skip
    await save(api_sessionmaker, ctx, wf, G().node("a", "testkit.echo@1", {"value": 1}).data()
               | {"settings": {"input_schema": stricter}})  # fmt: skip
    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "refused:input_invalid"


async def test_an_erasing_tenants_tick_is_an_audited_skip(ready, owner_sessionmaker, dispatch_sessionmaker) -> None:
    ctx, _, schedule_id = ready
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": ctx.tenant_id})
    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "skipped:tenant_erasing"
    assert await count(owner_sessionmaker, "run_requests") == 0
    async with owner_sessionmaker() as s:
        details = (await s.execute(text("select details from audit_log where action = 'schedule.tick_skipped'"))
                   ).scalar_one()  # fmt: skip
    assert details == {"schedule_id": str(schedule_id), "tick": KEY.format(schedule_id), "reason": "tenant_erasing"}
