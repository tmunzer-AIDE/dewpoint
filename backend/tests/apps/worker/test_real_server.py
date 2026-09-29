# SPDX-License-Identifier: Apache-2.0
"""What only a real Temporal server shows (2a-3b's handoff), on the dev server: a child an operator terminates
reaches its parent, which settles its whole grant and writes its end; and Temporal suggesting continue-as-new starts
the drain. Time runs for real here: waits are short, and a sleeping child is terminated, not waited for."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker.activities import cel_activity
from dewpoint.apps.worker.deployment import set_current
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import cel_queue
from dewpoint.engine.runtime.execution import SUBFLOW_GRANT
from tests.apps.worker.harness import MemoryStore, in_process, start
from tests.apps.worker.test_deployment import build
from tests.apps.worker.test_main import settings
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref
from tests.support.plugins.testkit import TESTKIT


@asynccontextmanager
async def serving(client: Client, store: MemoryStore) -> AsyncIterator[None]:
    """A build of this test's own, current: the dev server keeps the deployment's routing between tests."""
    this = build("real")
    evaluator = Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process)])
    async with evaluator, engine_worker(client, store, [TESTKIT], settings(), build=this, identity=this):
        await set_current(client, this)
        yield


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


def sleeper() -> G:
    return graph().node("d", "flow.delay@1", {"duration_s": 3600})


async def child_started(handle: WorkflowHandle[Any, Any]) -> str:
    """The first child's workflow id, once it has started (in real time)."""
    for _ in range(200):
        for e in (await handle.fetch_history()).events:
            if e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED:
                return e.child_workflow_execution_started_event_attributes.workflow_execution.workflow_id
        await asyncio.sleep(0.1)
    raise AssertionError("no child started")


async def test_a_terminated_sub_flow_fails_its_step_and_its_row_records_the_end(dev_env: WorkflowEnvironment) -> None:
    """The parent learns of the termination (the test server never tells it): its step fails with `terminated`
    under its error policy, the child's whole grant stays counted, and the sub-run's row, which the child never
    ended, records the end. It would otherwise stay `running` and hold its references."""
    client, store = dev_env.client, MemoryStore()
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sleeper()))}, on_error="continue")
    async with serving(client, store):
        handle = await start(client, store, g, {})
        child = await child_started(handle)
        await client.get_workflow_handle(child).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "terminated"}, SUBFLOW_GRANT)
    assert store.starts[child].kind == "subflow"
    end = store.runs[child]
    assert (end.status, end.error_code, end.iterations) == ("failed", "terminated", SUBFLOW_GRANT)


async def test_a_terminated_batch_fails_its_loop_and_its_whole_grant_stays_used(dev_env: WorkflowEnvironment) -> None:
    client, store = dev_env.client, MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", "flow.loop@1", {"items": list(range(101))}, on_error="continue").node(
        "d", "flow.delay@1", {"duration_s": 3600}
    )
    g.edge("l", "d", "body")
    async with serving(client, store):
        handle = await start(client, store, g, {})
        batch = await child_started(handle)
        await client.get_workflow_handle(batch).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert batch.endswith("/batch:0")
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "terminated"}, 100)


async def test_a_terminated_failure_handler_records_its_end_and_the_runs_stands(dev_env: WorkflowEnvironment) -> None:
    client, store = dev_env.client, MemoryStore()
    g = graph().node("f", "flow.fail@1", {"message": "it went wrong"})
    g.settings["failure_handler"] = str(store.publish(sleeper()))
    async with serving(client, store):
        handle = await start(client, store, g, {})
        handler = await child_started(handle)
        await client.get_workflow_handle(handler).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.error["code"] if result.error else None) == ("failed", "workflow_failed")
    assert result.iterations == SUBFLOW_GRANT  # the handler's whole grant: it never reported
    assert store.starts[handler].kind == "failure_handler"
    assert (store.runs[handler].status, store.runs[handler].error_code) == ("failed", "terminated")
    assert store.runs[handle.id].status == "failed"


def asks_for_more() -> G:
    """A filter over 1,500 items, more than its first grant of 1,000 iterations, so it asks for more; then a delay."""
    g = graph().node("f", "flow.filter@1", {"items": list(range(1_500)), "predicate": cel("item % 2 == 0")})
    return g.node("d", "flow.delay@1", {"duration_s": 3600}).edge("f", "d")


