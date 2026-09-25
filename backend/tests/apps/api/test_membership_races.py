# SPDX-License-Identifier: Apache-2.0
"""An actor authorized by require() can lose that authority before the tenant lock; mutations must re-check."""

import asyncio

import pytest
from sqlalchemy import text

from dewpoint.core.auth.users import create_user
from dewpoint.core.tenancy import service
from tests.apps.api.helpers import PW, member_client, session_client


@pytest.fixture
def pause_next_lock(monkeypatch):
    """Pause the next membership mutation right before it takes the tenant lock (after require() ran)."""
    real = service._lock_tenant
    reached, release = asyncio.Event(), asyncio.Event()
    state = {"armed": True}

    async def paused(s, tenant_id):  # type: ignore[no-untyped-def]
        if state["armed"]:
            state["armed"] = False
            reached.set()
            await release.wait()
        await real(s, tenant_id)

    monkeypatch.setattr(service, "_lock_tenant", paused)
    return reached, release


async def _is_member(owner_sessionmaker, tenant_id, email: str) -> bool:  # type: ignore[no-untyped-def]
    async with owner_sessionmaker() as s:
        row = await s.execute(
            text(
                "select 1 from memberships m join users u on u.id = m.user_id where m.tenant_id = :t and u.email = :e"
            ),
            {"t": tenant_id, "e": email},
        )
        return row.first() is not None


async def test_removed_owner_cannot_grant_ownership(app, owner_sessionmaker, api_settings, pause_next_lock) -> None:
    reached, release = pause_next_lock
    a, tid = await session_client(app, owner_sessionmaker, api_settings, "owner")
    b, b_id = await member_client(app, owner_sessionmaker, api_settings, tid, "owner")
    async with owner_sessionmaker() as s, s.begin():
        await create_user(s, email="newcomer@corp.test", password=PW)
    async with a, b:
        grant = asyncio.create_task(
            b.post(f"/api/v1/t/{tid}/members", json={"email": "newcomer@corp.test", "role": "owner"})
        )
        try:
            await asyncio.wait_for(reached.wait(), 10)  # B passed require() as owner, now paused before the lock
            removed = await a.delete(f"/api/v1/t/{tid}/members/{b_id}")
        finally:
            release.set()
            r = await asyncio.wait_for(grant, 10)
    assert removed.status_code == 204
    assert r.status_code == 403 and r.json() == {"error": "forbidden"}
    assert not await _is_member(owner_sessionmaker, tid, "newcomer@corp.test")


async def test_demoted_admin_cannot_change_roles(app, owner_sessionmaker, api_settings, pause_next_lock) -> None:
    reached, release = pause_next_lock
    a, tid = await session_client(app, owner_sessionmaker, api_settings, "owner")
    b, b_id = await member_client(app, owner_sessionmaker, api_settings, tid, "admin")
    _, target_id = await member_client(app, owner_sessionmaker, api_settings, tid, "viewer")
    async with a, b:
        change = asyncio.create_task(b.patch(f"/api/v1/t/{tid}/members/{target_id}", json={"role": "editor"}))
        try:
            await asyncio.wait_for(reached.wait(), 10)
            demoted = await a.patch(f"/api/v1/t/{tid}/members/{b_id}", json={"role": "viewer"})
        finally:
            release.set()
            r = await asyncio.wait_for(change, 10)
    assert demoted.status_code == 200
    assert r.status_code == 403 and r.json() == {"error": "forbidden"}
    async with owner_sessionmaker() as s:
        role = (await s.execute(text("select role from memberships where user_id = :u"), {"u": target_id})).scalar_one()
    assert role == "viewer"
