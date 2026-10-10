# SPDX-License-Identifier: Apache-2.0
"""What the online migrations' tests read of a database's catalogue: its security boundaries (`security`), checked at
each committed step against the states before and after the upgrade (`violations`), and its whole schema (`schema`),
compared between two databases."""

import asyncio
import hashlib
import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import asyncpg
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

BACKEND = Path(__file__).resolve().parents[2]

# A grantee: PUBLIC, the migrating role (the objects' owner, whatever its name), or the role's name
GRANTEE = (
    "CASE WHEN a.grantee = 0 THEN 'PUBLIC' WHEN pg_get_userbyid(a.grantee) = current_user THEN 'owner' "
    "ELSE pg_get_userbyid(a.grantee) END"
)
PRIVILEGES = f"""
SELECT c.relname, {GRANTEE}, a.privilege_type
FROM pg_class c, aclexplode(coalesce(c.relacl, acldefault((CASE WHEN c.relkind = 'S' THEN 's' ELSE 'r' END)::"char",
                                                            c.relowner))) a
WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'v', 'S')
UNION ALL
SELECT c.relname || '.' || t.attname, {GRANTEE},
       a.privilege_type
FROM pg_attribute t JOIN pg_class c ON c.oid = t.attrelid, aclexplode(t.attacl) a
WHERE c.relnamespace = 'public'::regnamespace AND t.attacl IS NOT NULL AND NOT t.attisdropped
UNION ALL
SELECT p.oid::regprocedure::text, {GRANTEE},
       a.privilege_type
FROM pg_proc p, aclexplode(coalesce(p.proacl, acldefault('f'::"char", p.proowner))) a
WHERE p.pronamespace = 'public'::regnamespace
UNION ALL
SELECT 'schema public', {GRANTEE}, a.privilege_type
FROM pg_namespace n, aclexplode(coalesce(n.nspacl, acldefault('n'::"char", n.nspowner))) a WHERE n.nspname = 'public'
"""
POLICIES = """SELECT tablename, policyname, permissive, roles::text, cmd, coalesce(qual, ''), coalesce(with_check, '')
FROM pg_policies WHERE schemaname = 'public'"""
RLS = """SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p')"""
TRIGGERS = """SELECT c.relname, t.tgname, t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal AND c.relnamespace = 'public'::regnamespace"""
DEFINERS = """SELECT oid::regprocedure::text, md5(prosrc), coalesce(proconfig::text, '') FROM pg_proc
WHERE pronamespace = 'public'::regnamespace AND prosecdef"""
KEYS = """SELECT conrelid::regclass::text, confrelid::regclass::text, count(*) FROM pg_constraint
WHERE contype = 'f' AND connamespace = 'public'::regnamespace GROUP BY 1, 2"""
ROLES = "SELECT rolname, rolsuper, rolinherit, rolcanlogin, rolbypassrls FROM pg_roles WHERE rolname LIKE 'dewpoint%'"
MEMBERS = """SELECT r.rolname, m.rolname FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid
JOIN pg_roles m ON m.oid = a.member WHERE r.rolname LIKE 'dewpoint%' AND m.rolname LIKE 'dewpoint%'"""

CONSTRAINTS = """SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid), convalidated FROM pg_constraint
WHERE connamespace = 'public'::regnamespace"""
INDEXES = "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'"
VALID = """SELECT c.relname, i.indisvalid, i.indisready FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
WHERE c.relnamespace = 'public'::regnamespace"""
COLUMNS = """SELECT table_name, ordinal_position, column_name, data_type, is_nullable, coalesce(column_default, '')
FROM information_schema.columns WHERE table_schema = 'public'"""
FUNCTIONS = """SELECT oid::regprocedure::text, md5(prosrc), coalesce(proconfig::text, ''), prosecdef, provolatile,
pg_get_function_result(oid) FROM pg_proc WHERE pronamespace = 'public'::regnamespace"""
TRIGGER_DEFS = """SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
WHERE NOT t.tgisinternal AND c.relnamespace = 'public'::regnamespace"""
SEQUENCES = """SELECT sequencename, data_type::text, start_value, increment_by FROM pg_sequences
WHERE schemaname = 'public'"""


def _rows(conn: Connection, query: str) -> set[tuple[Any, ...]]:
    return {tuple(row) for row in conn.execute(text(query))}


