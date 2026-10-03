# SPDX-License-Identifier: Apache-2.0
"""A start and its outcome (engine 2b spec §7.4, §7.8): only a confirmed refusal counts as an attempt, backing off
(5 s, doubling, capped at 10 min) until the 10th makes the request `dead` and fails its run with `start_failed`; an
uncertain start counts as nothing and stays `starting`, its slot held, for the reconciler; "already started" is
verified from the execution's own start before it counts, else it's an id collision. Confirmation is idempotent and
late-safe: it never changes a run that already ended, nor reserves its slot again."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.common import WorkflowIDReusePolicy
from temporalio.service import RPCStatusCode

from dewpoint.apps.dispatcher import dispatch
from dewpoint.engine.runtime.activities import ENGINE_QUEUE
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.dispatcher.support import BUILD, begin, state, workers
from tests.apps.test_admission import KEYS, admit, current, published
from tests.apps.test_runs import FakeClient, LostAck, rpc

pytestmark = pytest.mark.usefixtures("development_deployment")


async def started(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
    starting = await begin(dispatch_sessionmaker, request, settings)
    assert isinstance(starting, dispatch.Starting)
    return starting


async def through(dispatch_sessionmaker: Any, starting: dispatch.Starting, client: Any) -> str:
    return await dispatch.settle(dispatch_sessionmaker, starting, await dispatch.start(client, starting))


async def test_an_accepted_start_marks_the_request_started_and_its_run_started(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    client = FakeClient()
    assert await through(dispatch_sessionmaker, await started(dispatch_sessionmaker, request, api_settings),
                         client) == "started"  # fmt: skip
    assert client.calls == [(run_workflow_id(str(request.tenant_id), str(request.id)),
                             WorkflowIDReusePolicy.REJECT_DUPLICATE)]  # fmt: skip
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("started", None, 0) and after["run"][1] is not None and after["slot"] == 1


async def test_a_confirmed_refusal_counts_an_attempt_and_waits_its_backoff_with_the_slot_released(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await started(dispatch_sessionmaker, request, api_settings)
    assert await through(dispatch_sessionmaker, starting, FakeClient(rpc(RPCStatusCode.INVALID_ARGUMENT))) == "refused"
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("queued", None, 1) and after["slot"] == 0 and after["run"][:2] == ("running", None)
    async with owner_sessionmaker() as s:
        wait = (await s.execute(text("select next_attempt_at - now() from run_requests"))).scalar_one()
    assert timedelta(seconds=4) < wait <= timedelta(seconds=5)
    assert await begin(dispatch_sessionmaker, request, api_settings) is None  # not due before its backoff ends


def test_the_backoff_doubles_from_5_seconds_and_stops_at_10_minutes() -> None:
    assert [dispatch.backoff(n).total_seconds() for n in (1, 2, 3, 8, 9, 10)] == [5, 10, 20, 600, 600, 600]


async def test_the_tenth_confirmed_refusal_makes_the_request_dead_and_fails_its_run(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await started(dispatch_sessionmaker, request, api_settings)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set attempts = 9"))
    assert await through(dispatch_sessionmaker, starting, FakeClient(rpc(RPCStatusCode.FAILED_PRECONDITION))) == "dead"
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("dead", "start_refused", 10) and after["slot"] == 0 and after["run"][0] == "failed"
    async with owner_sessionmaker() as s:
        run = (await s.execute(text("select error_code from runs"))).scalar_one()
        audited = (await s.execute(text("select count(*) from audit_log where action = 'run.request.dead'"))).scalar()
    assert (run, audited) == ("start_failed", 1)


@pytest.mark.parametrize("answer", [rpc(RPCStatusCode.UNAVAILABLE), LostAck(TimeoutError()), ConnectionResetError()])
async def test_an_uncertain_start_counts_nothing_and_holds_its_slot(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, answer
) -> None:
    _, _, request = queued
    starting = await started(dispatch_sessionmaker, request, api_settings)
    assert await through(dispatch_sessionmaker, starting, FakeClient(answer)) == "uncertain"
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("starting", None, 0) and after["slot"] == 1 and after["run"][:2] == ("running", None)


async def test_a_busy_temporal_puts_the_request_back_without_an_attempt(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await started(dispatch_sessionmaker, request, api_settings)
    client = FakeClient(rpc(RPCStatusCode.RESOURCE_EXHAUSTED))
    assert await through(dispatch_sessionmaker, starting, client) == "throttled"
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("queued", None, 0) and after["slot"] == 0


async def test_a_late_confirmation_never_changes_a_run_that_already_ended(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """A fast run finishes, its end write making its row terminal and releasing its slot, before the dispatcher
    records `started` (§7.8)."""
    _, _, request = queued
    starting = await started(dispatch_sessionmaker, request, api_settings)
    outcome = await dispatch.start(FakeClient(), starting)
    async with owner_sessionmaker() as s, s.begin():  # the run's end write
        await s.execute(text("update runs set status = 'succeeded', ended_at = now() where id = :i"), {"i": request.id})
        await s.execute(text("delete from run_slots where run_id = :i"), {"i": request.id})
    assert await dispatch.settle(dispatch_sessionmaker, starting, outcome) == "started"
    after = await state(owner_sessionmaker, request.id)
    assert after["request"][0] == "started" and after["run"][0] == "succeeded" and after["slot"] == 0


async def test_already_started_is_verified_from_the_executions_own_start(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """A start whose answer was lost, sent again: Temporal refuses the duplicate id, and the execution's started event,
    decoded with the tenant's key, names this request: it's `started` (§7.4)."""
    _, _, request = queued
    starting = await started(dispatch_sessionmaker, request, api_settings)
    await env.client.start_workflow(
        RunGraph.run,
        starting.start,
        id=run_workflow_id(starting.start.tenant_id, starting.start.run_id),
        task_queue=ENGINE_QUEUE,
    )  # fmt: skip  (the lost one)
    assert await through(dispatch_sessionmaker, starting, env.client) == "started"
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "started"


async def test_another_execution_under_the_runs_id_is_an_id_collision(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    starting = await started(dispatch_sessionmaker, request, api_settings)
    impostor = starting.start.__class__(**{**starting.start.__dict__, "version_id": str(uuid.uuid4())})
    await env.client.start_workflow(RunGraph.run, impostor, id=run_workflow_id(impostor.tenant_id, impostor.run_id),
                                    task_queue=ENGINE_QUEUE)  # fmt: skip
    assert await through(dispatch_sessionmaker, starting, env.client) == "dead"
    after = await state(owner_sessionmaker, request.id)
    assert after["request"][:2] == ("dead", "id_collision") and after["run"][0] == "failed" and after["slot"] == 0


async def test_a_cycle_starts_each_tenants_oldest_due_request(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    tenants = []
    for _ in range(2):
        ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
        tenants.append((ctx, wf))
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    first = [(await admit(api_sessionmaker, ctx, wf, key=f"{n}")).request for n, (ctx, wf) in enumerate(tenants)]
    client = FakeClient()
    counts = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD)
    assert counts == {"started": 2} and {a.run_id for a, _, _ in client.started} == {str(r.id) for r in first}
