# Dewpoint — Engine 2b Design (payload protection, admission, triggers, retention)

- **Status:** approved by the owner, revision 4 (2026-09-30). Every section was approved in conversation before it was
  written here; this document is their written form.
  - Revision 2 folds in the owner's review of revision 1: a claim is owned by the run that produced it, with the
    root run id kept for retention and the secret index (§3.4); passing a secret-index bound is a fixed,
    non-retryable error, and matching work is bounded (§3.7); an idempotency retry is compared under its stored
    digest-key version (§7.2); the root's `runs` row is still written before the start (§7.3); `admit_request` runs
    inside its caller's transaction (§7.2, §8.3); the numbers are provisional until measured (§15).
  - From the owner's review of revision 2: every transition out of `starting` releases or keeps the slot and makes
    the pre-created `runs` row terminal as §7.8 specifies; the reconciler confirms a `starting` request whose
    execution exists (even closed) without overwriting a terminal row or recreating a slot; `runs.started_at`
    becomes nullable (§14); a leaked slot is released only when the logical run's latest execution is terminal
    (§7.6).
  - Revision 3 records the go/no-go results (§11.1): codec context and schedule time passed; the SDK checks size
    after the codec; a task's completion over the gRPC limit gets the workflow terminated, so the per-task byte
    budget is a hard invariant (§5.2); an operator's termination stays `terminated` (§7.6); Dewpoint never uses a
    schedule's trigger-now (§8.2). Structure dominates wide loop bodies, so §5.3 proposes an index-based snapshot
    format, a rebuilt ready queue and an open-iteration cap with a reservation for one dependency chain (bounded by
    `OPEN_SCOPES_CAP + D`), provisional until its own dev-server go/no-go, with parallel sibling loops, before
    2b-1b.
  - Revision 3 also renumbers 2b's ABIs: issue #15's fix takes `ENGINE_ABI` 4, so 2b-1a raises it to 5 and 2b-1b to 6
    (§1, §6.6, §12, §13), provided #15 lands first.
  - Revision 4 folds in the owner's decisions for 2b-1a's plan, and what its prototype settled. Spilling moves to
    2b-1b with the claims it needs (§1): until then a payload too large to send fails with a fixed, bounded error and
    is never sent, a batch is cut by bytes and an item that can't fit fails its loop, and results are guarded where
    they're produced, as well as commands before they're sent (§5.2). 2b-1a promises only a clean
    `snapshot_too_large` for continue-as-new (§5.3). The environment is recorded by `dewpoint platform
    init-environment`, in Compose's migrate step (§2.1). A worker's self-check is its KEK's, and a database outage
    isn't a failed check (§2.7). The tenant cross-check is made where the payload is used (§6.1, §6.2). A local
    activity's bookkeeping is visible (§4.6). The committed checks of §11.1 are named.
  - Revision 4 also answers the owner's review of the 2b-1a plan. The sensitive values a run carries are bounded,
    so every result without outputs fits, and every final result is checked before it's recorded (§5.2). A worker's
    self-check proves what `payload_codec` needs of the instance — its KEK, and its role's access to data keys — and
    tells a missing grant from an outage; lifting the gate additionally requires every stored key to unwrap, and the
    workers' own path to read each tenant's key (§2.7, §10.6). A key version is retired only after a conservative
    floor that bounds its last use for payloads,
    since nothing records that use (§6.4). Size claims start with 2b-1b (§5.1).
  - From the owner's rulings on 2b-1a's final review: an expired key is never used, even while the database doesn't
    answer, so the rotation and retirement bounds stay exact and a long database outage fails the payloads that need
    the key (§2.7, §6.3); `dewpoint keys ensure-tenants` runs as the key admin, which lists tenants under row-level
    security (§6.3).
  - Revision 5 records the 2b-1b go/no-go probe in §11.2, approved by the owner as an experiment record: promising,
    not yet a go. It lists the measured passes, five design additions, and the conditions still to be proven, with
    two counterexamples: a near-limit trigger, and loops waiting on the cap. It also revises §5.3, approved by the
    owner as the provisional design for the focused prototype. The §5.3 go/no-go stays open until the follow-up
    proves the bounds. The bound applies to the whole continued input.
    - Each component has an accounting rule and a worst-case maximum: the envelope (from the exact id grammar of
      §6.1), the trigger (§3.5 bounds its envelope), learned sensitive values, the structure, and the live values.
    - The live-state budget is fixed. Each version's open-scope cap is derived so that the whole fits, and pinned in
      the version.
    - A continued batch carries each value once: it drops its original items, outer scopes and variables.
    - A handle is bounded (§3.2): a longer pointer derives a new claim.
    - Queued loop steps share the execution's one budget request, so the budget's waiting needs have a maximum.
    - A loop step inside an iteration starts only when its loop can open an iteration, or when its budget is refused.
      It reads the variables as they were when it became ready, captured as a shared version number.
  - Revision 5 also records the §5.3 follow-up in §11.3: promising, not yet a go (the owner's ruling). Its checks
    passed on every workload; the at-continue budget term is accepted in principle, once enforced as an invariant,
    and a workflow task's CPU at the structural maximum blocks the gate until it's bounded.
  - From the owner's ruling on the conditions (2026-10-01): the at-continue budget term is approved and §5.3 counts
    only the budget's fixed counters in a continued input, with both checks kept; the CPU work is promising, but the
    gate stays open until the heaviest case runs on the target Linux CI runner, the long runs complete and replay,
    and the `UnhandledCommand` is explained (§11.3).
  - **The owner's decision (2026-10-01): go for the focused §5.3 gate (§11.3).** Revision 5's §5.3 is approved for
    implementation by the 2b-1b plan, not as production-ready: the plan turns the prototype's guarantees into
    regression tests and completes what the prototype didn't. The unpinned-run fix (#22, #23) is separate.
  - Revision 6 (draft, for the owner's approval with the 2b-1b plan), from the owner's reviews of the 2b-1b
    prototype's milestone 5: the log lines the worker controls hold only text proven to be code, which replaces
    redaction by field name, and nothing is promised for a plugin's own `logging` or `print`; a plugin's failure shows
    its code and message only when they're constants of its code; a secret a plugin makes and leaks before it's
    claimed is a canary of its own (§3.7, §6.7, §12).
- **Parent specs:**
  - `2026-09-24-dewpoint-architecture-design.md` (§5, §6.1, §6.5, §6.8, §12, §15). This spec **changes** its
    workflow-id contract (§6.1), replaces its `outbox` table (§6.1), details its claim check (§6.5) and settles the
    §15 defaults it leaves open (§13 below).
  - `2026-09-25-engine-core-design.md`, revision 5.6. This spec lifts its "hard rule until 2b ships" (§1), and
    extends its §4.5 (dispatch), §8 (codes, read paths) and §9 (starting runs) (§13 below).
- **Scope:** everything that lets Dewpoint start runs in production from real triggers, with real data kept out of
  Temporal: payload protection, admission, triggers and retention. **2b owns the backend contracts** of the run form,
  the CSV mapping step and the runs view; sub-project 4 builds those screens. Connections, credentials and
  `ctx.http` stay in sub-project 3.
- **Not in scope:** issue #15 (a `cel.evaluate` request over Temporal's payload limit) is fixed by its own small
  change **before** 2b-1a, and is one of the production gate's conditions (§2). A codec server for Temporal's Web UI
  (§6.9). Keeping original CSV files (§8.1). Per-tenant rollout of production runs (§2.6).

## 1. Plans and order

1. **#15's request-size guard**, as its own change.
2. **2b-1a — codec, ids and size:** the deployment environment and the production gate (off), enforced at the
   existing start boundary; server-built workflow ids; `TenantCodec` and its key cache; worker capability
   registration; the outgoing-payload guard, without spilling (§5.2); the per-task byte budget. `ENGINE_ABI` 5.
3. **2b-1b — claims and taint:** the claim tables, handles and grants, the activity boundary, the secret index,
   taint analysis and `declassify`, the tainted-filter activity, spilling into size claims (§5.2), the live-state
   budget and snapshots, the refusal of sensitive literals. `ENGINE_ABI` 6.
4. **2b-2 — admission:** `run_requests`, the dispatcher, slots, the reconciler, the run API and form metadata; the
   dev CLI moves onto admission.
5. **2b-3 — triggers:** CSV input, schedules, webhook ingress.
6. **2b-4 — retention and production:** retention, audit pruning, production Temporal settings, the readiness
   checks and the command that lifts the gate.

Protection comes first so admission and triggers adopt the final handle and payload contracts instead of being
retrofitted. The gate lifts only at the end of 2b-4.

**Each merged ABI has its own golden histories and replay gate.** 2b-1a records and tests the abi5 histories; 2b-1b
records and tests abi6. Neither defers the other's. **These numbers depend on issue #15's fix landing first:** it
raises `ENGINE_ABI` to 4 (`docs/superpowers/plans/2026-09-29-cel-request-size.md`). If the order changes, 2b-1a and
2b-1b take the next free numbers instead, and this spec is revised. Nothing runs in production before the gate
lifts, so publishing every workflow again after each ABI change costs only that.

## 2. Environment and the production gate

### 2.1 The deployment environment

- `dewpoint platform init-environment --environment production|development --temporal-namespace <ns>` records the
  environment once, in the single `platform_settings` row, with the Temporal namespace the deployment uses. Its
  defaults are `DEWPOINT_ENVIRONMENT` (else `production`) and `DEWPOINT_TEMPORAL_NAMESPACE`. Compose's migrate step
  runs it after the schema's migrations, so an existing deployment gets its record on its next upgrade. Running it
  again with the same values changes nothing; neither value can change, and the database refuses to (a trigger).
- **Development takes an explicit setup:** `--environment development --temporal-namespace <ns>` on a database
  created for it. Every process that talks to Temporal (the worker, the CLI's Temporal commands and, from 2b-2, the
  dispatcher) compares its configured namespace with the recorded one before it connects, and refuses to run (exit 2)
  on a mismatch or with no record, so a development database can't drive a namespace it wasn't set up for, and a
  production database can't either. The API talks to no Temporal namespace in 2b-1a; its admission path refuses runs
  while nothing is recorded.
- A `development` label proves nothing about the data. Keeping development's database and namespace apart from
  production's, with synthetic fixtures only, is the operator's documented responsibility.
- Ordinary Compose is `production`, and gated. CI and local development opt in through their own Compose override,
  which initializes `development`.
- A `development` deployment has no gate: runs start freely. Its UI and CLI say so on every screen and run.

### 2.2 The gate

- `platform_settings.production_runs`, **off by default**, is the single source of truth every process reads.
- **Enabling** (`dewpoint platform enable-production-runs`, platform admin only, 2b-4) runs the readiness checks of
  §10.6 and writes one audit entry with every result and the operator's attestation.
- **Disabling** is audited too (§2.4). Queued requests wait; started runs continue.
- While the gate is off in a `production` deployment, **no tenant starts a run**. There is no test-tenant bypass: a
  label can identify fixtures but can't prove data is synthetic, so it's never a security boundary.

### 2.3 Enforcement

- **At admission.** The shared admission path checks the gate. Interactive sources — the run API and the dev CLI —
  are refused while it's off, with `production_runs_disabled`. Durable sources — schedule ticks and webhook events —
  still record their work (§2.5).
- **At dispatch.** Immediately before `RunGraph` starts, in the transaction that marks a request `starting`, the
  dispatcher rechecks every critical condition. Any failure leaves the request queued, with a metric and an alert;
  it isn't failed or cancelled:
  - the gate is on, and the tenant isn't `erasing` (§6.8);
  - the current build's capabilities (§2.7);
  - the tenant's key is usable: the dispatcher encrypts the start payload with it, so a key that doesn't work stops
    the start;
  - retention is healthy (§10.3).

  A `development` deployment skips the gate and the retention SLO, and keeps the other checks.
- **ABI checks stay separate.** `admit` keeps its ABI rule and dispatch keeps `engine_abi_changed` (engine-core
  §4.5). The ABI identifies execution compatibility, never the presence of protection.
- **The existing start boundary is gated in 2b-1a,** not only the dev CLI: 2a's `admit`/`start_run` refuses in a
  `production` deployment while the gate is off. From 2b-2 the dev CLI enqueues through `admit_request` and the
  dispatcher. No packaged path starts a run directly at any point; `start_run` stays a test helper that no command
  exposes.

### 2.4 The gate-off race

- The dispatcher's `starting` transaction takes the transaction-scoped advisory lock `dewpoint:production-gate`
  **shared** and reads the flag under it. Disabling takes it **exclusively**. Once the disable commits, no request
  can become `starting`.
- Requests already `starting` may still reach Temporal. The disable command waits for them to settle — started, or
  back in the queue after a confirmed refusal — up to the dispatcher's start deadline.
- If the wait times out, the gate **stays off**, the command reports those starts as **unresolved**, and their
  eventual outcomes are audited when the reconciler settles them. A disable is never reported as fully settled
  while any start is unresolved.

### 2.5 Durable work while the gate is off

- Interactive starts are refused (§2.3).
- `ScheduleTick` still records its request (§8.2); ingress still accepts and records webhook events (§8.3).
- The dispatcher neither matches events nor starts requests. Queued requests, pending events and ticks wait.
- **Waiting isn't failing.** Backoff and dead-letter counters don't advance while the gate is off, or while any
  dispatch-time critical check fails. Work resumes FIFO per tenant once they hold again. Dead-lettering is only for
  failures specific to one request or event.

### 2.6 Later

Per-tenant rollout of production runs may be added later, only on top of the global gate, never in its place.

### 2.7 Worker capabilities, per instance

- Each engine worker **instance** records `(instance_id, build_id, capabilities, healthy, checked_at)` in
  `worker_instances`. The capabilities are compiled into the build: `payload_codec` (2b-1a), `cel_request_size_guard`
  (#15), `claim_check` (2b-1b).
- At startup and every 30 seconds, an instance proves what it records. For `payload_codec`: its keyring wraps and
  unwraps a fresh key with the current KEK, and its database role may read data keys (read from the catalog, so the
  answer doesn't depend on a tenant); from 2b-1b, its claim store answers. An instance that fails **stops polling**
  (running attempts get the shutdown grace), records itself unhealthy and exits (code 3); it never keeps taking
  tasks. One that can't prove itself at startup never polls.
- **A database that doesn't answer proves nothing either way:** it's an outage, which doesn't stop the instance.
  It keeps polling and records nothing, and its row goes stale; a record it can't write is logged the same way. A
  stale row isn't a live instance. Runs don't ride the outage out, though: a key that has expired from a process's
  cache can't be read until the database answers (§6.3).
- **What the check doesn't claim.** The probe checks a grant, not that the role's RLS-scoped reads return a tenant's
  key; the KEK check wraps and unwraps a fresh key, not the stored ones. A wrong KEK configured under the right id
  passes both, while no worker can decrypt existing payloads — and `dewpoint keys status` doesn't catch it either,
  since it compares KEK ids. 2b-1a keeps this lightweight check; lifting the gate requires §10.6's stored-key checks.
- The dispatcher and the readiness checks read the deployment's **current build** from Temporal and require every
  live instance of that build (`checked_at` within the last 90 seconds) to be healthy and to hold every required capability, and at
  least one to exist. One fresh healthy row can't hide another live instance that lacks the codec or key access.

## 3. Claims

A **claim** is one value stored encrypted in Postgres, under RLS. Sensitive values and large values become claims;
Temporal history holds only handles to them, never an encrypted copy (§4). The per-tenant codec (§6) is defense in
depth for what does enter history.

### 3.1 Storage

- **`run_inputs`:** claims made before a run starts — a trigger's claimed parts, 2b-3's CSV rows and their mapping.
- **`step_outputs`:** claims made during a run — plugin outputs, CEL results, spilled values and segments.
- Each row holds one value, encrypted with the keyring under the purpose `claim`, with the claim's id as context, so
  the tenant, the purpose and the id are bound to the ciphertext.
- **Authoritative metadata** on every row: the tenant; the **owner**, the run that produced the claim (§3.4); the
  **root run id** of the owner's tree, used by retention (§10.1) and the secret index (§3.7), never for
  authorization; the producer (step, iteration, attempt, for tracing); a **sensitive-pointer map** listing which
  pointers inside the value are tainted; a content hash.

### 3.2 Handles

- A handle is the internal engine type `ClaimRef(id, pointer)`, serialized under a reserved marker key. It carries
  **no taint bit** and asserts nothing: authority comes only from the stored row.
- A pointer addresses part of a claimed value: `item` over a claimed list is `ClaimRef(X, "/7")`.
- **A handle is bounded.** Its pointer is at most `POINTER_MAX` (initially 256 bytes, encoded).
  - A reference that would make a longer one instead derives a new claim of the value it addresses. That happens
    through long keys, or by extending a handle that already carries a pointer (a chain of transforms, say).
  - An activity copies that value into a claim with a deterministic id, written like any claim (idempotent and
    hash-checked), with the source row's taint for that part.
  - The reference yields the new claim's handle, with an empty pointer.
  - So a handle's encoding is at most `HANDLE_MAX`: the marker, a claim id and a `POINTER_MAX` pointer.
- **Forged handles are refused.** Data from outside never crosses into a run as a handle: admission rejects a
  trigger containing the marker, and the activity boundary rejects plugin output containing it.

### 3.3 Resolution

Every resolution happens in an activity and checks, against the stored row:
- the tenant equals the one the activity's server-built workflow id names (§6.1);
- the resolving run is the owner, or holds a grant (§3.4);
- the pointer exists;
- the taint of what's returned comes from the row's sensitive-pointer map, nested claims included.

### 3.4 Owners and grants

- **The owner is the run that produced the claim.**
  - A trigger's claims (`run_inputs`) are owned by the root run's id. In 2b-1, `admit` inserts the `runs` row
    before the run starts, and the claims are owned by that run. From 2b-2, a request's id is the id of the run it
    becomes (`run_requests.id = runs.id`, reserved when the request is frozen), and its `run_inputs` are owned by
    that id from the moment they're written — so `run_inputs` has no immediate foreign key to `runs`. The workflow
    id `t:<tenant>:run:<run_id>` names the same identity.
  - A claim made by an activity is owned by the run that scheduled it: a sub-flow's claims by the sub-flow, a
    failure handler's by the handler. `LoopBatch` shares its parent's run id, so a batch's claims belong to its run,
    and a batch resolves its run's claims directly.
- **Grants** (`claim_grants(claim_id, run_id)`) are only for handles crossing to another run:
  - **parent → child:** a sub-flow's input and a failure handler's trigger hold claims the parent owns or holds a
    grant on; the parent grants them to the child;
  - **child → parent:** a sub-flow's outputs hold claims the sub-flow owns or holds a grant on; the sub-flow grants
    them to its parent before its result returns.

  A run grants only claims it owns or holds a grant on, in an activity that completes before the handle crosses.
  Siblings and the rest of the tree get nothing.
- **Re-runs don't reuse handles.** A re-run (§7.7) resolves the original run's `run_inputs` while they're retained,
  revalidates the input against the active version's schema, and claims it again, owned by the new request. The new
  run never holds the old run's handles, so nothing depends on the old run's retention.

### 3.5 Claiming inputs before a run starts

One function in `apps` validates a trigger against the version's input schema, then splits it:
- **Sensitive first:** every value at an `x-sensitive` position, and every value at a position the schema doesn't
  declare (`additionalProperties`, pattern properties, a union where any branch is sensitive), is claimed with
  taint. Unknown counts as sensitive.
- **Then size:** a value larger than 64 KiB is claimed without taint. A size claim is made after its sensitive
  descendants were claimed, so it holds handles where they were: a pointer into a size claim reaches plain data or a
  nested handle, never an untainted view of a sensitive value.
- **Reappearing text:** an untainted field that contains a string (4 characters or more) from one of the trigger's
  own sensitive fields is claimed with taint.
- **Then the envelope:** while the trigger envelope passes `TRIGGER_INLINE` (initially 64 KiB), its largest remaining
  subtree is claimed without taint. Ties are broken by pointer. The root is claimed last, and the envelope is then one
  handle. Every continued input carries the envelope again, so it has to stay small (§5.3). A sub-flow's input is split
  the same way when its parent starts it.
- The result is the trigger envelope, with handles in place of claims. In 2b-1 the caller is `admit`/`start_run`; in
  2b-2, `admit_request`.

### 3.6 The activity boundary

- **Every activity that returns tenant data goes through one wrapper in the worker process, before the SDK
  serializes its result.** The wrapper splits the result as §3.5 does (by the node's output schema for plugin
  steps) and verifies that nothing plain is left at a sensitive or undeclared position. If something is, it raises
  a sanitized, non-retryable error instead of returning it.
- The workflow also checks what arrives, and fails the run with `internal_error` if a sensitive position holds
  plain data. That check is a tripwire: whatever it sees is already in history. The wrapper is the boundary.
- **Results of claims:** an activity's result is tainted if any claim it resolved was tainted, nested claims
  included. Evaluating an expression over a size claim that holds tainted handles can't return an untainted
  result.

### 3.7 The secret index

- `run_secret_index`: one encrypted row per **root run**, under RLS, holding every string of 4 characters or more
  found in any tainted claim made in its tree — seeded at admission with the trigger's claims, extended by every
  activity that makes a tainted claim.
- **At every activity boundary** in the tree, the wrapper consults it:
  - an untainted part of the output that contains an indexed string is claimed with taint — the data kept intact,
    only moved. This covers a later plugin that fetches the same token from outside and returns it in an untainted
    field;
  - every error message leaving the activity is masked against it. A plugin's own failure (`FatalError` and the
    like) is shown only as far as it's code (§6.7): its code when it's a constant of the plugin's code and a dotted
    lowercase identifier, else `node_failed`; its message when it's a constant of that code, else a generic one. A
    secret the node made and quoted before its output was claimed is in no index, so masking can't catch it there.
- **At projection:** masking of previews and messages moves from the workflow to the `project` activity, which
  masks against the index before writing `run_steps`.
- **Freshness:** the index has a version. Each boundary validates the version it uses; a cache is never served
  unchecked to concurrent activities.
- **Bounds on the index:** at most 100,000 strings or 8 MiB per root run (provisional, §15). Passing a bound is
  permanent for that run, so it's never retried: at admission the request is refused with `secret_index_limit`
  (422 for an interactive source, a `refused` request for a durable one); in an activity, the step fails with
  `secret_index_limit`, a fixed non-retryable code, under its error policy.
- **Bounds on matching work:** the boundary matches with an automaton (Aho–Corasick) built once per index version
  and cached with it, so building costs at most the index's bound; each scan is linear in the bytes it scans, which
  §5.2 bounds, and a value is claimed at its first match. Work per boundary is therefore bounded by the index bound
  plus the output bound, never by their product.
- **Unavailability is transient:** if the index can't be read, the activity is retried a bounded number of times,
  then fails its step with `secret_index_unavailable`. It never returns output unchecked.
- **The guarantee** covers the secrets recorded when a boundary checks. A secret learned concurrently can't
  retroactively change an earlier result.
- The learned-secret lists (`secrets` in `Parent`, `RunResult`, `BatchResult` and the snapshot) leave history.

### 3.8 Sensitive literals are refused

- Publish refuses a literal at a sensitive config position, a `default` at a sensitive position of `input_schema`
  or `vars_schema`, and a default on a sensitive CSV column (§8.1). The diagnostic points to trigger inputs now and to
  connections in sub-project 3.
- Publishing again an existing version that has such literals fails the same way, so the protection ABI can't admit
  it unchanged.

## 4. Taint, routing and declassification

### 4.1 Taint at publish

The validator marks every readable path and every value site as tainted or not, and the version stores the result
(as it stores CEL classification), with a per-output taint map. The editor explains it: why an expression runs in
the evaluator, and what each declassified site reveals.

**Sources:**
- trigger paths at `x-sensitive` positions of `input_schema`, and element paths of a sensitive CSV column
  (`trigger.rows[*].<column>`);
- plugin output paths at `x-sensitive` positions of the manifest's output schema;
- variable paths at `x-sensitive` positions of `vars_schema`;
- any position the schema doesn't declare, and any path a CEL expression addresses dynamically (a computed map key,
  for example) — unknown counts as sensitive, never local.

**Propagation (per path, not per value):**
- a ref, template, CEL expression or transform field is tainted if any path it reads is;
- a variable is tainted if its schema position is, or any assignment to it anywhere in the graph is;
- `item` takes the taint of its loop's items **element** paths, and `loops.<key>.item` likewise, field by field
  (`item.<column>`); `index` and `loops.<key>.index` never are; `run.*` never is;
- a loop's collected `items` takes the taint of its `collect` expression; its `count` is plain (declassified or
  untainted); its `failures` keep fixed codes, with masked messages;
- a **whole-list read** — CEL or a template reading a list as a whole, `size(list)`, a filter over it — is tainted
  if any element path of the list is. `trigger.row_count` stays public;
- a sub-flow's outputs take the output-taint map recorded on its pinned version.

### 4.2 Routing

- A tainted expression or template always goes to `cel.evaluate` by handle: the activity resolves the claims,
  evaluates in the isolated evaluator, and returns a claimed result — or, at a declassification site only, a plain
  decision.
- An untainted expression is routed as today, with one runtime rule on top: **a binding that is a handle is never
  evaluated in the workflow.** It goes to the activity, and its result's taint comes from §3.6.

### 4.3 Declassification

Only these sites may turn tainted input into plain output:

| Site | What becomes visible |
|---|---|
| `flow.if` `condition` | the branch taken |
| `flow.switch` case `when` | the port taken |
| `flow.loop` `items` | the item count; each `item` is a handle with a pointer, or a row with handles in its sensitive cells |
| `flow.filter` over tainted items or with a tainted predicate | the input count and the kept count |

- **Each declassifying site must be listed** in `graph.settings.declassify` (node and field). Publish refuses an
  unlisted tainted decision, and a listed site that isn't tainted (a stale entry).
- Publishing a version whose `declassify` list is non-empty requires the permission `workflow.declassify` (tenant
  admins and owners by default). The publish audit entry records every listed site and what it reveals.
- **The one exception:** a loop whose `items` is a direct reference to a list whose length publish can prove is
  already public — `trigger.rows`, whose length is `trigger.row_count` — needs no entry. A derived or filtered
  sensitive list doesn't inherit the exception.

### 4.4 The tainted filter

- When a filter's items or predicate are tainted, or its items are a handle, the whole filter runs in **one
  activity**: it resolves the list, evaluates each item in the evaluator in its own batches, and stores the kept
  items as a claim. The workflow gets the kept-items handle, the input count and the kept count; no per-item decision
  or view enters the workflow or its history. The iteration budget is charged the input count, exactly.
- When the items or the predicate are tainted, the kept-items claim **stays tainted**, even if the items were public.
  Only the two counts become plain, and the filter must be listed in `declassify`.
- A filter over a **size-only, untainted handle** takes the same activity route but needs no `declassify` entry.
- An untainted filter over inline items is unchanged.

### 4.5 Refused at publish

- `flow.delay` or `flow.wait_until` computed from tainted data: a timer's duration is visible in history.
- A tainted `flow.fail` message.
- A tainted value passed into a sub-flow's input field that the child doesn't mark `x-sensitive`, so each version's
  own analysis stays true.
- Sensitive literals and defaults (§3.8).

### 4.6 Visible metadata

Whatever the design, this stays in Temporal history — encrypted by the codec where it's a payload — for the
namespace's retention period, whatever the tenant's retention (§10.2):
- workflow ids, which include the tenant and run ids;
- workflow and activity types, task queues, build ids;
- step ids, iteration keys, attempts and timings;
- the run's shape: which steps ran, and timer durations taken from untainted values;
- claim ids and pointers;
- the declassified decisions and counts of §4.3;
- error codes — fixed and sanitized, never derived from a sensitive value or plugin-supplied free text — and
  already-masked messages;
- untainted data, including values up to 64 KiB;
- payload sizes;
- a local activity's bookkeeping, which the SDK's core records beside its (encrypted) result, outside any codec: its
  sequence number, attempt, activity id and type, and times.

## 5. Sizes and snapshots

### 5.1 The size threshold

**From 2b-1b**, a value larger than **64 KiB** (the local-CEL per-value cap) is a size claim. Anything the workflow
could evaluate locally stays inline; anything larger is a handle, evaluated by handle in an activity. In 2b-1a every
value still travels inline, within §5.2's limits.

### 5.2 The outgoing-payload guard

- **Measured before it goes.** Each payload is measured where it's produced: its JSON, as the SDK's payload
  converter writes it, plus `CODEC_OVERHEAD` (256 bytes), a bound on what `TenantCodec` adds that a test proves. The
  limit is a margin below Temporal's 2 MiB (initially 1.75 MiB). Experiment 2 (§11) showed that the SDK checks the
  payload **after** the codec, so the guard counts the codec's share.
- **Commands, before they're sent:** a client's start (`start_run` refuses it before admission, with a fixed reason,
  and leaves no row); a plugin step's input (the step fails, and nothing is sent); a sub-flow's start (the step
  fails) and a failure handler's (its row records the failure); continue-as-new (§5.3). `cel.evaluate` requests (as
  #15 does) and a loop's batch split, by bytes as well as count. The projection is already bounded (256 KiB); grant
  signals are bounded by construction.
- **Results, where they're produced:** a workflow-side check can't rescue a result Temporal has already refused to
  record. A plugin step's output is checked in its activity (the step fails once, keeping its outcome: the node ran);
  the version loader's result in its activity (`version_unusable`); a run's result in the run (it fails, with no
  outputs); a batch's in the batch (its loop fails, and it still reports the iterations it used). `cel.evaluate`
  results are bounded by the evaluator (256 KiB).
- **Fail with a fixed, bounded error; spill only from 2b-1b.** In 2b-1a a payload that can't be split fails its
  step, its loop or its run with `payload_too_large` — a result, never a retried workflow task — and is never sent. A
  batch item that can't fit, with what its batch reads, fails its loop after the items before it: it's never dropped.
  2b-1b adds spilling before failing: eligible values go into size claims, largest first, through a `spill` activity
  in chunks under the limit (every inline value is at most 64 KiB, so a chunk always fits), and the receiving paths
  accept the handles — plugin activities resolve them, sub-flows receive them with grants, a parent reads a
  sub-flow's outputs through its grant. Only then does an envelope that still doesn't fit, or a declared limit (a
  node's field count), fail.
- **The sensitive values a run carries are bounded:** its result, its children's starts and its snapshot carry the
  values it learned, so that they're masked there too. Until claims (2b-1b), they travel inline, bounded by
  `SECRETS_BYTES` (initially 256 KiB, measured as they grow). A value that would pass the bound fails the step, the
  child's step or the run that would add it, with `payload_too_large`, and whatever carried it is never used, so
  nothing unmasked goes on. What's carried is never dropped: a parent always masks everything its children tell it.
- **Every final result is checked** before it's recorded: a success's, a failure's, a cancel's,
  `snapshot_too_large`'s, a stopped batch's. Without outputs or collected items a result carries only an error (a
  stored message, at most 500 characters) and the bounded sensitive values, so it fits; outputs and collected items
  are checked where they're made. A result past the limit anyway is a bug: the run ends `internal_error` (a batch
  fails its loop), with no outputs, so nothing it returns needs masking, and no workflow task retries.
- **Per workflow task, a hard invariant:** the encoded bytes of every command one workflow task sends stay below
  Temporal's gRPC message limit (4 MiB on the tested server), with margin. Experiment 2 showed what happens
  otherwise: the SDK fails the task with the non-retryable `GrpcMessageTooLarge`, and Temporal **terminates** the
  workflow — no end write, no failure handler. So the yield budget (engine-core §5.6) gains a dimension for outgoing
  command bytes (initially 3 MiB): a command that would pass it waits for the next workflow task, and no single
  command exceeds the per-payload limit, so every completion fits. It counts every payload a task sends: each
  command's, the execution's result, and a local activity's result, whose marker goes out with the task's
  completion. It's an invariant with its own tests, not a tuning value.
- **#15's guard** is verified again after the codec: its 1.75 MiB of JSON plus `CODEC_OVERHEAD` stays under 2 MiB.

### 5.3 Live state and snapshots

**The bound is on the whole continued input:** what an execution sends when it continues as new. That is its run or
batch input with the snapshot, encoded as Temporal holds it. It must fit within `SNAPSHOT_MAX` (initially 1.5 MiB).

The input has five components, each with an accounting rule and a worst-case maximum. The live-state budget
(`LIVE_BUDGET`, initially 1 MiB) is one of them, a fixed constant. What gives way is each version's open-scope cap
`OPEN_SCOPES_CAP_v`: the largest cap, at most `OPEN_SCOPES_CAP` (initially 100), for which

`CODEC_OVERHEAD + ENVELOPE_MAX + TRIGGER_MAX + STRUCTURE_MAX_v(cap) + LIVE_BUDGET ≤ SNAPSHOT_MAX`

So the bound holds by construction for every version:
- **The cap is part of the pinned version.** Publish computes `OPEN_SCOPES_CAP_v`, and the version's loop depth `D_v`,
  and stores them in the version. Runs pin the version (engine-core §7), so a later change of a constant can't change
  how a pinned run schedules, on replay or after it continues.
- **The maxima are computed by tests** that build the largest encoding each can have.
- **Nothing is refused on an assumption.** The follow-up must show that a cap of at least 1 fits the largest graphs
  the limits allow (§11.2). No publish refusal is added on the assumption that it does. If it doesn't, the limits or
  constants change before 2b-1b's plan.
- Continuing still measures the encoded input (the check 2b-1a added). Past `SNAPSHOT_MAX` is then a bug: the run
  fails with `snapshot_too_large` rather than retry a workflow task.

**Each value travels once.** A continued input carries its envelope and its trigger beside the snapshot, and nothing
else. Everything else is restored from the snapshot alone:
- A continued `LoopBatch` drops `items`, `outer` and `variables` from its original `BatchInput`. The snapshot holds
  them as the loop's item list, the frozen scopes' results and the variables, counted in components 4 and 5.
- A continued `RunGraph` carries its variables only in the snapshot, as today.
- So an item slice that fit the 1.75 MiB start limit is a container like any other. The budget claims it on the
  batch's first workflow task, long before any continue.

1. **The envelope:** identifiers, settings, counters and deadlines, a child's `Parent` (its `grant` included), and the
   snapshot's own header, the iteration budget's fixed counters included (component 4).
   - Its ids are server-built, to the exact grammar of §6.1, whose longest form is `ID_MAX`.
   - Its other fields are enums, and numbers and timestamps with bounded ranges.
   - So `ENVELOPE_MAX` is a constant: every field at its widest, every id at `ID_MAX`. It never depends on what a
     parser would accept.
   - From 2b-1b it holds no learned sensitive values (component 3).
   - Accounting: none at run time.
2. **The trigger:** the inline trigger envelope, which every continued input carries again.
   - §3.5 bounds it: after the claims, the envelope's largest subtrees are claimed until it's within `TRIGGER_INLINE`
     (initially 64 KiB), down to claiming the whole trigger.
   - `TRIGGER_MAX = TRIGGER_INLINE + HANDLE_MAX`, and the trigger never changes during a run.
   - A start may carry up to the payload limit (1.75 MiB), so a trigger near it still starts, and its continuations
     carry at most `TRIGGER_MAX` (§11.2, condition 1).
3. **Learned sensitive values:** none.
   - From 2b-1b they leave history for the run's secret index (§3.7).
   - `SECRETS_BYTES` and the inline list retire with ABI 6.
4. **The structure:** what isn't a value.
   - **What it covers:**
     - scopes: their keys, and one code per node and per edge of their region;
     - the variable versions that queued loop steps captured (below);
     - started loops: their counters, their open and collecting indexes, and their collections' headers;
     - units handed out: sleeping timers, spills in flight.

     The iteration budget's waiting needs and its children's grants aren't in it: a continue happens only once both
     are empty (below).
   - **Scopes:** at most `OPEN_SCOPES_CAP_v + D` iteration scopes, the root, and a batch's frozen scopes (at most
     `MAX_LOOP_DEPTH` of them, which hold no codes). Each scope's codes number at most its region's nodes plus edges.
   - **Captures:** each loop step queued in an iteration scope (ready, and not started) holds one entry. The entry
     names the variable version the step captured (below): a node index and a small version number, at most
     `CAPTURE_MAX` bytes. A scope holds at most its region's loop steps of them.
   - **Loops:**
     - A loop step inside an iteration scope starts only when its loop can open an iteration at once. That means room
       under the cap, or its level's reserved scope on the progress path.
     - **Queued loop steps share one request.** A queued loop step never adds a need of its own to the budget.
       - While the budget can't decide, every queued loop step waits:
         - a child execution waits on its one request to its parent (a budget asks its parent at most once at a
           time);
         - the root never asks a parent. It grants or refuses once its own waiting needs can be decided, and under
           the exact cap that can mean waiting for an outstanding child to release unused budget.
       - Queued loop steps stay queued through either wait. They never fail early.
       - Once the budget decides, a grant lets queued steps start, in scheduling order, while budget remains.
       - A refusal starts them too, at most `IN_FLIGHT_CAP` at a time as any step. Each loop fails
         `iteration_cap_exceeded` at its first iteration, and the step settles under its `on_error`.
     - So a queued loop step always starts or settles:
       - the progress path frees scopes;
       - every request to a parent is answered;
       - the children the root waits for end, and release their unused budget as they end.

       It's never left queued.
     - A started loop takes the scope its own finished iteration frees, before anything else does, so it holds a
       scope until it finishes.
     - A loop waiting for more iteration budget holds none, but no loop starts while the budget is waiting.
     - So started loops in iteration scopes number at most `OPEN_SCOPES_CAP_v + D`, and root-region loops at most the
       root region's loop steps. Root-region loop steps are never deferred.
   - **Units:** at most `IN_FLIGHT_CAP` units are handed out at once, spills included, so the timers and handed-out
     records a snapshot keeps are bounded by it.
   - **The iteration budget (the at-continue term, approved by the owner):**
     - Its waiting needs and its children's grants are transient. While the execution runs, its waiting needs are at
       most one per started loop, one per running filter and one per child (queued loop steps add none), and its
       grants at most one per child.
     - **An execution continues only once its budget holds no waiting need and no child's grant.** Both are enforced,
       and both checks stay in the implementation:
       - the quiescence check that lets an execution continue requires both empty, besides no unit outstanding and
         no request to or from a parent;
       - the snapshot refuses to be taken otherwise;
       - a regression fails if either survives to a continue.

       A need still undecided when nothing else runs (asked while an answer was applied) is decided first. Under the
       exact cap the root may wait for an outstanding child, which isn't quiescence anyway.
     - So a continued input carries only the budget's fixed counters, in the envelope (component 1), as it carries
       `Parent.grant`. Neither waiting needs nor grants are a term of the bound.
   - `STRUCTURE_MAX_v(cap)` is the sum of four terms:
     - `(cap + D_v) × (ITER_SCOPE_MAX_v + LOOP_MAX)`;
     - `ROOT_SCOPE_MAX_v + ROOT_LOOPS_v × LOOP_MAX`;
     - `FROZEN_MAX`;
     - `IN_FLIGHT_CAP × UNIT_MAX`.

     The version-dependent terms:
     - `ITER_SCOPE_MAX_v`: the largest, over the version's loop regions, of the region's node and edge codes plus its
       loop steps × `CAPTURE_MAX` plus a scope's own fields;
     - `ROOT_SCOPE_MAX_v`: the root region's codes and fields;
     - `ROOT_LOOPS_v`: the root region's loop steps.

     `LOOP_MAX` and `UNIT_MAX` are fixed by the encoding and by `ID_MAX`.
   - Accounting: the cap, the deferred start, the shared request and the in-flight cap enforce it, and the
     quiescence check and the snapshot keep the budget's needs and grants out of it. The counts are checked as
     scopes open, loops start and units are handed out.
