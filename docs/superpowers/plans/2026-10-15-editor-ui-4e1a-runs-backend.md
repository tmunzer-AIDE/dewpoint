# Editor UI 4e-1a: the runs backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The API the Runs page and a run's page read (the runs design §4): typed run answers, B10's filters and
labels, where a request came from (migration 0073), a run's step reads for every run, its input read back, a bounded
run detail, and the Workflows list's last run's id.

**Architecture:**
- **Where a request came from.** Migration 0073 adds `rerun_of` and `trigger_id` to `run_requests`. Admission writes
  them: a re-run's original from its `Rerun`, a schedule's or a webhook endpoint's id from a new `trigger_id`
  argument.
- **The list (B10).** `service.list_items` filters the `UNION ALL` of runs and unstarted requests by status (two
  grouped values), mode, draft simulations, source and `since`. It reads the page first, then labels it in one join:
  the workflow's name, who asked, the schedule's timing, the endpoint's name.
- **A run's steps.** `apps/step_summary.py`, 4d-1b's draft-only summary, serves every run. It counts outcomes for a
  live run's origins (`sent`, `may_have_been_sent`, none), says `not_recorded` for a graph older than ABI 9, reads one
  instance's attempts, and names the sub-runs a page of instances started. Three routes under `/runs/{id}/steps`
  read them.
- **A run as itself.** `GET /runs/{id}` loses `steps` and `children`, gains the list's labels, `draft_revision`,
  `outcomes_recorded`, `parent` and a typed CSV record. `GET /runs/{id}/input` reads the request's envelope back,
  redacted, as 4d-1b does for simulations. The read-back moves to `runs.py` for both.

**Tech Stack:** FastAPI with pydantic response models (`extra="forbid"`), SQLAlchemy 2 (async) over PostgreSQL 16 with
row-level security, the online-migration helper (`backend/migrations/online.py`), pytest with testcontainers and
pytest-xdist, and openapi-typescript for the web client's types.

