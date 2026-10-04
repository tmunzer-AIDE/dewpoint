# SPDX-License-Identifier: Apache-2.0
"""`ScheduleTick` (engine 2b spec §8.2; the owner's ruling 10): a one-activity workflow on `dewpoint-admission`, run by
the dispatcher's own unversioned worker. It reads `TemporalScheduledStartTime` once and passes its tick key to its
activity, which takes its authority from the workflow's own id only: an argument naming another schedule, or an id
naming a schedule its tenant doesn't have, records nothing. A firing becomes a request under its key, and a backfill
over a time that already fired admits nothing new. A failing tick is retried without limit, and one still unadmitted
10 minutes after its time alerts.

The Temporal Schedules here are created directly: the sync that keeps them in step with `schedules` is task 15's."""

import asyncio
import dataclasses
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleBackfill,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    ScheduleSpec,
    ScheduleState,
    WorkflowFailureError,
)
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment

from dewpoint.apps import schedules
from dewpoint.apps.dispatcher import main, tick
from dewpoint.apps.worker import logs as worker_logs
from dewpoint.core.db import tenant_scope
from dewpoint.engine.runtime.ids import schedule_workflow_id
from tests.apps.test_admission import KEYS, TOKEN, count, current, published
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = pytest.mark.usefixtures("development_deployment")


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        created = await schedules.create(
            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
            timing={"cron": None, "every_s": 3600, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
            mode="live", input={"token": TOKEN, "site": "a"}, enabled=True,
        )  # fmt: skip
    return ctx, created.id


async def temporal_schedule(client: Client, schedule_id: str, *, argument: str) -> Any:
    """A Temporal Schedule as the sync will create it, paused so that only backfills fire."""
    return await client.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                "ScheduleTick", argument, id=schedule_id, task_queue=tick.ADMISSION_QUEUE
            ),  # fmt: skip
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
            state=ScheduleState(paused=True),
        ),
    )


