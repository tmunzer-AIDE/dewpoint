# SPDX-License-Identifier: Apache-2.0
"""Unresolved sends, counted for a platform admin (2b-4b M4 recovery, task 9; design revision 5 §4, revision 6 §2). The
API shows counts alone: `unresolved_sends_counts(token)` checks the caller's session itself (`admin_session`: its raw
token's digest, unrevoked, unexpired, `active`, with a second factor, of an active platform admin) and returns no
identifier. Identifiers go only through an audited reveal, under an operator's own recovery login
(`test_recovery_reveal.py`), on an `inspect_unresolved_send` command the API records like any other."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.auth.sessions import create_session
from dewpoint.core.auth.users import create_user
from tests.apps.api.test_erasure_api import admin_of, tenant_of
from tests.apps.api.test_recovery_api import url

COUNTS = "select * from unresolved_sends_counts(:token)"


async def _session(owner: Any, settings: Any, *, admin: bool = True, active: bool = True, state: str = "active",
                   methods: tuple[str, ...] = ("password", "totp"), revoked: bool = False,
                   expired: bool = False) -> str:  # fmt: skip
    """A session of a new user, as asked: its raw token."""
    async with owner() as s, s.begin():
        user = await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42",
                                 platform_admin=admin)  # fmt: skip
        sess, token = await create_session(s, user_id=user.id, state=state, methods=list(methods), settings=settings,
                                           ip=None, user_agent=None)  # fmt: skip
        await s.execute(text("update users set is_active = :a where id = :u"), {"a": active, "u": user.id})
        await s.execute(text("update sessions set revoked_at = case when :r then now() end, "
                             "expires_at = case when :e then now() - interval '1 second' else expires_at end "
                             "where id = :i"), {"r": revoked, "e": expired, "i": sess.id})  # fmt: skip
    return str(token)


async def _blockers(owner: Any) -> list[uuid.UUID]:
    """Blockers in each state, sends open and answered, under two tenants."""
    async with owner() as s, s.begin():
        tenants = [(await s.execute(text("insert into tenants (id, name, slug) values (gen_random_uuid(), 'T', "
                                         ":s) returning id"), {"s": uuid.uuid4().hex[:12]})).scalar_one()
                   for _ in range(2)]  # fmt: skip
        made = []
        for n, (state, open_sends) in enumerate((("pending", 1), ("unresolved", 2), ("unresolved", 0),
                                                 ("identified", 0), ("deleted_open", 1))):  # fmt: skip
            request = uuid.uuid4()
            await s.execute(text("insert into unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, "
                                 "state, identified_run_id, first_at) values (:r, :t, :w, gen_random_uuid(), :s, "
                                 "case when :s in ('identified', 'deleted_open') then 'run' end, "
                                 "now() - make_interval(hours => :h))"),
                            {"r": request, "t": tenants[n % 2], "w": f"t:{tenants[n % 2]}:run:{request}", "s": state,
                             "h": 10 - n})  # fmt: skip
            await s.execute(
                text(
                    "insert into start_sends (request_id, attempt, answer, answered_at) "
                    "values (:r, 1, 'refused', now())"
                ),
                {"r": request},
            )  # one answered
            for attempt in range(2, open_sends + 2):  # then `open_sends` open
                await s.execute(text("insert into start_sends (request_id, attempt) values (:r, :a)"),
                                {"r": request, "a": attempt})  # fmt: skip
            made.append(request)
    return made


async def test_an_admins_session_reads_counts_alone(owner_sessionmaker, api_sessionmaker, api_settings) -> None:
    await _blockers(owner_sessionmaker)
    token = await _session(owner_sessionmaker, api_settings)
    async with api_sessionmaker() as s:
        found = (await s.execute(text(COUNTS), {"token": token})).mappings().all()
    assert set(found[0].keys()) == {"state", "requests", "open_sends", "oldest"}  # no identifier
    by = {r["state"]: (r["requests"], r["open_sends"]) for r in found}
    assert by == {"pending": (1, 1), "unresolved": (2, 2), "identified": (1, 0), "deleted_open": (1, 1),
                  "erasures_held": (0, None)}  # fmt: skip


SESSIONS = {  # each way a token falls short
    "a member's": {"admin": False},
    "revoked": {"revoked": True},
    "expired": {"expired": True},
    "awaiting its second factor": {"state": "mfa_pending"},
    "without a second factor": {"methods": ("password",)},
    "an inactive user's": {"active": False},
}


@pytest.mark.parametrize("case", [*SESSIONS, "no token", "a made-up token"])
async def test_the_counts_refuse_any_token_but_a_live_admin_session_with_its_second_factor(
    owner_sessionmaker, api_sessionmaker, api_settings, case: str
) -> None:
    token = {"no token": None, "a made-up token": "x" * 43}.get(case)
    if case in SESSIONS:
        token = await _session(owner_sessionmaker, api_settings, **SESSIONS[case])
    async with api_sessionmaker() as s:
        await s.begin()
        with pytest.raises(DBAPIError, match="insufficient_privilege|not a platform admin's session"):
            await s.execute(text(COUNTS), {"token": token})
        await s.rollback()


async def test_the_api_role_checks_no_session_itself_nor_reads_the_store(api_sessionmaker) -> None:
    for statement in ("select admin_session('x')", "select count(*) from unresolved_sends",
                      "select * from recovery.unresolved_send_reveal(gen_random_uuid())"):  # fmt: skip
        async with api_sessionmaker() as s:
            await s.begin()
            with pytest.raises(DBAPIError, match="permission denied"):
                await s.execute(text(statement))
            await s.rollback()


async def test_the_counts_route_answers_an_admin_and_refuses_a_member(app, owner_sessionmaker, api_settings) -> None:
    await _blockers(owner_sessionmaker)
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    from tests.apps.api.helpers import session_client

    member, _ = await session_client(app, owner_sessionmaker, api_settings, "owner")
    async with admin, member:
        counted = await admin.get("/api/v1/admin/recovery/unresolved-sends/counts")
        assert counted.status_code == 200, counted.json()
        states = {r["state"]: r["requests"] for r in counted.json()["states"]}
        assert states["unresolved"] == 2 and states["erasures_held"] == 0
        assert (await member.get("/api/v1/admin/recovery/unresolved-sends/counts")).status_code == 403


async def test_an_erasure_of_a_tenant_with_a_blocker_is_counted_held(
    owner_sessionmaker, api_sessionmaker, api_settings
) -> None:
    """Until the erasure holds for them itself (phase D): an incomplete erasure of a tenant a blocker names."""
    [first, *_] = await _blockers(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        tenant = (await s.execute(text("select tenant_id from unresolved_sends where request_id = :r"),
                                  {"r": first})).scalar_one()  # fmt: skip
        await s.execute(text("insert into tenant_erasures (tenant_id, requested_by) values (:t, gen_random_uuid())"),
                        {"t": tenant})  # fmt: skip
    token = await _session(owner_sessionmaker, api_settings)
    async with api_sessionmaker() as s:
        found = {r["state"]: r["requests"] for r in (await s.execute(text(COUNTS), {"token": token})).mappings()}
    assert found["erasures_held"] == 1


async def test_an_inspect_command_is_recorded_for_its_operator_and_never_carried_out_by_the_leader(
    app, owner_sessionmaker, api_settings, dispatch_sessionmaker
) -> None:
    """The reveal's own command (plan ruling 6): the API records it, pending, naming the request; the leader never
    carries it out (the reveal does); left past its hour, the leader refuses it `expired`, freeing the request."""
    from dewpoint.apps.dispatcher import commands
    from tests.apps.dispatcher.test_commands import GONE
    from tests.support.recovery import confirmed_by_actor

    admin, admin_id = await admin_of(app, owner_sessionmaker, api_settings)
    tenant, _ = await tenant_of(app, owner_sessionmaker, api_settings)
    request = uuid.uuid4()
    asked = {"kind": "inspect_unresolved_send", "item_id": str(request), "idempotency_key": "inspect-1"}
    async with admin:
        made = await admin.post(url(tenant, "commands"), json=asked)
        assert made.status_code == 202, made.json()
        assert (made.json()["kind"], made.json()["item_id"], made.json()["reason"]) == (
            "inspect_unresolved_send", str(request), None)  # fmt: skip
    command = uuid.UUID(made.json()["id"])
    await confirmed_by_actor(owner_sessionmaker, command, admin_id)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {}  # never the leader's
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update operator_commands set requested_at = :t where id = :c"),
                        {"t": datetime.now(UTC) - timedelta(hours=1, seconds=1), "c": command})  # fmt: skip
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.EXPIRED: 1}
