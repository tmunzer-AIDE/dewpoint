# SPDX-License-Identifier: Apache-2.0
"""The tables sub-project 2b-4a added (the final review's M3; engine 2b spec §14). Those holding a tenant's rows force
row-level security scoped to that tenant: an erasure's record, its items and known executions, a sweep's counts per
tenant, and an audit chain's checkpoints. The retention process reads across tenants only through functions that return
ids or a status. The platform's own tables hold no tenant's rows and have no policies: their grants are their
boundary."""

import uuid
from typing import Any

from sqlalchemy import text

from dewpoint.core.db import tenant_scope
from tests.support.workflows import seed_workflow

SCOPED = {  # table: the column naming its tenant
    "tenant_erasures": "tenant_id", "tenant_erasure_items": "tenant_id", "tenant_erasure_known": "tenant_id",
    "retention_sweep_tenants": "tenant_id", "audit_checkpoints": "scope",
}  # fmt: skip
PLATFORM = ("retention_sweeps", "run_duration_limits", "tick_cutover", "namespace_boundaries")
READS = {  # what each role reads of them
    "api": ("tenant_erasures", "tenant_erasure_items", "tenant_erasure_known", "audit_checkpoints"),
    "retention": ("tenant_erasures", "tenant_erasure_items", "tenant_erasure_known", "retention_sweep_tenants"),
}


async def test_the_new_tables_holding_a_tenants_rows_force_row_level_security(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        query = text("select relname from pg_class where relname = any(:t) and relrowsecurity and relforcerowsecurity")
        forced = set((await s.execute(query, {"t": list(SCOPED)})).scalars())
    assert forced == set(SCOPED)


async def test_the_platform_tables_hold_no_tenants_rows(owner_sessionmaker) -> None:
    """The documented exceptions: no column names a tenant, so there's nothing to scope."""
    async with owner_sessionmaker() as s:
        query = text("select table_name, column_name from information_schema.columns where table_name = any(:t)")
        columns = (await s.execute(query, {"t": list(PLATFORM)})).all()
    assert {table for table, _ in columns} == set(PLATFORM)
    assert [c for c in columns if c.column_name in ("tenant_id", "scope")] == []


async def _rows(owner: Any) -> uuid.UUID:
    """A tenant being erased, with a row in each of the tables."""
    tenant, workflow, _ = await seed_workflow(owner)
    async with owner() as s, s.begin():
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": tenant})
        await s.execute(text("insert into tenant_erasures (tenant_id, requested_by) values (:t, :u)"),
                        {"t": tenant, "u": uuid.uuid4()})  # fmt: skip
        await s.execute(text("insert into tenant_erasure_items (tenant_id, step, kind, workflow_id, source) "
                             "values (:t, 50, 'run', :w, 'runs')"), {"t": tenant, "w": str(workflow)})  # fmt: skip
        await s.execute(text("insert into tenant_erasure_known (tenant_id, kind, workflow_id) "
                             "values (:t, 'execution', :w)"), {"t": tenant, "w": str(workflow)})  # fmt: skip
        sweep = (await s.execute(text("insert into retention_sweeps default values returning id"))).scalar_one()
        await s.execute(text("insert into retention_sweep_tenants (sweep_id, tenant_id) values (:s, :t)"),
                        {"s": sweep, "t": tenant})  # fmt: skip
        await s.execute(text("insert into audit_checkpoints (scope, seq, hash, sink, sink_ref) "
                             "values (:t, 1, '\\x00', 'file', 'r')"), {"t": str(tenant)})  # fmt: skip
    return tenant


async def test_each_role_reads_only_its_tenants_lifecycle_rows(
    owner_sessionmaker, api_sessionmaker, retention_sessionmaker
) -> None:
    a, b = await _rows(owner_sessionmaker), await _rows(owner_sessionmaker)
    for role, maker in (("api", api_sessionmaker), ("retention", retention_sessionmaker)):
        for table in READS[role]:
            column = SCOPED[table]
            async with maker() as s, s.begin():
                unscoped = (await s.execute(text(f"select count(*) from {table}"))).scalar_one()  # noqa: S608
                await tenant_scope(s, a)
                seen = set((await s.execute(text(f"select {column}::text from {table}"))).scalars())  # noqa: S608
            assert (role, table, unscoped, seen) == (role, table, 0, {str(a)})
    assert b != a


async def test_a_role_scoped_to_one_tenant_writes_none_of_anothers(owner_sessionmaker, retention_sessionmaker) -> None:
    a, b = await _rows(owner_sessionmaker), await _rows(owner_sessionmaker)
    async with retention_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        moved = await s.execute(text("update tenant_erasures set attempts = attempts + 1 where tenant_id = :t"),
                                {"t": b})  # fmt: skip
        counted = await s.execute(text("update retention_sweep_tenants set runs = runs + 1 where tenant_id = :t"),
                                  {"t": b})  # fmt: skip
    assert (moved.rowcount, counted.rowcount) == (0, 0)  # type: ignore[attr-defined]


async def test_the_retention_process_reads_across_tenants_only_ids_and_a_status(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    a, b = await _rows(owner_sessionmaker), await _rows(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenant_erasures set completed_at = now() where tenant_id = :b"), {"b": b})
        sweep = (await s.execute(text("select max(sweep_id) from retention_sweep_tenants"))).scalar_one()
        await s.execute(text("update retention_sweep_tenants set audited_at = now(), runs = 3 where tenant_id = :b"),
                        {"b": b})  # fmt: skip
        await s.execute(text("update retention_sweep_tenants set sweep_id = :s"), {"s": sweep})
    async with retention_sessionmaker() as s:
        due = list((await s.execute(text("select erasures_due()"))).scalars())
        completed = list((await s.execute(text("select erasures_completed()"))).scalars())
        unfinished = (await s.execute(text("select erasures_unfinished()"))).scalar_one()
        unaudited = list((await s.execute(text("select retention_sweep_unaudited(:s)"), {"s": sweep})).scalars())
        summary = (await s.execute(text("select * from retention_sweep_summary(:s)"), {"s": sweep})).one()
    assert (due, completed, unfinished, unaudited) == ([a], [b], 1, [a])
    assert tuple(summary) == (1, 1, False, 0.0)


async def test_an_old_sweeps_record_still_takes_its_tenants_counts_with_it(
    owner_sessionmaker, retention_sessionmaker
) -> None:
    """The key's cascade runs as the table's owner: neither the tenant scope nor the erasure's stage gate holds it."""
    tenant, _, _ = await seed_workflow(owner_sessionmaker)  # active: ordinary retention, no erasure
    async with owner_sessionmaker() as s, s.begin():
        sweep = (await s.execute(text("insert into retention_sweeps (started_at, ended_at, succeeded) values "
                                      "(now() - interval '40 days', now() - interval '40 days', true) returning id"))
                 ).scalar_one()  # fmt: skip
        await s.execute(text("insert into retention_sweep_tenants (sweep_id, tenant_id, audited_at) "
                             "values (:s, :t, now())"), {"s": sweep, "t": tenant})  # fmt: skip
    async with retention_sessionmaker() as s, s.begin():
        await s.execute(text("delete from retention_sweeps where ended_at < now() - interval '30 days'"))
    async with owner_sessionmaker() as s:
        left = (await s.execute(text("select count(*) from retention_sweep_tenants"))).scalar_one()
    assert left == 0
