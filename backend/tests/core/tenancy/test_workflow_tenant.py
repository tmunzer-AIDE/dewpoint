# SPDX-License-Identifier: Apache-2.0
"""A row names only its own tenant's workflows, versions and runs (#35; engine 2b spec §14). Row-level security checks
only the row's own `tenant_id`, and a foreign-key check doesn't apply the referenced table's policies, so a key on the
referenced id alone let a role scoped to tenant A record a row naming tenant B's object; only the application's own
reads prevented it. Every key between two tenant tables carries `tenant_id` (migration 0035)."""

import importlib.util
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from dewpoint.core.auth.users import create_user
from dewpoint.core.db import tenant_scope
from tests.support.workflows import PROFILE, seed_workflow

MIGRATION = Path(__file__).parents[3] / "migrations" / "versions" / "0035_tenant_keys.py"

# Every foreign key from a table with a tenant_id to another such table that leaves tenant_id out.
TENANT_BLIND_KEYS = """
select c.conrelid::regclass::text || ' ' || c.conname from pg_constraint c
 where c.contype = 'f'
   and exists (select 1 from pg_attribute a where a.attrelid = c.conrelid and a.attname = 'tenant_id')
   and exists (select 1 from pg_attribute a where a.attrelid = c.confrelid and a.attname = 'tenant_id')
   and not exists (select 1 from unnest(c.conkey) k(n) join pg_attribute a on a.attrelid = c.conrelid
                    and a.attnum = k.n where a.attname = 'tenant_id')
 order by 1
"""

REQUEST = (
    "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, idempotency_key, digest, "
    "digest_key_version, status, reason, ended_at) values (gen_random_uuid(), :t, :w, :v, 'manual', 'live', :key, "
    ":digest, 1, 'refused', 'input_invalid', now())"
)
VERSION = (
    "insert into workflow_versions (id, tenant_id, workflow_id, number, graph, node_refs, engine_abi, cel_profile, "
    "input_schema, output_schema, vars_schema, closure_version_ids, closure_workflow_ids, closure_node_refs, "
    "closure_cel_profiles, closure_depth, graph_hash, version_hash) values (:n, :t, :w, :number, '{}', '{}', 1, "
    "cast(:p as text), '{}', '{}', '{}', array[cast(:n as uuid)], array[cast(:w as uuid)], '{}', "
    "array[cast(:p as text)], 0, 'g', 'v')"
)
MAPPING = (
    "insert into csv_mappings (workflow_id, tenant_id, mapping, saved_by, saved_against) values (:w, :t, '{}', :u, :v)"
)
RUN = (
    "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, kind, parent_run_id) "
    "values (:n, :t, :w, :v, 'live', 'running', :kind, :r)"
)
# (case, writing role, statement, the parameters naming tenant B's objects); the control names tenant A's own.
CASES = [
    ("run_requests.workflow_id", "api", REQUEST, {"w": "wb"}),
    ("run_requests.workflow_id", "dispatch", REQUEST, {"w": "wb"}),
    ("run_requests.workflow_version_id", "dispatch", REQUEST, {"v": "vb"}),
    ("csv_uploads.workflow_id", "api",
     "insert into csv_uploads (id, tenant_id, owner_id, workflow_id, file_digest, digest_key_version, size_bytes, "
     "row_count, staged, expires_at) values (:n, :t, :u, :w, :digest, 1, 1, 1, :staged, now() + interval '1 hour')",
     {"w": "wb"}),
    ("csv_mappings.workflow_id", "api",
     MAPPING,
     {"w": "wb", "v": "vb"}),
    ("csv_mappings.saved_against", "api",
     MAPPING,
     {"v": "vb"}),
    ("schedules.workflow_id", "api",
     "insert into schedules (id, tenant_id, workflow_id, every_s, mode, input, created_by) "
     "values (:n, :t, :w, 60, 'live', :staged, :u)",
     {"w": "wb"}),
    ("workflow_versions.workflow_id", "api", VERSION, {"w": "wb"}),
    ("runs.workflow_version_id", "worker", RUN, {"w": "wb", "v": "vb"}),
    ("runs.parent_run_id", "worker", RUN, {"r": "rb"}),
    ("run_steps.run_id", "worker",
     "insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status) "
     "values (:t, :r, :n, '', 1, 'n', 'running')",
     {"r": "rb"}),
]  # fmt: skip


