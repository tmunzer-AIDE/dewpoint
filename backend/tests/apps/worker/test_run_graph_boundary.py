# SPDX-License-Identifier: Apache-2.0
"""The activity boundary (engine 2b spec §3.6, §3.7). A plugin step's activity resolves the handles in its input,
and splits its output by the node's output schema before returning it: what's sensitive or undeclared, and text that
repeats a secret the run knows, comes back as handles, and its strings join the run tree's secret index. Output that
holds the handle marker is refused. Every message leaving the activity is masked against the index, and so is every
row the projection writes. The workflow checks what arrives: plain data at a sensitive position fails the run."""

from typing import Any

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker.activities import engine_activities
from dewpoint.engine.handles import ClaimRef
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, StepInput, StepResult, step_activity
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import MemoryStore, run, run_id_of, start, workers
from tests.support.graphs import G, ref

SECRET = {"type": "string", "x-sensitive": True}


def graph(schema: dict[str, Any] | None = None, **outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": schema or {"type": "object", "additionalProperties": False}, "outputs": outputs}
    return g


def held(store: MemoryStore, value: Any) -> tuple[Any, bool]:
    found = ClaimRef.of(value)
    assert found is not None and found.pointer == "", value
    claim = store.claims[found.id]
    return claim.value, claim.sensitive_pointers == ("",)


def only_run(store: MemoryStore) -> str:
    [run_id] = list(store.runs)
    return run_id


async def test_a_steps_sensitive_output_is_claimed_and_read_resolved_by_the_next(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(public=ref("steps.s.output.public"), secret=ref("steps.s.output.secret_value"),
              echoed=ref("steps.e.output.value"))  # fmt: skip
    g.node("s", "testkit.sensitive@1").node("e", "testkit.echo@1", {"value": ref("steps.s.output.secret_value")})
    g.edge("s", "e")
    async with workers(env.client, store):
        result = await run(env.client, store, g, {})
    assert result.status == "succeeded", result.error
    assert result.outputs is not None and result.outputs["public"] == "visible"
    assert held(store, result.outputs["secret"]) == ("s3cr3t-value", True)
    # the echo got the value, resolved in its activity; what it returned repeats a secret the run knows: claimed
    assert held(store, result.outputs["echoed"]) == ("s3cr3t-value", True)
    assert {"s3cr3t-value", "pa55word"} <= store.index[only_run(store)]
    rows = {r.node_key: r for r in store.steps(only_run(store))}
    assert "s3cr3t-value" not in repr(rows) and "pa55word" not in repr(rows)


async def test_output_that_holds_the_marker_is_refused(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(code=ref("steps.e.error.code", default="none"))
    g.node("e", "testkit.echo@1", {"value": {"$claim": "not a claim"}}, on_error="continue")
    async with workers(env.client, store):
        result = await run(env.client, store, g, {})
    assert result.status == "succeeded", result.error
    assert result.outputs == {"code": "output_schema_violation"}


async def test_a_message_that_repeats_a_secret_is_masked_before_it_leaves_the_activity(
    env: WorkflowEnvironment,
) -> None:
    store = MemoryStore()
    schema = {"type": "object", "properties": {"tok": SECRET}, "required": ["tok"], "additionalProperties": False}
    g = graph(schema)
    g.node("p", "testkit.ambiguous_send@1", {"outcome": "rejected", "token": ref("trigger.tok")}, on_error="continue")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"tok": "hunter2-hunter2"}, claimed=True)
        result = await handle.result()
    assert result.status == "succeeded", result.error
    [row] = [r for r in store.steps(run_id_of(handle)) if r.node_key == "p"]
    assert row.error_message == "the receiver rejected the request for [redacted]"
    assert row.input_preview["token"] != "hunter2-hunter2"


async def test_plain_data_at_a_sensitive_position_fails_the_run(env: WorkflowEnvironment) -> None:
    """The tripwire (§3.6): a step activity that skipped the boundary returns a secret in plain; the workflow fails the
    run with `internal_error` rather than use it."""

    @activity.defn(name=step_activity("testkit.sensitive@1"))
    async def leaky(_: StepInput) -> StepResult:
        login = {"user": "ops", "password": "pa55word"}
        return StepResult({"public": "visible", "secret_value": "s3cr3t-value", "login": login})

    store = MemoryStore()
    g = graph()
    g.node("s", "testkit.sensitive@1")
    worker = Worker(env.client, task_queue=ENGINE_QUEUE, workflows=[RunGraph, LoopBatch],
                    activities=[*engine_activities(store, []), leaky])  # fmt: skip
    async with worker:
        handle = await start(env.client, store, g, {})
        result = await handle.result()
    assert (result.status, result.error and result.error["code"]) == ("failed", "internal_error")
    assert "s3cr3t-value" not in repr(store.rows) + repr(store.runs)
