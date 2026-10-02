# SPDX-License-Identifier: Apache-2.0
"""Reading handles in a run (engine 2b spec §3.2–3.4, §4.2). The trigger is claimed as admission claims it: its
sensitive values are handles. The workflow never reads a claim: a reference past a handle extends its pointer (and a
pointer past POINTER_MAX derives a claim in an activity); CEL and templates over handles go to `cel.evaluate`, whose
activity resolves them against their rows, and claims a result that read sensitive data."""

import uuid
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.handles import POINTER_MAX, ClaimRef
from tests.apps.worker.harness import EVALUATOR_ONLY, MemoryStore, run, workers
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


FLAGS: dict[str, Any] = {
    "type": "object",
    "properties": {"vip": {"type": "boolean", "x-sensitive": True}, "tier": {"type": "integer", "x-sensitive": True}},
    "required": ["vip", "tier"],
    "additionalProperties": False,
}


async def test_a_reference_to_a_sensitive_value_decides_a_listed_branch_and_case_plainly(
    env: WorkflowEnvironment,
) -> None:
    """A decision that reads a handle is resolved where the claim is read (spec §4.2): a listed branch's condition
    and a switch case's `when` come back as the plain decision, the only thing they reveal (§4.3)."""
    store = MemoryStore()
    g = G()
    g.settings = {
        "input_schema": FLAGS,
        "outputs": {},
        "declassify": [
            {"node": str(nid("c")), "field": "/condition"},
            {"node": str(nid("s")), "field": "/cases/0/when"},
        ],
    }
    g.node("c", "flow.if@1", {"condition": ref("trigger.vip")})
    g.node("y", "testkit.echo@1", {"value": 1}).node("n", "testkit.echo@1", {"value": 2})
    g.node("s", "flow.switch@1", {"cases": [{"port": "gold", "when": cel("trigger.tier > 2")}]})
    g.node("g", "testkit.echo@1", {"value": 3}).node("d", "testkit.echo@1", {"value": 4})
    g.edge("c", "y", "true").edge("c", "n", "false").edge("s", "g", "gold").edge("s", "d", "default")
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"vip": True, "tier": 1}, claimed=True)
    assert result.status == "succeeded", result.error
    ran = {r.node_key for r in store.steps(result_run(store))}
    assert {"y", "d"} <= ran and not {"n", "g"} & ran


async def test_a_loop_over_a_sensitive_list_counts_it_in_an_activity_and_iterates_item_handles(
    env: WorkflowEnvironment,
) -> None:
    """Spec §4.3: a listed loop over a tainted list reveals its count, nothing else. The count comes from an activity;
    each item is a handle into the list; a body step gets its item resolved in its activity."""
    secret_list = {"type": "array", "x-sensitive": True, "items": {"type": "string"}}
    store = MemoryStore()
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"keys": secret_list}, "required": ["keys"],
                         "additionalProperties": False},
        "outputs": {"count": ref("steps.l.output.count"), "items": ref("steps.l.output.items")},
        "declassify": [{"node": str(nid("l")), "field": "/items"}],
    }  # fmt: skip
    g.node("l", "flow.loop@1", {"items": ref("trigger.keys"), "collect": ref("steps.e.output.value")})
    g.node("e", "testkit.echo@1", {"value": ref("item")}).edge("l", "e", "body")
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"keys": ["k3y-one", "k3y-two", "k3y-three"]}, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs is not None and result.outputs["count"] == 3
    collected = [held(store, h)[0] for h in result.outputs["items"]]  # each echoed value repeats a secret: claimed
    assert collected == ["k3y-one", "k3y-two", "k3y-three"]
    assert "k3y-" not in repr(store.rows)


async def test_a_loop_over_a_list_too_large_to_carry_runs_in_batches_of_item_handles(env: WorkflowEnvironment) -> None:
    """A list over 64 KiB is claimed without taint (spec §3.5): its count is plain, no listing needed, and its
    batches carry item handles."""
    lines = {"type": "array", "items": {"type": "string"}}
    store = MemoryStore()
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"lines": lines}, "required": ["lines"],
                         "additionalProperties": False},
        "outputs": {"count": ref("steps.l.output.count")},
    }  # fmt: skip
    g.node("l", "flow.loop@1", {"items": ref("trigger.lines"), "concurrency": 5})
    g.node("e", "testkit.blob@1", {"size": 1}).edge("l", "e", "body")
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"lines": [f"{i:04d}" + "x" * 700 for i in range(150)]}, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs == {"count": 150}


def held(store: MemoryStore, value: Any) -> tuple[Any, bool]:
    found = ClaimRef.of(value)
    assert found is not None, value
    claim = store.claims[found.id]
    return claim.value, claim.sensitive_pointers == ("",)


async def test_a_filter_with_a_sensitive_predicate_runs_whole_in_one_activity(env: WorkflowEnvironment) -> None:
    """Spec §4.4: no per-item decision enters the workflow. The kept items come back as a tainted claim, and the two
    counts plain: the listed site reveals them, nothing else."""
    store = MemoryStore()
    g = graph(count=ref("steps.f.output.count"), kept=ref("steps.f.output.items"))
    g.settings["declassify"] = [{"node": str(nid("f")), "field": "/predicate"}]
    g.node("f", "flow.filter@1", {"items": [3, 20, 7, 40], "predicate": cel("size(trigger.token) > item")})
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs is not None and result.outputs["count"] == 2
    assert held(store, result.outputs["kept"]) == ([3, 7], True)  # tainted: its predicate is


