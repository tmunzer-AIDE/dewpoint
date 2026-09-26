# SPDX-License-Identifier: Apache-2.0
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from dewpoint.apps import workflow_ops
from dewpoint.core.auth.users import create_user
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import TenantContext
from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.core.workflows import service
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from tests.apps.api.helpers import PW
from tests.support.graphs import G, nid, ref
from tests.support.registry import sync_test_plugins

ECHO = Entry("node", "testkit.echo@1")
ECHO_GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()
SENSITIVE_GRAPH = G().node("s", "testkit.sensitive@1").data()


def runs(workflow_id: uuid.UUID) -> dict[str, Any]:
    return G().node("r", "flow.run_workflow@1", {"workflow_id": str(workflow_id)}).data()


async def actor(owner_sessionmaker: Any) -> TenantContext:
    tenant = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        user = await create_user(s, email=f"{uuid.uuid4().hex[:8]}@corp.test", password=PW)
        await s.execute(
            text("insert into tenants(id,name,slug) values (:t,'T',:slug)"), {"t": tenant, "slug": tenant.hex[:12]}
        )
    return TenantContext(tenant_id=tenant, user=user, role="editor", session=None)  # type: ignore[arg-type]


async def create(api_sessionmaker: Any, ctx: TenantContext, draft: dict[str, Any], name: str = "W") -> uuid.UUID:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        return (await service.create_workflow(s, ctx, name=name, draft=draft)).id


async def save(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, draft: dict[str, Any]) -> int:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
        assert wf is not None
        return await service.save_draft(s, wf, expected_revision=wf.draft_revision, draft=draft)


async def publish(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, settings: Any) -> workflow_ops.Published:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
        assert wf is not None
        return await workflow_ops.publish(s, ctx, wf, expected_revision=wf.draft_revision, settings=settings)


async def activate(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, version_id: uuid.UUID) -> list[Any]:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
        version = await service.get_version(s, wf_id, version_id)
        assert wf is not None and version is not None
        return await workflow_ops.activate(s, ctx, wf, version)


async def update(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, **changes: Any) -> list[Any]:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
        assert wf is not None
        return await workflow_ops.update(s, ctx, wf, name=changes.get("name"), enabled=changes.get("enabled"))


async def is_enabled(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID) -> bool:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id)
        assert wf is not None
        return wf.enabled


async def test_publish_creates_an_active_version_with_its_closure(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    out = await publish(api_sessionmaker, ctx, wf_id, api_settings)
    v = out.version
    assert out.errors == [] and v is not None
    assert v.number == 1 and v.node_refs == ["testkit.echo@1"] and v.cel_profile == CURRENT_CEL_PROFILE
    assert v.closure_version_ids == [v.id] and v.closure_workflow_ids == [wf_id] and v.closure_depth == 0
    assert v.closure_node_refs == ["testkit.echo@1"] and v.closure_cel_profiles == [CURRENT_CEL_PROFILE]
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id)
        assert wf is not None and wf.active_version_id == v.id


