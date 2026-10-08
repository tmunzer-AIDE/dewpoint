# SPDX-License-Identifier: Apache-2.0
"""The schedule sync (engine 2b spec §8.2; the owner's rulings on the milestone-3 gate): the reconciler's leader keeps
each Temporal Schedule in step with its row. Each change is a describe (its conflict token), the row read, then one
token-bearing update holding the spec, the action, the pause state and the note `dewpoint generation <n>`. Temporal
discards a stale update without an error, so an OK answer proves nothing: a generation is marked synced only once a
fresh describe shows its marker and a transaction confirms that the row still has that generation and the writer still
holds the leadership; a marker absent or different leaves it queued. A deletion is recorded only once the schedule's
absence is seen a call deadline after it, and a tick that finds a tombstone queues it again."""

import asyncio
import dataclasses
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.api.workflowservice.v1 import DescribeScheduleRequest, UpdateScheduleRequest
from temporalio.client import ScheduleActionStartWorkflow
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import schedules
from dewpoint.apps.dispatcher import schedule_sync, tick
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import schedule_workflow_id
from tests.apps.test_admission import KEYS, TOKEN, current, published
from tests.apps.test_runs import rpc
from tests.apps.test_workflow_ops import update as update_workflow
from tests.core.erasure.test_writers import erase, erasing_first, waiting
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


@dataclasses.dataclass
class Holds:
    """A race test's held events and the syncs it started."""

    events: list[asyncio.Event] = dataclasses.field(default_factory=list)
    tasks: list[asyncio.Task[Any]] = dataclasses.field(default_factory=list)

    def event(self) -> asyncio.Event:
        self.events.append(asyncio.Event())
        return self.events[-1]

    def task(self, started: Any) -> asyncio.Task[Any]:
        self.tasks.append(asyncio.create_task(started))
        return self.tasks[-1]


@pytest.fixture
async def holds() -> AsyncIterator[Holds]:
    """Released at teardown, whatever the test's outcome, before the database's cleanup: a sync left waiting on an
    event would hold its transaction, and the cleanup would wait for it for ever (the 2b-4a replay: a race test run
    before its code hung there)."""
    held = Holds()
    yield held
    for event in held.events:
        event.set()
    if held.tasks:
        _, pending = await asyncio.wait(held.tasks, timeout=30)
        for task in pending:
            task.cancel()
        await asyncio.gather(*held.tasks, return_exceptions=True)


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


OWNER: list[Any] = []  # the test's owner sessionmaker, for the helpers below


@pytest.fixture(autouse=True)
def _owner(owner_sessionmaker: Any) -> Any:
    OWNER[:] = [owner_sessionmaker]
    yield
    OWNER.clear()


async def incarnations(schedule_id: uuid.UUID) -> list[str]:
    """Every Temporal schedule id the schedule may have been created under, oldest first (2b-4a M4)."""
    async with OWNER[0]() as s:
        found = await s.execute(text("select temporal_id from schedule_incarnations where schedule_id = :i "
                                     "order by number"), {"i": schedule_id})  # fmt: skip
        return list(found.scalars())


async def current_id(ctx: Any, schedule_id: uuid.UUID) -> str:
    """Its current incarnation's id: the one the sync last created it under."""
    return (await incarnations(schedule_id) or [schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))])[-1]


async def in_temporal(server: Any, ctx: Any, schedule_id: uuid.UUID) -> Any:
    answer = await server.client.workflow_service.describe_schedule(
        DescribeScheduleRequest(namespace=server.client.namespace, schedule_id=await current_id(ctx, schedule_id))
    )
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
    handle = server.client.get_schedule_handle(await current_id(ctx, schedule_id))
    assert handle.id == schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)) + "~1"  # its first incarnation
    action = (await handle.describe()).schedule.action
    assert isinstance(action, ScheduleActionStartWorkflow) and action.task_queue == tick.ADMISSION_QUEUE
    assert action.id == schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))  # its tick's identity: its own
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
    [creation] = await intervals(owner_sessionmaker, schedule_id)  # disabled before its generation-1 update landed
    assert (creation["class"], creation["missed"], creation["reason"]) == ("unknown", None, "changed_while_waiting")
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
    temporal_id = await current_id(ctx, schedule_id)
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
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"  # paused: its count final
    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.paused is True
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
    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))  # incarnation 0, as before 2b-4a
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, backfilled) "
                "values (:i, :t, :s, 0, true)"
            ),
            {"i": temporal_id, "t": ctx.tenant_id, "s": schedule_id},
        )
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


# 2b-4a M4: schedules created paused (D3f), and the sync fenced by the tenant's lifecycle lock.


