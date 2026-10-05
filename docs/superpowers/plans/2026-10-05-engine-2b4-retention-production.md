# Engine 2b-4: Retention and Production — Outline

> **Status: approved by the owner as an outline (82bfca6, finalized 3b875c0, 2026-10-05); D2, D4 and D5 accepted; D6
> and D12 approved as proof candidates, not proven production boundaries, with D12b ruled and the proofs' images and
> `boto3` approved; no prototype, detailed plan or gate lift authorized. It was revised after the owner's first review
> (erasure's completion, production Temporal's proof, Mist, event grouping, ingress's switch), second (erasure: no
> reversal, durable progress, the `tenants` schema), third (the firing inventory before schedules are deleted,
> completeness from Temporal's retention bound, audit entries described as they are, eligibility requiring `active`),
> fourth (fencing in-flight writers, the schedule sync's included; the bound as the earliest final check) fifth (late
> Temporal writes made unable to fire and reconciled after completion), sixth (an enforced, audited namespace-change
> boundary for the 30-day cap; reconciliation's residual risk; missed firings recorded) and seventh (which targets
> qualify for that boundary; both readiness paths failing closed without it; the schedule action corrected). Not
> authorization to build anything; no gate is authorized to lift by this review, neither the production gate nor
> ingress's development-only restriction.** As in 2b-1a through 2b-3b, once the owner rules, each sub-project is built
> on a prototype branch from `main`, with the owner's checkpoint after each milestone; its plan is then written from
> the replayed diffs, with a revision of the 2b spec, for the owner's review before execution.

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
  (`run_inputs`, `step_outputs`, `run_secret_index`, pending `run_requests` and `inbound_events`, `csv_uploads`, the
  `schedules` rows' inputs) is re-encrypted or deleted by retention; each Temporal schedule's action, which carries only
  the schedule's id but is sealed by the codec under the tenant's key, is re-sealed by updating the schedule, since a
  tick couldn't decode its argument once the version retires; no request's idempotency digest uses it; the tenant's
  event private keys wrapped by it are re-wrapped. So retirement needs the re-encryption
  command, retention's deletion, and a recorded maximum run duration.
- **#28's fix → decrypt across versions.** Comparing a rewritten claim's plaintext needs the existing claim's version
  to still open, which retirement's rules already guarantee for any record it would compare.
- **Erasure → the lifecycle lock (exists), the reconciler (exists), Temporal's deletion, then the keys, then the
  sweep.** Mark `erasing` (raising the tenant's schedules' generations in the same transaction, §7.9); reconcile every
  `starting` request; delete its Temporal schedules; cancel queued requests and pending events; cancel running runs and
  wait until they're terminal; delete every execution, enumerated durably and read back; delete its keys, data keys and
  event keypairs alike, last among the operations that need them; then sweep its rows. Irreversible once `erasing` is
  committed. "Tenant erasure" below (D3).
- **Audit pruning → off-host anchors (#3).** Pruning anchors a checkpoint at the last entry pruned and verification
  starts from it (§10.2). With the anchor on the same host, a privileged operator could prune, rewrite and re-anchor
  undetected; the checkpoint must sit where #3 puts anchors. Decision D5.
- **Readiness checks → retention, production Temporal, keys, workers, reports.** `enable-production-runs` checks
  (§10.6): the environment; the namespace, its retention and verified TLS; every live worker of the current build
  healthy with its capabilities; every stored data key unwrapping, and the workers' own path reading each tenant's key;
  the dispatcher and reconciler reporting; a successful retention sweep within 24 hours with lag under 24 hours. The
  retention SLO also becomes a dispatch-time critical check that pauses new production starts when breached (§10.3).
- **Ingress in production → retention, erasure, key rotation, the scaling decision, its own switch.** Retention frees
  the retained caps (terminal events deleted); erasure cancels a tenant's pending events and deletes its event
  keypairs; the event keypairs and the ingress key can be rotated and retired; matching scales with dispatchers (D9).
  An audited switch of its own governs its first activation in production; once on, turning the runs gate off still
  lets it record events while matching waits (§2.5). "Ingress in production" below (D14).
- **Readiness → a real verified-TLS proof and a verified namespace-change boundary.** Both readiness paths
  (`enable-production-runs` and ingress's own switch) pass only after the production Temporal proof and fail closed
  without a verified boundary for the 30-day cap ("Production Temporal" below, D12 and D3g).
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

## Tenant erasure (D3)

**Irreversible once `erasing` is committed (D3a, the owner's ruling).** Before its keys are deleted, an erasure may
already have deleted the tenant's schedules and executions and cancelled its runs; returning it to `active` would
restore none of them. An operator can stop an erasure (audited; the tenant stays `erasing`, every refusal still
applies) and retry it, never reverse it.

**Durable progress.** `tenant_erasures` holds who asked, when, the step reached, whether an operator stopped it, its
attempts and the last failure's code. The steps with an effect outside PostgreSQL keep one row per item in
`tenant_erasure_items` (a schedule, a run, an execution: its ids, where it was found, its state). A Temporal call can't
complete in the same PostgreSQL transaction as a marker, so an item moves through recorded states (found, requested,
verified): each Temporal call is idempotent and retried with backoff, and an item is marked verified only after a
read-back confirms its effect. A step is marked done only once every item it owns is verified; a step with no outside
effect marks itself in the transaction that does it.

1. **Mark the tenant `erasing`,** under its lifecycle lock taken exclusively, raising its schedules' generations and
   creating the erasure's record, in one transaction. §6.5's refusals apply from then on, and every tenant-scoped
   write through the API is refused too, so nothing new (a schedule, an endpoint) appears mid-erasure; the schedule
   sync only ever pauses or deletes a tenant's schedules once it isn't `active`. The exclusive lock waits for every
   in-flight writer ("Fencing in-flight work" below).
2. **Reconcile** every `starting` request, started or confirmed absent (§7.6), each verified by the reconciler's
   recorded outcome.
3. **Its Temporal schedules,** in three recorded parts:
   1. each paused, verified by a describe that shows it paused; from then on it starts nothing, and the time the last
      one was verified paused is recorded;
   2. **the firing inventory, captured before any schedule is deleted:** every firing Dewpoint recorded (from 2b-4a,
      each `ScheduleTick` records its own workflow and run ids as its first act, a skip included), every firing the
      schedule's describe still lists (running and recent), and every execution visibility finds started by the
      schedule, each an item for step 6;
   3. each deleted, verified by a describe that finds nothing. A schedule's action carries only the schedule's id (its
      input is in Dewpoint's `schedules` row, which the sweep deletes), but a paused schedule still holds the tenant's
      spec and identifiers in Temporal and could be unpaused, so deleting extends §6.5's "pause" (revision 10).

   The inventory isn't claimed complete: a firing that never ran its first activity left no record, and visibility
   may lag. Completeness comes from step 9's bound, not from the inventory.
4. **Cancel** its queued requests and its pending events, their counters released.
5. **Cancel its running runs:** each verified terminal, in Dewpoint's projection and by a describe of its execution
   that finds it closed. Their workers need the tenant's keys until then.
6. **Delete every execution of the tenant** (D3b, the owner's ruling): "Enumerating and deleting executions" below.
7. **Delete its keys:** every data-key version and every event keypair. Nothing after step 6 needs a key, so this is
   last among the operations that need them, and every remaining ciphertext of the tenant is unreadable from then on,
   whatever the sweep's progress.
8. **The erasure sweep** (the retention role, which holds `DELETE` on these tables) deletes, in committed batches, every
   row of the tenant in: `runs`, `run_steps`, `step_outputs`, `run_inputs`, `run_secret_index`, `claim_grants`;
   `run_requests` (every status), `run_slots`, `tenant_run_limits`; `csv_uploads`, `csv_mappings`, `schedules`;
   `webhook_endpoints`, `trigger_bindings`, `inbound_events`, `tenant_event_counters`; `workflows`, `workflow_versions`,
   `connections`; `memberships`; `tenant_retention` (`data_keys` and `tenant_event_keys` went in step 7). Users aren't
   tenant data: a user keeps their account and loses the membership. The `tenants` row stays, so its id is never reused
   and its audit chain still resolves: status `erased` (a migration widens the `tenants_status` check, which admits only
   `active` and `erasing` today), its name replaced by a fixed placeholder, and its slug by a unique anonymized one
   built from its id (`erased-<tenant id>`), since slugs are unique.
9. **Wait out Temporal's retention bound:** "Why every execution is gone" below.

**Only `active` is eligible.** Admission and the `ScheduleTick` activity refuse `status == "erasing"` today
(`apps/admission.py`, `apps/dispatcher/tick.py`); with `erased` added they must require `status == "active"`, as
dispatch, the matcher and ingress's two functions already do, so a retained `erased` row never becomes eligible again.
A regression covers each of those checks against `erased`.

**Fencing in-flight work.** A check made before step 1 mustn't let a write land after it. The rule: every writer of
tenant data takes the tenant's lifecycle lock shared and checks `active` in the same transaction as its write, and a
writer whose effect is outside PostgreSQL holds that transaction open across the outside call. Step 1's exclusive lock
then waits for every writer that read `active` to commit or roll back, and every writer after it reads `erasing`.
- **Already fenced:** dispatch's `starting` transaction, the matcher, the recount, an event's cancel, and ingress's
  recording function.
- **To fence:**
  - admission, in the transaction that inserts a request;
  - the `ScheduleTick` activity, in the transaction that would insert its request;
  - a run's cancel;
  - the API's tenant-scoped writes, through the one dependency that authorizes them (`require()` in `core/http.py`):
    it takes the lock shared in the request's transaction and refuses a non-active tenant for every permission that
    writes (the prototype verifies the request's transaction spans the write and its commit);
  - the CLI's per-tenant key commands (`keys rotate-dek` for a tenant, `keys ensure-tenants`), so a key can't be
    created after step 7;
  - **the schedule sync:** today `sync_one` reads the row's wanted state in one transaction and calls Temporal's create
    or update after that transaction has ended, so a sync that read `active` before step 1 could create a schedule
    after step 3's last pause. It now holds the transaction, with the tenant's lock shared, from its read through its
    Temporal write (each call bounded by its 10 s deadline), so step 1 waits for it to finish. Once a tenant isn't
    `active`, the sync only pauses and deletes.
- **What a lock can't fence: a late Temporal write.** A request Temporal received before its client's deadline could
  take effect after the call returned, and no server-side bound says when Temporal applies or abandons it; waiting
  another deadline proves nothing. So the outline doesn't time it out. It makes a late write unable to fire, and
  reconciles what it can still leave, after completion too ("Late Temporal writes" below).
- **Regressions,** each in both orders:
  - a sync holding its read of `active` while step 1 waits: its create lands first, then step 3 pauses and deletes the
    schedule; started after step 1, it only pauses or deletes;
  - an API write holding its check of `active` while step 1 waits: it commits first and the sweep deletes its row;
    started after step 1, it's refused;
  - admission and a tick against step 1 likewise;
  - final absence: once the sweep has run, no writer can insert a row of the tenant;
  - a late create, simulated by creating the schedule after step 3 has deleted it: it lands paused and fires nothing,
    a stale unpause sent after it is discarded, and reconciliation deletes the schedule, alerting and reopening the
    erasure's record for it, after completion too.

### Late Temporal writes

- **Schedules are created paused** (a change to 2b-3a's sync): the sync creates every schedule paused, and only an
  update carrying the schedule's conflict token unpauses it. Step 3's verified pause changes the token, and Temporal
  discards an update whose token is stale (2b-3a's contract test), so a late unpause is discarded and a late create
  lands paused: nothing of the tenant fires after the last verified pause, whatever a late request does, and step 9's
  latest close holds. **That protection is relied on only once the prototype's test passes:** a token taken from a
  deleted schedule must never match a recreated one, and the discard and paused creation must hold on the CLI dev
  server and on D12's target. If it fails, paused creation doesn't protect the firing bound, and the bound stays
  unproven, completion blocked, until another design does.
- **A firing due between paused creation and the unpause is missed (D3f, the owner's ruling):** recorded and surfaced
  as a missed firing, never hidden by shifting the user's schedule start. The prototype establishes how to count those
  firings (Temporal doesn't count a paused schedule's firings as missed) and how they reach the schedule's missed count
  and its alert.
- **A run start in flight before step 1** (2b-2 starts after its `starting` transaction commits) could land late too.
  Its workflow id is its request's id, so it's a known id; such a run can't decrypt its input once the keys are gone,
  and the reconciler below terminates and deletes it.
- **Reconciliation after completion.** The erased tenant's known Temporal ids (its schedules', its requests'
  deterministic workflow ids, every execution step 6 enumerated) stay on a durable list with the erasure's record,
  identifiers only. The retention process describes every one on each pass, indefinitely. A schedule found is deleted
  after its listed firings are added to the list; an execution found is terminated and deleted; each is an incident,
  audited and alerted on, and reopens the erasure's record for it, so its firings get their own bound and final check.
- **What reconciliation can and can't do.** It detects and repairs a late schedule or execution on its next pass; it
  can't keep absence continuously true between passes, and no describe establishes that a write won't arrive later. So
  the final check proves absence only at the moment it runs. **The residual risk:** a late write landing after it
  leaves a tenant schedule (paused) or execution in Temporal until the next pass finds it, and, should paused creation
  ever fail to hold, a firing in between; each is an incident that reopens the erasure's record, as above.

### Enumerating and deleting executions (step 6)

Every execution Dewpoint starts for a tenant has a server-built workflow id beginning `t:<tenant>:` (§6.1): a root, a
sub-flow or a failure handler (`…:run:<run id>`), a loop batch (`…/batch:<start>`), a schedule tick
(`…:sched:<schedule id>-<suffix>`). A continue-as-new chain keeps its workflow id, each run with its own run id.

- **Enumerate durably, before deleting anything.** Every run of the tenant in `runs`, and every request step 2
  reconciled as started, gives a workflow id. Each one's whole run chain is walked through its histories, reads of the
  execution store, not of visibility: a run's start event names the run it continued from, its continue-as-new event
  the run that continues it. Every child those histories started (sub-flows, loop batches) is added and walked the
  same way, recursively. Step 3's firing inventory adds the schedule ticks. Visibility queries for workflow ids
  beginning `t:<tenant>:` add anything not yet listed, which is then walked too. Each item is recorded (workflow id,
  run id, where it was found) before it's deleted, so a crash resumes from the list.
- **Delete, then read back.** `DeleteWorkflowExecution` for each listed run; verified only when describing that exact
  run (workflow id and run id) answers not-found, a read of the execution store. Temporal deletes asynchronously, so a
  run still present is retried later, not failed. The step is done once every listed item is verified gone; that
  removes everything found at once, but proves nothing about what wasn't found.

### Why every execution is gone (step 9)

No Temporal API outside visibility enumerates a namespace's executions, and visibility has no guaranteed maximum lag,
so no number of visibility passes proves every id was found, schedule firings least of all. Completeness rests instead
on Temporal's own retention, which deletes every closed execution once the namespace's retention has passed since it
closed, found or not:
- **Every execution of the tenant is closed by a known time.** Runs were verified terminal in step 5, and their
  children close with them (the prototype verifies each child kind's parent-close policy; a child that would outlive
  its parent is cancelled and waited for in step 5). Every firing ends within the workflow execution timeout set on its
  schedule's action (the prototype verifies 2b-3a sets one, or adds it), and nothing fires after step 3's last pause.
  So the latest close is at most the later of step 5's verified ends and the last pause plus that timeout.
- **The bound:** that latest close plus the platform's maximum namespace retention (30 days, §10.2). A poll, at the
  start, the end or on every pass, can miss a temporary increase, and Temporal's API offers no namespace version to
  prove there was none (`DescribeNamespace` reports the retention and archival configuration, and `failover_version`
  isn't a configuration version). So the cap needs an actual namespace-change boundary:
  - **A production Temporal target qualifies only if every namespace-change path mechanically rejects a retention
    above 30 days and records every change in an independently reviewable audit trail** (D3g, the owner's ruling).
    Access control plus an audit log isn't enough while an authorized user can still set 31 days: such a target is
    unsupported unless it provides an equivalent enforced cap. An authorizer on a self-hosted frontend that refuses
    such a change and logs its decisions is a candidate to prove, not an assumed solution: D12's proof must show it
    rejecting the change on every namespace-change path of the real target.
  - **Readiness fails closed without it:** `enable-production-runs` and ingress's own switch both refuse a target whose
    boundary hasn't been verified, so production is never enabled on a deployment where erasures couldn't complete.
    Each records the verified boundary; an erasure records the boundary it relied on.
  - **If a verified boundary is later lost** (the deployment changes), the bound is unproven again: an erasure relying
    on it can't complete and stays `erasing`, alerting.
  - Archival must be disabled for the namespace (D12), so no copy outlives retention.
- **The bound is the earliest point to attempt the final check, not a completion deadline.** Then every found
  execution is read back not-found again, every schedule the tenant had is described absent, and a visibility query for
  `t:<tenant>:` finds nothing. Anything found keeps the erasure incomplete and alerting, never reporting success.
- **The trust boundary (D3d, accepted by the owner):** for executions Dewpoint can't enumerate, the bound relies on
  Temporal enforcing its namespace's retention, which Dewpoint can't observe for an execution it never found.
- **So an erasure can't complete before the bound** (at least 30 days after the latest close): its record shows
  Dewpoint's own data and keys gone, every found execution deleted, and the date the final check may first run.
- **What this asks of the production Temporal:** `DeleteWorkflowExecution`, visibility queries by workflow-id prefix,
  `DescribeNamespace`'s retention, and archival disabled for the namespace. The readiness checks verify the last
  (D12). The prototype measures each on the CLI dev server; D12's proof covers the real target.

**Complete** — status `erased`, with an audit entry of per-table counts — only once steps 1 to 9 are done and a final
check finds, for the tenant: no row in step 8's tables, no key, no Temporal schedule, every found execution verified
gone, and step 9's bound passed with nothing found. The completing transaction then deletes the erasure's item rows, its
audit entry keeping their counts; `tenant_erasures` stays as the erasure's record, identifiers only. Until then the
tenant stays `erasing` and the erasure's record shows the step reached and any failure; nothing reports it complete
early.

**A stopped or failed step resumes.** The retention process takes every `erasing` tenant an operator hasn't stopped
and retries its recorded step and its unverified items, with backoff and an alert, never skipping either; batches
commit their progress, so a crash resumes where it stopped. An operator's retry clears a stop. A run whose execution
answers not-found while its projection isn't terminal goes through §7.9's operator recovery path, audited.

**What remains (D3c, the owner's ruling):**
- **Audit records:** the tenant's audit entries stay under the platform's audit-retention policy
  (`audit_retention_days`, 400 by default) and its integrity anchors, leaving by audit pruning, not by erasure. They
  never hold a run's inputs or outputs or an event's payload, and the audit service refuses detail keys naming a
  password, a secret, a token, a code or a credential. But they aren't identifier-only. Today's entries keep:
  - **identifiers:** actors' user ids, and the ids of workflows, versions, requests, runs, endpoints, bindings, events
    and schedules;
  - **tenant-supplied names and labels:** the tenant's slug (`tenant.create`) and the fields an update sent
    (`tenant.update`), a workflow's name (`workflow.create`, `workflow.update`), a connection's name and type
    (`connection.create`), a webhook endpoint's name (`webhook_endpoint.create`);
  - **operational metadata:** the names of changed fields, counts, fixed reasons and outcomes, booleans, a published
    version's number, its graph and version hashes and its declassified pointers;
  - **personal data, platform-level** (no tenant): a failed login's email and IP address, a login's IP address.

  So an erased tenant's names and labels stay in its audit records for the audit-retention period, as do its
  identifiers. Erasure's own entries (its start, each step, a stop, a retry, its completion) hold identifiers and
  counts only.
- **Backups:** a backup taken before completion still holds the tenant's rows and its wrapped data keys, restorable by
  whoever holds the KEK. The erasure is complete in backups only once every such backup has expired (the guide
  recommends at most 35 days); the completion entry states that date.
- **Logs:** they name ids, never values; the operator's log retention applies.

## Production Temporal (D12)

- **Configuration (§10.4):** verified TLS always, the server's certificate checked against a configured CA or the
  system roots; client authentication by mTLS (`DEWPOINT_TEMPORAL_TLS_CERT`, `…_KEY`, `…_CA`) or an API key over that
  TLS; `DEWPOINT_TEMPORAL_INSECURE_DEV` only in a development deployment, refused by every process otherwise and warned
  about when used.
- **What the CLI dev server can show:** configuration parsing and the refusal paths, not that a real TLS, mTLS or
  API-key connection works.
- **So readiness needs a real verified-TLS proof:** an integration proof against a real TLS-serving Temporal, for each
  supported auth mode, before the readiness checks may pass; and `enable-production-runs` itself connects with the
  deployment's own settings, verifies the certificate, and calls `DescribeNamespace` (the recorded namespace, its
  retention within bounds), failing closed otherwise. The proof's target (a Temporal Cloud test namespace, a self-hosted
  server with TLS, or another) and any image it needs approved are the owner's decisions (D12).
- **What erasure needs of it** (D3b): `DeleteWorkflowExecution`, visibility queries by workflow-id prefix,
  `DescribeNamespace`'s retention and archival state, archival disabled for the namespace (which the readiness checks
  verify), and a verified namespace-change boundary: every path mechanically rejects a retention above 30 days, and
  every change is recorded in an independently reviewable audit trail (D3g). Without it, both readiness paths fail
  closed.

## Ingress in production (D14)

- **Its own audited switch** (off by default; enabled and disabled by a platform admin, the operator recorded, D11)
  governs ingress's first activation in production, after its own readiness: retention sweeping, the event keypairs'
  rotation in place, the scaling change (D9) in, the Mist decision (D13) reflected in the guide, the production Temporal
  proof passed, and the namespace-change boundary verified (D3g); without the last two it fails closed, as the runs
  gate does.
- **Independent of the runs gate once on:** turning the runs gate off keeps §2.5's durable-source behavior: ingress
  still records webhook events, and the matcher waits until the gate is on again. Turning ingress's switch off stops
  recording (503 `unavailable`), pending events kept for matching.
- **In a development deployment,** unchanged: ingress records, and the gate is skipped.
- Nothing lifts by this review.

## D6 and D12: concrete, testable choices

Brought back before any prototype, as the owner asked (2026-10-05). Each fact below was checked on the date given; what
couldn't be checked says so. **The owner's ruling (2026-10-05): D6 and D12 are approved as proof candidates, not as
proven production boundaries.** Approved for the proofs: `cgr.dev/chainguard/minio` (D6's test), `boto3` with its
`botocore` dependency (not a hand-written SigV4 client), and `golang`, `temporalio/admin-tools` and a minimal runtime
base (D12's proof); each image pinned when its proof is specified. None of this authorizes a prototype, a detailed
plan or either production gate's lift.

### D6: the off-host audit anchor sink (#3)

- **Proposed production target:** an S3 bucket with Object Lock in compliance mode. In compliance mode "a protected
  object version can't be overwritten or deleted by any user, including the root user", and its retention can't be
  shortened (AWS's Object Lock documentation, checked 2026-10-05). Another S3-compatible store qualifies only once the
  same proof shows the same behaviour.
  - **Layout:** one object per anchor, a key per scope and sequence, never reused; the bucket's default retention, in
    compliance mode, covering the configured audit-retention period plus the configured backup period (checked
    against the settings in force, not only today's defaults of 400 and 35 days); a bucket policy bounding retention
    with `s3:object-lock-remaining-retention-days`.
  - **Writer:** the anchor service's own put-only credentials, held apart from the database host's.
  - **Signing:** each anchor signed with an Ed25519 key the anchor service holds, not on the database host; verifying
    needs only the public keys (every key id kept, for rotation).
  - **Verifying reads versions:** a plain `DELETE` only adds a delete marker and a rewrite adds a version, so `dewpoint
    audit verify` against the bucket lists object versions and fails on a delete marker, a second version of a key, a
    bad signature, a hash mismatch, a chain break or a missing anchor.
  - **Monitoring outside Dewpoint's database:** a scheduled job, not on the database host, runs that verify and checks
    each scope's last anchor age, alerting on failure.
  - **Runbook:** a failed verify; rotating the signing key.
- **Anchor completeness (the owner's acceptance condition).** Object Lock protects a version, not the existence of the
  next anchor: a compromised database could erase a scope or suppress its next anchor without leaving an S3 version
  to find. So the expected scope roster and each scope's anchor cadence and high-water mark are kept off the database
  host, with the independent monitor, which alerts on a missing scope and on an overdue anchor. Verify reads every
  listed version and delete marker, across every page of the listing, and checks each version's retention mode
  (compliance) and its retain-until date.
- **The proof:** against an S3-compatible test server with compliance-mode Object Lock: deleting a locked version
  (by version id, with the server's root credentials) is refused, shortening its retention is refused, a delete
  marker and a rewrite are both caught by verify, and verify fails on each tampering case above; the monitor alerts on
  a scope removed from the database and on an anchor withheld past its cadence; a listing longer than one page is
  verified whole. At readiness, the real bucket gets the same check with a canary anchor.
- **Image to approve (test only):** `cgr.dev/chainguard/minio`. MinIO stopped publishing its own community images on
  2025-10-23 (source only since); Chainguard publishes a free image built from MinIO's source. Whether its Object Lock
  enforces compliance mode as above is what the proof establishes; if not, the fallback is building MinIO from source
  (a `golang` image to approve).
- **Dependency to approve:** an S3 client (`boto3` and `botocore`), Dewpoint's first; or a small SigV4 client of our
  own over the existing HTTP client, more code to own.
- **Not proposed:** a syslog or SIEM target (its immutability is the SIEM's, not mechanical by default), and other
  clouds' immutable storage (each would need its own client and proof).

### D12: the real Temporal target

- **Temporal Cloud doesn't qualify under D3g as documented.** A namespace's retention can be set anywhere from 1 to 90
  days (Temporal Cloud's namespace documentation, checked 2026-10-05), so an authorized user can set 31. Its audit logs
  do record `UpdateNamespace`, but access control plus an audit log isn't an enforced cap. It stays unsupported unless
  Temporal provides an enforced account-level cap, which its documentation doesn't show.
- **Self-hosted Temporal with a custom authorizer: the candidate to prove.**
  - **What exists (checked in Temporal's source, 2026-10-05):** `validateRetentionDuration` in the frontend's namespace
    handler checks only a minimum retention on `RegisterNamespace` and `UpdateNamespace`; there's no maximum and no
    setting for one. The server's `Authorizer` receives a `CallTarget` with `APIName`, `Namespace` and `Request`, "a
    deserialized copy of the API request object", so an authorizer can read the requested retention.
  - **What we'd build:** a small Go module running Temporal's server as a library with our authorizer and the JWT claim
    mapper, pinned to the server version Dewpoint targets (v1.32.0 is the latest release; CI's CLI dev server 1.9.1
    runs server 1.32.0). The authorizer refuses `RegisterNamespace` or `UpdateNamespace` with a retention above 30
    days, refuses any other API that can change a namespace's configuration (an allowlist, denying by default), and
    records every namespace-changing decision, allowed or refused, in an independent audit trail: D6's bucket. **It
    fails closed:** a namespace change whose audit record can't be written is refused (the owner's acceptance
    condition).
  - **The change paths the proof must cover (the owner's acceptance condition):** the SDK, the `temporal operator
    namespace` CLI, every OperatorService and AdminService API (enumerated from the server's own definitions), and any
    separately exposed administrative endpoint, each shown unable to set a retention of 31 days; plus the audit write
    failing, which must refuse the change.
  - **The persistence store's administrator (D12b, the owner's ruling):** privileged Temporal database administrators
    are inside the trusted platform-operator boundary, as Dewpoint's own database superuser is, not a path the API
    authorizer controls. Their access must be restricted and independently audited; a deployment that can't maintain
    that boundary doesn't qualify.
  - **The verified-TLS proof, in the same environment:** the server's certificate from a test CA, verified (a wrong CA
    refused); then, separately, since requiring a client certificate globally wouldn't prove the alternative (the
    owner's acceptance condition): **mTLS only** (a client without a certificate refused), and **a bearer token only**
    over verified TLS, without a client certificate (valid accepted, invalid or expired refused); plus
    `DescribeNamespace`'s retention and archival state, `DeleteWorkflowExecution`, visibility queries by workflow-id
    prefix on PostgreSQL visibility, and D3's deleted-and-recreated schedule token test and paused creation.
  - **Naming:** on a self-hosted server the token is a JWT bearer token, validated by the server's JWT claim mapper
    against a key set, named as such in the settings and the guide; it isn't a Temporal Cloud API key. Revision 10
    says which of §10.4's settings each target uses.
  - **Images to approve (proof environment):** `golang` (to build our server), `temporalio/admin-tools` (schema setup)
    and a minimal runtime base for our server image (a distroless static image or `alpine`); `postgres:16-alpine` is
    already approved. Exact tags pinned at the prototype.
  - **Production:** the owner's own deployment of that server, the proof rerun there before readiness.
- **Ruled:** the self-hosted authorizer is the candidate to prove; Temporal Cloud remains unsupported under D3g as
  documented (retention settable from 1 to 90 days; its audit log records changes but doesn't enforce a 30-day cap).

## Milestones (first cut)

**2b-4a, the data lifecycle**
- **M1. The schema blockers and the event-grouping contract:** #28 and #35, each with its migration and regression;
  `events_pointer` fixed at an endpoint's creation (D10), the API refusing it in a PATCH and the API's role losing its
  `UPDATE` grant, each boundary tested.
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
- **M4. Tenant erasure:** "Tenant erasure" above: its record and items, steps 1 to 9 (the firing inventory, the
  executions' enumeration and read-back, the retention bound), ticks recording their own firings, the `tenants`
  migration (`erased`, anonymized slugs), eligibility requiring `active`, fencing every in-flight writer (the schedule
  sync's transaction spanning its Temporal write included) with its race regressions, schedules created paused,
  missed firings counted, the deleted-and-recreated token test, reconciliation after completion, the namespace-change
  boundary recorded, completion and its final check, stopping and retrying, its command and audit, and a proof that
  afterwards nothing of the tenant stays decodable, and nothing stays stored beyond the agreed exceptions: its audit
  records under the platform's audit-retention policy, and backups until they expire.

**2b-4b, production hardening and the gate lift**
- **M1. The engine blockers:** #16, #18 and #26, each fixed or bounded (D7).
- **M2. §7.9's hardening:** as the ledger below rules, item by item, the dispatcher-scaling change and its measurement
  included.
- **M3. Production Temporal and audit integrity:** "Production Temporal" above, its real verified-TLS proof included;
  #3's off-host anchors.
- **M4. Readiness and the gate:** the readiness checks, `enable-production-runs` with the operator's attestation, the
  disable command naming its operator, ingress's own switch (D14), both readiness paths failing closed without the
  production Temporal proof and a verified namespace-change boundary (D3g). Then the gate-lift checkpoint: the owner
  rules with every blocker's evidence in front of them. Lifting the gate on a real deployment is the owner's act, not a
  plan task.

## Decision ledger

| # | Decision | Proposal |
|---|---|---|
| D1 | The split | 2b-4a then 2b-4b, as above; one outline, two plans, two prototypes. |
| D2 | Order inside 2b-4a | **Accepted (2026-10-05):** #28 and #35 first, then retention, then re-encryption and retirement, then erasure, which needs the others. |
| D3 | Tenant erasure | As "Tenant erasure" above, with the owner's rulings: (a) no abort once `erasing` is committed, only a stop or a retry; (b) every found execution deleted and read back, the firing inventory captured before schedules are deleted, and completeness from Temporal's retention bound, never from visibility; (c) audit entries under the platform's audit-retention policy, described as they are; (d) Temporal's retention enforcement accepted as the trust boundary for executions Dewpoint can't enumerate, the bound being the earliest point for the final check, not a deadline; (e) in-flight writers fenced by the lifecycle lock, the schedule sync's transaction spanning its Temporal write; late Temporal writes made unable to fire (schedules created paused, unpaused only by a token-carrying update, relied on only once the deleted-and-recreated token test passes) and detected and repaired after completion, the residual risk between passes stated; (f) a firing due between paused creation and the unpause recorded as missed, the user's start never shifted; (g) a production Temporal target qualifies only if every namespace-change path mechanically rejects a retention above 30 days and records changes in an independently reviewable audit trail; a self-hosted authorizer is a candidate to prove; access control plus an audit log alone is unsupported; both readiness paths fail closed without a verified boundary. |
| D4 | The read cutoff | **Accepted (2026-10-05):** filter in the shared read paths (one query helper per kind), proven by a test per user-facing path; never a database view the API could bypass. |
| D5 | Audit pruning and #3 | **Accepted (2026-10-05):** pruning ships in 2b-4a disabled in production until #3's sink is configured; the readiness checks refuse a production gate without it. |
| D6 | #3's first sink | **Approved as a proof candidate (2026-10-05):** an S3 bucket with compliance-mode Object Lock, with anchor completeness off the database host; `cgr.dev/chainguard/minio` and `boto3` approved. |
| D7 | #16, #18, #26 | Fix each, per the issues' preferred directions: #16 bounds the snapshot (or ends the run with a fixed code before the limit); #18 bounds measuring's cost; #26 sends a shared value once, as a size claim. Bounds instead of fixes need the owner's risk decision, case by case. |
| D8 | §7.9's items | See below. |
| D9 | Dispatcher scaling | Required before production. Measure first on the CLI dev server (approved image), then choose: `SKIP LOCKED` on the endpoint row, or dispatchers taking disjoint candidates. Rerun the load probe's separate-tenant control after the change; §8.3's fairness and races are re-proven. |
| D10 | 2b-3b's deferred ingress minors | (1) the matcher's endless retry: with §7.9's bounded retry and alerting (2b-4b M2); (2) the guide's warning about an empty `DEWPOINT_INGRESS_TRUSTED_PROXIES` behind a proxy: a doc fix (2b-4b M4); (3) changing `events_pointer` after deliveries changes deduplication: it becomes fixed at creation, like the id source, and a different grouping needs a new endpoint (2b-4a M1); an intentional contract change in revision 10 (§8.3), tested at the API and the database role; (4) the recording function not checking a blob's embedded key version: an added predicate (2b-4a M3). |
| D11 | The operator's identity | `enable-` and `disable-production-runs` record the operator: an admin login (an identity the platform knows) rather than the OS user. The mechanism is the owner's choice. |
| D12 | Production Temporal | **Approved as a proof candidate (2026-10-05):** self-hosted Temporal with a fail-closed custom authorizer, every change path proven; mTLS-only and bearer-token-only proven separately; D12b ruled (database administrators inside the operator boundary, restricted and audited); Temporal Cloud unsupported as documented; `golang`, `temporalio/admin-tools` and a minimal runtime base approved. |
| D13 | Mist webhooks | Supported in production only if a real Mist delivery confirms the bearer-header path. Otherwise the guide says Mist webhooks are unsupported in production: Mist signs the body alone, without a timestamp, so the timestamped HMAC scheme is no substitute for it. |
| D14 | Ingress in production | As "Ingress in production" above: its own audited switch for first activation; the runs gate turning off keeps recording events (§2.5). |

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
- *Mist's bearer token:* D13 (unsupported in production unless a real delivery confirms it).
- *The Compose proofs:* the run, the schedule and the webhook have passed in CI; they stay required on every PR.

## Open and separate

- **The gitleaks PR range:** CI's security job still uses `gitleaks/gitleaks-action` v2. Its fix (scanning a PR's
  whole `base..head` range with a pinned gitleaks) was never committed; its branch holds no commits of its own. #37's
  scan covered all 14 of its commits, but a PR past the action's first 30 commits would go partly unscanned. A small
  change of its own, not a 2b-4 dependency.
- **The dispatcher backoff test's clock skew:** a separate session is fixing it.
- **#2** (the signed release path), and the parent spec's later sub-projects (Mist integration; the UI's run form, CSV
  mapping screen and runs view).
