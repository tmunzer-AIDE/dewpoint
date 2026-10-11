# SPDX-License-Identifier: Apache-2.0
"""An attempt's outcome, and the cap's ends (2b-4b M4, the start-check slice; the upgrade barrier's revision 17).

D12's start check denies with one of two fixed reasons, carried in the error's `PermissionDeniedFailure` details: read
from there, never from the message. Until the reasons are confirmed end to end on D12
(`start_check_reasons_confirmed`), any `PERMISSION_DENIED` is uncertain, as is one whose reason is unknown or missing.
A certain answer concerns its own attempt only: an earlier unproven one stays unproven. At the cap (10 sends) a request
with any attempt unresolved is never ended; one whose sends all certainly created nothing ends `dead`, its reason
saying which (an unavailable check is infrastructure, never a refusal)."""

import dataclasses
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest
import structlog
from google.protobuf.any_pb2 import Any as AnyProto
from sqlalchemy import text
from temporalio.api.common.v1 import GrpcStatus
from temporalio.api.enums.v1 import EventType
from temporalio.api.errordetails.v1 import NamespaceNotFoundFailure, PermissionDeniedFailure
from temporalio.api.workflow.v1 import RequestIdInfo
from temporalio.api.workflowservice.v1 import DescribeWorkflowExecutionResponse
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps.dispatcher import dispatch, reconcile, start_call
from dewpoint.engine.runtime.activities import ENGINE_QUEUE
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.dispatcher.support import BUILD, begin, reasons
from tests.apps.dispatcher.test_reconcile import aged, once
from tests.apps.test_admission import KEYS
from tests.support.temporal import start_local

pytestmark = pytest.mark.usefixtures("development_deployment")
NOT_PERMITTED, UNAVAILABLE = "dewpoint:start-not-permitted", "dewpoint:start-check-unavailable"


def _error(status: RPCStatusCode, reason: str | None = None, detail: Any = None) -> RPCError:
    packed = []
    if reason is not None or detail is not None:
        any_ = AnyProto()
        any_.Pack(detail if detail is not None else PermissionDeniedFailure(reason=reason))
        packed.append(any_)
    raw = GrpcStatus(code=int(status), message="Request unauthorized.", details=packed).SerializeToString()
    return RPCError("Request unauthorized.", status, raw)


def test_the_reason_is_read_from_the_details_never_the_message() -> None:
    assert dispatch.deny_reason(_error(RPCStatusCode.PERMISSION_DENIED, NOT_PERMITTED)) == NOT_PERMITTED
    assert dispatch.deny_reason(_error(RPCStatusCode.PERMISSION_DENIED)) is None
    other = NamespaceNotFoundFailure(namespace="x")
    assert dispatch.deny_reason(_error(RPCStatusCode.PERMISSION_DENIED, detail=other)) is None
    worded = RPCError(f"denied: {NOT_PERMITTED}", RPCStatusCode.PERMISSION_DENIED,
                      GrpcStatus(code=7, message=f"denied: {NOT_PERMITTED}").SerializeToString())  # fmt: skip
    assert dispatch.deny_reason(worded) is None


