# SPDX-License-Identifier: Apache-2.0
"""The operator's commands, carried out by the dispatcher's leader (the owner's rulings on the 2b-4b M3 design, rev 1
and 2). A platform admin asks, through the API, for an item a pass left for recovery (its reason recorded in
`recovery_items`) to be settled; the API records the command, pending, and the leader carries it out: the API has no
Temporal client. Each pending command, oldest first and `BATCH` a pass within the leader's pass budget (D16), ids
reaching it only through `pending_commands()`:

1. is refused unless its operator confirmed it, through their own recovery login, and that confirmation still holds
   (2b-4b M4 recovery, task 6: the login still mapped to them, unrevoked, and the digest it confirmed still the
   command's, recomputed here), its operator is still an active platform admin, and its item's reason is still
   recorded since the time it was asked on (one that resolved, or resolved and recurred, makes the command stale). A
   command awaiting its operator's confirmation isn't picked; one left unconfirmed an hour is, and refused;
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

- `release_held` and `release_held_many` (2b-4b M4 recovery, task 8): the holds the command showed, recorded with it
  (`operator_command_holds`) and confirmed in its digest, released exactly (`work_failures_release_exact`): each still
  held under its token is `released`, one settled since `not_held`, one held again since `hold_changed`, nothing in a
  missing one's place, no other kind's hold touched; the results audited, `AUDITED_IDS` an entry. Temporal isn't asked,
  and a release names no recovery reason to go stale.

- `abandon_start` (`start_unresolved`; task 10): its operator's structured evidence first (the identifiers, each
  the record's; the Temporal response they saw, with its time; their rationale), then Temporal's own answer: only
  `absent` goes on. The request `dead` (`start_abandoned`), its run failed, the reason moved to `start_abandoned`; the
  blocker, the evidence and the keys untouched: abandoning a start ends the request, never its send. Both responses
  are audited.

`history_lost` is an administrative settlement: the execution's outcome is unconfirmed, never proof that it failed.
A command an unexpected error stops is refused (`internal_error`), once: the operator asks again once it's mended. The
database failing leaves it pending for the next pass."""

import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import budget, dispatch, reconcile, recovery
from dewpoint.core.audit import service as audit
from dewpoint.core.db import tenant_scope, unavailable
from dewpoint.core.recovery import ABANDON, AUDITED_IDS, INSPECT, LOST, RELEASES
from dewpoint.core.runs import service as runs
from dewpoint.core.runs.service import HISTORY_LOST as HISTORY_LOST_CODE
from dewpoint.core.tenancy import lifecycle
from dewpoint.engine.runtime.activities import RunResult
from dewpoint.engine.runtime.ids import run_workflow_id

log = structlog.get_logger("dewpoint.dispatcher")
BATCH = 20  # commands a pass

# What a command's result says, a fixed code: applied
HISTORY_LOST, SLOT_RELEASED, HOLDS_RELEASED = "history_lost", "slot_released", "holds_released"
SETTLED_TERMINAL, SETTLED_ABSENT = "settled_terminal", "settled_absent"
# ... or refused
UNCONFIRMED, UNAUTHORIZED, STALE, EXPIRED = "unconfirmed", "unauthorized", "stale", "expired"
TENANT_ERASING = "tenant_erasing"  # its tenant no longer active: an erasure began
CHANGED, EVIDENCE_MISSING = "changed", "evidence_missing"
TEMPORAL_UNCERTAIN, NAMESPACE_MISMATCH = "temporal_uncertain", "namespace_mismatch"
EXECUTION_PRESENT, EXECUTION_LIVE, INTERNAL_ERROR = "execution_present", "execution_live", "internal_error"
START_ABANDONED = "start_abandoned"
START_ABANDONED_MESSAGE = (
    "An operator ended this request. Temporal never showed its start; a send it may have taken is still tracked, and "
    "one that lands is stopped and flagged."
)
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
# Its operator's confirmation, still holding: by the login mapped to them, unrevoked, of the command's digest now (0056)
_CONFIRMED = text(
    "select exists (select 1 from operator_confirmations x join recovery_operators o on o.login = x.login "
    "where x.command_id = :c and x.user_id = :u and o.user_id = :u and o.revoked_at is null "
    "and x.digest = operator_command_digest(:c))"
)
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
    item_id: uuid.UUID | None  # a bulk release names none
    reason: str | None  # a release names none
    incident_since: datetime | None
    actor_id: uuid.UUID
    evidence: str

    @property
    def item(self) -> uuid.UUID:
        """An M3 command's item: each kind but a bulk release names one (`operator_commands_fields`, 0057)."""
        if self.item_id is None:
            raise ValueError(f"a {self.kind} command names no item")
        return self.item_id


@dataclass(frozen=True)
class Answer:
    """What Temporal said of the item's execution: `absent` (NOT_FOUND from its namespace, which answers),
    `terminal` (with the end it reports), `live`, or why it isn't certain."""

    kind: str
    ended: reconcile.Ended | None = None
    close_time: datetime | None = None
    observed: dict[str, str] | None = None  # the leader's own response, and when (an abandonment's record)


