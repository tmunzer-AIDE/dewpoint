# SPDX-License-Identifier: Apache-2.0
"""The schedule sync (engine 2b spec §8.2; the owner's rulings on the milestone-3 gate): the reconciler's leader keeps
each Temporal Schedule in step with its row. Each change is a describe (its conflict token), the row read, then one
token-bearing update holding the spec, the action, the pause state and the note `dewpoint generation <n>`. Temporal
discards a stale update without an error, so an OK answer proves nothing: a generation is marked synced only once a
fresh describe shows its marker and a transaction confirms that the row still has that generation and the writer still
holds the leadership; a marker absent or different leaves it queued. A deletion is recorded only once the schedule's
absence is seen a call deadline after it, and a tick that finds a tombstone queues it again."""

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.api.workflowservice.v1 import DescribeScheduleRequest, UpdateScheduleRequest
from temporalio.client import ScheduleActionStartWorkflow
from temporalio.service import RPCStatusCode
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import schedules
from dewpoint.apps.dispatcher import schedule_sync, tick
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import schedule_workflow_id
from tests.apps.test_admission import KEYS, TOKEN, current, published
from tests.apps.test_runs import rpc
from tests.apps.test_workflow_ops import update as update_workflow
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = pytest.mark.usefixtures("development_deployment")
TIMING = {"cron": "0 9 * * 1-5", "every_s": None, "offset_s": 0, "time_zone": "Europe/Paris", "catchup_window_s": 600}


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


class Leading:
    def __init__(self, value: bool = True) -> None:
        self.value = value

    async def leading(self) -> bool:
        return self.value


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        created = await schedules.create(s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
                                         timing=TIMING, mode="live", input={"token": TOKEN}, enabled=True)  # fmt: skip
    return ctx, wf, created.id


async def sync(server: Any, dispatch: Any, ctx: Any, schedule_id: uuid.UUID, leader: Any = None) -> str:
    return await schedule_sync.sync_one(dispatch, server.client, leader or Leading(), ctx.tenant_id, schedule_id)


async def stored(owner: Any, schedule_id: uuid.UUID) -> Any:
    async with owner() as s:
        return (await s.execute(text("select * from schedules where id = :i"), {"i": schedule_id})).mappings().one()


async def changed(api: Any, ctx: Any, schedule_id: uuid.UUID, **changes: Any) -> None:
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.update(s, KEYS, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id),
                               changes=changes)  # fmt: skip


async def in_temporal(server: Any, ctx: Any, schedule_id: uuid.UUID) -> Any:
    answer = await server.client.workflow_service.describe_schedule(
        DescribeScheduleRequest(namespace=server.client.namespace,
                                schedule_id=schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)))
    )  # fmt: skip
    return answer


def fires(found: Any) -> tuple[int, int, tuple[int, int] | None]:
    """The minute, the hour and the days of the week of a cron schedule, as Temporal holds it: a calendar."""
    [calendar] = found.schedule.spec.structured_calendar
    days = [(r.start, r.end) for r in calendar.day_of_week]
    return calendar.minute[0].start, calendar.hour[0].start, days[0] if days and days[0] != (0, 6) else None


async def test_a_new_schedule_is_created_and_recorded_only_after_its_read_back(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    found = await in_temporal(server, ctx, schedule_id)
    assert (found.schedule.state.notes, found.schedule.state.paused) == ("dewpoint generation 1", False)
    assert (fires(found), found.schedule.spec.timezone_name) == ((0, 9, (1, 5)), "Europe/Paris")
    assert found.schedule.policies.catchup_window.seconds == 600
    handle = server.client.get_schedule_handle(schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)))
    action = (await handle.describe()).schedule.action
    assert isinstance(action, ScheduleActionStartWorkflow) and action.task_queue == tick.ADMISSION_QUEUE
    assert action.workflow == "ScheduleTick" and list(action.args) == []  # its tick's workflow id names it
    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 1
    async with dispatch_sessionmaker() as s:
        candidates = (await s.execute(text("select schedule_id from schedule_candidates(50)"))).scalars().all()
    assert schedule_id not in candidates


