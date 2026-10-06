# Runs: admission, the dispatcher, the worker and the runs API

Spec: `docs/superpowers/specs/2026-09-25-engine-core-design.md` §6 (the interpreter), §8 (projection), §9 (starting
runs), and `2026-09-29-engine-2b-design.md` §3–§5 (claims, taint, sizes) and §7 (admission and dispatch).

A run executes one published version of a workflow on Temporal. `RunGraph`, the interpreter, walks the graph: control
nodes (`if`, `switch`, `loop`, …) run inside the workflow, and each attempt of a plugin step runs as an activity.
Every step's progress is copied into the database (`run_steps`), which is what the UI reads; Temporal's own history is
never shown.

A run starts as a **request**: the run API and `dewpoint dev run` admit it, in their own transaction, and
`dewpoint dispatcher` starts it on Temporal within its tenant's slots. Nothing else starts a run: a CSV start and a
schedule's tick are admitted the same way ([below](#starting-a-run-from-a-csv), [schedules](#schedules)), and so is a
webhook's event, by the dispatcher ([webhook ingress](ingress.md)).

## Starting a run

`POST /api/v1/t/{tenant}/workflows/{workflow}/runs`, with the `run.start` permission (operators and up), an
`Idempotency-Key` header (at most 255 characters; without one, 428 `idempotency_key_required`) and the body
`{"input": {...}, "mode": "live" | "simulate"}`, admits a request and answers 202 with it, `queued`. The API never
talks to Temporal.

- The same key with the same body returns the same request, as it is now; another body under the key is 409
  `idempotency_conflict`. Retrying after a lost answer is safe. A key is recognized only while its request is stored:
  past the request's retention cutoff a retry admits nothing and answers 410 `request_not_retained`, and once
  retention deletes the request the key is free again, so a retry under it admits a new request
  ([retention](retention.md)).
