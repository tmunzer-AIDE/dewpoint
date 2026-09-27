# Engine 2a-3a: Interpreter and Runs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run published workflow versions on Temporal: the `RunGraph` interpreter with every node kind inline, the
plugin, CEL, version-loading and projection activities, the `runs` and `run_steps` tables, `start_run`,
`dewpoint worker`, `dewpoint dev run`, the read-only runs API, and the first golden histories.

**Architecture:** `dewpoint.engine.runtime` holds the deterministic core: a compiled `Program`, the `Scheduler`
(scopes, edge states, dead-path elimination, loop iterations), value resolution with 2a-2's CEL routing, and the
control-node decisions. It may not touch a clock, randomness, I/O or threads (a new import contract).
`engine/runtime/workflow.py` is the Temporal workflow that drives them, and `engine/runtime/activities.py` only
*names* the activities. The workflow schedules every attempt of a plugin step itself, and it alone decides retries
and writes rows, through one DB-only projection activity. `dewpoint.apps.worker` implements the activities over a
`RunStore` (the database in production, a dict in tests) and runs the worker. A plugin step's activity runs one
attempt and writes nothing. `dewpoint.core.runs` stores the projection under row-level security, and
`dewpoint.apps.runs` admits and starts runs.

**Tech Stack:** Python 3.12, `temporalio==1.33.0` (new; it brings `nexus-rpc==1.4.0` and accepts the locked
`protobuf` 7.36.2), Temporal's time-skipping test server (downloaded by the SDK on first use), SQLAlchemy 2 async and
Alembic on PostgreSQL 16, FastAPI, Typer, pytest with Hypothesis.

**Spec:** `docs/superpowers/specs/2026-09-25-engine-core-design.md`, revision 5.4: §6 (interpreter), §7 (golden
histories), §8 (projection), §9 (starting runs), §10 (tests). Revision 5.4 records the decisions below. It lands in
the same docs-only PR as this plan, so the spec and the plan agree before implementation starts.

**Previous plan:** `docs/superpowers/plans/2026-09-26-engine-2a2-cel.md` (merged, PR #7). Its handoff section lists
what 2a-3 consumes. The owner split 2a-3 into three plans on 2026-09-27:

- **2a-3a (this plan):** the interpreter and runs.
- **2a-3b:** loop-batch children, sub-flows and the failure handler; on-demand iteration grants; continue-as-new
  with drain mode and the snapshot; the headroom tests.
- **2a-3c:** Worker Versioning; the Compose `temporal` and `worker` services; the two-build test and the CI replay
  gate; CEL gates 4 and 7b, then `LOCAL_CEL_PROFILE` together with an `ENGINE_ABI` bump.

## How this plan was made

1. **Go/no-go experiments ran first** (next section), on temporalio 1.33.0 from the CEL spike's environment. The
   owner approved the SDK's download of its time-skipping test server for planning, the suite and CI.
2. **Every module was prototyped** in a scratch copy of `backend/` until it passed its tests, `ruff`, `ruff format`,
   `mypy --strict` (132 source files) and `lint-imports` (10 contracts). The prototype's full suite gives 875 passed
   and 8 skipped (the Linux-only evaluator tests), against `main`'s 726 collected.
3. **The code blocks below are those files, verbatim.** Diffs to existing files were generated from the prototype.
4. **Each task was staged and checked on its own.** Stage *N* is `main` plus tasks 1..*N*. Every stage passed the
   static checks and its task's tests, and stages 1–3 did so without temporalio installed. Each task's first run was
   checked too: every task's tests fail as its "watch them fail" step says. Stage 8 is identical to the prototype;
   it recorded its golden histories from scratch, and they replay.
5. **Migration 0008 round-tripped** (upgrade, downgrade to 0007, upgrade) on a scratch `postgres:16-alpine`.
6. **Planning found and fixed eight defects in its own prototype,** each test-first:
   - an exception in workflow code left the run hanging (decision 11);
   - a failed row write after a step's effect caused a retry that repeated the effect (decision 12);
   - an unmapped `NotImplementedError` left a `running` row, and a malformed CEL request was retried (decision 7);
   - a zone-less or malformed `wait_until` crashed the workflow task (decision 14);
   - `on_error: continue` set a null output, which broke `has()` guards (decision 1);
   - projections were unbounded in flight (decision 13);
   - 200-character keys could fail a projection write (decision 17);
   - a node type no worker serves failed with the SDK's raw `NotFoundError` (decision 7).

7. **The owner's review of the first draft found four Important gaps**, all fixed test-first and re-staged:
   - an ambiguous send could be repeated after a timeout;
   - an uncertain start was recorded as failed;
   - previews missed `$ref`'d and copied sensitive values, and messages quoted input;
   - a failed final row write left an attempt `running` for good.

   The fixes rewrote decisions 7 and 12 and added 21 and 22. Fixing them found one more defect: the SDK reports a
   cancelled activity as an `ActivityError`, which the new retry loop first took for a failure (go/no-go 11).
8. **The second review found two more paths for secrets**, both fixed test-first and re-staged:
   - validator prose that quotes the value;
   - sensitive config values the run never learned.

   Checking for others found a third, CEL messages that quote data (masked, and pinned by a test), and a plugin step
   that failed before its first attempt got no row at all (decision 12).
9. **The third and fourth reviews found map keys in validation locations**: a location part can come from the data,
   even a numeric one (`dict[int, …]`) or one named like a field declared elsewhere. A location is now rendered by
   walking the schema along it, and shows anything the schema doesn't declare at that place as `*`. Checking the
   rest of the message found that a custom validation error's type can carry the value too; only pydantic's own
   codes show now (decision 21).
10. **Execution's checkpoint 1 found two more gaps**, fixed test-first on `feat/engine-2a3a` and carried into this
    plan:
    - redaction ignored `patternProperties`, and then, for a declared key a pattern also covers. Probing pydantic's
      schemas found the same gap for tuple positions (`prefixItems`) and sensitive keys (`propertyNames`)
      (decision 21);
    - the iteration cap left a loop's opened iterations running (decision 3).
11. **Checkpoint 2 found three more**, fixed test-first on the branch and carried here:
    - the workflow's outputs were evaluated outside the run's cancellation handler and deadline;
    - a malformed output envelope compiled and failed later outside any handler;
    - an instance of a node's `Output` was returned without validation. The re-review found that the first fix
      broke typed field serializers, so an instance is now checked as it's emitted, against the declared output
      schema, and the one after that added a fixed list of formats to the check.

    See decisions 7, 11 and 15.

Not run during planning: the new dependency install (Task 4 downloads it, with the owner's confirmation), and CI.

## Go/no-go: Temporal in this codebase (run 2026-09-27)

| # | Question | Result |
|---|---|---|
| 1 | Does the SDK's time-skipping test server run here? | **Yes.** It downloads once and starts in about 0.8 s. A one-day durable timer completes in milliseconds. |
| 2 | Can workflow code evaluate CEL inside the sandbox? | **Yes, through passthrough.** `cel_expr_python` is a C extension, which the sandbox can't re-import per run, so the workflow imports every `dewpoint.engine` module under `workflow.unsafe.imports_passed_through()`. They are deterministic and hold no mutable state. |
| 3 | Does a recorded history replay in a fresh process? | **Yes**, with `Replayer`, which needs no server. Planting a reordered start makes the replay fail (`TMPRL1100 Nondeterminism error`), so the replay test is a real gate. |
| 4 | Is `asyncio.wait` safe in workflow code? | **No.** The sandbox warns that it's non-deterministic. `workflow.wait` is the SDK's deterministic equivalent. |
| 5 | Does the test server skip schedule-to-start time? | **No.** A 5 s schedule-to-start took 5 real seconds, and `env.sleep` timed out. So the CEL schedule-to-start timeout is a run input (`cel_schedule_to_start_s`, from settings), and the test for a missing evaluator uses 2 s. |
| 6 | Does the test server's clock follow the host's? | **No.** Time skipping moves it ahead (to 2036 within one session). A test that builds a date from the host clock must use `env.get_current_time()` instead. |
| 7 | Does monkeypatching an engine module reach sandboxed workflow code? | **No.** The sandbox runs its own copy. The one test that injects a fault runs the workflow with `UnsandboxedWorkflowRunner`. |
| 8 | What do recorded histories contain? | The worker's identity (`pid@hostname`) and the activity failures' stack traces (local paths). The recorder replaces both before a history is committed. |
| 9 | What happens to an activity still running when its run ends (the deadline, `stop`)? | The run ends at once (the SDK's default `TRY_CANCEL`), but that activity never completes against the closed run, and the time-skipping server stops skipping time while any activity is outstanding. Every later timer on a shared test server would wait in real time. The one test that ends a run mid-activity gets a server of its own (`own_env`). |
| 10 | Does temporalio 1.33.0 fit the lock? | **Yes.** It accepts `protobuf>=3.20,<8` (locked: 7.36.2) and `types-protobuf` (already a dev dependency). It adds `nexus-rpc==1.4.0` (MIT); temporalio itself is MIT. |
| 11 | How does workflow code see its own cancellation of an activity? | **As `ActivityError` with a Temporal `CancelledError` cause, not `asyncio.CancelledError`.** A retry loop that catches `ActivityError` would take the cancel for a failure and start another attempt after the run ended: planning's deadline test caught exactly that (30 s past the deadline). The loop, and `cel.evaluate`'s caller, re-raise it as cancellation. |

**Verdict: go.**

## Decisions (recorded in spec revision 5.4)

Each decision goes beyond revision 5.3 or settles something it left open. Each is the smallest choice that satisfies
the spec, and the prototype implements it. The owner rules on each in the docs PR. **Decision 2 answers the question
the owner left to this plan: what `collect` gives for a failed iteration.**

The owner's review of the first draft (2026-09-27) accepted decisions 1, 2, 4 and 8 and found four Important gaps.
Their fixes are decisions 7 and 12 (rewritten), 21 and 22 (new), and the messages in 6 and 11. The second review
accepted 7, 12 and 22, and found two more paths for secrets, both closed in decision 21: validator prose, and
sensitive config values. The third found a map key in a validation location, and the fourth a numeric map key and a key named like a
field declared elsewhere: both closed in decision 21 by walking the schema along the location. During execution,
checkpoint 3 found a workflow change committing during admission, closed by decision 23.

1. **A handled failure leaves an error and no output.** With `on_error: continue` or `port`, `steps.<key>` becomes
   `{"error": {code, message, attempt}}`, with no `output` key. That is 2a-2's presence contract (§5.3, decision 3
   there): `has(steps.x.output)` is false, so the guard the validator demands actually guards, and a reference's
   default applies. §6's "`continue`: the output is `null`" said otherwise. Revision 5.4 aligns §6 with §5.3.
   (Tasks 1, 5)
2. **A failed iteration collects `null`, and is listed.** With `on_item_error: continue`, a failed iteration leaves
   `items[i] = null`, so positions still match the input list, and adds `{index, code, message}` to `failures`.
   `count` stays the number of items. A `collect` value that can't be computed fails its iteration the same way. With
   `stop` (the default), the first failure cancels the other open iterations and fails the loop step with that
   failure; the loop's own `on_error` then applies. Compacting the list would lose which item failed. (Tasks 1, 5)
3. **An unhandled failure ends its scope, and only its scope.** With `on_error: fail`:
   - in a loop body, the step fails its iteration: running steps there are cancelled, waiting ones die, and
     `on_item_error` decides;
   - in the root, it fails the run with the step's error.

   `stop`, `fail` and the deadline cancel every running step. A result that arrives from cancelled work is ignored.
   Policies compose across nested loops: an inner loop that stops fails its outer iteration only. A loop that ends
   early, when an iteration fails under `stop` or the run reaches its iteration cap, ends its open iterations
   first: running steps are cancelled and queued ones dropped. Only then does its own `on_error` apply, so nothing
   it opened runs beside the steps after it (checkpoint 1). (Task 1)
4. **Until 2a-3b, some graphs fail at run time with `not_supported`:** loops over more than 100 items (batches of
   child workflows) and `run_workflow` (sub-flows). The step fails and its error policy applies. Publish is
   unchanged, so versions published now run fully once 2a-3b ships. The workflow failure handler doesn't run until
   then either. (Task 2)
5. **A value that can't be computed fails its step:**
   - a reference with nothing there and no default: `evaluation_error`. Publish demands a default wherever a value
     may be missing, so only data that breaks its schema gets here;
   - a template part the same way. A `null` without a default adds nothing, and an object or list is
     `type_mismatch`;
   - a CEL outcome keeps its own code;
   - a value that fails a typed list path's binding check is `type_mismatch`.

   (Task 2)
6. **All CEL runs through `cel.evaluate` in this plan.** `LOCAL_CEL_PROFILE` stays `None`, so every expression goes
   to the `cel.evaluate` activity on `dewpoint-cel.<profile>`, one request per value. A filter's items go in chunks of
   1,000 binding sets.
   - Each request gets 3 attempts, and its schedule-to-start timeout is `DEWPOINT_CEL_SCHEDULE_TO_START_S` (default
     600: the spec's 10 minutes).
   - Any failure gives every binding set `cel_profile_unavailable`, and the step fails. The message names the
     profile and the error's type, never the transport's own text (decision 21).
   - `run_steps.cel_mode` records `activity`.
   - The inline path, the yield timer and gates 4 and 7b come with 2a-3c.

   (Task 5)
7. **The workflow schedules every attempt, and decides every retry** (parent §6.6; rewritten after review).
   - Each attempt of a plugin step is one activity execution, with `maximum_attempts=1`, and `StepInput.attempt` says
     which it is.
   - `RunGraph` applies the manifest's policy itself: `max_attempts` and `timeout_s`, both overridable per node, and
     the backoff, as a durable timer.
   - Temporal's own retries would repeat an attempt that timed out or lost its worker. That failure never passes
     through the node's error mapping, so it would resend an ambiguous request.

   How an attempt ends:

   | The node | The attempt | Retried |
   |---|---|---|
   | raises `RetryableError` | fails with its code | yes, unless the code is in the manifest's `non_retryable` |
   | raises `FatalError` | fails with its code | no |
   | raises `OutcomeUnknownError` | fails with its code, outcome `outcome_unknown` | never |
   | raises anything else | `unexpected_error` | yes; for an `ambiguous` node, `outcome_unknown` and never |
   | times out, or its worker is lost | `timeout` (or `error`) | yes; for an `ambiguous` node, `outcome_unknown` and never |
   | config doesn't validate | `config_invalid` | no |
   | output doesn't validate | `output_schema_violation` | no |
   | is `reconcilable`, on attempt 2 or later | calls `reconcile()` first and keeps what it finds | |
   | isn't served by any worker of the build | `node_type_unavailable` (the SDK's `NotFoundError`) | yes |

   A plain result is validated into the node's `Output` model. An `Output` instance can't be trusted as it stands:
   pydantic doesn't check instances built with `model_construct` or changed by assignment. So it is checked as it's
   emitted, dumped with its serializers, against the declared output schema. That schema is generated in
   serialization mode and is closed, so a typed field serializer that changes a type is honoured (checkpoint 2).
   Its formats are checked too, from a fixed list whose checks agree with what pydantic emits: `date`, `time`,
   `uuid`, `email`, `ipv4`, `ipv6` and `regex` (`CHECKED_FORMATS`). `date-time` isn't on it, because RFC 3339 wants
   an offset and pydantic emits naive datetimes without one. The list is fixed so that installing an optional
   library can't turn it on.

   The cost is history: each retry adds its activity's events and a timer, where Temporal's own retries add none. So
   2a-3b's headroom arithmetic counts `max_attempts`. (Tasks 4, 5)
8. **A simulated run** (`mode = simulate`) calls each plugin node's `simulate()` and records the outcome
   `simulated`. A node without one fails with `simulation_unavailable`. Control nodes and timers run as they would
   live, so a simulated `delay` waits. Skipping waits would make a simulation diverge from the run it previews. The
   owner agreed, noting that an editor preview may need a separate, bounded mode: that belongs to sub-project 4.
   (Tasks 4, 5)
9. **Identifiers.**
   - `run_steps.step_id` is the graph node's id.
   - `iteration_key` is `<loop key>:<index>`, joined by `/` from the outermost loop (`outer:1/inner:4`); it is empty
     in the root. Spec §6 already writes it so.
   - `attempt` is the workflow's attempt number (decision 7), and 1 for control nodes.
   - A step's idempotency key is `sha256(run_id ␟ step_id ␟ iteration_key)`, the same for every attempt.

   (Tasks 1, 4)
10. **Roles.**
    - `dewpoint_dispatch` admits and inserts runs, and records a refused start (decision 22).
    - `dewpoint_worker` loads versions and writes the projection, always inside the run's tenant.
    - `dewpoint_api` reads both tables.
    - `dewpoint_admin` reads `runs` across tenants, which §4.5's evaluator shutdown check needs.

    (Tasks 3, 6, 7)
11. **Every run's end is projected; none hangs.** Temporal retries a failed workflow task forever, so an exception
    in workflow code would leave the run open, shown as `running`. Instead:
    - A version this build can't load or compile fails the run with `version_unusable` before any step runs. Compile
      also checks that every CEL value has its expression record. The message names only the error's type, and the
      worker's log has the rest (decision 21).
    - Any other exception fails it with `internal_error`. The message names only the exception's type, because its
      text may quote run data; the worker's log has the rest (decision 21).
    - Cancellation projects `cancelled`.
    - The workflow's outputs are evaluated inside the same handlers and deadline as its steps (checkpoint 2), and so
      is the setup before the first step. A cancel or the deadline while they're computed ends the run as anywhere
      else. A malformed output envelope is refused at compile, as `version_unusable`.
    - A cancel that arrives while the run's end is being written comes too late to unmake that end. The write is
      repeated and the run returns its result, so the projection and Temporal agree.

    (Tasks 1, 5)
12. **Only the projection writes rows** (rewritten after review). A plugin step's activity runs its attempt and
    writes nothing.
    - The workflow queues each attempt's `running` row when it schedules the attempt, and the final row once the
      result is recorded in history: `succeeded`, `failed` or `cancelled`.
    - Rows are projected, with the run's summary, by the DB-only `project` activity, which retries without limit.
    - So a failed write can't repeat an effect, and no row stays `running` once the database answers again. A
      database outage delays the end of a run rather than losing it.
    - A later row of the same attempt replaces a queued one, and the upsert never lets `running` overwrite a final
      state.
    - A plugin step that fails before its first attempt, because its values can't be computed, still gets its one
      row: attempt 1, `failed`, with the value's code.

    (Tasks 4, 5)
13. **One projection in flight.** At most 100 steps (and loop `collect`s) are in flight per execution. Each has at
    most one activity outstanding: its CEL values, then its plugin activity. There is also at most one projection,
    and rows that settle meanwhile go in the next one. Unbounded projections would break §6's drain-headroom
    arithmetic in 2a-3b. (Task 5)
14. **`wait_until` needs a time zone.** It takes RFC 3339 with an offset. A time without a zone (whose 9 o'clock?)
    or anything unparseable fails the step with `type_mismatch`. A past instant doesn't wait. (Task 2)
15. **How a run ends:**
    - a `fail` node: `failed`, with code `workflow_failed` and the node's message;
    - `stop`: `succeeded`, with the workflow outputs evaluated;
    - an output that can't be computed fails the run with that value's code;
    - the deadline: `deadline_exceeded`, without outputs, including while the outputs are being computed.

    (Tasks 2, 5)
16. **A filter fails on its first bad item.** An item whose predicate errors fails the whole filter step with that
    item's error; a result that isn't a boolean is `type_mismatch`. All the items are debited from the run's 100,000
    iterations when the filter starts. (Task 5)
17. **Storage takes any length.** `run_steps.iteration_key` and both tables' `error_code` are `text`: three nested
    loops with 63-character keys already exceed 200 characters, and nothing bounds a plugin's codes. Codes are
    sanitized like messages: no control characters, at most 500 characters. (Task 3)
18. **New settings:** `DEWPOINT_TEMPORAL_ADDRESS` (default `localhost:7233`), `DEWPOINT_TEMPORAL_NAMESPACE`
    (`default`), `DEWPOINT_CEL_SOCKET` (none), `DEWPOINT_CEL_MAX_CONCURRENT` (2), and
    `DEWPOINT_CEL_SCHEDULE_TO_START_S` (600). (Tasks 6, 7)
19. **Golden histories start here, with `ENGINE_ABI = 1`.** The build id is `dewpoint-<version>+abi<ENGINE_ABI>`
    (spec §7), today `dewpoint-0.1.0+abi1`.
    - Eight scenarios cover what 2a-3a runs. 2a-3b and 2a-3c add theirs.
    - The recorder records only the scenarios a build's directory lacks, and never rewrites one. It replaces the
      worker identity and the stack traces.
    - The suite replays the current build's directory.
    - 2a-3c turns this into the CI gate across builds and bumps the ABI with `LOCAL_CEL_PROFILE`.

    (Task 8)
20. **Trigger payloads aren't validated in 2a.** `dewpoint dev run` takes test data. 2b's triggers validate payloads.
    Until then the engine treats a payload that breaks its schema like any other bad value: the reading step fails
    (decision 5). (Tasks 5, 7)
21. **What the projection may show** (new after review). The projection is tenant-readable, so:
    - **Redaction follows the schema everywhere.** A field marked `x-sensitive` is redacted behind local `$ref`s and in
      every branch of `anyOf`, `oneOf` and `allOf`: sensitive in one branch means redacted in all. Pydantic writes
      every nested or optional model that way.
      - Every `patternProperties` schema applies to every key of its object, matched or not and declared keys
        included (JSON Schema applies a declared property and a matching pattern together). No regex runs on data in
        the workflow; a sensitive pattern over-redacts rather than leaks.
      - A tuple's position is redacted by its `prefixItems` schema.
      - A map whose keys are sensitive (`propertyNames`) is redacted whole, and its keys are learned (checkpoint 1).
    - **Learned values are masked.** The workflow remembers the strings found at sensitive positions of:
      - each plugin output, once its result is recorded;
      - each plugin config: a literal when the run starts, so even a copy projected earlier is masked, and a resolved
        value before the step's first attempt (second review);
      - the trigger, by the workflow's input schema.

      It masks them in every preview, error message and run summary it projects: control outputs, templates, other
      steps' inputs, `fail` messages, CEL errors (which quote data, such as a missing key), and a plugin echoing a
      secret.
      - They are kept sorted, longest first, so every replay masks the same way.
      - Values under 4 characters aren't masked, since they would blank ordinary text.
      - A secret CEL transforms (encodes, slices) is no longer the same text, and isn't recognized.
    - **Messages never quote input.**
      - `config_invalid` and `output_schema_violation` name each field and its rule's stable code
        (`token (value_error)`). Pydantic's messages quote the value, and a validator's own prose can too, whatever
        `include_input` says (second review). An output that fails validation was never learned, so only this keeps
        it out.
      - A location shows only what the schema declares at each place (`projection.location`, walking the schema
        along it): a property name where that object declares it, an index where the schema has an array. Anything
        else came from the data or the validator and shows as `*`: a map key, numeric (`dict[int, …]`) or named like
        a field declared elsewhere, an unknown key, a union's tag (`headers.* (int_parsing)`,
        `* (extra_forbidden)`; third and fourth reviews).
      - A rule's code shows only if pydantic-core defines it (its 104 built-in `ErrorType`s). A `PydanticCustomError`'s
        type is whatever its validator made it, the value included, so it shows as `custom_error`.
      - An unexpected exception names only its type (`The node raised ConnectionError.`), and its text goes to the
        worker's log.
      - `version_unusable`, `internal_error` and `cel_profile_unavailable` likewise.
      - An `Output` instance that breaks the declared output schema names the schema-walked location and the
        jsonschema keyword (`n (type)`), never the value.
      - CEL error messages are kept, masked: they explain the tenant's own expression, and everything an expression
        reads is data the run has already seen, so its sensitive parts have been learned.
    - Temporal's history still holds values in full, until 2b's payload encryption.

    (Tasks 2, 4, 5)
22. **A start is failed only when Temporal refused it** (new after review).
    - `start_run` starts `RunGraph` with the run's id as the workflow id, with `REJECT_DUPLICATE` (which also covers
      a run that already finished).
    - A lost acknowledgement looks like a failure, so an uncertain attempt is repeated with the same id, up to 3
      attempts in all. A duplicate refusal (`WorkflowAlreadyStartedError`) confirms the earlier start.
    - `start_failed` is recorded only for a confirmed refusal: an `RPCError` of `INVALID_ARGUMENT`, `NOT_FOUND`,
      `PERMISSION_DENIED`, `UNAUTHENTICATED`, `FAILED_PRECONDITION`, `OUT_OF_RANGE` or `UNIMPLEMENTED` before any
      uncertain attempt, or throttling (`RESOURCE_EXHAUSTED`) on every attempt.
    - Anything else leaves the run `running` and raises `StartUncertainError`, and `dewpoint dev run` exits 3. 2b's
      dispatcher retries until it knows.

    (Tasks 6, 7)
23. **Admission holds the workflow still** (new at checkpoint 3). Admission reads whether the workflow is enabled and
    which version is active; a disable, publish or activation that committed between that read and the insert left a
    run the workflow no longer admits.
    - Admission takes the workflow's admission lock *shared* before it reads the workflow, and holds it until the run
      is inserted. Every change to a workflow takes it *exclusively*, before its row lock (`get_workflow` with
      `for_update`). So a change either commits before the read, and admission refuses, or waits until the run
      exists.
    - It is an advisory lock keyed `dewpoint:workflow:<id>`, like the lifecycle locks: a row lock would need UPDATE
      on `workflows`, which `dewpoint_dispatch` must not have.
    - Both sides take the workflow's lock before any lifecycle lock. A change waiting for an admission holds nothing
      that admission's insert needs.

    (Task 6)

## Global Constraints

- Python ≥ 3.12. `temporalio==1.33.0` exactly (Task 4 adds it; it brings `nexus-rpc==1.4.0`); `protobuf` stays at the
  locked 7.36.2.
- `dewpoint.engine` stays pure: no `dewpoint.core`, `dewpoint.apps`, `dewpoint.plugins`, SQLAlchemy, asyncpg,
  FastAPI or httpx. It may import `temporalio`: only `engine/runtime/workflow.py` does.
- `dewpoint.engine.runtime` imports no `random`, `secrets`, `time`, `socket`, `subprocess`, `threading`, `os` or
  `structlog` (the new contract, Task 1). Workflow code gets time from `workflow.now()` only, waits on
  `asyncio.sleep` (a durable timer) or `workflow.wait`, never iterates a set, and builds every dict in a fixed order.
- Unchanged from 2a-2: `CURRENT_CEL_PROFILE` is `cel-cpp-0.1.3/fn-1/cls-1`, and `LOCAL_CEL_PROFILE` stays `None`. New:
  `ENGINE_ABI = 1` (Task 8).
- Limits: 100 steps in flight per execution (`IN_FLIGHT_CAP`), plus one projection; 100 loop items inline
  (`INLINE_ITEMS`); 100,000 iterations and filter items per run (`ITERATION_CAP`); 1,000 binding sets per
  `cel.evaluate` request (`CEL_BATCH`); 8 KiB per preview (`PREVIEW_BYTES`); 500 characters per stored message or
  code (`MESSAGE_LIMIT`); 30 days per run (`max_run_duration_days`); 600 s CEL schedule-to-start; 3 `cel.evaluate`
  attempts; 30 s start-to-close for the version loader and each projection; masked values of at least 4 characters
  (`MIN_SECRET`); 3 start attempts, 0.5 s and 2 s apart (`START_RETRY_S`).
- Plugin steps: each attempt is one activity execution (`RetryPolicy(maximum_attempts=1)`), scheduled by `RunGraph`,
  which alone decides retries and writes rows (decisions 7, 12).
- Names:
  - task queues `dewpoint-engine` (`ENGINE_QUEUE`) and `dewpoint-cel.<profile>`;
  - workflow type `RunGraph`, whose workflow id is the run id;
  - activities `dewpoint.load_version` (a local activity), `dewpoint.project`, `cel.evaluate`, and `<type>.v<N>`
    for each plugin node (`testkit.echo@1` runs as `testkit.echo.v1`).
- **Carried from 2a-1 and 2a-2: a reference default replaces a missing *and* a `null` value.**
- Tests:
  - `tests/engine/**` needs no database.
  - `tests/apps/worker/**` starts Temporal's time-skipping test server, which the SDK downloads on first use (the
    owner approved it for the suite and CI).
  - Temporal's runtime threads outlive a test. The evaluator's fork tests (`tests/apps/cel_evaluator`) require a
    single-threaded process on Linux, so they must run before any test that starts a Temporal worker or `Replayer`.
    Path order guarantees it (`cel_evaluator` < `cli` < `test_*.py` < `worker`, and `tests/apps` < `tests/engine`),
    so don't reorder the suite (no `pytest-randomly`).
- Downloads and images:
  - Task 4's `uv add temporalio` downloads packages: confirm with the owner first.
  - The Postgres test image is already approved.
  - No other image or tool is pulled.
- Conventions:
  - SPDX header on every source file; comments explain why;
  - commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - run the checks and the commit in one `&&` chain;
  - never push, open a PR or enable auto-merge without the owner's word;
  - keep the branches `feat/foundations`, `spike/cel-evaluation`, `docs/engine-core-spec`, `feat/engine-2a1`,
    `docs/engine-2a2-plan` and `feat/engine-2a2`; leave the untracked `spikes/` alone.
- Checks (from `backend/`):
  - `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`;
  - tests: `uv run pytest -q <paths>`. The full suite needs Docker for Postgres.

## Review Focus

The inputs and conditions most likely to bite a person using this, beyond what the spec names. Each has a test in the
task that owns the code:

1. **A trigger payload that breaks the workflow's input schema.** 2a doesn't validate payloads. The step that reads
   the bad value fails (`evaluation_error` or `type_mismatch`) under its error policy, and the run ends visibly; the
   workflow never crashes. (Task 5:
   `test_a_trigger_that_breaks_its_schema_fails_a_step_not_the_workflow`)
2. **A node type the registry lists but this build's workers don't run** (a plugin missing from one deploy). The
   step fails with `node_type_unavailable` after its attempts, and nothing hangs. (Task 5:
   `test_a_node_type_this_worker_does_not_serve_fails_its_step`)
3. **A worker restart or cache eviction mid-run.** The next workflow task replays the whole history and the run
   carries on. With no cache, every task replays. (Task 5:
   `test_a_worker_without_the_run_in_its_cache_replays_it_and_carries_on`; golden histories, Task 8)
4. **Error policies mixed across nested loops.** An inner loop that stops fails only its outer iteration; an outer
   `continue` records it and goes on. (Task 1: `test_an_inner_loop_that_stops_fails_only_its_outer_iteration`)
5. **The database failing mid-run.** A step's effect runs once; the projection retries until the database is back,
   and then every row catches up, none left `running`. (Task 5:
   `test_a_database_outage_never_repeats_an_effect_and_the_rows_catch_up`)

## File structure

```
backend/src/dewpoint/engine/runtime/
  __init__.py      the package                                                                      Task 1
  program.py       a version compiled for execution: steps, edges by port, regions, records         Task 1
  scheduler.py     scopes, node and edge states, readiness, dead paths, loops, how a run ends       Task 1
  resolve.py       ScopeView per scope; refs, templates, CEL tasks; assembling configs              Task 2
  nodes.py         what each control node decides                                                   Task 2
  projection.py    previews: redaction through $ref and unions, masking of learned values, truncation  Task 2
  activities.py    activity names and their input and output dataclasses                            Task 4
  workflow.py      RunGraph: loads, drives the scheduler, runs values and steps, projects          Task 5
  build.py         ENGINE_ABI and the build id                                                      Task 8
backend/src/dewpoint/apps/worker/
  __init__.py, context.py, activities.py   StepContext; one attempt of a plugin step; loader, projection, CEL   Task 4
  store.py         the RunStore over the database                                                   Task 7
  main.py          `dewpoint worker`: the engine worker and the CEL worker                           Task 7
backend/src/dewpoint/core/runs/            __init__.py, service.py: runs and run_steps storage      Task 3
backend/src/dewpoint/core/models/runs.py   Run, RunStep (and models/__init__.py)                    Task 3
backend/migrations/versions/0008_runs.py   runs, run_steps, RLS, grants                             Task 3
backend/src/dewpoint/apps/runs.py          admit, start_run                                         Task 6
backend/src/dewpoint/core/workflows/service.py  (modify) the workflow's admission lock              Task 6
backend/src/dewpoint/core/config.py        (modify) Temporal and CEL settings                       Tasks 6, 7
backend/src/dewpoint/apps/api/routes/runs.py, api/main.py (modify)   GET /runs, GET /runs/{id}      Task 7
backend/src/dewpoint/apps/cli/main.py      (modify) `dewpoint worker`, `dewpoint dev run`           Task 7
backend/pyproject.toml, uv.lock            (modify) the determinism contract; temporalio            Tasks 1, 4
backend/tests/engine/runtime/              support.py and unit and property tests                   Tasks 1, 2
backend/tests/core/runs/                   storage tests; tests/conftest.py (modify) dispatch role  Task 3
backend/tests/support/plugins/testkit.py   (modify) Echo.simulate, the Reconcile node               Task 4
backend/tests/apps/worker/                 activity, RunGraph, database and dev-run tests; harness  Tasks 4, 5, 7
backend/tests/apps/test_runs.py            admission; test_lifecycle_races.py (modify)              Task 6
backend/tests/apps/cli/test_dev_run_cli.py                                                          Task 7
backend/tests/engine/replay/               scenarios, recorder, replay test, recorded histories     Task 8
docs/operations/runs.md, README.md                                                                  Task 7
(spec revision 5.4 lands with this plan in the docs PR, before Task 1)
```

## Suggested checkpoints (the owner's milestone reviews)

1. **After Task 2:** the deterministic core (program, scheduler, values, control nodes, previews), with no Temporal
   yet.
2. **After Task 5:** storage, the activities and `RunGraph`: runs execute end to end on the test server.
3. **After Task 8:** admission, the worker, the API, the CLI, the docs and the golden histories. Then the
   whole-branch review.

## Branching

As in 2a-1 and 2a-2:
1. This plan and spec revision 5.4 land in a docs-only PR from `main`, on branch `docs/engine-2a3a-plan`.
2. After it merges, implementation starts on `feat/engine-2a3a` from the updated `main`.

---

### Task 1: The compiled program and the scheduler

The deterministic heart of `RunGraph`: which step may run, in which scope, and what a result or a failure does to
the edges after it. It knows nothing of Temporal, values or effects. The workflow (Task 5) hands it results, and it
answers with the next steps. Property tests drive it over random graphs.

**Files:**
- Modify: `backend/pyproject.toml` (the determinism import contract)
- Create: `backend/src/dewpoint/engine/runtime/__init__.py`, `program.py`, `scheduler.py`
- Create: `backend/tests/engine/runtime/__init__.py` (empty), `support.py`, `test_program.py`, `test_scheduler.py`,
  `test_scheduler_properties.py`

**Interfaces:**
- Consumes (from `main`): `parse_graph`, `analyze_structure(graph, catalog) -> (Structure | None, diagnostics)`,
  `ERROR_PORT` and `Region` (`engine.graph.structure`), `Catalog` and `spec_from_manifest`
  (`engine.registry.catalog`), `iter_values`, `pointer_str`, `CelValue` and `ValueSyntaxError`
  (`engine.graph.values`), `ExpressionRecord.from_json` (`engine.cel.record`); in tests, `validate`,
  `ValidationContext`, `SubflowInfo`, `tests.support.graphs` (`G`, `nid`, `ref`, `cel`), `tests.support.catalog`, the
  flow plugin and `TESTKIT`.
- Produces:
  - `program.py`: `BODY = "body"`, `DONE = "done"`, `ERROR_PORT`, `ProgramError(ValueError)`,
    `Edge(index, source, port, target)`, and `Step` with the fields `id`, `key`, `ref`, `control`, `region`,
    `topo`, `on_error`, `timeout_s`, `max_attempts`, `config`, `values`, `ports`, `out`, `ins`.
    `Program(graph, steps, edges, regions, by_key, records, manifests, cel_profile)` has
    `.chain(region) -> list[uuid.UUID | None]` and `.record(step_id | None, field) -> ExpressionRecord`.
    `compile_program(graph_json, manifests, expressions, cel_profile) -> Program` raises `ProgramError` for a version
    it can't run.
  - `scheduler.py`:
    - `ScopeKey = tuple[tuple[str, int], ...]`, `ITERATION_CAP = 100_000`, `ITERATION_CAP_EXCEEDED`;
    - the enums `NodeState` and `EdgeState`, and `SETTLED`;
    - `iteration_key(scope) -> str`;
    - `Instance(scope, step)` (frozen, ordered), `Failure(code, message, attempt=1)` with `.to_json()`, `Scope`,
      `LoopRun`, `Collect(loop, index, scope)`, and `RunEnd(status, failure=None, stopped=False)`;
    - `Scheduler(program, *, iteration_cap=ITERATION_CAP)`: `start()`, `take_ready()`, `take_collects()`,
      `take_settled()`, `take_cancels()`, `succeed(inst, output, ports=None)`, `fail(inst, failure)`,
      `open_loop(inst, items, *, concurrency, stop_on_error)`, `debit(count) -> bool`,
      `collected(loop_inst, index, value)`, `collect_failed(loop_inst, index, failure)`,
      `finish(inst, end, output=None)`, `end(end)`, `step(inst)`, `scope(key)` and `order(inst)`. Its attributes
      are `program`, `scopes`, `loops`, `ended` and `iterations`.
  - `tests/engine/runtime/support.py`: `MANIFESTS`, `CATALOG`, `expressions(g, subflows=None)`, `program(g)` and
    `name(scheduler, inst)`.

- [ ] **Step 1: Write the failing tests**

Create the empty file `backend/tests/engine/runtime/__init__.py`.

Create `backend/tests/engine/runtime/support.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Compile test graphs the way a published version is compiled: validated first, with its expression records."""

import uuid
from collections.abc import Mapping
from typing import Any

from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import SubflowInfo, ValidationContext, validate
from dewpoint.engine.runtime.program import Program, compile_program
from dewpoint.engine.runtime.scheduler import Instance, Scheduler, iteration_key
from dewpoint.plugins.flow import PLUGIN
from tests.support.catalog import catalog
from tests.support.graphs import G
from tests.support.plugins.testkit import TESTKIT

MANIFESTS: dict[str, dict[str, Any]] = {
    f"{m['type']}@{m['version']}": m for p in (PLUGIN, TESTKIT) for m in p.manifest()["nodes"]
}
CATALOG = catalog(PLUGIN, TESTKIT)


def expressions(g: G, subflows: Mapping[uuid.UUID, SubflowInfo] | None = None) -> list[dict[str, Any]]:
    result = validate(g.build(), ValidationContext(catalog=CATALOG, subflows=subflows or {}))
    errors = [d.to_json() for d in result.diagnostics if d.severity == "error"]
    assert not errors, errors
    return [r.to_json() for r in result.expressions]


def program(g: G) -> Program:
    return compile_program(g.data(), MANIFESTS, expressions(g), CURRENT_CEL_PROFILE)


def name(s: Scheduler, inst: Instance) -> str:
    key = iteration_key(inst.scope)
    return f"{key}/{s.step(inst).key}" if key else s.step(inst).key
```

