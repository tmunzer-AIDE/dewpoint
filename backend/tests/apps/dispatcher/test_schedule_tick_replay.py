# SPDX-License-Identifier: Apache-2.0
"""`ScheduleTick`'s replay test (engine 2b spec §8.2, §12): the workflow is unversioned, so a change to what it does
would break every tick in flight when a new build takes over. One firing's history, recorded on the CLI dev server
with fixture keys (`histories/record.py`), replays against today's code, whatever
`ENGINE_ABI` is. A change that fails here is a contract change, made with a new workflow type."""

import json
from pathlib import Path

from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
from tests.support.keys import FIXTURE_CONVERTER, opened

RECORDED = Path(__file__).parent / "histories" / "schedule_tick.json"


async def test_schedule_tick_replays_its_recorded_history() -> None:
    recorded = json.loads(RECORDED.read_text())
    history = WorkflowHistory.from_json(recorded["workflow_id"], recorded["history"])
    replayer = Replayer(workflows=[ScheduleTick], data_converter=FIXTURE_CONVERTER)
    result = await replayer.replay_workflow(history)
    assert result.replay_failure is None


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
