# SPDX-License-Identifier: Apache-2.0
"""Migration 0054 on disposable databases, in a cluster of this module's own (2b-4b M4 recovery, task 3; the owner's
ruling 2): the blocker store, its fence, and its backfill of the attempts made before it. Every root evidence row left
`unproven`, and every request `starting`, gets a `legacy_unknown`, `unresolved` blocker, its recorded start request id
if it has one, and no invented send. Its downgrade refuses while any blocker is left: dropping one would forget a send
that may still create an execution."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import asyncpg
import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.migrations.support import copy, downgrade, upgrade
from tests.migrations.test_0053 import _drop, _sql
from tests.probes.migration_locks import seed

ROOTS = 20


async def _rows(url: str, query: str, *args: object) -> list[tuple[object, ...]]:
    c = await asyncpg.connect(url)
    try:
        return [tuple(r) for r in await c.fetch(query, *args)]
    finally:
        await c.close()


@pytest.fixture(scope="module")
def cluster() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url().rsplit("/", 1)[0]


@pytest.fixture(scope="module")
def template(cluster: str) -> str:
    """A seeded database at 0053, as the deployments that run 0054 are."""
    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0053"'))
    upgrade(f"{cluster}/t0053", "0034")
    asyncio.run(seed(f"{cluster}/t0053", ROOTS))
    upgrade(f"{cluster}/t0053", "0053")
    return "t0053"


@pytest.fixture
async def db(cluster: str, template: str) -> AsyncIterator[str]:
    url = await copy(cluster, template)
    yield url
    await _drop(cluster, url.rsplit("/", 1)[1])


async def test_the_backfill_blocks_every_attempt_made_before_it(db: str) -> None:
    requests = await _rows(db, "SELECT id, tenant_id FROM run_requests ORDER BY id LIMIT 3")
    (unproven, unproven_tenant), (starting, _), (recorded, _) = requests
    gone = uuid.uuid4()  # an unproven root whose request isn't there any more: its workflow id names it
    await _sql(
        db,
        f"UPDATE run_requests SET start_request_id = NULL, sends = 0 WHERE id = '{unproven}'",
        f"UPDATE execution_evidence SET unproven = true WHERE workflow_id = 't:{unproven_tenant}:run:{unproven}' "
        "AND run_id IS NULL",
        f"UPDATE run_requests SET status = 'starting', starting_at = now() WHERE id IN ('{starting}', '{recorded}')",
        f"UPDATE run_requests SET start_request_id = gen_random_uuid(), sends = 2 WHERE id = '{recorded}'",
        "INSERT INTO execution_evidence (tenant_id, workflow_id, started_at, unproven) "
        f"VALUES ('{unproven_tenant}', 't:{unproven_tenant}:run:{gone}', now(), true)",
    )
    expected = set(await _rows(db, """
        SELECT r.id, r.start_request_id FROM run_requests r WHERE r.status = 'starting'
        UNION
        SELECT split_part(e.workflow_id, ':', 4)::uuid, r.start_request_id FROM execution_evidence e
          LEFT JOIN run_requests r ON r.id = split_part(e.workflow_id, ':', 4)::uuid
         WHERE e.run_id IS NULL AND e.unproven"""))  # fmt: skip
    assert {unproven, starting, recorded, gone} <= {request for request, _ in expected}
    await asyncio.to_thread(upgrade, db, "0054")
    blockers = await _rows(db, "SELECT request_id, start_request_id, legacy_unknown, state FROM unresolved_sends")
    assert {(r, s) for r, s, _, _ in blockers} == expected
    assert {(legacy, state) for _, _, legacy, state in blockers} == {(True, "unresolved")}
    assert await _rows(db, "SELECT count(*) FROM start_sends") == [(0,)]  # no invented attempt


async def test_a_fresh_database_at_head_has_the_store_its_fence_and_their_grants() -> None:
    """In a cluster of its own: this module's ran 0053 already, whose role is the cluster's (one Dewpoint database
    per cluster)."""
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        url = pg.get_connection_url()
        await asyncio.to_thread(upgrade, url, "head")
        rights = set(await _rows(url, """
            SELECT r, t, p FROM unnest(ARRAY['dewpoint_dispatch', 'dewpoint_retention', 'dewpoint_api',
                                             'dewpoint_worker', 'dewpoint_admin']) r,
                   unnest(ARRAY['unresolved_sends', 'start_sends']) t,
                   unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE']) p
             WHERE has_table_privilege(r, t, p)"""))  # fmt: skip
        assert rights == {
            *(("dewpoint_dispatch", t, p) for t in ("unresolved_sends", "start_sends")
              for p in ("SELECT", "INSERT", "UPDATE")),
            ("dewpoint_dispatch", "unresolved_sends", "DELETE"),
            *(("dewpoint_retention", t, p) for t in ("unresolved_sends", "start_sends")
              for p in ("SELECT", "UPDATE", "DELETE")),
        }  # fmt: skip
        trigger = await _rows(url, "SELECT tgdeferrable, tginitdeferred FROM pg_trigger "
                                   "WHERE tgname = 'run_requests_send_recorded'")  # fmt: skip
        assert trigger == [(True, True)]


async def test_the_downgrade_refuses_while_a_blocker_is_left(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0054")
    request, tenant = (await _rows(db, "SELECT id, tenant_id FROM run_requests LIMIT 1"))[0]
    await _sql(db, "INSERT INTO unresolved_sends (request_id, tenant_id, workflow_id, legacy_unknown, state) "
                   f"VALUES ('{request}', '{tenant}', 't:{tenant}:run:{request}', true, 'unresolved') "
                   "ON CONFLICT (request_id) DO NOTHING")  # fmt: skip
    with pytest.raises(Exception, match="0054 refused"):
        await asyncio.to_thread(downgrade, db, "0053")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0054",)]
    await _sql(db, "DELETE FROM unresolved_sends")
    await asyncio.to_thread(downgrade, db, "0053")
    assert await _rows(db, "SELECT to_regclass('public.unresolved_sends'), to_regclass('public.start_sends'), "
                           "(SELECT count(*) FROM pg_trigger WHERE tgname = 'run_requests_send_recorded')") == [
        (None, None, 0)]  # fmt: skip


# 0055 (task 5): the recovery reasons and the paced pick, on the same cluster.
COLUMNS = """SELECT attname FROM pg_attribute WHERE attrelid = 'public.unresolved_sends'::regclass
              AND attname LIKE 'late_start%' AND NOT attisdropped ORDER BY attname"""
DEFINED = """SELECT (SELECT pg_get_functiondef('reconcile_candidates(interval, interval, integer)'::regprocedure)),
                    (SELECT pg_get_functiondef('work_settled_clear(integer)'::regprocedure)),
                    (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'recovery_items_reason'),
                    (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'operator_commands_reason')"""


async def test_0055_and_back_restores_0054s_functions_and_checks_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0054")
    before = await _rows(db, DEFINED)
    await asyncio.to_thread(upgrade, db, "0055")
    after = await _rows(db, DEFINED)
    assert "start_unresolved" in str(after[0][0]) and "start_unresolved" not in str(before[0][0])  # the paced pick
    assert "late_start" in str(after[0][1]) and "late_start" in str(after[0][2]) and "late_start" in str(after[0][3])
    assert await _rows(db, COLUMNS) == [("late_start",), ("late_start_at",)]  # the late start's record (0055)
    await asyncio.to_thread(downgrade, db, "0054")
    assert await _rows(db, DEFINED) == before
    assert await _rows(db, COLUMNS) == []


async def test_0055s_downgrade_refuses_while_a_new_reason_is_recorded(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0055")
    tenant = (await _rows(db, "SELECT id FROM tenants LIMIT 1"))[0][0]
    await _sql(db, f"INSERT INTO recovery_items (tenant_id, reason, item_id) VALUES ('{tenant}', 'late_start', "
                   "gen_random_uuid())")  # fmt: skip
    with pytest.raises(Exception, match="0055 refused"):
        await asyncio.to_thread(downgrade, db, "0054")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0055",)]
    await _sql(db, "DELETE FROM recovery_items WHERE reason = 'late_start'")
    await asyncio.to_thread(downgrade, db, "0054")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0054",)]


async def test_0055s_downgrade_refuses_while_a_blocker_keeps_a_late_start_record(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0055")
    request, tenant = (await _rows(db, "SELECT id, tenant_id FROM run_requests LIMIT 1"))[0]
    await _sql(db, "INSERT INTO unresolved_sends (request_id, tenant_id, workflow_id, legacy_unknown, state, "
                   f"late_start, late_start_at) VALUES ('{request}', '{tenant}', 't:{tenant}:run:{request}', true, "
                   "'unresolved', 'unmatched', now()) ON CONFLICT (request_id) DO UPDATE SET late_start = 'unmatched', "
                   "late_start_at = now()")  # fmt: skip
    with pytest.raises(Exception, match="0055 refused"):
        await asyncio.to_thread(downgrade, db, "0054")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0055",)]
    await _sql(db, "UPDATE unresolved_sends SET late_start = NULL, late_start_at = NULL")
    await asyncio.to_thread(downgrade, db, "0054")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0054",)]


# Each downgrade's refusal holds against a write it couldn't see yet (the owner's third gate-B review): it takes the
# guarded tables' locks before it checks them, so a record committed while it waits is seen, never dropped.


async def _waiting(url: str) -> None:
    """Until a session of `url`'s database waits on a lock (the downgrade, behind the writer)."""
    for _ in range(400):
        found = await _rows(url, "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                                 "AND wait_event_type = 'Lock'")  # fmt: skip
        if found[0][0]:
            return
        await asyncio.sleep(0.025)
    raise AssertionError("the downgrade never waited")


async def _while_written(db: str, write: str, target: str) -> Any:
    """`write`, uncommitted, while the downgrade to `target` starts; committed once the downgrade waits on it. The
    downgrade's outcome (it raises, or returns)."""
    writer = await asyncpg.connect(db)
    try:
        await writer.execute("BEGIN")
        await writer.execute(write)
        downgrading = asyncio.ensure_future(asyncio.to_thread(downgrade, db, target))
        await _waiting(db)
        await writer.execute("COMMIT")
        return await asyncio.gather(downgrading, return_exceptions=True)
    finally:
        await writer.close()


async def test_0054s_downgrade_never_drops_a_blocker_written_while_it_checks(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0054")
    await _sql(db, "DELETE FROM unresolved_sends")  # an empty store: nothing to refuse, until the writer commits
    request, tenant = (await _rows(db, "SELECT id, tenant_id FROM run_requests LIMIT 1"))[0]
    blocker = ("INSERT INTO unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, state) VALUES "
               f"('{request}', '{tenant}', 't:{tenant}:run:{request}', gen_random_uuid(), 'pending')")  # fmt: skip
    [outcome] = await _while_written(db, blocker, "0053")
    assert isinstance(outcome, Exception) and "0054 refused" in str(outcome), outcome
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0054",)]
    assert await _rows(db, "SELECT count(*) FROM unresolved_sends") == [(1,)]


# Each table 0055's downgrade guards, written while it checks: the write, and what reads it back once committed
GUARDED = {
    "a blocker's record": (
        "UPDATE unresolved_sends SET late_start = 'unmatched', late_start_at = now() WHERE request_id = '{r}'",
        "SELECT count(*) FROM unresolved_sends WHERE late_start IS NOT NULL",
    ),
    "a recovery item": (
        "INSERT INTO recovery_items (tenant_id, reason, item_id) VALUES ('{t}', 'late_start', '{r}')",
        "SELECT count(*) FROM recovery_items WHERE reason = 'late_start'",
    ),
    "an operator's command": (
        "INSERT INTO operator_commands (tenant_id, kind, item_id, reason, incident_since, actor_id, idempotency_key) "
        "VALUES ('{t}', 'settle_ended', '{r}', 'late_start_unmatched', now(), gen_random_uuid(), 'k')",
        "SELECT count(*) FROM operator_commands WHERE reason = 'late_start_unmatched'",
    ),
}


@pytest.mark.parametrize("guarded", GUARDED)
async def test_0055s_downgrade_never_drops_a_record_written_while_it_checks(db: str, guarded: str) -> None:
    await asyncio.to_thread(upgrade, db, "0055")
    request, tenant = (await _rows(db, "SELECT id, tenant_id FROM run_requests LIMIT 1"))[0]
    await _sql(db, "INSERT INTO unresolved_sends (request_id, tenant_id, workflow_id, legacy_unknown, state) "
                   f"VALUES ('{request}', '{tenant}', 't:{tenant}:run:{request}', true, 'unresolved') "
                   "ON CONFLICT (request_id) DO NOTHING")  # fmt: skip
    write, kept = GUARDED[guarded]
    [outcome] = await _while_written(db, write.format(r=request, t=tenant), "0054")
    assert isinstance(outcome, Exception) and "0055 refused" in str(outcome), outcome
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0055",)]
    assert await _rows(db, kept) == [(1,)]
