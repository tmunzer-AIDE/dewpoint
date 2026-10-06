# SPDX-License-Identifier: Apache-2.0
"""An erasure records what each stage finds as items, however many (the final review's C1): one statement binding every
row's values passes the database driver's limit of 32,767 arguments past about 5,460 rows (six values a row), and the
stage would fail on every pass."""

import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.apps.erasure import bound, stages
from tests.apps.erasure.support import erasing
from tests.support.workflows import seed_workflow

MANY = 6_000  # past one statement's limit at six values a row


async def _items(owner: Any, tenant: uuid.UUID) -> int:
    async with owner() as s:
        found = await s.execute(text("select count(*) from tenant_erasure_items where tenant_id = :t"), {"t": tenant})
        return int(found.scalar_one())


async def test_a_stage_records_more_items_than_one_statement_can_bind(
    owner_sessionmaker, api_sessionmaker, retention_sessionmaker
) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await erasing(api_sessionmaker, tenant)
    ctx = stages.Context(retention_sessionmaker, client=None, tenant_id=tenant)  # type: ignore[arg-type]  # no Temporal
    async with stages._scoped(ctx) as s:
        await stages._found(s, ctx, stages.Stage.EXECUTIONS, "execution",
                            [(f"t:{tenant}:run:{i}", None) for i in range(MANY)], "runs")  # fmt: skip
    assert await _items(owner_sessionmaker, tenant) == MANY


async def test_an_erasure_reopens_for_more_executions_than_one_statement_can_bind(
    owner_sessionmaker, api_sessionmaker, retention_sessionmaker
) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await erasing(api_sessionmaker, tenant)
    shown = bound.Found(executions=[(f"t:{tenant}:run:{i}", f"r{i}") for i in range(MANY)])
    await bound.reopen(retention_sessionmaker, tenant, shown, during="final_check")
    assert await _items(owner_sessionmaker, tenant) == MANY
