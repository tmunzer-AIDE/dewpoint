# SPDX-License-Identifier: Apache-2.0
"""Starting a CLI dev server of a test's own; or, for a probe, reaching an external one (2b-4b M4). Starting a
time-skipping test server, and whether it still skips time."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.core import temporal_connect
from tests.support.keys import FIXTURE_CONVERTER

TRIES = 3
PROBE_ADDRESS = "DEWPOINT_PROBE_TEMPORAL_ADDRESS"  # an external server for the probes: the D12 server
PROBE_NAMESPACE = "DEWPOINT_PROBE_TEMPORAL_NAMESPACE"
SKIPS_WITHIN_S = 10.0  # real seconds for an hour of a skipping server's time: it takes milliseconds


async def start_test_server() -> WorkflowEnvironment:
    """Temporal's time-skipping test server (downloaded once by the SDK). Its client encrypts as every Dewpoint process
    does, with fixture keys (engine 2b spec §6.2)."""
    return await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER)


async def skips_time(server: WorkflowEnvironment, *, within_s: float = SKIPS_WITHIN_S) -> bool:
    """Whether the time-skipping `server` still skips time: an hour of its time passes within `within_s` real seconds.
    The test server holds its clock for an activity or a workflow task from the moment it is scheduled until a worker
    completes, fails or cancels it or it times out, and none of those reach a task whose run has closed (sdk-java's
    `TestWorkflowMutableStateImpl`): an activity still scheduled or running as its run closes, or a run terminated
    before a worker took its first task, holds the clock for the rest of the server's life, and every later timer on it
    waits in real time. A server found not to skip is done with: the hour it was asked to sleep is still pending on
    it, and locks its clock again once it passes."""
    try:
        await asyncio.wait_for(server.sleep(timedelta(hours=1)), within_s)
    except TimeoutError:
        return False
    return True


async def start_local(**kwargs: Any) -> WorkflowEnvironment:
    """`WorkflowEnvironment.start_local`, tried again when the dev server misses the SDK's startup deadline, which its
    core fixes and a busy machine can exceed (many dev servers starting at once under `-n auto`: M4's full-suite
    failures, accounted for). Any other failure is raised at once."""
    for attempt in range(1, TRIES + 1):
        try:
            return await WorkflowEnvironment.start_local(**kwargs)
        except RuntimeError as e:
            if "did not start within" not in str(e) or attempt == TRIES:
                raise
    raise AssertionError("unreachable")


class _External(temporal_connect.TemporalConnection):
    temporal_address: str
    temporal_namespace: str


@asynccontextmanager
async def probe_temporal(**kwargs: Any) -> AsyncIterator[WorkflowEnvironment]:
    """A probe's Temporal: a dev server of its own (`start_local`'s `kwargs`), unless `DEWPOINT_PROBE_TEMPORAL_ADDRESS`
    names an external server, reached with §10.4's security from the `DEWPOINT_TEMPORAL_*` settings as a production
    deployment would (never plaintext). A `data_converter` is passed to the external client too."""
    address = os.environ.get(PROBE_ADDRESS)
    if not address:
        async with await start_local(**kwargs) as environment:
            yield environment
        return
    settings = _External(temporal_address=address, temporal_namespace=os.environ.get(PROBE_NAMESPACE, "default"))
    converter = {"data_converter": kwargs["data_converter"]} if "data_converter" in kwargs else {}
    client = await temporal_connect.connect(settings, "production", **converter)
    yield WorkflowEnvironment.from_client(client)
