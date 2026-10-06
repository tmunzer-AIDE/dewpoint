# SPDX-License-Identifier: Apache-2.0
"""The database's own boundary around an erasure's destructive paths (the final review's I2). The API records an
erasure with its tenant and requester only, never its stage. The retention role deletes a tenant's keys, and its other
rows outside ordinary retention, renames its tombstone, and cancels its queued work only once the tenant's erasure has
reached the stage that does so: a stray record, or a bug in the retention process, can't reach them early."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from dewpoint.core.models.erasure import Stage
from tests.core.ingress.support import KEYRING
from tests.core.retention.support import request
from tests.support.workflows import seed_workflow


async def test_the_api_records_an_erasure_with_its_tenant_and_requester_only(
    owner_sessionmaker, api_sessionmaker
) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    async with api_sessionmaker() as s:
        await s.begin()
        with pytest.raises(DBAPIError) as e:
            await s.execute(text("insert into tenant_erasures (tenant_id, requested_by, step) values (:t, :u, 80)"),
                            {"t": tenant, "u": uuid.uuid4()})  # fmt: skip
        assert getattr(e.value.orig, "sqlstate", None) == "42501"  # insufficient privilege
        await s.rollback()


async def _deleted(retention: Any, tenant: uuid.UUID) -> dict[str, int]:
    """What the retention role can delete or rename of the tenant, each in its own rolled-back transaction."""
    statements = {
        "data_keys": "delete from data_keys where tenant_id = :t",
        "workflows": "update workflows set active_version_id = null where tenant_id = :t",
        "connections": "delete from connections where tenant_id = :t",
        "memberships": "delete from memberships where tenant_id = :t",
        "tenants": "update tenants set name = 'Erased tenant' where id = :t",
        "run_requests": "update run_requests set status = 'cancelled', reason = 'tenant_erased', ended_at = now() "
        "where tenant_id = :t and status = 'queued'",
    }
    done: dict[str, int] = {}
    for name, sql in statements.items():
        async with retention() as s:
            await s.begin()
            await tenant_scope(s, tenant)
            done[name] = int(getattr(await s.execute(text(sql), {"t": tenant}), "rowcount", 0))
            await s.rollback()
    return done


async def test_the_retention_role_reaches_a_tenants_keys_and_rows_only_at_its_erasures_stage(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    tenant, workflow, version = await seed_workflow(owner_sessionmaker)
    user = uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        await KEYRING.ensure_key(s, tenant)
        await s.execute(text("insert into users (id, email, password_hash) values (:u, :e, 'x')"),
                        {"u": user, "e": f"{user.hex[:10]}@corp.test"})  # fmt: skip
        await s.execute(text("insert into memberships (tenant_id, user_id, role) values (:t, :u, 'owner')"),
                        {"t": tenant, "u": user})  # fmt: skip
        await s.execute(text("insert into connections (id, tenant_id, type, name, config) "
                             "values (gen_random_uuid(), :t, 'http', 'c', '{}')"), {"t": tenant})  # fmt: skip
    await request(owner_sessionmaker, {"t": tenant, "w": workflow, "v": version, "u": user}, "queued", None)
    none = dict.fromkeys(("data_keys", "workflows", "connections", "memberships", "tenants", "run_requests"), 0)
    assert await _deleted(retention_sessionmaker, tenant) == none  # active: no erasure

    async def at(stage: Stage) -> dict[str, int]:
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("insert into tenant_erasures (tenant_id, requested_by, step) values (:t, :u, :k) "
                                 "on conflict (tenant_id) do update set step = excluded.step"),
                            {"t": tenant, "u": user, "k": int(stage)})  # fmt: skip
        return await _deleted(retention_sessionmaker, tenant)

    assert await at(Stage.RECONCILE) == none
    assert await at(Stage.CANCEL) == {**none, "run_requests": 1}
    assert await at(Stage.KEYS) == {**none, "run_requests": 1, "data_keys": 1}
    assert await at(Stage.SWEEP) == {"data_keys": 1, "workflows": 1, "connections": 1, "memberships": 1, "tenants": 1,
                                     "run_requests": 1}  # fmt: skip
