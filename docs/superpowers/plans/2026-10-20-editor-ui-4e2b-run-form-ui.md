# Editor UI 4e-2b: the run form, a CSV file, re-run (the UI) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1, 2026-10-20.** Nothing is built before the owner accepts this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat.

**Goal:** The run form of the run form design §5, against the signed-off D8 boards: a start of the published version
from the Workflows list, the Runs page and the editor, live or simulated, on the version it names; a CSV workflow's
file, uploaded, its columns chosen, every row checked, its errors at a glance; a re-run of a run that ended, its input
kept or changed; and landing on the new run's page, at 1280 and 320 px.

**Architecture:**
- **The calls and the words** (`lib/runForm.ts`): the start, the re-run, the upload (the file's bytes, `text/csv`),
  the check under other columns and the saved columns, as the generated client types them (4e-2a, #130); who may start
  and what can; the key a submission goes under; the values a newer version keeps; a refusal's words, and a file's.
- **The form** (`routes/runs/RunForm.tsx`): a native modal dialog in the Simulate dialog's look, 600 px wide (full
  screen below 640 px). It reads the start form once and starts the version it shows (`expected_version_id`); a
  version published meanwhile is read and shown, the values that still fit kept. Its fields are `startInput`'s.
- **A CSV file** (`routes/runs/useCsvFile.ts`, `CsvFile.tsx`): the upload, the columns proposed and chosen, every row
  checked again under a change (one check at a time, the last change's), the errors grouped by column and problem, the
  first rows once every row passes, why Start waits.
- **Re-run** (`routes/runs/rerun.ts` and the form's `rerun`): the active version's form, the run's input read back
  and prefilled; what the server kept is never shown, and sent back whole while untouched.
- **The ways in:** Start… on a Workflows row, Start a run… on the Runs page (its workflow chosen as the Workflow filter
  chooses one) and in the editor, Re-run… on a run's page; then the new run's page, its name focused (`landing.ts`).

**Tech Stack:** React 19, TanStack Query 5 (query-core 5.103.2), TanStack Router 1.170, openapi-fetch over the
generated `schema.d.ts`, cmdk, Tailwind v4 tokens; Vitest and Testing Library (no jest-dom); Playwright against the
Compose stack, with axe.

**Spec:** `docs/superpowers/specs/2026-10-19-editor-4e2-run-form-design.md`: §5 (the UI), with §3 (the owner's
answers), §6 (4e-2b's tests), §7 (the risks) and §4 (the API 4e-2a built, merged as #130). The boards: "4e-2 Run Form
Mockups" v10 (Main, EntryPoints, CsvStates, Rerun, MoreStates, Narrow320Light, Narrow320Dark).

## How this plan was checked

The plan's code was checked before review on a scratch checkout of main at 11647275, never on a branch. Each
task's diffs were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff and the same tests: they passed;
- after every task, the type check (`tsc -b --noEmit`) and ESLint: silent;
- after the last, the tree matched the prototype the diffs were cut from, file for file (tree 277808e6);
- the 18 diff blocks, taken from this file's own text, are the diffs applied, byte for byte, in order;
- on the final tree: the whole frontend suite (1411 passed, 104 files; main has 1328 in 99), ESLint, the build,
  `check:api`, and CodeQL (javascript-typescript, CLI 2.27.2, javascript-queries 2.4.7, CI's filter: no finding).

The e2e specs (Task 10) were type-checked and linted, not run: they need the Compose stack, which Task 10 asks the
owner about. The executor still runs every step: the check is evidence, not a substitute.

## Global Constraints

- **The frontend only.** No backend change, no migration, no ABI change. The API is 4e-2a's (#130): `check:api`
  passes as it is.
- **No new dependency.** No npm package is added, and there's no third-party JavaScript or CDN asset: everything is
  bundled, under the strict CSP, with no inline script or style.
- **Words first.** Every state is said in words; colour and the hatch only repeat them. Live is orange (D3, D12's
  outline on Start), a simulation slate with the hatch (D2). The boards' copy is used where it exists; the rulings
  below say where it isn't, or where it departs.
- **No AI tells.** No left-border accents, halos, tinted icon tiles or eyebrows (`src/test/aiTells.test.ts`).
- **WCAG 2.2 AA**, light and dark, at 1280 and 320 px: axe in the e2e specs (Task 10); targets at least 24 px; one
  persistent live region, the shell's (`announce`); a refusal is an alert; a disabled Start names its reason
  (`aria-describedby`).
- **Nothing secret shown or sent back.** A sensitive field is a password input; a value the read-back redacted is
  never shown and never sent (`[redacted]`); the preview never shows a sensitive column.
- **No real Mist or SaaS call.** Unit tests stub `fetch`. The e2e specs run control steps only, on the Compose stack;
  nothing leaves the stack (D24: the gate fails a request to another origin).
- **Verify, don't remember.** Each library behaviour relied on was checked in the installed package:
  - query-core 5.103.2: `QueryClient.query` (its `fetchQuery` is deprecated, same code path), with `staleTime: 0` to
    read again;
  - openapi-fetch: a route the schema gives no body takes one through `bodySerializer`; the upload's bytes go as they
    are, with `Content-Type: text/csv`;
  - TanStack Router 1.170: `HistoryState` is declared in `@tanstack/history`, not a direct dependency (ruling 11);
  - jsdom 25: `Blob.arrayBuffer` is missing (a stand-in in `src/test/setup.ts`, beside `text()`'s).
- **The chunks.** The list's first load doesn't carry the form (ruling 30); the run pages and the editor keep their
  own chunks.
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker. Nothing is pushed and no PR is opened
  without the owner's OK in chat. Ask before any local run expected over 10 minutes (the e2e specs on a local Compose
  stack).

## Review Focus

The inputs and conditions most likely to bite a person using this that the design implies but its own lists don't
name. Each is pinned by the test named, in the task that owns the code.

1. **Start pressed again while the start is on its way** (a slow answer, an impatient click). One start, one run. Task
3: `starts
   once however often Start is pressed while the start is sent`.
2. **A version published meanwhile whose form then can't be read** (a dropped connection, a 500). The form stays on
   the version it showed, with the values typed, and says why; nothing started. Task 3: `keeps the form when the
   version published meanwhile can't be read, saying why`.
3. **The Runs page filtered on a workflow that can't start** (switched off, never published). Start a run… asks for
   the workflow, never opens a form that would be refused. Task 4: `asks for the workflow when its filter names one
   that can't start`.
4. **A check that fails** (a 500, the server restarting) after a column changed. The form says the rows weren't
   checked again, and Start waits for a check that passes. Task 6: `says when the rows couldn't be checked again, and
   Start waits for a check`.
5. **A CSV run re-run once its input is gone** (retention passed). The same rows can't be sent: only another file is
   offered, and the form says why. Task 8: `offers only another file once the run's input isn't kept`.

## Rulings (proposed; they join the ledger as 273 onward when the owner accepts the plan)

Each says what was decided, why, and what it costs if wrong. Found while building the prototype the diffs come from.

1. **One plan with milestone pauses:** after Task 4 (a typed start and its ways in), Task 6 (a CSV start) and Task 9
   (re-run, 320 px); then Tasks 10–11 (the browser, every check) and a fresh reviewer, as 4e-1b. Cost: none.
2. **One module for the form's calls and words** (`lib/runForm.ts`). The CSV file is sent as its bytes, read with
   `arrayBuffer()`, never as text: read as text, a byte that isn't UTF-8 would be replaced, and the server's encoding
   check (`csv_encoding`) would never see it. jsdom gets `Blob.arrayBuffer` beside its `text()` stand-in. Cost: none.
3. **One key per submitted form** (`keyFor`): the same body sent again (its answer lost on the way) goes under the
   same key; any change, a newer version's id included, under a new one. Cost: none.
4. **The version shown is the version started.** The form keeps the start form it first read: a later read of the
   query (a refetch elsewhere) never swaps it unseen. Only a `version_changed` refusal or a file checked against
   another version reads it again (`staleTime: 0`). Cost: none.
5. **A newer version keeps what still fits:** each value whose field still exists with the same type
   (`keptValues`), and a staged file with each column's choice whose column still exists, checked again. Cost: none.
6. **The version line** reads "Version 7 · published today 09:12:00 by nadia@corp.test": the time is 4e-1's `when`, to
   the second, and the publisher is the start form's email ("by …" left out once they're gone). The board drew
   "09:12" and a name; users have an email only. Cost: copy.
7. **A refusal in the form's words, its code beside them.** The form words its own codes in the present tense (an
   upload's end, `csv_busy`, `key_unusable`, `forbidden`, a lost answer); any other takes 4e-1's words for why a run
   didn't start (`reasonWords`), else the server's messages, then "Nothing started." The code shows beside the words,
   as the MoreStates board draws it, but for a newer version, a lost answer and a failed save of the columns, which
   the form words whole. The spec (§5.5) extends 4e-1's vocabulary with the new codes; they live with the form
   instead: `version_changed` and an upload's ends are raised at the start, never recorded on a run, so a run's page
   never shows them. Cost: copy.
8. **An input's reasons beside the field they name** (`refusalOf(e, shown)`): a reason at a field the form shows, or
   inside it, beside that field; any other above the buttons, "At <where>: it breaks `rule`."; as JSON, every reason
   above. Cost: none.
9. **The Simulate dialog's field labels and hints are shared** (`labelOf`, `hintOf`, `REQUIRED` move to
   `startInput.tsx`). Cost: none.
10. **Focus goes to the first field once the form is read; Cancel and Close close the native dialog** (`close()`),
    whose close event closes the form and gives focus back to the button that opened it (§5.6). Cost: none.
11. **Landing on the new run:** the form opens the run's page and marks it (`landOn`); the page takes the mark in an
    effect once its run is read, and focuses its name. A page opened any other way keeps the browser's focus. Not
    history state: its type lives in `@tanstack/history`, which the app doesn't depend on directly. Cost: none.
12. **The ways in.** A Workflows row's "Start…" is named "Start a run of <workflow>". The Runs page's "Start a run…"
    opens the Workflow filter's chooser (exported, without Any, its own words when none can start), unless the filter
    names a workflow that can start. The editor's "Start a run…" follows Simulate; whether the workflow can start is
    read from the workflows list (read again after a publish), not the workflow the editor opened (stale after a first
    publish). Cost: one more read in the editor, usually cached.
13. **How a column's choice was proposed** comes from the upload's `default_mapping`: "saved" for each column the
    applied saved columns map, else "same name"; "left out" for a column without one; a choice the person made says
    nothing. The CsvStates board mixes "saved" and "same name" in one file, which the API never proposes (saved
    columns apply whole). Cost: copy.
14. **A column is named by its header,** with its name beneath when they differ; the boards show the name. The header
    is what the file must hold, and what "same name" matches. Cost: copy.
15. **What a column holds,** in words: "Text", "A whole number", "An IP address", "One of a list: FR, DE, ES, IT, GB,
    US…" (its first six values). The board's "A whole number, 1 to 4094": a declaration has no range. Cost: copy.
16. **A file's problems:** the boards' words for a duplicate header, a file too large and a busy server; the others'
    written here ("Save it as UTF-8 and choose it again.", "Fix it and choose it again.", "Choose another file."), each
    with its code. A lost answer: "The server didn't answer: sites.csv wasn't read. Choose it again." Cost: copy.
17. **A file checked again: one check at a time, and only the last change's** (§7). An answer shows only while the
    columns it checked are the ones shown. A check that fails says so ("Change a column to check them again."); an
    upload a start used, past its hour or not found drops the file, with its words and code. Cost: none.
18. **The errors at a glance:** a table of each column's problem (Column, Problem, Rows), "The whole row" for a
    record's own problem (`cell_count`), then every error row by row in a disclosure. The note on the first 100 shows
    only above 100 errors (the board shows it always). Cost: copy.
19. **Every row passing:** "All 2,431 rows pass." in the success colour, the first rows under their headers (the cells
    as written; never a sensitive column, and the note only when the version has one), and the columns folded to
    "Columns: 4 of 5 mapped, as saved · VLAN not used" with Change. Start says the count: "Start the live run · 2,431
    rows". Cost: none.
20. **Saving the columns:** "Save these columns for this workflow's next CSV", for the roles that hold
    `trigger.manage`; saved when Start is pressed, before the start; a failed save starts nothing ("The columns
    couldn't be saved, so nothing started. Start again, or leave them unsaved."). Cost: copy.
21. **Why Start waits,** beside it: "Choose a file first.", "Choose the file's column for every required column
    first.", "The rows are being checked.", "The rows must be checked first.", "Fix the columns marked first.",
    "Every row must pass first." (the board's). Cost: copy beyond the board's one.
22. **Reading and checking are announced** through the shell's live region: "Reading the file…", "Checking every row
    again with these columns…", then the count ("37 errors in 29 of 2,431 rows", "All 2,431 rows pass."). Cost: none.
23. **A file checked against a version published since** the form was read: the form reads the start form again, once
    per version found, says so as a refused start does, and checks the file again under the new version (§5.3).
    Cost: none.
24. **Re-run…** shows on a run's page once the run has ended (a run that never started included), for the roles that
    hold `run.start`; never on a draft simulation, nor on a sub-run. Its form is headed "Re-run 4a2b17e0"; its
    version sentence compares the versions' ids; its mode is the run's. Cost: none.
25. **A re-run's kept values:** a field marked sensitive, and any whose value read back is or holds `[redacted]`, shows
    "Kept from the original run". Untouched, the re-run sends no input. Once any field changes (or Edit as JSON opens),
    the input goes whole: those fields are empty and required, with the spec's words ("Enter it again: a changed input
    is sent whole, and the original's protected values never reach this form."; the board v10 says "sensitive
    values"), and JSON holding the marker is refused. A kept field isn't changed alone, as the board draws it: any
    other change, or Edit as JSON, opens them all. Cost: a workflow whose only field is sensitive changes it through
    Edit as JSON.
26. **A CSV run's same rows** are offered only while its input is kept; its other fields show read only ("Not given"
    when absent). Another file, or a run without rows on a version that reads a CSV, takes the file's flow and the
    fields whole. A version that reads no CSV starts the fields empty, saying why. Cost: none.
27. **A re-run refused `input_not_retained`** turns the form into the `absent` one, its fields emptied, with no alert:
    the Input's words say it. Cost: none.
28. **Below 640 px** the form fills the screen with a Close button (the Narrow320 boards' ✕); its buttons are stacked
    full width, Start first in the page's order as on screen; the columns and the problems are lists, one item each
    ("21 rows · 7, 19, 33, 48, 52 and 16 more"); the preview and every error scroll in their frames. The board's "and
    3 more columns" is read as the board's crop: every column is listed. Cost: none.
29. **The checks:** each task's tests red, then green, with the type check and ESLint; on the final tree the whole
    frontend suite, the build, `check:api` and CodeQL. The browser specs seed their workflows through the API
    (`e2e/seed.ts`, shared with 4e-1b's `runs.spec.ts`) and run on the owner's word, else in CI's e2e job. Cost: none.
30. **The form's code loads when the Workflows list first opens it** (`LazyRunForm`, through 4e-1b's `LazyPage`), in a
    chunk the Runs page, a run's page and the editor share. Imported by the list itself, it put `startInput` and its
    helpers in the first load: built from main 11647275 the entry is 641.5 kB (207.6 kB gzipped); on this plan's final
    tree it's 649.7 kB (210.4 kB), the form a 47.7 kB chunk (16.2 kB), the editor's script 146.6 kB (it was 149.8:
    `startInput` moved to the form's chunk). Cost: "Loading the run form…" the first time, on a slow connection.

Mid-slice rulings start at M113.

## File structure

| File | Responsibility |
|---|---|
| `frontend/src/lib/runForm.ts` | the calls, who may start, the key, a newer version's values, a refusal's words (Task 2); an input's reasons by field (Task 3); a file's problems, what a column holds, stale saved columns (Task 5); the checked file's words (Task 6, Task 9) |
| `frontend/src/test/setup.ts` | jsdom's `Blob.arrayBuffer` (Task 2) |
| `frontend/src/routes/editor/startInput.tsx` | the fields' labels and hints, shared with the Simulate dialog (Task 3) |
| `frontend/src/routes/runs/RunForm.tsx` | the form: typed input (Task 3), Cancel (Task 4), a CSV file (Tasks 5–6), re-run (Tasks 7–8), 320 px (Task 9) |
| `frontend/src/routes/runs/landing.ts` | the new run's page, its name focused (Task 4) |
| `frontend/src/routes/Workflows.tsx`, `routes/runs/LazyRuns.tsx`, `routes/runs/RunsPage.tsx`, `routes/runs/Filters.tsx`, `routes/editor/Editor.tsx` | the ways in, the form loaded on demand from the list (Task 4) |
| `frontend/src/routes/runs/RunPage.tsx` | the landing (Task 4); Re-run… (Task 7) |
| `frontend/src/routes/runs/useCsvFile.ts`, `routes/runs/CsvFile.tsx` | a CSV file: uploaded, its columns (Task 5); checked, its errors, its first rows (Task 6); 320 px (Task 9) |
| `frontend/src/routes/runs/rerun.ts` | a re-run's input: kept values, the marker, the version sentence (Task 7) |
| `frontend/e2e/seed.ts`, `e2e/runForm.spec.ts`, `e2e/fixtures/runs-csv.dewpoint.json`, `playwright.config.ts` | the browser specs (Task 10) |
| `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` | the plan accepted (Task 1), the milestones and the final checkpoint |

## Milestones

1. **Tasks 1–4:** the ledger, the calls and words, the form for typed input, the ways in and the landing. Pause for the
   owner's review.
2. **Tasks 5–6:** a CSV file: its upload and columns, then every row checked, the errors, the preview, saving.
   Pause for the owner's review.
3. **Tasks 7–9:** re-run (typed, then a CSV run), and 320 px. Pause for the owner's review.
4. **Tasks 10–11:** the browser specs, every check, the final checkpoint. Then the final review.

## How to run things

Every command runs from the plan's worktree. `$WT` is that worktree's root.

- **The frontend's locked packages.** From `$WT/frontend`, `npx --offline pnpm@12.6.0 install --frozen-lockfile
  --offline` restores them from the local store, the lockfile untouched. It installs packages, so the owner's OK is
  asked at the start.
- **Tests.** From `$WT/frontend`: `npx --offline pnpm@12.6.0 exec vitest run <files>`. The editor's test file takes
  about 35 s; a task's run, under a minute.
- **A diff.** Copy the block, between its fences, to a file in the plan's workspace. Then, from `$WT`:
  `git apply --check <file> && git apply <file>`. Expected: no output. A diff that doesn't apply means the tree
  differs from what the previous task left: stop and compare, never apply by hand.
- **Static checks.** From `$WT/frontend`: `npx --offline pnpm@12.6.0 exec tsc -b --noEmit` and
  `npx --offline pnpm@12.6.0 exec eslint .`. Expected: no output from either.
- **The whole frontend suite**, at the end: `npx --offline pnpm@12.6.0 exec vitest run` (about a minute), then
  `npx --offline pnpm@12.6.0 build`.
- **The e2e specs** run against the Compose stack, as CI's e2e job does. Locally, building the stack takes long: the
  owner is asked first.
- **Local CodeQL**, at the end: CI's javascript-typescript analysis (CLI 2.27.2, javascript-queries 2.4.7, CI's query
  filter) on a `git archive` of the head; about a minute.

## Executing this plan

- **Inline**, by one implementing agent in one session, with the owner's reviews at the milestone pauses, and a fresh
  independent review at the end. Test-first, as each task's steps say. The owner chooses.
- **The branch** is settled with the owner at the start. The default proposed: `feat/editor-4e2b` from `origin/main`
  (11647275, or later), in its own worktree (`~/4_dev/mist_dewpoint-4e2b`), with the docs branch
  `docs/editor-ui-4e2b-plan` (this plan) merged into it first. A later main is merged in, never rebased.
- **Where the code base differs from a step**, the executor stops at the diff that doesn't apply, adapts it test-first
  and records the difference as a mid-slice ruling in the ledger (M113 onward).
- **Task 1 runs only once the owner has accepted the plan:** it writes the rulings into the ledger as accepted.

---

# Milestone 1 — A typed start, and its ways in

### Task 1: The ledger: 4e-2a merged, this plan accepted

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger section later tasks append to (`### 4e-2b, milestone N`).

- [ ] **Step 1: Append the plan's status**

Run this task only once the owner has accepted the plan. Apply:

```diff
diff --git a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
index ab45bfa7..1df7e546 100644
--- a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
+++ b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
@@ -3515,3 +3515,43 @@ M112. **A tick's codec doesn't list `version_changed`** (CI's backend job on #13
       outcomes. Only a start or a re-run through the API confirms a version, and their refusals are raised, never
       recorded; a schedule's tick confirms none. The test sets it aside, as it does a draft simulation's codes. The
       local broad suites hadn't included this file. Cost if wrong: a tick's outcome reading "refused" for that code.
+
+### 4e-2a merged; the 4e-2b plan accepted (2026-10-20)
+
+The owner merged 4e-2a as #130 (squash 11647275), every check green ("green and merged"); its six deferred minors are
+issue #131. `docs/superpowers/plans/2026-10-20-editor-ui-4e2b-run-form-ui.md`, revision 1: the UI of the run form
+design §5, against the boards "4e-2 Run Form Mockups" v10, one plan with milestone pauses. The owner accepted it: its
+rulings 1–30 join this ledger as 273–302. The frontend only: no backend change, no migration, no ABI change.
+Mid-slice rulings start at M113.
+
+273. **Accepted. One plan with milestone pauses** (plan ruling 1).
+274. **Accepted. One module for the form's calls and words; the CSV file sent as its bytes** (plan ruling 2).
+275. **Accepted. One key per submitted form** (plan ruling 3).
+276. **Accepted. The version shown is the version started** (plan ruling 4).
+277. **Accepted. A newer version keeps what still fits** (plan ruling 5).
+278. **Accepted. The version line: the time to the second, the publisher's email** (plan ruling 6).
+279. **Accepted. A refusal in the form's words, its code beside them** (plan ruling 7).
+280. **Accepted. An input's reasons beside the field they name** (plan ruling 8).
+281. **Accepted. The Simulate dialog's field labels and hints are shared** (plan ruling 9).
+282. **Accepted. Focus on the first field; Cancel and Close give it back to the opener** (plan ruling 10).
+283. **Accepted. Landing on the new run: a mark the run's page takes once its run is read** (plan ruling 11).
+284. **Accepted. The ways in: a Workflows row, the Runs page's chooser, the editor** (plan ruling 12).
+285. **Accepted. How a column's choice was proposed comes from the upload's default** (plan ruling 13).
+286. **Accepted. A column is named by its header** (plan ruling 14).
+287. **Accepted. What a column holds, in words** (plan ruling 15).
+288. **Accepted. A file's problems in words, with their codes** (plan ruling 16).
+289. **Accepted. A file checked again: one check at a time, the last change's** (plan ruling 17).
+290. **Accepted. The errors at a glance, then every error row by row** (plan ruling 18).
+291. **Accepted. Every row passing: the first rows, the columns folded, the count on Start** (plan ruling 19).
+292. **Accepted. Saving the columns before the start; a failed save starts nothing** (plan ruling 20).
+293. **Accepted. Why Start waits, beside it** (plan ruling 21).
+294. **Accepted. Reading and checking are announced** (plan ruling 22).
+295. **Accepted. A file checked against a version published since is checked again under it** (plan ruling 23).
+296. **Accepted. Re-run… on a run that ended, never a draft simulation's nor a sub-run's** (plan ruling 24).
+297. **Accepted. A re-run's kept values: never shown, sent back whole while untouched** (plan ruling 25).
+298. **Accepted. A CSV run's same rows only while its input is kept** (plan ruling 26).
+299. **Accepted. A re-run refused `input_not_retained` turns to the absent form** (plan ruling 27).
+300. **Accepted. Below 640 px: the full-screen form, Start first, lists for the columns and the problems** (plan ruling
+     28).
+301. **Accepted. The checks, and the browser specs on the owner's word** (plan ruling 29).
+302. **Accepted. The form's code loads when the Workflows list first opens it** (plan ruling 30).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): 4e-2a merged, the 4e-2b plan accepted

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The form's calls and words

**Spec:** §4 (4e-2a's routes), §5.1 (who may start, what can), §5.2 (the key, a newer version, the refusals), §5.3
(a file's words, a row's problems, a column's).

**Files:**
- Create: `frontend/src/lib/runForm.ts`, `frontend/src/lib/runForm.test.ts`
- Modify: `frontend/src/test/setup.ts` (jsdom's `Blob.arrayBuffer`)

**Interfaces:**
- Consumes: `client`, `ok`, `ApiError`, `Schemas` (`lib/client.ts`); `StartForm` (`lib/triggers.ts`); `WorkflowRow`
  (`lib/workflows.ts`); `reasonWords` (`lib/runStatus.ts`); `mbOf` (`lib/csv.ts`).
- Produces (`lib/runForm.ts`):
  - types `StartForm` (re-exported), `StartBody`, `RerunBody`, `RunRequest`, `CsvUpload`, `CsvPreview`, `CsvSaved`,
    `Mapping = Record<string, string>`;
  - `startRun(tenantId, workflowId, body, key)`, `rerunRun(tenantId, runId, body, key)`: `Promise<RunRequest>`;
    `uploadCsv(tenantId, workflowId, file: Blob): Promise<CsvUpload>`; `previewCsv(tenantId, workflowId, uploadId,
    mapping): Promise<CsvPreview>`; `saveColumns(tenantId, workflowId, mapping): Promise<CsvSaved>`;
  - `canStart(role)`, `canSaveColumns(role)`, `startable(w)`;
  - `interface Sent { key; body }`, `keyFor(last: Sent | null, body): Sent`;
  - `keptValues(values, from: StartForm, to: StartForm): Map<string, string>`;
  - `interface Refusal { code; words; fields: Record<string, string>; active? }`, `refusalOf(e): Refusal`;
  - `fileWords(code, limits)`, `cellWords(code)`, `mappingWords(code)`.

Each call is typed by the generated client. The upload sends the file's bytes as they are, `text/csv` (ruling 2): the
route declares no body, so they go through a serializer of their own. Starting is for the roles that hold `run.start`
(operator and up), saving the columns for those that hold `trigger.manage` (editor and up); a workflow can start when
it's published, switched on and executable. A submission's key is reused only for the same body (ruling 3); a newer
version keeps a value whose field still exists with the same type (ruling 5). A refusal is worded for the form (ruling
7): a newer version names itself; an input's reasons are keyed by field.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.test.ts b/frontend/src/lib/runForm.test.ts
new file mode 100644
index 00000000..171f759c
--- /dev/null
+++ b/frontend/src/lib/runForm.test.ts
@@ -0,0 +1,137 @@
+// SPDX-License-Identifier: Apache-2.0
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { ApiError } from "./client";
+import {
+  canSaveColumns, canStart, cellWords, fileWords, keptValues, keyFor, mappingWords, previewCsv, refusalOf, rerunRun, saveColumns,
+  startRun, startable, uploadCsv, type StartForm,
+} from "./runForm";  // prettier-ignore
+
+let sent: Request[];
+let bodies: string[];
+beforeEach(() => {
+  sent = [];
+  bodies = [];
+  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
+    const request = input as Request;
+    sent.push(request);
+    bodies.push(await request.clone().text());
+    return new Response(JSON.stringify({ id: "r1" }), { status: 202 });
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+const field = (name: string, type: string, over: object = {}) => ({ name, type, required: false, sensitive: false, ...over });
+const form = (fields: object[], over: Partial<StartForm> = {}): StartForm =>
+  ({ workflow_id: "w1", version_id: "v7", version_number: 7, published_at: "2026-10-20T09:12:00Z", published_by: null, fields, csv: null, ...over }) as StartForm;
+
+describe("the run form's calls (the run form design §5.2, §5.3)", () => {
+  it("starts a run on the version it confirmed, under the submission's key", async () => {
+    await startRun("t1", "w1", { input: { site: "HQ" }, mode: "live", expected_version_id: "v7" }, "k1");
+    expect(new URL(sent[0]!.url).pathname).toBe("/api/v1/t/t1/workflows/w1/runs");
+    expect(sent[0]!.headers.get("Idempotency-Key")).toBe("k1");
+    expect(JSON.parse(bodies[0]!)).toEqual({ input: { site: "HQ" }, mode: "live", expected_version_id: "v7" });
+  });
+
+  it("re-runs a run through its own route, under the submission's key", async () => {
+    await rerunRun("t1", "r0", { mode: "simulate", expected_version_id: "v7" }, "k2");
+    expect(new URL(sent[0]!.url).pathname).toBe("/api/v1/t/t1/runs/r0/rerun");
+    expect(sent[0]!.headers.get("Idempotency-Key")).toBe("k2");
+    expect(JSON.parse(bodies[0]!)).toEqual({ mode: "simulate", expected_version_id: "v7" });
+  });
+
+  it("uploads a file as it is, as text/csv, never as JSON", async () => {
+    await uploadCsv("t1", "w1", new File(["Site\nHQ\n"], "sites.csv", { type: "text/csv" }));
+    expect(new URL(sent[0]!.url).pathname).toBe("/api/v1/t/t1/workflows/w1/csv-uploads");
+    expect(sent[0]!.headers.get("Content-Type")).toBe("text/csv");
+    expect(bodies[0]).toBe("Site\nHQ\n");
+  });
+
+  it("checks a staged file again under other columns, and saves the columns", async () => {
+    await previewCsv("t1", "w1", "u1", { site: "Site" });
+    await saveColumns("t1", "w1", { site: "Site" });
+    expect(sent.map((r) => [r.method, new URL(r.url).pathname])).toEqual([
+      ["POST", "/api/v1/t/t1/workflows/w1/csv-uploads/u1/preview"],
+      ["PUT", "/api/v1/t/t1/workflows/w1/csv-mapping"],
+    ]);
+    expect(bodies.map((b) => JSON.parse(b) as unknown)).toEqual([{ mapping: { site: "Site" } }, { mapping: { site: "Site" } }]);
+  });
+});
+
+describe("who may start, and what can start (§5.1)", () => {
+  it("shows Start to the roles that hold run.start, and the columns' saving to those that manage triggers", () => {
+    expect(["viewer", "operator", "editor", "admin", "owner", undefined].map(canStart)).toEqual([false, true, true, true, true, false]);
+    expect(["viewer", "operator", "editor", "admin", "owner", undefined].map(canSaveColumns)).toEqual([false, false, true, true, true, false]);
+  });
+
+  it("offers a start only where it can go ahead: published, enabled, executable", () => {
+    const w = { active_version_id: "v7", enabled: true, executable: true };
+    expect([w, { ...w, active_version_id: null }, { ...w, enabled: false }, { ...w, executable: false }, { ...w, executable: null }].map(startable))
+      .toEqual([true, false, false, false, false]);  // prettier-ignore
+  });
+});
+
+describe("one key per submitted form (§5.2)", () => {
+  it("sends the same form again under the same key, and a changed one under a new key", () => {
+    const first = keyFor(null, { input: { site: "HQ" } });
+    expect(keyFor(first, { input: { site: "HQ" } })).toBe(first);
+    const changed = keyFor(first, { input: { site: "Lyon" } });
+    expect(changed.key).not.toBe(first.key);
+  });
+});
+
+describe("a newer version's form (§5.2)", () => {
+  it("keeps each value whose field still exists with the same type, and drops the rest", () => {
+    const before = form([field("site", "string"), field("floor", "integer"), field("note", "string")]);
+    const after = form([field("site", "string"), field("floor", "string"), field("vlan", "integer")], { version_id: "v8", version_number: 8 });
+    const typed = new Map([["site", "HQ"], ["floor", "2"], ["note", "x"]]);
+    expect([...keptValues(typed, before, after)]).toEqual([["site", "HQ"]]);
+  });
+});
+
+const refused = (status: number, body: object) => new ApiError(status, (body as { error: string }).error, body);
+
+describe("what a refused start says (§5.2, §5.3)", () => {
+  it("names the version published meanwhile", () => {
+    const r = refusalOf(refused(409, { error: "version_changed", messages: ["…"], active_version_id: "v8", active_version_number: 8 }));
+    expect(r.code).toBe("version_changed");
+    expect(r.active).toEqual({ id: "v8", number: 8 });
+    expect(r.words).toBe(
+      "Version 8 was published while this was open. Nothing started. The form now shows version 8's input, with your values kept where they still fit: check them and start again.",
+    );
+  });
+
+  it("puts an input's reasons beside their fields, and those of no field above the buttons", () => {
+    const r = refusalOf(refused(422, { error: "input_invalid", messages: [
+      "The run's input doesn't match the workflow's input schema at floor: it breaks `type`.",
+      "The run's input doesn't match the workflow's input schema at its root: it breaks `required`.",
+    ] }));  // prettier-ignore
+    expect(r.fields).toEqual({ "field:floor": "Doesn't fit the input: it breaks `type`." });
+    expect(r.words).toBe("The input doesn't fit the workflow's input. Nothing started. At its root: it breaks `required`.");
+  });
+
+  it("words a CSV upload's end, and falls back to 4e-1's words, then the server's", () => {
+    expect(refusalOf(refused(410, { error: "upload_expired" })).words).toBe("The file was kept for an hour, and that hour has passed: choose it again.");
+    expect(refusalOf(refused(409, { error: "upload_consumed" })).words).toBe("This file already started a run: choose it again to start another.");
+    expect(refusalOf(refused(409, { error: "workflow_disabled", messages: ["The workflow is disabled."] })).words).toBe("The workflow is disabled. Nothing started.");
+    expect(refusalOf(refused(409, { error: "a_new_code", messages: ["Its words."] })).words).toBe("Its words. Nothing started.");
+    expect(refusalOf(new TypeError("Failed to fetch")).code).toBe("network");
+  });
+});
+
+describe("a CSV file's words (§5.3)", () => {
+  it("says why a file can't be read, with the workflow's limits", () => {
+    const limits = { max_rows: 10_000, max_bytes: 5 * 1024 * 1024 };
+    expect(fileWords("csv_duplicate_header", limits)).toBe("has two columns with the same name");
+    expect(fileWords("csv_too_many_rows", limits)).toBe("has more than 10,000 rows, this workflow's limit");
+    expect(fileWords("too_large", limits)).toBe("is over 5 MB, this workflow's limit");
+    expect(fileWords("something_new", limits)).toBe("can't be read");
+  });
+
+  it("words each row's problem, and each column's", () => {
+    expect(["required", "cell_count", "not_in_enum", "not_boolean"].map(cellWords)).toEqual([
+      "Missing: a value is required", "Has more or fewer cells than the header", "Not one of the allowed values",
+      "Not true or false (true, yes, 1; false, no, 0)",
+    ]);  // prettier-ignore
+    expect(mappingWords("required_unmapped")).toBe("Required: choose the file's column for it.");
+  });
+});
diff --git a/frontend/src/test/setup.ts b/frontend/src/test/setup.ts
index b7e49f30..9e70a904 100644
--- a/frontend/src/test/setup.ts
+++ b/frontend/src/test/setup.ts
@@ -67,3 +67,18 @@ if (typeof Blob.prototype.text !== "function") {
     },
   });
 }
+// Nor arrayBuffer(): a CSV file is sent as its bytes (the run form, 4e-2).
+if (typeof Blob.prototype.arrayBuffer !== "function") {
+  Object.defineProperty(Blob.prototype, "arrayBuffer", {
+    configurable: true,
+    writable: true,
+    value(this: Blob): Promise<ArrayBuffer> {
+      return new Promise((resolve, reject) => {
+        const reader = new FileReader();
+        reader.onload = () => resolve(reader.result as ArrayBuffer);
+        reader.onerror = () => reject(reader.error ?? new Error("the file couldn't be read"));
+        reader.readAsArrayBuffer(this);
+      });
+    },
+  });
+}
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/runForm.test.ts`

Expected: FAIL: `runForm.test.ts` can't import its module (`Failed to resolve import "./runForm"`; no test runs).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.ts b/frontend/src/lib/runForm.ts
new file mode 100644
index 00000000..6e349188
--- /dev/null
+++ b/frontend/src/lib/runForm.ts
@@ -0,0 +1,183 @@
+// SPDX-License-Identifier: Apache-2.0
+// The run form (editor 4e-2; the run form design §5): its calls, as the generated schema types them (B1); who may
+// start, and what can; the key a submission is sent under; a newer version's form keeping what was typed; and what a
+// refused start or a CSV file says, in words.
+import { ApiError, client, ok, type Schemas } from "./client";
+import { mbOf } from "./csv";
+import { reasonWords } from "./runStatus";
+import type { StartForm } from "./triggers";
+import type { WorkflowRow } from "./workflows";
+
+export type { StartForm };
+export type StartBody = Schemas["StartIn"];
+export type RerunBody = Schemas["RerunIn"];
+export type RunRequest = Schemas["RequestOut"];
+export type CsvUpload = Schemas["CsvUploadOut"];
+export type CsvPreview = Schemas["CsvPreviewOut"];
+export type CsvSaved = Schemas["CsvMappingOut"];
+export type Mapping = Record<string, string>;
+
+const workflow = (tenantId: string, workflowId: string) => ({ tenant_id: tenantId, workflow_id: workflowId });
+
+/** Starts the workflow's published version (§5.2): its request, admitted (202), or an ApiError in the server's words. */
+export const startRun = (tenantId: string, workflowId: string, body: StartBody, key: string): Promise<RunRequest> =>
+  ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/runs", {
+    params: { path: workflow(tenantId, workflowId), header: { "Idempotency-Key": key } }, body,
+  }));  // prettier-ignore
+
+/** Runs a run's workflow again through its own route (§5.4). */
+export const rerunRun = (tenantId: string, runId: string, body: RerunBody, key: string): Promise<RunRequest> =>
+  ok(client.POST("/api/v1/t/{tenant_id}/runs/{request_id}/rerun", {
+    params: { path: { tenant_id: tenantId, request_id: runId }, header: { "Idempotency-Key": key } }, body,
+  }));  // prettier-ignore
+
+/** Stages a CSV file (§5.3): its bytes as they are, `text/csv`, the server reading them as they arrive and checking
+ * their encoding itself (read as text here, a bad byte would be replaced, never refused). The route declares no body (it
+ * reads the stream itself), so the bytes go through a serializer of their own. */
+export async function uploadCsv(tenantId: string, workflowId: string, file: Blob): Promise<CsvUpload> {
+  const bytes = new Uint8Array(await file.arrayBuffer());
+  return ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-uploads", {
+    params: { path: workflow(tenantId, workflowId) },
+    body: bytes as never,
+    bodySerializer: () => bytes,
+    headers: { "Content-Type": "text/csv" },
+  }));  // prettier-ignore
+}
+
+/** A staged file described again under other columns (B11; §5.3). */
+export const previewCsv = (tenantId: string, workflowId: string, uploadId: string, mapping: Mapping): Promise<CsvPreview> =>
+  ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-uploads/{upload_id}/preview", {
+    params: { path: { ...workflow(tenantId, workflowId), upload_id: uploadId } }, body: { mapping },
+  }));  // prettier-ignore
+
+/** The columns saved for the workflow's next CSV (§5.3; `trigger.manage`). */
+export const saveColumns = (tenantId: string, workflowId: string, mapping: Mapping): Promise<CsvSaved> =>
+  ok(client.PUT("/api/v1/t/{tenant_id}/workflows/{workflow_id}/csv-mapping", { params: { path: workflow(tenantId, workflowId) }, body: { mapping } }));
+
+// The roles that hold run.start (operator and up) and trigger.manage (editor and up), as
+// backend/src/dewpoint/core/authz/permissions.py grants them. The UI only hides what the API would refuse.
+const STARTERS = new Set(["owner", "admin", "editor", "operator"]);
+const TRIGGER_MANAGERS = new Set(["owner", "admin", "editor"]);
+export const canStart = (role?: string | null) => !!role && STARTERS.has(role);
+export const canSaveColumns = (role?: string | null) => !!role && TRIGGER_MANAGERS.has(role);
+
+/** Whether a start can go ahead (§5.1): published, enabled, executable. */
+export const startable = (w: Pick<WorkflowRow, "active_version_id" | "enabled" | "executable">) =>
+  w.active_version_id !== null && w.enabled && w.executable === true;
+
+/** A submission: its key and the body it was sent with, as JSON. */
+export interface Sent {
+  key: string;
+  body: string;
+}
+
+/** The key a submission goes under (§5.2): the last one's when the same form is sent again (an answer lost on the
+ * way), else a new one, so a changed form is never taken for a retry. */
+export function keyFor(last: Sent | null, body: unknown): Sent {
+  const text = JSON.stringify(body);
+  return last !== null && last.body === text ? last : { key: crypto.randomUUID(), body: text };
+}
+
+/** What was typed for one version's form, kept for another's (§5.2): each value whose field still exists there with
+ * the same type. */
+export function keptValues(values: ReadonlyMap<string, string>, from: StartForm, to: StartForm): Map<string, string> {
+  const before = new Map(from.fields.map((f) => [f.name, f]));
+  return new Map(
+    to.fields.flatMap((f) => {
+      const prior = before.get(f.name);
+      const typed = values.get(f.name);
+      return prior && typed !== undefined && JSON.stringify(prior.type) === JSON.stringify(f.type) ? [[f.name, typed] as const] : [];
+    }),
+  );
+}
+
+/** A refused start, in words: its code, what the form says, each reason beside the field it names, and for
+ * `version_changed` the version now active. */
+export interface Refusal {
+  code: string;
+  words: string;
+  fields: Record<string, string>;
+  active?: { id: string; number: number };
+}
+
+const AT = /^The run's input doesn't match the workflow's input schema at (.+): it breaks `(.+)`\.$/;
+const NOTHING = "Nothing started.";
+const FORM_WORDS: Record<string, string> = {
+  upload_expired: "The file was kept for an hour, and that hour has passed: choose it again.",
+  upload_consumed: "This file already started a run: choose it again to start another.",
+  upload_not_found: "The file isn't staged any more: choose it again.",
+  csv_busy: `The server is busy reading other files. ${NOTHING} Start again in a moment.`,
+  key_unusable: `The tenant's key can't be read while the tenant is being erased. ${NOTHING}`,
+  forbidden: `Your role can't start runs. ${NOTHING}`,
+  network: "The server didn't answer. Start again: the same form is never started twice.",
+};
+
+export function refusalOf(e: unknown): Refusal {
+  if (!(e instanceof ApiError)) return { code: "network", words: FORM_WORDS.network!, fields: {} };
+  const body = (e.body ?? {}) as { messages?: unknown; active_version_id?: unknown; active_version_number?: unknown };
+  const messages = Array.isArray(body.messages) ? body.messages.filter((m): m is string => typeof m === "string") : [];
+  if (e.code === "version_changed" && typeof body.active_version_id === "string" && typeof body.active_version_number === "number") {
+    const n = body.active_version_number;
+    return {
+      code: e.code, fields: {}, active: { id: body.active_version_id, number: n },
+      words: `Version ${n} was published while this was open. ${NOTHING} The form now shows version ${n}'s input, with your values kept where they still fit: check them and start again.`,
+    };  // prettier-ignore
+  }
+  if (e.code === "input_invalid") {
+    const fields: Record<string, string> = {};
+    const rest: string[] = [];
+    for (const m of messages) {
+      const at = AT.exec(m);
+      if (at && at[1] !== "its root") fields[`field:${at[1]!.split(".")[0]!}`] = `Doesn't fit the input: it breaks \`${at[2]!}\`.`;
+      else rest.push(at ? `At its root: it breaks \`${at[2]!}\`.` : m);
+    }
+    return { code: e.code, fields, words: ["The input doesn't fit the workflow's input.", NOTHING, ...rest].join(" ") };
+  }
+  const own = Object.hasOwn(FORM_WORDS, e.code) ? FORM_WORDS[e.code]! : null;
+  return { code: e.code, fields: {}, words: own ?? `${reasonWords(e.code) ?? (messages.join(" ") || "It was refused.")} ${NOTHING}` };
+}
+
+/** Why a file can't be read (§5.3), after its name: the server names no header, a file's text never in an answer. */
+export function fileWords(code: string, limits: { max_rows: number; max_bytes: number }): string {
+  switch (code) {
+    case "csv_encoding":
+      return "isn't UTF-8 text";
+    case "csv_empty":
+      return "has no header or rows";
+    case "csv_duplicate_header":
+      return "has two columns with the same name";
+    case "csv_malformed":
+      return "has a quote that isn't closed, or a cell split across lines";
+    case "csv_too_many_rows":
+      return `has more than ${limits.max_rows.toLocaleString("en-US")} rows, this workflow's limit`;
+    case "too_large":
+    case "csv_too_large":
+      return `is over ${mbOf(limits.max_bytes)} MB, this workflow's limit`;
+    default:
+      return "can't be read";
+  }
+}
+
+const CELL_WORDS: Record<string, string> = {
+  required: "Missing: a value is required",
+  cell_count: "Has more or fewer cells than the header",
+  not_integer: "Not a whole number",
+  out_of_range: "Out of range",
+  not_number: "Not a number",
+  not_boolean: "Not true or false (true, yes, 1; false, no, 0)",
+  not_mac: "Not a MAC address",
+  not_ip: "Not an IP address",
+  not_cidr: "Not a network in CIDR form",
+  not_in_enum: "Not one of the allowed values",
+};
+/** A row's problem with a cell (or the record as a whole), in words. */
+export const cellWords = (code: string) => (Object.hasOwn(CELL_WORDS, code) ? CELL_WORDS[code]! : `Breaks a rule (${code})`);
+
+const MAPPING_WORDS: Record<string, string> = {
+  required_unmapped: "Required: choose the file's column for it.",
+  unknown_header: "The file has no such column.",
+  header_reused: "Another column already comes from this one.",
+  unknown_column: "This version doesn't read this column.",
+};
+/** What keeps a column's choice from building rows, in words. */
+export const mappingWords = (code: string) => (Object.hasOwn(MAPPING_WORDS, code) ? MAPPING_WORDS[code]! : `Can't be used (${code})`);
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 13 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/runForm.ts frontend/src/lib/runForm.test.ts frontend/src/test/setup.ts
git commit -m "feat(editor): the run form's calls and words (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The form, for typed input

