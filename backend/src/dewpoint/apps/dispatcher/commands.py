# SPDX-License-Identifier: Apache-2.0
"""The operator's commands, carried out by the dispatcher's leader (the owner's rulings on the 2b-4b M3 design, rev 1
and 2). A platform admin asks, through the API, for an item a pass left for recovery (its reason recorded in
`recovery_items`) to be settled; the API records the command, pending, and the leader carries it out: the API has no
Temporal client. Each pending command, oldest first and `BATCH` a pass, ids reaching it only through
`pending_commands()`:

1. is refused unless its operator is still an active platform admin, and its item's reason is still recorded since
   the time it was asked on (one that resolved, or resolved and recurred, makes the command stale);
2. has Temporal asked about its item's execution, in the namespace the deployment recorded: an answer that isn't
   certain refuses it;
3. is applied in one transaction, every change conditional on the state checked, with its result and an audit entry
   naming its operator; or refused, with why, audited alike. Nothing retries a start.

Each command acts only on an item with its reason recorded:

- `record_lost_run` (`run_history_missing`): once Temporal says the execution is absent, and with the operator's
  evidence, the run `failed` with `history_lost`, its steps still `running` closed unconfirmed, its slot released;
- `record_lost_subrun` (`subrun_history_missing`): the sub-run the same, alike; it has no slot;
- `release_lost_slot` (`slot_history_missing`): the slot of a run whose row ended, alike;
- `settle_ended` (`start_after_end`, `start_history_missing`): the request `started`. Its execution terminal: its row
  records the end Temporal reports, if it has none. Absent, with evidence: its row's recorded end stands.

`history_lost` is an administrative settlement: the execution's outcome is unconfirmed, never proof that it failed.
A command an unexpected error stops is refused (`internal_error`), once: the operator asks again once it's mended. The
database failing leaves it pending for the next pass."""

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import dispatch, reconcile
from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope, unavailable
from dewpoint.core.recovery import LOST
from dewpoint.core.runs import service as runs
from dewpoint.core.runs.service import HISTORY_LOST as HISTORY_LOST_CODE
from dewpoint.engine.runtime.ids import run_workflow_id

log = structlog.get_logger("dewpoint.dispatcher")
BATCH = 20  # commands a pass

# What a command's result says, a fixed code: applied
HISTORY_LOST, SLOT_RELEASED = "history_lost", "slot_released"
SETTLED_TERMINAL, SETTLED_ABSENT = "settled_terminal", "settled_absent"
# ... or refused
UNAUTHORIZED, STALE, CHANGED, EVIDENCE_MISSING = "unauthorized", "stale", "changed", "evidence_missing"
TEMPORAL_UNCERTAIN, NAMESPACE_MISMATCH = "temporal_uncertain", "namespace_mismatch"
EXECUTION_PRESENT, EXECUTION_LIVE, INTERNAL_ERROR = "execution_present", "execution_live", "internal_error"
HISTORY_LOST_MESSAGE = (
    "Its history was gone before its end was recorded: an operator settled it. Whether it ran to its end is "
    "unconfirmed."
)

_PENDING = text("select tenant_id, command_id from pending_commands(:n)")
_COMMAND = text(
    "select id, tenant_id, kind, item_id, reason, incident_since, actor_id, evidence from operator_commands "
    "where id = :c and status = 'pending' for update"
)
_CURRENT = text("select exists (select 1 from recovery_items where item_id = :i and reason = :r and since = :since)")
_AUTHORIZED = text("select platform_admin_active(:u)")
_NAMESPACE = text("select temporal_namespace from platform_settings where id = 1")
_DECIDED = text(
    "update operator_commands set status = :s, outcome = :o, decided_at = statement_timestamp() "
    "where id = :c and status = 'pending'"
)


@dataclass(frozen=True)
class Command:
    id: uuid.UUID
    tenant_id: uuid.UUID
    kind: str
    item_id: uuid.UUID
    reason: str
    incident_since: datetime
    actor_id: uuid.UUID
    evidence: str


@dataclass(frozen=True)
class Answer:
    """What Temporal said of the item's execution: `absent` (NOT_FOUND from its namespace, which answers),
    `terminal` (with the end it reports), `live`, or why it isn't certain."""

    kind: str
    ended: reconcile.Ended | None = None
    close_time: datetime | None = None


