# SPDX-License-Identifier: Apache-2.0
"""The reveal (2b-4b M4 recovery, task 9; design revision 6 §2, the plan's ruling 6). An unresolved send's identifiers
go to an operator only through `recovery.unresolved_send_reveal(command)`, under their own recovery login, on a pending
`inspect_unresolved_send` command naming one blocker. Before returning anything it checks the command is confirmed, its
digest still the confirmed one, and the caller the confirming login, still mapped to its actor and unrevoked; then it
writes its audit entry, in the same transaction (if that fails, nothing is returned), returns each send of that blocker
and marks the command applied. `dewpoint recovery reveal` prints them."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from cryptography.hazmat.primitives import serialization
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from typer.testing import CliRunner

from dewpoint.apps.cli import recovery
from dewpoint.apps.cli.main import app
from dewpoint.core.db import make_engine, make_sessionmaker
from tests.apps.cli.test_recovery_confirm import _authority, _dsn
from tests.apps.dispatcher.test_commands import operator
from tests.core.retention.support import tenant
from tests.support.recovery import PASSWORD, as_login, confirm, mapped_login, revoked

REVEAL = "select * from recovery.unresolved_send_reveal(:c)"


async def _blocker(owner: Any, tenant_id: uuid.UUID) -> uuid.UUID:
    """A blocker with an answered send and an open one."""
    request = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(text("insert into unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, "
                             "state) values (:r, :t, :w, gen_random_uuid(), 'unresolved')"),
                        {"r": request, "t": tenant_id, "w": f"t:{tenant_id}:run:{request}"})  # fmt: skip
        await s.execute(
            text(
                "insert into start_sends (request_id, attempt, answer, run_id, answered_at) "
                "values (:r, 1, 'started', 'run-1', now()), (:r, 2, null, null, null)"
            ),
            {"r": request},
        )
    return request


async def _inspect(owner: Any) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """A pending inspect command on a blocker: (command, its actor, its request, its tenant)."""
    ctx, admin = await tenant(owner), await operator(owner)
    request = await _blocker(owner, ctx["t"])
    async with owner() as s, s.begin():
        command = (await s.execute(text("insert into operator_commands (tenant_id, kind, item_id, actor_id, "
                                        "idempotency_key) values (:t, 'inspect_unresolved_send', :r, :u, :k) "
                                        "returning id"),
                                   {"t": ctx["t"], "r": request, "u": admin,
                                    "k": uuid.uuid4().hex})).scalar_one()  # fmt: skip
    return command, admin, request, ctx["t"]


async def _state(owner: Any, command: uuid.UUID) -> tuple[Any, ...]:
    async with owner() as s:
        status = (await s.execute(text("select status, outcome from operator_commands where id = :c"),
                                  {"c": command})).one()  # fmt: skip
        audited = (await s.execute(text("select count(*) from audit_log where action = "
                                        "'recovery.unresolved_send.revealed' and target_id = :c"),
                                   {"c": str(command)})).scalar_one()  # fmt: skip
    return (*status, audited)


async def test_the_confirming_login_is_shown_the_blockers_sends_audited_once(owner_sessionmaker) -> None:
    command, admin, request, tenant_id = await _inspect(owner_sessionmaker)
    login = await mapped_login(owner_sessionmaker, admin)
    await confirm(owner_sessionmaker, login, command)
    rows = await as_login(owner_sessionmaker, login, REVEAL, c=command)
    assert [(r.tenant_id, r.request_id, r.state, r.attempt, r.answer, r.run_id) for r in rows] == [
        (tenant_id, request, "unresolved", 1, "started", "run-1"),
        (tenant_id, request, "unresolved", 2, None, None),
    ]
    assert rows[0].workflow_id == f"t:{tenant_id}:run:{request}" and rows[0].start_request_id is not None
    assert await _state(owner_sessionmaker, command) == ("applied", "revealed", 1)
    with pytest.raises(DBAPIError, match="no pending inspection"):  # once
        await as_login(owner_sessionmaker, login, REVEAL, c=command)


async def _refused(owner: Any, login: str, command: uuid.UUID, why: str) -> None:
    with pytest.raises(DBAPIError, match=why):
        await as_login(owner, login, REVEAL, c=command)
    assert await _state(owner, command) == ("pending", None, 0)  # nothing returned, nothing audited


async def test_an_unconfirmed_inspection_reveals_nothing(owner_sessionmaker) -> None:
    command, admin, _, _ = await _inspect(owner_sessionmaker)
    await _refused(owner_sessionmaker, await mapped_login(owner_sessionmaker, admin), command, "not confirmed")


async def test_an_inspection_changed_since_its_confirmation_reveals_nothing(owner_sessionmaker) -> None:
    command, admin, _, _ = await _inspect(owner_sessionmaker)
    login = await mapped_login(owner_sessionmaker, admin)
    await confirm(owner_sessionmaker, login, command)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update operator_commands set evidence = 'changed' where id = :c"), {"c": command})
    await _refused(owner_sessionmaker, login, command, "not confirmed")


async def test_only_the_confirming_login_is_shown(owner_sessionmaker) -> None:
    command, admin, _, _ = await _inspect(owner_sessionmaker)
    confirming = await mapped_login(owner_sessionmaker, admin)
    await confirm(owner_sessionmaker, confirming, command)
    for login in (await mapped_login(owner_sessionmaker, admin),  # the same person's other login
                  await mapped_login(owner_sessionmaker, await operator(owner_sessionmaker))):  # fmt: skip
        await _refused(owner_sessionmaker, login, command, "not the confirming login")


async def test_a_revoked_login_is_shown_nothing(owner_sessionmaker) -> None:
    command, admin, _, _ = await _inspect(owner_sessionmaker)
    login = await mapped_login(owner_sessionmaker, admin)
    await confirm(owner_sessionmaker, login, command)
    await revoked(owner_sessionmaker, login)
    await _refused(owner_sessionmaker, login, command, "not the confirming login")


@pytest.mark.parametrize("change", ["is_platform_admin = false", "is_active = false"])
async def test_an_actor_no_longer_an_active_platform_admin_is_shown_nothing(owner_sessionmaker, change: str) -> None:
    """Demoted or deactivated between confirming and revealing, its login not yet revoked: no identifier returned, the
    command not applied (the owner's final-gate ruling; 0065), as the leader refuses every other command."""
    command, admin, _, _ = await _inspect(owner_sessionmaker)
    login = await mapped_login(owner_sessionmaker, admin)
    await confirm(owner_sessionmaker, login, command)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(f"update users set {change} where id = :u"), {"u": admin})  # noqa: S608  # fixed text
    await _refused(owner_sessionmaker, login, command, "not an active platform admin")


