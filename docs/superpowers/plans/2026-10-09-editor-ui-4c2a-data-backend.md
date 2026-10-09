# Editor UI 4c-2a: Data, the Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1, 2026-10-09.** Nothing is built before the owner approves this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat.

The plan's code was checked before review on a scratch copy of 93a0dd61, never on a branch. Its blocks were applied
as written, its tests run, and the plan corrected where they failed:
- the engine's tests: 1,194 passed;
- the database tests the tasks touch, retention and erasure included: all passed;
- ruff, mypy (strict) and the import contracts: clean.
The whole backend suite wasn't run; Task 5 runs it, with the owner's OK. The executor still runs every step: the
check is evidence, not a substitute.

**Goal:** Give the editor what its data features need from the server: alternatives in output schemas read
conservatively by the validator, every reference a step's field can read (B6), whether each step may not run, and
the newest sample of a step's output with the connection it really used (B7).

**Architecture:**
- **Milestone 1, the engine.** `navigate` follows a schema's alternatives (`anyOf`, `oneOf`) together, and the
  validator keeps "may be missing" apart from "may be null". A new pure module, `engine/graph/scope.py`, runs the
  validator's own analysis and asks its resolver what each reference is at a field: type, missing, null, sensitive,
  and the guards a formula needs to read it safely. The validator also says which steps may not run.
- **Milestone 2, the API.** `POST …/validate` adds `conditional_steps`. A new `GET …/draft/scope` answers the scope
  of one field of the saved draft.
- **Milestone 3, samples.** Migration 0045 adds `run_step_connections`. The worker records, on each attempt, the
  connection it opened, as it was. A new `GET …/draft/samples` answers a step's newest sample.
- No screen changes: 4c-2b builds the UI on these, after this merges. The web client's generated types are
  regenerated, and nothing else in `frontend/` changes.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 (async), Alembic, PostgreSQL 16, Temporal (the worker's
activities only), cel-expr-python 0.1.3 (tests), pytest with pytest-xdist and hypothesis. No new dependency.

**Spec:**
- The outline `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`: §5 rows B6 (draft scope) and B7 (samples),
  D17 (validate answers carry their revision), D18 (the server alone checks and classifies), D20 (redacted values).
- The ledger `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`: ruling 70 (the "conditional" badge waits for
  B6's liveness), ruling 96 (4c in three plans; 4c-2 is data), the migration slot table (0045 is B7's).
- The owner's rulings in chat on 2026-10-09 (recorded in the ledger by Task 1, as written below):
  - D8: the 4c-2 mockups (Design canvas, version 10) are signed off, and the reviewer's ten recommendations are the
    owner's rulings.
  - The validator merges alternatives conservatively, in `navigate`, so the data tree and validation agree. Formulas
    keep engine-core spec §4.3: an element read by index in a formula stays "data, read freely".
  - 4c-2 is two plans in sequence: this one (the backend), reviewed, built and merged first; then 4c-2b (the UI).
- The engine-core spec `docs/superpowers/specs/2026-09-25-engine-core-design.md` §4.3 (references, guards), §5.10
  (diagnostics), §7 (ENGINE_ABI and replay), §8 (`run_steps`, previews). Engine 2b spec §4.1 (taint), §4.3 (declassify),
  §10.1 (retention).
- The code on `origin/main` 93a0dd61, read for this plan (the research is in the session's scratchpad,
  `research-4c2/R1`–`R4`).

## Global Constraints

- **ENGINE_ABI stays 6.** Nothing here may change a run's command sequence:
  - no edit to `engine/taint.py`, `engine/sensitive.py`, `engine/cel/bind.py`, `engine/cel/ast.py`'s `chains()` or
    `Chain`, `engine/cel/record.py`'s projections, `engine/runtime/*`, `StepRow` or `StepResult`;
  - the worker's new write happens inside an activity, never in workflow code;
  - the golden replays under `tests/engine/replay/` pass unchanged.
- **Validator changes apply to new validations only.** Published versions keep what they were validated with; the
  runtime never re-validates (`validate()` runs for draft validate, publish and export only).
- **One migration, 0045**, with `down_revision = "0047"` (the head on main). Deployed migrations are never edited.
  Never use Alembic autogenerate: the migration is written by hand.
- **A new tenant table** has:
  - `tenant_id`, with row-level security enabled and forced, and a `tenant_id = app_tenant_id()` policy;
  - grants for the roles that use it, and no others;
  - the `tenant_insert_fence()` trigger, and an entry in `FENCED_TABLES` (`tests/core/erasure/test_fence.py`);
  - a foreign key `(run_id, tenant_id) → runs(id, tenant_id) ON DELETE CASCADE`, so retention and erasure remove it
    with its run;
  - no foreign key to `connections`, which can be deleted.
- **Every new route** sets `response_model`, with models in `apps/api/responses.py` named uniquely. The OpenAPI
  document is regenerated and committed with the web client's types: `pnpm check:api` and the backend's
  "API schema is current" diff stay clean.
- **Permissions.** Scope needs `workflow.view`; samples need `run.view`; validate keeps `workflow.edit`. Every query
  is the tenant's (RLS, and an explicit `tenant_id` filter).
- **Retention.** A sample is read only from a run whose tree's root is within the tenant's retention
  (`core/retention/cutoff.py`), like every other API read of runs.
- **Secrets.**
  - A sample is the stored preview, already redacted (`[redacted]`) and cut (`[truncated]`). The API never unmasks,
    and never reads a step's real output.
  - A connection's record holds its non-secret config only, never its sealed secret.
  - Logs name an exception's type only. No secret in a URL or a log.
- **No real Mist or SaaS call, ever.** Tests use the testkit and flow plugins, fakes, and Mist's manifests read
  offline.
- **Verify, don't remember.** Every library API is checked against the installed package before it's relied on
  (SQLAlchemy's `lateral()`, FastAPI's `Query`, hypothesis strategies). Every engine name is checked in the code.
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker (the owner, 2026-10-08). Nothing is
  pushed and no PR is opened without the owner's OK in chat. Ask before any local run expected over 10 minutes.

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the tests named, in
the task that owns it.

- **A schema the merge didn't expect.**
  - The cases:
    - nested alternatives, and more of them than the bound;
    - alternatives holding `null`, a `$ref`, an open object, a closed one, a boolean schema;
    - Mist's recursive `$defs` and its unions of device kinds.
  - `navigate` ends, never raises anything but `PathError`, and stays on the safe side: a value read along the path
    is always one the answer allows, or the answer says it may be missing.
  - Tests:
    - Task 2: `follows nested alternatives up to the bound, then says any value`, `ends on a definition that refers
      to itself`, `reads a device's name as text in every kind of device`, `never promises less than the data holds`
      (a property test).
- **A step whose liveness the analysis can't settle.**
  - The cases: liveness too complex to analyse (`None`); a step in a loop body, inside a branch; a step after an
    error port.
  - Each is said to be conditional; only a step sure to run is not.
  - Tests:
    - Task 3: `counts a step it can't analyse as conditional`, `counts a loop body's steps conditional when the
      loop is`, `says a step after an error port may not run`.
- **A path a person can't write.**
  - The cases: a key with a dash or a space; a CEL word (`in`, `null`) as a key, which a reference can name and a
    formula can't; a path longer than 512 characters.
  - Each shows, disabled where it can't be named, and is never offered as something to insert or to test in a
    formula.
  - Tests:
    - Task 4: `shows a key a reference can't name, disabled`, `offers no formula for a key CEL can't select`,
      `stops at the reference length limit`.
- **A guarded read meeting awkward data at run time.**
  - The cases: a step that didn't run, a missing field, null, an empty list, and any value at all where the schema
    declares nothing (a string where a list might be, a list where an object might be).
  - A formula made of the guards and the read is false, never an error, and publishes without a guard diagnostic.
  - Tests:
    - Task 5: `every guarded read publishes without a guard problem`, `a guarded read is never an error at run time`
      (a property test), `says a formula reads sensitive data exactly when validation does`.
- **A sample that isn't what it seems.**
  - The cases:
    - a run past retention;
    - another tenant's run;
    - a sub-flow's run;
    - a simulated run;
    - a run from before connections were recorded;
    - a connection renamed (no new revision), changed (a new revision) or deleted;
    - a step whose type or config differs in the draft;
    - a loop's iterations `l:2` and `l:10`.
  - Each answers as B7 says: never another tenant's or past-retention data, a stale sample says it's stale, and
    "first" is the lowest index.
  - Tests:
    - Task 10: `never answers from a run past retention`, `never answers another tenant's run`, `answers a
      sub-flow's run of this workflow`, `says a simulated sample used no connection`, `tells the four connection
      states` (unknown for a run before records), `says what each connection is now` (changed, gone, and renamed
      but unchanged), `marks a sample stale when the config differs`, `takes the first iteration by number, not by
      text`, `takes the highest attempt`.

## Rulings this plan proposes

These join the ledger as rulings 114 onward once the owner accepts the plan. Each says why, and what it costs if
it's wrong.

1. **Alternatives are read together, conservatively** (`navigate`, Task 2; engine-core spec §4.3 amended).
   - `anyOf` and `oneOf` are unfolded, nested ones too, up to 8 levels and 64 alternatives; beyond that, the value
     is "any value". The schema around a union applies to each alternative, as `_strip_null` already does for one.
   - Reading a field or an index follows every alternative:
     - the value's type is what any alternative allows there;
     - it may be missing when an alternative may lack it (it doesn't require it, a closed one doesn't declare it, its
       type isn't an object or a list, its list may be shorter, or it's null);
     - an alternative that says nothing about it (open, undeclared) makes it "any value";
     - a field no alternative can hold is `ref.unknown_field`, as for one schema.
   - A union with `null` makes the value nullable whatever its number of alternatives (today only one non-null
     alternative counts). A position that is only `null` stays a plain null value, as today.
   - `declared_optional` and `declared_nullable` read through a union only when every alternative declares the
     field. Otherwise the data is open there, and nothing is reported (spec §4.3: undeclared data needs no guard).
   - `allOf` stays unread, as today.
   - Why: the owner's ruling, and the data tree must type a device's `name` as text, as validation does. The cost:
     an existing draft may meet new diagnostics when it's next validated: a reference now typed that mismatches its
     field (`ref.type_mismatch`), a formula field declared optional in every alternative (`cel.conditional_ref`), or
     `has()` on a list now typed (`cel.has_on_typed_path`). Published versions are untouched.
