# Editor UI 4d-1: simulating a draft and a single step (design)

Status: the design the owner accepted in chat on 2026-10-12 and 2026-10-13, section by section, with the D8 mockups
signed off at canvas version 20. This is D14's "separate engine design" (outline D14; ledger: "Execution, provenance
and retention semantics are settled before B8"). Base: `origin/main` d4ab0dbe (ENGINE_ABI 7; migrations to 0065, plus
0070).

Sources: the editor outline (`docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`: §2 4d, §5 B4b and B8, D2, D3,
D12, D14), the editor ledger (`docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`), the engine-core and engine 2b
specs, the architecture spec §10.1 and §10.4. The mockups are the Design canvas "4d-1 Simulation Mockups", version 20
(16 boards, each in light and dark, and two true 320 px boards).

## 1. What 4d-1 is

- **Simulate workflow** runs the draft as it stands, with input the person gives, and shows the result on the canvas
  and in a Simulation panel.
- **Simulate step** runs one step of the draft alone, with the values it reads supplied by the person, from the step
  drawer's Test tab.
- Every result says "Simulated · nothing was sent · results don't prove the live call will succeed". Each step carries
  a data-origin tag. The server's checks are listed apart. Simulated results are slate with the hatch (D2), never live
  orange (D3).
- Nothing in 4d-1 sends anything: live single-step testing is 4d-2's (B9).

Out of scope: simulating with a CSV file (D-b7: a draft whose input declares a CSV can't be simulated whole in 4d-1);
the runs list and run pages (4e); simulating a published version from the editor (the run form, 4e); B9.

## 2. Three plans, one design

| Plan | Contents | ABI | Migration |
|---|---|---|---|
| 4d-1a, engine | B4b (§3), simulated attempts and flow timers (§4), S2's engine part (§5) | 8 | 0071 |
| 4d-1b, backend | B8: draft snapshots, admission, execution path, readers, the reads the UI needs (§6) | none | 0072 |
| 4d-1c, UI | the screens of §7, built against the signed-off boards | none | none |

Each plan has its own branch and PR, stacked as before (D26). 4d-1b needs 4d-1a merged (S2's seeds and the ABI-8
statuses); 4d-1c needs both.

The migration slots are the ledger's: 0071 (B4b) and 0072 (B8). #90 (2b-4b) merged with its own 0048-0065, chained 0044
→ 0047 → 0045 → 0070 → 0048 → … → 0065. Both new migrations follow #90's rules: the online-migration
helper (`backend/migrations/online.py`), grants last, and the privilege reference
(`backend/tests/qualification/reference_rights.json`) regenerated.

## 3. B4b: every step instance's end (4d-1a)

### 3.1 The guarantee

- Every instantiated step in each opened scope has terminal coverage. A scope is the root or one opened loop
  iteration; there is no separate scope row (D-a4).
- Rows stay unique on the existing key `(run_id, step_id, iteration_key, attempt)`. A retried step has one final row per
  attempt. Completed outcomes are never replaced.
- No row is ever made up for a loop iteration that never opened, nor for a dead loop's body, which is never
  instantiated.
- Projection retries are idempotent (§3.4).

### 3.2 Statuses

`run_steps.status` gains two values: `running | succeeded | failed | cancelled | skipped | not_started`.

- `skipped`: the instance was on a branch not taken (branch elimination: `_check_ready` marks it dead when every
  incoming edge is resolved and none is live).
- `not_started`: the instance never began, and was discarded by a scope failure, a stop or fail step, a cancel or the
  deadline: waiting, ready, deferred, or handed off but unstarted.
- `cancelled`: started work that was stopped, control steps included (today `_queue_settled` writes control rows only on
  success or failure).

The classification is made where the instance changes state: branch elimination, `_fail_scope`, stop and fail steps,
cancellation, and `end()` (which clears the queues without `_fail_scope`). It never rests on `NodeState` alone:
`RUNNING` also means queued. It reads the queues, `_handed`, the execution's `_started` and the open loops. Timers
cancelled for a continue-as-new are never recorded as `cancelled`: they resume.

### 3.3 The rulings (section 1, accepted 2026-10-12)

- **D-a1:** rows describe attempts. A retry that never began is `not_started` at attempt k+1, with no `started_at`,
  and is never shown as an executed retry. Attempt k keeps its own failure. `cancelled` is only for an attempt that
  began and was stopped. `skipped` and `not_started` instances that never had an attempt record attempt 1.
- **D-a2:** a control step that awaits anything gets a `running` row first: an activity (CEL over sensitive values, a
  claimed filter), a timer, a child run, or a loop's iterations. Its `started_at` survives a continue-as-new: the upsert
  keeps the first.
- **D-a3:** a control step that finished in the same activation as the run's end keeps its real outcome. Tests cover
  completion against cancellation in both orders, and the same rows projected twice.
- **D-a4:** no per-iteration status. Nothing infers that an iteration opened or finished from missing rows.
- **D-a5:** in an ABI-8 run that ended outside the workflow (a bug, `history_lost`, a termination), a missing row reads
  "not recorded". #90's reconciler still closes `running` rows as `failed` with error code `outcome_unconfirmed`.
- **D-a6:** the extra rows follow the run's retention; the existing graph and iteration budgets and byte-bounded
  projection batches still apply.
- Runs of versions whose `engine_abi` is below 8 show a missing row as "not recorded": a version only ever runs on a
  build of its own ABI.

### 3.4 Upsert precedence

`core/runs/service.upsert_steps` changes from "update whenever the incoming row isn't `running`" to:

| Stored row | Incoming row | Result |
|---|---|---|
| `running` | anything | updated; the first `started_at` is kept |
| provisional (`failed`, error code `outcome_unconfirmed`) | genuine final | the genuine result replaces it |
| provisional | provisional or `running` | no change |
| genuine final | identical final | no change |
| genuine final | provisional or `running` | no change |
| genuine final | a different genuine final | the first is kept; a type-only log line, `where = step_result_conflict` |

This also fixes an existing ordering bug: `apps/worker/store._late()` turns a late `running` row into a provisional one,
which today's upsert writes over a genuine result. Tests cover both arrival orders.

### 3.5 `effect_preview`

0071 adds a nullable `run_steps.effect_preview` (JSONB), written in ABI-8 runs and protected like `output_preview` (the
same `storable()` and redaction): `{"port": "<name>"}` for `flow.if` and `flow.switch`, `{"assignments": {…}}` for
`flow.set_variables`, sensitive values redacted. The steps' declared outputs are unchanged. It reveals nothing new (a
`skipped` row already shows the branch) and gives run pages their taken edges.

