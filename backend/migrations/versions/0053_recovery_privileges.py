# SPDX-License-Identifier: Apache-2.0
"""2b-4b M4, operator recovery: the database's privileges for recovery, as gate A reviewed them (task 2, the owner's
limited go, 2026-10-10). PUBLIC loses EXECUTE on the application's 44 functions (36 of them pgcrypto's), USAGE on schema
`public` and TEMPORARY on this database; 18 explicit grants keep each service role's uses, and `dewpoint_start_check`
gets USAGE on `public`; functions made later are PUBLIC's to execute no more (default privileges). A cluster role,
`dewpoint_recovery` (NOLOGIN, its comment the marker), and schema `recovery`, which it alone may use, are made for the
recovery functions to come. PUBLIC loses USAGE on the trusted languages, `plpgsql` and `sql` (gate A revision 6):
PostgreSQL refuses GRANT and REVOKE on the untrusted `c` and `internal`, whose inherited USAGE can't let a non-superuser
make a function or run a DO block in them (a named exception of the recovery allow-list).

One transaction, Alembic's own for this migration (the owner's transactional exception, 2026-10-10): its checks, its
changes and Alembic's version update commit or roll back together, so an interrupted run leaves nothing, its own role
included. It isn't an online (D15) migration: it takes no lock on an application table and writes catalog rows only
(the functions', the languages', the schemas', this database's and the role's ACLs, one default-ACL row, the role and
its comment). `lock_timeout` bounds each lock wait (5 s, online.py's): one not taken in time rolls it all back.

Phase 0, checks only, before any change; each failure raises, and nothing changes:
- the guard: the database named explicitly (`-x expected_database=`, or DEWPOINT_EXPECTED_DATABASE, through env.py)
  is the current one, Dewpoint's (its `alembic_version` and `platform_settings` tables: a fresh installation records
  its deployment only after migrating, so the row can't be required), at 0052 to upgrade or 0053 to downgrade;
- the drift check, with `search_path` pinned to `pg_catalog, pg_temp`: `snapshot_0053.sql`'s objects and grants equal
  gate A's reference (`expected_0053.json`) exactly, and neither the role nor the schema exists; to downgrade, the rows
  it touches are as the upgrade left them;
- the role: to upgrade, no `dewpoint_recovery` exists, wherever it came from (a collision: another database of this
  cluster may have run 0053, and one Dewpoint database per cluster may); to downgrade, it is exactly the role made
  here, with no member and a member of nothing (a provisioned recovery login stops the downgrade).

Phase 1 runs the approved statements, as literal text, in order (`tests/migrations/approved_0053.sql`); the one not
written literally, TEMPORARY's, names the current database through `format('%I', current_database())`."""

import json
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None

_HERE = Path(__file__).resolve().parents[1]
_SNAPSHOT = (_HERE / "snapshot_0053.sql").read_text()
_EXPECTED = json.loads((_HERE / "expected_0053.json").read_text())
_SECTIONS = {
    part.split("\n", 1)[0].strip(): part.split("\n", 1)[1].strip().rstrip(";")
    for part in _SNAPSHOT.split("\n-- name: ")[1:]
}
OBJECTS = _SECTIONS["objects"]
GRANTS = _SECTIONS["grants"]
PRESENCE = _SECTIONS["recovery_presence"]

MARKER = "dewpoint:recovery-group:created-by-0053"
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
SEARCH_PATH = "SELECT current_setting('search_path')"
PINNED = "SET LOCAL search_path = pg_catalog, pg_temp"
RESTORED = "SELECT set_config('search_path', :saved, true)"
DATABASE = (
    "SELECT current_database(), to_regclass('public.alembic_version') IS NOT NULL, "
    "to_regclass('public.platform_settings') IS NOT NULL"
)
VERSION = "SELECT version_num FROM public.alembic_version"
ROLE = """SELECT r.rolsuper, r.rolinherit, r.rolcreaterole, r.rolcreatedb, r.rolcanlogin, r.rolreplication,
       r.rolbypassrls, r.rolconnlimit, r.rolvaliduntil IS NULL, coalesce(shobj_description(r.oid, 'pg_authid'), ''),
       (SELECT count(*) FROM pg_auth_members m WHERE m.roleid = r.oid),
       (SELECT count(*) FROM pg_auth_members m WHERE m.member = r.oid)
  FROM pg_roles r WHERE r.rolname = 'dewpoint_recovery'"""
# The role made here, as ROLE reads it: no member, a member of nothing
MADE = (False, True, False, False, False, False, False, -1, True, MARKER, 0, 0)

