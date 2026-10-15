# Editor UI 4d-1b: Draft Simulations (B8) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1, 2026-10-14.** Nothing is built before the owner approves this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat.

The plan's code was checked before review on a scratch tree of main at a914a799, never on a branch. Each task's diffs
were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff and the same tests: they passed;
- after every task, ruff (check and format), mypy on `src` and the import contracts (11 kept): clean;
- after the last, the tree matched the prototype the diffs were cut from, file for file;
- the 26 diff blocks, taken from this file's own text, apply in order onto a914a799, each `git apply --check` silent,
  and give that tree but the two generated files; Task 14's schema and types were regenerated on it, and the
  frontend's `check:api` and type check pass.

Three things changed after the check began. Task 3's diff left a blank line at the end of `drafts.py`, which `ruff
format` refuses: corrected, with Task 4's hunk that read it, and checked again. Task 4's red run of the whole erasure
suite took 24 minutes (its tests wait out their timeouts until the implementation lands): its "Run them" step now runs
only the new tests. Task 3 gained its row-level security test last: it passes on the final tree (Task 3's tests, 26
passed), and its file is new in Task 3, so that task's red step is unchanged.

The whole backend suite wasn't run; Task 15 runs it, with the owner's OK. The executor still runs every step: the
check is evidence, not a substitute.

**Goal:** Simulate a saved draft from the API, whole or one step alone: frozen on a draft snapshot, admitted, run and
read back as the editor needs (the spec's §6, B8).

**Architecture:** A draft snapshot holds a version's fields, frozen from the checked draft. Identical drafts share one;
it never changes, and retention deletes it once nothing names it. Admission (`admit_draft`) freezes the draft under the
workflow's admission lock and the snapshot's advisory lock, checks the input or the step's seeds, claims them, and
inserts a `simulate` request naming the snapshot. Dispatch, the reconciler and the worker take "a version or a
snapshot". Readers leave draft runs out of samples and statistics, refuse to re-run them, and count them in a forced
retirement. New reads give the editor its simulations, a per-step summary with data-origin tags, a step's instances by
iteration, a step's seed contract with prefills, and the draft's start form.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.1 (asyncpg), PostgreSQL (row-level security, advisory locks),
migrations written by hand through `migrations/online.py`, Temporal (the time-skipping test server), pytest-xdist.

**Spec:** `docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md`: §6 (B8), with §5.2 (the seed contract),
§7.4 (the data-origin tags) and §7.6 (the Test tab's prefill), which the reads serve.

## Global Constraints

- **No ABI change.** `ENGINE_ABI` stays 9 (spec §2: 4d-1b has none). No golden history is recorded, and none changes.
  A draft run's `RunInput` is a version's, its `version_id` naming the snapshot (ruling 2).
- **One migration, 0072** (the ledger's slot), with `down_revision = "0071"` (main's head).
  - Written by hand through the online helper (`migrations/online.py`: `online`, `step`, `plain`, `index`, `exists`):
    never Alembic autogenerate. Grants last; the privilege reference regenerated in Task 2.
  - Its downgrade refuses while a draft snapshot is kept (spec §6.2).
  - Deploy order: the migration first, then this build's API, dispatcher and worker (they read the new columns).
- **Nothing is sent in a simulation.** No new path sends anything: a draft run is a `simulate` run, and a step alone
  is refused outside one (4d-1a's `seeded_live_refused`).
- **Logs name an exception's type only, never values.** No new log line carries a value; read-back answers redact what
  the envelope holds as claims.
- **No real Mist or SaaS call.** Tests use the testkit and flow plugins and the database.
- **Verify, don't remember.** Every library API is checked in the installed package before it's relied on: SQLAlchemy
  2.1's `postgresql.distinct_on` (its `.distinct(expr)` is deprecated) and `ColumnExpressionArgument`, FastAPI's
  `Query`.
- **No screen changes.** The frontend gains only its regenerated `openapi.json` and `schema.d.ts` (Task 14); the
  screens are 4d-1c's.
- **CI.**
  - Every check runs locally first. Commits and PRs carry no skip marker.
  - Nothing is pushed and no PR is opened without the owner's OK in chat.
  - Ask before any local run expected over 10 minutes.

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the test named, in the
task that owns the code.

- **A simulation admitted while retention sweeps the snapshot it reuses**, in either order. The admission keeps it,
  or makes it again; never a request naming a deleted snapshot. Task 4:
  `test_a_snapshot_an_admission_holds_is_never_swept`,
  `test_a_snapshot_the_sweep_takes_before_an_admission_holds_it_is_made_again`.
- **An editor retrying a lost answer after editing the draft.** The retry is the original request, never a second
  simulation of the new draft, nor a conflict. Task 5:
  `test_an_exact_retry_is_the_original_request_whatever_the_draft_became`.
- **A plugin force-retired while a draft simulation waits in the queue.** Retirement sees the queued simulation
  (cancelled by a forced one), so nothing runs a retired type. Task 8:
  `test_a_queued_draft_simulation_blocks_normal_retirement_and_a_forced_one_cancels_it`.
- **A published sub-flow that a draft run started.** It's never a step's sample, never counted in the workflow list,
  never re-run. Tasks 8 and 9: `test_re_running_a_draft_run_or_a_published_child_of_one_is_refused`,
  `test_a_draft_run_and_a_published_child_of_one_are_never_samples`.
- **A loop of more than ten iterations, paged.** Iteration 2 comes before iteration 10, and a filter on iteration 1
  never returns 10 or 11. Task 12: `test_a_steps_instances_are_paged_in_iteration_order_each_its_final_attempt`.
- **A run a bug ended.** Its steps without rows read "not recorded", never "didn't run". Task 12:
  `test_a_step_with_no_row_is_not_recorded_when_the_run_ended_outside_the_workflow`.
- **A sensitive input or seed, read back.** It's `[redacted]`, never its value. Task 11:
  `test_the_input_used_is_read_back_redacted_from_the_request_whatever_the_draft_became`,
  `test_a_step_tests_seeds_are_read_back_redacted`.
- **A seed whose step's sample was redacted, cut, or of another type.** It's typed, saying why, never prefilled with a
  marker or a value admission would refuse. Task 13:
  `test_each_seed_is_prefilled_from_its_steps_own_faithful_sample_or_typed_saying_why`.
- **A draft whose formula doesn't compile, asked for a step's seeds.** It's refused with the draft's problems, never
  answered with a contract that misses the formula's reads (4d-1a's deferred minor). Task 13:
  `test_the_seeds_read_validates_the_draft_first_and_says_why_a_step_cant_run_alone`.
- **Another tenant's member asking for a simulation.** 404, on every read. Task 14:
  `test_every_role_reads_a_simulation_and_another_tenants_member_never_does`.

## Rulings this plan proposes

They join the ledger as 175 onward only when the owner accepts the plan. Rulings 9 and 13 add to the spec's §6.6
(Task 1, once accepted); the others follow the spec where it's silent.

1. **A draft simulation's source is `manual`**, as the spec's §6.3 has it, not the design notes' `editor` (D-b2). Why:
   the spec is the authority. Cost if wrong: a source value and a filter in 4e.
2. **The worker loads a version, then a snapshot, by the same id.** A draft run's `RunInput.version_id` names its
   snapshot; `DbRunStore.version` falls back to `DraftSnapshot`. Why: no new field in the run's input, so no ABI
   change. Cost if wrong: an `ENGINE_ABI` bump to carry a separate id.
3. **A snapshot's closure is its pins' alone**, without an id of its own (nothing pins a snapshot). Its own engine ABI
   is checked against the current build beside its pins' (`other_abi`). Why: the closure feeds retirement and the
   ABI checks, which name versions. Cost if wrong: one more id in each closure check.
4. **What a simulation reports and doesn't block:** `lifecycle.deprecated` (which the validator gives as an error for
   publish), unknown or mis-typed connections, and pickers, as `admission_checks`. Everything else that blocks
   publish blocks a simulation, `declassify.forbidden` in a simulation's words. Why: spec §6.3 steps 4 and 5. Cost if
   wrong: a code moved between two lists.
5. **"At a revision" means the current one:** a read or a simulation at another revision answers 409
   `draft_conflict` with the draft's `draft_revision`. Why: the draft keeps no history, and §7.6 never pairs a new
   revision with an older contract. Cost if wrong: none; a stored history would be a new design.
6. **The seeds envelope is claimed with each entry's own schema** (with `x-sensitive` where the contract says), never
   checked against it there (`claim_input(against_schema=False)`): `seeds.check` has, and an entry schema's
   `required` mustn't refuse what the contract accepts (spec §5.2, "A value given"). Cost if wrong: a seed admission
   accepts that its claim step refuses.
7. **The idempotency digest grows only for drafts:** `draft={revision, target, values, absent}`, so every other
   request's digest keeps its bytes (spec §6.3). Cost if wrong: none for existing keys.
8. **Snapshot reuse against the sweep:** admission inserts with ON CONFLICT DO NOTHING, takes the snapshot's shared
   advisory transaction lock (`dewpoint:draft:{tenant}:{workflow}:{version_hash}`), reads it again, and makes it again
   if it's gone; the sweep try-locks it exclusively and its DELETE checks again that nothing names it. Its deletions
   aren't counted in `retention_sweep_tenants` (like the ticks' records). Why: spec §6.2. Cost if wrong: a count
   column and its audit.
9. **The data-origin tags are sent as codes:** `evaluated`, `evaluated_not_waited`, `fixture_not_sent`, `skipped`,
   `not_started`, `cancelled`, `didnt_run`, `not_recorded`, `not_reached_yet`, and `given` is `input` or `seeded`;
   4d-1c words them as §7.4 does. A step's origin: an instance whose final attempt succeeded, failed or still runs
   says what made it (a delay or wait-until: not waited; another control step: evaluated; a plugin's step: its
   fixture); else `cancelled`, then `not_started`, then `skipped`; with no instance, `not_reached_yet` while the run
   runs, `not_recorded` when it ended with `internal_error`, `terminated` or `history_lost` (D-a5), else `didnt_run`.
   Why: §7.4 says the server sends them; codes keep the wording the UI's. Cost if wrong: the server sends words.
10. **A step's instances are paged by offset**, in iteration order by number (the keys' indexes as integers, as
    `samples.newest` reads them), with their total; `within` keeps one iteration and those nested in it. A step test's
    summary lists its target alone. Why: §7.5's "1–4 of 12" and §7.3. Cost if wrong: a cursor instead.
11. **The person's simulations list is theirs alone** (`actor_id`), newest first, at most 50. Why: §6.6, "the
    person's latest". Cost if wrong: a filter.
12. **The seeds read validates the draft first, as admission does** (`simulatable`): a draft that would be refused
    answers 422 `invalid` with its problems; a step that can't run alone answers 200 with `refused`, the contract's
    own words, and no entries. Why: 4d-1a's deferred minor (a CEL value without a record has no reads in the
    contract). Cost if wrong: a refusal shaped differently.
13. **D-s2's prefill is computed by the server, in the seeds read:** for each entry not sensitive and inside a
    `/steps/<key>/output`, the step's newest B7 sample there, when it's faithful (no `[redacted]`, `[truncated]` or
    handle, no U+FFFD, no `nan`, `inf` or `-inf` anywhere in it) and the contract's own check accepts it; else the
    reason it's typed: `sensitive`, `not_step_output`, `no_sample`, `not_in_sample`, `not_faithful`, `doesnt_fit`. So
    the read needs `run.view` beside `workflow.edit` and `run.start`. Why: "passes the contract" is the contract's
    check (value rules included), and the UI ships no schema validator; adding one is a dependency the owner would
    have to approve. Cost if wrong: the prefill moves to the UI with a validator.
14. **The draft's start form** needs what simulating needs (`workflow.edit` and `run.start`), and answers
    `start-form`'s shape with `draft_revision` in place of `version_id`; a draft that doesn't parse answers 422
    `invalid`. Cost if wrong: a permission.
15. **4d-1a's ruling 164 gets its guard:** a single step never continues as new (`execution`: no continue-as-new while
    seeds are given). Why: the deferred minor said it held by quiescence alone. Cost if wrong: none.
16. **A new partial index, `runs_workflow_last_published`**, serves the workflow list's last runs without draft runs;
    `runs_workflow_last` stays (the probe reads it). Why: the list's query plan keeps an index scan. Cost if wrong: an
    index dropped later.

## File Structure

New:
- `backend/migrations/versions/0072_draft_snapshots.py`: `draft_snapshots`, the request and run columns, their
  checks, the indexes, the grants.
- `backend/src/dewpoint/core/workflows/drafts.py`: a snapshot found or made under its lock; the sweep's step.
- `backend/src/dewpoint/apps/api/routes/simulations.py`: the simulation route and every read of §6.6.
- `backend/src/dewpoint/apps/step_summary.py`: the per-step summary, the origin rule, a step's instances.
- `backend/src/dewpoint/apps/seed_form.py`: a seed's prefill (D-s2).
- Tests: `backend/tests/migrations/test_0072.py`, `backend/tests/apps/test_draft_snapshots.py`,
  `backend/tests/core/retention/test_draft_snapshots.py`, `backend/tests/apps/test_admission_drafts.py`,
  `backend/tests/apps/api/test_simulations_api.py`, `backend/tests/apps/dispatcher/test_draft_simulations.py`,
  `backend/tests/apps/api/test_simulation_reads.py`, `backend/tests/apps/api/test_simulation_steps.py`,
  `backend/tests/apps/test_step_summary.py`, `backend/tests/apps/api/test_draft_forms.py`,
  `backend/tests/apps/test_seed_form.py`.

Changed:
- Models: `core/models/workflows.py` (`DraftSnapshot`), `core/models/requests.py`, `core/models/runs.py`.
- Freezing and admission: `apps/workflow_ops.py` (`frozen`, `simulatable`), `apps/admission.py` (`admit_draft`),
  `apps/inputs.py` (`against_schema`), `core/requests/digest.py` (`draft`), `core/http.py` (`require(*permissions)`).
- Retention and erasure: `core/retention/sweep.py`, `apps/erasure/stages.py`.
- Execution: `apps/dispatcher/dispatch.py`, `apps/dispatcher/reconcile.py`, `core/runs/service.py`,
  `apps/worker/store.py`, `engine/runtime/execution.py` (the guard).
- Readers: `apps/api/routes/run_requests.py` (`draft_run`), `core/plugins/lifecycle.py` (the preview's union),
  `core/runs/samples.py`, `apps/workflow_summary.py`, `apps/api/routes/runs.py`.
- The API: `apps/api/openapi.py`, `apps/api/responses.py`; `frontend/src/api/openapi.json` and `schema.d.ts`,
  regenerated.
- Tests changed: `tests/core/test_migration_chain.py`, `tests/core/erasure/test_fence.py`,
  `tests/qualification/reference_rights.json`, `tests/core/retention/support.py`, `tests/apps/erasure/support.py`,
  `tests/core/requests/test_digest.py`, `tests/apps/api/test_openapi.py`, `tests/apps/worker/test_run_graph_seeded.py`,
  `tests/apps/test_admission_retirement.py`, `tests/apps/test_connection_fields.py`,
  `tests/apps/api/test_workflow_summary.py`, `tests/core/runs/test_samples.py`.
- Docs: `docs/operations/runs.md`, `docs/operations/retention.md`; the ledger; the spec's §2 table (and §6.6 for
  rulings 9 and 13, once accepted).

## Milestones

1. **Storage** (Tasks 1–4): the ledger, migration 0072, freezing a draft, the snapshots' retention and erasure.
   **Pause:** the owner's review. The migration is what a deploy runs first.
2. **Admission and execution** (Tasks 5–8): admitting a simulation, its route, its run, and the readers that would
   fail open (re-runs, retirement, connections). **Pause:** the owner's review. Draft runs run from here.
3. **Readers and reads** (Tasks 9–15): the exclusions, the run API, every read of §6.6, the schema and docs, every
   check and the final checkpoint. **Pause:** a fresh reviewer, the summary; then stop.

## How to run things

Every command runs from the plan's worktree. `$WT` is that worktree's root. Each command is written out whole: none
is kept in a shell variable, which zsh wouldn't split into words.

- **Python.** From `$WT/backend`, the worktree's own environment is made from the lock: `uv sync --frozen` installs
  exactly `uv.lock` into `$WT/backend/.venv`. It installs packages, so the owner's OK is asked at the start. Then:
  ```bash
  uv run --frozen python -c 'import dewpoint; print(dewpoint.__file__)'   # must print $WT/backend/src/...
  ```
- **The frontend's locked packages**, for Task 14's types only: from `$WT/frontend`,
  `npx --offline pnpm@12.6.0 install --frozen-lockfile --offline` restores them from the local store, the lockfile
  untouched. It installs packages too: asked at the start with the Python environment.
- **Tests.** The database tests start PostgreSQL in Docker (testcontainers); Docker must be reachable. Use six
  workers. From `$WT/backend`: `uv run --frozen pytest -q -p no:cacheprovider -n 6 <files>`.
- **A diff.** Copy the block, between its fences, to a file in the plan's workspace. Then, from `$WT`:
  `git apply --check <file> && git apply <file>`. Expected: no output. A diff that doesn't apply means the tree
  differs from what the previous task left: stop and compare, never apply by hand.
- **Static checks.** From `$WT/backend`: `uv run --frozen ruff check src tests migrations`, `uv run --frozen ruff
  format --check src tests migrations`, `uv run --frozen mypy src`, `uv run --frozen lint-imports`. Expected: "All
  checks passed!", "… files already formatted", "Success: no issues found in … source files", "Contracts: 11 kept, 0
  broken."
- **The whole backend suite** took 23 minutes with 8 workers on 4d-1a's branch, so the owner is asked before it runs.
  It runs at the end only; each task runs its own tests.
- **Local CodeQL**, at the end: `scratchpad/codeql/scan.sh <sha>` (about 50 s).

## Executing this plan

- **Inline**, by one implementing agent in one session, with the owner's reviews at the milestone pauses, and a fresh
  independent review at the end. Test-first, as each task's steps say. The owner chooses.
- **The branch** is settled with the owner at the start. The default proposed: `feat/editor-4d1b` from `origin/main`,
  in its own worktree (`~/4_dev/mist_dewpoint-4d1b`), with the docs branch `docs/editor-ui-4d1b-plan` (this plan)
  merged into it first. A later main is merged in, never rebased.
- **Where the code base differs from a step**, the executor stops at the diff that doesn't apply, adapts it test-first
  and records the difference as a mid-slice ruling in the ledger (M98 onward).
- **The rulings above** join the ledger only when the owner accepts the plan; until then the ledger says they're
  proposed.

---

# Milestone 1 — Storage

### Task 1: The ledger: the slot, this plan proposed, and the spec's §2 table

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (the "Migration slots" table; append at the end)
- Modify: `docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md` (§2's table; §6.6 as far as the owner
  accepts rulings 9 and 13)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger sections later tasks append to (`### 4d-1b, milestone N`).

- [ ] **Step 1: The slot**

In the "Migration slots" table, replace the row for 0072 with:

```markdown
| 0072 | B8: `draft_snapshots`, and the requests' and runs' draft columns (the owner, 2026-10-08; the slot, 2026-10-11); 4d-1b, chained after 0071 |
```

- [ ] **Step 2: Append the plan's status**

Append exactly:

```markdown
### 4d-1b plan (2026-10-14)

`docs/superpowers/plans/2026-10-14-editor-ui-4d1b-backend.md`, revision 1: one plan for the whole of the spec's §6,
with milestone pauses (the owner, 2026-10-14: "One plan"). Its rulings (1–16) are proposed, and join this ledger as
175 onward only when the owner accepts the plan. Rulings 9 and 13 add to the spec's §6.6. It carries 4d-1a's deferred
minors that are 4d-1b's: the seeds read validates the draft first (ruling 12), the operations doc's codes (Task 14),
and ruling 164's guard (ruling 15).
```

- [ ] **Step 3: The spec**

In `docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md`, §2, replace:

```markdown
| 4d-1a, engine | B4b (§3), simulated attempts and flow timers (§4), S2's engine part (§5) | 8 | 0071 |
```

with (M94: ABI 9, after main's 8):

```markdown
| 4d-1a, engine | B4b (§3), simulated attempts and flow timers (§4), S2's engine part (§5) | 9 | 0071 |
```

Only once the owner has accepted ruling 9, in their own words, in §6.6, replace:

```markdown
  instance, and each step's data origin (§7.4). Tags come from it, never from a partial page.
```

with:

```markdown
  instance, and each step's data origin (§7.4). Tags come from it, never from a partial page. The server sends each
  as a code (`evaluated`, `evaluated_not_waited`, `fixture_not_sent`, `skipped`, `not_started`, `cancelled`,
  `didnt_run`, `not_recorded`, `not_reached_yet`; `input` or `seeded` for the values a person gave); the UI words them.
```

Only once the owner has accepted ruling 13, replace:

```markdown
- The seed contract at a revision: `GET …/draft/steps/{step_id}/seeds?revision=N`.
```

with:

```markdown
- The seed contract at a revision: `GET …/draft/steps/{step_id}/seeds?revision=N`, each entry with its prefill
  (D-s2) computed on the server: the contract's own check decides whether a sample fits.
```

A ruling not accepted leaves its part of the spec as it is, and is reported as open in Task 15. If ruling 13 is
declined, Task 13's prefill (`apps/seed_form.py` and the `prefill` field) is left out, its test reduced to the
contract's entries, and the prefill moves to 4d-1c.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md \
  docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md
git commit -m "docs(editor-4): the B8 slot, the 4d-1b plan proposed, and 4d-1a's ABI in the spec

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Migration 0072: draft snapshots, and the requests' and runs' draft columns

**Spec:** §6.1, §6.2, §6.7.

**Files:**
- Create: `backend/migrations/versions/0072_draft_snapshots.py`
- Create: `backend/tests/migrations/test_0072.py`
- Modify: `backend/src/dewpoint/core/models/workflows.py` (`DraftSnapshot`)
- Modify: `backend/src/dewpoint/core/models/requests.py`, `backend/src/dewpoint/core/models/runs.py`
- Modify: `backend/tests/qualification/reference_rights.json`
- Modify: `backend/tests/core/test_migration_chain.py`, `backend/tests/core/erasure/test_fence.py`

**Interfaces:**
- Consumes: `migrations.online` (`online`, `step`, `plain`, `index`, `exists`, `grants`); `tests.migrations.support`.
- Produces: `DraftSnapshot` (every field a `WorkflowVersion` freezes, `version_hash` and `graph_hash`, plus
  `draft_revision`, `created_by`, `declassified`); `RunRequest.draft_snapshot_id`, `.target_step_id`,
  `.draft_revision`, `.admission_checks`; `Run.draft_snapshot_id`, `.target_step_id`; `Run.workflow_version_id` now
  `UUID | None`.

`draft_snapshots` is unique on `(workflow_id, version_hash)` (the hash covers the graph, the pins, the CEL profile and
the engine ABI), and keyed with its workflow and tenant: the requests' and runs' foreign keys to it are composite
`(draft_snapshot_id, workflow_id, tenant_id)`, and restrict its deletion. An UPDATE trigger refuses any change; only
retention and an erasure delete one. Row-level security
scopes it to its tenant, with the erasure fence and an admin platform read. The checks on `run_requests` and `runs`:
a version or a snapshot, never both (a refused request may have neither); a snapshot only in `simulate`; a target only
with a snapshot. Each is added `NOT VALID`, validated outside a transaction, then put in its place, so the upgrade
never blocks writes. `runs.workflow_version_id` drops its NOT NULL (cheap: no rewrite). Four concurrent indexes: the
two snapshot foreign keys, the pending draft requests (Task 8's retirement read), and `runs_workflow_last_published`,
the workflow list's last runs without draft runs (Task 9, ruling 16). Grants: the API reads and inserts snapshots; the
dispatcher, the worker and the admin read them; retention reads and deletes them. The downgrade takes a 5 s lock
timeout, locks the three tables and refuses while a snapshot is kept: "0072 refused: a draft snapshot is kept" (so
while any request or run names one, as the spec asks).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/core/erasure/test_fence.py b/backend/tests/core/erasure/test_fence.py
index 8571615e..c478b81b 100644
--- a/backend/tests/core/erasure/test_fence.py
+++ b/backend/tests/core/erasure/test_fence.py
@@ -25,10 +25,10 @@ from tests.support.workflows import seed_workflow
 UNFENCED = {"audit_log", "retention_sweep_tenants", "tenant_erasures", "tenant_erasure_items", "tenant_erasure_known",
             "unresolved_sends"}  # fmt: skip
 FENCED_TABLES = (
-    "claim_grants", "connections", "csv_mappings", "csv_uploads", "data_keys", "egress_allowlist", "execution_evidence",
-    "inbound_events", "ingress_outstanding", "memberships", "operator_command_holds", "operator_commands",
-    "plugin_calls", "rate_buckets", "rate_scope_keys", "recovery_items", "run_inputs", "run_requests",
-    "run_secret_index", "run_slots", "run_step_connections", "run_steps", "runs", "schedule_firings",
+    "claim_grants", "connections", "csv_mappings", "csv_uploads", "data_keys", "draft_snapshots", "egress_allowlist",
+    "execution_evidence", "inbound_events", "ingress_outstanding", "memberships", "operator_command_holds",
+    "operator_commands", "plugin_calls", "rate_buckets", "rate_scope_keys", "recovery_items", "run_inputs",
+    "run_requests", "run_secret_index", "run_slots", "run_step_connections", "run_steps", "runs", "schedule_firings",
     "schedule_incarnations", "schedule_intervals", "schedules", "step_outputs", "tenant_event_counters",
     "tenant_event_keys", "tenant_retention", "tenant_run_limits", "trigger_bindings", "webhook_endpoints",
     "work_failures", "workflow_versions", "workflows",
diff --git a/backend/tests/core/test_migration_chain.py b/backend/tests/core/test_migration_chain.py
index 7e9f55a8..a9e6e067 100644
--- a/backend/tests/core/test_migration_chain.py
+++ b/backend/tests/core/test_migration_chain.py
@@ -24,7 +24,7 @@ def script() -> ScriptDirectory:
 
 
 def test_the_chain_has_one_head() -> None:
-    assert script().get_heads() == ["0071"]
+    assert script().get_heads() == ["0072"]
 
 
 def test_runs_workflow_last_comes_after_the_orphan_backoff() -> None:
@@ -50,3 +50,8 @@ def test_2b_4bs_migrations_come_after_the_endpoint_sender() -> None:
 def test_the_step_instance_ends_come_after_2b_4bs_last() -> None:
     """Slot 0071 (4d-1a, B4b) is chained after main's head when it was written, 0065 (2b-4b's last)."""
     assert script().get_revision("0071").down_revision == "0065"
+
+
+def test_the_draft_snapshots_come_after_the_step_instance_ends() -> None:
+    """Slot 0072 (4d-1b, B8) is chained after main's head when it was written, 0071 (4d-1a's)."""
+    assert script().get_revision("0072").down_revision == "0071"
diff --git a/backend/tests/migrations/test_0072.py b/backend/tests/migrations/test_0072.py
new file mode 100644
index 00000000..d0b12f2e
--- /dev/null
+++ b/backend/tests/migrations/test_0072.py
@@ -0,0 +1,110 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Migration 0072 on disposable databases, in a cluster of this module's own (editor 4d-1b, B8): `draft_snapshots`,
+immutable and one per workflow and version hash; a request or a run frozen on exactly one of a version or a draft
+snapshot, a snapshot's only in simulate, a target only with a snapshot; its downgrade refuses while a snapshot is
+kept. Its online steps are interrupted, bounded and compared with a fresh database by `test_online.py`, as every
+online migration's are."""
+
+import asyncio
+from collections.abc import AsyncIterator, Iterator
+
+import asyncpg
+import pytest
+from testcontainers.community.postgres import PostgresContainer
+
+from tests.migrations.support import copy, downgrade, upgrade
+from tests.migrations.test_0053 import _drop, _sql
+from tests.probes.migration_locks import seed
+
+ROOTS = 5
+FIELDS = ("graph, node_refs, engine_abi, cel_profile, connection_ids, subflow_version_ids, failure_handler_version_id, "
+          "input_schema, output_schema, vars_schema, expressions, tainted_sites, output_taint, open_scopes_cap, "
+          "loop_depth, closure_version_ids, closure_workflow_ids, closure_node_refs, closure_cel_profiles, "
+          "closure_depth, graph_hash, version_hash")  # fmt: skip
+SNAPSHOT = (f"INSERT INTO draft_snapshots (tenant_id, workflow_id, draft_revision, {FIELDS}) "
+            f"SELECT v.tenant_id, v.workflow_id, 3, {FIELDS.replace('version_hash', '$1')} FROM workflow_versions v "
+            "JOIN run_requests r ON r.workflow_version_id = v.id ORDER BY r.id LIMIT 1 RETURNING id")  # fmt: skip
+REQUEST = ("UPDATE run_requests SET workflow_version_id = $2, draft_snapshot_id = $3, draft_revision = $4, mode = $5, "
+           "target_step_id = $6 WHERE id = (SELECT r.id FROM run_requests r JOIN draft_snapshots s "
+           "ON s.workflow_id = r.workflow_id WHERE s.id = $1 ORDER BY r.id LIMIT 1)")  # fmt: skip
+RUN = ("UPDATE runs SET workflow_version_id = $2, draft_snapshot_id = $3, mode = $4, target_step_id = $5 "
+       "WHERE id = (SELECT r.id FROM runs r JOIN draft_snapshots s ON s.workflow_id = r.workflow_id "
+       "WHERE s.id = $1 ORDER BY r.id LIMIT 1)")  # fmt: skip
+
+
+async def _one(url: str, query: str, *args: object) -> object:
+    c = await asyncpg.connect(url)
+    try:
+        return await c.fetchval(query, *args)
+    finally:
+        await c.close()
+
+
+@pytest.fixture(scope="module")
+def cluster() -> Iterator[str]:
+    with PostgresContainer("postgres:16-alpine", driver=None) as pg:
+        yield pg.get_connection_url().rsplit("/", 1)[0]
+
+
+@pytest.fixture(scope="module")
+def template(cluster: str) -> str:
+    """A seeded database at 0071, as the deployments that run 0072 are."""
+    asyncio.run(_sql(f"{cluster}/postgres", 'CREATE DATABASE "t0071"'))
+    upgrade(f"{cluster}/t0071", "0034")
+    asyncio.run(seed(f"{cluster}/t0071", ROOTS))
+    upgrade(f"{cluster}/t0071", "0071")
+    return "t0071"
+
+
+@pytest.fixture
+async def db(cluster: str, template: str) -> AsyncIterator[str]:
+    url = await copy(cluster, template)
+    yield url
+    await _drop(cluster, url.rsplit("/", 1)[1])
+
+
+async def test_a_snapshot_is_one_per_workflow_and_version_hash_and_never_changes(db: str) -> None:
+    await asyncio.to_thread(upgrade, db, "0072")
+    snapshot = await _one(db, SNAPSHOT, "a" * 64)
+    with pytest.raises(asyncpg.UniqueViolationError):
+        await _one(db, SNAPSHOT, "a" * 64)
+    with pytest.raises(asyncpg.RaiseError, match="draft_snapshots rows are immutable"):
+        await _sql(db, f"UPDATE draft_snapshots SET draft_revision = 4 WHERE id = '{snapshot}'")
+    await _sql(db, f"DELETE FROM draft_snapshots WHERE id = '{snapshot}'")  # only retention may, by its grants
+
+
+async def test_a_request_and_a_run_are_frozen_on_a_version_or_a_simulated_snapshot(db: str) -> None:
+    await asyncio.to_thread(upgrade, db, "0072")
+    s = await _one(db, SNAPSHOT, "b" * 64)
+    version = await _one(db, "SELECT v.id FROM workflow_versions v JOIN draft_snapshots s "
+                             "ON s.workflow_id = v.workflow_id ORDER BY v.number LIMIT 1")  # fmt: skip
+    target = "00000000-0000-4000-8000-000000000001"
+    refused = [  # (version, snapshot, revision, mode, target)
+        (version, s, 3, "simulate", None),  # both
+        (None, s, 3, "live", None),  # a snapshot, live
+        (version, None, None, "simulate", target),  # a target without a snapshot
+        (None, s, None, "simulate", None),  # a snapshot without its revision
+    ]
+    for args in refused:
+        with pytest.raises(asyncpg.CheckViolationError):
+            await _one(db, REQUEST, s, *args)
+    await _one(db, REQUEST, s, None, s, 3, "simulate", target)
+    for args in ((None, None, "simulate", None), (version, s, "simulate", None), (None, s, "live", None)):
+        with pytest.raises(asyncpg.CheckViolationError):
+            await _one(db, RUN, s, *args)
+    await _one(db, RUN, s, None, s, "simulate", target)
+    with pytest.raises(asyncpg.ForeignKeyViolationError):  # a snapshot another run or request still names
+        await _sql(db, f"DELETE FROM draft_snapshots WHERE id = '{s}'")
+
+
+async def test_the_downgrade_refuses_while_a_snapshot_is_kept(db: str) -> None:
+    await asyncio.to_thread(upgrade, db, "0072")
+    s = await _one(db, SNAPSHOT, "c" * 64)
+    with pytest.raises(Exception, match="0072 refused"):
+        await asyncio.to_thread(downgrade, db, "0071")
+    await _sql(db, f"DELETE FROM draft_snapshots WHERE id = '{s}'")
+    await asyncio.to_thread(downgrade, db, "0071")
+    assert await _one(db, "SELECT to_regclass('public.draft_snapshots')") is None
+    nullable = await _one(db, "SELECT is_nullable FROM information_schema.columns WHERE table_name = 'runs' "
+                              "AND column_name = 'workflow_version_id'")  # fmt: skip
+    assert nullable == "NO"
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/migrations/test_0072.py
tests/core/test_migration_chain.py tests/core/erasure/test_fence.py tests/core/test_model_schema.py
tests/qualification/test_reference_rights.py`

Expected: FAIL, 6 failed and 18 passed: the chain's head is `['0071']`, not `['0072']`; 0072's three tests and its
chaining test can't find revision `0072` ("Can't locate revision identified by '0072'", "No such revision or branch
'0072'"); the fence's test finds `draft_snapshots` missing from the fenced tables.

- [ ] **Step 3: Implement**

Apply (the privilege reference's change is in it: regenerated with `DEWPOINT_WRITE_REFERENCE_RIGHTS=1 uv run --frozen
pytest -q tests/qualification/test_reference_rights.py`, which gives the same file):

```diff
diff --git a/backend/migrations/versions/0072_draft_snapshots.py b/backend/migrations/versions/0072_draft_snapshots.py
new file mode 100644
index 00000000..dd415029
--- /dev/null
+++ b/backend/migrations/versions/0072_draft_snapshots.py
@@ -0,0 +1,171 @@
+# SPDX-License-Identifier: Apache-2.0
+"""B8 (editor 4d-1b; the simulation design §6.1): draft snapshots, and requests and runs frozen on one.
+
+- `draft_snapshots`: what a version row carries, frozen from a workflow's draft for a simulation (its graph and
+  references, engine ABI and CEL profile, pins and closure, schemas, CEL records, taint, declassified sites, caps and
+  hashes), with the draft's revision and who first froze it. One per workflow and `version_hash` (which covers the ABI
+  and the CEL profile), so identical drafts share one. Immutable: an UPDATE is refused; only the retention role
+  deletes (an unreferenced snapshot past its runs, §6.2; a tenant's erasure). Nothing points at it from `workflows`, so
+  no trigger can start one.
+- `run_requests` and `runs`: `draft_snapshot_id` (its key with the workflow and tenant), exactly one of it or
+  `workflow_version_id` (a refused request may have neither), a snapshot only in `simulate`, a `target_step_id` only
+  with a snapshot. A request also records the draft revision it was admitted at and the checks it reported.
+- Indexes: each table's snapshot (the foreign keys' checks, the sweep's), a person's draft requests of a workflow
+  (their latest simulations), and the published runs' `runs_workflow_last` (the workflows list's last runs, which leave
+  draft runs out; the old index stays while the old code reads it).
+
+Online (2b-4b, D15): a step locks at most one table in use; the checks go in `NOT VALID` and are validated outside a
+transaction; the indexes are built concurrently; the grants come last. Its downgrade refuses while a snapshot is kept,
+its locks taken before it checks.
+
+Slot 0072 is the ledger's (B8), chained after 0071."""
+
+from alembic import op
+
+from migrations.online import exists, grants, index, online, plain, step, ungranted
+
+revision = "0072"
+down_revision = "0071"
+branch_labels = None
+depends_on = None
+
+TABLE = """CREATE TABLE draft_snapshots (
+  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
+  tenant_id uuid NOT NULL REFERENCES tenants (id),
+  workflow_id uuid NOT NULL,
+  draft_revision integer NOT NULL,
+  graph jsonb NOT NULL,
+  node_refs text[] NOT NULL,
+  engine_abi integer NOT NULL,
+  cel_profile varchar(120) NOT NULL REFERENCES cel_profiles (profile),
+  connection_ids uuid[] NOT NULL DEFAULT '{}',
+  subflow_version_ids jsonb NOT NULL DEFAULT '{}'::jsonb,
+  failure_handler_version_id uuid NULL,
+  input_schema jsonb NOT NULL,
+  output_schema jsonb NOT NULL,
+  vars_schema jsonb NOT NULL,
+  expressions jsonb NOT NULL DEFAULT '[]'::jsonb,
+  tainted_sites jsonb NOT NULL DEFAULT '[]'::jsonb,
+  output_taint jsonb NULL,
+  declassified jsonb NOT NULL DEFAULT '[]'::jsonb,
+  open_scopes_cap integer NULL,
+  loop_depth integer NULL,
+  closure_version_ids uuid[] NOT NULL,
+  closure_workflow_ids uuid[] NOT NULL,
+  closure_node_refs text[] NOT NULL,
+  closure_cel_profiles text[] NOT NULL,
+  closure_depth integer NOT NULL,
+  graph_hash varchar(64) NOT NULL,
+  version_hash varchar(64) NOT NULL,
+  created_by uuid NULL,
+  created_at timestamptz NOT NULL DEFAULT now(),
+  CONSTRAINT draft_snapshots_hash UNIQUE (workflow_id, version_hash),
+  CONSTRAINT draft_snapshots_tenant UNIQUE (id, workflow_id, tenant_id),
+  CONSTRAINT draft_snapshots_workflow FOREIGN KEY (workflow_id, tenant_id) REFERENCES workflows (id, tenant_id))"""
+IMMUTABLE = """CREATE FUNCTION draft_snapshots_immutable() RETURNS trigger LANGUAGE plpgsql
+SET search_path = public, pg_temp AS $$
+BEGIN
+  RAISE EXCEPTION 'draft_snapshots rows are immutable';
+END $$"""
+SNAPSHOTS = (
+    TABLE,
+    "ALTER TABLE draft_snapshots ENABLE ROW LEVEL SECURITY",
+    "ALTER TABLE draft_snapshots FORCE ROW LEVEL SECURITY",
+    "CREATE POLICY draft_snapshots_scope ON draft_snapshots "
+    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
+    "CREATE POLICY draft_snapshots_platform_read ON draft_snapshots FOR SELECT TO dewpoint_admin USING (true)",
+    IMMUTABLE,
+    "REVOKE ALL ON FUNCTION draft_snapshots_immutable() FROM PUBLIC",
+    "CREATE TRIGGER draft_snapshots_immutable BEFORE UPDATE ON draft_snapshots FOR EACH ROW "
+    "EXECUTE FUNCTION draft_snapshots_immutable()",
+    "CREATE TRIGGER draft_snapshots_fence BEFORE INSERT ON draft_snapshots FOR EACH ROW "
+    "EXECUTE FUNCTION tenant_insert_fence()",
+    "GRANT SELECT, INSERT ON draft_snapshots TO dewpoint_api",
+    "GRANT SELECT ON draft_snapshots TO dewpoint_dispatch, dewpoint_worker, dewpoint_admin",
+    "GRANT SELECT, DELETE ON draft_snapshots TO dewpoint_retention",
+)
+REQUEST_SHAPE = ("(draft_snapshot_id IS NULL AND target_step_id IS NULL AND draft_revision IS NULL "
+                 "AND admission_checks IS NULL) OR (draft_snapshot_id IS NOT NULL AND mode = 'simulate' "
+                 "AND draft_revision IS NOT NULL)")  # fmt: skip
+FROZEN = ("num_nonnulls(workflow_version_id, draft_snapshot_id) <= 1 "
+          "AND (status = 'refused' OR num_nonnulls(workflow_version_id, draft_snapshot_id) = 1)")  # fmt: skip
+WIDER = "run_requests_frozen_0072"
+WIDENED = ("SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'run_requests_frozen' "
+           "AND pg_get_constraintdef(oid) LIKE '%draft_snapshot_id%')")  # fmt: skip
+REQUESTS = {  # each check, added NOT VALID, then validated
+    "run_requests_draft": "FOREIGN KEY (draft_snapshot_id, workflow_id, tenant_id) "
+    "REFERENCES draft_snapshots (id, workflow_id, tenant_id)",
+    "run_requests_draft_shape": f"CHECK ({REQUEST_SHAPE})",
+    WIDER: f"CHECK ({FROZEN})",
+}
+RUN_SHAPE = ("(draft_snapshot_id IS NULL AND target_step_id IS NULL) "
+             "OR (draft_snapshot_id IS NOT NULL AND mode = 'simulate')")  # fmt: skip
+RUNS = {
+    "runs_draft_fk": "FOREIGN KEY (draft_snapshot_id, workflow_id, tenant_id) "
+    "REFERENCES draft_snapshots (id, workflow_id, tenant_id)",
+    "runs_draft_shape": f"CHECK ({RUN_SHAPE})",
+    "runs_frozen": "CHECK (num_nonnulls(workflow_version_id, draft_snapshot_id) = 1)",
+}
+INDEXES = {
+    "run_requests_draft_snapshot": "ON run_requests (draft_snapshot_id) WHERE draft_snapshot_id IS NOT NULL",
+    "runs_draft_snapshot": "ON runs (draft_snapshot_id) WHERE draft_snapshot_id IS NOT NULL",
+    "run_requests_drafts": "ON run_requests (tenant_id, workflow_id, actor_id, queued_at DESC, id DESC) "
+    "WHERE draft_snapshot_id IS NOT NULL",
+    "runs_workflow_last_published": "ON runs (workflow_id, mode, queued_at DESC, id DESC) "
+    "WHERE kind = 'run' AND draft_snapshot_id IS NULL",
+}
+LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"
+LOCKED = "LOCK TABLE draft_snapshots, run_requests, runs IN ACCESS EXCLUSIVE MODE"
+REFUSE_DOWNGRADE = """DO $$ BEGIN
+  IF EXISTS (SELECT 1 FROM draft_snapshots) THEN
+    RAISE EXCEPTION '0072 refused: a draft snapshot is kept';
+  END IF;
+END $$"""
+
+
+def upgrade() -> None:
+    with online() as conn:
+        step(conn, "0072 draft_snapshots", *ungranted(*SNAPSHOTS), done=exists("relation", "draft_snapshots"))
+        step(conn, "0072 run_requests columns",
+             "ALTER TABLE run_requests ADD COLUMN draft_snapshot_id uuid, ADD COLUMN target_step_id uuid, "
+             "ADD COLUMN draft_revision integer, ADD COLUMN admission_checks jsonb",
+             done=exists("column", "draft_snapshot_id", "run_requests"))  # fmt: skip
+        step(conn, "0072 run_requests checks",
+             *(f"ALTER TABLE run_requests ADD CONSTRAINT {name} {check} NOT VALID" for name, check in REQUESTS.items()),
+             done=exists("constraint", "run_requests_draft"))  # fmt: skip
+        for name in REQUESTS:
+            done = WIDENED if name == WIDER else f"SELECT convalidated FROM pg_constraint WHERE conname = '{name}'"
+            plain(conn, f"0072 {name} validated", f"ALTER TABLE run_requests VALIDATE CONSTRAINT {name}", done=done)
+        step(conn, "0072 run_requests_frozen, swapped", "ALTER TABLE run_requests DROP CONSTRAINT run_requests_frozen",
+             f"ALTER TABLE run_requests RENAME CONSTRAINT {WIDER} TO run_requests_frozen", done=WIDENED)  # fmt: skip
+        step(conn, "0072 runs columns",
+             "ALTER TABLE runs ADD COLUMN draft_snapshot_id uuid, ADD COLUMN target_step_id uuid, "
+             "ALTER COLUMN workflow_version_id DROP NOT NULL",
+             done=exists("column", "draft_snapshot_id", "runs"))  # fmt: skip
+        step(conn, "0072 runs checks",
+             *(f"ALTER TABLE runs ADD CONSTRAINT {name} {check} NOT VALID" for name, check in RUNS.items()),
+             done=exists("constraint", "runs_draft_fk"))  # fmt: skip
+        for name in RUNS:
+            plain(conn, f"0072 {name} validated", f"ALTER TABLE runs VALIDATE CONSTRAINT {name}",
+                  done=f"SELECT convalidated FROM pg_constraint WHERE conname = '{name}'")  # fmt: skip
+        for name, definition in INDEXES.items():
+            index(conn, f"0072 {name}", f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} {definition}")
+        step(conn, "0072 grants", *grants(*SNAPSHOTS))
+
+
+def downgrade() -> None:
+    for statement in (LOCK_TIMEOUT, LOCKED, REFUSE_DOWNGRADE):
+        op.execute(statement)
+    for name in INDEXES:
+        op.execute(f"DROP INDEX {name}")
+    op.execute("ALTER TABLE runs " + ", ".join(f"DROP CONSTRAINT {name}" for name in reversed(RUNS)))
+    op.execute("ALTER TABLE runs DROP COLUMN target_step_id, DROP COLUMN draft_snapshot_id, "
+               "ALTER COLUMN workflow_version_id SET NOT NULL")  # fmt: skip
+    op.execute("ALTER TABLE run_requests DROP CONSTRAINT run_requests_frozen, DROP CONSTRAINT run_requests_draft_shape, "
+               "DROP CONSTRAINT run_requests_draft")  # fmt: skip
+    op.execute("ALTER TABLE run_requests ADD CONSTRAINT run_requests_frozen "
+               "CHECK (status = 'refused' OR workflow_version_id IS NOT NULL)")  # fmt: skip
+    op.execute("ALTER TABLE run_requests DROP COLUMN admission_checks, DROP COLUMN draft_revision, "
+               "DROP COLUMN target_step_id, DROP COLUMN draft_snapshot_id")  # fmt: skip
+    op.execute("DROP TABLE draft_snapshots")
+    op.execute("DROP FUNCTION draft_snapshots_immutable()")
diff --git a/backend/src/dewpoint/core/models/requests.py b/backend/src/dewpoint/core/models/requests.py
index 14b459ef..94e7a5a4 100644
--- a/backend/src/dewpoint/core/models/requests.py
+++ b/backend/src/dewpoint/core/models/requests.py
@@ -4,6 +4,7 @@ slots a tenant's running root runs hold; its limits row; and the current build a
 
 import uuid
 from datetime import datetime
+from typing import Any
 
 from sqlalchemy import (
     DateTime,
@@ -18,7 +19,7 @@ from sqlalchemy import (
     func,
     text,
 )
-from sqlalchemy.dialects.postgresql import UUID
+from sqlalchemy.dialects.postgresql import JSONB, UUID
 from sqlalchemy.orm import Mapped, mapped_column
 
 from dewpoint.core.models.base import Base
@@ -43,6 +44,11 @@ class RunRequest(Base):
             ["workflow_versions.id", "workflow_versions.workflow_id", "workflow_versions.tenant_id"],
             name="run_requests_version",
         ),
+        ForeignKeyConstraint(  # or a draft snapshot of it (B8): exactly one of the two, but a refusal may have neither
+            ["draft_snapshot_id", "workflow_id", "tenant_id"],
+            ["draft_snapshots.id", "draft_snapshots.workflow_id", "draft_snapshots.tenant_id"],
+            name="run_requests_draft",
+        ),
         ForeignKeyConstraint(
             ["envelope_id", "tenant_id", "id", "envelope_role"],
             ["run_inputs.id", "run_inputs.tenant_id", "run_inputs.owner_run_id", "run_inputs.role"],
@@ -77,6 +83,12 @@ class RunRequest(Base):
     checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the reconciler's last look
     envelope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
     envelope_role: Mapped[str] = mapped_column(String(16), server_default="envelope")  # its envelope key's constant
+    # A draft simulation's (B8; the simulation design §6.1): the snapshot it runs, the step it runs alone (S2), the
+    # draft revision it was admitted at, and the checks admission reported without refusing.
+    draft_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    target_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    draft_revision: Mapped[int | None] = mapped_column(Integer)
+    admission_checks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
 
 
 class TenantRunLimits(Base):
diff --git a/backend/src/dewpoint/core/models/runs.py b/backend/src/dewpoint/core/models/runs.py
index 65ca93a5..79e65cd8 100644
--- a/backend/src/dewpoint/core/models/runs.py
+++ b/backend/src/dewpoint/core/models/runs.py
@@ -41,13 +41,20 @@ class Run(Base):
             ["workflow_versions.id", "workflow_versions.workflow_id", "workflow_versions.tenant_id"],
             name="runs_version_fk",
         ),
+        ForeignKeyConstraint(  # or a draft snapshot of it (B8): exactly one of the two
+            ["draft_snapshot_id", "workflow_id", "tenant_id"],
+            ["draft_snapshots.id", "draft_snapshots.workflow_id", "draft_snapshots.tenant_id"],
+            name="runs_draft_fk",
+        ),
         ForeignKeyConstraint(["parent_run_id", "tenant_id"], ["runs.id", "runs.tenant_id"], name="runs_parent_run"),
         ForeignKeyConstraint(["root_run_id", "tenant_id"], ["runs.id", "runs.tenant_id"], name="runs_root_run"),
     )
     id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
     tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
     workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
-    workflow_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
+    workflow_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # None: a draft snapshot's
+    draft_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # a draft simulation's (B8)
+    target_step_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # the step it ran alone (S2)
     mode: Mapped[str] = mapped_column(String(16))
     status: Mapped[str] = mapped_column(String(32))
     # A root run's row is written at dispatch, before Temporal answers (engine 2b spec §7.3): queued then, started
diff --git a/backend/src/dewpoint/core/models/workflows.py b/backend/src/dewpoint/core/models/workflows.py
index 42ac17eb..e7b7b8b3 100644
--- a/backend/src/dewpoint/core/models/workflows.py
+++ b/backend/src/dewpoint/core/models/workflows.py
@@ -83,3 +83,47 @@ class WorkflowVersion(UUIDPk, Base):
     version_hash: Mapped[str] = mapped_column(String(64))
     published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
     published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
+
+
+class DraftSnapshot(UUIDPk, Base):
+    """A workflow's draft, frozen for a simulation (B8; the simulation design §6.1): what a version carries, under the
+    same names, with the draft's revision and who first froze it. One per workflow and `version_hash`, so identical
+    drafts share one. Immutable (a trigger refuses UPDATE); only retention deletes one, once nothing names it. It is
+    never a workflow's active version: no trigger starts it."""
+
+    __tablename__ = "draft_snapshots"
+    __table_args__ = (
+        UniqueConstraint("workflow_id", "version_hash", name="draft_snapshots_hash"),
+        UniqueConstraint("id", "workflow_id", "tenant_id", name="draft_snapshots_tenant"),
+        ForeignKeyConstraint(
+            ["workflow_id", "tenant_id"], ["workflows.id", "workflows.tenant_id"], name="draft_snapshots_workflow"
+        ),
+    )
+    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
+    workflow_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
+    draft_revision: Mapped[int] = mapped_column(Integer)
+    graph: Mapped[dict[str, Any]] = mapped_column(JSONB)
+    node_refs: Mapped[list[str]] = mapped_column(ARRAY(Text))
+    engine_abi: Mapped[int] = mapped_column(Integer)
+    cel_profile: Mapped[str] = mapped_column(String(120), ForeignKey("cel_profiles.profile"))
+    connection_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
+    subflow_version_ids: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
+    failure_handler_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    input_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
+    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
+    vars_schema: Mapped[dict[str, Any]] = mapped_column(JSONB)
+    expressions: Mapped[list[Any]] = mapped_column(JSONB, default=list)
+    tainted_sites: Mapped[list[Any]] = mapped_column(JSONB, default=list)
+    output_taint: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
+    declassified: Mapped[list[Any]] = mapped_column(JSONB, default=list)  # [{node, field, reveals}], for its audit
+    open_scopes_cap: Mapped[int | None] = mapped_column(Integer)
+    loop_depth: Mapped[int | None] = mapped_column(Integer)
+    closure_version_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))  # its pins' (no own id)
+    closure_workflow_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
+    closure_node_refs: Mapped[list[str]] = mapped_column(ARRAY(Text))
+    closure_cel_profiles: Mapped[list[str]] = mapped_column(ARRAY(Text))
+    closure_depth: Mapped[int] = mapped_column(Integer)
+    graph_hash: Mapped[str] = mapped_column(String(64))
+    version_hash: Mapped[str] = mapped_column(String(64))
+    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
+    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
diff --git a/backend/tests/qualification/reference_rights.json b/backend/tests/qualification/reference_rights.json
index bb63e9e4..be201e76 100644
--- a/backend/tests/qualification/reference_rights.json
+++ b/backend/tests/qualification/reference_rights.json
@@ -285,6 +285,11 @@
    "public.dispatcher_reports",
    "SELECT"
   ],
