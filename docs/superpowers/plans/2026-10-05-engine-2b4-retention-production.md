# Engine 2b-4: Retention and Production — Outline

> **Status: an outline for the owner's decisions (2026-10-05), not authorization to build anything, nor to lift the
> production gate or ingress's development-only restriction.** As in 2b-1a through 2b-3b, once the owner rules, each
> sub-project is built on a prototype branch from `main`, with the owner's checkpoint after each milestone; its plan is
> then written from the replayed diffs, with a revision of the 2b spec, for the owner's review before execution.

**Goal:** Dewpoint can hold tenants' production data. Data leaves on schedule, a tenant can be erased, old keys can be
retired, the production Temporal is verified, every production blocker is fixed or bounded with the owner's explicit
decision, and a platform admin lifts the gate through audited readiness checks.

**Proposed split (decision D1):**
- **2b-4a, the data lifecycle:** retention (the tenant's retention, the retention job and its SLO), audit pruning,
  tenant erasure, re-encryption and key retirement (data keys, the tenants' event keypairs, the ingress key), and the
  two schema blockers, #28 and #35.
- **2b-4b, production hardening and the gate lift:** the engine blockers #16, #18 and #26, the production items of
  §7.9 (with the required dispatcher-scaling decision), the off-host audit anchors (#3), production Temporal, the
  readiness checks, `dewpoint platform enable-production-runs`, and enabling ingress in production.

**Spec:** `docs/superpowers/specs/2026-09-29-engine-2b-design.md`, revision 9: §10 (retention and production), §6.4
(key rotation and retirement), §6.5 (tenant erasure), §2.2–2.4 (the gate), §7.9 (open before production sign-off),
§8.3 (ingress's 2b-4 notes), §14 and §15. This outline's rulings land in a revision 10 with the plans.

## What exists today (main 6482c53)

- **The gate:** `platform_settings.production_runs`, off by default; `dewpoint platform init-environment` and
  `disable-production-runs` (its audit names no operator, §7.9); no command turns the gate on. Each live worker instance
  registers its health and its capabilities (`payload_codec`, `claim_check`, `cel_request_size_guard`); the dispatcher
  and the reconciler report (`dispatcher_reports`).
- **Tenants:** the status `erasing` is refused by admission, dispatch, the `ScheduleTick` activity, the matcher and
  ingress's recording function, under the tenant's lifecycle lock (`dewpoint:tenant:<id>`, shared). Nothing sets it: no
  erasure transition, command or steps exist.
- **Keys:** `dewpoint keys status`, `keys rewrap` (moving data keys to a new KEK), `keys rotate-dek` (a new data-key
  version; old versions stay readable) and `keys ensure-tenants`. Nothing re-encrypts stored records under a newer
  version, and nothing retires a version. The tenants' event keypairs exist at version 1 only; the ingress key carries
  an id, but nothing rotates it. `max_run_duration_days` (30) is a setting, not a recorded history: §6.4's payload floor
  needs "the longest maximum run duration ever configured".
- **Retention:** none. No `tenant_retention`, `retention_sweeps`, `dewpoint_retention` role or `dewpoint retention`
  process. So nothing frees stored inbound events (ingress fails closed at its retained caps), expired CSV uploads
  (one-hour `expires_at`) stay as rows, and schedule tombstones wait for retention (§8.2).
- **Audit:** a hash chain per scope, anchored every 15 minutes by Compose's `audit-anchor` service to a file on a
  Compose volume (`/anchors/anchors.jsonl`); `dewpoint audit verify` and `audit freshness`. No pruning, no off-host
  sink (#3).
- **Temporal:** only an address and a namespace are configured. No TLS, mTLS or API-key settings exist, nor the
  `DEWPOINT_TEMPORAL_INSECURE_DEV` exception §10.4 describes.
- **Ingress:** development-only: `dewpoint ingress` refuses to start, and `record_inbound_events()` records nothing,
  unless the recorded environment is `development`.
- **CI:** the Compose proofs pass: a run, a schedule and a webhook (the last one first green on #37).

## Dependencies

Each arrow reads "needs".

- **Retention → read cutoff.** Every user-facing read stops returning data past its cutoff at once, whatever the
  physical state (§10.1), so the cutoff filtering lands with (or before) the first deletion.
- **Key retirement → retention or re-encryption.** A data-key version retires only when nothing needs it (§6.4): the
  payload floor has passed and no execution that could hold its payloads is open; every stored record under it
  (`run_inputs`, `step_outputs`, `run_secret_index`, pending `run_requests` and `inbound_events`, `csv_uploads`,
  schedule inputs and Temporal schedule actions) is re-encrypted or deleted by retention; no request's idempotency
  digest uses it; the tenant's event private keys wrapped by it are re-wrapped. So retirement needs the re-encryption
  command, retention's deletion, and a recorded maximum run duration.
- **#28's fix → decrypt across versions.** Comparing a rewritten claim's plaintext needs the existing claim's version
  to still open, which retirement's rules already guarantee for any record it would compare.
- **Erasure → the lifecycle lock (exists), the reconciler (exists), schedule pausing, cancelling, then key deletion.**
  §6.5's order: mark `erasing` (and raise the tenant's schedules' generations in the same transaction, §7.9); reconcile
  every `starting` request; pause schedules; cancel queued requests and pending events; cancel running runs and wait
  until they're terminal; delete the tenant's keys, data keys and event keypairs alike, last. Whether erasure also
  deletes the rows, or relies on the deleted keys (crypto-shredding) and retention, is decision D3.
- **Audit pruning → off-host anchors (#3).** Pruning anchors a checkpoint at the last entry pruned and verification
  starts from it (§10.2). With the anchor on the same host, a privileged operator could prune, rewrite and re-anchor
  undetected; the checkpoint must sit where #3 puts anchors. Decision D5.
- **Readiness checks → retention, production Temporal, keys, workers, reports.** `enable-production-runs` checks
  (§10.6): the environment; the namespace, its retention and verified TLS; every live worker of the current build
  healthy with its capabilities; every stored data key unwrapping, and the workers' own path reading each tenant's key;
  the dispatcher and reconciler reporting; a successful retention sweep within 24 hours with lag under 24 hours. The
  retention SLO also becomes a dispatch-time critical check that pauses new production starts when breached (§10.3).
- **Ingress in production → retention, erasure, key rotation, the scaling decision, the gate.** Retention frees the
  retained caps (terminal events deleted); erasure cancels a tenant's pending events and deletes its event keypairs; the
  event keypairs and the ingress key can be rotated and retired; matching scales with dispatchers (D9); and the gate
  is on. Whether ingress's restriction lifts with the gate or by its own audited switch is decision D14.
- **The gate lift → every blocker.** #28, #35, #3; #16, #18 and #26 fixed, or bounded with a demonstrated bound and the
  owner's explicit risk decision; each §7.9 item fixed or explicitly decided; the readiness checks passing.

## Gate-lift blockers (the owner's rulings, 2026-10-05)

- **#28** (claims keep an unkeyed SHA-256 of their plaintext): remove `content_hash`; on a claim-id conflict, decrypt
  the existing claim and compare canonical plaintext; the migration drops the column, and its docs say backups taken
  before it still hold the hashes. Idempotent across a key rotation. Proposed for 2b-4a's first milestone.
- **#35** (four tables don't tie `workflow_id` to the row's tenant: `run_requests`, `csv_uploads`, `csv_mappings`,
  `schedules`): composite foreign keys to `workflows (id, tenant_id)`, as 2b-3b's bindings have, after a check for
  existing inconsistent rows that refuses to proceed if any exist; the direct-role reproduction becomes the regression.
  `versions` and `runs` stay marked for investigation. Proposed with #28.
- **#3** (production audit anchors): an on-host anchor isn't the specified production integrity boundary. An off-host
  sink with its own retention (object storage with object lock, or a syslog or SIEM target), written by the auditor role
  only; an anchor-signing key held apart from the database host's credentials; monitoring of the sink itself; a
  scheduled `dewpoint audit verify` against the sink that alerts on any failure; a runbook, signing-key rotation
  included. Proposed for 2b-4b, before audit pruning runs in production (D5).
- **#16, #18, #26** (reachable stuck or terminated runs): each gets a fix, or a demonstrated bound with the owner's
  explicit risk decision, before the gate-lift checkpoint. Run-failure modes aren't deferrable by kind.
  - #16: a continue-as-new snapshot over 2 MiB fails its workflow task on every retry, past the run's deadline.
  - #18: binding many large CEL views in one workflow task can outlast the SDK's 2 s deadlock timeout, and retry.
  - #26: a filter over a large plain string sends it once per item, until Temporal terminates the run for its history
    size.
  Each issue lists fix directions. Engine changes here may raise `ENGINE_ABI` (7), with its own golden histories and
  replay gate. Decision D7.

## Milestones (first cut)

**2b-4a, the data lifecycle**
- **M1. The schema blockers:** #28 and #35, each with its migration and regression.
- **M2. Retention:** `tenant_retention` (default 30 days, 1 to 365, set with `tenant.manage`); the read cutoff on every
  user-facing path; the `dewpoint_retention` role (the only role with `DELETE` on retained tables) and the `dewpoint
  retention` process (batches per tenant, under tenant scope, idempotent; an audit entry per tenant per sweep, counts
  only; each sweep recorded with its lag); what it deletes (§10.1, terminal inbound events and expired CSV uploads
  included, schedule tombstones once Temporal reports them gone); the SLO's dispatch-time check; audit pruning behind
  D5.
- **M3. Re-encryption and retirement:** `dewpoint keys reencrypt` over every record type §6.4 lists; rotating and
  re-wrapping the tenants' event keypairs; rotating the ingress key; retirement's checks (the payload floor, open
  executions, idempotency digests); a recorded maximum run duration. The ingress minor on embedded key versions (D10)
  lands here, since rotation makes versions matter.
- **M4. Tenant erasure:** the transition (with the schedules' generations), §6.5's steps, its command and audit, and a
  proof that nothing of the tenant stays decodable afterwards.

**2b-4b, production hardening and the gate lift**
- **M1. The engine blockers:** #16, #18 and #26, each fixed or bounded (D7).
- **M2. §7.9's hardening:** as the ledger below rules, item by item, the dispatcher-scaling change and its measurement
  included.
- **M3. Production Temporal and audit integrity:** verified TLS, mTLS or an API key, the development-only insecure
  exception (§10.4); #3's off-host anchors.
- **M4. Readiness and the gate:** the readiness checks, `enable-production-runs` with the operator's attestation, the
  disable command naming its operator, enabling ingress in production (D14). Then the gate-lift checkpoint: the owner
  rules with every blocker's evidence in front of them. Lifting the gate on a real deployment is the owner's act, not a
  plan task.

## Decision ledger

| # | Decision | Proposal |
|---|---|---|
| D1 | The split | 2b-4a then 2b-4b, as above; one outline, two plans, two prototypes. |
| D2 | Order inside 2b-4a | #28 and #35 first, then retention, then re-encryption and retirement, then erasure, which needs the others. |
| D3 | What erasure deletes | Crypto-shredding first (the keys deleted last, §6.5), then the tenant's rows deleted by an erasure sweep of the retention job; an erased tenant's audit entries follow the audit policy (D5), never the tenant's retention. |
| D4 | The read cutoff | Filter in the shared read paths (one query helper per kind), proven by a test per user-facing path; never a database view the API could bypass. |
| D5 | Audit pruning and #3 | Pruning ships in 2b-4a disabled in production until #3's sink is configured; the readiness checks refuse a production gate without it. |
| D6 | #3's first sink | One target first; which one (object storage with object lock, or syslog or SIEM) is the owner's. Testing it needs an image the owner approves (for object storage, an S3-compatible server). |
| D7 | #16, #18, #26 | Fix each, per the issues' preferred directions: #16 bounds the snapshot (or ends the run with a fixed code before the limit); #18 bounds measuring's cost; #26 sends a shared value once, as a size claim. Bounds instead of fixes need the owner's risk decision, case by case. |
| D8 | §7.9's items | See below. |
| D9 | Dispatcher scaling | Required before production. Measure first on the CLI dev server (approved image), then choose: `SKIP LOCKED` on the endpoint row, or dispatchers taking disjoint candidates. Rerun the load probe's separate-tenant control after the change; §8.3's fairness and races are re-proven. |
| D10 | 2b-3b's deferred ingress minors | (1) the matcher's endless retry: with §7.9's bounded retry and alerting (2b-4b M2); (2) the guide's warning about an empty `DEWPOINT_INGRESS_TRUSTED_PROXIES` behind a proxy: a doc fix (2b-4b M4); (3) changing `events_pointer` after deliveries changes deduplication: refuse the change once events exist, or document it (the owner's choice); (4) the recording function not checking a blob's embedded key version: an added predicate (2b-4a M3). |
| D11 | The operator's identity | `enable-` and `disable-production-runs` record the operator: an admin login (an identity the platform knows) rather than the OS user. The mechanism is the owner's choice. |
| D12 | Production Temporal | mTLS and API-key auth both, as §10.4 says; tested against the CLI dev server for configuration and refusal paths only, since a TLS-terminating Temporal isn't an approved image. |
| D13 | Mist's bearer token | Verified with a real Mist delivery before the guide documents it, or the guide keeps HMAC as the only documented production path. |
| D14 | Ingress in production | Its own audited switch, after the runs gate, so ingress can stay off while runs are on. |

**§7.9's items (D8), proposed:**
- *Bound the serial dispatch cycle:* fix (a time budget per cycle, with the leader's schedule batches inside it), 2b-4b
  M2.
- *Erasure pauses schedules:* fix, with erasure (2b-4a M4).
- *The CSV reader's memory:* a measured bound for concurrent uploads and a cap on them, or a streaming reader; the
  owner's choice, 2b-4b M2.
- *Bounded retry and alerting for a deterministic per-request failure* (the dispatcher's, the reconciler's and, per
  D10, the matcher's): fix, 2b-4b M2.
- *An operator's recovery path* for a run or slot whose Temporal history is gone, and for a `starting` request whose
  run already ended: fix (a command, audited), 2b-4b M2.
- *Bounded retry and alerting for a cancel that keeps failing to send:* fix, 2b-4b M2.
- *The disable command's audit identifies the operator:* fix, with D11 (2b-4b M4).
- *Matching scaling with dispatchers:* D9.
- *Ingress's limits:* production values from measurements with a real Temporal and up to twenty bindings, or the
  development values kept with the owner's risk decision; 2b-4b M2.
- *Mist's bearer token:* D13.
- *The Compose proofs:* the run, the schedule and the webhook have passed in CI; they stay required on every PR.

## Open and separate

- **The gitleaks PR range:** CI's security job still uses `gitleaks/gitleaks-action` v2. Its fix (scanning a PR's
  whole `base..head` range with a pinned gitleaks) was never committed; its branch holds no commits of its own. #37's
  scan covered all 14 of its commits, but a PR past the action's first 30 commits would go partly unscanned. A small
  change of its own, not a 2b-4 dependency.
- **The dispatcher backoff test's clock skew:** a separate session is fixing it.
- **#2** (the signed release path), and the parent spec's later sub-projects (Mist integration; the UI's run form, CSV
  mapping screen and runs view).
