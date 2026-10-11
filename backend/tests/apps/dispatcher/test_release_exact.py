# SPDX-License-Identifier: Apache-2.0
"""Releases bound to the exact holds shown (2b-4b M4 recovery, task 8; design revisions 7 and 8 §1). A held item's
release is a command like any other, confirmed by its operator. Each hold carries a token (`work_failures.hold_id`,
from a sequence, set exactly when `held_at` is and never reused), and the command records the holds it showed
(`operator_command_holds`), once, before its confirmation; its digest covers them, sorted. The leader releases those
holds and nothing else (`work_failures_release_exact`): each still held under the same token is `released`, one
settled since is `not_held`, one held again since is `hold_changed`, and no other hold ever takes a missing one's
place."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.apps.dispatcher import commands
from tests.apps.dispatcher.test_commands import GONE, decided, operator
from tests.core.retention.support import tenant
from tests.migrations.state_0053 import SERVICE_ROLES, effective, holders
from tests.migrations.support import autocommitted
from tests.support.recovery import confirmed_by_actor, mapped_login, shown

pytestmark = pytest.mark.usefixtures("development_deployment")
FAR = datetime(2999, 1, 1, tzinfo=UTC)  # every hold held before it


async def hold(owner: Any, tenant_id: uuid.UUID, kind: str, item: uuid.UUID, *, seconds_ago: int = 60) -> int:
    """`item` held for `kind`, `seconds_ago`: its hold's token."""
    async with owner() as s, s.begin():
        return int((await s.execute(text(
            "insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at, held_at) "
            "values (:t, :k, :i, 7, 'RuntimeError', now(), now() - make_interval(secs => :ago)) returning hold_id"),
            {"t": tenant_id, "k": kind, "i": item, "ago": seconds_ago})).scalar_one())  # fmt: skip


async def settled(owner: Any, tenant_id: uuid.UUID, kind: str, item: uuid.UUID) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("delete from work_failures where tenant_id = :t and kind = :k and item_id = :i"),
                        {"t": tenant_id, "k": kind, "i": item})  # fmt: skip


async def asked_release(owner: Any, tenant_id: uuid.UUID, actor: uuid.UUID, work_kind: str, *,
                        item: uuid.UUID | None = None, held_before: datetime | None = None,
                        max_holds: int | None = None) -> tuple[uuid.UUID, list[Any]]:  # fmt: skip
    """A release command as the API records one, and the holds it showed (its snapshot): (command, holds)."""
    kind = "release_held" if item is not None else "release_held_many"
    async with owner() as s, s.begin():
        await s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
        command = (await s.execute(text(
            "insert into operator_commands (tenant_id, kind, item_id, work_kind, held_before, max_holds, actor_id, "
            "idempotency_key) values (:t, :k, :i, :w, :b, :n, :u, :key) returning id"),
            {"t": tenant_id, "k": kind, "i": item, "w": work_kind, "b": held_before, "n": max_holds, "u": actor,
             "key": uuid.uuid4().hex})).scalar_one()  # fmt: skip
        holds = (await s.execute(text("select * from operator_command_holds_snapshot(:c)"), {"c": command})).all()
    return command, list(holds)


async def held(owner: Any, tenant_id: uuid.UUID) -> dict[tuple[str, uuid.UUID], int]:
    async with owner() as s:
        found = await s.execute(text("select kind, item_id, hold_id from work_failures where tenant_id = :t "
                                     "and held_at is not null"), {"t": tenant_id})  # fmt: skip
        return {(k, i): h for k, i, h in found}


async def results(owner: Any, command: uuid.UUID) -> dict[str, list[str]]:
    """The leader's per-hold results, from its audit entries."""
    async with owner() as s:
        found = await s.execute(text("select details from audit_log where action = 'operator.command.released' "
                                     "and target_id = :c order by seq"), {"c": str(command)})  # fmt: skip
        by: dict[str, list[str]] = {}
        for details in found.scalars():
            for row in details["results"]:
                by.setdefault(row["result"], []).append(row["item_id"])
        return by


