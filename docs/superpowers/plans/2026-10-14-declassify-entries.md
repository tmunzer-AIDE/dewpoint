# Declassify entries: no repeats, and a switch case named by its port (issue #78)

Branch `fix/declassify-entries` from `origin/main` a914a799, on the owner's choice of #78 (2026-10-14). A plan for the
owner's rulings; nothing is built until the owner's go, and nothing is committed without it. Executed inline: the
checkpoint is after the fresh review.

**Goal:** a declassification can't outlive the copy a person removes, and a switch case's declassification can't move
to another case when the cases are reordered outside the editor.

**Architecture:** the validator (`_declassify`, `engine/graph/validate.py`) refuses a repeated entry and checks a switch
case's entry against the case's port, which the entry now names (`DeclassifySite.port`, `engine/graph/model.py`); the
editor writes and keeps that port (`frontend/src/lib/config.ts`) and shows the new diagnostics beside the entry
(`DeclassifyPanel.tsx`). Validator, graph format and editor; the runtime never reads the list.

## Facts (checked 2026-10-14 at a914a799; never from memory)

- `GraphSettings.declassify` is a list of `DeclassifySite(node: UUID, field: str)`, at most 200
  (`engine/graph/model.py:76`, `:114`). `_declassify` (`validate.py`) compares entries as `(node, field)` tuples:
  nothing refuses a repeat, so a repeated entry declassifies its decision after one copy is removed. The node parses to
  a `uuid.UUID`, so any spelling of one id compares equal.
- A switch case's decision site is `/cases/{i}/when` (`_decision_sites`), by index. Case ports are literal, match
  `^[a-z][a-z0-9_]{0,30}$` and are unique within the step (`structure.py` `_dynamic_ports`); edges hang on them.
- The runtime doesn't read the list: every `if` condition and switch case's `when` is a decision (`execution.py`
  `_decision`), given back plain when tainted. The list is publish's authorization: publish refuses an unlisted tainted
  decision and a stale entry, requires `workflow.declassify` when the list isn't empty, and audits each listed site
  with what it reveals (§4.3). So a re-targeted entry declassifies a decision no one chose, under someone's permission.
