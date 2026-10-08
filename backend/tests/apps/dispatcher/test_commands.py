# SPDX-License-Identifier: Apache-2.0
"""The operator's commands, carried out by the dispatcher's leader (the owner's rulings on the 2b-4b M3 design, rev 1
and 2). The API recorded each one pending; the leader, a bounded number a pass, rechecks its operator's authorization
and that its item's recorded reason is still the one it was asked on, asks Temporal in the namespace the deployment
recorded, then applies it in one transaction, every change conditional, with its result and an audit entry naming its
operator; or refuses it, with why, audited alike.

`history_lost` is an administrative settlement: the run's outcome is unconfirmed, its steps still `running` close
unconfirmed, and its slot is released. Here Temporal is a stand-in answering as the case needs."""

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCStatusCode

from dewpoint.apps.dispatcher import commands
from dewpoint.core.auth.users import create_user
from dewpoint.core.runs.service import HISTORY_LOST, OUTCOME_UNCONFIRMED
from tests.apps.dispatcher.test_reconcile import DescribeFails
from tests.apps.dispatcher.test_reconcile_runs import Described
from tests.apps.test_runs import rpc
from tests.core.retention.support import request, run, sql, tenant

pytestmark = pytest.mark.usefixtures("development_deployment")
EVIDENCE = "Its namespace's retention passed: checked in the Temporal UI."
GONE = DescribeFails(rpc(RPCStatusCode.NOT_FOUND))  # from a namespace that answers


async def operator(owner: Any, *, admin: bool = True) -> uuid.UUID:
    async with owner() as s, s.begin():
        email = f"{uuid.uuid4().hex[:10]}@corp.test"
        return (await create_user(s, email=email, password="violet-otter-42", platform_admin=admin)).id


async def lost_run(owner: Any, ctx: dict[str, Any]) -> uuid.UUID:
    """A started run, its row `running` with a step still `running`, its slot held: its history gone."""
    rid = await request(owner, ctx, "started", None)
    await run(owner, ctx, None, run_id=rid)
    await sql(owner, "insert into run_slots (run_id, tenant_id) values (:i, :t)", i=rid, t=ctx["t"])
    await sql(owner, "insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status) "
              "values (:t, :r, :s, '', 1, 'n', 'running')", t=ctx["t"], r=rid, s=uuid.uuid4())  # fmt: skip
    return rid


async def lost_subrun(owner: Any, ctx: dict[str, Any]) -> uuid.UUID:
    root = await run(owner, ctx, timedelta(hours=1))
    return await run(owner, ctx, None, parent=root)


async def lost_slot(owner: Any, ctx: dict[str, Any]) -> uuid.UUID:
    rid = await request(owner, ctx, "started", None)
    await run(owner, ctx, timedelta(minutes=5), run_id=rid)
    await sql(owner, "insert into run_slots (run_id, tenant_id) values (:i, :t)", i=rid, t=ctx["t"])
    return rid


async def ended_start(owner: Any, ctx: dict[str, Any], *, ended: bool = True) -> uuid.UUID:
    """A request left `starting` without a slot: its row ended (start after its end), or still `running`."""
    rid = await request(owner, ctx, "starting", None)
    await run(owner, ctx, timedelta(minutes=5) if ended else None, run_id=rid)
    return rid


ITEMS = {  # a command's kind: how its item is made, the reason it's asked on
    "record_lost_run": (lost_run, "run_history_missing"),
    "record_lost_subrun": (lost_subrun, "subrun_history_missing"),
    "release_lost_slot": (lost_slot, "slot_history_missing"),
    "settle_ended": (ended_start, "start_after_end"),
}


async def asked(owner: Any, ctx: dict[str, Any], kind: str, actor: uuid.UUID, *, evidence: str = EVIDENCE,
                item: uuid.UUID | None = None) -> tuple[uuid.UUID, uuid.UUID]:  # fmt: skip
    """`kind`'s item with its reason recorded, and a command on it, pending, as the API records one: (item, command)."""
    made, reason = ITEMS[kind]
    item = item or await made(owner, ctx)
    command = uuid.uuid4()
    async with owner() as s, s.begin():
        since = (await s.execute(text("insert into recovery_items (tenant_id, reason, item_id) values (:t, :r, :i) "
                                      "on conflict do nothing returning since"),
                                 {"t": ctx["t"], "r": reason, "i": item})).scalar()  # fmt: skip
        if since is None:
            since = (await s.execute(text("select since from recovery_items where item_id = :i and reason = :r"),
                                     {"i": item, "r": reason})).scalar_one()  # fmt: skip
        await s.execute(text("insert into operator_commands (id, tenant_id, kind, item_id, reason, incident_since, "
                             "actor_id, idempotency_key, evidence) values (:c, :t, :k, :i, :r, :since, :u, :key, :e)"),
                        {"c": command, "t": ctx["t"], "k": kind, "i": item, "r": reason, "since": since, "u": actor,
                         "key": uuid.uuid4().hex, "e": evidence})  # fmt: skip
    return item, command


