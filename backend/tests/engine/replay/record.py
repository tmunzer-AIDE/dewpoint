# SPDX-License-Identifier: Apache-2.0
"""Record this build's golden histories: `uv run python -m tests.engine.replay.record`.

Only scenarios the build's directory lacks are recorded; a recorded history is never rewritten. A change that alters
the command sequence increments ENGINE_ABI (engine/runtime/build.py), which starts a new directory."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

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


async def record() -> list[str]:
    target = build_dir()
    missing = {name: s for name, s in scenarios().items() if not (target / f"{name}.json").exists()}
    if not missing:
        return []
    target.mkdir(exist_ok=True)
    store = MemoryStore()
    async with await WorkflowEnvironment.start_time_skipping() as env, workers(env.client, store):
        for name, scenario in sorted(missing.items()):
            handle = await start(env.client, store, scenario.graph, scenario.trigger, **scenario.options)
            await handle.result()
            history = await handle.fetch_history()
            data = scrub(json.loads(history.to_json()))
            (target / f"{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return sorted(missing)


def main() -> None:
    recorded = asyncio.run(record())
    print(f"{build_dir().name}: recorded {', '.join(recorded) or 'nothing (all present)'}", file=sys.stderr)


if __name__ == "__main__":
    main()
