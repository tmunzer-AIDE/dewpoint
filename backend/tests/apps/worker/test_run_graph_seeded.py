# SPDX-License-Identifier: Apache-2.0
"""A single-step run (S2; the simulation design §5.3–5.4): one step of a version runs alone, simulated, with the values
it reads given by pointer. Nothing else is instantiated, no declared output is evaluated and no failure handler runs;
the run binds `run` itself; a read the seeds don't cover fails `seed_missing`; a live start, or a target that can't
run alone, is refused before anything runs."""

import asyncio
import uuid
from typing import Any

from temporalio.testing import WorkflowEnvironment

from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run_id_of, start, start_version, workers
from tests.support.graphs import G, cel, nid, ref

ECHO, FAIL_N, IF, LOOP, TRANSFORM = "testkit.echo@1", "testkit.fail_n@1", "flow.if@1", "flow.loop@1", "flow.transform@1"
SET, FILTER = "flow.set_variables@1", "flow.filter@1"


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "count": {"type": "integer"},
                "owner": {"type": "object", "properties": {"tag": {"type": "integer"}}, "additionalProperties": False},
                "ns": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"n": {"type": "integer"}},
                        "required": ["n"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["x", "owner"],
        },  # fmt: skip
        **({"outputs": outputs} if outputs else {}),
    }
    return g


async def alone(env: WorkflowEnvironment, store: MemoryStore, g: G, target: str, seeds: dict[str, Any],
                mode: str = "simulate") -> tuple[Any, str]:  # fmt: skip
    async with workers(env.client, store):
        handle = await start(env.client, store, g, seeds, mode=mode, target_step_id=str(nid(target)))
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    return result, run_id_of(handle)


async def test_one_step_runs_alone_with_its_seeds(env: WorkflowEnvironment) -> None:
    """`b` alone: `a` and `c` are never instantiated, and the outputs (which read `c`) aren't evaluated."""
    store = MemoryStore()
    g = graph(last=ref("steps.c.output.value")).node("a", ECHO, {"value": 1})
    g.node("b", ECHO, {"value": ref("steps.a.output.value")}).node("c", ECHO, {"value": 3}).edge("a", "b").edge(
        "b", "c"
    )
    result, run_id = await alone(env, store, g, "b", {"values": {"/steps/a/output/value": 5}, "absent": []})
    assert (result.status, result.outputs) == ("succeeded", None)
    [row] = store.steps(run_id)
    assert (row.node_key, row.iteration_key, row.status, row.outcome) == ("b", "", "succeeded", "simulated")
    assert row.input_preview == {"value": 5}


