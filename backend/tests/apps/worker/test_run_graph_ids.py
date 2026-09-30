# SPDX-License-Identifier: Apache-2.0
"""Engine 2b spec §6.1: every store write is scoped by a start's tenant, so a run and a batch refuse a start whose
server-built workflow id names another tenant or run. Only a bug, or a start built outside Dewpoint, gets there: it
fails before anything runs, and writes nothing."""

import asyncio
import uuid
from typing import Any

import pytest
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime.activities import BATCH, ENGINE_QUEUE, BatchInput, Parent, RunInput
from dewpoint.engine.runtime.execution import INTERNAL_ERROR
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import TENANT, MemoryStore, workers
from tests.support.graphs import G

OTHER = str(uuid.UUID(int=9))
REFUSED = "This run's workflow id doesn't name its tenant and run."


def graph() -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {}}
    return g


async def refused(handle: Any) -> ApplicationError:
    with pytest.raises(WorkflowFailureError) as failed:
        await asyncio.wait_for(handle.result(), 30)
    assert isinstance(failed.value.cause, ApplicationError)
    return failed.value.cause


def ids(run_id: str) -> list[str]:
    """Workflow ids that don't name TENANT's run `run_id`."""
    return [run_workflow_id(OTHER, run_id), run_workflow_id(TENANT, OTHER), run_id]


async def test_a_run_refuses_a_workflow_id_of_another_tenant_or_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    version = store.add(graph().node("a", "testkit.echo@1", {"value": 1}))
    async with workers(env.client, store):
        for workflow_id in ids(run_id := str(uuid.uuid4())):
            start = RunInput(TENANT, run_id, version, {})
            handle = await env.client.start_workflow(RunGraph.run, start, id=workflow_id, task_queue=ENGINE_QUEUE)
            failure = await refused(handle)
            assert (failure.type, failure.message, failure.non_retryable) == (INTERNAL_ERROR, REFUSED, True)
    assert (store.starts, store.runs, store.rows) == ({}, {}, {})


async def test_a_batch_refuses_a_workflow_id_of_another_tenant_or_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    version = store.add(
        graph().node("l", "flow.loop@1", {"items": [1]}).node("x", "testkit.echo@1").edge("l", "x", "body")
    )
    now = (await env.get_current_time()).isoformat()
    run_id = str(uuid.uuid4())
    parent = Parent(run_workflow_id(TENANT, run_id), run_id, str(uuid.uuid4()), "", BATCH, now, 0)
    batch = BatchInput(TENANT, run_id, version, str(uuid.uuid4()), [], [], 0, 1, True, {}, {}, now, parent)
    async with workers(env.client, store):
        for workflow_id in ids(run_id):
            batch_id = f"{workflow_id}/{parent.step_id}/l:0/batch:0"
            handle = await env.client.start_workflow(LoopBatch.run, batch, id=batch_id, task_queue=ENGINE_QUEUE)
            failure = await refused(handle)
            assert (failure.type, failure.message, failure.non_retryable) == (INTERNAL_ERROR, REFUSED, True)
    assert (store.starts, store.runs, store.rows) == ({}, {}, {})
