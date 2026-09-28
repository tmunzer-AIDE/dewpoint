# Engine 2a-3b: Scale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Runs at scale:
- loops over 100 items run in batches, as child workflows;
- `run_workflow` sub-flows and the workflow failure handler run as runs of their own;
- one exact iteration budget per logical run, shared through on-demand grants;
- continue-as-new happens at a quiescent point, with drain mode and a snapshot.

**Architecture:**
- **The budget.** `engine/runtime/budget.py` is a pure `Budget`: one execution's share of the run's iteration cap,
  what its outstanding children hold, and the needs waiting for more. It decides exactly when to grant, wait, ask
  the parent or refuse.
- **The scheduler** gains:
  - batched loops;
  - a batch-child mode over read-only copies of the loop's enclosing scopes;
  - pruning of settled iterations;
  - a JSON snapshot.
- **The interpreter** moves into `engine/runtime/execution.py`, which holds the drive loop and every unit. Two
  workflow types in `workflow.py` share it:
  - `RunGraph`: a run, a sub-flow or a failure handler;
  - `LoopBatch`: a slice of a loop.

  A child and its parent exchange budget through two signals.
- **Sub-runs** are rows in `runs` (migration 0009), which each child writes itself.
- **Continue-as-new** happens only when nothing but sleeping timers and the projection is outstanding. Draining
  starts nothing new until that point.

**Tech Stack:** Python 3.12 and `temporalio==1.33.0`, already locked. This plan uses:
- child workflows;
- external signals;
- continue-as-new;
- the time-skipping test server.

It also uses SQLAlchemy 2 async and Alembic on PostgreSQL 16, FastAPI, and pytest with Hypothesis. There's no new
dependency.

**Spec:** `docs/superpowers/specs/2026-09-25-engine-core-design.md`, revision 5.5:
- §6: loop batches, sub-flows, the failure handler, the iteration counter, continue-as-new;
- §7: golden histories;
- §8: sub-runs in `runs`;
- §10: tests.

Revision 5.5 records the decisions below. It lands in the same docs-only PR as this plan, so the spec and the plan
agree before implementation starts.

**Previous plan:** `docs/superpowers/plans/2026-09-27-engine-2a3a-interpreter-runs.md` (merged, PR #9, `3012f3f`).
Its "Handoff to 2a-3b" section lists what this plan consumes. The owner chose one plan for all of 2a-3b on
2026-09-27. 2a-3c (Worker Versioning, Compose, the two-build test, the CI replay gate, inline CEL) follows.

## How this plan was made

1. **Go/no-go experiments ran first** (next section), on the locked temporalio 1.33.0 and its time-skipping server.
2. **Every module was prototyped** in a scratch copy of `backend/` at `main` (`3012f3f`) until it passed its tests,
   `ruff`, `ruff format`, `mypy --strict` (134 source files) and `lint-imports` (10 contracts). The prototype's full
   suite gives 994 passed and 8 skipped (the Linux-only evaluator tests), against `main`'s 902 passed.
3. **The code blocks below are those files, verbatim.** Diffs to existing files were generated from the prototype.
   Two files change too much for a readable diff, so their tasks give them whole ("Replace … with"):
   - `scheduler.py` in Task 2;
   - `workflow.py` in Task 5.
4. **Each task was staged and checked on its own.** Stage *N* is `main` plus Tasks 1..*N*.
   - Every stage passed the static checks and the **whole** suite: 919, 928, 930, 932, 960, 961, 966 and 994
     passed, each with 8 skipped. Two first runs failed, and both re-runs passed:
     - one hit a timing flake in `tests/core/audit/test_anchor.py`, which fails about one run in three on `main` too;
     - one hit a cross-process test while I was rebuilding its stage directory.
   - Each task's own `Run:` commands were run as written, and their output matched each `Expected:` line.
   - Each task's first run was checked too: every task's tests fail as its "watch them fail" step says.
   - Stage 8 is byte-identical to the prototype.
   - Applying this plan's blocks and diffs to `main`, in order, reproduces the prototype exactly (0 mismatches).
5. **Staging reshaped two tasks:**
   - The new scheduler breaks 2a-3a's `workflow.py` at two call sites, so Task 2 carries a small bridge (decision 22)
     that Task 5 replaces.
   - `nodes.py`'s changes need the new interpreter, and the contracts between executions (`activities.py`) are
     first used there, so both moved to Task 5, where their tests are.
6. **Migration 0009 round-tripped** (upgrade, downgrade to 0008, upgrade) on a scratch `postgres:16-alpine`.
7. **Planning found and fixed four defects in its own prototype,** each test-first:
   - A replay depended on the workflow id. Batch ids came from the workflow id, and budget requests were named
     with `uuid4`. They now come from the run id and a counter (decision 5).
   - The opportunistic checkpoint never fired: quiescence was checked after new work had started. It's now checked
     before (decision 14).
   - A batch that failed as a workflow always failed its loop with `internal_error`, even when the batch said
     `version_unusable` (decision 4).
   - A loop past the run's cap would wait forever for budget under the bridged 2a-3a interpreter (decision 22).

8. **The owner's first review (2026-09-28) found three run-consistency gaps and a weak headroom gate.** Each is
   fixed test-first, with a regression at the stated boundary:
   - A sub-run could end before its row existed, when its version didn't load or it was cancelled while loading.
     It now writes its row before loading (decision 9).
   - A cancel while the failure handler ran left Temporal saying `cancelled` and the row saying `failed`. The end is
     now decided first, a cancel then cancels the handler instead, and the decided end stands (decision 8).
   - The run's iteration count left out its failure handler. The end is now recorded once the handler has settled
     (decision 8).
   - The headroom test didn't show that the cap was saturated when draining began, or bound the bytes. The
     snapshot now records what the drain waited for, and the test checks the units, retries, heartbeats, grants
     and bytes (decision 17).

   The owner also ruled on decisions 3, 8, 14 and 19. Ruling 8 adds `deadline_exceeded` to the ends that run a
   handler.

   Fixing those found three more, each fixed test-first:
   - The in-flight cap counted the projection as a unit (decision 2).
   - A drain began only when a unit happened to end, sometimes well past the threshold, with one unit already done
     (decision 14).
   - A snapshot of another format hung the run instead of failing it (decision 16).

   Two late-cancel windows were closed by construction, without a test. The test server can't hit either on purpose,
   because each is a single write:
   - a cancel during a sub-run's first row write was swallowed; it now ends the sub-run `cancelled` (decision 9);
   - the wait for the last budget signals could still be cancelled after the end was recorded; it's now shielded
     like the end's own write.

   The golden histories were recorded again, because the child's row and the handler's order change commands.

9. **The owner's second review (2026-09-28) found a lifecycle gap and asked for two tighter tests:**
   - Round 1 recorded the run's end before its handler's row existed. That left a window where no non-terminal run
     held the handler's closure, so a disabled workflow's handler could lose its CEL profile's evaluator (spec
     §4.5). The run's row now stays non-terminal until its handler has ended (decision 8). This is pinned by
     `test_a_failed_run_stays_non_terminal_until_its_failure_handler_has_ended`, which fails on round 1's order.
   - The headroom test now shows that every heartbeat came after draining began, not only that 240 happened
     (decision 17).
   - The handler-cancel test now asserts the usage the cancelled handler returns (decision 19). A bite check that
     drops that usage makes it fail with 1,000 (the whole grant) instead of 30.

   Staging caught a regression in the first version of the fix. It flushed a failed run's rows ahead of its end
   even when no handler was pinned, which changed that run's commands, so 2a-3a's `failed` history stopped
   replaying. The early flush now happens only when a handler runs.

   The golden histories were recorded again: the handler's order changes commands.

10. **Execution's checkpoint 1 (2026-09-28) found a premature refusal in the budget**, fixed test-first on
    `feat/engine-2a3b` and carried into this plan. The root refused its own filter while a child that was asking
    held enough unused to cover it. That child releases its grant only once it's answered and ends. A child now
    reports what it holds with its ask (`held`). When what asking children hold would cover a need, their asks are
    refused first, latest first, and the need waits (decision 10).
    - Four unit tests pin the rule (Task 1), and an end-to-end test pins it through a sub-flow (Task 5).
    - Task 5's budget signal carries `held`.
    - The golden histories were recorded again, because the signal's arguments changed.

    The re-review found the same refusal one level down. An asking child reported only its own unreserved budget,
    not what its asking children held. So with 10 in all, the root refused its 8 while its asking child's asking
    leaf held 6. The report is now the whole subtree's (decision 10). A nested unit test, a strengthened property
    and a nested end-to-end test pin it.

    That end-to-end test, run against the old budget, also found a hang in Task 5's interpreter. A run that ended
    waited for its cancelled sub-flow to report back, and a cancel of the run meanwhile cancelled the sub-flow a
    second time. Temporal refused the duplicate, and the run's workflow task could never complete. That wait is now
    shielded like the end's write (decision 18), and a deterministic test pins it (Task 5).

The stage counts above are on the plan's base, `3012f3f`. `main` later gained 2 tests with PR #10 (an audit fix
that shares no file with this plan), so a branch from today's `main` counts 2 more.

Not run during planning: CI.

## Go/no-go: Temporal children and continue-as-new (run 2026-09-27)

| # | Question | Result |
|---|---|---|
| 1 | Do child workflows report results, failures and cancels to the parent? | **Yes.** A child's result reaches the parent. An `ApplicationError`'s details reach it through `ChildWorkflowError`. Cancelling a child under `WAIT_CANCELLATION_COMPLETED` delivers the child's failure details. A parent cancelled while awaiting a child (`REQUEST_CANCEL`) sees a `ChildWorkflowError` that carries the child's details. |
| 2 | Can a child and its parent exchange grants by signal, deterministically? | **Yes.** The child signals the parent through an external handle, and the parent answers the same way. The round trip is ordered by the parent's history, and adds about 3 events to it, plus workflow tasks. |
| 3 | Does continue-as-new carry a snapshot and a timer's wake time? | **Yes.** A snapshot argument works, and `result()` follows the chain. A timer re-armed from its absolute wake time fires within 1 ms of it. The chain's runs are found by following `ContinuedAsNew.new_execution_run_id`, and each replays in the sandbox. |
| 4 | Does the test server ever suggest continue-as-new? | **No,** not even at 3,057 events. So drain mode is tested through event thresholds that are run inputs (`checkpoint_events`, `drain_events`). |
| 5 | What does history cost? | 500 activities, in batches of 20, added about 3,057 events and 248 KB: about 6 events per activity. |
| 6 | What does a parent see of a child that continues-as-new? | The child's handle resolves at the end of the chain, with the last run's result. Signals reach the continued child through both its child handle and an external handle. |
| 7 | Do signal handlers declared on a shared base class work for two workflow types? | **Yes.** Inherited `@workflow.signal` handlers are registered for each `@workflow.defn` subclass. |
| 8 | What does a cancelled unit that awaits a child get, when the child returns normally on cancel? | **The child's result:** `await` returns it. So a cancelled child reports its usage by returning (decision 19). |
| 9 | Does `except Exception` catch `ContinueAsNewError`? | **No.** It's a `BaseException`, so the run's error handlers never swallow a continue-as-new. |
| 10 | Do 2a-3a's golden histories replay against this interpreter? | **Yes, all 8.** The refactor changes nothing that a 2a-3a graph does. Stages 1–7 keep `ENGINE_ABI` 1, and Task 8 bumps it with the new histories (decision 20). |
| 11 | Does the test server report a terminated child to its parent? | **No.** The parent never learns of the termination, and its deadline fires instead. A terminate can't be tested on the test server. Review Focus 3 tests the same path through a child that fails as a workflow. |

**Verdict: go.**

## Decisions (recorded in spec revision 5.5)

Decisions 3, 8, 14 and 19 chose between readings of the spec. The owner ruled on them at the plan's first review
(2026-09-28), and each is marked. The others follow the spec closely.

### Children

1. **Two workflow types, one drive loop.** `engine/runtime/execution.py` holds `Execution`, which both types share:
   - the context;
   - the drive loop and every unit it runs;
   - the budget signals;
   - the projection.

   `workflow.py` holds the types themselves:
   - `RunGraph`, for a run, a sub-flow and a failure handler;
   - `LoopBatch`, for a slice of a loop.

   A batch isn't a run: it has no row, no outputs and no failure handler. It does run the same units, though, so
   it gets the same loop. Both types serve `dewpoint-engine`, and the worker registers both.
2. **How a child starts.** Every child starts through `child_options(id)`, which sets:
   - the engine queue;
   - `ParentClosePolicy.REQUEST_CANCEL`, so no child outlives its parent;
   - `ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED`, so a cancelled child reports back before the
     parent carries on, and its iterations are always counted;
   - `RetryPolicy(maximum_attempts=1)`, so it starts once.

   A child is a unit of the drive loop, so it counts toward the in-flight cap of 100 per execution (spec §6). A batch
   child has a cap of its own. The cap counts units only: the one projection in flight is beside them, as §6 says.
   2a-3a counted it, so a projection in flight took a unit's slot.
3. **Loop batches, one at a time** (the owner's ruling). A loop over more than 100 items (`INLINE_ITEMS`) is batched:
   `nodes.decide` sets `LoopStart.batch = 100`.
   - The loop hands out one `Batch` at a time. A child `LoopBatch` runs its items (100 at most) with the loop's own
     `concurrency` and `on_item_error`, in index order. The next batch starts when that one returns.
   - Iteration keys are the inline ones (`l:137`), because a batch's scheduler numbers its iterations from the
     batch's `offset`. A batch writes its rows into the run that holds the loop.
   - `collect`, `failures` and `on_item_error` behave as they do inline. `failures` lists absolute indexes, across
     batches. Under `stop`, the first failure stops its batch, and the batch's `stopped` fails the loop.

   Spec §6 says "batches of 100 within the parent's concurrency". Concurrency (1–10) bounds how many items run at
   once, and a batch already runs that many. Batches side by side would multiply it. Cost: a batch's slowest item
   holds back the next batch.
4. **What a batch reads and returns.** Its input (`BatchInput`) carries:
   - the loop's enclosing scopes as `OuterScope`s, outermost first. Each has the results of the outside steps that
     the body and `collect` read, and the enclosing loop's `item` and `index`. `Program.outer_reads` collects those
     steps from refs, templates, CEL projections and typed paths. When an expression reads `steps` whole, every
     result goes;
   - the trigger;
   - the variables. A loop body can't write variables (2a-1's `vars.write_in_loop`), so a batch only reads them;
   - the run's start time and its deadline.

   The batch's scheduler holds those scopes frozen, so it never changes them.

   It returns `BatchResult`:
   - `collected` and `failures`;
   - `stopped`: the failure that stopped the slice;
   - `end`: set when the run ended inside the batch (a `fail` or `stop` node, the deadline, a cancel);
   - `iterations`;
   - the sensitive values it learned.

   A `fail` or `stop` node inside a batch ends the whole run, as it would inline.

   A batch can also fail as a workflow:
   - its version doesn't load or compile (`version_unusable`);
   - a bug (`internal_error`);
   - it was terminated.

   Then its loop fails with that code. Its usage is unknown, so its whole grant is debited.