def security(conn: Connection) -> dict[str, Any]:
    """The boundaries a committed step must keep: privileges (tables, columns, sequences, functions, the schema),
    policies, row-level security, triggers, security-definer functions, the keys between tables, roles."""
    return {
        "privileges": _rows(conn, PRIVILEGES),
        "policies": {(r[0], r[1]): r[2:] for r in _rows(conn, POLICIES)},
        "rls": {r[0]: r[1:] for r in _rows(conn, RLS)},
        "triggers": _rows(conn, TRIGGERS),
        "definers": {r[0]: r[1:] for r in _rows(conn, DEFINERS)},
        "keys": {(r[0], r[1]): r[2] for r in _rows(conn, KEYS)},
        "roles": _rows(conn, ROLES) | {("member", *r) for r in _rows(conn, MEMBERS)},
    }


def schema(conn: Connection) -> dict[str, Any]:
    """Everything an upgrade's end state is compared on: the boundaries above, every constraint (validated), index
    (valid), column, function, trigger and sequence."""
    return {**security(conn), **{name: _rows(conn, query) for name, query in {
        "constraints": CONSTRAINTS, "indexes": INDEXES, "valid": VALID, "columns": COLUMNS, "functions": FUNCTIONS,
        "trigger_defs": TRIGGER_DEFS, "sequences": SEQUENCES,
    }.items()}}  # fmt: skip


# What the online migrations add to the originals on purpose: 0040's capture of the schedules added until the
# inventory's cutover (the owner's D15 ruling on the 2b-4b M1 checkpoint)
ADDED = (
    "schedule_inventory_cutover", "schedule_inventory_catch_up", "schedule_inventory_capture", "schedule_inventoried",
    "schedules_inventoried",
)  # fmt: skip


def fingerprint(conn: Connection, excluding: tuple[str, ...] = ()) -> dict[str, list[Any]]:
    """Each part of `schema`: its rows' count and a digest of them, sorted: what a revision's state is compared on.
    Rows naming any of `excluding` are left out."""
    parts = {}
    for name, rows in schema(conn).items():
        kept = (repr(row) for row in (rows.items() if isinstance(rows, dict) else rows))
        flat = sorted(row for row in kept if not any(name in row for name in excluding))
        parts[name] = [len(flat), hashlib.sha256("\n".join(flat).encode()).hexdigest()]
    return parts


COMMANDS = {"ALL": {"SELECT", "INSERT", "UPDATE", "DELETE"}, "SELECT": {"SELECT"}, "INSERT": {"INSERT"},
            "UPDATE": {"UPDATE"}, "DELETE": {"DELETE"}}  # fmt: skip