async def decided(owner: Any, command: uuid.UUID) -> tuple[Any, ...]:
    async with owner() as s:
        found = await s.execute(text("select status, outcome, decided_at is not null from operator_commands "
                                     "where id = :c"), {"c": command})  # fmt: skip
        return tuple(found.one())


async def audited(owner: Any, command: uuid.UUID) -> list[tuple[Any, ...]]:
    async with owner() as s:
        found = await s.execute(text("select action, actor_id, details->>'outcome' from audit_log where target_id = :c "
                                     "order by seq"), {"c": str(command)})  # fmt: skip
        return [tuple(r) for r in found]


async def ended(owner: Any, run_id: uuid.UUID) -> tuple[Any, ...]:
    async with owner() as s:
        found = await s.execute(text("select status, error_code, ended_at is not null from runs where id = :i"),
                                {"i": run_id})  # fmt: skip
        return tuple(found.one())


async def count(owner: Any, query: str, item: uuid.UUID) -> int:
    async with owner() as s:
        return int((await s.execute(text(query), {"i": item})).scalar_one())


SLOTS = "select count(*) from run_slots where run_id = :i"
REASONS = "select count(*) from recovery_items where item_id = :i"


async def test_a_lost_runs_command_records_history_lost_closes_its_steps_and_releases_its_slot(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, "record_lost_run", admin)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.HISTORY_LOST: 1}
    assert await ended(owner_sessionmaker, item) == ("failed", HISTORY_LOST, True)
    assert await count(owner_sessionmaker, "select count(*) from run_steps where run_id = :i and status = 'failed' "
                       f"and error_code = '{OUTCOME_UNCONFIRMED}'", item) == 1  # fmt: skip
    assert (await count(owner_sessionmaker, SLOTS, item), await count(owner_sessionmaker, REASONS, item)) == (0, 0)
    assert await decided(owner_sessionmaker, command) == ("applied", commands.HISTORY_LOST, True)
    assert await audited(owner_sessionmaker, command) == [("operator.command.applied", admin, commands.HISTORY_LOST)]
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {}  # decided once


async def test_a_lost_subruns_command_records_history_lost(owner_sessionmaker, dispatch_sessionmaker) -> None:
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, "record_lost_subrun", admin)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.HISTORY_LOST: 1}
    assert await ended(owner_sessionmaker, item) == ("failed", HISTORY_LOST, True)
    assert await decided(owner_sessionmaker, command) == ("applied", commands.HISTORY_LOST, True)


async def test_a_lost_slots_command_releases_it(owner_sessionmaker, dispatch_sessionmaker) -> None:
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, "release_lost_slot", admin)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.SLOT_RELEASED: 1}
    assert await count(owner_sessionmaker, SLOTS, item) == 0
    assert await ended(owner_sessionmaker, item) == ("succeeded", None, True)  # its recorded end stands
    assert await decided(owner_sessionmaker, command) == ("applied", commands.SLOT_RELEASED, True)


async def test_settling_an_ended_start_whose_execution_is_gone_starts_it_its_recorded_end_standing(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, "settle_ended", admin)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.SETTLED_ABSENT: 1}
    assert await count(owner_sessionmaker, "select count(*) from run_requests where id = :i and status = 'started'",
                       item) == 1  # fmt: skip
    assert await ended(owner_sessionmaker, item) == ("succeeded", None, True)
    assert await decided(owner_sessionmaker, command) == ("applied", commands.SETTLED_ABSENT, True)


async def test_settling_a_start_whose_execution_ended_records_the_end_temporal_reports_if_its_row_has_none(
    owner_sessionmaker, dispatch_sessionmaker
) -> None:  # fmt: skip
    """The owner's ruling (rev 1): settle-ended may verify a present, terminal execution; no evidence is needed."""
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item = await ended_start(owner_sessionmaker, ctx, ended=False)
    _, command = await asked(owner_sessionmaker, ctx, "settle_ended", admin, item=item, evidence="")
    terminated = Described(WorkflowExecutionStatus.TERMINATED)
    assert await commands.commands_once(dispatch_sessionmaker, terminated) == {commands.SETTLED_TERMINAL: 1}
    assert await ended(owner_sessionmaker, item) == ("failed", "terminated", True)
    assert await decided(owner_sessionmaker, command) == ("applied", commands.SETTLED_TERMINAL, True)