@dataclass
class Refusing:
    """A client whose every start raises `error`."""

    error: Exception
    namespace: str = "default"

    async def start_workflow(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error


def _starting() -> dispatch.Starting:
    tenant, run = uuid.uuid4(), uuid.uuid4()
    start = dispatch.RunInput(tenant_id=str(tenant), run_id=str(run), version_id=str(uuid.uuid4()), trigger={},
                              mode="live", max_run_duration_s=60, cel_schedule_to_start_s=1.0)  # fmt: skip
    return dispatch.Starting(run, tenant, start, uuid.uuid4())


@pytest.mark.parametrize(
    ("reasons", "status", "reason", "kind"),
    [
        (False, RPCStatusCode.PERMISSION_DENIED, NOT_PERMITTED, "uncertain"),
        (False, RPCStatusCode.PERMISSION_DENIED, UNAVAILABLE, "uncertain"),
        (True, RPCStatusCode.PERMISSION_DENIED, NOT_PERMITTED, "not_permitted"),
        (True, RPCStatusCode.PERMISSION_DENIED, UNAVAILABLE, "check_unavailable"),
        (True, RPCStatusCode.PERMISSION_DENIED, "dewpoint:something-else", "uncertain"),
        (True, RPCStatusCode.PERMISSION_DENIED, None, "uncertain"),
        (True, RPCStatusCode.INVALID_ARGUMENT, None, "refused"),
        (True, RPCStatusCode.UNAVAILABLE, None, "uncertain"),
    ],
)  # fmt: skip
async def test_an_attempt_is_classified_from_its_actual_response(reasons, status, reason, kind) -> None:  # type: ignore[no-untyped-def]
    outcome = await dispatch.start(Refusing(_error(status, reason)), _starting(), reasons=reasons)  # type: ignore[arg-type]
    assert outcome.kind == kind


async def test_the_dispatcher_passes_its_setting_to_the_classification(
    queued, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    _, _, request = queued
    seen: list[bool] = []

    async def start(client: Any, starting: Any, *, reasons: bool = False) -> dispatch.Outcome:
        seen.append(reasons)
        return dispatch.Outcome("uncertain")

    monkeypatch.setattr(dispatch, "start", start)
    settings = api_settings.model_copy(update={"start_check_reasons_confirmed": True})
    seal = dispatch.sealer(dispatch_converter(), "default")
    await dispatch._dispatch(dispatch_sessionmaker, object(), seal, KEYS, settings, BUILD,  # type: ignore[arg-type]
                             request.tenant_id, request.id)  # fmt: skip
    assert seen == [True]


def dispatch_converter() -> Any:
    from dewpoint.apps.codec import data_converter

    return data_converter(KEYS)


# --- settling ------------------------------------------------------------------------------------------------------


async def _state(owner: Any, request_id: uuid.UUID) -> dict[str, Any]:
    async with owner() as s:
        row = await s.execute(text("select status, reason, attempts, sends, unavailable_sends, "
                                   "next_attempt_at > now() as later from run_requests where id = :i"),
                              {"i": request_id})  # fmt: skip
        return dict(row.mappings().one())


async def _evidence(owner: Any, request: Any) -> Any:
    async with owner() as s:
        found = await s.execute(
            text("select unproven from execution_evidence where workflow_id = :w and run_id is null"),
            {"w": run_workflow_id(str(request.tenant_id), str(request.id))},
        )
        return found.scalar()


async def _sent(owner: Any, request: Any, sends: int, *, unproven: bool = False, cancel: bool = False) -> None:
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set sends = :n, cancel_requested_at = case when :c then now() end "
                             "where id = :i"), {"n": sends, "c": cancel, "i": request.id})  # fmt: skip
        if unproven:
            await s.execute(text("update execution_evidence set unproven = true where workflow_id = :w"),
                            {"w": run_workflow_id(str(request.tenant_id), str(request.id))})  # fmt: skip


async def test_check_unavailable_backs_off_counts_its_send_and_isnt_a_refusal(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("check_unavailable")) \
        == "check_unavailable"  # fmt: skip
    state = await _state(owner_sessionmaker, request.id)
    assert (state["status"], state["attempts"], state["sends"], state["unavailable_sends"], state["later"]) == (
        "queued", 0, 1, 1, True,
    )  # fmt: skip


async def test_a_certain_answer_never_clears_an_earlier_unproven_attempt(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    await _sent(owner_sessionmaker, request, 1, unproven=True)
    await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("check_unavailable"))
    assert await _evidence(owner_sessionmaker, request) is True