UPGRADE = (
    "CREATE ROLE dewpoint_recovery NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
    "COMMENT ON ROLE dewpoint_recovery IS 'dewpoint:recovery-group:created-by-0053'",
    "CREATE SCHEMA recovery",
    "REVOKE ALL ON SCHEMA recovery FROM PUBLIC",
    "GRANT USAGE ON SCHEMA recovery TO dewpoint_recovery",
    "REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_admin",
    "GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_api",
    "GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_auditor",
    "GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_dispatch",
    "GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_retention",
    "GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO dewpoint_worker",
    "REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_admin",
    "GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_api",
    "GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_dispatch",
    "GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_retention",
    "GRANT EXECUTE ON FUNCTION public.app_user_id() TO dewpoint_worker",
    "REVOKE EXECUTE ON FUNCTION public.armor(bytea) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.armor(bytea,text[],text[]) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_admin",
    "GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_api",
    "GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_auditor",
    "GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_dispatch",
    "GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_ingress",
    "GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_retention",
    "GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO dewpoint_worker",
    "REVOKE EXECUTE ON FUNCTION public.audit_reject() FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.crypt(text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.dearmor(text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.decrypt(bytea,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.decrypt_iv(bytea,bytea,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.digest(bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.digest(text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.encrypt(bytea,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.encrypt_iv(bytea,bytea,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.gen_random_bytes(integer) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.gen_salt(text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.gen_salt(text,integer) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.hmac(bytea,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.hmac(text,text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_armor_headers(text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_key_id(bytea) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea,text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea,text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_encrypt(text,bytea) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_encrypt(text,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_encrypt_bytea(bytea,bytea) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_pub_encrypt_bytea(bytea,bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_sym_decrypt(bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_sym_decrypt(bytea,text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_sym_decrypt_bytea(bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_sym_decrypt_bytea(bytea,text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_sym_encrypt(text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_sym_encrypt(text,text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_sym_encrypt_bytea(bytea,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.pgp_sym_encrypt_bytea(bytea,text,text) FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.platform_settings_recorded_once() FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.gen_random_uuid() FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.runs_set_root() FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.runs_tree_fixed() FROM PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.workflow_versions_immutable() FROM PUBLIC",
    "REVOKE USAGE ON SCHEMA public FROM PUBLIC",
    "GRANT USAGE ON SCHEMA public TO dewpoint_start_check",
    "DO $$ BEGIN EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database()); END $$",
    "ALTER DEFAULT PRIVILEGES REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC",
    "REVOKE USAGE ON LANGUAGE plpgsql FROM PUBLIC",
    "REVOKE USAGE ON LANGUAGE sql FROM PUBLIC",
)
DOWNGRADE = (
    "GRANT USAGE ON LANGUAGE sql TO PUBLIC",
    "GRANT USAGE ON LANGUAGE plpgsql TO PUBLIC",
    "ALTER DEFAULT PRIVILEGES GRANT EXECUTE ON FUNCTIONS TO PUBLIC",
    "DO $$ BEGIN EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO PUBLIC', current_database()); END $$",
    "REVOKE USAGE ON SCHEMA public FROM dewpoint_start_check",
    "GRANT USAGE ON SCHEMA public TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.workflow_versions_immutable() TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.runs_tree_fixed() TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.runs_set_root() TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.gen_random_uuid() TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.platform_settings_recorded_once() TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_sym_encrypt_bytea(bytea,text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_sym_encrypt_bytea(bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_sym_encrypt(text,text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_sym_encrypt(text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_sym_decrypt_bytea(bytea,text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_sym_decrypt_bytea(bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_sym_decrypt(bytea,text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_sym_decrypt(bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_encrypt_bytea(bytea,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_encrypt_bytea(bytea,bytea) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_encrypt(text,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_encrypt(text,bytea) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea,text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt_bytea(bytea,bytea) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea,text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_pub_decrypt(bytea,bytea) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_key_id(bytea) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.pgp_armor_headers(text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.hmac(text,text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.hmac(bytea,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.gen_salt(text,integer) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.gen_salt(text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.gen_random_bytes(integer) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.encrypt_iv(bytea,bytea,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.encrypt(bytea,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.digest(text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.digest(bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.decrypt_iv(bytea,bytea,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.decrypt(bytea,bytea,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.dearmor(text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.crypt(text,text) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.audit_reject() TO PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_admin",
    "REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_api",
    "REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_auditor",
    "REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_dispatch",
    "REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_ingress",
    "REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_retention",
    "REVOKE EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) FROM dewpoint_worker",
    "GRANT EXECUTE ON FUNCTION public.audit_canonical(bigint,text,uuid,text,text,text,jsonb,timestamp with time zone) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.armor(bytea,text[],text[]) TO PUBLIC",
    "GRANT EXECUTE ON FUNCTION public.armor(bytea) TO PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_admin",
    "REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_api",
    "REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_dispatch",
    "REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_retention",
    "REVOKE EXECUTE ON FUNCTION public.app_user_id() FROM dewpoint_worker",
    "GRANT EXECUTE ON FUNCTION public.app_user_id() TO PUBLIC",
    "REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_admin",
    "REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_api",
    "REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_auditor",
    "REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_dispatch",
    "REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_retention",
    "REVOKE EXECUTE ON FUNCTION public.app_tenant_id() FROM dewpoint_worker",
    "GRANT EXECUTE ON FUNCTION public.app_tenant_id() TO PUBLIC",
    "DROP SCHEMA recovery",
    "DROP ROLE dewpoint_recovery",
)