class Elsewhere(DescribeFails):
    namespace = "another"  # not the namespace the deployment recorded


@pytest.mark.parametrize(
    ("case", "outcome"),
    [
        ("unanswered", commands.TEMPORAL_UNCERTAIN),
        ("live", commands.EXECUTION_PRESENT),
        ("other_namespace", commands.NAMESPACE_MISMATCH),
        ("no_evidence", commands.EVIDENCE_MISSING),
        ("no_longer_admin", commands.UNAUTHORIZED),
        ("resolved", commands.STALE),
        ("recurred", commands.STALE),
        ("ended_meanwhile", commands.CHANGED),
    ],
)
async def test_a_command_that_cant_be_carried_out_safely_is_refused_with_why_changing_nothing(
    owner_sessionmaker, dispatch_sessionmaker, case: str, outcome: str
) -> None:  # fmt: skip
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    item, command = await asked(owner_sessionmaker, ctx, "record_lost_run", admin,
                                evidence="" if case == "no_evidence" else EVIDENCE)  # fmt: skip
    client: Any = {
        "unanswered": DescribeFails(rpc(RPCStatusCode.NOT_FOUND), namespace_error=rpc(RPCStatusCode.UNAVAILABLE)),
        "live": Described(WorkflowExecutionStatus.RUNNING),
        "other_namespace": Elsewhere(rpc(RPCStatusCode.NOT_FOUND)),
    }.get(case, GONE)
    if case == "no_longer_admin":
        await sql(owner_sessionmaker, "update users set is_platform_admin = false where id = :u", u=admin)
    elif case == "resolved":
        await sql(owner_sessionmaker, "delete from recovery_items where item_id = :i", i=item)
    elif case == "recurred":  # resolved, then recorded again: another incident than the one it was asked on
        await sql(owner_sessionmaker, "update recovery_items set since = since + interval '1 minute' "
                  "where item_id = :i", i=item)  # fmt: skip
    elif case == "ended_meanwhile":
        await sql(owner_sessionmaker, "update runs set status = 'succeeded', ended_at = now() where id = :i", i=item)
    assert await commands.commands_once(dispatch_sessionmaker, client) == {outcome: 1}
    assert await decided(owner_sessionmaker, command) == ("refused", outcome, True)
    assert await audited(owner_sessionmaker, command) == [("operator.command.refused", admin, outcome)]
    expected = ("succeeded", None, True) if case == "ended_meanwhile" else ("running", None, False)
    assert await ended(owner_sessionmaker, item) == expected
    assert await count(owner_sessionmaker, SLOTS, item) == 1


async def test_a_pass_carries_out_a_bounded_number_of_commands_oldest_first(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:  # fmt: skip
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    made = [(await asked(owner_sessionmaker, ctx, "release_lost_slot", admin))[1] for _ in range(3)]
    monkeypatch.setattr(commands, "BATCH", 2)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.SLOT_RELEASED: 2}
    assert [(await decided(owner_sessionmaker, c))[0] for c in made] == ["applied", "applied", "pending"]
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.SLOT_RELEASED: 1}


async def test_a_command_an_unexpected_error_stops_is_refused_once_never_retried_every_pass(
    owner_sessionmaker, dispatch_sessionmaker, monkeypatch
) -> None:  # fmt: skip
    """A bug refuses it (`internal_error`), audited: the operator asks again once it's mended. A database outage
    leaves it pending for the next pass."""
    ctx, admin = await tenant(owner_sessionmaker), await operator(owner_sessionmaker)
    _, command = await asked(owner_sessionmaker, ctx, "release_lost_slot", admin)

    async def broken(*_a: Any, **_k: Any) -> Any:
        raise ConnectionRefusedError

    monkeypatch.setattr(commands, "_asked", broken)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {"error": 1}
    assert (await decided(owner_sessionmaker, command))[0] == "pending"

    async def bug(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("a bug")

    monkeypatch.setattr(commands, "_asked", bug)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.INTERNAL_ERROR: 1}
    assert await decided(owner_sessionmaker, command) == ("refused", commands.INTERNAL_ERROR, True)
    assert await audited(owner_sessionmaker, command) == [("operator.command.refused", admin, commands.INTERNAL_ERROR)]
