# SPDX-License-Identifier: Apache-2.0
"""#18: binding many CEL views in one workflow task stays within the SDK's deadlock timeout, however large the values
they share. Measuring a view's bindings for routing costs what it reads of them, never more than the local caps: a
value past them is known to be past them without being serialized. On the time-skipping server, the default build
(local CEL on); `tests/probes/test_engine_issues.py` runs it at the real size on the dev server."""

import asyncio
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.cel import route
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.apps.worker.test_real_server import task_failures
from tests.support.graphs import G, cel, ref

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"s": {"type": "string"}}, "required": ["s"]}


def issue_18(items: int) -> G:
    """#18's reproduction: a filter whose every item binds the same large string."""
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": {"code": ref("steps.f.error.code", default="none")}}
    g.node("f", "flow.filter@1", {"items": list(range(items)), "predicate": cel("size(trigger.s) > item")},
           on_error="continue")  # fmt: skip
    return g


async def test_issue_18s_thousand_views_of_a_large_string_end_with_a_step_result(env: WorkflowEnvironment) -> None:
    """#18's reproduction: 1,000 items each binding a 1.8 MiB string. Each view's measure serialized the string in
    full (about 1.8 GB of JSON in one workflow task), past the SDK's 2-second deadlock timeout: the task failed and
    retried, and the run had no result. It ends with the step's result (the binding set alone passes the request
    limit: `input_too_large`), no workflow task failed."""
    store = MemoryStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, issue_18(1_000), {"s": "x" * (1_800 * 1024)})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"}), result
    assert await task_failures(handle) == []


def shared(items: int) -> G:
    """A filter whose every item binds the same list, within the caps: four 16,000-character strings."""
    g = G()
    schema = {"type": "object", "properties": {"t": {"type": "array", "items": {"type": "string"}}}, "required": ["t"]}
    g.settings = {"input_schema": schema, "outputs": {"n": cel("size(steps.f.output.items)")}}
    g.node("f", "flow.filter@1", {"items": list(range(items)), "predicate": cel("size(trigger.t) > item")})
    return g


async def yield_timers(handle: WorkflowHandle[Any, Any]) -> int:
    """Every timer the run started: a yield's, since nothing in these graphs sleeps."""
    return len([e async for e in handle.fetch_history_events() if e.event_type == EventType.EVENT_TYPE_TIMER_STARTED])


async def test_views_of_a_large_value_within_the_caps_are_bound_within_a_byte_budget(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """#18, the rest (gate 7b, measured on macOS: 1.8 s a workflow task at 10,000 items, a deadlock at 30,000): a value
    within the caps that every view binds is measured exactly for each, a serialization of about 64 KB its six nodes
    don't account for. Binding charges the bytes each measure serialized (`YIELD_BOUND_BYTES` a task): lowered to 1
    MiB, 100 such views (6.4 MB) take at least five more workflow tasks than with it out of reach."""

    async def timers(limit: int) -> int:
        monkeypatch.setattr(route, "YIELD_BOUND_BYTES", limit)
        store = MemoryStore()
        async with workers(env.client, store):
            handle = await start(env.client, store, shared(100), {"t": ["x" * 16_000] * 4})
            result = await asyncio.wait_for(handle.result(), 60)
        assert (result.status, result.outputs) == ("succeeded", {"n": 4}), result  # items 0 to 3: under size 4
        return await yield_timers(handle)

    assert await timers(1 << 20) >= await timers(1 << 40) + 5


def issue_26(items: int) -> G:
    """#26's reproduction: a filter whose every item binds the same plain string, past the local caps (so its views go
    to `cel.evaluate`) and under the inline limit (so it stays plain)."""
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": {"kept": ref("steps.f.output.count", default=-1),
                                                      "code": ref("steps.f.error.code", default="none")}}  # fmt: skip
    g.node("f", "flow.filter@1", {"items": list(range(items)), "predicate": cel("size(trigger.s) > item")},
           on_error="continue")  # fmt: skip
    return g


async def request_bytes(handle: WorkflowHandle[Any, Any]) -> list[int]:
    """Each `cel.evaluate` request's bytes, as the history holds them."""
    return [
        sum(len(p.data) for p in e.activity_task_scheduled_event_attributes.input.payloads)
        async for e in handle.fetch_history_events()
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
        and e.activity_task_scheduled_event_attributes.activity_type.name == "cel.evaluate"
    ]


@pytest.mark.parametrize("cache", [1000, 0], ids=["cached", "replaying every task"])
async def test_issue_26s_shared_string_goes_to_the_evaluator_once_not_with_every_item(
    env: WorkflowEnvironment, cache: int
) -> None:  # fmt: skip
    """#26: every binding set carried its own copy of the shared 65,500-character string, so 1,000 items sent about
    64 MB, and Temporal terminated the run for its history's size (the time-skipping server doesn't: here the bytes
    are measured). It's claimed once and every set carries its handle: 100 items send under 100 KB, not 6.5 MB, and
    every item is evaluated; a replay of every task claims the same."""
    store = MemoryStore()
    async with workers(env.client, store, cache=cache):
        handle = await start(env.client, store, issue_26(100), {"s": "x" * 65_500})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 100, "code": "none"}), result
    sent = await request_bytes(handle)
    assert sent and sum(sent) < 100_000, sent


@pytest.mark.parametrize(("value", "items"), [("x" * 200, 1_000), ("x" * 1_000, 20)], ids=["light", "few copies"])
async def test_a_shared_value_stays_when_claiming_it_would_save_nothing(
    env: WorkflowEnvironment, value: str, items: int
) -> None:  # fmt: skip
    """A shared value no heavier than its handle (`SHARED_MIN`), or whose copies add less than `SHARED_REPEAT`, stays
    in every set: no claim is written."""
    from dewpoint.engine.runtime.activities import CLAIMS_SPILL

    store = MemoryStore()
    g = issue_26(items)
    g.settings["outputs"] = {"kept": ref("steps.f.output.count", default=-1)}
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"s": value})
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "succeeded", result
    spills = [e async for e in handle.fetch_history_events()
              if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
              and e.activity_task_scheduled_event_attributes.activity_type.name == CLAIMS_SPILL]  # fmt: skip
    assert spills == []