def _rows(name: str) -> set[tuple[object, ...]]:
    return {tuple(row) for row in _EXPECTED[name]}


def _changed(name: str) -> set[tuple[object, ...]]:
    return {tuple(row) for row in _EXPECTED["AFTER_CHANGES"].get(name)}


EXPECTED_OBJECTS = _rows("EXPECTED_OBJECTS")
EXPECTED_GRANTS = _rows("EXPECTED_GRANTS")
EXPECTED_AFTER = (
    (EXPECTED_OBJECTS - _changed("objects_removed")) | _changed("objects_added"),
    (EXPECTED_GRANTS - _changed("grants_removed")) | _changed("grants_added"),
)
# The rows the downgrade touches: the objects the upgrade touched, and those it made
TOUCHED = {(kind, identity) for kind, identity in _EXPECTED["TOUCHED"]} | {
    (row[0], row[1]) for row in _changed("objects_added")
}


def _same(what: str, found: set[tuple[object, ...]], expected: set[tuple[object, ...]]) -> None:
    """Raise, listing up to 20 rows, unless `found` is `expected` exactly."""
    if found != expected:
        missing, extra = sorted(expected - found), sorted(found - expected)
        raise RuntimeError(
            f"0053 refused: the database's {what} differ from gate A's reference: {len(missing)} missing "
            f"{missing[:20]}, {len(extra)} extra {extra[:20]}"
        )


def _checked(direction: str) -> None:
    """Phase 0: every check, in Alembic's transaction, before any change. Any failure raises, and it all rolls back."""
    bind = op.get_bind()
    bind.execute(text(LOCK_TIMEOUT))
    saved = bind.execute(text(SEARCH_PATH)).scalar_one()
    bind.execute(text(PINNED))
    expected = op.get_context().opts.get("expected_database")
    name, versioned, platform = bind.execute(text(DATABASE)).one()
    if expected is None:
        raise RuntimeError("0053 refused: no expected database (alembic -x expected_database=<name>)")
    if name != expected:
        raise RuntimeError(f"0053 refused: the current database is {name}, not the expected {expected}")
    if not (versioned and platform):
        raise RuntimeError("0053 refused: not a Dewpoint database (no alembic_version or platform_settings table)")
    at = bind.execute(text(VERSION)).scalar_one()
    if at != ("0052" if direction == "upgrade" else "0053"):
        raise RuntimeError(f"0053 refused: the database is at {at}, not where this {direction} starts")
    objects = {tuple(row) for row in bind.execute(text(OBJECTS))}
    grants = {tuple(row) for row in bind.execute(text(GRANTS))}
    presence = tuple(bind.execute(text(PRESENCE)).one())
    role = bind.execute(text(ROLE)).one_or_none()
    if direction == "upgrade":
        _same("objects", objects, EXPECTED_OBJECTS)
        _same("grants", grants, EXPECTED_GRANTS)
        if presence != (0, 0) or role is not None:
            raise RuntimeError("0053 refused: dewpoint_recovery or schema recovery exists already (a collision)")
    else:
        after_objects, after_grants = EXPECTED_AFTER
        _same("touched objects", {o for o in objects if (o[0], o[1]) in TOUCHED},
              {o for o in after_objects if (o[0], o[1]) in TOUCHED})  # fmt: skip
        _same("touched grants", {g for g in grants if (g[0], g[1]) in TOUCHED},
              {g for g in after_grants if (g[0], g[1]) in TOUCHED})  # fmt: skip
        if presence != (1, 1) or role is None or tuple(role) != MADE:
            raise RuntimeError("0053 refused: dewpoint_recovery isn't exactly the role 0053 made (a member, a "
                               "membership, another comment or attribute), or schema recovery is gone")  # fmt: skip
    bind.execute(text(RESTORED), {"saved": saved})


def _after_change(index: int) -> None:
    """A test's hook (`after_change`, through env.py), after each change: nothing, unless a test set one."""
    hook = op.get_context().opts.get("after_change")
    if hook is not None:
        hook(index)


def upgrade() -> None:
    _checked("upgrade")
    for index, statement in enumerate(UPGRADE):
        op.execute(statement)
        _after_change(index)


def downgrade() -> None:
    _checked("downgrade")
    for index, statement in enumerate(DOWNGRADE):
        op.execute(statement)
        _after_change(index)