async def test_a_new_schedule_is_created_paused_and_unpaused_only_by_a_token_bearing_update(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """A create lands paused; only an update carrying the schedule's conflict token unpauses it, so a late create
    fires nothing, and an erasure's verified pause makes every unpause sent before it stale (the 2b-4 outline)."""
    ctx, _, schedule_id = ready

    async def lost(*_: Any, **__: Any) -> None:
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(schedule_sync, "_update", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    found = await in_temporal(server, ctx, schedule_id)
    assert (found.schedule.state.paused, found.schedule.state.notes) == (True, schedule_sync.CREATED)
    assert (await stored(owner_sessionmaker, schedule_id))["synced_generation"] == 0
    monkeypatch.undo()
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    found = await in_temporal(server, ctx, schedule_id)
    assert (found.schedule.state.paused, found.schedule.state.notes) == (False, "dewpoint generation 1")


async def test_a_sync_holding_its_read_commits_its_create_before_step_1(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The sync holds its transaction, with the tenant's lifecycle lock shared, from its read through its Temporal
    write: step 1 waits for it. Its create lands first; the next pass, the tenant erasing, pauses the schedule (step 3
    then deletes it)."""
    ctx, _, schedule_id = ready
    started: list[asyncio.Task[None]] = []

    async def step_1_meanwhile() -> None:
        started.append(asyncio.create_task(erase(api_sessionmaker, ctx.tenant_id)))
        await waiting(owner_sessionmaker)
        assert not started[0].done()

    monkeypatch.setattr(schedule_sync, "_after_read", step_1_meanwhile)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    await started[0]
    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.paused is False
    monkeypatch.undo()
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"  # generation raised by step 1
    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.paused is True


async def test_a_sync_after_step_1_waits_and_never_creates(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx, _, schedule_id = ready
    erasing, hold = await erasing_first(api_sessionmaker, ctx.tenant_id, monkeypatch)
    syncing = asyncio.create_task(sync(server, dispatch_sessionmaker, ctx, schedule_id))
    try:
        await waiting(owner_sessionmaker)
    finally:
        hold.set()
        await erasing
    assert await syncing == "synced"  # nothing to bring to a tenant being erased: it only pauses or deletes
    with pytest.raises(RPCError, match="not found|NotFound|NOT_FOUND"):
        await in_temporal(server, ctx, schedule_id)


# 2b-4a M4, the owner's ruling on its checkpoint: a fresh Temporal schedule id for each create, recorded before the call


async def test_each_create_is_under_a_fresh_id_recorded_and_committed_before_the_call(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx, _, schedule_id = ready
    base = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    seen: list[list[str]] = []

    async def lost(_: Any, temporal_id: str, __: Any) -> bool:
        seen.append(await incarnations(schedule_id))  # from another connection: committed before the call
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(schedule_sync, "_create", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    assert seen == [[f"{base}~1"]]
    monkeypatch.undo()
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"  # ~1 may still land: never reused
    assert await incarnations(schedule_id) == [f"{base}~1", f"{base}~2"]
    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.paused is False
    assert await schedule_sync.described(server.client, f"{base}~1") is None


async def test_a_create_that_lands_late_stays_paused_under_its_own_id_and_is_deleted(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """A create lost in flight that lands after the next one: never described before it landed, so never updated, it
    stays paused; the stray check, which describes every incarnation that isn't current, finds it and deletes it,
    alerting."""
    import structlog

    ctx, _, schedule_id = ready
    held: list[tuple[str, Any]] = []
    real = schedule_sync._create

    async def lost(client: Any, temporal_id: str, schedule: Any) -> bool:
        held.append((temporal_id, schedule))
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(schedule_sync, "_create", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [(late, schedule)] = held
    assert await real(server.client, late, schedule)  # it lands now
    landed = await schedule_sync.described(server.client, late)
    assert landed is not None and (landed.paused, landed.note) == (True, schedule_sync.CREATED)
    with structlog.testing.capture_logs() as logs:
        assert await schedule_sync.check_strays(dispatch_sessionmaker, server.client) == {"held": 1}  # its own pause
        assert (await schedule_sync.check_strays(dispatch_sessionmaker, server.client))["deleted"] == 1
    assert [e["event"] for e in logs if e["log_level"] == "error"] == ["schedule_incarnation_stray"]
    assert await schedule_sync.described(server.client, late) is None
    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.paused is False  # the current one, untouched


async def lost_then_synced(server: Any, dispatch: Any, ctx: Any, schedule_id: uuid.UUID, monkeypatch: Any) -> Any:
    """The schedule's first create lost in flight (held), the next one synced: what the lost one would send."""
    held: list[tuple[str, Any]] = []

    async def lost(_: Any, temporal_id: str, schedule: Any) -> bool:
        held.append((temporal_id, schedule))
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(schedule_sync, "_create", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch, ctx, schedule_id)
    monkeypatch.undo()
    assert await sync(server, dispatch, ctx, schedule_id) == "synced"
    return held[0]


async def test_a_late_create_after_its_schedule_was_deleted_is_still_found_and_deleted(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's review: a tombstone settles a call deadline after its last incarnation reads back absent, and the
    miss check skips tombstones; a create landing after that would stay paused for good. The stray check describes
    every incarnation that isn't current, a deleted schedule's (even once retention deleted the tombstone) included, for
    good, each again every hour."""
    ctx, _, schedule_id = ready
    late, its_schedule = await lost_then_synced(server, dispatch_sessionmaker, ctx, schedule_id, monkeypatch)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"  # paused
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"  # deleted
    monkeypatch.setattr(schedule_sync, "CALL_DEADLINE", timedelta(0))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"  # the tombstone settled
    monkeypatch.undo()
    deleted = [i for i in await intervals(owner_sessionmaker, schedule_id) if i["kind"] == "deleted"]
    assert deleted == []  # found there at its deletion: nothing of it unaccounted
    for gone in (False, True):  # the tombstone kept, then deleted by retention
        if gone:
            async with owner_sessionmaker() as s, s.begin():
                await s.execute(text("delete from schedules where id = :i"), {"i": schedule_id})
                await s.execute(text("update schedule_incarnations set checked_at = now() - interval '2 hours' "
                                     "where schedule_id = :i"), {"i": schedule_id})  # fmt: skip
        assert await schedule_sync._create(server.client, late, its_schedule)  # it lands now
        assert (await schedule_sync.check_strays(dispatch_sessionmaker, server.client))["held"] == 1  # its own pause
        assert (await schedule_sync.check_strays(dispatch_sessionmaker, server.client))["deleted"] == 1
        assert await schedule_sync.described(server.client, late) is None
    assert (await schedule_sync.check_strays(dispatch_sessionmaker, server.client)) == {"checked": 1}  # read back
    assert (
        await schedule_sync.check_strays(dispatch_sessionmaker, server.client)
    ) == {}  # each checked within the hour


async def test_two_incarnations_missing_firings_in_one_check_both_count(
    ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's review: each incarnation's increase adds to the schedule's total, never replaces another's."""
    ctx, _, schedule_id = ready
    base = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    async with owner_sessionmaker() as s, s.begin():
        for number, temporal_id in ((0, base), (1, f"{base}~1")):
            await s.execute(text("insert into schedule_incarnations "
                                 "(temporal_id, tenant_id, schedule_id, number, backfilled) "
                                 "values (:i, :t, :s, :n, :n = 0)"),
                            {"i": temporal_id, "t": ctx.tenant_id, "s": schedule_id, "n": number})  # fmt: skip
        await s.execute(text("update schedules set synced_generation = generation where id = :i"), {"i": schedule_id})
    missed = {base: 2, f"{base}~1": 3}

    async def described(_: Any, temporal_id: str) -> Any:
        return schedule_sync.Described(b"\x00" * 8, "dewpoint generation 1", missed[temporal_id], paused=False)

    monkeypatch.setattr(schedule_sync, "described", described)
    assert (await schedule_sync.check_misses(dispatch_sessionmaker, None))["missed"] == 5  # type: ignore[arg-type]
    assert (await stored(owner_sessionmaker, schedule_id))["misses"] == 5
    async with owner_sessionmaker() as s:
        audited = sorted((await s.execute(text("select details ->> 'missed' from audit_log "
                                               "where action = 'schedule.missed'"))).scalars())  # fmt: skip
    assert audited == ["2", "3"]


async def every_minute(owner: Any, schedule_id: uuid.UUID) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update schedules set cron = null, every_s = 60 where id = :i"), {"i": schedule_id})


def minutes(start: Any, end: Any) -> int:
    """Firings of a schedule every minute (from the epoch) in (start, end]."""
    return int(end.timestamp() // 60) - int(start.timestamp() // 60)


async def test_a_stray_that_keeps_failing_is_retried_later_and_never_holds_the_others(
    ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx, _, schedule_id = ready
    base = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update schedules set deleted_at = now(), input = null where id = :i"), {"i": schedule_id})
        for n in (1, 2):
            await s.execute(text("insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number) "
                                 "values (:i, :t, :s, :n)"),
                            {"i": f"{base}~{n}", "t": ctx.tenant_id, "s": schedule_id, "n": n})  # fmt: skip
    asked: list[str] = []

    async def described(_: Any, temporal_id: str) -> Any:
        asked.append(temporal_id)
        if temporal_id.endswith("~1"):
            raise rpc(RPCStatusCode.UNAVAILABLE)
        return None

    monkeypatch.setattr(schedule_sync, "described", described)
    for _ in range(2):
        await schedule_sync.check_strays(dispatch_sessionmaker, None, batch=1)  # type: ignore[arg-type]
    assert asked == [f"{base}~1", f"{base}~2"]  # the failing one waits its retry; the scan moves on


# D3f's accounting (the owner's ruling, B): persisted intervals, each from durable evidence; certain only when the
# generation, which every schedule, workflow and tenant state change raises, didn't move; never a complete-looking zero


async def intervals(owner: Any, schedule_id: uuid.UUID) -> list[dict[str, Any]]:
    async with owner() as s:
        found = await s.execute(text("select kind, starts_at, ends_at, class, missed, reason, temporal_id "
                                     "from schedule_intervals where schedule_id = :i order by starts_at, kind"),
                                {"i": schedule_id})  # fmt: skip
        return [dict(r) for r in found.mappings()]


async def incarnation(owner: Any, temporal_id: str) -> dict[str, Any]:
    async with owner() as s:
        found = await s.execute(text("select * from schedule_incarnations where temporal_id = :i"), {"i": temporal_id})
        return dict(found.mappings().one())


async def created_ago(owner: Any, schedule_id: uuid.UUID, minutes_ago: int) -> Any:
    """The schedule created `minutes_ago` minutes ago: what its first incarnation's creation wait starts from."""
    async with owner() as s, s.begin():
        await s.execute(text("update schedules set created_at = now() - make_interval(mins => :m) where id = :i"),
                        {"m": minutes_ago, "i": schedule_id})  # fmt: skip
        return (await s.execute(text("select created_at from schedules where id = :i"), {"i": schedule_id})).scalar()


async def lost_create(monkeypatch: Any) -> list[str]:
    held: list[str] = []

    async def lost(_: Any, temporal_id: str, __: Any) -> bool:
        held.append(temporal_id)
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(schedule_sync, "_create", lost)
    return held


async def test_a_creation_wait_with_an_unchanged_generation_is_certainly_missed_and_counted(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
) -> None:
    """From the schedule's creation to its first landed update, the generation never moved and the update unpaused it:
    every firing due then was missed, counted on its own timing, audited and alerted on; the accounting complete."""
    import structlog

    ctx, _, schedule_id = ready
    await every_minute(owner_sessionmaker, schedule_id)
    since = await created_ago(owner_sessionmaker, schedule_id, 3)
    with structlog.testing.capture_logs() as logs:
        assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [first] = await incarnations(schedule_id)
    landed = (await incarnation(owner_sessionmaker, first))["landed_at"]
    [creation] = await intervals(owner_sessionmaker, schedule_id)
    assert (creation["kind"], creation["class"], creation["reason"]) == (
        "creation", "certainly_missed", "created_paused"
    )  # fmt: skip
    assert (creation["starts_at"], creation["ends_at"]) == (since, landed)
    assert creation["missed"] == minutes(since, landed) >= 3
    assert (await stored(owner_sessionmaker, schedule_id))["creation_misses"] == creation["missed"]
    assert [(e["event"], e["missed"]) for e in logs if e["log_level"] == "error"] == [
        ("schedule_firings_missed", creation["missed"])
    ]


async def test_a_generation_change_while_waiting_leaves_the_creation_wait_unknown(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx, _, schedule_id = ready
    await every_minute(owner_sessionmaker, schedule_id)

    async def lost(*_: Any) -> None:
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(schedule_sync, "_update", lost)  # created, waiting for its first update
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    await changed(api_sessionmaker, ctx, schedule_id, enabled=False)
    await changed(api_sessionmaker, ctx, schedule_id, enabled=True)  # off, then on again, while it waited
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [creation] = await intervals(owner_sessionmaker, schedule_id)
    assert (creation["class"], creation["missed"], creation["reason"]) == ("unknown", None, "changed_while_waiting")
    assert (await stored(owner_sessionmaker, schedule_id))["creation_misses"] == 0


async def test_a_re_enable_during_a_lost_create_is_never_silently_zero(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's case: an incarnation recorded while its schedule was disabled, its create lost; the schedule enabled
    meanwhile; its successor created. Its span is unknown (when the schedule came back isn't evidence it has), never a
    zero; the successor's own wait, under one generation, is certain."""
    ctx, _, schedule_id = ready
    await every_minute(owner_sessionmaker, schedule_id)
    await changed(api_sessionmaker, ctx, schedule_id, enabled=False)
    held = await lost_create(monkeypatch)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    await changed(api_sessionmaker, ctx, schedule_id, enabled=True)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    lost, creation = await intervals(owner_sessionmaker, schedule_id)
    assert (lost["kind"], lost["temporal_id"], lost["class"], lost["missed"], lost["reason"]) == (
        "lost", held[0], "unknown", None, "lost_before_unpause"
    )  # fmt: skip
    assert (creation["kind"], creation["class"]) == ("creation", "certainly_missed")
    assert lost["ends_at"] == creation["starts_at"]  # every span accounted, edge to edge


async def test_a_timing_edit_between_incarnations_is_unknown_never_a_complete_looking_zero(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's case: every minute, its create lost for three hours, then daily: the lost span isn't counted on the
    successor's timing (it would read zero), it's unknown, and the accounting incomplete."""
    ctx, _, schedule_id = ready
    await every_minute(owner_sessionmaker, schedule_id)
    await created_ago(owner_sessionmaker, schedule_id, 180)
    await lost_create(monkeypatch)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    await changed(api_sessionmaker, ctx, schedule_id, every_s=86400)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    lost, creation = await intervals(owner_sessionmaker, schedule_id)
    assert (lost["class"], lost["missed"]) == ("unknown", None)
    assert (creation["class"], creation["missed"]) == ("certainly_missed", 0)  # its own wait, on its own timing
    async with api_sessionmaker() as s:
        await tenant_scope(s, ctx.tenant_id)
        assert (await schedules.accounting(s, schedule_id)).complete is False


async def test_a_failed_second_update_never_moves_the_creation_wait(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's case: the first update lands, its count fails; a later update lands but its answer is lost. The
    first landed update is recorded before any other is sent, and the wait is counted from it, before the next update
    is sent: never from Temporal's latest update time, never on a later timing."""
    ctx, _, schedule_id = ready
    await every_minute(owner_sessionmaker, schedule_id)
    since = await created_ago(owner_sessionmaker, schedule_id, 3)
    real_matching, real_update = schedule_sync._matching, schedule_sync._update

    async def unreachable(*_: Any) -> Any:
        raise rpc(RPCStatusCode.UNAVAILABLE)

    monkeypatch.setattr(schedule_sync, "_matching", unreachable)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    [first] = await incarnations(schedule_id)
    landing = await incarnation(owner_sessionmaker, first)
    assert landing["landed_generation"] == 1 and landing["landed_paused"] is False  # recorded, durably
    assert await intervals(owner_sessionmaker, schedule_id) == []  # its count didn't commit
    monkeypatch.setattr(schedule_sync, "_matching", real_matching)

    async def landed_but_lost(*args: Any) -> None:
        await real_update(*args)
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(schedule_sync, "_update", landed_but_lost)
    await changed(api_sessionmaker, ctx, schedule_id, every_s=120)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)  # the wait recorded first, then the update
    monkeypatch.undo()
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [creation] = await intervals(owner_sessionmaker, schedule_id)
    assert (creation["ends_at"], creation["missed"]) == (landing["landed_at"],
                                                         minutes(since, landing["landed_at"]))  # fmt: skip
    assert (await incarnation(owner_sessionmaker, first))["landed_at"] == landing["landed_at"]


async def test_a_pre_migration_incarnation_that_goes_leaves_its_span_unknown(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """The owner's case: a schedule from before 2b-4a (its incarnation 0, backfilled, nothing known of it before the
    migration) lost from Temporal: its span is unknown, never counted from a guess at its state."""
    ctx, _, schedule_id = ready
    base = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into schedule_incarnations (temporal_id, tenant_id, schedule_id, number, "
                             "backfilled, recorded_at) values (:i, :t, :s, 0, true, now() - interval '1 day')"),
                        {"i": base, "t": ctx.tenant_id, "s": schedule_id})  # fmt: skip
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"  # 0 absent: its successor
    lost, creation = await intervals(owner_sessionmaker, schedule_id)
    assert (lost["temporal_id"], lost["class"], lost["missed"], lost["reason"]) == (
        base, "unknown", None, "lost_from_before_migration"
    )  # fmt: skip
    assert creation["class"] == "certainly_missed" and creation["starts_at"] == lost["ends_at"]


async def test_an_incarnation_sent_an_unpause_then_lost_is_possibly_missed_never_certain(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """Sent an unpause (it may have fired: no tick record proves otherwise), its sync losing leadership before it
    recorded anything, then gone: its span is possibly missed, uncounted."""
    ctx, _, schedule_id = ready
    await every_minute(owner_sessionmaker, schedule_id)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id, Leading(False)) == "not_leading"
    [first] = await incarnations(schedule_id)
    await schedule_sync._delete(server.client, first)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    lost = next(i for i in await intervals(owner_sessionmaker, schedule_id) if i["kind"] == "lost")
    assert (lost["temporal_id"], lost["class"], lost["missed"], lost["reason"]) == (
        first, "possibly_missed", None, "lost_after_unpause"
    )  # fmt: skip


async def test_a_schedule_deleted_before_its_first_update_landed_leaves_that_span_unknown(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    ctx, _, schedule_id = ready
    await lost_create(monkeypatch)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    monkeypatch.setattr(schedule_sync, "CALL_DEADLINE", timedelta(0))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [deleted] = await intervals(owner_sessionmaker, schedule_id)
    assert (deleted["kind"], deleted["class"], deleted["reason"]) == ("deleted", "unknown", "deleted_before_landing")


async def test_an_incarnation_gone_unseen_before_its_schedules_deletion_leaves_its_span_from_its_landing(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """Not found again at or after the deletion, it may have gone at any time since its landing (seeing it unpaused
    earlier proves it could fire, not that it did): possibly missed, from its landing to the deletion."""
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [first] = await incarnations(schedule_id)
    landed = (await incarnation(owner_sessionmaker, first))["landed_at"]
    await schedule_sync._delete(server.client, first)  # gone, unseen
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    monkeypatch.setattr(schedule_sync, "CALL_DEADLINE", timedelta(0))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    async with owner_sessionmaker() as s:
        deleted_at = (await s.execute(text("select deleted_at from schedules where id = :i"),
                                      {"i": schedule_id})).scalar_one()  # fmt: skip
    deleted = [i for i in await intervals(owner_sessionmaker, schedule_id) if i["kind"] == "deleted"]
    assert [(i["class"], i["reason"], i["starts_at"], i["ends_at"]) for i in deleted] == [
        ("possibly_missed", "gone_before_deletion", landed, deleted_at)
    ]


async def test_an_incarnation_gone_before_its_wait_was_counted_leaves_that_wait_unknown(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """Its landing recorded, its count failed, then it went: Temporal can't match its spec any more, so its wait can't
    be counted: unknown, never dropped; and from its landing, possibly missed."""
    ctx, _, schedule_id = ready
    await every_minute(owner_sessionmaker, schedule_id)

    async def unreachable(*_: Any) -> Any:
        raise rpc(RPCStatusCode.UNAVAILABLE)

    monkeypatch.setattr(schedule_sync, "_matching", unreachable)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    [first] = await incarnations(schedule_id)
    landed = (await incarnation(owner_sessionmaker, first))["landed_at"]
    await schedule_sync._delete(server.client, first)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    found = {(i["temporal_id"], i["kind"]): i for i in await intervals(owner_sessionmaker, schedule_id)}
    creation, lost = found[(first, "creation")], found[(first, "lost")]
    assert (creation["class"], creation["missed"], creation["reason"], creation["ends_at"]) == (
        "unknown", None, "gone_before_counted", landed
    )  # fmt: skip
    assert (lost["class"], lost["reason"], lost["starts_at"]) == ("possibly_missed", "lost_after_unpause", landed)


async def test_a_span_left_uncounted_is_audited_and_alerted_on(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    import structlog

    ctx, _, schedule_id = ready
    held = await lost_create(monkeypatch)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    with structlog.testing.capture_logs() as logs:
        assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    lost = next(i for i in await intervals(owner_sessionmaker, schedule_id) if i["kind"] == "lost")
    assert [(e["event"], e["class_"], e["reason"]) for e in logs if e["event"] == "schedule_firings_unaccounted"] == [
        ("schedule_firings_unaccounted", "unknown", "lost_before_unpause")
    ]
    async with owner_sessionmaker() as s:
        entry = (await s.execute(text("select details from audit_log where action = 'schedule.unaccounted' "
                                      "and target_id = :i"), {"i": str(schedule_id)})).scalar_one()  # fmt: skip
    assert entry == {"schedule_id": str(schedule_id), "class": "unknown", "reason": "lost_before_unpause",
                     "from": lost["starts_at"].isoformat(), "to": lost["ends_at"].isoformat()}  # fmt: skip
    assert held and lost["temporal_id"] == held[0]


async def test_an_incarnation_the_stray_check_deleted_after_its_schedules_deletion_was_there_until_it(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """A deleted schedule's incarnations are all the stray check's: one it finds, after the deletion, and deletes before
    the sync's tombstone pass does, was there at the deletion: nothing of it unaccounted."""
    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    assert await schedule_sync.check_strays(dispatch_sessionmaker, server.client) == {"held": 1}  # paused first
    assert (await in_temporal(server, ctx, schedule_id)).schedule.state.paused is True
    assert (await schedule_sync.check_strays(dispatch_sessionmaker, server.client))["deleted"] == 1  # picked again
    monkeypatch.setattr(schedule_sync, "CALL_DEADLINE", timedelta(0))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    assert [i for i in await intervals(owner_sessionmaker, schedule_id) if i["kind"] == "deleted"] == []


async def test_a_deleted_schedules_last_missed_count_is_read_from_it_paused_before_its_deleted(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's review: Temporal's count grows between the five-minute reads, and a deleted schedule's can't be
    read again. Paused, it can't grow (`test_temporal_erasure_contract.py`): the sync pauses it, records the count it
    then shows, committed, and only then deletes it."""
    import dataclasses

    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    first = await current_id(ctx, schedule_id)
    real = schedule_sync.described

    async def grown(client: Any, temporal_id: str) -> Any:  # three firings skipped since the last read
        found = await real(client, temporal_id)
        return dataclasses.replace(found, missed=found.missed + 3) if found is not None else None

    monkeypatch.setattr(schedule_sync, "described", grown)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"
    shown = await real(server.client, first)
    assert shown is not None and shown.paused and (await stored(owner_sessionmaker, schedule_id))["misses"] == 0
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"
    assert (await stored(owner_sessionmaker, schedule_id))["misses"] == 3 and await real(server.client, first)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"
    assert await real(server.client, first) is None
    async with owner_sessionmaker() as s:
        audited = (await s.execute(text("select details from audit_log where action = 'schedule.missed' "
                                        "and target_id = :i"), {"i": str(schedule_id)})).scalar_one()  # fmt: skip
    assert audited == {"schedule_id": str(schedule_id), "missed": 3}


async def test_an_open_or_uncounted_wait_leaves_the_accounting_incomplete_until_its_count_is_recorded(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's review: a wait with no span yet is never shown complete: before its first update lands (open,
    from the schedule's creation), after its count failed (pending, to its landing), complete once it's recorded."""
    ctx, _, schedule_id = ready

    async def accounted() -> Any:
        async with api_sessionmaker() as s:
            await tenant_scope(s, ctx.tenant_id)
            return await schedules.accounting(s, schedule_id)

    async def lost(*_: Any) -> None:
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    async def unreachable(*_: Any) -> Any:
        raise rpc(RPCStatusCode.UNAVAILABLE)

    since = (await stored(owner_sessionmaker, schedule_id))["created_at"].isoformat()
    never = await accounted()
    assert not never.complete and never.uncounted == [
        {"from": since, "to": None, "class": "pending", "reason": "awaiting_first_update"}
    ]  # never synced
    monkeypatch.setattr(schedule_sync, "_update", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    waiting = await accounted()
    assert not waiting.complete and waiting.uncounted == never.uncounted  # created, its first update lost
    monkeypatch.setattr(schedule_sync, "_matching", unreachable)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    [first] = await incarnations(schedule_id)
    landed = (await incarnation(owner_sessionmaker, first))["landed_at"].isoformat()
    pending = await accounted()
    assert not pending.complete and pending.uncounted == [
        {"from": since, "to": landed, "class": "pending", "reason": "count_pending"}
    ]
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    recovered = await accounted()
    assert recovered.complete and recovered.uncounted == []


async def test_a_schedule_deleted_after_its_first_update_was_sent_but_never_seen_leaves_that_span_possibly_missed(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """Created, its first update, an unpause, sent and its answer lost (it may have landed and fired); the schedule
    deleted: its wait is deleted before landing, possibly missed."""
    ctx, _, schedule_id = ready

    async def lost(*_: Any) -> None:
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    monkeypatch.setattr(schedule_sync, "_update", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    monkeypatch.undo()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    for _ in range(2):  # deleted (created paused, its count read), then absent within the call deadline
        assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "deleting"
    monkeypatch.setattr(schedule_sync, "CALL_DEADLINE", timedelta(0))
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    [first] = await incarnations(schedule_id)
    assert (await incarnation(owner_sessionmaker, first))["landed_at"] is None
    [deleted] = await intervals(owner_sessionmaker, schedule_id)
    assert (deleted["kind"], deleted["class"], deleted["reason"]) == (
        "deleted", "possibly_missed", "deleted_before_landing"
    )  # fmt: skip


async def test_a_note_no_sync_update_wrote_is_never_recorded_as_a_landing(ready, dispatch_sessionmaker) -> None:
    """A pause for a delete or an erasure writes its own note, over a first update the sync may never have seen land:
    only a `dewpoint generation <n>` note is a landing."""
    from datetime import UTC, datetime

    ctx, _, schedule_id = ready
    first = await schedule_sync._incarnate(dispatch_sessionmaker, None, ctx.tenant_id, schedule_id)  # type: ignore[arg-type]
    assert first is not None
    for note in (schedule_sync.CREATED, schedule_sync.DELETING, "tenant erasure"):
        shown = schedule_sync.Described(b"\x00" * 8, note, 0, paused=True, updated_at=datetime.now(UTC))
        await schedule_sync._landing(dispatch_sessionmaker, None, ctx.tenant_id, first, shown)  # type: ignore[arg-type]
    async with dispatch_sessionmaker() as s:
        await tenant_scope(s, ctx.tenant_id)
        landed = (await s.execute(text("select landed_at from schedule_incarnations where temporal_id = :i"),
                                  {"i": first})).scalar_one()  # fmt: skip
    assert landed is None


async def test_a_stale_unpause_in_flight_never_lands_between_the_final_read_and_the_delete(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's review: an incarnation already paused (its schedule disabled) and an unpause held in flight by a
    writer that described it before (its conflict token); the schedule deleted. A describe showing it paused isn't
    enough: the unpause could land after it, before the delete, and the count grow unread. The sync's own pause for
    the delete makes that token stale first, and the delete waits for a describe showing that pause."""
    from temporalio.client import ScheduleState

    ctx, _, schedule_id = ready
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    await changed(api_sessionmaker, ctx, schedule_id, enabled=False)
    assert await sync(server, dispatch_sessionmaker, ctx, schedule_id) == "synced"
    first = await current_id(ctx, schedule_id)
    stale = await schedule_sync.described(server.client, first)  # a writer's token, taken before the deletion
    assert stale is not None and stale.paused
    shown = (await server.client.get_schedule_handle(first).describe()).schedule
    unpause = dataclasses.replace(shown, state=ScheduleState(paused=False, note="dewpoint generation 2"))
    real_delete, at_delete = schedule_sync._delete, []

    async def raced(client: Any, temporal_id: str) -> None:  # the held unpause lands just before the delete
        await schedule_sync._update(client, temporal_id, unpause, stale.token)
        found = await schedule_sync.described(client, temporal_id)
        at_delete.append(found is not None and found.paused)
        await real_delete(client, temporal_id)

    monkeypatch.setattr(schedule_sync, "_delete", raced)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    for _ in range(3):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)
    assert at_delete == [True]  # discarded: still paused when deleted


async def test_an_older_sync_never_unpauses_an_incarnation_a_successor_replaced_with_a_token_taken_after_its_pause(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch, holds
) -> None:
    """The owner's review: an older sync lists incarnation 1 as current, then its describe is held until incarnation 2
    is recorded and 1, landing late, is paused by the stray check for its delete; the describe then takes a token
    issued after that pause, which the pause doesn't fence. Its unpause, released around the stray check's final read,
    must never land: incarnation 1 is deleted paused under the stray check's own note, its count the one it read."""
    ctx, _, schedule_id = ready
    held: list[tuple[str, Any]] = []

    async def lost(_: Any, temporal_id: str, schedule: Any) -> bool:
        held.append((temporal_id, schedule))
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    real_create, real_described = schedule_sync._create, schedule_sync.described
    real_update, real_delete = schedule_sync._update, schedule_sync._delete
    monkeypatch.setattr(schedule_sync, "_create", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)  # incarnation 1 recorded, its create in flight
    monkeypatch.setattr(schedule_sync, "_create", real_create)
    [(first, its_schedule)] = held
    waiting, gate, sent, release = holds.event(), holds.event(), holds.event(), holds.event()
    gated = [first]

    async def described(client: Any, temporal_id: str) -> Any:
        if temporal_id in gated:  # the older sync's describe, held
            gated.clear()
            waiting.set()
            await gate.wait()
        return await real_described(client, temporal_id)

    async def update(client: Any, temporal_id: str, schedule: Any, token: bytes) -> None:
        if temporal_id == first:  # its unpause, held in flight
            sent.set()
            await release.wait()
        await real_update(client, temporal_id, schedule, token)

    monkeypatch.setattr(schedule_sync, "described", described)
    monkeypatch.setattr(schedule_sync, "_update", update)
    older = holds.task(sync(server, dispatch_sessionmaker, ctx, schedule_id))  # it lists 1 as current
    await asyncio.wait_for(waiting.wait(), 10)
    assert await asyncio.wait_for(sync(server, dispatch_sessionmaker, ctx, schedule_id), 60) == "synced"  # 2 recorded
    assert await real_create(server.client, first, its_schedule)  # 1's create lands, late
    assert (await asyncio.wait_for(schedule_sync.check_strays(dispatch_sessionmaker, server.client), 60))["held"] == 1
    gate.set()  # the older sync's describe: a token taken after that pause
    await asyncio.wait({asyncio.create_task(sent.wait()), older}, timeout=30, return_when=asyncio.FIRST_COMPLETED)
    at_delete: list[Any] = []

    async def delete(client: Any, temporal_id: str) -> None:
        if temporal_id == first:
            release.set()  # the unpause, if one was sent, lands now: after the final read, before the delete
            await asyncio.wait({older}, timeout=30)
            found = await real_described(client, temporal_id)
            at_delete.append(None if found is None else (found.paused, found.note))
        await real_delete(client, temporal_id)

    monkeypatch.setattr(schedule_sync, "_delete", delete)
    strays = await asyncio.wait_for(schedule_sync.check_strays(dispatch_sessionmaker, server.client), 60)
    assert strays["deleted"] == 1
    release.set()
    await asyncio.wait({older}, timeout=30)
    assert at_delete == [(True, schedule_sync.DELETING)]  # never unpaused: no update landed after the final read
    assert older.done() and older.result() == "pending"
    assert (await incarnation(owner_sessionmaker, first))["unpause_sent_at"] is None


async def test_a_sync_never_unpauses_an_incarnation_its_schedules_deletion_paused_after_it_read_the_row(
    server, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, monkeypatch, holds
) -> None:
    """The same race through a deletion: a sync read the schedule live and created incarnation 1; its read-back is held
    until the schedule is deleted and another sync's tombstone pass paused 1 for its delete. The token it then takes
    isn't fenced: it must see the deletion and send nothing, and 1 is deleted paused under the delete's own note."""
    ctx, _, schedule_id = ready
    real_described, real_update, real_delete = schedule_sync.described, schedule_sync._update, schedule_sync._delete
    waiting, gate, sent, release = holds.event(), holds.event(), holds.event(), holds.event()
    gated: list[bool] = [True]

    async def described(client: Any, temporal_id: str) -> Any:
        found = await real_described(client, temporal_id)
        if found is not None and found.note == schedule_sync.CREATED and gated:  # its read-back of the create, held
            gated.clear()
            waiting.set()
            await gate.wait()
            return await real_described(client, temporal_id)
        return found

    async def update(client: Any, temporal_id: str, schedule: Any, token: bytes) -> None:
        sent.set()
        await release.wait()
        await real_update(client, temporal_id, schedule, token)

    monkeypatch.setattr(schedule_sync, "described", described)
    monkeypatch.setattr(schedule_sync, "_update", update)
    first_sync = holds.task(sync(server, dispatch_sessionmaker, ctx, schedule_id))
    await asyncio.wait_for(waiting.wait(), 10)
    [first] = await incarnations(schedule_id)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await schedules.delete(s, actor_id=ctx.user.id, schedule=await schedules.found(s, schedule_id))
    assert await asyncio.wait_for(sync(server, dispatch_sessionmaker, ctx, schedule_id), 60) == "deleting"  # paused
    gate.set()
    await asyncio.wait({asyncio.create_task(sent.wait()), first_sync}, timeout=30,
                       return_when=asyncio.FIRST_COMPLETED)  # fmt: skip
    at_delete: list[Any] = []

    async def delete(client: Any, temporal_id: str) -> None:
        release.set()  # an update, if one was sent, lands now: after the final read, before the delete
        await asyncio.wait({first_sync}, timeout=30)
        found = await real_described(client, temporal_id)
        at_delete.append(None if found is None else (found.paused, found.note))
        await real_delete(client, temporal_id)

    monkeypatch.setattr(schedule_sync, "_delete", delete)
    assert await asyncio.wait_for(sync(server, dispatch_sessionmaker, ctx, schedule_id), 60) == "deleting"  # deleted
    release.set()
    await asyncio.wait({first_sync}, timeout=30)
    assert at_delete == [(True, schedule_sync.DELETING)]
    assert first_sync.done() and first_sync.result() == "pending"
    assert (await incarnation(owner_sessionmaker, first))["unpause_sent_at"] is None


async def test_a_successor_recorded_while_an_older_sync_holds_its_update_never_leaves_a_stray_unpaused(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch, holds
) -> None:
    """The owner's review: one sync found incarnation 1 absent (its create still in flight) and is about to record
    incarnation 2; 1's create lands; an older sync describes 1, reads it current, and holds its unpause. The successor
    is committed meanwhile, then the unpause released, before anything pauses 1. A non-current incarnation must never
    be unpaused: either the successor waits for the update, or the update isn't sent."""
    ctx, _, schedule_id = ready
    held: list[tuple[str, Any]] = []

    async def lost(_: Any, temporal_id: str, schedule: Any) -> bool:
        held.append((temporal_id, schedule))
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    real_create, real_update, real_incarnate = schedule_sync._create, schedule_sync._update, schedule_sync._incarnate
    monkeypatch.setattr(schedule_sync, "_create", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)  # incarnation 1 recorded, its create in flight
    monkeypatch.setattr(schedule_sync, "_create", real_create)
    [(first, its_schedule)] = held
    deciding, decide, decided, proceed = holds.event(), holds.event(), holds.event(), holds.event()
    sent, release = holds.event(), holds.event()

    async def incarnate(*args: Any) -> Any:  # the sync that found 1 absent: about to record 2, then held
        deciding.set()
        await decide.wait()
        recorded = await real_incarnate(*args)
        decided.set()
        await proceed.wait()
        return recorded

    async def update(client: Any, temporal_id: str, schedule: Any, token: bytes) -> None:
        if temporal_id == first:  # the older sync's unpause, held after its currency read
            sent.set()
            await release.wait()
        await real_update(client, temporal_id, schedule, token)

    monkeypatch.setattr(schedule_sync, "_incarnate", incarnate)
    monkeypatch.setattr(schedule_sync, "_update", update)
    successor = holds.task(sync(server, dispatch_sessionmaker, ctx, schedule_id))
    await asyncio.wait_for(deciding.wait(), 10)  # it found 1 absent
    assert await real_create(server.client, first, its_schedule)  # 1's create lands, late
    older = holds.task(sync(server, dispatch_sessionmaker, ctx, schedule_id))
    await asyncio.wait_for(sent.wait(), 10)  # it read 1 current; its unpause held
    decide.set()
    await asyncio.wait({asyncio.create_task(decided.wait())}, timeout=5)  # 2 committed meanwhile, unless ordered
    release.set()  # the unpause lands, before anything pauses 1
    await asyncio.wait({older}, timeout=30)
    await asyncio.wait_for(decided.wait(), 30)  # the successor's decision, recorded or not
    newest = (await incarnations(schedule_id))[-1]
    shown = await schedule_sync.described(server.client, first)
    proceed.set()
    done, _ = await asyncio.wait({successor, older}, timeout=30)
    assert done == {successor, older}
    assert shown is not None
    assert shown.paused or newest == first  # never a non-current incarnation unpaused


async def test_an_older_sync_waits_for_a_successor_being_recorded_and_then_sends_nothing(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, monkeypatch, holds
) -> None:
    """The same race, the create landing just after the successor's own describe of 1 (under the schedule's lock)
    found it absent: an older sync that then describes 1 and reads it current, before the successor commits, could
    unpause it. Holding the lock shared from its read through its update, it waits for the successor, then sees it."""
    ctx, _, schedule_id = ready
    held: list[tuple[str, Any]] = []

    async def lost(_: Any, temporal_id: str, schedule: Any) -> bool:
        held.append((temporal_id, schedule))
        raise rpc(RPCStatusCode.DEADLINE_EXCEEDED)

    real_create, real_described = schedule_sync._create, schedule_sync.described
    real_update, real_incarnate = schedule_sync._update, schedule_sync._incarnate
    monkeypatch.setattr(schedule_sync, "_create", lost)
    with pytest.raises(RPCError):
        await sync(server, dispatch_sessionmaker, ctx, schedule_id)  # incarnation 1 recorded, its create in flight
    monkeypatch.setattr(schedule_sync, "_create", real_create)
    [(first, its_schedule)] = held
    sent, release, decided, proceed = holds.event(), holds.event(), holds.event(), holds.event()
    older: list[asyncio.Task[str]] = []
    asked: list[Any] = []

    async def described(client: Any, temporal_id: str) -> Any:
        found = await real_described(client, temporal_id)
        if temporal_id == first:
            asked.append(found)
            if len(asked) == 2:  # the successor's describe under the lock: 1 still absent; then its create lands
                assert await real_create(client, first, its_schedule)
                older.append(holds.task(sync(server, dispatch_sessionmaker, ctx, schedule_id)))
                await asyncio.wait({asyncio.create_task(sent.wait())}, timeout=5)  # the older sync, as far as it gets
        return found

    async def incarnate(*args: Any) -> Any:  # the successor, held once it has recorded 2
        recorded = await real_incarnate(*args)
        decided.set()
        await proceed.wait()
        return recorded

    async def update(client: Any, temporal_id: str, schedule: Any, token: bytes) -> None:
        if temporal_id == first:
            sent.set()
            await release.wait()
        await real_update(client, temporal_id, schedule, token)

    monkeypatch.setattr(schedule_sync, "described", described)
    monkeypatch.setattr(schedule_sync, "_incarnate", incarnate)
    monkeypatch.setattr(schedule_sync, "_update", update)
    successor = holds.task(sync(server, dispatch_sessionmaker, ctx, schedule_id))
    await asyncio.wait_for(decided.wait(), 30)  # 2 committed
    release.set()  # the older sync's unpause, if it was sent, lands before anything pauses 1
    await asyncio.wait(set(older), timeout=30)
    newest = (await incarnations(schedule_id))[-1]
    shown = await real_described(server.client, first)
    proceed.set()
    done, _ = await asyncio.wait({successor, *older}, timeout=30)
    assert done == {successor, *older} and newest != first
    assert shown is not None and shown.paused  # 1, no longer current, never unpaused
    assert older[0].result() == "pending"
