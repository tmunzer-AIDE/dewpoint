# SPDX-License-Identifier: Apache-2.0
"""The erasure's insert fence (migration 0040; 2b-4a M4, "final absence"): once an erasure reaches stage 60, its
executions being deleted, no row of the tenant is inserted into any table holding tenant data, by any role, whatever the
writer, the ones the outline's fence list never named included (a worker's straggling projection, the evidence pass, a
tick's firing record, the keyring's first-use key). Entering stage 60 takes the tenant's lifecycle lock exclusively, so
an insert in flight either commits before it or sees it."""

import asyncio
import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.crypto.kek import Kek, KekSet
from dewpoint.core.crypto.keyring import Keyring
from dewpoint.core.db import tenant_scope
from tests.support.workflows import seed_workflow

# What holds a tenant id and isn't fenced, each for its reason: the audit log (kept under the platform's audit policy),
# the retention sweep's counts (the erasure's sweep deletes them once audited), and the erasure's own record.
UNFENCED = {"audit_log", "retention_sweep_tenants", "tenant_erasures", "tenant_erasure_items", "tenant_erasure_known"}
FENCED_TABLES = (
    "claim_grants", "connections", "csv_mappings", "csv_uploads", "data_keys", "egress_allowlist", "execution_evidence",
    "inbound_events", "memberships", "plugin_calls", "rate_buckets", "rate_scope_keys", "run_inputs", "run_requests",
    "run_secret_index", "run_slots", "run_steps", "runs", "schedule_firings", "schedules", "step_outputs",
    "tenant_event_counters", "tenant_event_keys", "tenant_retention", "tenant_run_limits", "trigger_bindings",
    "webhook_endpoints", "workflow_versions", "workflows",
)  # fmt: skip
LIMITS = "insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 3)"


async def erasure_at(owner: Any, tenant_id: uuid.UUID, step: int) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("insert into tenant_erasures (tenant_id, requested_by, step) values (:t, :u, :s) "
                             "on conflict (tenant_id) do update set step = excluded.step"),
                        {"t": tenant_id, "u": uuid.uuid4(), "s": step})  # fmt: skip


def refused(e: pytest.ExceptionInfo[DBAPIError]) -> bool:
    return getattr(e.value.orig, "sqlstate", None) == "DPE01"


async def test_every_table_holding_tenant_data_is_fenced(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        holding = set((await s.execute(text(
            "select c.relname from pg_class c join pg_attribute a on a.attrelid = c.oid "
            "where c.relnamespace = 'public'::regnamespace and c.relkind = 'r' and a.attname = 'tenant_id' "
            "and not a.attisdropped"))).scalars())  # fmt: skip
        fenced = set((await s.execute(text(
            "select c.relname from pg_trigger t join pg_class c on c.oid = t.tgrelid "
            "join pg_proc p on p.oid = t.tgfoid where p.proname = 'tenant_insert_fence' and t.tgenabled = 'O'"
        ))).scalars())  # fmt: skip
    assert holding - fenced == UNFENCED
    assert fenced == set(FENCED_TABLES)


@pytest.mark.parametrize(("step", "inserted"), [(50, True), (60, False), (100, False)])
async def test_an_insert_is_refused_from_stage_60_whatever_the_role(
    owner_sessionmaker, worker_sessionmaker, step: int, inserted: bool
) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await erasure_at(owner_sessionmaker, tenant, step)
    for maker in (owner_sessionmaker, worker_sessionmaker):  # the table's owner, and a worker's straggling projection
        statement = LIMITS if maker is owner_sessionmaker else (
            "insert into claim_grants (claim_id, run_id, tenant_id, granted_by, root_run_id) "
            "values (:r, :r, :t, :r, :r)"
        )  # fmt: skip
        async with maker() as s:
            await s.begin()
            await tenant_scope(s, tenant)
            if inserted:
                await s.execute(text(statement), {"t": tenant, "r": uuid.uuid4()})
                await s.rollback()
                continue
            with pytest.raises(DBAPIError) as e:
                await s.execute(text(statement), {"t": tenant, "r": uuid.uuid4()})
            assert refused(e)
            await s.rollback()


async def test_a_row_for_every_tenant_is_never_fenced_and_a_fenced_tenants_own_is(owner_sessionmaker) -> None:
    """0041's tables (plugins-3a-1): an egress exception for every tenant (`tenant_id` null) names none, so the fence
    lets it through whoever is fenced; one of a fenced tenant's own, like its rate budget, is refused."""
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await erasure_at(owner_sessionmaker, tenant, 60)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into egress_allowlist (network, note) values ('192.0.2.0/24', 'every tenant')"))
    for statement in ("insert into egress_allowlist (network, tenant_id) values ('198.51.100.0/24', :t)",
                      "insert into rate_buckets (tenant_id, scope, capacity, refill_per_s, tokens, refilled_at) "
                      "values (:t, 's', 1, 1, 1, now())",
                      "insert into rate_scope_keys (tenant_id, sealed) values (:t, '\\x00')",
                      "insert into plugin_calls (tenant_id, kind, node_ref, field, expires_at) "  # 0042's
                      "values (:t, 'options', 'flow.x@1', 'f', now() + interval '1 hour')"):  # fmt: skip
        async with owner_sessionmaker() as s:
            await s.begin()
            with pytest.raises(DBAPIError) as e:
                await s.execute(text(statement), {"t": tenant})
            assert refused(e)
            await s.rollback()


async def test_no_key_is_created_for_a_tenant_whose_keys_may_have_gone(owner_sessionmaker) -> None:
    """The keyring creates a tenant's first key on first use: past stage 60, a straggler sealing anything would."""
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await erasure_at(owner_sessionmaker, tenant, 70)
    with pytest.raises(DBAPIError) as e:
        async with owner_sessionmaker() as s, s.begin():
            await Keyring(KekSet(Kek("k1", bytes(32)))).ensure_key(s, tenant)
    assert refused(e)


async def lock_waiters(owner: Any) -> int:
    async with owner() as s:
        return int((await s.execute(text("select count(*) from pg_stat_activity where wait_event_type = 'Lock'"))
                    ).scalar_one())  # fmt: skip


async def _waiting(owner: Any) -> None:
    for _ in range(500):
        if await lock_waiters(owner) >= 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("nothing waited for a lock")


async def enter_60(owner: Any, tenant_id: uuid.UUID, *, hold: asyncio.Event | None = None) -> None:
    """As the erasure enters stage 60: the tenant's lifecycle lock, exclusively, then the stage."""
    async with owner() as s, s.begin():
        await s.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                        {"k": f"dewpoint:tenant:{tenant_id}"})  # fmt: skip
        await s.execute(text("update tenant_erasures set step = 60 where tenant_id = :t"), {"t": tenant_id})
        if hold is not None:
            await hold.wait()