Create `backend/tests/engine/runtime/test_program.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A published version compiled for execution (spec §6), and the versions that can't be."""

import pytest

from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.program import ProgramError, compile_program
from tests.engine.runtime.support import MANIFESTS, expressions, program
from tests.support.graphs import G, cel, nid, ref


def graph() -> G:
    g = G()
    g.settings = {"outputs": {"n": ref("steps.l.output.count", default=0)}}
    g.node("a", "testkit.echo@1", {"value": 1}, on_error="port")
    g.node("l", "flow.loop@1", {"items": [1], "collect": cel("item + 1")})
    g.node("x", "testkit.echo@1", {"value": ref("item")}).node("h", "testkit.echo@1")
    return g.edge("a", "l").edge("l", "x", "body").edge("l", "h", "done").edge("a", "h", "error")


def test_steps_know_their_edges_ports_and_region() -> None:
    p = program(graph())
    a, loop, x = (p.steps[nid(k)] for k in ("a", "l", "x"))
    assert [p.steps[s].key for s in sorted(p.steps, key=lambda s: p.steps[s].topo)] == ["a", "l", "h", "x"]
    assert (a.control, loop.control, a.region, x.region) == (False, True, None, loop.id)
    assert {port: [p.edges[i].target for i in ids] for port, ids in a.out.items()} == {
        "error": [nid("h")],
        "out": [nid("l")],
    }
    assert [pointer for pointer, _ in loop.values] == ["/collect"] and p.chain(x.region) == [loop.id, None]
    assert p.record(loop.id, "/collect").expr == "item + 1"


def test_a_version_this_build_cannot_run_is_refused() -> None:
    g = graph()
    with pytest.raises(ProgramError):  # a node type this build doesn't have
        compile_program(g.data(), {k: v for k, v in MANIFESTS.items() if k != "testkit.echo@1"}, expressions(g), "p")
    with pytest.raises(ProgramError, match="`l`: no expression record for /collect"):  # damaged: fail before any step
        compile_program(g.data(), MANIFESTS, [], CURRENT_CEL_PROFILE)
    g.settings["outputs"] = {"n": cel("has(steps.l.output) ? steps.l.output.count : 0")}
    records = [r for r in expressions(g) if r["node"] is not None]
    with pytest.raises(ProgramError, match="no expression record for /settings/outputs/n"):
        compile_program(g.data(), MANIFESTS, records, CURRENT_CEL_PROFILE)


def test_a_damaged_output_is_refused() -> None:
    """Checkpoint-2 finding: compile checked the outputs' CEL records but not their envelopes, so a malformed output
    compiled, and evaluating it later raised outside the run's handlers."""
    g = graph()
    records = expressions(g)
    g.settings["outputs"] = {"n": {"$value": {"kind": "ref", "path": 5}}}  # publish refuses this; a damaged row
    with pytest.raises(ProgramError, match="/settings/outputs/n"):
        compile_program(g.data(), MANIFESTS, records, CURRENT_CEL_PROFILE)
```

Create `backend/tests/engine/runtime/test_scheduler.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The scheduler's rules (spec §6): readiness, edge resolution, dead paths, error policies, loop iterations."""

from typing import Any

from dewpoint.engine.runtime.scheduler import Failure, NodeState, RunEnd, Scheduler
from tests.engine.runtime.support import name, program
from tests.support.graphs import G

ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"
BOOM = Failure("testkit.boom", "it broke")


def started(g: G) -> Scheduler:
    s = Scheduler(program(g))
    s.start()
    return s


def ready(s: Scheduler) -> list[str]:
    return [name(s, i) for i in s.take_ready()]


def run_all(s: Scheduler) -> list[str]:
    """Succeed every step in the order the scheduler hands them over; loops get two items."""
    order: list[str] = []
    while s.ended is None:
        batch = s.take_ready()
        collects = s.take_collects()
        if not batch and not collects:
            raise AssertionError("stuck: nothing ready, nothing to collect")
        for inst in batch:
            order.append(name(s, inst))
            if s.step(inst).ref == LOOP:
                s.open_loop(inst, ["a", "b"], concurrency=1, stop_on_error=True)
            else:
                s.succeed(inst, {"n": name(s, inst)}, ("true",) if s.step(inst).ref == IF else None)
        for c in collects:
            s.collected(c.loop, c.index, c.index * 10)
    return order


def test_a_chain_runs_in_order_and_the_run_succeeds() -> None:
    s = started(G().node("a", ECHO).node("b", ECHO).node("c", ECHO).edge("a", "b").edge("b", "c"))
    assert run_all(s) == ["a", "b", "c"]
    assert s.ended == RunEnd("succeeded")
    assert s.scopes[()].results["c"] == {"output": {"n": "c"}}


def test_branches_meet_again_in_the_same_scope() -> None:
    """if → A | B → C: with `true`, A runs, B dies, and C runs once, in the root scope."""
    g = (
        G()
        .node("c", IF, {"condition": True})
        .node("a", ECHO)
        .node("b", ECHO)
        .node("j", ECHO)
        .edge("c", "a", "true")
        .edge("c", "b", "false")
        .edge("a", "j")
        .edge("b", "j")
    )
    s = started(g)
    assert run_all(s) == ["c", "a", "j"]
    root = s.scopes[()]
    assert root.nodes[s.program.by_key["b"]] == NodeState.DEAD and "b" not in root.results
    assert s.ended == RunEnd("succeeded")


def test_a_switch_takes_one_port_and_kills_the_rest() -> None:
    cases = [{"port": "x", "when": True}, {"port": "y", "when": True}]
    g = G().node("s", SWITCH, {"cases": cases}).node("x", ECHO).node("y", ECHO).node("d", ECHO)
    g.edge("s", "x", "x").edge("s", "y", "y").edge("s", "d", "default")
    s = started(g)
    [sw] = s.take_ready()
    s.succeed(sw, {}, ("y",))
    assert ready(s) == ["y"]
    states = {k: s.scopes[()].nodes[s.program.by_key[k]] for k in ("x", "d")}
    assert states == {"x": NodeState.DEAD, "d": NodeState.DEAD}


def test_error_port_routes_a_failure_and_records_the_error() -> None:
    g = G().node("a", ECHO, on_error="port").node("ok", ECHO).node("handler", ECHO)
    g.edge("a", "ok").edge("a", "handler", "error")
    s = started(g)
    [a] = s.take_ready()
    s.fail(a, BOOM)
    assert ready(s) == ["handler"]
    assert s.scopes[()].results["a"] == {"error": BOOM.to_json()}
    assert s.scopes[()].nodes[s.program.by_key["ok"]] == NodeState.DEAD


def test_continue_follows_the_normal_edges_without_an_output() -> None:
    s = started(G().node("a", ECHO, on_error="continue").node("b", ECHO).edge("a", "b"))
    [a] = s.take_ready()
    s.fail(a, BOOM)
    assert ready(s) == ["b"]
    assert s.scopes[()].results["a"] == {"error": BOOM.to_json()}  # `has(steps.a.output)` is false (spec §5.3)


def test_an_unhandled_failure_fails_the_run_and_cancels_running_steps() -> None:
    s = started(G().node("a", ECHO).node("b", ECHO))
    a, b = s.take_ready()
    s.fail(a, BOOM)
    assert s.ended == RunEnd("failed", BOOM)
    assert [name(s, i) for i in s.take_cancels()] == ["b"]
    s.succeed(b, {})  # a late result from cancelled work counts for nothing
    assert "b" not in s.scopes[()].results


def loop_graph(**config: Any) -> G:
    g = G().node("l", LOOP, {"items": [1, 2, 3], **config}).node("x", ECHO).node("y", ECHO).node("after", ECHO)
    return g.edge("l", "x", "body").edge("x", "y").edge("l", "after", "done")


def test_iterations_run_one_at_a_time_and_collect_in_order() -> None:
    s = started(loop_graph())
    [loop] = s.take_ready()
    s.open_loop(loop, ["a", "b", "c"], concurrency=1, stop_on_error=True)
    seen = []
    for index in range(3):
        [x] = s.take_ready()
        seen.append(name(s, x))
        s.succeed(x, {})
        [y] = s.take_ready()
        s.succeed(y, {})
        [c] = s.take_collects()
        assert (c.index, c.scope) == (index, (("l", index),))
        assert s.scopes[c.scope].item == ["a", "b", "c"][index]
        s.collected(c.loop, c.index, f"v{index}")
    assert seen == ["l:0/x", "l:1/x", "l:2/x"]
    assert ready(s) == ["after"]
    assert s.scopes[()].results["l"] == {"output": {"items": ["v0", "v1", "v2"], "failures": [], "count": 3}}
    assert s.iterations == 3


def test_concurrency_opens_that_many_iterations() -> None:
    s = started(loop_graph())
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2, 3], concurrency=2, stop_on_error=True)
    assert ready(s) == ["l:0/x", "l:1/x"]


def test_continue_on_item_error_records_the_failure_and_a_null_item() -> None:
    s = started(loop_graph())
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2], concurrency=1, stop_on_error=False)
    [x0] = s.take_ready()
    s.fail(x0, BOOM)
    [x1] = s.take_ready()
    assert name(s, x1) == "l:1/x"
    s.succeed(x1, {})
    [y1] = s.take_ready()
    s.succeed(y1, {})
    [c] = s.take_collects()
    s.collected(c.loop, c.index, "ok")
    assert s.scopes[()].results["l"]["output"] == {
        "items": [None, "ok"],
        "failures": [{"index": 0, "code": "testkit.boom", "message": "it broke"}],
        "count": 2,
    }


def test_stop_on_item_error_ends_the_other_iterations_and_fails_the_loop() -> None:
    g = loop_graph()
    g.nodes[0]["options"]["on_error"] = "port"
    g.node("handler", ECHO).edge("l", "handler", "error")
    s = started(g)
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2], concurrency=2, stop_on_error=True)
    x0, x1 = s.take_ready()
    s.fail(x0, BOOM)
    assert [name(s, i) for i in s.take_cancels()] == ["l:1/x"]
    assert ready(s) == ["handler"]
    assert s.scopes[()].results["l"] == {"error": BOOM.to_json()}
    s.succeed(x1, {})  # the cancelled iteration's late result is ignored
    assert s.ended is None


def test_an_inner_loop_that_stops_fails_only_its_outer_iteration() -> None:
    """Policies compose: the inner loop stops on its item's failure and fails, which fails the outer iteration; the
    outer loop continues past it and records it."""
    g = G().node("outer", LOOP, {"items": [1, 2], "on_item_error": "continue"}).node("inner", LOOP, {"items": [1]})
    g.node("x", ECHO).node("after", ECHO)
    g.edge("outer", "inner", "body").edge("inner", "x", "body").edge("outer", "after", "done")
    s = started(g)
    [outer] = s.take_ready()
    s.open_loop(outer, [1, 2], concurrency=1, stop_on_error=False)
    [inner] = s.take_ready()
    s.open_loop(inner, ["p"], concurrency=1, stop_on_error=True)
    [x] = s.take_ready()
    s.fail(x, BOOM)  # the inner loop stops and fails; outer:0 fails with it
    [inner] = s.take_ready()
    assert name(s, inner) == "outer:1/inner"
    s.open_loop(inner, [], concurrency=1, stop_on_error=True)  # outer:1 settles at once
    [collect] = s.take_collects()
    s.collected(collect.loop, collect.index, "second")
    assert ready(s) == ["after"]
    assert s.scopes[()].results["outer"] == {
        "output": {
            "items": [None, "second"],
            "failures": [{"index": 0, "code": BOOM.code, "message": BOOM.message}],
            "count": 2,
        }
    }


def test_nested_loops_open_nested_scopes() -> None:
    g = (
        G()
        .node("outer", LOOP, {"items": [1]})
        .node("inner", LOOP, {"items": [1]})
        .node("x", ECHO)
        .edge("outer", "inner", "body")
        .edge("inner", "x", "body")
    )
    s = started(g)
    [outer] = s.take_ready()
    s.open_loop(outer, [1, 2], concurrency=1, stop_on_error=True)
    [inner] = s.take_ready()
    assert name(s, inner) == "outer:0/inner"
    s.open_loop(inner, ["p", "q"], concurrency=2, stop_on_error=True)
    assert ready(s) == ["outer:0/inner:0/x", "outer:0/inner:1/x"]


def test_an_empty_loop_completes_at_once() -> None:
    s = started(loop_graph())
    [loop] = s.take_ready()
    s.open_loop(loop, [], concurrency=1, stop_on_error=True)
    assert ready(s) == ["after"]
    assert s.scopes[()].results["l"] == {"output": {"items": [], "failures": [], "count": 0}}


def test_the_iteration_cap_fails_the_loop() -> None:
    s = Scheduler(program(loop_graph()), iteration_cap=2)
    s.start()
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2, 3], concurrency=3, stop_on_error=True)
    assert s.ended is not None and s.ended.failure is not None
    assert s.ended.failure.code == "iteration_cap_exceeded"


def test_the_iteration_cap_ends_the_loops_queued_iterations_too() -> None:
    """Checkpoint-1 finding: the cap failed the loop but left the iterations it had already opened. With `continue`,
    the steps after the loop ran beside them, and the run could end with a child unsettled."""
    g = loop_graph()
    g.nodes[0]["options"]["on_error"] = "continue"
    s = Scheduler(program(g), iteration_cap=2)
    s.start()
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2, 3], concurrency=3, stop_on_error=True)  # opens 0 and 1, then the third hits the cap
    assert ready(s) == ["after"]  # the queued iterations never start
    assert s.take_cancels() == [] and s.scopes[()].results["l"]["error"]["code"] == "iteration_cap_exceeded"


def test_the_iteration_cap_cancels_the_loops_running_iterations() -> None:
    g = loop_graph()
    g.nodes[0]["options"]["on_error"] = "continue"
    s = Scheduler(program(g), iteration_cap=2)
    s.start()
    [loop] = s.take_ready()
    s.open_loop(loop, [1, 2, 3], concurrency=2, stop_on_error=True)
    x0, x1 = s.take_ready()
    s.succeed(x0, {})
    [y0] = s.take_ready()
    s.succeed(y0, {})
    [collect] = s.take_collects()
    s.collected(collect.loop, collect.index, "first")  # the third iteration hits the cap while l:1 still runs
    assert [name(s, i) for i in s.take_cancels()] == ["l:1/x"]
    assert ready(s) == ["after"]
    s.succeed(x1, {})  # the cancelled iteration's late result counts for nothing
    assert s.take_ready() == [] and "y" not in s.scopes[(("l", 1),)].results


def test_a_stop_ends_the_run_and_cancels_running_work() -> None:
    s = started(G().node("a", ECHO).node("b", ECHO))
    a, _ = s.take_ready()
    s.succeed(a, {})
    s.end(RunEnd("succeeded", stopped=True))
    assert [name(s, i) for i in s.take_cancels()] == ["b"]
```

Create `backend/tests/engine/runtime/test_scheduler_properties.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Spec §10, on random graphs with if/switch/joins/error ports/loops, completed in random orders:
- every node runs or dies exactly once per scope;
- dead paths never run;
- a step runs in its own region's scope, so branches that reconverge meet in the same scope;
- no edge is left pending when a run succeeds, so nothing deadlocks."""

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from dewpoint.engine.runtime.scheduler import (
    SETTLED,
    EdgeState,
    Failure,
    Instance,
    NodeState,
    Scheduler,
)
from tests.engine.runtime.support import program
from tests.support.graphs import G

ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"


@st.composite
def graphs(draw: st.DrawFn) -> G:
    g = G()
    count = [0]
    edges: set[tuple[str, str, str]] = set()

    def edge(src: str, dst: str, port: str) -> None:
        if (src, dst, port) not in edges:
            edges.add((src, dst, port))
            g.edge(src, dst, port)

    def block(depth: int, feeds: list[tuple[str, str]]) -> None:
        """One region's nodes. Every node is reached from `feeds` (a loop's body port) or from earlier nodes of
        the block, so the region is exactly the block; the root may also start fresh."""
        outs = list(feeds)
        made: list[str] = []
        needs_error: list[str] = []
        for _ in range(draw(st.integers(1, 4 if depth == 0 else 3))):
            count[0] += 1
            key = f"n{count[0]}"
            kinds = ["echo", "echo", "if", "switch"] + (["loop"] if depth < 2 else [])
            kind = draw(st.sampled_from(kinds))
            on_error = draw(st.sampled_from(["fail", "continue", "port"])) if kind in ("echo", "loop") else "fail"
            if kind == "echo":
                g.node(key, ECHO, {"value": 1}, on_error=on_error)
                ports = ["out"]
            elif kind == "if":
                g.node(key, IF, {"condition": True})
                ports = ["true", "false"]
            elif kind == "switch":
                cases = [{"port": f"c{i}", "when": True} for i in range(draw(st.integers(1, 2)))]
                g.node(key, SWITCH, {"cases": cases})
                ports = [c["port"] for c in cases] + ["default"]
            else:
                g.node(key, LOOP, {"items": [1]}, on_error=on_error)
                ports = ["done"]
            sources = draw(st.lists(st.sampled_from(outs), unique=True, max_size=2)) if outs else []
            if not sources and depth > 0:
                sources = [draw(st.sampled_from(outs))]
            for src, port in sources:
                edge(src, key, port)
            if kind == "loop":
                block(depth + 1, [(key, "body")])
            if on_error == "port":
                needs_error.append(key)
            made.append(key)
            outs += [(key, p) for p in ports]
        for key in needs_error:  # an error port must lead somewhere: a later step, or a new handler
            later = made[made.index(key) + 1 :]
            if later:
                edge(key, draw(st.sampled_from(later)), "error")
            else:
                count[0] += 1
                handler = f"n{count[0]}"
                g.node(handler, ECHO, {"value": 1})
                edge(key, handler, "error")
                made.append(handler)

    block(0, [])
    return g


def _entry_ok(s: Scheduler, inst: Instance) -> bool:
    scope = s.scopes[inst.scope]
    states = [scope.edges[e] for e in s.step(inst).ins if e in scope.edges]
    return all(x != EdgeState.PENDING for x in states) and (not states or EdgeState.LIVE in states)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(graphs(), st.data())
def test_random_runs_keep_the_scheduling_invariants(g: G, data: st.DataObject) -> None:
    s = Scheduler(program(g))
    s.start()
    running: list[Instance] = []
    collects: list[Any] = []
    handed: dict[Instance, int] = {}
    while s.ended is None:
        for inst in s.take_ready():
            handed[inst] = handed.get(inst, 0) + 1
            assert handed[inst] == 1, "a step ran twice in one scope"
            assert s.scopes[inst.scope].region == s.step(inst).region, "a step ran outside its region's scope"
            assert _entry_ok(s, inst), "a step ran without a live incoming edge"
            running.append(inst)
        collects += s.take_collects()
        cancelled = set(s.take_cancels())
        running = [r for r in running if r not in cancelled]
        if not running and not collects:
            raise AssertionError("stuck: nothing running, nothing to collect, and the run hasn't ended")
        pick = data.draw(st.integers(0, len(running) + len(collects) - 1))
        if pick >= len(running):
            c = collects.pop(pick - len(running))
            if data.draw(st.integers(0, 5), label="collect") == 0:
                s.collect_failed(c.loop, c.index, Failure("evaluation_error", "collect failed"))
            else:
                s.collected(c.loop, c.index, c.index)
            continue
        inst = running.pop(pick)
        step = s.step(inst)
        if step.ref == LOOP:
            items = list(range(data.draw(st.integers(0, 3), label="items")))
            s.open_loop(
                inst,
                items,
                concurrency=data.draw(st.integers(1, 2), label="concurrency"),
                stop_on_error=data.draw(st.booleans(), label="stop"),
            )
        elif step.ref in (IF, SWITCH):
            s.succeed(inst, {}, (data.draw(st.sampled_from(step.ports), label="port"),))
        elif data.draw(st.integers(0, 4), label="outcome") == 0:
            s.fail(inst, Failure("testkit.boom", "it broke"))
        else:
            s.succeed(inst, {"n": 1})
    # dead steps never ran; every step of a scope that finished normally settled, with no edge left pending
    for scope in s.scopes.values():
        for node_id, state in scope.nodes.items():
            if state == NodeState.DEAD and scope.failure is None:
                assert Instance(scope.key, node_id) not in handed, "a dead step ran"
        if s.ended.status == "succeeded" and scope.failure is None:
            assert all(state in SETTLED for state in scope.nodes.values()), "a step never settled"
            assert EdgeState.PENDING not in scope.edges.values(), "an edge was left pending"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/runtime`
Expected: 3 collection errors, `ModuleNotFoundError: No module named 'dewpoint.engine.runtime'`.

- [ ] **Step 3: Implement the program and the scheduler**

Create `backend/src/dewpoint/engine/runtime/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`RunGraph`'s deterministic core (spec §6): a compiled version, the scheduler, value resolution and the control
nodes. It runs inside Temporal's sandbox: no I/O, no wall clock, no randomness."""
```

Create `backend/src/dewpoint/engine/runtime/program.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A published version compiled for execution (spec §6): each step with its edges by port, its region and its
topological index, and the expression records by (node, field). Built once per run from the loaded version, and
never changed."""

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.graph.model import Graph, parse_graph
from dewpoint.engine.graph.structure import ERROR_PORT, Region, analyze_structure
from dewpoint.engine.graph.values import CelValue, Value, ValueSyntaxError, iter_values, pointer_str
from dewpoint.engine.registry.catalog import Catalog, spec_from_manifest

BODY, DONE = "body", "done"


class ProgramError(ValueError):
    """The version can't be executed. Publish validated it, so this means the stored version is damaged."""


@dataclass(frozen=True)
class Edge:
    index: int
    source: uuid.UUID
    port: str
    target: uuid.UUID


@dataclass(frozen=True)
class Step:
    id: uuid.UUID
    key: str
    ref: str  # type@version
    control: bool  # run by the interpreter (the flow plugin); otherwise an activity named `type.vN`
    region: uuid.UUID | None  # the loop whose body holds it; None for the root region
    topo: int
    on_error: str  # fail | continue | port
    timeout_s: float | None
    max_attempts: int | None
    config: Mapping[str, Any]
    values: tuple[tuple[str, Value], ...]  # every envelope in the config, by JSON pointer, in pointer order
    ports: tuple[str, ...]  # normal ports ("error" excluded)
    out: Mapping[str, tuple[int, ...]]  # edges leaving each port, "error" included when connected
    ins: tuple[int, ...]  # edges arriving, body edges from the step's own loop included


@dataclass(frozen=True)
class Program:
    graph: Graph
    steps: Mapping[uuid.UUID, Step]
    edges: tuple[Edge, ...]
    regions: Mapping[uuid.UUID | None, Region]
    by_key: Mapping[str, uuid.UUID]
    records: Mapping[tuple[str | None, str], ExpressionRecord]
    manifests: Mapping[str, Mapping[str, Any]]  # type@version -> the registered manifest
    cel_profile: str

    def chain(self, region: uuid.UUID | None) -> list[uuid.UUID | None]:
        """`region` and every region enclosing it, innermost first, ending with the root (None)."""
        out: list[uuid.UUID | None] = [region]
        while region is not None:
            region = self.regions[region].parent
            out.append(region)
        return out

    def record(self, step: uuid.UUID | None, field: str) -> ExpressionRecord:
        found = self.records.get((str(step) if step is not None else None, field))
        if found is None:
            raise ProgramError(f"no expression record for {field!r}")
        return found


def compile_program(
    graph_json: Mapping[str, Any],
    manifests: Mapping[str, Mapping[str, Any]],
    expressions: Iterable[Mapping[str, Any]],
    cel_profile: str,
) -> Program:
    graph = parse_graph(graph_json)
    structure, diagnostics = analyze_structure(graph, Catalog(spec_from_manifest(m) for m in manifests.values()))
    errors = [d for d in diagnostics if d.severity == "error"]
    if structure is None or errors:
        raise ProgramError("; ".join(d.message for d in errors) or "the graph can't be analyzed")
    edges = tuple(Edge(i, e.source.node, e.source.port, e.to.node) for i, e in enumerate(graph.edges))
    topo = {n: i for i, n in enumerate(structure.topo)}
    steps: dict[uuid.UUID, Step] = {}
    for node_id in structure.topo:  # a fixed order, so every mapping below is built the same way everywhere
        node = structure.nodes[node_id]
        values: list[tuple[str, Value]] = []
        for pointer, value in iter_values(node.config):
            if isinstance(value, ValueSyntaxError):
                raise ProgramError(f"`{node.key}`: {value.message}")
            values.append((pointer_str(pointer), value))
        out: dict[str, list[int]] = {}
        for e in edges:
            if e.source == node_id:
                out.setdefault(e.port, []).append(e.index)
        steps[node_id] = Step(
            id=node_id,
            key=node.key,
            ref=node.type,
            control=structure.specs[node_id].kind == "control",
            region=structure.region_of[node_id],
            topo=topo[node_id],
            on_error=node.options.on_error,
            timeout_s=node.options.timeout_s,
            max_attempts=node.options.max_attempts,
            config=node.config,
            values=tuple(values),
            ports=structure.ports[node_id],
            out={port: tuple(ids) for port, ids in sorted(out.items())},
            ins=tuple(e.index for e in edges if e.target == node_id),
        )
    records = {(r.node, r.field): r for r in (ExpressionRecord.from_json(x) for x in expressions)}
    for step in steps.values():  # every CEL value needs its record: checked before any step runs
        for field, value in step.values:
            if isinstance(value, CelValue) and (str(step.id), field) not in records:
                raise ProgramError(f"`{step.key}`: no expression record for {field}")
    for path, value in iter_values(graph.settings.outputs, ("settings", "outputs")):
        if isinstance(value, ValueSyntaxError):  # publish refuses these: the stored version is damaged
            raise ProgramError(f"output {pointer_str(path)}: {value.message}")
        if isinstance(value, CelValue) and (None, pointer_str(path)) not in records:
            raise ProgramError(f"no expression record for {pointer_str(path)}")
    return Program(
        graph=graph,
        steps=steps,
        edges=edges,
        regions=structure.regions,
        by_key=dict(structure.by_key),
        records=records,
        manifests=dict(manifests),
        cel_profile=cel_profile,
    )


__all__ = ["BODY", "DONE", "ERROR_PORT", "Edge", "Program", "ProgramError", "Step", "compile_program"]
```

Create `backend/src/dewpoint/engine/runtime/scheduler.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The scheduler (spec §6): node and edge states per scope, readiness, edge resolution, dead-path elimination, loop
iterations and how a run ends. It decides nothing about values or effects: the workflow runs each ready step and
reports how it ended. It is deterministic: its dicts are filled in a fixed order, and its ready queue is ordered by
(scope, topological index).

A scope is the root, or one loop iteration: `()` or `(("loop2", 7), ("loop5", 3))`. Branches don't open scopes, so
paths that split at an `if` meet again in the same scope. Each node runs or dies exactly once per scope."""

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dewpoint.engine.runtime.program import BODY, DONE, ERROR_PORT, Program, Step

ScopeKey = tuple[tuple[str, int], ...]
ITERATION_CAP = 100_000  # loop iterations and filter items across the whole logical run (spec §4.2)
ITERATION_CAP_EXCEEDED = "iteration_cap_exceeded"


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

    @property
    def settled(self) -> bool:
        return self.failure is not None or all(s in SETTLED for s in self.nodes.values())


@dataclass
class LoopRun:
    """A loop node's iterations: opened in order, at most `concurrency` at a time."""

    instance: Instance
    items: list[Any]
    concurrency: int
    stop_on_error: bool
    next: int = 0
    open: list[int] = field(default_factory=list)
    collecting: set[int] = field(default_factory=set)  # settled iterations whose `collect` is being evaluated
    collected: list[Any] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Collect:
    """An iteration settled without an unhandled failure: evaluate the loop's `collect` in `scope`."""

    loop: Instance
    index: int
    scope: ScopeKey


@dataclass(frozen=True)
class RunEnd:
    status: str  # succeeded | failed | deadline_exceeded | cancelled
    failure: Failure | None = None
    stopped: bool = False  # ended by a stop node: workflow outputs are still evaluated


class Scheduler:
    def __init__(self, program: Program, *, iteration_cap: int = ITERATION_CAP) -> None:
        self.program = program
        self.iteration_cap = iteration_cap
        self.iterations = 0
        self.scopes: dict[ScopeKey, Scope] = {}
        self.loops: dict[Instance, LoopRun] = {}
        self.ended: RunEnd | None = None
        self._ready: list[Instance] = []
        self._collects: list[Collect] = []
        self._cancels: list[Instance] = []
        self._settled: list[Instance] = []
        self._topo_of_key = {s.key: s.topo for s in program.steps.values()}
        self._members: dict[uuid.UUID | None, tuple[uuid.UUID, ...]] = {
            region: r.members for region, r in program.regions.items()
        }

    # --- the workflow's side ---------------------------------------------------------------------------------------

    def start(self) -> None:
        self._open_scope((), None)

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

    def take_settled(self) -> list[Instance]:
        """Steps that succeeded or failed since the last call, loops completed by their last iteration included."""
        out, self._settled = self._settled, []
        return out

    def take_cancels(self) -> list[Instance]:
        """Running steps whose scope ended (a failure, a stop, the deadline): their work must be cancelled, and
        nothing they report later counts."""
        out, self._cancels = sorted(self._cancels, key=self.order), []
        return out

    def succeed(self, inst: Instance, output: Any, ports: tuple[str, ...] | None = None) -> None:
        """The step succeeded. `ports`: the normal ports whose edges are live (if/switch pick one); all by default."""
        scope, step = self._running(inst)
        if scope is None:
            return
        scope.nodes[step.id] = NodeState.DONE
        scope.results[step.key] = {"output": output}
        self._settled.append(inst)
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
        self._settled.append(inst)
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

    def open_loop(self, inst: Instance, items: list[Any], *, concurrency: int, stop_on_error: bool) -> None:
        """The loop node's `items` are known: open its first iterations. An empty list completes it at once."""
        scope, step = self._running(inst)
        if scope is None:
            return
        loop = LoopRun(inst, list(items), concurrency, stop_on_error, collected=[None] * len(items))
        self.loops[inst] = loop
        self._advance(loop)

    def debit(self, count: int) -> bool:
        """Take `count` iterations (filter items) from the run's budget; False, and nothing taken, past the cap."""
        if self.iterations + count > self.iteration_cap:
            return False
        self.iterations += count
        return True

    def collected(self, loop_inst: Instance, index: int, value: Any) -> None:
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open:
            return
        loop.open.remove(index)
        loop.collecting.discard(index)
        loop.collected[index] = value
        self._advance(loop)

    def collect_failed(self, loop_inst: Instance, index: int, failure: Failure) -> None:
        """`collect` couldn't be evaluated: the iteration failed after all."""
        loop = self.loops.get(loop_inst)
        if loop is None or index not in loop.open:
            return
        self._iteration_failed(loop, index, failure)

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
        self._settled.append(inst)
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
        if self.ended is not None or scope is None or scope.failure is not None:
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
            del self.loops[inst]
        if scope.key == ():
            self.end(RunEnd("failed", failure))
        elif report:
            self._iteration_settled(scope)

    def _after_settle(self, scope: Scope) -> None:
        if scope.key != () and scope.settled:
            self._iteration_settled(scope)
        elif scope.key == () and scope.settled and self.ended is None:
            self.ended = RunEnd("succeeded")

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
        if loop.stop_on_error:
            self._abort(loop, failure)
            return
        loop.failures.append({"index": index, "code": failure.code, "message": failure.message})
        self._advance(loop)

    def _abort(self, loop: LoopRun, failure: Failure) -> None:
        """The loop ends early (an iteration failed under `stop`, or the run reached its iteration cap): its open
        iterations end first, running steps cancelled and queued ones dropped, and then the loop step fails, so its
        own `on_error` applies. Nothing the loop opened outlives it."""
        del self.loops[loop.instance]
        key = self.program.steps[loop.instance.step].key
        for other in loop.open:
            self._fail_scope(self.scopes[(*loop.instance.scope, (key, other))], failure, report=False)
        parent = self.scopes[loop.instance.scope]
        if parent.failure is None and self.ended is None:
            self.fail(loop.instance, failure)

    def _advance(self, loop: LoopRun) -> None:
        """Open iterations up to the concurrency, or complete the loop when every item is done."""
        step = self.program.steps[loop.instance.step]
        while loop.next < len(loop.items) and len(loop.open) < loop.concurrency:
            if not self.debit(1):
                self._abort(loop, Failure(ITERATION_CAP_EXCEEDED, "This run reached its limit of loop iterations."))
                return
            index = loop.next
            loop.next += 1
            loop.open.append(index)
            self._open_scope((*loop.instance.scope, (step.key, index)), step.id, item=loop.items[index], index=index)
            if loop.instance not in self.loops:  # the iteration failed at once and stopped the loop
                return
        if not loop.open and loop.next >= len(loop.items):
            del self.loops[loop.instance]
            output = {"items": loop.collected, "failures": loop.failures, "count": len(loop.items)}
            scope = self.scopes.get(loop.instance.scope)
            if scope is not None and scope.failure is None and self.ended is None:
                self.succeed(loop.instance, output, (DONE,))


__all__ = [
    "Collect",
    "EdgeState",
    "Failure",
    "Instance",
    "ITERATION_CAP",
    "ITERATION_CAP_EXCEEDED",
    "LoopRun",
    "NodeState",
    "RunEnd",
    "Scheduler",
    "Scope",
    "ScopeKey",
    "iteration_key",
]
```

Add the determinism contract to `backend/pyproject.toml`:

```diff
diff --git a/backend/pyproject.toml b/backend/pyproject.toml
--- a/backend/pyproject.toml
+++ b/backend/pyproject.toml
@@ -159,3 +159,9 @@
   "dewpoint.core", "dewpoint.plugins", "dewpoint.sdk", "dewpoint.engine.graph", "dewpoint.engine.registry",
   "sqlalchemy", "asyncpg", "fastapi", "pydantic", "jsonschema", "httpx", "temporalio", "cryptography",
 ]
+
+[[tool.importlinter.contracts]]
+name = "engine.runtime is deterministic: no clock, randomness, I/O or threads (spec §6)"
+type = "forbidden"
+source_modules = ["dewpoint.engine.runtime"]
+forbidden_modules = ["random", "secrets", "time", "socket", "subprocess", "threading", "os", "structlog"]
```

- [ ] **Step 4: Run the tests, and check that the contract bites**

Run: `cd backend && uv run pytest -q tests/engine/runtime`
Expected: 21 passed (3 program, 17 scheduler, 1 property test over 300 random graphs).

Then plant `import random` at the top of `scheduler.py`, run `uv run lint-imports`, and remove it again.
Expected: `engine.runtime is deterministic … BROKEN` naming `dewpoint.engine.runtime.scheduler -> random`, then
`Contracts: 10 kept, 0 broken` after the removal.

- [ ] **Step 5: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine \
  && git add pyproject.toml src/dewpoint/engine/runtime tests/engine/runtime \
  && git commit -m "feat(engine): the compiled program and the scheduler (scopes, dead paths, loops)" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: every engine test passes, `tests/engine/cel` included.

---

### Task 2: Values, control-node decisions and previews

The rest of the pure core:
- **`resolve`** builds what a step sees (the presence contract, `loops`, `item`/`index`) and turns each envelope in a
  config into a value: references and templates here, CEL through 2a-2's binding and routing.
- **`nodes`** says what each control node decides once its config is resolved.
- **`projection`** makes the previews `run_steps` stores (decision 21). It redacts sensitive fields through `$ref`s
  and unions, masks the sensitive values the run has learned, and truncates.

Everything here is deterministic and runs inside the workflow.

**Files:**
- Create: `backend/src/dewpoint/engine/runtime/resolve.py`, `nodes.py`, `projection.py`
- Create: `backend/tests/engine/runtime/test_resolve.py`, `test_nodes.py`, `test_projection.py`

**Interfaces:**
- Consumes:
  - from Task 1: `Scheduler` (`scopes`, `program.chain`, `program.regions`), `Failure`, `RunEnd`, `ScopeKey`;
  - from 2a-2: `ScopeView`, `bind`, `BindingError` and `measure` (`engine.cel.bind`), `route` (`engine.cel.route`),
    `EvaluateRequest` (`engine.cel.ipc`), `ExpressionRecord`, and from `engine.cel.evaluate` the functions
    `compiled` and `run`, the class `Outcome`, and the codes `EVALUATION_ERROR` and `TYPE_MISMATCH`;
  - from `main`: `canonical_json`, the `control` refs (`engine.registry.control`), and `RefValue`,
    `TemplateValue`, `RefPath`, `ENVELOPE`, `Pointer` and `pointer_str` (`engine.graph.values`); in tests, `Node`,
    `node_manifest` and `sensitive` from the SDK.
- Produces:
  - `resolve.py`:
    - `MISSING`, and `ValueFailure(code, message)` with `.failure`;
    - `view(scheduler, key, *, trigger, variables, run, item=None) -> ScopeView`;
    - `read(view, path)`, `ref(view, RefValue)` and `template(view, TemplateValue) -> str`;
    - `CelTask(record, bindings, local)` with `.request(profile) -> dict` and `.run_local() -> list[Outcome]`;
    - `cel_task(record, views, *, local_profile, version_profile) -> CelTask`, `outcome_value(outcome)`, and
      `assemble(config, values, base=())`.
  - `nodes.py`:
    - `INLINE_ITEMS = 100`, `ITEM_CAP_EXCEEDED`, `NOT_SUPPORTED`, `WORKFLOW_FAILED`;
    - `LoopStart(items, concurrency, stop_on_error)`;
    - `Decision(output, ports, variables, end, wait_s, wait_until, loop, filter_items, failure)`, where
      `wait_until` is an aware UTC `datetime`;
    - `decide(ref, config) -> Decision`.
  - `projection.py`:
    - `PREVIEW_BYTES = 8192`, `REDACTED`, `TRUNCATED`, `MIN_SECRET = 4`, and `Secrets = tuple[str, ...]`;
    - `preview(value, schema=None, secrets=())`;
    - `sensitive_values(value, schema) -> list[str]`: the strings at the schema's sensitive positions;
    - `remember(secrets, values) -> Secrets`: sorted longest first, and the same tuple when nothing is new;
    - `mask(value, secrets)`: in strings and keys, at any depth;
    - `location(loc, schema) -> str`: a validation error's location as far as the schema declares it, `*` elsewhere.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/engine/runtime/test_resolve.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Values at run time (spec §4.3, §5.6): what a step sees, and how refs, templates and CEL become values."""

from typing import Any

import pytest

from dewpoint.engine.cel.bind import ScopeView
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.values import ENVELOPE, Value, iter_values
from dewpoint.engine.runtime import resolve
from dewpoint.engine.runtime.resolve import ValueFailure
from dewpoint.engine.runtime.scheduler import Scheduler
from tests.engine.runtime.support import program
from tests.support.graphs import G, cel, ref, template

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "names": {"type": "array", "items": {"type": "string"}}},
    "required": ["x", "names"],
}


def value(envelope: dict[str, Any]) -> Value:
    [(_, parsed)] = list(iter_values({"v": envelope}))
    assert not isinstance(parsed, Exception)
    return parsed


