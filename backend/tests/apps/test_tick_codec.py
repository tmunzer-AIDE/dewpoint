# SPDX-License-Identifier: Apache-2.0
"""A schedule tick's payloads (the owner's M3 ruling: §6.2's one exception). In a `ScheduleTick` workflow's or
activity's context, and only there, the codec writes payloads unsealed, under their own marker, and only what the tick
contract allows: the tick's input (identifiers its workflow id already names) and its fixed outcome codes. Anything
else is refused. A tick's failures carry a fixed code, never an exception's text or a stack trace. Legacy sealed tick
payloads still decode, for replay; nothing holds a tenant's data key otherwise."""

import json
import re
import uuid

import pytest
from temporalio.api.common.v1 import Payload
from temporalio.api.failure.v1 import Failure
from temporalio.converter import ActivitySerializationContext, DataConverter, WorkflowSerializationContext
from temporalio.exceptions import ApplicationError

from dewpoint.apps import tick_contract
from dewpoint.apps.codec import ENCODING, KEY_VERSION, TICK_ENCODING, CodecRefusedError, TenantCodec, data_converter
from dewpoint.engine.runtime.ids import run_workflow_id, schedule_workflow_id
from tests.support.keys import FixtureKeys

T, S = str(uuid.UUID(int=11)), str(uuid.UUID(int=12))
NOMINAL = "2026-10-05T09:00:00Z"
FIRING = f"{schedule_workflow_id(T, S)}-{NOMINAL}"
INPUT = {"schedule_id": S, "key": f"sched:{S}:{NOMINAL}", "nominal": NOMINAL}


def _payload(value: object) -> Payload:
    return DataConverter.default.payload_converter.to_payloads([value])[0]


def _activity(workflow_type: str = "ScheduleTick", workflow_id: str = FIRING) -> ActivitySerializationContext:
    return ActivitySerializationContext(namespace="default", activity_id="1", activity_type="schedule.tick",
                                        activity_task_queue="dewpoint-admission", workflow_id=workflow_id,
                                        workflow_type=workflow_type, is_local=False)  # fmt: skip


def _codecs() -> list[TenantCodec]:
    return [TenantCodec(FixtureKeys()).with_context(c) for c in (WorkflowSerializationContext("default", FIRING),
                                                                 _activity())]  # fmt: skip


@pytest.mark.parametrize("value", ["queued", "recorded", "refused", "refused:schedule_paused",
                                   "refused:workflow_disabled", "skipped:tenant_erasing", INPUT])  # fmt: skip
async def test_what_a_tick_may_carry_is_written_unsealed_under_its_own_marker(value: object) -> None:
    for codec in _codecs():
        [written] = await codec.encode([_payload(value)])
        assert written.metadata["encoding"] == TICK_ENCODING and KEY_VERSION not in written.metadata
        assert json.loads(Payload.FromString(written.data).data) == value
        [read] = await codec.decode([written])
        assert json.loads(read.data) == value


@pytest.mark.parametrize("value", [
    "anything else", "refused:a reason someone wrote", "queued ", {"token": "a secret"},
    INPUT | {"schedule_id": str(uuid.UUID(int=13))}, INPUT | {"key": f"sched:{S}:2026-10-05T09:00:01Z"},
    INPUT | {"nominal": "2026-10-05 09:00:00"}, INPUT | {"extra": 1}, {"schedule_id": S}, 42, None, [S],
])  # fmt: skip
async def test_anything_else_in_a_tick_is_refused(value: object) -> None:
    for codec in _codecs():
        with pytest.raises(CodecRefusedError):
            await codec.encode([_payload(value)])


async def test_a_tick_refuses_bytes_and_a_marked_payload_outside_the_contract() -> None:
    raw = Payload(metadata={"encoding": b"binary/plain"}, data=b"queued")
    smuggled = Payload(metadata={"encoding": TICK_ENCODING}, data=_payload("a secret").SerializeToString())
    for codec in _codecs():
        with pytest.raises(CodecRefusedError):
            await codec.encode([raw])
        with pytest.raises(CodecRefusedError):
            await codec.decode([smuggled])


