# SPDX-License-Identifier: Apache-2.0
"""Reading handles in a run (engine 2b spec §3.2–3.4, §4.2). The trigger is claimed as admission claims it: its
sensitive values are handles. The workflow never reads a claim: a reference past a handle extends its pointer (and a
pointer past POINTER_MAX derives a claim in an activity); CEL and templates over handles go to `cel.evaluate`, whose
activity resolves them against their rows, and claims a result that read sensitive data."""

import uuid
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.handles import POINTER_MAX, ClaimRef
from tests.apps.worker.harness import MemoryStore, run, workers
from tests.support.graphs import G, cel, nid, ref, template

SECRET = {"type": "string", "x-sensitive": True}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"token": SECRET, "name": {"type": "string"}},
    "required": ["token", "name"],
    "additionalProperties": False,
}
TRIGGER = {"token": "s3cr3t-token", "name": "ann"}


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


def claimed(store: MemoryStore, value: Any) -> tuple[Any, bool]:
    """A handle's claim, as the store holds it: its value and whether it's tainted."""
    found = ClaimRef.of(value)
    assert found is not None and found.pointer == "", value
    held = store.claims[found.id]
    return held.value, held.sensitive_pointers == ("",)


async def test_cel_over_a_sensitive_value_runs_in_the_evaluator_and_its_result_is_claimed(
    env: WorkflowEnvironment,
) -> None:
    store = MemoryStore()
    g = graph(n=ref("steps.t.output.n"), plain=ref("steps.t.output.plain"))
    g.node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.token)"), "plain": cel("size(trigger.name)")}})
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs is not None and result.outputs["plain"] == 3  # untainted: as before
    assert claimed(store, result.outputs["n"]) == (12, True)
    [row] = [r for r in store.steps(result_run(store)) if r.node_key == "t"]
    assert row.cel_mode == "activity"


async def test_a_template_over_a_sensitive_value_is_joined_in_the_activity(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(auth=ref("steps.t.output.auth"), hi=ref("steps.t.output.hi"))
    fields = {"auth": template("Bearer ", {"ref": "trigger.token"}), "hi": template("hi ", {"ref": "trigger.name"})}
    g.node("t", "flow.transform@1", {"fields": fields})
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs is not None and result.outputs["hi"] == "hi ann"
    assert claimed(store, result.outputs["auth"]) == ("Bearer s3cr3t-token", True)


async def test_a_reference_past_a_handle_extends_it_and_a_long_one_derives_a_claim(env: WorkflowEnvironment) -> None:
    long_key = "k" * POINTER_MAX
    login = {"type": "object", "x-sensitive": True, "properties": {"user": {"type": "string"}, long_key: SECRET},
             "required": ["user", long_key]}  # fmt: skip
    store = MemoryStore()
    g = G()
    g.settings = {
        "input_schema": {
            "type": "object",
            "properties": {"login": login},
            "required": ["login"],
            "additionalProperties": False,  # declared: only `login` is claimed, not the whole trigger
        },
        "outputs": {"user": ref("trigger.login.user"), "deep": ref(f"trigger.login.{long_key}")},
    }
    g.node("e", "testkit.echo@1", {"value": 1})
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"login": {"user": "ops", long_key: "pa55word"}}, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs is not None
    user = ClaimRef.of(result.outputs["user"])
    assert user is not None and user.pointer == "/user"  # extended: the workflow never read the claim
    assert claimed(store, result.outputs["deep"]) == ("pa55word", True)  # derived: a claim of its own


async def test_a_handle_to_a_claim_the_run_may_not_read_fails_its_step(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    other = store.claim("someone else's", owner=str(uuid.uuid4()), tainted=True)  # another run's claim
    g = graph(n=ref("steps.t.output.n", default=-1))
    g.node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.token)")}}, on_error="continue")
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"token": other, "name": "ann"})
    assert result.status == "succeeded", result.error
    [row] = [r for r in store.steps(result_run(store)) if r.node_key == "t"]
    assert row.error_code == "claim_unavailable"
    assert result.outputs == {"n": -1}


def result_run(store: MemoryStore) -> str:
    [run_id] = list(store.runs)
    return run_id


async def test_a_reference_past_a_handle_gets_its_default_where_the_claim_has_nothing(
    env: WorkflowEnvironment,
) -> None:
    """Whether a part of a claim is missing or null is known only where the claim is read: a reference with a default
    asks there (`claims.derive`)."""
    login = {"type": "object", "x-sensitive": True, "properties": {"user": {"type": "string"},
             "opt": {"type": ["string", "null"]}}, "required": ["user"]}  # fmt: skip
    store = MemoryStore()
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"login": login}, "required": ["login"],
                         "additionalProperties": False},
        "outputs": {"opt": ref("trigger.login.opt", default="none"), "user": ref("trigger.login.user", default="?")},
    }  # fmt: skip
    g.node("e", "testkit.echo@1", {"value": 1})
    async with workers(env.client, store):
        missing = await run(env.client, store, g, {"login": {"user": "ops"}}, claimed=True)
        null = await run(env.client, store, g, {"login": {"user": "ops", "opt": None}}, claimed=True)
    assert missing.status == null.status == "succeeded", (missing.error, null.error)
    assert missing.outputs is not None and null.outputs is not None
    assert missing.outputs["opt"] == null.outputs["opt"] == "none"
    user = ClaimRef.of(missing.outputs["user"])
    assert user is not None and user.pointer == "/user"  # present: the same handle, no claim made


async def test_a_declassified_condition_over_a_sensitive_value_decides_plainly(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph()
    g.settings["declassify"] = [{"node": str(nid("c")), "field": "/condition"}]
    g.node("c", "flow.if@1", {"condition": cel("size(trigger.token) > 8")})
    g.node("a", "testkit.echo@1", {"value": 1}).node("b", "testkit.echo@1", {"value": 2})
    g.edge("c", "a", "true").edge("c", "b", "false")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER, claimed=True)
    assert result.status == "succeeded", result.error
    ran = {r.node_key for r in store.steps(result_run(store))}
    assert "a" in ran and "b" not in ran  # the branch taken: what the listed site reveals (spec §4.3)
