# SPDX-License-Identifier: Apache-2.0
"""What 0053's tests read of a database (gate A, 2b-4b M4 recovery): `snapshot_0053.sql`'s six sections, each role's
effective rights, and the comparison gate A defines for a downgrade (`restoration`)."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

BACKEND = Path(__file__).resolve().parents[2]
SNAPSHOT = BACKEND / "migrations" / "snapshot_0053.sql"
EXPECTED = BACKEND / "migrations" / "expected_0053.json"
SERVICE_ROLES = ("dewpoint_admin", "dewpoint_api", "dewpoint_auditor", "dewpoint_dispatch", "dewpoint_ingress",
                 "dewpoint_retention", "dewpoint_start_check", "dewpoint_worker")  # fmt: skip
MARKER = "dewpoint:recovery-group:created-by-0053"
GRANTED = {  # gate A's 18 grants, by function: its holders of EXECUTE among the service roles
    "public.app_tenant_id()": {
        "dewpoint_admin",
        "dewpoint_api",
        "dewpoint_auditor",
        "dewpoint_dispatch",
        "dewpoint_retention",
        "dewpoint_worker",
    },  # fmt: skip
    "public.app_user_id()": {
        "dewpoint_admin",
        "dewpoint_api",
        "dewpoint_dispatch",
        "dewpoint_retention",
        "dewpoint_worker",
    },  # fmt: skip
    "public.audit_canonical": {
        "dewpoint_admin",
        "dewpoint_api",
        "dewpoint_auditor",
        "dewpoint_dispatch",
        "dewpoint_ingress",
        "dewpoint_retention",
        "dewpoint_worker",
    },  # fmt: skip
}

Snapshot = dict[str, set[tuple[Any, ...]]]


def sections() -> dict[str, str]:
    """snapshot_0053.sql's sections, by name, as 0053 reads them."""
    parts = SNAPSHOT.read_text().split("\n-- name: ")[1:]
    return {p.split("\n", 1)[0].strip(): p.split("\n", 1)[1].strip().rstrip(";") for p in parts}


def snapshot(conn: Connection) -> Snapshot:
    """All six sections, with search_path pinned as gate A requires (a disposable connection of the test's own)."""
    conn.execute(text("SET search_path = pg_catalog, pg_temp"))
    try:
        return {name: {tuple(row) for row in conn.execute(text(sql))} for name, sql in sections().items()}
    finally:
        conn.execute(text("RESET search_path"))


def expected() -> dict[str, Any]:
    return json.loads(EXPECTED.read_text())


