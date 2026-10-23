# SPDX-License-Identifier: Apache-2.0
"""Migration 0074 on disposable databases, in a cluster of this module's own (editor 4f-3; the start-form pickers
design §4.1, §4.6): a request's picked names as a `run_inputs` record of the role `names`, at most one per request; a
schedule's as `schedules.names`, sealed, nullable with no default, null on every schedule before it, written by the API
and re-encrypted by the key admin as its input is. Its downgrade drops both."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.migrations.support import copy, downgrade, upgrade
from tests.migrations.test_0053 import _drop, _sql
from tests.probes.migration_locks import seed

ROOTS = 5
COLUMN = ("SELECT data_type, is_nullable, column_default FROM information_schema.columns "
          "WHERE table_name = 'schedules' AND column_name = 'names'")  # fmt: skip
GRANTED = ("SELECT grantee FROM information_schema.column_privileges WHERE table_name = 'schedules' "
           "AND column_name = 'names' AND privilege_type = 'UPDATE' AND grantee LIKE 'dewpoint_%' "
           "ORDER BY grantee")  # fmt: skip
ROLES = "(role = 'claim' AND pointer IS NOT NULL) OR (role IN ('envelope', 'csv', 'names') AND pointer IS NULL)"
COLUMN_ONLY = ("ALTER TABLE schedules ADD COLUMN names bytea",)
NOT_VALID = (*COLUMN_ONLY, f"ALTER TABLE run_inputs ADD CONSTRAINT run_inputs_role_0074 CHECK ({ROLES}) NOT VALID")
INTERRUPTED = {
    "column": COLUMN_ONLY,
    "not_valid": NOT_VALID,
    "validated": (*NOT_VALID, "ALTER TABLE run_inputs VALIDATE CONSTRAINT run_inputs_role_0074"),
}


def record(role: str, owner: uuid.UUID, pointer: str | None = None) -> str:
    """A `run_inputs` row of `role`, owned by `owner`, in the first tenant."""
    at = "NULL" if pointer is None else f"'{pointer}'"
    return ("INSERT INTO run_inputs (id, tenant_id, owner_run_id, root_run_id, sensitive_pointers, ciphertext, role, "
            f"pointer) SELECT gen_random_uuid(), id, '{owner}', '{owner}', '[]', '\\x00', '{role}', {at} "
            "FROM tenants ORDER BY id LIMIT 1")  # fmt: skip


async def _rows(url: str, query: str) -> list[tuple[object, ...]]:
    c = await asyncpg.connect(url)
    try:
        return [tuple(r) for r in await c.fetch(query)]
    finally:
        await c.close()


@pytest.fixture(scope="module")
def cluster() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url().rsplit("/", 1)[0]


@pytest.fixture(scope="module")
def template(cluster: str) -> str:
    """A seeded database at 0073, as the deployments that run 0074 are."""
    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0073"'))
    upgrade(f"{cluster}/t0073", "0034")
    asyncio.run(seed(f"{cluster}/t0073", ROOTS))
    upgrade(f"{cluster}/t0073", "0073")
    return "t0073"


@pytest.fixture
async def db(cluster: str, template: str) -> AsyncIterator[str]:
    url = await copy(cluster, template)
    yield url
    await _drop(cluster, url.rsplit("/", 1)[1])


async def test_a_schedules_names_are_sealed_bytes_null_before_it(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0074")
    assert await _rows(db, COLUMN) == [("bytea", "YES", None)]
    assert await _rows(db, "SELECT count(names) FROM schedules") == [(0,)]
    assert await _rows(db, GRANTED) == [("dewpoint_admin",), ("dewpoint_api",)]


async def test_a_request_holds_one_names_record_never_a_claim(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0074")
    owner = uuid.uuid4()
    await _sql(db, record("names", owner))
    with pytest.raises(asyncpg.UniqueViolationError):
        await _sql(db, record("names", owner))
    with pytest.raises(asyncpg.CheckViolationError):
        await _sql(db, record("names", uuid.uuid4(), pointer="/site"))
    await _sql(db, record("csv", owner), record("claim", owner, pointer="/site"))  # the others, as before


@pytest.mark.parametrize("state", list(INTERRUPTED))
async def test_an_upgrade_interrupted_part_way_goes_on(db: str, state: str) -> None:
    """#142 item 4, as 0071's: each place the online upgrade can stop (its steps commit one by one) goes on to the same
    end: one validated check naming `names` in the old one's place, the index, the grants."""
    await _sql(db, *INTERRUPTED[state])
    await asyncio.to_thread(upgrade, db, "0074")
    checks = await _rows(db, "SELECT conname, convalidated, pg_get_constraintdef(oid) LIKE '%names%' "
                             "FROM pg_constraint WHERE conname LIKE 'run_inputs_role%'")  # fmt: skip
    assert checks == [("run_inputs_role", True, True)]
    assert await _rows(db, "SELECT indisvalid FROM pg_index WHERE indexrelid = 'run_inputs_one_names'::regclass") == [
        (True,)
    ]
    assert await _rows(db, GRANTED) == [("dewpoint_admin",), ("dewpoint_api",)]


async def test_the_downgrade_drops_them(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0074")
    await _sql(db, record("names", uuid.uuid4()), "UPDATE schedules SET names = '\\x00'")
    await asyncio.to_thread(downgrade, db, "0073")
    assert await _rows(db, COLUMN) == []
    assert await _rows(db, "SELECT count(*) FROM run_inputs WHERE role = 'names'") == [(0,)]
    with pytest.raises(asyncpg.CheckViolationError):
        await _sql(db, record("names", uuid.uuid4()))
