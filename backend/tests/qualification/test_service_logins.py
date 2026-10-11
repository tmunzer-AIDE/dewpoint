# SPDX-License-Identifier: Apache-2.0
"""The services' logins, each checked against its intended role on a real database (the owner's final-gate ruling): a
member of that one service role alone, no attribute beyond LOGIN, and exactly the role's rights: a grant made to the
login directly is drift the group roles' reference never shows."""

import uuid
from collections.abc import AsyncIterator

import asyncpg  # type: ignore[import-untyped]  # it ships no type information
import pytest

from tests.migrations.state_0053 import SERVICE_ROLES
from tests.qualification import privileges


@pytest.fixture
async def conn(pg_url: str) -> AsyncIterator[asyncpg.Connection]:
    c = await asyncpg.connect(pg_url.replace("postgresql+asyncpg://", "postgresql://"))
    yield c
    await c.close()


@pytest.fixture
async def login(conn: asyncpg.Connection) -> AsyncIterator[str]:
    name = f"q_api_login_{uuid.uuid4().hex[:10]}"
    await conn.execute(f"CREATE ROLE {name} LOGIN IN ROLE dewpoint_api")
    yield name
    await conn.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {name}")
    await conn.execute(f"DROP ROLE {name}")


async def test_a_login_holding_exactly_its_roles_rights_is_clean(conn: asyncpg.Connection, login: str) -> None:
    assert await privileges.login_problems(conn, login, "dewpoint_api") == []


async def test_a_direct_grant_to_a_services_login_is_drift(conn: asyncpg.Connection, login: str) -> None:
    await conn.execute(f"GRANT INSERT ON operator_confirmations TO {login}")
    problems = await privileges.login_problems(conn, login, "dewpoint_api")
    assert any("operator_confirmations" in p and "INSERT" in p for p in problems), problems


async def test_a_second_membership_or_an_attribute_is_drift(conn: asyncpg.Connection, login: str) -> None:
    await conn.execute(f"GRANT dewpoint_admin TO {login}")
    await conn.execute(f"ALTER ROLE {login} CREATEROLE")
    problems = await privileges.login_problems(conn, login, "dewpoint_api")
    assert any("dewpoint_admin" in p for p in problems) and any("CREATEROLE" in p for p in problems), problems


async def test_every_login_of_a_service_role_is_found(conn: asyncpg.Connection, login: str) -> None:
    found = await privileges.service_logins(conn)
    assert found[login] == {"dewpoint_api"}


@pytest.fixture
async def worker_login(conn: asyncpg.Connection) -> AsyncIterator[str]:
    name = f"q_worker_login_{uuid.uuid4().hex[:10]}"
    await conn.execute(f"CREATE ROLE {name} LOGIN IN ROLE dewpoint_worker")
    yield name
    await conn.execute(f"DROP ROLE {name}")


async def test_an_expected_login_that_lost_its_membership_is_found_while_others_remain(
    conn: asyncpg.Connection, login: str, worker_login: str
) -> None:
    """The owner's final-gate ruling: discovery through membership alone would never see it."""
    inventory = {login: "dewpoint_api", worker_login: "dewpoint_worker"}
    await conn.execute(f"REVOKE dewpoint_api FROM {login}")
    found = await privileges.check_logins(conn, inventory)
    assert any("not a member of dewpoint_api" in p for p in found[login]), found
    assert found[worker_login] == []


async def test_an_expected_login_that_doesnt_exist_fails(conn: asyncpg.Connection) -> None:
    found = await privileges.check_logins(conn, {"q_never_made_login": "dewpoint_api"})
    assert found == {"q_never_made_login": ["q_never_made_login: no such login"]}


def test_the_inventory_names_a_login_for_every_service_role_and_every_login_found() -> None:
    complete = {f"{role}_login": role for role in SERVICE_ROLES}
    assert privileges.inventory_problems(complete, {"dewpoint_api_login": {"dewpoint_api"}}) == []
    without = {k: v for k, v in complete.items() if v != "dewpoint_start_check"}  # the start check's login left out
    assert any("dewpoint_start_check" in p for p in privileges.inventory_problems(without, {}))
    stray = {"someone_else_login": {"dewpoint_api"}}  # a login of a service role the inventory doesn't name
    assert any("someone_else_login" in p for p in privileges.inventory_problems(complete, stray))
    assert any("not a service role" in p for p in privileges.inventory_problems({**complete, "x": "postgres"}, {}))
