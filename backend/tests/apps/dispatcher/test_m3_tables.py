# SPDX-License-Identifier: Apache-2.0
"""Migration 0050's tables (the owner's rulings on the 2b-4b M3 design, rev 2): `work_failures`, an item's count of
unexpected failures for one kind of work; `recovery_items`, an item a pass can't settle and why; `operator_commands`,
what an operator asked done about one. Each is its tenant's (row-level security), fenced by the erasure's insert fence
and swept at its stage 80, and goes with its item under retention.

The dispatcher reads and writes failures and recovery items, and settles commands without changing what was asked. The
retention process reads only their keys and deletes. Nothing else reaches them. A command is bounded: one pending per
item and kind, an operator's key used once per tenant, its evidence short, and decided exactly when it isn't pending."""

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


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("service", ["api", "worker", "ingress"])
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
    tenant = await a_tenant(owner_sessionmaker)
    await rows(owner_sessionmaker, tenant, uuid.uuid4(), evidence="x" * 500)
    with pytest.raises(DBAPIError, match="too long"):
        await rows(owner_sessionmaker, tenant, uuid.uuid4(), key="other", evidence="x" * 501)


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
