# SPDX-License-Identifier: Apache-2.0
"""Confirmations (2b-4b M4 recovery, task 6; design revision 6 §3, plan ruling 4). The leader carries out a command only
once the same person confirmed it through their recovery login, a channel the API's processes don't hold: a confirmation
of the command's digest, by the login mapped (unrevoked) to its actor. The digest is computed in the database alone,
over one canonical text, which `recovery.operator_command_show` gives that login exactly; the leader recomputes it, so a
command changed since, or a mapping revoked since, is refused `unconfirmed`. A command no one confirmed stays pending
for its operator, never picked."""

import hashlib
import json
import uuid
from datetime import UTC
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.apps.dispatcher import commands
from dewpoint.core.audit.service import verify_chain
from dewpoint.core.db import tenant_scope
from tests.apps.dispatcher.test_commands import (
    GONE,
    ITEMS,
    REASONS,
    asked,
    count,
    decided,
    ended,
    lost_run,
    operator,
)
from tests.core.retention.support import tenant
from tests.migrations.state_0053 import SERVICE_ROLES, effective, holders
from tests.migrations.support import autocommitted
from tests.support.recovery import confirm, confirmed_by_actor, login_of, mapped_login, revoked, shown

pytestmark = pytest.mark.usefixtures("development_deployment")
CONFIRMATIONS = "select count(*) from operator_confirmations where command_id = :i"


async def _confirmed_audit(owner: Any, command: uuid.UUID) -> list[tuple[Any, ...]]:
    async with owner() as s:
        found = await s.execute(text("select tenant_id, actor_id, details->>'login', details->>'digest' from audit_log "
                                     "where action = 'operator.command.confirmed' and target_id = :c order by seq"),
                                {"c": str(command)})  # fmt: skip
        return [tuple(r) for r in found]


# --- the leader ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ITEMS)
async def test_an_unconfirmed_command_is_never_carried_out_and_waits_for_its_operator(
    owner_sessionmaker, dispatch_sessionmaker, kind: str
) -> None:
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, kind, admin, confirmed=False)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {}
    assert await decided(owner_sessionmaker, command) == ("pending", None, False)  # never picked, never refused
    assert await count(owner_sessionmaker, REASONS, item) == 1  # its item as it was
    await confirmed_by_actor(owner_sessionmaker, command, admin)  # confirmed later: carried out then
    assert sum((await commands.commands_once(dispatch_sessionmaker, GONE)).values()) == 1
    assert (await decided(owner_sessionmaker, command))[0] == "applied"


async def test_a_command_the_api_records_under_an_admins_id_is_never_carried_out(
    owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
) -> None:
    """The M3 gap: a holder of the API's credentials records a command naming any admin. Never confirmed by that
    admin, it's never carried out, and the API can confirm nothing."""
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item = await lost_run(owner_sessionmaker, ctx)  # its reason recorded, no command on it yet
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("insert into recovery_items (tenant_id, reason, item_id) "
                             "values (:t, 'run_history_missing', :i)"), {"t": ctx["t"], "i": item})  # fmt: skip
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, ctx["t"])
        forged = (await s.execute(text(
            "insert into operator_commands (tenant_id, kind, item_id, reason, incident_since, actor_id, "
            "idempotency_key, evidence) select :t, 'record_lost_run', :i, reason, since, :u, 'forged', 'none' "
            "from recovery_items where item_id = :i returning id"),
            {"t": ctx["t"], "i": item, "u": admin})).scalar_one()  # fmt: skip
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {}
    assert await decided(owner_sessionmaker, forged) == ("pending", None, False)
    assert (await ended(owner_sessionmaker, item))[0] == "running"
    async with api_sessionmaker() as s:
        await s.begin()
        with pytest.raises(DBAPIError, match="permission denied"):
            await s.execute(
                text(
                    "insert into operator_confirmations (command_id, login, user_id, digest, "
                    "confirmed_at) values (:c, 'rcv_x', :u, '\\x00', now())"
                ),
                {"c": forged, "u": admin},
            )
        await s.rollback()


async def test_a_confirmation_whose_login_is_revoked_before_it_runs_is_refused_unconfirmed(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, "record_lost_run", admin)
    await revoked(owner_sessionmaker, await login_of(owner_sessionmaker, admin))
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.UNCONFIRMED: 1}
    assert await decided(owner_sessionmaker, command) == ("refused", commands.UNCONFIRMED, True)
    assert (await ended(owner_sessionmaker, item))[0] == "running"


async def test_a_command_changed_after_its_confirmation_is_refused_unconfirmed(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """The leader recomputes the digest: the confirmation binds the content shown, not the command's id."""
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, "record_lost_run", admin)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update operator_commands set evidence = 'other evidence' where id = :c"), {"c": command})
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.UNCONFIRMED: 1}
    assert await decided(owner_sessionmaker, command) == ("refused", commands.UNCONFIRMED, True)
    assert (await ended(owner_sessionmaker, item))[0] == "running"