async def commands_once(sessionmaker: async_sessionmaker[AsyncSession], client: Client) -> dict[str, int]:
    """One pass: each pending command carried out or refused. What happened, counted by outcome."""
    async with sessionmaker() as s:
        picked = (await s.execute(_PENDING, {"n": BATCH})).all()
    counts: Counter[str] = Counter()
    for tenant_id, command_id in picked:
        try:
            outcome = await _carried_out(sessionmaker, client, tenant_id, command_id)
        except Exception as e:
            log.error("operator_command_failed", command_id=str(command_id), error=type(e).__name__)
            if unavailable(e) or isinstance(e, TimeoutError):  # the database (or the network) failing: next pass
                counts["error"] += 1
                continue
            outcome = await _refused_alone(sessionmaker, tenant_id, command_id, INTERNAL_ERROR)
        if outcome is not None:
            counts[outcome] += 1
    return dict(counts)


async def _carried_out(
    sessionmaker: async_sessionmaker[AsyncSession], client: Client, tenant_id: uuid.UUID, command_id: uuid.UUID
) -> str | None:
    """The command's outcome; None when another leader decided it meanwhile."""
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        command = await _pending(s, command_id)
        if command is None:
            return None
        why = await _why_not(s, command)
        if why is None and command.kind in LOST and not command.evidence.strip():
            why = EVIDENCE_MISSING  # the operator's word on how the loss was confirmed (the owner's ruling, rev 1)
        if why is not None:
            return await _decided(s, command, "refused", why)
    answer = await _asked(sessionmaker, client, command)
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        command = await _pending(s, command_id)  # under its lock again: checked again, then applied or refused
        if command is None:
            return None
        why = await _why_not(s, command) or _unanswered(command, answer)
        if why is not None:
            return await _decided(s, command, "refused", why)
        applied = await APPLIED[command.kind](s, command, answer)
        if applied is None:  # the item isn't as it was checked: nothing changed
            return await _decided(s, command, "refused", CHANGED)
        await s.execute(text("delete from recovery_items where item_id = :i and reason = :r"),
                        {"i": command.item_id, "r": command.reason})  # fmt: skip
        return await _decided(s, command, "applied", applied)


async def _pending(s: AsyncSession, command_id: uuid.UUID) -> Command | None:
    row = (await s.execute(_COMMAND, {"c": command_id})).first()
    return Command(*row) if row is not None else None


async def _why_not(s: AsyncSession, command: Command) -> str | None:
    """Why the command can't be carried out whatever Temporal says: its operator, or its reason, no longer as asked."""
    if not (await s.execute(_AUTHORIZED, {"u": command.actor_id})).scalar_one():
        return UNAUTHORIZED
    current = {"i": command.item_id, "r": command.reason, "since": command.incident_since}
    if not (await s.execute(_CURRENT, current)).scalar_one():
        return STALE
    return None


def _unanswered(command: Command, answer: Answer) -> str | None:
    """Why Temporal's answer refuses the command, or None."""
    if answer.kind in (TEMPORAL_UNCERTAIN, NAMESPACE_MISMATCH):
        return answer.kind
    if command.kind == "settle_ended":
        if answer.kind == "live":
            return EXECUTION_LIVE
        if answer.kind == "absent" and not command.evidence.strip():
            return EVIDENCE_MISSING
        return None
    return None if answer.kind == "absent" else EXECUTION_PRESENT


async def _asked(sessionmaker: async_sessionmaker[AsyncSession], client: Client, command: Command) -> Answer:
    """Temporal, in the namespace the deployment recorded, about the item's execution."""
    async with sessionmaker() as s:
        recorded = (await s.execute(_NAMESPACE)).scalar()
    if recorded != client.namespace:
        return Answer(NAMESPACE_MISMATCH)
    handle = client.get_workflow_handle(run_workflow_id(str(command.tenant_id), str(command.item_id)))
    try:
        described = await handle.describe(rpc_timeout=reconcile.CALL_DEADLINE)
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND and await reconcile.namespace_answers(client):
            return Answer("absent")
        return Answer(TEMPORAL_UNCERTAIN)
    except Exception:  # a lost connection or a timeout: nothing is known
        return Answer(TEMPORAL_UNCERTAIN)
    if described.status is None or described.status in reconcile.LIVE:
        return Answer("live")
    ended = await reconcile.reported_end(handle, described.status, command.item_id)
    return Answer("terminal", ended, described.close_time)