**Spec:** §5.2 (the form), §5.6 (focus, Escape and Cancel); the Main and MoreStates boards.

**Files:**
- Create: `frontend/src/routes/runs/RunForm.tsx`, `frontend/src/routes/runs/RunForm.test.tsx`
- Modify: `frontend/src/routes/editor/startInput.tsx` (`labelOf`, `hintOf`, `REQUIRED` move here),
  `frontend/src/routes/editor/simulation/SimulateDialog.tsx` (takes them)
- Modify: `frontend/src/lib/runForm.ts`, `frontend/src/lib/runForm.test.ts` (`refusalOf`'s `shown`)

**Interfaces:**
- Consumes: Task 2's `startRun`, `keyFor`, `keptValues`, `refusalOf`; `startFormQuery` (`lib/triggers.ts`);
  `InputControl`, `fromFields`, `startValues`, `wholeOf`, `fieldKey` (`routes/editor/startInput.tsx`); `SimBanner`;
  `When`.
- Produces:
  - `RunForm({ tenantId, workflow: { id, name }, draftDiffers?, onStarted(runId), onClose })`;
  - `startInput.tsx`: `REQUIRED`, `labelOf(f)`, `hintOf(f)`;
  - `refusalOf(e, shown?: ReadonlySet<string>)`: a reason at a shown field beside it, any other above (ruling 8).

The form reads the start form once and keeps it (ruling 4): its version line (ruling 6), the draft's note when opened
from the editor, Live or Simulated with their banners and buttons, the fields and Edit as JSON as the Simulate dialog
enters them. Start sends the input, the mode and `expected_version_id` under the submission's key. A newer version is
read again and shown, the values that still fit kept; a refusal stays in the form, its words and code in an alert
(ruling 7), an input's reasons beside their fields.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.test.ts b/frontend/src/lib/runForm.test.ts
index 171f759c..83e24e4c 100644
--- a/frontend/src/lib/runForm.test.ts
+++ b/frontend/src/lib/runForm.test.ts
@@ -100,13 +100,16 @@ describe("what a refused start says (§5.2, §5.3)", () => {
     );
   });
 