async def test_a_filter_over_a_sensitive_list_keeps_a_tainted_claim_and_charges_every_item(
    env: WorkflowEnvironment,
) -> None:
    secret_list = {"type": "array", "x-sensitive": True, "items": {"type": "string"}}
    store = MemoryStore()
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"keys": secret_list}, "required": ["keys"],
                         "additionalProperties": False},
        "outputs": {"count": ref("steps.f.output.count"), "kept": ref("steps.f.output.items")},
        "declassify": [{"node": str(nid("f")), "field": f} for f in ("/items", "/predicate")],  # it reads `item`
    }  # fmt: skip
    g.node("f", "flow.filter@1", {"items": ref("trigger.keys"), "predicate": cel("item.startsWith('k')")})
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"keys": ["k3y-a", "x3y-b", "k3y-c"]}, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs is not None and result.outputs["count"] == 2 and result.iterations == 3
    assert held(store, result.outputs["kept"]) == (["k3y-a", "k3y-c"], True)


async def test_a_sensitive_value_crosses_into_a_sub_flow_and_its_result_back_through_grants(
    env: WorkflowEnvironment,
) -> None:
    """Spec §3.4: the parent grants the child the handles it passes, before the start; the child grants its parent
    the handles in its outputs, before its result returns. Each reads the other's claims only through those grants."""
    store = MemoryStore()
    child = G()
    child.settings = {
        "input_schema": {"type": "object", "properties": {"key": SECRET}, "required": ["key"],
                         "additionalProperties": False},
        "outputs": {"n": ref("steps.t.output.n")},
    }  # fmt: skip
    child.node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.key)")}})
    g = graph(n=ref("steps.r.output.n"), more=ref("steps.p.output.more"))
    g.node(
        "r", "flow.run_workflow@1", {"workflow_id": str(store.publish(child)), "input": {"key": ref("trigger.token")}}
    )
    g.node("p", "flow.transform@1", {"fields": {"more": cel("steps.r.output.n + 1")}}).edge("r", "p")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER, claimed=True)
    assert result.status == "succeeded", result.error
    assert result.outputs is not None
    assert held(store, result.outputs["n"]) == (12, True)  # the child's claim, read through its grant
    assert held(store, result.outputs["more"]) == (13, True)  # the parent's own, computed from it
    [(child_run, _)] = store.starts.items()
    [token_claim] = [cid for cid, c in store.claims.items() if c.value == "s3cr3t-token"]
    assert (token_claim, child_run) in store.grants  # parent -> child


async def test_a_sub_flows_undeclared_input_is_claimed_for_the_child(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    child = G()
    child.settings = {"input_schema": {"type": "object"}, "outputs": {}}
    child.node("e", "testkit.echo@1", {"value": 1})
    g = graph().node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(child)), "input": {"x": 41}})
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER, claimed=True)
    assert result.status == "succeeded", result.error
    [(child_run, _)] = store.starts.items()
    assert [(c.value, c.owner) for c in store.claims.values() if c.kind == "input" and c.owner == child_run] == [
        (41, child_run)
    ]


async def test_cel_that_reads_sensitive_data_nowhere_still_resolves_a_size_claim(env: WorkflowEnvironment) -> None:
    """A value only its size claimed is plain data behind a handle (spec §3.5): an untainted expression over it goes to
    `cel.evaluate`, which resolves it, and its result comes back plain. Review finding: binding sets travel as a
    tuple, which the marker check didn't look into, so the evaluator got the handle itself and gave `size()` of it."""
    big = {"type": "object", "properties": {"v": {"type": "string"}}, "required": ["v"], "additionalProperties": False}
    store = MemoryStore()
    g = G()
    g.settings = {"input_schema": big, "outputs": {"n": cel("size(trigger.v)")}}
    g.node("e", "testkit.echo@1", {"value": 1})
    async with workers(env.client, store):
        result = await run(env.client, store, g, {"v": "x" * 100_000}, claimed=True)
    assert (result.status, result.outputs) == ("succeeded", {"n": 100_000}), result.error


async def test_a_cel_value_that_builds_the_marker_is_refused_wherever_it_runs(env: WorkflowEnvironment) -> None:
    """A map CEL builds with the marker key is no handle (spec §3.2): the step fails, in the workflow and in the
    evaluator alike, rather than take it for one."""
    store = MemoryStore()
    forged = "{'$claim': '00000000-0000-0000-0000-000000000007'}"
    g = graph(local=ref("steps.a.error.code", default="none"), remote=ref("steps.b.error.code", default="none"))
    g.node("a", "flow.transform@1", {"fields": {"v": cel(forged)}}, on_error="continue")
    g.node("b", "flow.transform@1", {"fields": {"v": cel(f"{EVALUATOR_ONLY} > 0 ? {forged} : {{}}")}},
           on_error="continue")  # fmt: skip
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER, claimed=True)
    assert (result.status, result.outputs) == ("succeeded", {"local": "evaluation_error", "remote": "evaluation_error"})
