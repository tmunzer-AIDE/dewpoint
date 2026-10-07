# SPDX-License-Identifier: Apache-2.0
"""Online migrations (the 2b-4b plan's M1a; the owner's D15, option B): 0035 to 0044 upgrade a database in use. Each
committed step keeps every boundary its migration keeps before and after it; an interrupted backfill goes on from its
committed batches; a step behind a lock gives way rather than keep normal operations waiting, until it's taken or its
attempts are spent, naming it. Each test copies a database seeded at a deployed starting revision (D15's two paths, a
few hundred root runs), in a Postgres 16 container of its own: the suite's database is at the head already."""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from migrations import online
from tests.migrations.support import (
    autocommitted,
    copy,
    downgrade,
    fingerprint,
    recorded,
    schema,
    security,
    upgrade,
    violations,
)
from tests.probes.migration_locks import seed

ROOTS = 300  # root runs seeded: 450 runs, in batches of `BATCH` below
BATCH = 40
PATHS = {  # each deployed starting revision's migrations, in order (D15)
    "0034": ["0041", "0042", "0035", "0036", "0037", "0038", "0039", "0040", "0043", "0044"],
    "0042": ["0035", "0036", "0037", "0038", "0039", "0040", "0043", "0044"],
}
TREE = """WITH RECURSIVE tree AS (
  SELECT id, id AS root FROM runs WHERE parent_run_id IS NULL
  UNION ALL
  SELECT r.id, t.root FROM runs r JOIN tree t ON r.parent_run_id = t.id
) SELECT count(*) FROM runs JOIN tree USING (id) WHERE runs.root_run_id IS DISTINCT FROM tree.root"""
REVISIONS = Path(__file__).with_name("revisions.json")  # the original migrations' (bc4c840), by revision
UNRECORDED = """SELECT count(*) FROM runs r WHERE r.parent_run_id IS NULL AND NOT EXISTS
  (SELECT 1 FROM execution_evidence e WHERE e.workflow_id = 't:' || r.tenant_id || ':run:' || r.id)"""


@pytest.fixture(scope="module")
def cluster() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url().rsplit("/", 1)[0]


async def _create(base: str, name: str) -> None:
    c = await asyncpg.connect(f"{base}/postgres")
    try:
        await c.execute(f'CREATE DATABASE "{name}"')
    finally:
        await c.close()


@pytest.fixture(scope="module")
def templates(cluster: str) -> dict[str, str]:
    """A database at each starting revision, seeded: what each test copies."""
    made = {}
    for start in PATHS:
        asyncio.run(_create(cluster, f"start{start}"))
        upgrade(f"{cluster}/start{start}", start)
        asyncio.run(seed(f"{cluster}/start{start}", ROOTS))
        made[start] = f"start{start}"
    return made


@pytest.fixture(autouse=True)
def _batches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(online, "BATCH", BATCH)


async def read[T](url: str, fn: Callable[[Connection], T]) -> T:
    return await asyncio.to_thread(autocommitted, url, fn)


async def scalar(url: str, query: str) -> Any:
    c = await asyncpg.connect(url)
    try:
        return await c.fetchval(query)
    finally:
        await c.close()


async def execute(url: str, statements: str) -> None:
    c = await asyncpg.connect(url)
    try:
        await c.execute(statements)
    finally:
        await c.close()


