# SPDX-License-Identifier: Apache-2.0
"""Records `ScheduleTick`'s golden history (engine 2b spec §8.2): one backfilled firing on the CLI dev server, the
activity a stub (replay never runs it), fixed ids, fixture keys. Recording again is a contract change: run it from
`backend/` as `python -m tests.apps.dispatcher.histories.record` only with a new workflow type."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from temporalio import activity
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleBackfill,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    ScheduleSpec,
    ScheduleState,
)
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.dispatcher.tick import ADMISSION_QUEUE, TICK, TickInput
from dewpoint.apps.dispatcher.tick_workflow import ScheduleTick
from dewpoint.engine.runtime.ids import schedule_workflow_id
from tests.support.keys import FIXTURE_CONVERTER

TENANT, SCHEDULE = "00000000-0000-4000-8000-0000000000a1", "00000000-0000-4000-8000-0000000000b2"


@activity.defn(name=TICK)
async def stub(given: TickInput) -> str:
    return "queued"


async def main() -> dict[str, object]:
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as env:
        client = env.client
        schedule_id = schedule_workflow_id(TENANT, SCHEDULE)
        handle = await client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    "ScheduleTick", SCHEDULE, id=schedule_id, task_queue=ADMISSION_QUEUE
                ),
                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
                state=ScheduleState(paused=True),
            ),
        )
        at = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
        async with Worker(client, task_queue=ADMISSION_QUEUE, workflows=[ScheduleTick], activities=[stub]):
            await handle.backfill(
                ScheduleBackfill(
                    start_at=at - timedelta(seconds=30), end_at=at, overlap=ScheduleOverlapPolicy.ALLOW_ALL
                )
            )
            for _ in range(100):
                found = [w async for w in client.list_workflows("WorkflowType='ScheduleTick'")]
                if found and found[0].status.name == "COMPLETED":
                    break
                await asyncio.sleep(0.2)
            [w] = found
            history = await client.get_workflow_handle(w.id, run_id=w.run_id).fetch_history()
        return {"workflow_id": history.workflow_id, "history": json.loads(history.to_json())}


if __name__ == "__main__":
    out = Path("tests/apps/dispatcher/histories/schedule_tick.json")
    out.write_text(json.dumps(asyncio.run(main()), indent=1))
    print("recorded ->", out)
