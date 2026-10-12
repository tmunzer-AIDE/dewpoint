# SPDX-License-Identifier: Apache-2.0
"""Main's 0047, 0045 and 0070 on D15's path (the owner's rulings at the merge, 2026-10-11): their files stay
byte-identical, and a database that hasn't applied one runs its online equivalent (`migrations/equivalents.py`), which
env.py installs in place of the file's `upgrade()`, guarded. Each equivalent ends exactly where its original's body
does; a downgrade goes back through the originals' own; an interrupted build is built again; writes to `runs` go on
through both index builds; and nothing runs an original body behind the guard (an edited file, offline SQL)."""

import asyncio
import dataclasses
import hashlib
import importlib.util
import io
import time
from collections.abc import Callable
from typing import Any

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import NullPool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from migrations import equivalents
from tests.migrations.support import BACKEND, autocommitted, copy, downgrade, recorded, schema, security, upgrade
from tests.probes.migration_locks import seed

MAIN = ["0047", "0045", "0070"]  # main's, in the order they're chained after 0044
STEPS = ["0047 runs_workflow_last", "0045 run_step_connections", "0045 grants", "0045 runs_workflow_ended",
         "0070 webhook_endpoints trigger_key"]  # fmt: skip
CLONES = 100_000  # root runs added at 0044, so each concurrent build lasts long enough to be watched (~0.1-0.3 s)
CLONE = """INSERT INTO runs SELECT (jsonb_populate_record(t.r, jsonb_build_object('id', g.id, 'root_run_id', g.id))).*
FROM (SELECT r FROM runs r WHERE parent_run_id IS NULL AND kind = 'run' AND ended_at IS NOT NULL LIMIT 1) t,
LATERAL (SELECT gen_random_uuid() AS id FROM generate_series(1, $1)) g"""
INDEXES = {"runs_workflow_last": ("0044", "0047"), "runs_workflow_ended": ("0047", "0045")}  # built by, from, to
STALL_S = 1.5  # how long a writer's open transaction holds `runs` while the upgrade runs
BOUND_S = 1.0  # the server's deadlock_timeout: no write waits that long behind a step (D15)


@pytest.fixture(scope="module")
def cluster() -> Any:
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        yield pg.get_connection_url().rsplit("/", 1)[0]


async def _sql(url: str, *statements: str) -> None:
    c = await asyncpg.connect(url)
    try:
        for statement in statements:
            await c.execute(statement)
    finally:
        await c.close()


async def scalar(url: str, query: str) -> Any:
    c = await asyncpg.connect(url)
    try:
        return await c.fetchval(query)
    finally:
        await c.close()


@pytest.fixture(scope="module")
def templates(cluster: str) -> dict[str, str]:
    """A seeded database at 0044 (D15's paths, up to main's three), and one with `CLONES` root runs more."""
    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "at0044"'))
    url = f"{cluster}/at0044"
    upgrade(url, "0042")
    asyncio.run(seed(url, 300))
    upgrade(url, "0044")

    async def larger() -> None:
        await _sql(f"{cluster}/postgres", 'CREATE DATABASE "large0044" TEMPLATE "at0044"')
        c = await asyncpg.connect(f"{cluster}/large0044")
        try:
            await c.execute(CLONE, CLONES)
            await c.execute("ANALYZE runs")
        finally:
            await c.close()

    asyncio.run(larger())
    return {"small": "at0044", "large": "large0044"}


def state(conn: Connection) -> dict[str, Any]:
    return {"version": conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one(),
            **schema(conn), **security(conn)}  # fmt: skip


async def read(url: str) -> dict[str, Any]:
    return await asyncio.to_thread(autocommitted, url, state)