async def test_not_permitted_is_a_refusal_and_a_cancelled_request_ends_cancelled(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("not_permitted")) == "refused"
    state = await _state(owner_sessionmaker, request.id)
    assert (state["status"], state["attempts"], state["later"]) == ("queued", 1, True)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set next_attempt_at = now() where id = :i"), {"i": request.id})
    again = await begin(dispatch_sessionmaker, request, api_settings)
    await _sent(owner_sessionmaker, request, 2, cancel=True)
    assert await dispatch.settle(dispatch_sessionmaker, again, dispatch.Outcome("not_permitted")) == "cancelled"


@pytest.mark.parametrize(
    ("kind", "unproven", "happened", "status", "reason"),
    [
        ("check_unavailable", False, "dead", "dead", dispatch.START_CHECK_UNAVAILABLE),
        ("check_unavailable", True, "unresolved", "starting", None),
        ("throttled", False, "dead", "dead", dispatch.START_THROTTLED),
        ("absent", False, "unresolved", "starting", None),
        ("uncertain", False, "uncertain", "starting", None),
    ],
)  # fmt: skip
async def test_at_the_cap_a_request_ends_only_when_every_send_certainly_created_nothing(  # type: ignore[no-untyped-def]
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, kind, unproven, happened, status, reason
) -> None:
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set sends = :n where id = :i"),
                        {"n": start_call.CAP - 1, "i": request.id})  # fmt: skip
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    if unproven:
        await _sent(owner_sessionmaker, request, start_call.CAP, unproven=True)
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome(kind)) == happened
    state = await _state(owner_sessionmaker, request.id)
    assert (state["status"], state["reason"], state["sends"]) == (status, reason, start_call.CAP)


# --- identity by the start request id ------------------------------------------------------------------------------


@dataclass
class Described:
    """A workflow service whose describes answer from `by_run` (the latest run under the key "")."""

    by_run: dict[str, DescribeWorkflowExecutionResponse]
    asked: list[str] = field(default_factory=list)

    async def describe_workflow_execution(self, req: Any, **kwargs: Any) -> DescribeWorkflowExecutionResponse:
        self.asked.append(req.execution.run_id)
        return self.by_run[req.execution.run_id]


@dataclass
class Client_:
    workflow_service: Described
    namespace: str = "default"


def _described(run_id: str, first_run_id: str, infos: dict[str, int]) -> DescribeWorkflowExecutionResponse:
    response = DescribeWorkflowExecutionResponse()
    response.workflow_execution_info.execution.run_id = run_id
    response.workflow_execution_info.first_run_id = first_run_id
    for request_id, event_type in infos.items():
        response.workflow_extended_info.request_id_infos[request_id].CopyFrom(RequestIdInfo(event_type=event_type))
    return response


STARTED = EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED
UPDATED = EventType.EVENT_TYPE_WORKFLOW_EXECUTION_OPTIONS_UPDATED


async def test_identity_is_the_request_id_on_the_first_runs_started_event_only() -> None:
    rid = str(uuid.uuid4())
    first = _described("first", "first", {rid: STARTED})
    assert await dispatch.started_by(Client_(Described({"": first, "first": first})), "w", rid) is not None  # type: ignore[arg-type]
    later = _described("later", "first", {rid: STARTED})  # on a later run, not the first
    first_without = _described("first", "first", {})
    assert await dispatch.started_by(Client_(Described({"": later, "first": first_without})), "w", rid) is None  # type: ignore[arg-type]
    attached = _described("first", "first", {rid: UPDATED})  # attached to another event
    assert await dispatch.started_by(Client_(Described({"": attached, "first": attached})), "w", rid) is None  # type: ignore[arg-type]
    other = _described("first", "first", {str(uuid.uuid4()): STARTED})
    assert await dispatch.started_by(Client_(Described({"": other, "first": other})), "w", rid) is None  # type: ignore[arg-type]


async def test_on_the_dev_server_a_start_is_identified_by_its_request_id() -> None:
    async with await start_local() as environment:
        client = environment.client
        start_call.install(client)
        rid, workflow_id = uuid.uuid4(), f"t:{uuid.uuid4()}:run:{uuid.uuid4()}"
        with start_call.sending(rid):
            handle = await client.start_workflow("Anything", id=workflow_id, task_queue="nowhere")
        assert await dispatch.started_by(client, workflow_id, rid) is not None
        assert await dispatch.started_by(client, workflow_id, uuid.uuid4()) is None
        await handle.terminate()
        assert await dispatch.started_by(client, workflow_id, rid) is not None  # closed, still identified