def _observed(status: str, message: str = "") -> dict[str, str]:
    return {"call": "DescribeWorkflowExecution", "status": status, "message": message[:500],
            "observed_at": datetime.now(UTC).isoformat()}  # fmt: skip


async def commands_once(sessionmaker: async_sessionmaker[AsyncSession], client: Client) -> dict[str, int]:
    """One pass: each pending command carried out or refused. What happened, counted by outcome."""
    async with sessionmaker() as s:
        picked = (await s.execute(_PENDING, {"n": BATCH})).all()
    counts: Counter[str] = Counter()
    with budget.passing("commands") as admitted:  # the leader's pass budget (D16): a slow Temporal never holds it
        for tenant_id, command_id in admitted(picked, key=lambda row: row[1]):
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
    admitted.reported(counts, full=len(picked) >= BATCH)
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
        if why is None and command.kind == ABANDON:
            why = await _abandon_evidence(s, command)
        if why is not None:
            return await _decided(s, command, "refused", why)
    answer = Answer("unasked") if command.kind in RELEASES else await _asked(sessionmaker, client, command)
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
        if command.reason is not None:
            await s.execute(text("delete from recovery_items where item_id = :i and reason = :r"),
                            {"i": command.item_id, "r": command.reason})  # fmt: skip
        return await _decided(s, command, "applied", applied)


async def _pending(s: AsyncSession, command_id: uuid.UUID) -> Command | None:
    row = (await s.execute(_COMMAND, {"c": command_id})).first()
    return Command(*row) if row is not None else None


async def _why_not(s: AsyncSession, command: Command) -> str | None:
    """Why the command can't be carried out whatever Temporal says: its confirmation, its operator, or its reason, no
    longer as asked. An inspection is the reveal's to carry out (task 9): one picked is past its hour.

    First, the tenant: active, read under its lifecycle lock, shared, which the transaction holds to its end, as the
    API's change does (the owner's review of gate C). An erasure's step waits for the command to commit, or the command
    sees the tenant `erasing` and is refused, changing nothing: past its stage 60 the fence would refuse its record."""
    if not await lifecycle.is_active(s, command.tenant_id):
        return TENANT_ERASING
    if command.kind == INSPECT:
        return EXPIRED
    if not (await s.execute(_CONFIRMED, {"c": command.id, "u": command.actor_id})).scalar_one():
        return UNCONFIRMED
    if not (await s.execute(_AUTHORIZED, {"u": command.actor_id})).scalar_one():
        return UNAUTHORIZED
    if command.kind in RELEASES:  # bound to its holds, each released or not by its own result
        return None
    current = {"i": command.item_id, "r": command.reason, "since": command.incident_since}
    if not (await s.execute(_CURRENT, current)).scalar_one():
        return STALE
    return None


def _unanswered(command: Command, answer: Answer) -> str | None:
    """Why Temporal's answer refuses the command, or None."""
    if command.kind in RELEASES:  # Temporal isn't asked
        return None
    if answer.kind in (TEMPORAL_UNCERTAIN, NAMESPACE_MISMATCH):
        return answer.kind
    if command.kind == ABANDON:  # only `absent` goes on
        return None if answer.kind == "absent" else EXECUTION_LIVE if answer.kind == "live" else EXECUTION_PRESENT
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
    handle = client.get_workflow_handle(
        run_workflow_id(str(command.tenant_id), str(command.item_id)), result_type=RunResult
    )  # a completed execution's own end, as it returned it
    try:
        described = await handle.describe(rpc_timeout=reconcile.CALL_DEADLINE)
    except RPCError as e:
        observed = _observed(e.status.name, e.message)
        if e.status == RPCStatusCode.NOT_FOUND and await reconcile.namespace_answers(client):
            return Answer("absent", observed=observed)
        return Answer(TEMPORAL_UNCERTAIN, observed=observed)
    except Exception as e:  # a lost connection or a timeout: nothing is known
        return Answer(TEMPORAL_UNCERTAIN, observed=_observed(type(e).__name__))
    observed = _observed(described.status.name if described.status is not None else "UNKNOWN")
    if described.status is None or described.status in reconcile.LIVE:
        return Answer("live", observed=observed)
    if command.kind != "settle_ended":  # it's there: a lost-history command needs no more to refuse
        return Answer("terminal", observed=observed)
    try:
        ended = await reconcile.reported_end(handle, described.status, command.item)
    except (RPCError, TimeoutError):  # its end unread this time: nothing is settled on it
        return Answer(TEMPORAL_UNCERTAIN)
    return Answer("terminal", ended, described.close_time)


async def _decided(s: AsyncSession, command: Command, status: str, outcome: str) -> str:
    """The command's result, and its audit entry naming its operator, in `s`'s transaction."""
    await s.execute(_DECIDED, {"s": status, "o": outcome, "c": command.id})
    await audit.record(s, tenant_id=command.tenant_id, actor_id=command.actor_id,
                       action=f"operator.command.{status}", target_type="operator_command", target_id=str(command.id),
                       details={"kind": command.kind, "item_id": command.item_id and str(command.item_id),
                                "outcome": outcome})  # fmt: skip
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
    await runs.close_unconfirmed(s, command.item)  # its steps' outcomes unconfirmed, as its own
    return True


async def _record_lost_run(s: AsyncSession, command: Command, _answer: Answer) -> str | None:
    if not await _lost(s, command, _ROOT):
        return None
    await dispatch.release(s, command.item)
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
    ended = answer.ended
    if answer.kind != "absent" and ended is None:  # a terminal answer carries its end: else nothing changes
        return None
    found = await s.execute(text("update run_requests set status = 'started' where id = :i and status = 'starting' "
                                 "returning id"), {"i": command.item_id})  # fmt: skip
    if found.first() is None:
        return None
    if ended is None:
        return SETTLED_ABSENT  # its row's recorded end stands
    await runs.finish_run(s, command.item, status=ended.status, ended_at=answer.close_time or datetime.now(UTC),
                          error_code=ended.error_code, error_message=ended.error_message, iterations=ended.iterations,
                          if_running=True)  # fmt: skip
    await runs.close_unconfirmed(s, command.item)
    return SETTLED_TERMINAL


_START_REQUEST = text("select start_request_id from run_requests where id = :i")
RESPONSE = ("call", "status", "message", "observed_at")


async def _abandon_evidence(s: AsyncSession, command: Command) -> str | None:
    """`evidence_missing` unless the abandonment's evidence is complete: the identifiers, each the record's; the
    Temporal response its operator saw, with its time; their rationale (a visibility result may be attached)."""
    try:
        given = json.loads(command.evidence)
    except ValueError:
        return EVIDENCE_MISSING
    if not isinstance(given, dict):
        return EVIDENCE_MISSING
    start = (await s.execute(_START_REQUEST, {"i": command.item})).scalar()
    record = {"tenant_id": str(command.tenant_id), "request_id": str(command.item),
              "workflow_id": run_workflow_id(str(command.tenant_id), str(command.item)),
              "start_request_id": None if start is None else str(start)}  # fmt: skip
    if any(key not in given or given[key] != value for key, value in record.items()):
        return EVIDENCE_MISSING
    response = given.get("temporal_response")
    if not isinstance(response, dict) or not all(isinstance(response.get(k), str) and response[k].strip()
                                                 for k in RESPONSE):  # fmt: skip
        return EVIDENCE_MISSING
    rationale = given.get("rationale")
    return None if isinstance(rationale, str) and rationale.strip() else EVIDENCE_MISSING


async def _abandon_start(s: AsyncSession, command: Command, answer: Answer) -> str | None:
    """The request `dead` (`start_abandoned`), its run failed, its reason moved; its blocker, its evidence and its keys
    untouched. Both Temporal responses, the operator's and the leader's, audited."""
    ended = await s.execute(text("update run_requests set status = 'dead', reason = :r, "
                                 "ended_at = statement_timestamp() where id = :i and status = 'starting' returning id"),
                            {"r": START_ABANDONED, "i": command.item})  # fmt: skip
    if ended.first() is None:
        return None
    await runs.finish_run(s, command.item, status="failed", ended_at=datetime.now(UTC), error_code=START_ABANDONED,
                          error_message=START_ABANDONED_MESSAGE, if_running=True)  # fmt: skip
    await recovery.noted(s, command.tenant_id, recovery.START_ABANDONED, command.item)
    await audit.record(s, tenant_id=command.tenant_id, actor_id=command.actor_id, action="operator.command.abandoned",
                       target_type="operator_command", target_id=str(command.id),
                       details={"operator_response": json.loads(command.evidence)["temporal_response"],
                                "leader_response": answer.observed})  # fmt: skip
    return START_ABANDONED


_RELEASE_EXACT = text("select item_id, kind, result from work_failures_release_exact(:c)")
_CONFIRMING = text("select login from operator_confirmations where command_id = :c")


async def _release_exact(s: AsyncSession, command: Command, _answer: Answer) -> str | None:
    """The holds the command showed, released exactly; each one's result audited, `AUDITED_IDS` an entry, naming the
    operator and the login that confirmed it."""
    found = (await s.execute(_RELEASE_EXACT, {"c": command.id})).all()
    if not found:  # no snapshot to act on: nothing changes
        return None
    login = (await s.execute(_CONFIRMING, {"c": command.id})).scalar()
    results = [{"item_id": str(item), "kind": kind, "result": result} for item, kind, result in found]
    parts = [results[n : n + AUDITED_IDS] for n in range(0, len(results), AUDITED_IDS)]
    for n, part in enumerate(parts, start=1):
        await audit.record(s, tenant_id=command.tenant_id, actor_id=command.actor_id,
                           action="operator.command.released", target_type="operator_command",
                           target_id=str(command.id),
                           details={"login": login, "part": n, "parts": len(parts), "results": part})  # fmt: skip
    return HOLDS_RELEASED


APPLIED = {
    "record_lost_run": _record_lost_run,
    "record_lost_subrun": _record_lost_subrun,
    "release_lost_slot": _release_lost_slot,
    "settle_ended": _settle_ended,
    "release_held": _release_exact,
    "release_held_many": _release_exact,
    "abandon_start": _abandon_start,
}
