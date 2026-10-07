# SPDX-License-Identifier: Apache-2.0
"""Every due tenant gets its turn (the whole-branch review): a cycle picks at most `CANDIDATES` tenants, and goes on
from where the last full pick ended, wrapping around, so tenants that can't start (at their limit, waiting on a key)
never keep a runnable tenant from being picked."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps.dispatcher import budget, dispatch
from tests.apps.dispatcher.support import BUILD, state, workers
from tests.apps.test_admission import KEYS, admit, current, published
from tests.apps.test_runs import FakeClient

pytestmark = pytest.mark.usefixtures("development_deployment")


async def at_its_limit(owner: Any, tenant_id: uuid.UUID) -> None:
    """A tenant limited to one run, which it's running."""
    async with owner() as s, s.begin():
        await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 1)"),
                        {"t": tenant_id})  # fmt: skip
        await s.execute(text("insert into run_slots (run_id, tenant_id) values (:r, :t)"),
                        {"r": uuid.uuid4(), "t": tenant_id})  # fmt: skip


async def test_fifty_blocked_tenants_never_starve_a_runnable_one(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    blocked = []
    for _ in range(dispatch.CANDIDATES):  # the oldest due tenants, every one at its limit
        ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
        await at_its_limit(owner_sessionmaker, ctx.tenant_id)
        blocked.append((await admit(api_sessionmaker, ctx, wf)).request)
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    runnable = (await admit(api_sessionmaker, ctx, wf)).request  # the newest due tenant, with a free slot
    client, rotation = FakeClient(), dispatch.Rotation()
    first = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, rotation)
    assert first == {"no_slot": dispatch.CANDIDATES}
    second = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, rotation)
    assert second == {"started": 1}  # on from where the first pick ended
    assert (await state(owner_sessionmaker, runnable.id))["request"][0] == "started"
    assert [(await state(owner_sessionmaker, r.id))["request"][0] for r in blocked[:3]] == ["queued"] * 3
    third = await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, rotation)
    assert third == {"no_slot": dispatch.CANDIDATES}  # wrapped around to the oldest


async def test_a_dispatch_pass_its_budget_stopped_goes_on_next_cycle_from_the_last_request_it_took(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """One request a pass (its soft budget spent at once, the D16 prototype): the oldest due tenant can't start, and
    stays due. The next pass goes on after it, not from the start of the queue, so it never keeps the runnable ones
    waiting."""
    monkeypatch.setattr(budget, "PASS_S", 0.0)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await at_its_limit(owner_sessionmaker, ctx.tenant_id)
    await admit(api_sessionmaker, ctx, wf)
    for _ in range(2):
        ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
        await admit(api_sessionmaker, ctx, wf)
    client, rotation = FakeClient(), dispatch.Rotation()
    passes = [await dispatch.dispatch_once(dispatch_sessionmaker, client, KEYS, api_settings, BUILD, rotation)
              for _ in range(3)]  # fmt: skip
    assert passes == [{"no_slot": 1, "deferred": 2}, {"started": 1, "deferred": 1}, {"started": 1}]
