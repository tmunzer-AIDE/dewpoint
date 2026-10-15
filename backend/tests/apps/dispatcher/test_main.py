# SPDX-License-Identifier: Apache-2.0
"""The dispatcher process outlives what it can't control (the whole-branch review): a cycle whose observation of the
current build fails (Temporal briefly unavailable) dispatches nothing, and the next one dispatches again; any cycle
that fails is logged by type and the loop goes on."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.service import RPCStatusCode
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.dispatcher import dispatch, main
from dewpoint.apps.worker.deployment import this_build
from dewpoint.core.config import Settings
from tests.apps.dispatcher.support import state
from tests.apps.test_admission import KEYS
from tests.apps.test_runs import FakeClient, FakeDeployment, rpc

pytestmark = pytest.mark.usefixtures("development_deployment")


class Flaky(FakeDeployment):
    """The deployment, unavailable for its first `failures` calls."""

    def __init__(self, failures: int) -> None:
        super().__init__(this_build())
        self.failures = failures

    async def describe_worker_deployment(self, request: Any, **kw: Any) -> Any:
        if self.failures:
            self.failures -= 1
            raise rpc(RPCStatusCode.UNAVAILABLE)
        return await super().describe_worker_deployment(request, **kw)


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

    for step in ("reconcile_once", "send_cancels", "sync_schedules", "check_misses", "check_budget"):
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


async def test_the_leader_carries_out_the_operators_commands_and_reports_them(
    owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:  # fmt: skip
    """2b-4b M3: the commands pass is the leader's, after the reconciler's (its outcomes in the reconciler's report)."""
    seen: list[str] = []

    async def nothing(*args: Any, **kwargs: Any) -> dict[str, int]:
        return {}

    async def carried_out(*args: Any, **kwargs: Any) -> dict[str, int]:
        seen.append("commands")
        return {"slot_released": 1}

    for step in ("reconcile_once", "reconcile_subruns", "send_cancels", "sync_schedules", "check_misses",
                 "check_strays", "recount_once"):  # fmt: skip
        monkeypatch.setattr(main, step, nothing)
    monkeypatch.setattr(main, "commands_once", carried_out)

    class Leading:
        async def leading(self) -> bool:
            return True

    client = FakeClient()
    client.workflow_service = Flaky(failures=0)
    reconciler = uuid.uuid4()
    await main.cycle(dispatch_sessionmaker, client, KEYS, api_settings, instance=uuid.uuid4(), reconciler=reconciler,
                     leader=Leading(), rotation=dispatch.Rotation())  # type: ignore[arg-type]  # fmt: skip
    assert seen == ["commands"]
    assert (await reported(owner_sessionmaker, reconciler)).get("command_slot_released") == 1


async def test_the_leader_checks_the_ingress_budget_and_reports_it(
    owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:  # fmt: skip
    """The owner's ruling on the 2b-4b M3 checkpoint 4: the budget against its truth, in the reconciler's report."""

    async def nothing(*args: Any, **kwargs: Any) -> dict[str, int]:
        return {}

    for step in ("reconcile_once", "reconcile_subruns", "send_cancels", "commands_once", "sync_schedules",
                 "check_misses", "check_strays", "recount_once"):  # fmt: skip
        monkeypatch.setattr(main, step, nothing)

    class Leading:
        async def leading(self) -> bool:
            return True

    client = FakeClient()
    client.workflow_service = Flaky(failures=0)
    reconciler = uuid.uuid4()
    await main.cycle(dispatch_sessionmaker, client, KEYS, api_settings, instance=uuid.uuid4(), reconciler=reconciler,
                     leader=Leading(), rotation=dispatch.Rotation())  # type: ignore[arg-type]  # fmt: skip
    assert (await reported(owner_sessionmaker, reconciler)).get("budget_checked") == 1


async def test_the_leader_clears_the_entries_of_settled_items_each_cycle(
    owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:  # fmt: skip
    """The owner's ruling on the M3 checkpoint: a held count of a request no longer queued goes within a cycle."""
    from tests.core.retention.support import sql, tenant

    async def nothing(*args: Any, **kwargs: Any) -> dict[str, int]:
        return {}

    for step in ("reconcile_once", "reconcile_subruns", "send_cancels", "commands_once", "sync_schedules",
                 "check_misses", "check_strays", "recount_once"):  # fmt: skip
        monkeypatch.setattr(main, step, nothing)
    ctx = await tenant(owner_sessionmaker)
    await sql(owner_sessionmaker, "insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at, "
              "held_at) values (:t, 'dispatch', gen_random_uuid(), 7, 'RuntimeError', now(), now())",
              t=ctx["t"])  # a request that isn't queued (there's none): settled  # fmt: skip

    class Leading:
        async def leading(self) -> bool:
            return True

    client = FakeClient()
    client.workflow_service = Flaky(failures=0)
    reconciler = uuid.uuid4()
    await main.cycle(dispatch_sessionmaker, client, KEYS, api_settings, instance=uuid.uuid4(), reconciler=reconciler,
                     leader=Leading(), rotation=dispatch.Rotation())  # type: ignore[arg-type]  # fmt: skip
    assert (await reported(owner_sessionmaker, reconciler)).get("settled_entries_cleared") == 1
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from work_failures where tenant_id = :t"),
                                {"t": ctx["t"]})).scalar_one() == 0  # fmt: skip


async def test_a_stop_request_ends_the_loop_once_the_cycle_in_hand_ends(monkeypatch) -> None:
    """The owner's ruling D1 (graceful stop): SIGTERM lets the cycle in hand end, a start in flight getting its answer,
    starts no other, and cuts the wait between cycles short."""
    monkeypatch.setattr(main, "CYCLE_S", 3600.0)  # a wait the stop didn't cut short would outlast the test
    requested, events = asyncio.Event(), []

    async def cycle() -> None:
        events.append("began")
        requested.set()
        await asyncio.sleep(0)
        events.append("ended")

    await asyncio.wait_for(main.serve(cycle, stop=requested), 10)
    assert events == ["began", "ended"]


class Parts:
    """The dispatcher process's parts around its cycles: what each did, in order."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, requested: asyncio.Event) -> None:
        self.events: list[str] = []
        test = self

        class Engine:
            async def dispose(self) -> None:
                test.events.append("disposed")

        class Leader:
            def __init__(self, engine: object) -> None: ...

            async def close(self) -> None:
                test.events.append("lead released")

        @asynccontextmanager
        async def admission_worker(*args: object) -> AsyncIterator[None]:
            test.events.append("admitting")
            try:
                yield
            finally:
                test.events.append("admission stopped")

        async def cycle(*args: object, **kwargs: object) -> None:
            test.events.append("cycle")
            requested.set()

        async def recorded(*args: object) -> object:
            return SimpleNamespace(environment="development")

        async def connect(*args: object, **kwargs: object) -> object:
            test.events.append("connected")
            return SimpleNamespace()

        monkeypatch.setattr(main, "make_engine", lambda url: Engine())
        monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
        monkeypatch.setattr(main, "startup", recorded)
        monkeypatch.setattr(main, "temporal_connect", connect)
        monkeypatch.setattr(main.budget, "instrument", lambda client: None)
        monkeypatch.setattr(main.start_call, "install", lambda client: None)
        monkeypatch.setattr(main, "Leader", Leader)
        monkeypatch.setattr(main, "admission_worker", admission_worker)
        monkeypatch.setattr(main, "cycle", cycle)
        monkeypatch.setattr(main, "CYCLE_S", 3600.0)


def settings() -> Settings:
    return Settings(database_url="postgresql+asyncpg://u:p@localhost/x", kek_b64="A" * 43 + "=",
                    public_origin="https://dewpoint.test")  # fmt: skip


async def test_a_stopped_dispatcher_stops_admitting_then_hands_over_the_lead(monkeypatch) -> None:
    """The owner's rulings D1, D2: after its last cycle, the admission worker stops (a tick in hand gets its grace),
    the leader's lock goes, for another dispatcher to take, and then the engine."""
    requested = asyncio.Event()
    parts = Parts(monkeypatch, requested)
    await asyncio.wait_for(main.run(settings(), stop_requested=requested), 10)
    assert parts.events == ["connected", "admitting", "cycle", "admission stopped", "lead released", "disposed"]


async def test_a_stop_while_starting_abandons_the_start(monkeypatch) -> None:
    """The owner's ruling W2, for the dispatcher: one still starting (its database not answering) stops at once."""
    requested = asyncio.Event()
    parts = Parts(monkeypatch, requested)

    async def unanswered(*args: object) -> object:
        requested.set()
        await asyncio.Event().wait()
        raise AssertionError("never answered")

    monkeypatch.setattr(main, "startup", unanswered)
    await asyncio.wait_for(main.run(settings(), stop_requested=requested), 10)
    assert parts.events == ["disposed"]


async def test_a_stopping_admission_worker_lets_a_tick_in_hand_finish() -> None:
    """The owner's ruling D2: a tick being admitted when the dispatcher stops gets 5 seconds, inside Compose's 15 (the
    cycle in hand ends first): admitted, rather than cancelled and retried. (A server of its own: the worker only is
    made, never run.)"""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        worker = main.admission_worker(env.client, None, KEYS)  # type: ignore[arg-type]
        assert worker.config()["graceful_shutdown_timeout"] == timedelta(seconds=5)