def by_migration(steps: list[tuple[str, dict[str, Any]]]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for name, state in steps:
        grouped.setdefault(name.split(" ", 1)[0], []).append((name, state))
    return grouped


@pytest.mark.parametrize("start", PATHS)
async def test_every_committed_step_keeps_the_boundaries_its_migration_keeps(cluster, templates, start) -> None:
    """Every migration on the path commits in steps, and the state each step commits breaks no boundary its migration
    keeps before and after it (`support.violations`): no privilege, policy, row-level security or security-definer
    function in a form neither has, no new privilege without its restrictive policy, no key or trigger both have
    missing. Each migration's end is its revision's state, as upgrading one revision at a time leaves it."""
    url = await copy(cluster, templates[start])
    before = await read(url, security)
    with recorded() as steps:
        await asyncio.to_thread(upgrade, url)
    migrated = by_migration(steps)
    assert list(migrated) == PATHS[start]
    found, at_start = [], before
    for revision in PATHS[start]:
        at_end = migrated[revision][-1][1]
        for name, state in migrated[revision]:
            found += [f"{name}: {v}" for v in violations(at_start, state, at_end)]
        at_start = at_end
    assert found == []
    assert await read(url, security) == at_start


async def test_an_upgraded_database_ends_as_a_fresh_one_does(cluster, templates) -> None:
    """Upgraded online from 0034 with its runs, a database ends with the schema an empty one upgraded to the head
    has: every constraint validated, every index valid, every column, function, trigger, policy and grant the same."""
    url = await copy(cluster, templates["0034"])
    await asyncio.to_thread(upgrade, url)
    await _create(cluster, "fresh")
    await asyncio.to_thread(upgrade, f"{cluster}/fresh")
    upgraded, fresh = await read(url, schema), await read(f"{cluster}/fresh", schema)
    assert {k: v for k, v in upgraded.items() if v != fresh[k]} == {}
    assert all(valid and ready for _, valid, ready in upgraded["valid"])
    assert all(validated for *_, validated in upgraded["constraints"])
    assert await scalar(url, TREE) == 0
    assert await scalar(url, UNRECORDED) == 0


async def test_each_revision_ends_as_the_original_left_it() -> None:
    """Run revision by revision from an empty database, the online migrations leave each revision's schema exactly as
    the original ones did (bc4c840's, fingerprinted by `tests/probes/migration_equivalence.py`): every migration's
    committed end is the original's state, grants, policies and roles included. A cluster of its own: roles are the
    cluster's, and the other tests' upgrades make them."""
    expected = json.loads(REVISIONS.read_text())
    differ = {}
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        url = pg.get_connection_url()
        for revision, parts in expected.items():
            await asyncio.to_thread(upgrade, url, revision)
            got = await read(url, fingerprint)
            differ[revision] = sorted(part for part in parts if got[part] != parts[part])
    assert {revision: parts for revision, parts in differ.items() if parts} == {}


async def test_the_round_trip_restores_the_starting_revision() -> None:
    """From 0034 with its runs: upgraded to the head, then downgraded to 0034 (the downgrades unchanged, a transaction
    per migration), the schema is 0034's again; upgraded again, every run has its tree's root. A cluster of its own:
    the downgrade drops roles, which the other tests' databases hold grants to."""
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        await round_trip(pg.get_connection_url())


async def round_trip(url: str) -> None:
    await asyncio.to_thread(upgrade, url, "0034")
    await seed(url, ROOTS)
    before = await read(url, schema)
    await asyncio.to_thread(upgrade, url)
    await asyncio.to_thread(downgrade, url, "0034")
    assert await read(url, schema) == before
    await asyncio.to_thread(upgrade, url)
    assert await scalar(url, TREE) == 0


class Interrupted(Exception):
    pass


@pytest.mark.parametrize(("at", "revision"), [("0037 runs.root_run_id", "0036"), ("0039 execution_evidence", "0038")])
async def test_an_interrupted_backfill_goes_on_from_its_committed_batches(cluster, templates, at, revision) -> None:
    """A backfill interrupted after its third batch (the process killed, the connection lost) leaves those batches
    committed and its migration unrecorded; the upgrade run again goes on from them and ends as one never interrupted:
    each run's root its tree's, each root run's execution recorded."""
    url = await copy(cluster, templates["0034"])
    batches: list[str] = []

    def interrupt(conn: Connection, name: str) -> None:
        if name.startswith(f"{at} backfill"):
            batches.append(name)
            if len(batches) == 3:
                raise Interrupted

    online.AFTER.append(interrupt)
    try:
        with pytest.raises(Interrupted):
            await asyncio.to_thread(upgrade, url)
    finally:
        online.AFTER.remove(interrupt)
    assert await scalar(url, "SELECT version_num FROM alembic_version") == revision
    if at.startswith("0037"):
        assert await scalar(url, "SELECT count(*) FROM runs WHERE root_run_id IS NOT NULL") == 3 * BATCH
    else:
        assert await scalar(url, "SELECT count(*) FROM execution_evidence") == 3 * BATCH
    with recorded() as steps:
        await asyncio.to_thread(upgrade, url)
    assert await scalar(url, "SELECT version_num FROM alembic_version") == "0044"
    assert await scalar(url, TREE) == 0
    assert await scalar(url, UNRECORDED) == 0
    remaining = (450 if at.startswith("0037") else ROOTS) - 3 * BATCH  # runs, or root runs, not done yet
    assert len([n for n, _ in steps if n.startswith(f"{at} backfill")]) == remaining // BATCH + 1
    straight = await copy(cluster, templates["0034"])
    await asyncio.to_thread(upgrade, straight)
    assert await read(url, schema) == await read(straight, schema)


class Holder:
    """A writer's open transaction on `tenants` (its `ROW EXCLUSIVE` lock), as any write holds until it commits."""

    def __init__(self, url: str) -> None:
        self.url = url

    async def __aenter__(self) -> "Holder":
        self.c = await asyncpg.connect(self.url)
        self.tx = self.c.transaction()
        await self.tx.start()
        await self.c.execute("LOCK TABLE tenants IN ROW EXCLUSIVE MODE")
        return self

    async def release(self) -> None:
        if not self.c.is_closed():
            await self.tx.rollback()
            await self.c.close()

    async def __aexit__(self, *exc: object) -> None:
        await self.release()


def gave_way(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "alembic.online" and "gave way" in r.getMessage()]


class GivingWay(logging.Handler):
    """Set once a step gives way, from the upgrade's thread."""

    def __init__(self) -> None:
        super().__init__()
        self.loop, self.seen = asyncio.get_running_loop(), asyncio.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if "gave way" in record.getMessage():
            self.loop.call_soon_threadsafe(self.seen.set)


async def test_a_step_behind_a_held_lock_gives_way_until_it_is_released(cluster, templates, caplog) -> None:
    """Behind a writer's open transaction, a step waits at most its budget, gives way, and tries again until the
    writer commits: a read of `tenants` meanwhile waits less than a second, never the writer's whole hold."""
    caplog.set_level(logging.INFO, logger="alembic.online")
    url = await copy(cluster, templates["0042"])
    reads: list[float] = []
    stop = asyncio.Event()

    async def reader() -> None:
        c = await asyncpg.connect(url)
        try:
            while not stop.is_set():
                t0 = time.monotonic()
                await c.fetch("SELECT id, status FROM tenants LIMIT 5")
                reads.append(time.monotonic() - t0)
                await asyncio.sleep(0.02)
        finally:
            await c.close()

    reading = asyncio.create_task(reader())
    giving_way = GivingWay()
    logging.getLogger("alembic.online").addHandler(giving_way)
    async with Holder(url) as holder:
        upgrading = asyncio.create_task(asyncio.to_thread(upgrade, url))
        try:
            await asyncio.wait_for(giving_way.seen.wait(), 60)
        finally:
            logging.getLogger("alembic.online").removeHandler(giving_way)
        await asyncio.sleep(1.5)  # held well past a step's budget
        await holder.release()
        try:
            await asyncio.wait_for(upgrading, 120)
        finally:
            stop.set()
            await reading
    assert gave_way(caplog) and all(m.endswith("(lock)") for m in gave_way(caplog))
    assert await scalar(url, "SELECT version_num FROM alembic_version") == "0044"
    assert max(reads) < 1.0


async def test_a_lock_never_released_stops_the_upgrade_naming_its_step(cluster, templates, monkeypatch) -> None:
    """A step that gives way `ATTEMPTS` times stops the upgrade, naming itself, in bounded time; its migration stays
    unrecorded, and the upgrade run again once the lock is free goes on to the head."""
    monkeypatch.setattr(online, "ATTEMPTS", 3)
    url = await copy(cluster, templates["0042"])
    t0 = time.monotonic()
    async with Holder(url):
        upgrading = asyncio.create_task(asyncio.to_thread(upgrade, url))
        with pytest.raises(online.StepFailedError, match=r"^online step 0037 .+ gave way 3 times \(lock\)"):
            await asyncio.wait_for(asyncio.shield(upgrading), 60)
    assert time.monotonic() - t0 < 30
    assert await scalar(url, "SELECT version_num FROM alembic_version") == "0036"
    await asyncio.to_thread(upgrade, url)
    assert await scalar(url, "SELECT version_num FROM alembic_version") == "0044"


# The steps themselves, on a scratch database


@pytest.fixture
async def scratch(cluster: str) -> str:
    name = f"scratch{time.monotonic_ns()}"
    await _create(cluster, name)
    return f"{cluster}/{name}"


async def run[T](url: str, fn: Callable[[Connection], T]) -> T:
    return await asyncio.to_thread(autocommitted, url, fn)


async def exists(url: str, table: str) -> bool:
    return bool(await scalar(url, f"SELECT to_regclass('public.{table}') IS NOT NULL"))


async def test_a_step_that_outruns_its_budget_gives_way_and_stops_after_its_attempts(scratch, monkeypatch) -> None:
    monkeypatch.setattr(online, "ATTEMPTS", 2)
    with pytest.raises(online.StepFailedError, match=r"gave way 2 times \(budget\)"):
        await run(scratch, lambda c: online.step(c, "slow", "CREATE TABLE t1 (x int)", "SELECT pg_sleep(0.4)",
                                                 "SELECT pg_sleep(0.4)"))  # fmt: skip
    assert not await exists(scratch, "t1")


async def test_a_failing_statement_rolls_its_step_back_whole_and_stops(scratch) -> None:
    tries: list[str] = []
    online.AFTER.append(lambda c, name: tries.append(name))
    try:
        with pytest.raises(DBAPIError) as raised:
            await run(scratch, lambda c: online.step(c, "failing", "CREATE TABLE t2 (x int)", "SELECT 1 / 0"))
    finally:
        online.AFTER.pop()
    assert getattr(raised.value.orig, "sqlstate", None) == "22012"
    assert not await exists(scratch, "t2") and tries == []


async def test_a_step_gives_way_to_a_writer_it_would_deadlock(scratch, caplog) -> None:
    """A step holding one table and waiting for a second, which a writer holds while it waits for the first: the step
    gives way within its budget, short of the server's deadlock check, so the writer goes on and commits; the step
    commits on a later attempt."""
    caplog.set_level(logging.INFO, logger="alembic.online")
    await execute(scratch, "CREATE TABLE a (x int); CREATE TABLE b (x int)")
    w = await asyncpg.connect(scratch)
    try:
        tx = w.transaction()
        await tx.start()
        await w.execute("INSERT INTO b VALUES (1)")
        stepping = asyncio.create_task(run(scratch, lambda c: online.step(
            c, "both", "LOCK TABLE a IN ACCESS EXCLUSIVE MODE", "LOCK TABLE b IN ACCESS EXCLUSIVE MODE")))  # fmt: skip
        await asyncio.sleep(0.15)  # the step holds `a`, and waits for `b`
        t0 = time.monotonic()
        await w.execute("INSERT INTO a VALUES (1)")
        waited = time.monotonic() - t0
        await tx.commit()
        await asyncio.wait_for(stepping, 30)
    finally:
        await w.close()
    assert waited < 1.0
    assert gave_way(caplog)[0] == "online step both: attempt 1 gave way (lock)"
    assert all(m.endswith("(lock)") for m in gave_way(caplog))


async def test_an_index_an_interrupted_build_left_invalid_is_built_again(scratch) -> None:
    await execute(scratch, "CREATE TABLE u (x int); INSERT INTO u VALUES (1), (1)")
    with pytest.raises(asyncpg.UniqueViolationError):  # a build that fails leaves its index, invalid
        await execute(scratch, "CREATE UNIQUE INDEX CONCURRENTLY u_x ON u (x)")
    await execute(scratch, "DELETE FROM u WHERE ctid = (SELECT max(ctid) FROM u)")
    await run(scratch, lambda c: online.index(c, "u_x", "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS u_x ON u (x)"))
    assert await scalar(scratch, "SELECT indisvalid FROM pg_index WHERE indexrelid = 'u_x'::regclass") is True


async def test_a_backfill_commits_each_batch_and_goes_on_from_them(scratch) -> None:
    await execute(scratch, "CREATE TABLE v (id int PRIMARY KEY, done bool NOT NULL DEFAULT false); "
                           "INSERT INTO v (id) SELECT generate_series(1, 25)")  # fmt: skip
    bounds = "SELECT max(id), count(*) FROM (SELECT id FROM v WHERE id > :after AND NOT done ORDER BY id LIMIT :n) b"
    apply = "UPDATE v SET done = true WHERE id > :after AND id <= :hi AND NOT done"
    names: list[str] = []

    def interrupt(c: Connection, name: str) -> None:
        names.append(name)
        if len(names) == 2:
            raise Interrupted

    online.AFTER.append(interrupt)
    try:
        with pytest.raises(Interrupted):
            await run(scratch, lambda c: online.batches(c, "v backfill", bounds, apply, first=0, size=10))
    finally:
        online.AFTER.remove(interrupt)
    assert await scalar(scratch, "SELECT count(*) FROM v WHERE done") == 20
    assert await run(scratch, lambda c: online.batches(c, "v backfill", bounds, apply, first=0, size=10)) == 5
    assert names == ["v backfill (batch 1)", "v backfill (batch 2)"]
    assert await scalar(scratch, "SELECT count(*) FROM v WHERE NOT done") == 0
