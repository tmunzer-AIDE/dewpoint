# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator
from typing import Any

import pytest
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.dispatcher import start_call
from tests.apps.dispatcher.support import workers
from tests.apps.test_admission import admit, current, published
from tests.support.temporal import start_test_server


@pytest.fixture(scope="session")
async def env() -> AsyncIterator[WorkflowEnvironment]:
    """A time-skipping test server the dispatcher tests share, apart from the worker tests' (whose `env` is checked
    after each test). Many tests here start runs that no worker serves, and some terminate them, which holds its clock
    for good (`skips_time`): none of them waits on a timer."""
    async with await start_test_server() as server:
        yield server


@pytest.fixture
async def queued(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
    """A tenant with one admitted request, and the current build's workers ready."""
    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await current(dispatch_sessionmaker)
    await workers(owner_sessionmaker)
    return ctx, wf, (await admit(api_sessionmaker, ctx, wf)).request


@pytest.fixture(autouse=True)
def _start_call(request: pytest.FixtureRequest) -> None:
    """A test server's client sends a start through the dispatcher's start call, as the dispatcher's main installs it:
    a start a test makes through `dispatch.start` carries its request's recorded id, whatever ran before it on a shared
    server. Only a start within `start_call.sending` changes; every other call is the SDK's own."""
    for name in ("env", "server"):
        if name in request.fixturenames:
            found = request.getfixturevalue(name)
            if hasattr(found, "client"):
                start_call.install(found.client)
