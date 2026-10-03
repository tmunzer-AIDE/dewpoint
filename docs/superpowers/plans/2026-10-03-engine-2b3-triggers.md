# Engine 2b-3: Triggers Implementation Plan

> **Status: outline, for the owner's decisions.** The tasks below are a first cut. As in 2b-1a, 2b-1b and 2b-2, each
> one is built and tested on a prototype branch from `main` first, and the plan is then written from the tested diffs,
> each replayed tests-first, for the owner's review before execution.

**Goal:** runs start from real triggers through admission: a manual start with a CSV file, a schedule's tick, and (in
its own plan, decision 1) a webhook event, each admitted by `admit_request` and started by the dispatcher.

**Architecture:** every trigger ends in `admit_request` (§7.2); none starts a run. A CSV is parsed by the API as data
only, staged encrypted, and turned into typed rows by admission, which claims its sensitive cells (§8.1). A schedule is
a row the API writes; the dispatcher's leader keeps a Temporal Schedule in step with it, whose action starts
`ScheduleTick` on `dewpoint-admission`, a one-activity workflow in the dispatcher process that admits one request per
nominal time (§8.2). Webhook ingress is a separate process that records sealed events, which the dispatcher matches and
admits (§8.3).

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy (async, asyncpg), Alembic, PostgreSQL 16 (RLS), the Temporal Python
SDK 1.33 (Schedules), `cryptography`, hypothesis (fuzzing, already a dev dependency), Typer, Compose. No new
dependency.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md` revision 7 (merged in #29): §8, with §2.5, §3.5,
§3.8, §4.1, §4.3, §6.1, §6.4, §6.5, §7.1–7.2, §7.7, §9, §10.1, §12–§15; `docs/superpowers/specs/2026-09-25-engine-core-design.md`
revision 5.10, §9 and §11.11; the parent spec's §6.1 and §6.8.

## What exists today (main 85177d8)

- **Admission is ready for durable sources.** `admit_request` takes the sources `schedule` and `webhook`, checks the
  gate only for interactive sources, and keeps a durable source's refusal as a `refused` request with its reason and an
  audit entry (tested). A caller may admit several requests in one transaction; nothing orders them by workflow id
  yet. `tenants.status` refuses an `erasing` tenant at admission, and dispatch waits on one.
- **The run API reserves CSV.** `StartIn` forbids unknown fields, so `csv` is refused (422, tested), and the start form
  returns `"csv": null`. There is no `trigger.manage` permission.
- **The engine already handles most of a CSV's run.** A loop over a claimed list (`ItemsRef`) gives each iteration a
  handle `ClaimRef(X, "/7")`; a step's reference passes it to its activity, which resolves it; CEL over a handle goes to
  `cel.evaluate`. Element taint works: an `x-sensitive` property of the row objects taints `trigger.rows[*].<col>` and
  `item.<col>`. The splitter, given closed row objects, claims each sensitive cell with taint, then the rows list as a
  size claim over 64 KiB, holding those handles. No page activity exists.
- **A finding in merged 2b-1b code.** The no-declassify exception for a loop over `trigger.rows` (§4.3,
  `engine/graph/validate.py` `_public_length`) matches the path alone: today any `input_schema` property named `rows`
  gets it, without a public `row_count` to prove its length is already public, so a version can reveal a sensitive
  list's length without listing the site or holding `workflow.declassify`. Decision 11.
- **Schedules:** the codec already reads the tenant from `t:<tenant>:sched:<id>` plus Temporal's appended time, and
  `test_temporal_contract.py` proves on the dev server that `TemporalScheduledStartTime` is whole seconds and the same
  under replay, a backfill repeats it, a catch-up gives each missed firing its own time, and a schedule's action
  arguments are sealed under its tenant. The dispatcher runs no Temporal worker; there is no schedule table, builder or
  sync.
- **Ingress:** the role `dewpoint_ingress` exists (no login, only `audit_append`); there is no process, login, route,
  table, ingress key or X25519 key.
- **Keys:** purposes are per call (`claim`, `secret_index`, `connection.secret`); `schedule.input`, `csv.upload` and the
  inbound keys are new. No key retirement exists yet (`rotate-dek` and `rewrap` only), so nothing has to block it now.

## Milestones and tasks (first cut, for 2b-3a: CSV and schedules)

**M1. The CSV declaration and the trigger schema (publish)**
1. `graph.settings.csv`: columns (header, variable name, type among `string`, `integer`, `number`, `boolean`, `mac`,
   `ip`, `cidr`, `enum`; required; default; sensitive), `max_rows` and `max_bytes` at most the platform's 10,000 rows
   and 5 MB. A graph without it serializes as today (`graph_hash` unchanged). Publish refuses a default on a sensitive
   column (§3.8), duplicate headers or variable names, and `input_schema` properties named `rows` or `row_count`.
2. The trigger schema, one pure function of the settings: `input_schema` plus `rows` (an array of closed row objects,
   `x-sensitive` on sensitive columns) and `row_count` (an integer), both required. Used wherever a trigger is typed,
   tainted, validated or split: the validator, admission, a sub-flow's crossing, the start form (which returns the
   declaration). The `trigger.rows` exception holds only for a version that declares a CSV (decision 11).

**M2. CSV uploads and CSV starts**
3. The parser, data only: UTF-8 with an optional BOM; the delimiter detected among comma, semicolon and tab; the caps
   (bytes, then rows); unique headers; each cell converted to its column's type (decision 7); per-row errors as row,
   column and code, never a value. Fuzzed with hypothesis.
4. `csv_uploads` (tenant, owner user, staged rows and headers encrypted under `csv.upload`, expiry one hour; RLS);
   `POST /t/{tid}/workflows/{wid}/csv-uploads` (`run.start`, a raw `text/csv` body, decision 4): headers with exact
   matches mapped (or the saved default), a preview of the first rows with sensitive columns masked, the per-row
   errors. A saved default mapping per workflow, encrypted (decision 6).
5. CSV starts: `POST …/runs` with `csv: {upload_id, mapping, skip_invalid}`. The digest covers what was asked
   (decision 5); admission validates again, builds typed rows, sets `row_count`, claims (sensitive cells with taint,
   then the list for size), and consumes the upload in the same transaction. The mapping, header names and skipped rows'
   numbers and codes go into a `run_inputs` row of their own (decision 5). The audit entry keeps the file's tenant-keyed
   digest and counts only. A re-run with the original input rebuilds the rows from the retained claims.

**M3. Schedules**
6. `schedules` (tenant, workflow, cron or interval, time zone, catch-up window, mode, the fixed input encrypted under
   `schedule.input`, enabled, the Temporal state last synced); the permission `trigger.manage` (editors and above); the
   API: create, list, read, update, enable and disable, delete (decisions 8 and 9).
7. `ScheduleTick` on `dewpoint-admission`, in the dispatcher process (a Temporal worker beside the cycle, unversioned,
   decision 10): it reads `TemporalScheduledStartTime` once, builds the key `sched:<schedule_id>:<nominal time>`
   (UTC, whole seconds) and passes it to its one activity, which takes the tenant from its own workflow id (the codec's
   grammar), checks the schedule against it, and in one transaction admits the request: `refused` with
   `schedule_paused` for a schedule disabled before the pause synced, `workflow_disabled` as admission already does,
   an audited skip for an `erasing` tenant. Its replay test pins the contract (§12).
8. The sync loop, in the reconciler's leader: `schedule_candidates()` returns the ids whose wanted Temporal state
   differs from the synced one (wanted paused: the schedule disabled, its workflow disabled, or its tenant `erasing`);
   it creates, updates, pauses, unpauses and deletes Temporal Schedules with id `t:<tenant>:sched:<id>`, overlap
   allow-all and the schedule's catch-up window, never `trigger`. A deleted schedule is removed from Temporal, then
   tombstoned. A failure is recorded with a fixed code, retried, and alerted on.

**M4. Proofs, Compose and docs**
9. On the dev server: a tick becomes a request and a run; a catch-up after downtime admits each missed time once; a
   backfill over a fired time admits nothing new; a disable racing a tick gives `schedule_paused`; ticks while the gate
   is off are queued and start once it's on. End to end with the keyring's real keys: a CSV run with a canary in a
   sensitive column, in a header and in the mapping, and a schedule whose fixed input holds one: no canary in any
   execution's whole raw history, any projection or any log line (§12). CSV parser fuzzing (§12).
10. Compose: the dispatcher's `ScheduleTick` worker (decision 12); `docs/operations/runs.md` (CSV starts, schedules);
    the 2b spec's revision 8 and engine-core §11.11 (`dewpoint-admission` outside the Worker Deployment), parent
    §6.1 and §6.8 noted in §13.

## 2b-3b: webhook ingress (its own outline, if decision 1 holds)

`dewpoint ingress` (its own login and Compose service, `/hooks/<endpoint_id>` routed apart from `/api/`), the tenants'
X25519 keypairs (made at tenant creation and by `keys ensure-tenants`), `DEWPOINT_INGRESS_KEY`, `webhook_endpoints`,
`trigger_bindings`, `inbound_events` with their counters and token buckets, `resolve_webhook_endpoint()`, the endpoint,
binding and event API (`trigger.manage`), matching in the dispatcher (only while the gate is on), the event outcomes
and dead-lettering, and its proofs: authentication, replay tolerance, quotas, sealing, a crash before matching commits,
and a local load probe. The decisions it will bring (decision 13 previews them).

## Decisions for the owner

1. **Split 2b-3.** Ingress is a subsystem of its own: a new process, login, route and role; a new key and keypairs;
   its own tables, quotas and matcher. CSV and schedules extend admission and the dispatcher. *Recommended:* 2b-3a (CSV
   and schedules, this outline's tasks) and 2b-3b (webhook ingress), each with its own prototype, plan and PR, as 2b-1
   was split. If you'd rather keep one plan, M5–M7 take ingress.
2. **Process.** *Recommended:* as 2b-2: prototype first on `proto/2b3a-v1` from `main`, checkpoints after M1, M2 and
   M3, then M4 and a whole-branch review; focused checks per milestone, the whole suite once; the plan and revision 8
   written from the replayed commits; inline execution by cherry-pick.
3. **No ABI change: the page activity is deferred.** §8.1 loads a size-claimed rows list a batch's slice at a time
   through one page activity, plain cells inline. Today each iteration's `item` is a handle: a step's reference to a
   plain cell is resolved in its own activity (no extra cost), but CEL over a plain cell (a condition on
   `item.status`) goes to `cel.evaluate`, about 50 ms each (§11.1: roughly 50 s of routing for 10,000 iterations at
   concurrency 10). A page activity is a new command in `RunGraph`, so `ENGINE_ABI` 7, a re-recorded `abi7` replay set
   and every workflow published again. A CSV under 64 KiB stays inline anyway. *Recommended:* defer it; 2b-3 keeps ABI
   6, revision 8 records the cost, and the page activity comes back with measurements.
4. **Upload transport.** FastAPI's `UploadFile` needs `python-multipart`, a new dependency. *Recommended:* a raw
   `text/csv` body, with the API's 1 MiB body limit raised to the declaration's `max_bytes` (at most 5 MB) for that
   route only (nginx already allows 6 MB).
5. **CSV start's identity and records.**
   a. *Digest:* the upload is single-use, so a retry can't rebuild the rows. *Recommended:* like a re-run's, a CSV
      start's digest covers what was asked, `{input, csv: {upload_id, mapping, skip_invalid}}`, and is checked before
      the upload is read: an exact retry returns its request after the upload was consumed.
   b. *Consuming the upload:* §10.3 gives `DELETE` to retention only. *Recommended:* the start marks the upload
      consumed and clears its staged rows in the same transaction (an UPDATE); a second start with it is refused
      (`upload_consumed`); an expired one is refused (`upload_expired`); 2b-4's retention deletes the rows.
   c. *Where the mapping, headers and skipped rows live:* *Recommended:* one `run_inputs` row of a third role, `csv`,
      encrypted, owned by the request, never a claim nor part of the trigger, read through its own reader by the run's
      details (`run.view`), kept and deleted with its request.
6. **The saved default mapping.** *Recommended:* one per workflow (not per version), encrypted, saved with
   `trigger.manage` since it changes every user's default; a mapping naming a column a later version lacks is ignored.
7. **CSV cells and caps.** *Recommended, unless you object:* an empty cell is absent (its default, else `required`);
   `boolean` takes true/false, yes/no, 1/0, any case; `integer` is decimal; `number` is finite; `mac` is normalized to
   lowercase colon form; `ip` and `cidr` to `ipaddress`'s canonical form (a `cidr` with host bits set is invalid);
   `enum` matches exactly. "A tenant may lower" the caps through each declaration's own `max_rows`/`max_bytes`; a
   tenant-wide cap waits. Formula escaping applies to export, which 2b doesn't have.
8. **Who may trigger a CSV workflow.** `rows` and `row_count` come only from an upload, which only the run API takes.
   *Recommended:* the run API refuses `rows` and `row_count` in a start's `input` (they come from `csv`); a schedule on
   a workflow that declares a CSV is refused when written (409 `csv_required`), and a tick of one whose later version
   declares it is a `refused` request (`input_invalid`); a re-run takes the original input or new `csv`.
9. **Schedules: the expression, the input and the actor.**
   a. *Cron:* five fields only (minute-granular, so §8.2's tick key stays unique), checked by an in-house validator
      (ranges, lists, steps, names), with no dependency; an interval of at least 60 s with an optional offset; an IANA
      time zone checked with `zoneinfo`. Whatever Temporal still refuses is the sync's recorded failure.
   b. *The fixed input* is validated against the active version when written (422) and again at each tick (a `refused`
      request when it no longer fits), encrypted with the schedule's id as context.
   c. *The actor:* a tick's request has none; its audit entry names the schedule. A schedule is the tenant's: its
      author losing access doesn't stop it; disabling or deleting it does.
   d. *The catch-up window:* per schedule, 10 minutes by default, between 1 minute and 24 hours (provisional).
   *Recommended:* all four.
10. **`ScheduleTick`'s worker.** *Recommended:* in the dispatcher process (§8.2), as the dispatch role, on the
    unversioned queue `dewpoint-admission`, outside the engine's Worker Deployment; engine-core §11.11 amended; its
    replay test is its own, independent of `ENGINE_ABI`. It reads `TemporalScheduledStartTime`, a search attribute
    Temporal sets: Dewpoint still sets none (§6.2).
11. **The `trigger.rows` finding.** *Recommended:* file it as an issue now, and fix it in M1: the exception only for a
    version declaring a CSV, whose `row_count` is public; nothing runs in production, so a version that relied on it
    is refused when published again.
12. **The Compose proof.** Compose runs only in CI (its base images aren't approved locally). *Recommended:* one bounded
    CI step in the existing e2e job: a schedule with a 60-second interval on a synthetic workflow, its first run waited
    for at most 150 seconds. Cost: about 1–2.5 more minutes of the 2-core runner per e2e run.
13. **2b-3b, for later** (decided with its own outline): the HMAC scheme (a timestamped `<t>.<body>` signature with
    configurable headers; Mist's untimestamped body signature left to sub-project 3's Mist trigger); ingress's writes
    through one narrow SECURITY DEFINER function for counters and token buckets beside RLS-scoped inserts; the dedupe
    key always an HMAC under the endpoint's key, the sender's event id never stored plain, and the request key
    `evt:<inbound event id>:<workflow id>`; one 401 for an unknown endpoint, a disallowed address and a failed
    authentication alike; provisional rate defaults; the parent's resolver returning more than tenant, mode and
    material (§13); the load test as a local probe, not a CI job.
