# SPDX-License-Identifier: Apache-2.0
"""0053 run on disposable databases, in a cluster of this module's own (gate A's tests, as task 2 specifies them; the
owner's transactional exception): one Dewpoint database per cluster may run 0053, so each test copies a seeded template
at 0052, and the database and the role it made are dropped after it. 0053 is one transaction: its checks, its changes
and Alembic's version update commit or roll back together."""

import asyncio
import importlib.util
import re
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from types import ModuleType
from typing import Any

import asyncpg
import pytest
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import column, event, select, table, text
from sqlalchemy.dialects.postgresql.asyncpg import PGDialect_asyncpg
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.community.postgres import PostgresContainer

from tests.migrations.derive_0053 import approved
from tests.migrations.state_0053 import (
    CALLS,
    GRANTED,
    MARKER,
    SERVICE_ROLES,
    Snapshot,
    after,
    effective,
    holders,
    lost,
    restoration,
    snapshot,
    touched,
)  # fmt: skip
from tests.migrations.support import BACKEND, alembic_config, autocommitted, copy, downgrade, upgrade
from tests.migrations.test_0053_static import WRITES
from tests.probes.migration_locks import Load, seed

MIGRATION = BACKEND / "migrations" / "versions" / "0053_recovery_privileges.py"
ROOTS = 20  # root runs seeded at 0034, before the template is upgraded to 0052
PROBE = "rcv_public_probe"  # a role with no memberships: what PUBLIC holds

State = tuple[Snapshot, dict[str, set[Any]], str]


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0053", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _sql(url: str, *statements: str) -> None:
    c = await asyncpg.connect(url)
    try:
        for statement in statements:
            await c.execute(statement)
    finally:
        await c.close()


async def _drop(base: str, name: str) -> None:
    c = await asyncpg.connect(f"{base}/postgres")
    try:
        await c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = $1", name)
        await c.execute(f'DROP DATABASE IF EXISTS "{name}"')
    finally:
        await c.close()


def _state_now(url: str) -> State:
    def read(c: Connection) -> State:
        rights = {r: effective(c, r) for r in (*SERVICE_ROLES, PROBE)}
        version = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        return snapshot(c), rights, version

    return autocommitted(url, read)


async def state(url: str) -> State:
    return await asyncio.to_thread(_state_now, url)


@pytest.fixture(scope="module")
def cluster() -> Iterator[str]:
    """The module's cluster, with the role that stands for PUBLIC (`PROBE`), whichever test runs first."""
    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
        base = pg.get_connection_url().rsplit("/", 1)[0]
        asyncio.run(_sql(f"{base}/postgres", f"CREATE ROLE {PROBE} NOLOGIN"))
        yield base


@pytest.fixture(scope="module")
def template(cluster: str) -> str:
    """A seeded database at 0052, seeded at 0034 as test_online seeds, then upgraded (0053 never runs here). No
    deployment recorded: a fresh installation records it only after migrating."""
    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0052"'))
    upgrade(f"{cluster}/t0052", "0034")
    asyncio.run(seed(f"{cluster}/t0052", ROOTS))
    upgrade(f"{cluster}/t0052", "0052")
    return "t0052"


@pytest.fixture
async def made(cluster: str) -> AsyncIterator[list[str]]:
    """The databases a test made; each dropped after it, then the role 0053 made, and any test role."""
    names: list[str] = []
    yield names
    for name in names:
        await _drop(cluster, name)
    await _sql(f"{cluster}/postgres", "DROP ROLE IF EXISTS dewpoint_recovery", "DROP ROLE IF EXISTS rcv_test_member")


@pytest.fixture
async def db(cluster: str, template: str, made: list[str]) -> str:
    url = await copy(cluster, template)
    made.append(url.rsplit("/", 1)[1])
    return url


def _hooked(hook: Callable[[int], None]) -> Any:
    config = alembic_config()
    config.attributes["after_change"] = hook
    return config


# Test 1: every guard failure changes nothing (gate A's guard as the owner amended it: the expected name, Dewpoint's
# tables, the revision; then the exact snapshot).


@pytest.mark.parametrize(
    ("expected", "refusal"), [(None, "no expected database"), ("another_database", "not the expected")]
)
async def test_without_the_expected_database_nothing_changes(db: str, expected: str | None, refusal: str) -> None:
    before = await state(db)
    with pytest.raises(Exception, match=f"0053 refused: .*{refusal}"):
        await asyncio.to_thread(upgrade, db, "0053", None, expected)
    assert await state(db) == before


async def test_without_the_platform_settings_table_nothing_changes(db: str) -> None:
    await _sql(db, "DROP TABLE platform_settings")
    before = await state(db)
    with pytest.raises(Exception, match="0053 refused: not a Dewpoint database"):
        await asyncio.to_thread(upgrade, db, "0053")
    assert await state(db) == before


def _phase0(url: str, direction: str, version: str | None) -> Exception | None:
    """0053's checks alone, in a transaction rolled back after, with alembic_version set to `version` (None: as it
    is)."""

    async def run() -> Exception | None:
        engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"), poolclass=NullPool)
        try:
            async with engine.connect() as c:
                await c.begin()

                def call(sync: Connection) -> Exception | None:
                    if version is not None:
                        sync.execute(text("UPDATE alembic_version SET version_num = :v"), {"v": version})
                    context = MigrationContext.configure(sync, opts={"expected_database": url.rsplit("/", 1)[1]})
                    with Operations.context(context):
                        try:
                            _module()._checked(direction)
                        except RuntimeError as e:
                            return e
                    return None

                found = await c.run_sync(call)
                await c.rollback()
                return found
        finally:
            await engine.dispose()

    return asyncio.run(run())


async def test_a_database_that_isnt_dewpoints_is_refused(cluster: str, made: list[str]) -> None:
    """An empty database named as expected (Temporal's, say): no alembic_version, no platform_settings."""
    name = f"e{uuid.uuid4().hex[:12]}"
    await _sql(f"{cluster}/postgres", f'CREATE DATABASE "{name}"')
    made.append(name)
    before = await asyncio.to_thread(autocommitted, f"{cluster}/{name}", snapshot)
    assert "not a Dewpoint database" in str(await asyncio.to_thread(_phase0, f"{cluster}/{name}", "upgrade", None))
    assert await asyncio.to_thread(autocommitted, f"{cluster}/{name}", snapshot) == before


async def test_the_upgrade_refuses_from_any_revision_but_0052(db: str) -> None:
    before = await state(db)
    assert await asyncio.to_thread(_phase0, db, "upgrade", "0052") is None  # the control
    assert "0053 refused" in str(await asyncio.to_thread(_phase0, db, "upgrade", "0051"))
    assert await state(db) == before


