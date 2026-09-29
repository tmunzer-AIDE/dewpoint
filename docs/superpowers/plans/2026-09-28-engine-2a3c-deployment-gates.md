# Engine 2a-3c: Deployment and Gates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the engine build by build, and turn local CEL on:
- each build is a pinned version of one Temporal Worker Deployment, which an operator promotes, and runs finish on
  the build they started on;
- Compose runs Temporal's dev server and the engine worker;
- CI replays this ABI's golden histories and never lets a recorded one change;
- a version runs only on a build of its engine ABI, so a new ABI means publishing each workflow again;
- CEL gates 4 and 7b pass (7b on Linux, in CI), then `LOCAL_CEL_PROFILE` is set, with `ENGINE_ABI` 3.

**Architecture:**
- **The yield budget belongs to the workflow task.** It's keyed on the history length, charges what each binding
  converts, and all units share one timer. That's what brings gate 7b under its 1 s target.
- **Worker Versioning.** `dewpoint.apps.worker.deployment` holds the deployment's name, this build's version, and
  the two calls an operator needs: make a build current, and describe the versions. `RunGraph` and `LoopBatch` are
  `PINNED`, and children inherit their parent's version. `dewpoint deployment` wraps both calls.
- **A real server for tests.** Tests that need Worker Versioning, a terminated child, or Temporal's continue-as-new
  suggestion run on Temporal's CLI dev server (`WorkflowEnvironment.start_local()`). Everything else stays on the
  time-skipping server.
- **Compose** gains `temporal` (the dev server, with SQLite on a volume) and `worker`, which promotes its own build
  because Compose runs one build at a time.
- **The replay gate** has two halves: the suite replays every history of this ABI, and CI checks that no recorded
  history changed.
- **A version and its build's ABI.** Admission refuses a version (or one whose sub-flows or failure handler are) of
  another engine ABI than the deployment's current build, which it asks Temporal for. Publishing refuses to pin one,
  and the version loader refuses one that raced a promotion. Runs already pinned to an older build finish there.
- **The deferred minors** of 2a-3a (M3–M6) and 2a-3b (M1–M8) are fixed, each test-first.

**Tech Stack:** Python 3.12 and `temporalio==1.33.0`, already locked. This plan uses:
- Worker Deployments and `VersioningBehavior.PINNED`;
- the raw `SetWorkerDeploymentCurrentVersion` and `DescribeWorkerDeployment` calls;
- Temporal's CLI dev server 1.9.1 (server 1.32.0), which the SDK downloads;
- the `temporalio/temporal:1.9.1` image for Compose.

It also uses SQLAlchemy 2 async on PostgreSQL 16, FastAPI, Typer, and pytest. There's no new dependency.

**Spec:** `docs/superpowers/specs/2026-09-25-engine-core-design.md`, revision 5.6:
- §5.6: workflow-task time;
- §5.9: gates 4 and 7, and the rollout of local CEL;
- §6: terminated children, the budget's minors, continue-as-new's minors;
- §7: Worker Versioning, promoting a build and the engine ABI of versions, the two-build test, Compose, golden
  histories and the replay gate;
- §8: run error codes, refused rows, and the runs list.

Revision 5.6 records the decisions below. It lands in the same docs-only PR as this plan, so the spec and the plan
agree before implementation starts.

**Previous plan:** `docs/superpowers/plans/2026-09-27-engine-2a3b-scale.md` (merged, PR #12, `ddfae57`). Its
"Handoff to 2a-3c" section lists what this plan consumes. This is the last of 2a-3's three plans.

## How this plan was made

1. **Go/no-go experiments ran first** (next section), on the locked temporalio 1.33.0, its time-skipping server, and
   the dev server that `start_local()` downloads.
2. **Every task was prototyped** in a scratch copy of the repository at `main` (`ddfae57`) until it passed its tests,
   `ruff`, `ruff format`, `mypy --strict` (135 source files) and `lint-imports` (10 contracts). The
   prototype's full suite gives 1,070 passed and 8 skipped, against `main`'s 1,006 passed. The 8 skipped are the Linux-only
   evaluator tests.
3. **The code blocks below are those files, verbatim.** Diffs to existing files were generated from the prototype.
4. **Each task was staged and checked on its own.** Stage *N* is `main` plus Tasks 1..*N*.
   - Every stage passed the static checks and the **whole** suite: 1,023, 1,026, 1,031, 1,032, 1,037, 1,038, 1,042, 1,046, 1,054, 1,063 and 1,070 passed, each with 8 skipped.
   - Each task's own `Run:` commands were run as written, and their output matched each `Expected:` line.
   - Each task's first run was checked too: every task's tests fail as its "watch them fail" step says. Tasks 2
     and 4 add tests of behaviour an earlier task (or `main`) already has, so their step shows how the test fails
     when that behaviour is removed. Planning ran those two steps, and Task 11's bite check, as written.
   - Three edits came after the stage suites. The stages were rebuilt with each, and the static checks and the
     affected `Run:` commands ran again on the rebuilt stages:
     - the runs guide's `terminated` row (Task 5) and a docstring in `deployment.py` (Task 3);
     - in the second round, one assertion of `test_half_a_cursor_is_refused` split in two (Task 9), so that its
       first run fails on the status code. `test_runs_api.py` ran again on stages 9–11.
   - Stages 1–8 are byte for byte the same in all three rounds, and stage 9 in the last two. The second round
     re-ran stages 9–11 in full, and the third stages 10 and 11.
   - Applying this plan's blocks and diffs to `main`, in order, reproduces the prototype exactly (0 mismatches).
5. **Staging reshaped the tasks.** The owner approved 11 tasks. Gate 7b fails on `main`, so it became Task 1's
   failing test, beside the yield fix it needs, which made 10. The owner's review then added Task 10 (next item).
   The checkpoints fall after Tasks 2, 7 and 11.
6. **Planning found one defect that it reports instead of fixing.** A failure handler cancelled in the activation
   that creates it is debited its whole grant, although it never ran. No test server can reach that window on
   purpose, so it's in the handoff.
7. **Compose's `temporal` service ran on its own** (healthy, the Web UI answering, and its state surviving a
   restart). The full stack's `worker` container runs only in CI: the app image's base images are approved for the
   evaluator only.
8. **The owner's first review (2026-09-28) found a blocker and two gaps**, each now fixed test-first:
   - **ABI-2 versions after promotion.** Nothing checked a version's stored `engine_abi`, so after the ABI-3 build
     was promoted, an active ABI-2 version would have started on it, with its sub-flows and failure handler. Task 10
     adds the owner's rule: such a start is refused until the workflow is published again, children first, and
     runs already pinned to the old build finish there (decision 16). A dev-server test covers the promotion.
   - **Half a runs cursor.** `before_id` without `before` was ignored, and `before` alone kept the same-instant skip
     that M5 fixes. The cursor is now the pair, and half of it is refused (decision 14, Task 9).
   - **Gate 7b on Linux.** Linux is authoritative, but planning's evidence is macOS only. A passing Linux run of
     gate 7b in CI is now a prerequisite of Task 11 (decision 15).

   Re-recording the abi3 histories with Task 10's loader showed that the `continue_as_new` scenario's number of
   continued runs varies between recordings (6 or 7). Task 11 says so.
9. **The owner's second review (2026-09-28) found a rollout gap in Task 10.** Admission compared versions with the
   admitting process's own ABI. In an overlapping rollout, an old process could then admit an old version after the
   promotion, whose run failed in the loader, and a new process could admit a new version before it. Admission now
   compares with the deployment's current build, read from Temporal at the start (decision 16), and the loader
   stays the backstop for a promotion that races a start. A dev-server test with the database covers both
   directions of the overlap.
   - Activation and enabling no longer check the ABI: the first revision checked them against the process's ABI,
     the same flaw.
   - Writing that test found a race in the first revision's promotion test: a run is pinned only once its first
     workflow task completes, and the test promoted right after starting it. It now waits for that task.
   - `start_run` now asks Temporal for the current build, which the time-skipping server can't answer. The stage suite
     found the two test files that start runs through admission on it, `test_worker_db.py` and `test_dev_run.py`.
     They stand in for the answer with one shared fixture.

Not run during planning: CI, so gate 7b hasn't run on Linux yet.

## During execution

Execution's second checkpoint (2026-09-29) changed Tasks 1, 2 and 7 after they ran. The task sections below show
their code as first planned; these commits carry the changes:
- **CI's CEL gate job** ran `tests/engine/cel` first, where Task 2's gate 4 starts a Temporal worker, before the
  evaluator's fork tests, which refuse to run beside its threads. The job now runs `tests/apps/cel_evaluator` first
  (`f2e6c14`).
- **The replay gate's base** (Task 7) was a push's previous commit, so a history rewritten by an earlier push of a
  branch passed once any later commit followed. CI now compares a pull request with its base, a push to `main` with
  the commit before it, and any other push with its merge base with `main` (`gate.base_for`, `5aa1914`; decision
  12).
- **Gate 7b on Linux** (Task 1) took three loads past 1 s, up to 1.12 s, each in a run's first workflow task, which
  also loads and compiles the version. The owner chose both fixes (`7d6ee2a`; decisions 1 to 3): an execution's first
  task gets a tenth of each threshold (`STARTUP_SHARE`), and the thresholds are a third lower. Task 11's prerequisite
  is a Linux `cel-gates` run of this code with every load at or under 1 s.

## Go/no-go: deployment and gates (run 2026-09-28)

| # | Question | Result |
|---|---|---|
| 1 | Does a pinned run stay on its build when another becomes current? | **Yes, on the dev server.** A run started on b1 stays on b1 after b2 becomes current: every workflow task (`WorkflowTaskCompleted.deployment_version`), every activity (by worker identity: activity events name no version), every child and every continued run, with `versioning_behavior` PINNED. A run started after lands on b2, and b1 then reports `draining`. The time-skipping server refuses Worker Versioning ("not yet supported in test server"). Making a version current can fail until one of its workers has polled, so the call retries. |
| 2 | Does CEL replay identically across processes, in the sandbox? | **Yes, with the CEL modules passed through**, as `RunGraph` does. Importing them in the sandbox fails: the C++ extension registers its types once ("type _InternalArena is already registered"). The corpus replays in 5 processes with different hash seeds. A comprehension over a map doesn't: its order is the process's own. Publish refuses those (`cel.unproven_list`), so gate 4's corpus is what publish accepts, and the map comprehension is its bite check. |
| 3 | Does every workflow task inside `RunGraph` stay under 1 s of CPU? | **No, not as it was.** Units that waited for the yield timer each started on a fresh budget, and `_drive` reset the budget after every wait. The worst task took 1.83 s (regular expressions), 1.51 s (conversions) and 1.34 s (equality), on macOS. Binding wasn't charged either: a cheap expression over values at the caps took about 77 ms per evaluation, up to 1.44 s per task. Decisions 1 and 2 fix both, and the worst task now takes 0.44 s. |
| 4 | Does the dev server reach what the test server can't? | **Yes.** A terminated child reaches its parent as a `ChildWorkflowError` caused by `TerminatedError`. With `limit.historyCount.suggestContinueAsNew=100`, `is_continue_as_new_suggested()` is true at 103 events. |
| 5 | How fast does a version report `drained`? | Within about a second, with the dev server's drainage checks set to 1 s. Temporal's default checks every 3 minutes. |
| 6 | Can Compose promote its build with a one-shot service? | **No.** `docker compose up --wait` fails (exit 1) when a one-shot service exits, even with 0, unless another service depends on it with `service_completed_successfully`. So the worker promotes its own build, behind a setting (decision 11). |
| 7 | Does `temporalio/temporal:1.9.1` run read-only, with its state on a volume? | **Yes,** with the volume at `/home/temporal`: the image's user (uid 1000) owns its home. `temporal operator cluster health` works as the health check. |

**Verdict: go,** with the yield fix.

## Decisions (recorded in spec revision 5.6)

The owner chose, on 2026-09-28:
- the dev server for the versioning tests and in Compose (decisions 7, 11);
- the replay gate (decision 12);
- the yield fix (decisions 1, 2);
- the extras: the real-server tests and the deferred minors (decisions 9, 10, 13, 14).

The owner's first review of this plan (2026-09-28) added decision 16, a version runs only on a build of its ABI,
with its rule: a start is refused until the workflow is published again. It also made the runs cursor a pair
(decision 14) and gate 7b's Linux result a prerequisite of local CEL (decisions 3, 15). The second review made
admission compare with the deployment's current build (decision 16). The others follow the spec closely.

### Workflow-task time (Task 1)

1. **One budget per workflow task.** 2a-3a's `YieldBudget` reset after any await. That let several units that
   waited for the yield timer each start on a fresh budget in the same workflow task, and `_drive` reset it after
   every wait, which can return in the middle of an activation. Inside `RunGraph`, a loop of 10 regular-expression
   evaluations at a time took 1.83 s of CPU in one workflow task (go/no-go 3), against a 1 s target. So:
   - The budget is keyed on `workflow.info().get_current_history_length()`. The length changes only between
     workflow tasks, and it's the same in a replay, so the budget is too.
   - Every unit calls `_yield_point` before it binds a view or evaluates locally. When the budget is spent, the
     units share one 1 ms timer (`asyncio.shield`, so a cancelled waiter never cancels it for the others), and
     each checks again once it fires.
   - A filter's items are evaluated one by one, each checked on its own. 2a-3a checked once for the whole filter.
   - `_drive` no longer resets anything.
2. **Binding is charged.** A cheap expression over the largest inputs (`size(trigger.c1) + size(trigger.c2) >= 0`
   over values at the caps) costs about 77 ms per evaluation to bind, measure and convert. Its stored bounds are
   tiny, so nothing charged it. `Measure.nodes` counts every value a binding set holds. `_cel_task` binds each view
   under the budget and charges its nodes, whether the expression then runs locally or in `cel.evaluate`. A
   workflow task also yields at 100,000 bound values (`YIELD_NODES`, new; 65,000 since checkpoint 2).
   - Cost: a run that binds more than 100,000 values in one task gains a timer. That changes its command sequence,
     so it needs a new `ENGINE_ABI`. Task 11 bumps it for local CEL, and no build ships in between.
