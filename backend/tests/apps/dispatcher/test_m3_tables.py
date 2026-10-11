# SPDX-License-Identifier: Apache-2.0
"""Migration 0050's tables (the owner's rulings on the 2b-4b M3 design, rev 2): `work_failures`, an item's count of
unexpected failures for one kind of work; `recovery_items`, an item a pass can't settle and why; `operator_commands`,
what an operator asked done about one. Each is its tenant's (row-level security), fenced by the erasure's insert fence
and swept at its stage 80, and goes with its item under retention.

The dispatcher reads and writes failures and recovery items, and settles commands without changing what was asked. The
retention process reads only their keys and deletes. The API, within its tenant, reads recovery reasons and records a
command, pending, never settling or changing one; it releases a held item only through a guarded function, for the
kind it names; it lists held items and recovery reasons across tenants only through functions returning metadata.
Nothing else reaches them. A command is bounded: one pending per item and kind, an operator's key used once per tenant,
its evidence short, and decided exactly when it isn't pending."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from dewpoint.core.db import tenant_scope
from tests.core.claims.test_service import a_tenant

TABLES = ("work_failures", "recovery_items", "operator_commands")
FAILURE = (
    "insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at) "
    "values (:t, 'dispatch', :i, 1, 'RuntimeError', now())"
)
RECOVERY = "insert into recovery_items (tenant_id, reason, item_id) values (:t, 'run_history_missing', :i)"
COMMAND = (
    "insert into operator_commands (id, tenant_id, kind, item_id, reason, incident_since, actor_id, idempotency_key, "
    "evidence) values (:c, :t, 'record_lost_run', :i, 'run_history_missing', now(), :u, :k, :e)"
)


async def rows(owner: Any, tenant: uuid.UUID, item: uuid.UUID, *, key: str = "k", evidence: str = "") -> uuid.UUID:
    """One row of each table for `item`, as the owner: the command's id."""
    command = uuid.uuid4()
    async with owner() as s, s.begin():
        for statement in (FAILURE, RECOVERY):
            await s.execute(text(statement), {"t": tenant, "i": item})
        await s.execute(text(COMMAND), {"c": command, "t": tenant, "i": item, "u": uuid.uuid4(), "k": key,
                                        "e": evidence})  # fmt: skip
    return command


@pytest.mark.parametrize("table", TABLES)
async def test_each_table_forces_row_level_security(owner_sessionmaker, table: str) -> None:
    async with owner_sessionmaker() as s:
        query = text("select relrowsecurity, relforcerowsecurity from pg_class where relname = :t")
        assert tuple((await s.execute(query, {"t": table})).one()) == (True, True)


@pytest.mark.parametrize("table", TABLES)
async def test_the_dispatcher_and_the_retention_process_see_only_their_tenants_rows(
    owner_sessionmaker, dispatch_sessionmaker, retention_sessionmaker, table: str
) -> None:  # fmt: skip
    a, b = await a_tenant(owner_sessionmaker), await a_tenant(owner_sessionmaker)
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    await rows(owner_sessionmaker, a, mine)
    await rows(owner_sessionmaker, b, theirs)
    for maker in (dispatch_sessionmaker, retention_sessionmaker):
        async with maker() as s, s.begin():
            await tenant_scope(s, a)
            assert set((await s.execute(text(f"select item_id from {table}"))).scalars()) == {mine}  # noqa: S608


@pytest.mark.parametrize("statement", [FAILURE, RECOVERY])
async def test_the_dispatcher_never_records_for_another_tenant(
    owner_sessionmaker, dispatch_sessionmaker, statement: str
) -> None:  # fmt: skip
    a, b = await a_tenant(owner_sessionmaker), await a_tenant(owner_sessionmaker)
    with pytest.raises(DBAPIError, match="row-level security"):
        async with dispatch_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(text(statement), {"t": b, "i": uuid.uuid4()})


