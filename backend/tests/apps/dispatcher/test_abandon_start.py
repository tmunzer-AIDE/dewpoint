# SPDX-License-Identifier: Apache-2.0
"""`abandon_start` (2b-4b M4 recovery, task 10; design revisions 2 and 3, ruling 4; the correction: abandoning a start
ends the request, never its send). On a request left unresolved (`starting`, spent, an attempt unproven, its
`start_unresolved` recorded), confirmed by its operator, with structured evidence: the identifiers, each equal to the
record's; the exact Temporal response the operator saw, with its time; their rationale (a visibility result may be
attached, never proof). The leader asks Temporal itself: only `absent` goes on, and its own response and time are
recorded with the operator's. Then, in one conditional transaction: the request `dead` (`start_abandoned`), its run
failed with the ruled message, `start_unresolved` moved to `start_abandoned`; the blocker, the evidence and the keys
untouched, and the start check refusing any further start of it."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCStatusCode

from dewpoint.apps.dispatcher import commands
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.support import reasons
from tests.apps.dispatcher.test_blocker_store import store
from tests.apps.dispatcher.test_commands import GONE, decided, operator
from tests.apps.dispatcher.test_reconcile import DescribeFails
from tests.apps.dispatcher.test_reconcile_runs import Described
from tests.apps.dispatcher.test_unresolved_requests import _spent_unresolved
from tests.apps.test_runs import rpc
from tests.support.recovery import confirmed_by_actor

pytestmark = pytest.mark.usefixtures("development_deployment")
RATIONALE = "Past the namespace's retention, and no execution under its id: checked in the Temporal UI."


async def _unresolved(owner: Any, dsm: Any, settings: Any, request: Any) -> dict[str, Any]:
    """The request left unresolved, as the record shows it."""
    await _spent_unresolved(owner, dsm, settings, request)
    async with owner() as s:
        row = (await s.execute(text("select q.tenant_id, q.id, q.start_request_id, i.since from run_requests q "
                                    "join recovery_items i on i.item_id = q.id and i.reason = 'start_unresolved' "
                                    "where q.id = :i"), {"i": request.id})).one()  # fmt: skip
    return {"tenant_id": row.tenant_id, "request_id": row.id, "start_request_id": row.start_request_id,
            "since": row.since}  # fmt: skip


def evidence(record: dict[str, Any], *, without: str | None = None, **changed: Any) -> str:
    """The operator's structured evidence, as the API records it (canonical JSON), `without` a field (`a.b` for a
    nested one), or with fields `changed`."""
    fields: dict[str, Any] = {
        "tenant_id": str(record["tenant_id"]),
        "request_id": str(record["request_id"]),
        "workflow_id": run_workflow_id(str(record["tenant_id"]), str(record["request_id"])),
        "start_request_id": str(record["start_request_id"]),
        "temporal_response": {"call": "DescribeWorkflowExecution", "status": "NOT_FOUND",
                              "message": "workflow execution not found", "observed_at": "2026-10-11T10:00:00+00:00"},
        "rationale": RATIONALE,
        **changed,
    }  # fmt: skip
    if without is not None:
        outer, _, inner = without.partition(".")
        if inner:
            del fields[outer][inner]
        else:
            del fields[outer]
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


async def asked(owner: Any, record: dict[str, Any], actor: uuid.UUID, given: str, *,
                confirmed: bool = True) -> uuid.UUID:  # fmt: skip
    async with owner() as s, s.begin():
        command = (await s.execute(text(
            "insert into operator_commands (tenant_id, kind, item_id, reason, incident_since, actor_id, "
            "idempotency_key, evidence) values (:t, 'abandon_start', :i, 'start_unresolved', :since, :u, :k, :e) "
            "returning id"),
            {"t": record["tenant_id"], "i": record["request_id"], "since": record["since"], "u": actor,
             "k": uuid.uuid4().hex, "e": given})).scalar_one()  # fmt: skip
    if confirmed:
        await confirmed_by_actor(owner, command, actor)
    return command


async def _request(owner: Any, request_id: uuid.UUID) -> tuple[Any, ...]:
    async with owner() as s:
        return tuple((await s.execute(text(
            "select q.status, q.reason, u.status, u.error_code, u.error_message from run_requests q "
            "join runs u on u.id = q.id where q.id = :i"), {"i": request_id})).one())  # fmt: skip


async def _kept(owner: Any, request_id: uuid.UUID, workflow_id: str) -> tuple[Any, ...]:
    """What abandonment never touches: the blocker and its sends, the execution's evidence."""
    async with owner() as s:
        found = await s.execute(text("select to_jsonb(e)::text from execution_evidence e where workflow_id = :w"),
                                {"w": workflow_id})  # fmt: skip
        return await store(owner, request_id), [tuple(r) for r in found]


