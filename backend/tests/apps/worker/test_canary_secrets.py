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
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from temporalio.api.enums.v1 import EventType
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner

from dewpoint.apps.worker.activities import MESSAGE_WITHHELD, NODE_FAILED
from dewpoint.apps.worker.logs import UNNAMED
from dewpoint.engine.handles import resolve_value
from dewpoint.engine.runtime import size
from dewpoint.engine.runtime import workflow as run_graph
from dewpoint.engine.runtime.activities import CLAIMS_CHILD_INPUT
from dewpoint.sdk import Empty, StepContext
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
from tests.support.plugins.testkit import Slow, SlowConfig

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
PIN = 100_000 + sum(map(ord, TOKEN))  # a number made from it, as testkit.leaky's forged traceback carries it


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
    run_id: str
    histories: list[Any]
    plain: str  # every payload of every history, decrypted
    rows: str  # every row the projection wrote
    logs: str  # every log line, structured and not
    entries: list[dict[str, Any]]  # the structured ones


async def observed(
    env: WorkflowEnvironment,
    caplog: pytest.LogCaptureFixture,
    g: G,
    trigger: dict[str, Any] | None = None,
    store: MemoryStore | None = None,
) -> Observed:
    store = store or MemoryStore()
    caplog.set_level(logging.DEBUG)
    with structlog.testing.capture_logs() as entries:
        async with workers(env.client, store):
            handle = await start(env.client, store, g, trigger or {}, claimed=True)
            result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
            histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    rows = [asdict(r) for r in store.rows.values()] + [asdict(r) for r in store.runs.values()]
    logs = json.dumps(entries, default=str) + caplog.text
    plain = await decoded(histories)
    return Observed(result, run_id_of(handle), histories, plain, json.dumps(rows, default=str), logs, list(entries))


async def results_of(histories: list[Any], activity: str) -> str:
    """The results of every `activity` attempt in the histories, decrypted."""
    done = []
    for h in histories:
        scheduled = {
            e.event_id: e.activity_task_scheduled_event_attributes.activity_type.name
            for e in h.events
            if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
        }
        done += [
            e
            for e in h.events
            if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED
            and scheduled.get(e.activity_task_completed_event_attributes.scheduled_event_id) == activity
        ]
    return await decoded([SimpleNamespace(events=done)])


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


async def test_a_crash_whose_traceback_a_plugin_forged_never_logs_its_line(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """A plugin raises with a traceback it built itself, whose line is a number made from its fresh token: Python
    keeps a caller's traceback through `raise`. A frame's line is logged only when the frame's function, compiled from
    its module's source, has that line; the forged one names the place without it."""
    seen = await observed(env, caplog, leaky("crash_forged", said=ref("steps.k.error.message", default="")))
    assert seen.result.outputs == {"said": "The node raised RuntimeError."}
    where = entry(seen, "step_unexpected_error")["where"]
    assert "testkit.py:run" in where  # the forged frame: its place, not its line
    assert any(w.startswith("testkit.py:run:") for w in where)  # the real raise: its line, proven
    assert f":{PIN}" not in seen.logs


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


MAP_KEY = "canary-map-key-5c1e"  # a secret the run's input holds as a key, not a value


async def test_a_sub_flow_input_refused_under_a_secret_key_never_names_the_key(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """A parent passes a sensitive map to a child whose sensitive field wants integer values: an object for an object
    passes publish, but a string under a secret key fails the child's check at the crossing (§3.5). The refusal names
    each place as far as the child's schema declares it: the key, data the input supplied, shows as `*`, in the
    crossing's result, the step's message, the decrypted history, the rows and the logs."""
    store = MemoryStore()
    creds = {"type": "object", "x-sensitive": True}
    numbers = {**creds, "additionalProperties": {"type": "integer"}}
    child = G()
    child.settings = {
        "input_schema": {"type": "object", "properties": {"creds": numbers}, "required": ["creds"],
                         "additionalProperties": False},
        "outputs": {},
    }  # fmt: skip
    child.node("e", ECHO, {"value": 1})
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"creds": creds}, "required": ["creds"],
                         "additionalProperties": False},
        "outputs": {"said": ref("steps.r.error.message", default="")},
    }  # fmt: skip
    sub = {"workflow_id": str(store.publish(child)), "input": {"creds": ref("trigger.creds")}}
    g.node("r", "flow.run_workflow@1", sub, on_error="continue")
    seen = await observed(env, caplog, g, {"creds": {MAP_KEY: "not-an-integer"}}, store)
    why = "at creds.*: it breaks `type`"
    assert why in seen.result.outputs["said"]
    crossing = await results_of(seen.histories, CLAIMS_CHILD_INPUT)
    assert why in crossing and MAP_KEY not in crossing
    for where in (seen.plain, seen.rows, seen.logs):
        assert MAP_KEY not in where


