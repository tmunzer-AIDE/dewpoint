# `cel.evaluate` Request Size (issue #15) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `cel.evaluate` request never passes Temporal's payload limit: the workflow cuts requests by their bytes as
well as by 1,000 binding sets, refuses a binding set that alone is too large with `input_too_large`, and paces the
`cel.evaluate` requests one workflow task sends — a step result, never a retried or terminated workflow task. The pacing
counts CEL requests only; the invariant over every command a task sends is 2b-1a's.

**Architecture:** One pure function in the deterministic core (`resolve.request_end`) decides where each request ends,
from each binding set's JSON size, measured one set at a time with the workflow's own payload converter. `RunGraph`'s
`_evaluate` sends one request per range, and turns a range of zero sets into an `input_too_large` outcome. The per-task
yield budget gains a byte dimension for the requests a workflow task sends. Requests that fit are still cut every
1,000 binding sets, but a run's commands can change — a request between 1.75 and 2 MiB, which succeeded before, now
splits, and pacing can add a timer to a task that sent several requests — so `ENGINE_ABI` becomes 4, with its own
golden histories (engine-core §7).

**Tech Stack:** Python 3.12, Temporal Python SDK 1.33.0, pytest with Temporal's time-skipping server and CLI dev server
(`WorkflowEnvironment.start_local`, approved), ruff, mypy strict, import-linter; `uv`.

**Spec:** `docs/superpowers/specs/2026-09-25-engine-core-design.md` (§5.6 yield budget, §5.7 IPC limits, §6 filter) on
`main`; issue #15 and its reproduction comment; for context, the approved 2b spec on branch `docs/engine-2b-spec`
(`docs/superpowers/specs/2026-09-29-engine-2b-design.md` §5.2 and §11.1: the size check happens after the codec, a
completion over the gRPC limit gets the workflow terminated; 2b-1a generalizes this guard to every command).

## Global Constraints

- One branch, `fix/cel-request-size`, from freshly updated `main` (`28b6f95`), for this plan and the fix; nothing is
  pushed until the owner says so; the owner merges.
- `ENGINE_ABI` becomes 4 (Task 4): this change can alter a run's command sequence (engine-core §7). The abi3 histories
  stay as recorded and immutable (the replay gate); runs already started drain on their pinned ABI-3 build; versions are
  published again for ABI 4 before new runs start (`docs/operations/deployment.md`).
- A failure is a step result (`input_too_large`, an existing CEL outcome code), never a retried or terminated workflow
  task. Its message is fixed and never quotes a value.
- `CEL_REQUEST_BYTES = 1_835_008` (1.75 MiB): a request's JSON bytes, a margin under Temporal's 2 MiB (2,097,152)
  payload limit, which the SDK checks after any codec (measured: 2b spec §11.1).
- `YIELD_SEND_BYTES = 3 * 1024 * 1024`: the `cel.evaluate` request bytes one workflow task sends, under Temporal's
  4 MiB (4,194,304) gRPC message limit (measured: a completion over it gets the workflow terminated). It counts CEL
  requests only — not projections, plugin steps or children in the same task — so it protects the CEL-only case #15
  reproduces; the whole-task invariant belongs to 2b-1a.
