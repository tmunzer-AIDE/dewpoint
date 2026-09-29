# SPDX-License-Identifier: Apache-2.0
"""#15: a `cel.evaluate` request stays under Temporal's payload limit. The workflow cuts requests by their bytes as
well as by 1,000 binding sets, and a binding set that alone passes the limit fails its evaluation with
`input_too_large` instead of leaving a workflow task retrying. The limit is lowered here so small values show it;
test_real_server.py shows it at the real one."""

import asyncio
import json
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.cel import route
from dewpoint.engine.runtime import execution
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.support.graphs import G, cel, ref

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]}


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


async def sent_sets(handle: WorkflowHandle[Any, Any]) -> list[int]:
    """How many binding sets each `cel.evaluate` request carried, in order."""
    out = []
    async for e in handle.fetch_history_events():
        a = e.activity_task_scheduled_event_attributes
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED and a.activity_type.name == "cel.evaluate":
            out.append(len(json.loads(a.input.payloads[0].data)["request"]["bindings"]))
    return out


async def requests(handle: WorkflowHandle[Any, Any]) -> list[int]:
    """The workflow task that scheduled each `cel.evaluate` request, in order."""
    out = []
    async for e in handle.fetch_history_events():
        a = e.activity_task_scheduled_event_attributes
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED and a.activity_type.name == "cel.evaluate":
            out.append(a.workflow_task_completed_event_id)
    return out


@pytest.fixture(autouse=True)
def evaluator_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A build without local CEL: every expression goes to `cel.evaluate`."""
    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", None)


async def finished(
    env: WorkflowEnvironment, store: MemoryStore, g: G, trigger: dict[str, Any], *, cache: int = 1000
) -> tuple[WorkflowHandle[Any, Any], Any]:
    async with workers(env.client, store, cache=cache):
        handle = await start(env.client, store, g, trigger)
        return handle, await asyncio.wait_for(handle.result(), 60)


async def test_requests_that_fit_are_cut_every_1000_binding_sets(env: WorkflowEnvironment) -> None:
    """As before #15, so today's histories replay."""
    store = MemoryStore()
    g = graph(kept=ref("steps.f.output.count"))  # a ref: an output expression would be a request of its own
    g.node(
        "f", "flow.filter@1", {"items": list(range(1_500)), "predicate": cel("item % 3 == 0 && size(trigger.s) > 0")}
    )
    handle, result = await finished(env, store, g, {"s": "x"})
    assert (result.status, result.outputs) == ("succeeded", {"kept": 500})
    assert len(await requests(handle)) == 2


async def test_a_request_over_the_byte_limit_is_split_and_keeps_its_items_in_order(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution, "CEL_REQUEST_BYTES", 4_000)
    store = MemoryStore()
    g = graph(kept=ref("steps.f.output.items"))
    g.node(
        "f", "flow.filter@1", {"items": list(range(40)), "predicate": cel("item % 2 == 0 && size(trigger.s) == 100")}
    )
    handle, result = await finished(env, store, g, {"s": "x" * 100})
    assert (result.status, result.outputs) == ("succeeded", {"kept": list(range(0, 40, 2))})
    assert len(await requests(handle)) >= 2


async def test_a_binding_set_over_the_limit_fails_its_step_with_input_too_large(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution, "CEL_REQUEST_BYTES", 4_000)
    store = MemoryStore()
    g = graph(code=ref("steps.t.error.code", default="none"))
    g.node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.s)")}}, on_error="continue")
    handle, result = await finished(env, store, g, {"s": "x" * 5_000})
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"})
    assert await requests(handle) == []  # nothing was sent
    [row] = [r for r in store.steps(handle.id) if r.node_key == "t" and r.status == "failed"]
    assert row.error_message == execution.REQUEST_TOO_LARGE  # fixed: it never quotes a value


async def test_one_oversized_item_fails_the_filter_after_the_items_before_it(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review focus 2: the items before it are evaluated in their own request; that item is `input_too_large`."""
    monkeypatch.setattr(execution, "CEL_REQUEST_BYTES", 4_000)
    store = MemoryStore()
    g = graph(code=ref("steps.f.error.code", default="none"))
    items = ["a", "b", "c", "d", "x" * 5_000, "f"]
    g.node("f", "flow.filter@1", {"items": items, "predicate": cel("size(item) > 0")}, on_error="continue")
    handle, result = await finished(env, store, g, {"s": ""})
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"})
    assert len(await requests(handle)) >= 1


@pytest.mark.parametrize("cache", [1000, 0], ids=["cached", "replaying every task"])
async def test_a_workflow_task_sends_at_most_its_request_bytes(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, cache: int
) -> None:
    """Three steps ready together each send a request of about 700 bytes; with 1,000 bytes a task, each goes out in
    its own workflow task. Replaying every task decides the same way (review focus 3)."""
    monkeypatch.setattr(route, "YIELD_SEND_BYTES", 1_000)
    store = MemoryStore()
    g = graph(**{f"n{k}": ref(f"steps.t{k}.output.n") for k in range(3)})
    for k in range(3):
        g.node(f"t{k}", "flow.transform@1", {"fields": {"n": cel(f"size(trigger.s) + {k}")}})
    handle, result = await finished(env, store, g, {"s": "x" * 600}, cache=cache)
    assert (result.status, result.outputs) == ("succeeded", {"n0": 600, "n1": 601, "n2": 602})
    tasks = await requests(handle)
    assert len(tasks) == 3 and len(set(tasks)) == 3


async def test_no_binding_set_after_a_refused_one_is_measured_or_sent(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final review: a refused set ends the evaluation. The sets after it can't change the result (a filter fails
    at its first failing item, and the sets before it were sent already), so they're neither measured nor sent.
    Measuring every oversized set in one workflow task could outlast the SDK's deadlock timeout, and the task would
    retry forever — #15's symptom."""
    monkeypatch.setattr(execution, "CEL_REQUEST_BYTES", 4_000)
    measured: list[int] = []
    real = execution._json_bytes

    def counting(value: Any) -> int:
        measured.append(1)
        return real(value)

    monkeypatch.setattr(execution, "_json_bytes", counting)
    store = MemoryStore()
    g = graph(code=ref("steps.f.error.code", default="none"))
    g.node(
        "f",
        "flow.filter@1",
        {"items": list(range(50)), "predicate": cel("size(trigger.s) > item")},
        on_error="continue",
    )
    handle, result = await finished(env, store, g, {"s": "x" * 5_000})
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"})
    assert await requests(handle) == []
    assert len(measured) == 2  # the envelope and the first set, not the 49 after it


async def test_the_sets_before_a_refused_one_are_sent_and_none_after_it(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution, "CEL_REQUEST_BYTES", 4_000)
    store = MemoryStore()
    g = graph(code=ref("steps.f.error.code", default="none"))
    items = ["a", "b", "x" * 5_000, "c", "d"]
    g.node("f", "flow.filter@1", {"items": items, "predicate": cel("size(item) > 0")}, on_error="continue")
    handle, result = await finished(env, store, g, {"s": ""})
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"})
    assert await sent_sets(handle) == [2]  # "a" and "b"; nothing after the refused one