-  it("puts an input's reasons beside their fields, and those of no field above the buttons", () => {
-    const r = refusalOf(refused(422, { error: "input_invalid", messages: [
-      "The run's input doesn't match the workflow's input schema at floor: it breaks `type`.",
+  it("puts an input's reasons beside the fields shown, and the others above the buttons, saying where", () => {
+    const e = refused(422, { error: "input_invalid", messages: [
+      "The run's input doesn't match the workflow's input schema at floor.0: it breaks `type`.",
+      "The run's input doesn't match the workflow's input schema at vlan: it breaks `maximum`.",
       "The run's input doesn't match the workflow's input schema at its root: it breaks `required`.",
-    ] }));  // prettier-ignore
+    ] });  // prettier-ignore
+    const r = refusalOf(e, new Set(["floor", "site"]));
     expect(r.fields).toEqual({ "field:floor": "Doesn't fit the input: it breaks `type`." });
-    expect(r.words).toBe("The input doesn't fit the workflow's input. Nothing started. At its root: it breaks `required`.");
+    expect(r.words).toBe("The input doesn't fit the workflow's input. Nothing started. At vlan: it breaks `maximum`. At its root: it breaks `required`.");
+    expect(refusalOf(e).fields).toEqual({}); // as JSON: every reason above, with where it is
   });
 
   it("words a CSV upload's end, and falls back to 4e-1's words, then the server's", () => {
diff --git a/frontend/src/routes/runs/RunForm.test.tsx b/frontend/src/routes/runs/RunForm.test.tsx
new file mode 100644
index 00000000..174fbcba
--- /dev/null
+++ b/frontend/src/routes/runs/RunForm.test.tsx
@@ -0,0 +1,206 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render, screen, waitFor, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import type { StartForm } from "../../lib/runForm";
+import { local } from "../../test/runs";
+import { RunForm } from "./RunForm";
+
+const FORM: StartForm = {
+  workflow_id: "w1", version_id: "v7", version_number: 7, published_at: local(9, 12, 0), published_by: "nadia@corp.test", csv: null,
+  fields: [
+    { name: "site", title: "Site", type: "string", required: true, sensitive: false },
+    { name: "floor", title: "Floor", type: "integer", required: false, sensitive: false },
+  ],
+};  // prettier-ignore
+const NEWER: StartForm = { ...FORM, version_id: "v8", version_number: 8, published_by: null, fields: [FORM.fields[0]!, { ...FORM.fields[1]!, type: "string" }] };
+
+let forms: StartForm[];
+let answers: (() => Promise<Response>)[];
+let posts: { key: string | null; body: unknown }[];
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+beforeEach(() => {
+  forms = [FORM];
+  answers = [];
+  posts = [];
+  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
+  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
+    const request = input as Request;
+    const url = new URL(request.url);
+    if (url.pathname === "/api/v1/t/t1/workflows/w1/start-form") return json(forms.length > 1 ? forms.shift() : forms[0]);
+    if (request.method === "POST" && url.pathname === "/api/v1/t/t1/workflows/w1/runs") {
+      posts.push({ key: request.headers.get("Idempotency-Key"), body: JSON.parse(await request.text()) as unknown });
+      return (answers.shift() ?? (() => Promise.resolve(json({ id: "r1" }, 202))))();
+    }
+    return json({ error: "not_found" }, 404);
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+function show(over: { draftDiffers?: boolean } = {}) {
+  const onStarted = vi.fn();
+  const onClose = vi.fn();
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  render(
+    <QueryClientProvider client={qc}>
+      <RunForm tenantId="t1" workflow={{ id: "w1", name: "Site onboarding" }} draftDiffers={over.draftDiffers} onStarted={onStarted} onClose={onClose} />
+    </QueryClientProvider>,
+  );
+  return { onStarted, onClose };
+}
+const dialog = () => screen.getByRole("dialog", { name: "Start a run" });
+/** The version line, its time a <time> inside it. */
+const versionLine = (text: string) => screen.findByText((_, el) => el?.tagName === "P" && el.textContent === text);
+
+describe("the run form (the run form design §5.2; the Main board)", () => {
+  it("names the workflow, the version that will run and who published it", async () => {
+    show();
+    expect(await versionLine("Version 7 · published today 09:12:00 by nadia@corp.test")).toBeTruthy();
+    expect(within(dialog()).getByText("Site onboarding")).toBeTruthy();
+    expect(screen.queryByText(/The draft has changes/)).toBeNull();
+  });
+
+  it("says when the draft differs from the published version, opened from the editor", async () => {
+    show({ draftDiffers: true });
+    expect(await screen.findByText("The draft has changes that aren't published. This run uses version 7, not the draft.")).toBeTruthy();
+  });
+
+  it("starts live by default, saying so; simulated says nothing is sent, and its button says so", async () => {
+    show();
+    const user = userEvent.setup();
+    await screen.findByLabelText(/Site/);
+    expect(screen.getByRole("radio", { name: "Live" })).toHaveProperty("checked", true);
+    expect(screen.getByText(/It acts for real: its steps call their connections/)).toBeTruthy();
+    expect(screen.getByRole("button", { name: "Start the live run" })).toBeTruthy();
+    await user.click(screen.getByRole("radio", { name: "Simulated" }));
+    expect(screen.getByText(/Nothing is sent: actions return fixtures instead of calling out/)).toBeTruthy();
+    expect(screen.getByRole("button", { name: "◌ Start the simulation" })).toBeTruthy();
+  });
+
+  it("starts the version it names under one key, and hands over the new run", async () => {
+    const { onStarted } = show();
+    const user = userEvent.setup();
+    await user.type(await screen.findByLabelText(/Site/), "HQ");
+    await user.type(screen.getByLabelText(/Floor/), "2");
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect(posts).toEqual([{ key: expect.any(String) as string, body: { input: { site: "HQ", floor: 2 }, mode: "live", expected_version_id: "v7" } }]);
+    expect(onStarted).toHaveBeenCalledWith("r1");
+  });
+
+  it("says beside a required field left empty that it's required, and sends nothing", async () => {
+    show();
+    const user = userEvent.setup();
+    await screen.findByLabelText(/Site/);
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect(screen.getByText("Give a value: the input requires it.")).toBeTruthy();
+    expect(posts).toEqual([]);
+  });
+
+  it("shows a version published meanwhile, keeping the values that still fit, and starts it once asked again", async () => {
+    forms = [FORM, NEWER];
+    answers = [() => Promise.resolve(json({ error: "version_changed", messages: ["…"], active_version_id: "v8", active_version_number: 8 }, 409))];
+    const { onStarted } = show();
+    const user = userEvent.setup();
+    await user.type(await screen.findByLabelText(/Site/), "HQ");
+    await user.type(screen.getByLabelText(/Floor/), "2");
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringMatching(/^Version 8 was published while this was open\. Nothing started\./));
+    expect(await versionLine("Version 8 · published today 09:12:00")).toBeTruthy(); // its publisher gone
+    expect(screen.getByLabelText(/Site/)).toHaveProperty("value", "HQ");
+    expect(screen.getByLabelText(/Floor/)).toHaveProperty("value", ""); // now text: not kept
+    expect(onStarted).not.toHaveBeenCalled();
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect(posts.map((p) => (p.body as { expected_version_id: string }).expected_version_id)).toEqual(["v7", "v8"]);
+    expect(posts[1]!.key).not.toBe(posts[0]!.key);
+    expect(onStarted).toHaveBeenCalledWith("r1");
+  });
+
+  it("sends the same form again under the same key after its answer was lost", async () => {
+    answers = [() => Promise.reject(new TypeError("Failed to fetch"))];
+    const { onStarted } = show();
+    const user = userEvent.setup();
+    await user.type(await screen.findByLabelText(/Site/), "HQ");
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "The server didn't answer. Start again: the same form is never started twice.");
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect(posts).toHaveLength(2);
+    expect(posts[1]!.key).toBe(posts[0]!.key);
+    expect(onStarted).toHaveBeenCalledWith("r1");
+  });
+
+  it("says an input's refusal beside the field it names, and the rest above the buttons", async () => {
+    answers = [() => Promise.resolve(json({ error: "input_invalid", messages: ["The run's input doesn't match the workflow's input schema at floor: it breaks `maximum`."] }, 422))];
+    show();
+    const user = userEvent.setup();
+    await user.type(await screen.findByLabelText(/Site/), "HQ");
+    await user.type(screen.getByLabelText(/Floor/), "200");
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect(await screen.findByText("Doesn't fit the input: it breaks `maximum`.")).toBeTruthy();
+    expect(screen.getByRole("alert").textContent).toBe("The input doesn't fit the workflow's input. Nothing started. input_invalid");
+  });
+
+  it("says a refusal's code beside its words", async () => {
+    answers = [() => Promise.resolve(json({ error: "workflow_disabled", messages: ["The workflow is disabled."] }, 409))];
+    show();
+    const user = userEvent.setup();
+    await user.type(await screen.findByLabelText(/Site/), "HQ");
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect((await screen.findByRole("alert")).textContent).toBe("The workflow is disabled. Nothing started. workflow_disabled");
+  });
+
+  it("starts once however often Start is pressed while the start is sent", async () => {
+    let answer!: (r: Response) => void;
+    answers = [() => new Promise((r) => (answer = r))];
+    const { onStarted } = show();
+    const user = userEvent.setup();
+    await user.type(await screen.findByLabelText(/Site/), "HQ");
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    answer(json({ id: "r1" }, 202));
+    await vi.waitFor(() => expect(onStarted).toHaveBeenCalledWith("r1"));
+    expect(posts).toHaveLength(1);
+  });
+
+  it("keeps the form when the version published meanwhile can't be read, saying why", async () => {
+    answers = [() => Promise.resolve(json({ error: "version_changed", messages: ["…"], active_version_id: "v8", active_version_number: 8 }, 409))];
+    show();
+    const user = userEvent.setup();
+    await user.type(await screen.findByLabelText(/Site/), "HQ");
+    const served = vi.mocked(globalThis.fetch).getMockImplementation()!;
+    vi.mocked(globalThis.fetch).mockImplementation(async (input) =>
+      new URL((input as Request).url).pathname.endsWith("/start-form") ? json({ error: "internal_error", messages: ["The server failed."] }, 500) : served(input),
+    );  // prettier-ignore
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect((await screen.findByRole("alert")).textContent).toBe("The server failed. Nothing started. internal_error");
+    expect(await versionLine("Version 7 · published today 09:12:00 by nadia@corp.test")).toBeTruthy();
+    expect(screen.getByLabelText(/Site/)).toHaveProperty("value", "HQ");
+  });
+
+  it("takes the input as JSON too", async () => {
+    show();
+    const user = userEvent.setup();
+    await screen.findByLabelText(/Site/);
+    await user.click(screen.getByRole("button", { name: "Edit as JSON" }));
+    const text = screen.getByLabelText("The input, as JSON");
+    await user.clear(text);
+    await user.type(text, '{{"site": "Lyon"}');
+    await user.click(screen.getByRole("button", { name: "Start the live run" }));
+    expect(posts[0]!.body).toEqual({ input: { site: "Lyon" }, mode: "live", expected_version_id: "v7" });
+  });
+
+  it("focuses its first field once the form is read", async () => {
+    show();
+    const site = await screen.findByLabelText(/Site/);
+    await waitFor(() => expect(document.activeElement).toBe(site));
+  });
+
+  it("closes on Cancel, starting nothing", async () => {
+    const { onClose } = show();
+    const user = userEvent.setup();
+    await screen.findByLabelText(/Site/);
+    await user.click(screen.getByRole("button", { name: "Cancel" }));
+    expect(onClose).toHaveBeenCalled();
+    expect(posts).toEqual([]);
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunForm.test.tsx src/lib/runForm.test.ts
src/routes/editor/simulation/SimulateDialog.test.tsx`

Expected: FAIL, 1 failed and 18 passed: `RunForm.test.tsx` can't import its module; `refusalOf` puts a reason at a field
it isn't told is shown beside it (`expected { …(2) } to deeply equal { Object (field:floor) }`). The Simulate dialog's
tests pass: its labels don't change.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.ts b/frontend/src/lib/runForm.ts
index 6e349188..4ac3e8ea 100644
--- a/frontend/src/lib/runForm.ts
+++ b/frontend/src/lib/runForm.ts
@@ -91,7 +91,7 @@ export function keptValues(values: ReadonlyMap<string, string>, from: StartForm,
   );
 }
 
-/** A refused start, in words: its code, what the form says, each reason beside the field it names, and for
+/** A refused start, in words: its code, what the form says, each reason beside the shown field it names, and for
  * `version_changed` the version now active. */
 export interface Refusal {
   code: string;
@@ -112,7 +112,9 @@ const FORM_WORDS: Record<string, string> = {
   network: "The server didn't answer. Start again: the same form is never started twice.",
 };
 
-export function refusalOf(e: unknown): Refusal {
+/** `shown`: the fields the form shows, a reason at one of them (or inside it) said beside it, keyed as startInput's
+ * fieldKey keys a field's problem; any other's is said above the buttons with where it is (Edit as JSON shows none). */
+export function refusalOf(e: unknown, shown: ReadonlySet<string> = new Set()): Refusal {
   if (!(e instanceof ApiError)) return { code: "network", words: FORM_WORDS.network!, fields: {} };
   const body = (e.body ?? {}) as { messages?: unknown; active_version_id?: unknown; active_version_number?: unknown };
   const messages = Array.isArray(body.messages) ? body.messages.filter((m): m is string => typeof m === "string") : [];
@@ -128,8 +130,9 @@ export function refusalOf(e: unknown): Refusal {
     const rest: string[] = [];
     for (const m of messages) {
       const at = AT.exec(m);
-      if (at && at[1] !== "its root") fields[`field:${at[1]!.split(".")[0]!}`] = `Doesn't fit the input: it breaks \`${at[2]!}\`.`;
-      else rest.push(at ? `At its root: it breaks \`${at[2]!}\`.` : m);
+      const name = at && at[1] !== "its root" ? at[1]!.split(".")[0]! : null;
+      if (name !== null && shown.has(name)) fields[`field:${name}`] = `Doesn't fit the input: it breaks \`${at![2]!}\`.`;
+      else rest.push(at ? `At ${at[1]!}: it breaks \`${at[2]!}\`.` : m);
     }
     return { code: e.code, fields, words: ["The input doesn't fit the workflow's input.", NOTHING, ...rest].join(" ") };
   }
diff --git a/frontend/src/routes/editor/simulation/SimulateDialog.tsx b/frontend/src/routes/editor/simulation/SimulateDialog.tsx
index a20965b8..f0b77072 100644
--- a/frontend/src/routes/editor/simulation/SimulateDialog.tsx
+++ b/frontend/src/routes/editor/simulation/SimulateDialog.tsx
@@ -8,34 +8,16 @@ import { useQuery } from "@tanstack/react-query";
 import { useEffect, useId, useRef, useState, type FormEvent } from "react";
 import { Button } from "../../../components/Button";
 import { TextArea } from "../../../components/Field";
-import { Tag } from "../../../components/Tag";
 import { inputOf, topicShaped } from "../../../lib/input";
 import { draftStartFormQuery } from "../../../lib/simulations";
 import { skeletonOf } from "../../../lib/skeleton";
-import { triggerTypesQuery, type StartField } from "../../../lib/triggers";
+import { triggerTypesQuery } from "../../../lib/triggers";
 import type { GraphDoc } from "../../../lib/workflows";
-import { InputControl, fieldKey, fieldsShow, fromFields, nameOf, startValues, wholeOf } from "../startInput";
+import { InputControl, REQUIRED, fieldKey, fieldsShow, fromFields, hintOf, labelOf, startValues, wholeOf } from "../startInput";
 import { SimBanner } from "./SimBanner";
 
-const REQUIRED = "Give a value: the input requires it.";
 const SKELETON = "A generated skeleton: every field the input declares, filled with empty values of its type. Fill it with the event you want to try.";
 
-/** A field's label, with what it is beside it, and what its hint adds: optional ones are left out when empty, sensitive
- * ones stored as protected values (the InputFields board). */
-const labelOf = (f: StartField) => (
-  <>
-    {nameOf(f)}
-    {f.required && <> <Tag>required</Tag></>}
-    {f.sensitive && <> <Tag>sensitive</Tag></>}
-  </>
-);
-const hintOf = (f: StartField) =>
-  [
-    f.description,
-    f.required ? null : "Optional: left out when empty.",
-    f.sensitive ? "Stored as a protected value: results show it as redacted." : null,
-  ].filter(Boolean).join(" ") || undefined;  // prettier-ignore
-
 export function SimulateDialog({ tenantId, workflowId, name, revision, doc, onSimulate, onClose }: {
   tenantId: string; workflowId: string; name: string; revision: number; doc: GraphDoc;
   onSimulate: (input: Record<string, unknown>) => void; onClose: () => void;
diff --git a/frontend/src/routes/editor/startInput.tsx b/frontend/src/routes/editor/startInput.tsx
index d02c32db..65d9a565 100644
--- a/frontend/src/routes/editor/startInput.tsx
+++ b/frontend/src/routes/editor/startInput.tsx
@@ -4,6 +4,7 @@
 // Simulate workflow dialog both enter an input this way; a sensitive field is never prefilled with what it hides.
 import type { ReactNode } from "react";
 import { Field, Select, TextArea } from "../../components/Field";
+import { Tag } from "../../components/Tag";
 import { parseJson } from "../../lib/config";
 import { isObject } from "../../lib/schemaForm";
 import type { StartField } from "../../lib/triggers";
@@ -87,6 +88,25 @@ export function fromFields(
   return problems.length > 0 ? { problems: Object.fromEntries(problems) } : { input: Object.fromEntries(entries) };
 }
 
+/** What a required field left empty says (the InputFields board). */
+export const REQUIRED = "Give a value: the input requires it.";
+
+/** A field's label, with what it is beside it, and what its hint adds: optional ones are left out when empty, sensitive
+ * ones stored as protected values (the InputFields board; the run form's Main board, 4e-2). */
+export const labelOf = (f: StartField) => (
+  <>
+    {nameOf(f)}
+    {f.required && <> <Tag>required</Tag></>}
+    {f.sensitive && <> <Tag>sensitive</Tag></>}
+  </>
+);
+export const hintOf = (f: StartField) =>
+  [
+    f.description,
+    f.required ? null : "Optional: left out when empty.",
+    f.sensitive ? "Stored as a protected value: results show it as redacted." : null,
+  ].filter(Boolean).join(" ") || undefined;  // prettier-ignore
+
 export const listed = (items: string[]) => (items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)!}`);
 
 /** One field of the published version's form: never prefilled with what a sensitive field hides. */
diff --git a/frontend/src/routes/runs/RunForm.tsx b/frontend/src/routes/runs/RunForm.tsx
new file mode 100644
index 00000000..5a5d3cc4
--- /dev/null
+++ b/frontend/src/routes/runs/RunForm.tsx
@@ -0,0 +1,213 @@
+// SPDX-License-Identifier: Apache-2.0
+// The run form (editor 4e-2b; the run form design §5.2; the Main and MoreStates boards): the published version's start
+// form, live or simulated, in the Simulate dialog's look. The version it shows is the one it starts: the start goes
+// with that version's id (B14), and a version published meanwhile is read and shown, the values that still fit kept.
+// Each submitted form goes under one key, sent again under it only when the same form is (an answer lost on the way).
+import { useQuery, useQueryClient } from "@tanstack/react-query";
+import { useEffect, useId, useRef, useState, type FormEvent } from "react";
+import { Button } from "../../components/Button";
+import { TextArea } from "../../components/Field";
+import { When } from "../../components/When";
+import { keptValues, keyFor, refusalOf, startRun, type Refusal, type Sent, type StartBody, type StartForm } from "../../lib/runForm";
+import { startFormQuery } from "../../lib/triggers";
+import { SimBanner } from "../editor/simulation/SimBanner";
+import { InputControl, REQUIRED, fieldKey, fromFields, hintOf, labelOf, startValues, wholeOf } from "../editor/startInput";
+
+type Mode = StartBody["mode"];
+
+/** A refusal says its code beside its words (the MoreStates board), but for those the form itself words. */
+const CODED = (code: string) => !["version_changed", "network"].includes(code);
+
+function ModeChoice({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
+  const id = useId();
+  return (
+    <fieldset className="flex flex-col gap-2">
+      <legend className="mb-1.5 text-small font-semibold">Mode</legend>
+      <div className="flex flex-wrap gap-x-6 gap-y-2">
+        {(["live", "simulate"] as const).map((m) => (
+          <label key={m} className="flex min-h-6 items-center gap-2 text-small">
+            <input type="radio" name={`${id}-mode`} checked={mode === m} onChange={() => onChange(m)} className="size-[16px] accent-accent" />
+            {m === "live" ? "Live" : "Simulated"}
+          </label>
+        ))}
+      </div>
+      {mode === "live" ? (
+        <p className="rounded-lg border border-live bg-live-bg px-3 py-2 text-small text-ink">
+          <strong className="text-live">Live.</strong> It acts for real: its steps call their connections, and what they
+          change in Mist stays changed.
+        </p>
+      ) : (
+        <SimBanner>
+          <p>
+            <strong>Simulated.</strong> Nothing is sent: actions return fixtures instead of calling out. Results don&apos;t
+            prove the live call will succeed.
+          </p>
+        </SimBanner>
+      )}
+    </fieldset>
+  );
+}
+
+export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, onClose }: {
+  tenantId: string; workflow: { id: string; name: string }; draftDiffers?: boolean;
+  onStarted: (runId: string) => void; onClose: () => void;
+}) {  // prettier-ignore
+  const id = useId();
+  const dialog = useRef<HTMLDialogElement>(null);
+  const fieldsRef = useRef<HTMLDivElement>(null);
+  useEffect(() => {
+    const d = dialog.current;
+    if (d && !d.open) d.showModal();
+  }, []);
+  const qc = useQueryClient();
+  const read = useQuery(startFormQuery(tenantId, workflow.id));
+  // The version shown is the one confirmed: a later read of the query (a refetch elsewhere) never swaps it unseen.
+  const [form, setForm] = useState<StartForm | null>(null);
+  if (form === null && read.data) setForm(read.data);
+  const [mode, setMode] = useState<Mode>("live");
+  const [values, setValues] = useState<ReadonlyMap<string, string> | null>(null);
+  const shownValues = values ?? (form ? startValues(form) : new Map<string, string>());
+  const [asJson, setAsJson] = useState(false);
+  const [jsonText, setJsonText] = useState<string | null>(null);
+  const [errors, setErrors] = useState<Record<string, string>>({});
+  const [refusal, setRefusal] = useState<Refusal | null>(null);
+  const [last, setLast] = useState<Sent | null>(null);
+  const [sending, setSending] = useState(false);
+  const shownJson = jsonText ?? "";
+
+  // Focus goes to the first field once the form is read (§5.6); before, the dialog holds it.
+  const formRead = form !== null;
+  useEffect(() => {
+    if (formRead) fieldsRef.current?.querySelector<HTMLElement>("input, select, textarea")?.focus();
+  }, [formRead]);
+
+  /** What's in the fields, as JSON; a field whose value doesn't read keeps the form where it is, saying why. */
+  const toJson = () => {
+    if (!form) return;
+    const made = fromFields(form, shownValues, false);
+    if ("problems" in made) return setErrors(made.problems);
+    setErrors({});
+    setJsonText(Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "");
+    setAsJson(true);
+  };
+
+  async function submit(e: FormEvent) {
+    e.preventDefault();
+    if (!form || sending) return;
+    let input: Record<string, unknown>;
+    if (asJson) {
+      const whole = wholeOf(shownJson);
+      if ("problem" in whole) return setErrors({ input: whole.problem });
+      input = whole.value;
+    } else {
+      const made = fromFields(form, shownValues, true, () => REQUIRED);
+      if ("problems" in made) return setErrors(made.problems);
+      input = made.input;
+    }
+    const body: StartBody = { input, mode, expected_version_id: form.version_id };
+    const sent = keyFor(last, body);
+    setLast(sent);
+    setErrors({});
+    setRefusal(null);
+    setSending(true);
+    try {
+      const started = await startRun(tenantId, workflow.id, body, sent.key);
+      onStarted(started.id);
+    } catch (err) {
+      let refused = refusalOf(err, new Set(asJson ? [] : form.fields.map((f) => f.name)));
+      if (refused.code === "version_changed") {
+        try {
+          const fresh = await qc.query({ ...startFormQuery(tenantId, workflow.id), staleTime: 0 });
+          if (fresh) {
+            setValues(keptValues(shownValues, form, fresh));
+            setForm(fresh);
+          }
+        } catch (again) {
+          refused = refusalOf(again);
+        }
+      }
+      setRefusal(refused);
+      setErrors(refused.fields);
+    } finally {
+      setSending(false);
+    }
+  }
+
+  return (
+    <dialog
+      ref={dialog}
+      aria-labelledby={`${id}-title`}
+      onClose={onClose}
+      className="mx-auto mt-16 w-[600px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
+    >
+      <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-4">
+        <header>
+          <h2 id={`${id}-title`} className="text-h3 font-semibold">Start a run</h2>
+          <p className="text-small text-muted">{workflow.name}</p>
+        </header>
+        {read.isPending && form === null ? (
+          <p className="text-small text-muted">Loading the published version&apos;s input…</p>
+        ) : form === null ? (
+          <p role="alert" className="text-small text-danger">
+            {read.isError ? "The published version's input couldn't be read. Close this and start again." : "This workflow has no published version: nothing can start."}
+          </p>
+        ) : (
+          <>
+            <p className="text-small">
+              <span className="text-muted">Version</span>
+              {` ${form.version_number} · published `}
+              <When iso={form.published_at} />
+              {form.published_by ? ` by ${form.published_by}` : ""}
+            </p>
+            {draftDiffers && (
+              <p className="text-small text-muted">
+                {`The draft has changes that aren't published. This run uses version ${form.version_number}, not the draft.`}
+              </p>
+            )}
+            <ModeChoice mode={mode} onChange={setMode} />
+            <div ref={fieldsRef} className="flex flex-col gap-4">
+              {asJson ? (
+                <TextArea
+                  label="The input, as JSON"
+                  hint='An object, like {"site": "HQ"}. Shown as typed, a sensitive value too.'
+                  error={errors.input}
+                  value={shownJson}
+                  rows={10}
+                  spellCheck={false}
+                  onChange={(e) => setJsonText(e.target.value)}
+                />
+              ) : (
+                <>
+                  {form.fields.length === 0 && <p className="text-small text-muted">This version takes no input.</p>}
+                  {form.fields.map((f) => (
+                    <InputControl
+                      key={f.name} f={f} value={shownValues.get(f.name)} error={errors[fieldKey(f.name)]} label={labelOf(f)} hint={hintOf(f)}
+                      onChange={(v) => setValues(new Map(shownValues).set(f.name, v))}
+                    />
+                  ))}
+                </>
+              )}
+            </div>
+            <div>
+              <Button size="sm" aria-pressed={asJson} onClick={() => (asJson ? (setAsJson(false), setJsonText(null)) : toJson())}>
+                Edit as JSON
+              </Button>
+            </div>
+          </>
+        )}
+        {refusal && (
+          <p role="alert" className="text-small text-danger">
+            {refusal.words}
+            {CODED(refusal.code) && <> <span className="font-mono">{refusal.code}</span></>}
+          </p>
+        )}
+        <div className="flex flex-wrap justify-end gap-2">
+          <Button onClick={onClose}>Cancel</Button>
+          <Button type="submit" variant={mode === "live" ? "live-outline" : "simulate"} disabled={form === null || sending}>
+            {mode === "live" ? "Start the live run" : "◌ Start the simulation"}
+          </Button>
+        </div>
+      </form>
+    </dialog>
+  );
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 33 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib frontend/src/routes
git commit -m "feat(editor): the run form for typed input, on the version it shows (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The ways in, and landing on the new run

**Spec:** §5.1 (where it opens), §5.2 (on 202: the new run's page, its heading focused), §5.6 (focus back to the
opener); the EntryPoints board.

**Files:**
- Create: `frontend/src/routes/runs/landing.ts`, `frontend/src/routes/runs/landing.test.tsx`
- Modify: `frontend/src/routes/Workflows.tsx`, `frontend/src/routes/Workflows.test.tsx`,
  `frontend/src/routes/runs/LazyRuns.tsx` (`LazyRunForm`)
- Modify: `frontend/src/routes/runs/RunsPage.tsx`, `frontend/src/routes/runs/RunsPage.test.tsx`,
  `frontend/src/routes/runs/Filters.tsx` (`Chooser` exported)
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`
- Modify: `frontend/src/routes/runs/RunPage.tsx`, `frontend/src/routes/runs/RunPage.test.tsx` (the landing),
  `frontend/src/routes/runs/RunForm.tsx` (Cancel closes the dialog)

**Interfaces:**
- Consumes: Task 3's `RunForm`; Task 2's `canStart`, `startable`; `workflowsQuery`, `tenantQuery`; `RUN_TITLE`
  (`routes/runs/useCancel.ts`).
- Produces:
  - `landing.ts`: `landOn(runId)`, `useLand(tenantId): (runId) => void`, `useLanded(runId, shown)`;
  - `Filters.tsx`: `Chooser({ workflows, value, any?, empty?, onPick, onClose })`;
  - `LazyRuns.tsx`: `LazyRunForm(props)`, the form loaded when the Workflows list first opens it (ruling 30).

Each way in shows only where a start can go ahead (ruling 12). A started run's page opens, its name focused once it's
read (ruling 11); Cancel closes the native dialog, which gives focus back to its opener (ruling 10).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/Workflows.test.tsx b/frontend/src/routes/Workflows.test.tsx
index 3724b537..0f76e827 100644
--- a/frontend/src/routes/Workflows.test.tsx
+++ b/frontend/src/routes/Workflows.test.tsx
@@ -22,6 +22,10 @@ const ROWS = [
         unpublished_changes: true, last_run: null, runs_24h: { live: 0, simulate: 0 } }),
 ];  // prettier-ignore
 
+const START_FORM = {
+  workflow_id: "w1", version_id: "v2", version_number: 2, published_at: "2026-10-06T09:00:00Z", published_by: "nadia@corp.test", csv: null, fields: [],
+};  // prettier-ignore
+
 let role = "editor";
 let sent: { method: string; path: string; body: unknown }[];
 let patchAnswer: Response | null;
@@ -38,6 +42,8 @@ beforeEach(() => {
     const path = new URL(request.url).pathname;
     const text = await request.text();
     sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
+    if (path === "/api/v1/t/t1/workflows/w1/start-form") return new Response(JSON.stringify(START_FORM));
+    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/runs") return new Response(JSON.stringify({ id: "r1" }), { status: 202 });
     if (request.method === "PATCH") return patchAnswer ?? new Response(JSON.stringify({ ...ROWS[0], enabled: false, warnings: [] }));
     if (path === "/api/v1/t/t1") return new Response(JSON.stringify({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }));
     if (path === "/api/v1/trigger-types") return new Response("[]"); // what New workflow offers to start it
@@ -196,3 +202,25 @@ it("gives each of those links a target of at least 24 px, one above the other (W
     expect(within(rowOf("Triage")).getByRole("link", { name }).className).toMatch(/(?:^|\s)min-h-\[24px\](?:\s|$)/);
   }
 });
+
+it("offers Start… on each row that can start, to the roles that hold run.start (the run form design §5.1)", async () => {
+  role = "operator";
+  await show();
+  expect(within(rowOf("Nightly")).getByRole("button", { name: "Start a run of Nightly" }).textContent).toBe("Start…");
+  expect(within(rowOf("Triage")).queryByRole("button", { name: /Start a run/ })).toBeNull(); // switched off
+  expect(within(rowOf("Sketch")).queryByRole("button", { name: /Start a run/ })).toBeNull(); // never published
+  cleanup();
+  role = "viewer";
+  await show();
+  expect(screen.queryByRole("button", { name: /Start a run/ })).toBeNull();
+});
+
+it("starts a run from its row and lands on its page (the run form design §5.2)", async () => {
+  const router = await show();
+  await userEvent.click(screen.getByRole("button", { name: "Start a run of Nightly" }));
+  const form = await screen.findByRole("dialog", { name: "Start a run" });
+  expect(within(form).getByText("Nightly")).toBeTruthy();
+  await userEvent.click(await within(form).findByRole("button", { name: "Start the live run" }));
+  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/runs/r1"));
+  expect(sent.filter((r) => r.method === "POST").map((r) => r.path)).toEqual(["/api/v1/t/t1/workflows/w1/runs"]);
+});
diff --git a/frontend/src/routes/editor/Editor.test.tsx b/frontend/src/routes/editor/Editor.test.tsx
index b1682d19..13453b14 100644
--- a/frontend/src/routes/editor/Editor.test.tsx
+++ b/frontend/src/routes/editor/Editor.test.tsx
@@ -1,7 +1,7 @@
 // SPDX-License-Identifier: Apache-2.0
 import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
 import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, redirect } from "@tanstack/react-router";
-import { act, render, screen, within } from "@testing-library/react";
+import { act, cleanup, render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { beforeEach, describe, expect, it, vi } from "vitest";
 import type { GraphDoc } from "../../lib/workflows";
@@ -2484,3 +2484,40 @@ describe("the runs, from the editor (the runs design §5.1)", () => {
     await vi.waitFor(() => expect(router.state.location.pathname).toBe(`/t/t1/runs/${request.id}`));
   });
 });
+
+// Start a run… (4e-2; the run form design §5.1; the EntryPoints board): the published version, never the draft.
+describe("Start a run from the editor", () => {
+  const PUBLISHED = { ...WORKFLOW, active_version_id: "v1", active_version_number: 1, executable: true };
+  const FORM = { workflow_id: "w1", version_id: "v1", version_number: 1, published_at: "2026-10-06T09:00:00Z", published_by: null, csv: null, fields: [] };
+  beforeEach(() => {
+    answers.set(`GET ${BASE}`, () => json(PUBLISHED));
+    answers.set("GET /api/v1/t/t1/workflows", () => json([PUBLISHED]));
+    answers.set(`GET ${BASE}/start-form`, () => json(FORM));
+    answers.set(`POST ${BASE}/runs`, () => json({ id: "r1" }, 202));
+  });
+
+  it("offers Start a run… beside Simulate once published, says the draft differs, and lands on the run", async () => {
+    const { router } = await show();
+    const start = await screen.findByRole("button", { name: "Start a run…" });
+    expect(screen.getByRole("button", { name: "◌ Simulate workflow" }).nextElementSibling).toBe(start);
+    await userEvent.click(start);
+    expect(await screen.findByText("The draft has changes that aren't published. This run uses version 1, not the draft.")).toBeTruthy();
+    await userEvent.click(screen.getByRole("button", { name: "Start the live run" }));
+    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/runs/r1"));
+  });
+
+  it("offers none on a workflow never published, nor to a role without run.start", async () => {
+    answers.set(`GET ${BASE}`, () => json(WORKFLOW));
+    answers.set("GET /api/v1/t/t1/workflows", () => json([WORKFLOW]));
+    await show();
+    await screen.findByRole("button", { name: "◌ Simulate workflow" });
+    expect(screen.queryByRole("button", { name: "Start a run…" })).toBeNull();
+    cleanup();
+    answers.set(`GET ${BASE}`, () => json(PUBLISHED));
+    answers.set("GET /api/v1/t/t1/workflows", () => json([PUBLISHED]));
+    role = "viewer";
+    await show();
+    await screen.findByRole("button", { name: "Versions" });
+    expect(screen.queryByRole("button", { name: "Start a run…" })).toBeNull();
+  });
+});
diff --git a/frontend/src/routes/runs/RunPage.test.tsx b/frontend/src/routes/runs/RunPage.test.tsx
index f57bc0f6..01e0e95d 100644
--- a/frontend/src/routes/runs/RunPage.test.tsx
+++ b/frontend/src/routes/runs/RunPage.test.tsx
@@ -8,6 +8,7 @@ import { onAnnounce } from "../../lib/announce";
 import type { Run, RunSteps } from "../../lib/runs";
 import { FAILED_GRAPH, FAILED_RUN, FAILED_STEPS, LOOP_GRAPH, LOOP_STEPS, LOOP_TOTAL, RUN_TYPES, attempt, local, loopInstance } from "../../test/runs";
 import type { CanvasProps } from "../editor/Canvas";
+import { landOn } from "./landing";
 import { RunPage } from "./RunPage";
 
 // The canvas stands in as the editor's tests have it: React Flow isn't drawn in jsdom. It shows what it was given.
@@ -101,6 +102,14 @@ it("names the run by its workflow and its short id, with the way back to Runs (
   expect(router.state.location.pathname).toBe("/t/t1/runs");
 });
 
+it("focuses its name when a start landed on it, once it's read (the run form design §5.2)", async () => {
+  answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
+  landOn(RUN.id);
+  show();
+  const heading = await screen.findByRole("heading", { level: 1, name: "AP offline triage" });
+  await vi.waitFor(() => expect(document.activeElement).toBe(heading));
+});
+
 it("says a run that isn't kept any more, or never was, is neither, with Back to Runs (§5.4; the RunOther board)", async () => {
   const router = show("0d4f9b2a-0000-4000-8000-000000000000");
   expect(await screen.findByRole("heading", { level: 1, name: "Run 0d4f9b2a" })).toBeTruthy();
diff --git a/frontend/src/routes/runs/RunsPage.test.tsx b/frontend/src/routes/runs/RunsPage.test.tsx
index 19a1b70c..cb000685 100644
--- a/frontend/src/routes/runs/RunsPage.test.tsx
+++ b/frontend/src/routes/runs/RunsPage.test.tsx
@@ -1,7 +1,7 @@
 // SPDX-License-Identifier: Apache-2.0
 import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
 import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, useSearch } from "@tanstack/react-router";
-import { act, render, screen, within } from "@testing-library/react";
+import { act, cleanup, render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import { onAnnounce } from "../../lib/announce";
@@ -43,18 +43,27 @@ const BOARD: RunItem[] = [
   }),
 ];  // prettier-ignore
 
-const WORKFLOWS = [{ id: "w1", name: "AP offline triage" }, { id: "w2", name: "Bulk AP rename" }];
+// The first can start (published, switched on, executable); the second was never published.
+const WORKFLOWS = [
+  { id: "w1", name: "AP offline triage", active_version_id: "v3", enabled: true, executable: true },
+  { id: "w2", name: "Bulk AP rename", active_version_id: null, enabled: true, executable: null },
+];
+const START_FORM = { workflow_id: "w1", version_id: "v3", version_number: 3, published_at: local(9, 0, 0), published_by: null, csv: null, fields: [] };
 
 let answers: (() => Response)[];
 let sent: URL[];
+let role: string;
 
 beforeEach(() => {
   answers = [];
   sent = [];
+  role = "operator";
   vi.spyOn(Date, "now").mockReturnValue(NOW);
   vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
     const url = new URL((input as Request).url);
     if (url.pathname === "/api/v1/t/t1/workflows") return Promise.resolve(new Response(JSON.stringify(WORKFLOWS)));
+    if (url.pathname === "/api/v1/t/t1") return Promise.resolve(new Response(JSON.stringify({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role })));
+    if (url.pathname === "/api/v1/t/t1/workflows/w1/start-form") return Promise.resolve(new Response(JSON.stringify(START_FORM)));
     sent.push(url);
     return Promise.resolve(answers.shift()?.() ?? new Response(JSON.stringify(BOARD)));
   });
@@ -380,3 +389,40 @@ it("starts the list afresh when a filter changes after older runs were loaded",
   expect(screen.queryByText("No older runs in the last 24 hours.")).toBeNull();
   expect(screen.getByRole("button", { name: "Load more" })).toBeTruthy();
 });
+
+describe("starting a run from the Runs page (the run form design §5.1; the EntryPoints board)", () => {
+  it("offers Start a run… beside the heading to the roles that hold run.start", async () => {
+    show();
+    const start = await screen.findByRole("button", { name: "Start a run…" });
+    expect(screen.getByRole("heading", { level: 1, name: "Runs" }).nextElementSibling).toBe(start);
+    cleanup();
+    role = "viewer";
+    show();
+    await screen.findByRole("heading", { level: 1, name: "Runs" });
+    await screen.findByRole("link", { name: "a14b2e9c" }); // the tenant's role is read beside the runs
+    expect(screen.queryByRole("button", { name: "Start a run…" })).toBeNull();
+  });
+
+  it("asks for the workflow first, among those that can start, then opens its form", async () => {
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Start a run…" }));
+    const chooser = screen.getByRole("dialog", { name: "Choose a workflow" });
+    expect(within(chooser).getAllByRole("option").map((o) => o.textContent)).toEqual(["AP offline triage"]); // no Any
+    await userEvent.click(within(chooser).getByRole("option", { name: "AP offline triage" }));
+    const form = await screen.findByRole("dialog", { name: "Start a run" });
+    expect(within(form).getByText("AP offline triage")).toBeTruthy();
+  });
+
+  it("asks for the workflow when its filter names one that can't start", async () => {
+    show("/t/t1/runs?workflow=w2");
+    await userEvent.click(await screen.findByRole("button", { name: "Start a run…" }));
+    expect(screen.getByRole("dialog", { name: "Choose a workflow" })).toBeTruthy();
+  });
+
+  it("starts the workflow its filter has chosen already", async () => {
+    show("/t/t1/runs?workflow=w1");
+    await userEvent.click(await screen.findByRole("button", { name: "Start a run…" }));
+    expect(await screen.findByRole("dialog", { name: "Start a run" })).toBeTruthy();
+    expect(screen.queryByRole("dialog", { name: "Choose a workflow" })).toBeNull();
+  });
+});
diff --git a/frontend/src/routes/runs/landing.test.tsx b/frontend/src/routes/runs/landing.test.tsx
new file mode 100644
index 00000000..95a34005
--- /dev/null
+++ b/frontend/src/routes/runs/landing.test.tsx
@@ -0,0 +1,41 @@
+// SPDX-License-Identifier: Apache-2.0
+import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter, useParams } from "@tanstack/react-router";
+import { render, screen, waitFor } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { describe, expect, it } from "vitest";
+import { useLand, useLanded } from "./landing";
+import { RUN_TITLE } from "./useCancel";
+
+function Starter() {
+  const land = useLand("t1");
+  return <button onClick={() => land("r1")}>Start</button>;
+}
+function Page() {
+  const runId = useParams({ strict: false }).runId ?? "";
+  useLanded(runId, true);
+  return <h1 id={RUN_TITLE} tabIndex={-1}>{`Run ${runId}`}</h1>;
+}
+
+function show() {
+  const root = createRootRoute({ component: Outlet });
+  const home = createRoute({ getParentRoute: () => root, path: "/", component: Starter });
+  const run = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/runs/$runId", component: Page });
+  const router = createRouter({ routeTree: root.addChildren([home, run]), history: createMemoryHistory({ initialEntries: ["/"] }) });
+  render(<RouterProvider router={router} />);
+  return router;
+}
+
+describe("landing on a run just started (the run form design §5.2)", () => {
+  it("opens the run's page, its heading focused, once", async () => {
+    const router = show();
+    await userEvent.click(await screen.findByRole("button", { name: "Start" }));
+    const heading = await screen.findByRole("heading", { name: "Run r1" });
+    await waitFor(() => expect(document.activeElement).toBe(heading));
+    expect(router.state.location.pathname).toBe("/t/t1/runs/r1");
+    heading.blur();
+    await router.navigate({ to: "/" });
+    await router.navigate({ to: "/t/$tenantId/runs/$runId", params: { tenantId: "t1", runId: "r1" } });
+    await screen.findByRole("heading", { name: "Run r1" });
+    expect(document.activeElement).toBe(document.body); // opened another way: the browser's focus, as any page
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/landing.test.tsx src/routes/runs/RunPage.test.tsx
src/routes/Workflows.test.tsx src/routes/runs/RunsPage.test.tsx src/routes/editor/Editor.test.tsx
src/routes/runs/RunForm.test.tsx`

Expected: FAIL, 7 failed and 217 passed: `landing.test.tsx` and `RunPage.test.tsx` can't import `./landing`; there's no
"Start a run of Nightly" on a Workflows row, no "Start a run…" on the Runs page (four tests) nor in the editor (`Unable
to find role="button" and name "Start a run…"`). The editor's "offers none on a workflow never published, nor to a role
without run.start" passes at once (nothing offers it yet), and so does the form's Cancel: they pin what stays true.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/Workflows.tsx b/frontend/src/routes/Workflows.tsx
index d93dfa43..43bfb985 100644
--- a/frontend/src/routes/Workflows.tsx
+++ b/frontend/src/routes/Workflows.tsx
@@ -1,7 +1,8 @@
 // SPDX-License-Identifier: Apache-2.0
 // The workflows list (screen 1a; 4b rulings 4-7): each workflow's state at a glance, filters, the enable switch for
 // publishers, and export. No delete: no route deletes a workflow. 4c-3b adds the Trigger column (ruling 68: what starts
-// it besides a person) and, under a workflow's name, why it needs attention.
+// it besides a person) and, under a workflow's name, why it needs attention. 4e-2 adds Start… on each row that can start,
+// for the roles that hold run.start: the run form, then the new run's page.
 import * as Dropdown from "@radix-ui/react-dropdown-menu";
 import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
 import { Link, useNavigate } from "@tanstack/react-router";
@@ -15,11 +16,14 @@ import { Table, Td, Th } from "../components/Table";
 import { announce } from "../lib/announce";
 import { ApiError, client, ok } from "../lib/client";
 import { downloadJson, fileName } from "../lib/download";
+import { canStart, startable } from "../lib/runForm";
 import { RUN_STATUS, type Tone } from "../lib/runStatus";
 import { useDocumentTitle } from "../lib/title";
 import { attentionWords, triggerColumn } from "../lib/triggers";
 import { canEdit, canPublish, notPortable, since, tenantQuery, workflowsQuery, type PortableProblem, type WorkflowRow } from "../lib/workflows";
 import { NewWorkflow } from "./NewWorkflow";
+import { useLand } from "./runs/landing";
+import { LazyRunForm } from "./runs/LazyRuns";
 
 type Filter = "all" | "published" | "unpublished" | "attention";
 
@@ -84,6 +88,8 @@ export function WorkflowsPage({ tenantId, startNew = false }: { tenantId: string
   const [text, setText] = useState("");
   const [error, setError] = useState<string | null>(null);
   const [creating, setCreating] = useState(startNew);
+  const [starting, setStarting] = useState<WorkflowRow | null>(null);
+  const land = useLand(tenantId);
 
   function closeNew() {
     setCreating(false);
@@ -133,6 +139,7 @@ export function WorkflowsPage({ tenantId, startNew = false }: { tenantId: string
   const named = rows.filter((w) => w.name.toLowerCase().includes(text.trim().toLowerCase()));
   const shown = named.filter(FILTERS.find((f) => f.value === filter)!.keep);
   const publisher = canPublish(tenant.data?.role);
+  const starter = canStart(tenant.data?.role);
 
   return (
     <section className="flex flex-col gap-4 p-6">
@@ -202,28 +209,33 @@ export function WorkflowsPage({ tenantId, startNew = false }: { tenantId: string
                     <span className="text-small">{w.enabled ? "On" : "Off"}</span>
                   )}
                 </Td>
-                <Td className="text-right">
-                  <Dropdown.Root modal={false}>
-                    <Dropdown.Trigger aria-label={`Actions for ${w.name}`} className="inline-grid min-h-8 place-items-center rounded-md border border-line-strong bg-surface px-2 text-small text-ink hover:bg-surface-hover">
-                      <MoreIcon />
-                    </Dropdown.Trigger>
-                    <Dropdown.Portal>
-                      <Dropdown.Content align="end" sideOffset={4} className="min-w-40 rounded-lg border border-line bg-surface p-1 shadow-dialog">
-                        <Dropdown.Item
-                          onSelect={() => void navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: w.id } })}
-                          className="cursor-pointer rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
-                        >
-                          Open
-                        </Dropdown.Item>
-                        <Dropdown.Item
-                          onSelect={() => void exportOne(w)}
-                          className="cursor-pointer rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
-                        >
-                          Export
-                        </Dropdown.Item>
-                      </Dropdown.Content>
-                    </Dropdown.Portal>
-                  </Dropdown.Root>
+                <Td>
+                  <div className="flex items-center justify-end gap-2">
+                    {starter && startable(w) && (
+                      <Button size="sm" aria-haspopup="dialog" aria-label={`Start a run of ${w.name}`} onClick={() => setStarting(w)}>Start…</Button>
+                    )}
+                    <Dropdown.Root modal={false}>
+                      <Dropdown.Trigger aria-label={`Actions for ${w.name}`} className="inline-grid min-h-8 place-items-center rounded-md border border-line-strong bg-surface px-2 text-small text-ink hover:bg-surface-hover">
+                        <MoreIcon />
+                      </Dropdown.Trigger>
+                      <Dropdown.Portal>
+                        <Dropdown.Content align="end" sideOffset={4} className="min-w-40 rounded-lg border border-line bg-surface p-1 shadow-dialog">
+                          <Dropdown.Item
+                            onSelect={() => void navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: w.id } })}
+                            className="cursor-pointer rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
+                          >
+                            Open
+                          </Dropdown.Item>
+                          <Dropdown.Item
+                            onSelect={() => void exportOne(w)}
+                            className="cursor-pointer rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
+                          >
+                            Export
+                          </Dropdown.Item>
+                        </Dropdown.Content>
+                      </Dropdown.Portal>
+                    </Dropdown.Root>
+                  </div>
                 </Td>
               </tr>
             ))}
@@ -241,6 +253,7 @@ export function WorkflowsPage({ tenantId, startNew = false }: { tenantId: string
       </p>
       {/* Asked for by the address (?new) too: opened only once the role is known to create one. */}
       {creating && canEdit(tenant.data?.role) && <NewWorkflow tenantId={tenantId} onClose={closeNew} />}
+      {starting && <LazyRunForm tenantId={tenantId} workflow={starting} onStarted={land} onClose={() => setStarting(null)} />}
     </section>
   );
 }
diff --git a/frontend/src/routes/editor/Editor.tsx b/frontend/src/routes/editor/Editor.tsx
index e51b93a4..bd72b6a1 100644
--- a/frontend/src/routes/editor/Editor.tsx
+++ b/frontend/src/routes/editor/Editor.tsx
@@ -1,6 +1,6 @@
 // SPDX-License-Identifier: Apache-2.0
 // The editor (screen 1c): the draft, on a canvas, by pointer or keyboard alone (D16), saved as it changes (D17). Task 14
-// adds problems, Task 15 publishing and versions.
+// adds problems, Task 15 publishing and versions. 4e-2 adds Start a run…: the published version, never the draft.
 import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { Link, useBlocker, useMatch, useRouter } from "@tanstack/react-router";
 import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
