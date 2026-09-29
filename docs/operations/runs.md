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

`dewpoint worker` polls the `dewpoint-engine` task queue: the `RunGraph` and `LoopBatch` workflows, the version
loader, the projection, and one activity per installed plugin node type. It needs:

- `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_worker` role. That role reads versions and writes `runs` and
  `run_steps`, inside the run's tenant only (row-level security).
- `DEWPOINT_TEMPORAL_ADDRESS` (default `localhost:7233`) and `DEWPOINT_TEMPORAL_NAMESPACE` (default `default`).
- `DEWPOINT_CEL_SOCKET` when a `cel-evaluator` runs next to it. The worker then waits for the evaluator, asks which
  CEL profile it serves, and serves `cel.evaluate` on that profile's queue (`dewpoint-cel.<profile>`) with
  `DEWPOINT_CEL_MAX_CONCURRENT` activities at a time (default 2; match the evaluator's slots,
  [`cel-evaluator.md`](cel-evaluator.md)).
- `DEWPOINT_WORKER_SHUTDOWN_GRACE_S` (default 30): a stopping worker lets running attempts finish this long, then
  cancels them. A cancelled attempt ends as on a lost worker: `outcome_unknown` for an `ambiguous` node. Give the
  process manager a stop timeout longer than this.
- `DEWPOINT_WORKER_SET_CURRENT` (default off): the worker makes its own build the one new runs start on. Only where
  one build runs at a time, as in Docker Compose; elsewhere, promote builds with `dewpoint deployment set-current`
  ([`deployment.md`](deployment.md)).

This build evaluates CEL of its own profile in the workflow: an expression that publish classified as inline, on
values within the caps (64 KiB, 200 list elements or map entries, 16 KiB strings), runs in-process, and its step's
`cel_mode` says `local`. Everything else goes to the evaluator (`cel_mode` `activity`): what publish classified as
"Runs as a separate step", values past the caps, and a filter over more than 1,000 items (in requests of 1,000). A
workflow task does a bounded amount of CEL work, binding included; past it, the run yields to the next task with a 1 ms
timer, so no task runs long enough to time out.

Without an evaluator, CEL expressions that can't run inline wait `DEWPOINT_CEL_SCHEDULE_TO_START_S` (default 600
seconds) and then fail the step with `cel_profile_unavailable`.

