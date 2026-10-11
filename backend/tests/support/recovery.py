# SPDX-License-Identifier: Apache-2.0
"""Recovery logins in tests (2b-4b M4 recovery, task 6): a personal login, a member of `dewpoint_recovery`, mapped to a
platform user in `recovery_operators`, made as the database administrator makes one (task 7's CLI), and dropped after
each test by its prefix (`tests/conftest.py::clean_db`). A login acts as itself: its calls run under `SET LOCAL SESSION
AUTHORIZATION`, so `session_user` is the login, as when it signs in."""

import uuid
from typing import Any

from sqlalchemy import text

PREFIX = "rcv_t_"  # `clean_db` drops every role it begins
PASSWORD = "violet-otter-42"


async def mapped_login(owner: Any, user_id: uuid.UUID) -> str:
    """A new login mapped to `user_id`, unrevoked."""
    login = f"{PREFIX}{uuid.uuid4().hex[:12]}"
    async with owner() as s, s.begin():
        await s.execute(text(f"CREATE ROLE {login} LOGIN PASSWORD '{PASSWORD}' IN ROLE dewpoint_recovery"))
        await s.execute(text("insert into recovery_operators (login, user_id, provisioned_by, provisioned_at) "
                             "values (:l, :u, 'tests', now())"), {"l": login, "u": user_id})  # fmt: skip
    return login


async def login_of(owner: Any, user_id: uuid.UUID) -> str:
    """`user_id`'s unrevoked login, made if it has none."""
    async with owner() as s:
        found = (await s.execute(text("select login from recovery_operators where user_id = :u and revoked_at is null "
                                      "order by provisioned_at limit 1"), {"u": user_id})).scalar()  # fmt: skip
    return found or await mapped_login(owner, user_id)


async def revoked(owner: Any, login: str) -> None:
    """The mapping revoked, as task 7's `operator revoke` records it (the role itself is task 7's)."""
    async with owner() as s, s.begin():
        await s.execute(text("update recovery_operators set revoked_at = now(), revoked_by = 'tests' where login = :l"),
                        {"l": login})  # fmt: skip


async def as_login(owner: Any, login: str, statement: str, **values: Any) -> list[Any]:
    """`statement` run by `login` itself, in a transaction of its own: its rows."""
    async with owner() as s, s.begin():
        await s.execute(text(f"SET LOCAL SESSION AUTHORIZATION {login}"))
        return list((await s.execute(text(statement), values)).all())


async def shown(owner: Any, login: str, command_id: uuid.UUID) -> tuple[str, bytes]:
    """What `recovery.operator_command_show` gives `login`: the canonical text, and its digest."""
    [row] = await as_login(owner, login, "select canonical, digest from recovery.operator_command_show(:c)",
                           c=command_id)  # fmt: skip
    return row.canonical, bytes(row.digest)


async def confirm(owner: Any, login: str, command_id: uuid.UUID, digest: bytes | None = None) -> None:
    """`login` confirms the command, with the digest it was shown (or `digest`)."""
    if digest is None:
        _, digest = await shown(owner, login, command_id)
    await as_login(owner, login, "select recovery.operator_command_confirm(:c, :d)", c=command_id, d=digest)


async def confirmed_by_actor(owner: Any, command_id: uuid.UUID, actor: uuid.UUID) -> str:
    """The command confirmed by its actor's login (made if need be): that login."""
    login = await login_of(owner, actor)
    await confirm(owner, login, command_id)
    return login