# --- the call budget's longest paths -------------------------------------------------------------------------------


@dataclass
class Counting:
    """A client whose chain has continued (its latest run isn't its first) and whose start request id matches no run:
    `verify` takes its longest path, each call counted; its history page is asked and fails (uncertain)."""

    calls: list[str] = field(default_factory=list)
    namespace: str = "default"

    @property
    def workflow_service(self) -> Any:
        return self

    async def describe_workflow_execution(self, req: Any, **kwargs: Any) -> DescribeWorkflowExecutionResponse:
        self.calls.append("describe_workflow_execution")
        return _described("latest" if not req.execution.run_id else req.execution.run_id, "first", {})

    def get_workflow_handle(self, workflow_id: str) -> Any:
        client = self

        class Handle:
            async def fetch_history_events(self, **kwargs: Any) -> Any:
                client.calls.append("get_workflow_execution_history")
                raise RuntimeError("no history here")
                yield  # an async generator

        return Handle()


async def test_verifys_longest_path_is_the_budgets() -> None:
    from dewpoint.apps.dispatcher import calls

    client = Counting()  # a recorded id: settled by its identity alone, never by the payload
    assert (await dispatch.verify(client, _starting())).kind == "uncertain"  # type: ignore[arg-type]
    assert client.calls == ["describe_workflow_execution", "describe_workflow_execution"]
    legacy = Counting()  # none recorded (from before 0052): its payload, as before
    unrecorded = dataclasses.replace(_starting(), start_request_id=None)
    assert (await dispatch.verify(legacy, unrecorded)).kind == "uncertain"  # type: ignore[arg-type]
    assert legacy.calls == ["get_workflow_execution_history"]
    assert max(len(client.calls), len(legacy.calls)) == calls.VERIFY
    assert calls.CALLS["dispatch"] == 1 + calls.VERIFY and calls.CALLS["reconcile"] == 1 + calls.VERIFY


# --- the final review's fixes -----------------------------------------------------------------------------------------


async def test_an_unreadable_denial_carries_no_reason_and_its_attempt_is_uncertain() -> None:
    """The plan's rule: an unknown or unreadable deny reason is uncertain, never an error that leaves the attempt
    unclassified (the final review's M4)."""
    corrupt = RPCError("Request unauthorized.", RPCStatusCode.PERMISSION_DENIED, b"\xff\xff\xff")
    detail = AnyProto(type_url="type.googleapis.com/temporal.api.errordetails.v1.PermissionDeniedFailure",
                      value=b"\xff\xff")  # fmt: skip
    garbled = RPCError("Request unauthorized.", RPCStatusCode.PERMISSION_DENIED,
                       GrpcStatus(code=7, details=[detail]).SerializeToString())  # fmt: skip
    for error in (corrupt, garbled):
        assert dispatch.deny_reason(error) is None
        assert (await dispatch.start(Refusing(error), _starting(), reasons=True)).kind == "uncertain"  # type: ignore[arg-type]


async def test_a_request_with_a_recorded_id_is_settled_by_it_alone_never_by_its_payload(
    queued, dispatch_sessionmaker, api_settings, env
) -> None:
    """Revision 17's table and the plan: "already started" for a request with a recorded start request id is settled
    only by that id on its first run's started event. An execution started under another id stays uncertain, its
    payload the request's own or not; only a request from before 0052, with no id, keeps the payload verify."""
    _, _, request = queued
    found = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(found, dispatch.Starting) and found.start_request_id is not None
    workflow_id = run_workflow_id(found.start.tenant_id, found.start.run_id)
    handle = await env.client.start_workflow(RunGraph.run, found.start, id=workflow_id, task_queue=ENGINE_QUEUE)
    try:  # started under the SDK's own request id, not the recorded one
        assert (await dispatch.verify(env.client, found)).kind == "uncertain"
        legacy = dataclasses.replace(found, start_request_id=None)
        assert (await dispatch.verify(env.client, legacy)).kind == "started"
    finally:
        await handle.terminate()


