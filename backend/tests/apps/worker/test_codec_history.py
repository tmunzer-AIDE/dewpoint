# SPDX-License-Identifier: Apache-2.0
"""Engine 2b spec §6.2: every payload a run puts in Temporal's history is encrypted with its tenant's key — the start
and the result, a sub-flow's, a batch's, a `cel.evaluate` request's, every activity's input and result, local
activities' markers. A canary in the trigger reaches all of them, and no history holds it in plain text."""

import asyncio

from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.codec import ENCODING
from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, start, workers
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref

CANARY = "canary-4f1b2c9e-never-in-plain-text"
SECRET = {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]}


def echoed() -> G:
    sub = G()
    sub.settings = {"input_schema": SECRET, "outputs": {"s": ref("steps.e.output.value")}}
    return sub.node("e", "testkit.echo@1", {"value": ref("trigger.s")})


async def test_no_history_of_a_run_holds_its_payloads_in_plain_text(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = G()
    outputs = {"sub": ref("steps.r.output.s"), "cel": ref("steps.c.output.value"), "items": ref("steps.l.output.items")}
    g.settings = {"input_schema": SECRET, "outputs": outputs}
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(echoed())), "input": {"s": ref("trigger.s")}})
    g.node("c", "testkit.echo@1", {"value": cel(f"{EVALUATOR_ONLY} == 1 ? trigger.s : ''")})  # the evaluator's
    g.node("l", "flow.loop@1", {"items": list(range(101)), "collect": ref("steps.x.output.value")})  # a batch
    g.node("x", "testkit.echo@1", {"value": ref("trigger.s")}).edge("l", "x", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"s": CANARY})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    assert result.outputs == {"sub": CANARY, "cel": CANARY, "items": [CANARY] * 101}  # the client decrypts it
    types = [h.events[0].workflow_execution_started_event_attributes.workflow_type.name for h in histories]
    assert types.count("RunGraph") == 2 and "LoopBatch" in types  # the run, its sub-flow, its batches
    for history in histories:
        raw = b"".join(e.SerializeToString() for e in history.events)
        assert ENCODING in raw and CANARY.encode() not in raw, history.workflow_id