# --- the hold's token ------------------------------------------------------------------------------------------------


async def test_a_holds_token_is_set_exactly_when_it_is_held_and_never_reused(owner_sessionmaker) -> None:
    ctx = await tenant(owner_sessionmaker)
    item = uuid.uuid4()
    first = await hold(owner_sessionmaker, ctx["t"], "dispatch", item)
    async with owner_sessionmaker() as s, s.begin():
        same = await s.execute(text("update work_failures set errors = errors + 1, hold_id = 987654321 "
                                    "where item_id = :i returning hold_id"), {"i": item})  # fmt: skip
        assert same.scalar_one() == first  # the same hold: its token kept, whatever an update says
        cleared = await s.execute(text("update work_failures set held_at = null where item_id = :i returning hold_id"),
                                  {"i": item})  # fmt: skip
        assert cleared.scalar_one() is None
        again = await s.execute(text("update work_failures set held_at = now() where item_id = :i returning hold_id"),
                                {"i": item})  # fmt: skip
        recurred = again.scalar_one()
    await settled(owner_sessionmaker, ctx["t"], "dispatch", item)
    latest = await hold(owner_sessionmaker, ctx["t"], "dispatch", item)
    assert first < recurred < latest  # a hold that clears and recurs, updated or inserted again, gets a new one
    async with owner_sessionmaker() as s:
        with pytest.raises(DBAPIError, match="work_failures_held_token"):
            async with s.begin():
                await s.execute(text("alter table work_failures disable trigger work_failures_hold_id"))
                await s.execute(text("update work_failures set hold_id = null where item_id = :i"), {"i": item})


async def test_the_dispatchers_own_failure_count_holds_with_a_token(owner_sessionmaker, dispatch_sessionmaker) -> None:
    """The writer that sets `held_at` (`failures._FAILED`), as the dispatcher's role: no grant on the sequence."""
    from dewpoint.apps.dispatcher import failures
    from dewpoint.core.db import tenant_scope

    ctx, item = await tenant(owner_sessionmaker), uuid.uuid4()
    for _ in range(failures.BOUND):
        async with dispatch_sessionmaker() as s, s.begin():
            await tenant_scope(s, ctx["t"])
            await s.execute(failures._FAILED, {"t": ctx["t"], "k": "dispatch", "i": item, "e": "RuntimeError",
                                               "first": 60, "delays": [60.0] * 6, "n": 6,
                                               "bound": failures.BOUND})  # fmt: skip
    assert list(await held(owner_sessionmaker, ctx["t"])) == [("dispatch", item)]


# --- the leader's release --------------------------------------------------------------------------------------------


async def test_a_bulk_release_releases_the_confirmed_holds_alone_one_settled_meanwhile_not_held(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """The review's bulk counterexample: 1,001 holds eligible, the oldest 1,000 shown and confirmed; the first settles
    before the leader runs. 999 are released, the first is `not_held`, and item 1,001 stays held."""
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    async with owner_sessionmaker() as s, s.begin():
        items = list((await s.execute(text(
            "insert into work_failures (tenant_id, kind, item_id, errors, last_error, due_at, held_at) "
            "select :t, 'dispatch', gen_random_uuid(), 7, 'RuntimeError', now(), "
            "now() - make_interval(secs => 2000 - n) "
            "from generate_series(1, 1001) n returning item_id"), {"t": ctx["t"]})).scalars())  # fmt: skip
    command, holds = await asked_release(owner_sessionmaker, ctx["t"], admin, "dispatch",
                                         held_before=FAR, max_holds=1000)  # fmt: skip
    assert [h.item_id for h in holds] == items[:1000]  # the oldest first
    await confirmed_by_actor(owner_sessionmaker, command, admin)
    await settled(owner_sessionmaker, ctx["t"], "dispatch", items[0])
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.HOLDS_RELEASED: 1}
    assert await decided(owner_sessionmaker, command) == ("applied", commands.HOLDS_RELEASED, True)
    found = await results(owner_sessionmaker, command)
    assert (len(found["released"]), found["not_held"], found.get("hold_changed")) == (999, [str(items[0])], None)
    assert list(await held(owner_sessionmaker, ctx["t"])) == [("dispatch", items[1000])]


