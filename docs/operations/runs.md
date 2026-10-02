# Runs: the worker, development runs and the runs API

Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §6 (the interpreter), §8 (projection), §9 (starting
runs), and `2026-09-29-engine-2b-design.md` §3–§5 (claims, taint, sizes).

A run executes one published version of a workflow on Temporal. `RunGraph`, the interpreter, walks the graph: control
nodes (`if`, `switch`, `loop`, …) run inside the workflow, and each attempt of a plugin step runs as an activity.
Every step's progress is copied into the database (`run_steps`), which is what the UI reads; Temporal's own history is
never shown.

**2a runs are internal.** Only `dewpoint dev run` and the tests start runs. Triggers, schedules, webhooks and the
public run API arrive with sub-project 2b, and so do admission control and idempotency keys.

## The worker

`dewpoint worker` polls the `dewpoint-engine` task queue: the `RunGraph` and `LoopBatch` workflows, the version
loader, the projection, and one activity per installed plugin node type. It needs:

- `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_worker` role. That role reads versions and the tenant's data
  keys, writes `runs` and `run_steps`, and reads and writes claims (`run_inputs`, `step_outputs`, `claim_grants`) and
  the secret index (`run_secret_index`), inside the run's tenant only (row-level security); it also records the
  instance in `worker_instances`.
- `DEWPOINT_TEMPORAL_ADDRESS` (default `localhost:7233`) and `DEWPOINT_TEMPORAL_NAMESPACE` (default `default`), the
  namespace this deployment recorded ([`deployment.md`](deployment.md)): on any other, or with none recorded, the worker
  exits 2 before it connects.
