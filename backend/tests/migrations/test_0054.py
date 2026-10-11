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


# 0056 (task 6): confirmations, on the same cluster. Its downgrade restores 0050's pick exactly, and refuses while a
# login's mapping, a confirmation or a pending command is kept (before 0056 a pending command runs unconfirmed).
PICK = "SELECT pg_get_functiondef('pending_commands(integer)'::regprocedure)"
CONFIRMING = """SELECT to_regclass('public.recovery_operators'), to_regclass('public.operator_confirmations'),
                       to_regprocedure('recovery.operator_command_confirm(uuid, bytea)')"""
KEPT = {  # what 0056's downgrade refuses to drop, each written as its writer would
    "a login's mapping": "INSERT INTO recovery_operators (login, user_id, provisioned_by, provisioned_at) "
                         "VALUES ('rcv_alice', gen_random_uuid(), 'admin', now())",
    "a pending command": "INSERT INTO operator_commands (tenant_id, kind, item_id, reason, incident_since, actor_id, "
                         "idempotency_key) SELECT tenant_id, 'record_lost_run', id, 'run_history_missing', now(), "
                         "gen_random_uuid(), 'k' FROM run_requests LIMIT 1",
}  # fmt: skip


async def test_0056_and_back_restores_0055s_pick_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0055")
    before = await _rows(db, PICK)
    await asyncio.to_thread(upgrade, db, "0056")
    assert "operator_confirmations" in str((await _rows(db, PICK))[0][0])
    assert None not in (await _rows(db, CONFIRMING))[0]
    await asyncio.to_thread(downgrade, db, "0055")
    assert await _rows(db, PICK) == before
    assert await _rows(db, CONFIRMING) == [(None, None, None)]


@pytest.mark.parametrize("kept", KEPT)
async def test_0056s_downgrade_refuses_while_a_mapping_or_a_pending_command_is_kept(db: str, kept: str) -> None:
    await asyncio.to_thread(upgrade, db, "0056")
    await _sql(db, KEPT[kept])
    with pytest.raises(Exception, match="0056 refused"):
        await asyncio.to_thread(downgrade, db, "0055")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0056",)]


@pytest.mark.parametrize("kept", KEPT)
async def test_0056s_downgrade_never_drops_what_is_written_while_it_checks(db: str, kept: str) -> None:
    await asyncio.to_thread(upgrade, db, "0056")
    [outcome] = await _while_written(db, KEPT[kept], "0055")
    assert isinstance(outcome, Exception) and "0056 refused" in str(outcome), outcome
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0056",)]


# 0057 (task 8): releases bound to the holds shown, on the same cluster. Its downgrade restores 0050's direct releases,
# 0056's canonical text, the columns, checks and grants exactly, and refuses while a release command is kept.
def _function(signature: str) -> str:
    return (f"(SELECT pg_get_functiondef(p) || coalesce(proacl::text, '') FROM pg_proc, "
            f"to_regprocedure('{signature}') p WHERE pg_proc.oid = p)")  # fmt: skip


RELEASES_STATE = f"""SELECT {_function("work_failure_release(text, uuid)")},
  {_function("work_failures_release_many(text, timestamptz, integer)")}, {_function("work_failures_held(integer)")},
  {_function("operator_command_canonical(uuid)")},
  (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'operator_commands_kind'),
  (SELECT string_agg(attname || ':' || attnotnull || ':' || coalesce(attacl::text, ''), ',' ORDER BY attnum)
     FROM pg_attribute WHERE attrelid = 'public.operator_commands'::regclass AND attnum > 0 AND NOT attisdropped),
  (SELECT string_agg(attname, ',' ORDER BY attnum) FROM pg_attribute
    WHERE attrelid = 'public.work_failures'::regclass AND attnum > 0 AND NOT attisdropped),
  to_regclass('public.work_hold_ids'), to_regclass('public.operator_command_holds')"""
RELEASE = ("INSERT INTO operator_commands (tenant_id, kind, work_kind, item_id, actor_id, idempotency_key) "
           "SELECT tenant_id, 'release_held', 'dispatch', id, gen_random_uuid(), 'k' "
           "FROM run_requests LIMIT 1")  # fmt: skip


async def test_0057_and_back_restores_0056s_functions_columns_checks_and_grants_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0056")
    before = await _rows(db, RELEASES_STATE)
    await asyncio.to_thread(upgrade, db, "0057")
    after = (await _rows(db, RELEASES_STATE))[0]
    assert after[0] is None and after[1] is None and "hold_id" in str(after[2]) and "holds" in str(after[3])
    assert "max_holds" in str(after[5]) and "hold_id" in str(after[6]) and None not in after[7:]
    await asyncio.to_thread(downgrade, db, "0056")
    assert await _rows(db, RELEASES_STATE) == before


