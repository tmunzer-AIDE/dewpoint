# SPDX-License-Identifier: Apache-2.0
"""`ScheduleTick`'s replay test (engine 2b spec §8.2, §12): the workflow is unversioned, so a change to what it does
would break every tick in flight when a new build takes over. One firing's history, recorded on the CLI dev server
with fixture keys (`histories/record.py`), replays against today's code, whatever
`ENGINE_ABI` is. A change that fails here is a contract change, made with a new workflow type.

Two histories: `schedule_tick.json`, recorded before the tick contract (its argument and payloads sealed, which still
open), and `schedule_tick_plain.json`, recorded since (no argument, every payload the contract's, unsealed)."""

import json
from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
from tests.support.keys import FIXTURE_CONVERTER, opened

RECORDED = Path(__file__).parent / "histories" / "schedule_tick.json"
PLAIN = Path(__file__).parent / "histories" / "schedule_tick_plain.json"


def _history(recorded: Path) -> WorkflowHistory:
    found = json.loads(recorded.read_text())
    return WorkflowHistory.from_json(found["workflow_id"], found["history"])


@pytest.mark.parametrize("recorded", [RECORDED, PLAIN], ids=["legacy", "plain"])
async def test_schedule_tick_replays_its_recorded_history(recorded: Path) -> None:
    history = _history(recorded)
    replayer = Replayer(workflows=[ScheduleTick], data_converter=FIXTURE_CONVERTER)
    result = await replayer.replay_workflow(history)
    assert result.replay_failure is None


async def test_the_plain_tick_holds_only_its_contract_unsealed() -> None:
    """The owner's M3 ruling: no argument, and each payload (the activity's input and result, the workflow's result)
    the tick contract's, under the tick's marker: nothing under a tenant's data key."""
    from temporalio.api.common.v1 import Payload

    from dewpoint.apps import tick_contract
    from dewpoint.apps.codec import KEY_VERSION, TICK_ENCODING

    history = _history(PLAIN)
    assert not history.events[0].workflow_execution_started_event_attributes.HasField("input")
    payloads = [
        p
        for e in history.events
        for attributes, field in (
            (e.activity_task_scheduled_event_attributes, "input"),
            (e.activity_task_completed_event_attributes, "result"),
            (e.workflow_execution_completed_event_attributes, "result"),
        )
        if attributes.HasField(field)  # type: ignore[arg-type]
        for p in getattr(attributes, field).payloads
    ]
    assert len(payloads) == 3
    for p in payloads:
        assert p.metadata["encoding"] == TICK_ENCODING and KEY_VERSION not in p.metadata
        assert tick_contract.allowed(Payload.FromString(p.data), "00000000-0000-4000-8000-0000000000b2")


async def test_the_recorded_tick_keyed_its_request_on_its_nominal_time() -> None:
    """What the history holds: the schedule's id as the only argument, and the activity's input carrying the key built
    from `TemporalScheduledStartTime`, sealed under the schedule's tenant like every payload."""
    recorded = json.loads(RECORDED.read_text())
    history = WorkflowHistory.from_json(recorded["workflow_id"], recorded["history"])
    started = history.events[0].workflow_execution_started_event_attributes
    scheduled = next(e for e in history.events if e.HasField("activity_task_scheduled_event_attributes"))
    activity = scheduled.activity_task_scheduled_event_attributes
    assert activity.activity_type.name == "schedule.tick" and activity.task_queue.name == "dewpoint-admission"
    schedule = "00000000-0000-4000-8000-0000000000b2"
    assert await opened(started.input.payloads[0]) == schedule
    assert await opened(activity.input.payloads[0]) == {
        "schedule_id": schedule, "key": f"sched:{schedule}:2026-10-04T09:00:00Z", "nominal": "2026-10-04T09:00:00Z",
    }  # fmt: skip
