# Engine 2b-2: Admission Implementation Plan

> **Status: outline.** The owner ruled on its nine decisions (2026-10-03, below), then on the trigger envelope's
> design: with its two boundaries made explicit (claim reads and grants never serve an envelope; re-runs resolve a
> request, not a run) and its row shape enforceable, it's approved for the 2b spec's revision 7 and the prototype, not
> as production sign-off. As in 2b-1a and 2b-1b, each task is built and tested on a prototype branch from `main`, and
> the plan is written from the tested diffs for the owner's review before execution.

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

## The trigger envelope

`claim_input` returns the trigger's envelope: its untainted values within `TRIGGER_INLINE`, with a handle in place of
every claim. Today it goes straight into the start. With a queue in between, the dispatcher (another process, later)
and a re-run (much later) both need it, so admission stores it.

- **Storage.** One row of `run_inputs`, encrypted as every claim is: the purpose `claim`, the row's id as context, the
  tenant's active data key. A new column `role` tells it apart: `claim` for the claims admission makes, `envelope` for
  the trigger's envelope. Its `sensitive_pointers` is empty: every tainted value is a claim it holds by handle.
- **An enforceable row shape:**
  - at most one envelope per owner: a partial unique index on `run_inputs (owner_run_id) WHERE role = 'envelope'`;
  - a claim always has a `pointer` (where in the input it came from) and the envelope never does:
    `CHECK ((role = 'envelope') = (pointer IS NULL))`, `pointer` becoming nullable for that one case;
  - the request names its envelope, and the reference can only reach an envelope its request owns: `run_requests`
    holds `envelope_id` and a constant `envelope_role` (`'envelope'`), with the foreign key `(envelope_id, id,
    envelope_role)` → `run_inputs (id, owner_run_id, role)` (unique there), `ON DELETE RESTRICT`;
  - only a `refused` request has no envelope: `CHECK ((status = 'refused') = (envelope_id IS NULL))`.
- **Ownership.** `owner_run_id` and `root_run_id` are the request's id, which is the run's id: the same owner as the
  claims it references, so the run that starts from it reads them as their owner.
- **Claim reads and grants never serve it.** Today `core/claims/service.py`'s `_row()`, `fetch()` and `grant()` (and
  the closure a grant walks) accept any `run_inputs` row the run owns. Each excludes `role = 'envelope'`: a handle that
  names an envelope's id is refused as any unreadable claim is (`claim_unavailable`), and a grant that reaches one
  grants nothing and is refused the same way. Tests attempt both.
- **Its own reader.** `read_envelope(s, cipher, tenant_id, request_id)`, tenant-scoped and request-scoped: it follows
  the request's `envelope_id` and nothing else. Its callers are the dispatcher, building `RunInput.trigger`, and the
  re-run path.
- **One transaction.** Admission writes the claims, the envelope and the request in its savepoint, inside its caller's
  transaction: all three commit or roll back together, and a lost idempotency race discards all three (§7.2, step 6).
- **Retention.** All three are kept while the request is `queued` or `starting`; the foreign key keeps the envelope
  for as long as its request row exists. They're deleted together, in one transaction, at the applicable terminal
  cutoff: the run's end plus the tenant's retention for a started request, the request's own end for a `cancelled`,
  `dead` or `refused` one (§10.1; 2b-4 builds the job), and with the tenant (§6.5). A `refused` request has no envelope
  and keeps no claims, being refused before its trigger is claimed or rolled back to its savepoint.
- **Re-run with the original input.** `POST /t/{tid}/runs/{id}/rerun` names a request: its id is also its run's, if
  it has one. In the API's transaction:
  1. resolve the request by id, tenant-scoped: a request cancelled while still queued may never have had a `runs` row,
     so the run isn't the prerequisite;
  2. authorize the caller: `run.view` in the tenant to read that request's input, and `run.start` on its workflow;
  3. read its envelope with `read_envelope` and resolve every handle in it as the request, the claims' owner, into the
     complete plain input, held in memory and never logged;
  4. refuse with `input_not_retained` when there's no such input: a run from before 2b-2, which has no request, a
     request with no envelope (`refused`), or a missing envelope or claim (retention removed it);
  5. admit it as a new request (source `rerun`) on the workflow's active version: validated against that version's
     input schema and claimed again under the new request's id. No old handle is ever reused.
- **No unkeyed hash.** The envelope is written after #28's fix (task 2), so no plaintext digest of it is ever stored.

## Milestones and tasks (first cut)

**M1. The queue and admission**
1. Schema: `run_requests` (with `envelope_id` and the envelope constraints above), `tenant_run_limits` (platform
   default 5), `run_slots`, the current-build record; `run_inputs.role`, the nullable `pointer` and their checks, the
   one-envelope index; `runs.queued_at` (backfilled from `started_at`), `runs.started_at` nullable with no
   default, the `(queued_at, id)` index; `tenants.status` (`active`, `erasing`); grants and RLS: tenant-scoped for the
   api, dispatch and worker roles, and for the dispatcher's cross-tenant pick a function that returns queue-selection
   metadata only.