def scope_view(**roots: Any) -> ScopeView:
    base: dict[str, Any] = {"trigger": {}, "steps": {}, "vars": {}, "loops": {}, "run": {}, "item": None, "index": None}
    return ScopeView(**{**base, **roots})


def test_a_step_sees_its_region_and_the_regions_around_it() -> None:
    g = G().node("a", "testkit.echo@1", {"value": 1}).node("l", "flow.loop@1", {"items": ["p", "q"]})
    g.node("x", "testkit.echo@1").edge("a", "l").edge("l", "x", "body")
    s = Scheduler(program(g))
    s.start()
    [a] = s.take_ready()
    s.succeed(a, {"value": 1})
    [loop] = s.take_ready()
    s.open_loop(loop, ["p", "q"], concurrency=1, stop_on_error=True)
    [x] = s.take_ready()
    run = {"id": "r", "started_at": "2026-09-27T00:00:00+00:00"}

    inside = resolve.view(s, x.scope, trigger={"t": 1}, variables={"n": 0}, run=run)
    assert inside.steps == {"x": {}, "a": {"output": {"value": 1}}, "l": {}}  # `{}`: not settled yet
    assert (inside.loops, inside.item, inside.index) == ({"l": {"item": "p", "index": 0}}, "p", 0)
    outside = resolve.view(s, (), trigger={"t": 1}, variables={"n": 0}, run=run)
    assert outside.steps == {"a": {"output": {"value": 1}}, "l": {}} and outside.index is None
    as_filter = resolve.view(s, (), trigger={}, variables={}, run=run, item=("ap-1", 4))
    assert (as_filter.item, as_filter.index) == ("ap-1", 4)  # a filter's predicate sees its own item


def test_a_default_replaces_a_missing_or_null_value() -> None:
    v = scope_view(
        trigger={"a": None, "b": 0},
        steps={"s": {}, "c": {"output": None, "error": {"code": "boom", "message": "", "attempt": 1}}},
    )
    assert resolve.ref(v, value(ref("trigger.a", default=5))) == 5
    assert resolve.ref(v, value(ref("trigger.nope", default=5))) == 5
    assert resolve.ref(v, value(ref("trigger.b", default=5))) == 0  # a falsy value is still a value
    assert resolve.ref(v, value(ref("steps.s.output.v", default="later"))) == "later"  # not settled yet
    assert resolve.ref(v, value(ref("steps.c.error.code"))) == "boom"
    assert resolve.ref(v, value(ref("trigger.a"))) is None  # null without a default stays null
    with pytest.raises(ValueFailure) as missing:
        resolve.ref(v, value(ref("trigger.nope")))
    assert missing.value.failure.code == "evaluation_error"


def test_a_template_joins_text() -> None:
    v = scope_view(trigger={"s": "ap", "n": 3, "f": 1.5, "b": True, "z": None, "o": {"k": 1}})
    parts = (
        "x=",
        {"ref": "trigger.s"},
        "/",
        {"ref": "trigger.n"},
        "/",
        {"ref": "trigger.f"},
        "/",
        {"ref": "trigger.b"},
    )
    assert resolve.template(v, value(template(*parts))) == "x=ap/3/1.5/true"
    assert resolve.template(v, value(template("[", {"ref": "trigger.z"}, "]"))) == "[]"  # null, no default: nothing
    assert resolve.template(v, value(template({"ref": "trigger.nope", "default": "-"}))) == "-"
    with pytest.raises(ValueFailure) as missing:
        resolve.template(v, value(template({"ref": "trigger.nope"})))
    with pytest.raises(ValueFailure) as shaped:
        resolve.template(v, value(template({"ref": "trigger.o"})))
    assert (missing.value.failure.code, shaped.value.failure.code) == ("evaluation_error", "type_mismatch")


def test_assemble_puts_each_value_at_its_pointer() -> None:
    envelope = {ENVELOPE: {"kind": "ref", "path": "trigger.x"}}
    config = {"a": 1, "b": [envelope, {"c": envelope}], "d": envelope}
    assert resolve.assemble(config, {"/b/0": 5, "/b/1/c": "x"}) == {"a": 1, "b": [5, {"c": "x"}], "d": None}


def test_cel_runs_inline_only_when_this_build_runs_the_profile() -> None:
    g = G()
    g.settings = {"input_schema": SCHEMA}
    fields = {"y": cel("trigger.x * 2"), "z": cel("10 / trigger.x"), "n": cel("size(trigger.names)")}
    p = program(g.node("t", "flow.transform@1", {"fields": fields}))
    step = p.by_key["t"]
    double, divide, count = (p.record(step, f"/fields/{f}") for f in ("y", "z", "n"))
    views = [scope_view(trigger={"x": 3}), scope_view(trigger={"x": 0})]

    remote = resolve.cel_task(double, views, local_profile=None, version_profile=CURRENT_CEL_PROFILE)
    assert not remote.local
    assert remote.request(CURRENT_CEL_PROFILE)["bindings"] == [{"trigger": {"x": 3}}, {"trigger": {"x": 0}}]

    local = resolve.cel_task(divide, views, local_profile=CURRENT_CEL_PROFILE, version_profile=CURRENT_CEL_PROFILE)
    ok, failed = local.run_local()
    assert local.local and resolve.outcome_value(ok) == 3
    with pytest.raises(ValueFailure) as e:
        resolve.outcome_value(failed)
    assert e.value.failure.code == "evaluation_error"

    with pytest.raises(ValueFailure) as bad:  # a typed list path (spec §5.3) is checked as it's bound
        resolve.cel_task(
            count, [scope_view(trigger={"x": 1, "names": "ap-1"})], local_profile=None, version_profile="p"
        )
    assert bad.value.failure.code == "type_mismatch"
```

Create `backend/tests/engine/runtime/test_nodes.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What each control node decides once its config is resolved (spec §6)."""

from datetime import UTC, datetime
from typing import Any

import pytest

from dewpoint.engine.runtime.nodes import Decision, LoopStart, decide
from dewpoint.engine.runtime.scheduler import Failure, RunEnd


@pytest.mark.parametrize(
    ("ref", "config", "decision"),
    [
        ("flow.if@1", {"condition": True}, Decision(output={}, ports=("true",))),
        ("flow.if@1", {"condition": False}, Decision(output={}, ports=("false",))),
        (
            "flow.switch@1",
            {"cases": [{"port": "a", "when": False}, {"port": "b", "when": True}, {"port": "c", "when": True}]},
            Decision(output={}, ports=("b",)),  # the first match wins
        ),
        ("flow.switch@1", {"cases": [{"port": "a", "when": False}]}, Decision(output={}, ports=("default",))),
        ("flow.set_variables@1", {"assignments": {"n": 2}}, Decision(output={}, variables={"n": 2})),
        ("flow.transform@1", {"fields": {"y": 1}}, Decision(output={"y": 1})),
        ("flow.stop@1", {}, Decision(output={}, end=RunEnd("succeeded", stopped=True))),
        (
            "flow.fail@1",
            {"message": "no"},
            Decision(output={}, end=RunEnd("failed", Failure("workflow_failed", "no"))),
        ),
        ("flow.delay@1", {"duration_s": 60}, Decision(output={}, wait_s=60.0)),
        (
            "flow.wait_until@1",
            {"until": "2027-01-01T01:00:00+01:00"},
            Decision(output={}, wait_until=datetime(2027, 1, 1, tzinfo=UTC)),
        ),
        (
            "flow.wait_until@1",
            {"until": "2027-01-01T00:00:00Z"},
            Decision(output={}, wait_until=datetime(2027, 1, 1, tzinfo=UTC)),
        ),
        (
            "flow.loop@1",
            {"items": [1, 2], "concurrency": 2, "on_item_error": "continue"},
            Decision(loop=LoopStart([1, 2], 2, stop_on_error=False)),
        ),
        ("flow.loop@1", {"items": []}, Decision(loop=LoopStart([], 1, stop_on_error=True))),
        ("flow.filter@1", {"items": ["a"]}, Decision(filter_items=["a"])),
    ],
)
def test_a_control_node_decides(ref: str, config: dict[str, Any], decision: Decision) -> None:
    assert decide(ref, config) == decision


@pytest.mark.parametrize(
    ("ref", "config", "code"),
    [
        ("flow.if@1", {"condition": "yes"}, "type_mismatch"),  # open data publish couldn't type
        ("flow.switch@1", {"cases": [{"port": "a", "when": 1}]}, "type_mismatch"),
        ("flow.delay@1", {"duration_s": True}, "type_mismatch"),
        ("flow.delay@1", {"duration_s": -1}, "type_mismatch"),
        ("flow.wait_until@1", {"until": 5}, "type_mismatch"),
        ("flow.wait_until@1", {"until": "tomorrow"}, "type_mismatch"),  # a ref to open data
        ("flow.wait_until@1", {"until": "2027-01-01T09:00:00"}, "type_mismatch"),  # no zone: whose 9 o'clock?
        ("flow.loop@1", {"items": {"a": 1}}, "type_mismatch"),
        ("flow.filter@1", {"items": "abc"}, "type_mismatch"),
        ("flow.loop@1", {"items": [1, 2, 3], "item_cap": 2}, "item_cap_exceeded"),
        ("flow.loop@1", {"items": list(range(101))}, "not_supported"),  # batches arrive with 2a-3b
        ("flow.run_workflow@1", {"workflow_id": "w"}, "not_supported"),  # sub-flows arrive with 2a-3b
    ],
)
def test_a_control_node_refuses(ref: str, config: dict[str, Any], code: str) -> None:
    failure = decide(ref, config).failure
    assert failure is not None and failure.code == code


def test_a_loop_of_exactly_a_hundred_items_runs_inline() -> None:
    assert decide("flow.loop@1", {"items": list(range(100))}).loop is not None


def test_only_control_nodes_are_decided() -> None:
    with pytest.raises(ValueError, match="isn't a control node"):
        decide("testkit.echo@1", {})
```

Create `backend/tests/engine/runtime/test_projection.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`run_steps` previews (spec §8): `x-sensitive` fields are redacted wherever the schema puts them, values learned to be
sensitive are masked wherever they reappear, and oversize previews are truncated."""

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from dewpoint.engine.runtime.projection import (
    MIN_SECRET,
    PREVIEW_BYTES,
    REDACTED,
    TRUNCATED,
    location,
    mask,
    preview,
    remember,
    sensitive_values,
)
from dewpoint.sdk import Node, node_manifest, sensitive

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "token": {"type": "string", "x-sensitive": True},
        "devices": {"type": "array", "items": {"type": "object", "properties": {"psk": {"x-sensitive": True}}}},
        "headers": {"type": "object", "additionalProperties": {"type": "string", "x-sensitive": True}},
        "name": {"type": "string"},
    },
}


class Cred(BaseModel):
    user: str
    secret: str = sensitive()


class NestedOutput(BaseModel):
    cred: Cred
    maybe: Cred | None
    many: list[Cred]


class Nested(Node):
    type = "testkit.nested"
    version = 1
    title = "Nested"
    Output = NestedOutput

    async def run(self, ctx: Any, config: Any) -> NestedOutput:
        raise NotImplementedError


NESTED = node_manifest(Nested)["output_schema"]  # $defs, $ref and anyOf, as pydantic writes nested models


def test_sensitive_fields_are_redacted_wherever_the_schema_marks_them() -> None:
    value = {
        "token": "t0p",
        "devices": [{"psk": "a", "id": 1}, {"id": 2}],
        "headers": {"Authorization": "Bearer x"},
        "name": "ap-1",
        "extra": {"token": "not declared"},  # only the schema decides
    }
    assert preview(value, SCHEMA) == {
        "token": REDACTED,
        "devices": [{"psk": REDACTED, "id": 1}, {"id": 2}],
        "headers": {"Authorization": REDACTED},
        "name": "ap-1",
        "extra": {"token": "not declared"},
    }


def test_redaction_follows_references_and_unions() -> None:
    """Review finding: a nested model's sensitive field sits behind `$ref`, and an optional one behind `anyOf`."""
    value = {
        "cred": {"user": "u", "secret": "s1"},
        "maybe": {"user": "v", "secret": "s2"},
        "many": [{"user": "w", "secret": "s3"}],
    }
    assert preview(value, NESTED) == {
        "cred": {"user": "u", "secret": REDACTED},
        "maybe": {"user": "v", "secret": REDACTED},
        "many": [{"user": "w", "secret": REDACTED}],
    }
    assert preview({"cred": None, "maybe": None, "many": []}, NESTED) == {"cred": None, "maybe": None, "many": []}


Secret = Annotated[str, sensitive()]


class Overlap(BaseModel):
    """A declared field that a sensitive pattern also covers: JSON Schema applies both to it."""

    model_config = ConfigDict(json_schema_extra={"patternProperties": {"^x-": {"type": "string", "x-sensitive": True}}})
    token: str = Field(alias="x-token")
    name: str


class Shapes(BaseModel):
    patterned: dict[Annotated[str, StringConstraints(pattern=r"^x-")], Secret]  # patternProperties
    pair: tuple[str, Secret]  # prefixItems
    keyed: dict[Secret, int]  # propertyNames: the keys are the secret
    overlap: Overlap  # properties and patternProperties at once


class ShapesNode(Node):
    type = "testkit.shapes"
    version = 1
    title = "Shapes"
    Output = Shapes

    async def run(self, ctx: Any, config: Any) -> Shapes:
        raise NotImplementedError


def test_redaction_covers_patterned_maps_tuples_and_sensitive_keys() -> None:
    """Checkpoint-1 finding: a patterned-key map's values sit under `patternProperties`, which redaction didn't read,
    so the credential showed and was never learned. Tuple positions (`prefixItems`) and sensitive keys
    (`propertyNames`) had the same gap."""
    schema = node_manifest(ShapesNode)["output_schema"]
    value = {
        "patterned": {"x-api": "k3y-one"},
        "pair": ["public", "k3y-two"],
        "keyed": {"k3y-three": 1},
        "overlap": {"x-token": "k3y-four", "name": "n"},  # checkpoint-1 re-review: a declared key a pattern covers
    }
    assert preview(value, schema) == {
        "patterned": {"x-api": REDACTED},
        "pair": ["public", REDACTED],
        "keyed": REDACTED,
        "overlap": {"x-token": REDACTED, "name": REDACTED},  # every pattern applies, matched or not: over-redaction
    }
    assert sensitive_values(value, schema) == ["k3y-one", "k3y-two", "k3y-three", "k3y-four", "n"]


def test_a_recursive_schema_ends() -> None:
    tree = {
        "$defs": {"T": {"properties": {"k": {"$ref": "#/$defs/T"}, "s": {"x-sensitive": True}}}},
        "$ref": "#/$defs/T",
    }
    assert preview({"k": {"k": {"s": "x"}}, "s": "y"}, tree) == {"k": {"k": {"s": REDACTED}}, "s": REDACTED}


def test_sensitive_values_are_learned_and_masked_wherever_they_reappear() -> None:
    """Review finding: a control step copies a secret into a field no schema marks (a transform, a template, a
    message). The run remembers every sensitive value it has seen and masks it everywhere it projects."""
    learned = sensitive_values({"cred": {"user": "u", "secret": "hunter22"}, "maybe": None, "many": []}, NESTED)
    assert learned == ["hunter22"]
    secrets = remember((), learned)
    assert preview({"copy": "hunter22", "header": "Bearer hunter22!", "n": 1}, None, secrets) == {
        "copy": REDACTED,
        "header": f"Bearer {REDACTED}!",
        "n": 1,
    }
    assert mask("login failed for hunter22", secrets) == f"login failed for {REDACTED}"
    assert preview({"hunter22": 1}, None, secrets) == {REDACTED: 1}  # keys too


def test_masking_is_deterministic_and_skips_values_too_short_to_mean_anything() -> None:
    secrets = remember(remember((), ["abcd"]), ["abcdef", "xy"])  # "xy" is below MIN_SECRET
    assert MIN_SECRET == 4 and secrets == ("abcdef", "abcd")  # longest first: a longer secret is masked whole
    assert mask("abcdef abcd", secrets) == f"{REDACTED} {REDACTED}"
    assert remember(secrets, ["abcd"]) is secrets  # nothing new, nothing rebuilt


def test_a_preview_over_8_kib_is_truncated() -> None:
    assert preview({"s": "x" * (PREVIEW_BYTES - 8)}) == {"s": "x" * (PREVIEW_BYTES - 8)}  # exactly 8 KiB
    assert preview({"s": "x" * (PREVIEW_BYTES - 7)}) == TRUNCATED
    assert preview({"token": "x" * PREVIEW_BYTES}, SCHEMA) == {"token": REDACTED}  # measured after redaction


def test_a_value_canonical_json_refuses_is_truncated() -> None:
    assert preview({"f": float("nan")}) == TRUNCATED


class Item(BaseModel):
    name: str


class Located(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headers: dict[int, int]
    tags: dict[str, int]
    items: list[Item]
    pair: tuple[int, str]
    maybe: Item | None
    name: str


def test_a_location_keeps_only_what_the_schema_declares_at_that_place() -> None:
    """Review findings: a location part can come from the data. A numeric key of `dict[int, …]` looks like a list
    index, and a text key can match a field declared elsewhere. Walking the schema tells them apart."""
    data = {
        "headers": {"428319": "x"},  # a numeric key
        "tags": {"name": "x"},  # a key that matches a field declared elsewhere
        "items": [{"name": 1}],
        "pair": [1, 2],
        "maybe": {"name": 3},
        "name": 4,
        "hunter22": 1,  # an unknown key
    }
    with pytest.raises(ValidationError) as e:
        Located.model_validate(data)
    schema = Located.model_json_schema()
    assert [location(err["loc"], schema) for err in e.value.errors()] == [
        "headers.*",
        "tags.*",
        "items.0.name",
        "pair.1",
        "maybe.name",
        "name",
        "*",
    ]
    assert location((), schema) == "(root)"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/runtime/test_resolve.py tests/engine/runtime/test_nodes.py tests/engine/runtime/test_projection.py`
Expected: 3 collection errors: `ImportError: cannot import name 'resolve' from 'dewpoint.engine.runtime'`, and
`ModuleNotFoundError` for `dewpoint.engine.runtime.nodes` and `dewpoint.engine.runtime.projection`.

- [ ] **Step 3: Implement**

Create `backend/src/dewpoint/engine/runtime/resolve.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Values at run time (spec §4.3, §5.6). A step's config holds literals and envelopes; each envelope becomes a value
in the step's scope:
- a ref reads the scope; its default replaces a missing *or* null value;
- a template joins its text and the text of its refs;
- CEL runs inline when the version's profile runs in this build and the inputs are within the caps, and otherwise in
  the `cel.evaluate` activity.

A value that can't be computed fails the step (`evaluation_error`, or the CEL outcome's own code), and the step's
error policy applies."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from dewpoint.engine.cel import evaluate
from dewpoint.engine.cel.bind import BindingError, ScopeView, bind, measure
from dewpoint.engine.cel.ipc import EvaluateRequest
from dewpoint.engine.cel.record import ExpressionRecord
from dewpoint.engine.cel.route import route
from dewpoint.engine.graph.values import ENVELOPE, Pointer, RefPath, RefValue, TemplateValue, pointer_str
from dewpoint.engine.runtime.scheduler import Failure, Scheduler, ScopeKey

MISSING: Any = object()


class ValueFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.failure = Failure(code, message)


def view(
    scheduler: Scheduler,
    key: ScopeKey,
    *,
    trigger: Mapping[str, Any],
    variables: Mapping[str, Any],
    run: Mapping[str, str],
    item: tuple[Any, int] | None = None,
) -> ScopeView:
    """What a step in scope `key` sees: every step of its region and the regions around it (`{}` before a step
    settles), its enclosing loops, the innermost item (or `item`, a filter's), the run."""
    program = scheduler.program
    scope = scheduler.scopes[key]
    steps: dict[str, Mapping[str, Any]] = {}
    loops: dict[str, dict[str, Any]] = {}
    at = key
    for region in program.chain(scope.region):
        current = scheduler.scopes[at]
        for member in program.regions[region].members:
            name = program.steps[member].key
            steps[name] = current.results.get(name, {})
        if at:
            loops[at[-1][0]] = {"item": current.item, "index": current.index}
            at = at[:-1]
    if item is not None:
        value, index = item
    elif scope.index is not None:
        value, index = scope.item, scope.index
    else:
        value, index = None, None
    return ScopeView(trigger=trigger, steps=steps, vars=variables, loops=loops, run=run, item=value, index=index)


def _base(v: ScopeView, path: RefPath) -> Any:
    if path.root == "trigger":
        return v.trigger
    if path.root == "steps":
        entry = v.steps.get(str(path.name), MISSING)
        return entry.get(str(path.section), MISSING) if isinstance(entry, Mapping) else MISSING
    if path.root == "vars":
        return v.vars.get(str(path.name), MISSING)
    if path.root in ("item", "index"):
        return MISSING if v.index is None else (v.item if path.root == "item" else v.index)
    if path.root == "loops":
        loop = v.loops.get(str(path.name))
        return loop.get(str(path.section), MISSING) if loop is not None else MISSING
    if path.root == "run":
        return v.run.get(str(path.section), MISSING)
    return MISSING


def read(v: ScopeView, path: RefPath) -> Any:
    """The value at `path`, or MISSING."""
    value = _base(v, path)
    for seg in path.rest:
        if isinstance(seg, int):
            value = value[seg] if isinstance(value, list) and 0 <= seg < len(value) else MISSING
        else:
            value = value.get(seg, MISSING) if isinstance(value, Mapping) else MISSING
        if value is MISSING:
            break
    return value


def ref(v: ScopeView, value: RefValue) -> Any:
    found = read(v, value.path)
    if (found is MISSING or found is None) and value.has_default:
        return value.default
    if found is MISSING:
        raise ValueFailure(evaluate.EVALUATION_ERROR, f"`{value.path.text}` has no value here.")
    return found


def _text(found: Any, path: RefPath) -> str:
    if isinstance(found, str):
        return found
    if isinstance(found, bool):
        return "true" if found else "false"
    if isinstance(found, int | float):
        return json.dumps(found)
    raise ValueFailure(evaluate.TYPE_MISMATCH, f"`{path.text}` isn't text, a number or a boolean.")


def template(v: ScopeView, value: TemplateValue) -> str:
    out: list[str] = []
    for part in value.parts:
        if isinstance(part, str):
            out.append(part)
            continue
        found = read(v, part.path)
        if found is MISSING or found is None:
            if part.default is not None:
                out.append(part.default)
                continue
            if found is MISSING:
                raise ValueFailure(evaluate.EVALUATION_ERROR, f"`{part.path.text}` has no value here.")
            continue  # null, no default: nothing
        out.append(_text(found, part.path))
    return "".join(out)


@dataclass(frozen=True)
class CelTask:
    """One expression, evaluated once per view: inline, or in one `cel.evaluate` request (1 to 1,000 views)."""

    record: ExpressionRecord
    bindings: tuple[Mapping[str, Any], ...]
    local: bool

    def request(self, profile: str) -> dict[str, Any]:
        return EvaluateRequest(profile, self.record.expr, dict(self.record.declarations), self.bindings).to_json()

    def run_local(self) -> list[evaluate.Outcome]:
        program = evaluate.compiled(self.record.expr, self.record.declarations)
        return [evaluate.run(program, b) for b in self.bindings]


def cel_task(
    record: ExpressionRecord, views: Sequence[ScopeView], *, local_profile: str | None, version_profile: str
) -> CelTask:
    """Bind every view; inline only when every binding set is within the caps and the profile runs here."""
    bindings: list[Mapping[str, Any]] = []
    local = True
    for v in views:
        try:
            b = bind(record, v)
        except BindingError as e:
            raise ValueFailure(evaluate.TYPE_MISMATCH, str(e)) from None
        bindings.append(b)
        mode = route(record, measure(b), local_profile=local_profile, version_profile=version_profile)
        local = local and mode == "local"
    return CelTask(record, tuple(bindings), local)


def outcome_value(outcome: evaluate.Outcome) -> Any:
    if not outcome.ok:
        raise ValueFailure(str(outcome.error), outcome.message)
    return outcome.value


def assemble(config: Any, values: Mapping[str, Any], base: Pointer = ()) -> Any:
    """`config` with every envelope replaced by its value (by JSON pointer); envelopes without one become None."""
    if isinstance(config, Mapping):
        if ENVELOPE in config:
            return values.get(pointer_str(base))
        return {k: assemble(v, values, (*base, k)) for k, v in config.items()}
    if isinstance(config, list):
        return [assemble(v, values, (*base, i)) for i, v in enumerate(config)]
    return config


__all__ = [
    "MISSING",
    "CelTask",
    "ValueFailure",
    "assemble",
    "cel_task",
    "outcome_value",
    "read",
    "ref",
    "template",
    "view",
]
```

Create `backend/src/dewpoint/engine/runtime/nodes.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Control nodes (spec §6): what each one decides once its config is resolved. Publish checked literal configs and
typed every ref and CEL value; the checks here catch open data whose shape publish couldn't know."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from dewpoint.engine.cel.evaluate import TYPE_MISMATCH
from dewpoint.engine.registry import control
from dewpoint.engine.runtime.scheduler import Failure, RunEnd

INLINE_ITEMS = 100  # larger loops run as batches of child workflows (2a-3b)
ITEM_CAP_EXCEEDED = "item_cap_exceeded"
NOT_SUPPORTED = "not_supported"  # until 2a-3b: sub-flows, loops over more than INLINE_ITEMS items
WORKFLOW_FAILED = "workflow_failed"  # a fail node ended the run


@dataclass(frozen=True)
class LoopStart:
    items: list[Any]
    concurrency: int
    stop_on_error: bool


@dataclass(frozen=True)
class Decision:
    output: Any = None
    ports: tuple[str, ...] | None = None  # None: every normal port
    variables: Mapping[str, Any] | None = None
    end: RunEnd | None = None
    wait_s: float | None = None
    wait_until: datetime | None = None  # UTC
    loop: LoopStart | None = None
    filter_items: list[Any] | None = None  # a filter: evaluate its predicate per item
    failure: Failure | None = None


def _instant(value: Any) -> datetime | None:
    """An RFC 3339 date-time, as UTC; None for anything else, a time without a zone included."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else None


def _mismatch(message: str) -> Decision:
    return Decision(failure=Failure(TYPE_MISMATCH, message))


def decide(ref: str, config: Mapping[str, Any]) -> Decision:
    if ref == control.IF:
        condition = config.get("condition")
        if not isinstance(condition, bool):
            return _mismatch("`condition` must be true or false.")
        return Decision(output={}, ports=("true" if condition else "false",))
    if ref == control.SWITCH:
        for case in config.get("cases", []):
            if not isinstance(case.get("when"), bool):
                return _mismatch(f"`when` for `{case.get('port')}` must be true or false.")
            if case["when"]:
                return Decision(output={}, ports=(str(case["port"]),))
        return Decision(output={}, ports=("default",))
    if ref == control.SET_VARIABLES:
        return Decision(output={}, variables=dict(config.get("assignments", {})))
    if ref == control.TRANSFORM:
        return Decision(output=dict(config.get("fields", {})))
    if ref == control.STOP:
        return Decision(output={}, end=RunEnd("succeeded", stopped=True))
    if ref == control.FAIL:
        return Decision(output={}, end=RunEnd("failed", Failure(WORKFLOW_FAILED, str(config.get("message", "")))))
    if ref == control.DELAY:
        seconds = config.get("duration_s")
        if isinstance(seconds, bool) or not isinstance(seconds, int | float) or seconds < 0:
            return _mismatch("`duration_s` must be a number of seconds.")
        return Decision(output={}, wait_s=float(seconds))
    if ref == control.WAIT_UNTIL:
        until = _instant(config.get("until"))
        if until is None:
            return _mismatch("`until` must be a date and time with a time zone, like 2027-01-01T09:00:00+01:00.")
        return Decision(output={}, wait_until=until)
    if ref == control.LOOP:
        items = config.get("items")
        if not isinstance(items, list):
            return _mismatch("`items` must be a list.")
        cap = int(config.get("item_cap", 10_000))
        if len(items) > cap:
            return Decision(failure=Failure(ITEM_CAP_EXCEEDED, f"{len(items)} items exceed this loop's cap of {cap}."))
        if len(items) > INLINE_ITEMS:
            return Decision(
                failure=Failure(
                    NOT_SUPPORTED, f"Loops over more than {INLINE_ITEMS} items run in batches, which this build lacks."
                )
            )
        start = LoopStart(items, int(config.get("concurrency", 1)), config.get("on_item_error", "stop") == "stop")
        return Decision(loop=start)
    if ref == control.FILTER:
        items = config.get("items")
        if not isinstance(items, list):
            return _mismatch("`items` must be a list.")
        return Decision(filter_items=items)
    if ref == control.RUN_WORKFLOW:
        return Decision(failure=Failure(NOT_SUPPORTED, "Sub-flows need a build that runs them."))
    raise ValueError(f"{ref} isn't a control node")


__all__ = [
    "INLINE_ITEMS",
    "ITEM_CAP_EXCEEDED",
    "NOT_SUPPORTED",
    "WORKFLOW_FAILED",
    "Decision",
    "LoopStart",
    "decide",
]
```

Create `backend/src/dewpoint/engine/runtime/projection.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Previews for `run_steps` (spec §8). The projection is tenant-readable, so:
- a field its schema marks `x-sensitive` becomes "[redacted]" wherever the schema puts it: behind local `$ref`s, in
  any branch of `anyOf`, `oneOf` or `allOf` (sensitive in one branch, redacted in all), under any `patternProperties`
  schema of its object (declared keys included: JSON Schema applies both) and at a tuple's position (`prefixItems`);
  a map whose keys are sensitive (`propertyNames`) is redacted whole;
- a value the run learned is sensitive (MIN_SECRET characters or more) is masked wherever it reappears, in strings and
  keys: copied by a transform, embedded by a template, echoed by an error message;
- a preview larger than 8 KiB of canonical JSON becomes "[truncated]".

It runs in the workflow. `remember` keeps the learned values in one sorted order, so every replay masks the same way.
Masking catches copies, not transformations: a secret that CEL encodes or slices is no longer the same text."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from dewpoint.engine.canonical import canonical_json

PREVIEW_BYTES = 8 * 1024
REDACTED, TRUNCATED = "[redacted]", "[truncated]"
SENSITIVE = "x-sensitive"
MIN_SECRET = 4  # shorter values would mask ordinary text ("1", "yes") everywhere
_MAX_DEPTH = 64  # a schema that refers to itself ends here

Secrets = tuple[str, ...]


def _resolve(root: Mapping[str, Any], ref: str) -> Any:
    """A local JSON pointer (`#/$defs/Name`); anything else resolves to nothing (schemas are local-only, spec §4.1)."""
    if not ref.startswith("#/"):
        return None
    node: Any = root
    for part in ref[2:].split("/"):
        node = node.get(part.replace("~1", "/").replace("~0", "~")) if isinstance(node, Mapping) else None
    return node


def _branches(schema: Any, root: Mapping[str, Any], depth: int = 0) -> list[Mapping[str, Any]]:
    """`schema` and everything it stands for: its `$ref` followed, its `anyOf`/`oneOf`/`allOf` branches expanded."""
    if not isinstance(schema, Mapping) or depth > _MAX_DEPTH:
        return []
    out: list[Mapping[str, Any]] = [schema]
    ref = schema.get("$ref")
    if isinstance(ref, str):
        out += _branches(_resolve(root, ref), root, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        subs = schema.get(key)
        for sub in subs if isinstance(subs, list) else ():
            out += _branches(sub, root, depth + 1)
    return out


def _patterns(branch: Mapping[str, Any]) -> list[Any]:
    """Every `patternProperties` schema, matched or not: no regex runs on data in the workflow, so a sensitive
    pattern redacts every key's value in its object, declared keys included (over-redaction, never a leak)."""
    patterns = branch.get("patternProperties")
    return list(patterns.values()) if isinstance(patterns, Mapping) else []


def _map_values(branches: list[Mapping[str, Any]]) -> list[Any]:
    """The schemas that may govern an undeclared key's value: `additionalProperties` and every pattern."""
    out: list[Any] = []
    for b in branches:
        if isinstance(b.get("additionalProperties"), Mapping):
            out.append(b["additionalProperties"])
        out.extend(_patterns(b))
    return out


def _children(branches: list[Mapping[str, Any]], key: str) -> list[Any]:
    """The schemas that may govern `key`'s value. JSON Schema applies a declared property and every matching pattern
    together; `additionalProperties` only to keys neither covers."""
    out: list[Any] = []
    for b in branches:
        props = b.get("properties")
        if isinstance(props, Mapping) and key in props:
            out += [props[key], *_patterns(b)]
        else:
            out += _map_values([b])
    return out


def _elements(branches: list[Mapping[str, Any]], index: int) -> list[Any]:
    """The schemas that may govern a list's element `index`: its tuple position (`prefixItems`), and `items`."""
    out: list[Any] = [b["items"] for b in branches if isinstance(b.get("items"), Mapping)]
    for b in branches:
        prefix = b.get("prefixItems")
        if isinstance(prefix, list) and index < len(prefix):
            out.append(prefix[index])
    return out


def _keys_sensitive(branches: list[Mapping[str, Any]], root: Mapping[str, Any]) -> bool:
    names = [b["propertyNames"] for b in branches if isinstance(b.get("propertyNames"), Mapping)]
    return any(n.get(SENSITIVE) is True for s in names for n in _branches(s, root))


def _walk(value: Any, schemas: list[Any], root: Mapping[str, Any], found: list[Any] | None) -> Any:
    """The value with its sensitive parts redacted; with `found`, also collects what was redacted."""
    branches = [b for s in schemas for b in _branches(s, root)]
    if any(b.get(SENSITIVE) is True for b in branches):
        if found is not None:
            found.append(value)
        return REDACTED
    if isinstance(value, dict):
        if _keys_sensitive(branches, root):  # the keys are the secret: the whole map goes, its keys are learned
            if found is not None:
                found.extend(value)
                for k, v in value.items():
                    _walk(v, _children(branches, k), root, found)
            return REDACTED
        return {k: _walk(v, _children(branches, k), root, found) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, _elements(branches, i), root, found) for i, v in enumerate(value)]
    return value


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def sensitive_values(value: Any, schema: Mapping[str, Any] | None) -> list[str]:
    """Every string at a position the schema marks sensitive (a whole sensitive object's strings included)."""
    if not schema:
        return []
    found: list[Any] = []
    _walk(value, [schema], schema, found)
    return [s for v in found for s in _strings(v)]


def remember(secrets: Secrets, values: Iterable[str]) -> Secrets:
    """`secrets` with `values` added: longest first, so a longer secret is masked whole before a shorter one inside
    it. The same tuple when nothing is new."""
    fresh = {v for v in values if len(v) >= MIN_SECRET} - set(secrets)
    if not fresh:
        return secrets
    return tuple(sorted({*secrets, *fresh}, key=lambda s: (-len(s), s)))


def mask(value: Any, secrets: Secrets) -> Any:
    """`value` with every learned secret replaced by "[redacted]", in strings and keys, at any depth."""
    if not secrets:
        return value
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return value
    if isinstance(value, dict):
        return {mask(k, secrets): mask(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v, secrets) for v in value]
    return value


def location(loc: Sequence[str | int], schema: Mapping[str, Any]) -> str:
    """A validation error's location, as far as the schema declares it. Walking the schema along the location, a part
    is kept only where the schema puts it: a property name at an object, an index at an array. Anything else came
    from the data (a map key, numeric or not; an unknown key) or from the validator (a union's tag), and shows as `*`.
    After a `*`, the walk continues into the map's values."""
    candidates: list[Any] = [schema]
    parts: list[str] = []
    for part in loc:
        branches = [b for c in candidates for b in _branches(c, schema)]
        found: list[Any] = []
        if isinstance(part, str):
            found = [
                c
                for b in branches
                if isinstance(b.get("properties"), Mapping) and part in b["properties"]
                for c in (b["properties"][part], *_patterns(b))
            ]
        elif isinstance(part, int):
            for b in branches:
                prefix = b.get("prefixItems")
                if isinstance(prefix, list) and 0 <= part < len(prefix):
                    found.append(prefix[part])
                elif isinstance(b.get("items"), Mapping):
                    found.append(b["items"])
        if found:
            parts.append(str(part))
            candidates = found
        else:
            parts.append("*")
            candidates = _map_values(branches)
    return ".".join(parts) or "(root)"


def preview(value: Any, schema: Mapping[str, Any] | None = None, secrets: Secrets = ()) -> Any:
    shown = mask(_walk(value, [schema] if schema else [], schema or {}, None), secrets)
    try:
        size = len(canonical_json(shown))
    except (TypeError, ValueError):
        return TRUNCATED
    return TRUNCATED if size > PREVIEW_BYTES else shown


__all__ = [
    "MIN_SECRET",
    "PREVIEW_BYTES",
    "REDACTED",
    "TRUNCATED",
    "Secrets",
    "location",
    "mask",
    "preview",
    "remember",
    "sensitive_values",
]
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest -q tests/engine/runtime`
Expected: 63 passed.

- [ ] **Step 5: Checks and commit, then pause for checkpoint 1**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine \
  && git add src/dewpoint/engine/runtime tests/engine/runtime \
  && git commit -m "feat(engine): run-time values, control-node decisions and step previews" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `runs` and `run_steps`

The projection's storage (spec §8), under row-level security like every tenant table. Rows arrive as plain mappings,
because `core` knows nothing of the engine. Every write is idempotent, so a retried projection changes nothing
twice, and a late `running` row never overwrites a finished attempt.

**Files:**
- Create: `backend/migrations/versions/0008_runs.py`
- Create: `backend/src/dewpoint/core/models/runs.py`; modify `backend/src/dewpoint/core/models/__init__.py`
- Create: `backend/src/dewpoint/core/runs/__init__.py`, `backend/src/dewpoint/core/runs/service.py`
- Create: `backend/tests/core/runs/__init__.py` (empty), `backend/tests/core/runs/test_service.py`
- Modify: `backend/tests/conftest.py` (a `dispatch_sessionmaker` fixture)

**Interfaces:**
- Consumes (from `main`):
  - `tenant_scope`, and the SQL function `app_tenant_id()`;
  - the roles `dewpoint_dispatch`, `dewpoint_worker`, `dewpoint_api` and `dewpoint_admin` (migration 0001);
  - `workflow_versions (id, workflow_id)`, the target of the composite foreign key (migration 0007);
  - `Base`, and `tests.support.workflows.seed_workflow(owner) -> (tenant_id, workflow_id, version_id)`;
  - the fixtures `owner_sessionmaker` and `worker_sessionmaker`, and `_url_for`.
- Produces:
  - the tables `runs` and `run_steps`, with the ORM models `Run` and `RunStep`;
  - `core.runs.service`:
    - `MESSAGE_LIMIT = 500` and `sanitize(text) -> str | None`;
    - `insert_run(s, *, run_id, tenant_id, workflow_id, version_id, mode, started_by=None) -> Run`;
    - `finish_run(s, run_id, *, status, ended_at, error_code=None, error_message=None, iterations=0)`;
    - `upsert_steps(s, tenant_id, rows)`, where each row is a mapping with `run_id`, `step_id`, `iteration_key`,
      `attempt` and the `STEP_FIELDS`;
    - `get_run(s, run_id)`, `list_runs(s, *, workflow_id=None, before=None, limit=50)` (newest first) and
      `run_steps(s, run_id)`;
  - the fixture `dispatch_sessionmaker`.

- [ ] **Step 1: Write the failing tests**

Add the dispatch role's sessionmaker to `backend/tests/conftest.py`:

```diff
diff --git a/backend/tests/conftest.py b/backend/tests/conftest.py
--- a/backend/tests/conftest.py
+++ b/backend/tests/conftest.py
@@ -70,6 +70,13 @@


 @pytest.fixture(scope="session")
