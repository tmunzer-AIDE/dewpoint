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
- `DEWPOINT_WORKER_SHUTDOWN_GRACE_S` (default 30): a stopping worker lets running attempts finish this long, then
  cancels them. A cancelled attempt ends as on a lost worker: `outcome_unknown` for an `ambiguous` node. Give the
  process manager a stop timeout longer than this.

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
| `deadline_exceeded` | `deadline_exceeded` | The run passed `DEWPOINT_MAX_RUN_DURATION_DAYS` (default 30). Running steps were cancelled. |
| `cancelled` | `cancelled` | The run was cancelled in Temporal. A cancel that arrives while the run's end is being written leaves that end. |

Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation`, `unexpected_error`,
`evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`, `item_cap_exceeded`,
`iteration_cap_exceeded`, `not_supported` and `node_type_unavailable` (the registry lists the node type, but no worker
of this build runs it: install its plugin on the workers).

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

- At most 100 steps run at once per run.
- Loops over more than 100 items, and `run_workflow` sub-flows, fail their step with `not_supported`: loop batches and
  sub-flows arrive with plan 2a-3b, as do continue-as-new and the workflow failure handler.
- A run counts at most 100,000 loop iterations and filter items (`iteration_cap_exceeded`).
- `flow.delay` waits 0 to 30 days, and `wait_until` takes instants from year 1 to 9999 in UTC. A value outside that,
  resolved at run time, fails the step with `type_mismatch`.

## If the database is unavailable

Plugin steps never write to the database: the interpreter projects every row through one activity, which retries
until the database answers. A step's effect therefore never repeats because of a failed write, rows catch up when the
database is back, and a run's end waits for its summary to be written. A backlog is written in batches of at most
256 KiB. A row the database refuses for its data (SQLSTATE class 22 or 23) is logged in the worker's log and
skipped, so the other rows, and the run's end, still land.
