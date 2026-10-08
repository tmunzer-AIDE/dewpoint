# SPDX-License-Identifier: Apache-2.0
"""#18: binding many CEL views in one workflow task stays within the SDK's deadlock timeout, however large the values
they share. Measuring a view's bindings for routing costs what it reads of them, never more than the local caps: a
value past them is known to be past them without being serialized. On the time-skipping server, the default build
(local CEL on); `tests/probes/test_engine_issues.py` runs it at the real size on the dev server."""

import asyncio
from typing import Any

import pytest
from temporalio import workflow
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


@pytest.mark.parametrize(
    ("chars", "items", "claimed"),
    [(200, 300, False), (300, 300, True), (1_000, 20, False), (1_000, 70, True)],
    ids=["light", "past SHARED_MIN", "few copies", "past SHARED_REPEAT"],
)
async def test_a_shared_value_is_claimed_only_when_that_saves_something(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, chars: int, items: int, claimed: bool
) -> None:  # fmt: skip
    """A shared value no heavier than its handle (`SHARED_MIN`, 256 bytes), or whose copies add less than
    `SHARED_REPEAT` (64 KiB), stays in every set; just past either, it's claimed once. On the evaluator's path, where
    claiming applies (the review of the M2 checkpoint, I2: run locally, the test checked nothing)."""
    from dewpoint.engine.runtime import execution
    from dewpoint.engine.runtime.activities import CLAIMS_SPILL

    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", None)
    store = MemoryStore()
    g = issue_26(items)
    g.settings["outputs"] = {"kept": ref("steps.f.output.count", default=-1)}
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"s": "x" * chars})
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "succeeded" and result.outputs == {"kept": min(items, chars)}, result
    spills = [e async for e in handle.fetch_history_events()
              if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
              and e.activity_task_scheduled_event_attributes.activity_type.name == CLAIMS_SPILL]  # fmt: skip
    assert len(spills) == (1 if claimed else 0)
    sent = sum(await request_bytes(handle))
    assert (sent < chars * items) is claimed  # copies when it stays: every set carries it


TWO = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "string"}}, "required": ["a", "b"]}


async def test_shared_claims_of_two_filters_never_collide(env: WorkflowEnvironment) -> None:
    """The review of the M2 checkpoint (C2): every claim `_shared_once` wrote took one id per execution for its first
    value, the filter's step and scope never passed: a second filter over another shared string wrote other content
    under the same id, the store refused it, and the step failed `internal_error`. Each call's claims have ids of
    their own."""
    store = MemoryStore()
    g = G()
    outputs = {"a": ref("steps.fa.output.count"), "b": ref("steps.fb.output.count")}
    g.settings = {"input_schema": TWO, "outputs": outputs}
    g.node("fa", "flow.filter@1", {"items": list(range(10)), "predicate": cel("size(trigger.a) > item")})
    g.node("fb", "flow.filter@1", {"items": list(range(10)), "predicate": cel("size(trigger.b) > item")})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"a": "a" * 20_000, "b": "b" * 20_000})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"a": 10, "b": 10}), result


FIELDS = {f"k{i}": {"type": "string"} for i in range(30)}  # declared: an undeclared position is sensitive
M = {"type": "object", "properties": FIELDS, "additionalProperties": False}
OBJECT = {"type": "object", "properties": {"m": M}, "required": ["m"]}


async def test_a_shared_value_is_written_as_one_claim(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The review of the M2 checkpoint (I1): `_fit` split a shared container into a claim per field (31 for an object of
    30), which the evaluator then fetched for every set. A shared value one spill can carry is written whole, as one
    claim."""
    from dewpoint.engine.runtime import execution

    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", None)  # to the evaluator, whatever its size
    store = MemoryStore()
    g = G()
    g.settings = {"input_schema": OBJECT, "outputs": {"n": ref("steps.f.output.count")}}
    g.node("f", "flow.filter@1", {"items": list(range(10)), "predicate": cel("size(trigger.m) > item")})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"m": {f"k{i}": "v" * 1_000 for i in range(30)}})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"n": 10}), result
    assert len([c for c in store.claims.values() if c.kind == "spill"]) == 1


async def test_a_shared_value_whose_claim_cant_be_written_is_sent_as_copies(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The review of the M2 checkpoint (M1): claiming a shared value is a saving, not a requirement. A spill that fails
    (the claim store unavailable) left every set failed; the sets now carry the value, as before #26's claim."""
    write = MemoryStore.write

    async def failing(self: MemoryStore, tenant_id: str, claims: Any, *, kind: str, **kw: Any) -> None:
        if kind == "spill":
            raise RuntimeError("the claim store is unavailable")
        await write(self, tenant_id, claims, kind=kind, **kw)

    monkeypatch.setattr(MemoryStore, "write", failing)
    store = MemoryStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, issue_26(100), {"s": "x" * 65_500})
        result = await asyncio.wait_for(handle.result(), 120)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 100, "code": "none"}), result


async def test_finding_shared_values_is_charged_as_binding_is(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """The review of the M2 checkpoint (M2): the walk that finds the shared values, and the sets rebuilt with their
    handles, ran in one workflow task, uncharged, however many sets. Each set's walk is charged its values (`nodes`),
    at a yield point, as each view's binding is: a filter of 100 items charges at least two hundred."""
    from dewpoint.engine.cel import route as route_module
    from dewpoint.engine.runtime import execution

    charges: list[int] = []

    class Counting(route_module.YieldBudget):
        def charge(self, record: Any = None, *, nodes: int = 0, **kw: Any) -> None:
            if nodes and not workflow.unsafe.is_replaying():
                charges.append(nodes)
            super().charge(record, nodes=nodes, **kw)

    monkeypatch.setattr(execution, "YieldBudget", Counting)
    store = MemoryStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, issue_26(100), {"s": "x" * 65_500})
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "succeeded", result
    assert len(charges) >= 200