async def fired(client: Client, handle: Any, at: datetime) -> list[Any]:
    """The ticks a backfill of the half minute ending at `at` starts (only `at` fires in it), each to its end."""
    before = {
        w.id
        async for w in client.list_workflows(f"WorkflowType='ScheduleTick' AND WorkflowId STARTS_WITH '{handle.id}'")
    }
    await handle.backfill(ScheduleBackfill(start_at=at - timedelta(seconds=30), end_at=at,
                                           overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
    for _ in range(100):
        listed = [
            w
            async for w in client.list_workflows(
                f"WorkflowType='ScheduleTick' AND WorkflowId STARTS_WITH '{handle.id}'"
            )
        ]
        if len(listed) > len(before) and all(w.status is not None and w.status.name != "RUNNING" for w in listed):
            return [client.get_workflow_handle(w.id, run_id=w.run_id) for w in listed]
        await asyncio.sleep(0.2)
    raise AssertionError("no tick ended")


async def test_a_firing_is_a_request_under_its_tick_key_and_a_repeat_admits_nothing_new(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, schedule_id = ready
    client = server.client
    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    handle = await temporal_schedule(client, temporal_id, argument=str(schedule_id))
    at = datetime.now(UTC).replace(second=0, microsecond=0)
    async with main.admission_worker(client, dispatch_sessionmaker, KEYS):
        [first] = await fired(client, handle, at)
        assert await first.result() == "queued"
        ticks = await fired(client, handle, at)  # the same nominal time again
        assert [await t.result() for t in ticks] == ["queued", "queued"]
    async with owner_sessionmaker() as s:
        keys = (await s.execute(text("select idempotency_key from run_requests"))).scalars().all()
    assert keys == [f"sched:{schedule_id}:{(at).strftime('%Y-%m-%dT%H:%M:%SZ')}"]
    await handle.delete()


async def test_an_id_naming_a_schedule_its_tenant_doesnt_have_records_nothing(
    server, ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """The row is read in the tenant the workflow id names: another tenant's schedule isn't there."""
    _, schedule_id = ready
    client = server.client
    elsewhere = schedule_workflow_id(str(uuid.uuid4()), str(schedule_id))
    handle = await temporal_schedule(client, elsewhere, argument=str(schedule_id))
    async with main.admission_worker(client, dispatch_sessionmaker, KEYS):
        [failed] = await fired(client, handle, datetime.now(UTC).replace(second=0, microsecond=0))
        with pytest.raises(WorkflowFailureError) as e:
            await failed.result()
    assert isinstance(e.value.cause.cause, ApplicationError) and e.value.cause.cause.type == tick.SCHEDULE_UNKNOWN
    assert await count(owner_sessionmaker, "run_requests") == 0
    await handle.delete()


async def test_a_tick_without_its_nominal_time_fails_before_its_activity(server, ready, dispatch_sessionmaker) -> None:
    ctx, schedule_id = ready
    client = server.client
    workflow_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)) + "-by-hand"
    async with main.admission_worker(client, dispatch_sessionmaker, KEYS):
        handle = await client.start_workflow("ScheduleTick", str(schedule_id), id=workflow_id,
                                             task_queue=tick.ADMISSION_QUEUE)  # fmt: skip
        with pytest.raises(WorkflowFailureError) as e:
            await handle.result()
    assert isinstance(e.value.cause, ApplicationError) and e.value.cause.type == "tick_no_nominal_time"


def environment(workflow_id: str) -> ActivityEnvironment:
    env = ActivityEnvironment()
    env.info = dataclasses.replace(env.info, workflow_id=workflow_id)
    return env


async def test_an_argument_naming_another_schedule_is_refused_whatever_the_database_holds() -> None:
    tenant, schedule_id, other = (str(uuid.uuid4()) for _ in range(3))
    nominal = datetime(2026, 10, 4, 9, tzinfo=UTC)
    ticker = tick.Ticker(None, KEYS)  # type: ignore[arg-type]  # never reached
    for workflow_id, argument in (
        (schedule_workflow_id(tenant, schedule_id) + "-2026-10-04T09:00:00Z", other),
        (f"t:{tenant}:run:{schedule_id}", schedule_id),  # not a schedule's id at all
    ):
        key, stamp = tick.tick_key(argument, nominal)
        with pytest.raises(ApplicationError) as e:
            await environment(workflow_id).run(ticker.tick, tick.TickInput(argument, key, stamp))
        assert (e.value.type, e.value.non_retryable) == (tick.TICK_IDENTITY, True)


class Down:
    """A database that doesn't answer."""

    def __call__(self) -> Any:
        raise OSError("connection refused")


async def test_a_tick_still_failing_ten_minutes_after_its_time_alerts() -> None:
    tenant, schedule_id = str(uuid.uuid4()), str(uuid.uuid4())
    ticker = tick.Ticker(Down(), KEYS)  # type: ignore[arg-type]
    for minutes, alerts in ((5, []), (11, ["schedule_tick_late"])):
        key, stamp = tick.tick_key(schedule_id, datetime.now(UTC) - timedelta(minutes=minutes))
        with structlog.testing.capture_logs() as logs, pytest.raises(OSError):
            await environment(schedule_workflow_id(tenant, schedule_id)).run(
                ticker.tick, tick.TickInput(schedule_id, key, stamp)
            )
        assert [entry["event"] for entry in logs if entry["log_level"] == "error"] == alerts


async def test_the_admission_worker_keeps_no_error_text_in_temporals_activity_records(
    server, dispatch_sessionmaker, caplog: pytest.LogCaptureFixture
) -> None:
    """The whole-branch review: a failed tick attempt is recorded through Temporal's activity loggers, which keep no
    error text only once the worker's filter is on them (engine 2b spec §12); the dispatcher's own worker installs it,
    as the engine worker does."""
    for name in ("temporalio.activity", "temporalio.worker._activity"):
        logging.getLogger(name).removeFilter(worker_logs._WITHHOLD)  # as in a dispatcher, which runs no engine worker
    main.admission_worker(server.client, dispatch_sessionmaker, KEYS)
    caplog.set_level(logging.DEBUG)
    try:
        raise RuntimeError(f"failed holding {TOKEN}")
    except RuntimeError:
        logging.getLogger("temporalio.activity").warning(
            "Completing activity as failed ({'activity_type': 'schedule.tick'})", exc_info=True
        )
    assert [r.getMessage() for r in caplog.records if r.name == "temporalio.activity"] == [
        "Completing activity as failed"
    ]
    assert TOKEN not in caplog.text


async def test_an_expiry_alerts_once_when_it_commits_never_for_a_retry_or_a_rolled_back_attempt(
    ready, dispatch_sessionmaker, monkeypatch
) -> None:
    """The owner's recheck of the catch-up ruling: `schedule_tick_expired` alerts once for each expiry newly recorded,
    after its transaction commits. An attempt that decided, then rolled back, alerts nothing; the attempt that records
    it alerts once; an exact retry, which finds the refusal it recorded, alerts nothing again."""
    ctx, schedule_id = ready
    ticker = tick.Ticker(dispatch_sessionmaker, KEYS)
    env = environment(schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)))
    key, stamp = tick.tick_key(str(schedule_id), datetime.now(UTC) - timedelta(hours=1))
    decide = tick.admit_tick

    async def decided_then_lost(*args: Any, **kwargs: Any) -> str:
        await decide(*args, **kwargs)
        raise OSError("connection lost before the commit")

    alerts: list[int] = []
    for failing in (True, False, False):
        monkeypatch.setattr(tick, "admit_tick", decided_then_lost if failing else decide)
        with structlog.testing.capture_logs() as logs:
            try:
                outcome = await env.run(ticker.tick, tick.TickInput(str(schedule_id), key, stamp))
            except OSError:
                outcome = "rolled back"
        alerts.append(sum(entry["event"] == "schedule_tick_expired" for entry in logs))
        assert outcome == ("rolled back" if failing else "refused:schedule_catchup_expired")
    assert alerts == [0, 1, 0]