@pytest.mark.parametrize(
    "statement",
    [
        COMMAND,
        "update operator_commands set kind = 'settle_ended' where id = :c",
        "update operator_commands set evidence = 'x' where id = :c",
        "update operator_commands set actor_id = :u where id = :c",
        "delete from operator_commands where id = :c",
    ],
)
async def test_the_dispatcher_settles_a_command_but_never_changes_what_was_asked(
    owner_sessionmaker, dispatch_sessionmaker, statement: str
) -> None:  # fmt: skip
    tenant, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    command = await rows(owner_sessionmaker, tenant, item)
    params = {"c": command, "t": tenant, "i": uuid.uuid4(), "u": uuid.uuid4(), "k": "other", "e": ""}
    with pytest.raises(DBAPIError, match="permission denied"):
        async with dispatch_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text(statement), params)
    async with dispatch_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        settled = await s.execute(text("update operator_commands set status = 'refused', outcome = 'stale', "
                                       "decided_at = now() where id = :c"), {"c": command})  # fmt: skip
        assert settled.rowcount == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("service", "table"),
    [("api", "work_failures"), *(("worker", t) for t in TABLES), *(("ingress", t) for t in TABLES)],
)
async def test_no_other_service_reaches_them(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker, ingress_sessionmaker, service: str, table: str
) -> None:  # fmt: skip
    maker = {"api": api_sessionmaker, "worker": worker_sessionmaker, "ingress": ingress_sessionmaker}[service]
    tenant = await a_tenant(owner_sessionmaker)
    await rows(owner_sessionmaker, tenant, uuid.uuid4())
    with pytest.raises(DBAPIError, match="permission denied"):
        async with maker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text(f"select 1 from {table}"))  # noqa: S608


@pytest.mark.parametrize("table", TABLES)
async def test_the_retention_process_deletes_but_never_writes(
    owner_sessionmaker, retention_sessionmaker, table: str
) -> None:  # fmt: skip
    tenant, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    await rows(owner_sessionmaker, tenant, item)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with retention_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text(f"update {table} set item_id = item_id"))  # noqa: S608
    async with retention_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        gone = await s.execute(text(f"delete from {table} where item_id = :i"), {"i": item})  # noqa: S608
        assert gone.rowcount == 1  # type: ignore[attr-defined]


async def test_an_item_has_one_pending_command_of_a_kind(owner_sessionmaker) -> None:
    tenant, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    await rows(owner_sessionmaker, tenant, item, key="first")
    with pytest.raises(IntegrityError, match="operator_commands_pending"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(COMMAND), {"c": uuid.uuid4(), "t": tenant, "i": item, "u": uuid.uuid4(),
                                            "k": "second", "e": ""})  # fmt: skip


async def test_a_decided_command_leaves_room_for_another(owner_sessionmaker) -> None:
    tenant, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    command = await rows(owner_sessionmaker, tenant, item, key="first")
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update operator_commands set status = 'refused', outcome = 'stale', decided_at = now() "
                             "where id = :c"), {"c": command})  # fmt: skip
        await s.execute(text(COMMAND), {"c": uuid.uuid4(), "t": tenant, "i": item, "u": uuid.uuid4(), "k": "second",
                                        "e": ""})  # fmt: skip


async def test_an_operators_key_is_used_once_per_tenant(owner_sessionmaker) -> None:
    tenant, actor = await a_tenant(owner_sessionmaker), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text(COMMAND), {"c": uuid.uuid4(), "t": tenant, "i": uuid.uuid4(), "u": actor, "k": "once",
                                        "e": ""})  # fmt: skip
    with pytest.raises(IntegrityError, match="operator_commands_idempotency"):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(COMMAND), {"c": uuid.uuid4(), "t": tenant, "i": uuid.uuid4(), "u": actor,
                                            "k": "once", "e": ""})  # fmt: skip


@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ("set status = 'applied'", "operator_commands_decided"),  # decided, but no time
        ("set decided_at = now()", "operator_commands_decided"),  # a time, still pending
        ("set status = 'done', decided_at = now()", "operator_commands_status"),
        ("set kind = 'anything'", "operator_commands_kind"),
        ("set reason = 'anything'", "operator_commands_reason"),
    ],
)
async def test_a_commands_shape_is_kept(owner_sessionmaker, change: str, constraint: str) -> None:
    tenant = await a_tenant(owner_sessionmaker)
    command = await rows(owner_sessionmaker, tenant, uuid.uuid4())
    with pytest.raises(IntegrityError, match=constraint):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(f"update operator_commands {change} where id = :c"), {"c": command})  # noqa: S608


async def test_a_commands_evidence_is_bounded(owner_sessionmaker) -> None:
    """4,000 characters (0059: an abandonment's evidence is structured); the API bounds the M3 kinds' at 500."""
    tenant = await a_tenant(owner_sessionmaker)
    await rows(owner_sessionmaker, tenant, uuid.uuid4(), evidence="x" * 4000)
    with pytest.raises(DBAPIError, match="too long"):
        await rows(owner_sessionmaker, tenant, uuid.uuid4(), key="other", evidence="x" * 4001)


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (FAILURE.replace("'dispatch'", "'reconcile'"), "work_failures_kind"),  # by phase only
        (FAILURE.replace(", 1, ", ", 0, "), "work_failures_errors"),
        (RECOVERY.replace("'run_history_missing'", "'anything'"), "recovery_items_reason"),
    ],
)
async def test_a_failures_and_a_recovery_items_shape_is_kept(owner_sessionmaker, statement: str,
                                                             constraint: str) -> None:  # fmt: skip
    tenant = await a_tenant(owner_sessionmaker)
    with pytest.raises(IntegrityError, match=constraint):
        async with owner_sessionmaker() as s, s.begin():
            await s.execute(text(statement), {"t": tenant, "i": uuid.uuid4()})


