# SPDX-License-Identifier: Apache-2.0
"""Record this build's golden histories: `uv run python -m tests.engine.replay.record`.

Only scenarios the build's directory lacks are recorded; a recorded history is never rewritten. A change that alters
the command sequence increments ENGINE_ABI (`dewpoint.engine`), which starts a new directory.

A scenario records every execution it ran: `<name>.json` is the run's first execution, and `<name>--<n>.json` each
other one, in the order they're found: the runs it continued as, then its children's, and theirs."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from temporalio.client import Client, WorkflowHistory
from temporalio.testing import WorkflowEnvironment

import dewpoint
from dewpoint.engine.runtime.build import build_id
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.engine.replay.scenarios import scenarios

HERE = Path(__file__).parent
SCRUBBED = {"identity": "replay-recorder", "stackTrace": ""}  # host names and local paths stay out of the repo


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: SCRUBBED[k] if k in SCRUBBED else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


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
    store = MemoryStore()
    async with await WorkflowEnvironment.start_time_skipping() as env, workers(env.client, store):
        for name, scenario in sorted(missing.items()):
            handle = await start(env.client, store, scenario.build(store), scenario.trigger, **scenario.options)
            await handle.result()
            histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
            for n, history in enumerate(histories):
                data = scrub(json.loads(history.to_json()))
                path = target / (f"{name}.json" if n == 0 else f"{name}--{n}.json")
                path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return sorted(missing)


def main() -> None:
    recorded = asyncio.run(record())
    print(f"{build_dir().name}: recorded {', '.join(recorded) or 'nothing (all present)'}", file=sys.stderr)


if __name__ == "__main__":
    main()