async def test_a_single_release_of_a_hold_that_cleared_and_recurred_is_hold_changed_the_new_hold_kept(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    """The review's single counterexample: the shown hold clears and recurs before the leader runs."""
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item = uuid.uuid4()
    await hold(owner_sessionmaker, ctx["t"], "dispatch", item)
    command, [shown_hold] = await asked_release(owner_sessionmaker, ctx["t"], admin, "dispatch", item=item)
    await confirmed_by_actor(owner_sessionmaker, command, admin)
    await settled(owner_sessionmaker, ctx["t"], "dispatch", item)
    recurred = await hold(owner_sessionmaker, ctx["t"], "dispatch", item)
    assert recurred != shown_hold.hold_id
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.HOLDS_RELEASED: 1}
    assert await results(owner_sessionmaker, command) == {"hold_changed": [str(item)]}
    assert await held(owner_sessionmaker, ctx["t"]) == {("dispatch", item): recurred}


async def test_a_release_never_clears_another_kinds_hold(owner_sessionmaker, dispatch_sessionmaker) -> None:
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item = uuid.uuid4()
    await hold(owner_sessionmaker, ctx["t"], "dispatch", item)
    cancel = await hold(owner_sessionmaker, ctx["t"], "cancel", item)
    command, _ = await asked_release(owner_sessionmaker, ctx["t"], admin, "dispatch", item=item)
    await confirmed_by_actor(owner_sessionmaker, command, admin)
    await commands.commands_once(dispatch_sessionmaker, GONE)
    assert await results(owner_sessionmaker, command) == {"released": [str(item)]}
    assert await held(owner_sessionmaker, ctx["t"]) == {("cancel", item): cancel}


