# Engine 2b-2: Admission Implementation Plan

> **Status: outline.** The owner ruled on its nine decisions (2026-10-03, below) and asked for the trigger envelope's
> storage, ownership and retention to be specified before dispatch or re-runs count as designed: that design is
> below, for the owner's approval. As in 2b-1a and 2b-1b, each task is then built and tested on a prototype branch
> from `main`, and the plan is written from the tested diffs for the owner's review before execution.

**Goal:** every run starts through one durable queue: `admit_request` freezes a request in its caller's transaction,
and `dewpoint dispatcher` starts it on Temporal within its tenant's slots, with a reconciler that settles every start
whose outcome was lost; the run API and the dev CLI admit through it.

**Architecture:** `run_requests` is the queue and the intent in one row (§7.1); the trigger's envelope is stored
encrypted beside the request's claims. Admission runs in the API's (or the CLI's) transaction and never talks to
Temporal; the dispatcher is the only process that starts runs, under the gate's and the tenant's shared locks, and a
reconciler inside it (one leader) resolves uncertain starts, leaked slots and rows whose workflow closed. Every
transition moves the request, its slot and its pre-created `runs` row together (§7.8).

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy (async, asyncpg), Alembic, PostgreSQL 16 (RLS, advisory locks), the
Temporal Python SDK 1.33, Typer, Compose.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md` revision 6 (approved 2026-10-03): §7, with §2.3–2.5,
§2.7, §6.5, §9, §10.6 and §12–§14; `docs/superpowers/specs/2026-09-25-engine-core-design.md` §4.5 and §9. The
envelope design below goes into the 2b spec as revision 7, with this plan, once the owner approves it.

## What exists today

- `apps/runs.py` `admit` and `start_run` start a run directly: admission freezes no request, makes its own run id, uses
  free-text reasons, writes no audit entry, reads the gate without a lock, and takes a version id rather than a
  workflow. The trigger's envelope only lives in memory between `admit` and the start. `_start` takes "already
  started" without verifying it, and fails a run on one confirmed refusal.
- Already usable: the admission and lifecycle locks (written for the dispatch role), `claim_input` (claims need no
  `runs` row), the `dewpoint_dispatch` role with the claim and key grants, `RunInput.parent` for a run the dispatcher
  starts, the paired runs cursor with `invalid_cursor`.
- Missing: `run_requests`, a stored envelope, slots, `queued_at`, the gate lock, `engine_abi_changed`, queued
  references in retirement, `run.cancel`, `Idempotency-Key`, a reader of `worker_instances`, a per-tenant HMAC key, a
  dispatcher process and Compose service, a development Compose override, the tenant `erasing` status.

## The trigger envelope (for the owner's approval)

`claim_input` returns the trigger's envelope: its untainted values within `TRIGGER_INLINE`, with a handle in place of
every claim. Today it goes straight into the start. With a queue in between, the dispatcher (another process, later)
and a re-run (much later) both need it, so admission stores it.

- **Storage.** One row of `run_inputs`, encrypted as every claim is: the purpose `claim`, the row's id as context, the
  tenant's active data key. A new column `role` tells it apart: `claim` for the claims admission makes, `envelope` for
  the trigger's envelope, at most one per owner (a partial unique index). `run_requests.envelope_id` names it; the
  request row holds no input. Its `sensitive_pointers` is empty: every tainted value is a claim it holds by handle.
- **Ownership.** `owner_run_id` and `root_run_id` are the request's id, which is the run's id: the same owner as the
  claims it references, so the run that starts from it reads them as their owner. Claim reads (`fetch`) never return
  an envelope row: it isn't a claim, and no handle names it.
- **Readers.** The dispatcher, tenant-scoped, reads and decrypts it to build `RunInput.trigger`; the re-run path
  reconstructs from it (below). Nothing else reads it.
- **Retention.** It lives and dies with its request's other `run_inputs` rows: kept while the request or its run is
  retained (tenant retention, §10.1, 2b-4), deleted with the tenant (§6.5). A `refused` request has none, being refused
  before its trigger is claimed. A `cancelled` or `dead` request keeps its envelope until retention, so its re-run can
  use the original input.
- **Re-run with the original input.** The caller needs `run.view` on the old run and `run.start` on the workflow. In
  the API's transaction: read the old request's envelope and resolve every handle in it as the old run, its owner,
  into the complete plain input, held in memory and never logged; refuse with `input_not_retained` when the envelope or
  any claim it references is gone. Then admit it as a new request (source `rerun`) on the active version: validated
  against that version's input schema and claimed again under the new request's id. No old handle is ever reused.
- **No unkeyed hash.** The envelope is written after #28's fix (task 2), so no plaintext digest of it is ever stored.

## Milestones and tasks (first cut)

**M1. The queue and admission**
1. Schema: `run_requests` (with `envelope_id`), `tenant_run_limits` (platform default 5), `run_slots`, the current-build
   record; `run_inputs.role`; `runs.queued_at` (backfilled from `started_at`), `runs.started_at` nullable with no
   default, the `(queued_at, id)` index; `tenants.status` (`active`, `erasing`); grants and RLS: tenant-scoped for the
   api, dispatch and worker roles, and for the dispatcher's cross-tenant pick a function that returns queue-selection
   metadata only.
2. #28, as its own task: claims lose `content_hash`; an id conflict decrypts the existing claim and compares canonical
   plaintext, across key rotation too; the migration and the docs account for existing rows and older backups.
3. The tenant-keyed digest: a key derived from the tenant's data key (`KeySource` gains it), HMAC over the canonical
   JSON of source, workflow, mode and input, with its key version.
4. `admit_request`: §7.2's order, the envelope stored, reason codes (§9), one audit entry, a durable source's refusal
   kept as `refused`, several requests admitted in workflow-id order; the ABI check against the current-build record,
   failing closed when it's missing or stale.
5. Retirement counts queued references; a forced retirement cancels queued requests, audited (engine-core §4.5).

**M2. The dispatcher**
6. `dewpoint dispatcher`: its loop; the current build read from Temporal and recorded, with when it was observed; the
   worker-instance check (every live instance of the current build healthy with every capability, §2.7), made
   independently at every dispatch whatever the record says; its health evidence recorded, without any claim that
   2b-4's readiness gate has passed.
7. The `starting` transaction: per-tenant FIFO among due requests, the gate's and the tenant's shared locks, §2.3's
   critical checks, the defensive executable check, `engine_abi_changed`, a free slot, the pre-created `runs` row, the
   envelope read; waiting isn't failing (§2.5).
8. The start and its outcomes: `REJECT_DUPLICATE`; a confirmed refusal backs off (5 s doubling to 10 min) and goes
   `dead` after 10 with `start_failed`; an uncertain start stays `starting`; "already started" verified from the
   execution's started event, else `id_collision`; confirmation idempotent and late-safe (§7.8).
9. The root's end write releases its slot in the same transaction (the worker's projection).

**M3. The reconciler, cancels and the gate**
10. One leader by advisory lock; uncertain starts settled after a trustworthy absence; leaked slots released once the
    logical run's latest execution is terminal.
11. Rows left `running` whose workflow closed: the outcome Temporal reports, following continue-as-new (§7.6).
12. Cancels: a queued request at once, a running run through the dispatcher, a `starting` one when it resolves.
13. The gate-off race: the shared lock at dispatch and `dewpoint platform disable-production-runs`, which waits for
    `starting` requests to settle and reports unresolved ones.

**M4. The run API, the CLI and Compose**
14. `POST /t/{tid}/workflows/{wid}/runs` (`Idempotency-Key`, 202, 503 `production_runs_disabled`, 422, 409);
    `GET .../start-form`; `POST /t/{tid}/runs/{id}/cancel` with `run.cancel`; `POST /t/{tid}/runs/{id}/rerun`.
15. `GET /t/{tid}/runs` lists requests and runs together by `(queued_at, id)`; a request's status while it's `queued`
    or `starting`.
16. `dewpoint dev run` admits a workflow with the source `dev`; `--wait` is bounded and reports the database's terminal
    outcome, not merely `started`; `start_run` stays a test helper no command exposes.
17. Compose: the dispatcher service with the dispatch login; a development override for CI and local work (§2.1);
    the operations docs; engine-core §9 and the 2b spec's §13 updated.

**M5. Proofs (§12)**
18. Every §7.8 transition with a tenant limit of 1; a fast completion before the start's reply.
19. Races: admission and dispatch against retirement (both paths, both orders) and against the gate; the gate-off race.
20. On the dev server: uncertain starts, duplicate-id verification, the reconciler's outcome mapping, and an
    end-to-end run through the API, the dispatcher and the worker in Compose.

## The owner's rulings (2026-10-03)

1. **Build check:** a dispatcher-maintained, timestamped current-build record for admission; missing or stale fails
   closed; dispatch checks Temporal and the worker capabilities independently.
2. **API transaction:** admission stays atomic with its caller, with tenant-scoped grants and key reads.
3. **Dispatcher reads:** cross-tenant access only to queue-selection metadata; claim reads and every write stay
   tenant-scoped.
4. **Scope:** retention's health check at dispatch in 2b-4; `tenants.status` and its refusals now, the erasure
   procedure later; CSV in 2b-3; `disable-production-runs` now; health evidence recorded now, without claiming 2b-4's
   retention or readiness gate has passed.
5. **Re-runs:** new admissions on the active version; the caller may read the old run; the complete retained input is
   reconstructed and validated against the new version; old handles are never reused.
6. **Dev CLI:** `--wait` bounded, reporting the database's terminal outcome.
7. **ABI:** no change expected; a change to the workflow payload or the replay contract comes back for approval.
8. **Process:** prototype first; focused checks at milestones and one final suite, not a full suite at every replayed
   task.
9. **Claim hash:** issue #28, fixed before the production gate; removing `content_hash` and comparing decrypted
   plaintext on an id conflict is preferred; M1 may implement it as its own task, accounting for existing rows and
   backups in the migration.