5. **Child ids that don't depend on the workflow id.**
   - A batch's id is `<run_id>/<loop step id>/<iteration key of the loop's scope>/batch:<start>`. The iteration key
     keeps a nested batched loop's ids distinct in each outer iteration.
   - A sub-run's id is its own run id (`workflow.uuid4()`), like a root run's.
   - A budget request is named by a counter in its execution.

   So a history replays under any workflow id. The replay test relies on this, and so will 2a-3c's two-build test.
6. **Sensitive values cross with the child.** A child starts out knowing the values its parent has learned
   (`Parent.secrets`). It returns what it learned (`RunResult.secrets`, `BatchResult.secrets`), and the parent
   masks those values from then on, as if it had learned them inline.
7. **Sub-flows.** A `run_workflow` step runs the version that publish pinned for that node, as a child `RunGraph`.
   The pin comes from `VersionData.subflow_version_ids`, which reads the version's `subflow_version_ids` column.
   - **Trigger:** the step's resolved `input`, which must be an object; anything else fails the step with
     `type_mismatch`.
   - **Its row** names the step's `workflow_id` (`SubflowStart.workflow_id`, passed as `RunInput.workflow_id`),
     because the child writes it before its version loads (decision 9).
   - **Inherited:** the parent's mode, CEL settings and absolute deadline.
   - **Depth:** publish refuses more than 5 levels. The interpreter checks again (`MAX_DEPTH`), and fails the step
     with `version_unusable`, as it does for a missing pin.
   - **Budget:** an initial grant of 1,000, per the spec.
   - **Ending:**
     - the sub-run's outputs are the step's output;
     - a sub-run that ends failed, cancelled or past its deadline fails the step, with its code and message, and the
       step's `on_error` applies;
     - a sub-flow that fails as a workflow (terminated) fails the step with `internal_error`, and its whole grant is
       debited.
8. **The failure handler** (the owner's ruling). It runs when a run ends `failed` or `deadline_exceeded` and its
   version pins a handler (`graph.settings.failure_handler`, pinned at publish). An explicit cancel isn't a
   failure, so a cancelled run runs none.
   - **Order.**
     1. The run's end is decided. Its rows land, but its own row stays non-terminal.
     2. The handler runs once, as a child `RunGraph`, and writes its own row first (decision 9).
     3. Once the handler has ended, the run's end is recorded, with the `ended_at` from step 1, counting the
        handler's iterations. The run's result counts them too.

     So from the run's start until its handler's row has ended, a non-terminal run holds the handler's closure, and
     with it the CEL profiles the handler pins: spec §4.5's running reference never lapses, even for a disabled
     workflow that nothing else references. The cost: a failed run shows `running` while its handler runs. A run
     whose version pins no handler records its end at once, with exactly 2a-3a's commands.
   - **A cancel while the handler runs** comes too late to change the run's end, which is already decided. The run
     cancels the handler, the handler reports back with its usage, and the run records the end it had: `failed` in
     Temporal and in its row. A root doesn't re-raise the cancel then. A cancel that arrives while the rows land,
     before the handler starts, means no handler runs.
   - Its trigger is `{run_id, workflow_id, version_id, error: {code, message}}`, masked as stored.
   - It gets a deadline of its own (`max_run_duration` from its start), because the run's may have passed.
   - It draws on the run's budget (an initial 1,000), and the run answers its requests while it waits.
   - Its end doesn't change the run's.
   - A failure handler's own failure runs no handler. A failed sub-flow runs the sub-flow's own handler.
   - A version that can't load or compile runs none, because the pin comes from the version.
9. **Sub-runs are runs.** A sub-flow's run and a failure handler's run each get a `runs` row. Migration 0009 adds:
   - the columns `kind` (`run`, `subflow` or `failure_handler`), `parent_run_id` (a foreign key), `parent_step_id`
     and `parent_iteration_key`;
   - the checks `runs_kind` and `runs_parent` (`(kind = 'run') = (parent_run_id IS NULL)`);
   - the index `runs_children`.

   The child writes its own row, as the worker role, with its first projection (`ProjectInput.start`,
   `ensure_run`, `ON CONFLICT DO NOTHING`). That happens before anything else, even its version's load, so every way
   it can end has a row to record the end: a version that doesn't load, a cancel while it loads. The row's workflow
   id comes from the parent (decisions 7, 8). The write is shielded. If a cancel arrives during it, the child
   records that and then ends `cancelled`, instead of carrying on. The worker role gains `INSERT` on `runs` for
   this, and row-level security still holds it to the tenant.

   A batch has no row: it writes into its loop's run.

   The API changes:
   - `GET /runs` lists top-level runs only;
   - `GET /runs/{id}` adds `kind` and `parent_run_id`, and `children` (each with `parent_step_id` and
     `parent_iteration_key`).

### One iteration budget per logical run

10. **`Budget`** (`engine/runtime/budget.py`) is pure and deterministic. It holds:
    - `total`: the cap at the root, or what a child was granted;
    - `used`;
    - `reserved`: what each outstanding child holds;
    - `waiting`: the needs, first in, first out;
    - `asking` and `refused`.

    A need names its requester (`LOCAL` or a child's workflow id), a key, `need` (at least) and `want` (up to). A
    child's need also carries `held`: what the child's subtree holds unused while it asks.
    - `take(n)` serves this execution's own need at once, when nothing waits ahead of it and it fits.
    - `start_child` reserves `min(initial, unreserved)`, or 0 when a need is waiting, so nothing jumps the queue.
    - `settle_child(used | None)` debits what the child used (at most its grant), or the whole grant when the child
      didn't say. It releases the rest and drops the child's waiting needs.
    - `decide()` serves the waiting needs in order:
      - a need that fits is granted, and a child gets up to its `want`;
      - otherwise it waits while another outstanding child, one that isn't itself asking, may still release budget;
      - otherwise a child execution asks its parent for its shortfall (`want = max(1,000, shortfall)`), one ask at
        a time. It reports what its subtree holds unused (`held`): its own unreserved budget, and what each of its
        asking children reported. It asks only once every other child is asking, and it answers nothing while it
        asks, so that's all it would release if it were refused and ended;
      - otherwise (at the root, or once refused), if other children that are asking hold enough to cover it, their
        asks are refused, latest first, until what they hold does. A child that asks releases what it holds only
        once it's answered and ends, so the need waits for them;
      - otherwise the need is refused.

    So a child asks only when its whole subtree is short. A need is refused only when nothing unused is left that
    could cover it, so the cap is exact: this is spec §6's "no premature rejection". Property tests check exactness
    and liveness.

    Execution's checkpoint 1 found the fourth rule missing. The root refused its own filter of 8 while a child held
    6 unused and asked for 5 more, and then refused the child too. Its re-review found the same refusal one level
    down: an asking child reported only its own unreserved budget, not what its asking child held. Five unit
    tests pin the rule, and the larger-needs property checks that the root refuses a need of its own only when the
    whole tree holds less unused. Two end-to-end tests pin it through sub-flows (Task 5).
11. **Grant signals.**
    - The child sends `request_budget(child, key, need, want, held)` to its parent.
    - The parent answers with `budget(key, granted)`.

    Both go through external handles by workflow id, so they reach a continued child at the end of its chain. The
    handlers only record. The drive loop serves them at its next turn, in the order they reached the history, so
    serving them is deterministic. Each send is a task. A send to a child that ended meanwhile is logged and
    dropped. The failure handler's wait serves budget too. A root never asks.
12. **Local needs: loop iterations and filters.**
    - An inline iteration takes 1 when it opens. If it can't, its loop waits (`LoopRun.waiting`) with a local need.
      The loop opens the iteration when the need is granted. When it's refused, the loop fails with
      `iteration_cap_exceeded`, after ending its in-flight iterations, as in 2a-3a.
    - A filter takes all its items at once (`need = want = n`). If it can't, its unit waits for the answer.
      A filter's need is all or nothing, so one larger than any single release waits for several children to
      settle. It's still refused only at the exact cap.
13. **Pruning.** A settled iteration's scope is dropped once its loop has taken its result. `take_settled` returns
    each settled step's result with it, because the scope may be gone before the step is projected. Only open
    scopes stay, so memory and the snapshot are bounded by what's in flight (2a-3a's deferred minor M7).

### Continue-as-new

14. **When.** Each turn of the drive loop checks, before any new unit starts:
    - **Drain mode** (the owner's ruling) begins when history reaches `drain_events` (4,000), or when Temporal
      suggests it. From then on, no new unit starts. This includes control nodes, which revision 5.4 let run:
      they're cheap to run after the continue, and the run reaches quiescence sooner. The drive loop also wakes when
      a drain is due, so drain mode begins at the first workflow task past the threshold, not when the next unit
      happens to end.
    - **Quiescent** means that every outstanding unit is a sleeping timer step or the projection, that the budget
      isn't asking the parent, and that no signal waits to be served. A plugin step between attempts (in backoff)
      is outstanding, because its attempt state isn't carried.
    - **Continue.** At a quiescent point, the run continues-as-new when history is past `checkpoint_events` (2,000),
      or when it's draining.

    `checkpoint_events` and `drain_events` are fields of `RunInput` and `BatchInput`, with the spec's values as
    defaults. So tests can drain early (go/no-go 4), and children inherit them. A child continues-as-new the same
    way, and its parent waits on the chain.
15. **How.**
    1. Sleeping timers stop; their wake times go into the snapshot.
    2. The projection in flight lands. Then every queued row, and every pending signal, is sent (`_flush`).
    3. Queued units go back to the scheduler (`give_back`).
    4. The run calls `workflow.continue_as_new(replace(start, snapshot=…))`.

    The continued run restores the snapshot, then re-arms each timer at its original wake time and the deadline
    clock at the original deadline.
16. **The snapshot** (`snapshot_format` 1) carries:
    - the scheduler:
      - open scopes, with their node and edge states and results;
      - loop runs, with their cursors, collected values, failures and running batch;
      - the ready, collect and batch queues;
      - the budget, with its reservations and waiting needs;
    - variables and learned secrets;
    - the run's start time and deadline;
    - timers, each with its scope key, step id, wake time, start time and CEL mode;
    - `drained`: when the drain began (`at`, the workflow's time), what it waited for (`units`, by kind:
      activities, children, timers and so on), and the history events and bytes it added, for the headroom test.

    It carries no rows, because they're flushed first. It has no yield accumulator either: that resets every
    workflow task. A snapshot of another format is read no further:
    - a run ends `internal_error` before anything runs;
    - a batch fails as a workflow, so its loop fails (decision 4).
17. **Headroom, measured.** The headroom test drains with the in-flight cap saturated, and checks that it was:
    - **Units.** The snapshot's `units` are exactly 90 activities and 10 children when draining begins:
      - 80 slow activities that heartbeat each second;
      - 10 activities that fail once and retry after the default 1 s backoff;
      - 10 sub-flows that ask for more budget once they're past a 1 s slow step.
    - **During the drain.** The root's history between the drain's first and last event holds all 10 retries and
      all 10 grants. All 240 of the slow activities' heartbeats come after the drain began: `testkit.slow` records
      each heartbeat's time, and the snapshot records when draining began. The test server shares the host's clock
      (a fresh server that hasn't skipped time), and the first heartbeat comes a second after its activity
      started.
    - **Bounds.** It asserts the spec's 1,000 events, and 512 KiB (`HEADROOM_BYTES`) of added history. Draining
      added 405–501 events and 98–131 KB across runs. The byte bound holds for this workload only. It's no guarantee
      for every payload, because payload sizes aren't enforced until 2b's claim check (decision 21).

### Ends, replay and limits

18. **Every end is recorded, children included** (2a-3a's decision 11).
    - A sub-run projects its own end.
    - `version_unusable` and `internal_error` end a sub-run as they end a run, and its step fails with that code.
    - A batch never ends the run itself. A `fail` or `stop` node, or the deadline, inside it comes back as `end`,
      and the parent applies it.
    - A batch that can't load its version fails as a workflow (a non-retryable `ApplicationError`), so its parent
      fails the loop instead of waiting forever.
    - A sub-run's row exists before anything can end it (decision 9).
    - An execution that ends waits for its cancelled children to report back. A cancel of the execution meanwhile
      doesn't reach them again: Temporal refuses a second cancel of the same child, and the workflow task could
      then never complete. The end already decided stands. (Found by checkpoint 1's re-review test.)
    - A failure handler never changes its run's end, and a cancel during it doesn't either (decision 8).
19. **A cancelled child returns its result** (the owner's ruling). Cancelling a run cancels its children, through
    `REQUEST_CANCEL` and `WAIT_CANCELLATION_COMPLETED`.
    - A child returns `cancelled`, with its usage and secrets, instead of ending as cancelled (go/no-go 8). So
      Temporal shows the child as completed, with a result that says `cancelled`, while its row says `cancelled`.
      `runs.md` says so. A test cancels a run while its failure handler waits after doing 30 iterations of work. It
      asserts that the handler's result, the run's result and the run's row all count those 30.
    - A root re-raises, and ends `cancelled`.
    - A cancelled unit stays outstanding (`("cancelled", n)`) until its child reports.
20. **`ENGINE_ABI` 2 and golden histories.** Task 8 bumps `ENGINE_ABI`, because batches, sub-flows and continue-as-new
    change the command sequence for graphs that used to fail with `not_supported`. It adds these scenarios:
    - `batches`;
    - `subflows`;
    - `failure_handler`;
    - `grants`;
    - `continue_as_new`, with `checkpoint_events` 60;
    - `drain`, with `drain_events` 15.

    The recorder now records every execution a scenario ran, breadth first: children and continued runs become
    `<name>--<n>.json`. The abi1 histories stay in the repo, and only their own build replays them (§7's gate). They
    also replay against this build (go/no-go 10).
21. **Payload limits.** Each of these travels as a Temporal payload, limited to 2 MiB until 2b's claim check:
    - a batch's input: its items, and the outside results the body reads;
    - a sub-flow's input;
    - a continue-as-new snapshot.

    `runs.md` says so.
22. **The Task 2 bridge.** Task 2's scheduler replaces `debit()` with a `Budget` and returns settled results with
    their instances. So Task 2 also adapts 2a-3a's `workflow.py`:
    - it builds the root budget explicitly;
    - it calls `answer_budget()` at each turn;
    - it takes the `(instance, result)` pairs;
    - it lets a filter `take` from the budget.

    Without `answer_budget()`, a loop past the cap would wait forever: nothing else would refuse its need. Task 2's
    worker test pins that the loop fails instead. Task 5 replaces the whole file.

## Global Constraints

- **Versions.**
  - Python ≥ 3.12, and `temporalio==1.33.0` as locked.
  - No new dependency, and no change to `pyproject.toml` or `uv.lock`.
- **Purity.** `dewpoint.engine` stays pure: no `dewpoint.core`, `dewpoint.apps`, `dewpoint.plugins`, SQLAlchemy,
  asyncpg, FastAPI or httpx. Only `engine/runtime/workflow.py` and `engine/runtime/execution.py` import
  `temporalio`. `engine/runtime/budget.py` imports nothing outside the standard library.
- **Workflow-code rules** (spec §6, and the `dewpoint.engine.runtime` import contract):
  - no `random`, `secrets`, `time`, `socket`, `subprocess`, `threading`, `os` or `structlog`;
  - time comes only from `workflow.now()`, and ids only from `workflow.uuid4()` or the run's own ids;
  - waits use `asyncio.sleep` (a durable timer), `workflow.wait` or `workflow.wait_condition`;
  - never iterate a set, and build every dict and list that reaches a command or the snapshot in a fixed order.
- **Limits.** Values are copied from spec §6 and §11; new constants are marked "new".
  - 100 units in flight per execution (`IN_FLIGHT_CAP`): steps, `collect`s, batches and sub-flows. Beside them,
    and not counted, is one projection.
  - 100 loop items inline (`INLINE_ITEMS`); larger loops run in batches of 100.
  - Iterations:
    - 100,000 iterations and filter items per logical run (`ITERATION_CAP`);
    - the refusal is `iteration_cap_exceeded`, with the message "This run reached its limit of 100,000 loop
      iterations." (`CAP_MESSAGE`).
  - Grants:
    - an initial grant of 1,000 for a sub-flow or a failure handler (`SUBFLOW_GRANT`, new);
    - a batch's own item count for a batch;
    - requests of at least 1,000 (`CHUNK`, new).
  - Sub-flows nest at most 5 deep (`MAX_DEPTH`, new; publish already enforces it).
  - Continue-as-new:
    - opportunistically from 2,000 history events (`CHECKPOINT_EVENTS`, new);
    - drain mode from 4,000, or when Temporal suggests it (`DRAIN_EVENTS`, new);
    - draining adds at most about 1,000 events (`HEADROOM_EVENTS` in the test). The test also bounds the bytes its
      workload's drain adds at 512 KiB (`HEADROOM_BYTES`): a bound for that workload, not a guarantee for every
      payload, whose size isn't enforced until 2b's claim check (decision 21).
  - `snapshot_format` 1 (`SNAPSHOT_FORMAT`, new); `ENGINE_ABI = 2` (Task 8).
- **Names:**
  - workflow types `RunGraph` and `LoopBatch`, both on `dewpoint-engine`;
  - signals `request_budget` and `budget`;
  - a batch's workflow id is `<run_id>/<loop step id>/<iteration key>/batch:<start>`;
  - a sub-run's workflow id is its run id;
  - run kinds are `run`, `subflow` and `failure_handler`.
- **Unchanged from 2a-3a:**
  - `CURRENT_CEL_PROFILE` is `cel-cpp-0.1.3/fn-1/cls-1`, and `LOCAL_CEL_PROFILE` stays `None`;
  - plugin steps run one activity execution per attempt, and the workflow alone decides retries and writes rows;
  - a reference default replaces a missing *and* a `null` value.
- **Tests:**
  - `tests/engine/**` needs no database.
  - `tests/apps/worker/**` starts Temporal's time-skipping test server; the owner approved its download.
  - Tests that monkeypatch a workflow module (`ITERATION_CAP`) run with `UnsandboxedWorkflowRunner`, because the
    sandbox imports its own copy (2a-3a's go/no-go 7).
  - Keep the suite's path order: the evaluator's fork tests must run before anything starts a Temporal worker, so
    no `pytest-randomly`.
- **Downloads and images:** none new. The Postgres test image and the Temporal test server are already approved.
- **Conventions:**
  - an SPDX header on every source file, and comments that explain why;
  - commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - run the checks and the commit in one `&&` chain;
  - never push, open a PR or enable auto-merge without the owner's word;
  - keep the branches `feat/foundations`, `spike/cel-evaluation`, `docs/engine-core-spec`, `feat/engine-2a1`,
    `docs/engine-2a2-plan`, `feat/engine-2a2`, `docs/engine-2a3a-plan` and `feat/engine-2a3a`;
  - leave the untracked `spikes/` alone.
- **Checks** (from `backend/`):
  - `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`;
  - tests: `uv run pytest -q <paths>`. The whole suite needs Docker for Postgres.

## Review Focus

These are the inputs and conditions most likely to bite a person using this, beyond what the spec names. Each has a
test in the task that owns the code.

1. **Cancelling a run while children are outstanding.** People cancel runs. A sub-flow and a batch each end
   cancelled and report back before the run ends; nothing is terminated, and the sub-run's row says `cancelled`.
   (Task 5: `test_cancelling_a_run_cancels_its_children_and_each_reports_back`)
2. **A batched loop inside a loop.** Batch ids name the enclosing iteration, so two outer iterations run their own
   batches side by side, with no id clash and the right iteration keys.
   (Task 5: `test_a_batched_loop_inside_a_loop_runs_its_own_batches_per_iteration`)
3. **A child that ends without reporting** (an operator terminates it, or it fails as a workflow). Its step or loop
   fails with the child's code, the run carries on under the error policy, and the child's whole grant stays
   counted. The time-skipping server never reports a termination to the parent (go/no-go 11), so the test uses a
   batch whose version stops compiling. (Task 5:
   `test_a_batch_that_fails_as_a_workflow_fails_its_loop_and_its_whole_grant_stays_used`)
4. **A sub-flow of a sub-flow that needs more than both grants.** The inner filter asks its parent, which asks the
   root, and the run succeeds with the exact count. (Task 5: `test_a_sub_flow_of_a_sub_flow_asks_up_the_chain`)
5. **A batched loop inside a sub-flow.** Its rows land in the sub-run, not the root run, and the root counts its
   iterations. (Task 5: `test_a_batched_loop_in_a_sub_flow_writes_into_the_sub_run`)

## File structure

```
backend/src/dewpoint/engine/runtime/
  budget.py        one execution's share of the run's iteration cap: grants, waits, asks, refusals   Task 1 (new)
  scheduler.py     + batched loops, batch-child mode, pruning, the snapshot, Budget for debit()       Task 2 (replace)
  workflow.py      bridged to the new scheduler (Task 2); RunGraph and LoopBatch (Task 5);
                   continue-as-new (Task 7)                                                            Tasks 2, 5, 7
  program.py       + pinned sub-flows and failure handler, outer_reads(loop)                          Task 3
  activities.py    + Parent, BatchInput/Result, RunStart, VersionData pins, signal names (Task 5);
                   thresholds and the snapshot field (Task 7)                                          Tasks 5, 7
  nodes.py         batched LoopStart, SubflowStart; not_supported removed                              Task 5
  execution.py     Execution: the drive loop, units, children, budget signals, projection (Task 5);
                   continue-as-new (Task 7)                                                            Tasks 5 (new), 7
  build.py         ENGINE_ABI = 2                                                                      Task 8
backend/migrations/versions/0009_subruns.py   runs.kind and parent columns, checks, index, worker INSERT  Task 4 (new)
backend/src/dewpoint/core/models/runs.py      RUN_KINDS and the columns                               Task 4
backend/src/dewpoint/core/runs/service.py     ensure_run, children; list_runs lists top-level runs    Task 4
backend/src/dewpoint/apps/worker/main.py      the worker runs LoopBatch too                           Task 5
backend/src/dewpoint/apps/worker/store.py     version pins; a sub-run's row with its first projection  Task 6
backend/src/dewpoint/apps/api/routes/runs.py  kind, parent_run_id, children                           Task 6
backend/tests/engine/runtime/     test_budget.py (new, Task 1); test_scheduler*.py (Task 2);
                                  test_program.py (Task 3); test_nodes.py (Task 5)
backend/tests/core/runs/test_service.py       sub-runs                                                Task 4
backend/tests/apps/worker/        test_run_graph_policies.py (Tasks 2, 5); harness.py, test_main.py,
                                  test_run_graph_children.py (new) (Task 5); test_worker_db.py (Task 6);
                                  test_run_graph_continue.py (new, Task 7)
backend/tests/support/plugins/testkit.py      (modify) `testkit.slow` records its heartbeats' times      Task 7
backend/tests/engine/replay/      scenarios, recorder, replay test, dewpoint-0.1.0+abi2/ histories    Task 8
docs/operations/runs.md                                                                               Task 8
(spec revision 5.5 lands with this plan in the docs PR, before Task 1)
```

## Suggested checkpoints (the owner's milestone reviews)

1. **After Task 3:** the deterministic core, with no new Temporal code: the budget, the scheduler with batches and
   its snapshot (and the bridge that keeps 2a-3a's interpreter running on it), and the program's pins and outer
   reads.
2. **After Task 6:** children end to end: the storage, the new interpreter (batches, sub-flows, the failure handler,
   grants), and sub-runs in the database and the API.
3. **After Task 8:** continue-as-new with drain mode, the golden histories and the docs. Then the whole-branch
   review.

## Branching

As in 2a-3a:
1. This plan and spec revision 5.5 land in a docs-only PR from `main`, on the branch `docs/engine-2a3b-plan`.
2. After it merges, implementation starts on `feat/engine-2a3b` from the updated `main`.

---

### Task 1: The iteration budget

One execution's share of the run's iteration cap (decision 10). It's pure: no Temporal and no I/O. The scheduler
(Task 2) and the interpreter (Task 5) drive it. The property tests check that the cap is exact: a need is refused
only when nothing unused is left anywhere. They also check liveness: no need waits forever once every child has
settled.

**Files:**
- Create: `backend/src/dewpoint/engine/runtime/budget.py`
- Create: `backend/tests/engine/runtime/test_budget.py`

**Interfaces:**
- Consumes: nothing (the standard library only).
- Produces (`dewpoint.engine.runtime.budget`):
  - `CHUNK = 1_000` and `LOCAL = ""` (the requester of an execution's own needs);
  - `Need(requester: str, key: str, need: int, want: int, held: int = 0)`, `Answer(need: Need, granted: int)`
    and `Ask(need: int, want: int, held: int = 0)`, all frozen dataclasses. `held` is what an asking child's
    subtree holds unused, which it reports with its ask: its own unreserved budget and what its asking children
    reported;
  - `Budget(total: int, root: bool, used=0, reserved: dict[str, int]={}, waiting: list[Need]=[], asking=False, refused=False)`,
    with:
    - the property `unreserved -> int`;
    - `take(n) -> bool`;
    - `request(need) -> None`;
    - `start_child(child, initial) -> int` (the grant);
    - `settle_child(child, used: int | None) -> None`;
    - `answered(granted) -> None`;
    - `decide() -> tuple[list[Answer], Ask | None]`;
    - `to_json() -> dict[str, Any]` and `Budget.from_json(data) -> Budget`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/engine/runtime/test_budget.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The iteration budget's grants (spec §6, "One iteration counter per logical run"): exact, and never stuck."""

from dataclasses import dataclass, field

from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.runtime.budget import CHUNK, LOCAL, Answer, Ask, Budget, Need


def local(key: str, n: int) -> Need:
    return Need(LOCAL, key, n, n)


def test_own_needs_are_served_in_order_while_the_budget_lasts() -> None:
    b = Budget(10, root=True)
    assert b.take(4) and b.take(6) and not b.take(1)
    assert (b.used, b.unreserved) == (10, 0)


def test_a_child_gets_its_initial_grant_and_releases_what_it_left() -> None:
    b = Budget(100, root=True)
    assert b.start_child("c", 30) == 30 and b.unreserved == 70
    b.settle_child("c", 12)
    assert (b.used, b.unreserved, b.reserved) == (12, 88, {})


def test_a_child_that_never_reports_is_debited_its_whole_grant() -> None:
    b = Budget(100, root=True)
    b.start_child("c", 30)
    b.settle_child("c", None)
    assert b.used == 30


def test_a_short_child_asks_its_parent_for_its_shortfall_up_to_a_chunk() -> None:
    b = Budget(5, root=False)
    assert b.take(5) and not b.take(3)
    b.request(local("loop", 3))
    answers, ask = b.decide()
    assert (answers, ask, b.asking) == ([], Ask(3, CHUNK), True)
    assert b.decide() == ([], None)  # one Ask at a time
    b.answered(CHUNK)
    answers, ask = b.decide()
    assert answers == [Answer(local("loop", 3), 3)] and ask is None and b.unreserved == CHUNK - 3


def test_the_parent_grants_up_to_the_chunk_from_what_it_has() -> None:
    root = Budget(50, root=True)
    root.start_child("c", 10)
    root.request(Need("c", "r1", 5, CHUNK))
    assert root.decide() == ([Answer(Need("c", "r1", 5, CHUNK), 40)], None)
    assert root.reserved == {"c": 50} and root.unreserved == 0


def test_a_need_waits_while_another_child_may_release_budget() -> None:
    root = Budget(20, root=True)
    root.start_child("busy", 10)
    root.start_child("idle", 10)
    root.request(Need("busy", "r1", 5, CHUNK))
    assert root.decide() == ([], None)  # `idle` holds 10 and isn't asking
    root.settle_child("idle", 2)
    assert root.decide() == ([Answer(Need("busy", "r1", 5, CHUNK), 8)], None)


def test_a_need_is_refused_only_when_no_other_child_can_release_anything() -> None:
    root = Budget(20, root=True)
    root.start_child("a", 10)
    root.start_child("b", 10)
    root.request(Need("a", "r1", 5, CHUNK))
    root.request(Need("b", "r1", 5, CHUNK))
    # both are asking, so neither can release anything, and nothing is left: `a` is refused. `b` then waits for
    # `a`, which is no longer asking and will settle, and is refused once `a` has released nothing.
    answers, ask = root.decide()
    assert [(a.need.requester, a.granted) for a in answers] == [("a", 0)] and ask is None
    root.settle_child("a", 10)
    answers, _ = root.decide()
    assert [(a.need.requester, a.granted) for a in answers] == [("b", 0)]


def test_a_refused_child_waits_for_its_own_children_and_never_asks_again() -> None:
    mid = Budget(10, root=False)
    mid.start_child("leaf", 10)
    mid.request(local("loop", 1))
    assert mid.decide() == ([], None)  # `leaf` may release
    mid.request(Need("leaf", "r1", 1, CHUNK))  # now the leaf is short too: the subtree is short
    assert mid.decide() == ([], Ask(1, CHUNK))
    mid.answered(0)
    answers, ask = mid.decide()
    assert [a.granted for a in answers] == [0, 0] and ask is None and mid.refused


def test_a_feasible_need_waits_for_an_asking_child_that_holds_enough_and_is_refused_first() -> None:
    """Checkpoint-1 review: the root's filter needs 8 and has 4. Child `a` holds 6 unused and asks for 5 more. The
    filter could have 8 once `a` releases its 6, which it does only once it's answered and ends. So `a` is refused,
    and the filter waits for it. Before, both were refused."""
    root = Budget(10, root=True)
    assert root.start_child("a", 6) == 6
    root.request(local("filter", 8))
    root.request(Need("a", "r1", 5, CHUNK, held=6))
    assert root.decide() == ([Answer(Need("a", "r1", 5, CHUNK, held=6), 0)], None)
    root.settle_child("a", 0)  # refused, `a` ends without using its grant
    assert root.decide() == ([Answer(local("filter", 8), 8)], None) and root.used == 8


def test_an_asking_child_that_holds_nothing_is_not_waited_for() -> None:
    root = Budget(10, root=True)
    root.start_child("a", 6)
    root.request(local("filter", 8))
    root.request(Need("a", "r1", 5, CHUNK, held=0))  # `a` used its 6
    answers, _ = root.decide()
    assert [(x.need.requester, x.granted) for x in answers] == [(LOCAL, 0), ("a", 0)]  # nothing could cover either


def test_only_as_many_asking_children_are_refused_as_the_need_takes_latest_first() -> None:
    root = Budget(20, root=True)
    root.start_child("a", 6)
    root.start_child("b", 6)
    root.request(local("filter", 12))  # 8 free
    root.request(Need("a", "r1", 5, CHUNK, held=6))
    root.request(Need("b", "r1", 5, CHUNK, held=6))
    answers, _ = root.decide()
    assert [(x.need.requester, x.granted) for x in answers] == [("b", 0)]  # `b`'s 6 is enough, and it asked last
    root.settle_child("b", 0)
    answers, _ = root.decide()
    assert [(x.need.requester, x.granted) for x in answers] == [(LOCAL, 12), ("a", 0)]


def test_a_refused_child_refuses_its_own_asking_children_before_its_own_need() -> None:
    mid = Budget(10, root=False)
    mid.start_child("leaf", 6)
    mid.request(local("filter", 8))
    mid.request(Need("leaf", "r1", 5, CHUNK, held=6))
    assert mid.decide() == ([], Ask(4, CHUNK, 10))  # it asks its parent first, holding its 4 and its leaf's 6
    mid.answered(0)
    answers, _ = mid.decide()
    assert [(x.need.requester, x.granted) for x in answers] == [("leaf", 0)]  # the leaf's 6 can cover the filter
    mid.settle_child("leaf", 1)
    assert mid.decide() == ([Answer(local("filter", 8), 8)], None)


def test_an_asking_child_reports_what_its_asking_children_hold_too() -> None:
    """Checkpoint-1 re-review: the root has 10 and grants 6 to `mid`, which grants all 6 to `leaf`. The root needs 8,
    `mid` 7 and `leaf` 8. `leaf` asks, holding 6. `mid` holds nothing itself, but its asking leaf's 6 is released if
    they're both refused, so it reports 6. The root refuses `mid`'s ask, and its 8 waits; the nested needs are then
    refused, all 10 come back, and the root's 8 is granted. Before, `mid` reported 0, and the root refused its 8 while
    the whole tree held 10 unused."""
    root, mid, leaf = Budget(10, root=True), Budget(6, root=False), Budget(6, root=False)
    assert root.start_child("mid", 6) == 6 and mid.start_child("leaf", 6) == 6
    leaf.request(local("filter", 8))
    answers, leaf_ask = leaf.decide()
    assert (answers, leaf_ask) == ([], Ask(2, CHUNK, 6))
    assert leaf_ask is not None
    mid.request(local("filter", 7))
    mid.request(Need("leaf", "1", leaf_ask.need, leaf_ask.want, leaf_ask.held))
    answers, mid_ask = mid.decide()
    assert (answers, mid_ask) == ([], Ask(7, CHUNK, 6))  # nothing of its own, but its asking leaf holds 6
    assert mid_ask is not None
    root.request(local("filter", 8))
    root.request(Need("mid", "1", mid_ask.need, mid_ask.want, mid_ask.held))
    answers, _ = root.decide()
    assert [(a.need.requester, a.granted) for a in answers] == [("mid", 0)]  # the root's 8 waits for mid's subtree
    mid.answered(0)
    answers, _ = mid.decide()
    assert [(a.need.requester, a.granted) for a in answers] == [(LOCAL, 0), ("leaf", 0)]  # 7 can't come from 6
    leaf.answered(0)
    assert leaf.decide() == ([Answer(local("filter", 8), 0)], None)
    mid.settle_child("leaf", leaf.used)  # the leaf ends, having used nothing
    root.settle_child("mid", mid.used)  # and so does mid
    assert root.decide() == ([Answer(local("filter", 8), 8)], None)


def test_no_premature_rejection_one_busy_child_among_ten_takes_nearly_everything() -> None:
    """Spec §10: with 10 child slots and one busy child, that child can use nearly the whole budget."""
    cap = 100_000
    root = Budget(cap, root=True)
    for i in range(10):
        root.start_child(f"c{i}", 100)
    busy = 100
    for request in range(1, 1_000):
        root.request(Need("c0", str(request), 1, CHUNK))
        answers, _ = root.decide()
        if not answers:
            break  # the others may still release what they hold: the request waits for them
        busy += answers[0].granted
    assert busy == cap - 900
    for i in range(1, 10):
        root.settle_child(f"c{i}", 1)  # the idle ones used 1 each and release the rest
    answers, _ = root.decide()
    busy += answers[0].granted
    assert busy == cap - 9


def test_the_state_round_trips_through_json() -> None:
    b = Budget(100, root=False, used=3, reserved={"c": 4}, waiting=[Need("c", "r", 1, CHUNK, held=2)], asking=True)
    assert Budget.from_json(b.to_json()) == b


# --- a simulated tree of executions ------------------------------------------------------------------------------


@dataclass
class Execution:
    name: str
    budget: Budget
    parent: "Execution | None" = None
    depth: int = 0
    children: list["Execution"] = field(default_factory=list)
    pending: dict[str, int] = field(default_factory=dict)  # own needs waiting for an answer
    served: int = 0  # own needs served
    done: bool = False
    counter: int = 0


@dataclass
class Tree:
    cap: int
    root: Execution
    everyone: list[Execution]
    mail: list[tuple[str, Execution, object]] = field(default_factory=list)  # (kind, to, payload)
    refusals: list[tuple[int, int]] = field(default_factory=list)  # (need, unused anywhere at that moment)
    root_refusals: list[tuple[int, int]] = field(default_factory=list)  # the root's own, likewise

    def served(self) -> int:
        return sum(e.served for e in self.everyone)

    def settle(self, e: Execution) -> None:
        answers, ask = e.budget.decide()
        for a in answers:
            if a.need.requester == LOCAL:
                n = e.pending.pop(a.need.key)
                if a.granted:
                    e.served += n
                else:
                    self.refusals.append((n, self.cap - self.served()))
                    if e.parent is None:
                        self.root_refusals.append((n, self.cap - self.served()))
            else:
                child = next(c for c in e.children if c.name == a.need.requester)
                self.mail.append(("answer", child, a.granted))
        if ask is not None and e.parent is not None:
            e.counter += 1
            self.mail.append(("ask", e.parent, Need(e.name, str(e.counter), ask.need, ask.want, ask.held)))

    def deliver(self, i: int) -> None:
        kind, to, payload = self.mail.pop(i)
        if kind == "ask":
            assert isinstance(payload, Need)
            to.budget.request(payload)
        elif kind == "answer":
            assert isinstance(payload, int)
            to.budget.answered(payload)
        else:  # a child ended
            assert isinstance(payload, tuple)
            name, used = payload
            to.budget.settle_child(name, used)
        self.settle(to)


def run(data: st.DataObject, cap: int, unit: bool) -> Tree:
    root = Execution("root", Budget(cap, root=True))
    tree = Tree(cap, root, [root])
    for _ in range(data.draw(st.integers(10, 120))):
        live = [e for e in tree.everyone if not e.done]
        moves = ["need", "child", "finish"] + (["mail"] if tree.mail else [])
        move = data.draw(st.sampled_from(moves))
        if move == "mail":
            tree.deliver(data.draw(st.integers(0, len(tree.mail) - 1)))
            continue
        e = data.draw(st.sampled_from(live))
        if move == "need" and not e.pending:
            n = 1 if unit else data.draw(st.integers(1, 30))
            if e.budget.take(n):
                e.served += n
            else:
                e.counter += 1
                key = f"own{e.counter}"
                e.pending[key] = n
                e.budget.request(Need(LOCAL, key, n, n))
                tree.settle(e)
        elif move == "child" and e.depth < 2 and len(e.children) < 3 and not e.pending:
            name = f"{e.name}.{len(e.children)}"
            grant = e.budget.start_child(name, data.draw(st.integers(0, 40)))
            child = Execution(name, Budget(grant, root=False), e, e.depth + 1)
            e.children.append(child)
            tree.everyone.append(child)
        elif move == "finish" and e is not root and not e.pending and all(c.done for c in e.children):
            if not any(m[1] is e for m in tree.mail) and not e.budget.asking:
                e.done = True
                assert e.parent is not None
                tree.mail.append(("ended", e.parent, (e.name, e.budget.used)))
        assert tree.served() <= cap, "the cap was exceeded"
    return tree


def finish(tree: Tree) -> None:
    """Let everything settle: deliver the mail, and end each execution that's no longer waiting."""
    for _ in range(10_000):
        if tree.mail:
            tree.deliver(0)
            continue
        idle = [
            e
            for e in tree.everyone
            if not e.done
            and e is not tree.root
            and not e.pending
            and not e.budget.asking
            and all(c.done for c in e.children)
        ]
        if not idle:
            break
        e = idle[-1]
        e.done = True
        assert e.parent is not None
        tree.mail.append(("ended", e.parent, (e.name, e.budget.used)))
    stuck = [e.name for e in tree.everyone if e.pending]
    assert not stuck, f"needs never answered: {stuck}"
    assert tree.served() <= tree.cap


@settings(max_examples=300, deadline=None)
@given(st.data())
def test_one_at_a_time_needs_are_refused_only_when_nothing_is_left(data: st.DataObject) -> None:
    """With loop iterations (needs of 1), the cap is exact: a need is refused only when nothing unused is left in the
    whole tree, and no need waits forever."""
    tree = run(data, cap=data.draw(st.integers(5, 60)), unit=True)
    finish(tree)
    for need, unused in tree.refusals:
        assert unused < need, f"a need of {need} was refused with {unused} unused"


@settings(max_examples=300, deadline=None)
@given(st.data())
def test_larger_needs_never_pass_the_cap_and_never_wait_forever(data: st.DataObject) -> None:
    """Needs of any size: all or nothing, so two needs can compete for the same budget, and one is refused while
    the other holds it. But the root refuses a need of its own only when the whole tree holds less unused: what
    asking children hold, all the way down, counts (checkpoint-1 re-review)."""
    tree = run(data, cap=data.draw(st.integers(5, 200)), unit=False)
    finish(tree)
    for need, unused in tree.root_refusals:
        assert unused < need, f"the root refused a need of {need} with {unused} unused in the tree"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/runtime/test_budget.py`
Expected: a collection error, `ModuleNotFoundError: No module named 'dewpoint.engine.runtime.budget'`.

- [ ] **Step 3: Implement the budget**

Create `backend/src/dewpoint/engine/runtime/budget.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""One execution's share of the run's iteration budget (spec §6, "One iteration counter per logical run").

The root execution holds the cap. A child (a loop batch, a sub-flow) holds what its parent granted it: an initial
grant when it starts, and more on demand. Needs are served in the order they arrive: this execution's own (an inline
iteration, a filter's items) and its children's requests.

A need the unreserved budget can't cover waits while another outstanding child may still release budget: a child
that isn't itself asking. Only then does a child execution ask its parent, for its shortfall (and up to a chunk of
1,000, so it asks rarely), reporting what its subtree holds unused meanwhile: its own unreserved budget and what
its asking children reported. So a child asks only when its whole subtree is short. A child that asks holds its
unused budget until it's answered and ends: when what asking children hold would cover a need, their asks are
refused first, latest first, and the need waits for them to release it. A need is refused only when nothing unused
is left that could cover it: the cap is exact.

It is pure and deterministic, and its state is plain data, carried through continue-as-new."""

from dataclasses import dataclass, field
from typing import Any

CHUNK = 1_000  # a child asks for at least this much, so it rarely asks
LOCAL = ""  # the requester of this execution's own needs


@dataclass(frozen=True)
class Need:
    requester: str  # LOCAL, or the child's workflow id
    key: str  # the requester's own name for it: a child's request id, or the scheduler's unit
    need: int  # at least this much, or nothing
    want: int  # up to this much: a child's chunk; a local need wants exactly `need`
    held: int = 0  # what a child's subtree holds unused while it asks: released if it's refused and ends


@dataclass(frozen=True)
class Answer:
    need: Need
    granted: int  # 0: refused


@dataclass(frozen=True)
class Ask:
    """What this execution asks its parent for: its shortfall, up to a chunk. `held` is what it holds unused meanwhile,
    which its parent can have if it refuses the ask."""

    need: int
    want: int
    held: int = 0


@dataclass
class Budget:
    total: int  # what this execution may spend: the cap at the root, its grants in a child
    root: bool
    used: int = 0  # its own needs served, and what its settled children used
    reserved: dict[str, int] = field(default_factory=dict)  # outstanding child -> what it was granted so far
    waiting: list[Need] = field(default_factory=list)
    asking: bool = False  # an Ask is out and unanswered
    refused: bool = False  # the parent refused: only this execution's own children can help now

    @property
    def unreserved(self) -> int:
        return self.total - self.used - sum(self.reserved.values())

    def take(self, n: int) -> bool:
        """This execution's own need, served now when nothing waits ahead of it and it fits."""
        if self.waiting or n > self.unreserved:
            return False
        self.used += n
        return True

    def request(self, need: Need) -> None:
        self.waiting.append(need)

    def start_child(self, child: str, initial: int) -> int:
        """A child starts: reserve its initial grant from the unreserved budget. Nothing is taken ahead of a waiting
        need, so a child may start with 0 and ask."""
        grant = 0 if self.waiting else max(0, min(initial, self.unreserved))
        self.reserved[child] = grant
        return grant

    def settle_child(self, child: str, used: int | None) -> None:
        """A child ended: debit what it used (all it was granted when it didn't say), and release the rest. Needs it
        left waiting are dropped: nothing will read their answers."""
        granted = self.reserved.pop(child, 0)
        self.used += granted if used is None else min(max(used, 0), granted)
        self.waiting = [n for n in self.waiting if n.requester != child]

    def answered(self, granted: int) -> None:
        """The parent answered this execution's Ask."""
        self.asking = False
        self.total += granted
        if granted == 0:
            self.refused = True

    def decide(self) -> tuple[list[Answer], Ask | None]:
        """Serve the waiting needs in order, as far as the budget goes. Returns the answers, and an Ask for the
        parent when this execution must ask (at most one at a time)."""
        answers: list[Answer] = []
        while self.waiting:
            head = self.waiting[0]
            free = self.unreserved
            if head.need <= free:
                granted = head.need if head.requester == LOCAL else min(head.want, free)
                if head.requester == LOCAL:
                    self.used += granted
                else:
                    self.reserved[head.requester] = self.reserved.get(head.requester, 0) + granted
                answers.append(Answer(head, granted))
                self.waiting.pop(0)
                continue
            if self._may_release(head):
                break  # another child may still release budget: wait for it
            if not self.root and not self.refused:
                if self.asking:
                    break
                self.asking = True
                shortfall = head.need - max(free, 0)
                return answers, Ask(shortfall, max(CHUNK, shortfall), self._held())
            if self._refuse_asking(head, free, answers):
                break  # children that were asking hold enough: refused, they end and release it; wait for them
            answers.append(Answer(head, 0))
            self.waiting.pop(0)
        return answers, None

    def _refuse_asking(self, head: Need, free: int, answers: list[Answer]) -> bool:
        """Other children that are asking hold what they report (`held`) until they end, and they end only once
        answered. When what they hold would cover the head, refuse their needs, latest first, until it does: they
        release it when they end, and the head waits for them. Otherwise refuse none, and the head is refused."""
        chosen: list[str] = []
        held = 0
        for n in reversed(self.waiting):
            if free + held >= head.need:
                break
            if n.requester not in (LOCAL, head.requester) and n.requester not in chosen and n.held > 0:
                chosen.append(n.requester)
                held += n.held
        if free + held < head.need:
            return False
        answers.extend(Answer(n, 0) for n in self.waiting if n.requester in chosen)
        self.waiting = [n for n in self.waiting if n.requester not in chosen]
        return True

    def _held(self) -> int:
        """What this execution's subtree holds unused as it asks: its own unreserved budget, and what each of its
        asking children reported. It asks only once every other child is asking (see `_may_release`), and it
        answers nothing while it asks, so that's all it would release if it were refused and ended."""
        return max(self.unreserved, 0) + sum(n.held for n in self.waiting if n.requester != LOCAL)

    def _may_release(self, head: Need) -> bool:
        """Whether an outstanding child other than the requester may still release budget: one that isn't asking."""
        asking = {n.requester for n in self.waiting}
        return any(child != head.requester and child not in asking for child in self.reserved)

    def to_json(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "root": self.root,
            "used": self.used,
            "reserved": dict(self.reserved),
            "waiting": [[n.requester, n.key, n.need, n.want, n.held] for n in self.waiting],
            "asking": self.asking,
            "refused": self.refused,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Budget":
        return cls(
            total=int(data["total"]),
            root=bool(data["root"]),
            used=int(data["used"]),
            reserved={str(k): int(v) for k, v in data["reserved"].items()},
            waiting=[Need(str(r), str(k), int(n), int(w), int(h)) for r, k, n, w, h in data["waiting"]],
            asking=bool(data["asking"]),
            refused=bool(data["refused"]),
        )


__all__ = ["CHUNK", "LOCAL", "Answer", "Ask", "Budget", "Need"]
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest -q tests/engine/runtime/test_budget.py`
Expected: 17 passed.

- [ ] **Step 5: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine \
  && git add src/dewpoint/engine/runtime/budget.py tests/engine/runtime/test_budget.py \
  && git commit -m "feat(engine): an exact iteration budget per logical run, with on-demand grants" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The scheduler: budget, batched loops, batch children, pruning and the snapshot

The scheduler draws iterations from a `Budget` (Task 1) instead of its own counter:
- an iteration that can't be debited waits for budget, and its loop fails only when the need is refused
  (decision 12);
- a loop over more than 100 items hands out one `Batch` at a time and takes back each `BatchOutcome` (decision 3);
- a batch child's scheduler runs one slice of a loop over frozen copies of the loop's enclosing scopes (decision 4);
- settled iterations are pruned once collected (decision 13);
- the whole state round-trips through JSON, for continue-as-new (decision 16).

The file changes too much for a readable diff, so this task gives it whole. The property tests now take snapshots
at random points, with work still queued, and run some loops in batches whose children report random outcomes.

2a-3a's `workflow.py` uses two things that change here: `debit()` and the bare instances from `take_settled()`.
So this task also bridges it (decision 22). A new worker test pins that a loop past the run's cap fails, rather
than waiting forever for budget. Task 5 replaces the whole file.

**Files:**
- Replace: `backend/src/dewpoint/engine/runtime/scheduler.py`
- Modify: `backend/src/dewpoint/engine/runtime/workflow.py` (the bridge)
- Modify: `backend/tests/engine/runtime/test_scheduler.py`, `backend/tests/engine/runtime/test_scheduler_properties.py`
- Create: `backend/tests/engine/runtime/test_scheduler_batches.py`
- Modify: `backend/tests/apps/worker/test_run_graph_policies.py` (the run-cap test)

**Interfaces:**
- Consumes: from Task 1, `Budget`, `Need`, `Answer`, `Ask`, `LOCAL`; from 2a-3a, `Program`, `Step`, `BODY`, `DONE`,
  `ERROR_PORT`.
- Produces (`dewpoint.engine.runtime.scheduler`), beyond 2a-3a's names:
  - `CAP_MESSAGE` and `SNAPSHOT_FORMAT = 1`;
  - `Failure.from_json(data)`, `RunEnd.to_json()` and `RunEnd.from_json(data)`;
  - `Batch(loop: Instance, start: int, items: list)`;
  - `BatchOutcome(collected: list, failures: list[dict], stopped: Failure | None = None)`;
  - `OuterScope(key: ScopeKey, results: dict[str, dict], item=None, index: int | None = None)`;
  - `Scope.frozen`;
  - `LoopRun.offset`, `.batch`, `.running_batch` and `.waiting`.
  - `Scheduler(program, *, budget: Budget | None = None)`. Without a budget, it builds a root budget of
    `ITERATION_CAP`. It has:
    - `budget`, `outcome: BatchOutcome | None` (a batch child's result) and `batch_loop`;
    - `iterations`, which is now `budget.used`;
    - `start_batch(loop_step, outer: list[OuterScope], items, *, offset, concurrency, stop_on_error)`;
    - `take_batches() -> list[Batch]`;
    - `take_settled() -> list[tuple[Instance, dict]]` (each with its result);
    - `give_back(steps, collects, batches)`;
    - `open_loop(inst, items, *, concurrency, stop_on_error, batch=0)`;
    - `batch_done(loop_inst, start, outcome)` and `batch_failed(loop_inst, start, failure)`;
    - `answer_budget() -> tuple[list[Answer], Ask | None]`, which returns the answers that aren't the loops' own,
      and the ask for the parent;
    - `to_json()` and `Scheduler.from_json(program, data)`.
  - `debit()` and the `iteration_cap` argument are gone.

- [ ] **Step 1: Write the failing tests**

The cap tests build a root budget of 2. The third iteration now waits for budget until `answer_budget()` refuses
it. In `backend/tests/engine/runtime/test_scheduler.py`:

```diff
diff --git a/backend/tests/engine/runtime/test_scheduler.py b/backend/tests/engine/runtime/test_scheduler.py
--- a/backend/tests/engine/runtime/test_scheduler.py
+++ b/backend/tests/engine/runtime/test_scheduler.py
@@ -3,6 +3,7 @@

 from typing import Any

+from dewpoint.engine.runtime.budget import Budget
 from dewpoint.engine.runtime.scheduler import Failure, NodeState, RunEnd, Scheduler
 from tests.engine.runtime.support import name, program
 from tests.support.graphs import G
@@ -232,10 +233,12 @@


 def test_the_iteration_cap_fails_the_loop() -> None:
-    s = Scheduler(program(loop_graph()), iteration_cap=2)
+    s = Scheduler(program(loop_graph()), budget=Budget(2, root=True))
     s.start()
     [loop] = s.take_ready()
     s.open_loop(loop, [1, 2, 3], concurrency=3, stop_on_error=True)
+    assert s.ended is None  # the third iteration waits for budget
+    s.answer_budget()  # nothing can release any: it's refused, and the loop fails
     assert s.ended is not None and s.ended.failure is not None
     assert s.ended.failure.code == "iteration_cap_exceeded"

@@ -245,10 +248,11 @@
     the steps after the loop ran beside them, and the run could end with a child unsettled."""
     g = loop_graph()
     g.nodes[0]["options"]["on_error"] = "continue"
-    s = Scheduler(program(g), iteration_cap=2)
-    s.start()
-    [loop] = s.take_ready()
-    s.open_loop(loop, [1, 2, 3], concurrency=3, stop_on_error=True)  # opens 0 and 1, then the third hits the cap
+    s = Scheduler(program(g), budget=Budget(2, root=True))
+    s.start()
+    [loop] = s.take_ready()
+    s.open_loop(loop, [1, 2, 3], concurrency=3, stop_on_error=True)  # opens 0 and 1; the third waits for budget
+    s.answer_budget()  # refused: the cap
     assert ready(s) == ["after"]  # the queued iterations never start
     assert s.take_cancels() == [] and s.scopes[()].results["l"]["error"]["code"] == "iteration_cap_exceeded"

@@ -256,7 +260,7 @@
 def test_the_iteration_cap_cancels_the_loops_running_iterations() -> None:
     g = loop_graph()
     g.nodes[0]["options"]["on_error"] = "continue"
-    s = Scheduler(program(g), iteration_cap=2)
+    s = Scheduler(program(g), budget=Budget(2, root=True))
     s.start()
     [loop] = s.take_ready()
     s.open_loop(loop, [1, 2, 3], concurrency=2, stop_on_error=True)
@@ -265,11 +269,12 @@
     [y0] = s.take_ready()
     s.succeed(y0, {})
     [collect] = s.take_collects()
-    s.collected(collect.loop, collect.index, "first")  # the third iteration hits the cap while l:1 still runs
+    s.collected(collect.loop, collect.index, "first")  # the third iteration waits for budget while l:1 still runs
+    s.answer_budget()  # refused: the cap
     assert [name(s, i) for i in s.take_cancels()] == ["l:1/x"]
     assert ready(s) == ["after"]
     s.succeed(x1, {})  # the cancelled iteration's late result counts for nothing
-    assert s.take_ready() == [] and "y" not in s.scopes[(("l", 1),)].results
+    assert s.take_ready() == [] and (("l", 1),) not in s.scopes  # and its scope is gone


 def test_a_stop_ends_the_run_and_cancels_running_work() -> None:
```

The property test snapshots at random points and runs batches. In
`backend/tests/engine/runtime/test_scheduler_properties.py`:

```diff
diff --git a/backend/tests/engine/runtime/test_scheduler_properties.py b/backend/tests/engine/runtime/test_scheduler_properties.py
--- a/backend/tests/engine/runtime/test_scheduler_properties.py
+++ b/backend/tests/engine/runtime/test_scheduler_properties.py
@@ -3,8 +3,12 @@
 - every node runs or dies exactly once per scope;
 - dead paths never run;
 - a step runs in its own region's scope, so branches that reconverge meet in the same scope;
-- no edge is left pending when a run succeeds, so nothing deadlocks."""
+- no edge is left pending when a run succeeds, so nothing deadlocks.

+The same runs also take snapshots at random points and carry on from them (continue-as-new), and some loops run in
+batches whose children report random outcomes (2a-3b)."""
+
+import json
 from typing import Any

 from hypothesis import HealthCheck, given, settings
@@ -12,6 +16,8 @@

 from dewpoint.engine.runtime.scheduler import (
     SETTLED,
+    Batch,
+    BatchOutcome,
     EdgeState,
     Failure,
     Instance,
@@ -99,8 +105,16 @@
     s.start()
     running: list[Instance] = []
     collects: list[Any] = []
+    batches: list[Batch] = []
     handed: dict[Instance, int] = {}
     while s.ended is None:
+        cancelled = set(s.take_cancels())
+        running = [r for r in running if r not in cancelled]
+        batches = [b for b in batches if b.loop not in cancelled]
+        # continue-as-new: carry on from a snapshot, taken with work still queued, as drain mode leaves it
+        if data.draw(st.integers(0, 7), label="snapshot") == 0:
+            s.take_settled()
+            s = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json())))
         for inst in s.take_ready():
             handed[inst] = handed.get(inst, 0) + 1
             assert handed[inst] == 1, "a step ran twice in one scope"
@@ -108,11 +122,22 @@
             assert _entry_ok(s, inst), "a step ran without a live incoming edge"
             running.append(inst)
         collects += s.take_collects()
-        cancelled = set(s.take_cancels())
-        running = [r for r in running if r not in cancelled]
-        if not running and not collects:
+        batches += s.take_batches()
+        if not running and not collects and not batches:
             raise AssertionError("stuck: nothing running, nothing to collect, and the run hasn't ended")
-        pick = data.draw(st.integers(0, len(running) + len(collects) - 1))
+        pick = data.draw(st.integers(0, len(running) + len(collects) + len(batches) - 1))
+        if pick >= len(running) + len(collects):
+            b = batches.pop(pick - len(running) - len(collects))
+            how = data.draw(st.sampled_from(["ok", "ok", "item_failed", "stopped", "failed"]), label="batch")
+            if how == "failed":
+                s.batch_failed(b.loop, b.start, Failure("internal_error", "the child failed"))
+                continue
+            failures = (
+                [{"index": b.start, "code": "testkit.boom", "message": "it broke"}] if how == "item_failed" else []
+            )
+            stopped = Failure("testkit.boom", "it broke") if how == "stopped" else None
+            s.batch_done(b.loop, b.start, BatchOutcome([b.start + i for i in range(len(b.items))], failures, stopped))
+            continue
         if pick >= len(running):
             c = collects.pop(pick - len(running))
             if data.draw(st.integers(0, 5), label="collect") == 0:
@@ -123,12 +148,13 @@
         inst = running.pop(pick)
         step = s.step(inst)
         if step.ref == LOOP:
-            items = list(range(data.draw(st.integers(0, 3), label="items")))
+            items = list(range(data.draw(st.integers(0, 5), label="items")))
             s.open_loop(
                 inst,
                 items,
                 concurrency=data.draw(st.integers(1, 2), label="concurrency"),
                 stop_on_error=data.draw(st.booleans(), label="stop"),
+                batch=data.draw(st.sampled_from([0, 0, 2]), label="batch"),
             )
         elif step.ref in (IF, SWITCH):
             s.succeed(inst, {}, (data.draw(st.sampled_from(step.ports), label="port"),))
```

Create `backend/tests/engine/runtime/test_scheduler_batches.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Batched loops (spec §6, 2a-3b): the parent hands out one batch at a time and takes back its results; a batch
child runs one slice of the loop over read-only copies of the loop's enclosing scopes; settled iterations are
pruned; the state survives a snapshot."""

import json

from dewpoint.engine.runtime.budget import Budget
from dewpoint.engine.runtime.resolve import view
from dewpoint.engine.runtime.scheduler import (
    Batch,
    BatchOutcome,
    Failure,
    Instance,
    OuterScope,
    RunEnd,
    Scheduler,
)
from tests.engine.runtime.support import name, program
from tests.support.graphs import G

ECHO, LOOP, FAIL = "testkit.echo@1", "flow.loop@1", "flow.fail@1"
BOOM = Failure("testkit.boom", "it broke")


def loop_graph() -> G:
    g = G().node("a", ECHO).node("l", LOOP, {"items": [1]}).node("x", ECHO).node("after", ECHO)
    return g.edge("a", "l").edge("l", "x", "body").edge("l", "after", "done")


def parent_at_loop(items: int, *, stop: bool = True) -> tuple[Scheduler, Instance]:
    s = Scheduler(program(loop_graph()))
    s.start()
    [a] = s.take_ready()
    s.succeed(a, {"seen": "a"})
    [loop] = s.take_ready()
    s.open_loop(loop, list(range(items)), concurrency=3, stop_on_error=stop, batch=100)
    return s, loop


def test_a_batched_loop_hands_out_one_batch_at_a_time_and_collects_them_in_order() -> None:
    s, loop = parent_at_loop(250)
    assert s.take_ready() == [] and not any(k for k in s.scopes if k)  # no iteration opens in the parent
    starts = []
    for _ in range(3):
        [b] = s.take_batches()
        assert s.take_batches() == []  # the next one waits for this one
        starts.append((b.start, len(b.items)))
        s.batch_done(loop, b.start, BatchOutcome([i * 10 for i in b.items], []))
    assert starts == [(0, 100), (100, 100), (200, 50)]
    assert [name(s, i) for i in s.take_ready()] == ["after"]
    output = s.scopes[()].results["l"]["output"]
    assert output["items"] == [i * 10 for i in range(250)] and output["count"] == 250


def test_a_stopped_batch_fails_the_loop_and_a_failed_batch_too() -> None:
    s, loop = parent_at_loop(150)
    [b] = s.take_batches()
    s.batch_done(
        loop, b.start, BatchOutcome([None] * 100, [{"index": 7, "code": "testkit.boom", "message": "x"}], BOOM)
    )
    assert s.ended is not None and s.ended.failure == BOOM
    s, loop = parent_at_loop(150)
    [b] = s.take_batches()
    s.batch_failed(loop, b.start, Failure("internal_error", "the child failed"))
    assert s.ended is not None and s.ended.failure is not None and s.ended.failure.code == "internal_error"


def test_failed_items_of_every_batch_are_listed_under_continue() -> None:
    s, loop = parent_at_loop(150, stop=False)
    for failed in (7, 120):
        [b] = s.take_batches()
        failures = [{"index": failed, "code": "testkit.boom", "message": "it broke"}]
        s.batch_done(loop, b.start, BatchOutcome([None] * len(b.items), failures))
    output = s.scopes[()].results["l"]["output"]
    assert [f["index"] for f in output["failures"]] == [7, 120]


def child_for(items: list[int], offset: int, *, stop: bool = True, g: G | None = None) -> Scheduler:
    p = program(g or loop_graph())
    s = Scheduler(p, budget=Budget(len(items), root=False))
    outer = [OuterScope((), {"a": {"output": {"seen": "a"}}})]
    s.start_batch(p.by_key["l"], outer, items, offset=offset, concurrency=2, stop_on_error=stop)
    return s


def test_a_batch_child_runs_its_slice_with_the_inline_iteration_keys() -> None:
    s = child_for([100, 101, 102], 100)
    first = s.take_ready()
    assert [name(s, i) for i in first] == ["l:100/x", "l:101/x"]  # the loop's concurrency, in index order
    v = view(s, first[0].scope, trigger={}, variables={}, run={})
    assert v.steps["a"] == {"output": {"seen": "a"}} and v.item == 100 and v.loops["l"] == {"item": 100, "index": 100}
    for inst in first:
        s.succeed(inst, {})
    for c in s.take_collects():
        s.collected(c.loop, c.index, c.index * 2)
    [last] = s.take_ready()
    s.succeed(last, {})
    [c] = s.take_collects()
    s.collected(c.loop, c.index, c.index * 2)
    assert s.ended == RunEnd("succeeded") and s.outcome == BatchOutcome([200, 202, 204], [])
    assert list(s.scopes) == [()]  # every iteration was pruned; the enclosing scope stays


def test_a_failed_iteration_stops_the_slice_or_is_listed() -> None:
    stopping = child_for([5, 6], 5)
    x5, x6 = stopping.take_ready()
    stopping.fail(x5, BOOM)
    assert stopping.outcome is not None and stopping.outcome.stopped == BOOM
    assert [name(stopping, i) for i in stopping.take_cancels()] == ["l:6/x"]
    going_on = child_for([5, 6], 5, stop=False)
    x5, x6 = going_on.take_ready()
    going_on.fail(x5, BOOM)
    going_on.succeed(x6, {})
    [c] = going_on.take_collects()
    going_on.collected(c.loop, c.index, "six")
    assert going_on.outcome == BatchOutcome(
        [None, "six"], [{"index": 5, "code": "testkit.boom", "message": "it broke"}]
    )


def test_a_fail_node_in_a_batch_ends_the_run_not_just_the_slice() -> None:
    g = G().node("a", ECHO).node("l", LOOP, {"items": [1]}).node("f", FAIL, {"message": "no"})
    g.edge("a", "l").edge("l", "f", "body")
    s = child_for([0], 0, g=g)
    [f] = s.take_ready()
    s.finish(f, RunEnd("failed", Failure("workflow_failed", "no")))
    assert s.outcome is None and s.ended == RunEnd("failed", Failure("workflow_failed", "no"))


def test_an_iteration_waits_for_budget_in_a_child_and_the_grant_opens_it() -> None:
    p = program(loop_graph())
    s = Scheduler(p, budget=Budget(1, root=False))
    s.start_batch(p.by_key["l"], [OuterScope((), {})], [0, 1], offset=0, concurrency=2, stop_on_error=True)
    assert [name(s, i) for i in s.take_ready()] == ["l:0/x"]
    answers, ask = s.answer_budget()
    assert answers == [] and ask is not None and ask.need == 1  # it asks its parent for the second
    s.budget.answered(1_000)
    s.answer_budget()
    assert [name(s, i) for i in s.take_ready()] == ["l:1/x"]


def test_a_batched_loop_survives_a_snapshot() -> None:
    s, loop = parent_at_loop(150)
    [b] = s.take_batches()
    s.take_settled()
    s = Scheduler.from_json(s.program, json.loads(json.dumps(s.to_json())))
    s.batch_done(loop, b.start, BatchOutcome(list(b.items), []))
    [b2] = s.take_batches()
    assert b2 == Batch(loop, 100, list(range(100, 150)))
```

Add the worker test for the run's cap. It patches `ITERATION_CAP` in the workflow module, so it runs outside the
sandbox. In `backend/tests/apps/worker/test_run_graph_policies.py`:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_policies.py b/backend/tests/apps/worker/test_run_graph_policies.py
--- a/backend/tests/apps/worker/test_run_graph_policies.py
+++ b/backend/tests/apps/worker/test_run_graph_policies.py
@@ -16,6 +16,7 @@
 from dewpoint.engine.canonical import canonical_json
 from dewpoint.engine.graph.validate import SubflowInfo
 from dewpoint.engine.runtime import nodes
+from dewpoint.engine.runtime import workflow as run_graph
 from dewpoint.engine.runtime.activities import CEL_EVALUATE, ENGINE_QUEUE, PROJECT, ProjectInput, RunInput
 from dewpoint.engine.runtime.workflow import PROJECT_BYTES, RunGraph
 from tests.apps.worker.harness import TENANT, MemoryStore, run, start, workers
@@ -107,6 +108,21 @@
     g.node("r", "flow.run_workflow@1", {"workflow_id": str(child)}, on_error="continue")
     async with workers(env.client, store):
         assert (await run(env.client, store, g, TRIGGER)).outputs == {"code": "not_supported"}
+
+
+async def test_a_loop_past_the_runs_iteration_cap_fails(
+    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """The run's cap (spec §6): the iteration past it is refused and its loop fails. The run doesn't wait for budget
+    nothing could release."""
+    monkeypatch.setattr(run_graph, "ITERATION_CAP", 2)
+    store = MemoryStore()
+    g = graph(code=ref("steps.l.error.code", default="none"))
+    g.node("l", LOOP, {"items": [1, 2, 3]}, on_error="continue")
+    g.node("x", ECHO).edge("l", "x", "body")
+    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
+        result = await asyncio.wait_for(run(env.client, store, g, TRIGGER), 60)
+    assert (result.outputs, result.iterations) == ({"code": "iteration_cap_exceeded"}, 2)


 async def test_a_failing_collect_fails_its_iteration(env: WorkflowEnvironment) -> None:
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/runtime/test_scheduler.py tests/engine/runtime/test_scheduler_properties.py tests/engine/runtime/test_scheduler_batches.py "tests/apps/worker/test_run_graph_policies.py::test_a_loop_past_the_runs_iteration_cap_fails"`
Expected: two collection errors, `ImportError: cannot import name 'Batch' from
'dewpoint.engine.runtime.scheduler'` (in `test_scheduler_properties.py` and `test_scheduler_batches.py`).

- [ ] **Step 3: Replace the scheduler**

Replace `backend/src/dewpoint/engine/runtime/scheduler.py` with:

```python
# SPDX-License-Identifier: Apache-2.0
"""The scheduler (spec §6): node and edge states per scope, readiness, edge resolution, dead-path elimination, loop
iterations and how a run ends. It decides nothing about values or effects: the workflow runs each ready step and
reports how it ended. It is deterministic: its dicts are filled in a fixed order, and its ready queue is ordered by
(scope, topological index).

A scope is the root, or one loop iteration: `()` or `(("loop2", 7), ("loop5", 3))`. Branches don't open scopes, so
paths that split at an `if` meet again in the same scope. Each node runs or dies exactly once per scope.

Loops over more than `INLINE_ITEMS` items run in batches (2a-3b): the loop hands out one `Batch` at a time, which the
workflow runs as a child execution, and takes back its results. A batch child's scheduler runs one slice of the loop
(`start_batch`) over read-only copies of the loop's enclosing scopes, so its iteration keys are the inline ones.

Every iteration and filter item is debited from the execution's `Budget` (spec §6, one counter per logical run). An
iteration that can't be debited waits for budget, or ends the loop at the cap. A settled iteration's scope is pruned
once its loop has taken its result: only open scopes stay, which keeps a continue-as-new snapshot small."""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dewpoint.engine.runtime.budget import LOCAL, Answer, Ask, Budget, Need
from dewpoint.engine.runtime.program import BODY, DONE, ERROR_PORT, Program, Step

ScopeKey = tuple[tuple[str, int], ...]
ITERATION_CAP = 100_000  # loop iterations and filter items across the whole logical run (spec §4.2)
ITERATION_CAP_EXCEEDED = "iteration_cap_exceeded"
CAP_MESSAGE = "This run reached its limit of 100,000 loop iterations."
SNAPSHOT_FORMAT = 1


class NodeState(StrEnum):
    WAITING = "waiting"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    DEAD = "dead"


class EdgeState(StrEnum):
    PENDING = "pending"
    LIVE = "live"
    DEAD = "dead"


SETTLED = frozenset({NodeState.DONE, NodeState.FAILED, NodeState.DEAD})


def iteration_key(scope: ScopeKey) -> str:
    """`loop2:7/loop5:3`; empty for the root."""
    return "/".join(f"{loop}:{index}" for loop, index in scope)


@dataclass(frozen=True, order=True)
class Instance:
    """One step in one scope."""

    scope: ScopeKey
    step: uuid.UUID


@dataclass(frozen=True)
class Failure:
    code: str
    message: str
    attempt: int = 1

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "attempt": self.attempt}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Failure":
        return cls(str(data["code"]), str(data["message"]), int(data.get("attempt", 1)))


@dataclass
class Scope:
    key: ScopeKey
    region: uuid.UUID | None
    nodes: dict[uuid.UUID, NodeState]
    edges: dict[int, EdgeState]
    results: dict[str, dict[str, Any]]  # step key -> {"output": …} and/or {"error": …} (the presence contract)
    item: Any = None
    index: int | None = None
    failure: Failure | None = None  # the unhandled failure that ended this scope
    frozen: bool = False  # an enclosing scope a batch child reads, and never runs

    @property
    def settled(self) -> bool:
        return self.failure is not None or all(s in SETTLED for s in self.nodes.values())


@dataclass
class LoopRun:
    """A loop node's iterations: opened in order, at most `concurrency` at a time. `offset` is the index of
    `items[0]` (a batch child runs a slice). With `batch`, the items run in children of that many, one at a time."""

    instance: Instance
    items: list[Any]
    concurrency: int
    stop_on_error: bool
    offset: int = 0
    batch: int = 0
    next: int = 0  # the next item to open, as a position in `items`
    open: list[int] = field(default_factory=list)  # open iterations, by absolute index
    collecting: set[int] = field(default_factory=set)  # settled iterations whose `collect` is being evaluated
    collected: list[Any] = field(default_factory=list)  # per item of `items`
    failures: list[dict[str, Any]] = field(default_factory=list)
    running_batch: int | None = None  # the start of the batch a child is running
    waiting: bool = False  # the next iteration waits for budget


@dataclass(frozen=True)
class Collect:
    """An iteration settled without an unhandled failure: evaluate the loop's `collect` in `scope`."""

    loop: Instance
    index: int
    scope: ScopeKey


@dataclass(frozen=True)
class Batch:
    """A batch of a loop's items, for a child: items `start` .. `start + len(items)`."""

    loop: Instance
    start: int
    items: list[Any]


@dataclass(frozen=True)
class BatchOutcome:
    """What a batch child's slice produced: the collected values, the failed iterations, and the failure that stopped
    it under `on_item_error: stop`."""

    collected: list[Any]
    failures: list[dict[str, Any]]
    stopped: Failure | None = None


@dataclass(frozen=True)
class OuterScope:
    """An enclosing scope, as a batch child reads it: the results its region can reference, and the loop item."""

    key: ScopeKey
    results: dict[str, dict[str, Any]]
    item: Any = None
    index: int | None = None


@dataclass(frozen=True)
class RunEnd:
    status: str  # succeeded | failed | deadline_exceeded | cancelled
    failure: Failure | None = None
    stopped: bool = False  # ended by a stop node: workflow outputs are still evaluated

    def to_json(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "failure": self.failure.to_json() if self.failure else None,
            "stopped": self.stopped,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "RunEnd":
        failure = data.get("failure")
        return cls(str(data["status"]), Failure.from_json(failure) if failure else None, bool(data.get("stopped")))


class Scheduler:
    def __init__(self, program: Program, *, budget: Budget | None = None) -> None:
        self.program = program
        self.budget = budget if budget is not None else Budget(ITERATION_CAP, root=True)
        self.scopes: dict[ScopeKey, Scope] = {}
        self.loops: dict[Instance, LoopRun] = {}
        self.ended: RunEnd | None = None
        self.batch_loop: Instance | None = None  # a batch child: the loop whose slice it runs
        self.outcome: BatchOutcome | None = None  # a batch child: its slice's result, once it's done
        self._ready: list[Instance] = []
        self._collects: list[Collect] = []
        self._batches: list[Batch] = []
        self._cancels: list[Instance] = []
        self._settled: list[tuple[Instance, dict[str, Any]]] = []
        self._budget_waits: dict[str, Instance] = {}  # a need's key -> the loop waiting for it
        self._topo_of_key = {s.key: s.topo for s in program.steps.values()}
        self._members: dict[uuid.UUID | None, tuple[uuid.UUID, ...]] = {
            region: r.members for region, r in program.regions.items()
        }

    @property
    def iterations(self) -> int:
        """Iterations and filter items this execution used, its settled children's included."""
        return self.budget.used

    # --- the workflow's side ---------------------------------------------------------------------------------------

    def start(self) -> None:
        self._open_scope((), None)

    def start_batch(
        self,
        loop_step: uuid.UUID,
        outer: list[OuterScope],
        items: list[Any],
        *,
        offset: int,
        concurrency: int,
        stop_on_error: bool,
    ) -> None:
        """A batch child: rebuild the loop's enclosing scopes read-only, outermost first, and run items `offset` ..
        `offset + len(items)` of it. The loop's own scope is the last one."""
        chain = self.program.chain(self.program.steps[loop_step].region)  # innermost first
        for depth, o in enumerate(outer):
            region = chain[len(outer) - 1 - depth]
            self.scopes[o.key] = Scope(o.key, region, {}, {}, dict(o.results), o.item, o.index, frozen=True)
        loop_inst = Instance(outer[-1].key, loop_step)
        self.batch_loop = loop_inst
        loop = LoopRun(loop_inst, list(items), concurrency, stop_on_error, offset=offset, collected=[None] * len(items))
        self.loops[loop_inst] = loop
        self._advance(loop)

    def take_ready(self) -> list[Instance]:
        """Ready steps, in (scope, topological) order. They are running from now on."""
        ready = sorted(self._ready, key=self.order)
        self._ready = []
        for inst in ready:
            self.scopes[inst.scope].nodes[inst.step] = NodeState.RUNNING
        return ready

    def take_collects(self) -> list[Collect]:
        out, self._collects = self._collects, []
        return out

    def take_batches(self) -> list[Batch]:
        out, self._batches = self._batches, []
        return out

    def take_settled(self) -> list[tuple[Instance, dict[str, Any]]]:
        """Steps that succeeded or failed since the last call, with their result as it was when they settled (loops
        completed by their last iteration included)."""
        out, self._settled = self._settled, []
        return out

    def take_cancels(self) -> list[Instance]:
        """Running steps whose scope ended (a failure, a stop, the deadline): their work must be cancelled, and
        nothing they report later counts."""
        out, self._cancels = sorted(self._cancels, key=self.order), []
        return out

    def give_back(self, steps: list[Instance], collects: list[Collect], batches: list[Batch]) -> None:
        """Work handed over but never started (drain mode, the in-flight cap): it waits in the queues again, first,
        for the continued run."""
        self._ready = steps + self._ready
        self._collects = collects + self._collects
        self._batches = batches + self._batches

    def succeed(self, inst: Instance, output: Any, ports: tuple[str, ...] | None = None) -> None:
        """The step succeeded. `ports`: the normal ports whose edges are live (if/switch pick one); all by default."""
        scope, step = self._running(inst)
        if scope is None:
            return
        scope.nodes[step.id] = NodeState.DONE
        scope.results[step.key] = {"output": output}
        self._settled.append((inst, scope.results[step.key]))
        live = set(step.ports if ports is None else ports)
        self._resolve(scope, step, {p for p in step.ports if p in live} - {BODY})
        self._after_settle(scope)

    def fail(self, inst: Instance, failure: Failure) -> None:
        """The step failed. Its `on_error` decides: `port` follows the error edges, `continue` the normal ones, and
        `fail` ends the scope: the run in the root, the iteration in a loop body. Either handled way, the step has an
        error and no output, so `has(steps.x.output)` is false (spec §5.3) and a reference's default applies."""
        scope, step = self._running(inst)
        if scope is None:
            return
        scope.nodes[step.id] = NodeState.FAILED
        self._settled.append((inst, {"error": failure.to_json()}))
        if step.on_error == "port":
            scope.results[step.key] = {"error": failure.to_json()}
            self._resolve(scope, step, {ERROR_PORT})
        elif step.on_error == "continue":
            scope.results[step.key] = {"error": failure.to_json()}
            self._resolve(scope, step, set(step.ports) - {BODY})
        else:
            self._fail_scope(scope, failure)
            return
        self._after_settle(scope)

    def open_loop(
        self, inst: Instance, items: list[Any], *, concurrency: int, stop_on_error: bool, batch: int = 0
    ) -> None:
        """The loop node's `items` are known: open its first iterations, or hand out its first batch. An empty list
        completes it at once."""
        scope, step = self._running(inst)
        if scope is None:
            return
        loop = LoopRun(inst, list(items), concurrency, stop_on_error, batch=batch, collected=[None] * len(items))
        self.loops[inst] = loop
        self._advance(loop)

    def collected(self, loop_inst: Instance, index: int, value: Any) -> None:
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open:
            return
        loop.open.remove(index)
        loop.collecting.discard(index)
        loop.collected[index - loop.offset] = value
        self._prune(self._iteration_scope(loop, index))
        self._advance(loop)

    def collect_failed(self, loop_inst: Instance, index: int, failure: Failure) -> None:
        """`collect` couldn't be evaluated: the iteration failed after all."""
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open:
            return
        self._iteration_failed(loop, index, failure)

    def batch_done(self, loop_inst: Instance, start: int, outcome: BatchOutcome) -> None:
        """A batch child finished its slice: take its results, then hand out the next batch or complete the loop. A
        slice stopped by a failed iteration (`on_item_error: stop`) fails the loop."""
        loop = self.loops.get(loop_inst)
        if loop is None or loop.running_batch != start:
            return
        loop.running_batch = None
        loop.collected[start : start + len(outcome.collected)] = outcome.collected
        loop.failures.extend(outcome.failures)
        if outcome.stopped is not None:
            self._abort(loop, outcome.stopped)
            return
        self._advance(loop)

    def batch_failed(self, loop_inst: Instance, start: int, failure: Failure) -> None:
        """A batch child failed as a whole (not one of its iterations): the loop fails with it."""
        loop = self.loops.get(loop_inst)
        if loop is None or loop.running_batch != start:
            return
        loop.running_batch = None
        self._abort(loop, failure)

    def finish(self, inst: Instance, end: RunEnd, output: Any = None) -> None:
        """A stop or fail node: record its result, then end the run (it has no edges to resolve)."""
        scope, step = self._running(inst)
        if scope is None:
            return
        if end.failure is None:
            scope.nodes[step.id] = NodeState.DONE
            scope.results[step.key] = {"output": output}
        else:
            scope.nodes[step.id] = NodeState.FAILED
            scope.results[step.key] = {"error": end.failure.to_json()}
        self._settled.append((inst, scope.results[step.key]))
        self.end(end)

    def end(self, end: RunEnd) -> None:
        """A stop or fail node, or the deadline: the run ends now. Every running step is cancelled."""
        if self.ended is not None:
            return
        self.ended = end
        queued = set(self._ready)
        for scope in self.scopes.values():
            for node_id, state in scope.nodes.items():
                if state == NodeState.RUNNING and Instance(scope.key, node_id) not in queued:
                    self._cancels.append(Instance(scope.key, node_id))
        self._ready = []
        self._batches = []

    def answer_budget(self) -> tuple[list[Answer], Ask | None]:
        """Serve the budget's waiting needs. The loops' own answers are applied here: a granted iteration opens, a
        refused one ends its loop at the cap. The other answers (a filter's, a child's) and the Ask for the parent
        are the workflow's to deliver."""
        others: list[Answer] = []
        answers, ask = self.budget.decide()
        for a in answers:
            inst = self._budget_waits.pop(a.need.key, None) if a.need.requester == LOCAL else None
            if inst is None:
                others.append(a)
                continue
            loop = self.loops.get(inst)
            if loop is None:  # the loop ended meanwhile: give back what it was granted
                self.budget.used -= a.granted
                continue
            loop.waiting = False
            if not a.granted:
                self._abort(loop, Failure(ITERATION_CAP_EXCEEDED, CAP_MESSAGE))
                continue
            self._open_next(loop)
            self._advance(loop)
        return others, ask

    def step(self, inst: Instance) -> Step:
        return self.program.steps[inst.step]

    def scope(self, key: ScopeKey) -> Scope:
        return self.scopes[key]

    # --- internals -------------------------------------------------------------------------------------------------

    def order(self, inst: Instance) -> tuple[Any, ...]:
        """The ready queue's order: scope (by its loops' topological index, then item index), then the step's."""
        return (tuple((self._topo_of_key[loop], i) for loop, i in inst.scope), self.program.steps[inst.step].topo)

    def _running(self, inst: Instance) -> tuple[Scope | None, Step]:
        """The instance's scope, or None when its result no longer counts (the scope failed, the run ended)."""
        step = self.program.steps[inst.step]
        scope = self.scopes.get(inst.scope)
        if self.ended is not None or scope is None or scope.failure is not None or scope.frozen:
            return None, step
        if scope.nodes.get(inst.step) != NodeState.RUNNING:
            raise ValueError(f"`{step.key}` isn't running in {iteration_key(inst.scope)!r}")
        return scope, step

    def _open_scope(self, key: ScopeKey, region: uuid.UUID | None, item: Any = None, index: int | None = None) -> None:
        members = self._members[region]
        member_set = set(members)
        edges: dict[int, EdgeState] = {}
        for node_id in members:
            for e in self.program.steps[node_id].ins:
                source = self.program.edges[e].source
                # an edge from this region's own loop node is its body edge: live for every iteration
                edges[e] = EdgeState.LIVE if source not in member_set and source == region else EdgeState.PENDING
        scope = Scope(key, region, dict.fromkeys(members, NodeState.WAITING), edges, {}, item, index)
        self.scopes[key] = scope
        for node_id in members:
            self._check_ready(scope, node_id)
        self._after_settle(scope)

    def _prune(self, key: ScopeKey) -> None:
        """Forget a settled iteration's scope and every scope nested in it: its loop has what it needs."""
        for k in [k for k in self.scopes if k[: len(key)] == key]:
            del self.scopes[k]

    def _resolve(self, scope: Scope, step: Step, live_ports: set[str]) -> None:
        """Resolve every outgoing edge of `step` in `scope` exactly once. Body edges belong to the iterations."""
        work = [(step, live_ports)]
        while work:
            source, live = work.pop()
            targets: list[uuid.UUID] = []
            for port, ids in source.out.items():
                if port == BODY and source.id in self.program.regions:
                    continue
                for e in ids:
                    if e in scope.edges:
                        scope.edges[e] = EdgeState.LIVE if port in live else EdgeState.DEAD
                        targets.append(self.program.edges[e].target)
            for target in sorted(set(targets), key=lambda n: self.program.steps[n].topo):
                dead = self._check_ready(scope, target)
                if dead is not None:
                    work.append((dead, set()))

    def _check_ready(self, scope: Scope, node_id: uuid.UUID) -> Step | None:
        """Queue the node when every incoming edge is resolved and one is live. Returns it when it died instead."""
        if scope.nodes[node_id] != NodeState.WAITING:
            return None
        step = self.program.steps[node_id]
        states = [scope.edges[e] for e in step.ins if e in scope.edges]
        if any(s == EdgeState.PENDING for s in states):
            return None
        if not states or any(s == EdgeState.LIVE for s in states):
            scope.nodes[node_id] = NodeState.RUNNING  # queued; take_ready() hands it over
            self._ready.append(Instance(scope.key, node_id))
            return None
        scope.nodes[node_id] = NodeState.DEAD
        return step

    def _fail_scope(self, scope: Scope, failure: Failure, *, report: bool = True) -> None:
        """An unhandled failure ends its scope: waiting steps die, running ones are cancelled, and so is every scope
        nested inside it. `report`: tell the loop the iteration failed (not when the loop itself is stopping it)."""
        scope.failure = failure
        queued = set(self._ready)
        for key in [k for k in self.scopes if k[: len(scope.key)] == scope.key]:
            inner = self.scopes[key]
            if key != scope.key and inner.failure is None:
                inner.failure = failure
            for node_id, state in inner.nodes.items():
                inst = Instance(key, node_id)
                if state == NodeState.RUNNING and inst not in queued:
                    self._cancels.append(inst)
                if state in (NodeState.RUNNING, NodeState.WAITING):
                    inner.nodes[node_id] = NodeState.DEAD
        self._ready = [r for r in self._ready if r.scope[: len(scope.key)] != scope.key]
        for inst in [i for i in self.loops if i.scope[: len(scope.key)] == scope.key]:
            self._drop_loop(self.loops[inst])
        if scope.key == ():
            self.end(RunEnd("failed", failure))
        elif report:
            self._iteration_settled(scope)

    def _drop_loop(self, loop: LoopRun) -> None:
        """The loop ends: nothing it waits for is still wanted."""
        del self.loops[loop.instance]
        for key in [k for k, inst in self._budget_waits.items() if inst == loop.instance]:
            del self._budget_waits[key]
            self.budget.waiting = [n for n in self.budget.waiting if not (n.requester == LOCAL and n.key == key)]
        self._batches = [b for b in self._batches if b.loop != loop.instance]

    def _after_settle(self, scope: Scope) -> None:
        if scope.frozen:
            return
        if scope.key != () and scope.settled:
            self._iteration_settled(scope)
        elif scope.key == () and scope.settled and self.ended is None:
            self.ended = RunEnd("succeeded")

    def _iteration_scope(self, loop: LoopRun, index: int) -> ScopeKey:
        return (*loop.instance.scope, (self.program.steps[loop.instance.step].key, index))

    def _iteration_settled(self, scope: Scope) -> None:
        *outer, (loop_key, index) = scope.key
        loop_inst = Instance(tuple(outer), self.program.by_key[loop_key])
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open or index in loop.collecting:
            return
        if scope.failure is not None:
            self._iteration_failed(loop, index, scope.failure)
        else:
            loop.collecting.add(index)
            self._collects.append(Collect(loop_inst, index, scope.key))

    def _iteration_failed(self, loop: LoopRun, index: int, failure: Failure) -> None:
        loop.open.remove(index)
        loop.collecting.discard(index)
        self._prune(self._iteration_scope(loop, index))
        if loop.stop_on_error:
            self._abort(loop, failure)
            return
        loop.failures.append({"index": index, "code": failure.code, "message": failure.message})
        self._advance(loop)

    def _abort(self, loop: LoopRun, failure: Failure) -> None:
        """The loop ends early (an iteration failed under `stop`, or the run reached its iteration cap): its open
        iterations end first, running steps cancelled and queued ones dropped, and then the loop step fails, so its
        own `on_error` applies. Nothing the loop opened outlives it. In a batch child, its slice stops instead."""
        self._drop_loop(loop)
        for other in loop.open:
            key = self._iteration_scope(loop, other)
            self._fail_scope(self.scopes[key], failure, report=False)
            self._prune(key)
        if loop.instance == self.batch_loop:
            self._batch_over(loop, failure)
            return
        parent = self.scopes[loop.instance.scope]
        if parent.failure is None and self.ended is None:
            self.fail(loop.instance, failure)

    def _batch_over(self, loop: LoopRun, stopped: Failure | None) -> None:
        if self.ended is None:
            self.outcome = BatchOutcome(list(loop.collected), list(loop.failures), stopped)
            self.ended = RunEnd("succeeded")

    def _open_next(self, loop: LoopRun) -> None:
        index = loop.offset + loop.next
        item = loop.items[loop.next]
        loop.next += 1
        loop.open.append(index)
        self._open_scope(self._iteration_scope(loop, index), loop.instance.step, item=item, index=index)

    def _advance(self, loop: LoopRun) -> None:
        """Open iterations up to the concurrency (or hand out the next batch), or complete the loop when every item
        is done."""
        if loop.batch:
            if loop.running_batch is None and loop.next < len(loop.items):
                start = loop.next
                loop.next = min(start + loop.batch, len(loop.items))
                loop.running_batch = start
                self._batches.append(Batch(loop.instance, start, loop.items[start : loop.next]))
                return
        else:
            while loop.next < len(loop.items) and len(loop.open) < loop.concurrency and not loop.waiting:
                if not self.budget.take(1):
                    loop.waiting = True
                    key = f"loop:{iteration_key(loop.instance.scope)}:{self.program.steps[loop.instance.step].key}"
                    self._budget_waits[key] = loop.instance
                    self.budget.request(Need(LOCAL, key, 1, 1))
                    return
                self._open_next(loop)
                if loop.instance not in self.loops:  # the iteration failed at once and stopped the loop
                    return
        if not loop.open and loop.next >= len(loop.items) and loop.running_batch is None and not loop.waiting:
            self._drop_loop(loop)
            if loop.instance == self.batch_loop:
                self._batch_over(loop, None)
                return
            output = {"items": loop.collected, "failures": loop.failures, "count": len(loop.items)}
            scope = self.scopes.get(loop.instance.scope)
            if scope is not None and scope.failure is None and self.ended is None:
                self.succeed(loop.instance, output, (DONE,))

    # --- continue-as-new ---------------------------------------------------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        """The scheduler's state for a continue-as-new snapshot. Taken between units: nothing settled or cancelled
        is left to hand over."""
        if self._settled or self._cancels or self.ended is not None:
            raise ValueError("a snapshot is taken only between units, and never after the run ended")
        return {
            "snapshot_format": SNAPSHOT_FORMAT,
            "scopes": [_scope_json(s) for s in self.scopes.values()],
            "loops": [_loop_json(loop) for loop in self.loops.values()],
            "ready": [_inst_json(i) for i in self._ready],
            "collects": [[_inst_json(c.loop), c.index, _key_json(c.scope)] for c in self._collects],
            "batches": [[_inst_json(b.loop), b.start, b.items] for b in self._batches],
            "budget": self.budget.to_json(),
            "budget_waits": [[k, _inst_json(i)] for k, i in self._budget_waits.items()],
            "batch_loop": _inst_json(self.batch_loop) if self.batch_loop else None,
        }

    @classmethod
    def from_json(cls, program: Program, data: dict[str, Any]) -> "Scheduler":
        if data.get("snapshot_format") != SNAPSHOT_FORMAT:
            raise ValueError(f"unknown snapshot format {data.get('snapshot_format')!r}")
        s = cls(program, budget=Budget.from_json(data["budget"]))
        for raw in data["scopes"]:
            scope = _scope_from(raw)
            s.scopes[scope.key] = scope
        for raw in data["loops"]:
            loop = _loop_from(raw)
            s.loops[loop.instance] = loop
        s._ready = [_inst_from(i) for i in data["ready"]]
        s._collects = [Collect(_inst_from(i), int(n), _key_from(k)) for i, n, k in data["collects"]]
        s._batches = [Batch(_inst_from(i), int(n), list(items)) for i, n, items in data["batches"]]
        s._budget_waits = {str(k): _inst_from(i) for k, i in data["budget_waits"]}
        s.batch_loop = _inst_from(data["batch_loop"]) if data["batch_loop"] else None
        return s


def _key_json(key: ScopeKey) -> list[list[Any]]:
    return [[loop, index] for loop, index in key]


def _key_from(raw: list[list[Any]]) -> ScopeKey:
    return tuple((str(loop), int(index)) for loop, index in raw)


def _inst_json(inst: Instance) -> list[Any]:
    return [_key_json(inst.scope), str(inst.step)]


def _inst_from(raw: list[Any]) -> Instance:
    return Instance(_key_from(raw[0]), uuid.UUID(raw[1]))


def _scope_json(s: Scope) -> dict[str, Any]:
    return {
        "key": _key_json(s.key),
        "region": str(s.region) if s.region else None,
        "nodes": [[str(n), state.value] for n, state in s.nodes.items()],
        "edges": [[e, state.value] for e, state in s.edges.items()],
        "results": s.results,
        "item": s.item,
        "index": s.index,
        "failure": s.failure.to_json() if s.failure else None,
        "frozen": s.frozen,
    }


def _scope_from(raw: dict[str, Any]) -> Scope:
    return Scope(
        key=_key_from(raw["key"]),
        region=uuid.UUID(raw["region"]) if raw["region"] else None,
        nodes={uuid.UUID(n): NodeState(state) for n, state in raw["nodes"]},
        edges={int(e): EdgeState(state) for e, state in raw["edges"]},
        results=dict(raw["results"]),
        item=raw["item"],
        index=raw["index"],
        failure=Failure.from_json(raw["failure"]) if raw["failure"] else None,
        frozen=bool(raw["frozen"]),
    )


def _loop_json(loop: LoopRun) -> dict[str, Any]:
    return {
        "instance": _inst_json(loop.instance),
        "items": loop.items,
        "concurrency": loop.concurrency,
        "stop_on_error": loop.stop_on_error,
        "offset": loop.offset,
        "batch": loop.batch,
        "next": loop.next,
        "open": list(loop.open),
        "collecting": sorted(loop.collecting),
        "collected": loop.collected,
        "failures": loop.failures,
        "running_batch": loop.running_batch,
        "waiting": loop.waiting,
    }


def _loop_from(raw: dict[str, Any]) -> LoopRun:
    return LoopRun(
        instance=_inst_from(raw["instance"]),
        items=list(raw["items"]),
        concurrency=int(raw["concurrency"]),
        stop_on_error=bool(raw["stop_on_error"]),
        offset=int(raw["offset"]),
        batch=int(raw["batch"]),
        next=int(raw["next"]),
        open=[int(i) for i in raw["open"]],
        collecting={int(i) for i in raw["collecting"]},
        collected=list(raw["collected"]),
        failures=list(raw["failures"]),
        running_batch=raw["running_batch"],
        waiting=bool(raw["waiting"]),
    )


__all__ = [
    "Batch",
    "BatchOutcome",
    "CAP_MESSAGE",
    "Collect",
    "EdgeState",
    "Failure",
    "Instance",
    "ITERATION_CAP",
    "ITERATION_CAP_EXCEEDED",
    "LoopRun",
    "NodeState",
    "OuterScope",
    "RunEnd",
    "SNAPSHOT_FORMAT",
    "Scheduler",
    "Scope",
    "ScopeKey",
    "iteration_key",
]
```

- [ ] **Step 4: Bridge 2a-3a's workflow to it**

In `backend/src/dewpoint/engine/runtime/workflow.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -43,6 +43,7 @@
         cel_queue,
         step_activity,
     )
+    from dewpoint.engine.runtime.budget import Budget
     from dewpoint.engine.runtime.program import Step, compile_program
     from dewpoint.engine.runtime.projection import (
         Secrets,
@@ -54,6 +55,7 @@
         storable,
     )
     from dewpoint.engine.runtime.scheduler import (
+        ITERATION_CAP,
         ITERATION_CAP_EXCEEDED,
         Collect,
         Failure,
@@ -167,7 +169,7 @@
             workflow.logger.error("run_version_unusable", exc_info=True)
             message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
             return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)))
-        self.sched = Scheduler(self.program)
+        self.sched = Scheduler(self.program, budget=Budget(ITERATION_CAP, root=True))
         deadline = self.started_at + timedelta(seconds=start.max_run_duration_s)
         outputs: dict[str, Any] | None = None
         try:
@@ -204,6 +206,7 @@
         clock = asyncio.create_task(asyncio.sleep(max(0.0, (deadline - workflow.now()).total_seconds())))
         try:
             while self.sched.ended is None:
+                self.sched.answer_budget()  # no children yet: a need past the cap is refused, and its loop fails
                 waiting += [("step", i) for i in self.sched.take_ready()]
                 waiting += [("collect", c) for c in self.sched.take_collects()]
                 for inst in self.sched.take_cancels():
@@ -328,11 +331,10 @@
     def _queue_settled(self) -> None:
         """Control steps that settled since the last call. Plugin steps queue their own attempts (`_activity`)."""
         now = workflow.now().isoformat()
-        for inst in self.sched.take_settled():
+        for inst, result in self.sched.take_settled():
             step = self.sched.step(inst)
             if not step.control:
                 continue
-            result = self.sched.scopes[inst.scope].results.get(step.key, {})
             error = result.get("error")
             self._queue(
                 StepRow(
@@ -453,7 +455,7 @@
         )

     async def _filter(self, inst: Instance, step: Step, items: list[Any]) -> _Effect:
-        if not self.sched.debit(len(items)):
+        if not self.sched.budget.take(len(items)):
             return _Effect(failure=Failure(ITERATION_CAP_EXCEEDED, "This run reached its limit of loop iterations."))
         record = self.program.record(step.id, "/predicate")
         views = [self._view(inst.scope, item=(item, i)) for i, item in enumerate(items)]
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_policies.py tests/engine/runtime/test_scheduler.py tests/engine/runtime/test_scheduler_properties.py tests/engine/runtime/test_scheduler_batches.py`
Expected: 73 passed (14 + 33 + 17 + 1 + 8). Keep this path order, which is the suite's: `test_run_graph_policies.py`
run before `test_run_graph.py` hangs one of 2a-3a's timer tests.

- [ ] **Step 6: Checks and commit**

2a-3a's golden histories still replay: the bridge changes no command.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine tests/apps/worker \
  && git add src/dewpoint/engine/runtime/scheduler.py src/dewpoint/engine/runtime/workflow.py \
       tests/engine/runtime/test_scheduler.py tests/engine/runtime/test_scheduler_properties.py \
       tests/engine/runtime/test_scheduler_batches.py tests/apps/worker/test_run_graph_policies.py \
  && git commit -m "feat(engine): the scheduler draws on the budget, batches large loops, prunes and snapshots" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The program's pinned versions and a loop's outer reads

The compiled program carries the versions its version pins:
- the sub-flow version for each `run_workflow` node, in a fixed order;
- the failure handler's version.

The interpreter (Task 5) reads them. The program also answers `outer_reads(loop)`: which outside steps a loop's body
and `collect` read. That's everything a batch child needs from the enclosing scopes (decision 4). It's `None` when
an expression reads `steps` whole, and then every result goes. 2a-3a's loop over a step's values named its loop
variable `field`, which would shadow the new `dataclasses.field` import, so it's `where` now.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/program.py`
- Modify: `backend/tests/engine/runtime/test_program.py`

**Interfaces:**
- Consumes: from 2a-2, `ExpressionRecord.idents` and `.projections`; from 2a-1, `RefValue`, `TemplateValue` and
  `TemplateRef`.
- Produces:
  - `Program.subflows: Mapping[str, str]` (a `run_workflow` node id to its pinned version id, sorted by node id);
  - `Program.failure_handler: str | None`;
  - `Program.outer_reads(loop: uuid.UUID) -> frozenset[str] | None` (step keys);
  - `compile_program(graph_json, manifests, expressions, cel_profile, subflows=None, failure_handler=None)`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/engine/runtime/test_program.py`:

```diff
diff --git a/backend/tests/engine/runtime/test_program.py b/backend/tests/engine/runtime/test_program.py
--- a/backend/tests/engine/runtime/test_program.py
+++ b/backend/tests/engine/runtime/test_program.py
@@ -6,7 +6,7 @@
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.program import ProgramError, compile_program
 from tests.engine.runtime.support import MANIFESTS, expressions, program
-from tests.support.graphs import G, cel, nid, ref
+from tests.support.graphs import G, cel, nid, ref, template


 def graph() -> G:
@@ -51,3 +51,32 @@
     g.settings["outputs"] = {"n": {"$value": {"kind": "ref", "path": 5}}}  # publish refuses this; a damaged row
     with pytest.raises(ProgramError, match="/settings/outputs/n"):
         compile_program(g.data(), MANIFESTS, records, CURRENT_CEL_PROFILE)
+
+
+def test_a_program_carries_the_versions_it_pins() -> None:
+    """2a-3b: the version publish pinned for each `run_workflow` node, in a fixed order, and the failure handler's."""
+    g = graph()
+    p = compile_program(g.data(), MANIFESTS, expressions(g), CURRENT_CEL_PROFILE, {"n2": "v2", "n1": "v1"}, "h1")
+    assert (list(p.subflows.items()), p.failure_handler) == ([("n1", "v1"), ("n2", "v2")], "h1")
+    assert (program(g).subflows, program(g).failure_handler) == ({}, None)
+
+
+def test_a_loops_outer_reads_are_the_outside_steps_its_body_references() -> None:
+    """2a-3b: a batch child gets only the enclosing results its loop's body (nested loops included) and `collect`
+    read, by reference, template or CEL; everything when an expression reads `steps` whole."""
+    g = G().node("a", "testkit.echo@1").node("b", "testkit.echo@1").node("c", "testkit.echo@1")
+    g.node("d", "testkit.echo@1").node("unread", "testkit.echo@1")
+    g.node("l", "flow.loop@1", {"items": [1], "collect": ref("steps.d.output")})
+    g.node("x", "testkit.echo@1", {"value": ref("steps.a.output.value", default=0)})
+    g.node("y", "testkit.echo@1", {"value": template({"ref": "steps.b.output.value"}, "!")})
+    g.node("i", "flow.loop@1", {"items": [1]}).node("z", "testkit.echo@1", {"value": cel("steps.c.output.value + 1")})
+    for src, dst in [("a", "b"), ("b", "c"), ("c", "d"), ("d", "unread"), ("unread", "l"), ("x", "y"), ("y", "i")]:
+        g.edge(src, dst)
+    g.edge("l", "x", "body").edge("i", "z", "body")
+    p = program(g)
+    assert p.outer_reads(p.by_key["l"]) == {"a", "b", "c", "d"}
+    assert p.outer_reads(p.by_key["i"]) == {"c"}  # the inner loop's outside includes the outer body's steps
+    whole = G().node("a", "testkit.echo@1").node("l", "flow.loop@1", {"items": [1]})
+    whole.node("x", "testkit.echo@1", {"value": cel("size(steps) > 0")}).edge("a", "l").edge("l", "x", "body")
+    p = program(whole)
+    assert p.outer_reads(p.by_key["l"]) is None
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/runtime/test_program.py`
Expected: 2 failed, 3 passed:
- `TypeError: compile_program() takes 4 positional arguments but 6 were given`;
- `AttributeError: 'Program' object has no attribute 'outer_reads'`.

- [ ] **Step 3: Implement**

In `backend/src/dewpoint/engine/runtime/program.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/program.py b/backend/src/dewpoint/engine/runtime/program.py
--- a/backend/src/dewpoint/engine/runtime/program.py
+++ b/backend/src/dewpoint/engine/runtime/program.py
@@ -1,17 +1,26 @@
 # SPDX-License-Identifier: Apache-2.0
 """A published version compiled for execution (spec §6): each step with its edges by port, its region and its
-topological index, and the expression records by (node, field). Built once per run from the loaded version, and
-never changed."""
+topological index, the expression records by (node, field), and the versions it pins (its sub-flows and its failure
+handler). Built once per run from the loaded version, and never changed."""

 import uuid
 from collections.abc import Iterable, Mapping
-from dataclasses import dataclass
+from dataclasses import dataclass, field
 from typing import Any

 from dewpoint.engine.cel.record import ExpressionRecord
 from dewpoint.engine.graph.model import Graph, parse_graph
 from dewpoint.engine.graph.structure import ERROR_PORT, Region, analyze_structure
-from dewpoint.engine.graph.values import CelValue, Value, ValueSyntaxError, iter_values, pointer_str
+from dewpoint.engine.graph.values import (
+    CelValue,
+    RefValue,
+    TemplateRef,
+    TemplateValue,
+    Value,
+    ValueSyntaxError,
+    iter_values,
+    pointer_str,
+)
 from dewpoint.engine.registry.catalog import Catalog, spec_from_manifest

 BODY, DONE = "body", "done"
@@ -57,6 +66,8 @@
     records: Mapping[tuple[str | None, str], ExpressionRecord]
     manifests: Mapping[str, Mapping[str, Any]]  # type@version -> the registered manifest
     cel_profile: str
+    subflows: Mapping[str, str] = field(default_factory=dict)  # run_workflow node id -> its pinned version id
+    failure_handler: str | None = None  # the pinned failure-handler version id

     def chain(self, region: uuid.UUID | None) -> list[uuid.UUID | None]:
         """`region` and every region enclosing it, innermost first, ending with the root (None)."""
@@ -72,12 +83,42 @@
             raise ProgramError(f"no expression record for {field!r}")
         return found

+    def outer_reads(self, loop: uuid.UUID) -> frozenset[str] | None:
+        """The steps outside `loop`'s body that the body (its nested loops included) and the loop's `collect` read:
+        what a batch child needs from the enclosing scopes. None when an expression reads `steps` as a whole."""
+        inside = {r for r in self.regions if r is not None and loop in self.chain(r)}
+        members = {m for r in inside for m in self.regions[r].members}
+        names: set[str] = set()
+        sites = [(m, p, v) for m in members for p, v in self.steps[m].values]
+        sites += [(loop, p, v) for p, v in self.steps[loop].values if p == "/collect" or p.startswith("/collect/")]
+        for owner, pointer, value in sites:
+            if isinstance(value, RefValue):
+                paths = [value.path]
+            elif isinstance(value, TemplateValue):
+                paths = [part.path for part in value.parts if isinstance(part, TemplateRef)]
+            elif isinstance(value, CelValue):
+                record = self.record(owner, pointer)
+                projected = [p.path for p in record.projections if p.path[:1] == ("steps",)]
+                for ident in record.idents:  # a typed path is a dotted identifier; `steps` alone binds the root
+                    if ident.startswith("steps."):
+                        names.add(ident.split(".")[1])
+                    elif ident == "steps" and (not projected or any(len(path) < 2 for path in projected)):
+                        return None
+                names |= {path[1] for path in projected}
+                continue
+            else:
+                continue
+            names |= {str(p.name) for p in paths if p.root == "steps" and p.name is not None}
+        return frozenset(names - {self.steps[m].key for m in members})
+

 def compile_program(
     graph_json: Mapping[str, Any],
     manifests: Mapping[str, Mapping[str, Any]],
     expressions: Iterable[Mapping[str, Any]],
     cel_profile: str,
+    subflows: Mapping[str, str] | None = None,
+    failure_handler: str | None = None,
 ) -> Program:
     graph = parse_graph(graph_json)
     structure, diagnostics = analyze_structure(graph, Catalog(spec_from_manifest(m) for m in manifests.values()))
@@ -116,9 +157,9 @@
         )
     records = {(r.node, r.field): r for r in (ExpressionRecord.from_json(x) for x in expressions)}
     for step in steps.values():  # every CEL value needs its record: checked before any step runs
-        for field, value in step.values:
-            if isinstance(value, CelValue) and (str(step.id), field) not in records:
-                raise ProgramError(f"`{step.key}`: no expression record for {field}")
+        for where, value in step.values:
+            if isinstance(value, CelValue) and (str(step.id), where) not in records:
+                raise ProgramError(f"`{step.key}`: no expression record for {where}")
     for path, value in iter_values(graph.settings.outputs, ("settings", "outputs")):
         if isinstance(value, ValueSyntaxError):  # publish refuses these: the stored version is damaged
             raise ProgramError(f"output {pointer_str(path)}: {value.message}")
@@ -133,6 +174,8 @@
         records=records,
         manifests=dict(manifests),
         cel_profile=cel_profile,
+        subflows=dict(sorted((subflows or {}).items())),
+        failure_handler=failure_handler,
     )


```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest -q tests/engine/runtime/test_program.py`
Expected: 5 passed.

- [ ] **Step 5: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine \
  && git add src/dewpoint/engine/runtime/program.py tests/engine/runtime/test_program.py \
  && git commit -m "feat(engine): the program carries its pinned versions and a loop's outer reads" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Checkpoint 1.** The deterministic core is complete: the budget, the scheduler with batches and its snapshot, and
the program. Stop for the owner's review before Task 4.

---

### Task 4: Sub-runs in storage

A sub-flow's run and a failure handler's run are runs of their own (decision 9). Migration 0009 adds:
- their kind;
- the run, step and iteration that started them;
- two checks and an index;
- `INSERT` on `runs` for the worker role, because a sub-run writes its own row with its first projection.

`ensure_run` writes that row idempotently, because a projection can be retried. `list_runs` lists top-level runs
only, and `children` lists the sub-runs a run started. Row-level security still holds the worker to the run's
tenant.

**Files:**
- Create: `backend/migrations/versions/0009_subruns.py`
- Modify: `backend/src/dewpoint/core/models/runs.py`, `backend/src/dewpoint/core/runs/service.py`
- Modify: `backend/tests/core/runs/test_service.py`

**Interfaces:**
- Consumes: from 2a-3a, the `runs` table (0008), `Run`, `insert_run`, `list_runs`, and the test fixtures
  `seed_workflow` and `seeded_run`.
- Produces:
  - `RUN_KINDS = ("run", "subflow", "failure_handler")`;
  - `Run.kind`, `.parent_run_id`, `.parent_step_id` and `.parent_iteration_key`;
  - `ensure_run(s, *, run_id, tenant_id, workflow_id, version_id, mode, kind, parent_run_id, parent_step_id, parent_iteration_key, started_at) -> None`;
  - `children(s, run_id) -> list[Run]`, oldest first;
  - `list_runs(...)`, which now lists top-level runs only.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/core/runs/test_service.py`:

```diff
diff --git a/backend/tests/core/runs/test_service.py b/backend/tests/core/runs/test_service.py
--- a/backend/tests/core/runs/test_service.py
+++ b/backend/tests/core/runs/test_service.py
@@ -6,6 +6,7 @@
 from typing import Any

 import pytest
+from sqlalchemy import text
 from sqlalchemy.exc import DBAPIError

 from dewpoint.core.db import tenant_scope
@@ -160,3 +161,79 @@
     if isinstance(value, str):
         assert projection.sanitize(value) == service.sanitize(value)
         assert service.sanitize(projection.sanitize(value)) == projection.sanitize(value)
+
+
+async def sub_run(worker: Any, tenant: uuid.UUID, parent: uuid.UUID, wf: uuid.UUID, version: uuid.UUID) -> uuid.UUID:
+    run_id = uuid.uuid4()
+    for _ in range(2):  # a retried projection writes it once
+        async with worker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await service.ensure_run(
+                s,
+                run_id=run_id,
+                tenant_id=tenant,
+                workflow_id=wf,
+                version_id=version,
+                mode="live",
+                kind="subflow",
+                parent_run_id=parent,
+                parent_step_id=uuid.UUID(int=9),
+                parent_iteration_key="l:3",
+                started_at=datetime.now(UTC),
+            )
+    return run_id
+
+
+async def test_a_sub_run_writes_its_own_row_and_is_listed_with_its_parent(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    """2a-3b: a sub-flow's or failure handler's run is a run of its own, pointing at the run and step that started
+    it. The worker writes its row (the sub-run's first projection); the list shows top-level runs only."""
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        parent = (
+            await service.insert_run(
+                s, run_id=uuid.uuid4(), tenant_id=tenant, workflow_id=wf, version_id=version, mode="live"
+            )
+        ).id
+    child = await sub_run(worker_sessionmaker, tenant, parent, wf, version)
+    async with owner_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        assert [r.id for r in await service.list_runs(s)] == [parent]
+        [row] = await service.children(s, parent)
+    assert (row.id, row.kind, row.parent_step_id, row.parent_iteration_key, row.status) == (
+        child,
+        "subflow",
+        uuid.UUID(int=9),
+        "l:3",
+        "running",
+    )
+    other, _ = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    with pytest.raises(DBAPIError, match="row-level security"):  # a sub-run for another tenant is refused
+        async with worker_sessionmaker() as s, s.begin():
+            await tenant_scope(s, other)
+            await service.ensure_run(
+                s,
+                run_id=uuid.uuid4(),
+                tenant_id=tenant,
+                workflow_id=wf,
+                version_id=version,
+                mode="live",
+                kind="subflow",
+                parent_run_id=parent,
+                parent_step_id=None,
+                parent_iteration_key="",
+                started_at=datetime.now(UTC),
+            )
+
+
+async def test_a_sub_run_needs_a_parent(owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker) -> None:
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    with pytest.raises(DBAPIError, match="runs_parent"):  # a sub-run's kind and its parent go together
+        async with owner_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await service.insert_run(
+                s, run_id=uuid.uuid4(), tenant_id=tenant, workflow_id=wf, version_id=version, mode="live"
+            )
+            await s.execute(text("update runs set kind = 'subflow'"))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/core/runs/test_service.py`
Expected: 2 failed, 11 passed:
- `AttributeError: module 'dewpoint.core.runs.service' has no attribute 'ensure_run'`;
- `AssertionError: Regex pattern did not match`: the error is `column "kind" of relation "runs" does not exist`,
  not the `runs_parent` check.

- [ ] **Step 3: Migrate, and extend the model and the service**

Create `backend/migrations/versions/0009_subruns.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""sub-runs: a sub-flow's or a failure handler's run points at the run that started it (engine spec §8, 2a-3b)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("kind", sa.String(32), nullable=False, server_default="run"))
    op.add_column("runs", sa.Column("parent_run_id", pg.UUID(as_uuid=True), sa.ForeignKey("runs.id"), nullable=True))
    op.add_column("runs", sa.Column("parent_step_id", pg.UUID(as_uuid=True), nullable=True))
    op.add_column("runs", sa.Column("parent_iteration_key", sa.Text, nullable=True))
    op.create_check_constraint("runs_kind", "runs", "kind IN ('run', 'subflow', 'failure_handler')")
    op.create_check_constraint("runs_parent", "runs", "(kind = 'run') = (parent_run_id IS NULL)")
    op.create_index("runs_children", "runs", ["parent_run_id"], postgresql_where=sa.text("parent_run_id IS NOT NULL"))
    # a sub-run's row is written by the sub-run itself, with its first projection, as the worker role
    op.execute("GRANT INSERT ON runs TO dewpoint_worker")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON runs FROM dewpoint_worker")
    op.drop_index("runs_children", "runs")
    op.drop_constraint("runs_parent", "runs")
    op.drop_constraint("runs_kind", "runs")
    for column in ("parent_iteration_key", "parent_step_id", "parent_run_id", "kind"):
        op.drop_column("runs", column)
```

In `backend/src/dewpoint/core/models/runs.py`:

```diff
diff --git a/backend/src/dewpoint/core/models/runs.py b/backend/src/dewpoint/core/models/runs.py
--- a/backend/src/dewpoint/core/models/runs.py
+++ b/backend/src/dewpoint/core/models/runs.py
@@ -10,10 +10,12 @@
 from dewpoint.core.models.base import Base

 RUN_STATUSES = ("running", "succeeded", "failed", "cancelled", "deadline_exceeded")
+RUN_KINDS = ("run", "subflow", "failure_handler")  # a sub-flow's or failure handler's run points at its parent


 class Run(Base):
-    """One run of a pinned workflow version. Its id is the Temporal workflow id."""
+    """One run of a pinned workflow version. Its id is the Temporal workflow id. A sub-run (a sub-flow's, a failure
+    handler's) points at the run and step that started it."""

     __tablename__ = "runs"
     id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
@@ -28,6 +30,10 @@
     error_message: Mapped[str | None] = mapped_column(Text)
     iterations: Mapped[int] = mapped_column(Integer, default=0)
     started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    kind: Mapped[str] = mapped_column(String(32), default="run")
+    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"))
+    parent_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    parent_iteration_key: Mapped[str | None] = mapped_column(Text)


 class RunStep(Base):
```

In `backend/src/dewpoint/core/runs/service.py`:

```diff
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -81,6 +81,38 @@
     return run


+async def ensure_run(
+    s: AsyncSession,
+    *,
+    run_id: uuid.UUID,
+    tenant_id: uuid.UUID,
+    workflow_id: uuid.UUID,
+    version_id: uuid.UUID,
+    mode: str,
+    kind: str,
+    parent_run_id: uuid.UUID,
+    parent_step_id: uuid.UUID | None,
+    parent_iteration_key: str,
+    started_at: datetime,
+) -> None:
+    """A sub-run's own row, written by its first projection: a retried write changes nothing."""
+    statement = insert(Run).values(
+        id=run_id,
+        tenant_id=tenant_id,
+        workflow_id=workflow_id,
+        workflow_version_id=version_id,
+        mode=mode,
+        status="running",
+        started_at=started_at,
+        iterations=0,
+        kind=kind,
+        parent_run_id=parent_run_id,
+        parent_step_id=parent_step_id,
+        parent_iteration_key=parent_iteration_key,
+    )
+    await s.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
+
+
 async def finish_run(
     s: AsyncSession,
     run_id: uuid.UUID,
@@ -136,12 +168,18 @@
 async def list_runs(
     s: AsyncSession, *, workflow_id: uuid.UUID | None = None, before: datetime | None = None, limit: int = 50
 ) -> list[Run]:
-    """Newest first; `before` pages through older runs."""
-    q = select(Run).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
+    """Top-level runs, newest first; `before` pages through older runs. Sub-runs are listed with their parent."""
+    q = select(Run).where(Run.parent_run_id.is_(None)).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
     if workflow_id is not None:
         q = q.where(Run.workflow_id == workflow_id)
     if before is not None:
         q = q.where(Run.started_at < before)
+    return list((await s.execute(q)).scalars())
+
+
+async def children(s: AsyncSession, run_id: uuid.UUID) -> list[Run]:
+    """The sub-runs a run started, in the order they started."""
+    q = select(Run).where(Run.parent_run_id == run_id).order_by(Run.started_at, Run.id)
     return list((await s.execute(q)).scalars())


```

- [ ] **Step 4: Run the tests and the migration round trip**

Run: `cd backend && uv run pytest -q tests/core/runs/test_service.py`
Expected: 13 passed. The session fixture migrates a fresh container to head.

Then check the downgrade on a scratch database (the image is the approved test image):

```bash
docker run -d --rm --name dp-mig -e POSTGRES_PASSWORD=pw -p 55433:5432 postgres:16-alpine && sleep 3 && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55433/postgres uv run alembic upgrade head && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55433/postgres uv run alembic downgrade 0008 && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55433/postgres uv run alembic upgrade head; \
docker stop dp-mig
```

Expected: all three alembic commands exit 0 (`Running upgrade 0008 -> 0009`, `Running downgrade 0009 -> 0008`,
`Running upgrade 0008 -> 0009`).

- [ ] **Step 5: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/core \
  && git add migrations/versions/0009_subruns.py src/dewpoint/core/models/runs.py src/dewpoint/core/runs/service.py \
       tests/core/runs/test_service.py \
  && git commit -m "feat(runs): sub-runs point at the run that started them (migration 0009)" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Children: loop batches, sub-flows and the failure handler, on one budget

This task gives the interpreter its children. The drive loop and every unit move into `Execution`
(`engine/runtime/execution.py`, decision 1), shared by two workflow types:
- `RunGraph` runs a run, a sub-flow or a failure handler;
- `LoopBatch` runs a slice of a loop.

What this adds:
- A loop over more than 100 items hands out batches, and each batch runs as a child (decisions 3–5).
- A `run_workflow` step runs its pinned version as a child run (decision 7).
- A run that fails or passes its deadline runs its failure handler once. Its end is decided first, and recorded
  once the handler has ended, counting the handler's iterations. Until then its row stays non-terminal, so the
  handler's closure stays held (spec §4.5). A cancel meanwhile doesn't change the end (decision 8).
- Each child writes its own `runs` row before anything else, even its version's load (decision 9). The worker's
  database store writes it in Task 6; the test harness records it here.
- The in-flight cap counts units only, not the projection beside them (decision 2).
- Every child draws on the run's one budget through the grant signals (decisions 10–12).
- A cancelled child returns its usage (decision 19).

Continue-as-new comes in Task 7, so these versions of `execution.py` and `workflow.py` don't have it yet. Task 7 is
a diff on top of them.

Several other files change with this:
- **Contracts.** `activities.py` gains the contracts between executions: `Parent`, `BatchInput`/`BatchResult`,
  `RunStart`, the version's pins, and the grant signals' names.
- **Nodes.** `nodes.py` stops refusing large loops and sub-flows with `not_supported`: a large loop is batched, and
  `run_workflow` decides a `SubflowStart`.
- **Harness.** The test harness publishes graphs the way `publish` does, validating them and recording their
  sub-flow pins, so tests can run sub-flows. It records the rows sub-runs write, and runs both workflow types. A
  version it doesn't have fails to load without retrying, as the database store's does.
- **Tests.** `test_run_graph_children.py` covers batches, sub-flows, the failure handler and grants. It includes the
  five Review Focus tests and three from execution's checkpoint 1:
  - a need that waits for an asking sub-flow holding enough;
  - a need that waits for what an asking sub-flow's own sub-flow holds;
  - a cancel while the run waits for a cancelled sub-flow to report back.

  It also has seven from the owner's reviews of this plan:
  - a child's row at its boundaries: a version that doesn't load, and a cancel while it loads;
  - the failure handler:
    - a cancel while it runs, and the usage it returns;
    - its iterations;
    - the run staying non-terminal until the handler has ended;
    - a run past its deadline;
    - no handler for a cancelled run.

  In the policies tests, the `not_supported` tests become a test of the item cap alone. A new test pins that a
  projection in flight takes no unit's slot.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/activities.py`, `backend/src/dewpoint/engine/runtime/nodes.py`
- Create: `backend/src/dewpoint/engine/runtime/execution.py`
- Replace: `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/src/dewpoint/apps/worker/main.py`
- Modify: `backend/tests/engine/runtime/test_nodes.py`, `backend/tests/apps/worker/harness.py`,
  `backend/tests/apps/worker/test_main.py`, `backend/tests/apps/worker/test_run_graph_policies.py`
- Create: `backend/tests/apps/worker/test_run_graph_children.py`

**Interfaces:**
- Consumes:
  - from Task 1, `Budget`, `Need`, `LOCAL`;
  - from Task 2, `Scheduler` (with `budget`, `take_batches`, `start_batch`, `batch_done`, `batch_failed`,
    `answer_budget`, `outcome`), `Batch`, `BatchOutcome`, `OuterScope`, `CAP_MESSAGE`, `RunEnd.to_json`/`from_json`
    and `Failure.from_json`;
  - from Task 3, `Program.subflows`, `.failure_handler`, `.outer_reads`, and `compile_program(..., subflows, failure_handler)`;
  - from 2a-2's validator, `ValidationContext`, `validate` and `SubflowInfo` (the harness publishes through them).
- Produces:
  - **`engine/runtime/activities.py`:**
    - `SUBFLOW`, `FAILURE_HANDLER`, `BATCH`, and the signal names `REQUEST_BUDGET` and `BUDGET`;
    - `Parent(workflow_id, run_id, step_id, iteration_key, kind, deadline, grant, depth=1, secrets=[])`;
    - `RunInput.parent: Parent | None = None`, `RunInput.workflow_id: str = ""` (a sub-run's workflow, for its
      row) and `RunResult.secrets: list[str] = []`;
    - `BatchInput(tenant_id, run_id, version_id, loop_step, outer, items, offset, concurrency, stop_on_error, trigger, variables, run_started_at, parent, mode=LIVE, cel_schedule_to_start_s=600)`;
    - `BatchResult(collected, failures, stopped=None, end=None, iterations=0, secrets=[])`;
    - `VersionData.subflow_version_ids: dict[str, str] = {}` and `.failure_handler_version_id: str | None = None`;
    - `RunStart(run_id, workflow_id, version_id, mode, parent_run_id, parent_step_id, parent_iteration_key, kind, started_at)`;
    - `ProjectInput.start: RunStart | None = None`.
  - **`engine/runtime/nodes.py`:** `LoopStart.batch: int = 0`, `SubflowStart(input: dict, workflow_id: str)`,
    `Decision.subflow: SubflowStart | None`; `NOT_SUPPORTED` is removed.
  - **`engine/runtime/execution.py`:**
    - `Execution`, with the signals `request_budget(child, key, need, want, held)` and `budget(key, granted)`;
    - `child_options(child_id) -> dict`;
    - `SUBFLOW_GRANT = 1_000` and `MAX_DEPTH = 5`;
    - 2a-3a's `IN_FLIGHT_CAP`, `PROJECT_BYTES`, `CEL_BATCH`, `DEADLINE_EXCEEDED`, `VERSION_UNUSABLE`,
      `INTERNAL_ERROR` and `NODE_TYPE_UNAVAILABLE`, moved here from `workflow.py`, which re-exports them.
  - **`engine/runtime/workflow.py`:**
    - `RunGraph.run(RunInput) -> RunResult`;
    - `LoopBatch.run(BatchInput) -> BatchResult`;
    - the module-level `ITERATION_CAP`, which tests patch.
  - **`apps/worker/main.py`:** `engine_worker` registers `[RunGraph, LoopBatch]`.
  - **Test harness:**
    - `MemoryStore.add(g, workflow_id=None)` validates `g` and records its pins;
    - `MemoryStore.publish(g) -> uuid.UUID` makes `g` runnable as a sub-flow or a failure handler;
    - `MemoryStore.starts: dict[str, RunStart]` holds each sub-run's own row, and `MemoryStore.schemas` holds the
      output schemas;
    - `MemoryStore.version` raises a non-retryable `ApplicationError` (`version_not_found`) for a version it
      doesn't have.

- [ ] **Step 1: Write the failing tests**

A large loop is batched, and `run_workflow` decides a sub-flow start. In
`backend/tests/engine/runtime/test_nodes.py`:

```diff
diff --git a/backend/tests/engine/runtime/test_nodes.py b/backend/tests/engine/runtime/test_nodes.py
--- a/backend/tests/engine/runtime/test_nodes.py
+++ b/backend/tests/engine/runtime/test_nodes.py
@@ -6,7 +6,7 @@

 import pytest

-from dewpoint.engine.runtime.nodes import MAX_DELAY_S, Decision, LoopStart, decide
+from dewpoint.engine.runtime.nodes import MAX_DELAY_S, Decision, LoopStart, SubflowStart, decide
 from dewpoint.engine.runtime.scheduler import Failure, RunEnd
 from tests.engine.runtime.support import MANIFESTS

@@ -48,6 +48,13 @@
             Decision(loop=LoopStart([1, 2], 2, stop_on_error=False)),
         ),
         ("flow.loop@1", {"items": []}, Decision(loop=LoopStart([], 1, stop_on_error=True))),
+        (
+            "flow.loop@1",
+            {"items": list(range(101)), "concurrency": 3},
+            Decision(loop=LoopStart(list(range(101)), 3, stop_on_error=True, batch=100)),  # batches of child workflows
+        ),
+        ("flow.run_workflow@1", {"workflow_id": "w", "input": {"n": 1}}, Decision(subflow=SubflowStart({"n": 1}, "w"))),
+        ("flow.run_workflow@1", {"workflow_id": "w"}, Decision(subflow=SubflowStart({}, "w"))),
         ("flow.filter@1", {"items": ["a"]}, Decision(filter_items=["a"])),
     ],
 )
@@ -75,8 +82,7 @@
         ("flow.loop@1", {"items": {"a": 1}}, "type_mismatch"),
         ("flow.filter@1", {"items": "abc"}, "type_mismatch"),
         ("flow.loop@1", {"items": [1, 2, 3], "item_cap": 2}, "item_cap_exceeded"),
-        ("flow.loop@1", {"items": list(range(101))}, "not_supported"),  # batches arrive with 2a-3b
-        ("flow.run_workflow@1", {"workflow_id": "w"}, "not_supported"),  # sub-flows arrive with 2a-3b
+        ("flow.run_workflow@1", {"workflow_id": "w", "input": ["not", "an", "object"]}, "type_mismatch"),
     ],
 )
 def test_a_control_node_refuses(ref: str, config: dict[str, Any], code: str) -> None:
@@ -89,7 +95,8 @@


 def test_a_loop_of_exactly_a_hundred_items_runs_inline() -> None:
-    assert decide("flow.loop@1", {"items": list(range(100))}).loop is not None
+    loop = decide("flow.loop@1", {"items": list(range(100))}).loop
+    assert loop is not None and loop.batch == 0


 def test_only_control_nodes_are_decided() -> None:
```

The harness publishes as `publish` does (validation, pins), records sub-runs' rows, and runs both workflow types. In
`backend/tests/apps/worker/harness.py`:

```diff
diff --git a/backend/tests/apps/worker/harness.py b/backend/tests/apps/worker/harness.py
--- a/backend/tests/apps/worker/harness.py
+++ b/backend/tests/apps/worker/harness.py
@@ -9,27 +9,29 @@
 from typing import Any

 from temporalio.client import Client, WorkflowHandle
+from temporalio.exceptions import ApplicationError
 from temporalio.worker import Worker, WorkflowRunner
 from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

 from dewpoint.apps.worker.activities import Evaluate, RunStore, cel_activity, engine_activities
 from dewpoint.engine.cel import ipc
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
-from dewpoint.engine.graph.validate import SubflowInfo
+from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, validate
 from dewpoint.engine.runtime.activities import (
     ENGINE_QUEUE,
     LIVE,
     ProjectInput,
     RunInput,
     RunResult,
+    RunStart,
     RunSummary,
     StepRow,
     VersionData,
     cel_queue,
 )
-from dewpoint.engine.runtime.workflow import RunGraph
+from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
 from dewpoint.sdk import Plugin
-from tests.engine.runtime.support import MANIFESTS, expressions
+from tests.engine.runtime.support import CATALOG, MANIFESTS
 from tests.support.graphs import G
 from tests.support.plugins.testkit import TESTKIT

@@ -42,24 +44,48 @@
     rows: dict[tuple[str, str, str, int], StepRow] = field(default_factory=dict)
     runs: dict[str, RunSummary] = field(default_factory=dict)
     subflows: dict[uuid.UUID, SubflowInfo] = field(default_factory=dict)  # what validation sees as published
+    starts: dict[str, RunStart] = field(default_factory=dict)  # sub-runs' own rows
+    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)  # version -> its output schema

-    def add(self, g: G) -> str:
+    def add(self, g: G, workflow_id: uuid.UUID | None = None) -> str:
+        """Publish `g` as a version, pinned to the sub-flows it runs (as `publish` registered them)."""
+        result = validate(g.build(), ValidationContext(catalog=CATALOG, subflows=self.subflows))
+        errors = [d.to_json() for d in result.diagnostics if d.severity == "error"]
+        assert not errors, errors
         version_id = str(uuid.uuid4())
         refs = {n["type"] for n in g.nodes}
+        handler = result.failure_handler_version_id
         self.versions[version_id] = VersionData(
             version_id=version_id,
-            workflow_id=str(uuid.uuid4()),
+            workflow_id=str(workflow_id or uuid.uuid4()),
             graph=g.data(),
-            expressions=expressions(g, self.subflows),
+            expressions=[r.to_json() for r in result.expressions],
             cel_profile=CURRENT_CEL_PROFILE,
             manifests={r: MANIFESTS[r] for r in sorted(refs)},
+            subflow_version_ids=dict(result.subflow_pins),
+            failure_handler_version_id=str(handler) if handler else None,
         )
+        self.schemas[version_id] = dict(result.output_schema)
         return version_id

+    def publish(self, g: G) -> uuid.UUID:
+        """A workflow other graphs can run as a sub-flow or a failure handler: its id."""
+        workflow_id = uuid.uuid4()
+        version_id = self.add(g, workflow_id)
+        input_schema = g.settings.get("input_schema", {"type": "object"})
+        self.subflows[workflow_id] = SubflowInfo(
+            workflow_id, uuid.UUID(version_id), input_schema, self.schemas[version_id]
+        )
+        return workflow_id
+
     async def version(self, tenant_id: str, version_id: str) -> VersionData:
+        if version_id not in self.versions:  # as the database store: a version that isn't there is never retried
+            raise ApplicationError(f"version {version_id} not found", type="version_not_found", non_retryable=True)
         return self.versions[version_id]

     async def project(self, data: ProjectInput) -> None:
+        if data.start is not None:
+            self.starts.setdefault(data.start.run_id, data.start)
         for row in data.steps:
             self.rows[(row.run_id, row.step_id, row.iteration_key, row.attempt)] = row
         if data.run is not None:
@@ -92,7 +118,7 @@
     engine = Worker(
         client,
         task_queue=ENGINE_QUEUE,
-        workflows=[RunGraph],
+        workflows=[RunGraph, LoopBatch],
         activities=engine_activities(store, plugins),
         workflow_runner=runner or SandboxedWorkflowRunner(),
         max_cached_workflows=cache,
```

The worker runs both types, and a helper builds the settings both tests use.

Replace `backend/tests/apps/worker/test_main.py` with:

```python
# SPDX-License-Identifier: Apache-2.0
"""`dewpoint worker`'s workers."""

from datetime import timedelta
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.worker.main import engine_worker
from dewpoint.core.config import Settings
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import MemoryStore
from tests.support.plugins.testkit import TESTKIT


def settings(**overrides: Any) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://u:p@localhost/x",
        kek_b64="A" * 43 + "=",
        public_origin="https://dewpoint.test",
        **overrides,
    )


async def test_a_stopping_worker_lets_running_attempts_finish(own_env: WorkflowEnvironment) -> None:
    """Final review: a worker that stops cancels its running attempts at once by default, so every deploy would end
    the ambiguous ones as `outcome_unknown`. It gives them the configured grace first. (A server of its own: a worker
    holds its task queue on its client until it runs and stops.)"""
    worker = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings(worker_shutdown_grace_s=45))
    assert worker.config()["graceful_shutdown_timeout"] == timedelta(seconds=45)
    assert Settings.model_fields["worker_shutdown_grace_s"].default == 30


async def test_the_engine_worker_runs_runs_and_loop_batches(own_env: WorkflowEnvironment) -> None:
    """2a-3b: a loop batch is a workflow type of its own, on the same queue as the runs that start it."""
    worker = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings())
    assert worker.config()["workflows"] == [RunGraph, LoopBatch]
```

The `not_supported` cases go. In `backend/tests/apps/worker/test_run_graph_policies.py`:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_policies.py b/backend/tests/apps/worker/test_run_graph_policies.py
--- a/backend/tests/apps/worker/test_run_graph_policies.py
+++ b/backend/tests/apps/worker/test_run_graph_policies.py
@@ -14,7 +14,6 @@
 from temporalio.worker import UnsandboxedWorkflowRunner

 from dewpoint.engine.canonical import canonical_json
-from dewpoint.engine.graph.validate import SubflowInfo
 from dewpoint.engine.runtime import nodes
 from dewpoint.engine.runtime import workflow as run_graph
 from dewpoint.engine.runtime.activities import CEL_EVALUATE, ENGINE_QUEUE, PROJECT, ProjectInput, RunInput
@@ -86,28 +85,13 @@
     assert stopped.status == "failed" and stopped.error and stopped.error["code"] == "testkit.rejected"


-@pytest.mark.parametrize(
-    ("config", "code"),
-    [
-        ({"items": list(range(101))}, "not_supported"),  # batches arrive with 2a-3b
-        ({"items": [1, 2, 3], "item_cap": 2}, "item_cap_exceeded"),
-    ],
-)
-async def test_loop_limits_fail_the_loop(env: WorkflowEnvironment, config: dict[str, Any], code: str) -> None:
-    store = MemoryStore()
-    g = graph(code=ref("steps.l.error.code", default="none")).node("l", LOOP, config, on_error="continue")
+async def test_the_item_cap_fails_the_loop(env: WorkflowEnvironment) -> None:
+    store = MemoryStore()
+    g = graph(code=ref("steps.l.error.code", default="none"))
+    g.node("l", LOOP, {"items": [1, 2, 3], "item_cap": 2}, on_error="continue")
     g.node("x", ECHO).edge("l", "x", "body")
     async with workers(env.client, store):
-        assert (await run(env.client, store, g, TRIGGER)).outputs == {"code": code}
-
-
-async def test_sub_flows_are_not_supported_yet(env: WorkflowEnvironment) -> None:
-    child = uuid.uuid4()
-    store = MemoryStore(subflows={child: SubflowInfo(child, uuid.uuid4(), {"type": "object"}, {"type": "object"})})
-    g = graph(code=ref("steps.r.error.code", default="none"))
-    g.node("r", "flow.run_workflow@1", {"workflow_id": str(child)}, on_error="continue")
-    async with workers(env.client, store):
-        assert (await run(env.client, store, g, TRIGGER)).outputs == {"code": "not_supported"}
+        assert (await run(env.client, store, g, TRIGGER)).outputs == {"code": "item_cap_exceeded"}


 async def test_a_loop_past_the_runs_iteration_cap_fails(
@@ -207,6 +191,34 @@
             outstanding.discard(event.activity_task_completed_event_attributes.scheduled_event_id)
     assert most == 1
     assert sorted(r.node_key for r in store.steps(handle.id)) == sorted(f"{k}{i}" for k in "et" for i in range(4))
+
+
+async def test_a_projection_in_flight_takes_no_units_slot(env: WorkflowEnvironment) -> None:
+    """Spec §6: 100 units in flight, and besides them one projection. A slow projection is still in flight when 105
+    more steps become ready: 99 of them start beside the slow step, so draining can wait on the full cap."""
+    store = SlowStore()
+    g = graph().node("x", "testkit.slow@1", {"seconds": 1})
+    g.node("t0", "flow.transform@1", {"fields": {"a": 1}}).node("t1", "flow.transform@1", {"fields": {"a": 2}})
+    g.edge("t0", "t1")  # when t1 settles, the projection of x's first row is in flight
+    for i in range(105):
+        g.node(f"e{i}", ECHO, {"value": i}).edge("t1", f"e{i}")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, TRIGGER)
+        await handle.result()
+        history = await handle.fetch_history()
+    kinds = {
+        e.event_id: e.activity_task_scheduled_event_attributes.activity_type.name
+        for e in history.events
+        if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
+    }
+    steps = 0
+    for event in history.events:
+        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
+            if kinds[event.activity_task_completed_event_attributes.scheduled_event_id] != PROJECT:
+                break  # the first step that ended
+        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
+            steps += kinds[event.event_id] != PROJECT
+    assert steps == 100  # the slow step and 99 others


 async def test_the_deadline_cancels_running_work(own_env: WorkflowEnvironment) -> None:
```

Create `backend/tests/apps/worker/test_run_graph_children.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Children (spec §6, 2a-3b): loops over more than 100 items run in batches of child workflows, a `run_workflow`
step runs its pinned version as a run of its own, a failed run runs its failure handler once, and every child draws
its iterations from one budget per logical run."""

import asyncio
import dataclasses
import json
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner

from dewpoint.engine.runtime import execution
from dewpoint.engine.runtime import workflow as run_graph
from dewpoint.engine.runtime.activities import ProjectInput, VersionData
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.support.graphs import G, cel, ref

ECHO, LOOP, FILTER, RUN, FAIL = "testkit.echo@1", "flow.loop@1", "flow.filter@1", "flow.run_workflow@1", "flow.fail@1"
LISTS = {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]}
NUMBER = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


def graph(schema: dict[str, Any] | None = None, **outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": schema or LISTS, "outputs": outputs}
    return g


async def finished(env: WorkflowEnvironment, store: MemoryStore, g: G, trigger: dict[str, Any]) -> tuple[Any, Any]:
    async with workers(env.client, store):
        handle = await start(env.client, store, g, trigger)
        result = await asyncio.wait_for(handle.result(), 120)
    return handle, result


async def children_started(handle: Any) -> int:
    history = await handle.fetch_history()
    return sum(e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED for e in history.events)


async def test_a_loop_over_more_than_a_hundred_items_runs_in_batches_and_collects_everything(
    env: WorkflowEnvironment,
) -> None:
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"), count=ref("steps.l.output.count"))
    g.node("a", ECHO, {"value": "from outside"}).node("b", ECHO, {"value": "never read"})
    g.node("l", LOOP, {"items": list(range(250)), "concurrency": 3, "collect": ref("item")})
    g.node("x", ECHO, {"value": ref("steps.a.output.value")}).edge("a", "b").edge("b", "l").edge("l", "x", "body")
    handle, result = await finished(env, store, g, {})
    assert result.status == "succeeded" and result.outputs == {"items": list(range(250)), "count": 250}
    assert result.iterations == 250 and await children_started(handle) == 3  # batches of 100, 100 and 50
    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
    assert sorted(r.iteration_key for r in rows) == sorted(f"l:{i}" for i in range(250))  # the inline keys
    assert {(r.status, r.output_preview["value"]) for r in rows} == {("succeeded", "from outside")}
    history = await handle.fetch_history()
    batches = [
        json.loads(e.start_child_workflow_execution_initiated_event_attributes.input.payloads[0].data)
        for e in history.events
        if e.HasField("start_child_workflow_execution_initiated_event_attributes")
    ]
    assert all(set(b["outer"][0]["results"]) == {"a"} for b in batches)  # only what the body reads goes along


async def test_a_secret_a_batch_learned_is_masked_in_its_parent_too(env: WorkflowEnvironment) -> None:
    """A batch returns the sensitive values it learned: the parent masks them where they reappear, as it would have
    learned them inline."""
    store = MemoryStore()
    g = graph()
    g.node("l", LOOP, {"items": list(range(101)), "collect": ref("steps.s.output.secret_value")})
    g.node("s", "testkit.sensitive@1").node("e", ECHO, {"value": ref("steps.l.output.items")})
    g.edge("l", "s", "body").edge("l", "e", "done")
    handle, result = await finished(env, store, g, {})
    assert result.status == "succeeded"
    [echoed] = [r for r in store.steps(handle.id) if r.node_key == "e"]
    assert "s3cr3t-value" not in json.dumps(echoed.output_preview) and "[redacted]" in json.dumps(echoed.output_preview)


@pytest.mark.parametrize(("policy", "status"), [("continue", "succeeded"), ("stop", "failed")])
async def test_a_failed_item_in_a_batch_follows_the_loops_policy(
    env: WorkflowEnvironment, policy: str, status: str
) -> None:
    store = MemoryStore()
    g = graph(failures=ref("steps.l.output.failures", default=None))
    config = {"items": list(range(150)), "on_item_error": policy}
    g.node("l", LOOP, config).node(
        "s", "testkit.ambiguous_send@1", {"outcome": cel("item == 120 ? 'rejected' : 'sent'")}
    )
    g.edge("l", "s", "body")
    _, result = await finished(env, store, g, {})
    assert result.status == status
    if policy == "continue":
        assert [f["index"] for f in result.outputs["failures"]] == [120]  # in the second batch, by its own index
    else:
        assert result.error["code"] == "testkit.rejected"


async def test_a_fail_node_inside_a_batch_ends_the_whole_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph()
    g.node("l", LOOP, {"items": list(range(150))})
    g.node("f", FAIL, {"message": "item 130 is bad"}).node("e", ECHO)
    g.node("i", "flow.if@1", {"condition": cel("item == 130")})
    g.edge("l", "i", "body").edge("i", "f", "true").edge("i", "e", "false")
    _, result = await finished(env, store, g, {})
    assert (result.status, result.error["code"], result.error["message"]) == (
        "failed",
        "workflow_failed",
        "item 130 is bad",
    )


def doubler() -> G:
    """A sub-flow: doubles its input."""
    g = graph(NUMBER, double=ref("steps.t.output.double"))
    g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    return g


async def test_a_sub_flow_is_a_run_of_its_own_and_its_outputs_are_the_steps_output(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    sub = store.publish(doubler())
    g = graph(result=ref("steps.r.output.double"))
    g.node("r", RUN, {"workflow_id": str(sub), "input": {"n": 21}})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.outputs) == ("succeeded", {"result": 42})
    [(child, row)] = store.starts.items()
    step = next(n["id"] for n in g.nodes if n["key"] == "r")
    assert (row.kind, row.parent_run_id, row.parent_step_id, row.parent_iteration_key) == (
        "subflow",
        handle.id,
        step,
        "",
    )
    assert store.runs[child].status == "succeeded"
    assert [r.node_key for r in store.steps(child)] == ["t"]  # the sub-flow's steps are its own run's


async def test_a_failed_sub_flow_fails_its_step_under_the_steps_error_policy(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    broken = graph({"type": "object"})
    broken.node("f", FAIL, {"message": "nope"})
    sub = store.publish(broken)
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub)}, on_error="continue")
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs) == ("succeeded", {"code": "workflow_failed"})


async def test_a_failed_run_runs_its_failure_handler_once_with_the_error(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    handler = graph({"type": "object", "properties": {"error": {"type": "object"}}})
    handler.node("h", ECHO, {"value": ref("trigger.error.code", default="?")})
    handler_id = store.publish(handler)
    g = graph()
    g.settings["failure_handler"] = str(handler_id)
    g.node("f", FAIL, {"message": "it went wrong"})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.error["code"]) == ("failed", "workflow_failed")  # the handler changes nothing
    [(child, row)] = store.starts.items()
    assert (row.kind, row.parent_run_id, row.parent_step_id) == ("failure_handler", handle.id, None)
    assert store.runs[child].status == "succeeded"
    [echoed] = store.steps(child)
    assert echoed.output_preview == {"value": "workflow_failed"}


async def test_a_sub_flow_asks_for_more_than_its_first_grant(env: WorkflowEnvironment) -> None:
    """Its initial grant is 1,000 iterations; a filter over 1,200 items asks its parent for the rest."""
    store = MemoryStore()
    sub = graph(kept=ref("steps.k.output.count"))
    sub.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("item % 2 == 0")})
    sub_id = store.publish(sub)
    g = graph(kept=ref("steps.r.output.kept"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": list(range(1_200))}})
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"kept": 600}, 1_200)


async def test_no_premature_rejection_one_busy_child_among_ten(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §10: with 10 child slots and one busy child, that child can use nearly the whole budget. With a cap of
    300, ten sub-flows run at once; nine filter 1 item, one filters 250, and nothing is refused."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 300)
    store = MemoryStore()
    sub = graph(n=ref("steps.k.output.count"))
    sub.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")})
    sub_id = store.publish(sub)
    g = graph(counts=ref("steps.l.output.items"))
    lists = [[0]] * 4 + [list(range(250))] + [[0]] * 5
    g.node("l", LOOP, {"items": lists, "concurrency": 10, "collect": ref("steps.r.output.n")})
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": ref("item")}}).edge("l", "r", "body")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 120)
    assert result.status == "succeeded", result.error
    assert result.outputs == {"counts": [1, 1, 1, 1, 250, 1, 1, 1, 1, 1]}
    assert result.iterations == 10 + 9 + 250


async def test_a_need_waits_for_an_asking_sub_flow_that_holds_enough(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkpoint-1 review, end to end: with a cap of 10, the sub-flow is granted 6. The run's own filter needs 8,
    and waits while the sub-flow may still release. Then the sub-flow asks for 5 more, reporting the 6 it holds. The
    run refuses the sub-flow, which ends having used nothing, and the filter gets its 8. Before, both were refused."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 10)
    monkeypatch.setattr(execution, "SUBFLOW_GRANT", 6)
    store = MemoryStore()
    sub = graph(n=ref("steps.k.output.count"))
    sub.node("s", "testkit.slow@1", {"seconds": 2})  # it asks once the run's filter is waiting
    sub.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")}).edge("s", "k")
    sub_id = store.publish(sub)
    g = graph(kept=ref("steps.f.output.count"), code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": list(range(11))}}, on_error="continue")
    g.node("s", "testkit.slow@1", {"seconds": 1}).node("f", FILTER, {"items": list(range(8)), "predicate": cel("true")})
    g.edge("s", "f")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 8, "code": "iteration_cap_exceeded"})
    assert result.iterations == 8


async def test_a_need_waits_for_what_an_asking_sub_flows_own_sub_flow_holds(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checkpoint-1 re-review, end to end: with a cap of 10, the run grants 6 to `mid`, which grants all 6 to its own
    sub-flow `leaf`. The run's filter needs 8, `mid`'s 7 and `leaf`'s 8. `leaf` asks holding 6, and `mid` asks
    holding nothing itself but reporting its leaf's 6. The run refuses `mid`, whose subtree ends having used nothing,
    and the run's filter gets its 8. Before, `mid` reported 0 and the run refused its filter too."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 10)
    monkeypatch.setattr(execution, "SUBFLOW_GRANT", 6)
    store = MemoryStore()
    leaf = graph(n=ref("steps.k.output.count"))
    leaf.node("s", "testkit.slow@1", {"seconds": 2})  # it asks once both filters above it are waiting
    leaf.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")}).edge("s", "k")
    leaf_id = store.publish(leaf)
    mid = graph(n=ref("steps.k.output.count"))
    mid.node("r", RUN, {"workflow_id": str(leaf_id), "input": {"items": ref("trigger.items")}}, on_error="continue")
    mid.node("s", "testkit.slow@1", {"seconds": 1}).node(
        "k", FILTER, {"items": list(range(7)), "predicate": cel("true")}
    )
    mid.edge("s", "k")
    mid_id = store.publish(mid)
    g = graph(kept=ref("steps.f.output.count"), code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(mid_id), "input": {"items": list(range(8))}}, on_error="continue")
    g.node("s", "testkit.slow@1", {"seconds": 1}).node("f", FILTER, {"items": list(range(8)), "predicate": cel("true")})
    g.edge("s", "f")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 8, "code": "iteration_cap_exceeded"})
    assert result.iterations == 8


@dataclasses.dataclass
class SlowEnds(MemoryStore):
    """A run's end takes a while to write: a sub-run that's cancelled takes that long to report back."""

    async def project(self, data: ProjectInput) -> None:
        if data.run is not None:
            await asyncio.sleep(1)
        await super().project(data)


async def test_a_cancel_while_the_run_waits_for_a_cancelled_sub_flow_to_report_back(env: WorkflowEnvironment) -> None:
    """Found in checkpoint 1's end-to-end test: the run fails, which cancels its running sub-flow, and waits for it to
    report back. A cancel of the run meanwhile reached that wait and cancelled the sub-flow a second time: Temporal
    refused the duplicate request, so the run's workflow task could never complete, and the run hung. The run's
    failure stands, and the sub-flow is cancelled once."""
    store = SlowEnds()
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(store.publish(sleeper()))}, on_error="continue")
    g.node("s", "testkit.slow@1", {"seconds": 1}).node("f", FAIL, {"message": "it went wrong"}).edge("s", "f")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        for _ in range(200):  # until the run has cancelled its sub-flow
            if await child_cancels(handle):
                break
            await asyncio.sleep(0.05)
        await handle.cancel()  # while the sub-flow is still writing its end
        result = await asyncio.wait_for(handle.result(), 30)
    assert (result.status, result.error["code"]) == ("failed", "workflow_failed")
    assert await child_cancels(handle) == 1


async def child_cancels(handle: Any) -> int:
    """How many times the run has asked Temporal to cancel a child."""
    history = await handle.fetch_history()
    return sum(
        e.HasField("request_cancel_external_workflow_execution_initiated_event_attributes") for e in history.events
    )


async def test_the_cap_holds_across_children(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> None:
    """One cap for the logical run: past it, the child that can't be served fails with `iteration_cap_exceeded`."""
    monkeypatch.setattr(run_graph, "ITERATION_CAP", 100)
    store = MemoryStore()
    sub = graph(n=ref("steps.k.output.count"))
    sub.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")})
    sub_id = store.publish(sub)
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": list(range(150))}}, on_error="continue")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 120)
    assert (result.status, result.outputs) == ("succeeded", {"code": "iteration_cap_exceeded"})
    assert result.iterations <= 100


# --- the plan's Review Focus: inputs a user meets that nothing above covers -------------------------------------


def sleeper() -> G:
    """A sub-flow that waits an hour: it's still running when the test acts on it."""
    g = graph({"type": "object"})
    g.node("d", "flow.delay@1", {"duration_s": 3600})
    return g


async def children_running(handle: Any, n: int) -> None:
    """Wait (in real time: nothing skips it) until `n` children have started."""
    for _ in range(200):
        if await children_started(handle) >= n:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"fewer than {n} children started")


async def test_cancelling_a_run_cancels_its_children_and_each_reports_back(env: WorkflowEnvironment) -> None:
    """A cancel reaches a sub-flow and a loop batch alike: each ends cancelled and returns its result (its usage)
    before the run ends, and the sub-run's own row says `cancelled`."""
    store = MemoryStore()
    sub = store.publish(sleeper())
    g = graph()
    g.node("r", RUN, {"workflow_id": str(sub)})
    g.node("l", LOOP, {"items": list(range(150))}).node("w", "flow.delay@1", {"duration_s": 3600})
    g.edge("l", "w", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await children_running(handle, 2)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 60)
    history = await handle.fetch_history()
    kinds = [e.event_type for e in history.events]
    assert kinds.count(EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED) == 2  # both reported back
    assert kinds.index(EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED) > max(
        i for i, k in enumerate(kinds) if k == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED
    )
    [(child, _)] = store.starts.items()
    assert (store.runs[handle.id].status, store.runs[child].status) == ("cancelled", "cancelled")


async def test_a_batched_loop_inside_a_loop_runs_its_own_batches_per_iteration(env: WorkflowEnvironment) -> None:
    """Batch ids name the enclosing iteration: two outer iterations run two batched inner loops side by side."""
    store = MemoryStore()
    g = graph(counts=ref("steps.outer.output.items"))
    g.node("outer", LOOP, {"items": [0, 1], "concurrency": 2, "collect": ref("steps.inner.output.count")})
    g.node("inner", LOOP, {"items": list(range(150))}).node("x", ECHO, {"value": ref("item")})
    g.edge("outer", "inner", "body").edge("inner", "x", "body")
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"counts": [150, 150]}, 302)
    assert await children_started(handle) == 4
    keys = {r.iteration_key for r in store.steps(handle.id) if r.node_key == "x"}
    assert keys == {f"outer:{o}/inner:{i}" for o in (0, 1) for i in range(150)}


@dataclasses.dataclass
class LaterLoadsUnusable(MemoryStore):
    """The version loads for the run, and fails to compile for anything that loads it later: a batch here."""

    loads: int = 0

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        self.loads += 1
        data = await super().version(tenant_id, version_id)
        return data if self.loads == 1 else dataclasses.replace(data, manifests={})


async def test_a_batch_that_fails_as_a_workflow_fails_its_loop_and_its_whole_grant_stays_used(
    env: WorkflowEnvironment,
) -> None:
    """A child that fails as a workflow never reports its usage (a terminated child is the other case, which the
    time-skipping server never reports to the parent): its loop fails with the child's code, and the run counts the
    child's whole grant (spec §6, settlement)."""
    store = LaterLoadsUnusable()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", LOOP, {"items": list(range(150))}, on_error="continue").node("x", ECHO)
    g.edge("l", "x", "body")
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "version_unusable"}, 100)


async def test_a_sub_flow_of_a_sub_flow_asks_up_the_chain(env: WorkflowEnvironment) -> None:
    """The inner sub-flow's filter needs more than both grants: it asks its parent, which asks the root."""
    store = MemoryStore()
    inner = graph(kept=ref("steps.k.output.count"))
    inner.node("k", FILTER, {"items": ref("trigger.items"), "predicate": cel("true")})
    inner_id = store.publish(inner)
    middle = graph(kept=ref("steps.r.output.kept"))
    middle.node("r", RUN, {"workflow_id": str(inner_id), "input": {"items": ref("trigger.items")}})
    middle_id = store.publish(middle)
    g = graph(kept=ref("steps.r.output.kept"))
    g.node("r", RUN, {"workflow_id": str(middle_id), "input": {"items": list(range(1_500))}})
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"kept": 1_500}, 1_500)


async def test_a_batched_loop_in_a_sub_flow_writes_into_the_sub_run(env: WorkflowEnvironment) -> None:
    """A batch writes into the run that holds its loop: here the sub-run, not the root."""
    store = MemoryStore()
    sub = graph(n=ref("steps.l.output.count"))
    sub.node("l", LOOP, {"items": ref("trigger.items")}).node("x", ECHO, {"value": ref("item")})
    sub.edge("l", "x", "body")
    sub_id = store.publish(sub)
    g = graph(n=ref("steps.r.output.n"))
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": list(range(150))}})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"n": 150}, 150)
    [(child, _)] = store.starts.items()
    assert len([r for r in store.steps(child) if r.node_key == "x"]) == 150
    assert not [r for r in store.steps(handle.id) if r.node_key == "x"]


# --- the owner's plan review: every end at a child's boundary is recorded ----------------------------------------


@dataclasses.dataclass
class SlowToLoad(MemoryStore):
    """Some versions never finish loading: their run is cancelled while they load."""

    stuck: set[str] = dataclasses.field(default_factory=set)

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        if version_id in self.stuck:
            await asyncio.Event().wait()
        return await super().version(tenant_id, version_id)


async def test_a_sub_flow_whose_version_does_not_load_still_has_its_row(env: WorkflowEnvironment) -> None:
    """A sub-run writes its row before its version loads, so one that ends right there still shows, with its end."""
    store = MemoryStore()
    sub = store.publish(doubler())
    del store.versions[str(store.subflows[sub].version_id)]  # gone: the loader can't find it
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", RUN, {"workflow_id": str(sub), "input": {"n": 1}}, on_error="continue")
    _, result = await finished(env, store, g, {})
    assert (result.status, result.outputs) == ("succeeded", {"code": "version_unusable"})
    [(child, row)] = store.starts.items()
    assert (row.kind, row.workflow_id) == ("subflow", str(sub))
    assert (store.runs[child].status, store.runs[child].error_code) == ("failed", "version_unusable")


async def test_a_sub_flow_cancelled_while_its_version_loads_still_has_its_row(env: WorkflowEnvironment) -> None:
    store = SlowToLoad()
    sub = store.publish(doubler())
    store.stuck.add(str(store.subflows[sub].version_id))
    g = graph()
    g.node("r", RUN, {"workflow_id": str(sub), "input": {"n": 1}})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await children_running(handle, 1)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 60)
    [(child, row)] = store.starts.items()
    assert (row.kind, store.runs[child].status) == ("subflow", "cancelled")


async def test_a_cancel_while_the_failure_handler_runs_leaves_the_run_failed(env: WorkflowEnvironment) -> None:
    """The run's end is decided before its handler starts. A cancel then cancels the handler, which reports back
    with what it used (decision 19), and the run stays `failed`, in Temporal and in its row."""
    store = MemoryStore()
    handler = graph({"type": "object"})
    handler.node("k", FILTER, {"items": list(range(30)), "predicate": cel("true")})  # some work first
    handler.node("d", "flow.delay@1", {"duration_s": 3_600}).edge("k", "d")
    g = graph()
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("f", FAIL, {"message": "it went wrong"})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        child = await settled(store, "k")  # the handler has done its work, and waits
        await handle.cancel()
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.error["code"], result.iterations) == ("failed", "workflow_failed", 30)
    assert (store.runs[handle.id].status, store.runs[handle.id].iterations) == ("failed", 30)
    assert (store.runs[child].status, store.runs[child].iterations) == ("cancelled", 30)


async def settled(store: MemoryStore, key: str) -> str:
    """Wait (in real time) until a sub-run's step `key` has settled: that sub-run's id."""
    for _ in range(200):
        for child in store.starts:
            if any(r.node_key == key for r in store.steps(child)):
                return child
        await asyncio.sleep(0.05)
    raise AssertionError(f"no sub-run settled `{key}`")


@dataclasses.dataclass
class Ordered(MemoryStore):
    """Records the order runs start and end in, as their rows are written."""

    log: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    async def project(self, data: ProjectInput) -> None:
        await super().project(data)
        if data.start is not None:
            self.log.append(("start", data.start.run_id))
        if data.run is not None:
            self.log.append(("end", data.run.run_id))


async def test_a_failed_run_stays_non_terminal_until_its_failure_handler_has_ended(env: WorkflowEnvironment) -> None:
    """Spec §4.5: a non-terminal run's closure keeps the CEL profiles it pins in use. The failed run's row stays
    non-terminal until its handler's own row exists and has ended, so the handler never starts, or runs, with nothing
    holding its profile."""
    store = Ordered()
    handler = graph({"type": "object"})
    handler.node("h", ECHO, {"value": 1})
    g = graph()
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("f", FAIL, {"message": "it went wrong"})
    handle, result = await finished(env, store, g, {})
    [(child, _)] = store.starts.items()
    assert store.log.index(("start", child)) < store.log.index(("end", child)) < store.log.index(("end", handle.id))
    assert (result.status, store.runs[handle.id].status) == ("failed", "failed")


async def test_a_failure_handlers_iterations_count_toward_its_run(env: WorkflowEnvironment) -> None:
    """One budget per logical run: the run's result and its row count what its handler used."""
    store = MemoryStore()
    handler = graph({"type": "object"})
    handler.node("k", FILTER, {"items": list(range(50)), "predicate": cel("true")})
    g = graph()
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("f", FAIL, {"message": "it went wrong"})
    handle, result = await finished(env, store, g, {})
    assert (result.status, result.iterations, store.runs[handle.id].iterations) == ("failed", 50, 50)


async def test_a_run_past_its_deadline_runs_its_failure_handler(env: WorkflowEnvironment) -> None:
    """The owner's ruling: `deadline_exceeded` runs the handler too, with a deadline of its own."""
    store = MemoryStore()
    handler = graph({"type": "object"})
    handler.node("h", ECHO, {"value": ref("trigger.error.code", default="?")})
    g = graph()
    g.settings["failure_handler"] = str(store.publish(handler))
    g.node("d", "flow.delay@1", {"duration_s": 3 * 86_400})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, max_run_duration_s=86_400)
        result = await asyncio.wait_for(handle.result(), 60)
    assert result.status == "deadline_exceeded"
    [(child, row)] = store.starts.items()
    assert row.kind == "failure_handler"
    assert [r.output_preview for r in store.steps(child)] == [{"value": "deadline_exceeded"}]


async def test_a_cancelled_run_runs_no_failure_handler(env: WorkflowEnvironment) -> None:
    """The owner's ruling: an explicit cancel is not a failure."""
    store = MemoryStore()
    g = graph()
    g.settings["failure_handler"] = str(store.publish(sleeper()))
    g.node("d", "flow.delay@1", {"duration_s": 3_600})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {})
        await asyncio.sleep(0.2)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 60)
    assert (store.runs[handle.id].status, store.starts) == ("cancelled", {})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_main.py tests/apps/worker/test_run_graph_children.py tests/apps/worker/test_run_graph_policies.py tests/engine/runtime/test_nodes.py`
Expected: four collection errors:
- `ImportError: cannot import name 'SubflowStart' from 'dewpoint.engine.runtime.nodes'`;
- `ImportError: cannot import name 'LoopBatch' from 'dewpoint.engine.runtime.workflow'`, three times (through the
  harness).

- [ ] **Step 3: The contracts and the decisions**

In `backend/src/dewpoint/engine/runtime/activities.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/activities.py b/backend/src/dewpoint/engine/runtime/activities.py
--- a/backend/src/dewpoint/engine/runtime/activities.py
+++ b/backend/src/dewpoint/engine/runtime/activities.py
@@ -1,7 +1,10 @@
 # SPDX-License-Identifier: Apache-2.0
 """What `RunGraph` asks of the outside world, as names and dataclasses (spec §2): the version loader, plugin steps,
 `cel.evaluate` and the projection. `apps/worker` implements them; the workflow only names them. A plugin step's
-activity runs one attempt and writes nothing; the projection is the only activity that writes."""
+activity runs one attempt and writes nothing; the projection is the only activity that writes.
+
+Also the contracts between executions (2a-3b): a child's input and result (a sub-flow or failure handler is a
+`RunGraph`; a loop batch is a `LoopBatch`), and the budget signals a child and its parent exchange."""

 from dataclasses import dataclass, field
 from typing import Any
@@ -12,6 +15,11 @@
 CEL_EVALUATE = "cel.evaluate"
 LIVE, SIMULATE = "live", "simulate"
 APPLIED, SIMULATED, OUTCOME_UNKNOWN = "applied", "simulated", "outcome_unknown"
+SUBFLOW, FAILURE_HANDLER, BATCH = "subflow", "failure_handler", "batch"  # the kinds of child execution
+REQUEST_BUDGET, BUDGET = (
+    "request_budget",
+    "budget",
+)  # child -> parent (child, key, need, want, held); parent -> child (key, granted)
 # In a plugin step's failure details: the activity's own mapping made this failure. `RunGraph` trusts no other failure
 # as the node's: the SDK makes its own (a worker shutting down, an exception nothing caught), and those say nothing
 # of whether the request went out.
@@ -29,6 +37,21 @@


 @dataclass(frozen=True)
+class Parent:
+    """How a child execution reaches its parent, and what it inherits from it."""
+
+    workflow_id: str  # where its budget requests go
+    run_id: str  # the parent run: a sub-run's row points at it
+    step_id: str  # the step that started it; empty for a failure handler
+    iteration_key: str
+    kind: str  # subflow | failure_handler | batch
+    deadline: str  # ISO 8601: the logical run's deadline, which children share (a failure handler gets its own)
+    grant: int  # the iterations its parent reserved for it
+    depth: int = 1  # sub-flows nest at most 5 deep (spec §6)
+    secrets: list[str] = field(default_factory=list)  # sensitive values the parent learned, masked here too
+
+
+@dataclass(frozen=True)
 class RunInput:
     tenant_id: str
     run_id: str
@@ -37,6 +60,8 @@
     mode: str = LIVE  # live | simulate
     max_run_duration_s: float = 30 * 86_400
     cel_schedule_to_start_s: float = 600  # no evaluator for the profile after this: cel_profile_unavailable
+    parent: Parent | None = None  # a sub-flow or a failure handler; None for a run the dispatcher started
+    workflow_id: str = ""  # a sub-run's workflow: it writes its own row with it, before its version loads


 @dataclass(frozen=True)
@@ -45,6 +70,39 @@
     outputs: dict[str, Any] | None = None
     error: dict[str, Any] | None = None  # {code, message}
     iterations: int = 0
+    secrets: list[str] = field(default_factory=list)  # what it learned: its parent masks them too
+
+
+@dataclass(frozen=True)
+class BatchInput:
+    """A slice of a loop, for a `LoopBatch` child: items `offset` .. `offset + len(items)`. It reads the loop's
+    enclosing scopes as `outer` (outermost first, the loop's own scope last) and writes its rows into `run_id`."""
+
+    tenant_id: str
+    run_id: str
+    version_id: str
+    loop_step: str
+    outer: list[dict[str, Any]]  # {key, results, item, index} per enclosing scope
+    items: list[Any]
+    offset: int
+    concurrency: int
+    stop_on_error: bool
+    trigger: dict[str, Any]
+    variables: dict[str, Any]
+    run_started_at: str
+    parent: Parent
+    mode: str = LIVE
+    cel_schedule_to_start_s: float = 600
+
+
+@dataclass(frozen=True)
+class BatchResult:
+    collected: list[Any]
+    failures: list[dict[str, Any]]
+    stopped: dict[str, Any] | None = None  # the failure that stopped the slice (`on_item_error: stop`)
+    end: dict[str, Any] | None = None  # the run ended inside the batch (a fail or stop node, the deadline)
+    iterations: int = 0
+    secrets: list[str] = field(default_factory=list)


 @dataclass(frozen=True)
@@ -61,6 +119,8 @@
     expressions: list[dict[str, Any]]
     cel_profile: str
     manifests: dict[str, dict[str, Any]]  # type@version -> manifest, for every node type in the graph
+    subflow_version_ids: dict[str, str] = field(default_factory=dict)  # run_workflow node id -> pinned version id
+    failure_handler_version_id: str | None = None


 @dataclass(frozen=True)
@@ -123,7 +183,23 @@


 @dataclass(frozen=True)
+class RunStart:
+    """A sub-run's own `runs` row: written with its first projection, before any of its steps."""
+
+    run_id: str
+    workflow_id: str
+    version_id: str
+    mode: str
+    parent_run_id: str
+    parent_step_id: str | None
+    parent_iteration_key: str
+    kind: str  # subflow | failure_handler
+    started_at: str
+
+
+@dataclass(frozen=True)
 class ProjectInput:
     tenant_id: str
     steps: list[StepRow] = field(default_factory=list)
     run: RunSummary | None = None
+    start: RunStart | None = None
```

In `backend/src/dewpoint/engine/runtime/nodes.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/nodes.py b/backend/src/dewpoint/engine/runtime/nodes.py
--- a/backend/src/dewpoint/engine/runtime/nodes.py
+++ b/backend/src/dewpoint/engine/runtime/nodes.py
@@ -11,10 +11,9 @@
 from dewpoint.engine.registry import control
 from dewpoint.engine.runtime.scheduler import Failure, RunEnd

-INLINE_ITEMS = 100  # larger loops run as batches of child workflows (2a-3b)
+INLINE_ITEMS = 100  # larger loops run in batches of this many items, one child workflow per batch (spec §6)
 MAX_DELAY_S = 30 * 86_400  # flow.delay's own bound: a value resolved at run time isn't checked by its schema
 ITEM_CAP_EXCEEDED = "item_cap_exceeded"
-NOT_SUPPORTED = "not_supported"  # until 2a-3b: sub-flows, loops over more than INLINE_ITEMS items
 WORKFLOW_FAILED = "workflow_failed"  # a fail node ended the run


@@ -23,6 +22,16 @@
     items: list[Any]
     concurrency: int
     stop_on_error: bool
+    batch: int = 0  # > 0: the items run in child workflows of this many
+
+
+@dataclass(frozen=True)
+class SubflowStart:
+    """A `run_workflow` step: its pinned version runs as a child with this input. `workflow_id` is the sub-flow's
+    workflow, which the child's own row names before its version loads."""
+
+    input: dict[str, Any]
+    workflow_id: str


 @dataclass(frozen=True)
@@ -35,6 +44,7 @@
     wait_until: datetime | None = None  # UTC
     loop: LoopStart | None = None
     filter_items: list[Any] | None = None  # a filter: evaluate its predicate per item
+    subflow: SubflowStart | None = None
     failure: Failure | None = None


@@ -91,21 +101,19 @@
         cap = int(config.get("item_cap", 10_000))
         if len(items) > cap:
             return Decision(failure=Failure(ITEM_CAP_EXCEEDED, f"{len(items)} items exceed this loop's cap of {cap}."))
-        if len(items) > INLINE_ITEMS:
-            return Decision(
-                failure=Failure(
-                    NOT_SUPPORTED, f"Loops over more than {INLINE_ITEMS} items run in batches, which this build lacks."
-                )
-            )
-        start = LoopStart(items, int(config.get("concurrency", 1)), config.get("on_item_error", "stop") == "stop")
-        return Decision(loop=start)
+        batch = INLINE_ITEMS if len(items) > INLINE_ITEMS else 0
+        stop = config.get("on_item_error", "stop") == "stop"
+        return Decision(loop=LoopStart(items, int(config.get("concurrency", 1)), stop, batch))
     if ref == control.FILTER:
         items = config.get("items")
         if not isinstance(items, list):
             return _mismatch("`items` must be a list.")
         return Decision(filter_items=items)
     if ref == control.RUN_WORKFLOW:
-        return Decision(failure=Failure(NOT_SUPPORTED, "Sub-flows need a build that runs them."))
+        data = config.get("input", {})
+        if not isinstance(data, dict):
+            return _mismatch("`input` must be an object.")
+        return Decision(subflow=SubflowStart(dict(data), str(config.get("workflow_id", ""))))
     raise ValueError(f"{ref} isn't a control node")


@@ -113,9 +121,9 @@
     "INLINE_ITEMS",
     "MAX_DELAY_S",
     "ITEM_CAP_EXCEEDED",
-    "NOT_SUPPORTED",
     "WORKFLOW_FAILED",
     "Decision",
     "LoopStart",
+    "SubflowStart",
     "decide",
 ]
```

- [ ] **Step 4: The shared execution**

Create `backend/src/dewpoint/engine/runtime/execution.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What every execution of a graph shares (spec §6): a run, a sub-flow and a failure handler (`RunGraph`), and a loop
batch (`LoopBatch`). Each drives its scheduler until it ends: every ready step runs as one future (its values
resolved, then a control node decides, a plugin step runs as its activity, a sub-flow or a batch runs as a child).
At most IN_FLIGHT_CAP futures are outstanding, plus one projection; completions are applied in (scope, topological)
order, so a replay applies them the same way. Nothing else creates concurrency.

Children draw their iterations from their parent's budget (spec §6): a child signals `request_budget` to its parent,
which answers `budget` in the order the requests reach its history."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError, TimeoutError
from temporalio.exceptions import CancelledError as ActivityCancelled

with workflow.unsafe.imports_passed_through():
    from dewpoint.engine.canonical import canonical_json
    from dewpoint.engine.cel import evaluate as cel
    from dewpoint.engine.cel.profile import LOCAL_CEL_PROFILE
    from dewpoint.engine.cel.route import YieldBudget
    from dewpoint.engine.graph.values import CelValue, RefValue, TemplateValue
    from dewpoint.engine.runtime import nodes, resolve
    from dewpoint.engine.runtime.activities import (
        BATCH,
        BUDGET,
        CEL_EVALUATE,
        ENGINE_QUEUE,
        MAPPED,
        OUTCOME_UNKNOWN,
        PROJECT,
        REQUEST_BUDGET,
        SUBFLOW,
        BatchInput,
        BatchResult,
        CelInput,
        CelResult,
        Parent,
        ProjectInput,
        RunInput,
        RunResult,
        RunStart,
        RunSummary,
        StepInput,
        StepResult,
        StepRow,
        cel_queue,
        step_activity,
    )
    from dewpoint.engine.runtime.budget import LOCAL, Need
    from dewpoint.engine.runtime.program import Program, Step
    from dewpoint.engine.runtime.projection import (
        Secrets,
        mask,
        preview,
        remember,
        sanitize,
        sensitive_values,
        storable,
    )
    from dewpoint.engine.runtime.scheduler import (
        CAP_MESSAGE,
        ITERATION_CAP_EXCEEDED,
        Batch,
        BatchOutcome,
        Collect,
        Failure,
        Instance,
        RunEnd,
        Scheduler,
        ScopeKey,
        iteration_key,
    )

IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
PROJECT_BYTES = 256 * 1024  # a projection's rows at most, as JSON: far below Temporal's 2 MiB payload limit
CEL_BATCH = 1_000  # binding sets per cel.evaluate request
SUBFLOW_GRANT = 1_000  # a sub-flow's initial grant (spec §6)
MAX_DEPTH = 5  # sub-flows nest at most this deep (spec §6; publish checks it too)
DEADLINE_EXCEEDED = "deadline_exceeded"
VERSION_UNUSABLE = "version_unusable"  # this build can't load or compile the version
INTERNAL_ERROR = "internal_error"  # an exception in workflow code: a bug
NODE_TYPE_UNAVAILABLE = "node_type_unavailable"  # the registry has it, but this build's workers don't run it
CANCELLED = Failure("cancelled", "The run was cancelled.")
AMBIGUOUS = "ambiguous"  # a manifest's side_effect: the request may have been sent


@dataclass(frozen=True)
class _Effect:
    """How a future ended; applied to the scheduler in order."""

    output: Any = None
    ports: tuple[str, ...] | None = None
    variables: Mapping[str, Any] | None = None
    failure: Failure | None = None
    end: RunEnd | None = None
    loop: nodes.LoopStart | None = None
    collected: Any = None
    cel_mode: str | None = None
    batch: BatchOutcome | None = None


def _attempt_failed(
    error: ActivityError, key: str, attempt: int, *, ambiguous: bool, non_retryable: Sequence[str]
) -> tuple[Failure, str | None, bool]:
    """How one attempt failed: (the failure, its outcome, whether another attempt may follow)."""
    cause = error.cause
    if isinstance(cause, ApplicationError) and cause.type == "NotFoundError":  # the SDK: no such activity here
        return Failure(NODE_TYPE_UNAVAILABLE, f"No worker of this build runs `{key}`'s node type.", attempt), None, True
    details = cause.details[0] if isinstance(cause, ApplicationError) and cause.details else None
    if isinstance(cause, ApplicationError) and isinstance(details, dict) and details.get(MAPPED) is True:
        code = cause.type or "error"  # the node's own error, mapped by the activity
        retryable = not cause.non_retryable and code not in non_retryable
        return Failure(code, cause.message, attempt), details.get("outcome"), retryable
    # Anything else: a timeout, a worker lost or shutting down, a failure the activity never mapped. The node may have
    # done its work, and nothing that saw what happened described it.
    code, message = (
        (cel.TIMEOUT, f"`{key}` didn't finish in time.")
        if isinstance(cause, TimeoutError)
        else (
            "error",
            f"`{key}` ended without a result.",
        )
    )
    if ambiguous:  # the request may have been sent: never repeat it (parent §6.6)
        return Failure(code, f"{message} Its request may have been sent.", attempt), OUTCOME_UNKNOWN, False
    return Failure(code, message, attempt), None, True


def _cancelled(e: BaseException) -> bool:
    """Our own cancel, as the SDK reports it: `CancelledError` when the awaited activity had already finished in the
    same activation, an `ActivityError` caused by Temporal's `CancelledError` otherwise."""
    return isinstance(e, asyncio.CancelledError) or (
        isinstance(e, ActivityError) and isinstance(e.cause, ActivityCancelled)
    )


def _backoff(retry: Mapping[str, Any], attempt: int) -> float:
    """Seconds before attempt `attempt + 1`, from the manifest's retry settings."""
    delay = float(retry["initial_interval_s"]) * float(retry["backoff"]) ** (attempt - 1)
    return min(delay, float(retry["max_interval_s"]))


async def _landed(work: "asyncio.Future[Any]") -> bool:
    """Wait for `work` whatever cancels arrive meanwhile: it isn't cancelled, and it completes. True when a cancel
    arrived."""
    cancelled = False
    while True:
        try:
            await asyncio.shield(work)
            return cancelled
        except asyncio.CancelledError:
            if work.cancelled():
                raise
            cancelled = True


def child_options(child_id: str) -> dict[str, Any]:
    """Every child: on the engine queue, started once, and never outliving its parent. A cancelled child reports
    back before the parent carries on, so its iterations are always counted."""
    return {
        "id": child_id,
        "task_queue": ENGINE_QUEUE,
        "parent_close_policy": workflow.ParentClosePolicy.REQUEST_CANCEL,
        "cancellation_type": workflow.ChildWorkflowCancellationType.WAIT_CANCELLATION_COMPLETED,
        "retry_policy": RetryPolicy(maximum_attempts=1),
    }


class Execution:
    """The drive loop and everything it runs. A subclass sets the context (`_context`) and a scheduler, then drives."""

    program: Program
    sched: Scheduler

    def __init__(self) -> None:
        self._yield = YieldBudget()
        self._rows: dict[tuple[str, str, int], StepRow] = {}  # queued for the next projection, per attempt
        self._secrets: Secrets = ()  # sensitive values seen so far: masked in everything projected
        self._started: dict[Instance, str] = {}
        self._cel_modes: dict[Instance, str] = {}
        self._projects = 0
        self._mail: list[Need] = []  # children's budget requests, as their signals arrived
        self._answers: list[tuple[str, int]] = []  # our parent's answers
        self._ask: str | None = None  # the request we sent our parent, unanswered
        self._asks = 0
        self._dirty = False  # a unit changed the budget: serve it
        self._filters: dict[str, asyncio.Future[int]] = {}  # a filter's budget need -> its answer
        self._signals: list[asyncio.Task[None]] = []
        self._cancelled = 0
        self._batches: dict[
            tuple[Instance, int], Batch
        ] = {}  # a batch unit's key -> the batch (its items aren't hashable)

    # --- the budget signals ----------------------------------------------------------------------------------------

    @workflow.signal(name=REQUEST_BUDGET)
    def request_budget(self, child: str, key: str, need: int, want: int, held: int) -> None:
        self._mail.append(Need(child, key, need, want, held))

    @workflow.signal(name=BUDGET)
    def budget(self, key: str, granted: int) -> None:
        self._answers.append((key, granted))

    # --- the context -----------------------------------------------------------------------------------------------

    def _context(
        self,
        *,
        tenant_id: str,
        run_id: str,
        version_id: str,
        mode: str,
        trigger: dict[str, Any],
        cel_schedule_to_start_s: float,
        max_run_duration_s: float,
        parent: Parent | None,
        run_started_at: datetime,
        deadline: datetime,
    ) -> None:
        self.tenant_id, self.run_id, self.version_id, self.mode = tenant_id, run_id, version_id, mode
        self.trigger = trigger
        self.cel_schedule_to_start_s = cel_schedule_to_start_s
        self.max_run_duration_s = max_run_duration_s
        self.parent = parent
        self.depth = parent.depth if parent is not None else 0
        self.run_started_at, self.deadline = run_started_at, deadline
        self.vars: dict[str, Any] = {}
        if parent is not None:
            self._secrets = remember((), tuple(parent.secrets))

    # --- the scheduler loop ----------------------------------------------------------------------------------------

    async def _drive(self) -> None:
        """Drive the scheduler until the execution ends."""
        tasks: dict[tuple[Any, ...], asyncio.Task[_Effect | None]] = {}
        waiting: list[tuple[Any, ...]] = []
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (self.deadline - workflow.now()).total_seconds())))
        try:
            while self.sched.ended is None:
                self._serve_budget()
                waiting += [("step", i) for i in self.sched.take_ready()]
                waiting += [("collect", c) for c in self.sched.take_collects()]
                for b in self.sched.take_batches():
                    self._batches[(b.loop, b.start)] = b
                    waiting.append(("batch", b.loop, b.start))
                for inst in self.sched.take_cancels():
                    for key in [k for k in tasks if k[0] in ("step", "batch") and self._owner(k) == inst]:
                        task = tasks.pop(key)
                        task.cancel()  # a child reports back first: the unit stays outstanding until it does
                        self._cancelled += 1
                        tasks[("cancelled", self._cancelled)] = task
                waiting = [w for w in waiting if not self._gone(w)]
                waiting.sort(key=self._rank)
                self._queue_settled()
                if self.sched.ended is not None:
                    break
                while waiting and self._in_flight(tasks) < IN_FLIGHT_CAP:
                    unit = waiting.pop(0)
                    tasks[unit] = asyncio.create_task(self._unit(unit))
                if self._rows and not any(key[0] == "project" for key in tasks):  # one at a time: rows wait for it
                    self._projects += 1
                    tasks[("project", self._projects)] = asyncio.create_task(self._project(self._take_rows()))
                if not tasks:
                    raise RuntimeError("nothing is running and the run hasn't ended")
                wake = asyncio.create_task(
                    workflow.wait_condition(lambda: bool(self._mail or self._answers or self._dirty))
                )
                done, _ = await workflow.wait([*tasks.values(), clock, wake], return_when=asyncio.FIRST_COMPLETED)
                wake.cancel()
                self._yield.reset()
                if clock in done:
                    self.sched.end(
                        RunEnd(DEADLINE_EXCEEDED, Failure(DEADLINE_EXCEEDED, "The run passed its deadline."))
                    )
                    break
                for key in sorted((k for k, t in tasks.items() if t in done), key=self._rank):
                    effect = tasks.pop(key).result()
                    if effect is not None and key[0] != "cancelled":
                        self._apply(key, effect)
        finally:
            clock.cancel()
            for key, task in tasks.items():
                if key[0] not in ("project", "cancelled"):
                    task.cancel()
            # Each outstanding unit reports back first, a cancelled child included. A cancel of this execution meanwhile
            # mustn't reach them again: Temporal refuses a second cancel of the same child, and then this workflow
            # task could never complete. An end already decided stands.
            await _landed(asyncio.gather(*tasks.values(), return_exceptions=True))

    @staticmethod
    def _in_flight(tasks: Mapping[tuple[Any, ...], asyncio.Task[Any]]) -> int:
        """The units outstanding: the in-flight cap counts them, not the one projection beside them (spec §6)."""
        return sum(1 for key in tasks if key[0] != "project")

    def _owner(self, key: tuple[Any, ...]) -> Instance:
        owner: Instance = key[1]  # a step's instance, or a batch's loop
        return owner

    def _rank(self, key: tuple[Any, ...]) -> tuple[Any, ...]:
        if key[0] == "step":
            return (self.sched.order(key[1]), 0)
        if key[0] == "collect":
            c: Collect = key[1]
            return (self.sched.order(Instance(c.scope, c.loop.step)), 1)
        if key[0] == "batch":
            return (self.sched.order(key[1]), 2, key[2])
        return ((), 3, key[1])

    def _gone(self, unit: tuple[Any, ...]) -> bool:
        """A queued unit whose scope has ended since: it never starts."""
        key = unit[1].scope  # a step's, a batch's loop's, or a collect's own
        scope = self.sched.scopes.get(key)
        return scope is None or scope.failure is not None

    async def _unit(self, key: tuple[Any, ...]) -> _Effect | None:
        if key[0] == "step":
            self._started[key[1]] = workflow.now().isoformat()
            return await self._step(key[1])
        if key[0] == "batch":
            return await self._batch(self._batches.pop((key[1], key[2])))
        return await self._collect(key[1])

    def _apply(self, key: tuple[Any, ...], effect: _Effect) -> None:
        if key[0] == "collect":
            c: Collect = key[1]
            if effect.failure is not None:
                self.sched.collect_failed(c.loop, c.index, effect.failure)
            else:
                self.sched.collected(c.loop, c.index, effect.collected)
            return
        if key[0] == "batch":
            loop, start = key[1], key[2]
            if effect.end is not None:
                self.sched.end(effect.end)
            elif effect.batch is not None:
                self.sched.batch_done(loop, start, effect.batch)
            elif effect.failure is not None:
                self.sched.batch_failed(loop, start, effect.failure)
            return
        inst: Instance = key[1]
        if effect.cel_mode is not None:
            self._cel_modes[inst] = effect.cel_mode
        if effect.loop is not None:
            self.sched.open_loop(
                inst,
                effect.loop.items,
                concurrency=effect.loop.concurrency,
                stop_on_error=effect.loop.stop_on_error,
                batch=effect.loop.batch,
            )
        elif effect.end is not None:
            self.sched.finish(inst, effect.end, effect.output)
        elif effect.failure is not None:
            self.sched.fail(inst, effect.failure)
        else:
            if effect.variables:
                self.vars.update(effect.variables)
            self.sched.succeed(inst, effect.output, effect.ports)

    # --- the budget ------------------------------------------------------------------------------------------------

    def _serve_budget(self) -> None:
        """Take in the children's requests and our parent's answer, then serve what the budget can: grants go to
        children, a filter resumes, a loop opens its next iteration (the scheduler's own), and a shortfall goes to our
        parent."""
        self._dirty = False
        for need in self._mail:
            self.sched.budget.request(need)
        self._mail = []
        for key, granted in self._answers:
            if key == self._ask:
                self._ask = None
                self.sched.budget.answered(granted)
        self._answers = []
        answers, ask = self.sched.answer_budget()
        for a in answers:
            if a.need.requester == LOCAL:
                waiter = self._filters.pop(a.need.key, None)
                if waiter is not None and not waiter.done():
                    waiter.set_result(a.granted)
                else:  # the filter was cancelled meanwhile: give back what it was granted
                    self.sched.budget.used -= a.granted
            else:
                self._signal(a.need.requester, BUDGET, [a.need.key, a.granted])
        if ask is not None and self.parent is not None:
            self._asks += 1
            self._ask = str(self._asks)  # only our parent answers us: a counter names the request
            self._signal(
                self.parent.workflow_id,
                REQUEST_BUDGET,
                [workflow.info().workflow_id, self._ask, ask.need, ask.want, ask.held],
            )

    def _signal(self, workflow_id: str, name: str, args: list[Any]) -> None:
        async def send() -> None:
            try:
                await workflow.get_external_workflow_handle(workflow_id).signal(name, args=args)
            except Exception:  # the child ended meanwhile: nothing reads the answer
                workflow.logger.warning("budget_signal_undelivered", extra={"to": workflow_id, "signal": name})

        self._signals.append(asyncio.create_task(send()))

    async def _take_budget(self, key: str, n: int) -> bool:
        """A filter's items, now or once the budget has them: False at the cap."""
        if self.sched.budget.take(n):
            return True
        waiter: asyncio.Future[int] = asyncio.get_running_loop().create_future()
        self._filters[key] = waiter
        self.sched.budget.request(Need(LOCAL, key, n, n))
        self._dirty = True
        return bool(await waiter)

    # --- the projection -------------------------------------------------------------------------------------------

    def _queue(self, row: StepRow) -> None:
        """Queue a row for the next projection, as storage will write it: `_take_rows` sizes the rows it sends, and a
        character strict UTF-8 can't encode would fail that in workflow code, on every retry. A later row of the same
        attempt replaces it."""
        row = replace(
            row,
            input_preview=storable(row.input_preview),
            output_preview=storable(row.output_preview),
            error_code=sanitize(row.error_code),
            error_message=sanitize(row.error_message),
        )
        self._rows[(row.step_id, row.iteration_key, row.attempt)] = row

    def _take_rows(self) -> list[StepRow]:
        """The next projection's rows, oldest first, within PROJECT_BYTES; one row at least. A backlog (after a
        database outage, say) takes several projections, each well within Temporal's payload limit."""
        taken: list[StepRow] = []
        size = 0
        for key in list(self._rows):
            row_size = len(canonical_json(asdict(self._rows[key])))
            if taken and size + row_size > PROJECT_BYTES:
                break
            taken.append(self._rows.pop(key))
            size += row_size
        return taken

    def _learn(self, value: Any, schema: Mapping[str, Any] | None) -> None:
        self._secrets = remember(self._secrets, sensitive_values(value, schema))

    def _preview(self, value: Any, schema: Mapping[str, Any] | None = None) -> Any:
        return preview(value, schema, self._secrets)

    def _queue_settled(self) -> None:
        """Control steps that settled since the last call. Plugin steps queue their own attempts (`_activity`)."""
        now = workflow.now().isoformat()
        for inst, result in self.sched.take_settled():
            step = self.sched.step(inst)
            if not step.control:
                continue
            error = result.get("error")
            self._queue(
                StepRow(
                    run_id=self.run_id,
                    step_id=str(step.id),
                    node_key=step.key,
                    iteration_key=iteration_key(inst.scope),
                    attempt=1,
                    status="failed" if error else "succeeded",
                    started_at=self._started.get(inst),
                    ended_at=now,
                    output_preview=self._preview(result.get("output")),
                    error_code=error["code"] if error else None,
                    error_message=mask(error["message"], self._secrets) if error else None,
                    cel_mode=self._cel_modes.get(inst),
                )
            )

    async def _project(
        self, rows: list[StepRow], summary: RunSummary | None = None, start: RunStart | None = None
    ) -> None:
        await workflow.execute_activity(
            PROJECT,
            ProjectInput(self.tenant_id, rows, summary, start),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=30)),
        )

    async def _shielded(
        self, rows: list[StepRow], summary: RunSummary | None = None, start: RunStart | None = None
    ) -> bool:
        """A write a cancel must not stop: shielded, it's never cancelled, and it lands. True when a cancel arrived
        meanwhile: the caller decides what it means (an end already written stands; a sub-run's first row doesn't)."""
        return await _landed(asyncio.create_task(self._project(rows, summary, start)))

    async def _project_end(self, summary: RunSummary | None) -> bool:
        """The execution's last projections: the rows still queued, in batches, the last one with the run's end, if
        it's given (a batch has none). A cancel that arrives meanwhile comes too late to unmake the end they record:
        each write is shielded, so it's never cancelled, and it lands; the run's result stands, so the projection and
        Temporal agree. True when a cancel arrived meanwhile."""
        self._queue_settled()
        cancelled = False
        while True:
            rows = self._take_rows()
            last = not self._rows
            if rows or (last and summary is not None):
                cancelled = await self._shielded(rows, summary if last else None) or cancelled
            if last:
                break
        return await self._send_signals() or cancelled

    async def _send_signals(self) -> bool:
        """Every budget signal still in flight, sent before the execution ends: a late cancel can't stop them. True
        when a cancel arrived meanwhile."""
        pending, self._signals = self._signals, []
        return await _landed(asyncio.gather(*pending, return_exceptions=True))

    @staticmethod
    def _stored(error: dict[str, Any] | None) -> dict[str, Any] | None:
        """A run's error as storage writes it: the summary and the run's result say the same."""
        if error is None:
            return None
        return {**error, "code": sanitize(error["code"]), "message": sanitize(error["message"])}

    # --- values ----------------------------------------------------------------------------------------------------

    def _view(self, scope: ScopeKey, item: tuple[Any, int] | None = None) -> Any:
        run = {
            "id": self.run_id,
            "started_at": self.run_started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "now": workflow.now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        return resolve.view(self.sched, scope, trigger=self.trigger, variables=dict(self.vars), run=run, item=item)

    async def _values(
        self, owner: Step | None, pairs: list[tuple[str, Any]], scope: ScopeKey
    ) -> tuple[dict[str, Any], str | None]:
        """Every envelope's value, by JSON pointer, and the CEL mode used (activity wins over local)."""
        values: dict[str, Any] = {}
        mode: str | None = None
        v = self._view(scope)
        for pointer, value in pairs:
            if isinstance(value, RefValue):
                values[pointer] = resolve.ref(v, value)
            elif isinstance(value, TemplateValue):
                values[pointer] = resolve.template(v, value)
            elif isinstance(value, CelValue):
                record = self.program.record(owner.id if owner is not None else None, pointer)
                task = resolve.cel_task(
                    record, [v], local_profile=LOCAL_CEL_PROFILE, version_profile=self.program.cel_profile
                )
                [outcome] = await self._evaluate(task)
                values[pointer] = resolve.outcome_value(outcome)
                mode = "activity" if mode == "activity" or not task.local else "local"
            else:
                values[pointer] = value.value
        return values, mode

    async def _evaluate(self, task: resolve.CelTask) -> list[cel.Outcome]:
        if task.local:
            if self._yield.must_yield(task.record):
                await asyncio.sleep(0.001)  # a durable timer: the workflow task ends here (spec §5.6)
                self._yield.reset()
            outcomes = task.run_local()
            for _ in outcomes:
                self._yield.charge(task.record)
            return outcomes
        out: list[cel.Outcome] = []
        profile = self.program.cel_profile
        for i in range(0, len(task.bindings), CEL_BATCH):
            chunk = resolve.CelTask(task.record, task.bindings[i : i + CEL_BATCH], False)
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
        return out

    # --- steps -----------------------------------------------------------------------------------------------------

    async def _step(self, inst: Instance) -> _Effect:
        step = self.sched.step(inst)
        skip = ("/collect",) if step.ref == "flow.loop@1" else ("/predicate",) if step.ref == "flow.filter@1" else ()
        pairs = [(p, v) for p, v in step.values if not any(p == s or p.startswith(s + "/") for s in skip)]
        try:
            values, cel_mode = await self._values(step, pairs, inst.scope)
        except resolve.ValueFailure as e:
            if not step.control:  # it never reached an attempt: its one row says why
                self._queue_unstarted(inst, step, e.failure)
            return _Effect(failure=e.failure)
        config = resolve.assemble(step.config, values)
        if not step.control:
            return await self._activity(inst, step, config, cel_mode)
        decision = nodes.decide(step.ref, config)
        if decision.failure is not None:
            return _Effect(failure=decision.failure, cel_mode=cel_mode)
        if decision.loop is not None:
            return _Effect(loop=decision.loop, cel_mode=cel_mode)
        if decision.filter_items is not None:
            return await self._filter(inst, step, decision.filter_items)
        if decision.subflow is not None:
            return await self._subflow(inst, step, decision.subflow, cel_mode)
        if decision.wait_s is not None:
            await asyncio.sleep(decision.wait_s)
        if decision.wait_until is not None:
            await asyncio.sleep(max(0.0, (decision.wait_until - workflow.now()).total_seconds()))
        return _Effect(
            output=decision.output,
            ports=decision.ports,
            variables=decision.variables,
            end=decision.end,
            cel_mode=cel_mode,
        )

    async def _filter(self, inst: Instance, step: Step, items: list[Any]) -> _Effect:
        if not await self._take_budget(f"filter:{iteration_key(inst.scope)}:{step.key}", len(items)):
            return _Effect(failure=Failure(ITERATION_CAP_EXCEEDED, CAP_MESSAGE))
        record = self.program.record(step.id, "/predicate")
        views = [self._view(inst.scope, item=(item, i)) for i, item in enumerate(items)]
        try:
            task = resolve.cel_task(
                record, views, local_profile=LOCAL_CEL_PROFILE, version_profile=self.program.cel_profile
            )
        except resolve.ValueFailure as e:
            return _Effect(failure=e.failure)
        kept: list[Any] = []
        for item, outcome in zip(items, await self._evaluate(task), strict=True):
            if not outcome.ok:
                return _Effect(failure=Failure(str(outcome.error), outcome.message))
            if not isinstance(outcome.value, bool):
                return _Effect(failure=Failure(cel.TYPE_MISMATCH, "`predicate` must give true or false."))
            if outcome.value:
                kept.append(item)
        return _Effect(output={"items": kept, "count": len(kept)}, cel_mode="local" if task.local else "activity")

    async def _collect(self, c: Collect) -> _Effect:
        step = self.sched.step(c.loop)
        collect = step.config.get("collect")
        pairs = [(p, v) for p, v in step.values if p == "/collect" or p.startswith("/collect/")]
        try:
            values, _ = await self._values(step, pairs, c.scope)
        except resolve.ValueFailure as e:
            return _Effect(failure=e.failure)
        if collect is None:
            return _Effect(collected=None)
        return _Effect(collected=resolve.assemble({"collect": collect}, values)["collect"])

    # --- children -------------------------------------------------------------------------------------------------

    async def _subflow(self, inst: Instance, step: Step, start: nodes.SubflowStart, cel_mode: str | None) -> _Effect:
        """A `run_workflow` step: its pinned version runs as a child `RunGraph`, a run of its own that shares the
        deadline and draws on this execution's budget. Its outputs are the step's output; its failure, the step's."""
        version = self.program.subflows.get(str(step.id))
        if version is None or self.depth >= MAX_DEPTH:
            reason = "no pinned version" if version is None else f"more than {MAX_DEPTH} sub-flows deep"
            return _Effect(failure=Failure(VERSION_UNUSABLE, f"`{step.key}` can't run its sub-flow: {reason}."))
        child = str(workflow.uuid4())
        grant = self.sched.budget.start_child(child, SUBFLOW_GRANT)
        parent = Parent(
            workflow_id=workflow.info().workflow_id,
            run_id=self.run_id,
            step_id=str(step.id),
            iteration_key=iteration_key(inst.scope),
            kind=SUBFLOW,
            deadline=self.deadline.isoformat(),
            grant=grant,
            depth=self.depth + 1,
            secrets=list(self._secrets),
        )
        run = RunInput(
            self.tenant_id,
            child,
            version,
            start.input,
            self.mode,
            self.max_run_duration_s,
            self.cel_schedule_to_start_s,
            parent=parent,
            workflow_id=start.workflow_id,
        )
        used: int | None = None
        try:
            result = await workflow.execute_child_workflow(
                "RunGraph", run, result_type=RunResult, **child_options(child)
            )
            used = result.iterations
        except ChildWorkflowError as e:  # it failed as a workflow, which a run never does: a bug, or terminated
            message = f"The sub-flow ended without a result ({type(e.cause).__name__})."
            return _Effect(failure=Failure(INTERNAL_ERROR, message), cel_mode=cel_mode)
        finally:
            self.sched.budget.settle_child(child, used)
            self._dirty = True
        self._secrets = remember(self._secrets, tuple(result.secrets))
        if result.status == "succeeded":
            return _Effect(output=dict(result.outputs or {}), cel_mode=cel_mode)
        error = result.error or {"code": result.status, "message": f"The sub-flow ended {result.status}."}
        return _Effect(failure=Failure(str(error["code"]), str(error["message"])), cel_mode=cel_mode)

    def _outer(self, loop: Instance) -> list[dict[str, Any]]:
        """The loop's enclosing scopes as its batch reads them, outermost first: the results its body can
        reference, and each enclosing loop's item."""
        reads = self.program.outer_reads(loop.step)
        out = []
        for depth in range(len(loop.scope) + 1):
            scope = self.sched.scopes[loop.scope[:depth]]
            results = {k: v for k, v in scope.results.items() if reads is None or k in reads}
            out.append(
                {"key": [[k, i] for k, i in scope.key], "results": results, "item": scope.item, "index": scope.index}
            )
        return out

    async def _batch(self, b: Batch) -> _Effect:
        """A batch of a loop's items, as a child `LoopBatch`. It writes its iterations' rows into this run, and
        returns what they collected."""
        step = self.sched.step(b.loop)
        loop = self.sched.loops[b.loop]
        # from the input, not the workflow id: a replay of this history sees the same id (the run id names the logical
        # run, the loop step and its scope name the loop, the start names the batch)
        child = f"{self.run_id}/{step.id}/{iteration_key(b.loop.scope)}/batch:{b.start}"
        grant = self.sched.budget.start_child(child, len(b.items))
        parent = Parent(
            workflow_id=workflow.info().workflow_id,
            run_id=self.run_id,
            step_id=str(step.id),
            iteration_key=iteration_key(b.loop.scope),
            kind=BATCH,
            deadline=self.deadline.isoformat(),
            grant=grant,
            depth=self.depth,
            secrets=list(self._secrets),
        )
        batch = BatchInput(
            tenant_id=self.tenant_id,
            run_id=self.run_id,
            version_id=self.version_id,
            loop_step=str(step.id),
            outer=self._outer(b.loop),
            items=b.items,
            offset=b.start,
            concurrency=loop.concurrency,
            stop_on_error=loop.stop_on_error,
            trigger=self.trigger,
            variables=dict(self.vars),
            run_started_at=self.run_started_at.isoformat(),
            parent=parent,
            mode=self.mode,
            cel_schedule_to_start_s=self.cel_schedule_to_start_s,
        )
        used: int | None = None
        try:
            result = await workflow.execute_child_workflow(
                "LoopBatch", batch, result_type=BatchResult, **child_options(child)
            )
            used = result.iterations
        except ChildWorkflowError as e:  # its version didn't load or compile, a bug, or it was terminated
            cause = e.cause
            if isinstance(cause, ApplicationError) and cause.type in (VERSION_UNUSABLE, INTERNAL_ERROR):
                return _Effect(failure=Failure(cause.type, cause.message))
            return _Effect(failure=Failure(INTERNAL_ERROR, "The batch ended without a result."))
        finally:
            self.sched.budget.settle_child(child, used)
            self._dirty = True
        self._secrets = remember(self._secrets, tuple(result.secrets))
        if result.end is not None:
            end = RunEnd.from_json(result.end)
            if end.status == "cancelled":
                return _Effect(failure=CANCELLED)
            return _Effect(end=end)
        stopped = Failure.from_json(result.stopped) if result.stopped else None
        return _Effect(batch=BatchOutcome(list(result.collected), list(result.failures), stopped))

    # --- plugin steps ---------------------------------------------------------------------------------------------

    async def _activity(self, inst: Instance, step: Step, config: Any, cel_mode: str | None) -> _Effect:
        """A plugin step, one activity execution per attempt (`maximum_attempts=1`). The workflow decides each retry,
        so a timeout after an ambiguous send is never repeated, and projects each attempt's rows, so no row write can
        repeat an effect (decisions 7, 12)."""
        manifest = self.program.manifests[step.ref]
        retry = manifest["retry"]
        attempts = step.max_attempts or int(retry["max_attempts"])
        timeout = timedelta(seconds=step.timeout_s or float(manifest["timeout_s"]))
        ambiguous = manifest["side_effect"] == AMBIGUOUS
        self._learn(config, manifest["config_schema"])  # a resolved sensitive value, before anything can echo it
        attempt = 1
        while True:
            row = StepRow(
                run_id=self.run_id,
                step_id=str(step.id),
                node_key=step.key,
                iteration_key=iteration_key(inst.scope),
                attempt=attempt,
                status="running",
                started_at=workflow.now().isoformat(),
                input_preview=self._preview(config, manifest["config_schema"]),
                cel_mode=cel_mode,
            )
            self._queue(row)
            try:
                result = await workflow.execute_activity(
                    step_activity(step.ref),
                    StepInput(
                        tenant_id=self.tenant_id,
                        run_id=self.run_id,
                        step_id=str(step.id),
                        node_key=step.key,
                        iteration_key=iteration_key(inst.scope),
                        ref=step.ref,
                        config=config,
                        mode=self.mode,
                        attempt=attempt,
                    ),
                    result_type=StepResult,
                    start_to_close_timeout=timeout,
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except (asyncio.CancelledError, ActivityError) as e:
                if isinstance(e, ActivityError) and not isinstance(e.cause, ActivityCancelled):
                    failure, outcome, retryable = self._failed_attempt(e, row, step.key, ambiguous, retry)
                    if not retryable or attempt >= attempts:
                        return _Effect(failure=failure, cel_mode=cel_mode)
                    await asyncio.sleep(_backoff(retry, attempt))  # a durable timer
                    attempt += 1
                    continue
                # The run or the scope ended: the SDK reports our own cancel as an ActivityError. Never retry it.
                self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat()))
                raise asyncio.CancelledError from None
            self._learn(result.output, manifest["output_schema"])
            self._queue(
                replace(
                    row,
                    status="succeeded",
                    ended_at=workflow.now().isoformat(),
                    output_preview=self._preview(result.output, manifest["output_schema"]),
                    outcome=result.outcome,
                )
            )
            return _Effect(output=result.output, cel_mode=cel_mode)

    def _queue_unstarted(self, inst: Instance, step: Step, failure: Failure) -> None:
        now = workflow.now().isoformat()
        self._queue(
            StepRow(
                run_id=self.run_id,
                step_id=str(step.id),
                node_key=step.key,
                iteration_key=iteration_key(inst.scope),
                attempt=1,
                status="failed",
                started_at=self._started.get(inst, now),
                ended_at=now,
                error_code=failure.code,
                error_message=mask(failure.message, self._secrets),
            )
        )

    def _failed_attempt(
        self, e: ActivityError, row: StepRow, key: str, ambiguous: bool, retry: Mapping[str, Any]
    ) -> tuple[Failure, str | None, bool]:
        failure, outcome, retryable = _attempt_failed(
            e, key, row.attempt, ambiguous=ambiguous, non_retryable=retry["non_retryable"]
        )
        self._queue(
            replace(
                row,
                status="failed",
                ended_at=workflow.now().isoformat(),
                error_code=failure.code,
                error_message=mask(failure.message, self._secrets),
                outcome=outcome,
            )
        )
        return failure, outcome, retryable


__all__ = [
    "CEL_BATCH",
    "DEADLINE_EXCEEDED",
    "INTERNAL_ERROR",
    "IN_FLIGHT_CAP",
    "MAX_DEPTH",
    "NODE_TYPE_UNAVAILABLE",
    "PROJECT_BYTES",
    "SUBFLOW_GRANT",
    "VERSION_UNUSABLE",
    "Execution",
    "child_options",
]
```

- [ ] **Step 5: The two workflow types**

Replace `backend/src/dewpoint/engine/runtime/workflow.py` with:

```python
# SPDX-License-Identifier: Apache-2.0
"""The two workflow types on `dewpoint-engine` (spec §6, §7):
- `RunGraph` runs a pinned version: a run the dispatcher started, a sub-flow (`run_workflow`) and a failure handler.
  A sub-flow and a failure handler are runs of their own: each writes its row first, points at its parent run, and
  draws its iterations from its parent.
- `LoopBatch` runs a slice of a loop over more than 100 items, as a child of the execution that holds the loop.

Both drive the shared `Execution` loop."""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.exceptions import ApplicationError, ChildWorkflowError

with workflow.unsafe.imports_passed_through():
    from dewpoint.engine.graph.values import iter_values, pointer_str
    from dewpoint.engine.runtime import resolve
    from dewpoint.engine.runtime.activities import (
        FAILURE_HANDLER,
        LOAD_VERSION,
        BatchInput,
        BatchResult,
        LoadVersionInput,
        Parent,
        RunInput,
        RunResult,
        RunStart,
        RunSummary,
        VersionData,
    )
    from dewpoint.engine.runtime.budget import Budget
    from dewpoint.engine.runtime.execution import (
        CANCELLED,
        CEL_BATCH,
        DEADLINE_EXCEEDED,
        IN_FLIGHT_CAP,
        INTERNAL_ERROR,
        NODE_TYPE_UNAVAILABLE,
        PROJECT_BYTES,
        SUBFLOW_GRANT,
        VERSION_UNUSABLE,
        Execution,
        _cancelled,
        child_options,
    )
    from dewpoint.engine.runtime.program import Program, compile_program
    from dewpoint.engine.runtime.projection import mask
    from dewpoint.engine.runtime.scheduler import (
        ITERATION_CAP,
        Failure,
        OuterScope,
        RunEnd,
        Scheduler,
    )


HANDLED = ("failed", DEADLINE_EXCEEDED)  # the ends that run a failure handler (a cancel is no failure)


@workflow.defn(name="RunGraph")
class RunGraph(Execution):
    @workflow.run
    async def run(self, start: RunInput) -> RunResult:
        """Every way a run ends is projected. Python exceptions in workflow code would fail the workflow task, which
        Temporal retries forever: the run would hang, `running` in the projection. So a version this build can't
        load or compile fails the run (`version_unusable`) before any step runs, and any other exception fails it
        (`internal_error`). The workflow's outputs are evaluated under the same deadline and handlers as its steps:
        a cancel or the deadline while they're computed ends the run as it would anywhere else.

        A child run (a sub-flow, a failure handler) writes its own row before anything else, even its version's
        load, so every way it ends has a row to record it. It shares its parent's deadline (a failure handler has
        its own), and, cancelled, returns its result instead of ending cancelled, so its parent learns how many
        iterations it used.

        A run that ends `failed` or `deadline_exceeded` then runs its failure handler once. Its end is decided
        first, and stands: a cancel meanwhile cancels the handler, which reports back. But its row stays
        non-terminal until the handler has ended, so something non-terminal always holds the handler's closure,
        and with it the CEL profiles it pins (spec §4.5). The end is recorded once, counting the handler's
        iterations."""
        started = workflow.info().start_time
        if start.parent is not None and start.parent.kind != FAILURE_HANDLER:
            deadline = datetime.fromisoformat(start.parent.deadline)
        else:
            deadline = started + timedelta(seconds=start.max_run_duration_s)
        self._context(
            tenant_id=start.tenant_id,
            run_id=start.run_id,
            version_id=start.version_id,
            mode=start.mode,
            trigger=start.trigger,
            cel_schedule_to_start_s=start.cel_schedule_to_start_s,
            max_run_duration_s=start.max_run_duration_s,
            parent=start.parent,
            run_started_at=started,
            deadline=deadline,
        )
        self.input = start
        if start.parent is not None:  # its row first: whatever ends it now has a row to end
            if await self._shielded([], None, self._start_row(start.parent, start.workflow_id, started)):
                return await self._cancelled_early()  # cancelled while the row was written
        try:
            data = await workflow.execute_local_activity(
                LOAD_VERSION,
                LoadVersionInput(start.tenant_id, start.version_id),
                result_type=VersionData,
                start_to_close_timeout=timedelta(seconds=30),
            )
        except asyncio.CancelledError:
            return await self._cancelled_early()
        except Exception as e:  # its text may quote the version: the log has it, the projection names the type
            if _cancelled(e):
                return await self._cancelled_early()
            workflow.logger.error("run_version_unusable", exc_info=True)
            message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
            return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)))
        try:
            program = compile_program(
                data.graph,
                data.manifests,
                data.expressions,
                data.cel_profile,
                data.subflow_version_ids,
                data.failure_handler_version_id,
            )
        except Exception as e:
            workflow.logger.error("run_version_unusable", exc_info=True)
            message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
            return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)))
        outputs: dict[str, Any] | None = None
        try:
            self._fresh(program)
            await self._drive()
            end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
            if end.status == "succeeded":
                end, outputs = await self._outputs_by(end)
        except asyncio.CancelledError:
            self.sched.end(RunEnd("cancelled", CANCELLED))
            result = await self._finish(RunEnd("cancelled", CANCELLED))
            if start.parent is None:
                raise
            return result  # a child reports back instead: its parent learns what it used
        except Exception as e:  # a bug: the text may quote run data, so it goes to the log, not the projection
            workflow.logger.error("run_internal_error", exc_info=True)
            message = f"The interpreter failed ({type(e).__name__}); the worker's log has the details."
            end, outputs = RunEnd("failed", Failure(INTERNAL_ERROR, message)), None
        ended = workflow.now()  # the end is decided: whatever follows, it stands
        pin = self._handler_pin(data) if end.status in HANDLED else None
        if pin is not None and not await self._project_end(None):  # its rows land; its end waits for the handler
            await self._failure_handler(pin, data, self._end_error(end))  # (a cancel meanwhile: no handler)
        return await self._finish(end, outputs, ended)

    def _fresh(self, program: Program) -> None:
        """A new run's state: its budget (the cap, or what its parent granted), the sensitive values it can see
        already, and its variables."""
        self.program = program
        parent = self.parent
        budget = Budget(ITERATION_CAP, root=True) if parent is None else Budget(parent.grant, root=False)
        self.sched = Scheduler(program, budget=budget)
        self._learn(self.trigger, program.graph.settings.input_schema)
        for step in program.steps.values():  # sensitive literals in plugin configs: masked from the start
            if not step.control:
                self._learn(resolve.assemble(step.config, {}), program.manifests[step.ref]["config_schema"])
        schema = program.graph.settings.vars_schema
        self.vars = {k: p.get("default") for k, p in sorted(schema.get("properties", {}).items())}
        self.sched.start()

    def _start_row(self, parent: Parent, workflow_id: str, started: datetime) -> RunStart:
        return RunStart(
            run_id=self.run_id,
            workflow_id=workflow_id,
            version_id=self.version_id,
            mode=self.mode,
            parent_run_id=parent.run_id,
            parent_step_id=parent.step_id or None,
            parent_iteration_key=parent.iteration_key,
            kind=parent.kind,
            started_at=started.isoformat(),
        )

    async def _outputs_by(self, end: RunEnd) -> tuple[RunEnd, dict[str, Any] | None]:
        """The workflow's outputs, within the run's deadline. Past it, their evaluation is cancelled and the run ends
        `deadline_exceeded`; an output that can't be computed fails the run with its code."""
        task = asyncio.create_task(self._outputs())
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (self.deadline - workflow.now()).total_seconds())))
        try:
            done, _ = await workflow.wait([task, clock], return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:  # the run was cancelled: so is what it was computing
            task.cancel()
            clock.cancel()
            raise
        clock.cancel()
        if task not in done:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return RunEnd(DEADLINE_EXCEEDED, Failure(DEADLINE_EXCEEDED, "The run passed its deadline.")), None
        try:
            return end, task.result()
        except resolve.ValueFailure as e:
            return RunEnd("failed", e.failure), None

    async def _outputs(self) -> dict[str, Any]:
        settings_outputs = self.program.graph.settings.outputs
        pairs = [(pointer_str(p), v) for p, v in iter_values(settings_outputs, ("settings", "outputs"))]
        values, _ = await self._values(None, pairs, ())
        assembled = resolve.assemble({"settings": {"outputs": settings_outputs}}, values)
        return dict(assembled["settings"]["outputs"])

    async def _finish(
        self, end: RunEnd, outputs: dict[str, Any] | None = None, ended: datetime | None = None
    ) -> RunResult:
        error = self._end_error(end)
        summary = RunSummary(
            run_id=self.run_id,
            status=end.status,
            ended_at=(ended or workflow.now()).isoformat(),
            error_code=error["code"] if error else None,
            error_message=error["message"] if error else None,
            iterations=self.sched.iterations,
        )
        await self._project_end(summary)
        return RunResult(
            status=end.status,
            outputs=outputs,
            error=error,
            iterations=self.sched.iterations,
            secrets=list(self._secrets),
        )

    def _end_error(self, end: RunEnd) -> dict[str, Any] | None:
        """The run's error as it's stored: its summary, its result and its failure handler's trigger all say this."""
        error = end.failure.to_json() if end.failure is not None and end.status != "succeeded" else None
        if error is not None:
            error["message"] = mask(error["message"], self._secrets)
        return self._stored(error)

    async def _end_early(self, end: RunEnd) -> RunResult:
        """The run ends before it has a program: nothing ran, so only the run is projected."""
        error = self._stored(end.failure.to_json() if end.failure is not None else None)
        summary = RunSummary(
            run_id=self.run_id,
            status=end.status,
            ended_at=workflow.now().isoformat(),
            error_code=error["code"] if error else None,
            error_message=error["message"] if error else None,
        )
        await self._shielded([], summary)
        return RunResult(status=end.status, error=error)

    async def _cancelled_early(self) -> RunResult:
        result = await self._end_early(RunEnd("cancelled", CANCELLED))
        if self.parent is None:
            raise asyncio.CancelledError
        return result

    def _handler_pin(self, data: VersionData) -> tuple[str, str] | None:
        """The failure handler this run's version pins, as (version id, workflow id); none for a failure handler's
        own run, whose failure runs no handler."""
        version, workflow_id = data.failure_handler_version_id, self.program.graph.settings.failure_handler
        if version is None or workflow_id is None or (self.parent is not None and self.parent.kind == FAILURE_HANDLER):
            return None
        return version, str(workflow_id)

    async def _failure_handler(self, pin: tuple[str, str], data: VersionData, error: dict[str, Any] | None) -> None:
        """The run's failure handler (spec §6): its pinned version runs once, as a child run, with the error summary as
        its trigger, and draws on this run's budget. Its end doesn't change this run's.

        This run's end is already decided: a cancel meanwhile comes too late to change it. It cancels the handler,
        which reports back first, so its iterations still count."""
        version, workflow_id = pin
        child = str(workflow.uuid4())
        grant = self.sched.budget.start_child(child, SUBFLOW_GRANT)
        parent = Parent(
            workflow_id=workflow.info().workflow_id,
            run_id=self.run_id,
            step_id="",
            iteration_key="",
            kind=FAILURE_HANDLER,
            deadline=(workflow.now() + timedelta(seconds=self.max_run_duration_s)).isoformat(),
            grant=grant,
            depth=self.depth + 1,
            secrets=list(self._secrets),
        )
        trigger = {
            "run_id": self.run_id,
            "workflow_id": data.workflow_id,
            "version_id": self.version_id,
            "error": {"code": (error or {}).get("code"), "message": (error or {}).get("message")},
        }
        run = RunInput(
            self.tenant_id,
            child,
            version,
            trigger,
            self.mode,
            self.max_run_duration_s,
            self.cel_schedule_to_start_s,
            parent=parent,
            workflow_id=workflow_id,
        )
        handler = asyncio.create_task(self._handler(run, child))
        while not handler.done():  # it draws its iterations from this run: answer as it asks
            wake = asyncio.create_task(workflow.wait_condition(lambda: bool(self._mail or self._answers)))
            try:
                await workflow.wait([handler, wake], return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:  # this run's end stands: the handler is cancelled, and reports back
                handler.cancel()
            finally:
                wake.cancel()
            self._serve_budget()
        self.sched.budget.settle_child(child, None if handler.cancelled() else handler.result())
        await self._send_signals()

    async def _handler(self, run: RunInput, child: str) -> int | None:
        """The failure handler's run: the iterations it used, or None when it ended without saying."""
        try:
            result: RunResult = await workflow.execute_child_workflow(
                "RunGraph", run, result_type=RunResult, **child_options(child)
            )
        except ChildWorkflowError:
            workflow.logger.warning("failure_handler_failed", exc_info=True)
            return None
        return result.iterations


@workflow.defn(name="LoopBatch")
class LoopBatch(Execution):
    @workflow.run
    async def run(self, start: BatchInput) -> BatchResult:
        """A slice of a loop, run as a child of the execution that holds the loop (spec §6). Its iterations run as
        they would inline, with the loop's concurrency and error policy, over read-only copies of the scopes around
        the loop; their rows go into the parent's run. It returns what they collected, the failures, and how many
        iterations it used. A fail or stop node, or the deadline, ends the run: the batch reports it as `end`."""
        self._context(
            tenant_id=start.tenant_id,
            run_id=start.run_id,
            version_id=start.version_id,
            mode=start.mode,
            trigger=start.trigger,
            cel_schedule_to_start_s=start.cel_schedule_to_start_s,
            max_run_duration_s=0,
            parent=start.parent,
            run_started_at=datetime.fromisoformat(start.run_started_at),
            deadline=datetime.fromisoformat(start.parent.deadline),
        )
        try:
            data = await workflow.execute_local_activity(
                LOAD_VERSION,
                LoadVersionInput(start.tenant_id, start.version_id),
                result_type=VersionData,
                start_to_close_timeout=timedelta(seconds=30),
            )
            program = compile_program(
                data.graph,
                data.manifests,
                data.expressions,
                data.cel_profile,
                data.subflow_version_ids,
                data.failure_handler_version_id,
            )
        except asyncio.CancelledError:
            return BatchResult([], [], end=RunEnd("cancelled", CANCELLED).to_json())
        except Exception as e:
            if _cancelled(e):
                return BatchResult([], [], end=RunEnd("cancelled", CANCELLED).to_json())
            workflow.logger.error("batch_version_unusable", exc_info=True)
            message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
            raise ApplicationError(message, type=VERSION_UNUSABLE, non_retryable=True) from None
        try:
            self.program = program
            self.sched = Scheduler(program, budget=Budget(start.parent.grant, root=False))
            self.vars = dict(start.variables)
            outer = [
                OuterScope(tuple((str(k), int(i)) for k, i in o["key"]), o["results"], o["item"], o["index"])
                for o in start.outer
            ]
            self.sched.start_batch(
                uuid.UUID(start.loop_step),
                outer,
                start.items,
                offset=start.offset,
                concurrency=start.concurrency,
                stop_on_error=start.stop_on_error,
            )
            await self._drive()
        except asyncio.CancelledError:
            self.sched.end(RunEnd("cancelled", CANCELLED))
            await self._project_end(None)
            return self._result(RunEnd("cancelled", CANCELLED))
        except Exception as e:
            workflow.logger.error("batch_internal_error", exc_info=True)
            message = f"The batch failed ({type(e).__name__}); the worker's log has the details."
            raise ApplicationError(message, type=INTERNAL_ERROR, non_retryable=True) from None
        await self._project_end(None)
        return self._result(self.sched.ended)

    def _result(self, end: RunEnd | None) -> BatchResult:
        outcome = self.sched.outcome
        if outcome is None:  # the run ended inside the batch
            end = end or RunEnd("failed", Failure("error", "The batch ended without a result."))
            return BatchResult([], [], end=end.to_json(), iterations=self.sched.iterations, secrets=list(self._secrets))
        return BatchResult(
            collected=outcome.collected,
            failures=outcome.failures,
            stopped=outcome.stopped.to_json() if outcome.stopped else None,
            iterations=self.sched.iterations,
            secrets=list(self._secrets),
        )


__all__ = [
    "CEL_BATCH",
    "DEADLINE_EXCEEDED",
    "INTERNAL_ERROR",
    "IN_FLIGHT_CAP",
    "NODE_TYPE_UNAVAILABLE",
    "PROJECT_BYTES",
    "VERSION_UNUSABLE",
    "LoopBatch",
    "RunGraph",
]
```

In `backend/src/dewpoint/apps/worker/main.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/main.py b/backend/src/dewpoint/apps/worker/main.py
--- a/backend/src/dewpoint/apps/worker/main.py
+++ b/backend/src/dewpoint/apps/worker/main.py
@@ -18,7 +18,7 @@
 from dewpoint.core.config import Settings
 from dewpoint.core.db import make_engine, make_sessionmaker
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
-from dewpoint.engine.runtime.workflow import RunGraph
+from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
 from dewpoint.sdk import Plugin

 log = structlog.get_logger("dewpoint.worker")
@@ -40,7 +40,7 @@
     return Worker(
         client,
         task_queue=ENGINE_QUEUE,
-        workflows=[RunGraph],
+        workflows=[RunGraph, LoopBatch],
         activities=engine_activities(store, plugins),
         graceful_shutdown_timeout=timedelta(seconds=settings.worker_shutdown_grace_s),
     )
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_main.py tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_children.py tests/apps/worker/test_run_graph_policies.py tests/engine/runtime/test_nodes.py`
Expected: 112 passed (2 + 14 + 26 + 32 + 38). Keep this path order, which is the suite's: `test_run_graph_policies.py` run before
`test_run_graph.py` hangs one of 2a-3a's timer tests.

- [ ] **Step 7: Checks and commit**

2a-3a's golden histories still replay (`tests/engine/replay`): nothing a 2a-3a graph does has changed (go/no-go 10).

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine tests/apps/worker \
  && git add src/dewpoint/engine/runtime/activities.py src/dewpoint/engine/runtime/nodes.py \
       src/dewpoint/engine/runtime/execution.py src/dewpoint/engine/runtime/workflow.py src/dewpoint/apps/worker/main.py \
       tests/engine/runtime/test_nodes.py tests/apps/worker/harness.py tests/apps/worker/test_main.py \
       tests/apps/worker/test_run_graph_policies.py tests/apps/worker/test_run_graph_children.py \
  && git commit -m "feat(engine): loop batches, sub-flows and the failure handler as children, on one budget" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Sub-runs through the database and the runs API

The worker's database store now loads a version's pins: its sub-flow versions and its failure handler. It also
writes a sub-run's own row with the sub-run's first projection (decision 9). The runs API lists top-level runs, and
shows each run's kind, its parent and its children.

The end-to-end test runs a published workflow whose step runs a published sub-flow. It goes through the real
store, the worker role, row-level security and the API. Without the pins, the sub-flow step fails
(`version_unusable`), and so does the run.

**Files:**
- Modify: `backend/src/dewpoint/apps/worker/store.py`, `backend/src/dewpoint/apps/api/routes/runs.py`
- Modify: `backend/tests/apps/worker/test_worker_db.py`

**Interfaces:**
- Consumes:
  - from Task 4, `ensure_run`, `children`, the `Run` columns, and `list_runs` (top-level runs only);
  - from Task 5, `RunStart`, `ProjectInput.start`, `VersionData.subflow_version_ids` and
    `.failure_handler_version_id`;
  - from 2a-1, `WorkflowVersion.subflow_version_ids` and `.failure_handler_version_id`.
- Produces:
  - `DbRunStore.version` returns the pins;
  - `DbRunStore.project` writes `data.start` first, when it's there, in the same transaction as the rows;
  - `GET /runs/{id}` adds `kind`, `parent_run_id` and `children` (`_child`: each child's run fields, plus
    `parent_step_id` and `parent_iteration_key`);
  - `GET /runs` adds `kind` and `parent_run_id`.

- [ ] **Step 1: Write the failing test**

In `backend/tests/apps/worker/test_worker_db.py`:

```diff
diff --git a/backend/tests/apps/worker/test_worker_db.py b/backend/tests/apps/worker/test_worker_db.py
--- a/backend/tests/apps/worker/test_worker_db.py
+++ b/backend/tests/apps/worker/test_worker_db.py
@@ -139,3 +139,54 @@
     assert run is not None
     assert (run.status, run.error_code, run.error_message) == ("failed", "workflow_failed", "bad \ufffd note")
     assert [r.node_key for r in steps] == ["f"]
+
+
+async def test_a_sub_flow_is_projected_as_a_run_of_its_own(
+    env: WorkflowEnvironment,
+    owner_sessionmaker: Any,
+    api_sessionmaker: Any,
+    admin_sessionmaker: Any,
+    dispatch_sessionmaker: Any,
+    worker_sessionmaker: Any,
+    api_settings: Any,
+    app: Any,
+) -> None:
+    """2a-3b: a sub-flow writes its own `runs` row (as the worker role, with its first projection) before any of its
+    steps, pointing at the run and step that started it. The list shows top-level runs; a run shows its children."""
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    sub = G()
+    sub.settings = {
+        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
+        "outputs": {"double": ref("steps.t.output.double")},
+    }
+    sub.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
+    sub_id = await create(api_sessionmaker, ctx, sub.data(), name="doubler")
+    assert (await publish(api_sessionmaker, ctx, sub_id, api_settings)).version is not None
+    g = G()
+    g.settings = {"input_schema": {"type": "object"}, "outputs": {"double": ref("steps.r.output.double")}}
+    g.node("r", "flow.run_workflow@1", {"workflow_id": str(sub_id), "input": {"n": 21}})
+    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, g.data()), api_settings)
+    assert out.version is not None
+    async with workers(env.client, DbRunStore(worker_sessionmaker)):
+        run_id = await start_run(
+            dispatch_sessionmaker, env.client, api_settings,
+            tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={},
+        )  # fmt: skip
+        result = await asyncio.wait_for(env.client.get_workflow_handle_for(RunGraph.run, str(run_id)).result(), 60)
+    assert (result.status, result.outputs) == ("succeeded", {"double": 42})
+    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
+    listed = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()
+    assert [r["id"] for r in listed] == [str(run_id)]  # the sub-run isn't listed on its own
+    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")).json()
+    [child] = detail["children"]
+    step = next(n["id"] for n in g.nodes if n["key"] == "r")
+    assert (child["kind"], child["parent_run_id"], child["parent_step_id"], child["status"]) == (
+        "subflow",
+        str(run_id),
+        step,
+        "succeeded",
+    )
+    assert child["workflow_id"] == str(sub_id)
+    sub_detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{child['id']}")).json()
+    assert [s["key"] for s in sub_detail["steps"]] == ["t"] and sub_detail["parent_run_id"] == str(run_id)
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_worker_db.py`
Expected: 1 failed, 3 passed:
`AssertionError: assert ('failed', None) == ('succeeded', {'double': 42})`. The store doesn't load the pin, so the
sub-flow step fails, and the run with it.

- [ ] **Step 3: Implement**

In `backend/src/dewpoint/apps/worker/store.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/store.py b/backend/src/dewpoint/apps/worker/store.py
--- a/backend/src/dewpoint/apps/worker/store.py
+++ b/backend/src/dewpoint/apps/worker/store.py
@@ -18,7 +18,7 @@
 from dewpoint.core.models.workflows import WorkflowVersion
 from dewpoint.core.plugins.registry import load_node_types
 from dewpoint.core.runs import service as runs
-from dewpoint.engine.runtime.activities import ProjectInput, RunSummary, StepRow, VersionData
+from dewpoint.engine.runtime.activities import ProjectInput, RunStart, RunSummary, StepRow, VersionData

 REFUSED = ("22", "23")  # SQLSTATE classes: data exceptions, integrity violations
 _log = structlog.get_logger("dewpoint.worker")
@@ -62,6 +62,8 @@
                 expressions=list(v.expressions),
                 cel_profile=v.cel_profile,
                 manifests={t.ref: t.manifest for t in types},
+                subflow_version_ids=dict(sorted(v.subflow_version_ids.items())),
+                failure_handler_version_id=str(v.failure_handler_version_id) if v.failure_handler_version_id else None,
             )

     async def project(self, data: ProjectInput) -> None:
@@ -69,6 +71,8 @@
         try:
             async with self.sessionmaker() as s, s.begin():
                 await tenant_scope(s, tenant)
+                if data.start is not None:
+                    await _start(s, tenant, data.start)
                 await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps])
                 if data.run is not None:
                     await _finish(s, data.run)
@@ -80,6 +84,8 @@
     async def _one_by_one(self, tenant: uuid.UUID, data: ProjectInput) -> None:
         async with self.sessionmaker() as s, s.begin():
             await tenant_scope(s, tenant)
+            if data.start is not None:
+                await _start(s, tenant, data.start)
             for row in data.steps:
                 try:
                     async with s.begin_nested():
@@ -107,6 +113,22 @@
                     _log.warning("projection_run_refused", run_id=data.run.run_id, sqlstate=state)


+async def _start(s: AsyncSession, tenant: uuid.UUID, start: RunStart) -> None:
+    await runs.ensure_run(
+        s,
+        run_id=uuid.UUID(start.run_id),
+        tenant_id=tenant,
+        workflow_id=uuid.UUID(start.workflow_id),
+        version_id=uuid.UUID(start.version_id),
+        mode=start.mode,
+        kind=start.kind,
+        parent_run_id=uuid.UUID(start.parent_run_id),
+        parent_step_id=uuid.UUID(start.parent_step_id) if start.parent_step_id else None,
+        parent_iteration_key=start.parent_iteration_key,
+        started_at=datetime.fromisoformat(start.started_at),
+    )
+
+
 async def _finish(s: AsyncSession, run: RunSummary) -> None:
     await runs.finish_run(
         s,
```

In `backend/src/dewpoint/apps/api/routes/runs.py`:

```diff
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -1,6 +1,7 @@
 # SPDX-License-Identifier: Apache-2.0
-"""Runs, read-only (spec §8): the list, and one run with its steps. The UI reads this projection, never Temporal
-history. Starting runs isn't public until 2b."""
+"""Runs, read-only (spec §8): the list of top-level runs, and one run with its steps and the sub-runs it started (its
+sub-flows and failure handler). The UI reads this projection, never Temporal history. Starting runs isn't public
+until 2b."""

 import uuid
 from datetime import datetime
@@ -31,6 +32,16 @@
         "ended_at": _when(r.ended_at),
         "error": {"code": r.error_code, "message": r.error_message} if r.error_code else None,
         "iterations": r.iterations,
+        "kind": r.kind,
+        "parent_run_id": str(r.parent_run_id) if r.parent_run_id else None,
+    }
+
+
+def _child(r: Run) -> dict[str, object]:
+    return {
+        **_run(r),
+        "parent_step_id": str(r.parent_step_id) if r.parent_step_id else None,
+        "parent_iteration_key": r.parent_iteration_key,
     }


@@ -71,4 +82,8 @@
     run = await service.get_run(db, run_id)
     if run is None or run.tenant_id != ctx.tenant_id:
         raise HTTPException(404, detail={"error": "not_found"})
-    return {**_run(run), "steps": [_step(r) for r in await service.run_steps(db, run.id)]}
+    return {
+        **_run(run),
+        "steps": [_step(r) for r in await service.run_steps(db, run.id)],
+        "children": [_child(c) for c in await service.children(db, run.id)],
+    }
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_worker_db.py`
Expected: 4 passed.

- [ ] **Step 5: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/apps tests/core \
  && git add src/dewpoint/apps/worker/store.py src/dewpoint/apps/api/routes/runs.py tests/apps/worker/test_worker_db.py \
  && git commit -m "feat(worker): sub-runs write their own rows, and the runs API shows them under their parent" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Checkpoint 2.** Children work end to end: batches, sub-flows, the failure handler, grants, and sub-runs in the
database and the API. Stop for the owner's review before Task 7.

---

### Task 7: Continue-as-new at a quiescent point, with drain mode

Each turn of the drive loop checks, before anything new starts, whether the execution may continue-as-new
(decision 14):
- it continues opportunistically, past `checkpoint_events`, at a point that is already quiescent;
- past `drain_events`, or when Temporal suggests it, it drains: it starts nothing new until what's outstanding
  settles, then continues. The loop also wakes when a drain is due, so draining begins at the first workflow task
  past the threshold.

Quiescent means that nothing but sleeping timers and the projection is outstanding, that the budget isn't asking,
and that no signal waits.

A timer step records its wake time instead of sleeping inline, so a snapshot can carry it. On continue:
- the timers stop;
- the projection and the pending signals are flushed;
- queued units go back to the scheduler;
- the snapshot (decision 16) becomes the continued run's input.

A continued run restores the snapshot, re-arms each timer at its original wake time, and keeps the original
deadline. Both workflow types do this, so a batch or a sub-flow continues too. A snapshot of another format is read
no further: a run ends `internal_error`, and a batch fails as a workflow. The thresholds are run inputs, with the
spec's values as defaults, because the test server never suggests continue-as-new (go/no-go 4).

The tests:
- **An opportunistic checkpoint.** It ends as the run would have without one, with no fresh cap.
- **The threshold test (spec §6).** It drains with batches, a sub-flow, activities and a timer outstanding.
  Nothing is terminated or restarted, each ambiguous send happens once, and the timer fires at its original wake
  time.
- **The measured headroom test (spec §10, decision 17).**
  - It shows that draining began with the cap saturated: the snapshot's `units` are 90 activities and 10 children.
  - It shows that the retries, the grants and the heartbeats all happened while draining. It counts the first two
    from the root's history between the drain's first and last event. It compares each heartbeat's time, which
    `testkit.slow` now records, with the drain's start, which the snapshot records.
  - It prints what draining added, and asserts at most 1,000 events and, for this workload, 512 KiB. Planning
    measured 405–501 events and 98–131 KB.
- **A snapshot of another format**, for a run and for a batch (decision 16).

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/activities.py`, `backend/src/dewpoint/engine/runtime/execution.py`,
  `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/tests/support/plugins/testkit.py` (`testkit.slow` records its heartbeats)
- Create: `backend/tests/apps/worker/test_run_graph_continue.py`

**Interfaces:**
- Consumes:
  - from Task 2, `Scheduler.to_json`/`from_json`, `give_back` and `SNAPSHOT_FORMAT`;
  - from Task 5, `Execution` and both workflow types;
  - from the harness, `start(client, store, g, trigger, **RunInput options)`;
  - from testkit, `SlowSend.sent` and the `testkit.slow`, `testkit.slow_send` and `testkit.fail_n` nodes.
- Produces:
  - `CHECKPOINT_EVENTS = 2_000` and `DRAIN_EVENTS = 4_000`;
  - `RunInput` and `BatchInput` gain `snapshot: dict | None = None`, `checkpoint_events` and `drain_events`;
  - `execution.CONTINUE`;
  - `Execution._drive() -> str | None`, which returns `CONTINUE` to continue-as-new;
  - `Execution._snapshot() -> dict`, `_restore(program, snapshot)` and `_flush()`;
  - `Execution._drain_due() -> bool`, which the drive loop also wakes on;
  - the snapshot's `drained: {"at": iso, "events": [from, to], "bytes": [from, to], "units": {kind: count}}`, which
    draining sets;
  - `testkit.Slow.beats: list[tuple[str, datetime]]`: each heartbeat's run id and time.

- [ ] **Step 1: Write the failing tests**

`testkit.slow` records its heartbeats and their times, as `testkit.slow_send` records its sends. In
`backend/tests/support/plugins/testkit.py`:

```diff
diff --git a/backend/tests/support/plugins/testkit.py b/backend/tests/support/plugins/testkit.py
--- a/backend/tests/support/plugins/testkit.py
+++ b/backend/tests/support/plugins/testkit.py
@@ -2,6 +2,7 @@
 """Engine test fixtures. Lives under tests/, so it is never packaged or registered in production."""

 import asyncio
+from datetime import UTC, datetime
 from typing import Any, ClassVar, Literal

 from pydantic import BaseModel, Field
@@ -63,10 +64,13 @@


 class Slow(Node):
+    """Takes `seconds`, heartbeating each second. `beats` records each heartbeat's run and time, for the tests."""
+
     type = "testkit.slow"
     version = 1
     title = "Slow"
     Config = SlowConfig
+    beats: ClassVar[list[tuple[str, datetime]]] = []

     async def run(self, ctx: StepContext, config: SlowConfig) -> Empty:
         remaining = config.seconds
@@ -75,6 +79,7 @@
             await asyncio.sleep(step)
             remaining -= step
             ctx.heartbeat(remaining)
+            Slow.beats.append((str(ctx.run_id), datetime.now(UTC)))
         return Empty()


```

Create `backend/tests/apps/worker/test_run_graph_continue.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Continue-as-new (spec §6, 2a-3b): only at a quiescent point, opportunistically past `checkpoint_events`, or after
draining past `drain_events`. Nothing outstanding is cancelled, abandoned or restarted; a timer keeps its wake time;
the budget carries over; and draining adds a bounded number of events (the measured headroom test)."""

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowFailureError, WorkflowHistory
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime.activities import BATCH, BUDGET, ENGINE_QUEUE, BatchInput, Parent
from dewpoint.engine.runtime.workflow import LoopBatch
from tests.apps.worker.harness import TENANT, MemoryStore, start, workers
from tests.support.graphs import G, cel, ref
from tests.support.plugins.testkit import Slow, SlowSend

ECHO, LOOP, RUN = "testkit.echo@1", "flow.loop@1", "flow.run_workflow@1"
HEADROOM_EVENTS = 1_000  # spec §6: draining adds at most about this many events
HEADROOM_BYTES = 512 * 1024  # and this many bytes of history
DRAIN_AT = 100  # just past the first turn's commands: every unit has started, and none has ended


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


async def chain(client: Client, workflow_id: str, first_run: str) -> list[WorkflowHistory]:
    """Every run of a continue-as-new chain, oldest first."""
    out: list[WorkflowHistory] = []
    run = first_run
    while run:
        history = await client.get_workflow_handle(workflow_id, run_id=run).fetch_history()
        out.append(history)
        last = history.events[-1]
        attrs = last.workflow_execution_continued_as_new_event_attributes
        run = (
            attrs.new_execution_run_id if last.HasField("workflow_execution_continued_as_new_event_attributes") else ""
        )
    return out


def snapshot(history: WorkflowHistory) -> dict[str, Any]:
    """The snapshot a run continued with: the continued run's input."""
    attrs = history.events[-1].workflow_execution_continued_as_new_event_attributes
    return dict(json.loads(attrs.input.payloads[0].data)["snapshot"])


def count(histories: list[WorkflowHistory], kind: int) -> int:
    return sum(e.event_type == kind for h in histories for e in h.events)


async def test_a_long_run_continues_as_new_and_ends_as_it_would_have(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"))
    g.node("l", LOOP, {"items": list(range(40)), "collect": ref("steps.x.output.value")})
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, checkpoint_events=120)
        result = await asyncio.wait_for(handle.result(), 60)
        runs = await chain(env.client, handle.id, handle.first_execution_run_id or "")
    assert len(runs) >= 2, "it never continued as new"
    assert (result.status, result.outputs) == ("succeeded", {"items": list(range(40))})
    assert result.iterations == 40  # the budget carried over: no fresh cap after continue-as-new
    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
    assert len(rows) == 40 and {(r.attempt, r.status) for r in rows} == {(1, "succeeded")}


def doubler() -> G:
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "outputs": {"double": ref("steps.t.output.double")},
    }
    g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    return g


async def test_draining_settles_what_is_outstanding_and_a_timer_keeps_its_wake_time(
    own_env: WorkflowEnvironment,
) -> None:
    """Spec §6's threshold test: drain mode is entered while loop-batch children, a sub-flow, activities and a timer
    are outstanding. No child is terminated or restarted, each activity completes once, the timer fires at its
    original wake time, and the continued run carries on from the snapshot."""
    store = MemoryStore()
    sub = store.publish(doubler())
    g = graph(double=ref("steps.r.output.double"), count=ref("steps.l.output.count"))
    g.node("s", LOOP, {"items": [1, 2, 3, 4, 5], "concurrency": 5})
    g.node("send", "testkit.slow_send@1", {"seconds": 2}).edge("s", "send", "body")
    g.node("d", "flow.delay@1", {"duration_s": 3600})
    g.node("l", LOOP, {"items": list(range(150))}).node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    g.node("r", RUN, {"workflow_id": str(sub), "input": {"n": 21}})
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {}, drain_events=15)
        result = await asyncio.wait_for(handle.result(), 120)
        runs = await chain(own_env.client, handle.id, handle.first_execution_run_id or "")
    assert (result.status, result.outputs) == ("succeeded", {"double": 42, "count": 150})
    assert len(runs) >= 2, "it never drained"
    assert SlowSend.sent.count(handle.id) == 5  # each ambiguous send once
    started = count(runs, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED)
    assert started == 3  # two batches and the sub-flow, none restarted
    assert count(runs, EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_TERMINATED) == 0
    carried = [s for s in (snapshot(h) for h in runs[:-1]) if s["timers"]]
    assert carried, "the timer never went into a snapshot"
    [delay] = [r for r in store.steps(handle.id) if r.node_key == "d"]
    assert delay.started_at and delay.ended_at
    took = datetime.fromisoformat(delay.ended_at) - datetime.fromisoformat(delay.started_at)
    assert timedelta(seconds=3599) <= took <= timedelta(seconds=3601), took  # its original wake time


async def test_the_headroom_draining_adds_is_measured_and_bounded(own_env: WorkflowEnvironment) -> None:
    """Spec §10's measured headroom test. Draining begins with the in-flight cap saturated: 80 slow activities that
    heartbeat, 10 activities that fail once and retry, and 10 sub-flows that ask for more budget once they're past a
    slow step. The retries, the heartbeats and the grants all happen while it drains. What draining added, in events
    and bytes, is recorded in the snapshot, and stays within the headroom."""
    store = MemoryStore()
    sub = G()
    sub.settings = {
        "input_schema": {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
        "outputs": {"n": ref("steps.k.output.count")},
    }
    sub.node("s", "testkit.slow@1", {"seconds": 1})  # so it asks for budget while its parent drains
    sub.node("k", "flow.filter@1", {"items": ref("trigger.items"), "predicate": cel("true")}).edge("s", "k")
    sub_id = store.publish(sub)
    g = graph()
    for i in range(8):  # 80 slow activities, heartbeating each second
        g.node(f"l{i}", LOOP, {"items": list(range(10)), "concurrency": 10})
        g.node(f"w{i}", "testkit.slow@1", {"seconds": 3}).edge(f"l{i}", f"w{i}", "body")
    g.node("f", LOOP, {"items": list(range(10)), "concurrency": 10})  # 10 that fail once, then retry
    g.node("fail", "testkit.fail_n@1", {"failures": 1}).edge("f", "fail", "body")
    g.node("c", LOOP, {"items": [list(range(1_200))] * 10, "concurrency": 10})  # 10 sub-flows that ask for more
    g.node("r", RUN, {"workflow_id": str(sub_id), "input": {"items": ref("item")}}).edge("c", "r", "body")
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, {}, drain_events=DRAIN_AT)
        result = await asyncio.wait_for(handle.result(), 180)
        runs = await chain(own_env.client, handle.id, handle.first_execution_run_id or "")
    assert result.status == "succeeded", result.error
    assert len(runs) >= 2, "it never drained"
    drained = snapshot(runs[0])["drained"]
    assert drained["units"] == {"activities": 90, "children": 10}  # the cap was saturated when draining began
    (began, continued), (size_began, size_continued) = drained["events"], drained["bytes"]
    during = [e for e in runs[0].events if began < e.event_id <= continued]
    retried = [
        e
        for e in during
        if e.HasField("activity_task_scheduled_event_attributes")
        and e.activity_task_scheduled_event_attributes.activity_type.name == "testkit.fail_n.v1"
    ]
    granted = [
        e
        for e in during
        if e.HasField("signal_external_workflow_execution_initiated_event_attributes")
        and e.signal_external_workflow_execution_initiated_event_attributes.signal_name == BUDGET
    ]
    assert (len(retried), len(granted)) == (10, 10)  # every retry and every grant happened while draining
    beats = [at for run, at in Slow.beats if run == handle.id]
    assert len(beats) == 80 * 3 and min(beats) > datetime.fromisoformat(drained["at"])  # and every heartbeat
    events, added = continued - began, size_continued - size_began
    print(f"draining added {events} events and {added} bytes")  # the measurement the headroom is set from
    assert events <= HEADROOM_EVENTS and added <= HEADROOM_BYTES


async def test_a_snapshot_of_another_format_fails_the_run(env: WorkflowEnvironment) -> None:
    """Decision 16: a continued run whose snapshot this build can't read ends `internal_error`; it never hangs."""
    store = MemoryStore()
    g = graph().node("a", ECHO, {"value": 1})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {}, snapshot={"snapshot_format": 99})
        result = await asyncio.wait_for(handle.result(), 30)
    assert (result.status, result.error["code"]) == ("failed", "internal_error")


async def test_a_batch_with_a_snapshot_of_another_format_fails_as_a_workflow(env: WorkflowEnvironment) -> None:
    """Its parent then fails the loop (decision 4) instead of waiting for a batch that can't carry on."""
    store = MemoryStore()
    version = store.add(graph().node("l", LOOP, {"items": [1]}).node("x", ECHO).edge("l", "x", "body"))
    now = (await env.get_current_time()).isoformat()
    parent = Parent("nobody", str(uuid.uuid4()), str(uuid.uuid4()), "", BATCH, now, 0)
    batch = BatchInput(
        TENANT, parent.run_id, version, str(uuid.uuid4()), [], [], 0, 1, True, {}, {}, now, parent,
        snapshot={"snapshot_format": 99},
    )  # fmt: skip
    async with workers(env.client, store):
        handle = await env.client.start_workflow(LoopBatch.run, batch, id=str(uuid.uuid4()), task_queue=ENGINE_QUEUE)
        with pytest.raises(WorkflowFailureError) as failed:
            await asyncio.wait_for(handle.result(), 30)
    assert isinstance(failed.value.cause, ApplicationError) and failed.value.cause.type == "internal_error"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_run_graph_continue.py`
Expected: 5 failed, each with a `TypeError`: `RunInput.__init__()` or `BatchInput.__init__()` got an unexpected
keyword argument (`'checkpoint_events'`, `'drain_events'` or `'snapshot'`).

- [ ] **Step 3: The thresholds and the snapshot field**

In `backend/src/dewpoint/engine/runtime/activities.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/activities.py b/backend/src/dewpoint/engine/runtime/activities.py
--- a/backend/src/dewpoint/engine/runtime/activities.py
+++ b/backend/src/dewpoint/engine/runtime/activities.py
@@ -20,6 +20,8 @@
     "request_budget",
     "budget",
 )  # child -> parent (child, key, need, want, held); parent -> child (key, granted)
+CHECKPOINT_EVENTS = 2_000  # continue-as-new at the next quiescent point after this many events (spec §6)
+DRAIN_EVENTS = 4_000  # drain mode from this many events, or when Temporal suggests it
 # In a plugin step's failure details: the activity's own mapping made this failure. `RunGraph` trusts no other failure
 # as the node's: the SDK makes its own (a worker shutting down, an exception nothing caught), and those say nothing
 # of whether the request went out.
@@ -62,6 +64,9 @@
     cel_schedule_to_start_s: float = 600  # no evaluator for the profile after this: cel_profile_unavailable
     parent: Parent | None = None  # a sub-flow or a failure handler; None for a run the dispatcher started
     workflow_id: str = ""  # a sub-run's workflow: it writes its own row with it, before its version loads
+    snapshot: dict[str, Any] | None = None  # a continued run: where it carries on (spec §6, `snapshot_format` 1)
+    checkpoint_events: int = CHECKPOINT_EVENTS
+    drain_events: int = DRAIN_EVENTS


 @dataclass(frozen=True)
@@ -93,6 +98,9 @@
     parent: Parent
     mode: str = LIVE
     cel_schedule_to_start_s: float = 600
+    snapshot: dict[str, Any] | None = None
+    checkpoint_events: int = CHECKPOINT_EVENTS
+    drain_events: int = DRAIN_EVENTS


 @dataclass(frozen=True)
```

- [ ] **Step 4: Drain, checkpoint, snapshot and restore**

In `backend/src/dewpoint/engine/runtime/execution.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -6,9 +6,13 @@
 order, so a replay applies them the same way. Nothing else creates concurrency.

 Children draw their iterations from their parent's budget (spec §6): a child signals `request_budget` to its parent,
-which answers `budget` in the order the requests reach its history."""
+which answers `budget` in the order the requests reach its history. An execution continues-as-new at a quiescent
+point (no activity and no child outstanding): opportunistically past `checkpoint_events`, or after draining past
+`drain_events` (or when Temporal suggests it), when it starts nothing new and waits for what's outstanding. A timer
+isn't outstanding: its wake time goes into the snapshot, and the continued run re-arms it."""

 import asyncio
+import uuid
 from collections.abc import Mapping, Sequence
 from dataclasses import asdict, dataclass, replace
 from datetime import UTC, datetime, timedelta
@@ -25,6 +29,7 @@
     from dewpoint.engine.cel.profile import LOCAL_CEL_PROFILE
     from dewpoint.engine.cel.route import YieldBudget
     from dewpoint.engine.graph.values import CelValue, RefValue, TemplateValue
+    from dewpoint.engine.registry import control
     from dewpoint.engine.runtime import nodes, resolve
     from dewpoint.engine.runtime.activities import (
         BATCH,
@@ -66,6 +71,7 @@
     from dewpoint.engine.runtime.scheduler import (
         CAP_MESSAGE,
         ITERATION_CAP_EXCEEDED,
+        SNAPSHOT_FORMAT,
         Batch,
         BatchOutcome,
         Collect,
@@ -88,6 +94,7 @@
 NODE_TYPE_UNAVAILABLE = "node_type_unavailable"  # the registry has it, but this build's workers don't run it
 CANCELLED = Failure("cancelled", "The run was cancelled.")
 AMBIGUOUS = "ambiguous"  # a manifest's side_effect: the request may have been sent
+CONTINUE = "continue"  # `_drive`'s answer when the execution continues-as-new


 @dataclass(frozen=True)
@@ -185,6 +192,8 @@
         self._started: dict[Instance, str] = {}
         self._cel_modes: dict[Instance, str] = {}
         self._projects = 0
+        self._timers: dict[Instance, datetime] = {}  # a timer step asleep -> its wake time
+        self._resume: list[Instance] = []  # timer steps a snapshot carried over: they re-arm first
         self._mail: list[Need] = []  # children's budget requests, as their signals arrived
         self._answers: list[tuple[str, int]] = []  # our parent's answers
         self._ask: str | None = None  # the request we sent our parent, unanswered
@@ -196,6 +205,8 @@
         self._batches: dict[
             tuple[Instance, int], Batch
         ] = {}  # a batch unit's key -> the batch (its items aren't hashable)
+        self._drained: dict[str, Any] = {}  # what draining waited for, and added: history events and bytes
+        self._draining = False  # drain mode: nothing new starts until the execution continues-as-new

     # --- the budget signals ----------------------------------------------------------------------------------------

@@ -222,6 +233,8 @@
         parent: Parent | None,
         run_started_at: datetime,
         deadline: datetime,
+        checkpoint_events: int,
+        drain_events: int,
     ) -> None:
         self.tenant_id, self.run_id, self.version_id, self.mode = tenant_id, run_id, version_id, mode
         self.trigger = trigger
@@ -230,26 +243,32 @@
         self.parent = parent
         self.depth = parent.depth if parent is not None else 0
         self.run_started_at, self.deadline = run_started_at, deadline
+        self.checkpoint_events, self.drain_events = checkpoint_events, drain_events
         self.vars: dict[str, Any] = {}
         if parent is not None:
             self._secrets = remember((), tuple(parent.secrets))

     # --- the scheduler loop ----------------------------------------------------------------------------------------

-    async def _drive(self) -> None:
-        """Drive the scheduler until the execution ends."""
+    async def _drive(self) -> str | None:
+        """Drive the scheduler until the execution ends (None), or until it continues-as-new (CONTINUE)."""
         tasks: dict[tuple[Any, ...], asyncio.Task[_Effect | None]] = {}
         waiting: list[tuple[Any, ...]] = []
+        for inst in self._resume:
+            tasks[("step", inst)] = asyncio.create_task(self._timer(inst, self._timers[inst]))
+        self._resume = []
         clock = asyncio.create_task(asyncio.sleep(max(0.0, (self.deadline - workflow.now()).total_seconds())))
         try:
             while self.sched.ended is None:
                 self._serve_budget()
-                waiting += [("step", i) for i in self.sched.take_ready()]
-                waiting += [("collect", c) for c in self.sched.take_collects()]
-                for b in self.sched.take_batches():
-                    self._batches[(b.loop, b.start)] = b
-                    waiting.append(("batch", b.loop, b.start))
+                if not self._draining:
+                    waiting += [("step", i) for i in self.sched.take_ready()]
+                    waiting += [("collect", c) for c in self.sched.take_collects()]
+                    for b in self.sched.take_batches():
+                        self._batches[(b.loop, b.start)] = b
+                        waiting.append(("batch", b.loop, b.start))
                 for inst in self.sched.take_cancels():
+                    self._timers.pop(inst, None)
                     for key in [k for k in tasks if k[0] in ("step", "batch") and self._owner(k) == inst]:
                         task = tasks.pop(key)
                         task.cancel()  # a child reports back first: the unit stays outstanding until it does
@@ -260,7 +279,28 @@
                 self._queue_settled()
                 if self.sched.ended is not None:
                     break
-                while waiting and self._in_flight(tasks) < IN_FLIGHT_CAP:
+                # Before anything new starts: is this a point where continue-as-new may happen (spec §6)?
+                length = workflow.info().get_current_history_length()
+                if not self._draining and self._drain_due():
+                    self._draining = True  # start nothing new; continue-as-new once what's outstanding settles
+                    self._drained = {
+                        "at": workflow.now().isoformat(),
+                        "events": [length],
+                        "bytes": [workflow.info().get_current_history_size()],
+                        "units": self._units(tasks),  # what the drain waits for
+                    }
+                if (self._draining or length >= self.checkpoint_events) and self._quiescent(tasks):
+                    if self._draining:  # measured, for the headroom (spec §6): what draining added
+                        self._drained["events"].append(length)
+                        self._drained["bytes"].append(workflow.info().get_current_history_size())
+                    await self._settle_for_continue(tasks)
+                    self.sched.give_back(
+                        [w[1] for w in waiting if w[0] == "step"],
+                        [w[1] for w in waiting if w[0] == "collect"],
+                        [self._batches.pop((w[1], w[2])) for w in waiting if w[0] == "batch"],
+                    )
+                    return CONTINUE
+                while not self._draining and waiting and self._in_flight(tasks) < IN_FLIGHT_CAP:
                     unit = waiting.pop(0)
                     tasks[unit] = asyncio.create_task(self._unit(unit))
                 if self._rows and not any(key[0] == "project" for key in tasks):  # one at a time: rows wait for it
@@ -269,7 +309,12 @@
                 if not tasks:
                     raise RuntimeError("nothing is running and the run hasn't ended")
                 wake = asyncio.create_task(
-                    workflow.wait_condition(lambda: bool(self._mail or self._answers or self._dirty))
+                    workflow.wait_condition(
+                        lambda: (
+                            bool(self._mail or self._answers or self._dirty)
+                            or (not self._draining and self._drain_due())
+                        )
+                    )
                 )
                 done, _ = await workflow.wait([*tasks.values(), clock, wake], return_when=asyncio.FIRST_COMPLETED)
                 wake.cancel()
@@ -292,6 +337,49 @@
             # mustn't reach them again: Temporal refuses a second cancel of the same child, and then this workflow
             # task could never complete. An end already decided stands.
             await _landed(asyncio.gather(*tasks.values(), return_exceptions=True))
+        return None
+
+    def _drain_due(self) -> bool:
+        """Past `drain_events`, or Temporal suggests continuing. The drive loop wakes for it too, so a drain begins at
+        the first workflow task past the threshold, not at the next unit's end."""
+        info = workflow.info()
+        return info.get_current_history_length() >= self.drain_events or info.is_continue_as_new_suggested()
+
+    def _units(self, tasks: Mapping[tuple[Any, ...], asyncio.Task[Any]]) -> dict[str, int]:
+        """What's outstanding, by kind: activities, children, timers, values (CEL, filters), collects, the
+        projection, cancelled units."""
+        kinds: dict[str, int] = {}
+        for key in tasks:
+            kind = self._kind(key)
+            kinds[kind] = kinds.get(kind, 0) + 1
+        return dict(sorted(kinds.items()))
+
+    def _kind(self, key: tuple[Any, ...]) -> str:
+        if key[0] == "batch":
+            return "children"
+        if key[0] != "step":
+            return str(key[0])
+        if key[1] in self._timers:
+            return "timers"
+        step = self.sched.step(key[1])
+        if not step.control:
+            return "activities"
+        return "children" if step.ref == control.RUN_WORKFLOW else "values"
+
+    def _quiescent(self, tasks: Mapping[tuple[Any, ...], asyncio.Task[Any]]) -> bool:
+        """No activity and no child outstanding, and no request to or from a parent or child: a sleeping timer step
+        doesn't count, nor a projection (it's written before the run continues)."""
+        idle = all(k[0] == "project" or (k[0] == "step" and k[1] in self._timers) for k in tasks)
+        return idle and not self.sched.budget.asking and not self._mail and not self._answers
+
+    async def _settle_for_continue(self, tasks: dict[tuple[Any, ...], asyncio.Task[Any]]) -> None:
+        """Continue-as-new: the sleeping timer steps stop here (their wake times go into the snapshot), and the
+        projection in flight lands."""
+        for key, task in tasks.items():
+            if key[0] == "step":
+                task.cancel()
+        await asyncio.gather(*tasks.values(), return_exceptions=True)
+        tasks.clear()

     @staticmethod
     def _in_flight(tasks: Mapping[tuple[Any, ...], asyncio.Task[Any]]) -> int:
@@ -610,10 +698,13 @@
             return await self._filter(inst, step, decision.filter_items)
         if decision.subflow is not None:
             return await self._subflow(inst, step, decision.subflow, cel_mode)
-        if decision.wait_s is not None:
-            await asyncio.sleep(decision.wait_s)
-        if decision.wait_until is not None:
-            await asyncio.sleep(max(0.0, (decision.wait_until - workflow.now()).total_seconds()))
+        wake = (
+            workflow.now() + timedelta(seconds=decision.wait_s) if decision.wait_s is not None else decision.wait_until
+        )
+        if wake is not None:
+            if cel_mode is not None:
+                self._cel_modes[inst] = cel_mode
+            return await self._timer(inst, wake)
         return _Effect(
             output=decision.output,
             ports=decision.ports,
@@ -621,6 +712,13 @@
             end=decision.end,
             cel_mode=cel_mode,
         )
+
+    async def _timer(self, inst: Instance, wake: datetime) -> _Effect:
+        """A timer step asleep until `wake`. It isn't outstanding work: a continue-as-new carries its wake time."""
+        self._timers[inst] = wake
+        await asyncio.sleep(max(0.0, (wake - workflow.now()).total_seconds()))
+        del self._timers[inst]
+        return _Effect(output={}, cel_mode=self._cel_modes.get(inst))

     async def _filter(self, inst: Instance, step: Step, items: list[Any]) -> _Effect:
         if not await self._take_budget(f"filter:{iteration_key(inst.scope)}:{step.key}", len(items)):
@@ -687,6 +785,8 @@
             self.cel_schedule_to_start_s,
             parent=parent,
             workflow_id=start.workflow_id,
+            checkpoint_events=self.checkpoint_events,
+            drain_events=self.drain_events,
         )
         used: int | None = None
         try:
@@ -755,6 +855,8 @@
             parent=parent,
             mode=self.mode,
             cel_schedule_to_start_s=self.cel_schedule_to_start_s,
+            checkpoint_events=self.checkpoint_events,
+            drain_events=self.drain_events,
         )
         used: int | None = None
         try:
@@ -881,9 +983,55 @@
         )
         return failure, outcome, retryable

+    # --- continue-as-new ------------------------------------------------------------------------------------------
+
+    def _snapshot(self) -> dict[str, Any]:
+        """Where a continued run carries on (spec §6, `snapshot_format` 1). The projection is written first, so no
+        row is carried; timers carry their wake times."""
+        return {
+            "snapshot_format": SNAPSHOT_FORMAT,
+            "scheduler": self.sched.to_json(),
+            "variables": self.vars,
+            "secrets": list(self._secrets),
+            "run_started_at": self.run_started_at.isoformat(),
+            "deadline": self.deadline.isoformat(),
+            "drained": self._drained,
+            "timers": [
+                [
+                    [[k, n] for k, n in i.scope],
+                    str(i.step),
+                    wake.isoformat(),
+                    self._started.get(i),
+                    self._cel_modes.get(i),
+                ]
+                for i, wake in self._timers.items()
+            ],
+        }
+
+    def _restore(self, program: Program, snapshot: dict[str, Any]) -> None:
+        if snapshot.get("snapshot_format") != SNAPSHOT_FORMAT:
+            raise ValueError(f"unknown snapshot format {snapshot.get('snapshot_format')!r}")
+        self.program = program
+        self.sched = Scheduler.from_json(program, snapshot["scheduler"])
+        self.vars = dict(snapshot["variables"])
+        self._secrets = remember((), tuple(snapshot["secrets"]))
+        for key, step, wake, started, mode in snapshot["timers"]:
+            inst = Instance(tuple((str(k), int(n)) for k, n in key), uuid.UUID(step))
+            self._timers[inst] = datetime.fromisoformat(wake)
+            if started:
+                self._started[inst] = started
+            if mode:
+                self._cel_modes[inst] = mode
+            self._resume.append(inst)
+
+    async def _flush(self) -> None:
+        """Before continuing as new: every queued row written, and every signal sent."""
+        await self._project_end(None)
+

 __all__ = [
     "CEL_BATCH",
+    "CONTINUE",
     "DEADLINE_EXCEEDED",
     "INTERNAL_ERROR",
     "IN_FLIGHT_CAP",
```

In `backend/src/dewpoint/engine/runtime/workflow.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -5,10 +5,11 @@
   draws its iterations from its parent.
 - `LoopBatch` runs a slice of a loop over more than 100 items, as a child of the execution that holds the loop.

-Both drive the shared `Execution` loop."""
+Both drive the shared `Execution` loop, and both may continue-as-new at a quiescent point, carrying a snapshot."""

 import asyncio
 import uuid
+from dataclasses import replace
 from datetime import datetime, timedelta
 from typing import Any

@@ -35,6 +36,7 @@
     from dewpoint.engine.runtime.execution import (
         CANCELLED,
         CEL_BATCH,
+        CONTINUE,
         DEADLINE_EXCEEDED,
         IN_FLIGHT_CAP,
         INTERNAL_ERROR,
@@ -50,6 +52,7 @@
     from dewpoint.engine.runtime.projection import mask
     from dewpoint.engine.runtime.scheduler import (
         ITERATION_CAP,
+        SNAPSHOT_FORMAT,
         Failure,
         OuterScope,
         RunEnd,
@@ -80,8 +83,14 @@
         non-terminal until the handler has ended, so something non-terminal always holds the handler's closure,
         and with it the CEL profiles it pins (spec §4.5). The end is recorded once, counting the handler's
         iterations."""
-        started = workflow.info().start_time
-        if start.parent is not None and start.parent.kind != FAILURE_HANDLER:
+        snapshot = start.snapshot
+        unreadable = snapshot is not None and snapshot.get("snapshot_format") != SNAPSHOT_FORMAT
+        if unreadable:
+            snapshot = None  # nothing of it is read: the run ends below
+        started = datetime.fromisoformat(snapshot["run_started_at"]) if snapshot else workflow.info().start_time
+        if snapshot is not None:
+            deadline = datetime.fromisoformat(snapshot["deadline"])
+        elif start.parent is not None and start.parent.kind != FAILURE_HANDLER:
             deadline = datetime.fromisoformat(start.parent.deadline)
         else:
             deadline = started + timedelta(seconds=start.max_run_duration_s)
@@ -96,9 +105,14 @@
             parent=start.parent,
             run_started_at=started,
             deadline=deadline,
+            checkpoint_events=start.checkpoint_events,
+            drain_events=start.drain_events,
         )
         self.input = start
-        if start.parent is not None:  # its row first: whatever ends it now has a row to end
+        if unreadable:  # a snapshot this build can't read: the run ends, it never hangs (spec §6)
+            message = "This build can't read the run's continue-as-new snapshot."
+            return await self._end_early(RunEnd("failed", Failure(INTERNAL_ERROR, message)))
+        if start.parent is not None and snapshot is None:  # its row first: whatever ends it now has a row to end
             if await self._shielded([], None, self._start_row(start.parent, start.workflow_id, started)):
                 return await self._cancelled_early()  # cancelled while the row was written
         try:
@@ -131,8 +145,13 @@
             return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)))
         outputs: dict[str, Any] | None = None
         try:
-            self._fresh(program)
-            await self._drive()
+            if snapshot is not None:
+                self._restore(program, snapshot)
+            else:
+                self._fresh(program)
+            if await self._drive() == CONTINUE:
+                await self._flush()
+                workflow.continue_as_new(replace(start, snapshot=self._snapshot()))
             end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
             if end.status == "succeeded":
                 end, outputs = await self._outputs_by(end)
@@ -299,6 +318,8 @@
             self.cel_schedule_to_start_s,
             parent=parent,
             workflow_id=workflow_id,
+            checkpoint_events=self.checkpoint_events,
+            drain_events=self.drain_events,
         )
         handler = asyncio.create_task(self._handler(run, child))
         while not handler.done():  # it draws its iterations from this run: answer as it asks
@@ -333,6 +354,11 @@
         they would inline, with the loop's concurrency and error policy, over read-only copies of the scopes around
         the loop; their rows go into the parent's run. It returns what they collected, the failures, and how many
         iterations it used. A fail or stop node, or the deadline, ends the run: the batch reports it as `end`."""
+        snapshot = start.snapshot
+        if snapshot is not None and snapshot.get("snapshot_format") != SNAPSHOT_FORMAT:  # it can't carry on: fail
+            message = "This build can't read the batch's continue-as-new snapshot."  # its loop (decision 4)
+            raise ApplicationError(message, type=INTERNAL_ERROR, non_retryable=True)
+        deadline = snapshot["deadline"] if snapshot else start.parent.deadline
         self._context(
             tenant_id=start.tenant_id,
             run_id=start.run_id,
@@ -343,7 +369,9 @@
             max_run_duration_s=0,
             parent=start.parent,
             run_started_at=datetime.fromisoformat(start.run_started_at),
-            deadline=datetime.fromisoformat(start.parent.deadline),
+            deadline=datetime.fromisoformat(deadline),
+            checkpoint_events=start.checkpoint_events,
+            drain_events=start.drain_events,
         )
         try:
             data = await workflow.execute_local_activity(
@@ -369,22 +397,27 @@
             message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
             raise ApplicationError(message, type=VERSION_UNUSABLE, non_retryable=True) from None
         try:
-            self.program = program
-            self.sched = Scheduler(program, budget=Budget(start.parent.grant, root=False))
-            self.vars = dict(start.variables)
-            outer = [
-                OuterScope(tuple((str(k), int(i)) for k, i in o["key"]), o["results"], o["item"], o["index"])
-                for o in start.outer
-            ]
-            self.sched.start_batch(
-                uuid.UUID(start.loop_step),
-                outer,
-                start.items,
-                offset=start.offset,
-                concurrency=start.concurrency,
-                stop_on_error=start.stop_on_error,
-            )
-            await self._drive()
+            if snapshot is not None:
+                self._restore(program, snapshot)
+            else:
+                self.program = program
+                self.sched = Scheduler(program, budget=Budget(start.parent.grant, root=False))
+                self.vars = dict(start.variables)
+                outer = [
+                    OuterScope(tuple((str(k), int(i)) for k, i in o["key"]), o["results"], o["item"], o["index"])
+                    for o in start.outer
+                ]
+                self.sched.start_batch(
+                    uuid.UUID(start.loop_step),
+                    outer,
+                    start.items,
+                    offset=start.offset,
+                    concurrency=start.concurrency,
+                    stop_on_error=start.stop_on_error,
+                )
+            if await self._drive() == CONTINUE:
+                await self._flush()
+                workflow.continue_as_new(replace(start, snapshot=self._snapshot()))
         except asyncio.CancelledError:
             self.sched.end(RunEnd("cancelled", CANCELLED))
             await self._project_end(None)
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest -q -s tests/apps/worker/test_run_graph_continue.py`
Expected: 5 passed. The headroom test prints what draining added (planning saw, for example, `draining added 501
events and 110059 bytes`); note the numbers in the task's ledger line.

- [ ] **Step 6: Checks and commit**

2a-3a's golden histories still replay: a run that never reaches a threshold issues the same commands.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine tests/apps/worker \
  && git add src/dewpoint/engine/runtime/activities.py src/dewpoint/engine/runtime/execution.py \
       src/dewpoint/engine/runtime/workflow.py tests/apps/worker/test_run_graph_continue.py \
  && git commit -m "feat(engine): continue-as-new at a quiescent point, with drain mode and a snapshot" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `ENGINE_ABI` 2, golden histories and the runs guide

Batches, sub-flows, the failure handler and continue-as-new change the command sequence of graphs that 2a-3a
refused with `not_supported`. So `ENGINE_ABI` becomes 2, and a new directory of golden histories starts
(decision 20). It gets six new scenarios: `batches`, `subflows`, `failure_handler`, `grants`, `continue_as_new`
and `drain`.

A scenario that runs sub-flows publishes them through the recorder's store first, so a scenario's graph can be a
function of the store. The recorder records every execution a scenario ran: the runs it continued as, then its
children's executions, breadth first. The replay test replays each one against both workflow types.

The abi1 histories stay in the repo, and only their own build replays them (§7). They also replay against this
build (go/no-go 10).

The runs guide gains:
- sub-flows, failure handlers and large loops;
- one budget per run;
- long runs;
- the sub-run fields in the API;
- the new limits.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/build.py`
- Modify: `backend/tests/engine/replay/scenarios.py`, `backend/tests/engine/replay/record.py`,
  `backend/tests/engine/replay/test_replay.py`
- Create: `backend/tests/engine/replay/dewpoint-0.1.0+abi2/*.json` (recorded, not written by hand)
- Modify: `docs/operations/runs.md`

**Interfaces:**
- Consumes:
  - from Task 5, `MemoryStore.publish`, `LoopBatch`, and the harness's `start(client, store, g, trigger, **options)`;
  - from Task 7, `RunInput.checkpoint_events` and `drain_events`.
- Produces:
  - `ENGINE_ABI = 2`, so the build id is `dewpoint-0.1.0+abi2`;
  - `Scenario.graph: G | Callable[[MemoryStore], G]` and `Scenario.build(store) -> G`;
  - `record.executions(client, workflow_id, run_id) -> list[WorkflowHistory]`;
  - the history files `<name>.json` and `<name>--<n>.json`.

- [ ] **Step 1: Write the failing tests**

The six new scenarios. In `backend/tests/engine/replay/scenarios.py`:

```diff
diff --git a/backend/tests/engine/replay/scenarios.py b/backend/tests/engine/replay/scenarios.py
--- a/backend/tests/engine/replay/scenarios.py
+++ b/backend/tests/engine/replay/scenarios.py
@@ -3,11 +3,15 @@

 2a-3a records what it can run: branches, joins, dead paths and switch; inline loops, filter and transform; every
 error policy; variables and timers; stop, fail, simulation and the deadline; CEL through `cel.evaluate`. 2a-3b adds
-batched loops, sub-flows and continue-as-new; 2a-3c adds local CEL and the yield-point timer."""
+batched loops, sub-flows, the failure handler, grants, continue-as-new and drain mode; 2a-3c adds local CEL and the
+yield-point timer. A scenario that runs sub-flows builds its graph against the recorder's store, which publishes
+them first."""

+from collections.abc import Callable
 from dataclasses import dataclass, field
 from typing import Any

+from tests.apps.worker.harness import MemoryStore
 from tests.support.graphs import G, cel, ref

 ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"
@@ -21,9 +25,12 @@

 @dataclass(frozen=True)
 class Scenario:
-    graph: G
+    graph: G | Callable[[MemoryStore], G]  # a callable publishes the sub-flows it runs, then builds the graph
     trigger: dict[str, Any] = field(default_factory=lambda: dict(TRIGGER))
     options: dict[str, Any] = field(default_factory=dict)  # RunInput fields
+
+    def build(self, store: MemoryStore) -> G:
+        return self.graph(store) if callable(self.graph) else self.graph


 def _graph(**outputs: Any) -> G:
@@ -79,6 +86,74 @@
     return g.edge("a", "f")


+def _batches() -> G:
+    g = _graph(items=ref("steps.l.output.items"), failures=ref("steps.l.output.failures"))
+    items = ["sent"] * 101 + ["rejected"]  # two batches: the second one's last item fails
+    g.node("l", LOOP, {"items": items, "concurrency": 10, "on_item_error": "continue", "collect": ref("item")})
+    g.node("b", "testkit.ambiguous_send@1", {"outcome": ref("item")})
+    return g.edge("l", "b", "body")
+
+
+def _doubler(store: MemoryStore) -> str:
+    g = G()
+    g.settings = {
+        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
+        "outputs": {"double": ref("steps.t.output.double")},
+    }
+    g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
+    return str(store.publish(g))
+
+
+def _broken(store: MemoryStore) -> str:
+    g = G()
+    g.settings = {"input_schema": {"type": "object"}, "outputs": {}}
+    g.node("f", "flow.fail@1", {"message": "the sub-flow gave up"})
+    return str(store.publish(g))
+
+
+def _subflows(store: MemoryStore) -> G:
+    g = _graph(double=ref("steps.r.output.double"), code=ref("steps.x.error.code", default="none"))
+    g.node("r", "flow.run_workflow@1", {"workflow_id": _doubler(store), "input": {"n": ref("trigger.x")}})
+    g.node("x", "flow.run_workflow@1", {"workflow_id": _broken(store)}, on_error="continue")
+    return g
+
+
+def _failure_handler(store: MemoryStore) -> G:
+    handler = G()
+    handler.settings = {"input_schema": {"type": "object"}, "outputs": {}}
+    handler.node("h", ECHO, {"value": ref("trigger.error.code", default="?")})
+    g = _failed()
+    g.settings["failure_handler"] = str(store.publish(handler))
+    return g
+
+
+def _grants(store: MemoryStore) -> G:
+    sub = G()
+    sub.settings = {
+        "input_schema": {"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
+        "outputs": {"n": ref("steps.k.output.count")},
+    }
+    sub.node("k", "flow.filter@1", {"items": ref("trigger.items"), "predicate": cel("item % 2 == 0")})
+    g = _graph(kept=ref("steps.r.output.n"))
+    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sub)), "input": {"items": list(range(1_200))}})
+    return g
+
+
+def _continued() -> G:
+    g = _graph(items=ref("steps.l.output.items"))
+    g.node("l", LOOP, {"items": list(range(30)), "collect": ref("item")})
+    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
+    return g.node("d", "flow.delay@1", {"duration_s": 3_600})
+
+
+def _drained(store: MemoryStore) -> G:
+    g = _graph(count=ref("steps.l.output.count"), double=ref("steps.r.output.double"))
+    g.node("l", LOOP, {"items": list(range(101)), "concurrency": 10})  # two batches: 100 and 1
+    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
+    g.node("r", "flow.run_workflow@1", {"workflow_id": _doubler(store), "input": {"n": 21}})
+    return g.node("d", "flow.delay@1", {"duration_s": 3_600})
+
+
 def scenarios() -> dict[str, Scenario]:
     return {
         "branches": Scenario(_branches()),
@@ -93,4 +168,10 @@
         "deadline": Scenario(
             _graph().node("d", "flow.delay@1", {"duration_s": 3 * 86_400}), options={"max_run_duration_s": 86_400}
         ),
+        "batches": Scenario(_batches()),
+        "subflows": Scenario(_subflows),
+        "failure_handler": Scenario(_failure_handler),
+        "grants": Scenario(_grants),
+        "continue_as_new": Scenario(_continued(), options={"checkpoint_events": 60}),
+        "drain": Scenario(_drained, options={"drain_events": 40}),
     }
```

Record every execution. In `backend/tests/engine/replay/record.py`:

```diff
diff --git a/backend/tests/engine/replay/record.py b/backend/tests/engine/replay/record.py
--- a/backend/tests/engine/replay/record.py
+++ b/backend/tests/engine/replay/record.py
@@ -2,7 +2,10 @@
 """Record this build's golden histories: `uv run python -m tests.engine.replay.record`.

 Only scenarios the build's directory lacks are recorded; a recorded history is never rewritten. A change that alters
-the command sequence increments ENGINE_ABI (engine/runtime/build.py), which starts a new directory."""
+the command sequence increments ENGINE_ABI (engine/runtime/build.py), which starts a new directory.
+
+A scenario records every execution it ran: `<name>.json` is the run's first execution, and `<name>--<n>.json` each
+other one, in the order they're found: the runs it continued as, then its children's, and theirs."""

 import asyncio
 import json
@@ -10,6 +13,7 @@
 from pathlib import Path
 from typing import Any

+from temporalio.client import Client, WorkflowHistory
 from temporalio.testing import WorkflowEnvironment

 import dewpoint
@@ -33,6 +37,23 @@
     return HERE / build_id(dewpoint.__version__)


+async def executions(client: Client, workflow_id: str, run_id: str) -> list[WorkflowHistory]:
+    """Every execution a run led to, breadth first: the runs it continued as, and its children, recursively."""
+    out: list[WorkflowHistory] = []
+    queue = [(workflow_id, run_id)]
+    while queue:
+        wid, rid = queue.pop(0)
+        history = await client.get_workflow_handle(wid, run_id=rid).fetch_history()
+        out.append(history)
+        for e in history.events:
+            if e.HasField("workflow_execution_continued_as_new_event_attributes"):
+                queue.append((wid, e.workflow_execution_continued_as_new_event_attributes.new_execution_run_id))
+            if e.HasField("child_workflow_execution_started_event_attributes"):
+                child = e.child_workflow_execution_started_event_attributes.workflow_execution
+                queue.append((child.workflow_id, child.run_id))
+    return out
+
+
 async def record() -> list[str]:
     target = build_dir()
     missing = {name: s for name, s in scenarios().items() if not (target / f"{name}.json").exists()}
@@ -42,11 +63,13 @@
     store = MemoryStore()
     async with await WorkflowEnvironment.start_time_skipping() as env, workers(env.client, store):
         for name, scenario in sorted(missing.items()):
-            handle = await start(env.client, store, scenario.graph, scenario.trigger, **scenario.options)
+            handle = await start(env.client, store, scenario.build(store), scenario.trigger, **scenario.options)
             await handle.result()
-            history = await handle.fetch_history()
-            data = scrub(json.loads(history.to_json()))
-            (target / f"{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
+            histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
+            for n, history in enumerate(histories):
+                data = scrub(json.loads(history.to_json()))
+                path = target / (f"{name}.json" if n == 0 else f"{name}--{n}.json")
+                path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
     return sorted(missing)


```

Replay each execution against both workflow types. A scenario's name is the part of a file's name before `--`. In
`backend/tests/engine/replay/test_replay.py`:

```diff
diff --git a/backend/tests/engine/replay/test_replay.py b/backend/tests/engine/replay/test_replay.py
--- a/backend/tests/engine/replay/test_replay.py
+++ b/backend/tests/engine/replay/test_replay.py
@@ -1,5 +1,6 @@
 # SPDX-License-Identifier: Apache-2.0
-"""This build's golden histories replay against this build's `RunGraph` (spec §7). The Replayer needs no server."""
+"""This build's golden histories replay against this build's workflows (spec §7): every execution a scenario ran,
+its continued runs and its children included. The Replayer needs no server."""

 import asyncio
 import re
@@ -9,7 +10,7 @@
 from temporalio.client import WorkflowHistory
 from temporalio.worker import Replayer

-from dewpoint.engine.runtime.workflow import RunGraph
+from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
 from tests.engine.replay.record import build_dir
 from tests.engine.replay.scenarios import scenarios

@@ -17,7 +18,8 @@


 def test_every_scenario_is_recorded_for_this_build() -> None:
-    assert {p.stem for p in HISTORIES} == set(scenarios()), "run `uv run python -m tests.engine.replay.record`"
+    recorded = {p.stem.split("--")[0] for p in HISTORIES}
+    assert recorded == set(scenarios()), "run `uv run python -m tests.engine.replay.record`"


 def test_recorded_histories_carry_no_host_data() -> None:
@@ -30,4 +32,4 @@
 @pytest.mark.parametrize("path", HISTORIES, ids=lambda p: p.stem)
 async def test_a_golden_history_replays(path: Path) -> None:
     history = WorkflowHistory.from_json(path.stem, await asyncio.to_thread(path.read_text))
-    await Replayer(workflows=[RunGraph]).replay_workflow(history)
+    await Replayer(workflows=[RunGraph, LoopBatch]).replay_workflow(history)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/replay`
Expected: 1 failed, 9 passed. `test_every_scenario_is_recorded_for_this_build` fails with "run `uv run python -m
tests.engine.replay.record`": the abi1 directory lacks the six new scenarios. The 8 abi1 histories still replay.

- [ ] **Step 3: Bump the ABI and record**

In `backend/src/dewpoint/engine/runtime/build.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/build.py b/backend/src/dewpoint/engine/runtime/build.py
--- a/backend/src/dewpoint/engine/runtime/build.py
+++ b/backend/src/dewpoint/engine/runtime/build.py
@@ -4,7 +4,7 @@
 ENGINE_ABI increments on any change that can alter `RunGraph`'s command sequence; its golden histories live in
 `tests/engine/replay/<build id>/`. A change that leaves it alone must still replay that directory."""

-ENGINE_ABI = 1
+ENGINE_ABI = 2  # 2a-3b: loop batches, sub-flows, the failure handler and continue-as-new


 def build_id(version: str) -> str:
```

Run: `cd backend && uv run python -m tests.engine.replay.record`
Expected: `dewpoint-0.1.0+abi2: recorded batches, branches, continue_as_new, deadline, drain, errors, failed,
failure_handler, grants, loops, simulate, stop, subflows, variables_and_timers`.

The new directory holds about 37 files, about 1.8 MB in all:

| Scenario | Files |
|---|---|
| `batches` | 3 |
| `subflows` | 3 |
| `failure_handler` | 2 |
| `grants` | 2 |
| `continue_as_new` | 6 or 7 |
| `drain` | about 12 |
| each 2a-3a scenario | 1 |

The number of continued runs depends on how activity completions fall into workflow tasks, which varies between
recordings. Planning saw 36 and 37 files. Every recording replays.

- [ ] **Step 4: Run the replays**

Run: `cd backend && uv run pytest -q tests/engine/replay`
Expected: every test passes: one per history file, plus 2 (38 passed with planning's 36 files).

Check that the replay gate bites. Make a batch's workflow id differ from what was recorded:

```bash
sed -i.bak 's|/batch:{b.start}"|/batch-{b.start}"|' src/dewpoint/engine/runtime/execution.py \
  && uv run pytest -q tests/engine/replay; mv src/dewpoint/engine/runtime/execution.py.bak src/dewpoint/engine/runtime/execution.py
```

Expected: `test_a_golden_history_replays[batches]` and `[drain]` fail with `[TMPRL1100] Nondeterminism error: Child
workflow id of scheduled event … does not match`; the rest pass. Then `git diff src` is empty.

- [ ] **Step 5: The runs guide**

In `docs/operations/runs.md`:

```diff
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -13,8 +13,8 @@

 ## The worker

-`dewpoint worker` polls the `dewpoint-engine` task queue: `RunGraph`, the version loader, the projection, and one
-activity per installed plugin node type. It needs:
+`dewpoint worker` polls the `dewpoint-engine` task queue: the `RunGraph` and `LoopBatch` workflows, the version
+loader, the projection, and one activity per installed plugin node type. It needs:

 - `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_worker` role. That role reads versions and writes `runs` and
   `run_steps`, inside the run's tenant only (row-level security).
@@ -58,10 +58,42 @@

 ## Reading runs

-`GET /api/v1/t/{tenant}/runs` lists runs, newest first (`workflow_id`, `before` and `limit` filter and page them).
-`GET /api/v1/t/{tenant}/runs/{run_id}` returns one run with its steps: one row per step, loop iteration and attempt.
-The `iteration_key` is the loop step's key and the item's index, like `each_ap:3`, or `outer:1/inner:4` when nested.
-Both need the `run.view` permission.
+`GET /api/v1/t/{tenant}/runs` lists top-level runs, newest first (`workflow_id`, `before` and `limit` filter and page
+them). `GET /api/v1/t/{tenant}/runs/{run_id}` returns one run with its steps (one row per step, loop iteration and
+attempt) and its `children`: the sub-runs it started. The `iteration_key` is the loop step's key and the item's index,
+like `each_ap:3`, or `outer:1/inner:4` when nested. Both need the `run.view` permission.
+
+Every run has a `kind`. A sub-flow's run (`subflow`) and a failure handler's (`failure_handler`) are runs of their
+own, with their own steps, and point at the run that started them (`parent_run_id`, and for a sub-flow the step and
+iteration that ran it). Their own id opens them like any other run. A sub-run's row appears as soon as it starts,
+before its version loads, so a sub-run that ends right away still shows, with its end. A cancelled sub-run says
+`cancelled` here, but Temporal shows its workflow as completed: it returns what it used to its parent instead of
+ending as cancelled.
+
+## Sub-flows, failure handlers and large loops
+
+- **A `run_workflow` step** runs the workflow version it was pinned to at publish, as a child run. The child's outputs
+  are the step's output; its failure fails the step, with the child's error code and message, and the step's own
+  `on_error` applies. A sub-flow shares its parent's deadline, and nests at most 5 deep.
+- **A workflow's failure handler**, when it has one, runs once when a run of it fails or passes its deadline (not when
+  it's cancelled), as a child run whose trigger is `{run_id, workflow_id, version_id, error: {code, message}}`. It
+  gets its own deadline. The run's end is decided when it fails, but the run shows `running` until its handler has
+  finished; then its end is recorded, counting the handler's iterations. The handler's end doesn't change the
+  run's, and neither does a cancel while it runs: that cancels the handler. A failure handler's own failure runs no
+  handler.
+- **A loop over more than 100 items** runs in batches of 100, each a child workflow, one batch at a time; inside a
+  batch, the items run with the loop's own concurrency. Its iterations' rows, keys and results are the same as if
+  they had run inline, and its `on_item_error` works across batches.
+- **One budget per run.** The 100,000 loop iterations and filter items a run may use are shared by everything it
+  starts: its batches, its sub-flows (and theirs), and its failure handler. A child that needs more asks its parent;
+  a request waits while another child may still give budget back, and is refused only when nothing is left anywhere.
+
+## Long runs
+
+A run whose Temporal history passes 2,000 events carries on as a new Temporal execution (continue-as-new) at the next
+point where no activity and no child is outstanding: nothing is cancelled or repeated, and a timer keeps its wake
+time. Past 4,000 events, or when Temporal suggests it, the run drains: it starts nothing new, waits for what's
+outstanding, then continues. The run keeps its id, its rows and its budget; only Temporal's history starts afresh.

 ## What the projection shows

@@ -101,8 +133,8 @@

 Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation`, `unexpected_error`,
 `evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`, `item_cap_exceeded`,
-`iteration_cap_exceeded`, `not_supported` and `node_type_unavailable` (the registry lists the node type, but no worker
-of this build runs it: install its plugin on the workers).
+`iteration_cap_exceeded` and `node_type_unavailable` (the registry lists the node type, but no worker of this build
+runs it: install its plugin on the workers). A sub-flow step fails with its sub-flow's code.

 ## Attempts and retries

@@ -120,10 +152,11 @@

 ## Limits in this build

-- At most 100 steps run at once per run.
-- Loops over more than 100 items, and `run_workflow` sub-flows, fail their step with `not_supported`: loop batches and
-  sub-flows arrive with plan 2a-3b, as do continue-as-new and the workflow failure handler.
-- A run counts at most 100,000 loop iterations and filter items (`iteration_cap_exceeded`).
+- At most 100 steps, batches and sub-flows run at once per run (and per child).
+- A run counts at most 100,000 loop iterations and filter items, its children's included (`iteration_cap_exceeded`).
+- A batch's or a sub-flow's input, and a run's continue-as-new snapshot, travel through Temporal, whose payloads are
+  limited to 2 MiB: a loop body that reads very large outside values, or a very large loop, can pass it until 2b's
+  claim check.
 - `flow.delay` waits 0 to 30 days, and `wait_until` takes instants from year 1 to 9999 in UTC. A value outside that,
   resolved at run time, fails the step with `type_mismatch`.

```

- [ ] **Step 6: The whole suite, checks and commit**

Run: `cd backend && uv run pytest -q`
Expected: every test passes, with 8 skipped (the Linux-only evaluator tests). Planning's prototype gave 994
passed.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine \
  && git add src/dewpoint/engine/runtime/build.py tests/engine/replay ../docs/operations/runs.md \
  && git commit -m "test(engine): ENGINE_ABI 2 and golden histories of every execution; the runs guide covers scale" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**Checkpoint 3.** Continue-as-new, the golden histories and the docs are in. Stop for the owner's review, then the
whole-branch review.

---

## Handoff to 2a-3c and 2b

**2a-3c (deployment and gates):**
- **Worker Versioning.**
  - `RunGraph` and `LoopBatch` both become `PINNED`.
  - Children start on `dewpoint-engine`, so they inherit the parent's version.
  - Continue-as-new stays on the same queue, without upgrade-on-continue-as-new.
- **The two-build test.** Its N-1 runs need child sub-flows, loop batches, plugin activities and continue-as-new.
  This plan's `batches`, `subflows` and `drain` scenarios build such graphs. The test's history check must follow
  each run's children and continued runs; `record.executions` already does.
- **The CI replay gate** replays each build's directory against its own build. From abi2 on, a directory holds every
  execution of a scenario (`<name>--<n>.json`).
- **What only a real server can test:**
  - `is_continue_as_new_suggested`, which the test server never sets (go/no-go 4);
  - a terminated child, which the test server never reports to its parent (go/no-go 11).

  The Compose `temporal` service can.
- **Inline CEL.** The yield accumulator isn't in the snapshot, because it resets every workflow task. Keep it that
  way when local CEL arrives.

**2b:**
- **The claim check** must cover a batch's input (items and outer results), a sub-flow's input and a continue-as-new
  snapshot. Until then, each is a Temporal payload limited to 2 MiB (decision 21).
- **Payload validation** should cover a sub-flow's input against the sub-flow's input schema, as for any trigger.
  2a validates neither.
- **Terminated runs.** A terminated sub-run's row stays `running`, as a terminated root run's does. Retention or a
  reconciler should close them.

**Open for the owner:**
- 2a-3a's deferred minors M3–M6 remain unscheduled; M7 (pruning) is done here (decision 13).
- A timing flake on `main`: `tests/core/audit/test_anchor.py` (`test_verification_fails_closed`,
  `test_anchor_freshness_flags_unanchored_rows`) fails about one run in three with `max_lag=timedelta(0)`. It's
  outside this plan, and flagged for a separate fix.
- A test-order dependence from 2a-3a: running `test_run_graph_policies.py` before `test_run_graph.py` hangs
  `test_timers_are_durable_and_the_deadline_ends_the_run`. The suite's default order is fine.

## Self-review: spec coverage

| Spec | Requirement | Where |
|---|---|---|
| §6 | loops ≤ 100 items inline; more run as child workflows in batches of 100 within the loop's concurrency | Tasks 2, 5 (decisions 3, 4) |
| §6 | sub-flows: a child pinned to `subflow_version_id`, depth ≤ 5, sharing the deadline | Tasks 3, 5, 6 (decision 7) |
| §6 | the workflow failure handler runs once with the error summary: for `failed` and `deadline_exceeded`, once the end is decided; its iterations count, and a cancel during it doesn't change the end | Tasks 3, 5 (decision 8) |
| §4.5 | a non-terminal run holds its closure's CEL profiles, the failure handler's included, until the handler's own row has ended | Task 5 (decision 8) |
| §8 | a sub-run's row exists before anything can end it | Task 5 (decision 9) |
| §6 | at most 100 activities and child workflows outstanding per execution, and one projection beside them | Task 5 (decision 2) |
| §6 | one iteration counter per logical run, carried through continue-as-new | Tasks 1, 2, 7 (decisions 10, 16) |
| §6 | initial grants: a batch's item count, 1,000 for a sub-flow; more on demand by signal, in chunks of 1,000, in history order | Tasks 1, 5 (decisions 10, 11) |
| §6 | waiting, not refusing; refused only at the exact cap, with `iteration_cap_exceeded` | Tasks 1, 2, 5 (decisions 10, 12) |
| §6 | settlement: used debited, the rest released; a child that never reports is debited its whole grant | Tasks 1, 5 (decisions 4, 10, 19) |
| §6 | continue-as-new only at a quiescent checkpoint; never cancels, abandons or restarts work | Task 7 (decisions 14, 15) |
| §6 | opportunistic checkpoint past 2,000 events; drain from 4,000 or when suggested; drain still answers grants | Task 7 (decision 14) |
| §6 | timers carry their wake times; the snapshot's contents | Tasks 2, 7 (decisions 15, 16) |
| §6 | threshold tests: drain with batches, a sub-flow, activities and a timer outstanding | Task 7 |
| §6 | pinning across continue-as-new | 2a-3c (Worker Versioning); children and continued runs stay on `dewpoint-engine` |
| §7 | golden histories cover batched loops, sub-flows, every error policy, continue-as-new | Task 8 (decision 20) |
| §7 | `engine_abi` increments when the command sequence can change | Task 8 |
| §8 | sub-runs in `runs`; the read API | Tasks 4, 6 (decision 9) |
| §8 | `not_supported` removed from the run error codes | Task 5 |
| §10 | interpreter tests: batching, sub-flows, continue-as-new | Tasks 5, 7 |
| §10 | iteration counter: one cap across inline loops, batches, sub-flows and continue-as-new; no premature rejection; waits; settlement of failed and terminated children; no fresh cap after continue-as-new | Tasks 1, 2, 5, 7 (terminated: through a child that fails as a workflow, Review Focus 3) |
| §10 | the measured headroom test: the cap saturated when draining begins, with retries, heartbeats and grant traffic while it drains; events and bytes recorded and bounded | Task 7 (decision 17) |
| §10 | grants in drain mode | Task 7 (the headroom test's sub-flows ask while the run drains) |
| 2a-3a handoff | prune settled scopes; re-arm the deadline from the snapshot; drain stops starting units; carry secrets | Tasks 2, 7 (decisions 13, 15, 16) |
| 2a-3a handoff | the queued rows, and a plugin step between attempts | Task 7: rows are flushed before continuing; a step in backoff is outstanding (decision 14) |

Placeholder scan: every code step shows its code, and every command its expected output. The one value that varies
between runs, the headroom measurement, is printed and noted in the ledger. Type consistency: the names in each
Interfaces block match the code shown. The plan's code is the prototype's code, stage by stage, and replaying the
plan onto `main` reproduces the prototype exactly.
