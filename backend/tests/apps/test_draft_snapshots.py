# SPDX-License-Identifier: Apache-2.0
"""A draft frozen for a simulation (B8; the simulation design §6.1, §6.3): its snapshot carries what its version would,
identical drafts share one (described by its first freezing), another engine build freezes its own; a simulation
refuses what can't run and reports what publish would refuse but a simulation never meets."""

import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.apps import workflow_ops
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import TenantContext
from dewpoint.core.models.workflows import DraftSnapshot
from dewpoint.core.plugins import lifecycle
from dewpoint.core.workflows import drafts, service
from dewpoint.engine import ENGINE_ABI
from tests.apps.test_workflow_ops import ECHO, ECHO_GRAPH, actor, create, declassifying_graph, publish, save
from tests.support.graphs import G
from tests.support.registry import sync_test_plugins


async def freeze(
    api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, settings: Any
) -> workflow_ops.Simulatable:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id)
        assert wf is not None
        checked = await workflow_ops.check_draft(s, ctx.tenant_id, wf.draft, settings)
        return await workflow_ops.simulatable(s, ctx, wf, checked)


async def snapshot(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, settings: Any) -> DraftSnapshot:
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id)
        assert wf is not None
        checked = await workflow_ops.check_draft(s, ctx.tenant_id, wf.draft, settings)
        out = await workflow_ops.simulatable(s, ctx, wf, checked)
        assert out.new is not None, out.blocking
        return await drafts.snapshot_for(s, wf, out.new, revision=wf.draft_revision, created_by=ctx.user.id)


async def test_a_draft_is_frozen_as_its_version_would_be(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    s = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
    v = (await publish(api_sessionmaker, ctx, wf_id, api_settings)).version
    assert v is not None
    same = ("graph", "node_refs", "engine_abi", "cel_profile", "subflow_version_ids", "input_schema", "output_schema",
            "vars_schema", "expressions", "tainted_sites", "output_taint", "open_scopes_cap", "loop_depth",
            "closure_workflow_ids", "closure_node_refs", "closure_cel_profiles", "closure_depth", "graph_hash",
            "version_hash", "connection_ids")  # fmt: skip
    assert {f: getattr(s, f) for f in same} == {f: getattr(v, f) for f in same}
    assert (s.closure_version_ids, v.closure_version_ids) == ([], [v.id])  # a snapshot isn't a version: nothing pins it
    assert (s.workflow_id, s.draft_revision, s.created_by) == (wf_id, 1, ctx.user.id)


async def test_identical_drafts_share_one_snapshot_described_by_its_first(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    first = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
    await save(api_sessionmaker, ctx, wf_id, ECHO_GRAPH)  # revision 2, the same graph
    other = TenantContext(tenant_id=ctx.tenant_id, user=ctx.user, role="admin", session=None)  # type: ignore[arg-type]
    again = await snapshot(api_sessionmaker, other, wf_id, api_settings)
    assert (again.id, again.draft_revision) == (first.id, 1)
    await save(api_sessionmaker, ctx, wf_id, G().node("a", "testkit.echo@1", {"value": 2}).data())
    changed = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
    assert changed.id != first.id and changed.draft_revision == 3


async def test_another_engine_build_freezes_a_snapshot_of_its_own(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, monkeypatch
) -> None:
    """`version_hash` covers the engine ABI and the CEL profile: a draft frozen by another build is never reused."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    first = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
    monkeypatch.setattr(workflow_ops, "ENGINE_ABI", ENGINE_ABI + 1)
    later = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
    assert later.id != first.id and (later.engine_abi, first.engine_abi) == (ENGINE_ABI + 1, ENGINE_ABI)


async def test_a_simulation_reports_a_deprecated_type_that_publish_refuses(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """Spec §6.3, step 5: deprecated types are reported, not blocking (a simulation of what runs today)."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.deprecate(s, ECHO, actor_id=None)
    out = await freeze(api_sessionmaker, ctx, wf_id, api_settings)
    assert out.new is not None and out.blocking == []
    assert [d.code for d in out.reported] == ["lifecycle.deprecated"]
    refused = await publish(api_sessionmaker, ctx, wf_id, api_settings)
    assert [d.code for d in refused.errors] == ["lifecycle.deprecated"]


async def test_a_simulation_refuses_a_retired_type_and_an_undeclassifiable_draft(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """Spec §6.3, step 4: what can't run blocks it; `declassify.forbidden` in a simulation's words."""
    await sync_test_plugins(admin_sessionmaker)
    editor = await actor(owner_sessionmaker)
    declassifying = await create(api_sessionmaker, editor, declassifying_graph(), name="d")
    out = await freeze(api_sessionmaker, editor, declassifying, api_settings)
    assert out.new is None and [(d.code, d.field) for d in out.blocking] == [
        ("declassify.forbidden", "/settings/declassify")
    ]
    assert out.blocking[0].message.startswith("Simulating a draft that declassifies sensitive data needs")
    echo = await create(api_sessionmaker, editor, ECHO_GRAPH, name="e")
    async with admin_sessionmaker() as s, s.begin():
        await lifecycle.retire(s, ECHO, force=True, confirm=True)
    out = await freeze(api_sessionmaker, editor, echo, api_settings)
    assert out.new is None and [d.code for d in out.blocking] == ["lifecycle.retired"]


async def test_a_snapshot_is_seen_only_within_its_tenant(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    """Row-level security, forced (§6.1): the API, the dispatcher and the worker read a tenant's snapshots only in its
    scope; the admin's platform read sees them all."""
    await sync_test_plugins(admin_sessionmaker)
    ctx, other = await actor(owner_sessionmaker), await actor(owner_sessionmaker)
    await snapshot(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, ECHO_GRAPH), api_settings)
    async with owner_sessionmaker() as s:
        flags = (await s.execute(text("select relrowsecurity, relforcerowsecurity from pg_class "
                                      "where relname = 'draft_snapshots'"))).one()  # fmt: skip
    assert tuple(flags) == (True, True)
    mine = text("select count(*) from draft_snapshots where tenant_id = :t")
    for maker in (api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker):
        async with maker() as s, s.begin():
            assert (await s.execute(mine, {"t": ctx.tenant_id})).scalar_one() == 0
            await tenant_scope(s, other.tenant_id)
            assert (await s.execute(mine, {"t": ctx.tenant_id})).scalar_one() == 0
        async with maker() as s, s.begin():
            await tenant_scope(s, ctx.tenant_id)
            assert (await s.execute(mine, {"t": ctx.tenant_id})).scalar_one() == 1
    async with admin_sessionmaker() as s, s.begin():
        assert (await s.execute(mine, {"t": ctx.tenant_id})).scalar_one() == 1