The engine worker is its build's version of the `dewpoint-engine` Worker Deployment, and a run finishes on the build it
started on. Rolling out a build, and what Docker Compose runs (Temporal's dev server and one worker):
[`deployment.md`](deployment.md).

## Starting a development run

```bash
dewpoint dev run <version-id> --tenant <tenant-id> --input trigger.json
```

- The version must be the **active** version of an **enabled** workflow, and nothing it uses may be retired. It,
  and the sub-flows and failure handler it runs, must have been published for the engine ABI of the deployment's
  current build, where the run starts ([`deployment.md`](deployment.md)).
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

`GET /api/v1/t/{tenant}/runs` lists top-level runs, newest first (`workflow_id`, `before` and `limit` filter and page
them). `GET /api/v1/t/{tenant}/runs/{run_id}` returns one run with its steps (one row per step, loop iteration and
attempt) and its `children`: the sub-runs it started. The `iteration_key` is the loop step's key and the item's index,
like `each_ap:3`, or `outer:1/inner:4` when nested. Both need the `run.view` permission.

Every run has a `kind`. A sub-flow's run (`subflow`) and a failure handler's (`failure_handler`) are runs of their
own, with their own steps, and point at the run that started them (`parent_run_id`, and for a sub-flow the step and
iteration that ran it). Their own id opens them like any other run. A sub-run's row appears as soon as it starts,
before its version loads, so a sub-run that ends right away still shows, with its end. A cancelled sub-run says
`cancelled` here, but Temporal shows its workflow as completed: it returns what it used to its parent instead of
ending as cancelled.

## Sub-flows, failure handlers and large loops

- **A `run_workflow` step** runs the workflow version it was pinned to at publish, as a child run. The child's outputs
  are the step's output; its failure fails the step, with the child's error code and message, and the step's own
  `on_error` applies. A sub-flow shares its parent's deadline, and nests at most 5 deep.
- **A workflow's failure handler**, when it has one, runs once when a run of it fails or passes its deadline (not when
  it's cancelled), as a child run whose trigger is `{run_id, workflow_id, version_id, error: {code, message}}`. It
  gets its own deadline. The run's end is decided when it fails, but the run shows `running` until its handler has
  finished; then its end is recorded, counting the handler's iterations. The handler's end doesn't change the
  run's, and neither does a cancel while it runs: that cancels the handler. A failure handler's own failure runs no
  handler.
- **A loop over more than 100 items** runs in batches of 100, each a child workflow, one batch at a time; inside a
  batch, the items run with the loop's own concurrency. Its iterations' rows, keys and results are the same as if
  they had run inline, and its `on_item_error` works across batches.
- **One budget per run.** The 100,000 loop iterations and filter items a run may use are shared by everything it
  starts: its batches, its sub-flows (and theirs), and its failure handler. A child that needs more asks its parent;
  a request waits while another child may still give budget back, and is refused only when nothing is left anywhere.

## Long runs

A run whose Temporal history passes 2,000 events carries on as a new Temporal execution (continue-as-new) at the next
point where no activity and no child is outstanding: nothing is cancelled or repeated, and a timer keeps its wake
time. Past 4,000 events, or when Temporal suggests it, the run drains: it starts nothing new, waits for what's
outstanding, then continues. The run keeps its id, its rows and its budget; only Temporal's history starts afresh.

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
- Characters Postgres can't store (NUL, lone surrogates) show as U+FFFD, and a number JSON can't hold (NaN,
  infinity) as its name.

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
| `failed` | `terminated` | A sub-run that an operator terminated in Temporal. It couldn't record its end, so its parent did, and the step or loop that started it failed with the same code. |
| `deadline_exceeded` | `deadline_exceeded` | The run passed `DEWPOINT_MAX_RUN_DURATION_DAYS` (default 30). Running steps were cancelled. |
| `cancelled` | `cancelled` | The run was cancelled in Temporal. A cancel that arrives while the run's end is being written leaves that end. |

Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation`, `unexpected_error`,
`evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`, `item_cap_exceeded`,
`iteration_cap_exceeded` and `node_type_unavailable` (the registry lists the node type, but no worker of this build
runs it: install its plugin on the workers). A sub-flow step fails with its sub-flow's code, and with `terminated`
when an operator terminated the sub-flow; a loop fails with `terminated` when one of its batches was.

## Attempts and retries

Each attempt of a plugin step has its own row. The interpreter schedules every attempt itself, following the node's
retry settings (`max_attempts` and `timeout_s` can be overridden per step), and decides whether another follows:

- A node's `RetryableError` and unexpected exceptions are retried, and so are timeouts, unless the node is
  `ambiguous`.
- For an `ambiguous` node, a timeout, a lost or stopping worker, or any failure the step's activity didn't describe
  itself means the request may have been sent: the attempt records `outcome_unknown` and is never repeated. So is an
  `OutcomeUnknownError`, from any node.
- A config or output check that fails with something other than a validation error (a validator's bug) fails the
  step as `config_invalid` or `output_schema_violation`, never retried.
- A `reconcilable` node checks with `reconcile()` before each retry.

## Limits in this build

- At most 100 steps, batches and sub-flows run at once per run (and per child).
- A run counts at most 100,000 loop iterations and filter items, its children's included (`iteration_cap_exceeded`).
- A batch's or a sub-flow's input, and a run's continue-as-new snapshot, travel through Temporal, whose payloads are
  limited to 2 MiB: a loop body that reads very large outside values, or a very large loop, can pass it until 2b's
  claim check.
- `flow.delay` waits 0 to 30 days, and `wait_until` takes instants from year 1 to 9999 in UTC. A value outside that,
  resolved at run time, fails the step with `type_mismatch`.

## If the database is unavailable

Plugin steps never write to the database: the interpreter projects every row through one activity, which retries
until the database answers. A step's effect therefore never repeats because of a failed write, rows catch up when the
database is back, and a run's end waits for its summary to be written. A backlog is written in batches of at most
256 KiB. A row the database refuses for its data (SQLSTATE class 22 or 23) is logged in the worker's log and
skipped, so the other rows, and the run's end, still land.