async def test_each_change_and_a_workflows_disable_reach_temporal_by_generation(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, wf, schedule_id = ready
    await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    await changed(api_sessionmaker, ctx, schedule_id, cron="30 8 * * *")
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    found = await in_temporal(server, ctx, schedule_id)
    assert (found.schedule.state.notes, fires(found)) == ("dewpoint generation 2", (30, 8, None))
    await update_workflow(api_sessionmaker, ctx, wf, enabled=False)  # raises the generation of its schedules
    assert (await stored(owner_sessionmaker, schedule_id))["generation"] == 3
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    found = await in_temporal(server, ctx, schedule_id)
    assert (found.schedule.state.notes, found.schedule.state.paused) == ("dewpoint generation 3", True)


async def test_a_row_changed_while_the_sync_works_stays_queued(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx, _, schedule_id = ready

    async def meanwhile() -> None:
        monkeypatch.setattr(schedule_sync, "_after_read", _noop)
        await changed(api_sessionmaker, ctx, schedule_id, enabled=False)  # generation 2, after the sync read 1

    monkeypatch.setattr(schedule_sync, "_after_read", meanwhile)
    assert (
        await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "pending"
    )  # its marker 1 landed, but the row moved
    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 0
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    found = await in_temporal(server, ctx, schedule_id)
    assert (found.schedule.state.notes, found.schedule.state.paused) == ("dewpoint generation 2", True)


async def _noop() -> None:
    return None


async def test_a_stale_writers_update_is_discarded_and_it_records_nothing(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """Another writer's update lands between this one's describe and its update: Temporal discards this one without
    an error, its read-back shows the other's marker, and it records nothing."""
    ctx, _, schedule_id = ready
    await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    await changed_db(owner_sessionmaker, schedule_id)  # generation 2, for this writer to sync
    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    service, namespace = server.client.workflow_service, server.client.namespace

    async def other_writer() -> None:
        monkeypatch.setattr(schedule_sync, "_after_read", _noop)
        current = await service.describe_schedule(DescribeScheduleRequest(namespace=namespace, schedule_id=temporal_id))
        current.schedule.state.notes = "dewpoint generation 9"
        await service.update_schedule(UpdateScheduleRequest(
            namespace=namespace, schedule_id=temporal_id, schedule=current.schedule,
            conflict_token=current.conflict_token, identity="another", request_id=str(uuid.uuid4()),
        ))  # fmt: skip

    monkeypatch.setattr(schedule_sync, "_after_read", other_writer)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "pending"
    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.notes == "dewpoint generation 9"
    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 1


async def changed_db(owner: Any, schedule_id: uuid.UUID) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update schedules set generation = generation + 1 where id = :i"), {"i": schedule_id})


async def test_a_writer_that_lost_the_leadership_records_nothing(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id, Leading(False)) == "not_leading"
    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.notes == "dewpoint generation 1"
    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 0


async def test_a_deletion_is_recorded_once_its_absence_is_seen_after_the_call_deadline(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx, _, schedule_id = ready
    await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"  # the delete sent
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"  # absent, but within the deadline
    monkeypatch.setattr(schedule_sync, "CALL_DEADLINE", timedelta(0))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    stone = await stored(owner_sessionmaker, schedule_id)
    assert stone["synced_generation"] == stone["generation"] == 2
    with pytest.raises(Exception, match="not found|NotFound|NOT_FOUND"):
        await in_temporal(server, ctx, schedule_id)


async def test_a_tick_that_finds_a_tombstone_queues_it_again(
    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker
) -> None:
    """A stale create can bring a deleted schedule back in Temporal: its tick records `schedule_deleted`, and the sync
    deletes it again."""
    ctx, _, schedule_id = ready
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update schedules set input = null, deleted_at = now(), generation = 2, "
                             "synced_generation = 2 where id = :i"), {"i": schedule_id})  # fmt: skip
    async with dispatch_sessionmaker() as s, s.begin():
        outcome = await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id,
                                        key=f"sched:{schedule_id}:2026-10-04T09:00:00Z")  # fmt: skip
    assert outcome == "refused:schedule_deleted"
    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 1
    async with dispatch_sessionmaker() as s:
        candidates = (await s.execute(text("select schedule_id from schedule_candidates(50)"))).scalars().all()
    assert schedule_id in candidates


async def test_an_update_temporal_refuses_is_recorded_and_retried_later(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx, _, schedule_id = ready

    async def refused(*_: Any, **__: Any) -> bool:
        raise rpc(RPCStatusCode.INVALID_ARGUMENT)

    monkeypatch.setattr(schedule_sync, "_create", refused)
    counts = await schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading())
    assert counts.get("failed") == 1
    row = await stored(owner_sessionmaker, schedule_id)
    assert (row["sync_error"], row["synced_generation"]) == (schedule_sync.TEMPORAL_REFUSED, 0)
    async with dispatch_sessionmaker() as s:
        candidates = (await s.execute(text("select schedule_id from schedule_candidates(50)"))).scalars().all()
    assert schedule_id not in candidates  # retried after a while, not every cycle
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update schedules set sync_error_at = now() - interval '2 minutes' where id = :i"),
                        {"i": schedule_id})  # fmt: skip
    monkeypatch.undo()
    assert (await schedule_sync.sync_schedules(dispatch_sessionmaker, server.client, Leading())).get("synced") == 1
    assert (await stored(owner_sessionmaker, schedule_id))["sync_error"] is None