async def test_publish_refuses_invalid_graphs_and_stale_revisions(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(
        api_sessionmaker, ctx, G().node("a", "testkit.echo@1", {"value": ref("steps.nope.output")}).data()
    )
    out = await publish(api_sessionmaker, ctx, wf_id, api_settings)
    assert out.version is None and [d.code for d in out.errors] == ["ref.unknown_step"]
    with pytest.raises(service.DraftConflictError):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
            assert wf is not None
            await workflow_ops.publish(s, ctx, wf, expected_revision=wf.draft_revision + 1, settings=api_settings)


async def test_subflows_are_pinned_into_the_closure(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    child_v = (await publish(api_sessionmaker, ctx, child, api_settings)).version
    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
    v = (await publish(api_sessionmaker, ctx, parent, api_settings)).version
    assert child_v is not None and v is not None
    assert v.subflow_version_ids == {str(nid("r")): str(child_v.id)}
    assert set(v.closure_version_ids) == {v.id, child_v.id} and v.closure_depth == 1
    assert v.closure_node_refs == ["flow.run_workflow@1", "testkit.echo@1"]


async def test_version_hash_changes_when_a_pinned_subflow_changes(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    await publish(api_sessionmaker, ctx, child, api_settings)
    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
    first = (await publish(api_sessionmaker, ctx, parent, api_settings)).version
    await save(api_sessionmaker, ctx, child, SENSITIVE_GRAPH)
    await publish(api_sessionmaker, ctx, child, api_settings)  # the child's active version changes
    second = (await publish(api_sessionmaker, ctx, parent, api_settings)).version  # same parent graph
    assert first is not None and second is not None
    assert second.graph_hash == first.graph_hash and second.version_hash != first.version_hash
    assert second.subflow_version_ids != first.subflow_version_ids


async def test_cycles_through_subflows_are_refused(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    a = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="a")
    await publish(api_sessionmaker, ctx, a, api_settings)
    b = await create(api_sessionmaker, ctx, runs(a), name="b")
    await publish(api_sessionmaker, ctx, b, api_settings)
    await save(api_sessionmaker, ctx, a, runs(b))  # a would run b, which runs a
    out = await publish(api_sessionmaker, ctx, a, api_settings)
    assert out.version is None and [d.code for d in out.errors] == ["subflow.cycle"]


async def test_deprecated_types_block_publish_even_through_subflows(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    await publish(api_sessionmaker, ctx, child, api_settings)
    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.deprecate(s, ECHO, actor_id=None)
    out = await publish(api_sessionmaker, ctx, parent, api_settings)
    assert out.version is None and [d.code for d in out.errors] == ["lifecycle.deprecated"]


async def test_rollback_to_a_superseded_version(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    v1 = (await publish(api_sessionmaker, ctx, wf, api_settings)).version
    await save(api_sessionmaker, ctx, wf, SENSITIVE_GRAPH)
    v2 = (await publish(api_sessionmaker, ctx, wf, api_settings)).version
    assert v1 is not None and v2 is not None and v2.number == 2
    assert await activate(api_sessionmaker, ctx, wf, v1.id) == []  # superseded, still activatable
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.retire(s, ECHO, force=True, confirm=True)
    assert await activate(api_sessionmaker, ctx, wf, v2.id) == []
    with pytest.raises(workflow_ops.NotActivatableError) as e:
        await activate(api_sessionmaker, ctx, wf, v1.id)
    assert [d.code for d in e.value.errors] == ["lifecycle.retired"]


async def test_retiring_a_subflow_type_blocks_its_parents(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    await publish(api_sessionmaker, ctx, child, api_settings)
    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
    await publish(api_sessionmaker, ctx, parent, api_settings)
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO, force=True)
    assert {r.workflow_id for r in preview.active_refs} == {child, parent}  # parent reaches echo only via child
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.retire(s, ECHO, force=True, confirm=True)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, parent)
        assert wf is not None and wf.active_version_id is not None
        version = await service.get_version(s, parent, wf.active_version_id)
        assert version is not None and await service.blocked_by(s, version) == ["testkit.echo@1"]


async def test_reenabling_rechecks_the_active_closure(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    await publish(api_sessionmaker, ctx, wf, api_settings)
    assert await update(api_sessionmaker, ctx, wf, enabled=False) == []
    async with admin_sessionmaker() as s, s.begin():
        assert (await lifecycle.retire(s, ECHO)).applied  # normal path: the only user is disabled
    with pytest.raises(workflow_ops.NotActivatableError) as e:
        await update(api_sessionmaker, ctx, wf, enabled=True)
    assert [d.code for d in e.value.errors] == ["lifecycle.retired"]
    assert not await is_enabled(api_sessionmaker, ctx, wf)
    assert await update(api_sessionmaker, ctx, wf, name="Renamed") == []  # renaming needs no lifecycle check


async def test_reenabling_warns_about_deprecated_types(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    await publish(api_sessionmaker, ctx, wf, api_settings)
    await update(api_sessionmaker, ctx, wf, enabled=False)
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.deprecate(s, ECHO, actor_id=None)
    warnings = await update(api_sessionmaker, ctx, wf, enabled=True)
    assert [d.code for d in warnings] == ["lifecycle.deprecated"] and await is_enabled(api_sessionmaker, ctx, wf)