- The evaluator's own 4 MiB request check (`apps/cel_client.py`) stays as a second line.
- Test first: every test below fails before its implementation, for the stated reason.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Docker: no new images (the dev server is
  the SDK's download). Scratch files go in the session scratchpad, never `/tmp`.
- Test-order quirk: list `tests/apps/...` before `tests/engine/...` in one command, never a worker file, then another
  apps file, then a worker file.

## Review Focus

1. **Non-ASCII text in bindings** — Temporal's JSON escapes it (`é`, surrogate pairs), so its bytes differ from
   UTF-8 or canonical JSON; the measure must be the converter's own. Task 1's exactness test pins it.
2. **One oversized binding set among fitting ones** — a filter whose 5th item alone passes the limit: the items before
   it are evaluated, that one is `input_too_large`, and the filter fails with that code, in item order. Task 2 pins it.
3. **Replay with no worker cache** — sizing and pacing happen while replaying every task; they must decide the same
   way (they read only history-derived state). Task 3's pacing test runs cached and replaying every task.
4. **Several large requests in one workflow task** — three steps each sending about 1.6 MiB at once today exceed the
   gRPC limit and get the run terminated; they must go out in separate tasks. Task 3 pins it on the dev server.
5. **Requests that fit** — a 1,500-item filter must still send exactly 1,000 + 500: the cut changes only requests
   past the limit. Task 2 pins it; Task 4 records ABI 4's histories, and the gate keeps ABI 3's unchanged.

---

## File structure

- `backend/src/dewpoint/engine/runtime/resolve.py` — gains `request_end`: where a request ends (pure).
- `backend/src/dewpoint/engine/cel/route.py` — `YieldBudget` gains `sent` and `YIELD_SEND_BYTES` (Task 3).
- `backend/src/dewpoint/engine/runtime/execution.py` — `CEL_REQUEST_BYTES`, `_json_bytes`, `_evaluate` cuts, refuses
  and paces; `_yield_point` takes `send`.
- `backend/tests/engine/runtime/test_resolve.py` — the cut and the exactness of the measure.
- `backend/tests/engine/cel/test_route.py` — the send budget.
- `backend/tests/apps/worker/test_run_graph_cel_requests.py` (new) — the workflow on the time-skipping server, with the
  limits lowered.
- `backend/tests/apps/worker/test_run_graph_yield.py` — its `Recording` budget accepts `sent`.
- `backend/tests/apps/worker/test_real_server.py` — the dev-server regressions at the real limits.
- `backend/src/dewpoint/engine/__init__.py`, `backend/tests/engine/cel/test_profile.py`,
  `backend/tests/engine/replay/dewpoint-0.1.0+abi4/` — `ENGINE_ABI` 4 and its recorded histories (Task 4).
- `docs/superpowers/specs/2026-09-25-engine-core-design.md`, `docs/operations/cel-evaluator.md`,
  `docs/operations/runs.md` — the rule.

---

### Task 1: Where a `cel.evaluate` request ends

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/resolve.py` (after `class CelTask`)
- Test: `backend/tests/engine/runtime/test_resolve.py`

**Interfaces:**
- Produces: `resolve.request_end(start: int, count: int, size_of: Callable[[int], int], *, envelope: int, batch: int,
  limit: int) -> tuple[int, int]` — the exclusive end of the request starting at binding set `start`, and its JSON
  bytes. `end == start` means set `start` alone passes `limit`.

- [ ] **Step 1: Write the failing tests** — in `backend/tests/engine/runtime/test_resolve.py`, add to the imports
  (sorted into their groups: ruff's isort):

```python
from temporalio.converter import DataConverter

from dewpoint.engine.runtime.activities import CelInput
from tests.engine.cel.support import make_record
```

  and append:

```python
def test_requests_that_fit_are_cut_every_batch() -> None:
    """#15: as before, when their bytes fit, requests hold `batch` binding sets, the last one the rest."""
    sizes = [10] * 25
    assert resolve.request_end(0, 25, sizes.__getitem__, envelope=100, batch=10, limit=10_000) == (10, 100 + 100 + 9)
    assert resolve.request_end(20, 25, sizes.__getitem__, envelope=100, batch=10, limit=10_000) == (25, 100 + 50 + 4)


def test_a_request_ends_where_its_bytes_would_pass_the_limit() -> None:
    sizes = [100] * 10
    # 50 + 100 = 150; + 1 + 100 = 251; + 1 + 100 = 352 > 300
    assert resolve.request_end(0, 10, sizes.__getitem__, envelope=50, batch=1_000, limit=300) == (2, 251)
    assert resolve.request_end(2, 10, sizes.__getitem__, envelope=50, batch=1_000, limit=300) == (4, 251)


def test_a_binding_set_that_alone_passes_the_limit_ends_its_request_where_it_starts() -> None:
    sizes = [10, 500, 10]
    assert resolve.request_end(0, 3, sizes.__getitem__, envelope=50, batch=1_000, limit=300) == (1, 60)
    assert resolve.request_end(1, 3, sizes.__getitem__, envelope=50, batch=1_000, limit=300) == (1, 50)
    assert resolve.request_end(2, 3, sizes.__getitem__, envelope=50, batch=1_000, limit=300) == (3, 60)


def test_a_requests_bytes_are_its_envelope_plus_its_sets_and_the_commas_between() -> None:
    """The workflow sizes a request from its parts, one binding set at a time: that must equal what Temporal's JSON
    converter writes for the whole request — non-ASCII text, escapes, floats, nulls and nesting included."""
    conv = DataConverter.default.payload_converter
    record = make_record("size(trigger.s) > 0")
    sets: tuple[dict[str, Any], ...] = (
        {"trigger": {"s": 'é€😀\n"\\', "f": 1.5, "n": None}},
        {"item": [1, {"b": True}], "trigger": {"s": "x" * 50}},
        {"item": 0},
    )

    def size(v: Any) -> int:
        return len(conv.to_payloads([v])[0].data)

    whole = size(CelInput(resolve.CelTask(record, sets, False).request(CURRENT_CEL_PROFILE)))
    envelope = size(CelInput(resolve.CelTask(record, (), False).request(CURRENT_CEL_PROFILE)))
    measured = resolve.request_end(0, 3, lambda i: size(sets[i]), envelope=envelope, batch=1_000, limit=10**9)
    assert measured == (3, whole)
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && uv run pytest tests/engine/runtime/test_resolve.py -q -k "request"`
Expected: the 4 new tests FAIL with `AttributeError: module 'dewpoint.engine.runtime.resolve' has no attribute
'request_end'` (any existing test whose name matches `request` still passes).

- [ ] **Step 3: Implement** — in `backend/src/dewpoint/engine/runtime/resolve.py`, add `Callable` to the
  `collections.abc` import, and after `class CelTask`:

```python
def request_end(
    start: int, count: int, size_of: Callable[[int], int], *, envelope: int, batch: int, limit: int
) -> tuple[int, int]:
    """Where the `cel.evaluate` request that starts at binding set `start` ends (exclusive), and its JSON bytes: as
    many sets as fit in `limit`, at most `batch` (#15). A request's JSON is its envelope (no sets) plus each set's JSON
    and a comma between sets, so `size_of(i)` measures one set at a time. Requests that fit are cut every `batch` sets,
    as before. An end equal to `start` means set `start` alone passes the limit."""
    end, size = start, envelope
    while end < min(start + batch, count):
        extra = size_of(end) + (1 if end > start else 0)
        if size + extra > limit:
            break
        size += extra
        end += 1
    return end, size
```

- [ ] **Step 4: Run them to see them pass**

Run: `cd backend && uv run pytest tests/engine/runtime/test_resolve.py -q`
Expected: all PASS.

- [ ] **Step 5: Static checks and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`
Expected: clean (`lint-imports`: 10 kept, 0 broken).

```bash
git add backend/src/dewpoint/engine/runtime/resolve.py backend/tests/engine/runtime/test_resolve.py
git commit -m "feat(engine): where a cel.evaluate request ends, by its bytes as well as its binding sets (#15)"
```

---

### Task 2: `RunGraph` cuts its requests by bytes, and refuses a binding set that can't fit

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/execution.py` (constants near `CEL_BATCH`; `_evaluate`)
- Create: `backend/tests/apps/worker/test_run_graph_cel_requests.py`
- Modify: `backend/tests/apps/worker/test_real_server.py`
- Modify: `docs/superpowers/specs/2026-09-25-engine-core-design.md`, `docs/operations/cel-evaluator.md`,
  `docs/operations/runs.md`

**Interfaces:**
- Consumes: `resolve.request_end` (Task 1); `cel.INPUT_TOO_LARGE` (`dewpoint.engine.cel.evaluate`, imported as `cel`).
- Produces: `execution.CEL_REQUEST_BYTES: int`, `execution.REQUEST_TOO_LARGE: str`, `execution._json_bytes(value: Any)
  -> int`; Task 3 adds pacing around the send in `_evaluate`.

- [ ] **Step 1: Write the failing time-skipping tests** — create
  `backend/tests/apps/worker/test_run_graph_cel_requests.py`:

```python
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
    g = graph(kept=cel("steps.f.output.count"))
    g.node("f", "flow.filter@1", {"items": list(range(1_500)), "predicate": cel("item % 3 == 0 && size(trigger.s) > 0")})
    handle, result = await finished(env, store, g, {"s": "x"})
    assert (result.status, result.outputs) == ("succeeded", {"kept": 500})
    assert len(await requests(handle)) == 2


async def test_a_request_over_the_byte_limit_is_split_and_keeps_its_items_in_order(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(execution, "CEL_REQUEST_BYTES", 4_000)
    store = MemoryStore()
    g = graph(kept=ref("steps.f.output.items"))
    g.node("f", "flow.filter@1", {"items": list(range(40)), "predicate": cel("item % 2 == 0 && size(trigger.s) == 100")})
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
```

- [ ] **Step 2: Write the failing dev-server tests** — append to `backend/tests/apps/worker/test_real_server.py`
  (it already imports `asyncio`, `EventType`, `WorkflowHandle`, `MemoryStore`, `start`, `G`, `cel`, `ref`):

```python
def strings(*names: str) -> dict[str, Any]:
    return {"type": "object", "properties": {n: {"type": "string"} for n in names}, "required": list(names)}


async def task_failures(handle: WorkflowHandle[Any, Any]) -> list[int]:
    """The causes of every failed workflow task: none, when nothing retried a command Temporal refused."""
    out = []
    async for e in handle.fetch_history_events():
        if e.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_FAILED:
            out.append(e.workflow_task_failed_event_attributes.cause)
    return out


async def cel_requests(handle: WorkflowHandle[Any, Any]) -> list[int]:
    out = []
    async for e in handle.fetch_history_events():
        a = e.activity_task_scheduled_event_attributes
        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED and a.activity_type.name == "cel.evaluate":
            out.append(a.workflow_task_completed_event_id)
    return out


async def test_issue_15s_filter_splits_its_request_and_keeps_every_item(dev_env: WorkflowEnvironment) -> None:
    """#15's reproduction: 1,500 items each binding a 3,000-character string made a 3 MB request, whose workflow task
    retried until the run's deadline, or forever. It's split, and every item is evaluated."""
    client, store = dev_env.client, MemoryStore()
    g = G()
    g.settings = {"input_schema": strings("s"), "outputs": {"kept": cel("steps.f.output.count")}}
    g.node("f", "flow.filter@1", {"items": list(range(1_500)), "predicate": cel("size(trigger.s) > item")})
    async with serving(client, store):
        handle = await start(client, store, g, {"s": "x" * 3_000})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 1_500})
    assert len(await cel_requests(handle)) >= 3
    assert await task_failures(handle) == []