async def test_an_abandoned_start_ends_its_request_and_never_its_send(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    record = await _unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    workflow_id = run_workflow_id(str(request.tenant_id), str(request.id))
    before = await _kept(owner_sessionmaker, request.id, workflow_id)
    admin = await operator(owner_sessionmaker)
    command = await asked(owner_sessionmaker, record, admin, evidence(record))
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.START_ABANDONED: 1}
    assert await decided(owner_sessionmaker, command) == ("applied", commands.START_ABANDONED, True)
    assert await _request(owner_sessionmaker, request.id) == (
        "dead", "start_abandoned", "failed", "start_abandoned", commands.START_ABANDONED_MESSAGE)  # fmt: skip
    assert set(await reasons(owner_sessionmaker, request.id)) == {"start_abandoned"}  # start_unresolved, moved
    assert await _kept(owner_sessionmaker, request.id, workflow_id) == before  # blocker, sends and evidence untouched
    async with owner_sessionmaker() as s:
        responses = (await s.execute(text("select actor_id, details from audit_log where action = "
                                          "'operator.command.abandoned' and target_id = :c"),
                                     {"c": str(command)})).all()  # fmt: skip
        permitted = (await s.execute(text("select start_permitted(:w, :r)"),
                                     {"w": workflow_id,
                                      "r": str(record["start_request_id"])})).scalar_one()  # fmt: skip
    [(actor, details)] = responses
    assert actor == admin and details["operator_response"]["status"] == "NOT_FOUND"
    assert details["leader_response"]["status"] == "NOT_FOUND" and details["leader_response"]["observed_at"]
    assert permitted is False  # the start check refuses any further start of it


