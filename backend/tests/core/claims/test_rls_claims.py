# SPDX-License-Identifier: Apache-2.0
"""The claim tables (engine 2b spec §3.1, §3.4, §3.7, §14): tenant-scoped under forced row-level security, written
once and never changed, and reachable only by the roles that make and resolve claims."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope

TABLES = ("run_inputs", "step_outputs", "claim_grants", "run_secret_index")


async def tenants(owner: Any) -> tuple[uuid.UUID, uuid.UUID]:
    a, b = uuid.uuid4(), uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(text("insert into tenants(id,name,slug) values (:a,'A','a'),(:b,'B','b')"), {"a": a, "b": b})
    return a, b


def row(table: str, tenant: uuid.UUID) -> dict[str, Any]:
    """One valid row of `table` for `tenant`."""
    run = uuid.uuid4()
    if table == "claim_grants":
        return {"claim_id": uuid.uuid4(), "run_id": uuid.uuid4(), "tenant_id": tenant, "granted_by": run,
                "root_run_id": run}  # fmt: skip
    if table == "run_secret_index":
        return {"root_run_id": run, "tenant_id": tenant, "version": 1, "string_count": 0, "byte_count": 0,
                "ciphertext": b"\x01"}  # fmt: skip
    claim = {"id": uuid.uuid4(), "tenant_id": tenant, "owner_run_id": run, "root_run_id": run,
             "sensitive_pointers": "[]", "ciphertext": b"\x01"}  # fmt: skip
    if table == "run_inputs":
        return {**claim, "pointer": ""}
    return {**claim, "kind": "output", "step_id": uuid.uuid4(), "iteration_key": "", "attempt": 1}


def insert(table: str, values: dict[str, Any]) -> Any:
    cols = ", ".join(values)
    params = ", ".join(f"CAST(:{c} AS jsonb)" if c == "sensitive_pointers" else f":{c}" for c in values)
    return text(f"insert into {table} ({cols}) values ({params})")


@pytest.mark.parametrize("table", TABLES)
async def test_each_claim_table_forces_row_level_security(owner_sessionmaker, table) -> None:
    async with owner_sessionmaker() as s:
        flags = (
            await s.execute(
                text("select relrowsecurity, relforcerowsecurity from pg_class where relname = :t"), {"t": table}
            )
        ).one()
    assert tuple(flags) == (True, True)


@pytest.mark.parametrize("table", TABLES)
async def test_a_row_is_seen_only_within_its_tenant(owner_sessionmaker, worker_sessionmaker, table) -> None:
    a, b = await tenants(owner_sessionmaker)
    values = row(table, a)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(insert(table, values), values)
    count = text(f"select count(*) from {table}")
    async with worker_sessionmaker() as s, s.begin():
        assert (await s.execute(count)).scalar_one() == 0  # no tenant: nothing
        await tenant_scope(s, b)
        assert (await s.execute(count)).scalar_one() == 0
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        assert (await s.execute(count)).scalar_one() == 1


@pytest.mark.parametrize("table", TABLES)
async def test_a_row_for_another_tenant_is_refused(owner_sessionmaker, worker_sessionmaker, table) -> None:
    a, b = await tenants(owner_sessionmaker)
    values = row(table, b)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(insert(table, values), values)


# Who may do what. Admission claims a trigger and seeds the secret index in its caller's transaction: the API's (the
# owner's ruling on 2b-2), the CLI's as dispatch; the worker claims during a run, grants, and resolves. Nobody updates
# or deletes a claim: retention (2b-4) gets its own role.
ALLOWED = {
    ("api", "run_inputs"): {"select", "insert"},
    ("api", "run_secret_index"): {"select", "insert", "update"},
    ("dispatch", "run_inputs"): {"select", "insert"},
    ("dispatch", "run_secret_index"): {"select", "insert", "update"},
    ("worker", "run_inputs"): {"select", "insert"},
    ("worker", "step_outputs"): {"select", "insert"},
    ("worker", "claim_grants"): {"select", "insert"},
    ("worker", "run_secret_index"): {"select", "insert", "update"},
}
ROLES = ("api", "dispatch", "worker", "admin", "auditor")
OPS = ("select", "insert", "update", "delete")


@pytest.mark.parametrize("table", TABLES)
async def test_each_role_has_exactly_its_privileges(owner_sessionmaker, table) -> None:
    async with owner_sessionmaker() as s:
        for role in ROLES:
            for op in OPS:
                granted = (
                    await s.execute(
                        text("select has_table_privilege(:r, :t, :p)"),
                        {"r": f"dewpoint_{role}", "t": table, "p": op},
                    )
                ).scalar_one()
                assert granted == (op in ALLOWED.get((role, table), set())), (role, table, op)
