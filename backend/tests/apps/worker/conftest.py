# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

import pytest
from temporalio.testing import WorkflowEnvironment


@pytest.fixture(scope="session")
async def env() -> AsyncIterator[WorkflowEnvironment]:
    """Temporal's time-skipping test server (downloaded once by the SDK), shared by the session."""
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment


@pytest.fixture
async def own_env() -> AsyncIterator[WorkflowEnvironment]:
    """A test server of the test's own, for a test that ends a run while an activity still runs. That activity never
    completes against its closed run, and the time-skipping server stops skipping time while any activity is
    outstanding: every later timer on a shared server would wait in real time."""
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment
