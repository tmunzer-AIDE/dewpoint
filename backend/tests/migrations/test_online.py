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
import uuid
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from testcontainers.community.postgres import PostgresContainer

from migrations import online
from tests.migrations.support import (
    ADDED,
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
from tests.probes.migration_locks import Load, seed

ROOTS = 300  # root runs seeded: 450 runs, in batches of `BATCH` below
BATCH = 40
HEAD = "0051"
# each deployed starting revision's migrations, in order (D15)
LATER = ["0035", "0036", "0037", "0038", "0039", "0040", "0043", "0044", "0048", "0049", "0050", "0051"]
PATHS = {"0034": ["0041", "0042", *LATER], "0042": LATER}
TREE = """WITH RECURSIVE tree AS (
  SELECT id, id AS root FROM runs WHERE parent_run_id IS NULL
  UNION ALL
  SELECT r.id, t.root FROM runs r JOIN tree t ON r.parent_run_id = t.id
) SELECT count(*) FROM runs JOIN tree USING (id) WHERE runs.root_run_id IS DISTINCT FROM tree.root"""
REVISIONS = Path(__file__).with_name("revisions.json")  # the original migrations' (bc4c840), by revision
UNINCARNATED = """SELECT count(*) FROM schedules s WHERE NOT EXISTS
  (SELECT 1 FROM schedule_incarnations i WHERE i.schedule_id = s.id AND i.number = 0 AND i.backfilled)"""
UNSPANNED = """SELECT count(*) FROM schedule_incarnations i WHERE i.backfilled AND NOT EXISTS
  (SELECT 1 FROM schedule_intervals v WHERE v.temporal_id = i.temporal_id AND v.reason = 'before_migration')"""
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


@pytest.mark.parametrize("start", PATHS)
async def test_an_upgraded_database_ends_as_a_fresh_one_does(cluster, templates, start) -> None:
    """Upgraded online from either path with its runs and schedules, a database ends with the schema an empty one
    upgraded to the head has: every constraint validated, every index valid, every column, function, trigger, policy
    and grant the same; its data backfilled: each run's root its tree's, each root's execution recorded, each schedule
    its incarnation 0 with its life before the migration."""
    url = await copy(cluster, templates[start])
    await asyncio.to_thread(upgrade, url)
    empty = await copy(cluster, "template0")
    await asyncio.to_thread(upgrade, empty)
    upgraded, fresh = await read(url, schema), await read(empty, schema)
    assert {k: v for k, v in upgraded.items() if v != fresh[k]} == {}
    assert all(valid and ready for _, valid, ready in upgraded["valid"])
    assert all(validated for *_, validated in upgraded["constraints"])
    assert await scalar(url, TREE) == 0
    assert await scalar(url, UNRECORDED) == 0
    assert await scalar(url, "SELECT count(*) FROM schedules") > 0
    assert await scalar(url, UNINCARNATED) == 0 and await scalar(url, UNSPANNED) == 0


ADDED_THERE = (
    "SELECT (to_regclass('public.schedule_inventory_cutover') IS NOT NULL) "
    "AND (to_regprocedure('public.schedule_inventoried()') IS NOT NULL)"
)


async def test_each_revision_ends_as_the_original_left_it() -> None:
    """Run revision by revision from an empty database, the online migrations leave each revision's schema exactly as
    the original ones did (bc4c840's, fingerprinted by `tests/probes/migration_equivalence.py`): every migration's
    committed end is the original's state, grants, policies and roles included, but for what 0040 adds on purpose
    (`support.ADDED`: the capture until the inventory's cutover), which is there from 0040 on. A cluster of its own:
    roles are the cluster's, and the other tests' upgrades make them."""
    expected = json.loads(REVISIONS.read_text())
    differ, added = {}, {}
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        url = pg.get_connection_url()
        for revision, parts in expected.items():
            await asyncio.to_thread(upgrade, url, revision)
            got = await read(url, lambda c: fingerprint(c, ADDED))
            differ[revision] = sorted(part for part in parts if got[part] != parts[part])
            added[revision] = await scalar(url, ADDED_THERE)
    assert {revision: parts for revision, parts in differ.items() if parts} == {}
    assert [r for r, there in added.items() if there] == ["0040", "0043", "0044"]


HOLDING = """SELECT tenant_id, count(*) FROM run_requests WHERE source = 'webhook' AND status IN ('queued', 'starting')
GROUP BY tenant_id"""


async def test_the_budget_counts_the_webhook_requests_queued_or_starting_when_0050_arrives(cluster, templates) -> None:
    """The owner's ruling on the 2b-4b M3 checkpoint 5: from 0049 with webhook requests queued and starting (and
    manual ones queued, which it never counts), 0050's backfill counts each tenant's holding webhook requests, the
    deployment's total and its tenants with any, in the triggers' own step; from then on the triggers keep it."""
    url = await copy(cluster, templates["0042"])
    await asyncio.to_thread(upgrade, url, "0049")
    await execute(url, """
UPDATE run_requests SET source = 'webhook', status = 'queued'
 WHERE id IN (SELECT id FROM run_requests ORDER BY id LIMIT 30);
UPDATE run_requests SET source = 'webhook', status = 'starting', starting_at = now()
 WHERE id IN (SELECT id FROM run_requests WHERE source <> 'webhook' ORDER BY id LIMIT 12);
UPDATE run_requests SET status = 'queued'
 WHERE id IN (SELECT id FROM run_requests WHERE source <> 'webhook' ORDER BY id LIMIT 5);
""")  # fmt: skip
    c = await asyncpg.connect(url)
    try:
        expected = {r[0]: r[1] for r in await c.fetch(HOLDING)}
    finally:
        await c.close()
    assert sum(expected.values()) == 42 and len(expected) > 1
    await asyncio.to_thread(upgrade, url)
    c = await asyncpg.connect(url)
    try:
        counted = {r[0]: r[1] for r in await c.fetch("SELECT tenant_id, outstanding FROM ingress_outstanding")}
        assert counted == expected
        assert tuple(await c.fetchrow("SELECT outstanding, active FROM ingress_budget")) == (42, len(expected))
        await c.execute("UPDATE run_requests SET status = 'cancelled', reason = 'user_cancelled', ended_at = now() "
                        "WHERE id = (SELECT id FROM run_requests WHERE source = 'webhook' AND status = 'queued' "
                        "ORDER BY id LIMIT 1)")  # fmt: skip
        assert await c.fetchval("SELECT outstanding FROM ingress_budget") == 41
    finally:
        await c.close()


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
    assert await scalar(url, "SELECT version_num FROM alembic_version") == HEAD
    assert await scalar(url, TREE) == 0
    assert await scalar(url, UNRECORDED) == 0
    remaining = (450 if at.startswith("0037") else ROOTS) - 3 * BATCH  # runs, or root runs, not done yet
    assert len([n for n, _ in steps if n.startswith(f"{at} backfill")]) == remaining // BATCH + 1
    straight = await copy(cluster, templates["0034"])
    await asyncio.to_thread(upgrade, straight)
    assert await read(url, schema) == await read(straight, schema)


async def test_an_upgrade_interrupted_after_any_step_goes_on_from_there(cluster, templates, monkeypatch) -> None:
    """Interrupted after each committed step in turn (the process killed just after its commit), the upgrade run again
    goes on from there: each step's `done` query skips what committed, each step without one is safe to run again. It
    ends as one never interrupted, its data backfilled whole."""
    monkeypatch.setattr(online, "BATCH", 200)
    url = await copy(cluster, templates["0034"])
    seen: set[str] = set()

    def interrupt(conn: Connection, name: str) -> None:
        if name not in seen:
            seen.add(name)
            raise Interrupted

    online.AFTER.append(interrupt)
    runs = 0
    try:
        while True:
            runs += 1
            assert runs < 1_000
            try:
                await asyncio.to_thread(upgrade, url)
                break
            except Interrupted:
                pass
    finally:
        online.AFTER.remove(interrupt)
    assert runs == len(seen) + 1 > 100
    straight = await copy(cluster, templates["0034"])
    await asyncio.to_thread(upgrade, straight)
    assert await read(url, schema) == await read(straight, schema)
    for query in (TREE, UNRECORDED, UNINCARNATED, UNSPANNED):
        assert await scalar(url, query) == 0, query


@pytest.mark.parametrize("start", PATHS)
async def test_both_paths_upgrade_under_a_continuing_load(cluster, templates, start) -> None:
    """The lock probe's normal load runs throughout (an API's reads, a worker's writes, an admission, an ingress
    recording, one connection each): the upgrade completes, no operation fails, none waits D15's five seconds. (That
    no writer waits its `deadlock_timeout` behind a step is the deadlock tests' to prove: under the parallel suite, a
    loaded machine alone made an operation take over a second.)"""
    url = await copy(cluster, templates[start])
    load = Load(url, per_kind=1, pause=0.01)
    await load.prepare()
    loops = [asyncio.create_task(load._loop(kind)) for kind in Load.KINDS]
    try:
        await asyncio.wait_for(asyncio.to_thread(upgrade, url), 120)
    finally:
        load.stop.set()
        await asyncio.gather(*loops)
    assert await scalar(url, "SELECT version_num FROM alembic_version") == HEAD
    assert {kind: errors for kind, errors in load.errors.items() if errors} == {}
    assert sum(len(times) for times in load.times.values()) > 100
    assert max(took for times in load.times.values() for _, took in times) < 5.0


# The old application (from before 0040) at work during the upgrade, each under its own role and its tenant's scope: its
# API adds a schedule; its dispatcher syncs it (under the schedule's own id in Temporal, as it did every schedule) and
# records the missed count Temporal shows for that id, as it did every five minutes
OLD_PICK = """SELECT w.tenant_id, w.id, m.user_id FROM workflows w JOIN memberships m ON m.tenant_id = w.tenant_id
ORDER BY w.id LIMIT 1"""
OLD_CREATE = """INSERT INTO schedules (id, tenant_id, workflow_id, mode, created_by, every_s, offset_s, input)
VALUES (:i, :t, :w, 'live', :u, 3600, 0, '\\x01'::bytea)"""
OLD_SYNC = "UPDATE schedules SET synced_generation = generation, misses = :m WHERE id = :i"
OLD_MISSED = 5
INVENTORIED = """SELECT count(*) FROM schedule_incarnations i JOIN schedule_intervals v ON v.temporal_id = i.temporal_id
WHERE i.schedule_id = :i AND i.number = 0 AND i.backfilled AND v.reason = 'before_migration'"""


def as_old(conn: Connection, role: str, tenant: uuid.UUID, statement: str, **params: object) -> None:
    """`statement` as the old application's `role` does it, in its tenant's scope, committed: its own session's row
    security on (the migration's is off)."""
    conn.execute(text("BEGIN"))
    conn.execute(text(f"SET LOCAL ROLE {role}"))
    conn.execute(text("SET LOCAL row_security = on"))
    conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant)})
    conn.execute(text(statement), params)
    conn.execute(text("COMMIT"))