async def test_firings_missed_past_the_catch_up_window_are_recorded_audited_and_alerted(
    ready, owner_sessionmaker, dispatch_sessionmaker, tmp_path
) -> None:
    """ "No tick is silently dropped" holds within the catch-up window: a Temporal outage longer than it skips the
    firings it missed. Temporal counts them, and the leader reads that count every five minutes, records an increase
    on the schedule, audits and alerts on it. The Temporal Schedule here fires every 2 s with a 10 s window (the
    product's floors are 60 s and 1 minute), so the outage stays short."""
    import asyncio

    import structlog
    from temporalio.client import Schedule, ScheduleIntervalSpec, ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec

    ctx, _, schedule_id = ready
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update schedules set synced_generation = generation where id = :i"), {"i": schedule_id})
    args = ["--db-filename", str(tmp_path / "temporal.db")]
    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    async with await WorkflowEnvironment.start_local(
        data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args
    ) as env:
        await env.client.create_schedule(temporal_id, Schedule(
            action=ScheduleActionStartWorkflow("ScheduleTick", id=temporal_id, task_queue=tick.ADMISSION_QUEUE),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(seconds=2))]),
            policy=SchedulePolicy(catchup_window=timedelta(seconds=10), overlap=ScheduleOverlapPolicy.ALLOW_ALL),
        ))  # fmt: skip
        assert (await schedule_sync.check_misses(dispatch_sessionmaker, env.client))["missed"] == 0
    await asyncio.sleep(25)  # past the window: the firings before its last 10 s are skipped
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update schedules set misses_checked_at = null where id = :i"), {"i": schedule_id})
    async with await WorkflowEnvironment.start_local(
        data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args
    ) as env:
        for _ in range(50):
            found = await schedule_sync.described(env.client, temporal_id)
            if found is not None and found.missed:
                break
            await asyncio.sleep(0.2)
        with structlog.testing.capture_logs() as logs:
            counts = await schedule_sync.check_misses(dispatch_sessionmaker, env.client)
        await env.client.get_schedule_handle(temporal_id).delete()
    row = await stored(owner_sessionmaker, schedule_id)
    assert counts["missed"] == row["misses"] > 0 and row["misses_checked_at"] is not None
    assert [e["event"] for e in logs if e["log_level"] == "error"] == ["schedule_firings_missed"]
    async with owner_sessionmaker() as s:
        audit = (await s.execute(text("select details from audit_log where action = 'schedule.missed'"))).scalar_one()
    assert audit == {"schedule_id": str(schedule_id), "missed": row["misses"]}


async def test_the_synced_action_carries_nothing_and_a_legacy_one_its_key_version(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's M3 ruling: a schedule's action carries no argument (its tick's workflow id names the schedule) and
    no execution timeout, so it holds nothing under a tenant's key. An action synced before still carries the schedule's
    id, sealed: the sync records the version it names, from its own read-back, and `keys retire` waits for the
    schedule's next sync (which `keys reencrypt` queues) to write it without."""
    import dataclasses

    from tests.support.keys import sealed_as_before

    ctx, _, schedule_id = ready
    real = schedule_sync.temporal

    def as_before(row: Any, *, paused: bool) -> Any:
        wanted = real(row, paused=paused)
        return dataclasses.replace(wanted, action=dataclasses.replace(wanted.action, args=[legacy]))

    legacy = await sealed_as_before(str(ctx.tenant_id), str(schedule_id))
    monkeypatch.setattr(schedule_sync, "temporal", as_before)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    assert (await stored(owner_sessionmaker, schedule_id))["action_key_version"] == 1  # the fixture keys' version
    monkeypatch.setattr(schedule_sync, "temporal", real)
    await changed(api_sessionmaker, ctx, schedule_id, cron="30 8 * * *")
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    start = (await in_temporal(server, ctx, schedule_id)).schedule.action.start_workflow
    assert list(start.input.payloads) == [] and not start.HasField("workflow_execution_timeout")
    assert (await stored(owner_sessionmaker, schedule_id))["action_key_version"] is None