- The KEK (`DEWPOINT_KEK_B64`, `DEWPOINT_KEK_ID`): every payload it exchanges with Temporal, and every claim it
  stores, is encrypted with its tenant's data key. It checks its KEK and its role's grants at startup and every 30
  seconds, and exits 3 when the check fails ([`deployment.md`](deployment.md#worker-health)).
- `DEWPOINT_CEL_SOCKET` when a `cel-evaluator` runs next to it. The worker then waits for the evaluator, asks which
  CEL profile it serves, and serves `cel.evaluate` on that profile's queue for its build's engine ABI
  (`dewpoint-cel.abi<engine ABI>.<profile>`) with
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
- Exit codes: 0 when the run succeeded; 1 when it ended otherwise, or its start was refused (by Temporal, or because
  it couldn't be encrypted); 2 when it wasn't admitted (each reason is printed: in a `production` deployment,
  "Production runs are off in this deployment"; a trigger that doesn't match the workflow's input schema, each place
  and rule it breaks, never a value; a trigger that holds the key `$claim`; a `dewpoint` of another engine ABI than
  the current build's, [`deployment.md`](deployment.md)); 3 when Temporal never confirmed the start (see below).
- It needs `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_dispatch` role, the Temporal settings above, and the
  KEK: it encrypts the trigger's claims and the start with the tenant's data key.

The trigger is checked against the version's input schema when the run is admitted, then claimed
([below](#sensitive-and-large-values-claims)): its sensitive values, the positions its schema doesn't declare, and any
value over 64 KiB are stored encrypted in `run_inputs`, and the run starts with handles in their place. A refused
trigger leaves no run.

**An unconfirmed start.** A start whose answer is lost looks like a failure, so it's retried with the same workflow id
(`t:<tenant>:run:<run id>`), which Temporal refuses as a duplicate if the first attempt went through. A run is recorded
as failed (`start_failed`) only when its start certainly never began: Temporal refused it, or the start couldn't be
encrypted, so it was never sent (for example, the tenant has no data key: `dewpoint keys ensure-tenants` gives it
one). If no attempt is answered at all, the run may be executing: it stays `running`, and the command exits 3.

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
- **A loop's output.** `failures` lists the failed iterations in index order (before ABI 6, in the order they failed).
  A loop whose collected values outgrew the run's live state, or that collected more than 64 KiB, outputs them as one
  claim: `steps.<loop>.output.items` is its handle, and `items[3]` reads into it as into any list.
- **Nested loops wait for room.** An execution opens at most 100 loop iterations at once (fewer when publish computed a
  smaller bound for a large workflow), plus one per nesting level kept for the oldest. A loop inside an iteration
  starts once it can open an iteration, and reads the variables as they were when it became ready.
- **One budget per run.** The 100,000 loop iterations and filter items a run may use are shared by everything it
  starts: its batches, its sub-flows (and theirs), and its failure handler. A child that needs more asks its parent;
  a request waits while another child may still give budget back, and is refused only when nothing is left anywhere.

## Sensitive and large values: claims

A sensitive value never enters a run's workflow, nor Temporal's history. It's a **claim**: a row stored encrypted with
the tenant's data key (`run_inputs` for what a run is given, `step_outputs` for what it produces), and the run holds a
**handle** in its place, `{"$claim": "<claim id>"}`, with a `pointer` when it addresses a part of the value. Large
values travel the same way. A handle tells nothing but the claim's id: a run's outputs and its rows show handles where
claims are.

- **What's claimed.** A run's input when it's admitted, a sub-flow's input before it starts, and a plugin step's output
  before it leaves the step's activity: every value at a position the schema marks `x-sensitive`, and every position
  it doesn't declare (unknown counts as sensitive: `additionalProperties`, pattern properties, a key one branch of a
  union leaves open); text that repeats a secret the run already knows; and any value over 64 KiB, claimed for its
  size. What CEL or a template returns from `cel.evaluate` is claimed when it read sensitive data, when it repeats a
  known secret, or when it's over 64 KiB.
- **Where a claim is read.** Only in an activity, by the run that owns it or was granted it. A plugin step gets its
  input with every handle resolved. CEL or a template that reads a handle runs in the evaluator (`cel_mode`
  `activity`), and so does CEL that indexes trigger or step data by a computed key or position. A reference further
  into a handle extends its pointer without reading the claim.
- **Decisions.** Where sensitive data decides something the run can see — a `flow.if` condition, a switch case's
  `when`, a loop's items (their count) or a filter's items or predicate — the workflow lists the site in
  `graph.settings.declassify`, and the decision is made where the claim is read. Publishing such a workflow needs the
  `workflow.declassify` permission (tenant admins and owners), and its audit entry lists what each site reveals. A loop
  over a list itself (`trigger.rows`) needs no entry: a list's length isn't secret. A loop over a list held as a handle
  gets each item as a handle into it. A filter over sensitive data runs whole in one
  activity: the run sees the kept items' handle and the two counts, never a decision per item.
- **Sub-flows and failure handlers.** A sub-flow's input is checked against the child's input schema
  (`input_invalid` when it doesn't match) and claimed as a trigger is, and the child is granted the parent's claims it
  holds; a sub-flow grants its parent the claims in its outputs. A failure handler is granted what its trigger holds.
- **The secret index.** Every string of 4 characters or more in a sensitive claim joins its run tree's index (the run,
  its sub-runs and its batches share one), stored encrypted. Every message leaving an activity (a step's error, a CEL
  error, a `fail` node's message) and every row the projection writes is masked against it. It holds at most 100,000
  strings or 8 MiB: the admission or step that would pass that fails with `secret_index_limit`.
- **What masking can't see.** A secret that CEL has transformed (encoded, sliced) is no longer the same text. A CEL
  result the workflow computes from plain data is history like any plain value, and isn't checked against the index;
  whatever leaves an activity is.

## Long runs

A run whose Temporal history passes 2,000 events carries on as a new Temporal execution (continue-as-new) at the next
point where no activity and no child is outstanding: nothing is cancelled or repeated, and a timer keeps its wake
time. Past 4,000 events, or when Temporal suggests it, the run drains: it starts nothing new, waits for what's
outstanding, then continues. The run keeps its id, its rows and its budget; only Temporal's history starts afresh.

## What the projection shows

Anyone who can view runs can read the projection, so it keeps secrets out:

- A field the node's schema marks sensitive shows as `[redacted]`, however deep: nested models, lists and optional
  values included.
- A sensitive value shows as its handle. Text that repeats a secret of the run tree's index is masked as
  `[redacted]` wherever it reappears: copied by a transform, embedded in a template, passed to another step, echoed in
  an error message, a CEL error or a `fail` node's message. The index learns from every sensitive claim (the input's,
  the outputs') and from nodes' configs, whose sensitive fields are indexed before the step's attempt. Values under 4
  characters aren't masked, and neither is a secret that CEL has transformed (encoded, sliced): only copies are
  recognized.
- Messages never quote input: a config or output that doesn't validate names each field and its rule's code
  (`token (value_error)`). A location shows only what the node's schema declares at each place: a field name where
  that field is declared, a position in a list. A map key, numeric or not, and an unknown key show as `*`
  (`headers.* (int_parsing)`). The rule's code is one Pydantic defines; a validator's own error type shows as
  `custom_error`. An unexpected exception, a version this build can't run and an interpreter error name only the
  error's type ([the worker's log](#what-the-workers-log-shows) records where it was raised).
- Previews hold at most 8 KiB of JSON each; a larger one shows as `[truncated]`.
- Characters Postgres can't store (NUL, lone surrogates) show as U+FFFD, and a number JSON can't hold (NaN,
  infinity) as its name.

Temporal's own history holds every payload encrypted with the tenant's data key: its Web UI shows ciphertext. A run's
workflow id is `t:<tenant>:run:<run id>`, a sub-flow's and a failure handler's too
([`deployment.md`](deployment.md#encrypted-payloads)).

## What the worker's log shows

The worker's log holds no text a run's data could have written unless it's proven to be code. A secret a plugin makes
itself, such as a token an API has just issued, is in no secret index until the step's output is claimed, so masking
can't catch it there:

- A plugin's `ctx.log` keeps an event, a field's name and a field's value only when each is a constant written in the
  plugin's own source, a boolean or null. A computed event is logged as `step_event_withheld`, a computed field name
  is dropped (`fields_withheld` counts them), and any other value, a number included, shows as `[redacted]`. A field
  whose name looks secret (`password`, `token`, …) is redacted even then. Log `"token_refreshed"`, not
  `f"refreshed {token}"`.
- A bug in a node (an unexpected exception, a validator's or the claim store's failure) is logged with its type and
  where it was raised (`where`: file, function and line), and with its text only when that's a constant of the
  plugin.
- Temporal's own record of a failed attempt keeps the error's code and drops its text and traceback; its records that
  would quote an error or heartbeat details are withheld.

A plugin's own failure message (`FatalError`, `RetryableError`, `OutcomeUnknownError`) is its step's error: it's
masked against the run tree's index and shown in the projection, so it must not quote a secret the run doesn't know.

## How a run ends

| Status | Error code | Meaning |
|---|---|---|
| `succeeded` | | Every path finished, or a `stop` node ended the run. |
| `failed` | the step's code | A step failed with `on_error: fail` (the default) outside any loop. |
| `failed` | `workflow_failed` | A `fail` node ended the run. |
| `failed` | `start_failed` | It never started: Temporal refused it, or its start couldn't be encrypted and was never sent. |
| `failed` | `version_unusable` | This build can't load or run the version, for example a node type it lacks. Nothing ran. |
| `failed` | `internal_error` | A bug in the interpreter. The message names the exception's type, and the worker's log has the details, or says the result was too large to return; please report it. |
| `failed` | `payload_too_large` | The run's outputs were too large to return (over 1.75 MiB once encrypted). A step or a loop fails with the same code, below. |
| `failed` | `snapshot_too_large` | The run's state was too large to carry on as a new Temporal execution (over 1.5 MiB). |
| `failed` | `terminated` | A sub-run that an operator terminated in Temporal. It couldn't record its end, so its parent did, and the step or loop that started it failed with the same code. |
| `deadline_exceeded` | `deadline_exceeded` | The run passed `DEWPOINT_MAX_RUN_DURATION_DAYS` (default 30). Running steps were cancelled. |
| `cancelled` | `cancelled` | The run was cancelled in Temporal. A cancel that arrives while the run's end is being written leaves that end. |

Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation` (an output holding the
key `$claim` too), `unexpected_error`, `evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`,
`input_too_large`, `item_cap_exceeded`, `iteration_cap_exceeded`, `node_type_unavailable` (the registry lists the node
type, but no worker of this build runs it: install its plugin on the workers), `payload_too_large`,
`claim_unavailable` (a claim the run may not read or that isn't there, or the step's output couldn't be stored as
claims after the node ran: its effect happened, and its row says so), `secret_index_limit` and `input_invalid` (a
sub-flow's input that doesn't match the child's input schema). A sub-flow step fails with its sub-flow's code, and with `terminated`
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
- A database outage longer than 5 minutes fails attempts too. A worker can't read a tenant's data key once its cached
  copy is 5 minutes old, so an attempt that starts or ends then fails as above: retried, or `outcome_unknown` for an
  `ambiguous` node ([`deployment.md`](deployment.md#encrypted-payloads)).

## Limits in this build

- At most 100 steps, batches and sub-flows run at once per run (and per child).
- A run counts at most 100,000 loop iterations and filter items, its children's included (`iteration_cap_exceeded`).
- Everything a run sends Temporal, or returns, is checked where it's produced, against 1.75 MiB once encrypted
  (Temporal's limit is 2 MiB), never a stuck run. A step's input, a sub-flow's input, a failure handler's trigger and
  a batch's item that wouldn't fit have their largest values spilled into claims first, and the receiver reads them
  whole; what still doesn't fit fails with `payload_too_large`. A step's output over 64 KiB is claimed at its
  boundary. The run's outputs aren't spilled: too large fails the run with `payload_too_large`.
- An execution keeps at most 1 MiB of values in its own state (results, items, collected values, failures, variables).
  Past that, the largest go to claims, read back by handle, and a step is sent at most 1 KiB of its input inline, the
  rest as handles it resolves. A claim the run can't write fails the run.
- A run continues as a new Temporal execution when its history grows long. Publish computes each version's bound on
  open iterations so that its state fits 1.5 MiB (`version.unbounded` refuses one that can't), and `snapshot_too_large`
  remains the guard (a batch fails its loop).
- A run tree's secret index holds at most 100,000 strings or 8 MiB (`secret_index_limit`).
- A workflow task sends at most 3 MiB of payloads, so its completion stays under Temporal's 4 MiB message limit: more
  wait for the next task.
- `flow.delay` waits 0 to 30 days, and `wait_until` takes instants from year 1 to 9999 in UTC. A value outside that,
  resolved at run time, fails the step with `type_mismatch`.

## If the database is unavailable

Plugin steps never write to the database: the interpreter projects every row through one activity, which retries
until the database answers. A step's effect therefore never repeats because of a failed write, rows catch up when the
database is back, and a run's end waits for its summary to be written. A backlog is written in batches of at most
256 KiB. A row the database refuses for its data (SQLSTATE class 22 or 23) is logged in the worker's log and
skipped, so the other rows, and the run's end, still land.