async def filtered(store: MemoryStore, run_id: str) -> None:
    """Until the run's filter has ended, so it has been granted more (its row lands in real time)."""
    for _ in range(200):
        if any(r.node_key == "f" and r.status == "succeeded" for r in store.steps(run_id)):
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"{run_id}'s filter never ended")


@pytest.mark.parametrize("kind", ["subflow", "failure_handler"])
async def test_a_terminated_sub_run_that_asked_for_more_records_its_whole_grant(
    dev_env: WorkflowEnvironment, kind: str
) -> None:
    """The final review: the row a parent writes for a terminated sub-run recorded its first grant, not all it had
    been granted, which the parent debits (spec §6)."""
    client, store = dev_env.client, MemoryStore()
    child_workflow = str(store.publish(asks_for_more()))
    if kind == "subflow":
        g = graph().node("r", "flow.run_workflow@1", {"workflow_id": child_workflow}, on_error="continue")
    else:
        g = graph().node("x", "flow.fail@1", {"message": "it went wrong"})
        g.settings["failure_handler"] = child_workflow
    async with serving(client, store):
        handle = await start(client, store, g, {})
        child = await child_started(handle)
        await filtered(store, child)
        await client.get_workflow_handle(child).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert store.starts[child].kind == kind
    assert result.iterations > SUBFLOW_GRANT  # it had been granted more, and the parent debits all of it
    assert (store.runs[child].error_code, store.runs[child].iterations) == ("terminated", result.iterations)


async def test_temporal_suggesting_continue_as_new_drains_the_run() -> None:
    """The dev server suggests continuing past 100 history events here (Temporal's default is thousands): the run
    drains and continues as new, long before its own thresholds (2,000 and 4,000), and ends as it would have."""
    args = ["--dynamic-config-value", "limit.historyCount.suggestContinueAsNew=100"]
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"))
    g.node("l", "flow.loop@1", {"items": list(range(40)), "collect": cel("steps.x.output.value")})
    g.node("x", "testkit.echo@1", {"value": ref("item")}).edge("l", "x", "body")
    async with await WorkflowEnvironment.start_local(dev_server_extra_args=args) as env, serving(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 120)
        chain = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"items": list(range(40))}, 40)
    assert len(chain) >= 2 and all(len(h.events) < 2_000 for h in chain)


def strings(*names: str) -> dict[str, Any]:
    return {"type": "object", "properties": {n: {"type": "string"} for n in names}, "required": list(names)}


async def task_failures(handle: WorkflowHandle[Any, Any]) -> list[int]:
    """The causes of every failed workflow task: none, when nothing retried a command Temporal refused."""
    out = []
    async for e in handle.fetch_history_events():
        if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED:
            out.append(e.workflow_task_failed_event_attributes.cause)
    return out


async def cel_requests(handle: WorkflowHandle[Any, Any]) -> list[int]:
    out = []
    async for e in handle.fetch_history_events():
        a = e.activity_task_scheduled_event_attributes
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED and a.activity_type.name == "cel.evaluate":
            out.append(a.workflow_task_completed_event_id)
    return out


async def test_issue_15s_filter_splits_its_request_and_keeps_every_item(dev_env: WorkflowEnvironment) -> None:
    """#15's reproduction: 1,500 items each binding a 3,000-character string made a 3 MB request, whose workflow task
    retried until the run's deadline, or forever. It's split, and every item is evaluated."""
    client, store = dev_env.client, MemoryStore()
    g = G()
    g.settings = {"input_schema": strings("s"), "outputs": {"kept": cel("steps.f.output.count")}}
    g.node("f", "flow.filter@1", {"items": list(range(1_500)), "predicate": cel("size(trigger.s) > item")})
    async with serving(client, store):
        handle = await start(client, store, g, {"s": "x" * 3_000})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 1_500})
    assert len(await cel_requests(handle)) >= 3
    assert await task_failures(handle) == []


async def test_a_binding_set_over_the_request_limit_fails_its_step(dev_env: WorkflowEnvironment) -> None:
    """Two 900 KiB strings in one binding set pass 1.75 MiB: the step fails with `input_too_large`; nothing is sent."""
    client, store = dev_env.client, MemoryStore()
    half = 900 * 1024
    g = G()
    g.settings = {"input_schema": strings("a", "b"), "outputs": {"code": ref("steps.t.error.code", default="none")}}
    g.node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.a) + size(trigger.b)")}}, on_error="continue")
    async with serving(client, store):
        handle = await start(client, store, g, {"a": "x" * half, "b": "y" * half})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"})
    assert await cel_requests(handle) == []
    assert await task_failures(handle) == []