async def test_an_inspection_past_its_hour_reveals_nothing(owner_sessionmaker) -> None:
    command, admin, _, _ = await _inspect(owner_sessionmaker)
    login = await mapped_login(owner_sessionmaker, admin)
    await confirm(owner_sessionmaker, login, command)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update operator_commands set requested_at = :t where id = :c"),
                        {"t": datetime.now(UTC) - timedelta(hours=1, seconds=1), "c": command})  # fmt: skip
    await _refused(owner_sessionmaker, login, command, "hour")


async def test_nothing_is_returned_when_its_audit_entry_fails(owner_sessionmaker) -> None:
    command, admin, _, _ = await _inspect(owner_sessionmaker)
    login = await mapped_login(owner_sessionmaker, admin)
    await confirm(owner_sessionmaker, login, command)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(
            text(
                "create function pg_temp_refuse_audit() returns trigger language plpgsql as "
                "$$ begin raise exception 'the audit failed'; end $$"
            )
        )
        await s.execute(
            text(
                "create trigger refuse_audit before insert on audit_log for each row "
                "execute function pg_temp_refuse_audit()"
            )
        )
    try:
        await _refused(owner_sessionmaker, login, command, "the audit failed")
    finally:
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text("drop trigger refuse_audit on audit_log"))
            await s.execute(text("drop function pg_temp_refuse_audit()"))


# --- the command -----------------------------------------------------------------------------------------------------


async def _confirmed(pg_url: str) -> tuple[uuid.UUID, str]:
    engine = make_engine(pg_url)
    owner = make_sessionmaker(engine)
    try:
        command, admin, _, _ = await _inspect(owner)
        login = await mapped_login(owner, admin)
        await confirm(owner, login, command)
        return command, login
    finally:
        await engine.dispose()


def test_the_reveal_command_prints_each_send_of_the_blocker(
    pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    command, login = asyncio.run(_confirmed(pg_url))
    ca = tmp_path / "ca.pem"  # the connection is the suite's: the CA file is only checked
    ca.write_bytes(_authority("deployment CA")[0].public_bytes(serialization.Encoding.PEM))
    address = pg_url.split("@", 1)[1]

    async def connect(target: recovery.Target, password: str) -> asyncpg.Connection:
        assert target.user == login and password == PASSWORD
        return await asyncpg.connect(f"postgresql://{login}:{password}@{address}")

    monkeypatch.setattr(recovery, "connect", connect)
    result = CliRunner().invoke(app, ["recovery", "reveal", str(command), "--dsn", _dsn(5432, ca, login)],
                                input=f"{PASSWORD}\n")  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "attempt 1: started (run-1)" in result.output and "attempt 2: unanswered" in result.output
    again = CliRunner().invoke(app, ["recovery", "reveal", str(command), "--dsn", _dsn(5432, ca, login)],
                               input=f"{PASSWORD}\n")  # fmt: skip
    assert again.exit_code == 1 and "no pending inspection" in again.output