### 3.6 Migration 0071

- The `run_steps_status` CHECK widened to the six values, added `NOT VALID` then validated (the online helper).
- `run_steps.effect_preview jsonb NULL`.
- The grants the projection needs, last; the privilege reference regenerated.
- Its downgrade refuses while any `skipped` or `not_started` row, or any non-null `effect_preview`, exists (after the
  ABI-8 workers are stopped), in #90's `REFUSE_DOWNGRADE` style. Clearing such rows is a recovery procedure the owner
  approves, never automatic.
- If 0071 lags a new build, its projections fail on the missing column and are retried until the migration lands:
  nothing is dropped, and runs' ends wait for it. The deploy order is migration first, as for every ABI bump.

## 4. Simulated attempts and flow timers (4d-1a, ABI 8)

### 4.1 Simulated attempts (D-a7)

- A simulated attempt uses the configured retry policy: maximum attempts, backoff, the non-retryable rules.
- Its failures are classified without the live-only "a request may have been sent" uncertainty: on the workflow side
  (`execution._failed_attempt`'s timeout and unmapped paths) and the worker side (an `OutcomeUnknownError` from
  `simulate()`, an ambiguous node's unexpected exception). It never says "Its request may have been sent".
- A genuine fatal failure from the simulator stays non-retryable; a cancellation never retries.
- The outcome is `simulated` ("nothing was sent"), never `outcome_unknown`; the status stays `cancelled` or `failed`
  with its reason.
- This is the same policy as live, not a promise of the same path.

### 4.2 Flow timers aren't waited (capacity ruling (b))

In every simulate run of a version at ABI 8 or later (draft simulations, scheduled simulate runs, simulate starts of
published versions, and their sub-flow and failure-handler children, which inherit the mode):

- `flow.delay` and `flow.wait_until` resolve and validate their config as live: an invalid duration or timestamp fails
  as it would live.
- They don't sleep. The step ends at once: `succeeded`, outcome `simulated`, output `{}` (unchanged), the resolved
  duration or target in its input preview. Its data-origin tag is "evaluated · not waited". It is never `skipped`.
- There is no virtual clock: `run.now` stays `workflow.now()`. A condition after a skipped delay sees the real time. The
  result says: "Flow delays and wait-until weren't waited; the simulation clock wasn't advanced."
- Retry backoff, deadlines, timeouts, cancellation and budgets are unchanged. This removes long flow-timer waits; it
  guarantees neither short simulations nor reserved live capacity. There is no draft cap: draft runs use the tenant's
  slots like any run.

## 5. S2: a single step, with its values supplied (engine in 4d-1a, wired in 4d-1b)

### 5.1 Targets

- Action (plugin) steps, and the control steps that evaluate: `flow.if`, `flow.switch`, `flow.filter`,
  `flow.transform`, `flow.set_variables`.
- Not targets in v1 (D-s1): `flow.loop` (a container), `flow.run_workflow` (a child run), `flow.stop` and `flow.fail`
  (they end the run), `flow.delay` and `flow.wait_until` (a v1 boundary: they would still evaluate their config and
  compute a wake target). Simulate workflow covers them.

### 5.2 The seed contract

Derived from the draft snapshot's frozen validator analysis (scope types, taint, CEL records), never from the B6 data
tree's display shapes.

- **Entries:** root-anchored JSON pointers (`/steps/fetch/output/customer`, `/trigger/site`, `/vars`, `/item`), each
  with the validator's type, its presence (required or optional), whether it may be null, and whether it is sensitive.
- **Sources:** ref paths; template parts; each CEL value's `idents` and `projections` (`engine/cel/record.py`). A
  whole-container read (`size(vars)`) gives a root entry.
- **Runtime-owned `run.*` is never a seed:** `run.id`, `run.started_at` and `run.now` come from the actual run, as in
  any run (`execution._view`). `/run…` reads are left out of the contract, and the target's view binds `run` from the
  run itself.
- **Obligations, aggregated over every use, the strictest wins:**
  - required if any use requires it: a strict ref, a template part without a default, or a CEL read the validator's
    guard analysis doesn't mark as guarded;
  - optional only if every use tolerates absence: a ref with a default, a template part with a default, a
    presence-only projection (`has(…)`), a guarded CEL read;
  - null accepted only if every use tolerates null.
- **Overlaps:** a parent read and a child read merge into the parent, one coherent value, carrying the children's
  obligations (a whole `/steps/a/output` must contain every path a use reads strictly). Contradictory types refuse: a
  validator bug.
- **Lists and every step's results:** a read through a list index is a read of the whole list (a seed never builds a
  list with gaps). A CEL value that reads `steps` or `loops` without naming a step's section reads every step's
  results, so its step can't be simulated alone.
