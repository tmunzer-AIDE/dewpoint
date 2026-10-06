# SPDX-License-Identifier: Apache-2.0
"""An erasure's record alone never erases (the final review's I2): the retention process carries one on only for a
tenant being erased, so a record written for an active tenant, by a stray write or a bug, deletes nothing."""

import uuid
from typing import Any

import structlog
from sqlalchemy import text

from dewpoint.apps.erasure import process
from dewpoint.core.models.erasure import Stage
from tests.core.ingress.support import KEYRING
from tests.support.workflows import seed_workflow


async def test_a_record_for_an_active_tenant_is_never_carried_on(owner_sessionmaker, retention_sessionmaker) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await KEYRING.ensure_key(s, tenant)
        await s.execute(text("insert into tenant_erasures (tenant_id, requested_by, step) values (:t, :u, :k)"),
                        {"t": tenant, "u": uuid.uuid4(), "k": int(Stage.KEYS)})  # fmt: skip
    with structlog.testing.capture_logs() as logs:
        await process.advance(retention_sessionmaker, client=None, tenant_id=tenant)  # type: ignore[arg-type]

    async def one(sql: str) -> Any:
        async with owner_sessionmaker() as s:
            return (await s.execute(text(sql), {"t": tenant})).scalar_one()

    keys = await one("select count(*) from data_keys where tenant_id = :t")
    assert (keys, await one("select status from tenants where id = :t")) == (1, "active")
    assert await one("select step from tenant_erasures where tenant_id = :t") == int(Stage.KEYS)
    assert [e["event"] for e in logs if e.get("event") == "erasure_tenant_active"] == ["erasure_tenant_active"]
