# SPDX-License-Identifier: Apache-2.0
"""Record this build's golden histories: `uv run python -m tests.engine.replay.record`.

Only scenarios the build's directory lacks are recorded; a recorded history is never rewritten. A change that alters
the command sequence increments ENGINE_ABI (`dewpoint.engine`), which starts a new directory.

A scenario records every execution it ran: `<name>.json` is the run's first execution, and `<name>--<n>.json` each
other one, in the order they're found: the runs it continued as, then its children's, and theirs. Each file keeps its
execution's workflow id beside the events (`workflowId`): the workflows check that it names their tenant and run
(engine 2b spec §6.1), so a replay needs the one they ran under."""

import asyncio
import contextlib
import dataclasses
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowFailureError, WorkflowHandle, WorkflowHistory
from temporalio.testing import WorkflowEnvironment

import dewpoint
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, RunInput, VersionData
from dewpoint.engine.runtime.build import build_id
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.worker.harness import TENANT, MemoryStore, workers
from tests.engine.replay.scenarios import scenarios

HERE = Path(__file__).parent
SCRUBBED = {"identity": "replay-recorder", "stackTrace": ""}  # host names and local paths stay out of the repo


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: SCRUBBED[k] if k in SCRUBBED else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


@dataclasses.dataclass
class RecorderStore(MemoryStore):
    """The versions in `unusable` lose their manifests when a run loads them: this build can't compile them."""

    unusable: set[str] = dataclasses.field(default_factory=set)

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        data = await super().version(tenant_id, version_id)
        return dataclasses.replace(data, manifests={}) if version_id in self.unusable else data


async def delaying(handle: WorkflowHandle[Any, Any]) -> None:
    """Until the run's delay is running: its second timer (the deadline's is the first)."""
    for _ in range(200):
        history = await handle.fetch_history()
        if sum(e.event_type == EventType.EVENT_TYPE_TIMER_STARTED for e in history.events) >= 2:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the run never started its delay")


def build_dir() -> Path:
    return HERE / build_id(dewpoint.__version__)


async def executions(client: Client, workflow_id: str, run_id: str) -> list[WorkflowHistory]:
    """Every execution a run led to, breadth first: the runs it continued as, and its children, recursively."""
    out: list[WorkflowHistory] = []
    queue = [(workflow_id, run_id)]
    while queue:
        wid, rid = queue.pop(0)
        history = await client.get_workflow_handle(wid, run_id=rid).fetch_history()
        out.append(history)
        for e in history.events:
            if e.HasField("workflow_execution_continued_as_new_event_attributes"):
                queue.append((wid, e.workflow_execution_continued_as_new_event_attributes.new_execution_run_id))
            if e.HasField("child_workflow_execution_started_event_attributes"):
                child = e.child_workflow_execution_started_event_attributes.workflow_execution
                queue.append((child.workflow_id, child.run_id))
    return out


async def record() -> list[str]:
    target = build_dir()
    missing = {name: s for name, s in scenarios().items() if not (target / f"{name}.json").exists()}
    if not missing:
        return []
    target.mkdir(exist_ok=True)
    store = RecorderStore()
    async with await WorkflowEnvironment.start_time_skipping() as env, workers(env.client, store):
        for name, scenario in sorted(missing.items()):
            version, run_id = store.add(scenario.build(store)), str(uuid.uuid4())
            if scenario.unusable:
                store.unusable.add(version)
            run = RunInput(TENANT, run_id, version, scenario.trigger, **scenario.options)
            handle = await env.client.start_workflow(
                RunGraph.run, run, id=run_workflow_id(TENANT, run_id), task_queue=ENGINE_QUEUE
            )
            if scenario.cancel:
                await delaying(handle)
                await handle.cancel()
            with contextlib.suppress(WorkflowFailureError):  # a cancelled run's result is its cancel
                await asyncio.wait_for(handle.result(), 120)
            histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
            for n, history in enumerate(histories):
                data = {**scrub(json.loads(history.to_json())), "workflowId": history.workflow_id}
                path = target / (f"{name}.json" if n == 0 else f"{name}--{n}.json")
                path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return sorted(missing)


def main() -> None:
    recorded = asyncio.run(record())
    print(f"{build_dir().name}: recorded {', '.join(recorded) or 'nothing (all present)'}", file=sys.stderr)


if __name__ == "__main__":
    main()