+async def dispatch_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
+    eng = make_engine(_url_for(pg_url, "dewpoint_dispatch"))
+    yield make_sessionmaker(eng)
+    await eng.dispose()
+
+
+@pytest.fixture(scope="session")
 async def worker_sessionmaker(pg_url: str, _test_users: None) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
     eng = make_engine(_url_for(pg_url, "dewpoint_worker"))
     yield make_sessionmaker(eng)
```

Create the empty file `backend/tests/core/runs/__init__.py`.

Create `backend/tests/core/runs/test_service.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`runs` and `run_steps` (spec §8, §10 projection): idempotent upserts under retries, sanitized messages, RLS."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from dewpoint.core.runs import service
from tests.support.workflows import seed_workflow


def row(run_id: uuid.UUID, status: str, **extra: Any) -> dict[str, Any]:
    step = uuid.UUID(int=7)
    return {
        "run_id": run_id,
        "step_id": step,
        "iteration_key": "",
        "attempt": 1,
        "node_key": "a",
        "status": status,
        **extra,
    }


async def seeded_run(owner: Any, dispatch: Any) -> tuple[uuid.UUID, uuid.UUID]:
    tenant, wf, version = await seed_workflow(owner)
    async with dispatch() as s, s.begin():
        await tenant_scope(s, tenant)
        run = await service.insert_run(
            s, run_id=uuid.uuid4(), tenant_id=tenant, workflow_id=wf, version_id=version, mode="live"
        )
    return tenant, run.id


async def steps(sm: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> list[Any]:
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant)
        return await service.run_steps(s, run_id)


async def test_upserts_are_idempotent_and_a_late_running_row_never_wins(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    done = row(run_id, "succeeded", output_preview={"v": 1}, outcome="applied")
    for rows in ([row(run_id, "running")], [done], [done], [row(run_id, "running")]):  # a retried projection
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await service.upsert_steps(s, tenant, rows)
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert (only.status, only.output_preview, only.outcome) == ("succeeded", {"v": 1}, "applied")


async def test_messages_are_sanitized(owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker) -> None:
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.upsert_steps(s, tenant, [row(run_id, "failed", error_message="bad\x00\x1b[31mred" + "x" * 900)])
        await service.finish_run(s, run_id, status="failed", ended_at=datetime.now(UTC), error_message="a\x07b")
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert only.error_message.startswith("bad  [31mred") and len(only.error_message) == service.MESSAGE_LIMIT
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        assert (await service.get_run(s, run_id)).error_message == "a b"  # type: ignore[union-attr]


async def test_deep_iterations_and_long_codes_are_stored(
    owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker
) -> None:
    """A projection write must never fail on a length: keys nest, and nothing bounds a plugin's error codes."""
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    deep = "/".join(f"{'k' * 63}:9999" for _ in range(3))  # the deepest nesting, longest keys, last items: 206 chars
    code = "plugin.\x1b" + "c" * 900
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.upsert_steps(s, tenant, [row(run_id, "failed", iteration_key=deep, error_code=code)])
        await service.finish_run(s, run_id, status="failed", ended_at=datetime.now(UTC), error_code=code)
    [only] = await steps(owner_sessionmaker, tenant, run_id)
    assert only.iteration_key == deep and only.error_code == service.sanitize(code)
    assert only.error_code.startswith("plugin. ") and len(only.error_code) == service.MESSAGE_LIMIT


async def test_rows_stay_in_their_tenant(owner_sessionmaker, dispatch_sessionmaker, worker_sessionmaker) -> None:
    tenant, run_id = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    other, _ = await seeded_run(owner_sessionmaker, dispatch_sessionmaker)
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        await service.upsert_steps(s, tenant, [row(run_id, "running")])
    async with worker_sessionmaker() as s, s.begin():
        await tenant_scope(s, other)
        assert await service.get_run(s, run_id) is None and await service.run_steps(s, run_id) == []
    async with worker_sessionmaker() as s, s.begin():  # no tenant at all: nothing visible
        assert await service.list_runs(s) == []
    with pytest.raises(DBAPIError):  # a row for another tenant is refused
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, other)
            await service.upsert_steps(s, tenant, [row(run_id, "running", node_key="b")])


async def test_runs_list_newest_first_and_page(owner_sessionmaker, dispatch_sessionmaker) -> None:
    tenant, wf, version = await seed_workflow(owner_sessionmaker)
    ids = []
    for _ in range(3):
        async with dispatch_sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            run = await service.insert_run(
                s, run_id=uuid.uuid4(), tenant_id=tenant, workflow_id=wf, version_id=version, mode="live"
            )
            ids.append(run.id)
    async with owner_sessionmaker() as s, s.begin():
        await tenant_scope(s, tenant)
        first = await service.list_runs(s, limit=2)
        rest = await service.list_runs(s, before=first[-1].started_at, limit=2)
    assert [r.id for r in first + rest] == ids[::-1]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/core/runs`
Expected: a collection error, `ModuleNotFoundError: No module named 'dewpoint.core.runs'`.

- [ ] **Step 3: Implement the migration, the models and the service**

Create `backend/migrations/versions/0008_runs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""runs and their per-step projection (engine spec §8)"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE runs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE runs FORCE ROW LEVEL SECURITY",
    "CREATE POLICY runs_scope ON runs USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    # A profile's evaluator may shut down only when no non-terminal run uses it (§4.5): counted across tenants.
    "CREATE POLICY runs_platform_read ON runs FOR SELECT TO dewpoint_admin USING (true)",
    "ALTER TABLE run_steps ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE run_steps FORCE ROW LEVEL SECURITY",
    "CREATE POLICY run_steps_scope ON run_steps "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT, UPDATE ON runs TO dewpoint_dispatch",
    "GRANT SELECT, UPDATE ON runs TO dewpoint_worker",
    "GRANT SELECT ON runs TO dewpoint_api, dewpoint_admin",
    "GRANT SELECT, INSERT, UPDATE ON run_steps TO dewpoint_worker",
    "GRANT SELECT ON run_steps TO dewpoint_api",
]
RUN_STATUSES = "status IN ('running', 'succeeded', 'failed', 'cancelled', 'deadline_exceeded')"


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_version_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("iterations", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_by", pg.UUID(as_uuid=True)),
        sa.ForeignKeyConstraint(
            ["workflow_version_id", "workflow_id"],
            ["workflow_versions.id", "workflow_versions.workflow_id"],
            name="runs_version_fk",
        ),
        sa.CheckConstraint("mode IN ('live', 'simulate')", name="runs_mode"),
        sa.CheckConstraint(RUN_STATUSES, name="runs_status"),
    )
    op.create_index("runs_tenant_started", "runs", ["tenant_id", sa.text("started_at DESC"), "id"])
    op.create_index("runs_open", "runs", ["workflow_version_id"], postgresql_where=sa.text("status = 'running'"))
    op.create_table(
        "run_steps",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), sa.ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("step_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("iteration_key", sa.Text, primary_key=True),
        sa.Column("attempt", sa.Integer, primary_key=True),
        sa.Column("node_key", sa.String(63), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("input_preview", pg.JSONB),
        sa.Column("output_preview", pg.JSONB),
        sa.Column("error_code", sa.Text),
        sa.Column("error_message", sa.Text),
        sa.Column("outcome", sa.String(16)),
        sa.Column("cel_mode", sa.String(16)),
        sa.CheckConstraint("status IN ('running', 'succeeded', 'failed', 'cancelled')", name="run_steps_status"),
        sa.CheckConstraint("outcome IN ('applied', 'simulated', 'outcome_unknown')", name="run_steps_outcome"),
        sa.CheckConstraint("cel_mode IN ('local', 'activity')", name="run_steps_cel_mode"),
    )
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in ("run_steps", "runs"):
        for policy in ("scope", "platform_read"):
            op.execute(f"DROP POLICY IF EXISTS {table}_{policy} ON {table}")
    op.drop_table("run_steps")
    op.drop_table("runs")
```

Create `backend/src/dewpoint/core/models/runs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from dewpoint.core.models.base import Base

RUN_STATUSES = ("running", "succeeded", "failed", "cancelled", "deadline_exceeded")


class Run(Base):
    """One run of a pinned workflow version. Its id is the Temporal workflow id."""

    __tablename__ = "runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(Text)  # a plugin's code: nothing bounds it, sanitize() does
    error_message: Mapped[str | None] = mapped_column(Text)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class RunStep(Base):
    """One attempt of one step in one scope: what the UI shows, never Temporal history (spec §8)."""

    __tablename__ = "run_steps"
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    step_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    iteration_key: Mapped[str] = mapped_column(Text, primary_key=True)  # unbounded: loops nest without a limit
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_key: Mapped[str] = mapped_column(String(63))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_preview: Mapped[Any] = mapped_column(JSONB)
    output_preview: Mapped[Any] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(Text)  # a plugin's code: nothing bounds it, sanitize() does
    error_message: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(16))
    cel_mode: Mapped[str | None] = mapped_column(String(16))
```

Register the models in `backend/src/dewpoint/core/models/__init__.py`:

```diff
diff --git a/backend/src/dewpoint/core/models/__init__.py b/backend/src/dewpoint/core/models/__init__.py
--- a/backend/src/dewpoint/core/models/__init__.py
+++ b/backend/src/dewpoint/core/models/__init__.py
@@ -1,5 +1,5 @@
 # SPDX-License-Identifier: Apache-2.0
-from dewpoint.core.models import audit, connections, identity, keys, plugins, tenancy, workflows
+from dewpoint.core.models import audit, connections, identity, keys, plugins, runs, tenancy, workflows
 from dewpoint.core.models.base import Base

-__all__ = ["Base", "audit", "connections", "identity", "keys", "plugins", "tenancy", "workflows"]
+__all__ = ["Base", "audit", "connections", "identity", "keys", "plugins", "runs", "tenancy", "workflows"]
```

Create `backend/src/dewpoint/core/runs/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
```

Create `backend/src/dewpoint/core/runs/service.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Storage for runs and their per-step projection (engine spec §8). Rows arrive as plain mappings: `core` knows
nothing of the engine. Every write is idempotent, so a retried projection changes nothing twice, and a late
`running` row never overwrites a finished attempt."""

import re
import uuid
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.runs import Run, RunStep

MESSAGE_LIMIT = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
STEP_FIELDS = (
    "node_key",
    "status",
    "started_at",
    "ended_at",
    "input_preview",
    "output_preview",
    "error_code",
    "error_message",
    "outcome",
    "cel_mode",
)


def sanitize(message: str | None) -> str | None:
    """A message or code fit to show: no control characters, at most MESSAGE_LIMIT characters."""
    if message is None:
        return None
    clean = _CONTROL.sub(" ", message)
    return clean if len(clean) <= MESSAGE_LIMIT else clean[: MESSAGE_LIMIT - 1] + "…"


async def insert_run(
    s: AsyncSession,
    *,
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    mode: str,
    started_by: uuid.UUID | None = None,
) -> Run:
    run = Run(
        id=run_id,
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        workflow_version_id=version_id,
        mode=mode,
        status="running",
        iterations=0,
        started_by=started_by,
    )
    s.add(run)
    await s.flush()
    return run


async def finish_run(
    s: AsyncSession,
    run_id: uuid.UUID,
    *,
    status: str,
    ended_at: datetime,
    error_code: str | None = None,
    error_message: str | None = None,
    iterations: int = 0,
) -> None:
    await s.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(
            status=status,
            ended_at=ended_at,
            error_code=sanitize(error_code),
            error_message=sanitize(error_message),
            iterations=iterations,
        )
    )


async def upsert_steps(s: AsyncSession, tenant_id: uuid.UUID, rows: Iterable[Mapping[str, Any]]) -> None:
    for row in rows:
        values = {
            "tenant_id": tenant_id,
            "run_id": row["run_id"],
            "step_id": row["step_id"],
            "iteration_key": row["iteration_key"],
            "attempt": row["attempt"],
            **{k: row.get(k) for k in STEP_FIELDS},
        }
        values["error_code"] = sanitize(values["error_code"])
        values["error_message"] = sanitize(values["error_message"])
        statement = insert(RunStep).values(**values)
        fresh = statement.excluded
        await s.execute(
            statement.on_conflict_do_update(
                index_elements=["run_id", "step_id", "iteration_key", "attempt"],
                set_={k: getattr(fresh, k) for k in STEP_FIELDS},
                where=(RunStep.status == "running") | (fresh.status != "running"),
            )
        )


async def get_run(s: AsyncSession, run_id: uuid.UUID) -> Run | None:
    return await s.get(Run, run_id)


async def list_runs(
    s: AsyncSession, *, workflow_id: uuid.UUID | None = None, before: datetime | None = None, limit: int = 50
) -> list[Run]:
    """Newest first; `before` pages through older runs."""
    q = select(Run).order_by(Run.started_at.desc(), Run.id.desc()).limit(limit)
    if workflow_id is not None:
        q = q.where(Run.workflow_id == workflow_id)
    if before is not None:
        q = q.where(Run.started_at < before)
    return list((await s.execute(q)).scalars())


async def run_steps(s: AsyncSession, run_id: uuid.UUID) -> list[RunStep]:
    q = (
        select(RunStep)
        .where(RunStep.run_id == run_id)
        .order_by(RunStep.started_at.nulls_last(), RunStep.iteration_key, RunStep.step_id, RunStep.attempt)
    )
    return list((await s.execute(q)).scalars())
```

- [ ] **Step 4: Run the tests and the migration round trip**

Run: `cd backend && uv run pytest -q tests/core/runs`
Expected: 5 passed. The session fixture migrates a fresh container to head.

Then check the downgrade on a scratch database (the image is the approved test image):

```bash
docker run -d --rm --name dp-mig -e POSTGRES_PASSWORD=pw -p 55432:5432 postgres:16-alpine && sleep 3 && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55432/postgres uv run alembic upgrade head && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55432/postgres uv run alembic downgrade 0007 && \
DEWPOINT_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:55432/postgres uv run alembic upgrade head; \
docker stop dp-mig
```

Expected: all three alembic commands exit 0 (`Running upgrade 0007 -> 0008`, `Running downgrade 0008 -> 0007`,
`Running upgrade 0007 -> 0008`).

- [ ] **Step 5: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/core tests/engine \
  && git add migrations/versions/0008_runs.py src/dewpoint/core/models src/dewpoint/core/runs tests/conftest.py \
       tests/core/runs \
  && git commit -m "feat(core): runs and run_steps with idempotent, non-regressing upserts under RLS" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The Temporal SDK, the activity contracts and the plugin-step activity

`RunGraph` names its activities and the dataclasses they exchange, in `engine/runtime/activities.py`. The worker
implements them in `apps/worker/activities.py`. The plugin-step activity runs **one attempt** and writes nothing:
`RunGraph` counts attempts and projects rows (decisions 7, 12, Task 5). It maps the node's errors per parent §6.6, and
its messages never quote input (decision 21). `ActivityEnvironment` runs it with no server.

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (`temporalio==1.33.0`)
- Create: `backend/src/dewpoint/engine/runtime/activities.py`
- Create: `backend/src/dewpoint/apps/worker/__init__.py`, `context.py`, `activities.py`
- Modify: `backend/tests/support/plugins/testkit.py` (`Echo.simulate`, a nested sensitive `login`, a `detail` and a
  sensitive `token` on `ambiguous_send`'s rejection, and the `testkit.slow_send` and `testkit.reconcile` nodes),
  `backend/tests/core/plugins/test_registry.py` (18 node types now)
- Create: `backend/tests/apps/worker/__init__.py` (empty), `backend/tests/apps/worker/test_activities.py`

**Interfaces:**
- Consumes:
  - from Task 2: `location`;
  - from 2a-2: `cel_client.evaluate_remote`, `cel_client.EvaluatorUnavailable`, `ipc.parse_request`,
    `ipc.EvaluateRequest`, `ipc.FrameError`, `ipc.read_frame`, `ipc.encode`, `ipc.SCHEMA`, `ipc.MAX_REQUEST`,
    `CURRENT_CEL_PROFILE`;
  - from the SDK: `Node`, `NodeKind`, `SideEffect`, `Plugin`, `StepContext`, `StepLogger`, `dump_output`,
    `node_manifest`, `RetryableError`, `FatalError`, `OutcomeUnknownError`.
- Produces:
  - `engine/runtime/activities.py`:
    - the constants `ENGINE_QUEUE`, `LOAD_VERSION`, `PROJECT`, `CEL_EVALUATE`, `LIVE`, `SIMULATE`, `APPLIED`,
      `SIMULATED` and `OUTCOME_UNKNOWN`;
    - `step_activity(ref) -> str` and `cel_queue(profile) -> str`;
    - `RunInput(tenant_id, run_id, version_id, trigger, mode=LIVE, max_run_duration_s=2_592_000, cel_schedule_to_start_s=600)`;
    - `RunResult(status, outputs=None, error=None, iterations=0)`;
    - `LoadVersionInput(tenant_id, version_id)`;
    - `VersionData(version_id, workflow_id, graph, expressions, cel_profile, manifests)`;
    - `StepInput(tenant_id, run_id, step_id, node_key, iteration_key, ref, config, mode=LIVE, attempt=1)`;
    - `StepResult(output, outcome=APPLIED)`, `CelInput(request)` and `CelResult(outcomes)`;
    - `StepRow(run_id, step_id, node_key, iteration_key, attempt, status, started_at=None, ended_at=None, input_preview=None, output_preview=None, error_code=None, error_message=None, outcome=None, cel_mode=None)`;
    - `RunSummary(run_id, status, ended_at, error_code=None, error_message=None, iterations=0)`;
    - `ProjectInput(tenant_id, steps=[], run=None)`.
  - `apps/worker/context.py`: `idempotency_key(run_id, step_id, iteration_key) -> str`, and
    `context(tenant_id, run_id, step_id, iteration_key, attempt) -> StepContext`.
  - `apps/worker/activities.py`:
    - the codes `CONFIG_INVALID`, `OUTPUT_SCHEMA_VIOLATION`, `SIMULATION_UNAVAILABLE`, `UNEXPECTED_ERROR` and
      `INVALID_REQUEST`;
    - the `RunStore` protocol: `async version(tenant_id, version_id) -> VersionData` and
      `async project(ProjectInput) -> None`;
    - `step_activity_for(node)`, one attempt that raises `ApplicationError(message, {"outcome": ...}, type=code,
      non_retryable=...)` on failure;
    - `engine_activities(store, plugins) -> list`, which covers the loader, the projection (the only writer) and one
      activity per action node;
    - `Evaluate`, `remote_evaluator(socket_path, profile) -> Evaluate` and `cel_activity(evaluate)`.
  - testkit:
    - `testkit.echo` simulates as `{"simulated": value}`;
    - `testkit.sensitive` outputs a nested `login` with a sensitive `password`, behind a `$ref`;
    - `testkit.ambiguous_send` appends `detail`, and its sensitive `token`, to its rejection message, like a
      receiver echoing what it got;
    - `testkit.slow_send@1` is ambiguous: it sends at once, records the send in `SlowSend.sent`, and then takes
      `seconds` to answer;
    - `testkit.reconcile@1` is reconcilable: `run()` applies its effect and then loses the reply
      (`RetryableError`), and `reconcile()` finds the effect.

- [ ] **Step 1: Add the Temporal SDK (confirm the download with the owner first)**

Run: `cd backend && uv add 'temporalio==1.33.0' && uv run python -c "import importlib.metadata as m; print(*(m.version(p) for p in ('temporalio', 'nexus-rpc', 'protobuf')))"`
Expected: `1.33.0 1.4.0 7.36.2`. `uv.lock` gains exactly `temporalio` and `nexus-rpc`, and every other locked
version is unchanged (`git diff uv.lock`).

- [ ] **Step 2: Write the failing tests**

Give testkit's echo a simulation and add the reconcilable node, in `backend/tests/support/plugins/testkit.py`:

```diff
diff --git a/backend/tests/support/plugins/testkit.py b/backend/tests/support/plugins/testkit.py
--- a/backend/tests/support/plugins/testkit.py
+++ b/backend/tests/support/plugins/testkit.py
@@ -2,7 +2,7 @@
 """Engine test fixtures. Lives under tests/, so it is never packaged or registered in production."""

 import asyncio
-from typing import Any, Literal
+from typing import Any, ClassVar, Literal

 from pydantic import BaseModel, Field

@@ -36,6 +36,9 @@

     async def run(self, ctx: StepContext, config: EchoConfig) -> EchoOutput:
         return EchoOutput(value=config.value)
+
+    async def simulate(self, ctx: StepContext, config: EchoConfig) -> EchoOutput:
+        return EchoOutput(value={"simulated": config.value})


 class FailNConfig(BaseModel):
@@ -75,9 +78,15 @@
         return Empty()


+class Login(BaseModel):
+    user: str
+    password: str = sensitive()
+
+
 class SensitiveOutput(BaseModel):
     public: str
     secret_value: str = sensitive()
+    login: Login  # a nested model: its schema sits behind a $ref


 class Sensitive(Node):
@@ -87,11 +96,15 @@
     Output = SensitiveOutput

     async def run(self, ctx: StepContext, config: Empty) -> SensitiveOutput:
-        return SensitiveOutput(public="visible", secret_value="s3cr3t-value")
+        return SensitiveOutput(
+            public="visible", secret_value="s3cr3t-value", login=Login(user="ops", password="pa55word")
+        )


 class AmbiguousConfig(BaseModel):
     outcome: Literal["sent", "unknown", "rejected"] = "sent"
+    detail: str = ""  # appended to the rejection: a receiver that echoes what it was sent
+    token: str = sensitive(default="")  # and a credential it echoes too


 class AmbiguousSend(Node):
@@ -105,8 +118,52 @@
         if config.outcome == "unknown":
             raise OutcomeUnknownError("testkit.timeout_after_send", "the request may have been delivered")
         if config.outcome == "rejected":
-            raise FatalError("testkit.rejected", "the receiver rejected the request")
+            detail = (f": {config.detail}" if config.detail else "") + (f" for {config.token}" if config.token else "")
+            raise FatalError("testkit.rejected", "the receiver rejected the request" + detail)
         return Empty()


-TESTKIT = Plugin(name="testkit", version="0.0.0", nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend))
+class SlowSendConfig(BaseModel):
+    seconds: float = Field(ge=0, le=600)
+
+
+class SlowSend(Node):
+    """Sends at once, then takes `seconds` to hear back. Past its timeout the request went out, but no reply came:
+    the case a retry would duplicate. `sent` counts the sends, for the tests."""
+
+    type = "testkit.slow_send"
+    version = 1
+    title = "Slow send"
+    Config = SlowSendConfig
+    side_effect = SideEffect.AMBIGUOUS
+    sent: ClassVar[list[str]] = []
+
+    async def run(self, ctx: StepContext, config: SlowSendConfig) -> Empty:
+        SlowSend.sent.append(str(ctx.run_id))
+        await asyncio.sleep(config.seconds)
+        return Empty()
+
+
+class ReconcileOutput(BaseModel):
+    found: bool
+
+
+class Reconcile(Node):
+    """Its first attempt applies the effect and then loses the reply; `reconcile()` finds the effect on a retry."""
+
+    type = "testkit.reconcile"
+    version = 1
+    title = "Reconcilable"
+    Output = ReconcileOutput
+    side_effect = SideEffect.RECONCILABLE
+
+    async def run(self, ctx: StepContext, config: Empty) -> ReconcileOutput:
+        raise RetryableError("testkit.lost_reply", "the effect happened, but the reply was lost")
+
+    async def reconcile(self, ctx: StepContext, config: Empty) -> ReconcileOutput | None:
+        return ReconcileOutput(found=True)
+
+
+TESTKIT = Plugin(
+    name="testkit", version="0.0.0", nodes=(Echo, FailN, Slow, Sensitive, AmbiguousSend, SlowSend, Reconcile)
+)
```

The registry sync test counts node types: 11 flow nodes and 7 testkit nodes now. In
`backend/tests/core/plugins/test_registry.py`:

```diff
diff --git a/backend/tests/core/plugins/test_registry.py b/backend/tests/core/plugins/test_registry.py
--- a/backend/tests/core/plugins/test_registry.py
+++ b/backend/tests/core/plugins/test_registry.py
@@ -19,10 +19,10 @@
 async def test_sync_registers_and_is_idempotent(admin_sessionmaker) -> None:
     async with admin_sessionmaker() as s, s.begin():
         report = await sync_installed(s, [PLUGIN, TESTKIT])
-    assert len(report.added) == 16 and report.unchanged == []
+    assert len(report.added) == 18 and report.unchanged == []
     async with admin_sessionmaker() as s, s.begin():
         report = await sync_installed(s, [PLUGIN, TESTKIT])
-    assert report.added == [] and len(report.unchanged) == 16
+    assert report.added == [] and len(report.unchanged) == 18
     async with admin_sessionmaker() as s:
         refs = {r.ref for r in await registry.list_node_types(s)}
         state = (
```

Create the empty file `backend/tests/apps/worker/__init__.py`.

Create `backend/tests/apps/worker/test_activities.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A plugin step's activity (spec §3, parent §6.6), run in Temporal's ActivityEnvironment: no server, no workflow. It
runs one attempt of the node and writes nothing: `RunGraph` counts the attempts and projects their rows."""

import asyncio
import dataclasses
import datetime
import ipaddress
import os
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator
from pydantic_core import PydanticCustomError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from dewpoint.apps.worker.activities import CHECKED_FORMATS, cel_activity, remote_evaluator, step_activity_for
from dewpoint.apps.worker.context import idempotency_key
from dewpoint.engine.cel import ipc
from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.activities import CelInput, CelResult, StepInput, StepResult
from dewpoint.sdk import Node, SideEffect, StepContext, sensitive
from tests.support.plugins.testkit import AmbiguousSend, Echo, FailN, Reconcile, Sensitive, Slow

IDS = {"tenant_id": str(uuid.UUID(int=1)), "run_id": str(uuid.UUID(int=2)), "step_id": str(uuid.UUID(int=3))}
SECRET = "hunter22"


def _quoting(what: str) -> Callable[[str], str]:
    """A validator whose own message quotes the value, as validators often do."""

    def check(value: str) -> str:
        if value.startswith("bad"):
            raise ValueError(f"{what} {value} isn't accepted")
        return value

    return check


class LiarOutput(BaseModel):
    n: int
    key: str
    _key = field_validator("key")(_quoting("key"))


def _custom(value: str) -> str:
    """A validator whose own error *type* carries the value: pydantic accepts any string there."""
    if value.startswith("bad"):
        raise PydanticCustomError(f"not_{value}", "refused")
    return value


class PinConfig(BaseModel):
    pin: int = Field(ge=1000, le=9999)
    token: str = "ok"
    code: str = "ok"
    _token = field_validator("token")(_quoting("token"))
    _code = field_validator("code")(_custom)


class Liar(Node):
    type = "testkit.liar"
    version = 1
    title = "Liar"
    Config = PinConfig
    Output = LiarOutput

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return {"n": config.pin, "key": f"bad-{SECRET}"}  # an output nobody ever sees, so nothing learns it


class KeyedOutput(BaseModel):
    headers: dict[str, int] = sensitive()
    codes: dict[int, int] = sensitive()


class StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: int


class Keyed(Node):
    """Its output fails validation under a key that came from the data, and its config refuses unknown keys."""

    type = "testkit.keyed"
    version = 1
    title = "Keyed"
    Config = StrictConfig
    Output = KeyedOutput

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return {"headers": {f"x-{SECRET}": "not-an-int"}, "codes": {428319: "not-an-int"}}


class Constructed(Node):
    """Returns an instance built without validation: `model_construct` holds whatever it's given."""

    type = "testkit.constructed"
    version = 1
    title = "Constructed"
    Output = LiarOutput

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return LiarOutput.model_construct(n="not-an-int", key="ok")


class FormatsConfig(BaseModel):
    valid: bool


class Tagged(BaseModel):
    """A valid output whose field serializer changes the type: an `int` is emitted as text, as its schema says."""

    id: int

    @field_serializer("id")
    def _tag(self, value: int) -> str:
        return f"id-{value}"


class Serialized(Node):
    type = "testkit.serialized"
    version = 1
    title = "Serialized"
    Output = Tagged

    async def run(self, ctx: StepContext, config: Any) -> Any:
        return Tagged(id=3)


class Formatted(BaseModel):
    """Values whose output schema declares a `format`, as pydantic writes it."""

    id: uuid.UUID
    at: datetime.datetime
    on: datetime.date
    ip: ipaddress.IPv4Address


class Formats(Node):
    type = "testkit.formats"
    version = 1
    title = "Formats"
    Config = FormatsConfig
    Output = Formatted

    async def run(self, ctx: StepContext, config: FormatsConfig) -> Any:
        valid = Formatted(
            id=uuid.UUID(int=5), at=datetime.datetime(2026, 9, 27, 10, 0), on=datetime.date(2026, 9, 27), ip="10.0.0.1"
        )
        return valid if config.valid else Formatted.model_construct(**{**dict(valid), "id": "not-a-uuid"})


class Broken(Node):
    type = "testkit.broken"
    version = 1
    title = "Broken"

    async def run(self, ctx: StepContext, config: Any) -> Any:
        raise ConnectionError(f"https://api.example/?token={SECRET} refused")


class BrokenSend(Broken):
    type = "testkit.broken_send"
    side_effect = SideEffect.AMBIGUOUS


def step(ref: str, config: dict[str, Any] | None = None, **extra: Any) -> StepInput:
    return StepInput(**IDS, node_key="s", iteration_key="l:0", ref=ref, config=config or {}, **extra)


async def call(fn: Callable[[StepInput], Awaitable[StepResult]], data: StepInput) -> StepResult:
    return await ActivityEnvironment().run(fn, data)


async def failure(fn: Callable[[StepInput], Awaitable[StepResult]], data: StepInput) -> Any:
    with pytest.raises(ApplicationError) as e:
        await call(fn, data)
    return e.value


async def test_a_step_returns_its_output_dumped_by_alias() -> None:
    assert await call(step_activity_for(Echo), step("testkit.echo@1", {"value": 5})) == StepResult(
        {"value": 5}, "applied"
    )


async def test_config_and_output_are_checked_without_echoing_the_values() -> None:
    """Review findings: pydantic's messages quote the input, and so does a validator's own prose (even with
    `include_input=False`). The projection is tenant-readable: name the field and the rule's code, nothing else."""
    bad_pin = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": SECRET}))
    bad_token = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": 1234, "token": f"bad-{SECRET}"}))
    bad_output = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": 1234}))
    assert {(e.type, e.non_retryable) for e in (bad_pin, bad_token)} == {("config_invalid", True)}
    assert (bad_output.type, bad_output.non_retryable) == ("output_schema_violation", True)
    assert bad_pin.message == "The config doesn't match `testkit.liar@1`: pin (int_parsing)."
    assert bad_token.message == "The config doesn't match `testkit.liar@1`: token (value_error)."
    assert bad_output.message == "The output doesn't match `testkit.liar@1`: key (value_error)."
    assert all(SECRET not in e.message for e in (bad_pin, bad_token, bad_output))


async def test_a_location_names_only_declared_fields() -> None:
    """Review finding: a location can hold a map key or an unknown key, taken from the data. A failed output is never
    learned, so the key would reach the projection. Declared names and list indexes stay; anything else is `*`."""
    bad_output = await failure(step_activity_for(Keyed), step("testkit.keyed@1", {"pin": 1}))
    bad_config = await failure(step_activity_for(Keyed), step("testkit.keyed@1", {"pin": 1, f"x-{SECRET}": 2}))
    listed = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": [SECRET]}))
    both = "headers.* (int_parsing); codes.* (int_parsing)"  # a numeric key isn't a list index
    assert bad_output.message == f"The output doesn't match `testkit.keyed@1`: {both}."
    assert bad_config.message == "The config doesn't match `testkit.keyed@1`: * (extra_forbidden)."
    assert listed.message == "The config doesn't match `testkit.liar@1`: pin (int_type)."
    assert all(SECRET not in e.message and "428319" not in e.message for e in (bad_output, bad_config, listed))


async def test_a_rule_code_is_one_pydantic_defines() -> None:
    """A custom error's type is whatever its validator made it, the value included: only pydantic's own codes show."""
    custom = await failure(step_activity_for(Liar), step("testkit.liar@1", {"pin": 1234, "code": f"bad-{SECRET}"}))
    assert custom.message == "The config doesn't match `testkit.liar@1`: code (custom_error)."


async def test_errors_map_to_retries_and_outcomes() -> None:
    retry = await failure(step_activity_for(FailN), step("testkit.fail_n@1", {"failures": 1}))
    fatal = await failure(step_activity_for(AmbiguousSend), step("testkit.ambiguous_send@1", {"outcome": "rejected"}))
    unknown = await failure(step_activity_for(AmbiguousSend), step("testkit.ambiguous_send@1", {"outcome": "unknown"}))
    assert (retry.type, retry.non_retryable, retry.details) == ("testkit.transient", False, ({"outcome": None},))
    assert (fatal.type, fatal.non_retryable) == ("testkit.rejected", True)
    assert (unknown.type, unknown.non_retryable, unknown.details) == (
        "testkit.timeout_after_send",
        True,
        ({"outcome": "outcome_unknown"},),
    )


async def test_an_unexpected_exception_is_retried_unless_the_request_may_have_been_sent() -> None:
    plain = await failure(step_activity_for(Broken), step("testkit.broken@1"))
    sent = await failure(step_activity_for(BrokenSend), step("testkit.broken_send@1"))
    assert (plain.type, plain.non_retryable, plain.details) == ("unexpected_error", False, ({"outcome": None},))
    assert (sent.type, sent.non_retryable, sent.details) == ("outcome_unknown", True, ({"outcome": "outcome_unknown"},))
    assert plain.message == "The node raised ConnectionError." and SECRET not in sent.message  # the text goes to logs


async def test_the_attempt_comes_from_the_workflow() -> None:
    """RunGraph counts attempts (each is one activity execution), so a reconcilable node checks on the second."""
    first = await failure(step_activity_for(Reconcile), step("testkit.reconcile@1"))
    second = await call(step_activity_for(Reconcile), step("testkit.reconcile@1", attempt=2))
    assert first.type == "testkit.lost_reply" and second == StepResult({"found": True}, "applied")
    passed = await call(step_activity_for(FailN), step("testkit.fail_n@1", {"failures": 1}, attempt=2))
    assert passed == StepResult({}, "applied")


async def test_simulation_calls_simulate_or_says_it_cannot() -> None:
    echoed = await call(step_activity_for(Echo), step("testkit.echo@1", {"value": 1}, mode="simulate"))
    refused = await failure(step_activity_for(Sensitive), step("testkit.sensitive@1", mode="simulate"))
    assert echoed == StepResult({"value": {"simulated": 1}}, "simulated")
    assert (refused.type, refused.non_retryable) == ("simulation_unavailable", True)


async def test_a_cancelled_step_stops() -> None:
    env = ActivityEnvironment()
    task = asyncio.create_task(env.run(step_activity_for(Slow), step("testkit.slow@1", {"seconds": 30})))
    await asyncio.sleep(0.1)
    env.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_the_idempotency_key_is_per_step_and_iteration_not_per_attempt() -> None:
    key = idempotency_key("r", "s", "l:0")
    assert key == idempotency_key("r", "s", "l:0") and len(key) == 64
    others = {idempotency_key("r", "s", "l:1"), idempotency_key("r", "t", "l:0"), idempotency_key("q", "s", "l:0")}
    assert len({key, *others}) == 4


def test_the_workflow_sends_the_attempt_and_nothing_to_project() -> None:
    names = [f.name for f in dataclasses.fields(StepInput)]
    assert names[-2:] == ["mode", "attempt"] and "cel_mode" not in names


@asynccontextmanager
async def evaluator(reply: dict[str, Any]) -> AsyncIterator[str]:
    """A fake cel-evaluator on a Unix socket, answering every request with `reply`."""

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await ipc.read_frame(reader, ipc.MAX_REQUEST)
        writer.write(ipc.encode(reply))
        await writer.drain()
        writer.close()

    with tempfile.TemporaryDirectory(dir="/tmp") as d:  # AF_UNIX paths are limited to about 100 bytes
        path = os.path.join(d, "cel.sock")
        async with await asyncio.start_unix_server(handle, path=path):
            yield path


REQUEST = CelInput(ipc.EvaluateRequest(CURRENT_CEL_PROFILE, "x + 1", {"x": T.DYN}, ({"x": 1},)).to_json())


async def test_cel_evaluate_records_outcomes_and_retries_an_unavailable_evaluator(tmp_path: Path) -> None:
    reply = {"schema": ipc.SCHEMA, "results": [{"ok": 2}]}
    async with evaluator(reply) as path:
        answered = await ActivityEnvironment().run(cel_activity(remote_evaluator(path, CURRENT_CEL_PROFILE)), REQUEST)
    assert answered == CelResult([{"ok": 2}])
    nowhere = cel_activity(remote_evaluator(str(tmp_path / "nowhere.sock"), CURRENT_CEL_PROFILE))
    with pytest.raises(ApplicationError) as unavailable:
        await ActivityEnvironment().run(nowhere, REQUEST)
    assert (unavailable.value.type, unavailable.value.non_retryable) == ("evaluator_unavailable", False)
    with pytest.raises(ApplicationError) as invalid:
        await ActivityEnvironment().run(nowhere, CelInput({"schema": "nope"}))
    assert (invalid.value.type, invalid.value.non_retryable) == ("invalid_request", True)


async def test_an_output_instance_is_validated_too() -> None:
    """Checkpoint-2 finding: an instance of the node's own Output was trusted as it stood, but pydantic validates
    instances only when they're built through it. It's checked like any other output."""
    bad = await failure(step_activity_for(Constructed), step("testkit.constructed@1"))
    assert (bad.type, bad.non_retryable) == ("output_schema_violation", True)
    assert bad.message == "The output doesn't match `testkit.constructed@1`: n (type)."  # the output schema's rule


async def test_an_instance_breaking_a_format_is_refused_and_valid_formats_pass() -> None:
    """Checkpoint-2 re-review: without a format checker, `format: uuid` held nothing. The formats checked are the ones
    whose checks agree with what pydantic emits: a naive datetime is valid output, so `date-time` isn't checked."""
    bad = await failure(step_activity_for(Formats), step("testkit.formats@1", {"valid": False}))
    assert (bad.type, bad.message) == (
        "output_schema_violation",
        "The output doesn't match `testkit.formats@1`: id (format).",
    )
    assert set(FormatChecker(formats=CHECKED_FORMATS).checkers) == set(CHECKED_FORMATS)  # each one really checked
    good = await call(step_activity_for(Formats), step("testkit.formats@1", {"valid": True}))
    assert good.output == {
        "id": str(uuid.UUID(int=5)),
        "at": "2026-09-27T10:00:00",
        "on": "2026-09-27",
        "ip": "10.0.0.1",
    }