def _original_module(revision: str) -> Any:
    """Main's file for `revision`, loaded afresh: its own `upgrade()`, never an installed equivalent."""
    path = BACKEND / "migrations" / "versions" / equivalents.ONLINE[revision].file
    spec = importlib.util.spec_from_file_location(f"original_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def original(url: str, revision: str) -> None:
    """Main's `upgrade()` body of `revision`, as Alembic ran it before D15: one transaction, its version recorded in it.
    Run only here, as what its equivalent must end as: env.py never runs one."""
    module = _original_module(revision)

    def apply(conn: Connection) -> None:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == module.down_revision
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        conn.execute(text("UPDATE alembic_version SET version_num = :r"), {"r": revision})

    async def run() -> None:
        engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"), poolclass=NullPool)
        try:
            async with engine.begin() as c:
                await c.run_sync(apply)
        finally:
            await engine.dispose()

    asyncio.run(run())


# The guard


def test_only_mains_three_run_an_online_equivalent() -> None:
    assert list(equivalents.ONLINE) == MAIN


def test_each_equivalent_stands_for_its_original_file_byte_for_byte() -> None:
    """Each names the file it stands for and that file's digest: main's, unchanged since the equivalent was written."""
    for revision, equivalent in equivalents.ONLINE.items():
        path = BACKEND / "migrations" / "versions" / equivalent.file
        assert path.name.startswith(f"{revision}_"), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == equivalent.sha256, revision
        assert _original_module(revision).revision == revision


async def test_an_edited_original_stops_the_upgrade_before_anything_runs(cluster, templates, monkeypatch) -> None:
    """An original whose file isn't the one its equivalent stands for refuses the upgrade, naming it, before any
    migration runs: neither its edited body nor the stale equivalent runs silently."""
    url = await copy(cluster, templates["small"])
    edited = dataclasses.replace(equivalents.ONLINE["0045"], sha256="0" * 64)
    monkeypatch.setitem(equivalents.ONLINE, "0045", edited)
    with pytest.raises(equivalents.EquivalentStaleError, match="0045"):
        await asyncio.to_thread(upgrade, url, "0070")
    assert await scalar(url, "SELECT version_num FROM alembic_version") == "0044"
    assert await scalar(url, "SELECT to_regclass('public.runs_workflow_last') IS NULL")


def test_offline_sql_through_an_equivalent_is_refused(monkeypatch) -> None:
    """Offline (`alembic upgrade --sql`), a script would hold the original bodies: refused, writing none of them."""
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://offline@localhost/offline")
    out = io.StringIO()
    config = Config(output_buffer=out)
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    with pytest.raises(equivalents.EquivalentOfflineError, match="0047"):
        command.upgrade(config, "0044:0070", sql=True)
    assert "runs_workflow_last" not in out.getvalue()


# The end state


async def test_each_equivalent_runs_online_and_ends_as_mains_original_does(cluster, templates) -> None:
    """From the same database at 0044, main's original bodies and the equivalents end each revision identical:
    columns, keys, indexes (valid), functions, grants, policies, row-level security, triggers. The equivalents commit
    their steps, an index each concurrently."""
    by_originals, by_equivalents = await copy(cluster, templates["small"]), await copy(cluster, templates["small"])
    with recorded() as steps:
        for revision in MAIN:
            await asyncio.to_thread(original, by_originals, revision)
            await asyncio.to_thread(upgrade, by_equivalents, revision)
            assert await read(by_equivalents) == await read(by_originals), revision
    assert [name for name, _ in steps] == STEPS


async def test_a_downgrade_goes_back_through_the_originals_own_and_up_again(cluster, templates) -> None:
    """Up through the equivalents, then down through main's own downgrades one revision at a time, each state is the
    one the way up left. Up again, the end is the one main's originals reach after the same round trip: 0070's
    downgrade drops its column, and PostgreSQL never reuses a dropped column's number, so the column added again comes
    one position later, whichever body adds it."""
    url, by_originals = await copy(cluster, templates["small"]), await copy(cluster, templates["small"])
    states = {"0044": await read(url)}
    for revision in MAIN:
        await asyncio.to_thread(upgrade, url, revision)
        await asyncio.to_thread(original, by_originals, revision)
        states[revision] = await read(url)
    for revision in ["0045", "0047", "0044"]:
        await asyncio.to_thread(downgrade, url, revision)
        await asyncio.to_thread(downgrade, by_originals, revision)
        assert await read(url) == states[revision] == await read(by_originals), revision
    for revision in MAIN:
        await asyncio.to_thread(upgrade, url, revision)
        await asyncio.to_thread(original, by_originals, revision)
        assert await read(url) == await read(by_originals), revision


# Interrupted builds and concurrent writes


class Holder:
    """A writer's open transaction on `runs`: ROW EXCLUSIVE and a row lock, held until released."""

    async def __aenter__(self) -> "Holder":
        return self

    def __init__(self, url: str) -> None:
        self.url = url

    async def hold(self) -> None:
        self.c = await asyncpg.connect(self.url)
        self.tx = self.c.transaction()
        await self.tx.start()
        await self.c.execute("UPDATE runs SET iterations = iterations WHERE id = (SELECT id FROM runs LIMIT 1)")

    async def release(self) -> None:
        if hasattr(self, "c") and not self.c.is_closed():
            await self.tx.rollback()
            await self.c.close()

    async def __aexit__(self, *exc: object) -> None:
        await self.release()


async def _until(check: Callable[[], Any]) -> None:
    for _ in range(6_000):  # a minute
        if await check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never observed")


@pytest.mark.parametrize("name", INDEXES)
async def test_an_index_an_interrupted_build_left_invalid_is_built_again(cluster, templates, name) -> None:
    """A concurrent build of `name` cancelled while it waited for a writer leaves the index invalid: the upgrade drops
    it and builds it again, valid, as the original defines it."""
    start, revision = INDEXES[name]
    url, straight = await copy(cluster, templates["small"]), await copy(cluster, templates["small"])
    for target in (url, straight):
        if start != "0044":
            await asyncio.to_thread(upgrade, target, start)
    definition = equivalents.CONCURRENT[name]
    async with Holder(url) as holder:
        await holder.hold()
        builder = await asyncpg.connect(url)
        try:
            building = asyncio.create_task(builder.execute(definition))
            pid = builder.get_server_pid()
            await _until(lambda: scalar(url, f"SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE pid = {pid} "
                                              "AND wait_event_type = 'Lock')"))  # fmt: skip
            await _sql(url, f"SELECT pg_cancel_backend({pid})")
            with pytest.raises(asyncpg.QueryCanceledError):
                await building
        finally:
            await builder.close()
    assert await scalar(url, f"SELECT NOT indisvalid FROM pg_index WHERE indexrelid = '{name}'::regclass")
    await asyncio.to_thread(upgrade, url, revision)
    await asyncio.to_thread(upgrade, straight, revision)
    assert await read(url) == await read(straight)


async def test_writes_to_runs_go_on_through_both_index_builds(cluster, templates) -> None:
    """While each index is built on a `runs` of `CLONES` root runs, a writer keeps inserting runs: it commits during
    each build, never waits on the migration while a build runs, and no write waits a deadlock_timeout. Another
    writer's open transaction holds `runs` as each migration starts, which a non-concurrent build would queue behind
    (and every write behind it). Then every row is in both indexes (amcheck, heapallindexed)."""
    url = await copy(cluster, templates["large"])
    writer = await asyncpg.connect(url)
    watcher = await asyncpg.connect(url)
    writes: list[tuple[float, float]] = []
    samples: list[tuple[float, list[int], list[str]]] = []
    stop = asyncio.Event()
    wpid = writer.get_server_pid()

    async def write() -> None:
        while not stop.is_set():
            t0 = time.monotonic()
            await writer.execute(CLONE, 1)
            writes.append((t0, time.monotonic()))

    async def watch() -> None:
        while not stop.is_set():
            row = await watcher.fetchrow(
                "SELECT pg_blocking_pids($1) AS blocked_by, ARRAY(SELECT coalesce(index_relid::regclass::text, '') "
                "FROM pg_stat_progress_create_index WHERE relid = 'runs'::regclass) AS building",
                wpid,
            )  # fmt: skip
            samples.append((time.monotonic(), list(row["blocked_by"]), list(row["building"])))
            await asyncio.sleep(0.005)

    writing, watching = asyncio.create_task(write()), asyncio.create_task(watch())
    holders: list[int] = []
    try:
        for target in ("0047", "0045"):
            async with Holder(url) as holder:
                await holder.hold()
                holders.append(holder.c.get_server_pid())
                upgrading = asyncio.create_task(asyncio.to_thread(upgrade, url, target))
                await asyncio.sleep(STALL_S)
            await upgrading
    finally:
        stop.set()
        await asyncio.gather(writing, watching)
        await writer.close()
        await watcher.close()
    assert writes and max(end - t0 for t0, end in writes) < BOUND_S
    for name in INDEXES:
        during = [at for at, _, building in samples if name in building]
        assert during, f"{name}'s build never observed"
        assert any(min(during) <= end <= max(during) for _, end in writes), f"no write committed during {name}'s build"
    held_up = [(at, by) for at, by, building in samples if building and set(by) - set(holders)]
    assert held_up == [], "a write waited on the migration while it built an index"
    await _sql(url, "CREATE EXTENSION IF NOT EXISTS amcheck")
    for name in INDEXES:
        await _sql(url, f"SELECT bt_index_check('{name}'::regclass, true)")