async def test_a_command_left_unconfirmed_an_hour_is_refused_and_its_item_may_be_asked_again(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """A pending command holds its item (one pending command an item and kind): one its operator never confirms, a
    forged one among them, is refused `unconfirmed` once its hour has passed, never confirmed late."""
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, "record_lost_run", admin, confirmed=False)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update operator_commands set requested_at = now() - interval '1 hour 1 second' "
                             "where id = :c"), {"c": command})  # fmt: skip
    with pytest.raises(DBAPIError, match="hour to be confirmed has passed"):
        await confirm(owner_sessionmaker, await mapped_login(owner_sessionmaker, admin), command)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.UNCONFIRMED: 1}
    assert await decided(owner_sessionmaker, command) == ("refused", commands.UNCONFIRMED, True)
    _, again = await asked(owner_sessionmaker, ctx, "record_lost_run", admin, item=item)  # asked again, confirmed
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.HISTORY_LOST: 1}
    assert (await decided(owner_sessionmaker, again))[0] == "applied"


# --- the confirmation ------------------------------------------------------------------------------------------------


async def _pending(owner: Any) -> tuple[uuid.UUID, uuid.UUID]:
    """An unconfirmed command, and its actor."""
    ctx, admin = await tenant(owner), await operator(owner)
    _, command = await asked(owner, ctx, "record_lost_run", admin, confirmed=False)
    return command, admin


async def test_another_persons_login_confirms_nothing(owner_sessionmaker) -> None:
    command, admin = await _pending(owner_sessionmaker)
    _, digest = await shown(owner_sessionmaker, await mapped_login(owner_sessionmaker, admin), command)
    theirs = await mapped_login(owner_sessionmaker, await operator(owner_sessionmaker))
    with pytest.raises(DBAPIError, match="not the command's operator"):
        await confirm(owner_sessionmaker, theirs, command, digest)
    assert await count(owner_sessionmaker, CONFIRMATIONS, command) == 0
    assert await _confirmed_audit(owner_sessionmaker, command) == []


async def test_a_digest_other_than_the_commands_confirms_nothing(owner_sessionmaker) -> None:
    command, admin = await _pending(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="changed since it was shown"):
        await confirm(owner_sessionmaker, await mapped_login(owner_sessionmaker, admin), command, bytes(32))
    assert await count(owner_sessionmaker, CONFIRMATIONS, command) == 0


async def test_a_revoked_login_confirms_nothing(owner_sessionmaker) -> None:
    command, admin = await _pending(owner_sessionmaker)
    login = await mapped_login(owner_sessionmaker, admin)
    _, digest = await shown(owner_sessionmaker, login, command)
    await revoked(owner_sessionmaker, login)
    with pytest.raises(DBAPIError, match="not the command's operator"):
        await confirm(owner_sessionmaker, login, command, digest)
    assert await count(owner_sessionmaker, CONFIRMATIONS, command) == 0


async def test_a_command_is_confirmed_once_and_only_while_pending(owner_sessionmaker, dispatch_sessionmaker) -> None:
    command, admin = await _pending(owner_sessionmaker)
    login = await confirmed_by_actor(owner_sessionmaker, command, admin)
    with pytest.raises(DBAPIError, match="already confirmed"):
        await confirm(owner_sessionmaker, await mapped_login(owner_sessionmaker, admin), command)
    assert await count(owner_sessionmaker, CONFIRMATIONS, command) == 1
    async with owner_sessionmaker() as s, s.begin():  # decided meanwhile, as the leader would
        await s.execute(text("delete from operator_confirmations where command_id = :c"), {"c": command})
        await s.execute(text("update operator_commands set status = 'refused', outcome = 'stale', "
                             "decided_at = now() where id = :c"), {"c": command})  # fmt: skip
    with pytest.raises(DBAPIError, match="no pending command"):
        await confirm(owner_sessionmaker, login, command)


async def test_a_confirmation_is_audited_in_its_tenants_scope_naming_the_login(owner_sessionmaker) -> None:
    command, admin = await _pending(owner_sessionmaker)
    login = await mapped_login(owner_sessionmaker, admin)
    _, digest = await shown(owner_sessionmaker, login, command)
    await confirm(owner_sessionmaker, login, command, digest)
    async with owner_sessionmaker() as s:
        tenant_id = (await s.execute(text("select tenant_id from operator_commands where id = :c"),
                                     {"c": command})).scalar_one()  # fmt: skip
        recorded = (await s.execute(text("select login, user_id, digest from operator_confirmations "
                                         "where command_id = :c"), {"c": command})).one()  # fmt: skip
        assert (await verify_chain(s, str(tenant_id))).ok
    assert tuple(recorded) == (login, admin, digest)
    assert await _confirmed_audit(owner_sessionmaker, command) == [(tenant_id, admin, login, digest.hex())]


# --- what's shown and digested (plan ruling 4) -----------------------------------------------------------------------


