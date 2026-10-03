# SPDX-License-Identifier: Apache-2.0
"""The reconciler (engine 2b spec §7.6): one leader among the dispatchers settles what a start left uncertain. An
execution it finds is verified as a dispatcher verifies one, and its request is `started`; a request goes back to the
queue, no attempt counted, only after a trustworthy absence (a describe after the grace period, from a namespace that
answers); any error leaves it `starting`, its slot held. Its grace runs from when it became `starting`, slot or not. A
slot is released only once its run's latest execution is closed, never because its history is gone. Every request it
settles is audited (§2.4)."""

import asyncio
import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from temporalio.service import RPCStatusCode

from dewpoint.apps.dispatcher import dispatch, reconcile
from dewpoint.apps.worker import store
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, ProjectInput, RunSummary
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.dispatcher.support import begin, state
from tests.apps.test_admission import KEYS
from tests.apps.test_runs import rpc
from tests.apps.worker.harness import workers

pytestmark = pytest.mark.usefixtures("development_deployment")


async def starting(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
    found = await begin(dispatch_sessionmaker, request, settings)
    assert isinstance(found, dispatch.Starting)
    return found


async def aged(owner: Any, request_id: uuid.UUID, by: timedelta = reconcile.GRACE + timedelta(seconds=5)) -> None:
    """The request became `starting` `by` ago."""
    async with owner() as s, s.begin():
        await s.execute(
            text("update run_requests set starting_at = starting_at - cast(:by as interval) where id = :i"),
            {"by": by, "i": request_id},
        )


async def reconciled(owner: Any) -> list[Any]:
    async with owner() as s:
        rows = await s.execute(text("select target_id, details from audit_log where action = 'run.request.reconciled'"))
        return [tuple(r) for r in rows]


async def once(dispatch_sessionmaker: Any, client: Any, settings: Any) -> dict[str, int]:
    return await reconcile.reconcile_once(dispatch_sessionmaker, client, KEYS, settings)


class Handle:
    def __init__(self, error: BaseException | None) -> None:
        self.error = error

    async def describe(self) -> Any:
        if self.error is not None:
            raise self.error
        raise AssertionError("no execution in this fake")


class Service:
    def __init__(self, namespace_error: BaseException | None) -> None:
        self.namespace_error = namespace_error

    async def describe_namespace(self, _: Any) -> Any:
        if self.namespace_error is not None:
            raise self.namespace_error
        return object()


class DescribeFails:
    """A client whose describe fails with `error`, and whose namespace answers unless `namespace_error`."""

    namespace = "default"

    def __init__(self, error: BaseException, namespace_error: BaseException | None = None) -> None:
        self.error, self.workflow_service = error, Service(namespace_error)

    def get_workflow_handle(self, _: str, **__: Any) -> Handle:
        return Handle(self.error)


async def test_one_dispatcher_leads_the_reconciler_at_a_time(dispatch_sessionmaker) -> None:
    engine = dispatch_sessionmaker.kw["bind"]
    first, second = reconcile.Leader(engine), reconcile.Leader(engine)
    try:
        assert await first.leading() and not await second.leading()
        assert await first.leading()  # still its own
        await first.close()
        assert await second.leading()
    finally:
        await first.close()
        await second.close()


async def test_an_uncertain_start_whose_execution_exists_is_verified_and_started(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    assert (await dispatch.start(env.client, lost)).kind == "started"  # accepted; its answer never settled
    await aged(owner_sessionmaker, request.id)
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("started", None, 0) and after["slot"] == 1  # the root's end write releases it
    assert after["run"][0] == "running" and after["run"][1] is not None
    assert await reconciled(owner_sessionmaker) == [(str(request.id), {"outcome": "started"})]


async def test_an_uncertain_start_absent_after_its_grace_goes_back_to_the_queue(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    await starting(dispatch_sessionmaker, request, api_settings)  # never reached Temporal
    await aged(owner_sessionmaker, request.id)
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"absent": 1}
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("queued", None, 0) and after["slot"] == 0  # no attempt counted
    assert after["run"][0] == "running"  # kept, non-terminal, hidden behind the request (§7.8)
    assert await reconciled(owner_sessionmaker) == [(str(request.id), {"outcome": "absent"})]
    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)  # due at once


async def test_an_uncertain_start_within_its_grace_is_left_alone(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    await starting(dispatch_sessionmaker, request, api_settings)
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {}
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"


@pytest.mark.parametrize(
    "client",
    [
        DescribeFails(rpc(RPCStatusCode.UNAVAILABLE)),
        DescribeFails(rpc(RPCStatusCode.NOT_FOUND), namespace_error=rpc(RPCStatusCode.UNAVAILABLE)),
        DescribeFails(ConnectionResetError()),
    ],
    ids=["unavailable", "namespace_unreachable", "connection_reset"],
)
async def test_an_absence_that_cant_be_trusted_keeps_the_start_unresolved(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, client
) -> None:
    _, _, request = queued
    await starting(dispatch_sessionmaker, request, api_settings)
    await aged(owner_sessionmaker, request.id)
    assert await once(dispatch_sessionmaker, client, api_settings) == {"unresolved": 1}
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("starting", None, 0) and after["slot"] == 1
    assert await once(dispatch_sessionmaker, client, api_settings) == {}  # checked: not again before RECHECK


async def test_another_execution_found_under_the_runs_id_is_an_id_collision(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    impostor = lost.start.__class__(**{**lost.start.__dict__, "version_id": str(uuid.uuid4())})
    await env.client.start_workflow(RunGraph.run, impostor, id=run_workflow_id(impostor.tenant_id, impostor.run_id),
                                    task_queue=ENGINE_QUEUE)  # fmt: skip
    await aged(owner_sessionmaker, request.id)
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"dead": 1}
    after = await state(owner_sessionmaker, request.id)
    assert after["request"][:2] == ("dead", "id_collision") and after["slot"] == 0


async def test_a_leaked_slot_is_released_only_once_its_runs_execution_is_closed(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """A slot whose run's row already ended (here by hand): released once Temporal says its execution closed, never
    while it still runs."""
    _, _, request = queued
    started = await starting(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, started, await dispatch.start(env.client, started)) == "started"
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update runs set status = 'failed', ended_at = now() where id = :i"), {"i": request.id})
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"live": 1}
    assert (await state(owner_sessionmaker, request.id))["slot"] == 1
    await env.client.get_workflow_handle(run_workflow_id(str(request.tenant_id), str(request.id))).terminate()
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set checked_at = null where id = :i"), {"i": request.id})
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"released": 1}
    assert (await state(owner_sessionmaker, request.id))["slot"] == 0


class RefusedEndWrite(DbRunStore):
    """The worker's projection, but the database refuses the root's end write: logged and skipped, its row left
    `running`, its slot released all the same (the owner's ruling on M2's Task 10)."""

    async def project(self, data: ProjectInput) -> None:
        refused = dataclasses.replace(data.run, status="bogus") if data.run is not None else None
        await super().project(dataclasses.replace(data, run=refused))


@pytest.mark.parametrize("end_write", ["recorded", "refused"])
async def test_a_lost_reply_whose_run_already_ended_is_still_reconciled(
    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, env, monkeypatch, end_write
) -> None:
    """The owner's M3 checkpoints: a start accepted, its reply lost, and the run so quick that its end write (recorded,
    or refused) released the slot while the request was still `starting`. The reconciler finds it by when it entered
    `starting`, never by a slot it no longer has; with its history unavailable it's never queued or started again."""
    ctx, _, request = queued
    monkeypatch.setattr(reconcile, "GRACE", timedelta(0))  # its grace period over at once
    store = DbRunStore if end_write == "recorded" else RefusedEndWrite
    async with workers(env.client, store(worker_sessionmaker, KEYS)):
        lost = await starting(dispatch_sessionmaker, request, api_settings)
        assert (await dispatch.start(env.client, lost)).kind == "started"  # accepted; its reply never settled
        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
        assert (await asyncio.wait_for(handle.result(), 30)).status == "succeeded"
    before = await state(owner_sessionmaker, request.id)
    row = "succeeded" if end_write == "recorded" else "running"
    assert (before["request"][0], before["slot"], before["run"][0]) == ("starting", 0, row)
    # Its history unavailable (NOT_FOUND from a namespace that answers), and its slot gone: its end write ran, so a
    # start did happen. Never back in the queue, never started again: unresolved, with an alert, for an operator.
    with structlog.testing.capture_logs() as seen:
        assert await once(dispatch_sessionmaker, DescribeFails(rpc(RPCStatusCode.NOT_FOUND)), api_settings) == {
            "unresolved": 1
        }
    assert await state(owner_sessionmaker, request.id) == before
    assert any(e["event"] == "start_history_missing" and e["log_level"] == "error" for e in seen)
    assert await begin(dispatch_sessionmaker, request, api_settings) is None  # not due: it isn't queued
    async with owner_sessionmaker() as s, s.begin():  # its history back: asked again without waiting for RECHECK
        await s.execute(text("update run_requests set checked_at = null where id = :i"), {"i": request.id})
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
    after = await state(owner_sessionmaker, request.id)
    assert (after["request"][0], after["slot"]) == ("started", 0)
    assert after["run"][1] is not None  # its started_at, from the execution's own start
    # A recorded end leaves nothing to settle; a refused one leaves a running row, ended from Temporal's result (§7.6).
    assert await once(dispatch_sessionmaker, env.client, api_settings) == (
        {} if end_write == "recorded" else {"ended": 1}
    )
    assert (await state(owner_sessionmaker, request.id))["run"][0] == "succeeded"


async def until_someone_waits(owner: Any) -> None:
    """Until a transaction waits for a lock someone else holds (a row's, here)."""
    for _ in range(200):
        async with owner() as s:
            if (await s.execute(text("select count(*) from pg_locks where not granted"))).scalar_one():
                return
        await asyncio.sleep(0.05)
    raise AssertionError("nobody is waiting for a lock")


@pytest.mark.parametrize("end_write", ["recorded", "refused"])
async def test_an_end_write_in_flight_is_waited_for_before_an_absence_requeues(
    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, end_write
) -> None:
    """The owner's M3 review: the request's lock doesn't hold back the worker's own writes to the run's row and slot.
    An absence's evidence (the row still `running`, the slot still held) is read under those rows' locks, so an end
    write in flight is waited for, and then seen: no requeue."""
    ctx, _, request = queued
    await starting(dispatch_sessionmaker, request, api_settings)
    async with worker_sessionmaker() as w, w.begin():  # the end write, not yet committed
        await w.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(ctx.tenant_id)})
        if end_write == "recorded":
            await w.execute(
                text("update runs set status = 'succeeded', ended_at = now() where id = :i"), {"i": request.id}
            )
        await w.execute(text("delete from run_slots where run_id = :i"), {"i": request.id})
        settling = asyncio.create_task(
            dispatch.settle(dispatch_sessionmaker, dispatch.Ref(request.id, ctx.tenant_id), dispatch.Outcome("absent"))
        )
        await until_someone_waits(owner_sessionmaker)
        assert not settling.done()
    assert await settling == "history_missing"
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"