2. #28, as its own task: claims lose `content_hash`; an id conflict decrypts the existing claim and compares canonical
   plaintext, across key rotation too; the migration and the docs account for existing rows and older backups.
3. The tenant-keyed digest: a key derived from the tenant's data key (`KeySource` gains it), HMAC over the canonical
   JSON of source, workflow, mode and input, with its key version.
4. The envelope boundary: claim reads (`_row`, `fetch`), grants and their closure exclude envelopes; `read_envelope`;
   tests of a handle read and a grant that reach an envelope.
5. `admit_request`: §7.2's order, the claims, envelope and request written in one savepoint, reason codes (§9), one audit entry, a durable source's refusal
   kept as `refused`, several requests admitted in workflow-id order; the ABI check against the current-build record,
   failing closed when it's missing or stale.
6. Retirement counts queued references; a forced retirement cancels queued requests, audited (engine-core §4.5).

**M2. The dispatcher**
7. `dewpoint dispatcher`: its loop; the current build read from Temporal and recorded, with when it was observed; the
   worker-instance check (every live instance of the current build healthy with every capability, §2.7), made
   independently at every dispatch whatever the record says; its health evidence recorded, without any claim that
   2b-4's readiness gate has passed.
8. The `starting` transaction: per-tenant FIFO among due requests, the gate's and the tenant's shared locks, §2.3's
   critical checks, the defensive executable check, `engine_abi_changed`, a free slot, the pre-created `runs` row, the
   envelope read; waiting isn't failing (§2.5).
9. The start and its outcomes: `REJECT_DUPLICATE`; a confirmed refusal backs off (5 s doubling to 10 min) and goes
   `dead` after 10 with `start_failed`; an uncertain start stays `starting`; "already started" verified from the
   execution's started event, else `id_collision`; confirmation idempotent and late-safe (§7.8).
10. The root's end write releases its slot in the same transaction (the worker's projection).

**M3. The reconciler, cancels and the gate**
11. One leader by advisory lock; uncertain starts settled after a trustworthy absence; leaked slots released once the
    logical run's latest execution is terminal.
12. Rows left `running` whose workflow closed: the outcome Temporal reports, following continue-as-new (§7.6).
13. Cancels: a queued request at once, a running run through the dispatcher, a `starting` one when it resolves.
14. The gate-off race: the shared lock at dispatch and `dewpoint platform disable-production-runs`, which waits for
    `starting` requests to settle and reports unresolved ones.

**M4. The run API, the CLI and Compose**
15. `POST /t/{tid}/workflows/{wid}/runs` (`Idempotency-Key`, 202, 503 `production_runs_disabled`, 422, 409);
    `GET .../start-form`; `POST /t/{tid}/runs/{id}/cancel` with `run.cancel`; `POST /t/{tid}/runs/{id}/rerun`.
16. `GET /t/{tid}/runs` lists requests and runs together by `(queued_at, id)`; a request's status while it's `queued`
    or `starting`.
17. `dewpoint dev run` admits a workflow with the source `dev`; `--wait` is bounded and reports the database's terminal
    outcome, not merely `started`; `start_run` stays a test helper no command exposes.
18. Compose: the dispatcher service with the dispatch login; a development override for CI and local work (§2.1);
    the operations docs; engine-core §9 and the 2b spec's §13 updated.

**M5. Proofs (§12)**
19. Every §7.8 transition with a tenant limit of 1; a fast completion before the start's reply.
20. Races: admission and dispatch against retirement (both paths, both orders) and against the gate; the gate-off race.
21. On the dev server: uncertain starts, duplicate-id verification, the reconciler's outcome mapping, and an
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
5. **Re-runs:** new admissions on the active version; the complete retained input is reconstructed and validated
   against the new version; old handles are never reused. Refined with the envelope (below): a re-run resolves the
   old *request*, not a run.
6. **Dev CLI:** `--wait` bounded, reporting the database's terminal outcome.
7. **ABI:** no change expected; a change to the workflow payload or the replay contract comes back for approval.
8. **Process:** prototype first; focused checks at milestones and one final suite, not a full suite at every replayed
   task.
9. **Claim hash:** issue #28, fixed before the production gate; removing `content_hash` and comparing decrypted
   plaintext on an id conflict is preferred; M1 may implement it as its own task, accounting for existing rows and
   backups in the migration.
10. **The trigger envelope** (2026-10-03): the storage approach is approved for revision 7 and the prototype, not as
    production sign-off, with two boundaries explicit: ordinary claim lookup and grants exclude envelopes, read only
    through a tenant- and request-scoped reader, with a test of an attempted handle read and of an attempted grant;
    and a re-run resolves the old request by id, authorizes reading that request's input and `run.start` on its
    workflow, then reconstructs and re-admits, with `input_not_retained` for runs from before 2b-2 and for a missing
    envelope or claim. The row shape is enforceable (one envelope per owner, a valid request-to-envelope reference, an
    explicit `pointer` rule); envelope, claims and request share one transaction; retention keeps all three while the
    request is `queued` or `starting` and deletes them together at the applicable terminal cutoff.
