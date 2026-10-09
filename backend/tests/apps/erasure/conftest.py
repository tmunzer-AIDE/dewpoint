# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

import pytest
from temporalio.testing import WorkflowEnvironment

from tests.support.keys import FIXTURE_CONVERTER
from tests.support.temporal import probe_temporal


@pytest.fixture(scope="session")
async def server() -> AsyncIterator[WorkflowEnvironment]:
    """The CLI dev server, one per test process for every erasure test (each its own tenant): a dev server misses the
    SDK's fixed startup deadline when too many start at once (M4's full-suite failures, accounted for). With
    `DEWPOINT_PROBE_TEMPORAL_ADDRESS` set, D12's proof server instead (`probe_temporal`): D12.11 runs the incarnation
    fencing here (the owner's ruling on the run request, 2b-4b M4)."""
    async with probe_temporal(data_converter=FIXTURE_CONVERTER) as environment:
        yield environment