async def test_the_abandoned_record_outlives_the_settled_entries_clearing(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """`work_settled_clear` keeps a reason only while its item is live: `start_abandoned` is an operator's record, kept
    whatever its request's state (its request is dead)."""
    _, _, request = queued
    record = await _unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    admin = await operator(owner_sessionmaker)
    await asked(owner_sessionmaker, record, admin, evidence(record))
    await commands.commands_once(dispatch_sessionmaker, GONE)
    async with dispatch_sessionmaker() as s, s.begin():
        await s.execute(text("select work_settled_clear(100)"))
    assert set(await reasons(owner_sessionmaker, request.id)) == {"start_abandoned"}


REFUSED = {  # how Temporal answers, or what changed: the refusal
    "unauthorized": (GONE, commands.UNAUTHORIZED),
    "stale": (GONE, commands.STALE),
    "changed": (GONE, commands.CHANGED),
    "execution_live": (Described(WorkflowExecutionStatus.RUNNING), commands.EXECUTION_LIVE),
    "execution_present": (Described(WorkflowExecutionStatus.COMPLETED), commands.EXECUTION_PRESENT),
    "temporal_uncertain": (DescribeFails(rpc(RPCStatusCode.NOT_FOUND), namespace_error=rpc(RPCStatusCode.UNAVAILABLE)),
                           commands.TEMPORAL_UNCERTAIN),
}  # fmt: skip


@pytest.mark.parametrize("case", REFUSED)
async def test_an_abandonment_that_cant_be_carried_out_safely_is_refused_changing_nothing(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, case: str
) -> None:
    _, _, request = queued
    record = await _unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    admin = await operator(owner_sessionmaker)
    command = await asked(owner_sessionmaker, record, admin, evidence(record))
    async with owner_sessionmaker() as s, s.begin():
        if case == "unauthorized":
            await s.execute(text("update users set is_platform_admin = false where id = :u"), {"u": admin})
        elif case == "stale":
            await s.execute(text("delete from recovery_items where item_id = :i"), {"i": request.id})
        elif case == "changed":  # ended meanwhile, its reason still recorded
            await s.execute(text("update run_requests set status = 'dead', reason = 'refused', ended_at = now() "
                                 "where id = :i"), {"i": request.id})  # fmt: skip
    client, outcome = REFUSED[case]
    before = await _request(owner_sessionmaker, request.id)
    assert await commands.commands_once(dispatch_sessionmaker, client) == {outcome: 1}
    assert await decided(owner_sessionmaker, command) == ("refused", outcome, True)
    assert await _request(owner_sessionmaker, request.id) == before


EVIDENCE = {  # each structured field missing, or an identifier not the record's
    **{f"no {f}": {"without": f} for f in ("tenant_id", "request_id", "workflow_id", "start_request_id", "rationale",
                                           "temporal_response", "temporal_response.call", "temporal_response.status",
                                           "temporal_response.message", "temporal_response.observed_at")},
    **{f"another {f}": {f: v} for f, v in (("tenant_id", str(uuid.uuid4())), ("request_id", str(uuid.uuid4())),
                                           ("workflow_id", "t:x:run:y"), ("start_request_id", str(uuid.uuid4())))},
    "an empty rationale": {"rationale": "  "},
}  # fmt: skip


@pytest.mark.parametrize("case", [*EVIDENCE, "not JSON"])
async def test_evidence_missing_or_not_the_records_is_refused(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, case: str
) -> None:
    _, _, request = queued
    record = await _unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    admin = await operator(owner_sessionmaker)
    given = "checked in the UI" if case == "not JSON" else evidence(record, **EVIDENCE[case])
    command = await asked(owner_sessionmaker, record, admin, given)
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.EVIDENCE_MISSING: 1}
    assert await decided(owner_sessionmaker, command) == ("refused", commands.EVIDENCE_MISSING, True)
    assert (await _request(owner_sessionmaker, request.id))[0] == "starting"


async def test_an_abandonment_no_one_confirmed_is_refused_unconfirmed_once_its_hour_has_passed(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    record = await _unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    command = await asked(owner_sessionmaker, record, await operator(owner_sessionmaker), evidence(record),
                          confirmed=False)  # fmt: skip
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {}
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update operator_commands set requested_at = :t where id = :c"),
                        {"t": datetime.now(UTC) - timedelta(hours=1, seconds=1), "c": command})  # fmt: skip
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.UNCONFIRMED: 1}
    assert (await _request(owner_sessionmaker, request.id))[0] == "starting"


# --- the API ---------------------------------------------------------------------------------------------------------


async def test_the_api_records_an_abandonment_with_its_evidence_structured_and_canonical(
    app, owner_sessionmaker, api_settings, queued, dispatch_sessionmaker
) -> None:
    from tests.apps.api.test_erasure_api import admin_of
    from tests.apps.api.test_recovery_api import url

    _, _, request = queued
    record = await _unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    admin, _ = await admin_of(app, owner_sessionmaker, api_settings)
    structured = json.loads(evidence(record))
    asked_for = {"kind": "abandon_start", "item_id": str(request.id), "idempotency_key": "abandon-1"}
    async with admin:
        missing = await admin.post(url(record["tenant_id"], "commands"), json=asked_for)
        assert (missing.status_code, missing.json()) == (422, {"error": "evidence_required"})
        made = await admin.post(url(record["tenant_id"], "commands"), json=asked_for | {"abandon": structured})
        assert made.status_code == 202, made.json()
    async with owner_sessionmaker() as s:
        stored = (await s.execute(text("select evidence from operator_commands where id = :c"),
                                  {"c": made.json()["id"]})).scalar_one()  # fmt: skip
    kept = json.loads(stored)
    assert stored == json.dumps(kept, sort_keys=True, separators=(",", ":"))  # canonical
    seen, given = kept["temporal_response"].pop("observed_at"), structured["temporal_response"].pop("observed_at")
    assert kept == structured and datetime.fromisoformat(seen) == datetime.fromisoformat(given)