- Admission takes the workflow's active version, if the workflow is enabled, and freezes it in the request. It checks
  the deployment's environment is recorded and, in `production`, that production runs are on; that the dispatcher
  recorded a current build within the last 2 minutes, of the version's engine ABI; that nothing the version uses is
  retired; and the input, against the version's input schema. Then it claims the input, as any run's
  ([below](#sensitive-and-large-values-claims)), and keeps the request's input, with handles in place of its claimed
  values, encrypted beside them (its trigger envelope).
- A refusal answers with its code and fixed messages that never quote a value: 503 `production_runs_disabled`,
  `environment_not_recorded`, `no_current_build` or `key_unusable` (the tenant's data key can't be read); 422
  `input_invalid` or `secret_index_limit`, with each place and rule the input breaks; 409 `workflow_disabled`,
  `not_active`, `version_unusable`, `node_type_retired`, `cel_profile_retired` or `tenant_erasing`; 404 for a workflow
  that isn't the tenant's. A refused start leaves no request.

`GET /api/v1/t/{tenant}/workflows/{workflow}/start-form` (`run.start`) describes the active version's input for a
form: its typed top-level fields, each with its `type`, whether it's `required`, its `title`, `description`, `enum`
and `default`, and `x-dewpoint-picker` as `picker`. A sensitive field never shows a value its schema holds:
`default_masked` and `enum_masked` say there is one. 409 `not_active` without an active version.

## Starting a run from a CSV

A workflow that takes a file declares it in `graph.settings.csv`: its columns (the header, a variable name, a type
among `string`, `integer`, `number`, `boolean`, `mac`, `ip`, `cidr` and `enum`, whether it's required, a default, and
whether it's sensitive) and its caps, `max_rows` and `max_bytes`, at most the platform's 10,000 rows and 5 MiB. The run
sees `trigger.rows` (one object per row, each column by its name) and `trigger.row_count`.

- **Publish checks the declaration:** unique headers and identifier names; an enum's values, and only an enum's; a
  default that's its type's canonical value (`mac` in lowercase colon form, `ip` and `cidr` as Python's `ipaddress`
  writes them), never beside `required`. A sensitive column takes neither a default nor `values`: both would be
  written into the workflow in plain text. `rows` and `row_count` are reserved: no input schema may declare them, and
  no caller may send them. A CSV workflow's input schema stays plain at its root (`type`, `properties`, `required`,
  `additionalProperties`, `$defs` and annotations), since any other root keyword could refuse the rows. Such a workflow
  is started only with its file: it can't be a sub-flow, a failure handler or scheduled.
- **Uploading:** `POST /api/v1/t/{tenant}/workflows/{workflow}/csv-uploads` (`run.start`) with the file as a raw
  `text/csv` body, read as it arrives and refused one byte past the declaration's `max_bytes` (413 `too_large`). It's
  read as data only: UTF-8 with an optional BOM, the delimiter detected among comma, semicolon and tab, strict quoting,
  unique headers, a field as long as the file allows. A file that can't be read is 422 with its code (`csv_encoding`,
  `csv_empty`, `csv_duplicate_header`, `csv_malformed`, `csv_too_many_rows`, `csv_too_large`). The file is staged,
  encrypted, for one hour, for its uploader only. The answer gives the headers, the proposed mapping (declared names to
  headers), what keeps it from building rows, a preview of the first rows without the sensitive columns, and the
  first 100 errors with their count, each a row number, a column and a code, never a cell.
- **The saved default mapping:** `PUT …/workflows/{workflow}/csv-mapping` (`trigger.manage`) saves one per workflow,
  encrypted. An upload proposes it while it fits the active version's declaration; one a later version no longer fits
  is reported `stale`, with each column's code, and never applied, until a new one is saved.
- **Starting:** the run API's body takes `"csv": {"upload_id", "mapping", "skip_invalid"}` beside `input`. The rows are
  built against the version the request freezes: each cell converted to its type (an empty one is its default, or
  `required`); with `skip_invalid`, a row that breaks a rule is skipped and recorded, else the start is refused
  (`input_invalid`, naming the first rows, columns and codes). Sensitive cells are claimed as any sensitive value is.
  The upload is used once: its retry under the same key returns its request, to its uploader only; any other start of
  it is 409 `upload_consumed`. 404 `upload_not_found` for an upload that isn't yours or this workflow's, 410
  `upload_expired`, 422 `csv_mapping_invalid`. A re-run takes the original rows while they're retained, or a new file.
- **What the run keeps:** the mapping, the file's headers and the skipped rows (each one's number and first code, the
  first 100 errors in detail, and their count), encrypted beside its input; its details show them (`run.view`). The
  audit entry keeps a tenant-keyed digest of the file and counts.
