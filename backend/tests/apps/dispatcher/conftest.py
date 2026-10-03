# SPDX-License-Identifier: Apache-2.0
from typing import Any

import pytest

from tests.apps.dispatcher.support import workers
from tests.apps.test_admission import admit, current, published
from tests.apps.worker.conftest import env  # noqa: F401  (the time-skipping test server, for the start tests)


@pytest.fixture
async def queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    """A tenant with one admitted request, and the current build's workers ready."""
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    return ctx, wf, (await admit(api_sessionmaker, ctx, wf)).request