async def test_the_downgrade_refuses_from_any_revision_but_0053(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0053")
    before = await state(db)
    assert await asyncio.to_thread(_phase0, db, "downgrade", "0053") is None  # the control
    assert "0053 refused" in str(await asyncio.to_thread(_phase0, db, "downgrade", "0052"))
    assert await state(db) == before


# Test 2: a drift row, one per kind, changes nothing.

DRIFTS = {
    "an extra grant": ["GRANT EXECUTE ON FUNCTION public.start_permitted(text, text) TO PUBLIC"],
    "a missing grant": ["REVOKE EXECUTE ON FUNCTION public.start_permitted(text, text) FROM dewpoint_start_check"],
    "another owner": ["ALTER FUNCTION public.app_user_id() OWNER TO dewpoint_admin"],
    "an empty ACL": [
        "REVOKE ALL ON FUNCTION public.armor(bytea) FROM PUBLIC",
        "REVOKE ALL ON FUNCTION public.armor(bytea) FROM CURRENT_USER",
    ],  # fmt: skip
    "an extra function": ["CREATE FUNCTION public.extra_drift() RETURNS integer LANGUAGE sql AS 'SELECT 1'"],
    "a default-ACL row": ["ALTER DEFAULT PRIVILEGES GRANT SELECT ON TABLES TO dewpoint_api"],
    "a recovery schema": ["CREATE SCHEMA recovery"],
}


@pytest.mark.parametrize("drift", DRIFTS)
async def test_a_drifted_database_changes_nothing(db: str, drift: str) -> None:
    await _sql(db, *DRIFTS[drift])
    before = await state(db)
    with pytest.raises(Exception, match="0053 refused"):
        await asyncio.to_thread(upgrade, db, "0053")
    assert await state(db) == before


# Test 3: a pre-existing dewpoint_recovery is always a collision.


@pytest.mark.parametrize("comment", [MARKER, None])
async def test_a_role_made_elsewhere_changes_nothing(db: str, cluster: str, comment: str | None) -> None:
    made = ["CREATE ROLE dewpoint_recovery NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"]
    if comment is not None:
        made.append(f"COMMENT ON ROLE dewpoint_recovery IS '{comment}'")
    await _sql(f"{cluster}/postgres", *made)
    before = await state(db)
    with pytest.raises(Exception, match="0053 refused"):
        await asyncio.to_thread(upgrade, db, "0053")
    assert await state(db) == before


async def test_a_second_database_in_the_cluster_changes_nothing(db: str, cluster: str, template: str,
                                                                  made: list[str]) -> None:  # fmt: skip
    await asyncio.to_thread(upgrade, db, "0053")
    second = await copy(cluster, template)
    made.append(second.rsplit("/", 1)[1])
    before = await state(second)
    with pytest.raises(Exception, match="0053 refused"):
        await asyncio.to_thread(upgrade, second, "0053")
    assert await state(second) == before
    assert (await state(db))[2] == "0053"


# Tests 5, 6, 8 and the end state: an upgrade, then a downgrade.


async def test_the_upgrade_ends_at_the_derived_reference(db: str) -> None:
    before = await state(db)
    await asyncio.to_thread(upgrade, db, "0053")
    snap, _, version = await state(db)
    objects, grants = after()
    assert version == "0053"
    assert snap["objects"] == objects
    assert snap["grants"] == grants
    assert snap["recovery_presence"] == {(1, 1)}
    # Test 8: nothing changed outside this database but the role it made
    assert {r for r in snap["databases"] if r[0] != "<current>"} == {r for r in before[0]["databases"]
                                                                      if r[0] != "<current>"}  # fmt: skip
    assert {r for r in snap["roles"] if r[0] != "dewpoint_recovery"} == before[0]["roles"]
    assert snap["memberships"] == before[0]["memberships"]


async def test_the_role_it_makes_is_exactly_the_approved_one(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0053")
    snap, _, _ = await state(db)
    roles = {r[0]: r for r in snap["roles"]}
    assert roles["dewpoint_recovery"] == ("dewpoint_recovery", False, True, False, False, False, False, False, -1, "",
                                          MARKER)  # fmt: skip
    assert not [m for m in snap["memberships"] if "dewpoint_recovery" in (m[0], m[1])]


async def test_each_service_role_keeps_exactly_its_grants(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0053")
    _, rights, _ = await state(db)
    for function, roles in GRANTED.items():
        assert holders({r: rights[r] for r in SERVICE_ROLES}, function) == roles, function
    assert ("schema", "public", "USAGE") in rights["dewpoint_start_check"]
    assert not [r for r in rights[PROBE] if r[0].startswith("function")]  # PUBLIC executes no application function
    assert ("database", "<current>", "TEMPORARY") not in rights[PROBE]


async def test_a_downgrade_restores_what_gate_a_defines(db: str) -> None:
    before = await state(db)
    await asyncio.to_thread(upgrade, db, "0053")
    await asyncio.to_thread(downgrade, db, "0052")
    restored = await state(db)
    assert restored[2] == "0052"
    assert restoration(before[0], restored[0], before[1], restored[1]) == []


@pytest.mark.parametrize(
    "mutation", ["a grant left out", "an untouched object's state changed", "PUBLIC's USAGE on sql left out"]
)
async def test_the_restoration_comparison_catches(db: str, mutation: str) -> None:
    before = await state(db)
    await asyncio.to_thread(upgrade, db, "0053")
    await asyncio.to_thread(downgrade, db, "0052")
    if mutation == "a grant left out":
        await _sql(db, "REVOKE EXECUTE ON FUNCTION public.start_permitted(text, text) FROM dewpoint_start_check")
    elif mutation == "PUBLIC's USAGE on sql left out":
        await _sql(db, "REVOKE USAGE ON LANGUAGE sql FROM PUBLIC")
    else:
        untouched = sorted(o for o in before[0]["objects"] if o[3] == "default" and o[0].startswith("relation:")
                           and (o[0], o[1]) not in touched())  # fmt: skip
        await _sql(db, f"GRANT SELECT ON {untouched[0][1]} TO CURRENT_USER")  # no right more, an explicit ACL
    restored = await state(db)
    assert restoration(before[0], restored[0], before[1], restored[1]) != []


# Test 7, at run time: every statement sent is approved, a fixed read, or read-only bookkeeping.


@contextmanager
def captured() -> Iterator[list[str]]:
    seen: list[str] = []

    def listen(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", listen)
    try:
        yield seen
    finally:
        event.remove(Engine, "before_cursor_execute", listen)


PHASE0 = ("LOCK_TIMEOUT", "SEARCH_PATH", "PINNED", "RESTORED", "DATABASE", "VERSION", "ROLE", "OBJECTS", "GRANTS",
          "PRESENCE")  # fmt: skip
DIALECT = PGDialect_asyncpg()
# Alembic's read of its version (alembic/runtime/migration.py, get_current_heads), as the dialect sends it
VERSION_READ = str(select(table("alembic_version", column("version_num")).c.version_num).compile(dialect=DIALECT))


def _as_sent(sql: str) -> str:
    """One of 0053's fixed statements as the dialect sends it (a bind as asyncpg's numbered parameter)."""
    return str(text(sql).compile(dialect=DIALECT))


def _version_update(was: str, to: str) -> str:
    """Alembic's version update, as it writes it (alembic/runtime/migration.py, 1.20: literal values)."""
    return f"UPDATE alembic_version SET version_num='{to}' WHERE alembic_version.version_num = '{was}'"


def _bookkeeping(statement: str) -> bool:
    """Alembic's bookkeeping with nothing to run: its version read, or the dialect's check that its version table
    exists, which reads pg_catalog alone."""
    if statement == VERSION_READ:
        return True
    read = re.findall(r"\b(?:FROM|JOIN) +([\w.]+)", statement)
    catalog_only = bool(read) and all(r.startswith("pg_catalog.") for r in read)
    writes = any(w in statement.upper() for w in WRITES)
    return statement.startswith("SELECT pg_catalog.pg_class.relname") and catalog_only and not writes


def _unapproved(sent: list[str], changes: list[str], allowed: set[str]) -> list[str]:
    """What was sent beyond the approved changes (each once, in order) and the `allowed` statements, exactly."""
    found, next_change = [], 0
    for statement in sent:
        if next_change < len(changes) and statement == changes[next_change]:
            next_change += 1
        elif statement not in allowed:
            found.append(statement)
    if next_change != len(changes):
        found.append(f"only {next_change} of {len(changes)} approved changes sent, in order")
    return found


async def test_every_statement_sent_is_on_the_allowlist(db: str) -> None:
    module = _module()
    reads = {_as_sent(getattr(module, name)) for name in PHASE0}
    upgrade_changes, downgrade_changes = approved()
    with captured() as sent:
        await asyncio.to_thread(upgrade, db, "0053")
    with captured() as bookkeeping:  # Alembic with nothing left to run
        await asyncio.to_thread(upgrade, db, "0053")
    assert bookkeeping and all(_bookkeeping(b) for b in bookkeeping), bookkeeping
    allowed = reads | set(bookkeeping)
    assert _unapproved(sent, upgrade_changes, allowed | {_version_update("0052", "0053")}) == []
    with captured() as sent:
        await asyncio.to_thread(downgrade, db, "0052")
    assert _unapproved(sent, downgrade_changes, allowed | {_version_update("0053", "0052")}) == []


@pytest.mark.parametrize(
    "extra",
    ["CREATE SCHEMA extra", "SELECT set_config('search_path', 'public', false)", "SELECT pg_terminate_backend(1)",
     "SHOW search_path", "SELECT nextval('public.audit_log_id_seq')"],
)  # fmt: skip
def test_the_runtime_check_catches_an_unapproved_statement(extra: str) -> None:
    changes, _ = approved()
    allowed = {_as_sent(getattr(_module(), name)) for name in PHASE0} | {VERSION_READ}
    assert _unapproved([*changes[:3], extra, *changes[3:]], changes, allowed) == [extra]
    assert not _bookkeeping(extra)


def test_the_runtime_check_catches_a_change_left_out() -> None:
    changes, _ = approved()
    assert _unapproved(changes[:-1], changes, set()) != []


def test_bookkeeping_is_alembics_version_read_and_a_catalog_read_only() -> None:
    assert _bookkeeping(VERSION_READ)
    assert _bookkeeping("SELECT pg_catalog.pg_class.relname \nFROM pg_catalog.pg_class JOIN pg_catalog.pg_namespace "
                        "ON pg_catalog.pg_namespace.oid = pg_catalog.pg_class.relnamespace")  # fmt: skip
    assert not _bookkeeping("SELECT pg_catalog.pg_class.relname FROM pg_catalog.pg_class JOIN public.runs ON true")
    assert not _bookkeeping("SELECT alembic_version.version_num FROM alembic_version FOR UPDATE")


# Test 9 (the owner's): an interrupted upgrade rolls back whole, and a retry succeeds.


async def test_an_interrupted_upgrade_leaves_nothing_and_a_retry_succeeds(db: str) -> None:
    before = await state(db)

    def interrupt(index: int) -> None:
        if index == 9:  # past CREATE ROLE, CREATE SCHEMA and some revokes
            raise RuntimeError("interrupted on purpose")

    with pytest.raises(Exception, match="interrupted on purpose"):
        await asyncio.to_thread(upgrade, db, "0053", _hooked(interrupt))
    assert await state(db) == before  # role, schema, ACLs and alembic_version (0052) as they were
    await asyncio.to_thread(upgrade, db, "0053")
    snap, _, version = await state(db)
    assert version == "0053"
    assert (snap["objects"], snap["grants"]) == after()


# Test 10: bounded locks.


async def test_normal_operations_never_wait_on_its_open_transaction(db: str) -> None:
    paused, release = threading.Event(), threading.Event()
    last = len(approved()[0]) - 1

    def hold(index: int) -> None:
        if index == last:  # every change made, not committed yet
            paused.set()
            release.wait(30)

    upgrading = asyncio.create_task(asyncio.to_thread(upgrade, db, "0053", _hooked(hold)))
    try:
        while not paused.is_set():
            assert not upgrading.done(), "the upgrade ended before it paused"
            await asyncio.sleep(0.05)
        load = Load(db)
        await load.prepare()
        started = time.monotonic()
        c = await asyncpg.connect(db)
        assert time.monotonic() - started < 1.0, "a new connection"
        try:
            await c.execute("SET lock_timeout = '1s'")
            for kind in Load.KINDS:
                started = time.monotonic()
                try:
                    async with c.transaction():
                        await load._op(c, kind)
                except asyncpg.LockNotAvailableError:
                    pytest.fail(f"{kind} waited on 0053's open transaction")
                except asyncpg.PostgresError:
                    pass  # a synthetic operation refused for its own reasons: not a wait
                assert time.monotonic() - started < 1.0, kind
            started = time.monotonic()
            async with c.transaction():
                await c.execute("SET LOCAL ROLE dewpoint_api")
                await c.fetchval("SELECT public.app_tenant_id()")
            assert time.monotonic() - started < 1.0
        finally:
            await c.close()
    finally:
        release.set()
        await upgrading
    assert (await state(db))[2] == "0053"


async def test_a_lock_it_cant_take_in_time_rolls_it_all_back(db: str) -> None:
    before = await state(db)
    holder = await asyncpg.connect(db)
    try:
        await holder.execute("BEGIN")
        await holder.fetch("SELECT version_num FROM alembic_version FOR UPDATE")
        started = time.monotonic()
        with pytest.raises(Exception, match="lock timeout|LockNotAvailable|canceling statement due to lock"):
            await asyncio.to_thread(upgrade, db, "0053")
        assert 4.0 < time.monotonic() - started < 30.0
    finally:
        await holder.execute("ROLLBACK")
        await holder.close()
    assert await state(db) == before


# The trigger functions lose PUBLIC's EXECUTE with no grant (gate A, section 3): their writers' writes don't change.

TRIGGERED = {
    "dewpoint_dispatch": ["insert a root run", "change a run's tree"],
    "dewpoint_worker": ["insert a root run", "change a run's tree"],
    # its tenant's erasure at stage 80 (the gate's restrictive policy lets it, the trigger too), then past it
    "dewpoint_retention": ["delete a version at stage 80", "delete a version at stage 90"],
}


class _RolledBack(Exception):
    pass


async def _copied(c: asyncpg.Connection, table: str, row: Any, **values: Any) -> None:
    """A copy of `row` in `table`, with `values` for some of its columns."""
    columns = [k for k in row.keys() if k != "root_run_id"]
    await c.execute(f"INSERT INTO public.{table} ({', '.join(columns)}) "  # noqa: S608
                    f"VALUES ({', '.join(f'${i + 1}' for i in range(len(columns)))})",
                    *(values.get(k, row[k]) for k in columns))  # fmt: skip


async def _write(c: asyncpg.Connection, role: str, write: str, run: Any, other: Any, version: Any) -> str:
    """One write as `role`, in its row's tenant (the policies' `app.tenant_id`), in a transaction rolled back after."""
    tenant = version["tenant_id"] if write.startswith("delete") else run["tenant_id"]
    outcome = ""
    try:
        async with c.transaction():
            new = uuid.uuid4()
            if write.startswith("delete"):  # a version of its own, then the tenant's erasure at the stage
                number = await c.fetchval("SELECT max(number) + 1 FROM public.workflow_versions WHERE workflow_id = $1",
                                          version["workflow_id"])  # fmt: skip
                await _copied(c, "workflow_versions", version, id=new, number=number)
                await c.execute("UPDATE public.tenants SET status = 'erasing' WHERE id = $1", tenant)
                await c.execute("INSERT INTO public.tenant_erasures (tenant_id, requested_by, step) "
                                "VALUES ($1, gen_random_uuid(), $2)", tenant, int(write[-2:]))  # fmt: skip
            await c.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant))
            await c.execute(f"SET LOCAL ROLE {role}")
            if write == "insert a root run":
                await _copied(c, "runs", run, id=new)
                await c.execute("RESET ROLE")
                root = await c.fetchval("SELECT root_run_id FROM public.runs WHERE id = $1", new)
                outcome = "root set" if root == new else f"root {root}"
            elif write == "change a run's tree":
                done = await c.execute("UPDATE public.runs SET parent_run_id = $1 WHERE id = $2", other, run["id"])
                outcome = f"changed: {done}"
            else:
                outcome = await c.execute("DELETE FROM public.workflow_versions WHERE id = $1", new)
            raise _RolledBack
    except _RolledBack:
        return outcome
    except asyncpg.PostgresError as e:
        return f"{e.sqlstate}: {e}"


async def _writes(url: str) -> dict[tuple[str, str], str]:
    """Each writer role's write that fires one of the three trigger functions: what happened (the root
    runs_set_root sets, the row deleted, or the error a trigger raises)."""
    c = await asyncpg.connect(url)
    try:
        run = await c.fetchrow("SELECT * FROM public.runs WHERE parent_run_id IS NULL ORDER BY id LIMIT 1")
        other = await c.fetchval("SELECT id FROM public.runs WHERE id <> $1 AND tenant_id = $2 ORDER BY id LIMIT 1",
                                 run["id"], run["tenant_id"])  # fmt: skip
        version = await c.fetchrow("SELECT * FROM public.workflow_versions ORDER BY id LIMIT 1")
        return {(role, write): await _write(c, role, write, run, other, version)
                for role, writes in TRIGGERED.items() for write in writes}  # fmt: skip
    finally:
        await c.close()


async def test_the_trigger_functions_fire_for_their_writers_without_execute(db: str) -> None:
    at_0052 = await _writes(db)
    # The writes this test makes, as they are before 0053: each fires its trigger function, which acts
    assert at_0052[("dewpoint_dispatch", "insert a root run")] == "root set", at_0052
    assert at_0052[("dewpoint_worker", "insert a root run")] == "root set", at_0052
    for role in ("dewpoint_dispatch", "dewpoint_worker"):
        assert "a run's tree never changes" in at_0052[(role, "change a run's tree")], at_0052
    assert at_0052[("dewpoint_retention", "delete a version at stage 80")] == "DELETE 1", at_0052
    assert "workflow_versions rows are immutable" in at_0052[("dewpoint_retention", "delete a version at stage 90")]
    await asyncio.to_thread(upgrade, db, "0053")
    assert await _writes(db) == at_0052


# The language amendment (gate A revision 6): PUBLIC's USAGE on plpgsql and sql revoked; c and internal can't be, and
# their USAGE lets no non-superuser make a function or run a DO block in them.


async def _outcome(url: str, role: str, statement: str, *setup: str) -> str:
    """`statement` as `role`, after `setup` as the superuser, in a transaction rolled back after: "allowed", or what
    refused it."""
    c = await asyncpg.connect(url)
    try:
        async with c.transaction():
            for prepared in setup:
                await c.execute(prepared)
            await c.execute(f"SET LOCAL ROLE {role}")
            await c.execute(statement)
            raise _RolledBack
    except _RolledBack:
        return "allowed"
    except asyncpg.PostgresError as e:
        return f"{e.sqlstate}: {e}"
    finally:
        await c.close()


async def test_each_service_role_loses_exactly_what_gate_a_takes(db: str) -> None:
    at_0052 = (await state(db))[1]
    await asyncio.to_thread(upgrade, db, "0053")
    at_0053 = (await state(db))[1]
    for role in SERVICE_ROLES:
        assert at_0053[role] - at_0052[role] == set(), role
        assert at_0052[role] - at_0053[role] == lost(role), role
    assert at_0053[PROBE] - at_0052[PROBE] == set()
    assert at_0052[PROBE] - at_0053[PROBE] == lost(PROBE) | {("schema", "public", "USAGE")}


async def test_no_service_role_runs_a_do_block_after_0053(db: str) -> None:
    at_0052 = {r: await _outcome(db, r, "DO $$ BEGIN END $$") for r in SERVICE_ROLES}
    await asyncio.to_thread(upgrade, db, "0053")
    at_0053 = {r: await _outcome(db, r, "DO $$ BEGIN END $$") for r in SERVICE_ROLES}
    assert set(at_0052.values()) == {"allowed"}, at_0052
    assert all("permission denied for language plpgsql" in o for o in at_0053.values()), at_0053


async def test_each_granted_function_runs_for_its_roles_alone(db: str) -> None:
    await asyncio.to_thread(upgrade, db, "0053")
    for function, call in CALLS.items():
        for role in SERVICE_ROLES:
            outcome = await _outcome(db, role, call)
            expected = "allowed" if role in GRANTED[function] else "permission denied for function"
            assert expected in outcome, (function, role, outcome)


SCRATCH = ("CREATE SCHEMA rcv_scratch", "GRANT USAGE, CREATE ON SCHEMA rcv_scratch TO rcv_test_member")
LANGUAGES = {  # a function, and a DO block where the language has an inline handler
    "c": ["CREATE FUNCTION rcv_scratch.f() RETURNS integer LANGUAGE c AS 'nothing', 'nothing'", "DO LANGUAGE c $$ $$"],
    "internal": [
        "CREATE FUNCTION rcv_scratch.f() RETURNS integer LANGUAGE internal AS 'int4in'",
        "DO LANGUAGE internal $$ $$",
    ],  # fmt: skip
    "plpgsql": [
        "CREATE FUNCTION rcv_scratch.f() RETURNS integer LANGUAGE plpgsql AS 'BEGIN RETURN 1; END'",
        "DO $$ BEGIN END $$",
    ],  # fmt: skip
    "sql": ["CREATE FUNCTION rcv_scratch.f() RETURNS integer LANGUAGE sql AS 'SELECT 1'"],
}


async def test_a_non_superuser_with_a_schema_to_create_in_uses_no_language(db: str, cluster: str) -> None:
    """Given CREATE on a schema of its own (in a transaction rolled back): the untrusted languages need a superuser,
    before 0053 and after; the trusted ones are PUBLIC's no more after it. As a member of dewpoint_recovery after 0053,
    as a recovery login is."""
    await _sql(f"{cluster}/postgres", "CREATE ROLE rcv_test_member NOLOGIN")
    tries = [(language, statement) for language, statements in LANGUAGES.items() for statement in statements]
    at_0052 = {t: await _outcome(db, "rcv_test_member", t[1], *SCRATCH) for t in tries}
    await asyncio.to_thread(upgrade, db, "0053")
    await _sql(f"{cluster}/postgres", "GRANT dewpoint_recovery TO rcv_test_member")
    at_0053 = {t: await _outcome(db, "rcv_test_member", t[1], *SCRATCH) for t in tries}
    for (language, statement), outcome in at_0052.items():
        expected = "allowed" if language in ("plpgsql", "sql") else f"permission denied for language {language}"
        assert expected in outcome, (statement, outcome)
    for (language, statement), outcome in at_0053.items():
        assert f"permission denied for language {language}" in outcome, (statement, outcome)


# Test 11: 0053's schema, from a fresh database, its deployment not yet recorded (as a fresh installation's): to 0053,
# where 0053 ends (later revisions have tests of their own; tests/migrations/test_0054.py checks head's).


@pytest.mark.parametrize("path", [["0053"], ["0052", "0053"]])
async def test_a_fresh_database_migrated_to_head_ends_at_the_reference(cluster: str, made: list[str],
                                                                          path: list[str]) -> None:  # fmt: skip
    name = f"f{uuid.uuid4().hex[:12]}"
    await _sql(f"{cluster}/postgres", f'CREATE DATABASE "{name}"')
    made.append(name)
    for target in path:
        await asyncio.to_thread(upgrade, f"{cluster}/{name}", target)
    snap, _, version = await state(f"{cluster}/{name}")
    assert version == "0053"
    assert (snap["objects"], snap["grants"]) == after()