async def test_0057s_downgrade_refuses_while_a_release_command_is_kept(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0057")
    await _sql(db, RELEASE)
    with pytest.raises(Exception, match="0057 refused"):
        await asyncio.to_thread(downgrade, db, "0056")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0057",)]


async def test_0057s_downgrade_never_drops_a_release_recorded_while_it_checks(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0057")
    [outcome] = await _while_written(db, RELEASE, "0056")
    assert isinstance(outcome, Exception) and "0057 refused" in str(outcome), outcome
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0057",)]


# 0058 (task 9): the counts and the reveal, on the same cluster. Its downgrade restores 0056's pick and 0057's checks
# exactly, and refuses while an inspection is kept.
REVEAL_STATE = f"""SELECT {_function("pending_commands(integer)")},
  (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'operator_commands_kind'),
  (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'operator_commands_fields'),
  to_regprocedure('admin_session(text)'), to_regprocedure('unresolved_sends_counts(text)'),
  to_regprocedure('recovery.unresolved_send_reveal(uuid)')"""
INSPECTION = ("INSERT INTO operator_commands (tenant_id, kind, item_id, actor_id, idempotency_key) "
              "SELECT tenant_id, 'inspect_unresolved_send', id, gen_random_uuid(), 'k' "
              "FROM run_requests LIMIT 1")  # fmt: skip


async def test_0058_and_back_restores_0057s_pick_and_checks_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0057")
    before = await _rows(db, REVEAL_STATE)
    await asyncio.to_thread(upgrade, db, "0058")
    after = (await _rows(db, REVEAL_STATE))[0]
    assert "inspect_unresolved_send" in str(after[0]) and "inspect_unresolved_send" in str(after[1])
    assert None not in after[3:]
    await asyncio.to_thread(downgrade, db, "0057")
    assert await _rows(db, REVEAL_STATE) == before


async def test_0058s_downgrade_refuses_while_an_inspection_is_kept(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0058")
    await _sql(db, INSPECTION)
    with pytest.raises(Exception, match="0058 refused"):
        await asyncio.to_thread(downgrade, db, "0057")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0058",)]


async def test_0058s_downgrade_never_drops_an_inspection_recorded_while_it_checks(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0058")
    [outcome] = await _while_written(db, INSPECTION, "0057")
    assert isinstance(outcome, Exception) and "0058 refused" in str(outcome), outcome


# 0059 (task 10): abandon_start, on the same cluster. Its downgrade restores 0055's settled entries, the checks and the
# evidence's width exactly, and refuses while an abandonment or its record is kept.
ABANDON_STATE = f"""SELECT {_function("work_settled_clear(integer)")},
  (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'operator_commands_kind'),
  (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'operator_commands_reason'),
  (SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'recovery_items_reason'),
  (SELECT format_type(atttypid, atttypmod) FROM pg_attribute
    WHERE attrelid = 'public.operator_commands'::regclass AND attname = 'evidence')"""
ABANDONED = ("INSERT INTO recovery_items (tenant_id, reason, item_id) "
             "SELECT tenant_id, 'start_abandoned', id FROM run_requests LIMIT 1")  # fmt: skip


async def test_0059_and_back_restores_0058s_functions_checks_and_width_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0058")
    before = await _rows(db, ABANDON_STATE)
    await asyncio.to_thread(upgrade, db, "0059")
    after = (await _rows(db, ABANDON_STATE))[0]
    assert (
        "start_abandoned" in str(after[0]) and "abandon_start" in str(after[1]) and "start_abandoned" in str(after[3])
    )
    assert after[4] == "character varying(4000)"
    await asyncio.to_thread(downgrade, db, "0058")
    assert await _rows(db, ABANDON_STATE) == before


async def test_0059s_downgrade_refuses_while_an_abandonments_record_is_kept(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0059")
    await _sql(db, ABANDONED)
    with pytest.raises(Exception, match="0059 refused"):
        await asyncio.to_thread(downgrade, db, "0058")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0059",)]


async def test_0059s_downgrade_never_drops_a_record_written_while_it_checks(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0059")
    [outcome] = await _while_written(db, ABANDONED, "0058")
    assert isinstance(outcome, Exception) and "0059 refused" in str(outcome), outcome


# 0060 (task 11): provenance. Every execution row from before is `legacy`: an incomplete erasure with one loses its
# bound (its close kept as `verified_close`), a completed one is qualified, its completion kept, and alerted once.
async def _tenant(db: str) -> uuid.UUID:
    made = await _rows(db, "INSERT INTO tenants (id, name, slug) VALUES (gen_random_uuid(), 'T', "
                           "substr(md5(random()::text), 1, 12)) RETURNING id")  # fmt: skip
    return uuid.UUID(str(made[0][0]))


async def test_0060_marks_every_known_execution_legacy_and_holds_or_qualifies_its_erasure(db: str) -> None:
    import structlog

    await asyncio.to_thread(upgrade, db, "0059")
    completed, incomplete, clean = [await _tenant(db) for _ in range(3)]
    await _sql(db, "INSERT INTO tenant_erasures (tenant_id, requested_by, step, completed_at) VALUES "
                   f"('{completed}', gen_random_uuid(), 100, '2026-09-01T00:00:00Z'), "
                   f"('{clean}', gen_random_uuid(), 100, '2026-09-02T00:00:00Z')")  # fmt: skip
    await _sql(db, "INSERT INTO tenant_erasures (tenant_id, requested_by, step, latest_close, check_after) VALUES "
                   f"('{incomplete}', gen_random_uuid(), 90, '2026-10-01T00:00:00Z', "
                   "'2026-10-31T00:00:00Z')")  # fmt: skip
    rows = ((completed, "execution", "w:1", "'r1'"), (completed, "execution", "w:2", "NULL"),
            (completed, "schedule", "s:1", "NULL"), (incomplete, "execution", "w:3", "'r3'"),
            (clean, "schedule", "s:2", "NULL"))  # fmt: skip
    for tenant, kind, workflow_id, run_id in rows:
        await _sql(db, "INSERT INTO tenant_erasure_known (tenant_id, kind, workflow_id, run_id) "
                       f"VALUES ('{tenant}', '{kind}', '{workflow_id}', {run_id})")  # fmt: skip
    with structlog.testing.capture_logs() as logs:
        await asyncio.to_thread(upgrade, db, "0060")
    known = await _rows(db, "SELECT kind, workflow_id, provenance FROM tenant_erasure_known ORDER BY workflow_id")
    assert known == [("schedule", "s:1", None), ("schedule", "s:2", None), ("execution", "w:1", "legacy"),
                     ("execution", "w:2", "legacy"), ("execution", "w:3", "legacy")]  # fmt: skip
    erasures = await _rows(db, "SELECT tenant_id, step, completed_at IS NOT NULL, qualification, "
                               "legacy_completed_at = completed_at, verified_close, latest_close, check_after "
                               "FROM tenant_erasures")  # fmt: skip
    by = {row[0]: row[1:] for row in erasures}
    assert by[completed][:4] == (100, True, "legacy_completion_unproven", True)  # its completion kept, qualified
    assert by[clean][:4] == (100, True, None, None)
    assert str(by[incomplete][4])[:10] == "2026-10-01" and by[incomplete][5:] == (None, None)  # held: no bound
    assert [e["tenant"] for e in logs if e["event"] == "erasure_legacy_unproven"] == [str(completed)]


ERASURE_COLUMNS = """SELECT string_agg(attrelid::regclass || '.' || attname, ','
                         ORDER BY attrelid::regclass::text, attnum)
  FROM pg_attribute WHERE attrelid IN ('public.tenant_erasures'::regclass, 'public.tenant_erasure_known'::regclass)
   AND attnum > 0 AND NOT attisdropped"""


async def test_0060_and_back_restores_0059s_erasure_tables_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0059")
    before = await _rows(db, ERASURE_COLUMNS)
    await asyncio.to_thread(upgrade, db, "0060")
    assert "provenance" in str((await _rows(db, ERASURE_COLUMNS))[0][0])
    await asyncio.to_thread(downgrade, db, "0059")
    assert await _rows(db, ERASURE_COLUMNS) == before


async def _gone_row(db: str) -> str:
    tenant = await _tenant(db)
    await _sql(db, f"INSERT INTO tenant_erasures (tenant_id, requested_by) VALUES ('{tenant}', gen_random_uuid())")
    return (f"INSERT INTO tenant_erasure_known (tenant_id, kind, workflow_id, run_id, provenance) "
            f"VALUES ('{tenant}', 'execution', 'w:1', 'r1', 'gone')")  # fmt: skip


async def test_0060s_downgrade_refuses_while_a_provenance_is_kept(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0060")
    await _sql(db, await _gone_row(db))
    with pytest.raises(Exception, match="0060 refused"):
        await asyncio.to_thread(downgrade, db, "0059")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0060",)]


async def test_0060s_downgrade_never_drops_a_provenance_written_while_it_checks(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0060")
    [outcome] = await _while_written(db, await _gone_row(db), "0059")
    assert isinstance(outcome, Exception) and "0060 refused" in str(outcome), outcome


# 0061 (task 12): the predicates. Its downgrade restores 0040's item states exactly, and refuses while an item is
# absent.
PREDICATES = """SELECT (SELECT pg_get_constraintdef(oid) FROM pg_constraint
                         WHERE conname = 'tenant_erasure_items_state'),
  to_regprocedure('erasure_unresolved(uuid)'), to_regprocedure('erasure_proven(uuid)'),
  to_regclass('public.unresolved_sends_tenant')"""


async def _absent_item(db: str) -> str:
    tenant = await _tenant(db)
    await _sql(db, f"INSERT INTO tenant_erasures (tenant_id, requested_by) VALUES ('{tenant}', gen_random_uuid())")
    return ("INSERT INTO tenant_erasure_items (tenant_id, step, kind, workflow_id, source, state) "
            f"VALUES ('{tenant}', 60, 'execution', 'w:1', 'tests', 'absent')")  # fmt: skip


async def test_0061_and_back_restores_0060s_item_states_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0060")
    before = await _rows(db, PREDICATES)
    await asyncio.to_thread(upgrade, db, "0061")
    after = (await _rows(db, PREDICATES))[0]
    assert "absent" in str(after[0]) and None not in after
    await asyncio.to_thread(downgrade, db, "0060")
    assert await _rows(db, PREDICATES) == before


async def test_0061s_downgrade_refuses_while_an_item_is_absent(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0061")
    await _sql(db, await _absent_item(db))
    with pytest.raises(Exception, match="0061 refused"):
        await asyncio.to_thread(downgrade, db, "0060")


async def test_0061s_downgrade_never_drops_an_absent_item_written_while_it_checks(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0061")
    [outcome] = await _while_written(db, await _absent_item(db), "0060")
    assert isinstance(outcome, Exception) and "0061 refused" in str(outcome), outcome


# 0062 (task 14): the lifelong check's selection, a function alone. No row is kept, so its downgrade refuses nothing.
RECHECKED = """SELECT to_regprocedure('erasures_rechecked()') IS NOT NULL,
  coalesce((SELECT has_function_privilege('dewpoint_retention', 'erasures_rechecked()', 'EXECUTE')
            WHERE to_regprocedure('erasures_rechecked()') IS NOT NULL), false),
  coalesce((SELECT has_function_privilege('dewpoint_api', 'erasures_rechecked()', 'EXECUTE')
            WHERE to_regprocedure('erasures_rechecked()') IS NOT NULL), false)"""


async def test_0062_and_back_adds_and_drops_the_rechecked_selection_for_retention_alone(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0061")
    assert await _rows(db, RECHECKED) == [(False, False, False)]
    await asyncio.to_thread(upgrade, db, "0062")
    assert await _rows(db, RECHECKED) == [(True, True, False)]
    await asyncio.to_thread(downgrade, db, "0061")
    assert await _rows(db, RECHECKED) == [(False, False, False)]


# 0063 (task 15): `retained_out`'s evidence. Its downgrade refuses while a captured close, a registration or a
# qualification interval is kept: what a qualification rests on is never dropped.
RETAINED = """SELECT (SELECT string_agg(attname, ',' ORDER BY attnum) FROM pg_attribute
                       WHERE attrelid = 'public.execution_evidence'::regclass AND attnum > 0 AND NOT attisdropped),
  to_regclass('public.target_namespace_registrations'), to_regclass('public.target_qualification_intervals')"""
INTERVAL = ("INSERT INTO target_qualification_intervals (namespace, valid_from, valid_to, evidence) "
            "VALUES ('ns', now() - interval '1 day', now(), 'tests')")  # fmt: skip


async def _closed_evidence(db: str) -> str:
    tenant = await _tenant(db)
    return ("INSERT INTO execution_evidence (tenant_id, workflow_id, run_id, started_at, closed_at, closed_seen_at) "
            f"VALUES ('{tenant}', 'w:1', 'r1', now(), now(), now())")  # fmt: skip


async def test_0063_and_back_restores_0062s_evidence_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0062")
    before = await _rows(db, RETAINED)
    await asyncio.to_thread(upgrade, db, "0063")
    after = (await _rows(db, RETAINED))[0]
    assert "closed_at,closed_seen_at" in str(after[0]) and None not in after
    await asyncio.to_thread(downgrade, db, "0062")
    assert await _rows(db, RETAINED) == before


@pytest.mark.parametrize("kept", ["interval", "registration", "close"])
async def test_0063s_downgrade_refuses_while_its_evidence_is_kept(db: str, kept: str) -> None:
    await asyncio.to_thread(upgrade, db, "0063")
    write = {"interval": INTERVAL, "close": await _closed_evidence(db),
             "registration": "INSERT INTO target_namespace_registrations (namespace, registered_at, evidence) "
                             "VALUES ('ns', now(), 'tests')"}[kept]  # fmt: skip
    await _sql(db, write)
    with pytest.raises(Exception, match="0063 refused"):
        await asyncio.to_thread(downgrade, db, "0062")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0063",)]


async def test_0063s_downgrade_never_drops_evidence_written_while_it_checks(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0063")
    [outcome] = await _while_written(db, INTERVAL, "0062")
    assert isinstance(outcome, Exception) and "0063 refused" in str(outcome), outcome


# 0064 (gate D, the owner's item 3): `erasures_held` counts stopped erasures too. The function alone is replaced, its
# grant kept; the downgrade restores 0058's text exactly.
COUNTS_DEF = """SELECT pg_get_functiondef('unresolved_sends_counts(text)'::regprocedure),
  has_function_privilege('dewpoint_api', 'unresolved_sends_counts(text)', 'EXECUTE'),
  has_function_privilege('dewpoint_retention', 'unresolved_sends_counts(text)', 'EXECUTE')"""


async def test_0064_and_back_counts_stopped_erasures_held_and_restores_0058s_count_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0063")
    before = await _rows(db, COUNTS_DEF)
    assert "e.stopped_at IS NULL" in str(before[0][0])
    await asyncio.to_thread(upgrade, db, "0064")
    after = (await _rows(db, COUNTS_DEF))[0]
    assert "stopped_at" not in str(after[0]) and after[1:] == (True, False)
    await asyncio.to_thread(downgrade, db, "0063")
    assert await _rows(db, COUNTS_DEF) == before


# 0065 (the final gate, the owner's ruling): the reveal re-checks that its actor is still an active platform admin.
REVEAL_DEF = """SELECT pg_get_functiondef('recovery.unresolved_send_reveal(uuid)'::regprocedure),
  has_function_privilege('dewpoint_recovery', 'recovery.unresolved_send_reveal(uuid)', 'EXECUTE'),
  has_function_privilege('dewpoint_api', 'recovery.unresolved_send_reveal(uuid)', 'EXECUTE')"""


async def test_0065_and_back_rechecks_the_actor_and_restores_0058s_reveal_exactly(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0064")
    before = await _rows(db, REVEAL_DEF)
    assert "platform_admin_active" not in str(before[0][0])
    await asyncio.to_thread(upgrade, db, "0065")
    after = (await _rows(db, REVEAL_DEF))[0]
    assert "platform_admin_active(v.actor_id)" in str(after[0]) and after[1:] == (True, False)
    await asyncio.to_thread(downgrade, db, "0064")
    assert await _rows(db, REVEAL_DEF) == before


RECOVERY_ACCESS = {  # what 0065's downgrade refuses while kept: 0058's reveal would disclose through it
    "an inspection": INSPECTION,
    "an unrevoked login's mapping": KEPT["a login's mapping"],
    "a member of the recovery group": "CREATE ROLE rcv_q0065 LOGIN IN ROLE dewpoint_recovery",
}


@pytest.mark.parametrize("kept", list(RECOVERY_ACCESS))
async def test_0065s_downgrade_refuses_while_recovery_access_or_an_inspection_is_kept(db: str, kept: str) -> None:
    await asyncio.to_thread(upgrade, db, "0065")
    await _sql(db, RECOVERY_ACCESS[kept])
    try:
        with pytest.raises(Exception, match="0065 refused"):
            await asyncio.to_thread(downgrade, db, "0064")
        assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0065",)]
    finally:
        await _sql(db, "DROP ROLE IF EXISTS rcv_q0065")  # the cluster's: the module's other databases share it


async def test_0065s_downgrade_passes_a_revoked_mapping(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0065")
    await _sql(db, "INSERT INTO recovery_operators (login, user_id, provisioned_by, provisioned_at, revoked_by, "
                   "revoked_at) VALUES ('rcv_gone', gen_random_uuid(), 'admin', now(), 'admin', now())")  # fmt: skip
    await asyncio.to_thread(downgrade, db, "0064")
    assert await _rows(db, "SELECT version_num FROM alembic_version") == [("0064",)]


async def test_0065s_downgrade_never_drops_an_inspection_recorded_while_it_checks(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0065")
    [outcome] = await _while_written(db, INSPECTION, "0064")
    assert isinstance(outcome, Exception) and "0065 refused" in str(outcome), outcome
