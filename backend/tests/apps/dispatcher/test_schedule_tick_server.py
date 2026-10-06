# SPDX-License-Identifier: Apache-2.0
"""`ScheduleTick` (engine 2b spec §8.2; the owner's ruling 10): a one-activity workflow on `dewpoint-admission`, run by
the dispatcher's own unversioned worker. It reads `TemporalScheduledStartTime` once and passes its tick key to its
activity, which takes its authority from the workflow's own id only: an argument naming another schedule, or an id
naming a schedule its tenant doesn't have, records nothing. A firing becomes a request under its key, and a backfill
over a time that already fired admits nothing new. A failing tick is retried within the tick bound (its execution
timeout), and one still unadmitted 10 minutes after its time alerts.

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


async def temporal_schedule(client: Client, schedule_id: str, *, argument: Any = None) -> Any:
    """A Temporal Schedule as the sync creates it (no argument), paused so that only backfills fire; `argument`: the
    sealed one an action synced before the tick contract carried."""
    return await client.create_schedule(
        schedule_id,
        Schedule(
            action=ScheduleActionStartWorkflow(
                "ScheduleTick",
                args=[] if argument is None else [argument],
                id=schedule_id,
                task_queue=tick.ADMISSION_QUEUE,
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


@pytest.mark.parametrize("legacy", [False, True])
async def test_a_firing_is_a_request_under_its_tick_key_and_a_repeat_admits_nothing_new(
    server, ready, owner_sessionmaker, dispatch_sessionmaker, legacy: bool
) -> None:
    """`legacy`: an action synced before the tick contract, carrying the schedule's id sealed, still fires (its
    argument opens, and is ignored: the workflow id names the schedule)."""
    from tests.support.keys import sealed_as_before

    ctx, schedule_id = ready
    client = server.client
    temporal_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id))
    argument = await sealed_as_before(str(ctx.tenant_id), str(schedule_id)) if legacy else None
    handle = await temporal_schedule(client, temporal_id, argument=argument)
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
    handle = await temporal_schedule(client, elsewhere)
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
        handle = await client.start_workflow("ScheduleTick", id=workflow_id, task_queue=tick.ADMISSION_QUEUE)
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


async def test_a_ticks_history_holds_nothing_under_a_tenant_key(server, ready, dispatch_sessionmaker) -> None:
    """The owner's M3 ruling: every payload a tick's execution leaves in Temporal (its activity's input and result, its
    own result) is the tick contract's, unsealed under the tick's marker: no key version, nothing a key retirement
    waits for."""
    from temporalio.api.common.v1 import Payload

    from dewpoint.apps import tick_contract
    from dewpoint.apps.codec import KEY_VERSION, TICK_ENCODING

    ctx, schedule_id = ready
    target = server.client.service_client.config.target_host  # its own client: another test's worker may linger
    client = await Client.connect(target, namespace=server.client.namespace, data_converter=FIXTURE_CONVERTER)
    handle = await temporal_schedule(client, schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)))
    async with main.admission_worker(client, dispatch_sessionmaker, KEYS):
        [first] = await fired(client, handle, datetime.now(UTC).replace(second=0, microsecond=0))
        assert await first.result() == "queued"
    payloads = []
    async for event in first.fetch_history_events():
        for attributes, field in (
            (event.workflow_execution_started_event_attributes, "input"),
            (event.activity_task_scheduled_event_attributes, "input"),
            (event.activity_task_completed_event_attributes, "result"),
            (event.workflow_execution_completed_event_attributes, "result"),
        ):
            if attributes.HasField(field):  # type: ignore[arg-type]
                payloads.extend(getattr(attributes, field).payloads)
    assert len(payloads) == 3  # the activity's input and result, the workflow's result: no input of its own
    for p in payloads:
        assert p.metadata["encoding"] == TICK_ENCODING and KEY_VERSION not in p.metadata
        assert tick_contract.allowed(Payload.FromString(p.data), str(schedule_id))
    await handle.delete()


async def test_the_admission_queues_pollers_show_each_dispatchers_mark(server, dispatch_sessionmaker) -> None:
    """`keys tick-cutover` reads who polls the admission queue: a dispatcher's identity carries the tick contract's
    mark (its own client, as `dispatcher.main` connects it). Other tests' workers, unmarked, may still be listed."""
    import asyncio

    from dewpoint.apps import tick_contract

    target = server.client.service_client.config.target_host
    marked = await Client.connect(target, namespace=server.client.namespace, data_converter=FIXTURE_CONVERTER,
                                  identity=f"7@host {tick_contract.IDENTITY}")  # fmt: skip
    async with main.admission_worker(marked, dispatch_sessionmaker, KEYS):
        for _ in range(100):
            found = await tick.admission_pollers(server.client)
            if any(tick_contract.IDENTITY in identity for identity in found):
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError(f"no marked poller among {found}")


async def test_a_tick_records_its_own_ids_first_a_skip_included(
    ready, owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """2b-4a M4: each tick records its workflow and run ids as its first act, in a transaction of its own, so an
    erasure's firing inventory finds every tick that ran, a skip included. Past its tenant's insert fence (the erasure
    is deleting its executions) the record is refused: the tick still skips, and alerts."""
    ctx, schedule_id = ready
    ticker = tick.Ticker(dispatch_sessionmaker, KEYS)
    workflow_id = schedule_workflow_id(str(ctx.tenant_id), str(schedule_id)) + "-2026-10-05T09:00:00Z"
    key, stamp = tick.tick_key(str(schedule_id), datetime.now(UTC))
    given = tick.TickInput(str(schedule_id), key, stamp)

    async def ran(run_id: str) -> str:
        env = environment(workflow_id)
        env.info = dataclasses.replace(env.info, workflow_run_id=run_id)
        return str(await env.run(ticker.tick, given))

    async def recorded() -> list[tuple[str, str, uuid.UUID]]:
        async with owner_sessionmaker() as s:
            found = await s.execute(
                text("select workflow_id, run_id, schedule_id from schedule_firings order by run_id")
            )
            return [tuple(row) for row in found]

    assert await ran("run-1") == "queued"
    assert await ran("run-1") == "queued"  # a retry of the same run finds its request, and records nothing more
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": ctx.tenant_id})
    assert await ran("run-2") == "skipped:tenant_erasing"
    assert await recorded() == [(workflow_id, "run-1", schedule_id), (workflow_id, "run-2", schedule_id)]
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into tenant_erasures (tenant_id, requested_by, step, fenced_at) "
                             "values (:t, :u, 60, now())"),
                        {"t": ctx.tenant_id, "u": uuid.uuid4()})  # fmt: skip
    with structlog.testing.capture_logs() as logs:
        assert await ran("run-3") == "skipped:tenant_erasing"
    assert [e["event"] for e in logs if e["log_level"] == "error"] == ["schedule_tick_unrecorded"]
    assert len(await recorded()) == 2
