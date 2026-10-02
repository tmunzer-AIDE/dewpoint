# SPDX-License-Identifier: Apache-2.0
"""The canary secrets (engine 2b spec §12), 2b-1b's part. A run is seeded with two known secrets: one in its trigger,
claimed at admission, and one a plugin step outputs at a sensitive position. Both travel through plugin steps, CEL in
the evaluator, a sub-flow, a batched loop, a filter, a spill, a failure message and a plugin's crash. Decrypted, no
payload of any of the run's histories holds either; nor does any row the projection writes, nor any log line. They
did travel: the run's outputs read them back through its claims.

A secret a plugin makes itself is unknown to the run until its output is claimed: a log line, a crash or a failure
before then can't be masked against anything. So no log holds text that isn't proven to be code (§6.7): the focused
canaries below leak a fresh secret each way before it's claimed."""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from typing import Any

import pytest
import structlog
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.worker.activities import MESSAGE_WITHHELD, NODE_FAILED
from dewpoint.apps.worker.logs import UNNAMED
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
LEAKY_SEED = "canary-leaky-"  # a literal of the graph; the plugin's token isn't, nor one of its code
TOKEN = (LEAKY_SEED + "t" * 24)[:24]  # what testkit.leaky makes from it
IDENT = TOKEN.replace("-", "_")  # the same, as a valid identifier: a class name, a code


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
    assert result.outputs["failed"] == MESSAGE_WITHHELD  # the plugin's computed message: never shown
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


@dataclass
class Observed:
    result: Any
    plain: str  # every payload of every history, decrypted
    rows: str  # every row the projection wrote
    logs: str  # every log line, structured and not
    entries: list[dict[str, Any]]  # the structured ones


async def observed(env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture, g: G) -> Observed:
    store = MemoryStore()
    caplog.set_level(logging.DEBUG)
    with structlog.testing.capture_logs() as entries:
        async with workers(env.client, store):
            handle = await start(env.client, store, g, {}, claimed=True)
            result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
            histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    rows = [asdict(r) for r in store.rows.values()] + [asdict(r) for r in store.runs.values()]
    logs = json.dumps(entries, default=str) + caplog.text
    return Observed(result, await decoded(histories), json.dumps(rows, default=str), logs, list(entries))


def leaky(how: str, **outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object", "additionalProperties": False}, "outputs": outputs}
    on_error = "fail" if how == "log" else "continue"  # a step that logs and returns, or one that fails
    g.node("k", "testkit.leaky@1", {"seed": LEAKY_SEED, "size": len(TOKEN), "how": how}, on_error=on_error)
    g.nodes[-1]["options"]["max_attempts"] = 1
    return g


def entry(seen: Observed, event: str) -> dict[str, Any]:
    [found] = [e for e in seen.entries if e.get("event") == event]
    return found


async def test_a_secret_a_plugin_logs_before_its_claimed_never_reaches_the_log(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """A plugin logs its fresh token in an event, a neutral field, a nested value and a field's name, then returns it
    at a sensitive position. Only the plugin's own constants are logged: the computed event is withheld, its fields'
    computed values redacted, a computed field name dropped; a boolean and a constant value stay."""
    seen = await observed(env, caplog, leaky("log", token=ref("steps.k.output.token")))
    assert seen.result.status == "succeeded", seen.result.error
    withheld = entry(seen, "step_event_withheld")
    assert (withheld["detail"], withheld["nested"], withheld["ok"], withheld["fields_withheld"]) == (
        "[redacted]", "[redacted]", True, 1,
    )  # fmt: skip
    issued = entry(seen, "token_issued")
    assert (issued["detail"], issued["ok"], issued["size"], issued["kind"]) == (
        "[redacted]",
        True,
        "[redacted]",
        "bearer",
    )
    for where in (seen.plain, seen.rows, seen.logs):
        assert TOKEN not in where


async def test_a_crash_quoting_a_secret_never_claimed_logs_its_type_and_place_only(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """A plugin crashes quoting a token it made and never returned: no index knows it. The worker logs the bug's type
    and where it was raised, never its text; the step's message names only the type."""
    seen = await observed(env, caplog, leaky("crash", said=ref("steps.k.error.message", default="")))
    assert seen.result.outputs == {"said": "The node raised RuntimeError."}
    bug = entry(seen, "step_unexpected_error")
    assert bug["error_type"] == "RuntimeError" and "error" not in bug
    assert any(w.startswith("testkit.py:run:") for w in bug["where"])
    for where in (seen.plain, seen.rows, seen.logs):
        assert TOKEN not in where


async def test_a_crash_whose_class_a_plugin_named_with_a_secret_never_shows_that_name(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """A plugin raises an exception of a class it made at run time, named with its fresh token as an identifier. A
    class name is text too: it's shown only when it's proven to be code (a builtin, or a name its module's code
    declares), so the step says "an exception" and the log withholds the type."""
    seen = await observed(env, caplog, leaky("crash_class", said=ref("steps.k.error.message", default="")))
    assert seen.result.outputs == {"said": f"The node raised {UNNAMED}."}
    assert entry(seen, "step_unexpected_error")["error_type"] == UNNAMED
    for where in (seen.plain, seen.rows, seen.logs):
        assert IDENT not in where


@pytest.mark.parametrize(
    ("how", "code", "message"),
    [
        ("fail", "leaky_failed", MESSAGE_WITHHELD),  # a computed message: the generic one instead, its code kept
        ("fail_code", NODE_FAILED, "the token was refused"),  # a computed code, a valid identifier: the generic one
    ],
)
async def test_a_failure_quoting_a_secret_never_claimed_shows_only_the_plugins_constants(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture, how: str, code: str, message: str
) -> None:
    """A plugin fails quoting a token it made and never returned, in its message, or as its code shaped as a valid
    identifier. No index knows the token, so masking proves nothing: a failure's code is shown only when it's a safe
    identifier its plugin's code declares, its message only when it's a constant of that code, and a generic one stands
    for either otherwise. The retry behavior stays its error class's. Temporal's record of the failed attempt keeps
    only its fixed text. The token reaches no history, row or log."""
    seen = await observed(env, caplog, leaky(how, code=ref("steps.k.error.code", default=""),
                                             said=ref("steps.k.error.message", default="")))  # fmt: skip
    assert seen.result.outputs == {"code": code, "said": message}
    assert "Completing activity as failed" in seen.logs
    for where in (seen.plain, seen.rows, seen.logs):
        assert TOKEN not in where and IDENT not in where
