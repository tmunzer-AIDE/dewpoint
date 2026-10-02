# SPDX-License-Identifier: Apache-2.0
"""The canary secrets (engine 2b spec §12), 2b-1b's part. A run is seeded with two known secrets: one in its trigger,
claimed at admission, and one a plugin step outputs at a sensitive position. Both travel through plugin steps, CEL in
the evaluator, a sub-flow, a batched loop, a filter, a spill, a failure message and a plugin's crash. Decrypted, no
payload of any of the run's histories holds either; nor does any row the projection writes, nor any log line. They
did travel: the run's outputs read them back through its claims."""

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

import pytest
import structlog
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.handles import resolve_value
from dewpoint.engine.runtime import size
from tests.apps.worker.harness import (
    EVALUATOR_ONLY,
    RESULT_TIMEOUT_S,
    TENANT,
    MemoryStore,
    decoded,
    run_id_of,
    start,
    workers,
)
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, nid, ref

IN_TRIGGER = "canary-in-the-trigger-7d2f"
SEED = "canary-from-a-plugin-"  # a literal of the graph, which its history holds: only the seed
FROM_A_PLUGIN = SEED + "s" * 9  # what the plugin outputs: never in the graph
CANARIES = (IN_TRIGGER, FROM_A_PLUGIN)
SECRET = {"type": "string", "x-sensitive": True}
ECHO, SLOW_ECHO, BLOB = "testkit.echo@1", "testkit.slow_echo@1", "testkit.blob@1"
LIMIT, INLINE, BLOBS, EACH = 50_000, 10_000, 6, 9_000  # six blobs: together past the lowered payload limit


@pytest.fixture(autouse=True)
def lowered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The payload and inline limits lowered, as the spill tests lower them, so small values spill."""
    monkeypatch.setattr(size, "PAYLOAD_BYTES", LIMIT)
    monkeypatch.setattr(size, "INLINE_LIMIT", INLINE)


def schema(name: str) -> dict[str, Any]:
    return {"type": "object", "properties": {name: SECRET}, "required": [name], "additionalProperties": False}


def child() -> G:
    """A sub-flow that echoes its sensitive input back as its output."""
    g = G()
    g.settings = {"input_schema": schema("s"), "outputs": {"s": ref("steps.e.output.value")}}
    return g.node("e", ECHO, {"value": ref("trigger.s")})


def seeded(store: MemoryStore) -> G:
    g = G()
    g.settings = {
        "input_schema": schema("token"),
        "outputs": {
            "echoed": ref("steps.e.output.value"),
            "joined": ref("steps.c.output.v"),
            "sub": ref("steps.r.output.s"),
            "items": ref("steps.l.output.items"),
            "kept": ref("steps.f.output.count"),
            "spilled": ref("steps.s.output.value"),
            "failed": ref("steps.x.error.message", default=""),
            "crashed": ref("steps.y.error.message", default=""),
        },
        "declassify": [{"node": str(nid("f")), "field": "/predicate"}],  # the count is plain: a listed site
    }
    g.node("p", "testkit.secret_blob@1", {"seed": SEED, "size": len(FROM_A_PLUGIN)})  # a sensitive output
    g.node("e", ECHO, {"value": {"t": ref("trigger.token"), "p": ref("steps.p.output.token")}}).edge("p", "e")
    joined = cel(f"{EVALUATOR_ONLY} > 0 ? trigger.token + '/' + steps.p.output.token : ''")  # in the evaluator
    g.node("c", "flow.transform@1", {"fields": {"v": joined}}).edge("p", "c")
    sub = {"workflow_id": str(store.publish(child())), "input": {"s": ref("steps.p.output.token")}}
    g.node("r", "flow.run_workflow@1", sub).edge("p", "r")
    g.node("l", "flow.loop@1", {"items": list(range(101)), "collect": ref("steps.i.output.value")})  # in batches
    g.node("i", ECHO, {"value": ref("trigger.token")}).edge("l", "i", "body")
    g.node("f", "flow.filter@1", {"items": ["a", "b"], "predicate": cel("item != trigger.token")})
    blobs = [f"b{k}" for k in range(BLOBS)]
    for b in blobs:
        g.node(b, BLOB, {"size": EACH})
    big = [ref(f"steps.{b}.output.value") for b in blobs] + [ref("trigger.token"), ref("steps.p.output.token")]
    g.node("s", ECHO, {"value": big}).edge("p", "s")  # an input too large to send: it spills
    for b in blobs:
        g.edge(b, "s")
    g.node("x", SLOW_ECHO, {"seconds": 0, "value": ref("trigger.token"), "fail": True}, on_error="continue")
    g.node("y", SLOW_ECHO, {"seconds": 0, "value": ref("steps.p.output.token"), "crash": True}, on_error="continue")
    g.nodes[-1]["options"]["max_attempts"] = 1
    return g.edge("p", "y")


async def test_no_history_projection_or_log_of_a_canary_run_holds_its_secrets(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    store = MemoryStore()
    g = seeded(store)
    caplog.set_level(logging.DEBUG)
    with structlog.testing.capture_logs() as logged:
        async with workers(env.client, store):
            handle = await start(env.client, store, g, {"token": IN_TRIGGER}, claimed=True)
            result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
            histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    assert result.status == "succeeded", result.error
    assert result.outputs is not None

    # they travelled: read back through the run's own claims and grants, every path holds its secret
    async def fetch(claim_id: str) -> Any:
        return await store.fetch(TENANT, run_id_of(handle), claim_id)

    outputs = (await resolve_value(result.outputs, fetch)).value
    assert outputs["echoed"] == {"t": IN_TRIGGER, "p": FROM_A_PLUGIN}
    assert outputs["joined"] == f"{IN_TRIGGER}/{FROM_A_PLUGIN}"
    assert outputs["sub"] == FROM_A_PLUGIN
    assert outputs["items"] == [IN_TRIGGER] * 101
    assert outputs["kept"] == 2
    assert outputs["spilled"] == ["x" * EACH] * BLOBS + [IN_TRIGGER, FROM_A_PLUGIN]
    assert result.outputs["failed"] == "failed on [redacted]"  # masked where it left the activity
    assert result.outputs["crashed"] == "The node raised RuntimeError."
    types = [h.events[0].workflow_execution_started_event_attributes.workflow_type.name for h in histories]
    assert types.count("RunGraph") == 2 and "LoopBatch" in types  # the run, its sub-flow, its batches
    assert any(c.kind == "spill" for c in store.claims.values())

    plain = await decoded(histories)  # every payload Temporal holds, decrypted
    rows = json.dumps(
        [asdict(r) for r in store.rows.values()]
        + [asdict(r) for r in store.runs.values()]
        + [asdict(r) for r in store.starts.values()],
        default=str,
    )
    logs = json.dumps(logged, default=str) + caplog.text
    assert "step_unexpected_error" in logs  # the crash was logged
    for canary in CANARIES:
        assert canary not in plain, canary
        assert canary not in rows, canary
        assert canary not in logs, canary