@@ -20,6 +20,7 @@ import {
 import { begin, record, redo, undo, type History } from "../../lib/history";
 import { CARD, layout } from "../../lib/layout";
 import { guardLeaving } from "../../lib/leaving";
+import { canStart, startable } from "../../lib/runForm";
 import { runId } from "../../lib/runStatus";
 import type { Path } from "../../lib/schemaForm";
 import { ENDED, draftSnapshotQuery, freeze, type StepSummary } from "../../lib/simulations";
@@ -30,10 +31,12 @@ import {
   type Unapplied, type UnappliedKind,
 } from "../../lib/unapplied";  // prettier-ignore
 import {
-  canEdit, canPublish, nodeTypesQuery, notPortable, tenantQuery, versionsQuery, workflowQuery, type Diagnostic,
+  canEdit, canPublish, nodeTypesQuery, notPortable, tenantQuery, versionsQuery, workflowQuery, workflowsQuery, type Diagnostic,
   type GraphDoc, type GraphEdge, type GraphNode, type NodeType, type PortableProblem, type VersionDetail, type VersionRow,
   type WorkflowDetail,
 } from "../../lib/workflows";  // prettier-ignore
+import { useLand } from "../runs/landing";
+import { RunForm } from "../runs/RunForm";
 import { Canvas } from "./Canvas";
 import { NAV_KEYS, navModel, pathTo, type NavKey } from "./canvasNav";
 import { checkLabel, checkState, lastOf, type Check } from "./check";
@@ -462,6 +465,12 @@ function Editor({
   const simulation = useSimulation(tenantId, workflow.id);
   const simulator = canEdit(role) && viewing === null;
   const [simulateAt, setSimulateAt] = useState<{ revision: number; doc: GraphDoc } | null>(null); // the input, asked
+  // Starting the published version (4e-2; the run form design §5.1): where it can start, as the list says (read again
+  // after a publish), for the roles that hold run.start; the form warns when the draft differs.
+  const row = useQuery(workflowsQuery(tenantId)).data?.find((w) => w.id === workflow.id);
+  const starter = canStart(role) && viewing === null && row !== undefined && startable(row);
+  const [starting, setStarting] = useState(false);
+  const landOnRun = useLand(tenantId);
   const [saving, setSaving] = useState(false); // the save Simulate waits for
   // Its result on the canvas (§7.3): tags beside each step, under the banner, until "Hide the result", which hides this
   // simulation's only (the next one shows again).
@@ -1226,6 +1235,7 @@ function Editor({
             ◌ Simulate workflow
           </Button>
         )}
+        {starter && <Button size="md" aria-haspopup="dialog" onClick={() => setStarting(true)}>Start a run…</Button>}
         {publisher && viewing === null && (
           <Button
             ref={publishButton}
@@ -1532,6 +1542,12 @@ function Editor({
           onClose={() => setPicker(null)}
         />
       )}
+      {starting && (
+        <RunForm
+          tenantId={tenantId} workflow={{ id: workflow.id, name: workflow.name }} draftDiffers={sync.unpublished === true}
+          onStarted={landOnRun} onClose={() => setStarting(false)}
+        />
+      )}
       {simulateAt && (
         <SimulateDialog
           tenantId={tenantId}
diff --git a/frontend/src/routes/runs/Filters.tsx b/frontend/src/routes/runs/Filters.tsx
index b9b8b222..1a42085b 100644
--- a/frontend/src/routes/runs/Filters.tsx
+++ b/frontend/src/routes/runs/Filters.tsx
@@ -1,7 +1,8 @@
 // SPDX-License-Identifier: Apache-2.0
 // The Runs page's filters (editor 4e-1; the runs design §5.2; the ListStates board): "Label · Value ▾" menus, one
 // choice each, a set one outlined in the accent. The workflow is chosen from a list that can be searched: a native
-// modal dialog around cmdk, as the palette and the step picker are (D23).
+// modal dialog around cmdk, as the palette and the step picker are (D23). Start a run… chooses its workflow there too
+// (4e-2), among those that can start, without Any.
 import * as Dropdown from "@radix-ui/react-dropdown-menu";
 import { useQuery } from "@tanstack/react-query";
 import { Command } from "cmdk";
@@ -86,8 +87,9 @@ function Menu<T extends string>({ label, choices, value, onChange }: { label: st
   );
 }
 
-function Chooser({ workflows, value, onPick, onClose }: {
-  workflows: WorkflowRow[]; value: string | undefined; onPick: (id: string | undefined) => void; onClose: () => void;
+export function Chooser({ workflows, value, any = true, empty = "No workflow matches.", onPick, onClose }: {
+  workflows: WorkflowRow[]; value: string | undefined; any?: boolean; empty?: string;
+  onPick: (id: string | undefined) => void; onClose: () => void;
 }) {  // prettier-ignore
   const dialog = useRef<HTMLDialogElement>(null);
   useEffect(() => {
@@ -119,10 +121,12 @@ function Chooser({ workflows, value, onPick, onClose }: {
           className="w-full rounded-t-dialog border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2"
         />
         <Command.List className="max-h-96 overflow-y-auto p-1">
-          <Command.Empty className="px-3 py-2 text-body text-muted">No workflow matches.</Command.Empty>
-          <Command.Item value="Any" onSelect={() => pick(undefined)} className={`${PALETTE_ITEM} justify-start`}>
-            {chosen(value === undefined)}Any
-          </Command.Item>
+          <Command.Empty className="px-3 py-2 text-body text-muted">{empty}</Command.Empty>
+          {any && (
+            <Command.Item value="Any" onSelect={() => pick(undefined)} className={`${PALETTE_ITEM} justify-start`}>
+              {chosen(value === undefined)}Any
+            </Command.Item>
+          )}
           {workflows.map((w) => (
             <Command.Item key={w.id} value={`${w.name} ${w.id}`} onSelect={() => pick(w.id)} className={`${PALETTE_ITEM} justify-start`}>
               {chosen(value === w.id)}
diff --git a/frontend/src/routes/runs/LazyRuns.tsx b/frontend/src/routes/runs/LazyRuns.tsx
index e6c81f36..5b21e538 100644
--- a/frontend/src/routes/runs/LazyRuns.tsx
+++ b/frontend/src/routes/runs/LazyRuns.tsx
@@ -1,8 +1,10 @@
 // SPDX-License-Identifier: Apache-2.0
-// The Runs page's code and a run's page's, each loaded when it's opened, in its own chunk (the runs design §5.1).
-import type { ComponentType } from "react";
+// The Runs page's code and a run's page's, each loaded when it's opened, in its own chunk (the runs design §5.1). The
+// run form's too, opened from the Workflows list (4e-2b): the list's first load doesn't carry it.
+import type { ComponentProps, ComponentType } from "react";
 import { LazyPage } from "../../components/LazyPage";
 import type { RunFilters } from "../../lib/runs";
+import type { RunForm } from "./RunForm";
 
 type RunsProps = { tenantId: string; filters: RunFilters };
 type RunProps = { tenantId: string; runId: string };
@@ -14,3 +16,9 @@ export function LazyRunsPage(props: RunsProps) {
 export function LazyRunPage(props: RunProps) {
   return <LazyPage what="the run" load={(): Promise<ComponentType<RunProps>> => import("./RunPage").then((m) => m.RunPage)} props={props} />;
 }
+
+type RunFormProps = ComponentProps<typeof RunForm>;
+
+export function LazyRunForm(props: RunFormProps) {
+  return <LazyPage what="the run form" load={(): Promise<ComponentType<RunFormProps>> => import("./RunForm").then((m) => m.RunForm)} props={props} />;
+}
diff --git a/frontend/src/routes/runs/RunForm.tsx b/frontend/src/routes/runs/RunForm.tsx
index 5a5d3cc4..e77d965d 100644
--- a/frontend/src/routes/runs/RunForm.tsx
+++ b/frontend/src/routes/runs/RunForm.tsx
@@ -202,7 +202,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
           </p>
         )}
         <div className="flex flex-wrap justify-end gap-2">
-          <Button onClick={onClose}>Cancel</Button>
+          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
           <Button type="submit" variant={mode === "live" ? "live-outline" : "simulate"} disabled={form === null || sending}>
             {mode === "live" ? "Start the live run" : "◌ Start the simulation"}
           </Button>
diff --git a/frontend/src/routes/runs/RunPage.tsx b/frontend/src/routes/runs/RunPage.tsx
index 90c6ab7d..d5407f9e 100644
--- a/frontend/src/routes/runs/RunPage.tsx
+++ b/frontend/src/routes/runs/RunPage.tsx
@@ -33,6 +33,7 @@ import { useCanvasNav } from "../editor/useCanvasNav";
 import { RunBanner, RunBar } from "./RunBar";
 import { LoopResult, SeveralResult, StepResult } from "./RunResult";
 import { StartDrawer } from "./StartDrawer";
+import { useLanded } from "./landing";
 import { triggerOf, triggerWords } from "./trigger";
 import { useCancel } from "./useCancel";
 import { useRunReads } from "./useRunReads";
@@ -96,6 +97,7 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
   const types = useQuery(nodeTypesQuery);
   const tenant = useQuery(tenantQuery(tenantId));
   const cancel = useCancel(tenantId, id, r?.mode === "live");
+  useLanded(id, r !== undefined); // a run just started: its name takes focus once read (4e-2)
   // The graph it ran: its version's, or the draft a draft simulation froze for it. Neither ever changes.
   const version = useQuery({ ...versionQuery(tenantId, r?.workflow_id ?? "", r?.version_id ?? ""), enabled: !!r?.version_id });
   const snapshot = useQuery({ ...draftSnapshotQuery(tenantId, r?.workflow_id ?? "", r?.draft_snapshot_id ?? ""), enabled: !!r?.draft_snapshot_id });
diff --git a/frontend/src/routes/runs/RunsPage.tsx b/frontend/src/routes/runs/RunsPage.tsx
index 514514cc..a5eaf301 100644
--- a/frontend/src/routes/runs/RunsPage.tsx
+++ b/frontend/src/routes/runs/RunsPage.tsx
@@ -6,7 +6,8 @@
 // live in its address (§5.1); an empty list says what was asked, never that no run ever ran when the window hides them.
 // The first page is read again every 5 s while the page is visible; older pages, loaded on, aren't; each run is listed
 // once (`listed`). A refresh that fails keeps the list and says since when; a change is said once, through the shell's
-// live region (§5.6).
+// live region (§5.6). Start a run… (4e-2) asks for the workflow first, among those that can start, unless the Workflow
+// filter has chosen one that can.
 import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { Link, useNavigate } from "@tanstack/react-router";
 import { useEffect, useRef, useState } from "react";
@@ -16,11 +17,15 @@ import { Table, Td, Th } from "../../components/Table";
 import { When } from "../../components/When";
 import { announce } from "../../lib/announce";
 import { useNarrow } from "../../lib/media";
+import { canStart, startable } from "../../lib/runForm";
 import { PAGE, cursorOf, isEnded, listed, runsQuery, searchOf, type RunFilters, type RunItem } from "../../lib/runs";
 import { duration, reasonWords, runId } from "../../lib/runStatus";
 import { useDocumentTitle } from "../../lib/title";
 import { timeOf } from "../../lib/when";
-import { Filters } from "./Filters";
+import { tenantQuery, workflowsQuery, type WorkflowRow } from "../../lib/workflows";
+import { Chooser, Filters } from "./Filters";
+import { useLand } from "./landing";
+import { RunForm } from "./RunForm";
 import { triggerOf } from "./trigger";
 
 const WINDOW: Record<NonNullable<RunFilters["started"]>, string> = {
@@ -192,11 +197,20 @@ export function RunsPage({ tenantId, filters }: { tenantId: string; filters: Run
     }
   }
   const setFilters = (next: RunFilters) => void navigate({ to: "/t/$tenantId/runs", params: { tenantId }, search: searchOf(next) });
+  const tenant = useQuery(tenantQuery(tenantId));
+  const workflows = useQuery(workflowsQuery(tenantId));
+  const land = useLand(tenantId);
+  const can = (workflows.data ?? []).filter(startable);
+  const [starting, setStarting] = useState<"choose" | WorkflowRow | null>(null);
+  const start = () => setStarting(can.find((w) => w.id === filters.workflow) ?? "choose");
   const started = filters.started ?? "24h";
   return (
     <section className="flex flex-col gap-4 p-6">
       <div className="flex flex-wrap items-baseline justify-between gap-3">
-        <h1 className="text-h1 font-semibold">Runs</h1>
+        <div className="flex flex-wrap items-center gap-3">
+          <h1 className="text-h1 font-semibold">Runs</h1>
+          {canStart(tenant.data?.role) && <Button size="md" aria-haspopup="dialog" onClick={start}>Start a run…</Button>}
+        </div>
         {first.isRefetchError ? (
           <p className="flex flex-wrap items-center gap-2 text-small text-muted">
             {`Couldn't be refreshed · as of ${timeOf(first.dataUpdatedAt)}`}
@@ -207,6 +221,16 @@ export function RunsPage({ tenantId, filters }: { tenantId: string; filters: Run
         )}
       </div>
       <Filters tenantId={tenantId} filters={filters} onChange={setFilters} />
+      {starting === "choose" && (
+        <Chooser
+          workflows={can} value={undefined} any={false} empty="No workflow can start: it must be published, switched on and able to run."
+          onPick={(id) => setStarting(can.find((w) => w.id === id) ?? null)}
+          onClose={() => setStarting((s) => (s === "choose" ? null : s))}
+        />
+      )}
+      {starting !== null && starting !== "choose" && (
+        <RunForm tenantId={tenantId} workflow={starting} onStarted={land} onClose={() => setStarting(null)} />
+      )}
       {first.isPending ? (
         <p role="status" className="text-body text-muted">Reading the runs…</p>
       ) : first.isLoadingError ? (
diff --git a/frontend/src/routes/runs/landing.ts b/frontend/src/routes/runs/landing.ts
new file mode 100644
index 00000000..b0cb8475
--- /dev/null
+++ b/frontend/src/routes/runs/landing.ts
@@ -0,0 +1,33 @@
+// SPDX-License-Identifier: Apache-2.0
+// Landing on a run just started (editor 4e-2; the run form design §5.2): the form gives way to the run's page, whose
+// heading takes focus once it's shown. Only a page opened from a start is landed on, once: one opened any other way (a
+// link, back and forward) keeps the browser's focus. Asked in an effect, never while rendering, so StrictMode's second
+// pass finds it taken.
+import { useNavigate } from "@tanstack/react-router";
+import { useEffect } from "react";
+import { RUN_TITLE } from "./useCancel";
+
+let landing: string | null = null; // the run whose page is opening from a start
+
+/** Marks the run whose page opens next as landed on from a start. */
+export const landOn = (runId: string) => {
+  landing = runId;
+};
+
+/** Opens a run just started, its heading to take focus once its page shows it. */
+export function useLand(tenantId: string): (runId: string) => void {
+  const navigate = useNavigate();
+  return (runId) => {
+    landOn(runId);
+    void navigate({ to: "/t/$tenantId/runs/$runId", params: { tenantId, runId } });
+  };
+}
+
+/** On a run's page: once its heading is `shown`, it takes focus if a start landed here. */
+export function useLanded(runId: string, shown: boolean) {
+  useEffect(() => {
+    if (!shown || landing !== runId) return;
+    landing = null;
+    document.getElementById(RUN_TITLE)?.focus();
+  }, [runId, shown]);
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 263 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/routes
git commit -m "feat(editor): start a run from a workflow, the Runs page or the editor, and land on it (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4e-2b, milestone 1 (<date>)` to the ledger: each task's commit, its red and green results as run, any
mid-slice ruling. Commit it as `docs(editor-4): 4e-2b milestone 1`, with the trailer. **Pause** for the owner's review.

---

# Milestone 2 — A CSV start

### Task 5: A CSV file: uploaded, its columns proposed and chosen

**Spec:** §5.3 (before a file, reading, a file that can't be read, the columns, the saved columns stale, a required
column unmapped); the CsvStates and MoreStates boards.

**Files:**
- Create: `frontend/src/routes/runs/useCsvFile.ts`, `frontend/src/routes/runs/CsvFile.tsx`,
  `frontend/src/routes/runs/RunForm.csv.test.tsx`
- Modify: `frontend/src/routes/runs/RunForm.tsx`
- Modify: `frontend/src/lib/runForm.ts`, `frontend/src/lib/runForm.test.ts`

**Interfaces:**
- Consumes: Task 2's `uploadCsv`, `fileWords`, `mappingWords`; `Table`, `Th`, `Tag`, `controlClass`, `LINK_BUTTON`.
- Produces:
  - `lib/runForm.ts`: `type CsvColumnForm`; `uploadProblem(name, e, limits): { words; code: string | null }`;
    `holds(column)`; `staleWords(versionNumber, problems)`;
  - `useCsvFile.ts`: `type How = "saved" | "same name" | "left out"`; `type CsvFile` (`none` with its problem,
    `reading`, `staged` with its upload, mapping, how and the answer shown); `unmapped(columns, mapping)`;
    `useCsvFile(tenantId, workflowId)` → `{ file, choose(f, csv), map(column, header) }`; `csvReason(file, columns)`;
  - `CsvFile.tsx`: `CsvPart({ form, csv, file, onChoose, onMap })`.

A CSV workflow's form says what it reads and its limits, with "Choose a file" (and a drop zone). The file is uploaded
as it is; a file that can't be read says why, with its code (ruling 16). The columns table shows each column (ruling
14), the file's column chosen for it and how that was proposed (ruling 13); stale saved columns say so; a required
column without one is marked, and no row is checked until each has one. Start sends `csv: {upload_id, mapping}`
beside the other fields, never `skip_invalid`, and waits with its reason (ruling 21).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.test.ts b/frontend/src/lib/runForm.test.ts
index 83e24e4c..111a1ab9 100644
--- a/frontend/src/lib/runForm.test.ts
+++ b/frontend/src/lib/runForm.test.ts
@@ -2,8 +2,8 @@
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import { ApiError } from "./client";
 import {
-  canSaveColumns, canStart, cellWords, fileWords, keptValues, keyFor, mappingWords, previewCsv, refusalOf, rerunRun, saveColumns,
-  startRun, startable, uploadCsv, type StartForm,
+  canSaveColumns, canStart, cellWords, fileWords, holds, keptValues, keyFor, mappingWords, previewCsv, refusalOf, rerunRun,
+  saveColumns, staleWords, startRun, startable, uploadCsv, uploadProblem, type StartForm,
 } from "./runForm";  // prettier-ignore
 
 let sent: Request[];
@@ -138,3 +138,33 @@ describe("a CSV file's words (§5.3)", () => {
     expect(mappingWords("required_unmapped")).toBe("Required: choose the file's column for it.");
   });
 });
+
+describe("a CSV file's columns and problems, in words (§5.3; the CsvStates and MoreStates boards)", () => {
+  const limits = { max_rows: 10_000, max_bytes: 5 * 1024 * 1024 };
+  it("says what a file can't be, by its name, and what to do", () => {
+    expect(uploadProblem("sites.csv", refused(422, { error: "csv_duplicate_header" }), limits)).toEqual({
+      words: "sites.csv can't be read: it has two columns with the same name. Rename one and choose the file again.", code: "csv_duplicate_header",
+    });  // prettier-ignore
+    expect(uploadProblem("all.csv", refused(413, { error: "too_large" }), limits).words).toBe("all.csv is over 5 MB, this workflow's limit. Split it, or keep only the rows to run.");
+    expect(uploadProblem("all.csv", refused(503, { error: "csv_busy" }), limits).words).toBe(
+      "The server is busy reading other files. Nothing was kept. Choose the file again in a moment.",
+    );
+    expect(uploadProblem("a.csv", new TypeError("Failed to fetch"), limits)).toEqual({ words: "The server didn't answer: a.csv wasn't read. Choose it again.", code: null });
+    expect(uploadProblem("a.csv", refused(409, { error: "workflow_disabled", messages: ["…"] }), limits).words).toBe("a.csv wasn't read. The workflow is disabled.");
+  });
+
+  it("says what each column holds", () => {
+    const col = (type: string, over: object = {}) => ({ header: "H", name: "h", type, required: false, sensitive: false, ...over });
+    expect(holds(col("string"))).toBe("Text");
+    expect(holds(col("integer"))).toBe("A whole number");
+    expect(holds(col("ip"))).toBe("An IP address");
+    expect(holds(col("enum", { values: ["FR", "DE", "ES", "IT", "GB", "US", "NL"] }))).toBe("One of a list: FR, DE, ES, IT, GB, US…");
+    expect(holds(col("enum", { values: ["FR", "DE"] }))).toBe("One of a list: FR, DE");
+  });
+
+  it("says why the saved columns no longer fit", () => {
+    expect(staleWords(7, [{ column: "site_ref", code: "unknown_column" }, { column: "name", code: "required_unmapped" }])).toBe(
+      "The columns saved for this workflow no longer fit version 7: it doesn't read site_ref any more, and it needs name, which they leave out. The file's columns with the same names are proposed instead; check them.",
+    );
+  });
+});
diff --git a/frontend/src/routes/runs/RunForm.csv.test.tsx b/frontend/src/routes/runs/RunForm.csv.test.tsx
new file mode 100644
index 00000000..7a43885b
--- /dev/null
+++ b/frontend/src/routes/runs/RunForm.csv.test.tsx
@@ -0,0 +1,187 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render, screen, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { onAnnounce } from "../../lib/announce";
+import type { CsvUpload, StartForm } from "../../lib/runForm";
+import { local } from "../../test/runs";
+import { RunForm } from "./RunForm";
+
+// The CsvStates board's workflow: five columns, two required.
+const COLUMNS = [
+  { header: "Site name", name: "name", type: "string", required: true, sensitive: false },
+  { header: "Country", name: "country_code", type: "enum", required: true, sensitive: false, values: ["FR", "DE", "ES", "IT", "GB", "US", "NL"] },
+  { header: "address", name: "address", type: "string", required: false, sensitive: false },
+  { header: "Gateway", name: "gateway_ip", type: "ip", required: false, sensitive: false },
+  { header: "VLAN", name: "vlan_id", type: "integer", required: false, sensitive: false },
+];  // prettier-ignore
+const FORM: StartForm = {
+  workflow_id: "w1", version_id: "v7", version_number: 7, published_at: local(9, 12, 0), published_by: "nadia@corp.test", fields: [],
+  csv: { max_rows: 10_000, max_bytes: 5 * 1024 * 1024, columns: COLUMNS },
+};  // prettier-ignore
+const HEADERS = ["Site name", "Country", "address", "Gateway", "Notes", "Region"];
+const SAVED = { name: "Site name", country_code: "Country", address: "address", gateway_ip: "Gateway" };
+/** An upload's answer: every row passes unless `over` says otherwise. */
+const upload = (over: Partial<CsvUpload> = {}): CsvUpload => ({
+  version_id: "v7", upload_id: "u1", expires_at: local(11, 0, 0), headers: HEADERS, row_count: 2431, mapping: SAVED,
+  default_mapping: { status: "applied" }, problems: [], masked_columns: [], preview: [], errors: [], error_count: 0,
+  error_groups: [], rows_with_errors: 0, ...over,
+});  // prettier-ignore
+
+let uploads: { type: string | null; body: string }[];
+let starts: unknown[];
+let uploadAnswer: () => Promise<Response>;
+let said: string[];
+let stop: () => void;
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+beforeEach(() => {
+  uploads = [];
+  starts = [];
+  said = [];
+  uploadAnswer = () => Promise.resolve(json(upload(), 201));
+  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
+  stop = onAnnounce((m) => said.push(m));
+  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
+    const request = input as Request;
+    const path = new URL(request.url).pathname;
+    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(FORM);
+    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads") {
+      uploads.push({ type: request.headers.get("Content-Type"), body: await request.text() });
+      return uploadAnswer();
+    }
+    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/runs") {
+      starts.push(JSON.parse(await request.text()));
+      return json({ id: "r1" }, 202);
+    }
+    return json({ error: "not_found" }, 404);
+  });
+});
+afterEach(() => {
+  stop();
+  vi.restoreAllMocks();
+});
+
+function show() {
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  render(
+    <QueryClientProvider client={qc}>
+      <RunForm tenantId="t1" workflow={{ id: "w1", name: "Bulk site creation" }} onStarted={vi.fn()} onClose={vi.fn()} />
+    </QueryClientProvider>,
+  );
+}
+const FILE = () => new File(["Site name,Country\nLyon,FR\n"], "sites-q4.csv", { type: "text/csv" });
+async function choose(file = FILE()) {
+  const user = userEvent.setup();
+  await user.upload(await screen.findByLabelText("Choose a file"), file);
+  return user;
+}
+/** The columns' table, row by row: the column, the file's column chosen, how it was proposed. */
+const columnRows = () =>
+  within(screen.getByRole("region", { name: "Columns" })).getAllByRole("row").slice(1).map((r) => {
+    const select = within(r).getByRole<HTMLSelectElement>("combobox");
+    return [r.querySelector("th")?.textContent, select.selectedOptions[0]?.textContent, r.querySelector("td:last-child")?.textContent];
+  });  // prettier-ignore
+
+describe("a CSV workflow's file (the run form design §5.3; the CsvStates board)", () => {
+  it("says what it reads and its limits before a file, and Start waits for one", async () => {
+    show();
+    expect(await screen.findByText("This workflow starts from a CSV file: one run, one pass of its loop per row.")).toBeTruthy();
+    expect(screen.getByText("Up to 10,000 rows and 5 MB · comma, semicolon or tab separated · UTF-8")).toBeTruthy();
+    const reads = within(screen.getByRole("region", { name: "The columns it reads" })).getAllByRole("row").slice(1);
+    expect(reads.map((r) => [...r.querySelectorAll("th, td")].map((c) => c.textContent))).toEqual([
+      ["Site name requiredname", "Text"],
+      ["Country requiredcountry_code", "One of a list: FR, DE, ES, IT, GB, US…"],
+      ["address", "Text"],
+      ["Gatewaygateway_ip", "An IP address"],
+      ["VLANvlan_id", "A whole number"],
+    ]);
+    const start = screen.getByRole("button", { name: "Start the live run" });
+    expect(start).toHaveProperty("disabled", true);
+    expect(document.getElementById(start.getAttribute("aria-describedby")!)?.textContent).toBe("Choose a file first.");
+  });
+
+  it("uploads the file as it is, says it's reading, then proposes the file's columns, saying how", async () => {
+    let answer!: (r: Response) => void;
+    uploadAnswer = () => new Promise((r) => (answer = r));
+    show();
+    await choose();
+    expect(uploads).toEqual([{ type: "text/csv", body: "Site name,Country\nLyon,FR\n" }]);
+    expect(screen.getByText("sites-q4.csv · 1 KB")).toBeTruthy();
+    expect(said).toContain("Reading the file…");
+    answer(json(upload(), 201));
+    expect(await screen.findByText("sites-q4.csv · 2,431 rows · 6 columns")).toBeTruthy();
+    expect(columnRows()).toEqual([
+      ["Site name requiredname", "Site name", "saved"],
+      ["Country requiredcountry_code", "Country", "saved"],
+      ["address", "address", "saved"],
+      ["Gatewaygateway_ip", "Gateway", "saved"],
+      ["VLANvlan_id", "Not used", "left out"],
+    ]);
+    expect(screen.getByLabelText("Choose another file")).toBeTruthy();
+  });
+
+  it("starts with the staged file and its columns, never skipping a row", async () => {
+    show();
+    const user = await choose();
+    await screen.findByRole("region", { name: "Columns" });
+    await user.click(screen.getByRole("button", { name: /^Start the live run/ }));
+    expect(starts).toEqual([{ input: {}, mode: "live", expected_version_id: "v7", csv: { upload_id: "u1", mapping: SAVED } }]);
+  });
+
+  it("says the file's columns with the same names are proposed when none are saved", async () => {
+    uploadAnswer = () => Promise.resolve(json(upload({ default_mapping: { status: "none" }, mapping: { address: "address" } }), 201));
+    show();
+    await choose();
+    await screen.findByRole("region", { name: "Columns" });
+    expect(columnRows().map((r) => r[2])).toEqual(["left out", "left out", "same name", "left out", "left out"]);
+  });
+
+  it("says a file can't be read, why, with its code, and asks for another", async () => {
+    uploadAnswer = () => Promise.resolve(json({ error: "csv_duplicate_header", messages: ["…"] }, 422));
+    show();
+    await choose();
+    const alert = await screen.findByRole("alert");
+    expect(alert.textContent).toBe("sites-q4.csv can't be read: it has two columns with the same name. Rename one and choose the file again. csv_duplicate_header");
+    expect(screen.getByLabelText("Choose a file")).toBeTruthy();
+    expect(screen.getByRole("region", { name: "The columns it reads" })).toBeTruthy();
+  });
+
+  it("says the server is busy, keeping nothing", async () => {
+    uploadAnswer = () => Promise.resolve(json({ error: "csv_busy", messages: ["…"] }, 503));
+    show();
+    await choose();
+    expect((await screen.findByRole("alert")).textContent).toBe("The server is busy reading other files. Nothing was kept. Choose the file again in a moment. csv_busy");
+  });
+
+  it("says the saved columns no longer fit this version, the same names proposed instead (the MoreStates board)", async () => {
+    uploadAnswer = () => Promise.resolve(json(upload({ default_mapping: { status: "stale", problems: [{ column: "site_ref", code: "unknown_column" }] } }), 201));
+    show();
+    await choose();
+    expect(
+      await screen.findByText(
+        "The columns saved for this workflow no longer fit version 7: it doesn't read site_ref any more. The file's columns with the same names are proposed instead; check them.",
+      ),
+    ).toBeTruthy();
+  });
+
+  it("marks a required column without the file's column, and checks no row until it has one (the MoreStates board)", async () => {
+    const partial = { name: "Site name", address: "address", gateway_ip: "Gateway" }; // no Country
+    uploadAnswer = () => Promise.resolve(json(upload({ mapping: partial, problems: [{ column: "country_code", code: "required_unmapped" }] }), 201));
+    show();
+    await choose();
+    const select = await screen.findByRole("combobox", { name: "Country, from the file's column" });
+    expect((select as HTMLSelectElement).selectedOptions[0]?.textContent).toBe("Choose a column");
+    expect(document.getElementById(select.getAttribute("aria-describedby")!)?.textContent).toBe("Required: choose the file's column for it.");
+    expect(screen.getByText("No row is checked until every required column is mapped.")).toBeTruthy();
+  });
+
+  it("says beside a column that the file has no such column", async () => {
+    uploadAnswer = () => Promise.resolve(json(upload({ mapping: { ...SAVED, gateway_ip: "GW" }, problems: [{ column: "gateway_ip", code: "unknown_header" }] }), 201));
+    show();
+    await choose();
+    const select = await screen.findByRole("combobox", { name: "Gateway, from the file's column" });
+    expect((select as HTMLSelectElement).selectedOptions[0]?.textContent).toBe("GW");
+    expect(document.getElementById(select.getAttribute("aria-describedby")!)?.textContent).toBe("The file has no such column.");
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunForm.csv.test.tsx src/routes/runs/RunForm.test.tsx
src/lib/runForm.test.ts`

Expected: FAIL, 12 failed and 27 passed: `uploadProblem`, `holds` and `staleWords` don't exist (`(0 , uploadProblem) is
not a function`); a CSV workflow's form says nothing of its file and has no "Choose a file" (`Unable to find a label
with the text of: Choose a file`, nine tests). The typed form's tests pass.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.ts b/frontend/src/lib/runForm.ts
index 4ac3e8ea..344eb99e 100644
--- a/frontend/src/lib/runForm.ts
+++ b/frontend/src/lib/runForm.ts
@@ -161,6 +161,55 @@ export function fileWords(code: string, limits: { max_rows: number; max_bytes: n
   }
 }
 
+const FILE_HINTS: Record<string, string> = {
+  csv_encoding: "Save it as UTF-8 and choose it again.",
+  csv_duplicate_header: "Rename one and choose the file again.",
+  csv_malformed: "Fix it and choose it again.",
+  csv_too_many_rows: "Split it, or keep only the rows to run.",
+  too_large: "Split it, or keep only the rows to run.",
+  csv_too_large: "Split it, or keep only the rows to run.",
+};
+const FILE_CODES = new Set(["csv_encoding", "csv_empty", "csv_duplicate_header", "csv_malformed", "csv_too_many_rows", "too_large", "csv_too_large"]);
+const OVER = new Set(["csv_too_many_rows", "too_large", "csv_too_large"]); // read, but past a limit
+
+/** Why an upload of the file `name` gave nothing to map (§5.3; the CsvStates and MoreStates boards): what it can't be and
+ * what to do, with its code (none when the server didn't answer). */
+export function uploadProblem(name: string, e: unknown, limits: { max_rows: number; max_bytes: number }): { words: string; code: string | null } {
+  if (!(e instanceof ApiError)) return { words: `The server didn't answer: ${name} wasn't read. Choose it again.`, code: null };
+  if (e.code === "csv_busy") return { words: "The server is busy reading other files. Nothing was kept. Choose the file again in a moment.", code: e.code };
+  if (FILE_CODES.has(e.code)) {
+    const hint = FILE_HINTS[e.code] ?? "Choose another file.";
+    const what = fileWords(e.code, limits);
+    return { words: OVER.has(e.code) ? `${name} ${what}. ${hint}` : `${name} can't be read: it ${what}. ${hint}`, code: e.code };
+  }
+  return { words: `${name} wasn't read. ${refusalOf(e).words.replace(/ Nothing started\.$/, "")}`, code: e.code };
+}
+
+/** A declared column, as the form shows it: the start form's `csv.columns`. */
+export type CsvColumnForm = NonNullable<StartForm["csv"]>["columns"][number];
+
+const HOLDS: Record<string, string> = {
+  string: "Text", integer: "A whole number", number: "A number", boolean: "Yes or no", mac: "A MAC address", ip: "An IP address",
+  cidr: "A network in CIDR form",
+};  // prettier-ignore
+/** What a column holds, in words: its type, a list's first six values. */
+export function holds(c: CsvColumnForm): string {
+  if (c.type === "enum") {
+    const values = c.values ?? [];
+    return `One of a list: ${values.slice(0, 6).join(", ")}${values.length > 6 ? "…" : ""}`;
+  }
+  return Object.hasOwn(HOLDS, c.type) ? HOLDS[c.type]! : c.type;
+}
+
+/** Why the columns saved for the workflow weren't proposed (`default_mapping.status` stale), for version `n`. */
+export function staleWords(n: number, problems: { column: string; code: string }[]): string {
+  const why = problems.map((p) =>
+    p.code === "unknown_column" ? `it doesn't read ${p.column} any more` : p.code === "required_unmapped" ? `it needs ${p.column}, which they leave out` : `${p.column}: ${mappingWords(p.code)}`,
+  );  // prettier-ignore
+  const said = why.length < 2 ? (why[0] ?? "") : `${why.slice(0, -1).join(", ")}, and ${why.at(-1)!}`;
+  return `The columns saved for this workflow no longer fit version ${n}: ${said}. The file's columns with the same names are proposed instead; check them.`;
+}
+
 const CELL_WORDS: Record<string, string> = {
   required: "Missing: a value is required",
   cell_count: "Has more or fewer cells than the header",
diff --git a/frontend/src/routes/runs/CsvFile.tsx b/frontend/src/routes/runs/CsvFile.tsx
new file mode 100644
index 00000000..b31f6e58
--- /dev/null
+++ b/frontend/src/routes/runs/CsvFile.tsx
@@ -0,0 +1,162 @@
+// SPDX-License-Identifier: Apache-2.0
+// A CSV run's file in the run form (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): what
+// the workflow reads before a file, the file being read, why one can't be, and the file's column chosen for each of the
+// workflow's, with how it was proposed.
+import { useId, type ChangeEvent, type DragEvent } from "react";
+import { LINK_BUTTON } from "../../components/Button";
+import { controlClass } from "../../components/Field";
+import { Table, Th } from "../../components/Table";
+import { Tag } from "../../components/Tag";
+import { mbOf } from "../../lib/csv";
+import { holds, mappingWords, staleWords, type CsvColumnForm, type StartForm } from "../../lib/runForm";
+import { unmapped, type CsvFile } from "./useCsvFile";
+
+type Csv = NonNullable<StartForm["csv"]>;
+
+const count = (x: number) => x.toLocaleString("en-US");
+const sizeOf = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
+const ROW_HEAD = "border-t border-line px-3 py-2.5 text-left align-top font-normal";
+const CELL = "border-t border-line px-3 py-2.5 align-top";
+
+/** A declared column: its header, what it is, and its name when the header isn't it. */
+function ColumnName({ c }: { c: CsvColumnForm }) {
+  return (
+    <>
+      <span className="block">
+        {c.header}
+        {c.required && <> <Tag>required</Tag></>}
+        {c.sensitive && <> <Tag>sensitive</Tag></>}
+      </span>
+      {c.name !== c.header && <span className="block font-mono text-meta text-muted">{c.name}</span>}
+    </>
+  );
+}
+
+/** The file chooser, as a button: a file chosen again is read again. */
+function Choose({ label, onChoose }: { label: string; onChoose: (f: File) => void }) {
+  const picked = (e: ChangeEvent<HTMLInputElement>) => {
+    const f = e.target.files?.[0];
+    e.target.value = "";
+    if (f) onChoose(f);
+  };
+  return (
+    <label className={`${LINK_BUTTON} cursor-pointer focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-focus`}>
+      {label}
+      <input type="file" accept=".csv,text/csv" className="sr-only" onChange={picked} />
+    </label>
+  );
+}
+
+function Reads({ csv }: { csv: Csv }) {
+  return (
+    <Table label="The columns it reads">
+      <thead>
+        <tr><Th>Column</Th><Th>Holds</Th></tr>
+      </thead>
+      <tbody>
+        {csv.columns.map((c) => (
+          <tr key={c.name}>
+            <th scope="row" className={ROW_HEAD}><ColumnName c={c} /></th>
+            <td className={`${CELL} text-small`}>{holds(c)}</td>
+          </tr>
+        ))}
+      </tbody>
+    </Table>
+  );
+}
+
+function Columns({ csv, file, onMap }: { csv: Csv; file: Extract<CsvFile, { phase: "staged" }>; onMap: (column: string, header: string) => void }) {
+  const id = useId();
+  const missing = new Set(unmapped(csv.columns, file.mapping));
+  // A problem the server found under the columns chosen now: an answer for other columns says nothing of these.
+  const problem = (c: CsvColumnForm) => file.shown.problems.find((p) => p.column === c.name && file.shown.mapping[c.name] === file.mapping[c.name]);
+  return (
+    <>
+      <div className="flex flex-col gap-1">
+        <h3 className="text-small font-semibold">Columns</h3>
+        <p className="text-small text-muted">Each column the workflow reads, and the file&apos;s column it comes from.</p>
+      </div>
+      <Table label="Columns">
+        <thead>
+          <tr><Th>Column</Th><Th>From the file&apos;s</Th><Th>How</Th></tr>
+        </thead>
+        <tbody>
+          {csv.columns.map((c, i) => {
+            const chosen = file.mapping[c.name] ?? "";
+            const error = missing.has(c.name) ? mappingWords("required_unmapped") : problem(c) ? mappingWords(problem(c)!.code) : undefined;
+            const errorId = `${id}-${i}-err`;
+            return (
+              <tr key={c.name}>
+                <th scope="row" className={ROW_HEAD}><ColumnName c={c} /></th>
+                <td className={CELL}>
+                  <select
+                    aria-label={`${c.header}, from the file's column`} aria-invalid={!!error} aria-describedby={error ? errorId : undefined}
+                    value={chosen} onChange={(e) => onMap(c.name, e.target.value)} className={`${controlClass(!!error)} min-w-40`}
+                  >
+                    <option value="">{c.required ? "Choose a column" : "Not used"}</option>
+                    {chosen && !file.upload.headers.includes(chosen) && <option value={chosen}>{chosen}</option>}
+                    {file.upload.headers.map((h) => <option key={h} value={h}>{h}</option>)}
+                  </select>
+                  {error && <p id={errorId} className="mt-1 text-small text-danger">{error}</p>}
+                </td>
+                <td className={`${CELL} text-small text-muted`}>{file.how[c.name] ?? ""}</td>
+              </tr>
+            );  // prettier-ignore
+          })}
+        </tbody>
+      </Table>
+      {missing.size > 0 && <p className="text-small">No row is checked until every required column is mapped.</p>}
+    </>
+  );
+}
+
+export function CsvPart({ form, csv, file, onChoose, onMap }: {
+  form: StartForm; csv: Csv; file: CsvFile; onChoose: (f: File) => void; onMap: (column: string, header: string) => void;
+}) {  // prettier-ignore
+  const drop = (e: DragEvent) => {
+    e.preventDefault();
+    const f = e.dataTransfer.files[0];
+    if (f) onChoose(f);
+  };
+  if (file.phase === "reading") {
+    return (
+      <div className="flex flex-col gap-1">
+        <p className="text-small font-medium">{`${file.name} · ${sizeOf(file.size)}`}</p>
+        <p className="text-small text-muted">Reading the file…</p>
+      </div>
+    );
+  }
+  if (file.phase === "staged") {
+    const stale = file.upload.default_mapping.status === "stale";
+    return (
+      <div className="flex flex-col gap-3">
+        <div className="flex flex-wrap items-center justify-between gap-2">
+          <p className="text-small font-medium">{`${file.name} · ${count(file.upload.row_count)} rows · ${file.upload.headers.length} columns`}</p>
+          <Choose label="Choose another file" onChoose={onChoose} />
+        </div>
+        {stale && <p className="text-small">{staleWords(form.version_number, file.upload.default_mapping.problems ?? [])}</p>}
+        <Columns csv={csv} file={file} onMap={onMap} />
+      </div>
+    );
+  }
+  return (
+    <div className="flex flex-col gap-3">
+      <p className="text-small">This workflow starts from a CSV file: one run, one pass of its loop per row.</p>
+      <div onDragOver={(e) => e.preventDefault()} onDrop={drop} className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-line-strong px-4 py-6 text-center">
+        <p className="flex flex-wrap items-center justify-center gap-2 text-small">
+          Drop a CSV file here, or
+          <Choose label="Choose a file" onChoose={onChoose} />
+        </p>
+        <p className="text-small text-muted">{`Up to ${count(csv.max_rows)} rows and ${mbOf(csv.max_bytes)} MB · comma, semicolon or tab separated · UTF-8`}</p>
+      </div>
+      {file.problem && (
+        <p role="alert" className="text-small text-danger">
+          {file.problem.words}
+          {file.problem.code && <> <span className="font-mono">{file.problem.code}</span></>}
+        </p>
+      )}
+      <h3 className="text-small font-semibold">The columns it reads</h3>
+      <Reads csv={csv} />
+    </div>
+  );
+}
diff --git a/frontend/src/routes/runs/RunForm.tsx b/frontend/src/routes/runs/RunForm.tsx
index e77d965d..cc0cbf2f 100644
--- a/frontend/src/routes/runs/RunForm.tsx
+++ b/frontend/src/routes/runs/RunForm.tsx
@@ -3,6 +3,7 @@
 // form, live or simulated, in the Simulate dialog's look. The version it shows is the one it starts: the start goes
 // with that version's id (B14), and a version published meanwhile is read and shown, the values that still fit kept.
 // Each submitted form goes under one key, sent again under it only when the same form is (an answer lost on the way).
+// A workflow that declares a CSV starts only with its file (§5.3, CsvPart), any other fields beside it.
 import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { useEffect, useId, useRef, useState, type FormEvent } from "react";
 import { Button } from "../../components/Button";
@@ -11,6 +12,8 @@ import { When } from "../../components/When";
 import { keptValues, keyFor, refusalOf, startRun, type Refusal, type Sent, type StartBody, type StartForm } from "../../lib/runForm";
 import { startFormQuery } from "../../lib/triggers";
 import { SimBanner } from "../editor/simulation/SimBanner";
+import { CsvPart } from "./CsvFile";
+import { csvReason, useCsvFile } from "./useCsvFile";
 import { InputControl, REQUIRED, fieldKey, fromFields, hintOf, labelOf, startValues, wholeOf } from "../editor/startInput";
 
 type Mode = StartBody["mode"];
@@ -74,6 +77,8 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
   const [last, setLast] = useState<Sent | null>(null);
   const [sending, setSending] = useState(false);
   const shownJson = jsonText ?? "";
+  const csv = useCsvFile(tenantId, workflow.id);
+  const reason = form?.csv ? csvReason(csv.file, form.csv.columns) : null;
 
   // Focus goes to the first field once the form is read (§5.6); before, the dialog holds it.
   const formRead = form !== null;
@@ -93,7 +98,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
 
   async function submit(e: FormEvent) {
     e.preventDefault();
-    if (!form || sending) return;
+    if (!form || sending || reason !== null) return;
     let input: Record<string, unknown>;
     if (asJson) {
       const whole = wholeOf(shownJson);
@@ -105,6 +110,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
       input = made.input;
     }
     const body: StartBody = { input, mode, expected_version_id: form.version_id };
+    if (form.csv && csv.file.phase === "staged") body.csv = { upload_id: csv.file.upload.upload_id, mapping: csv.file.mapping };
     const sent = keyFor(last, body);
     setLast(sent);
     setErrors({});
@@ -166,6 +172,9 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
             )}
             <ModeChoice mode={mode} onChange={setMode} />
             <div ref={fieldsRef} className="flex flex-col gap-4">
+              {form.csv && (
+                <CsvPart form={form} csv={form.csv} file={csv.file} onChoose={(f) => void csv.choose(f, form.csv!)} onMap={csv.map} />
+              )}
               {asJson ? (
                 <TextArea
                   label="The input, as JSON"
@@ -178,7 +187,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
                 />
               ) : (
                 <>
-                  {form.fields.length === 0 && <p className="text-small text-muted">This version takes no input.</p>}
+                  {form.fields.length === 0 && !form.csv && <p className="text-small text-muted">This version takes no input.</p>}
                   {form.fields.map((f) => (
                     <InputControl
                       key={f.name} f={f} value={shownValues.get(f.name)} error={errors[fieldKey(f.name)]} label={labelOf(f)} hint={hintOf(f)}
@@ -188,11 +197,13 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
                 </>
               )}
             </div>
-            <div>
-              <Button size="sm" aria-pressed={asJson} onClick={() => (asJson ? (setAsJson(false), setJsonText(null)) : toJson())}>
-                Edit as JSON
-              </Button>
-            </div>
+            {(form.fields.length > 0 || !form.csv) && (
+              <div>
+                <Button size="sm" aria-pressed={asJson} onClick={() => (asJson ? (setAsJson(false), setJsonText(null)) : toJson())}>
+                  Edit as JSON
+                </Button>
+              </div>
+            )}
           </>
         )}
         {refusal && (
@@ -201,9 +212,13 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
             {CODED(refusal.code) && <> <span className="font-mono">{refusal.code}</span></>}
           </p>
         )}
-        <div className="flex flex-wrap justify-end gap-2">
+        <div className="flex flex-wrap items-center justify-end gap-2">
+          {reason && <p id={`${id}-reason`} className="me-auto text-small text-muted">{reason}</p>}
           <Button onClick={() => dialog.current?.close()}>Cancel</Button>
-          <Button type="submit" variant={mode === "live" ? "live-outline" : "simulate"} disabled={form === null || sending}>
+          <Button
+            type="submit" variant={mode === "live" ? "live-outline" : "simulate"} disabled={form === null || sending || reason !== null}
+            aria-describedby={reason ? `${id}-reason` : undefined}
+          >
             {mode === "live" ? "Start the live run" : "◌ Start the simulation"}
           </Button>
         </div>
diff --git a/frontend/src/routes/runs/useCsvFile.ts b/frontend/src/routes/runs/useCsvFile.ts
new file mode 100644
index 00000000..bea8e401
--- /dev/null
+++ b/frontend/src/routes/runs/useCsvFile.ts
@@ -0,0 +1,62 @@
+// SPDX-License-Identifier: Apache-2.0
+// A CSV run's file (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): chosen, uploaded as it
+// is, read by the server against the version's columns, the file's columns proposed for them (saved, or the same names),
+// and the person's choice of each. The upload's answer says what keeps the file from building rows.
+import { useRef, useState } from "react";
+import { announce } from "../../lib/announce";
+import { uploadCsv, uploadProblem, type CsvColumnForm, type CsvPreview, type CsvUpload, type Mapping } from "../../lib/runForm";
+
+/** How a column's choice was made: proposed from the saved columns, by the same name, or left out; the person's own
+ * choice says nothing. */
+export type How = "saved" | "same name" | "left out";
+
+export type CsvFile =
+  | { phase: "none"; problem: { words: string; code: string | null } | null }
+  | { phase: "reading"; name: string; size: number }
+  | { phase: "staged"; name: string; upload: CsvUpload; mapping: Mapping; how: Partial<Record<string, How>>; shown: CsvPreview };
+
+/** The required columns `mapping` gives no file's column: no row is built without them. */
+export const unmapped = (columns: CsvColumnForm[], mapping: Mapping) => columns.filter((c) => c.required && !mapping[c.name]).map((c) => c.name);
+
+const howOf = (columns: CsvColumnForm[], upload: CsvUpload): Partial<Record<string, How>> =>
+  Object.fromEntries(columns.map((c) => [c.name, !upload.mapping[c.name] ? "left out" : upload.default_mapping.status === "applied" ? "saved" : "same name"]));
+
+export function useCsvFile(tenantId: string, workflowId: string) {
+  const [file, setFile] = useState<CsvFile>({ phase: "none", problem: null });
+  const chosen = useRef(0); // the files chosen: an answer for one chosen since is dropped
+
+  async function choose(f: File, csv: { columns: CsvColumnForm[]; max_rows: number; max_bytes: number }) {
+    const n = ++chosen.current;
+    setFile({ phase: "reading", name: f.name, size: f.size });
+    announce("Reading the file…");
+    try {
+      const upload = await uploadCsv(tenantId, workflowId, f);
+      if (n !== chosen.current) return;
+      setFile({ phase: "staged", name: f.name, upload, mapping: upload.mapping, how: howOf(csv.columns, upload), shown: upload });
+    } catch (e) {
+      if (n === chosen.current) setFile({ phase: "none", problem: uploadProblem(f.name, e, csv) });
+    }
+  }
+
+  /** The file's column chosen for `column` ("" for none). */
+  function map(column: string, header: string) {
+    setFile((f) => {
+      if (f.phase !== "staged") return f;
+      const mapping = { ...f.mapping };
+      if (header) mapping[column] = header;
+      else delete mapping[column];
+      return { ...f, mapping, how: { ...f.how, [column]: undefined } };
+    });
+  }
+
+  return { file, choose, map };
+}
+
+/** Why a CSV start can't go ahead yet, or null (§5.3): said beside Start, which waits. */
+export function csvReason(file: CsvFile, columns: CsvColumnForm[]): string | null {
+  if (file.phase !== "staged") return "Choose a file first.";
+  if (unmapped(columns, file.mapping).length > 0) return "Choose the file's column for every required column first.";
+  if (file.shown.problems.length > 0) return "Fix the columns marked first.";
+  if (file.shown.error_count > 0) return "Every row must pass first.";
+  return null;
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 39 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib frontend/src/routes
git commit -m "feat(editor): a CSV workflow's file, uploaded, its columns proposed and chosen (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: A CSV file checked: its errors, its first rows, its columns saved

**Spec:** §5.3 (a change checks every row again, the errors at a glance, every row passing, Start, the upload's hour,
a publish meanwhile, saving the columns), §5.6 (announced), §7 (one check at a time); the CsvStates and MoreStates
boards.

**Files:**
- Modify: `frontend/src/routes/runs/useCsvFile.ts`, `frontend/src/routes/runs/CsvFile.tsx`,
  `frontend/src/routes/runs/RunForm.tsx`, `frontend/src/routes/runs/RunForm.csv.test.tsx`
- Modify: `frontend/src/lib/runForm.ts`, `frontend/src/lib/runForm.test.ts`

**Interfaces:**
- Consumes: Task 5's hook and part; Task 2's `previewCsv`, `saveColumns`, `canSaveColumns`, `cellWords`.
- Produces:
  - `lib/runForm.ts`: `changedWords(n)` (`refusalOf` uses it), `checkedWords(shown, rows)`, `groupRows(group)`;
  - `useCsvFile.ts`: the `staged` file's `checking` and `failed`; `recheck(form)`, `drop(problem)`; `ENDED`, the codes
    that end an upload;
  - `CsvPart` gains `saveable`, `save`, `onSave`.

A changed column checks every row again (ruling 17), said and announced (ruling 22). The errors show at a glance, then
row by row (ruling 18); every row passing shows the first rows and folds the columns, and Start counts the rows (ruling
19). The columns are saved before the start when asked (ruling 20). An upload a start used, or past its hour, is chosen
again; a version published since is read, and the file checked again under it (ruling 23).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.test.ts b/frontend/src/lib/runForm.test.ts
index 111a1ab9..39e49996 100644
--- a/frontend/src/lib/runForm.test.ts
+++ b/frontend/src/lib/runForm.test.ts
@@ -3,7 +3,7 @@ import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import { ApiError } from "./client";
 import {
   canSaveColumns, canStart, cellWords, fileWords, holds, keptValues, keyFor, mappingWords, previewCsv, refusalOf, rerunRun,
-  saveColumns, staleWords, startRun, startable, uploadCsv, uploadProblem, type StartForm,
+  changedWords, checkedWords, groupRows, saveColumns, staleWords, startRun, startable, uploadCsv, uploadProblem, type StartForm,
 } from "./runForm";  // prettier-ignore
 
 let sent: Request[];
@@ -168,3 +168,21 @@ describe("a CSV file's columns and problems, in words (§5.3; the CsvStates and
     );
   });
 });
+
+describe("a checked file, in words (§5.3; the CsvStates board)", () => {
+  it("counts the errors and the rows they're in, or says every row passes", () => {
+    expect(checkedWords({ error_count: 37, rows_with_errors: 29 }, 2431)).toBe("37 errors in 29 of 2,431 rows");
+    expect(checkedWords({ error_count: 1, rows_with_errors: 1 }, 1)).toBe("1 error in 1 of 1 row");
+    expect(checkedWords({ error_count: 0, rows_with_errors: 0 }, 2431)).toBe("All 2,431 rows pass.");
+  });
+
+  it("gives a problem's count and its first rows, and how many more", () => {
+    expect(groupRows({ count: 21, rows: [7, 19, 33, 48, 52] })).toBe("21 · 7, 19, 33, 48, 52 and 16 more");
+    expect(groupRows({ count: 3, rows: [7, 19, 33] })).toBe("3 · 7, 19 and 33");
+    expect(groupRows({ count: 1, rows: [1204] })).toBe("1 · 1,204");
+  });
+
+  it("says a version was published meanwhile as a refused start does", () => {
+    expect(changedWords(8)).toBe(refusalOf(refused(409, { error: "version_changed", active_version_id: "v8", active_version_number: 8 })).words);
+  });
+});
diff --git a/frontend/src/routes/runs/RunForm.csv.test.tsx b/frontend/src/routes/runs/RunForm.csv.test.tsx
index 7a43885b..bbd5b64d 100644
--- a/frontend/src/routes/runs/RunForm.csv.test.tsx
+++ b/frontend/src/routes/runs/RunForm.csv.test.tsx
@@ -4,7 +4,7 @@ import { render, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import { onAnnounce } from "../../lib/announce";
-import type { CsvUpload, StartForm } from "../../lib/runForm";
+import type { CsvPreview, CsvUpload, StartForm } from "../../lib/runForm";
 import { local } from "../../test/runs";
 import { RunForm } from "./RunForm";
 
@@ -22,15 +22,36 @@ const FORM: StartForm = {
 };  // prettier-ignore
 const HEADERS = ["Site name", "Country", "address", "Gateway", "Notes", "Region"];
 const SAVED = { name: "Site name", country_code: "Country", address: "address", gateway_ip: "Gateway" };
-/** An upload's answer: every row passes unless `over` says otherwise. */
+/** A file checked under its columns: every row passes unless `over` says otherwise. */
+const described = (over: Partial<CsvPreview> = {}): CsvPreview => ({
+  version_id: "v7", mapping: SAVED, problems: [], masked_columns: [], preview: [], errors: [], error_count: 0, error_groups: [],
+  rows_with_errors: 0, ...over,
+});  // prettier-ignore
+/** An upload's answer. */
 const upload = (over: Partial<CsvUpload> = {}): CsvUpload => ({
-  version_id: "v7", upload_id: "u1", expires_at: local(11, 0, 0), headers: HEADERS, row_count: 2431, mapping: SAVED,
-  default_mapping: { status: "applied" }, problems: [], masked_columns: [], preview: [], errors: [], error_count: 0,
-  error_groups: [], rows_with_errors: 0, ...over,
+  ...described(), upload_id: "u1", expires_at: local(11, 0, 0), headers: HEADERS, row_count: 2431, default_mapping: { status: "applied" }, ...over,
 });  // prettier-ignore
+// The Errors board's file: 37 errors in 29 rows.
+const ERRORS: Partial<CsvPreview> = {
+  error_count: 37, rows_with_errors: 29,
+  error_groups: [
+    { column: "country_code", code: "not_in_enum", count: 21, rows: [7, 19, 33, 48, 52] },
+    { column: "gateway_ip", code: "not_ip", count: 10, rows: [12, 13, 14, 15, 16] },
+    { column: null, code: "cell_count", count: 6, rows: [102, 140, 141, 150, 151] },
+  ],
+  errors: [{ row: 7, column: "country_code", code: "not_in_enum" }, { row: 102, column: null, code: "cell_count" }],
+};  // prettier-ignore
 
 let uploads: { type: string | null; body: string }[];
 let starts: unknown[];
+let writes: string[]; // "METHOD path" of each write, in order
+let previews: { mapping: unknown; answer: (r: Response) => void }[]; // each check asked, in order
+let held: boolean; // previews wait for the test to answer them
+let previewAnswer: (mapping: Record<string, string>) => Response;
+let startAnswers: (() => Response)[];
+let saveAnswer: () => Response;
+let forms: StartForm[];
+let role: string;
 let uploadAnswer: () => Promise<Response>;
 let said: string[];
 let stop: () => void;
@@ -38,6 +59,14 @@ const json = (body: unknown, status = 200) => new Response(JSON.stringify(body),
 beforeEach(() => {
   uploads = [];
   starts = [];
+  writes = [];
+  previews = [];
+  held = false;
+  previewAnswer = (mapping) => json(described({ mapping }));
+  startAnswers = [];
+  saveAnswer = () => json({ version_id: "v7", mapping: SAVED });
+  forms = [FORM];
+  role = "operator";
   said = [];
   uploadAnswer = () => Promise.resolve(json(upload(), 201));
   vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
@@ -45,14 +74,25 @@ beforeEach(() => {
   vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
     const request = input as Request;
     const path = new URL(request.url).pathname;
-    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(FORM);
+    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(forms.length > 1 ? forms.shift() : forms[0]);
+    if (path === "/api/v1/t/t1") return json({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role });
+    if (request.method !== "GET") writes.push(`${request.method} ${path}`);
+    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads/u1/preview") {
+      const { mapping } = JSON.parse(await request.text()) as { mapping: Record<string, string> };
+      if (!held) {
+        previews.push({ mapping, answer: () => undefined });
+        return previewAnswer(mapping);
+      }
+      return new Promise<Response>((answer) => previews.push({ mapping, answer }));
+    }
+    if (request.method === "PUT" && path === "/api/v1/t/t1/workflows/w1/csv-mapping") return saveAnswer();
     if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads") {
       uploads.push({ type: request.headers.get("Content-Type"), body: await request.text() });
       return uploadAnswer();
     }
     if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/runs") {
       starts.push(JSON.parse(await request.text()));
-      return json({ id: "r1" }, 202);
+      return (startAnswers.shift() ?? (() => json({ id: "r1" }, 202)))();
     }
     return json({ error: "not_found" }, 404);
   });
@@ -109,7 +149,7 @@ describe("a CSV workflow's file (the run form design §5.3; the CsvStates board)
     expect(uploads).toEqual([{ type: "text/csv", body: "Site name,Country\nLyon,FR\n" }]);
     expect(screen.getByText("sites-q4.csv · 1 KB")).toBeTruthy();
     expect(said).toContain("Reading the file…");
-    answer(json(upload(), 201));
+    answer(json(upload(ERRORS), 201)); // rows to fix: the columns stay open
     expect(await screen.findByText("sites-q4.csv · 2,431 rows · 6 columns")).toBeTruthy();
     expect(columnRows()).toEqual([
       ["Site name requiredname", "Site name", "saved"],
@@ -124,7 +164,7 @@ describe("a CSV workflow's file (the run form design §5.3; the CsvStates board)
   it("starts with the staged file and its columns, never skipping a row", async () => {
     show();
     const user = await choose();
-    await screen.findByRole("region", { name: "Columns" });
+    await screen.findByText("sites-q4.csv · 2,431 rows · 6 columns");
     await user.click(screen.getByRole("button", { name: /^Start the live run/ }));
     expect(starts).toEqual([{ input: {}, mode: "live", expected_version_id: "v7", csv: { upload_id: "u1", mapping: SAVED } }]);
   });
@@ -185,3 +225,172 @@ describe("a CSV workflow's file (the run form design §5.3; the CsvStates board)
     expect(document.getElementById(select.getAttribute("aria-describedby")!)?.textContent).toBe("The file has no such column.");
   });
 });
+
+describe("a CSV file checked (the run form design §5.3; the CsvStates and MoreStates boards)", () => {
+  const pick = async (user: ReturnType<typeof userEvent.setup>, column: string, header: string) =>
+    user.selectOptions(await screen.findByRole("combobox", { name: `${column}, from the file's column` }), header); // once the upload's answer is drawn
+
+  it("checks every row again when a column changes, one check at a time, the last change's", async () => {
+    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
+    held = true;
+    show();
+    const user = await choose();
+    await pick(user, "Gateway", "Notes");
+    expect(previews.map((p) => p.mapping)).toEqual([{ ...SAVED, gateway_ip: "Notes" }]);
+    expect(screen.getByText("Checking every row again with these columns…")).toBeTruthy();
+    expect(said).toContain("Checking every row again with these columns…");
+    const start = screen.getByRole("button", { name: "Start the live run" });
+    expect(document.getElementById(start.getAttribute("aria-describedby")!)?.textContent).toBe("The rows are being checked.");
+    await pick(user, "VLAN", "Region");
+    await pick(user, "address", "Not used");
+    expect(previews).toHaveLength(1); // one at a time
+    previews[0]!.answer(json(described({ mapping: { ...SAVED, gateway_ip: "Notes" }, ...ERRORS })));
+    await vi.waitFor(() => expect(previews).toHaveLength(2));
+    const last = { name: "Site name", country_code: "Country", gateway_ip: "Notes", vlan_id: "Region" }; // address: Not used
+    expect(previews[1]!.mapping).toEqual(last); // the last change's only, never the one between
+    expect(screen.queryByText(/errors in/)).toBeNull(); // the first answer is already old
+    previews[1]!.answer(json(described({ mapping: last })));
+    expect(await screen.findByText("All 2,431 rows pass.")).toBeTruthy();
+    expect(said).toContain("All 2,431 rows pass.");
+  });
+
+  it("gives the errors at a glance: the counts, each column's problem with its first rows, and every error row by row", async () => {
+    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
+    show();
+    await choose();
+    expect(await screen.findByText("37 errors in 29 of 2,431 rows")).toBeTruthy();
+    expect(said).toContain("37 errors in 29 of 2,431 rows");
+    expect(screen.getByText("The run can't start until every row passes. Fix the file, then choose it again.")).toBeTruthy();
+    const groups = within(screen.getByRole("region", { name: "Errors by column" })).getAllByRole("row").slice(1);
+    expect(groups.map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent))).toEqual([
+      ["Country", "Not one of the allowed values", "21 · 7, 19, 33, 48, 52 and 16 more"],
+      ["Gateway", "Not an IP address", "10 · 12, 13, 14, 15, 16 and 5 more"],
+      ["The whole row", "Has more or fewer cells than the header", "6 · 102, 140, 141, 150, 151 and 1 more"],
+    ]);
+    await userEvent.click(screen.getByText("Every error, row by row (37)"));
+    const listed = within(screen.getByRole("region", { name: "Every error, row by row" })).getAllByRole("row").slice(1);
+    expect(listed.map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent))).toEqual([
+      ["7", "Country", "Not one of the allowed values"],
+      ["102", "The whole row", "Has more or fewer cells than the header"],
+    ]);
+    const start = screen.getByRole("button", { name: "Start the live run" });
+    expect(start).toHaveProperty("disabled", true);
+    expect(document.getElementById(start.getAttribute("aria-describedby")!)?.textContent).toBe("Every row must pass first.");
+    expect(screen.queryByText(/^Above 100 errors/)).toBeNull();
+  });
+
+  it("says when only the first 100 errors are listed", async () => {
+    const errors = Array.from({ length: 100 }, (_, i) => ({ row: i + 1, column: "gateway_ip", code: "not_ip" }));
+    uploadAnswer = () => Promise.resolve(json(upload({ ...ERRORS, error_count: 150, errors }), 201));
+    show();
+    await choose();
+    expect(await screen.findByText("Above 100 errors, the first 100 are listed row by row; the counts above are of every error.")).toBeTruthy();
+  });
+
+  it("previews the first rows as written once every row passes, folds the columns, and Start says how many rows", async () => {
+    const preview = [{ row: 1, cells: { name: "Lyon Part-Dieu", country_code: "FR", address: "17 Rue du Docteur Bouchut", gateway_ip: "10.40.1.1" } }];
+    uploadAnswer = () => Promise.resolve(json(upload({ preview, masked_columns: ["psk"] }), 201));
+    show();
+    const user = await choose();
+    expect(await screen.findByText("All 2,431 rows pass.")).toBeTruthy();
+    const rows = within(screen.getByRole("region", { name: "The file's first 5 rows, under these columns" })).getAllByRole("row");
+    expect(rows.map((r) => [...r.querySelectorAll("th, td")].map((c) => c.textContent))).toEqual([
+      ["#", "Site name", "Country", "address", "Gateway"],
+      ["1", "Lyon Part-Dieu", "FR", "17 Rue du Docteur Bouchut", "10.40.1.1"],
+    ]);
+    expect(screen.getByText("A column marked sensitive is never shown here.")).toBeTruthy();
+    expect(screen.getByText("Columns: 4 of 5 mapped, as saved · VLAN not used")).toBeTruthy();
+    expect(screen.queryByRole("region", { name: "Columns" })).toBeNull();
+    await user.click(screen.getByRole("button", { name: "Change" }));
+    expect(screen.getByRole("region", { name: "Columns" })).toBeTruthy();
+    expect(screen.getByRole("button", { name: "Start the live run · 2,431 rows" })).toHaveProperty("disabled", false);
+    await user.click(screen.getByRole("radio", { name: "Simulated" }));
+    expect(screen.getByRole("button", { name: "◌ Start the simulation · 2,431 rows" })).toBeTruthy();
+  });
+
+  it("saves the columns for the workflow's next CSV before the start, when asked, for the roles that manage triggers", async () => {
+    role = "editor";
+    show();
+    const user = await choose();
+    await user.click(await screen.findByRole("checkbox", { name: "Save these columns for this workflow's next CSV" }));
+    await user.click(screen.getByRole("button", { name: "Start the live run · 2,431 rows" }));
+    await vi.waitFor(() => expect(writes).toEqual(["POST /api/v1/t/t1/workflows/w1/csv-uploads", "PUT /api/v1/t/t1/workflows/w1/csv-mapping", "POST /api/v1/t/t1/workflows/w1/runs"]));
+  });
+
+  it("starts nothing when the columns couldn't be saved", async () => {
+    role = "editor";
+    saveAnswer = () => json({ error: "internal_error" }, 500);
+    show();
+    const user = await choose();
+    await user.click(await screen.findByRole("checkbox", { name: "Save these columns for this workflow's next CSV" }));
+    await user.click(screen.getByRole("button", { name: "Start the live run · 2,431 rows" }));
+    expect((await screen.findByRole("alert")).textContent).toBe("The columns couldn't be saved, so nothing started. Start again, or leave them unsaved.");
+    expect(starts).toEqual([]);
+  });
+
+  it("offers an operator no saving of the columns", async () => {
+    show();
+    await choose();
+    await screen.findByText("All 2,431 rows pass.");
+    expect(screen.queryByRole("checkbox", { name: /Save these columns/ })).toBeNull();
+  });
+
+  it("asks for the file again when its hour has passed, or a start already used it", async () => {
+    startAnswers = [() => json({ error: "upload_expired", messages: ["…"] }, 410)];
+    show();
+    const user = await choose();
+    await user.click(await screen.findByRole("button", { name: "Start the live run · 2,431 rows" }));
+    expect((await screen.findByRole("alert")).textContent).toBe("The file was kept for an hour, and that hour has passed: choose it again. upload_expired");
+    expect(screen.getByLabelText("Choose a file")).toBeTruthy();
+  });
+
+  it("says when the rows couldn't be checked again, and Start waits for a check", async () => {
+    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
+    previewAnswer = () => json({ error: "internal_error", messages: ["…"] }, 500);
+    show();
+    const user = await choose();
+    await pick(user, "Gateway", "Notes");
+    expect(await screen.findByText("The rows couldn't be checked again with these columns. Change a column to check them again.")).toBeTruthy();
+    const start = screen.getByRole("button", { name: "Start the live run" });
+    expect(document.getElementById(start.getAttribute("aria-describedby")!)?.textContent).toBe("The rows must be checked first.");
+  });
+
+  it("asks for the file again when a check finds it already used", async () => {
+    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
+    previewAnswer = () => json({ error: "upload_consumed", messages: ["…"] }, 409);
+    show();
+    const user = await choose();
+    await pick(user, "Gateway", "Notes");
+    expect((await screen.findByRole("alert")).textContent).toBe("This file already started a run: choose it again to start another. upload_consumed");
+  });
+
+  it("shows a version published since the form opened, keeping the file and the columns it still reads, and checks again", async () => {
+    const NEWER: StartForm = { ...FORM, version_id: "v8", version_number: 8, csv: { ...FORM.csv!, columns: COLUMNS.filter((c) => c.name !== "gateway_ip") } };
+    forms = [FORM, NEWER];
+    uploadAnswer = () => Promise.resolve(json(upload({ version_id: "v8" }), 201));
+    previewAnswer = (mapping) => json(described({ version_id: "v8", mapping }));
+    show();
+    await choose();
+    expect((await screen.findByRole("alert")).textContent).toMatch(/^Version 8 was published while this was open\./);
+    await vi.waitFor(() => expect(previews.map((c) => c.mapping)).toEqual([{ name: "Site name", country_code: "Country", address: "address" }]));
+    expect(await screen.findByText((_, el) => el?.tagName === "P" && el.textContent === "Version 8 · published today 09:12:00 by nadia@corp.test")).toBeTruthy();
+    expect(await screen.findByText("All 2,431 rows pass.")).toBeTruthy();
+    expect(screen.getByText("Columns: 3 of 4 mapped, as saved · VLAN not used")).toBeTruthy();
+  });
+
+  it("checks the file again under the version a refused start names, its upload unused", async () => {
+    const NEWER: StartForm = { ...FORM, version_id: "v8", version_number: 8 };
+    forms = [FORM, NEWER];
+    startAnswers = [() => json({ error: "version_changed", messages: ["…"], active_version_id: "v8", active_version_number: 8 }, 409)];
+    previewAnswer = (mapping) => json(described({ version_id: "v8", mapping }));
+    show();
+    const user = await choose();
+    await user.click(await screen.findByRole("button", { name: "Start the live run · 2,431 rows" }));
+    await vi.waitFor(() => expect(previews.map((c) => c.mapping)).toEqual([SAVED]));
+    await user.click(await screen.findByRole("button", { name: "Start the live run · 2,431 rows" }));
+    expect(starts).toEqual([
+      { input: {}, mode: "live", expected_version_id: "v7", csv: { upload_id: "u1", mapping: SAVED } },
+      { input: {}, mode: "live", expected_version_id: "v8", csv: { upload_id: "u1", mapping: SAVED } },
+    ]);
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunForm.csv.test.tsx src/routes/runs/RunForm.test.tsx
src/lib/runForm.test.ts`

Expected: FAIL, 15 failed and 39 passed: `checkedWords`, `groupRows` and `changedWords` don't exist; a changed column
checks nothing (`expected [] to deeply equal [ { name: 'Site name', …(3) } ]`); no errors, preview, count on Start or
saving (`Unable to find an element with the text: 37 errors in 29 of 2,431 rows`, `… All 2,431 rows pass.`, `Unable to
find role="checkbox" and name "Save these columns for this workflow's next CSV"`); an upload's end and a newer version
say nothing (`Unable to find role="alert"`). Task 5's tests pass, two of them now on a file with errors (its columns
stay open).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.ts b/frontend/src/lib/runForm.ts
index 344eb99e..04575498 100644
--- a/frontend/src/lib/runForm.ts
+++ b/frontend/src/lib/runForm.ts
@@ -100,6 +100,10 @@ export interface Refusal {
   active?: { id: string; number: number };
 }
 
+/** A version published while the form was open (§5.2, §5.3): what the form says, refused or not. */
+export const changedWords = (n: number) =>
+  `Version ${n} was published while this was open. ${NOTHING} The form now shows version ${n}'s input, with your values kept where they still fit: check them and start again.`;
+
 const AT = /^The run's input doesn't match the workflow's input schema at (.+): it breaks `(.+)`\.$/;
 const NOTHING = "Nothing started.";
 const FORM_WORDS: Record<string, string> = {
@@ -119,11 +123,7 @@ export function refusalOf(e: unknown, shown: ReadonlySet<string> = new Set()): R
   const body = (e.body ?? {}) as { messages?: unknown; active_version_id?: unknown; active_version_number?: unknown };
   const messages = Array.isArray(body.messages) ? body.messages.filter((m): m is string => typeof m === "string") : [];
   if (e.code === "version_changed" && typeof body.active_version_id === "string" && typeof body.active_version_number === "number") {
-    const n = body.active_version_number;
-    return {
-      code: e.code, fields: {}, active: { id: body.active_version_id, number: n },
-      words: `Version ${n} was published while this was open. ${NOTHING} The form now shows version ${n}'s input, with your values kept where they still fit: check them and start again.`,
-    };  // prettier-ignore
+    return { code: e.code, fields: {}, active: { id: body.active_version_id, number: body.active_version_number }, words: changedWords(body.active_version_number) };
   }
   if (e.code === "input_invalid") {
     const fields: Record<string, string> = {};
@@ -233,3 +233,20 @@ const MAPPING_WORDS: Record<string, string> = {
 };
 /** What keeps a column's choice from building rows, in words. */
 export const mappingWords = (code: string) => (Object.hasOwn(MAPPING_WORDS, code) ? MAPPING_WORDS[code]! : `Can't be used (${code})`);
+
+const count = (n: number) => n.toLocaleString("en-US");
+const plural = (n: number, one: string) => `${count(n)} ${one}${n === 1 ? "" : "s"}`;
+
+/** A checked file's errors and the rows they're in, or that every row passes (§5.3): said, and announced. */
+export const checkedWords = (shown: Pick<CsvPreview, "error_count" | "rows_with_errors">, rows: number) =>
+  shown.error_count === 0
+    ? `All ${count(rows)} rows pass.`
+    : `${plural(shown.error_count, "error")} in ${count(shown.rows_with_errors)} of ${plural(rows, "row")}`;
+
+/** A column's problem: how many rows, the first ones, and how many more (§4.4: its first five). */
+export function groupRows(g: { count: number; rows: number[] }): string {
+  const rows = g.rows.map(count);
+  const more = g.count - rows.length;
+  const said = more > 0 ? `${rows.join(", ")} and ${more} more` : rows.length < 2 ? (rows[0] ?? "") : `${rows.slice(0, -1).join(", ")} and ${rows.at(-1)!}`;
+  return `${count(g.count)} · ${said}`;
+}
diff --git a/frontend/src/routes/runs/CsvFile.tsx b/frontend/src/routes/runs/CsvFile.tsx
index b31f6e58..321f94ef 100644
--- a/frontend/src/routes/runs/CsvFile.tsx
+++ b/frontend/src/routes/runs/CsvFile.tsx
@@ -1,14 +1,16 @@
 // SPDX-License-Identifier: Apache-2.0
 // A CSV run's file in the run form (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): what
 // the workflow reads before a file, the file being read, why one can't be, and the file's column chosen for each of the
-// workflow's, with how it was proposed.
-import { useId, type ChangeEvent, type DragEvent } from "react";
-import { LINK_BUTTON } from "../../components/Button";
+// workflow's, with how it was proposed. Once checked: its errors at a glance (counted by column and problem on the
+// server, every error), or, every row passing, its first rows as written, the columns folded to a line.
+import { useId, useState, type ChangeEvent, type DragEvent } from "react";
+import { Button, LINK_BUTTON } from "../../components/Button";
 import { controlClass } from "../../components/Field";
 import { Table, Th } from "../../components/Table";
 import { Tag } from "../../components/Tag";
 import { mbOf } from "../../lib/csv";
-import { holds, mappingWords, staleWords, type CsvColumnForm, type StartForm } from "../../lib/runForm";
+import { cellWords, checkedWords, groupRows, holds, mappingWords, staleWords, type CsvColumnForm, type CsvPreview, type StartForm } from "../../lib/runForm";
+import { listed } from "../editor/startInput";
 import { unmapped, type CsvFile } from "./useCsvFile";
 
 type Csv = NonNullable<StartForm["csv"]>;
@@ -17,6 +19,7 @@ const count = (x: number) => x.toLocaleString("en-US");
 const sizeOf = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);
 const ROW_HEAD = "border-t border-line px-3 py-2.5 text-left align-top font-normal";
 const CELL = "border-t border-line px-3 py-2.5 align-top";
+const LISTED = 100; // the errors an answer lists row by row (the run form design §4.4); every one is counted
 
 /** A declared column: its header, what it is, and its name when the header isn't it. */
 function ColumnName({ c }: { c: CsvColumnForm }) {
@@ -110,9 +113,82 @@ function Columns({ csv, file, onMap }: { csv: Csv; file: Extract<CsvFile, { phas
   );
 }
 
-export function CsvPart({ form, csv, file, onChoose, onMap }: {
-  form: StartForm; csv: Csv; file: CsvFile; onChoose: (f: File) => void; onMap: (column: string, header: string) => void;
+/** A column's header, or the whole row's for a problem of no column (`cell_count`). */
+const headerOf = (csv: Csv, name: string | null) => (name === null ? "The whole row" : (csv.columns.find((c) => c.name === name)?.header ?? name));
+
+function Errors({ csv, shown, rows }: { csv: Csv; shown: CsvPreview; rows: number }) {
+  return (
+    <div className="flex flex-col gap-2">
+      <p className="text-small font-semibold text-danger">{checkedWords(shown, rows)}</p>
+      <p className="text-small">The run can&apos;t start until every row passes. Fix the file, then choose it again.</p>
+      <Table label="Errors by column">
+        <thead>
+          <tr><Th>Column</Th><Th>Problem</Th><Th>Rows</Th></tr>
+        </thead>
+        <tbody>
+          {shown.error_groups.map((g) => (
+            <tr key={`${g.column ?? ""}:${g.code}`}>
+              <td className={`${CELL} text-small`}>{headerOf(csv, g.column)}</td>
+              <td className={`${CELL} text-small`}>{cellWords(g.code)}</td>
+              <td className={`${CELL} font-mono text-small`}>{groupRows(g)}</td>
+            </tr>
+          ))}
+        </tbody>
+      </Table>
+      <details className="text-small">
+        <summary className="min-h-6 cursor-pointer">{`Every error, row by row (${count(shown.error_count)})`}</summary>
+        <Table label="Every error, row by row" className="mt-2">
+          <thead>
+            <tr><Th>Row</Th><Th>Column</Th><Th>Problem</Th></tr>
+          </thead>
+          <tbody>
+            {shown.errors.map((e, i) => (
+              <tr key={i}>
+                <td className={`${CELL} font-mono`}>{count(e.row)}</td>
+                <td className={CELL}>{headerOf(csv, e.column)}</td>
+                <td className={CELL}>{cellWords(e.code)}</td>
+              </tr>
+            ))}
+          </tbody>
+        </Table>
+      </details>
+      {shown.error_count > LISTED && (
+        <p className="text-small text-muted">Above 100 errors, the first 100 are listed row by row; the counts above are of every error.</p>
+      )}
+    </div>
+  );
+}
+
+/** The file's first rows as written, under the columns chosen (§5.3): a sensitive column is never in them. */
+function Preview({ csv, shown, rows }: { csv: Csv; shown: CsvPreview; rows: number }) {
+  const names = csv.columns.filter((c) => shown.preview.some((r) => c.name in r.cells));
+  return (
+    <div className="flex flex-col gap-2">
+      <p className="text-small font-semibold text-ok">{checkedWords(shown, rows)}</p>
+      <h3 className="text-small font-semibold">The file&apos;s first 5 rows, under these columns</h3>
+      <Table label="The file's first 5 rows, under these columns">
+        <thead>
+          <tr><Th>#</Th>{names.map((c) => <Th key={c.name}>{c.header}</Th>)}</tr>
+        </thead>
+        <tbody>
+          {shown.preview.map((r) => (
+            <tr key={r.row}>
+              <td className={`${CELL} font-mono text-small`}>{r.row}</td>
+              {names.map((c) => <td key={c.name} className={`${CELL} text-small`}>{r.cells[c.name] ?? ""}</td>)}
+            </tr>
+          ))}
+        </tbody>
+      </Table>
+      {shown.masked_columns.length > 0 && <p className="text-small text-muted">A column marked sensitive is never shown here.</p>}
+    </div>
+  );  // prettier-ignore
+}
+
+export function CsvPart({ form, csv, file, saveable, save, onChoose, onMap, onSave }: {
+  form: StartForm; csv: Csv; file: CsvFile; saveable: boolean; save: boolean;
+  onChoose: (f: File) => void; onMap: (column: string, header: string) => void; onSave: (save: boolean) => void;
 }) {  // prettier-ignore
+  const [unfolded, setUnfolded] = useState(false);
   const drop = (e: DragEvent) => {
     e.preventDefault();
     const f = e.dataTransfer.files[0];
@@ -128,14 +204,36 @@ export function CsvPart({ form, csv, file, onChoose, onMap }: {
   }
   if (file.phase === "staged") {
     const stale = file.upload.default_mapping.status === "stale";
+    const rows = file.upload.row_count;
+    const settled = !file.checking && !file.failed && unmapped(csv.columns, file.mapping).length === 0 && file.shown.problems.length === 0;
+    const passes = settled && file.shown.error_count === 0;
+    const mapped = csv.columns.filter((c) => file.mapping[c.name]);
+    const unused = csv.columns.filter((c) => !file.mapping[c.name]).map((c) => c.header);
+    const asSaved = mapped.length > 0 && mapped.every((c) => file.how[c.name] === "saved");
     return (
       <div className="flex flex-col gap-3">
         <div className="flex flex-wrap items-center justify-between gap-2">
-          <p className="text-small font-medium">{`${file.name} · ${count(file.upload.row_count)} rows · ${file.upload.headers.length} columns`}</p>
+          <p className="text-small font-medium">{`${file.name} · ${count(rows)} rows · ${file.upload.headers.length} columns`}</p>
           <Choose label="Choose another file" onChoose={onChoose} />
         </div>
         {stale && <p className="text-small">{staleWords(form.version_number, file.upload.default_mapping.problems ?? [])}</p>}
-        <Columns csv={csv} file={file} onMap={onMap} />
+        {passes && !unfolded ? (
+          <p className="flex flex-wrap items-center gap-2 text-small">
+            {`Columns: ${mapped.length} of ${csv.columns.length} mapped${asSaved ? ", as saved" : ""}${unused.length > 0 ? ` · ${listed(unused)} not used` : ""}`}
+            <Button size="sm" onClick={() => setUnfolded(true)}>Change</Button>
+          </p>
+        ) : (
+          <Columns csv={csv} file={file} onMap={onMap} />
+        )}
+        {saveable && (
+          <label className="flex min-h-6 items-center gap-2 text-small">
+            <input type="checkbox" checked={save} onChange={(e) => onSave(e.target.checked)} className="size-[16px] accent-accent" />
+            Save these columns for this workflow&apos;s next CSV
+          </label>
+        )}
+        {file.checking && <p className="text-small text-muted">Checking every row again with these columns…</p>}
+        {file.failed && <p className="text-small text-danger">The rows couldn&apos;t be checked again with these columns. Change a column to check them again.</p>}
+        {settled && (passes ? <Preview csv={csv} shown={file.shown} rows={rows} /> : file.shown.error_count > 0 && <Errors csv={csv} shown={file.shown} rows={rows} />)}
       </div>
     );
   }
diff --git a/frontend/src/routes/runs/RunForm.tsx b/frontend/src/routes/runs/RunForm.tsx
index cc0cbf2f..90b1becb 100644
--- a/frontend/src/routes/runs/RunForm.tsx
+++ b/frontend/src/routes/runs/RunForm.tsx
@@ -3,23 +3,28 @@
 // form, live or simulated, in the Simulate dialog's look. The version it shows is the one it starts: the start goes
 // with that version's id (B14), and a version published meanwhile is read and shown, the values that still fit kept.
 // Each submitted form goes under one key, sent again under it only when the same form is (an answer lost on the way).
-// A workflow that declares a CSV starts only with its file (§5.3, CsvPart), any other fields beside it.
+// A workflow that declares a CSV starts only with its file (§5.3, CsvPart), any other fields beside it, once every row
+// passes; the columns are saved first when asked, and a failed save starts nothing. A file checked against a version
+// published since the form was read has the form read again, as a refused start does.
 import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { useEffect, useId, useRef, useState, type FormEvent } from "react";
 import { Button } from "../../components/Button";
 import { TextArea } from "../../components/Field";
 import { When } from "../../components/When";
-import { keptValues, keyFor, refusalOf, startRun, type Refusal, type Sent, type StartBody, type StartForm } from "../../lib/runForm";
+import {
+  canSaveColumns, changedWords, keptValues, keyFor, refusalOf, saveColumns, startRun, type Refusal, type Sent, type StartBody, type StartForm,
+} from "../../lib/runForm";  // prettier-ignore
 import { startFormQuery } from "../../lib/triggers";
+import { tenantQuery } from "../../lib/workflows";
 import { SimBanner } from "../editor/simulation/SimBanner";
 import { CsvPart } from "./CsvFile";
-import { csvReason, useCsvFile } from "./useCsvFile";
+import { ENDED, csvReason, useCsvFile } from "./useCsvFile";
 import { InputControl, REQUIRED, fieldKey, fromFields, hintOf, labelOf, startValues, wholeOf } from "../editor/startInput";
 
 type Mode = StartBody["mode"];
 
 /** A refusal says its code beside its words (the MoreStates board), but for those the form itself words. */
-const CODED = (code: string) => !["version_changed", "network"].includes(code);
+const CODED = (code: string) => !["version_changed", "network", "columns_unsaved"].includes(code);
 
 function ModeChoice({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
   const id = useId();
@@ -79,6 +84,37 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
   const shownJson = jsonText ?? "";
   const csv = useCsvFile(tenantId, workflow.id);
   const reason = form?.csv ? csvReason(csv.file, form.csv.columns) : null;
+  const rows = form?.csv && csv.file.phase === "staged" && reason === null ? csv.file.upload.row_count : null;
+  const tenant = useQuery(tenantQuery(tenantId));
+  const saveable = canSaveColumns(tenant.data?.role);
+  const [save, setSave] = useState(false);
+
+  /** The version now published, read again (§5.2, §5.3): its form shown, the values that still fit kept, a staged file
+   * checked again under it; why it couldn't be read, else null. */
+  async function reread(from: StartForm, values: ReadonlyMap<string, string>): Promise<{ fresh: StartForm | null } | { refused: Refusal }> {
+    try {
+      const fresh = await qc.query({ ...startFormQuery(tenantId, workflow.id), staleTime: 0 });
+      if (fresh) {
+        setValues(keptValues(values, from, fresh));
+        setForm(fresh);
+        csv.recheck(fresh);
+      }
+      return { fresh };
+    } catch (e) {
+      return { refused: refusalOf(e) };
+    }
+  }
+
+  // A file checked against a version the form doesn't show (§5.3): one published since the form was read. Read once.
+  const drifted = form && csv.file.phase === "staged" && !csv.file.checking && csv.file.shown.version_id !== form.version_id ? csv.file.shown.version_id : null;
+  const followed = useRef<string | null>(null);
+  useEffect(() => {
+    if (drifted === null || form === null || followed.current === drifted) return;
+    followed.current = drifted;
+    void reread(form, shownValues).then((r) =>
+      setRefusal("refused" in r ? r.refused : r.fresh ? { code: "version_changed", words: changedWords(r.fresh.version_number), fields: {} } : null),
+    );  // prettier-ignore
+  }, [drifted]); // once per version found: the form and values of the draw that found it
 
   // Focus goes to the first field once the form is read (§5.6); before, the dialog holds it.
   const formRead = form !== null;
@@ -117,20 +153,21 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
     setRefusal(null);
     setSending(true);
     try {
+      if (body.csv && save && saveable) {
+        try {
+          await saveColumns(tenantId, workflow.id, body.csv.mapping);
+        } catch {
+          return setRefusal({ code: "columns_unsaved", words: "The columns couldn't be saved, so nothing started. Start again, or leave them unsaved.", fields: {} });
+        }
+      }
       const started = await startRun(tenantId, workflow.id, body, sent.key);
       onStarted(started.id);
     } catch (err) {
       let refused = refusalOf(err, new Set(asJson ? [] : form.fields.map((f) => f.name)));
+      if (ENDED.has(refused.code)) return csv.drop({ words: refused.words, code: refused.code }); // chosen again
       if (refused.code === "version_changed") {
-        try {
-          const fresh = await qc.query({ ...startFormQuery(tenantId, workflow.id), staleTime: 0 });
-          if (fresh) {
-            setValues(keptValues(shownValues, form, fresh));
-            setForm(fresh);
-          }
-        } catch (again) {
-          refused = refusalOf(again);
-        }
+        const r = await reread(form, shownValues);
+        if ("refused" in r) refused = r.refused;
       }
       setRefusal(refused);
       setErrors(refused.fields);
@@ -173,7 +210,10 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
             <ModeChoice mode={mode} onChange={setMode} />
             <div ref={fieldsRef} className="flex flex-col gap-4">
               {form.csv && (
-                <CsvPart form={form} csv={form.csv} file={csv.file} onChoose={(f) => void csv.choose(f, form.csv!)} onMap={csv.map} />
+                <CsvPart
+                  form={form} csv={form.csv} file={csv.file} saveable={saveable} save={save} onSave={setSave}
+                  onChoose={(f) => void csv.choose(f, form.csv!)} onMap={(column, header) => csv.map(column, header, form.csv!)}
+                />
               )}
               {asJson ? (
                 <TextArea
@@ -219,7 +259,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
             type="submit" variant={mode === "live" ? "live-outline" : "simulate"} disabled={form === null || sending || reason !== null}
             aria-describedby={reason ? `${id}-reason` : undefined}
           >
-            {mode === "live" ? "Start the live run" : "◌ Start the simulation"}
+            {`${mode === "live" ? "Start the live run" : "◌ Start the simulation"}${rows === null ? "" : ` · ${rows.toLocaleString("en-US")} row${rows === 1 ? "" : "s"}`}`}
           </Button>
         </div>
       </form>
diff --git a/frontend/src/routes/runs/useCsvFile.ts b/frontend/src/routes/runs/useCsvFile.ts
index bea8e401..6bf5b03a 100644
--- a/frontend/src/routes/runs/useCsvFile.ts
+++ b/frontend/src/routes/runs/useCsvFile.ts
@@ -1,19 +1,30 @@
 // SPDX-License-Identifier: Apache-2.0
 // A CSV run's file (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): chosen, uploaded as it
 // is, read by the server against the version's columns, the file's columns proposed for them (saved, or the same names),
-// and the person's choice of each. The upload's answer says what keeps the file from building rows.
-import { useRef, useState } from "react";
+// and the person's choice of each. A changed choice has every row checked again (B11): one check at a time, and only the
+// last change's (§7), its answer shown only while it's the choice shown. A file a start used, or kept past its hour, is
+// chosen again.
+import { useEffect, useRef, useState } from "react";
 import { announce } from "../../lib/announce";
-import { uploadCsv, uploadProblem, type CsvColumnForm, type CsvPreview, type CsvUpload, type Mapping } from "../../lib/runForm";
+import {
+  checkedWords, previewCsv, refusalOf, uploadCsv, uploadProblem, type CsvColumnForm, type CsvPreview, type CsvUpload, type Mapping,
+  type StartForm,
+} from "../../lib/runForm";  // prettier-ignore
 
 /** How a column's choice was made: proposed from the saved columns, by the same name, or left out; the person's own
  * choice says nothing. */
 export type How = "saved" | "same name" | "left out";
 
+export type Problem = { words: string; code: string | null };
 export type CsvFile =
-  | { phase: "none"; problem: { words: string; code: string | null } | null }
+  | { phase: "none"; problem: Problem | null }
   | { phase: "reading"; name: string; size: number }
-  | { phase: "staged"; name: string; upload: CsvUpload; mapping: Mapping; how: Partial<Record<string, How>>; shown: CsvPreview };
+  | {
+      phase: "staged"; name: string; upload: CsvUpload; mapping: Mapping; how: Partial<Record<string, How>>; shown: CsvPreview;
+      checking: boolean; failed: boolean;
+    };  // prettier-ignore
+
+type Csv = NonNullable<StartForm["csv"]>;
 
 /** The required columns `mapping` gives no file's column: no row is built without them. */
 export const unmapped = (columns: CsvColumnForm[], mapping: Mapping) => columns.filter((c) => c.required && !mapping[c.name]).map((c) => c.name);
@@ -21,41 +32,105 @@ export const unmapped = (columns: CsvColumnForm[], mapping: Mapping) => columns.
 const howOf = (columns: CsvColumnForm[], upload: CsvUpload): Partial<Record<string, How>> =>
   Object.fromEntries(columns.map((c) => [c.name, !upload.mapping[c.name] ? "left out" : upload.default_mapping.status === "applied" ? "saved" : "same name"]));
 
+const same = (a: Mapping, b: Mapping) => JSON.stringify(Object.entries(a).sort()) === JSON.stringify(Object.entries(b).sort());
+
+/** The codes that end an upload: it's chosen again. */
+export const ENDED = new Set(["upload_expired", "upload_consumed", "upload_not_found"]);
+
 export function useCsvFile(tenantId: string, workflowId: string) {
   const [file, setFile] = useState<CsvFile>({ phase: "none", problem: null });
   const chosen = useRef(0); // the files chosen: an answer for one chosen since is dropped
+  const flight = useRef<{ busy: boolean; next: { id: string; mapping: Mapping } | null }>({ busy: false, next: null });
+  // The file as last drawn: what a call made after an await (a newer version read) works from.
+  const latest = useRef(file);
+  useEffect(() => {
+    latest.current = file;
+  }, [file]);
 
-  async function choose(f: File, csv: { columns: CsvColumnForm[]; max_rows: number; max_bytes: number }) {
+  async function choose(f: File, csv: Csv) {
     const n = ++chosen.current;
     setFile({ phase: "reading", name: f.name, size: f.size });
     announce("Reading the file…");
     try {
       const upload = await uploadCsv(tenantId, workflowId, f);
       if (n !== chosen.current) return;
-      setFile({ phase: "staged", name: f.name, upload, mapping: upload.mapping, how: howOf(csv.columns, upload), shown: upload });
+      setFile({ phase: "staged", name: f.name, upload, mapping: upload.mapping, how: howOf(csv.columns, upload), shown: upload, checking: false, failed: false });
+      if (unmapped(csv.columns, upload.mapping).length === 0) announce(checkedWords(upload, upload.row_count));
     } catch (e) {
       if (n === chosen.current) setFile({ phase: "none", problem: uploadProblem(f.name, e, csv) });
     }
   }
 
+  /** Every row checked again under `mapping`: after the one in flight, if any, and only the last asked meanwhile. */
+  async function check(id: string, mapping: Mapping, rows: number) {
+    flight.current.next = { id, mapping };
+    if (flight.current.busy) return;
+    flight.current.busy = true;
+    announce("Checking every row again with these columns…");
+    try {
+      while (flight.current.next) {
+        const ask = flight.current.next;
+        flight.current.next = null;
+        const current = (f: CsvFile): f is Extract<CsvFile, { phase: "staged" }> => f.phase === "staged" && f.upload.upload_id === ask.id && same(f.mapping, ask.mapping);
+        try {
+          const shown = await previewCsv(tenantId, workflowId, ask.id, ask.mapping);
+          if (flight.current.next) continue; // a later choice is checked next: this answer is already old
+          setFile((f) => (current(f) ? { ...f, shown, checking: false, failed: false } : f));
+          announce(checkedWords(shown, rows));
+        } catch (e) {
+          if (flight.current.next) continue;
+          const refused = refusalOf(e);
+          if (ENDED.has(refused.code)) setFile({ phase: "none", problem: { words: refused.words, code: refused.code } });
+          else setFile((f) => (current(f) ? { ...f, checking: false, failed: true } : f));
+        }
+      }
+    } finally {
+      flight.current.busy = false;
+    }
+  }
+
+  /** Each column's choice kept or changed, then every row checked again once each required column has one. */
+  function choices(f: Extract<CsvFile, { phase: "staged" }>, csv: Csv, mapping: Mapping, how: Partial<Record<string, How>>) {
+    const ready = unmapped(csv.columns, mapping).length === 0;
+    const next = { ...f, mapping, how, checking: ready, failed: false };
+    latest.current = next; // a second choice before the next draw starts from this one
+    setFile(next);
+    if (ready) void check(f.upload.upload_id, mapping, f.upload.row_count);
+  }
+
   /** The file's column chosen for `column` ("" for none). */
-  function map(column: string, header: string) {
-    setFile((f) => {
-      if (f.phase !== "staged") return f;
-      const mapping = { ...f.mapping };
-      if (header) mapping[column] = header;
-      else delete mapping[column];
-      return { ...f, mapping, how: { ...f.how, [column]: undefined } };
-    });
+  function map(column: string, header: string, csv: Csv) {
+    const f = latest.current;
+    if (f.phase !== "staged") return;
+    const mapping = { ...f.mapping };
+    if (header) mapping[column] = header;
+    else delete mapping[column];
+    choices(f, csv, mapping, { ...f.how, [column]: undefined });
   }
 
-  return { file, choose, map };
+  /** A newer version's form (§5.3): the staged file kept, each choice whose column it still reads, checked again; a
+   * version that reads no CSV drops the file. */
+  function recheck(form: StartForm) {
+    const f = latest.current;
+    if (f.phase !== "staged") return;
+    if (!form.csv) return setFile({ phase: "none", problem: null });
+    const names = new Set(form.csv.columns.map((c) => c.name));
+    const mapping = Object.fromEntries(Object.entries(f.mapping).filter(([name]) => names.has(name)));
+    choices(f, form.csv, mapping, Object.fromEntries(Object.entries(f.how).filter(([name]) => names.has(name))));
+  }
+
+  /** The upload ended (a start used it, its hour passed): the file is chosen again, `problem` saying why. */
+  const drop = (problem: Problem) => setFile({ phase: "none", problem });
+
+  return { file, choose, map, recheck, drop };
 }
 
 /** Why a CSV start can't go ahead yet, or null (§5.3): said beside Start, which waits. */
 export function csvReason(file: CsvFile, columns: CsvColumnForm[]): string | null {
   if (file.phase !== "staged") return "Choose a file first.";
   if (unmapped(columns, file.mapping).length > 0) return "Choose the file's column for every required column first.";
+  if (file.checking) return "The rows are being checked.";
+  if (file.failed) return "The rows must be checked first.";
   if (file.shown.problems.length > 0) return "Fix the columns marked first.";
   if (file.shown.error_count > 0) return "Every row must pass first.";
   return null;
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 54 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/lib frontend/src/routes
git commit -m "feat(editor): a CSV file checked: its errors at a glance, its first rows, its columns saved (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4e-2b, milestone 2 (<date>)` to the ledger, as for milestone 1, commit it as
`docs(editor-4): 4e-2b milestone 2`, and **pause** for the owner's review.

---

# Milestone 3 — Re-run, and 320 px

### Task 7: Re-run a run, its input kept or changed

**Spec:** §5.1 (Re-run… on a run's page), §5.4 (the version, the mode, typed input kept, changed, `absent`,
`unreadable`, `410 input_not_retained`); the Rerun and MoreStates boards.

**Files:**
- Create: `frontend/src/routes/runs/rerun.ts`, `frontend/src/routes/runs/RunForm.rerun.test.tsx`
- Modify: `frontend/src/routes/runs/RunForm.tsx`
- Modify: `frontend/src/routes/runs/RunPage.tsx`, `frontend/src/routes/runs/RunPage.test.tsx`

**Interfaces:**
- Consumes: Task 2's `rerunRun`, `RerunBody`; `runInputQuery`, `Run` (`lib/runs.ts`); `runId` (`lib/runStatus.ts`);
  `shownOf` (`routes/editor/startInput.tsx`); Task 4's `useLand`.
- Produces:
  - `rerun.ts`: `REDACTED`, `holdsMarker(v)`, `prefill(form, input): { values; kept }`, `versionWords(form, ran,
    short)`, `MARKER_WORDS`, `AGAIN`;
  - `RunForm`'s `rerun?: { run: Run; ranVersion: number | null }`.

A run that ended offers Re-run… (ruling 24). Its form reads the run's input back and the active version's form: the
fields prefilled, a kept value said and never shown (ruling 25). Untouched, it sends no input; changed, the input goes
whole, the kept values entered again, the marker never sent. An input the server no longer keeps starts the fields
empty, saying why (ruling 27).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunForm.rerun.test.tsx b/frontend/src/routes/runs/RunForm.rerun.test.tsx
new file mode 100644
index 00000000..56733877
--- /dev/null
+++ b/frontend/src/routes/runs/RunForm.rerun.test.tsx
@@ -0,0 +1,172 @@
+// SPDX-License-Identifier: Apache-2.0
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render, screen } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import type { StartForm } from "../../lib/runForm";
+import type { Run } from "../../lib/runs";
+import { FAILED_RUN, local } from "../../test/runs";
+import { RunForm } from "./RunForm";
+
+// The Rerun board: version 11's run, re-run on version 12; its token read back redacted.
+const RUN: Run = { ...FAILED_RUN, version_id: "v11" };
+const FORM: StartForm = {
+  workflow_id: "w1", version_id: "v12", version_number: 12, published_at: local(9, 0, 0), published_by: null, csv: null,
+  fields: [
+    { name: "site", title: "Site", type: "string", required: true, sensitive: false },
+    { name: "floor", title: "Floor", type: "integer", required: false, sensitive: false },
+    { name: "token", title: "API token", type: "string", required: true, sensitive: true },
+  ],
+};  // prettier-ignore
+const KEPT = { input: { site: "HQ", floor: 2, token: "[redacted]" }, read_back: "kept", seeds: null };
+
+let input: unknown;
+let reruns: { key: string | null; body: unknown }[];
+let rerunAnswers: (() => Response)[];
+const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
+beforeEach(() => {
+  input = KEPT;
+  reruns = [];
+  rerunAnswers = [];
+  vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
+  vi.spyOn(globalThis, "fetch").mockImplementation(async (req) => {
+    const request = req as Request;
+    const path = new URL(request.url).pathname;
+    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(FORM);
+    if (path === `/api/v1/t/t1/runs/${RUN.id}/input`) return json(input);
+    if (request.method === "POST" && path === `/api/v1/t/t1/runs/${RUN.id}/rerun`) {
+      reruns.push({ key: request.headers.get("Idempotency-Key"), body: JSON.parse(await request.text()) as unknown });
+      return (rerunAnswers.shift() ?? (() => json({ id: "r1" }, 202)))();
+    }
+    return json({ error: "not_found" }, 404);
+  });
+});
+afterEach(() => vi.restoreAllMocks());
+
+function show(run: Run = RUN, ranVersion: number | null = 11) {
+  const onStarted = vi.fn();
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  render(
+    <QueryClientProvider client={qc}>
+      <RunForm tenantId="t1" workflow={{ id: "w1", name: "AP offline triage" }} rerun={{ run, ranVersion }} onStarted={onStarted} onClose={vi.fn()} />
+    </QueryClientProvider>,
+  );
+  return { onStarted };
+}
+const site = () => screen.findByLabelText(/^Site/);
+
+describe("re-running a run (the run form design §5.4; the Rerun board)", () => {
+  it("names the run, and the version it runs beside the one the run ran", async () => {
+    show();
+    expect(await screen.findByRole("dialog", { name: "Re-run 4a2b17e0" })).toBeTruthy();
+    expect(await screen.findByText("It runs version 12, the one published now. Run 4a2b17e0 ran version 11.")).toBeTruthy();
+  });
+
+  it("says when it runs the same version as the run", async () => {
+    show({ ...RUN, version_id: "v12" }, 12);
+    expect(await screen.findByText("It runs version 12, the same version as run 4a2b17e0.")).toBeTruthy();
+  });
+
+  it("preselects the run's mode", async () => {
+    show({ ...RUN, mode: "simulate" });
+    await site();
+    expect(screen.getByRole("radio", { name: "Simulated" })).toHaveProperty("checked", true);
+    expect(screen.getByRole("button", { name: "◌ Re-run as a simulation" })).toBeTruthy();
+  });
+
+  it("prefills the original's input, keeps its protected values, and sends no input untouched: the original goes back whole", async () => {
+    const { onStarted } = show();
+    expect(await site()).toHaveProperty("value", "HQ");
+    expect(screen.getByLabelText(/^Floor/)).toHaveProperty("value", "2");
+    expect(screen.getByText("The original run's input. Change what you need.")).toBeTruthy();
+    expect(screen.getByText("Kept from the original run")).toBeTruthy();
+    expect(screen.queryByLabelText(/^API token/)).toBeNull();
+    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
+    expect(reruns).toEqual([{ key: expect.any(String) as string, body: { mode: "live", expected_version_id: "v12" } }]);
+    expect(onStarted).toHaveBeenCalledWith("r1");
+  });
+
+  it("sends a changed input whole, its protected values entered again, never the marker", async () => {
+    show();
+    const user = userEvent.setup();
+    await user.type(await site(), " north");
+    expect(screen.getByText("Changed from the original run's input.")).toBeTruthy();
+    const token = screen.getByLabelText(/^API token/);
+    expect(token).toHaveProperty("value", "");
+    expect(token).toHaveProperty("type", "password");
+    expect(screen.getByText("Enter it again: a changed input is sent whole, and the original's protected values never reach this form.")).toBeTruthy();
+    await user.click(screen.getByRole("button", { name: "Re-run live" }));
+    expect(screen.getByText("Give a value: the input requires it.")).toBeTruthy();
+    expect(reruns).toEqual([]);
+    await user.type(token, "s3cret");
+    await user.click(screen.getByRole("button", { name: "Re-run live" }));
+    expect(reruns.map((r) => r.body)).toEqual([{ input: { site: "HQ north", floor: 2, token: "s3cret" }, mode: "live", expected_version_id: "v12" }]);
+  });
+
+  it("keeps any value that read back holding the marker, a field not marked sensitive too, and empties it once changed; an undeclared one is never sent", async () => {
+    const meta = { name: "meta", title: "Meta", type: "object", required: false, sensitive: false };
+    const note = { name: "note", title: "Note", type: "string", required: false, sensitive: false };
+    vi.mocked(globalThis.fetch).mockImplementation(async (req) => {
+      const request = req as Request;
+      const path = new URL(request.url).pathname;
+      if (path === "/api/v1/t/t1/workflows/w1/start-form") return json({ ...FORM, fields: [FORM.fields[0], meta, note] });
+      if (path === `/api/v1/t/t1/runs/${RUN.id}/input`) return json({ ...KEPT, input: { site: "HQ", meta: { key: "[redacted]", n: 1 }, note: "[redacted]", extra: "[redacted]" } });
+      if (request.method === "POST") reruns.push({ key: null, body: JSON.parse(await request.text()) as unknown });
+      return json({ id: "r1" }, 202);
+    });
+    show();
+    await site();
+    expect(screen.getAllByText("Kept from the original run")).toHaveLength(2);
+    await userEvent.type(await site(), "!");
+    expect(screen.getByLabelText(/^Meta/)).toHaveProperty("value", "");
+    expect(screen.getByLabelText(/^Note/)).toHaveProperty("value", "");
+    await userEvent.type(screen.getByLabelText(/^Meta/), "{{}");
+    await userEvent.type(screen.getByLabelText(/^Note/), "n");
+    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
+    expect(reruns.map((r) => r.body)).toEqual([{ input: { site: "HQ!", meta: {}, note: "n" }, mode: "live", expected_version_id: "v12" }]);
+  });
+
+  it("refuses the marker typed as JSON", async () => {
+    show();
+    const user = userEvent.setup();
+    await site();
+    await user.click(screen.getByRole("button", { name: "Edit as JSON" }));
+    const text = screen.getByLabelText("The input, as JSON");
+    await user.clear(text);
+    await user.type(text, '{{"site": "HQ", "token": "[[redacted]"}');
+    await user.click(screen.getByRole("button", { name: "Re-run live" }));
+    expect(screen.getByText("It holds [redacted], a protected value the original kept: enter that value again.")).toBeTruthy();
+    expect(reruns).toEqual([]);
+  });
+
+  it("says when the original input isn't kept, and starts from empty fields", async () => {
+    input = { input: null, read_back: "absent", seeds: null };
+    show();
+    expect(await screen.findByText("Run 4a2b17e0's input isn't kept, so it can't be sent again. Fill in the fields to run it again.")).toBeTruthy();
+    expect(await site()).toHaveProperty("value", "");
+    await userEvent.type(await site(), "HQ");
+    await userEvent.type(screen.getByLabelText(/^API token/), "t");
+    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
+    expect(reruns.map((r) => r.body)).toEqual([{ input: { site: "HQ", token: "t" }, mode: "live", expected_version_id: "v12" }]);
+  });
+
+  it("says when the original input can't be read back, and re-runs with new input", async () => {
+    input = { input: null, read_back: "unreadable", seeds: null };
+    show();
+    expect(
+      await screen.findByText(
+        "Run 4a2b17e0's input can't be read back: it doesn't open, or the tenant's key is gone during an erasure. Fill in the fields to run it again.",
+      ),
+    ).toBeTruthy();
+    expect(await site()).toHaveProperty("value", "");
+  });
+
+  it("turns to empty fields when the original input is gone by the time it's sent", async () => {
+    rerunAnswers = [() => json({ error: "input_not_retained", messages: ["…"] }, 410)];
+    show();
+    await site();
+    await userEvent.click(screen.getByRole("button", { name: "Re-run live" }));
+    expect(await screen.findByText("Run 4a2b17e0's input isn't kept, so it can't be sent again. Fill in the fields to run it again.")).toBeTruthy();
+    expect(await site()).toHaveProperty("value", "");
+  });
+});
diff --git a/frontend/src/routes/runs/RunPage.test.tsx b/frontend/src/routes/runs/RunPage.test.tsx
index 01e0e95d..151c332b 100644
--- a/frontend/src/routes/runs/RunPage.test.tsx
+++ b/frontend/src/routes/runs/RunPage.test.tsx
@@ -675,3 +675,40 @@ describe("runs that didn't run, and others (§5.4; the RunOther board)", () => {
     });
   });
 });
+
+describe("Re-run… (the run form design §5.1, §5.4; the EntryPoints board)", () => {
+  const FORM = { workflow_id: "w1", version_id: "v2", version_number: 2, published_at: local(8, 0, 0), published_by: null, csv: null, fields: [] };
+  beforeEach(() => {
+    answers.set("/api/v1/t/t1/workflows/w1/start-form", json(FORM));
+    answers.set(`/api/v1/t/t1/runs/${RUN.id}/input`, json({ input: {}, read_back: "kept", seeds: null }));
+  });
+
+  it("offers Re-run… once the run has ended, to the roles that hold run.start, and opens its form", async () => {
+    answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(RUN));
+    show();
+    await userEvent.click(await screen.findByRole("button", { name: "Re-run…" }));
+    expect(await screen.findByRole("dialog", { name: "Re-run 4a2b17e0" })).toBeTruthy();
+    expect(await screen.findByText("It runs version 2, the same version as run 4a2b17e0.")).toBeTruthy();
+  });
+
+  it("offers none while the run goes (Cancel instead), on a draft simulation, on a sub-run, nor to a viewer", async () => {
+    const cases: [Run, string][] = [
+      [{ ...RUN, status: "running", ended_at: null }, "operator"],
+      [{ ...RUN, draft_snapshot_id: "s1", draft_revision: 4, mode: "simulate" }, "operator"],
+      [{ ...RUN, parent: { run_id: "p1", step_id: null, iteration_key: null }, parent_run_id: "p1" }, "operator"],
+      [RUN, "viewer"],
+    ];
+    for (const [run, as] of cases) {
+      role = as;
+      answers.set(`/api/v1/t/t1/runs/${RUN.id}`, json(run));
+      show();
+      await screen.findByRole("heading", { level: 1, name: "AP offline triage" });
+      await vi.waitFor(() => expect(reads).toContain("/api/v1/t/t1")); // the role read, then drawn
+      await act(() => new Promise((r) => setTimeout(r, 0)));
+      expect(screen.queryByRole("button", { name: "Re-run…" })).toBeNull();
+      if (run.status === "running") expect(screen.getByRole("button", { name: "Cancel the run" })).toBeTruthy();
+      cleanup();
+      reads = [];
+    }
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunForm.rerun.test.tsx src/routes/runs/RunPage.test.tsx`

Expected: FAIL, 11 failed and 39 passed: a run's page offers no Re-run… (`Unable to find role="button" and name
"Re-run…"`); the form takes no `rerun` (`Unable to find role="dialog" and name "Re-run 4a2b17e0"`, nothing prefilled, no
"Kept from the original run", no "Re-run live"). "offers none while the run goes …" passes at once: no run offers it
yet; it pins where it never shows.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunForm.tsx b/frontend/src/routes/runs/RunForm.tsx
index 90b1becb..93f9fc0c 100644
--- a/frontend/src/routes/runs/RunForm.tsx
+++ b/frontend/src/routes/runs/RunForm.tsx
@@ -5,19 +5,24 @@
 // Each submitted form goes under one key, sent again under it only when the same form is (an answer lost on the way).
 // A workflow that declares a CSV starts only with its file (§5.3, CsvPart), any other fields beside it, once every row
 // passes; the columns are saved first when asked, and a failed save starts nothing. A file checked against a version
-// published since the form was read has the form read again, as a refused start does.
+// published since the form was read has the form read again, as a refused start does. A re-run (§5.4; the Rerun board)
+// is the same form on the active version, the run's own input prefilled and its mode chosen (rerun.ts).
 import { useQuery, useQueryClient } from "@tanstack/react-query";
-import { useEffect, useId, useRef, useState, type FormEvent } from "react";
+import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
 import { Button } from "../../components/Button";
 import { TextArea } from "../../components/Field";
 import { When } from "../../components/When";
 import {
-  canSaveColumns, changedWords, keptValues, keyFor, refusalOf, saveColumns, startRun, type Refusal, type Sent, type StartBody, type StartForm,
+  canSaveColumns, changedWords, keptValues, keyFor, refusalOf, rerunRun, saveColumns, startRun, type Refusal, type RerunBody, type Sent,
+  type StartBody, type StartForm,
 } from "../../lib/runForm";  // prettier-ignore
+import { runInputQuery, type Run } from "../../lib/runs";
+import { runId } from "../../lib/runStatus";
 import { startFormQuery } from "../../lib/triggers";
 import { tenantQuery } from "../../lib/workflows";
 import { SimBanner } from "../editor/simulation/SimBanner";
 import { CsvPart } from "./CsvFile";
+import { AGAIN, MARKER_WORDS, holdsMarker, prefill, versionWords } from "./rerun";
 import { ENDED, csvReason, useCsvFile } from "./useCsvFile";
 import { InputControl, REQUIRED, fieldKey, fromFields, hintOf, labelOf, startValues, wholeOf } from "../editor/startInput";
 
@@ -56,8 +61,22 @@ function ModeChoice({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => voi
   );
 }
 
-export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, onClose }: {
+const NONE: ReadonlySet<string> = new Set();
+
+/** A field kept by the server, untouched: said, never shown. */
+function Kept({ label }: { label: ReactNode }) {
+  return (
+    <div className="flex flex-col gap-1.5">
+      <span className="text-small font-semibold">{label}</span>
+      <p className="text-small text-muted">Kept from the original run</p>
+    </div>
+  );
+}
+
+export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onStarted, onClose }: {
   tenantId: string; workflow: { id: string; name: string }; draftDiffers?: boolean;
+  /** A re-run of `run`, which ran version `ranVersion` (null when it never had one). */
+  rerun?: { run: Run; ranVersion: number | null };
   onStarted: (runId: string) => void; onClose: () => void;
 }) {  // prettier-ignore
   const id = useId();
@@ -72,9 +91,21 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
   // The version shown is the one confirmed: a later read of the query (a refetch elsewhere) never swaps it unseen.
   const [form, setForm] = useState<StartForm | null>(null);
   if (form === null && read.data) setForm(read.data);
-  const [mode, setMode] = useState<Mode>("live");
+  const [mode, setMode] = useState<Mode>(rerun?.run.mode ?? "live");
+  // A re-run's input, read back (§5.4): kept, absent or unreadable; absent too once the server says it's gone.
+  const original = useQuery({ ...runInputQuery(tenantId, rerun?.run.id ?? ""), enabled: rerun !== undefined });
+  const [gone, setGone] = useState(false);
+  const readBack = !rerun ? null : gone ? "absent" : original.isError ? "error" : (original.data?.read_back ?? null);
+  const prefilled = form && readBack === "kept" ? prefill(form, original.data?.input ?? null) : null;
+  const [touched, setTouched] = useState(false); // a re-run's input changed: sent whole
+  const keptShown = prefilled && !touched ? prefilled.kept : NONE; // said as kept
+  const again = prefilled && touched ? prefilled.kept : NONE; // entered again
   const [values, setValues] = useState<ReadonlyMap<string, string> | null>(null);
-  const shownValues = values ?? (form ? startValues(form) : new Map<string, string>());
+  const shownValues = values ?? (!form ? new Map<string, string>() : rerun ? (prefilled?.values ?? new Map<string, string>()) : startValues(form));
+  const change = (name: string, v: string) => {
+    setValues(new Map(shownValues).set(name, v));
+    setTouched(true);
+  };
   const [asJson, setAsJson] = useState(false);
   const [jsonText, setJsonText] = useState<string | null>(null);
   const [errors, setErrors] = useState<Record<string, string>>({});
@@ -116,8 +147,8 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
     );  // prettier-ignore
   }, [drifted]); // once per version found: the form and values of the draw that found it
 
-  // Focus goes to the first field once the form is read (§5.6); before, the dialog holds it.
-  const formRead = form !== null;
+  // Focus goes to the first field once the form is read (§5.6), a re-run's input with it; before, the dialog holds it.
+  const formRead = form !== null && (!rerun || readBack !== null);
   useEffect(() => {
     if (formRead) fieldsRef.current?.querySelector<HTMLElement>("input, select, textarea")?.focus();
   }, [formRead]);
@@ -130,22 +161,27 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
     setErrors({});
     setJsonText(Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "");
     setAsJson(true);
+    setTouched(true);
   };
 
   async function submit(e: FormEvent) {
     e.preventDefault();
     if (!form || sending || reason !== null) return;
-    let input: Record<string, unknown>;
-    if (asJson) {
-      const whole = wholeOf(shownJson);
-      if ("problem" in whole) return setErrors({ input: whole.problem });
-      input = whole.value;
-    } else {
-      const made = fromFields(form, shownValues, true, () => REQUIRED);
+    // Untouched, a re-run sends no input: the server rebuilds the original whole, its protected values too.
+    const whole = !(rerun && readBack === "kept" && !touched);
+    let input: Record<string, unknown> = {};
+    if (whole && asJson) {
+      const typed = wholeOf(shownJson);
+      if ("problem" in typed) return setErrors({ input: typed.problem });
+      if (rerun && holdsMarker(typed.value)) return setErrors({ input: MARKER_WORDS }); // never sent (§5.4)
+      input = typed.value;
+    } else if (whole) {
+      const entering = { fields: form.fields.map((f) => (again.has(f.name) ? { ...f, required: true } : f)) };
+      const made = fromFields(entering, shownValues, true, () => REQUIRED);
       if ("problems" in made) return setErrors(made.problems);
       input = made.input;
     }
-    const body: StartBody = { input, mode, expected_version_id: form.version_id };
+    const body: StartBody | RerunBody = whole ? { input, mode, expected_version_id: form.version_id } : { mode, expected_version_id: form.version_id };
     if (form.csv && csv.file.phase === "staged") body.csv = { upload_id: csv.file.upload.upload_id, mapping: csv.file.mapping };
     const sent = keyFor(last, body);
     setLast(sent);
@@ -160,11 +196,17 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
           return setRefusal({ code: "columns_unsaved", words: "The columns couldn't be saved, so nothing started. Start again, or leave them unsaved.", fields: {} });
         }
       }
-      const started = await startRun(tenantId, workflow.id, body, sent.key);
+      const started = rerun ? await rerunRun(tenantId, rerun.run.id, body, sent.key) : await startRun(tenantId, workflow.id, body as StartBody, sent.key);
       onStarted(started.id);
     } catch (err) {
       let refused = refusalOf(err, new Set(asJson ? [] : form.fields.map((f) => f.name)));
       if (ENDED.has(refused.code)) return csv.drop({ words: refused.words, code: refused.code }); // chosen again
+      if (rerun && refused.code === "input_not_retained") {
+        // Retention passed meanwhile: the form is the absent one (§5.4), its fields empty.
+        setGone(true);
+        setValues(new Map());
+        return;
+      }
       if (refused.code === "version_changed") {
         const r = await reread(form, shownValues);
         if ("refused" in r) refused = r.refused;
@@ -176,6 +218,15 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
     }
   }
 
+  const short = rerun ? runId(rerun.run.id) : "";
+  const INPUT_WORDS: Record<string, string> = {
+    kept: touched ? "Changed from the original run's input." : "The original run's input. Change what you need.",
+    absent: `Run ${short}'s input isn't kept, so it can't be sent again. Fill in the fields to run it again.`,
+    unreadable: `Run ${short}'s input can't be read back: it doesn't open, or the tenant's key is gone during an erasure. Fill in the fields to run it again.`,
+    error: `Run ${short}'s input couldn't be read. Fill in the fields to run it again.`,
+  };
+  const live = mode === "live";
+  const submitWords = rerun ? (live ? "Re-run live" : "◌ Re-run as a simulation") : live ? "Start the live run" : "◌ Start the simulation";
   return (
     <dialog
       ref={dialog}
@@ -185,29 +236,39 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
     >
       <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-4">
         <header>
-          <h2 id={`${id}-title`} className="text-h3 font-semibold">Start a run</h2>
+          <h2 id={`${id}-title`} className="text-h3 font-semibold">{rerun ? `Re-run ${short}` : "Start a run"}</h2>
           <p className="text-small text-muted">{workflow.name}</p>
         </header>
-        {read.isPending && form === null ? (
-          <p className="text-small text-muted">Loading the published version&apos;s input…</p>
+        {(read.isPending && form === null) || (form !== null && rerun && readBack === null) ? (
+          <p className="text-small text-muted">{rerun ? "Reading the run's input…" : "Loading the published version's input…"}</p>
         ) : form === null ? (
           <p role="alert" className="text-small text-danger">
             {read.isError ? "The published version's input couldn't be read. Close this and start again." : "This workflow has no published version: nothing can start."}
           </p>
         ) : (
           <>
-            <p className="text-small">
-              <span className="text-muted">Version</span>
-              {` ${form.version_number} · published `}
-              <When iso={form.published_at} />
-              {form.published_by ? ` by ${form.published_by}` : ""}
-            </p>
+            {rerun ? (
+              <p className="text-small">{versionWords(form, { id: rerun.run.version_id, number: rerun.ranVersion }, short)}</p>
+            ) : (
+              <p className="text-small">
+                <span className="text-muted">Version</span>
+                {` ${form.version_number} · published `}
+                <When iso={form.published_at} />
+                {form.published_by ? ` by ${form.published_by}` : ""}
+              </p>
+            )}
             {draftDiffers && (
               <p className="text-small text-muted">
                 {`The draft has changes that aren't published. This run uses version ${form.version_number}, not the draft.`}
               </p>
             )}
             <ModeChoice mode={mode} onChange={setMode} />
+            {rerun && readBack !== null && (
+              <div className="flex flex-col gap-1">
+                <h3 className="text-small font-semibold">Input</h3>
+                <p className="text-small">{INPUT_WORDS[readBack]}</p>
+              </div>
+            )}
             <div ref={fieldsRef} className="flex flex-col gap-4">
               {form.csv && (
                 <CsvPart
@@ -228,12 +289,17 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
               ) : (
                 <>
                   {form.fields.length === 0 && !form.csv && <p className="text-small text-muted">This version takes no input.</p>}
-                  {form.fields.map((f) => (
-                    <InputControl
-                      key={f.name} f={f} value={shownValues.get(f.name)} error={errors[fieldKey(f.name)]} label={labelOf(f)} hint={hintOf(f)}
-                      onChange={(v) => setValues(new Map(shownValues).set(f.name, v))}
-                    />
-                  ))}
+                  {form.fields.map((f) =>
+                    keptShown.has(f.name) ? (
+                      <Kept key={f.name} label={labelOf(f)} />
+                    ) : (
+                      <InputControl
+                        key={f.name} f={f} value={shownValues.get(f.name)} error={errors[fieldKey(f.name)]}
+                        label={labelOf(again.has(f.name) ? { ...f, required: true } : f)} hint={again.has(f.name) ? AGAIN : hintOf(f)}
+                        onChange={(v) => change(f.name, v)}
+                      />
+                    ),
+                  )}
                 </>
               )}
             </div>
@@ -259,7 +325,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, onStarted, o
             type="submit" variant={mode === "live" ? "live-outline" : "simulate"} disabled={form === null || sending || reason !== null}
             aria-describedby={reason ? `${id}-reason` : undefined}
           >
-            {`${mode === "live" ? "Start the live run" : "◌ Start the simulation"}${rows === null ? "" : ` · ${rows.toLocaleString("en-US")} row${rows === 1 ? "" : "s"}`}`}
+            {`${submitWords}${rows === null ? "" : ` · ${rows.toLocaleString("en-US")} row${rows === 1 ? "" : "s"}`}`}
           </Button>
         </div>
       </form>
diff --git a/frontend/src/routes/runs/RunPage.tsx b/frontend/src/routes/runs/RunPage.tsx
index d5407f9e..1b50cbe5 100644
--- a/frontend/src/routes/runs/RunPage.tsx
+++ b/frontend/src/routes/runs/RunPage.tsx
@@ -5,7 +5,9 @@
 // (useRunReads). A step's result opens in the editor's drawer, read only, its Result tab first; a failed run opens on
 // its failed step (the owner's answer 6), and Close gives focus back to its card. A run past its tenant's retention, or
 // an id that never was, is said to be neither, with Back to Runs; a run read while its tenant is erased says why it
-// can't be (§5.5). Cancel, for the roles that hold run.cancel, while it waits or runs (useCancel).
+// can't be (§5.5). Cancel, for the roles that hold run.cancel, while it waits or runs (useCancel). Re-run…, once it
+// has ended (or never started), for the roles that hold run.start (4e-2; the run form design §5.1): never on a draft
+// simulation, which opens in the editor, nor on a sub-run, which has no request of its own.
 import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { Link } from "@tanstack/react-router";
 import { useCallback, useMemo, useState, type KeyboardEvent } from "react";
@@ -14,6 +16,7 @@ import { ConfirmDialog } from "../../components/ConfirmDialog";
 import { When } from "../../components/When";
 import { ApiError } from "../../lib/client";
 import { START, findNode, idKey, nodesOf, portsOf, sameId } from "../../lib/graph";
+import { canStart } from "../../lib/runForm";
 import { canCancel, isEnded, runInstancesQuery, type Run, type RunStepSummary } from "../../lib/runs";
 import { reasonWords, runId } from "../../lib/runStatus";
 import { draftSnapshotQuery } from "../../lib/simulations";
@@ -33,7 +36,8 @@ import { useCanvasNav } from "../editor/useCanvasNav";
 import { RunBanner, RunBar } from "./RunBar";
 import { LoopResult, SeveralResult, StepResult } from "./RunResult";
 import { StartDrawer } from "./StartDrawer";
-import { useLanded } from "./landing";
+import { useLand, useLanded } from "./landing";
+import { RunForm } from "./RunForm";
 import { triggerOf, triggerWords } from "./trigger";
 import { useCancel } from "./useCancel";
 import { useRunReads } from "./useRunReads";
@@ -98,6 +102,8 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
   const tenant = useQuery(tenantQuery(tenantId));
   const cancel = useCancel(tenantId, id, r?.mode === "live");
   useLanded(id, r !== undefined); // a run just started: its name takes focus once read (4e-2)
+  const [rerunning, setRerunning] = useState(false);
+  const land = useLand(tenantId);
   // The graph it ran: its version's, or the draft a draft simulation froze for it. Neither ever changes.
   const version = useQuery({ ...versionQuery(tenantId, r?.workflow_id ?? "", r?.version_id ?? ""), enabled: !!r?.version_id });
   const snapshot = useQuery({ ...draftSnapshotQuery(tenantId, r?.workflow_id ?? "", r?.draft_snapshot_id ?? ""), enabled: !!r?.draft_snapshot_id });
@@ -180,7 +186,16 @@ export function RunPage({ tenantId, runId: id }: { tenantId: string; runId: stri
         {canCancel(tenant.data?.role) && !ended && !r.cancel_requested_at && (
           <Button size="sm" variant="danger-outline" disabled={cancel.state === "sending"} onClick={cancel.ask}>Cancel the run</Button>
         )}
+        {canStart(tenant.data?.role) && ended && r.draft_snapshot_id === null && r.parent === null && (
+          <Button size="sm" aria-haspopup="dialog" onClick={() => setRerunning(true)}>Re-run…</Button>
+        )}
       </RunBar>
+      {rerunning && (
+        <RunForm
+          tenantId={tenantId} workflow={{ id: r.workflow_id, name: r.workflow_name ?? "—" }} rerun={{ run: r, ranVersion: version.data?.number ?? null }}
+          onStarted={land} onClose={() => setRerunning(false)}
+        />
+      )}
       <div className="flex flex-col gap-2 border-b border-line bg-surface px-5 py-2.5">
         {steps.isLoadingError && (
           <p className="flex flex-wrap items-center gap-2 text-small">
diff --git a/frontend/src/routes/runs/rerun.ts b/frontend/src/routes/runs/rerun.ts
new file mode 100644
index 00000000..9c7f6208
--- /dev/null
+++ b/frontend/src/routes/runs/rerun.ts
@@ -0,0 +1,43 @@
+// SPDX-License-Identifier: Apache-2.0
+// A re-run's input (editor 4e-2b; the run form design §5.4; the Rerun board): the original's, read back redacted. What
+// the server kept of it (a protected value) is never shown here: untouched, the re-run sends no input and the server
+// rebuilds the original whole; changed, the input goes whole, those values entered again, the marker never sent.
+import type { StartForm } from "../../lib/runForm";
+import { shownOf } from "../editor/startInput";
+
+/** What the read-back writes where the original held a protected value (a claim: sensitive, undeclared, too large, or
+ * nested in a sensitive property). */
+export const REDACTED = "[redacted]";
+
+/** Whether a value read back is, or holds, the marker. */
+export function holdsMarker(v: unknown): boolean {
+  if (v === REDACTED) return true;
+  if (Array.isArray(v)) return v.some(holdsMarker);
+  return v !== null && typeof v === "object" && Object.values(v).some(holdsMarker);
+}
+
+/** The original's input on a form: each field's value as its control shows it, and the fields the server kept (marked
+ * sensitive, or read back holding the marker), shown as kept and entered again once the input changes. */
+export function prefill(form: StartForm, input: Record<string, unknown> | null): { values: Map<string, string>; kept: Set<string> } {
+  const values = new Map<string, string>();
+  const kept = new Set<string>();
+  for (const f of form.fields) {
+    if (input === null || !Object.hasOwn(input, f.name)) continue;
+    const v = input[f.name];
+    if (f.sensitive || holdsMarker(v)) kept.add(f.name);
+    else {
+      const shown = shownOf(f, v);
+      if (shown !== null) values.set(f.name, shown);
+    }
+  }
+  return { values, kept };
+}
+
+/** The version a re-run runs, beside the one its run ran (§5.4). */
+export const versionWords = (form: StartForm, ran: { id: string | null; number: number | null }, short: string) =>
+  ran.id === form.version_id
+    ? `It runs version ${form.version_number}, the same version as run ${short}.`
+    : `It runs version ${form.version_number}, the one published now.${ran.number === null ? "" : ` Run ${short} ran version ${ran.number}.`}`;
+
+export const MARKER_WORDS = `It holds ${REDACTED}, a protected value the original kept: enter that value again.`;
+export const AGAIN = "Enter it again: a changed input is sent whole, and the original's protected values never reach this form.";
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 50 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes
git commit -m "feat(editor): re-run a run, its input kept or changed (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Re-run a CSV run: its same rows, or another file

**Spec:** §5.4 (a CSV run, the original and the active version disagreeing about a CSV), §3's answer 10 (the same
rows' other fields read only); the Rerun board.

**Files:**
- Modify: `frontend/src/routes/runs/RunForm.tsx`, `frontend/src/routes/runs/RunForm.rerun.test.tsx`

**Interfaces:**
- Consumes: Tasks 5–7's CSV part and re-run.
- Produces: nothing other tasks use.

A CSV run's re-run offers its same rows (no input, no file; the other fields read only) or another file (the file's
flow, the fields whole), the same rows only while its input is kept (ruling 26). A run without rows on a version that
reads a CSV takes another file only; a version that reads no CSV starts the fields empty, saying why.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunForm.rerun.test.tsx b/frontend/src/routes/runs/RunForm.rerun.test.tsx
index 56733877..f05efbae 100644
--- a/frontend/src/routes/runs/RunForm.rerun.test.tsx
+++ b/frontend/src/routes/runs/RunForm.rerun.test.tsx
@@ -20,21 +20,43 @@ const FORM: StartForm = {
 };  // prettier-ignore
 const KEPT = { input: { site: "HQ", floor: 2, token: "[redacted]" }, read_back: "kept", seeds: null };
 
+// A CSV run (the Rerun board's third): 2,431 rows on version 7, its other fields a region and a token.
+const CSV_RUN: Run = {
+  ...FAILED_RUN, id: "77e0b9d2-0000-4000-8000-000000000005", version_id: "v7",
+  csv: { row_count: 2431, headers: ["Site name"], mapping: { name: "Site name" }, error_count: 0, errors: [], skipped: [] },
+};  // prettier-ignore
+const CSV_FORM: StartForm = {
+  workflow_id: "w1", version_id: "v7", version_number: 7, published_at: local(9, 0, 0), published_by: null,
+  fields: [
+    { name: "region", title: "Region", type: "string", required: true, sensitive: false },
+    { name: "token", title: "API token", type: "string", required: true, sensitive: true },
+  ],
+  csv: { max_rows: 10_000, max_bytes: 5 * 1024 * 1024, columns: [{ header: "Site name", name: "name", type: "string", required: true, sensitive: false }] },
+};  // prettier-ignore
+const CSV_KEPT = { input: { region: "EMEA", token: "[redacted]" }, read_back: "kept", seeds: null };
+const UPLOADED = {
+  version_id: "v7", upload_id: "u1", expires_at: local(11, 0, 0), headers: ["Site name"], row_count: 12, mapping: { name: "Site name" },
+  default_mapping: { status: "none" }, problems: [], masked_columns: [], preview: [], errors: [], error_count: 0, error_groups: [], rows_with_errors: 0,
+};  // prettier-ignore
+
 let input: unknown;
+let form: StartForm;
 let reruns: { key: string | null; body: unknown }[];
 let rerunAnswers: (() => Response)[];
 const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
 beforeEach(() => {
   input = KEPT;
+  form = FORM;
   reruns = [];
   rerunAnswers = [];
   vi.spyOn(Date, "now").mockReturnValue(Date.parse(local(10, 0, 0)));
   vi.spyOn(globalThis, "fetch").mockImplementation(async (req) => {
     const request = req as Request;
     const path = new URL(request.url).pathname;
-    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(FORM);
-    if (path === `/api/v1/t/t1/runs/${RUN.id}/input`) return json(input);
-    if (request.method === "POST" && path === `/api/v1/t/t1/runs/${RUN.id}/rerun`) {
+    if (path === "/api/v1/t/t1/workflows/w1/start-form") return json(form);
+    if (path.endsWith("/input")) return json(input);
+    if (request.method === "POST" && path === "/api/v1/t/t1/workflows/w1/csv-uploads") return json(UPLOADED, 201);
+    if (request.method === "POST" && path.endsWith("/rerun")) {
       reruns.push({ key: request.headers.get("Idempotency-Key"), body: JSON.parse(await request.text()) as unknown });
       return (rerunAnswers.shift() ?? (() => json({ id: "r1" }, 202)))();
     }
@@ -170,3 +192,59 @@ describe("re-running a run (the run form design §5.4; the Rerun board)", () =>
     expect(await site()).toHaveProperty("value", "");
   });
 });
+
+describe("re-running a CSV run (the run form design §5.4; the Rerun board)", () => {
+  beforeEach(() => {
+    form = CSV_FORM;
+    input = CSV_KEPT;
+  });
+
+  it("re-runs its same rows, sending neither input nor file, its other fields shown read only", async () => {
+    show(CSV_RUN, 7);
+    const same = await screen.findByRole("radio", { name: "The same rows: 2,431 rows, as run 77e0b9d2 read them" });
+    expect(same).toHaveProperty("checked", true);
+    expect(screen.getByText("EMEA")).toBeTruthy();
+    expect(screen.queryByRole("textbox", { name: /^Region/ })).toBeNull();
+    expect(screen.getByText("Kept from the original run")).toBeTruthy();
+    expect(screen.getByText("To change them, choose another file.")).toBeTruthy();
+    expect(screen.queryByRole("button", { name: "Edit as JSON" })).toBeNull();
+    await userEvent.click(screen.getByRole("button", { name: "Re-run live · 2,431 rows" }));
+    expect(reruns.map((r) => r.body)).toEqual([{ mode: "live", expected_version_id: "v7" }]);
+  });
+
+  it("re-runs another file, checked as for a new start, its other fields sent whole, protected ones entered again", async () => {
+    show(CSV_RUN, 7);
+    const user = userEvent.setup();
+    await user.click(await screen.findByRole("radio", { name: "Another file: it's checked here before the re-run starts, as for a new start" }));
+    expect(screen.getByLabelText(/^Region/)).toHaveProperty("value", "EMEA");
+    expect(screen.getByLabelText(/^API token/)).toHaveProperty("value", "");
+    await user.upload(screen.getByLabelText("Choose a file"), new File(["Site name\nLyon\n"], "more.csv", { type: "text/csv" }));
+    await user.type(screen.getByLabelText(/^API token/), "t");
+    await user.click(await screen.findByRole("button", { name: "Re-run live · 12 rows" }));
+    expect(reruns.map((r) => r.body)).toEqual([
+      { input: { region: "EMEA", token: "t" }, mode: "live", expected_version_id: "v7", csv: { upload_id: "u1", mapping: { name: "Site name" } } },
+    ]);
+  });
+
+  it("offers only another file once the run's input isn't kept", async () => {
+    input = { input: null, read_back: "absent", seeds: null };
+    show(CSV_RUN, 7);
+    expect(await screen.findByLabelText("Choose a file")).toBeTruthy();
+    expect(screen.queryByRole("radio", { name: /^The same rows/ })).toBeNull();
+    expect(screen.getByText("Run 77e0b9d2's input isn't kept, so it can't be sent again. Fill in the fields to run it again.")).toBeTruthy();
+  });
+
+  it("offers only another file when the run had no rows and the version reads a CSV", async () => {
+    show({ ...CSV_RUN, csv: null }, 6);
+    expect(await screen.findByLabelText("Choose a file")).toBeTruthy();
+    expect(screen.queryByRole("radio", { name: /^The same rows/ })).toBeNull();
+  });
+
+  it("starts from empty fields when the run had rows and the version reads no CSV, saying why", async () => {
+    form = FORM;
+    show(CSV_RUN, 7);
+    expect(await screen.findByText("Version 12 doesn't read a CSV file: fill in its fields.")).toBeTruthy();
+    expect(await site()).toHaveProperty("value", "");
+    expect(screen.getByLabelText(/^API token/)).toHaveProperty("value", "");
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunForm.rerun.test.tsx`

Expected: FAIL, 3 failed and 12 passed: a CSV run's re-run offers no choice of rows (`Unable to find role="radio" and
name "The same rows: 2,431 rows, as run 77e0b9d2 read them"`, and none for another file), and a version that reads no
CSV says nothing of it. "offers only another file once the run's input isn't kept" and "… when the run had no rows and
the version reads a CSV" pass at once: Task 7's form already shows only the file's flow there; they pin it now that the
same rows can be offered.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/runs/RunForm.tsx b/frontend/src/routes/runs/RunForm.tsx
index 93f9fc0c..f05bb6f8 100644
--- a/frontend/src/routes/runs/RunForm.tsx
+++ b/frontend/src/routes/runs/RunForm.tsx
@@ -63,12 +63,14 @@ function ModeChoice({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => voi
 
 const NONE: ReadonlySet<string> = new Set();
 
-/** A field kept by the server, untouched: said, never shown. */
-function Kept({ label }: { label: ReactNode }) {
+const KEPT = "Kept from the original run";
+
+/** A field a re-run sends as the original had it: its value, or that the server kept it (never shown). */
+function ReadOnly({ label, value }: { label: ReactNode; value: string }) {
   return (
     <div className="flex flex-col gap-1.5">
       <span className="text-small font-semibold">{label}</span>
-      <p className="text-small text-muted">Kept from the original run</p>
+      <p className={`text-small ${value === KEPT ? "text-muted" : ""}`}>{value}</p>
     </div>
   );
 }
@@ -96,10 +98,17 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
   const original = useQuery({ ...runInputQuery(tenantId, rerun?.run.id ?? ""), enabled: rerun !== undefined });
   const [gone, setGone] = useState(false);
   const readBack = !rerun ? null : gone ? "absent" : original.isError ? "error" : (original.data?.read_back ?? null);
-  const prefilled = form && readBack === "kept" ? prefill(form, original.data?.input ?? null) : null;
+  // A CSV run (§5.4): its same rows, read again by the server with its input, or another file; on a version that reads
+  // no CSV, the fields alone, from empty. The same rows only while the input is kept.
+  const [source, setSource] = useState<"same" | "file">("same");
+  const csvGone = !!rerun?.run.csv && form !== null && form.csv === null;
+  const offerSame = !!rerun?.run.csv && !!form?.csv && readBack === "kept";
+  const sameRows = offerSame && source === "same";
+  const prefilled = form && readBack === "kept" && !csvGone ? prefill(form, original.data?.input ?? null) : null;
   const [touched, setTouched] = useState(false); // a re-run's input changed: sent whole
-  const keptShown = prefilled && !touched ? prefilled.kept : NONE; // said as kept
-  const again = prefilled && touched ? prefilled.kept : NONE; // entered again
+  const changed = touched || (!!rerun && !!form?.csv && !sameRows); // another file: the fields go whole beside it
+  const keptShown = prefilled && !changed ? prefilled.kept : NONE; // said as kept
+  const again = prefilled && changed ? prefilled.kept : NONE; // entered again
   const [values, setValues] = useState<ReadonlyMap<string, string> | null>(null);
   const shownValues = values ?? (!form ? new Map<string, string>() : rerun ? (prefilled?.values ?? new Map<string, string>()) : startValues(form));
   const change = (name: string, v: string) => {
@@ -114,8 +123,10 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
   const [sending, setSending] = useState(false);
   const shownJson = jsonText ?? "";
   const csv = useCsvFile(tenantId, workflow.id);
-  const reason = form?.csv ? csvReason(csv.file, form.csv.columns) : null;
-  const rows = form?.csv && csv.file.phase === "staged" && reason === null ? csv.file.upload.row_count : null;
+  const reason = form?.csv && !sameRows ? csvReason(csv.file, form.csv.columns) : null;
+  const rows = sameRows
+    ? rerun.run.csv!.row_count
+    : form?.csv && csv.file.phase === "staged" && reason === null ? csv.file.upload.row_count : null;  // prettier-ignore
   const tenant = useQuery(tenantQuery(tenantId));
   const saveable = canSaveColumns(tenant.data?.role);
   const [save, setSave] = useState(false);
@@ -168,7 +179,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
     e.preventDefault();
     if (!form || sending || reason !== null) return;
     // Untouched, a re-run sends no input: the server rebuilds the original whole, its protected values too.
-    const whole = !(rerun && readBack === "kept" && !touched);
+    const whole = !(rerun && readBack === "kept" && !csvGone && (sameRows || (!form.csv && !touched)));
     let input: Record<string, unknown> = {};
     if (whole && asJson) {
       const typed = wholeOf(shownJson);
@@ -182,7 +193,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
       input = made.input;
     }
     const body: StartBody | RerunBody = whole ? { input, mode, expected_version_id: form.version_id } : { mode, expected_version_id: form.version_id };
-    if (form.csv && csv.file.phase === "staged") body.csv = { upload_id: csv.file.upload.upload_id, mapping: csv.file.mapping };
+    if (form.csv && !sameRows && csv.file.phase === "staged") body.csv = { upload_id: csv.file.upload.upload_id, mapping: csv.file.mapping };
     const sent = keyFor(last, body);
     setLast(sent);
     setErrors({});
@@ -219,8 +230,8 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
   }
 
   const short = rerun ? runId(rerun.run.id) : "";
-  const INPUT_WORDS: Record<string, string> = {
-    kept: touched ? "Changed from the original run's input." : "The original run's input. Change what you need.",
+  const INPUT_WORDS: Record<string, string | null> = {
+    kept: form?.csv ? null : touched ? "Changed from the original run's input." : "The original run's input. Change what you need.",
     absent: `Run ${short}'s input isn't kept, so it can't be sent again. Fill in the fields to run it again.`,
     unreadable: `Run ${short}'s input can't be read back: it doesn't open, or the tenant's key is gone during an erasure. Fill in the fields to run it again.`,
     error: `Run ${short}'s input couldn't be read. Fill in the fields to run it again.`,
@@ -264,19 +275,42 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
             )}
             <ModeChoice mode={mode} onChange={setMode} />
             {rerun && readBack !== null && (
-              <div className="flex flex-col gap-1">
-                <h3 className="text-small font-semibold">Input</h3>
-                <p className="text-small">{INPUT_WORDS[readBack]}</p>
-              </div>
+              <fieldset className="flex flex-col gap-1.5">
+                <legend className="mb-1 text-small font-semibold">Input</legend>
+                {csvGone ? (
+                  <p className="text-small">{`Version ${form.version_number} doesn't read a CSV file: fill in its fields.`}</p>
+                ) : (
+                  INPUT_WORDS[readBack] && <p className="text-small">{INPUT_WORDS[readBack]}</p>
+                )}
+                {offerSame && (
+                  <>
+                    <label className="flex min-h-6 items-center gap-2 text-small">
+                      <input type="radio" name={`${id}-source`} checked={source === "same"} onChange={() => setSource("same")} className="size-[16px] accent-accent" />
+                      {`The same rows: ${rerun.run.csv!.row_count.toLocaleString("en-US")} rows, as run ${short} read them`}
+                    </label>
+                    <label className="flex min-h-6 items-center gap-2 text-small">
+                      <input type="radio" name={`${id}-source`} checked={source === "file"} onChange={() => setSource("file")} className="size-[16px] accent-accent" />
+                      Another file: it&apos;s checked here before the re-run starts, as for a new start
+                    </label>
+                  </>
+                )}
+              </fieldset>
             )}
             <div ref={fieldsRef} className="flex flex-col gap-4">
-              {form.csv && (
+              {form.csv && !sameRows && (
                 <CsvPart
                   form={form} csv={form.csv} file={csv.file} saveable={saveable} save={save} onSave={setSave}
                   onChoose={(f) => void csv.choose(f, form.csv!)} onMap={(column, header) => csv.map(column, header, form.csv!)}
                 />
               )}
-              {asJson ? (
+              {sameRows ? (
+                <>
+                  {form.fields.map((f) => (
+                    <ReadOnly key={f.name} label={labelOf(f)} value={prefilled?.kept.has(f.name) ? KEPT : (prefilled?.values.get(f.name) ?? "Not given")} />
+                  ))}
+                  {form.fields.length > 0 && <p className="text-small text-muted">To change them, choose another file.</p>}
+                </>
+              ) : asJson ? (
                 <TextArea
                   label="The input, as JSON"
                   hint='An object, like {"site": "HQ"}. Shown as typed, a sensitive value too.'
@@ -291,7 +325,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
                   {form.fields.length === 0 && !form.csv && <p className="text-small text-muted">This version takes no input.</p>}
                   {form.fields.map((f) =>
                     keptShown.has(f.name) ? (
-                      <Kept key={f.name} label={labelOf(f)} />
+                      <ReadOnly key={f.name} label={labelOf(f)} value={KEPT} />
                     ) : (
                       <InputControl
                         key={f.name} f={f} value={shownValues.get(f.name)} error={errors[fieldKey(f.name)]}
@@ -303,7 +337,7 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
                 </>
               )}
             </div>
-            {(form.fields.length > 0 || !form.csv) && (
+            {(form.fields.length > 0 || !form.csv) && !sameRows && (
               <div>
                 <Button size="sm" aria-pressed={asJson} onClick={() => (asJson ? (setAsJson(false), setJsonText(null)) : toJson())}>
                   Edit as JSON
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 15 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes
git commit -m "feat(editor): re-run a CSV run, its same rows or another file (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The form at 320 px

**Spec:** §5.6 (below 640 px: the form fills the screen, its buttons stacked full width, Start first; the errors one
item per problem); the Narrow320Light and Narrow320Dark boards.

**Files:**
- Modify: `frontend/src/routes/runs/RunForm.tsx`, `frontend/src/routes/runs/RunForm.test.tsx`
- Modify: `frontend/src/routes/runs/CsvFile.tsx`, `frontend/src/routes/runs/RunForm.csv.test.tsx`
- Modify: `frontend/src/lib/runForm.ts`, `frontend/src/lib/runForm.test.ts` (`groupRows`' `"rows"`)

**Interfaces:**
- Consumes: `useNarrow` (`lib/media.ts`).
- Produces: `groupRows(group, unit?: "rows")`.

Below 640 px the form is a full-screen sheet with Close, its buttons stacked, Start first in the page's order as on
screen; the columns and the problems become lists (ruling 28).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.test.ts b/frontend/src/lib/runForm.test.ts
index 39e49996..4a3bb057 100644
--- a/frontend/src/lib/runForm.test.ts
+++ b/frontend/src/lib/runForm.test.ts
@@ -180,6 +180,8 @@ describe("a checked file, in words (§5.3; the CsvStates board)", () => {
     expect(groupRows({ count: 21, rows: [7, 19, 33, 48, 52] })).toBe("21 · 7, 19, 33, 48, 52 and 16 more");
     expect(groupRows({ count: 3, rows: [7, 19, 33] })).toBe("3 · 7, 19 and 33");
     expect(groupRows({ count: 1, rows: [1204] })).toBe("1 · 1,204");
+    expect(groupRows({ count: 21, rows: [7, 19, 33, 48, 52] }, "rows")).toBe("21 rows · 7, 19, 33, 48, 52 and 16 more"); // a list's item
+    expect(groupRows({ count: 1, rows: [3] }, "rows")).toBe("1 row · 3");
   });
 
   it("says a version was published meanwhile as a refused start does", () => {
diff --git a/frontend/src/routes/runs/RunForm.csv.test.tsx b/frontend/src/routes/runs/RunForm.csv.test.tsx
index bbd5b64d..ace81150 100644
--- a/frontend/src/routes/runs/RunForm.csv.test.tsx
+++ b/frontend/src/routes/runs/RunForm.csv.test.tsx
@@ -394,3 +394,26 @@ describe("a CSV file checked (the run form design §5.3; the CsvStates and MoreS
     ]);
   });
 });
+
+describe("a CSV file below 640 px (the run form design §5.6; the Narrow320 boards)", () => {
+  beforeEach(() => {
+    const wide = window.matchMedia.bind(window);
+    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({ ...wide(query), matches: true }));
+  });
+
+  it("lists each column with its choice, and each problem with its rows", async () => {
+    uploadAnswer = () => Promise.resolve(json(upload(ERRORS), 201));
+    show();
+    await choose();
+    const columns = await screen.findByRole("list", { name: "Columns" });
+    expect(within(columns).getAllByRole("listitem")).toHaveLength(5);
+    expect(within(columns).getByRole("combobox", { name: "Country, from the file's column" })).toBeTruthy();
+    expect(screen.queryByRole("region", { name: "Columns" })).toBeNull();
+    const problems = within(screen.getByRole("list", { name: "Errors by column" })).getAllByRole("listitem");
+    expect(problems.map((p) => [...p.querySelectorAll("p")].map((l) => l.textContent))).toEqual([
+      ["Country · Not one of the allowed values", "21 rows · 7, 19, 33, 48, 52 and 16 more"],
+      ["Gateway · Not an IP address", "10 rows · 12, 13, 14, 15, 16 and 5 more"],
+      ["The whole row · Has more or fewer cells than the header", "6 rows · 102, 140, 141, 150, 151 and 1 more"],
+    ]);
+  });
+});
diff --git a/frontend/src/routes/runs/RunForm.test.tsx b/frontend/src/routes/runs/RunForm.test.tsx
index 174fbcba..2f2c1a7d 100644
--- a/frontend/src/routes/runs/RunForm.test.tsx
+++ b/frontend/src/routes/runs/RunForm.test.tsx
@@ -204,3 +204,20 @@ describe("the run form (the run form design §5.2; the Main board)", () => {
     expect(posts).toEqual([]);
   });
 });
+
+describe("below 640 px (the run form design §5.6; the Narrow320 boards)", () => {
+  beforeEach(() => {
+    const wide = window.matchMedia.bind(window);
+    vi.spyOn(window, "matchMedia").mockImplementation((query) => ({ ...wide(query), matches: true }));
+  });
+
+  it("fills the screen, with a Close button, its buttons stacked, Start first", async () => {
+    const { onClose } = show();
+    await screen.findByLabelText(/Site/);
+    expect(dialog().className).toContain("h-dvh");
+    const buttons = within(dialog()).getAllByRole("button").map((b) => b.textContent);
+    expect(buttons.slice(-2)).toEqual(["Start the live run", "Cancel"]);
+    await userEvent.click(screen.getByRole("button", { name: "Close" }));
+    expect(onClose).toHaveBeenCalled();
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/runs/RunForm.test.tsx src/routes/runs/RunForm.csv.test.tsx
src/lib/runForm.test.ts`

Expected: FAIL, 3 failed and 53 passed: `groupRows` has no list item's form (`expected '21 · 7, 19, 33, 48, 52 and 16
more' to be '21 rows · 7, 19, 33, 48, 52 and 16 mo…'`); the form doesn't fill the screen (`expected 'mx-auto mt-16
w-[600px] max-w-[calc(1…' to contain 'h-dvh'`), and the columns aren't a list (`Unable to find role="list" and name
"Columns"`).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/runForm.ts b/frontend/src/lib/runForm.ts
index 04575498..16b4e788 100644
--- a/frontend/src/lib/runForm.ts
+++ b/frontend/src/lib/runForm.ts
@@ -243,10 +243,11 @@ export const checkedWords = (shown: Pick<CsvPreview, "error_count" | "rows_with_
     ? `All ${count(rows)} rows pass.`
     : `${plural(shown.error_count, "error")} in ${count(shown.rows_with_errors)} of ${plural(rows, "row")}`;
 
-/** A column's problem: how many rows, the first ones, and how many more (§4.4: its first five). */
-export function groupRows(g: { count: number; rows: number[] }): string {
+/** A column's problem: how many rows, the first ones, and how many more (§4.4: its first five); a list's item says
+ * "rows" after the count, with no header above it. */
+export function groupRows(g: { count: number; rows: number[] }, unit?: "rows"): string {
   const rows = g.rows.map(count);
   const more = g.count - rows.length;
   const said = more > 0 ? `${rows.join(", ")} and ${more} more` : rows.length < 2 ? (rows[0] ?? "") : `${rows.slice(0, -1).join(", ")} and ${rows.at(-1)!}`;
-  return `${count(g.count)} · ${said}`;
+  return `${unit ? plural(g.count, "row") : count(g.count)} · ${said}`;
 }
diff --git a/frontend/src/routes/runs/CsvFile.tsx b/frontend/src/routes/runs/CsvFile.tsx
index 321f94ef..e9372366 100644
--- a/frontend/src/routes/runs/CsvFile.tsx
+++ b/frontend/src/routes/runs/CsvFile.tsx
@@ -2,13 +2,15 @@
 // A CSV run's file in the run form (editor 4e-2b; the run form design §5.3; the CsvStates and MoreStates boards): what
 // the workflow reads before a file, the file being read, why one can't be, and the file's column chosen for each of the
 // workflow's, with how it was proposed. Once checked: its errors at a glance (counted by column and problem on the
-// server, every error), or, every row passing, its first rows as written, the columns folded to a line.
+// server, every error), or, every row passing, its first rows as written, the columns folded to a line. Below 640 px
+// the columns and the problems are lists, one item each (§5.6; the Narrow320 boards).
 import { useId, useState, type ChangeEvent, type DragEvent } from "react";
 import { Button, LINK_BUTTON } from "../../components/Button";
 import { controlClass } from "../../components/Field";
 import { Table, Th } from "../../components/Table";
 import { Tag } from "../../components/Tag";
 import { mbOf } from "../../lib/csv";
+import { useNarrow } from "../../lib/media";
 import { cellWords, checkedWords, groupRows, holds, mappingWords, staleWords, type CsvColumnForm, type CsvPreview, type StartForm } from "../../lib/runForm";
 import { listed } from "../editor/startInput";
 import { unmapped, type CsvFile } from "./useCsvFile";
@@ -70,44 +72,64 @@ function Reads({ csv }: { csv: Csv }) {
 
 function Columns({ csv, file, onMap }: { csv: Csv; file: Extract<CsvFile, { phase: "staged" }>; onMap: (column: string, header: string) => void }) {
   const id = useId();
+  const narrow = useNarrow();
   const missing = new Set(unmapped(csv.columns, file.mapping));
   // A problem the server found under the columns chosen now: an answer for other columns says nothing of these.
   const problem = (c: CsvColumnForm) => file.shown.problems.find((p) => p.column === c.name && file.shown.mapping[c.name] === file.mapping[c.name]);
+  /** A column's choice of the file's column, and what keeps it from building rows. */
+  const choice = (c: CsvColumnForm, i: number) => {
+    const chosen = file.mapping[c.name] ?? "";
+    const found = problem(c);
+    const error = missing.has(c.name) ? mappingWords("required_unmapped") : found ? mappingWords(found.code) : undefined;
+    const errorId = `${id}-${i}-err`;
+    return (
+      <>
+        <select
+          aria-label={`${c.header}, from the file's column`} aria-invalid={!!error} aria-describedby={error ? errorId : undefined}
+          value={chosen} onChange={(e) => onMap(c.name, e.target.value)} className={`${controlClass(!!error)} min-w-40`}
+        >
+          <option value="">{c.required ? "Choose a column" : "Not used"}</option>
+          {chosen && !file.upload.headers.includes(chosen) && <option value={chosen}>{chosen}</option>}
+          {file.upload.headers.map((h) => <option key={h} value={h}>{h}</option>)}
+        </select>
+        {error && <p id={errorId} className="mt-1 text-small text-danger">{error}</p>}
+      </>
+    );  // prettier-ignore
+  };
   return (
     <>
       <div className="flex flex-col gap-1">
         <h3 className="text-small font-semibold">Columns</h3>
         <p className="text-small text-muted">Each column the workflow reads, and the file&apos;s column it comes from.</p>
       </div>
-      <Table label="Columns">
-        <thead>
-          <tr><Th>Column</Th><Th>From the file&apos;s</Th><Th>How</Th></tr>
-        </thead>
-        <tbody>
-          {csv.columns.map((c, i) => {
-            const chosen = file.mapping[c.name] ?? "";
-            const error = missing.has(c.name) ? mappingWords("required_unmapped") : problem(c) ? mappingWords(problem(c)!.code) : undefined;
-            const errorId = `${id}-${i}-err`;
-            return (
+      {narrow ? (
+        <ul aria-label="Columns" className="flex flex-col rounded-lg border border-line">
+          {csv.columns.map((c, i) => (
+            <li key={c.name} className="flex flex-col gap-1.5 border-t border-line px-3 py-2.5 first:border-t-0">
+              <div className="flex items-start justify-between gap-2">
+                <span className="text-small"><ColumnName c={c} /></span>
+                <span className="text-small text-muted">{file.how[c.name] ?? ""}</span>
+              </div>
+              {choice(c, i)}
+            </li>
+          ))}
+        </ul>
+      ) : (
+        <Table label="Columns">
+          <thead>
+            <tr><Th>Column</Th><Th>From the file&apos;s</Th><Th>How</Th></tr>
+          </thead>
+          <tbody>
+            {csv.columns.map((c, i) => (
               <tr key={c.name}>
                 <th scope="row" className={ROW_HEAD}><ColumnName c={c} /></th>
-                <td className={CELL}>
-                  <select
-                    aria-label={`${c.header}, from the file's column`} aria-invalid={!!error} aria-describedby={error ? errorId : undefined}
-                    value={chosen} onChange={(e) => onMap(c.name, e.target.value)} className={`${controlClass(!!error)} min-w-40`}
-                  >
-                    <option value="">{c.required ? "Choose a column" : "Not used"}</option>
-                    {chosen && !file.upload.headers.includes(chosen) && <option value={chosen}>{chosen}</option>}
-                    {file.upload.headers.map((h) => <option key={h} value={h}>{h}</option>)}
-                  </select>
-                  {error && <p id={errorId} className="mt-1 text-small text-danger">{error}</p>}
-                </td>
+                <td className={CELL}>{choice(c, i)}</td>
                 <td className={`${CELL} text-small text-muted`}>{file.how[c.name] ?? ""}</td>
               </tr>
-            );  // prettier-ignore
-          })}
-        </tbody>
-      </Table>
+            ))}
+          </tbody>
+        </Table>
+      )}
       {missing.size > 0 && <p className="text-small">No row is checked until every required column is mapped.</p>}
     </>
   );
@@ -117,24 +139,36 @@ function Columns({ csv, file, onMap }: { csv: Csv; file: Extract<CsvFile, { phas
 const headerOf = (csv: Csv, name: string | null) => (name === null ? "The whole row" : (csv.columns.find((c) => c.name === name)?.header ?? name));
 
 function Errors({ csv, shown, rows }: { csv: Csv; shown: CsvPreview; rows: number }) {
+  const narrow = useNarrow();
   return (
     <div className="flex flex-col gap-2">
       <p className="text-small font-semibold text-danger">{checkedWords(shown, rows)}</p>
       <p className="text-small">The run can&apos;t start until every row passes. Fix the file, then choose it again.</p>
-      <Table label="Errors by column">
-        <thead>
-          <tr><Th>Column</Th><Th>Problem</Th><Th>Rows</Th></tr>
-        </thead>
-        <tbody>
+      {narrow ? (
+        <ul aria-label="Errors by column" className="flex flex-col rounded-lg border border-line">
           {shown.error_groups.map((g) => (
-            <tr key={`${g.column ?? ""}:${g.code}`}>
-              <td className={`${CELL} text-small`}>{headerOf(csv, g.column)}</td>
-              <td className={`${CELL} text-small`}>{cellWords(g.code)}</td>
-              <td className={`${CELL} font-mono text-small`}>{groupRows(g)}</td>
-            </tr>
+            <li key={`${g.column ?? ""}:${g.code}`} className="flex flex-col gap-0.5 border-t border-line px-3 py-2 first:border-t-0">
+              <p className="text-small">{`${headerOf(csv, g.column)} · ${cellWords(g.code)}`}</p>
+              <p className="font-mono text-small text-muted">{groupRows(g, "rows")}</p>
+            </li>
           ))}
-        </tbody>
-      </Table>
+        </ul>
+      ) : (
+        <Table label="Errors by column">
+          <thead>
+            <tr><Th>Column</Th><Th>Problem</Th><Th>Rows</Th></tr>
+          </thead>
+          <tbody>
+            {shown.error_groups.map((g) => (
+              <tr key={`${g.column ?? ""}:${g.code}`}>
+                <td className={`${CELL} text-small`}>{headerOf(csv, g.column)}</td>
+                <td className={`${CELL} text-small`}>{cellWords(g.code)}</td>
+                <td className={`${CELL} font-mono text-small`}>{groupRows(g)}</td>
+              </tr>
+            ))}
+          </tbody>
+        </Table>
+      )}
       <details className="text-small">
         <summary className="min-h-6 cursor-pointer">{`Every error, row by row (${count(shown.error_count)})`}</summary>
         <Table label="Every error, row by row" className="mt-2">
diff --git a/frontend/src/routes/runs/RunForm.tsx b/frontend/src/routes/runs/RunForm.tsx
index f05bb6f8..6705d37c 100644
--- a/frontend/src/routes/runs/RunForm.tsx
+++ b/frontend/src/routes/runs/RunForm.tsx
@@ -6,7 +6,8 @@
 // A workflow that declares a CSV starts only with its file (§5.3, CsvPart), any other fields beside it, once every row
 // passes; the columns are saved first when asked, and a failed save starts nothing. A file checked against a version
 // published since the form was read has the form read again, as a refused start does. A re-run (§5.4; the Rerun board)
-// is the same form on the active version, the run's own input prefilled and its mode chosen (rerun.ts).
+// is the same form on the active version, the run's own input prefilled and its mode chosen (rerun.ts). Below 640 px
+// it fills the screen, with a Close button, its buttons stacked full width, Start first (§5.6; the Narrow320 boards).
 import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode } from "react";
 import { Button } from "../../components/Button";
@@ -19,6 +20,7 @@ import {
 import { runInputQuery, type Run } from "../../lib/runs";
 import { runId } from "../../lib/runStatus";
 import { startFormQuery } from "../../lib/triggers";
+import { useNarrow } from "../../lib/media";
 import { tenantQuery } from "../../lib/workflows";
 import { SimBanner } from "../editor/simulation/SimBanner";
 import { CsvPart } from "./CsvFile";
@@ -237,18 +239,30 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
     error: `Run ${short}'s input couldn't be read. Fill in the fields to run it again.`,
   };
   const live = mode === "live";
+  const narrow = useNarrow();
+  const close = () => dialog.current?.close(); // its close event closes the form, giving focus back to its opener
+  const cancel = <Button onClick={close} className={narrow ? "w-full" : ""}>Cancel</Button>;
   const submitWords = rerun ? (live ? "Re-run live" : "◌ Re-run as a simulation") : live ? "Start the live run" : "◌ Start the simulation";
   return (
     <dialog
       ref={dialog}
       aria-labelledby={`${id}-title`}
       onClose={onClose}
-      className="mx-auto mt-16 w-[600px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
+      className={`bg-surface text-ink backdrop:bg-overlay ${narrow
+        ? "m-0 h-dvh max-h-none w-screen max-w-none overflow-y-auto p-4"
+        : "mx-auto mt-16 w-[600px] max-w-[calc(100vw-32px)] rounded-dialog border border-line p-6 shadow-dialog"}`}  // prettier-ignore
     >
       <form onSubmit={(e) => void submit(e)} className="flex flex-col gap-4">
-        <header>
-          <h2 id={`${id}-title`} className="text-h3 font-semibold">{rerun ? `Re-run ${short}` : "Start a run"}</h2>
-          <p className="text-small text-muted">{workflow.name}</p>
+        <header className="flex items-start justify-between gap-3">
+          <div className="min-w-0">
+            <h2 id={`${id}-title`} className="text-h3 font-semibold">{rerun ? `Re-run ${short}` : "Start a run"}</h2>
+            <p className="text-small text-muted">{workflow.name}</p>
+          </div>
+          {narrow && (
+            <button type="button" aria-label="Close" onClick={close} className="inline-grid size-11 shrink-0 place-items-center rounded-lg text-body-lg text-muted hover:bg-surface-hover">
+              <span aria-hidden="true">✕</span>
+            </button>
+          )}
         </header>
         {(read.isPending && form === null) || (form !== null && rerun && readBack === null) ? (
           <p className="text-small text-muted">{rerun ? "Reading the run's input…" : "Loading the published version's input…"}</p>
@@ -352,15 +366,16 @@ export function RunForm({ tenantId, workflow, draftDiffers = false, rerun, onSta
             {CODED(refusal.code) && <> <span className="font-mono">{refusal.code}</span></>}
           </p>
         )}
-        <div className="flex flex-wrap items-center justify-end gap-2">
-          {reason && <p id={`${id}-reason`} className="me-auto text-small text-muted">{reason}</p>}
-          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
+        <div className={narrow ? "flex flex-col gap-2" : "flex flex-wrap items-center justify-end gap-2"}>
+          {reason && <p id={`${id}-reason`} className={narrow ? "text-small text-muted" : "me-auto text-small text-muted"}>{reason}</p>}
+          {!narrow && cancel}
           <Button
             type="submit" variant={mode === "live" ? "live-outline" : "simulate"} disabled={form === null || sending || reason !== null}
-            aria-describedby={reason ? `${id}-reason` : undefined}
+            aria-describedby={reason ? `${id}-reason` : undefined} className={narrow ? "w-full" : ""}
           >
             {`${submitWords}${rows === null ? "" : ` · ${rows.toLocaleString("en-US")} row${rows === 1 ? "" : "s"}`}`}
           </Button>
+          {narrow && cancel /* stacked: Start first (the Narrow320 boards) */}
         </div>
       </form>
     </dialog>
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 56 passed.

- [ ] **Step 5: Static checks**

Run: the two of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/lib frontend/src/routes
git commit -m "feat(editor): the run form at 320 px (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4e-2b, milestone 3 (<date>)` to the ledger, as for milestone 1, commit it as
`docs(editor-4): 4e-2b milestone 3`, and **pause** for the owner's review.

---

# Milestone 4 — Close

### Task 10: In the browser

**Spec:** §6 (4e-2b: the Playwright gate, light and dark, at 1280 and 320 px, on the Compose stack: a typed start
landing on its run's page, a CSV start with errors and then a clean file, a re-run; control steps only, run live).

**Files:**
- Create: `frontend/e2e/seed.ts` (`api` and `accessibleBothWays`, moved from `runs.spec.ts`),
  `frontend/e2e/runForm.spec.ts`, `frontend/e2e/fixtures/runs-csv.dewpoint.json`
- Modify: `frontend/e2e/runs.spec.ts` (imports them), `frontend/playwright.config.ts` (the workflows project runs
  `runForm.spec.ts`)

**Interfaces:**
- Consumes: `test`, `expect`, `expectAccessible` (`e2e/gate.ts`); the admin's saved state (the foundations project).
- Produces: `e2e/seed.ts`: `api(page)` (publish, start, ended, running), `accessibleBothWays(page, screen)`.

"Runs CSV" is a control step reading `trigger.row_count` and `trigger.region`, with two columns (Site required, VLAN a
whole number) and a Region field beside. The specs:
- a typed start from the Workflows list, live and simulated, light and dark, landing on its run's page, its name
  focused;
- a CSV start from the Runs page's chooser: a file with two errors in one row, then a clean one, started;
- an ended run re-run with its input changed;
- at 320 px: the form full screen, Close giving focus back to Start a run….

The gate fails any CSP violation, console error or request to another origin (ruling 29).

- [ ] **Step 1: Write the specs**

Apply:

```diff
diff --git a/frontend/e2e/fixtures/runs-csv.dewpoint.json b/frontend/e2e/fixtures/runs-csv.dewpoint.json
new file mode 100644
index 00000000..1c4ac512
--- /dev/null
+++ b/frontend/e2e/fixtures/runs-csv.dewpoint.json
@@ -0,0 +1,24 @@
+{
+  "format": "dewpoint.workflow",
+  "format_version": 1,
+  "name": "Runs CSV",
+  "graph": {
+    "graph_format": 1,
+    "nodes": [
+      { "id": "4b8d2e6f-1a3c-4e5f-8a7b-9c0d1e2f3a01", "key": "count", "type": "flow.transform@1", "config": { "fields": { "sites": { "$value": { "kind": "cel", "expr": "trigger.row_count" } }, "region": { "$value": { "kind": "cel", "expr": "trigger.region" } } } }, "position": { "x": 0, "y": 140 } }
+    ],
+    "edges": [],
+    "settings": {
+      "input_schema": { "type": "object", "properties": { "region": { "type": "string", "title": "Region" } }, "required": ["region"] },
+      "csv": {
+        "columns": [
+          { "header": "Site", "name": "site", "type": "string", "required": true },
+          { "header": "VLAN", "name": "vlan", "type": "integer" }
+        ],
+        "max_rows": 1000,
+        "max_bytes": 100000
+      }
+    }
+  },
+  "bindings": []
+}
diff --git a/frontend/e2e/runForm.spec.ts b/frontend/e2e/runForm.spec.ts
new file mode 100644
index 00000000..7a0e4e88
--- /dev/null
+++ b/frontend/e2e/runForm.spec.ts
@@ -0,0 +1,90 @@
+// SPDX-License-Identifier: Apache-2.0
+// Slice 4e-2b in the browser (the run form design §5, §6): the run form against the real stack, behind nginx, under
+// the served CSP, with axe, light and dark, at 1280 and 320 px. A typed start from the Workflows list lands on its
+// run's page; a CSV start from the Runs page is refused by a file with errors, then started from a clean one; an ended
+// run is re-run with its input changed. The workflows are control steps only, run live: nothing leaves the stack (D24).
+import { expect, test } from "./gate";
+import { accessibleBothWays, api } from "./seed";
+
+test.describe.configure({ mode: "serial" });
+
+const RUN_PAGE = /\/t\/[^/]+\/runs\/[0-9a-f-]{36}$/;
+const csvFile = (text: string) => ({ name: "sites.csv", mimeType: "text/csv", buffer: Buffer.from(text) });
+
+test("a typed start from the Workflows list lands on its run's page (the Main and EntryPoints boards)", async ({ page }) => {
+  const seed = await api(page);
+  await seed.publish("runs-check.dewpoint.json", "Form A");
+  await page.goto(`/t/${seed.tenant}/workflows`);
+  await page.getByRole("button", { name: "Start a run of Form A" }).click();
+  const form = page.getByRole("dialog", { name: "Start a run" });
+  await expect(form.getByText(/^Version 1 · published /)).toBeVisible();
+  await expect(form.getByLabel(/^Site/)).toBeFocused();
+  await accessibleBothWays(page, "the run form: live");
+  await form.getByRole("radio", { name: "Simulated" }).click();
+  await expect(form.getByRole("button", { name: "◌ Start the simulation" })).toBeVisible();
+  await accessibleBothWays(page, "the run form: simulated");
+  await form.getByRole("radio", { name: "Live" }).click();
+  await form.getByLabel(/^Site/).fill("HQ Paris");
+  await form.getByRole("button", { name: "Start the live run" }).click();
+  await expect(page).toHaveURL(RUN_PAGE);
+  await expect(page.getByRole("heading", { level: 1, name: "Form A" })).toBeFocused();
+  await accessibleBothWays(page, "a run just started");
+});
+
+test("a CSV start: a file with errors says them at a glance, a clean one starts (the CsvStates board)", async ({ page }) => {
+  const seed = await api(page);
+  await seed.publish("runs-csv.dewpoint.json", "Form B");
+  await page.goto(`/t/${seed.tenant}/runs`);
+  await page.getByRole("button", { name: "Start a run…" }).click();
+  const chooser = page.getByRole("dialog", { name: "Choose a workflow" });
+  await chooser.getByRole("combobox").fill("Form B");
+  await chooser.getByRole("option", { name: "Form B" }).click();
+  const form = page.getByRole("dialog", { name: "Start a run" });
+  await expect(form.getByText("This workflow starts from a CSV file: one run, one pass of its loop per row.")).toBeVisible();
+  await accessibleBothWays(page, "the run form: before a file");
+  await form.getByLabel("Choose a file").setInputFiles(csvFile("Site,VLAN\nParis,10\n,x\n"));
+  await expect(form.getByText("2 errors in 1 of 2 rows")).toBeVisible();
+  await expect(form.getByRole("button", { name: "Start the live run" })).toBeDisabled();
+  await accessibleBothWays(page, "the run form: a file's errors");
+  await form.getByLabel("Choose another file").setInputFiles(csvFile("Site,VLAN\nParis,10\nLyon,20\n"));
+  await expect(form.getByText("All 2 rows pass.")).toBeVisible();
+  await accessibleBothWays(page, "the run form: every row passes");
+  await form.getByLabel(/^Region/).fill("EMEA");
+  await form.getByRole("button", { name: "Start the live run · 2 rows" }).click();
+  await expect(page).toHaveURL(RUN_PAGE);
+  await expect(page.getByRole("heading", { level: 1, name: "Form B" })).toBeFocused();
+});
+
+test("an ended run is re-run with its input changed (the Rerun board)", async ({ page }) => {
+  const seed = await api(page);
+  const check = await seed.publish("runs-check.dewpoint.json", "Form C");
+  const run = await seed.start(check, { site: "HQ" });
+  await seed.ended(run);
+  await page.goto(`/t/${seed.tenant}/runs/${run}`);
+  await page.getByRole("button", { name: "Re-run…" }).click();
+  const form = page.getByRole("dialog", { name: `Re-run ${run.slice(0, 8)}` });
+  await expect(form.getByText(`It runs version 1, the same version as run ${run.slice(0, 8)}.`)).toBeVisible();
+  await expect(form.getByLabel(/^Site/)).toHaveValue("HQ");
+  await accessibleBothWays(page, "the re-run form");
+  await form.getByLabel(/^Site/).fill("HQ Lyon");
+  await expect(form.getByText("Changed from the original run's input.")).toBeVisible();
+  await form.getByRole("button", { name: "Re-run live" }).click();
+  await expect(page).toHaveURL(RUN_PAGE);
+  await expect(page).not.toHaveURL(new RegExp(`${run}$`));
+  await expect(page.getByRole("heading", { level: 1, name: "Form C" })).toBeFocused();
+});
+
+test("at 320 px the form fills the screen, its buttons stacked (the Narrow320 boards)", async ({ page }) => {
+  const seed = await api(page);
+  const check = await seed.publish("runs-check.dewpoint.json", "Form D");
+  await page.setViewportSize({ width: 320, height: 720 });
+  await page.goto(`/t/${seed.tenant}/runs?workflow=${check}`);
+  await page.getByRole("button", { name: "Start a run…" }).click();
+  const form = page.getByRole("dialog", { name: "Start a run" });
+  await expect(form.getByLabel(/^Site/)).toBeFocused();
+  await accessibleBothWays(page, "the run form, 320 px");
+  await form.getByRole("button", { name: "Close" }).click();
+  await expect(form).toHaveCount(0);
+  await expect(page.getByRole("button", { name: "Start a run…" })).toBeFocused(); // back to its opener
+  await page.setViewportSize({ width: 1280, height: 720 });
+});
diff --git a/frontend/e2e/runs.spec.ts b/frontend/e2e/runs.spec.ts
index 63202aec..3fc9e01b 100644
--- a/frontend/e2e/runs.spec.ts
+++ b/frontend/e2e/runs.spec.ts
@@ -4,66 +4,12 @@
 // seeded through the API: workflows of control steps only, run live (nothing leaves the stack, D24) and simulated, one
 // failing at a `fail` step, a loop, and a run held by a delay to be cancelled. The gate fails any request to another
 // origin.
-import { readFileSync } from "node:fs";
 import type { Page } from "@playwright/test";
-import { expect, expectAccessible, test } from "./gate";
+import { expect, test } from "./gate";
+import { accessibleBothWays, api } from "./seed";
 
 test.describe.configure({ mode: "serial" });
 
-const ENDED = new Set(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);
-
-async function tenantId(page: Page): Promise<string> {
-  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
-  return tenants[0]!.id;
-}
-
-/** The API as the web client calls it: an unsafe request names the client and carries the session's CSRF token.
- * Publishing names the draft's revision it publishes (`If-Match`, as the editor does); a start, its idempotency key. */
-async function api(page: Page) {
-  const tenant = await tenantId(page);
-  const { csrf_token } = (await (await page.request.get("/api/v1/auth/session")).json()) as { csrf_token: string };
-  const headers = { "X-Dewpoint-Client": "web", "X-CSRF-Token": csrf_token };
-  const post = async (path: string, data: unknown, more: Record<string, string> = {}) => {
-    const answer = await page.request.post(`/api/v1/t/${tenant}${path}`, { data, headers: { ...headers, ...more } });
-    expect(answer.ok(), `POST ${path}: ${answer.status()}`).toBe(true);
-    return (await answer.json()) as Record<string, unknown>;
-  };
-  return {
-    tenant,
-    /** A fixture imported under `name` and published: its workflow's id. */
-    async publish(fixture: string, name: string): Promise<string> {
-      const document = JSON.parse(readFileSync(`e2e/fixtures/${fixture}`, "utf8")) as unknown;
-      const workflow = await post("/workflows/import", { name, document });
-      await post(`/workflows/${String(workflow.id)}/publish`, { expected_latest_version: null }, { "If-Match": String(workflow.draft_revision) });
-      return String(workflow.id);
-    },
-    /** A run started by hand: its id. */
-    async start(workflowId: string, input: Record<string, unknown>, mode: "live" | "simulate" = "live"): Promise<string> {
-      return String((await post(`/workflows/${workflowId}/runs`, { input, mode }, { "Idempotency-Key": crypto.randomUUID() })).id);
-    },
-    /** Waits for a run to end, as the dispatcher and the worker run it. */
-    async ended(runId: string): Promise<void> {
-      await expect
-        .poll(async () => ENDED.has(((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status), { timeout: 60_000 })
-        .toBe(true);
-    },
-    /** Waits for a run to be running. */
-    async running(runId: string): Promise<void> {
-      await expect
-        .poll(async () => ((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status, { timeout: 60_000 })
-        .toBe("running");
-    },
-  };
-}
-
-/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
-async function accessibleBothWays(page: Page, screen: string): Promise<void> {
-  await expectAccessible(page, `${screen}, light`);
-  await page.emulateMedia({ colorScheme: "dark" });
-  await expectAccessible(page, `${screen}, dark`);
-  await page.emulateMedia({ colorScheme: "light" });
-}
-
 const tags = (page: Page, key: string) => page.getByRole("list", { name: `${key}: result` });
 
 test("the Runs page lists runs, filters them in its address, and says when none match (the Main and ListStates boards)", async ({ page }) => {
diff --git a/frontend/e2e/seed.ts b/frontend/e2e/seed.ts
new file mode 100644
index 00000000..ded8d8c7
--- /dev/null
+++ b/frontend/e2e/seed.ts
@@ -0,0 +1,60 @@
+// SPDX-License-Identifier: Apache-2.0
+// Seeding the browser gate's runs through the API (editor 4e-1b; shared with 4e-2b's run form): workflows imported and
+// published, runs started and waited for, as the web client calls the API. Screens are checked light and dark.
+import { readFileSync } from "node:fs";
+import type { Page } from "@playwright/test";
+import { expect, expectAccessible } from "./gate";
+
+const ENDED = new Set(["succeeded", "failed", "cancelled", "deadline_exceeded", "refused", "dead"]);
+
+async function tenantId(page: Page): Promise<string> {
+  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
+  return tenants[0]!.id;
+}
+
+/** The API as the web client calls it: an unsafe request names the client and carries the session's CSRF token.
+ * Publishing names the draft's revision it publishes (`If-Match`, as the editor does); a start, its idempotency key. */
+export async function api(page: Page) {
+  const tenant = await tenantId(page);
+  const { csrf_token } = (await (await page.request.get("/api/v1/auth/session")).json()) as { csrf_token: string };
+  const headers = { "X-Dewpoint-Client": "web", "X-CSRF-Token": csrf_token };
+  const post = async (path: string, data: unknown, more: Record<string, string> = {}) => {
+    const answer = await page.request.post(`/api/v1/t/${tenant}${path}`, { data, headers: { ...headers, ...more } });
+    expect(answer.ok(), `POST ${path}: ${answer.status()}`).toBe(true);
+    return (await answer.json()) as Record<string, unknown>;
+  };
+  return {
+    tenant,
+    /** A fixture imported under `name` and published: its workflow's id. */
+    async publish(fixture: string, name: string): Promise<string> {
+      const document = JSON.parse(readFileSync(`e2e/fixtures/${fixture}`, "utf8")) as unknown;
+      const workflow = await post("/workflows/import", { name, document });
+      await post(`/workflows/${String(workflow.id)}/publish`, { expected_latest_version: null }, { "If-Match": String(workflow.draft_revision) });
+      return String(workflow.id);
+    },
+    /** A run started by hand: its id. */
+    async start(workflowId: string, input: Record<string, unknown>, mode: "live" | "simulate" = "live"): Promise<string> {
+      return String((await post(`/workflows/${workflowId}/runs`, { input, mode }, { "Idempotency-Key": crypto.randomUUID() })).id);
+    },
+    /** Waits for a run to end, as the dispatcher and the worker run it. */
+    async ended(runId: string): Promise<void> {
+      await expect
+        .poll(async () => ENDED.has(((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status), { timeout: 60_000 })
+        .toBe(true);
+    },
+    /** Waits for a run to be running. */
+    async running(runId: string): Promise<void> {
+      await expect
+        .poll(async () => ((await (await page.request.get(`/api/v1/t/${tenant}/runs/${runId}`)).json()) as { status: string }).status, { timeout: 60_000 })
+        .toBe("running");
+    },
+  };
+}
+
+/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
+export async function accessibleBothWays(page: Page, screen: string): Promise<void> {
+  await expectAccessible(page, `${screen}, light`);
+  await page.emulateMedia({ colorScheme: "dark" });
+  await expectAccessible(page, `${screen}, dark`);
+  await page.emulateMedia({ colorScheme: "light" });
+}
diff --git a/frontend/playwright.config.ts b/frontend/playwright.config.ts
index d339c003..3f47210e 100644
--- a/frontend/playwright.config.ts
+++ b/frontend/playwright.config.ts
@@ -7,7 +7,7 @@ export default defineConfig({
     { name: "foundations", testMatch: /(foundations|gate)\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
     {
       name: "workflows",
-      testMatch: /(workflows|triggers|simulation|runs)\.spec\.ts/,
+      testMatch: /(workflows|triggers|simulation|runs|runForm)\.spec\.ts/,
       dependencies: ["foundations"],
       use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
     },
```

- [ ] **Step 2: Type check and lint them**

Run: the two of "How to run things". Expected: no output (the type check covers `e2e/`, and ESLint lints it).

- [ ] **Step 3: Run them in the browser**

They need the Compose stack, with its dispatcher and worker, as CI's e2e job brings it up (`deploy/compose`, the
development override, a generated `.env` that's never printed, `dewpoint admin init`). Locally, building it takes long:
ask the owner first. Then, from `$WT/frontend`: `npx --offline pnpm@12.6.0 exec playwright test` (the foundations
project signs the admin in first).
Expected: every spec passes, the four of `runForm.spec.ts` and the five of `runs.spec.ts` (which now import their
seeding) among them. A failure is read and fixed test-first. If the owner prefers, the specs run in CI's e2e job on the
PR instead, and the summary says they weren't run locally.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e frontend/playwright.config.ts
git commit -m "test(e2e): the run form in the browser, light and dark, at 1280 and 320 px (4e-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Every check, the ledger, the final checkpoint

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`

- [ ] **Step 1: Every check, and CodeQL**

From `$WT/frontend`:
- `npx --offline pnpm@12.6.0 exec vitest run`: the whole suite (about a minute);
- `npx --offline pnpm@12.6.0 exec eslint .`; `npx --offline pnpm@12.6.0 build` (the type check, then Vite);
- `npx --offline pnpm@12.6.0 check:api`: the API's schema, unchanged since 4e-2a;
- local CodeQL on the head (CI's javascript-typescript analysis on a `git archive` of it): no alert.

Expected, as on the plan's own check (at the top): the suite, 1411 passed in 104 files (main has 1328 in 99); ESLint and
the type check silent; the build done, the entry 649.7 kB, the form's chunk 47.7 kB, the editor's script 146.6 kB, a
run's page 19.5 kB and the Runs page 11.7 kB (ruling 30); `check:api` passes; CodeQL, no finding.

A failure is read and fixed test-first, or reported as it is: never a claim that every check passes when one didn't.

- [ ] **Step 2: The ledger**

Append `### 4e-2b, milestone 4 and the final checkpoint (<date>)`: the tasks' commits, each check's result as run (the
suite's counts), whether the e2e specs ran locally or wait for CI, every mid-slice ruling, anything deferred. Commit it
(`docs(editor-4): 4e-2b final checkpoint`), with the trailer.

- [ ] **Step 3: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch:
- against this plan (its Review Focus first) and the spec's §5 and §6, with the boards;
- with the ledger's rulings in view.

Critical and important findings are fixed test-first, once; minor ones are listed. Then **stop**. The summary to the
owner lists the commits, the checks as run, the rulings made mid-slice, the review's findings and what was deferred.
Nothing is pushed and no PR is opened without the owner's word.