@pytest.fixture
async def two_tenants(owner_sessionmaker) -> dict[str, Any]:
    """Tenant A and tenant B, each with a workflow, its published version and a run of it."""
    ids: dict[str, Any] = {}
    for side in ("a", "b"):
        ids[side], ids[f"w{side}"], ids[f"v{side}"] = await seed_workflow(owner_sessionmaker)
        ids[f"r{side}"] = uuid.uuid4()
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(RUN), {"n": ids[f"r{side}"], "t": ids[side], "w": ids[f"w{side}"],
                                        "v": ids[f"v{side}"], "kind": "run", "r": None})  # fmt: skip
    async with owner_sessionmaker() as s, s.begin():
        ids["u"] = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
    return ids


def _params(ids: dict[str, Any], foreign: dict[str, str]) -> dict[str, Any]:
    """A case's parameters: tenant A's own objects, but those the case names from tenant B."""
    params = {"t": ids["a"], "w": ids["wa"], "v": ids["va"], "r": ids["ra"], "u": ids["u"], "n": uuid.uuid4(),
              "number": 2, "p": PROFILE, "key": uuid.uuid4().hex, "digest": b"\x00" * 32, "staged": b"\x01",
              "kind": "subflow"}  # fmt: skip
    return params | {name: ids[key] for name, key in foreign.items()}


async def _insert(makers: dict[str, Any], ids: dict[str, Any], role: str, sql: str, foreign: dict[str, str]) -> None:
    async with makers[role]() as s, s.begin():
        await tenant_scope(s, ids["a"])
        await s.execute(text(sql), _params(ids, foreign))


@pytest.fixture
def makers(api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker) -> dict[str, Any]:
    return {"api": api_sessionmaker, "dispatch": dispatch_sessionmaker, "worker": worker_sessionmaker}


async def test_no_key_between_tenant_tables_leaves_the_tenant_out(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        assert (await s.execute(text(TENANT_BLIND_KEYS))).scalars().all() == []


@pytest.mark.parametrize(("case", "role", "sql", "foreign"), CASES, ids=[f"{c[0]}-{c[1]}" for c in CASES])
async def test_a_row_names_its_own_tenants_objects(two_tenants, makers, case, role, sql, foreign) -> None:
    """The control: the same row, naming only tenant A's own objects, is recorded."""
    await _insert(makers, two_tenants, role, sql, {})


@pytest.mark.parametrize(("case", "role", "sql", "foreign"), CASES, ids=[f"{c[0]}-{c[1]}" for c in CASES])
async def test_a_row_cant_name_another_tenants_object(two_tenants, makers, case, role, sql, foreign) -> None:
    """Scoped to tenant A, the writing role can't name tenant B's object: a foreign-key violation."""
    with pytest.raises(IntegrityError, match="foreign key"):
        await _insert(makers, two_tenants, role, sql, foreign)


async def test_the_upgrade_refuses_rows_that_break_a_key_naming_keys_and_counts_only(owner_sessionmaker,
                                                                                    two_tenants) -> None:  # fmt: skip
    """Rows recorded before migration 0035 that break one of its keys stop the upgrade before any key changes. The
    error names each key and its count, never a row's contents. The keys are dropped inside a transaction that's
    rolled back, to record such rows."""
    spec = importlib.util.spec_from_file_location("migration_0035", MIGRATION)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    ids = two_tenants
    async with owner_sessionmaker() as s:
        await s.begin()
        for name, table, *_ in migration.KEYS:
            await s.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
        await s.execute(text("ALTER TABLE runs DROP CONSTRAINT runs_root_run"))  # 0037's, which such a sub-run breaks
        for _, _, sql, foreign in CASES:
            params = _params(ids, foreign)
            await s.execute(text(sql), params)
            if sql == VERSION:  # tenant B's workflow made active a version recorded for it in tenant A
                await s.execute(text("update workflows set active_version_id = :n where id = :w"), params)
        with pytest.raises(RuntimeError) as refused:
            await s.run_sync(lambda sync: migration.check(sync.connection()))
        await s.rollback()
    message = str(refused.value)
    for name, *_ in migration.KEYS:
        assert re.search(rf"\b{name} [1-9]", message), name
    assert not any(str(value) in message for value in ids.values()), "a row's contents are in the message"


async def test_deleting_a_run_still_deletes_its_steps(owner_sessionmaker, two_tenants) -> None:
    """Migration 0035 rebuilt the run-steps key with the tenant; it keeps deleting a run's steps with the run."""
    ids = two_tenants
    sql = next(sql for case, _, sql, _ in CASES if case == "run_steps.run_id")
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(sql), _params(ids, {}))
        await s.execute(text("delete from runs where id = :r"), {"r": ids["ra"]})
        steps = await s.execute(text("select count(*) from run_steps where run_id = :r"), {"r": ids["ra"]})
        assert steps.scalar() == 0
