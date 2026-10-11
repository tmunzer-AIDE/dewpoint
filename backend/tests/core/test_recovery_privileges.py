# SPDX-License-Identifier: Apache-2.0
"""The privileges 0053 leaves at head (2b-4b M4 recovery, gate A's test 4 and section 2), on the session's database: a
recovery login, a member of `dewpoint_recovery`, may connect and use schema `recovery`, and nothing else of the
database's but the allow-list's two named exceptions (USAGE on the untrusted languages, inert); it creates nothing.
PUBLIC executes no function of the application's, uses no schema `public` and no trusted language, and makes no
temporary table; each service role executes exactly the functions gate A granted it."""

import uuid
from collections.abc import Iterator

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection

from tests.migrations.state_0053 import GRANTED, SERVICE_ROLES, UNTRUSTED, effective, holders
from tests.migrations.support import autocommitted

RECOVERY_FUNCTIONS = (  # each with its task: the confirmation (task 6)
    "recovery.operator_command_show(command_id uuid)",
    "recovery.operator_command_confirm(command_id uuid, digest bytea)",
    "recovery.unresolved_send_reveal(command_id uuid)",  # the reveal (task 9)
)


@pytest.fixture
def login(pg_url: str) -> Iterator[str]:
    name = f"rcv_test_{uuid.uuid4().hex[:12]}"
    autocommitted(pg_url, lambda c: c.execute(text(f"CREATE ROLE {name} LOGIN IN ROLE dewpoint_recovery")))
    yield name
    autocommitted(pg_url, lambda c: c.execute(text(f"DROP ROLE {name}")))


def test_a_recovery_login_may_connect_and_use_its_schema_only(pg_url: str, login: str) -> None:
    rights = autocommitted(pg_url, lambda c: effective(c, login))
    # Gate A's allow-list, exactly, and its two named exceptions (revision 6)
    assert rights - UNTRUSTED == {("database", "<current>", "CONNECT"), ("schema", "recovery", "USAGE"),
                                  *(("function:f", f, "EXECUTE") for f in RECOVERY_FUNCTIONS)}  # fmt: skip
    assert rights & UNTRUSTED == UNTRUSTED
    assert not [r for r in rights if r[2] == "CREATE"]  # no schema, no database


def test_a_recovery_login_is_a_member_of_dewpoint_recovery_alone(pg_url: str, login: str) -> None:
    def memberships(c: Connection) -> set[str]:
        rows = c.execute(text("SELECT r.rolname FROM pg_auth_members a JOIN pg_roles r ON r.oid = a.roleid "
                              "JOIN pg_roles m ON m.oid = a.member WHERE m.rolname = :m"), {"m": login})  # fmt: skip
        return set(rows.scalars())

    assert autocommitted(pg_url, memberships) == {"dewpoint_recovery"}


def test_public_holds_no_function_no_schema_public_and_no_temporary(pg_url: str) -> None:
    name = f"rcv_probe_{uuid.uuid4().hex[:12]}"  # a role with no memberships: what PUBLIC holds

    def probe(c: Connection) -> set[tuple[str, str, str]]:
        c.execute(text(f"CREATE ROLE {name} NOLOGIN"))
        try:
            return effective(c, name)
        finally:
            c.execute(text(f"DROP ROLE {name}"))

    assert autocommitted(pg_url, probe) == {("database", "<current>", "CONNECT"), *UNTRUSTED}


def test_each_service_role_executes_exactly_its_granted_functions(pg_url: str) -> None:
    rights = autocommitted(pg_url, lambda c: {r: effective(c, r) for r in SERVICE_ROLES})
    for function, roles in GRANTED.items():
        assert holders(rights, function) == roles, function
    assert ("schema", "public", "USAGE") in rights["dewpoint_start_check"]


ATTEMPTS = {  # what a recovery login might try to create: each refused, and why
    "CREATE FUNCTION recovery.f() RETURNS integer LANGUAGE sql AS 'SELECT 1'": "permission denied for schema recovery",
    "CREATE TABLE recovery.t (i integer)": "permission denied for schema recovery",
    "CREATE FUNCTION public.f() RETURNS integer LANGUAGE sql AS 'SELECT 1'": "permission denied for schema public",
    "CREATE TEMPORARY TABLE t (i integer)": "permission denied to create temporary tables",
    "DO $$ BEGIN END $$": "permission denied for language plpgsql",
    "DO LANGUAGE c $$ $$": "permission denied for language c",
    "DO LANGUAGE internal $$ $$": "permission denied for language internal",
}


@pytest.mark.parametrize("attempt", ATTEMPTS)
async def test_a_recovery_login_creates_nothing(pg_url: str, login: str, attempt: str) -> None:
    c = await asyncpg.connect(pg_url.replace("postgresql+asyncpg://", "postgresql://", 1))
    try:
        with pytest.raises(asyncpg.InsufficientPrivilegeError, match=ATTEMPTS[attempt]):
            async with c.transaction():
                await c.execute(f"SET LOCAL ROLE {login}")
                await c.execute(attempt)
    finally:
        await c.close()