async def test_a_schedule_the_old_code_makes_after_the_backfill_is_still_inventoried(cluster, templates) -> None:
    """Right after each batch of 0040's backfills (the last ones included), the old application adds a schedule (its
    API, as dewpoint_api) and syncs it (its dispatcher, as dewpoint_dispatch), recording the missed count Temporal
    shows: once the upgrade ends, each has its incarnation 0 and its life before the migration recorded, as the
    schedules already there have. 0040 captures every schedule added until the inventory's cutover is recorded; the
    cutover's catch-up takes each incarnation 0's count as the old dispatcher last recorded it (the review's I1: the new
    misses pass would have counted that increase again)."""
    url = await copy(cluster, templates["0034"])
    made: list[uuid.UUID] = []

    def old_code(conn: Connection, name: str) -> None:
        if name.startswith(("0040 schedule_incarnations backfill", "0040 schedule_intervals backfill")):
            tenant, workflow, user = conn.execute(text(OLD_PICK)).one()
            made.append(uuid.uuid4())
            as_old(conn, "dewpoint_api", tenant, OLD_CREATE, i=made[-1], t=tenant, w=workflow, u=user)
            as_old(conn, "dewpoint_dispatch", tenant, OLD_SYNC, i=made[-1], m=OLD_MISSED)

    online.AFTER.append(old_code)
    try:
        await asyncio.to_thread(upgrade, url)
    finally:
        online.AFTER.remove(old_code)
    assert len(made) >= 2
    found = [await scalar(url, INVENTORIED.replace(":i", f"'{i}'")) for i in made]
    assert found == [1] * len(made)
    assert await scalar(url, UNINCARNATED) == 0 and await scalar(url, UNSPANNED) == 0
    caught = await scalar(url, "SELECT caught FROM schedule_inventory_catch_up('00000000-0000-0000-0000-000000000000', "
                               "1000000)")  # fmt: skip
    recorded = await scalar(url, "SELECT schedule_inventory_cutover_record(schedule_inventory_capture())")
    assert caught == 0 and recorded == "recorded"  # none missed
    counts = [await scalar(url, f"SELECT misses FROM schedule_incarnations WHERE schedule_id = '{i}' AND number = 0")
              for i in made]  # fmt: skip
    assert counts == [OLD_MISSED] * len(made)


