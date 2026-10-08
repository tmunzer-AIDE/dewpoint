# SPDX-License-Identifier: Apache-2.0
"""The engine blockers' reproductions at their real size, on Temporal's CLI dev server (the 2b-4b plan's M2: #16, #18,
#26): minutes each, too slow for the suite, where a fast regression pins each. A run by hand, never in CI (skipped
unless `DEWPOINT_PROBE` is set); each prints what it measured. From `backend/`:

    DEWPOINT_PROBE=1 .venv/bin/pytest tests/probes/test_engine_issues.py -p no:randomly -s

These are this machine's numbers, on the dev server: evidence for the issues' acceptance, not supported figures."""

import asyncio
import os
from collections.abc import AsyncIterator

import pytest
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime import bounds
from tests.apps.worker.harness import MemoryStore, start
from tests.apps.worker.test_real_server import continued_inputs, issue_16, serving
from tests.support.keys import FIXTURE_CONVERTER

pytestmark = pytest.mark.skipif(not os.environ.get("DEWPOINT_PROBE"), reason="a probe, run by hand (DEWPOINT_PROBE)")


@pytest.fixture(scope="module")
async def dev() -> AsyncIterator[WorkflowEnvironment]:
    """The dev server, as the suite's `dev_env` starts it."""
    drainage = ["matching.wv.VersionDrainageStatusVisibilityGracePeriod",
                "matching.wv.VersionDrainageStatusRefreshInterval"]  # fmt: skip
    args = [a for key in drainage for a in ("--dynamic-config-value", f'{key}="1s"')]
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER,
                                                     dev_server_extra_args=args) as environment:  # fmt: skip
        yield environment


async def test_issue_16s_reproduction_carries_on_within_the_snapshot_bound(dev: WorkflowEnvironment) -> None:
    """#16's acceptance at its real size: its reproduction (nested loops 10 x 10, each inner iteration 200 parallel
    steps) ends, every iteration done; no workflow task failed; each continued run's input within `SNAPSHOT_MAX`,
    encoded. Measured on `b5cbb9e`: succeeded in 240 s, 81 runs continued, the largest input 72,588 bytes."""
    client, store = dev.client, MemoryStore()
    loop = asyncio.get_running_loop()
    async with serving(client, store):
        handle = await start(client, store, issue_16(), checkpoint_events=300, drain_events=600, max_run_duration_s=900)
        t0 = loop.time()
        result = await asyncio.wait_for(handle.result(), 900)
        took = loop.time() - t0
    sizes, failures = await continued_inputs(client, handle)
    print(f"issue 16: {result.status} in {took:.1f} s; {len(sizes)} continued, largest {max(sizes, default=0)} bytes")
    assert (result.status, result.outputs) == ("succeeded", {"n": 10}), result
    assert failures == []
    assert sizes and max(sizes) <= bounds.SNAPSHOT_MAX