# --- the erasure (the owner's review of gate C, finding 1) -----------------------------------------------------------


async def test_an_abandonment_still_pending_when_its_tenants_erasure_reaches_stage_60_is_refused_unchanged(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Asked and confirmed while the tenant was active, still pending into its erasure's stage 60, where the fence
    refuses the `start_abandoned` record: refused, the request and its reasons as they were (the API refuses a command
    for a tenant that isn't active; so does the leader, under the tenant's lock)."""
    from tests.core.erasure.test_fence import erasure_at

    _, _, request = queued
    record = await _unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    admin = await operator(owner_sessionmaker)
    command = await asked(owner_sessionmaker, record, admin, evidence(record))
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": record["tenant_id"]})
    await erasure_at(owner_sessionmaker, record["tenant_id"], 60)
    before = (await _request(owner_sessionmaker, request.id), set(await reasons(owner_sessionmaker, request.id)))
    assert await commands.commands_once(dispatch_sessionmaker, GONE) == {commands.TENANT_ERASING: 1}
    assert await decided(owner_sessionmaker, command) == ("refused", commands.TENANT_ERASING, True)
    after = (await _request(owner_sessionmaker, request.id), set(await reasons(owner_sessionmaker, request.id)))
    assert after == before and before[1] == {"start_unresolved"}


async def test_an_erasure_beginning_while_an_abandonment_is_applied_waits_for_its_record(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    """The leader applies under the tenant's lifecycle lock, shared, as the API's change does: an erasure's step (its
    lock, exclusively) waits for the abandonment to commit, so its record is in before any fence, never lost."""
    import asyncio

    from dewpoint.core.tenancy import lifecycle
    from tests.core.erasure.test_fence import _waiting

    _, _, request = queued
    record = await _unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, request)
    admin = await operator(owner_sessionmaker)
    await asked(owner_sessionmaker, record, admin, evidence(record))
    original, reached, go = commands.APPLIED["abandon_start"], asyncio.Event(), asyncio.Event()

    async def paused(s: Any, command: Any, answer: Any) -> Any:  # mid-apply, its transaction open
        reached.set()
        await go.wait()
        return await original(s, command, answer)

    monkeypatch.setitem(commands.APPLIED, "abandon_start", paused)
    leading = asyncio.create_task(commands.commands_once(dispatch_sessionmaker, GONE))
    await reached.wait()

    async def erasing() -> None:  # its step 1 and, all at once, its fence: what a stalled transaction would race
        async with owner_sessionmaker() as s, s.begin():
            await lifecycle.hold_exclusive(s, record["tenant_id"])
            await s.execute(text("update tenants set status = 'erasing' where id = :t"), {"t": record["tenant_id"]})
            await s.execute(text("insert into tenant_erasures (tenant_id, requested_by, step, fenced_at) "
                                 "values (:t, gen_random_uuid(), 60, now())"), {"t": record["tenant_id"]})  # fmt: skip

    erasure = asyncio.create_task(erasing())
    try:
        await _waiting(owner_sessionmaker)  # the erasure waits for the leader's transaction
    finally:
        go.set()
        outcome = await leading
        await erasure
    assert outcome == {commands.START_ABANDONED: 1}
    assert set(await reasons(owner_sessionmaker, request.id)) == {"start_abandoned"}  # in before the fence