async def _not_permitted_before(owner: Any, request: Any, n: int) -> None:
    """`n` earlier sends, each denied "not permitted": refusals, and the start check's."""
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set sends = :n, attempts = :n, not_permitted_sends = :n "
                             "where id = :i"), {"n": n, "i": request.id})  # fmt: skip


async def _end(owner: Any, request_id: uuid.UUID) -> tuple[Any, ...]:
    async with owner() as s:
        found = await s.execute(text("select q.status, q.reason, u.error_message from run_requests q "
                                     "join runs u on u.id = q.id where q.id = :i"), {"i": request_id})  # fmt: skip
        return tuple(found.one())


ALERTS = ("start_not_permitted", "start_integrity_failure")


def _refused_by_the_check() -> tuple[str, str, str]:
    return "dead", dispatch.START_REFUSED, dispatch.NOT_PERMITTED_MESSAGE


def _alerts(seen: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(e["event"], e["log_level"]) for e in seen if e["event"] in ALERTS]


async def test_refusals_by_the_start_check_end_dead_and_alerted_as_an_integrity_failure(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Revision 17, section 2: a `start_refused` end that came from "not permitted" denials is alerted as an integrity
    failure, the request not cancelled, its message naming the start check (never Temporal); each such denial is
    logged (the final review's I3)."""
    _, _, request = queued
    await _not_permitted_before(owner_sessionmaker, request, dispatch.MAX_ATTEMPTS - 1)
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    with structlog.testing.capture_logs() as seen:
        assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("not_permitted")) == "dead"
    assert await _end(owner_sessionmaker, request.id) == _refused_by_the_check()
    assert _alerts(seen) == [("start_not_permitted", "warning"), ("start_integrity_failure", "error")]


async def test_at_the_cap_earlier_not_permitted_sends_keep_the_end_an_integrity_failure(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Nine sends denied "not permitted", the tenth throttled: every send certainly created nothing, and the end says
    the start check refused it (`start_refused`, alerted), never `start_throttled`."""
    _, _, request = queued
    await _not_permitted_before(owner_sessionmaker, request, start_call.CAP - 1)
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    with structlog.testing.capture_logs() as seen:
        assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("throttled")) == "dead"
    assert await _end(owner_sessionmaker, request.id) == _refused_by_the_check()
    assert _alerts(seen) == [("start_integrity_failure", "error")]


async def test_a_cancelled_requests_not_permitted_denial_is_expected_never_alerted(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    await _sent(owner_sessionmaker, request, 1, cancel=True)
    with structlog.testing.capture_logs() as seen:
        assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("not_permitted")) == "cancelled"
    assert _alerts(seen) == []


async def _rechecked_long_ago(owner: Any, request_id: uuid.UUID) -> None:
    """Its last look, and when it was first noted, both an hour and a second back: due again, whatever its paced gap
    (task 5: a spent request's looks double from 30 s to an hour)."""
    by = timedelta(hours=1, seconds=1)
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set checked_at = checked_at - cast(:by as interval) where id = :i"),
                        {"by": by, "i": request_id})  # fmt: skip
        await s.execute(text("update recovery_items set since = since - cast(:by as interval) where item_id = :i"),
                        {"by": by, "i": request_id})  # fmt: skip


async def _observed_twice_as_unresolved(owner: Any, dispatcher: Any, settings: Any, client: Any, request: Any) -> None:
    """Two reconciler passes, each when its look is due, each seeing the run absent: each leaves it unresolved, and none
    asks about it again before its next look."""
    await aged(owner, request.id)
    for _ in range(2):
        assert await once(dispatcher, client, settings) == {"unresolved": 1}
        assert await once(dispatcher, client, settings) == {}  # paced
        await _rechecked_long_ago(owner, request.id)
    assert (await _state(owner, request.id))["status"] == "starting"
    assert set(await reasons(owner, request.id)) == {"start_unresolved"}  # never start_history_missing


async def test_an_unresolved_start_at_the_cap_stays_unresolved_however_often_it_is_seen_absent(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """The final review's I1: its sends spent with an attempt unproven, a request stays `starting` without a slot; an
    absence the reconciler sees later leaves it unresolved, never `start_history_missing` (which says a start happened
    and its history is gone, and allows an operator's `started`)."""
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set sends = :n where id = :i"),
                        {"n": start_call.CAP - 1, "i": request.id})  # fmt: skip
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    await _sent(owner_sessionmaker, request, start_call.CAP, unproven=True)
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("check_unavailable")) == "unresolved"
    await _observed_twice_as_unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, env.client, request)


