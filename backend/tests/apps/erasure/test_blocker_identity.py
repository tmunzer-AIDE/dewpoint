# SPDX-License-Identifier: Apache-2.0
"""A blocker's execution at step 60 (2b-4b M4 recovery, task 13; design revision 6 §6): before the erasure terminates
or deletes an execution whose workflow id has a blocker, it reads the identity, the request id on the started event of
the chain's first run, whichever run was sighted, and compares it with the blocker's recorded start request id.

- A match identifies the blocker with that first run. Once that run is deleted and read back, the blocker is `gone`:
  deleted with its sends, its record (the late start's included) audited in that transaction (the owner's gate-B
  condition), and its workflow's known row `gone` with it. With a send still open, it's `deleted_open`.
- A mismatch, or an identity that can't be read: alerted, the blocker unchanged, the execution still deleted (it's the
  tenant's), the known row tied to the blocker left `absent`.
- A read that fails this time deletes nothing: the stage fails, and is tried again."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from sqlalchemy import text
from temporalio.api.enums.v1 import EventType
from temporalio.api.workflow.v1 import RequestIdInfo
from temporalio.api.workflowservice.v1 import DescribeWorkflowExecutionResponse
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import start_call
from dewpoint.apps.erasure import stages, temporal
from tests.apps.erasure.fake_temporal import FakeTemporal
from tests.apps.erasure.test_provenance import _ctx, _erasing, _known

LATE_AT = datetime(2026, 10, 1, tzinfo=UTC)


async def _blocker(owner: Any, tenant_id: uuid.UUID, *, state: str = "pending", identified: str | None = None,
                   open_send: bool = False, late_start: str | None = None, legacy: bool = False
                   ) -> tuple[str, uuid.UUID, uuid.UUID]:  # fmt: skip
    """A blocker of the tenant with one send, answered or open: (its root's workflow id, its request, its recorded start
    request id)."""
    request_id, start_request_id = uuid.uuid4(), uuid.uuid4()
    workflow_id = f"t:{tenant_id}:run:{request_id}"
    async with owner() as s, s.begin():
        await s.execute(text("insert into unresolved_sends (request_id, tenant_id, workflow_id, start_request_id, "
                             "state, identified_run_id, late_start, late_start_at, legacy_unknown) "
                             "values (:r, :t, :w, :s, :st, :i, :l, :la, :lg)"),
                        {"r": request_id, "t": tenant_id, "w": workflow_id, "s": start_request_id, "st": state,
                         "i": identified, "l": late_start, "la": LATE_AT if late_start else None,
                         "lg": legacy})  # fmt: skip
        await s.execute(text("insert into start_sends (request_id, attempt, answer, answered_at) values (:r, 1, :a, "
                             ":at)"), {"r": request_id, "a": None if open_send else "already_started",
                                       "at": None if open_send else LATE_AT})  # fmt: skip
    return workflow_id, request_id, start_request_id


async def _row(owner: Any, request_id: uuid.UUID) -> tuple[Any, ...] | None:
    """The blocker's (state, identified run, last change), None once it's gone."""
    async with owner() as s:
        found = await s.execute(text("select state, identified_run_id, changed_at from unresolved_sends "
                                     "where request_id = :r"), {"r": request_id})  # fmt: skip
        row = found.first()
        return tuple(row) if row is not None else None


async def _sends(owner: Any, request_id: uuid.UUID) -> int:
    async with owner() as s:
        found = await s.execute(text("select count(*) from start_sends where request_id = :r"), {"r": request_id})
        return int(found.scalar_one())


async def _audited(owner: Any, request_id: uuid.UUID) -> list[dict[str, Any]]:
    async with owner() as s:
        found = await s.execute(text("select details from audit_log where action = 'run.request.start_gone' "
                                     "and target_id = :r order by seq"), {"r": str(request_id)})  # fmt: skip
        return list(found.scalars())


async def test_a_match_with_no_send_open_is_gone_with_its_sends_and_its_record_audited(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    w, request_id, rid = await _blocker(owner_sessionmaker, t)
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", open=True, request_id=str(rid))
    ctx = _ctx(retention_sessionmaker, t)
    assert await stages.executions(ctx) is False
    assert (await _row(owner_sessionmaker, request_id) or ())[:2] == ("identified", "r1")  # before the read-back
    assert await _known(owner_sessionmaker, t) == {("execution", w, None): "absent"}
    assert await stages.executions(ctx) is True
    assert await _row(owner_sessionmaker, request_id) is None
    assert await _sends(owner_sessionmaker, request_id) == 0
    assert await _known(owner_sessionmaker, t) == {("execution", w, None): "gone", ("execution", w, "r1"): "gone"}
    assert await _audited(owner_sessionmaker, request_id) == [
        {"run_id": "r1", "start_request_id": str(rid), "late_start": None, "late_start_at": None}
    ]


async def test_a_late_starts_record_is_audited_as_its_blocker_is_deleted(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """The owner's gate-B condition: the late start's record (0055), kept only on its blocker, outlives it."""
    t = await _erasing(owner_sessionmaker)
    w, request_id, rid = await _blocker(owner_sessionmaker, t, state="identified", identified="r1",
                                        late_start="matched")  # fmt: skip
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", request_id=str(rid))
    ctx = _ctx(retention_sessionmaker, t)
    for _ in range(2):
        await stages.executions(ctx)
    assert await _row(owner_sessionmaker, request_id) is None
    assert [c for c in fake.calls if c[0] == "identity"] == []  # identified already: not read again
    assert await _audited(owner_sessionmaker, request_id) == [
        {"run_id": "r1", "start_request_id": str(rid), "late_start": "matched", "late_start_at": LATE_AT.isoformat()}
    ]


async def test_a_match_with_a_send_open_is_deleted_open(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    w, request_id, rid = await _blocker(owner_sessionmaker, t, open_send=True)
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", request_id=str(rid))
    ctx = _ctx(retention_sessionmaker, t)
    for _ in range(2):
        await stages.executions(ctx)
    assert (await _row(owner_sessionmaker, request_id) or ())[:2] == ("deleted_open", "r1")
    assert await _sends(owner_sessionmaker, request_id) == 1
    assert await _known(owner_sessionmaker, t) == {("execution", w, None): "absent", ("execution", w, "r1"): "gone"}
    assert await _audited(owner_sessionmaker, request_id) == []


async def test_a_blockers_id_alone_reached_after_its_run_was_deleted_is_resolved_with_it(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """Visibility lists the run first, so its item precedes the blocker's id alone: deleted before that id is
    described, the id answers NOT_FOUND. Its run was shown and deleted, so it's read back, never `absent` for good (the
    final review's finding 1)."""
    t = await _erasing(owner_sessionmaker)
    w, request_id, rid = await _blocker(owner_sessionmaker, t)
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", request_id=str(rid))
    fake.visible.append((w, "r1"))
    ctx = _ctx(retention_sessionmaker, t)
    for _ in range(3):
        await stages.executions(ctx)
    async with owner_sessionmaker() as s:
        states = (await s.execute(text("select workflow_id, run_id, state from tenant_erasure_items "
                                       "where tenant_id = :t order by id"), {"t": t})).all()  # fmt: skip
        unresolved = (await s.execute(text("select erasure_unresolved(:t)"), {"t": t})).scalar_one()
    assert [tuple(r) for r in states] == [(w, "r1", "verified"), (w, None, "verified")]
    assert await _row(owner_sessionmaker, request_id) is None
    assert unresolved == 0