async def test_a_passs_resolved_items_lose_their_reasons_by_tenant_and_item(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    """One statement for a pass, as `work_failures_clear`: the named reasons of each (tenant, item) go; another
    reason, and the same item id under another tenant, stay."""
    a, b, item = await a_tenant(owner_sessionmaker), await a_tenant(owner_sessionmaker), uuid.uuid4()
    async with owner_sessionmaker() as s, s.begin():
        for tenant, reason in ((a, "run_history_missing"), (a, "start_after_end"), (a, "subrun_history_missing"),
                               (b, "run_history_missing")):  # fmt: skip
            await s.execute(text("insert into recovery_items (tenant_id, reason, item_id) values (:t, :r, :i)"),
                            {"t": tenant, "r": reason, "i": item})  # fmt: skip
    async with dispatch_sessionmaker() as s, s.begin():
        gone = await s.execute(text("select recovery_items_clear(:r, :t, :i)"),
                               {"r": ["run_history_missing", "start_after_end"], "t": [a], "i": [item]})  # fmt: skip
        assert gone.scalar_one() == 2
    async with owner_sessionmaker() as s:
        left = (await s.execute(text("select tenant_id, reason from recovery_items where item_id = :i"),
                                {"i": item})).all()  # fmt: skip
    assert sorted(left) == sorted([(a, "subrun_history_missing"), (b, "run_history_missing")])


API_COMMAND = (
    "insert into operator_commands (tenant_id, kind, item_id, reason, incident_since, actor_id, idempotency_key, "
    "evidence) values (:t, 'record_lost_run', :i, 'run_history_missing', now(), :u, :k, 'gone past retention') "
    "returning id"
)


async def test_the_api_reads_recovery_reasons_and_records_a_pending_command_within_its_tenant(
    owner_sessionmaker, api_sessionmaker
) -> None:  # fmt: skip
    a, b = await a_tenant(owner_sessionmaker), await a_tenant(owner_sessionmaker)
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    await rows(owner_sessionmaker, a, mine)
    await rows(owner_sessionmaker, b, theirs)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, a)
        assert set((await s.execute(text("select item_id from recovery_items"))).scalars()) == {mine}
        made = (await s.execute(text(API_COMMAND), {"t": a, "i": uuid.uuid4(), "u": uuid.uuid4(), "k": "new"})).one()
        found = await s.execute(text("select status from operator_commands where id = :c"), {"c": made.id})
        assert found.scalar_one() == "pending"
    with pytest.raises(DBAPIError, match="row-level security"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, a)
            await s.execute(text(API_COMMAND), {"t": b, "i": uuid.uuid4(), "u": uuid.uuid4(), "k": "other"})


@pytest.mark.parametrize(
    "statement",
    [
        "insert into operator_commands (tenant_id, kind, item_id, reason, incident_since, actor_id, idempotency_key, "
        "status, decided_at) values (:t, 'record_lost_run', :i, 'run_history_missing', now(), :u, 'k2', 'applied', "
        "now())",
        "update operator_commands set status = 'refused', outcome = 'stale', decided_at = now() where id = :c",
        "update operator_commands set evidence = 'x' where id = :c",
        "delete from operator_commands where id = :c",
        "select evidence from operator_commands where id = :c",
        "update recovery_items set since = now() where item_id = :i",
        "delete from recovery_items where item_id = :i",
    ],
)
async def test_the_api_never_settles_changes_or_removes_what_it_reads(
    owner_sessionmaker, api_sessionmaker, statement: str
) -> None:  # fmt: skip
    """Its evidence, once recorded, is the command's and its audit entry's: never read back through the table."""
    tenant, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    command = await rows(owner_sessionmaker, tenant, item)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with api_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await s.execute(text(statement), {"c": command, "t": tenant, "i": item, "u": uuid.uuid4()})


async def held(owner: Any, tenant: uuid.UUID, kind: str, item: uuid.UUID, *, hold: bool = True) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at, "
                             "held_at) values (:t, :k, :i, 7, 'RuntimeError', now(), case when :h then now() end)"),
                        {"t": tenant, "k": kind, "i": item, "h": hold})  # fmt: skip