async def test_a_refused_end_write_keeps_its_row_locked_until_its_slot_is_released(
    queued, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings, monkeypatch
) -> None:
    """The owner's M3 review: a refused end write rolls back its savepoint, and the row lock taken inside it, before it
    releases the slot. Its outer transaction keeps the run's row locked across both, so an absence checked in between
    waits, then finds the slot released: no requeue."""
    ctx, _, request = queued
    await starting(dispatch_sessionmaker, request, api_settings)
    paused, go = asyncio.Event(), asyncio.Event()
    release = store._release

    async def release_when_told(s: Any, run: Any) -> None:  # paused after the refused savepoint, before the release
        paused.set()
        await go.wait()
        await release(s, run)

    monkeypatch.setattr(store, "_release", release_when_told)
    refused = RunSummary(str(request.id), "bogus", datetime.now(UTC).isoformat())
    writing = asyncio.create_task(
        DbRunStore(worker_sessionmaker, KEYS).project(ProjectInput(str(ctx.tenant_id), [], refused))
    )
    try:
        await asyncio.wait_for(paused.wait(), 10)
        settling = asyncio.create_task(
            dispatch.settle(dispatch_sessionmaker, dispatch.Ref(request.id, ctx.tenant_id), dispatch.Outcome("absent"))
        )
        done, _ = await asyncio.wait({settling}, timeout=1.0)
        assert not done, f"settled during the end write: {settling.result()}"  # it waits for the row's lock
    finally:
        go.set()
        await writing
    assert await settling == "history_missing"
    after = await state(owner_sessionmaker, request.id)
    assert (after["request"][0], after["slot"], after["run"][0]) == ("starting", 0, "running")


async def test_a_queued_request_whose_run_already_ended_is_never_started_again(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """An end write that lands only after an absence requeued its request (Temporal said NOT_FOUND for an execution
    that was in fact live): the dispatcher never starts it again. It goes back to `starting`, without a slot, with an
    alert, for the reconciler to verify or leave for an operator."""
    ctx, _, request = queued
    lost = await starting(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, lost, dispatch.Outcome("absent")) == "absent"
    async with owner_sessionmaker() as s, s.begin():  # the late end write
        await s.execute(text("update runs set status = 'succeeded', ended_at = now() where id = :i"), {"i": request.id})
    with structlog.testing.capture_logs() as seen:
        assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Held("run_ended")
    after = await state(owner_sessionmaker, request.id)
    assert (after["request"][0], after["slot"], after["run"][0]) == ("starting", 0, "succeeded")
    assert any(e["event"] == "start_after_end" and e["log_level"] == "error" for e in seen)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set starting_at = now() - interval '1 hour' where id = :i"),
                        {"i": request.id})  # fmt: skip
    gone = DescribeFails(rpc(RPCStatusCode.NOT_FOUND))
    assert await once(dispatch_sessionmaker, gone, api_settings) == {"unresolved": 1}  # never back in the queue


async def test_a_leaked_slot_whose_history_is_gone_is_kept_with_an_alert(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """The owner's ruling: a slot is never released solely because Temporal no longer has the run's history; it's left
    unresolved, with an alert, for an operator."""
    _, _, request = queued
    found = await starting(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("started")) == "started"
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update runs set status = 'failed', ended_at = now() where id = :i"), {"i": request.id})
    with structlog.testing.capture_logs() as seen:
        assert await once(dispatch_sessionmaker, DescribeFails(rpc(RPCStatusCode.NOT_FOUND)), api_settings) == {
            "unresolved": 1
        }
    assert (await state(owner_sessionmaker, request.id))["slot"] == 1
    assert {"event": "slot_history_missing", "log_level": "error"}.items() <= next(
        e for e in seen if e["event"] == "slot_history_missing"
    ).items()


async def test_a_starting_request_always_says_when_it_became_starting(queued, owner_sessionmaker) -> None:
    """The reconciler's grace depends on it: the schema refuses a `starting` request without it."""
    _, _, request = queued
    with pytest.raises(IntegrityError, match="run_requests_starting_since"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update run_requests set status = 'starting' where id = :i"), {"i": request.id})