async def test_once_the_cutover_is_recorded_a_new_schedule_is_the_new_syncs_alone(cluster, templates) -> None:
    """After `dewpoint schedules inventory-cutover` (no writer from before 0040 left), a schedule added is the new
    sync's to incarnate: nothing is captured for it."""
    url = await copy(cluster, templates["0042"])
    await asyncio.to_thread(upgrade, url)
    await execute(url, "INSERT INTO schedule_inventory_cutover DEFAULT VALUES")
    made = uuid.uuid4()
    await execute(
        url,
        "INSERT INTO schedules (id, tenant_id, workflow_id, mode, created_by, every_s, offset_s, input) "
        f"SELECT '{made}', p.tenant_id, p.id, 'live', p.user_id, 3600, 0, '\\x01'::bytea FROM ({OLD_PICK}) p",
    )
    assert await scalar(url, f"SELECT count(*) FROM schedule_incarnations WHERE schedule_id = '{made}'") == 0


class Holder:
    """An open transaction holding `table` in `mode`: a writer's (`ROW EXCLUSIVE`), as any write holds until it
    commits, or a long read's (`ACCESS SHARE`)."""

    def __init__(self, url: str, table: str = "tenants", mode: str = "ROW EXCLUSIVE") -> None:
        self.url, self.table, self.mode = url, table, mode

    async def __aenter__(self) -> "Holder":
        self.c = await asyncpg.connect(self.url)
        self.tx = self.c.transaction()
        await self.tx.start()
        await self.c.execute(f"LOCK TABLE {self.table} IN {self.mode} MODE")
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


HELD = {  # the table held and how, from which revision; the writes probed meanwhile; the first migration that waits
    "tenants": ("tenants", "ROW EXCLUSIVE", "0042", ["UPDATE tenants SET status = status WHERE false"], "0037"),
    # A long read of `runs`, which a concurrent index build doesn't wait for: 0035's steps on `runs` do (its unique key
    # attached, then the keys that take both their table and the one they reference)
    "runs": ("runs", "ACCESS SHARE", "0042", ["UPDATE runs SET iterations = iterations WHERE false",
                                              "UPDATE run_steps SET attempt = attempt WHERE false"], "0035"),
    # 0050's tables (the owner's ruling on the 2b-4b M3 design, rev 2): new, but their keys reference `tenants`
    "tenants, by 0050": ("tenants", "ROW EXCLUSIVE", "0049", ["UPDATE tenants SET status = status WHERE false"],
                         "0050"),
    # 0050's ingress budget (the owner's ruling on the M3 checkpoint 4): each busy table's column and triggers in steps
    # of their own (the fresh review 5's M6), behind ingress's and the dispatcher's writers
    "inbound_events, by 0050": ("inbound_events", "ROW EXCLUSIVE", "0049",
                                ["UPDATE inbound_events SET attempts = attempts WHERE false"], "0050"),
    "run_requests, by 0050": ("run_requests", "ROW EXCLUSIVE", "0049",
                              ["UPDATE run_requests SET attempts = attempts WHERE false"], "0050"),
}  # fmt: skip


@pytest.mark.parametrize("case", HELD)
async def test_a_step_behind_a_held_lock_gives_way_until_it_is_released(cluster, templates, caplog, case) -> None:
    """Behind a writer's open transaction, a step waits at most its budget, gives way, and tries again until the
    writer commits. A write queued behind the step meanwhile (any write waits for a pending lock that conflicts with
    it, a read only for an exclusive one) waits less than `deadlock_timeout`, never the writer's whole hold."""
    caplog.set_level(logging.INFO, logger="alembic.online")
    url = await copy(cluster, templates["0042"])
    table, mode, at, probes, first = HELD[case]
    if at != "0042":
        await asyncio.to_thread(upgrade, url, at)
        caplog.clear()  # the setup's own steps (0035 to 0040 for 0049) may give way on their budget on a loaded machine
    waits: list[float] = []
    stop = asyncio.Event()

    async def writer(statement: str) -> None:
        c = await asyncpg.connect(url)
        try:
            while not stop.is_set():
                t0 = time.monotonic()
                await c.execute(statement)
                waits.append(time.monotonic() - t0)
                await asyncio.sleep(0.02)
        finally:
            await c.close()

    writing = [asyncio.create_task(writer(statement)) for statement in probes]
    giving_way = GivingWay()
    logging.getLogger("alembic.online").addHandler(giving_way)
    async with Holder(url, table, mode) as holder:
        upgrading = asyncio.create_task(asyncio.to_thread(upgrade, url))
        try:
            await asyncio.wait_for(giving_way.seen.wait(), 60)
        finally:
            logging.getLogger("alembic.online").removeHandler(giving_way)
        await asyncio.sleep(1.5)  # held well past a step's budget
        while_held = gave_way(caplog)  # logged before the release: each attempt gave way while the lock was held
        await holder.release()
        try:
            await asyncio.wait_for(upgrading, 120)
        finally:
            stop.set()
            await asyncio.gather(*writing)
    # While the lock was held, the held step gave way on it, or on its budget when a loaded machine ran its statements
    # before the lock too slowly (seen under the parallel suite); the attempt the release came during, and a later
    # step's, may end on its budget too: each is tried again
    assert while_held and all(m.startswith(f"online step {first} ") for m in while_held), while_held
    assert any(m.endswith("(lock)") for m in while_held) and all(m.endswith(("(lock)", "(budget)")) for m in while_held)
    assert await scalar(url, "SELECT version_num FROM alembic_version") == HEAD
    assert max(waits) < 1.0  # the server's deadlock_timeout