5. **Live values, within `LIVE_BUDGET`:** every value the snapshot holds inline except the trigger.
   - **What it covers:**
     - settled steps' results in open scopes, and scopes' items;
     - loops' inline item lists;
     - collections' tails, the values being sealed, and their segment lists;
     - the variables, and the older variable versions kept for captures (below);
     - a batch's frozen outer results.
   - **Accounting rule:** each value is counted at its exact encoded size (compact JSON, as the payload converter
     writes it, with its fixed framing in the snapshot) when it enters the state, and uncounted when it leaves. The
     counter isn't stored: restoring counts it again from the snapshot, and a test asserts the two agree at every
     snapshot.
   - **Enforcement:** it runs after every change: a merge, a result, a scope opening, a loop starting, a variable
     version created or dropped, a spill written.
     - While the counter passes `LIVE_BUDGET`, the largest spillable container is claimed and replaced by its handle,
       ties broken by scheduling order.
     - Values on their way to a claim still count until they're written, and the choice discounts them.
     - The containers:
       - a collection's tail, and its segment list, claimed as an index segment;
       - a loop's inline item list: the loop waits for its segments, then carries on over them as a cursor;
       - a scope's whole result set, and its item;
       - the variables, and each older variable version kept;
       - a frozen scope's result set.
     - A container is spillable when it's larger than `HANDLE_MAX`. The handle that replaces it has an empty pointer
       (§3.2). A reference into a claimed container reads by handle, in an activity (§3.3), as any claim.
   - **Bound:**
     - With every spillable container claimed, the live state is at most `HANDLE_MAX` per container.
     - The containers number at most two per scope, five per started loop, one per kept version (at most the root
       region's `set_variables` steps, plus the current one), and one per frozen scope. Component 4's counts bound
       those.
     - A test proves that `LIVE_BUDGET` is above that minimum for every cap the formula allows. The budget then holds
       at every continue: continuing happens only when nothing is in flight, spills included. A drain still starts
       the claims it decides, and a run doesn't continue while its live state is past `LIVE_BUDGET` (§11.3).

**When a loop step inside an iteration reads variables.**
- **Today:** a step resolves all its values when it starts, and the in-flight cap can already start a ready step later
  (engine-core §6).
- **From 2b-1b:** a loop step inside an iteration scope (the only step the open-scope cap defers) reads the variables
  **as they were when it became ready**, captured then. It resolves everything else when it starts:
  - the trigger, the results it references, `item`, `index` and `loops.*` don't change once it's ready;
  - `run.now` is the time it starts, as for any step.
- **The effect:** what it reads no longer depends on how long it waits, so the read is deterministic under deferral.
  It can differ from today's read at start: a root-region `set_variables` step that settles between the loop step's
  readiness and its start is visible to it today, and isn't from 2b-1b. Such graphs stay publishable.
- **Every other step** still reads variables when it starts: root-region loop steps, all steps outside loops, and
  every step that isn't a loop step. A batch's variables never change (a loop body can't write them,
  `vars.write_in_loop`), so its loop steps capture nothing.
- **The representation is shared and bounded:**
  - Variables change only when a root-region `set_variables` step settles, at most once each per run
    (`vars.write_in_loop`). So a run has at most that many plus one versions: the defaults are version 0.
  - A queued loop step's capture is just the number of the version it became ready under (component 4).
  - A snapshot keeps the current variables and each older version some queued loop step still names. An older version
    is kept as the values that differ from the current ones, each version one container (component 5).
  - A version no queued step names is dropped.
- **Tests:**
  - a root `set_variables` that settles while a loop step is queued isn't seen by it;
  - the same run, with the cap and with a cap large enough never to defer, reads the same values;
  - root-region loop steps and other steps still read at start;
  - with many queued sibling loop steps, at the scale of §11.2's counterexample, an exhausted iteration budget starts
    or settles every one, and the budget's waiting needs stay within their maximum at every snapshot.

**The rest of the design:**
- **Merges are authoritative.** The inline threshold an activity sees (§5.4) is advisory. A result that would pass the
  budget is claimed before it merges, and merges happen one at a time, so concurrent activities can't all spend the
  same headroom.
- **Collections compact.** A loop's collected values and its failure list are each immutable **segment** claims plus
  a short tail. The tail is claimed as one segment once it passes `SEGMENT_BYTES` (initially 256 KiB), or earlier when
  the budget requires. The segment list is a container itself (component 5), so a collection's inline part stays
  bounded however many segments it has.
- **Pending work is cursors:** a loop's items (a handle, or an inline list, which is a container) and its next index.
- **`snapshot_format` 2** (measured in §11.2): one code per node and per edge in region order, indexes instead of
  ids, and no stored queue. Restoring rebuilds what's queued from the node, edge and loop states. The snapshot records
  only the units already handed out: in practice, sleeping timers.
- **Open iterations are capped per execution:**
  - **The general cap:** a loop opens an iteration only while the execution has fewer than `OPEN_SCOPES_CAP_v` open
    iteration scopes: at most `OPEN_SCOPES_CAP` (initially 100), and less for a version whose structure needs it
    (above).
  - **The reservation, one scope per nesting level,** `D` in all, where `D` is the version's deepest loop nesting,
    computed at publish.
    - The **progress path** runs from the execution's root (a batch's loop scope) through the oldest open iteration
      at each level, "oldest" by opening order, so it's deterministic across replay.
    - A loop on that path may open one iteration from its level's reserved scope while that scope is free.
    - A shared pool of `D` scopes isn't enough: sibling loops on one level can exhaust it, and the next level
      deadlocks (§11.2).
  - **The bound:** open iteration scopes never exceed `OPEN_SCOPES_CAP_v + D`.
  - **Progress:** the deepest scope on the path can always open an iteration of its own loop, from its level's
    reserved scope. Steps without loops run under `IN_FLIGHT_CAP`, and activities and children always end or time out.
    So the path's deepest iteration completes and frees its scopes, and the path moves on. An outer iteration waiting
    for an inner loop is never starved.
