# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

import pytest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import runs as run_ops
from dewpoint.engine import ENGINE_ABI
from tests.support.keys import FIXTURE_CONVERTER


@pytest.fixture(scope="session")
async def env() -> AsyncIterator[WorkflowEnvironment]:
    """Temporal's time-skipping test server (downloaded once by the SDK), shared by the session. Its client encrypts
    as every Dewpoint process does, with fixture keys (engine 2b spec §6.2)."""
    async with await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


@pytest.fixture
async def own_env() -> AsyncIterator[WorkflowEnvironment]:
    """A test server of the test's own, for a test that ends a run while an activity still runs. That activity never
    completes against its closed run, and the time-skipping server stops skipping time while any activity is
    outstanding: every later timer on a shared server would wait in real time."""
    async with await WorkflowEnvironment.start_time_skipping(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment


@pytest.fixture(scope="session")
async def dev_env() -> AsyncIterator[WorkflowEnvironment]:
    """Temporal's CLI dev server (downloaded once by the SDK), for what the test server can't do: Worker Versioning,
    a terminated child reaching its parent, and Temporal suggesting continue-as-new. Time runs for real on it. A
    version that no run is pinned to reports itself drained within about a second (the default checks every 3 min)."""
    drainage = [
        "matching.wv.VersionDrainageStatusVisibilityGracePeriod",
        "matching.wv.VersionDrainageStatusRefreshInterval",
    ]
    args = [a for key in drainage for a in ("--dynamic-config-value", f'{key}="1s"')]
    async with await WorkflowEnvironment.start_local(
        data_converter=FIXTURE_CONVERTER, dev_server_extra_args=args
    ) as environment:
        yield environment


@pytest.fixture
def this_build_is_current(monkeypatch: pytest.MonkeyPatch) -> None:
    """For tests that start runs through admission on the time-skipping server, which has no Worker Deployments:
    admission takes this build as the deployment's current one. The deployment's own answer is tested on the dev
    server (test_admission_abi.py)."""

    async def current_abi(_client: Client) -> int:
        return ENGINE_ABI

    monkeypatch.setattr(run_ops, "current_abi", current_abi)