async def test_a_field_serializer_emits_what_the_output_schema_declares() -> None:
    """Checkpoint-2 re-review: an instance is checked as it's emitted, against the declared output schema, not
    against the model's input types, which a typed field serializer may change."""
    assert await call(step_activity_for(Serialized), step("testkit.serialized@1")) == StepResult(
        {"id": "id-3"}, "applied"
    )
```

- [ ] **Step 3: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_activities.py tests/core/plugins/test_registry.py`
Expected: a collection error, `ModuleNotFoundError: No module named 'dewpoint.apps.worker'`.

- [ ] **Step 4: Implement the contracts and the activities**

Create `backend/src/dewpoint/engine/runtime/activities.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What `RunGraph` asks of the outside world, as names and dataclasses (spec §2): the version loader, plugin steps,
`cel.evaluate` and the projection. `apps/worker` implements them; the workflow only names them. A plugin step's
activity runs one attempt and writes nothing; the projection is the only activity that writes."""

from dataclasses import dataclass, field
from typing import Any

ENGINE_QUEUE = "dewpoint-engine"
LOAD_VERSION = "dewpoint.load_version"
PROJECT = "dewpoint.project"
CEL_EVALUATE = "cel.evaluate"
LIVE, SIMULATE = "live", "simulate"
APPLIED, SIMULATED, OUTCOME_UNKNOWN = "applied", "simulated", "outcome_unknown"


def step_activity(ref: str) -> str:
    """`testkit.echo@1` runs as the activity `testkit.echo.v1`."""
    node_type, version = ref.rsplit("@", 1)
    return f"{node_type}.v{version}"


def cel_queue(profile: str) -> str:
    return f"dewpoint-cel.{profile}"


@dataclass(frozen=True)
class RunInput:
    tenant_id: str
    run_id: str
    version_id: str
    trigger: dict[str, Any]
    mode: str = LIVE  # live | simulate
    max_run_duration_s: float = 30 * 86_400
    cel_schedule_to_start_s: float = 600  # no evaluator for the profile after this: cel_profile_unavailable


@dataclass(frozen=True)
class RunResult:
    status: str  # succeeded | failed | deadline_exceeded | cancelled
    outputs: dict[str, Any] | None = None
    error: dict[str, Any] | None = None  # {code, message}
    iterations: int = 0


@dataclass(frozen=True)
class LoadVersionInput:
    tenant_id: str
    version_id: str


@dataclass(frozen=True)
class VersionData:
    version_id: str
    workflow_id: str
    graph: dict[str, Any]
    expressions: list[dict[str, Any]]
    cel_profile: str
    manifests: dict[str, dict[str, Any]]  # type@version -> manifest, for every node type in the graph


@dataclass(frozen=True)
class StepInput:
    tenant_id: str
    run_id: str
    step_id: str
    node_key: str
    iteration_key: str
    ref: str
    config: dict[str, Any]
    mode: str = LIVE
    attempt: int = 1  # RunGraph counts attempts: each one is its own activity execution


@dataclass(frozen=True)
class StepResult:
    output: dict[str, Any]
    outcome: str = APPLIED


@dataclass(frozen=True)
class CelInput:
    request: dict[str, Any]  # a cel.evaluate.v1 request


@dataclass(frozen=True)
class CelResult:
    outcomes: list[dict[str, Any]]  # one per binding set: {ok} or {error, message}


@dataclass(frozen=True)
class StepRow:
    """One `run_steps` row, keyed (run_id, step_id, iteration_key, attempt)."""

    run_id: str
    step_id: str
    node_key: str
    iteration_key: str
    attempt: int
    status: str  # running | succeeded | failed | cancelled
    started_at: str | None = None
    ended_at: str | None = None
    input_preview: Any = None
    output_preview: Any = None
    error_code: str | None = None
    error_message: str | None = None
    outcome: str | None = None
    cel_mode: str | None = None


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    ended_at: str
    error_code: str | None = None
    error_message: str | None = None
    iterations: int = 0


@dataclass(frozen=True)
class ProjectInput:
    tenant_id: str
    steps: list[StepRow] = field(default_factory=list)
    run: RunSummary | None = None
```

Create `backend/src/dewpoint/apps/worker/__init__.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The Temporal worker (spec §2, §6): `RunGraph` and the activities it names, wired to `core` and the plugins."""
```

Create `backend/src/dewpoint/apps/worker/context.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The `StepContext` a plugin step receives (spec §3)."""

import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from temporalio import activity

from dewpoint.sdk import StepContext, StepLogger

_SECRET = re.compile(r"password|secret|token|credential|authorization|api_?key", re.IGNORECASE)


def idempotency_key(run_id: str, step_id: str, iteration_key: str) -> str:
    """Derived from (run_id, step_id, iteration_key): the same for every attempt of a step in one iteration."""
    return hashlib.sha256(f"{run_id}\x1f{step_id}\x1f{iteration_key}".encode()).hexdigest()


class _Logger:
    """Logs with the step's ids; a field whose name looks secret is redacted."""

    def __init__(self, **ids: str) -> None:
        self._log = structlog.get_logger("dewpoint.step").bind(**ids)

    @staticmethod
    def _clean(fields: dict[str, Any]) -> dict[str, Any]:
        return {k: "[redacted]" if _SECRET.search(k) else v for k, v in fields.items()}

    def info(self, event: str, **fields: Any) -> None:
        self._log.info(event, **self._clean(fields))

    def warning(self, event: str, **fields: Any) -> None:
        self._log.warning(event, **self._clean(fields))


@dataclass(frozen=True)
class Context:
    tenant_id: uuid.UUID
    run_id: uuid.UUID
    step_id: uuid.UUID
    iteration_key: str
    attempt: int
    log: StepLogger

    @property
    def cancelled(self) -> bool:
        return activity.is_cancelled()

    def idempotency_key(self) -> str:
        return idempotency_key(str(self.run_id), str(self.step_id), self.iteration_key)

    def heartbeat(self, *details: object) -> None:
        activity.heartbeat(*details)


def context(tenant_id: str, run_id: str, step_id: str, iteration_key: str, attempt: int) -> StepContext:
    log = _Logger(run_id=run_id, step_id=step_id, iteration_key=iteration_key)
    return Context(uuid.UUID(tenant_id), uuid.UUID(run_id), uuid.UUID(step_id), iteration_key, attempt, log)
```

Create `backend/src/dewpoint/apps/worker/activities.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The activities `RunGraph` names (engine/runtime/activities.py), over a `RunStore`: the database in production, a
dict in tests.

A plugin step's activity runs **one attempt** of its node and writes nothing (spec §3, parent §6.6). `RunGraph`
schedules each attempt itself, decides whether to retry, and projects every attempt's rows, so a row write can
never repeat an effect, and a timeout after an ambiguous send is never retried. The attempt:
- validates the config before `run()` and the output after; a mismatch is fatal (`config_invalid`,
  `output_schema_violation`);
- calls `simulate()` in a simulated run, and records `simulated`;
- maps `RetryableError` to retryable, `FatalError` to fatal, and `OutcomeUnknownError` to `outcome_unknown`, never
  retried;
- maps any other exception to `unexpected_error`, retryable, except from an `ambiguous` node, where the request may
  have been sent: `outcome_unknown`;
- for a `reconcilable` node on attempt 2 or later, calls `reconcile()` first and keeps what it finds.

The projection is tenant-readable, so a message never quotes input: a validation error names each field and its
rule's code, and an unexpected exception names only its type. Its text goes to the worker's log."""

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Protocol, get_args

import structlog
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError
from pydantic_core.core_schema import ErrorType
from temporalio import activity
from temporalio.exceptions import ApplicationError

from dewpoint.apps.cel_client import EvaluatorUnavailable, evaluate_remote
from dewpoint.apps.worker.context import context
from dewpoint.engine.cel import ipc
from dewpoint.engine.runtime.activities import (
    APPLIED,
    CEL_EVALUATE,
    LOAD_VERSION,
    OUTCOME_UNKNOWN,
    PROJECT,
    SIMULATE,
    SIMULATED,
    CelInput,
    CelResult,
    LoadVersionInput,
    ProjectInput,
    StepInput,
    StepResult,
    VersionData,
    step_activity,
)
from dewpoint.engine.runtime.projection import location
from dewpoint.sdk import (
    FatalError,
    Node,
    NodeKind,
    OutcomeUnknownError,
    Plugin,
    RetryableError,
    SideEffect,
    dump_output,
    node_manifest,
)

CONFIG_INVALID = "config_invalid"
OUTPUT_SCHEMA_VIOLATION = "output_schema_violation"
SIMULATION_UNAVAILABLE = "simulation_unavailable"
UNEXPECTED_ERROR = "unexpected_error"
INVALID_REQUEST = "invalid_request"
_log = structlog.get_logger("dewpoint.worker")
_PYDANTIC_CODES = frozenset(get_args(ErrorType))  # every built-in validation error type
# The `format`s an emitted output is checked for: those whose checks agree with what pydantic emits, and need no
# optional library. `date-time` isn't one (RFC 3339 wants an offset; pydantic emits naive datetimes without one).
# Listing them keeps the check from changing when an optional format library happens to be installed.
CHECKED_FORMATS = ("date", "time", "uuid", "email", "ipv4", "ipv6", "regex")


class RunStore(Protocol):
    async def version(self, tenant_id: str, version_id: str) -> VersionData: ...
    async def project(self, data: ProjectInput) -> None: ...


class _StepFailed(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool, outcome: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable, self.outcome = code, message, retryable, outcome


def _fields(error: ValidationError, schema: Mapping[str, Any]) -> str:
    """Each failing field and its rule's stable code (`int_parsing`, `value_error`), nothing else: pydantic's
    messages quote the input, and so does a validator's own prose, whatever `include_input` says. A location shows
    only what the schema declares at each place (`projection.location`): a map key is data, even a numeric one. A
    code shows only if pydantic defines it: a custom error's type is whatever its validator made it."""
    problems = error.errors(include_url=False, include_context=False, include_input=False)
    return "; ".join(f"{location(e['loc'], schema)} ({_code(e['type'])})" for e in problems) + "."


def _code(error_type: str) -> str:
    return error_type if error_type in _PYDANTIC_CODES else "custom_error"


async def _call(node: type[Node], step: StepInput, schema: Mapping[str, Any]) -> tuple[BaseModel, str]:
    try:
        config = node.Config.model_validate(step.config)
    except ValidationError as e:
        message = f"The config doesn't match `{step.ref}`: {_fields(e, schema)}"
        raise _StepFailed(CONFIG_INVALID, message, retryable=False) from None
    ctx = context(step.tenant_id, step.run_id, step.step_id, step.iteration_key, step.attempt)
    instance = node()
    try:
        if step.mode == SIMULATE:
            return await instance.simulate(ctx, config), SIMULATED
        if node.side_effect == SideEffect.RECONCILABLE and step.attempt > 1:
            found = await instance.reconcile(ctx, config)
            if found is not None:
                return found, APPLIED
        return await instance.run(ctx, config), APPLIED
    except OutcomeUnknownError as e:
        raise _StepFailed(e.code, e.message, retryable=False, outcome=OUTCOME_UNKNOWN) from None
    except FatalError as e:
        raise _StepFailed(e.code, e.message, retryable=False) from None
    except RetryableError as e:
        raise _StepFailed(e.code, e.message, retryable=True) from None
    except asyncio.CancelledError:
        raise
    except Exception as e:
        if isinstance(e, NotImplementedError) and step.mode == SIMULATE:
            raise _StepFailed(SIMULATION_UNAVAILABLE, f"`{step.ref}` can't be simulated.", retryable=False) from None
        _log.warning(
            "step_unexpected_error",
            run_id=step.run_id,
            step_id=step.step_id,
            iteration_key=step.iteration_key,
            attempt=step.attempt,
            error_type=type(e).__name__,
            error=str(e)[:500],
        )
        message = f"The node raised {type(e).__name__}."
        if node.side_effect == SideEffect.AMBIGUOUS:
            raise _StepFailed(OUTCOME_UNKNOWN, message, retryable=False, outcome=OUTCOME_UNKNOWN) from None
        raise _StepFailed(UNEXPECTED_ERROR, message, retryable=True) from None


def step_activity_for(node: type[Node]) -> Callable[[StepInput], Awaitable[StepResult]]:
    ref = f"{node.type}@{node.version}"
    config_schema = node.Config.model_json_schema(mode="validation")
    output_schema = node_manifest(node)["output_schema"]  # what the node promises to emit: serialized and closed
    emitted = Draft202012Validator(output_schema, format_checker=FormatChecker(formats=CHECKED_FORMATS))

    @activity.defn(name=step_activity(ref))
    async def run_step(step: StepInput) -> StepResult:
        try:
            result, outcome = await _call(node, step, config_schema)
            if not isinstance(result, BaseModel):
                return StepResult(dump_output(node.Output.model_validate(result)), outcome)
            # pydantic trusts instances it didn't build (`model_construct`, assignment): check what the instance emits
            # against the declared output schema, not against the model's input types (a field serializer may change
            # them)
            data = result.model_dump(mode="json", by_alias=True, warnings=False)
            problems = sorted(emitted.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path])
            if problems:
                where = "; ".join(f"{location(list(e.absolute_path), output_schema)} ({e.validator})" for e in problems)
                message = f"The output doesn't match `{ref}`: {where}."
                raise ApplicationError(message, {"outcome": None}, type=OUTPUT_SCHEMA_VIOLATION, non_retryable=True)
            return StepResult(data, outcome)
        except _StepFailed as f:
            details = {"outcome": f.outcome}
            raise ApplicationError(f.message, details, type=f.code, non_retryable=not f.retryable) from None
        except PydanticSerializationError:
            message = f"The output doesn't match `{ref}`: it can't be written as JSON."
            raise ApplicationError(
                message, {"outcome": None}, type=OUTPUT_SCHEMA_VIOLATION, non_retryable=True
            ) from None
        except ValidationError as e:
            message = f"The output doesn't match `{ref}`: {_fields(e, output_schema)}"
            raise ApplicationError(
                message, {"outcome": None}, type=OUTPUT_SCHEMA_VIOLATION, non_retryable=True
            ) from None

    return run_step


def engine_activities(store: RunStore, plugins: Iterable[Plugin]) -> list[Callable[..., Any]]:
    """Everything the engine queue serves: the version loader, the projection, and one activity per action node."""

    @activity.defn(name=LOAD_VERSION)
    async def load_version(data: LoadVersionInput) -> VersionData:
        return await store.version(data.tenant_id, data.version_id)

    @activity.defn(name=PROJECT)
    async def project(data: ProjectInput) -> None:
        await store.project(data)

    steps = [step_activity_for(node) for plugin in plugins for node in plugin.nodes if node.kind == NodeKind.ACTION]
    return [load_version, project, *steps]


Evaluate = Callable[[dict[str, Any]], Awaitable[list[dict[str, Any]]]]


def remote_evaluator(socket_path: str, profile: str) -> Evaluate:
    """Evaluate through the cel-evaluator on `socket_path` (spec §5.7)."""

    async def evaluate(request: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            parsed = ipc.parse_request(request)
        except ipc.FrameError as e:  # a request no retry can fix
            raise ApplicationError(f"not an evaluate request: {e}", type=INVALID_REQUEST, non_retryable=True) from None
        if not isinstance(parsed, ipc.EvaluateRequest):
            raise ApplicationError("not an evaluate request", type=INVALID_REQUEST, non_retryable=True)
        outcomes = await evaluate_remote(socket_path, parsed, served_profile=profile)
        return [o.to_json() for o in outcomes]

    return evaluate


def cel_activity(evaluate: Evaluate) -> Callable[[CelInput], Awaitable[CelResult]]:
    """`cel.evaluate`: outcomes are recorded; an unavailable evaluator is retried by Temporal (3 attempts)."""

    @activity.defn(name=CEL_EVALUATE)
    async def cel_evaluate(data: CelInput) -> CelResult:
        try:
            return CelResult(await evaluate(data.request))
        except EvaluatorUnavailable as e:
            raise ApplicationError(str(e), type="evaluator_unavailable") from None

    return cel_evaluate


__all__ = [
    "CHECKED_FORMATS",
    "CONFIG_INVALID",
    "INVALID_REQUEST",
    "OUTPUT_SCHEMA_VIOLATION",
    "SIMULATION_UNAVAILABLE",
    "UNEXPECTED_ERROR",
    "Evaluate",
    "RunStore",
    "cel_activity",
    "engine_activities",
    "remote_evaluator",
    "step_activity_for",
]
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_activities.py tests/core/plugins/test_registry.py`
Expected: 20 passed (15 + 5).

- [ ] **Step 6: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine tests/core tests/apps/worker \
  && uv run pip-licenses --fail-on="GPL;AGPL;LGPL;SSPL;BUSL" --partial-match > /dev/null \
  && git add pyproject.toml uv.lock src/dewpoint/engine/runtime/activities.py src/dewpoint/apps/worker \
       tests/support/plugins/testkit.py tests/core/plugins/test_registry.py tests/apps/worker \
  && git commit -m "feat(worker): the Temporal SDK, activity contracts and the plugin-step activity" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `RunGraph`

The workflow. It loads the pinned version with one local activity and compiles it (decision 11), then drives the
scheduler:
- Each ready step, and each loop iteration's `collect`, runs as one asyncio task, at most 100 at a time.
- A task resolves its values, CEL through `cel.evaluate` (decision 6). Then a control node decides, or a plugin
  step runs its attempts: one activity execution each, retried by the workflow itself, never after a timeout of an
  ambiguous node (decision 7).
- Completions are applied in (scope, topological) order, so a replay applies them the same way.
- Every row, for plugin attempts and control steps alike, and the run's summary go through the one DB-only
  projection, at most one in flight (decisions 12, 13).
- Every value the run learns is sensitive (from outputs, configs and the trigger) is masked in what it projects
  (decision 21).
- Cancellation arrives as an `ActivityError` and is re-raised as cancellation, never retried (go/no-go 11).
- The deadline is a durable timer, and so are `delay` and `wait_until`.

The tests run on Temporal's time-skipping test server.

**Files:**
- Create: `backend/src/dewpoint/engine/runtime/workflow.py`
- Create: `backend/tests/apps/worker/conftest.py`, `harness.py`, `test_run_graph.py`, `test_run_graph_policies.py`

**Interfaces:**
- Consumes:
  - from Tasks 1, 2 and 4: `compile_program`, `Scheduler` and its types, `resolve`, `nodes`, `preview`, and the
    activity names and dataclasses;
  - from 2a-2: `YieldBudget` (`engine.cel.route`), `LOCAL_CEL_PROFILE`, and from `engine.cel.evaluate` the class
    `Outcome` and the codes `PROFILE_UNAVAILABLE`, `TYPE_MISMATCH` and `TIMEOUT`;
  - from `engine.graph.values`: `CelValue`, `RefValue`, `TemplateValue`, `iter_values` and `pointer_str`;
  - from Task 4: `engine_activities`, `cel_activity`, `Evaluate` and `RunStore`, which the harness uses.
