# SPDX-License-Identifier: Apache-2.0
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from dewpoint.core.models.workflows import Workflow, WorkflowVersion
from tests.support.workflows import seed_workflow


async def test_workflows_and_versions_are_tenant_scoped(owner_sessionmaker, api_sessionmaker) -> None:
    a, wf, v = await seed_workflow(owner_sessionmaker)
    b, _, _ = await seed_workflow(owner_sessionmaker, name="Other")
    async with api_sessionmaker() as s, s.begin():
        assert (await s.execute(select(Workflow))).scalars().all() == []  # no tenant context
        await tenant_scope(s, a)
        assert [w.id for w in (await s.execute(select(Workflow))).scalars()] == [wf]
        assert [x.id for x in (await s.execute(select(WorkflowVersion))).scalars()] == [v]
        await tenant_scope(s, b)
        assert v not in [x.id for x in (await s.execute(select(WorkflowVersion))).scalars()]


async def test_versions_are_immutable_even_for_the_owner(owner_sessionmaker) -> None:
    _, _, v = await seed_workflow(owner_sessionmaker)
    for stmt in (
        "update workflow_versions set number = 2 where id = :v",
        "delete from workflow_versions where id = :v",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            async with owner_sessionmaker() as s, s.begin():
                await s.execute(text(stmt), {"v": v})


async def test_api_role_cannot_delete_versions_or_workflows(owner_sessionmaker, api_sessionmaker) -> None:
    tenant, wf, v = await seed_workflow(owner_sessionmaker)
    for stmt, target in (
        ("delete from workflow_versions where id = :x", v),
        ("delete from workflows where id = :x", wf),
    ):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, tenant)
                await s.execute(text(stmt), {"x": target})


async def test_admin_reads_across_tenants_but_cannot_write(owner_sessionmaker, admin_sessionmaker) -> None:
    _, wf, _ = await seed_workflow(owner_sessionmaker)
    async with admin_sessionmaker() as s, s.begin():
        assert [w.id for w in (await s.execute(select(Workflow))).scalars()] == [wf]
    with pytest.raises(DBAPIError, match="permission denied"):
        async with admin_sessionmaker() as s, s.begin():
            await s.execute(text("update workflows set enabled = false where id = :w"), {"w": wf})


async def test_active_version_must_belong_to_its_workflow(owner_sessionmaker) -> None:
    tenant, _, v = await seed_workflow(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="workflows_active_version_fk"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(
                text("insert into workflows(id,tenant_id,name,draft,active_version_id) values (:o,:t,'Other','{}',:v)"),
                {"o": uuid.uuid4(), "t": tenant, "v": v},
            )
