# SPDX-License-Identifier: Apache-2.0
"""An erasure's stages 20 to 80, carried on by the retention process's pass (the 2b-4 outline's steps 2 to 8), against
the CLI dev server: what each stage does, that each resumes, that a failure backs off with its fixed code, that a
stop is honoured, and that the sweep leaves no row of the tenant and every other tenant's rows."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio import workflow
from temporalio.client import Client, ScheduleBackfill, ScheduleOverlapPolicy
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from dewpoint.apps.dispatcher import schedule_sync
from dewpoint.apps.erasure import process, stages, temporal
from dewpoint.core.erasure import service
from dewpoint.core.models.erasure import Stage
from dewpoint.engine.runtime.ids import run_workflow_id, schedule_workflow_id
from tests.apps.dispatcher.test_schedule_sync import Leading
from tests.apps.erasure.support import erasing, populated, rows_of
from tests.core.erasure.test_fence import FENCED_TABLES
from tests.core.retention.support import sql

pytestmark = pytest.mark.usefixtures("development_deployment")
QUEUE = "erasure-stages"


async def until(retention: Any, client: Client, tenant: uuid.UUID, stage: Stage, *, tries: int = 600,
                batch: int = stages.BATCH) -> int:  # fmt: skip
    """The erasure carried on, pass after pass, until it reaches `stage` (Temporal deletes a closed execution within
    about a minute)."""
    at: int | None = None
    for _ in range(tries):
        at = await process.advance(retention, client, tenant, batch=batch)
        if at is not None and at >= stage:
            return at
        await asyncio.sleep(0.3)
    async with retention() as s:
        left = (await s.execute(text("select step, workflow_id, run_id, state, attempts from tenant_erasure_items "
                                     "where tenant_id = :t and state <> 'verified'"), {"t": tenant})).all()  # fmt: skip
    raise AssertionError(f"held at {at}: {[tuple(r) for r in left]}")


async def record(owner: Any, tenant: uuid.UUID) -> Any:
    async with owner() as s:
        return (await s.execute(text("select * from tenant_erasures where tenant_id = :t"), {"t": tenant})).one()


def held(monkeypatch: pytest.MonkeyPatch, stage: Stage) -> None:
    """The erasure stops short at `stage`, which never completes."""

    async def never(_: Any) -> bool:
        return False

    monkeypatch.setitem(stages.STAGES, stage, never)


async def test_an_erasure_reaches_its_bound_with_no_row_of_the_tenant_left_and_every_other_tenants_kept(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker
) -> None:
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    other = await populated(owner_sessionmaker, ingress_sessionmaker)
    every = uuid.uuid4()  # an egress exception for every tenant (0041): no tenant's, never swept
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into egress_allowlist (id, network) values (:i, '192.0.2.0/24')"), {"i": every})
    assert [t for t, n in (await rows_of(owner_sessionmaker, data["t"])).items() if n == 0] == []  # every table
    kept = await rows_of(owner_sessionmaker, other["t"])
    await erasing(api_sessionmaker, data["t"])
    assert await until(retention_sessionmaker, server.client, data["t"], Stage.BOUND) == Stage.BOUND
    assert await rows_of(owner_sessionmaker, data["t"]) == dict.fromkeys(sorted(FENCED_TABLES), 0)
    assert await rows_of(owner_sessionmaker, other["t"]) == kept
    async with owner_sessionmaker() as s:
        survived = (await s.execute(text("select count(*) from egress_allowlist where id = :i"), {"i": every})).scalar()
    assert survived == 1
    async with owner_sessionmaker() as s:
        tombstone = (await s.execute(text("select name, slug, status from tenants where id = :t"), {"t": data["t"]})
                     ).one()  # fmt: skip
        steps = list((await s.execute(text(
            "select details from audit_log where action = 'tenant.erasure.step' and tenant_id = :t order by seq"
        ), {"t": data["t"]})).scalars())  # fmt: skip
    assert tuple(tombstone) == ("Erased tenant", f"erased-{data['t']}", "erasing")  # erased only once complete
    assert [(d["step"], d["next"]) for d in steps] == list(zip(list(Stage)[:-2], list(Stage)[1:-1], strict=True))
    erasure = await record(owner_sessionmaker, data["t"])
    assert erasure.paused_at is not None and erasure.check_after == erasure.latest_close + timedelta(days=30)
    assert erasure.counts["runs"] == 2 and erasure.counts["inbound_events"] == 1  # a tree, its sub-run; the event


async def test_queued_requests_and_pending_events_are_cancelled_and_their_counters_released(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    await erasing(api_sessionmaker, data["t"])
    held(monkeypatch, Stage.END_RUNS)
    assert await until(retention_sessionmaker, server.client, data["t"], Stage.END_RUNS) == Stage.END_RUNS
    async with owner_sessionmaker() as s:
        request = (await s.execute(text("select status, reason from run_requests where id = :i"),
                                   {"i": data["queued"]})).one()  # fmt: skip
        event = (await s.execute(text("select status, reason from inbound_events where endpoint_id = :e"),
                                 {"e": data["endpoint"]})).one()  # fmt: skip
        pending = (await s.execute(text(
            "select e.pending_events, e.pending_bytes, c.pending_events, c.pending_bytes from webhook_endpoints e "
            "join tenant_event_counters c on c.tenant_id = e.tenant_id where e.id = :e"
        ), {"e": data["endpoint"]})).one()  # fmt: skip
    assert tuple(request) == tuple(event) == ("cancelled", "tenant_erased")
    assert tuple(pending) == (0, 0, 0, 0)


async def test_a_starting_request_holds_the_erasure_until_the_reconciler_resolves_it(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker
) -> None:
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    await sql(owner_sessionmaker, "update run_requests set status = 'starting', starting_at = now() where id = :i",
              i=data["queued"])  # fmt: skip
    await erasing(api_sessionmaker, data["t"])
    for _ in range(3):
        assert await process.advance(retention_sessionmaker, server.client, data["t"]) == Stage.RECONCILE
    await sql(owner_sessionmaker, "update run_requests set status = 'started' where id = :i", i=data["queued"])
    assert await process.advance(retention_sessionmaker, server.client, data["t"]) > Stage.RECONCILE


async def test_schedules_are_paused_their_firings_inventoried_then_deleted_and_every_tick_deleted(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker,
    dispatch_sessionmaker, monkeypatch,
) -> None:  # fmt: skip
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    client = server.client
    assert await schedule_sync.sync_one(dispatch_sessionmaker, client, Leading(), data["t"], data["schedule"]) == (
        "synced"
    )  # fmt: skip
    temporal_id = schedule_workflow_id(str(data["t"]), str(data["schedule"]))
    handle = client.get_schedule_handle(temporal_id)
    now = (await handle.describe()).info.created_at.replace(second=0, microsecond=0)
    await handle.backfill(ScheduleBackfill(start_at=now - timedelta(minutes=3), end_at=now,
                                           overlap=ScheduleOverlapPolicy.ALLOW_ALL))  # fmt: skip
    for _ in range(100):  # the ticks run, with no admission worker: they stay open
        shown = await temporal.schedule(client, temporal_id)
        if shown is not None and len(shown.executions) >= 3:
            break
        await asyncio.sleep(0.1)
    ticks = list(shown.executions) if shown else []
    await erasing(api_sessionmaker, data["t"])
    held(monkeypatch, Stage.CANCEL)
    assert await until(retention_sessionmaker, client, data["t"], Stage.CANCEL) == Stage.CANCEL
    assert await temporal.schedule(client, temporal_id) is None
    async with owner_sessionmaker() as s:
        items = {(r.workflow_id, r.run_id): r.source for r in (await s.execute(text(
            "select workflow_id, run_id, source from tenant_erasure_items where tenant_id = :t and step = 60"
        ), {"t": data["t"]}))}  # fmt: skip
        known = list((await s.execute(text("select workflow_id from tenant_erasure_known where kind = 'schedule'"))
                      ).scalars())  # fmt: skip
    assert len(ticks) >= 3 and set(ticks) <= set(items)  # every tick the describe listed, before the delete
    assert f"t:{data['t']}:sched:{data['schedule']}-2026-10-05T09:00:00Z" in {w for w, _ in items}  # its record
    assert known == [temporal_id] and (await record(owner_sessionmaker, data["t"])).paused_at is not None
    monkeypatch.undo()
    assert await until(retention_sessionmaker, client, data["t"], Stage.BOUND) == Stage.BOUND
    for workflow_id, run_id in ticks:  # open ticks: terminated, read, deleted
        assert await temporal.execution(client, workflow_id, run_id) is None


@workflow.defn
class Leaf:
    @workflow.run
    async def run(self) -> None:
        await workflow.wait_condition(lambda: False)


@workflow.defn
class Root:
    """A run that starts a child, continues as new once, then waits until it's cancelled."""

    @workflow.run
    async def run(self, again: bool) -> None:
        if again:
            await workflow.start_child_workflow(Leaf.run, id=f"{workflow.info().workflow_id}/s/0/batch:0")
            workflow.continue_as_new(False)
        await workflow.wait_condition(lambda: False)


