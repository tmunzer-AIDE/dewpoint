# SPDX-License-Identifier: Apache-2.0
import threading
import uuid
from typing import Any

import pytest
from sqlalchemy import text

import dewpoint
from dewpoint.apps import workflow_ops
from dewpoint.core.auth.users import create_user
from dewpoint.core.db import tenant_scope
from dewpoint.core.http import TenantContext
from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.core.workflows import service
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.graph.model import version_hash
from dewpoint.engine.runtime.build import build_id
from tests.apps.api.helpers import PW
from tests.support.graphs import G, cel, nid, ref
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


async def test_a_published_version_carries_the_abi_of_this_build(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """Spec §7: a version is stamped and hashed with the ABI this build's id names, the one its runs' histories are
    recorded and replayed under."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    v = (await publish(api_sessionmaker, ctx, wf_id, api_settings)).version
    assert v is not None
    abi = int(build_id(dewpoint.__version__).rpartition("+abi")[2])
    assert v.engine_abi == abi
    assert v.version_hash == version_hash(
        graph_hash=v.graph_hash,
        subflow_pins={},
        failure_handler_version_id=None,
        cel_profile=v.cel_profile,
        engine_abi=abi,
    )


async def test_a_published_version_pins_its_open_iteration_cap_and_its_loop_depth(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """Engine 2b spec §5.3: publish computes them from the version's structure and stores them, so a later change of a
    constant can't change how a pinned run schedules; the worker loads them with the version."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    looped = G().node("o", "flow.loop@1", {"items": [1]}).node("i", "flow.loop@1", {"items": [1]})
    looped.node("e", "testkit.echo@1", {"value": 1}).edge("o", "i", "body").edge("i", "e", "body")
    wf_id = await create(api_sessionmaker, ctx, looped.data())
    out = await publish(api_sessionmaker, ctx, wf_id, api_settings)
    assert out.errors == [] and out.version is not None
    assert (out.version.open_scopes_cap, out.version.loop_depth) == (100, 2)


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


async def published_by_the_previous_build(
    api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """A version as the build before this one published it: stamped with the ABI before this build's."""
    with monkeypatch.context() as m:
        m.setattr(workflow_ops, "ENGINE_ABI", ENGINE_ABI - 1)
        version = (await publish(api_sessionmaker, ctx, wf_id, settings)).version
    assert version is not None and version.engine_abi == ENGINE_ABI - 1
    return version


async def test_publish_refuses_to_pin_a_sub_flow_or_failure_handler_of_another_abi(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, monkeypatch
) -> None:
    """Spec §7: a version runs only on a build of its engine ABI. Publishing a parent again on its own, while a
    workflow it runs still has an older ABI's version, would leave it running that version: refused, until that
    workflow is published again."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
    old = await published_by_the_previous_build(api_sessionmaker, ctx, child, api_settings, monkeypatch)
    handled = G().node("a", "testkit.echo@1", {"value": 1})
    handled.settings["failure_handler"] = str(child)
    reason = (
        f"Version {old.id}, a sub-flow or failure handler this workflow would run, was published for engine ABI "
        f"{ENGINE_ABI - 1}, and this build publishes ABI {ENGINE_ABI}."
    )
    parents = [
        await create(api_sessionmaker, ctx, draft, name=name)
        for name, draft in (("runs it", runs(child)), ("handles with it", handled.data()))
    ]
    for parent in parents:
        out = await publish(api_sessionmaker, ctx, parent, api_settings)
        assert out.version is None
        assert [(d.code, d.message, d.fix) for d in out.errors] == [
            ("subflow.engine_abi", reason, "Publish that workflow again first.")
        ]
    await save(api_sessionmaker, ctx, child, ECHO_GRAPH)
    assert (await publish(api_sessionmaker, ctx, child, api_settings)).version is not None  # the child, again
    for parent in parents:
        assert (await publish(api_sessionmaker, ctx, parent, api_settings)).version is not None


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


async def test_validation_runs_off_the_event_loop(
    monkeypatch, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    on_loop_thread: list[bool] = []
    real = workflow_ops.validate

    def spy(graph: Any, context: Any) -> Any:
        on_loop_thread.append(threading.current_thread() is threading.main_thread())
        return real(graph, context)

    monkeypatch.setattr(workflow_ops, "validate", spy)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        await workflow_ops.check_draft(s, ctx.tenant_id, ECHO_GRAPH, api_settings)
    assert on_loop_thread == [False]


async def test_publish_stores_every_expression_with_its_class(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    graph = G().node("a", "testkit.echo@1", {"value": cel("[1, 2, 3].filter(x, x > 1)")}).data()
    wf_id = await create(api_sessionmaker, ctx, graph)
    out = await publish(api_sessionmaker, ctx, wf_id, api_settings)
    assert out.errors == [] and out.version is not None
    [stored] = out.version.expressions
    record = ExpressionRecord.from_json(stored)
    assert (record.node, record.field, record.expr, record.mode) == (
        str(nid("a")),
        "/value",
        "[1, 2, 3].filter(x, x > 1)",
        "local",
    )
    assert record.iterations == 3 and record.to_json() == stored


async def test_a_writer_sees_what_was_committed_while_its_session_held_the_workflow(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """A session may hold the `Workflow` from before its lock: the writer must act on what's committed, not on that
    copy. Here another transaction saves a draft and disables the workflow in between."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
    assert (await publish(api_sessionmaker, ctx, wf_id, api_settings)).version is not None
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        held = await service.get_workflow(s, ctx.tenant_id, wf_id)  # the session holds it while this reference lives
        assert held is not None and held.enabled
        seen = held.draft_revision
        await save(api_sessionmaker, ctx, wf_id, SENSITIVE_GRAPH)
        await update(api_sessionmaker, ctx, wf_id, enabled=False)
        wf = await service.get_workflow(s, ctx.tenant_id, wf_id, for_update=True)
        assert wf is not None
        assert (wf.draft_revision, wf.draft, wf.enabled) == (seen + 1, SENSITIVE_GRAPH, False)
        with pytest.raises(service.DraftConflictError):  # the draft this session saw is no longer the draft
            await workflow_ops.publish(s, ctx, wf, expected_revision=seen, settings=api_settings)
        await workflow_ops.update(s, ctx, wf, name=None, enabled=True)  # an enable, not a no-op
    assert await is_enabled(api_sessionmaker, ctx, wf_id)


async def test_publish_stores_the_tainted_sites_and_the_output_taint_a_parent_then_reads(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """Engine 2b spec §4.1: the version records which value sites are tainted, and its outputs' taint map; a parent's
    analysis reads its pinned sub-flow's map."""
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    token_schema = {
        "type": "object",
        "properties": {"token": {"type": "string", "x-sensitive": True}},
        "required": ["token"],
        "additionalProperties": False,
    }
    child_graph = G().node("a", "testkit.echo@1", {"value": ref("trigger.token")})
    child_graph.settings = {"input_schema": token_schema, "outputs": {"secret": ref("trigger.token"), "plain": 1}}
    child = await create(api_sessionmaker, ctx, child_graph.data(), name="child")
    child_v = (await publish(api_sessionmaker, ctx, child, api_settings)).version
    assert child_v is not None
    assert child_v.tainted_sites == [
        {"node": None, "field": "/settings/outputs/secret"},  # the workflow's outputs first
        {"node": str(nid("a")), "field": "/value"},
    ]
    assert child_v.output_taint == {"secret": True, "plain": False}
    parent_graph = G().node(
        "r", "flow.run_workflow@1", {"workflow_id": str(child), "input": {"token": ref("trigger.token")}}
    )
    parent_graph.node("e", "testkit.echo@1", {"value": ref("steps.r.output.secret")}).edge("r", "e")
    parent_graph.node("p", "testkit.echo@1", {"value": ref("steps.r.output.plain")}).edge("r", "p")
    parent_graph.settings = {"input_schema": token_schema}
    parent = await create(api_sessionmaker, ctx, parent_graph.data(), name="parent")
    out = await publish(api_sessionmaker, ctx, parent, api_settings)
    assert out.errors == [] and out.version is not None
    sites = {(site["node"], site["field"]) for site in out.version.tainted_sites}
    assert (str(nid("e")), "/value") in sites and (str(nid("p")), "/value") not in sites


DECLASSIFYING = {
    "input_schema": {
        "type": "object",
        "properties": {"token": {"type": "string", "x-sensitive": True}},
        "required": ["token"],
        "additionalProperties": False,
    },
    "declassify": [{"node": str(nid("c")), "field": "/condition"}],
}


def declassifying_graph() -> dict[str, Any]:
    g = G().node("c", "flow.if@1", {"condition": cel("size(trigger.token) > 8")}).node("a", "testkit.echo@1")
    g.node("b", "testkit.echo@1").edge("c", "a", "true").edge("c", "b", "false")
    g.settings = DECLASSIFYING
    return g.data()


async def test_declassifying_needs_its_permission_and_the_audit_entry_lists_each_site(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
) -> None:
    """Engine 2b spec §4.3: publishing a version that lists declassified sites needs `workflow.declassify` (tenant
    admins and owners); the publish audit entry records every listed site and what it reveals."""
    await sync_test_plugins(admin_sessionmaker)
    editor = await actor(owner_sessionmaker)
    wf_id = await create(api_sessionmaker, editor, declassifying_graph())
    refused = await publish(api_sessionmaker, editor, wf_id, api_settings)
    assert refused.version is None and [(d.code, d.field) for d in refused.errors] == [
        ("declassify.forbidden", "/settings/declassify")
    ]
    admin = TenantContext(tenant_id=editor.tenant_id, user=editor.user, role="admin", session=None)  # type: ignore[arg-type]
    published = await publish(api_sessionmaker, admin, wf_id, api_settings)
    assert published.errors == [] and published.version is not None
    async with owner_sessionmaker() as s:
        details = (
            await s.execute(text("select details from audit_log where action = 'workflow.publish'"))
        ).scalar_one()
    assert details["declassify"] == [{"node": str(nid("c")), "field": "/condition", "reveals": "the branch taken"}]
