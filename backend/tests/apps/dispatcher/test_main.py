# SPDX-License-Identifier: Apache-2.0
"""The dispatcher process outlives what it can't control (the whole-branch review): a cycle whose observation of the
current build fails (Temporal briefly unavailable) dispatches nothing, and the next one dispatches again; any cycle
that fails is logged by type and the loop goes on."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.service import RPCStatusCode

from dewpoint.apps.dispatcher import dispatch, main
from dewpoint.apps.worker.deployment import this_build
from tests.apps.dispatcher.support import state
from tests.apps.test_admission import KEYS
from tests.apps.test_runs import FakeClient, FakeDeployment, rpc

pytestmark = pytest.mark.usefixtures("development_deployment")


class Flaky(FakeDeployment):
    """The deployment, unavailable for its first `failures` calls."""

    def __init__(self, failures: int) -> None:
        super().__init__(this_build())
        self.failures = failures

    async def describe_worker_deployment(self, request: Any) -> Any:
        if self.failures:
            self.failures -= 1
            raise rpc(RPCStatusCode.UNAVAILABLE)
        return await super().describe_worker_deployment(request)


class NotLeading:
    async def leading(self) -> bool:
        return False


async def reported(owner: Any, instance: uuid.UUID) -> Any:
    async with owner() as s:
        found = await s.execute(text("select details from dispatcher_reports where instance_id = :i"), {"i": instance})
        return found.scalar()


async def test_a_cycle_whose_observation_fails_dispatches_nothing_and_the_next_one_dispatches(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    client = FakeClient()
    client.workflow_service = Flaky(failures=1)
    instance, rotation = uuid.uuid4(), dispatch.Rotation()

    async def cycle() -> None:
        await main.cycle(dispatch_sessionmaker, client, KEYS, api_settings, instance=instance, reconciler=uuid.uuid4(),
                         leader=NotLeading(), rotation=rotation)  # type: ignore[arg-type]  # fmt: skip

    await cycle()  # Temporal unavailable: no build observed, nothing dispatched
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "queued"
    assert (await reported(owner_sessionmaker, instance))["current_build"] is False
    await cycle()  # Temporal back
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "started"
    assert (await reported(owner_sessionmaker, instance)) == {"current_build": True, "started": 1}


async def test_the_loop_outlives_a_cycle_that_fails(monkeypatch) -> None:
    monkeypatch.setattr(main, "CYCLE_S", 0)
    calls: list[int] = []

    async def cycle() -> None:
        calls.append(len(calls))
        if len(calls) == 1:
            raise ConnectionResetError("the database went away")

    await main.serve(cycle, cycles=3)
    assert calls == [0, 1, 2]


async def test_a_cycle_matches_events_only_when_it_observed_the_current_build(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, ingress_sessionmaker,
    api_settings,
) -> None:  # fmt: skip
    """Admission refuses a durable request for want of a fresh build record, for good: a cycle that couldn't observe
    the build leaves events pending, and the next one matches them (2b-3b, M3)."""
    from tests.apps.dispatcher.inbound import bind, event_state, inbound, send

    ready = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                          api_settings)  # fmt: skip
    await bind(owner_sessionmaker, ready)
    [event_id] = await send(ingress_sessionmaker, ready, {"type": "ap_down"})
    client = FakeClient()
    client.workflow_service = Flaky(failures=1)
    instance, rotation = uuid.uuid4(), dispatch.Rotation()

    async def cycle() -> None:
        await main.cycle(dispatch_sessionmaker, client, KEYS, api_settings, instance=instance, reconciler=uuid.uuid4(),
                         leader=NotLeading(), rotation=rotation)  # type: ignore[arg-type]  # fmt: skip

    await cycle()
    assert (await event_state(owner_sessionmaker, event_id))["status"] == "pending"
    await cycle()
    assert (await event_state(owner_sessionmaker, event_id))["status"] == "matched"
    assert (await reported(owner_sessionmaker, instance)) == {"current_build": True, "event_matched": 1}


async def test_the_leader_recounts_inbound_event_counters_and_reports_it(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, ingress_sessionmaker,
    api_settings, monkeypatch,
) -> None:  # fmt: skip
    from tests.apps.dispatcher.inbound import inbound, send

    ready = await inbound(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
                          api_settings)  # fmt: skip
    await send(ingress_sessionmaker, ready, {"type": "ap_down"})
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update webhook_endpoints set pending_events = 5 where id = :e"), {"e": ready.endpoint_id})

    async def nothing(*args: Any, **kwargs: Any) -> dict[str, int]:
        return {}

    for step in ("reconcile_once", "send_cancels", "sync_schedules", "check_misses"):
        monkeypatch.setattr(main, step, nothing)

    class Leading:
        async def leading(self) -> bool:
            return True

    client = FakeClient()
    client.workflow_service = Flaky(failures=0)
    reconciler = uuid.uuid4()
    await main.cycle(dispatch_sessionmaker, client, KEYS, api_settings, instance=uuid.uuid4(), reconciler=reconciler,
                     leader=Leading(), rotation=dispatch.Rotation())  # type: ignore[arg-type]  # fmt: skip
    assert await reported(owner_sessionmaker, reconciler) == {"recount_recounted": 1, "recount_drifted": 1}
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select pending_events from webhook_endpoints where id = :e"),
                                {"e": ready.endpoint_id})).scalar_one() == 0  # fmt: skip