async def test_a_bulk_releases_results_are_audited_in_bounded_entries(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:
    monkeypatch.setattr(commands, "AUDITED_IDS", 2)
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    items = [uuid.uuid4() for _ in range(5)]
    for n, item in enumerate(items):
        await hold(owner_sessionmaker, ctx["t"], "cancel", item, seconds_ago=600 - n)
    command, _ = await asked_release(owner_sessionmaker, ctx["t"], admin, "cancel",
                                     held_before=FAR, max_holds=4)  # fmt: skip
    await confirmed_by_actor(owner_sessionmaker, command, admin)
    await commands.commands_once(dispatch_sessionmaker, GONE)
    async with owner_sessionmaker() as s:
        found = await s.execute(text("select actor_id, details from audit_log where action = "
                                     "'operator.command.released' and target_id = :c order by seq"),
                                {"c": str(command)})  # fmt: skip
        entries = [(a, d["part"], d["parts"], [r["item_id"] for r in d["results"]]) for a, d in found]
    released = sorted(str(item) for item in items[:4])  # the four oldest, by kind and item
    assert entries == [(admin, 1, 2, released[:2]), (admin, 2, 2, released[2:])]


# --- the snapshot: shown, digested, confirmed ------------------------------------------------------------------------


async def test_the_holds_shown_are_digested_sorted_with_their_tokens(owner_sessionmaker) -> None:
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    items = sorted(uuid.uuid4() for _ in range(2))
    tokens = [await hold(owner_sessionmaker, ctx["t"], "cancel", item) for item in items]
    command, _ = await asked_release(owner_sessionmaker, ctx["t"], admin, "cancel",
                                     held_before=FAR, max_holds=10)  # fmt: skip
    canonical, _ = await shown(owner_sessionmaker, await mapped_login(owner_sessionmaker, admin), command)
    lines = canonical.splitlines()
    assert lines[1:3] == [f"id: {command}", 'kind: "release_held_many"']
    assert {'work_kind: "cancel"', "max_holds: 10", "held_before: 2999-01-01T00:00:00.000000Z"} <= set(lines)
    assert lines[-3:] == [
        "holds: 2",
        *(f'hold: {ctx["t"]} "cancel" {i} {t}' for i, t in zip(items, tokens, strict=True)),
    ]


async def test_no_hold_is_recorded_after_the_confirmation_and_one_added_anyway_fails_its_digest(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, other = uuid.uuid4(), uuid.uuid4()
    await hold(owner_sessionmaker, ctx["t"], "dispatch", item)
    token = await hold(owner_sessionmaker, ctx["t"], "dispatch", other)
    command, _ = await asked_release(owner_sessionmaker, ctx["t"], admin, "dispatch", item=item)
    await confirmed_by_actor(owner_sessionmaker, command, admin)
    async with owner_sessionmaker() as s:
        with pytest.raises(DBAPIError, match="recorded already"):
            async with s.begin():
                await s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(ctx["t"])})
                await s.execute(text("select * from operator_command_holds_snapshot(:c)"), {"c": command})
    async with owner_sessionmaker() as s, s.begin():  # past the function: the table's owner adds one
        await s.execute(text("insert into operator_command_holds (command_id, tenant_id, kind, item_id, hold_id) "
                             "values (:c, :t, 'dispatch', :i, :h)"),
                        {"c": command, "t": ctx["t"], "i": other, "h": token})  # fmt: skip
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.UNCONFIRMED: 1}
    assert len(await held(owner_sessionmaker, ctx["t"])) == 2  # nothing released


async def test_a_release_confirmed_before_its_holds_were_recorded_records_none_after(owner_sessionmaker) -> None:
    """Its holds are recorded once, before any confirmation: a confirmation binds what was shown, never what's added
    after it (a command the API records has its holds in the same transaction; one made otherwise shows none)."""
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item = uuid.uuid4()
    await hold(owner_sessionmaker, ctx["t"], "dispatch", item)
    async with owner_sessionmaker() as s, s.begin():
        command = (await s.execute(text(
            "insert into operator_commands (tenant_id, kind, item_id, work_kind, actor_id, idempotency_key) "
            "values (:t, 'release_held', :i, 'dispatch', :u, 'unshown') returning id"),
            {"t": ctx["t"], "i": item, "u": admin})).scalar_one()  # fmt: skip
    await confirmed_by_actor(owner_sessionmaker, command, admin)
    async with owner_sessionmaker() as s:
        with pytest.raises(DBAPIError, match="recorded already"):
            async with s.begin():
                await s.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": str(ctx["t"])})
                await s.execute(text("select * from operator_command_holds_snapshot(:c)"), {"c": command})


# --- the functions ---------------------------------------------------------------------------------------------------


def test_the_api_releases_nothing_itself_and_the_exact_release_is_the_leaders_alone(pg_url: str) -> None:
    def found(c: Any) -> tuple[Any, ...]:
        gone = c.execute(
            text(
                "select to_regprocedure('work_failure_release(text, uuid)'), "
                "to_regprocedure('work_failures_release_many(text, timestamptz, integer)')"
            )
        ).one()
        return tuple(gone), {r: effective(c, r) for r in (*SERVICE_ROLES, "dewpoint_recovery")}

    gone, rights = autocommitted(pg_url, found)
    assert gone == (None, None)
    assert holders(rights, "public.work_failures_release_exact") == {"dewpoint_dispatch"}
    assert holders(rights, "public.operator_command_holds_snapshot") == {"dewpoint_api"}
    assert holders(rights, "public.work_failures_held") == {"dewpoint_api"}