def violations(before: dict[str, Any], at: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """How the state `at` a committed step breaks a boundary that holds both `before` the upgrade and `after` it: a
    privilege neither had; a policy in a form neither had; a privilege new since `before` without a restrictive policy
    `after` puts on it, or a restrictive policy both have, missing; a privilege new since `before` while a trigger the
    migration adds is missing (a migration's grants come after everything that bounds them: the erasure's insert fence,
    say, before the eraser may advance an erasure); a table's row-level security in neither's form (a new table's, not
    `after`'s); a trigger both had, missing; a security-definer function in neither's form; fewer keys between two
    tables than both had; a role neither had."""
    found = [f"privilege {p}" for p in sorted(at["privileges"] - before["privileges"] - after["privileges"])]
    for key, form in sorted(at["policies"].items()):
        if form not in (before["policies"].get(key), after["policies"].get(key)):
            found.append(f"policy {key} in a form neither before nor after")
    new = at["privileges"] - before["privileges"]
    for (table, name), (permissive, roles, applies, *_) in sorted(after["policies"].items()):
        if permissive != "RESTRICTIVE" or (table, name) in at["policies"]:
            continue
        named = set(roles.strip("{}").split(","))
        for obj, grantee, privilege in new:
            gated = privilege in COMMANDS[applies] and ("public" in named or grantee in named)
            if obj.split(".")[0] == table and gated:
                found.append(f"{grantee} {privilege} on {obj} without the restrictive policy {name}")
    for key, form in sorted(before["policies"].items()):
        if form[0] == "RESTRICTIVE" and after["policies"].get(key) == form and key not in at["policies"]:
            found.append(f"restrictive policy {key} missing")
    # Granted: not the migrating role's, which owns what it makes, nor `PUBLIC`'s default on a new invoker function
    # (a trigger's), which runs with its caller's privileges
    granted = {
        p for p in new if p[1] != "owner" and not (p[1] == "PUBLIC" and "(" in p[0] and p[0] not in at["definers"])
    }
    unadded = sorted(after["triggers"] - before["triggers"] - at["triggers"])
    if granted and unadded:
        found.append(f"{len(granted)} privileges granted while {len(unadded)} triggers aren't there: {unadded[:2]}")
    for table, form in sorted(at["rls"].items()):
        allowed = [after["rls"].get(table), *([before["rls"][table]] if table in before["rls"] else [])]
        if form not in allowed:
            found.append(f"row-level security of {table}: {form}")
    found += [f"trigger {t} missing" for t in sorted((before["triggers"] & after["triggers"]) - at["triggers"])]
    for fn, form in sorted(at["definers"].items()):
        if form not in (before["definers"].get(fn), after["definers"].get(fn)):
            found.append(f"security-definer function {fn} in a form neither before nor after")
    for pair in sorted(set(before["keys"]) | set(after["keys"])):
        both = min(before["keys"].get(pair, 0), after["keys"].get(pair, 0))
        if set(pair) <= set(at["rls"]) and at["keys"].get(pair, 0) < both:
            found.append(f"keys from {pair[0]} to {pair[1]}: {at['keys'].get(pair, 0)} of {both}")
    found += [f"role {r}" for r in sorted(at["roles"] - before["roles"] - after["roles"])]
    return found


def alembic_config(migrations: Path = BACKEND / "migrations") -> Config:
    """The repository's migrations (or others'), without alembic.ini's logging configuration, which would replace the
    test run's."""
    config = Config()
    config.set_main_option("script_location", str(migrations))
    return config


FROM_URL = "<the url's database>"  # the default expected name (0053's guard): the database `url` names


def _alembic(url: str, config: Config | None, run: Callable[[Config], None], expected: str | None = FROM_URL) -> None:
    """An Alembic command in this process (its hooks seen here), on `url` (asyncpg's, plain); env.py reads the url, and
    the expected database's name 0053's guard compares (`expected`: the url's own by default, None for none), from the
    environment, restored after."""
    before = {k: os.environ.get(k) for k in ("DEWPOINT_DATABASE_URL", "DEWPOINT_EXPECTED_DATABASE")}
    os.environ["DEWPOINT_DATABASE_URL"] = url.replace("postgresql://", "postgresql+asyncpg://")
    name = url.rsplit("/", 1)[1].split("?", 1)[0] if expected == FROM_URL else expected
    if name is None:
        os.environ.pop("DEWPOINT_EXPECTED_DATABASE", None)
    else:
        os.environ["DEWPOINT_EXPECTED_DATABASE"] = name
    try:
        run(config or alembic_config())
    finally:
        for key, value in before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def upgrade(url: str, target: str = "head", config: Config | None = None, expected: str | None = FROM_URL) -> None:
    _alembic(url, config, lambda c: command.upgrade(c, target), expected)


def downgrade(url: str, target: str, config: Config | None = None, expected: str | None = FROM_URL) -> None:
    _alembic(url, config, lambda c: command.downgrade(c, target), expected)


def autocommitted[T](url: str, fn: Callable[[Connection], T]) -> T:
    """`fn` on a connection of its own in autocommit, as a migration's online statements run, in this thread."""

    async def run() -> T:
        engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://"), poolclass=NullPool)
        try:
            async with engine.connect() as c:
                c = await c.execution_options(isolation_level="AUTOCOMMIT")
                return await c.run_sync(fn)
        finally:
            await engine.dispose()

    return asyncio.run(run())


@contextmanager
def recorded() -> Iterator[list[tuple[str, dict[str, Any]]]]:
    """Each step the online migrations commit while recorded: its name and the security state it committed."""
    from migrations import online

    seen: list[tuple[str, dict[str, Any]]] = []

    def hook(conn: Connection, name: str) -> None:
        seen.append((name, security(conn)))

    online.AFTER.append(hook)
    try:
        yield seen
    finally:
        online.AFTER.remove(hook)


async def copy(base: str, template: str) -> str:
    """A new database copied from `template`: its url."""
    name = f"d{uuid.uuid4().hex[:12]}"
    c = await asyncpg.connect(f"{base}/postgres")
    try:
        await c.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template}"')
    finally:
        await c.close()
    return f"{base}/{name}"