**Spec:** `docs/superpowers/specs/2026-10-15-editor-4e1-runs-design.md`: §4 (the backend), with §2 (the plans), §3
(the owner's answers), §6 (4e-1a's tests) and §8 (the review's answers). The UI is 4e-1b's plan, after this one merges.

## How this plan was checked

The plan's code was checked before review on a scratch checkout of main at dd1cb01b, never on a branch. Each
task's diffs were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff and the same tests: they passed;
- after every task, ruff, `ruff format --check` and mypy: silent;
- after Task 8's docs, `dewpoint api openapi` and openapi-typescript regenerated the client; `check:api` passed, and
  the tree matched the prototype the diffs were cut from, every file, byte for byte;
- the 13 diff blocks, taken from this file's own text, are the diffs applied, byte for byte, in order.

On the final tree:
- the privilege reference, `test_online.py` and 0073's tests: 50 passed;
- the API, admission, summary and core runs tests: 708 passed;
- `lint-imports`: 11 contracts kept;
- the frontend's type check and ESLint: silent;
- its suite: 1184 passed (90 files), unchanged;
- CodeQL (python, CLI 2.27.2, python-queries 1.8.12, CI's filter): no finding.

The whole backend suite wasn't run: Task 8 asks the owner first. The prototype's list was measured with EXPLAIN ANALYZE
on 100,000 items (ruling 1). The executor still runs every step: the check is evidence, not a substitute.

## Global Constraints

- **The backend and its generated client only.** No screen changes (4e-1b's). The 4d-1c frontend keeps passing as it
  is: its draft simulation types are unchanged.
- **Migration 0073 is the owner's slot** (the design §8): the online-migration helper, one step; no grant changes (the
  inserting roles hold table-level INSERT, the API SELECT); never Alembic autogenerate.
- **No ABI change:** `ENGINE_ABI` stays 9. No new dependency.
- **Every answer is typed**, and models forbid extra keys. `openapi.json` and `schema.d.ts` are regenerated, never
  edited by hand.
- **Nothing secret leaves:** previews stay as the projection stored them (`[redacted]`, `[truncated]`). The input read
  back puts `[redacted]` for every claim. Logs name an exception's type, never a value.
- **Tests run as CI runs them:** `cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 <files>` (the fixture's
  own `uv run alembic` would sync otherwise).
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Nothing is pushed; the owner merges.

## Review Focus

The inputs and failure modes the design implies that a person would meet first. Each is pinned by a test in the task
that owns the code:

1. **A live step whose answer was lost and then cancelled** (an ambiguous cancel: `cancelled` with `outcome_unknown`)
   says "may have been sent", never just "cancelled". Task 4:
  `test_a_live_runs_origins_say_what_was_sent_and_nothing_of_control_steps`
   and `test_a_live_steps_origin_says_what_was_sent`.
2. **A request from before 0073, or whose schedule was deleted,** lists with its kind and null details, never a 500.
   Task 3: `test_an_item_names_its_workflow_who_asked_a_requested_cancel_and_where_it_came_from`.
3. **A sub-run's page** reads its own (sub-flow) version's graph and names its parent; its parent's step instance names
   it. Task 5: `test_a_sub_flow_is_projected_as_a_run_of_its_own`.
4. **A tenant's key gone during an erasure:** the input reads back `unreadable`, never a 503 page. Task 6:
   `test_an_input_that_doesnt_open_is_unreadable_its_key_gone_included`.
5. **A run past its retention cutoff** answers 404 on every new read, as on its detail. Task 6:
   `test_a_runs_step_reads_and_its_input_keep_its_cutoff`.

## Rulings (proposed; they join the ledger as 210 onward when the owner accepts the plan)

Each says what was decided, why, and what it costs if wrong. Found while building the prototype the diffs come from.

1. **No index in 0073.** On one tenant with 50,000 runs and 50,000 unstarted requests, the unfiltered page took 85 ms.
   It sorts every item, as today's list already does. A status- or source-filtered page took about 9 ms: the filters
   shrink the sort and add no scan. Cost if wrong: an index in a later migration.
2. **`trigger_id` is an explicit argument** to `admit_request` and `record_refused`, passed by the schedule tick and
   by webhook matching. It isn't read from the audit details. Cost: none.
3. **`started_by` names a person only for `manual`, `rerun` and pre-2b-2 runs.** Admission's tests give every source
   an actor; a schedule or a webhook never has one. Cost: none.
4. **A refused or dead request shows its reason code, not messages.** Admission keeps only the reason
   (`record_refused` passes the messages to the refusal, never to the row). This amends the design §5.4's "the
   server's messages (up to 5)": the UI words each code. Cost: a refused schedule's run page says why only by its code;
   storing messages would be a third column.
5. **The status filter takes one value,** with `waiting` (queued, starting) and `didnt_start` (refused, dead) grouping
   two. It applies to the union's `status`, so it covers a run's or an unstarted request's. Cost: none.
6. **`draft=exclude` is the default** (the design §4.2), which changes today's answer. The one test that lists a draft
   simulation (`test_simulations_api.py`) now asks `draft=only`. Cost: none.
7. **A run's step reads have models of their own** (`RunStepSummaryOut`, `RunInstancesOut`, `RunAttemptsOut`,
   `RunStepOut`). The draft simulation routes keep theirs, so 4d-1c's origin union and types don't change. Their
   finals and items gain `child_run_id` (additive), through the shared `_step`. Cost: two models for one shape.
8. **A live run's origin:** `may_have_been_sent` first, whatever else the step's finals say; then `sent` for a plugin
   step whose finals include `applied`; else none (a control step, or nothing sent). Cost: none.
9. **`OUTCOMES_ABI = 9` is a constant in `step_summary.py`.** Versions are immutable, so tests patch the constant to
   read the current graph as an older one. Cost: none.
10. **The step reads come before the bounded detail** (Task 4, then 5). The tests that read a run's old `steps` and
    `children` (the triggers end to end, the worker's projection, retention) move to the new reads in Task 5. Cost:
    none.
11. **`service.children` and `service.run_steps` stay:** the core service's own tests use them; the route stops. Cost:
    none.
12. **The attempts read is bounded at 20,** a retry policy's most (`max_attempts`, `le=20`). Cost: none.
13. **A request that hasn't started has steps that haven't run:** `not_reached_yet`, or `didnt_run` once it ended
    (refused, dead, cancelled). Its instances and attempts are empty, never a 404. Cost: none.
14. **`read_back` moves to `runs.py`,** and the simulations route imports it. `absent` means the request kept no
    envelope (a refusal that froze nothing, or a run from before 2b-2). Retention keeps a request's envelope as long as
    the request and drops only its claims, which read back as `[redacted]`. This amends the design §4.3's wording. A
    tenant's key gone reads as `unreadable` (the design). A CSV start's `rows` and `row_count` are left out. Cost: none.
15. **Cancel is typed** (`CancelOut` with `RequestOut`). Start and re-run stay untyped until 4e-2 types them with
    their forms. Cost: none.
16. **The detail keeps `parent_run_id` beside the new `parent`.** Cost: none.
17. **0073's downgrade drops the columns, never refusing:** they record where a request came from, never what it ran.
    Cost: older pages lose their trigger details.
18. **The Workflows list's `LastRun` gains `id`, defaulting to None:** the summary's unit tests construct it without
    one. The API always reads it. Cost: none.
19. **The client is regenerated as CI checks it** (`dewpoint api openapi`, then `pnpm gen:api`). The frontend suite,
    type check and lint pass unchanged. Cost: none.
20. **The summary's cost is pinned by statements, not time:** three statements for 100,000 instances. Cost: none.

Mid-slice rulings start at M103.

## File structure

| File | Responsibility |
|---|---|
| `backend/migrations/versions/0073_request_origins.py` | create: `rerun_of`, `trigger_id` (Task 2) |
| `backend/src/dewpoint/core/models/requests.py` | the two columns (Task 2) |
| `backend/src/dewpoint/apps/admission.py` | writes them; `trigger_id` argument (Task 2) |
| `backend/src/dewpoint/apps/dispatcher/tick.py`, `matching.py` | pass the schedule's, the endpoint's id (Task 2) |
| `backend/src/dewpoint/core/runs/service.py` | the list's filters and labels (Task 3); `graph_of` (Task 4); `labels` (Task 5) |
| `backend/src/dewpoint/apps/step_summary.py` | live origins, `not_recorded`, outcomes, attempts, children (Task 4) |
| `backend/src/dewpoint/apps/api/routes/runs.py` | the list (Task 3), the step reads (Task 4), the detail (Task 5), the input (Task 6) |
| `backend/src/dewpoint/apps/api/routes/run_requests.py` | cancel typed (Task 5) |
| `backend/src/dewpoint/apps/api/routes/simulations.py` | imports `read_back` (Task 6) |
| `backend/src/dewpoint/apps/api/responses.py` | the run models (Tasks 3–6), `LastRunOut.id` (Task 7) |
| `backend/src/dewpoint/apps/workflow_summary.py`, `routes/workflows.py` | the last run's id (Task 7) |
| `frontend/src/api/openapi.json`, `schema.d.ts` | regenerated (Task 8) |
| `docs/operations/runs.md` | "Reading runs" (Task 8) |

## Milestones

1. **Tasks 1–3:** the ledger, where a request came from, the list. Pause for the owner's review.
2. **Tasks 4–6:** a run's steps, a run as itself, its input. Pause for the owner's review.
3. **Tasks 7–8:** the last run's id, the client, the docs, every check, the final checkpoint. Then the final review.

---

# Milestone 1 — Where a request came from, and the list

### Task 1: The ledger: the 4e-1 design and this plan accepted

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger section later tasks append to (`### 4e-1a, milestone N`).

- [ ] **Step 1: Append the design's and the plan's status**

Run this task only once the owner has accepted the plan. Append exactly:

```markdown
### 4e-1: the design accepted; the 4e-1a plan accepted (2026-10-15)

The owner started 4e ("Start the 4e plan") after 4d-1c merged (#111, c5b63da5) and its minors were filed (#112).
Their answers, in chat:
- shape: "Read first, then start". 4e-1 is the Runs page, a run's page and cancel; 4e-2 is the run form with CSV
  mapping and the re-run dialog;
- the list shows a failed run's error; draft simulations appear only through the Mode filter; runs are named by
  their first 8 characters; "Ran out of time" everywhere;
- a run's page is laid out like the editor; Cancel asks first for live runs only; times are in the person's own zone.

D8 was signed off ("D8 signed off; write the 4e-1 spec") at the Design canvas "4e-1 Runs Mockups", version 9.
`docs/superpowers/specs/2026-10-15-editor-4e1-runs-design.md` (5fc7b5a1) was accepted ("Yes to all four; commit the
spec"):
- migration slot 0073 for `rerun_of` and `trigger_id`;
- the starter's email shown to every run viewer;
- the run detail loses `steps` and `children`;
- "sent" on reads too.

`docs/superpowers/plans/2026-10-15-editor-ui-4e1a-runs-backend.md`, revision 1, was accepted. Its rulings 1–20 join
this ledger as 210–229. Mid-slice rulings start at M103. Backend and generated client only: no screen change, no ABI
change.

210. **Accepted. No index in 0073** (plan ruling 1): the filters shrink the list's sort; they add no scan.
211. **Accepted. `trigger_id` is an explicit admission argument** (plan ruling 2).
212. **Accepted. `started_by` names a person for `manual`, `rerun` and pre-2b-2 runs only** (plan ruling 3).
213. **Accepted. A refused or dead request shows its reason code, not messages** (plan ruling 4; amends the design
     §5.4).
214. **Accepted. The status filter takes one value; `waiting` and `didnt_start` group two** (plan ruling 5).
215. **Accepted. `draft=exclude` is the list's default** (plan ruling 6).
216. **Accepted. A run's step reads have models of their own; the draft routes keep theirs** (plan ruling 7).
217. **Accepted. A live origin: `may_have_been_sent` first, `sent` for plugin steps, else none** (plan ruling 8).
218. **Accepted. `OUTCOMES_ABI = 9` is a constant; tests patch it** (plan ruling 9).
219. **Accepted. The step reads come before the bounded detail** (plan ruling 10).
220. **Accepted. `service.children` and `service.run_steps` stay** (plan ruling 11).
221. **Accepted. The attempts read is bounded at 20** (plan ruling 12).
222. **Accepted. A request that hasn't started has steps that haven't run** (plan ruling 13).
223. **Accepted. `read_back` moves to `runs.py`; `absent` means no envelope kept** (plan ruling 14; amends the design
     §4.3's wording).
224. **Accepted. Cancel is typed; start and re-run wait for 4e-2** (plan ruling 15).
225. **Accepted. The detail keeps `parent_run_id` beside `parent`** (plan ruling 16).
226. **Accepted. 0073's downgrade drops the columns** (plan ruling 17).
227. **Accepted. `LastRun.id` defaults to None** (plan ruling 18).
228. **Accepted. The client is regenerated as CI checks it** (plan ruling 19).
229. **Accepted. The summary's cost is pinned by statements** (plan ruling 20).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): the 4e-1 design accepted, the 4e-1a plan accepted (rulings 210-229)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Where a request came from (migration 0073)

**Spec:** §4.3 (the two columns), §8 (slot 0073).

**Files:**
- Create: `backend/migrations/versions/0073_request_origins.py`
- Modify: `backend/src/dewpoint/core/models/requests.py` (two columns), `backend/src/dewpoint/apps/admission.py`
  (`admit_request`, `record_refused`, `_insert`), `backend/src/dewpoint/apps/dispatcher/tick.py`,
  `backend/src/dewpoint/apps/dispatcher/matching.py`
- Test: create `backend/tests/migrations/test_0073.py`, `backend/tests/apps/test_admission_origins.py`; modify
  `backend/tests/apps/dispatcher/test_matching.py`

**Interfaces:**
- Consumes: `migrations.online.online`, `step`, `exists`; admission's `Rerun` (`of: uuid.UUID`).
- Produces:
  - `RunRequest.rerun_of: uuid.UUID | None` and `RunRequest.trigger_id: uuid.UUID | None`;
  - `admission.admit_request(..., trigger_id: uuid.UUID | None = None)` and
    `admission.record_refused(..., trigger_id: uuid.UUID | None = None)`;
  - `tests/apps/test_admission_origins.py`'s `schedule(api, ctx, wf, *, enabled=True) -> uuid.UUID` (Task 3 uses
    it).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/dispatcher/test_matching.py b/backend/tests/apps/dispatcher/test_matching.py
index 116b9fbb..8351c026 100644
--- a/backend/tests/apps/dispatcher/test_matching.py
+++ b/backend/tests/apps/dispatcher/test_matching.py
@@ -131,6 +131,23 @@ async def test_a_refused_admission_is_a_request_too(dev, owner_sessionmaker, ing
     assert (await event_state(owner_sessionmaker, event_id))["request_count"] == 1
 
 
+@pytest.mark.parametrize("enabled", [True, False], ids=["admitted", "refused"])
+async def test_an_events_request_names_the_endpoint_it_came_through(
+    dev, owner_sessionmaker, ingress_sessionmaker, dispatch_sessionmaker, enabled: bool
+) -> None:
+    """The runs design §4.3: the request's `trigger_id` is its endpoint, admitted or refused."""
+    await bind(owner_sessionmaker, dev)
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update workflows set enabled = :e where id = :w"), {"e": enabled, "w": dev.workflow_id})
+    [event_id] = await send(ingress_sessionmaker, dev, ALARM)
+    assert await matched(dispatch_sessionmaker, dev, event_id) == "matched"
+    async with owner_sessionmaker() as s:
+        found = await s.execute(text("select status, rerun_of, trigger_id from run_requests "
+                                     "where idempotency_key like :k"), {"k": f"evt:{event_id}:%"})  # fmt: skip
+        row = found.one()
+    assert (row.status, row.rerun_of, row.trigger_id) == ("queued" if enabled else "refused", None, dev.endpoint_id)
+
+
 async def test_with_the_gate_off_nothing_is_matched(ready, owner_sessionmaker, dispatch_sessionmaker) -> None:
     async with owner_sessionmaker() as s, s.begin():  # a production deployment, its runs off by default (the gate)
         await record_environment(s, environment=PRODUCTION, namespace="default")
diff --git a/backend/tests/apps/test_admission_origins.py b/backend/tests/apps/test_admission_origins.py
new file mode 100644
index 00000000..aa8bd908
--- /dev/null
+++ b/backend/tests/apps/test_admission_origins.py
@@ -0,0 +1,74 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Where a request came from, in plain ids on its row (editor 4e-1; the runs design §4.3): a re-run names the run it
+repeats; a schedule's request, admitted or refused, names its schedule. A request by hand names neither."""
+
+import uuid
+from datetime import UTC, datetime
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import admission, schedules
+from dewpoint.apps.dispatcher import tick
+from dewpoint.core.db import tenant_scope
+from tests.apps.test_admission import KEYS, TOKEN, admit, current, published
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+async def origins(owner: Any, request_id: uuid.UUID) -> tuple[Any, Any]:
+    async with owner() as s:
+        found = await s.execute(text("select rerun_of, trigger_id from run_requests where id = :i"), {"i": request_id})
+        row = found.one()
+        return row.rerun_of, row.trigger_id
+
+
+async def test_a_rerun_names_the_run_it_repeats_and_a_request_by_hand_names_nothing(
+    ready, owner_sessionmaker, api_sessionmaker
+) -> None:
+    ctx, wf = ready
+    first = (await admit(api_sessionmaker, ctx, wf, key="first")).request
+    again = (await admit(api_sessionmaker, ctx, wf, key="again", source="rerun",
+                         rerun=admission.Rerun(of=first.id, input={"token": TOKEN}))).request  # fmt: skip
+    assert await origins(owner_sessionmaker, first.id) == (None, None)
+    assert await origins(owner_sessionmaker, again.id) == (first.id, None)
+
+
+async def schedule(api: Any, ctx: Any, wf: uuid.UUID, *, enabled: bool = True) -> uuid.UUID:
+    async with api() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        created = await schedules.create(
+            s, KEYS, tenant_id=ctx.tenant_id, actor_id=ctx.user.id, workflow_id=wf,
+            timing={"cron": "0 9 * * *", "every_s": None, "offset_s": 0, "time_zone": "UTC", "catchup_window_s": 600},
+            mode="live", input={"token": TOKEN}, enabled=enabled,
+        )  # fmt: skip
+        return created.id
+
+
+async def ticked(dispatch: Any, ctx: Any, schedule_id: uuid.UUID) -> uuid.UUID:
+    key = tick.tick_key(str(schedule_id), datetime.now(UTC).replace(microsecond=0))[0]
+    async with dispatch() as s, s.begin():
+        await tick.admit_tick(s, KEYS, tenant_id=ctx.tenant_id, schedule_id=schedule_id, key=key)
+        found = await s.execute(text("select id from run_requests where idempotency_key = :k"), {"k": key})
+        return found.scalar_one()
+
+
+@pytest.mark.parametrize("enabled", [True, False], ids=["admitted", "refused"])
+async def test_a_schedules_request_names_its_schedule_admitted_or_refused(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, enabled: bool
+) -> None:
+    ctx, wf = ready
+    schedule_id = await schedule(api_sessionmaker, ctx, wf, enabled=enabled)
+    request_id = await ticked(dispatch_sessionmaker, ctx, schedule_id)
+    async with owner_sessionmaker() as s:
+        status = (await s.execute(text("select status from run_requests where id = :i"), {"i": request_id})).scalar()
+    assert status == ("queued" if enabled else "refused")
+    assert await origins(owner_sessionmaker, request_id) == (None, schedule_id)
diff --git a/backend/tests/migrations/test_0073.py b/backend/tests/migrations/test_0073.py
new file mode 100644
index 00000000..0ac5c071
--- /dev/null
+++ b/backend/tests/migrations/test_0073.py
@@ -0,0 +1,65 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Migration 0073 on disposable databases, in a cluster of this module's own (editor 4e-1; the runs design §4.3): a
+request's `rerun_of` and `trigger_id`, nullable with no default, null on every request before it; its downgrade drops
+them. Its online step is interrupted, bounded and compared with a fresh database by `test_online.py`, as every online
+migration's is."""
+
+import asyncio
+from collections.abc import AsyncIterator, Iterator
+
+import asyncpg
+import pytest
+from testcontainers.community.postgres import PostgresContainer
+
+from tests.migrations.support import copy, downgrade, upgrade
+from tests.migrations.test_0053 import _drop, _sql
+from tests.probes.migration_locks import seed
+
+ROOTS = 5
+COLUMNS = ("SELECT column_name, is_nullable, column_default FROM information_schema.columns WHERE table_name = "
+           "'run_requests' AND column_name IN ('rerun_of', 'trigger_id') ORDER BY column_name")  # fmt: skip
+
+
+async def _rows(url: str, query: str) -> list[tuple[object, ...]]:
+    c = await asyncpg.connect(url)
+    try:
+        return [tuple(r) for r in await c.fetch(query)]
+    finally:
+        await c.close()
+
+
+@pytest.fixture(scope="module")
+def cluster() -> Iterator[str]:
+    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
+        yield pg.get_connection_url().rsplit("/", 1)[0]
+
+
+@pytest.fixture(scope="module")
+def template(cluster: str) -> str:
+    """A seeded database at 0072, as the deployments that run 0073 are."""
+    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0072"'))
+    upgrade(f"{cluster}/t0072", "0034")
+    asyncio.run(seed(f"{cluster}/t0072", ROOTS))
+    upgrade(f"{cluster}/t0072", "0072")
+    return "t0072"
+
+
+@pytest.fixture
+async def db(cluster: str, template: str) -> AsyncIterator[str]:
+    url = await copy(cluster, template)
+    yield url
+    await _drop(cluster, url.rsplit("/", 1)[1])
+
+
+async def test_a_requests_origins_are_nullable_and_null_before_it(db: str) -> None:
+    await asyncio.to_thread(upgrade, db, "0073")
+    assert await _rows(db, COLUMNS) == [("rerun_of", "YES", None), ("trigger_id", "YES", None)]
+    counted = await _rows(db, "SELECT count(*) > 0, count(rerun_of), count(trigger_id) FROM run_requests")
+    assert counted == [(True, 0, 0)]
+
+
+async def test_the_downgrade_drops_them(db: str) -> None:
+    await asyncio.to_thread(upgrade, db, "0073")
+    await _sql(db, "UPDATE run_requests SET rerun_of = gen_random_uuid(), trigger_id = gen_random_uuid()")
+    await asyncio.to_thread(downgrade, db, "0072")
+    assert await _rows(db, COLUMNS) == []
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/migrations/test_0073.py \
  tests/apps/test_admission_origins.py \
  tests/apps/dispatcher/test_matching.py
```

Expected: FAIL, 7 failed and 22 passed: `test_0073.py`'s two tests can't upgrade ("Can't locate revision identified by
'0073'"); the admission tests and the matching test's two cases meet `column "rerun_of" does not exist`.

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/migrations/versions/0073_request_origins.py b/backend/migrations/versions/0073_request_origins.py
new file mode 100644
index 00000000..8e08de02
--- /dev/null
+++ b/backend/migrations/versions/0073_request_origins.py
@@ -0,0 +1,32 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Editor 4e-1 (the runs design §4.3): where a request came from, in plain ids a run's page and the runs list read.
+
+- `run_requests.rerun_of`: the run a re-run repeats. Its audit entry names it already; the row now does.
+- `run_requests.trigger_id`: the schedule a `schedule` request came from, or the webhook endpoint of a `webhook`
+  request. The trigger itself stays in the request's encrypted envelope; this is its id, never a secret.
+
+Both are nullable, with no default (a catalog change only), and null on every request before this one. No grant
+changes: the roles that insert requests hold INSERT on the table, and the API holds SELECT. Online (2b-4b, D15), one
+step. The downgrade drops them: they record where a request came from, never what it ran.
+
+Slot 0073 is the owner's (the runs design §8), chained after 0072."""
+
+from alembic import op
+
+from migrations.online import exists, online, step
+
+revision = "0073"
+down_revision = "0072"
+branch_labels = None
+depends_on = None
+
+
+def upgrade() -> None:
+    with online() as conn:
+        step(conn, "0073 run_requests columns",
+             "ALTER TABLE run_requests ADD COLUMN rerun_of uuid, ADD COLUMN trigger_id uuid",
+             done=exists("column", "trigger_id", "run_requests"))  # fmt: skip
+
+
+def downgrade() -> None:
+    op.execute("ALTER TABLE run_requests DROP COLUMN trigger_id, DROP COLUMN rerun_of")
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index 6a791a92..78d6b4ff 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -246,10 +246,12 @@ async def admit_request(
     rerun: Rerun | None = None,
     csv: CsvStart | None = None,
     details: dict[str, object] | None = None,
+    trigger_id: uuid.UUID | None = None,
 ) -> Admitted:
     """The request under `idempotency_key`: an exact retry's, or a new one, frozen. A re-run's digest covers its
-    `rerun` identity in place of `input`, and a CSV start's its `csv` beside it. Raises IdempotencyConflictError,
-    WorkflowNotFoundError, or, for an interactive source, AdmissionRefusedError."""
+    `rerun` identity in place of `input`, and a CSV start's its `csv` beside it. `trigger_id` is the schedule or webhook
+    endpoint a durable source's request came from. Raises IdempotencyConflictError, WorkflowNotFoundError, or, for an
+    interactive source, AdmissionRefusedError."""
     if source not in INTERACTIVE + DURABLE or mode not in (LIVE, SIMULATE):
         raise ValueError(f"no such source or mode: {source}, {mode}")
     if csv is not None and source not in ("manual", "rerun"):
@@ -286,10 +288,11 @@ async def admit_request(
         if source in INTERACTIVE:
             raise AdmissionRefusedError(refused.reason, refused.messages) from None
         return await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, None, None, refused,
-                             rerun, extra=details)  # fmt: skip
+                             rerun, extra=details, trigger_id=trigger_id)  # fmt: skip
     await _before_insert()
     admitted = await _insert(s, keys, tenant_id, request_id, actor_id, idempotency_key, digested, frozen.version_id,
-                             frozen.envelope_id, rerun=rerun, extra={**frozen.details, **(details or {})})  # fmt: skip
+                             frozen.envelope_id, rerun=rerun, extra={**frozen.details, **(details or {})},
+                             trigger_id=trigger_id)  # fmt: skip
     if admitted.new:
         await savepoint.commit()
     else:
@@ -345,10 +348,11 @@ async def admit_draft(
 async def record_refused(
     s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, source: str, mode: str,
     idempotency_key: str, reason: str, messages: list[str], details: dict[str, object] | None = None,
+    trigger_id: uuid.UUID | None = None,
 ) -> RunRequest:  # fmt: skip
     """A durable source's refusal decided before admission, a paused or deleted schedule's tick (§8.2): a `refused`
     request under its key, frozen like any, never lost; an exact retry finds it. Raises IdempotencyConflictError when
-    the key holds another request."""
+    the key holds another request. `trigger_id` is the schedule or webhook endpoint it came from."""
     if source not in DURABLE:
         raise ValueError(f"only a durable source's refusal is recorded: {source}")
     await tenant_scope(s, tenant_id)
@@ -358,7 +362,7 @@ async def record_refused(
         return (await _retry(keys, tenant_id, existing, fields)).request
     refused = _Refused(reason, messages)
     inserted = await _insert(s, keys, tenant_id, uuid.uuid4(), None, idempotency_key, fields, None, None, refused,
-                             extra=details)  # fmt: skip
+                             extra=details, trigger_id=trigger_id)  # fmt: skip
     return inserted.request
 
 
@@ -656,9 +660,11 @@ async def _insert(
     rerun: Rerun | None = None,
     extra: dict[str, object] | None = None,
     draft: _DraftFrozen | None = None,
+    trigger_id: uuid.UUID | None = None,
 ) -> Admitted:
     """The request row, queued or refused, and its audit entry; `new` False when another transaction won the key. A
-    draft simulation's (`draft`) is frozen on its snapshot."""
+    draft simulation's (`draft`) is frozen on its snapshot. The row names where it came from (the runs design §4.3):
+    the run a re-run repeats, and the schedule or endpoint of a durable source's."""
     key_version, digest = await digests.digest(keys, str(tenant_id), **fields)  # the tenant's active key (§7.2)
     status = "refused" if refused else "queued"
     row = {
@@ -676,6 +682,8 @@ async def _insert(
         "reason": refused.reason if refused else None,
         "ended_at": func.now() if refused else None,
         "envelope_id": envelope_id,
+        "rerun_of": rerun.of if rerun is not None else None,
+        "trigger_id": trigger_id,
     }
     if draft is not None:
         row |= {"draft_snapshot_id": draft.snapshot_id, "target_step_id": draft.target,
diff --git a/backend/src/dewpoint/apps/dispatcher/matching.py b/backend/src/dewpoint/apps/dispatcher/matching.py
index 01f86885..38b77abf 100644
--- a/backend/src/dewpoint/apps/dispatcher/matching.py
+++ b/backend/src/dewpoint/apps/dispatcher/matching.py
@@ -314,6 +314,7 @@ async def _match(
             s, keys, tenant_id=tenant_id, workflow_id=binding.workflow_id, source=SOURCE, actor_id=None, mode=LIVE,
             idempotency_key=f"evt:{event.id}:{binding.workflow_id}", input=payload,
             details={"endpoint_id": str(endpoint_id), "event_id": str(event.id), "binding_id": str(binding.id)},
+            trigger_id=endpoint_id,
         )  # fmt: skip
         admitted += 1
         queued += request.new and request.request.status == "queued"
diff --git a/backend/src/dewpoint/apps/dispatcher/tick.py b/backend/src/dewpoint/apps/dispatcher/tick.py
index 303c7be7..2d387fe6 100644
--- a/backend/src/dewpoint/apps/dispatcher/tick.py
+++ b/backend/src/dewpoint/apps/dispatcher/tick.py
@@ -148,7 +148,7 @@ async def admit_tick(
             )  # fmt: skip
             refused = await admission.record_refused(
                 s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", mode=schedule.mode,
-                idempotency_key=key, reason=reason, messages=[said], details=named,
+                idempotency_key=key, reason=reason, messages=[said], details=named, trigger_id=schedule_id,
             )  # fmt: skip
             return _outcome(refused)
         late = await _database_now(s) - _parsed(key.split(":", 2)[2])
@@ -157,7 +157,7 @@ async def admit_tick(
             expired = await admission.record_refused(
                 s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", mode=schedule.mode,
                 idempotency_key=key, reason=SCHEDULE_CATCHUP_EXPIRED,
-                messages=["The tick is past its schedule's catch-up window."], details=named,
+                messages=["The tick is past its schedule's catch-up window."], details=named, trigger_id=schedule_id,
             )  # fmt: skip
             if new and expired.reason == SCHEDULE_CATCHUP_EXPIRED:  # the caller alerts once its transaction commits
                 s.info.setdefault(EXPIRED, []).append({"schedule_id": str(schedule_id),
@@ -167,7 +167,7 @@ async def admit_tick(
         given = json.loads(await cipher.open(str(tenant_id), str(schedule_id), schedule.input))
         admitted = await admission.admit_request(
             s, keys, tenant_id=tenant_id, workflow_id=schedule.workflow_id, source="schedule", actor_id=None,
-            mode=schedule.mode, idempotency_key=key, input=given, details=named,
+            mode=schedule.mode, idempotency_key=key, input=given, details=named, trigger_id=schedule_id,
         )  # fmt: skip
     except admission.IdempotencyConflictError:
         return "recorded"
diff --git a/backend/src/dewpoint/core/models/requests.py b/backend/src/dewpoint/core/models/requests.py
index 94e7a5a4..a0ae053a 100644
--- a/backend/src/dewpoint/core/models/requests.py
+++ b/backend/src/dewpoint/core/models/requests.py
@@ -89,6 +89,10 @@ class RunRequest(Base):
     target_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
     draft_revision: Mapped[int | None] = mapped_column(Integer)
     admission_checks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
+    # Where it came from, in plain ids (editor 4e-1; the runs design §4.3): the run a re-run repeats, and the schedule
+    # or webhook endpoint it came from. Null on every request before migration 0073.
+    rerun_of: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    trigger_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
 
 
 class TenantRunLimits(Base):
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 29 passed.

- [ ] **Step 5: Run the static checks**

Run:

```bash
cd backend \
  && uv run ruff check src tests migrations \
  && uv run ruff format --check src tests migrations \
  && uv run mypy src
```

Expected: silent ("All checks passed!", every file already formatted, "Success: no issues found").

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/0073_request_origins.py backend/src/dewpoint/core/models/requests.py \
  backend/src/dewpoint/apps/admission.py backend/src/dewpoint/apps/dispatcher/tick.py \
  backend/src/dewpoint/apps/dispatcher/matching.py backend/tests/migrations/test_0073.py \
  backend/tests/apps/test_admission_origins.py backend/tests/apps/dispatcher/test_matching.py
git commit -m "feat(runs): a request names where it came from, migration 0073 (4e-1a)

The run a re-run repeats and the schedule or webhook endpoint a request came from, in plain ids on its row
(the runs design §4.3); null on every request before it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The runs list's filters and labels (B10)

**Spec:** §4.1 (typed answers), §4.2 (the list).

**Files:**
- Modify: `backend/src/dewpoint/core/runs/service.py` (`Listed`, `STATUSES`, `DRAFTS`, `list_items`),
  `backend/src/dewpoint/apps/api/routes/runs.py` (`ListedStatus`, `_item`, `_trigger`, `list_runs`),
  `backend/src/dewpoint/apps/api/responses.py` (`RunStatus`, `Source`, `RunErrorOut`, `RunRequestStateOut`,
  `ScheduleTimingOut`, `RunTriggerOut`, `RunItemOut`)
- Test: create `backend/tests/apps/api/test_runs_list.py`; modify `backend/tests/apps/api/test_simulations_api.py`

**Interfaces:**
- Consumes: Task 2's columns; `test_admission_origins.schedule`.
- Produces:
  - `service.list_items(s, *, kept_after, workflow_id=None, status=None, mode=None, draft="exclude", source=None,
    since=None, before=None, limit=50) -> list[Listed]`;
  - `Listed` gains `workflow_name`, `started_by`, `cancel_requested_at`, `rerun_of`, `schedule_cron`,
    `schedule_every_s`, `schedule_offset_s`, `schedule_time_zone`, `endpoint_name`;
  - `runs._trigger(source, rerun_of, named)` (Task 5 calls it with `service.Labels`);
  - `RunItemOut`, `RunErrorOut`, `RunRequestStateOut`, `RunTriggerOut`, `ScheduleTimingOut`, `RunStatus`, `Source`
    (Tasks 4–6 build on them).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_runs_list.py b/backend/tests/apps/api/test_runs_list.py
new file mode 100644
index 00000000..503e77af
--- /dev/null
+++ b/backend/tests/apps/api/test_runs_list.py
@@ -0,0 +1,189 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The runs list's filters and labels (editor 4e-1, B10; the runs design §4.2): by status, over a run's status or an
+unstarted request's (`waiting`, `didnt_start` grouping two each); by mode, draft simulations (left out by default),
+source and `since`, the cursor paging under them. Each item names its workflow, the email of the person who asked, a
+requested cancel, and where it came from: the schedule's timing, the endpoint's name, the run a re-run repeats."""
+
+import uuid
+from datetime import UTC, datetime
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import admission
+from dewpoint.apps.dispatcher import dispatch as dispatch_module
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.runs import service
+from tests.apps.api.helpers import member_client
+from tests.apps.dispatcher.inbound import endpoint
+from tests.apps.dispatcher.support import begin, workers
+from tests.apps.test_admission import TOKEN, admit, current, published
+from tests.apps.test_admission_drafts import simulate
+from tests.apps.test_admission_origins import schedule
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    async with owner_sessionmaker() as s:
+        version = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
+    return ctx, wf, version
+
+
+async def requested(api: Any, ctx: Any, wf: uuid.UUID, key: str, **request: Any) -> uuid.UUID:
+    """A request under `key`, as admission left it."""
+    return (await admit(api, ctx, wf, key=key, **request)).request.id  # type: ignore[no-any-return]
+
+
+async def moved(api: Any, owner: Any, dispatch: Any, settings: Any, ctx: Any, wf: uuid.UUID, key: str,
+                status: str) -> uuid.UUID:  # fmt: skip
+    """A request the dispatcher moved on, as it does: `starting`, `dead`, or `started` and its run `running`; or one
+    cancelled before it started."""
+    r = (await admit(api, ctx, wf, key=key)).request
+    if status == "cancelled":
+        async with owner() as s, s.begin():
+            await s.execute(text("update run_requests set status = 'cancelled', ended_at = now() where id = :i"),
+                            {"i": r.id})  # fmt: skip
+        return r.id  # type: ignore[no-any-return]
+    starting = await begin(dispatch, r, settings)
+    if status != "starting":
+        outcome = {"dead": "collision", "started": "started"}[status]
+        await dispatch_module.settle(dispatch, starting, dispatch_module.Outcome(outcome))
+    return r.id  # type: ignore[no-any-return]
+
+
+async def ran(api: Any, owner: Any, dispatch: Any, settings: Any, ctx: Any, wf: uuid.UUID, key: str,
+              status: str) -> uuid.UUID:  # fmt: skip
+    """A request that started a run, which is at `status`: ended as a run ends, its slot given back."""
+    request_id = await moved(api, owner, dispatch, settings, ctx, wf, key, "started")
+    if status != "running":
+        async with dispatch() as s, s.begin():
+            await tenant_scope(s, ctx.tenant_id)
+            await service.finish_run(s, request_id, status=status, ended_at=datetime.now(UTC))
+    return request_id
+
+
+async def listed(app: Any, owner: Any, settings: Any, ctx: Any, **params: Any) -> list[dict[str, Any]]:
+    viewer, _ = await member_client(app, owner, settings, ctx.tenant_id, "viewer")
+    answer = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params=params)
+    assert answer.status_code == 200, answer.text
+    return list(answer.json())
+
+
+async def test_each_status_filter_picks_its_runs_and_unstarted_requests(
+    app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf, _ = ready
+    await workers(owner_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():  # room for every run this test starts at once
+        await s.execute(text("insert into tenant_run_limits (tenant_id, max_concurrent) values (:t, 20)"),
+                        {"t": ctx.tenant_id})  # fmt: skip
+    made: dict[str, uuid.UUID] = {}
+    for status in ("succeeded", "failed", "deadline_exceeded", "cancelled", "running"):  # one slot held at a time
+        made[f"run {status}"] = await ran(api_sessionmaker, owner_sessionmaker, dispatch_sessionmaker, api_settings,
+                                          ctx, wf, f"x-{status}", status)  # fmt: skip
+    for status in ("dead", "starting", "cancelled"):
+        made[f"request {status}"] = await moved(api_sessionmaker, owner_sessionmaker, dispatch_sessionmaker,
+                                                api_settings, ctx, wf, f"r-{status}", status)  # fmt: skip
+    made["request queued"] = await requested(api_sessionmaker, ctx, wf, "r-queued")
+    made["request refused"] = await requested(api_sessionmaker, ctx, wf, "r-refused", source="schedule",
+                                              input={"token": 7})  # fmt: skip
+    expected = {
+        "waiting": {"request queued", "request starting"},
+        "running": {"run running"},
+        "succeeded": {"run succeeded"},
+        "failed": {"run failed"},
+        "deadline_exceeded": {"run deadline_exceeded"},
+        "cancelled": {"request cancelled", "run cancelled"},
+        "didnt_start": {"request dead", "request refused"},
+    }
+    for status, names in expected.items():
+        found = {i["id"] for i in await listed(app, owner_sessionmaker, api_settings, ctx, status=status)}
+        assert found == {str(made[n]) for n in names}, status
+    assert len(await listed(app, owner_sessionmaker, api_settings, ctx)) == len(made)
+
+
+async def test_mode_source_and_since_filter_and_the_cursor_pages_under_them(
+    app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf, _ = ready
+    live = [await requested(api_sessionmaker, ctx, wf, f"l{n}") for n in range(3)]
+    simulated = await requested(api_sessionmaker, ctx, wf, "s", mode="simulate")
+    rerun = await requested(api_sessionmaker, ctx, wf, "rr", source="rerun",
+                            rerun=admission.Rerun(of=live[0], input={"token": TOKEN}))  # fmt: skip
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update run_requests set queued_at = now() - interval '2 days' where id = :i"),
+                        {"i": live[0]})  # fmt: skip
+        since = (await s.execute(text("select now() - interval '1 day'"))).scalar()
+
+    def ids(items: list[dict[str, Any]]) -> set[str]:
+        return {i["id"] for i in items}
+
+    assert ids(await listed(app, owner_sessionmaker, api_settings, ctx, mode="simulate")) == {str(simulated)}
+    assert ids(await listed(app, owner_sessionmaker, api_settings, ctx, source="rerun")) == {str(rerun)}
+    recent = await listed(app, owner_sessionmaker, api_settings, ctx, since=since.isoformat())
+    assert ids(recent) == {str(live[1]), str(live[2]), str(simulated), str(rerun)}
+    first = await listed(app, owner_sessionmaker, api_settings, ctx, mode="live", source="manual", limit=2)
+    last = first[-1]
+    rest = await listed(app, owner_sessionmaker, api_settings, ctx, mode="live", source="manual", limit=2,
+                        before=last["queued_at"], before_id=last["id"])  # fmt: skip
+    assert [i["id"] for i in first + rest] == [str(i) for i in reversed(live)]
+
+
+async def test_draft_simulations_are_left_out_unless_asked_for(
+    app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf, _ = ready
+    published_run = await requested(api_sessionmaker, ctx, wf, "p")
+    draft = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN})).request.id
+
+    async def ids(**params: Any) -> list[str]:
+        return [i["id"] for i in await listed(app, owner_sessionmaker, api_settings, ctx, **params)]
+
+    assert await ids() == [str(published_run)]
+    assert await ids(draft="only") == [str(draft)]
+    assert await ids(draft="include") == [str(draft), str(published_run)]
+
+
+async def test_an_item_names_its_workflow_who_asked_a_requested_cancel_and_where_it_came_from(
+    app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf, _ = ready
+    by_hand = await requested(api_sessionmaker, ctx, wf, "h")
+    rerun = await requested(api_sessionmaker, ctx, wf, "r", source="rerun",
+                            rerun=admission.Rerun(of=by_hand, input={"token": TOKEN}))  # fmt: skip
+    schedule_id = await schedule(api_sessionmaker, ctx, wf)
+    ticked = await requested(api_sessionmaker, ctx, wf, "t", source="schedule",
+                             trigger_id=schedule_id)  # fmt: skip
+    endpoint_id = await endpoint(owner_sessionmaker, ctx.tenant_id, ctx.user.id)
+    hooked = await requested(api_sessionmaker, ctx, wf, "w", source="webhook",
+                             trigger_id=endpoint_id)  # fmt: skip
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update run_requests set cancel_requested_at = now() where id = :i"), {"i": by_hand})
+    items = {i["id"]: i for i in await listed(app, owner_sessionmaker, api_settings, ctx)}
+    assert {i["workflow_name"] for i in items.values()} == {"W"}
+    hand = items[str(by_hand)]
+    assert (hand["started_by"], hand["cancel_requested_at"] is not None) == (ctx.user.email, True)
+    assert hand["trigger"] == {"source": "manual", "schedule": None, "endpoint": None, "rerun_of": None}
+    assert items[str(rerun)]["trigger"]["rerun_of"] == str(by_hand)
+    assert items[str(ticked)]["started_by"] is None
+    assert items[str(ticked)]["trigger"]["schedule"] == {"cron": "0 9 * * *", "every_s": None, "offset_s": 0,
+                                                         "time_zone": "UTC"}  # fmt: skip
+    assert items[str(hooked)]["trigger"]["endpoint"] == "hooks"
+    async with owner_sessionmaker() as s, s.begin():  # a deleted schedule, and a request from before 0073
+        await s.execute(text("update schedules set deleted_at = now(), input = null where id = :i"), {"i": schedule_id})
+        await s.execute(text("update run_requests set trigger_id = null where id = :i"), {"i": hooked})
+    items = {i["id"]: i for i in await listed(app, owner_sessionmaker, api_settings, ctx)}
+    assert items[str(ticked)]["trigger"] == {"source": "schedule", "schedule": None, "endpoint": None, "rerun_of": None}
+    assert items[str(hooked)]["trigger"] == {"source": "webhook", "schedule": None, "endpoint": None, "rerun_of": None}
+
+
+@pytest.mark.parametrize("params", [{"status": "awaiting_approval"}, {"draft": "yes"}, {"source": "import"}])
+async def test_an_unknown_filter_value_is_refused(app, ready, owner_sessionmaker, api_settings, params) -> None:
+    ctx, _, _ = ready
+    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
+    assert (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params=params)).status_code == 422
diff --git a/backend/tests/apps/api/test_simulations_api.py b/backend/tests/apps/api/test_simulations_api.py
index 28c6bcb7..d09dfd9d 100644
--- a/backend/tests/apps/api/test_simulations_api.py
+++ b/backend/tests/apps/api/test_simulations_api.py
@@ -143,7 +143,8 @@ async def test_the_runs_api_shows_a_draft_runs_snapshot_target_and_each_steps_ef
     request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
                               values={"/steps/a/output/value": 5})).request  # fmt: skip
     viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
-    shown = {k: v for k, v in (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()[0].items()
+    listed = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params={"draft": "only"})  # left out by default
+    shown = {k: v for k, v in listed.json()[0].items()
              if k in ("id", "version_id", "draft_snapshot_id", "target_step_id")}  # fmt: skip
     assert shown == {"id": str(request.id), "version_id": None, "draft_snapshot_id": str(request.draft_snapshot_id),
                      "target_step_id": str(nid("b"))}  # fmt: skip
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/api/test_runs_list.py \
  tests/apps/api/test_runs_api.py \
  tests/apps/api/test_simulations_api.py
```

Expected: FAIL, 7 failed and 21 passed: the status filter answers every item ("AssertionError: waiting"), mode, source
and `since` are ignored, the draft simulation is listed by default, the three unknown values answer 200 ("assert 200 ==
422"), and an item has no `workflow_name` (`KeyError`). `test_simulations_api.py` passes at once: `draft=only` is
ignored, and today's list shows the draft simulation anyway.

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index f7559a09..3593313c 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -740,3 +740,67 @@ class SeedContractOut(_Answer):
     step_id: str
     refused: str | None
     entries: list[SeedEntryOut]
+
+
+RunStatus = Literal[
+    "queued", "starting", "running", "succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"
+]
+Source = Literal["manual", "rerun", "schedule", "webhook", "dev"]
+
+
+class RunErrorOut(_Answer):
+    code: str
+    message: str | None
+
+
+class RunRequestStateOut(_Answer):
+    """A run's request where it is (engine 2b spec §7.3): started, or why it isn't."""
+
+    status: Literal["queued", "starting", "started", "cancelled", "refused", "dead"]
+    source: Source
+    reason: str | None
+
+
+class ScheduleTimingOut(_Answer):
+    """A schedule's timing as it is now, which the UI words as the Triggers panel does (4c-3b)."""
+
+    cron: str | None
+    every_s: int | None
+    offset_s: int
+    time_zone: str
+
+
+class RunTriggerOut(_Answer):
+    """Where a run's request came from (editor 4e-1; the runs design §4.2): its source, and the schedule or webhook
+    endpoint, or the run a re-run repeats. Null where the request predates migration 0073, or the schedule or endpoint
+    was deleted."""
+
+    source: Source
+    schedule: ScheduleTimingOut | None
+    endpoint: str | None  # the webhook endpoint's name
+    rerun_of: str | None
+
+
+class RunItemOut(_Answer):
+    """An item of the runs list (engine 2b spec §7.7; editor 4e-1, B10): a top-level run, or a request that hasn't
+    started, as its request. `status` is the run's once its request started, else the request's."""
+
+    id: str
+    workflow_id: str
+    workflow_name: str | None
+    version_id: str | None
+    draft_snapshot_id: str | None  # a draft simulation's (B8): no version
+    target_step_id: str | None
+    mode: Literal["live", "simulate"]
+    status: RunStatus
+    queued_at: str | None
+    started_at: str | None
+    ended_at: str | None
+    error: RunErrorOut | None
+    iterations: int
+    kind: str
+    parent_run_id: str | None
+    request: RunRequestStateOut | None  # null for a run from before 2b-2, which had no request
+    started_by: str | None  # the email of the person who asked: by hand, or a re-run
+    cancel_requested_at: str | None
+    trigger: RunTriggerOut | None
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
index 4c5d71d5..93c55473 100644
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -6,10 +6,12 @@ A request that hasn't started is shown as its request, never as the row an attem
 
 import uuid
 from datetime import datetime
+from typing import Literal
 
 from fastapi import APIRouter, Depends, HTTPException, Query
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from dewpoint.apps.api.responses import RunItemOut
 from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.claims import service as claims
@@ -22,6 +24,8 @@ from dewpoint.core.retention import cutoff as retention
 from dewpoint.core.runs import service
 
 router = APIRouter(prefix="/api/v1", tags=["runs"])
+# The list's status filter (the runs design §4.2): `waiting` is queued or starting; `didnt_start`, refused or dead
+ListedStatus = Literal["waiting", "running", "succeeded", "failed", "deadline_exceeded", "cancelled", "didnt_start"]
 
 
 def _when(value: datetime | None) -> str | None:
@@ -53,9 +57,24 @@ def _item(i: service.Listed) -> dict[str, object]:
         "kind": i.kind,
         "parent_run_id": None,
         "request": {"status": i.request_status, "source": i.source, "reason": i.reason} if i.request_status else None,
+        "workflow_name": i.workflow_name,
+        "started_by": i.started_by,
+        "cancel_requested_at": _when(i.cancel_requested_at),
+        "trigger": _trigger(i),
     }
 
 
+def _trigger(i: service.Listed) -> dict[str, object] | None:
+    """Where the request came from (the runs design §4.2): null for a run from before 2b-2, which had no request."""
+    if i.source is None:
+        return None
+    timing = None
+    if i.schedule_time_zone is not None:  # the schedule, as it is now; a deleted one's left out
+        timing = {"cron": i.schedule_cron, "every_s": i.schedule_every_s, "offset_s": i.schedule_offset_s,
+                  "time_zone": i.schedule_time_zone}  # fmt: skip
+    return {"source": i.source, "schedule": timing, "endpoint": i.endpoint_name, "rerun_of": _id(i.rerun_of)}
+
+
 def _unstarted(r: RunRequest) -> dict[str, object]:
     """A request that hasn't started, as the list shows it: its own status, no run yet."""
     return {
@@ -122,9 +141,14 @@ def _step(r: RunStep) -> dict[str, object]:
     }
 
 
-@router.get("/t/{tenant_id}/runs")
+@router.get("/t/{tenant_id}/runs", response_model=list[RunItemOut])
 async def list_runs(
     workflow_id: uuid.UUID | None = None,
+    status: ListedStatus | None = None,
+    mode: Literal["live", "simulate"] | None = None,
+    draft: Literal["exclude", "only", "include"] = "exclude",
+    source: Literal["manual", "rerun", "schedule", "webhook", "dev"] | None = None,
+    since: datetime | None = None,
     before: datetime | None = None,
     before_id: uuid.UUID | None = None,
     limit: int = Query(50, ge=1, le=200),
@@ -133,12 +157,14 @@ async def list_runs(
 ) -> list[dict[str, object]]:
     """Requests and runs, newest first by `(queued_at, id)`. The next page: `before` and `before_id`, the last item's
     `queued_at` and `id`, always together: items can be queued in the same instant, so the time alone would skip
-    some."""
+    some. Filtered (the runs design §4.2) by workflow, status (`waiting`: queued or starting; `didnt_start`: refused
+    or dead), mode, draft simulations (left out unless `draft` is `only` or `include`), source, and `since`."""
     if (before is None) != (before_id is None):
         raise HTTPException(422, detail={"error": "invalid_cursor", "message": "Give before and before_id together."})
     cursor = (before, before_id) if before is not None and before_id is not None else None
     at = await retention.cutoff(db, ctx.tenant_id)
-    items = await service.list_items(db, kept_after=at, workflow_id=workflow_id, before=cursor, limit=limit)
+    items = await service.list_items(db, kept_after=at, workflow_id=workflow_id, status=status, mode=mode,
+                                     draft=draft, source=source, since=since, before=cursor, limit=limit)  # fmt: skip
     return [_item(i) for i in items]
 
 
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
index 55f8e1a2..75aed0b3 100644
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -11,12 +11,16 @@ from dataclasses import dataclass
 from datetime import datetime
 from typing import Any, Protocol
 
-from sqlalchemy import delete, func, literal, null, or_, select, text, tuple_, union_all, update
+from sqlalchemy import and_, delete, func, literal, null, or_, select, text, tuple_, union_all, update
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
+from dewpoint.core.models.identity import User
+from dewpoint.core.models.ingress import WebhookEndpoint
 from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.runs import ExecutionEvidence, Run, RunStep
+from dewpoint.core.models.schedules import Schedule
+from dewpoint.core.models.workflows import Workflow
 from dewpoint.core.retention.cutoff import Cutoff, kept
 
 MESSAGE_LIMIT = 500
@@ -390,6 +394,31 @@ class Listed:
     request_status: str | None
     source: str | None
     reason: str | None
+    # Who and where from (editor 4e-1; the runs design §4.2): the workflow's name, the email of the person who asked,
+    # whether a cancel was requested, the run a re-run repeats, and the schedule (its timing) or webhook endpoint (its
+    # name) it came from, null when it was deleted or the request predates migration 0073.
+    workflow_name: str | None = None
+    started_by: str | None = None
+    cancel_requested_at: datetime | None = None
+    rerun_of: uuid.UUID | None = None
+    schedule_cron: str | None = None
+    schedule_every_s: int | None = None
+    schedule_offset_s: int | None = None
+    schedule_time_zone: str | None = None
+    endpoint_name: str | None = None
+
+
+# The list's status filter (the runs design §4.2): one value, over a run's status or an unstarted request's
+STATUSES: dict[str, tuple[str, ...]] = {
+    "waiting": ("queued", "starting"),
+    "running": ("running",),
+    "succeeded": ("succeeded",),
+    "failed": ("failed",),
+    "deadline_exceeded": ("deadline_exceeded",),
+    "cancelled": ("cancelled",),
+    "didnt_start": ("refused", "dead"),
+}
+DRAFTS = ("exclude", "only", "include")
 
 
 async def list_items(
@@ -397,18 +426,29 @@ async def list_items(
     *,
     kept_after: Cutoff,
     workflow_id: uuid.UUID | None = None,
+    status: str | None = None,
+    mode: str | None = None,
+    draft: str = "exclude",
+    source: str | None = None,
+    since: datetime | None = None,
     before: tuple[datetime, uuid.UUID] | None = None,
     limit: int = 50,
 ) -> list[Listed]:
     """Requests and runs together, newest first by `(queued_at, id)`; the next page starts after the last item of this
     one. A request's pre-created row is never shown until its request has started (§7.3): the request is. Nothing past
-    the retention cutoff `kept_after` is (§10.1): every run listed is a root, so its own end is its tree's."""
+    the retention cutoff `kept_after` is (§10.1): every run listed is a root, so its own end is its tree's.
+
+    Filtered (the runs design §4.2) by workflow, by `status` (a key of `STATUSES`), `mode`, draft simulations (`draft`:
+    left out, alone, or with the rest), `source`, and `since` (queued at or after). The page is read first, then
+    labelled: who asked, the workflow's name, the schedule or endpoint, in one join over the page."""
     runs = (
         select(
             Run.id, Run.workflow_id, Run.workflow_version_id.label("version_id"), Run.draft_snapshot_id,
             Run.target_step_id, Run.mode, Run.status, Run.queued_at,
             Run.started_at, Run.ended_at, Run.error_code, Run.error_message, Run.iterations, Run.kind,
             RunRequest.status.label("request_status"), RunRequest.source, RunRequest.reason,
+            func.coalesce(RunRequest.actor_id, Run.started_by).label("actor_id"), RunRequest.cancel_requested_at,
+            RunRequest.rerun_of, RunRequest.trigger_id,
         )
         .outerjoin(RunRequest, RunRequest.id == Run.id)
         .where(Run.parent_run_id.is_(None), or_(RunRequest.id.is_(None), RunRequest.status == "started"),
@@ -420,6 +460,7 @@ async def list_items(
         RunRequest.status, RunRequest.queued_at, null().label("started_at"), RunRequest.ended_at,
         null().label("error_code"), null().label("error_message"), literal(0).label("iterations"),
         literal("run").label("kind"), RunRequest.status.label("request_status"), RunRequest.source, RunRequest.reason,
+        RunRequest.actor_id, RunRequest.cancel_requested_at, RunRequest.rerun_of, RunRequest.trigger_id,
     ).where(RunRequest.status != "started", kept(RunRequest.ended_at, kept_after))  # fmt: skip
     if workflow_id is not None:
         runs, requests = (
@@ -430,7 +471,34 @@ async def list_items(
     q = select(both).order_by(both.c.queued_at.desc(), both.c.id.desc()).limit(limit)
     if before is not None:
         q = q.where(tuple_(both.c.queued_at, both.c.id) < tuple_(*before))
-    return [Listed(**row._mapping) for row in await s.execute(q)]
+    if status is not None:
+        q = q.where(both.c.status.in_(STATUSES[status]))
+    if mode is not None:
+        q = q.where(both.c.mode == mode)
+    if draft != "include":
+        q = q.where(both.c.draft_snapshot_id.is_(None) if draft == "exclude" else both.c.draft_snapshot_id.is_not(None))
+    if source is not None:
+        q = q.where(both.c.source == source)
+    if since is not None:
+        q = q.where(both.c.queued_at >= since)
+    page = q.subquery()
+    labelled = (
+        select(
+            *(c for c in page.c if c.name not in ("actor_id", "trigger_id")),
+            Workflow.name.label("workflow_name"), User.email.label("started_by"),
+            Schedule.cron.label("schedule_cron"), Schedule.every_s.label("schedule_every_s"),
+            Schedule.offset_s.label("schedule_offset_s"), Schedule.time_zone.label("schedule_time_zone"),
+            WebhookEndpoint.name.label("endpoint_name"),
+        )
+        .outerjoin(Workflow, Workflow.id == page.c.workflow_id)
+        .outerjoin(User, and_(User.id == page.c.actor_id,  # a person asked: by hand, a re-run, or a run before 2b-2
+                              or_(page.c.source.is_(None), page.c.source.in_(("manual", "rerun")))))
+        .outerjoin(Schedule, and_(page.c.source == "schedule", Schedule.id == page.c.trigger_id,
+                                  Schedule.deleted_at.is_(None)))
+        .outerjoin(WebhookEndpoint, and_(page.c.source == "webhook", WebhookEndpoint.id == page.c.trigger_id))
+        .order_by(page.c.queued_at.desc(), page.c.id.desc())
+    )  # fmt: skip
+    return [Listed(**row._mapping) for row in await s.execute(labelled)]
 
 
 async def children(s: AsyncSession, run_id: uuid.UUID) -> list[Run]:
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 28 passed.

- [ ] **Step 5: Run the static checks**

Run:

```bash
cd backend \
  && uv run ruff check src tests migrations \
  && uv run ruff format --check src tests migrations \
  && uv run mypy src
```

Expected: silent.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/core/runs/service.py backend/src/dewpoint/apps/api/routes/runs.py \
  backend/src/dewpoint/apps/api/responses.py backend/tests/apps/api/test_runs_list.py \
  backend/tests/apps/api/test_simulations_api.py
git commit -m "feat(api): the runs list's filters and labels (B10, 4e-1a)

Filtered by status (waiting and didnt_start grouping two), mode, draft simulations (left out by default),
source and since; each item names its workflow, who asked, a requested cancel and where it came from. Typed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: The milestone**

Append `### 4e-1a, milestone 1 (<date>)` to the ledger. For each of Tasks 1–3, record its commit and its red and
green results as they ran. Add any mid-slice ruling from M103 and "Nothing pushed". Commit it as
`docs(editor-4): 4e-1a milestone 1`, with the trailer. Then stop for the owner's review.

---

# Milestone 2 — A run's reads

### Task 4: A run's steps, for every run

**Spec:** §4.4 (the summary, instances, attempts, origins), §6.

**Files:**
- Modify: `backend/src/dewpoint/apps/step_summary.py` (`OUTCOMES_ABI`, `ATTEMPTS`, `origin`, `Summarized.outcomes`,
  `summarize`, `attempts`, `children`), `backend/src/dewpoint/core/runs/service.py` (`graph_of`),
  `backend/src/dewpoint/apps/api/routes/runs.py` (`_step`'s child, `_ran`, `_nodes`, three routes),
  `backend/src/dewpoint/apps/api/responses.py` (`RunStepOut`, `RunStepSummaryOut`, `RunStepsOut`, `RunInstancesOut`,
  `RunAttemptsOut`)
- Test: create `backend/tests/apps/api/test_run_steps.py`, `backend/tests/apps/test_step_summary_cost.py`; modify
  `backend/tests/apps/test_step_summary.py`

**Interfaces:**
- Consumes: Task 3's `RunErrorOut`; 4d-1b's `step_summary.instances`, `_finals`; `test_simulation_steps.row`,
  `ended`, `LOOPED`.
- Produces:
  - `step_summary.origin(type_ref, statuses, outcomes=None, *, live=False, ended, error_code, recorded=True) -> str |
  None`;
  - `step_summary.summarize(s, run_id, nodes, *, ended, error_code, live=False, recorded=True)`;
  - `step_summary.attempts(s, run_id, step_id, iteration_key) -> list[RunStep]`;
  - `step_summary.children(s, run_id, instances) -> dict[tuple[uuid.UUID, str], uuid.UUID]`;
  - `step_summary.OUTCOMES_ABI = 9`, `step_summary.ATTEMPTS = 20`;
  - `service.graph_of(s, version_id, snapshot_id) -> tuple[dict | None, int | None]` (Task 5 reads its ABI);
  - `runs._ran(db, ctx, run_id) -> tuple[Run | None, Run | RunRequest]` (Task 6 calls it);
  - routes `GET /t/{tenant}/runs/{run_id}/steps`, `…/steps/{step_id}/instances`, `…/steps/{step_id}/attempts`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_run_steps.py b/backend/tests/apps/api/test_run_steps.py
new file mode 100644
index 00000000..e3e5c1ca
--- /dev/null
+++ b/backend/tests/apps/api/test_run_steps.py
@@ -0,0 +1,176 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A run's steps, for every run (editor 4e-1; the runs design §4.4), `run.view`: the summary per step of the graph it
+ran, in run order, with a live run's origins (`may_have_been_sent` before `sent`; nothing for a control step, or a
+plugin step that sent nothing) and `not_recorded` where its graph's engine predates B4b; a step's instances, paged,
+each naming the sub-run it started; one instance's attempts, first to last, at most a retry policy's most."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import step_summary
+from dewpoint.apps.dispatcher import dispatch as dispatch_module
+from tests.apps.api.test_run_requests_api import as_role, keyed_app
+from tests.apps.api.test_simulation_steps import LOOPED, ended, row
+from tests.apps.dispatcher.support import begin, workers
+from tests.apps.test_admission import admit, current, published
+from tests.apps.test_admission_drafts import drafted, simulate
+from tests.support.graphs import nid
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
+
+
+def steps(ctx: Any, run_id: uuid.UUID, step: str | None = None, read: str = "instances") -> str:
+    base = f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}/steps"
+    return base if step is None else f"{base}/{nid(step)}/{read}"
+
+
+async def started(owner: Any, api: Any, admin: Any, dispatch: Any, settings: Any, mode: str = "live") -> Any:
+    """A published LOOPED run in `mode`, started, still running, with no step rows yet."""
+    await current(dispatch)
+    ctx, wf = await published(owner, api, admin, settings, LOOPED)
+    request = (await admit(api, ctx, wf, mode=mode, input={})).request
+    await workers(owner)
+    starting = await begin(dispatch, request, settings)
+    assert await dispatch_module.settle(dispatch, starting, dispatch_module.Outcome("started")) == "started"
+    return ctx, request.id
+
+
+@pytest.fixture
+async def live(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    return await started(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings)
+
+
+async def origins(client: Any, ctx: Any, run_id: uuid.UUID) -> dict[str, Any]:
+    answer = await client.get(steps(ctx, run_id))
+    assert answer.status_code == 200, answer.text
+    return {s["key"]: s["origin"] for s in answer.json()["steps"]}
+
+
+async def test_a_live_runs_origins_say_what_was_sent_and_nothing_of_control_steps(
+    keyed_app, live, owner_sessionmaker, api_settings
+) -> None:
+    ctx, run_id = live
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    assert set((await origins(viewer, ctx, run_id)).values()) == {"not_reached_yet"}
+    await row(owner_sessionmaker, ctx, run_id, "l", "", 1, "succeeded", at=1)
+    await row(owner_sessionmaker, ctx, run_id, "c", "l:0", 1, "succeeded", at=2, port="true")
+    await row(owner_sessionmaker, ctx, run_id, "x", "l:0", 1, "failed", at=3)  # it sent nothing
+    await row(owner_sessionmaker, ctx, run_id, "x", "l:0", 2, "succeeded", at=4, outcome="applied")
+    await row(owner_sessionmaker, ctx, run_id, "d", "", 1, "succeeded", at=5)  # waited: a live run's timer
+    await ended(owner_sessionmaker, run_id)
+    assert await origins(viewer, ctx, run_id) == {"l": None, "c": None, "x": "sent", "d": None, "t": "didnt_run"}
+    await row(owner_sessionmaker, ctx, run_id, "x", "l:1", 1, "cancelled", at=6, outcome="outcome_unknown")
+    assert (await origins(viewer, ctx, run_id))["x"] == "may_have_been_sent"  # whatever became of the others
+
+
+async def test_a_plugin_step_that_sent_nothing_has_no_origin(keyed_app, live, owner_sessionmaker, api_settings) -> None:
+    ctx, run_id = live
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    await row(owner_sessionmaker, ctx, run_id, "x", "l:0", 1, "failed", at=3)
+    await ended(owner_sessionmaker, run_id, "failed", "boom")
+    assert (await origins(viewer, ctx, run_id))["x"] is None
+
+
+async def test_a_simulated_runs_origins_are_the_simulations(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, run_id = await started(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker,
+                                api_settings, mode="simulate")  # fmt: skip
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    await row(owner_sessionmaker, ctx, run_id, "x", "l:0", 1, "succeeded", at=3, outcome="simulated")
+    await row(owner_sessionmaker, ctx, run_id, "d", "", 1, "succeeded", at=5, outcome="simulated")
+    await ended(owner_sessionmaker, run_id)
+    found = await origins(viewer, ctx, run_id)
+    assert (found["x"], found["d"], found["t"]) == ("fixture_not_sent", "evaluated_not_waited", "didnt_run")
+
+
+async def test_a_step_with_no_row_is_not_recorded_when_its_graph_predates_b4b(
+    keyed_app, live, owner_sessionmaker, api_settings, monkeypatch
+) -> None:
+    ctx, run_id = live
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    await row(owner_sessionmaker, ctx, run_id, "l", "", 1, "succeeded", at=1)
+    await ended(owner_sessionmaker, run_id)
+    monkeypatch.setattr(step_summary, "OUTCOMES_ABI", step_summary.OUTCOMES_ABI + 1)  # its graph's ABI, now older
+    assert (await origins(viewer, ctx, run_id))["t"] == "not_recorded"
+    monkeypatch.undo()
+    assert (await origins(viewer, ctx, run_id))["t"] == "didnt_run"
+
+
+async def sub_run(owner: Any, parent: uuid.UUID, step: str, iteration: str) -> uuid.UUID:
+    """A sub-run the parent's step instance started, as the worker writes one."""
+    child = uuid.uuid4()
+    async with owner() as s, s.begin():
+        await s.execute(text(
+            "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, started_at, "
+            "ended_at, kind, parent_run_id, root_run_id, parent_step_id, parent_iteration_key) "
+            "select :c, tenant_id, workflow_id, workflow_version_id, mode, 'succeeded', queued_at, started_at, now(), "
+            "'subflow', id, root_run_id, :s, :k from runs where id = :p"
+        ), {"c": child, "p": parent, "s": nid(step), "k": iteration})  # fmt: skip
+    return child
+
+
+async def test_a_steps_instances_are_paged_each_naming_the_sub_run_it_started(
+    keyed_app, live, owner_sessionmaker, api_settings
+) -> None:
+    ctx, run_id = live
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    for i in range(5):
+        await row(owner_sessionmaker, ctx, run_id, "x", f"l:{i}", 1, "succeeded", at=3, outcome="applied")
+    child = await sub_run(owner_sessionmaker, run_id, "x", "l:3")
+    first = (await viewer.get(steps(ctx, run_id, "x"), params={"limit": 2})).json()
+    assert first["total"] == 5 and [i["iteration_key"] for i in first["items"]] == ["l:0", "l:1"]
+    page = (await viewer.get(steps(ctx, run_id, "x"), params={"offset": 2, "limit": 2})).json()
+    assert [(i["iteration_key"], i["child_run_id"]) for i in page["items"]] == [("l:2", None), ("l:3", str(child))]
+    assert (await viewer.get(steps(ctx, run_id, "nope"))).status_code == 404
+
+
+async def test_one_instances_attempts_come_first_to_last_at_most_a_retry_policys_most(
+    keyed_app, live, owner_sessionmaker, api_settings
+) -> None:
+    ctx, run_id = live
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    for attempt in range(1, step_summary.ATTEMPTS + 2):
+        await row(owner_sessionmaker, ctx, run_id, "x", "l:0", attempt, "failed", at=attempt)
+    await row(owner_sessionmaker, ctx, run_id, "d", "", 1, "succeeded", at=1)
+    answer = (await viewer.get(steps(ctx, run_id, "x", "attempts"), params={"iteration": "l:0"})).json()
+    assert [a["attempt"] for a in answer["items"]] == list(range(1, step_summary.ATTEMPTS + 1))
+    outside = (await viewer.get(steps(ctx, run_id, "d", "attempts"))).json()  # outside a loop: no iteration
+    assert [(a["iteration_key"], a["attempt"]) for a in outside["items"]] == [("", 1)]
+
+
+async def test_a_request_that_hasnt_started_has_steps_that_havent_run(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    await current(dispatch_sessionmaker)
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, LOOPED)
+    request = (await admit(api_sessionmaker, ctx, wf, input={})).request
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    assert set((await origins(viewer, ctx, request.id)).values()) == {"not_reached_yet"}
+    assert (await viewer.get(steps(ctx, request.id, "x"))).json() == {"total": 0, "items": []}
+
+
+async def test_a_draft_simulation_reads_the_same_through_the_runs_route(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    await current(dispatch_sessionmaker)
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOPED)
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    through_runs = (await viewer.get(steps(ctx, request.id))).json()
+    through_drafts = (await viewer.get(
+        f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/simulations/{request.id}/steps")).json()  # fmt: skip
+    assert through_runs == through_drafts
+
+
+async def test_another_tenants_run_isnt_found(keyed_app, live, owner_sessionmaker, api_sessionmaker, api_settings,
+                                              admin_sessionmaker) -> None:  # fmt: skip
+    _, run_id = live
+    other, _ = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, other, "viewer")
+    for path in (steps(other, run_id), steps(other, run_id, "x"), steps(other, run_id, "x", "attempts")):
+        assert (await viewer.get(path)).status_code == 404
diff --git a/backend/tests/apps/test_step_summary.py b/backend/tests/apps/test_step_summary.py
index c0708b6d..56b12bf0 100644
--- a/backend/tests/apps/test_step_summary.py
+++ b/backend/tests/apps/test_step_summary.py
@@ -34,3 +34,28 @@ def test_a_steps_origin_comes_from_its_instances_or_from_where_the_run_is(
     type_ref: str, statuses: dict[str, int], ended: bool, error_code: str | None, expected: str
 ) -> None:
     assert origin(type_ref, statuses, ended=ended, error_code=error_code) == expected
+
+
+@pytest.mark.parametrize(
+    ("type_ref", "statuses", "outcomes", "expected"),
+    [
+        (ECHO, {"succeeded": 1}, {"applied": 1}, "sent"),  # a live run (the runs design §4.4): its request was sent
+        (ECHO, {"succeeded": 1, "failed": 2}, {"applied": 1}, "sent"),
+        (ECHO, {"failed": 1}, {}, None),  # it sent nothing, or the service refused it: nothing to say
+        (ECHO, {"succeeded": 1, "cancelled": 1}, {"applied": 1, "outcome_unknown": 1}, "may_have_been_sent"),
+        (ECHO, {"cancelled": 1}, {"outcome_unknown": 1}, "may_have_been_sent"),  # whatever became of it
+        (IF, {"succeeded": 3}, {}, None),  # a control step's: nothing to say
+        (DELAY, {"succeeded": 1}, {}, None),  # waited, live
+        (ECHO, {"skipped": 3}, {}, "skipped"),
+        (ECHO, {}, {}, "didnt_run"),
+    ],
+)
+def test_a_live_steps_origin_says_what_was_sent(
+    type_ref: str, statuses: dict[str, int], outcomes: dict[str, int], expected: str | None
+) -> None:
+    assert origin(type_ref, statuses, outcomes, live=True, ended=True, error_code=None) == expected
+
+
+def test_a_step_without_a_row_is_not_recorded_when_its_graph_predates_b4b() -> None:
+    assert origin(ECHO, {}, ended=True, error_code=None, recorded=False) == "not_recorded"
+    assert origin(ECHO, {}, ended=False, error_code=None, recorded=False) == "not_reached_yet"
diff --git a/backend/tests/apps/test_step_summary_cost.py b/backend/tests/apps/test_step_summary_cost.py
new file mode 100644
index 00000000..60150605
--- /dev/null
+++ b/backend/tests/apps/test_step_summary_cost.py
@@ -0,0 +1,57 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The summary a run's page polls costs the same few statements whatever the run's size (the runs design §4.4): a run
+of 100,000 instances is summarized in three, its counts grouped by the database, never read row by row."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import event, text
+from sqlalchemy.engine import Engine
+
+from dewpoint.apps import step_summary
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.runs import service
+from tests.support.graphs import nid
+from tests.support.workflows import seed_workflow
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+INSTANCES = 100_000
+NODES = [{"id": str(nid("l")), "key": "l", "type": "flow.loop@1"},
+         {"id": str(nid("x")), "key": "x", "type": "testkit.echo@1"}]  # fmt: skip
+
+
+async def test_a_run_of_100000_instances_is_summarized_in_three_statements(
+    owner_sessionmaker, dispatch_sessionmaker, api_sessionmaker
+) -> None:
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    run_id = uuid.uuid4()
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        await service.insert_run(s, run_id=run_id, tenant_id=tenant, workflow_id=wf, version_id=version, mode="live")
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text(
+            "insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, started_at, "
+            "ended_at, outcome) select :t, :r, :x, 'l:' || g, 1, 'x', 'succeeded', now(), now(), 'applied' "
+            "from generate_series(0, :n - 1) g"
+        ), {"t": tenant, "r": run_id, "x": nid("x"), "n": INSTANCES})  # fmt: skip
+        await s.execute(text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, "
+                             "status, started_at, ended_at) "
+                             "values (:t, :r, :l, '', 1, 'l', 'succeeded', now(), now())"),
+                        {"t": tenant, "r": run_id, "l": nid("l")})  # fmt: skip
+    seen: list[str] = []
+
+    def on(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
+        if "run_steps" in statement:
+            seen.append(statement)
+
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        event.listen(Engine, "before_cursor_execute", on)
+        try:
+            summarized = await step_summary.summarize(s, run_id, NODES, ended=True, error_code=None, live=True)
+        finally:
+            event.remove(Engine, "before_cursor_execute", on)
+    counted = {x.key: (x.instances, x.origin, x.final is not None) for x in summarized}
+    assert counted == {"l": (1, None, True), "x": (INSTANCES, "sent", False)}
+    assert len(seen) == 3  # the counts, the first starts, the single instances' final attempts
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/api/test_run_steps.py \
  tests/apps/test_step_summary.py \
  tests/apps/test_step_summary_cost.py \
  tests/apps/api/test_simulation_steps.py
```

Expected: FAIL, 19 failed and 23 passed: `origin()` takes no `live` or `recorded` (`TypeError`), `step_summary` has no
`OUTCOMES_ABI` or `ATTEMPTS`, `summarize` takes no `live`, and the three routes don't exist (404 `not_found`, `KeyError:
'total'`). "another tenant's run isn't found" passes at once: an unknown route is a 404 too; it pins the tenancy once
the routes exist. The simulation step tests pass.

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 3593313c..03bf91d6 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -804,3 +804,64 @@ class RunItemOut(_Answer):
     started_by: str | None  # the email of the person who asked: by hand, or a re-run
     cancel_requested_at: str | None
     trigger: RunTriggerOut | None
+
+
+class RunStepOut(_Answer):
+    """One attempt of a step instance (engine spec §8; B4b): where it ran (its iteration), how it ended, its previews
+    (redacted and cut as the projection stores them: `[redacted]`, `[truncated]`), its error, its side effect's outcome,
+    a control step's port or assignments, and the sub-run it started, when it did."""
+
+    step_id: str
+    key: str
+    iteration_key: str
+    attempt: int
+    status: Literal["running", "succeeded", "failed", "cancelled", "skipped", "not_started"]
+    started_at: str | None
+    ended_at: str | None
+    input: Any
+    output: Any
+    error: RunErrorOut | None
+    outcome: Literal["applied", "simulated", "outcome_unknown"] | None
+    cel_mode: str | None
+    effect: Any
+    child_run_id: str | None = None
+
+
+class RunStepSummaryOut(_Answer):
+    """A step of the graph a run ran (the runs design §4.4): its instances' final attempts counted by status and by the
+    port they took, a single instance's final attempt, and where its data came from: in a live run, `sent` or
+    `may_have_been_sent` for a plugin step's request, null when there's nothing to say."""
+
+    step_id: str
+    key: str
+    type: str
+    origin: Literal[
+        "sent", "may_have_been_sent", "evaluated", "evaluated_not_waited", "fixture_not_sent", "skipped",
+        "not_started", "cancelled", "didnt_run", "not_recorded", "not_reached_yet",
+    ] | None  # fmt: skip
+    instances: int
+    statuses: dict[str, int]
+    ports: dict[str, int]
+    final: RunStepOut | None
+
+
+class RunStepsOut(_Answer):
+    """A run's steps in run order (§4.4), and what the values a person gave were: the workflow's input, or a step
+    test's seeds. A step test lists its target alone."""
+
+    given: Literal["input", "seeded"]
+    steps: list[RunStepSummaryOut]
+
+
+class RunInstancesOut(_Answer):
+    """A step's instances in a run, one per iteration, each its final attempt, in iteration order: a page, and their
+    total."""
+
+    total: int
+    items: list[RunStepOut]
+
+
+class RunAttemptsOut(_Answer):
+    """One step instance's attempts, first to last."""
+
+    items: list[RunStepOut]
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
index 93c55473..f00a7c5d 100644
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -6,12 +6,13 @@ A request that hasn't started is shown as its request, never as the row an attem
 
 import uuid
 from datetime import datetime
-from typing import Literal
+from typing import Any, Literal
 
 from fastapi import APIRouter, Depends, HTTPException, Query
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from dewpoint.apps.api.responses import RunItemOut
+from dewpoint.apps import step_summary
+from dewpoint.apps.api.responses import RunAttemptsOut, RunInstancesOut, RunItemOut, RunStepsOut
 from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.claims import service as claims
@@ -123,7 +124,8 @@ def _child(r: Run) -> dict[str, object]:
     }
 
 
-def _step(r: RunStep) -> dict[str, object]:
+def _step(r: RunStep, child: uuid.UUID | None = None) -> dict[str, object]:
+    """One attempt of a step instance, and the sub-run it started (the runs design §4.4)."""
     return {
         "step_id": str(r.step_id),
         "key": r.node_key,
@@ -138,6 +140,7 @@ def _step(r: RunStep) -> dict[str, object]:
         "outcome": r.outcome,
         "cel_mode": r.cel_mode,
         "effect": r.effect_preview,  # a control step's port or assignments (4d-1a), masked as its previews are
+        "child_run_id": _id(child),
     }
 
 
@@ -200,3 +203,100 @@ async def get_run(
         "children": [_child(c) for c in await service.children(db, run.id)],
         "csv": csv,
     }
+
+
+async def _ran(db: AsyncSession, ctx: TenantContext, run_id: uuid.UUID) -> tuple[Run | None, Run | RunRequest]:
+    """A run within retention, or a request that hasn't started (no run yet); and the one of them that says what it
+    runs. Else 404."""
+    at = await retention.cutoff(db, ctx.tenant_id)
+    request = await db.get(RunRequest, run_id)  # row-level security: the caller's tenant's only
+    if request is not None and not await retention.request_kept(db, at, request):
+        raise HTTPException(404, detail={"error": "not_found"})
+    if request is not None and request.status != "started":
+        return None, request
+    run = await service.get_run(db, run_id)
+    if run is None or run.tenant_id != ctx.tenant_id or not await retention.run_kept(db, at, run):
+        raise HTTPException(404, detail={"error": "not_found"})
+    return run, run
+
+
+async def _nodes(db: AsyncSession, of: Run | RunRequest) -> tuple[list[dict[str, Any]], bool]:
+    """The steps a run ran (its graph's, or a step test's target alone), and whether its graph's engine records every
+    step instance's end (B4b)."""
+    graph, abi = await service.graph_of(db, of.workflow_version_id, of.draft_snapshot_id)
+    nodes: list[dict[str, Any]] = [] if graph is None else graph["nodes"]
+    target = of.target_step_id
+    recorded = abi is None or abi >= step_summary.OUTCOMES_ABI
+    return [n for n in nodes if target is None or n["id"] == str(target)], recorded
+
+
+@router.get("/t/{tenant_id}/runs/{run_id}/steps", response_model=RunStepsOut)
+async def run_steps(
+    run_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """A run's steps in run order, summarized (the runs design §4.4): the tags the UI shows come from here, never from
+    a partial page of instances. A request that hasn't started has steps that haven't run."""
+    run, of = await _ran(db, ctx, run_id)
+    nodes, recorded = await _nodes(db, of)
+    ended = run.status != "running" if run is not None else of.ended_at is not None
+    summarized = await step_summary.summarize(
+        db, None if run is None else run.id, nodes, ended=ended, error_code=None if run is None else run.error_code,
+        live=of.mode == "live", recorded=recorded,
+    )  # fmt: skip
+    singles = [(x.step_id, x.final.iteration_key) for x in summarized if x.final is not None]
+    started = await step_summary.children(db, run.id, singles) if run is not None else {}
+    return {
+        "given": "input" if of.target_step_id is None else "seeded",
+        "steps": [
+            {"step_id": str(x.step_id), "key": x.key, "type": x.type, "origin": x.origin, "instances": x.instances,
+             "statuses": x.statuses, "ports": x.ports,
+             "final": None if x.final is None else _step(x.final, started.get((x.step_id, x.final.iteration_key)))}
+            for x in summarized
+        ],
+    }  # fmt: skip
+
+
+@router.get("/t/{tenant_id}/runs/{run_id}/steps/{step_id}/instances", response_model=RunInstancesOut)
+async def step_instances(
+    run_id: uuid.UUID,
+    step_id: uuid.UUID,
+    within: str | None = None,
+    offset: int = Query(0, ge=0),
+    limit: int = Query(20, ge=1, le=100),
+    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """A step's instances in a run, one per iteration (its final attempt), in iteration order, paged from `offset`;
+    with `within`, only that iteration's (itself and every iteration nested in it). Each names the sub-run it
+    started."""
+    run, of = await _ran(db, ctx, run_id)
+    nodes, _ = await _nodes(db, of)
+    if str(step_id) not in {n["id"] for n in nodes}:
+        raise HTTPException(404, detail={"error": "not_found"})
+    if run is None:
+        return {"total": 0, "items": []}
+    total, rows = await step_summary.instances(db, run.id, step_id, within=within, offset=offset, limit=limit)
+    started = await step_summary.children(db, run.id, [(r.step_id, r.iteration_key) for r in rows])
+    return {"total": total, "items": [_step(r, started.get((r.step_id, r.iteration_key))) for r in rows]}
+
+
+@router.get("/t/{tenant_id}/runs/{run_id}/steps/{step_id}/attempts", response_model=RunAttemptsOut)
+async def step_attempts(
+    run_id: uuid.UUID,
+    step_id: uuid.UUID,
+    iteration: str = "",
+    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """One step instance's attempts, first to last: `iteration` is its iteration key (empty outside a loop)."""
+    run, of = await _ran(db, ctx, run_id)
+    nodes, _ = await _nodes(db, of)
+    if str(step_id) not in {n["id"] for n in nodes}:
+        raise HTTPException(404, detail={"error": "not_found"})
+    if run is None:
+        return {"items": []}
+    rows = await step_summary.attempts(db, run.id, step_id, iteration)
+    started = await step_summary.children(db, run.id, [(step_id, iteration)])
+    return {"items": [_step(r, started.get((r.step_id, r.iteration_key))) for r in rows]}
diff --git a/backend/src/dewpoint/apps/step_summary.py b/backend/src/dewpoint/apps/step_summary.py
index 80b4e0dd..44f85fed 100644
--- a/backend/src/dewpoint/apps/step_summary.py
+++ b/backend/src/dewpoint/apps/step_summary.py
@@ -1,8 +1,8 @@
 # SPDX-License-Identifier: Apache-2.0
-"""A draft simulation's steps, summarized on the server (B8; the simulation design §6.6, §7.4): per step of the graph it
-ran, its instances' final attempts counted by status and by the port they took, a single instance's final attempt, and
-where its data came from; and a step's instances, one per iteration, paged in their iterations' own order. The general
-run detail stays unpaged until 4e (§9)."""
+"""A run's steps, summarized on the server (B8; the simulation design §6.6, §7.4; the runs design §4.4): per step of the
+graph it ran, its instances' final attempts counted by status, by the port they took and by their outcome, a single
+instance's final attempt, and where its data came from; a step's instances, one per iteration, paged in their
+iterations' own order; and one instance's attempts. Draft simulations and every other run, live or simulated."""
 
 import uuid
 from collections.abc import Mapping, Sequence
@@ -10,27 +10,41 @@ from dataclasses import dataclass, field
 from datetime import datetime
 from typing import Any
 
-from sqlalchemy import ColumnExpressionArgument, Integer, Select, cast, func, or_, select
+from sqlalchemy import ColumnExpressionArgument, Integer, Select, cast, func, or_, select, tuple_
 from sqlalchemy.dialects.postgresql import ARRAY, distinct_on
 from sqlalchemy.ext.asyncio import AsyncSession
 from sqlalchemy.orm import aliased
 from sqlalchemy.sql.elements import ColumnElement
 
-from dewpoint.core.models.runs import RunStep
+from dewpoint.core.models.runs import Run, RunStep
 from dewpoint.core.runs.service import HISTORY_LOST
 from dewpoint.engine.registry.control import CONTROL_TYPES, DELAY, WAIT_UNTIL
 from dewpoint.engine.runtime.execution import INTERNAL_ERROR, TERMINATED
 
 # D-a5: a run that ended outside the workflow (a bug, a termination, a lost history) never recorded what it would have
 NOT_RECORDED = frozenset({INTERNAL_ERROR, TERMINATED, HISTORY_LOST})
-
-
-def origin(type_ref: str, statuses: Mapping[str, int], *, ended: bool, error_code: str | None) -> str:
-    """Where a step's data came from (§7.4), from its instances' final attempts: one that began and wasn't stopped
-    says what made it (a timer that wasn't waited, an evaluation, or a plugin's fixture: nothing was sent); else the
-    instances say why none did. With none, where the run is: not reached yet while it runs; after its end, not
-    recorded in D-a5's cases, else it didn't run."""
+# B4b (4d-1a): from this engine ABI on, every step instance's end is recorded; before it, a step without a row after
+# its run's end is "not recorded" (the runs design §4.4)
+OUTCOMES_ABI = 9
+ATTEMPTS = 20  # a retry policy's most attempts (the graph model's `max_attempts`): one instance's, all of them
+
+
+def origin(
+    type_ref: str, statuses: Mapping[str, int], outcomes: Mapping[str, int] | None = None, *, live: bool = False,
+    ended: bool, error_code: str | None, recorded: bool = True,
+) -> str | None:  # fmt: skip
+    """Where a step's data came from (§7.4), from its instances' final attempts. In a live run (the runs design §4.4):
+    a plugin's request that may have been sent, whatever became of it, or one that was sent; nothing to say of a
+    control step's, or of one that sent nothing. Else, one that began and wasn't stopped says what made it (a timer
+    that wasn't waited, an evaluation, or a plugin's fixture: nothing was sent); else the instances say why none did.
+    With none, where the run is: not reached yet while it runs; after its end, not recorded in D-a5's cases or when its
+    graph's engine predates B4b (`recorded` False), else it didn't run."""
+    outcomes = outcomes or {}
+    if live and outcomes.get("outcome_unknown"):
+        return "may_have_been_sent"
     if any(statuses.get(status) for status in ("succeeded", "failed", "running")):
+        if live:
+            return "sent" if outcomes.get("applied") and type_ref not in CONTROL_TYPES else None
         if type_ref in (DELAY, WAIT_UNTIL):
             return "evaluated_not_waited"
         return "evaluated" if type_ref in CONTROL_TYPES else "fixture_not_sent"
@@ -39,7 +53,7 @@ def origin(type_ref: str, statuses: Mapping[str, int], *, ended: bool, error_cod
             return status
     if not ended:
         return "not_reached_yet"
-    return "not_recorded" if error_code in NOT_RECORDED else "didnt_run"
+    return "not_recorded" if error_code in NOT_RECORDED or not recorded else "didnt_run"
 
 
 @dataclass
@@ -49,9 +63,10 @@ class Summarized:
     step_id: uuid.UUID
     key: str
     type: str
-    origin: str
+    origin: str | None
     statuses: dict[str, int] = field(default_factory=dict)  # its instances, by their final attempt's status
     ports: dict[str, int] = field(default_factory=dict)  # and by the port it took (an `if`'s, a `switch`'s)
+    outcomes: dict[str, int] = field(default_factory=dict)  # and by their outcome, where they have one
     final: RunStep | None = None  # a single instance's final attempt
     first_at: datetime | None = None  # when it first began, or ended without beginning: its place in run order
 
@@ -72,22 +87,26 @@ def _finals(run_id: uuid.UUID) -> Select[Any]:
 
 async def summarize(
     s: AsyncSession, run_id: uuid.UUID | None, nodes: Sequence[Mapping[str, Any]], *, ended: bool,
-    error_code: str | None,
+    error_code: str | None, live: bool = False, recorded: bool = True,
 ) -> list[Summarized]:  # fmt: skip
-    """The steps `nodes` (the snapshot's, or a step test's target) of the run `run_id` (None: not written yet), in run
-    order: the steps that began or ended by when they first did, then the others in the graph's order."""
+    """The steps `nodes` (the graph's, or a step test's target) of the run `run_id` (None: not written yet), in run
+    order: the steps that began or ended by when they first did, then the others in the graph's order. `live` and
+    `recorded` (its graph's engine records every end) are the run's, for each step's origin."""
     found = {uuid.UUID(n["id"]): Summarized(uuid.UUID(n["id"]), n["key"], n["type"], "") for n in nodes}
     if run_id is not None:
         final = _finals(run_id).subquery()
         port = final.c.effect_preview["port"].astext
         counts = await s.execute(
-            select(final.c.step_id, final.c.status, port, func.count()).group_by(final.c.step_id, final.c.status, port)
-        )
-        for step_id, status, taken, n in counts:
+            select(final.c.step_id, final.c.status, port, final.c.outcome, func.count())
+            .group_by(final.c.step_id, final.c.status, port, final.c.outcome)
+        )  # fmt: skip
+        for step_id, status, taken, outcome, n in counts:
             if (step := found.get(step_id)) is not None:
                 step.statuses[status] = step.statuses.get(status, 0) + n
                 if taken is not None:
                     step.ports[taken] = step.ports.get(taken, 0) + n
+                if outcome is not None:
+                    step.outcomes[outcome] = step.outcomes.get(outcome, 0) + n
         firsts = await s.execute(
             select(RunStep.step_id, func.min(func.coalesce(RunStep.started_at, RunStep.ended_at)))
             .where(RunStep.run_id == run_id)
@@ -102,7 +121,8 @@ async def summarize(
             for row in rows.scalars():
                 found[row.step_id].final = row
     for step in found.values():
-        step.origin = origin(step.type, step.statuses, ended=ended, error_code=error_code)
+        step.origin = origin(step.type, step.statuses, step.outcomes, live=live, ended=ended, error_code=error_code,
+                             recorded=recorded)  # fmt: skip
     order = {step_id: n for n, step_id in enumerate(found)}
     return sorted(found.values(), key=lambda x: (x.first_at is None, x.first_at or datetime.min, order[x.step_id]))
 
@@ -130,3 +150,31 @@ async def instances(
         select(one).order_by(_numbered(one.iteration_key), one.iteration_key).offset(offset).limit(limit)
     )
     return total, list(page.scalars())
+
+
+async def attempts(s: AsyncSession, run_id: uuid.UUID, step_id: uuid.UUID, iteration_key: str) -> list[RunStep]:
+    """One instance's attempts, first to last: at most a retry policy's most."""
+    q = (
+        select(RunStep)
+        .where(RunStep.run_id == run_id, RunStep.step_id == step_id, RunStep.iteration_key == iteration_key)
+        .order_by(RunStep.attempt)
+        .limit(ATTEMPTS)
+    )
+    return list((await s.execute(q)).scalars())
+
+
+async def children(
+    s: AsyncSession, run_id: uuid.UUID, instances: Sequence[tuple[uuid.UUID, str]]
+) -> dict[tuple[uuid.UUID, str], uuid.UUID]:
+    """The sub-runs some of a run's step instances started (a sub-flow's, a failure handler's), by `(step_id,
+    iteration_key)`: only those asked for, so a page's or a few single steps', never every one of a loop's."""
+    if not instances:
+        return {}
+    q = select(Run.parent_step_id, Run.parent_iteration_key, Run.id).where(
+        Run.parent_run_id == run_id, tuple_(Run.parent_step_id, Run.parent_iteration_key).in_(list(instances))
+    )
+    found: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
+    for step_id, key, child in await s.execute(q):
+        if step_id is not None and key is not None:  # always: the query matched both
+            found[(step_id, key)] = child
+    return found
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
index 75aed0b3..97d7c499 100644
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -20,7 +20,7 @@ from dewpoint.core.models.ingress import WebhookEndpoint
 from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.runs import ExecutionEvidence, Run, RunStep
 from dewpoint.core.models.schedules import Schedule
-from dewpoint.core.models.workflows import Workflow
+from dewpoint.core.models.workflows import DraftSnapshot, Workflow, WorkflowVersion
 from dewpoint.core.retention.cutoff import Cutoff, kept
 
 MESSAGE_LIMIT = 500
@@ -514,3 +514,20 @@ async def run_steps(s: AsyncSession, run_id: uuid.UUID) -> list[RunStep]:
         .order_by(RunStep.started_at.nulls_last(), RunStep.iteration_key, RunStep.step_id, RunStep.attempt)
     )
     return list((await s.execute(q)).scalars())
+
+
+async def graph_of(
+    s: AsyncSession, version_id: uuid.UUID | None, snapshot_id: uuid.UUID | None
+) -> tuple[dict[str, Any] | None, int | None]:
+    """The graph a run ran and its engine ABI: its version's, or its draft snapshot's; none for a refusal that froze
+    neither."""
+    if version_id is not None:
+        found = await s.execute(select(WorkflowVersion.graph, WorkflowVersion.engine_abi)
+                                .where(WorkflowVersion.id == version_id))  # fmt: skip
+    elif snapshot_id is not None:
+        found = await s.execute(select(DraftSnapshot.graph, DraftSnapshot.engine_abi)
+                                .where(DraftSnapshot.id == snapshot_id))  # fmt: skip
+    else:
+        return None, None
+    row = found.one_or_none()
+    return (None, None) if row is None else (row[0], row[1])
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 42 passed.

- [ ] **Step 5: Run the static checks**

Run:

```bash
cd backend \
  && uv run ruff check src tests migrations \
  && uv run ruff format --check src tests migrations \
  && uv run mypy src
```

Expected: silent.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/step_summary.py backend/src/dewpoint/core/runs/service.py \
  backend/src/dewpoint/apps/api/routes/runs.py backend/src/dewpoint/apps/api/responses.py \
  backend/tests/apps/api/test_run_steps.py backend/tests/apps/test_step_summary.py \
  backend/tests/apps/test_step_summary_cost.py
git commit -m "feat(api): every run's steps, summarized and paged, its attempts and its sub-runs (4e-1a)

4d-1b's summary serves every run: a live run's origins (sent, may_have_been_sent, none), not_recorded for a
graph older than ABI 9, one instance's attempts, and the sub-runs a page of instances started.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: A run as itself, bounded

**Spec:** §4.3 (a run's answer), §4.5 (no `steps`, no `children`), §4.6 (cancel).

**Files:**
- Modify: `backend/src/dewpoint/core/runs/service.py` (`Labels`, `labels`),
  `backend/src/dewpoint/apps/api/routes/runs.py` (`get_run`, `_trigger`'s callers),
  `backend/src/dewpoint/apps/api/routes/run_requests.py` (cancel's `response_model`),
  `backend/src/dewpoint/apps/api/responses.py` (`CsvSkippedOut`, `CsvErrorOut`, `CsvRecordOut`, `RunParentOut`,
  `RunOut`, `RequestOut`, `CancelOut`)
- Test: create `backend/tests/apps/api/test_run_detail.py`; modify `backend/tests/apps/api/test_runs_api.py`,
  `backend/tests/apps/api/test_retention_reads.py`, `backend/tests/apps/api/test_simulations_api.py`,
  `backend/tests/apps/worker/test_worker_db.py`, `backend/tests/apps/dispatcher/test_triggers_end_to_end.py`

**Interfaces:**
- Consumes: Task 3's `_trigger`, `RunItemOut`; Task 4's `graph_of`, `OUTCOMES_ABI`.
- Produces:
  - `service.labels(s, *, workflow_id, actor_id, source, trigger_id) -> Labels`;
  - `RunOut` (extends `RunItemOut`: `draft_revision`, `outcomes_recorded`, `parent`, `csv`), `CancelOut`,
    `RequestOut`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_retention_reads.py b/backend/tests/apps/api/test_retention_reads.py
index 68383593..416b32d1 100644
--- a/backend/tests/apps/api/test_retention_reads.py
+++ b/backend/tests/apps/api/test_retention_reads.py
@@ -92,8 +92,8 @@ async def test_a_run_a_sub_run_or_a_request_past_its_cutoff_isnt_found(aged, key
     viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
     answer = await viewer.get(url(ctx, f"/runs/{aged[name]}"))
     assert answer.status_code == (200 if found else 404), answer.text
-    if name == "recent_run":  # its sub-runs come with it
-        assert [c["id"] for c in answer.json()["children"]] == [str(aged["recent_sub"])]
+    if name == "recent_sub":  # it names the run it was started from
+        assert answer.json()["parent"]["run_id"] == str(aged["recent_run"])
 
 
 async def test_a_tenants_retention_applies_to_reads_at_once(aged, keyed_app, owner_sessionmaker,
diff --git a/backend/tests/apps/api/test_run_detail.py b/backend/tests/apps/api/test_run_detail.py
new file mode 100644
index 00000000..9d1d58b4
--- /dev/null
+++ b/backend/tests/apps/api/test_run_detail.py
@@ -0,0 +1,78 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A run as itself (editor 4e-1; the runs design §4.3, §4.5), `run.view`: what the list says of it, the draft revision
+a draft simulation ran, whether its graph records every step instance's end, the run a sub-run was started from, and a
+CSV start's file; never its steps, which are read apart, summarized and paged. A cancel's answer, typed."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import step_summary
+from tests.apps.api.helpers import member_client
+from tests.apps.test_admission import TOKEN, admit, current, published
+from tests.apps.test_admission_drafts import simulate
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+async def read(app: Any, owner: Any, settings: Any, ctx: Any, run_id: uuid.UUID, role: str = "viewer") -> Any:
+    client, _ = await member_client(app, owner, settings, ctx.tenant_id, role)
+    return await client.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")
+
+
+async def test_a_request_shows_what_the_list_says_of_it_and_no_steps(
+    app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    request = (await admit(api_sessionmaker, ctx, wf, key="h")).request
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update run_requests set cancel_requested_at = now() where id = :i"), {"i": request.id})
+    answer = await read(app, owner_sessionmaker, api_settings, ctx, request.id)
+    assert answer.status_code == 200, answer.text
+    run = answer.json()
+    assert (run["status"], run["workflow_name"], run["started_by"]) == ("queued", "W", ctx.user.email)
+    assert run["trigger"] == {"source": "manual", "schedule": None, "endpoint": None, "rerun_of": None}
+    assert run["cancel_requested_at"] is not None
+    assert (run["draft_revision"], run["outcomes_recorded"], run["parent"], run["csv"]) == (None, True, None, None)
+    assert "steps" not in run and "children" not in run
+    assert TOKEN not in answer.text
+
+
+async def test_a_run_whose_graph_predates_b4b_says_its_ends_arent_all_recorded(
+    app, ready, owner_sessionmaker, api_sessionmaker, api_settings, monkeypatch
+) -> None:
+    ctx, wf = ready
+    request = (await admit(api_sessionmaker, ctx, wf, key="h")).request
+    monkeypatch.setattr(step_summary, "OUTCOMES_ABI", step_summary.OUTCOMES_ABI + 1)  # its graph's ABI, now older
+    assert (await read(app, owner_sessionmaker, api_settings, ctx, request.id)).json()["outcomes_recorded"] is False
+
+
+async def test_a_draft_simulation_names_the_revision_it_ran(
+    app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    draft = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN})).request
+    run = (await read(app, owner_sessionmaker, api_settings, ctx, draft.id)).json()
+    assert (run["mode"], run["draft_revision"]) == ("simulate", 1)
+    assert run["draft_snapshot_id"] == str(draft.draft_snapshot_id)
+
+
+async def test_a_cancel_answers_with_its_request(app, ready, owner_sessionmaker, api_sessionmaker,
+                                                api_settings) -> None:  # fmt: skip
+    ctx, wf = ready
+    request = (await admit(api_sessionmaker, ctx, wf, key="h")).request
+    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
+    assert (await viewer.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}/cancel")).status_code == 403
+    operator, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "operator")
+    answer = await operator.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}/cancel")
+    assert answer.status_code == 200, answer.text
+    assert (answer.json()["cancel"], answer.json()["request"]["status"]) == ("cancelled", "cancelled")
diff --git a/backend/tests/apps/api/test_runs_api.py b/backend/tests/apps/api/test_runs_api.py
index 5fc0611a..01e4cc14 100644
--- a/backend/tests/apps/api/test_runs_api.py
+++ b/backend/tests/apps/api/test_runs_api.py
@@ -98,7 +98,7 @@ async def test_a_request_that_never_started_is_shown_as_its_request_never_as_its
     viewer, items = await listed(app, owner_sessionmaker, api_settings, ctx)  # its pre-created row is `running`
     assert [(i["id"], i["status"], i["started_at"]) for i in items] == [(str(request.id), "queued", None)]
     detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}")).json()
-    assert (detail["status"], detail["steps"], detail["children"]) == ("queued", [], [])
+    assert (detail["status"], detail["started_at"], "steps" in detail) == ("queued", None, False)
     async with owner_sessionmaker() as s, s.begin():  # its backoff over
         await s.execute(text("update run_requests set next_attempt_at = now() where id = :i"), {"i": request.id})
     starting = await begin(dispatch_sessionmaker, request, api_settings)
diff --git a/backend/tests/apps/api/test_simulations_api.py b/backend/tests/apps/api/test_simulations_api.py
index d09dfd9d..e1966276 100644
--- a/backend/tests/apps/api/test_simulations_api.py
+++ b/backend/tests/apps/api/test_simulations_api.py
@@ -160,7 +160,8 @@ async def test_the_runs_api_shows_a_draft_runs_snapshot_target_and_each_steps_ef
     assert (run["version_id"], run["draft_snapshot_id"], run["target_step_id"]) == (
         None, str(request.draft_snapshot_id), str(nid("b")),
     )  # fmt: skip
-    assert [(step["key"], step["effect"]) for step in run["steps"]] == [("b", {"port": "true"})]
+    summary = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}/steps")).json()
+    assert [(step["key"], step["final"]["effect"]) for step in summary["steps"]] == [("b", {"port": "true"})]
 
 
 async def test_a_draft_snapshot_is_read_with_its_graph(
diff --git a/backend/tests/apps/dispatcher/test_triggers_end_to_end.py b/backend/tests/apps/dispatcher/test_triggers_end_to_end.py
index cbbbbf85..f0f40f9c 100644
--- a/backend/tests/apps/dispatcher/test_triggers_end_to_end.py
+++ b/backend/tests/apps/dispatcher/test_triggers_end_to_end.py
@@ -165,9 +165,11 @@ async def test_a_csv_start_and_a_schedules_tick_end_to_end_with_the_keyrings_rea
     rows = await plain_rows(owner_sessionmaker)
     assert not [c for c in CANARIES if c in rows]
     assert not [c for c in CANARIES for entry in logs if c in str(entry)]
-    for run in (csv_run, tick_run):
-        steps = (await editor.get(f"{base}/runs/{run['id']}")).json()["steps"]
-        assert steps and not [c for c in (CELL, FIXED) if c in str(steps)]
+    for run in (csv_run, tick_run):  # every step's instances, as a run's page reads them (the runs design §4.4)
+        steps = (await editor.get(f"{base}/runs/{run['id']}/steps")).json()["steps"]
+        seen = [(await editor.get(f"{base}/runs/{run['id']}/steps/{s['step_id']}/instances",
+                                  params={"limit": 100})).json()["items"] for s in steps]  # fmt: skip
+        assert steps and any(seen) and not [c for c in (CELL, FIXED) if c in str(seen)]
 
 
 async def decrypted_input(dispatch: Any, keys: Any, tenant_id: uuid.UUID, request_id: str) -> Any:
diff --git a/backend/tests/apps/worker/test_worker_db.py b/backend/tests/apps/worker/test_worker_db.py
index e4aab4d3..c4521968 100644
--- a/backend/tests/apps/worker/test_worker_db.py
+++ b/backend/tests/apps/worker/test_worker_db.py
@@ -68,8 +68,7 @@ async def test_a_run_is_projected_and_readable_through_the_api(
     viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
     listed = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()
     assert [(r["id"], r["status"], r["iterations"]) for r in listed] == [(str(run_id), "succeeded", 2)]
-    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")).json()
-    steps = {(s["key"], s["iteration_key"]): s for s in detail["steps"]}
+    steps = await instances(viewer, ctx.tenant_id, run_id)
     assert steps[("a", "")]["output"] == {"value": 2} and steps[("a", "")]["cel_mode"] == "local"
     assert steps[("a", "")]["outcome"] == "applied"
     assert {k for k in steps if k[0] == "x"} == {("x", "l:0"), ("x", "l:1")}
@@ -87,6 +86,17 @@ async def test_a_run_is_projected_and_readable_through_the_api(
     assert (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{uuid.uuid4()}")).status_code == 404
 
 
+async def instances(client: Any, tenant_id: uuid.UUID, run_id: Any) -> dict[tuple[str, str], dict[str, Any]]:
+    """A run's step instances, each its final attempt, by key and iteration, as a run's page reads them (the runs
+    design §4.4): the summary, then each step's instances."""
+    base = f"/api/v1/t/{tenant_id}/runs/{run_id}/steps"
+    found: dict[tuple[str, str], dict[str, Any]] = {}
+    for step in (await client.get(base)).json()["steps"]:
+        for item in (await client.get(f"{base}/{step['step_id']}/instances", params={"limit": 100})).json()["items"]:
+            found[(item["key"], item["iteration_key"])] = item
+    return found
+
+
 async def test_a_row_the_database_refuses_never_holds_up_the_others_or_the_run(
     owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
 ) -> None:
@@ -215,18 +225,16 @@ async def test_a_sub_flow_is_projected_as_a_run_of_its_own(
     viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
     listed = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()
     assert [r["id"] for r in listed] == [str(run_id)]  # the sub-run isn't listed on its own
-    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")).json()
-    [child] = detail["children"]
     step = next(n["id"] for n in g.nodes if n["key"] == "r")
-    assert (child["kind"], child["parent_run_id"], child["parent_step_id"], child["status"]) == (
+    [started] = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}/steps/{step}/instances")).json()["items"]
+    child = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{started['child_run_id']}")).json()
+    assert (child["kind"], child["parent"], child["status"]) == (
         "subflow",
-        str(run_id),
-        step,
+        {"run_id": str(run_id), "step_id": step, "iteration_key": ""},
         "succeeded",
     )
     assert child["workflow_id"] == str(sub_id)
-    sub_detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{child['id']}")).json()
-    assert [s["key"] for s in sub_detail["steps"]] == ["t"] and sub_detail["parent_run_id"] == str(run_id)
+    assert list(await instances(viewer, ctx.tenant_id, child["id"])) == [("t", "")]
 
 
 async def test_the_worker_loads_a_versions_pinned_cap_and_depth(
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/api/test_run_detail.py \
  tests/apps/api/test_runs_api.py \
  tests/apps/api/test_retention_reads.py \
  tests/apps/api/test_simulations_api.py \
  tests/apps/worker/test_worker_db.py \
  tests/apps/dispatcher/test_triggers_end_to_end.py
```

Expected: FAIL, 6 failed and 46 passed: a run has no `workflow_name`, `outcomes_recorded`, `draft_revision` or `parent`
(`KeyError`), and still has `steps` ("assert ('queued', None, True) == ('queued', None, False)"); the sub-run (worker)
and the recent sub-run (retention) have no `parent`. "a cancel answers with its request" passes at once: it pins today's
answer, which the model now types; the triggers end to end and the simulations test pass: they read Task 4's routes.

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 03bf91d6..bb9a1f6f 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -865,3 +865,70 @@ class RunAttemptsOut(_Answer):
     """One step instance's attempts, first to last."""
 
     items: list[RunStepOut]
+
+
+class CsvSkippedOut(_Answer):
+    row: int  # the record's number: 1 is the first after the header
+    code: str  # the first rule it broke
+
+
+class CsvErrorOut(_Answer):
+    row: int
+    column: str | None  # the declared column's name; null for the record as a whole
+    code: str
+
+
+class CsvRecordOut(_Answer):
+    """A CSV start's file as admission read it (engine 2b spec §8.1): the mapping from declared columns to its headers,
+    the rows run, every skipped row, and the first errors in detail with their count."""
+
+    mapping: dict[str, str]
+    headers: list[str]
+    row_count: int
+    skipped: list[CsvSkippedOut]
+    errors: list[CsvErrorOut]
+    error_count: int
+
+
+class RunParentOut(_Answer):
+    """The run a sub-run's step started it from (its sub-flow or failure handler)."""
+
+    run_id: str
+    step_id: str | None
+    iteration_key: str | None
+
+
+class RunOut(RunItemOut):
+    """A run, or a request that hasn't started, as itself (editor 4e-1; the runs design §4.3, §4.5): the list item's
+    facts, the draft revision a draft simulation ran, whether every step instance's end is recorded (its graph's engine
+    ABI is B4b's or later), the run that started a sub-run, and a CSV start's file. Its steps are read apart, summarized
+    and paged (§4.4)."""
+
+    draft_revision: int | None
+    outcomes_recorded: bool
+    parent: RunParentOut | None
+    csv: CsvRecordOut | None
+
+
+class RequestOut(_Answer):
+    """A run's request as the API shows it (engine 2b spec §7.2): its state and its frozen version, never its input."""
+
+    id: str
+    workflow_id: str
+    version_id: str | None
+    draft_snapshot_id: str | None
+    target_step_id: str | None
+    mode: Literal["live", "simulate"]
+    source: Source
+    status: Literal["queued", "starting", "started", "cancelled", "refused", "dead"]
+    reason: str | None
+    queued_at: str | None
+    ended_at: str | None
+
+
+class CancelOut(_Answer):
+    """A cancel (engine 2b spec §7.4): `cancelled` (200), the request hadn't started; `requested` (202), recorded for
+    the dispatcher to apply."""
+
+    cancel: Literal["cancelled", "requested"]
+    request: RequestOut
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
index 8d7c2d2b..c1d9e1a7 100644
--- a/backend/src/dewpoint/apps/api/routes/run_requests.py
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -15,7 +15,7 @@ from pydantic import BaseModel, ConfigDict, Field
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import admission, cancels
-from dewpoint.apps.api.responses import StartFormOut
+from dewpoint.apps.api.responses import CancelOut, StartFormOut
 from dewpoint.apps.csv_slots import CsvBusyError, Slot
 from dewpoint.apps.forms import csv_form, form_fields
 from dewpoint.apps.inputs import INPUT_INVALID, TOO_DEEP
@@ -210,7 +210,7 @@ async def start_form(
     }
 
 
-@router.post("/t/{tenant_id}/runs/{request_id}/cancel")
+@router.post("/t/{tenant_id}/runs/{request_id}/cancel", response_model=CancelOut)
 async def cancel_run(
     request_id: uuid.UUID,
     response: Response,
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
index f00a7c5d..c7bdadd1 100644
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -1,6 +1,6 @@
 # SPDX-License-Identifier: Apache-2.0
-"""Runs, read-only (spec §8; engine 2b spec §7.7): requests and top-level runs listed together, and one with its steps
-and the sub-runs it started (its sub-flows and failure handler). The UI reads this projection, never Temporal history.
+"""Runs, read-only (spec §8; engine 2b spec §7.7; editor 4e-1): requests and top-level runs listed together, filtered,
+and one as itself, its steps read apart (summarized and paged). The UI reads this projection, never Temporal history.
 A request that hasn't started is shown as its request, never as the row an attempt pre-created. Starting a run is
 `run_requests`'s."""
 
@@ -12,7 +12,7 @@ from fastapi import APIRouter, Depends, HTTPException, Query
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import step_summary
-from dewpoint.apps.api.responses import RunAttemptsOut, RunInstancesOut, RunItemOut, RunStepsOut
+from dewpoint.apps.api.responses import RunAttemptsOut, RunInstancesOut, RunItemOut, RunOut, RunStepsOut
 from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.claims import service as claims
@@ -61,19 +61,21 @@ def _item(i: service.Listed) -> dict[str, object]:
         "workflow_name": i.workflow_name,
         "started_by": i.started_by,
         "cancel_requested_at": _when(i.cancel_requested_at),
-        "trigger": _trigger(i),
+        "trigger": _trigger(i.source, i.rerun_of, i),
     }
 
 
-def _trigger(i: service.Listed) -> dict[str, object] | None:
+def _trigger(
+    source: str | None, rerun_of: uuid.UUID | None, named: service.Listed | service.Labels
+) -> dict[str, object] | None:
     """Where the request came from (the runs design §4.2): null for a run from before 2b-2, which had no request."""
-    if i.source is None:
+    if source is None:
         return None
     timing = None
-    if i.schedule_time_zone is not None:  # the schedule, as it is now; a deleted one's left out
-        timing = {"cron": i.schedule_cron, "every_s": i.schedule_every_s, "offset_s": i.schedule_offset_s,
-                  "time_zone": i.schedule_time_zone}  # fmt: skip
-    return {"source": i.source, "schedule": timing, "endpoint": i.endpoint_name, "rerun_of": _id(i.rerun_of)}
+    if named.schedule_time_zone is not None:  # the schedule, as it is now; a deleted one's left out
+        timing = {"cron": named.schedule_cron, "every_s": named.schedule_every_s, "offset_s": named.schedule_offset_s,
+                  "time_zone": named.schedule_time_zone}  # fmt: skip
+    return {"source": source, "schedule": timing, "endpoint": named.endpoint_name, "rerun_of": _id(rerun_of)}
 
 
 def _unstarted(r: RunRequest) -> dict[str, object]:
@@ -116,14 +118,6 @@ def _run(r: Run) -> dict[str, object]:
     }
 
 
-def _child(r: Run) -> dict[str, object]:
-    return {
-        **_run(r),
-        "parent_step_id": str(r.parent_step_id) if r.parent_step_id else None,
-        "parent_iteration_key": r.parent_iteration_key,
-    }
-
-
 def _step(r: RunStep, child: uuid.UUID | None = None) -> dict[str, object]:
     """One attempt of a step instance, and the sub-run it started (the runs design §4.4)."""
     return {
@@ -171,16 +165,17 @@ async def list_runs(
     return [_item(i) for i in items]
 
 
-@router.get("/t/{tenant_id}/runs/{run_id}")
+@router.get("/t/{tenant_id}/runs/{run_id}", response_model=RunOut)
 async def get_run(
     run_id: uuid.UUID,
     ctx: TenantContext = Depends(require(P.RUN_VIEW)),
     db: AsyncSession = Depends(get_db, scope="function"),
     keys: KeySource = Depends(get_keys),
 ) -> dict[str, object]:
-    """A run with its steps and sub-runs, or a request that hasn't started as itself; with its CSV record (engine 2b
-    spec §8.1), when it took a CSV: the mapping, the file's headers, the row count and the skipped rows. A run whose
-    tree, or a request that, passed the retention cutoff isn't found (§10.1)."""
+    """A run, or a request that hasn't started as itself (the runs design §4.3): what the list says of it, the draft
+    revision a draft simulation ran, whether its graph records every step instance's end, the run a sub-run's step
+    started it from, and its CSV record (engine 2b spec §8.1) when it took a CSV. Its steps are read apart (§4.4). A run
+    whose tree, or a request that, passed the retention cutoff isn't found (§10.1)."""
     at = await retention.cutoff(db, ctx.tenant_id)
     request = await db.get(RunRequest, run_id)  # row-level security: the caller's tenant's only
     if request is not None and not await retention.request_kept(db, at, request):
@@ -191,16 +186,32 @@ async def get_run(
             csv = await claims.read_csv_record(db, ClaimCipher(keys), ctx.tenant_id, request_id=request.id)
         except Exception as e:
             raise key_unusable(e) from None
+    parent = None
+    of: Run | RunRequest
     if request is not None and request.status != "started":
-        return {**_unstarted(request), "steps": [], "children": [], "csv": csv}
-    run = await service.get_run(db, run_id)
-    if run is None or run.tenant_id != ctx.tenant_id or not await retention.run_kept(db, at, run):
-        raise HTTPException(404, detail={"error": "not_found"})
+        base, of, actor = _unstarted(request), request, request.actor_id
+    else:
+        run = await service.get_run(db, run_id)
+        if run is None or run.tenant_id != ctx.tenant_id or not await retention.run_kept(db, at, run):
+            raise HTTPException(404, detail={"error": "not_found"})
+        base, of = {**_run(run), "request": _request(request)}, run
+        actor = run.started_by if request is None else request.actor_id  # before 2b-2, a run had no request
+        if run.parent_run_id is not None:
+            parent = {"run_id": str(run.parent_run_id), "step_id": _id(run.parent_step_id),
+                      "iteration_key": run.parent_iteration_key}  # fmt: skip
+    source = request.source if request is not None else None
+    named = await service.labels(db, workflow_id=of.workflow_id, actor_id=actor, source=source,
+                                 trigger_id=request.trigger_id if request is not None else None)  # fmt: skip
+    _, abi = await service.graph_of(db, of.workflow_version_id, of.draft_snapshot_id)
     return {
-        **_run(run),
-        "request": _request(request),
-        "steps": [_step(r) for r in await service.run_steps(db, run.id)],
-        "children": [_child(c) for c in await service.children(db, run.id)],
+        **base,
+        "workflow_name": named.workflow_name,
+        "started_by": named.started_by,
+        "cancel_requested_at": _when(request.cancel_requested_at) if request is not None else None,
+        "trigger": _trigger(source, request.rerun_of if request is not None else None, named),
+        "draft_revision": request.draft_revision if request is not None else None,
+        "outcomes_recorded": abi is None or abi >= step_summary.OUTCOMES_ABI,
+        "parent": parent,
         "csv": csv,
     }
 
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
index 97d7c499..df00d3da 100644
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -516,6 +516,42 @@ async def run_steps(s: AsyncSession, run_id: uuid.UUID) -> list[RunStep]:
     return list((await s.execute(q)).scalars())
 
 
+@dataclass(frozen=True)
+class Labels:
+    """What a run's page names besides the run (the runs design §4.3), as the list labels its items."""
+
+    workflow_name: str | None
+    started_by: str | None
+    schedule_cron: str | None
+    schedule_every_s: int | None
+    schedule_offset_s: int | None
+    schedule_time_zone: str | None
+    endpoint_name: str | None
+
+
+async def labels(
+    s: AsyncSession, *, workflow_id: uuid.UUID, actor_id: uuid.UUID | None, source: str | None,
+    trigger_id: uuid.UUID | None,
+) -> Labels:  # fmt: skip
+    """The workflow's name; the email of the person who asked, by hand or for a re-run (or before 2b-2, no source); the
+    schedule's timing, or the webhook endpoint's name, when it's still there."""
+    asked = actor_id if source in (None, "manual", "rerun") else None
+    q = select(
+        select(Workflow.name).where(Workflow.id == workflow_id).scalar_subquery(),
+        select(User.email).where(User.id == asked).scalar_subquery(),
+    )
+    workflow_name, started_by = (await s.execute(q)).one()
+    cron = every_s = offset_s = time_zone = endpoint_name = None
+    if source == "schedule" and trigger_id is not None:
+        found = await s.execute(select(Schedule.cron, Schedule.every_s, Schedule.offset_s, Schedule.time_zone)
+                                .where(Schedule.id == trigger_id, Schedule.deleted_at.is_(None)))  # fmt: skip
+        if (timing := found.one_or_none()) is not None:
+            cron, every_s, offset_s, time_zone = timing
+    if source == "webhook" and trigger_id is not None:
+        endpoint_name = (await s.execute(select(WebhookEndpoint.name).where(WebhookEndpoint.id == trigger_id))).scalar()
+    return Labels(workflow_name, started_by, cron, every_s, offset_s, time_zone, endpoint_name)
+
+
 async def graph_of(
     s: AsyncSession, version_id: uuid.UUID | None, snapshot_id: uuid.UUID | None
 ) -> tuple[dict[str, Any] | None, int | None]:
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 52 passed.

- [ ] **Step 5: Run the static checks**

Run:

```bash
cd backend \
  && uv run ruff check src tests migrations \
  && uv run ruff format --check src tests migrations \
  && uv run mypy src
```

Expected: silent.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/core/runs/service.py backend/src/dewpoint/apps/api/routes/runs.py \
  backend/src/dewpoint/apps/api/routes/run_requests.py backend/src/dewpoint/apps/api/responses.py \
  backend/tests/apps/api/test_run_detail.py backend/tests/apps/api/test_runs_api.py \
  backend/tests/apps/api/test_retention_reads.py backend/tests/apps/api/test_simulations_api.py \
  backend/tests/apps/worker/test_worker_db.py backend/tests/apps/dispatcher/test_triggers_end_to_end.py
git commit -m "feat(api): a run as itself, bounded (4e-1a)

What the list says of it, the draft revision, whether its graph records every end, the run a sub-run came
from, a typed CSV record; no steps or children, read apart instead. Cancel's answer typed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: A run's input, read back

**Spec:** §4.3 (the input read back), §4.6 (retention, erasure).

**Files:**
- Modify: `backend/src/dewpoint/apps/api/routes/runs.py` (`read_back`, `_redacted` moved in; `CSV_ROWS`,
  `run_input`), `backend/src/dewpoint/apps/api/routes/simulations.py` (imports `read_back`),
  `backend/src/dewpoint/apps/api/responses.py` (`RunInputOut`)
- Test: create `backend/tests/apps/api/test_run_input.py`; modify `backend/tests/apps/api/test_retention_reads.py`

**Interfaces:**
- Consumes: Task 4's `_ran`; 4d-1b's `claims.read_envelope`, `read_csv_record`.
- Produces: `runs.read_back(db, keys, ctx, r) -> tuple[str, Any]` (the simulations route imports it); route
  `GET /t/{tenant}/runs/{run_id}/input` answering `RunInputOut`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_retention_reads.py b/backend/tests/apps/api/test_retention_reads.py
index 416b32d1..a4a4de81 100644
--- a/backend/tests/apps/api/test_retention_reads.py
+++ b/backend/tests/apps/api/test_retention_reads.py
@@ -96,6 +96,22 @@ async def test_a_run_a_sub_run_or_a_request_past_its_cutoff_isnt_found(aged, key
         assert answer.json()["parent"]["run_id"] == str(aged["recent_run"])
 
 
+@pytest.mark.parametrize(("name", "found"), [("old_run", False), ("recent_run", True)])
+async def test_a_runs_step_reads_and_its_input_keep_its_cutoff(aged, keyed_app, owner_sessionmaker, api_settings,
+                                                                name: str, found: bool) -> None:  # fmt: skip
+    """The runs design §4.6: past the cutoff, a run's step reads and its input read back aren't found either."""
+    ctx = aged["ctx"]
+    async with owner_sessionmaker() as s:
+        step = (await s.execute(text("select v.graph->'nodes'->0->>'id' from workflow_versions v "
+                                     "join workflows w on w.active_version_id = v.id where w.id = :w"),
+                                {"w": aged["wf"]})).scalar()  # fmt: skip
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    run = aged[name]
+    for path in (f"/runs/{run}/steps", f"/runs/{run}/steps/{step}/instances", f"/runs/{run}/steps/{step}/attempts",
+                 f"/runs/{run}/input"):  # fmt: skip
+        assert (await viewer.get(url(ctx, path))).status_code == (200 if found else 404), path
+
+
 async def test_a_tenants_retention_applies_to_reads_at_once(aged, keyed_app, owner_sessionmaker,
                                                             api_settings) -> None:  # fmt: skip
     """Reads filter by the cutoff whatever is stored: a longer retention shows again what retention hasn't deleted."""
diff --git a/backend/tests/apps/api/test_run_input.py b/backend/tests/apps/api/test_run_input.py
new file mode 100644
index 00000000..62b581b2
--- /dev/null
+++ b/backend/tests/apps/api/test_run_input.py
@@ -0,0 +1,101 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What a run was admitted with, read back (editor 4e-1; the runs design §4.3), `run.view`: from its request's own
+envelope, redacted, never recomputed; a step test's seeds; a CSV start's input without its rows; `absent` when the
+request kept none; `unreadable` when it doesn't open, its key gone included, never an error."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from tests.apps.api.test_run_requests_api import as_role, keyed_app
+from tests.apps.test_admission import admit, current, published
+from tests.apps.test_admission_csv import GRAPH, staged, start
+from tests.apps.test_admission_drafts import STEPS_GRAPH, drafted, simulate
+from tests.support.graphs import nid
+from tests.support.keys import FixtureKeys
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    await current(dispatch_sessionmaker)
+    return ctx, wf
+
+
+async def read(app: Any, owner: Any, settings: Any, ctx: Any, run_id: uuid.UUID) -> Any:
+    viewer = await as_role(app, owner, settings, ctx, "viewer")
+    answer = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}/input")
+    assert answer.status_code == 200, answer.text
+    return answer.json()
+
+
+async def test_the_input_is_read_back_redacted(keyed_app, ready, owner_sessionmaker, api_sessionmaker,
+                                               api_settings) -> None:  # fmt: skip
+    ctx, wf = ready
+    request = (await admit(api_sessionmaker, ctx, wf)).request
+    assert await read(keyed_app, owner_sessionmaker, api_settings, ctx, request.id) == {
+        "read_back": "kept", "input": {"token": "[redacted]", "site": "a"}, "seeds": None,
+    }  # fmt: skip
+
+
+async def test_a_step_tests_seeds_are_read_back(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    await current(dispatch_sessionmaker)
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
+                              values={"/steps/a/output/value": 3})).request  # fmt: skip
+    found = await read(keyed_app, owner_sessionmaker, api_settings, ctx, request.id)
+    assert (found["read_back"], found["input"]) == ("kept", None)
+    assert found["seeds"]["values"] == {"/steps/a/output/value": "[redacted]"}  # an echo's output: tainted
+
+
+async def test_a_csv_starts_input_leaves_its_rows_to_its_csv_record(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, GRAPH)
+    await current(dispatch_sessionmaker)
+    upload = await staged(api_sessionmaker, ctx, wf)
+    request = (await admit(api_sessionmaker, ctx, wf, csv=start(upload))).request
+    found = await read(keyed_app, owner_sessionmaker, api_settings, ctx, request.id)
+    assert found == {"read_back": "kept", "input": {"token": "[redacted]", "site": "a"}, "seeds": None}
+
+
+async def test_a_refusal_that_froze_nothing_kept_no_input(keyed_app, ready, owner_sessionmaker, api_sessionmaker,
+                                                          api_settings) -> None:  # fmt: skip
+    ctx, wf = ready
+    refused = (await admit(api_sessionmaker, ctx, wf, source="schedule", input={"token": 7})).request
+    assert refused.status == "refused"
+    assert await read(keyed_app, owner_sessionmaker, api_settings, ctx, refused.id) == {
+        "read_back": "absent", "input": None, "seeds": None,
+    }  # fmt: skip
+
+
+async def test_an_input_that_doesnt_open_is_unreadable_its_key_gone_included(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    broken = (await admit(api_sessionmaker, ctx, wf, key="broken")).request
+    kept = (await admit(api_sessionmaker, ctx, wf, key="kept")).request
+    async with owner_sessionmaker() as s, s.begin():
+        await s.execute(text("update run_inputs set ciphertext = :junk "
+                             "where id = (select envelope_id from run_requests where id = :r)"),
+                        {"junk": b"\x00" * 48, "r": broken.id})  # fmt: skip
+    unreadable = {"read_back": "unreadable", "input": None, "seeds": None}
+    assert await read(keyed_app, owner_sessionmaker, api_settings, ctx, broken.id) == unreadable
+    keyed_app.state.keys = FixtureKeys(missing={str(ctx.tenant_id)})  # an erasure took the tenant's key
+    assert await read(keyed_app, owner_sessionmaker, api_settings, ctx, kept.id) == unreadable
+
+
+async def test_another_tenants_runs_input_isnt_found(keyed_app, ready, owner_sessionmaker, api_sessionmaker,
+                                                     admin_sessionmaker, api_settings) -> None:  # fmt: skip
+    ctx, wf = ready
+    request = (await admit(api_sessionmaker, ctx, wf)).request
+    other, _ = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, other, "viewer")
+    assert (await viewer.get(f"/api/v1/t/{other.tenant_id}/runs/{request.id}/input")).status_code == 404
```

- [ ] **Step 2: Run them**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/api/test_run_input.py \
  tests/apps/api/test_simulation_reads.py \
  tests/apps/api/test_retention_reads.py
```

Expected: FAIL, 6 failed and 28 passed: `/input` isn't a route (404 `not_found`) for the five read-back tests and the
recent run's retention case. The other tenant's case and the old run's pass at once (a 404 either way); the simulation
reads pass.

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index bb9a1f6f..187f6753 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -932,3 +932,14 @@ class CancelOut(_Answer):
 
     cancel: Literal["cancelled", "requested"]
     request: RequestOut
+
+
+class RunInputOut(_Answer):
+    """What a run was admitted with, read back from its request's own envelope, redacted (the runs design §4.3): its
+    `input`, or a step test's `seeds`. `absent`: the request kept none (a refusal admission never froze, or a run from
+    before 2b-2); `unreadable`: there, but it doesn't open (a broken ciphertext, or the tenant's key gone during an
+    erasure). A CSV start's rows are its CSV record's, never repeated here."""
+
+    read_back: Literal["kept", "absent", "unreadable"]
+    input: dict[str, Any] | None
+    seeds: dict[str, Any] | None
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
index c7bdadd1..0d1b92dc 100644
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -12,7 +12,14 @@ from fastapi import APIRouter, Depends, HTTPException, Query
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import step_summary
-from dewpoint.apps.api.responses import RunAttemptsOut, RunInstancesOut, RunItemOut, RunOut, RunStepsOut
+from dewpoint.apps.api.responses import (
+    RunAttemptsOut,
+    RunInputOut,
+    RunInstancesOut,
+    RunItemOut,
+    RunOut,
+    RunStepsOut,
+)
 from dewpoint.apps.api.routes.run_requests import get_keys, key_unusable
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.claims import service as claims
@@ -23,6 +30,8 @@ from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.runs import Run, RunStep
 from dewpoint.core.retention import cutoff as retention
 from dewpoint.core.runs import service
+from dewpoint.engine.handles import ClaimRef
+from dewpoint.engine.runtime.projection import REDACTED
 
 router = APIRouter(prefix="/api/v1", tags=["runs"])
 # The list's status filter (the runs design §4.2): `waiting` is queued or starting; `didnt_start`, refused or dead
@@ -311,3 +320,61 @@ async def step_attempts(
     rows = await step_summary.attempts(db, run.id, step_id, iteration)
     started = await step_summary.children(db, run.id, [(step_id, iteration)])
     return {"items": [_step(r, started.get((r.step_id, r.iteration_key))) for r in rows]}
+
+
+async def read_back(db: AsyncSession, keys: KeySource, ctx: TenantContext, r: RunRequest) -> tuple[str, Any]:
+    """The request's own envelope (B8; the runs design §4.3), each claim in it `[redacted]` (a sensitive value, or one
+    claimed by its size): the input or seeds it was admitted with, never recomputed. `kept` with it; `absent` when the
+    request has none; `unreadable` when it's there but doesn't open under its tenant or isn't JSON: never read as
+    absent."""
+    try:
+        envelope = await claims.read_envelope(db, ClaimCipher(keys), ctx.tenant_id, request_id=r.id)
+    except claims.EnvelopeUnreadableError:
+        return "unreadable", None
+    except claims.EnvelopeUnavailableError:
+        return "absent", None
+    except Exception as e:
+        raise key_unusable(e) from None
+    return "kept", _redacted(envelope)
+
+
+def _redacted(value: Any) -> Any:
+    if ClaimRef.of(value) is not None:
+        return REDACTED
+    if isinstance(value, dict):
+        return {k: _redacted(v) for k, v in value.items()}
+    if isinstance(value, list):
+        return [_redacted(v) for v in value]
+    return value
+
+
+CSV_ROWS = ("rows", "row_count")  # what a CSV start's envelope adds to its input (admission)
+
+
+@router.get("/t/{tenant_id}/runs/{run_id}/input", response_model=RunInputOut)
+async def run_input(
+    run_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    """What a run was admitted with, read back from its request's own envelope, redacted, never recomputed (the runs
+    design §4.3): a step test's seeds, or the workflow's input, a CSV start's rows left to its CSV record. A tenant's
+    key gone (an erasure) reads as `unreadable`, never an error."""
+    await _ran(db, ctx, run_id)
+    request = await db.get(RunRequest, run_id)
+    if request is None:  # a run from before 2b-2 had no request
+        return {"read_back": "absent", "input": None, "seeds": None}
+    try:
+        kept, used = await read_back(db, keys, ctx, request)
+    except HTTPException as e:
+        if e.status_code != 503:
+            raise
+        return {"read_back": "unreadable", "input": None, "seeds": None}
+    if kept != "kept" or not isinstance(used, dict):
+        return {"read_back": kept, "input": None, "seeds": None}
+    if request.target_step_id is not None:
+        return {"read_back": kept, "input": None, "seeds": used}
+    if await claims.read_csv_record(db, ClaimCipher(keys), ctx.tenant_id, request_id=request.id) is not None:
+        used = {k: v for k, v in used.items() if k not in CSV_ROWS}
+    return {"read_back": kept, "input": used, "seeds": None}
diff --git a/backend/src/dewpoint/apps/api/routes/simulations.py b/backend/src/dewpoint/apps/api/routes/simulations.py
index c086700f..6262ee1a 100644
--- a/backend/src/dewpoint/apps/api/routes/simulations.py
+++ b/backend/src/dewpoint/apps/api/routes/simulations.py
@@ -32,12 +32,10 @@ from dewpoint.apps.api.routes.run_requests import (
     not_past_cutoff,
     request_body,
 )
-from dewpoint.apps.api.routes.runs import _step
+from dewpoint.apps.api.routes.runs import _step, read_back
 from dewpoint.apps.api.routes.workflows import _get, _revision
 from dewpoint.apps.forms import csv_form, form_fields
 from dewpoint.core.authz.permissions import P
-from dewpoint.core.claims import service as claims
-from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.config import Settings
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
@@ -48,8 +46,6 @@ from dewpoint.core.retention import cutoff as retention
 from dewpoint.core.workflows.service import DraftConflictError
 from dewpoint.engine.graph import seeds
 from dewpoint.engine.graph.model import GraphFormatError, parse_graph
-from dewpoint.engine.handles import ClaimRef
-from dewpoint.engine.runtime.projection import REDACTED
 
 router = APIRouter(prefix="/api/v1", tags=["simulations"])
 
@@ -233,31 +229,6 @@ async def simulation_of(
     return r
 
 
-async def read_back(db: AsyncSession, keys: KeySource, ctx: TenantContext, r: RunRequest) -> tuple[str, Any]:
-    """The request's own envelope, each claim in it `[redacted]` (a sensitive value, or one claimed by its size): the
-    input or seeds it was admitted with, never recomputed. `kept` with it; `absent` when the request has none;
-    `unreadable` when it's there but doesn't open under its tenant or isn't JSON: never read as absent."""
-    try:
-        envelope = await claims.read_envelope(db, ClaimCipher(keys), ctx.tenant_id, request_id=r.id)
-    except claims.EnvelopeUnreadableError:
-        return "unreadable", None
-    except claims.EnvelopeUnavailableError:
-        return "absent", None
-    except Exception as e:
-        raise key_unusable(e) from None
-    return "kept", _redacted(envelope)
-
-
-def _redacted(value: Any) -> Any:
-    if ClaimRef.of(value) is not None:
-        return REDACTED
-    if isinstance(value, dict):
-        return {k: _redacted(v) for k, v in value.items()}
-    if isinstance(value, list):
-        return [_redacted(v) for v in value]
-    return value
-
-
 @router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps",
             response_model=SimulationStepsOut)  # fmt: skip
 async def simulation_steps(
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 34 passed: the simulation reads too, on the read-back moved to `runs.py`.

- [ ] **Step 5: Run the static checks**

Run:

```bash
cd backend \
  && uv run ruff check src tests migrations \
  && uv run ruff format --check src tests migrations \
  && uv run mypy src
```

Expected: silent.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/api/routes/runs.py backend/src/dewpoint/apps/api/routes/simulations.py \
  backend/src/dewpoint/apps/api/responses.py backend/tests/apps/api/test_run_input.py \
  backend/tests/apps/api/test_retention_reads.py
git commit -m "feat(api): a run's input, read back redacted (4e-1a)

From its request's own envelope, as a simulation's is: a step test's seeds, or the input without a CSV
start's rows; absent when none was kept, unreadable when it doesn't open, its key gone included.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: The milestone**

Append `### 4e-1a, milestone 2 (<date>)` to the ledger. For each of Tasks 4–6, record its commit and its red and
green results as they ran, and any mid-slice ruling. Commit it as `docs(editor-4): 4e-1a milestone 2`, with the
trailer. Then stop for the owner's review.

---

# Milestone 3 — The last run's id, the client, every check

### Task 7: The Workflows list's last run names its run

**Spec:** §4.5 (the last run's `id`).

**Files:**
- Modify: `backend/src/dewpoint/apps/workflow_summary.py` (`LAST_RUNS`, `LastRun.id`),
  `backend/src/dewpoint/apps/api/routes/workflows.py` (`_last`), `backend/src/dewpoint/apps/api/responses.py`
  (`LastRunOut.id`)
- Test: modify `backend/tests/apps/api/test_workflow_summary.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `LastRunOut.id: str` (4e-1b links the cell to the run).

- [ ] **Step 1: Write the failing test**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_workflow_summary.py b/backend/tests/apps/api/test_workflow_summary.py
index 154053a7..7c9032c2 100644
--- a/backend/tests/apps/api/test_workflow_summary.py
+++ b/backend/tests/apps/api/test_workflow_summary.py
@@ -91,7 +91,7 @@ async def test_the_list_says_how_each_workflows_runs_went(app, owner_sessionmake
         wid, vid = await published(c, tid)
         root = await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", hours_ago=30)  # out of the 24 h
         await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", hours_ago=2)
-        await add_run(owner_sessionmaker, tid, wid, vid, status="failed", hours_ago=0.5)  # the last live root run
+        failed = await add_run(owner_sessionmaker, tid, wid, vid, status="failed", hours_ago=0.5)  # the last live
         await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", mode="simulate", hours_ago=0.2)
         await add_run(owner_sessionmaker, tid, wid, vid, status="running", hours_ago=0.1, parent=root)  # a sub-run
         quiet, _ = await published(c, tid)
@@ -99,6 +99,7 @@ async def test_the_list_says_how_each_workflows_runs_went(app, owner_sessionmake
     busy = rows[wid]
     assert busy["draft_graph_hash"] == graph_hash(parse_graph(GRAPH))
     assert busy["last_run"]["status"] == "failed" and busy["last_simulation"]["status"] == "succeeded"
+    assert busy["last_run"]["id"] == str(failed)  # its page's link (editor 4e-1; the runs design §4.5)
     assert busy["runs_24h"] == {"live": 2, "simulate": 1}
     assert busy["needs_attention"] == ["last_run_failed"]  # the later successful simulation doesn't clear it
     assert busy["unpublished_changes"] is False
```

- [ ] **Step 2: Run it**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/apps/api/test_workflow_summary.py \
  tests/apps/test_workflow_summary.py
```

Expected: FAIL, 1 failed and 25 passed: the last run has no `id` (`KeyError: 'id'`).

- [ ] **Step 3: Write the implementation**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 187f6753..8413cb12 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -165,6 +165,7 @@ class DiagnosticOut(_Answer):
 
 
 class LastRunOut(_Answer):
+    id: str  # its page's (editor 4e-1; the runs design §4.5)
     status: Literal["running", "succeeded", "failed", "cancelled", "deadline_exceeded"]
     at: str  # when it ended, else started, else was queued
 
diff --git a/backend/src/dewpoint/apps/api/routes/workflows.py b/backend/src/dewpoint/apps/api/routes/workflows.py
index 7ff3f551..2ce5e06a 100644
--- a/backend/src/dewpoint/apps/api/routes/workflows.py
+++ b/backend/src/dewpoint/apps/api/routes/workflows.py
@@ -96,7 +96,7 @@ async def _get(db: AsyncSession, ctx: TenantContext, workflow_id: uuid.UUID, *,
 
 
 def _last(run: workflow_summary.LastRun | None) -> dict[str, str] | None:
-    return None if run is None else {"status": run.status, "at": run.at.isoformat()}
+    return None if run is None else {"id": str(run.id), "status": run.status, "at": run.at.isoformat()}
 
 
 async def _summaries(db: AsyncSession, tenant_id: uuid.UUID, wfs: list[Workflow]) -> list[dict[str, object]]:
diff --git a/backend/src/dewpoint/apps/workflow_summary.py b/backend/src/dewpoint/apps/workflow_summary.py
index 0a27e336..9c754142 100644
--- a/backend/src/dewpoint/apps/workflow_summary.py
+++ b/backend/src/dewpoint/apps/workflow_summary.py
@@ -31,9 +31,9 @@ ATTENTION_STATUSES = ("failed", "deadline_exceeded")
 # and the probe and the work-unit test observed the ordered scan on every workload they tried; it's what the planner
 # chose there, not a guarantee for every future plan.
 LAST_RUNS = text(
-    "select w.id as workflow_id, m.mode, r.status, r.at"
+    "select w.id as workflow_id, m.mode, r.id, r.status, r.at"
     " from unnest(cast(:ids as uuid[])) as w(id) cross join (values ('live'), ('simulate')) as m(mode)"
-    " cross join lateral (select mode, status, coalesce(ended_at, started_at, queued_at) as at from runs"
+    " cross join lateral (select id, mode, status, coalesce(ended_at, started_at, queued_at) as at from runs"
     " where tenant_id = :tenant and kind = 'run' and draft_snapshot_id is null and workflow_id = w.id"
     " and mode >= m.mode"
     " order by mode, queued_at desc, id desc limit 1) as r where r.mode = m.mode"
@@ -68,6 +68,7 @@ TRIGGERS = text(
 class LastRun:
     status: str
     at: datetime  # when it ended, else started, else was queued
+    id: uuid.UUID | None = None  # its page's (editor 4e-1)
 
 
 @dataclass(frozen=True)
@@ -87,7 +88,7 @@ async def run_stats(
     if not ids:
         return {}
     params = {"tenant": tenant_id, "ids": ids}
-    last = {(r.workflow_id, r.mode): LastRun(r.status, r.at) for r in await s.execute(LAST_RUNS, params)}
+    last = {(r.workflow_id, r.mode): LastRun(r.status, r.at, r.id) for r in await s.execute(LAST_RUNS, params)}
     counts = {r.workflow_id: (int(r.live), int(r.simulated)) for r in await s.execute(COUNTS_24H, params)}
     return {
         wid: RunStats(
```

- [ ] **Step 4: Run it again**

Run: the same command.

Expected: PASS, 26 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/dewpoint/apps/workflow_summary.py backend/src/dewpoint/apps/api/routes/workflows.py \
  backend/src/dewpoint/apps/api/responses.py backend/tests/apps/api/test_workflow_summary.py
git commit -m "feat(api): the Workflows list's last run names its run (4e-1a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The client, the docs, every check, the final checkpoint

**Spec:** §4.1 (the generated client), §6.

**Files:**
- Modify: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts` (regenerated), `docs/operations/runs.md`
  ("Reading runs"), `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (the final checkpoint)

**Interfaces:**
- Consumes: every route and model above.
- Produces: the typed client 4e-1b reads.

- [ ] **Step 1: Regenerate the client**

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run dewpoint api openapi > ../frontend/src/api/openapi.json
cd ../frontend && pnpm gen:api && pnpm check:api
```

Expected: `openapi.json` gains the run routes and models (about 1,900 lines added); `schema.d.ts` gains their types
(about 620); `check:api` passes. Never edit either by hand.

- [ ] **Step 2: Check that the frontend still passes**

Run:

```bash
cd frontend && pnpm exec tsc -b --noEmit && pnpm exec eslint . && pnpm exec vitest run
```

Expected: the type check and ESLint silent; 1184 passed in 90 files, as on main: the draft simulation types are
unchanged (ruling 7).

- [ ] **Step 3: The docs**

Apply:

```diff
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index b5624434..727796a9 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -522,15 +522,43 @@ or replace (422). Nothing is recorded. Nothing kept can hold one, and a webhook
 ## Reading runs
 
 `GET /api/v1/t/{tenant}/runs` lists requests and top-level runs together, newest first by `(queued_at, id)`
-(`workflow_id`, `before`, `before_id` and `limit` filter and page them). A request's `queued_at` is when it was
-admitted; its run shares its id and `queued_at`; a run from before 2b-2 has its `started_at`. **The order changed in
-2b-2:** it was by start time, and the next page's cursor is now the last item's `queued_at` with its `id`, given
-together (else 422 `invalid_cursor`). Each item's `request` holds its `status`, `source` and `reason` (none for a run
-from before 2b-2). A request that hasn't started is shown as itself — `queued`, `starting`, `cancelled`, `refused` or
-`dead` — never as the row an attempt pre-created. `GET /api/v1/t/{tenant}/runs/{run_id}` returns one run with its
-steps (one row per step, loop iteration and attempt) and its `children`: the sub-runs it started (a request that hasn't
-started has neither). The `iteration_key` is the loop step's key and the item's index,
-like `each_ap:3`, or `outer:1/inner:4` when nested. Both need the `run.view` permission.
+(`before`, `before_id` and `limit` page them). A request's `queued_at` is when it was admitted; its run shares its id
+and `queued_at`; a run from before 2b-2 has its `started_at`. **The order changed in 2b-2:** it was by start time, and
+the next page's cursor is now the last item's `queued_at` with its `id`, given together (else 422 `invalid_cursor`).
+Each item's `request` holds its `status`, `source` and `reason` (none for a run from before 2b-2). A request that hasn't
+started is shown as itself — `queued`, `starting`, `cancelled`, `refused` or `dead` — never as the row an attempt
+pre-created. Both reads need the `run.view` permission.
+
+The list is filtered (editor 4e-1) by:
+
+| Parameter | Values |
+|---|---|
+| `workflow_id` | a workflow |
+| `status` | `waiting` (queued or starting), `running`, `succeeded`, `failed`, `deadline_exceeded`, `cancelled`, `didnt_start` (refused or dead): a run's status, or an unstarted request's |
+| `mode` | `live` or `simulate` |
+| `draft` | `exclude` (the default: draft simulations left out), `only`, `include` |
+| `source` | `manual`, `rerun`, `schedule`, `webhook`, `dev` |
+| `since` | items queued at or after this time |
+
+Each item also names its workflow (`workflow_name`); the email of the person who asked (`started_by`: by hand or a
+re-run, else null); a requested cancel (`cancel_requested_at`); and where it came from (`trigger`: its `source`, the
+schedule's timing, the webhook endpoint's name, or the run a re-run repeats, `rerun_of`). A request admitted before
+migration 0073 has no schedule, endpoint or re-run link; a deleted schedule's is null too.
+
+`GET /api/v1/t/{tenant}/runs/{run_id}` returns one run, or a request that hasn't started, as itself: what the list says
+of it, the `draft_revision` a draft simulation ran, `outcomes_recorded` (false when its graph's engine ABI predates 9,
+B4b: a step without a row after its end is "not recorded"), `parent` for a sub-run (the run, step and iteration that
+started it), and a CSV start's `csv` record. **It no longer returns `steps` or `children` (editor 4e-1):** a run's steps
+are read apart, summarized and paged, so a run of many iterations is read in bounded pieces:
+
+| Route (under `/api/v1/t/{tenant}/runs/{run_id}`) | Returns |
+|---|---|
+| `GET /steps` | a summary per step of the graph it ran, in run order: its instances' final attempts counted by status and by port, a single instance's final attempt, and its origin. A live run's plugin step says `sent` (its request went out, reads included) or `may_have_been_sent` (an attempt whose answer was lost); a control step's, or one that sent nothing, has none. A simulated run's are the simulation's (above). `given`: `input`, or `seeded` for a step test |
+| `GET /steps/{step}/instances` | a step's instances, one per iteration (its final attempt), by iteration number, with their `total` (`offset`; `limit`, 1 to 100; `within`, one iteration and those nested in it); each names the sub-run it started (`child_run_id`) |
+| `GET /steps/{step}/attempts?iteration=KEY` | one instance's attempts, first to last (at most 20, a retry policy's most); `iteration` empty outside a loop |
+| `GET /input` | what it was admitted with, read back from its request's envelope, redacted (`[redacted]` where it held a claim): its `input`, or a step test's `seeds`; a CSV start's rows are its `csv` record's. `read_back`: `kept`, `absent` (a refusal that froze nothing, or a run from before 2b-2), `unreadable` (it doesn't open, or the tenant's key is gone during an erasure) |
+
+The `iteration_key` is the loop step's key and the item's index, like `each_ap:3`, or `outer:1/inner:4` when nested.
 
 Every run has a `kind`. A sub-flow's run (`subflow`) and a failure handler's (`failure_handler`) are runs of their
 own, with their own steps, and point at the run that started them (`parent_run_id`, and for a sub-flow the step and
```

- [ ] **Step 4: The backend's checks**

Run:

```bash
cd backend \
  && uv run ruff check src tests migrations \
  && uv run ruff format --check src tests migrations \
  && uv run mypy src \
  && uv run lint-imports
```

Expected: silent; "Contracts: 11 kept, 0 broken."

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 \
  tests/qualification/test_reference_rights.py \
  tests/migrations/test_online.py \
  tests/migrations/test_0073.py
```

Expected: PASS, 50 passed (about 75 s): the privilege reference unchanged; 0073 upgrades online, interrupted or not, as
a fresh database does.

Run:

```bash
cd backend && UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 8 \
  tests/apps/api \
  tests/apps/test_admission.py \
  tests/apps/test_admission_origins.py \
  tests/apps/test_admission_drafts.py \
  tests/apps/test_step_summary.py \
  tests/apps/test_step_summary_cost.py \
  tests/apps/test_workflow_summary.py \
  tests/core/runs
```

Expected: PASS, 708 passed (about 90 s).

- [ ] **Step 5: CodeQL**

Run CI's python analysis locally (the CLI CI pins, python-queries 1.8.12, CI's query filter) over `backend`.

Expected: no finding.

- [ ] **Step 6: The whole backend suite**

Ask the owner before running it: it takes long locally (4d-1b's took 54 minutes with 8 workers). CI runs it on the PR
in about 12 minutes. Run it on their word, as CI does (the CEL gates in a process of their own, the rest with `-n 8`),
and record every failure by name.

- [ ] **Step 7: Commit, and the final checkpoint**

```bash
git add frontend/src/api/openapi.json frontend/src/api/schema.d.ts docs/operations/runs.md
git commit -m "docs(runs): reading runs; the client regenerated (4e-1a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4e-1a, milestone 3 and the final checkpoint (<date>)` to the ledger. Record Task 7's commit and red and
green results, and every check of Steps 1–6 as it ran. Add the mid-slice rulings and "Nothing pushed". Commit it as
`docs(editor-4): 4e-1a final checkpoint`, with the trailer. The final whole-branch review follows. Nothing is pushed
without the owner's word.