- **Loop aliases:** outside a filter predicate, the innermost loop's frame has one canonical pair, `/item` and `/index`;
  reads of `loops.<innermost>.item` and `.index` map to them, absence states included. Outer loops' `loops.<key>…`
  stay separate entries. The contract lists only canonical pointers; a submission naming an alias is refused with 422
  `seed_alias`.
- **Evaluation contexts:** the contract covers the target's own context only. Names bound per element, such as a
  filter predicate's `item` and `index`, are never seeds: they bind per element of the filtered list, as today
  (`bind_item`).
- **A filter over a computed list:** what its predicate reads strictly of each element can't be traced to a seed, so
  the values its items are computed from keep their schema's `required` there. A guarded or defaulted predicate read
  keeps nothing.
- **Three states:** a value (`null` only where nullable); explicitly absent (only where optional: `has()` is false and
  defaults apply exactly as in a run; a ref default replaces a missing or null value, `resolve.defaulted`); omitted
  (refused at admission, 422 `seed_missing`, naming the pointers). The body is `{values: {pointer: value}, absent:
  [pointer]}`; every entry is in exactly one.
- **Nothing outside the contract:** a pointer the contract doesn't list, in `values` or in `absent`, a `/run…` pointer
  included, is refused at admission with 422 `seed_unknown`, naming it. An alias of a canonical pointer is
  `seed_alias`.