def before() -> tuple[set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    e = expected()
    return {tuple(o) for o in e["EXPECTED_OBJECTS"]}, {tuple(g) for g in e["EXPECTED_GRANTS"]}


def after() -> tuple[set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    """The reference after the approved upgrade: what derive_0053.py derived, kept in expected_0053.json."""
    e = expected()
    objects, grants = before()
    changes = e["AFTER_CHANGES"]
    objects = (objects - {tuple(o) for o in changes["objects_removed"]}) | {tuple(o) for o in changes["objects_added"]}
    grants = (grants - {tuple(g) for g in changes["grants_removed"]}) | {tuple(g) for g in changes["grants_added"]}
    return objects, grants


def touched() -> set[tuple[str, str]]:
    return {(k, i) for k, i in expected()["TOUCHED"]}


EFFECTIVE = """WITH s AS (SELECT oid, nspname FROM pg_namespace
           WHERE nspname NOT IN ('pg_catalog', 'information_schema') AND nspname !~ '^pg_(toast|temp)')
SELECT 'schema', quote_ident(s.nspname), p FROM s, unnest(ARRAY['USAGE', 'CREATE']) p
 WHERE has_schema_privilege(:r, s.oid, p)
UNION ALL
SELECT 'relation:' || c.relkind::text, quote_ident(s.nspname) || '.' || quote_ident(c.relname), p
  FROM pg_class c JOIN s ON s.oid = c.relnamespace,
       unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) p
 WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND has_table_privilege(:r, c.oid, p)
UNION ALL
SELECT 'relation:S', quote_ident(s.nspname) || '.' || quote_ident(c.relname), p
  FROM pg_class c JOIN s ON s.oid = c.relnamespace, unnest(ARRAY['USAGE', 'SELECT', 'UPDATE']) p
 WHERE c.relkind = 'S' AND has_sequence_privilege(:r, c.oid, p)
UNION ALL
SELECT 'column', quote_ident(s.nspname) || '.' || quote_ident(c.relname) || '.' || quote_ident(a.attname), p
  FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN s ON s.oid = c.relnamespace,
       unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']) p
 WHERE a.attnum > 0 AND NOT a.attisdropped AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
   AND has_column_privilege(:r, c.oid, a.attnum, p) AND NOT has_table_privilege(:r, c.oid, p)
UNION ALL
SELECT 'function:' || p.prokind::text,
       quote_ident(s.nspname) || '.' || quote_ident(p.proname)
         || '(' || pg_get_function_identity_arguments(p.oid) || ')',
       'EXECUTE'
  FROM pg_proc p JOIN s ON s.oid = p.pronamespace WHERE has_function_privilege(:r, p.oid, 'EXECUTE')
UNION ALL
SELECT 'type:' || t.typtype::text, quote_ident(s.nspname) || '.' || quote_ident(t.typname), 'USAGE'
  FROM pg_type t JOIN s ON s.oid = t.typnamespace
 WHERE t.typcategory <> 'A' AND (t.typrelid = 0 OR (SELECT c.relkind FROM pg_class c WHERE c.oid = t.typrelid) = 'c')
   AND has_type_privilege(:r, t.oid, 'USAGE')
UNION ALL
SELECT 'language', quote_ident(l.lanname), 'USAGE' FROM pg_language l WHERE has_language_privilege(:r, l.oid, 'USAGE')
UNION ALL
SELECT 'fdw', quote_ident(w.fdwname), 'USAGE' FROM pg_foreign_data_wrapper w
 WHERE has_foreign_data_wrapper_privilege(:r, w.oid, 'USAGE')
UNION ALL
SELECT 'server', quote_ident(v.srvname), 'USAGE' FROM pg_foreign_server v WHERE has_server_privilege(:r, v.oid, 'USAGE')
UNION ALL
SELECT 'database', '<current>', p FROM unnest(ARRAY['CONNECT', 'CREATE', 'TEMPORARY']) p
 WHERE has_database_privilege(:r, current_database(), p)"""


# The recovery allow-list's two named exceptions (gate A revision 6): PUBLIC's USAGE on the untrusted languages, which
# PostgreSQL refuses to grant or revoke, and which can't let a non-superuser make a function or run a DO block in them
UNTRUSTED = {("language", "c", "USAGE"), ("language", "internal", "USAGE")}
# What 0053 takes from every role that held it through PUBLIC alone (the functions aside: `lost`)
TAKEN = {("language", "plpgsql", "USAGE"), ("language", "sql", "USAGE"), ("database", "<current>", "TEMPORARY")}
CALLS = {  # one call of each granted function, with real arguments (audit_canonical isn't strict)
    "public.app_tenant_id()": "SELECT public.app_tenant_id()",
    "public.app_user_id()": "SELECT public.app_user_id()",
    "public.audit_canonical": "SELECT public.audit_canonical(1, 'platform', NULL, 'a', '', '', '{}'::jsonb, now())",
}


def granted(identity: str) -> set[str]:
    """The service roles gate A grants EXECUTE on the function `identity` (none for most of the 44)."""
    return {r for f, roles in GRANTED.items() if identity == f or identity.startswith(f + "(") for r in roles}


def lost(role: str) -> set[tuple[str, str, str]]:
    """What `role` loses to 0053, exactly: EXECUTE on each of the 44 functions it isn't granted, and TAKEN."""
    functions = {i for k, i in touched() if k == "function:f"}
    return TAKEN | {("function:f", i, "EXECUTE") for i in functions if role not in granted(i)}


def holders(rights: dict[str, set[Any]], function: str) -> set[str]:
    """The roles of `rights` that may execute `function` (its name, or its name and arguments)."""
    name = function if function.endswith(")") else function + "("
    return {r for r, held in rights.items() if any(k.startswith("function") and i.startswith(name)
                                                    for k, i, _ in held)}  # fmt: skip


def effective(conn: Connection, role: str) -> set[tuple[str, str, str]]:
    """Every right `role` holds, directly, through its memberships or through PUBLIC, on every object of the database
    outside the system schemas (large objects aside: PostgreSQL 16 has no privilege function for them, and none
    exist)."""
    return {tuple(r) for r in conn.execute(text(EFFECTIVE), {"r": role})}  # type: ignore[misc]


def restoration(before: Snapshot, after: Snapshot, rights_before: dict[str, set[Any]],
                rights_after: dict[str, set[Any]]) -> list[str]:  # fmt: skip
    """Gate A's section 4: identical, but that an ACL state may go from `default` to `explicit` on an object 0053
    touches, and only there."""
    found: list[str] = []
    allowed = touched()

    def keyed(rows: set[tuple[Any, ...]]) -> dict[tuple[str, str], tuple[Any, ...]]:
        return {(r[0], r[1]): r for r in rows}

    was, now = keyed(before["objects"]), keyed(after["objects"])
    found += [f"object gone: {k}" for k in sorted(was.keys() - now.keys())]
    found += [f"object added: {k}" for k in sorted(now.keys() - was.keys())]
    for key in sorted(was.keys() & now.keys()):
        (_, _, owner_b, state_b, detail_b), (_, _, owner_a, state_a, detail_a) = was[key], now[key]
        if (owner_b, detail_b) != (owner_a, detail_a):
            found.append(f"object changed: {key}")
        if state_b != state_a and not (key in allowed and state_b == "default" and state_a == "explicit"):
            found.append(f"ACL state {state_b} -> {state_a}: {key}")
    found += [f"grant gone: {g}" for g in sorted(before["grants"] - after["grants"])]
    found += [f"grant added: {g}" for g in sorted(after["grants"] - before["grants"])]
    for name in ("roles", "memberships", "recovery_presence"):
        if before[name] != after[name]:
            found.append(f"{name} differ: {sorted(before[name] ^ after[name])[:5]}")

    def databases(rows: set[tuple[Any, ...]], state_of_current: str) -> set[tuple[Any, ...]]:
        return {(r[0], r[1], state_of_current if r[0] == "<current>" and r[2] in ("default", "explicit") else r[2],
                 *r[3:]) for r in rows}  # fmt: skip

    if databases(before["databases"], "-") != databases(after["databases"], "-"):
        found.append("databases differ")
    for role in sorted(rights_before.keys() | rights_after.keys()):
        if rights_before.get(role) != rights_after.get(role):
            found.append(f"effective rights of {role} differ")
    return found