+  [
+   "relation:r",
+   "public.draft_snapshots",
+   "SELECT"
+  ],
   [
    "relation:r",
    "public.egress_allowlist",
@@ -1302,6 +1307,16 @@
    "public.data_keys",
    "UPDATE"
   ],
+  [
+   "relation:r",
+   "public.draft_snapshots",
+   "INSERT"
+  ],
+  [
+   "relation:r",
+   "public.draft_snapshots",
+   "SELECT"
+  ],
   [
    "relation:r",
    "public.egress_allowlist",
@@ -2236,6 +2251,11 @@
    "public.dispatcher_reports",
    "UPDATE"
   ],
+  [
+   "relation:r",
+   "public.draft_snapshots",
+   "SELECT"
+  ],
   [
    "relation:r",
    "public.execution_evidence",
@@ -3130,6 +3150,16 @@
    "public.data_keys",
    "DELETE"
   ],
+  [
+   "relation:r",
+   "public.draft_snapshots",
+   "DELETE"
+  ],
+  [
+   "relation:r",
+   "public.draft_snapshots",
+   "SELECT"
+  ],
   [
    "relation:r",
    "public.egress_allowlist",
@@ -3609,6 +3639,11 @@
    "public.data_keys",
    "UPDATE"
   ],
+  [
+   "relation:r",
+   "public.draft_snapshots",
+   "SELECT"
+  ],
   [
    "relation:r",
    "public.egress_allowlist",
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 24 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/0072_draft_snapshots.py backend/tests/migrations/test_0072.py \
  backend/src/dewpoint/core/models/workflows.py backend/src/dewpoint/core/models/requests.py \
  backend/src/dewpoint/core/models/runs.py backend/tests/qualification/reference_rights.json \
  backend/tests/core/test_migration_chain.py backend/tests/core/erasure/test_fence.py
git commit -m "feat(runs): migration 0072, draft snapshots and the requests' and runs' draft columns (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Freezing a draft: one snapshot per version hash

**Spec:** §6.1, §6.2, §6.3 (steps 4 and 5).

**Files:**
- Modify: `backend/src/dewpoint/apps/workflow_ops.py` (`frozen`, `Simulatable`, `simulatable`, `REPORTED`)
- Create: `backend/src/dewpoint/core/workflows/drafts.py`
- Create: `backend/tests/apps/test_draft_snapshots.py`

**Interfaces:**
- Consumes: Task 2's `DraftSnapshot`; `workflow_ops.Checked`, `service.NewVersion`.
- Produces: `workflow_ops.frozen(checked, workflow_id, cap, depth, *, version_id: uuid.UUID | None) ->
  service.NewVersion` (publish passes its new id; a snapshot None); `workflow_ops.Simulatable(new, blocking, reported,
  warnings)`; `async workflow_ops.simulatable(s, ctx, wf, checked) -> Simulatable`; `workflow_ops.REPORTED =
  ("lifecycle.deprecated",)`; `drafts.lock_key(tenant_id, workflow_id, version_hash) -> str`; `async
  drafts.snapshot_for(s, wf, new, *, revision: int, created_by: uuid.UUID | None) -> DraftSnapshot`.

Publish's field computation moves into `frozen`, which publish and a simulation share: a draft is frozen exactly as
its version would be, except that a snapshot's closure is its pins' alone (ruling 3). `simulatable` sorts the draft's
problems (ruling 4): any error but `lifecycle.deprecated` blocks, and so do `declassify.forbidden` (in a simulation's
words), the sub-flows' problems, retired types and `version.unbounded`; deprecated types, connections and pickers are
reported. `snapshot_for` inserts with ON CONFLICT DO NOTHING, takes the snapshot's shared advisory lock, and reads it
again, so a reused snapshot keeps the revision and author of its first freezing (ruling 8). A test pins the table's
row-level security, forced: the API, the dispatcher and the worker see a tenant's snapshots only in its scope (§8).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/test_draft_snapshots.py b/backend/tests/apps/test_draft_snapshots.py
new file mode 100644
index 00000000..7230ac9d
--- /dev/null
+++ b/backend/tests/apps/test_draft_snapshots.py
@@ -0,0 +1,149 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A draft frozen for a simulation (B8; the simulation design §6.1, §6.3): its snapshot carries what its version would,
+identical drafts share one (described by its first freezing), another engine build freezes its own; a simulation
+refuses what can't run and reports what publish would refuse but a simulation never meets."""
+
+import uuid
+from typing import Any
+
+from sqlalchemy import text
+
+from dewpoint.apps import workflow_ops
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.http import TenantContext
+from dewpoint.core.models.workflows import DraftSnapshot
+from dewpoint.core.plugins import lifecycle
+from dewpoint.core.workflows import drafts, service
+from dewpoint.engine import ENGINE_ABI
+from tests.apps.test_workflow_ops import ECHO, ECHO_GRAPH, actor, create, declassifying_graph, publish, save
+from tests.support.graphs import G
+from tests.support.registry import sync_test_plugins
+
+
+async def freeze(
+    api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, settings: Any
+) -> workflow_ops.Simulatable:
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        wf = await service.get_workflow(s, ctx.tenant_id, wf_id)
+        assert wf is not None
+        checked = await workflow_ops.check_draft(s, ctx.tenant_id, wf.draft, settings)
+        return await workflow_ops.simulatable(s, ctx, wf, checked)
+
+
+async def snapshot(api_sessionmaker: Any, ctx: TenantContext, wf_id: uuid.UUID, settings: Any) -> DraftSnapshot:
+    async with api_sessionmaker() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        wf = await service.get_workflow(s, ctx.tenant_id, wf_id)
+        assert wf is not None
+        checked = await workflow_ops.check_draft(s, ctx.tenant_id, wf.draft, settings)
+        out = await workflow_ops.simulatable(s, ctx, wf, checked)
+        assert out.new is not None, out.blocking
+        return await drafts.snapshot_for(s, wf, out.new, revision=wf.draft_revision, created_by=ctx.user.id)
+
+
+async def test_a_draft_is_frozen_as_its_version_would_be(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
+    s = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
+    v = (await publish(api_sessionmaker, ctx, wf_id, api_settings)).version
+    assert v is not None
+    same = ("graph", "node_refs", "engine_abi", "cel_profile", "subflow_version_ids", "input_schema", "output_schema",
+            "vars_schema", "expressions", "tainted_sites", "output_taint", "open_scopes_cap", "loop_depth",
+            "closure_workflow_ids", "closure_node_refs", "closure_cel_profiles", "closure_depth", "graph_hash",
+            "version_hash", "connection_ids")  # fmt: skip
+    assert {f: getattr(s, f) for f in same} == {f: getattr(v, f) for f in same}
+    assert (s.closure_version_ids, v.closure_version_ids) == ([], [v.id])  # a snapshot isn't a version: nothing pins it
+    assert (s.workflow_id, s.draft_revision, s.created_by) == (wf_id, 1, ctx.user.id)
+
+
+async def test_identical_drafts_share_one_snapshot_described_by_its_first(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
+    first = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
+    await save(api_sessionmaker, ctx, wf_id, ECHO_GRAPH)  # revision 2, the same graph
+    other = TenantContext(tenant_id=ctx.tenant_id, user=ctx.user, role="admin", session=None)  # type: ignore[arg-type]
+    again = await snapshot(api_sessionmaker, other, wf_id, api_settings)
+    assert (again.id, again.draft_revision) == (first.id, 1)
+    await save(api_sessionmaker, ctx, wf_id, G().node("a", "testkit.echo@1", {"value": 2}).data())
+    changed = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
+    assert changed.id != first.id and changed.draft_revision == 3
+
+
+async def test_another_engine_build_freezes_a_snapshot_of_its_own(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, monkeypatch
+) -> None:
+    """`version_hash` covers the engine ABI and the CEL profile: a draft frozen by another build is never reused."""
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
+    first = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
+    monkeypatch.setattr(workflow_ops, "ENGINE_ABI", ENGINE_ABI + 1)
+    later = await snapshot(api_sessionmaker, ctx, wf_id, api_settings)
+    assert later.id != first.id and (later.engine_abi, first.engine_abi) == (ENGINE_ABI + 1, ENGINE_ABI)
+
+
+async def test_a_simulation_reports_a_deprecated_type_that_publish_refuses(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    """Spec §6.3, step 5: deprecated types are reported, not blocking (a simulation of what runs today)."""
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    wf_id = await create(api_sessionmaker, ctx, ECHO_GRAPH)
+    async with admin_sessionmaker() as s, s.begin():
+        await lifecycle.deprecate(s, ECHO, actor_id=None)
+    out = await freeze(api_sessionmaker, ctx, wf_id, api_settings)
+    assert out.new is not None and out.blocking == []
+    assert [d.code for d in out.reported] == ["lifecycle.deprecated"]
+    refused = await publish(api_sessionmaker, ctx, wf_id, api_settings)
+    assert [d.code for d in refused.errors] == ["lifecycle.deprecated"]
+
+
+async def test_a_simulation_refuses_a_retired_type_and_an_undeclassifiable_draft(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    """Spec §6.3, step 4: what can't run blocks it; `declassify.forbidden` in a simulation's words."""
+    await sync_test_plugins(admin_sessionmaker)
+    editor = await actor(owner_sessionmaker)
+    declassifying = await create(api_sessionmaker, editor, declassifying_graph(), name="d")
+    out = await freeze(api_sessionmaker, editor, declassifying, api_settings)
+    assert out.new is None and [(d.code, d.field) for d in out.blocking] == [
+        ("declassify.forbidden", "/settings/declassify")
+    ]
+    assert out.blocking[0].message.startswith("Simulating a draft that declassifies sensitive data needs")
+    echo = await create(api_sessionmaker, editor, ECHO_GRAPH, name="e")
+    async with admin_sessionmaker() as s, s.begin():
+        await lifecycle.retire(s, ECHO, force=True, confirm=True)
+    out = await freeze(api_sessionmaker, editor, echo, api_settings)
+    assert out.new is None and [d.code for d in out.blocking] == ["lifecycle.retired"]
+
+
+async def test_a_snapshot_is_seen_only_within_its_tenant(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    """Row-level security, forced (§6.1): the API, the dispatcher and the worker read a tenant's snapshots only in its
+    scope; the admin's platform read sees them all."""
+    await sync_test_plugins(admin_sessionmaker)
+    ctx, other = await actor(owner_sessionmaker), await actor(owner_sessionmaker)
+    await snapshot(api_sessionmaker, ctx, await create(api_sessionmaker, ctx, ECHO_GRAPH), api_settings)
+    async with owner_sessionmaker() as s:
+        flags = (await s.execute(text("select relrowsecurity, relforcerowsecurity from pg_class "
+                                      "where relname = 'draft_snapshots'"))).one()  # fmt: skip
+    assert tuple(flags) == (True, True)
+    mine = text("select count(*) from draft_snapshots where tenant_id = :t")
+    for maker in (api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker):
+        async with maker() as s, s.begin():
+            assert (await s.execute(mine, {"t": ctx.tenant_id})).scalar_one() == 0
+            await tenant_scope(s, other.tenant_id)
+            assert (await s.execute(mine, {"t": ctx.tenant_id})).scalar_one() == 0
+        async with maker() as s, s.begin():
+            await tenant_scope(s, ctx.tenant_id)
+            assert (await s.execute(mine, {"t": ctx.tenant_id})).scalar_one() == 1
+    async with admin_sessionmaker() as s, s.begin():
+        assert (await s.execute(mine, {"t": ctx.tenant_id})).scalar_one() == 1
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/test_draft_snapshots.py
tests/apps/test_workflow_ops.py`

Expected: FAIL at collection, 1 error: `tests/apps/test_draft_snapshots.py` can't import `drafts` from
`dewpoint.core.workflows`. The 20 tests of `test_workflow_ops.py` pass.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/workflow_ops.py b/backend/src/dewpoint/apps/workflow_ops.py
index c539fa64..cf3ce423 100644
--- a/backend/src/dewpoint/apps/workflow_ops.py
+++ b/backend/src/dewpoint/apps/workflow_ops.py
@@ -373,57 +373,120 @@ async def publish(
     if errors:
         return Published(None, errors, warnings)
     version_id = uuid.uuid4()
-    graph_settings = checked.graph.settings
-    authored = graph_hash(checked.graph)
     try:
         cap, depth = await _pinned(s, checked)
     except BoundError as e:  # engine 2b spec §5.3: the continued-input bound can't be established for it
         return Published(None, [Diagnostic(code="version.unbounded", message=str(e))], warnings)
-    fh = checked.result.failure_handler_version_id
-    version = await service.insert_version(
-        s,
-        ctx,
-        wf,
-        service.NewVersion(
-            id=version_id,
-            graph=graph_json(checked.graph),
-            node_refs=list(checked.result.node_refs),
-            engine_abi=ENGINE_ABI,
-            cel_profile=CURRENT_CEL_PROFILE,
-            subflow_version_ids=dict(checked.result.subflow_pins),
-            failure_handler_version_id=checked.result.failure_handler_version_id,
-            input_schema=dict(graph_settings.input_schema),
-            output_schema=dict(checked.result.output_schema),
-            vars_schema=dict(graph_settings.vars_schema),
-            closure_version_ids=[version_id, *sorted({i for v in pins for i in v.closure_version_ids}, key=str)],
-            closure_workflow_ids=[wf.id, *sorted({i for v in pins for i in v.closure_workflow_ids}, key=str)],
-            closure_node_refs=closure_node_refs,
-            closure_cel_profiles=closure_cel_profiles,
-            closure_depth=_depth(checked.pins),
-            expressions=[r.to_json() for r in checked.result.expressions],
-            tainted_sites=[{"node": node, "field": fld} for node, fld in checked.result.tainted_sites],
-            output_taint=dict(checked.result.output_taint),
-            open_scopes_cap=cap,
-            loop_depth=depth,
-            declassified=[
-                {"node": node, "field": fld, "reveals": reveals} for node, fld, reveals in checked.result.declassified
-            ],
-            connection_ids=sorted(
-                {named for _, _, named, _ in checked.result.connections}
-                | {named for _, _, _, named, _ in checked.result.pickers},
-                key=str,
-            ),
+    version = await service.insert_version(s, ctx, wf, frozen(checked, wf.id, cap, depth, version_id=version_id))
+    return Published(version, [], warnings)
+
+
+def frozen(
+    checked: Checked, workflow_id: uuid.UUID, cap: int, depth: int, *, version_id: uuid.UUID | None
+) -> service.NewVersion:
+    """What a version carries, from a checked draft: publish's, and a draft snapshot's (B8; the simulation design
+    §6.1). A version's closure starts with its own id; a snapshot isn't a version, nothing pins it, so its closure is
+    its pins' alone (`version_id` None)."""
+    if checked.graph is None or checked.result is None:
+        raise ValueError("a draft is frozen only once checked")
+    pins = list(checked.pins.values())
+    result, graph_settings = checked.result, checked.graph.settings
+    authored = graph_hash(checked.graph)
+    fh = result.failure_handler_version_id
+    return service.NewVersion(
+        id=version_id or uuid.uuid4(),
+        graph=graph_json(checked.graph),
+        node_refs=list(result.node_refs),
+        engine_abi=ENGINE_ABI,
+        cel_profile=CURRENT_CEL_PROFILE,
+        subflow_version_ids=dict(result.subflow_pins),
+        failure_handler_version_id=result.failure_handler_version_id,
+        input_schema=dict(graph_settings.input_schema),
+        output_schema=dict(result.output_schema),
+        vars_schema=dict(graph_settings.vars_schema),
+        closure_version_ids=[
+            *([version_id] if version_id else []),
+            *sorted({i for v in pins for i in v.closure_version_ids}, key=str),
+        ],
+        closure_workflow_ids=[workflow_id, *sorted({i for v in pins for i in v.closure_workflow_ids}, key=str)],
+        closure_node_refs=sorted({*result.node_refs, *(r for v in pins for r in v.closure_node_refs)}),
+        closure_cel_profiles=sorted({CURRENT_CEL_PROFILE, *(p for v in pins for p in v.closure_cel_profiles)}),
+        closure_depth=_depth(checked.pins),
+        expressions=[r.to_json() for r in result.expressions],
+        tainted_sites=[{"node": node, "field": fld} for node, fld in result.tainted_sites],
+        output_taint=dict(result.output_taint),
+        open_scopes_cap=cap,
+        loop_depth=depth,
+        declassified=[{"node": node, "field": fld, "reveals": reveals} for node, fld, reveals in result.declassified],
+        connection_ids=sorted(
+            {named for _, _, named, _ in result.connections} | {named for _, _, _, named, _ in result.pickers},
+            key=str,
+        ),
+        graph_hash=authored,
+        version_hash=version_hash(
             graph_hash=authored,
-            version_hash=version_hash(
-                graph_hash=authored,
-                subflow_pins=checked.result.subflow_pins,
-                failure_handler_version_id=str(fh) if fh else None,
-                cel_profile=CURRENT_CEL_PROFILE,
-                engine_abi=ENGINE_ABI,
-            ),
+            subflow_pins=result.subflow_pins,
+            failure_handler_version_id=str(fh) if fh else None,
+            cel_profile=CURRENT_CEL_PROFILE,
+            engine_abi=ENGINE_ABI,
         ),
     )
-    return Published(version, [], warnings)
+
+
+_DECLASSIFY_SIMULATING = Diagnostic(
+    code="declassify.forbidden",
+    field="/settings/declassify",
+    message="Simulating a draft that declassifies sensitive data needs the workflow.declassify permission "
+    "(tenant admins and owners).",
+)
+REPORTED = ("lifecycle.deprecated",)  # what the validator refuses for publish and a simulation only reports
+
+
+@dataclass(frozen=True)
+class Simulatable:
+    """A draft as a simulation freezes it (B8; the simulation design §6.3, steps 4 and 5): `new` unless something
+    blocks it; what it reports without refusing (connections, pickers, deprecated types: a simulation opens no
+    connection and runs what's installed today); the validator's warnings."""
+
+    new: service.NewVersion | None
+    blocking: list[Diagnostic]
+    reported: list[Diagnostic]
+    warnings: list[Diagnostic]
+
+
+async def simulatable(s: AsyncSession, ctx: TenantContext, wf: Workflow, checked: Checked) -> Simulatable:
+    """Blocking: any error but what's reported, `declassify.forbidden` (in a simulation's words), the sub-flows' cycle,
+    depth and engine ABI, retired types in the closure, `version.unbounded`. The current build is admission's."""
+    warnings = [d for d in checked.diagnostics if d.severity == "warning"]
+    reported = [d for d in checked.diagnostics if d.severity == "error" and d.code in REPORTED]
+    errors = [d for d in checked.diagnostics if d.severity == "error" and d.code not in REPORTED]
+    if checked.graph is None or checked.result is None or errors:
+        return Simulatable(None, errors, reported, warnings)
+    if checked.graph.settings.declassify and P.WORKFLOW_DECLASSIFY not in ROLE_PERMISSIONS[ctx.role]:
+        return Simulatable(None, [_DECLASSIFY_SIMULATING], reported, warnings)
+    pins = list(checked.pins.values())
+    errors = _pin_errors(wf.id, checked.pins) or await _pin_abi_errors(s, pins)
+    if errors:
+        return Simulatable(None, errors, reported, warnings)
+    closure_node_refs = sorted({*checked.result.node_refs, *(r for v in pins for r in v.closure_node_refs)})
+    closure_cel_profiles = sorted({CURRENT_CEL_PROFILE, *(p for v in pins for p in v.closure_cel_profiles)})
+    entries = lifecycle.entries_for(closure_node_refs, closure_cel_profiles)
+    await lifecycle.lock_shared(s, entries)
+    lifecycled = _lifecycle_errors(await lifecycle.states(s, entries), refuse_deprecated=True)
+    errors = [d for d in lifecycled if d.code not in REPORTED]
+    reported += [d for d in lifecycled if d.code in REPORTED and d.code not in {r.code for r in reported}]
+    if errors:
+        return Simulatable(None, errors, reported, warnings)
+    reported += await _connection_errors(s, ctx.tenant_id, checked.result.connections)
+    reported += await _picker_errors(s, ctx.tenant_id, checked.result.pickers)
+    reported += await _closure_connection_errors(
+        s, ctx.tenant_id, sorted({i for v in pins for i in v.closure_version_ids}, key=str)
+    )
+    try:
+        cap, depth = await _pinned(s, checked)
+    except BoundError as e:
+        return Simulatable(None, [Diagnostic(code="version.unbounded", message=str(e))], reported, warnings)
+    return Simulatable(frozen(checked, wf.id, cap, depth, version_id=None), [], reported, warnings)
 
 
 async def _pinned(s: AsyncSession, checked: Checked) -> tuple[int, int]:
diff --git a/backend/src/dewpoint/core/workflows/drafts.py b/backend/src/dewpoint/core/workflows/drafts.py
new file mode 100644
index 00000000..01ca4253
--- /dev/null
+++ b/backend/src/dewpoint/core/workflows/drafts.py
@@ -0,0 +1,52 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Draft snapshots (B8; the simulation design §6.1, §6.2): a workflow's draft frozen for a simulation, one per
+workflow and `version_hash`, and how admission's reuse of one holds off retention's sweep of it.
+
+Both take a transaction-scoped advisory lock keyed on the deduplication identity (tenant, workflow, `version_hash`),
+never the snapshot's id, so a snapshot made again after the sweep took it is held by the same lock. No row locks, so
+no UPDATE grant (as the admission lock reasons, `service.lock_for_admission`): admission inserts the snapshot if it's
+new, takes the lock shared, reads the row again in a fresh statement (READ COMMITTED), inserts it again if the sweep
+took it meanwhile, and its request names it before the lock is released, at commit. The sweep try-locks each candidate
+exclusively, skips it if busy, and deletes it only if, in a fresh statement, nothing names it."""
+
+import dataclasses
+import uuid
+
+from sqlalchemy import select, text
+from sqlalchemy.dialects.postgresql import insert
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.core.models.workflows import DraftSnapshot, Workflow
+from dewpoint.core.workflows.service import NewVersion
+
+_HELD = text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:k, 0))")
+
+
+def lock_key(tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_hash: str) -> str:
+    return f"dewpoint:draft:{tenant_id}:{workflow_id}:{version_hash}"
+
+
+async def snapshot_for(
+    s: AsyncSession, wf: Workflow, new: NewVersion, *, revision: int, created_by: uuid.UUID | None
+) -> DraftSnapshot:
+    """`new`'s snapshot of `wf`'s draft, found or inserted, then held against the sweep until this transaction ends. A
+    reused one keeps the revision and author of its first freezing."""
+    fields = {f.name: getattr(new, f.name) for f in dataclasses.fields(new) if f.name != "id"}
+    add = (
+        insert(DraftSnapshot)
+        .values(tenant_id=wf.tenant_id, workflow_id=wf.id, draft_revision=revision, created_by=created_by, **fields)
+        .on_conflict_do_nothing(constraint="draft_snapshots_hash")
+    )
+    await s.execute(add)
+    await s.execute(_HELD, {"k": lock_key(wf.tenant_id, wf.id, new.version_hash)})
+    for _ in range(2):  # a fresh statement: the sweep may have taken it before the lock was held
+        found = await s.execute(
+            select(DraftSnapshot)
+            .where(DraftSnapshot.workflow_id == wf.id, DraftSnapshot.version_hash == new.version_hash)
+            .execution_options(populate_existing=True)
+        )
+        snapshot = found.scalar_one_or_none()
+        if snapshot is not None:
+            return snapshot
+        await s.execute(add)
+    raise RuntimeError("a draft snapshot inserted under its lock wasn't found")
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 26 passed (publish's tests among them: `frozen` is publish's code moved).

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/workflow_ops.py backend/src/dewpoint/core/workflows/drafts.py \
  backend/tests/apps/test_draft_snapshots.py
git commit -m "feat(workflows): a draft frozen as its version would be, one snapshot per version hash (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Retention and erasure of draft snapshots

**Spec:** §6.2, §6.7.

**Files:**
- Modify: `backend/src/dewpoint/core/workflows/drafts.py` (`_found`, `sweep`)
- Modify: `backend/src/dewpoint/core/retention/sweep.py`, `backend/src/dewpoint/apps/erasure/stages.py`
- Modify: `backend/tests/core/retention/support.py`, `backend/tests/apps/erasure/support.py`
- Create: `backend/tests/core/retention/test_draft_snapshots.py`

**Interfaces:**
- Consumes: Task 3's `drafts.lock_key`, `drafts.snapshot_for`.
- Produces: `async drafts.sweep(s, tenant_id, n) -> tuple[int, int]` (chosen, deleted); `async drafts._found()`, a
  hook between the insert and the lock that tests replace; in `tests.core.retention.support`: `snapshot(owner, ctx,
  version_hash=None) -> uuid.UUID`, and `request`, `run` and `tree` taking `snapshot=`.

The sweep takes, per tenant, the snapshots no request or run names, try-locks each one's key exclusively, and deletes
it with a WHERE that checks again that nothing names it: an admission holding the shared lock keeps it, and an
admission that comes after the delete makes it again (ruling 8). It runs after the run trees and requests, in the
same batches, uncounted. An erasure sweeps `draft_snapshots` after `run_requests` and fences the table.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/erasure/support.py b/backend/tests/apps/erasure/support.py
index b288e5a7..65f60aea 100644
--- a/backend/tests/apps/erasure/support.py
+++ b/backend/tests/apps/erasure/support.py
@@ -13,15 +13,16 @@ from dewpoint.core.erasure import service
 from dewpoint.engine.runtime.ids import run_workflow_id
 from tests.core.erasure.test_fence import FENCED_TABLES
 from tests.core.ingress.support import KEYRING, digest, endpoint, key, record
-from tests.core.retention.support import CIPHER, OLD, request, sql, tree
+from tests.core.retention.support import CIPHER, OLD, request, snapshot, sql, tree
 from tests.support.workflows import seed_workflow
 
 
 async def populated(owner: Any, ingress: Any) -> dict[str, Any]:
-    """A tenant holding a row in each of its tables: its keys and keypair, a webhook endpoint with a pending event and
-    a binding, a workflow and version, a run tree that ended (its steps, claims, grants, secret index, request and
-    envelope, its evidence), a queued request, a schedule and a tick's record of a firing, a connection, a member, an
-    upload and a saved mapping, its retention, limits and a slot, and a plugin call's answer."""
+    """A tenant holding a row in each of its tables: its keys and keypair, a webhook endpoint with a pending event and a
+    binding, a workflow and version, a run tree that ended (its steps, claims, grants, secret index, request and
+    envelope, its evidence), a queued request, a draft snapshot and a queued simulation of it, a schedule and a tick's
+    record of a firing, a connection, a member, an upload and a saved mapping, its retention, limits and a slot, and a
+    plugin call's answer."""
     tenant, endpoint_id = await endpoint(owner)
     _, workflow_id, version_id = await seed_workflow(owner, tenant_id=tenant)
     async with owner() as s, s.begin():
@@ -31,6 +32,8 @@ async def populated(owner: Any, ingress: Any) -> dict[str, Any]:
     await record(ingress, endpoint_id, [(key(1), digest(1), b"one")])
     run_tree = await tree(owner, ctx, OLD)
     queued = await request(owner, ctx, "queued", None)
+    draft = await snapshot(owner, ctx)  # a draft simulation's, queued (B8): its request goes before it
+    await request(owner, ctx, "queued", None, snapshot=draft)
     schedule_id, release = uuid.uuid4(), uuid.uuid4()  # a release command (0057) and its snapshot
     for statement, params in (
         ("insert into memberships (tenant_id, user_id, role) values (:t, :u, 'owner')", {}),
diff --git a/backend/tests/core/retention/support.py b/backend/tests/core/retention/support.py
index d4b2e938..e7c75430 100644
--- a/backend/tests/core/retention/support.py
+++ b/backend/tests/core/retention/support.py
@@ -46,47 +46,69 @@ async def _claim(owner: Any, table: str, ctx: dict[str, Any], owner_run: uuid.UU
     return claim
 
 
+SNAPSHOT_FIELDS = (
+    "graph, node_refs, engine_abi, cel_profile, connection_ids, subflow_version_ids, failure_handler_version_id, "
+    "input_schema, output_schema, vars_schema, expressions, tainted_sites, output_taint, open_scopes_cap, loop_depth, "
+    "closure_version_ids, closure_workflow_ids, closure_node_refs, closure_cel_profiles, closure_depth, graph_hash"
+)
+
+
+async def snapshot(owner: Any, ctx: dict[str, Any], version_hash: str | None = None) -> uuid.UUID:
+    """A draft snapshot of the tenant's workflow (B8), its version's fields under `version_hash` (or a new one)."""
+    snapshot_id = uuid.uuid4()
+    await sql(owner, f"insert into draft_snapshots (id, tenant_id, workflow_id, draft_revision, version_hash, "  # noqa: S608
+              f"{SNAPSHOT_FIELDS}) select :i, tenant_id, workflow_id, 1, :h, {SNAPSHOT_FIELDS} "
+              "from workflow_versions where id = :v",
+              i=snapshot_id, h=version_hash or uuid.uuid4().hex * 2, v=ctx["v"])  # fmt: skip
+    return snapshot_id
+
+
 async def request(owner: Any, ctx: dict[str, Any], status: str, ago: timedelta | None,
-                  request_id: uuid.UUID | None = None) -> uuid.UUID:  # fmt: skip
-    """A request in `status`, ended `ago` when terminal, with its envelope and one claim unless refused."""
+                  request_id: uuid.UUID | None = None, snapshot: uuid.UUID | None = None) -> uuid.UUID:  # fmt: skip
+    """A request in `status`, ended `ago` when terminal, with its envelope and one claim unless refused; a draft
+    simulation's of `snapshot` when given."""
     rid = request_id or uuid.uuid4()
     envelope = None
     if status != "refused":
         envelope = await _claim(owner, "run_inputs", ctx, rid, rid, role="envelope")
         await _claim(owner, "run_inputs", ctx, rid, rid)
     terminal = status in ("cancelled", "refused", "dead")
-    await sql(owner, "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, source, mode, "
-              "idempotency_key, digest, digest_key_version, status, reason, envelope_id, queued_at, starting_at, "
-              "ended_at) values (:i, :t, :w, :v, 'manual', 'live', :k, :d, 1, :s, :reason, :e, "
-              "now() - interval '3 days', case when cast(:s as varchar) = 'starting' then now() end, "
+    await sql(owner, "insert into run_requests (id, tenant_id, workflow_id, workflow_version_id, draft_snapshot_id, "
+              "draft_revision, source, mode, idempotency_key, digest, digest_key_version, status, reason, envelope_id, "
+              "queued_at, starting_at, ended_at) values (:i, :t, :w, :v, :snap, :rev, 'manual', :m, :k, :d, 1, :s, "
+              ":reason, :e, now() - interval '3 days', case when cast(:s as varchar) = 'starting' then now() end, "
               "case when :terminal then now() - cast(:ago as interval) end)",
-              i=rid, t=ctx["t"], w=ctx["w"], v=ctx["v"], k=uuid.uuid4().hex, d=b"\x00" * 32, s=status,
+              i=rid, t=ctx["t"], w=ctx["w"], v=None if snapshot else ctx["v"], snap=snapshot,
+              rev=1 if snapshot else None, m="simulate" if snapshot else "live", k=uuid.uuid4().hex, d=b"\x00" * 32,
+              s=status,
               reason="r" if terminal else None, e=envelope, terminal=terminal, ago=ago or timedelta())  # fmt: skip
     return rid
 
 
 async def run(owner: Any, ctx: dict[str, Any], ago: timedelta | None, parent: uuid.UUID | None = None,
-              run_id: uuid.UUID | None = None) -> uuid.UUID:  # fmt: skip
-    """A run that ended `ago`, or is still running; a sub-run of `parent` when given."""
+              run_id: uuid.UUID | None = None, snapshot: uuid.UUID | None = None) -> uuid.UUID:  # fmt: skip
+    """A run that ended `ago`, or is still running; a sub-run of `parent` when given; a draft simulation of
+    `snapshot` when given."""
     rid = run_id or uuid.uuid4()
-    await sql(owner, "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, kind, "
-              "parent_run_id, queued_at, ended_at) values (:i, :t, :w, :v, 'live', :s, :k, :p, "
+    await sql(owner, "insert into runs (id, tenant_id, workflow_id, workflow_version_id, draft_snapshot_id, mode, "
+              "status, kind, parent_run_id, queued_at, ended_at) values (:i, :t, :w, :v, :snap, :m, :s, :k, :p, "
               "now() - interval '3 days', now() - cast(:ago as interval))",
-              i=rid, t=ctx["t"], w=ctx["w"], v=ctx["v"], s="running" if ago is None else "succeeded",
+              i=rid, t=ctx["t"], w=ctx["w"], v=None if snapshot else ctx["v"], snap=snapshot,
+              m="simulate" if snapshot else "live", s="running" if ago is None else "succeeded",
               k="run" if parent is None else "subflow", p=parent, ago=ago)  # fmt: skip
     return rid
 
 
 async def tree(owner: Any, ctx: dict[str, Any], ago: timedelta | None, *, request_status: str | None = "started",
-               sub_ago: timedelta | None | str = "same",
-               root: uuid.UUID | None = None) -> dict[str, uuid.UUID]:  # fmt: skip
+               sub_ago: timedelta | None | str = "same", root: uuid.UUID | None = None,
+               snapshot: uuid.UUID | None = None) -> dict[str, uuid.UUID]:  # fmt: skip
     """A run tree rooted in a run (`root`, or a new one) that ended `ago`: its request (`request_status`, or none, as a
     run from before 2b-2), a sub-run that ended with it (or `sub_ago`), a step of each, and claims of every kind on the
-    tree."""
+    tree. With `snapshot`, a draft simulation's, its sub-run a published version's, as a sub-flow in one is."""
     root = root or uuid.uuid4()
     if request_status is not None:
-        await request(owner, ctx, request_status, None, request_id=root)
-    await run(owner, ctx, ago, run_id=root)
+        await request(owner, ctx, request_status, None, request_id=root, snapshot=snapshot)
+    await run(owner, ctx, ago, run_id=root, snapshot=snapshot)
     sub = await run(owner, ctx, ago if sub_ago == "same" else sub_ago, parent=root)  # type: ignore[arg-type]
     for r in (root, sub):
         step = uuid.uuid4()
diff --git a/backend/tests/core/retention/test_draft_snapshots.py b/backend/tests/core/retention/test_draft_snapshots.py
new file mode 100644
index 00000000..1ad8b594
--- /dev/null
+++ b/backend/tests/core/retention/test_draft_snapshots.py
@@ -0,0 +1,101 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Retention's sweep of draft snapshots (B8; the simulation design §6.2, §6.7): a snapshot no request or run names
+goes, after the trees that named it; one an admission is reusing never does, in either order: the admission holding
+its lock keeps the sweep off, and one the sweep took before the lock was held is made again."""
+
+import asyncio
+import dataclasses
+import uuid
+from typing import Any
+
+from sqlalchemy import text
+
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.models.workflows import WorkflowVersion
+from dewpoint.core.retention import sweep
+from dewpoint.core.workflows import drafts, service
+from tests.core.retention.support import OLD, RECENT, count, request, snapshot, tenant, tree
+
+SNAPSHOTS = "select count(*) from draft_snapshots where tenant_id = :t"
+
+
+async def new_version(owner: Any, ctx: dict[str, Any], version_hash: str) -> service.NewVersion:
+    """The tenant's version, as a draft frozen under `version_hash` would carry it."""
+    async with owner() as s:
+        v = await s.get(WorkflowVersion, ctx["v"])
+        assert v is not None
+        names = {f.name for f in dataclasses.fields(service.NewVersion)} - {"id", "version_hash", "declassified"}
+        return service.NewVersion(id=uuid.uuid4(), version_hash=version_hash, **{n: getattr(v, n) for n in names})
+
+
+async def admitted(api: Any, ctx: dict[str, Any], new: service.NewVersion, hold: asyncio.Event | None = None,
+                   released: asyncio.Event | None = None) -> uuid.UUID:  # fmt: skip
+    """An admission's reuse of the snapshot of `new`: held (`hold` set) until `released`, then committed."""
+    async with api() as s, s.begin():
+        await tenant_scope(s, ctx["t"])
+        wf = await service.get_workflow(s, ctx["t"], ctx["w"])
+        assert wf is not None
+        found = await drafts.snapshot_for(s, wf, new, revision=1, created_by=None)
+        if hold is not None and released is not None:
+            hold.set()
+            await released.wait()
+        return found.id
+
+
+async def test_the_sweep_takes_a_snapshot_nothing_names_and_keeps_the_ones_named(
+    owner_sessionmaker, retention_sessionmaker
+) -> None:
+    ctx = await tenant(owner_sessionmaker)  # a retention of a day
+    await snapshot(owner_sessionmaker, ctx)  # nothing names it
+    queued = await snapshot(owner_sessionmaker, ctx)
+    await request(owner_sessionmaker, ctx, "queued", None, snapshot=queued)
+    recent = await snapshot(owner_sessionmaker, ctx)
+    await tree(owner_sessionmaker, ctx, RECENT, snapshot=recent)
+    old = await snapshot(owner_sessionmaker, ctx)
+    await tree(owner_sessionmaker, ctx, OLD, snapshot=old)  # its tree goes first, in the same sweep
+    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])
+    async with owner_sessionmaker() as s:
+        left = set((await s.execute(text("select id from draft_snapshots where tenant_id = :t"), {"t": ctx["t"]}))
+                   .scalars())  # fmt: skip
+    assert left == {queued, recent}
+
+
+async def test_a_snapshot_an_admission_holds_is_never_swept(
+    owner_sessionmaker, api_sessionmaker, retention_sessionmaker
+) -> None:
+    ctx = await tenant(owner_sessionmaker)
+    kept = await snapshot(owner_sessionmaker, ctx, version_hash="a" * 64)
+    hold, released = asyncio.Event(), asyncio.Event()
+    admission = asyncio.create_task(
+        admitted(api_sessionmaker, ctx, await new_version(owner_sessionmaker, ctx, "a" * 64), hold, released)
+    )
+    await hold.wait()
+    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])  # its try-lock finds the admission's: it skips it
+    assert await count(owner_sessionmaker, SNAPSHOTS, t=ctx["t"]) == 1
+    released.set()
+    assert await admission == kept
+    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])  # nothing holds or names it now
+    assert await count(owner_sessionmaker, SNAPSHOTS, t=ctx["t"]) == 0
+
+
+async def test_a_snapshot_the_sweep_takes_before_an_admission_holds_it_is_made_again(
+    owner_sessionmaker, api_sessionmaker, retention_sessionmaker, monkeypatch
+) -> None:
+    ctx = await tenant(owner_sessionmaker)
+    taken = await snapshot(owner_sessionmaker, ctx, version_hash="b" * 64)
+    found, go = asyncio.Event(), asyncio.Event()
+
+    async def paused() -> None:  # the admission found the snapshot and holds nothing yet
+        found.set()
+        await go.wait()
+
+    monkeypatch.setattr(drafts, "_found", paused)
+    admission = asyncio.create_task(
+        admitted(api_sessionmaker, ctx, await new_version(owner_sessionmaker, ctx, "b" * 64))
+    )
+    await found.wait()
+    await sweep.sweep_tenant(retention_sessionmaker, ctx["t"])
+    assert await count(owner_sessionmaker, SNAPSHOTS, t=ctx["t"]) == 0
+    go.set()
+    again = await admission
+    assert again != taken and await count(owner_sessionmaker, SNAPSHOTS, t=ctx["t"]) == 1
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/core/retention/test_draft_snapshots.py`

Only the new tests: the erasure suite isn't run before the implementation. Its tenant now holds a snapshot and a
queued draft request, which an erasure can't delete yet, so twelve of its tests wait out their timeouts and fail (24
minutes in the check, past the 10 a run may take unasked).

Expected: FAIL, 3 failed: `drafts` has no attribute `_found`; the sweep deletes nothing, so the snapshot nothing names
is still there (`assert {…} == {…}`, extra items); once the admission that held a snapshot is gone, the snapshot isn't
swept either (`assert 1 == 0`).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/erasure/stages.py b/backend/src/dewpoint/apps/erasure/stages.py
index c9f6eb55..88fdccc6 100644
--- a/backend/src/dewpoint/apps/erasure/stages.py
+++ b/backend/src/dewpoint/apps/erasure/stages.py
@@ -455,7 +455,7 @@ SWEPT: tuple[tuple[str, str], ...] = (
     ("claim_grants", "claim_id, run_id"), ("step_outputs", "id"), ("run_secret_index", "root_run_id"),
     ("run_slots", "run_id"), ("execution_evidence", "id"), ("schedule_firings", "workflow_id, run_id"),
     ("schedule_incarnations", "temporal_id"), ("schedule_intervals", "id"), ("runs", "root_run_id"),
-    ("run_requests", "id"), ("run_inputs", "id"), ("inbound_events", "id"),
+    ("run_requests", "id"), ("draft_snapshots", "id"), ("run_inputs", "id"), ("inbound_events", "id"),
     ("trigger_bindings", "id"), ("webhook_endpoints", "id"), ("tenant_event_counters", "tenant_id"),
     ("csv_mappings", "workflow_id"), ("csv_uploads", "id"), ("schedules", "id"), ("workflow_versions", "id"),
     ("workflows", "id"), ("plugin_calls", "id"),  # 0042's: an options call names no connection, so nothing cascades
diff --git a/backend/src/dewpoint/core/retention/sweep.py b/backend/src/dewpoint/core/retention/sweep.py
index 1f73a01b..8e442e84 100644
--- a/backend/src/dewpoint/core/retention/sweep.py
+++ b/backend/src/dewpoint/core/retention/sweep.py
@@ -30,6 +30,7 @@ from dewpoint.core.db import tenant_scope
 from dewpoint.core.ingress.counters import lock_tenant_shared
 from dewpoint.core.models.retention import RetentionSweep
 from dewpoint.core.retention import policy
+from dewpoint.core.workflows import drafts
 
 log = structlog.get_logger("dewpoint.retention")
 BATCH = 100
@@ -243,6 +244,13 @@ async def sweep_tenant(
             pruned = (await s.execute(_FIRINGS, {"kept": FIRINGS_KEPT, "n": batch})).rowcount  # type: ignore[attr-defined]
         if pruned < batch:
             break
+    while True:  # draft snapshots nothing names now, the trees that named them gone (B8; the simulation design §6.2)
+        async with sessionmaker() as s, s.begin():
+            if not await _active(s, tenant_id):
+                return swept
+            chosen, deleted = await drafts.sweep(s, tenant_id, batch)
+        if chosen < batch or deleted == 0:  # the rest of a full batch are held: the next sweep takes them
+            break
     async with sessionmaker() as s, s.begin():
         await tenant_scope(s, tenant_id)
         swept.lag_s = float((await s.execute(_LAG, {"cutoff": await _cutoff(s, tenant_id)})).scalar_one())
diff --git a/backend/src/dewpoint/core/workflows/drafts.py b/backend/src/dewpoint/core/workflows/drafts.py
index 01ca4253..4f35927f 100644
--- a/backend/src/dewpoint/core/workflows/drafts.py
+++ b/backend/src/dewpoint/core/workflows/drafts.py
@@ -20,6 +20,20 @@ from dewpoint.core.models.workflows import DraftSnapshot, Workflow
 from dewpoint.core.workflows.service import NewVersion
 
 _HELD = text("SELECT pg_advisory_xact_lock_shared(hashtextextended(:k, 0))")
+_TRY = text("SELECT pg_try_advisory_xact_lock(hashtextextended(:k, 0))")
+_UNNAMED = (
+    "NOT EXISTS (SELECT 1 FROM run_requests q WHERE q.draft_snapshot_id = s.id) "
+    "AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.draft_snapshot_id = s.id)"
+)
+_CANDIDATES = text(
+    f"SELECT s.id, s.workflow_id, s.version_hash FROM draft_snapshots s WHERE {_UNNAMED} "  # noqa: S608
+    "ORDER BY s.created_at, s.id LIMIT :n"
+)
+_DELETE = text(f"DELETE FROM draft_snapshots s WHERE s.id = :id AND {_UNNAMED}")  # noqa: S608
+
+
+async def _found() -> None:
+    """Hook between finding or inserting the snapshot and holding its lock. A no-op; the race tests pause here."""
 
 
 def lock_key(tenant_id: uuid.UUID, workflow_id: uuid.UUID, version_hash: str) -> str:
@@ -38,6 +52,7 @@ async def snapshot_for(
         .on_conflict_do_nothing(constraint="draft_snapshots_hash")
     )
     await s.execute(add)
+    await _found()
     await s.execute(_HELD, {"k": lock_key(wf.tenant_id, wf.id, new.version_hash)})
     for _ in range(2):  # a fresh statement: the sweep may have taken it before the lock was held
         found = await s.execute(
@@ -51,2 +66,13 @@ async def snapshot_for(
         await s.execute(add)
     raise RuntimeError("a draft snapshot inserted under its lock wasn't found")
+
+
+async def sweep(s: AsyncSession, tenant_id: uuid.UUID, n: int) -> tuple[int, int]:
+    """Up to `n` of the tenant's snapshots no request or run names, each deleted unless an admission holds it: (chosen,
+    deleted). The caller holds the tenant's scope."""
+    chosen = (await s.execute(_CANDIDATES, {"n": n})).all()
+    deleted = 0
+    for snapshot_id, workflow_id, version_hash in chosen:
+        if (await s.execute(_TRY, {"k": lock_key(tenant_id, workflow_id, version_hash)})).scalar():
+            deleted += (await s.execute(_DELETE, {"id": snapshot_id})).rowcount  # type: ignore[attr-defined]
+    return len(chosen), deleted
```

- [ ] **Step 4: Run them again, with retention and erasure whole**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/core/retention tests/apps/erasure tests/core/erasure`

Expected: PASS, 165 passed (about 5 minutes: the erasure tests are slow).

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/core/workflows/drafts.py backend/src/dewpoint/core/retention/sweep.py \
  backend/src/dewpoint/apps/erasure/stages.py backend/tests/core/retention/support.py \
  backend/tests/apps/erasure/support.py backend/tests/core/retention/test_draft_snapshots.py
git commit -m "feat(retention): draft snapshots nothing names are swept, never one an admission holds (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: The milestone's ledger entry and the pause**

Append `### 4d-1b, milestone 1 (date)`: the tasks' commits, each task's tests as run, the static checks, every
mid-slice ruling. Commit (`docs(editor-4): 4d-1b milestone 1`). Then **stop** for the owner's review.

---

# Milestone 2 — Admission and execution

### Task 5: Admitting a draft simulation

**Spec:** §6.3, §5.2 (the three states, "Nothing outside the contract", "A value given").

**Files:**
- Modify: `backend/src/dewpoint/apps/admission.py` (`Simulation`, `admit_draft`, `_draft_frozen`, `_seeded`, `_open`,
  `_current_build`, `DraftInvalidError`, `SeedsRefusedError`, `TARGET_INVALID`, `SEED_CODES`)
- Modify: `backend/src/dewpoint/apps/inputs.py` (`checked`, `claim_input`: `against_schema`)
- Modify: `backend/src/dewpoint/apps/workflow_ops.py` (`Checked.context`)
- Modify: `backend/src/dewpoint/core/requests/digest.py` (`draft`)
- Create: `backend/tests/apps/test_admission_drafts.py`
- Modify: `backend/tests/core/requests/test_digest.py`

**Interfaces:**
- Consumes: Task 3's `simulatable`, `snapshot_for`; 4d-1a's `seeds.contract(graph, ctx, node)` and
  `seeds.check(contract,
  values, absent) -> list[SeedProblem]`.
- Produces: `admission.Simulation(revision: int, target: uuid.UUID | None = None, values: dict = {}, absent:
  tuple[str, ...] = ())`; `async admission.admit_draft(s, keys, ctx, *, workflow_id, idempotency_key, input,
  simulation, settings) -> Admitted`; `admission.DraftInvalidError(blocking, reported, warnings)`;
  `admission.SeedsRefusedError(problems)` with `.reason` (the first of `SEED_CODES` its problems hold);
  `admission.TARGET_INVALID`; `inputs.claim_input(..., against_schema: bool = True)`; `digest(..., draft=None)`;
  `workflow_ops.Checked.context` (the validation context, which the seed contract reads again).

`admit_draft` follows §6.3's order: the key first (an exact retry returns its request, whatever the draft became);
the tenant and the gate; the workflow's admission lock, enabled or not, published or not (D-b1); the revision (409
`draft_conflict`, `DraftConflictError`); the draft (`simulatable`: `DraftInvalidError` with what blocks); the current
build, of the snapshot's ABI and its pins'; the input against the draft's trigger schema, or the seeds against the
step's contract (`SeedsRefusedError`; `target_invalid` for a step that can't run alone), claimed (ruling 6); the
snapshot found or made; the request, its digest grown by the draft's identity (ruling 7), its source `manual` (ruling
1), its `admission_checks` the reported problems; one `run.request` audit entry naming the snapshot, the revision, the
graph hash, the target and the declassified sites.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/test_admission_drafts.py b/backend/tests/apps/test_admission_drafts.py
new file mode 100644
index 00000000..48a56563
--- /dev/null
+++ b/backend/tests/apps/test_admission_drafts.py
@@ -0,0 +1,219 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A draft simulation's admission (B8; the simulation design §6.3): frozen on a snapshot of the revision it names, of
+a workflow never published or disabled; an exact retry is the original request whatever the draft became; what can't
+run blocks it, what a simulation never meets is reported and kept; the input checked against the draft's trigger
+schema, or a step's seeds against its contract, claimed where sensitive (S2)."""
+
+import uuid
+from datetime import timedelta
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps import admission
+from dewpoint.apps.inputs import RESERVED_INPUT
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.db import tenant_scope
+from dewpoint.core.plugins import lifecycle
+from dewpoint.core.workflows import service
+from dewpoint.engine import ENGINE_ABI
+from tests.apps.test_admission import KEYS, OPEN_GRAPH, TOKEN, TOKEN_GRAPH, current
+from tests.apps.test_workflow_ops import ECHO, ECHO_GRAPH, actor, create, save, update
+from tests.support.graphs import G, nid, ref
+from tests.support.registry import sync_test_plugins
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+STEPS = (
+    G().node("a", "testkit.echo@1", {"value": 1}).node("b", "testkit.echo@1", {"value": ref("steps.a.output.value")})
+)
+STEPS_GRAPH = STEPS.edge("a", "b").data() | {"settings": {"input_schema": {"type": "object"}}}
+SENSITIVE_READ = G().node("t", "testkit.echo@1", {"value": ref("trigger.token")}).data() | {
+    "settings": {"input_schema": TOKEN_GRAPH["settings"]["input_schema"]}
+}
+PLAIN_READ = G().node("p", "testkit.echo@1", {"value": ref("trigger.site")}).data() | {
+    "settings": {"input_schema": {"type": "object", "properties": {"site": {"type": "string"}}, "required": ["site"]}}
+}
+LOOP_GRAPH = (
+    G().node("l", "flow.loop@1", {"items": [1, 2]}).node("x", "testkit.echo@1", {"value": ref("item")})
+    .edge("l", "x", "body").data() | {"settings": {"input_schema": {"type": "object"}}}
+)  # fmt: skip
+
+
+async def drafted(owner: Any, api: Any, admin: Any, graph: Any = OPEN_GRAPH) -> tuple[Any, uuid.UUID]:
+    """A workflow with a draft, never published."""
+    await sync_test_plugins(admin)
+    ctx = await actor(owner)
+    return ctx, await create(api, ctx, graph)
+
+
+async def simulate(api: Any, ctx: Any, wf: uuid.UUID, settings: Any, *, key: str = "s1", revision: int = 1,
+                   input: dict[str, Any] | None = None, target: uuid.UUID | None = None,
+                   values: dict[str, Any] | None = None, absent: tuple[str, ...] = (),
+                   ) -> admission.Admitted:  # fmt: skip
+    async with api() as s, s.begin():
+        return await admission.admit_draft(
+            s, KEYS, ctx, workflow_id=wf, idempotency_key=key, input=input or {},
+            simulation=admission.Simulation(revision, target, values or {}, absent), settings=settings,
+        )  # fmt: skip
+
+
+async def envelope(dispatch: Any, ctx: Any, request_id: uuid.UUID) -> Any:
+    async with dispatch() as s, s.begin():
+        await tenant_scope(s, ctx.tenant_id)
+        return await claims.read_envelope(s, ClaimCipher(KEYS), ctx.tenant_id, request_id=request_id)
+
+
+@pytest.fixture
+async def built(dispatch_sessionmaker) -> None:
+    await current(dispatch_sessionmaker)
+
+
+@pytest.mark.usefixtures("built")
+async def test_a_draft_is_simulated_on_a_snapshot_of_its_revision_published_or_not(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    """D-b1: a workflow never published, or disabled, is simulated: testing before the first publish is the point."""
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker)
+    r = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
+    assert (r.status, r.source, r.mode, r.workflow_version_id, r.draft_revision, r.target_step_id) == (
+        "queued", "manual", "simulate", None, 1, None,
+    )  # fmt: skip
+    async with owner_sessionmaker() as s:
+        found = text("select workflow_id, draft_revision, created_by, graph_hash from draft_snapshots where id = :i")
+        snapshot = (await s.execute(found, {"i": r.draft_snapshot_id})).one()
+        details = (await s.execute(text("select details from audit_log where action = 'run.request'"))).scalar_one()
+    assert snapshot[:3] == (wf, 1, ctx.user.id)
+    assert details == {"workflow_id": str(wf), "source": "manual", "mode": "simulate", "status": "queued",
+                       "draft_snapshot_id": str(r.draft_snapshot_id), "draft_revision": 1,
+                       "graph_hash": snapshot.graph_hash}  # fmt: skip
+    await update(api_sessionmaker, ctx, wf, enabled=False)
+    again = await simulate(api_sessionmaker, ctx, wf, api_settings, key="s2")
+    assert again.new and again.request.draft_snapshot_id == r.draft_snapshot_id  # the same draft: its snapshot
+
+
+@pytest.mark.usefixtures("built")
+async def test_a_revision_the_draft_moved_past_is_refused(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker)
+    await save(api_sessionmaker, ctx, wf, OPEN_GRAPH)
+    with pytest.raises(service.DraftConflictError) as refused:
+        await simulate(api_sessionmaker, ctx, wf, api_settings, revision=1)
+    assert refused.value.current_revision == 2
+
+
+@pytest.mark.usefixtures("built")
+async def test_an_exact_retry_is_the_original_request_whatever_the_draft_became(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    """Spec §6.3, step 1: the key first; a retry never rebuilds today's draft, nor meets a later refusal."""
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker)
+    first = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"site": "a"})).request
+    await save(api_sessionmaker, ctx, wf, G().node("z", "no.such@1").data())  # revision 2: it wouldn't validate
+    retry = await simulate(api_sessionmaker, ctx, wf, api_settings, input={"site": "a"})
+    assert (retry.new, retry.request.id, retry.request.draft_snapshot_id) == (False, first.id, first.draft_snapshot_id)
+    for changed in ({"input": {"site": "b"}}, {"revision": 2}, {"target": nid("a")}):
+        with pytest.raises(admission.IdempotencyConflictError):
+            await simulate(api_sessionmaker, ctx, wf, api_settings, **{"input": {"site": "a"}, **changed})
+
+
+@pytest.mark.usefixtures("built")
+async def test_what_cant_run_blocks_and_what_a_simulation_never_meets_is_reported(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker,
+                            G().node("z", "no.such@1").data())  # fmt: skip
+    with pytest.raises(admission.DraftInvalidError) as invalid:
+        await simulate(api_sessionmaker, ctx, wf, api_settings)
+    assert [d.code for d in invalid.value.blocking] == ["node.unknown_type"]
+    echo = await create(api_sessionmaker, ctx, ECHO_GRAPH, name="echo")
+    async with admin_sessionmaker() as s, s.begin():
+        await lifecycle.deprecate(s, ECHO, actor_id=None)
+    r = (await simulate(api_sessionmaker, ctx, echo, api_settings, key="s2")).request
+    assert [c["code"] for c in r.admission_checks or []] == ["lifecycle.deprecated"]
+
+
+@pytest.mark.usefixtures("built")
+async def test_the_input_is_checked_against_the_drafts_trigger_schema_and_claimed(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, TOKEN_GRAPH)
+    for refused, key in (({"site": "a"}, "s1"), ({"token": TOKEN, "rows": []}, "s2")):
+        with pytest.raises(admission.AdmissionRefusedError) as e:
+            await simulate(api_sessionmaker, ctx, wf, api_settings, key=key, input=refused)
+        assert e.value.reason == "input_invalid"
+    assert e.value.messages == [RESERVED_INPUT]
+    r = (await simulate(api_sessionmaker, ctx, wf, api_settings, key="s3", input={"token": TOKEN})).request
+    assert "$claim" in (await envelope(dispatch_sessionmaker, ctx, r.id))["token"]
+
+
+async def test_a_simulation_needs_a_current_build_of_its_abi(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker)
+    await current(dispatch_sessionmaker, age=timedelta(minutes=5))
+    with pytest.raises(admission.AdmissionRefusedError) as e:
+        await simulate(api_sessionmaker, ctx, wf, api_settings)
+    assert e.value.reason == "no_current_build"
+    await current(dispatch_sessionmaker, abi=ENGINE_ABI + 1)
+    with pytest.raises(admission.AdmissionRefusedError) as e:
+        await simulate(api_sessionmaker, ctx, wf, api_settings)
+    assert e.value.reason == "version_unusable"
+
+
+@pytest.mark.usefixtures("built")
+async def test_a_step_is_simulated_alone_with_its_seeds_sensitive_ones_claimed(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """S2 (the simulation design §5.3): a seed is split as the run's input is; one the contract marks sensitive (a
+    sensitive input, a tainted step's output) is a handle in the envelope, as the run's own value would be."""
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, PLAIN_READ)
+    r = (
+        await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("p"), values={"/trigger/site": "a"})
+    ).request
+    assert (r.target_step_id, r.mode) == (nid("p"), "simulate")
+    assert await envelope(dispatch_sessionmaker, ctx, r.id) == {"values": {"/trigger/site": "a"}, "absent": []}
+    for n, (graph, target, pointer, value) in enumerate([
+        (SENSITIVE_READ, nid("t"), "/trigger/token", TOKEN),
+        (STEPS_GRAPH, nid("b"), "/steps/a/output/value", 5),  # an echo's output is tainted
+    ]):  # fmt: skip
+        other = await create(api_sessionmaker, ctx, graph, name=f"w{n}")
+        r = (await simulate(api_sessionmaker, ctx, other, api_settings, key=f"k{n}", target=target,
+                            values={pointer: value})).request  # fmt: skip
+        assert "$claim" in (await envelope(dispatch_sessionmaker, ctx, r.id))["values"][pointer]
+
+
+@pytest.mark.usefixtures("built")
+async def test_seeds_the_contract_doesnt_take_are_refused_naming_each(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
+    cases = [  # (values, absent, the refusal's code, its pointers)
+        ({}, (), "seed_missing", ["/steps/a/output/value"]),
+        ({"/steps/a/output/value": 5, "/trigger/x": 1}, (), "seed_unknown", ["/trigger/x"]),
+        ({"/steps/a/output/value": 5, "/run/id": "r"}, (), "seed_unknown", ["/run/id"]),
+    ]
+    for n, (values, absent, code, pointers) in enumerate(cases):
+        with pytest.raises(admission.SeedsRefusedError) as e:
+            await simulate(api_sessionmaker, ctx, wf, api_settings, key=f"k{n}", target=nid("b"), values=values,
+                           absent=absent)  # fmt: skip
+        assert (e.value.reason, [p.pointer for p in e.value.problems]) == (code, pointers)
+    looped = await create(api_sessionmaker, ctx, LOOP_GRAPH, name="loop")
+    with pytest.raises(admission.SeedsRefusedError) as e:
+        await simulate(api_sessionmaker, ctx, looped, api_settings, key="alias", target=nid("x"),
+                       values={"/loops/l/item": 1})  # fmt: skip
+    assert e.value.reason == "seed_alias"
+
+
+@pytest.mark.usefixtures("built")
+async def test_a_step_that_cant_run_alone_is_refused(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOP_GRAPH)
+    for n, target in enumerate((nid("l"), uuid.uuid4())):  # a loop; no step of the draft
+        with pytest.raises(admission.AdmissionRefusedError) as e:
+            await simulate(api_sessionmaker, ctx, wf, api_settings, key=f"t{n}", target=target)
+        assert e.value.reason == "target_invalid"
diff --git a/backend/tests/core/requests/test_digest.py b/backend/tests/core/requests/test_digest.py
index 565cf9a4..18dc8631 100644
--- a/backend/tests/core/requests/test_digest.py
+++ b/backend/tests/core/requests/test_digest.py
@@ -39,3 +39,19 @@ async def test_a_stored_digest_is_compared_with_its_own_key_version_after_a_rota
     assert version == 2 and fresh != stored
     assert await d.matches(rotated, TENANT, stored, 1, **REQUEST)
     assert not await d.matches(rotated, TENANT, stored, 1, **{**REQUEST, "mode": "simulate"})
+
+
+async def test_a_draft_simulation_digests_its_draft_and_any_other_request_keeps_its_bytes() -> None:
+    """B8 (the simulation design §6.3, step 1): a draft simulation's digest covers its revision, target and seeds; a
+    request that isn't one is digested as before, byte for byte."""
+    keys = FixtureKeys()
+    assert d.canonical(**REQUEST) == (
+        b'{"input":{"pin":"1234","site":"a"},"mode":"live","source":"manual",'
+        b'"workflow_id":"00000000-0000-0000-0000-000000000003"}'
+    )
+    _, plain = await d.digest(keys, TENANT, **REQUEST)
+    _, drafted = await d.digest(keys, TENANT, **REQUEST, draft={"draft_revision": 2})
+    _, later = await d.digest(keys, TENANT, **REQUEST, draft={"draft_revision": 3})
+    assert len({plain, drafted, later}) == 3
+    assert await d.matches(keys, TENANT, drafted, 1, **REQUEST, draft={"draft_revision": 2})
+    assert not await d.matches(keys, TENANT, drafted, 1, **REQUEST)
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/test_admission_drafts.py
tests/core/requests/test_digest.py tests/apps/test_admission.py tests/apps/test_admission_csv.py
tests/apps/test_admission_gate.py tests/apps/test_admission_retirement.py tests/apps/test_inputs.py
tests/apps/test_workflow_ops.py`

Expected: FAIL, 10 failed and 91 passed: the nine admission tests find no `admit_draft`, `DraftInvalidError` or
`SeedsRefusedError` in `dewpoint.apps.admission` (AttributeError); the digest's test finds `digest()` takes no `draft`
(TypeError). Every existing admission, input and publish test passes.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/admission.py b/backend/src/dewpoint/apps/admission.py
index 6994ca37..843f6f9a 100644
--- a/backend/src/dewpoint/apps/admission.py
+++ b/backend/src/dewpoint/apps/admission.py
@@ -27,7 +27,7 @@ upload, all in the same savepoint."""
 
 import asyncio
 import uuid
-from dataclasses import asdict, dataclass
+from dataclasses import asdict, dataclass, field
 from datetime import timedelta
 from typing import Any
 
@@ -35,25 +35,30 @@ from sqlalchemy import func, select, update
 from sqlalchemy.dialects.postgresql import insert
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from dewpoint.apps import csv_uploads
+from dewpoint.apps import csv_uploads, workflow_ops
 from dewpoint.apps.csv_input import Built, CsvFileError, RowError, build_rows, mapping_problems, read_table
 from dewpoint.apps.inputs import INPUT_INVALID, RESERVED_INPUT, TOO_DEEP, InputRefusedError, claim_input, nests_too_deep
 from dewpoint.apps.workflow_ops import abi_reasons
 from dewpoint.core.audit import service as audit
 from dewpoint.core.claims import service as claims
 from dewpoint.core.claims.cipher import ClaimCipher
+from dewpoint.core.config import Settings
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.db import tenant_scope
+from dewpoint.core.http import TenantContext
 from dewpoint.core.models.requests import CurrentBuild, RunRequest
 from dewpoint.core.models.tenancy import Tenant
 from dewpoint.core.models.uploads import CsvUpload
-from dewpoint.core.models.workflows import WorkflowVersion
+from dewpoint.core.models.workflows import Workflow, WorkflowVersion
 from dewpoint.core.platform.service import NOT_RECORDED, PRODUCTION, recorded
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.requests import digest as digests
 from dewpoint.core.tenancy import lifecycle as tenant_lifecycle
-from dewpoint.core.workflows.service import lock_for_admission, other_abi
+from dewpoint.core.workflows import drafts
+from dewpoint.core.workflows.service import DraftConflictError, lock_for_admission, other_abi
+from dewpoint.engine.graph import seeds
 from dewpoint.engine.graph.csv import RESERVED, trigger_schema
+from dewpoint.engine.graph.diagnostics import Diagnostic
 from dewpoint.engine.runtime.activities import LIVE, SIMULATE
 
 INTERACTIVE = ("manual", "rerun", "dev")  # refused while the gate is off; a refusal is raised
@@ -76,6 +81,9 @@ CSV_MAPPING_INVALID = "csv_mapping_invalid"
 UPLOAD_NOT_FOUND = "upload_not_found"
 UPLOAD_EXPIRED = "upload_expired"
 UPLOAD_CONSUMED = "upload_consumed"
+TARGET_INVALID = "target_invalid"
+# A seeds refusal's code (S2; the simulation design §5.2): the first of these among its problems, every problem listed.
+SEED_CODES = (seeds.SEED_ALIAS, seeds.SEED_UNKNOWN, seeds.SEED_MISSING, seeds.SEED_INVALID)
 _LISTED = 5  # a refusal lists this many of the CSV's problems
 
 GATE_OFF = (
@@ -104,6 +112,25 @@ class WorkflowNotFoundError(LookupError):
     """No such workflow in the caller's tenant."""
 
 
+class DraftInvalidError(Exception):
+    """A draft simulation's draft that can't run (B8; the simulation design §6.3, step 4): what blocks it, with what it
+    would report and the validator's warnings."""
+
+    def __init__(self, blocking: list[Diagnostic], reported: list[Diagnostic], warnings: list[Diagnostic]) -> None:
+        super().__init__("; ".join(d.code for d in blocking))
+        self.blocking, self.reported, self.warnings = blocking, reported, warnings
+
+
+class SeedsRefusedError(Exception):
+    """A step's seeds its contract doesn't take (S2; the simulation design §5.2): every problem, and the refusal's code,
+    the first of `SEED_CODES` among them."""
+
+    def __init__(self, problems: list[seeds.SeedProblem]) -> None:
+        super().__init__("; ".join(f"{p.code} {p.pointer}" for p in problems))
+        self.problems = problems
+        self.reason = next(code for code in SEED_CODES if any(p.code == code for p in problems))
+
+
 @dataclass(frozen=True)
 class CsvStart:
     """A start's CSV: the staged upload, the mapping from declared column names to its headers, and whether rows that
@@ -134,6 +161,24 @@ class Rerun:
         return digested
 
 
+@dataclass(frozen=True)
+class Simulation:
+    """A draft simulation's identity (B8; the simulation design §6.3): the draft revision it simulates, and for a step
+    alone (S2) its target and seeds, given or absent by pointer. Its idempotency digest covers it beside the input, so
+    the digests of the requests that aren't simulations keep their bytes."""
+
+    revision: int
+    target: uuid.UUID | None = None
+    values: dict[str, Any] = field(default_factory=dict)
+    absent: tuple[str, ...] = ()
+
+    def digested(self) -> dict[str, Any]:
+        digested: dict[str, Any] = {"draft_revision": self.revision}
+        if self.target is not None:
+            digested |= {"target": str(self.target), "values": self.values, "absent": sorted(self.absent)}
+        return digested
+
+
 @dataclass(frozen=True)
 class Admitted:
     request: RunRequest
@@ -156,6 +201,16 @@ class _Frozen:
     details: dict[str, object]  # the audit entry's, beyond the request's own
 
 
+@dataclass(frozen=True)
+class _DraftFrozen:
+    snapshot_id: uuid.UUID
+    envelope_id: uuid.UUID
+    revision: int
+    target: uuid.UUID | None
+    checks: list[dict[str, Any]]  # what it reports, kept on the request
+    details: dict[str, object]
+
+
 async def _before_insert() -> None:
     """Runs between a new request's claims and its insert. A no-op; the race tests commit a competing request here."""
 
@@ -228,6 +283,48 @@ async def admit_request(
     return admitted
 
 
+async def admit_draft(
+    s: AsyncSession,
+    keys: KeySource,
+    ctx: TenantContext,
+    *,
+    workflow_id: uuid.UUID,
+    idempotency_key: str,
+    input: dict[str, Any],
+    simulation: Simulation,
+    settings: Settings,
+) -> Admitted:
+    """A draft simulation's request under `idempotency_key` (B8; the simulation design §6.3): an exact retry's, as it
+    is now, whatever the draft became; or a new one, `simulate` and `manual`, frozen on a snapshot of the revision it
+    names. Raises IdempotencyConflictError, WorkflowNotFoundError, DraftConflictError (another revision),
+    DraftInvalidError (what can't run), SeedsRefusedError, AdmissionRefusedError."""
+    if nests_too_deep(input) or nests_too_deep(simulation.values):  # before its key's digest reads them
+        raise AdmissionRefusedError(INPUT_INVALID, [TOO_DEEP])
+    await lifecycle.assert_read_committed(s)
+    await tenant_scope(s, ctx.tenant_id)
+    fields: dict[str, Any] = {"source": "manual", "workflow_id": workflow_id, "mode": SIMULATE, "input": input}
+    digested = {**fields, "draft": simulation.digested()}
+    existing = await _by_key(s, idempotency_key)
+    if existing is not None:
+        return await _retry(keys, ctx.tenant_id, existing, digested)
+    request_id = uuid.uuid4()
+    savepoint = await s.begin_nested()
+    try:
+        frozen = await _draft_frozen(s, keys, ctx, request_id, fields, simulation, settings)
+    except _Refused as refused:
+        await savepoint.rollback()
+        raise AdmissionRefusedError(refused.reason, refused.messages) from None
+    await _before_insert()
+    admitted = await _insert(s, keys, ctx.tenant_id, request_id, ctx.user.id, idempotency_key, digested, None,
+                             frozen.envelope_id, extra=frozen.details, draft=frozen)  # fmt: skip
+    if admitted.new:
+        await savepoint.commit()
+    else:
+        await savepoint.rollback()  # another transaction won the key: this call's claims, envelope and snapshot go
+        return await _retry(keys, ctx.tenant_id, await _winner(s, idempotency_key), digested)
+    return admitted
+
+
 async def record_refused(
     s: AsyncSession, keys: KeySource, *, tenant_id: uuid.UUID, workflow_id: uuid.UUID, source: str, mode: str,
     idempotency_key: str, reason: str, messages: list[str], details: dict[str, object] | None = None,
@@ -303,18 +400,7 @@ async def _frozen(
 ) -> _Frozen:  # fmt: skip
     """The mutable checks, then the trigger claimed and its envelope stored (a CSV start's rows built and its upload
     consumed first): the frozen version, the envelope and what the audit entry adds."""
-    await tenant_lifecycle.hold_shared(s, tenant_id)  # an erasure's step 1 waits for this request, or it sees `erasing`
-    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
-    if tenant is None:
-        raise WorkflowNotFoundError(str(fields["workflow_id"]))
-    if tenant.status != "active":  # erasing, or erased: a retained tombstone is never eligible again
-        raise _Refused(TENANT_ERASING, ["This tenant is being erased: it starts no run."])
-    if fields["source"] in INTERACTIVE:
-        platform = await recorded(s)
-        if platform is None:
-            raise _Refused(ENVIRONMENT_NOT_RECORDED, [NOT_RECORDED])
-        if platform.environment == PRODUCTION and not platform.production_runs:
-            raise _Refused(PRODUCTION_RUNS_DISABLED, [GATE_OFF])
+    await _open(s, tenant_id, fields)
     workflow = await lock_for_admission(s, tenant_id, fields["workflow_id"])  # stands until the request is frozen
     if workflow is None:
         raise WorkflowNotFoundError(str(fields["workflow_id"]))
@@ -325,11 +411,7 @@ async def _frozen(
     version = await s.get(WorkflowVersion, workflow.active_version_id)
     if version is None:
         raise RuntimeError("A workflow's active version that isn't there.")
-    build = (
-        await s.execute(
-            select(CurrentBuild.engine_abi).where(CurrentBuild.observed_at >= func.statement_timestamp() - BUILD_STALE)
-        )
-    ).scalar_one_or_none()
+    build = await _current_build(s)
     if build is None:
         raise _Refused(NO_CURRENT_BUILD, [NO_BUILD], version.id)
     stale = await other_abi(s, version.closure_version_ids, build)  # versions never change: no lock needed
@@ -380,6 +462,108 @@ async def _frozen(
                                              "csv_skipped": len(built.skipped)})  # fmt: skip
 
 
+async def _draft_frozen(
+    s: AsyncSession, keys: KeySource, ctx: TenantContext, request_id: uuid.UUID, fields: dict[str, Any],
+    simulation: Simulation, settings: Settings,
+) -> _DraftFrozen:  # fmt: skip
+    """§6.3's steps 2 to 7: the tenant and the gate; the workflow's admission lock (enabled or not, published or not:
+    D-b1); the revision; the draft checked, blocking and reported; the current build of its ABI and its pins'; the
+    input against the draft's trigger schema, or the step's seeds against its contract, claimed into the envelope; and
+    the snapshot found or made, held against the sweep until the request is committed."""
+    tenant_id = ctx.tenant_id
+    await _open(s, tenant_id, fields)
+    if await lock_for_admission(s, tenant_id, fields["workflow_id"]) is None:
+        raise WorkflowNotFoundError(str(fields["workflow_id"]))
+    found = select(Workflow).where(Workflow.id == fields["workflow_id"]).execution_options(populate_existing=True)
+    wf = (await s.execute(found)).scalar_one()
+    if wf.draft_revision != simulation.revision:
+        raise DraftConflictError(wf.draft_revision)
+    checked = await workflow_ops.check_draft(s, tenant_id, wf.draft, settings)
+    sim = await workflow_ops.simulatable(s, ctx, wf, checked)
+    if sim.new is None or checked.graph is None or checked.context is None:
+        raise DraftInvalidError(sim.blocking, sim.reported, sim.warnings)
+    build = await _current_build(s)
+    if build is None:
+        raise _Refused(NO_CURRENT_BUILD, [NO_BUILD])
+    if sim.new.engine_abi != build:
+        raise _Refused(VERSION_UNUSABLE, [
+            f"This draft is simulated for engine ABI {sim.new.engine_abi}, this server's, and the current build runs "
+            f"ABI {build}: simulate it again once they're the same build."
+        ])  # fmt: skip
+    stale = await other_abi(s, sim.new.closure_version_ids, build)  # its pins'
+    if stale:
+        raise _Refused(VERSION_UNUSABLE, abi_reasons(wf.id, stale, build))
+    schema: dict[str, Any]
+    value: dict[str, Any]
+    if simulation.target is None:
+        if any(name in fields["input"] for name in RESERVED):  # only a CSV upload supplies them: none here (D-b8)
+            raise _Refused(INPUT_INVALID, [RESERVED_INPUT])
+        schema, value = trigger_schema(sim.new.graph.get("settings") or {}), fields["input"]
+    else:
+        contract = await asyncio.to_thread(seeds.contract, checked.graph, checked.context, simulation.target)
+        if contract.refused is not None:
+            raise _Refused(TARGET_INVALID, [contract.refused])
+        problems = seeds.check(contract, simulation.values, simulation.absent)
+        if problems:
+            raise SeedsRefusedError(problems)
+        schema, value = _seeded(contract), {"values": dict(simulation.values), "absent": sorted(simulation.absent)}
+    try:
+        envelope = await claim_input(s, keys, tenant_id=tenant_id, run_id=request_id, root_run_id=request_id,
+                                     schema=schema, value=value, against_schema=simulation.target is None)  # fmt: skip
+    except InputRefusedError as e:
+        raise _Refused(e.reason, e.reasons) from None
+    envelope_id = await claims.write_envelope(s, ClaimCipher(keys), tenant_id, request_id=request_id, envelope=envelope)
+    snapshot = await drafts.snapshot_for(s, wf, sim.new, revision=wf.draft_revision, created_by=ctx.user.id)
+    details: dict[str, object] = {"draft_snapshot_id": str(snapshot.id), "draft_revision": wf.draft_revision,
+                                  "graph_hash": snapshot.graph_hash}  # fmt: skip
+    if simulation.target is not None:
+        details["target_step_id"] = str(simulation.target)
+    if snapshot.declassified:
+        details["declassify"] = snapshot.declassified
+    checks = [d.to_json() for d in sim.reported]
+    return _DraftFrozen(snapshot.id, envelope_id, wf.draft_revision, simulation.target, checks, details)
+
+
+def _seeded(contract: seeds.SeedContract) -> dict[str, Any]:
+    """The seeds' envelope schema, each entry's own: a value is split as the run's input would be (§5.3), a sensitive
+    one, or a sensitive part of one, claimed, a handle. Never checked against it: `seeds.check` has."""
+    values = {e.pointer: {**(e.schema or {}), **({"x-sensitive": True} if e.sensitive else {})}
+              for e in contract.entries}  # fmt: skip
+    return {
+        "type": "object",
+        "additionalProperties": False,
+        "properties": {
+            "values": {"type": "object", "additionalProperties": False, "properties": values},
+            "absent": {"type": "array", "items": {"type": "string"}},
+        },
+    }
+
+
+async def _open(s: AsyncSession, tenant_id: uuid.UUID, fields: dict[str, Any]) -> None:
+    """The tenant starts runs: it's active (an erasure's step 1 waits for this request, or this one sees `erasing`),
+    and, for an interactive source, the gate is open."""
+    await tenant_lifecycle.hold_shared(s, tenant_id)
+    tenant = await s.get(Tenant, tenant_id, populate_existing=True)
+    if tenant is None:
+        raise WorkflowNotFoundError(str(fields["workflow_id"]))
+    if tenant.status != "active":  # erasing, or erased: a retained tombstone is never eligible again
+        raise _Refused(TENANT_ERASING, ["This tenant is being erased: it starts no run."])
+    if fields["source"] in INTERACTIVE:
+        platform = await recorded(s)
+        if platform is None:
+            raise _Refused(ENVIRONMENT_NOT_RECORDED, [NOT_RECORDED])
+        if platform.environment == PRODUCTION and not platform.production_runs:
+            raise _Refused(PRODUCTION_RUNS_DISABLED, [GATE_OFF])
+
+
+async def _current_build(s: AsyncSession) -> int | None:
+    """The current build's engine ABI, as the dispatcher recorded it lately; None: no record, or a stale one."""
+    found = await s.execute(
+        select(CurrentBuild.engine_abi).where(CurrentBuild.observed_at >= func.statement_timestamp() - BUILD_STALE)
+    )
+    return found.scalar_one_or_none()
+
+
 @dataclass(frozen=True)
 class _Built:
     headers: list[str]
@@ -450,8 +634,10 @@ async def _insert(
     refused: _Refused | None = None,
     rerun: Rerun | None = None,
     extra: dict[str, object] | None = None,
+    draft: _DraftFrozen | None = None,
 ) -> Admitted:
-    """The request row, queued or refused, and its audit entry; `new` False when another transaction won the key."""
+    """The request row, queued or refused, and its audit entry; `new` False when another transaction won the key. A
+    draft simulation's (`draft`) is frozen on its snapshot."""
     key_version, digest = await digests.digest(keys, str(tenant_id), **fields)  # the tenant's active key (§7.2)
     status = "refused" if refused else "queued"
     row = {
@@ -470,6 +656,9 @@ async def _insert(
         "ended_at": func.now() if refused else None,
         "envelope_id": envelope_id,
     }
+    if draft is not None:
+        row |= {"draft_snapshot_id": draft.snapshot_id, "target_step_id": draft.target,
+                "draft_revision": draft.revision, "admission_checks": draft.checks}  # fmt: skip
     written = await s.execute(
         insert(RunRequest)
         .values(row)
diff --git a/backend/src/dewpoint/apps/inputs.py b/backend/src/dewpoint/apps/inputs.py
index 81b4e019..20ab6f1f 100644
--- a/backend/src/dewpoint/apps/inputs.py
+++ b/backend/src/dewpoint/apps/inputs.py
@@ -88,12 +88,13 @@ def reasons(schema: Mapping[str, Any], value: Any) -> list[str]:
     ]
 
 
-def checked(schema: Mapping[str, Any], value: dict[str, Any]) -> Split:
+def checked(schema: Mapping[str, Any], value: dict[str, Any], *, against_schema: bool = True) -> Split:
     """`value` checked against `schema`, then split: CPU only. Raises InputRefusedError. Its depth first: nothing
-    recursive reads an input deeper than the limit (issue #88)."""
+    recursive reads an input deeper than the limit (issue #88). `against_schema` False: the caller checked it by rules
+    of its own (a step's seeds, S2), and the schema only says what's sensitive."""
     if nests_too_deep(value):
         raise InputRefusedError([TOO_DEEP])
-    refused = reasons(schema, value)
+    refused = reasons(schema, value) if against_schema else []
     if refused:
         raise InputRefusedError(refused)
     if contains_marker(value):
@@ -111,12 +112,16 @@ async def claim_input(
     schema: Mapping[str, Any],
     value: dict[str, Any],
     off_loop: bool = False,
+    against_schema: bool = True,
 ) -> Any:
     """The envelope of `value`, its claims written (`run_inputs`) and its secrets indexed, inside the caller's
     transaction. Raises InputRefusedError, having written nothing that commits. `off_loop`: the check and the split in a
     thread, for the work a CSV slot bounds (seconds of CPU for a CSV's rows at the caps; the owner's ruling 2 on 2b-4b's
     M3 checkpoint); the session stays on the event loop."""
-    done = await asyncio.to_thread(checked, schema, value) if off_loop else checked(schema, value)
+    if off_loop:
+        done = await asyncio.to_thread(checked, schema, value, against_schema=against_schema)
+    else:
+        done = checked(schema, value, against_schema=against_schema)
     if done.claims:
         cipher = ClaimCipher(keys)
         for c in done.claims:
diff --git a/backend/src/dewpoint/apps/workflow_ops.py b/backend/src/dewpoint/apps/workflow_ops.py
index cf3ce423..4d5abbb9 100644
--- a/backend/src/dewpoint/apps/workflow_ops.py
+++ b/backend/src/dewpoint/apps/workflow_ops.py
@@ -57,6 +57,7 @@ class Checked:
     diagnostics: list[Diagnostic]
     pins: dict[uuid.UUID, WorkflowVersion]  # pinned workflow id -> its active version
     result: ValidationResult | None
+    context: ValidationContext | None = None  # what it was validated in: a step's seed contract reads it again
 
 
 async def validation_context(
@@ -86,7 +87,7 @@ async def check_draft(s: AsyncSession, tenant_id: uuid.UUID, draft: Any, setting
         return Checked(None, list(e.diagnostics), {}, None)
     ctx, pins = await validation_context(s, tenant_id, graph, settings)
     result = await asyncio.to_thread(validate, graph, ctx)  # CPU-bound: keep the event loop serving others
-    return Checked(graph, list(result.diagnostics), pins, result)
+    return Checked(graph, list(result.diagnostics), pins, result, ctx)
 
 
 async def draft_scope(
diff --git a/backend/src/dewpoint/core/requests/digest.py b/backend/src/dewpoint/core/requests/digest.py
index 1935e0cb..7e9a7be9 100644
--- a/backend/src/dewpoint/core/requests/digest.py
+++ b/backend/src/dewpoint/core/requests/digest.py
@@ -13,9 +13,12 @@ from typing import Any
 from dewpoint.core.crypto.keys import KeySource
 
 
-def canonical(*, source: str, workflow_id: uuid.UUID, mode: str, input: Any) -> bytes:
-    """Sorted keys, no whitespace, UTF-8, no NaN: equal requests always give equal bytes."""
+def canonical(*, source: str, workflow_id: uuid.UUID, mode: str, input: Any, draft: Any = None) -> bytes:
+    """Sorted keys, no whitespace, UTF-8, no NaN: equal requests always give equal bytes. A draft simulation's `draft`
+    (B8) is there only when given, so every other request's bytes stay what they were."""
     value = {"source": source, "workflow_id": str(workflow_id), "mode": mode, "input": input}
+    if draft is not None:
+        value["draft"] = draft
     return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
 
 
@@ -27,21 +30,22 @@ async def digest(
     workflow_id: uuid.UUID,
     mode: str,
     input: Any,
+    draft: Any = None,
     version: int | None = None,
 ) -> tuple[int, bytes]:
     """The request's digest with the tenant's key of `version` (its active one when None), and that version."""
     found, key = await keys.digest_key(tenant_id, version)
-    message = canonical(source=source, workflow_id=workflow_id, mode=mode, input=input)
+    message = canonical(source=source, workflow_id=workflow_id, mode=mode, input=input, draft=draft)
     return found, hmac.new(key, message, hashlib.sha256).digest()
 
 
 async def matches(
     keys: KeySource, tenant_id: str, stored: bytes, version: int, *, source: str, workflow_id: uuid.UUID, mode: str,
-    input: Any,
+    input: Any, draft: Any = None,
 ) -> bool:  # fmt: skip
     """Whether a request is the one `stored` was computed for, with the key version it was computed with."""
     _, fresh = await digest(keys, tenant_id, source=source, workflow_id=workflow_id, mode=mode, input=input,
-                            version=version)  # fmt: skip
+                            draft=draft, version=version)  # fmt: skip
     return hmac.compare_digest(fresh, stored)
 
 
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 101 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/admission.py backend/src/dewpoint/apps/inputs.py \
  backend/src/dewpoint/apps/workflow_ops.py backend/src/dewpoint/core/requests/digest.py \
  backend/tests/apps/test_admission_drafts.py backend/tests/core/requests/test_digest.py
git commit -m "feat(admission): a draft simulated whole or one step alone, frozen on its snapshot (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The route: `POST …/draft/simulations`

**Spec:** §6.3, §7.7 (refusals in the server's words).

**Files:**
- Modify: `backend/src/dewpoint/core/http.py` (`require(*permissions)`)
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`SimulationOut`)
- Create: `backend/src/dewpoint/apps/api/routes/simulations.py`
- Modify: `backend/src/dewpoint/apps/api/openapi.py` (its routers)
- Create: `backend/tests/apps/api/test_simulations_api.py`
- Modify: `backend/tests/apps/api/test_openapi.py` (`SLICE_4D1`)

**Interfaces:**
- Consumes: Task 5's `admit_draft`, `Simulation` and its errors; `routes.workflows._revision` (If-Match);
  `routes.run_requests` (`idempotency_key`, `request_body`, `get_keys`, `key_unusable`, `not_past_cutoff`, `INVALID`,
  `UNAVAILABLE`).
- Produces: `require(*permissions: P)` (every permission named); `SimulationOut`; `simulations.router`;
  `simulations.simulation_body(r: RunRequest) -> dict[str, object]`.

The body is `{input}` or `{target: {step_id, values, absent}}`, never both. `workflow.edit` and `run.start` are
required. The answers: 202 with the request; 409 `draft_conflict` with the draft's revision, `idempotency_conflict`;
422 `invalid` with the diagnostics, `seed_*` with each problem's pointer, `target_invalid`, the start's `input_invalid`;
503 and 409 for the start's other codes; 428 `revision_required` and `idempotency_key_required`; 400 `bad_revision`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_openapi.py b/backend/tests/apps/api/test_openapi.py
index 94f233c1..fb281605 100644
--- a/backend/tests/apps/api/test_openapi.py
+++ b/backend/tests/apps/api/test_openapi.py
@@ -191,6 +191,19 @@ def test_slice_4c3_routes_name_their_answer(method: str, path: str) -> None:
     assert "$ref" in body or "$ref" in body.get("items", {}), body
 
 
+SLICE_4D1 = [  # B8 (the simulation design §6.3, §6.6)
+    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations"),
+]
+
+
+@pytest.mark.parametrize("method,path", SLICE_4D1)
+def test_slice_4d1_routes_name_their_answer(method: str, path: str) -> None:
+    responses = schema()["paths"][path][method]["responses"]
+    ok = next(code for code in responses if code.startswith("2"))
+    body = responses[ok]["content"]["application/json"]["schema"]
+    assert "$ref" in body or "$ref" in body.get("items", {}), body
+
+
 def test_a_schedules_uncounted_span_keeps_its_wire_names() -> None:
     """`from` and `class` are Python keywords: the model aliases them, and the schema says the names on the wire."""
     span = schema()["components"]["schemas"]["UncountedOut"]
diff --git a/backend/tests/apps/api/test_simulations_api.py b/backend/tests/apps/api/test_simulations_api.py
new file mode 100644
index 00000000..f4031447
--- /dev/null
+++ b/backend/tests/apps/api/test_simulations_api.py
@@ -0,0 +1,108 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Simulating a draft through the API (B8; the simulation design §6.3): `POST …/draft/simulations` with `If-Match` (the
+draft revision) and an `Idempotency-Key`, `{input}` for the workflow or `{target}` for a step alone (S2). It needs
+`workflow.edit` and `run.start`, answers 202 with the request, and refuses in the server's words: 409 for another
+revision, 422 for a draft that can't run, for seeds, and for a step that can't run alone."""
+
+import uuid
+from typing import Any
+
+import pytest
+
+from tests.apps.api.test_run_requests_api import as_role, keyed_app
+from tests.apps.test_admission import current
+from tests.apps.test_admission_drafts import LOOP_GRAPH, STEPS_GRAPH, drafted
+from tests.apps.test_workflow_ops import create, save
+from tests.support.graphs import G, nid
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
+
+
+def url(ctx: Any, wf: uuid.UUID) -> str:
+    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/simulations"
+
+
+def headers(key: str = "k1", revision: int | str | None = 1) -> dict[str, str]:
+    return {"Idempotency-Key": key} | ({} if revision is None else {"If-Match": f'"{revision}"'})
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker) -> Any:
+    await current(dispatch_sessionmaker)
+    return await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
+
+
+async def test_an_editor_simulates_the_draft_and_gets_its_queued_request(
+    keyed_app, ready, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await client.post(url(ctx, wf), json={"input": {}}, headers=headers())
+    assert answer.status_code == 202, answer.text
+    body = answer.json()
+    assert {k: body[k] for k in ("status", "mode", "source", "version_id", "draft_revision", "target_step_id",
+                                 "admission_checks")} == {
+        "status": "queued", "mode": "simulate", "source": "manual", "version_id": None, "draft_revision": 1,
+        "target_step_id": None, "admission_checks": [],
+    }  # fmt: skip
+    assert body["draft_snapshot_id"] and body["workflow_id"] == str(wf)
+    again = await client.post(url(ctx, wf), json={"input": {}}, headers=headers())
+    assert (again.status_code, again.json()["id"]) == (202, body["id"])  # an exact retry
+
+
+@pytest.mark.parametrize(("role", "status"), [("viewer", 403), ("operator", 403), ("editor", 202), ("admin", 202)])
+async def test_simulating_needs_workflow_edit_and_run_start(
+    keyed_app, ready, owner_sessionmaker, api_settings, role, status
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
+    answer = await client.post(url(ctx, wf), json={"input": {}}, headers=headers())
+    assert answer.status_code == status, answer.text
+
+
+async def test_the_revision_and_the_key_are_required(keyed_app, ready, owner_sessionmaker, api_settings) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    for sent, status, code in (
+        ({"Idempotency-Key": "k1"}, 428, "revision_required"),
+        (headers(revision="x"), 400, "bad_revision"),
+        ({"If-Match": "1"}, 428, "idempotency_key_required"),
+    ):
+        answer = await client.post(url(ctx, wf), json={"input": {}}, headers=sent)
+        assert (answer.status_code, answer.json()["error"]) == (status, code)
+
+
+async def test_another_revision_is_a_conflict_naming_the_drafts(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    await save(api_sessionmaker, ctx, wf, STEPS_GRAPH)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await client.post(url(ctx, wf), json={"input": {}}, headers=headers(revision=1))
+    assert (answer.status_code, answer.json()) == (409, {"error": "draft_conflict", "draft_revision": 2})
+
+
+async def test_a_draft_that_cant_run_seeds_and_targets_are_refused_in_the_servers_words(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    missing = await client.post(url(ctx, wf), json={"target": {"step_id": str(nid("b"))}}, headers=headers("k1"))
+    assert missing.status_code == 422
+    assert missing.json() == {"error": "seed_missing", "problems": [{
+        "code": "seed_missing", "pointer": "/steps/a/output/value",
+        "message": "Give this value, or leave it absent if it may be.",
+    }]}  # fmt: skip
+    alone = await client.post(url(ctx, wf), json={"target": {"step_id": str(uuid.uuid4())}}, headers=headers("k2"))
+    assert (alone.status_code, alone.json()["error"]) == (422, "target_invalid")
+    both = await client.post(url(ctx, wf), json={"input": {"x": 1}, "target": {"step_id": str(nid("b"))}},
+                             headers=headers("k3"))  # fmt: skip
+    assert both.status_code == 422
+    broken = await create(api_sessionmaker, ctx, G().node("z", "no.such@1").data(), name="broken")
+    invalid = await client.post(url(ctx, broken), json={"input": {}}, headers=headers("k4"))
+    assert (invalid.status_code, invalid.json()["error"]) == (422, "invalid")
+    assert [d["code"] for d in invalid.json()["diagnostics"]] == ["node.unknown_type"]
+    looped = await create(api_sessionmaker, ctx, LOOP_GRAPH, name="looped")
+    loop = await client.post(url(ctx, looped), json={"target": {"step_id": str(nid("l"))}}, headers=headers("k5"))
+    assert (loop.status_code, loop.json()["error"]) == (422, "target_invalid")
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/api/test_simulations_api.py
tests/apps/api/test_openapi.py tests/apps/api/test_run_requests_api.py`

Expected: FAIL, 9 failed and 103 passed: the route doesn't exist yet, so each call answers 404
(`{"error":"not_found"}`), and the schema has no `…/draft/simulations` path (KeyError). The run start tests pass.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/openapi.py b/backend/src/dewpoint/apps/api/openapi.py
index 34d9077c..2c43bcd8 100644
--- a/backend/src/dewpoint/apps/api/openapi.py
+++ b/backend/src/dewpoint/apps/api/openapi.py
@@ -26,6 +26,7 @@ from dewpoint.apps.api.routes import (
     run_requests,
     runs,
     schedules,
+    simulations,
     tenants,
     webhooks,
     workflows,
@@ -58,6 +59,7 @@ ROUTERS: tuple[APIRouter, ...] = (
     retention.router,
     schedules.router,
     webhooks.router,
+    simulations.router,
 )
 
 
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 1cc4e126..7f412755 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -607,3 +607,22 @@ class StartFormOut(_Answer):
     version_id: str
     fields: list[StartFieldOut]
     csv: CsvFormOut | None
+
+
+class SimulationOut(_Answer):
+    """A draft simulation's request (B8; the simulation design §6.3): frozen on its draft snapshot, at the revision it
+    was admitted at, with the step it runs alone (S2) and what admission reported without refusing. Never its input."""
+
+    id: str
+    workflow_id: str
+    version_id: None
+    draft_snapshot_id: str
+    draft_revision: int
+    target_step_id: str | None
+    mode: Literal["simulate"]
+    source: str
+    status: Literal["queued", "starting", "started", "cancelled", "refused", "dead"]
+    reason: str | None
+    queued_at: str | None
+    ended_at: str | None
+    admission_checks: list[DiagnosticOut]
diff --git a/backend/src/dewpoint/apps/api/routes/simulations.py b/backend/src/dewpoint/apps/api/routes/simulations.py
new file mode 100644
index 00000000..9e910d70
--- /dev/null
+++ b/backend/src/dewpoint/apps/api/routes/simulations.py
@@ -0,0 +1,109 @@
+# SPDX-License-Identifier: Apache-2.0
+"""Simulating a workflow's draft (B8; the simulation design §6.3): `POST …/draft/simulations` admits a request frozen
+on a snapshot of the draft at the revision `If-Match` names, under an `Idempotency-Key`, always `simulate` and
+`manual`, and the dispatcher starts it as any run. `{input}` simulates the workflow; `{target}` a step alone with the
+values it reads (S2). It needs `workflow.edit` and `run.start`; cancelling is the run's own route (`run.cancel`)."""
+
+import uuid
+from typing import Any
+
+from fastapi import APIRouter, Depends, Header, HTTPException
+from pydantic import BaseModel, ConfigDict, Field, model_validator
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.apps import admission
+from dewpoint.apps.api.responses import SimulationOut
+from dewpoint.apps.api.routes.run_requests import (
+    INVALID,
+    UNAVAILABLE,
+    get_keys,
+    idempotency_key,
+    key_unusable,
+    not_past_cutoff,
+    request_body,
+)
+from dewpoint.apps.api.routes.workflows import _revision
+from dewpoint.core.authz.permissions import P
+from dewpoint.core.config import Settings
+from dewpoint.core.crypto.keys import KeySource
+from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
+from dewpoint.core.models.requests import RunRequest
+from dewpoint.core.workflows.service import DraftConflictError
+
+router = APIRouter(prefix="/api/v1", tags=["simulations"])
+
+
+class TargetIn(BaseModel):
+    """A step to run alone (S2) and the values it reads, given or absent by pointer (the simulation design §5.2)."""
+
+    model_config = ConfigDict(extra="forbid")
+    step_id: uuid.UUID
+    values: dict[str, Any] = Field(default_factory=dict)
+    absent: list[str] = Field(default_factory=list)
+
+
+class SimulateIn(BaseModel):
+    model_config = ConfigDict(extra="forbid")
+    input: dict[str, Any] = Field(default_factory=dict)  # the workflow's, as its draft's trigger schema takes it
+    target: TargetIn | None = None
+
+    @model_validator(mode="after")
+    def _one(self) -> "SimulateIn":
+        if self.target is not None and self.input:
+            raise ValueError("A step simulated alone takes its values, not the workflow's input.")
+        return self
+
+
+def simulation_body(r: RunRequest) -> dict[str, object]:
+    """A draft simulation's request as the API shows it, never its input or seeds."""
+    return {
+        **request_body(r),
+        "draft_snapshot_id": str(r.draft_snapshot_id),
+        "draft_revision": r.draft_revision,
+        "target_step_id": str(r.target_step_id) if r.target_step_id else None,
+        "admission_checks": r.admission_checks or [],
+    }
+
+
+@router.post("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations", status_code=202, response_model=SimulationOut)
+async def simulate(
+    workflow_id: uuid.UUID,
+    body: SimulateIn,
+    if_match: str | None = Header(default=None, alias="If-Match"),
+    key: str = Depends(idempotency_key),
+    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT, P.RUN_START)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+    settings: Settings = Depends(get_settings_dep),
+) -> dict[str, object]:
+    revision = _revision(if_match)
+    target = body.target
+    simulation = admission.Simulation(
+        revision,
+        target.step_id if target else None,
+        dict(target.values) if target else {},
+        tuple(target.absent) if target else (),
+    )
+    try:
+        admitted = await admission.admit_draft(db, keys, ctx, workflow_id=workflow_id, idempotency_key=key,
+                                               input=body.input, simulation=simulation, settings=settings)  # fmt: skip
+    except admission.WorkflowNotFoundError:
+        raise HTTPException(404, detail={"error": "not_found"}) from None
+    except admission.IdempotencyConflictError:
+        raise HTTPException(409, detail={"error": "idempotency_conflict"}) from None
+    except DraftConflictError as e:
+        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
+    except admission.DraftInvalidError as e:
+        diagnostics = [d.to_json() for d in [*e.blocking, *e.warnings]]
+        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics}) from None
+    except admission.SeedsRefusedError as e:
+        problems = [{"code": p.code, "pointer": p.pointer, "message": p.message} for p in e.problems]
+        raise HTTPException(422, detail={"error": e.reason, "problems": problems}) from None
+    except admission.AdmissionRefusedError as e:
+        status = 503 if e.reason in UNAVAILABLE else 422 if e.reason in INVALID | {admission.TARGET_INVALID} else 409
+        raise HTTPException(status, detail={"error": e.reason, "messages": e.messages}) from None
+    except Exception as e:
+        raise key_unusable(e) from None
+    if not admitted.new:
+        await not_past_cutoff(db, ctx, admitted.request)
+    return simulation_body(admitted.request)
diff --git a/backend/src/dewpoint/core/http.py b/backend/src/dewpoint/core/http.py
index efa38aca..b473413a 100644
--- a/backend/src/dewpoint/core/http.py
+++ b/backend/src/dewpoint/core/http.py
@@ -72,11 +72,12 @@ async def _after_require() -> None:
     here."""
 
 
-def require(permission: P) -> Callable[..., Awaitable[TenantContext]]:
-    """The caller's role in the tenant, checked for `permission`. A write (any non-safe method) takes the tenant's
-    lifecycle lock, shared, in the request's transaction (`get_db`'s, which commits before the response) before it
-    reads the tenant, and is refused unless the tenant is active (409 `tenant_erasing`): an erasure's step 1, which
-    takes it exclusively, waits for the write to commit, or the write sees `erasing` (the 2b-4 outline's fencing)."""
+def require(*permissions: P) -> Callable[..., Awaitable[TenantContext]]:
+    """The caller's role in the tenant, checked for every one of `permissions`. A write (any non-safe method) takes the
+    tenant's lifecycle lock, shared, in the request's transaction (`get_db`'s, which commits before the response)
+    before it reads the tenant, and is refused unless the tenant is active (409 `tenant_erasing`): an erasure's step 1,
+    which takes it exclusively, waits for the write to commit, or the write sees `erasing` (the 2b-4 outline's
+    fencing)."""
 
     async def _dep(
         tenant_id: uuid.UUID,
@@ -101,7 +102,7 @@ def require(permission: P) -> Callable[..., Awaitable[TenantContext]]:
         role, require_passkey, status = row
         if require_passkey and "passkey" not in sess.auth_methods:
             raise HTTPException(403, detail={"error": "step_up_required"})
-        if permission not in ROLE_PERMISSIONS[role]:
+        if any(p not in ROLE_PERMISSIONS[role] for p in permissions):
             raise HTTPException(403, detail={"error": "forbidden"})
         if writes and status != "active":
             raise HTTPException(409, detail={"error": "tenant_erasing"})
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 112 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/core/http.py backend/src/dewpoint/apps/api/responses.py \
  backend/src/dewpoint/apps/api/routes/simulations.py backend/src/dewpoint/apps/api/openapi.py \
  backend/tests/apps/api/test_simulations_api.py backend/tests/apps/api/test_openapi.py
git commit -m "feat(api): simulate a draft, whole or one step, with its revision and a key (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: A draft simulation runs, whole or one step alone

**Spec:** §6.4, §5.3; 4d-1a's ruling 164.

**Files:**
- Modify: `backend/src/dewpoint/apps/dispatcher/dispatch.py` (`frozen`, `_begin`, `run_input`)
- Modify: `backend/src/dewpoint/apps/dispatcher/reconcile.py` (`_expected`)
- Modify: `backend/src/dewpoint/core/runs/service.py` (`precreate_run`)
- Modify: `backend/src/dewpoint/apps/worker/store.py` (`DbRunStore.version`)
- Modify: `backend/src/dewpoint/engine/runtime/execution.py` (the guard)
- Create: `backend/tests/apps/dispatcher/test_draft_simulations.py`
- Modify: `backend/tests/apps/worker/test_run_graph_seeded.py`

**Interfaces:**
- Consumes: Task 5's draft requests.
- Produces: `async dispatch.frozen(s, request) -> WorkflowVersion | DraftSnapshot`; `service.precreate_run(...,
  draft_snapshot_id=None, target_step_id=None)`; `RunInput.target_step_id` set from the request.

Dispatch and the reconciler read "a version or a snapshot" for the closure, the engine ABI and the start: a snapshot's
own ABI is checked against the build beside its pins' (ruling 3). The run row names the snapshot and no version. The
worker loads a version, else a snapshot, by the start's `version_id` (ruling 2). A step alone never continues as new
(ruling 15).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/dispatcher/test_draft_simulations.py b/backend/tests/apps/dispatcher/test_draft_simulations.py
new file mode 100644
index 00000000..c9086250
--- /dev/null
+++ b/backend/tests/apps/dispatcher/test_draft_simulations.py
@@ -0,0 +1,94 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A draft simulation's run (B8; the simulation design §6.4) on the time-skipping server: dispatch starts it from its
+snapshot and the worker loads that snapshot, its run row naming it and no version; a step alone runs from its seeds,
+the one step instantiated (S2); the reconciler expects the start dispatch sent."""
+
+import asyncio
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from dewpoint.apps.dispatcher import dispatch, reconcile
+from dewpoint.apps.worker.store import DbRunStore
+from dewpoint.engine.runtime.ids import run_workflow_id
+from dewpoint.engine.runtime.workflow import RunGraph
+from tests.apps.dispatcher.support import BUILD, begin, workers
+from tests.apps.test_admission import KEYS, current
+from tests.apps.test_admission_drafts import drafted, simulate
+from tests.apps.worker.harness import workers as running
+from tests.support.graphs import G, cel, nid, ref
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+
+TRANSFORMS = (
+    G().node("a", "flow.transform@1", {"fields": {"n": cel("1 + 1")}})
+    .node("b", "flow.transform@1", {"fields": {"m": ref("steps.a.output.n")}}).edge("a", "b").data()
+    | {"settings": {"input_schema": {"type": "object"}}}
+)  # fmt: skip
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker) -> Any:
+    """A tenant with a draft never published, and the current build's workers ready."""
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, TRANSFORMS)
+    await current(dispatch_sessionmaker)
+    await workers(owner_sessionmaker)
+    return ctx, wf
+
+
+async def ran(env: Any, ctx: Any, request: Any, dispatch_sessionmaker: Any, worker_sessionmaker: Any,
+              settings: Any) -> Any:  # fmt: skip
+    async with running(env.client, DbRunStore(worker_sessionmaker, KEYS)):
+        assert await dispatch.dispatch_once(dispatch_sessionmaker, env.client, KEYS, settings, BUILD) == {"started": 1}
+        handle = env.client.get_workflow_handle_for(RunGraph.run, run_workflow_id(str(ctx.tenant_id), str(request.id)))
+        return await asyncio.wait_for(handle.result(), 30)
+
+
+async def rows(owner: Any, request: Any) -> tuple[Any, list[Any]]:
+    async with owner() as s:
+        run = (await s.execute(text("select workflow_version_id, draft_snapshot_id, target_step_id, mode, status "
+                                    "from runs where id = :i"), {"i": request.id})).one()  # fmt: skip
+        steps = (await s.execute(text("select node_key, status, output_preview from run_steps where run_id = :i "
+                                      "order by node_key"), {"i": request.id})).all()  # fmt: skip
+    return tuple(run), [tuple(r) for r in steps]
+
+
+async def test_a_draft_simulation_runs_to_its_end_on_its_snapshot(
+    ready, env, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
+    result = await ran(env, ctx, request, dispatch_sessionmaker, worker_sessionmaker, api_settings)
+    assert result.status == "succeeded", result.error
+    run, steps = await rows(owner_sessionmaker, request)
+    assert run == (None, request.draft_snapshot_id, None, "simulate", "succeeded")
+    assert steps == [("a", "succeeded", {"n": 2}), ("b", "succeeded", {"m": 2})]
+
+
+async def test_a_step_runs_alone_from_its_snapshot_and_its_seeds(
+    ready, env, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, worker_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
+                              values={"/steps/a/output/n": 7})).request  # fmt: skip
+    result = await ran(env, ctx, request, dispatch_sessionmaker, worker_sessionmaker, api_settings)
+    assert result.status == "succeeded", result.error
+    run, steps = await rows(owner_sessionmaker, request)
+    assert run == (None, request.draft_snapshot_id, nid("b"), "simulate", "succeeded")
+    assert steps == [("b", "succeeded", {"m": 7})]  # `a` was never instantiated
+
+
+async def test_the_reconciler_expects_the_start_dispatch_sent(
+    ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
+                              values={"/steps/a/output/n": 7})).request  # fmt: skip
+    started = await begin(dispatch_sessionmaker, request, api_settings)
+    assert isinstance(started, dispatch.Starting)
+    sent = started.start
+    assert (sent.version_id, sent.target_step_id, sent.mode) == (str(request.draft_snapshot_id), str(nid("b")),
+                                                                 "simulate")  # fmt: skip
+    expected = await reconcile._expected(dispatch_sessionmaker, KEYS, api_settings, ctx.tenant_id, request.id)
+    assert expected is not None and expected.start == sent
diff --git a/backend/tests/apps/worker/test_run_graph_seeded.py b/backend/tests/apps/worker/test_run_graph_seeded.py
index 7397ec3e..fb0650b0 100644
--- a/backend/tests/apps/worker/test_run_graph_seeded.py
+++ b/backend/tests/apps/worker/test_run_graph_seeded.py
@@ -250,3 +250,19 @@ async def test_a_failing_step_fails_its_run_whatever_its_error_policy(env: Workf
     assert (result.status, result.error["code"]) == ("failed", "simulation_unavailable")  # it has no simulator
     [row] = store.steps(run_id)
     assert (row.status, row.outcome) == ("failed", "simulated")
+
+
+async def test_a_single_step_never_continues_as_new_however_long_its_history(env: WorkflowEnvironment) -> None:
+    """Ruling 164's guard (4d-1a's deferred minor): a single-step run has no state a continue-as-new could carry, so
+    past its checkpoint it carries on to its end rather than continue."""
+    from temporalio.api.enums.v1 import EventType
+
+    store = MemoryStore()
+    g = graph().node("b", ECHO, {"value": 1})
+    async with workers(env.client, store):
+        handle = await start(env.client, store, g, {"values": {}, "absent": []}, mode="simulate",
+                             target_step_id=str(nid("b")), checkpoint_events=1)  # fmt: skip
+        result = await asyncio.wait_for(handle.result(), RESULT_TIMEOUT_S)
+        kinds = [e.event_type for e in (await handle.fetch_history()).events]
+    assert result.status == "succeeded", result.error
+    assert EventType.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW not in kinds
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/dispatcher
tests/apps/worker/test_run_graph_seeded.py tests/apps/worker/test_store_claims.py
tests/apps/worker/test_store_precedence.py tests/engine/replay`

Expected: FAIL, 4 failed and 774 passed, in about 6 minutes: dispatch starts no draft request (`assert {} == {'started':
1}`, twice) and begins none (`isinstance(None, Starting)` is false); without the guard, the single step past its
checkpoint continues as new and never ends (`TimeoutError` after 60 s). The dispatcher, store and replay tests pass.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/dispatcher/dispatch.py b/backend/src/dewpoint/apps/dispatcher/dispatch.py
index 46900847..74b25b8d 100644
--- a/backend/src/dewpoint/apps/dispatcher/dispatch.py
+++ b/backend/src/dewpoint/apps/dispatcher/dispatch.py
@@ -51,7 +51,7 @@ from dewpoint.core.models.platform import PlatformSettings
 from dewpoint.core.models.requests import RunRequest, RunSlot, TenantRunLimits
 from dewpoint.core.models.runs import ExecutionEvidence
 from dewpoint.core.models.tenancy import Tenant
-from dewpoint.core.models.workflows import WorkflowVersion
+from dewpoint.core.models.workflows import DraftSnapshot, WorkflowVersion
 from dewpoint.core.platform.service import PRODUCTION, workers_ready
 from dewpoint.core.plugins import lifecycle
 from dewpoint.core.retention import slo as retention_slo
@@ -292,7 +292,7 @@ async def _begin(
             .execution_options(populate_existing=True)
         )
     ).scalar_one_or_none()
-    if request is None or request.workflow_version_id is None:
+    if request is None or (request.workflow_version_id is None and request.draft_snapshot_id is None):
         return None
     ran = (await s.execute(text("select status from runs where id = :i for update"), {"i": request.id})).scalar()
     if ran is not None and ran != "running":  # an earlier attempt's execution ran to its end: never a second start
@@ -324,9 +324,7 @@ async def _begin(
     if problems:
         log.warning("dispatch_waiting", reason="workers_not_ready", problems=problems)
         return Waiting("workers_not_ready")
-    version = await s.get(WorkflowVersion, request.workflow_version_id)
-    if version is None:
-        raise RuntimeError("A request frozen on a version that isn't there.")
+    version = await frozen(s, request)  # or a draft simulation's snapshot (B8): what a run starts from, alike
     entries = lifecycle.entries_for(version.closure_node_refs, version.closure_cel_profiles)
     # Never waited for: this transaction holds the request's row, which a retirement holding these locks cancels.
     if not await lifecycle.try_lock_shared(s, entries):
@@ -337,8 +335,8 @@ async def _begin(
         reason = "node_type_retired" if any(e.kind == "node" for e in blocked) else "cel_profile_retired"
         log.warning("dispatch_defensive_cancel", request_id=str(request.id), reason=reason)
         return await _cancel(s, request, reason, {"reason": reason})
-    stale = await other_abi(s, version.closure_version_ids, build.engine_abi)
-    if stale:
+    stale = await other_abi(s, version.closure_version_ids, build.engine_abi)  # a snapshot's closure: its pins'
+    if stale or version.engine_abi != build.engine_abi:
         details: dict[str, object] = {"reason": "engine_abi_changed", "version_abi": version.engine_abi,
                                       "build_abi": build.engine_abi}  # fmt: skip
         return await _cancel(s, request, "engine_abi_changed", details)
@@ -368,8 +366,10 @@ async def _begin(
         return Waiting(KEY_UNUSABLE)
     s.add(RunSlot(run_id=request.id, tenant_id=tenant_id))
     await runs.precreate_run(
-        s, run_id=request.id, tenant_id=tenant_id, workflow_id=request.workflow_id, version_id=version.id,
-        mode=request.mode, started_by=request.actor_id, queued_at=request.queued_at,
+        s, run_id=request.id, tenant_id=tenant_id, workflow_id=request.workflow_id,
+        version_id=request.workflow_version_id, draft_snapshot_id=request.draft_snapshot_id,
+        target_step_id=request.target_step_id, mode=request.mode, started_by=request.actor_id,
+        queued_at=request.queued_at,
     )  # fmt: skip
     await runs.record_attempt(s, tenant_id, request.id)  # its execution's evidence, before Temporal is asked
     if request.start_request_id is None:  # recorded once: every start of it carries it (the start-check slice)
@@ -391,7 +391,8 @@ async def _held(s: AsyncSession) -> None:
 
 
 def run_input(request: RunRequest, version_id: uuid.UUID, envelope: Any, settings: Settings) -> RunInput:
-    """A request's start: its frozen version and its envelope, with the deployment's run bounds."""
+    """A request's start: its frozen version (or a draft simulation's snapshot, and the step it runs alone, B8) and its
+    envelope, with the deployment's run bounds."""
     return RunInput(
         tenant_id=str(request.tenant_id),
         run_id=str(request.id),
@@ -400,9 +401,23 @@ def run_input(request: RunRequest, version_id: uuid.UUID, envelope: Any, setting
         mode=request.mode,
         max_run_duration_s=settings.max_run_duration_days * 86_400,
         cel_schedule_to_start_s=settings.cel_schedule_to_start_s,
+        target_step_id=str(request.target_step_id) if request.target_step_id else None,
     )
 
 
+async def frozen(s: AsyncSession, request: RunRequest) -> WorkflowVersion | DraftSnapshot:
+    """What a request was frozen on: its version, or a draft simulation's snapshot (B8; the simulation design §6.4),
+    which carries the same fields under the same names."""
+    found = (
+        await s.get(WorkflowVersion, request.workflow_version_id)
+        if request.workflow_version_id is not None
+        else await s.get(DraftSnapshot, request.draft_snapshot_id)
+    )
+    if found is None:
+        raise RuntimeError("A request frozen on a version or snapshot that isn't there.")
+    return found
+
+
 async def _slot_free(s: AsyncSession, tenant_id: uuid.UUID, platform: PlatformSettings) -> bool:
     """Whether the tenant runs fewer root runs than its limit, under its limits row's lock (§7.5)."""
     await s.execute(insert(TenantRunLimits).values(tenant_id=tenant_id).on_conflict_do_nothing())
diff --git a/backend/src/dewpoint/apps/dispatcher/reconcile.py b/backend/src/dewpoint/apps/dispatcher/reconcile.py
index 360aee36..3f978136 100644
--- a/backend/src/dewpoint/apps/dispatcher/reconcile.py
+++ b/backend/src/dewpoint/apps/dispatcher/reconcile.py
@@ -189,11 +189,12 @@ async def _expected(
         request = (
             await s.execute(select(RunRequest).where(RunRequest.id == request_id, RunRequest.status == "starting"))
         ).scalar_one_or_none()
-        if request is None or request.workflow_version_id is None:
+        frozen_on = request.workflow_version_id or request.draft_snapshot_id if request is not None else None
+        if request is None or frozen_on is None:
             return None
         cipher = ClaimCipher(dispatch.KeyFailures(keys))
         envelope = await claims.read_envelope(s, cipher, tenant_id, request_id=request_id)
-        start = dispatch.run_input(request, request.workflow_version_id, envelope, settings)
+        start = dispatch.run_input(request, frozen_on, envelope, settings)
         recorded = request.start_request_id
     return dispatch.Starting(request_id, tenant_id, start, recorded)
 
diff --git a/backend/src/dewpoint/apps/worker/store.py b/backend/src/dewpoint/apps/worker/store.py
index 9755e4d7..6213aa87 100644
--- a/backend/src/dewpoint/apps/worker/store.py
+++ b/backend/src/dewpoint/apps/worker/store.py
@@ -27,7 +27,7 @@ from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.claims import SecretIndex
 from dewpoint.core.models.requests import RunSlot
-from dewpoint.core.models.workflows import WorkflowVersion
+from dewpoint.core.models.workflows import DraftSnapshot, WorkflowVersion
 from dewpoint.core.plugins.registry import load_node_types
 from dewpoint.core.runs import service as runs
 from dewpoint.engine.handles import StoredClaim, handles_in
@@ -218,7 +218,10 @@ class DbRunStore:
     async def version(self, tenant_id: str, version_id: str) -> VersionData:
         async with self.sessionmaker() as s, s.begin():
             await tenant_scope(s, uuid.UUID(tenant_id))
-            v = await s.get(WorkflowVersion, uuid.UUID(version_id))
+            found = uuid.UUID(version_id)  # or a draft simulation's snapshot (B8): the same fields, the same names
+            v: WorkflowVersion | DraftSnapshot | None = await s.get(WorkflowVersion, found)
+            if v is None:
+                v = await s.get(DraftSnapshot, found)
             if v is None:
                 raise ApplicationError(f"version {version_id} not found", type="version_not_found", non_retryable=True)
             types = await load_node_types(s, v.node_refs)
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
index ac6607d6..21789855 100644
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -132,18 +132,23 @@ async def precreate_run(
     run_id: uuid.UUID,
     tenant_id: uuid.UUID,
     workflow_id: uuid.UUID,
-    version_id: uuid.UUID,
+    version_id: uuid.UUID | None,
     mode: str,
     started_by: uuid.UUID | None,
     queued_at: datetime,
+    draft_snapshot_id: uuid.UUID | None = None,
+    target_step_id: uuid.UUID | None = None,
 ) -> None:
     """A root run's row, written at dispatch before Temporal answers (engine 2b spec §7.3): queued with its request,
-    not yet started. An earlier attempt's row is reused: a retried dispatch changes nothing."""
+    not yet started; a draft simulation's names its snapshot and its target (B8). An earlier attempt's row is reused: a
+    retried dispatch changes nothing."""
     statement = insert(Run).values(
         id=run_id,
         tenant_id=tenant_id,
         workflow_id=workflow_id,
         workflow_version_id=version_id,
+        draft_snapshot_id=draft_snapshot_id,
+        target_step_id=target_step_id,
         mode=mode,
         status="running",
         iterations=0,
diff --git a/backend/src/dewpoint/engine/runtime/execution.py b/backend/src/dewpoint/engine/runtime/execution.py
index 4daad54e..34355249 100644
--- a/backend/src/dewpoint/engine/runtime/execution.py
+++ b/backend/src/dewpoint/engine/runtime/execution.py
@@ -420,7 +420,11 @@ class Execution:
                         "bytes": [workflow.info().get_current_history_size()],
                         "units": self._units(tasks),  # what the drain waits for
                     }
-                if (self._draining or length >= self.checkpoint_events) and self._quiescent(tasks):
+                if (
+                    (self._draining or length >= self.checkpoint_events)
+                    and self._quiescent(tasks)
+                    and self.seeds is None  # a single step carries nothing a continue could (S2; ruling 164)
+                ):
                     if self._draining:  # measured, for the headroom (spec §6): what draining added
                         self._drained["events"].append(length)
                         self._drained["bytes"].append(workflow.info().get_current_history_size())
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 778 passed (about 4.5 minutes).

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/dispatcher/dispatch.py backend/src/dewpoint/apps/dispatcher/reconcile.py \
  backend/src/dewpoint/core/runs/service.py backend/src/dewpoint/apps/worker/store.py \
  backend/src/dewpoint/engine/runtime/execution.py backend/tests/apps/dispatcher/test_draft_simulations.py \
  backend/tests/apps/worker/test_run_graph_seeded.py
git commit -m "feat(runs): a draft simulation dispatched and run from its snapshot, one step alone included (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Re-runs, retirement and connections

**Spec:** §6.5; §9 (the two paths that would fail open).

**Files:**
- Modify: `backend/src/dewpoint/apps/api/routes/run_requests.py` (`DRAFT_RUN`, `_of_a_draft`)
- Modify: `backend/src/dewpoint/core/plugins/lifecycle.py` (`_closure`, `_preview`)
- Modify: `backend/tests/apps/api/test_simulations_api.py`, `backend/tests/apps/test_admission_retirement.py`,
  `backend/tests/apps/test_connection_fields.py`

**Interfaces:**
- Consumes: Task 2's columns, Task 4's test support (`snapshot`, `tree(snapshot=)`).
- Produces: `run_requests.DRAFT_RUN = "draft_run"`; the retirement preview's `QueuedRef.version_id` naming a draft
  request's snapshot.

A re-run of a run whose root is a draft run is refused, 409 `draft_run` ("This run simulated a draft: simulate the
draft again."), its published children included. A forced retirement's preview reads the queued and starting
requests frozen on a version or on a snapshot (a UNION ALL): a queued simulation that names a retiring type blocks a
normal retirement and is cancelled by a forced one. A connection's "in use" leaves draft requests out, as the spec
says (a simulation opens no connection): a test pins it, and passes at once.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_simulations_api.py b/backend/tests/apps/api/test_simulations_api.py
index f4031447..8c1a0eec 100644
--- a/backend/tests/apps/api/test_simulations_api.py
+++ b/backend/tests/apps/api/test_simulations_api.py
@@ -106,3 +106,24 @@ async def test_a_draft_that_cant_run_seeds_and_targets_are_refused_in_the_server
     looped = await create(api_sessionmaker, ctx, LOOP_GRAPH, name="looped")
     loop = await client.post(url(ctx, looped), json={"target": {"step_id": str(nid("l"))}}, headers=headers("k5"))
     assert (loop.status_code, loop.json()["error"]) == (422, "target_invalid")
+
+
+async def test_re_running_a_draft_run_or_a_published_child_of_one_is_refused(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """Spec §6.5: a draft run is never run again, on the published version or otherwise: simulate the draft again."""
+    from sqlalchemy import text
+
+    from tests.apps.test_admission import published
+    from tests.core.retention.support import RECENT, snapshot, tree
+
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings)
+    async with owner_sessionmaker() as s:
+        active = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
+    rows = {"t": ctx.tenant_id, "w": wf, "v": active, "u": ctx.user.id}
+    ran = await tree(owner_sessionmaker, rows, RECENT, snapshot=await snapshot(owner_sessionmaker, rows))
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "operator")
+    for n, run_id in enumerate((ran["root"], ran["sub"])):
+        answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}/rerun", json={},
+                                   headers={"Idempotency-Key": f"r{n}"})  # fmt: skip
+        assert (answer.status_code, answer.json()["error"]) == (409, "draft_run")
diff --git a/backend/tests/apps/test_admission_retirement.py b/backend/tests/apps/test_admission_retirement.py
index c9707980..82273d80 100644
--- a/backend/tests/apps/test_admission_retirement.py
+++ b/backend/tests/apps/test_admission_retirement.py
@@ -110,3 +110,22 @@ async def test_the_admin_cancels_only_a_queued_request_even_within_a_tenant_scop
             await tenant_scope(s, tenant)
             await s.execute(text("update run_requests set status = 'dead', ended_at = now() where id = :i"),
                             {"i": queued["id"]})  # fmt: skip
+
+
+async def test_a_queued_draft_simulation_blocks_normal_retirement_and_a_forced_one_cancels_it(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """B8 (the simulation design §6.5): a draft simulation's closure is its snapshot's, read as a version's would be,
+    so retirement never misses it."""
+    from tests.apps.test_admission_drafts import drafted, simulate
+
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, ECHO_GRAPH)
+    await current(dispatch_sessionmaker)
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
+    with pytest.raises(lifecycle.ReferencedError) as blocked:
+        async with admin_sessionmaker() as s, s.begin():
+            await lifecycle.retire(s, ECHO)
+    assert [(q.tenant_id, q.request_id) for q in blocked.value.preview.queued] == [(ctx.tenant_id, request.id)]
+    async with admin_sessionmaker() as s, s.begin():
+        await lifecycle.retire(s, ECHO, force=True, confirm=True)
+    assert await status(owner_sessionmaker, request.id) == ("cancelled", "node_type_retired", True)
diff --git a/backend/tests/apps/test_connection_fields.py b/backend/tests/apps/test_connection_fields.py
index 4e730fa7..a0610c2c 100644
--- a/backend/tests/apps/test_connection_fields.py
+++ b/backend/tests/apps/test_connection_fields.py
@@ -192,3 +192,21 @@ async def test_activating_refuses_a_version_naming_a_deleted_connection(
         ).scalar_one()
     with pytest.raises(workflow_ops.NotActivatableError):
         await activate(api_sessionmaker, ctx, child, old)
+
+
+@pytest.mark.usefixtures("development_deployment")
+async def test_a_connection_only_a_queued_draft_simulation_names_can_be_deleted(
+    owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """B8 (the simulation design §6.5): a simulation opens no connection, so a draft simulation never holds one in
+    use."""
+    from tests.apps.test_admission import current
+    from tests.apps.test_admission_drafts import simulate
+
+    await sync_test_plugins(admin_sessionmaker)
+    ctx = await actor(owner_sessionmaker)
+    cid = await connection(owner_sessionmaker, ctx.tenant_id)
+    wf = await create(api_sessionmaker, ctx, graph(str(cid)))
+    await current(dispatch_sessionmaker)
+    assert (await simulate(api_sessionmaker, ctx, wf, api_settings)).request.status == "queued"
+    await _delete(api_sessionmaker, ctx, cid)  # no version names it, enabled or queued
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/api/test_simulations_api.py
tests/apps/test_admission_retirement.py tests/apps/test_connection_fields.py tests/apps/api/test_run_requests_api.py
tests/core/plugins/test_lifecycle.py`

Expected: FAIL, 2 failed and 64 passed: a draft run's re-run is tried and answers `(410, 'input_not_retained')`, not
`(409, 'draft_run')`; a normal retirement doesn't see the queued simulation (`DID NOT RAISE ReferencedError`). The
connection test passes at once: "in use" already leaves draft requests out, and now a test says so.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
index 0b3390b0..1440634b 100644
--- a/backend/src/dewpoint/apps/api/routes/run_requests.py
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -41,6 +41,8 @@ NOT_FOUND = {admission.UPLOAD_NOT_FOUND}  # whoever's it is: an upload is its ow
 GONE = {admission.UPLOAD_EXPIRED}
 INPUT_NOT_RETAINED = "input_not_retained"
 REQUEST_NOT_RETAINED = "request_not_retained"  # an exact retry's request, past its retention cutoff
+DRAFT_RUN = "draft_run"
+DRAFT_RUN_MESSAGE = "This run simulated a draft: simulate the draft again."
 
 
 class CsvIn(BaseModel):
@@ -257,6 +259,8 @@ async def rerun(
     named = old if old is not None else run
     if named is None:
         raise HTTPException(404, detail={"error": "not_found"})
+    if await _of_a_draft(db, old, run):  # B8 (the simulation design §6.5): never run again, on a version or otherwise
+        raise HTTPException(409, detail={"error": DRAFT_RUN, "messages": [DRAFT_RUN_MESSAGE]})
     workflow_id, mode = named.workflow_id, given.mode or named.mode
     again = admission.Rerun(request_id, given.input, given.csv.start() if given.csv is not None else None)
     try:
@@ -286,6 +290,16 @@ async def rerun(
     return request_body(await admit(db, keys, ctx, workflow_id, "rerun", start, key, rerun=again))
 
 
+async def _of_a_draft(db: AsyncSession, old: RunRequest | None, run: Run | None) -> bool:
+    """Whether the request, or the run (a sub-run's tree's root), simulated a draft."""
+    if old is not None:
+        return old.draft_snapshot_id is not None
+    if run is None:
+        return False
+    root = run if run.root_run_id == run.id else await db.get(Run, run.root_run_id)
+    return root is not None and root.draft_snapshot_id is not None
+
+
 async def original_input(db: AsyncSession, keys: KeySource, tenant_id: uuid.UUID, old: RunRequest) -> dict[str, Any]:
     """A request's complete input, held in memory only: its envelope read through its own reader and every handle in
     it resolved, as the request that owns the claims (§7.7), bounded to the input limit whatever the store holds: past
diff --git a/backend/src/dewpoint/core/plugins/lifecycle.py b/backend/src/dewpoint/core/plugins/lifecycle.py
index 6ced1aca..eb696a7e 100644
--- a/backend/src/dewpoint/core/plugins/lifecycle.py
+++ b/backend/src/dewpoint/core/plugins/lifecycle.py
@@ -12,7 +12,7 @@ from collections.abc import Iterable, Mapping
 from dataclasses import dataclass, replace
 from typing import Literal
 
-from sqlalchemy import any_, func, literal, select, text, tuple_, update
+from sqlalchemy import any_, func, literal, select, text, tuple_, union_all, update
 from sqlalchemy.ext.asyncio import AsyncSession
 from sqlalchemy.orm import InstrumentedAttribute
 
@@ -20,7 +20,7 @@ from dewpoint.core.audit.service import record
 from dewpoint.core.db import tenant_scope
 from dewpoint.core.models.plugins import CelProfile, NodeTypeVersion
 from dewpoint.core.models.requests import RunRequest
-from dewpoint.core.models.workflows import Workflow, WorkflowVersion
+from dewpoint.core.models.workflows import DraftSnapshot, Workflow, WorkflowVersion
 from dewpoint.core.plugins.registry import split_ref
 
 Kind = Literal["node", "cel"]
@@ -133,8 +133,9 @@ class AffectedVersion:
 
 @dataclass(frozen=True)
 class QueuedRef:
-    """A run request that hasn't started, frozen on a version whose closure uses the entry: a `queued` one, which a
-    forced retirement cancels, or a `starting` one, which may still reach Temporal and is left to start or come back."""
+    """A run request that hasn't started, frozen on a version whose closure uses the entry (or a draft simulation's
+    snapshot, B8: `version_id` is then the snapshot's): a `queued` one, which a forced retirement cancels, or a
+    `starting` one, which may still reach Temporal and is left to start or come back."""
 
     tenant_id: uuid.UUID
     request_id: uuid.UUID
@@ -162,8 +163,10 @@ class ReferencedError(RuntimeError):
         self.preview = preview
 
 
-def _closure(entry: Entry) -> InstrumentedAttribute[list[str]]:
-    return WorkflowVersion.closure_node_refs if entry.kind == "node" else WorkflowVersion.closure_cel_profiles
+def _closure(
+    entry: Entry, frozen: type[WorkflowVersion | DraftSnapshot] = WorkflowVersion
+) -> InstrumentedAttribute[list[str]]:
+    return frozen.closure_node_refs if entry.kind == "node" else frozen.closure_cel_profiles
 
 
 async def _preview(s: AsyncSession, entry: Entry, state: str) -> RetirePreview:
@@ -190,11 +193,24 @@ async def _preview(s: AsyncSession, entry: Entry, state: str) -> RetirePreview:
         .order_by(Workflow.tenant_id, Workflow.name, WorkflowVersion.number)
     )
     versions = tuple(AffectedVersion(*row) for row in affected)
-    unstarted = await s.execute(
-        select(RunRequest.tenant_id, RunRequest.id, RunRequest.workflow_id, WorkflowVersion.id, RunRequest.status)
+    pending = RunRequest.status.in_(("queued", "starting"))
+    on_versions = (
+        select(RunRequest.tenant_id, RunRequest.id.label("request_id"), RunRequest.workflow_id,
+               WorkflowVersion.id.label("frozen_id"), RunRequest.status, RunRequest.queued_at)
         .join(WorkflowVersion, WorkflowVersion.id == RunRequest.workflow_version_id)
-        .where(uses, RunRequest.status.in_(("queued", "starting")))
-        .order_by(RunRequest.tenant_id, RunRequest.queued_at, RunRequest.id)
+        .where(uses, pending)
+    )  # fmt: skip
+    on_drafts = (  # a draft simulation's (B8): its closure is its snapshot's
+        select(RunRequest.tenant_id, RunRequest.id, RunRequest.workflow_id, DraftSnapshot.id, RunRequest.status,
+               RunRequest.queued_at)
+        .join(DraftSnapshot, DraftSnapshot.id == RunRequest.draft_snapshot_id)
+        .where(literal(entry.key) == any_(_closure(entry, DraftSnapshot)), pending)
+    )  # fmt: skip
+    both = union_all(on_versions, on_drafts).subquery()
+    unstarted = await s.execute(
+        select(both.c.tenant_id, both.c.request_id, both.c.workflow_id, both.c.frozen_id, both.c.status).order_by(
+            both.c.tenant_id, both.c.queued_at, both.c.request_id
+        )
     )
     queued = tuple(QueuedRef(*row) for row in unstarted)
     return RetirePreview(entry=entry, state=state, active_refs=refs, affected=versions, queued=queued)
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 66 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/api/routes/run_requests.py backend/src/dewpoint/core/plugins/lifecycle.py \
  backend/tests/apps/api/test_simulations_api.py backend/tests/apps/test_admission_retirement.py \
  backend/tests/apps/test_connection_fields.py
git commit -m "feat(runs): a draft run is never re-run, and retirement sees queued simulations (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: The milestone's ledger entry and the pause**

Append `### 4d-1b, milestone 2 (date)`, as for milestone 1. Commit (`docs(editor-4): 4d-1b milestone 2`). Then
**stop** for the owner's review.

---

# Milestone 3 — Readers and reads

### Task 9: Samples and the workflow list leave draft runs out

**Spec:** §6.5 (root-based exclusions).

**Files:**
- Modify: `backend/src/dewpoint/core/runs/samples.py` (the candidates)
- Modify: `backend/src/dewpoint/apps/workflow_summary.py` (`LAST_RUNS`, `COUNTS_24H`)
- Modify: `backend/tests/core/runs/test_samples.py`, `backend/tests/apps/api/test_workflow_summary.py`

**Interfaces:**
- Consumes: Task 2's `runs.draft_snapshot_id` and `runs_workflow_last_published`; Task 4's test support.
- Produces: nothing new.

A step's sample is never taken from a draft run's tree: its root's `draft_snapshot_id` is null, inside the candidates
before their limit, so a published sub-flow a draft run started is never one either. The workflow list's last runs
and 24-hour counts leave draft runs out (`draft_snapshot_id IS NULL`), served by `runs_workflow_last_published`
(ruling 16); the attention state follows them.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_workflow_summary.py b/backend/tests/apps/api/test_workflow_summary.py
index ac7864a7..154053a7 100644
--- a/backend/tests/apps/api/test_workflow_summary.py
+++ b/backend/tests/apps/api/test_workflow_summary.py
@@ -28,18 +28,20 @@ async def synced(admin_sessionmaker) -> None:
     await sync_test_plugins(admin_sessionmaker)
 
 
-async def add_run(owner, tid, wid, vid, *, status, mode="live", hours_ago=1.0, parent=None) -> uuid.UUID:
-    """A run row as the dispatcher writes one: a root run, or a sub-flow's when `parent` is given."""
+async def add_run(owner, tid, wid, vid, *, status, mode="live", hours_ago=1.0, parent=None, snapshot=None) -> uuid.UUID:
+    """A run row as the dispatcher writes one: a root run, or a sub-flow's when `parent` is given, or a draft
+    simulation's of `snapshot` (B8)."""
     rid = uuid.uuid4()
     async with owner() as s, s.begin():
         await s.execute(
             text(
-                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at,"
-                " iterations, kind, parent_run_id, parent_step_id) values (:i, :t, :w, :v, :m, :st,"
+                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, draft_snapshot_id, mode, status,"
+                " queued_at, iterations, kind, parent_run_id, parent_step_id) values (:i, :t, :w, :v, :snap, :m, :st,"
                 " now() - make_interval(secs => :ago), 0, :k, :p, :ps)"
             ),
             {
-                "i": rid, "t": tid, "w": wid, "v": vid, "m": mode, "st": status, "ago": hours_ago * 3600,
+                "i": rid, "t": tid, "w": wid, "v": None if snapshot else vid, "snap": snapshot,
+                "m": "simulate" if snapshot else mode, "st": status, "ago": hours_ago * 3600,
                 "k": "subflow" if parent else "run", "p": parent, "ps": uuid.uuid4() if parent else None,
             },
         )  # fmt: skip
@@ -115,6 +117,22 @@ async def test_a_failed_simulation_never_needs_attention(app, owner_sessionmaker
     assert row["needs_attention"] == []
 
 
+async def test_a_draft_simulation_never_counts_in_the_list(app, owner_sessionmaker, api_settings) -> None:
+    """B8 (the simulation design §6.5): a draft simulation is the editor's, not the workflow's: it's no last
+    simulation, no run of the last 24 hours, and never needs attention."""
+    from tests.core.retention.support import snapshot
+
+    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
+    async with c:
+        wid, vid = await published(c, tid)
+        await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", mode="simulate", hours_ago=2)
+        draft = await snapshot(owner_sessionmaker, {"v": uuid.UUID(str(vid))})
+        await add_run(owner_sessionmaker, tid, wid, vid, status="failed", hours_ago=1, snapshot=draft)
+        row = (await c.get(f"/api/v1/t/{tid}/workflows/{wid}")).json()
+    assert row["last_simulation"]["status"] == "succeeded" and row["runs_24h"] == {"live": 0, "simulate": 1}
+    assert row["last_run"] is None and row["needs_attention"] == []
+
+
 async def test_another_tenants_runs_never_count(app, owner_sessionmaker, api_settings) -> None:
     c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
     _, otid = await session_client(app, owner_sessionmaker, api_settings, "editor")
@@ -311,8 +329,8 @@ async def test_the_lists_reads_dont_grow_with_its_workflows(app, owner_sessionma
 # (migration 0047). REFERENCE is the statement it replaced, kept to prove the two answer the same.
 REFERENCE = text(
     "select distinct on (workflow_id, mode) workflow_id, mode, status, coalesce(ended_at, started_at, queued_at) as at"
-    " from runs where tenant_id = :tenant and kind = 'run' and workflow_id = any(cast(:ids as uuid[]))"
-    " order by workflow_id, mode, queued_at desc, id desc"
+    " from runs where tenant_id = :tenant and kind = 'run' and draft_snapshot_id is null"
+    " and workflow_id = any(cast(:ids as uuid[])) order by workflow_id, mode, queued_at desc, id desc"
 )
 
 
@@ -335,13 +353,18 @@ async def put_run(owner, tid, wid, vid, *, mode, status, at, rid=None, parent=No
 
 
 async def test_the_index_is_the_one_reserved(owner_sessionmaker) -> None:
+    """0047's, and 0072's, which leaves draft simulations out (B8): the read uses it."""
     async with owner_sessionmaker() as s:
-        found = await s.execute(text("select indexdef from pg_indexes where indexname = 'runs_workflow_last'"))
-        definition = found.scalar_one()
-    assert definition == (
-        "CREATE INDEX runs_workflow_last ON public.runs USING btree (workflow_id, mode, queued_at DESC, id DESC)"
-        " WHERE ((kind)::text = 'run'::text)"
-    )
+        named = "('runs_workflow_last', 'runs_workflow_last_published')"
+        found = await s.execute(text(f"select indexname, indexdef from pg_indexes where indexname in {named}"))
+        definitions = dict(found.all())
+    assert definitions == {
+        "runs_workflow_last": "CREATE INDEX runs_workflow_last ON public.runs USING btree (workflow_id, mode,"
+        " queued_at DESC, id DESC) WHERE ((kind)::text = 'run'::text)",
+        "runs_workflow_last_published": "CREATE INDEX runs_workflow_last_published ON public.runs USING btree"
+        " (workflow_id, mode, queued_at DESC, id DESC) WHERE (((kind)::text = 'run'::text) AND"
+        " (draft_snapshot_id IS NULL))",
+    }
 
 
 async def test_the_last_runs_read_answers_as_the_statement_it_replaced(
@@ -432,5 +455,5 @@ async def test_the_last_runs_read_examines_one_run_per_workflow_and_mode(
         query = text(f"explain (analyze, buffers, format json) {workflow_summary.LAST_RUNS.text}")
         plan = (await s.execute(query, params)).scalar_one()[0]["Plan"]
     rows, pages, how = runs_scanned(plan)
-    assert how == {"Index Scan runs_workflow_last"}  # ordered, stopping at the first row: no bitmap, no sort
+    assert how == {"Index Scan runs_workflow_last_published"}  # ordered, stopping at the first row: no bitmap, no sort
     assert rows <= 4 and pages <= 16  # 2 workflows x 2 modes: one lookup each, a few pages of the index and heap
diff --git a/backend/tests/core/runs/test_samples.py b/backend/tests/core/runs/test_samples.py
index 10ed1c96..56e61457 100644
--- a/backend/tests/core/runs/test_samples.py
+++ b/backend/tests/core/runs/test_samples.py
@@ -26,19 +26,21 @@ async def synced(admin_sessionmaker) -> None:
 
 async def _run(
     owner: Any, seeded: Seeded, *, status: str = "succeeded", ago: int = 0, mode: str = "live",
-    parent: uuid.UUID | None = None,
+    parent: uuid.UUID | None = None, snapshot: uuid.UUID | None = None,
 ) -> uuid.UUID:  # fmt: skip
-    """Another run of `seeded`'s workflow and version, queued `ago` minutes back; a sub-flow's when it has a parent."""
+    """Another run of `seeded`'s workflow and version, queued `ago` minutes back; a sub-flow's when it has a parent; a
+    draft simulation's of `snapshot` when given (B8)."""
     run = uuid.uuid4()
     async with owner() as s, s.begin():
         wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
         await s.execute(
             text(
-                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, ended_at, "
-                "kind, parent_run_id) values (:i, :t, :w, :v, :m, :st, :q, :e, :k, :p)"
+                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, draft_snapshot_id, mode, status, "
+                "queued_at, ended_at, kind, parent_run_id) values (:i, :t, :w, :v, :snap, :m, :st, :q, :e, :k, :p)"
             ),
-            {"i": run, "t": seeded.tenant, "w": wf, "v": seeded.version, "m": mode, "st": status,
-             "q": NOW - timedelta(minutes=ago), "e": None if status == "running" else NOW - timedelta(minutes=ago),
+            {"i": run, "t": seeded.tenant, "w": wf, "v": None if snapshot else seeded.version, "snap": snapshot,
+             "m": "simulate" if snapshot else mode, "st": status, "q": NOW - timedelta(minutes=ago),
+             "e": None if status == "running" else NOW - timedelta(minutes=ago),
              "k": "run" if parent is None else "subflow", "p": parent},
         )  # fmt: skip
     return run
@@ -71,6 +73,29 @@ async def _newest(api: Any, seeded: Seeded, iteration: str | None = None) -> sam
     return (await _search(api, seeded, iteration)).sample
 
 
+async def test_a_draft_run_and_a_published_child_of_one_are_never_samples(owner_sessionmaker, api_sessionmaker) -> None:
+    """B8 (the simulation design §6.5): by the root's provenance, before the newest runs are taken, so they never fill
+    the places a published run's sample would be found in."""
+    from tests.core.retention.support import snapshot
+
+    seeded = await seed_step(owner_sessionmaker, named=[None])
+    published = await _run(owner_sessionmaker, seeded, ago=10)
+    await _row(owner_sessionmaker, seeded, published, output={"v": "published"})
+    async with owner_sessionmaker() as s:
+        wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
+    draft = await _run(
+        owner_sessionmaker,
+        seeded,
+        ago=5,
+        snapshot=await snapshot(owner_sessionmaker, {"t": seeded.tenant, "w": wf, "v": seeded.version}),
+    )
+    child = await _run(owner_sessionmaker, seeded, ago=4, parent=draft)  # a published sub-flow inside the simulation
+    for run in (draft, child):
+        await _row(owner_sessionmaker, seeded, run, output={"v": "draft"})
+    found = await _newest(api_sessionmaker, seeded)
+    assert found is not None and (found.run_id, found.output) == (published, {"v": "published"})
+
+
 async def test_takes_the_newest_succeeded_row_of_an_ended_run(owner_sessionmaker, api_sessionmaker) -> None:
     seeded = await seed_step(owner_sessionmaker, named=[None])  # its own run is still running: never a candidate
     old, new = await _run(owner_sessionmaker, seeded, ago=10), await _run(owner_sessionmaker, seeded, ago=5)
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/api/test_workflow_summary.py
tests/core/runs/test_samples.py`

Expected: FAIL, 3 failed and 25 passed: the list counts the draft run (its last status `failed`, not the published run's
`succeeded`); the plan's index scan is `runs_workflow_last`, not `runs_workflow_last_published`; a published sub-run a
draft run started is taken as a sample. `test_the_index_is_the_one_reserved`, which now names both indexes, passes at
once: Task 2 made the new one.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/workflow_summary.py b/backend/src/dewpoint/apps/workflow_summary.py
index a3143ff8..0a27e336 100644
--- a/backend/src/dewpoint/apps/workflow_summary.py
+++ b/backend/src/dewpoint/apps/workflow_summary.py
@@ -20,20 +20,22 @@ from dewpoint.engine.graph.model import GraphFormatError, graph_hash, parse_grap
 ATTENTION_STATUSES = ("failed", "deadline_exceeded")
 
 # Each workflow's last root run of each mode, in one statement for every workflow (4b ruling 5), meant as one ordered
-# lookup of `runs_workflow_last` (migration 0047) per workflow and mode, however long its history; a workflow and mode
-# with no root run give no row. The mode is a lower bound that leads the order, checked for equality outside the
-# lookup (ledger M5): the first row is the mode's newest, or another mode's when it has none, which the outer
-# equality drops, so the answer is the exact-mode lookup's. Why not an equality inside: the planner then drops the mode
-# from the order, and `runs_tenant_queued (tenant_id, queued_at DESC, id DESC)` serves the order too; on a live-only
-# history it chose that index and read the tenant's whole history for each workflow and mode with no run. Bounded on
-# both sides, its default range estimate (0.5%) made it sort each workflow's runs of the mode. With this form, only
-# `runs_workflow_last` gives the order without a sort, and the probe and the work-unit test observed the ordered scan
-# on every workload they tried; it's what the planner chose there, not a guarantee for every future plan.
+# lookup of `runs_workflow_last_published` (migration 0072: 0047's `runs_workflow_last` without draft simulations, which
+# never count, B8) per workflow and mode, however long its history; a workflow and mode with no root run give no row.
+# The mode is a lower bound that leads the order, checked for equality outside the lookup (ledger M5): the first row is
+# the mode's newest, or another mode's when it has none, which the outer equality drops, so the answer is the exact-mode
+# lookup's. Why not an equality inside: the planner then drops the mode from the order, and `runs_tenant_queued
+# (tenant_id, queued_at DESC, id DESC)` serves the order too; on a live-only history it chose that index and read the
+# tenant's whole history for each workflow and mode with no run. Bounded on both sides, its default range estimate
+# (0.5%) made it sort each workflow's runs of the mode. With this form, only the index gives the order without a sort,
+# and the probe and the work-unit test observed the ordered scan on every workload they tried; it's what the planner
+# chose there, not a guarantee for every future plan.
 LAST_RUNS = text(
     "select w.id as workflow_id, m.mode, r.status, r.at"
     " from unnest(cast(:ids as uuid[])) as w(id) cross join (values ('live'), ('simulate')) as m(mode)"
     " cross join lateral (select mode, status, coalesce(ended_at, started_at, queued_at) as at from runs"
-    " where tenant_id = :tenant and kind = 'run' and workflow_id = w.id and mode >= m.mode"
+    " where tenant_id = :tenant and kind = 'run' and draft_snapshot_id is null and workflow_id = w.id"
+    " and mode >= m.mode"
     " order by mode, queued_at desc, id desc limit 1) as r where r.mode = m.mode"
 )
 # Each workflow's root runs queued in the last 24 hours, by the database's clock (its clock wrote the rows): a range of
@@ -41,8 +43,8 @@ LAST_RUNS = text(
 COUNTS_24H = text(
     "select workflow_id, count(*) filter (where mode = 'live') as live,"
     " count(*) filter (where mode = 'simulate') as simulated"
-    " from runs where tenant_id = :tenant and kind = 'run' and workflow_id = any(cast(:ids as uuid[]))"
-    " and queued_at >= now() - interval '24 hours' group by workflow_id"
+    " from runs where tenant_id = :tenant and kind = 'run' and draft_snapshot_id is null"
+    " and workflow_id = any(cast(:ids as uuid[])) and queued_at >= now() - interval '24 hours' group by workflow_id"
 )
 
 # Each workflow's triggers, in one statement for every workflow (4c-3a ruling 3): its live schedules (a deleted one's
diff --git a/backend/src/dewpoint/core/runs/samples.py b/backend/src/dewpoint/core/runs/samples.py
index b9bb41e8..4ed5bdd2 100644
--- a/backend/src/dewpoint/core/runs/samples.py
+++ b/backend/src/dewpoint/core/runs/samples.py
@@ -90,6 +90,7 @@ async def newest(
         .join(root, (root.id == Run.root_run_id) & (root.tenant_id == Run.tenant_id))
         .where(Run.tenant_id == tenant_id, Run.workflow_id == workflow_id)
         .where(Run.status != "running", Run.ended_at.is_not(None), kept(root.ended_at, at))
+        .where(root.draft_snapshot_id.is_(None))  # a draft simulation's tree is never a sample (B8; design §6.5)
         .order_by(Run.ended_at.desc(), Run.id.desc())
         .limit(SCAN_RUNS)
         .cte("candidates")
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 28 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/core/runs/samples.py backend/src/dewpoint/apps/workflow_summary.py \
  backend/tests/core/runs/test_samples.py backend/tests/apps/api/test_workflow_summary.py
git commit -m "feat(runs): draft runs are never samples, nor counted in the workflow list (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The run API names a draft run's snapshot; a snapshot's graph

**Spec:** §6.5.

**Files:**
- Modify: `backend/src/dewpoint/core/runs/service.py` (`Listed`, `list_items`)
- Modify: `backend/src/dewpoint/apps/api/routes/runs.py` (`_id`, the draft fields, a step's `effect`)
- Modify: `backend/src/dewpoint/apps/api/routes/run_requests.py` (`request_body`)
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`DraftSnapshotOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/simulations.py` (`snapshot`)
- Modify: `backend/src/dewpoint/apps/api/openapi.py` (`GRAPH_PROPERTIES`)
- Modify: `backend/tests/apps/api/test_simulations_api.py`, `backend/tests/apps/api/test_openapi.py`

**Interfaces:**
- Consumes: Task 6's route module.
- Produces: `draft_snapshot_id` and `target_step_id` on every run and request the run API returns, `version_id` null
  for a draft run; a step's `effect` (4d-1a's `effect_preview`); `GET …/workflows/{workflow}/draft/snapshots/{id}`
  (`workflow.view`) answering `DraftSnapshotOut`, its graph documented as `Graph`.

A run serialized with no version said `"None"` as its `version_id` (`str(None)`): `_id` answers null.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_openapi.py b/backend/tests/apps/api/test_openapi.py
index fb281605..ca730b4a 100644
--- a/backend/tests/apps/api/test_openapi.py
+++ b/backend/tests/apps/api/test_openapi.py
@@ -193,6 +193,7 @@ def test_slice_4c3_routes_name_their_answer(method: str, path: str) -> None:
 
 SLICE_4D1 = [  # B8 (the simulation design §6.3, §6.6)
     ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations"),
+    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/snapshots/{snapshot_id}"),
 ]
 
 
diff --git a/backend/tests/apps/api/test_simulations_api.py b/backend/tests/apps/api/test_simulations_api.py
index 8c1a0eec..02ad172b 100644
--- a/backend/tests/apps/api/test_simulations_api.py
+++ b/backend/tests/apps/api/test_simulations_api.py
@@ -11,7 +11,7 @@ import pytest
 
 from tests.apps.api.test_run_requests_api import as_role, keyed_app
 from tests.apps.test_admission import current
-from tests.apps.test_admission_drafts import LOOP_GRAPH, STEPS_GRAPH, drafted
+from tests.apps.test_admission_drafts import LOOP_GRAPH, STEPS_GRAPH, drafted, simulate
 from tests.apps.test_workflow_ops import create, save
 from tests.support.graphs import G, nid
 
@@ -127,3 +127,54 @@ async def test_re_running_a_draft_run_or_a_published_child_of_one_is_refused(
         answer = await client.post(f"/api/v1/t/{ctx.tenant_id}/runs/{run_id}/rerun", json={},
                                    headers={"Idempotency-Key": f"r{n}"})  # fmt: skip
         assert (answer.status_code, answer.json()["error"]) == (409, "draft_run")
+
+
+async def test_the_runs_api_shows_a_draft_runs_snapshot_target_and_each_steps_effect(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """Spec §6.5: a draft run, queued or started, names its snapshot and its target, and no version (D-b3: readable
+    with `run.view`); a step shows what it did besides its output (4d-1a's `effect_preview`)."""
+    from sqlalchemy import text
+
+    from tests.apps.dispatcher.support import begin, workers
+
+    ctx, wf = ready
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
+                              values={"/steps/a/output/value": 5})).request  # fmt: skip
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    shown = {k: v for k, v in (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs")).json()[0].items()
+             if k in ("id", "version_id", "draft_snapshot_id", "target_step_id")}  # fmt: skip
+    assert shown == {"id": str(request.id), "version_id": None, "draft_snapshot_id": str(request.draft_snapshot_id),
+                     "target_step_id": str(nid("b"))}  # fmt: skip
+    await workers(owner_sessionmaker)
+    await begin(dispatch_sessionmaker, request, api_settings)
+    async with owner_sessionmaker() as s, s.begin():  # as the worker's projection leaves it
+        await s.execute(text("update run_requests set status = 'started' where id = :i"), {"i": request.id})
+        await s.execute(text("update runs set started_at = now() where id = :i"), {"i": request.id})
+        await s.execute(text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, "
+                             "status, effect_preview) values (:t, :r, :s, '', 1, 'b', 'succeeded', :e)"),
+                        {"t": ctx.tenant_id, "r": request.id, "s": nid("b"), "e": '{"port": "true"}'})  # fmt: skip
+    run = (await viewer.get(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}")).json()
+    assert (run["version_id"], run["draft_snapshot_id"], run["target_step_id"]) == (
+        None, str(request.draft_snapshot_id), str(nid("b")),
+    )  # fmt: skip
+    assert [(step["key"], step["effect"]) for step in run["steps"]] == [("b", {"port": "true"})]
+
+
+async def test_a_draft_snapshot_is_read_with_its_graph(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    """Spec §6.5: B4a's version read, for a draft run's snapshot (`workflow.view`)."""
+    ctx, wf = ready
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    base = f"/api/v1/t/{ctx.tenant_id}/workflows"
+    answer = await viewer.get(f"{base}/{wf}/draft/snapshots/{request.draft_snapshot_id}")
+    assert answer.status_code == 200, answer.text
+    body = answer.json()
+    assert (body["id"], body["draft_revision"]) == (str(request.draft_snapshot_id), 1)
+    assert [n["key"] for n in body["graph"]["nodes"]] == ["a", "b"] and body["expressions"] == []
+    other = await create(api_sessionmaker, ctx, STEPS_GRAPH, name="other")
+    for path in (f"{base}/{other}/draft/snapshots/{request.draft_snapshot_id}",
+                 f"{base}/{wf}/draft/snapshots/{uuid.uuid4()}"):  # fmt: skip
+        assert (await viewer.get(path)).status_code == 404
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/api/test_simulations_api.py
tests/apps/api/test_openapi.py tests/apps/api/test_runs_api.py tests/core/runs`

Expected: FAIL, 3 failed and 123 passed: the runs list shows the draft run without `draft_snapshot_id` and
`target_step_id` (the right side holds 2 more items); the snapshot route answers 404 and the schema has no such path
(KeyError).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/openapi.py b/backend/src/dewpoint/apps/api/openapi.py
index 2c43bcd8..cca47d22 100644
--- a/backend/src/dewpoint/apps/api/openapi.py
+++ b/backend/src/dewpoint/apps/api/openapi.py
@@ -72,6 +72,7 @@ GRAPH_PROPERTIES: tuple[tuple[str, str], ...] = (
     ("WorkflowDetailOut", "draft"),
     ("VersionDetailOut", "graph"),
     ("WorkflowDocument", "graph"),
+    ("DraftSnapshotOut", "graph"),
 )
 
 
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 7f412755..f7be3a88 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -626,3 +626,20 @@ class SimulationOut(_Answer):
     queued_at: str | None
     ended_at: str | None
     admission_checks: list[DiagnosticOut]
+
+
+class DraftSnapshotOut(_Answer):
+    """A draft simulation's snapshot whole (B8; the simulation design §6.5): what B4a's version read is for a version,
+    its graph verbatim as frozen (documented as a Graph), and how each of its expressions runs."""
+
+    id: str
+    workflow_id: str
+    draft_revision: int
+    created_at: str
+    graph_hash: str
+    version_hash: str
+    cel_profile: str
+    engine_abi: int
+    node_refs: list[str]
+    graph: dict[str, Any]
+    expressions: list[ExpressionOut]
diff --git a/backend/src/dewpoint/apps/api/routes/run_requests.py b/backend/src/dewpoint/apps/api/routes/run_requests.py
index 1440634b..0ee56901 100644
--- a/backend/src/dewpoint/apps/api/routes/run_requests.py
+++ b/backend/src/dewpoint/apps/api/routes/run_requests.py
@@ -111,6 +111,8 @@ def request_body(r: RunRequest) -> dict[str, object]:
         "id": str(r.id),
         "workflow_id": str(r.workflow_id),
         "version_id": str(r.workflow_version_id) if r.workflow_version_id else None,
+        "draft_snapshot_id": str(r.draft_snapshot_id) if r.draft_snapshot_id else None,  # a draft simulation's (B8)
+        "target_step_id": str(r.target_step_id) if r.target_step_id else None,
         "mode": r.mode,
         "source": r.source,
         "status": r.status,
diff --git a/backend/src/dewpoint/apps/api/routes/runs.py b/backend/src/dewpoint/apps/api/routes/runs.py
index 42afccee..4c5d71d5 100644
--- a/backend/src/dewpoint/apps/api/routes/runs.py
+++ b/backend/src/dewpoint/apps/api/routes/runs.py
@@ -28,6 +28,10 @@ def _when(value: datetime | None) -> str | None:
     return value.isoformat() if value else None
 
 
+def _id(value: uuid.UUID | None) -> str | None:
+    return str(value) if value else None
+
+
 def _request(r: RunRequest | None) -> dict[str, object] | None:
     return {"status": r.status, "source": r.source, "reason": r.reason} if r is not None else None
 
@@ -36,7 +40,9 @@ def _item(i: service.Listed) -> dict[str, object]:
     return {
         "id": str(i.id),
         "workflow_id": str(i.workflow_id),
-        "version_id": str(i.version_id) if i.version_id else None,
+        "version_id": _id(i.version_id),
+        "draft_snapshot_id": _id(i.draft_snapshot_id),  # a draft simulation's (B8): no version
+        "target_step_id": _id(i.target_step_id),
         "mode": i.mode,
         "status": i.status,
         "queued_at": _when(i.queued_at),
@@ -55,7 +61,9 @@ def _unstarted(r: RunRequest) -> dict[str, object]:
     return {
         "id": str(r.id),
         "workflow_id": str(r.workflow_id),
-        "version_id": str(r.workflow_version_id) if r.workflow_version_id else None,
+        "version_id": _id(r.workflow_version_id),
+        "draft_snapshot_id": _id(r.draft_snapshot_id),
+        "target_step_id": _id(r.target_step_id),
         "mode": r.mode,
         "status": r.status,
         "queued_at": _when(r.queued_at),
@@ -73,7 +81,9 @@ def _run(r: Run) -> dict[str, object]:
     return {
         "id": str(r.id),
         "workflow_id": str(r.workflow_id),
-        "version_id": str(r.workflow_version_id),
+        "version_id": _id(r.workflow_version_id),
+        "draft_snapshot_id": _id(r.draft_snapshot_id),
+        "target_step_id": _id(r.target_step_id),
         "mode": r.mode,
         "status": r.status,
         "queued_at": _when(r.queued_at),
@@ -108,6 +118,7 @@ def _step(r: RunStep) -> dict[str, object]:
         "error": {"code": r.error_code, "message": r.error_message} if r.error_code else None,
         "outcome": r.outcome,
         "cel_mode": r.cel_mode,
+        "effect": r.effect_preview,  # a control step's port or assignments (4d-1a), masked as its previews are
     }
 
 
diff --git a/backend/src/dewpoint/apps/api/routes/simulations.py b/backend/src/dewpoint/apps/api/routes/simulations.py
index 9e910d70..e35172f2 100644
--- a/backend/src/dewpoint/apps/api/routes/simulations.py
+++ b/backend/src/dewpoint/apps/api/routes/simulations.py
@@ -9,10 +9,11 @@ from typing import Any
 
 from fastapi import APIRouter, Depends, Header, HTTPException
 from pydantic import BaseModel, ConfigDict, Field, model_validator
+from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import admission
-from dewpoint.apps.api.responses import SimulationOut
+from dewpoint.apps.api.responses import DraftSnapshotOut, SimulationOut
 from dewpoint.apps.api.routes.run_requests import (
     INVALID,
     UNAVAILABLE,
@@ -28,6 +29,7 @@ from dewpoint.core.config import Settings
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
 from dewpoint.core.models.requests import RunRequest
+from dewpoint.core.models.workflows import DraftSnapshot
 from dewpoint.core.workflows.service import DraftConflictError
 
 router = APIRouter(prefix="/api/v1", tags=["simulations"])
@@ -107,3 +109,35 @@ async def simulate(
     if not admitted.new:
         await not_past_cutoff(db, ctx, admitted.request)
     return simulation_body(admitted.request)
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/snapshots/{snapshot_id}", response_model=DraftSnapshotOut)
+async def snapshot(
+    workflow_id: uuid.UUID,
+    snapshot_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """A draft run's snapshot (B8; the simulation design §6.5), as B4a's read shows a version."""
+    found = await db.execute(
+        select(DraftSnapshot).where(DraftSnapshot.id == snapshot_id, DraftSnapshot.workflow_id == workflow_id)
+    )
+    s = found.scalar_one_or_none()
+    if s is None:
+        raise HTTPException(404, detail={"error": "not_found"})
+    return {
+        "id": str(s.id),
+        "workflow_id": str(s.workflow_id),
+        "draft_revision": s.draft_revision,
+        "created_at": s.created_at.isoformat(),
+        "graph_hash": s.graph_hash,
+        "version_hash": s.version_hash,
+        "cel_profile": s.cel_profile,
+        "engine_abi": s.engine_abi,
+        "node_refs": list(s.node_refs),
+        "graph": s.graph,
+        "expressions": [
+            {"node": e.get("node"), "field": e["field"], "mode": e["mode"], "reason": e.get("reason")}
+            for e in s.expressions
+        ],
+    }
diff --git a/backend/src/dewpoint/core/runs/service.py b/backend/src/dewpoint/core/runs/service.py
index 21789855..55f8e1a2 100644
--- a/backend/src/dewpoint/core/runs/service.py
+++ b/backend/src/dewpoint/core/runs/service.py
@@ -376,6 +376,8 @@ class Listed:
     id: uuid.UUID
     workflow_id: uuid.UUID
     version_id: uuid.UUID | None
+    draft_snapshot_id: uuid.UUID | None  # a draft simulation's (B8), and the step it ran alone (S2)
+    target_step_id: uuid.UUID | None
     mode: str
     status: str
     queued_at: datetime
@@ -403,7 +405,8 @@ async def list_items(
     the retention cutoff `kept_after` is (§10.1): every run listed is a root, so its own end is its tree's."""
     runs = (
         select(
-            Run.id, Run.workflow_id, Run.workflow_version_id.label("version_id"), Run.mode, Run.status, Run.queued_at,
+            Run.id, Run.workflow_id, Run.workflow_version_id.label("version_id"), Run.draft_snapshot_id,
+            Run.target_step_id, Run.mode, Run.status, Run.queued_at,
             Run.started_at, Run.ended_at, Run.error_code, Run.error_message, Run.iterations, Run.kind,
             RunRequest.status.label("request_status"), RunRequest.source, RunRequest.reason,
         )
@@ -412,7 +415,8 @@ async def list_items(
                kept(Run.ended_at, kept_after))
     )  # fmt: skip
     requests = select(
-        RunRequest.id, RunRequest.workflow_id, RunRequest.workflow_version_id.label("version_id"), RunRequest.mode,
+        RunRequest.id, RunRequest.workflow_id, RunRequest.workflow_version_id.label("version_id"),
+        RunRequest.draft_snapshot_id, RunRequest.target_step_id, RunRequest.mode,
         RunRequest.status, RunRequest.queued_at, null().label("started_at"), RunRequest.ended_at,
         null().label("error_code"), null().label("error_message"), literal(0).label("iterations"),
         literal("run").label("kind"), RunRequest.status.label("request_status"), RunRequest.source, RunRequest.reason,
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 126 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/core/runs/service.py backend/src/dewpoint/apps/api/routes/runs.py \
  backend/src/dewpoint/apps/api/routes/run_requests.py backend/src/dewpoint/apps/api/responses.py \
  backend/src/dewpoint/apps/api/routes/simulations.py backend/src/dewpoint/apps/api/openapi.py \
  backend/tests/apps/api/test_simulations_api.py backend/tests/apps/api/test_openapi.py
git commit -m "feat(api): a draft run names its snapshot and target; a snapshot's graph is read (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The person's simulations, a simulation's state, and what it ran with

**Spec:** §6.6 (the latest simulations, the state, the read-back).

**Files:**
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`SimulationRunOut`, `SimulationStateOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/simulations.py` (`mine`, `state`, `simulation_of`, `read_back`)
- Create: `backend/tests/apps/api/test_simulation_reads.py`
- Modify: `backend/tests/apps/api/test_openapi.py`

**Interfaces:**
- Consumes: `claims.read_envelope`, `ClaimRef.of`, `projection.REDACTED`, `retention.kept`/`request_kept`.
- Produces: `GET …/draft/simulations` (`run.view`, `limit` 1–50) answering `list[SimulationOut]`; `GET
  …/draft/simulations/{request_id}` answering `SimulationStateOut {request, run, cancel_requested, input, seeds}`;
  `async simulations.simulation_of(db, ctx, workflow_id, request_id) -> RunRequest` (404 unless it's this workflow's
  simulation, within retention).

The list is the caller's own (ruling 11). The input or seeds come from the request's own envelope, every claim in it
`[redacted]`: never recomputed from the draft as it is now, and `null` once retention removed it.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_openapi.py b/backend/tests/apps/api/test_openapi.py
index ca730b4a..16eeb6de 100644
--- a/backend/tests/apps/api/test_openapi.py
+++ b/backend/tests/apps/api/test_openapi.py
@@ -194,6 +194,8 @@ def test_slice_4c3_routes_name_their_answer(method: str, path: str) -> None:
 SLICE_4D1 = [  # B8 (the simulation design §6.3, §6.6)
     ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations"),
     ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/snapshots/{snapshot_id}"),
+    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations"),
+    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}"),
 ]
 
 
diff --git a/backend/tests/apps/api/test_simulation_reads.py b/backend/tests/apps/api/test_simulation_reads.py
new file mode 100644
index 00000000..af4a50e8
--- /dev/null
+++ b/backend/tests/apps/api/test_simulation_reads.py
@@ -0,0 +1,108 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A draft simulation's reads (B8; the simulation design §6.6), `run.view` (D-b3): the person's latest simulations of a
+workflow, newest first, labelled with their revision; a simulation's state, a requested cancel included; the input or
+seeds it used, read back from its own request, redacted, never recomputed from the draft as it is now."""
+
+import uuid
+from typing import Any
+
+import pytest
+
+from tests.apps.api.test_run_requests_api import as_role, keyed_app
+from tests.apps.dispatcher.support import begin, workers
+from tests.apps.test_admission import TOKEN, TOKEN_GRAPH, current
+from tests.apps.test_admission_drafts import STEPS_GRAPH, drafted, simulate
+from tests.apps.test_workflow_ops import create, save
+from tests.support.graphs import nid
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
+
+
+def simulations(ctx: Any, wf: uuid.UUID, request_id: uuid.UUID | None = None) -> str:
+    base = f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/simulations"
+    return base if request_id is None else f"{base}/{request_id}"
+
+
+@pytest.fixture
+async def ready(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker) -> Any:
+    await current(dispatch_sessionmaker)
+    return await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, TOKEN_GRAPH)
+
+
+async def test_a_person_reads_their_own_latest_simulations_of_a_workflow_newest_first(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    me = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    them = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+
+    async def post(client: Any, key: str, revision: int, workflow: uuid.UUID = wf) -> str:
+        answer = await client.post(simulations(ctx, workflow), json={"input": {"token": TOKEN}},
+                                   headers={"Idempotency-Key": key, "If-Match": str(revision)})  # fmt: skip
+        assert answer.status_code == 202, answer.text
+        return str(answer.json()["id"])
+
+    first = await post(me, "a1", 1)
+    await save(api_sessionmaker, ctx, wf, TOKEN_GRAPH)  # revision 2
+    second = await post(me, "a2", 2)
+    theirs = await post(them, "b1", 2)
+    await post(me, "a3", 1, await create(api_sessionmaker, ctx, TOKEN_GRAPH, name="other"))
+    listed = (await me.get(simulations(ctx, wf))).json()
+    assert [(s["id"], s["draft_revision"]) for s in listed] == [(second, 2), (first, 1)]
+    assert [s["id"] for s in (await me.get(simulations(ctx, wf), params={"limit": 1})).json()] == [second]
+    assert [s["id"] for s in (await them.get(simulations(ctx, wf))).json()] == [theirs]
+
+
+async def test_a_simulations_state_says_where_it_is_and_whether_a_cancel_was_requested(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN, "site": "a"})).request
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    state = (await viewer.get(simulations(ctx, wf, request.id))).json()
+    assert (state["request"]["status"], state["run"], state["cancel_requested"]) == ("queued", None, False)
+    await workers(owner_sessionmaker)
+    await begin(dispatch_sessionmaker, request, api_settings)  # starting: a cancel is only requested
+    operator = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "operator")
+    cancel = await operator.post(f"/api/v1/t/{ctx.tenant_id}/runs/{request.id}/cancel")
+    assert cancel.status_code == 202
+    state = (await viewer.get(simulations(ctx, wf, request.id))).json()
+    assert (state["request"]["status"], state["cancel_requested"]) == ("starting", True)
+    assert state["run"]["status"] == "running"  # the row dispatch wrote before Temporal answered
+
+
+async def test_the_input_used_is_read_back_redacted_from_the_request_whatever_the_draft_became(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN, "site": "a"})).request
+    await save(api_sessionmaker, ctx, wf, STEPS_GRAPH)  # the draft moves on: the request's own input is read back
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    answer = await viewer.get(simulations(ctx, wf, request.id))
+    assert answer.json()["input"] == {"token": "[redacted]", "site": "a"} and answer.json()["seeds"] is None
+    assert TOKEN not in answer.text
+
+
+async def test_a_step_tests_seeds_are_read_back_redacted(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    await current(dispatch_sessionmaker)
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
+                              values={"/steps/a/output/value": 5})).request  # fmt: skip
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    state = (await viewer.get(simulations(ctx, wf, request.id))).json()
+    assert state["seeds"] == {"values": {"/steps/a/output/value": "[redacted]"}, "absent": []}  # an echo's: tainted
+    assert state["input"] is None
+
+
+async def test_another_workflows_or_a_published_runs_request_is_not_a_simulation_of_this_one(
+    keyed_app, ready, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    ctx, wf = ready
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, input={"token": TOKEN})).request
+    other = await create(api_sessionmaker, ctx, TOKEN_GRAPH, name="other")
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    for path in (simulations(ctx, other, request.id), simulations(ctx, wf, uuid.uuid4())):
+        assert (await viewer.get(path)).status_code == 404
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/api/test_simulation_reads.py
tests/apps/api/test_openapi.py`

Expected: FAIL, 6 failed and 74 passed: neither read exists yet. `GET …/draft/simulations` meets only the POST (405, so
the list isn't a list: TypeError), and a simulation's state answers 404, so its body has no `request`, `input` or
`seeds` (KeyError); the schema has neither GET (KeyError). The not-found test passes at once: everything is not found
yet.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index f7be3a88..38f2a2fb 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -643,3 +643,27 @@ class DraftSnapshotOut(_Answer):
     node_refs: list[str]
     graph: dict[str, Any]
     expressions: list[ExpressionOut]
+
+
+class SimulationRunOut(_Answer):
+    """A draft simulation's run, once dispatch wrote it (B8): its own state."""
+
+    status: Literal["running", "succeeded", "failed", "cancelled", "deadline_exceeded"]
+    queued_at: str | None
+    started_at: str | None
+    ended_at: str | None
+    error: dict[str, Any] | None  # {code, message}
+    iterations: int
+
+
+class SimulationStateOut(_Answer):
+    """A draft simulation where it is (B8; the simulation design §6.6): its request, its run once there is one,
+    whether a cancel was requested, and what it ran with, read back from its own request, redacted (`[redacted]` in
+    place of what its envelope holds as claims), never recomputed from the draft as it is now: its `input`, or a step
+    test's `seeds` (S2)."""
+
+    request: SimulationOut
+    run: SimulationRunOut | None
+    cancel_requested: bool
+    input: dict[str, Any] | None
+    seeds: dict[str, Any] | None
diff --git a/backend/src/dewpoint/apps/api/routes/simulations.py b/backend/src/dewpoint/apps/api/routes/simulations.py
index e35172f2..5a715fef 100644
--- a/backend/src/dewpoint/apps/api/routes/simulations.py
+++ b/backend/src/dewpoint/apps/api/routes/simulations.py
@@ -7,13 +7,13 @@ values it reads (S2). It needs `workflow.edit` and `run.start`; cancelling is th
 import uuid
 from typing import Any
 
-from fastapi import APIRouter, Depends, Header, HTTPException
+from fastapi import APIRouter, Depends, Header, HTTPException, Query
 from pydantic import BaseModel, ConfigDict, Field, model_validator
 from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from dewpoint.apps import admission
-from dewpoint.apps.api.responses import DraftSnapshotOut, SimulationOut
+from dewpoint.apps.api.responses import DraftSnapshotOut, SimulationOut, SimulationStateOut
 from dewpoint.apps.api.routes.run_requests import (
     INVALID,
     UNAVAILABLE,
@@ -25,12 +25,18 @@ from dewpoint.apps.api.routes.run_requests import (
 )
 from dewpoint.apps.api.routes.workflows import _revision
 from dewpoint.core.authz.permissions import P
+from dewpoint.core.claims import service as claims
+from dewpoint.core.claims.cipher import ClaimCipher
 from dewpoint.core.config import Settings
 from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
 from dewpoint.core.models.requests import RunRequest
+from dewpoint.core.models.runs import Run
 from dewpoint.core.models.workflows import DraftSnapshot
+from dewpoint.core.retention import cutoff as retention
 from dewpoint.core.workflows.service import DraftConflictError
+from dewpoint.engine.handles import ClaimRef
+from dewpoint.engine.runtime.projection import REDACTED
 
 router = APIRouter(prefix="/api/v1", tags=["simulations"])
 
@@ -141,3 +147,93 @@ async def snapshot(
             for e in s.expressions
         ],
     }
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations", response_model=list[SimulationOut])
+async def mine(
+    workflow_id: uuid.UUID,
+    limit: int = Query(20, ge=1, le=50),
+    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> list[dict[str, object]]:
+    """The caller's own latest draft simulations of the workflow, newest first (§6.6): what they started, labelled
+    with their revision, never proof of what a submission was (the editor recovers by its own request's key)."""
+    found = await db.execute(
+        select(RunRequest)
+        .where(
+            RunRequest.workflow_id == workflow_id,
+            RunRequest.actor_id == ctx.user.id,
+            RunRequest.draft_snapshot_id.is_not(None),
+            retention.kept(RunRequest.ended_at, await retention.cutoff(db, ctx.tenant_id)),
+        )
+        .order_by(RunRequest.queued_at.desc(), RunRequest.id.desc())
+        .limit(limit)
+    )
+    return [simulation_body(r) for r in found.scalars()]
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}", response_model=SimulationStateOut)
+async def state(
+    workflow_id: uuid.UUID,
+    request_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    keys: KeySource = Depends(get_keys),
+) -> dict[str, object]:
+    """A draft simulation where it is (§6.6), and what it ran with, read back redacted from its own request."""
+    r = await simulation_of(db, ctx, workflow_id, request_id)
+    run = await db.get(Run, r.id)
+    used = await read_back(db, keys, ctx, r)
+    return {
+        "request": simulation_body(r),
+        "run": None if run is None else {
+            "status": run.status,
+            "queued_at": run.queued_at.isoformat() if run.queued_at else None,
+            "started_at": run.started_at.isoformat() if run.started_at else None,
+            "ended_at": run.ended_at.isoformat() if run.ended_at else None,
+            "error": {"code": run.error_code, "message": run.error_message} if run.error_code else None,
+            "iterations": run.iterations,
+        },
+        "cancel_requested": r.cancel_requested_at is not None,
+        "input": used if r.target_step_id is None else None,
+        "seeds": used if r.target_step_id is not None else None,
+    }  # fmt: skip
+
+
+async def simulation_of(
+    db: AsyncSession, ctx: TenantContext, workflow_id: uuid.UUID, request_id: uuid.UUID
+) -> RunRequest:
+    """The workflow's draft simulation `request_id`, within retention; else 404."""
+    found = await db.execute(
+        select(RunRequest).where(
+            RunRequest.id == request_id,
+            RunRequest.workflow_id == workflow_id,
+            RunRequest.draft_snapshot_id.is_not(None),
+        )
+    )
+    r = found.scalar_one_or_none()
+    if r is None or not await retention.request_kept(db, await retention.cutoff(db, ctx.tenant_id), r):
+        raise HTTPException(404, detail={"error": "not_found"})
+    return r
+
+
+async def read_back(db: AsyncSession, keys: KeySource, ctx: TenantContext, r: RunRequest) -> Any:
+    """The request's own envelope, each claim in it `[redacted]` (a sensitive value, or one claimed by its size): the
+    input or seeds it was admitted with, never recomputed. None once retention removed it."""
+    try:
+        envelope = await claims.read_envelope(db, ClaimCipher(keys), ctx.tenant_id, request_id=r.id)
+    except claims.EnvelopeUnavailableError:
+        return None
+    except Exception as e:
+        raise key_unusable(e) from None
+    return _redacted(envelope)
+
+
+def _redacted(value: Any) -> Any:
+    if ClaimRef.of(value) is not None:
+        return REDACTED
+    if isinstance(value, dict):
+        return {k: _redacted(v) for k, v in value.items()}
+    if isinstance(value, list):
+        return [_redacted(v) for v in value]
+    return value
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 80 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/api/responses.py backend/src/dewpoint/apps/api/routes/simulations.py \
  backend/tests/apps/api/test_simulation_reads.py backend/tests/apps/api/test_openapi.py
git commit -m "feat(api): a person's simulations, a simulation's state, and what it ran with, redacted (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: The per-step summary and a step's instances

**Spec:** §6.6 (the summary, the instances), §7.3, §7.4, D-a5.

**Files:**
- Create: `backend/src/dewpoint/apps/step_summary.py`
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`StepSummaryOut`, `SimulationStepsOut`, `StepInstancesOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/simulations.py` (`simulation_steps`, `step_instances`, `_steps_of`)
- Create: `backend/tests/apps/test_step_summary.py`, `backend/tests/apps/api/test_simulation_steps.py`
- Modify: `backend/tests/apps/api/test_openapi.py`

**Interfaces:**
- Consumes: Task 11's `simulation_of`; `routes.runs._step` (a step row as the run API shows it).
- Produces: `step_summary.origin(type_ref, statuses, *, ended, error_code) -> str`; `step_summary.Summarized`;
  `async step_summary.summarize(s, run_id, nodes, *, ended, error_code) -> list[Summarized]`; `async
  step_summary.instances(s, run_id, step_id, *, within, offset, limit) -> tuple[int, list[RunStep]]`; `GET
  …/draft/simulations/{id}/steps` and `…/steps/{step_id}/instances` (`run.view`).

Each instance counts by its final attempt (the latest, retries included), read with `postgresql.distinct_on` (SQLAlchemy
2.1 deprecates `.distinct(expr)`; checked in the installed package). Ports come from each final attempt's
`effect_preview`. The steps come in run order: by when each first began or ended, then the graph's order. Origins and
paging follow rulings 9 and 10.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_openapi.py b/backend/tests/apps/api/test_openapi.py
index 16eeb6de..09676c11 100644
--- a/backend/tests/apps/api/test_openapi.py
+++ b/backend/tests/apps/api/test_openapi.py
@@ -196,6 +196,8 @@ SLICE_4D1 = [  # B8 (the simulation design §6.3, §6.6)
     ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/snapshots/{snapshot_id}"),
     ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations"),
     ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}"),
+    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps"),
+    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps/{step_id}/instances"),
 ]
 
 
diff --git a/backend/tests/apps/api/test_simulation_steps.py b/backend/tests/apps/api/test_simulation_steps.py
new file mode 100644
index 00000000..615d72fa
--- /dev/null
+++ b/backend/tests/apps/api/test_simulation_steps.py
@@ -0,0 +1,162 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A draft simulation's steps (B8; the simulation design §6.6, §7.4), `run.view`: a summary per step of the draft it
+ran (each instance's final attempt counted by status, its ports counted, a single instance's final attempt, the step's
+data origin), in run order; and a step's instances, one per iteration, paged and filtered by iteration, in the
+iterations' own order."""
+
+import uuid
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from tests.apps.api.test_run_requests_api import as_role, keyed_app
+from tests.apps.dispatcher.support import begin, workers
+from tests.apps.test_admission import current
+from tests.apps.test_admission_drafts import STEPS_GRAPH, drafted, simulate
+from tests.support.graphs import G, cel, nid
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
+
+LOOPED = (
+    G().node("l", "flow.loop@1", {"items": list(range(12))}).node("c", "flow.if@1", {"condition": True})
+    .node("x", "testkit.echo@1", {"value": 1}).node("d", "flow.delay@1", {"duration_s": 1})
+    .node("t", "flow.transform@1", {"fields": {"n": cel("1 + 1")}})
+    .edge("l", "c", "body").edge("c", "x", "true").data() | {"settings": {"input_schema": {"type": "object"}}}
+)  # fmt: skip
+
+
+def steps(ctx: Any, wf: uuid.UUID, request_id: uuid.UUID, step: str | None = None) -> str:
+    base = f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/simulations/{request_id}/steps"
+    return base if step is None else f"{base}/{nid(step)}/instances"
+
+
+async def row(owner: Any, ctx: Any, run_id: uuid.UUID, key: str, iteration: str, attempt: int, status: str, *,
+              at: int | None = None, outcome: str | None = None, port: str | None = None) -> None:  # fmt: skip
+    """A step row as the worker's projection leaves it: begun `at` seconds into the run (none for an instance that
+    never began)."""
+    async with owner() as s, s.begin():
+        await s.execute(
+            text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, "
+                 "started_at, ended_at, outcome, effect_preview) values (:t, :r, :s, :i, :a, :k, :st, "
+                 "case when cast(:at as integer) is null then null "
+                 "else now() - interval '1 hour' + make_interval(secs => cast(:at as integer)) end, "
+                 "case when cast(:st as varchar) = 'running' then null else now() end, :o, :e)"),
+            {"t": ctx.tenant_id, "r": run_id, "s": nid(key), "i": iteration, "a": attempt, "k": key, "st": status,
+             "at": at, "o": outcome, "e": None if port is None else f'{{"port": "{port}"}}'},
+        )  # fmt: skip
+
+
+async def ended(owner: Any, run_id: uuid.UUID, status: str = "succeeded", error_code: str | None = None) -> None:
+    async with owner() as s, s.begin():
+        await s.execute(text("update runs set status = :s, ended_at = now(), error_code = :e, error_message = :m "
+                             "where id = :i"),
+                        {"i": run_id, "s": status, "e": error_code, "m": error_code and "m"})  # fmt: skip
+
+
+@pytest.fixture
+async def looped(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings) -> Any:
+    """A simulation of LOOPED, its run row written by dispatch, still running, with no step rows yet."""
+    await current(dispatch_sessionmaker)
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOPED)
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings)).request
+    await workers(owner_sessionmaker)
+    await begin(dispatch_sessionmaker, request, api_settings)
+    return ctx, wf, request.id
+
+
+async def ran_loop(owner: Any, ctx: Any, run_id: uuid.UUID) -> None:
+    """The loop's 12 iterations: `c` took `true` 3 times; `x` failed twice (its first instance once, then succeeded on
+    its retry) and was skipped 9 times; `d` wasn't waited; `t` never ran."""
+    await row(owner, ctx, run_id, "l", "", 1, "succeeded", at=1)
+    for i in range(12):
+        await row(owner, ctx, run_id, "c", f"l:{i}", 1, "succeeded", at=2, port="true" if i < 3 else "false")
+    await row(owner, ctx, run_id, "x", "l:0", 1, "failed", at=3)
+    await row(owner, ctx, run_id, "x", "l:0", 2, "succeeded", at=4, outcome="simulated")
+    for i in (1, 2):
+        await row(owner, ctx, run_id, "x", f"l:{i}", 1, "failed", at=3, outcome="simulated")
+    for i in range(3, 12):
+        await row(owner, ctx, run_id, "x", f"l:{i}", 1, "skipped")
+    await row(owner, ctx, run_id, "d", "", 1, "succeeded", at=5, outcome="simulated")
+    await ended(owner, run_id)
+
+
+async def test_the_summary_counts_each_steps_instances_and_ports_and_says_where_its_data_came_from(
+    keyed_app, looped, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf, run_id = looped
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    before = (await viewer.get(steps(ctx, wf, run_id))).json()
+    assert before["given"] == "input"
+    assert {s["key"]: s["origin"] for s in before["steps"]} == dict.fromkeys("lcxdt", "not_reached_yet")
+    await ran_loop(owner_sessionmaker, ctx, run_id)
+    summary = (await viewer.get(steps(ctx, wf, run_id))).json()
+    shown = [(s["key"], s["origin"], s["instances"], s["statuses"], s["ports"]) for s in summary["steps"]]
+    assert shown == [  # in run order; a step that never ran last
+        ("l", "evaluated", 1, {"succeeded": 1}, {}),
+        ("c", "evaluated", 12, {"succeeded": 12}, {"true": 3, "false": 9}),
+        ("x", "fixture_not_sent", 12, {"succeeded": 1, "failed": 2, "skipped": 9}, {}),
+        ("d", "evaluated_not_waited", 1, {"succeeded": 1}, {}),
+        ("t", "didnt_run", 0, {}, {}),
+    ]
+    final = {s["key"]: s["final"] for s in summary["steps"]}
+    assert final["c"] is None and final["x"] is None and final["t"] is None  # many instances, or none
+    assert (final["d"]["attempt"], final["d"]["status"], final["d"]["outcome"]) == (1, "succeeded", "simulated")
+
+
+async def test_a_step_with_no_row_is_not_recorded_when_the_run_ended_outside_the_workflow(
+    keyed_app, looped, owner_sessionmaker, api_settings
+) -> None:
+    """D-a5: a bug, a termination or a lost history ended it: what it would have recorded is unknown."""
+    ctx, wf, run_id = looped
+    await row(owner_sessionmaker, ctx, run_id, "l", "", 1, "running", at=1)
+    await ended(owner_sessionmaker, run_id, "failed", "internal_error")
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    summary = (await viewer.get(steps(ctx, wf, run_id))).json()
+    assert {s["key"]: s["origin"] for s in summary["steps"]} == {"l": "evaluated"} | dict.fromkeys(
+        "cxdt", "not_recorded"
+    )
+
+
+async def test_a_steps_instances_are_paged_in_iteration_order_each_its_final_attempt(
+    keyed_app, looped, owner_sessionmaker, api_settings
+) -> None:
+    ctx, wf, run_id = looped
+    await ran_loop(owner_sessionmaker, ctx, run_id)
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    first = (await viewer.get(steps(ctx, wf, run_id, "x"), params={"limit": 4})).json()
+    assert first["total"] == 12
+    assert [(i["iteration_key"], i["attempt"], i["status"]) for i in first["items"]] == [
+        ("l:0", 2, "succeeded"), ("l:1", 1, "failed"), ("l:2", 1, "failed"), ("l:3", 1, "skipped"),
+    ]  # fmt: skip
+    last = (await viewer.get(steps(ctx, wf, run_id, "x"), params={"offset": 8, "limit": 4})).json()
+    assert [i["iteration_key"] for i in last["items"]] == ["l:8", "l:9", "l:10", "l:11"]  # by number, not by text
+    one = (await viewer.get(steps(ctx, wf, run_id, "x"), params={"within": "l:1"})).json()
+    assert (one["total"], [i["iteration_key"] for i in one["items"]]) == (1, ["l:1"])  # never l:10 or l:11
+
+
+async def test_a_step_test_shows_its_target_alone_and_its_values_as_seeded(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """§7.3: only the target carries a result; the other steps are outside the test."""
+    await current(dispatch_sessionmaker)
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, STEPS_GRAPH)
+    request = (await simulate(api_sessionmaker, ctx, wf, api_settings, target=nid("b"),
+                              values={"/steps/a/output/value": 5})).request  # fmt: skip
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    summary = (await viewer.get(steps(ctx, wf, request.id))).json()
+    assert summary["given"] == "seeded"
+    assert [(s["key"], s["origin"]) for s in summary["steps"]] == [("b", "not_reached_yet")]
+
+
+async def test_another_workflows_simulation_or_a_step_outside_the_draft_is_not_found(
+    keyed_app, looped, owner_sessionmaker, api_sessionmaker, api_settings
+) -> None:
+    from tests.apps.test_workflow_ops import create
+
+    ctx, wf, run_id = looped
+    other = await create(api_sessionmaker, ctx, LOOPED, name="other")
+    viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
+    for path in (steps(ctx, other, run_id), steps(ctx, wf, run_id, "nowhere"), steps(ctx, other, run_id, "x")):
+        assert (await viewer.get(path)).status_code == 404, path
diff --git a/backend/tests/apps/test_step_summary.py b/backend/tests/apps/test_step_summary.py
new file mode 100644
index 00000000..c0708b6d
--- /dev/null
+++ b/backend/tests/apps/test_step_summary.py
@@ -0,0 +1,36 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A simulated step's data origin (the simulation design §7.4), sent by the server: from what its instances' final
+attempts did and the step's type, or, with none, from where the run is (D-a5)."""
+
+import pytest
+
+from dewpoint.apps.step_summary import origin
+
+ECHO, IF, DELAY, WAIT = "testkit.echo@1", "flow.if@1", "flow.delay@1", "flow.wait_until@1"
+
+
+@pytest.mark.parametrize(
+    ("type_ref", "statuses", "ended", "error_code", "expected"),
+    [
+        (ECHO, {"succeeded": 1}, True, None, "fixture_not_sent"),  # a plugin's fixture answered: nothing was sent
+        (ECHO, {"failed": 2, "skipped": 9}, True, None, "fixture_not_sent"),
+        (ECHO, {"running": 1}, False, None, "fixture_not_sent"),
+        (IF, {"succeeded": 3}, True, None, "evaluated"),
+        (IF, {"failed": 1}, True, None, "evaluated"),
+        (DELAY, {"succeeded": 1}, True, None, "evaluated_not_waited"),  # §4.2: timers aren't waited
+        (WAIT, {"succeeded": 1}, True, None, "evaluated_not_waited"),
+        (ECHO, {"cancelled": 1, "skipped": 2}, True, None, "cancelled"),  # began, and was stopped
+        (ECHO, {"not_started": 1, "skipped": 2}, True, None, "not_started"),
+        (ECHO, {"skipped": 3}, True, None, "skipped"),
+        (ECHO, {}, False, None, "not_reached_yet"),  # only while the run hasn't ended
+        (ECHO, {}, True, None, "didnt_run"),
+        (ECHO, {}, True, "cancelled", "didnt_run"),  # a cancel ends inside the workflow: B4b recorded what it stopped
+        (ECHO, {}, True, "internal_error", "not_recorded"),  # D-a5: it ended outside the workflow
+        (ECHO, {}, True, "terminated", "not_recorded"),
+        (ECHO, {}, True, "history_lost", "not_recorded"),
+    ],
+)
+def test_a_steps_origin_comes_from_its_instances_or_from_where_the_run_is(
+    type_ref: str, statuses: dict[str, int], ended: bool, error_code: str | None, expected: str
+) -> None:
+    assert origin(type_ref, statuses, ended=ended, error_code=error_code) == expected
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 -W error::DeprecationWarning
tests/apps/test_step_summary.py tests/apps/api/test_simulation_steps.py tests/apps/api/test_openapi.py`

Expected: FAIL, 6 failed, 76 passed and 1 error: `tests/apps/test_step_summary.py` can't import
`dewpoint.apps.step_summary` (ModuleNotFoundError, at collection); the routes don't exist, so the answers have no
`given`, `steps` or `total` (KeyError), and the schema has neither path. The not-found test passes at once.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 38f2a2fb..37125013 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -667,3 +667,36 @@ class SimulationStateOut(_Answer):
     cancel_requested: bool
     input: dict[str, Any] | None
     seeds: dict[str, Any] | None
+
+
+class StepSummaryOut(_Answer):
+    """A step of the draft a simulation ran (B8; the simulation design §6.6): its instances' final attempts counted by
+    status and by the port they took, a single instance's final attempt, and where its data came from (§7.4)."""
+
+    step_id: str
+    key: str
+    type: str
+    origin: Literal[
+        "evaluated", "evaluated_not_waited", "fixture_not_sent", "skipped", "not_started", "cancelled", "didnt_run",
+        "not_recorded", "not_reached_yet",
+    ]  # fmt: skip
+    instances: int
+    statuses: dict[str, int]
+    ports: dict[str, int]
+    final: dict[str, Any] | None  # the run API's step: a single instance's final attempt
+
+
+class SimulationStepsOut(_Answer):
+    """A draft simulation's steps in run order (§6.6), and what the values a person gave were (§7.4): the workflow's
+    input, or a step test's seeds. A step test lists its target alone: the other steps are outside the test."""
+
+    given: Literal["input", "seeded"]
+    steps: list[StepSummaryOut]
+
+
+class StepInstancesOut(_Answer):
+    """A step's instances in a draft simulation, one per iteration, each its final attempt (the run API's step), in
+    iteration order (§6.6): a page of them, and their total."""
+
+    total: int
+    items: list[dict[str, Any]]
diff --git a/backend/src/dewpoint/apps/api/routes/simulations.py b/backend/src/dewpoint/apps/api/routes/simulations.py
index 5a715fef..def22295 100644
--- a/backend/src/dewpoint/apps/api/routes/simulations.py
+++ b/backend/src/dewpoint/apps/api/routes/simulations.py
@@ -12,8 +12,14 @@ from pydantic import BaseModel, ConfigDict, Field, model_validator
 from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from dewpoint.apps import admission
-from dewpoint.apps.api.responses import DraftSnapshotOut, SimulationOut, SimulationStateOut
+from dewpoint.apps import admission, step_summary
+from dewpoint.apps.api.responses import (
+    DraftSnapshotOut,
+    SimulationOut,
+    SimulationStateOut,
+    SimulationStepsOut,
+    StepInstancesOut,
+)
 from dewpoint.apps.api.routes.run_requests import (
     INVALID,
     UNAVAILABLE,
@@ -23,6 +29,7 @@ from dewpoint.apps.api.routes.run_requests import (
     not_past_cutoff,
     request_body,
 )
+from dewpoint.apps.api.routes.runs import _step
 from dewpoint.apps.api.routes.workflows import _revision
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.claims import service as claims
@@ -237,3 +244,58 @@ def _redacted(value: Any) -> Any:
     if isinstance(value, list):
         return [_redacted(v) for v in value]
     return value
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps",
+            response_model=SimulationStepsOut)  # fmt: skip
+async def simulation_steps(
+    workflow_id: uuid.UUID,
+    request_id: uuid.UUID,
+    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """A draft simulation's steps in run order, summarized (§6.6): the tags the editor shows come from here, never
+    from a partial page of instances."""
+    r = await simulation_of(db, ctx, workflow_id, request_id)
+    run = await db.get(Run, r.id)
+    summarized = await step_summary.summarize(
+        db, None if run is None else run.id, await _steps_of(db, r),
+        ended=r.ended_at is not None if run is None else run.status != "running",
+        error_code=None if run is None else run.error_code,
+    )  # fmt: skip
+    return {
+        "given": "input" if r.target_step_id is None else "seeded",
+        "steps": [
+            {"step_id": str(x.step_id), "key": x.key, "type": x.type, "origin": x.origin, "instances": x.instances,
+             "statuses": x.statuses, "ports": x.ports, "final": None if x.final is None else _step(x.final)}
+            for x in summarized
+        ],
+    }  # fmt: skip
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps/{step_id}/instances",
+            response_model=StepInstancesOut)  # fmt: skip
+async def step_instances(
+    workflow_id: uuid.UUID,
+    request_id: uuid.UUID,
+    step_id: uuid.UUID,
+    within: str | None = None,
+    offset: int = Query(0, ge=0),
+    limit: int = Query(20, ge=1, le=100),
+    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """A step's instances in a draft simulation, one per iteration (its final attempt), in iteration order, paged
+    from `offset`; with `within`, only that iteration's (itself and every iteration nested in it)."""
+    r = await simulation_of(db, ctx, workflow_id, request_id)
+    if str(step_id) not in {n["id"] for n in await _steps_of(db, r)}:
+        raise HTTPException(404, detail={"error": "not_found"})
+    total, rows = await step_summary.instances(db, r.id, step_id, within=within, offset=offset, limit=limit)
+    return {"total": total, "items": [_step(x) for x in rows]}
+
+
+async def _steps_of(db: AsyncSession, r: RunRequest) -> list[dict[str, Any]]:
+    """The steps a simulation ran: its snapshot's, or a step test's target alone."""
+    snapshot = await db.get(DraftSnapshot, r.draft_snapshot_id)
+    nodes: list[dict[str, Any]] = [] if snapshot is None else snapshot.graph["nodes"]
+    return [n for n in nodes if r.target_step_id is None or n["id"] == str(r.target_step_id)]
diff --git a/backend/src/dewpoint/apps/step_summary.py b/backend/src/dewpoint/apps/step_summary.py
new file mode 100644
index 00000000..814f573c
--- /dev/null
+++ b/backend/src/dewpoint/apps/step_summary.py
@@ -0,0 +1,132 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A draft simulation's steps, summarized on the server (B8; the simulation design §6.6, §7.4): per step of the graph it
+ran, its instances' final attempts counted by status and by the port they took, a single instance's final attempt, and
+where its data came from; and a step's instances, one per iteration, paged in their iterations' own order. The general
+run detail stays unpaged until 4e (§9)."""
+
+import uuid
+from collections.abc import Mapping, Sequence
+from dataclasses import dataclass, field
+from datetime import datetime
+from typing import Any
+
+from sqlalchemy import ColumnExpressionArgument, Integer, Select, cast, func, or_, select
+from sqlalchemy.dialects.postgresql import ARRAY, distinct_on
+from sqlalchemy.ext.asyncio import AsyncSession
+from sqlalchemy.orm import aliased
+from sqlalchemy.sql.elements import ColumnElement
+
+from dewpoint.core.models.runs import RunStep
+from dewpoint.core.runs.service import HISTORY_LOST
+from dewpoint.engine.registry.control import CONTROL_TYPES, DELAY, WAIT_UNTIL
+from dewpoint.engine.runtime.execution import INTERNAL_ERROR, TERMINATED
+
+# D-a5: a run that ended outside the workflow (a bug, a termination, a lost history) never recorded what it would have
+NOT_RECORDED = frozenset({INTERNAL_ERROR, TERMINATED, HISTORY_LOST})
+
+
+def origin(type_ref: str, statuses: Mapping[str, int], *, ended: bool, error_code: str | None) -> str:
+    """Where a step's data came from (§7.4), from its instances' final attempts: one that began and wasn't stopped
+    says what made it (a timer that wasn't waited, an evaluation, or a plugin's fixture: nothing was sent); else the
+    instances say why none did. With none, where the run is: not reached yet while it runs; after its end, not
+    recorded in D-a5's cases, else it didn't run."""
+    if any(statuses.get(status) for status in ("succeeded", "failed", "running")):
+        if type_ref in (DELAY, WAIT_UNTIL):
+            return "evaluated_not_waited"
+        return "evaluated" if type_ref in CONTROL_TYPES else "fixture_not_sent"
+    for status in ("cancelled", "not_started", "skipped"):
+        if statuses.get(status):
+            return status
+    if not ended:
+        return "not_reached_yet"
+    return "not_recorded" if error_code in NOT_RECORDED else "didnt_run"
+
+
+@dataclass
+class Summarized:
+    """A step of the graph a simulation ran, as §6.6 summarizes it."""
+
+    step_id: uuid.UUID
+    key: str
+    type: str
+    origin: str
+    statuses: dict[str, int] = field(default_factory=dict)  # its instances, by their final attempt's status
+    ports: dict[str, int] = field(default_factory=dict)  # and by the port it took (an `if`'s, a `switch`'s)
+    final: RunStep | None = None  # a single instance's final attempt
+    first_at: datetime | None = None  # when it first began, or ended without beginning: its place in run order
+
+    @property
+    def instances(self) -> int:
+        return sum(self.statuses.values())
+
+
+def _finals(run_id: uuid.UUID) -> Select[Any]:
+    """Each instance's final attempt: the latest, retries included."""
+    return (
+        select(RunStep)
+        .where(RunStep.run_id == run_id)
+        .ext(distinct_on(RunStep.step_id, RunStep.iteration_key))
+        .order_by(RunStep.step_id, RunStep.iteration_key, RunStep.attempt.desc())
+    )
+
+
+async def summarize(
+    s: AsyncSession, run_id: uuid.UUID | None, nodes: Sequence[Mapping[str, Any]], *, ended: bool,
+    error_code: str | None,
+) -> list[Summarized]:  # fmt: skip
+    """The steps `nodes` (the snapshot's, or a step test's target) of the run `run_id` (None: not written yet), in run
+    order: the steps that began or ended by when they first did, then the others in the graph's order."""
+    found = {uuid.UUID(n["id"]): Summarized(uuid.UUID(n["id"]), n["key"], n["type"], "") for n in nodes}
+    if run_id is not None:
+        final = _finals(run_id).subquery()
+        port = final.c.effect_preview["port"].astext
+        counts = await s.execute(
+            select(final.c.step_id, final.c.status, port, func.count()).group_by(final.c.step_id, final.c.status, port)
+        )
+        for step_id, status, taken, n in counts:
+            if (step := found.get(step_id)) is not None:
+                step.statuses[status] = step.statuses.get(status, 0) + n
+                if taken is not None:
+                    step.ports[taken] = step.ports.get(taken, 0) + n
+        firsts = await s.execute(
+            select(RunStep.step_id, func.min(func.coalesce(RunStep.started_at, RunStep.ended_at)))
+            .where(RunStep.run_id == run_id)
+            .group_by(RunStep.step_id)
+        )
+        for step_id, first_at in firsts:
+            if (step := found.get(step_id)) is not None:
+                step.first_at = first_at
+        singles = [step.step_id for step in found.values() if step.instances == 1]
+        if singles:
+            rows = await s.execute(_finals(run_id).where(RunStep.step_id.in_(singles)))
+            for row in rows.scalars():
+                found[row.step_id].final = row
+    for step in found.values():
+        step.origin = origin(step.type, step.statuses, ended=ended, error_code=error_code)
+    order = {step_id: n for n, step_id in enumerate(found)}
+    return sorted(found.values(), key=lambda x: (x.first_at is None, x.first_at or datetime.min, order[x.step_id]))
+
+
+def _numbered(key: ColumnExpressionArgument[str]) -> ColumnElement[Any]:
+    """An iteration key's indexes as numbers, outermost first: `l:2` before `l:10` (the engine writes `loop:index`,
+    joined by `/`, as `samples.newest` reads them; a step's instances all share its loops)."""
+    return cast(func.string_to_array(func.regexp_replace(key, "[a-z][a-z0-9_]*:", "", "g"), "/"), ARRAY(Integer))
+
+
+async def instances(
+    s: AsyncSession, run_id: uuid.UUID, step_id: uuid.UUID, *, within: str | None, offset: int, limit: int
+) -> tuple[int, list[RunStep]]:
+    """A step's instances, each its final attempt, in iteration order: their total and the page from `offset`; within
+    the iteration `within` (itself, and every iteration nested in it) when given."""
+    query = _finals(run_id).where(RunStep.step_id == step_id)
+    if within is not None:
+        query = query.where(
+            or_(RunStep.iteration_key == within, RunStep.iteration_key.startswith(f"{within}/", autoescape=True))
+        )
+    final = query.subquery()
+    total = (await s.execute(select(func.count()).select_from(final))).scalar_one()
+    one = aliased(RunStep, final)
+    page = await s.execute(
+        select(one).order_by(_numbered(one.iteration_key), one.iteration_key).offset(offset).limit(limit)
+    )
+    return total, list(page.scalars())
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 98 passed, with no warning (a deprecation would fail the run).

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/step_summary.py backend/src/dewpoint/apps/api/responses.py \
  backend/src/dewpoint/apps/api/routes/simulations.py backend/tests/apps/test_step_summary.py \
  backend/tests/apps/api/test_simulation_steps.py backend/tests/apps/api/test_openapi.py
git commit -m "feat(api): a simulation's steps summarized with their data origins, and a step's instances (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: The draft's start form and a step's seed contract

**Spec:** §6.6 (the seed contract, the start form), §5.2, §7.1, §7.6 (D-s2); 4d-1a's deferred minor.

**Files:**
- Create: `backend/src/dewpoint/apps/seed_form.py`
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`DraftStartFormOut`, `SeedPrefillOut`, `SeedEntryOut`,
  `SeedContractOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/simulations.py` (`_draft_at`, `draft_start_form`, `seed_contract`)
- Create: `backend/tests/apps/test_seed_form.py`, `backend/tests/apps/api/test_draft_forms.py`
- Modify: `backend/tests/apps/api/test_openapi.py`

**Interfaces:**
- Consumes: Task 3's `simulatable`; `seeds.contract`, `seeds.check`; `samples.newest`; `forms.form_fields`,
  `forms.csv_form`; `routes.workflows._get`.
- Produces: `seed_form.faithful(value) -> bool`; `seed_form.output_of(pointer) -> tuple[str, list[str]] | None`;
  `seed_form.prefill(entry, sample) -> Prefill`; `async seed_form.prefills(s, tenant_id, workflow_id, steps,
  contract, at) -> dict[str, Prefill]`; `GET …/draft/start-form?revision=N` (`workflow.edit`, `run.start`); `GET
  …/draft/steps/{step_id}/seeds?revision=N` (`workflow.edit`, `run.start`, `run.view`).

Both reads answer 409 `draft_conflict` at another revision (ruling 5). The start form is `start-form`'s, from the
draft's parsed settings (ruling 14). The seeds read validates the draft as admission does (ruling 12), then gives each
entry's pointer, types, presence, null and sensitivity, and its prefill (ruling 13).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_draft_forms.py b/backend/tests/apps/api/test_draft_forms.py
new file mode 100644
index 00000000..f02a4286
--- /dev/null
+++ b/backend/tests/apps/api/test_draft_forms.py
@@ -0,0 +1,139 @@
+# SPDX-License-Identifier: Apache-2.0
+"""What the editor asks before simulating (B8; the simulation design §6.6, §7.1, §7.6), at the revision it will send,
+`workflow.edit` and `run.start` as simulating needs: the draft's start form, in `start-form`'s shape (which reads only
+the active version); and a step's seed contract, the draft validated first as admission validates it, each entry
+prefilled from its step's own sample only where the sample is provably faithful and fits (D-s2), else typed, saying
+why."""
+
+import json
+import uuid
+from datetime import timedelta
+from typing import Any
+
+import pytest
+from sqlalchemy import text
+
+from tests.apps.api.test_run_requests_api import as_role, keyed_app
+from tests.apps.test_admission import CSV_GRAPH, TOKEN_GRAPH, current, published
+from tests.apps.test_admission_drafts import LOOP_GRAPH, drafted
+from tests.apps.test_workflow_ops import create, save
+from tests.core.retention.support import run
+from tests.support.graphs import G, cel, nid, ref
+
+pytestmark = pytest.mark.usefixtures("development_deployment")
+__all__ = ["keyed_app"]  # the run start tests' fixture: the API with fixture keys
+
+READS = (
+    G().node("a", "flow.transform@1", {"fields": {"n": cel("1 + 1")}})
+    .node("c", "flow.transform@1", {"fields": {"k": cel("1 + 1")}})
+    .node("d", "flow.transform@1", {"fields": {"k": cel("1 + 1")}})
+    .node("e", "testkit.echo@1", {"value": 1})
+    .node("f", "flow.transform@1", {"fields": {"k": cel("1 + 1")}})
+    .node("g", "flow.transform@1", {"fields": {"k": cel("1 + 1")}})
+    .node("b", "flow.transform@1", {"fields": {
+        "m": ref("steps.a.output.n"), "t": ref("trigger.site"), "u": ref("steps.e.output.value"),
+        "v": ref("steps.c.output.k"), "w": ref("steps.d.output.k"), "x": ref("steps.f.output.k"),
+        "y": ref("steps.g.output.k"),
+    }})
+    .edge("a", "b").edge("c", "b").edge("d", "b").edge("e", "b").edge("f", "b").edge("g", "b").data()
+    | {"settings": {"input_schema": {"type": "object", "properties": {"site": {"type": "string"}},
+                                     "required": ["site"]}}}
+)  # fmt: skip
+
+
+def url(ctx: Any, wf: uuid.UUID, path: str) -> str:
+    return f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft/{path}"
+
+
+async def sampled(owner: Any, ctx: Any, wf: uuid.UUID, outputs: dict[str, Any]) -> None:
+    """An ended run of the active version, each step of `outputs` with that output preview: its B7 sample."""
+    async with owner() as s:
+        version = (await s.execute(text("select active_version_id from workflows where id = :w"), {"w": wf})).scalar()
+    run_id = await run(owner, {"t": ctx.tenant_id, "w": wf, "v": version, "u": ctx.user.id}, timedelta())
+    async with owner() as s, s.begin():
+        for key, output in outputs.items():
+            await s.execute(text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, "
+                                 "status, started_at, ended_at, output_preview) values (:t, :r, :s, '', 1, :k, "
+                                 "'succeeded', now(), now(), cast(:o as jsonb))"),
+                            {"t": ctx.tenant_id, "r": run_id, "s": nid(key), "k": key,
+                             "o": json.dumps(output)})  # fmt: skip
+
+
+async def test_the_drafts_start_form_reads_the_draft_at_its_revision_published_or_not(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings
+) -> None:
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, TOKEN_GRAPH)
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.get(url(ctx, wf, "start-form"), params={"revision": 1})
+    assert answer.status_code == 200, answer.text
+    body = answer.json()
+    assert (body["workflow_id"], body["draft_revision"], body["csv"]) == (str(wf), 1, None)
+    assert sorted((f["name"], f["required"], f["sensitive"]) for f in body["fields"]) == [
+        ("site", False, False), ("token", True, True),
+    ]  # fmt: skip
+    await save(api_sessionmaker, ctx, wf, CSV_GRAPH)  # revision 2: a CSV, so it can't be simulated whole (D-b7)
+    stale = await editor.get(url(ctx, wf, "start-form"), params={"revision": 1})
+    assert (stale.status_code, stale.json()) == (409, {"error": "draft_conflict", "draft_revision": 2})
+    csv = (await editor.get(url(ctx, wf, "start-form"), params={"revision": 2})).json()["csv"]
+    assert csv["columns"] == [{"header": "Site", "name": "site", "type": "string", "required": False,
+                               "sensitive": False}]  # fmt: skip
+
+
+@pytest.mark.parametrize(("role", "status"), [("viewer", 403), ("operator", 403), ("editor", 200), ("admin", 200)])
+async def test_the_drafts_forms_need_what_simulating_needs(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings, role,
+    status,
+) -> None:  # fmt: skip
+    await current(dispatch_sessionmaker)
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, READS)
+    client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
+    for path in ("start-form", f"steps/{nid('b')}/seeds"):
+        assert (await client.get(url(ctx, wf, path), params={"revision": 1})).status_code == status, path
+
+
+async def test_each_seed_is_prefilled_from_its_steps_own_faithful_sample_or_typed_saying_why(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    await current(dispatch_sessionmaker)
+    ctx, wf = await published(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, api_settings, READS)
+    await sampled(owner_sessionmaker, ctx, wf, {
+        "a": {"n": 2}, "c": {"k": "[redacted]"}, "d": {"k": "two"}, "e": {"value": 1}, "g": {"other": 1},
+    })  # fmt: skip
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    answer = await editor.get(url(ctx, wf, f"steps/{nid('b')}/seeds"), params={"revision": 1})
+    assert answer.status_code == 200, answer.text
+    body = answer.json()
+    assert (body["draft_revision"], body["step_id"], body["refused"]) == (1, str(nid("b")), None)
+    entries = {e["pointer"]: e for e in body["entries"]}
+    assert {k: (e["types"], e["required"], e["nullable"]) for k, e in entries.items() if k == "/steps/a/output/n"} == {
+        "/steps/a/output/n": (["integer"], True, False),
+    }  # fmt: skip
+    assert {k: e["prefill"] for k, e in entries.items()} == {
+        "/steps/a/output/n": {"state": "prefilled", "value": 2, "reason": None},
+        "/trigger/site": {"state": "typed", "value": None, "reason": "not_step_output"},
+        "/steps/e/output/value": {"state": "typed", "value": None, "reason": "sensitive"},  # an echo's: tainted
+        "/steps/c/output/k": {"state": "typed", "value": None, "reason": "not_faithful"},
+        "/steps/d/output/k": {"state": "typed", "value": None, "reason": "doesnt_fit"},
+        "/steps/f/output/k": {"state": "typed", "value": None, "reason": "no_sample"},
+        "/steps/g/output/k": {"state": "typed", "value": None, "reason": "not_in_sample"},
+    }
+    assert entries["/steps/e/output/value"]["sensitive"] is True
+
+
+async def test_the_seeds_read_validates_the_draft_first_and_says_why_a_step_cant_run_alone(
+    keyed_app, owner_sessionmaker, api_sessionmaker, admin_sessionmaker, dispatch_sessionmaker, api_settings
+) -> None:
+    """4d-1a's deferred minor: an invalid draft's CEL values have no record, so the contract would miss their reads."""
+    await current(dispatch_sessionmaker)
+    ctx, wf = await drafted(owner_sessionmaker, api_sessionmaker, admin_sessionmaker, LOOP_GRAPH)
+    editor = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "editor")
+    loop = (await editor.get(url(ctx, wf, f"steps/{nid('l')}/seeds"), params={"revision": 1})).json()
+    assert (loop["refused"], loop["entries"]) == ("This step can't be simulated alone: simulate the workflow to see it "
+                                                  "run.", [])  # fmt: skip
+    stale = await editor.get(url(ctx, wf, f"steps/{nid('x')}/seeds"), params={"revision": 2})
+    assert (stale.status_code, stale.json()) == (409, {"error": "draft_conflict", "draft_revision": 1})
+    broken = await create(api_sessionmaker, ctx, G().node("z", "no.such@1").node("y", "flow.transform@1", {
+        "fields": {"n": cel("1 +")}}).data(), name="broken")  # fmt: skip
+    invalid = await editor.get(url(ctx, broken, f"steps/{nid('y')}/seeds"), params={"revision": 1})
+    assert (invalid.status_code, invalid.json()["error"]) == (422, "invalid")
+    assert "node.unknown_type" in [d["code"] for d in invalid.json()["diagnostics"]]
diff --git a/backend/tests/apps/api/test_openapi.py b/backend/tests/apps/api/test_openapi.py
index 09676c11..1b0f0aef 100644
--- a/backend/tests/apps/api/test_openapi.py
+++ b/backend/tests/apps/api/test_openapi.py
@@ -198,6 +198,8 @@ SLICE_4D1 = [  # B8 (the simulation design §6.3, §6.6)
     ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}"),
     ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps"),
     ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/simulations/{request_id}/steps/{step_id}/instances"),
+    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/start-form"),
+    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/steps/{step_id}/seeds"),
 ]
 
 
diff --git a/backend/tests/apps/test_seed_form.py b/backend/tests/apps/test_seed_form.py
new file mode 100644
index 00000000..e08515e7
--- /dev/null
+++ b/backend/tests/apps/test_seed_form.py
@@ -0,0 +1,71 @@
+# SPDX-License-Identifier: Apache-2.0
+"""D-s2's rules (the simulation design §7.6): a seed is prefilled only from its step's own output, and only from a
+sample that is provably what the step output: nothing redacted, cut or claimed, nothing storage couldn't hold."""
+
+import pytest
+
+from dewpoint.apps.seed_form import _ABSENT, _at, faithful, output_of
+
+
+@pytest.mark.parametrize(
+    "value",
+    [2, None, "ok", {"a": [1, "two", {"b": None}]}, [], {}, "nano", "information"],
+)
+def test_a_value_stored_as_it_was_output_is_faithful(value: object) -> None:
+    assert faithful(value)
+
+
+@pytest.mark.parametrize(
+    "value",
+    [
+        "[redacted]",
+        "[truncated]",
+        {"a": ["[redacted]"]},
+        {"$claim": "6f1c0e5e-1d3a-4c55-9a51-8f7f8d5f2c10"},  # a handle: the value itself was claimed
+        {"a": {"$claim": "6f1c0e5e-1d3a-4c55-9a51-8f7f8d5f2c10", "pointer": "/x"}},
+        {"$claim": "c1", "kind": "string"},  # only Dewpoint writes the key: never a value it can vouch for
+        "caf�",  # storage's stand-in for NUL or a lone surrogate
+        {"k�": 1},
+        "nan",
+        "inf",
+        {"a": ["-inf"]},  # storage's name for a number JSON can't hold
+    ],
+)
+def test_a_marked_cut_or_unstorable_value_is_never_faithful(value: object) -> None:
+    assert not faithful(value)
+
+
+@pytest.mark.parametrize(
+    ("pointer", "expected"),
+    [
+        ("/steps/a/output", ("a", [])),
+        ("/steps/a/output/n", ("a", ["n"])),
+        ("/steps/a/output/x~1y/z~0w", ("a", ["x/y", "z~w"])),
+        ("/steps/a/error/message", None),  # an error path is typed
+        ("/steps/a", None),
+        ("/trigger/site", None),
+        ("/vars/n", None),
+        ("/item", None),
+    ],
+)
+def test_only_a_steps_own_output_is_prefilled(pointer: str, expected: tuple[str, list[str]] | None) -> None:
+    assert output_of(pointer) == expected
+
+
+@pytest.mark.parametrize(
+    ("output", "path", "expected"),
+    [
+        ({"a": {"b": [1, 2]}}, ["a", "b", "1"], 2),
+        ({"a": None}, ["a"], None),
+        ({"a": 1}, ["b"], _ABSENT),
+        ({"a": 1}, ["a", "b"], _ABSENT),  # nothing inside a number
+        ({"a": [1]}, ["a", "3"], _ABSENT),
+        ("[truncated]", ["a"], "[truncated]"),  # a cut preview: the marker, never "not there"
+        ({"a": {"$claim": "6f1c0e5e-1d3a-4c55-9a51-8f7f8d5f2c10"}}, ["a", "b"],
+         {"$claim": "6f1c0e5e-1d3a-4c55-9a51-8f7f8d5f2c10"}),
+    ],
+)  # fmt: skip
+def test_a_samples_value_is_read_down_its_path_never_through_a_marker(
+    output: object, path: list[str], expected: object
+) -> None:
+    assert _at(output, path) == expected or (_at(output, path) is _ABSENT and expected is _ABSENT)
```

- [ ] **Step 2: Run them**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/test_seed_form.py
tests/apps/api/test_draft_forms.py tests/apps/api/test_openapi.py`

Expected: FAIL, 9 failed, 77 passed and 1 error: `tests/apps/test_seed_form.py` can't import `dewpoint.apps.seed_form`
(ModuleNotFoundError, at collection); both reads answer 404 for every role (`assert 404 == 200`, `assert 404 == 403`),
and the schema has neither path.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/api/responses.py b/backend/src/dewpoint/apps/api/responses.py
index 37125013..fcf7b15b 100644
--- a/backend/src/dewpoint/apps/api/responses.py
+++ b/backend/src/dewpoint/apps/api/responses.py
@@ -700,3 +700,42 @@ class StepInstancesOut(_Answer):
 
     total: int
     items: list[dict[str, Any]]
+
+
+class DraftStartFormOut(_Answer):
+    """The draft's input as a form, at its revision (B8; the simulation design §7.1): `start-form`'s fields and CSV
+    declaration, for a draft that may never have been published. A draft declaring a CSV can't be simulated whole."""
+
+    workflow_id: str
+    draft_revision: int
+    fields: list[StartFieldOut]
+    csv: CsvFormOut | None
+
+
+class SeedPrefillOut(_Answer):
+    """A seed's value from its step's own sample (D-s2), or why the person types it."""
+
+    state: Literal["prefilled", "typed"]
+    value: Any  # the sample's, when prefilled (null may be one)
+    reason: Literal["sensitive", "not_step_output", "no_sample", "not_faithful", "not_in_sample", "doesnt_fit"] | None
+
+
+class SeedEntryOut(_Answer):
+    """One value the step reads (§5.2): its pointer, the JSON types it may have (none listed: any value), whether it's
+    required (else it may be absent), whether null is taken, and whether it's sensitive (typed and masked)."""
+
+    pointer: str
+    types: list[str]
+    required: bool
+    nullable: bool
+    sensitive: bool
+    prefill: SeedPrefillOut
+
+
+class SeedContractOut(_Answer):
+    """A step's seed contract at the draft's revision (§5.2, §6.6), or why the step can't run alone."""
+
+    draft_revision: int
+    step_id: str
+    refused: str | None
+    entries: list[SeedEntryOut]
diff --git a/backend/src/dewpoint/apps/api/routes/simulations.py b/backend/src/dewpoint/apps/api/routes/simulations.py
index def22295..a9c2b46a 100644
--- a/backend/src/dewpoint/apps/api/routes/simulations.py
+++ b/backend/src/dewpoint/apps/api/routes/simulations.py
@@ -4,6 +4,7 @@ on a snapshot of the draft at the revision `If-Match` names, under an `Idempoten
 `manual`, and the dispatcher starts it as any run. `{input}` simulates the workflow; `{target}` a step alone with the
 values it reads (S2). It needs `workflow.edit` and `run.start`; cancelling is the run's own route (`run.cancel`)."""
 
+import asyncio
 import uuid
 from typing import Any
 
@@ -12,9 +13,11 @@ from pydantic import BaseModel, ConfigDict, Field, model_validator
 from sqlalchemy import select
 from sqlalchemy.ext.asyncio import AsyncSession
 
-from dewpoint.apps import admission, step_summary
+from dewpoint.apps import admission, seed_form, step_summary, workflow_ops
 from dewpoint.apps.api.responses import (
     DraftSnapshotOut,
+    DraftStartFormOut,
+    SeedContractOut,
     SimulationOut,
     SimulationStateOut,
     SimulationStepsOut,
@@ -30,7 +33,8 @@ from dewpoint.apps.api.routes.run_requests import (
     request_body,
 )
 from dewpoint.apps.api.routes.runs import _step
-from dewpoint.apps.api.routes.workflows import _revision
+from dewpoint.apps.api.routes.workflows import _get, _revision
+from dewpoint.apps.forms import csv_form, form_fields
 from dewpoint.core.authz.permissions import P
 from dewpoint.core.claims import service as claims
 from dewpoint.core.claims.cipher import ClaimCipher
@@ -39,9 +43,11 @@ from dewpoint.core.crypto.keys import KeySource
 from dewpoint.core.http import TenantContext, get_db, get_settings_dep, require
 from dewpoint.core.models.requests import RunRequest
 from dewpoint.core.models.runs import Run
-from dewpoint.core.models.workflows import DraftSnapshot
+from dewpoint.core.models.workflows import DraftSnapshot, Workflow
 from dewpoint.core.retention import cutoff as retention
 from dewpoint.core.workflows.service import DraftConflictError
+from dewpoint.engine.graph import seeds
+from dewpoint.engine.graph.model import GraphFormatError, parse_graph
 from dewpoint.engine.handles import ClaimRef
 from dewpoint.engine.runtime.projection import REDACTED
 
@@ -299,3 +305,70 @@ async def _steps_of(db: AsyncSession, r: RunRequest) -> list[dict[str, Any]]:
     snapshot = await db.get(DraftSnapshot, r.draft_snapshot_id)
     nodes: list[dict[str, Any]] = [] if snapshot is None else snapshot.graph["nodes"]
     return [n for n in nodes if r.target_step_id is None or n["id"] == str(r.target_step_id)]
+
+
+async def _draft_at(db: AsyncSession, ctx: TenantContext, workflow_id: uuid.UUID, revision: int) -> Workflow:
+    """The workflow, its draft at `revision`: else 409 `draft_conflict`, naming the draft's (a form never pairs a new
+    revision with an older read)."""
+    wf = await _get(db, ctx, workflow_id)
+    if wf.draft_revision != revision:
+        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": wf.draft_revision})
+    return wf
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/start-form", response_model=DraftStartFormOut,
+            response_model_exclude_unset=True)  # fmt: skip
+async def draft_start_form(
+    workflow_id: uuid.UUID,
+    revision: int = Query(ge=1),
+    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT, P.RUN_START)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+) -> dict[str, object]:
+    """The draft's input at `revision`, as a form (§7.1): `start-form`'s, which reads only the active version."""
+    wf = await _draft_at(db, ctx, workflow_id, revision)
+    try:
+        graph = parse_graph(wf.draft)
+    except GraphFormatError as e:
+        diagnostics = [d.to_json() for d in e.diagnostics]
+        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics}) from None
+    csv = graph.settings.csv
+    return {
+        "workflow_id": str(wf.id),
+        "draft_revision": wf.draft_revision,
+        "fields": form_fields(graph.settings.input_schema),
+        "csv": csv_form(csv.model_dump(mode="json") if csv is not None else None),
+    }
+
+
+@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/steps/{step_id}/seeds", response_model=SeedContractOut)
+async def seed_contract(
+    workflow_id: uuid.UUID,
+    step_id: uuid.UUID,
+    revision: int = Query(ge=1),
+    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT, P.RUN_START, P.RUN_VIEW)),
+    db: AsyncSession = Depends(get_db, scope="function"),
+    settings: Settings = Depends(get_settings_dep),
+) -> dict[str, object]:
+    """A step's seed contract at `revision` (§5.2, §6.6), the draft validated first as admission validates it (422
+    `invalid`, its blocking problems: an invalid draft's contract would miss reads), each entry prefilled from its
+    step's own sample where D-s2 allows (run data: `run.view`), else typed, saying why."""
+    wf = await _draft_at(db, ctx, workflow_id, revision)
+    checked = await workflow_ops.check_draft(db, ctx.tenant_id, wf.draft, settings)
+    sim = await workflow_ops.simulatable(db, ctx, wf, checked)
+    if sim.new is None or checked.graph is None or checked.context is None:
+        diagnostics = [d.to_json() for d in [*sim.blocking, *sim.warnings]]
+        raise HTTPException(422, detail={"error": "invalid", "diagnostics": diagnostics})
+    contract = await asyncio.to_thread(seeds.contract, checked.graph, checked.context, step_id)
+    steps = {n.key: n.id for n in checked.graph.nodes}
+    filled = await seed_form.prefills(db, ctx.tenant_id, wf.id, steps, contract,
+                                      await retention.cutoff(db, ctx.tenant_id))  # fmt: skip
+    return {
+        "draft_revision": wf.draft_revision,
+        "step_id": str(step_id),
+        "refused": contract.refused,
+        "entries": [
+            {"pointer": e.pointer, "types": list(e.types), "required": e.required, "nullable": e.nullable,
+             "sensitive": e.sensitive, "prefill": filled[e.pointer].to_json()}
+            for e in contract.entries
+        ],
+    }  # fmt: skip
diff --git a/backend/src/dewpoint/apps/seed_form.py b/backend/src/dewpoint/apps/seed_form.py
new file mode 100644
index 00000000..ff5a61dd
--- /dev/null
+++ b/backend/src/dewpoint/apps/seed_form.py
@@ -0,0 +1,111 @@
+# SPDX-License-Identifier: Apache-2.0
+"""A step's seed contract as the Test tab shows it (B8; the simulation design §5.2, §6.6, §7.6): each entry with its
+types, presence, null and sensitivity, prefilled from its step's own sample only where D-s2 allows, else typed, saying
+why. Whether a sample fits is the contract's own check, as admission makes it: the UI ships no schema validator."""
+
+import uuid
+from collections.abc import Mapping, Sequence
+from dataclasses import dataclass
+from typing import Any
+
+from sqlalchemy.ext.asyncio import AsyncSession
+
+from dewpoint.core.retention.cutoff import Cutoff
+from dewpoint.core.runs import samples
+from dewpoint.engine.graph import seeds
+from dewpoint.engine.handles import MARKER
+from dewpoint.engine.runtime.projection import REDACTED, TRUNCATED
+
+NON_FINITE = frozenset({"nan", "inf", "-inf"})  # how storage names a number JSON can't hold (`projection.storable`)
+UNSTORABLE = "�"  # storage's stand-in for NUL and lone surrogates
+_ABSENT = object()
+
+
+@dataclass(frozen=True)
+class Prefill:
+    """A seed's value from its step's sample, or why it's typed: `sensitive`, `not_step_output` (the trigger,
+    variables, a loop's frame, an error path), `no_sample`, `not_faithful`, `not_in_sample`, `doesnt_fit`."""
+
+    value: Any = None
+    reason: str | None = None
+
+    def to_json(self) -> dict[str, Any]:
+        return {"state": "typed" if self.reason else "prefilled", "value": self.value, "reason": self.reason}
+
+
+def faithful(value: Any) -> bool:
+    """Whether a stored preview is, provably, what the step output (D-s2): no redaction, truncation or handle marker,
+    no U+FFFD, no non-finite number's name, anywhere in it."""
+    if isinstance(value, str):
+        return value not in (REDACTED, TRUNCATED) and value not in NON_FINITE and UNSTORABLE not in value
+    if isinstance(value, dict):
+        return MARKER not in value and all(UNSTORABLE not in k and faithful(v) for k, v in value.items())
+    if isinstance(value, list):
+        return all(faithful(v) for v in value)
+    return True
+
+
+def output_of(pointer: str) -> tuple[str, list[str]] | None:
+    """The step a `/steps/<key>/output…` pointer reads, and the path inside its output; None for any other pointer."""
+    segments = [s.replace("~1", "/").replace("~0", "~") for s in pointer.split("/")[1:]]
+    if len(segments) >= 3 and segments[0] == "steps" and segments[2] == "output":
+        return segments[1], segments[3:]
+    return None
+
+
+def _at(value: Any, path: Sequence[str]) -> Any:
+    """What `path` addresses in `value`, `_ABSENT` when nothing; a marker on the way is returned as it is."""
+    for segment in path:
+        if isinstance(value, dict) and MARKER not in value:
+            if segment not in value:
+                return _ABSENT
+            value = value[segment]
+        elif isinstance(value, list):
+            if not (segment.isdigit() and int(segment) < len(value)):
+                return _ABSENT
+            value = value[int(segment)]
+        elif faithful(value):  # a value with nothing inside it
+            return _ABSENT
+        else:
+            return value  # a marker or a handle where a container was: never followed
+    return value
+
+
+def prefill(entry: seeds.SeedEntry, sample: samples.Sample | None) -> Prefill:
+    """D-s2, for one entry: from its own step's sample, only when the value there is faithful and fits the entry."""
+    if entry.sensitive:
+        return Prefill(reason="sensitive")
+    if output_of(entry.pointer) is None:
+        return Prefill(reason="not_step_output")
+    if sample is None:
+        return Prefill(reason="no_sample")
+    _, path = output_of(entry.pointer) or ("", [])
+    value = _at(sample.output, path)
+    if value is _ABSENT:
+        return Prefill(reason="not_in_sample")
+    if not faithful(value):
+        return Prefill(reason="not_faithful")
+    if seeds.check(seeds.SeedContract(entries=(entry,)), {entry.pointer: value}, ()):
+        return Prefill(reason="doesnt_fit")
+    return Prefill(value)
+
+
+async def prefills(
+    s: AsyncSession, tenant_id: uuid.UUID, workflow_id: uuid.UUID, steps: Mapping[str, uuid.UUID],
+    contract: seeds.SeedContract, at: Cutoff,
+) -> dict[str, Prefill]:  # fmt: skip
+    """Each entry's prefill, by pointer: `steps` names the draft's steps by key; each step's newest B7 sample (its
+    first iteration's, in a loop) is read once."""
+    found: dict[str, samples.Sample | None] = {}
+    filled: dict[str, Prefill] = {}
+    for entry in contract.entries:
+        read = output_of(entry.pointer)
+        key = read[0] if read is not None and not entry.sensitive else None
+        if key is not None and key not in found:
+            step_id = steps.get(key)
+            search = None if step_id is None else await samples.newest(
+                s, tenant_id, workflow_id, step_id, iteration_key=None, at=at
+            )  # fmt: skip
+            found[key] = None if search is None else search.sample
+        filled[entry.pointer] = prefill(entry, found.get(key) if key is not None else None)
+    return filled
```

- [ ] **Step 4: Run them again**

Run: the command of Step 2. Expected: PASS, 120 passed.

- [ ] **Step 5: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/seed_form.py backend/src/dewpoint/apps/api/responses.py \
  backend/src/dewpoint/apps/api/routes/simulations.py backend/tests/apps/test_seed_form.py \
  backend/tests/apps/api/test_draft_forms.py backend/tests/apps/api/test_openapi.py
git commit -m "feat(api): the draft's start form, and a step's seed contract with its prefills (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: The role matrix, the docs, the API's schema and the client's types

**Spec:** §8 (the role × endpoint matrix); 4d-1a's deferred minor (the operations doc's codes).

**Files:**
- Modify: `backend/tests/apps/api/test_simulation_steps.py` (the matrix)
- Modify: `docs/operations/runs.md`, `docs/operations/retention.md`
- Modify (regenerated): `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: every route of Tasks 6 and 10–13.
- Produces: nothing new.

- [ ] **Step 1: The role matrix**

Apply:

```diff
diff --git a/backend/tests/apps/api/test_simulation_steps.py b/backend/tests/apps/api/test_simulation_steps.py
index 615d72fa..6abae8b7 100644
--- a/backend/tests/apps/api/test_simulation_steps.py
+++ b/backend/tests/apps/api/test_simulation_steps.py
@@ -160,3 +160,23 @@ async def test_another_workflows_simulation_or_a_step_outside_the_draft_is_not_f
     viewer = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, "viewer")
     for path in (steps(ctx, other, run_id), steps(ctx, wf, run_id, "nowhere"), steps(ctx, other, run_id, "x")):
         assert (await viewer.get(path)).status_code == 404, path
+
+
+async def test_every_role_reads_a_simulation_and_another_tenants_member_never_does(
+    keyed_app, looped, owner_sessionmaker, api_settings
+) -> None:
+    """D-b3: a draft run is run data, `run.view` (every role); its snapshot, `workflow.view`."""
+    from tests.apps.api.helpers import session_client
+
+    ctx, wf, run_id = looped
+    await ran_loop(owner_sessionmaker, ctx, run_id)
+    async with owner_sessionmaker() as s:
+        snapshot = (await s.execute(text("select draft_snapshot_id from runs where id = :i"), {"i": run_id})).scalar()
+    base = f"/api/v1/t/{ctx.tenant_id}/workflows/{wf}/draft"
+    reads = [f"{base}/simulations", f"{base}/simulations/{run_id}", steps(ctx, wf, run_id),
+             steps(ctx, wf, run_id, "x"), f"{base}/snapshots/{snapshot}"]  # fmt: skip
+    for role in ("viewer", "operator", "editor", "admin"):
+        client = await as_role(keyed_app, owner_sessionmaker, api_settings, ctx, role)
+        assert [(await client.get(path)).status_code for path in reads] == [200] * 5, role
+    outsider, _ = await session_client(keyed_app, owner_sessionmaker, api_settings, "owner")  # another tenant's owner
+    assert [(await outsider.get(path)).status_code for path in reads] == [404] * 5
```

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/api/test_simulation_steps.py`

Expected: PASS, 6 passed: the matrix test passes at once. It pins what `require()` already enforces on the routes of
Tasks 10–12 (every role reads them; another tenant's member gets 404), so a later change that loosens one fails here.

- [ ] **Step 2: The docs**

Apply:

```diff
diff --git a/docs/operations/retention.md b/docs/operations/retention.md
index 62a9628d..cd4e1d96 100644
--- a/docs/operations/retention.md
+++ b/docs/operations/retention.md
@@ -65,6 +65,8 @@ lifecycle lock, in batches that each commit, so a sweep that stops resumes where
 - a run tree past the cutoff, whole: its runs and their steps, its claims, grants and secret index, and its request
   with its envelope, together;
 - a request that ended without starting, with its inputs;
+- a draft snapshot no request or run names any more: a simulation admitted at the same moment keeps it (both take
+  the snapshot's lock);
 - an event that ended, freeing its endpoint's and its tenant's retained counters (so `retained_full` clears);
 - an upload, an hour after it was made, whether a start consumed it or not;
 - a schedule's tombstone, once the dispatcher's sync has recorded its Temporal schedule gone;
diff --git a/docs/operations/runs.md b/docs/operations/runs.md
index 32b3617e..46342dbd 100644
--- a/docs/operations/runs.md
+++ b/docs/operations/runs.md
@@ -107,6 +107,50 @@ sees `trigger.rows` (one object per row, each column by its name) and `trigger.r
   cell is read in its own activity, but CEL over a cell (a condition on `item.status`) runs in `cel.evaluate`, one
   activity per row ([its cost](#limits-in-this-build)).
 
+## Simulating a draft
+
+`POST /api/v1/t/{tenant}/workflows/{workflow}/draft/simulations`, with `workflow.edit` and `run.start` (editors and
+up), an `If-Match` header holding the draft's revision (without one, 428 `revision_required`; not a number, 400
+`bad_revision`) and an `Idempotency-Key` (428 `idempotency_key_required`), simulates the saved draft as it stands: the
+workflow need not be enabled, nor ever published. The body is `{"input": {...}}` for the whole workflow, or
+`{"target": {"step_id": ..., "values": {pointer: value}, "absent": [pointer]}}` for one step alone, given the values it
+reads (its seeds). It answers 202 with the request, `queued`, in `simulate` mode, frozen on a **draft snapshot**: the
+draft's graph, pins, CEL profile and engine ABI as a version holds them, shared by the simulations of the same draft.
+
+- Admission checks the key first: an exact retry returns its request even after the draft changed. Then the tenant and
+  the production gate, as a start; the revision (409 `draft_conflict`, with the draft's `draft_revision`); the draft,
+  validated: an error diagnostic, `declassify.forbidden` (a draft that declassifies, without `workflow.declassify`),
+  `version.unbounded`, a sub-flow's cycle, depth or engine version and a retired type refuse it (422 `invalid`, with
+  the diagnostics); so do no current build or one of another engine ABI, with the start's codes. Unknown or mis-typed
+  connections, pickers and deprecated step types don't (a simulation opens no connection): they're kept on the request
+  as `admission_checks` and returned. Then the input, against the draft's input schema (a draft whose input takes a
+  CSV can't be simulated whole), or the seeds, against the step's seed contract: every pointer in exactly one of
+  `values` (null only where it's nullable) and `absent` (only where it's optional), else 422 `seed_missing`,
+  `seed_alias`, `seed_unknown` or `seed_invalid`, each problem with its pointer; 422 `target_invalid` for a step that
+  can't run alone. One audit entry, `run.request`, names the snapshot, the revision, its graph hash, the target and
+  the declassified sites.
+- The run takes the tenant's slots and the dispatcher as any run. A step alone runs only that step, from its seeds, and
+  ends with it: no outputs, no failure handler, no edge followed; the other steps have no rows.
+- A draft run is never re-run (409 `draft_run`, its published sub-runs included): simulate the draft again. Draft runs
+  show in `GET …/runs` with their `draft_snapshot_id` and `target_step_id` and no `version_id`; they're never a step's
+  sample, nor counted in a workflow's last runs and 24-hour counts. Cancelling one is the run's own route
+  ([below](#cancelling-and-re-running)).
+
+The editor's reads, `run.view` unless said otherwise:
+
+| Route (under `/api/v1/t/{tenant}/workflows/{workflow}`) | |
+|---|---|
+| `GET /draft/simulations` | the caller's own latest simulations of the workflow, newest first (`limit`, 1 to 50, 20 by default), each with its `draft_revision` |
+| `GET /draft/simulations/{id}` | where it is: its request, its run once there is one, `cancel_requested`, and the `input` or `seeds` it was admitted with, read back from its own request, its claimed values `[redacted]` |
+| `GET /draft/simulations/{id}/steps` | a summary per step, in run order: its instances' final attempts counted by status and by port, a single instance's final attempt, and where its data came from: `evaluated`, `evaluated_not_waited` (a delay or wait-until), `fixture_not_sent` (a plugin's simulation), `skipped`, `not_started`, `cancelled`, `didnt_run`, `not_recorded` (the run ended outside the workflow: `internal_error`, `terminated`, `history_lost`), `not_reached_yet`; `given` says whether a person gave `input` or `seeded` values |
+| `GET /draft/simulations/{id}/steps/{step}/instances` | a step's instances, one per iteration (its final attempt), by iteration number, with their `total` (`offset`; `limit`, 1 to 100; `within`, one iteration and those nested in it) |
+| `GET /draft/snapshots/{snapshot}` | a snapshot's graph (`workflow.view`) |
+| `GET /draft/start-form?revision=N` | the draft's input as a form, as `start-form` describes the active version's (`workflow.edit` and `run.start`) |
+| `GET /draft/steps/{step}/seeds?revision=N` | the step's seed contract: each pointer it reads, its types, whether it's required, nullable and sensitive, and its prefill: its step's newest sample there when that's faithful (nothing redacted, cut or claimed, no U+FFFD, no `nan`, `inf` or `-inf`) and fits, else why it's typed; or why the step can't run alone. The draft is validated first, as admission validates it (422 `invalid`). `workflow.edit`, `run.start` and `run.view` |
+
+The two revision-bound reads answer 409 `draft_conflict` for another revision. Draft snapshots follow the tenant's
+retention ([retention](retention.md)).
+
 ## Schedules
 
 `POST /api/v1/t/{tenant}/workflows/{workflow}/schedules` (`trigger.manage`, editors and up) schedules the workflow's
@@ -381,7 +425,8 @@ refused request, a request past its tenant's retention cutoff, or an input reten
 optional (the old one's by default). The key covers what was asked (the request re-run, the mode, any new input), and is
 checked before anything is rebuilt: an exact retry returns the request it admitted even once retention has removed the
 old input, while the re-run's own request is within its cutoff (410 `request_not_retained` past it), and another re-run
-under the key is 409 `idempotency_conflict`. The audit entry names the request re-run (`rerun_of`).
+under the key is 409 `idempotency_conflict`. The audit entry names the request re-run (`rerun_of`). A draft simulation's
+run, or any run of its tree, is never re-run: 409 `draft_run`.
 
 ## The worker
 
@@ -650,12 +695,16 @@ its error class's either way.
 | `failed` | `terminated` | A sub-run that an operator terminated in Temporal. It couldn't record its end, so its parent did, and the step or loop that started it failed with the same code. |
 | `deadline_exceeded` | `deadline_exceeded` | The run passed `DEWPOINT_MAX_RUN_DURATION_DAYS` (default 30). Running steps were cancelled. |
 | `cancelled` | `cancelled` | The run was cancelled in Temporal. A cancel that arrives while the run's end is being written leaves that end. |
+| `failed` | `seeded_live_refused` | A step alone was started outside a simulation; admission never does. Nothing ran. |
+| `failed` | `target_invalid` | A step alone that can't run alone, or whose values aren't values and absences by pointer; admission refuses both first. Nothing ran. |
 
 Step error codes include the plugin's own codes and `config_invalid`, `output_schema_violation` (an output holding the
 key `$claim` too), `unexpected_error`, `evaluation_error`, `type_mismatch`, `timeout`, `cel_profile_unavailable`,
 `input_too_large`, `history_too_large` (the step's requests to the CEL evaluator would take the run's history past
 32 MiB, under Temporal's limit, which would terminate the run: the rest are never sent), `item_cap_exceeded`,
-`iteration_cap_exceeded`, `outcome_unconfirmed` (the run ended before the step's outcome was recorded: a bug in the
+`iteration_cap_exceeded`, `seed_missing` (a step run alone read a value its seeds don't hold: a guard, which the seed
+contract's check at admission should make unreachable), `outcome_unconfirmed` (the run ended before the step's
+outcome was recorded: a bug in the
 interpreter failed the run, or a batch of its loop, or the run ended from outside; whether the step ran is unconfirmed,
 and it is never a plugin's failure; a projection landing after the run's end, or after its batch's closing while the
 run still runs, writes its steps so too: the run's row keeps each closed batch, `unconfirmed_batches`; each projection
```

- [ ] **Step 3: The API's schema**

From `$WT/backend`: `uv run --frozen dewpoint api openapi > ../frontend/src/api/openapi.json`. Then check that it
only adds, against the committed file:

```bash
uv run --frozen python - <<'PY'
import json, subprocess
committed = subprocess.run(["git", "show", "HEAD:frontend/src/api/openapi.json"], capture_output=True, text=True,
                           check=True).stdout
old, new = json.loads(committed), json.load(open("../frontend/src/api/openapi.json"))
for part, o, n in (("paths", old["paths"], new["paths"]),
                   ("schemas", old["components"]["schemas"], new["components"]["schemas"])):
    print(part, "added", len(set(n) - set(o)), "removed", len(set(o) - set(n)),
          "changed", sorted(k for k in set(o) & set(n) if o[k] != n[k]))
PY
```

Expected: `paths added 7 removed 0 changed []` and `schemas added 13 removed 0 changed []`. Git's line diff of the
file is larger (keys are sorted, so blocks shift): that's expected.

- [ ] **Step 4: The client's types**

From `$WT/frontend`, with the locked packages restored ("How to run things"): `npx --offline pnpm@12.6.0 gen:api`,
then `npx --offline pnpm@12.6.0 check:api` and `npx --offline pnpm@12.6.0 typecheck`. Expected: `schema.d.ts` gains
the new paths and schemas; the check and the type check pass. No screen changes.

- [ ] **Step 5: The API suite, whole**

Run: `uv run --frozen pytest -q -p no:cacheprovider -n 6 tests/apps/api`. Expected: PASS, 551 passed (about 1.5 to 3
minutes).

- [ ] **Step 6: Static checks**

Run: the four of "How to run things". Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add backend/tests/apps/api/test_simulation_steps.py docs/operations/runs.md docs/operations/retention.md \
  frontend/src/api/openapi.json frontend/src/api/schema.d.ts
git commit -m "docs(runs): simulating a draft; the API's schema and the client's types regenerated (B8)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Every check, the ledger, the final checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`

- [ ] **Step 1: The whole backend suite, CodeQL**

Ask the owner before the backend suite (about 23 minutes with 8 workers). Then:
- `uv run --frozen pytest -q -n 8` from `backend/`, the CEL gate tests in a process of their own, as CI runs them;
- ruff (format and check), mypy, the import linter;
- the frontend's `check:api`, `lint`, `typecheck`, `test` and `build`, as CI's frontend job;
- local CodeQL on the branch's head (`scratchpad/codeql/scan.sh <sha>`): no new alert.

Expected: every one passes. A failure is read and fixed test-first, or reported as it is: never a claim that every
check passes when one didn't.

- [ ] **Step 2: The ledger**

Append `### 4d-1b, milestone 3 and the final checkpoint (date)`: the tasks' commits, each check's result as run (the
suite's counts), every mid-slice ruling, anything deferred. Commit (`docs(editor-4): 4d-1b final checkpoint`).

- [ ] **Step 3: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch:
- against this plan (its Review Focus first) and the spec's §6 and §8;
- with the ledger's rulings in view.

Critical and important findings are fixed test-first, once; minor ones are listed. Then **stop**. The summary to the
owner names:
- what's built, and the checks as run;
- the rulings proposed and made, and whether rulings 9 and 13 changed the spec or are still open;
- the deploy order (0072, then this build's API, dispatcher and worker).

It asks for the owner's word on push and a PR; nothing is pushed before it. CI on the PR runs the backend (about 23
minutes), the frontend, CodeQL and the Compose e2e: say so before pushing.
