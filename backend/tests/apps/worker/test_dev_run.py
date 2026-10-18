# SPDX-License-Identifier: Apache-2.0
"""`dewpoint dev run`'s path (engine 2b spec §7.7): the dev CLI admits a workflow's active version with the source
`dev`, as the dispatch role; the dispatcher starts it; the CLI's bounded wait reports the end the database records, not
merely that it started. No command starts a run itself: `start_run` is a test helper."""

import asyncio
from typing import Any

import pytest
from temporalio.client import WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps import admission, dev_run
from dewpoint.apps.dispatcher.dispatch import dispatch_once
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine.runtime.activities import ProjectInput
from dewpoint.engine.runtime.ids import run_workflow_id
from tests.apps.dispatcher.support import BUILD
from tests.apps.dispatcher.support import workers as ready_workers
from tests.apps.test_admission import KEYS, current
from tests.apps.test_workflow_ops import actor, create, publish, update
from tests.apps.worker.harness import wait_for_close, workers
from tests.support.graphs import G, cel, ref
from tests.support.registry import sync_test_plugins

pytestmark = pytest.mark.usefixtures("development_deployment")


def graph() -> dict[str, Any]:
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        "outputs": {"v": ref("steps.a.output.value")},
    }
    return g.node("a", "testkit.echo@1", {"value": cel("trigger.x + 1")}).data()


@pytest.fixture
async def workflow(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> Any:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    wf = await create(api_sessionmaker, ctx, graph())
    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None
    await current(dispatch_sessionmaker)
    await ready_workers(owner_sessionmaker)
    return ctx, wf


async def test_dev_run_admits_the_workflow_and_waits_for_the_end_the_database_records(
    env: WorkflowEnvironment, workflow, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    ctx, wf = workflow
    request = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf,
                                  input={"x": 1}, simulate=False, idempotency_key="d1")  # fmt: skip
    assert (request.source, request.status, request.mode) == ("dev", "queued", "live")
    assert await dev_run.wait_for_end(dispatch_sessionmaker, ctx.tenant_id, request.id, within=0) is None
    async with workers(env.client, DbRunStore(worker_sessionmaker, KEYS)):
        assert await dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD) == {"started": 1}
        ended = await wait_for_close(env.client, dispatch_sessionmaker, ctx.tenant_id, request.id, within=30, poll=0.1)
    assert ended == dev_run.Ended("run", "succeeded", None, None)


class LateEnd(DbRunStore):
    """The run's end, committed: its projection's activity returns half a second later."""

    async def project(self, data: ProjectInput) -> None:
        await super().project(data)
        if data.run is not None:
            await asyncio.sleep(0.5)


async def test_a_tests_wait_for_the_end_lasts_until_the_runs_execution_closes(
    env: WorkflowEnvironment, workflow, dispatch_sessionmaker, worker_sessionmaker, api_settings
) -> None:
    """The database records a run's end in its last projection activity; its execution closes only on the workflow
    task after it. A test that stops its worker in between leaves that task scheduled and the run open, holding the
    shared test server's clock (`env`): `wait_for_close` waits for both, however late that activity returns."""
    ctx, wf = workflow
    request = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf,
                                  input={"x": 1}, simulate=False, idempotency_key="d5")  # fmt: skip
    async with workers(env.client, LateEnd(worker_sessionmaker, KEYS)):
        assert await dispatch_once(dispatch_sessionmaker, env.client, KEYS, api_settings, BUILD) == {"started": 1}
        ended = await wait_for_close(env.client, dispatch_sessionmaker, ctx.tenant_id, request.id, within=30, poll=0.1)
        handle = env.client.get_workflow_handle(run_workflow_id(str(ctx.tenant_id), str(request.id)))
        status = (await handle.describe()).status
    assert ended == dev_run.Ended("run", "succeeded", None, None)
    assert status == WorkflowExecutionStatus.COMPLETED


async def test_dev_run_simulates_when_asked(workflow, dispatch_sessionmaker) -> None:
    ctx, wf = workflow
    request = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf,
                                  input={"x": 1}, simulate=True, idempotency_key="d2")  # fmt: skip
    assert (request.source, request.mode) == ("dev", "simulate")


async def test_a_dev_run_admission_refuses_says_why(workflow, api_sessionmaker, dispatch_sessionmaker) -> None:
    ctx, wf = workflow
    await update(api_sessionmaker, ctx, wf, enabled=False)
    with pytest.raises(admission.AdmissionRefusedError) as refused:
        await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf, input={"x": 1},
                            simulate=False, idempotency_key="d3")  # fmt: skip
    assert refused.value.reason == "workflow_disabled"


async def test_a_request_that_ends_without_starting_reports_its_own_end(
    workflow, dispatch_sessionmaker, api_settings
) -> None:
    from tests.apps.dispatcher.support import begin

    ctx, wf = workflow
    request = await dev_run.admit(dispatch_sessionmaker, KEYS, tenant_id=ctx.tenant_id, workflow_id=wf,
                                  input={"x": 1}, simulate=False, idempotency_key="d4")  # fmt: skip
    from dewpoint.apps.dispatcher import dispatch

    starting = await begin(dispatch_sessionmaker, request, api_settings)
    assert await dispatch.settle(dispatch_sessionmaker, starting, dispatch.Outcome("collision")) == "dead"
    ended = await dev_run.wait_for_end(dispatch_sessionmaker, ctx.tenant_id, request.id, within=0)
    assert ended == dev_run.Ended("request", "dead", "id_collision", None)
