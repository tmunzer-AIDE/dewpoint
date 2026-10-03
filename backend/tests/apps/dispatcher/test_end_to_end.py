# SPDX-License-Identifier: Apache-2.0
"""M2's whole path on the time-skipping server (engine 2b spec §7.3–7.8): an admitted request is started by a dispatch
cycle, run by a worker with its envelope's handles resolved, and its end write frees the tenant's slot."""

import asyncio

import pytest

from dewpoint.apps.dispatcher import dispatch
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.dispatcher.support import BUILD, state
from tests.apps.test_admission import KEYS
from tests.apps.worker.harness import workers

pytestmark = pytest.mark.usefixtures("development_deployment")


async def test_an_admitted_request_runs_to_its_end_and_frees_its_slot(
    queued, env, owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    ctx, _, request = queued
    async with workers(env.client, DbRunStore(worker_sessionmaker, KEYS)):
        done = await dispatch.dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD)
        assert done == {"started": 1}
        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
        result = await asyncio.wait_for(handle.result(), 30)
    assert result.status == "succeeded"
    after = await state(owner_sessionmaker, request.id)
    assert after["request"] == ("started", None, 0) and after["slot"] == 0
    assert after["run"][0] == "succeeded" and after["run"][1] is not None  # started, then ended
    assert await dispatch.dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD) == {}