async def test_the_run_binds_its_own_fields_without_seeds(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    fields = {"id": cel("run.id"), "started": ref("run.started_at"), "now": cel("run.now")}
    g = graph().node("t", TRANSFORM, {"fields": fields})
    result, run_id = await alone(env, store, g, "t", {"values": {}, "absent": []})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert row.output_preview["id"] == run_id and row.output_preview["started"] and row.output_preview["now"]


async def test_an_absent_seed_leaves_its_container_in_place(env: WorkflowEnvironment) -> None:
    """`/trigger/owner/tag` absent: `owner` is still there (the schema says so), so `has()` is false, not an error."""
    store = MemoryStore()
    g = graph().node("t", TRANSFORM, {"fields": {"tagged": cel("has(trigger.owner.tag) ? 1 : 0")}})
    result, run_id = await alone(env, store, g, "t", {"values": {}, "absent": ["/trigger/owner/tag"]})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert row.output_preview == {"tagged": 0}


async def test_a_live_single_step_is_refused_before_anything_runs(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("b", ECHO, {"value": 1})
    result, run_id = await alone(env, store, g, "b", {"values": {}, "absent": []}, mode="live")
    assert (result.status, result.error["code"]) == ("failed", "seeded_live_refused")
    assert store.steps(run_id) == []


async def test_a_target_that_cant_run_alone_is_refused(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("l", LOOP, {"items": [1]}).node("x", ECHO, {"value": 1}).edge("l", "x", "body")
    result, run_id = await alone(env, store, g, "l", {"values": {}, "absent": []})
    assert (result.status, result.error["code"]) == ("failed", "target_invalid")
    assert store.steps(run_id) == []


async def test_a_read_the_seeds_dont_cover_fails_seed_missing(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("a", ECHO, {"value": 1}).node("b", ECHO, {"value": ref("steps.a.output.value")}).edge("a", "b")
    result, run_id = await alone(env, store, g, "b", {"values": {}, "absent": []})
    assert (result.status, result.error["code"]) == ("failed", "seed_missing")
    [row] = store.steps(run_id)
    assert (row.node_key, row.status, row.error_code) == ("b", "failed", "seed_missing")


async def test_an_absent_seed_takes_the_references_default(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("b", ECHO, {"value": ref("trigger.count", default=9)})  # an echo's strings are claimed: a number
    result, run_id = await alone(env, store, g, "b", {"values": {}, "absent": ["/trigger/count"]})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert row.input_preview == {"value": 9}


async def test_a_loop_contained_step_reads_its_frame_from_item_and_index(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("l", LOOP, {"items": [1, 2]})
    g.node("x", ECHO, {"value": {"i": ref("item"), "n": ref("loops.l.index")}}).edge("l", "x", "body")
    result, run_id = await alone(env, store, g, "x", {"values": {"/item": 2, "/index": 3}, "absent": []})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert (row.iteration_key, row.input_preview) == ("", {"value": {"i": 2, "n": 3}})


async def test_a_loop_contained_step_that_reads_only_its_item_needs_no_index(env: WorkflowEnvironment) -> None:
    """The frame is there whether or not its index is read: `/item/n` alone, through a ref and through CEL."""
    store = MemoryStore()
    g = graph().node("l", LOOP, {"items": ref("trigger.ns", default=[])})
    g.node("t", TRANSFORM, {"fields": {"a": ref("item.n"), "b": cel("item.n + 1")}}).edge("l", "t", "body")
    result, run_id = await alone(env, store, g, "t", {"values": {"/item/n": 7}, "absent": []})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert row.output_preview == {"a": 7, "b": 8}


async def test_the_variables_seeded_whole_as_one_claim_are_each_read_through_it(env: WorkflowEnvironment) -> None:
    """`size(vars)` beside a sensitive `vars.n`: one sensitive `/vars` entry, which admission claims whole. A
    variable is read through that claim, as through any claimed value."""
    store = MemoryStore()
    g = graph()
    g.settings["vars_schema"] = {"type": "object", "properties": {"n": {"type": "integer", "x-sensitive": True}}}
    g.node("s", SET, {"assignments": {"n": ref("trigger.x")}})
    g.node("t", TRANSFORM, {"fields": {"count": cel("size(vars)"), "n": ref("vars.n")}}).edge("s", "t")
    run_id = str(uuid.uuid4())
    seeds = {"values": {"/vars": store.claim({"n": 5}, owner=run_id, tainted=True)}, "absent": []}
    async with workers(env.client, store):
        handle = await start_version(env.client, store.add(g), seeds, run_id=run_id, mode="simulate",
                                     target_step_id=str(nid("t")))  # fmt: skip
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    counted = row.output_preview["count"]  # a result over sensitive data is claimed (engine 2b spec §4)
    assert store.claims[counted["$claim"]].value == 1


async def test_an_absent_item_leaves_its_loops_frame_in_place(env: WorkflowEnvironment) -> None:
    """`/item` absent: the innermost loop's frame is still there, empty, so `has(loops.l.item)` is false."""
    store = MemoryStore()
    g = graph().node("l", LOOP, {"items": ref("trigger.ns", default=[])})
    g.node("t", TRANSFORM, {"fields": {"v": cel("has(loops.l.item) ? 1 : 0")}}).edge("l", "t", "body")
    result, run_id = await alone(env, store, g, "t", {"values": {}, "absent": ["/item"]})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert row.output_preview == {"v": 0}


async def test_a_guarded_read_of_a_required_field_runs_with_it_absent(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("t", TRANSFORM, {"fields": {"v": cel("has(trigger.x) ? trigger.x : 0")}})
    result, run_id = await alone(env, store, g, "t", {"values": {}, "absent": ["/trigger/x"]})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert row.output_preview == {"v": 0}


async def test_a_value_whose_inner_read_has_a_default_runs_without_it_or_with_null(env: WorkflowEnvironment) -> None:
    """`owner` read whole and `owner.tag` with a default: `{}` and `{"tag": null}` both run, the default in place."""
    store = MemoryStore()
    fields = {"o": cel("size(trigger.owner)"), "t": ref("trigger.owner.tag", default=9)}
    g = graph().node("t", TRANSFORM, {"fields": fields})
    for owner, size in (({}, 0), ({"tag": None}, 1)):
        result, run_id = await alone(env, store, g, "t", {"values": {"/trigger/owner": owner}, "absent": []})
        assert result.status == "succeeded", result.error
        [row] = store.steps(run_id)
        assert row.output_preview == {"o": size, "t": 9}


async def test_a_filter_alone_takes_elements_its_guarded_predicate_reads_nothing_of(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node(
        "f", FILTER, {"items": ref("trigger.ns", default=[]), "predicate": cel("has(item.n) && item.n > 0")}
    )
    result, run_id = await alone(env, store, g, "f", {"values": {"/trigger/ns": [{}, {"n": 2}]}, "absent": []})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert row.status == "succeeded"


async def test_a_filter_alone_over_a_null_list_takes_its_items_default(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("f", FILTER, {"items": ref("trigger.ns", default=[]), "predicate": cel("item.n > 0")})
    result, run_id = await alone(env, store, g, "f", {"values": {"/trigger/ns": None}, "absent": []})
    assert result.status == "succeeded", result.error


async def test_an_if_alone_records_its_port_and_nothing_downstream(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("c", IF, {"condition": cel("trigger.x > 5")}).node("y", ECHO, {"value": 1}).edge("c", "y", "true")
    result, run_id = await alone(env, store, g, "c", {"values": {"/trigger/x": 7}, "absent": []})
    assert result.status == "succeeded", result.error
    [row] = store.steps(run_id)
    assert (row.node_key, row.effect_preview) == ("c", {"port": "true"})


async def test_a_failing_step_fails_its_run_whatever_its_error_policy(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("f", FAIL_N, {"failures": 10}, on_error="continue")
    g.nodes[0]["options"]["max_attempts"] = 1
    result, run_id = await alone(env, store, g, "f", {"values": {}, "absent": []})
    assert (result.status, result.error["code"]) == ("failed", "simulation_unavailable")  # it has no simulator
    [row] = store.steps(run_id)
    assert (row.status, row.outcome) == ("failed", "simulated")
