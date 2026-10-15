# SPDX-License-Identifier: Apache-2.0
"""Migration 0072 on disposable databases, in a cluster of this module's own (editor 4d-1b, B8): `draft_snapshots`,
immutable and one per workflow and version hash; a request or a run frozen on exactly one of a version or a draft
snapshot, a snapshot's only in simulate, a target only with a snapshot; its downgrade refuses while a snapshot is
kept. Its online steps are interrupted, bounded and compared with a fresh database by `test_online.py`, as every
online migration's are."""

import asyncio
from collections.abc import AsyncIterator, Iterator

import asyncpg
import pytest
from testcontainers.community.postgres import PostgresContainer

from tests.migrations.support import copy, downgrade, upgrade
from tests.migrations.test_0053 import _drop, _sql
from tests.probes.migration_locks import seed

ROOTS = 5
FIELDS = ("graph, node_refs, engine_abi, cel_profile, connection_ids, subflow_version_ids, failure_handler_version_id, "
          "input_schema, output_schema, vars_schema, expressions, tainted_sites, output_taint, open_scopes_cap, "
          "loop_depth, closure_version_ids, closure_workflow_ids, closure_node_refs, closure_cel_profiles, "
          "closure_depth, graph_hash, version_hash")  # fmt: skip
SNAPSHOT = (f"INSERT INTO draft_snapshots (tenant_id, workflow_id, draft_revision, {FIELDS}) "
            f"SELECT v.tenant_id, v.workflow_id, 3, {FIELDS.replace('version_hash', '$1')} FROM workflow_versions v "
            "JOIN run_requests r ON r.workflow_version_id = v.id ORDER BY r.id LIMIT 1 RETURNING id")  # fmt: skip
REQUEST = ("UPDATE run_requests SET workflow_version_id = $2, draft_snapshot_id = $3, draft_revision = $4, mode = $5, "
           "target_step_id = $6 WHERE id = (SELECT r.id FROM run_requests r JOIN draft_snapshots s "
           "ON s.workflow_id = r.workflow_id WHERE s.id = $1 ORDER BY r.id LIMIT 1)")  # fmt: skip
RUN = ("UPDATE runs SET workflow_version_id = $2, draft_snapshot_id = $3, mode = $4, target_step_id = $5 "
       "WHERE id = (SELECT r.id FROM runs r JOIN draft_snapshots s ON s.workflow_id = r.workflow_id "
       "WHERE s.id = $1 ORDER BY r.id LIMIT 1)")  # fmt: skip


async def _one(url: str, query: str, *args: object) -> object:
    c = await asyncpg.connect(url)
    try:
        return await c.fetchval(query, *args)
    finally:
        await c.close()


@pytest.fixture(scope="module")
def cluster() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url().rsplit("/", 1)[0]


@pytest.fixture(scope="module")
def template(cluster: str) -> str:
    """A seeded database at 0071, as the deployments that run 0072 are."""
    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0071"'))
    upgrade(f"{cluster}/t0071", "0034")
    asyncio.run(seed(f"{cluster}/t0071", ROOTS))
    upgrade(f"{cluster}/t0071", "0071")
    return "t0071"


@pytest.fixture
async def db(cluster: str, template: str) -> AsyncIterator[str]:
    url = await copy(cluster, template)
    yield url
    await _drop(cluster, url.rsplit("/", 1)[1])


async def test_a_snapshot_is_one_per_workflow_and_version_hash_and_never_changes(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0072")
    snapshot = await _one(db, SNAPSHOT, "a" * 64)
    with pytest.raises(asyncpg.UniqueViolationError):
        await _one(db, SNAPSHOT, "a" * 64)
    with pytest.raises(asyncpg.RaiseError, match="draft_snapshots rows are immutable"):
        await _sql(db, f"UPDATE draft_snapshots SET draft_revision = 4 WHERE id = '{snapshot}'")
    await _sql(db, f"DELETE FROM draft_snapshots WHERE id = '{snapshot}'")  # only retention may, by its grants


async def test_a_request_and_a_run_are_frozen_on_a_version_or_a_simulated_snapshot(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0072")
    s = await _one(db, SNAPSHOT, "b" * 64)
    version = await _one(db, "SELECT v.id FROM workflow_versions v JOIN draft_snapshots s "
                             "ON s.workflow_id = v.workflow_id ORDER BY v.number LIMIT 1")  # fmt: skip
    target = "00000000-0000-4000-8000-000000000001"
    refused = [  # (version, snapshot, revision, mode, target)
        (version, s, 3, "simulate", None),  # both
        (None, s, 3, "live", None),  # a snapshot, live
        (version, None, None, "simulate", target),  # a target without a snapshot
        (None, s, None, "simulate", None),  # a snapshot without its revision
    ]
    for args in refused:
        with pytest.raises(asyncpg.CheckViolationError):
            await _one(db, REQUEST, s, *args)
    await _one(db, REQUEST, s, None, s, 3, "simulate", target)
    for args in ((None, None, "simulate", None), (version, s, "simulate", None), (None, s, "live", None)):
        with pytest.raises(asyncpg.CheckViolationError):
            await _one(db, RUN, s, *args)
    await _one(db, RUN, s, None, s, "simulate", target)
    with pytest.raises(asyncpg.ForeignKeyViolationError):  # a snapshot another run or request still names
        await _sql(db, f"DELETE FROM draft_snapshots WHERE id = '{s}'")


async def test_the_downgrade_refuses_while_a_snapshot_is_kept(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0072")
    s = await _one(db, SNAPSHOT, "c" * 64)
    with pytest.raises(Exception, match="0072 refused"):
        await asyncio.to_thread(downgrade, db, "0071")
    await _sql(db, f"DELETE FROM draft_snapshots WHERE id = '{s}'")
    await asyncio.to_thread(downgrade, db, "0071")
    assert await _one(db, "SELECT to_regclass('public.draft_snapshots')") is None
    nullable = await _one(db, "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'runs' "
                              "AND column_name = 'workflow_version_id'")  # fmt: skip
    assert nullable == "NO"
