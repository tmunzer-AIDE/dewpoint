# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.support.temporal import start_test_server


@pytest.fixture(scope="session")
async def env() -> AsyncIterator[WorkflowEnvironment]:
    """The time-skipping test server, for the Compose proof."""
    async with await start_test_server() as server:
        yield server
