# SPDX-License-Identifier: Apache-2.0
"""The activity boundary (engine 2b spec §3.6, §3.7). A plugin step's activity resolves the handles in its input,
and splits its output by the node's output schema before returning it: what's sensitive or undeclared, and text that
repeats a secret the run knows, comes back as handles, and its strings join the run tree's secret index. Output that
holds the handle marker is refused. Every message leaving the activity is masked against the index, and so is every
row the projection writes. The workflow checks what arrives: plain data at a sensitive position fails the run."""

import uuid
from collections.abc import Iterator
from typing import Any

from temporalio import activity
from temporalio.api.common.v1 import Payload
from temporalio.converter import WorkflowSerializationContext
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.codec import ENCODING, TENANT, TenantCodec
from dewpoint.apps.worker.activities import engine_activities
from dewpoint.engine.handles import ClaimRef
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, StepInput, StepResult, step_activity
from dewpoint.engine.runtime.ids import run_workflow_id
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import MemoryStore, run, run_id_of, start, workers
from tests.engine.replay.record import executions
from tests.support.graphs import G, ref, template
from tests.support.keys import FixtureKeys

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
    assert {"s3cr3t-value", "pa55word"} <= store.index_of[only_run(store)]
    rows = {r.node_key: r for r in store.steps(only_run(store))}
    assert "s3cr3t-value" not in repr(rows) and "pa55word" not in repr(rows)


async def test_output_that_holds_the_marker_is_refused(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(
        {"type": "object", "properties": {"x": {}}, "required": ["x"]}, code=ref("steps.e.error.code", default="none")
    )
    g.node("e", "testkit.echo@1", {"value": ref("trigger.x")}, on_error="continue")
    async with workers(env.client, store):  # unclaimed, as admission would refuse it: a node's output may hold it
        result = await run(env.client, store, g, {"x": {"$claim": "not a claim"}})
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


async def test_a_secret_indexed_while_a_step_runs_is_claimed_and_masked_at_its_boundary(
    env: WorkflowEnvironment,
) -> None:
    """Engine 2b spec §3.7: the index a step read before its attempt can be stale at its end, when another activity
    indexed a secret meanwhile. Its output and its message are checked against the index as it is at the boundary."""
    store = MemoryStore()
    note = {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"],
            "additionalProperties": False}  # fmt: skip
    g = graph(note, echoed=ref("steps.a.output.value"), said=ref("steps.f.error.message", default="none"))
    g.node("a", "testkit.slow_echo@1", {"seconds": 3, "value": ref("trigger.note")})
    g.node("f", "testkit.slow_echo@1", {"seconds": 3, "value": ref("trigger.note"), "fail": True}, on_error="continue")
    g.node("w", "testkit.slow@1", {"seconds": 1})  # `a` and `f` have read the index by then
    g.node("s", "testkit.secret_blob@1", {"seed": "hunter2-hunter2", "size": 15}).edge("w", "s")  # indexes it
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"note": "hunter2-hunter2"}, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs is not None
    assert held(store, result.outputs["echoed"]) == ("hunter2-hunter2", True)  # claimed: it repeats a secret
    assert result.outputs["said"] == "failed on [redacted]"  # masked before it left the activity


def _payloads(message: Any) -> Iterator[Payload]:
    for field, value in message.ListFields():
        if field.type != field.TYPE_MESSAGE:
            continue
        if field.message_type.GetOptions().map_entry:
            items = list(value.values())
        else:
            items = [value] if hasattr(value, "ListFields") else list(value)  # one message, or a repeated field
        for item in items:
            if isinstance(item, Payload):
                yield item
            elif hasattr(item, "ListFields"):
                yield from _payloads(item)


async def decoded(histories: Any) -> str:
    """Every payload of every history, decrypted with the fixture keys: what Temporal holds, in plain text. It takes
    each payload's tenant from its metadata, which only a test may do (the codec never does)."""
    out = []
    for history in histories:
        for event in history.events:
            for payload in _payloads(event):
                if payload.metadata.get("encoding") == ENCODING:
                    workflow_id = run_workflow_id(payload.metadata[TENANT].decode(), str(uuid.UUID(int=0)))
                    codec = TenantCodec(FixtureKeys()).with_context(
                        WorkflowSerializationContext("default", workflow_id)
                    )
                    [payload] = await codec.decode([payload])
                out.append(payload.data.decode(errors="replace"))
    return "\n".join(out)


async def test_a_failure_message_that_repeats_a_secret_is_masked_in_the_result_and_in_history(
    env: WorkflowEnvironment,
) -> None:
    """A failure's message is built in the workflow (`flow.fail`), from data publish can't see is sensitive: here a
    field only its size claimed, whose text holds a secret the run learns later. The text is resolved where the claim
    is read, and it repeats a secret the run knows, so it comes back claimed; the message is masked against the index
    before it becomes the run's error, its result's and its failure handler's trigger's (engine 2b spec §3.6, §3.7).
    Neither the result nor any payload of the run's histories holds the secret, decrypted."""
    notes = "s3cr3t-value then " + "x" * 70_000  # past 64 KiB: claimed for its size at admission
    schema = {"type": "object", "properties": {"notes": {"type": "string"}}, "required": ["notes"],
              "additionalProperties": False}  # fmt: skip
    store = MemoryStore()
    g = graph(schema)
    g.settings["failure_handler"] = str(store.publish(graph().node("h", "testkit.echo@1", {"value": 1})))
    g.node("s", "testkit.sensitive@1")  # the run learns s3cr3t-value here
    g.node("f", "flow.fail@1", {"message": template("gave up: ", {"ref": "trigger.notes"})}).edge("s", "f")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"notes": notes}, claimed=True)
        result = await handle.result()
        histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    assert result.status == "failed" and result.error is not None and result.error["code"] == "workflow_failed"
    # the joined text repeated a secret, so it came back claimed, tainted: every string of it is a secret now (§3.7)
    assert result.error["message"] == "[redacted]"
    assert len(histories) >= 2  # the run, and its failure handler
    plain = await decoded(histories)
    assert "workflow_failed" in plain and "[redacted]" in plain  # decrypted: the result and the handler's trigger
    assert "s3cr3t-value" not in plain