async def test_a_binding_set_over_the_request_limit_fails_its_step(dev_env: WorkflowEnvironment) -> None:
    """Two 900 KiB strings in one binding set pass 1.75 MiB: the step fails with `input_too_large`; nothing is sent."""
    client, store = dev_env.client, MemoryStore()
    half = 900 * 1024
    g = G()
    g.settings = {"input_schema": strings("a", "b"), "outputs": {"code": ref("steps.t.error.code", default="none")}}
    g.node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.a) + size(trigger.b)")}}, on_error="continue")
    async with serving(client, store):
        handle = await start(client, store, g, {"a": "x" * half, "b": "y" * half})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"code": "input_too_large"})
    assert await cel_requests(handle) == []
    assert await task_failures(handle) == []
```

- [ ] **Step 3: Run the new tests to see them fail**

Run: `cd backend && uv run pytest tests/apps/worker/test_run_graph_cel_requests.py tests/apps/worker/test_real_server.py -q -k "request or issue_15 or binding_set"`
Expected:
- `test_requests_that_fit_are_cut_every_1000_binding_sets`: PASS (today's behavior, kept);
- `test_a_request_over_the_byte_limit_is_split…`, `…fails_its_step_with_input_too_large`,
  `test_one_oversized_item…`: FAIL with `AttributeError: … has no attribute 'CEL_REQUEST_BYTES'` (monkeypatch);
- `test_issue_15s_filter…`: FAIL with `TimeoutError` (the workflow task retries, as #15 describes);
- `test_a_binding_set_over_the_request_limit…`: FAIL, `{'code': 'none'}` — today the 1.8 MB request goes out.

- [ ] **Step 4: Implement** — in `backend/src/dewpoint/engine/runtime/execution.py`, after `CEL_BATCH`:

```python
CEL_REQUEST_BYTES = 1_835_008  # a cel.evaluate request's JSON bytes: a margin under Temporal's 2 MiB payload limit (#15)
REQUEST_TOO_LARGE = "The values this expression reads are too large to send to the CEL evaluator (over 1.75 MiB)."
```

add `"CEL_REQUEST_BYTES"` to `__all__` next to `"CEL_BATCH"`, and a module-level function before `class Execution`:

```python
def _json_bytes(value: Any) -> int:
    """The JSON bytes Temporal's payload converter writes for `value`: what the SDK checks against its payload limit,
    before any codec (#15)."""
    return len(workflow.payload_converter().to_payloads([value])[0].data)
