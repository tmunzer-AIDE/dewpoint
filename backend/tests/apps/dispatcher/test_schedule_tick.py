# SPDX-License-Identifier: Apache-2.0
"""A schedule's tick admitted (engine 2b spec §8.2; the owner's rulings 9 and 10): in one transaction, as the dispatch
role, under the tick key `sched:<schedule_id>:<nominal time>`, so every retry of a tick finds what the first recorded.
No tick is silently dropped: an enabled schedule's is a request (queued, or refused as admission refuses a durable
source); a schedule disabled before its pause reached Temporal gives a `refused` request (`schedule_paused`), a deleted
one's tombstone one (`schedule_deleted`); an `erasing` tenant's is an audited skip, never a request."""

import asyncio
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


async def lock_waiters(owner: Any) -> int:
    async with owner() as s:
        query = text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'")
        return int((await s.execute(query)).scalar_one())


async def until_waiting(owner: Any) -> None:
    for _ in range(300):
        if await lock_waiters(owner):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("nothing waited on the schedule")


CHANGES = {
    "disable": ("schedule_paused", lambda s, ctx, schedule: schedules.update(
        s, KEYS, actor_id=ctx.user.id, schedule=schedule, changes={"enabled": False})),
    "delete": ("schedule_deleted", lambda s, ctx, schedule: schedules.delete(
        s, actor_id=ctx.user.id, schedule=schedule)),
}  # fmt: skip


@pytest.mark.parametrize("change", list(CHANGES))
async def test_a_change_holding_the_schedule_first_decides_the_tick(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, change
) -> None:
    """The owner's M3 review: a tick decides under the schedule's row lock, which a change holds until it commits. A
    disable or a delete that holds it first makes the tick wait, then record what it committed."""
    ctx, _, schedule_id = ready
    reason, apply = CHANGES[change]
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await apply(s, ctx, await schedules.found(s, schedule_id))
        pending = asyncio.create_task(ticked(dispatch_sessionmaker, ctx, schedule_id))
        await until_waiting(owner_sessionmaker)
    assert await pending == f"refused:{reason}"
    assert [(r["status"], r["reason"]) for r in await requests(owner_sessionmaker)] == [("refused", reason)]


@pytest.mark.parametrize("change", list(CHANGES))
async def test_a_tick_holding_the_schedule_first_commits_before_the_change(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch, change
) -> None:
    """A tick that holds the row first admits its request; the disable or the delete waits for it, so no request is
    ever admitted under a schedule state that a committed change had already replaced."""
    ctx, _, schedule_id = ready
    _, apply = CHANGES[change]
    started: list[asyncio.Task[Any]] = []

    async def changing() -> None:
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            await apply(s, ctx, await schedules.found(s, schedule_id))

    async def meanwhile() -> None:
        started.append(asyncio.create_task(changing()))
        await until_waiting(owner_sessionmaker)

    monkeypatch.setattr(tick, "_after_schedule_locked", meanwhile)
    assert await ticked(dispatch_sessionmaker, ctx, schedule_id) == "queued"
    await started[0]
    [r] = await requests(owner_sessionmaker)
    assert r["status"] == "queued"
    async with owner_sessionmaker() as s:
        changed_at = (await s.execute(text("select updated_at from schedules where id = :i"), {"i": schedule_id})
                      ).scalar_one()  # fmt: skip
    assert changed_at > r["queued_at"]  # the change committed after the tick's request


async def test_a_ticks_request_names_its_schedule_in_its_audit_entry(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    """The owner's M3 review: the `run.request` entry of a tick's request, queued or refused, names the schedule."""
    ctx, wf, schedule_id = ready
    await ticked(dispatch_sessionmaker, ctx, schedule_id)
    await changed(owner_sessionmaker, schedule_id, "update schedules set enabled = false where id = :i")
    async with dispatch_sessionmaker() as s, s.begin():
        await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
                              key=f"sched:{schedule_id}:2026-10-04T10:00:00Z")  # fmt: skip
    await changed(owner_sessionmaker, schedule_id, "update schedules set enabled = true where id = :i")
    await update(api_sessionmaker, ctx, wf, enabled=False)
    async with dispatch_sessionmaker() as s, s.begin():
        await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
                              key=f"sched:{schedule_id}:2026-10-04T11:00:00Z")  # fmt: skip
    async with owner_sessionmaker() as s:
        entries = (await s.execute(text("select details from audit_log where action = 'run.request' "
                                        "order by seq"))).scalars().all()  # fmt: skip
    assert [(e["status"], e.get("reason"), e["schedule_id"]) for e in entries] == [
        ("queued", None, str(schedule_id)),
        ("refused", "schedule_paused", str(schedule_id)),
        ("refused", "workflow_disabled", str(schedule_id)),
    ]


async def test_two_late_ticks_of_a_tombstone_both_record_their_outcome(
    ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's M3 review: a tick of a deleted schedule writes its row (it queues the tombstone again), so a tick
    takes the row exclusively before it decides. Under a shared lock, two late ticks of other nominal times would each
    hold it and wait to write: a deadlock that aborts one. Here the first holds the row while the second arrives."""
    ctx, _, schedule_id = ready
    await changed(owner_sessionmaker, schedule_id, "update schedules set input = null, deleted_at = now(), "
                                                   "generation = 2, synced_generation = 2 where id = :i")  # fmt: skip
    second: list[asyncio.Task[Any]] = []
    holding = asyncio.Event()

    async def at(hour: int) -> str:
        async with dispatch_sessionmaker() as s, s.begin():
            return await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
                                         key=f"sched:{schedule_id}:2026-10-04T{hour:02d}:00:00Z")  # fmt: skip

    async def meanwhile() -> None:
        if second:  # the second tick holds the row too: give the first time to try its write
            holding.set()
            await asyncio.sleep(0.3)
            return
        second.append(asyncio.create_task(at(10)))
        for _ in range(300):  # until the second holds the row too, or waits on it
            if holding.is_set() or await lock_waiters(owner_sessionmaker):
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the second tick neither held nor waited on the schedule")

    monkeypatch.setattr(tick, "_after_schedule_locked", meanwhile)
    assert await at(9) == "refused:schedule_deleted"
    assert await second[0] == "refused:schedule_deleted"
    assert [r["reason"] for r in await requests(owner_sessionmaker)] == ["schedule_deleted"] * 2