async def test_a_request_held_at_the_cap_is_observed_as_unresolved_never_as_history_missing(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    found = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("absent")) == "absent"  # unproven
    async with owner_sessionmaker() as s, s.begin():  # queued at the cap: a bug's, or a hand's edit
        await s.execute(text("update run_requests set sends = :n where id = :i"),
                        {"n": start_call.CAP, "i": request.id})  # fmt: skip
    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Held(dispatch.SEND_CAP)
    await _observed_twice_as_unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, env.client, request)


async def test_a_later_sighting_by_its_recorded_id_settles_an_unresolved_start_at_the_cap(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("update run_requests set sends = :n where id = :i"),
                        {"n": start_call.CAP - 1, "i": request.id})  # fmt: skip
    starting = await begin(dispatch_sessionmaker, request, api_settings)
    await _sent(owner_sessionmaker, request, start_call.CAP, unproven=True)
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("check_unavailable")) == "unresolved"
    start_call.install(env.client)
    assert (await dispatch.start(env.client, starting)).kind == "started"  # a send that landed, seen late
    await aged(owner_sessionmaker, request.id)
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
    assert (await _state(owner_sessionmaker, request.id))["status"] == "started"
    await env.client.get_workflow_handle(run_workflow_id(starting.start.tenant_id, starting.start.run_id)).terminate()


async def _as_0052_left(owner: Any, request: Any) -> None:
    """A request `starting` from before 0052, as 0054's backfill then found it: no recorded start request id, no counted
    send (`starting` only as the dispatcher's own hold has it, the fence's), and a legacy-unknown blocker with no send
    recorded. Its run's row, slot and evidence are its `begin`'s."""
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set status = 'queued', start_request_id = null, sends = 0 "
                             "where id = :i"), {"i": request.id})  # fmt: skip
        await s.execute(text("select set_config('dewpoint.start_held', 'on', true)"))
        await s.execute(text("update run_requests set status = 'starting' where id = :i"), {"i": request.id})
        await s.execute(text("delete from start_sends where request_id = :i"), {"i": request.id})
        await s.execute(text("update unresolved_sends set legacy_unknown = true, state = 'unresolved', "
                             "start_request_id = null where request_id = :i"), {"i": request.id})  # fmt: skip


