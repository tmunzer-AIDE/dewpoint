# SPDX-License-Identifier: Apache-2.0
"""The starting transaction (engine 2b spec §7.3, §7.8, §2.3–2.5; engine-core §4.5): one due request, locked with
SKIP LOCKED under the gate's and its tenant's shared locks, becomes `starting` only when every critical condition holds;
its slot is reserved and its run's row written in the same transaction. A condition that doesn't hold leaves it
queued, no attempt counted: waiting isn't failing. A frozen version the current build can't run, or whose closure was
retired, is cancelled explicitly, never started."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import dispatch
from dewpoint.apps.dispatcher.observe import Build
from dewpoint.core.plugins import lifecycle
from dewpoint.engine import ENGINE_ABI
from tests.apps.dispatcher.support import begin, state, workers
from tests.apps.test_admission import KEYS, TOKEN, admit
from tests.apps.test_workflow_ops import update
from tests.support.keys import FixtureKeys

pytestmark = pytest.mark.usefixtures("development_deployment")


async def test_a_due_request_becomes_starting_with_its_slot_and_its_runs_row(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, request = queued
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(starting, dispatch.Starting)
    start = starting.start
    assert (start.tenant_id, start.run_id, start.version_id) == (
        str(ctx.tenant_id), str(request.id), str(request.workflow_version_id),
    )  # fmt: skip
    assert set(start.trigger) == {"token", "site"} and TOKEN not in str(start.trigger)  # the envelope, with a handle
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("starting", None, 0) and after["slot"] == 1
    assert after["run"][:2] == ("running", None) and after["run"][2] == request.queued_at  # queued, not yet started


async def test_a_runs_row_from_an_earlier_attempt_is_reused(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
    async with owner_sessionmaker() as s, s.begin():  # a confirmed refusal put it back in the queue (§7.8)
        await s.execute(
            text("update run_requests set status = 'queued', attempts = 1 where id = :i"), {"i": request.id}
        )
        await s.execute(text("delete from run_slots"))
    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from runs"))).scalar_one() == 1


@pytest.mark.parametrize("breaks", ["gate_off", "workers_not_ready", "no_slot", "tenant_erasing", "key_unusable"])
async def test_a_condition_that_doesnt_hold_leaves_the_request_queued_without_an_attempt(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, breaks
) -> None:
    ctx, _, request = queued
    keys: Any = KEYS
    async with owner_sessionmaker() as s, s.begin():
        if breaks == "gate_off":  # a production deployment's gate (§2.3); a development one has none
            await s.execute(text("alter table platform_settings disable trigger user"))
            await s.execute(text("update platform_settings set environment = 'production', production_runs = false"))
            await s.execute(text("alter table platform_settings enable trigger user"))
        elif breaks == "workers_not_ready":
            await s.execute(text("update worker_instances set healthy = false"))
        elif breaks == "no_slot":
            await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 1)"),
                            {"t": ctx.tenant_id})  # fmt: skip
            await s.execute(text("insert into run_slots (run_id, tenant_id) values (:r, :t)"),
                            {"r": uuid.uuid4(), "t": ctx.tenant_id})  # fmt: skip
        elif breaks == "tenant_erasing":
            await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": ctx.tenant_id})
    if breaks == "key_unusable":  # the start is sealed with the tenant's key before anything is written (§2.3)
        keys = FixtureKeys(missing={str(ctx.tenant_id)})
    waiting = await begin(dispatch_sessionmaker, request, api_settings, keys=keys)
    assert waiting == dispatch.Waiting(breaks)
    assert await state(owner_sessionmaker, request.id) == {"request": ("queued", None, 0), "run": None, "slot": 0}


async def test_the_platforms_default_limit_holds_without_a_tenant_override(
    queued, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, first = queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update platform_settings set max_concurrent_runs = 1"))
    second = (await admit(api_sessionmaker, ctx, wf, key="k2")).request
    assert isinstance(await begin(dispatch_sessionmaker, first, api_settings), dispatch.Starting)
    assert await begin(dispatch_sessionmaker, second, api_settings) == dispatch.Waiting("no_slot")


async def test_a_frozen_version_the_current_build_cant_run_is_cancelled_at_dispatch(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Engine-core §4.5: `engine_abi_changed`, explicit and audited with both ABIs, never a failure later."""
    ctx, _, request = queued
    other = Build(f"dewpoint-9.9.9+abi{ENGINE_ABI + 1}", ENGINE_ABI + 1)
    await workers(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update worker_instances set build_id = :b"), {"b": other.build_id})
    assert await begin(dispatch_sessionmaker, request, api_settings, build=other) == dispatch.Cancelled(
        "engine_abi_changed"
    )
    assert (await state(owner_sessionmaker, request.id))["request"][:2] == ("cancelled", "engine_abi_changed")
    async with owner_sessionmaker() as s:
        details = (await s.execute(text("select details from audit_log where action = 'run.request.cancel'"))).scalar()
    assert details == {"reason": "engine_abi_changed", "version_abi": ENGINE_ABI, "build_abi": ENGINE_ABI + 1}


async def test_a_starting_request_back_in_the_queue_after_its_closure_was_retired_is_cancelled_not_started(
    queued, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """The owner's M2 condition: a forced retirement leaves a `starting` request alone; if it comes back to the queue
    (a confirmed refusal), dispatch's defensive check cancels it, audited, and the run's row an earlier attempt wrote
    becomes terminal with it (§7.8). Nothing starts."""
    ctx, wf, request = queued
    assert isinstance(await begin(dispatch_sessionmaker, request, api_settings), dispatch.Starting)
    await update(api_sessionmaker, ctx, wf, enabled=False)
    async with admin_sessionmaker() as s, s.begin():
        assert (await lifecycle.retire(s, lifecycle.Entry("node", "testkit.echo@1"), force=True, confirm=True)).applied
    assert (await state(owner_sessionmaker, request.id))["request"][0] == "starting"  # left alone
    async with owner_sessionmaker() as s, s.begin():  # Temporal refused it: back in the queue, its slot released
        await s.execute(
            text("update run_requests set status = 'queued', attempts = 1 where id = :i"), {"i": request.id}
        )
        await s.execute(text("delete from run_slots"))
    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Cancelled("node_type_retired")
    after = await state(owner_sessionmaker, request.id)
    assert after["request"][:2] == ("cancelled", "node_type_retired") and after["slot"] == 0
    assert after["run"][0] == "cancelled"


async def test_a_request_another_dispatcher_holds_is_skipped(queued, dispatch_sessionmaker, api_settings) -> None:
    _, _, request = queued
    async with dispatch_sessionmaker() as s, s.begin():
        await s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(request.tenant_id)})
        await s.execute(text("select 1 from run_requests where id = :i for update"), {"i": request.id})
        assert await begin(dispatch_sessionmaker, request, api_settings) is None
