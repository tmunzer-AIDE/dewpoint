# SPDX-License-Identifier: Apache-2.0
"""Admission and dispatch against retirement and the gate (engine 2b spec §2.4, §7.2, §7.3; engine-core §4.5), in
both orders (M5's proofs). Admission and the starting transaction take the closure's lifecycle locks shared, a
retirement takes them exclusively: whichever is first, the other sees what it committed. A request admitted first
holds a normal retirement back and is cancelled by a forced one; one already `starting` survives a forced retirement
for the defensive check; a retirement first refuses admission and cancels a queued request before dispatch sees it,
never deadlocking with a starting transaction that has locked the request. An admission that read the gate on just
before it was turned off queues a request that never starts."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import admission
from dewpoint.apps.dispatcher import dispatch, gate
from dewpoint.core.plugins import lifecycle
from tests.apps.dispatcher.support import begin, state
from tests.apps.test_admission import admit, count, current, published
from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock

pytestmark = pytest.mark.usefixtures("development_deployment")
ECHO = lifecycle.Entry("node", "testkit.echo@1")


@pytest.fixture
async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    return ctx, wf


@pytest.fixture
def pause(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Pause admission (after its locks, before its insert) or the starting transaction (after its lifecycle locks),
    once armed: `pause("admission")` or `pause("dispatch")`."""
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused() -> None:
        reached.set()
        await release.wait()

    def arm(where: str) -> tuple[asyncio.Event, asyncio.Event]:
        if where == "admission":
            monkeypatch.setattr(admission, "_before_insert", paused)
        else:
            monkeypatch.setattr(dispatch, "_after_lifecycle_lock", paused)
        return reached, release

    return arm


async def retire(admin: Any, *, force: bool) -> lifecycle.RetirePreview:
    async with admin() as a, a.begin():
        return await lifecycle.retire(a, ECHO, force=force, confirm=force)


@pytest.mark.parametrize("force", [False, True], ids=["normal", "forced"])
async def test_admission_first_holds_a_retirement_until_its_request_is_committed(
    ready, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, pause, force
) -> None:
    ctx, wf = ready
    reached, release = pause("admission")
    admitting = asyncio.create_task(admit(api_sessionmaker, ctx, wf))
    await asyncio.wait_for(reached.wait(), 10)
    retiring = asyncio.create_task(retire(admin_sessionmaker, force=force))
    await until_someone_waits_for_a_lock(owner_sessionmaker)
    release.set()
    request = (await asyncio.wait_for(admitting, 10)).request
    if not force:
        with pytest.raises(lifecycle.ReferencedError) as refused:
            await asyncio.wait_for(retiring, 10)
        assert [q.request_id for q in refused.value.preview.queued] == [request.id]
        return
    preview = await asyncio.wait_for(retiring, 10)
    assert preview.applied and [q.request_id for q in preview.queued] == [request.id]
    assert (await state(owner_sessionmaker, request.id))["request"][:2] == ("cancelled", "node_type_retired")


@pytest.mark.parametrize("source", ["manual", "schedule"])
async def test_retirement_first_refuses_admission(
    ready, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, source
) -> None:
    """An interactive source is refused; a durable one's refusal is kept as a `refused` request (§2.5)."""
    ctx, wf = ready
    async with admin_sessionmaker() as a, a.begin():
        await lifecycle.lock_exclusive(a, ECHO)
        admitting = asyncio.create_task(admit(api_sessionmaker, ctx, wf, source=source))
        await until_someone_waits_for_a_lock(owner_sessionmaker)
        assert (await lifecycle.retire(a, ECHO, force=True, confirm=True)).applied
    if source == "manual":
        with pytest.raises(admission.AdmissionRefusedError) as refused:
            await asyncio.wait_for(admitting, 10)
        assert refused.value.reason == "node_type_retired"
        assert await count(owner_sessionmaker, "run_requests") == 0
    else:
        request = (await asyncio.wait_for(admitting, 10)).request
        assert (request.status, request.reason) == ("refused", "node_type_retired")


@pytest.mark.parametrize("force", [False, True], ids=["normal", "forced"])
async def test_dispatch_first_holds_a_retirement_until_its_request_is_starting(
    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, pause, force
) -> None:
    _, _, request = queued
    reached, release = pause("dispatch")
    beginning = asyncio.create_task(begin(dispatch_sessionmaker, request, api_settings))
    await asyncio.wait_for(reached.wait(), 10)
    retiring = asyncio.create_task(retire(admin_sessionmaker, force=force))
    await until_someone_waits_for_a_lock(owner_sessionmaker)
    release.set()
    assert isinstance(await asyncio.wait_for(beginning, 10), dispatch.Starting)
    if not force:
        with pytest.raises(lifecycle.ReferencedError) as refused:
            await asyncio.wait_for(retiring, 10)
        assert [(q.request_id, q.status) for q in refused.value.preview.queued] == [(request.id, "starting")]
        return
    assert (await asyncio.wait_for(retiring, 10)).applied
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"  # for the defensive check


async def test_retirement_first_cancels_a_queued_request_without_deadlocking_a_starting_transaction(
    queued, owner_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """The retirement holds the closure's lock when a starting transaction, having locked the request, reaches it: the
    starting transaction waits a cycle, never on the lock, so the retirement can cancel the request it holds."""
    _, _, request = queued
    async with admin_sessionmaker() as a, a.begin():
        await lifecycle.lock_exclusive(a, ECHO)
        beginning = asyncio.create_task(begin(dispatch_sessionmaker, request, api_settings))
        done, _ = await asyncio.wait({beginning}, timeout=3)
        assert done and beginning.result() == dispatch.Waiting("retiring")
        preview = await lifecycle.retire(a, ECHO, force=True, confirm=True)
    assert preview.applied and [q.request_id for q in preview.queued] == [request.id]
    assert (await state(owner_sessionmaker, request.id))["request"][:2] == ("cancelled", "node_type_retired")
    assert await begin(dispatch_sessionmaker, request, api_settings) is None  # nothing left to start


async def test_an_admission_that_read_the_gate_on_queues_a_request_that_never_starts(
    ready, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, pause
) -> None:
    """§2.4: admission reads the gate without its lock; one in flight when the gate goes off still queues its request,
    and the starting transaction, under the gate's lock, never starts it."""
    from tests.apps.dispatcher.support import workers

    ctx, wf = ready
    await workers(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("alter table platform_settings disable trigger user"))
        await s.execute(text("update platform_settings set environment = 'production', production_runs = true"))
        await s.execute(text("alter table platform_settings enable trigger user"))
    reached, release = pause("admission")
    admitting = asyncio.create_task(admit(api_sessionmaker, ctx, wf))
    await asyncio.wait_for(reached.wait(), 10)
    async with admin_sessionmaker() as a, a.begin():
        assert await gate.disable_production_runs(a, actor_id=None) is True
    release.set()
    request = (await asyncio.wait_for(admitting, 10)).request
    assert request.status == "queued"
    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Waiting("gate_off")