async def test_only_a_scheduletick_context_is_excepted() -> None:
    """An activity of another workflow type under a schedule's id gets nothing (neither the exception nor a seal); a
    run's payloads are still sealed, and a run refuses a tick's marker."""
    other = TenantCodec(FixtureKeys()).with_context(_activity(workflow_type="RunGraph"))
    with pytest.raises(CodecRefusedError):
        await other.encode([_payload("queued")])
    run = TenantCodec(FixtureKeys()).with_context(WorkflowSerializationContext("default", run_workflow_id(T, S)))
    [sealed] = await run.encode([_payload("queued")])
    assert sealed.metadata["encoding"] == ENCODING
    [marked] = await _codecs()[0].encode([_payload("queued")])
    with pytest.raises(CodecRefusedError):
        await run.decode([marked])


async def test_a_legacy_sealed_tick_payload_still_decodes_for_replay() -> None:
    """A tick written before the exception sealed its payloads under its tenant's key: they still open, whatever they
    hold (a schedule id argument isn't in today's contract), so its history replays."""
    run = TenantCodec(FixtureKeys()).with_context(WorkflowSerializationContext("default", run_workflow_id(T, S)))
    sealed = await run.encode([_payload(S), _payload(INPUT), _payload("queued")])
    for codec in _codecs():
        assert [json.loads(p.data) for p in await codec.decode(sealed)] == [S, INPUT, "queued"]


def _failure(context: object, error: BaseException) -> Failure:
    failure = Failure()
    converter = data_converter(FixtureKeys()).with_context(context)  # type: ignore[arg-type]
    converter.failure_converter.to_failure(error, converter.payload_converter, failure)
    return failure


def _raised(error: BaseException, cause: BaseException | None = None) -> BaseException:
    try:
        raise error from cause
    except BaseException as e:  # noqa: BLE001 - the traceback is the point
        return e


async def test_a_ticks_failure_carries_a_fixed_code_never_its_text_details_or_stack() -> None:
    for context in (WorkflowSerializationContext("default", FIRING), _activity()):
        leaked = _failure(context, _raised(RuntimeError("password=hunter2"), ValueError("row (a secret)")))
        for f in (leaked, leaked.cause):
            assert (f.message, f.stack_trace, f.HasField("encoded_attributes")) == ("tick_failed", "", False)
            assert f.application_failure_info.type == "tick_failed"
        known = _failure(
            context,
            _raised(
                ApplicationError(
                    "named another schedule", "a detail", type=tick_contract.TICK_IDENTITY, non_retryable=True
                )
            ),
        )
        assert (known.message, known.application_failure_info.type) == (tick_contract.TICK_IDENTITY,) * 2
        assert known.application_failure_info.non_retryable and not known.application_failure_info.HasField("details")
        assert known.stack_trace == ""


async def test_a_runs_failure_still_seals_its_text() -> None:
    run = WorkflowSerializationContext("default", run_workflow_id(T, S))
    failure = _failure(run, _raised(RuntimeError("password=hunter2")))
    assert failure.HasField("encoded_attributes") and "hunter2" not in failure.message


def test_every_refusal_admission_or_a_tick_can_record_is_a_tick_outcome() -> None:
    """The contract's codes are literal (the codec imports nothing heavier): each refusal reason a request can carry
    is one, so a tick's outcome is never refused by its own codec."""
    from dewpoint.apps import admission, inputs
    from dewpoint.apps.dispatcher import tick

    reasons = {
        v for k, v in vars(admission).items() if k.isupper() and isinstance(v, str) and re.fullmatch("[a-z_]+", v)
    } - {"live", "simulate", "production"}  # modes and environments
    reasons |= {tick.SCHEDULE_PAUSED, tick.SCHEDULE_DELETED, tick.SCHEDULE_CATCHUP_EXPIRED, inputs.INPUT_INVALID,
                inputs.SECRET_INDEX_LIMIT}  # fmt: skip
    assert {f"refused:{r}" for r in reasons} <= tick_contract.OUTCOMES
    assert f"skipped:{admission.TENANT_ERASING}" in tick_contract.OUTCOMES
    assert {tick.TICK_IDENTITY, tick.SCHEDULE_UNKNOWN} <= tick_contract.FAILURES
    assert tick_contract.outcome("refused:a code added later") == "refused"
    assert tick_contract.outcome("an unknown status") == "other"