2. **"May be missing" and "may be null" are told apart.** `Resolved` gains `missing` and `nullable`, filled by
   `navigate` and by the resolver (a step that may not run); the scope adds a variable not yet set. `conditional`
   stays their union, so every existing check is unchanged. Why: a default replaces both, but the tree and the builder say them
   differently ("may be null" for Mist's `total`). The cost: none.
3. **A step is conditional when it may not run**:
   - its liveness in its region isn't "always", or it can't be analysed;
   - or the loop whose body holds it is conditional.
   Validate's answer lists them (`conditional_steps`, node ids, sorted). A version's detail doesn't: the badge is the
   draft's. Why: ruling 70. The cost: none.
4. **The scope of a field** (B6): `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/scope`.
   - It takes `node`, `field` (a JSON pointer in that node's config), and at most one of:
     - nothing: the top of each root (each of `trigger`, `steps.<key>.output|error`, `vars.<name>`, `item`, `index`,
       `loops.<key>.item|index`, `run.id|started_at|now` that the field can read);
     - `under`: the children of one path (at most 500, then `more`); the top answer includes each root's children too;
     - `at`: one path, or the problem that stops the field reading it (the validator's own diagnostic);
     - `find`: fields whose name contains the text, at most 6 levels below each root, 2,000 positions visited and
       50 found.
   - It reads the saved draft, like validate, and answers its `draft_revision`, so an editor drops an old answer
     (D17). It needs `workflow.view`: a viewer's read-only drawer shows a pill's details too.
   - When the saved draft can't be analysed, or doesn't hold the step, it answers `state: "unavailable"` and a
     reason, never an error status.
   - Why: B6; scope is per field, since a filter's predicate and a loop's `collect` see their own `item`. The cost:
     each request runs the validator's analysis once (as validate does).
5. **An entry** says:
   - `path`, `parent`, `name` (`timezone`, `[0]`);
   - `root`, and `step` (the producing step's id);
   - `types` (the JSON types it may have; empty: any value) and `format`;
   - `missing` and `nullable`;
   - `sensitive`: what a reference to it holds (engine 2b spec §4.1);
   - `nameable`: false for a key a reference can't name (a dash, a space), shown disabled;
   - `children`;
   - `formula`: null when CEL can't select one of its fields (`in`, `true`, `false`, `null`); otherwise its `guards`
     and whether a formula reading it reads sensitive data.
   Why: the 4c-2 mockups and their ten rulings. The cost: none.
6. **Guards come from the server, as data** (`present`, `not_null`, `is_map`, `is_list`, `min_size`).
   - For each step of the path:
     - a step that may not run: `has(steps.<key>.output)`;
     - a parent that may be null: `parent != null`;
     - a field read from what isn't surely an object: `type(parent) == map`;
     - an index into what isn't surely a list: `type(parent) == list`, then `size(parent) > i`;
     - a field that may be absent: `has(path)`.
   - Never `has()` on a list always there (`cel.has_on_typed_path`).
   - Tests prove a formula made of the guards and the read publishes with no guard diagnostic, and is never an error
     at run time.
   - "is there" is the guards, and `path != null` when the entry may be null or is untyped (`nullable`, or no
     `types`); "is missing" is its negation. A list always there can't be compared with null in CEL (`list != null`
     doesn't compile), and needs no such test. 4c-2b's builder renders them.
   - Why: the owner's ruling for per-comparison guards with defined "is missing" and "is there"; D18 (the server
     alone checks): the same rules make and check them. The cost: the builder can't guard data the scope doesn't
     list.
7. **A formula's sensitivity is reported per entry**, for the formula the guards make: the read and every guard.
   - A formula reading `X[0].f` reads the list `X` whole: CEL's chains stop at an index.
   - A guard reads its operand whole: `trigger.owner != null` or `type(trigger.who) == map` reads that object, and
     an object open to undeclared fields counts as sensitive (engine 2b spec §4.1). A `has()` guard reads only the
     field it tests.
   - So `formula.sensitive` can differ from `sensitive`. A test holds it equal to what validation finds.
   - Why: a condition on `results[0].name` needs declassifying even though the pill isn't sensitive; the tree says so
     before the person builds it. The cost: none.
8. **Each attempt records the connections it opens** (B7, slot 0045).
   - Table `run_step_connections`, keyed `(run_id, step_id, iteration_key, attempt, connection_id)`.
   - It holds the connection's type, name and revision, and its non-secret config as it was (`context`, at most
     4 KiB as canonical JSON, otherwise `{}`), with the time.
   - The worker writes it when an attempt opens the connection, before the node uses it, inside the activity: no
     ABI change. Opening it twice in one attempt records it once.
   - A write the database doesn't answer fails the attempt as nothing sent (retryable), like the connection's own
     load. Any other failure is a bug, raised.
   - A simulated attempt opens no connection, so records nothing. Neither do flow steps.
   - Why: B7: a connection keeps its id while its config changes. The cost: one insert per opened connection per
     attempt.
9. **Which sample** (B7):
   - Candidates: the newest 200 ended runs of this workflow, of any kind (a run, a sub-flow's run, a failure
     handler's run), newest queued first.
   - Each candidate must be within retention through its root.
   - The answer is the first candidate with a succeeded row for the step. Within that run: the asked iteration, else
     the first by number (`l:2` before `l:10`), and its highest attempt.
   - Migration 0045 adds the index `runs_workflow_recent (workflow_id, queued_at DESC, id DESC)` for it.
   - Why: B7's selection; sub-flows run this workflow's steps too. The cost: a sample older than the newest 200 ended
     runs isn't found.
10. **A sample's answer:**
    - `run_id`, the run's kind and mode, its version id and number;
    - the iteration and attempt, and `captured_at` (the row's end);
    - the node's `type@version` in that version, with `same_type` and `same_config` against the saved draft;
    - `output`: the stored preview, markers as they are;
    - `connections`, with one of four states:
      - `recorded`, with each connection's state: `unchanged`, `changed` (another revision now) or `deleted`;
      - `none`: the step names no connection;
      - `simulated`: none used;
      - `unknown`: the step names one, but no record exists;
    - `stale`: true when the type, the config or a connection differs.
    - A renamed connection is unchanged: a rename doesn't change a revision. The current name shows, or the
      recorded one when the connection is gone.
    - A step the saved draft doesn't hold, or with no sample, answers `sample: null`.
    - It needs `run.view`.
    - Why: B7, D20. The cost: none.
11. **The web client's types are regenerated, and its screens untouched.** `schema.d.ts` gains the new routes and
    `conditional_steps`. A test fixture the type checker names gets `conditional_steps: []`. Why: B1's drift check.
    The cost: none.

## File Structure

New:
- `backend/src/dewpoint/engine/graph/scope.py`: what a field can read (B6), from the validator's analysis.
- `backend/tests/engine/graph/test_scope.py`: entries, children, find, at, availability, names.
- `backend/tests/engine/graph/test_scope_guards.py`: the guards' two guarantees, and formula sensitivity.
- `backend/migrations/versions/0045_run_step_connections.py`: the record table and the runs index.
- `backend/src/dewpoint/core/runs/samples.py`: the sample query and its connections (B7).
- `backend/tests/core/runs/test_run_step_connections.py`: the table's RLS, grants, fence and cascade.
- `backend/tests/core/runs/test_samples.py`: selection, retention, tenants, iterations, staleness.
- `backend/tests/apps/api/test_draft_data.py`: the two routes, their permissions and their answers.

Changed:
- `backend/src/dewpoint/engine/graph/schemas.py`: `Resolved.missing`/`nullable`, `alternatives`, `navigate`,
  `declared_optional`, `declared_nullable`.
- `backend/src/dewpoint/engine/graph/validate.py`: the resolver carries `missing`; `analyze`, `site_of`,
  `conditional_steps`.
- `backend/tests/engine/graph/test_schemas.py`, `test_validate.py`, `test_validate_cel.py`, `test_liveness.py`:
  the merge's and liveness's tests.
- `docs/superpowers/specs/2026-09-25-engine-core-design.md`: §4.3, how alternatives are read.
- `backend/src/dewpoint/apps/workflow_ops.py`: the shared validation context; `draft_scope`.
- `backend/src/dewpoint/apps/api/responses.py`: `ValidationOut.conditional_steps`; scope and sample models.
- `backend/src/dewpoint/apps/api/routes/workflows.py`: the validate answer; the two new routes.
- `backend/tests/apps/api/test_workflows.py`, `test_openapi.py`: permission rows, the 4c routes' named answers.
- `backend/src/dewpoint/core/models/runs.py`: `RunStepConnection`.
- `backend/src/dewpoint/apps/worker/network.py`, `activities.py`: the name loaded, the record written, the
  attempt's iteration and number passed.
- `backend/tests/apps/worker/test_activities_network.py`: the record.
- `backend/tests/core/test_migration_chain.py`, `backend/tests/core/erasure/test_fence.py`: the new head, the fenced
  table.
- `backend/tests/core/retention/support.py`, `backend/tests/core/retention/test_sweep.py`: the seeded run tree holds a
  connection record, so retention's and erasure's tests prove it's swept.
- `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`: regenerated.
- `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`: the owner's 2026-10-09 rulings, this plan's rulings,
  and its mid-slice rulings and status.

## Milestones

1. **The engine** (Tasks 1–5): the ledger, the merge, liveness, the scope, the guards. **Pause:** the owner's review
   of the engine changes, which change what every draft's validation says, before any route is built.
2. **The API** (Tasks 6–7): validate's `conditional_steps`, the scope route, the client's types.
3. **Samples** (Tasks 8–11): the table, the worker's record, the sample route, then every check, the ledger and the
   final checkpoint. **Pause:** a fresh reviewer, the summary; then stop.

## How to run things

Every command runs from the plan's worktree (see "Executing this plan"). `$WT` is that worktree's root.

- Python, from `$WT/backend`: the main checkout's venv, whose `uv.lock` matches this one (`cmp` them first), with
  this worktree's source first on the path:
  ```bash
  export PY="/Users/tmunzer/4_dev/mist_dewpoint/backend/.venv/bin/python"
  PYTHONPATH=src:. $PY -c 'import dewpoint; print(dewpoint.__file__)'   # must print $WT/backend/src/...
  ```
- The database tests start PostgreSQL in Docker (testcontainers) and migrate it with `uv run alembic upgrade head`;
  run them with Docker reachable, and make `uv run` use that venv without syncing:
  ```bash
  UV_NO_SYNC=1 UV_PROJECT_ENVIRONMENT=/Users/tmunzer/4_dev/mist_dewpoint/backend/.venv \
    PYTHONPATH=src:. $PY -m pytest -q -n auto tests/engine/graph
  ```
- One test: `… $PY -m pytest -q tests/engine/graph/test_scope.py::test_name`.
- Lint and types: `ruff format src tests && ruff check src tests` (the formatter rewraps new code; existing files
  are already formatted); `PYTHONPATH=src $PY -m mypy src`;
  `PYTHONPATH=src $PY -m importlinter` (the `lint-imports` entry point: `PYTHONPATH=src $PY -c 'from importlinter.cli
  import lint_imports_command; lint_imports_command()'` if the script isn't on the path).
- The whole backend suite (`-n auto`): about the CI job's 12 minutes, so the owner is asked before it runs. It runs at
  milestone ends only; each task runs its own directories.
- The OpenAPI document, from `$WT/backend`:
  ```bash
  PYTHONPATH=src:. $PY -B -c 'import json; from dewpoint.apps.api.openapi import schema; print(json.dumps(schema(), indent=2, sort_keys=True))' > ../frontend/src/api/openapi.json
  ```
  then, from `$WT/frontend` (after `npx -y pnpm@12.6.0 install --frozen-lockfile`, the locked packages only):
  `npx -y pnpm@12.6.0 gen:api`, `check:api`, `typecheck`, `test`.
- Local CodeQL, at the end: `scratchpad/codeql/scan.sh <sha>` (about 40 s).

## Executing this plan

- Inline in one session, with the owner's reviews at the milestone pauses; test-first, as each task's steps say.
- The branch is settled with the owner at the start (memory: the branch point is the owner's). The default proposed:
  `feat/editor-4c2a` from `origin/main`, in its own worktree, this plan's docs branch merged into it first. A later
  main is merged in, never rebased.
- Where the code base differs from a step (a name, a line), the executor adapts the step test-first and records the
  difference as a mid-slice ruling in the ledger (M58 onward).
- The rulings above join the ledger only when the owner accepts the plan; until then the ledger says they're
  proposed.

---

# Milestone 1 — the engine

### Task 1: The ledger: the owner's rulings, and this plan proposed

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger sections later tasks append to (`### 4c-2a, milestone N`).

- [ ] **Step 1: Append the owner's rulings and the plan's status**

Append exactly:

```markdown
### Owner, 4c-2 mockups and plan shape (2026-10-09, in chat)

Asked with the 4c-2 mockups (the Design canvas "4c-2 Data Mockups", version 10, after a pasted review's six
corrections), the owner:
- signed off D8 for 4c-2: the plan may be written from the mockups;
- adopted the pasted review's ten recommendations as rulings: one text and pill editor as a text field's fixed mode;
  conditional pills stay dashed, with a default; "Add a default" is a visible button; the untyped trigger keeps its
  fallback (type a path), a declared input schema is honoured, and no trigger setup comes before 4c-3; samples show
  only in a pill's details; alternatives are merged conservatively; the builder replaces "Fixed" for conditions; one
  level of groups; per-comparison guards, with "is missing" and "is there" defined; keys a reference can't name are
  shown disabled;
- ruled, when asked again on corrected facts, that the validator merges alternatives (`anyOf`, `oneOf`) only.
  References and templates already treat an index as possibly missing; formulas keep engine-core spec §4.3, an element
  read by index being "data, read freely";
- ruled that 4c-2 is two plans in sequence: 4c-2a, the backend (the merge, B6, liveness, B7 with slot 0045), reviewed,
  built and merged first; then 4c-2b, the UI.

Two findings from the research went to the owner as separate tasks, outside 4c-2: a text-only template or a CEL
string constant at a sensitive position publishes clean where a literal is refused; and a switch case's declassify
entry follows its index, not its case, when cases are moved or removed.

### 4c-2a plan (2026-10-09)

`docs/superpowers/plans/2026-10-09-editor-ui-4c2a-data-backend.md`, revision 1. Its rulings (1–11) are proposed,
and join this ledger as 114 onward only when the owner accepts the plan.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): the owner's 4c-2 rulings, and the 4c-2a plan proposed

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Alternatives, read together

**Files:**
- Modify: `backend/src/dewpoint/engine/graph/schemas.py` (`Resolved`, new `alternatives`, `navigate`,
  `declared_optional`, `declared_nullable`; `_strip_null` stays for `target_schema`'s steps)
- Modify: `backend/src/dewpoint/engine/graph/validate.py` (`_resolve_step`, `_resolve_loop`: carry `missing`)
- Modify: `docs/superpowers/specs/2026-09-25-engine-core-design.md` (§4.3)
- Test: `backend/tests/engine/graph/test_schemas.py`, `backend/tests/engine/graph/test_validate_cel.py`,
  `backend/tests/engine/graph/test_validate.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Resolved(schema, conditional, taint=CLEAN, missing=False, nullable=False)`: `navigate` and the resolver fill
    `missing` (may be absent) and `nullable` (the value may be null); `conditional` stays `missing or nullable` where
    they're filled.
  - `alternatives(root: Mapping[str, Any], schema: Any) -> tuple[list[Mapping[str, Any]], bool] | None`: the
    alternatives at a position and whether it may also be null; None when unknown.
  - `MAX_ALTERNATIVES = 64`, `MAX_UNION_DEPTH = 8`.

- [ ] **Step 1: Write the failing tests for `navigate`**

Append to `backend/tests/engine/graph/test_schemas.py` (add `import json`, `from typing import Any`,
`from hypothesis import given, settings`, `from hypothesis import strategies as st` to its imports, and
`MAX_ALTERNATIVES, MAX_UNION_DEPTH` to the `schemas` import):

```python
# Alternatives, read together (4c-2a ruling 1; engine-core spec §4.3).
DEVICES: dict[str, Any] = {
    "type": "object",
    "properties": {
        "results": {"type": "array", "items": {"$ref": "#/$defs/device"}},
        "total": {"type": ["integer", "null"]},
    },
    "required": ["results", "total"],
    "additionalProperties": False,
    "$defs": {
        "device": {"anyOf": [{"$ref": "#/$defs/ap"}, {"$ref": "#/$defs/switch"}]},
        "ap": {"type": "object", "properties": {"name": {"type": "string"}, "radios": {"type": "array"}}},
        "switch": {"type": "object", "properties": {"name": {"type": "string"}, "ports": {"type": "integer"}}},
    },
}
CLOSED: dict[str, Any] = {
    "anyOf": [
        {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"], "additionalProperties": False},
        {"type": "object", "properties": {"b": {"type": "integer"}}, "required": ["b"], "additionalProperties": False},
    ]
}


def test_reads_a_field_every_alternative_declares_as_its_type() -> None:
    r = navigate(DEVICES, ["results", 0, "name"])
    assert json_types(r.schema) == {"string"}
    assert r.missing and r.conditional and not r.nullable  # the list may be shorter; no kind requires a name


def test_a_field_one_open_alternative_doesnt_declare_is_any_value() -> None:
    r = navigate(DEVICES, ["results", 0, "radios"])  # an AP declares it; a switch is open and says nothing
    assert r.schema is None and r.missing


def test_a_field_a_closed_alternative_lacks_may_be_missing() -> None:
    r = navigate(CLOSED, ["a"])
    assert json_types(r.schema) == {"string"} and r.missing and not r.nullable


def test_a_field_no_alternative_holds_is_an_error() -> None:
    with pytest.raises(PathError, match="no field `c`"):
        navigate(CLOSED, ["c"])


def test_a_field_every_alternative_requires_is_always_there() -> None:
    either = {
        "anyOf": [
            {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
            {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        ]
    }
    r = navigate(either, ["id"])
    assert json_types(r.schema) == {"integer", "string"} and not r.conditional


def test_a_union_with_null_is_nullable_whatever_its_size() -> None:
    either = {"anyOf": [{"type": "string"}, {"type": "integer"}, {"type": "null"}]}
    three = {"type": "object", "properties": {"v": either}, "required": ["v"]}
    r = navigate(three, ["v"])
    assert json_types(r.schema) == {"integer", "string"} and r.nullable and not r.missing and r.conditional
    total = navigate(DEVICES, ["total"])
    assert json_types(total.schema) == {"integer"} and total.nullable and not total.missing


def test_a_value_only_null_stays_a_value() -> None:
    r = navigate({"type": "object", "properties": {"v": {"type": "null"}}, "required": ["v"]}, ["v"])
    assert json_types(r.schema) == {"null"} and not r.conditional  # as before: null is its value


def test_reads_an_index_through_alternative_lists() -> None:
    lists = {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "array", "items": {"type": "integer"}}]}
    r = navigate(lists, [0])
    assert json_types(r.schema) == {"integer", "string"} and r.missing


def test_the_schema_around_a_union_applies_to_each_alternative() -> None:
    around = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "anyOf": [{"required": ["a"]}, {"required": ["a"]}],
    }
    r = navigate(around, ["a"])
    assert json_types(r.schema) == {"string"} and not r.conditional


def test_follows_nested_alternatives_up_to_the_bound_then_says_any_value() -> None:
    def nested(levels: int) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "string"}
        for _ in range(levels):
            schema = {"anyOf": [schema, {"type": "integer"}]}
        return {"type": "object", "properties": {"v": schema}, "required": ["v"]}

    assert json_types(navigate(nested(MAX_UNION_DEPTH), ["v"]).schema) == {"integer", "string"}
    assert navigate(nested(MAX_UNION_DEPTH + 1), ["v"]).schema is None
    wide = {"anyOf": [{"type": "object", "properties": {f"k{i}": {"type": "string"}}}
                      for i in range(MAX_ALTERNATIVES + 1)]}  # fmt: skip
    assert navigate(wide, ["k0"]).schema is None


def test_ends_on_a_definition_that_refers_to_itself() -> None:
    loop = {"$defs": {"node": {"anyOf": [{"$ref": "#/$defs/node"}, {"type": "string"}]}}, "$ref": "#/$defs/node"}
    assert navigate(loop, []).schema is None


def test_declared_optional_reads_through_a_union_only_where_every_alternative_declares() -> None:
    both = {"anyOf": [{"type": "object", "properties": {"x": {"type": "string"}}},
                      {"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]}]}  # fmt: skip
    assert declared_optional(both, ["x"]) == (0,)
    one = {"anyOf": [{"type": "object", "properties": {"x": {"type": "string"}}}, {"type": "object"}]}
    assert declared_optional(one, ["x"]) == ()  # open data from here (spec §4.3)


def test_reads_a_device_name_as_text_in_every_kind_of_device() -> None:
    """Mist's device list, as its catalog prints it: every kind declares `name` as text and none requires it."""
    from dewpoint.plugins.mist import PLUGIN
    from dewpoint.sdk import node_manifest

    out = node_manifest(next(n for n in PLUGIN.nodes if n.type == "mist.site_devices.list"))["output_schema"]
    name = navigate(out, ["results", 0, "name"])
    assert json_types(name.schema) == {"string"} and name.missing and not name.nullable
    total = navigate(out, ["total"])
    assert json_types(total.schema) == {"integer"} and total.nullable and not total.missing


# A property: whatever the alternatives, a value read along a path is one the answer allows, or the answer says it
# may be missing (never promising less than the data holds).
_LEAVES = st.sampled_from([{"type": "string"}, {"type": "integer"}, {"type": "null"}, {"type": ["string", "null"]}])


def _object(children: st.SearchStrategy[Any]) -> st.SearchStrategy[dict[str, Any]]:
    return st.dictionaries(st.sampled_from("abc"), children, min_size=1, max_size=3).flatmap(
        lambda props: st.sets(st.sampled_from(sorted(props))).map(
            lambda required: {"type": "object", "properties": props, "required": sorted(required),
                              "additionalProperties": False}  # fmt: skip
        )
    )


SCHEMAS = st.recursive(
    _LEAVES,
    lambda children: st.one_of(
        _object(children),
        children.map(lambda item: {"type": "array", "items": item}),
        st.lists(children, min_size=2, max_size=3).map(lambda options: {"anyOf": options}),
    ),
    max_leaves=8,
)
_ABSENT = object()


def _value(draw: Any, schema: dict[str, Any]) -> Any:
    if "anyOf" in schema:
        return _value(draw, draw(st.sampled_from(schema["anyOf"])))
    kind = schema["type"]
    kind = draw(st.sampled_from(kind)) if isinstance(kind, list) else kind
    if kind == "string":
        return draw(st.text(max_size=2))
    if kind == "integer":
        return draw(st.integers(-3, 3))
    if kind == "null":
        return None
    if kind == "array":
        return [_value(draw, schema["items"]) for _ in range(draw(st.integers(0, 2)))]
    props = schema["properties"].items()
    return {k: _value(draw, sub) for k, sub in props if k in schema["required"] or draw(st.booleans())}


def _paths(schema: dict[str, Any], depth: int) -> list[list[str | int]]:
    if depth == 0:
        return []
    if "anyOf" in schema:
        return [p for option in schema["anyOf"] for p in _paths(option, depth)]
    out: list[list[str | int]] = [["z"]]  # a field nothing declares
    if schema.get("type") == "array":
        out += [[0]] + [[0, *rest] for rest in _paths(schema["items"], depth - 1)]
    for k, sub in schema.get("properties", {}).items():
        out += [[k]] + [[k, *rest] for rest in _paths(sub, depth - 1)]
    return out


def _read(value: Any, path: list[str | int]) -> Any:
    for seg in path:
        if isinstance(seg, int):
            value = value[seg] if isinstance(value, list) and seg < len(value) else _ABSENT
        else:
            value = value.get(seg, _ABSENT) if isinstance(value, dict) else _ABSENT
        if value is _ABSENT:
            return _ABSENT
    return value


_JSON = {bool: "boolean", int: "integer", str: "string", list: "array", dict: "object"}


@settings(max_examples=300, deadline=None)
@given(st.data())
def test_never_promises_less_than_the_data_holds(data: st.DataObject) -> None:
    schema = data.draw(SCHEMAS)
    value = _value(data.draw, schema)
    for path in _paths(schema, 3):
        found = _read(value, path)
        try:
            r = navigate(schema, path)
        except PathError:
            assert found is _ABSENT, (json.dumps(schema), path)  # no alternative can hold it, so no value does
            continue
        if found is _ABSENT:
            assert r.missing, (json.dumps(schema), path)
        elif found is None:
            assert r.nullable or r.schema is None or json_types(r.schema) == {"null"}, (json.dumps(schema), path)
        elif r.schema is not None:
            assert _JSON[type(found)] in (json_types(r.schema) or {_JSON[type(found)]}), (json.dumps(schema), path)
```

- [ ] **Step 2: Write the failing validator tests**

Append to `backend/tests/engine/graph/test_validate_cel.py`:

```python
# Alternatives (4c-2a ruling 1): a formula reads a field every alternative declares as typed, and guards it when one
# of them doesn't require it; where one of them doesn't declare it, the data is open (spec §4.3).
UNION_INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "device": {
            "anyOf": [
                {"type": "object", "properties": {"name": {"type": "string"}, "site": {"type": "string"},
                                                  "ports": {"type": "integer"}}, "required": ["name"]},
                {"type": "object", "properties": {"name": {"type": "string"}, "site": {"type": "string"}},
                 "required": ["name"]},
            ]
        }
    },
    "required": ["device"],
}  # fmt: skip


def test_a_field_every_alternative_declares_but_one_doesnt_require_needs_a_guard() -> None:
    assert codes(one("trigger.device.site == 'a'", input_schema=UNION_INPUT)) == ["cel.conditional_ref"]
    assert codes(one("has(trigger.device.site) && trigger.device.site == 'a'", input_schema=UNION_INPUT)) == []
    assert codes(one("trigger.device.name == 'a'", input_schema=UNION_INPUT)) == []  # required in every one
    assert codes(one("trigger.device.ports == 1", input_schema=UNION_INPUT)) == []  # open data: one doesn't declare it
```

The file's helper `one(expr, …, **settings)` writes `{"input_schema": INPUT, **settings}`, so passing
`input_schema=UNION_INPUT` replaces the default input.

Append to `backend/tests/engine/graph/test_validate.py` (it already has `G`, `ref`, the flow plugin's `CAT` and a
`check(g)` helper):

```python
def test_a_reference_through_alternatives_is_typed() -> None:
    """4c-2a ruling 1: a field every alternative declares as text is text, so it can't fill a number."""
    union = {
        "type": "object",
        "properties": {"device": {"anyOf": [
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        ]}},
        "required": ["device"],
    }  # fmt: skip
    g = G().node("wait", "flow.delay@1", {"duration_s": ref("trigger.device.name")})
    g.settings = {"input_schema": union}
    found = [d for d in check(g).diagnostics if d.code == "ref.type_mismatch"]
    assert [d.message for d in found] == ["`trigger.device.name` is string, but this field expects integer."]
```

- [ ] **Step 3: Run them to see them fail**

Run (from `backend/`, see "How to run things"):
`… $PY -m pytest -q tests/engine/graph/test_schemas.py tests/engine/graph/test_validate_cel.py tests/engine/graph/test_validate.py`
Expected: FAIL. `MAX_ALTERNATIVES` doesn't import; once stubbed, `navigate` returns "any value" for every
multi-alternative read, so the device, union, nullable and validator tests fail.

- [ ] **Step 4: Write the merge**

In `backend/src/dewpoint/engine/graph/schemas.py`, add `import json` to the imports, and replace `Resolved` with:

```python
@dataclass(frozen=True)
class Resolved:
    schema: Schema | None  # None: unknown, any value
    conditional: bool  # may be missing or null at run time
    taint: Shape = CLEAN  # which parts are tainted (engine 2b spec §4.1)
    missing: bool = False  # may be absent: `navigate` and the resolver say; elsewhere `conditional` says it all
    nullable: bool = False  # the value itself may be null
```

Add, after `standalone`:

```python
MAX_ALTERNATIVES = 64  # alternatives followed at one position; past it, any value
MAX_UNION_DEPTH = 8  # unions inside unions, unfolded


def alternatives(root: Schema, schema: Any) -> tuple[list[Schema], bool] | None:
    """The schemas a value here may match, with unions (`anyOf`, `oneOf`, nested) unfolded and each dereferenced, and
    whether the value may also be null. The schema around a union applies to each of its alternatives. A position that
    is only null gives no alternative and "may be null": its reader decides (a field read from it is missing; read
    itself, null is its value). None: unknown (a `$ref` that doesn't resolve, an alternative that isn't a schema, an
    empty union, or past the bounds)."""
    out: list[Schema] = []
    nulls = 0
    stack: list[tuple[Any, int]] = [(schema, 0)]
    while stack:
        current, depth = stack.pop()
        s = _deref(root, current)
        if s is None or depth > MAX_UNION_DEPTH:
            return None
        union = next((key for key in ("anyOf", "oneOf") if key in s), None)
        if union is not None:
            options = s[union]
            if not isinstance(options, list) or not options:
                return None
            around = {k: v for k, v in s.items() if k != union}
            for option in reversed(options):  # popped in order
                inner = _deref(root, option)
                if inner is None:
                    return None
                stack.append(({**around, **inner}, depth + 1))
            continue
        kind = s.get("type")
        if kind == "null" or (isinstance(kind, list) and kind and set(kind) == {"null"}):
            nulls += 1
            continue
        if isinstance(kind, list) and "null" in kind:
            nulls += 1
            others = [x for x in kind if x != "null"]
            s = {**s, "type": others[0] if len(others) == 1 else others}
        out.append(s)
        if len(out) > MAX_ALTERNATIVES:
            return None
    return out, nulls > 0
```

Replace `navigate` with:

```python
def _step(root: Schema, schema: Schema, seg: str | int) -> tuple[Any, bool] | PathError | None:
    """One alternative, one segment: the schema there and whether it may be absent; a PathError when this alternative
    can't hold it; None when it says nothing about it (any value)."""
    types = json_types(standalone(root, schema))
    if isinstance(seg, int):
        if types is not None and "array" not in types:
            return PathError(f"[{seg}] indexes a value that isn't a list")
        items = schema.get("items")
        if not isinstance(items, Mapping) or not items:
            return None
        return items, True  # the list may be shorter
    props = schema.get("properties")
    if isinstance(props, Mapping) and seg in props:
        required = schema.get("required")
        return props[seg], not (isinstance(required, list) and seg in required)
    if types is not None and "object" not in types:
        return PathError(f"`{seg}` reads a field of a value that isn't an object")
    extra = schema.get("additionalProperties")
    if isinstance(extra, Mapping) and extra:
        return extra, True
    if extra is False:  # only a closed object rules the field out; otherwise it may exist
        return PathError(f"there is no field `{seg}`")
    return None


def navigate(root: Any, path: Sequence[str | int], start: Any = None) -> Resolved:
    """Follow a reference path through an output schema. Raises PathError for a field no alternative can hold.

    Alternatives are followed together, on the safe side (engine-core spec §4.3; 4c-2a ruling 1): the value may be
    anything one of them allows there; it may be missing when one of them may lack it; it is any value when one of them
    says nothing about it."""
    if not isinstance(root, Mapping):
        return Resolved(None, bool(path), missing=bool(path))
    current: list[Any] = [root if start is None else start]
    missing = False
    for seg in path:
        found: list[Any] = []
        refused: PathError | None = None
        for schema in current:
            unfolded = alternatives(root, schema)
            if unfolded is None:
                return Resolved(None, True, missing=True)
            options, nullable = unfolded
            missing |= nullable  # a null value has no fields and no items
            for option in options or [{"type": "null"}]:  # only null: it refuses the read, as before
                step = _step(root, option, seg)
                if step is None:
                    return Resolved(None, True, missing=True)
                if isinstance(step, PathError):
                    missing, refused = True, refused or step  # when the value is this alternative, it's missing
                    continue
                found.append(step[0])
                missing |= step[1]
        if not found:
            raise refused or PathError(f"there is no field `{seg}`")
        current = found
    return _end(root, current, missing)


def _end(root: Schema, current: list[Any], missing: bool) -> Resolved:
    schemas: list[Schema] = []
    nullable = False
    for schema in current:
        if _deref(root, schema) is None:  # a boolean schema, or one that doesn't resolve: any value, as before
            return Resolved(None, missing, missing=missing)
        unfolded = alternatives(root, schema)
        if unfolded is None:
            return Resolved(None, True, missing=True)
        options, maybe_null = unfolded
        nullable |= maybe_null
        schemas += options
    if not schemas:  # only null: null is its value, as before
        return Resolved(standalone(root, {"type": "null"}), missing, missing=missing)
    unique = list({json.dumps(s, sort_keys=True, default=str): s for s in schemas}.values())
    merged = unique[0] if len(unique) == 1 else {"anyOf": unique}
    return Resolved(standalone(root, merged), missing or nullable, missing=missing, nullable=nullable)
```

Replace `declared_optional` and `declared_nullable` with:

```python
def _declared(root: Any, path: Sequence[str | int], start: Any, nullable: bool) -> tuple[int, ...]:
    """Positions in `path` of fields every alternative declares, where one of them doesn't require it (or where one of
    them says it may be null). It stops where the schema stops describing the data: a field one alternative doesn't
    declare, an unknown schema, a list index. Open data carries no such promise (spec §4.3)."""
    if not isinstance(root, Mapping):
        return ()
    current: list[Any] = [root if start is None else start]
    out: list[int] = []
    for i, seg in enumerate(path):
        if isinstance(seg, int):
            break
        options: list[Schema] = []
        for schema in current:
            unfolded = alternatives(root, schema)
            if unfolded is None:
                return tuple(out)
            options += unfolded[0]
        fields: list[Any] = []
        for option in options:
            props = option.get("properties")
            if not isinstance(props, Mapping) or seg not in props:
                return tuple(out)
            fields.append(props[seg])
        if not fields:
            return tuple(out)
        if nullable:
            if any((found := alternatives(root, f)) is not None and found[1] for f in fields):
                out.append(i)
        elif any(not (isinstance(o.get("required"), list) and seg in o["required"]) for o in options):
            out.append(i)
        current = fields
    return tuple(out)


def declared_optional(root: Any, path: Sequence[str | int], start: Any = None) -> tuple[int, ...]:
    """Positions in `path` of fields the schema declares but doesn't require: the value may be absent there."""
    return _declared(root, path, start, nullable=False)


def declared_nullable(root: Any, path: Sequence[str | int], start: Any = None) -> tuple[int, ...]:
    """Positions in `path` of fields the schema declares may be null (a `null` type, or a union with null)."""
    return _declared(root, path, start, nullable=True)
```

Keep `_strip_null`: `target_schema`'s `_steps` still uses it (grep to confirm; delete nothing else).

In `backend/src/dewpoint/engine/graph/validate.py`, make the resolver carry `missing`:
- In `_resolve_loop`, `return Resolved(None, bool(p.rest))` becomes `return Resolved(None, bool(p.rest), missing=bool(p.rest))`.
- In `_resolve_step`, the error section's `return Resolved(r.schema, r.conditional or not available)` and the output's
  last line both become, wrapped to the line limit:
  ```python
  return dataclasses.replace(r, conditional=r.conditional or not available, missing=r.missing or not available)
  ```
  and `return Resolved(None, not available)` becomes `return Resolved(None, not available, missing=not available)`.

- [ ] **Step 5: Amend the spec**

In `docs/superpowers/specs/2026-09-25-engine-core-design.md` §4.3, insert before the bullet `- In CEL:` (line 335 at
93a0dd61):

```markdown
  - Alternatives (`anyOf`, `oneOf`, nested ones too) are read together, on the safe side (sub-project 4, 4c-2a
    ruling 1). A field or an index read through them may be any type one alternative allows there. It may be missing
    when one alternative may lack it (doesn't require it, is closed without it, isn't an object or a list there, its
    list may be shorter, or is null). It is any value when one alternative says nothing about it. A field no
    alternative can hold is `ref.unknown_field`. A union with `null` makes the value nullable. CEL's guards follow
    alternatives only where every one of them declares the field; elsewhere the data is open. `allOf` isn't read.
```

- [ ] **Step 6: Run the tests to see them pass, then the engine's graph tests**

Run: `… $PY -m pytest -q tests/engine/graph/test_schemas.py tests/engine/graph/test_validate_cel.py tests/engine/graph/test_validate.py`
Expected: PASS (the new tests, and the files' existing ones).
Run: `… $PY -m pytest -q -n auto tests/engine`
Expected: PASS. A failure in an existing test is read, not patched: either the merge changed a promise the test
holds (then the executor records why, as a mid-slice ruling, and the owner sees it at the milestone's pause), or
the code is wrong.

- [ ] **Step 7: Lint, types, commit**

Run: `ruff format src tests && ruff check src tests && PYTHONPATH=src $PY -m mypy src`
Expected: no findings (the formatter may rewrap the new code; that's expected).

```bash
git add backend/src/dewpoint/engine/graph/schemas.py backend/src/dewpoint/engine/graph/validate.py \
  backend/tests/engine/graph/test_schemas.py backend/tests/engine/graph/test_validate_cel.py \
  backend/tests/engine/graph/test_validate.py docs/superpowers/specs/2026-09-25-engine-core-design.md
git commit -m "feat(engine): references read a schema's alternatives together, on the safe side (4c-2a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Which steps may not run

**Files:**
- Modify: `backend/src/dewpoint/engine/graph/validate.py` (`conditional_steps`, `ValidationResult.conditional_steps`)
- Test: `backend/tests/engine/graph/test_liveness.py`

**Interfaces:**
- Consumes: `lv.RegionLiveness`, `Structure`.
- Produces:
  - `conditional_steps(s: Structure, live: Mapping[uuid.UUID | None, lv.RegionLiveness]) -> tuple[uuid.UUID, ...]`
    (in topological order);
  - `ValidationResult.conditional_steps: tuple[str, ...] = ()` (node ids, sorted).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/engine/graph/test_liveness.py` (add `from dewpoint.engine.graph.validate import
ValidationContext, conditional_steps, validate` and `import dataclasses` to its imports):

```python
# Which steps may not run (4c-2a ruling 3; ledger ruling 70's badge).
def _conditional(g: G) -> set[str]:
    result = validate(g.build(), ValidationContext(catalog=CAT))
    keys = {n["id"]: n["key"] for n in g.nodes}
    return {keys[n] for n in result.conditional_steps}


def test_says_which_steps_a_branch_may_skip() -> None:
    g = (
        G().node("a", "testkit.echo@1", {"value": 1}).node("c", "flow.if@1", {"condition": True})
        .node("t", "testkit.echo@1", {"value": 1}).node("f", "testkit.echo@1", {"value": 1})
        .node("j", "testkit.echo@1", {"value": 1})
        .edge("a", "c").edge("c", "t", port="true").edge("c", "f", port="false").edge("t", "j").edge("f", "j")
    )  # fmt: skip
    assert _conditional(g) == {"t", "f"}  # the join runs whichever way the branch goes


def test_counts_a_loop_bodys_steps_conditional_when_the_loop_is() -> None:
    g = (
        G().node("c", "flow.if@1", {"condition": True}).node("l", "flow.loop@1", {"items": [1, 2]})
        .node("x", "testkit.echo@1", {"value": 1})
        .edge("c", "l", port="true").edge("l", "x", port="body")
    )  # fmt: skip
    assert _conditional(g) == {"l", "x"}


def test_says_a_step_after_an_error_port_may_not_run() -> None:
    g = (
        G().node("a", "testkit.echo@1", {"value": 1}, on_error="port")
        .node("ok", "testkit.echo@1", {"value": 1}).node("bad", "testkit.echo@1", {"value": 1})
        .edge("a", "ok").edge("a", "bad", port="error")
    )  # fmt: skip
    assert _conditional(g) == {"ok", "bad"}


def test_counts_a_step_it_cant_analyse_as_conditional() -> None:
    g = G().node("a", "testkit.echo@1", {"value": 1}).node("b", "testkit.echo@1", {"value": 1}).edge("a", "b")
    s, _ = analyze_structure(g.build(), CAT)
    assert s is not None
    live = {r: lv.analyze_region(s, r) for r in s.regions}
    assert conditional_steps(s, live) == ()
    root = live[None]
    unknown = dataclasses.replace(root, live={**root.live, nid("b"): None})  # too complex to analyse
    assert conditional_steps(s, {**live, None: unknown}) == (nid("b"),)
```

`G` (`tests/support/graphs.py`) keeps its nodes as dicts (`g.nodes`, with `id` and `key`) and takes `port=` on
`edge` and `on_error=` on `node`.

- [ ] **Step 2: Run them to see them fail**

Run: `… $PY -m pytest -q tests/engine/graph/test_liveness.py`
Expected: FAIL: `conditional_steps` doesn't import.

- [ ] **Step 3: Write it**

In `backend/src/dewpoint/engine/graph/validate.py`, add to `ValidationResult` after `pickers`:

```python
    conditional_steps: tuple[str, ...] = ()  # the steps that may not run (ruling 70's badge), by id, sorted
```

Add after `_descendants`:

```python
def conditional_steps(
    s: Structure, live: Mapping[uuid.UUID | None, lv.RegionLiveness]
) -> tuple[uuid.UUID, ...]:
    """The steps that may not run (4c-2a ruling 3): their liveness in their region isn't "always", or can't be
    analysed; or the loop whose body holds them may not run."""
    memo: dict[uuid.UUID, bool] = {}

    def may_skip(n: uuid.UUID) -> bool:
        if n not in memo:
            region = s.region_of[n]
            cond = live[region].live[n]
            memo[n] = cond is None or frozenset() not in cond or (region is not None and may_skip(region))
        return memo[n]

    return tuple(n for n in s.topo if may_skip(n))
```

In `validate()`, add to the returned `ValidationResult`:

```python
        conditional_steps=tuple(sorted(str(n) for n in conditional_steps(structure, v.live))),
```

- [ ] **Step 4: Run them to see them pass, then the graph tests**

Run: `… $PY -m pytest -q tests/engine/graph/test_liveness.py` then `… $PY -m pytest -q -n auto tests/engine/graph`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/dewpoint/engine/graph/validate.py backend/tests/engine/graph/test_liveness.py
git commit -m "feat(engine): validation says which steps may not run (4c-2a, ledger ruling 70)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: What a field can read

**Files:**
- Modify: `backend/src/dewpoint/engine/graph/validate.py` (`Analysis`, `analyze`, `site_of`; `validate` and `_node`
  use them)
- Create: `backend/src/dewpoint/engine/graph/scope.py`
- Test: `backend/tests/engine/graph/test_scope.py`

**Interfaces:**
- Consumes: `Resolved.missing`/`nullable`, `alternatives` (Task 2).
- Produces:
  - in `validate.py`: `Analysis(settings, pickers, structural, structure, validator)`,
    `analyze(graph: Graph, ctx: ValidationContext) -> Analysis`, `site_of(s: Structure, node: uuid.UUID, field: str)
    -> _Site`;
  - in `scope.py`: `Guard(kind, path, size=None)` with `.cel() -> str`; `FormulaUse(guards, sensitive)`;
    `Entry(path, parent, name, root, step, types, format, missing, nullable, sensitive, nameable, children, formula)`;
    `Scope(entries=(), more=False, problem=None, unavailable=None)`;
    `scope(graph: Graph, ctx: ValidationContext, node: uuid.UUID, field: str, *, under: str | None = None,
    at: str | None = None, find: str | None = None) -> Scope`; `MAX_CHILDREN = 500`, `FIND_DEPTH = 6`,
    `FIND_VISITS = 2000`, `FIND_FOUND = 50`; the reasons `NO_STEP`, `NO_ANALYSIS` and `UNREADABLE` (the last for the
    API, when the draft doesn't parse).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/engine/graph/test_scope.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What a field can read (B6; 4c-2a rulings 4–7): the validator's own answers, per field."""

import uuid
from typing import Any

from dewpoint.engine.graph.scope import FIND_FOUND, Entry, Scope, scope
from dewpoint.engine.graph.validate import ValidationContext
from dewpoint.plugins.flow import PLUGIN as FLOW
from dewpoint.plugins.mist import PLUGIN as MIST
from tests.support.catalog import catalog
from tests.support.graphs import G, cel, nid, ref
from tests.support.plugins.testkit import TESTKIT

CTX = ValidationContext(catalog=catalog(FLOW, TESTKIT, MIST))
SITE_ID = "00000000-0000-4000-8000-000000000001"
INPUT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "site": {"type": "string"},
        "note": {"type": ["string", "null"]},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"mac": {"type": "string"}, "ap-name": {"type": "string"}, "in": {"type": "string"}},
                "required": ["mac"],
            },
        },
        "secret": {"type": "string", "x-sensitive": True},
        # A nullable parent (`!= null` before its fields), and unions whose alternatives aren't all objects or all
        # lists (`type(…) == map`, `type(…) == list` before a field or an index).
        "owner": {"type": ["object", "null"], "properties": {"name": {"type": "string"}}, "required": ["name"]},
        "who": {"anyOf": [{"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                          {"type": "string"}]},
        "labels": {"anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
    },
    "required": ["site", "events", "owner", "who", "labels"],
}


def graph() -> G:
    """`c` reads everything upstream; `maybe` runs on one branch; `f` filters, `l` loops over `x`."""
    g = (
        G().node("get", "testkit.echo@1", {"value": 1})
        .node("devices", "mist.site_devices.list@1", {"site_id": SITE_ID})
        .node("br", "flow.if@1", {"condition": True}).node("maybe", "testkit.echo@1", {"value": 1})
        .node("c", "flow.if@1", {"condition": True})
        .node("f", "flow.filter@1", {"items": ref("trigger.events"), "predicate": cel("true")})
        .node("l", "flow.loop@1", {"items": ref("trigger.events")}).node("x", "testkit.echo@1", {"value": 1})
        .edge("get", "devices").edge("devices", "br").edge("br", "maybe", port="true").edge("maybe", "c")
        .edge("br", "c", port="false").edge("c", "f", port="true").edge("f", "l").edge("l", "x", port="body")
    )  # fmt: skip
    count = {"type": "integer", "default": 0}
    g.settings = {"input_schema": INPUT, "vars_schema": {"type": "object", "properties": {"count": count}}}
    return g


def at(node: str, field: str, **ask: str) -> Scope:
    return scope(graph().build(), CTX, nid(node), field, **ask)


def by_path(s: Scope) -> dict[str, Entry]:
    return {e.path: e for e in s.entries}


def test_lists_what_a_field_can_read() -> None:
    paths = set(by_path(at("c", "/condition")))
    assert {"trigger", "trigger.site", "trigger.events", "trigger.note", "trigger.secret", "vars.count"} <= paths
    assert {"steps.get.output", "steps.get.output.value", "steps.maybe.output", "steps.devices.output",
            "steps.devices.output.results", "steps.devices.output.total"} <= paths  # fmt: skip
    assert {"run.id", "run.started_at", "run.now"} <= paths
    assert not any(p.startswith(("steps.c.", "steps.f.", "steps.x.", "item", "index")) for p in paths)


def test_says_a_step_on_a_branch_may_be_missing() -> None:
    maybe = by_path(at("c", "/condition"))["steps.maybe.output"]
    assert maybe.missing and maybe.step == str(nid("maybe"))
    assert maybe.formula is not None and [g.cel() for g in maybe.formula.guards] == ["has(steps.maybe.output)"]


def test_tells_missing_from_null() -> None:
    entries = by_path(at("c", "/condition"))
    assert entries["trigger.note"].missing and entries["trigger.note"].nullable
    assert not entries["trigger.site"].missing and not entries["trigger.site"].nullable
    total = entries["steps.devices.output.total"]
    assert total.types == ("integer",) and total.nullable and not total.missing


def test_reads_a_device_name_through_the_list() -> None:
    first = by_path(at("c", "/condition", under="steps.devices.output.results[0]"))
    name = first["steps.devices.output.results[0].name"]
    assert name.types == ("string",) and name.missing and not name.sensitive and name.nameable
    assert name.formula is not None and name.formula.sensitive  # a formula reads the list whole, which isn't declared


def test_shows_a_key_a_reference_cant_name_disabled() -> None:
    event = by_path(at("c", "/condition", under="trigger.events[0]"))
    dashed = next(e for e in event.values() if e.name == "ap-name")
    assert not dashed.nameable and dashed.formula is None and not dashed.children
    assert event["trigger.events[0].mac"].nameable


def test_offers_no_formula_for_a_key_cel_cant_select() -> None:
    word = by_path(at("c", "/condition", under="trigger.events[0]"))["trigger.events[0].in"]
    assert word.nameable and word.formula is None  # a reference may name it; CEL can't select `in`


def test_item_is_the_filters_in_its_predicate_and_the_loops_in_its_body() -> None:
    assert {"item", "index"} <= set(by_path(at("f", "/predicate")))
    assert not {"item", "index"} & set(by_path(at("f", "/items")))
    body = set(by_path(at("x", "/value")))
    assert {"item", "index"} <= body and "loops.l.item" not in body  # `item` already is the loop's


def test_at_answers_one_path_or_the_validators_own_problem() -> None:
    mac = at("c", "/condition", at="trigger.events[0].mac")
    assert [e.path for e in mac.entries] == ["trigger.events[0].mac"] and mac.entries[0].missing
    unknown = at("c", "/condition", at="steps.nope.output")
    assert unknown.entries == () and unknown.problem is not None and unknown.problem.code == "ref.unknown_step"
    later = at("c", "/condition", at="steps.x.output")
    assert later.problem is not None and later.problem.code in ("ref.out_of_scope", "ref.not_upstream")


def test_finds_fields_by_name_within_its_bounds() -> None:
    names = at("c", "/condition", find="name")
    assert "steps.devices.output.results[0].name" in by_path(names)
    assert all("name" in e.name.casefold() for e in names.entries)
    many = at("c", "/condition", find="e")
    assert len(many.entries) <= FIND_FOUND


def test_stops_at_the_reference_length_limit() -> None:
    long = "k" * 200
    g = G().node("c", "flow.if@1", {"condition": True})
    deep = {"type": "object", "properties": {long: {"type": "object", "properties": {long: {"type": "object",
            "properties": {long: {"type": "string"}}}}}}}  # fmt: skip
    g.settings = {"input_schema": deep}
    second = scope(g.build(), CTX, nid("c"), "/condition", under=f"trigger.{long}.{long}")
    assert [e.nameable for e in second.entries] == [False]  # trigger + 3 × 201 characters is past 512


def test_says_why_there_is_no_scope() -> None:
    assert scope(graph().build(), CTX, uuid.uuid4(), "/condition").unavailable == (
        "This step isn't in the saved draft yet."
    )
    loop = G().node("a", "testkit.echo@1").node("b", "testkit.echo@1").edge("a", "b").edge("b", "a")
    assert scope(loop.build(), CTX, nid("a"), "/value").unavailable is not None  # a cycle stops the analysis
```

- [ ] **Step 2: Run them to see them fail**

Run: `… $PY -m pytest -q tests/engine/graph/test_scope.py`
Expected: FAIL: `dewpoint.engine.graph.scope` doesn't exist.

- [ ] **Step 3: Share the validator's analysis and its sites**

In `backend/src/dewpoint/engine/graph/validate.py`, add after `class _Site`:

```python
def site_of(s: Structure, node: uuid.UUID, field: str) -> _Site:
    """Where a value at `field` (a JSON pointer) of `node`'s config is evaluated: its scope, and whose `item` it sees.
    A filter's predicate sees the filter's; a loop's `collect` is evaluated as each body ends; anything else sees the
    innermost loop's, if any."""
    first = field.split("/")[1] if field.startswith("/") else ""
    ref = s.specs[node].ref
    if ref == C.LOOP and first == "collect":
        return _Site(node, field, node, at_exit=True, item_node=node)
    region = s.region_of[node]
    return _Site(node, field, region, item_node=node if ref == C.FILTER and first == "predicate" else region)
```

In `_Validator._node`, use it for both sites (the behaviour is unchanged):

```python
            if spec.ref == C.LOOP and pointer[0] == "collect":
                self.deferred.append((site_of(self.s, n.id, where), value))
                continue
            root, inner = self._value_root(n, spec, pointer)
            resolved[pointer] = self._value(site_of(self.s, n.id, where), value, root, inner)
```

(The local `item_node = …` line goes, and so does `region = self.s.region_of[n.id]`, which nothing else in `_node`
reads then: ruff's F841 says so.) Then split `validate` in two. Add before `def validate`:

```python
@dataclass(frozen=True)
class Analysis:
    """The validator's converged analysis (the taint fixpoint's last pass), for the questions validation itself
    doesn't ask: what a field can read (B6, `scope.py`). `validator` is None when the graph's structure stops it."""

    settings: tuple[Diagnostic, ...]
    pickers: tuple[tuple[str, str, str, uuid.UUID, tuple[str, ...]], ...]
    structural: tuple[Diagnostic, ...]
    structure: Structure | None
    validator: _Validator | None


def analyze(graph: Graph, ctx: ValidationContext) -> Analysis:
    settings = _settings(graph)
    if not any((d.field or "").startswith("/settings/input_schema") for d in settings):
        picker_diags, pickers = _pickers(graph, ctx.catalog)
        settings += picker_diags
    else:
        pickers = []
    structure, structural = analyze_structure(graph, ctx.catalog)
    if structure is None:
        return Analysis(tuple(settings), tuple(pickers), tuple(structural), None, None)
    unusable = ("settings.invalid_schema", "settings.unresolvable_ref", "settings.unsupported_keyword")
    settings_ok = not any(d.code in unusable for d in settings)
    facts = NO_FACTS
    while True:  # the taint analysis's fixpoint (§4.1): facts only grow, so this ends
        v = _Validator(graph, structure, ctx, settings_ok, facts)
        v.run()
        learned = TaintFacts(facts.vars | v.assigned, facts.collects | frozenset(v.collected_tainted))
        if learned == facts:
            break
        facts = learned
    return Analysis(tuple(settings), tuple(pickers), tuple(structural), structure, v)
```

and make `validate` read it:

```python
def validate(graph: Graph, ctx: ValidationContext) -> ValidationResult:
    a = analyze(graph, ctx)
    node_refs = tuple(sorted({n.type for n in graph.nodes}))
    if a.structure is None or a.validator is None:
        return ValidationResult(tuple([*a.settings, *a.structural]), node_refs)
    v = a.validator
    declassify, declassified = _declassify(graph, a.structure, v.site_taint)
    return ValidationResult(
        diagnostics=tuple([*a.settings, *a.structural, *v.diags, *declassify]),
        # … every other field exactly as before, reading `a.structure` for `structure`, and:
        pickers=a.pickers if not picker_problems(list(a.settings)) else (),
        conditional_steps=tuple(sorted(str(n) for n in conditional_steps(a.structure, v.live))),
    )
```

(`picker_problems` takes a sequence: check its signature and pass `a.settings` as it accepts.)

Run: `… $PY -m pytest -q -n auto tests/engine/graph`
Expected: PASS: a pure refactor.

- [ ] **Step 4: Write the scope**

Create `backend/src/dewpoint/engine/graph/scope.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What one field of a step can read (sub-project 4, B6; 4c-2a rulings 4–7): every reference available there, as the
validator sees it: its type, whether it may be missing or null, whether it's sensitive, whether a reference can name
it, and the guards a formula needs to read it safely.

It asks the validator's own analysis (`analyze`) and resolver, never a copy of their rules, so the editor's data tree
and validation can't disagree. It writes nothing, and its questions leave no diagnostics behind."""

import re
import uuid
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Literal

from dewpoint.engine.graph.diagnostics import Diagnostic
from dewpoint.engine.graph.model import Graph
from dewpoint.engine.graph.schemas import PathError, Resolved, alternatives, json_types, navigate
from dewpoint.engine.graph.validate import Analysis, ValidationContext, analyze, site_of
from dewpoint.engine.graph.values import CEL_KEYWORDS, MAX_REF_LENGTH, RefPath, RefSyntaxError, parse_ref
from dewpoint.engine.registry import control as C

Root = Literal["trigger", "steps", "vars", "item", "index", "loops", "run"]
GuardKind = Literal["present", "not_null", "is_map", "is_list", "min_size"]
JSON_TYPES = frozenset({"string", "integer", "number", "boolean", "array", "object", "null"})
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")  # what a reference names (the ref grammar's field)
MAX_CHILDREN = 500
FIND_DEPTH, FIND_VISITS, FIND_FOUND = 6, 2000, 50
NO_STEP = "This step isn't in the saved draft yet."
NO_ANALYSIS = "The saved draft has problems that stop its steps being read. Fix them first."
UNREADABLE = "The saved draft isn't a workflow yet: fix its format first."  # parse_graph refused it (the API says)


@dataclass(frozen=True)
class Guard:
    """A test a formula makes before it reads a path (4c-2a ruling 6). For `min_size`, `size` is the index the read
    takes: the list must have more items than that."""

    kind: GuardKind
    path: str
    size: int | None = None

    def cel(self) -> str:
        if self.kind == "present":
            return f"has({self.path})"
        if self.kind == "not_null":
            return f"{self.path} != null"
        if self.kind == "is_map":
            return f"type({self.path}) == map"
        if self.kind == "is_list":
            return f"type({self.path}) == list"
        return f"size({self.path}) > {self.size}"


@dataclass(frozen=True)
class FormulaUse:
    guards: tuple[Guard, ...]
    sensitive: bool  # a formula reading it reads sensitive data: through an index, the whole list (ruling 7)


@dataclass(frozen=True)
class Entry:
    path: str
    parent: str | None
    name: str
    root: Root
    step: str | None  # the step it comes from: a step's output or error, a loop's item
    types: tuple[str, ...]  # the JSON types it may have, sorted; () when any value
    format: str | None
    missing: bool
    nullable: bool
    sensitive: bool  # a reference to it holds sensitive data (engine 2b spec §4.1)
    nameable: bool  # a reference can name it; false for a key like `ap-name`, shown disabled
    children: bool
    formula: FormulaUse | None  # None when CEL can't select one of its fields (`in`, `null`, …)


@dataclass(frozen=True)
class Scope:
    entries: tuple[Entry, ...] = ()
    more: bool = False  # some children past MAX_CHILDREN, or a search past its bounds
    problem: Diagnostic | None = None  # `at`: why the field can't read the path, as validation says it
    unavailable: str | None = None  # why there's no scope at all


def scope(
    graph: Graph,
    ctx: ValidationContext,
    node: uuid.UUID,
    field: str,
    *,
    under: str | None = None,
    at: str | None = None,
    find: str | None = None,
) -> Scope:
    a = analyze(graph, ctx)
    if a.structure is None or a.validator is None:
        return Scope(unavailable=NO_ANALYSIS)
    if node not in a.structure.nodes:
        return Scope(unavailable=NO_STEP)
    reader = _Reader(a, node, field)
    if at is not None:
        return reader.at(at)
    if under is not None:
        return reader.under(under)
    if find is not None:
        return reader.find(find)
    return reader.tops()


def _head(p: RefPath) -> str:
    """The part of a reference before its fields: `steps.k.output`, `vars.n`, `loops.k.item`, `run.now`, `trigger`."""
    if p.root in ("steps", "loops"):
        return f"{p.root}.{p.name}.{p.section}"
    if p.root == "vars":
        return f"vars.{p.name}"
    if p.root == "run":
        return f"run.{p.section}"
    return p.root


def _split(p: RefPath) -> tuple[str | None, str]:
    """A path's parent and the name it shows: `trigger.events[0]` is `[0]` under `trigger.events`."""
    if not p.rest:
        return None, p.text
    last = p.rest[-1]
    shown = f"[{last}]" if isinstance(last, int) else last
    return p.text[: len(p.text) - len(shown) - (0 if isinstance(last, int) else 1)], shown


class _Reader:
    def __init__(self, a: Analysis, node: uuid.UUID, field: str) -> None:
        if a.structure is None or a.validator is None:
            raise ValueError("no analysis")
        self.s, self.v = a.structure, a.validator
        self.site = site_of(self.s, node, field)

    # ---- resolution -----------------------------------------------------------------------------------------

    def resolve(self, text: str) -> tuple[RefPath, Resolved] | None:
        try:
            p = parse_ref(text)
        except RefSyntaxError:
            return None
        r = self.v._resolve(self.site, p, report=False)
        return (p, r) if r is not None else None

    def roots(self) -> Iterator[str]:
        yield "trigger"
        for n_id in self.s.topo:
            key = self.s.nodes[n_id].key
            for section in ("output", "error"):
                if self.resolve(f"steps.{key}.{section}") is not None:
                    yield f"steps.{key}.{section}"
        for name in self.v.vars:
            if NAME.fullmatch(name):
                yield f"vars.{name}"
        if self.site.item_node is not None:
            yield from ("item", "index")
        for loop in self.s.chain(self.site.region):
            if loop is not None and loop != self.site.item_node and self.s.specs[loop].ref == C.LOOP:
                key = self.s.nodes[loop].key
                yield from (f"loops.{key}.item", f"loops.{key}.index")
        yield from ("run.id", "run.started_at", "run.now")

    # ---- entries --------------------------------------------------------------------------------------------

    def entry(self, text: str) -> Entry | None:
        found = self.resolve(text)
        if found is None:
            return None
        p, r = found
        parent, name = _split(p)
        types = json_types(r.schema)
        fmt = r.schema.get("format") if r.schema is not None else None
        unset = p.root == "vars" and p.name in self.v.unset and not self.v._set_before(self.site, str(p.name))
        return Entry(
            path=text,
            parent=parent,
            name=name,
            root=p.root,  # type: ignore[arg-type]  # parse_ref gives one of Root's values
            step=self._step(p),
            types=tuple(sorted(types)) if types is not None and types <= JSON_TYPES else (),
            format=fmt if isinstance(fmt, str) else None,
            missing=r.missing or unset,
            nullable=r.nullable,
            sensitive=r.taint.tainted,
            nameable=True,
            children=bool(self.child_names(r.schema)),
            formula=self.formula(p),
        )

    def _step(self, p: RefPath) -> str | None:
        if p.root in ("steps", "loops") and p.name in self.s.by_key:
            return str(self.s.by_key[str(p.name)])
        return None

    def child_names(self, schema: Any) -> list[str | int]:
        if schema is None:
            return []
        unfolded = alternatives(schema, schema)
        if unfolded is None:
            return []
        names: dict[str | int, None] = {}
        for option in unfolded[0]:
            props = option.get("properties")
            if isinstance(props, dict):
                names.update(dict.fromkeys(k for k in props if isinstance(k, str)))
            items = option.get("items")
            if isinstance(items, dict) and items:
                names[0] = None
        return list(names)

    def child(self, parent: str, name: str | int) -> Entry | None:
        if isinstance(name, int):
            text = f"{parent}[{name}]"
        elif NAME.fullmatch(name):
            text = f"{parent}.{name}"
        else:
            return self.unnameable(parent, name)
        if len(text) > MAX_REF_LENGTH:
            return self.unnameable(parent, name if isinstance(name, str) else f"[{name}]")
        return self.entry(text)

    def unnameable(self, parent: str, name: str) -> Entry | None:
        """A key a reference can't name (4c-2a ruling 5): shown, disabled, typed as its schema says."""
        found = self.resolve(parent)
        if found is None:
            return None
        p, r = found
        try:
            types = json_types(navigate(r.schema, [name]).schema) if r.schema is not None else None
        except PathError:
            types = None
        return Entry(
            path=f"{parent}.{name}", parent=parent, name=name, root=p.root,  # type: ignore[arg-type]
            step=self._step(p), types=tuple(sorted(types)) if types is not None and types <= JSON_TYPES else (),
            format=None, missing=True, nullable=False, sensitive=r.taint.tainted, nameable=False, children=False,
            formula=None,
        )  # fmt: skip

    # ---- the four questions ---------------------------------------------------------------------------------

    def tops(self) -> Scope:
        out: list[Entry] = []
        more = False
        for text in self.roots():
            top = self.entry(text)
            if top is None:
                continue
            out.append(top)
            names = self.child_names(self.resolve(text)[1].schema) if top.children else []  # type: ignore[index]
            more |= len(names) > MAX_CHILDREN
            out += [e for name in names[:MAX_CHILDREN] if (e := self.child(text, name)) is not None]
        return Scope(tuple(out), more=more)

    def under(self, text: str) -> Scope:
        found = self.resolve(text)
        if found is None:
            return Scope()
        names = self.child_names(found[1].schema)
        entries = [e for name in names[:MAX_CHILDREN] if (e := self.child(text, name)) is not None]
        return Scope(tuple(entries), more=len(names) > MAX_CHILDREN)

    def at(self, text: str) -> Scope:
        try:
            p = parse_ref(text)
        except RefSyntaxError as e:
            return Scope(problem=Diagnostic(code="value.syntax", message=f"`{text}`: {e}"))
        mark = len(self.v.diags)
        r = self.v._resolve(self.site, p)  # reported: its problem is the validator's own
        problems = self.v.diags[mark:]
        del self.v.diags[mark:]
        if r is None:
            return Scope(problem=problems[0] if problems else None)
        entry = self.entry(text)
        return Scope((entry,) if entry is not None else ())

    def find(self, text: str) -> Scope:
        needle = text.casefold()
        found: list[Entry] = []
        visits = 0
        queue: deque[tuple[str, int]] = deque((root, 0) for root in self.roots())
        while queue and len(found) < FIND_FOUND and visits < FIND_VISITS:
            parent, depth = queue.popleft()
            resolved = self.resolve(parent)
            if resolved is None or depth >= FIND_DEPTH:
                continue
            for name in self.child_names(resolved[1].schema)[:MAX_CHILDREN]:
                visits += 1
                e = self.child(parent, name)
                if e is None:
                    continue
                if isinstance(name, str) and needle in name.casefold():
                    found.append(e)
                if e.nameable and e.children:
                    queue.append((e.path, depth + 1))
                if visits >= FIND_VISITS or len(found) >= FIND_FOUND:
                    break
        return Scope(tuple(found[:FIND_FOUND]), more=bool(queue) or visits >= FIND_VISITS)

    # ---- formulas -------------------------------------------------------------------------------------------

    def formula(self, p: RefPath) -> FormulaUse | None:
        """How a formula reads `p` safely (4c-2a rulings 6, 7). None when CEL can't select one of its fields."""
        if any(isinstance(seg, str) and seg in CEL_KEYWORDS for seg in p.rest):
            return None
        head = _head(p)
        found = self.resolve(head)
        if found is None:
            return None
        whole = found[1]
        guards: list[Guard] = []
        if p.root == "steps" and whole.missing:
            guards.append(Guard("present", head))  # the step may not have run
        schema, nullable, prefix = whole.schema, whole.nullable, head
        for seg in p.rest:
            if nullable:
                guards.append(Guard("not_null", prefix))
            types = json_types(schema)
            if isinstance(seg, int):
                if types != frozenset({"array"}):
                    guards.append(Guard("is_list", prefix))
                guards.append(Guard("min_size", prefix, seg))
                path = f"{prefix}[{seg}]"
            else:
                if types != frozenset({"object"}):
                    guards.append(Guard("is_map", prefix))
                path = f"{prefix}.{seg}"
            try:
                step = navigate(schema, [seg]) if schema is not None else Resolved(None, True, missing=True)
            except PathError:
                return None
            if isinstance(seg, str) and step.missing:
                guards.append(Guard("present", path))  # never on a list always there: it isn't missing
            schema, nullable, prefix = step.schema, step.nullable, path
        reads = {p.text, *(g.path for g in guards)}
        return FormulaUse(tuple(guards), any(self.reads_sensitive(parse_ref(text)) for text in reads))

    def reads_sensitive(self, p: RefPath) -> bool:
        """Whether a formula reading `p` reads sensitive data: CEL's chain stops at the first index, so through one it
        reads that list whole; a bare root is read whole (engine 2b spec §4.1)."""
        cut = next((i for i, seg in enumerate(p.rest) if isinstance(seg, int)), len(p.rest))
        if p.root in ("trigger", "item") and cut == 0:
            return self.v._root_tainted(self.site, p.root)
        prefix = _head(p) + "".join(f".{seg}" for seg in p.rest[:cut])
        return self.v._taint_of(self.site, parse_ref(prefix)).tainted
```

Notes for the executor:
- `_split` must give `trigger.events` for `trigger.events[0]` and `steps.a.output` for `steps.a.output.x`; the test
  `test_at_answers_one_path…` and the entries' `parent` hold it. If the arithmetic is off by one, fix it test-first
  (a unit test of `_split` is welcome).
- `reads_sensitive`'s rule is pinned against validation by Task 5. If Task 5 shows a mismatch, the rule changes to
  match validation, never the reverse.
- mypy's `type: ignore` comments are only where `parse_ref`'s `str` meets `Root`; prefer a `cast(Root, p.root)` if
  the executor finds it cleaner.

- [ ] **Step 5: Run the tests to see them pass**

Run: `… $PY -m pytest -q tests/engine/graph/test_scope.py`
Expected: PASS, 11 tests.

- [ ] **Step 6: The engine's graph tests, lint, types, imports; commit**

Run: `… $PY -m pytest -q -n auto tests/engine/graph`, `ruff format src tests && ruff check src tests`,
`PYTHONPATH=src $PY -m mypy src`, the import linter.
Expected: PASS; no findings (the engine still imports neither `core` nor `apps`).

```bash
git add backend/src/dewpoint/engine/graph/validate.py backend/src/dewpoint/engine/graph/scope.py \
  backend/tests/engine/graph/test_scope.py
git commit -m "feat(engine): what a step's field can read, from the validator's own analysis (4c-2a, B6)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The guards' two guarantees

**Files:**
- Test: `backend/tests/engine/graph/test_scope_guards.py`
- Modify (only if a test shows a gap): `backend/src/dewpoint/engine/graph/scope.py`

**Interfaces:**
- Consumes: `scope`, `Entry`, `Guard.cel()` (Task 4); `compile_checked`, `evaluate` (`engine/cel/runtime.py`).
- Produces: nothing new: the guarantees 4c-2b's builder relies on.

- [ ] **Step 1: Write the tests**

Create `backend/tests/engine/graph/test_scope_guards.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The guards a scope gives (4c-2a rulings 6, 7): a formula made of them and the read publishes with no guard
problem, is never an error at run time, and reads sensitive data exactly when validation says it does."""

import functools
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from dewpoint.engine.cel import types as T
from dewpoint.engine.cel.runtime import compile_checked, evaluate
from dewpoint.engine.graph.scope import Entry, scope
from dewpoint.engine.graph.validate import ValidationResult, validate
from tests.engine.graph.test_scope import CTX, graph
from tests.support.graphs import G, cel, nid

GUARD_CODES = {"cel.conditional_ref", "cel.has_on_typed_path", "cel.invalid", "cel.unknown_name", "cel.bad_path",
               "cel.unproven_list", "ref.unknown_field", "ref.unknown_step", "ref.not_upstream"}  # fmt: skip
PER_PARENT = 25  # Mist's device kinds declare many fields: a sample of each list keeps the run short


@functools.cache
def collected() -> tuple[Entry, ...]:
    """Every entry `c`'s condition can read that a reference can name, up to six segments deep."""
    out: list[Entry] = []
    seen: set[str] = set()
    todo = [e for e in scope(graph().build(), CTX, nid("c"), "/condition").entries]
    while todo:
        e = todo.pop()
        if e.path in seen or not e.nameable:
            continue
        seen.add(e.path)
        out.append(e)
        if e.children and e.path.count(".") + e.path.count("[") < 6:
            todo += list(scope(graph().build(), CTX, nid("c"), "/condition", under=e.path).entries)[:PER_PARENT]
    return tuple(sorted(out, key=lambda e: e.path))


@functools.cache
def entries() -> tuple[Entry, ...]:
    """Those a formula can name: what the guards are for."""
    return tuple(e for e in collected() if e.formula is not None)


def guarded(e: Entry, read: str) -> str:
    assert e.formula is not None
    return " && ".join([*(g.cel() for g in e.formula.guards), read])


def checked(expr: str) -> ValidationResult:
    g: G = graph()
    for node in g.nodes:
        if node["key"] == "c":
            node["config"] = {"condition": cel(expr)}
    return validate(g.build(), CTX)


@functools.cache
def verdicts() -> dict[str, tuple[list[str], bool]]:
    """Per entry: the guard problems validation finds at `c`, and whether it finds `c`'s condition tainted."""
    out: dict[str, tuple[list[str], bool]] = {}
    for e in entries():
        result = checked(guarded(e, f"{e.path} == {e.path}"))
        mine = [d.code for d in result.diagnostics if d.node == nid("c") and d.code in GUARD_CODES]
        tainted = (str(nid("c")), "/condition") in result.tainted_sites
        out[e.path] = (mine, tainted)
    return out


def test_covers_the_cases_that_need_guards() -> None:
    kinds = {g.kind for e in entries() for g in e.formula.guards}  # type: ignore[union-attr]
    assert kinds == {"present", "not_null", "is_map", "is_list", "min_size"}


def test_every_guarded_read_publishes_without_a_guard_problem() -> None:
    problems = {path: codes for path, (codes, _) in verdicts().items() if codes}
    assert problems == {}


def there(e: Entry) -> str:
    """"is there" (4c-2a ruling 6): the guards, and not null where it may be null or is untyped."""
    assert e.formula is not None
    tests = [g.cel() for g in e.formula.guards]
    if e.nullable or not e.types:
        tests.append(f"{e.path} != null")
    return " && ".join(tests) or "true"


def test_is_there_publishes_without_a_guard_problem() -> None:
    for e in entries():
        result = checked(there(e))
        assert [d.code for d in result.diagnostics if d.node == nid("c") and d.code in GUARD_CODES] == [], e.path


def test_says_a_formula_reads_sensitive_data_exactly_when_validation_does() -> None:
    wrong = {e.path for e in entries() if e.formula.sensitive != verdicts()[e.path][1]}  # type: ignore[union-attr]
    assert wrong == set()


# At run time. The data holds what its schemas declare: admission checks a run's input against its input schema, and
# a plugin's output is checked against its output schema. So each position the scope types gets a value of one of its
# types (or nothing where it may be missing, or null where it may be null), and a position it doesn't type gets any
# JSON at all: the wrong type, an empty list, a string where a list might have been.
_KEYS = sorted({seg for e in collected() for seg in e.path.replace("[", ".").replace("]", "").split(".")} | {"z"})
_SCALARS = st.none() | st.booleans() | st.integers(-3, 3) | st.floats(allow_nan=False, allow_infinity=False)
_ANY = st.recursive(
    _SCALARS | st.text(max_size=2),
    lambda c: st.lists(c, max_size=3) | st.dictionaries(st.sampled_from(_KEYS), c, max_size=4),
    max_leaves=12,
)
_DECLS = {"trigger": T.MAP, "steps": T.MAP, "vars": T.MAP, "loops": T.MAP, "run": T.MAP}


@functools.cache
def children() -> dict[str, tuple[Entry, ...]]:
    out: dict[str, list[Entry]] = {}
    for e in collected():
        if e.parent is not None:
            out.setdefault(e.parent, []).append(e)
    return {k: tuple(v) for k, v in out.items()}


def _optional(e: Entry) -> bool:
    """Whether a field may be absent from its parent itself (`missing` also counts a step that may not have run): its
    read is guarded by has(). One a formula can't name falls back to `missing`."""
    if e.formula is None:
        return e.missing
    return any(g.kind == "present" and g.path == e.path for g in e.formula.guards)


def _data(draw: Any, e: Entry) -> Any:
    if e.nullable and draw(st.booleans()):
        return None
    kind = draw(st.sampled_from(e.types or ("any",)))
    below = children().get(e.path, ())
    if kind == "object":  # a field is left out only where it may be absent itself: where its read is guarded by has()
        return {c.name: _data(draw, c) for c in below if not (_optional(c) and draw(st.booleans()))}
    if kind == "array":
        element = next((c for c in below if c.name == "[0]"), None)
        if element is None:
            return draw(st.lists(_ANY, max_size=2))
        return [_data(draw, element) for _ in range(draw(st.integers(0, 2)))]
    if kind == "string":
        return draw(st.text(max_size=2))
    if kind == "integer":
        return draw(st.integers(-3, 3))
    if kind == "number":
        return draw(st.integers(-3, 3) | st.floats(allow_nan=False, allow_infinity=False))
    if kind == "boolean":
        return draw(st.booleans())
    if kind == "null":
        return None
    return draw(_ANY)


@functools.cache
def programs() -> tuple[tuple[str, Any], ...]:
    return tuple((e.path, compile_checked(guarded(e, f"{e.path} == {e.path}"), _DECLS)) for e in entries())


@settings(max_examples=120, deadline=None)
@given(st.data())
def test_a_guarded_read_is_never_an_error_at_run_time(data: st.DataObject) -> None:
    tops = {e.path: e for e in collected() if e.parent is None}
    trigger = _data(data.draw, tops["trigger"])
    # As the runtime binds them (engine/cel/bind.py): `{}` for a step that hasn't run, `{"output": …}` once it has.
    steps: dict[str, Any] = {}
    for path, e in tops.items():
        if path.startswith("steps.") and path.endswith(".output"):
            ran = not e.missing or data.draw(st.booleans())
            steps[path.split(".")[1]] = {"output": _data(data.draw, e)} if ran else {}
    bindings = {"trigger": trigger, "steps": steps, "vars": {"count": 0}, "loops": {},
                "run": {"id": "r", "started_at": "2026-01-01T00:00:00Z", "now": "2026-01-01T00:00:00Z"}}  # fmt: skip
    for path, program in programs():
        result = evaluate(program, bindings)
        assert result.kind == "value", (path, result.message)
```

Check before running: `evaluate`'s and `compile_checked`'s signatures in `engine/cel/runtime.py` (the 4c-2 mockup
check script called `compile_checked(expr, {"trigger": types.MAP})` and `evaluate(compiled, {"trigger": …})`, and read
`r.kind`, `r.value`, `r.message`); `T.MAP` in `engine/cel/types.py`. The formula `x == x` compiles for every type; if
the executor finds one it doesn't, it reads the value with `type(x) == type(x)` instead and says so in the ledger.

- [ ] **Step 2: Run them**

Run: `… $PY -m pytest -q tests/engine/graph/test_scope_guards.py`
Expected: PASS. If a test fails, it names the entry: the rule in `scope.formula` (or `formula_sensitive`) is
corrected to what validation and the runtime need, test-first, and the correction is a mid-slice ruling (M58 onward)
with the case that showed it. A guard is never dropped to make a test pass without saying why.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/engine/graph/test_scope_guards.py backend/src/dewpoint/engine/graph/scope.py
git commit -m "test(engine): a scope's guards publish clean, never fail at run time, and match validation's taint (4c-2a)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Milestone 1's checks, and its pause**

Run every engine test (`… $PY -m pytest -q -n auto tests/engine`), the golden replays among them, ruff, mypy and the
import linter. Then, with the owner's OK (about 12 minutes), the whole backend suite (`-n auto`): the merge changes
what validation says for every graph a test publishes (the plugins' and the worker's run tests among them), and only
the whole suite shows them all. A test that now fails because validation says more is read, never patched blind: its
graph is fixed, or its expectation, with a mid-slice ruling saying which and why. Then append to the ledger:

```markdown
### 4c-2a, milestone 1 (2026-10-XX)

Tasks 1–5 at <sha>: the merge, liveness, the scope, the guards. Engine tests <N passed>; golden replays unchanged;
ENGINE_ABI 6. Mid-slice rulings: <M58…, or none>.
```

Commit it (`docs(editor-4): 4c-2a milestone 1`), and **pause**: the owner reviews the engine changes before Task 6.
The pause message lists what validation now says differently (the new diagnostics' cases, from Task 2's tests) and
every mid-slice ruling.

---

# Milestone 2 — the API

### Task 6: Validate says which steps may not run

**Files:**
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`ValidationOut.conditional_steps`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`validate_draft`)
- Modify: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts` (regenerated), and any frontend test
  fixture the type checker names
- Test: `backend/tests/apps/api/test_workflows.py`

**Interfaces:**
- Consumes: `ValidationResult.conditional_steps` (Task 3).
- Produces: `ValidationOut.conditional_steps: list[str]` (node ids, sorted) in the API and in `schema.d.ts`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/apps/api/test_workflows.py`:

```python
async def test_validate_says_which_steps_may_not_run(app, owner_sessionmaker, api_settings) -> None:
    """4c-2a ruling 3: a branch's steps may not run; the step after the join does."""
    draft = (
        G().node("c", "flow.if@1", {"condition": True})
        .node("t", "testkit.echo@1", {"value": 1}).node("f", "testkit.echo@1", {"value": 2})
        .node("j", "testkit.echo@1", {"value": 3})
        .edge("c", "t", port="true").edge("c", "f", port="false").edge("t", "j").edge("f", "j")
        .data()
    )  # fmt: skip
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Branches", "draft": draft})).json()
        r = await c.post(f"/api/v1/t/{tid}/workflows/{wf['id']}/validate")
    assert r.status_code == 200, r.text
    assert r.json()["conditional_steps"] == sorted([str(nid("t")), str(nid("f"))])
```

- [ ] **Step 2: Run it to see it fail**

Run (Docker reachable; see "How to run things"):
`… $PY -m pytest -q tests/apps/api/test_workflows.py::test_validate_says_which_steps_may_not_run`
Expected: FAIL: `KeyError: 'conditional_steps'`.

- [ ] **Step 3: Answer it**

In `backend/src/dewpoint/apps/api/responses.py`, add to `ValidationOut`:

```python
    conditional_steps: list[str]  # the steps that may not run, by id (4c-2a ruling 3; ledger ruling 70's badge)
```

In `validate_draft` (`backend/src/dewpoint/apps/api/routes/workflows.py`), add to the returned dict:

```python
        # The steps that may not run on every path: the canvas's "conditional" badge (ledger ruling 70).
        "conditional_steps": list(result.conditional_steps) if result is not None else [],
```

- [ ] **Step 4: Run it to see it pass, then the API's workflow tests**

Run: `… $PY -m pytest -q tests/apps/api/test_workflows.py tests/apps/api/test_openapi.py`
Expected: PASS.

- [ ] **Step 5: Regenerate the client's schema and types**

Run the two commands in "How to run things" (`openapi.json` from the backend, then `gen:api`), then from `frontend/`:
`npx -y pnpm@12.6.0 check:api && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 test`.
Expected: `check:api` clean. If `typecheck` names a test fixture that builds a `Validation` without
`conditional_steps` (the Editor test's default validate answer is one candidate), add `conditional_steps: []` to it,
nothing else, and run the three again. Expected then: PASS, the suite's count unchanged.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/api/responses.py backend/src/dewpoint/apps/api/routes/workflows.py \
  backend/tests/apps/api/test_workflows.py frontend/src/api/openapi.json frontend/src/api/schema.d.ts
git add -u frontend/src   # only the fixtures typecheck named
git commit -m "feat(api): validate says which steps may not run (4c-2a, ledger ruling 70)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The scope route

**Files:**
- Modify: `backend/src/dewpoint/apps/workflow_ops.py` (`validation_context`, shared by `check_draft` and the new
  `draft_scope`)
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`GuardOut`, `FormulaUseOut`, `ScopeEntryOut`, `ScopeOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`GET …/draft/scope`)
- Modify: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts` (regenerated)
- Create: `backend/tests/apps/api/test_draft_data.py`
- Modify: `backend/tests/apps/api/test_workflows.py` (`test_permission_matrix`), `backend/tests/apps/api/test_openapi.py`
  (`SLICE_4C`)

**Interfaces:**
- Consumes: `scope.scope`, `Scope`, `Entry`, `NO_STEP`, `NO_ANALYSIS`, `UNREADABLE` (Task 4).
- Produces:
  - `workflow_ops.validation_context(s, tenant_id, graph, settings) -> tuple[ValidationContext, dict[uuid.UUID,
    WorkflowVersion]]`;
  - `workflow_ops.draft_scope(s, tenant_id, draft, settings, node, field, *, under=None, at=None, find=None) -> Scope`;
  - `workflow_ops.scope_answer(found: Scope) -> dict[str, object]`;
  - `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/scope?node=&field=[&under=|&at=|&find=]` →
    `ScopeOut {draft_revision, node, field, state, reason, entries, more, problem}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/apps/api/test_draft_data.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The editor's data routes (B6, B7; 4c-2a rulings 4–10): what a field can read, and a step's newest sample."""

import json
import uuid
from typing import Any

import pytest

from tests.apps.api.helpers import member_client, session_client
from tests.support.graphs import G, nid
from tests.support.registry import sync_test_plugins

DRAFT = G().node("a", "testkit.echo@1", {"value": 1}).node("c", "flow.if@1", {"condition": True}).edge("a", "c").data()
FIELD = {"node": str(nid("c")), "field": "/condition"}


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def _create(c: Any, tid: Any, draft: dict[str, Any] = DRAFT) -> str:
    wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Data", "draft": draft})).json()
    return f"/api/v1/t/{tid}/workflows/{wf['id']}"


async def test_answers_what_a_field_can_read(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        r = await c.get(f"{await _create(c, tid)}/draft/scope", params=FIELD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["draft_revision"], body["state"], body["reason"], body["problem"]) == (1, "ok", None, None)
    value = next(e for e in body["entries"] if e["path"] == "steps.a.output.value")
    assert value["step"] == str(nid("a")) and value["nameable"] and value["types"] == []  # the echo's value: any
    # Data the schema doesn't describe counts as sensitive (engine 2b spec §4.1), so a formula on it would need
    # declassifying; `a` always runs before `c`, so nothing guards it.
    assert value["sensitive"] and value["formula"] == {"guards": [], "sensitive": True}
    assert next(e for e in body["entries"] if e["path"] == "run.now")["formula"] == {"guards": [], "sensitive": False}


async def test_a_viewer_reads_the_scope_too(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, tid, "viewer")
    async with viewer:
        assert (await viewer.get(f"{base}/draft/scope", params=FIELD)).status_code == 200


async def test_says_why_there_is_no_scope(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        r = await c.get(f"{await _create(c, tid)}/draft/scope", params={**FIELD, "node": str(uuid.uuid4())})
    assert r.status_code == 200 and r.json()["state"] == "unavailable" and r.json()["entries"] == []
    assert r.json()["reason"] == "This step isn't in the saved draft yet."


async def test_answers_the_validators_own_problem_for_a_path(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        r = await c.get(f"{await _create(c, tid)}/draft/scope", params={**FIELD, "at": "steps.nope.output"})
    assert r.status_code == 200 and r.json()["problem"]["code"] == "ref.unknown_step"


async def test_asks_one_question_at_a_time(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        two = await c.get(f"{base}/draft/scope", params={**FIELD, "under": "steps.a.output", "find": "value"})
        bad = await c.get(f"{base}/draft/scope", params={**FIELD, "field": "condition"})
    assert (two.status_code, two.json()) == (422, {"error": "one_question"})  # the app's error shape: no `detail`
    assert (bad.status_code, bad.json()) == (422, {"error": "invalid_field"})
```

Add to `test_permission_matrix` in `backend/tests/apps/api/test_workflows.py`, inside the `for role in ("viewer",
"operator")` loop:

```python
            scope = await c.get(f"{base}/draft/scope", params={"node": str(nid("a")), "field": "/value"})
            assert scope.status_code == 200  # workflow.view: a read-only drawer shows a pill's details too
```

Add to `backend/tests/apps/api/test_openapi.py`, after `SLICE_4B` and its test:

```python
# What the web client calls in slice 4c-2: each answers a named model.
SLICE_4C = [
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/scope"),
]


@pytest.mark.parametrize("method,path", SLICE_4C)
def test_slice_4c_routes_name_their_answer(method: str, path: str) -> None:
    responses = schema()["paths"][path][method]["responses"]
    ok = next(code for code in responses if code.startswith("2"))
    body = responses[ok]["content"]["application/json"]["schema"]
    assert "$ref" in body or "$ref" in body.get("items", {}), body
```

- [ ] **Step 2: Run them to see them fail**

Run: `… $PY -m pytest -q tests/apps/api/test_draft_data.py tests/apps/api/test_openapi.py tests/apps/api/test_workflows.py::test_permission_matrix`
Expected: FAIL: the route answers 404; `SLICE_4C`'s path isn't in the schema.

- [ ] **Step 3: Share the validation context**

In `backend/src/dewpoint/apps/workflow_ops.py`, add `from dewpoint.engine.graph import scope as scopes` and split
`check_draft`:

```python
async def validation_context(
    s: AsyncSession, tenant_id: uuid.UUID, graph: Graph, settings: Settings
) -> tuple[ValidationContext, dict[uuid.UUID, WorkflowVersion]]:
    """What validating `graph` needs: its node types, and the active versions of the workflows it pins."""
    rows = await registry.load_node_types(s, {n.type for n in graph.nodes} | picker_refs(graph))
    catalog = Catalog(spec_from_manifest(r.manifest, r.state) for r in rows)
    pins = await service.active_versions(s, tenant_id, referenced_workflows(graph))
    ctx = ValidationContext(
        catalog=catalog,
        subflows={
            wid: SubflowInfo(
                wid, v.id, v.input_schema, v.output_schema, v.output_taint, declares_csv=declares_csv(v.graph)
            )
            for wid, v in pins.items()
        },
        max_run_duration=timedelta(days=settings.max_run_duration_days),
    )
    return ctx, pins


async def check_draft(s: AsyncSession, tenant_id: uuid.UUID, draft: Any, settings: Settings) -> Checked:
    try:
        graph = parse_graph(draft)
    except GraphFormatError as e:
        return Checked(None, list(e.diagnostics), {}, None)
    ctx, pins = await validation_context(s, tenant_id, graph, settings)
    result = await asyncio.to_thread(validate, graph, ctx)  # CPU-bound: keep the event loop serving others
    return Checked(graph, list(result.diagnostics), pins, result)


async def draft_scope(
    s: AsyncSession,
    tenant_id: uuid.UUID,
    draft: Any,
    settings: Settings,
    node: uuid.UUID,
    field: str,
    *,
    under: str | None = None,
    at: str | None = None,
    find: str | None = None,
) -> scopes.Scope:
    """What `field` of `node` can read in the saved draft (B6; 4c-2a ruling 4)."""
    try:
        graph = parse_graph(draft)
    except GraphFormatError:
        return scopes.Scope(unavailable=scopes.UNREADABLE)
    ctx, _ = await validation_context(s, tenant_id, graph, settings)
    return await asyncio.to_thread(scopes.scope, graph, ctx, node, field, under=under, at=at, find=find)


def scope_answer(found: scopes.Scope) -> dict[str, object]:
    return {
        "state": "unavailable" if found.unavailable is not None else "ok",
        "reason": found.unavailable,
        "entries": [dataclasses.asdict(e) for e in found.entries],
        "more": found.more,
        "problem": found.problem.to_json() if found.problem is not None else None,
    }
```

(Add `import dataclasses`. `dataclasses.asdict` keeps the tuples of `types` and `guards` as tuples, which the
response model accepts as lists; it drops `Guard.cel`, a method.)

- [ ] **Step 4: Name the answer**

In `backend/src/dewpoint/apps/api/responses.py`, after `ValidationOut`:

```python
class GuardOut(_Answer):
    """A test a formula makes before it reads a path (4c-2a ruling 6). `size`, for `min_size`: the list's size must
    exceed it."""

    kind: Literal["present", "not_null", "is_map", "is_list", "min_size"]
    path: str
    size: int | None


class FormulaUseOut(_Answer):
    guards: list[GuardOut]
    sensitive: bool  # a formula reading it, with its guards, reads sensitive data (4c-2a ruling 7)


class ScopeEntryOut(_Answer):
    path: str
    parent: str | None
    name: str
    root: Literal["trigger", "steps", "vars", "item", "index", "loops", "run"]
    step: str | None
    types: list[Literal["string", "integer", "number", "boolean", "array", "object", "null"]]  # none: any value
    format: str | None
    missing: bool
    nullable: bool
    sensitive: bool
    nameable: bool  # false: a key a reference can't name, shown disabled
    children: bool
    formula: FormulaUseOut | None  # null: CEL can't select one of its fields


class ScopeOut(_Answer):
    """What one field of the saved draft's step can read (B6), at the revision it was computed for: an editor drops an
    answer for an older revision (D17)."""

    draft_revision: int
    node: str
    field: str
    state: Literal["ok", "unavailable"]
    reason: str | None
    entries: list[ScopeEntryOut]
    more: bool
    problem: DiagnosticOut | None
```

- [ ] **Step 5: The route**

In `backend/src/dewpoint/apps/api/routes/workflows.py`, add `import re`, `Query` to the `fastapi` import, `ScopeOut`
to the `responses` import, and after `validate_draft`:

```python
POINTER = re.compile(r"(/[^/]*)*")  # a JSON pointer inside a step's config ("" is the whole config)


@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/scope", response_model=ScopeOut)
async def draft_scope(
    workflow_id: uuid.UUID,
    node: uuid.UUID,
    field: str = Query(max_length=200),
    under: str | None = Query(default=None, max_length=512),
    at: str | None = Query(default=None, max_length=512),
    find: str | None = Query(default=None, min_length=1, max_length=100),
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    """What one field of the saved draft's step can read (B6; 4c-2a rulings 4–7): the top of each root, the children
    of one path (`under`), one path (`at`), or fields by name (`find`)."""
    if not POINTER.fullmatch(field):
        raise HTTPException(422, detail={"error": "invalid_field"})
    if sum(q is not None for q in (under, at, find)) > 1:
        raise HTTPException(422, detail={"error": "one_question"})
    wf = await _get(db, ctx, workflow_id)
    found = await workflow_ops.draft_scope(
        db, ctx.tenant_id, wf.draft, settings, node, field, under=under, at=at, find=find
    )
    return {"draft_revision": wf.draft_revision, "node": str(node), "field": field, **workflow_ops.scope_answer(found)}
```

Check before relying on it: `fastapi.Query`'s `max_length`/`min_length` keywords in the installed FastAPI
(`backend/.venv`), and that `fastapi.Query` is already in ruff's `extend-immutable-calls` (it is).

- [ ] **Step 6: Run the tests to see them pass**

Run: `… $PY -m pytest -q tests/apps/api/test_draft_data.py tests/apps/api/test_openapi.py tests/apps/api/test_workflows.py tests/apps/test_workflow_ops.py`
Expected: PASS.

- [ ] **Step 7: Regenerate the client's schema and types; lint; commit**

Regenerate as in Task 6 Step 5, then `check:api`, `typecheck` and `test` from `frontend/`: PASS, no fixture change
(nothing in the UI calls the route yet). Then `ruff format src tests && ruff check src tests`, mypy, the import linter.

```bash
git add backend/src/dewpoint/apps/workflow_ops.py backend/src/dewpoint/apps/api/responses.py \
  backend/src/dewpoint/apps/api/routes/workflows.py backend/tests/apps/api/test_draft_data.py \
  backend/tests/apps/api/test_workflows.py backend/tests/apps/api/test_openapi.py \
  frontend/src/api/openapi.json frontend/src/api/schema.d.ts
git commit -m "feat(api): what a field of the saved draft can read (4c-2a, B6)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Milestone 2's ledger line**

Append to the ledger `### 4c-2a, milestone 2 (date)`: Tasks 6–7 at `<sha>`, the API tests' result, `check:api`
clean; commit it (`docs(editor-4): 4c-2a milestone 2`). No pause: Milestone 3 follows.

---

# Milestone 3 — samples

### Task 8: The record table (migration 0045)

**Files:**
- Create: `backend/migrations/versions/0045_run_step_connections.py`
- Modify: `backend/src/dewpoint/core/models/runs.py` (`RunStepConnection`)
- Modify: `backend/tests/core/test_migration_chain.py`, `backend/tests/core/erasure/test_fence.py` (`FENCED_TABLES`)
- Modify: `backend/tests/core/retention/support.py` (`tree` writes a record per run; `TREE_ROWS` counts them),
  `backend/tests/core/retention/test_sweep.py` (the tree's exact count)
- Create: `backend/tests/core/runs/test_run_step_connections.py`

**Interfaces:**
- Consumes: nothing.
- Produces: table `run_step_connections (tenant_id, run_id, step_id, iteration_key, attempt, connection_id, type,
  name, revision, context, opened_at)`, primary key `(run_id, step_id, iteration_key, attempt, connection_id)`; model
  `RunStepConnection`; index `runs_workflow_recent (workflow_id, queued_at DESC, id DESC)`.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/core/test_migration_chain.py`, change the head's assertion to `["0045"]` and add:

```python
def test_the_samples_record_comes_after_the_workflows_list_index() -> None:
    """Slot 0045 (B7) is chained after main's head when it was written, 0047: slot numbers name ownership, not order."""
    assert script().get_revision("0045").down_revision == "0047"
```

In `backend/tests/core/erasure/test_fence.py`, add `"run_step_connections"` to `FENCED_TABLES` (alphabetically, after
`"run_slots"`), rewrapping the tuple's lines within 120 characters (it's `# fmt: skip`).

In `backend/tests/core/retention/support.py`, the run tree that retention's and erasure's tests seed holds a record
too, so both prove it's swept with its run (the erasure test checks every fenced table held a row before). In `tree`,
after each run's `run_steps` row (give the step id a name, `step = uuid.uuid4()`, and use it in both):

```python
        await sql(owner, "insert into run_step_connections (tenant_id, run_id, step_id, iteration_key, attempt, "
                  "connection_id, type, name, revision) values (:t, :r, :s, '', 1, :c, 'http', 'c', 1)",
                  t=ctx["t"], r=r, s=step, c=uuid.uuid4())  # fmt: skip
```

and add to `TREE_ROWS`, before its last term:

```python
    "(select count(*) from run_step_connections c join runs r on r.id = c.run_id where r.root_run_id = :r) + "
```

`test_sweep.py::test_a_tree_past_its_cutoff_goes_whole_with_its_request` counts a tree's rows exactly; its
assertion becomes:

```python
    assert swept.runs == 1 and before == 2 + 2 + 2 + 1 + 2 + 1 + 1 + 1  # runs, steps, their connections, output, …
```

Create `backend/tests/core/runs/test_run_step_connections.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The connections each step attempt opened (B7; 4c-2a ruling 8): the tenant's alone, written by the worker, read by
the API, gone with their run."""

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from dewpoint.core.db import tenant_scope
from tests.support.connections import seed_step

INSERT = text(
    "insert into run_step_connections (tenant_id, run_id, step_id, iteration_key, attempt, connection_id, type, name, "
    "revision) values (:t, :r, :s, '', 1, :c, 'testkit', 'Lab', 1)"
)


async def _record(maker: Any, tenant: uuid.UUID, run: uuid.UUID, step: uuid.UUID) -> None:
    async with maker() as s, s.begin():
        await tenant_scope(s, tenant)
        await s.execute(INSERT, {"t": tenant, "r": run, "s": step, "c": uuid.uuid4()})


async def test_the_table_forces_row_level_security(owner_sessionmaker) -> None:
    async with owner_sessionmaker() as s:
        flags = (
            await s.execute(
                text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'run_step_connections'")
            )
        ).one()
    assert tuple(flags) == (True, True)


async def test_rows_stay_in_their_tenant(owner_sessionmaker, worker_sessionmaker, api_sessionmaker) -> None:
    a, b = await seed_step(owner_sessionmaker, named=[None]), await seed_step(owner_sessionmaker, named=[None])
    await _record(worker_sessionmaker, a.tenant, a.run, a.step)
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, b.tenant)
        assert (await s.execute(text("select count(*) from run_step_connections"))).scalar_one() == 0
        await tenant_scope(s, a.tenant)
        assert (await s.execute(text("select count(*) from run_step_connections"))).scalar_one() == 1
    with pytest.raises(DBAPIError, match="row-level security"):
        async with worker_sessionmaker() as s, s.begin():
            await tenant_scope(s, a.tenant)
            await s.execute(INSERT, {"t": b.tenant, "r": b.run, "s": b.step, "c": uuid.uuid4()})


async def test_the_api_reads_and_never_writes(owner_sessionmaker, api_sessionmaker) -> None:
    a = await seed_step(owner_sessionmaker, named=[None])
    with pytest.raises(DBAPIError, match="permission denied"):
        await _record(api_sessionmaker, a.tenant, a.run, a.step)


async def test_goes_with_its_run(owner_sessionmaker, worker_sessionmaker) -> None:
    a = await seed_step(owner_sessionmaker, named=[None])
    await _record(worker_sessionmaker, a.tenant, a.run, a.step)
    async with owner_sessionmaker() as s, s.begin():
        await s.execute(text("delete from runs where id = :r"), {"r": a.run})
        assert (await s.execute(text("select count(*) from run_step_connections"))).scalar_one() == 0
```

Check before running: `tenant_scope`'s module (`dewpoint.core.db`, as `tests/core/plugins/test_plugin_calls_schema.py`
imports it), and whether a run with an `execution_evidence` row can be deleted by the owner as above (migration 0039's
trigger writes one per root run). If the delete is refused by another table's key, delete through what retention
deletes (`core/retention/sweep.py`) or remove that row first, and say which in the test's comment.

- [ ] **Step 2: Run them to see them fail**

Run: `… $PY -m pytest -q tests/core/test_migration_chain.py tests/core/runs/test_run_step_connections.py tests/core/erasure/test_fence.py`
Expected: FAIL: the head is 0047; the table doesn't exist.

- [ ] **Step 3: Write the migration**

Create `backend/migrations/versions/0045_run_step_connections.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""run_step_connections: the connections each step attempt opened, as they were (sub-project 4, B7; 4c-2a ruling 8).
A connection keeps its id while its config changes (`connections.revision`), so a sample's connection can't come
from the graph: the worker records its id, type, name, revision and non-secret config when an attempt opens it. No
foreign key to `connections`, which can be deleted; the record goes with its run.

Also `runs_workflow_recent`, for a step's newest sample among every kind of run of a workflow (4c-2a ruling 9).

Slot 0045 is the owner's reservation for B7 (the editor-ui-4 ledger); slot numbers name ownership, not order, so it is
chained after main's head when it was written, 0047."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0045"
down_revision = "0047"
branch_labels = None
depends_on = None

ACCESS = (
    "ALTER TABLE run_step_connections ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE run_step_connections FORCE ROW LEVEL SECURITY",
    "CREATE POLICY run_step_connections_scope ON run_step_connections "
    "USING (tenant_id = app_tenant_id()) WITH CHECK (tenant_id = app_tenant_id())",
    "GRANT SELECT, INSERT ON run_step_connections TO dewpoint_worker",
    "GRANT SELECT ON run_step_connections TO dewpoint_api",
    "CREATE TRIGGER run_step_connections_fence BEFORE INSERT ON run_step_connections FOR EACH ROW "
    "EXECUTE FUNCTION tenant_insert_fence()",
)


def upgrade() -> None:
    op.create_table(
        "run_step_connections",
        sa.Column("tenant_id", pg.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("run_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("step_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("iteration_key", sa.Text, primary_key=True),
        sa.Column("attempt", sa.Integer, primary_key=True),
        sa.Column("connection_id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("context", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id"], ["runs.id", "runs.tenant_id"], name="run_step_connections_run", ondelete="CASCADE"
        ),
    )
    for statement in ACCESS:
        op.execute(statement)
    op.create_index("runs_workflow_recent", "runs", ["workflow_id", sa.text("queued_at DESC"), sa.text("id DESC")])


def downgrade() -> None:
    op.drop_index("runs_workflow_recent", table_name="runs")
    op.drop_table("run_step_connections")
```

The policy names no role, like `run_steps_scope`: it applies to every role. Retention and erasure delete `runs`, and
the record goes by its foreign key, as `run_steps` does (`tests/apps/erasure/test_proof.py` holds that no tenant row
is left).

- [ ] **Step 4: The model**

In `backend/src/dewpoint/core/models/runs.py`, after `RunStep`:

```python
class RunStepConnection(Base):
    """A connection one step attempt opened, as it was (B7; 4c-2a ruling 8): what a sample says it ran with."""

    __tablename__ = "run_step_connections"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "tenant_id"], ["runs.id", "runs.tenant_id"], name="run_step_connections_run", ondelete="CASCADE"
        ),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    step_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    iteration_key: Mapped[str] = mapped_column(Text, primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)  # no key: may be deleted
    type: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(100))
    revision: Mapped[int] = mapped_column(Integer)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))  # its non-secret config
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 5: Run the tests to see them pass, then the database's guards**

Run: `… $PY -m pytest -q -n auto tests/core/test_migration_chain.py tests/core/runs tests/core/erasure tests/core/tenancy tests/core/retention tests/apps/erasure`
Expected: PASS (the fence, the tenant-key guard on foreign keys, retention's sweep of a tree, the erasure's proof
that no tenant row is left). About 7 minutes with `-n 4` locally: the erasure stages are slow. A model/migration comparison
test, if the suite has one, passes too: the executor greps `tests/core` for one and runs it.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/versions/0045_run_step_connections.py backend/src/dewpoint/core/models/runs.py \
  backend/tests/core/test_migration_chain.py backend/tests/core/erasure/test_fence.py \
  backend/tests/core/retention/support.py backend/tests/core/retention/test_sweep.py \
  backend/tests/core/runs/test_run_step_connections.py
git commit -m "feat(db): each step attempt's connections, as they were (0045; 4c-2a, B7)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The worker records what it opens

**Files:**
- Modify: `backend/src/dewpoint/apps/worker/network.py` (`StoredConnection.name`, `DbConnections.load`,
  `ConnectionSource.opened`, `DbConnections.opened`, `Network.attempt`, `AttemptNetwork`)
- Modify: `backend/src/dewpoint/apps/worker/activities.py` (`run_step`: the attempt's iteration and number)
- Test: `backend/tests/apps/worker/test_activities_network.py`

**Interfaces:**
- Consumes: `RunStepConnection` (Task 8).
- Produces:
  - `StoredConnection(type, config, secret_ct, revision=0, name="")`;
  - `ConnectionSource.opened(tenant_id, run_id, step_id, iteration_key, attempt, connection_id, stored) -> None`;
  - `Network.attempt(..., iteration_key: str = "", attempt: int = 1)` (keywords, defaulted: every existing caller
    keeps working);
  - `CONTEXT_BYTES = 4096`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/apps/worker/test_activities_network.py` (add `from sqlalchemy import text`,
`from dewpoint.sdk.net import SimulationSendsNothing` if not imported):

```python
# What an attempt opened, as it was (B7; 4c-2a ruling 8).
async def _records(owner: Any) -> list[dict[str, Any]]:
    async with owner() as s:
        rows = await s.execute(
            text("select iteration_key, attempt, type, name, revision, context from run_step_connections")
        )
        return [dict(r._mapping) for r in rows]


async def test_an_attempt_records_the_connection_it_opened(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(respond(201, b"made"), tls_names=NAMES) as server:
        await _run(worker_sessionmaker, owner_sessionmaker, server.port, HttpCall)
        base_url = f"https://dewpoint.test:{server.port}"
    [row] = await _records(owner_sessionmaker)
    assert (row["iteration_key"], row["attempt"], row["type"], row["revision"]) == ("", 1, "testkit", 1)
    assert row["name"].startswith("c-") and row["context"] == {"base_url": base_url}


async def test_an_attempt_that_fails_still_records_what_it_opened(owner_sessionmaker, worker_sessionmaker) -> None:
    async with serve(_hang_up(), tls_names=NAMES) as server:  # opened, then the server hangs up
        await _failure(worker_sessionmaker, owner_sessionmaker, server.port, HttpCall)
    assert len(await _records(owner_sessionmaker)) == 1
```

Then a test of the attempt itself, opening one connection twice, and of a simulated attempt:

```python
async def test_opening_a_connection_twice_records_it_once(owner_sessionmaker, worker_sessionmaker) -> None:
    tenant = uuid.uuid4()
    await seed_step(owner_sessionmaker, named=[None], tenant=tenant)
    cid = await add_connection(owner_sessionmaker, tenant, config={"base_url": "https://dewpoint.test:1"})
    seeded = await seed_step(owner_sessionmaker, named=[cid], tenant=tenant, node_type="testkit.http_call@1")
    network = Network(guard=guard({}, []), connections=DbConnections(worker_sessionmaker),
                      sessionmaker=worker_sessionmaker, keys=FixtureKeys(), types=types_for_testkit())  # fmt: skip

    async def remember(*_: Any) -> None:
        return None

    attempt = network.attempt(
        tenant_id=tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=HttpCall,
        simulated=False, remember=remember, beat=lambda: None, iteration_key="l:2", attempt=3,
    )  # fmt: skip
    try:
        await attempt.connection(cid)
        await attempt.connection(cid)
    finally:
        await attempt.aclose()
    assert [(r["iteration_key"], r["attempt"]) for r in await _records(owner_sessionmaker)] == [("l:2", 3)]


async def test_a_simulated_attempt_records_nothing(owner_sessionmaker, worker_sessionmaker) -> None:
    """A simulation opens no connection (`SimulationSendsNothing`): there's nothing it used."""
    tenant = uuid.uuid4()
    await seed_step(owner_sessionmaker, named=[None], tenant=tenant)
    cid = await add_connection(owner_sessionmaker, tenant, config={"base_url": "https://dewpoint.test:1"})
    seeded = await seed_step(owner_sessionmaker, named=[cid], tenant=tenant, node_type="testkit.http_call@1")
    network = Network(guard=guard({}, []), connections=DbConnections(worker_sessionmaker),
                      sessionmaker=worker_sessionmaker, keys=FixtureKeys(), types=types_for_testkit())  # fmt: skip

    async def remember(*_: Any) -> None:
        return None

    attempt = network.attempt(
        tenant_id=tenant, run_id=seeded.run, step_id=seeded.step, root_run_id=seeded.run, node=HttpCall,
        simulated=True, remember=remember, beat=lambda: None,
    )  # fmt: skip
    with pytest.raises(SimulationSendsNothing):
        await attempt.connection(cid)
    await attempt.aclose()
    assert await _records(owner_sessionmaker) == []
```

`Network`'s `ssl_context` defaults to None, and `guard(answers, entries=…)` is `tests/support/netfakes.py`'s: neither
attempt here sends anything.

- [ ] **Step 2: Run them to see them fail**

Run: `… $PY -m pytest -q tests/apps/worker/test_activities_network.py -k "record or twice or simulated"`
Expected: FAIL: no rows; `Network.attempt()` takes no `iteration_key`.

- [ ] **Step 3: Write the record**

In `backend/src/dewpoint/apps/worker/network.py`:
- add `from sqlalchemy.dialects.postgresql import insert`, `from dewpoint.core.models.runs import RunStepConnection`,
  `from dewpoint.engine.canonical import canonical_json` (check each isn't already imported);
- give `StoredConnection` a last field `name: str = ""`;
- add to `ConnectionSource`:

```python
    async def opened(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, step_id: uuid.UUID, iteration_key: str, attempt: int,
        connection_id: uuid.UUID, stored: StoredConnection,
    ) -> None: ...  # fmt: skip
```

- in `DbConnections.load`, select `ConnectionRow.name` too and build `StoredConnection(row[0], dict(row[1]), row[2],
  row[3], row[4])`;
- add to `DbConnections`:

```python
    async def opened(
        self, tenant_id: uuid.UUID, run_id: uuid.UUID, step_id: uuid.UUID, iteration_key: str, attempt: int,
        connection_id: uuid.UUID, stored: StoredConnection,
    ) -> None:  # fmt: skip
        """Records that a step attempt opened this connection, as it was (B7; 4c-2a ruling 8): what a sample says it ran
        with. Once per attempt and connection, however often the node opens it. Its config is non-secret; past
        CONTEXT_BYTES it isn't kept."""
        context = dict(stored.config) if len(canonical_json(stored.config)) <= CONTEXT_BYTES else {}
        async with self.sessionmaker() as s, s.begin():
            await tenant_scope(s, tenant_id)
            await s.execute(
                insert(RunStepConnection)
                .values(
                    tenant_id=tenant_id, run_id=run_id, step_id=step_id, iteration_key=iteration_key, attempt=attempt,
                    connection_id=connection_id, type=stored.type, name=stored.name, revision=stored.revision,
                    context=context,
                )
                .on_conflict_do_nothing()
            )  # fmt: skip
```

- add `CONTEXT_BYTES = 4096` near the module's other constants;
- give `Network.attempt` two keyword parameters, `iteration_key: str = ""` and `attempt: int = 1`, passed on to
  `AttemptNetwork`, whose `__init__` takes and keeps them (`self.iteration_key`, `self.attempt`);
- in `AttemptNetwork.connection`, after `await self._remember(...)` and before `return unsealed.opened(...)`:

```python
        try:  # before the node can use it: a sample says which connection, as it was (B7)
            await self.network.connections.opened(
                self.tenant_id, self.run_id, self.step_id, self.iteration_key, self.attempt, connection_id, stored
            )
        except Exception as e:
            if unavailable(e):  # the database didn't answer: nothing was sent
                raise NotSent() from None
            raise
```

In `backend/src/dewpoint/apps/worker/activities.py`, `run_step`'s `network.attempt(...)` gains
`iteration_key=step.iteration_key, attempt=step.attempt`.

- [ ] **Step 4: Run them to see them pass, then the worker's tests**

Run: `… $PY -m pytest -q tests/apps/worker/test_activities_network.py`, then `… $PY -m pytest -q -n auto tests/apps/worker tests/engine/replay`
Expected: PASS; the golden replays unchanged (nothing in workflow code moved).

- [ ] **Step 5: Lint, types; commit**

```bash
git add backend/src/dewpoint/apps/worker/network.py backend/src/dewpoint/apps/worker/activities.py \
  backend/tests/apps/worker/test_activities_network.py
git commit -m "feat(worker): each attempt records the connections it opens, as they were (4c-2a, B7)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: A step's newest sample

**Files:**
- Create: `backend/src/dewpoint/core/runs/samples.py`
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`SampleConnectionOut`, `SampleConnectionsOut`, `SampleOut`,
  `SamplesOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`GET …/draft/samples`)
- Modify: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts` (regenerated)
- Create: `backend/tests/core/runs/test_samples.py`
- Modify: `backend/tests/apps/api/test_draft_data.py`, `backend/tests/apps/api/test_workflows.py`,
  `backend/tests/apps/api/test_openapi.py`

**Interfaces:**
- Consumes: `RunStepConnection`, `runs_workflow_recent` (Task 8); the worker's records (Task 9).
- Produces:
  - `samples.SCAN_RUNS = 200`; `samples.UsedConnection(connection_id, type, name, revision, current_revision,
    context)` with `.state -> Literal["unchanged", "changed", "deleted"]`; `samples.Sample(run_id, run_kind, mode,
    version_id, version_number, iteration_key, attempt, captured_at, output, node, connections, names_connection)`;
  - `samples.newest(s, tenant_id, workflow_id, step_id, *, iteration_key: str | None, at: Cutoff) -> Sample | None`;
  - `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/samples?node=[&iteration=]` → `SamplesOut
    {draft_revision, node, sample}`.

- [ ] **Step 1: Write the failing core tests**

Create `backend/tests/core/runs/test_samples.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A step's newest sample (B7; 4c-2a rulings 9, 10): which run, which row, which connections, within retention and
the tenant."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from dewpoint.core.db import tenant_scope
from dewpoint.core.retention.cutoff import cutoff
from dewpoint.core.runs import samples
from tests.support.connections import Seeded, add_connection, seed_step

NOW = datetime.now(UTC)


async def _run(
    owner: Any, seeded: Seeded, *, status: str = "succeeded", ago: int = 0, mode: str = "live",
    parent: uuid.UUID | None = None,
) -> uuid.UUID:  # fmt: skip
    """Another run of `seeded`'s workflow and version, queued `ago` minutes back; a sub-flow's when it has a parent."""
    run = uuid.uuid4()
    async with owner() as s, s.begin():
        wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
        await s.execute(
            text(
                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, ended_at, "
                "kind, parent_run_id) values (:i, :t, :w, :v, :m, :st, :q, :e, :k, :p)"
            ),
            {"i": run, "t": seeded.tenant, "w": wf, "v": seeded.version, "m": mode, "st": status,
             "q": NOW - timedelta(minutes=ago), "e": None if status == "running" else NOW - timedelta(minutes=ago),
             "k": "run" if parent is None else "subflow", "p": parent},
        )  # fmt: skip
    return run


async def _row(owner: Any, seeded: Seeded, run: uuid.UUID, *, iteration: str = "", attempt: int = 1,
               status: str = "succeeded", output: Any = None) -> None:  # fmt: skip
    async with owner() as s, s.begin():
        await s.execute(
            text(
                "insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, "
                "ended_at, output_preview) values (:t, :r, :s, :i, :a, 'call', :st, :e, cast(:o as jsonb))"
            ),
            {"t": seeded.tenant, "r": run, "s": seeded.step, "i": iteration, "a": attempt, "st": status, "e": NOW,
             "o": json.dumps(output if output is not None else {"n": attempt})},
        )  # fmt: skip


async def _newest(api: Any, seeded: Seeded, iteration: str | None = None) -> samples.Sample | None:
    async with api() as s, s.begin():
        await tenant_scope(s, seeded.tenant)
        wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": seeded.run})).scalar_one()
        return await samples.newest(s, seeded.tenant, wf, seeded.step, iteration_key=iteration,
                                    at=await cutoff(s, seeded.tenant))  # fmt: skip


async def test_takes_the_newest_succeeded_row_of_an_ended_run(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])  # its own run is still running: never a candidate
    old, new = await _run(owner_sessionmaker, seeded, ago=10), await _run(owner_sessionmaker, seeded, ago=5)
    failed = await _run(owner_sessionmaker, seeded, ago=1)
    await _row(owner_sessionmaker, seeded, old, output={"v": "old"})
    await _row(owner_sessionmaker, seeded, new, output={"v": "new"})
    await _row(owner_sessionmaker, seeded, failed, status="failed")
    await _row(owner_sessionmaker, seeded, seeded.run, output={"v": "running"})
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and found.run_id == new and found.output == {"v": "new"}


async def test_takes_the_first_iteration_by_number_not_by_text(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    run = await _run(owner_sessionmaker, seeded)
    for key in ("l:10", "l:2"):
        await _row(owner_sessionmaker, seeded, run, iteration=key, output={"k": key})
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and found.iteration_key == "l:2"
    asked = await _newest(api_sessionmaker, seeded, iteration="l:10")
    assert asked is not None and asked.output == {"k": "l:10"}


async def test_takes_the_highest_attempt(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    run = await _run(owner_sessionmaker, seeded)
    await _row(owner_sessionmaker, seeded, run, attempt=1, status="failed")
    await _row(owner_sessionmaker, seeded, run, attempt=2)
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and found.attempt == 2


async def test_answers_a_sub_flows_run_of_this_workflow(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    parent = await _run(owner_sessionmaker, seeded, ago=20)  # any root run will do as the parent here
    child = await _run(owner_sessionmaker, seeded, parent=parent)
    await _row(owner_sessionmaker, seeded, child)
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None and (found.run_id, found.run_kind) == (child, "subflow")


async def test_never_answers_from_a_run_past_retention(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    run = await _run(owner_sessionmaker, seeded, ago=60 * 24 * 400)  # ended 400 days ago: past any retention
    await _row(owner_sessionmaker, seeded, run)
    assert await _newest(api_sessionmaker, seeded) is None


async def test_never_answers_another_tenants_run(owner_sessionmaker, api_sessionmaker) -> None:
    mine, theirs = await seed_step(owner_sessionmaker, named=[None]), await seed_step(owner_sessionmaker, named=[None])
    await _row(owner_sessionmaker, theirs, await _run(owner_sessionmaker, theirs))
    async with owner_sessionmaker() as s:
        their_wf = (await s.execute(text("select workflow_id from runs where id = :r"), {"r": theirs.run})).scalar_one()
    async with api_sessionmaker() as s, s.begin():
        await tenant_scope(s, mine.tenant)
        at = await cutoff(s, mine.tenant)
        for tenant in (mine.tenant, theirs.tenant):  # their ids, asked from my tenant: row-level security and the filter
            assert await samples.newest(s, tenant, their_wf, theirs.step, iteration_key=None, at=at) is None
    assert await _newest(api_sessionmaker, theirs) is not None  # and from theirs, it's there


async def test_says_what_each_connection_is_now(owner_sessionmaker, api_sessionmaker) -> None:
    seeded = await seed_step(owner_sessionmaker, named=[None])
    same = await add_connection(owner_sessionmaker, seeded.tenant)
    changed = await add_connection(owner_sessionmaker, seeded.tenant)
    gone = await add_connection(owner_sessionmaker, seeded.tenant)
    run = await _run(owner_sessionmaker, seeded)
    await _row(owner_sessionmaker, seeded, run)
    async with owner_sessionmaker() as s, s.begin():
        for cid in (same, changed, gone):
            await s.execute(
                text("insert into run_step_connections (tenant_id, run_id, step_id, iteration_key, attempt, "
                     "connection_id, type, name, revision) values (:t, :r, :s, '', 1, :c, 'testkit', 'Then', 1)"),
                {"t": seeded.tenant, "r": run, "s": seeded.step, "c": cid},
            )  # fmt: skip
        await s.execute(text("update connections set revision = 2, name = 'Renamed' where id = :c"), {"c": changed})
        await s.execute(text("update connections set name = 'Renamed too' where id = :c"), {"c": same})
        await s.execute(text("delete from connections where id = :c"), {"c": gone})
    found = await _newest(api_sessionmaker, seeded)
    assert found is not None
    states = {c.connection_id: (c.state, c.name) for c in found.connections}
    assert states == {same: ("unchanged", "Renamed too"), changed: ("changed", "Renamed"), gone: ("deleted", "Then")}
```

`seed_step` gives a run whose status is `running`; `_run` adds ended ones. Check before running: the `Seeded` export from
`tests/support/connections.py` and `runs.queued_at`'s type. Retention's default is 30 days
(`core/retention/policy.py`), so 400 is past it; `workflow_versions.connection_ids` is an array, not a key, so a
connection deletes.

- [ ] **Step 2: Run them to see them fail**

Run: `… $PY -m pytest -q tests/core/runs/test_samples.py`
Expected: FAIL: `dewpoint.core.runs.samples` doesn't exist.

- [ ] **Step 3: Write the query**

Create `backend/src/dewpoint/core/runs/samples.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A step's newest sample (sub-project 4, B7; 4c-2a rulings 9, 10): the preview of its output in an ended run of its
workflow, with the version it ran as and the connections it opened, so the editor can say whether it still
represents the draft. Only API reads use it, within the tenant's retention (core/retention/cutoff.py)."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Integer, cast, func, select, true
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from dewpoint.core.models.connections import Connection
from dewpoint.core.models.runs import Run, RunStep, RunStepConnection
from dewpoint.core.models.workflows import WorkflowVersion
from dewpoint.core.retention.cutoff import Cutoff, kept

SCAN_RUNS = 200  # the newest ended runs of a workflow a sample is looked for in (ruling 9)


@dataclass(frozen=True)
class UsedConnection:
    connection_id: uuid.UUID
    type: str
    name: str  # its name now, or as recorded when it's gone
    revision: int  # as the attempt used it
    current_revision: int | None  # None: deleted since
    context: Mapping[str, Any]

    @property
    def state(self) -> Literal["unchanged", "changed", "deleted"]:
        if self.current_revision is None:
            return "deleted"
        return "unchanged" if self.current_revision == self.revision else "changed"


@dataclass(frozen=True)
class Sample:
    run_id: uuid.UUID
    run_kind: str
    mode: str
    version_id: uuid.UUID
    version_number: int
    iteration_key: str
    attempt: int
    captured_at: datetime | None
    output: Any  # the stored preview: redacted and cut where it was (engine-core spec §8)
    node: Mapping[str, Any] | None  # the step as its version wrote it
    connections: tuple[UsedConnection, ...]
    names_connection: bool  # the step, as its version wrote it, names one of the version's connections


async def newest(
    s: AsyncSession,
    tenant_id: uuid.UUID,
    workflow_id: uuid.UUID,
    step_id: uuid.UUID,
    *,
    iteration_key: str | None,
    at: Cutoff,
) -> Sample | None:
    root = aliased(Run)
    candidates = (
        select(Run.id, Run.kind, Run.mode, Run.workflow_version_id, Run.queued_at)
        .join(root, (root.id == Run.root_run_id) & (root.tenant_id == Run.tenant_id))
        .where(Run.tenant_id == tenant_id, Run.workflow_id == workflow_id, Run.status != "running")
        .where(kept(root.ended_at, at))
        .order_by(Run.queued_at.desc(), Run.id.desc())
        .limit(SCAN_RUNS)
        .subquery("candidates")
    )
    # "l:3/m:10" → {3,10}: the first iteration is the lowest index, by number (`l:2` before `l:10`).
    number = cast(
        func.string_to_array(func.regexp_replace(RunStep.iteration_key, "[a-z][a-z0-9_]*:", "", "g"), "/"),
        ARRAY(Integer),
    )
    picked = (
        select(RunStep.iteration_key, RunStep.attempt, RunStep.ended_at, RunStep.output_preview)
        .where(
            RunStep.run_id == candidates.c.id,
            RunStep.tenant_id == tenant_id,
            RunStep.step_id == step_id,
            RunStep.status == "succeeded",
            *([RunStep.iteration_key == iteration_key] if iteration_key is not None else []),
        )
        .order_by(number, RunStep.attempt.desc())
        .limit(1)
        .lateral("picked")
    )
    found = (
        await s.execute(
            select(
                candidates.c.id, candidates.c.kind, candidates.c.mode, candidates.c.workflow_version_id,
                picked.c.iteration_key, picked.c.attempt, picked.c.ended_at, picked.c.output_preview,
            )
            .select_from(candidates)
            .join(picked, true())
            .order_by(candidates.c.queued_at.desc(), candidates.c.id.desc())
            .limit(1)
        )
    ).first()  # fmt: skip
    if found is None:
        return None
    version = (
        await s.execute(
            select(WorkflowVersion.number, WorkflowVersion.graph, WorkflowVersion.connection_ids).where(
                WorkflowVersion.id == found.workflow_version_id, WorkflowVersion.tenant_id == tenant_id
            )
        )
    ).one()
    nodes = version.graph.get("nodes", []) if isinstance(version.graph, dict) else []
    node = next((n for n in nodes if isinstance(n, dict) and n.get("id") == str(step_id)), None)
    recorded = {str(c) for c in version.connection_ids or ()}
    written = node.get("config") if node is not None else None
    config: dict[str, Any] = written if isinstance(written, dict) else {}
    used = await s.execute(
        select(
            RunStepConnection.connection_id, RunStepConnection.type, RunStepConnection.name,
            RunStepConnection.revision, RunStepConnection.context, Connection.name.label("now_name"),
            Connection.revision.label("now_revision"),
        )
        .outerjoin(
            Connection,
            (Connection.id == RunStepConnection.connection_id) & (Connection.tenant_id == RunStepConnection.tenant_id),
        )
        .where(
            RunStepConnection.run_id == found.id, RunStepConnection.step_id == step_id,
            RunStepConnection.iteration_key == found.iteration_key, RunStepConnection.attempt == found.attempt,
        )
        .order_by(RunStepConnection.connection_id)
    )  # fmt: skip
    return Sample(
        run_id=found.id,
        run_kind=found.kind,
        mode=found.mode,
        version_id=found.workflow_version_id,
        version_number=version.number,
        iteration_key=found.iteration_key,
        attempt=found.attempt,
        captured_at=found.ended_at,
        output=found.output_preview,
        node=node,
        connections=tuple(
            UsedConnection(r.connection_id, r.type, r.now_name if r.now_name is not None else r.name, r.revision,
                           r.now_revision, dict(r.context))  # fmt: skip
            for r in used
        ),
        names_connection=any(isinstance(v, str) and v in recorded for v in config.values()),
    )
```

Check before running: SQLAlchemy's `.lateral()` and `select_from(...).join(lateral, true())` in the installed
SQLAlchemy (2.x), the `Connection` model's module, and that `RunStep.tenant_id` is filtered (RLS also applies).
`core` imports neither `engine` nor `apps` (the import linter's contracts).

- [ ] **Step 4: Run the core tests to see them pass**

Run: `… $PY -m pytest -q tests/core/runs/test_samples.py`
Expected: PASS, 7 tests.

- [ ] **Step 5: Write the route's failing tests**

Append to `backend/tests/apps/api/test_draft_data.py` (add `from sqlalchemy import text` and
`from tests.support.workflows import PROFILE` to its imports):

```python
async def _sampled(owner: Any, base: str, step: uuid.UUID, *, mode: str = "live", output: Any = None) -> str:
    """Publish isn't needed: a version row (as `tests/support/connections.py::seed_step` writes one, from the draft)
    and an ended run with a succeeded row for `step`."""
    tenant, workflow_id = base.split("/")[4], base.split("/")[6]
    version, run = uuid.uuid4(), uuid.uuid4()
    async with owner() as s, s.begin():
        draft = (await s.execute(text("select draft from workflows where id = :w"), {"w": workflow_id})).scalar_one()
        await s.execute(text("insert into cel_profiles(profile) values (:p) on conflict do nothing"), {"p": PROFILE})
        await s.execute(
            text(
                "insert into workflow_versions(id,tenant_id,workflow_id,number,graph,node_refs,engine_abi,cel_profile,"
                "input_schema,output_schema,vars_schema,closure_version_ids,closure_workflow_ids,closure_node_refs,"
                "closure_cel_profiles,closure_depth,graph_hash,version_hash,connection_ids) "
                "values (:v,:t,:w,1,cast(:g as jsonb),array['testkit.echo@1'],1,cast(:p as text),"
                "'{}','{}','{}',array[cast(:v as uuid)],array[cast(:w as uuid)],array['testkit.echo@1'],"
                "array[cast(:p as text)],0,'h','h','{}')"
            ),
            {"v": version, "t": tenant, "w": workflow_id, "g": json.dumps(draft), "p": PROFILE},
        )
        await s.execute(
            text("insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, ended_at) "
                 "values (:r, :t, :w, :v, :m, 'succeeded', now())"),
            {"r": run, "t": tenant, "w": workflow_id, "v": version, "m": mode},
        )  # fmt: skip
        await s.execute(
            text("insert into run_steps (tenant_id, run_id, step_id, iteration_key, attempt, node_key, status, "
                 "ended_at, output_preview) values (:t, :r, :s, '', 1, 'a', 'succeeded', now(), cast(:o as jsonb))"),
            {"t": tenant, "r": run, "s": step, "o": json.dumps(output if output is not None else {"value": 1})},
        )  # fmt: skip
    return str(run)


async def test_answers_a_steps_newest_sample(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        run = await _sampled(owner_sessionmaker, base, nid("a"), output={"value": "[redacted]"})
        r = await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})
    assert r.status_code == 200, r.text
    sample = r.json()["sample"]
    assert (sample["run_id"], sample["mode"], sample["version_number"], sample["attempt"]) == (run, "live", 1, 1)
    assert sample["output"] == {"value": "[redacted]"}  # as stored: the API never unmasks
    assert (sample["type"], sample["same_type"], sample["same_config"], sample["stale"]) == (
        "testkit.echo@1", True, True, False)
    assert sample["connections"] == {"state": "none", "items": []}  # an echo names no connection


async def test_marks_a_sample_stale_when_the_config_differs(app, owner_sessionmaker, api_settings) -> None:
    changed = G().node("a", "testkit.echo@1", {"value": 2}).node("c", "flow.if@1", {"condition": True}).edge("a", "c")
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        await _sampled(owner_sessionmaker, base, nid("a"))
        assert (await c.put(f"{base}/draft", json=changed.data(), headers={"If-Match": "1"})).status_code == 200
        r = await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})
    sample = r.json()["sample"]
    assert r.json()["draft_revision"] == 2 and not sample["same_config"] and sample["stale"]


async def test_says_a_simulated_sample_used_no_connection(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        await _sampled(owner_sessionmaker, base, nid("a"), mode="simulate")
        sample = (await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})).json()["sample"]
    assert sample["mode"] == "simulate" and sample["connections"]["state"] == "simulated"


async def test_has_no_sample_for_a_step_without_one(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await _create(c, tid)
        none_yet = await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})
        not_there = await c.get(f"{base}/draft/samples", params={"node": str(uuid.uuid4())})
    assert none_yet.json()["sample"] is None and not_there.json()["sample"] is None
```

The "unknown" connection state (a step that names a connection, a run before records) is a case of `sample_answer`,
tested directly in Step 7.

Add to `test_permission_matrix`, in the viewer/operator loop:

```python
            assert (await c.get(f"{base}/draft/samples", params={"node": str(nid("a"))})).status_code == 200  # run.view
```

Add `("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/samples")` to `SLICE_4C` in `test_openapi.py`.

`test_workflows.py`'s `GRAPH` names node `a` (`G().node("a", "testkit.echo@1", …)`), so the permission matrix's new rows
ask about a step the draft holds.

- [ ] **Step 6: Run them to see them fail**

Run: `… $PY -m pytest -q tests/apps/api/test_draft_data.py -k sample tests/apps/api/test_openapi.py`
Expected: FAIL: the route answers 404.

- [ ] **Step 7: The answer and the route**

In `backend/src/dewpoint/apps/api/responses.py`:

```python
class SampleConnectionOut(_Answer):
    connection_id: str
    type: str
    name: str  # its name now, or as recorded when it's gone
    revision: int  # as the attempt used it
    current_revision: int | None
    state: Literal["unchanged", "changed", "deleted"]
    context: dict[str, Any]  # its non-secret config, as it was


class SampleConnectionsOut(_Answer):
    """What the sample's attempt used: `recorded` (each one, as it was and as it is now), `none` (the step names
    none), `simulated` (a simulation opens none) or `unknown` (it names one, but the run predates records)."""

    state: Literal["recorded", "none", "simulated", "unknown"]
    items: list[SampleConnectionOut]


class SampleOut(_Answer):
    run_id: str
    run_kind: Literal["run", "subflow", "failure_handler"]
    mode: Literal["live", "simulate"]
    version_id: str
    version_number: int
    iteration_key: str
    attempt: int
    captured_at: str | None
    type: str | None  # the step's type@version in that version
    same_type: bool
    same_config: bool
    output: Any  # the stored preview, `[redacted]` and `[truncated]` where they were (D20)
    connections: SampleConnectionsOut
    stale: bool  # its type, config or a connection differs from the draft's now


class SamplesOut(_Answer):
    """A step's newest sample (B7), against the saved draft at this revision."""

    draft_revision: int
    node: str
    sample: SampleOut | None
```

In `backend/src/dewpoint/apps/workflow_ops.py`:

```python
def draft_node(draft: Any, node: uuid.UUID) -> Mapping[str, Any] | None:
    """The step as the saved draft writes it, read without parsing: a draft that doesn't parse still has steps."""
    nodes = draft.get("nodes") if isinstance(draft, Mapping) else None
    found = (n for n in nodes or () if isinstance(n, Mapping) and n.get("id") == str(node))
    return next(found, None)


def sample_answer(found: samples.Sample, drafted: Mapping[str, Any]) -> dict[str, object]:
    """B7's answer (4c-2a ruling 10): the sample, and whether it still represents the draft's step."""
    ran = found.node or {}
    same_type, same_config = ran.get("type") == drafted.get("type"), ran.get("config") == drafted.get("config")
    if found.connections:
        state = "recorded"
    elif found.mode == "simulate":
        state = "simulated"
    elif found.names_connection:
        state = "unknown"
    else:
        state = "none"
    return {
        "run_id": str(found.run_id), "run_kind": found.run_kind, "mode": found.mode,
        "version_id": str(found.version_id), "version_number": found.version_number,
        "iteration_key": found.iteration_key, "attempt": found.attempt,
        "captured_at": found.captured_at.isoformat() if found.captured_at is not None else None,
        "type": ran.get("type"), "same_type": same_type, "same_config": same_config, "output": found.output,
        "connections": {
            "state": state,
            "items": [
                {"connection_id": str(c.connection_id), "type": c.type, "name": c.name, "revision": c.revision,
                 "current_revision": c.current_revision, "state": c.state, "context": dict(c.context)}
                for c in found.connections
            ],
        },
        "stale": not same_type or not same_config or any(c.state != "unchanged" for c in found.connections),
    }  # fmt: skip
```

(`apps` may import `core`: `from dewpoint.core.runs import samples`.)

In `backend/src/dewpoint/apps/api/routes/workflows.py` (import `SamplesOut`, `cutoff` from
`dewpoint.core.retention.cutoff`, `samples` from `dewpoint.core.runs`):

```python
@router.get("/t/{tenant_id}/workflows/{workflow_id}/draft/samples", response_model=SamplesOut)
async def draft_samples(
    workflow_id: uuid.UUID,
    node: uuid.UUID,
    iteration: str | None = Query(default=None, max_length=2000),
    ctx: TenantContext = Depends(require(P.RUN_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A step's newest sample against the saved draft (B7; 4c-2a rulings 9, 10). Run data: `run.view`, and the
    tenant's retention."""
    wf = await _get(db, ctx, workflow_id)
    drafted = workflow_ops.draft_node(wf.draft, node)
    found = None
    if drafted is not None:
        found = await samples.newest(
            db, ctx.tenant_id, workflow_id, node, iteration_key=iteration, at=await cutoff(db, ctx.tenant_id)
        )
    return {
        "draft_revision": wf.draft_revision,
        "node": str(node),
        "sample": workflow_ops.sample_answer(found, drafted) if found is not None and drafted is not None else None,
    }
```

And a unit test of the four connection states, appended to `backend/tests/apps/api/test_draft_data.py`:

```python
def test_tells_the_four_connection_states() -> None:
    from datetime import UTC, datetime

    from dewpoint.apps.workflow_ops import sample_answer
    from dewpoint.core.runs.samples import Sample, UsedConnection

    step = {"id": "x", "type": "testkit.http_call@1", "config": {"connection": "c1"}}
    base = dict(run_id=uuid.uuid4(), run_kind="run", mode="live", version_id=uuid.uuid4(), version_number=1,
                iteration_key="", attempt=1, captured_at=datetime.now(UTC), output={}, node=step)  # fmt: skip
    used = UsedConnection(uuid.uuid4(), "testkit", "Lab", 1, 2, {})
    cases = {
        "recorded": Sample(**base, connections=(used,), names_connection=True),
        "unknown": Sample(**base, connections=(), names_connection=True),
        "none": Sample(**base, connections=(), names_connection=False),
    }
    for state, sample in cases.items():
        assert sample_answer(sample, step)["connections"]["state"] == state  # type: ignore[index]
    assert sample_answer(cases["recorded"], step)["stale"]  # its connection changed since
    simulated = Sample(**{**base, "mode": "simulate"}, connections=(), names_connection=True)
    assert sample_answer(simulated, step)["connections"]["state"] == "simulated"  # type: ignore[index]
```

- [ ] **Step 8: Run them to see them pass; regenerate the client; checks; commit**

Run: `… $PY -m pytest -q tests/apps/api/test_draft_data.py tests/apps/api/test_openapi.py tests/apps/api/test_workflows.py tests/core/runs`
Expected: PASS.
Regenerate `openapi.json` and `schema.d.ts` (Task 6 Step 5), then `check:api`, `typecheck`, `test` from `frontend/`:
PASS. Then `ruff format src tests && ruff check src tests`, mypy, the import linter: no findings.

```bash
git add backend/src/dewpoint/core/runs/samples.py backend/src/dewpoint/apps/workflow_ops.py \
  backend/src/dewpoint/apps/api/responses.py backend/src/dewpoint/apps/api/routes/workflows.py \
  backend/tests/core/runs/test_samples.py backend/tests/apps/api/test_draft_data.py \
  backend/tests/apps/api/test_workflows.py backend/tests/apps/api/test_openapi.py \
  frontend/src/api/openapi.json frontend/src/api/schema.d.ts
git commit -m "feat(api): a step's newest sample, with what it ran as and with (4c-2a, B7)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Every check, the ledger, the final checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` (§5: B6 and B7's rows say where they were built)

- [ ] **Step 1: The whole backend suite, the frontend's checks, CodeQL**

Ask the owner before the backend suite (about 12 minutes with `-n auto`). Then:
- `… $PY -m pytest -q -n auto` from `backend/` (with the CEL gate tests too, as CI runs them);
- ruff (format and check), mypy, the import linter;
- the backend's OpenAPI diff against `frontend/src/api/openapi.json` (CI's step), and from `frontend/`:
  `check:api`, `lint`, `typecheck`, `test`, `build`;
- local CodeQL on the branch's head (`scratchpad/codeql/scan.sh <sha>`): no new alert.
Expected: every one passes. A failure is read and fixed test-first, or reported as it is: never a claim that every
check passes when one didn't. The browser gate isn't run: no screen changed (the frontend's unit suite and build
are).

- [ ] **Step 2: The outline's rows**

In the outline's §5 table, B6's row adds "Built in 4c-2a: `GET …/draft/scope`, and validate's `conditional_steps`"
and B7's adds "Built in 4c-2a: `GET …/draft/samples`; slot 0045 `run_step_connections`".

- [ ] **Step 3: The ledger**

Append `### 4c-2a, milestone 3 and the final checkpoint (date)`: the tasks' commits, each check's result as run (the
suite's counts), every mid-slice ruling, anything deferred. Commit (`docs(editor-4): 4c-2a final checkpoint`).

- [ ] **Step 4: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch against this plan (its Review Focus first),
the outline's B6/B7 rows and engine-core spec §4.3. Critical and important findings are fixed test-first, once;
minor ones are listed. Then **stop**: the summary to the owner names what's built, the checks as run, the rulings
proposed and made, and asks for the owner's word on push and a PR (nothing is pushed before it). CI on the PR runs
the backend (about 12 minutes), the frontend, CodeQL and the Compose e2e: say so before pushing.