3. **Gate 7b measures what a worker pays.** Every workflow activation runs through a `ThreadPoolExecutor` subclass
   passed as `workflow_task_executor`, which records its `time.thread_time()`. Each load runs inside `RunGraph`: a
   loop of 20 iterations, 10 at a time, local CEL on. The loads are gate 7's worst cases, each adversarial template
   at the heaviest form that still publishes `local`, and the binding load. No activation may pass 1 s. The CI job
   `cel-gates` runs it on Linux, which is authoritative, and keeps `task_cost.json`. Planning measured the worst
   task at 0.44 s (the regular-expression load, macOS), the run's first task included. That's evidence for the
   plan, not the gate: the in-process gate ran about twice as slow on Linux, so Task 11 waits for CI's Linux result
   (decision 15).
   - Execution's checkpoint 2: CI's first Linux run took conversion, equality and binding past 1 s (1.12, 1.11 and
     1.02 s), each in a run's first workflow task, which also starts the run. So that task gets a tenth of each
     threshold (`STARTUP_SHARE`): a view's first binding and light evaluations still run in it, and a heavier
     evaluation waits for the next task. The thresholds are a third lower too: 13,000 iterations, 5.5 MiB,
     2,700,000 work units, 130 evaluations and 65,000 bound values. The worst task is now 0.22 s on macOS and
     0.46 s on Linux (CI's `cel-gates`, commit `7d6ee2a`).

### CEL gate 4 (Task 2)

4. **Gate 4 evaluates as `RunGraph` does.** A sandboxed workflow, `CelCorpus`, evaluates the corpus in-process and
   hands its digest to an activity (the digest is the activity's id, so a different result is a different command).
   The CEL modules are passed through the sandbox, as `RunGraph` does: the runtime is a C++ extension, and importing
   it a second time fails (go/no-go 2). The history is then replayed in 5 fresh processes, each with its own
   `PYTHONHASHSEED`.
   - The corpus is what publish accepts: gate 1's 71 cases that compile and iterate only proven lists, `sortedKeys`
     over maps built in either insertion order, and map results.
   - The bite check: a comprehension over a map computes its order per process, and its replay fails with
     `[TMPRL1100] Nondeterminism error: Activity id`. Publish refuses such expressions (`cel.unproven_list`), so the
     check shows that the gate catches a leak the corpus doesn't have.
   - The gate passes on `main` too. It pins existing behaviour before Task 11 turns local CEL on.

### Worker Versioning (Tasks 3, 4)

5. **One deployment, pinned.** Every engine worker serves its build's version of the Worker Deployment
   `dewpoint-engine`, with build ID `dewpoint-<version>+abi<ENGINE_ABI>` (2a-3a's `build_id`). `RunGraph` and
   `LoopBatch` are `PINNED`. Children start on `dewpoint-engine` and inherit their parent's version, and a
   continued run stays on it. The `cel.evaluate` workers aren't in the deployment: their queues are per profile
   (§5.7).
6. **An operator promotes a build.** New runs start on the deployment's current version. `dewpoint deployment
   set-current [--build-id B] [--wait S]` makes a build current. A version exists only once one of its workers has
   polled, so `set_current` retries Temporal's `NOT_FOUND` and `FAILED_PRECONDITION` for up to `--wait` seconds
   (default 60). `dewpoint deployment status` prints the current build and each version's status (`draining`,
   `drained`, ...). The rollout guide says to stop the old build's workers once it reports `drained`.
7. **The versioning tests run on Temporal's dev server.** The time-skipping server refuses Worker Versioning
   ("not yet supported in test server"). `WorkflowEnvironment.start_local()` downloads the Temporal CLI once
   (1.9.1, server 1.32.0; the owner approved it for local runs and CI). One dev server serves the session
   (`dev_env`), with drainage checks shortened to 1 s. Time runs for real on it, so these tests take about two minutes in all.
   - A workflow task records its version (`WorkflowTaskCompleted.deployment_version`), but an activity's events
     don't. So each build's engine worker gets an identity of its own, and tests read `ActivityTaskStarted.identity`.
8. **The two-build test.** Build N-1 starts a run with a slow activity, a sub-flow, a batched loop of 101 items with
   CEL, and a continue-as-new. Then build N starts, without `testkit.slow`, and becomes current. N-1's run finishes
   on N-1: every workflow task, activity, child and continued run. A new run lands on N. Each CEL task ran on the
   version's profile queue. N-1 then reports `drained`.

### A real server (Task 5)

9. **A terminated child.** The dev server reports a terminated child to its parent (go/no-go 4), which the test
   server never did. The child can't write its own end. So the parent writes it: `failed`, with the error code
   `terminated` (new) and the child's whole grant. It writes the start row too, if the child had none
   (`RunStart.of`), shielded like any end. It never writes over an end the child wrote first
   (`RunSummary.if_running`). This fixes 2a-3b's minor M4. A sub-flow's step fails with `terminated`, a batch's
   loop too, and a terminated failure handler leaves the run's decided end standing. The child's grant stays used.
10. **Temporal's suggestion.** A dev server with `limit.historyCount.suggestContinueAsNew=100` suggests
    continue-as-new at about 100 events, and the run drains and continues. The test starts a dev server of its own.

### Compose and the replay gate (Tasks 6, 7)

11. **Compose runs Temporal's dev server.** The `temporal` service is `temporalio/temporal:1.9.1` (the owner
    approved the pull): `server start-dev`, its state in SQLite on the `temporal-data` volume, mounted at the image
    user's home. It's read-only, with its capabilities dropped, and its Web UI is on `127.0.0.1:8233`. The `worker`
    service logs in as `dewpoint_worker_login`, and `initdb` creates it and `dewpoint_dispatch_login`.
    - Compose runs one build at a time. So its worker makes its own build current once it polls
      (`DEWPOINT_WORKER_SET_CURRENT=true`, off by default). A one-shot `set-current` service would break
      `docker compose up --wait`, which fails when a one-shot service exits, even with 0, unless another service
      depends on it.
12. **The replay gate: current and immutable.** The suite replays every history of this build's `ENGINE_ABI`
    (`*+abi<ENGINE_ABI>/*.json`), so a new version that keeps the ABI replays the previous version's histories. CI
    then checks the replay directory's changes since the base (`git diff --name-status --no-renames`):
    - a recorded history is never changed or removed (a rename is both);
    - new histories go only into this build's directory, so a new directory appears only with a new build ID.

    The recorder, the scenarios and the tests may change. The base (`gate.base_for`, execution's checkpoint 2): a
    pull request's base, `main`'s previous commit for a push to `main`, and for any other push its merge base with
    `main`, so a rewrite stays visible on every later push of its branch.

### The deferred minors (Tasks 8, 9)

13. **2a-3b's final review** (M4 is decision 9):
    - M1: a child whose parent refused its ask refused every later need too. Now it refuses only the needs that
      waited, and a later need asks again: budget may have come back.
    - M2: loops still waiting when a run ended kept their needs, which starved the failure handler's grant. The
      run's end now drops them (`Budget.drop_local`).
    - M3: a `LoopBatch` that failed with `internal_error` didn't flush its rows first. It does now.
    - M5: a sub-run's start row that the database refused for its data was retried forever, holding up the
      projection. It's logged and skipped, like any refused row.
    - M6: a run whose snapshot another build can't read reported 0 iterations. The continued run's input now
      carries the iterations used so far, outside the snapshot. Checkpoint 3 found the other ends before a restore
      still reported 0 (a version that doesn't load or compile, a cancel while it loads), so a sub-flow's parent
      released budget it had spent: every one reports them now (`860d332`).
    - M7: `test_the_cap_holds_across_children` asserted `<= 100` iterations. It asserts exactly 0: the filter's 150
      items are all or nothing, so none ran.
    - M8: a cancel while the run waited for its projection in flight, before continuing, cancelled that projection.
      The wait now lets it land (`_landed`), then ends the run `cancelled`.
14. **2a-3a's final review:**
    - M3: a cancelled attempt of an `ambiguous` node is `outcome_unknown`: its request may have been sent.
    - M4: `dewpoint dev run --input` with JSON that isn't an object hung. It's refused before anything starts
      (exit 2).
    - M5: `GET /runs` paged by start time alone, so runs that started in the same instant could be skipped. The
      cursor is now the pair (start time, id): `before` and `before_id`, given together. Half a cursor is refused
      with 422 `invalid_cursor`, since the time alone is the lossy mode this fixes and nothing calls the API with a
      cursor yet. The service takes the pair as one value.
    - M6: time-skipping tests waited for results without a bound. Every wait is bounded (the harness's
      `RESULT_TIMEOUT_S = 60`). The golden histories gain a cancelled run and `version_unusable` (Task 11). There's
      no `internal_error` scenario: only a bug causes it, and a history recorded through a bug doesn't replay
      against the code without it.

### Local CEL (Task 11)

15. **Local CEL is on.** With gates 1–7 passing, `LOCAL_CEL_PROFILE` becomes `cel-cpp-0.1.3/fn-1/cls-1`, the
    current profile, and `ENGINE_ABI` becomes 3: a run's commands change when an expression runs in the workflow.
    - Gate 7b must have passed on Linux first: Task 11 starts only with a passing `cel-gates` job on this branch
      (Task 1's code), and its `task_cost.json` in the ledger. Pushing is the owner's, so Task 11 stops to ask for
      it. If the job fails, the yield thresholds (spec §5.6) need the owner's ruling before local CEL goes on.
    - An expression publish classified `local`, whose values are within the caps, runs in the workflow. Everything
      else goes to `cel.evaluate` on the version's profile queue.
    - A filter over more than 1,000 items (`FILTER_INLINE`, new) goes to `cel.evaluate` in chunks, however cheap
      its predicate: its items would take many workflow tasks, each with a timer.
    - Tests that exercise the evaluator path use `EVALUATOR_ONLY` in the harness. It's an expression publish always
      sends to the evaluator: a named time zone.
    - New golden scenarios: `local_cel` (yield timers), `evaluator` (chunks), `cancelled` and `version_unusable`.

### A version and its build's ABI (Task 10)

16. **A version runs only on a build of its engine ABI** (the owner's rule). A run's commands depend on the build's
    ABI, and a version is stamped with the one it was published under. Starting a run is refused when the build it
    would start on can't run its version. Runs already pinned to the old build finish there.
    - **Admission compares with the deployment's current build**, where a new run starts, not with the admitting
      process's build (the owner's second review). `start_run` asks Temporal for the current build before its
      transaction, and reads the ABI from its ID. In a rollout's overlap, both builds' processes then give the same
      answer: before the promotion, the new ABI's versions are refused ("make a build of ABI 3 current first"); after
      it, the old ABI's ("publish the workflow again with a build of ABI 3"). With no Dewpoint build current, nothing
      is admitted. The check covers the version's whole closure: every sub-flow and failure handler it runs.
    - **Publishing** refuses a draft whose pinned workflows' active versions, closures included, are of another ABI
      than the one it's published for (`subflow.engine_abi`). So the order is children first, and a parent published
      again on its own never runs an older ABI's child.
    - **The loader** refuses a version of another ABI, for a promotion that races a start (between the admission and
      the run's first workflow task), and for pins made before the rule. The run fails with `version_unusable`
      before any step runs, saying what to do.
    - **Activation and enabling don't check.** They don't start runs, and they can't know which build will be current
      when one starts. The plan's first revision checked them against the process's own ABI, the same flaw the
      owner's second review found in admission.
    - Cost: after an ABI change, every active workflow must be published again, children first, and until then its
      runs are refused. The rollout guide says so. Starting a run takes one more call to Temporal. A rollback across
      an ABI change means publishing again with the old build. Builds before 2a-3c don't check at admission, so their
      starts after the promotion reach the loader.

## Global Constraints

- **Versions.**
  - Python ≥ 3.12, and `temporalio==1.33.0` as locked.
  - No new dependency, and no change to `pyproject.toml` or `uv.lock`.
- **Purity.** `dewpoint.engine` stays pure: no `dewpoint.core`, `dewpoint.apps`, `dewpoint.plugins`, SQLAlchemy,
  asyncpg, FastAPI or httpx. Only `engine/runtime/workflow.py` and `engine/runtime/execution.py` import
  `temporalio`. Worker Deployment code lives in `dewpoint.apps.worker.deployment`, outside the engine.
- **Workflow-code rules** (spec §6, and the `dewpoint.engine.runtime` import contract):
  - no `random`, `secrets`, `time`, `socket`, `subprocess`, `threading`, `os` or `structlog`;
  - time comes only from `workflow.now()`, and ids only from `workflow.uuid4()` or the run's own ids;
  - waits use `asyncio.sleep` (a durable timer), `workflow.wait` or `workflow.wait_condition`;
  - never iterate a set, and build every dict and list that reaches a command or the snapshot in a fixed order.
- **Limits.** Values are copied from spec §5.6 and §6; new constants are marked "new".
  - The yield thresholds per workflow task: 13,000 iterations, 5.5 MiB, 2,700,000 work units, 130 evaluations, and
    65,000 bound values (`YIELD_NODES`, new), and a tenth of each in an execution's first workflow task
    (`STARTUP_SHARE`, new). Execution's checkpoint 2 set them; the plan first had 20,000, 8 MiB, 4,000,000, 200 and
    100,000.
  - The CPU target per workflow task: 1 s (`TASK_CPU_TARGET_S`), against Temporal's 10 s workflow-task timeout.
  - A filter runs inline up to 1,000 items (`FILTER_INLINE`, new); larger ones go to `cel.evaluate` in chunks of
    1,000 binding sets.
  - `set_current` waits up to 60 s by default for a build's workers to poll; Compose's worker waits 120 s.
- **Names:**
  - the Worker Deployment `dewpoint-engine` (`DEPLOYMENT`), with build ID `dewpoint-<version>+abi<ENGINE_ABI>`;
  - the CLI group `dewpoint deployment`, with `set-current [--build-id] [--wait]` and `status`;
  - the setting `DEWPOINT_WORKER_SET_CURRENT` (`worker_set_current`, default off);
  - the run error code `terminated` (new); publish's diagnostic `subflow.engine_abi` (new); the runs API's 422
    `invalid_cursor` (new);
  - the Compose services `temporal` and `worker`, the volume `temporal-data`, and the database logins
    `dewpoint_worker_login` and `dewpoint_dispatch_login`.
- **What changes when:**
  - `ENGINE_ABI` stays 2 until Task 11, which makes it 3 with `LOCAL_CEL_PROFILE` and records the abi3 histories;
    Task 10's rule, that a version runs only on a build of its ABI, comes first;
  - Task 11 starts only once gate 7b has passed on Linux, in CI (decision 15);
  - the abi2 histories stay in the repo, unchanged, and every stage replays them until Task 11;
  - `CURRENT_CEL_PROFILE` stays `cel-cpp-0.1.3/fn-1/cls-1`.
- **Tests:**
  - `tests/engine/**` needs no database.
  - `tests/apps/worker/**` starts Temporal's time-skipping test server, except the tests that take `dev_env`, or
    start a dev server of their own: those run on Temporal's CLI dev server, which `start_local()` downloads once.
  - Tests that monkeypatch a module the sandbox imports on its own run with `UnsandboxedWorkflowRunner` (2a-3a's
    go/no-go 7). `workflow.py` passes `execution` through the sandbox, so the yield tests and gate 7b patch it
    (`LOCAL_CEL_PROFILE`, `YieldBudget`) and stay sandboxed.
  - Keep the suite's path order: the evaluator's fork tests must run before anything starts a Temporal worker, so
    no `pytest-randomly`.
- **Downloads and images** (the owner approved each):
  - the Temporal CLI dev server, which `WorkflowEnvironment.start_local()` downloads, locally and in CI;
  - `temporalio/temporal:1.9.1`, for Compose;
  - `postgres:16-alpine` and the evaluator's base images, as before. Nothing else.
- **Conventions:**
  - an SPDX header on every source file, and comments that explain why;
  - commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - run the checks and the commit in one `&&` chain;
  - never push, open a PR or enable auto-merge without the owner's word;
  - keep the branches `feat/foundations`, `spike/cel-evaluation`, `docs/engine-core-spec`, `feat/engine-2a1`,
    `docs/engine-2a2-plan`, `feat/engine-2a2`, `docs/engine-2a3a-plan`, `feat/engine-2a3a`,
    `docs/engine-2a3b-plan` and `feat/engine-2a3b`;
  - leave the untracked `spikes/` alone.
- **Checks** (from `backend/`):
  - `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`;
  - tests: `uv run pytest -q <paths>`. The whole suite needs Docker for Postgres.

## Review Focus

These are the inputs and conditions most likely to bite a person using this, beyond what the spec names. Each has a
test in the task that owns the code.

1. **Promoting a build right after starting its workers.** An operator runs `set-current` before any new worker has
   polled. Temporal refuses a version it doesn't know yet, so the command waits and retries until a worker polls,
   then promotes. It doesn't fail. (Task 3: `test_set_current_waits_for_the_builds_workers`)
2. **An operator terminates a sub-run** from the Web UI or the CLI: a sub-flow, a batch, or a failure handler. The
   parent's step or loop fails with `terminated`, the sub-run's row records its end, its grant stays used, and a
   terminated failure handler leaves the run's own end standing. (Task 5: the three `test_a_terminated_*` tests)
3. **A cheap expression over the largest inputs.** Each binding converts every value it binds, whatever the
   expression costs, so the workflow task yields on what it bound, whether the expression runs locally or in the
   evaluator. (Task 1: `test_binding_is_charged_when_the_evaluator_runs_the_expression`, and gate 7b's `binding`
   load)
4. **A filter over a large list.** Over 1,000 items, the predicate runs in `cel.evaluate` in chunks, even when
   publish classified it `local`, instead of taking workflow task after workflow task.
   (Task 11: `test_a_filter_over_more_than_a_thousand_items_goes_to_the_evaluator_in_chunks`)
5. **Runs that start in the same instant**, from a schedule or a burst of triggers. Paging `GET /runs` lists each
   exactly once. (Task 9: `test_the_runs_list_pages_past_runs_that_started_in_the_same_instant`)

## File structure

```
backend/src/dewpoint/engine/cel/bind.py         Measure.nodes: every value a binding set holds             Task 1
backend/src/dewpoint/engine/cel/route.py        YIELD_NODES; YieldBudget charges bindings                  Task 1
backend/src/dewpoint/engine/cel/profile.py      LOCAL_CEL_PROFILE = CURRENT_CEL_PROFILE                    Task 11
backend/src/dewpoint/engine/__init__.py         ENGINE_ABI = 3                                              Task 11
backend/src/dewpoint/engine/runtime/
  build.py         abi_of: the ABI a build ID names                                                          Task 10
  resolve.py       Bound, bind_view, cel_task over bound views, CelTask.run_one                             Task 1
  execution.py     the per-task yield budget (Task 1); terminated children (Task 5); M2, M8 (Task 8);
                   M3 (Task 9); a version that didn't load (Task 10); FILTER_INLINE (Task 11)                Tasks 1, 5, 8–11
  workflow.py      PINNED (Task 3); RunStart.of, a terminated handler's end (Task 5); M3, M6, M8 (Task 8);
                   the loader's message (Task 10)                                                            Tasks 3, 5, 8, 10
  activities.py    RunSummary.if_running, RunStart.of (Task 5); iterations in RunInput/BatchInput (Task 8);
                   VersionData.engine_abi (Task 10)                                                          Tasks 5, 8, 10
  budget.py, scheduler.py                       M1, M2                                                      Task 8
backend/src/dewpoint/apps/worker/deployment.py  the deployment: build, config, set_current, describe (Task 3);
                                                current_abi (Task 10)                                       Tasks 3 (new), 10
backend/src/dewpoint/apps/worker/main.py        the engine worker's deployment (Task 3); promote (Task 6);
                                                its ABI (Task 10)                                           Tasks 3, 6, 10
backend/src/dewpoint/apps/worker/activities.py  the loader refuses another ABI                              Task 10
backend/src/dewpoint/apps/worker/store.py       if_running (Task 5); M5 (Task 8); engine_abi (Task 10)      Tasks 5, 8, 10
backend/src/dewpoint/apps/workflow_ops.py       publish refuses to pin another ABI                          Task 10
backend/src/dewpoint/apps/runs.py               admission compares with the current build's ABI             Task 10
backend/src/dewpoint/apps/cli/main.py           `dewpoint deployment` (Task 3); M4 (Task 9)                Tasks 3, 9
backend/src/dewpoint/apps/api/routes/runs.py    the cursor pair                                             Task 9
backend/src/dewpoint/core/runs/service.py       finish_run(if_running) (Task 5); the runs cursor (Task 9)  Tasks 5, 9
backend/src/dewpoint/core/workflows/service.py  other_abi                                                   Task 10
backend/src/dewpoint/core/config.py             worker_set_current                                          Task 6
backend/tests/apps/          test_workflow_ops.py, test_runs.py (Task 10); api/test_runs_api.py (Task 9)
backend/tests/apps/worker/   test_run_graph_yield.py, test_gate_task_cost.py (Task 1); conftest.py (Tasks 3, 4, 10);
                             test_deployment.py (Tasks 3, 6); test_two_builds.py (Tasks 4, 10); test_real_server.py
                             (Task 5); test_run_graph_abi.py, test_admission_abi.py (Task 10);
                             test_dev_run.py (Task 10); test_run_graph_local_cel.py (Task 11);
                             test_worker_db.py (Tasks 8, 10, 11);
                             harness.py (Tasks 5, 9, 10, 11)
backend/tests/engine/cel/    gate_replay_workflow.py, test_gate_replay.py (Task 2); test_bind, test_route,
                             test_gate_cost (Task 1); test_profile (Task 11)
backend/tests/engine/replay/ gate.py, test_gate.py, test_replay.py (Task 7); scenarios.py, record.py and the
                             dewpoint-0.1.0+abi3/ histories (Task 11)
deploy/compose/              docker-compose.yml, initdb/10-roles.sh, .env.example                           Task 6
.github/workflows/ci.yml     gate 7b (Task 1); the e2e worker (Task 6); the replay gate (Task 7)            Tasks 1, 6, 7
docs/operations/             deployment.md (new), runs.md, README.md (Task 6); deployment.md, runs.md (Task 10);
                             runs.md, cel-evaluator.md (Task 11)
(spec revision 5.6 lands with this plan in the docs PR, before Task 1)
```

## Suggested checkpoints (the owner's milestone reviews)

1. **After Task 2:** the CEL gates. The per-task yield budget, with gate 7b passing, and gate 4 with its bite check.
   A push here gets CI's Linux gate 7b result, which Task 11 needs.
2. **After Task 7:** deployment. Worker Versioning with the `dewpoint deployment` commands, the two-build test, the
   real-server tests, Compose's `temporal` and `worker`, and the replay gate.
3. **After Task 11:** the deferred minors, the ABI rule, then local CEL with `ENGINE_ABI` 3 and its golden
   histories. Then the whole-branch review.

## Branching

As in 2a-3b:
1. This plan and spec revision 5.6 land in a docs-only PR from `main`, on the branch `docs/engine-2a3c-plan`.
2. After it merges, implementation starts on `feat/engine-2a3c` from the updated `main`.

---

### Task 1: One CEL budget per workflow task, binding charged, and gate 7b

Gate 7b runs each adversarial CEL load inside `RunGraph` and measures every workflow activation's CPU (decision 3).
On `main` four loads take more than the 1 s target in one workflow task, because the yield budget isn't the workflow task's (decision 1) and
binding costs nothing (decision 2). This task fixes both, and the gate passes.
- `Measure.nodes` counts the values a binding set holds.
- `YieldBudget` charges a bound view's nodes, and yields at 100,000 of them too.
- `resolve.bind_view` binds and measures one view. `cel_task` takes the bound views, and `CelTask.run_one`
  evaluates one binding set.
- `Execution._cel_task` binds view by view under the budget. `_evaluate` runs a local task's binding sets one by
  one. `_yield_point` keys the budget on the history length and shares one timer.

`LOCAL_CEL_PROFILE` is still `None`, so nothing runs locally in a real run until Task 11. The tests turn it on by
patching `execution.LOCAL_CEL_PROFILE`.

**Files:**
- Modify: `backend/src/dewpoint/engine/cel/bind.py`, `backend/src/dewpoint/engine/cel/route.py`
- Modify: `backend/src/dewpoint/engine/runtime/resolve.py`, `backend/src/dewpoint/engine/runtime/execution.py`
- Modify: `backend/tests/engine/cel/test_bind.py`, `backend/tests/engine/cel/test_route.py`,
  `backend/tests/engine/runtime/test_resolve.py`, `backend/tests/engine/cel/test_gate_cost.py`
- Create: `backend/tests/apps/worker/test_run_graph_yield.py`, `backend/tests/apps/worker/test_gate_task_cost.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: 2a-2's `bind`, `measure`, `route` and `ExpressionRecord`; 2a-3b's `Execution` and the harness
  (`MemoryStore`, `start`, `workers`, `in_process`, `CATALOG`, `TESTKIT`).
- Produces:
  - `Measure.nodes: int` (the last field);
  - `route.YIELD_NODES = 100_000`; `YieldBudget.nodes`, `must_yield(record: ExpressionRecord | None = None) -> bool`
    and `charge(record: ExpressionRecord | None = None, *, nodes: int = 0) -> None`;
  - `resolve.Bound(bindings: Mapping[str, Any], measured: Measure)`, `resolve.bind_view(record, view) -> Bound`,
    `resolve.cel_task(record, bound: Sequence[Bound], *, local_profile, version_profile) -> CelTask`, and
    `CelTask.run_one(bindings) -> evaluate.Outcome` (`run_local` is gone);
  - `Execution._cel_task(record, views) -> resolve.CelTask` and `Execution._yield_point(record | None)`;
  - `tests.engine.cel.test_gate_cost.BINDING`, the binding load.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/engine/cel/test_bind.py`, `measure` counts every value:

```diff
diff --git a/backend/tests/engine/cel/test_bind.py b/backend/tests/engine/cel/test_bind.py
--- a/backend/tests/engine/cel/test_bind.py
+++ b/backend/tests/engine/cel/test_bind.py
@@ -58,6 +58,12 @@
         bind.bind(r, view(vars={"x": bad}))


+def test_measure_counts_every_value_it_binds() -> None:
+    """What binding costs grows with the values converted, not their bytes: containers count as well as scalars."""
+    assert bind.measure({"a": [1, [2, 3]], "b": {"c": "x"}}).nodes == 7
+    assert bind.measure({"a": "x" * 10_000}).nodes == 1
+
+
 def test_measure_against_the_caps() -> None:
     m = bind.measure({"a": [1] * caps.LIST_LENGTH, "b": "x" * 10})
     assert m.within_caps and m.longest_list == caps.LIST_LENGTH and m.longest_string == 10
```

In `backend/tests/engine/cel/test_route.py`, a bound view is charged its nodes:

```diff
diff --git a/backend/tests/engine/cel/test_route.py b/backend/tests/engine/cel/test_route.py
--- a/backend/tests/engine/cel/test_route.py
+++ b/backend/tests/engine/cel/test_route.py
@@ -35,3 +35,15 @@
     budget.reset()
     budget.charge(small)
     assert budget.must_yield(big)
+
+
+def test_the_yield_budget_charges_the_values_each_view_binds() -> None:
+    """Binding a view converts every value it binds, a cost the stored bounds don't count: a cheap expression over
+    the largest inputs would otherwise bind them 200 times in one workflow task (spec §5.6)."""
+    cheap = replace(make_record("trigger.x == 1"), iterations=0, bytes=0, work=0)
+    budget = route.YieldBudget()
+    assert not budget.must_yield()  # the first binding of a task always runs, however large
+    budget.charge(nodes=route.YIELD_NODES - 1)
+    assert not budget.must_yield() and not budget.must_yield(cheap)
+    budget.charge(cheap, nodes=1)
+    assert budget.must_yield()  # the values bound reached the budget: the next view waits for the next task
```

In `backend/tests/engine/runtime/test_resolve.py`, views are bound one at a time:

```diff
diff --git a/backend/tests/engine/runtime/test_resolve.py b/backend/tests/engine/runtime/test_resolve.py
--- a/backend/tests/engine/runtime/test_resolve.py
+++ b/backend/tests/engine/runtime/test_resolve.py
@@ -106,19 +106,21 @@
     double, divide, count = (p.record(step, f"/fields/{f}") for f in ("y", "z", "n"))
     views = [scope_view(trigger={"x": 3}), scope_view(trigger={"x": 0})]

-    remote = resolve.cel_task(double, views, local_profile=None, version_profile=CURRENT_CEL_PROFILE)
+    remote = resolve.cel_task(
+        double, [resolve.bind_view(double, v) for v in views], local_profile=None, version_profile=CURRENT_CEL_PROFILE
+    )
     assert not remote.local
     assert remote.request(CURRENT_CEL_PROFILE)["bindings"] == [{"trigger": {"x": 3}}, {"trigger": {"x": 0}}]

-    local = resolve.cel_task(divide, views, local_profile=CURRENT_CEL_PROFILE, version_profile=CURRENT_CEL_PROFILE)
-    ok, failed = local.run_local()
+    bound = [resolve.bind_view(divide, v) for v in views]
+    assert [b.measured.nodes for b in bound] == [2, 2]  # each binding set: `trigger` and its `x`
+    local = resolve.cel_task(divide, bound, local_profile=CURRENT_CEL_PROFILE, version_profile=CURRENT_CEL_PROFILE)
+    ok, failed = (local.run_one(b) for b in local.bindings)
     assert local.local and resolve.outcome_value(ok) == 3
     with pytest.raises(ValueFailure) as e:
         resolve.outcome_value(failed)
     assert e.value.failure.code == "evaluation_error"

     with pytest.raises(ValueFailure) as bad:  # a typed list path (spec §5.3) is checked as it's bound
-        resolve.cel_task(
-            count, [scope_view(trigger={"x": 1, "names": "ap-1"})], local_profile=None, version_profile="p"
-        )
+        resolve.bind_view(count, scope_view(trigger={"x": 1, "names": "ap-1"}))
     assert bad.value.failure.code == "type_mismatch"
```

In `backend/tests/engine/cel/test_gate_cost.py`, gate 7 gains the binding load. Its `_task` helper now mirrors
`RunGraph`, binding each view under the budget:

```diff
diff --git a/backend/tests/engine/cel/test_gate_cost.py b/backend/tests/engine/cel/test_gate_cost.py
--- a/backend/tests/engine/cel/test_gate_cost.py
+++ b/backend/tests/engine/cel/test_gate_cost.py
@@ -69,6 +69,9 @@
     for name, template in ADVERSARIAL.items():
         heaviest = _heaviest_local(template, v)
         report["task"][name] = {"expr_chars": len(heaviest.expr), "work": heaviest.work, **_task([heaviest], v)}
+    binding = make_record(BINDING)
+    assert binding.mode == "local" and bind.measure(bind.bind(binding, v)).within_caps
+    report["task"]["binding"] = {"nodes": bind.measure(bind.bind(binding, v)).nodes, **_task([binding], v)}
     if directory := os.environ.get("DEWPOINT_CEL_GATE_RESULTS"):
         os.makedirs(directory, exist_ok=True)
         with open(os.path.join(directory, "cost.json"), "w") as f:
@@ -78,10 +81,16 @@


 def _task(records: list[Any], v: Any) -> dict[str, Any]:
-    """Evaluate back to back, cycling through `records`, until the yield policy demands a yield."""
+    """Bind and evaluate back to back, cycling through `records`, until the yield policy demands a yield: what
+    RunGraph does in one workflow task (execution.py, `_cel_task` and `_evaluate`)."""
     budget, cpu, done = route.YieldBudget(), time.process_time(), 0
-    while not budget.must_yield(r := records[done % len(records)]):
-        evaluate.evaluate_local(r, v)
+    while not budget.must_yield():
+        r = records[done % len(records)]
+        bindings = bind.bind(r, v)
+        budget.charge(nodes=bind.measure(bindings).nodes)
+        if budget.must_yield(r):
+            break
+        evaluate.run(evaluate.compiled(r.expr, r.declarations), bindings)
         budget.charge(r)
         done += 1
     return {"evaluations": done, "cpu_s": time.process_time() - cpu}
@@ -107,6 +116,10 @@
 }


+# Cheap by its stored bounds, but binding the most values the caps allow: the cost the budget charges by `nodes`.
+BINDING = "size(trigger.c1) + size(trigger.c2) >= 0"
+
+
 def _heaviest_local(template: Callable[[int], str], v: Any) -> Any:
     """The largest n that still classifies local: it maxes out the work bound (or the expression or pattern
     length). Its inputs are within the caps and it evaluates, so the load is real."""
```

Create `backend/tests/apps/worker/test_run_graph_yield.py`. A recording `YieldBudget` shows where each workflow
task yields:

```python
# SPDX-License-Identifier: Apache-2.0
"""The yield policy inside RunGraph (spec §5.6): one budget per workflow task, however many units share it. A view's
binding is charged as the values it binds, whether the expression then runs here or in `cel.evaluate`; a local
evaluation is charged its stored bounds. When the budget is spent, the work waits for a 1 ms durable timer."""

import asyncio
from collections import defaultdict
from typing import Any

import pytest
from temporalio import workflow
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.cel import route
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.engine.runtime import execution
from tests.apps.worker.harness import CATALOG, MemoryStore, start, workers
from tests.engine.cel.test_gate_cost import ADVERSARIAL, AT_CAPS
from tests.support.graphs import G, cel

S = {"type": "string"}
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "s": S,
        "needle": S,
        "xs": {"type": "array", "items": {"type": "integer"}},
        "c1": {"type": "array", "items": {"type": "array", "items": {"type": "integer"}}},
    },
    "required": ["s", "needle", "xs", "c1"],
}
TRIGGER = {"s": AT_CAPS["s"], "needle": AT_CAPS["needle"], "xs": list(range(450)), "c1": AT_CAPS["c1"]}
TASKS: dict[int, list[tuple[str, int]]] = defaultdict(list)  # history length -> ("bind", nodes) / ("eval", work)


class Recording(route.YieldBudget):
    """Records every charge under the workflow task it was made in (its history length). A replay makes the same
    charges again, for tasks already recorded: those aren't recorded twice."""

    def charge(self, record: Any = None, *, nodes: int = 0) -> None:
        if not workflow.unsafe.is_replaying():
            task = TASKS[workflow.info().get_current_history_length()]
            if nodes:
                task.append(("bind", nodes))
            if record is not None:
                task.append(("eval", record.work or 0))
        super().charge(record, nodes=nodes)


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> dict[int, list[tuple[str, int]]]:
    """The engine modules are passed through the sandbox, so this reaches RunGraph's budget too."""
    TASKS.clear()
    monkeypatch.setattr(execution, "YieldBudget", Recording)
    return TASKS


def local_cel(monkeypatch: pytest.MonkeyPatch) -> None:
    """What setting `LOCAL_CEL_PROFILE` does in a build (Task 11)."""
    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", CURRENT_CEL_PROFILE)


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


def heaviest_search() -> str:
    """The heaviest substring search that still publishes local: about half the work budget per evaluation."""
    best = ""
    for n in range(1, 60):
        g = graph().node("x", "flow.transform@1", {"fields": {"r": cel(ADVERSARIAL["search"](n))}})
        result = validate(g.build(), ValidationContext(catalog=CATALOG, subflows={}))
        if any(d.severity == "error" for d in result.diagnostics) or result.expressions[0].mode != "local":
            break
        best = ADVERSARIAL["search"](n)
    assert best
    return best


async def finished(env: WorkflowEnvironment, store: MemoryStore, g: G, *, cache: int = 1000) -> tuple[Any, Any]:
    async with workers(env.client, store, cache=cache):
        handle = await start(env.client, store, g, TRIGGER)
        return handle, await asyncio.wait_for(handle.result(), 120)


@pytest.mark.parametrize("cache", [1000, 0], ids=["cached", "replaying every task"])
async def test_concurrent_evaluations_share_one_budget_per_workflow_task(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, recorded: dict[int, list[tuple[str, int]]], cache: int
) -> None:
    """Ten iterations run at once, each evaluating about half the work budget: each workflow task evaluates two at
    most. Waiting units share one timer and check again once it fires. With no worker cache, every workflow task
    replays the run's history: the budget, keyed on the history length, decides the same way."""
    local_cel(monkeypatch)
    store = MemoryStore()
    g = graph(count=cel("size(steps.l.output.items)"))
    g.node("l", "flow.loop@1", {"items": list(range(20)), "concurrency": 10, "collect": cel("steps.x.output.r")})
    g.node("x", "flow.transform@1", {"fields": {"r": cel(heaviest_search())}}).edge("l", "x", "body")
    handle, result = await finished(env, store, g, cache=cache)
    assert (result.status, result.outputs) == ("succeeded", {"count": 20})
    assert {r.cel_mode for r in store.steps(handle.id) if r.node_key == "x"} == {"local"}
    evaluating = [[w for kind, w in t if kind == "eval"] for t in recorded.values()]
    evaluating = [works for works in evaluating if works]
    assert sum(len(works) for works in evaluating) >= 20 and len(evaluating) >= 10  # the budget split them
    assert all(len(works) == 1 or sum(works) <= route.YIELD_WORK for works in evaluating)


async def test_a_local_filter_evaluates_its_items_within_the_budget(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, recorded: dict[int, list[tuple[str, int]]]
) -> None:
    """A filter's 450 items are 450 evaluations: at most 200 in one workflow task (they used to run all at once)."""
    local_cel(monkeypatch)
    store = MemoryStore()
    g = graph(kept=cel("steps.f.output.count"))
    g.node("f", "flow.filter@1", {"items": cel("trigger.xs"), "predicate": cel("item % 3 == 0")})
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 150})
    assert [r.cel_mode for r in store.steps(handle.id) if r.node_key == "f"] == ["local"]
    counts = [sum(kind == "eval" for kind, _ in t) for t in recorded.values()]
    assert max(counts) <= route.YIELD_EVALUATIONS and sum(counts) >= 450


async def test_binding_is_charged_when_the_evaluator_runs_the_expression(
    env: WorkflowEnvironment, recorded: dict[int, list[tuple[str, int]]]
) -> None:
    """No local CEL: each of the filter's 20 views still binds `trigger.c1` (16,081 values) in the workflow. A
    workflow task binds up to the budget, and the next view waits for the next task."""
    store = MemoryStore()
    g = graph(kept=cel("steps.f.output.count"))
    g.node("f", "flow.filter@1", {"items": list(range(20)), "predicate": cel("size(trigger.c1) > item")})
    handle, result = await finished(env, store, g)
    assert (result.status, result.outputs) == ("succeeded", {"kept": 20})
    assert [r.cel_mode for r in store.steps(handle.id) if r.node_key == "f"] == ["activity"]
    binding = [[n for kind, n in t if kind == "bind" and n > 16_000] for t in recorded.values()]  # the 20 views
    binding = [nodes for nodes in binding if nodes]
    assert sum(len(nodes) for nodes in binding) == 20 and len(binding) == 3  # 7, 7 and 6: 6 fit, the 7th passes it
    assert all(sum(nodes[:-1]) < route.YIELD_NODES for nodes in binding)  # the last one may pass it: then it yields
```

Create `backend/tests/apps/worker/test_gate_task_cost.py`, gate 7b:

```python
# SPDX-License-Identifier: Apache-2.0
"""Gate 7b (spec §5.6, §5.9): the workflow-task half of gate 7. Each adversarial load of the in-process gate, at its
heaviest form that still publishes local, runs inside RunGraph: a loop of 20 iterations, 10 at a time, evaluating it
in-process. The worker's task executor measures the CPU of every workflow activation, and none may pass the 1 s
target, against Temporal's 10 s workflow-task timeout. Linux (the CEL gate job) is authoritative. Results go to
$DEWPOINT_CEL_GATE_RESULTS/task_cost.json when set, to tune the thresholds."""

import asyncio
import concurrent.futures
import json
import os
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from dewpoint.apps.worker.activities import cel_activity, engine_activities
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.engine.runtime import execution
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
from tests.apps.worker.harness import CATALOG, TESTKIT, MemoryStore, in_process, start
from tests.engine.cel.test_gate_cost import ADVERSARIAL, AT_CAPS, BINDING, TASK_CPU_TARGET_S, WORST
from tests.support.graphs import G, cel

S = {"type": "string"}
INTS = {"type": "array", "items": {"type": "integer"}}
SCHEMA: dict[str, Any] = {  # AT_CAPS, typed as publish sees it: every list a proven list
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {"type": "object", "properties": {"mac": S, "type": S}, "required": ["mac", "type"]},
        },
        "m": {"type": "object", "additionalProperties": {"type": "integer"}},
        "s": S,
        "needle": S,
        "texts": {"type": "array", "items": S},
        "c1": {"type": "array", "items": INTS},
        "c2": {"type": "array", "items": INTS},
        "dense": {"type": "object", "additionalProperties": INTS},
    },
    "required": ["events", "m", "s", "needle", "texts", "c1", "c2", "dense"],
}


class Timed(concurrent.futures.ThreadPoolExecutor):
    """Runs each workflow activation and records its CPU time: what one workflow task costs the worker."""

    def __init__(self) -> None:
        super().__init__(max_workers=4)
        self.cpu: list[float] = []

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> concurrent.futures.Future[Any]:
        def timed() -> Any:
            started = time.thread_time()
            try:
                return fn(*args, **kwargs)
            finally:
                self.cpu.append(time.thread_time() - started)

        return super().submit(timed)


def graph(expr: str | None = None) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": {}}
    if expr is not None:
        g.node("x", "flow.transform@1", {"fields": {"r": cel(expr)}})
    return g


def publishes_local(expr: str) -> bool:
    result = validate(graph(expr).build(), ValidationContext(catalog=CATALOG, subflows={}))
    return not any(d.severity == "error" for d in result.diagnostics) and result.expressions[0].mode == "local"


def heaviest(template: Callable[[int], str]) -> str:
    """The largest n that still publishes local: it maxes out the work bound (or the expression or pattern length)."""
    best = ""
    for n in range(1, 400):
        if not publishes_local(template(n)):
            break
        best = template(n)
    assert best, template(1)
    return best


def loads() -> Iterator[tuple[str, str]]:
    for i, expr in enumerate(WORST):
        yield f"worst{i}", expr
    for name, template in ADVERSARIAL.items():
        yield name, heaviest(template)
    yield "binding", BINDING


LOADS = dict(loads())
REPORT: dict[str, Any] = {"profile": CURRENT_CEL_PROFILE, "target_s": TASK_CPU_TARGET_S, "loads": {}}


@pytest.fixture(scope="module", autouse=True)
def report() -> Iterator[None]:
    yield
    if directory := os.environ.get("DEWPOINT_CEL_GATE_RESULTS"):
        os.makedirs(directory, exist_ok=True)
        with open(os.path.join(directory, "task_cost.json"), "w") as f:
            json.dump(REPORT, f, indent=1, sort_keys=True)


@pytest.mark.parametrize("name", list(LOADS))
async def test_no_workflow_task_passes_the_cpu_target(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    expr = LOADS[name]
    assert publishes_local(expr), expr[:80]
    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", CURRENT_CEL_PROFILE)  # what the build constant does
    store = MemoryStore()
    g = graph().node("l", "flow.loop@1", {"items": list(range(20)), "concurrency": 10})
    g.node("x", "flow.transform@1", {"fields": {"r": cel(expr)}}).edge("l", "x", "body")
    with Timed() as executor:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            engine = Worker(
                env.client,
                task_queue=ENGINE_QUEUE,
                workflows=[RunGraph, LoopBatch],
                activities=engine_activities(store, [TESTKIT]),
                workflow_runner=SandboxedWorkflowRunner(),
                workflow_task_executor=executor,
            )
            evaluator = Worker(
                env.client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process)]
            )
            async with engine, evaluator:
                handle = await start(env.client, store, g, AT_CAPS)
                result = await asyncio.wait_for(handle.result(), 300)
    assert result.status == "succeeded"
    assert {r.cel_mode for r in store.steps(handle.id) if r.node_key == "x"} == {"local"}
    worst = max(executor.cpu)
    REPORT["loads"][name] = {"expr_chars": len(expr), "tasks": len(executor.cpu), "worst_cpu_s": worst}
    assert worst <= TASK_CPU_TARGET_S, (name, sorted(executor.cpu, reverse=True)[:5])
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/cel/test_bind.py tests/engine/cel/test_route.py tests/engine/runtime/test_resolve.py tests/engine/cel/test_gate_cost.py tests/apps/worker/test_run_graph_yield.py tests/apps/worker/test_gate_task_cost.py`
Expected: 12 failed, 24 passed, in about 6 minutes (one gate 7b load never finishes on `main`).
- `test_measure_counts_every_value_it_binds`: `AttributeError: 'Measure' object has no attribute 'nodes'`.
- `test_the_yield_budget_charges_the_values_each_view_binds` and gate 7's
  `test_local_latency_and_the_cpu_between_two_yield_points`: `TypeError: YieldBudget.must_yield() missing 1 required
  positional argument: 'record'`.
- `test_cel_runs_inline_only_when_this_build_runs_the_profile`: `AttributeError: module
  'dewpoint.engine.runtime.resolve' has no attribute 'bind_view'`.
- The four `test_run_graph_yield.py` tests: three runs fail with `internal_error` (the log shows
  `TypeError: YieldBudget.charge() got an unexpected keyword argument 'nodes'`), and
  `test_binding_is_charged_when_the_evaluator_runs_the_expression` sees no binding charged (`assert (0 == 20)`).
- Gate 7b's `equality`, `conversion` and `binding` loads each have a workflow task over 1 s (planning measured 1.77,
  2.18 and 1.62 s). The `regex` load's tasks pass the SDK's 2 s deadlock detector, so they fail and retry until the
  test gives up (`CancelledError`).

- [ ] **Step 3: Count and charge what a binding holds**

In `backend/src/dewpoint/engine/cel/bind.py`:

```diff
diff --git a/backend/src/dewpoint/engine/cel/bind.py b/backend/src/dewpoint/engine/cel/bind.py
--- a/backend/src/dewpoint/engine/cel/bind.py
+++ b/backend/src/dewpoint/engine/cel/bind.py
@@ -146,6 +146,7 @@
     longest_list: int
     largest_map: int
     longest_string: int
+    nodes: int  # every value bound, containers included: what binding them costs grows with this (spec §5.6)

     @property
     def within_caps(self) -> bool:
@@ -160,10 +161,11 @@

 def measure(bindings: Mapping[str, Any]) -> Measure:
     sizes = [len(canonical_json(v)) for v in bindings.values()]
-    lists = maps = strings = 0
+    lists = maps = strings = nodes = 0
     stack = list(bindings.values())
     while stack:
         v = stack.pop()
+        nodes += 1
         if isinstance(v, dict):
             maps = max(maps, len(v))
             stack.extend(v.values())
@@ -172,4 +174,4 @@
             stack.extend(v)
         elif isinstance(v, str):
             strings = max(strings, len(v.encode()))
-    return Measure(sum(sizes), max(sizes, default=0), lists, maps, strings)
+    return Measure(sum(sizes), max(sizes, default=0), lists, maps, strings, nodes)
```

In `backend/src/dewpoint/engine/cel/route.py`:

```diff
diff --git a/backend/src/dewpoint/engine/cel/route.py b/backend/src/dewpoint/engine/cel/route.py
--- a/backend/src/dewpoint/engine/cel/route.py
+++ b/backend/src/dewpoint/engine/cel/route.py
@@ -12,6 +12,7 @@
 YIELD_BYTES = 8 * 1024 * 1024
 YIELD_WORK = 4_000_000  # not in the spec's list: iterations don't bound CPU on their own (estimate.py)
 YIELD_EVALUATIONS = 200
+YIELD_NODES = 100_000  # the values the evaluations bind: converting them costs CPU their stored bounds don't count


 def route(
@@ -26,30 +27,36 @@

 @dataclass
 class YieldBudget:
-    """Stored bounds of the local evaluations since the interpreter's last await."""
+    """One workflow task's local evaluations: their stored bounds, and the values they bound (`Measure.nodes`)."""

     iterations: int = 0
     bytes: int = 0
     work: int = 0
     evaluations: int = 0
+    nodes: int = 0

-    def must_yield(self, record: ExpressionRecord) -> bool:
-        """True when the interpreter must await a 1 ms durable timer before evaluating `record` locally."""
-        if self.evaluations == 0:
+    def must_yield(self, record: ExpressionRecord | None = None) -> bool:
+        """True when the interpreter must await a 1 ms durable timer before binding a view (`record` None), or before
+        evaluating `record` locally. The first thing a workflow task does always runs."""
+        if self.evaluations == 0 and self.nodes == 0:
             return False
-        return (
-            self.evaluations >= YIELD_EVALUATIONS
-            or self.iterations + (record.iterations or 0) > YIELD_ITERATIONS
+        if self.evaluations >= YIELD_EVALUATIONS or self.nodes >= YIELD_NODES:
+            return True
+        return record is not None and (
+            self.iterations + (record.iterations or 0) > YIELD_ITERATIONS
             or self.bytes + (record.bytes or 0) > YIELD_BYTES
             or self.work + (record.work or 0) > YIELD_WORK
         )

-    def charge(self, record: ExpressionRecord) -> None:
-        self.iterations += record.iterations or 0
-        self.bytes += record.bytes or 0
-        self.work += record.work or 0
-        self.evaluations += 1
+    def charge(self, record: ExpressionRecord | None = None, *, nodes: int = 0) -> None:
+        """A view bound (`nodes`: the values it bound), or `record` evaluated locally."""
+        self.nodes += nodes
+        if record is not None:
+            self.iterations += record.iterations or 0
+            self.bytes += record.bytes or 0
+            self.work += record.work or 0
+            self.evaluations += 1

     def reset(self) -> None:
-        """After any await: the next workflow task starts a fresh budget."""
-        self.iterations = self.bytes = self.work = self.evaluations = 0
+        """A new workflow task starts a fresh budget."""
+        self.iterations = self.bytes = self.work = self.evaluations = self.nodes = 0
```

- [ ] **Step 4: Bind one view at a time**

In `backend/src/dewpoint/engine/runtime/resolve.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/resolve.py b/backend/src/dewpoint/engine/runtime/resolve.py
--- a/backend/src/dewpoint/engine/runtime/resolve.py
+++ b/backend/src/dewpoint/engine/runtime/resolve.py
@@ -15,7 +15,7 @@
 from typing import Any

 from dewpoint.engine.cel import evaluate
-from dewpoint.engine.cel.bind import BindingError, ScopeView, bind, measure
+from dewpoint.engine.cel.bind import BindingError, Measure, ScopeView, bind, measure
 from dewpoint.engine.cel.ipc import EvaluateRequest
 from dewpoint.engine.cel.record import ExpressionRecord
 from dewpoint.engine.cel.route import route
@@ -143,26 +143,36 @@
     def request(self, profile: str) -> dict[str, Any]:
         return EvaluateRequest(profile, self.record.expr, dict(self.record.declarations), self.bindings).to_json()

-    def run_local(self) -> list[evaluate.Outcome]:
-        program = evaluate.compiled(self.record.expr, self.record.declarations)
-        return [evaluate.run(program, b) for b in self.bindings]
+    def run_one(self, bindings: Mapping[str, Any]) -> evaluate.Outcome:
+        """One binding set, in-process."""
+        return evaluate.run(evaluate.compiled(self.record.expr, self.record.declarations), bindings)
+
+
+@dataclass(frozen=True)
+class Bound:
+    """One view's binding set, measured: routing reads the caps, the yield budget the values bound."""
+
+    bindings: Mapping[str, Any]
+    measured: Measure
+
+
+def bind_view(record: ExpressionRecord, view: ScopeView) -> Bound:
+    try:
+        b = bind(record, view)
+    except BindingError as e:
+        raise ValueFailure(evaluate.TYPE_MISMATCH, str(e)) from None
+    return Bound(b, measure(b))


 def cel_task(
-    record: ExpressionRecord, views: Sequence[ScopeView], *, local_profile: str | None, version_profile: str
+    record: ExpressionRecord, bound: Sequence[Bound], *, local_profile: str | None, version_profile: str
 ) -> CelTask:
-    """Bind every view; inline only when every binding set is within the caps and the profile runs here."""
-    bindings: list[Mapping[str, Any]] = []
-    local = True
-    for v in views:
-        try:
-            b = bind(record, v)
-        except BindingError as e:
-            raise ValueFailure(evaluate.TYPE_MISMATCH, str(e)) from None
-        bindings.append(b)
-        mode = route(record, measure(b), local_profile=local_profile, version_profile=version_profile)
-        local = local and mode == "local"
-    return CelTask(record, tuple(bindings), local)
+    """Inline only when every binding set is within the caps and the profile runs here."""
+    local = all(
+        route(record, b.measured, local_profile=local_profile, version_profile=version_profile) == "local"
+        for b in bound
+    )
+    return CelTask(record, tuple(b.bindings for b in bound), local)


 def outcome_value(outcome: evaluate.Outcome) -> Any:
```

- [ ] **Step 5: Give the budget to the workflow task**

In `backend/src/dewpoint/engine/runtime/execution.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -27,6 +27,7 @@
     from dewpoint.engine.canonical import canonical_json
     from dewpoint.engine.cel import evaluate as cel
     from dewpoint.engine.cel.profile import LOCAL_CEL_PROFILE
+    from dewpoint.engine.cel.record import ExpressionRecord
     from dewpoint.engine.cel.route import YieldBudget
     from dewpoint.engine.graph.values import CelValue, RefValue, TemplateValue
     from dewpoint.engine.registry import control
@@ -186,7 +187,9 @@
     sched: Scheduler

     def __init__(self) -> None:
-        self._yield = YieldBudget()
+        self._yield = YieldBudget()  # the local evaluations of the current workflow task (spec §5.6)
+        self._yield_task = -1  # the history length that workflow task started with
+        self._yield_timer: asyncio.Task[None] | None = None  # the one yield point every waiter shares
         self._rows: dict[tuple[str, str, int], StepRow] = {}  # queued for the next projection, per attempt
         self._secrets: Secrets = ()  # sensitive values seen so far: masked in everything projected
         self._started: dict[Instance, str] = {}
@@ -318,7 +321,6 @@
                 )
                 done, _ = await workflow.wait([*tasks.values(), clock, wake], return_when=asyncio.FIRST_COMPLETED)
                 wake.cancel()
-                self._yield.reset()
                 if clock in done:
                     self.sched.end(
                         RunEnd(DEADLINE_EXCEEDED, Failure(DEADLINE_EXCEEDED, "The run passed its deadline."))
@@ -636,9 +638,7 @@
                 values[pointer] = resolve.template(v, value)
             elif isinstance(value, CelValue):
                 record = self.program.record(owner.id if owner is not None else None, pointer)
-                task = resolve.cel_task(
-                    record, [v], local_profile=LOCAL_CEL_PROFILE, version_profile=self.program.cel_profile
-                )
+                task = await self._cel_task(record, [v])
                 [outcome] = await self._evaluate(task)
                 values[pointer] = resolve.outcome_value(outcome)
                 mode = "activity" if mode == "activity" or not task.local else "local"
@@ -646,13 +646,25 @@
                 values[pointer] = value.value
         return values, mode

+    async def _cel_task(self, record: ExpressionRecord, views: Sequence[Any]) -> resolve.CelTask:
+        """Bind each view within the workflow task's budget (spec §5.6). Binding converts every value it binds, so
+        it's charged as they are (`Measure.nodes`), whether the expression then runs here or in `cel.evaluate`."""
+        bound: list[resolve.Bound] = []
+        for v in views:
+            await self._yield_point(None)
+            b = resolve.bind_view(record, v)
+            self._yield.charge(nodes=b.measured.nodes)
+            bound.append(b)
+        return resolve.cel_task(
+            record, bound, local_profile=LOCAL_CEL_PROFILE, version_profile=self.program.cel_profile
+        )
+
     async def _evaluate(self, task: resolve.CelTask) -> list[cel.Outcome]:
         if task.local:
-            if self._yield.must_yield(task.record):
-                await asyncio.sleep(0.001)  # a durable timer: the workflow task ends here (spec §5.6)
-                self._yield.reset()
-            outcomes = task.run_local()
-            for _ in outcomes:
+            outcomes = []
+            for bindings in task.bindings:  # a filter's items one at a time: each is an evaluation
+                await self._yield_point(task.record)
+                outcomes.append(task.run_one(bindings))
                 self._yield.charge(task.record)
             return outcomes
         out: list[cel.Outcome] = []
@@ -676,6 +688,22 @@
                 return [cel.Outcome(error=cel.PROFILE_UNAVAILABLE, message=message)] * len(task.bindings)
             out += [cel.Outcome.from_json(o) for o in result.outcomes]
         return out
+
+    async def _yield_point(self, record: ExpressionRecord | None) -> None:
+        """Before binding a view (`record` None) or evaluating `record` locally: when the current workflow task's budget
+        is spent, await a 1 ms durable timer, which ends the task (spec §5.6). The budget belongs to one workflow task:
+        it starts afresh when the history length changes, which happens only between tasks, in a replay too.
+        Concurrent units share the budget and one timer, and each checks again once it fires."""
+        while True:
+            length = workflow.info().get_current_history_length()
+            if length != self._yield_task:
+                self._yield_task = length
+                self._yield.reset()
+            if not self._yield.must_yield(record):
+                return
+            if self._yield_timer is None or self._yield_timer.done():
+                self._yield_timer = asyncio.create_task(asyncio.sleep(0.001))
+            await asyncio.shield(self._yield_timer)

     # --- steps -----------------------------------------------------------------------------------------------------

@@ -729,9 +757,7 @@
         record = self.program.record(step.id, "/predicate")
         views = [self._view(inst.scope, item=(item, i)) for i, item in enumerate(items)]
         try:
-            task = resolve.cel_task(
-                record, views, local_profile=LOCAL_CEL_PROFILE, version_profile=self.program.cel_profile
-            )
+            task = await self._cel_task(record, views)
         except resolve.ValueFailure as e:
             return _Effect(failure=e.failure)
         kept: list[Any] = []
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest -q tests/engine/cel/test_bind.py tests/engine/cel/test_route.py tests/engine/runtime/test_resolve.py tests/engine/cel/test_gate_cost.py tests/apps/worker/test_run_graph_yield.py tests/apps/worker/test_gate_task_cost.py`
Expected: 36 passed, in about 45 s.

- [ ] **Step 7: Run gate 7b in CI's CEL gate job**

In `.github/workflows/ci.yml`:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -25,7 +25,9 @@
       - uses: actions/checkout@v4
       - uses: astral-sh/setup-uv@38f3f104447c67c051c4a08e39b64a148898af3a # v4
       - run: uv sync --locked
-      - run: uv run pytest -q tests/engine/cel tests/engine/graph/test_validate_cel.py tests/apps/cel_evaluator
+      - run: >-
+          uv run pytest -q tests/engine/cel tests/engine/graph/test_validate_cel.py tests/apps/cel_evaluator
+          tests/apps/worker/test_gate_task_cost.py
         env: { DEWPOINT_CEL_GATE_RESULTS: cel-gate-results }
       # The measurements matter most when a gate fails: print and keep them either way.
       - if: always()
```

- [ ] **Step 8: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src/dewpoint/engine/cel src/dewpoint/engine/runtime tests/engine tests/apps/worker ../.github \
  && git commit -m "feat(engine): one CEL budget per workflow task, binding charged, and gate 7b" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,023 passed and 8 skipped.

---

### Task 2: CEL gate 4, Temporal replay

Gate 4 evaluates the corpus in a sandboxed workflow, the way `RunGraph` evaluates local CEL, and replays its history
in five fresh processes (decision 4). The corpus is what publish accepts. A bite check shows that the gate catches
what publish refuses: a comprehension over a map, whose order differs from process to process.

The gate tests behaviour `main` already has, so it passes as soon as it's written. Step 2 shows that the bite check
bites instead: a gate that can't fail proves nothing.

**Files:**
- Create: `backend/tests/engine/cel/gate_replay_workflow.py`, `backend/tests/engine/cel/test_gate_replay.py`

**Interfaces:**
- Consumes: 2a-2's gate 1 corpus (`tests.engine.cel.test_gate_semantics.CASES`), `classify.order_problems`,
  `runtime.compile_checked` and `evaluate`.
- Produces: the workflow `CelCorpus` and the activity `gate4.outcomes` (test-only).

- [ ] **Step 1: Write the gate**

Create `backend/tests/engine/cel/gate_replay_workflow.py`, the workflow. It's a module of its own, so each replaying
process imports it fresh:

```python
# SPDX-License-Identifier: Apache-2.0
"""Gate 4's workflow (spec §5.9): it evaluates a CEL corpus in-process, inside Temporal's sandbox, the way RunGraph
evaluates local CEL. The digest of the outcomes names the activity it then schedules, so a replay that computes any
other outcome fails as nondeterministic."""

import hashlib
import json
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():  # as RunGraph: the runtime is a C++ extension, loaded once
    from dewpoint.engine.cel import evaluate


@activity.defn(name="gate4.outcomes")
async def outcomes(digest: str) -> None:
    """Nothing to do: the digest is the activity's id."""


@workflow.defn(name="CelCorpus")
class CelCorpus:
    @workflow.run
    async def run(self, corpus: list[list[Any]]) -> str:
        out = [evaluate.run(evaluate.compiled(expr, decls), bindings).to_json() for expr, decls, bindings in corpus]
        digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:32]
        await workflow.execute_activity(
            outcomes, digest, activity_id=digest, start_to_close_timeout=timedelta(seconds=30)
        )
        return digest
```

Create `backend/tests/engine/cel/test_gate_replay.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Gate 4 (spec §5.9): Temporal replay. A sandboxed workflow evaluates the gate corpus in-process; its history is
recorded once, then replayed in 5 fresh processes with different PYTHONHASHSEED values. The C++ runtime seeds its
maps per process, so this catches iteration order leaking into what a workflow computes. The corpus holds only what
publish accepts: gate 1's cases that compile and iterate only proven lists, and maps read through sortedKeys."""

import asyncio
import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from typing import Any

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.engine.cel import classify, runtime
from dewpoint.engine.cel import types as T
from tests.engine.cel.gate_replay_workflow import CelCorpus, outcomes
from tests.engine.cel.test_gate_semantics import CASES

BACKEND = Path(__file__).parents[3]
REPLAY = textwrap.dedent(
    """
    import asyncio, sys
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer
    from tests.engine.cel.gate_replay_workflow import CelCorpus

    history = WorkflowHistory.from_json("gate4", open(sys.argv[1]).read())
    asyncio.run(Replayer(workflows=[CelCorpus]).replay_workflow(history))
    """
)
M = {f"k{i:02d}": i for i in reversed(range(24))}  # built in reverse: the runtime's order is its own
MAPS: list[list[Any]] = [
    ["sortedKeys(m)", {"m": T.MAP}, {"m": M}],
    ["sortedKeys(m).map(k, m[k] * 2)", {"m": T.MAP}, {"m": M}],
    ["m", {"m": T.MAP}, {"m": M}],
    ["{'b': m.k01, 'a': m.k02, 'c': [m.k03, {'z': 1, 'y': 2}]}", {"m": T.MAP}, {"m": M}],
    ["sortedKeys(m).exists_one(k, 10 / m[k] > 3)", {"m": T.MAP}, {"m": M}],
    ["'k03' in m && m == m", {"m": T.MAP}, {"m": M}],
    ["[macNormalize('5C:5B:35:00:00:01'), ipInCidr('10.1.2.3', '10.0.0.0/8')]", {}, {}],
]
LEAK = ["m.map(k, k)", {"m": T.MAP}, {"m": M}]  # iterates a map: publish refuses it


def publishable(expr: str, decls: dict[str, str]) -> bool:
    try:
        return not classify.order_problems(runtime.compile_checked(expr, decls).checked)
    except runtime.CompileError:
        return False


def corpus() -> list[list[Any]]:
    cases = [[e, {n: T.DYN for n in v}, v] for e, v, _ in CASES]
    return [c for c in cases if publishable(c[0], c[1])] + MAPS


async def recorded(path: Path, items: list[list[Any]]) -> Path:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(env.client, task_queue="gate4", workflows=[CelCorpus], activities=[outcomes]):
            handle = await env.client.start_workflow(CelCorpus.run, items, id=str(uuid.uuid4()), task_queue="gate4")
            await asyncio.wait_for(handle.result(), 120)
            history = (await handle.fetch_history()).to_json()
    await asyncio.to_thread(path.write_text, history)
    return path


def replays(history: Path) -> list[str]:
    """What each replay reported on stderr, in 5 fresh processes with different hash seeds: "" when it passed."""
    out = []
    for seed in range(5):
        done = subprocess.run(
            [sys.executable, "-c", REPLAY, str(history)],
            cwd=BACKEND,
            env={**os.environ, "PYTHONHASHSEED": str(seed * 7919 + 1)},
            capture_output=True,
            text=True,
            timeout=120,
        )
        out.append("" if done.returncode == 0 else done.stderr or f"exit {done.returncode}")
    return out


def test_the_corpus_is_what_publish_accepts() -> None:
    items = corpus()
    assert len(items) == 71 + len(MAPS)  # gate 1's 82 cases, less 6 that don't compile and 5 over unproven lists
    assert all(publishable(e, d) for e, d, _ in items) and not publishable(LEAK[0], LEAK[1])


async def test_the_corpus_replays_identically_in_five_fresh_processes(tmp_path: Path) -> None:
    assert replays(await recorded(tmp_path / "gate4.json", corpus())) == [""] * 5


async def test_the_gate_catches_iteration_order_leaking(tmp_path: Path) -> None:
    """The bite check: a comprehension over a map, which publish refuses, computes a different list in another
    process, and its replay fails."""
    failed = [r for r in replays(await recorded(tmp_path / "leak.json", [*corpus(), LEAK])) if r]
    assert failed and all("[TMPRL1100] Nondeterminism error: Activity id" in r for r in failed)
```

- [ ] **Step 2: Run it, and see the bite check bite**

Run: `cd backend && uv run pytest -q tests/engine/cel/test_gate_replay.py`
Expected: 3 passed.

Then check that the bite check can fail. In `test_the_gate_catches_iteration_order_leaking`, temporarily record
`corpus()` without `LEAK`, and run `cd backend && uv run pytest -q tests/engine/cel/test_gate_replay.py -k leaking`.
It fails with `assert ([])`: every replay passes, so nothing was caught. Undo the change.

- [ ] **Step 3: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add tests/engine/cel/gate_replay_workflow.py tests/engine/cel/test_gate_replay.py \
  && git commit -m "test(cel): gate 4, the corpus replays identically in five fresh processes" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,026 passed and 8 skipped.

**Checkpoint 1:** the CEL gates. Stop for the owner's review. Gate 7b's Linux result, which Task 11 needs, comes
from CI: ask the owner whether to push the branch now, so that the `cel-gates` job runs it.

---

### Task 3: Worker Versioning and `dewpoint deployment`

Every engine worker serves its build's version of the Worker Deployment `dewpoint-engine`, and both workflow types
are pinned (decision 5). An operator makes a build current with `dewpoint deployment set-current`, and
`dewpoint deployment status` shows where each version stands (decision 6).

The time-skipping server refuses Worker Versioning, so the tests that need it take `dev_env`: one Temporal CLI dev
server per session, which `start_local()` downloads the first time (decision 7). They check where a pinned run's
every piece ran: each workflow task's version, and each activity's worker identity.

**Files:**
- Create: `backend/src/dewpoint/apps/worker/deployment.py`
- Modify: `backend/src/dewpoint/engine/runtime/workflow.py`, `backend/src/dewpoint/apps/worker/main.py`,
  `backend/src/dewpoint/apps/cli/main.py`
- Modify: `backend/tests/apps/worker/conftest.py`, `backend/tests/apps/worker/test_main.py`
- Create: `backend/tests/apps/worker/test_deployment.py`, `backend/tests/apps/cli/test_deployment_cli.py`

**Interfaces:**
- Consumes: 2a-3a's `build_id(version)` (`engine/runtime/build.py`), and 2a-3b's `RunGraph`, `LoopBatch` and
  harness.
- Produces:
  - `dewpoint.apps.worker.deployment`: `DEPLOYMENT = "dewpoint-engine"`, `IDENTITY`, `this_build() -> str`,
    `deployment_config(build: str) -> WorkerDeploymentConfig`, the frozen dataclasses `Version(build_id, status)` and
    `Deployment(current: str | None, versions: list[Version])`,
    `async set_current(client, build, *, wait_s: float = 60.0) -> None` and `async describe(client) -> Deployment`;
  - `engine_worker(client, store, plugins, settings, *, build: str | None = None, identity: str | None = None)`;
  - the CLI commands `dewpoint deployment set-current [--build-id B] [--wait S]` and `dewpoint deployment status`;
  - the session fixture `dev_env` (`tests/apps/worker/conftest.py`);
  - in `tests/apps/worker/test_deployment.py`: `build(name) -> str` (a build ID of the test's own),
    `engine(client, store, build_id) -> Worker` (its identity is the build ID), and
    `placement(history) -> Placement`: the builds that completed a history's workflow tasks, their versioning
    behaviours, the workers that ran its engine activities, and its CEL tasks as (queue, worker).

- [ ] **Step 1: Write the failing tests**

In `backend/tests/apps/worker/conftest.py`, the dev server:

```diff
diff --git a/backend/tests/apps/worker/conftest.py b/backend/tests/apps/worker/conftest.py
--- a/backend/tests/apps/worker/conftest.py
+++ b/backend/tests/apps/worker/conftest.py
@@ -19,3 +19,11 @@
     outstanding: every later timer on a shared server would wait in real time."""
     async with await WorkflowEnvironment.start_time_skipping() as environment:
         yield environment
+
+
+@pytest.fixture(scope="session")
+async def dev_env() -> AsyncIterator[WorkflowEnvironment]:
+    """Temporal's CLI dev server (downloaded once by the SDK), for what the test server can't do: Worker Versioning,
+    a terminated child reaching its parent, and Temporal suggesting continue-as-new. Time runs for real on it."""
+    async with await WorkflowEnvironment.start_local() as environment:
+        yield environment
```

In `backend/tests/apps/worker/test_main.py`, the engine worker's deployment:

```diff
diff --git a/backend/tests/apps/worker/test_main.py b/backend/tests/apps/worker/test_main.py
--- a/backend/tests/apps/worker/test_main.py
+++ b/backend/tests/apps/worker/test_main.py
@@ -6,8 +6,10 @@

 from temporalio.testing import WorkflowEnvironment

+import dewpoint
 from dewpoint.apps.worker.main import engine_worker
 from dewpoint.core.config import Settings
+from dewpoint.engine.runtime.build import build_id
 from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
 from tests.apps.worker.harness import MemoryStore
 from tests.support.plugins.testkit import TESTKIT
@@ -35,3 +37,14 @@
     """2a-3b: a loop batch is a workflow type of its own, on the same queue as the runs that start it."""
     worker = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings())
     assert worker.config()["workflows"] == [RunGraph, LoopBatch]
+
+
+async def test_the_engine_worker_serves_this_builds_version_of_the_deployment(own_env: WorkflowEnvironment) -> None:
+    """Spec §7: one Worker Deployment, `dewpoint-engine`; this build's version is its build id. The CEL worker isn't
+    in it: its queues are routed by profile."""
+    config = engine_worker(own_env.client, MemoryStore(), [TESTKIT], settings()).config()["deployment_config"]
+    assert config.use_worker_versioning
+    assert (config.version.deployment_name, config.version.build_id) == (
+        "dewpoint-engine",
+        build_id(dewpoint.__version__),
+    )
```

Create `backend/tests/apps/worker/test_deployment.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The engine's Worker Deployment (spec §7), on Temporal's dev server: the test server refuses Worker Versioning.
A run is pinned to the build it started on, with its children and its continued runs, while new runs start on the
deployment's current build."""

import asyncio
import uuid
from dataclasses import dataclass

import pytest
from temporalio.api.enums.v1 import VersioningBehavior
from temporalio.client import Client, WorkflowHistory
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker.activities import cel_activity
from dewpoint.apps.worker.deployment import describe, set_current
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
from tests.apps.worker.harness import MemoryStore, in_process, start
from tests.apps.worker.test_main import settings
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref
from tests.support.plugins.testkit import TESTKIT


def build(name: str) -> str:
    """A build id of this test's own: each test's builds are new versions of the one deployment."""
    return f"{name}-{uuid.uuid4().hex[:8]}"


def engine(client: Client, store: MemoryStore, build_id: str) -> Worker:
    return engine_worker(client, store, [TESTKIT], settings(), build=build_id, identity=build_id)


@dataclass(frozen=True)
class Placement:
    """Where an execution's tasks ran. An activity's events don't name a version: its worker's identity does."""

    builds: set[str]  # the builds that completed its workflow tasks
    behaviours: set[int]  # the versioning behaviour each workflow task reported
    engine: set[str]  # the workers that ran its `dewpoint-engine` activities
    cel: set[tuple[str, str]]  # (task queue, worker) of its `cel.evaluate` activities


def placement(history: WorkflowHistory) -> Placement:
    queues = {
        e.event_id: e.activity_task_scheduled_event_attributes.task_queue.name
        for e in history.events
        if e.HasField("activity_task_scheduled_event_attributes")
    }
    started = [
        (queues[a.scheduled_event_id], a.identity)
        for e in history.events
        if e.HasField("activity_task_started_event_attributes")
        for a in [e.activity_task_started_event_attributes]
    ]
    tasks = [
        e.workflow_task_completed_event_attributes
        for e in history.events
        if e.HasField("workflow_task_completed_event_attributes")
    ]
    return Placement(
        builds={t.deployment_version.build_id for t in tasks},
        behaviours={t.versioning_behavior for t in tasks},
        engine={who for queue, who in started if queue == ENGINE_QUEUE},
        cel={(queue, who) for queue, who in started if queue != ENGINE_QUEUE},
    )


async def test_set_current_waits_for_the_builds_workers(dev_env: WorkflowEnvironment) -> None:
    """A version exists once one of its workers has polled: `set_current` retries until then, and gives up after its
    wait. `describe` then names the build new runs start on."""
    client, first = dev_env.client, build("first")
    with pytest.raises(RPCError):
        await set_current(client, build("nobody"), wait_s=1)
    promote = asyncio.create_task(set_current(client, first, wait_s=30))
    await asyncio.sleep(1)
    assert not promote.done()  # no worker of that build yet
    async with engine(client, MemoryStore(), first):
        await asyncio.wait_for(promote, 30)
        deployment = await describe(client)
    assert deployment.current == first and ("current" in {v.status for v in deployment.versions if v.build_id == first})


def graph() -> tuple[MemoryStore, G]:
    """A plugin step long enough to switch builds under it, then a sub-flow and a batched loop: children."""
    store = MemoryStore()
    sub = G()
    sub.settings = {
        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "outputs": {"double": ref("steps.t.output.double")},
    }
    sub.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    g = G()
    g.settings = {
        "input_schema": {"type": "object"},
        "outputs": {"double": ref("steps.r.output.double"), "count": ref("steps.l.output.count")},
    }
    g.node("s", "testkit.slow@1", {"seconds": 3}).node(
        "r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sub)), "input": {"n": 21}}
    )
    g.node("l", "flow.loop@1", {"items": list(range(101))}).node("x", "testkit.echo@1", {"value": ref("item")})
    g.edge("s", "r").edge("r", "l").edge("l", "x", "body")
    return store, g


async def test_a_run_stays_on_the_build_it_started_on_with_its_children_and_continued_runs(
    dev_env: WorkflowEnvironment,
) -> None:
    client, old, new = dev_env.client, build("old"), build("new")
    store, g = graph()
    cel_worker = Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process)])
    async with engine(client, store, old), engine(client, store, new), cel_worker:
        await set_current(client, old)
        first = await start(client, store, g, {}, checkpoint_events=60)
        await asyncio.sleep(1)  # the plugin step is running on the old build
        await set_current(client, new)
        second = await start(client, store, g, {}, checkpoint_events=60)
        results = await asyncio.wait_for(asyncio.gather(first.result(), second.result()), 120)
        runs = [await executions(client, h.id, h.first_execution_run_id or "") for h in (first, second)]
    assert [(r.status, r.outputs) for r in results] == [("succeeded", {"double": 42, "count": 101})] * 2
    for handle, expected, chain in zip((first, second), (old, new), runs, strict=True):
        assert len(chain) >= 4, handle.id  # the run, a continued run, the sub-flow and the batch
        for history in chain:
            ran = placement(history)
            assert ran.builds == {expected} and ran.engine <= {expected}, (history.workflow_id, ran)
            assert ran.behaviours == {VersioningBehavior.VERSIONING_BEHAVIOR_PINNED}
```

Create `backend/tests/apps/cli/test_deployment_cli.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`dewpoint deployment`: `set-current` makes this build (or the one named) the one new runs start on, and `status`
lists every version. The calls themselves are covered by tests/apps/worker/test_deployment.py, on Temporal's dev
server; here Temporal is a stand-in."""

from typing import Any

import pytest
from typer.testing import CliRunner

import dewpoint
from dewpoint.apps.cli import main as cli
from dewpoint.apps.worker.deployment import Deployment, Version
from dewpoint.engine.runtime.build import build_id
from tests.apps.cli.test_dev_run_cli import cli_env  # noqa: F401  (a fixture)


@pytest.mark.usefixtures("cli_env")
def test_set_current_defaults_to_this_build(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[str, float]] = []

    async def set_current(client: Any, build: str, *, wait_s: float) -> None:
        seen.append((build, wait_s))

    monkeypatch.setattr(cli, "set_current", set_current)
    this = build_id(dewpoint.__version__)
    first = CliRunner().invoke(cli.app, ["deployment", "set-current"])
    second = CliRunner().invoke(cli.app, ["deployment", "set-current", "--build-id", "b-2", "--wait", "5"])
    assert (first.exit_code, first.output) == (0, f"current: {this}\n")
    assert (second.exit_code, second.output) == (0, "current: b-2\n")
    assert seen == [(this, 60.0), ("b-2", 5.0)]


@pytest.mark.usefixtures("cli_env")
def test_status_lists_every_version(monkeypatch: pytest.MonkeyPatch) -> None:
    async def describe(client: Any) -> Deployment:
        return Deployment("b-2", [Version("b-1", "draining"), Version("b-2", "current")])

    monkeypatch.setattr(cli, "describe", describe)
    result = CliRunner().invoke(cli.app, ["deployment", "status"])
    assert (result.exit_code, result.output) == (0, "current: b-2\nb-1  draining\nb-2  current\n")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_main.py tests/apps/worker/test_deployment.py tests/apps/cli/test_deployment_cli.py`
Expected: 2 errors during collection: `ModuleNotFoundError: No module named 'dewpoint.apps.worker.deployment'`, in
`test_deployment.py` and `test_deployment_cli.py`.

- [ ] **Step 3: The deployment**

Create `backend/src/dewpoint/apps/worker/deployment.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The engine's Worker Deployment (spec §7). Each build is a Deployment Version of `dewpoint-engine`, with build ID
`dewpoint-<version>+abi<ENGINE_ABI>`. `RunGraph` and `LoopBatch` are pinned: a run, its children and its continued
runs finish on the version they started on, while new runs start on the deployment's current version. Making a build
current is an operator's step (docs/operations/deployment.md)."""

import asyncio
from dataclasses import dataclass

from temporalio.api.enums.v1 import WorkerDeploymentVersionStatus
from temporalio.api.workflowservice.v1 import (
    DescribeWorkerDeploymentRequest,
    SetWorkerDeploymentCurrentVersionRequest,
)
from temporalio.client import Client
from temporalio.common import WorkerDeploymentVersion
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import WorkerDeploymentConfig

import dewpoint
from dewpoint.engine.runtime.build import build_id

DEPLOYMENT = "dewpoint-engine"
IDENTITY = "dewpoint-deployment"  # who changed the routing, as Temporal records it


def this_build() -> str:
    return build_id(dewpoint.__version__)


def deployment_config(build: str) -> WorkerDeploymentConfig:
    """The engine worker's: it serves `build`'s version of the deployment. The CEL workers aren't in it (§7)."""
    return WorkerDeploymentConfig(version=WorkerDeploymentVersion(DEPLOYMENT, build), use_worker_versioning=True)


@dataclass(frozen=True)
class Version:
    build_id: str
    status: str  # current, ramping, draining, drained or inactive


@dataclass(frozen=True)
class Deployment:
    current: str | None  # the build new runs start on
    versions: list[Version]


async def set_current(client: Client, build: str, *, wait_s: float = 60.0) -> None:
    """Make `build` the version new runs start on. A version exists once one of its workers has polled: until then
    Temporal refuses, and this retries for up to `wait_s`."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_s
    request = SetWorkerDeploymentCurrentVersionRequest(
        namespace=client.namespace, deployment_name=DEPLOYMENT, build_id=build, identity=IDENTITY
    )
    while True:
        try:
            await client.workflow_service.set_worker_deployment_current_version(request)
            return
        except RPCError as e:
            if e.status not in (RPCStatusCode.NOT_FOUND, RPCStatusCode.FAILED_PRECONDITION) or loop.time() > deadline:
                raise
        await asyncio.sleep(0.5)


async def describe(client: Client) -> Deployment:
    """The current build, and every version Temporal knows with its status: a version still draining serves the
    pinned runs that started on it."""
    info = (
        await client.workflow_service.describe_worker_deployment(
            DescribeWorkerDeploymentRequest(namespace=client.namespace, deployment_name=DEPLOYMENT)
        )
    ).worker_deployment_info
    current = info.routing_config.current_deployment_version.build_id or None
    prefix = "WORKER_DEPLOYMENT_VERSION_STATUS_"
    versions = [
        Version(
            v.deployment_version.build_id, WorkerDeploymentVersionStatus.Name(v.status).removeprefix(prefix).lower()
        )
        for v in info.version_summaries
    ]
    return Deployment(current, sorted(versions, key=lambda v: v.build_id))
```

- [ ] **Step 4: Pin the workflow types**

In `backend/src/dewpoint/engine/runtime/workflow.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -14,6 +14,7 @@
 from typing import Any

 from temporalio import workflow
+from temporalio.common import VersioningBehavior
 from temporalio.exceptions import ApplicationError, ChildWorkflowError

 with workflow.unsafe.imports_passed_through():
@@ -63,7 +64,7 @@
 HANDLED = ("failed", DEADLINE_EXCEEDED)  # the ends that run a failure handler (a cancel is no failure)


-@workflow.defn(name="RunGraph")
+@workflow.defn(name="RunGraph", versioning_behavior=VersioningBehavior.PINNED)  # spec §7
 class RunGraph(Execution):
     @workflow.run
     async def run(self, start: RunInput) -> RunResult:
@@ -346,7 +347,7 @@
         return result.iterations


-@workflow.defn(name="LoopBatch")
+@workflow.defn(name="LoopBatch", versioning_behavior=VersioningBehavior.PINNED)
 class LoopBatch(Execution):
     @workflow.run
     async def run(self, start: BatchInput) -> BatchResult:
```

- [ ] **Step 5: The engine worker serves its build's version**

In `backend/src/dewpoint/apps/worker/main.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/main.py b/backend/src/dewpoint/apps/worker/main.py
--- a/backend/src/dewpoint/apps/worker/main.py
+++ b/backend/src/dewpoint/apps/worker/main.py
@@ -1,7 +1,8 @@
 # SPDX-License-Identifier: Apache-2.0
 """`dewpoint worker` (spec §6, §7): `RunGraph` and the engine activities on `dewpoint-engine`. When an evaluator is
 configured, it also serves `cel.evaluate`, only on the queue of the profile the evaluator reports: it waits for the
-evaluator, then asks its identity. Worker Versioning (the pinned deployment) comes with plan 2a-3c."""
+evaluator, then asks its identity. The engine worker serves this build's version of the `dewpoint-engine` Worker
+Deployment (deployment.py); the CEL worker is outside it, routed by profile."""

 import asyncio
 from collections.abc import Iterable
@@ -14,6 +15,7 @@
 from dewpoint.apps import cel_client
 from dewpoint.apps.plugin_loader import installed_plugins
 from dewpoint.apps.worker.activities import RunStore, cel_activity, engine_activities, remote_evaluator
+from dewpoint.apps.worker.deployment import deployment_config, this_build
 from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.core.config import Settings
 from dewpoint.core.db import make_engine, make_sessionmaker
@@ -34,15 +36,26 @@
             await asyncio.sleep(wait_s)


-def engine_worker(client: Client, store: RunStore, plugins: Iterable[Plugin], settings: Settings) -> Worker:
-    """A stopping worker lets running attempts finish for `worker_shutdown_grace_s`: one it cancels ends as it would
-    on a lost worker, `outcome_unknown` for an ambiguous node."""
+def engine_worker(
+    client: Client,
+    store: RunStore,
+    plugins: Iterable[Plugin],
+    settings: Settings,
+    *,
+    build: str | None = None,
+    identity: str | None = None,
+) -> Worker:
+    """This build's version of the engine deployment (`build`: another's, in the two-build test). A stopping worker
+    lets running attempts finish for `worker_shutdown_grace_s`: one it cancels ends as it would on a lost worker,
+    `outcome_unknown` for an ambiguous node."""
     return Worker(
         client,
         task_queue=ENGINE_QUEUE,
         workflows=[RunGraph, LoopBatch],
         activities=engine_activities(store, plugins),
         graceful_shutdown_timeout=timedelta(seconds=settings.worker_shutdown_grace_s),
+        deployment_config=deployment_config(build or this_build()),
+        identity=identity,
     )


```

- [ ] **Step 6: `dewpoint deployment`**

In `backend/src/dewpoint/apps/cli/main.py`:

```diff
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -17,6 +17,7 @@

 from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
 from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
+from dewpoint.apps.worker.deployment import Deployment, describe, set_current, this_build
 from dewpoint.apps.worker.main import run as run_worker
 from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, anchor_freshness, verify_anchors
 from dewpoint.core.auth.users import PasswordPolicyError, create_user
@@ -52,6 +53,8 @@
 app.add_typer(lifecycle_cli, name="lifecycle")
 dev_cli = typer.Typer(no_args_is_help=True)
 app.add_typer(dev_cli, name="dev")
+deployment_cli = typer.Typer(no_args_is_help=True)
+app.add_typer(deployment_cli, name="deployment")


 async def _init(email: str, password: str) -> None:
@@ -327,6 +330,39 @@
     asyncio.run(run_worker(get_settings()))


+async def _temporal() -> Client:
+    settings = get_settings()
+    return await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
+
+
+@deployment_cli.command("set-current")
+def deployment_set_current(
+    build: str | None = typer.Option(None, "--build-id", help="the build new runs start on (default: this one)"),
+    wait: float = typer.Option(60.0, "--wait", help="seconds to wait for that build's workers to poll"),
+) -> None:
+    """Make a build the one new runs start on (spec §7). A run already started stays on its build until it ends."""
+    target = build or this_build()
+
+    async def _go() -> None:
+        await set_current(await _temporal(), target, wait_s=wait)
+
+    asyncio.run(_go())
+    typer.echo(f"current: {target}")
+
+
+@deployment_cli.command("status")
+def deployment_status() -> None:
+    """The build new runs start on, and every version with its status: a draining one still serves its runs."""
+
+    async def _go() -> Deployment:
+        return await describe(await _temporal())
+
+    deployment = asyncio.run(_go())
+    typer.echo(f"current: {deployment.current or 'none'}")
+    for v in deployment.versions:
+        typer.echo(f"{v.build_id}  {v.status}")
+
+
 async def dev_run_version(
     settings: Settings,
     client: Client,
```

- [ ] **Step 7: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_main.py tests/apps/worker/test_deployment.py tests/apps/cli/test_deployment_cli.py`
Expected: 7 passed. The first run downloads the Temporal CLI.

- [ ] **Step 8: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src/dewpoint/apps src/dewpoint/engine/runtime/workflow.py tests/apps \
  && git commit -m "feat(worker): each build is a pinned version of the dewpoint-engine deployment" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,031 passed and 8 skipped.

---

### Task 4: The two-build test

Spec §7's deployment test, with two builds of the one deployment on the dev server (decision 8):
1. Build N-1 serves, and is current. Its run has a `testkit.slow` step, a sub-flow, a batched loop of 101 items that
   evaluates CEL, and a continue-as-new.
2. While that run is in its slow step, build N starts. N's plugins lack `testkit.slow`, as a build that retired the
   node type would. N becomes current, and a new run starts.
3. Both runs succeed. Every workflow task and every engine activity of N-1's run, its children and its continued
   runs ran on N-1, and the new run's on N. Each CEL task ran on the version's profile queue.
4. Temporal reports N-1 `drained`, and N `current`.

Temporal checks whether a version has drained every 3 minutes by default. The dev server's checks are shortened to
1 s, so the test takes about 20 s.

The code under test is Task 3's, so this test passes as soon as it's written. Step 2 shows that it can fail.

**Files:**
- Modify: `backend/tests/apps/worker/conftest.py`
- Create: `backend/tests/apps/worker/test_two_builds.py`

**Interfaces:**
- Consumes: Task 3's `dev_env`, `set_current`, `describe`, `engine_worker(..., build=, identity=)`, and
  `test_deployment`'s `build` and `placement`; 2a-3b's `record.executions`.
- Produces: nothing new.

- [ ] **Step 1: Write the test**

In `backend/tests/apps/worker/conftest.py`, shorten the dev server's drainage checks:

```diff
diff --git a/backend/tests/apps/worker/conftest.py b/backend/tests/apps/worker/conftest.py
--- a/backend/tests/apps/worker/conftest.py
+++ b/backend/tests/apps/worker/conftest.py
@@ -24,6 +24,12 @@
 @pytest.fixture(scope="session")
 async def dev_env() -> AsyncIterator[WorkflowEnvironment]:
     """Temporal's CLI dev server (downloaded once by the SDK), for what the test server can't do: Worker Versioning,
-    a terminated child reaching its parent, and Temporal suggesting continue-as-new. Time runs for real on it."""
-    async with await WorkflowEnvironment.start_local() as environment:
+    a terminated child reaching its parent, and Temporal suggesting continue-as-new. Time runs for real on it. A
+    version that no run is pinned to reports itself drained within about a second (the default checks every 3 min)."""
+    drainage = [
+        "matching.wv.VersionDrainageStatusVisibilityGracePeriod",
+        "matching.wv.VersionDrainageStatusRefreshInterval",
+    ]
+    args = [a for key in drainage for a in ("--dynamic-config-value", f'{key}="1s"')]
+    async with await WorkflowEnvironment.start_local(dev_server_extra_args=args) as environment:
         yield environment
```

Create `backend/tests/apps/worker/test_two_builds.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The two-build deployment test (spec §7, §10), on Temporal's dev server. Build N-1 drains while build N serves new
runs, and N lacks a node type retired in between (`testkit.slow`). The N-1 run uses that type, and runs plugin
activities, a sub-flow, a loop batch, CEL and continue-as-new. Every engine task of it (workflow tasks and
`dewpoint-engine` activities, in the run, its children and its continued runs) runs on N-1. `cel.evaluate` is outside
the deployment, deliberately: each CEL task runs on a worker serving the version's profile. Once its runs have ended,
N-1 reports itself drained."""

import asyncio

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker.activities import cel_activity
from dewpoint.apps.worker.deployment import describe, set_current
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import cel_queue
from dewpoint.sdk import Plugin
from tests.apps.worker.harness import MemoryStore, in_process, start
from tests.apps.worker.test_deployment import build, placement
from tests.apps.worker.test_main import settings
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref
from tests.support.plugins.testkit import TESTKIT, Slow

WITHOUT_SLOW = Plugin(TESTKIT.name, TESTKIT.version, tuple(n for n in TESTKIT.nodes if n is not Slow))
CEL = f"cel:{CURRENT_CEL_PROFILE}"  # the evaluator worker's identity: the profile it serves


def graphs() -> tuple[MemoryStore, G, G]:
    store = MemoryStore()
    sub = G()
    sub.settings = {
        "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]},
        "outputs": {"double": ref("steps.t.output.double")},
    }
    sub.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.n * 2")}})
    old = G()  # N-1's run: the retired type, a sub-flow, a loop batch with CEL, and continue-as-new
    old.settings = {"input_schema": {"type": "object"}, "outputs": {"double": ref("steps.r.output.double")}}
    old.node("s", "testkit.slow@1", {"seconds": 3})
    old.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sub)), "input": {"n": 21}})
    old.node("l", "flow.loop@1", {"items": list(range(101)), "collect": cel("item * 2")})
    old.node("x", "testkit.echo@1", {"value": ref("item")})
    old.edge("s", "r").edge("r", "l").edge("l", "x", "body")
    new = G()  # N's: nothing retired
    new.settings = {
        "input_schema": {"type": "object"},
        "outputs": {"n": cel("steps.e.output.value + 1")},
    }
    new.node("e", "testkit.echo@1", {"value": 41})
    return store, old, new


async def test_the_old_build_drains_while_the_new_one_serves_new_runs(dev_env: WorkflowEnvironment) -> None:
    client, n1, n = dev_env.client, build("n-1"), build("n")
    store, old_graph, new_graph = graphs()
    evaluator = Worker(
        client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process)], identity=CEL
    )
    async with evaluator, engine_worker(client, store, [TESTKIT], settings(), build=n1, identity=n1):
        await set_current(client, n1)
        old = await start(client, store, old_graph, {}, checkpoint_events=60)
        async with engine_worker(client, store, [WITHOUT_SLOW], settings(), build=n, identity=n):
            await asyncio.sleep(1)  # N-1's run is in its `testkit.slow` step
            await set_current(client, n)
            new = await start(client, store, new_graph, {})
            done = await asyncio.wait_for(asyncio.gather(old.result(), new.result()), 120)
            for _ in range(60):  # N-1 has no run left: Temporal reports it drained
                statuses = {v.build_id: v.status for v in (await describe(client)).versions}
                if statuses.get(n1) == "drained":
                    break
                await asyncio.sleep(0.5)
        chains = [await executions(client, h.id, h.first_execution_run_id or "") for h in (old, new)]
    assert [(r.status, r.outputs) for r in done] == [("succeeded", {"double": 42}), ("succeeded", {"n": 42})]
    assert (statuses[n1], statuses[n]) == ("drained", "current")
    slow = [r for r in store.steps(old.id) if r.node_key == "s"]
    assert [(r.status, r.attempt) for r in slow] == [("succeeded", 1)]  # the retired type ran on N-1, once
    for chain, expected in ((chains[0], n1), (chains[1], n)):
        assert len(chain) >= (4 if expected == n1 else 1)
        cel_tasks = set()
        for history in chain:
            ran = placement(history)
            assert ran.builds == {expected} and ran.engine <= {expected}, (history.workflow_id, ran)
            cel_tasks |= ran.cel
        assert cel_tasks == {(cel_queue(CURRENT_CEL_PROFILE), CEL)}  # on the version's profile, and only there
```

- [ ] **Step 2: Run it, and see it fail without pinning**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_two_builds.py`
Expected: 1 passed, in about 45 s.

Then check that it catches a run leaving its build. In `backend/src/dewpoint/engine/runtime/workflow.py`,
temporarily make `RunGraph` `VersioningBehavior.AUTO_UPGRADE` instead of `PINNED`, and run it again. It fails on
N-1's run: its `Placement` lists both builds, because its workflow tasks and activities moved to N once N was
current. Undo the change. (Removing the behaviour altogether fails sooner: the SDK refuses a workflow type without
one on a versioned worker.)

- [ ] **Step 3: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add tests/apps/worker/conftest.py tests/apps/worker/test_two_builds.py \
  && git commit -m "test(worker): the old build drains while the new one serves new runs" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,032 passed and 8 skipped.

---

### Task 5: What only a real server shows: terminated children, and Temporal's suggestion

2a-3b's handoff left two paths that the time-skipping server can't reach. The dev server reaches both (decisions 9,
10):
- **A child an operator terminates** reaches its parent as a `ChildWorkflowError` caused by a `TerminatedError`.
  The child never wrote its end, so the parent writes it:
  - the child's row is `failed`, with the error code `terminated` (new) and the child's whole grant as its
    iterations;
  - the parent writes the child's start row first, in case the child was terminated before it wrote one
    (`RunStart.of`);
  - both writes are shielded, like any end, and never replace an end the child wrote first:
    `finish_run(..., if_running=True)` updates only a `running` row.

  A sub-flow's step fails with `terminated`, and so does a batch's loop. A terminated failure handler gets its
  row's end, and the run's own end, decided before the handler ran, stands. This fixes 2a-3b's minor M4.
- **Temporal's suggestion** (`is_continue_as_new_suggested`): a dev server of the test's own, configured to suggest
  continuing past 100 history events, drains the run, which continues as new and ends as it would have.

`RunStart.of(run, started_at)` builds a sub-run's start row from its input. `RunGraph` now uses it too, instead of
its private `_start_row`.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/activities.py`, `backend/src/dewpoint/engine/runtime/execution.py`,
  `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/src/dewpoint/core/runs/service.py`, `backend/src/dewpoint/apps/worker/store.py`
- Modify: `backend/tests/core/runs/test_service.py`, `backend/tests/apps/worker/harness.py`
- Create: `backend/tests/apps/worker/test_real_server.py`
- Modify: `docs/operations/runs.md`

**Interfaces:**
- Consumes: Task 3's `dev_env`, `set_current`, `engine_worker(..., build=, identity=)` and `test_deployment.build`;
  2a-3b's `SUBFLOW_GRANT`, `record.executions`, and the store's `start_run`/`finish_run` path.
- Produces:
  - `activities.RunSummary.if_running: bool = False`;
  - `activities.RunStart.of(run: RunInput, started_at: str) -> RunStart` (a `ValueError` for a run that isn't a
    sub-run);
  - `service.finish_run(..., if_running: bool = False)`;
  - `execution.TERMINATED = "terminated"`;
  - the harness's `MemoryStore` honours `if_running` as the database does.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/core/runs/test_service.py`, a parent's write of a child's end never replaces one:

```diff
diff --git a/backend/tests/core/runs/test_service.py b/backend/tests/core/runs/test_service.py
--- a/backend/tests/core/runs/test_service.py
+++ b/backend/tests/core/runs/test_service.py
@@ -237,3 +237,40 @@
                 s, run_id=uuid.uuid4(), tenant_id=tenant, workflow_id=wf, version_id=version, mode="live"
             )
             await s.execute(text("update runs set kind = 'subflow'"))
+
+
+async def test_a_parents_write_of_a_childs_end_never_replaces_one(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    """2a-3c (M4): a parent writes the end of a child that ended without one (terminated). It lands only on a run
+    still `running`: an end the child wrote first stands."""
+    tenant, running = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    async with dispatch_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        first = await service.get_run(s, running)
+        assert first is not None
+        ended = (
+            await service.insert_run(
+                s,
+                run_id=uuid.uuid4(),
+                tenant_id=tenant,
+                workflow_id=first.workflow_id,
+                version_id=first.workflow_version_id,
+                mode="live",
+            )
+        ).id
+    now = datetime.now(UTC)
+    async with worker_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        await service.finish_run(s, ended, status="succeeded", ended_at=now, iterations=3)
+    for run_id in (running, ended):
+        async with worker_sessionmaker() as s, s.begin():
+            await tenant_scope(s, tenant)
+            await service.finish_run(
+                s, run_id, status="failed", ended_at=now, error_code="terminated", iterations=1000, if_running=True
+            )
+    async with owner_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        first, second = await service.get_run(s, running), await service.get_run(s, ended)
+    assert first is not None and (first.status, first.error_code, first.iterations) == ("failed", "terminated", 1000)
+    assert second is not None and (second.status, second.iterations) == ("succeeded", 3)
```

Create `backend/tests/apps/worker/test_real_server.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What only a real Temporal server shows (2a-3b's handoff), on the dev server: a child an operator terminates
reaches its parent, which settles its whole grant and writes its end; and Temporal suggesting continue-as-new starts
the drain. Time runs for real here: waits are short, and a sleeping child is terminated, not waited for."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from temporalio.api.enums.v1 import EventType
from temporalio.client import Client, WorkflowHandle
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from dewpoint.apps.worker.activities import cel_activity
from dewpoint.apps.worker.deployment import set_current
from dewpoint.apps.worker.main import engine_worker
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import cel_queue
from dewpoint.engine.runtime.execution import SUBFLOW_GRANT
from tests.apps.worker.harness import MemoryStore, in_process, start
from tests.apps.worker.test_deployment import build
from tests.apps.worker.test_main import settings
from tests.engine.replay.record import executions
from tests.support.graphs import G, cel, ref
from tests.support.plugins.testkit import TESTKIT


@asynccontextmanager
async def serving(client: Client, store: MemoryStore) -> AsyncIterator[None]:
    """A build of this test's own, current: the dev server keeps the deployment's routing between tests."""
    this = build("real")
    evaluator = Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(in_process)])
    async with evaluator, engine_worker(client, store, [TESTKIT], settings(), build=this, identity=this):
        await set_current(client, this)
        yield


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": outputs}
    return g


def sleeper() -> G:
    return graph().node("d", "flow.delay@1", {"duration_s": 3600})


async def child_started(handle: WorkflowHandle[Any, Any]) -> str:
    """The first child's workflow id, once it has started (in real time)."""
    for _ in range(200):
        for e in (await handle.fetch_history()).events:
            if e.event_type == EventType.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED:
                return e.child_workflow_execution_started_event_attributes.workflow_execution.workflow_id
        await asyncio.sleep(0.1)
    raise AssertionError("no child started")


async def test_a_terminated_sub_flow_fails_its_step_and_its_row_records_the_end(dev_env: WorkflowEnvironment) -> None:
    """The parent learns of the termination (the test server never tells it): its step fails with `terminated`
    under its error policy, the child's whole grant stays counted, and the sub-run's row, which the child never
    ended, records the end. It would otherwise stay `running` and hold its references."""
    client, store = dev_env.client, MemoryStore()
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sleeper()))}, on_error="continue")
    async with serving(client, store):
        handle = await start(client, store, g, {})
        child = await child_started(handle)
        await client.get_workflow_handle(child).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "terminated"}, SUBFLOW_GRANT)
    assert store.starts[child].kind == "subflow"
    end = store.runs[child]
    assert (end.status, end.error_code, end.iterations) == ("failed", "terminated", SUBFLOW_GRANT)


async def test_a_terminated_batch_fails_its_loop_and_its_whole_grant_stays_used(dev_env: WorkflowEnvironment) -> None:
    client, store = dev_env.client, MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none"))
    g.node("l", "flow.loop@1", {"items": list(range(101))}, on_error="continue").node(
        "d", "flow.delay@1", {"duration_s": 3600}
    )
    g.edge("l", "d", "body")
    async with serving(client, store):
        handle = await start(client, store, g, {})
        batch = await child_started(handle)
        await client.get_workflow_handle(batch).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert batch.endswith("/batch:0")
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"code": "terminated"}, 100)


async def test_a_terminated_failure_handler_records_its_end_and_the_runs_stands(dev_env: WorkflowEnvironment) -> None:
    client, store = dev_env.client, MemoryStore()
    g = graph().node("f", "flow.fail@1", {"message": "it went wrong"})
    g.settings["failure_handler"] = str(store.publish(sleeper()))
    async with serving(client, store):
        handle = await start(client, store, g, {})
        handler = await child_started(handle)
        await client.get_workflow_handle(handler).terminate("an operator")
        result = await asyncio.wait_for(handle.result(), 60)
    assert (result.status, result.error["code"] if result.error else None) == ("failed", "workflow_failed")
    assert result.iterations == SUBFLOW_GRANT  # the handler's whole grant: it never reported
    assert store.starts[handler].kind == "failure_handler"
    assert (store.runs[handler].status, store.runs[handler].error_code) == ("failed", "terminated")
    assert store.runs[handle.id].status == "failed"


async def test_temporal_suggesting_continue_as_new_drains_the_run() -> None:
    """The dev server suggests continuing past 100 history events here (Temporal's default is thousands): the run
    drains and continues as new, long before its own thresholds (2,000 and 4,000), and ends as it would have."""
    args = ["--dynamic-config-value", "limit.historyCount.suggestContinueAsNew=100"]
    store = MemoryStore()
    g = graph(items=ref("steps.l.output.items"))
    g.node("l", "flow.loop@1", {"items": list(range(40)), "collect": cel("steps.x.output.value")})
    g.node("x", "testkit.echo@1", {"value": ref("item")}).edge("l", "x", "body")
    async with await WorkflowEnvironment.start_local(dev_server_extra_args=args) as env, serving(env.client, store):
        handle = await start(env.client, store, g, {})
        result = await asyncio.wait_for(handle.result(), 120)
        chain = await executions(env.client, handle.id, handle.first_execution_run_id or "")
    assert (result.status, result.outputs, result.iterations) == ("succeeded", {"items": list(range(40))}, 40)
    assert len(chain) >= 2 and all(len(h.events) < 2_000 for h in chain)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_real_server.py tests/core/runs/test_service.py`
Expected: 4 failed, 14 passed.
- `test_a_terminated_sub_flow_fails_its_step_and_its_row_records_the_end` and
  `test_a_terminated_batch_fails_its_loop_and_its_whole_grant_stays_used`: the step or loop fails with
  `internal_error`, not `terminated`.
- `test_a_terminated_failure_handler_records_its_end_and_the_runs_stands`: a `KeyError`, because nobody wrote the
  handler's end.
- `test_a_parents_write_of_a_childs_end_never_replaces_one`: `TypeError: finish_run() got an unexpected keyword
  argument 'if_running'`.
- `test_temporal_suggesting_continue_as_new_drains_the_run` passes already: 2a-3b drains on Temporal's suggestion,
  and this is its first test on a server that makes one.

- [ ] **Step 3: A run's end that only applies to a running row**

In `backend/src/dewpoint/engine/runtime/activities.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/activities.py b/backend/src/dewpoint/engine/runtime/activities.py
--- a/backend/src/dewpoint/engine/runtime/activities.py
+++ b/backend/src/dewpoint/engine/runtime/activities.py
@@ -188,6 +188,7 @@
     error_code: str | None = None
     error_message: str | None = None
     iterations: int = 0
+    if_running: bool = False  # a parent writing the end of a child that ended without one: never over the child's own


 @dataclass(frozen=True)
@@ -204,6 +205,24 @@
     kind: str  # subflow | failure_handler
     started_at: str

+    @classmethod
+    def of(cls, run: "RunInput", started_at: str) -> "RunStart":
+        """A sub-run's row, from its input: what its own first projection writes, and what its parent writes for it
+        when it ended before writing one."""
+        if run.parent is None or not run.workflow_id:
+            raise ValueError("a root run has no sub-run row")
+        return cls(
+            run_id=run.run_id,
+            workflow_id=run.workflow_id,
+            version_id=run.version_id,
+            mode=run.mode,
+            parent_run_id=run.parent.run_id,
+            parent_step_id=run.parent.step_id or None,
+            parent_iteration_key=run.parent.iteration_key,
+            kind=run.parent.kind,
+            started_at=started_at,
+        )
+

 @dataclass(frozen=True)
 class ProjectInput:
```

In `backend/src/dewpoint/core/runs/service.py`:

```diff
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -122,11 +122,15 @@
     error_code: str | None = None,
     error_message: str | None = None,
     iterations: int = 0,
+    if_running: bool = False,
 ) -> None:
+    """A run's end. `if_running`: only if it has none yet, as when a parent writes the end of a child that was
+    terminated before it could write its own."""
+    query = update(Run).where(Run.id == run_id)
+    if if_running:
+        query = query.where(Run.status == "running")
     await s.execute(
-        update(Run)
-        .where(Run.id == run_id)
-        .values(
+        query.values(
             status=status,
             ended_at=ended_at,
             error_code=sanitize(error_code),
```

In `backend/src/dewpoint/apps/worker/store.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/store.py b/backend/src/dewpoint/apps/worker/store.py
--- a/backend/src/dewpoint/apps/worker/store.py
+++ b/backend/src/dewpoint/apps/worker/store.py
@@ -138,4 +138,5 @@
         error_code=run.error_code,
         error_message=run.error_message,
         iterations=run.iterations,
+        if_running=run.if_running,
     )
```

The test harness's store behaves the same way. In `backend/tests/apps/worker/harness.py`:

```diff
diff --git a/backend/tests/apps/worker/harness.py b/backend/tests/apps/worker/harness.py
--- a/backend/tests/apps/worker/harness.py
+++ b/backend/tests/apps/worker/harness.py
@@ -88,7 +88,7 @@
             self.starts.setdefault(data.start.run_id, data.start)
         for row in data.steps:
             self.rows[(row.run_id, row.step_id, row.iteration_key, row.attempt)] = row
-        if data.run is not None:
+        if data.run is not None and not (data.run.if_running and data.run.run_id in self.runs):
             self.runs[data.run.run_id] = data.run

     def steps(self, run_id: str) -> list[StepRow]:
```

- [ ] **Step 4: The parent writes a terminated child's end**

In `backend/src/dewpoint/engine/runtime/execution.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -20,7 +20,7 @@

 from temporalio import workflow
 from temporalio.common import RetryPolicy
-from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError, TimeoutError
+from temporalio.exceptions import ActivityError, ApplicationError, ChildWorkflowError, TerminatedError, TimeoutError
 from temporalio.exceptions import CancelledError as ActivityCancelled

 with workflow.unsafe.imports_passed_through():
@@ -92,6 +92,7 @@
 DEADLINE_EXCEEDED = "deadline_exceeded"
 VERSION_UNUSABLE = "version_unusable"  # this build can't load or compile the version
 INTERNAL_ERROR = "internal_error"  # an exception in workflow code: a bug
+TERMINATED = "terminated"  # a child ended by an operator, outside Dewpoint: it never reported
 NODE_TYPE_UNAVAILABLE = "node_type_unavailable"  # the registry has it, but this build's workers don't run it
 CANCELLED = Failure("cancelled", "The run was cancelled.")
 AMBIGUOUS = "ambiguous"  # a manifest's side_effect: the request may have been sent
@@ -818,6 +819,7 @@
             drain_events=self.drain_events,
         )
         used: int | None = None  # until it reports, all it was granted counts: it may have run
+        started = workflow.now().isoformat()
         try:
             try:
                 handle = await workflow.start_child_workflow(
@@ -829,8 +831,9 @@
             result = await handle
             used = result.iterations
         except ChildWorkflowError as e:  # it failed as a workflow, which a run never does: a bug, or terminated
-            message = f"The sub-flow ended without a result ({type(e.cause).__name__})."
-            return _Effect(failure=Failure(INTERNAL_ERROR, message), cel_mode=cel_mode)
+            failure = self._lost("sub-flow", e)
+            await self._lost_end(run, started, failure, grant)
+            return _Effect(failure=failure, cel_mode=cel_mode)
         finally:
             self.sched.budget.settle_child(child, used)
             self._dirty = True
@@ -839,6 +842,20 @@
             return _Effect(output=dict(result.outputs or {}), cel_mode=cel_mode)
         error = result.error or {"code": result.status, "message": f"The sub-flow ended {result.status}."}
         return _Effect(failure=Failure(str(error["code"]), str(error["message"])), cel_mode=cel_mode)
+
+    @staticmethod
+    def _lost(kind: str, e: ChildWorkflowError) -> Failure:
+        """A child that ended without a result: terminated from outside Dewpoint, or failed as a workflow (a bug)."""
+        if isinstance(e.cause, TerminatedError):
+            return Failure(TERMINATED, f"The {kind} was terminated outside Dewpoint.")
+        return Failure(INTERNAL_ERROR, f"The {kind} ended without a result ({type(e.cause).__name__}).")
+
+    async def _lost_end(self, run: RunInput, started_at: str, failure: Failure, grant: int) -> None:
+        """A sub-run that ended without a result never wrote its end: its row would stay `running`, holding its
+        references (spec §4.5). Its parent writes it, unless it has one, with its whole grant, as counted here. It
+        writes the row too, in case the child was ended before its own: a start written later changes nothing."""
+        end = RunSummary(run.run_id, "failed", workflow.now().isoformat(), failure.code, failure.message, grant, True)
+        await self._shielded([], end, RunStart.of(run, started_at))

     def _outer(self, loop: Instance) -> list[dict[str, Any]]:
         """The loop's enclosing scopes as its batch reads them, outermost first: the results its body can
@@ -907,7 +924,7 @@
             cause = e.cause
             if isinstance(cause, ApplicationError) and cause.type in (VERSION_UNUSABLE, INTERNAL_ERROR):
                 return _Effect(failure=Failure(cause.type, cause.message))
-            return _Effect(failure=Failure(INTERNAL_ERROR, "The batch ended without a result."))
+            return _Effect(failure=self._lost("batch", e))
         finally:
             self.sched.budget.settle_child(child, used)
             self._dirty = True
```

In `backend/src/dewpoint/engine/runtime/workflow.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -114,7 +114,7 @@
             message = "This build can't read the run's continue-as-new snapshot."
             return await self._end_early(RunEnd("failed", Failure(INTERNAL_ERROR, message)))
         if start.parent is not None and snapshot is None:  # its row first: whatever ends it now has a row to end
-            if await self._shielded([], None, self._start_row(start.parent, start.workflow_id, started)):
+            if await self._shielded([], None, RunStart.of(start, started.isoformat())):
                 return await self._cancelled_early()  # cancelled while the row was written
         try:
             data = await workflow.execute_local_activity(
@@ -187,19 +187,6 @@
         self.vars = {k: p.get("default") for k, p in sorted(schema.get("properties", {}).items())}
         self.sched.start()

-    def _start_row(self, parent: Parent, workflow_id: str, started: datetime) -> RunStart:
-        return RunStart(
-            run_id=self.run_id,
-            workflow_id=workflow_id,
-            version_id=self.version_id,
-            mode=self.mode,
-            parent_run_id=parent.run_id,
-            parent_step_id=parent.step_id or None,
-            parent_iteration_key=parent.iteration_key,
-            kind=parent.kind,
-            started_at=started.isoformat(),
-        )
-
     async def _outputs_by(self, end: RunEnd) -> tuple[RunEnd, dict[str, Any] | None]:
         """The workflow's outputs, within the run's deadline. Past it, their evaluation is cancelled and the run ends
         `deadline_exceeded`; an output that can't be computed fails the run with its code."""
@@ -322,7 +309,7 @@
             checkpoint_events=self.checkpoint_events,
             drain_events=self.drain_events,
         )
-        handler = asyncio.create_task(self._handler(run, child))
+        handler = asyncio.create_task(self._handler(run, child, grant))
         while not handler.done():  # it draws its iterations from this run: answer as it asks
             wake = asyncio.create_task(workflow.wait_condition(lambda: bool(self._mail or self._answers)))
             try:
@@ -335,14 +322,17 @@
         self.sched.budget.settle_child(child, None if handler.cancelled() else handler.result())
         await self._send_signals()

-    async def _handler(self, run: RunInput, child: str) -> int | None:
-        """The failure handler's run: the iterations it used, or None when it ended without saying."""
+    async def _handler(self, run: RunInput, child: str, grant: int) -> int | None:
+        """The failure handler's run: the iterations it used, or None when it ended without saying (its end is then
+        written here, as a sub-flow's is)."""
+        started = workflow.now().isoformat()
         try:
             result: RunResult = await workflow.execute_child_workflow(
                 "RunGraph", run, result_type=RunResult, **child_options(child)
             )
-        except ChildWorkflowError:
+        except ChildWorkflowError as e:
             workflow.logger.warning("failure_handler_failed", exc_info=True)
+            await self._lost_end(run, started, self._lost("failure handler", e), grant)
             return None
         return result.iterations

```

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_real_server.py tests/core/runs/test_service.py`
Expected: 18 passed.

- [ ] **Step 6: Document the error code**

In `docs/operations/runs.md`:

```diff
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -128,13 +128,15 @@
 | `failed` | `start_failed` | Temporal refused to start it. |
 | `failed` | `version_unusable` | This build can't load or run the version, for example a node type it lacks. Nothing ran. |
 | `failed` | `internal_error` | A bug in the interpreter. The message names the exception's type, and the worker's log has the details; please report it. |
+| `failed` | `terminated` | A sub-run that an operator terminated in Temporal. It couldn't record its end, so its parent did, and the step or loop that started it failed with the same code. |
 | `deadline_exceeded` | `deadline_exceeded` | The run passed `DEWPOINT_MAX_RUN_DURATION_DAYS` (default 30). Running steps were cancelled. |
 | `cancelled` | `cancelled` | The run was cancelled in Temporal. A cancel that arrives while the run's end is being written leaves that end. |

 Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation`, `unexpected_error`,
 `evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`, `item_cap_exceeded`,
 `iteration_cap_exceeded` and `node_type_unavailable` (the registry lists the node type, but no worker of this build
-runs it: install its plugin on the workers). A sub-flow step fails with its sub-flow's code.
+runs it: install its plugin on the workers). A sub-flow step fails with its sub-flow's code, and with `terminated`
+when an operator terminated the sub-flow; a loop fails with `terminated` when one of its batches was.

 ## Attempts and retries

```

- [ ] **Step 7: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src tests ../docs/operations/runs.md \
  && git commit -m "feat(engine): a terminated sub-run's end is written by its parent" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,037 passed and 8 skipped.

---

### Task 6: Compose's `temporal` and `worker`, and the rollout guide

Compose gains Temporal's dev server and the engine worker (decision 11):
- **`temporal`:** `temporalio/temporal:1.9.1` running `server start-dev`, with its state in SQLite on the
  `temporal-data` volume. The volume is mounted at `/home/temporal`, which the image's user (uid 1000) owns. The
  container is read-only, with a tmpfs `/tmp` and every capability dropped. The Web UI is on
  `127.0.0.1:8233`, and the health check is `temporal operator cluster health`.
- **`worker`:** the Dewpoint image running `dewpoint worker`. It logs in as `dewpoint_worker_login`, reaches Temporal
  at `temporal:7233` and the evaluator through its socket, and gets 45 s to stop. It waits for the migrations,
  Temporal and the evaluator. It sets `DEWPOINT_WORKER_SET_CURRENT=true`: Compose runs one build at a time, so its
  worker makes its own build current once it polls.
- **`initdb`** creates `dewpoint_worker_login` and `dewpoint_dispatch_login` on a fresh install. The guide gives the
  two statements for an install whose database predates them.

`Settings.worker_set_current` (default off) runs `promote(client)` beside the workers: `set_current` for this build,
waiting up to 120 s. The test runs the worker's `main.run` against the dev server, with stand-ins for the database
and the plugins.

CI's end-to-end job generates the two new passwords, and checks that the worker's build becomes current.

The new `docs/operations/deployment.md` covers builds and versions, rolling out a new build, rolling back, and
Compose. Planning ran the `temporal` service on its own (healthy, the Web UI answering, and its state surviving a
restart). The full stack's `worker` container runs only in CI, because the app image's base images are approved
for the evaluator only.

**Files:**
- Modify: `backend/src/dewpoint/core/config.py`, `backend/src/dewpoint/apps/worker/main.py`
- Modify: `backend/tests/apps/worker/test_deployment.py`
- Modify: `deploy/compose/docker-compose.yml`, `deploy/compose/initdb/10-roles.sh`, `deploy/compose/.env.example`
- Modify: `.github/workflows/ci.yml`
- Create: `docs/operations/deployment.md`
- Modify: `docs/operations/runs.md`, `README.md`

**Interfaces:**
- Consumes: Task 3's `set_current`, `this_build`, `describe` and `dev_env`.
- Produces: `Settings.worker_set_current: bool = False` (`DEWPOINT_WORKER_SET_CURRENT`), and
  `async main.promote(client) -> None`.

- [ ] **Step 1: Write the failing test**

In `backend/tests/apps/worker/test_deployment.py`:

```diff
diff --git a/backend/tests/apps/worker/test_deployment.py b/backend/tests/apps/worker/test_deployment.py
--- a/backend/tests/apps/worker/test_deployment.py
+++ b/backend/tests/apps/worker/test_deployment.py
@@ -4,6 +4,7 @@
 deployment's current build."""

 import asyncio
+import contextlib
 import uuid
 from dataclasses import dataclass

@@ -14,8 +15,9 @@
 from temporalio.testing import WorkflowEnvironment
 from temporalio.worker import Worker

+from dewpoint.apps.worker import main
 from dewpoint.apps.worker.activities import cel_activity
-from dewpoint.apps.worker.deployment import describe, set_current
+from dewpoint.apps.worker.deployment import describe, set_current, this_build
 from dewpoint.apps.worker.main import engine_worker
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
@@ -128,3 +130,32 @@
             ran = placement(history)
             assert ran.builds == {expected} and ran.engine <= {expected}, (history.workflow_id, ran)
             assert ran.behaviours == {VersioningBehavior.VERSIONING_BEHAVIOR_PINNED}
+
+
+async def test_a_worker_set_to_makes_its_build_current_once_it_polls(
+    dev_env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """Compose runs one build at a time: its worker (DEWPOINT_WORKER_SET_CURRENT) promotes its own build, so new runs
+    start on it. Here the database and the plugins are stand-ins: no run starts."""
+
+    class Engine:
+        async def dispose(self) -> None: ...
+
+    async def connect(*args: object, **kwargs: object) -> Client:
+        return dev_env.client
+
+    monkeypatch.setattr(main.Client, "connect", connect)
+    monkeypatch.setattr(main, "make_engine", lambda url: Engine())
+    monkeypatch.setattr(main, "make_sessionmaker", lambda engine: None)
+    monkeypatch.setattr(main, "installed_plugins", lambda: [TESTKIT])
+    worker = asyncio.create_task(main.run(settings(worker_set_current=True, worker_shutdown_grace_s=0.1)))
+    try:
+        for _ in range(60):
+            if (await describe(dev_env.client)).current == this_build():
+                break
+            await asyncio.sleep(0.5)
+        assert (await describe(dev_env.client)).current == this_build()
+    finally:
+        worker.cancel()
+        with contextlib.suppress(asyncio.CancelledError):
+            await worker
```

- [ ] **Step 2: Run it and watch it fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_deployment.py`
Expected: 1 failed, 2 passed. `test_a_worker_set_to_makes_its_build_current_once_it_polls` fails: the current build is
still the one an earlier test made current (`assert 'new-…' == 'dewpoint-0.1.0+abi2'`), because nothing promotes
this build.

- [ ] **Step 3: The setting, and the worker that promotes its build**

In `backend/src/dewpoint/core/config.py`:

```diff
diff --git a/backend/src/dewpoint/core/config.py b/backend/src/dewpoint/core/config.py
--- a/backend/src/dewpoint/core/config.py
+++ b/backend/src/dewpoint/core/config.py
@@ -33,6 +33,9 @@
     cel_max_concurrent: int = 2  # the evaluator's N (docs/operations/cel-evaluator.md)
     cel_schedule_to_start_s: float = 600  # spec §5.7: no evaluator for a profile after this: cel_profile_unavailable
     worker_shutdown_grace_s: float = 30  # a stopping worker lets running attempts finish this long, then cancels them
+    # One build at a time (Compose): the worker makes its build the one new runs start on, once it polls. Leave it off
+    # where builds overlap, and promote each with `dewpoint deployment set-current` (docs/operations/deployment.md).
+    worker_set_current: bool = False
     audit_signing_key_b64: str | None = None  # Ed25519 private key (raw 32 bytes, base64)
     audit_anchor_path: str | None = None

```

In `backend/src/dewpoint/apps/worker/main.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/main.py b/backend/src/dewpoint/apps/worker/main.py
--- a/backend/src/dewpoint/apps/worker/main.py
+++ b/backend/src/dewpoint/apps/worker/main.py
@@ -15,7 +15,7 @@
 from dewpoint.apps import cel_client
 from dewpoint.apps.plugin_loader import installed_plugins
 from dewpoint.apps.worker.activities import RunStore, cel_activity, engine_activities, remote_evaluator
-from dewpoint.apps.worker.deployment import deployment_config, this_build
+from dewpoint.apps.worker.deployment import deployment_config, set_current, this_build
 from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.core.config import Settings
 from dewpoint.core.db import make_engine, make_sessionmaker
@@ -68,6 +68,12 @@
     )


+async def promote(client: Client) -> None:
+    """This build becomes current once its version exists: as soon as the engine worker polls."""
+    await set_current(client, this_build(), wait_s=120)
+    log.info("deployment_current", build=this_build())
+
+
 async def run(settings: Settings) -> None:
     client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
     engine = make_engine(settings.database_url)
@@ -77,6 +83,9 @@
             profile = await evaluator_profile(settings.cel_socket)
             log.info("cel_queue", profile=profile)
             workers.append(cel_worker(client, settings.cel_socket, profile, max_concurrent=settings.cel_max_concurrent))
-        await asyncio.gather(*(w.run() for w in workers))
+        tasks = [w.run() for w in workers]
+        if settings.worker_set_current:
+            tasks.append(promote(client))
+        await asyncio.gather(*tasks)
     finally:
         await engine.dispose()
```

- [ ] **Step 4: Run the test**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_deployment.py`
Expected: 3 passed.

- [ ] **Step 5: Compose**

In `deploy/compose/docker-compose.yml`:

```diff
diff --git a/deploy/compose/docker-compose.yml b/deploy/compose/docker-compose.yml
--- a/deploy/compose/docker-compose.yml
+++ b/deploy/compose/docker-compose.yml
@@ -26,6 +26,8 @@
       DEWPOINT_API_DB_PASSWORD: ${DEWPOINT_API_DB_PASSWORD:?set in .env}
       DEWPOINT_ADMIN_DB_PASSWORD: ${DEWPOINT_ADMIN_DB_PASSWORD:?set in .env}
       DEWPOINT_AUDITOR_DB_PASSWORD: ${DEWPOINT_AUDITOR_DB_PASSWORD:?set in .env}
+      DEWPOINT_WORKER_DB_PASSWORD: ${DEWPOINT_WORKER_DB_PASSWORD:?set in .env}
+      DEWPOINT_DISPATCH_DB_PASSWORD: ${DEWPOINT_DISPATCH_DB_PASSWORD:?set in .env}
     volumes: [pgdata:/var/lib/postgresql/data, ./initdb:/docker-entrypoint-initdb.d:ro]
     healthcheck: { test: ["CMD-SHELL", "pg_isready -U dewpoint_owner -d dewpoint"], interval: 5s, retries: 20 }

@@ -73,11 +75,45 @@
     volumes: [anchors:/anchors]
     depends_on: { migrate: { condition: service_completed_successfully } }

+  temporal:
+    # Temporal's dev server: one container, its state in SQLite on a volume. For evaluation: production runs a
+    # Temporal cluster (docs/operations/deployment.md). Its Web UI is on this host only.
+    image: temporalio/temporal:1.9.1
+    command: ["server", "start-dev", "--ip", "0.0.0.0", "--ui-ip", "0.0.0.0", "--db-filename", "/home/temporal/temporal.db"]
+    read_only: true
+    tmpfs: [/tmp]
+    security_opt: ["no-new-privileges:true"]
+    cap_drop: [ALL]
+    volumes: [temporal-data:/home/temporal]  # the image's user owns its home: the new volume takes that ownership
+    ports: ["127.0.0.1:8233:8233"]
+    healthcheck:
+      test: ["CMD", "temporal", "operator", "cluster", "health", "--address", "127.0.0.1:7233"]
+      interval: 5s
+      retries: 30
+
+  worker:
+    <<: *app
+    command: ["dewpoint", "worker"]
+    environment:
+      <<: *appenv
+      DEWPOINT_DATABASE_URL: postgresql+asyncpg://dewpoint_worker_login:${DEWPOINT_WORKER_DB_PASSWORD}@postgres/dewpoint
+      DEWPOINT_TEMPORAL_ADDRESS: temporal:7233
+      DEWPOINT_CEL_SOCKET: /run/dewpoint-cel/cel.sock
+      DEWPOINT_CEL_MAX_CONCURRENT: "2"  # the evaluator's slots at 2 CPUs (docs/operations/cel-evaluator.md)
+      # Compose runs one build at a time: the worker makes its build current (docs/operations/deployment.md).
+      DEWPOINT_WORKER_SET_CURRENT: "true"
+    volumes: [cel-socket:/run/dewpoint-cel]
+    stop_grace_period: 45s  # longer than DEWPOINT_WORKER_SHUTDOWN_GRACE_S (30 s): running attempts finish
+    depends_on:
+      migrate: { condition: service_completed_successfully }
+      temporal: { condition: service_healthy }
+      cel-evaluator: { condition: service_healthy }
+
   cel-evaluator:
     image: ${DEWPOINT_CEL_EVALUATOR_IMAGE:-dewpoint-cel-evaluator:dev}
     build: { context: ../.., dockerfile: deploy/docker/cel-evaluator.Dockerfile }
-    # Secretless and egress-free (spec §5.7): no network at all, no environment beyond its own settings. The CEL
-    # activity worker (2a-3) reaches it through the socket on the `cel-socket` volume, which only the two mount.
+    # Secretless and egress-free (spec §5.7): no network at all, no environment beyond its own settings. The worker
+    # reaches it through the socket on the `cel-socket` volume, which only the two mount.
     network_mode: none
     read_only: true
     tmpfs: [/tmp]
@@ -105,4 +141,4 @@
       DEWPOINT_TRUSTED_PROXIES: ${DEWPOINT_TRUSTED_PROXIES:-}
     depends_on: { api: { condition: service_healthy } }

-volumes: { pgdata: {}, anchors: {}, cel-socket: {} }
+volumes: { pgdata: {}, anchors: {}, cel-socket: {}, temporal-data: {} }
```

In `deploy/compose/initdb/10-roles.sh`:

```diff
diff --git a/deploy/compose/initdb/10-roles.sh b/deploy/compose/initdb/10-roles.sh
--- a/deploy/compose/initdb/10-roles.sh
+++ b/deploy/compose/initdb/10-roles.sh
@@ -3,13 +3,18 @@
 set -eu
 psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
   -v api_pw="$DEWPOINT_API_DB_PASSWORD" -v admin_pw="$DEWPOINT_ADMIN_DB_PASSWORD" \
-  -v auditor_pw="$DEWPOINT_AUDITOR_DB_PASSWORD" <<'SQL'
+  -v auditor_pw="$DEWPOINT_AUDITOR_DB_PASSWORD" -v worker_pw="$DEWPOINT_WORKER_DB_PASSWORD" \
+  -v dispatch_pw="$DEWPOINT_DISPATCH_DB_PASSWORD" <<'SQL'
 DO $$ BEGIN
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_api') THEN CREATE ROLE dewpoint_api NOLOGIN; END IF;
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_admin') THEN CREATE ROLE dewpoint_admin NOLOGIN; END IF;
   IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_auditor') THEN CREATE ROLE dewpoint_auditor NOLOGIN; END IF;
+  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_worker') THEN CREATE ROLE dewpoint_worker NOLOGIN; END IF;
+  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='dewpoint_dispatch') THEN CREATE ROLE dewpoint_dispatch NOLOGIN; END IF;
 END $$;
 CREATE ROLE dewpoint_api_login LOGIN PASSWORD :'api_pw' IN ROLE dewpoint_api;
 CREATE ROLE dewpoint_admin_login LOGIN PASSWORD :'admin_pw' IN ROLE dewpoint_admin;
 CREATE ROLE dewpoint_auditor_login LOGIN PASSWORD :'auditor_pw' IN ROLE dewpoint_auditor;
+CREATE ROLE dewpoint_worker_login LOGIN PASSWORD :'worker_pw' IN ROLE dewpoint_worker;
+CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD :'dispatch_pw' IN ROLE dewpoint_dispatch;
 SQL
```

In `deploy/compose/.env.example`:

```diff
diff --git a/deploy/compose/.env.example b/deploy/compose/.env.example
--- a/deploy/compose/.env.example
+++ b/deploy/compose/.env.example
@@ -3,6 +3,8 @@
 DEWPOINT_API_DB_PASSWORD=     # openssl rand -base64 24
 DEWPOINT_ADMIN_DB_PASSWORD=   # openssl rand -base64 24  (key-management CLI: dewpoint keys …)
 DEWPOINT_AUDITOR_DB_PASSWORD= # openssl rand -base64 24  (audit anchor/verify only)
+DEWPOINT_WORKER_DB_PASSWORD=  # openssl rand -base64 24  (the worker: runs and their steps)
+DEWPOINT_DISPATCH_DB_PASSWORD= # openssl rand -base64 24  (starting runs: dewpoint dev run)
 DEWPOINT_KEK_B64=             # openssl rand -base64 32
 DEWPOINT_AUDIT_SIGNING_KEY_B64=  # python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
 DEWPOINT_PUBLIC_ORIGIN=http://localhost:8080
```

Check the file, and bring up `temporal` alone. The only image this pulls is the approved
`temporalio/temporal:1.9.1`. The project name keeps the check apart from any Compose stack you run:

```bash
cd deploy/compose \
  && for v in POSTGRES_PASSWORD DEWPOINT_API_DB_PASSWORD DEWPOINT_ADMIN_DB_PASSWORD DEWPOINT_AUDITOR_DB_PASSWORD \
       DEWPOINT_WORKER_DB_PASSWORD DEWPOINT_DISPATCH_DB_PASSWORD DEWPOINT_KEK_B64 DEWPOINT_AUDIT_SIGNING_KEY_B64; do
       echo "$v=check"; done > .env.check \
  && docker compose -p dewpoint-check --env-file .env.check config -q \
  && docker compose -p dewpoint-check --env-file .env.check up -d --wait temporal \
  && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8233; \
  docker compose -p dewpoint-check --env-file .env.check down -v; rm -f .env.check
```

Expected: `config` prints nothing, the `temporal` container reports `Healthy`, and the Web UI answers `200`. The
`down` removes the container, its volume and its network.

- [ ] **Step 6: The end-to-end job**

In `.github/workflows/ci.yml`:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -69,6 +69,8 @@
             echo "DEWPOINT_API_DB_PASSWORD=$(openssl rand -hex 16)"
             echo "DEWPOINT_ADMIN_DB_PASSWORD=$(openssl rand -hex 16)"
             echo "DEWPOINT_AUDITOR_DB_PASSWORD=$(openssl rand -hex 16)"
+            echo "DEWPOINT_WORKER_DB_PASSWORD=$(openssl rand -hex 16)"
+            echo "DEWPOINT_DISPATCH_DB_PASSWORD=$(openssl rand -hex 16)"
             echo "DEWPOINT_KEK_B64=$(openssl rand -base64 32)"
             echo "DEWPOINT_AUDIT_SIGNING_KEY_B64=$(openssl rand -base64 32)"
           } > .env
@@ -79,6 +81,15 @@
           docker compose run --rm -e DEWPOINT_INIT_PASSWORD=violet-otter-canyon-42 \
             -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_api_login:${DEWPOINT_API_DB_PASSWORD}@postgres/dewpoint" \
             api dewpoint admin init --email admin@example.com
+      - name: The worker's build is current
+        working-directory: deploy/compose
+        run: |
+          for _ in $(seq 60); do
+            docker compose exec -T worker dewpoint deployment status | tee status.txt
+            grep -q '^current: dewpoint-' status.txt && exit 0
+            sleep 2
+          done
+          exit 1
       - uses: pnpm/action-setup@b906affcce14559ad1aafd4ab0e942779e9f58b1 # v4  (version comes from package.json "packageManager")
         with: { package_json_file: frontend/package.json }
       - uses: actions/setup-node@v4
```

- [ ] **Step 7: The rollout guide**

Create `docs/operations/deployment.md`:

````markdown
# Deploying builds: Temporal and the engine worker

Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §7.

A run is **pinned** to the build it started on. Its sub-flows, its loop batches and the runs it continues as finish
on that build too, even after a newer build takes over. That's what lets a new build change how runs execute without
breaking the runs already going.

## Builds and versions

- Each build of Dewpoint has a build ID, `dewpoint-<version>+abi<engine ABI>`, for example `dewpoint-0.1.0+abi3`. The
  engine ABI changes whenever a build could execute a workflow differently, so such a build always has a new ID.
- Every engine worker joins one Temporal **Worker Deployment**, `dewpoint-engine`, as its build's version.
- New runs start on the deployment's **current** version. Nothing becomes current by itself: making a build current
  is the step that switches new runs to it.
- The `cel.evaluate` queues (`dewpoint-cel.<profile>`) are outside the deployment: an expression goes to an evaluator
  serving its version's CEL profile, whatever the build ([`cel-evaluator.md`](cel-evaluator.md)).

`dewpoint deployment status` shows the current build and every version Temporal knows:

```text
current: dewpoint-0.1.0+abi3
dewpoint-0.1.0+abi2  draining
dewpoint-0.1.0+abi3  current
```

A `draining` version still has runs pinned to it. A `drained` one has none left.

## Rolling out a new build

1. Run `dewpoint plugins sync` with the new build, as on every deploy
   ([`plugin-lifecycle.md`](plugin-lifecycle.md)).
2. Start the new build's workers **next to** the old ones.
3. From the new build, run `dewpoint deployment set-current`. It waits (up to `--wait` seconds, default 60) until one
   of the new build's workers has polled, then makes that build current. `--build-id` names another build.
4. Watch `dewpoint deployment status`. Stop the old build's workers only once its version reports `drained`.

Stopping them earlier doesn't lose runs, but it stalls them: a pinned run waits, durably, until a worker of its own
build polls again. Temporal's Web UI lists the runs still pinned to a version.

To roll back, make the old build current again while its workers still run: `dewpoint deployment set-current
--build-id <old build ID>`. Runs that started on the new build stay on it.

A node type the new build no longer ships must be retired first ([`plugin-lifecycle.md`](plugin-lifecycle.md)). The
old build's runs that still use it finish on the old build's workers, which still have it.

## Docker Compose (evaluation)

Compose runs Temporal's dev server (the `temporal` service: its state in SQLite on the `temporal-data` volume, its Web
UI at <http://127.0.0.1:8233>) and one `worker`. Production uses a Temporal cluster instead.

Compose runs one build at a time, so its worker makes its own build current as it starts
(`DEWPOINT_WORKER_SET_CURRENT=true`). Replacing the `worker` container with a new image removes the old build's only
worker: **let runs end before upgrading**, or their build's worker must come back for them to finish. Leave the setting
off wherever builds overlap.

The worker and `dewpoint dev run` log in as `dewpoint_worker_login` and `dewpoint_dispatch_login`
(`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`). A fresh install creates both. An install whose
database predates them creates them once, as the database owner:

```sql
CREATE ROLE dewpoint_worker_login LOGIN PASSWORD '<worker password>' IN ROLE dewpoint_worker;
CREATE ROLE dewpoint_dispatch_login LOGIN PASSWORD '<dispatch password>' IN ROLE dewpoint_dispatch;
```
````

In `docs/operations/runs.md`:

```diff
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -26,13 +26,24 @@
 - `DEWPOINT_WORKER_SHUTDOWN_GRACE_S` (default 30): a stopping worker lets running attempts finish this long, then
   cancels them. A cancelled attempt ends as on a lost worker: `outcome_unknown` for an `ambiguous` node. Give the
   process manager a stop timeout longer than this.
+- `DEWPOINT_WORKER_SET_CURRENT` (default off): the worker makes its own build the one new runs start on. Only where
+  one build runs at a time, as in Docker Compose; elsewhere, promote builds with `dewpoint deployment set-current`
+  ([`deployment.md`](deployment.md)).
+
+This build evaluates CEL of its own profile in the workflow: an expression that publish classified as inline, on
+values within the caps (64 KiB, 200 list elements or map entries, 16 KiB strings), runs in-process, and its step's
+`cel_mode` says `local`. Everything else goes to the evaluator (`cel_mode` `activity`): what publish classified as
+"Runs as a separate step", values past the caps, and a filter over more than 1,000 items (in requests of 1,000). A
+workflow task does a bounded amount of CEL work, binding included; past it, the run yields to the next task with a 1 ms
+timer, so no task runs long enough to time out.

 Without an evaluator, CEL expressions that can't run inline wait `DEWPOINT_CEL_SCHEDULE_TO_START_S` (default 600
 seconds) and then fail the step with `cel_profile_unavailable`. In 2a every CEL expression runs through the evaluator:
 inline evaluation is switched on by plan 2a-3c, together with the build's `ENGINE_ABI`.

-Docker Compose gains `temporal` and `worker` services, and the worker and dispatch logins, in plan 2a-3c. Until then,
-point the worker at any Temporal server.
+The engine worker is its build's version of the `dewpoint-engine` Worker Deployment, and a run finishes on the build it
+started on. Rolling out a build, and what Docker Compose runs (Temporal's dev server and one worker):
+[`deployment.md`](deployment.md).

 ## Starting a development run

```

In `README.md`:

```diff
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -48,7 +48,9 @@

 Until sub-project 2b brings triggers, runs start only from `dewpoint dev run` and the tests; `dewpoint worker` executes
 them on Temporal. Settings, how a run ends, and this build's limits:
-[`docs/operations/runs.md`](docs/operations/runs.md).
+[`docs/operations/runs.md`](docs/operations/runs.md). Compose runs Temporal's dev server (Web UI at
+<http://127.0.0.1:8233>) and one worker; rolling out a new build, and upgrading Compose:
+[`docs/operations/deployment.md`](docs/operations/deployment.md).

 ## Audit integrity

```

- [ ] **Step 8: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src/dewpoint/core/config.py src/dewpoint/apps/worker/main.py tests/apps/worker/test_deployment.py \
       ../deploy/compose ../.github ../docs/operations ../README.md \
  && git commit -m "feat(deploy): Compose runs Temporal's dev server and the engine worker" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,038 passed and 8 skipped.

---

### Task 7: The replay gate

The replay gate has two halves (decision 12):
- **The suite** replays every history of this build's `ENGINE_ABI`, in every build directory of that ABI. A new
  version of Dewpoint that keeps the ABI then replays the previous version's histories too. A history's test id is
  its name in this build's directory, and `<directory>/<name>` in another.
- **CI** checks what changed in the replay directory since the base. It fails when a recorded history was changed or
  removed (a rename counts as a removal), or when a new history went into a directory other than this build's.
  `tests/engine/replay/gate.py` does it, from `git diff --name-status --no-renames <base>...HEAD`. CI's checkout
  fetches the whole history so that the base is there. The base is the pull request's base, or the pushed range's
  start, or `origin/main`.

**Files:**
- Create: `backend/tests/engine/replay/gate.py`, `backend/tests/engine/replay/test_gate.py`
- Modify: `backend/tests/engine/replay/test_replay.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: 2a-3b's `record.HERE` and `record.build_dir()`, and `dewpoint.engine.ENGINE_ABI`.
- Produces: `gate.REPLAY = "backend/tests/engine/replay/"`, `gate.problems(changes: list[tuple[str, str]],
  current: str) -> list[str]`, `gate.changes(base: str, repo: Path = REPO) -> list[tuple[str, str]]`, and
  `python -m tests.engine.replay.gate <base>` (exit 1 when it prints a problem).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/engine/replay/test_gate.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The replay gate's history check (spec §7): recorded histories are never changed or removed, and new ones go only
into this build's directory."""

import subprocess
from pathlib import Path

from tests.engine.replay.gate import REPLAY, changes, problems

THIS = "dewpoint-0.1.0+abi3"


def test_a_recorded_history_is_never_changed_or_removed() -> None:
    found = problems([("M", f"{REPLAY}dewpoint-0.1.0+abi2/loops.json"), ("D", f"{REPLAY}{THIS}/drain.json")], THIS)
    assert found == [
        f"{REPLAY}dewpoint-0.1.0+abi2/loops.json: a recorded history is never changed or removed (M)",
        f"{REPLAY}{THIS}/drain.json: a recorded history is never changed or removed (D)",
    ]


def test_new_histories_go_into_this_builds_directory_only() -> None:
    assert problems([("A", f"{REPLAY}{THIS}/grants.json")], THIS) == []
    older, unknown = f"{REPLAY}dewpoint-0.1.0+abi2/new.json", f"{REPLAY}dewpoint-0.1.0+abi9/new.json"
    assert problems([("A", older), ("A", unknown)], THIS) == [
        f"{older}: new histories go into this build's directory, {THIS}",
        f"{unknown}: new histories go into this build's directory, {THIS}",
    ]


def test_the_recorder_and_the_scenarios_may_change() -> None:
    assert (
        problems([("M", f"{REPLAY}scenarios.py"), ("M", f"{REPLAY}test_replay.py"), ("A", f"{REPLAY}x.md")], THIS) == []
    )


def test_changes_are_read_from_git_since_the_base_and_a_rename_is_a_removal(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True).stdout

    git("init", "-q", "-b", "main")
    git("config", "user.email", "gate@example.test")
    git("config", "user.name", "gate")
    old = tmp_path / REPLAY / "dewpoint-0.1.0+abi2"
    old.mkdir(parents=True)
    (old / "loops.json").write_text("{}")
    (old / "errors.json").write_text("{}")
    git("add", ".")
    git("commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD").strip()
    (old / "loops.json").write_text('{"rewritten": true}')
    (old / "errors.json").rename(old / "errors-renamed.json")
    git("add", "-A")
    git("commit", "-q", "-m", "change")
    assert sorted(changes(base, tmp_path)) == [
        ("A", f"{REPLAY}dewpoint-0.1.0+abi2/errors-renamed.json"),
        ("D", f"{REPLAY}dewpoint-0.1.0+abi2/errors.json"),
        ("M", f"{REPLAY}dewpoint-0.1.0+abi2/loops.json"),
    ]
```

In `backend/tests/engine/replay/test_replay.py`, replay every directory of this ABI:

```diff
diff --git a/backend/tests/engine/replay/test_replay.py b/backend/tests/engine/replay/test_replay.py
--- a/backend/tests/engine/replay/test_replay.py
+++ b/backend/tests/engine/replay/test_replay.py
@@ -1,6 +1,7 @@
 # SPDX-License-Identifier: Apache-2.0
-"""This build's golden histories replay against this build's workflows (spec §7): every execution a scenario ran,
-its continued runs and its children included. The Replayer needs no server."""
+"""The golden histories of this build's ABI replay against this build's workflows (spec §7): every execution a
+scenario ran, its continued runs and its children included. A build that keeps the ABI (a new version) must replay
+the previous build's histories too. The Replayer needs no server."""

 import asyncio
 import re
@@ -10,15 +11,16 @@
 from temporalio.client import WorkflowHistory
 from temporalio.worker import Replayer

+from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
-from tests.engine.replay.record import build_dir
+from tests.engine.replay.record import HERE, build_dir
 from tests.engine.replay.scenarios import scenarios

-HISTORIES = sorted(build_dir().glob("*.json"))
+HISTORIES = sorted(HERE.glob(f"*+abi{ENGINE_ABI}/*.json"))


 def test_every_scenario_is_recorded_for_this_build() -> None:
-    recorded = {p.stem.split("--")[0] for p in HISTORIES}
+    recorded = {p.stem.split("--")[0] for p in build_dir().glob("*.json")}
     assert recorded == set(scenarios()), "run `uv run python -m tests.engine.replay.record`"


@@ -29,7 +31,9 @@
         assert not re.search(r'"stackTrace": "[^"]', text), path.name


-@pytest.mark.parametrize("path", HISTORIES, ids=lambda p: p.stem)
+@pytest.mark.parametrize(
+    "path", HISTORIES, ids=lambda p: p.stem if p.parent == build_dir() else f"{p.parent.name}/{p.stem}"
+)
 async def test_a_golden_history_replays(path: Path) -> None:
     history = WorkflowHistory.from_json(path.stem, await asyncio.to_thread(path.read_text))
     await Replayer(workflows=[RunGraph, LoopBatch]).replay_workflow(history)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/replay`
Expected: 1 error during collection: `ModuleNotFoundError: No module named 'tests.engine.replay.gate'`.

- [ ] **Step 3: The history check**

Create `backend/tests/engine/replay/gate.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The replay gate's history check (spec §7): `uv run python -m tests.engine.replay.gate <base>`.

A recorded history is never changed or removed: a run of its build may still be open, and must replay. New histories
go only into this build's directory, so a new directory appears only with a new build ID (a new `ENGINE_ABI`, or a
new version). Replaying them is the suite's part (test_replay.py): every directory of this build's ABI."""

import subprocess
import sys
from pathlib import Path

from tests.engine.replay.record import build_dir

REPO = Path(__file__).parents[4]
REPLAY = "backend/tests/engine/replay/"


def problems(changes: list[tuple[str, str]], current: str) -> list[str]:
    """What breaks the rules, one line each. `changes`: the replay directory's changes since the base, as git names
    them (status, path); `current`: this build's directory."""
    out: list[str] = []
    for status, path in changes:
        parts = path.removeprefix(REPLAY).split("/")
        if len(parts) != 2 or not parts[1].endswith(".json"):
            continue  # not a history: the recorder, the scenarios, the tests
        if not status.startswith("A"):
            out.append(f"{path}: a recorded history is never changed or removed ({status})")
        elif parts[0] != current:
            out.append(f"{path}: new histories go into this build's directory, {current}")
    return out


def changes(base: str, repo: Path = REPO) -> list[tuple[str, str]]:
    """The replay directory's changes since `base`'s merge base with HEAD. A rename is a removal and an addition."""
    done = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD", "--", REPLAY],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return [(status, path) for status, path in (line.split("\t", 1) for line in done.stdout.splitlines() if line)]


def main(argv: list[str]) -> int:
    found = problems(changes(argv[1]), build_dir().name)
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 4: Run the tests, and the check itself**

Run: `cd backend && uv run pytest -q tests/engine/replay`
Expected: 43 passed.

Run: `cd backend && uv run python -m tests.engine.replay.gate main; echo "exit $?"`
Expected: `exit 0`, with nothing printed: this branch recorded no history.

- [ ] **Step 5: The gate in CI**

In `.github/workflows/ci.yml`:

```diff
diff --git a/.github/workflows/ci.yml b/.github/workflows/ci.yml
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ -7,6 +7,7 @@
     defaults: { run: { working-directory: backend } }
     steps:
       - uses: actions/checkout@v4
+        with: { fetch-depth: 0 }  # the replay gate compares with the base
       - uses: astral-sh/setup-uv@38f3f104447c67c051c4a08e39b64a148898af3a # v4
       - run: uv sync --locked
       - run: uv run ruff check .
@@ -14,6 +15,13 @@
       - run: uv run mypy src
       - run: uv run lint-imports
       - run: uv run pytest -q
+      # The replay gate (spec §7): the suite replays this ABI's histories; this checks none was changed or removed,
+      # and that new ones went into this build's directory.
+      - name: Recorded histories are never rewritten
+        env: { BASE: "${{ github.event.pull_request.base.sha || github.event.before }}" }
+        run: |
+          case "$BASE" in ""|0000000000000000000000000000000000000000) BASE=origin/main ;; esac
+          uv run python -m tests.engine.replay.gate "$BASE"
       - run: uv run pip-licenses --fail-on="GPL;AGPL;LGPL;SSPL;BUSL" --partial-match
   cel-gates:
     # The CEL gates (spec §5.9) in a pinned Linux container: rlimits, fork and cgroup behaviour are Linux's. The
```

- [ ] **Step 6: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add tests/engine/replay ../.github \
  && git commit -m "ci: the replay gate, recorded histories are never rewritten" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,042 passed and 8 skipped.

**Checkpoint 2:** deployment. Stop for the owner's review.

---

### Task 8: 2a-3b's deferred minors

2a-3b's final review deferred eight minors. Task 5 fixed M4, and this task fixes the other seven, each with a test
that fails first (decision 13):

| Minor | The fix | Its test |
|---|---|---|
| M1 | `Budget` forgets a refusal once no need waits, so a later need asks the parent again | `test_budget.py`: `test_a_refused_child_refuses_its_waiting_needs_and_asks_again_for_a_later_one` (replaces `test_a_refused_child_waits_for_its_own_children_and_never_asks_again`) |
| M2 | the run's end drops the needs its loops wait with (`Budget.drop_local`, from `Scheduler.end`) | `test_scheduler_batches.py`: `test_the_runs_end_drops_what_its_loops_wait_for` |
| M3 | a `LoopBatch` that fails with `internal_error` flushes its rows first | `test_run_graph_children.py`: `test_a_batch_that_fails_on_a_bug_writes_its_rows_first` |
| M5 | the store logs and skips a sub-run's start row that the database refuses for its data | `test_worker_db.py`: `test_a_sub_run_row_the_database_refuses_never_holds_up_its_projection` |
| M6 | a continued run's input carries its iterations (`RunInput.iterations`, `BatchInput.iterations`), so a run whose snapshot this build can't read still reports them | `test_run_graph_continue.py`: `test_a_snapshot_of_another_format_fails_the_run` now expects the 37 iterations its input carries, and `test_a_long_run_continues_as_new_and_ends_as_it_would_have` checks that a continued run's input carries them |
| M7 | `test_the_cap_holds_across_children` asserts exactly `== 0`: the filter's 150 items are all or nothing | itself, in `test_run_graph_children.py` |
| M8 | a cancel while the run waits for its projection in flight, before continuing, lets that projection land (`_landed`), then ends the run `cancelled` | `test_run_graph_continue.py`: `test_a_cancel_while_the_run_settles_for_continue_as_new_lets_its_projection_land` |

The M8 test needs a projection that's still in flight when the cancel arrives. Its store (`SlowRunning`) holds the
projection of the `running` row of `a`, a 1 s `testkit.slow` step, for 3 s. A parallel `testkit.echo` step sends
that projection (queued rows alone don't wake the drive loop), and `a` ends while it's held. The run then waits at
its quiescent point with the projection in flight, and the test cancels it there.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/budget.py`, `backend/src/dewpoint/engine/runtime/scheduler.py`,
  `backend/src/dewpoint/engine/runtime/activities.py`, `backend/src/dewpoint/engine/runtime/execution.py`,
  `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/src/dewpoint/apps/worker/store.py`
- Modify: `backend/tests/engine/runtime/test_budget.py`, `backend/tests/engine/runtime/test_scheduler_batches.py`,
  `backend/tests/apps/worker/test_run_graph_children.py`, `backend/tests/apps/worker/test_worker_db.py`,
  `backend/tests/apps/worker/test_run_graph_continue.py`

**Interfaces:**
- Consumes: 2a-3b's `Budget`, `Scheduler`, `Execution`, `RunGraph`, `LoopBatch` and `DbRunStore`.
- Produces: `Budget.drop_local() -> None`; `RunInput.iterations: int = 0` and `BatchInput.iterations: int = 0`.
  Continue-as-new passes the scheduler's iterations in them.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/engine/runtime/test_budget.py` (M1):

```diff
diff --git a/backend/tests/engine/runtime/test_budget.py b/backend/tests/engine/runtime/test_budget.py
--- a/backend/tests/engine/runtime/test_budget.py
+++ b/backend/tests/engine/runtime/test_budget.py
@@ -78,7 +78,9 @@
     assert [(a.need.requester, a.granted) for a in answers] == [("b", 0)]


-def test_a_refused_child_waits_for_its_own_children_and_never_asks_again() -> None:
+def test_a_refused_child_refuses_its_waiting_needs_and_asks_again_for_a_later_one() -> None:
+    """A refusal answers the needs that were waiting. A later need asks again: budget may have come back meanwhile
+    (the final review of 2a-3b, M1)."""
     mid = Budget(10, root=False)
     mid.start_child("leaf", 10)
     mid.request(local("loop", 1))
@@ -87,7 +89,10 @@
     assert mid.decide() == ([], Ask(1, CHUNK))
     mid.answered(0)
     answers, ask = mid.decide()
-    assert [a.granted for a in answers] == [0, 0] and ask is None and mid.refused
+    assert [a.granted for a in answers] == [0, 0] and ask is None and not mid.refused
+    mid.settle_child("leaf", 10)  # it spent all it had
+    mid.request(local("later", 1))
+    assert mid.decide() == ([], Ask(1, CHUNK))  # before: refused on the spot, whatever the parent had since


 def test_a_feasible_need_waits_for_an_asking_child_that_holds_enough_and_is_refused_first() -> None:
```

In `backend/tests/engine/runtime/test_scheduler_batches.py` (M2):

```diff
diff --git a/backend/tests/engine/runtime/test_scheduler_batches.py b/backend/tests/engine/runtime/test_scheduler_batches.py
--- a/backend/tests/engine/runtime/test_scheduler_batches.py
+++ b/backend/tests/engine/runtime/test_scheduler_batches.py
@@ -140,6 +140,22 @@
     assert [name(s, i) for i in s.take_ready()] == ["l:1/x"]


+def test_the_runs_end_drops_what_its_loops_wait_for() -> None:
+    """A loop waiting for its next iteration's budget when the run ends opens nothing, and its need leaves the queue:
+    a failure handler started now gets its grant (2a-3b's final review, M2)."""
+    p = program(loop_graph())
+    s = Scheduler(p, budget=Budget(1, root=False))
+    s.start_batch(p.by_key["l"], [OuterScope((), {})], [0, 1], offset=0, concurrency=2, stop_on_error=True)
+    assert [name(s, i) for i in s.take_ready()] == ["l:0/x"]
+    s.answer_budget()  # the second iteration waits: it asks the parent
+    s.end(RunEnd("failed", Failure("workflow_failed", "it went wrong")))
+    assert s.budget.waiting == []
+    s.budget.answered(1_000)
+    s.answer_budget()
+    assert s.take_ready() == [] and s.iterations == 1  # nothing opened, nothing debited
+    assert s.budget.start_child("handler", 1_000) == 1_000
+
+
 def test_a_batched_loop_survives_a_snapshot() -> None:
     s, loop = parent_at_loop(150)
     [b] = s.take_batches()
```

In `backend/tests/apps/worker/test_run_graph_children.py` (M3, M7):

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_children.py b/backend/tests/apps/worker/test_run_graph_children.py
--- a/backend/tests/apps/worker/test_run_graph_children.py
+++ b/backend/tests/apps/worker/test_run_graph_children.py
@@ -348,6 +348,31 @@
     assert (result.status, result.error["code"]) == ("failed", "internal_error")


+async def test_a_batch_that_fails_on_a_bug_writes_its_rows_first(
+    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
+) -> None:
+    """2a-3b's final review, M3: a batch that fails with `internal_error` wrote nothing it had queued, and its steps'
+    rows stayed `running`. It writes them before it fails, as a run does. The bug here: collecting item 50."""
+    collected = Scheduler.collected
+
+    def broken(self: Scheduler, loop: Any, index: int, value: Any) -> None:
+        if index == 50:
+            raise RuntimeError("a bug")
+        collected(self, loop, index, value)
+
+    monkeypatch.setattr(Scheduler, "collected", broken)
+    store = MemoryStore()
+    g = graph(code=ref("steps.l.error.code", default="none"))
+    g.node("l", LOOP, {"items": list(range(150)), "collect": ref("item")}, on_error="continue")
+    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
+    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
+        handle = await start(env.client, store, g, {})
+        result = await asyncio.wait_for(handle.result(), 60)
+    assert (result.status, result.outputs) == ("succeeded", {"code": "internal_error"})
+    rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
+    assert len(rows) >= 50 and "running" not in {r.status for r in rows}
+
+
 async def test_the_cap_holds_across_children(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> None:
     """One cap for the logical run: past it, the child that can't be served fails with `iteration_cap_exceeded`."""
     monkeypatch.setattr(run_graph, "ITERATION_CAP", 100)
@@ -361,7 +386,7 @@
         handle = await start(env.client, store, g, {})
         result = await asyncio.wait_for(handle.result(), 120)
     assert (result.status, result.outputs) == ("succeeded", {"code": "iteration_cap_exceeded"})
-    assert result.iterations <= 100
+    assert result.iterations == 0  # the filter's 150 items are all or nothing: none ran (2a-3b's final review, M7)


 # --- the plan's Review Focus: inputs a user meets that nothing above covers -------------------------------------
```

In `backend/tests/apps/worker/test_worker_db.py` (M5):

```diff
diff --git a/backend/tests/apps/worker/test_worker_db.py b/backend/tests/apps/worker/test_worker_db.py
--- a/backend/tests/apps/worker/test_worker_db.py
+++ b/backend/tests/apps/worker/test_worker_db.py
@@ -13,7 +13,7 @@
 from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.runs import service as runs
-from dewpoint.engine.runtime.activities import ProjectInput, RunSummary, StepRow
+from dewpoint.engine.runtime.activities import ProjectInput, RunStart, RunSummary, StepRow
 from dewpoint.engine.runtime.workflow import RunGraph
 from tests.apps.api.helpers import member_client
 from tests.apps.test_workflow_ops import actor, create, publish
@@ -139,6 +139,35 @@
     assert run is not None
     assert (run.status, run.error_code, run.error_message) == ("failed", "workflow_failed", "bad \ufffd note")
     assert [r.node_key for r in steps] == ["f"]
+
+
+async def test_a_sub_run_row_the_database_refuses_never_holds_up_its_projection(
+    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
+) -> None:
+    """2a-3b's final review, M5: a sub-run's row the database refuses (here its parent doesn't exist) was retried
+    forever, and the sub-run couldn't even be cancelled: its first write is shielded. It's logged and skipped, as a
+    refused step row is."""
+    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
+    async with owner_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        seeded = await runs.get_run(s, run_id)
+    assert seeded is not None
+    child = uuid.uuid4()
+    start = RunStart(
+        run_id=str(child),
+        workflow_id=str(seeded.workflow_id),
+        version_id=str(seeded.workflow_version_id),
+        mode="live",
+        parent_run_id=str(uuid.uuid4()),  # no such run
+        parent_step_id=None,
+        parent_iteration_key="",
+        kind="subflow",
+        started_at=datetime.now(UTC).isoformat(),
+    )
+    await DbRunStore(worker_sessionmaker).project(ProjectInput(str(tenant), [], None, start))
+    async with owner_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        assert await runs.get_run(s, child) is None


 async def test_a_sub_flow_is_projected_as_a_run_of_its_own(
```

In `backend/tests/apps/worker/test_run_graph_continue.py` (M6, M8):

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_continue.py b/backend/tests/apps/worker/test_run_graph_continue.py
--- a/backend/tests/apps/worker/test_run_graph_continue.py
+++ b/backend/tests/apps/worker/test_run_graph_continue.py
@@ -71,6 +71,10 @@
     assert len(runs) >= 2, "it never continued as new"
     assert (result.status, result.outputs) == ("succeeded", {"items": list(range(40))})
     assert result.iterations == 40  # the budget carried over: no fresh cap after continue-as-new
+    continued = json.loads(
+        runs[0].events[-1].workflow_execution_continued_as_new_event_attributes.input.payloads[0].data
+    )
+    assert continued["iterations"] == continued["snapshot"]["scheduler"]["budget"]["used"] > 0  # outside it too (M6)
     rows = [r for r in store.steps(handle.id) if r.node_key == "x"]
     assert len(rows) == 40 and {(r.attempt, r.status) for r in rows} == {(1, "succeeded")}

@@ -101,6 +105,56 @@
         runs = await chain(env.client, handle.id, handle.first_execution_run_id or "")
     assert len(runs) == 1 and store.runs[handle.id].status == "cancelled"
     assert [(r.node_key, r.status) for r in store.steps(handle.id)] == [("a", "succeeded")]  # `b` never started
+
+
+@dataclasses.dataclass
+class SlowRunning(MemoryStore):
+    """The projection of `a`'s `running` row takes 3 s. `c` ending next to `a` sends it (a queued row alone doesn't
+    wake the run); `a` (1 s) ends meanwhile, and the run reaches its quiescent point with it still in flight."""
+
+    projecting: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)
+
+    async def project(self, data: ProjectInput) -> None:
+        if any(r.node_key == "a" and r.status == "running" for r in data.steps):
+            self.projecting.set()
+            await asyncio.sleep(3)
+        await super().project(data)
+
+
+async def test_a_cancel_while_the_run_settles_for_continue_as_new_lets_its_projection_land(
+    env: WorkflowEnvironment,
+) -> None:
+    """2a-3b's final review, M8: the run waits for the projection in flight before continuing. A cancel then used to
+    cancel that projection too; it lands, and the run ends cancelled."""
+    store = SlowRunning()
+    g = graph().node("a", "testkit.slow@1", {"seconds": 1}).node("c", ECHO, {"value": 1})
+    g.node("b", ECHO, {"value": 2}).edge("a", "b").edge("c", "b")
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {}, checkpoint_events=10)
+        await asyncio.wait_for(store.projecting.wait(), 30)
+        first = env.client.get_workflow_handle(handle.id, run_id=handle.first_execution_run_id)
+        for _ in range(100):  # until `a` has ended: the run now waits for the projection to continue
+            history = await first.fetch_history()
+            slow = {
+                e.event_id
+                for e in history.events
+                if e.HasField("activity_task_scheduled_event_attributes")
+                and e.activity_task_scheduled_event_attributes.activity_type.name.startswith("testkit.slow")
+            }
+            if any(
+                e.activity_task_completed_event_attributes.scheduled_event_id in slow
+                for e in history.events
+                if e.HasField("activity_task_completed_event_attributes")
+            ):
+                break
+            await asyncio.sleep(0.05)
+        await handle.cancel()
+        with pytest.raises(WorkflowFailureError):
+            await asyncio.wait_for(handle.result(), 30)
+        history = await first.fetch_history()
+    requested = [e for e in history.events if e.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_CANCEL_REQUESTED]
+    assert requested == [] and store.runs[handle.id].status == "cancelled"
+    assert sorted(r.node_key for r in store.steps(handle.id)) == ["a", "c"]  # `b` never started


 def doubler() -> G:
@@ -198,13 +252,16 @@


 async def test_a_snapshot_of_another_format_fails_the_run(env: WorkflowEnvironment) -> None:
-    """Decision 16: a continued run whose snapshot this build can't read ends `internal_error`; it never hangs."""
+    """Decision 16: a continued run whose snapshot this build can't read ends `internal_error`; it never hangs. It
+    still reports the iterations it used before continuing, which its input carries outside the snapshot (2a-3b's
+    final review, M6: it reported 0)."""
     store = MemoryStore()
     g = graph().node("a", ECHO, {"value": 1})
     async with workers(env.client, store):
-        handle = await start(env.client, store, g, {}, snapshot={"snapshot_format": 99})
+        handle = await start(env.client, store, g, {}, snapshot={"snapshot_format": 99}, iterations=37)
         result = await asyncio.wait_for(handle.result(), 30)
-    assert (result.status, result.error["code"]) == ("failed", "internal_error")
+    assert (result.status, result.error["code"], result.iterations) == ("failed", "internal_error", 37)
+    assert store.runs[handle.id].iterations == 37


 async def test_a_batch_with_a_snapshot_of_another_format_fails_as_a_workflow(env: WorkflowEnvironment) -> None:
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/runtime/test_budget.py tests/engine/runtime/test_scheduler_batches.py tests/apps/worker/test_run_graph_children.py tests/apps/worker/test_worker_db.py tests/apps/worker/test_run_graph_continue.py`
Expected: 7 failed, 64 passed.
- M1: `test_a_refused_child_refuses_its_waiting_needs_and_asks_again_for_a_later_one`: the budget is still `refused`
  once no need waits.
- M2: `test_the_runs_end_drops_what_its_loops_wait_for`: the loop's need is still waiting
  (`[Need(requester='', key='loop::l', …)] == []`).
- M3: `test_a_batch_that_fails_on_a_bug_writes_its_rows_first`: the items' rows weren't all written, and some
  still say `running`.
- M5: `test_a_sub_run_row_the_database_refuses_never_holds_up_its_projection`: a `ForeignKeyViolationError` on
  `runs_parent_run_id_fkey`, retried.
- M6: `test_a_long_run_continues_as_new_and_ends_as_it_would_have` (`KeyError: 'iterations'`) and
  `test_a_snapshot_of_another_format_fails_the_run` (`TypeError: RunInput.__init__() got an unexpected keyword
  argument 'iterations'`).
- M8: `test_a_cancel_while_the_run_settles_for_continue_as_new_lets_its_projection_land`: the projection in flight
  is cancelled (an `ACTIVITY_TASK_CANCEL_REQUESTED` for it).

- [ ] **Step 3: The budget (M1, M2)**

In `backend/src/dewpoint/engine/runtime/budget.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/budget.py b/backend/src/dewpoint/engine/runtime/budget.py
--- a/backend/src/dewpoint/engine/runtime/budget.py
+++ b/backend/src/dewpoint/engine/runtime/budget.py
@@ -56,7 +56,7 @@
     reserved: dict[str, int] = field(default_factory=dict)  # outstanding child -> what it was granted so far
     waiting: list[Need] = field(default_factory=list)
     asking: bool = False  # an Ask is out and unanswered
-    refused: bool = False  # the parent refused: only this execution's own children can help now
+    refused: bool = False  # the parent refused: only this execution's own children can help its waiting needs

     @property
     def unreserved(self) -> int:
@@ -89,6 +89,11 @@
         granted = self.reserved.pop(child, 0)
         self.used += granted if used is None else min(max(used, 0), granted)
         self.waiting = [n for n in self.waiting if n.requester != child]
+
+    def drop_local(self) -> None:
+        """The execution ended: its own needs still waiting will never run. They leave the queue, so a child started
+        now (a failure handler) gets its grant, and nothing is debited for them."""
+        self.waiting = [n for n in self.waiting if n.requester != LOCAL]

     def answered(self, granted: int) -> None:
         """The parent answered this execution's Ask."""
@@ -125,6 +130,8 @@
                 break  # children that were asking hold enough: refused, they end and release it; wait for them
             answers.append(Answer(head, 0))
             self.waiting.pop(0)
+        if not self.waiting:
+            self.refused = False  # the needs it was refused for are answered: a later one may ask again
         return answers, None

     def _refuse_asking(self, head: Need, free: int, answers: list[Answer]) -> bool:
```

In `backend/src/dewpoint/engine/runtime/scheduler.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/scheduler.py b/backend/src/dewpoint/engine/runtime/scheduler.py
--- a/backend/src/dewpoint/engine/runtime/scheduler.py
+++ b/backend/src/dewpoint/engine/runtime/scheduler.py
@@ -364,6 +364,8 @@
                     self._cancels.append(Instance(scope.key, node_id))
         self._ready = []
         self._batches = []
+        self.budget.drop_local()  # a loop waiting for its next iteration opens none now
+        self._budget_waits.clear()

     def answer_budget(self) -> tuple[list[Answer], Ask | None]:
         """Serve the budget's waiting needs. The loops' own answers are applied here: a granted iteration opens, a
```

- [ ] **Step 4: The workflows (M3, M6, M8)**

In `backend/src/dewpoint/engine/runtime/activities.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/activities.py b/backend/src/dewpoint/engine/runtime/activities.py
--- a/backend/src/dewpoint/engine/runtime/activities.py
+++ b/backend/src/dewpoint/engine/runtime/activities.py
@@ -67,6 +67,7 @@
     snapshot: dict[str, Any] | None = None  # a continued run: where it carries on (spec §6, `snapshot_format` 1)
     checkpoint_events: int = CHECKPOINT_EVENTS
     drain_events: int = DRAIN_EVENTS
+    iterations: int = 0  # a continued run: what it had used, readable even when its snapshot isn't


 @dataclass(frozen=True)
@@ -101,6 +102,7 @@
     snapshot: dict[str, Any] | None = None
     checkpoint_events: int = CHECKPOINT_EVENTS
     drain_events: int = DRAIN_EVENTS
+    iterations: int = 0  # a continued batch: what it had used, readable even when its snapshot isn't


 @dataclass(frozen=True)
```

In `backend/src/dewpoint/engine/runtime/execution.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -380,12 +380,15 @@

     async def _settle_for_continue(self, tasks: dict[tuple[Any, ...], asyncio.Task[Any]]) -> None:
         """Continue-as-new: the sleeping timer steps stop here (their wake times go into the snapshot), and the
-        projection in flight lands."""
+        projection in flight lands, whatever cancels arrive meanwhile. A cancel then ends the execution instead
+        (raised once it has landed): a continued run wouldn't inherit it."""
         for key, task in tasks.items():
             if key[0] == "step":
                 task.cancel()
-        await asyncio.gather(*tasks.values(), return_exceptions=True)
+        cancelled = await _landed(asyncio.gather(*tasks.values(), return_exceptions=True))
         tasks.clear()
+        if cancelled:
+            raise asyncio.CancelledError

     @staticmethod
     def _in_flight(tasks: Mapping[tuple[Any, ...], asyncio.Task[Any]]) -> int:
```

In `backend/src/dewpoint/engine/runtime/workflow.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -112,7 +112,7 @@
         self.input = start
         if unreadable:  # a snapshot this build can't read: the run ends, it never hangs (spec §6)
             message = "This build can't read the run's continue-as-new snapshot."
-            return await self._end_early(RunEnd("failed", Failure(INTERNAL_ERROR, message)))
+            return await self._end_early(RunEnd("failed", Failure(INTERNAL_ERROR, message)), start.iterations)
         if start.parent is not None and snapshot is None:  # its row first: whatever ends it now has a row to end
             if await self._shielded([], None, RunStart.of(start, started.isoformat())):
                 return await self._cancelled_early()  # cancelled while the row was written
@@ -152,7 +152,7 @@
                 self._fresh(program)
             if await self._drive() == CONTINUE:
                 await self._flush()
-                workflow.continue_as_new(replace(start, snapshot=self._snapshot()))
+                workflow.continue_as_new(replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations))
             end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
             if end.status == "succeeded":
                 end, outputs = await self._outputs_by(end)
@@ -243,8 +243,9 @@
             error["message"] = mask(error["message"], self._secrets)
         return self._stored(error)

-    async def _end_early(self, end: RunEnd) -> RunResult:
-        """The run ends before it has a program: nothing ran, so only the run is projected."""
+    async def _end_early(self, end: RunEnd, iterations: int = 0) -> RunResult:
+        """The run ends before it has a program: nothing ran in this execution, so only the run is projected, with
+        what it used before continuing as new (`iterations`)."""
         error = self._stored(end.failure.to_json() if end.failure is not None else None)
         summary = RunSummary(
             run_id=self.run_id,
@@ -252,9 +253,10 @@
             ended_at=workflow.now().isoformat(),
             error_code=error["code"] if error else None,
             error_message=error["message"] if error else None,
+            iterations=iterations,
         )
         await self._shielded([], summary)
-        return RunResult(status=end.status, error=error)
+        return RunResult(status=end.status, error=error, iterations=iterations)

     async def _cancelled_early(self) -> RunResult:
         result = await self._end_early(RunEnd("cancelled", CANCELLED))
@@ -408,13 +410,14 @@
                 )
             if await self._drive() == CONTINUE:
                 await self._flush()
-                workflow.continue_as_new(replace(start, snapshot=self._snapshot()))
+                workflow.continue_as_new(replace(start, snapshot=self._snapshot(), iterations=self.sched.iterations))
         except asyncio.CancelledError:
             self.sched.end(RunEnd("cancelled", CANCELLED))
             await self._project_end(None)
             return self._result(RunEnd("cancelled", CANCELLED))
         except Exception as e:
             workflow.logger.error("batch_internal_error", exc_info=True)
+            await self._project_end(None)  # its steps' rows land first, as a run's do
             message = f"The batch failed ({type(e).__name__}); the worker's log has the details."
             raise ApplicationError(message, type=INTERNAL_ERROR, non_retryable=True) from None
         await self._project_end(None)
```

- [ ] **Step 5: The store (M5)**

In `backend/src/dewpoint/apps/worker/store.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/store.py b/backend/src/dewpoint/apps/worker/store.py
--- a/backend/src/dewpoint/apps/worker/store.py
+++ b/backend/src/dewpoint/apps/worker/store.py
@@ -85,7 +85,14 @@
         async with self.sessionmaker() as s, s.begin():
             await tenant_scope(s, tenant)
             if data.start is not None:
-                await _start(s, tenant, data.start)
+                try:
+                    async with s.begin_nested():
+                        await _start(s, tenant, data.start)
+                except DBAPIError as e:
+                    state = _refused(e)
+                    if state is None:
+                        raise
+                    _log.warning("projection_start_refused", run_id=data.start.run_id, sqlstate=state)
             for row in data.steps:
                 try:
                     async with s.begin_nested():
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest -q tests/engine/runtime/test_budget.py tests/engine/runtime/test_scheduler_batches.py tests/apps/worker/test_run_graph_children.py tests/apps/worker/test_worker_db.py tests/apps/worker/test_run_graph_continue.py`
Expected: 71 passed.

- [ ] **Step 7: Checks, the whole suite, and commit**

The abi2 histories must still replay: none of these fixes changes a recorded scenario's commands.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src tests \
  && git commit -m "fix(engine): 2a-3b's deferred minors, M1-M3 and M5-M8" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,046 passed and 8 skipped.

---

### Task 9: 2a-3a's deferred minors

2a-3a's final review deferred M3–M7, and 2a-3b fixed M7. This task fixes M3–M6 (decision 14):

| Minor | The fix | Its test |
|---|---|---|
| M3 | a cancelled attempt of an `ambiguous` node is `outcome_unknown` | `test_run_graph_policies.py`: `test_a_cancelled_ambiguous_attempt_says_its_outcome_is_unknown` |
| M4 | `dewpoint dev run --input` refuses JSON that isn't an object, with exit 2, before anything starts | `test_dev_run_cli.py`: `test_an_input_that_isnt_a_json_object_is_refused_before_anything_starts` |
| M5 | `list_runs` pages by the pair `(started_at, id)`, and `GET /runs` takes it as `before` and `before_id`, together or not at all: half a cursor is refused (422, `invalid_cursor`) | `test_service.py`: `test_runs_that_started_in_the_same_instant_are_paged_by_id_too`, and 2a-3a's `test_runs_list_newest_first_and_page` pages with the pair; `tests/apps/api/test_runs_api.py` (new): `test_the_runs_list_pages_past_runs_that_started_in_the_same_instant` and `test_half_a_cursor_is_refused` |
| M6 | every wait for a result in a time-skipping test is bounded: the harness's `RESULT_TIMEOUT_S = 60`, and 120 s in the recorder | the tests themselves |

The M3 test cancels the run while the ambiguous step's request is out. It waits until `testkit`'s `SlowSend` has
recorded the send, not for a history event: Temporal writes `ACTIVITY_TASK_STARTED` only once the activity closes.

M5's cursor was `before` alone, a start time. Runs that started in the same instant as the last one of a page were
skipped, and nothing calls the API with a cursor yet, so there's no date-only mode to keep: `before` without
`before_id`, or the other way round, is refused. The service takes the cursor as one value, so half a cursor can't
reach it.

M6's golden scenarios (a cancelled run, `version_unusable`) come with Task 11's new histories, so they're recorded
once, in abi3.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/execution.py`, `backend/src/dewpoint/apps/cli/main.py`,
  `backend/src/dewpoint/core/runs/service.py`, `backend/src/dewpoint/apps/api/routes/runs.py`
- Modify: `backend/tests/apps/worker/test_run_graph_policies.py`, `backend/tests/apps/cli/test_dev_run_cli.py`,
  `backend/tests/core/runs/test_service.py`, `backend/tests/apps/worker/harness.py`,
  `backend/tests/apps/worker/test_run_graph.py`, `backend/tests/engine/replay/record.py`
- Create: `backend/tests/apps/api/test_runs_api.py`

**Interfaces:**
- Consumes: 2a-3a's `list_runs`, the runs route, `dev run` and the harness.
- Produces: `service.list_runs(s, *, workflow_id=None, before: tuple[datetime, uuid.UUID] | None = None,
  limit=50)`, where `before` is the last run's `(started_at, id)`; the route's `before_id` query parameter, and its
  422 `{"error": "invalid_cursor"}` for half a cursor; `harness.RESULT_TIMEOUT_S = 60`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/apps/worker/test_run_graph_policies.py` (M3, and M6's bounded waits):

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_policies.py b/backend/tests/apps/worker/test_run_graph_policies.py
--- a/backend/tests/apps/worker/test_run_graph_policies.py
+++ b/backend/tests/apps/worker/test_run_graph_policies.py
@@ -16,9 +16,16 @@
 from dewpoint.engine.canonical import canonical_json
 from dewpoint.engine.runtime import nodes
 from dewpoint.engine.runtime import workflow as run_graph
-from dewpoint.engine.runtime.activities import CEL_EVALUATE, ENGINE_QUEUE, PROJECT, ProjectInput, RunInput
+from dewpoint.engine.runtime.activities import (
+    CEL_EVALUATE,
+    ENGINE_QUEUE,
+    OUTCOME_UNKNOWN,
+    PROJECT,
+    ProjectInput,
+    RunInput,
+)
 from dewpoint.engine.runtime.workflow import PROJECT_BYTES, RunGraph
-from tests.apps.worker.harness import TENANT, MemoryStore, run, start, workers
+from tests.apps.worker.harness import RESULT_TIMEOUT_S, TENANT, MemoryStore, run, start, workers
 from tests.support.graphs import G, cel, ref, template
 from tests.support.plugins.testkit import SlowSend

@@ -55,7 +62,7 @@
     g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.x * 2"), "label": "fixed"}}).edge("w", "t")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
         info = await handle.describe()
     assert result.outputs == {"t": {"double": 14, "label": "fixed"}}
     assert (
@@ -145,7 +152,7 @@
     g.node("b", ECHO, {"value": cel("trigger.open.nothing")}, on_error="continue")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.outputs == {"a": "fallback", "b": "evaluation_error"}
     rows = {r.node_key: r for r in store.steps(handle.id)}  # b never reached its activity, and still has its row
     assert (rows["b"].attempt, rows["b"].status, rows["b"].error_code) == (1, "failed", "evaluation_error")
@@ -168,7 +175,7 @@
         g.node(f"e{i}", ECHO, {"value": i})
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        await handle.result()
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
         history = await handle.fetch_history()
     before_first_completion = 0
     for event in history.events:
@@ -195,7 +202,7 @@
         g.edge(f"e{i}", f"t{i}")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        await handle.result()
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
         history = await handle.fetch_history()
     outstanding: set[int] = set()
     most = 0
@@ -221,7 +228,7 @@
         g.node(f"e{i}", ECHO, {"value": i}).edge("t1", f"e{i}")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        await handle.result()
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
         history = await handle.fetch_history()
     kinds = {
         e.event_id: e.activity_task_scheduled_event_attributes.activity_type.name
@@ -243,7 +250,7 @@
     g = graph().node("s", "testkit.slow@1", {"seconds": 30})
     async with workers(own_env.client, store):
         handle = await start(own_env.client, store, g, TRIGGER, max_run_duration_s=2)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.status == "deadline_exceeded"
     [row] = store.steps(handle.id)
     assert row.status == "cancelled"
@@ -258,7 +265,7 @@
         await asyncio.sleep(0.2)
         await handle.cancel()
         with pytest.raises(WorkflowFailureError):
-            await handle.result()
+            await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert store.runs[handle.id].status == "cancelled"


@@ -344,7 +351,7 @@
     g.nodes[0]["options"].update(timeout_s=1, max_attempts=3)
     async with workers(own_env.client, store):
         handle = await start(own_env.client, store, g, TRIGGER)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert SlowSend.sent.count(handle.id) == 1
     assert result.status == "failed" and result.error and result.error["code"] == "timeout"
     [row] = store.steps(handle.id)
@@ -376,13 +383,28 @@
     assert result.status == "failed"


+async def test_a_cancelled_ambiguous_attempt_says_its_outcome_is_unknown(own_env: WorkflowEnvironment) -> None:
+    """2a-3a's final review, M3: a run cancelled during an ambiguous attempt recorded it `cancelled` only. Its request
+    may have been sent: the row says so, as it does for a timeout or a lost worker."""
+    store = MemoryStore()
+    g = graph().node("s", "testkit.slow_send@1", {"seconds": 5})
+    async with workers(own_env.client, store):
+        handle = await start(own_env.client, store, g, TRIGGER)
+        await sent(handle.id)  # the attempt has sent its request (its history says so only once it ends)
+        await handle.cancel()
+        with pytest.raises(WorkflowFailureError):
+            await asyncio.wait_for(handle.result(), 30)
+    [row] = [r for r in store.steps(handle.id) if r.node_key == "s"]
+    assert (row.status, row.outcome) == ("cancelled", OUTCOME_UNKNOWN)
+
+
 async def test_a_timeout_is_retried_when_repeating_is_safe(own_env: WorkflowEnvironment) -> None:
     store = MemoryStore()
     g = graph().node("s", "testkit.slow@1", {"seconds": 3})
     g.nodes[0]["options"].update(timeout_s=1, max_attempts=2)
     async with workers(own_env.client, store):
         handle = await start(own_env.client, store, g, TRIGGER)
-        await handle.result()
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert [(r.attempt, r.status, r.error_code, r.outcome) for r in store.steps(handle.id)] == [
         (1, "failed", "timeout", None),
         (2, "failed", "timeout", None),
@@ -409,7 +431,7 @@
     g.edge("s", "t")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.status == "succeeded" and SlowSend.sent.count(handle.id) == 1 and store.down == 0
     assert [(r.node_key, r.status) for r in store.steps(handle.id)] == [("s", "succeeded"), ("t", "succeeded")]
     assert store.runs[handle.id].status == "succeeded"
@@ -460,7 +482,7 @@
     g.edge("s", "t").edge("s", "e").edge("s", "p").edge("t", "f").edge("e", "f").edge("p", "f")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     rows = {r.node_key: r for r in store.steps(handle.id)}
     assert rows["s"].output_preview == {
         "public": "visible",
@@ -489,7 +511,7 @@
     g.node("e", ECHO, {"value": template("Bearer ", {"ref": "trigger.api_key"})})
     async with workers(env.client, store):
         handle = await start(env.client, store, g, {"api_key": "k3y-k3y-k3y"})
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     [row] = store.steps(handle.id)
     assert (row.input_preview, row.output_preview) == ({"value": "Bearer [redacted]"}, {"value": "Bearer [redacted]"})
     assert result.outputs == {"key": "k3y-k3y-k3y"}  # the workflow's own outputs are its contract, not a preview
@@ -507,7 +529,7 @@
     g.node("q", "testkit.ambiguous_send@1", echo, on_error="continue").edge("t", "p").edge("t", "q")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, {"x": 7, "open": {"tok": passed}})
-        await handle.result()
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     rows = {r.node_key: r for r in store.steps(handle.id)}
     assert rows["t"].output_preview == {"copy": "[redacted]"}  # projected before `p` ran
     assert rows["p"].input_preview == {"outcome": "rejected", "token": "[redacted]"}
```

In `backend/tests/apps/cli/test_dev_run_cli.py` (M4):

```diff
diff --git a/backend/tests/apps/cli/test_dev_run_cli.py b/backend/tests/apps/cli/test_dev_run_cli.py
--- a/backend/tests/apps/cli/test_dev_run_cli.py
+++ b/backend/tests/apps/cli/test_dev_run_cli.py
@@ -96,3 +96,20 @@
     _answer(monkeypatch, error, {})
     result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
     assert result.exit_code == code and said in result.output
+
+
+@pytest.mark.usefixtures("cli_env")
+@pytest.mark.parametrize("payload", ["[1, 2]", '"text"', "3"])
+def test_an_input_that_isnt_a_json_object_is_refused_before_anything_starts(
+    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, payload: str
+) -> None:
+    """2a-3a's final review, M4: a trigger that isn't an object (a list, a string) left the run failing its first
+    workflow task forever, so it hung. The CLI refuses it."""
+    seen: dict[str, Any] = {}
+    _answer(monkeypatch, RunResult("succeeded", {}), seen)
+    trigger = tmp_path / "trigger.json"
+    trigger.write_text(payload)
+    result = CliRunner().invoke(
+        cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4()), "--input", str(trigger)]
+    )
+    assert (result.exit_code, result.output) == (2, "ERROR: --input must hold a JSON object\n") and seen == {}
```

In `backend/tests/core/runs/test_service.py` (M5):

```diff
diff --git a/backend/tests/core/runs/test_service.py b/backend/tests/core/runs/test_service.py
--- a/backend/tests/core/runs/test_service.py
+++ b/backend/tests/core/runs/test_service.py
@@ -116,8 +116,28 @@
     async with owner_sessionmaker() as s, s.begin():
         await tenant_scope(s, tenant)
         first = await service.list_runs(s, limit=2)
-        rest = await service.list_runs(s, before=first[-1].started_at, limit=2)
+        rest = await service.list_runs(s, before=(first[-1].started_at, first[-1].id), limit=2)
     assert [r.id for r in first + rest] == ids[::-1]
+
+
+async def test_runs_that_started_in_the_same_instant_are_paged_by_id_too(
+    owner_sessionmaker, dispatch_sessionmaker
+) -> None:
+    """2a-3a's final review, M5: paging by the start time alone skipped runs that started in the same instant as the
+    last one of a page. The cursor is (start time, id)."""
+    tenant, wf, version = await seed_workflow(owner_sessionmaker)
+    async with dispatch_sessionmaker() as s, s.begin():  # one transaction: now() is one instant
+        await tenant_scope(s, tenant)
+        for _ in range(3):
+            await service.insert_run(
+                s, run_id=uuid.uuid4(), tenant_id=tenant, workflow_id=wf, version_id=version, mode="live"
+            )
+    async with owner_sessionmaker() as s, s.begin():
+        await tenant_scope(s, tenant)
+        first = await service.list_runs(s, limit=2)
+        rest = await service.list_runs(s, before=(first[-1].started_at, first[-1].id), limit=2)
+    assert len({r.started_at for r in first + rest}) == 1
+    assert len({r.id for r in first + rest}) == 3


 async def test_previews_and_messages_hold_nothing_the_database_refuses(
```

Create `backend/tests/apps/api/test_runs_api.py` (M5):

```python
# SPDX-License-Identifier: Apache-2.0
"""`GET /runs` pages by (start time, id): `before` and `before_id` name the last run of the previous page, and go
together."""

import uuid

import pytest

from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service
from tests.apps.api.helpers import member_client
from tests.apps.test_workflow_ops import actor
from tests.support.workflows import seed_workflow


async def test_the_runs_list_pages_past_runs_that_started_in_the_same_instant(
    app, owner_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx = await actor(owner_sessionmaker)
    _, wf, version = await seed_workflow(owner_sessionmaker, tenant_id=ctx.tenant_id)
    async with dispatch_sessionmaker() as s, s.begin():  # one transaction: now() is one instant
        await tenant_scope(s, ctx.tenant_id)
        for _ in range(3):
            await service.insert_run(
                s, run_id=uuid.uuid4(), tenant_id=ctx.tenant_id, workflow_id=wf, version_id=version, mode="live"
            )
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    first = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params={"limit": 2})).json()
    last = first[-1]
    params = {"limit": 2, "before": last["started_at"], "before_id": last["id"]}
    rest = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params=params)).json()
    assert len({r["id"] for r in first + rest}) == 3


@pytest.mark.parametrize("half", ["before", "before_id"])
async def test_half_a_cursor_is_refused(app, owner_sessionmaker, api_settings, half: str) -> None:
    """The start time alone would skip runs that started in the same instant; an id alone names no position."""
    ctx = await actor(owner_sessionmaker)
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    value = {"before": "2026-09-28T12:00:00+00:00", "before_id": str(uuid.uuid4())}[half]
    response = await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs", params={half: value})
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_cursor"
```

In `backend/tests/apps/worker/harness.py` (M6):

```diff
diff --git a/backend/tests/apps/worker/harness.py b/backend/tests/apps/worker/harness.py
--- a/backend/tests/apps/worker/harness.py
+++ b/backend/tests/apps/worker/harness.py
@@ -2,6 +2,7 @@
 """Run test graphs through `RunGraph` on Temporal's time-skipping test server, with the real step activities, an
 in-memory store and an in-process CEL evaluator (the real one needs Linux and its own container)."""

+import asyncio
 import uuid
 from collections.abc import AsyncIterator, Iterable
 from contextlib import asynccontextmanager
@@ -36,6 +37,9 @@
 from tests.support.plugins.testkit import TESTKIT

 TENANT = str(uuid.UUID(int=1))
+
+
+RESULT_TIMEOUT_S = 60  # the harness's runs are time-skipped: a minute is far more than any needs


 @dataclass
@@ -142,5 +146,6 @@
 async def run(
     client: Client, store: MemoryStore, g: G, trigger: dict[str, Any] | None = None, **options: Any
 ) -> RunResult:
+    """A run to its end: a run that hangs fails its test instead of stalling the suite (2a-3a's final review, M6)."""
     handle = await start(client, store, g, trigger, **options)
-    return await handle.result()
+    return await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
```

In `backend/tests/apps/worker/test_run_graph.py` (M6):

```diff
diff --git a/backend/tests/apps/worker/test_run_graph.py b/backend/tests/apps/worker/test_run_graph.py
--- a/backend/tests/apps/worker/test_run_graph.py
+++ b/backend/tests/apps/worker/test_run_graph.py
@@ -1,6 +1,7 @@
 # SPDX-License-Identifier: Apache-2.0
 """`RunGraph` end to end on the time-skipping test server (spec §6, §10 interpreter tests)."""

+import asyncio
 from typing import Any

 from temporalio.client import WorkflowHistory
@@ -9,7 +10,7 @@

 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.workflow import RunGraph
-from tests.apps.worker.harness import MemoryStore, run, start, workers
+from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run, start, workers
 from tests.support.graphs import G, cel, ref, template

 ECHO, IF, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.filter@1"
@@ -46,7 +47,7 @@
     g.edge("c", "yes", "true").edge("c", "no", "false")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert (result.status, result.outputs) == ("succeeded", {"side": "yes"})
     rows = {r.node_key: r for r in store.steps(handle.id)}
     assert rows["c"].status == "succeeded" and rows["c"].cel_mode == "activity"  # LOCAL_CEL_PROFILE is None
@@ -61,7 +62,7 @@
     g.edge("l", "x", "body").edge("l", "f", "done")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.outputs == {"doubled": [2, 4, 6], "aps": ["ap-1", "ap-2"]}
     assert result.iterations == 3 + 3  # three iterations, three filter items
     rows = [(r.node_key, r.iteration_key, r.status) for r in store.steps(handle.id)]
@@ -89,7 +90,7 @@
     g = graph().node("f", "testkit.fail_n@1", {"failures": 2})
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        assert (await handle.result()).status == "succeeded"
+        assert (await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)).status == "succeeded"
     assert [(r.attempt, r.status, r.error_code) for r in store.steps(handle.id)] == [
         (1, "failed", "testkit.transient"),
         (2, "failed", "testkit.transient"),
@@ -112,7 +113,7 @@
     g = graph().node("a", "testkit.ambiguous_send@1", {"outcome": "unknown"})
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.status == "failed" and result.error == {
         "code": "testkit.timeout_after_send",
         "message": "the request may have been delivered",
@@ -156,7 +157,7 @@
     g = graph(outputs={"v": ref("steps.a.output.value")}).node("a", ECHO, {"value": 5})
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER, mode="simulate")
-        result = await handle.result()
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert result.outputs == {"v": {"simulated": 5}}
     assert [r.outcome for r in store.steps(handle.id)] == ["simulated"]

@@ -177,7 +178,7 @@
     g = graph().node("s", "testkit.sensitive@1")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        await handle.result()
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     [row] = store.steps(handle.id)
     assert row.output_preview == {
         "public": "visible",
@@ -193,6 +194,6 @@
     g.node("x", ECHO, {"value": ref("item")}).edge("c", "l", "true").edge("l", "x", "body")
     async with workers(env.client, store):
         handle = await start(env.client, store, g, TRIGGER)
-        await handle.result()
+        await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
         history = await handle.fetch_history()
     await Replayer(workflows=[RunGraph]).replay_workflow(WorkflowHistory.from_json(handle.id, history.to_json()))
```

In `backend/tests/engine/replay/record.py` (M6):

```diff
diff --git a/backend/tests/engine/replay/record.py b/backend/tests/engine/replay/record.py
--- a/backend/tests/engine/replay/record.py
+++ b/backend/tests/engine/replay/record.py
@@ -64,7 +64,7 @@
     async with await WorkflowEnvironment.start_time_skipping() as env, workers(env.client, store):
         for name, scenario in sorted(missing.items()):
             handle = await start(env.client, store, scenario.build(store), scenario.trigger, **scenario.options)
-            await handle.result()
+            await asyncio.wait_for(handle.result(), 120)
             histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
             for n, history in enumerate(histories):
                 data = scrub(json.loads(history.to_json()))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_policies.py tests/apps/cli/test_dev_run_cli.py tests/core/runs/test_service.py tests/apps/api/test_runs_api.py`
Expected: 9 failed, 66 passed.
- M3: `test_a_cancelled_ambiguous_attempt_says_its_outcome_is_unknown`: the row has no outcome
  (`('cancelled', None)`).
- M4: the three cases of `test_an_input_that_isnt_a_json_object_is_refused_before_anything_starts` exit 0: the run
  starts.
- M5: `test_runs_that_started_in_the_same_instant_are_paged_by_id_too` and 2a-3a's
  `test_runs_list_newest_first_and_page` pass the cursor as a pair (`TypeError: expected a datetime.date or
  datetime.datetime instance, got 'tuple'`); `test_the_runs_list_pages_past_runs_that_started_in_the_same_instant`
  lists 2 runs of 3; both cases of `test_half_a_cursor_is_refused` get `200`, not `422`.

- [ ] **Step 3: A cancelled ambiguous attempt (M3)**

In `backend/src/dewpoint/engine/runtime/execution.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -993,7 +993,8 @@
                     attempt += 1
                     continue
                 # The run or the scope ended: the SDK reports our own cancel as an ActivityError. Never retry it.
-                self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat()))
+                outcome = OUTCOME_UNKNOWN if ambiguous else None  # its request may have been sent
+                self._queue(replace(row, status="cancelled", ended_at=workflow.now().isoformat(), outcome=outcome))
                 raise asyncio.CancelledError from None
             self._learn(result.output, manifest["output_schema"])
             self._queue(
```

- [ ] **Step 4: `--input` must be an object (M4)**

In `backend/src/dewpoint/apps/cli/main.py`:

```diff
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -401,6 +401,9 @@
 ) -> None:
     """Start a run of a workflow's active version. Development only: 2b brings admission and triggers."""
     trigger = json.loads(Path(input_file).read_text()) if input_file else {}
+    if not isinstance(trigger, dict):  # a run's trigger is an object: anything else could never start
+        typer.echo("ERROR: --input must hold a JSON object")
+        raise typer.Exit(2)

     async def _go() -> tuple[uuid.UUID, RunResult | None]:
         settings = get_settings()
```

- [ ] **Step 5: The runs list's cursor (M5)**

In `backend/src/dewpoint/core/runs/service.py`:

```diff
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -10,7 +10,7 @@
 from datetime import datetime
 from typing import Any

-from sqlalchemy import select, update
+from sqlalchemy import select, tuple_, update
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession

@@ -170,14 +170,19 @@


 async def list_runs(
-    s: AsyncSession, *, workflow_id: uuid.UUID | None = None, before: datetime | None = None, limit: int = 50
+    s: AsyncSession,
+    *,
+    workflow_id: uuid.UUID | None = None,
+    before: tuple[datetime, uuid.UUID] | None = None,
+    limit: int = 50,
 ) -> list[Run]:
-    """Top-level runs, newest first; `before` pages through older runs. Sub-runs are listed with their parent."""
+    """Top-level runs, newest first. The next page starts after the last run of this one: `before` is its start time
+    and its id, since runs can start in the same instant. Sub-runs are listed with their parent."""
     q = select(Run).where(Run.parent_run_id.is_(None)).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
     if workflow_id is not None:
         q = q.where(Run.workflow_id == workflow_id)
     if before is not None:
-        q = q.where(Run.started_at < before)
+        q = q.where(tuple_(Run.started_at, Run.id) < tuple_(*before))
     return list((await s.execute(q)).scalars())


```

In `backend/src/dewpoint/apps/api/routes/runs.py`:

```diff
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -66,11 +66,18 @@
 async def list_runs(
     workflow_id: uuid.UUID | None = None,
     before: datetime | None = None,
+    before_id: uuid.UUID | None = None,
     limit: int = Query(50, ge=1, le=200),
     ctx: TenantContext = Depends(require(P.RUN_VIEW)),
     db: AsyncSession = Depends(get_db, scope="function"),
 ) -> list[dict[str, object]]:
-    return [_run(r) for r in await service.list_runs(db, workflow_id=workflow_id, before=before, limit=limit)]
+    """Newest first. The next page: `before` and `before_id`, the last run's `started_at` and `id`, always together:
+    runs can start in the same instant, so the time alone would skip some."""
+    if (before is None) != (before_id is None):
+        raise HTTPException(422, detail={"error": "invalid_cursor", "message": "Give before and before_id together."})
+    cursor = (before, before_id) if before is not None and before_id is not None else None
+    runs = await service.list_runs(db, workflow_id=workflow_id, before=cursor, limit=limit)
+    return [_run(r) for r in runs]


 @router.get("/t/{tenant_id}/runs/{run_id}")
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_policies.py tests/apps/cli/test_dev_run_cli.py tests/core/runs/test_service.py tests/apps/api/test_runs_api.py`
Expected: 75 passed.

- [ ] **Step 7: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src tests \
  && git commit -m "fix: 2a-3a's deferred minors, M3-M6" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,054 passed and 8 skipped.

---

### Task 10: A version runs only on a build of its engine ABI

Task 11 moves `ENGINE_ABI` to 3. Publishing stamps each version with the ABI it was published for, but nothing reads
it back. After the ABI-3 build is promoted, an active version published by the ABI-2 build would start on the ABI-3
worker, and its sub-flows and failure handler with it. This task adds the rule (decision 16): **a version runs only
on a build of its ABI.** Starting a run of any other is refused.
- **Admission compares with the deployment's current build**, where a new run starts. It doesn't compare with the
  admitting process's own build: during a rollout, both builds' processes start runs. `start_run` reads the current
  build from Temporal before its transaction (`current_abi`, from the build ID's `+abi<N>`), and `admit` checks
  every version in the closure against it: the version itself, and the sub-flows and failure handlers it runs, at
  any depth. So in the overlap:
  - before the promotion, a version of the new ABI is refused: "make a build of ABI 3 current first";
  - after it, a version of the old ABI is refused: "publish the workflow again with a build of ABI 3";
  - with no Dewpoint build current, nothing is admitted.
- **Publishing** refuses a draft that would pin a workflow whose active version's closure has another ABI than the
  one it's published for (`subflow.engine_abi`). So a parent can't be published again on its own, leaving it running
  an older ABI's children: its sub-flows and failure handler must be published again first.
- **The version loader** is the backstop, for a promotion that races a start: between the admission and the run's
  first workflow task. It refuses a version of another ABI, so the run, sub-flow or failure handler fails with
  `version_unusable` before any step runs. Its message says what to do. It's written for users, so the run's error
  shows it; any other load failure still shows only the exception's type.
- **Runs already pinned to the old build continue there**, their sub-flows and failure handlers included: the old
  build's loader accepts its own ABI's versions.

Activating or enabling a version doesn't start a run, and it doesn't know which build will be current when one
starts, so neither checks the ABI: admission does, at the start.

In tests, two builds run in one process with the same code, so `engine_worker` and `engine_activities` take the ABI
their loader accepts (`abi`, this build's by default). The harness stamps its versions with an ABI too, can publish
a new version of an existing workflow, and can start a version it already has (`start_version`). The end-to-end
tests of `test_worker_db.py` and `test_dev_run.py` start runs on the time-skipping server, which has no deployments,
so they stand in for its answer (the `this_build_is_current` fixture): this build is current.

**Files:**
- Modify: `backend/src/dewpoint/engine/runtime/build.py`, `backend/src/dewpoint/apps/worker/deployment.py`
- Modify: `backend/src/dewpoint/core/workflows/service.py`, `backend/src/dewpoint/apps/workflow_ops.py`,
  `backend/src/dewpoint/apps/runs.py`
- Modify: `backend/src/dewpoint/engine/runtime/activities.py`, `backend/src/dewpoint/engine/runtime/execution.py`,
  `backend/src/dewpoint/engine/runtime/workflow.py`
- Modify: `backend/src/dewpoint/apps/worker/activities.py`, `backend/src/dewpoint/apps/worker/store.py`,
  `backend/src/dewpoint/apps/worker/main.py`
- Modify: `backend/tests/apps/test_workflow_ops.py`, `backend/tests/apps/test_runs.py`,
  `backend/tests/apps/worker/harness.py`, `backend/tests/apps/worker/test_two_builds.py`,
  `backend/tests/apps/worker/conftest.py`, `backend/tests/apps/worker/test_worker_db.py`,
  `backend/tests/apps/worker/test_dev_run.py`
- Create: `backend/tests/apps/worker/test_run_graph_abi.py`, `backend/tests/apps/worker/test_admission_abi.py`
- Modify: `docs/operations/deployment.md`, `docs/operations/runs.md`

**Interfaces:**
- Consumes: Task 3's `describe`, `set_current`, `engine_worker(..., build=, identity=)` and `test_deployment`'s
  `build` and `placement`; Task 4's `test_two_builds.py`; 2a-3a's `admit`/`start_run` and `publish`.
- Produces:
  - `build.abi_of(build: str) -> int | None`: the ABI a Dewpoint build ID names;
  - `deployment.current_abi(client) -> int | None`: the current build's ABI, None when no Dewpoint build is current;
  - `admit(s, *, tenant_id, version_id, abi: int | None, mode=LIVE, started_by=None)`: `abi` is the current build's,
    required, which 2b's dispatcher passes too; `runs.NO_CURRENT_BUILD`, the reason when it's None;
  - `service.other_abi(s, version_ids, abi: int) -> list[tuple[uuid.UUID, int]]`: the versions among them of
    another ABI, each with its own;
  - `workflow_ops.abi_reasons(version_id, stale, current: int) -> list[str]`, and publish's diagnostic
    `subflow.engine_abi`;
  - `VersionData.engine_abi: int | None = None` (None only in histories recorded before this task);
  - `engine_activities(store, plugins, *, abi: int = ENGINE_ABI)` and `engine_worker(..., abi: int = ENGINE_ABI)`;
  - `execution._unloadable(e) -> str`, the message of a run whose version didn't load;
  - in the harness: `MemoryStore.add(g, workflow_id=None, *, engine_abi=ENGINE_ABI)`,
    `MemoryStore.publish(g, workflow_id=None, *, engine_abi=ENGINE_ABI)` and
    `start_version(client, version_id, trigger=None, **options)`; the fixture `this_build_is_current`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/apps/test_workflow_ops.py`, publishing. `published_by_the_previous_build` publishes a version as
the build before this one would, stamped with the ABI before this build's:

```diff
diff --git a/backend/tests/apps/test_workflow_ops.py b/backend/tests/apps/test_workflow_ops.py
--- a/backend/tests/apps/test_workflow_ops.py
+++ b/backend/tests/apps/test_workflow_ops.py
@@ -14,6 +14,7 @@
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.plugins.lifecycle import Entry
 from dewpoint.core.workflows import service
+from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.cel.record import ExpressionRecord
 from dewpoint.engine.graph.model import version_hash
@@ -222,6 +223,49 @@
     with pytest.raises(workflow_ops.NotActivatableError) as e:
         await activate(api_sessionmaker, ctx, wf, v1.id)
     assert [d.code for d in e.value.errors] == ["lifecycle.retired"]
+
+
+async def published_by_the_previous_build(
+    api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, settings: Any, monkeypatch: pytest.MonkeyPatch
+) -> Any:
+    """A version as the build before this one published it: stamped with the ABI before this build's."""
+    with monkeypatch.context() as m:
+        m.setattr(workflow_ops, "ENGINE_ABI", ENGINE_ABI - 1)
+        version = (await publish(api_sessionmaker, ctx, wf_id, settings)).version
+    assert version is not None and version.engine_abi == ENGINE_ABI - 1
+    return version
+
+
+async def test_publish_refuses_to_pin_a_sub_flow_or_failure_handler_of_another_abi(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, monkeypatch
+) -> None:
+    """Spec §7: a version runs only on a build of its engine ABI. Publishing a parent again on its own, while a
+    workflow it runs still has an older ABI's version, would leave it running that version: refused, until that
+    workflow is published again."""
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
+    old = await published_by_the_previous_build(api_sessionmaker, ctx, child, api_settings, monkeypatch)
+    handled = G().node("a", "testkit.echo@1", {"value": 1})
+    handled.settings["failure_handler"] = str(child)
+    reason = (
+        f"Version {old.id}, a sub-flow or failure handler this workflow would run, was published for engine ABI "
+        f"{ENGINE_ABI - 1}, and this build publishes ABI {ENGINE_ABI}."
+    )
+    parents = [
+        await create(api_sessionmaker, ctx, draft, name=name)
+        for name, draft in (("runs it", runs(child)), ("handles with it", handled.data()))
+    ]
+    for parent in parents:
+        out = await publish(api_sessionmaker, ctx, parent, api_settings)
+        assert out.version is None
+        assert [(d.code, d.message, d.fix) for d in out.errors] == [
+            ("subflow.engine_abi", reason, "Publish that workflow again first.")
+        ]
+    await save(api_sessionmaker, ctx, child, ECHO_GRAPH)
+    assert (await publish(api_sessionmaker, ctx, child, api_settings)).version is not None  # the child, again
+    for parent in parents:
+        assert (await publish(api_sessionmaker, ctx, parent, api_settings)).version is not None


 async def test_retiring_a_subflow_type_blocks_its_parents(
```

In `backend/tests/apps/test_runs.py`, admission. `FakeClient`'s deployment says which build is current:

```diff
diff --git a/backend/tests/apps/test_runs.py b/backend/tests/apps/test_runs.py
--- a/backend/tests/apps/test_runs.py
+++ b/backend/tests/apps/test_runs.py
@@ -9,20 +9,40 @@
 from typing import Any

 import pytest
+from temporalio.api.workflowservice.v1 import DescribeWorkerDeploymentRequest, DescribeWorkerDeploymentResponse
 from temporalio.common import WorkflowIDReusePolicy
 from temporalio.exceptions import WorkflowAlreadyStartedError
 from temporalio.service import RPCError, RPCStatusCode

 from dewpoint.apps import runs as run_ops
 from dewpoint.apps import workflow_ops
-from dewpoint.apps.runs import START_FAILED, NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
+from dewpoint.apps.runs import (
+    NO_CURRENT_BUILD,
+    START_FAILED,
+    NotAdmissibleError,
+    StartRefusedError,
+    StartUncertainError,
+    start_run,
+)
+from dewpoint.apps.worker.deployment import this_build
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.runs import service
 from dewpoint.core.workflows import service as workflows
+from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, SIMULATE, RunInput
 from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock
-from tests.apps.test_workflow_ops import ECHO, ECHO_GRAPH, actor, create, publish, save, update
+from tests.apps.test_workflow_ops import (
+    ECHO,
+    ECHO_GRAPH,
+    actor,
+    create,
+    publish,
+    published_by_the_previous_build,
+    runs,
+    save,
+    update,
+)
 from tests.support.registry import sync_test_plugins


@@ -37,11 +57,29 @@
     return RPCError(status.name.lower(), status, b"")


+class FakeDeployment:
+    """Temporal's `dewpoint-engine` deployment, as admission reads it: its current build (None: there's none)."""
+
+    def __init__(self, current: str | None) -> None:
+        self.current = current
+
+    async def describe_worker_deployment(self, _request: DescribeWorkerDeploymentRequest) -> Any:
+        if self.current is None:
+            raise rpc(RPCStatusCode.NOT_FOUND)  # no worker has joined it
+        response = DescribeWorkerDeploymentResponse()
+        response.worker_deployment_info.routing_config.current_deployment_version.build_id = self.current
+        return response
+
+
 class FakeClient:
     """Temporal's start, as start_run sees it. Each call takes the next answer: None accepts, an exception refuses,
-    and a LostAck accepts but raises. Like the server, it refuses a workflow id it already accepted."""
-
-    def __init__(self, *answers: BaseException | LostAck | None) -> None:
+    and a LostAck accepts but raises. Like the server, it refuses a workflow id it already accepted. Its deployment's
+    current build is this one unless a test says otherwise."""
+
+    namespace = "default"
+
+    def __init__(self, *answers: BaseException | LostAck | None, current: str | None = this_build()) -> None:
+        self.workflow_service = FakeDeployment(current)
         self.answers = list(answers)
         self.started: list[tuple[RunInput, str, str]] = []
         self.calls: list[tuple[str, WorkflowIDReusePolicy]] = []
@@ -114,6 +152,92 @@
             dispatch_sessionmaker, FakeClient(), api_settings,  # type: ignore[arg-type]
             tenant_id=ctx.tenant_id, version_id=first, trigger={},
         )  # fmt: skip
+
+
+async def test_a_version_of_another_abi_is_refused_until_its_workflows_are_published_again(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
+) -> None:
+    """Spec §7: a version runs only on a build of its engine ABI. Once a build with a new ABI is current, a version the
+    build before published is refused, and so is one that runs such a version as a sub-flow, until each workflow is
+    published again: the sub-flow first, since publishing refuses a parent that pins an older ABI's version."""
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    child = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="child")
+    parent = await create(api_sessionmaker, ctx, runs(child), name="parent")
+    old_child = await published_by_the_previous_build(api_sessionmaker, ctx, child, api_settings, monkeypatch)
+    old_parent = await published_by_the_previous_build(api_sessionmaker, ctx, parent, api_settings, monkeypatch)
+
+    async def started(version_id: uuid.UUID) -> uuid.UUID:
+        return await start_run(
+            dispatch_sessionmaker, FakeClient(), api_settings,  # type: ignore[arg-type]
+            tenant_id=ctx.tenant_id, version_id=version_id, trigger={},
+        )  # fmt: skip
+
+    with pytest.raises(NotAdmissibleError) as refused:
+        await started(old_parent.id)
+    old = ENGINE_ABI - 1
+    assert sorted(refused.value.reasons) == sorted(
+        [
+            f"This version was published for engine ABI {old}, and the current build runs ABI {ENGINE_ABI}: publish "
+            f"the workflow again with a build of ABI {ENGINE_ABI}.",
+            f"Version {old_child.id}, a sub-flow or failure handler it runs, was published for engine ABI {old}, and "
+            f"the current build runs ABI {ENGINE_ABI}: publish that workflow again with a build of ABI {ENGINE_ABI}, "
+            "then this one.",
+        ]
+    )
+    await save(api_sessionmaker, ctx, parent, runs(child))
+    assert [d.code for d in (await publish(api_sessionmaker, ctx, parent, api_settings)).errors] == [
+        "subflow.engine_abi"
+    ]  # the parent alone can't be published again
+    await save(api_sessionmaker, ctx, child, ECHO_GRAPH)
+    assert (await publish(api_sessionmaker, ctx, child, api_settings)).version is not None
+    new_parent = (await publish(api_sessionmaker, ctx, parent, api_settings)).version
+    assert new_parent is not None
+    run_id = await started(new_parent.id)
+    assert (await run_row(owner_sessionmaker, ctx.tenant_id, run_id)).status == "running"
+
+
+async def test_admission_compares_with_the_current_build_not_the_admitting_one(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
+) -> None:
+    """During a rollout, both builds' processes admit runs, and a run starts on the deployment's current build. Before
+    this build is promoted, the build before it is current: this process admits that build's versions, and refuses
+    its own, which the current build can't run (and the reverse after the promotion)."""
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    old_wf = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="old")
+    new_wf = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="new")
+    old = await published_by_the_previous_build(api_sessionmaker, ctx, old_wf, api_settings, monkeypatch)
+    new = (await publish(api_sessionmaker, ctx, new_wf, api_settings)).version
+    assert new is not None
+    previous = f"dewpoint-0.1.0+abi{ENGINE_ABI - 1}"  # current: this build isn't promoted yet
+    run_id = await start_run(
+        dispatch_sessionmaker, FakeClient(current=previous), api_settings,  # type: ignore[arg-type]
+        tenant_id=ctx.tenant_id, version_id=old.id, trigger={},
+    )  # fmt: skip
+    assert (await run_row(owner_sessionmaker, ctx.tenant_id, run_id)).workflow_version_id == old.id
+    with pytest.raises(NotAdmissibleError) as refused:
+        await start_run(
+            dispatch_sessionmaker, FakeClient(current=previous), api_settings,  # type: ignore[arg-type]
+            tenant_id=ctx.tenant_id, version_id=new.id, trigger={},
+        )  # fmt: skip
+    assert refused.value.reasons == [
+        f"This version was published for engine ABI {ENGINE_ABI}, and the current build runs ABI {ENGINE_ABI - 1}: "
+        f"make a build of ABI {ENGINE_ABI} current first."
+    ]
+
+
+async def test_nothing_is_admitted_while_no_build_is_current(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    client = FakeClient(current=None)
+    with pytest.raises(NotAdmissibleError) as refused:
+        await start_run(
+            dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
+            tenant_id=ctx.tenant_id, version_id=version, trigger={},
+        )  # fmt: skip
+    assert refused.value.reasons == [NO_CURRENT_BUILD] and client.started == []


 async def only_run(owner: Any, tenant: uuid.UUID) -> Any:
@@ -376,4 +500,4 @@
         assert held is not None and held.enabled and held.active_version_id == version
         await change_committed(api_sessionmaker, ctx, wf, change)
         with pytest.raises(NotAdmissibleError, match=REFUSED[how]):
-            await run_ops.admit(s, tenant_id=ctx.tenant_id, version_id=version)
+            await run_ops.admit(s, tenant_id=ctx.tenant_id, version_id=version, abi=ENGINE_ABI)
```

In `backend/tests/apps/worker/harness.py`, the harness's support for these tests:

```diff
diff --git a/backend/tests/apps/worker/harness.py b/backend/tests/apps/worker/harness.py
--- a/backend/tests/apps/worker/harness.py
+++ b/backend/tests/apps/worker/harness.py
@@ -15,6 +15,7 @@
 from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

 from dewpoint.apps.worker.activities import Evaluate, RunStore, cel_activity, engine_activities
+from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.cel import ipc
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, validate
@@ -51,8 +52,9 @@
     starts: dict[str, RunStart] = field(default_factory=dict)  # sub-runs' own rows
     schemas: dict[str, dict[str, Any]] = field(default_factory=dict)  # version -> its output schema

-    def add(self, g: G, workflow_id: uuid.UUID | None = None) -> str:
-        """Publish `g` as a version, pinned to the sub-flows it runs (as `publish` registered them)."""
+    def add(self, g: G, workflow_id: uuid.UUID | None = None, *, engine_abi: int = ENGINE_ABI) -> str:
+        """Publish `g` as a version, pinned to the sub-flows it runs (as `publish` registered them). `engine_abi`:
+        the build that published it, this one unless a test says otherwise."""
         result = validate(g.build(), ValidationContext(catalog=CATALOG, subflows=self.subflows))
         errors = [d.to_json() for d in result.diagnostics if d.severity == "error"]
         assert not errors, errors
@@ -68,14 +70,16 @@
             manifests={r: MANIFESTS[r] for r in sorted(refs)},
             subflow_version_ids=dict(result.subflow_pins),
             failure_handler_version_id=str(handler) if handler else None,
+            engine_abi=engine_abi,
         )
         self.schemas[version_id] = dict(result.output_schema)
         return version_id

-    def publish(self, g: G) -> uuid.UUID:
-        """A workflow other graphs can run as a sub-flow or a failure handler: its id."""
-        workflow_id = uuid.uuid4()
-        version_id = self.add(g, workflow_id)
+    def publish(self, g: G, workflow_id: uuid.UUID | None = None, *, engine_abi: int = ENGINE_ABI) -> uuid.UUID:
+        """A workflow other graphs can run as a sub-flow or a failure handler: its id. With `workflow_id`, a new
+        version of that workflow, which graphs published from now on pin."""
+        workflow_id = workflow_id or uuid.uuid4()
+        version_id = self.add(g, workflow_id, engine_abi=engine_abi)
         input_schema = g.settings.get("input_schema", {"type": "object"})
         self.subflows[workflow_id] = SubflowInfo(
             workflow_id, uuid.UUID(version_id), input_schema, self.schemas[version_id]
@@ -138,8 +142,15 @@
 async def start(
     client: Client, store: MemoryStore, g: G, trigger: dict[str, Any] | None = None, **options: Any
 ) -> WorkflowHandle[Any, RunResult]:
+    return await start_version(client, store.add(g), trigger, **options)
+
+
+async def start_version(
+    client: Client, version_id: str, trigger: dict[str, Any] | None = None, **options: Any
+) -> WorkflowHandle[Any, RunResult]:
+    """A run of a version the store already has."""
     run_id = str(uuid.uuid4())
-    run = RunInput(TENANT, run_id, store.add(g), trigger or {}, options.pop("mode", LIVE), **options)
+    run = RunInput(TENANT, run_id, version_id, trigger or {}, options.pop("mode", LIVE), **options)
     return await client.start_workflow(RunGraph.run, run, id=run_id, task_queue=ENGINE_QUEUE)


```

Create `backend/tests/apps/worker/test_run_graph_abi.py`, the loader's backstop:

```python
# SPDX-License-Identifier: Apache-2.0
"""A version runs only on a build of its engine ABI (spec §7). Admission refuses to start one of another ABI than the
current build's (tests/apps/test_runs.py, test_admission_abi.py), and publishing refuses to pin one
(tests/apps/test_workflow_ops.py). The version loader is the backstop, for a promotion that races a start: a run, a
sub-flow or a failure handler whose version was published for another ABI fails `version_unusable` before any of its
steps runs, saying to publish the workflow again."""

import asyncio
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.engine import ENGINE_ABI
from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, start, start_version, workers
from tests.support.graphs import G

OLD = ENGINE_ABI - 1  # the build before this one
ECHO, RUN = "testkit.echo@1", "flow.run_workflow@1"
REFUSED = (
    f"This version was published for engine ABI {OLD}, and this build runs ABI {ENGINE_ABI}: publish the workflow "
    f"again with a build of ABI {ENGINE_ABI}."
)


def echo() -> G:
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {}}
    return g.node("a", ECHO, {"value": 1})


async def test_a_version_of_another_abi_fails_before_any_step_runs(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    version = store.add(echo(), engine_abi=OLD)
    async with workers(env.client, store):
        handle = await start_version(env.client, version)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert result.error is not None
    assert (result.status, result.error["code"], result.error["message"]) == ("failed", "version_unusable", REFUSED)
    assert store.steps(handle.id) == []


async def test_a_sub_flow_or_failure_handler_of_another_abi_fails_where_it_starts(env: WorkflowEnvironment) -> None:
    """A parent of this build's ABI that still pins them: each fails as it loads, and the run's end, decided before
    its failure handler ran, stands."""
    store = MemoryStore()
    sub, handler = store.publish(echo(), engine_abi=OLD), store.publish(echo(), engine_abi=OLD)
    g = G()
    g.settings = {"input_schema": {"type": "object"}, "outputs": {}, "failure_handler": str(handler)}
    g.node("r", RUN, {"workflow_id": str(sub), "input": {}})
    async with workers(env.client, store):
        handle = await start(env.client, store, g)
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
    assert (result.status, result.error["code"] if result.error else None) == ("failed", "version_unusable")
    ended: dict[str, Any] = {
        row.kind: (store.runs[child].status, store.runs[child].error_code, store.runs[child].error_message)
        for child, row in store.starts.items()
    }
    assert ended == {
        "subflow": ("failed", "version_unusable", REFUSED),
        "failure_handler": ("failed", "version_unusable", REFUSED),
    }
```

In `backend/tests/apps/worker/test_two_builds.py`, the promotion case, on the dev server. The old build's run is
pinned before the promotion: `pinned` waits for its first workflow task.

```diff
diff --git a/backend/tests/apps/worker/test_two_builds.py b/backend/tests/apps/worker/test_two_builds.py
--- a/backend/tests/apps/worker/test_two_builds.py
+++ b/backend/tests/apps/worker/test_two_builds.py
@@ -4,20 +4,26 @@
 activities, a sub-flow, a loop batch, CEL and continue-as-new. Every engine task of it (workflow tasks and
 `dewpoint-engine` activities, in the run, its children and its continued runs) runs on N-1. `cel.evaluate` is outside
 the deployment, deliberately: each CEL task runs on a worker serving the version's profile. Once its runs have ended,
-N-1 reports itself drained."""
+N-1 reports itself drained.
+
+A new engine ABI adds a rule: a version runs only on a build of its ABI. After the promotion, a new run of a version
+the old build published, or of one pinning such a sub-flow, fails until each workflow is published again."""

 import asyncio
+from typing import Any

+from temporalio.client import WorkflowHandle
 from temporalio.testing import WorkflowEnvironment
 from temporalio.worker import Worker

 from dewpoint.apps.worker.activities import cel_activity
 from dewpoint.apps.worker.deployment import describe, set_current
 from dewpoint.apps.worker.main import engine_worker
+from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import cel_queue
 from dewpoint.sdk import Plugin
-from tests.apps.worker.harness import MemoryStore, in_process, start
+from tests.apps.worker.harness import MemoryStore, in_process, start, start_version
 from tests.apps.worker.test_deployment import build, placement
 from tests.apps.worker.test_main import settings
 from tests.engine.replay.record import executions
@@ -84,3 +90,62 @@
             assert ran.builds == {expected} and ran.engine <= {expected}, (history.workflow_id, ran)
             cel_tasks |= ran.cel
         assert cel_tasks == {(cel_queue(CURRENT_CEL_PROFILE), CEL)}  # on the version's profile, and only there
+
+
+async def pinned(handle: WorkflowHandle[Any, Any]) -> None:
+    """Until the run's first workflow task has completed: from then on, it's pinned to that task's build."""
+    for _ in range(100):
+        if any(e.HasField("workflow_task_completed_event_attributes") for e in (await handle.fetch_history()).events):
+            return
+        await asyncio.sleep(0.1)
+    raise AssertionError(f"{handle.id}'s first workflow task never completed")
+
+
+async def test_after_a_new_abi_is_promoted_old_versions_wait_to_be_published_again(
+    dev_env: WorkflowEnvironment,
+) -> None:
+    """N-1 runs the ABI before N's. A run it started finishes there, its sub-flow included. Once N is current, a new
+    run of a version N-1 published fails before any step runs; so does the sub-flow of a parent published again on
+    its own. Published again, child first, the workflow runs on N."""
+    client, n1, n = dev_env.client, build("abi-n-1"), build("abi-n")
+    old = ENGINE_ABI - 1
+    store = MemoryStore()
+    child = G()
+    child.settings = {"input_schema": {"type": "object"}, "outputs": {"v": ref("steps.a.output.value")}}
+    child.node("a", "testkit.echo@1", {"value": 1})
+    child_id = store.publish(child, engine_abi=old)
+
+    def parent() -> G:
+        g = G()
+        g.settings = {"input_schema": {"type": "object"}, "outputs": {"v": ref("steps.r.output.v")}}
+        g.node("s", "testkit.slow@1", {"seconds": 2})
+        g.node("r", "flow.run_workflow@1", {"workflow_id": str(child_id), "input": {}})
+        return g.edge("s", "r")
+
+    old_parent = store.add(parent(), engine_abi=old)
+    async with engine_worker(client, store, [TESTKIT], settings(), build=n1, identity=n1, abi=old):
+        await set_current(client, n1)
+        on_old = await start_version(client, old_parent)  # in its slow step when N takes over
+        await pinned(on_old)
+        async with engine_worker(client, store, [TESTKIT], settings(), build=n, identity=n):
+            await set_current(client, n)
+            refused = await start_version(client, old_parent)
+            parent_only = await start_version(client, store.add(parent()))  # it still pins N-1's child
+            store.publish(child, child_id)
+            both = await start_version(client, store.add(parent()))
+            handles = (on_old, refused, parent_only, both)
+            done = await asyncio.wait_for(asyncio.gather(*(h.result() for h in handles)), 120)
+        chain = await executions(client, on_old.id, on_old.first_execution_run_id or "")
+    refusal = f"This version was published for engine ABI {old}, and this build runs ABI {ENGINE_ABI}: publish the "
+    refusal += f"workflow again with a build of ABI {ENGINE_ABI}."
+    ended = [(r.status, (r.error or {}).get("code"), r.outputs) for r in done]
+    assert ended == [
+        ("succeeded", None, {"v": 1}),
+        ("failed", "version_unusable", None),
+        ("failed", "version_unusable", None),
+        ("succeeded", None, {"v": 1}),
+    ]
+    assert (done[1].error or {}).get("message") == refusal
+    [sub_run] = [c for c, row in store.starts.items() if row.parent_run_id == parent_only.id]
+    assert (store.runs[sub_run].error_code, store.runs[sub_run].error_message) == ("version_unusable", refusal)
+    assert len(chain) == 2 and all(placement(h).builds == {n1} for h in chain)  # the run and its sub-flow, on N-1
```

Create `backend/tests/apps/worker/test_admission_abi.py`, admission through a promotion, on the dev server with the
database. The run admitted before the promotion ends before it, so that nothing races:

```python
# SPDX-License-Identifier: Apache-2.0
"""Admission and the deployment's current build (spec §7), on Temporal's dev server with the database. A new run
starts on the deployment's current build, so a version is admitted only when that build runs its engine ABI,
whichever build's process admits it: during a rollout, both builds' processes start runs. The version loader stays
the backstop for a promotion that races a start (test_run_graph_abi.py, test_two_builds.py)."""

import uuid
from typing import Any

import pytest
from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.runs import NotAdmissibleError, start_run
from dewpoint.apps.worker.deployment import current_abi, set_current, this_build
from dewpoint.apps.worker.main import engine_worker
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine import ENGINE_ABI
from dewpoint.engine.runtime.build import abi_of
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.test_workflow_ops import ECHO_GRAPH, actor, create, publish, published_by_the_previous_build
from tests.apps.worker.test_deployment import placement
from tests.apps.worker.test_main import settings
from tests.engine.replay.record import executions
from tests.support.plugins.testkit import TESTKIT
from tests.support.registry import sync_test_plugins

OLD, NEW = ENGINE_ABI - 1, ENGINE_ABI  # the build before this one, and this one


def dewpoint_build(abi: int) -> str:
    """A build ID of the test's own that names `abi`, as a Dewpoint build's does."""
    return f"dewpoint-0.0.0.dev{uuid.uuid4().int % 10**9}+abi{abi}"


def test_a_build_id_names_its_abi() -> None:
    assert (abi_of(this_build()), abi_of("dewpoint-0.1.0+abi12")) == (ENGINE_ABI, 12)
    assert [abi_of(b) for b in ("n-1-3f2a", "dewpoint-0.1.0", "other-0.1.0+abi3", "dewpoint-0.1.0+abix")] == [None] * 4


async def test_admission_follows_the_current_build_through_a_promotion(
    dev_env: WorkflowEnvironment,
    owner_sessionmaker: Any,
    api_sessionmaker: Any,
    admin_sessionmaker: Any,
    dispatch_sessionmaker: Any,
    worker_sessionmaker: Any,
    api_settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This process is build N's. Before N is promoted, N-1 is current: N-1's version is admitted and runs on N-1, and
    N's own version is refused. After the promotion it's the other way round: N-1's version is refused, as it would be
    from an N-1 process, and N's runs on N."""
    client = dev_env.client
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    old_wf = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="published by N-1")
    new_wf = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="published by N")
    old = await published_by_the_previous_build(api_sessionmaker, ctx, old_wf, api_settings, monkeypatch)
    new = (await publish(api_sessionmaker, ctx, new_wf, api_settings)).version
    assert new is not None

    async def started(version_id: uuid.UUID) -> uuid.UUID:
        return await start_run(
            dispatch_sessionmaker, client, api_settings, tenant_id=ctx.tenant_id, version_id=version_id, trigger={}
        )

    store = DbRunStore(worker_sessionmaker)
    n1, n = dewpoint_build(OLD), dewpoint_build(NEW)
    async with engine_worker(client, store, [TESTKIT], settings(), build=n1, identity=n1, abi=OLD):
        await set_current(client, n1)
        async with engine_worker(client, store, [TESTKIT], settings(), build=n, identity=n):
            assert await current_abi(client) == OLD
            with pytest.raises(NotAdmissibleError) as early:
                await started(new.id)
            on_old = await started(old.id)
            # it ends before the promotion: a run whose first task hadn't run yet would start on N, and fail as it
            # loads its version (the loader's backstop, for a promotion that races a start)
            results = [await client.get_workflow_handle_for(RunGraph.run, str(on_old)).result()]
            await set_current(client, n)
            assert await current_abi(client) == NEW
            with pytest.raises(NotAdmissibleError) as late:
                await started(old.id)
            on_new = await started(new.id)
            results.append(await client.get_workflow_handle_for(RunGraph.run, str(on_new)).result())
            chains = [await executions(client, str(r), "") for r in (on_old, on_new)]
    assert early.value.reasons == [
        f"This version was published for engine ABI {NEW}, and the current build runs ABI {OLD}: make a build of ABI "
        f"{NEW} current first."
    ]
    assert late.value.reasons == [
        f"This version was published for engine ABI {OLD}, and the current build runs ABI {NEW}: publish the workflow "
        f"again with a build of ABI {NEW}."
    ]
    assert [r.status for r in results] == ["succeeded", "succeeded"]
    assert [placement(chain[0]).builds for chain in chains] == [{n1}, {n}]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/test_workflow_ops.py tests/apps/test_runs.py tests/apps/worker/test_worker_db.py tests/apps/worker/test_dev_run.py tests/apps/worker/test_run_graph_abi.py tests/apps/worker/test_two_builds.py tests/apps/worker/test_admission_abi.py`
Expected: 2 errors during collection, which stop the run:
`ImportError: cannot import name 'NO_CURRENT_BUILD' from 'dewpoint.apps.runs'` (`test_runs.py`) and
`ImportError: cannot import name 'current_abi' from 'dewpoint.apps.worker.deployment'` (`test_admission_abi.py`).
Steps 3 and 4 add them.

- [ ] **Step 3: The current build's ABI**

In `backend/src/dewpoint/engine/runtime/build.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/build.py b/backend/src/dewpoint/engine/runtime/build.py
--- a/backend/src/dewpoint/engine/runtime/build.py
+++ b/backend/src/dewpoint/engine/runtime/build.py
@@ -11,4 +11,10 @@
     return f"dewpoint-{version}+abi{ENGINE_ABI}"


-__all__ = ["build_id"]
+def abi_of(build: str) -> int | None:
+    """The engine ABI a Dewpoint build ID names; None for an ID that isn't one."""
+    name, plus, abi = build.rpartition("+abi")
+    return int(abi) if plus and name.startswith("dewpoint-") and abi.isdecimal() else None
+
+
+__all__ = ["abi_of", "build_id"]
```

In `backend/src/dewpoint/apps/worker/deployment.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/deployment.py b/backend/src/dewpoint/apps/worker/deployment.py
--- a/backend/src/dewpoint/apps/worker/deployment.py
+++ b/backend/src/dewpoint/apps/worker/deployment.py
@@ -18,7 +18,7 @@
 from temporalio.worker import WorkerDeploymentConfig

 import dewpoint
-from dewpoint.engine.runtime.build import build_id
+from dewpoint.engine.runtime.build import abi_of, build_id

 DEPLOYMENT = "dewpoint-engine"
 IDENTITY = "dewpoint-deployment"  # who changed the routing, as Temporal records it
@@ -80,3 +80,15 @@
         for v in info.version_summaries
     ]
     return Deployment(current, sorted(versions, key=lambda v: v.build_id))
+
+
+async def current_abi(client: Client) -> int | None:
+    """The engine ABI of the deployment's current build: new runs start on it, so admission compares versions with it
+    (§7). None when no Dewpoint build is current, or no worker has ever joined the deployment."""
+    try:
+        current = (await describe(client)).current
+    except RPCError as e:
+        if e.status == RPCStatusCode.NOT_FOUND:
+            return None
+        raise
+    return abi_of(current) if current else None
```

- [ ] **Step 4: Publishing and admission**

In `backend/src/dewpoint/core/workflows/service.py`:

```diff
diff --git a/backend/src/dewpoint/core/workflows/service.py b/backend/src/dewpoint/core/workflows/service.py
--- a/backend/src/dewpoint/core/workflows/service.py
+++ b/backend/src/dewpoint/core/workflows/service.py
@@ -265,6 +265,20 @@
     return {workflow_id: version for workflow_id, version in rows}


+async def other_abi(s: AsyncSession, version_ids: Iterable[uuid.UUID], abi: int) -> list[tuple[uuid.UUID, int]]:
+    """The versions among `version_ids` published for an engine ABI other than `abi`, each with its own. A version
+    runs only on a build of its ABI (spec §7)."""
+    ids = sorted(set(version_ids), key=str)
+    if not ids:
+        return []
+    rows = await s.execute(
+        select(WorkflowVersion.id, WorkflowVersion.engine_abi)
+        .where(WorkflowVersion.id.in_(ids), WorkflowVersion.engine_abi != abi)
+        .order_by(WorkflowVersion.id)
+    )
+    return [(version_id, version_abi) for version_id, version_abi in rows]
+
+
 async def blocked_by(s: AsyncSession, version: WorkflowVersion) -> list[str]:
     """Lifecycle entries in the version's closure that stop it from running (retired or missing)."""
     current = await lifecycle.states(s, lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles))
```

In `backend/src/dewpoint/apps/workflow_ops.py`:

```diff
diff --git a/backend/src/dewpoint/apps/workflow_ops.py b/backend/src/dewpoint/apps/workflow_ops.py
--- a/backend/src/dewpoint/apps/workflow_ops.py
+++ b/backend/src/dewpoint/apps/workflow_ops.py
@@ -115,6 +115,41 @@
     return out


+def abi_reasons(version_id: uuid.UUID, stale: list[tuple[uuid.UUID, int]], current: int) -> list[str]:
+    """Why `version_id` can't start runs on the current build, of engine ABI `current`: it, or a version it runs, was
+    published for another. A version runs only on a build of its ABI (spec §7): an older one is published again with
+    the current build, and a newer one waits for its own build to be made current."""
+
+    def remedy(abi: int, what: str) -> str:
+        if abi > current:
+            return f"make a build of ABI {abi} current first"
+        return f"publish {what} again with a build of ABI {current}"
+
+    return [
+        f"This version was published for engine ABI {abi}, and the current build runs ABI {current}: "
+        f"{remedy(abi, 'the workflow')}."
+        if other == version_id
+        else f"Version {other}, a sub-flow or failure handler it runs, was published for engine ABI {abi}, and the "
+        f"current build runs ABI {current}: {remedy(abi, 'that workflow')}, then this one."
+        for other, abi in stale
+    ]
+
+
+async def _pin_abi_errors(s: AsyncSession, pins: list[WorkflowVersion]) -> list[Diagnostic]:
+    """Every version a new one would run must be of the ABI it's published for, this build's (spec §7): so a parent is
+    published again only after its sub-flows and failure handler."""
+    stale = await service.other_abi(s, [i for v in pins for i in v.closure_version_ids], ENGINE_ABI)
+    return [
+        Diagnostic(
+            code="subflow.engine_abi",
+            message=f"Version {other}, a sub-flow or failure handler this workflow would run, was published for engine "
+            f"ABI {abi}, and this build publishes ABI {ENGINE_ABI}.",
+            fix="Publish that workflow again first.",
+        )
+        for other, abi in stale
+    ]
+
+
 async def publish(
     s: AsyncSession, ctx: TenantContext, wf: Workflow, *, expected_revision: int, settings: Settings
 ) -> Published:
@@ -130,6 +165,9 @@
     if errors:
         return Published(None, errors, warnings)
     pins = list(checked.pins.values())
+    errors = await _pin_abi_errors(s, pins)
+    if errors:
+        return Published(None, errors, warnings)
     closure_node_refs = sorted({*checked.result.node_refs, *(r for v in pins for r in v.closure_node_refs)})
     closure_cel_profiles = sorted({CURRENT_CEL_PROFILE, *(p for v in pins for p in v.closure_cel_profiles)})
     entries = lifecycle.entries_for(closure_node_refs, closure_cel_profiles)
```

In `backend/src/dewpoint/apps/runs.py`:

```diff
diff --git a/backend/src/dewpoint/apps/runs.py b/backend/src/dewpoint/apps/runs.py
--- a/backend/src/dewpoint/apps/runs.py
+++ b/backend/src/dewpoint/apps/runs.py
@@ -1,7 +1,9 @@
 # SPDX-License-Identifier: Apache-2.0
 """Starting runs (spec §9). `start_run` is 2a's admission, and 2b's dispatcher reuses `admit`: the workflow is
-enabled, the version is its active one, and nothing in the version's closure is retired. All three are checked in the
-transaction that inserts the run (§4.5), under locks the other side takes too:
+enabled, the version is its active one, every version in its closure was published for the engine ABI of the
+deployment's current build (a version runs only on a build of its ABI, and a new run starts on the current build,
+§7), and nothing in the closure is retired. They're checked in the transaction that inserts the run (§4.5), under
+locks the other side takes too:
 - the workflow is read under its admission lock (shared), so a disable, publish or activation either commits before
   the read or waits until the run exists;
 - the closure is read under the lifecycle locks (shared), so a retirement either sees the run or the run sees the
@@ -23,17 +25,23 @@
 from temporalio.exceptions import WorkflowAlreadyStartedError
 from temporalio.service import RPCError, RPCStatusCode

+from dewpoint.apps.worker.deployment import current_abi
+from dewpoint.apps.workflow_ops import abi_reasons
 from dewpoint.core.config import Settings
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.runs import Run
 from dewpoint.core.models.workflows import WorkflowVersion
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.runs import service as runs
-from dewpoint.core.workflows.service import lock_for_admission
+from dewpoint.core.workflows.service import lock_for_admission, other_abi
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, LIVE, RunInput
 from dewpoint.engine.runtime.workflow import RunGraph

 START_FAILED = "start_failed"
+NO_CURRENT_BUILD = (
+    "No Dewpoint build is current in the `dewpoint-engine` deployment, so no worker would run it: make one current "
+    "with `dewpoint deployment set-current`."
+)
 START_RETRY_S = (0.5, 2.0)  # the waits between three attempts to start a run
 # Temporal refused the request itself, so it started nothing. Any other failure may follow an accepted start.
 _REFUSED = frozenset(
@@ -78,10 +86,13 @@
     *,
     tenant_id: uuid.UUID,
     version_id: uuid.UUID,
+    abi: int | None,
     mode: str = LIVE,
     started_by: uuid.UUID | None = None,
 ) -> Run:
-    """Insert the run, or raise NotAdmissibleError. Call it inside a READ COMMITTED transaction."""
+    """Insert the run, or raise NotAdmissibleError. Call it inside a READ COMMITTED transaction. `abi` is the engine
+    ABI of the deployment's current build, where the run will start (`current_abi`; None: no build is current). The
+    admitting process's own build doesn't matter: during a rollout, both builds' processes admit runs."""
     await tenant_scope(s, tenant_id)
     version = await s.get(WorkflowVersion, version_id)
     if version is None:
@@ -91,6 +102,11 @@
         raise NotAdmissibleError(["The workflow is disabled."])
     if workflow.active_version_id != version.id:
         raise NotAdmissibleError(["Only the workflow's active version can start runs."])
+    if abi is None:
+        raise NotAdmissibleError([NO_CURRENT_BUILD])
+    stale = await other_abi(s, version.closure_version_ids, abi)  # versions never change: no lock needed
+    if stale:
+        raise NotAdmissibleError(abi_reasons(version.id, stale, abi))
     entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
     await lifecycle.lock_shared(s, entries)
     await _admission_locked()
@@ -120,9 +136,11 @@
     started_by: uuid.UUID | None = None,
 ) -> uuid.UUID:
     """Admit the run and start it. Raises NotAdmissibleError, StartRefusedError (the run is recorded as failed) or
-    StartUncertainError (the run stays `running`: it may be executing)."""
+    StartUncertainError (the run stays `running`: it may be executing). A promotion between the admission and the
+    start is caught when the run loads its version (§7)."""
+    abi = await current_abi(client)  # before the transaction: no lock is held across a call to Temporal
     async with sessionmaker() as s, s.begin():
-        run = await admit(s, tenant_id=tenant_id, version_id=version_id, mode=mode, started_by=started_by)
+        run = await admit(s, tenant_id=tenant_id, version_id=version_id, abi=abi, mode=mode, started_by=started_by)
     start = RunInput(
         tenant_id=str(tenant_id),
         run_id=str(run.id),
@@ -175,6 +193,7 @@

 __all__ = [
     "START_FAILED",
+    "NO_CURRENT_BUILD",
     "START_RETRY_S",
     "NotAdmissibleError",
     "StartRefusedError",
```

`start_run` now asks Temporal which build is current, and the time-skipping server has no deployments. The tests
that start runs through admission on it stand in for the answer. In `backend/tests/apps/worker/conftest.py`:

```diff
diff --git a/backend/tests/apps/worker/conftest.py b/backend/tests/apps/worker/conftest.py
--- a/backend/tests/apps/worker/conftest.py
+++ b/backend/tests/apps/worker/conftest.py
@@ -2,7 +2,11 @@
 from collections.abc import AsyncIterator

 import pytest
+from temporalio.client import Client
 from temporalio.testing import WorkflowEnvironment
+
+from dewpoint.apps import runs as run_ops
+from dewpoint.engine import ENGINE_ABI


 @pytest.fixture(scope="session")
@@ -33,3 +37,15 @@
     args = [a for key in drainage for a in ("--dynamic-config-value", f'{key}="1s"')]
     async with await WorkflowEnvironment.start_local(dev_server_extra_args=args) as environment:
         yield environment
+
+
+@pytest.fixture
+def this_build_is_current(monkeypatch: pytest.MonkeyPatch) -> None:
+    """For tests that start runs through admission on the time-skipping server, which has no Worker Deployments:
+    admission takes this build as the deployment's current one. The deployment's own answer is tested on the dev
+    server (test_admission_abi.py)."""
+
+    async def current_abi(_client: Client) -> int:
+        return ENGINE_ABI
+
+    monkeypatch.setattr(run_ops, "current_abi", current_abi)
```

In `backend/tests/apps/worker/test_worker_db.py`:

```diff
diff --git a/backend/tests/apps/worker/test_worker_db.py b/backend/tests/apps/worker/test_worker_db.py
--- a/backend/tests/apps/worker/test_worker_db.py
+++ b/backend/tests/apps/worker/test_worker_db.py
@@ -7,6 +7,7 @@
 from datetime import UTC, datetime
 from typing import Any

+import pytest
 from temporalio.testing import WorkflowEnvironment

 from dewpoint.apps.runs import start_run
@@ -21,6 +22,8 @@
 from tests.core.runs.test_service import seeded_run
 from tests.support.graphs import G, cel, ref
 from tests.support.registry import sync_test_plugins
+
+pytestmark = pytest.mark.usefixtures("this_build_is_current")  # its runs start on the time-skipping server


 def graph() -> dict[str, Any]:
```

In `backend/tests/apps/worker/test_dev_run.py`:

```diff
diff --git a/backend/tests/apps/worker/test_dev_run.py b/backend/tests/apps/worker/test_dev_run.py
--- a/backend/tests/apps/worker/test_dev_run.py
+++ b/backend/tests/apps/worker/test_dev_run.py
@@ -3,6 +3,7 @@

 from typing import Any

+import pytest
 from temporalio.testing import WorkflowEnvironment

 from dewpoint.apps.cli.main import dev_run_version
@@ -12,6 +13,8 @@
 from tests.conftest import _url_for
 from tests.support.graphs import G, cel, ref
 from tests.support.registry import sync_test_plugins
+
+pytestmark = pytest.mark.usefixtures("this_build_is_current")  # its run starts on the time-skipping server


 def graph() -> dict[str, Any]:
```

- [ ] **Step 5: The version loader**

In `backend/src/dewpoint/engine/runtime/activities.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/activities.py b/backend/src/dewpoint/engine/runtime/activities.py
--- a/backend/src/dewpoint/engine/runtime/activities.py
+++ b/backend/src/dewpoint/engine/runtime/activities.py
@@ -131,6 +131,7 @@
     manifests: dict[str, dict[str, Any]]  # type@version -> manifest, for every node type in the graph
     subflow_version_ids: dict[str, str] = field(default_factory=dict)  # run_workflow node id -> pinned version id
     failure_handler_version_id: str | None = None
+    engine_abi: int | None = None  # the ABI it was published for; None only in histories recorded before 2a-3c


 @dataclass(frozen=True)
```

In `backend/src/dewpoint/apps/worker/store.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/store.py b/backend/src/dewpoint/apps/worker/store.py
--- a/backend/src/dewpoint/apps/worker/store.py
+++ b/backend/src/dewpoint/apps/worker/store.py
@@ -64,6 +64,7 @@
                 manifests={t.ref: t.manifest for t in types},
                 subflow_version_ids=dict(sorted(v.subflow_version_ids.items())),
                 failure_handler_version_id=str(v.failure_handler_version_id) if v.failure_handler_version_id else None,
+                engine_abi=v.engine_abi,
             )

     async def project(self, data: ProjectInput) -> None:
```

In `backend/src/dewpoint/apps/worker/activities.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/activities.py b/backend/src/dewpoint/apps/worker/activities.py
--- a/backend/src/dewpoint/apps/worker/activities.py
+++ b/backend/src/dewpoint/apps/worker/activities.py
@@ -34,6 +34,7 @@

 from dewpoint.apps.cel_client import EvaluatorUnavailable, evaluate_remote
 from dewpoint.apps.worker.context import context
+from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.cel import ipc
 from dewpoint.engine.runtime.activities import (
     APPLIED,
@@ -53,6 +54,7 @@
     VersionData,
     step_activity,
 )
+from dewpoint.engine.runtime.execution import VERSION_UNUSABLE
 from dewpoint.engine.runtime.projection import location
 from dewpoint.sdk import (
     FatalError,
@@ -201,12 +203,28 @@
     return run_step


-def engine_activities(store: RunStore, plugins: Iterable[Plugin]) -> list[Callable[..., Any]]:
-    """Everything the engine queue serves: the version loader, the projection, and one activity per action node."""
+def engine_activities(store: RunStore, plugins: Iterable[Plugin], *, abi: int = ENGINE_ABI) -> list[Callable[..., Any]]:
+    """Everything the engine queue serves: the version loader, the projection, and one activity per action node.
+    `abi` is the engine ABI this build runs (another build's in the two-build tests): a version runs only on a build
+    of its ABI (spec §7). Admission already compares with the current build's; the loader refuses any other too, for
+    a run that reached this build anyway (a promotion that raced its start), a sub-flow or a failure handler."""

     @activity.defn(name=LOAD_VERSION)
     async def load_version(data: LoadVersionInput) -> VersionData:
-        return await store.version(data.tenant_id, data.version_id)
+        version = await store.version(data.tenant_id, data.version_id)
+        if version.engine_abi != abi:  # the run fails `version_unusable`, with this message
+            remedy = (
+                f"start the run again once a build of ABI {version.engine_abi} is current"
+                if version.engine_abi is not None and version.engine_abi > abi
+                else f"publish the workflow again with a build of ABI {abi}"
+            )
+            raise ApplicationError(
+                f"This version was published for engine ABI {version.engine_abi}, and this build runs ABI {abi}: "
+                f"{remedy}.",
+                type=VERSION_UNUSABLE,
+                non_retryable=True,
+            )
+        return version

     @activity.defn(name=PROJECT)
     async def project(data: ProjectInput) -> None:
```

In `backend/src/dewpoint/apps/worker/main.py`:

```diff
diff --git a/backend/src/dewpoint/apps/worker/main.py b/backend/src/dewpoint/apps/worker/main.py
--- a/backend/src/dewpoint/apps/worker/main.py
+++ b/backend/src/dewpoint/apps/worker/main.py
@@ -19,6 +19,7 @@
 from dewpoint.apps.worker.store import DbRunStore
 from dewpoint.core.config import Settings
 from dewpoint.core.db import make_engine, make_sessionmaker
+from dewpoint.engine import ENGINE_ABI
 from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
 from dewpoint.engine.runtime.workflow import LoopBatch, RunGraph
 from dewpoint.sdk import Plugin
@@ -44,15 +45,17 @@
     *,
     build: str | None = None,
     identity: str | None = None,
+    abi: int = ENGINE_ABI,
 ) -> Worker:
-    """This build's version of the engine deployment (`build`: another's, in the two-build test). A stopping worker
-    lets running attempts finish for `worker_shutdown_grace_s`: one it cancels ends as it would on a lost worker,
-    `outcome_unknown` for an ambiguous node."""
+    """This build's version of the engine deployment, running versions of this build's engine ABI (`build` and `abi`:
+    another build's, in the two-build tests). A stopping worker lets running attempts finish for
+    `worker_shutdown_grace_s`: one it cancels ends as it would on a lost worker, `outcome_unknown` for an ambiguous
+    node."""
     return Worker(
         client,
         task_queue=ENGINE_QUEUE,
         workflows=[RunGraph, LoopBatch],
-        activities=engine_activities(store, plugins),
+        activities=engine_activities(store, plugins, abi=abi),
         graceful_shutdown_timeout=timedelta(seconds=settings.worker_shutdown_grace_s),
         deployment_config=deployment_config(build or this_build()),
         identity=identity,
```

In `backend/src/dewpoint/engine/runtime/execution.py`, the message a run whose version didn't load shows:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -147,6 +147,16 @@
     return isinstance(e, asyncio.CancelledError) or (
         isinstance(e, ActivityError) and isinstance(e.cause, ActivityCancelled)
     )
+
+
+def _unloadable(e: BaseException) -> str:
+    """What a run whose version didn't load says. The loader's own refusal (`version_unusable`: a version of another
+    engine ABI) is written for users; any other error's text may quote the version, so the projection names only its
+    type, and the worker's log has the rest."""
+    refusal = e.cause if isinstance(e, ActivityError) else e  # a local activity's failure comes unwrapped
+    if isinstance(refusal, ApplicationError) and refusal.type == VERSION_UNUSABLE:
+        return refusal.message
+    return f"This build can't run the version ({type(e).__name__}); the worker's log has the details."


 def _backoff(retry: Mapping[str, Any], attempt: int) -> float:
```

In `backend/src/dewpoint/engine/runtime/workflow.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/workflow.py b/backend/src/dewpoint/engine/runtime/workflow.py
--- a/backend/src/dewpoint/engine/runtime/workflow.py
+++ b/backend/src/dewpoint/engine/runtime/workflow.py
@@ -47,6 +47,7 @@
         VERSION_UNUSABLE,
         Execution,
         _cancelled,
+        _unloadable,
         child_options,
     )
     from dewpoint.engine.runtime.program import Program, compile_program
@@ -125,12 +126,11 @@
             )
         except asyncio.CancelledError:
             return await self._cancelled_early()
-        except Exception as e:  # its text may quote the version: the log has it, the projection names the type
+        except Exception as e:
             if _cancelled(e):
                 return await self._cancelled_early()
             workflow.logger.error("run_version_unusable", exc_info=True)
-            message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
-            return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)))
+            return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, _unloadable(e))))
         try:
             program = compile_program(
                 data.graph,
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/test_workflow_ops.py tests/apps/test_runs.py tests/apps/worker/test_worker_db.py tests/apps/worker/test_dev_run.py tests/apps/worker/test_run_graph_abi.py tests/apps/worker/test_two_builds.py tests/apps/worker/test_admission_abi.py`
Expected: 47 passed, in about a minute: the dev-server tests take most of it.

List files from `tests/apps` before those from `tests/apps/worker`, as here. On `main` already, a
`tests/apps/worker` file listed before a `tests/apps` file and another `tests/apps/worker` file loses the worker
directory's fixtures (`fixture 'env' not found`).

- [ ] **Step 7: Document the rule**

In `docs/operations/deployment.md`:

```diff
diff --git a/docs/operations/deployment.md b/docs/operations/deployment.md
--- a/docs/operations/deployment.md
+++ b/docs/operations/deployment.md
@@ -44,6 +44,29 @@
 A node type the new build no longer ships must be retired first ([`plugin-lifecycle.md`](plugin-lifecycle.md)). The
 old build's runs that still use it finish on the old build's workers, which still have it.

+## A build with a new engine ABI
+
+A build ID ends with its engine ABI (`+abi3`), which changes whenever a build could execute a workflow differently. A
+version runs only on a build of the ABI it was published for. So when a new build changes it:
+
+- Runs already started finish on the old build, pinned to it, with their sub-flows and failure handlers.
+- A new run starts on the deployment's current build, so that's the build admission compares versions with,
+  whichever build's process admits the run. While the old build is current, the new build's versions are refused
+  ("make a build of ABI 3 current first"). Once the new build is current, the old build's versions are refused
+  ("publish the workflow again"), and `dewpoint dev run` prints which ones. A sub-flow or failure handler of the other
+  ABI refuses its parent's runs the same way.
+- Publish each workflow again with the new build once it's current. Start with the workflows that others run as
+  sub-flows or failure handlers, then publish those that run them. Publishing refuses a workflow that would run a
+  version of another ABI (`subflow.engine_abi`).
+- A promotion that happens between a run's admission and its start is caught when the run loads its version: it fails
+  with `version_unusable` before any step runs, with the same explanation. Start it again.
+
+Builds from before 2a-3c aren't in the deployment, and their processes don't check the ABI when they admit a run.
+Such a run starts on the current build, whose loader refuses a version of another ABI. Until a 2a-3c build is
+current, 2a-3c's processes admit nothing: no build is current.
+
+Rolling back across an ABI change means publishing again with the old build, too.
+
 ## Docker Compose (evaluation)

 Compose runs Temporal's dev server (the `temporal` service: its state in SQLite on the `temporal-data` volume, its Web
@@ -51,8 +74,9 @@

 Compose runs one build at a time, so its worker makes its own build current as it starts
 (`DEWPOINT_WORKER_SET_CURRENT=true`). Replacing the `worker` container with a new image removes the old build's only
-worker: **let runs end before upgrading**, or their build's worker must come back for them to finish. Leave the setting
-off wherever builds overlap.
+worker: **let runs end before upgrading**, or their build's worker must come back for them to finish. When the new
+image has a new engine ABI, publish every workflow again after upgrading (above). Leave the setting off wherever builds
+overlap.

 The worker and `dewpoint dev run` log in as `dewpoint_worker_login` and `dewpoint_dispatch_login`
 (`DEWPOINT_WORKER_DB_PASSWORD`, `DEWPOINT_DISPATCH_DB_PASSWORD`). A fresh install creates both. An install whose
```

In `docs/operations/runs.md`:

````diff
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -51,7 +51,9 @@
 dewpoint dev run <version-id> --tenant <tenant-id> --input trigger.json
 ```

-- The version must be the **active** version of an **enabled** workflow, and nothing it uses may be retired.
+- The version must be the **active** version of an **enabled** workflow, and nothing it uses may be retired. It,
+  and the sub-flows and failure handler it runs, must have been published for the engine ABI of the deployment's
+  current build, where the run starts ([`deployment.md`](deployment.md)).
 - `--simulate` calls each plugin node's `simulate()` instead of `run()`: nothing is sent anywhere. A node without a
   simulation fails its step with `simulation_unavailable`. Timers still wait, as they would in a live run.
 - By default the command waits and prints the result. `--no-wait` prints the run id and returns.
````

- [ ] **Step 8: Checks, the whole suite, and commit**

The abi2 histories must still replay: their recorded version loads lack `engine_abi`, and a replay never runs the
loader.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src tests ../docs/operations \
  && git commit -m "feat: a version runs only on a build of its engine ABI, the current build's at admission" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,063 passed and 8 skipped.

---

### Task 11: Local CEL, `ENGINE_ABI` 3 and its golden histories

Gates 1–7 pass for `cel-cpp-0.1.3/fn-1/cls-1`, gate 7b on Linux included, so this build evaluates it in-process
(decision 15):
- `LOCAL_CEL_PROFILE` becomes `CURRENT_CEL_PROFILE`.
- `ENGINE_ABI` becomes 3, because a run's commands change when its expressions run in the workflow. The build ID is
  `dewpoint-0.1.0+abi3`, and publishing stamps new versions with 3. The profile tripwire expects `(3, CURRENT)`.
- A filter over more than 1,000 items (`FILTER_INLINE`) goes to `cel.evaluate`, as spec §6's node table says,
  however cheap its predicate: `_cel_task(..., inline=False)` routes it there.

Tests that exercise the evaluator path used expressions that now run locally. They switch to the harness's
`EVALUATOR_ONLY`, which publish always sends to the evaluator (it reads a named time zone). Tests that check where
an expression ran now expect `local`. The yield test that checks binding on the evaluator path turns local CEL off.

The abi3 directory records every scenario again, plus four new ones:
- `local_cel`: heavy local evaluations, three at a time, with yield timers, and a small local filter;
- `evaluator`: a filter over 1,500 items in two chunks, and an expression only the evaluator runs;
- `cancelled`: the recorder cancels the run while its delay runs (`Scenario.cancel`);
- `version_unusable`: the version's manifests are gone when it loads (`Scenario.unusable`).

The recorder's store records the rows it's sent (`RecorderStore`), and `delaying()` waits until a run's delay has
started. `internal_error` gets no scenario: only a bug causes it, and a history recorded through a bug doesn't
replay against the fixed code.

The abi2 histories stay, unchanged, as the replay gate requires. They're no longer replayed: this build's ABI is 3.
Versions published before this task are ABI 2, so after this build is promoted they must be published again (Task
10's rule).

**Prerequisite: gate 7b passes on Linux.** Linux is authoritative for gate 7 (spec §5.9), and planning measured gate
7b on macOS only (0.44 s worst). Local CEL goes on only once the CI job `cel-gates` has passed on this branch with
Task 1's code as execution's checkpoint 2 changed it (`7d6ee2a`), `tests/apps/worker/test_gate_task_cost.py`
included. CI runs on push, and only the owner pushes:
1. Before Step 1, stop and ask the owner for the `cel-gates` result of a push of this branch. Checkpoint 1 is the
   natural time for that push, so the result is usually already in hand.
2. Read the job's `cel-gate-results` artifact, and record in the ledger each load's `worst_cpu_s` from
   `task_cost.json`, and the commit it ran on.
3. Continue only if the job passed, with every load at or under 1 s. If it failed, stop: bringing a load under the
   target means lower yield thresholds, which are spec values (§5.6), so the owner rules on them first. Don't start
   this task.

**Files:**
- Modify: `backend/src/dewpoint/engine/cel/profile.py`, `backend/src/dewpoint/engine/__init__.py`,
  `backend/src/dewpoint/engine/runtime/execution.py`
- Modify: `backend/tests/engine/cel/test_profile.py`, `backend/tests/apps/worker/harness.py`,
  `backend/tests/apps/worker/test_run_graph.py`, `backend/tests/apps/worker/test_run_graph_policies.py`,
  `backend/tests/apps/worker/test_two_builds.py`, `backend/tests/apps/worker/test_run_graph_yield.py`,
  `backend/tests/apps/worker/test_worker_db.py`
- Create: `backend/tests/apps/worker/test_run_graph_local_cel.py`
- Modify: `backend/tests/engine/replay/scenarios.py`, `backend/tests/engine/replay/record.py`
- Create: `backend/tests/engine/replay/dewpoint-0.1.0+abi3/*.json` (recorded, not written by hand)
- Modify: `docs/operations/runs.md`, `docs/operations/cel-evaluator.md`

**Interfaces:**
- Consumes: Task 1's `_cel_task` and yield budget, and gate 7b's Linux result (the prerequisite); Task 7's replay
  of this ABI's directories; Task 9's bounded recorder; Task 10's ABI rule and its harness (`start_version`);
  2a-3b's `record.executions` and `scenarios()`.
- Produces:
  - `dewpoint.engine.ENGINE_ABI = 3`; `profile.LOCAL_CEL_PROFILE = CURRENT_CEL_PROFILE`;
  - `execution.FILTER_INLINE = 1_000`, and `Execution._cel_task(record, views, *, inline: bool = True)`;
  - `harness.EVALUATOR_ONLY = "timestamp('2026-01-01T00:00:00Z').getHours('Europe/Paris')"`;
  - `Scenario.cancel` and `Scenario.unusable`, and the scenarios `local_cel`, `evaluator`, `cancelled` and
    `version_unusable`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/engine/cel/test_profile.py`, the tripwire:

```diff
diff --git a/backend/tests/engine/cel/test_profile.py b/backend/tests/engine/cel/test_profile.py
--- a/backend/tests/engine/cel/test_profile.py
+++ b/backend/tests/engine/cel/test_profile.py
@@ -13,4 +13,4 @@
 def test_local_evaluation_is_a_build_constant_tied_to_the_engine_abi() -> None:
     """Tripwire (spec §5.9 rollout): LOCAL_CEL_PROFILE is part of engine_abi. Changing it without bumping ENGINE_ABI
     would let an open run replay on a build that routes its CEL differently. Update both, then this pair."""
-    assert (ENGINE_ABI, profile.LOCAL_CEL_PROFILE) == (2, None)
+    assert (ENGINE_ABI, profile.LOCAL_CEL_PROFILE) == (3, profile.CURRENT_CEL_PROFILE)
```

Create `backend/tests/apps/worker/test_run_graph_local_cel.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Local CEL (spec §5.6, §5.9 rollout): this build evaluates its profile in-process. An expression runs in the
workflow when publish classified it local and the values it reads are within the caps; everything else, and a filter
over more than 1,000 items, goes to `cel.evaluate` on the profile's queue."""

import asyncio
from typing import Any

from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment

from dewpoint.engine.runtime.activities import CEL_EVALUATE
from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, start, workers
from tests.support.graphs import G, cel, ref

ITEMS = {"type": "object", "properties": {"xs": {"type": "array", "items": {"type": "integer"}}}, "required": ["xs"]}


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": ITEMS, "outputs": outputs}
    return g


async def finished(env: WorkflowEnvironment, g: G, xs: list[int]) -> tuple[MemoryStore, str, Any, WorkflowHistory]:
    store = MemoryStore()
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"xs": xs})
        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
        history = await handle.fetch_history()
    return store, handle.id, result, history


def evaluations(history: WorkflowHistory) -> int:
    """The `cel.evaluate` requests the run sent."""
    return sum(
        e.activity_task_scheduled_event_attributes.activity_type.name == CEL_EVALUATE
        for e in history.events
        if e.HasField("activity_task_scheduled_event_attributes")
    )


async def test_cel_this_build_can_run_runs_in_the_workflow(env: WorkflowEnvironment) -> None:
    g = graph(n=ref("steps.t.output.n")).node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.xs) * 2")}})
    store, run_id, result, history = await finished(env, g, [1, 2, 3])
    assert (result.status, result.outputs) == ("succeeded", {"n": 6})
    assert [r.cel_mode for r in store.steps(run_id)] == ["local"] and evaluations(history) == 0


async def test_a_filter_over_more_than_a_thousand_items_goes_to_the_evaluator_in_chunks(
    env: WorkflowEnvironment,
) -> None:
    """Spec §6: up to 1,000 items a filter's predicate may run inline; larger lists go to `cel.evaluate`, 1,000 binding
    sets at a time, however cheap the predicate."""
    g = graph(kept=ref("steps.f.output.count"))
    g.node("f", "flow.filter@1", {"items": cel("trigger.xs"), "predicate": cel("item % 2 == 0")})
    store, run_id, result, history = await finished(env, g, list(range(1_500)))
    assert (result.status, result.outputs) == ("succeeded", {"kept": 750})
    assert [r.cel_mode for r in store.steps(run_id) if r.node_key == "f"] == ["activity"]
    assert evaluations(history) == 2 + 1  # the filter's two chunks, and `items` itself (a list past the caps)


async def test_values_past_the_caps_go_to_the_evaluator(env: WorkflowEnvironment) -> None:
    """A list of 201 items is past the 200-element cap (spec §5.6): the same expression runs in `cel.evaluate`."""
    g = graph(n=ref("steps.t.output.n")).node("t", "flow.transform@1", {"fields": {"n": cel("size(trigger.xs) * 2")}})
    store, run_id, result, history = await finished(env, g, list(range(201)))
    assert (result.status, result.outputs) == ("succeeded", {"n": 402})
    assert [r.cel_mode for r in store.steps(run_id)] == ["activity"] and evaluations(history) == 1


async def test_an_expression_only_the_evaluator_runs_goes_to_it(env: WorkflowEnvironment) -> None:
    g = graph(n=ref("steps.t.output.n")).node("t", "flow.transform@1", {"fields": {"n": cel(EVALUATOR_ONLY)}})
    store, run_id, result, history = await finished(env, g, [])
    assert (result.status, result.outputs) == ("succeeded", {"n": 1})
    assert [r.cel_mode for r in store.steps(run_id)] == ["activity"] and evaluations(history) == 1
```

In `backend/tests/apps/worker/harness.py`:

```diff
diff --git a/backend/tests/apps/worker/harness.py b/backend/tests/apps/worker/harness.py
--- a/backend/tests/apps/worker/harness.py
+++ b/backend/tests/apps/worker/harness.py
@@ -41,6 +41,9 @@


 RESULT_TIMEOUT_S = 60  # the harness's runs are time-skipped: a minute is far more than any needs
+# CEL only the evaluator runs, whatever the build (a named time zone, spec §5.5): 1, Paris's hour at 00:00 UTC
+# on 1 January. The tests of the `cel.evaluate` path use it now that this build evaluates the rest in-process.
+EVALUATOR_ONLY = "timestamp('2026-01-01T00:00:00Z').getHours('Europe/Paris')"


 @dataclass
```

In `backend/tests/apps/worker/test_run_graph.py`:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph.py b/backend/tests/apps/worker/test_run_graph.py
--- a/backend/tests/apps/worker/test_run_graph.py
+++ b/backend/tests/apps/worker/test_run_graph.py
@@ -10,7 +10,7 @@

 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.workflow import RunGraph
-from tests.apps.worker.harness import RESULT_TIMEOUT_S, MemoryStore, run, start, workers
+from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, MemoryStore, run, start, workers
 from tests.support.graphs import G, cel, ref, template

 ECHO, IF, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.filter@1"
@@ -50,7 +50,7 @@
         result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
     assert (result.status, result.outputs) == ("succeeded", {"side": "yes"})
     rows = {r.node_key: r for r in store.steps(handle.id)}
-    assert rows["c"].status == "succeeded" and rows["c"].cel_mode == "activity"  # LOCAL_CEL_PROFILE is None
+    assert rows["c"].status == "succeeded" and rows["c"].cel_mode == "local"  # this build runs its profile in-process
     assert "no" not in rows and store.runs[handle.id].status == "succeeded"


@@ -164,7 +164,7 @@

 async def test_without_an_evaluator_cel_fails_as_profile_unavailable(env: WorkflowEnvironment) -> None:
     store = MemoryStore()
-    g = graph().node("t", TRANSFORM, {"fields": {"y": cel("trigger.x * 2")}}, on_error="continue")
+    g = graph().node("t", TRANSFORM, {"fields": {"y": cel(f"trigger.x * {EVALUATOR_ONLY}")}}, on_error="continue")
     g.settings["outputs"] = {"error": ref("steps.t.error", default="none")}
     async with workers(env.client, store, evaluate=None):
         # the test server doesn't skip schedule-to-start time: a real 2 s stands in for the 10 minutes
```

In `backend/tests/apps/worker/test_run_graph_policies.py`:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_policies.py b/backend/tests/apps/worker/test_run_graph_policies.py
--- a/backend/tests/apps/worker/test_run_graph_policies.py
+++ b/backend/tests/apps/worker/test_run_graph_policies.py
@@ -25,7 +25,7 @@
     RunInput,
 )
 from dewpoint.engine.runtime.workflow import PROJECT_BYTES, RunGraph
-from tests.apps.worker.harness import RESULT_TIMEOUT_S, TENANT, MemoryStore, run, start, workers
+from tests.apps.worker.harness import EVALUATOR_ONLY, RESULT_TIMEOUT_S, TENANT, MemoryStore, run, start, workers
 from tests.support.graphs import G, cel, ref, template
 from tests.support.plugins.testkit import SlowSend

@@ -551,7 +551,7 @@
     """Checkpoint-2 finding: the outputs were evaluated outside the run's cancellation handler, so a cancel then
     closed the workflow with nothing projected: the run stayed `running`."""
     store = MemoryStore()
-    g = graph(n=cel("trigger.x + 1")).node("a", ECHO)
+    g = graph(n=cel(f"trigger.x + {EVALUATOR_ONLY}")).node("a", ECHO)
     async with workers(env.client, store, evaluate=None):  # no evaluator: the output's CEL waits for one
         handle = await start(env.client, store, g, TRIGGER, cel_schedule_to_start_s=60)
         await asyncio.wait_for(output_evaluation_started(handle), 10)
@@ -564,7 +564,7 @@
 async def test_the_deadline_holds_while_the_outputs_are_evaluated(env: WorkflowEnvironment) -> None:
     """Checkpoint-2 finding: past the deadline, a run waited on its outputs' evaluator and ended as its failure."""
     store = MemoryStore()
-    g = graph(n=cel("trigger.x + 1")).node("a", ECHO)
+    g = graph(n=cel(f"trigger.x + {EVALUATOR_ONLY}")).node("a", ECHO)
     async with workers(env.client, store, evaluate=None):
         handle = await start(env.client, store, g, TRIGGER, max_run_duration_s=1, cel_schedule_to_start_s=5)
         result = await asyncio.wait_for(handle.result(), 10)
```

In `backend/tests/apps/worker/test_two_builds.py`:

```diff
diff --git a/backend/tests/apps/worker/test_two_builds.py b/backend/tests/apps/worker/test_two_builds.py
--- a/backend/tests/apps/worker/test_two_builds.py
+++ b/backend/tests/apps/worker/test_two_builds.py
@@ -23,7 +23,7 @@
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
 from dewpoint.engine.runtime.activities import cel_queue
 from dewpoint.sdk import Plugin
-from tests.apps.worker.harness import MemoryStore, in_process, start, start_version
+from tests.apps.worker.harness import EVALUATOR_ONLY, MemoryStore, in_process, start, start_version
 from tests.apps.worker.test_deployment import build, placement
 from tests.apps.worker.test_main import settings
 from tests.engine.replay.record import executions
@@ -46,13 +46,13 @@
     old.settings = {"input_schema": {"type": "object"}, "outputs": {"double": ref("steps.r.output.double")}}
     old.node("s", "testkit.slow@1", {"seconds": 3})
     old.node("r", "flow.run_workflow@1", {"workflow_id": str(store.publish(sub)), "input": {"n": 21}})
-    old.node("l", "flow.loop@1", {"items": list(range(101)), "collect": cel("item * 2")})
+    old.node("l", "flow.loop@1", {"items": list(range(101)), "collect": cel(f"item + {EVALUATOR_ONLY}")})
     old.node("x", "testkit.echo@1", {"value": ref("item")})
     old.edge("s", "r").edge("r", "l").edge("l", "x", "body")
     new = G()  # N's: nothing retired
     new.settings = {
         "input_schema": {"type": "object"},
-        "outputs": {"n": cel("steps.e.output.value + 1")},
+        "outputs": {"n": cel(f"steps.e.output.value + {EVALUATOR_ONLY}")},
     }
     new.node("e", "testkit.echo@1", {"value": 41})
     return store, old, new
```

In `backend/tests/apps/worker/test_run_graph_yield.py`:

```diff
diff --git a/backend/tests/apps/worker/test_run_graph_yield.py b/backend/tests/apps/worker/test_run_graph_yield.py
--- a/backend/tests/apps/worker/test_run_graph_yield.py
+++ b/backend/tests/apps/worker/test_run_graph_yield.py
@@ -123,10 +123,11 @@


 async def test_binding_is_charged_when_the_evaluator_runs_the_expression(
-    env: WorkflowEnvironment, recorded: dict[int, list[tuple[str, int]]]
+    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch, recorded: dict[int, list[tuple[str, int]]]
 ) -> None:
-    """No local CEL: each of the filter's 20 views still binds `trigger.c1` (16,081 values) in the workflow. A
-    workflow task binds up to the budget, and the next view waits for the next task."""
+    """A build without local CEL: each of the filter's 20 views still binds `trigger.c1` (16,081 values) in the
+    workflow. A workflow task binds up to the budget, and the next view waits for the next task."""
+    monkeypatch.setattr(execution, "LOCAL_CEL_PROFILE", None)
     store = MemoryStore()
     g = graph(kept=cel("steps.f.output.count"))
     g.node("f", "flow.filter@1", {"items": list(range(20)), "predicate": cel("size(trigger.c1) > item")})
```

In `backend/tests/apps/worker/test_worker_db.py`:

```diff
diff --git a/backend/tests/apps/worker/test_worker_db.py b/backend/tests/apps/worker/test_worker_db.py
--- a/backend/tests/apps/worker/test_worker_db.py
+++ b/backend/tests/apps/worker/test_worker_db.py
@@ -66,7 +66,7 @@
     assert [(r["id"], r["status"], r["iterations"]) for r in listed] == [(str(run_id), "succeeded", 2)]
     detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")).json()
     steps = {(s["key"], s["iteration_key"]): s for s in detail["steps"]}
-    assert steps[("a", "")]["output"] == {"value": 2} and steps[("a", "")]["cel_mode"] == "activity"
+    assert steps[("a", "")]["output"] == {"value": 2} and steps[("a", "")]["cel_mode"] == "local"
     assert steps[("a", "")]["outcome"] == "applied"
     assert {k for k in steps if k[0] == "x"} == {("x", "l:0"), ("x", "l:1")}
     assert steps[("l", "")]["output"] == {"items": [10, 20], "failures": [], "count": 2}
```

In `backend/tests/engine/replay/scenarios.py`, the new scenarios:

```diff
diff --git a/backend/tests/engine/replay/scenarios.py b/backend/tests/engine/replay/scenarios.py
--- a/backend/tests/engine/replay/scenarios.py
+++ b/backend/tests/engine/replay/scenarios.py
@@ -3,15 +3,18 @@

 2a-3a records what it can run: branches, joins, dead paths and switch; inline loops, filter and transform; every
 error policy; variables and timers; stop, fail, simulation and the deadline; CEL through `cel.evaluate`. 2a-3b adds
-batched loops, sub-flows, the failure handler, grants, continue-as-new and drain mode; 2a-3c adds local CEL and the
-yield-point timer. A scenario that runs sub-flows builds its graph against the recorder's store, which publishes
-them first."""
+batched loops, sub-flows, the failure handler, grants, continue-as-new and drain mode. 2a-3c turns local CEL on:
+expressions run in the workflow, with the yield-point timer, and the rest go to `cel.evaluate`. It also records a
+cancelled run and a version this build can't compile. A scenario that runs sub-flows builds its graph against the
+recorder's store, which publishes them first."""

 from collections.abc import Callable
 from dataclasses import dataclass, field
 from typing import Any

-from tests.apps.worker.harness import MemoryStore
+from dewpoint.engine.graph.validate import ValidationContext, validate
+from tests.apps.worker.harness import CATALOG, EVALUATOR_ONLY, MemoryStore
+from tests.engine.cel.test_gate_cost import ADVERSARIAL
 from tests.support.graphs import G, cel, ref

 ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"
@@ -28,6 +31,8 @@
     graph: G | Callable[[MemoryStore], G]  # a callable publishes the sub-flows it runs, then builds the graph
     trigger: dict[str, Any] = field(default_factory=lambda: dict(TRIGGER))
     options: dict[str, Any] = field(default_factory=dict)  # RunInput fields
+    cancel: bool = False  # the recorder cancels the run once its delay is running
+    unusable: bool = False  # when a run loads its version, the manifests are gone: this build can't compile it

     def build(self, store: MemoryStore) -> G:
         return self.graph(store) if callable(self.graph) else self.graph
@@ -152,6 +157,54 @@
     g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
     g.node("r", "flow.run_workflow@1", {"workflow_id": _doubler(store), "input": {"n": 21}})
     return g.node("d", "flow.delay@1", {"duration_s": 3_600})
+
+
+TEXT = {
+    "type": "object",
+    "properties": {
+        "s": {"type": "string"},
+        "needle": {"type": "string"},
+        "xs": {"type": "array", "items": {"type": "integer"}},
+    },
+    "required": ["s", "needle", "xs"],
+}
+TEXT_TRIGGER: dict[str, Any] = {"s": "a" * 16_384, "needle": "a" * 8_191 + "b", "xs": list(range(1_500))}
+
+
+def _text(**outputs: Any) -> G:
+    g = G()
+    g.settings = {"input_schema": TEXT, "outputs": outputs}
+    return g
+
+
+def _heaviest_search() -> str:
+    """The heaviest substring search that still publishes local: about half a workflow task's work budget."""
+    best = ""
+    for n in range(1, 60):
+        expr = ADVERSARIAL["search"](n)
+        result = validate(
+            _text().node("x", "flow.transform@1", {"fields": {"r": cel(expr)}}).build(),
+            ValidationContext(catalog=CATALOG, subflows={}),
+        )
+        if any(d.severity == "error" for d in result.diagnostics) or result.expressions[0].mode != "local":
+            break
+        best = expr
+    return best
+
+
+def _local_cel() -> G:
+    """Six heavy local evaluations, three at a time: a workflow task runs two at most, then the yield timer."""
+    g = _text(found=ref("steps.l.output.items"), short=ref("steps.f.output.count"))
+    g.node("l", LOOP, {"items": list(range(6)), "concurrency": 3, "collect": cel("steps.x.output.r")})
+    g.node("x", "flow.transform@1", {"fields": {"r": cel(_heaviest_search())}}).edge("l", "x", "body")
+    g.node("f", "flow.filter@1", {"items": [1, 2, 3, 4], "predicate": cel("item < 3")})
+    return g.edge("l", "f", "done")
+
+
+def _evaluator() -> G:
+    """A filter over 1,500 items goes to `cel.evaluate` in chunks of 1,000; so does what only the evaluator runs."""
+    g = _text(kept=ref("steps.f.output.count"), hour=cel(EVALUATOR_ONLY))
+    return g.node("f", "flow.filter@1", {"items": cel("trigger.xs"), "predicate": cel("item % 2 == 0")})


 def scenarios() -> dict[str, Scenario]:
@@ -174,4 +227,8 @@
         "grants": Scenario(_grants),
         "continue_as_new": Scenario(_continued(), options={"checkpoint_events": 60}),
         "drain": Scenario(_drained, options={"drain_events": 40}),
+        "local_cel": Scenario(_local_cel(), trigger=dict(TEXT_TRIGGER)),
+        "evaluator": Scenario(_evaluator(), trigger=dict(TEXT_TRIGGER)),
+        "cancelled": Scenario(_graph().node("d", "flow.delay@1", {"duration_s": 3_600}), cancel=True),
+        "version_unusable": Scenario(_graph().node("a", ECHO, {"value": 1}), unusable=True),
     }
```

In `backend/tests/engine/replay/record.py`, cancelling and unusable versions:

```diff
diff --git a/backend/tests/engine/replay/record.py b/backend/tests/engine/replay/record.py
--- a/backend/tests/engine/replay/record.py
+++ b/backend/tests/engine/replay/record.py
@@ -8,17 +8,23 @@
 other one, in the order they're found: the runs it continued as, then its children's, and theirs."""

 import asyncio
+import contextlib
+import dataclasses
 import json
 import sys
+import uuid
 from pathlib import Path
 from typing import Any

-from temporalio.client import Client, WorkflowHistory
+from temporalio.api.enums.v1 import EventType
+from temporalio.client import Client, WorkflowFailureError, WorkflowHandle, WorkflowHistory
 from temporalio.testing import WorkflowEnvironment

 import dewpoint
+from dewpoint.engine.runtime.activities import ENGINE_QUEUE, RunInput, VersionData
 from dewpoint.engine.runtime.build import build_id
-from tests.apps.worker.harness import MemoryStore, start, workers
+from dewpoint.engine.runtime.workflow import RunGraph
+from tests.apps.worker.harness import TENANT, MemoryStore, workers
 from tests.engine.replay.scenarios import scenarios

 HERE = Path(__file__).parent
@@ -31,6 +37,27 @@
     if isinstance(value, list):
         return [scrub(v) for v in value]
     return value
+
+
+@dataclasses.dataclass
+class RecorderStore(MemoryStore):
+    """The versions in `unusable` lose their manifests when a run loads them: this build can't compile them."""
+
+    unusable: set[str] = dataclasses.field(default_factory=set)
+
+    async def version(self, tenant_id: str, version_id: str) -> VersionData:
+        data = await super().version(tenant_id, version_id)
+        return dataclasses.replace(data, manifests={}) if version_id in self.unusable else data
+
+
+async def delaying(handle: WorkflowHandle[Any, Any]) -> None:
+    """Until the run's delay is running: its second timer (the deadline's is the first)."""
+    for _ in range(200):
+        history = await handle.fetch_history()
+        if sum(e.event_type == EventType.EVENT_TYPE_TIMER_STARTED for e in history.events) >= 2:
+            return
+        await asyncio.sleep(0.05)
+    raise AssertionError("the run never started its delay")


 def build_dir() -> Path:
@@ -60,11 +87,19 @@
     if not missing:
         return []
     target.mkdir(exist_ok=True)
-    store = MemoryStore()
+    store = RecorderStore()
     async with await WorkflowEnvironment.start_time_skipping() as env, workers(env.client, store):
         for name, scenario in sorted(missing.items()):
-            handle = await start(env.client, store, scenario.build(store), scenario.trigger, **scenario.options)
-            await asyncio.wait_for(handle.result(), 120)
+            version, run_id = store.add(scenario.build(store)), str(uuid.uuid4())
+            if scenario.unusable:
+                store.unusable.add(version)
+            run = RunInput(TENANT, run_id, version, scenario.trigger, **scenario.options)
+            handle = await env.client.start_workflow(RunGraph.run, run, id=run_id, task_queue=ENGINE_QUEUE)
+            if scenario.cancel:
+                await delaying(handle)
+                await handle.cancel()
+            with contextlib.suppress(WorkflowFailureError):  # a cancelled run's result is its cancel
+                await asyncio.wait_for(handle.result(), 120)
             histories = await executions(env.client, handle.id, handle.first_execution_run_id or "")
             for n, history in enumerate(histories):
                 data = scrub(json.loads(history.to_json()))
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/cel/test_profile.py tests/apps/worker/test_run_graph_local_cel.py tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_policies.py tests/apps/worker/test_two_builds.py tests/apps/worker/test_run_graph_yield.py tests/apps/worker/test_worker_db.py tests/engine/replay`
Expected: 5 failed, 103 passed.
- `test_local_evaluation_is_a_build_constant_tied_to_the_engine_abi`: `(2, None) == (3, 'cel-cpp-0.1.3/fn-1/cls-1')`.
- `test_cel_this_build_can_run_runs_in_the_workflow`, `test_a_cel_branch_runs_one_side_and_projects_control_steps`
  and `test_a_run_is_projected_and_readable_through_the_api`: the expression ran in `activity` mode, not `local`.
- `test_every_scenario_is_recorded_for_this_build`: "run `uv run python -m tests.engine.replay.record`".
- The other three `test_run_graph_local_cel.py` tests pass already: they pin the evaluator path, which this task
  must keep.

- [ ] **Step 3: Turn local CEL on, with `ENGINE_ABI` 3**

In `backend/src/dewpoint/engine/cel/profile.py`:

```diff
diff --git a/backend/src/dewpoint/engine/cel/profile.py b/backend/src/dewpoint/engine/cel/profile.py
--- a/backend/src/dewpoint/engine/cel/profile.py
+++ b/backend/src/dewpoint/engine/cel/profile.py
@@ -15,7 +15,7 @@
 # The one profile this worker build evaluates in-process, or None (spec §5.9 rollout). A build constant, never a
 # setting: it is part of engine_abi, so changing it requires bumping ENGINE_ABI (tests/engine/cel/test_profile.py).
 # Stays None until gates 1-7 pass, including the workflow-task gates that 2a-3 adds.
-LOCAL_CEL_PROFILE: str | None = None
+LOCAL_CEL_PROFILE: str | None = CURRENT_CEL_PROFILE


 def profile_of(runtime_version: str) -> str:
```

In `backend/src/dewpoint/engine/__init__.py`:

```diff
diff --git a/backend/src/dewpoint/engine/__init__.py b/backend/src/dewpoint/engine/__init__.py
--- a/backend/src/dewpoint/engine/__init__.py
+++ b/backend/src/dewpoint/engine/__init__.py
@@ -4,4 +4,4 @@
 # The one engine ABI (spec §7): publishing stamps and hashes a version with it, and the build id names it. Bump it on
 # any change that can alter a run's command sequence. 2: 2a-3b's loop batches, sub-flows, the failure handler and
 # continue-as-new.
-ENGINE_ABI = 2
+ENGINE_ABI = 3
```

In `backend/src/dewpoint/engine/runtime/execution.py`:

```diff
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -87,6 +87,7 @@
 IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
 PROJECT_BYTES = 256 * 1024  # a projection's rows at most, as JSON: far below Temporal's 2 MiB payload limit
 CEL_BATCH = 1_000  # binding sets per cel.evaluate request
+FILTER_INLINE = 1_000  # a filter's items the workflow may evaluate itself; a larger list goes to cel.evaluate (spec §6)
 SUBFLOW_GRANT = 1_000  # a sub-flow's initial grant (spec §6)
 MAX_DEPTH = 5  # sub-flows nest at most this deep (spec §6; publish checks it too)
 DEADLINE_EXCEEDED = "deadline_exceeded"
@@ -660,18 +661,20 @@
                 values[pointer] = value.value
         return values, mode

-    async def _cel_task(self, record: ExpressionRecord, views: Sequence[Any]) -> resolve.CelTask:
+    async def _cel_task(
+        self, record: ExpressionRecord, views: Sequence[Any], *, inline: bool = True
+    ) -> resolve.CelTask:
         """Bind each view within the workflow task's budget (spec §5.6). Binding converts every value it binds, so
-        it's charged as they are (`Measure.nodes`), whether the expression then runs here or in `cel.evaluate`."""
+        it's charged as they are (`Measure.nodes`), whether the expression then runs here or in `cel.evaluate`.
+        `inline` False: it goes to `cel.evaluate`, whatever its class."""
         bound: list[resolve.Bound] = []
         for v in views:
             await self._yield_point(None)
             b = resolve.bind_view(record, v)
             self._yield.charge(nodes=b.measured.nodes)
             bound.append(b)
-        return resolve.cel_task(
-            record, bound, local_profile=LOCAL_CEL_PROFILE, version_profile=self.program.cel_profile
-        )
+        local_profile = LOCAL_CEL_PROFILE if inline else None
+        return resolve.cel_task(record, bound, local_profile=local_profile, version_profile=self.program.cel_profile)

     async def _evaluate(self, task: resolve.CelTask) -> list[cel.Outcome]:
         if task.local:
@@ -771,7 +774,7 @@
         record = self.program.record(step.id, "/predicate")
         views = [self._view(inst.scope, item=(item, i)) for i, item in enumerate(items)]
         try:
-            task = await self._cel_task(record, views)
+            task = await self._cel_task(record, views, inline=len(items) <= FILTER_INLINE)
         except resolve.ValueFailure as e:
             return _Effect(failure=e.failure)
         kept: list[Any] = []
```

- [ ] **Step 4: Record the abi3 histories**

Run: `cd backend && uv run python -m tests.engine.replay.record`
Expected: `dewpoint-0.1.0+abi3: recorded batches, branches, cancelled, continue_as_new, deadline, drain, errors, evaluator, failed, failure_handler, grants, local_cel, loops, simulate, stop, subflows, variables_and_timers, version_unusable` on stderr. Planning recorded 40 or 41 files, about 2.0 MB:
a scenario that runs children or continues as new records each execution, and `continue_as_new` continued 6 or 7
times across planning's recordings, depending on how the test server delivered its activities' completions.

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest -q tests/engine/cel/test_profile.py tests/apps/worker/test_run_graph_local_cel.py tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_policies.py tests/apps/worker/test_two_builds.py tests/apps/worker/test_run_graph_yield.py tests/apps/worker/test_worker_db.py tests/engine/replay`
Expected: 111 passed, with planning's 40 history files: one test per file, so 112 with 41.

Then check that the histories bite. Temporarily set `FILTER_INLINE = 2_000` and run
`cd backend && uv run pytest -q tests/engine/replay -k evaluator`. The `evaluator` history fails to replay, with
`[TMPRL1100] Nondeterminism error: Timer machine does not handle this event`: its filter now runs in the workflow
and yields, where the history has its `cel.evaluate` chunks. Undo the change.

- [ ] **Step 6: Document local CEL**

In `docs/operations/runs.md`:

```diff
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -38,8 +38,7 @@
 timer, so no task runs long enough to time out.

 Without an evaluator, CEL expressions that can't run inline wait `DEWPOINT_CEL_SCHEDULE_TO_START_S` (default 600
-seconds) and then fail the step with `cel_profile_unavailable`. In 2a every CEL expression runs through the evaluator:
-inline evaluation is switched on by plan 2a-3c, together with the build's `ENGINE_ABI`.
+seconds) and then fail the step with `cel_profile_unavailable`.

 The engine worker is its build's version of the `dewpoint-engine` Worker Deployment, and a run finishes on the build it
 started on. Rolling out a build, and what Docker Compose runs (Temporal's dev server and one worker):
```

In `docs/operations/cel-evaluator.md`:

```diff
diff --git a/docs/operations/cel-evaluator.md b/docs/operations/cel-evaluator.md
--- a/docs/operations/cel-evaluator.md
+++ b/docs/operations/cel-evaluator.md
@@ -7,8 +7,8 @@
 volume that only the two of them mount.

 Publish sends it the expressions too costly to run inline. At run time, any expression whose inputs exceed the inline
-caps comes here too: a list or map over 200 entries, a string over 16 KiB, or more than 64 KiB of JSON. The list and
-map caps are low because the CEL runtime's memory for `map` and `filter` grows with the square of the list's length
+caps comes here too: a list or map over 200 entries, a string over 16 KiB, or more than 64 KiB of JSON. So does a
+`filter` over more than 1,000 items, 1,000 at a time. The list and map caps are low because the CEL runtime's memory for `map` and `filter` grows with the square of the list's length
 (spec §5.5). Workflows over large lists therefore depend on the evaluator: size its slots for them.

 **Docker Compose only, for now.** That socket only works between containers on one host. In Kubernetes the evaluator
```

- [ ] **Step 7: Checks, the whole suite, and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src tests ../docs/operations \
  && git commit -m "feat(engine): local CEL on, ENGINE_ABI 3, and its golden histories" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: the suite gives 1,070 passed and 8 skipped. `git add tests` adds the `dewpoint-0.1.0+abi3` directory.

Then run the replay gate on the committed branch: `cd backend && uv run python -m tests.engine.replay.gate main; echo "exit $?"`.
Expected: `exit 0`, with nothing printed: every new history is in `dewpoint-0.1.0+abi3`, and none was changed.

**Checkpoint 3:** the minors, the ABI rule and local CEL. Stop for the owner's review, then the whole-branch review.

---

## Handoff to 2b

- **Production Temporal.** Compose's `temporal` is the dev server, for evaluation. Production runs a Temporal
  cluster whose server supports Worker Deployments (the tests run server 1.32.0). The rollout guide's steps are the
  same there: start the new build's workers, `dewpoint deployment set-current`, and stop the old build's workers once
  it reports `drained`.
- **Terminated runs.** A terminated sub-run's row now records its end, written by its parent. A terminated root run
  has no parent, so its row stays `running`. Retention or a reconciler should close it.
- **A failure handler cancelled as it starts** is debited its whole grant, although it never ran, so the run's
  recorded iterations count 1,000 it didn't use. It happens only when the cancel arrives in the same activation
  that starts the handler, and no test server can reach that window on purpose.
- **Unchanged from 2a-3b's handoff:** the claim check (a batch's input, a sub-flow's input, a continue-as-new
  snapshot, each a Temporal payload limited to 2 MiB until then) and payload validation of a sub-flow's input.
- **Local CEL.** The yield budget belongs to the workflow task and isn't in the snapshot: keep it that way. A new
  CEL profile a build can run locally needs gates 1–7 for that profile, gate 7b on Linux included, and a new
  `ENGINE_ABI`.
- **An ABI change means publishing every active workflow again**, children first (decision 16). A command that
  publishes each active workflow again in that order would make an ABI change one step; until then it's done
  workflow by workflow.
- **2b's dispatcher** reuses `admit`, whose `abi` is required: it passes the current build's (`current_abi`), read
  when it freezes a request. At dispatch it reads it again, since a promotion may come between, and cancels a request
  whose frozen version the current build can't run: `engine_abi_changed`, audited (spec §4.5).
- **A test-order quirk on `main`:** listing a `tests/apps/worker` file, then a `tests/apps` file, then another
  `tests/apps/worker` file loses the worker directory's fixtures (`fixture 'env' not found`). The plan's commands
  list `tests/apps` first. It's outside this plan.

## Self-review: spec coverage

| Spec | Requirement | Where |
|---|---|---|
| §5.6 | a workflow task's budget: stored bounds of local evaluations, binding charged by the values it converts; a 1 ms timer when it's spent; 200 evaluations | Task 1 (decisions 1, 2) |
| §5.6 | thresholds: 20,000 iterations, 8 MiB, 4,000,000 work units, 100,000 bound values | Task 1 |
| §5.9 | gate 4: the corpus in a sandboxed workflow, replayed in 5 fresh processes | Task 2 (decision 4) |
| §5.9 | gate 7: the workflow-task test inside `RunGraph`, with a binding load; Linux authoritative | Task 1 (decision 3), CI's `cel-gates` job |
| §5.9 | the rollout: `LOCAL_CEL_PROFILE` set once gates 1–7 pass, gate 7b on Linux included, with `engine_abi` | Task 11 (decision 15; the Linux result is its prerequisite) |
| §6 | a filter over more than 1,000 items goes to `cel.evaluate` in chunks of 1,000 | Task 11 |
| §6 | a terminated child: its whole grant, its end written by its parent | Task 5 (decision 9) |
| §6 | drain when Temporal suggests continue-as-new | Task 5 (decision 10) |
| §6 | a refused child asks again for a later need; the run's end drops what its loops wait for; iterations outside the snapshot; a cancel while settling for continue-as-new | Task 8 (decision 13) |
| §7 | one Worker Deployment, `dewpoint-engine`; build ID `dewpoint-<version>+abi<engine_abi>`; `RunGraph` and `LoopBatch` pinned; children and continued runs on the same version | Task 3 (decision 5) |
| §7 | promoting a build, and the old one draining | Tasks 3, 6 (decisions 6, 11), `docs/operations/deployment.md` |
| §7 | the two-build test: N-1's runs with children, batches, activities and continue-as-new finish on N-1; a node type N lacks; CEL on the version's profile | Task 4 (decision 8) |
| §7 | Compose adds `temporal` and `worker` | Task 6 (decision 11) |
| §7 | a version runs only on a build of its engine ABI: admission compares with the deployment's current build, publishing refuses to pin another ABI, the loader refuses one that raced a promotion, and runs already pinned to an older build finish there | Task 10 (decision 16) |
| §7 | golden histories, `engine_abi` 3 with local CEL | Task 11 (decision 15) |
| §7 | the replay gate | Task 7 (decision 12) |
| §8 | run error codes: `terminated` | Task 5 |
| §8 | a sub-run's refused row is logged and skipped; a cancelled ambiguous attempt is `outcome_unknown`; `GET /runs` pages by the pair (start time, id), and refuses half of it | Tasks 8, 9 (decisions 13, 14) |
| §10 | settlement of terminated children, on the dev server | Task 5 |
| 2a-3b handoff | Worker Versioning, the two-build test, the replay gate, what only a real server can test, and the yield budget outside the snapshot | Tasks 1, 3, 4, 5, 7 |
| 2a-3a and 2a-3b final reviews | the deferred minors | Tasks 5, 8, 9 |

Placeholder scan: every code step shows its code, and every command its expected output. Type consistency: the
names in each Interfaces block match the code shown. The plan's code is the prototype's code, stage by stage, and
replaying the plan onto `main` reproduces the prototype exactly.