- **A loop over the rows** needs no `declassify` entry: their count is `trigger.row_count`, already public. Rows that
  together pass 64 KiB are one claim, and the loop gives each iteration a handle to its row: a step's reference to a
  cell is read in its own activity, but CEL over a cell (a condition on `item.status`) runs in `cel.evaluate`, one
  activity per row ([its cost](#limits-in-this-build)).

## Schedules

`POST /api/v1/t/{tenant}/workflows/{workflow}/schedules` (`trigger.manage`, editors and up) schedules the workflow's
active version: `cron` or `every_s`, `time_zone` (an IANA name), `catchup_window_s` (1 minute to 24 hours, 10 minutes
by default), `mode`, a fixed `input` checked against the active version, and `enabled`. `GET` lists and reads them
(`workflow.view`), never with their input; `PATCH` changes any field (only `cron` and `every_s` take a null, which
switches the timing's kind); `DELETE` removes one.

- **Cron, as Temporal reads it:** five fields (minute, hour, day of the month, month, day of the week), each `*`, a
  number, a range, `*/step` or `a-b/step`, or a list; months and days by name in any case; Sunday is 0 or 7. A day of
  the month and a day of the week together are refused: Temporal requires both to match, where cron usually takes
  either. A local time a daylight-saving change skips doesn't fire that day; one it repeats fires once, at its second
  occurrence. An interval is at least 60 seconds.
- **The dispatcher keeps Temporal in step.** Every change raises the schedule's `generation`, and so does disabling or
  enabling its workflow; the dispatcher's leader applies it to the Temporal Schedule (paused when the schedule or its
  workflow is disabled) and marks it synced (`synced_generation`) only once Temporal shows its `dewpoint generation
  <n>` note. Editing a schedule directly in Temporal isn't supported. A sync Temporal refuses is shown as
  `sync_error` and retried after a minute. There's no "run now": start the workflow instead.
- **Each firing is a tick.** It's admitted as any request, under the key `sched:<schedule>:<nominal time>`, so a retry
  or a backfill over a time that already fired admits nothing new. A tick of a schedule disabled or deleted before
  Temporal heard of it is a `refused` request (`schedule_paused`, `schedule_deleted`); one of a disabled workflow is
  refused as admission refuses it; a tenant being erased skips it, audited. A tick that can't be admitted (the database,
  a key) is retried without limit, and alerts after 10 minutes. Its request's audit entry names the schedule.
- **Missed firings.** Within the catch-up window, firings missed while Temporal was down fire when it's back, each
  with its own time. Past it they're skipped: Temporal counts them, and the schedule's `misses` shows the count, read
  every five minutes, audited and alerted on.
- **A backlog past the window isn't run.** When the dispatcher or the database is down instead, Temporal keeps firing
  and the ticks wait. Once they're decided, a tick more than its schedule's catch-up window old, by the database's
  clock, is a `refused` request, `schedule_catchup_expired`, audited and alerted on once (`schedule_tick_expired`, when
  it's recorded): an outage longer than the window starts only the firings within it. A tick already decided keeps its
  outcome, and a queued request never expires, even one waiting while production runs are off. This limits the runs
  started, not the ticks Temporal records or the refused requests written as they're decided, and these refusals aren't
  counted in `misses`.

## The dispatcher

`dewpoint dispatcher` starts admitted requests. Run one or more. It needs `DEWPOINT_DATABASE_URL` with a login in the
`dewpoint_dispatch` role, `DEWPOINT_TEMPORAL_ADDRESS` and `DEWPOINT_TEMPORAL_NAMESPACE` (checked against the recorded
namespace before it connects: exit 2 otherwise, [`deployment.md`](deployment.md)), and the KEK. Every second it:

1. reads the current build from Temporal and records it, for admission's engine ABI check;
2. picks each tenant's oldest due request (through `dispatch_candidates()`, which returns ids and when they were
   queued), up to 50 tenants, going on from where the last full pick ended so that tenants that can't start never
   hold the others back, and, in one transaction under the production gate's and the tenant's shared locks, checks
   again what must hold at a start:
   - production runs on (in `production`), and the tenant not being erased;
   - every live worker of the current build healthy, with every capability the build needs;
   - nothing the frozen version uses retired, else the request is `cancelled` (`node_type_retired`,
     `cel_profile_retired`), and the version of the build's engine ABI, else `cancelled` (`engine_abi_changed`);
   - a free slot: a tenant runs at most `max_concurrent` top-level runs at once (`tenant_run_limits`, else the
     platform's default, 5);
   - the tenant's key: it opens the request's envelope and encrypts the start with it.

   A check that doesn't hold leaves the request queued, no attempt counted: waiting isn't failing. An envelope that
   doesn't open, or isn't JSON, makes the request `dead` (`envelope_unreadable`), audited; repairing a key never
   reopens it: re-run it;
3. reserves the slot, writes the run's row (`running`, no start time yet), marks the request `starting`, and starts the
   workflow under its run's id, refusing a duplicate, with a 10-second deadline.

What Temporal answers decides what follows:

- accepted: `started`, and the run's start time recorded;
- refused: back in the queue after 5 seconds, doubling up to 10 minutes; the 10th refusal makes it `dead`
  (`start_refused`), audited, and its run `failed` with `start_failed`;
- busy (`RESOURCE_EXHAUSTED`), or the start couldn't be encrypted: back in the queue, no attempt counted;
- already started: it counts only once the execution's own start decodes to this request; anything else is an id
  collision, which the server-built ids make impossible: `dead` (`id_collision`), with an alert;
- no answer: it stays `starting`, its slot held, for the reconciler.

The root run's end write releases its slot. A failure the dispatcher can't classify is logged (`dispatch_failed`, its
type only) and leaves that request as it was; the cycle goes on with the other tenants. A cycle that can't read the
current build from Temporal dispatches nothing (`dispatcher_observe_failed`), and the next one asks again; a cycle
that fails is logged (`dispatcher_cycle_failed`) and the process goes on. Each instance records its
last cycle in `dispatcher_reports`.

### The reconciler

One dispatcher at a time also leads the reconciler (an advisory lock held on a connection of its own; another takes
over when it goes). It asks Temporal about each request at most once every 30 seconds:

- **A request still `starting` 30 seconds after it became so.** An execution found is verified as above, and the
  request is `started`. A `NOT_FOUND` from a namespace that answers puts it back in the queue, no attempt counted,
  with a warning, but only while its run's row is still `running` and its slot still held: when its row records an end
  or its slot is gone, its end write ran, and it's left `starting` with an error (`start_history_missing`) for an
  operator. Any other answer leaves it `starting`; still so 10 minutes on, an error (`start_unresolved`). Each one it
  settles is audited (`run.request.reconciled`).
- **A started run whose row is still `running`,** once Temporal says the logical run's latest execution closed:
  completed records the run's own result; cancelled, `cancelled`; terminated, `failed` with `terminated`; failed or
  timed out, `failed` with `internal_error`, and an alert. Its slot is released in the same transaction. This is how a
  run whose end write was lost, or refused, ends.
- **A slot whose run's row has ended:** released once its execution is closed.
- **History Temporal no longer has**, for a started run or a held slot: left as it is, with an error
  (`run_history_missing`, `slot_history_missing`); no outcome is invented and no slot released. Recover it by hand.
- **Cancels:** it sends each recorded cancel to Temporal, once.

## Cancelling and re-running

`POST /api/v1/t/{tenant}/runs/{id}/cancel`, with `run.cancel` (operators and up), names a request (its id is also its
run's): a queued request is cancelled at once, 200 `cancelled` (reason `user_cancelled`), audited; a starting request
or a running run has its cancel recorded, 202 `requested`, audited once: the dispatcher applies it when the start
doesn't happen, or sends it to Temporal and the run ends `cancelled`. 409 `run_ended` when there's nothing left to
cancel.

`POST /api/v1/t/{tenant}/runs/{id}/rerun`, with `run.start` and an `Idempotency-Key`, admits a new request (source
`rerun`) on the workflow's active version. With `{"input": {...}}` it uses that new input, offered whatever was
retained. Without it, it uses the old request's complete input: rebuilt from its envelope and its claims in memory only,
then validated and claimed again, so no old handle is reused; 410 `input_not_retained` for a run from before 2b-2, a
refused request, a request past its tenant's retention cutoff, or an input retention has removed. `{"mode": ...}` is
optional (the old one's by default). The key covers what was asked (the request re-run, the mode, any new input), and is
checked before anything is rebuilt: an exact retry returns the request it admitted even once retention has removed the
old input, while the re-run's own request is within its cutoff (410 `request_not_retained` past it), and another re-run
under the key is 409 `idempotency_conflict`. The audit entry names the request re-run (`rerun_of`).

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
dewpoint dev run <workflow-id> --tenant <tenant-id> --input input.json --wait 60
```

It admits the workflow's active version with the source `dev`, as any start is admitted
([above](#starting-a-run)), and the dispatcher starts it: one must be running.

- `--simulate` calls each plugin node's `simulate()` instead of `run()`: nothing is sent anywhere. A node without a
  simulation fails its step with `simulation_unavailable`. Timers still wait, as they would in a live run.
- `--wait SECONDS` waits up to that long for the end the database records: its run's (status, code and message), or,
  when it never started, the request's own (`cancelled`, `refused` or `dead`, with its reason). Without it, the
  command prints the queued request and returns.
- `--idempotency-key` retries a request; by default each invocation admits a new one. A retry, or a wait, on a
  request past its tenant's retention cutoff shows nothing of it (exit 2, `request_not_retained`).
- Exit codes: 0 when it was admitted (with `--wait`: when its run succeeded); 1 when it ended otherwise; 2 when it
  wasn't admitted (each message is printed, never a value: in a `production` deployment, "Production runs are off in
  this deployment"; an input that doesn't match the workflow's input schema, each place and rule it breaks, a map's key
  shown as `*`; an input that holds the key `$claim`; a version of another engine ABI than the current build's,
  [`deployment.md`](deployment.md)); 3 when the wait ran out.
- It needs `DEWPOINT_DATABASE_URL` with a login in the `dewpoint_dispatch` role and the KEK: it claims the input with
  the tenant's data key. It doesn't talk to Temporal.

The input is checked against the version's input schema when the request is admitted, then claimed
([below](#sensitive-and-large-values-claims)): its sensitive values, the positions its schema doesn't declare, and any
value over 64 KiB are stored encrypted in `run_inputs`, and the run starts with handles in their place. A refused
input leaves no request.

## Reading runs

`GET /api/v1/t/{tenant}/runs` lists requests and top-level runs together, newest first by `(queued_at, id)`
(`workflow_id`, `before`, `before_id` and `limit` filter and page them). A request's `queued_at` is when it was
admitted; its run shares its id and `queued_at`; a run from before 2b-2 has its `started_at`. **The order changed in
2b-2:** it was by start time, and the next page's cursor is now the last item's `queued_at` with its `id`, given
together (else 422 `invalid_cursor`). Each item's `request` holds its `status`, `source` and `reason` (none for a run
from before 2b-2). A request that hasn't started is shown as itself — `queued`, `starting`, `cancelled`, `refused` or
`dead` — never as the row an attempt pre-created. `GET /api/v1/t/{tenant}/runs/{run_id}` returns one run with its
steps (one row per step, loop iteration and attempt) and its `children`: the sub-runs it started (a request that hasn't
started has neither). The `iteration_key` is the loop step's key and the item's index,
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
  before it leaves the step's activity: every value at a position the schema marks `x-sensitive`, and every position it
  doesn't declare (unknown counts as sensitive: `additionalProperties`, pattern properties, a key one branch of a union
  leaves open); a map that holds a key its schema doesn't declare, whole, since a key the data supplied is data too (a
  reference to one of its declared fields still reads that field); text that repeats a secret the run already knows, or
  such a key; and any value over 64 KiB, claimed for its size. What CEL or a template returns from `cel.evaluate` is
  claimed when it read sensitive data, when it repeats a known secret, or when it's over 64 KiB.
- **Where a claim is read.** Only in an activity, by the run that owns it or was granted it. A plugin step gets its
  input with every handle resolved. CEL or a template that reads a handle runs in the evaluator (`cel_mode`
  `activity`), and so does CEL that indexes trigger or step data by a computed key or position. A reference further
  into a handle extends its pointer without reading the claim.
- **Decisions.** Where sensitive data decides something the run can see — a `flow.if` condition, a switch case's `when`,
  a loop's items (their count) or a filter's items or predicate — the workflow lists the site in
  `graph.settings.declassify`, and the decision is made where the claim is read. Publishing such a workflow needs the
  `workflow.declassify` permission (tenant admins and owners), and its audit entry lists what each site reveals. A
  decision comes back plain only as a decision, `true` or `false` for a condition or a case and a whole number for a
  loop's count: anything else fails the step with `type_mismatch`, revealing nothing. A loop over a CSV's rows
  themselves (`trigger.rows`, in a workflow that declares a CSV) needs no entry: their count, `trigger.row_count`, is
  already public. A loop over any other sensitive list needs its entry. A loop over a list held as a handle (a
  reference's, or CEL's that comes back claimed) gets each item as a handle into it. A filter over sensitive data runs
  whole in one activity: the run sees the kept items' handle and the two counts, never a decision per item.
- **Sub-flows and failure handlers.** A sub-flow's input is checked against the child's input schema
  (`input_invalid` when it doesn't match) and claimed as a trigger is, and the child is granted the parent's claims it
  holds; a sub-flow grants its parent the claims in its outputs. A failure handler is granted what its trigger holds.
- **The secret index.** Every string of 4 characters or more in a sensitive claim joins its run tree's index (the run,
  its sub-runs and its batches share one), stored encrypted, and so does a map key claimed with its map. Every
  message leaving an activity (a step's error, a CEL error, a `fail` node's message) and every row the projection
  writes is masked against it; secrets that overlap are masked as one span. It holds at most 100,000 strings or
  8 MiB: the admission, step, CEL evaluation, filter or sub-flow input that would pass that fails with
  `secret_index_limit`.
- **Heartbeats.** A plugin's `ctx.heartbeat()` tells Temporal the attempt is alive, and nothing else: details it
  passes aren't sent, since Temporal writes an attempt's last ones into the run's history when it times out.
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
  `[redacted]` wherever it reappears: copied by a transform, embedded in a template, passed to another step, in a CEL
  error or a `fail` node's message. A plugin's failure message is shown only when it's text written in the plugin's
  code ([below](#what-the-workers-log-shows)). The index learns from every sensitive claim (the input's,
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

The log lines the worker controls hold no text a run's data could have written unless it's proven to be code: its own
logs, a plugin's `ctx.log`, and Temporal's records of activities. A secret a plugin makes itself, such as a token an
API has just issued, is in no secret index until the step's output is claimed, so masking can't catch it there:

- A plugin's `ctx.log` keeps an event, a field's name and a field's value only when each is a constant written in the
  plugin's own source, a boolean or null. A computed event is logged as `step_event_withheld`, a computed field name
  is dropped (`fields_withheld` counts them), and any other value, a number included, shows as `[redacted]`. A field
  whose name looks secret (`password`, `token`, …) is redacted even then. Log `"token_refreshed"`, not
  `f"refreshed {token}"`.
- A bug in a node (an unexpected exception, a validator's or the claim store's failure) is logged with its type and
  where it was raised (`where`: file, function and line), and with its text only when that's a constant of the
  plugin. A class name is text too, and a plugin can name a class at run time: it's shown only when the class is a
  builtin or its module's code declares that name, else as "an exception whose class name isn't shown", in the log
  and in the step's message alike. A frame is named only when its code was compiled from its module's source, else
  `withheld`, and its line only when that compiled function has it (a traceback a plugin built can carry any number).
- A bug in the workflow itself is logged with its type and where it was raised (`error_type`, `where`), never its
  text.
- Temporal's records of activities keep only the exact text of the SDK's fixed messages: never what follows it (an
  activity's details, an error's text), nor an error's code or class. The rest are logged as `Activity record
  withheld`. The step's code is in its row.

Outside these paths nothing is promised: a plugin that logs through Python's `logging` or `print`, or calls a library
that logs, writes what it writes. Plugins log through `ctx.log`.

A plugin's own failure (`FatalError`, `RetryableError`, `OutcomeUnknownError`) is its step's error, held to the same
rule: its code is shown only when it's a constant of the plugin's code and a dotted lowercase identifier
(`mist.rate_limited`), else as `node_failed`; its message only when it's a constant of the plugin's code, else as
"The node's message isn't shown: it was computed, and only text written in the node's code is." The retry behavior is
its error class's either way.

## How a run ends

| Status | Error code | Meaning |
|---|---|---|
| `succeeded` | | Every path finished, or a `stop` node ended the run. |
| `failed` | the step's code | A step failed with `on_error: fail` (the default) outside any loop. |
| `failed` | the output's code | One of the workflow's outputs couldn't be computed: an expression that failed (`evaluation_error`, `type_mismatch`), or a claim it can't read (`claim_unavailable`). |
| `failed` | `workflow_failed` | A `fail` node ended the run. |
| `failed` | `start_failed` | It never started: Temporal refused it, or its start couldn't be encrypted and was never sent. |
| `failed` | `version_unusable` | This build can't load or run the version, for example a node type it lacks. Nothing ran. |
| `failed` | `internal_error` | A bug in the interpreter. The message names the exception's type, and the worker's log names where it was raised, or says the result was too large to return; please report it. |
| `failed` | `payload_too_large` | The run's outputs were too large to return (over 1.75 MiB once encrypted). A step or a loop fails with the same code, below. |
| `failed` | `snapshot_too_large` | The run's state was too large to carry on as a new Temporal execution (over 1.5 MiB). |
| `failed` | `terminated` | A sub-run that an operator terminated in Temporal. It couldn't record its end, so its parent did, and the step or loop that started it failed with the same code. |
| `deadline_exceeded` | `deadline_exceeded` | The run passed `DEWPOINT_MAX_RUN_DURATION_DAYS` (default 30). Running steps were cancelled. |
| `cancelled` | `cancelled` | The run was cancelled in Temporal. A cancel that arrives while the run's end is being written leaves that end. |

Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation` (an output holding the
key `$claim` too), `unexpected_error`, `evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`,
`input_too_large`, `item_cap_exceeded`, `iteration_cap_exceeded`, `node_type_unavailable` (the registry lists the node
type, but no worker of this build runs it: install its plugin on the workers), `payload_too_large`,
`claim_unavailable` (a claim the run may not read, that isn't there or that's nested deeper than 32 claims, or the
step's output couldn't be stored as claims after the node ran: its effect happened, and its row says so),
`secret_index_limit`, `secret_index_unavailable` (the claim store didn't answer before a plugin's node ran: nothing
was sent, and the attempt is retried under the step's retry policy), `internal_error` (a bug in the worker, such as
one while preparing a step before its node ran: nothing was sent, it isn't retried, and the worker's log names where
it was raised), `input_invalid` (a
sub-flow's input that doesn't match the child's input schema: each place and rule, a map's key shown as `*`) and `node_failed` (a plugin's failure whose own code
wasn't a constant identifier of its code, [above](#what-the-workers-log-shows)). A sub-flow step fails with its sub-flow's code, and with `terminated`
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
- A CSV holds at most 10,000 rows and 5 MiB (its declaration may lower both), and an upload is kept for one hour. The
  API reads a file whole: reading one 5 MiB test file peaked at about 72 MB of memory. That's what one file showed,
  not a bound, and the memory concurrent uploads need is still to be sized.
- A loop over a CSV's rows, once they pass 64 KiB, runs each step's activity per row as any loop does, and CEL over a
  cell adds one `cel.evaluate` per row. On a development machine (Temporal's dev server, one worker), 1,000 rows took
  133 seconds with a condition on a cell and 54 seconds without; 2,500 rows, 340 seconds and 143 seconds. The time grows
  with the rows, slightly faster than they do: 10,000 rows would take about 23 to 25 minutes with the condition and 10
  to 12 without (estimated from those two, not measured).
- Each sensitive cell is its own claim and joins the run tree's secret index, while the start request waits: 2,500 rows
  with five sensitive columns took 7 seconds to admit (12,501 claims), so 10,000 would take about 30 seconds (estimated,
  not measured). Ten sensitive columns of distinct values in 10,000 rows reach the index's 100,000 strings
  (`secret_index_limit`).
- A schedule fires at most once a minute, and its catch-up window is 1 minute to 24 hours. Each cycle, the
  dispatcher's leader syncs at most 50 changed schedules (up to three Temporal calls each) and reads at most 50
  schedules' misses, one call after another, each bounded at 10 seconds: a Temporal that answers slowly delays
  dispatch as well.

## If the database is unavailable

Plugin steps never write to the database: the interpreter projects every row through one activity, which retries
until the database answers. A step's effect therefore never repeats because of a failed write, rows catch up when the
database is back, and a run's end waits for its summary to be written. A backlog is written in batches of at most
256 KiB. A row the database refuses for its data (SQLSTATE class 22 or 23) is logged in the worker's log and
skipped, so the other rows, and the run's end, still land.