@contextlib.asynccontextmanager
async def serving(client: Client) -> AsyncIterator[None]:
    async with Worker(client, task_queue=QUEUE, workflows=[Root, Leaf], workflow_runner=UnsandboxedWorkflowRunner()):
        yield


async def test_running_runs_are_cancelled_waited_for_then_every_execution_walked_and_deleted(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    root = data["tree"]["root"]
    await sql(owner_sessionmaker, "update runs set status = 'running', ended_at = null where root_run_id = :r",
              r=root)  # fmt: skip
    client, workflow_id = server.client, run_workflow_id(str(data["t"]), str(root))
    async with serving(client):
        first = await client.start_workflow(Root.run, True, id=workflow_id, task_queue=QUEUE)
        for _ in range(100):  # it continued as new: its first run closed, its child running
            latest = await temporal.execution(client, workflow_id, None)
            if latest is not None and latest.run_id != first.result_run_id:
                break
            await asyncio.sleep(0.1)
        read = await temporal.read_run(client, workflow_id, first.result_run_id or "")
        assert read.previous is None and read.next == latest.run_id  # type: ignore[union-attr]
        assert [w for w, _ in read.children] == [f"{workflow_id}/s/0/batch:0"]  # from its history, not visibility
        await erasing(api_sessionmaker, data["t"])
        held(monkeypatch, Stage.EXECUTIONS)
        for _ in range(3):  # cancelled, but its projection still running: it waits
            assert await process.advance(retention_sessionmaker, client, data["t"]) == Stage.END_RUNS
            await asyncio.sleep(0.3)
        assert not (await temporal.execution(client, workflow_id, None)).open  # type: ignore[union-attr]
        await sql(owner_sessionmaker, "update runs set status = 'cancelled', ended_at = now() where root_run_id = :r",
                  r=root)  # its workers' end write  # fmt: skip
        assert await process.advance(retention_sessionmaker, client, data["t"]) == Stage.EXECUTIONS
    monkeypatch.undo()
    assert await until(retention_sessionmaker, client, data["t"], Stage.KEYS) >= Stage.KEYS
    child = f"{workflow_id}/s/0/batch:0"
    async with owner_sessionmaker() as s:
        sources = {(r.workflow_id, r.run_id is None): r.source for r in (await s.execute(text(
            "select workflow_id, run_id, source from tenant_erasure_items where tenant_id = :t and step = 60"
        ), {"t": data["t"]}))}  # fmt: skip
    assert (child, False) in sources and sources[(workflow_id, True)] == "runs"
    assert await temporal.execution(client, workflow_id, first.result_run_id) is None  # the chain's first run
    assert await temporal.execution(client, workflow_id, None) is None  # and its last
    assert await temporal.execution(client, child, None) is None  # the child, a loop batch's id


async def test_a_failure_backs_off_with_its_fixed_code_and_alerts_and_a_stop_is_honoured(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    await erasing(api_sessionmaker, data["t"])

    async def refused(_: Any) -> bool:
        raise RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")

    monkeypatch.setitem(stages.STAGES, Stage.RECONCILE, refused)
    waits = []
    with structlog.testing.capture_logs() as logs:
        for _ in range(2):
            assert await process.advance(retention_sessionmaker, server.client, data["t"]) == Stage.RECONCILE
            erasure = await record(owner_sessionmaker, data["t"])
            waits.append((erasure.failure, erasure.attempts, erasure.next_attempt_at - erasure.failed_at))
    assert waits == [("temporal_failed", 1, timedelta(seconds=30)), ("temporal_failed", 2, timedelta(seconds=60))]
    assert [(e["event"], e["code"], e["error"]) for e in logs if e["log_level"] == "error"] == [
        ("erasure_step_failed", "temporal_failed", "RPCError")
    ] * 2
    assert (await process.erase_pass(retention_sessionmaker, server.client)) == {}  # not due: backing off
    monkeypatch.undo()
    async with api_sessionmaker() as s, s.begin():
        await service.stop(s, tenant_id=data["t"], stopped_by=uuid.uuid4())
    await sql(
        owner_sessionmaker, "update tenant_erasures set next_attempt_at = now() where tenant_id = :t", t=data["t"]
    )
    assert (await process.erase_pass(retention_sessionmaker, server.client)) == {}  # stopped: left where it is
    assert await process.advance(retention_sessionmaker, server.client, data["t"]) == Stage.RECONCILE
    async with api_sessionmaker() as s, s.begin():
        await service.retry(s, tenant_id=data["t"], actor_id=uuid.uuid4())
    assert await process.erase_pass(retention_sessionmaker, server.client) == {str(int(Stage.BOUND)): 1}
    erasure = await record(owner_sessionmaker, data["t"])
    assert (erasure.failure, erasure.attempts) == ("firing_bound_unproven", 0)  # the failure cleared; held at 90


async def test_entering_stage_60_waits_for_a_write_in_flight_and_fences_every_later_one(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    from tests.core.erasure.test_writers import waiting

    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    await erasing(api_sessionmaker, data["t"])
    held(monkeypatch, Stage.EXECUTIONS)
    async with owner_sessionmaker() as s, s.begin():  # a worker's straggling write, holding the lock shared
        await s.execute(text("insert into run_slots (run_id, tenant_id) values (:i, :t)"),
                        {"i": uuid.uuid4(), "t": data["t"]})  # fmt: skip
        entering = asyncio.create_task(until(retention_sessionmaker, server.client, data["t"], Stage.EXECUTIONS))
        await waiting(owner_sessionmaker)
        assert not entering.done()
    assert await entering == Stage.EXECUTIONS
    with pytest.raises(Exception, match="tenant_erased"):
        await sql(owner_sessionmaker, "insert into run_slots (run_id, tenant_id) values (:i, :t)", i=uuid.uuid4(),
                  t=data["t"])  # fmt: skip


# The whole-branch review's findings (2b-4a M4)


async def test_more_executions_than_a_batch_are_all_reached_and_deleted(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker
) -> None:
    """Each pass works through every open item, a batch at a time: an id alone whose execution Temporal still shows
    never holds back the run it resolves to (the review's finding 1: stage 60 stalled, silently, past a batch)."""
    from tests.core.retention.support import OLD, run

    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    client, tenant = server.client, data["t"]
    runs = [data["tree"]["root"], data["tree"]["sub"], await run(owner_sessionmaker, data, OLD)]
    async with serving(client):
        for r in runs:
            await client.start_workflow(Leaf.run, id=run_workflow_id(str(tenant), str(r)), task_queue=QUEUE)
    await erasing(api_sessionmaker, tenant)
    assert await until(retention_sessionmaker, client, tenant, Stage.KEYS, batch=1) >= Stage.KEYS
    for r in runs:
        assert await temporal.execution(client, run_workflow_id(str(tenant), str(r)), None) is None


async def test_a_stage_that_waits_over_an_hour_alerts(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """A run ignoring its cancel, a request left starting: a wait is no failure, but one past an hour at the same
    stage alerts on every pass (the review's finding 3)."""
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    await erasing(api_sessionmaker, data["t"])
    held(monkeypatch, Stage.RECONCILE)
    with structlog.testing.capture_logs() as logs:
        assert await process.advance(retention_sessionmaker, server.client, data["t"]) == Stage.RECONCILE
    assert [e for e in logs if e["log_level"] == "error"] == []
    await sql(owner_sessionmaker, "update tenant_erasures set step_at = now() - interval '2 hours' "
              "where tenant_id = :t", t=data["t"])  # fmt: skip
    with structlog.testing.capture_logs() as logs:
        await process.advance(retention_sessionmaker, server.client, data["t"])
    assert [(e["event"], e["step"]) for e in logs if e["log_level"] == "error"] == [("erasure_stalled", 20)]


async def test_a_firing_recorded_after_the_inventory_is_still_found_and_deleted(
    server, owner_sessionmaker, ingress_sessionmaker, api_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """A tick that started before the pause and ran its first activity late records itself after stage 32, until the
    fence goes up at 60: stage 60 reads the records again (the review's finding 4)."""
    data = await populated(owner_sessionmaker, ingress_sessionmaker)
    await erasing(api_sessionmaker, data["t"])
    held(monkeypatch, Stage.END_RUNS)
    assert await until(retention_sessionmaker, server.client, data["t"], Stage.END_RUNS) == Stage.END_RUNS
    late, late_run = f"t:{data['t']}:sched:{data['schedule']}-2026-10-06T09:00:00Z", str(uuid.uuid4())
    await sql(owner_sessionmaker, "insert into schedule_firings (workflow_id, run_id, tenant_id, schedule_id) "
              "values (:w, :r, :t, :s)", w=late, r=late_run, t=data["t"], s=data["schedule"])  # fmt: skip
    monkeypatch.undo()
    assert await until(retention_sessionmaker, server.client, data["t"], Stage.KEYS) >= Stage.KEYS
    async with owner_sessionmaker() as s:
        known = (await s.execute(text("select count(*) from tenant_erasure_known where workflow_id = :w "
                                      "and run_id = :r"), {"w": late, "r": late_run})).scalar_one()  # fmt: skip
    assert known == 1