async def test_entering_stage_60_waits_for_an_insert_in_flight(owner_sessionmaker) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await erasure_at(owner_sessionmaker, tenant, 50)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(LIMITS), {"t": tenant})  # holds the lock, shared, until it commits
        entering = asyncio.create_task(enter_60(owner_sessionmaker, tenant))
        await _waiting(owner_sessionmaker)
        assert not entering.done()
    await entering
    async with owner_sessionmaker() as s:
        limits = text("select count(*) from tenant_run_limits where tenant_id = :t")
        assert (await s.execute(limits, {"t": tenant})).scalar_one() == 1  # it committed first: the sweep's to delete


async def test_an_insert_waiting_for_stage_60_is_refused_once_it_commits(owner_sessionmaker) -> None:
    tenant, _, _ = await seed_workflow(owner_sessionmaker)
    await erasure_at(owner_sessionmaker, tenant, 50)
    hold = asyncio.Event()
    entering = asyncio.create_task(enter_60(owner_sessionmaker, tenant, hold=hold))
    await asyncio.sleep(0.2)

    async def insert() -> None:
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(LIMITS), {"t": tenant})

    inserting = asyncio.create_task(insert())
    try:
        await _waiting(owner_sessionmaker)
    finally:
        hold.set()
        await entering
    with pytest.raises(DBAPIError) as e:
        await inserting
    assert refused(e)


@pytest.mark.parametrize(("step", "deleted"), [(None, False), (70, False), (80, True)])
async def test_a_workflow_version_stays_immutable_but_to_its_tenants_erasure_sweep(
    owner_sessionmaker, step: int | None, deleted: bool
) -> None:
    """Migration 0007 makes a version immutable, deletes included; an erasure's sweep (stage 80) deletes the tenant's
    versions, and nothing else does."""
    tenant, workflow_id, version_id = await seed_workflow(owner_sessionmaker)
    if step is not None:
        await erasure_at(owner_sessionmaker, tenant, step)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update workflows set active_version_id = null where id = :w"), {"w": workflow_id})
    statement = text("delete from workflow_versions where id = :v")
    if deleted:
        async with owner_sessionmaker() as s, s.begin():
            assert (await s.execute(statement, {"v": version_id})).rowcount == 1
        return
    with pytest.raises(DBAPIError, match="immutable"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(statement, {"v": version_id})
    with pytest.raises(DBAPIError, match="immutable"):  # an update never
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("update workflow_versions set number = 2 where id = :v"), {"v": version_id})