async def test_the_api_releases_nothing_itself(owner_sessionmaker, api_sessionmaker) -> None:
    """The owner's ruling on design revision 6 (2b-4b M4 recovery, task 8): a held item's release is a command its
    operator confirms; the API's role has no release function left (0057 dropped them) and no write on the table. The
    leader's exact release never clears another kind's hold, nor another tenant's (test_release_exact.py)."""
    a, item = await a_tenant(owner_sessionmaker), uuid.uuid4()
    await held(owner_sessionmaker, a, "dispatch", item)
    for statement, refused in (
        ("select work_failure_release('dispatch', :i)", "does not exist"),
        ("select * from work_failures_release_many('dispatch', now(), 10)", "does not exist"),
        ("delete from work_failures where item_id = :i", "permission denied"),
        ("select * from work_failures_release_exact(gen_random_uuid())", "permission denied"),
    ):
        with pytest.raises(DBAPIError, match=refused):
            async with api_sessionmaker() as s, s.begin():
                await tenant_scope(s, a)
                await s.execute(text(statement), {"i": item})
    async with owner_sessionmaker() as s:
        assert (await s.execute(text("select count(*) from work_failures where item_id = :i"),
                                {"i": item})).scalar_one() == 1  # fmt: skip


async def test_the_api_lists_held_items_and_recovery_reasons_across_tenants_as_metadata(
    owner_sessionmaker, api_sessionmaker, worker_sessionmaker
) -> None:  # fmt: skip
    a, b = await a_tenant(owner_sessionmaker), await a_tenant(owner_sessionmaker)
    first, second, counting = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await held(owner_sessionmaker, a, "cancel", first)
    await held(owner_sessionmaker, b, "match", second)
    await held(owner_sessionmaker, a, "dispatch", counting, hold=False)
    await rows(owner_sessionmaker, b, second)
    async with api_sessionmaker() as s:
        listed = (await s.execute(text("select * from work_failures_held(100) where tenant_id = any(:t)"),
                                  {"t": [a, b]})).mappings().all()  # fmt: skip
        reasons = (await s.execute(text("select * from recovery_items_listed(100) where tenant_id = any(:t)"),
                                   {"t": [a, b]})).mappings().all()  # fmt: skip
    assert {(r["tenant_id"], r["kind"], r["item_id"]) for r in listed} == {(a, "cancel", first), (b, "match", second)}
    assert set(listed[0].keys()) == {"tenant_id", "kind", "item_id", "errors", "last_error", "held_at", "hold_id"}
    assert [(r["tenant_id"], r["reason"], r["item_id"]) for r in reasons] == [(b, "run_history_missing", second)]
    assert set(reasons[0].keys()) == {"tenant_id", "reason", "item_id", "since", "last_seen_at"}
    for listing in ("work_failures_held(1)", "recovery_items_listed(1)"):
        with pytest.raises(DBAPIError, match="permission denied"):
            async with worker_sessionmaker() as s:
                await s.execute(text(f"select * from {listing}"))  # noqa: S608


async def test_the_dispatcher_finds_pending_commands_and_rechecks_their_operators(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    from dewpoint.core.auth.users import create_user

    tenant = await a_tenant(owner_sessionmaker)
    older, newer, decided, waiting = [await rows(owner_sessionmaker, tenant, uuid.uuid4(), key=k)
                                      for k in ("a", "b", "c", "d")]  # fmt: skip
    async with owner_sessionmaker() as s, s.begin():
        # confirmed by their operators but `waiting`, asked within the hour: the leader picks those alone (0056)
        await s.execute(text("insert into operator_confirmations (command_id, login, user_id, digest, confirmed_at) "
                             "select id, 'rcv_t_x', actor_id, '\\x00', now() from operator_commands "
                             "where id = any(:c)"), {"c": [older, newer, decided]})  # fmt: skip
        await s.execute(text("update operator_commands set requested_at = now() - interval '1 minute' where id = :c"),
                        {"c": older})  # fmt: skip
        await s.execute(text("update operator_commands set status = 'applied', outcome = 'history_lost', "
                             "decided_at = now() where id = :c"), {"c": decided})  # fmt: skip
        admin = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42",
                                   platform_admin=True)).id  # fmt: skip
        gone = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42",
                                  platform_admin=True)).id  # fmt: skip
        member = (await create_user(s, email=f"{uuid.uuid4().hex[:10]}@corp.test", password="violet-otter-42")).id
        await s.execute(text("update users set is_active = false where id = :u"), {"u": gone})
    async with dispatch_sessionmaker() as s:
        pending = (await s.execute(text("select tenant_id, command_id from pending_commands(10) where tenant_id = :t"),
                                   {"t": tenant})).all()  # fmt: skip
        assert pending == [(tenant, older), (tenant, newer)]
        active = text("select platform_admin_active(:u)")
        assert [(await s.execute(active, {"u": u})).scalar_one() for u in (admin, gone, member, uuid.uuid4())] == [
            True, False, False, False,
        ]  # fmt: skip
