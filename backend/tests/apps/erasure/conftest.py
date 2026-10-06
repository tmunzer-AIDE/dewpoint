# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.support.keys import FIXTURE_CONVERTER


@pytest.fixture(scope="module")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    """The CLI dev server, a module's own: erasure's tests delete what they make, and closed executions go slowly."""
    async with await WorkflowEnvironment.start_local(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment
