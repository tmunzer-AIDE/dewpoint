# SPDX-License-Identifier: Apache-2.0
"""The reconciler (engine 2b spec §7.6): one leader among the dispatchers settles what a start left uncertain. An
execution it finds is verified as a dispatcher verifies one, and its request is `started`; a request goes back to the
queue, no attempt counted, only after a trustworthy absence (a describe after the grace period, from a namespace that
answers); any error leaves it `starting`, its slot held. A slot is released only once its run's latest execution is
closed. Every request it settles is audited (§2.4)."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.service import RPCStatusCode

from dewpoint.apps.dispatcher import dispatch, reconcile
from dewpoint.engine.runtime.activities import ENGINE_QUEUE
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.dispatcher.support import begin, state
from tests.apps.test_admission import KEYS
from tests.apps.test_runs import rpc

pytestmark = pytest.mark.usefixtures("development_deployment")


async def starting(dispatch_sessionmaker: Any, request: Any, settings: Any) -> dispatch.Starting:
    found = await begin(dispatch_sessionmaker, request, settings)
    assert isinstance(found, dispatch.Starting)
    return found


async def aged(owner: Any, request_id: uuid.UUID, by: timedelta = reconcile.GRACE + timedelta(seconds=5)) -> None:
    """The start was made `by` ago: its slot was reserved then."""
    async with owner() as s, s.begin():
        await s.execute(
            text("update run_slots set reserved_at = reserved_at - cast(:by as interval) where run_id = :i"),
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

    def get_workflow_handle(self, _: str) -> Handle:
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
