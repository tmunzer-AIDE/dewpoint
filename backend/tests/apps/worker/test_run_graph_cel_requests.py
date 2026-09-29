# SPDX-License-Identifier: Apache-2.0
"""#15: a `cel.evaluate` request stays under Temporal's payload limit. The workflow cuts requests by their bytes as
well as by 1,000 binding sets, and a binding set that alone passes the limit fails its evaluation with
`input_too_large` instead of leaving a workflow task retrying. The limit is lowered here so small values show it;
test_real_server.py shows it at the real one."""

import asyncio
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime import execution
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.support.graphs import G, cel, ref

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]}


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


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
