# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.support.keys import FIXTURE_CONVERTER


@pytest.fixture(scope="session")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    """The CLI dev server, one per test process for every erasure test (each its own tenant): a dev server misses the
    SDK's fixed startup deadline when too many start at once (M4's full-suite failures, accounted for)."""
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment
