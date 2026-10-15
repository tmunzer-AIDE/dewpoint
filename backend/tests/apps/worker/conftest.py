# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

import pytest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import runs as run_ops
from dewpoint.engine import ENGINE_ABI
from tests.support.keys import FIXTURE_CONVERTER
from tests.support.temporal import probe_temporal, skips_time, start_test_server


@pytest.fixture(scope="session")
async def shared_servers() -> AsyncIterator[list[WorkflowEnvironment]]:
    """The time-skipping test servers the worker tests share, the one in use last: `env` starts the next once a test
    leaves the one in use unable to skip time. Each is shut down with the session."""
    servers = [await start_test_server()]
    try:
        yield servers
    finally:
        for server in servers:
            await server.shutdown()


@pytest.fixture
async def env(shared_servers: list[WorkflowEnvironment]) -> AsyncIterator[WorkflowEnvironment]:
    """Temporal's time-skipping test server (`start_test_server`), shared by the worker tests. It refuses a run's
    cancel of an activity that completed while the run's workflow task was in flight (`ACTIVITY_UNKNOWN for
    scheduledEventId=…`), and that run stalls: a test whose run may end as a quick activity completes runs on
    `dev_env`, a real server, which records the cancel and lets the run end (`test_real_server.py`'s
    `test_a_run_ending_as_its_running_activity_completes_cancels_it_and_ends`).

    After each test it must still skip time (`skips_time`, about 10 ms): a test whose run closed with an activity still
    scheduled or running has held its clock for good, and every later timer on it would wait in real time (the 2-day
    `wait_until` of `test_run_graph_policies.py` timed out at 60 s). That test fails here, and the tests after it get a
    fresh server."""
    server = shared_servers[-1]
    yield server
    if not await skips_time(server):
        shared_servers.append(await start_test_server())
        pytest.fail(
            "This test left the shared test server unable to skip time: a run closed with an activity still scheduled "
            "or running (or was terminated before a worker took its first task), and the server never releases its "
            "clock for it (`skips_time`). Give the test `own_env`."
        )


@pytest.fixture
async def own_env() -> AsyncIterator[WorkflowEnvironment]:
    """A test server of the test's own, for a test that ends a run while one of its activities is still scheduled or
    running. Nothing completes that activity against its closed run, and the time-skipping server holds its clock for
    an activity from the moment it is scheduled until it completes: on a shared server every later timer would wait in
    real time (`env` checks for it)."""
    async with await start_test_server() as environment:
        yield environment


@pytest.fixture(scope="session")
async def dev_env() -> AsyncIterator[WorkflowEnvironment]:
    """Temporal's CLI dev server (downloaded once by the SDK), for what the test server can't do: Worker Versioning,
    a terminated child reaching its parent, and Temporal suggesting continue-as-new. Time runs for real on it. A
    version that no run is pinned to reports itself drained within about a second (the default checks every 3 min).
    With `DEWPOINT_PROBE_TEMPORAL_ADDRESS` set, D12's proof server instead (`probe_temporal`, with §10.4's security):
    D12.9-D12.11 are the deletion, visibility and schedule contract tests run there (2b-4b M4)."""
    drainage = [
        "matching.wv.VersionDrainageStatusVisibilityGracePeriod",
        "matching.wv.VersionDrainageStatusRefreshInterval",
    ]
    args = [a for key in drainage for a in ("--dynamic-config-value", f'{key}="1s"')]
    async with probe_temporal(data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args) as environment:
        yield environment


@pytest.fixture
def this_build_is_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """For tests that start runs through admission on the time-skipping server, which has no Worker Deployments:
    admission takes this build as the deployment's current one. The deployment's own answer is tested on the dev
    server (test_admission_abi.py)."""

    async def current_abi(_client: Client) -> int:
        return ENGINE_ABI

    monkeypatch.setattr(run_ops, "current_abi", current_abi)
