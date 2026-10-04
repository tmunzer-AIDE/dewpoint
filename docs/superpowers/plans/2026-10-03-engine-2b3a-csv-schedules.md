# Engine 2b-3a: CSV Starts and Schedules Implementation Plan

> **Status: outline revised with the owner's rulings (2026-10-03) and corrections (2026-10-04); the prototype is
> approved to start with M1, and the schedule sync stays provisional until its conflict-token path is proven.** The
> owner approved splitting 2b-3 into 2b-3a (CSV and schedules, this plan) and 2b-3b (webhook ingress, its own outline,
> prototype, plan and PR), and the prototype-first process. As in 2b-1a, 2b-1b and 2b-2, each task is built and tested
> on a prototype branch from `main` first, and the plan is then written from the tested diffs, each replayed
> tests-first, for the owner's review before execution.

**Goal:** runs start from a manual start with a CSV file and from a schedule's tick, each admitted by `admit_request`
and started by the dispatcher.

**Architecture:** every trigger ends in `admit_request` (§7.2); none starts a run. A CSV is parsed by the API as data
only, staged encrypted, and turned into typed rows by admission, which claims its sensitive cells (§8.1). A schedule is
a row the API writes; the dispatcher's leader keeps a Temporal Schedule in step with it, whose action starts
`ScheduleTick` on `dewpoint-admission`, a one-activity workflow in the dispatcher process that admits one request per
nominal time (§8.2).

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy (async, asyncpg), Alembic, PostgreSQL 16 (RLS), the Temporal Python
SDK 1.33 (Schedules), `cryptography`, hypothesis (fuzzing, already a dev dependency), Typer, Compose. No new
dependency.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md` revision 7 (merged in #29): §8.1 and §8.2, with
§2.5, §3.5, §3.8, §4.1, §4.3, §6.1, §6.4, §6.5, §7.1–7.2, §7.7, §9, §10.1, §12–§15;
`docs/superpowers/specs/2026-09-25-engine-core-design.md` revision 5.10, §9 and §11.11; the parent spec's §6.1 and
§6.8. This plan's revision 8 of the 2b spec lands with it (below).

## What exists today (main 85177d8)

- **Admission is ready for durable sources.** `admit_request` takes the sources `schedule` and `webhook`, checks the
  gate only for interactive sources, and keeps a durable source's refusal as a `refused` request with its reason and an
  audit entry (tested). `tenants.status` refuses an `erasing` tenant at admission, and dispatch waits on one.
- **The run API reserves CSV.** `StartIn` forbids unknown fields, so `csv` is refused (422, tested), and the start form
  returns `"csv": null`. There is no `trigger.manage` permission. The API caps every body at 1 MiB by the bytes it
  actually receives (`BodyLimitMiddleware`, 413 at one byte more).
- **The engine already handles most of a CSV's run.** A loop over a claimed list (`ItemsRef`) gives each iteration a
  handle `ClaimRef(X, "/7")`; a step's reference passes it to its activity, which resolves it; CEL over a handle goes to
  `cel.evaluate`. Element taint works: an `x-sensitive` property of the row objects taints `trigger.rows[*].<col>` and
  `item.<col>`. The splitter, given closed row objects, claims each sensitive cell with taint, then the rows list as a
  size claim over 64 KiB, holding those handles. No page activity exists.
- **A finding in merged 2b-1b code** (ruling 11): the no-declassify exception for a loop over `trigger.rows` (§4.3,
  `engine/graph/validate.py` `_public_length`) matches the path alone, so any `input_schema` property named `rows`
  gets it without a public `row_count`.
- **Schedules:** the codec reads the tenant from `t:<tenant>:sched:<id>` plus Temporal's appended time, and
  `test_temporal_contract.py` proves on the dev server that `TemporalScheduledStartTime` is whole seconds and the same
  under replay, a backfill repeats it, a catch-up gives each missed firing its own time, and a schedule's action
  arguments are sealed under its tenant. The dispatcher runs no Temporal worker; there is no schedule table, builder or
  sync.
- **Keys:** purposes are per call (`claim`, `secret_index`, `connection.secret`); `schedule.input`, `csv.upload` and
  `csv.mapping` are new. No key retirement exists yet (`rotate-dek` and `rewrap` only).

## Milestones and tasks

**M1. The CSV declaration and the trigger schema (publish)**
1. `graph.settings.csv`: columns (header, variable name, type among `string`, `integer`, `number`, `boolean`, `mac`,
   `ip`, `cidr`, `enum`; required; default; sensitive), `max_rows` and `max_bytes` at most the platform's 10,000 rows
   and 5 MB. A graph without it serializes as today (`graph_hash` unchanged). Publish refuses a default on a sensitive
   column (§3.8), and duplicate headers or variable names.
2. The trigger schema, one pure function of the settings: `input_schema` plus `rows` (an array of closed row objects,
   `x-sensitive` on sensitive columns) and `row_count` (an integer), both required when a CSV is declared. Used wherever
   a trigger is typed, tainted, validated or split: the validator, admission, a sub-flow's crossing, the start form
   (which returns the declaration). `rows` and `row_count` are reserved (ruling 7–8): publish refuses them as
   `input_schema` properties, declared CSV or not, and only admission writes them, from an upload. A version declaring
   a CSV is started only by the run API with a CSV, or by a re-run of such a request: publish refuses it as a
   sub-flow's or a failure handler's target.
3. **The `trigger.rows` fix (ruling 11, test first):** the exception holds only for a version that declares a CSV,
   whose `row_count` is public; a loop over a `rows` list without one needs its `declassify` entry. Filed as #31
   (2026-10-04).

   **From the owner's M1 reviews (2026-10-04), test first:** a CSV's input schema may hold only `type`, `properties`,
   `required`, `additionalProperties`, `$defs` and annotations at its root, since any other keyword (a closed `allOf`
   branch, a root `$ref`, `propertyNames`, `maxProperties`, `x-sensitive`, ...) could refuse the generated `rows`, or
   make their count sensitive (`csv.input_schema`); a sensitive column lists no `values` (`sensitive.literal`). And,
   as its own issue (#32): publish refuses a `default`, `enum`, `const` or `examples` at a sensitive position of
   `input_schema` or `vars_schema`, nested, in a union's branch, or in a definition a sensitive position reaches
   through a local `$ref`; §3.8 states it, and the start form keeps `enum_masked` for versions published before.

**M2. CSV uploads and CSV starts**
4. The parser, data only: UTF-8 with an optional BOM; the delimiter detected among comma, semicolon and tab; the caps
   (bytes, then rows); unique headers; each cell converted to its column's type (ruling 7: an empty cell is absent, so
   its default or `required`; `boolean` true/false, yes/no, 1/0 in any case; `integer` decimal; `number` finite; `mac`
   to lowercase colon form; `ip` and `cidr` to `ipaddress`'s canonical form, a `cidr` with host bits set invalid; `enum`
   exact); per-row errors as row, column and code, never a value. Fuzzed with hypothesis.
5. `csv_uploads` (tenant, owner user, workflow, raw cells and headers encrypted under `csv.upload`, expiry one hour,
   consumed-by; RLS); `POST /t/{tid}/workflows/{wid}/csv-uploads` (`run.start`, a raw `text/csv` body). **The caps
   are enforced as bytes arrive (ruling 4, corrected 2026-10-04):** `BodyLimitMiddleware` buffers a whole permitted body
   before the route runs, so it doesn't raise its cap for this route: it passes this one route (`POST`, matched
   exactly) through unbuffered, and the route reads the stream itself. Before reading any of the body, the route
   authorizes the caller and loads the active version's declaration, then reads chunk by chunk up to the smaller of the
   declaration's `max_bytes` and the platform's 5 MB: a declared `Content-Length` past it, or one byte past it as
   chunks arrive, answers 413 without reading the rest, and nothing past the cap is ever buffered. Tests: a chunked
   body with no `Content-Length` stops at the declaration's cap + 1 byte (the bytes read are counted), and every other
   route keeps the 1 MiB middleware. The response: headers with exact matches mapped (or the saved default, below), a
   preview of the first rows with sensitive columns masked, the per-row errors.
6. **The saved default mapping (ruling 6):** one per workflow, encrypted under `csv.mapping`, saved with
   `trigger.manage`, with the declaration it was saved against. Whenever it's read, it's checked against the active
   version's declaration; one that no longer fits (a column it maps is gone, a required column is unmapped) is marked
   stale on its row and returned as stale, with each column's code and no value, and never applied. Saving a new one
   clears the mark. A start always needs a mapping valid for its version (422 `csv_mapping_invalid`), whatever the
   default.
7. **CSV starts (ruling 5):** `POST …/runs` with `csv: {upload_id, mapping, skip_invalid}`.
   - The key first: the digest covers what was asked, `{input, csv: {upload_id, mapping, skip_invalid}}`, so a retry
     is recognized without rebuilding the rows, even after the upload was consumed, and another start under the key is
     a 409.
   - **An exact retry is returned only to the upload's owner (corrected 2026-10-04).** The start that consumed an
     upload ran as its owner (below), so that request's actor is the owner. A key that matches a CSV start's digest
     returns its request only when the caller is that actor; any other caller, even one of the tenant who knows the
     key and the upload's id, gets the same 409 `idempotency_conflict` as a different request under the key, which
     reveals nothing more. Test: a second user of the tenant replaying the owner's exact start gets the 409 and no
     request.
   - Then the upload, locked (`FOR UPDATE`) and verified: its tenant (row-level security and an explicit check), its
     owner (the caller), its workflow (the path's), not expired (`upload_expired`), not consumed. A start that finds it
     consumed looks up its own key again, since the consumer has committed: an exact retry returns that request (its
     owner verified first), and anything else is 409 `upload_consumed`. Concurrent starts therefore yield one consumer.
   - Admission validates again against the frozen version's declaration, builds typed rows and `row_count`, claims
     (sensitive cells with taint, then the list for size), and consumes the upload by an UPDATE in the same
     transaction: consumed-by set, staged cells cleared (§10.3: only retention deletes rows).
   - The mapping, the file's header names and the skipped rows' numbers and codes go into one `run_inputs` row of a
     third role, `csv`: encrypted, owned by the request, never a claim nor part of the trigger, read through its own
     reader by the run's details (`run.view`), kept and deleted with its request.
   - The audit entry keeps the file's tenant-keyed digest and counts only.
   - A re-run takes the original input, its rows rebuilt from the retained claims, or a new `csv` (the re-run's body
     gains it); `rows` and `row_count` in any caller's `input` are refused (422, the reserved names).

**M3. Schedules**
8. `schedules` (tenant, workflow, cron or interval, time zone, catch-up window, mode, the fixed input encrypted under
   `schedule.input` with the schedule's id as context, enabled, a `generation` and the synced state, a tombstone);
   the permission `trigger.manage` (editors and above); the API: create, list, read, update, enable and disable,
   delete. Ruling 9:
   - **Cron as Temporal reads it.** Temporal's own interpretation is pinned first, by a dev-server contract test:
     `ListScheduleMatchingTimes` over a corpus — day-of-month with day-of-week, steps, ranges, names, and a non-UTC time
     zone across both daylight-saving changes. The API's validator accepts five-field expressions only (minute-granular,
     so the tick key stays unique), and only the forms whose times that test shows match their documented meaning; any
     form Temporal reads otherwise (both day fields restricted, if Temporal doesn't treat them as cron's usual "either")
     is refused, never accepted under a meaning of our own. An interval is at least 60 s, with an optional offset.
   - **Time zones:** an IANA name, checked with `zoneinfo`. The shipped image's time-zone data is verified, in CI's
     Compose step (ruling 12), by creating a schedule in a non-UTC zone through the API container. If the image lacks
     it, the `tzdata` package is a new dependency, brought to the owner first.
   - The fixed input is validated against the active version when written (422) and again at each tick (a `refused`
     request when it no longer fits). A workflow declaring a CSV can't be scheduled (409 `csv_required`).
   - A tick's request has no actor; its audit entry names the schedule. Disabling or deleting a schedule stops it; its
     author losing access doesn't.
   - The catch-up window: per schedule, 10 minutes by default, from 1 minute to 24 hours (provisional).
9. `ScheduleTick` on `dewpoint-admission`, in the dispatcher process (a Temporal worker beside the cycle, unversioned,
   outside the engine's Worker Deployment; ruling 10). The workflow reads `TemporalScheduledStartTime` once, builds the
   key `sched:<schedule_id>:<nominal time>` (UTC, whole seconds) and passes it to its one activity. **The activity
   takes its authority from the workflow's own id only:** it parses both the tenant and the schedule id from it (the
   codec's grammar), refuses an argument that isn't that schedule id, and reads the schedule row by both, in that
   tenant's scope. In one transaction it admits the request, or records the outcome:
   - a schedule disabled before the pause synced: `refused`, `schedule_paused`;
   - a deleted schedule, from its tombstone: `refused`, `schedule_deleted`;
   - a disabled workflow: `refused`, `workflow_disabled`, as admission already does;
   - an `erasing` tenant: an audited skip, no request.

   The activity retries with backoff and no attempt limit (a platform-wide failure waits, §2.5), and a tick still
   unadmitted after 10 minutes alerts. Its replay test pins the workflow's contract, independent of `ENGINE_ABI`.
10. **The sync loop**, in the reconciler's leader. `schedule_candidates()` returns ids only: those whose `generation`
    passes their synced one, or whose wanted pause differs from the synced pause (wanted paused: the schedule disabled,
    its workflow disabled, or its tenant `erasing`). Temporal Schedule id `t:<tenant>:sched:<id>`, overlap allow-all,
    the schedule's catch-up window, never `trigger`.
    - **The fence is Temporal's conflict token, sent by a path of our own; only a read-back completes a change (the
      owner's rulings, 2026-10-04).** The pinned SDK 1.33.0 never sends the token: `ScheduleHandle.update()` describes,
      then builds `UpdateScheduleRequest` without `conflict_token`. So `apps/dispatcher/schedules.py` calls the service
      directly: `describe_schedule` for the token, then `update_schedule` with it and one schedule built by the SDK's
      own conversion (the codec seals the action under the tenant), holding the spec, the action, the pause state and
      the note `dewpoint generation <n>` together. **The gate passed in another form** (contract tests 1f7be8a,
      8405bdd): on this server a stale-token update is discarded, not refused (the call succeeds, nothing changes), a
      landed one is seen by the describe at once, a firing doesn't move the token, and the note shows the generation of
      the update that landed, never a stale writer's.
    - **The order, and the read-back gate.** Each change is: describe (token T) → read the row's generation and wanted
      state → one update with T and the marker. An OK answer is no evidence: a generation is marked synced only once a
      fresh describe shows its marker and a transaction confirms that the row still has that generation and the writer
      still holds the leadership; a marker absent or different leaves the row queued, and the next pass starts again.
      Tests: the row changed between the describe and the update; another writer's update landing between a describe
      and its update (the first's marker never shows, and it records nothing); a writer that lost the leadership.
    - **Out-of-band edits are unsupported.** The marker is evidence of a Dewpoint update, not of the whole state: a
      direct edit in Temporal that keeps the note intact goes unseen; detecting such drift would take a full
      comparison, which the sync doesn't make.
    - **Creates and deletes, which carry no token.** A create follows a describe that answered `NOT_FOUND`; a create
      that finds the schedule already there leaves the row a candidate, and the next pass updates it with a token.
      Deleting marks the row a tombstone (its fixed input cleared): tombstones are final, so no newer state can follow
      one. But a stale writer's create, started before the tombstone, could land after the delete and bring the Temporal
      Schedule back, so a tombstone stays a candidate until a describe made at least one call deadline after its delete
      answers `NOT_FOUND`, and a tick that finds a tombstone makes it a candidate again.
    - **Deletion keeps a tombstone.** The row keeps the tenant, schedule id, workflow and mode, so a late tick (fired
      before the deletion synced, caught up, delayed by a stopped worker, or from a schedule a stale create brought
      back) records `schedule_deleted`. 2b-4's retention deletes a tombstone only once Temporal reports its schedule gone
      and no tick of it is open.
    - **Misses are counted, not promised away.** No tick within the catch-up window is dropped, but a Temporal outage
      longer than the window skips the firings it missed. The leader reads each enabled schedule's
      `num_actions_missed_catchup_window` from Temporal (every 5 minutes, a bounded batch a pass, provisional) and
      records an increase on the schedule, audited, alerted and shown by the API. The dev-server test stops the server
      past a 1-minute window.
    - A failure is recorded with a fixed code, retried, and alerted on.

**From the owner's M3 review (2026-10-04):** a tick decides under its schedule's row lock (the workflow's admission
lock first, shared, the order a workflow's change takes them in), so a disable or a delete either decides it or waits
for its request; a PATCH's null is refused except for `cron` and `every_s`; a tick's `run.request` audit entry names
the schedule. **Erasure (ruling, outside 2b-3a):** the transition that sets a tenant `erasing` must raise its
schedules' generations in the same transaction, with a regression proving they pause; until it exists, nothing
claims the sync pauses a schedule because its tenant's status changed (the tick skips an erasing tenant's, audited).
The sync's two serial batches (up to 50 schedules of three calls each, and up to 50 describes for misses: 200
calls of at most 10 s each) join §7.9's dispatch-latency gate.

**M4. Proofs, Compose and docs**
11. On the dev server: a tick becomes a request and a run; a catch-up after downtime admits each missed time once, and
    an outage past the window records the misses; a backfill over a fired time admits nothing new; a disable racing a
    tick gives `schedule_paused`, a deletion `schedule_deleted`; ticks while the gate is off are queued and start once
    it's on. CSV: two concurrent starts with one upload yield one request; an exact retry after consumption returns it.
12. **The measurement (ruling 3):** a 10,000-row CSV, its rows list size-claimed, with a representative per-row
    condition on a plain column (a `flow.if` reading `item.<col>`, routed to `cel.evaluate` since `item` is a handle):
    its wall time and activity count on the dev server, beside the same run with the condition removed. Also the
    admission of 10,000 rows with one and with five sensitive columns: its time, claim rows and secret-index size (a
    CSV past the index bound is refused with `secret_index_limit`). The results go into revision 8; if they make runs
    impractical, the cap comes back to the owner.
    **Result (dev machine, the CLI dev server, one worker):** 1,000 rows: 133 s with the condition (1,001
    `cel.evaluate`, 1,511 projections, 500 echoes), 54 s without (1 `cel.evaluate`); 2,500 rows: 340 s and 143 s. Per
    row about 135 ms and 55 ms, growing slightly with the rows claim each row re-reads (67 KB, then 168 KB). Admission:
    1 sensitive column 0.61 s / 1.57 s, 5 columns 2.95 s / 7.15 s (12,501 claims, index 313 KB at 2,500 rows). **The
    owner's ruling (2026-10-04): use the estimate, no 10,000-row run:** about 23–25 min with the condition and 10–12
    min without, admission about 30 s for 5 sensitive columns. A work-unit test pins the counts (90 rows: `cel.evaluate`
    = rows + 1 with the condition, 1 without), and one pins the index bound's refusal.
13. End to end with the keyring's real keys: a CSV run with a canary in a sensitive column, in a header and in the
    mapping, and a schedule whose fixed input holds one: no canary in any execution's whole raw history, any projection
    or any log line (§12). CSV parser fuzzing (§12).
14. Compose and CI: the dispatcher's `ScheduleTick` worker; one bounded step in the e2e job (ruling 12): a schedule in
    a non-UTC zone with a 60-second interval on a synthetic workflow, created through the API container, its first run
    waited for at most 150 seconds (about 1–2.5 more minutes of the 2-core runner per run). `docs/operations/runs.md`
    (CSV starts, schedules, misses).

## Revision 8 of the 2b spec (lands with the plan)

- §8.1 replaces the page-activity requirement explicitly (ruling 3): a size-claimed rows list is iterated by handle,
  with the measured cost; it also records the CSV start's digest, the locked single-use upload, the `csv` role, the
  reserved names, CSV starts by the run API only, the stale default mapping, the cap enforced while reading, and the
  cell rules.
- §8.2: cron as Temporal reads it, the time zones, the activity's authority from its workflow id, the generation and
  conflict-token sync, tombstones, and "no tick is silently dropped" qualified: within the catch-up window; past it,
  misses are counted and reported.
- §4.3: the `trigger.rows` exception needs a CSV declaration. §7.1: `run_inputs` roles `claim`, `envelope`, `csv`.
  §9: `schedule_paused`, `schedule_deleted`, `upload_expired`, `upload_consumed`, `csv_mapping_invalid`,
  `csv_required`. §14 and §15: the tables, `trigger.manage`, the grants, the provisional values. §13: engine-core §11.11
  (`dewpoint-admission` outside the Worker Deployment); the parent's §6.8 ("rows load in pages through an activity")
  superseded.

## The owner's rulings (2026-10-03)

1–2. Split approved: CSV and schedules here; ingress gets its own outline, prototype, plan and PR. Prototype first,
     checkpoints after M1, M2 and M3, then M4 and a whole-branch review.
3. The page activity is deferred and ABI 6 kept, provided the prototype measures a 10,000-row CSV with a representative
   per-row condition (task 12); revision 8 replaces §8.1's requirement explicitly.
4. A raw `text/csv` body, the cap enforced while reading (task 5).
5. Key-first digest, consumption by UPDATE, encrypted request-owned CSV metadata; the upload locked and verified, one
   consumer, an exact retry returns its request (task 7).
6. An encrypted workflow-level default, marked stale when a later version invalidates it, never silently ignored
   (task 6).
7–8. The cell rules, the caps and API-only CSV starts; `rows` and `row_count` reserved (tasks 2, 4, 7).
9. Fixed input, actor and catch-up bounds as proposed; cron as Temporal actually reads it; time-zone data verified in
   the shipped image (task 8).
10. The separate unversioned admission worker; the activity verifies the row against both ids in its workflow's
    identity (task 9).
11. File the `trigger.rows` issue and fix it in M1 (task 3).
12. The bounded Compose schedule proof in CI (task 14).
13. Ingress rulings deferred to 2b-3b's outline; its preview approved nothing.
Added by the owner for M3: the generation and recheck, the tombstone for late ticks, and misses past the catch-up
window detected and reported (task 10).

**What follows from the rulings, for the owner to check** (decided here, not by the owner):
- The reserved names apply to every version, CSV or not, so existing tests that declare `rows` by hand move to a CSV
  declaration; and a version declaring a CSV can't be a sub-flow's or failure handler's target, since no caller may
  supply its rows.
- Misses are read from Temporal's own counter (`ScheduleInfo.missed_catchup_window`); the tick's activity retries
  without limit and alerts past 10 minutes.

**The owner's corrections (2026-10-04)**, recorded above; filing the amended issue and starting M1 are approved, and the
schedule sync isn't settled until its conflict-token path is proven:
1. Schedule fencing: SDK 1.33.0's `ScheduleHandle.update()` sends no conflict token, so the sync uses a narrow,
   tested RPC path that sends the token from `DescribeScheduleResponse`, proven first in M3 (task 10). A post-call
   generation check alone can't keep a stale leader from overwriting a newer Temporal state.
2. Upload streaming: the middleware buffers a whole permitted body, so the CSV route streams itself, with the platform
   cap enforced as bytes arrive and the declaration's cap enforced before the remainder is buffered (task 5).
3. Upload ownership on retries: the key-first lookup stays, without rebuilding rows, but an exact retry is returned
   only to the upload's owner (task 7).
