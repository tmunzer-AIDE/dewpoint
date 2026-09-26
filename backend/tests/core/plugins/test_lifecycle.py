# SPDX-License-Identifier: Apache-2.0
import pytest
from sqlalchemy import text

from dewpoint.core.plugins import lifecycle
from dewpoint.core.plugins.lifecycle import Entry
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from tests.support.registry import sync_test_plugins
from tests.support.workflows import seed_workflow

ECHO = Entry("node", "testkit.echo@1")


async def test_states_and_entries(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    missing, profile = Entry("node", "testkit.nope@1"), Entry("cel", CURRENT_CEL_PROFILE)
    async with admin_sessionmaker() as s:
        assert await lifecycle.states(s, [ECHO, missing, profile]) == {
            ECHO: "active",
            missing: "missing",
            profile: "active",
        }
    assert lifecycle.entries_for(["b@1", "a@1", "a@1"], ["p"]) == [
        Entry("cel", "p"),
        Entry("node", "a@1"),
        Entry("node", "b@1"),
    ]


async def test_deprecate_then_retire_when_unused(admin_sessionmaker, owner_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        assert await lifecycle.deprecate(s, ECHO, actor_id=None) == "deprecated"
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO)
    assert preview.applied and preview.active_refs == ()
    async with owner_sessionmaker() as s:
        actions = (
            (
                await s.execute(
                    text("select action from audit_log where target_id = 'testkit.echo@1' order by created_at")
                )
            )
            .scalars()
            .all()
        )
    assert actions == ["lifecycle.deprecate", "lifecycle.retire"]


async def test_active_workflows_block_normal_retirement(admin_sessionmaker, owner_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    _, wf, _ = await seed_workflow(owner_sessionmaker)
    with pytest.raises(lifecycle.ReferencedError) as e:
        async with admin_sessionmaker() as s, s.begin():
            await lifecycle.retire(s, ECHO)
    assert [r.workflow_id for r in e.value.preview.active_refs] == [wf]


async def test_disabled_and_superseded_workflows_do_not_block(admin_sessionmaker, owner_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    _, disabled, disabled_v = await seed_workflow(owner_sessionmaker, enabled=False)
    _, superseded, superseded_v = await seed_workflow(owner_sessionmaker, active=False)
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO)
    assert preview.applied and preview.active_refs == ()
    affected = {(v.workflow_id, v.version_id, v.active, v.enabled) for v in preview.affected}
    assert affected == {(disabled, disabled_v, True, False), (superseded, superseded_v, False, True)}


async def test_forced_retirement_previews_then_applies(admin_sessionmaker, owner_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)
    tenant, wf, _ = await seed_workflow(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO, force=True)
    assert not preview.applied and [r.workflow_id for r in preview.active_refs] == [wf]
    assert [(v.tenant_id, v.workflow_id, v.version_number) for v in preview.affected] == [(tenant, wf, 1)]
    async with admin_sessionmaker() as s:
        assert (await lifecycle.states(s, [ECHO]))[ECHO] == "active"
    async with admin_sessionmaker() as s, s.begin():
        preview = await lifecycle.retire(s, ECHO, force=True, confirm=True)
    assert preview.applied
    async with owner_sessionmaker() as s:
        rows = (
            await s.execute(
                text("select tenant_id, details from audit_log where action = 'lifecycle.retire' order by created_at")
            )
        ).all()
    assert [r.tenant_id for r in rows] == [None, tenant]
    assert rows[1].details == {"forced": True, "workflows": [str(wf)]}


async def test_retirement_requires_read_committed(admin_sessionmaker) -> None:
    async with admin_sessionmaker() as s:
        await s.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        with pytest.raises(lifecycle.IsolationError):
            await lifecycle.retire(s, Entry("cel", CURRENT_CEL_PROFILE))
        await s.rollback()
