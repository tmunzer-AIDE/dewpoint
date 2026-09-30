# SPDX-License-Identifier: Apache-2.0
"""Engine 2b spec §5.2: every payload the engine sends Temporal, and every result it gets back, stays under Temporal's
payload limit once encoded. Each is checked where it's produced: too large fails its step, its loop or its run with
`payload_too_large`, never a retried or terminated workflow task. The limit is lowered here so small values show it;
test_real_server.py shows it at the real one."""

import asyncio
from typing import Any

import pytest
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime import size
from dewpoint.engine.runtime.activities import RunResult
from dewpoint.engine.runtime.size import OUTPUTS_TOO_LARGE, PAYLOAD_TOO_LARGE
from tests.apps.worker.harness import MemoryStore, run_id_of, start, workers
from tests.support.graphs import G, ref

LIMIT = 50_000
BLOB, LOOP, RUN = "testkit.blob@1", "flow.loop@1", "flow.run_workflow@1"


@pytest.fixture(autouse=True)
def lowered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(size, "PAYLOAD_BYTES", LIMIT)


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


async def finished(env: WorkflowEnvironment, store: MemoryStore, g: G) -> tuple[WorkflowHandle[Any, Any], RunResult]:
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        return handle, await asyncio.wait_for(handle.result(), 60)


async def test_a_step_output_too_large_to_record_fails_the_step_once(env: WorkflowEnvironment) -> None:
    """Its node ran: the row says so (`applied`), and nothing repeats it."""
    store = MemoryStore()
    g = graph(code=ref("steps.b.error.code", default="none"))
    g.node("b", BLOB, {"size": LIMIT}, on_error="continue")
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
    [row] = store.steps(run_id_of(handle))
    assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", PAYLOAD_TOO_LARGE, "applied")


async def test_outputs_too_large_to_return_fail_the_run(env: WorkflowEnvironment) -> None:
    """Each output fits; together they don't. The run fails, and its result carries no outputs."""
    store = MemoryStore()
    g = graph(a=ref("steps.a.output.value"), b=ref("steps.b.output.value"))
    g.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("failed", None)
    assert result.error is not None and (result.error["code"], result.error["message"]) == (
        PAYLOAD_TOO_LARGE,
        OUTPUTS_TOO_LARGE,
    )
    summary = store.runs[run_id_of(handle)]
    assert (summary.status, summary.error_code) == ("failed", PAYLOAD_TOO_LARGE)


async def test_a_sub_flow_whose_outputs_are_too_large_fails_its_step(env: WorkflowEnvironment) -> None:
    """The sub-run fails where its result is produced, so its parent's step fails with it."""
    store = MemoryStore()
    sub = graph(a=ref("steps.a.output.value"), b=ref("steps.b.output.value"))
    sub.node("a", BLOB, {"size": LIMIT // 2}).node("b", BLOB, {"size": LIMIT // 2})
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(store.publish(sub)), "input": {}}, on_error="continue")
    _, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
    [(child, _)] = store.starts.items()
    assert (store.runs[child].status, store.runs[child].error_code) == ("failed", PAYLOAD_TOO_LARGE)


async def test_a_batch_that_collected_too_much_to_return_fails_its_loop(env: WorkflowEnvironment) -> None:
    """A batch of 100 iterations collecting 1,000 characters each: it reports what it used, and its loop fails; no
    collected item is dropped silently."""
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", LOOP, {"items": list(range(150)), "collect": ref("steps.b.output.value")}, on_error="continue")
    g.node("b", BLOB, {"size": 1_000}).edge("l", "b", "body")
    _, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"code": PAYLOAD_TOO_LARGE})
    assert result.iterations == 100  # the batch reported what it used