async def test_the_text_shown_is_the_text_digested_and_the_leader_recomputes_that_digest(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    command, admin = await _pending(owner_sessionmaker)
    canonical, digest = await shown(owner_sessionmaker, await mapped_login(owner_sessionmaker, admin), command)
    assert hashlib.sha256(canonical.encode()).digest() == digest
    async with dispatch_sessionmaker() as s:
        leader = (await s.execute(text("select operator_command_digest(:c)"), {"c": command})).scalar_one()
    assert bytes(leader) == digest


async def test_the_canonical_text_labels_each_field_quotes_text_and_writes_its_time_in_utc(owner_sessionmaker) -> None:
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    evidence = 'line one\nline "two" é'
    item, command = await asked(owner_sessionmaker, ctx, "settle_ended", admin, evidence=evidence, confirmed=False)
    async with owner_sessionmaker() as s:
        row = (await s.execute(text("select incident_since, idempotency_key from operator_commands where id = :c"),
                               {"c": command})).one()  # fmt: skip
    since = row.incident_since.astimezone(UTC)
    expected = "\n".join([
        "format: dewpoint-operator-command/1",
        f"id: {command}",
        'kind: "settle_ended"',
        f"tenant: {ctx['t']}",
        f"item: {item}",
        'reason: "start_after_end"',
        f"incident_since: {since:%Y-%m-%dT%H:%M:%S.%f}Z",
        f"evidence: {json.dumps(evidence, ensure_ascii=False)}",
        f"actor: {admin}",
        f"idempotency_key: {json.dumps(row.idempotency_key)}",
    ])  # fmt: skip
    canonical, _ = await shown(owner_sessionmaker, await mapped_login(owner_sessionmaker, admin), command)
    assert canonical == expected
    async with owner_sessionmaker() as s, s.begin():  # whatever the session's time zone
        await s.execute(text("set local timezone = 'Pacific/Chatham'"))
        assert (await s.execute(text("select operator_command_canonical(:c)"), {"c": command})).scalar_one() == expected


async def test_only_the_actors_mapped_unrevoked_login_is_shown_a_command(owner_sessionmaker) -> None:
    command, admin = await _pending(owner_sessionmaker)
    theirs = await mapped_login(owner_sessionmaker, await operator(owner_sessionmaker))
    mine = await mapped_login(owner_sessionmaker, admin)
    await revoked(owner_sessionmaker, mine)
    for login in (theirs, mine):
        with pytest.raises(DBAPIError, match="not the command's operator"):
            await shown(owner_sessionmaker, login, command)


# --- privileges ------------------------------------------------------------------------------------------------------

FUNCTIONS = {  # each function's executors among the service roles (the recovery group's own aside)
    "public.operator_command_canonical(command_id uuid)": set(),
    "public.operator_command_digest(command_id uuid)": {"dewpoint_dispatch"},
    "recovery.operator_command_show(command_id uuid)": set(),
    "recovery.operator_command_confirm(command_id uuid, digest bytea)": set(),
}
TABLES = ("recovery_operators", "operator_confirmations")
PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def test_the_digest_is_the_leaders_alone_and_the_confirmation_the_recovery_groups(pg_url: str) -> None:
    rights = autocommitted(pg_url, lambda c: {r: effective(c, r) for r in (*SERVICE_ROLES, "dewpoint_recovery")})
    for function, roles in FUNCTIONS.items():
        assert holders({r: rights[r] for r in SERVICE_ROLES}, function) == roles, function
    assert holders(rights, "recovery.operator_command_show") == {"dewpoint_recovery"}
    assert holders(rights, "recovery.operator_command_confirm") == {"dewpoint_recovery"}


def test_no_service_role_writes_either_table_the_leader_reads_both_and_the_monitor_the_mappings(pg_url: str) -> None:
    def held(c: Any) -> set[tuple[str, str, str]]:
        found = c.execute(
            text(
                "select r, t, p from unnest(cast(:r as text[])) r, unnest(cast(:t as text[])) t, "
                "unnest(cast(:p as text[])) p where has_table_privilege(r, t, p)"
            ),
            {"r": [*SERVICE_ROLES, "dewpoint_recovery"], "t": list(TABLES), "p": list(PRIVILEGES)},
        )
        return {tuple(row) for row in found}  # type: ignore[misc]

    leader = {("dewpoint_dispatch", t, "SELECT") for t in TABLES}
    assert autocommitted(pg_url, held) == {*leader, ("dewpoint_auditor", "recovery_operators", "SELECT")}  # task 7


async def test_the_api_role_runs_neither_function(api_sessionmaker: Any) -> None:
    for statement in ("select recovery.operator_command_confirm(gen_random_uuid(), '\\x00')",
                      "select operator_command_digest(gen_random_uuid())"):  # fmt: skip
        async with api_sessionmaker() as s:
            await s.begin()
            with pytest.raises(DBAPIError, match="permission denied"):
                await s.execute(text(statement))
            await s.rollback()