async def test_a_lock_never_released_stops_the_upgrade_naming_its_step(cluster, templates, monkeypatch) -> None:
    """A step that gives way `ATTEMPTS` times stops the upgrade, naming itself, in bounded time; its migration stays
    unrecorded, and the upgrade run again once the lock is free goes on to the head. Ten attempts: enough for the
    other steps to finish on a loaded machine (with three, a large one ran out first, under the parallel suite). Its
    last attempt gives way to the lock it waited for, or, on a machine loaded enough that its statement began waiting
    later than its margin, at its statement's bound: either way within its budget (seen under the full suite, the
    2b-4b M1 checkpoint 6)."""
    monkeypatch.setattr(online, "ATTEMPTS", 10)
    url = await copy(cluster, templates["0042"])
    t0 = time.monotonic()
    async with Holder(url):
        upgrading = asyncio.create_task(asyncio.to_thread(upgrade, url))
        with pytest.raises(online.StepFailedError, match=r"^online step 0037 .+ gave way 10 times \((lock|budget)\)"):
            await asyncio.wait_for(asyncio.shield(upgrading), 60)
    assert time.monotonic() - t0 < 30
    assert await scalar(url, "SELECT version_num FROM alembic_version") == "0036"
    await asyncio.to_thread(upgrade, url)
    assert await scalar(url, "SELECT version_num FROM alembic_version") == HEAD


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


async def waiting_for(url: str, table: str, *, granted: bool = False) -> None:
    """Until a session waits for a lock on `table` (or holds one, `granted`): the step holds its first table, and waits
    for the second (a fixed pause wasn't enough on a loaded machine: the step hadn't begun)."""
    held = "" if granted else "NOT "
    query = f"SELECT EXISTS (SELECT 1 FROM pg_locks WHERE {held}granted AND relation = to_regclass('public.{table}'))"
    for _ in range(200):
        if await scalar(url, query):
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"nothing waited for {table}")


async def test_a_step_that_outruns_its_budget_gives_way_and_stops_after_its_attempts(scratch, monkeypatch) -> None:
    monkeypatch.setattr(online, "ATTEMPTS", 2)
    with pytest.raises(online.StepFailedError, match=r"gave way 2 times \(budget\)"):
        await run(scratch, lambda c: online.step(c, "slow", "CREATE TABLE t1 (x int)", "SELECT pg_sleep(0.4)",
                                                 "SELECT pg_sleep(0.4)"))  # fmt: skip
    assert not await exists(scratch, "t1")


class _RollbackCancelledOnce:
    """The migration's connection, but its first `ROLLBACK` cancelled before it ran, as the step's own statement timeout
    cancels one on a machine too loaded to run it in time (seen under the parallel suite): its transaction stays
    aborted."""

    def __init__(self, conn: Connection) -> None:
        self.conn, self.cancelled = conn, False

    @property
    def info(self) -> dict[str, Any]:
        return self.conn.info

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        if str(statement) == "ROLLBACK" and not self.cancelled:
            self.cancelled = True
            raise DBAPIError("ROLLBACK", {}, _Cancelled())
        return self.conn.execute(statement, *args, **kwargs)


class _Cancelled(Exception):
    sqlstate = "57014"

    def __str__(self) -> str:
        return "canceling statement due to statement timeout"