- The editor (since 4c-2b, #86) has a Declassify panel: it lists entries by index with Remove (one row), and adds an
  entry only for an undecided decision, once (`config.ts` `declassify`). Since #77 it rewrites a switch case's entry
  when the case moves or goes, and a renamed port carries its edges along (`config.ts`). Repeats come from the API, an
  import or a JSON edit; a reorder by the API keeps the old indexes.
- `Diagnostic.severity` defaults to `error`: an error refuses publish; a draft still saves.
- Graph format: models forbid extra keys; `csv` was added in 2b-3 written only when declared ("so hashes stay"),
  without an `ENGINE_ABI` bump, which is for changes to a run's command sequence. `frontend/src/api/openapi.json` must
  equal what the backend serves (CI diffs it; regenerate with `uv run dewpoint api openapi`, then `pnpm gen:api`).

## Proposed rulings

- Ruling 1 (repeats): a repeated entry, the same node (any spelling) and field as an earlier one, is a diagnostic
  `taint.repeated_declassify` at `/settings/declassify/{i}` ("This entry repeats an earlier one: removing one copy
  wouldn't stop declassifying the decision."; fix "Remove it."), an error, so publish refuses it and a draft saves it;
  the first copy counts as before - cost if wrong: a list a client built with repeats publishes only once they're gone.
- Ruling 2 (a switch case named by its port), recommended option A: a switch case's entry names its case's port beside
  the pointer, `{node, field: "/cases/2/when", port: "approved"}`, and counts only while the case at that index has
  that port. Otherwise (no port, another case's port, a port on an entry that isn't a switch case's) it's a diagnostic
  `taint.case_declassify` ("This entry doesn't name the case at its place: a switch case's decision is declassified by
  its port, so a reordered case keeps or loses its own."; fix "Declassify the case's decision again."), an error, and
  the entry declassifies nothing: a reorder outside the editor is reported, never followed silently - cost if wrong:
  a client reordering cases must rewrite the entries' indexes (the editor does already).
  Option B, for comparison: the entry names the port instead of an index, and the validator finds the case by it: a
  reorder is followed silently, never reported; the pointer stops being a pointer into the config, so every place
  that shows or follows an entry (the panel's labels, Go to the step, #77's follow code, the audit's field) translates.
- Ruling 3 (entries already written): a switch case's entry without a port, in a draft today, gets ruling 2's
  diagnostic at its next validate or publish; the person declassifies the decision again in the editor, which writes
  the port. Published versions keep what they hold: they're immutable, the runtime doesn't read the list, and their
  audit entries name a version where each index is fixed - cost if wrong: drafts with switch-case entries need one
  re-confirmation each.
- Ruling 4 (the editor): `declassify` writes the case's port for a switch case's decision; renaming a case's port
  rewrites that step's entries naming it in the same edit (one undo step); a move or removal keeps #77's index rewrite,
  the port unchanged; the panel shows ruling 1's and ruling 2's message beside the entry, as it shows a stale one - cost
  if wrong: none.
- Ruling 5 (format and ABI): `port` is optional in the model (`^[a-z][a-z0-9_]{0,30}$`), written only when set, so a
  document without it keeps its hash; no `ENGINE_ABI` bump (the run's commands don't change; `csv`'s precedent); the
  OpenAPI document and the frontend's types are regenerated - cost if wrong: none.

## Not in scope

- An entry names a site, not its content: editing a declassified decision in place (an `if` condition, a case's
  `when`) keeps its declassification (#78's last note; not proposed).
- The audit's record format (it names the version, where an index is fixed).

## Global constraints

- Test-first, each test watched failing; each protection mutation-checked. Backend: `ruff check`, `ruff format`,
  `ruff check`, `mypy src`, the import contracts. Frontend: `pnpm lint`, `typecheck`, `check:api`, `test`, `build`.
- A diagnostic never quotes a value. Commands: the backend through the borrowed venv
  `~/4_dev/mist_dewpoint-celbackport/backend/.venv` (its `uv.lock` is a914a799's) with `PYTHONPATH=src`, from
  `backend/`.

## Review focus (inputs no rule above names; each pinned by a test in the task that owns it)

1. One node written in two UUID spellings, same field: a repeat - Task 1.
2. A repeat of a stale entry: the repeat reported as a repeat, the first copy as stale; never two copies counted - Task 1.
3. Cases reordered through the API with the entries untouched: each moved entry reported (`taint.case_declassify`)
   and its case's decision undeclassified, never declassified by another case's entry - Task 2.
4. A port renamed in the editor: its entry still counts; a whole-list JSON edit renaming a port: its entry reported,
   never kept on another case - Task 3.
5. The 200-entry cap and a port on an `if`'s, a loop's or a filter's entry: reported, never a crash - Tasks 1 and 2.

## Tasks

### Task 1: repeats (`engine/graph/validate.py`)

**Files:** modify `backend/src/dewpoint/engine/graph/validate.py` (`_declassify`); test
`backend/tests/engine/graph/test_validate_declassify.py`.

- [ ] Tests: a repeated entry (and one in another UUID spelling) gives `taint.repeated_declassify` at its own index,
  the first copy still counting (the decision isn't reported undeclassified); a repeat of a stale entry gives both
  codes, one each; 200 entries, all distinct, publish clean. Watch them fail.
- [ ] Code, in `_declassify`: walk the entries once, keeping the first of each `(node, field)`; a later one is the
  diagnostic and doesn't count; the undeclassified and stale checks read the kept entries, by their own indexes.
- [ ] Mutation-check: the repeat check removed; a repeat counted; the first copy dropped instead.

### Task 2: a switch case named by its port (`model.py`, `validate.py`)

**Files:** modify `backend/src/dewpoint/engine/graph/model.py` (`DeclassifySite.port`, written only when set),
`validate.py` (`_declassify`); tests `test_validate_declassify.py`, `backend/tests/engine/graph/test_model.py`.

- [ ] Tests: an entry with its case's port counts; with none, with another case's port, after the cases are reordered
  with the entry untouched, and with a port on an `if`'s entry: `taint.case_declassify` at its index, the case's
  tainted decision reported undeclassified; a document without `port` round-trips byte for byte (its hash kept); a
  port outside the pattern is refused by the model (as the step's own ports are). Watch them fail.
- [ ] Code: `port: str | None = Field(default=None, pattern=PORT_PATTERN)` with a serializer dropping it when unset;
  `_declassify` reads the case's port from the step's config at the entry's index (the field parsed as
  `/cases/{i}/when`), compares, reports, and counts only a match.
- [ ] Mutation-check: the comparison removed; a port-less switch entry counted; the serializer writing `port: null`.

### Task 3: the editor (`frontend/src/lib/config.ts`, `DeclassifyPanel.tsx`)

**Files:** modify `frontend/src/lib/config.ts` (`declassify`, the port rename), `frontend/src/routes/editor/
DeclassifyPanel.tsx`, `frontend/src/api/openapi.json` and `schema.d.ts` (regenerated); tests `config.test.ts`,
`DeclassifyPanel.test.tsx`.

- [ ] Tests: declassifying a switch case's decision writes its port; renaming the case's port rewrites the entry (one
  undo step) and leaves another step's entries alone; moving a case keeps the port, its index followed (#77); the panel
  shows `taint.repeated_declassify`'s and `taint.case_declassify`'s message beside the entry. Watch them fail.
- [ ] Code, then the OpenAPI document regenerated and `pnpm gen:api`; `pnpm check:api`, lint, typecheck, test, build.

### Task 4: the spec and this record

- [ ] Engine 2b spec §4.3: entries are distinct; a switch case's entry names its port and counts only while the case at
  its index has it (rulings 1 to 3). This plan's record: the runs, the review, the checkpoint.

Then a fresh-context review hunting a declassification that counts for a decision no one chose, fixes test-first, the
affected suites (backend `tests/engine/graph`, `tests/apps/api`; frontend all), gitleaks, local CodeQL, a checkpoint;
the full suite, commits, push and PR each on the owner's go.

## Build (2026-10-14, on the owner's "go, build it with option A"; uncommitted until the owner's go)

Tasks 1 to 4 built test-first at a914a799, each test watched failing, each protection mutation-checked (24 mutants,
all killed; three frontend survivors first, each pinned by a new test):
- Task 1 (`_declassify`): repeats by `(node, field)`, the node parsed so any spelling compares equal; the first copy
  counts; the 200-entry cap pinned; 4 mutants killed.
- Task 2 (`DeclassifySite.port`, written only when set; `_case_ports`): an entry with its case's port counts; none,
  another case's, a reorder with the entry untouched, and a port on an `if`'s entry are `taint.case_declassify` and
  declassify nothing; the model refuses a port outside the pattern; the worker's handle test names its case's port;
  7 mutants killed.
- Task 3 (`config.ts`, `DeclassifyPanel.tsx`): `declassify` writes a switch case's port, and gives an entry without
  it (or naming another case) the case's port again, since re-declassifying is how a person confirms such an entry
  (a no-op on an existing entry would leave no way to); `renamePort` rewrites the renamed case's entry only; the panel
  reads an entry's own diagnostic (stale, repeated, misnamed) before saying what its decision reveals: a repeat used
  to say "Reveals …" as its first copy did; the OpenAPI document and the types regenerated (only `port` and the
  model's description changed); 13 mutants killed.
- Task 4: spec §4.3 (a bullet for rulings 1 to 3 and 5) and `docs/operations/deployment.md` (the two codes).

Runs: backend `tests/engine/graph`, `tests/apps/api`, `test_workflow_ops`, the worker's handle tests and
`tests/core/workflows`: 1,188 passed. Frontend (dependencies cloned from a lock-matched worktree, nothing installed):
lint, typecheck, `check:api`, 1,000 tests, build. Ruff, format, `mypy src`, the 11 import contracts; the served
OpenAPI document equals `frontend/src/api/openapi.json`.

A fresh-context review of the build (2026-10-14): no fail-open path on publish (34 probe graphs: entries swapped
between cases, cases reordered, removed or added by the API, repeats and misnamed entries mixed, odd pointers, ports
on other sites, deleted and retyped steps, the cap, malformed `cases`); hashes byte-identical for graphs without a
port; the OpenAPI document matches. Two Medium, three Low, all fixed test-first and mutation-checked (6 mutants):
- Medium: the editor hid a decision whenever any entry had its node and field, whatever the port (`Editor.tsx`), so
  a port-less entry (a draft written before #78, or one an API reorder left) offered no "Declassify this decision"
  and ruling 3's re-confirmation was out of reach. An entry now lists its decision only naming the case's port
  (`casePort`, exported); an Editor test re-declassifies such an entry and the saved draft carries the port.
- Medium: `casePort` wrote any string, so a case's port the format refuses (`Approved`, set by a JSON edit) made the
  draft unsavable; it now writes only a port matching the format's pattern.
- Low: a case without a literal port (missing, computed) gave a port-less entry nothing to mismatch, so it counted in
  the validate answer (publish refused it for the step's structure anyway); every switch case's entry now needs a
  port equal to its case's.
- Low: an entry naming a decision that isn't there (a deleted step, past the cases' end) with a port read
  `taint.case_declassify`; it's `taint.stale_declassify` now, the site checked first.
- Low: test gaps: a switch whose cases aren't objects (validated without failing), a repeat naming the case behind a
  first copy that doesn't (never counted).

Runs at the final tree: backend `tests/engine/graph`, `tests/apps/api`, `test_workflow_ops`, the worker's handle
tests and `tests/core/workflows` 1,192 passed; frontend lint, typecheck, `check:api`, 1,003 tests, build; ruff,
format, `mypy src`, the 11 import contracts; the served OpenAPI document equals the frontend's. gitleaks: nothing in
the changed files (the spec's one `generic-api-key` match is main's, its line 1721). Local CodeQL (python): 0; the
JavaScript analysis runs in CI only. Not run: the full suite, the browser e2e.

The owner signed off rulings 1 to 5, with option A for ruling 2 (2026-10-14: "1. yes 2. yes 3. yes 4. yes"), and
authorized the commits, the full suite, push and PR.