```

and replace the activity half of `_evaluate` (from `out: list[cel.Outcome] = []` to `return out`) with:

```python
        out: list[cel.Outcome] = []
        profile = self.program.cel_profile
        envelope = _json_bytes(CelInput(resolve.CelTask(task.record, (), False).request(profile)))
        start, count = 0, len(task.bindings)
        while start < count:
            end, _ = resolve.request_end(
                start,
                count,
                lambda i: _json_bytes(task.bindings[i]),
                envelope=envelope,
                batch=CEL_BATCH,
                limit=CEL_REQUEST_BYTES,
            )
            if end == start:  # this binding set alone would pass Temporal's payload limit: it's never sent (#15)
                out.append(cel.Outcome(error=cel.INPUT_TOO_LARGE, message=REQUEST_TOO_LARGE))
                start += 1
                continue
            chunk = resolve.CelTask(task.record, task.bindings[start:end], False)
            try:
                result = await workflow.execute_activity(
                    CEL_EVALUATE,
                    CelInput(chunk.request(profile)),
                    result_type=CelResult,
                    task_queue=cel_queue(profile),
                    schedule_to_start_timeout=timedelta(seconds=self.cel_schedule_to_start_s),
                    start_to_close_timeout=timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1)),
                )
            except ActivityError as e:
                if isinstance(e.cause, ActivityCancelled):  # the run or the scope ended: stop here
                    raise asyncio.CancelledError from None
                message = f"No evaluator served `{profile}` ({type(e.cause or e).__name__})."
                return [cel.Outcome(error=cel.PROFILE_UNAVAILABLE, message=message)] * len(task.bindings)
            out += [cel.Outcome.from_json(o) for o in result.outcomes]
            start = end
        return out
