# Engine 2b-2: Admission Implementation Plan

> **Status: outline, for the owner's decisions.** The tasks below are a first cut. As in 2b-1a and 2b-1b, each one is
> built and tested on a prototype branch from `main` first, and the plan is then written from the tested diffs, each
> replayed tests-first, for the owner's review before execution.

**Goal:** every run starts through one durable queue: `admit_request` freezes a request in its caller's transaction,
and `dewpoint dispatcher` starts it on Temporal within its tenant's slots, with a reconciler that settles every start
whose outcome was lost; the run API and the dev CLI admit through it.

**Architecture:** `run_requests` is the queue and the intent in one row (§7.1). Admission runs in the API's (or the
CLI's) transaction and never talks to Temporal; the dispatcher is the only process that starts runs, under the gate's
and the tenant's shared locks, and a reconciler inside it (one leader) resolves uncertain starts, leaked slots and rows
whose workflow closed. Every transition moves the request, its slot and its pre-created `runs` row together (§7.8).

**Tech stack:** Python 3.12, FastAPI, SQLAlchemy (async, asyncpg), Alembic, PostgreSQL 16 (RLS, advisory locks), the
Temporal Python SDK 1.33, Typer, Compose.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md` revision 6 (approved 2026-10-03): §7, with §2.3–2.5,
§2.7, §6.5, §9, §10.6 and §12–§14; `docs/superpowers/specs/2026-09-25-engine-core-design.md` §4.5 and §9.

## What exists today

- `apps/runs.py` `admit` and `start_run` start a run directly: admission freezes no request, makes its own run id, uses
  free-text reasons, writes no audit entry, reads the gate without a lock, and takes a version id rather than a
  workflow. `_start` takes "already started" without verifying it, and fails a run on one confirmed refusal.
- Already usable: the admission and lifecycle locks (written for the dispatch role), `claim_input` (claims need no
  `runs` row), the `dewpoint_dispatch` role with the claim and key grants, `RunInput.parent` for a run the dispatcher
  starts, the paired runs cursor with `invalid_cursor`.
- Missing: `run_requests`, slots, `queued_at`, the gate lock, `engine_abi_changed`, queued references in retirement,
  `run.cancel`, `Idempotency-Key`, a reader of `worker_instances`, a per-tenant HMAC key, a dispatcher process and
  Compose service, a development Compose override, the tenant `erasing` status.

## Milestones and tasks (first cut)

**M1. The queue and admission**
1. Schema: `run_requests`, `tenant_run_limits` (platform default 5), `run_slots`; `runs.queued_at` (backfilled from
   `started_at`), `runs.started_at` nullable with no default, the `(queued_at, id)` index; `tenants.status`
   (`active`, `erasing`); grants and RLS for the api, dispatch and worker roles.
2. The tenant-keyed digest: a key derived from the tenant's data key (`KeySource` gains it), HMAC over the canonical
   JSON of source, workflow, mode and input, with its key version.
3. `admit_request`: §7.2's order (authorize, idempotency lookup with the stored key version, the mutable checks for a
   new key under the admission and lifecycle locks, digest, claim, `ON CONFLICT DO NOTHING` insert with the
   savepoint and the winner's comparison, one audit entry), reason codes (§9), a durable source's refusal kept as
   `refused`, several requests admitted in workflow-id order.
4. Retirement counts queued references; a forced retirement cancels queued requests, audited (engine-core §4.5).

**M2. The dispatcher**
5. `dewpoint dispatcher`: its loop, the current build read from Temporal, and the platform's view of it recorded for
   admission (decision 1); the worker-instance check (every live instance of the current build healthy with every
   capability, §2.7); its own health report (decision 4e).
6. The `starting` transaction: per-tenant FIFO among due requests (`SKIP LOCKED`), the gate's and the tenant's shared
   locks, §2.3's critical checks, the defensive executable check, `engine_abi_changed`, a free slot, the pre-created
   `runs` row; waiting isn't failing (§2.5).
7. The start and its outcomes: `REJECT_DUPLICATE`, a confirmed refusal backs off (5 s doubling to 10 min) and goes
   `dead` after 10 with `start_failed`; an uncertain start stays `starting`; "already started" verified from the
   execution's started event, else `id_collision`; confirmation idempotent and late-safe (§7.8).
8. The root's end write releases its slot in the same transaction (the worker's projection).

**M3. The reconciler, cancels and the gate**
9. One leader by advisory lock; uncertain starts settled after a trustworthy absence; leaked slots released once the
   logical run's latest execution is terminal.
10. Rows left `running` whose workflow closed: the outcome Temporal reports, following continue-as-new (§7.6).
11. Cancels: a queued request at once, a running run through the dispatcher, a `starting` one when it resolves.
12. The gate-off race: the shared lock at dispatch and `dewpoint platform disable-production-runs`, which waits for
    `starting` requests to settle and reports unresolved ones (decision 4d).

**M4. The run API, the CLI and Compose**
13. `POST /t/{tid}/workflows/{wid}/runs` (`Idempotency-Key`, 202, 503 `production_runs_disabled`, 422, 409);
    `GET .../start-form`; `POST /t/{tid}/runs/{id}/cancel` with `run.cancel`; re-runs (decision 5).
14. `GET /t/{tid}/runs` lists requests and runs together by `(queued_at, id)`; a request's status while it's `queued`
    or `starting`.
15. `dewpoint dev run` admits with the source `dev` and waits on the database (decision 6); `start_run` stays a test
    helper no command exposes.
16. Compose: the dispatcher service with the dispatch login; a development override for CI and local work (§2.1);
    the operations docs; engine-core §9 and the 2b spec's §13 updated.

**M5. Proofs (§12)**
17. Every §7.8 transition with a tenant limit of 1; a fast completion before the start's reply.
18. Races: admission and dispatch against retirement (both paths, both orders) and against the gate; the gate-off race.
19. On the dev server: uncertain starts, duplicate-id verification, the reconciler's outcome mapping, and an
    end-to-end run through the API, the dispatcher and the worker in Compose.

## Decisions for the owner

1. **Admission's ABI check without Temporal.** §7.2 checks the ABI against the current build, but the API has no
   Temporal client (§7.7). *Recommended:* the dispatcher records the current build (id, ABI, when observed) in the
   database on every cycle; admission reads it and refuses with `no_current_build` when it's missing or stale.
2. **Admission in the API's transaction.** §7.2 runs it in the caller's transaction, so the api role needs INSERT on
   `run_requests`, `run_inputs` and `run_secret_index`, and the API process a `KeyringKeys` (it already holds the KEK
   to create tenants' keys). *Recommended:* yes, as the spec says.
3. **The dispatcher reads every tenant's queue.** *Recommended:* a narrow cross-tenant SELECT policy for the dispatch
   role on `run_requests` (and slots and limits); every write then runs under `tenant_scope`.
4. **Scope:**
   a. Retention's health check at dispatch (§2.3): *recommended* deferred to 2b-4, which builds retention; the gate
      can't open before 2b-4.
   b. Tenant erasure: *recommended* `tenants.status` and its refusals at admission and dispatch now; the erasure
      procedure (§6.5) in its own plan.
   c. CSV (the run body's `csv` and the start form's declaration): *recommended* 2b-3, with CSV itself.
   d. `disable-production-runs` with its settle wait (§2.4): *recommended* now, since it's the other side of the
      dispatcher's lock; enabling stays in 2b-4.
   e. The dispatcher's and reconciler's health reports (§10.6 reads them): *recommended* recorded now.
5. **Re-runs.** *Recommended:* `POST /t/{tid}/runs/{id}/rerun` with `Idempotency-Key`, the original input by default
   while its `run_inputs` are retained, or a new input in the body; a new admission on the active version.
6. **The dev CLI** admits a workflow (its active version), not a version id, and `--wait` reads the database.
   *Recommended:* yes.
7. **No ABI change expected.** The dispatcher starts `RunGraph` with today's `RunInput`, and the slot release is in the
   projection activity, so `ENGINE_ABI` stays 6. If the prototype finds a workflow change, it comes back to the owner.
8. **Process:** prototype first, one plan and one branch, milestones as above, checkpoints after M1, M2 and M3, then a
   whole-branch review after M5; inline execution by cherry-pick, as 2b-1b.
9. **A finding in merged 2b-1b code.** `run_inputs.content_hash` and `step_outputs.content_hash` are an unkeyed SHA-256
   of each claim's plaintext, sensitive claims included (`core/claims/service.py` `_write`): any reader of those tables
   can test guesses for a low-entropy secret, the exposure §7.2 avoids for the digest. *Recommended:* file it as an
   issue now, and fix it in M1 with the same tenant-derived key the digest needs (a keyed hash; existing development
   rows rehashed by a one-off command, or accepted since nothing runs in production).