async def _decided(s: AsyncSession, command: Command, status: str, outcome: str) -> str:
    """The command's result, and its audit entry naming its operator, in `s`'s transaction."""
    await s.execute(_DECIDED, {"s": status, "o": outcome, "c": command.id})
    await audit.record(s, tenant_id=command.tenant_id, actor_id=command.actor_id,
                       action=f"operator.command.{status}", target_type="operator_command", target_id=str(command.id),
                       details={"kind": command.kind, "item_id": str(command.item_id), "outcome": outcome})  # fmt: skip
    (log.info if status == "applied" else log.warning)(
        f"operator_command_{status}", command_id=str(command.id), kind=command.kind, outcome=outcome
    )
    return outcome


async def _refused_alone(
    sessionmaker: async_sessionmaker[AsyncSession], tenant_id: uuid.UUID, command_id: uuid.UUID, why: str
) -> str | None:
    async with sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant_id)
        command = await _pending(s, command_id)
        return await _decided(s, command, "refused", why) if command is not None else None


# --- what each command does, conditional on the state checked: None when it isn't so --------------------------------

_LOST = (
    "update runs set status = 'failed', error_code = :code, error_message = :m, ended_at = statement_timestamp() "
    "where id = :i and status = 'running' and {which} returning id"
)
_ROOT = "parent_run_id is null and exists (select 1 from run_requests q where q.id = runs.id and q.status = 'started')"
_ORPHAN = (
    "parent_run_id is not null "
    "and exists (select 1 from runs r where r.id = runs.root_run_id and r.status <> 'running')"
)


async def _lost(s: AsyncSession, command: Command, which: str) -> bool:
    found = await s.execute(text(_LOST.format(which=which)), {"code": HISTORY_LOST_CODE, "m": HISTORY_LOST_MESSAGE,
                                                               "i": command.item_id})  # fmt: skip
    if found.first() is None:
        return False
    await runs.close_unconfirmed(s, command.item_id)  # its steps' outcomes unconfirmed, as its own
    return True


async def _record_lost_run(s: AsyncSession, command: Command, _answer: Answer) -> str | None:
    if not await _lost(s, command, _ROOT):
        return None
    await dispatch.release(s, command.item_id)
    return HISTORY_LOST


async def _record_lost_subrun(s: AsyncSession, command: Command, _answer: Answer) -> str | None:
    return HISTORY_LOST if await _lost(s, command, _ORPHAN) else None


async def _release_lost_slot(s: AsyncSession, command: Command, _answer: Answer) -> str | None:
    found = await s.execute(text(
        "delete from run_slots t where t.run_id = :i and exists (select 1 from runs u where u.id = t.run_id "
        "and u.status <> 'running') and exists (select 1 from run_requests q where q.id = t.run_id "
        "and q.status <> 'starting') returning t.run_id"), {"i": command.item_id})  # fmt: skip
    return SLOT_RELEASED if found.first() is not None else None


async def _settle_ended(s: AsyncSession, command: Command, answer: Answer) -> str | None:
    found = await s.execute(text("update run_requests set status = 'started' where id = :i and status = 'starting' "
                                 "returning id"), {"i": command.item_id})  # fmt: skip
    if found.first() is None:
        return None
    if answer.kind == "absent":
        return SETTLED_ABSENT  # its row's recorded end stands
    ended = answer.ended
    if ended is None:  # a terminal answer carries its end
        return None
    await runs.finish_run(s, command.item_id, status=ended.status, ended_at=answer.close_time or datetime.now(UTC),
                          error_code=ended.error_code, error_message=ended.error_message, iterations=ended.iterations,
                          if_running=True)  # fmt: skip
    await runs.close_unconfirmed(s, command.item_id)
    return SETTLED_TERMINAL


APPLIED = {
    "record_lost_run": _record_lost_run,
    "record_lost_subrun": _record_lost_subrun,
    "release_lost_slot": _release_lost_slot,
    "settle_ended": _settle_ended,
}