```

- [ ] **Step 5: Run the new tests to see them pass**

Run: `cd backend && uv run pytest tests/apps/worker/test_run_graph_cel_requests.py tests/apps/worker/test_real_server.py -q`
Expected: all PASS.

- [ ] **Step 6: The replay suite, as a sanity check** — ABI 3's recorded scenarios hold no request near the limits, so
  they still replay; that doesn't prove other histories do, which is why Task 4 raises the ABI.

Run: `cd backend && uv run pytest tests/engine/replay -q`
Expected: all PASS; `git status` shows no change under `backend/tests/engine/replay/`.

- [ ] **Step 7: Document the rule.**
  - `docs/superpowers/specs/2026-09-25-engine-core-design.md`, §5.7 **IPC limits**, after the bullet **Request size ≤ 4
    MiB**, add:

```markdown
- **Temporal's payload limit.** The workflow cuts each request by its JSON bytes as well as by 1,000 binding sets, so
  its payload stays within `CEL_REQUEST_BYTES` (1.75 MiB), a margin under Temporal's 2 MiB limit, which the SDK checks
  after any codec. Requests that fit are cut every 1,000 sets, as before. A binding set that alone passes it is the
  outcome `input_too_large`, and no request is sent for it (issue #15).
```

  - same file, §6's node table, the `filter` row: replace `in chunks of 1,000` with `in chunks of 1,000, fewer when
    their bytes would pass 1.75 MiB (§5.7)`.
  - `docs/operations/cel-evaluator.md`, after the **Outcomes** paragraph, add: ``A binding set too large to send
    within Temporal's payload limit (1.75 MiB, with a margin) is `input_too_large` too: the workflow never sends it.``
  - `docs/operations/runs.md`, the step error codes sentence: add `input_too_large` after `cel_profile_unavailable`.

- [ ] **Step 8: Static checks and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`
Expected: clean.

```bash
git add backend/src/dewpoint/engine/runtime/execution.py backend/tests/apps/worker/test_run_graph_cel_requests.py \
  backend/tests/apps/worker/test_real_server.py docs/superpowers/specs/2026-09-25-engine-core-design.md \
  docs/operations/cel-evaluator.md docs/operations/runs.md
git commit -m "fix(engine): a cel.evaluate request is cut by its bytes, and a set that can't fit is input_too_large (#15)"
```

---

### Task 3: A workflow task paces the requests it sends

**Files:**
- Modify: `backend/src/dewpoint/engine/cel/route.py` (`YieldBudget`, a new constant)
- Modify: `backend/src/dewpoint/engine/runtime/execution.py` (`_yield_point`, `_evaluate`'s send)
- Modify: `backend/tests/engine/cel/test_route.py`, `backend/tests/apps/worker/test_run_graph_yield.py`,
  `backend/tests/apps/worker/test_run_graph_cel_requests.py`, `backend/tests/apps/worker/test_real_server.py`
- Modify: `docs/superpowers/specs/2026-09-25-engine-core-design.md` (§5.6, §5.7)

**Interfaces:**
- Consumes: Task 2's `_evaluate` and test helpers `requests`, `finished`, `cel_requests`, `task_failures`, `strings`.
- Produces: `route.YIELD_SEND_BYTES: int`; `YieldBudget.sent: int`; `YieldBudget.must_yield(record=None, *, send: int
  = 0) -> bool`; `YieldBudget.charge(record=None, *, nodes: int = 0, sent: int = 0) -> None`;
  `Execution._yield_point(record, *, send: int = 0)`.

- [ ] **Step 1: Write the failing unit test** — append to `backend/tests/engine/cel/test_route.py`:

```python
def test_a_workflow_task_sends_at_most_its_request_bytes() -> None:
    """#15: the requests one workflow task sends stay under Temporal's gRPC message limit together. The first always
    goes; sending isn't evaluating, so it spends none of the evaluation budget; the startup share doesn't apply."""
    budget = route.YieldBudget()
    big = route.YIELD_SEND_BYTES - 10
    assert not budget.must_yield(send=big)
    budget.charge(sent=big)
    assert not budget.must_yield(send=10)
    assert budget.must_yield(send=11)
    assert not budget.must_yield(None)  # binding a view isn't held back by requests sent
    budget.reset(startup=True)
    assert not budget.must_yield(send=big)
    budget.charge(sent=big)
    assert budget.must_yield(send=11)
```

- [ ] **Step 2: Write the failing workflow tests** — in
  `backend/tests/apps/worker/test_run_graph_cel_requests.py`, add `from dewpoint.engine.cel import route` to the
  imports (before `from dewpoint.engine.runtime import execution`), and append:

```python
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
```

  and append to `backend/tests/apps/worker/test_real_server.py`:

```python
async def test_three_large_requests_are_paced_under_temporals_message_limit(dev_env: WorkflowEnvironment) -> None:
    """Three steps ready together each send about 1.6 MiB. In one workflow task that passes Temporal's 4 MiB gRPC
    message limit, and Temporal terminates the run; paced, they go out in separate tasks (review focus 4)."""
    client, store = dev_env.client, MemoryStore()
    part = 800 * 1024
    g = G()
    g.settings = {"input_schema": strings("a", "b"), "outputs": {f"n{k}": ref(f"steps.t{k}.output.n") for k in range(3)}}
    for k in range(3):
        g.node(f"t{k}", "flow.transform@1", {"fields": {"n": cel(f"size(trigger.a) + size(trigger.b) + {k}")}})
    async with serving(client, store):
        handle = await start(client, store, g, {"a": "x" * part, "b": "y" * part})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {f"n{k}": 2 * part + k for k in range(3)})
    tasks = await cel_requests(handle)
    assert len(tasks) == 3 and len(set(tasks)) == 3
    assert await task_failures(handle) == []
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd backend && uv run pytest tests/apps/worker/test_run_graph_cel_requests.py tests/apps/worker/test_real_server.py tests/engine/cel/test_route.py -q -k "request_bytes or paced"`
Expected:
- `test_route.py`: FAIL with `AttributeError: module … has no attribute 'YIELD_SEND_BYTES'`;
- the workflow test: FAIL with `AttributeError` from the monkeypatch;
- the dev-server test: FAIL with `WorkflowFailureError` — Temporal terminated the run (the three requests went out in
  one task).

- [ ] **Step 4: Implement the budget** — in `backend/src/dewpoint/engine/cel/route.py`, next to the other thresholds:

```python
YIELD_SEND_BYTES = 3 * 1024 * 1024  # cel.evaluate request bytes one workflow task sends: under Temporal's 4 MiB gRPC
# message limit, which terminates the workflow when a task's completion passes it (#15)
```

  and in `YieldBudget`: the docstring's first line becomes `"""One workflow task's local evaluations, the values they
  bound (`Measure.nodes`), and the cel.evaluate requests it sends."""`; add the field `sent: int = 0` after `nodes`;
  replace `must_yield`'s signature and first lines with:

```python
    def must_yield(self, record: ExpressionRecord | None = None, *, send: int = 0) -> bool:
        """True when the interpreter must await a 1 ms durable timer before binding a view (`record` None), before
        evaluating `record` locally, or before sending a request of `send` bytes. The first thing a workflow task does
        always runs; a view is always bound first, so an evaluation whose bounds pass an execution's first task's share
        waits for the next task. Sending has its own limit, Temporal's, with no startup share."""
        if send:
            return self.sent > 0 and self.sent + send > YIELD_SEND_BYTES
        if self.evaluations == 0 and self.nodes == 0:
            return False
```

  (the rest of `must_yield` is unchanged), and replace `charge` and `reset` with:

```python
    def charge(self, record: ExpressionRecord | None = None, *, nodes: int = 0, sent: int = 0) -> None:
        """A view bound (`nodes`: the values it bound), `record` evaluated locally, or a request of `sent` bytes."""
        self.nodes += nodes
        self.sent += sent
        if record is not None:
            self.iterations += record.iterations or 0
            self.bytes += record.bytes or 0
            self.work += record.work or 0
            self.evaluations += 1

    def reset(self, *, startup: bool = False) -> None:
        """A new workflow task starts a fresh budget: a tenth of it (`STARTUP_SHARE`) in an execution's first task,
        which also loads and compiles the version, or restores a snapshot."""
        self.iterations = self.bytes = self.work = self.evaluations = self.nodes = self.sent = 0
        self.share = STARTUP_SHARE if startup else 1
```

- [ ] **Step 5: Pace the sends** — in `backend/src/dewpoint/engine/runtime/execution.py`, `_yield_point` takes the
  bytes to send:

```python
    async def _yield_point(self, record: ExpressionRecord | None, *, send: int = 0) -> None:
```

  and its `if not self._yield.must_yield(record):` becomes `if not self._yield.must_yield(record, send=send):`; add to
  its docstring: `Before sending a cel.evaluate request (\`send\` its bytes), the same wait keeps a task's requests under
  Temporal's gRPC message limit (#15).` In `_evaluate`, keep the size `request_end` returns and send under the budget:

```python
            end, size = resolve.request_end(
```

```python
            chunk = resolve.CelTask(task.record, task.bindings[start:end], False)
            await self._yield_point(None, send=size)
            self._yield.charge(sent=size)
            try:
```

  In `backend/tests/apps/worker/test_run_graph_yield.py`, `Recording.charge` accepts and passes on `sent`:

```python
    def charge(self, record: Any = None, *, nodes: int = 0, sent: int = 0) -> None:
        if not workflow.unsafe.is_replaying():
            task = TASKS[workflow.info().get_current_history_length()]
            if nodes:
                task.append(("bind", nodes))
            if record is not None:
                task.append(("eval", record.work or 0))
        super().charge(record, nodes=nodes, sent=sent)
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `cd backend && uv run pytest tests/apps/worker/test_run_graph_cel_requests.py tests/apps/worker/test_real_server.py tests/apps/worker/test_run_graph_yield.py tests/engine/cel/test_route.py -q`
Expected: all PASS.

- [ ] **Step 7: The replay gate and the whole suite**

Run: `cd backend && uv run pytest tests/engine/replay -q && uv run pytest -q`
Expected: the replay gate passes with no change under `dewpoint-0.1.0+abi3/`; the whole suite passes (8 skipped, the
Linux-only evaluator tests, on macOS).

- [ ] **Step 8: Document the pacing** — `docs/superpowers/specs/2026-09-25-engine-core-design.md`:
  - §5.7, at the end of the **Temporal's payload limit** bullet from Task 2, add: `A workflow task sends at most 3 MiB
    of these requests (\`YIELD_SEND_BYTES\`); the next one waits for the next task, so CEL requests alone can't push a
    task's completion past Temporal's 4 MiB gRPC message limit, past which Temporal terminates the workflow. Other
    commands in the same task aren't counted: the invariant over every command is sub-project 2b's.`
  - §5.6, after the sub-bullet that begins `- Thresholds: 13,000 iterations, 5.5 MiB, 2,700,000 work units`, add the
    sub-bullet: `- Apart from them, the cel.evaluate requests a task sends: at most 3 MiB (§5.7). It has no startup
    share, since that limit is Temporal's, not CPU.`

- [ ] **Step 9: Static checks and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`
Expected: clean.

```bash
git add backend/src/dewpoint/engine/cel/route.py backend/src/dewpoint/engine/runtime/execution.py \
  backend/tests/engine/cel/test_route.py backend/tests/apps/worker/test_run_graph_yield.py \
  backend/tests/apps/worker/test_run_graph_cel_requests.py backend/tests/apps/worker/test_real_server.py \
  docs/superpowers/specs/2026-09-25-engine-core-design.md
git commit -m "fix(engine): a workflow task sends at most 3 MiB of cel.evaluate requests (#15)"
```

---

### Task 4: `ENGINE_ABI` 4 and its golden histories

A run's commands can change with Tasks 2 and 3 — a request between 1.75 and 2 MiB, which succeeded before, now splits,
and pacing can add a timer to a task that sent several requests — so engine-core §7 requires a new ABI. The abi3
histories stay as recorded; each build replays its own.

**Files:**
- Modify: `backend/src/dewpoint/engine/__init__.py`, `backend/tests/engine/cel/test_profile.py`
- Create: `backend/tests/engine/replay/dewpoint-0.1.0+abi4/*.json` (recorded by the recorder, never written by hand)
- Modify: `docs/superpowers/specs/2026-09-25-engine-core-design.md` (the status's revision list)

**Interfaces:**
- Consumes: Tasks 2 and 3's behavior; the recorder `tests.engine.replay.record` and `scenarios()`.
- Produces: `dewpoint.engine.ENGINE_ABI = 4`; build ids `dewpoint-<version>+abi4`; publishing stamps new versions 4.

- [ ] **Step 1: Write the failing tripwire** — in `backend/tests/engine/cel/test_profile.py`,
  `test_local_evaluation_is_a_build_constant_tied_to_the_engine_abi`'s assertion becomes:

```python
    assert (ENGINE_ABI, profile.LOCAL_CEL_PROFILE) == (4, profile.CURRENT_CEL_PROFILE)
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && uv run pytest tests/engine/cel/test_profile.py -q`
Expected: FAIL with `(3, 'cel-cpp-0.1.3/fn-1/cls-1') == (4, 'cel-cpp-0.1.3/fn-1/cls-1')`.

- [ ] **Step 3: Raise the ABI** — in `backend/src/dewpoint/engine/__init__.py`, the comment and the constant become:

```python
# The one engine ABI (spec §7): publishing stamps and hashes a version with it, and the build id names it. Bump it on
# any change that can alter a run's command sequence. 2: 2a-3b's loop batches, sub-flows, the failure handler and
# continue-as-new. 3: 2a-3c's local CEL. 4: issue #15's cel.evaluate requests, cut by their bytes, refused when one
# binding set can't fit, and paced per workflow task.
ENGINE_ABI = 4
```

- [ ] **Step 4: Run the tripwire and the replay suite**

Run: `cd backend && uv run pytest tests/engine/cel/test_profile.py tests/engine/replay -q`
Expected: the tripwire PASSES; `test_every_scenario_is_recorded_for_this_build` FAILS with "run `uv run python -m
tests.engine.replay.record`" (no abi4 histories yet); the others pass.

- [ ] **Step 5: Record ABI 4's golden histories** (the time-skipping server; nothing else to start)

Run: `cd backend && uv run python -m tests.engine.replay.record`
Expected: it writes `backend/tests/engine/replay/dewpoint-0.1.0+abi4/*.json`, one file per execution of every scenario
(as many scenarios as abi3 has); `git status` shows only new files under `dewpoint-0.1.0+abi4/`, and nothing changed
under `dewpoint-0.1.0+abi3/` or older.

- [ ] **Step 6: The replay suite and the whole suite**

Run: `cd backend && uv run pytest tests/engine/replay -q && uv run pytest -q`
Expected: every abi4 history replays, `test_recorded_histories_carry_no_host_data` passes, the gate tests pass; the
whole suite passes (8 skipped, the Linux-only evaluator tests, on macOS).

- [ ] **Step 7: Record the revision** — in `docs/superpowers/specs/2026-09-25-engine-core-design.md`, the status's
  revision list, after the revision 5.6 entry, add:

```markdown
  - Revision 5.6.1 (issue #15): a `cel.evaluate` request is cut by its JSON bytes as well as by 1,000 binding sets,
    a binding set that alone passes 1.75 MiB is `input_too_large`, and a workflow task sends at most 3 MiB of CEL
    requests (§5.6, §5.7). A run's commands can change, so `engine_abi` becomes 4, with its own golden histories.
```

- [ ] **Step 8: Static checks and commit**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`
Expected: clean.

```bash
git add backend/src/dewpoint/engine/__init__.py backend/tests/engine/cel/test_profile.py \
  backend/tests/engine/replay/dewpoint-0.1.0+abi4 docs/superpowers/specs/2026-09-25-engine-core-design.md
git commit -m "feat(engine): ENGINE_ABI 4, and its golden histories (#15)"
```

---

## During execution

- **The final review** found that a refused binding set didn't end the evaluation: every set after it was measured in
  the same workflow task, and a filter of a few hundred items each binding about 1.8 MiB outlasted the SDK's 2 s
  deadlock timeout and retried forever — #15's symptom. `_evaluate` now stops at the first refused set and reports the
  rest `input_too_large` too; they can't change the result. Tests:
  `test_no_binding_set_after_a_refused_one_is_measured_or_sent` and
  `test_the_sets_before_a_refused_one_are_sent_and_none_after_it`. It lands before ABI 4 ships, so it needs no
  further ABI.
- **abi4's recorded histories differ in shape from abi3's** (for example `continue_as_new`: 6 executions against 7).
  Recordings vary from run to run on the same code: a real-time race between each execution's projection and its
  next step decides where each continue falls. Cross-replay passes both ways, and the final outcomes are identical.

## Handoff

- **2b-1a** generalizes both rules to every outgoing command, measured after its codec (2b spec §5.2): the payload
  guard (with spilling) and the per-task byte budget, of which `YIELD_SEND_BYTES` becomes one part. It re-verifies
  `CEL_REQUEST_BYTES` against the encoded size, and registers the capability `cel_request_size_guard`.
- **Not covered here:** other commands in the same workflow task (plugin configs, projections, children) still count
  toward Temporal's gRPC limit unpaced; oversized continue-as-new snapshots are issue #16.
- **Rolling out ABI 4:** start the new build's workers and make it current (`dewpoint deployment set-current`); runs
  already started finish on their pinned ABI-3 build, which is stopped once it reports `drained`; every workflow is
  published again for ABI 4, children first, before new runs start (`docs/operations/deployment.md`).
- **The 2b spec's ABI numbers shift:** it names 2b-1a's ABI 4 and 2b-1b's 5; after this change they become 5 and 6.
  Revise it when the 2b-1a plan is written.
- After merge, #15 can be closed with a link to the merge commit and the dev-server tests.