- **The go/no-go.** The first probe (§11.2) measured the tested workloads: promising, not yet a go. The gate passes on
  a focused follow-up that tests these rules at their limits:
  - a near-limit trigger;
  - every container of component 5 together: the variables, a batch's frozen results, and collections whose segment
    indexes grow;
  - many sibling loops under the cap;
  - root `set_variables` steps settling while loop steps are queued;
  - an exhausted iteration budget, with many queued sibling loop steps;
  - a batch whose item slice is near the 1.75 MiB start limit;
  - references through long keys, and through chained handles.

  For each, it measures every component against its maximum, and the whole encoded continued input against
  `SNAPSHOT_MAX`. It also checks the queued loop steps' reads, and that each one starts or settles. It reports the
  computed maxima and the cap they leave for the largest graphs, and it shows that a cap of at least 1 fits them.
  Until the gate passes, the spec promises only that continuing is guarded against size (§5.2), and the rules above
  stay provisional.
  - **The gate passed (the owner's go, 2026-10-01, §11.3).** The rules above are approved for implementation by
    2b-1b, whose tests prove them; the numbers stay provisional until measured (§15).
- **2b-1a promises only the check:** a continued run's input past `SNAPSHOT_MAX` once encoded fails the run cleanly
  with `snapshot_too_large` (a batch fails its loop). The components above and a proven bound are 2b-1b's.
- **History headroom:** the drain thresholds reserve room in the old run's history for the snapshot, so a structure
  that can't be compacted fails the run before history headroom is exhausted.
- **Writes are idempotent and hash-checked.** A spill's claim id is derived by the workflow, deterministically, so a
  retried activity writes the same row. A row that already exists must match the content hash the activity computed,
  or the activity fails without writing.
- **Restoring** reads the snapshot's cursors and segment handles deterministically, across repeated continues.

### 5.4 Values the workflow makes

Activity inputs carry the current inline threshold, derived deterministically from workflow state: above the
budget, activities claim outputs larger than a small floor (1 KiB). Values the workflow makes itself (local CEL
results, transform outputs, variable values) enter the live state like any value. §5.3's enforcement claims the
largest container when the budget requires.

## 6. Codec, keys and workflow ids

### 6.1 Workflow ids, always built by the server

- Every run — root, sub-flow, failure handler — has the workflow id `t:<tenant>:run:<run_id>`. Workflow code builds
  a child's id deterministically before starting it.
- Batches: `t:<tenant>:run:<run_id>/<step_id>/<iteration_key>/batch:<start>`.
  - `<step_id>` is the loop step's UUID.
  - `<iteration_key>` is the loop's enclosing iterations, outermost first: empty at the root, otherwise at most
    `MAX_LOOP_DEPTH − 1` segments `<step key>:<index>` joined by `/`. A step key is at most 63 characters.
  - `<start>` is the batch's first item. It and every index are below the largest `item_cap` (10,000).
  - So a server-built id has a longest form, `ID_MAX`, which `ENVELOPE_MAX` is built from (§5.3).
- Schedules (2b-3): the Temporal Schedule id and the `ScheduleTick` workflow-id prefix are
  `t:<tenant>:sched:<schedule_id>`.
- **Idempotency:** a root's run id is its request's id, and the start uses `REJECT_DUPLICATE` (§7.4).
- **Lookup** is always by (tenant, run id), with the id rebuilt on the server. A workflow id supplied from outside is
  never parsed.
- **Checked where it's used.** The codec reads the tenant from the id's strict grammar (a full match: nothing may
  follow). From 2b-1b the grammar is exact: it matches a batch's suffix part by part, as above. 2b-1a's parser still
  accepts anything after the run's id and a `/`. `RunGraph` and `LoopBatch` refuse a start whose id doesn't name
  the start's tenant and run, and every activity that touches the store refuses an input of another tenant —
  `internal_error`, never the node's failure.
  An id that names no tenant never reaches Temporal: the client's codec has no key to encrypt its start with.
- This replaces the parent spec's `run:{run_request_id}` (§13).

### 6.2 `TenantCodec`

- A PayloadCodec implementing `with_context`. **Its tenant comes only from the context:** it parses the context's
  workflow id with a strict grammar. No context, or an id that doesn't parse, means it refuses to encode or decode
  (fail closed). There's no default key and no fallback to metadata.
- **Encoding:** AES-256-GCM with the tenant's active data key. The payload metadata records the encoding, the tenant
  and the key version; the tenant and key version are also bound into the associated data.
- **Decoding:** the tenant in the metadata must equal the context's tenant; the version selects the key. Where a
  decoded payload carries a `tenant_id`, the code that uses it checks it against the workflow id (§6.1): the codec
  never reads a payload's content.
- **Failures:** every client and worker uses `DefaultFailureConverterWithEncodedAttributes`, so failure messages and
  stack traces are encrypted too (they're already masked).
- Dewpoint never uses memo or search attributes; the codec never sees them.
- **Conditional on experiment 1 (§11):** if any path lacks reliable context, that path is redesigned before the
  plan, never given a fallback.

### 6.3 Keys

- The codec uses the keyring's per-tenant data keys through an in-process cache of unwrapped keys, bounded in size
  and time (initially 1,024 keys for 5 minutes, so a rotation reaches every process within 5 minutes) and never
  persisted. The codec never creates a key, and a missing key isn't cached. A tenant gets its key when it's created;
  `dewpoint keys ensure-tenants` gives one to older tenants, as the key admin (`dewpoint_admin`, which lists every
  tenant under row-level security), in Compose's migrate step.
- **An expired key is never used**, even while the database doesn't answer: the rotation bound above and §6.4's
  floor stay exact. The cost is that a database outage longer than a key's time fails the payloads that need it: an
  activity's attempt fails (a plugin step's is retried or `outcome_unknown`; `cel.evaluate` ends
  `cel_profile_unavailable`), and a workflow task fails and is retried until the database answers.
- **Who has keys:** the worker (including the `cel.evaluate` activity) and the dispatch role, which gains `SELECT` on
  `data_keys` in 2b-1a: until 2b-2, the dev CLI still starts runs directly, through that role, and encrypts the
  start. From 2b-2 the API and the dev CLI send Temporal no payloads (the CLI enqueues, and `--wait` reads the
  database), and the dispatcher encrypts every start. Ingress has none (§8.3).

### 6.4 Key rotation and retirement

- Rotating a tenant's key keeps every older version able to decrypt. The codec records the version on every
  payload.
- **A version's last use for payloads is bounded, not recorded.** Every process caches a tenant's active key for at
  most the key cache's TTL (5 minutes, `KeyringKeys`), so none encrypts with a version later than its successor's
  creation plus that TTL.
  An execution holding such a payload closes within twice the maximum run duration (a run, then its failure handler),
  and Temporal deletes it after the namespace's retention. So the **payload floor** is: the successor's creation +
  the cache's TTL + 2 × the longest maximum run duration ever configured + the namespace's retention. (Durable
  last-use tracking would shorten it; it isn't needed to retire safely.)
- **An old version is retired only when nothing needs it:**
  - the payload floor has passed, and no execution that could hold such a payload is still open: a run stalled past
    its deadline (its build's workers gone) keeps its history, and its payloads, until it closes;
  - every record Dewpoint stores under it — `run_inputs`, `step_outputs`, `run_secret_index`, pending
    `run_requests` and `inbound_events` material, `csv_uploads`, schedule inputs and Temporal schedule actions — has
    been re-encrypted under the current version by `dewpoint keys reencrypt` (schedules by updating them), or deleted
    by retention;
  - no request's idempotency digest was made with it, until retention deletes that request;
  - the tenant's inbound X25519 private keys (§8.3), wrapped by it, have been re-wrapped under the current version.

### 6.5 Tenant erasure

1. **Mark the tenant `erasing`,** atomically, under its lock. From then on these refuse the tenant: admission,
   dispatch, ingress recording, webhook matching, and the `ScheduleTick` activity (in the transaction that would
   insert its request). The dispatcher's `starting` transaction takes the tenant's lock shared, as it does the gate's.
2. **Synchronize with starts:** every `starting` request of the tenant is reconciled (§7.6) — started, or confirmed
   absent — before anything is deleted.
3. Pause its schedules.
4. Cancel its queued requests and pending events.
5. Cancel its running runs, and wait until they're terminal.
6. Delete its keys — only once nothing is left that could decode, so no live run is left unable to read its history.

### 6.6 ABI 5 and draining

- 2b-1a raises `ENGINE_ABI` to 5 (ids, codec); 2b-1b to 6 (handles, claims). Issue #15's fix takes 4 first (§1); these
  numbers depend on it landing before 2b-1a.
- An older build drains its pinned runs on its own build. No newer component sends it payloads: dispatch requires
  the new capabilities of the current build (§2.7).
- Histories of builds before 2b-1a — ABI 4 and older — stay in plain text until the namespace's retention ends;
  under 2a's rule they hold only test data.
- Queued requests of an older ABI are cancelled with `engine_abi_changed` (engine-core §4.5).

### 6.7 Without a codec server

There's no codec server in 2b; Temporal's Web UI shows ciphertext. Incidents rely on the run projections (status,
steps, codes, masked messages), worker logs (below), and `dewpoint runs diagnose <run>`, which reports only what
Temporal shows without decoding — the workflow's status and timestamps, its task queue and build id, pending activity
types and attempt counts, and whether a failure exists — next to the projection. It doesn't promise failure types.

**The log lines the worker controls hold only text proven to be code (§12)**: its own logs, a plugin's `ctx.log`,
and Temporal's records of activities. A secret a plugin makes itself, such as a token an API has just issued, is in no
secret index until the step's output is claimed (§3.7), so neither masking nor redaction by a field's name proves a
log line safe. So:
- A plugin's log line keeps its event, a field's name and a field's value only when each is a constant of the plugin's
  own source (read from its package's code objects), a boolean or null. A computed event is withheld, a computed field
  name dropped, and any other value redacted, numbers included. A field whose name looks secret is redacted even then.
- A bug in a node is logged by its type and where it was raised (file, function and line); its text only when that's
  such a constant. A class name is text too, which a plugin can make at run time: it's shown, in a log line and in a
  step's message, only when the class is a builtin or its module's code declares the name. A frame is named only when
  its code was compiled from its module's source, and its line only when that compiled function has it: a traceback a
  plugin builds survives `raise` and can carry any number.
- Temporal's records of activities keep only the exact text of one of the SDK's fixed messages, never what follows it
  (an activity's details, an error's text), nor an error's code or class: a code's shape proves nothing about where it
  came from. Any other record is withheld whole, and no record keeps an exception or its traceback.
- A plugin's failure, its step's error, follows the same rule (§3.7): its code and message are shown only when they're
  constants of its code.

Nothing is promised outside these paths: a plugin that logs through Python's `logging` or `print`, or calls a library
that logs, writes what it writes. The SDK says so, and plugins log through `ctx.log`.

## 7. Admission and dispatch (2b-2)

### 7.1 `run_requests`

`run_requests` is the durable, transactional queue; it replaces the parent spec's separate `outbox` (the request row
is itself the intent, written atomically). Each row: the id (also the future run's id); the tenant, workflow and
frozen version; the source (`manual`, `rerun`, `schedule`, `webhook`, `dev`) and the actor; the mode; the
idempotency key and digest; the status and a reason code; the attempt count and next-attempt time; `queued_at`. The
trigger isn't on the row: it lives in `run_inputs`, encrypted, as an envelope holding handles.

**Statuses:** `queued`, `starting`, `started`, `cancelled`, `refused`, `dead`.

### 7.2 `admit_request`

**It runs inside its caller's READ COMMITTED transaction and never commits it.** The caller commits: the API handler
(one request), `ScheduleTick`'s activity (one tick), the webhook matcher (every binding of one event, with the
event's progress — §8.3). Each call runs under its own savepoint. Whatever one call writes — claims, secret-index
seed, request, audit entry — commits or rolls back with the caller's transaction as a whole.

The **digest** is tenant-keyed: an HMAC with a key derived from the tenant's data key, over the canonical JSON of the
source, workflow, mode and input — never an unkeyed hash of input that may hold low-entropy secrets. Each request
stores the digest's key version.

In this order:
1. **Authorize** the caller: `run.start` in the tenant for interactive sources; a durable source is authorized by
   its binding or schedule.
2. **Look up the idempotency key** `(tenant_id, idempotency_key)` first. If a request exists, compute the digest
   with **that request's stored key version** and compare. An exact retry returns the original frozen request as it
   is now, whatever has changed since — a key rotation, the gate, the active version, the workflow being enabled. A
   different request under the same key is a conflict (409 `idempotency_conflict`).
3. **Only for a new key,** the mutable checks: the tenant isn't `erasing`; the gate, for interactive sources
   (§2.3); engine-core §4.5's rules — the workflow's admission lock, enabled, active version, executable, ABI against
   the current build; the input schema (errors give locations only).
4. **Digest** with the tenant's **active** key version.
5. **Claim** the trigger (§3.5) and seed the secret index.
6. **Insert** the request with `ON CONFLICT DO NOTHING`, and its audit entry. If a concurrent insert won the key,
   roll back to the savepoint — discarding this call's claims — reread the winner, and compare using the winner's
   stored key version: the same request returns the winner; a different one is a conflict.

- A durable source's refusal is kept as a `refused` request with its reason, never lost.
- A caller admitting several requests in one transaction (the matcher) admits them in workflow-id order, so
  admission locks are always taken in the same order.

### 7.3 Dispatch

`dewpoint dispatcher` (role `dewpoint_dispatch`):
- Before its transaction, it reads the current build (ABI, and instance capabilities — §2.7).
- It picks, per tenant, the oldest **due** `queued` request with `SKIP LOCKED`: FIFO among due requests, so one in
  backoff doesn't block those behind it.
- In the transaction, under the shared gate and tenant locks, it checks §2.3's critical conditions, executability
  (the defensive check), the ABI (`engine_abi_changed` cancels, audited), and a free slot; then it reserves the slot
  and marks the request `starting`.
- It starts `RunGraph` with id `t:<tenant>:run:<id>`, the payload encrypted by the codec, and `REJECT_DUPLICATE`.
- **The root's `runs` row is written before the start,** in the `starting` transaction, as 2a's `admit` does today:
  the worker's projection relies on it existing before any step row. Its `started_at` is set when the start is
  confirmed. While the request is `queued` or `starting` — a start still uncertain, or a request put back in the
  queue — every read path shows the **request's** status, never a run that may not exist; the run's own status is
  shown once the request is `started`. A request that goes `dead` fails its run with `start_failed`.

### 7.4 Refusals and uncertain starts

- **A confirmed refusal** — Temporal answered with a refusal status — is the only outcome that counts as an attempt.
  It backs off (5 s, doubling, capped at 10 min); after 10 such attempts the request goes `dead` and its run fails
  with `start_failed`, keeping 2a's rule that a start fails only when Temporal refused it. Slots and rows follow
  §7.8. Admins see dead requests; retrying one is a re-run (a new admission, §7.7), since terminal states never
  reopen.
- **An uncertain start** — a timeout, an unavailable service, a lost answer — counts as nothing. The request stays
  `starting`; the reconciler resolves it (§7.6).
- **Infrastructure checks** failing at dispatch leave the request queued without consuming an attempt (§2.5).
- **"Already started" is verified before it counts.** The dispatcher reads the existing execution's
  `WorkflowExecutionStarted` event and decodes its input with its own codec. Its tenant, run id, frozen version and
  request identity must all match the request; then the request is `started`. Otherwise it's an id collision, which
  the ids make impossible: the request goes `dead` with the reason `id_collision`, and an alert fires.

### 7.5 Slots

- `tenant_run_limits(tenant_id, max_concurrent)`: **default 5**, a platform setting, with per-tenant overrides.
  Raising the default toward 20 waits for capacity tests.
- `run_slots(tenant_id, run_id)`: one row per running root run, reserved under the limits row's lock.
- Sub-flows, batches and failure handlers run inside their root's slot.
- The root's end write, after its failure handler, deletes the slot in the same transaction.

### 7.6 The reconciler

Inside the dispatcher, with one leader chosen through an advisory lock:
- **Uncertain starts:** a request still `starting` may already have a running, or even closed, workflow whose start
  reply was lost. If a describe finds the execution, the reconciler verifies it as in §7.4, moves the request to
  `started`, and then, if the execution has already closed, maps its terminal outcome as for any started row
  (below). The request goes back to `queued`
  (same id, no attempt counted, but counted and alerted on) only after a **trustworthy absence**: a describe made
  after a grace period longer than the start call's own deadline returns `NOT_FOUND` from a reachable namespace. Any
  error keeps it `starting`, retried, and alerted past a threshold.
- **Leaked slots:** a slot is released only when the **latest execution of its logical run is terminal** — the
  reconciler follows continue-as-new to that execution first. An earlier execution that closed by continuing as new
  never frees its run's slot.
- **Rows left `running` whose workflow is closed** (rows whose request is `started`, including one just confirmed
  above; a row whose request is `queued` has no workflow and follows §7.8): it follows continue-as-new to the logical run's latest
  execution and records the outcome Temporal reports, releasing the slot in the same transaction:
  - `COMPLETED` → the decoded `RunResult` (the run's own end, which its end write should already have recorded);
  - `CANCELED` → `cancelled`;
  - `TERMINATED` → `failed` with `terminated`. An operator's termination stays `terminated`. A run Temporal itself
    terminated because a task's completion was too large (§5.2) is recorded as `internal_error` instead only if the
    server records a reliably distinguishable cause — for example the last failed workflow task's
    `GRPC_MESSAGE_TOO_LARGE` cause before the termination — and a test proves it; otherwise it stays `terminated`;
  - `FAILED`, or `TIMED_OUT` (Dewpoint sets no execution timeout, so it's unexpected) → `failed` with
    `internal_error`, and an alert.
- The synchronization that disabling the gate (§2.4) and erasing a tenant (§6.5) wait for.

### 7.7 The run API

- `POST /t/{tid}/workflows/{wid}/runs` — `run.start`, `Idempotency-Key` header, body `{input, mode, csv?}` → 202 with
  the request; 503 `production_runs_disabled` while the gate is off; 422 with locations; 409 on an idempotency
  conflict.
- `GET /t/{tid}/workflows/{wid}/start-form` — form metadata from the active version: the typed fields of
  `input_schema` (types, required, enums, defaults, which are sensitive and so masked), the CSV declaration (§8.1),
  and the reserved `x-dewpoint-picker` annotation for sub-project 3's pickers.
- `POST /t/{tid}/runs/{id}/cancel` — the new permission `run.cancel` (operators and above). A queued request is
  cancelled at once, audited. A running run gets a cancel request recorded, and the dispatcher sends it to Temporal,
  so the API has no Temporal client.
- Re-runs are new admissions on the active version. With the original input, they're offered only while its
  `run_inputs` are retained (§10.1), and the input is claimed again for the new request (§3.4).
- `GET /t/{tid}/runs` lists requests and runs together, by one stable sort key `(queued_at, id)`: a request's
  `queued_at` is when it was created, its run shares its id and `queued_at`, and a run from before 2b gets
  `queued_at = started_at` (backfilled). The paired cursor stays: `before` and `before_id`, given together or refused
  (422 `invalid_cursor`). The ordering change is documented.
- The dev CLI calls `admit_request` with the source `dev`.

### 7.8 Request, slot and row transitions

The dispatcher reserves the slot and writes the root's `runs` row **before** calling Temporal (§7.3), so every
transition out of `starting` says what happens to both, in the same transaction as the request's status:

| Transition | Cause | Slot | Pre-created `runs` row |
|---|---|---|---|
| `queued` → `starting` | dispatch | reserved | written (`running`, `started_at` null) or reused from an earlier attempt |
| `starting` → `started` | start confirmed, a verified duplicate (§7.4), or an execution the reconciler found and verified (§7.6) | never reserved again; the one reserved at dispatch is released by the root's end write | `started_at` set to the execution's start time if still null; a terminal status is never overwritten |
| `starting` → `starting` | uncertain start; the reconciler hasn't decided | **kept** until reconciled | unchanged |
| `starting` → `queued` | confirmed refusal with attempts left, or a trustworthy `NOT_FOUND` (§7.6) | **released** | kept, non-terminal, hidden behind the request's status |
| `starting` → `dead` | the 10th confirmed refusal, or `id_collision` | released | terminal: `failed`, `start_failed` |
| `queued` → `cancelled` | a user, `engine_abi_changed`, a retirement, tenant erasure | none held | if one was written by an earlier attempt: terminal, `cancelled` |
| — → `refused` | admission refused a durable source | none | none written |

- A row whose request never reached `started` is never shown as a run (§7.3), and it's always made terminal when
  its request is, so it can't stay `running` forever or escape retention (§10.1).
- Terminal states never reopen: a `dead` or `cancelled` request is retried only as a re-run.
- **Confirmation is idempotent and late-safe.** A fast run can finish — its end write making the row terminal and
  releasing the slot — before the dispatcher or the reconciler records `started`. Confirming then only sets the
  request's status and a null `started_at`: it never changes a terminal row, and it never reserves or recreates a
  slot.
- A cancel that arrives while a request is `starting` is recorded and applied when the start resolves: sent to
  Temporal if the run started, or as `queued` → `cancelled` if it didn't.
- An uncertain start holds its slot, so with a tenant limit of 1 nothing else of that tenant starts until the
  reconciler decides; a confirmed refusal or a trustworthy absence frees the slot at once.

## 8. Triggers (2b-3)

### 8.1 Manual input forms and CSV

- **Declaration:** `graph.settings.csv` — columns (header, variable name, type among `string`, `integer`,
  `number`, `boolean`, `mac`, `ip`, `cidr`, `enum`; required; default; sensitive), and `max_rows`/`max_bytes` at most
  the platform's 10,000 rows and 5 MB, which a tenant may lower. Publish derives the types of `trigger.rows` and `trigger.row_count`, and
  refuses defaults on sensitive columns.
- **Upload:** `POST …/csv-uploads` (`run.start`). The API parses the file as data only — UTF-8 with an optional BOM,
  the delimiter detected among comma, semicolon and tab, the caps enforced — and stages the rows encrypted in
  `csv_uploads`, owned by the user and tenant, expiring after one hour. The response gives the headers with exact
  matches mapped, a preview of the first rows with sensitive columns masked, and per-row errors as row, column and
  code, never quoting values. A mapping can be saved as the trigger's default.
- **Start:** `POST …/runs` with `csv: {upload_id, mapping, skip_invalid}`. Admission validates again, builds typed
  rows, claims sensitive cells with taint, then the rows list for size, so the list and its count stay untainted
  (§4.3's exception). The staged upload is consumed in the same transaction.
- **Stored encrypted, never in plain metadata:** the mapping and the file's header names (with the upload, then in
  `run_inputs`), and skipped rows' numbers and codes.
- **Audit keeps:** the file's tenant-keyed digest, the validation outcome as counts, and skipped-row counts. The
  original file isn't kept (deferred).
- **In the graph:** a loop over a size-claimed list loads each batch's slice through one page activity: untainted
  cells inline, sensitive cells as handles. Each row's outcome comes from the loop's iteration results in the
  projection.

### 8.2 Schedules

- `schedules` (tenant, workflow, cron or interval with a minimum of 60 s, time zone, fixed input encrypted with the
  purpose `schedule.input`, enabled) is the source of truth; the API writes it (permission `trigger.manage`).
- A sync loop in the dispatcher creates, updates, pauses and deletes the matching Temporal Schedules. Disabling a
  workflow or a schedule pauses it.
- The Temporal Schedule's action starts `ScheduleTick` with the schedule's id as its only argument (encrypted by the
  codec). Overlap: allow all. Catch-up window: 10 minutes by default, configurable.
- `ScheduleTick` is a one-activity workflow on its own task queue, `dewpoint-admission`, in the dispatcher process
  with the dispatch role. It's unversioned and holds no engine logic; a replay test keeps its short contract
  compatible.
- **The tick key** is `sched:<schedule_id>:<nominal time>`: the schedule's nominal time
  (`TemporalScheduledStartTime`, never the actual start or jitter), normalized to UTC at the precision Temporal
  reports — whole seconds (experiment 1), unique per schedule because intervals are at least 60 s and cron is
  minute-granular. `ScheduleTick` reads it once, deterministically, and passes it to its activity; retries reuse it; each
  caught-up time is its own tick. Experiment 1 must prove the attribute is deterministically available; if it isn't,
  the key is redesigned, never replaced by the actual start time.
- **Dewpoint never uses a schedule's trigger-now action.** Experiment 1 showed that triggers within the same second
  share a nominal time and a workflow id, so the tick key would collapse them. "Run now" is a manual admission
  (§7.7).
- **No tick is silently dropped.** Every tick calls `admit_request`, which records the request even while the gate
  is off. A disabled workflow or a paused schedule (a tick fired before the pause synced) produces a `refused`
  request with its reason. A tenant that's `erasing` produces an audited skip.

### 8.3 Webhook ingress

- **The process:** `dewpoint ingress`, with its own login (role `dewpoint_ingress`), reached at
  `/hooks/<endpoint_id>` and routed apart from `/api/`. The ingress role has no grant on `data_keys`.
- **Endpoints** (`webhook_endpoints`, managed with `trigger.manage`): an unguessable id; authentication by HMAC-SHA256
  with a timestamp tolerance, or by bearer token; an optional IP allowlist; a size limit (1 MiB default); a rate
  limit (token buckets in Postgres); where to find the event id (a JSON pointer or a header); an optional pointer to
  an array of events.
- **Secrets without tenant keys:** bearer tokens are high-entropy and stored as SHA-256 hashes. HMAC secrets, and
  each endpoint's dedupe-digest key (used when an event has no id), are encrypted under a separate ingress key,
  `DEWPOINT_INGRESS_KEY`, which only ingress and the API have.
- **Events are sealed to the tenant:** each tenant has an X25519 keypair for inbound events, its private key wrapped
  by the tenant's data key. Ingress reads only the public key, through `resolve_webhook_endpoint()` (SECURITY DEFINER,
  which also returns the endpoint's tenant — never taken from the payload), and seals each event (X25519 + HKDF +
  AES-256-GCM, with the tenant, endpoint and event id in the associated data). Each event records its keypair
  version. Only the dispatcher opens events.
- **Each request:** check size, IP, rate and authentication (constant time); split into events; in one transaction
  insert `inbound_events` (sealed payload; unique on `(tenant_id, endpoint_id, dedupe_key)`; `pending`); answer 2xx
  only after the commit. An `erasing` tenant is refused and nothing is recorded.
- **Bounded backlog:** pending events are bounded per endpoint (10,000 events, 64 MiB) and per tenant (50,000 events,
  256 MiB), all configurable. Past a bound, ingress answers 429 with `Retry-After` before inserting. An
  authenticated duplicate is a no-op acknowledgment even at quota, since it consumes nothing. Counters on the
  endpoint and tenant rows are kept under their row locks by insert, matching, cancellation and dead-lettering, and
  a periodic recount corrects drift.
- **Matching (dispatcher, only while the gate is on):** it claims a `pending` event with `SKIP LOCKED` and, in one
  transaction that it alone commits, calls `admit_request` (§7.2) for each matching binding (source `webhook`, key `evt:<event_id>:<workflow_id>`,
  the event as the trigger input) — each yields a frozen request or a `refused` one — and records the event's
  progress: `matched` with its request count, or `unmatched` when no binding matches. A crash before the commit
  leaves the event pending.
- **Bindings** (`trigger_bindings`): an endpoint, a workflow, and an optional filter of bounded, typed JSON-pointer
  equality on the event. No CEL.
- **Event outcomes:** `pending` → `matched`, `unmatched`, `cancelled` (an admin, singly or per endpoint, audited,
  counters released; or tenant erasure), or `dead`. `dead` is only for a confirmed event-specific, unrecoverable
  failure — its ciphertext fails authentication while its key version is present and works for other events; its
  payload isn't valid JSON — or an exhausted event-specific retry policy (5 attempts, backing off). A platform-wide
  failure (keyring or database unavailable, a missing key version) keeps the event pending with backoff and an alert.
  Admins see dead events and can cancel them.
- **Keypair rotation** keeps every private-key version that any retained event ciphertext still needs, or re-encrypts
  those events first.

## 9. Errors, statuses and codes

- **Run and step codes added:** `payload_too_large`, `snapshot_too_large`, `claim_unavailable`,
  `secret_index_limit`, `secret_index_unavailable`. `terminated` now also applies
  to a root run an operator terminated (recorded by the reconciler).
- **API errors added:** `production_runs_disabled` (503), `idempotency_conflict` (409).
- **Request statuses:** `queued`, `starting`, `started`, `cancelled`, `refused`, `dead`. Reasons include
  `engine_abi_changed`, `node_type_retired`, `cel_profile_retired`, `workflow_disabled`, `not_active`,
  `schedule_paused`, `input_invalid`, `secret_index_limit`, `start_refused`, `id_collision`, `user_cancelled`,
  `tenant_erasing`.
- **Event statuses:** `pending`, `matched`, `unmatched`, `cancelled`, `dead`.
- Every code is fixed and sanitized; none is derived from a sensitive value or plugin-supplied free text.
- Audit detail keys avoid the names `core/audit` rejects (`…code…`, `…secret…`, `…token…`): reasons are recorded as
  `reason`.

## 10. Retention and production (2b-4)

### 10.1 Tenant retention

- `tenant_retention.runs_days`: default **30**, set by tenant admins (`tenant.manage`) within platform bounds (1 to
  365).
- **The cutoff:** a run tree's data is due `runs_days` after its root became terminal; terminal requests and events
  count from when they ended.
- **At the cutoff, for users:** every user-facing read path — lists, run details, steps, sub-runs — stops returning
  that data at once (reads filter by cutoff, whatever the physical state). Re-runs with the original input and
  Temporal resets stop being supported: from then on the claims may disappear, and a reset execution that resolves
  a deleted claim fails that step with `claim_unavailable`, not retried.
- **Physical deletion within 24 hours after the cutoff** is an enforced operational SLO (§10.3).
- **What's deleted:** a terminal root's whole tree, found by root run id — `runs`, `run_steps`, `step_outputs`
  (spills, segments, snapshots), `run_inputs`, `run_secret_index`, `claim_grants`; terminal requests that never started (with their
  inputs); `matched`, `unmatched`, `cancelled` and `dead` events. Nothing of a non-terminal tree, and no `pending`
  event, is ever deleted. `csv_uploads` expire after one hour.
- **Never "exactly N days":** the spec and the guide describe retention by cutoff, visibility, deletion time and the
  backup exception.

### 10.2 What a tenant's retention can't reach

- Temporal histories — §4.6's visible metadata and codec-encrypted payloads — for the namespace's retention: **7
  days by default, at most 30** (platform policy). A tenant whose retention is shorter than Temporal's has histories
  that outlive its data; resets of them won't work.
- **Audit records:** a platform policy, `audit_retention_days` (default 400). The audit service prunes: it anchors a
  checkpoint at the last entry pruned, deletes older entries, and the verifier starts from the anchored checkpoint.
- **Backups:** the operator's policy; the guide recommends at most 35 days. Data removed by retention lasts in
  backups until they expire.

### 10.3 The retention job

- `dewpoint retention`: its own process and role, `dewpoint_retention` — `DELETE` on the retained tables plus the
  reads it needs. No other role gains `DELETE`.
- It deletes in batches, per tenant, under tenant scope, idempotently (a crash resumes). It writes one audit entry
  per tenant per sweep, with counts only, and records each sweep: start, end, success and **lag** (how far past its
  cutoff the oldest undeleted data is).
- **The SLO:** a successful sweep within the last 24 hours and a lag under 24 hours. A breach alerts and **pauses
  new production starts** (a dispatch-time critical check, §2.3) until retention recovers.
- Key retirement (§6.4) waits for retention or re-encryption.

### 10.4 Production Temporal

- A cluster whose server supports Worker Deployments — self-hosted with persistent storage, or Temporal Cloud.
- **Verified TLS always,** with the server's certificate checked against a configured CA or the system roots. Client
  authentication by mTLS (`DEWPOINT_TEMPORAL_TLS_CERT`, `…_KEY`, `…_CA`) or by an API key
  (`DEWPOINT_TEMPORAL_API_KEY`) sent over that TLS. An API key replaces the client certificate, never TLS.
- **One exception:** a `development` environment may connect without TLS when `DEWPOINT_TEMPORAL_INSECURE_DEV=true`
  (CI and local Compose on their isolated network). Every process refuses that setting unless the recorded
  environment is `development`, and warns at startup when it's used.
- Compose's dev server can never pass readiness; a Compose deployment runs production only against an external
  Temporal.
- The rollout guide gains these requirements, the minimum server version, and the drainage dynamic config.

### 10.5 Pending work and outages

Section 2.5 (the gate), §7.4 (dispatch) and §8.3 (events) share one rule: a platform-wide condition makes work wait
with backoff and an alert, without consuming attempts; only failures confirmed to belong to one request or event
dead-letter it.

### 10.6 Lifting the gate

`dewpoint platform enable-production-runs` checks, and audits with the results and the operator's attestation:
- the environment is `production`;
- Temporal: the namespace matches the recorded one; `DescribeNamespace` reports retention within bounds; TLS
  verification is active; the operator attests persistent storage;
- every live worker instance of the current build is healthy and holds `payload_codec`, `claim_check` and
  `cel_request_size_guard` (§2.7);
- the KEK and keyring wrap and unwrap;
- **every stored data key unwraps:** as the key-admin role, every version of every tenant's data key, and the platform
  key, is unwrapped with the configured KEKs. Comparing KEK ids (`dewpoint keys status`) isn't enough: a wrong KEK
  under the right id passes it;
- **the workers' path reads a tenant's key:** with the workers' own configuration (their database role and KEKs), for
  every tenant with a key, scoped to that tenant under RLS, its active data key is read and unwrapped — the codec's
  own path (`KeyringKeys`). The tenants come from the key-admin pass above, since the worker role can't list them;
- the dispatcher and reconciler have reported within the last 5 minutes;
- retention: a successful sweep within 24 hours with lag under 24 hours, and its defaults set.

## 11. Go/no-go experiments

Run before the 2b-1a plan, as throwaway code in the scratchpad, on the approved Temporal dev server and
`postgres:16-alpine`. **Every decisive result becomes a committed regression check, with the SDK and server versions
recorded, before 2b-1a ships.**
1. **Codec context.** A recording codec asserts, on every path, a context naming the expected tenant: client start
   and result; workflow ↔ activity on both sides; child start and result; signals both ways; continue-as-new;
   failures with encoded attributes; schedule create, describe and fire (prefixes); `Replayer`. It also proves that
   `TemporalScheduledStartTime` is deterministically available to `ScheduleTick`, under replay and catch-up.
2. **Size.** Whether the SDK's payload check sees the payload after the codec; a proven bound on the codec's
   overhead; what happens when one workflow task's completion passes the gRPC limit.
3. **Live state at the limits:** the structure's worst case at the in-flight caps; loops of 10,000 items with
   collection; 100,000 iterations per run; handle counts; nested loops; batch merges; structural growth with no
   merge; repeated continues; the history cost of spills. These set `SNAPSHOT_MAX` and the budget.
4. **Claim-routing cost:** the delay a tainted expression adds by going through an activity. A measurement, not a
   gate.

### 11.1 Results (2026-09-29)

Temporal Python SDK 1.33.0; Temporal CLI dev server 1.9.1 (server 1.32.0); the time-skipping test server for the
larger engine runs. Two tenants ran side by side throughout.

1. **Codec context — passed.** 339 codec calls, in the original runs and again through `Replayer`, all had a context
   whose workflow id named the right tenant, and every decode's metadata matched it: client start and result, and a
   workflow failure reaching the client; workflow ↔ activity on both sides, local activities (marked local) and
   heartbeats; activity and child failures with encoded attributes; child start and result; signals both ways;
   continue-as-new; a batch-style child id; schedule create, describe and fire.
   **Schedule time — passed, to the second.** `TemporalScheduledStartTime` is available to the schedule's workflow
   and identical under replay, for interval firings, backfills, and a real catch-up after 130 s of server downtime
   (the missed firings ran at restart with their own nominal times). Temporal truncates it to whole seconds, and
   schedule workflow ids use seconds too: three triggers within one second shared both (§8.2's rule). A backfill over
   an already-fired time produced a second execution with the same nominal time, which the tick key collapses.
2. **Size — the guard's premises hold.** The SDK checks each command's payloads **after** the codec: a payload of
   2,097,118 bytes before encoding passed the 2,097,152-byte limit once encrypted, and its workflow task then failed
   and retried about 23 times a second. The experiment codec's overhead was 103–105 bytes. The SDK warns above
   512 KiB. A workflow task whose completion passed the gRPC limit (4,194,304 bytes; three commands of 1.5 MiB, or
   five of 900 KiB) failed with the non-retryable `GrpcMessageTooLarge`, and Temporal **terminated** the workflow;
   two of 1.5 MiB completed (§5.2's invariant).
3. **Live state (today's engine, 2a) — measured; the bound is not yet proven.**

   | Scenario | Worst snapshot | What dominates |
   |---|---|---|
   | 100 pending timers | 24 KB | timers (12 KB) |
   | nested loops 100 × 100, activity bodies | 70 KB | collections (30 KB) |
   | a 10,000-item loop collecting integers | 99 KB | the items and collected lists (49 KB each) |
   | a 10,000-item loop collecting 60-byte values (a handle's size) | 713 KB | collected (663 KB) |
   | 10 loops of 10,000 in a row (100,000 iterations, 1,030 continues) | 540 KB | finished loops' outputs (440 KB) |
   | 100 open iterations of a 48-step parallel body | 665 KB | ready queue (269 KB), node states (245 KB), edge states (126 KB); values 5.7 KB |
   | the same with a 200-step body | over 2 MiB | the continue-as-new command failed its workflow task, which retried |

   On the saved 48-step snapshot, the index-based encoding of §5.3 gives 72 KB, and 36 KB with the ready queue
   rebuilt. §5.3's go/no-go still has to prove the bound on a prototype.
4. **Claim-routing cost.** Per evaluation, sequential, on the dev server with the codec: about 0 ms in the workflow,
   about 0.6 ms in a local activity, about 50 ms (p95 54 ms) in an activity. A loop of 10,000 iterations with one
   tainted expression each spends roughly 50 s in routing at concurrency 10. The editor explains this cost where it
   explains routing (§4.1).

These results become committed regression checks, with the versions above recorded, before 2b-1a ships: context on
every path, schedule time under replay and catch-up, the size check after the codec, and the per-task invariant.
2b-1a commits them in `backend/tests/apps/worker/test_temporal_contract.py`, on the CLI dev server; a test there fails
on any other SDK or server version, so an upgrade verifies them again.

### 11.2 The 2b-1b go/no-go (§5.3): results (2026-09-30) — promising, not yet a go

**Outcome: promising, not yet a §5.3 go.** A prototype passed every criterion of §5.3 on the workloads below. That
covers the workloads tested, not the bound §5.3 promises for every continued run that can occur. Five conditions
remain unproven, and two of them are counterexamples (below). The gate passes only once the encoded **whole**
continued-run input is proven to fit, by a focused follow-up or by a revision that offloads what doesn't fit.

**How it was measured.** A throwaway prototype of §5.3 (local branch `proto/2b1b-snapshot`, never merged): snapshot
format 2, the open-scope cap with its reservation, handle-backed loop items, compacted collections and failure lists,
and the live-state budget. Claims were a stub store on `postgres:16-alpine`. It gave the spill path the properties
it relies on: segments durable across worker restarts, immutable, idempotent (a second write must carry the same
content hash), and size-checked. It had no RLS, owners, grants or taint: those are implementation work. Versions:
Temporal Python SDK 1.33.0; the CLI dev server 1.9.1 (server 1.32.0) and the time-skipping test server; Python 3.12.
Every workload is a valid published graph (at most 500 nodes in the whole graph), run with low continue thresholds so
that it continues many times.

For every continued run, the probe recorded:
- the encoded continued-run input, as Temporal holds the payload, and its parts decrypted;
- the peak of open iteration scopes;
- whether each snapshot's scheduler, restored, encodes again identically;
- whether every history replays through the `Replayer`;
- whether the run completes within a fixed timeout: 900 s on the time-skipping server, 2,400 s on the dev server, and
  1,800 s for the value workloads on the time-skipping server.

**Measured passes (the workloads tested).**

| §5.3 criterion | Result on the tested workloads |
|---|---|
| Encoded snapshots within `SNAPSHOT_MAX` (1.5 MiB) | Worst encoded continued-run input 1.10 MB: a live state at the budget (1.05 MB), plus 57 KB of structure. Structural worst: 148 KB. |
| Repeated continues restoring identically | 3,424 continues. Each snapshot, restored, encoded again byte for byte, rebuilt the same queued work, and counted the same live state. |
| Deterministic ordering across replay | 5,404 histories replayed without nondeterminism. |
| Open scopes never above `OPEN_SCOPES_CAP + D` | Peaks of 100–102, with `D` of 2 or 3. The scheduler checks the bound on every open. |
| Progress, no deadlock | Every run completed within its timeout. Driven alone in an adversarial order (every loop opens before any step runs), the scheduler deadlocks at 100 open scopes without the reservation, and completes with it (peak 101 of 103). |

| Workload | Server | Continues | Worst encoded input | Peak open |
|---|---|---|---|---|
| A loop body at the node limit (498 nodes) | time-skipping | 205 | 30 KB | 10 |
| A 480-step body under nested 10 × 10 loops (483 nodes) | time-skipping | 197 | 148 KB | 100 |
| Loops nested 3 deep, 100 × 10 × 10 | time-skipping / dev | 51 / 48 | 42 / 41 KB | 101 |
| 20 sibling loops, each with an inner loop | time-skipping / dev | 97 / 74 | 51 / 52 KB | 102 |
| Combined structural case (342 nodes) | time-skipping / dev | 142 / 136 | 99 / 100 KB | 101 |
| A 10,000-item loop collecting integers | time-skipping | 103 | 167 KB | 10 |
| 10,000 handle-backed items of 60 bytes, collected | time-skipping / dev | 103 / 103 | 225 / 225 KB | 10 |
| 10,000 failing iterations with ~485-character messages | time-skipping / dev | 3 / 3 | 104 / 211 KB | 10 |
| 10,000 handle-backed items of 64 KiB, workers restarted mid-run | time-skipping / dev | 295 / 204 | 856 / 857 KB | 10 |
| 10 loops of 10,000 in a row (100,000 iterations) | time-skipping | 1,030 | 167 KB | 10 |
| Loops nested 3 deep, the innermost reading a 50 KB inline list | time-skipping / dev | 61 / 58 | 1.10 / 1.10 MB | 101 |
| Combined value case (233 nodes) | time-skipping / dev | 257 / 254 | 791 / 856 KB | 101 |

**Design additions the probe established.** §5.3 needs each of these to hold:
1. **Inline item lists spill under the budget.** A loop's list becomes segments, and the loop carries on over them as
   a cursor. Without this, the nested loops above hold one 50 KB list per open outer iteration, and the run fails
   `snapshot_too_large` at its first continue.
2. **The budget is enforced after every change,** not only where results merge. A step's result and a newly opened
   scope's item raise the live state too.
3. **Failure lists compact like collected values.** Without this, 10,000 failures hold about 5 MB inline.
4. **Snapshot format 2 records the units already handed out** (in practice, sleeping timers), and rebuilds what's
   queued from the node, edge and loop states. Storing the queues isn't needed.
5. **The reservation is one scope per nesting level, along the path of oldest open iterations.** From the execution's
   root, the path follows the oldest open iteration at each level. A loop on that path may open one iteration from its
   level's reserved scope. A shared pool of `D` scopes isn't enough: sibling loops on one level can exhaust it, and the
   next level deadlocks.

**Unproven conditions: before the gate passes.**
1. **The trigger, a counterexample.** A start may carry nearly 1.75 MiB of trigger (the 2b-1a payload limit), and
   every continued-run input carries it again, while that input must fit within 1.5 MiB. No compaction makes that
   continuation fit: today such a run fails `snapshot_too_large` at its first continue. The trigger needs a bound
   within the continued input, or it must be offloaded: claimed before the run starts (§3.5), with the continued input
   carrying only its handle.
2. **The fields outside the live-state budget** travel in every continued input, and nothing bounds their sum with
   the budget:
   - variables;
   - carried sensitive values (`SECRETS_BYTES`, 256 KiB, until claims);
   - a batch's outer scopes and item slice.

   Each needs a bound or a spill path, measured together with the budget.
3. **Segment-handle lists grow without a bound.** A compacted collection keeps about 20 bytes per segment outside the
   budget (about 50 KB at most in the workloads above). Nothing bounds it: small segments spilled under budget
   pressure can number in the tens of thousands. The proposed remedy, index segments (a list of segments spilled as a
   segment of its own), was not prototyped.
4. **Loops waiting on the cap, a second counterexample.** `OPEN_SCOPES_CAP` bounds iteration scopes, not loops. A
   loop step that has started holds its loop's state (about 200–400 bytes, its collections included) even while the
   cap keeps it from opening an iteration. Measured on the scheduler alone: 240 sibling loops in the body of nested
   10 × 10 loops (482 nodes) made 21,611 loops, 21,601 of them waiting on the cap, holding 4.5 MB of loop state.
   Either loops count toward the cap, or a loop step doesn't start until its loop could open an iteration; a waiting
   loop step then costs one state code.
5. **The whole input, encoded.** The bound to prove is on the entire encoded continued-run input:
   - the live-state budget;
   - the structure: at most `OPEN_SCOPES_CAP + D` scopes of node and edge codes, and the loop state that condition 4
     bounds;
   - every field in conditions 1–3;
   - the codec's overhead.

**Follow-up before the gate passes.** A focused probe with four workloads:
- a near-limit trigger;
- the fields outside the budget, combined;
- segment indexes that grow;
- many sibling loops under the cap.

The alternative is a revision that offloads these fields. Either way, the proof must show that the encoded whole
continued input fits `SNAPSHOT_MAX`. The 2b-1b task plan waits for it. Revision 5's §5.3 gives each condition a rule
and a worst-case maximum, and the follow-up tests those rules.

**Also measured.**
- **History cost:** a value that returns inline, and then leaves again as part of a collection's spill, crosses history
  twice. For 10,000 items of 64 KiB, that made 1.6–1.7 GB of history, of which 656 MB were spill inputs. The store
  held 1.3 GB (the items, then the outputs). Claiming outputs at the activity when the loop collects them would avoid
  the second pass.
- **Time:** 100,000 iterations took 576 s on the time-skipping server.
- **Numbers the tested workloads support:** `SNAPSHOT_MAX` 1.5 MiB, a 1 MiB live-state budget, `OPEN_SCOPES_CAP` 100,
  256 KiB segments, a 1 KiB floor, and a 64 KiB inline limit. They stay provisional until the conditions above are
  proven (§15).
- **Not prototyped, implementation work:** real claim permissions (RLS, owners, grants, taint), and the consumers of
  handles (CEL over a handle-backed item, references into a spilled collection or result). The workloads read only
  counts and handles.

### 11.3 The §5.3 follow-up: results (2026-09-30 to 2026-10-01) — go (the owner's decision, 2026-10-01)

**Outcome (2026-10-01): go for the focused §5.3 gate** (the owner's decision). The corrected 99,990-item case passed
on the target CI runner at `3215452`: all 1,999 continues met the bound, all 3,000 histories replayed, no task failed
and no activity timed out, and an activation took 757 ms of CPU at most. The other CI results stand; no full rerun
was needed.
- This approves revision 5's provisional §5.3 for implementation, not production readiness. The 2b-1b plan turns the
  prototype's guarantees into regression tests, and completes the work the prototype didn't (the end of this
  section).
- The unpinned-run fix (#22, #23) is separate: rollout correctness, not part of the size proof.

The findings below are the record that led there, in order, each with the verdict it had then.

**Earlier verdict (2026-09-30), kept as history: promising, not yet a §5.3 go** (the owner's ruling). A focused
prototype of revision 5's §5.3 passed every check below, on every workload, on both servers. Two conditions remained
before the gate passed: the at-continue budget term had to be an enforced invariant, and a workflow task's CPU had to
stay within engine-core's 1 s target at the structural maximum.

**How it was measured.** A throwaway prototype of revision 5's §5.3 (local branch `proto/2b1b-bound`, from §11.2's
`proto/2b1b-snapshot`, never merged), with §11.2's stub claim store and versions.
- Publish computes each version's cap and `D`, and pins them in the version. Each maximum is built as the largest
  encoding its component can have, with the prototype's own encoders.
- At every continue of every execution, the probe checked:
  - each component against its maximum: the envelope, the trigger, no learned sensitive values, the structure;
  - the live values: within `LIVE_BUDGET`, and the counter equal to a recount;
  - the whole encoded continued input against `SNAPSHOT_MAX`;
  - open scopes and started loops within the cap plus `D`;
  - the budget's waiting needs and grants;
  - that no failed scope was kept.
- Every snapshot restored and encoded again identically, every history replayed, and every run completed with the
  values its outputs read.

**Computed maxima.** `ID_MAX` 265 B, `HANDLE_MAX` 336 B, `ENVELOPE_MAX` 1,837 B, `TRIGGER_MAX` 65,872 B. The largest
graphs the limits allow (500 nodes, 2,000 edges, loops 3 deep, 63-character keys):

| Largest graph | `D` | Root loops | `ITER_SCOPE_MAX` | `LOOP_MAX` | Cap, revision 5's budget term | Cap, at-continue term |
|---|---|---|---|---|---|---|
| One loop, a 499-step body, 1,999 edges | 1 | 1 | 2,580 B | 524 B | 71 | 100 |
| Loops 3 deep, a 497-step body, 2,000 edges | 3 | 1 | 2,591 B | 550 B | 68 | 100 |
| 249 loop steps in one body | 2 | 1 | 1,078 B | 540 B | 100 | 100 |
| 250 root loops (a loop needs a body) | 1 | 250 | 88 B | 528 B | **none: 15,801 B over at cap 1** | 100 |
| 494 root `set_variables` steps | 2 | 1 | 91 B | 536 B | 100 | 100 |

With every container claimed, the live state needs at most 660,576 B (250 root loops at cap 100): under `LIVE_BUDGET`.

**Workloads.** Every run succeeded with the values expected, with no check failed.

| Workload | Continues (time-skipping / dev) | Worst encoded input | Longest workflow task (dev) |
|---|---|---|---|
| A 1.69 MB trigger, claimed to its envelope before the start (141 B travelled) | 20 / 20 | 4 KB | — |
| Every container of component 5: variables claimed, collected values, 416-436 results claimed at merge | 38 / 33 | 1.05 MB | — |
| A batch's frozen results claimed | 1 / 1 | 332 KB | — |
| Scope items claimed, and read through their handles | 3 / 3 | 1.04 MB | — |
| Segment lists claimed as index segments (6 loops of 10,000, 1 KiB segments as a stress) | 612 / 743 | 1.02 MB | 1,022 ms |
| 240 sibling loops in nested 10 × 10 loops (§11.2's counterexample 4) | 433 / 387 | 109 KB | 741 ms |
| Root `set_variables` steps settling while 18,000 loop steps wait | 363 / 324 | 93 KB | 623 ms |
| 240 sibling loops of 3 items, `on_error: continue` (see the correction below) | 653 / 586 | 110 KB | 1,148 ms |
| The same as a sub-flow (see the correction below) | 652 / 589 | 110 KB | 861 ms |
| A batch slice of 0.97 MB inline, and one claimed by its parent | 1 / 1 | 36 KB | — |
| References through 400 characters of keys (a derived claim), chained handles, a spilled collection | 21 / 21 | 33 KB | — |

- Started loops inside iterations stayed at most 100; §11.2 measured 21,611.
- Queued loop steps read the variables they became ready under. Under a cap of 3 and of 100 they read the same;
  17,993 of them would have read otherwise at start.
- No queued loop step started while the budget waited, and every one started or settled: measured on the scheduler
  alone, with the root's budget at 610 and a child's at 0 (19,032 loops refused at their first iteration).
- **Correction (2026-10-01).** The two rows above were meant to exhaust the budget on Temporal, but didn't. The
  probe lowered the root's cap through its own module, and `workflow.py` reads a copy of that module inside the
  sandbox, so these runs had the normal cap. Once the cap reached the run (through a module the sandbox passes
  through), an exhausted budget drained 21,600 queued loop steps in one workflow task, and the SDK's deadlock
  detector stopped it at 2 s. That is the CPU condition below.
- Driven alone at 24,010 loop steps, the scheduler's worst snapshot was 105 KB; §11.2 measured 4.5 MB.

**What the follow-up established.** §5.3 needs each of these to hold:
1. **A capture is two characters per loop step, by position in its scope's record.** A list of captures cost
   432 KB at 21,600 queued steps.
2. **Kept versions are one undo record per write:** what the write replaced. A version needs the records after it.
   A delta per version grows quadratically.
3. **A batch-mode loop inside an iteration holds its slot until it finishes.** It opens no scope, so otherwise
   started loops aren't bounded by the cap.
4. **Merges being authoritative, containers are claimed on other growth:** variables, collected values, items,
   opened scopes. Results passing the budget are claimed at the merge instead.
5. **A size claim may hold up to the payload limit.** A trigger's claimed subtree reached 1.68 MB.
6. **A batch slice near 1.75 MiB can't arise.** The parent's budget claims an inline item list before any batch is
   cut. The follow-up ran the reachable edges instead.

**Before the gate passes (the owner's rulings).**
1. **The at-continue budget term is accepted in principle.** A snapshot taken only after child grants and pending
   needs have cleared needn't count them.
   - Revision 5's term counts `2 × IN_FLIGHT_CAP` needs and `IN_FLIGHT_CAP` grants. Under it, 250 root loops get no
     cap.
   - Measured zero isn't the invariant. The quiescence check must require that the budget hold no waiting need and
     no child's grant. The snapshot must refuse otherwise, and a regression must fail if either survives.
   - Only then do they leave the continued-input formula. The budget's fixed counters and `Parent.grant` stay
     counted.
2. **A workflow task's CPU blocks the gate.** The longest task took 1,148 ms at 21,600 queued loop steps, past
   engine-core's 1 s target (§5.6 there). The SDK's deadlock detector (2 s) fired once in a replay, under four
   concurrent probes.
   - Snapshot, restore and the first take after a restore need deterministic chunking or yield points.
   - The 21,600-queued-step workload then runs again on the dev server and on Linux, under representative
     concurrency.

**The conditions, checked (2026-10-01): promising, the gate still open.**
1. **The at-continue budget term: approved by the owner, and §5.3 revised.** The prototype enforces it at both
   points, and both checks stay in the implementation:
   - the quiescence check requires no waiting need and no child's grant;
   - the snapshot refuses to be taken otherwise;
   - a need left undecided when nothing else runs is decided before the execution continues.

   Regressions fail if either check is removed (`test_proto_continue_budget.py`, watched failing first). At every
   continue measured since, waiting needs and grants were zero. With the fixed counters in the envelope, every
   largest graph gets cap 100; 250 root loops keep 284,707 B of headroom at cap 1.
2. **A workflow task's CPU: much better, not yet settled.** The probe found three causes:
   - **Scans of the whole queue.** Every pruned iteration scanned all 21,600 captures. They're now found through
     the queues that hold their steps, versions are reference-counted, and the relief is computed only past the
     budget.
   - **Snapshot, restore and the first take.** They now run in parts, each part charged to the workflow task in
     units weighted by their measured cost. Past the task's share (`YIELD_STRUCTURE`, 200,000 units, a tenth in an
     execution's first task), the next part waits for the next task behind §5.6's 1 ms durable timer. A restore defers
     its queued loop steps as it goes, so the first take after it does no deferral.
   - **An exhausted budget drained every queued loop step in one task.** Each loop step started, was refused and
     settled in the workflow, with no command to end the task, and the deadlock detector stopped it at 2 s. Each
     step unit now charges its work and its view's size before it starts, and a take takes only what the task's
     share allows.

   Measured at 21,600 queued loop steps:
   - The scheduler alone, on macOS and in a Linux container on the same machine: a snapshot takes 14-16 ms, a
     restore 123-133 ms over three tasks (at most 98 ms in one), and the first take after it 0 ms.
   - On the dev server, the longest workflow task in wall time, with no check failing:

     | Runs at once on one worker | macOS | Linux container |
     |---|---|---|
     | One, an exhausted budget (run to its end, 19,032 loops refused) | 401 ms | 437 ms |
     | One, 240 sibling loops | 397 ms | 500 ms |
     | Four, an exhausted budget | 2,445 ms (5 of 5,907 tasks past 1 s) | 2,477 ms (4 of 6,161) |
     | Four, 240 sibling loops | 2,227 ms (4 of 7,884) | 2,511 ms (5 of 8,035) |
     | Four, the worker at 2 workflow-task slots | 1,347 ms (1 of 5,808) | 1,385 ms (1 of 5,887) |

   - No workflow task failed, apart from one `UnhandledCommand` among four concurrent Linux runs that the probe
     cancelled.
   - A worker at 1 slot hung; that wasn't investigated.

   Engine-core's 1 s target is CPU time. A task's wall time under contention isn't itself a failure, but it leaves
   the SDK's deadlock risk open, given the earlier detector event and gate 7b's slower CI runner.

**Before the gate passes (the owner's ruling, 2026-10-01).** The 2b-1b plan doesn't start until these pass:
- **The CI runner.** The heaviest queued-state case runs on the target Linux CI runner, with the intended worker slot
  count and representative concurrency. It measures each task's CPU time and the cause of every failed task.
- **Complete runs.** The long runs complete, and every history replays, with the new yield logic: not only their
  first 40 continues.
- **The `UnhandledCommand`.** Its coincidence with the probe's cancel is verified, not assumed.

**The CI runner, complete runs, and the `UnhandledCommand` (2026-10-01): promising, the gate still open.**
- **Two more changes, from what the runs showed:**
  - A version's program is compiled once per worker process, keyed by its id and its content. Compiling a 482-node
    version took 0.3-0.5 s on macOS and 0.5-0.75 s on the CI runner, in the first task of every execution and every
    continue.
  - A step unit and a take are charged against a task's whole structural share. An execution's first task keeps its
    tenth for a restore: with a tenth, a fresh run started only 13 of its first 100 steps before yielding.
- **The target Linux CI runner** (GitHub's ubuntu-latest, x86_64, 2 vCPUs). The engine worker ran at 2 workflow-task
  slots, the slot count intended. The heaviest queued-state cases ran to their end, and every history replayed. The
  probe timed each activation's CPU (the thread's) and wall time:

  | Runs at once | CPU per activation, max (p99) | Wall per activation, max | Failed tasks |
  |---|---|---|---|
  | One, an exhausted budget | 871 ms (174) | 872 ms | none |
  | One, 240 sibling loops (441 executions) | 879 ms (210) | 890 ms | none |
  | Four, an exhausted budget | 899 ms (233) | 1,529 ms | none |
  | Four, 240 sibling loops (1,701 executions) | 907 ms (387) | 1,657 ms | none |

  - Every activation stayed within engine-core's 1 s CPU target, the worst at 907 ms. With one run, a single
    activation passed 500 ms: the version's first compile, once per worker process. The scheduler alone at 21,600
    queued steps: a snapshot took 21 ms, a restore 221 ms over three tasks (at most 155 ms in one).
  - Without the program cache (the commit before), four runs of 240 sibling loops reached 1,308 ms of CPU in one
    activation, and 87 activations passed 1 s.
- **Complete runs on macOS, every history replayed.** These ran on the dev server, at 2 slots, with the final code:
  - 240 sibling loops: 409 executions;
  - root writes while loop steps wait: 329;
  - an exhausted budget: 27;
  - the same as a sub-flow: 40.

  No check failed and no task failed. CPU per activation was at most 369 ms.
- **Overload, at 2 slots: open.** Segment indexes that grow (6 loops of 10,000 items, about 600 batch children and
  60,000 small claims) overloaded one worker process at 2 slots: its workflows and all its activities.
  - Claim activities timed out (53).
  - The deadlock detector fired once.
  - The run hadn't ended after 1 h 40 min, and was stopped.

  At the SDK's default slots, the same run completed in 407 s, with every history replayed. The detector fired once
  there too, on an activation of 306 ms CPU and 2,022 ms wall: time spent waiting for the interpreter's lock, not
  computing. The deadlock risk follows a worker's load, its activities' included. Sizing workers is the 2b-1b plan's,
  with this case as its test.
- **The `UnhandledCommand`: not verified.**
  - Its histories weren't kept.
  - The same configuration, run three more times, produced no failed task. So did every complete run, which the probe
    never cancels.
  - In that workload, the probe's cancel is the only event from outside: no child, no signal, nothing outstanding at a
    continue. That fits a cancel arriving as a task completes, but it isn't verified.
  - The probe now records each failed task's events and the cancel's time, so a recurrence can be checked.

**Segment indexes and the `UnhandledCommand`, again (2026-10-01): promising, the gate still open.**
- **The 1 KiB stress, corrected (the owner's review).** An earlier version of this record said the stress makes at
  least as many segments as any reachable state, because it seals every tail at 1 KiB. That reasoning was wrong:
  its own estimate of about 2,000 competing containers allows segments smaller than 1 KiB, near `HANDLE_MAX`
  (336 B).
  - Under §5.3's rules, a collection's tail becomes a segment at `SEGMENT_BYTES` (256 KiB). Under budget pressure, it
    becomes one earlier, when it's the largest container that can be claimed (past `HANDLE_MAX`).
  - A segment holds at least one collected item: an empty tail isn't claimed. So a collection has at most one
    segment per item, and a run at most 100,000, its iteration cap. Smaller segments can't outnumber the items.
  - With items of 1 KB, the stress already makes one segment per item. What the 60,000-item workload didn't reach is
    the number of items. A second workload does: 10 loops of 9,999 items, 99,990 segments, the most a run can make.
- **One worker configuration completes it:** the engine worker at 2 workflow-task slots, with the SDK's default
  activity slots, in a process of its own. The workload: segment indexes that grow (6 loops of 10,000 items, about
  600 batch children, 60,000 claims). Each continue was checked against the bound, and every history replayed.

  | Where | Time | Continues | Histories replayed | Failed tasks | Activity timeouts | Activation, max CPU / wall |
  |---|---|---|---|---|---|---|
  | The CI runner | 950 s | 1,181 | 1,782 | none | none | 833 / 833 ms |
  | macOS, a fresh process | 308 s | 906 | 1,507 | none | none | 311 / 323 ms |
  | macOS, the same process again | 307 s | 908 | 1,509 | none | none | 445 / 467 ms |

  The run that crawled earlier ran fifth in one long-lived harness process, after four heavy workloads. That wasn't
  reproduced: run alone, or twice in a process, it completed cleanly. Its cause is observed, not explained. It stays a
  worker-lifecycle risk for the 2b-1b plan, which owns worker sizing; it isn't evidence that sizing is settled.
- **A controlled cancellation race.** 40 runs continue every second or so, each cancelled at a seeded random moment.
  40 more are never cancelled.
  - With cancels: one `UNHANDLED_COMMAND`, on the CI runner and on macOS alike. In both, the event right after the
    failed task is the run's cancel request.
  - Without: no failed task, over 195 continues on the CI runner and 184 on macOS.
  - So an unhandled command is a cancel arriving while a task completes with a command that closes the run. The server
    rejects that completion, and the run then sees the cancel.
  - The original one stays unattributed: its histories weren't kept.
  - **The narrow cancellation exception (approved by the owner).** A failed task is permitted only in a run the probe
    intentionally cancelled, when that run's next history event is `WORKFLOW_EXECUTION_CANCEL_REQUESTED` and the run
    settles as cancelled. Any failed task in a run that wasn't cancelled, or one that doesn't match these conditions,
    fails the check. The original failure stays unattributed.
- **Acceptance is enforced, and the gate waits for one rerun (the owner's ruling).** The probe printed failed checks
  and statuses without failing its process, and the cancellation probe swallowed errors from a run's result. Every
  acceptance condition becomes an assertion, and the process exits non-zero on any of these:
  - a run that doesn't settle as expected;
  - outputs that differ;
  - a failed check against the continued-input bound, or no continue checked;
  - a failed replay, or an activity timeout;
  - a failed task the exception doesn't excuse.

  A cancel counts as landed only when the run's history records it: this server accepts a cancel of a run that has
  already completed, and records nothing. A landed cancel may still end in a completed run, as engine-core §8 says,
  when it comes while the run's end is being written: after it, nothing but the end's projection is scheduled. Any
  other completion after a cancel fails the check. The focused gate is called a go only after a CI rerun passes
  these assertions.
- **The enforced race found an engine bug, outside §5.3, fixed in the prototype (2026-10-01).**
  - Locally, the assertions failed: cancelled runs were still running at the wait. That was 2 of 24 landed cancels in
    one race and 4 of 25 in another; two of those four ended cancelled, after 70 s and after 3 minutes.
  - Their histories: after the cancel, the end's projection was scheduled but didn't start for minutes. Meanwhile the
    run had hundreds of workflow tasks that recorded nothing (586 and 1,086).
  - The cause is the worker's configuration, not §5.3. The SDK's core completes a workflow task by itself when it has
    nothing new for the workflow, such as the task after an unstarted activity's cancel is recorded. That completion
    reports the worker's default versioning behaviour, and the engine worker had none. Temporal then took the run as
    unversioned. Each start of its next activity, on the run's own build, began a deployment transition instead, and
    brought another such task. The activity started only when some other event reached the workflow.
  - The fix: the engine worker's deployment config sets `PINNED` as its default. A dev-server regression test cancels an
    unstarted activity and then needs another one. Without the default, a task reported no behaviour and the run hung;
    with it, the test passes.
  - With the fix, the local race (40 runs, 27 landed cancels): every cancelled run settled cancelled, the one
    `UNHANDLED_COMMAND` matched the exception, and every history replayed.
  - Main has the same configuration. There, any cancel of an unstarted activity, a run's cancel or a scope's end, can
    unpin a run, and during a rollout an unpinned run could move to another build, against §7.
  - It's a rollout-correctness issue, not part of §5.3's size proof (the owner's ruling). It's tracked as #22 and
    fixed from `main` by #23, which ports only the default and its regression test.

**The enforced rerun (2026-10-01): every condition passed, then the owner's go.**
- **On the CI runner** (2 vCPUs, the engine worker at 2 workflow-task slots, every acceptance condition asserted,
  every run to its end and every history replayed):

  | Workload | Runs | Executions replayed | Activation, max CPU / wall | Failed tasks | Result |
  |---|---|---|---|---|---|
  | The scheduler alone, 21,282 queued loop steps | - | - | decode 174 ms per task | - | - |
  | Queued state, an exhausted budget | 1 | 30 | 754 / 766 ms | none | passed |
  | Queued state, 240 sibling loops | 1 | 440 | 673 / 681 ms | none | passed |
  | Queued state, an exhausted budget | 4 at once | 108 | 768 / 1,066 ms | none | passed |
  | Queued state, 240 sibling loops | 4 at once | 1,670 | 811 / 1,352 ms | none | passed |
  | Segment indexes, 60,000 items | 1 | 1,640 | 647 / 650 ms | none | passed |
  | Segment indexes, 99,990 items | 1 | 2,971 | 638 / 638 ms | none | **failed: live 1,058,838 B** |
  | Cancellation race, 40 cancelled and 40 not | 80 | 313 | - | none | passed |

  No activation took a second of CPU, and none came near the 2 s deadlock detector. In the race, 37 cancels landed:
  36 runs settled cancelled and one completed as a late cancel; every run not cancelled completed.
- **The 99,990-item failure was a prototype bug, now fixed.** A loop's segment index passed `LIVE_BUDGET` and its claim
  was decided, but a drain neither took nor started claims. So the run continued with the index still live: 10.3 KB
  over the budget on the CI runner, 5.8 KB on macOS. That's under `SNAPSHOT_MAX`, but past what §5.3 counts.
  - The fix: a drain takes and starts claims, since they only shrink the state. An execution isn't quiescent while its
    live state is over the budget, and a snapshot refuses that state, as it refuses a waiting need or a child's
    grant. Two tests cover it, and they failed before the fix.
  - With the fix, on macOS, the five correctness workloads ran in parallel, to their ends, and passed. The
    99,990-item one had no violation over 1,763 continues; its worst snapshot was 1,012,698 B.
  - **The corrected run on the CI runner (run 36928968433), the owner's condition:** the 99,990-item workload alone,
    with the fix, every acceptance condition asserted, activation CPU included. It passed (the run 29 minutes, the
    whole check 39):
    - the run succeeded with the expected outputs;
    - 1,999 continues checked against the bound, with no violation, the worst snapshot 1,039,069 B;
    - all 3,000 histories replayed;
    - no failed task and no activity timeout;
    - activation CPU at most 757 ms, and wall time at most 760 ms, over 22,906 activations.

    The earlier CI results stand for the other cases (the owner's ruling).
- **How the checks run from now on (the owner's ruling).** Correctness runs locally, in parallel. The CI runner
  measures only what needs it, a task's CPU at the heaviest queued state, in about 10 minutes, and only on request.
  Full runs on it are for milestones.

**Not prototyped, implementation work:**
- a loop over a claimed list that isn't handle-backed;
- CEL and templates over handles;
- defaults through a handle;
- a frozen scope telling a missing result from a claimed one;
- the undo record's claim (records stayed under `HANDLE_MAX`);
- claim permissions.

## 12. Testing

Beyond each task's own tests:
- **Canary secrets** — the main end-to-end proof: runs seeded with known secrets have their entire decoded history,
  projections and logs scanned; no secret may appear. 2b-1a's part: no execution of a canary run (its sub-flow, its
  batches, its `cel.evaluate` requests and local activities) holds the canary in its raw history. 2b-1b's part: a
  canary in the trigger and one a plugin outputs at a sensitive position, carried through plugin steps, the evaluator,
  a sub-flow, batches, a filter, a spill, a failure message and a crash, appear in no decrypted history, projection or
  log line; and a secret a plugin makes and leaks before it's claimed appears in none of them either: in its `ctx.log`
  event, field names and values (no log line), in a crash's text, its class's name or its traceback's line (no
  history, row or log line),
  and in a failure's message or code, shaped as a valid identifier included (no history, row or log line) (§3.7,
  §6.7).
- **Properties:** the taint analysis (no tainted path is routed locally; plain output appears only at listed sites);
  the splitter (nothing plain at sensitive or undeclared positions; nesting follows the claiming order); forged
  handles refused.
- **Codec fail-closed:** no context, the wrong tenant, mismatched metadata, key rotation, replay with fixture keys.
- **Golden histories** per merged ABI (abi5, abi6), recorded encrypted with fixture keys, replayed by the replay
  gate; `ScheduleTick`'s replay test.
- **Fault injection:** admission and dispatch races, the gate-off race, erasure, uncertain starts, duplicate-id
  verification, the reconciler's outcome mapping on the dev server, matching interrupted by a crash.
- **Every transition of §7.8,** with a tenant limit of 1: a confirmed refusal frees the slot and another request
  starts; a refusal followed by a cancellation leaves the row terminal and no slot held; an uncertain start holds the
  slot until reconciled, then frees it on a trustworthy absence; the 10th refusal and an `id_collision` each leave the
  row `failed` and the slot free; none of these rows stays `running`, and retention deletes them after the cutoff.
  **A fast completion before the reply:** a run that completes and writes its end while its start reply is lost or
  late — confirmed later by the dispatcher or by the reconciler — leaves the request `started`, the row terminal with
  its own outcome, and no slot held.
- **Triggers:** CSV parser fuzzing; ingress authentication, replay tolerance, quotas and sealing; ingress load tests
  (parent §12).
- **Size invariants:** no workflow task's commands pass the per-task byte budget, at the largest configs, fan-outs
  and spills; an outgoing payload over the limit fails its step, loop or run (2b-1a) or is spilled (2b-1b), never a
  retried task; a result over the limit fails where it's produced; if the
  `TERMINATED` classification of §7.6 is adopted, a test proves it on the dev server.
- **Retention:** cutoffs on every read path, the SLO pause, audit pruning's checkpoint.
- **RLS and roles:** the RLS matrix over the new tables and roles; the authorization matrix over `run.start`,
  `run.cancel`, `trigger.manage` and `workflow.declassify`.

## 13. Changes to earlier specs

Each plan updates the older specs as it lands, as the engine-core 5.x revisions did. This spec is the authority for
2b in the meantime.
- **Parent spec:** §6.1's workflow id (`t:<tenant>:run:<run_id>`, §6.1 here) and its idempotency and lookup rules;
  the `outbox` replaced by `run_requests` (§7.1); §6.5's claim check detailed by §3–§5; §15's open defaults settled —
  5 concurrent root runs per tenant, 30 days of tenant retention, 7 days of Temporal retention (at most 30).
- **Engine-core spec:** the "hard rule until 2b ships" (lifted by §10.6); §9 (starting runs: admission and the
  dispatcher); §8 (the new codes, the cutoff on read paths, the `(queued_at, id)` ordering); §4.5 (dispatch as §7.3
  describes it); §5.6 (the per-task byte budget); §6 (claims, handles, the live-state budget, snapshots in
  `snapshot_format` 2, the open-iteration cap); §7 (ABI 5 and 6, ids).

## 14. Roles, tables and permissions (summary)

- **New tables:** `platform_settings`, `worker_instances`, `run_inputs`, `step_outputs`, `claim_grants`,
  `run_secret_index`, `run_requests`, `tenant_run_limits`, `run_slots`, `csv_uploads`, `schedules`,
  `webhook_endpoints`, `trigger_bindings`, `inbound_events`, `tenant_event_keys`, `tenant_retention`,
  `retention_sweeps`. `tenants` gains a status (`active`, `erasing`). `runs` gains `queued_at` (existing rows
  backfilled from `started_at`), and `runs.started_at` becomes nullable with no default: existing rows keep their
  values, a row pre-created at dispatch has none until the start is confirmed (§7.8), and every read path and the
  cursor order by `queued_at` (§7.7). 2b-1's `admit` keeps setting `started_at` as it does today.
- **Roles:** `dewpoint_dispatch` gains `SELECT` on `data_keys` and the admission tables; `dewpoint_ingress` gets a
  login and only `resolve_webhook_endpoint()` plus event inserts and counters; `dewpoint_retention` is new; the
  worker gains the claim tables and `worker_instances`. The plans give the exact grants.
- **Permissions:** `run.cancel` (operators and above), `trigger.manage` (editors and above), `workflow.declassify`
  (admins and owners).
- **Processes:** `dewpoint dispatcher` (dispatch, reconciler, schedule sync, `ScheduleTick` worker), `dewpoint
  ingress`, `dewpoint retention`, alongside the API and the worker.

## 15. Provisional values

These numbers are starting points. Each stays provisional until the go/no-go experiments (§11) or the owning plan's
measurements establish it; the spec is revised with the measured value when that plan lands.
- **Measured before they're final:** the outgoing-payload limit (1.75 MiB) and the codec-overhead bound (§5.2: 256
  bytes, which a test proves for `TenantCodec`; the experiment's codec added 103–105); the bound on carried sensitive
  values (256 KiB, §5.2); the key cache's TTL (5 minutes, §6.4); the
  per-task outgoing-byte budget (3 MiB under a 4 MiB gRPC limit, §5.2); `SNAPSHOT_MAX` (1.5 MiB), the live-state
  budget (1 MiB), `TRIGGER_INLINE` (64 KiB), `SEGMENT_BYTES` (256 KiB) and `OPEN_SCOPES_CAP` (100, the most a
  version's derived cap may be, §5.3); a handle's `POINTER_MAX` (256 bytes, §3.2); the
  spill floor (1 KiB, §5.4); the secret-index bounds (100,000 strings or 8 MiB, §3.7).
- **Operational intervals:** worker health every 30 s, live for 90 s (§2.7); dispatcher and reconciler reports
  within 5 minutes (§10.6); the retention SLO's 24 hours (§10.3).
- **Configurable defaults** (policy, not measurement): 5 concurrent root runs per tenant, raised only after capacity
  tests (§7.5); dispatch backoff 5 s doubling to 10 min and 10 confirmed refusals (§7.4); ingress quotas of 10,000
  events and 64 MiB per endpoint and 50,000 events and 256 MiB per tenant (§8.3); 5 event-specific retries (§8.3);
  the schedule catch-up window of 10 minutes and the 60 s minimum interval (§8.2); retention of 30 days for tenant data,
  7 days (at most 30) for Temporal, 400 days for audit (§10).