SECRET_KEY = "sk-k3y-canary-0002"  # a secret the run's input holds as a map key, at a position its schema leaves open


async def test_a_secret_map_key_reaches_no_history_row_or_log_and_declared_fields_still_read(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """Review finding C1: a map's keys are data, and one at a position the schema doesn't declare can be a secret. The
    map is claimed whole, so the key never enters the run; a step echoes the map, a sub-flow gets it through its
    grants and returns it, and a reference to a declared sibling still reads it plain. Decrypted, no history, row or
    log line holds the key; the run's outputs read it back through its claims."""
    store = MemoryStore()
    creds = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"],
             "additionalProperties": {"type": "string"}}  # fmt: skip
    child = G()
    child.settings = {
        "input_schema": {"type": "object", "properties": {"c": {**creds, "x-sensitive": True}}, "required": ["c"],
                         "additionalProperties": False},
        "outputs": {"c": ref("steps.e.output.value")},
    }  # fmt: skip
    child.node("e", ECHO, {"value": ref("trigger.c")})
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"c": creds}, "required": ["c"],
                         "additionalProperties": False},
        "outputs": {"echoed": ref("steps.e.output.value"), "sub": ref("steps.r.output.c"),
                    "name": ref("steps.n.output.value")},
    }  # fmt: skip
    g.node("e", ECHO, {"value": ref("trigger.c")})
    g.node("n", ECHO, {"value": ref("trigger.c.name")})
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(child)), "input": {"c": ref("trigger.c")}})
    seen = await observed(env, caplog, g, {"c": {"name": "ann", SECRET_KEY: "prod"}}, store)
    assert seen.result.status == "succeeded", seen.result.error

    async def fetch(claim_id: str) -> Any:
        return await store.fetch(TENANT, seen.run_id, claim_id)

    outputs = (await resolve_value(seen.result.outputs, fetch)).value
    assert outputs == {"echoed": {"name": "ann", SECRET_KEY: "prod"}, "sub": {"name": "ann", SECRET_KEY: "prod"},
                       "name": "ann"}  # fmt: skip
    for where in (seen.plain, seen.rows, seen.logs):
        assert SECRET_KEY not in where


ECHOED_KEY = "sk-k3y-echoed-canary-0003"  # a secret map key that a declared sibling field repeats


async def test_a_secret_map_key_a_sibling_field_repeats_reaches_no_history_row_or_log(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """The owner's re-review of C1: a declared, plain field that repeats an undeclared map key stayed plain in the run's
    start, because the keys were collected after the reappearing-text check. The key is a secret before the rest is
    checked: the sibling is claimed, and the map's declared field still reads plain. Decrypted, no history, row or log
    line holds the key; the run's outputs read the sibling back through its claim."""
    open_map = {"type": "object", "properties": {"env": {"type": "string"}}, "required": ["env"],
                "additionalProperties": {"type": "string"}}  # fmt: skip
    store, g = MemoryStore(), G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"c": open_map, "note": {"type": "string"}},
                         "required": ["c", "note"], "additionalProperties": False},
        "outputs": {"note": ref("trigger.note"), "env": ref("steps.n.output.value")},
    }  # fmt: skip
    g.node("n", ECHO, {"value": ref("trigger.c.env")})
    seen = await observed(env, caplog, g, {"c": {"env": "prod", ECHOED_KEY: "x"}, "note": ECHOED_KEY}, store)
    assert seen.result.status == "succeeded", seen.result.error
    assert seen.result.outputs["env"] == "prod"  # a declared field of the map, read plain

    async def fetch(claim_id: str) -> Any:
        return await store.fetch(TENANT, seen.run_id, claim_id)

    assert (await resolve_value(seen.result.outputs, fetch)).value == {"note": ECHOED_KEY, "env": "prod"}
    for where in (seen.plain, seen.rows, seen.logs):
        assert ECHOED_KEY not in where


DECIDED = "sk-l3ak-canary-0001"  # a sensitive value a listed condition evaluates to, instead of a boolean