- **A value given:** checked against its entry's schema for types and value rules (enum, pattern, bounds, closed
  objects); inside it, presence and null follow the uses, never what the schema's `required` obliges (`required`
  inside `not` or `if` still tests the value).
- **`/trigger/rows`:** a seed may supply it when an eligible target reads it. Admission's reservation of `rows` and
  `row_count` (only a CSV upload supplies them, `apps/admission.py`) applies to whole-workflow input, not to seeds.

### 5.3 How it runs

- The run executes the draft snapshot's program with only the target step instantiated and no edges, at the root scope
  (iteration key `''`). No iteration opens.
- The target's resolver view is built from the seeds (a seeded resolver view) for its context, with `run` bound from
  the run as always. Reading a seedable path (`steps`, `trigger`, `vars`, a loop's frame) outside the seeds fails the
  attempt `seed_missing`: a guard, which should be unreachable. Runtime bindings never meet that guard.
- The target's config, CEL profile, pinned `type@version` and taint routing come from the draft snapshot.
- Values at sensitive entries were claimed at admission and are handles: CEL over them runs in the evaluator, and the
  secret index applies, exactly as for sensitive run input.
- Its attempts follow §4.1. Its output is checked against its output schema and claimed, as in any run. For if, switch
  and set variables, `effect_preview` carries the port or the assignments.
- **Target-only completion:** the run ends when the target's attempts end, with the target's status. It evaluates no
  declared workflow outputs, starts no failure handler, and follows no normal or error edge.
- Steps other than the target are never instantiated, so they have no rows (not `skipped`).

### 5.4 Guards and the input

- `RunInput` gains `target_step_id: str | None` (ABI 8). `RunInput.version_id` carries the draft snapshot's id; the
  existing `RunInput.snapshot` (a continue-as-new snapshot) is unrelated.
- At admission (§6.3) and again in the workflow before any step: the target exists in the draft snapshot, its type is
  on the allowlist, and the mode is `simulate`. The workflow fails a targeted run that isn't simulate,
  `seeded_live_refused`, before instantiating anything. S2 runs are simulate-only until B9.
- Seeds travel in the request's encrypted envelope, like run input.

## 6. B8: draft snapshots, admission and readers (4d-1b)

### 6.1 Storage (migration 0072)

- **`draft_snapshots`:** the fields a version row carries (graph, node references, `engine_abi`, CEL profile,
  connection ids, pins, schemas, `expressions`, `tainted_sites`, `output_taint`, the declassified sites, the caps, the
  closure, `graph_hash`, `version_hash`), plus `workflow_id`, `draft_revision`, `created_by`, `created_at`.
  - Composite key with the workflow and tenant. Immutable by trigger, like versions, except deletion by retention and
    erasure. Row-level security, the erasure fence, `FENCED_TABLES` and `SWEPT`.
  - Unique on `(workflow_id, version_hash)`: identical drafts share one snapshot. `version_hash` covers the ABI and the
    CEL profile, so an engine upgrade never reuses a stale snapshot. Its `draft_revision` and `created_by` describe its
    first creation.
  - It can never become `workflows.active_version_id`: nothing points there from `workflows`. Triggers start only the
    active version, so no trigger can start a draft snapshot.
- **`run_requests` and `runs`:** `draft_snapshot_id` (composite foreign key with the workflow and tenant);
  `workflow_version_id` nullable; a CHECK for exactly one of the two (a request may also be `refused`); a CHECK that
  `draft_snapshot_id` set implies `mode = 'simulate'`, on both tables, with or without a target.
- **`target_step_id`** on both, allowed only with a draft snapshot and `mode = 'simulate'`.
- **`run_requests.draft_revision`:** each admission's own revision. Its actor is `actor_id`, as now.
- **`run_requests.admission_checks`** (JSONB): the reported checks (§6.3), stored at admission for read-back.
- Grants stay narrow: the API role inserts and selects snapshots; dispatch and the worker select; retention selects and
  deletes. All of them go in the privilege matrix and the reference.
- The downgrade refuses while any request or run backed by a draft snapshot remains, in #90's style.

### 6.2 Reuse against the sweep

- Both paths take a transaction-scoped advisory lock keyed on the deduplication identity `(tenant, workflow,
  version_hash)`, never on the snapshot's id, so recreating a snapshot is covered by the same lock. No row locks, and
  so no UPDATE grants (the admission lock's own reasoning, `core/workflows/service.lock_for_admission`).
- Admission inserts the snapshot `ON CONFLICT DO NOTHING`, takes the lock shared, reads the row again in a fresh READ
  COMMITTED statement, and inserts it again if the sweep removed it; then it inserts the request.
- The sweep (a step after the trees) try-locks each candidate exclusively and skips it if busy; once locked, it checks
  again in a fresh statement that no request or run references it, and only then deletes. The foreign keys stay
  `RESTRICT`. Tests cover both orders.

### 6.3 Admission

`POST /api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations`, with `If-Match: <draft revision>` and an
`Idempotency-Key`. The body is `{input}` (Simulate workflow) or `{target: {step_id, values, absent}}` (Simulate step).
The route takes no mode: it is always `simulate`, `source = manual`.

1. Route permissions (`workflow.edit` and `run.start`; cancelling is the existing route's `run.cancel`) and tenant
   scoping; then the idempotency key. The digest also covers the requested draft revision, the target and the seeds
   (it grows only when they are present, so existing digests keep their bytes). An exact retry returns the original
   request, with the existing concurrent-winner rollback and retention rules (past its cutoff, 410), and never
   rebuilds today's draft or meets a later refusal.
2. Only a new key goes on: the tenant is active; the production gate (interactive sources); the workflow admission
   lock. The workflow need not be enabled, nor ever published (D-b1).
3. The revision is compared: a mismatch is 409 `draft_conflict`.
4. The draft is validated. **Blocking:** any error diagnostic (warnings allowed); `declassify.forbidden` when the
   draft lists declassify entries and the role lacks `workflow.declassify` (worded for simulating: "Simulating a draft
   that declassifies sensitive data needs the workflow.declassify permission (tenant admins and owners)");
   `version.unbounded`; sub-flow cycle, depth and engine version; retired step types; the current build and the
   closure's engine versions.
5. **Reported, not blocking:** unknown or mis-typed connections, pickers, deprecated step types (a simulation opens no
   connection). They are stored on the request as `admission_checks` and returned.
6. Whole-workflow input: the draft's trigger schema at that revision, as admission checks a run's (reserved names
   refused: a draft declaring a CSV can't be simulated whole). Simulate step: the seed contract (§5.2), checked and
   claimed.
7. The draft snapshot is found or inserted (§6.2), the input or seeds are claimed into the envelope, and the request is
   inserted. One audit entry, `run.request`, with the snapshot's id, the revision, `graph_hash`, the target and the
   declassified sites. No separate `workflow.simulate` action (D-b4).

The production gate, the tenant's slots and the dispatcher apply as to every run (decision 4; capacity (b)).

### 6.4 Execution

- Dispatch and the reconciler branch on "version or draft snapshot" for the closure, the engine version and the start.
- The worker's version load (`apps/worker/store.RunStore.version`) reads a draft snapshot by id. Whole-draft runs need
  no workflow-code change; S2 uses §5.
- Sub-flows inside a draft run start their pinned published versions, as now.

### 6.5 Readers

- Every exclusion reads the root's provenance through `root_run_id`: B7 samples, the workflows list's statistics
  ("last simulation", "+N simulated"), "needs attention", and anything that later counts runs. A published child of a
  draft run is excluded with its root.
- Re-running any run whose root is a draft run is refused, 409 `draft_run` ("simulate the draft again"), published
  children included.
- Forced retirement unions the closures of queued draft requests, with a test. A connection's "in use" check leaves
  draft requests out on purpose (a simulation opens no connection); a test pins that.
- The run API returns `draft_snapshot_id` and `target_step_id`. A route reads a draft snapshot's graph (B4a's part for
  draft runs).
- 4e's runs list shows draft runs with a Draft tag, readable with `run.view` (D-b3).

### 6.6 The reads the UI needs

- The person's latest draft simulations of a workflow (labelled as such: never proof of a given submission).
- A simulation's state, including whether a cancel was requested.
- A per-step summary: per step, its instance counts by final status, ports counted, the final attempt for a single
  instance, and each step's data origin (§7.4). Tags come from it, never from a partial page.
- Instances paged and filtered by iteration (decision 5).
- The seed contract at a revision: `GET …/draft/steps/{step_id}/seeds?revision=N`.
- The draft's start form at a revision: `GET …/draft/start-form?revision=N`, in `start-form`'s shape (which reads only
  the active version).
- Read-back from the original request: `admission_checks`, and the input or seeds used, redacted from the envelope,
  never recomputed from today's draft.
- Cancel: the existing route (200 `cancelled`, 202 `requested`).

### 6.7 Retention, erasure, audit

Draft runs follow the tenant's `runs_days`. The sweep deletes draft snapshots no request or run references (§6.2).
Erasure fences and sweeps the new table. The audit is §6.3's `run.request`.

## 7. The UI (4d-1c), per the signed-off boards

### 7.1 Starting

- "◌ Simulate workflow", a slate outline, just before Publish; shown to people who may simulate (editors and up);
  hidden on a version view; disabled with its reason during a conflict, and while the person's own simulation of this
  workflow hasn't ended: being sent, its lost answer being checked, starting, queued or running.
- Both Simulate buttons run Publish's preflight: the save is flushed; held edits get Publish's own "Edits not applied"
  question, worded "Discard and simulate" / "Go back to them". A failed save: "Not simulated: your latest edits aren't
  saved. Retry the save, then simulate."
- The input dialog comes from `GET …/draft/start-form?revision=N`: the form fields, or "Edit as JSON". A Mist-event
  input starts from a skeleton generated from the draft's own input schema at that revision (the Mist catalogue keeps
  no examples, `plugins/mist/schemas.py`), labelled as such. A draft whose input takes a CSV file: the dialog says it
  can't be simulated whole yet, and that Simulate step still works.
- One idempotency key per submit. The editor keeps the exact frozen request (key, revision, input, target, seeds) in
  memory; an unknown outcome sends that same POST again. After a reload there is no such proof: "your latest
  simulation" is labelled as exactly that.

### 7.2 Lifecycle

Submitting, outcome unknown ("Check again": while the first request is still kept, it can't start a second time), queued
("Waiting for a free run slot"), starting, running (confirmed), cancel requested (still running: "It's shown as
cancelled once the server confirms it"), cancelled, succeeded, failed, deadline exceeded, refused, couldn't start
(dead). A failed read keeps the last state, "Couldn't be refreshed · as of …", with "Read it again". Polling starts
at 1 s, backs off to 5 s, and pauses while the tab is hidden.

### 7.3 The result

- A hatched slate banner: "Simulated. Nothing was sent. Results don't prove the live call will succeed." When a flow
  timer wasn't waited: "Flow delays and wait-until weren't waited; the simulation clock wasn't advanced." "Hide the
  result" replaces the banner and tags with a "Show the result" bar; the simulation, its history and a running one are
  untouched.
- Each step card is unchanged (no tint, plain edges). Its tags sit beside it, under it at narrow widths, beside the
  problem and "may not run" badges, never replacing them.
- A step that ran once shows its final attempt ("attempt 2 of 3" in the panel). A step in a loop shows a total over its
  instances, one per opened iteration, skipped ones included ("12 instances: 1 succeeded · 2 failed · 9 skipped"),
  ports as separate chips ("→ true ×3", "→ false ×9").
- After the end, a step with no instance reads "didn't run"; "not recorded" only in D-a5's cases; "not reached yet" only
  while running.
- A step test is distinct: banner "Step test: <key>. Only this step ran. Nothing was sent."; only the target carries a
  result; other steps are outside the test.

### 7.4 Data-origin tags (sent by the server)

`input` and `seeded` (slate outline: values a person gave), `evaluated`, `evaluated · not waited`,
`fixture · not sent` (hatched), `skipped`, `not started`, `cancelled`, `didn't run`, `not recorded`, `not reached yet`.
Always words, never colour alone.

### 7.5 The Simulation panel

Status and the "Simulated" chip; "Ended: <status> · <duration> · draft revision N · run <id>"; the banner; **Checks
on the server** (the request's `admission_checks`, with Go to); the steps in run order with origins and Go to; a loop's
iterations paged ("1–4 of 12", "Next 4"); the input used, redacted, from the request; "◌ Simulate again".

### 7.6 The Test tab

A third drawer tab beside Setup and Options, for allowlisted targets:

- The seed contract at the revision it will send, as fields: the pointer, the type, required or optional, nullable,
  sensitive. Required-nullable: "A value" / "Null". Optional: "A value" / "Absent" (and "Null" when nullable). Sensitive
  values are typed and masked, never prefilled.
- Prefill (D-s2): a `/steps/<key>/output…` entry only from step `<key>`'s own B7 sample, and only when the sample's
  subtree is provably faithful: no redaction, truncation or handle marker; no U+FFFD; no `nan`, `inf` or `-inf` string
  anywhere (what storage writes for non-finite numbers); and it passes the contract. Otherwise it's typed, and the field
  says why. Trigger values, variables, loop context and error paths are always typed.
- If the flush moved the revision on, the contract is read again and the form shown ("this step changed; check the
  values") before sending: a new revision is never paired with an older contract.
- "◌ Simulate step"; the result: status, tags, the values used ("seeded", sensitive ones redacted), the output
  preview, the effect (the port, or what was set), attempts, errors.
- Other step types: why the step can't run alone, and "◌ Simulate workflow".
- After a workflow simulation, the step's result in it, with an iteration picker.
- No live button and no pinned footer (D12).

### 7.7 Stale and refusals

- A result is "Before your edits" when the server revision differs, or when there are local unsaved edits (the editor's
  generation, as publish findings use it). "Go to" a step changed since says so; a deleted step reads "no longer in the
  draft", with no Go to; a step added since has no result.
- Refusals in the server's words, in the panel: validation ("Fix N problems first", with the problems and "Show the
  problems"), `declassify.forbidden`, the gate, retired types, no current build, `seed_missing` and `seed_alias` on
  their fields, `seed_unknown` on its field or, where the form has none, with the refused pointer in the refusal's
  summary. A failed step shows its code and message (`simulation_unavailable`, a fixture's checks) and "Nothing was
  sent".

## 8. Testing

- **4d-1a:** scheduler and execution unit tests per end path (branch elimination, scope failure in an iteration, stop
  and fail, cancel with queued, deferred and handed work, the deadline, a batch); the property that every instance of
  every opened scope ends exactly once; the upsert precedence in both arrival orders; the simulated-attempt
  classification on both sides; timers in simulate; the seed contract (obligations, overlaps, aliases, filter contexts,
  the three states, `/run…` and unknown pointers refused); a seeded run's target-only completion and guards; a
  targeted run whose step reads `run.id`, `run.started_at` and `run.now` with no seed for them; recorded ABI-8
  histories; 0071 up, down
  (refused), the CHECK and the privilege reference.
- **4d-1b:** admission order (an exact retry after the draft changed), blocking against reported checks, the snapshot
  reuse against the sweep in both orders, root-based exclusions (samples, statistics, a published child), re-run
  refusals, retirement and connection checks, the reads of §6.6, RLS and the erasure fence, 0072 up and down (refused),
  the role × endpoint matrix.
- **4d-1c:** unit tests per surface; the Playwright gate (CSP, console, axe) over each board's state, light and dark, at
  1280 and 320 px; nothing leaves the stack (D24).

## 9. Risks

- Volume: B4b adds rows runs don't write today, in successful runs too: terminal rows for untaken branches, unstarted
  instances and unbegun retries. A loop of 12 that takes a branch 3 times adds 9 `skipped` rows for one step. B4b's
  additional coverage rows are bounded by the instance count (opened iterations × region size); stored rows in total
  also count every attempt (§3.1). All of it stays within the existing graph and iteration budgets and byte-bounded
  projection batches. The simulation's reads are paged and summarized on the server; the general run
  detail stays unpaged until 4e.
- The ABI-8 deploy order: migration first.
- B8's dual paths ("version or draft snapshot"): most fail closed; the two that would fail open (retirement, connection
  "in use") have explicit tests.
- The seed contract depends on the validator's guard analysis; the plan verifies what it records before relying on it.
