# SPDX-License-Identifier: Apache-2.0
"""Publish and activate serialize with retirement through the lifecycle locks (spec §4.5), in either order."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import workflow_ops
from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from tests.apps.test_workflow_ops import ECHO_GRAPH, SENSITIVE_GRAPH, activate, actor, create, publish, save
from tests.support.registry import sync_test_plugins

ECHO = Entry("node", "testkit.echo@1")


async def until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker: Any) -> None:
    for _ in range(200):
        async with owner_sessionmaker() as s:
            waiting = (
                await s.execute(text("select count(*) from pg_locks where locktype = 'advisory' and not granted"))
            ).scalar_one()
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("nobody is waiting for a lifecycle lock")


@pytest.fixture
def pause_after_lock(monkeypatch):  # type: ignore[no-untyped-def]
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(workflow_ops, "_lifecycle_locked", paused)
    return reached, release


async def test_retirement_first_makes_publish_refuse(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    async with admin_sessionmaker() as a:
        async with a.begin():
            await lifecycle.lock_exclusive(a, ECHO)
            publishing = asyncio.create_task(publish(api_sessionmaker, ctx, wf, api_settings))
            await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
            assert (await lifecycle.retire(a, ECHO)).applied
    out = await asyncio.wait_for(publishing, 10)
    assert out.version is None and [d.code for d in out.errors] == ["lifecycle.retired"]


async def test_publish_first_blocks_normal_retirement(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, pause_after_lock
) -> None:
    reached, release = pause_after_lock
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    publishing = asyncio.create_task(publish(api_sessionmaker, ctx, wf, api_settings))
    await asyncio.wait_for(reached.wait(), 10)

    async def retire() -> lifecycle.RetirePreview:
        async with admin_sessionmaker() as a, a.begin():
            return await lifecycle.retire(a, ECHO)

    retiring = asyncio.create_task(retire())
    await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
    release.set()
    assert (await asyncio.wait_for(publishing, 10)).version is not None
    with pytest.raises(lifecycle.ReferencedError) as e:
        await asyncio.wait_for(retiring, 10)
    assert [r.workflow_id for r in e.value.preview.active_refs] == [wf]


async def test_publish_first_is_included_in_a_forced_retirement(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, pause_after_lock
) -> None:
    reached, release = pause_after_lock
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    publishing = asyncio.create_task(publish(api_sessionmaker, ctx, wf, api_settings))
    await asyncio.wait_for(reached.wait(), 10)

    async def retire() -> lifecycle.RetirePreview:
        async with admin_sessionmaker() as a, a.begin():
            return await lifecycle.retire(a, ECHO, force=True, confirm=True)

    retiring = asyncio.create_task(retire())
    await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
    release.set()
    assert (await asyncio.wait_for(publishing, 10)).version is not None
    preview = await asyncio.wait_for(retiring, 10)
    assert preview.applied and [r.workflow_id for r in preview.active_refs] == [wf]
    async with owner_sessionmaker() as s:
        tenants = (
            (
                await s.execute(
                    text("select tenant_id from audit_log where action = 'lifecycle.retire' and tenant_id is not null")
                )
            )
            .scalars()
            .all()
        )
    assert tenants == [ctx.tenant_id]


async def test_retirement_first_makes_activate_refuse(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    v1 = (await publish(api_sessionmaker, ctx, wf, api_settings)).version
    await save(api_sessionmaker, ctx, wf, SENSITIVE_GRAPH)
    await publish(api_sessionmaker, ctx, wf, api_settings)  # v2 is active and doesn't use echo
    assert v1 is not None
    async with admin_sessionmaker() as a:
        async with a.begin():
            await lifecycle.lock_exclusive(a, ECHO)
            activating = asyncio.create_task(activate(api_sessionmaker, ctx, wf, v1.id))
            await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
            assert (await lifecycle.retire(a, ECHO)).applied  # nothing active uses echo: normal path
    with pytest.raises(workflow_ops.NotActivatableError):
        await asyncio.wait_for(activating, 10)