async def test_a_request_starting_from_before_0052_is_requeued_unended_and_gets_its_id_at_its_next_intent(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """Review focus 4: a request `starting` at the upgrade has no recorded id and no counted send. Seen absent, it goes
    back to the queue, nothing ended; its next intent records an id and counts one send; and while the reasons are
    unconfirmed, a denial of it is uncertain, never a refusal that could end it."""
    _, _, request = queued
    await begin(dispatch_sessionmaker, request, api_settings)
    await _as_0052_left(owner_sessionmaker, request)
    expected = await reconcile._expected(dispatch_sessionmaker, KEYS, api_settings, request.tenant_id, request.id)
    assert expected is not None and expected.start_request_id is None  # its payload verifies a found execution
    await aged(owner_sessionmaker, request.id)
    assert await once(dispatch_sessionmaker, env.client, api_settings) == {"absent": 1}
    state = await _state(owner_sessionmaker, request.id)
    assert (state["status"], state["attempts"], state["sends"]) == ("queued", 0, 0)
    again = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(again, dispatch.Starting) and again.start_request_id is not None
    assert (await _state(owner_sessionmaker, request.id))["sends"] == 1
    outcome = await dispatch.start(Refusing(_error(RPCStatusCode.PERMISSION_DENIED, NOT_PERMITTED)), again)  # type: ignore[arg-type]
    assert outcome.kind == "uncertain"
    assert await dispatch.settle(dispatch_sessionmaker, again, outcome) == "uncertain"
    assert (await _state(owner_sessionmaker, request.id))["status"] == "starting"


async def test_a_request_starting_from_before_0052_whose_start_landed_is_identified_by_its_payload(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    _, _, request = queued
    found = await begin(dispatch_sessionmaker, request, api_settings)
    assert isinstance(found, dispatch.Starting)
    await _as_0052_left(owner_sessionmaker, request)
    workflow_id = run_workflow_id(found.start.tenant_id, found.start.run_id)
    handle = await env.client.start_workflow(RunGraph.run, found.start, id=workflow_id, task_queue=ENGINE_QUEUE)
    try:  # the earlier build's start: the SDK's own request id
        await aged(owner_sessionmaker, request.id)
        assert await once(dispatch_sessionmaker, env.client, api_settings) == {"started": 1}
    finally:
        await handle.terminate()


# --- an uncertain start never becomes `dead`, whichever limit it reaches first (the final review's M6)


async def _refusals_carried_over(owner: Any, request: Any, attempts: int) -> None:
    """Refusals counted before 0052 counted sends: `attempts` ahead of `sends`."""
    async with owner() as s, s.begin():
        await s.execute(text("update run_requests set attempts = :n where id = :i"), {"n": attempts, "i": request.id})


async def test_the_last_refusal_after_an_unproven_attempt_leaves_the_start_unresolved_never_dead(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings, env
) -> None:
    """Refusals carried over from before 0052 can reach MAX_ATTEMPTS before the sends' cap. An earlier attempt left
    unproven (an absence seen once) then holds the end back exactly as it does at the cap: `starting`, unresolved,
    noted for an operator, and observed by the reconciler, paced; never `dead` (the owner's rule)."""
    _, _, request = queued
    found = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("absent")) == "absent"  # unproven
    await _refusals_carried_over(owner_sessionmaker, request, dispatch.MAX_ATTEMPTS - 1)
    again = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, again, dispatch.Outcome("refused")) == "unresolved"
    state = await _state(owner_sessionmaker, request.id)
    assert (state["status"], state["reason"], state["attempts"], state["sends"]) == (
        "starting", None, dispatch.MAX_ATTEMPTS, 2,
    )  # fmt: skip
    await _observed_twice_as_unresolved(owner_sessionmaker, dispatch_sessionmaker, api_settings, env.client, request)


async def test_the_last_refusal_with_nothing_unproven_still_ends_the_request_refused(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    await _refusals_carried_over(owner_sessionmaker, request, dispatch.MAX_ATTEMPTS - 1)
    found = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, found, dispatch.Outcome("refused")) == "dead"
    assert await _end(owner_sessionmaker, request.id) == ("dead", dispatch.START_REFUSED, dispatch.REFUSED_MESSAGE)


async def test_a_request_found_queued_with_its_refusals_spent_is_held_never_sent(
    queued, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    _, _, request = queued
    await _refusals_carried_over(owner_sessionmaker, request, dispatch.MAX_ATTEMPTS)  # a bug's, or a hand's edit
    assert await begin(dispatch_sessionmaker, request, api_settings) == dispatch.Held(dispatch.SEND_CAP)
    assert set(await reasons(owner_sessionmaker, request.id)) == {"start_unresolved"}