async def test_a_listed_decision_that_isnt_a_boolean_reveals_nothing(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture
) -> None:
    """Review finding I1: a listed site reveals its decision, the branch taken, never a value. A condition whose CEL
    evaluates to the sensitive value itself (publish can't type a field the schema leaves open) fails its step
    `type_mismatch` in the activity, with a fixed message: the value reaches no history, row or log line."""
    store = MemoryStore()
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"cfg": {"type": "object"}}, "required": ["cfg"],
                         "additionalProperties": False},
        "outputs": {"said": ref("steps.i.error.code", default="")},
        "declassify": [{"node": str(nid("i")), "field": "/condition"}],
    }  # fmt: skip
    g.node("i", "flow.if@1", {"condition": cel("trigger.cfg.enabled")}, on_error="continue")
    seen = await observed(env, caplog, g, {"cfg": {"enabled": DECIDED}}, store)
    assert seen.result.outputs == {"said": "type_mismatch"}
    for where in (seen.plain, seen.rows, seen.logs):
        assert DECIDED not in where


async def test_a_secret_a_plugin_heartbeats_never_reaches_history(
    own_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding (M5): Temporal keeps an attempt's last heartbeat details, and a timeout writes them into the
    run's history (`last_heartbeat_details`). A plugin's details are its own data, a secret it holds too: the
    boundary sends none."""
    beat = "canary-heartbeat-5c1e"

    async def run(self: Slow, ctx: StepContext, config: SlowConfig) -> Empty:
        ctx.heartbeat({"cursor": beat})
        await asyncio.sleep(config.seconds)
        return Empty()

    monkeypatch.setattr(Slow, "run", run)
    store, g = MemoryStore(), G()
    g.settings = {"input_schema": {"type": "object", "additionalProperties": False}, "outputs": {}}
    g.node("s", "testkit.slow@1", {"seconds": 3})
    g.nodes[0]["options"].update(timeout_s=1, max_attempts=1)
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        histories = await executions(own_env.client, handle.id, handle.first_execution_run_id or "")
    assert result.status == "failed" and result.error is not None and result.error["code"] == "timeout"
    assert beat not in await decoded(histories)


IN_A_BUG = "canary-in-a-bug-3e9a"  # what the workflow's own exception quotes: the run's data, say


async def bug_logged(env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture, event: str) -> logging.LogRecord:
    """A run whose workflow code raises an exception quoting IN_A_BUG, outside the sandbox so a test can break it:
    the record the workflow logs for it. No log line holds the exception's text."""
    caplog.set_level(logging.DEBUG)
    store, g = MemoryStore(), G()
    g.settings = {"input_schema": {"type": "object", "additionalProperties": False}, "outputs": {}}
    g.node("e", ECHO, {"value": 1})
    with structlog.testing.capture_logs() as entries:
        async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
            handle = await start(env.client, store, g, {})
            result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "failed", result
    assert IN_A_BUG not in caplog.text + json.dumps(entries, default=str)
    [record] = [r for r in caplog.records if r.getMessage().startswith(event)]
    return record


async def test_a_bug_in_the_workflow_logs_its_type_and_place_never_its_text(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding (M6): the workflow logged its own bugs with their tracebacks, whose text may quote the run's
    data. As the activities' bugs are (§6.7), each is logged by its type and where it was raised, never its text."""

    async def outputs(self: run_graph.RunGraph) -> dict[str, Any]:
        raise RuntimeError(f"no outputs for {IN_A_BUG}")

    monkeypatch.setattr(run_graph.RunGraph, "_outputs", outputs)
    bug = await bug_logged(env, caplog, "run_internal_error")
    assert bug.exc_info is None and getattr(bug, "error_type", None) == "RuntimeError"
    assert any(w.startswith("test_canary_secrets.py:outputs:") for w in getattr(bug, "where", []))


async def test_a_version_the_workflow_cant_compile_logs_its_type_and_place_never_its_text(
    env: WorkflowEnvironment, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def compiled(data: Any) -> Any:
        raise ValueError(f"can't compile {IN_A_BUG}")

    monkeypatch.setattr(run_graph, "program_of", compiled)
    bug = await bug_logged(env, caplog, "run_version_unusable")
    assert bug.exc_info is None and getattr(bug, "error_type", None) == "ValueError"
    assert any(w.startswith("test_canary_secrets.py:compiled:") for w in getattr(bug, "where", []))