async def test_a_legacy_unknown_blocker_stays_identified_once_its_run_is_gone(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """Never removed (ruling 1), and no send open to keep it `deleted_open`: `identified`, an operator's abandonment."""
    t = await _erasing(owner_sessionmaker)
    w, request_id, rid = await _blocker(owner_sessionmaker, t, state="identified", identified="r1", legacy=True)
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", request_id=str(rid))
    ctx = _ctx(retention_sessionmaker, t)
    for _ in range(2):
        await stages.executions(ctx)
    assert (await _row(owner_sessionmaker, request_id) or ())[:2] == ("identified", "r1")
    assert await _known(owner_sessionmaker, t) == {("execution", w, None): "absent", ("execution", w, "r1"): "gone"}
    assert await _audited(owner_sessionmaker, request_id) == []


async def test_only_the_identified_runs_read_back_makes_its_blocker_gone(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    w, request_id, rid = await _blocker(owner_sessionmaker, t, state="identified", identified="r1")
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", request_id=str(rid))
    fake.add(w, "r2")
    fake.sticky.add((w, "r1"))  # its deletion not read back yet; the later run's is
    ctx = _ctx(retention_sessionmaker, t)
    for _ in range(3):
        await stages.executions(ctx)
    assert ("execution", w, "r2") in await _known(owner_sessionmaker, t)
    assert (await _row(owner_sessionmaker, request_id) or ())[:2] == ("identified", "r1")
    fake.sticky.clear()
    await stages.executions(ctx)  # deleted again, if it's still there
    await stages.executions(ctx)
    assert await _row(owner_sessionmaker, request_id) is None


@pytest.mark.parametrize(("started_with", "alert"), [("another", "start_identity_mismatch"),
                                                      (None, "start_identity_unread")])  # fmt: skip
async def test_a_mismatch_or_an_unread_identity_is_alerted_moves_nothing_and_the_execution_is_still_deleted(
    owner_sessionmaker, retention_sessionmaker, monkeypatch, started_with: str | None, alert: str
) -> None:
    t = await _erasing(owner_sessionmaker)
    w, request_id, _ = await _blocker(owner_sessionmaker, t)
    before = await _row(owner_sessionmaker, request_id)
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", open=True, request_id=None if started_with is None else str(uuid.uuid4()))
    ctx = _ctx(retention_sessionmaker, t)
    with structlog.testing.capture_logs() as logs:
        for _ in range(2):
            done = await stages.executions(ctx)
    assert done is True  # every item verified: the execution was deleted and read back
    assert ("delete", w, "r1") in fake.calls
    assert await _row(owner_sessionmaker, request_id) == before  # its state, its identified run, its last change
    assert await _known(owner_sessionmaker, t) == {("execution", w, None): "absent", ("execution", w, "r1"): "gone"}
    assert [(e["event"], e["tenant"], e["request_id"]) for e in logs if e["log_level"] == "error"] == [
        (alert, str(t), str(request_id))
    ]


async def test_a_later_run_is_identified_from_its_chains_first_run(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    w, request_id, rid = await _blocker(owner_sessionmaker, t)
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", request_id=str(rid))
    fake.add(w, "r2", open=True)  # the run it continued as, the one sighted
    await stages.executions(ctx := _ctx(retention_sessionmaker, t))
    assert [c for c in fake.calls if c[0] == "identity"] == [("identity", w, "r2")]
    assert (await _row(owner_sessionmaker, request_id) or ())[:2] == ("identified", "r1")
    for _ in range(2):
        await stages.executions(ctx)
    assert await _row(owner_sessionmaker, request_id) is None


async def test_the_identity_is_read_before_the_execution_is_terminated_or_deleted(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t = await _erasing(owner_sessionmaker)
    w, _, rid = await _blocker(owner_sessionmaker, t)
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", open=True, request_id=str(rid))
    await stages.executions(_ctx(retention_sessionmaker, t))
    assert [c[0] for c in fake.calls if c[1:] == (w, "r1")] == ["describe", "identity", "terminate", "read", "delete"]


async def test_an_identity_read_that_fails_deletes_nothing(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    """Unanswered this time is not unreadable: a deletion would lose the identity for good. The stage fails and backs
    off (`temporal_failed`); the next pass reads again."""
    t = await _erasing(owner_sessionmaker)
    w, request_id, rid = await _blocker(owner_sessionmaker, t)
    fake = FakeTemporal().install(monkeypatch)
    fake.add(w, "r1", open=True, request_id=str(rid))
    fake.unanswered = RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")
    with pytest.raises(RPCError):
        await stages.executions(_ctx(retention_sessionmaker, t))
    assert [c for c in fake.calls if c[0] in ("terminate", "delete")] == []
    assert (await _row(owner_sessionmaker, request_id) or ())[:2] == ("pending", None)


async def test_each_blocker_of_the_tenant_is_an_item_and_an_absent_known_row(
    owner_sessionmaker, retention_sessionmaker, monkeypatch
) -> None:
    t, other = await _erasing(owner_sessionmaker), await _erasing(owner_sessionmaker)
    w, _, _ = await _blocker(owner_sessionmaker, t, state="unresolved")
    await _blocker(owner_sessionmaker, other)
    FakeTemporal().install(monkeypatch)  # Temporal never shows it
    assert await stages.executions(_ctx(retention_sessionmaker, t)) is True  # settled; what's unresolved holds it
    async with owner_sessionmaker() as s:
        items = (await s.execute(text("select workflow_id, run_id, source, state from tenant_erasure_items "
                                      "where tenant_id = :t and step = 60"), {"t": t})).all()  # fmt: skip
        unresolved = (await s.execute(text("select erasure_unresolved(:t)"), {"t": t})).scalar_one()
    assert [tuple(i) for i in items] == [(w, None, "blocker", "absent")]
    assert await _known(owner_sessionmaker, t) == {("execution", w, None): "absent"}
    assert unresolved == 3  # its known row, its item, the blocker itself


# --- the identity read itself ---------------------------------------------------------------------------------------


STARTED = EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
UPDATED = EventType.EVENT_TYPE_WORKFLOW_EXECUTION_OPTIONS_UPDATED


def _described(run_id: str, first_run_id: str, infos: dict[str, int]) -> DescribeWorkflowExecutionResponse:
    response = DescribeWorkflowExecutionResponse()
    response.workflow_execution_info.execution.run_id = run_id
    response.workflow_execution_info.first_run_id = first_run_id
    for request_id, event_type in infos.items():
        response.workflow_extended_info.request_id_infos[request_id].CopyFrom(RequestIdInfo(event_type=event_type))
    return response


class _Service:
    """Describes answered by run id: a response, or what it raises."""

    def __init__(self, by_run: dict[str, DescribeWorkflowExecutionResponse | Exception]) -> None:
        self.by_run, self.asked = by_run, list[str]()

    async def describe_workflow_execution(self, req: Any, **_: Any) -> DescribeWorkflowExecutionResponse:
        self.asked.append(req.execution.run_id)
        answer = self.by_run[req.execution.run_id]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _client(service: _Service) -> Any:
    return SimpleNamespace(workflow_service=service, namespace="default")


async def test_the_identity_is_the_first_runs_started_request_id_whichever_run_is_named() -> None:
    rid, own = str(uuid.uuid4()), str(uuid.uuid4())
    later = _Service({"r2": _described("r2", "r1", {own: STARTED}), "r1": _described("r1", "r1", {rid: STARTED})})
    assert await temporal.first_run_request_id(_client(later), "w", "r2") == temporal.FirstRun("r1", rid)
    assert later.asked == ["r2", "r1"]
    first = _Service({"r1": _described("r1", "r1", {rid: STARTED, own: UPDATED})})
    assert await temporal.first_run_request_id(_client(first), "w", "r1") == temporal.FirstRun("r1", rid)
    assert first.asked == ["r1"]


async def test_a_first_run_gone_or_without_a_started_request_id_is_unreadable_and_a_failure_is_raised() -> None:
    gone = RPCError("gone", RPCStatusCode.NOT_FOUND, b"")
    assert await temporal.first_run_request_id(
        _client(_Service({"r2": _described("r2", "r1", {}), "r1": gone})), "w", "r2"
    ) is None  # fmt: skip
    attached = _Service({"r1": _described("r1", "r1", {str(uuid.uuid4()): UPDATED})})  # on another event only
    assert await temporal.first_run_request_id(_client(attached), "w", "r1") is None
    unavailable = RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")
    with pytest.raises(RPCError):
        await temporal.first_run_request_id(_client(_Service({"r1": unavailable})), "w", "r1")


async def test_on_the_dev_server_the_first_runs_request_id_is_read(server) -> None:
    client = server.client
    start_call.install(client)  # a start carries a given request id only within `sending`
    rid, workflow_id = uuid.uuid4(), f"t:{uuid.uuid4()}:run:{uuid.uuid4()}"
    with start_call.sending(rid):
        handle = await client.start_workflow("Unserved", id=workflow_id, task_queue="erasure-unserved")
    run = str(handle.first_execution_run_id)
    assert await temporal.first_run_request_id(client, workflow_id, run) == temporal.FirstRun(run, str(rid))
    await handle.terminate()