- Produces:
  - `RunGraph`, workflow type `RunGraph`, with `run(RunInput) -> RunResult`;
  - the constants `IN_FLIGHT_CAP = 100`, `CEL_BATCH = 1_000`, `DEADLINE_EXCEEDED`, `VERSION_UNUSABLE`,
    `INTERNAL_ERROR`, `NODE_TYPE_UNAVAILABLE` and `AMBIGUOUS`;
  - `tests/apps/worker/harness.py`:
    - `TENANT`;
    - `MemoryStore`, with the fields `versions`, `rows`, `runs` and `subflows`, and the methods
      `add(g) -> version_id`, `version`, `project` and `steps(run_id) -> list[StepRow]`;
    - `in_process(request)`, the evaluator's own work computed in-process;
    - `workers(client, store, *, plugins=(TESTKIT,), evaluate=in_process, runner=None, cache=1000)`, an async
      context manager;
    - `start(client, store, g, trigger=None, **run_input) -> WorkflowHandle` and `run(...) -> RunResult`;
  - the fixtures `env` (session-scoped) and `own_env` (a server of the test's own).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/apps/worker/conftest.py`:

```python
# SPDX-License-Identifier: Apache-2.0
from collections.abc import AsyncIterator

import pytest
from temporalio.testing import WorkflowEnvironment


@pytest.fixture(scope="session")
async def env() -> AsyncIterator[WorkflowEnvironment]:
    """Temporal's time-skipping test server (downloaded once by the SDK), shared by the session."""
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment


@pytest.fixture
async def own_env() -> AsyncIterator[WorkflowEnvironment]:
    """A test server of the test's own, for a test that ends a run while an activity still runs. That activity never
    completes against its closed run, and the time-skipping server stops skipping time while any activity is
    outstanding: every later timer on a shared server would wait in real time."""
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment
```

Create `backend/tests/apps/worker/harness.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Run test graphs through `RunGraph` on Temporal's time-skipping test server, with the real step activities, an
in-memory store and an in-process CEL evaluator (the real one needs Linux and its own container)."""

import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from temporalio.client import Client, WorkflowHandle
from temporalio.worker import Worker, WorkflowRunner
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner

from dewpoint.apps.worker.activities import Evaluate, RunStore, cel_activity, engine_activities
from dewpoint.engine.cel import ipc
from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.graph.validate import SubflowInfo
from dewpoint.engine.runtime.activities import (
    ENGINE_QUEUE,
    LIVE,
    ProjectInput,
    RunInput,
    RunResult,
    RunSummary,
    StepRow,
    VersionData,
    cel_queue,
)
from dewpoint.engine.runtime.workflow import RunGraph
from dewpoint.sdk import Plugin
from tests.engine.runtime.support import MANIFESTS, expressions
from tests.support.graphs import G
from tests.support.plugins.testkit import TESTKIT

TENANT = str(uuid.UUID(int=1))


@dataclass
class MemoryStore:
    versions: dict[str, VersionData] = field(default_factory=dict)
    rows: dict[tuple[str, str, str, int], StepRow] = field(default_factory=dict)
    runs: dict[str, RunSummary] = field(default_factory=dict)
    subflows: dict[uuid.UUID, SubflowInfo] = field(default_factory=dict)  # what validation sees as published

    def add(self, g: G) -> str:
        version_id = str(uuid.uuid4())
        refs = {n["type"] for n in g.nodes}
        self.versions[version_id] = VersionData(
            version_id=version_id,
            workflow_id=str(uuid.uuid4()),
            graph=g.data(),
            expressions=expressions(g, self.subflows),
            cel_profile=CURRENT_CEL_PROFILE,
            manifests={r: MANIFESTS[r] for r in sorted(refs)},
        )
        return version_id

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        return self.versions[version_id]

    async def project(self, data: ProjectInput) -> None:
        for row in data.steps:
            self.rows[(row.run_id, row.step_id, row.iteration_key, row.attempt)] = row
        if data.run is not None:
            self.runs[data.run.run_id] = data.run

    def steps(self, run_id: str) -> list[StepRow]:
        return [r for k, r in sorted(self.rows.items()) if k[0] == run_id]


async def in_process(request: dict[str, Any]) -> list[dict[str, Any]]:
    """What the evaluator would answer, computed here: `ipc.evaluate_request` is the child's own work."""
    parsed = ipc.parse_request(request)
    assert isinstance(parsed, ipc.EvaluateRequest)
    reply = ipc.parse_reply(ipc.evaluate_request(parsed), len(parsed.bindings))
    if reply.error is not None:
        return [{"error": reply.error, "message": reply.message}] * len(parsed.bindings)
    return [o.to_json() for o in reply.outcomes]


@asynccontextmanager
async def workers(
    client: Client,
    store: RunStore,
    *,
    plugins: Iterable[Plugin] = (TESTKIT,),
    evaluate: Evaluate | None = in_process,
    runner: WorkflowRunner | None = None,  # tests that inject faults run the workflow outside the sandbox
    cache: int = 1000,  # 0: every workflow task replays the run's whole history
) -> AsyncIterator[None]:
    engine = Worker(
        client,
        task_queue=ENGINE_QUEUE,
        workflows=[RunGraph],
        activities=engine_activities(store, plugins),
        workflow_runner=runner or SandboxedWorkflowRunner(),
        max_cached_workflows=cache,
    )
    async with engine:
        if evaluate is None:  # no evaluator serves the profile
            yield
            return
        async with Worker(client, task_queue=cel_queue(CURRENT_CEL_PROFILE), activities=[cel_activity(evaluate)]):
            yield


async def start(
    client: Client, store: MemoryStore, g: G, trigger: dict[str, Any] | None = None, **options: Any
) -> WorkflowHandle[Any, RunResult]:
    run_id = str(uuid.uuid4())
    run = RunInput(TENANT, run_id, store.add(g), trigger or {}, options.pop("mode", LIVE), **options)
    return await client.start_workflow(RunGraph.run, run, id=run_id, task_queue=ENGINE_QUEUE)


async def run(
    client: Client, store: MemoryStore, g: G, trigger: dict[str, Any] | None = None, **options: Any
) -> RunResult:
    handle = await start(client, store, g, trigger, **options)
    return await handle.result()
```

Create `backend/tests/apps/worker/test_run_graph.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`RunGraph` end to end on the time-skipping test server (spec §6, §10 interpreter tests)."""

from typing import Any

from temporalio.client import WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer

from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.worker.harness import MemoryStore, run, start, workers
from tests.support.graphs import G, cel, ref, template

ECHO, IF, LOOP, FILTER = "testkit.echo@1", "flow.if@1", "flow.loop@1", "flow.filter@1"
SET, DELAY, STOP, FAIL = "flow.set_variables@1", "flow.delay@1", "flow.stop@1", "flow.fail@1"
TRANSFORM = "flow.transform@1"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "names": {"type": "array", "items": {"type": "string"}}},
    "required": ["x", "names"],
}
TRIGGER = {"x": 7, "names": ["ap-1", "sw-1", "ap-2"]}


def graph(*, outputs: dict[str, Any] | None = None) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, **({"outputs": outputs} if outputs else {})}
    return g


async def test_values_flow_from_the_trigger_through_steps_to_the_outputs(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"result": ref("steps.b.output.value")})
    g.node("a", ECHO, {"value": ref("trigger.x")})
    g.node("b", ECHO, {"value": template("x=", {"ref": "steps.a.output.value"})}).edge("a", "b")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert (result.status, result.outputs) == ("succeeded", {"result": "x=7"})


async def test_a_cel_branch_runs_one_side_and_projects_control_steps(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"side": cel("has(steps.yes.output) ? 'yes' : 'no'")})
    g.node("c", IF, {"condition": cel("trigger.x > 5")}).node("yes", ECHO, {"value": 1}).node("no", ECHO, {"value": 2})
    g.edge("c", "yes", "true").edge("c", "no", "false")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await handle.result()
    assert (result.status, result.outputs) == ("succeeded", {"side": "yes"})
    rows = {r.node_key: r for r in store.steps(handle.id)}
    assert rows["c"].status == "succeeded" and rows["c"].cel_mode == "activity"  # LOCAL_CEL_PROFILE is None
    assert "no" not in rows and store.runs[handle.id].status == "succeeded"


async def test_a_loop_collects_per_item_and_a_filter_keeps_matches(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"doubled": ref("steps.l.output.items"), "aps": ref("steps.f.output.items")})
    g.node("l", LOOP, {"items": [1, 2, 3], "concurrency": 2, "collect": cel("item * 2")}).node("x", ECHO)
    g.node("f", FILTER, {"items": ref("trigger.names"), "predicate": cel("item.startsWith('ap-')")})
    g.edge("l", "x", "body").edge("l", "f", "done")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await handle.result()
    assert result.outputs == {"doubled": [2, 4, 6], "aps": ["ap-1", "ap-2"]}
    assert result.iterations == 3 + 3  # three iterations, three filter items
    rows = [(r.node_key, r.iteration_key, r.status) for r in store.steps(handle.id)]
    assert sorted(rows) == [
        ("f", "", "succeeded"),
        ("l", "", "succeeded"),
        ("x", "l:0", "succeeded"),
        ("x", "l:1", "succeeded"),
        ("x", "l:2", "succeeded"),
    ]


async def test_variables_are_set_and_read(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"v": ref("vars.count")})
    g.settings["vars_schema"] = {"type": "object", "properties": {"count": {"type": "integer", "default": 0}}}
    g.node("s", SET, {"assignments": {"count": cel("trigger.x + 1")}})
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert result.outputs == {"v": 8}


async def test_retries_follow_the_manifest_and_each_attempt_is_projected(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("f", "testkit.fail_n@1", {"failures": 2})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        assert (await handle.result()).status == "succeeded"
    assert [(r.attempt, r.status, r.error_code) for r in store.steps(handle.id)] == [
        (1, "failed", "testkit.transient"),
        (2, "failed", "testkit.transient"),
        (3, "succeeded", None),
    ]


async def test_an_error_port_handles_a_fatal_failure(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"code": ref("steps.a.error.code", default="none")})
    g.node("a", "testkit.ambiguous_send@1", {"outcome": "rejected"}, on_error="port").node("h", ECHO, {"value": 1})
    g.edge("a", "h", "error")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert (result.status, result.outputs) == ("succeeded", {"code": "testkit.rejected"})


async def test_an_unknown_outcome_is_never_retried_and_fails_the_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("a", "testkit.ambiguous_send@1", {"outcome": "unknown"})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await handle.result()
    assert result.status == "failed" and result.error == {
        "code": "testkit.timeout_after_send",
        "message": "the request may have been delivered",
        "attempt": 1,
    }
    [row] = store.steps(handle.id)
    assert (row.attempt, row.outcome) == (1, "outcome_unknown")


async def test_a_reconcilable_step_finds_its_effect_before_retrying(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"found": ref("steps.r.output.found")}).node("r", "testkit.reconcile@1")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert result.outputs == {"found": True}


async def test_timers_are_durable_and_the_deadline_ends_the_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    day = graph().node("d", DELAY, {"duration_s": 86_400}).node("a", ECHO).edge("d", "a")
    long = graph().node("d", DELAY, {"duration_s": 3 * 86_400})
    async with workers(env.client, store):
        assert (await run(env.client, store, day, TRIGGER)).status == "succeeded"
        late = await run(env.client, store, long, TRIGGER, max_run_duration_s=86_400)
    assert (late.status, late.error and late.error["code"]) == ("deadline_exceeded", "deadline_exceeded")


async def test_stop_and_fail_end_the_run(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    stop = graph(outputs={"n": 1}).node("l", LOOP, {"items": [1, 2]}).node("s", STOP).edge("l", "s", "body")
    fail = graph().node("f", FAIL, {"message": "no, stop"})
    async with workers(env.client, store):
        stopped = await run(env.client, store, stop, TRIGGER)
        failed = await run(env.client, store, fail, TRIGGER)
    assert (stopped.status, stopped.outputs) == ("succeeded", {"n": 1})
    assert failed.status == "failed" and failed.error and failed.error["code"] == "workflow_failed"


async def test_simulation_calls_simulate_and_records_it(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"v": ref("steps.a.output.value")}).node("a", ECHO, {"value": 5})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER, mode="simulate")
        result = await handle.result()
    assert result.outputs == {"v": {"simulated": 5}}
    assert [r.outcome for r in store.steps(handle.id)] == ["simulated"]


async def test_without_an_evaluator_cel_fails_as_profile_unavailable(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("t", TRANSFORM, {"fields": {"y": cel("trigger.x * 2")}}, on_error="continue")
    g.settings["outputs"] = {"error": ref("steps.t.error", default="none")}
    async with workers(env.client, store, evaluate=None):
        # the test server doesn't skip schedule-to-start time: a real 2 s stands in for the 10 minutes
        result = await run(env.client, store, g, TRIGGER, cel_schedule_to_start_s=2)
    message = f"No evaluator served `{CURRENT_CEL_PROFILE}` (TimeoutError)."  # never the transport's own text
    assert result.outputs == {"error": {"code": "cel_profile_unavailable", "message": message, "attempt": 1}}


async def test_sensitive_outputs_are_redacted_in_the_projection(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("s", "testkit.sensitive@1")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await handle.result()
    [row] = store.steps(handle.id)
    assert row.output_preview == {
        "public": "visible",
        "secret_value": "[redacted]",
        "login": {"user": "ops", "password": "[redacted]"},
    }


async def test_a_recorded_history_replays(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(outputs={"doubled": ref("steps.l.output.items", default=[])})
    g.node("c", IF, {"condition": cel("trigger.x > 5")}).node("l", LOOP, {"items": [1, 2], "collect": cel("item + 1")})
    g.node("x", ECHO, {"value": ref("item")}).edge("c", "l", "true").edge("l", "x", "body")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await handle.result()
        history = await handle.fetch_history()
    await Replayer(workflows=[RunGraph]).replay_workflow(WorkflowHistory.from_json(handle.id, history.to_json()))
```

Create `backend/tests/apps/worker/test_run_graph_policies.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`RunGraph`: every node kind, every error policy, the limits it enforces, and how a run can end (spec §6, §10)."""

import asyncio
import dataclasses
import uuid
from datetime import timedelta
from typing import Any

import pytest
from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner

from dewpoint.engine.graph.validate import SubflowInfo
from dewpoint.engine.runtime import nodes
from dewpoint.engine.runtime.activities import CEL_EVALUATE, ENGINE_QUEUE, PROJECT, ProjectInput, RunInput
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.worker.harness import TENANT, MemoryStore, run, start, workers
from tests.support.graphs import G, cel, ref, template
from tests.support.plugins.testkit import SlowSend

ECHO, LOOP, SWITCH = "testkit.echo@1", "flow.loop@1", "flow.switch@1"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "open": {"type": "object"}},
    "required": ["x", "open"],
}
TRIGGER: dict[str, Any] = {"x": 7, "open": {}}


def graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


async def test_a_switch_takes_its_first_matching_case(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    cases = [{"port": "small", "when": cel("trigger.x < 5")}, {"port": "big", "when": cel("trigger.x > 5")}]
    g = graph(taken=cel("has(steps.b.output) ? 'big' : 'other'")).node("s", SWITCH, {"cases": cases})
    g.node("a", ECHO).node("b", ECHO).node("d", ECHO).edge("s", "a", "small").edge("s", "b", "big")
    g.edge("s", "d", "default")
    async with workers(env.client, store):
        assert (await run(env.client, store, g, TRIGGER)).outputs == {"taken": "big"}


async def test_wait_until_waits_durably_then_transform_shapes_values(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    until = (await env.get_current_time() + timedelta(days=2)).isoformat()  # the server's clock, not the host's
    g = graph(t=ref("steps.t.output")).node("w", "flow.wait_until@1", {"until": until})
    g.node("t", "flow.transform@1", {"fields": {"double": cel("trigger.x * 2"), "label": "fixed"}}).edge("w", "t")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await handle.result()
        info = await handle.describe()
    assert result.outputs == {"t": {"double": 14, "label": "fixed"}}
    assert info.close_time and info.close_time - info.start_time >= timedelta(days=2)


def failing_loop(on_item_error: str) -> G:
    g = graph(out=ref("steps.l.output", default=None))
    config = {"items": [0, 1, 2], "on_item_error": on_item_error, "collect": ref("item")}
    g.node("l", LOOP, config).node("f", "testkit.ambiguous_send@1", {"outcome": cel("item == 1 ? 'rejected' : 'sent'")})
    return g.edge("l", "f", "body")


async def test_continue_records_failed_items_and_stop_fails_the_loop(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    async with workers(env.client, store):
        kept = await run(env.client, store, failing_loop("continue"), TRIGGER)
        stopped = await run(env.client, store, failing_loop("stop"), TRIGGER)
    assert kept.outputs == {
        "out": {
            "items": [0, None, 2],
            "failures": [{"index": 1, "code": "testkit.rejected", "message": "the receiver rejected the request"}],
            "count": 3,
        }
    }
    assert stopped.status == "failed" and stopped.error and stopped.error["code"] == "testkit.rejected"


@pytest.mark.parametrize(
    ("config", "code"),
    [
        ({"items": list(range(101))}, "not_supported"),  # batches arrive with 2a-3b
        ({"items": [1, 2, 3], "item_cap": 2}, "item_cap_exceeded"),
    ],
)
async def test_loop_limits_fail_the_loop(env: WorkflowEnvironment, config: dict[str, Any], code: str) -> None:
    store = MemoryStore()
    g = graph(code=ref("steps.l.error.code", default="none")).node("l", LOOP, config, on_error="continue")
    g.node("x", ECHO).edge("l", "x", "body")
    async with workers(env.client, store):
        assert (await run(env.client, store, g, TRIGGER)).outputs == {"code": code}


async def test_sub_flows_are_not_supported_yet(env: WorkflowEnvironment) -> None:
    child = uuid.uuid4()
    store = MemoryStore(subflows={child: SubflowInfo(child, uuid.uuid4(), {"type": "object"}, {"type": "object"})})
    g = graph(code=ref("steps.r.error.code", default="none"))
    g.node("r", "flow.run_workflow@1", {"workflow_id": str(child)}, on_error="continue")
    async with workers(env.client, store):
        assert (await run(env.client, store, g, TRIGGER)).outputs == {"code": "not_supported"}


async def test_a_failing_collect_fails_its_iteration(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(out=ref("steps.l.output.failures", default=None))
    g.node("l", LOOP, {"items": [1, 0], "on_item_error": "continue", "collect": cel("10 / item")}).node("x", ECHO)
    g.edge("l", "x", "body")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert [(f["index"], f["code"]) for f in result.outputs["out"]] == [(1, "evaluation_error")]  # type: ignore[index]


async def test_a_default_covers_a_missing_value_and_a_failed_expression_fails_the_step(
    env: WorkflowEnvironment,
) -> None:
    store = MemoryStore()
    g = graph(a=ref("steps.a.output.value", default="?"), b=ref("steps.b.error.code", default="none"))
    g.node("a", ECHO, {"value": ref("trigger.open.nothing", default="fallback")})
    g.node("b", ECHO, {"value": cel("trigger.open.nothing")}, on_error="continue")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await handle.result()
    assert result.outputs == {"a": "fallback", "b": "evaluation_error"}
    rows = {r.node_key: r for r in store.steps(handle.id)}  # b never reached its activity, and still has its row
    assert (rows["b"].attempt, rows["b"].status, rows["b"].error_code) == (1, "failed", "evaluation_error")


async def test_after_continue_a_guard_sees_no_output(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    seen = cel("has(steps.a.output) ? 'output' : has(steps.a.error) ? steps.a.error.code : 'nothing'")
    g = graph(seen=seen, v=ref("steps.a.output", default="d"))
    g.node("a", "testkit.ambiguous_send@1", {"outcome": "rejected"}, on_error="continue")
    async with workers(env.client, store):
        result = await run(env.client, store, g, TRIGGER)
    assert result.outputs == {"seen": "testkit.rejected", "v": "d"}


async def test_at_most_a_hundred_steps_are_in_flight(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph()
    for i in range(105):
        g.node(f"e{i}", ECHO, {"value": i})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await handle.result()
        history = await handle.fetch_history()
    before_first_completion = 0
    for event in history.events:
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            break
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            before_first_completion += event.activity_task_scheduled_event_attributes.activity_type.name != PROJECT
    assert before_first_completion == 100  # steps; the one projection of their running rows is outside the cap


class SlowStore(MemoryStore):
    async def project(self, data: ProjectInput) -> None:
        await asyncio.sleep(0.5)  # a slow database
        await super().project(data)


async def test_one_projection_is_outstanding_at_a_time(env: WorkflowEnvironment) -> None:
    """Projections count toward the history an execution can add while it drains (spec §6): rows that settle while
    one is outstanding wait for it, and go in the next."""
    store = SlowStore()
    g = graph()
    for i in range(4):  # branches ending 0.3 s apart: each transform settles while the last projection runs
        g.node(f"e{i}", "testkit.slow@1", {"seconds": 0.3 * i}).node(f"t{i}", "flow.transform@1", {"fields": {"i": i}})
        g.edge(f"e{i}", f"t{i}")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await handle.result()
        history = await handle.fetch_history()
    outstanding: set[int] = set()
    most = 0
    for event in history.events:
        if event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
            if event.activity_task_scheduled_event_attributes.activity_type.name == PROJECT:
                outstanding.add(event.event_id)
                most = max(most, len(outstanding))
        elif event.event_type == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
            outstanding.discard(event.activity_task_completed_event_attributes.scheduled_event_id)
    assert most == 1
    assert sorted(r.node_key for r in store.steps(handle.id)) == sorted(f"{k}{i}" for k in "et" for i in range(4))


async def test_the_deadline_cancels_running_work(own_env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("s", "testkit.slow@1", {"seconds": 30})
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, TRIGGER, max_run_duration_s=2)
        result = await handle.result()
    assert result.status == "deadline_exceeded"
    [row] = store.steps(handle.id)
    assert row.status == "cancelled"
    assert store.runs[handle.id].status == "deadline_exceeded"


async def test_a_cancelled_run_projects_its_end(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("d", "flow.delay@1", {"duration_s": 3600})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.sleep(0.2)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await handle.result()
    assert store.runs[handle.id].status == "cancelled"


async def test_a_version_this_build_cannot_run_fails_the_run(env: WorkflowEnvironment) -> None:
    """A version whose node types this build lacks (or that no longer loads): the run fails, and says so."""
    store = MemoryStore()
    version_id = store.add(graph().node("a", ECHO))
    store.versions[version_id] = dataclasses.replace(store.versions[version_id], manifests={})
    run_id = str(uuid.uuid4())
    async with workers(env.client, store):
        handle = await env.client.start_workflow(
            RunGraph.run, RunInput(TENANT, run_id, version_id, TRIGGER), id=run_id, task_queue=ENGINE_QUEUE
        )
        result = await asyncio.wait_for(handle.result(), 10)
    assert result.status == "failed" and result.error and result.error["code"] == "version_unusable"
    assert (store.runs[run_id].status, store.runs[run_id].error_code) == ("failed", "version_unusable")
    message = "This build can't run the version (ProgramError); the worker's log has the details."  # no raw text
    assert (result.error["message"], store.runs[run_id].error_message) == (message, message)
    assert store.steps(run_id) == []  # nothing ran


async def test_a_bug_fails_the_run_instead_of_leaving_it_running(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exception in workflow code would fail the workflow task, which Temporal retries forever: the run would
    hang, still `running` in the projection."""

    def broken(ref: str, config: Any) -> nodes.Decision:
        raise RuntimeError("a bug in a control node")

    monkeypatch.setattr(nodes, "decide", broken)  # the sandbox runs its own copy: this test runs outside it
    store = MemoryStore()
    g = graph().node("a", ECHO).node("t", "flow.transform@1", {"fields": {"y": 1}}).edge("a", "t")
    async with workers(env.client, store, runner=UnsandboxedWorkflowRunner()):
        handle = await start(env.client, store, g, TRIGGER)
        result = await asyncio.wait_for(handle.result(), 10)
    message = "The interpreter failed (RuntimeError); the worker's log has the details."  # never the raw text
    assert result.error == {"code": "internal_error", "message": message, "attempt": 1}
    assert store.runs[handle.id].status == "failed" and [r.status for r in store.steps(handle.id)] == ["succeeded"]


async def test_a_trigger_that_breaks_its_schema_fails_a_step_not_the_workflow(env: WorkflowEnvironment) -> None:
    """2a doesn't validate trigger payloads (2b does). Publish trusted the schema; the run must fail visibly."""
    store = MemoryStore()
    g = graph(v=ref("steps.b.output.value", default="none"))
    g.node("a", ECHO, {"value": ref("trigger.x")}).node("b", ECHO, {"value": cel("trigger.x + 1")}, on_error="continue")
    async with workers(env.client, store):
        missing = await run(env.client, store, g, {"open": {}})
        wrong = await run(env.client, store, g, {"x": "seven", "open": {}})
    assert (missing.status, missing.error and missing.error["code"]) == ("failed", "evaluation_error")
    assert (wrong.status, wrong.outputs) == ("succeeded", {"v": "none"})  # b failed and continued


async def test_a_node_type_this_worker_does_not_serve_fails_its_step(env: WorkflowEnvironment) -> None:
    """The registry lists it, but this worker's plugins don't (a build without the plugin): no hang."""
    store = MemoryStore()
    g = graph(code=ref("steps.a.error.code", default="none")).node("a", ECHO, on_error="continue")
    g.nodes[0]["options"]["max_attempts"] = 2
    async with workers(env.client, store, plugins=()):
        result = await asyncio.wait_for(run(env.client, store, g, TRIGGER), 30)
    assert result.status == "succeeded" and result.outputs == {"code": "node_type_unavailable"}


async def test_a_worker_without_the_run_in_its_cache_replays_it_and_carries_on(env: WorkflowEnvironment) -> None:
    """A restart or a cache eviction mid-run: the next workflow task replays the whole history first. With no cache,
    every task does, so any non-determinism in the interpreter fails this run."""
    store = MemoryStore()
    g = graph(doubled=ref("steps.l.output.items", default=[]), side=cel("has(steps.yes.output) ? 'yes' : 'no'"))
    g.node("c", "flow.if@1", {"condition": cel("trigger.x > 5")}).node("yes", ECHO).node("no", ECHO)
    g.node("l", LOOP, {"items": [1, 2, 3], "concurrency": 2, "collect": cel("item * 2")})
    g.node("x", ECHO, {"value": ref("item")}).node("d", "flow.delay@1", {"duration_s": 3600})
    g.edge("c", "yes", "true").edge("c", "no", "false").edge("yes", "l").edge("l", "x", "body").edge("l", "d", "done")
    async with workers(env.client, store, cache=0):
        result = await run(env.client, store, g, TRIGGER)
    assert result.outputs == {"doubled": [2, 4, 6], "side": "yes"}


async def test_a_timeout_after_an_ambiguous_send_is_never_retried(own_env: WorkflowEnvironment) -> None:
    """Review finding: a start-to-close timeout (or a lost worker) never reaches the node's own error mapping. The
    send may have happened, so an ambiguous node's timed-out attempt is `outcome_unknown` and never repeated."""
    store = MemoryStore()
    g = graph().node("s", "testkit.slow_send@1", {"seconds": 3})
    g.nodes[0]["options"].update(timeout_s=1, max_attempts=3)
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, TRIGGER)
        result = await handle.result()
    assert SlowSend.sent.count(handle.id) == 1
    assert result.status == "failed" and result.error and result.error["code"] == "timeout"
    [row] = store.steps(handle.id)
    assert (row.attempt, row.status, row.error_code, row.outcome) == (1, "failed", "timeout", "outcome_unknown")


async def test_a_timeout_is_retried_when_repeating_is_safe(own_env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph().node("s", "testkit.slow@1", {"seconds": 3})
    g.nodes[0]["options"].update(timeout_s=1, max_attempts=2)
    async with workers(own_env.client, store):
        handle = await start(own_env.client, store, g, TRIGGER)
        await handle.result()
    assert [(r.attempt, r.status, r.error_code, r.outcome) for r in store.steps(handle.id)] == [
        (1, "failed", "timeout", None),
        (2, "failed", "timeout", None),
    ]


class FlakyStore(MemoryStore):
    """A database that refuses the first `down` writes."""

    down = 3

    async def project(self, data: ProjectInput) -> None:
        if self.down:
            self.down -= 1
            raise ConnectionError("the database went away")
        await super().project(data)


async def test_a_database_outage_never_repeats_an_effect_and_the_rows_catch_up(env: WorkflowEnvironment) -> None:
    """Review finding: rows are written by the projection alone, which retries on its own. A step's effect runs
    once, and no row is left `running` once the database is back."""
    store = FlakyStore()
    g = graph().node("s", "testkit.slow_send@1", {"seconds": 0}).node("t", "flow.transform@1", {"fields": {"n": 1}})
    g.edge("s", "t")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await handle.result()
    assert result.status == "succeeded" and SlowSend.sent.count(handle.id) == 1 and store.down == 0
    assert [(r.node_key, r.status) for r in store.steps(handle.id)] == [("s", "succeeded"), ("t", "succeeded")]
    assert store.runs[handle.id].status == "succeeded"


async def test_sensitive_values_never_reach_the_projection(env: WorkflowEnvironment) -> None:
    """Review finding: a nested model's sensitive field sits behind `$ref`, and control steps, templates, plugin inputs
    and messages can all copy a sensitive value into a place no schema marks."""
    store = MemoryStore()
    secret, password = ref("steps.s.output.secret_value"), ref("steps.s.output.login.password")
    g = graph().node("s", "testkit.sensitive@1")
    line = template("key=", {"ref": "steps.s.output.secret_value"})
    g.node("t", "flow.transform@1", {"fields": {"copy": secret, "line": line}})
    g.node("e", ECHO, {"value": password}).node(
        "p", "testkit.ambiguous_send@1", {"outcome": "rejected", "detail": secret}, on_error="continue"
    )
    g.node("f", "flow.fail@1", {"message": template("gave up on ", {"ref": "steps.s.output.login.password"})})
    lookup = cel("{'a': 1}[steps.s.output.secret_value] > 0")  # CEL's message quotes the missing key
    g.node("k", "flow.transform@1", {"fields": {"n": lookup}}, on_error="continue").edge("s", "k").edge("k", "f")
    g.edge("s", "t").edge("s", "e").edge("s", "p").edge("t", "f").edge("e", "f").edge("p", "f")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        result = await handle.result()
    rows = {r.node_key: r for r in store.steps(handle.id)}
    assert rows["s"].output_preview == {
        "public": "visible",
        "secret_value": "[redacted]",
        "login": {"user": "ops", "password": "[redacted]"},
    }
    assert rows["t"].output_preview == {"copy": "[redacted]", "line": "key=[redacted]"}
    assert (rows["e"].input_preview, rows["e"].output_preview) == ({"value": "[redacted]"}, {"value": "[redacted]"})
    assert rows["p"].error_message == "the receiver rejected the request: [redacted]"
    assert rows["f"].error_message == "gave up on [redacted]"
    assert rows["k"].error_message == 'NOT_FOUND: Key not found in map : "[redacted]"'
    assert store.runs[handle.id].error_message == "gave up on [redacted]"
    assert result.error and result.error["message"] == "gave up on [redacted]"
    dump = repr(store.rows) + repr(store.runs)
    assert "s3cr3t-value" not in dump and "pa55word" not in dump


async def test_a_sensitive_trigger_field_is_masked_where_it_is_copied(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    g = graph(key=ref("trigger.api_key"))
    g.settings["input_schema"] = {
        "type": "object",
        "properties": {"api_key": {"type": "string", "x-sensitive": True}},
        "required": ["api_key"],
    }
    g.node("e", ECHO, {"value": template("Bearer ", {"ref": "trigger.api_key"})})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"api_key": "k3y-k3y-k3y"})
        result = await handle.result()
    [row] = store.steps(handle.id)
    assert (row.input_preview, row.output_preview) == ({"value": "Bearer [redacted]"}, {"value": "Bearer [redacted]"})
    assert result.outputs == {"key": "k3y-k3y-k3y"}  # the workflow's own outputs are its contract, not a preview


async def test_a_sensitive_config_value_is_masked_where_it_is_copied_or_echoed(env: WorkflowEnvironment) -> None:
    """Review finding: a node's `x-sensitive` config field is redacted in its own input preview, but a control step
    can copy the same literal, and the node can echo it in its error. Literals are learned when the run starts;
    a value that only the config marks sensitive (here from an unmarked trigger field), before its attempt."""
    store = MemoryStore()
    token, passed = "tok-hunter22", "tok-from-trigger"
    g = graph().node("t", "flow.transform@1", {"fields": {"copy": token}})
    g.node("p", "testkit.ambiguous_send@1", {"outcome": "rejected", "token": token}, on_error="continue")
    echo = {"outcome": "rejected", "token": ref("trigger.open.tok", default="")}
    g.node("q", "testkit.ambiguous_send@1", echo, on_error="continue").edge("t", "p").edge("t", "q")
    async with workers(env.client, store):
        handle = await start(env.client, store, g, {"x": 7, "open": {"tok": passed}})
        await handle.result()
    rows = {r.node_key: r for r in store.steps(handle.id)}
    assert rows["t"].output_preview == {"copy": "[redacted]"}  # projected before `p` ran
    assert rows["p"].input_preview == {"outcome": "rejected", "token": "[redacted]"}
    assert rows["p"].error_message == rows["q"].error_message == "the receiver rejected the request for [redacted]"
    assert token not in repr(store.rows) + repr(store.runs) and passed not in repr(store.rows) + repr(store.runs)


async def output_evaluation_started(handle: Any) -> None:
    """Wait until the run is evaluating its outputs: their `cel.evaluate` is scheduled."""
    while True:
        for event in (await handle.fetch_history()).events:
            if event.HasField("activity_task_scheduled_event_attributes"):
                if event.activity_task_scheduled_event_attributes.activity_type.name == CEL_EVALUATE:
                    return
        await asyncio.sleep(0.05)


async def test_a_cancel_while_the_outputs_are_evaluated_projects_cancelled(env: WorkflowEnvironment) -> None:
    """Checkpoint-2 finding: the outputs were evaluated outside the run's cancellation handler, so a cancel then
    closed the workflow with nothing projected: the run stayed `running`."""
    store = MemoryStore()
    g = graph(n=cel("trigger.x + 1")).node("a", ECHO)
    async with workers(env.client, store, evaluate=None):  # no evaluator: the output's CEL waits for one
        handle = await start(env.client, store, g, TRIGGER, cel_schedule_to_start_s=60)
        await asyncio.wait_for(output_evaluation_started(handle), 10)
        await handle.cancel()
        with pytest.raises(WorkflowFailureError):
            await asyncio.wait_for(handle.result(), 10)
    assert store.runs[handle.id].status == "cancelled"


async def test_the_deadline_holds_while_the_outputs_are_evaluated(env: WorkflowEnvironment) -> None:
    """Checkpoint-2 finding: past the deadline, a run waited on its outputs' evaluator and ended as its failure."""
    store = MemoryStore()
    g = graph(n=cel("trigger.x + 1")).node("a", ECHO)
    async with workers(env.client, store, evaluate=None):
        handle = await start(env.client, store, g, TRIGGER, max_run_duration_s=1, cel_schedule_to_start_s=5)
        result = await asyncio.wait_for(handle.result(), 10)
    assert (result.status, result.error and result.error["code"]) == ("deadline_exceeded", "deadline_exceeded")
    assert store.runs[handle.id].status == "deadline_exceeded"


async def test_a_damaged_output_fails_the_run_as_unusable(env: WorkflowEnvironment) -> None:
    store = MemoryStore()
    version_id = store.add(graph(n=ref("trigger.x")).node("a", ECHO))
    damaged = {**store.versions[version_id].graph}
    damaged["settings"] = {**damaged["settings"], "outputs": {"n": {"$value": {"kind": "ref", "path": 5}}}}
    store.versions[version_id] = dataclasses.replace(store.versions[version_id], graph=damaged)
    run_id = str(uuid.uuid4())
    async with workers(env.client, store):
        handle = await env.client.start_workflow(
            RunGraph.run, RunInput(TENANT, run_id, version_id, TRIGGER), id=run_id, task_queue=ENGINE_QUEUE
        )
        result = await asyncio.wait_for(handle.result(), 10)
    assert result.error and result.error["code"] == "version_unusable" and store.steps(run_id) == []


class HeldStore(MemoryStore):
    """Holds the run's summary write open until the test lets it go: a cancel can arrive in between."""

    def __init__(self) -> None:
        super().__init__()
        self.writing, self.release = asyncio.Event(), asyncio.Event()

    async def project(self, data: ProjectInput) -> None:
        if data.run is not None and not self.writing.is_set():
            self.writing.set()
            await self.release.wait()
        await super().project(data)


async def test_a_cancel_after_the_run_concluded_leaves_its_outcome(env: WorkflowEnvironment) -> None:
    """A cancel that arrives while the run's end is being written can't unmake that end: the write is repeated and
    the run's own result stands, so the projection and Temporal agree."""
    store = HeldStore()
    g = graph(v=ref("steps.a.output.value")).node("a", ECHO, {"value": 1})
    async with workers(env.client, store):
        handle = await start(env.client, store, g, TRIGGER)
        await asyncio.wait_for(store.writing.wait(), 10)
        await handle.cancel()
        store.release.set()
        result = await asyncio.wait_for(handle.result(), 10)
    assert (result.status, result.outputs, store.runs[handle.id].status) == ("succeeded", {"v": 1}, "succeeded")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_run_graph.py tests/apps/worker/test_run_graph_policies.py`
Expected: 2 collection errors, `ModuleNotFoundError: No module named 'dewpoint.engine.runtime.workflow'`.

- [ ] **Step 3: Implement `RunGraph`**

Create `backend/src/dewpoint/engine/runtime/workflow.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`RunGraph` (spec §6): loads the pinned version, then drives the scheduler until the run ends. Each ready step runs
as one future: its values are resolved (CEL inline or through `cel.evaluate`), then a control node decides in the
workflow, or a plugin step runs as its activity. At most IN_FLIGHT_CAP futures are outstanding, plus one projection;
completions are applied in (scope, topological) order, so a replay applies them the same way. Nothing else creates
concurrency."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, TimeoutError
from temporalio.exceptions import CancelledError as ActivityCancelled

with workflow.unsafe.imports_passed_through():
    from dewpoint.engine.cel import evaluate as cel
    from dewpoint.engine.cel.profile import LOCAL_CEL_PROFILE
    from dewpoint.engine.cel.route import YieldBudget
    from dewpoint.engine.graph.values import CelValue, RefValue, TemplateValue, iter_values, pointer_str
    from dewpoint.engine.runtime import nodes, resolve
    from dewpoint.engine.runtime.activities import (
        CEL_EVALUATE,
        LOAD_VERSION,
        OUTCOME_UNKNOWN,
        PROJECT,
        CelInput,
        CelResult,
        LoadVersionInput,
        ProjectInput,
        RunInput,
        RunResult,
        RunSummary,
        StepInput,
        StepResult,
        StepRow,
        VersionData,
        cel_queue,
        step_activity,
    )
    from dewpoint.engine.runtime.program import Step, compile_program
    from dewpoint.engine.runtime.projection import Secrets, mask, preview, remember, sensitive_values
    from dewpoint.engine.runtime.scheduler import (
        ITERATION_CAP_EXCEEDED,
        Collect,
        Failure,
        Instance,
        RunEnd,
        Scheduler,
        ScopeKey,
        iteration_key,
    )

IN_FLIGHT_CAP = 100  # activities and child workflows outstanding per execution (spec §6)
CEL_BATCH = 1_000  # binding sets per cel.evaluate request
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


def _attempt_failed(
    error: ActivityError, key: str, attempt: int, *, ambiguous: bool, non_retryable: Sequence[str]
) -> tuple[Failure, str | None, bool]:
    """How one attempt failed: (the failure, its outcome, whether another attempt may follow)."""
    cause = error.cause
    if isinstance(cause, ApplicationError) and cause.type == "NotFoundError":  # the SDK: no such activity here
        return Failure(NODE_TYPE_UNAVAILABLE, f"No worker of this build runs `{key}`'s node type.", attempt), None, True
    if isinstance(cause, ApplicationError):  # the node's own error, mapped by the activity
        details = cause.details[0] if cause.details and isinstance(cause.details[0], dict) else {}
        code = cause.type or "error"
        retryable = not cause.non_retryable and code not in non_retryable
        return Failure(code, cause.message, attempt), details.get("outcome"), retryable
    # A timeout or a lost worker: the node may have done its work, and it never saw the error to map it.
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


def _backoff(retry: Mapping[str, Any], attempt: int) -> float:
    """Seconds before attempt `attempt + 1`, from the manifest's retry settings."""
    delay = float(retry["initial_interval_s"]) * float(retry["backoff"]) ** (attempt - 1)
    return min(delay, float(retry["max_interval_s"]))


@workflow.defn(name="RunGraph")
class RunGraph:
    def __init__(self) -> None:
        self._budget = YieldBudget()
        self._rows: dict[tuple[str, str, int], StepRow] = {}  # queued for the next projection, per attempt
        self._secrets: Secrets = ()  # sensitive values seen so far: masked in everything projected
        self._started: dict[Instance, str] = {}
        self._cel_modes: dict[Instance, str] = {}
        self._projects = 0

    @workflow.run
    async def run(self, start: RunInput) -> RunResult:
        """Every way a run ends is projected. Python exceptions in workflow code would fail the workflow task, which
        Temporal retries forever: the run would hang, `running` in the projection. So a version this build can't
        load or compile fails the run (`version_unusable`) before any step runs, and any other exception fails it
        (`internal_error`). The workflow's outputs are evaluated under the same deadline and handlers as its steps:
        a cancel or the deadline while they're computed ends the run as it would anywhere else."""
        self.input = start
        self.started_at = workflow.info().start_time
        try:
            data = await workflow.execute_local_activity(
                LOAD_VERSION,
                LoadVersionInput(start.tenant_id, start.version_id),
                result_type=VersionData,
                start_to_close_timeout=timedelta(seconds=30),
            )
            self.program = compile_program(data.graph, data.manifests, data.expressions, data.cel_profile)
        except asyncio.CancelledError:
            await self._end_early(RunEnd("cancelled", CANCELLED))
            raise
        except Exception as e:  # its text may quote the version: the log has it, the projection names the type
            workflow.logger.error("run_version_unusable", exc_info=True)
            message = f"This build can't run the version ({type(e).__name__}); the worker's log has the details."
            return await self._end_early(RunEnd("failed", Failure(VERSION_UNUSABLE, message)))
        self.sched = Scheduler(self.program)
        deadline = self.started_at + timedelta(seconds=start.max_run_duration_s)
        outputs: dict[str, Any] | None = None
        try:
            self._prepare(start)
            await self._drive(deadline)
            end = self.sched.ended or RunEnd("failed", Failure("error", "The run ended without a result."))
            if end.status == "succeeded":
                end, outputs = await self._outputs_by(deadline, end)
        except asyncio.CancelledError:
            self.sched.end(RunEnd("cancelled", CANCELLED))
            await self._finish(RunEnd("cancelled", CANCELLED))
            raise
        except Exception as e:  # a bug: the text may quote run data, so it goes to the log, not the projection
            workflow.logger.error("run_internal_error", exc_info=True)
            message = f"The interpreter failed ({type(e).__name__}); the worker's log has the details."
            end, outputs = RunEnd("failed", Failure(INTERNAL_ERROR, message)), None
        return await self._finish(end, outputs)

    def _prepare(self, start: RunInput) -> None:
        """What the run knows before its first step: the sensitive values it can see already, and its variables."""
        self._learn(start.trigger, self.program.graph.settings.input_schema)
        for step in self.program.steps.values():  # sensitive literals in plugin configs: masked from the start
            if not step.control:
                self._learn(resolve.assemble(step.config, {}), self.program.manifests[step.ref]["config_schema"])
        schema = self.program.graph.settings.vars_schema
        self.vars = {k: p.get("default") for k, p in sorted(schema.get("properties", {}).items())}

    # --- the scheduler loop ----------------------------------------------------------------------------------------

    async def _drive(self, deadline: datetime) -> None:
        self.sched.start()
        tasks: dict[tuple[Any, ...], asyncio.Task[_Effect | None]] = {}
        waiting: list[tuple[Any, ...]] = []
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (deadline - workflow.now()).total_seconds())))
        try:
            while self.sched.ended is None:
                waiting += [("step", i) for i in self.sched.take_ready()]
                waiting += [("collect", c) for c in self.sched.take_collects()]
                for inst in self.sched.take_cancels():
                    task = tasks.pop(("step", inst), None)
                    if task is not None:
                        task.cancel()
                waiting = [w for w in waiting if not self._gone(w)]
                waiting.sort(key=self._rank)
                while waiting and len(tasks) < IN_FLIGHT_CAP:
                    unit = waiting.pop(0)
                    tasks[unit] = asyncio.create_task(self._unit(unit))
                self._queue_settled()
                if self._rows and not any(key[0] == "project" for key in tasks):  # one at a time: rows wait for it
                    rows, self._rows = list(self._rows.values()), {}
                    self._projects += 1
                    tasks[("project", self._projects)] = asyncio.create_task(self._project(rows))
                if self.sched.ended is not None:
                    break
                if not tasks:
                    raise RuntimeError("nothing is running and the run hasn't ended")
                done, _ = await workflow.wait([*tasks.values(), clock], return_when=asyncio.FIRST_COMPLETED)
                self._budget.reset()
                if clock in done:
                    self.sched.end(
                        RunEnd(DEADLINE_EXCEEDED, Failure(DEADLINE_EXCEEDED, "The run passed its deadline."))
                    )
                    break
                for key in sorted((k for k, t in tasks.items() if t in done), key=self._rank):
                    effect = tasks.pop(key).result()
                    if effect is not None:
                        self._apply(key, effect)
        finally:
            clock.cancel()
            for key, task in tasks.items():
                if key[0] != "project":
                    task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    def _rank(self, key: tuple[Any, ...]) -> tuple[Any, ...]:
        if key[0] == "step":
            return (self.sched.order(key[1]), 0)
        if key[0] == "collect":
            c: Collect = key[1]
            return (self.sched.order(Instance(c.scope, c.loop.step)), 1)
        return ((), 2, key[1])

    def _gone(self, unit: tuple[Any, ...]) -> bool:
        """A queued step or collect whose scope has ended since: it never starts."""
        scope = self.sched.scopes.get(unit[1].scope)
        return scope is None or scope.failure is not None

    async def _unit(self, key: tuple[Any, ...]) -> _Effect | None:
        if key[0] == "step":
            self._started[key[1]] = workflow.now().isoformat()
            return await self._step(key[1])
        return await self._collect(key[1])

    def _apply(self, key: tuple[Any, ...], effect: _Effect) -> None:
        if key[0] == "collect":
            c: Collect = key[1]
            if effect.failure is not None:
                self.sched.collect_failed(c.loop, c.index, effect.failure)
            else:
                self.sched.collected(c.loop, c.index, effect.collected)
            return
        inst: Instance = key[1]
        if effect.cel_mode is not None:
            self._cel_modes[inst] = effect.cel_mode
        if effect.loop is not None:
            self.sched.open_loop(
                inst, effect.loop.items, concurrency=effect.loop.concurrency, stop_on_error=effect.loop.stop_on_error
            )
        elif effect.end is not None:
            self.sched.finish(inst, effect.end, effect.output)
        elif effect.failure is not None:
            self.sched.fail(inst, effect.failure)
        else:
            if effect.variables:
                self.vars.update(effect.variables)
            self.sched.succeed(inst, effect.output, effect.ports)

    # --- the projection -------------------------------------------------------------------------------------------

    def _queue(self, row: StepRow) -> None:
        """Queue a row for the next projection. A later row of the same attempt replaces it."""
        self._rows[(row.step_id, row.iteration_key, row.attempt)] = row

    def _learn(self, value: Any, schema: Mapping[str, Any] | None) -> None:
        self._secrets = remember(self._secrets, sensitive_values(value, schema))

    def _preview(self, value: Any, schema: Mapping[str, Any] | None = None) -> Any:
        return preview(value, schema, self._secrets)

    def _queue_settled(self) -> None:
        """Control steps that settled since the last call. Plugin steps queue their own attempts (`_activity`)."""
        now = workflow.now().isoformat()
        for inst in self.sched.take_settled():
            step = self.sched.step(inst)
            if not step.control:
                continue
            result = self.sched.scopes[inst.scope].results.get(step.key, {})
            error = result.get("error")
            self._queue(
                StepRow(
                    run_id=self.input.run_id,
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

    # --- values ----------------------------------------------------------------------------------------------------

    def _view(self, scope: ScopeKey, item: tuple[Any, int] | None = None) -> Any:
        run = {
            "id": self.input.run_id,
            "started_at": self.started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "now": workflow.now().astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        return resolve.view(
            self.sched, scope, trigger=self.input.trigger, variables=dict(self.vars), run=run, item=item
        )

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
            if self._budget.must_yield(task.record):
                await asyncio.sleep(0.001)  # a durable timer: the workflow task ends here (spec §5.6)
                self._budget.reset()
            outcomes = task.run_local()
            for _ in outcomes:
                self._budget.charge(task.record)
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
                    schedule_to_start_timeout=timedelta(seconds=self.input.cel_schedule_to_start_s),
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
        if not self.sched.debit(len(items)):
            return _Effect(failure=Failure(ITERATION_CAP_EXCEEDED, "This run reached its limit of loop iterations."))
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
        return _Effect(collected=resolve.assemble({"collect": collect}, values)["collect"])

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
                run_id=self.input.run_id,
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
                        tenant_id=self.input.tenant_id,
                        run_id=self.input.run_id,
                        step_id=str(step.id),
                        node_key=step.key,
                        iteration_key=iteration_key(inst.scope),
                        ref=step.ref,
                        config=config,
                        mode=self.input.mode,
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
                run_id=self.input.run_id,
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

    # --- the end ---------------------------------------------------------------------------------------------------

    async def _outputs_by(self, deadline: datetime, end: RunEnd) -> tuple[RunEnd, dict[str, Any] | None]:
        """The workflow's outputs, within the run's deadline. Past it, their evaluation is cancelled and the run ends
        `deadline_exceeded`; an output that can't be computed fails the run with its code."""
        task = asyncio.create_task(self._outputs())
        clock = asyncio.create_task(asyncio.sleep(max(0.0, (deadline - workflow.now()).total_seconds())))
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

    async def _finish(self, end: RunEnd, outputs: dict[str, Any] | None = None) -> RunResult:
        error = end.failure.to_json() if end.failure is not None and end.status != "succeeded" else None
        if error is not None:
            error["message"] = mask(error["message"], self._secrets)
        summary = RunSummary(
            run_id=self.input.run_id,
            status=end.status,
            ended_at=workflow.now().isoformat(),
            error_code=error["code"] if error else None,
            error_message=error["message"] if error else None,
            iterations=self.sched.iterations,
        )
        self._queue_settled()
        rows, self._rows = list(self._rows.values()), {}
        await self._project_end(rows, summary)
        return RunResult(status=end.status, outputs=outputs, error=error, iterations=self.sched.iterations)

    async def _end_early(self, end: RunEnd) -> RunResult:
        """The run ends before it has a program: nothing ran, so only the run is projected."""
        error = end.failure.to_json() if end.failure is not None else None
        summary = RunSummary(
            run_id=self.input.run_id,
            status=end.status,
            ended_at=workflow.now().isoformat(),
            error_code=error["code"] if error else None,
            error_message=error["message"] if error else None,
        )
        await self._project_end([], summary)
        return RunResult(status=end.status, error=error)

    async def _outputs(self) -> dict[str, Any]:
        settings_outputs = self.program.graph.settings.outputs
        pairs = [(pointer_str(p), v) for p, v in iter_values(settings_outputs, ("settings", "outputs"))]
        values, _ = await self._values(None, pairs, ())
        assembled = resolve.assemble({"settings": {"outputs": settings_outputs}}, values)
        return dict(assembled["settings"]["outputs"])

    async def _project_end(self, rows: list[StepRow], summary: RunSummary) -> None:
        """The run's last projection. A cancel that arrives while it's written comes too late to unmake the end it
        records: the write is repeated and the run's result stands, so the projection and Temporal agree."""
        try:
            await self._project(rows, summary)
        except asyncio.CancelledError:
            await self._project(rows, summary)

    async def _project(self, rows: list[StepRow], summary: RunSummary | None = None) -> None:
        await workflow.execute_activity(
            PROJECT,
            ProjectInput(self.input.tenant_id, rows, summary),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_interval=timedelta(seconds=30)),
        )
        return None


__all__ = [
    "CEL_BATCH",
    "DEADLINE_EXCEEDED",
    "INTERNAL_ERROR",
    "IN_FLIGHT_CAP",
    "NODE_TYPE_UNAVAILABLE",
    "VERSION_UNUSABLE",
    "RunGraph",
]
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker`
Expected: 57 passed (15 + 14 + 28) in about 20 s: the timeout tests wait a few real seconds, on test servers of their
own. The first run downloads Temporal's test server into the SDK's cache (the owner approved it). The warnings that
activities "completed as failed" are the tests' own failing steps and the flaky store's refused writes.

- [ ] **Step 5: Check that the in-flight, projection, ambiguous-timeout and masking tests bite**

Set `IN_FLIGHT_CAP = 101` in `workflow.py`, run
`uv run pytest -q tests/apps/worker/test_run_graph_policies.py -k hundred`, and restore it.
Expected: 1 failed (`assert 101 == 100`), then 1 passed after restoring.

Change `if self._rows and not any(key[0] == "project" for key in tasks):` to `if self._rows:`, run
`uv run pytest -q tests/apps/worker/test_run_graph_policies.py -k one_projection`, and restore it.
Expected: 1 failed (`assert 4 == 1`, or another count above 1: several projections were in flight), then 1 passed.

In `_attempt_failed`, change `if ambiguous:` to `if False:`, run
`uv run pytest -q tests/apps/worker/test_run_graph_policies.py -k ambiguous_send_is_never`, and restore it.
Expected: 1 failed (`assert 3 == 1`: the send went out three times), then 1 passed.

In `_preview`, drop `self._secrets` from the `preview` call, run
`uv run pytest -q tests/apps/worker/test_run_graph_policies.py -k sensitive`, and restore it.
Expected: 3 failed (the copied secrets show), then 3 passed.

Delete the line `self._learn(config, manifest["config_schema"])` in `_activity`, run
`uv run pytest -q tests/apps/worker/test_run_graph_policies.py -k sensitive_config`, and restore it.
Expected: 1 failed (`q`'s error echoes `tok-from-trigger`), then 1 passed.

- [ ] **Step 6: Checks and commit, then pause for checkpoint 2**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/engine tests/core tests/apps/worker \
  && git add src/dewpoint/engine/runtime/workflow.py tests/apps/worker \
  && git commit -m "feat(engine): RunGraph, the interpreter workflow" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Admission and `start_run`

2a's only way to start a run (spec §9), and the admission 2b's dispatcher will reuse. The run is inserted as the
dispatch role, in one READ COMMITTED transaction that first takes two kinds of shared lock (§4.5, decision 23):
- the workflow's admission lock, before it reads whether the workflow is enabled and which version is active. A
  disable, publish or activation takes that lock exclusively, so it either commits before the read or waits until the
  run exists;
- the lifecycle locks on the version's closure. So a retirement either sees the run, or the run sees the retirement.

Then `RunGraph` starts, with the run's id as its workflow id and `REJECT_DUPLICATE`. A lost acknowledgement looks like
a failure, so an uncertain attempt is repeated with the same id, and a duplicate refusal confirms the earlier start.
Only a confirmed refusal records the run as failed (`start_failed`). An answer that never comes leaves it `running`
(decision 22).

**Files:**
- Create: `backend/src/dewpoint/apps/runs.py`
- Modify: `backend/src/dewpoint/core/config.py` (`cel_schedule_to_start_s`)
- Modify: `backend/src/dewpoint/core/workflows/service.py` (the workflow's admission lock)
- Create: `backend/tests/apps/test_runs.py`
- Modify: `backend/tests/apps/test_lifecycle_races.py` (the lock-wait helper covers both kinds of lock)

**Interfaces:**
- Consumes:
  - from Task 3: `insert_run`, `finish_run` and `get_run`;
  - from Task 4: `ENGINE_QUEUE`, `LIVE`, `SIMULATE` and `RunInput`;
  - from Task 5: `RunGraph`;
  - from `main`: `lifecycle.entries_for`, `lock_shared`, `states` and `not_executable`; `get_workflow`;
    `WorkflowVersion`; `Settings.max_run_duration_days`; and the lifecycle race helpers in
    `tests/apps/test_lifecycle_races.py` and `tests/apps/test_workflow_ops.py`.
- Produces:
  - `Settings.cel_schedule_to_start_s` (default 600);
  - `core/workflows/service.py`: `lock_for_admission(s, workflow_id)`, the workflow's admission lock, shared. With
    `for_update`, `get_workflow` now takes it exclusively before the row lock, so publish, activate, enable, disable
    and rename all do;
  - `apps/runs.py`:
    - `START_FAILED = "start_failed"` and `START_RETRY_S = (0.5, 2.0)`;
    - `NotAdmissibleError(reasons)` with `.reasons`, `StartRefusedError`, and `StartUncertainError(run_id)` with
      `.run_id`;
    - `admit(s, *, tenant_id, version_id, mode=LIVE, started_by=None) -> Run`;
    - `start_run(sessionmaker, client, settings, *, tenant_id, version_id, trigger, mode=LIVE, started_by=None) -> uuid.UUID`;
    - the test hook `_admission_locked()`;
  - in `tests/apps/test_lifecycle_races.py`, `until_someone_waits_for_a_lock` (renamed from
    `until_someone_waits_for_a_lifecycle_lock`).

- [ ] **Step 1: Write the failing tests**

The workflow's admission lock is an advisory lock too, so rename the lock-wait helper in
`backend/tests/apps/test_lifecycle_races.py`:

```diff
diff --git a/backend/tests/apps/test_lifecycle_races.py b/backend/tests/apps/test_lifecycle_races.py
--- a/backend/tests/apps/test_lifecycle_races.py
+++ b/backend/tests/apps/test_lifecycle_races.py
@@ -26,7 +26,8 @@
 ECHO = Entry("node", "testkit.echo@1")


-async def until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker: Any) -> None:
+async def until_someone_waits_for_a_lock(owner_sessionmaker: Any) -> None:
+    """Until a transaction waits for an advisory lock: a lifecycle entry's, or a workflow's admission lock."""
     for _ in range(200):
         async with owner_sessionmaker() as s:
             waiting = (
@@ -35,7 +36,7 @@
         if waiting:
             return
         await asyncio.sleep(0.05)
-    raise AssertionError("nobody is waiting for a lifecycle lock")
+    raise AssertionError("nobody is waiting for a lock")


 @pytest.fixture
@@ -69,7 +70,7 @@
         async with a.begin():
             await lifecycle.lock_exclusive(a, ECHO)
             publishing = asyncio.create_task(publish(api_sessionmaker, ctx, wf, api_settings))
-            await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
+            await until_someone_waits_for_a_lock(owner_sessionmaker)
             assert (await lifecycle.retire(a, ECHO)).applied
     out = await asyncio.wait_for(publishing, 10)
     assert out.version is None and [d.code for d in out.errors] == ["lifecycle.retired"]
@@ -91,7 +92,7 @@
             return await lifecycle.retire(a, ECHO)

     retiring = asyncio.create_task(retire())
-    await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
+    await until_someone_waits_for_a_lock(owner_sessionmaker)
     release.set()
     assert (await asyncio.wait_for(publishing, 10)).version is not None
     with pytest.raises(lifecycle.ReferencedError) as e:
@@ -115,7 +116,7 @@
             return await lifecycle.retire(a, ECHO, force=True, confirm=True)

     retiring = asyncio.create_task(retire())
-    await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
+    await until_someone_waits_for_a_lock(owner_sessionmaker)
     release.set()
     assert (await asyncio.wait_for(publishing, 10)).version is not None
     preview = await asyncio.wait_for(retiring, 10)
@@ -147,7 +148,7 @@
         async with a.begin():
             await lifecycle.lock_exclusive(a, ECHO)
             activating = asyncio.create_task(activate(api_sessionmaker, ctx, wf, v1.id))
-            await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
+            await until_someone_waits_for_a_lock(owner_sessionmaker)
             assert (await lifecycle.retire(a, ECHO)).applied  # nothing active uses echo: normal path
     with pytest.raises(workflow_ops.NotActivatableError):
         await asyncio.wait_for(activating, 10)
@@ -165,7 +166,7 @@
         async with a.begin():
             await lifecycle.lock_exclusive(a, ECHO)
             enabling = asyncio.create_task(update(api_sessionmaker, ctx, wf, enabled=True))
-            await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
+            await until_someone_waits_for_a_lock(owner_sessionmaker)
             assert (await lifecycle.retire(a, ECHO)).applied  # the workflow is disabled: normal path
     with pytest.raises(workflow_ops.NotActivatableError):
         await asyncio.wait_for(enabling, 10)
@@ -190,7 +191,7 @@
             return await lifecycle.retire(a, ECHO)

     retiring = asyncio.create_task(retire())
-    await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
+    await until_someone_waits_for_a_lock(owner_sessionmaker)
     release.set()
     await asyncio.wait_for(enabling, 10)
     with pytest.raises(lifecycle.ReferencedError) as e:
@@ -218,7 +219,7 @@
             return await lifecycle.retire(a, ECHO)

     retiring = asyncio.create_task(retire())
-    await until_someone_waits_for_a_lifecycle_lock(owner_sessionmaker)
+    await until_someone_waits_for_a_lock(owner_sessionmaker)
     release.set()
     await asyncio.wait_for(activating, 10)
     with pytest.raises(lifecycle.ReferencedError) as e:
```

Create `backend/tests/apps/test_runs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`start_run` (spec §4.5, §9): admission of the workflow's active version under the lifecycle locks."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import pytest
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.apps import runs as run_ops
from dewpoint.apps import workflow_ops
from dewpoint.apps.runs import START_FAILED, NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
from dewpoint.core.db import tenant_scope
from dewpoint.core.plugins import lifecycle
from dewpoint.core.runs import service
from dewpoint.core.workflows import service as workflows
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, SIMULATE, RunInput
from tests.apps.test_lifecycle_races import until_someone_waits_for_a_lock
from tests.apps.test_workflow_ops import ECHO, ECHO_GRAPH, actor, create, publish, save, update
from tests.support.registry import sync_test_plugins


@dataclass(frozen=True)
class LostAck:
    """Temporal accepts the start, but its answer never arrives: the client sees `error`."""

    error: BaseException


def rpc(status: RPCStatusCode) -> RPCError:
    return RPCError(status.name.lower(), status, b"")


class FakeClient:
    """Temporal's start, as start_run sees it. Each call takes the next answer: None accepts, an exception refuses,
    and a LostAck accepts but raises. Like the server, it refuses a workflow id it already accepted."""

    def __init__(self, *answers: BaseException | LostAck | None) -> None:
        self.answers = list(answers)
        self.started: list[tuple[RunInput, str, str]] = []
        self.calls: list[tuple[str, WorkflowIDReusePolicy]] = []

    async def start_workflow(
        self, _run: Any, arg: RunInput, *, id: str, task_queue: str, id_reuse_policy: WorkflowIDReusePolicy
    ) -> None:
        self.calls.append((id, id_reuse_policy))
        answer = self.answers.pop(0) if self.answers else None
        if any(started == id for _, started, _ in self.started):
            raise WorkflowAlreadyStartedError(id, "RunGraph")
        if isinstance(answer, BaseException):
            raise answer
        self.started.append((arg, id, task_queue))
        if isinstance(answer, LostAck):
            raise answer.error


@pytest.fixture(autouse=True)
def no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_ops, "START_RETRY_S", (0.0, 0.0))


async def published(owner: Any, api: Any, admin: Any, settings: Any) -> tuple[Any, uuid.UUID, uuid.UUID]:
    await sync_test_plugins(admin)
    ctx = await actor(owner)
    wf = await create(api, ctx, ECHO_GRAPH)
    out = await publish(api, ctx, wf, settings)
    assert out.version is not None
    return ctx, wf, out.version.id


async def run_row(sm: Any, tenant: uuid.UUID, run_id: uuid.UUID) -> Any:
    async with sm() as s, s.begin():
        await tenant_scope(s, tenant)
        return await service.get_run(s, run_id)


async def test_the_active_version_starts_with_its_run_id_as_the_workflow_id(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient()
    run_id = await start_run(
        dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
        tenant_id=ctx.tenant_id, version_id=version, trigger={"x": 1}, mode=SIMULATE,
    )  # fmt: skip
    [(arg, workflow_id, queue)] = client.started
    assert (workflow_id, queue) == (str(run_id), ENGINE_QUEUE)
    assert (arg.version_id, arg.trigger, arg.mode) == (str(version), {"x": 1}, SIMULATE)
    assert arg.max_run_duration_s == api_settings.max_run_duration_days * 86_400
    row = await run_row(owner_sessionmaker, ctx.tenant_id, run_id)
    assert (row.status, row.mode, row.workflow_version_id) == ("running", SIMULATE, version)


async def test_only_the_active_version_of_an_enabled_workflow_is_admitted(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, first = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    await save(api_sessionmaker, ctx, wf, ECHO_GRAPH)
    assert (await publish(api_sessionmaker, ctx, wf, api_settings)).version is not None  # supersedes `first`
    with pytest.raises(NotAdmissibleError, match="active version"):
        await start_run(
            dispatch_sessionmaker, FakeClient(), api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=first, trigger={},
        )  # fmt: skip
    await update(api_sessionmaker, ctx, wf, enabled=False)
    with pytest.raises(NotAdmissibleError, match="disabled"):
        await start_run(
            dispatch_sessionmaker, FakeClient(), api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=first, trigger={},
        )  # fmt: skip


async def only_run(owner: Any, tenant: uuid.UUID) -> Any:
    async with owner() as s, s.begin():
        await tenant_scope(s, tenant)
        [row] = await service.list_runs(s)
    return row


@pytest.mark.parametrize(
    ("answers", "calls"),
    [
        ((rpc(RPCStatusCode.INVALID_ARGUMENT),), 1),  # refused outright: no retry
        ((rpc(RPCStatusCode.RESOURCE_EXHAUSTED),) * 3, 3),  # throttled every time: never accepted
    ],
)
async def test_a_confirmed_refusal_records_the_run_as_failed(
    owner_sessionmaker,
    api_sessionmaker,
    admin_sessionmaker,
    dispatch_sessionmaker,
    api_settings,
    answers: tuple[RPCError, ...],
    calls: int,
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient(*answers)
    with pytest.raises(StartRefusedError):
        await start_run(
            dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=version, trigger={},
        )  # fmt: skip
    row = await only_run(owner_sessionmaker, ctx.tenant_id)
    assert (row.status, row.error_code, len(client.calls)) == ("failed", START_FAILED, calls)


async def test_a_lost_acknowledgement_is_reconciled_by_the_workflow_id(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """Review finding: Temporal accepted the run, but the answer was lost. The retry with the same workflow id is
    refused as a duplicate, which confirms the start; the run is running, not failed."""
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient(LostAck(rpc(RPCStatusCode.UNAVAILABLE)))
    run_id = await start_run(
        dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
        tenant_id=ctx.tenant_id, version_id=version, trigger={},
    )  # fmt: skip
    assert len(client.started) == 1  # started once, not twice
    assert client.calls == [(str(run_id), WorkflowIDReusePolicy.REJECT_DUPLICATE)] * 2
    assert (await only_run(owner_sessionmaker, ctx.tenant_id)).status == "running"


async def test_a_start_that_stays_uncertain_leaves_the_run_running(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    """No answer ever confirms or refuses: the run may be executing, so it isn't marked failed. 2b's dispatcher
    retries until it knows; here the caller is told."""
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    client = FakeClient(ConnectionResetError(), rpc(RPCStatusCode.DEADLINE_EXCEEDED), rpc(RPCStatusCode.UNAVAILABLE))
    with pytest.raises(StartUncertainError) as e:
        await start_run(
            dispatch_sessionmaker, client, api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id, version_id=version, trigger={},
        )  # fmt: skip
    row = await only_run(owner_sessionmaker, ctx.tenant_id)
    assert (row.status, row.error_code, len(client.calls), e.value.run_id) == ("running", None, 3, row.id)


async def test_retirement_first_makes_admission_refuse(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    async with admin_sessionmaker() as a:
        async with a.begin():
            await lifecycle.lock_exclusive(a, ECHO)
            starting = asyncio.create_task(
                start_run(
                    dispatch_sessionmaker,
                    FakeClient(),
                    api_settings,  # type: ignore[arg-type]
                    tenant_id=ctx.tenant_id,
                    version_id=version,
                    trigger={},
                )  # fmt: skip
            )
            await until_someone_waits_for_a_lock(owner_sessionmaker)
            await lifecycle.retire(a, ECHO, force=True, confirm=True)
    with pytest.raises(NotAdmissibleError, match="retired"):
        await asyncio.wait_for(starting, 10)


async def test_admission_first_holds_retirement_until_the_run_exists(
    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    ctx, _, version = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(run_ops, "_admission_locked", paused)
    client = FakeClient()
    starting = asyncio.create_task(
        start_run(
            dispatch_sessionmaker,
            client,
            api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id,
            version_id=version,
            trigger={},
        )  # fmt: skip
    )
    await asyncio.wait_for(reached.wait(), 10)

    async def retire() -> Any:
        async with admin_sessionmaker() as a, a.begin():
            return await lifecycle.retire(a, ECHO, force=True, confirm=True)

    retiring = asyncio.create_task(retire())
    await until_someone_waits_for_a_lock(owner_sessionmaker)  # retirement waits for admission's lock
    release.set()
    run_id = await asyncio.wait_for(starting, 10)
    assert (await asyncio.wait_for(retiring, 10)).applied
    assert client.started and (await run_row(owner_sessionmaker, ctx.tenant_id, run_id)).status == "running"


# A change to what admission checks (spec §4.5, "Admissible"), made as the API makes it: in a transaction that locks
# the workflow for update. Each one makes the version admission was asked for inadmissible, and admission says why.
Change = Callable[[Any, Any], Awaitable[object]]
REFUSED = {"disable": "disabled", "activate": "active version", "publish": "active version"}


async def admissible(
    how: str, owner: Any, api: Any, admin: Any, settings: Any
) -> tuple[Any, uuid.UUID, uuid.UUID, Change]:
    """A workflow, the version admission is asked for, and the change `how` that makes that version inadmissible:
    disabling the workflow, activating an older version, or publishing a newer one."""
    ctx, wf, version = await published(owner, api, admin, settings)
    older = version
    if how in ("activate", "publish"):
        await save(api, ctx, wf, ECHO_GRAPH)  # a draft for `publish`, or for the newer version `activate` replaces
    if how == "activate":
        newer = (await publish(api, ctx, wf, settings)).version
        assert newer is not None
        version = newer.id

    async def change(s: Any, row: Any) -> object:
        if how == "disable":
            return await workflow_ops.update(s, ctx, row, name=None, enabled=False)
        if how == "activate":
            return await workflow_ops.activate(s, ctx, row, await workflows.get_version(s, wf, older))
        out = await workflow_ops.publish(s, ctx, row, expected_revision=row.draft_revision, settings=settings)
        assert out.version is not None
        return out

    return ctx, wf, version, change


@asynccontextmanager
async def changing(api: Any, ctx: Any, wf: uuid.UUID, change: Change) -> AsyncIterator[None]:
    """Make the change in a transaction that stays open for the block, and commit it when the block ends."""
    async with api() as s, s.begin():
        await tenant_scope(s, ctx.tenant_id)
        row = await workflows.get_workflow(s, ctx.tenant_id, wf, for_update=True)
        assert row is not None
        await change(s, row)
        yield


async def change_committed(api: Any, ctx: Any, wf: uuid.UUID, change: Change) -> None:
    async with changing(api, ctx, wf, change):
        pass


async def until_waiting_or_done(task: asyncio.Task[Any], owner: Any) -> None:
    """Until `task` has finished, or someone waits for a lock."""
    waiting = asyncio.create_task(until_someone_waits_for_a_lock(owner))
    done, _ = await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
    if waiting in done:
        waiting.result()  # nobody waited in time: AssertionError
    else:
        waiting.cancel()


@pytest.mark.parametrize("how", REFUSED)
async def test_a_workflow_change_first_makes_admission_refuse(
    how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
) -> None:
    ctx, wf, version, change = await admissible(
        how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
    )
    client = FakeClient()
    async with changing(api_sessionmaker, ctx, wf, change):
        starting = asyncio.create_task(
            start_run(
                dispatch_sessionmaker,
                client,
                api_settings,  # type: ignore[arg-type]
                tenant_id=ctx.tenant_id,
                version_id=version,
                trigger={},
            )  # fmt: skip
        )
        await until_waiting_or_done(starting, owner_sessionmaker)  # admission waits for the change to commit
    with pytest.raises(NotAdmissibleError, match=REFUSED[how]):
        await asyncio.wait_for(starting, 10)
    assert not client.started


@pytest.mark.parametrize("how", REFUSED)
async def test_admission_first_holds_a_workflow_change_until_the_run_exists(
    how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, monkeypatch
) -> None:
    ctx, wf, version, change = await admissible(
        how, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
    )
    reached, release = asyncio.Event(), asyncio.Event()

    async def paused() -> None:
        reached.set()
        await release.wait()

    monkeypatch.setattr(run_ops, "_admission_locked", paused)
    client = FakeClient()
    starting = asyncio.create_task(
        start_run(
            dispatch_sessionmaker,
            client,
            api_settings,  # type: ignore[arg-type]
            tenant_id=ctx.tenant_id,
            version_id=version,
            trigger={},
        )  # fmt: skip
    )
    await asyncio.wait_for(reached.wait(), 10)
    changed = asyncio.create_task(change_committed(api_sessionmaker, ctx, wf, change))
    await until_waiting_or_done(changed, owner_sessionmaker)  # the change waits for the run
    changed_first = changed.done()
    release.set()
    run_id = await asyncio.wait_for(starting, 10)
    await asyncio.wait_for(changed, 10)
    assert not changed_first, f"`{how}` committed while a run of the version it makes inadmissible was admitted"
    row = await run_row(owner_sessionmaker, ctx.tenant_id, run_id)
    assert client.started and (row.status, row.workflow_version_id) == ("running", version)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/test_runs.py`
Expected: a collection error, `ImportError: cannot import name 'runs' from 'dewpoint.apps'`.

- [ ] **Step 3: Implement**

Add the setting to `backend/src/dewpoint/core/config.py`:

```diff
diff --git a/backend/src/dewpoint/core/config.py b/backend/src/dewpoint/core/config.py
--- a/backend/src/dewpoint/core/config.py
+++ b/backend/src/dewpoint/core/config.py
@@ -27,6 +27,7 @@
     webauthn_challenges_max: int = 10_000  # outstanding (unexpired) challenges across the platform
     max_request_body_bytes: int = 1_048_576  # counted as received: chunked bodies have no Content-Length
     max_run_duration_days: int = 30  # spec §6: whole logical run, including continue-as-new and waits
+    cel_schedule_to_start_s: float = 600  # spec §5.7: no evaluator for a profile after this: cel_profile_unavailable
     audit_signing_key_b64: str | None = None  # Ed25519 private key (raw 32 bytes, base64)
     audit_anchor_path: str | None = None

```

Add the workflow's admission lock to `backend/src/dewpoint/core/workflows/service.py`:

```diff
diff --git a/backend/src/dewpoint/core/workflows/service.py b/backend/src/dewpoint/core/workflows/service.py
--- a/backend/src/dewpoint/core/workflows/service.py
+++ b/backend/src/dewpoint/core/workflows/service.py
@@ -6,7 +6,7 @@
 from dataclasses import dataclass, field
 from typing import Any

-from sqlalchemy import func, select, update
+from sqlalchemy import func, select, text, update
 from sqlalchemy.ext.asyncio import AsyncSession

 from dewpoint.core.audit.service import record
@@ -46,11 +46,35 @@
     return wf


+def _admission_key(workflow_id: uuid.UUID) -> str:
+    return f"dewpoint:workflow:{workflow_id}"
+
+
+async def lock_for_admission(s: AsyncSession, workflow_id: uuid.UUID) -> None:
+    """Hold what admission checks (`enabled`, `active_version_id`) until this transaction ends (spec §4.5).
+
+    Admission takes the workflow's admission lock *shared* before it reads the workflow, and keeps it until the run
+    is inserted. Every change to a workflow takes it *exclusively* first (`get_workflow` with `for_update`). So a
+    change either commits before admission reads, or waits until the run exists. Like the lifecycle locks, it is
+    a transaction-scoped advisory lock: a row lock would need UPDATE on `workflows`, which the dispatch role must
+    not have."""
+    await lifecycle.assert_read_committed(s)  # the read after the lock must see what a change committed
+    await s.execute(
+        text("select pg_advisory_xact_lock_shared(hashtextextended(:k, 0))"), {"k": _admission_key(workflow_id)}
+    )
+
+
 async def get_workflow(
     s: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID, *, for_update: bool = False
 ) -> Workflow | None:
+    """With `for_update`, take the workflow's admission lock exclusively (`lock_for_admission`), then its row lock.
+    Both are held until the change commits, so a run is admitted either before the change or after it. The admission
+    lock comes first: a change waiting for an admission holds nothing that admission's insert could need."""
     q = select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == tenant_id)
     if for_update:
+        await s.execute(
+            text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": _admission_key(workflow_id)}
+        )
         q = q.with_for_update()
     return (await s.execute(q)).scalar_one_or_none()

```

Create `backend/src/dewpoint/apps/runs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Starting runs (spec §9). `start_run` is 2a's admission, and 2b's dispatcher reuses `admit`: the workflow is
enabled, the version is its active one, and nothing in the version's closure is retired. All three are checked in the
transaction that inserts the run (§4.5), under locks the other side takes too:
- the workflow is read under its admission lock (shared), so a disable, publish or activation either commits before
  the read or waits until the run exists;
- the closure is read under the lifecycle locks (shared), so a retirement either sees the run or the run sees the
  retirement.

Then `RunGraph` starts, with the run's id as its workflow id. A lost acknowledgement looks like a failure, so an
uncertain start is repeated with the same id: Temporal refuses a duplicate id (`REJECT_DUPLICATE`, which also covers
a run that has already finished), and that refusal confirms the first start. Only a confirmed refusal records the run
as failed (`start_failed`)."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from dewpoint.core.config import Settings
from dewpoint.core.db import tenant_scope
from dewpoint.core.models.runs import Run
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.plugins import lifecycle
from dewpoint.core.runs import service as runs
from dewpoint.core.workflows.service import get_workflow, lock_for_admission
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, LIVE, RunInput
from dewpoint.engine.runtime.workflow import RunGraph

START_FAILED = "start_failed"
START_RETRY_S = (0.5, 2.0)  # the waits between three attempts to start a run
# Temporal refused the request itself, so it started nothing. Any other failure may follow an accepted start.
_REFUSED = frozenset(
    {
        RPCStatusCode.INVALID_ARGUMENT,
        RPCStatusCode.NOT_FOUND,
        RPCStatusCode.PERMISSION_DENIED,
        RPCStatusCode.UNAUTHENTICATED,
        RPCStatusCode.FAILED_PRECONDITION,
        RPCStatusCode.OUT_OF_RANGE,
        RPCStatusCode.UNIMPLEMENTED,
    }
)
_THROTTLED = RPCStatusCode.RESOURCE_EXHAUSTED  # refused before it was processed: worth another attempt


class NotAdmissibleError(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class StartRefusedError(Exception):
    """Temporal refused the start: the run is recorded as failed (`start_failed`)."""


class StartUncertainError(Exception):
    """No answer confirmed or refused the start: the run may be executing, so it stays `running`."""

    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"Temporal didn't confirm or refuse run {run_id}: it may be running.")
        self.run_id = run_id


async def _admission_locked() -> None:
    """Hook that runs once the workflow's admission lock and the lifecycle locks are held. A no-op; the race tests
    pause here."""


async def admit(
    s: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    mode: str = LIVE,
    started_by: uuid.UUID | None = None,
) -> Run:
    """Insert the run, or raise NotAdmissibleError. Call it inside a READ COMMITTED transaction."""
    await tenant_scope(s, tenant_id)
    version = await s.get(WorkflowVersion, version_id)
    if version is None:
        raise NotAdmissibleError(["There is no such version."])
    await lock_for_admission(s, version.workflow_id)  # first: the workflow read below stands until the run exists
    workflow = await get_workflow(s, tenant_id, version.workflow_id)
    if workflow is None or not workflow.enabled:
        raise NotAdmissibleError(["The workflow is disabled."])
    if workflow.active_version_id != version.id:
        raise NotAdmissibleError(["Only the workflow's active version can start runs."])
    entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
    await lifecycle.lock_shared(s, entries)
    await _admission_locked()
    blocked = lifecycle.not_executable(await lifecycle.states(s, entries))
    if blocked:
        raise NotAdmissibleError([f"{entry} has been retired." for entry in blocked])
    return await runs.insert_run(
        s,
        run_id=uuid.uuid4(),
        tenant_id=tenant_id,
        workflow_id=version.workflow_id,
        version_id=version.id,
        mode=mode,
        started_by=started_by,
    )


async def start_run(
    sessionmaker: async_sessionmaker[AsyncSession],
    client: Client,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    version_id: uuid.UUID,
    trigger: dict[str, Any],
    mode: str = LIVE,
    started_by: uuid.UUID | None = None,
) -> uuid.UUID:
    """Admit the run and start it. Raises NotAdmissibleError, StartRefusedError (the run is recorded as failed) or
    StartUncertainError (the run stays `running`: it may be executing)."""
    async with sessionmaker() as s, s.begin():
        run = await admit(s, tenant_id=tenant_id, version_id=version_id, mode=mode, started_by=started_by)
    start = RunInput(
        tenant_id=str(tenant_id),
        run_id=str(run.id),
        version_id=str(version_id),
        trigger=trigger,
        mode=mode,
        max_run_duration_s=settings.max_run_duration_days * 86_400,
        cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
    )
    try:
        await _start(client, start, run.id)
    except StartRefusedError as e:
        async with sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            await runs.finish_run(
                s, run.id, status="failed", ended_at=datetime.now(UTC), error_code=START_FAILED, error_message=str(e)
            )
        raise
    return run.id


async def _start(client: Client, start: RunInput, run_id: uuid.UUID) -> None:
    uncertain = False
    last: BaseException | None = None
    for wait in (*START_RETRY_S, None):
        try:
            await client.start_workflow(
                RunGraph.run,
                start,
                id=str(run_id),
                task_queue=ENGINE_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            )
            return
        except WorkflowAlreadyStartedError:
            return  # an earlier attempt was accepted; its answer was lost
        except RPCError as e:
            if e.status in _REFUSED and not uncertain:
                raise StartRefusedError(f"Temporal refused the run ({e.status.name}).") from e
            uncertain = uncertain or e.status != _THROTTLED
            last = e
        except Exception as e:  # a lost connection: the request may have been accepted
            uncertain, last = True, e
        if wait is not None:
            await asyncio.sleep(wait)
    if uncertain:
        raise StartUncertainError(run_id) from last
    raise StartRefusedError("Temporal refused the run: it was busy (RESOURCE_EXHAUSTED).") from last


__all__ = [
    "START_FAILED",
    "START_RETRY_S",
    "NotAdmissibleError",
    "StartRefusedError",
    "StartUncertainError",
    "admit",
    "start_run",
]
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/test_runs.py tests/apps/test_lifecycle_races.py tests/apps/test_workflow_ops.py`
Expected: all pass: 14 new, 6 of them races between admission and a disable, activation or publish, in both orders.
The lifecycle race and workflow tests pass unchanged.

- [ ] **Step 5: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q tests/apps/test_runs.py tests/apps/test_lifecycle_races.py tests/apps/test_workflow_ops.py \
       tests/core \
  && git add src/dewpoint/apps/runs.py src/dewpoint/core/config.py src/dewpoint/core/workflows/service.py \
       tests/apps/test_runs.py tests/apps/test_lifecycle_races.py \
  && git commit -m "feat(apps): admit and start runs under the workflow's admission lock and the lifecycle locks" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The worker process, the database store, the runs API and `dewpoint dev run`

This task wires everything to the outside:
- **`DbRunStore`** loads versions and writes the projection as the worker role, inside the run's tenant.
- **`dewpoint worker`** runs the engine worker. With an evaluator configured, it also runs the CEL worker on the
  queue of the profile the evaluator reports.
- **The runs API** is read-only: the UI reads the projection, never Temporal history.
- **`dewpoint dev run`** starts a run of a version for development.

The operations doc explains all four.

**Files:**
- Create: `backend/src/dewpoint/apps/worker/store.py`, `backend/src/dewpoint/apps/worker/main.py`
- Create: `backend/src/dewpoint/apps/api/routes/runs.py`; modify `backend/src/dewpoint/apps/api/main.py`
- Modify: `backend/src/dewpoint/apps/cli/main.py`, `backend/src/dewpoint/core/config.py`
- Create: `backend/tests/apps/worker/test_worker_db.py`, `backend/tests/apps/worker/test_dev_run.py`,
  `backend/tests/apps/cli/test_dev_run_cli.py`
- Create: `docs/operations/runs.md`; modify `README.md`

**Interfaces:**
- Consumes:
  - from Task 3: the service and the models;
  - from Task 4: `RunStore`, `engine_activities`, `cel_activity` and `remote_evaluator`;
  - from Task 5: `RunGraph` and the harness;
  - from Task 6: `start_run`, `NotAdmissibleError`, `StartRefusedError` and `StartUncertainError`;
  - from `main`: `load_node_types`, `installed_plugins`, `cel_client.identity`, `make_engine`, `make_sessionmaker`,
    `P.RUN_VIEW`, `require`, `TenantContext`, `get_db`, and the test helpers `member_client`, `actor`, `create`,
    `publish` and `sync_test_plugins`.
- Produces:
  - `DbRunStore(sessionmaker)`, a `RunStore`;
  - `apps/worker/main.py`: `evaluator_profile(socket_path, *, wait_s=2.0)`,
    `engine_worker(client, store, plugins)`, `cel_worker(client, socket_path, profile, *, max_concurrent)` and
    `run(settings)`;
  - the settings `temporal_address`, `temporal_namespace`, `cel_socket` and `cel_max_concurrent`;
  - the API:
    - `GET /api/v1/t/{tenant_id}/runs?workflow_id=&before=&limit=` (1–200, default 50) lists runs, each with `id`,
      `workflow_id`, `version_id`, `mode`, `status`, `started_at`, `ended_at`, `error` (`{code, message}` or
      null) and `iterations`;
    - `GET /api/v1/t/{tenant_id}/runs/{run_id}` returns the same, plus `steps`, each with `step_id`, `key`,
      `iteration_key`, `attempt`, `status`, `started_at`, `ended_at`, `input`, `output`, `error`, `outcome` and
      `cel_mode`, or a 404;
    - both require `run.view`;
  - the CLI: `dewpoint worker`; `dewpoint dev run VERSION_ID --tenant T [--input FILE] [--simulate] [--wait/--no-wait]`,
    which exits 0 when the run succeeded, 1 when it ended otherwise or Temporal refused it, 2 when it wasn't
    admitted, and 3 when Temporal never confirmed the start; and
    `dev_run_version(settings, client, *, tenant_id, version_id, trigger, simulate=False, wait=True)`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/apps/worker/test_worker_db.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A run end to end (spec §8, §9): admitted by `start_run`, executed by `RunGraph`, projected by the worker into
`runs` and `run_steps` under RLS, and read back through the runs API."""

import uuid
from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.runs import start_run
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.engine.runtime.workflow import RunGraph
from tests.apps.api.helpers import member_client
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.support.graphs import G, cel, ref
from tests.support.registry import sync_test_plugins


def graph() -> dict[str, Any]:
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        "outputs": {"items": ref("steps.l.output.items")},
    }
    g.node("a", "testkit.echo@1", {"value": cel("trigger.x + 1")})
    g.node("l", "flow.loop@1", {"items": [1, 2], "collect": cel("item * 10")}).node("x", "testkit.echo@1")
    g.node("s", "testkit.sensitive@1")
    g.edge("a", "l").edge("l", "x", "body").edge("l", "s", "done")
    return g.data()


async def test_a_run_is_projected_and_readable_through_the_api(
    env: WorkflowEnvironment,
    owner_sessionmaker: Any,
    api_sessionmaker: Any,
    admin_sessionmaker: Any,
    dispatch_sessionmaker: Any,
    worker_sessionmaker: Any,
    api_settings: Any,
    app: Any,
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, graph()), api_settings)
    assert out.version is not None
    async with workers(env.client, DbRunStore(worker_sessionmaker)):
        run_id = await start_run(
            dispatch_sessionmaker, env.client, api_settings,
            tenant_id=ctx.tenant_id, version_id=out.version.id, trigger={"x": 1},
        )  # fmt: skip
        result = await env.client.get_workflow_handle_for(RunGraph.run, str(run_id)).result()
    assert (result.status, result.outputs) == ("succeeded", {"items": [10, 20]})

    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, ctx.tenant_id, "viewer")
    listed = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()
    assert [(r["id"], r["status"], r["iterations"]) for r in listed] == [(str(run_id), "succeeded", 2)]
    detail = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}")).json()
    steps = {(s["key"], s["iteration_key"]): s for s in detail["steps"]}
    assert steps[("a", "")]["output"] == {"value": 2} and steps[("a", "")]["cel_mode"] == "activity"
    assert steps[("a", "")]["outcome"] == "applied"
    assert {k for k in steps if k[0] == "x"} == {("x", "l:0"), ("x", "l:1")}
    assert steps[("l", "")]["output"] == {"items": [10, 20], "failures": [], "count": 2}
    assert steps[("s", "")]["output"] == {
        "public": "visible",
        "secret_value": "[redacted]",
        "login": {"user": "ops", "password": "[redacted]"},
    }

    other = await actor(owner_sessionmaker)
    stranger, _ = await member_client(app, owner_sessionmaker, api_settings, other.tenant_id, "viewer")
    assert (await stranger.get(f"/api/v1/t/{other.tenant_id}/runs")).json() == []
    assert (await stranger.get(f"/api/v1/t/{other.tenant_id}/runs/{run_id}")).status_code == 404
    assert (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{uuid.uuid4()}")).status_code == 404
```

Create `backend/tests/apps/worker/test_dev_run.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`dev_run_version` (spec §9): the dev CLI's path, through the dispatch role, to a run of the active version."""

from typing import Any

from temporalio.testing import WorkflowEnvironment

from dewpoint.apps.cli.main import dev_run_version
from dewpoint.apps.worker.store import DbRunStore
from tests.apps.test_workflow_ops import actor, create, publish
from tests.apps.worker.harness import workers
from tests.conftest import _url_for
from tests.support.graphs import G, cel, ref
from tests.support.registry import sync_test_plugins


def graph() -> dict[str, Any]:
    g = G()
    g.settings = {
        "input_schema": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        "outputs": {"v": ref("steps.a.output.value")},
    }
    return g.node("a", "testkit.echo@1", {"value": cel("trigger.x + 1")}).data()


async def test_dev_run_starts_the_active_version(
    env: WorkflowEnvironment,
    pg_url: str,
    owner_sessionmaker: Any,
    api_sessionmaker: Any,
    admin_sessionmaker: Any,
    worker_sessionmaker: Any,
    api_settings: Any,
) -> None:
    await sync_test_plugins(admin_sessionmaker)
    ctx = await actor(owner_sessionmaker)
    out = await publish(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, graph()), api_settings)
    assert out.version is not None
    settings = api_settings.model_copy(update={"database_url": _url_for(pg_url, "dewpoint_dispatch")})
    common: dict[str, Any] = {"tenant_id": ctx.tenant_id, "version_id": out.version.id, "trigger": {"x": 1}}
    async with workers(env.client, DbRunStore(worker_sessionmaker)):
        _, waited = await dev_run_version(settings, env.client, **common)
        _, simulated = await dev_run_version(settings, env.client, simulate=True, **common)
        started, nothing = await dev_run_version(settings, env.client, wait=False, **common)
        await env.client.get_workflow_handle(str(started)).result()
    assert waited is not None and (waited.status, waited.outputs) == ("succeeded", {"v": 2})
    assert simulated is not None and simulated.outputs == {"v": {"simulated": 2}}
    assert nothing is None
```

Create `backend/tests/apps/cli/test_dev_run_cli.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`dewpoint dev run`'s exit codes: 0 when the run succeeded, 1 when it ended otherwise or Temporal refused it, 2 when
it wasn't admitted, 3 when Temporal never confirmed the start. The run itself is covered by
tests/apps/worker/test_dev_run.py; here Temporal and the run are stand-ins."""

import base64
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dewpoint.apps.cli import main as cli
from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError
from dewpoint.core.config import get_settings
from dewpoint.engine.runtime.activities import RunResult

RUN = uuid.UUID(int=7)


class _Client:
    @staticmethod
    async def connect(*args: Any, **kwargs: Any) -> "_Client":
        return _Client()


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEWPOINT_DATABASE_URL", "postgresql+asyncpg://nobody@localhost/none")
    monkeypatch.setenv("DEWPOINT_KEK_B64", base64.b64encode(b"k" * 32).decode())
    monkeypatch.setenv("DEWPOINT_PUBLIC_ORIGIN", "https://dewpoint.test")
    monkeypatch.setattr(cli, "Client", _Client)
    get_settings.cache_clear()


def _answer(monkeypatch: pytest.MonkeyPatch, outcome: RunResult | Exception, seen: dict[str, Any]) -> None:
    async def dev_run_version(settings: Any, client: Any, **kwargs: Any) -> tuple[uuid.UUID, RunResult | None]:
        seen.update(kwargs)
        if isinstance(outcome, Exception):
            raise outcome
        return RUN, outcome if kwargs["wait"] else None

    monkeypatch.setattr(cli, "dev_run_version", dev_run_version)


@pytest.mark.usefixtures("cli_env")
def test_a_succeeded_run_prints_its_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}
    _answer(monkeypatch, RunResult("succeeded", {"v": 2}), seen)
    payload = tmp_path / "trigger.json"
    payload.write_text(json.dumps({"x": 1}))
    tenant, version = uuid.uuid4(), uuid.uuid4()
    result = CliRunner().invoke(
        cli.app, ["dev", "run", str(version), "--tenant", str(tenant), "--input", str(payload), "--simulate"]
    )
    assert result.exit_code == 0, result.output
    assert f"run {RUN}" in result.output and '"status": "succeeded"' in result.output
    assert seen == {"tenant_id": tenant, "version_id": version, "trigger": {"x": 1}, "simulate": True, "wait": True}


@pytest.mark.usefixtures("cli_env")
def test_a_run_that_did_not_succeed_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, RunResult("failed", error={"code": "workflow_failed", "message": "no"}), {})
    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
    assert result.exit_code == 1 and '"code": "workflow_failed"' in result.output


@pytest.mark.usefixtures("cli_env")
def test_a_refused_run_exits_2_with_its_reasons(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, NotAdmissibleError(["the workflow is disabled"]), {})
    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
    assert result.exit_code == 2 and "ERROR: the workflow is disabled" in result.output


@pytest.mark.usefixtures("cli_env")
def test_no_wait_prints_only_the_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, RunResult("succeeded"), {})
    args = ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4()), "--no-wait"]
    result = CliRunner().invoke(cli.app, args)
    assert (result.exit_code, result.output.strip()) == (0, f"run {RUN}")


@pytest.mark.usefixtures("cli_env")
@pytest.mark.parametrize(
    ("error", "code", "said"),
    [
        (StartRefusedError("Temporal refused the run (INVALID_ARGUMENT)."), 1, "ERROR: Temporal refused the run"),
        (StartUncertainError(RUN), 3, f"WARNING: Temporal didn't confirm or refuse run {RUN}"),
    ],
)
def test_a_start_temporal_refused_or_never_confirmed(
    monkeypatch: pytest.MonkeyPatch, error: Exception, code: int, said: str
) -> None:
    _answer(monkeypatch, error, {})
    result = CliRunner().invoke(cli.app, ["dev", "run", str(uuid.uuid4()), "--tenant", str(uuid.uuid4())])
    assert result.exit_code == code and said in result.output
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/apps/worker/test_worker_db.py tests/apps/worker/test_dev_run.py tests/apps/cli/test_dev_run_cli.py`
Expected: 2 collection errors: `ModuleNotFoundError: No module named 'dewpoint.apps.worker.store'` and
`ImportError: cannot import name 'dev_run_version' from 'dewpoint.apps.cli.main'`.

- [ ] **Step 3: Implement the store, the worker and the settings**

Add the settings to `backend/src/dewpoint/core/config.py`:

```diff
diff --git a/backend/src/dewpoint/core/config.py b/backend/src/dewpoint/core/config.py
--- a/backend/src/dewpoint/core/config.py
+++ b/backend/src/dewpoint/core/config.py
@@ -27,6 +27,10 @@
     webauthn_challenges_max: int = 10_000  # outstanding (unexpired) challenges across the platform
     max_request_body_bytes: int = 1_048_576  # counted as received: chunked bodies have no Content-Length
     max_run_duration_days: int = 30  # spec §6: whole logical run, including continue-as-new and waits
+    temporal_address: str = "localhost:7233"
+    temporal_namespace: str = "default"
+    cel_socket: str | None = None  # the cel-evaluator's socket; a worker without one serves no CEL queue
+    cel_max_concurrent: int = 2  # the evaluator's N (docs/operations/cel-evaluator.md)
     cel_schedule_to_start_s: float = 600  # spec §5.7: no evaluator for a profile after this: cel_profile_unavailable
     audit_signing_key_b64: str | None = None  # Ed25519 private key (raw 32 bytes, base64)
     audit_anchor_path: str | None = None
```

Create `backend/src/dewpoint/apps/worker/store.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The worker's `RunStore` over the database, as the worker role and inside the run's tenant (spec §8)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.exceptions import ApplicationError

from dewpoint.core.db import tenant_scope
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.plugins.registry import load_node_types
from dewpoint.core.runs import service as runs
from dewpoint.engine.runtime.activities import ProjectInput, StepRow, VersionData


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row(row: StepRow) -> dict[str, Any]:
    return {
        **row.__dict__,
        "run_id": uuid.UUID(row.run_id),
        "step_id": uuid.UUID(row.step_id),
        "started_at": _at(row.started_at),
        "ended_at": _at(row.ended_at),
    }


class DbRunStore:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def version(self, tenant_id: str, version_id: str) -> VersionData:
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, uuid.UUID(tenant_id))
            v = await s.get(WorkflowVersion, uuid.UUID(version_id))
            if v is None:
                raise ApplicationError(f"version {version_id} not found", type="version_not_found", non_retryable=True)
            types = await load_node_types(s, v.node_refs)
            return VersionData(
                version_id=str(v.id),
                workflow_id=str(v.workflow_id),
                graph=v.graph,
                expressions=list(v.expressions),
                cel_profile=v.cel_profile,
                manifests={t.ref: t.manifest for t in types},
            )

    async def project(self, data: ProjectInput) -> None:
        tenant = uuid.UUID(data.tenant_id)
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant)
            await runs.upsert_steps(s, tenant, [_row(r) for r in data.steps])
            if data.run is not None:
                await runs.finish_run(
                    s,
                    uuid.UUID(data.run.run_id),
                    status=data.run.status,
                    ended_at=datetime.fromisoformat(data.run.ended_at),
                    error_code=data.run.error_code,
                    error_message=data.run.error_message,
                    iterations=data.run.iterations,
                )
```

Create `backend/src/dewpoint/apps/worker/main.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""`dewpoint worker` (spec §6, §7): `RunGraph` and the engine activities on `dewpoint-engine`. When an evaluator is
configured, it also serves `cel.evaluate`, only on the queue of the profile the evaluator reports: it waits for the
evaluator, then asks its identity. Worker Versioning (the pinned deployment) comes with plan 2a-3c."""

import asyncio
from collections.abc import Iterable

import structlog
from temporalio.client import Client
from temporalio.worker import Worker

from dewpoint.apps import cel_client
from dewpoint.apps.plugin_loader import installed_plugins
from dewpoint.apps.worker.activities import RunStore, cel_activity, engine_activities, remote_evaluator
from dewpoint.apps.worker.store import DbRunStore
from dewpoint.core.config import Settings
from dewpoint.core.db import make_engine, make_sessionmaker
from dewpoint.engine.runtime.activities import ENGINE_QUEUE, cel_queue
from dewpoint.engine.runtime.workflow import RunGraph
from dewpoint.sdk import Plugin

log = structlog.get_logger("dewpoint.worker")


async def evaluator_profile(socket_path: str, *, wait_s: float = 2.0) -> str:
    """The profile the evaluator serves; retried until it answers (Compose starts it healthy first)."""
    while True:
        try:
            return await cel_client.identity(socket_path)
        except cel_client.EvaluatorUnavailable as e:
            log.warning("cel_evaluator_unavailable", error=str(e))
            await asyncio.sleep(wait_s)


def engine_worker(client: Client, store: RunStore, plugins: Iterable[Plugin]) -> Worker:
    return Worker(client, task_queue=ENGINE_QUEUE, workflows=[RunGraph], activities=engine_activities(store, plugins))


def cel_worker(client: Client, socket_path: str, profile: str, *, max_concurrent: int) -> Worker:
    return Worker(
        client,
        task_queue=cel_queue(profile),
        activities=[cel_activity(remote_evaluator(socket_path, profile))],
        max_concurrent_activities=max_concurrent,
    )


async def run(settings: Settings) -> None:
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    engine = make_engine(settings.database_url)
    try:
        workers = [engine_worker(client, DbRunStore(make_sessionmaker(engine)), installed_plugins())]
        if settings.cel_socket:
            profile = await evaluator_profile(settings.cel_socket)
            log.info("cel_queue", profile=profile)
            workers.append(cel_worker(client, settings.cel_socket, profile, max_concurrent=settings.cel_max_concurrent))
        await asyncio.gather(*(w.run() for w in workers))
    finally:
        await engine.dispose()
```

- [ ] **Step 4: Implement the runs API and the CLI commands**

Create `backend/src/dewpoint/apps/api/routes/runs.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Runs, read-only (spec §8): the list, and one run with its steps. The UI reads this projection, never Temporal
history. Starting runs isn't public until 2b."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.authz.permissions import P
from dewpoint.core.http import TenantContext, get_db, require
from dewpoint.core.models.runs import Run, RunStep
from dewpoint.core.runs import service

router = APIRouter(prefix="/api/v1", tags=["runs"])


def _when(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _run(r: Run) -> dict[str, object]:
    return {
        "id": str(r.id),
        "workflow_id": str(r.workflow_id),
        "version_id": str(r.workflow_version_id),
        "mode": r.mode,
        "status": r.status,
        "started_at": _when(r.started_at),
        "ended_at": _when(r.ended_at),
        "error": {"code": r.error_code, "message": r.error_message} if r.error_code else None,
        "iterations": r.iterations,
    }


def _step(r: RunStep) -> dict[str, object]:
    return {
        "step_id": str(r.step_id),
        "key": r.node_key,
        "iteration_key": r.iteration_key,
        "attempt": r.attempt,
        "status": r.status,
        "started_at": _when(r.started_at),
        "ended_at": _when(r.ended_at),
        "input": r.input_preview,
        "output": r.output_preview,
        "error": {"code": r.error_code, "message": r.error_message} if r.error_code else None,
        "outcome": r.outcome,
        "cel_mode": r.cel_mode,
    }


@router.get("/t/{tenant_id}/runs")
async def list_runs(
    workflow_id: uuid.UUID | None = None,
    before: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> list[dict[str, object]]:
    return [_run(r) for r in await service.list_runs(db, workflow_id=workflow_id, before=before, limit=limit)]


@router.get("/t/{tenant_id}/runs/{run_id}")
async def get_run(
    run_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    run = await service.get_run(db, run_id)
    if run is None or run.tenant_id != ctx.tenant_id:
        raise HTTPException(404, detail={"error": "not_found"})
    return {**_run(run), "steps": [_step(r) for r in await service.run_steps(db, run.id)]}
```

Register the router in `backend/src/dewpoint/apps/api/main.py`:

```diff
diff --git a/backend/src/dewpoint/apps/api/main.py b/backend/src/dewpoint/apps/api/main.py
--- a/backend/src/dewpoint/apps/api/main.py
+++ b/backend/src/dewpoint/apps/api/main.py
@@ -17,6 +17,7 @@
     mfa,
     node_types,
     passkeys,
+    runs,
     tenants,
     workflows,
 )
@@ -62,6 +63,7 @@
         connections.router,
         node_types.router,
         workflows.router,
+        runs.router,
     ):
         app.include_router(router)
     return app
```

Add `dewpoint worker` and `dewpoint dev run` to `backend/src/dewpoint/apps/cli/main.py`:

```diff
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -1,9 +1,11 @@
 # SPDX-License-Identifier: Apache-2.0
 import asyncio
 import base64
+import json
 import os
 import uuid
 from collections.abc import Awaitable, Callable
+from dataclasses import asdict
 from datetime import timedelta
 from pathlib import Path

@@ -11,11 +13,14 @@
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
 from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
+from temporalio.client import Client

 from dewpoint.apps.plugin_loader import PluginLoadError, installed_plugins, prepare
+from dewpoint.apps.runs import NotAdmissibleError, StartRefusedError, StartUncertainError, start_run
+from dewpoint.apps.worker.main import run as run_worker
 from dewpoint.core.audit.anchor import FileAnchorSink, anchor_all, anchor_freshness, verify_anchors
 from dewpoint.core.auth.users import PasswordPolicyError, create_user
-from dewpoint.core.config import get_settings
+from dewpoint.core.config import Settings, get_settings
 from dewpoint.core.crypto.kek import KekSet, UnknownKekError
 from dewpoint.core.crypto.keyring import Keyring
 from dewpoint.core.db import make_engine, make_sessionmaker
@@ -30,6 +35,8 @@
     sync_plugins,
 )
 from dewpoint.engine.cel.profile import CURRENT_CEL_PROFILE
+from dewpoint.engine.runtime.activities import LIVE, SIMULATE, RunResult
+from dewpoint.engine.runtime.workflow import RunGraph
 from dewpoint.sdk import ManifestError

 app = typer.Typer(no_args_is_help=True)
@@ -43,6 +50,8 @@
 app.add_typer(plugins_cli, name="plugins")
 lifecycle_cli = typer.Typer(no_args_is_help=True)
 app.add_typer(lifecycle_cli, name="lifecycle")
+dev_cli = typer.Typer(no_args_is_help=True)
+app.add_typer(dev_cli, name="dev")


 async def _init(email: str, password: str) -> None:
@@ -310,3 +319,80 @@
         typer.echo("forced retirement NOT applied: review the list above, then re-run with --confirm")
         raise typer.Exit(3)
     typer.echo(f"{entry}: retired")
+
+
+@app.command("worker")
+def worker() -> None:
+    """Run the Temporal worker: RunGraph and its activities, and cel.evaluate when DEWPOINT_CEL_SOCKET is set."""
+    asyncio.run(run_worker(get_settings()))
+
+
+async def dev_run_version(
+    settings: Settings,
+    client: Client,
+    *,
+    tenant_id: uuid.UUID,
+    version_id: uuid.UUID,
+    trigger: dict[str, object],
+    simulate: bool = False,
+    wait: bool = True,
+) -> tuple[uuid.UUID, RunResult | None]:
+    engine = make_engine(settings.database_url)
+    try:
+        run_id = await start_run(
+            make_sessionmaker(engine),
+            client,
+            settings,
+            tenant_id=tenant_id,
+            version_id=version_id,
+            trigger=trigger,
+            mode=SIMULATE if simulate else LIVE,
+        )
+    finally:
+        await engine.dispose()
+    if not wait:
+        return run_id, None
+    return run_id, await client.get_workflow_handle_for(RunGraph.run, str(run_id)).result()
+
+
+@dev_cli.command("run")
+def dev_run(
+    version_id: uuid.UUID,
+    tenant: str = typer.Option(..., "--tenant", help="tenant id"),
+    input_file: str | None = typer.Option(None, "--input", help="JSON trigger payload (test data only until 2b)"),
+    simulate: bool = typer.Option(False, "--simulate", help="Plugin steps call simulate(): nothing is sent"),
+    wait: bool = typer.Option(True, "--wait/--no-wait"),
+) -> None:
+    """Start a run of a workflow's active version. Development only: 2b brings admission and triggers."""
+    trigger = json.loads(Path(input_file).read_text()) if input_file else {}
+
+    async def _go() -> tuple[uuid.UUID, RunResult | None]:
+        settings = get_settings()
+        client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
+        return await dev_run_version(
+            settings,
+            client,
+            tenant_id=uuid.UUID(tenant),
+            version_id=version_id,
+            trigger=trigger,
+            simulate=simulate,
+            wait=wait,
+        )
+
+    try:
+        run_id, result = asyncio.run(_go())
+    except NotAdmissibleError as e:
+        for reason in e.reasons:
+            typer.echo(f"ERROR: {reason}")
+        raise typer.Exit(2) from None
+    except StartRefusedError as e:
+        typer.echo(f"ERROR: {e}")
+        raise typer.Exit(1) from None
+    except StartUncertainError as e:
+        typer.echo(f"WARNING: {e}")
+        raise typer.Exit(3) from None
+    typer.echo(f"run {run_id}")
+    if result is not None:
+        typer.echo(json.dumps(asdict(result), indent=2, sort_keys=True))
+        if result.status != "succeeded":
+            raise typer.Exit(1)
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && uv run pytest -q tests/apps/worker tests/apps/cli tests/apps/api`
Expected: all pass, among them the 8 new tests (1 end-to-end through the database and the API, 1 `dev_run_version`,
6 CLI exit codes).

- [ ] **Step 6: Document it**

Create `docs/operations/runs.md`:

````markdown
# Runs: the worker, development runs and the runs API

Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §6 (the interpreter), §8 (projection), §9 (starting
runs).

A run executes one published version of a workflow on Temporal. `RunGraph`, the interpreter, walks the graph: control
nodes (`if`, `switch`, `loop`, …) run inside the workflow, and each attempt of a plugin step runs as an activity.
Every step's progress is copied into the database (`run_steps`), which is what the UI reads; Temporal's own history is
never shown.

**2a runs are internal.** Only `dewpoint dev run` and the tests start runs. Triggers, schedules, webhooks and the
public run API arrive with sub-project 2b, and so do admission control and idempotency keys.

## The worker

`dewpoint worker` polls the `dewpoint-engine` task queue: `RunGraph`, the version loader, the projection, and one
activity per installed plugin node type. It needs:

- `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_worker` role. That role reads versions and writes `runs` and
  `run_steps`, inside the run's tenant only (row-level security).
- `DEWPOINT_TEMPORAL_ADDRESS` (default `localhost:7233`) and `DEWPOINT_TEMPORAL_NAMESPACE` (default `default`).
- `DEWPOINT_CEL_SOCKET` when a `cel-evaluator` runs next to it. The worker then waits for the evaluator, asks which
  CEL profile it serves, and serves `cel.evaluate` on that profile's queue (`dewpoint-cel.<profile>`) with
  `DEWPOINT_CEL_MAX_CONCURRENT` activities at a time (default 2; match the evaluator's slots,
  [`cel-evaluator.md`](cel-evaluator.md)).

Without an evaluator, CEL expressions that can't run inline wait `DEWPOINT_CEL_SCHEDULE_TO_START_S` (default 600
seconds) and then fail the step with `cel_profile_unavailable`. In 2a every CEL expression runs through the evaluator:
inline evaluation is switched on by plan 2a-3c, together with the build's `ENGINE_ABI`.

Docker Compose gains `temporal` and `worker` services, and the worker and dispatch logins, in plan 2a-3c. Until then,
point the worker at any Temporal server.

## Starting a development run

```bash
dewpoint dev run <version-id> --tenant <tenant-id> --input trigger.json
```

- The version must be the **active** version of an **enabled** workflow, and nothing it uses may be retired.
- `--simulate` calls each plugin node's `simulate()` instead of `run()`: nothing is sent anywhere. A node without a
  simulation fails its step with `simulation_unavailable`. Timers still wait, as they would in a live run.
- By default the command waits and prints the result. `--no-wait` prints the run id and returns.
- Exit codes: 0 when the run succeeded; 1 when it ended otherwise, or Temporal refused to start it; 2 when it wasn't
  admitted (each reason is printed); 3 when Temporal never confirmed the start (see below).
- It needs `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_dispatch` role, and the Temporal settings above.

The trigger file is test data: 2a doesn't validate it against the workflow's input schema (2b's triggers will). A
value that breaks the schema fails the step that reads it.

**An unconfirmed start.** A start whose answer is lost looks like a failure, so it's retried with the same workflow id
(the run's id), which Temporal refuses as a duplicate if the first attempt went through. Only a confirmed refusal
records the run as failed (`start_failed`). If no attempt is answered at all, the run may be executing: it stays
`running`, and the command exits 3.

## Reading runs

`GET /api/v1/t/{tenant}/runs` lists runs, newest first (`workflow_id`, `before` and `limit` filter and page them).
`GET /api/v1/t/{tenant}/runs/{run_id}` returns one run with its steps: one row per step, loop iteration and attempt.
The `iteration_key` is the loop step's key and the item's index, like `each_ap:3`, or `outer:1/inner:4` when nested.
Both need the `run.view` permission.

## What the projection shows

Anyone who can view runs can read the projection, so it keeps secrets out:

- A field the node's schema marks sensitive shows as `[redacted]`, however deep: nested models, lists and optional
  values included.
- A sensitive value the run has seen is masked wherever it reappears: copied by a transform, embedded in a template,
  passed to another step, echoed in an error message, a CEL error or a `fail` node's message. The run learns them from
  every field marked sensitive: in nodes' outputs, in nodes' configs (a literal from the start of the run, any other
  value before the step's first attempt), and in the workflow's input schema. Values under 4 characters aren't
  masked, and neither is a secret that CEL has transformed (encoded, sliced): only copies are recognized.
- Messages never quote input: a config or output that doesn't validate names each field and its rule's code
  (`token (value_error)`). A location shows only what the node's schema declares at each place: a field name where
  that field is declared, a position in a list. A map key, numeric or not, and an unknown key show as `*`
  (`headers.* (int_parsing)`). The rule's code is one Pydantic defines; a validator's own error type shows as
  `custom_error`. An unexpected exception, a version this build can't run and an interpreter error name only the
  error's type. The full text goes to the worker's log.
- Previews hold at most 8 KiB of JSON each; a larger one shows as `[truncated]`.

Temporal's own history still holds the values in full until 2b's payload encryption: restrict access to Temporal.

## How a run ends

| Status | Error code | Meaning |
|---|---|---|
| `succeeded` | | Every path finished, or a `stop` node ended the run. |
| `failed` | the step's code | A step failed with `on_error: fail` (the default) outside any loop. |
| `failed` | `workflow_failed` | A `fail` node ended the run. |
| `failed` | `start_failed` | Temporal refused to start it. |
| `failed` | `version_unusable` | This build can't load or run the version, for example a node type it lacks. Nothing ran. |
| `failed` | `internal_error` | A bug in the interpreter. The message names the exception's type, and the worker's log has the details; please report it. |
| `deadline_exceeded` | `deadline_exceeded` | The run passed `DEWPOINT_MAX_RUN_DURATION_DAYS` (default 30). Running steps were cancelled. |
| `cancelled` | `cancelled` | The run was cancelled in Temporal. |

Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation`, `unexpected_error`,
`evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`, `item_cap_exceeded`,
`iteration_cap_exceeded`, `not_supported` and `node_type_unavailable` (the registry lists the node type, but no worker
of this build runs it: install its plugin on the workers).

## Attempts and retries

Each attempt of a plugin step has its own row. The interpreter schedules every attempt itself, following the node's
retry settings (`max_attempts` and `timeout_s` can be overridden per step), and decides whether another follows:

- A node's `RetryableError` and unexpected exceptions are retried, and so are timeouts, unless the node is
  `ambiguous`.
- For an `ambiguous` node, a timeout or a lost worker means the request may have been sent: the attempt records
  `outcome_unknown` and is never repeated. So is an `OutcomeUnknownError`, from any node.
- A `reconcilable` node checks with `reconcile()` before each retry.

## Limits in this build

- At most 100 steps run at once per run.
- Loops over more than 100 items, and `run_workflow` sub-flows, fail their step with `not_supported`: loop batches and
  sub-flows arrive with plan 2a-3b, as do continue-as-new and the workflow failure handler.
- A run counts at most 100,000 loop iterations and filter items (`iteration_cap_exceeded`).

## If the database is unavailable

Plugin steps never write to the database: the interpreter projects every row through one activity, which retries
until the database answers. A step's effect therefore never repeats because of a failed write, rows catch up when the
database is back, and a run's end waits for its summary to be written.
````

Point to it from `README.md`:

```diff
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -44,6 +44,12 @@
 (Docker Compose; Kubernetes support comes with the Helm chart). Sizing, refusals and health:
 [`docs/operations/cel-evaluator.md`](docs/operations/cel-evaluator.md).

+## Runs
+
+Until sub-project 2b brings triggers, runs start only from `dewpoint dev run` and the tests; `dewpoint worker` executes
+them on Temporal. Settings, how a run ends, and this build's limits:
+[`docs/operations/runs.md`](docs/operations/runs.md).
+
 ## Audit integrity

 The `audit-anchor` service writes signed chain heads every 15 minutes. **In production, anchors must live off this
```

- [ ] **Step 7: Checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && git add src/dewpoint/apps src/dewpoint/core/config.py tests/apps ../docs/operations/runs.md ../README.md \
  && git commit -m "feat(apps): the worker, the runs API and dewpoint dev run" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: 865 passed and 8 skipped (the Linux-only evaluator tests).

---

### Task 8: Golden histories

Spec §7's replay discipline starts here (decision 19). The build id comes from `ENGINE_ABI`. Eight scenarios cover
what this plan runs, and the recorder writes their histories to `tests/engine/replay/<build id>/`, once. The suite
replays them against the current `RunGraph`. A change that alters the command sequence fails that replay, and must
bump `ENGINE_ABI`, which starts a new directory. 2a-3c adds the CI gate that replays older builds' histories against
their own builds.

**Files:**
- Create: `backend/src/dewpoint/engine/runtime/build.py`
- Create: `backend/tests/engine/replay/__init__.py` (empty), `scenarios.py`, `record.py`, `test_replay.py`
- Create (recorded): `backend/tests/engine/replay/dewpoint-0.1.0+abi1/*.json`, 8 histories

**Interfaces:**
- Consumes: Task 5's `RunGraph`, `MemoryStore`, `start` and `workers`; `dewpoint.__version__`.
- Produces:
  - `build.py`: `ENGINE_ABI = 1` and `build_id(version) -> str`, which gives `dewpoint-0.1.0+abi1`;
  - `scenarios.py`: `Scenario(graph, trigger, options)` and `scenarios() -> dict[str, Scenario]`, with the scenarios
    `branches`, `loops`, `errors`, `variables_and_timers`, `stop`, `failed`, `simulate` and `deadline`;
  - `record.py`: `build_dir() -> Path`, `scrub(value)` and `record() -> list[str]`, run as
    `uv run python -m tests.engine.replay.record`.

- [ ] **Step 1: Write the failing tests**

Create the empty file `backend/tests/engine/replay/__init__.py`.

Create `backend/tests/engine/replay/scenarios.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The runs every build records as golden histories (spec §7).

2a-3a records what it can run: branches, joins, dead paths and switch; inline loops, filter and transform; every
error policy; variables and timers; stop, fail, simulation and the deadline; CEL through `cel.evaluate`. 2a-3b adds
batched loops, sub-flows and continue-as-new; 2a-3c adds local CEL and the yield-point timer."""

from dataclasses import dataclass, field
from typing import Any

from tests.support.graphs import G, cel, ref

ECHO, IF, SWITCH, LOOP = "testkit.echo@1", "flow.if@1", "flow.switch@1", "flow.loop@1"
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"x": {"type": "integer"}, "names": {"type": "array", "items": {"type": "string"}}},
    "required": ["x", "names"],
}
TRIGGER: dict[str, Any] = {"x": 7, "names": ["ap-1", "sw-1", "ap-2"]}


@dataclass(frozen=True)
class Scenario:
    graph: G
    trigger: dict[str, Any] = field(default_factory=lambda: dict(TRIGGER))
    options: dict[str, Any] = field(default_factory=dict)  # RunInput fields


def _graph(**outputs: Any) -> G:
    g = G()
    g.settings = {"input_schema": SCHEMA, "outputs": outputs}
    return g


def _branches() -> G:
    g = _graph(side=cel("has(steps.yes.output) ? 'yes' : 'no'"), size=ref("steps.big.output.value", default="?"))
    g.node("c", IF, {"condition": cel("trigger.x > 5")}).node("yes", ECHO, {"value": 1}).node("no", ECHO, {"value": 2})
    g.node("j", ECHO, {"value": "joined"}).edge("c", "yes", "true").edge("c", "no", "false")
    g.edge("yes", "j").edge("no", "j")
    cases = [{"port": "small", "when": cel("trigger.x < 5")}, {"port": "big", "when": cel("trigger.x > 5")}]
    g.node("s", SWITCH, {"cases": cases}).node("small", ECHO).node("big", ECHO, {"value": "big"}).edge("j", "s")
    return g.edge("s", "small", "small").edge("s", "big", "big")


def _loops() -> G:
    g = _graph(doubled=ref("steps.l.output.items"), aps=ref("steps.f.output.items"), t=ref("steps.t.output"))
    g.node("l", LOOP, {"items": [1, 2, 3], "concurrency": 2, "collect": cel("item * 2")})
    g.node("x", ECHO, {"value": ref("item")}).edge("l", "x", "body")
    g.node("f", "flow.filter@1", {"items": ref("trigger.names"), "predicate": cel("item.startsWith('ap-')")})
    g.node("t", "flow.transform@1", {"fields": {"n": cel("size(steps.f.output.items)")}})
    return g.edge("l", "f", "done").edge("f", "t")


def _errors() -> G:
    g = _graph(port=ref("steps.p.error.code", default="none"), kept=ref("steps.l.output.failures", default=[]))
    g.node("r", "testkit.fail_n@1", {"failures": 2}).node("u", "testkit.reconcile@1")
    g.node("p", "testkit.ambiguous_send@1", {"outcome": "rejected"}, on_error="port").node("h", ECHO)
    g.node("c", "testkit.ambiguous_send@1", {"outcome": "rejected"}, on_error="continue").edge("p", "h", "error")
    g.node("l", LOOP, {"items": [0, 1], "on_item_error": "continue", "collect": ref("item")})
    g.node("b", "testkit.ambiguous_send@1", {"outcome": cel("item == 1 ? 'rejected' : 'sent'")})
    return g.edge("l", "b", "body")


def _variables_and_timers() -> G:
    g = _graph(count=ref("vars.count"))
    g.settings["vars_schema"] = {"type": "object", "properties": {"count": {"type": "integer", "default": 0}}}
    g.node("d", "flow.delay@1", {"duration_s": 86_400})
    g.node("s", "flow.set_variables@1", {"assignments": {"count": cel("trigger.x + 1")}})
    return g.edge("d", "s")


def _stop() -> G:
    g = _graph(n=1).node("l", LOOP, {"items": [1, 2]}).node("s", "flow.stop@1")
    return g.edge("l", "s", "body")


def _failed() -> G:
    g = _graph().node("a", ECHO, {"value": 1}).node("f", "flow.fail@1", {"message": "no, stop"})
    return g.edge("a", "f")


def scenarios() -> dict[str, Scenario]:
    return {
        "branches": Scenario(_branches()),
        "loops": Scenario(_loops()),
        "errors": Scenario(_errors()),
        "variables_and_timers": Scenario(_variables_and_timers()),
        "stop": Scenario(_stop()),
        "failed": Scenario(_failed()),
        "simulate": Scenario(
            _graph(v=ref("steps.a.output.value")).node("a", ECHO, {"value": 5}), options={"mode": "simulate"}
        ),
        "deadline": Scenario(
            _graph().node("d", "flow.delay@1", {"duration_s": 3 * 86_400}), options={"max_run_duration_s": 86_400}
        ),
    }
```

Create `backend/tests/engine/replay/record.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Record this build's golden histories: `uv run python -m tests.engine.replay.record`.

Only scenarios the build's directory lacks are recorded; a recorded history is never rewritten. A change that alters
the command sequence increments ENGINE_ABI (engine/runtime/build.py), which starts a new directory."""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from temporalio.testing import WorkflowEnvironment

import dewpoint
from dewpoint.engine.runtime.build import build_id
from tests.apps.worker.harness import MemoryStore, start, workers
from tests.engine.replay.scenarios import scenarios

HERE = Path(__file__).parent
SCRUBBED = {"identity": "replay-recorder", "stackTrace": ""}  # host names and local paths stay out of the repo


def scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: SCRUBBED[k] if k in SCRUBBED else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def build_dir() -> Path:
    return HERE / build_id(dewpoint.__version__)


async def record() -> list[str]:
    target = build_dir()
    missing = {name: s for name, s in scenarios().items() if not (target / f"{name}.json").exists()}
    if not missing:
        return []
    target.mkdir(exist_ok=True)
    store = MemoryStore()
    async with await WorkflowEnvironment.start_time_skipping() as env, workers(env.client, store):
        for name, scenario in sorted(missing.items()):
            handle = await start(env.client, store, scenario.graph, scenario.trigger, **scenario.options)
            await handle.result()
            history = await handle.fetch_history()
            data = scrub(json.loads(history.to_json()))
            (target / f"{name}.json").write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return sorted(missing)


def main() -> None:
    recorded = asyncio.run(record())
    print(f"{build_dir().name}: recorded {', '.join(recorded) or 'nothing (all present)'}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

Create `backend/tests/engine/replay/test_replay.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""This build's golden histories replay against this build's `RunGraph` (spec §7). The Replayer needs no server."""

import asyncio
import re
from pathlib import Path

import pytest
from temporalio.client import WorkflowHistory
from temporalio.worker import Replayer

from dewpoint.engine.runtime.workflow import RunGraph
from tests.engine.replay.record import build_dir
from tests.engine.replay.scenarios import scenarios

HISTORIES = sorted(build_dir().glob("*.json"))


def test_every_scenario_is_recorded_for_this_build() -> None:
    assert {p.stem for p in HISTORIES} == set(scenarios()), "run `uv run python -m tests.engine.replay.record`"


def test_recorded_histories_carry_no_host_data() -> None:
    for path in HISTORIES:
        text = path.read_text()
        assert set(re.findall(r'"identity": "([^"]*)"', text)) <= {"replay-recorder"}, path.name
        assert not re.search(r'"stackTrace": "[^"]', text), path.name


@pytest.mark.parametrize("path", HISTORIES, ids=lambda p: p.stem)
async def test_a_golden_history_replays(path: Path) -> None:
    history = WorkflowHistory.from_json(path.stem, await asyncio.to_thread(path.read_text))
    await Replayer(workflows=[RunGraph]).replay_workflow(history)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd backend && uv run pytest -q tests/engine/replay`
Expected: a collection error, `ModuleNotFoundError: No module named 'dewpoint.engine.runtime.build'`.

- [ ] **Step 3: Implement the build id**

Create `backend/src/dewpoint/engine/runtime/build.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The engine's build id (spec §7): `dewpoint-<version>+abi<ENGINE_ABI>`.

ENGINE_ABI increments on any change that can alter `RunGraph`'s command sequence; its golden histories live in
`tests/engine/replay/<build id>/`. A change that leaves it alone must still replay that directory."""

ENGINE_ABI = 1


def build_id(version: str) -> str:
    return f"dewpoint-{version}+abi{ENGINE_ABI}"


__all__ = ["ENGINE_ABI", "build_id"]
```

Run: `cd backend && uv run pytest -q -rs tests/engine/replay`
Expected: `1 failed, 1 passed, 1 skipped`. `test_every_scenario_is_recorded_for_this_build` fails with "run
`uv run python -m tests.engine.replay.record`", and the replay test is skipped with an empty parameter set: nothing is
recorded yet.

- [ ] **Step 4: Record this build's histories**

Run: `cd backend && uv run python -m tests.engine.replay.record && ls tests/engine/replay/dewpoint-0.1.0+abi1`
Expected: `dewpoint-0.1.0+abi1: recorded branches, deadline, errors, failed, loops, simulate, stop, variables_and_timers`,
and 8 JSON files of about 10–50 KB each. Running the recorder again prints `recorded nothing (all present)` and
changes no file (`git status` shows the directory unchanged after the first `git add`).

- [ ] **Step 5: Run the tests, and check that the replay bites**

Run: `cd backend && uv run pytest -q tests/engine/replay`
Expected: 10 passed (the coverage check, the host-data check, and 8 replays).

Then in `workflow.py` change `unit = waiting.pop(0)` to `unit = waiting.pop()`, run the same command, and restore it.
Expected: `test_a_golden_history_replays[errors]` fails with `NondeterminismError` (`TMPRL1100 … Activity type of
scheduled event 'testkit.ambiguous_send.v1' does not match activity type of activity command 'testkit.reconcile.v1'`).
After restoring, 10 passed.

- [ ] **Step 6: Full suite, checks and commit, then pause for checkpoint 3**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pytest -q \
  && uv run pip-licenses --fail-on="GPL;AGPL;LGPL;SSPL;BUSL" --partial-match > /dev/null \
  && git add src/dewpoint/engine/runtime/build.py tests/engine/replay \
  && git commit -m "test(engine): golden histories for build dewpoint-0.1.0+abi1 and their replay" \
       -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Expected: 875 passed and 8 skipped locally (`main` collects 726 tests; this plan adds 157). On Linux the 8
evaluator-limit tests run too. Push only when the owner says so; CI then runs the same suite, downloading the test
server on first use.

---

## Handoff to 2a-3b, 2a-3c and 2b

**2a-3b (scale)** builds on these interfaces:
- **`nodes.decide` returns `not_supported`** for loops over `INLINE_ITEMS` and for `run_workflow`. 2a-3b replaces both
  with child workflows: loop batches of 100 within the loop's concurrency, and pinned sub-flows. It also runs the
  workflow failure handler.
- **The iteration counter** is `Scheduler.iterations`, debited by `debit()` when an iteration or a filter item starts.
  On-demand grants to children draw on it.
- **The in-flight cap** counts units (a step or a `collect`), each with at most one activity outstanding, plus one
  projection. Children count as units.
- **Continue-as-new.**
  - `Scheduler.scopes` keeps every scope, settled iterations included. The snapshot must carry only open scopes and
    loop cursors (§6), so settled iteration scopes need pruning once collected.
  - The deadline timer (`clock` in `_drive`) must be re-armed from the snapshot's deadline.
  - Drain mode stops `_drive` from starting units, and waits for the outstanding ones and the projection.
  - Beyond the scheduler, the snapshot carries the workflow's own state:
    - the learned secrets (`_secrets`), or masking stops after the first continue-as-new;
    - the queued rows (`_rows`), the start times and CEL modes;
    - for a plugin step between attempts, its attempt number and its backoff's wake time.
- **History growth.**
  - Each CEL value is its own `cel.evaluate` request. Batching a step's values into one request would save events if
    the headroom tests call for it.
  - Each retry of a plugin step adds its activity's events and a timer (decision 7), so the headroom arithmetic
    counts `max_attempts`.
- **Golden histories:** add batched loops, sub-flows, every error policy through children, continue-as-new and the
  failure handler as scenarios. A change to the command sequence bumps `ENGINE_ABI`.

**2a-3c (deployment and gates):**
- **Worker Versioning.** `RunGraph` becomes `PINNED`. `engine_worker` gets the deployment options, and its build id is
  `build_id(dewpoint.__version__)`.
- **Compose.** Add the `temporal` and `worker` services, and logins for `dewpoint_worker` and `dewpoint_dispatch` in
  `initdb`. The worker mounts `cel-socket` and sets `DEWPOINT_CEL_SOCKET`; it already waits for the evaluator
  (`evaluator_profile`).
- **Inline CEL.** Gates 4 and 7b come first, then `LOCAL_CEL_PROFILE` and an `ENGINE_ABI` bump together. With inline
  CEL on:
  - a filter over more than 1,000 items must still go to `cel.evaluate` (§6's table);
  - `_evaluate`'s yield timer and `cel_mode = local` get their first tests;
  - gate 4 replays in 5 fresh processes. The same-process replays here can't catch hash-order non-determinism.
- **The CI replay gate** replays each build's directory against its own build (§7). The recorder already refuses to
  rewrite a history.

**2b:**
- validate trigger payloads against the input schema (decision 20);
- the dispatcher retries a start until Temporal confirms or refuses it (decision 22). `start_run` stops after three
  attempts and leaves an unanswered run `running`;
- the payload codec: Temporal's history still holds sensitive values in full (decision 21);
- the claim check: an output over Temporal's payload limit (2 MB) fails its activity completion today;
- run retention;
- paging for the public runs API by `(started_at, id)`: today's `before` is a timestamp, so runs that started in the
  same microsecond can straddle a page.

## Self-review: spec coverage

| Spec | Requirement | Where |
|---|---|---|
| §6 | inputs: run, version, trigger, deadline = started_at + max_run_duration | Task 4 (`RunInput`), Task 5 |
| §6 | the version loaded by one local activity, immutable for the run | Task 5 (`dewpoint.load_version`, `compile_program`) |
| §6 | scopes, edge and node states, resolution, readiness, dead paths, joins | Task 1 (unit and property tests) |
| §6 | loops: a scope per item, settle, `done` edges, outer values visible | Tasks 1, 2 (`view`), 5 |
| §6 | `stop` and `fail` end the run and cancel in-flight work | Tasks 1, 5 (decision 15) |
| §6 | one scheduler loop, ready queue by (scope, topological index), in-flight cap 100 | Tasks 1, 5 (decision 13) |
| §6 | control nodes, time nodes (durable timers; dynamic waits past the deadline end the run) | Tasks 2, 5 (decision 14) |
| §6 | loops ≤ 100 items inline; filter per item, batched `cel.evaluate` in chunks of 1,000; transform per field | Tasks 2, 5; more than 100 items: 2a-3b (decision 4) |
| §6 | sub-flows | 2a-3b (decision 4) |
| §6 | plugin nodes as activities `type.vN`, retry and timeout from the manifest, overridable per node | Tasks 4, 5 (decision 7) |
| §6 | errors: `fail`, `continue`, `port`; `OutcomeUnknownError` never retried | Tasks 1, 4, 5 (decisions 1, 3, 7) |
| parent §6.6 | an ambiguous request is never repeated, a timeout after the send included | Tasks 4, 5 (decision 7) |
| §6 | failure handler, continue-as-new, drain mode, snapshot, grants | 2a-3b |
| §6 | one iteration counter per logical run, debited when an item starts | Task 1 (`debit`, the cap); grants: 2a-3b |
| §6 | workflow-code rules: no clock, randomness or I/O; no set iteration; ordered dicts | Task 1 (contract), Task 5 (`workflow.now`, `workflow.wait`, sandbox) |
| §7 | golden histories per build; the replay gate; `engine_abi` | Task 8 (decision 19); the CI gate across builds: 2a-3c |
| §7 | Worker Versioning, Compose services, two-build test | 2a-3c |
| §8 | `runs` and `run_steps` columns, statuses, outcomes, CEL mode | Task 3 (decision 17) |
| §8 | writes: a batched projection, keyed per attempt; control nodes at each await | Task 5 (decisions 12, 13): the projection is the only writer |
| §8 | redaction of `x-sensitive` fields | Tasks 2, 5 (decision 21): through `$ref`s and unions, plus masking of learned values |
| §8 | the worker role inside `tenant_scope`; redaction; truncation; the read API | Tasks 7, 2, 7 |
| §9 | `start_run` for tests and the dev CLI; no public run API | Tasks 6, 7 (decisions 20, 22) |
| §4.5 | admission under shared lifecycle locks, in the transaction that inserts the run; the workflow read under its admission lock | Task 6 (decision 23) |
| §5.7 | a missing evaluator times out to `cel_profile_unavailable` | Task 5 (decision 6) |
| §10 | interpreter tests: every node kind and error policy, `on_item_error`, the deadline | Tasks 1, 5; batching, sub-flows, continue-as-new: 2a-3b; yield points: 2a-3c |
| §10 | property tests: once per scope, dead paths never run, same-scope joins, no pending edge | Task 1 |
| 2a-2 handoff | presence contract; defaults replace missing and null; `dump_output`; routing and yields; the `cel.evaluate` wiring; sandbox passthrough; filter batching; the `collect` decision | Tasks 2, 4, 5 (decisions 1, 2, 5, 6); the local path and gates 4 and 7b: 2a-3c |

Placeholder scan: every code step shows its code, and every command its expected output. Type consistency: the names
in each Interfaces block match the code shown, and the plan's code is the prototype's code, stage by stage.