async def test_a_step_whose_rollback_was_cancelled_rolls_back_again_and_gives_way_as_such(scratch, monkeypatch) -> None:
    """The review of checkpoint 4's validation: a step's `ROLLBACK` cancelled left its transaction aborted, so the next
    attempt's `BEGIN` failed (`current transaction is aborted`) and the upgrade stopped on that, the cleanup masking
    why. A cancelled `ROLLBACK` is run again; the step gives way on its lock, as it should, and its connection is
    whole."""
    monkeypatch.setattr(online, "ATTEMPTS", 2)
    await execute(scratch, "CREATE TABLE a (x int)")
    holder = await asyncpg.connect(scratch)
    tx = holder.transaction()
    await tx.start()
    await holder.execute("INSERT INTO a VALUES (1)")  # a writer's open transaction: the step's lock times out

    def stepped(c: Connection) -> Any:
        wrapped = _RollbackCancelledOnce(c)
        try:
            online.step(wrapped, "cancelled", "LOCK TABLE a IN ACCESS EXCLUSIVE MODE")  # type: ignore[arg-type]
        except online.StepFailedError as e:
            return str(e), wrapped.cancelled, c.execute(text("SELECT 1")).scalar()
        return None

    try:
        found = await run(scratch, stepped)
    finally:
        await tx.rollback()
        await holder.close()
    assert found is not None and found[1:] == (True, 1)
    assert found[0] == "online step cancelled gave way 2 times (lock)"


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
    gives way within its budget, short of the writer's deadlock check (its lock timeout, or its own shorter deadlock
    check making it the victim), so the writer goes on and commits; the step commits on a later attempt."""
    caplog.set_level(logging.INFO, logger="alembic.online")
    await execute(scratch, "CREATE TABLE a (x int); CREATE TABLE b (x int)")
    w = await asyncpg.connect(scratch)
    try:
        tx = w.transaction()
        await tx.start()
        await w.execute("INSERT INTO b VALUES (1)")
        stepping = asyncio.create_task(run(scratch, lambda c: online.step(
            c, "both", "LOCK TABLE a IN ACCESS EXCLUSIVE MODE", "LOCK TABLE b IN ACCESS EXCLUSIVE MODE")))  # fmt: skip
        await waiting_for(scratch, "b")  # the step holds `a`, and waits for `b`
        t0 = time.monotonic()
        await w.execute("INSERT INTO a VALUES (1)")
        waited = time.monotonic() - t0
        await tx.commit()
        await asyncio.wait_for(stepping, 30)
    finally:
        await w.close()
    assert waited < 1.0
    assert gave_way(caplog)[0] in ("online step both: attempt 1 gave way (lock)",
                                   "online step both: attempt 1 gave way (deadlock)")  # fmt: skip


async def _queued_through(
    scratch: str, step: Callable[[Connection], Any], *, writer: str = "",
    release: Callable[[], Awaitable[None]] | None = None,
) -> tuple[float, Any]:  # fmt: skip
    """A writer queued behind `step` (on table `a`, which the step locks first): how long it waited (infinity: still
    waiting after `QUEUED_MAX_S`), and the step's outcome (its error, if it stopped). `release` frees whatever holds the
    step up, before its outcome is awaited."""
    w = await asyncpg.connect(scratch)
    stepping = asyncio.create_task(run(scratch, step))
    try:
        if writer:
            await w.execute(writer)
        await waiting_for(scratch, "a", granted=True)
        t0 = time.monotonic()
        try:
            await asyncio.wait_for(w.execute("INSERT INTO a VALUES (1)"), QUEUED_MAX_S)
            waited = time.monotonic() - t0
        except TimeoutError:
            waited = float("inf")
    finally:
        if release is not None:
            await release()
        try:
            outcome: Any = await asyncio.wait_for(stepping, 30)
        except Exception as e:
            outcome = e
        w.terminate()
    return waited, outcome


QUEUED_MAX_S = 6.0  # past D15's five seconds


async def test_a_steps_deferred_work_runs_within_its_budget_not_in_its_commit(scratch, monkeypatch) -> None:
    """The owner's review of checkpoint 4: a `COMMIT` isn't bounded by a statement timeout (Postgres turns it off before
    the commit's own work), so a step's deferred trigger work, done at its commit, held its locks for as long as it
    took. It runs within the step's budget (`SET CONSTRAINTS ALL IMMEDIATE`, its last statement): 3 s of it gives way
    at the budget, and a writer queued behind the step waits no longer."""
    monkeypatch.setattr(online, "ATTEMPTS", 1)
    await execute(
        scratch,
        """CREATE TABLE a (x int); CREATE TABLE d (x int);
CREATE FUNCTION slow() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(3); RETURN NULL; END $$;
CREATE CONSTRAINT TRIGGER d_slow AFTER INSERT ON d DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
EXECUTE FUNCTION slow()""",
    )
    waited, outcome = await _queued_through(scratch, lambda c: online.step(
        c, "deferred", "LOCK TABLE a IN ACCESS EXCLUSIVE MODE", "INSERT INTO d VALUES (1)"))  # fmt: skip
    assert waited < 1.5 and isinstance(outcome, online.StepFailedError) and "(budget)" in str(outcome)
    assert await scalar(scratch, "SELECT count(*) FROM d") == 0


async def test_a_steps_commit_waits_for_no_standby(cluster, scratch) -> None:
    """The owner's review of checkpoint 4: a commit waits for a synchronous standby's answer with its locks held, and
    no statement timeout bounds that. A step commits without waiting for any (`synchronous_commit = local`: it's
    idempotent, run again if a failover lost it): with a standby named that never answers, the step commits, and a
    writer queued behind it waits only for the step."""
    await execute(scratch, "CREATE TABLE a (x int)")
    await execute(f"{cluster}/postgres", "ALTER SYSTEM SET synchronous_standby_names = 'nobody'")
    await execute(f"{cluster}/postgres", "SELECT pg_reload_conf()")

    async def answered() -> None:  # no standby named: a commit waiting for one is let go
        await execute(f"{cluster}/postgres", "ALTER SYSTEM RESET synchronous_standby_names")
        await execute(f"{cluster}/postgres", "SELECT pg_reload_conf()")

    waited, outcome = await _queued_through(scratch, lambda c: online.step(
        c, "standby", "LOCK TABLE a IN ACCESS EXCLUSIVE MODE", "SELECT pg_sleep(0.2)"),
        writer="SET synchronous_commit = local", release=answered)  # fmt: skip
    assert outcome is None and waited < 1.5


async def test_a_migrating_client_that_stalls_mid_step_never_holds_its_locks_past_the_idle_bound(scratch) -> None:
    """The review of checkpoint 5 (I1): the server bounded a step's statements, not the time it sat idle in its
    transaction while the migrating client stalled (a paused machine, a lost network), its locks held until TCP
    noticed. A step's session idle in its transaction past its budget (and margin) is ended, its locks with it: a
    client stalled 5 s mid-step holds a writer queued behind it its budget and that idle bound at most, about two
    budgets, not 5 s; the upgrade stops (run it again)."""
    await execute(scratch, "CREATE TABLE a (x int)")
    waited, outcome = await _queued_through(scratch, lambda c: online.step(
        c, "stalled", "LOCK TABLE a IN ACCESS EXCLUSIVE MODE", lambda: time.sleep(5), "SELECT 1"))  # fmt: skip
    assert isinstance(outcome, Exception) and waited < 2 * online.BUDGET_MAX_S + 1.0, (waited, outcome)


async def test_a_writer_whose_role_checks_deadlocks_sooner_is_never_a_steps_victim(scratch) -> None:
    """A role of its own `deadlock_timeout` (200 ms, `ALTER ROLE … IN DATABASE`): the steps' budget is the shortest
    any role or the database has, so the step gives way before that writer's deadlock check could find it in a cycle."""
    role = f"w_{uuid.uuid4().hex[:8]}"
    await execute(
        scratch,
        f"CREATE TABLE a (x int); CREATE TABLE b (x int); CREATE ROLE {role} LOGIN PASSWORD 'pw'; "
        f"ALTER ROLE {role} IN DATABASE {scratch.rsplit('/', 1)[1]} SET deadlock_timeout = '200ms'; "  # this database's
        f"GRANT ALL ON a, b TO {role}",
    )
    w = await asyncpg.connect(f"postgresql://{role}:pw@{scratch.split('@', 1)[1]}")
    try:
        assert await w.fetchval("SHOW deadlock_timeout") == "200ms"
        tx = w.transaction()
        await tx.start()
        await w.execute("INSERT INTO b VALUES (1)")
        stepping = asyncio.create_task(run(scratch, lambda c: online.step(
            c, "both", "LOCK TABLE a IN ACCESS EXCLUSIVE MODE", "LOCK TABLE b IN ACCESS EXCLUSIVE MODE")))  # fmt: skip
        await waiting_for(scratch, "b")  # the step holds `a`, and waits for `b`
        t0 = time.monotonic()
        await w.execute("INSERT INTO a VALUES (1)")
        waited = time.monotonic() - t0
        await tx.commit()
        await asyncio.wait_for(stepping, 30)
    finally:
        await w.close()
    assert waited < 1.0  # a deadlock's victim would have raised; the margin is a loaded machine's


async def test_a_step_lasts_at_most_a_second_however_long_deadlock_timeout_is(scratch, monkeypatch) -> None:
    """The owner's review of checkpoint 3: a database whose `deadlock_timeout` is 10 s let a step last 6 s (60% of
    it), and a read or write queued behind the step wait as long. A step's budget is `BUDGET_MAX_S` at most, whatever
    `deadlock_timeout` is: behind a held lock it gives way within that, and what queued behind it waits no longer."""
    monkeypatch.setattr(online, "ATTEMPTS", 1)
    await execute(scratch, f"CREATE TABLE a (x int); ALTER DATABASE {scratch.rsplit('/', 1)[1]} "
                           "SET deadlock_timeout = '10s'")  # fmt: skip
    holder, reader = await asyncpg.connect(scratch), await asyncpg.connect(scratch)
    tx = holder.transaction()
    await tx.start()
    await holder.execute("INSERT INTO a VALUES (1)")  # a writer's open transaction
    try:
        t0 = time.monotonic()
        stepping = asyncio.create_task(run(scratch, lambda c: online.step(
            c, "capped", "LOCK TABLE a IN ACCESS EXCLUSIVE MODE")))  # fmt: skip
        await asyncio.sleep(0.2)  # the step waits for the writer
        t1 = time.monotonic()
        await reader.fetchval("SELECT count(*) FROM a")  # queued behind the step's request
        queued = time.monotonic() - t1
        with pytest.raises(online.StepFailedError, match=r"\(lock\)"):
            await stepping
        took = time.monotonic() - t0
    finally:
        await tx.rollback()
        await holder.close()
        await reader.close()
    assert took < 3.0 and queued < 1.5  # 6 s uncapped; the margins are a loaded machine's


async def test_an_upgrade_refuses_while_a_role_could_lower_its_own_deadlock_timeout(scratch, templates) -> None:
    """The owner's review of checkpoint 3: a step's budget rests on the shortest `deadlock_timeout` the catalogue shows,
    so no session may set its own lower unseen. The upgrade refuses, naming them, while a role other than the
    migrating one is granted `SET` on it, or a superuser is one of the application's roles or a member of one (here, of
    `dewpoint_api`, through another role); it changes nothing."""
    tag = uuid.uuid4().hex[:8]
    granted, between, superuser = f"granted_{tag}", f"between_{tag}", f"su_{tag}"
    await execute(scratch, f"CREATE ROLE {granted}; GRANT SET ON PARAMETER deadlock_timeout TO {granted}; "
                           f"CREATE ROLE {between} NOLOGIN IN ROLE dewpoint_api; "
                           f"CREATE ROLE {superuser} SUPERUSER IN ROLE {between}")  # fmt: skip
    try:
        with pytest.raises(online.StepFailedError) as refused:
            await run(scratch, lambda c: online.step(c, "refused", "CREATE TABLE t3 (x int)"))
        assert granted in str(refused.value) and superuser in str(refused.value)
        assert not await exists(scratch, "t3")
    finally:
        await execute(scratch, f"REVOKE SET ON PARAMETER deadlock_timeout FROM {granted}; DROP ROLE {granted}; "
                               f"DROP ROLE {superuser}; DROP ROLE {between}")  # fmt: skip


async def test_a_superuser_that_isnt_an_application_role_never_refuses_the_upgrade(scratch, templates) -> None:
    """Compose's bootstrap superuser is `dewpoint_owner`: when another role migrates (one that bypasses row-level
    security, as the deployment guide allows), it's a superuser named like the application's roles, but none of them
    nor a member of one, and its superuser can't be taken away. The upgrade goes on (the review of checkpoint 4: the
    application's roles were found by their names' prefix)."""
    owner = f"dewpoint_owner_{uuid.uuid4().hex[:8]}"
    await execute(scratch, f"CREATE ROLE {owner} SUPERUSER")
    try:
        await run(scratch, lambda c: online.step(c, "allowed", "CREATE TABLE t4 (x int)"))
    finally:
        await execute(scratch, f"DROP ROLE {owner}")
    assert await exists(scratch, "t4")


async def test_an_upgrade_refuses_when_its_own_setting_hides_the_servers(scratch) -> None:
    """The owner's review of checkpoint 4 (M1): the migrating session shows the server's `deadlock_timeout` (its files,
    its command line, its default) unless a role or session setting of its own replaces it, and no catalogue shows a
    command-line value. So the upgrade refuses while its own value comes from such a setting, unless the database has
    one of its own (then no session of it runs with the server's)."""
    db = scratch.rsplit("/", 1)[1]
    await execute(scratch, f"ALTER ROLE CURRENT_USER IN DATABASE {db} SET deadlock_timeout = '2s'")
    with pytest.raises(online.UnsafeSettingsError, match="hides the server's"):
        await run(scratch, lambda c: online.step(c, "hidden", "CREATE TABLE t5 (x int)"))
    assert not await exists(scratch, "t5")
    await execute(scratch, f"ALTER DATABASE {db} SET deadlock_timeout = '3s'")  # every session of it: none the server's
    await run(scratch, lambda c: online.step(c, "own", "CREATE TABLE t5 (x int)"))
    assert await exists(scratch, "t5")


async def test_an_upgrade_with_application_sessions_connected_needs_their_settings_attested(
    scratch, templates, monkeypatch
) -> None:  # fmt: skip
    """The owner's review of checkpoint 4 (R2): a live session runs with the `deadlock_timeout` it had when it
    connected, which no catalogue shows. While an application session is connected, the upgrade needs the operator's
    attestation that the application's connections were recycled after any change to it, and that it holds until the
    upgrade ends (`DEWPOINT_UPGRADE_SETTINGS_ATTESTED=1`); with none connected (a fresh installation, an upgrade with
    the application stopped), it needs none."""
    monkeypatch.delenv("DEWPOINT_UPGRADE_SETTINGS_ATTESTED", raising=False)
    login = f"app_{uuid.uuid4().hex[:8]}"
    await execute(scratch, f"CREATE ROLE {login} LOGIN PASSWORD 'pw' IN ROLE dewpoint_worker")
    await run(scratch, lambda c: online.step(c, "none connected", "CREATE TABLE t6 (x int)"))
    app = await asyncpg.connect(f"postgresql://{login}:pw@{scratch.split('@', 1)[1]}")
    try:
        with pytest.raises(online.UnsafeSettingsError, match="DEWPOINT_UPGRADE_SETTINGS_ATTESTED"):
            await run(scratch, lambda c: online.step(c, "connected", "CREATE TABLE t7 (x int)"))
        monkeypatch.setenv("DEWPOINT_UPGRADE_SETTINGS_ATTESTED", "1")
        await run(scratch, lambda c: online.step(c, "attested", "CREATE TABLE t7 (x int)"))
    finally:
        await app.close()
        await execute(scratch, f"DROP ROLE {login}")
    assert await exists(scratch, "t6") and await exists(scratch, "t7")


async def test_application_sessions_of_another_database_need_no_attestation(cluster, scratch, templates,
                                                                             monkeypatch) -> None:  # fmt: skip
    """The review of checkpoint 5 (M1), seen in the full suite: the attestation counted application sessions in every
    database of the cluster, so a fresh database's upgrade refused while another database's application was connected.
    A session of another database takes no lock on this one's tables, so it can't queue behind a step nor join its lock
    cycle: only this database's sessions count."""
    monkeypatch.delenv("DEWPOINT_UPGRADE_SETTINGS_ATTESTED", raising=False)
    login = f"app_{uuid.uuid4().hex[:8]}"
    await execute(scratch, f"CREATE ROLE {login} LOGIN PASSWORD 'pw' IN ROLE dewpoint_worker")
    app = await asyncpg.connect(f"postgresql://{login}:pw@{cluster.split('@', 1)[1]}/{templates['0042']}")
    try:
        await run(scratch, lambda c: online.step(c, "elsewhere", "CREATE TABLE t8 (x int)"))
    finally:
        await app.close()
        await execute(scratch, f"DROP ROLE {login}")
    assert await exists(scratch, "t8")


CHANGES = {  # a change to what a step's budget rests on, made while the upgrade runs
    "deadlock_timeout": ["ALTER DATABASE {db} SET deadlock_timeout = '500ms'"],
    "a grant": ["CREATE ROLE {role}", "GRANT SET ON PARAMETER deadlock_timeout TO {role}"],
}


@pytest.mark.parametrize("change", CHANGES)
async def test_an_upgrade_stops_when_what_its_budget_rests_on_changes_under_it(scratch, change) -> None:
    """The owner's review of checkpoint 3: `deadlock_timeout`, and who may set it, held stable through the upgrade.
    Each step reads them again; changed since the upgrade began, the upgrade stops before the step, naming why, and is
    run again once they're settled (its committed steps stay done)."""
    role = f"granted_{uuid.uuid4().hex[:8]}"

    def two(c: Connection) -> None:
        online.step(c, "one", "CREATE TABLE s1 (x int)")
        for statement in CHANGES[change]:
            c.execute(text(statement.format(db=scratch.rsplit("/", 1)[1], role=role)))
        online.step(c, "two", "CREATE TABLE s2 (x int)")

    try:
        with pytest.raises(online.StepFailedError, match=r"deadlock_timeout"):
            await run(scratch, two)
    finally:
        if change == "a grant":
            await execute(scratch, f"REVOKE SET ON PARAMETER deadlock_timeout FROM {role}; DROP ROLE {role}")
    assert await exists(scratch, "s1") and not await exists(scratch, "s2")


async def test_no_application_role_can_set_its_own_deadlock_timeout(cluster, templates) -> None:
    """The owner's review of checkpoint 3, verified: every role the migrations make (`dewpoint_*`) is refused `SET
    deadlock_timeout` in its sessions (a superuser's parameter, granted to none of them)."""
    url = await copy(cluster, templates["0042"])
    await asyncio.to_thread(upgrade, url)
    c = await asyncpg.connect(url)
    try:
        roles = [r["rolname"] for r in await c.fetch("SELECT rolname FROM pg_roles WHERE rolname LIKE 'dewpoint\\_%' "
                                                     "AND NOT rolsuper ORDER BY 1")]  # fmt: skip
        refused = []
        for role in roles:
            try:
                async with c.transaction():
                    await c.execute(f"SET LOCAL ROLE {role}")
                    await c.execute("SET LOCAL deadlock_timeout = '100ms'")
            except asyncpg.InsufficientPrivilegeError:
                refused.append(role)
        superusers = await c.fetchval("SELECT count(*) FROM pg_roles WHERE rolname LIKE 'dewpoint\\_%' AND rolsuper")
    finally:
        await c.close()
    assert len(roles) >= 7 and refused == roles and superusers == 0


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


async def test_a_backfill_whose_rows_take_long_to_find_still_goes_on(scratch, monkeypatch) -> None:
    """Finding a batch's rows (a resumed backfill scans the rows already done) takes no lock that blocks a normal
    operation, so it runs outside the step and its budget: only applying the batch does."""
    monkeypatch.setattr(online, "ATTEMPTS", 2)
    await execute(scratch, "CREATE TABLE w (id int PRIMARY KEY, done bool NOT NULL DEFAULT false); "
                           "INSERT INTO w (id) SELECT generate_series(1, 5)")  # fmt: skip
    bounds = ("SELECT max(id), count(*) FROM (SELECT id FROM w WHERE id > :after AND NOT done ORDER BY id LIMIT :n) b, "
              "pg_sleep(0.7)")  # fmt: skip
    apply = "UPDATE w SET done = true WHERE id > :after AND id <= :hi AND NOT done"
    assert await run(scratch, lambda c: online.batches(c, "w backfill", bounds, apply, first=0, size=10)) == 5
    assert await scalar(scratch, "SELECT count(*) FROM w WHERE NOT done") == 0


@pytest.fixture(scope="module")
def autovacuuming() -> Iterator[str]:
    """A cluster of its own, its autovacuum woken every second."""
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        url = pg.get_connection_url()
        asyncio.run(execute(url, "ALTER SYSTEM SET autovacuum_naptime = '1s'"))
        asyncio.run(execute(url, "SELECT pg_reload_conf()"))
        yield url


VACUUMED = """SELECT count(*) FROM pg_stat_activity a JOIN pg_locks l ON l.pid = a.pid AND l.locktype = 'relation'
WHERE a.backend_type = 'autovacuum worker' AND l.relation = to_regclass('public.{t}')"""


async def slowly_vacuumed(url: str, *tables: str, observer: str | None = None) -> None:
    """Each table's autovacuum under way, slowed (a page a tenth of a second) so it holds its lock for long. Made by
    `url`'s role, seen by `observer`'s (a role that may see the autovacuum's session)."""
    for t in tables:
        await execute(url, f"CREATE TABLE {t} (id int, pad text) WITH (autovacuum_vacuum_threshold = 0, "
                           "autovacuum_vacuum_scale_factor = 0, autovacuum_vacuum_cost_delay = 100, "
                           f"autovacuum_vacuum_cost_limit = 1); INSERT INTO {t} SELECT g, repeat('x', 200) "
                           f"FROM generate_series(1, 20000) g; DELETE FROM {t}")  # fmt: skip
    until = time.monotonic() + 60
    while not all([await scalar(observer or url, VACUUMED.format(t=t)) for t in tables]):
        assert time.monotonic() < until, "no autovacuum started"
        await asyncio.sleep(0.2)


async def test_a_step_behind_an_autovacuum_has_the_server_cancel_that_one_only(autovacuuming) -> None:
    """The server cancels an autovacuum that blocks a lock request once the request has waited `deadlock_timeout`; a
    step waits less than its budget, so it sets its own shorter (a role that may): the server then cancels the very
    autovacuum it waits for, never one against wraparound, and no other. The step commits; another table's autovacuum
    runs on."""
    db = await copy(autovacuuming.rsplit("/", 1)[0], "template1")
    await slowly_vacuumed(db, "av1", "av2")
    await run(db, lambda c: online.step(c, "vacuumed", "ALTER TABLE av1 ADD COLUMN x int"))
    assert await scalar(db, VACUUMED.format(t="av2")) == 1
    await execute(db, "DROP TABLE av2")  # its autovacuum ends with it


async def test_a_role_that_may_not_shorten_its_deadlock_timeout_gives_way_and_cancels_nothing(
    autovacuuming, monkeypatch, caplog
) -> None:  # fmt: skip
    """A migrating role without the privilege to set `deadlock_timeout` (a superuser's parameter, unless granted)
    cancels no autovacuum: a step behind one gives way and tries again, its attempts bounded, and says why."""
    caplog.set_level(logging.INFO, logger="alembic.online")
    monkeypatch.setattr(online, "ATTEMPTS", 3)
    db = await copy(autovacuuming.rsplit("/", 1)[0], "template1")
    role = f"m_{uuid.uuid4().hex[:8]}"
    await execute(db, f"CREATE ROLE {role} LOGIN PASSWORD 'pw'; GRANT CREATE ON SCHEMA public TO {role}")
    owned = f"postgresql://{role}:pw@{db.split('@', 1)[1]}"
    await slowly_vacuumed(owned, "av3", observer=db)
    with pytest.raises(online.StepFailedError, match=r"gave way 3 times \(lock\)"):
        await run(owned, lambda c: online.step(c, "vacuumed", "ALTER TABLE av3 ADD COLUMN x int"))
    assert await scalar(db, VACUUMED.format(t="av3")) == 1
    assert any("may not set deadlock_timeout" in r.getMessage() for r in caplog.records)
    await execute(db, "DROP TABLE av3")


async def test_an_operators_cancel_stops_the_step_rather_than_retry_it(scratch) -> None:
    """A statement cancelled on purpose (`pg_cancel_backend`) stops the upgrade: only a timeout gives way."""
    stepping = asyncio.create_task(run(scratch, lambda c: online.step(c, "cancelled", "SELECT pg_sleep(0.5)")))
    query = "SELECT pid FROM pg_stat_activity WHERE query = 'SELECT pg_sleep(0.5)' AND state = 'active'"
    until = time.monotonic() + 10
    while (pid := await scalar(scratch, query)) is None:
        assert time.monotonic() < until
        await asyncio.sleep(0.01)
    await scalar(scratch, f"SELECT pg_cancel_backend({pid})")
    with pytest.raises(DBAPIError) as raised:
        await stepping
    assert getattr(raised.value.orig, "sqlstate", None) == "57014"
