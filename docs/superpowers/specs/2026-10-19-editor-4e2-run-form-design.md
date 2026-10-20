# Editor UI 4e-2: starting a run, a CSV file, and re-run (design)

Status: the design for the owner's review, 2026-10-19. The D8 mockups were signed off at canvas version 6 ("signed
off, write the spec"); later versions bring their words in line with what the backend allows (§3.2, §8). Base:
`origin/main` 00cbbad9 (ENGINE_ABI 11; migrations to 0073).

Sources:
- the editor outline (`docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`: §2 "4e — runs"; §5 B11 and B14;
  D3, D12, D13);
- the editor ledger (`docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`);
- the 4e-1 design (`docs/superpowers/specs/2026-10-15-editor-4e1-runs-design.md`: §4.3 a run's facts, `rerun_of`;
  §5.3 a run's page; §5.5 words);
- the 4d-1 design (`docs/superpowers/specs/2026-10-13-editor-4d1-simulation-design.md`: §7.1 the Simulate dialog's
  input);
- the engine 2b spec (§7.7, re-run; §8.1, a CSV start; §10.1, retention).

The mockups are the Design canvas "4e-2 Run Form Mockups", version 10. It has seven boards: Main, EntryPoints,
CsvStates, Rerun and MoreStates, each in light and dark, and two true 320 px boards.

## 1. What 4e-2 is

- **The run form.** One dialog starts a workflow's published version, live or simulated. Its input is typed fields,
  or, for a workflow that declares a CSV, a file plus any other fields. It names the version that will run and sends
  it, so a publish meanwhile can't change what runs (D13).
- **A CSV file.** The form uploads it, maps the workflow's columns to the file's, and shows the errors at a glance:
  counted by column and problem, every error, with the first 100 row by row. A run starts only when every row passes.
- **Re-run.** The same dialog, opened from a run's page, prefilled with the original input. Left untouched, the
  original goes back whole; changed, it goes as new input.
- **Where it opens:** the Workflows list, the Runs page, a run's page (Re-run), and the editor.
- **After Start,** the person lands on the new run's page.

Out of scope:
- skipping invalid rows (§3.1, answer 4: the UI never sends `skip_invalid`);
- a CSV workflow started without a file (the backend refuses it, §3.2);
- editing a CSV's cells in the browser;
- starting a draft (Simulate does that, 4d-1) or one step;
- schedules and webhooks (4c-3), approvals (slice 5).

## 2. Two plans, one design

| Plan | Contents | ABI | Migration |
|---|---|---|---|
| 4e-2a, backend | B14, the version check; the start form names its version; B11, a file checked again under other columns; every error counted by column and problem; a same-rows re-run keeps its rows' record (§4) | none | none |
| 4e-2b, UI | the screens of §5, built against the signed-off boards | none | none |

Each plan has its own branch and PR (D26). 4e-2b needs 4e-2a merged.

## 3. The owner's answers

### 3.1 During the design (2026-10-19)

1. **Who starts a run: both** the builder, from the editor, and an operator, from the Workflows list or the Runs page.
2. **A CSV row is one turn of the workflow's main loop.** A file holds a few rows to thousands (the platform's caps:
   10,000 rows, 5 MB; a declaration may lower them).
3. **The form gives a quick view of the CSV's validation errors.**
4. **A CSV start goes ahead only when every row passes.** The outline's "skip invalid → Start run for N rows" is
   dropped.
5. **In the editor, Start warns when the draft differs** from the published version; the run uses the published one.
6. **Re-run: the same input, or a changed one,** the original prefilled.
7. **A changed re-run input asks for its sensitive values again.** No backend work: untouched, the original goes back
   whole, its sensitive values included.
8. **After Start, the new run's page.**
9. **The boards are signed off** ("looks good" on round 1; "signed off, write the spec" on version 6).
10. **A same-rows re-run keeps the original's other fields, read-only, with no backend work** ("read-only, no backend
    work"). The server can't take the original's rows with changed fields; changing them means another file.

### 3.2 Corrections after sign-off (canvas versions 7 and 8)

- **A workflow that declares a CSV starts only with one** (`StartIn`: "a workflow that declares a CSV starts only with
  one", §8.1). Version 6's "Fill in the fields / From a CSV file" choice can't be: it's removed. Main now shows a
  workflow of typed fields; a CSV workflow's form shows its file, and any other fields beside it.
- **A CSV run keeps no file name** (an upload is a raw `text/csv` body). The re-run says "The same rows: 2,431 rows,
  as run 77e0b9d2 read them".

## 4. Backend (4e-2a)

### 4.1 Starting on the confirmed version (B14)

As the outline's B14 has it:
- `StartIn` and `RerunIn` gain `expected_version_id: uuid | null`.
- It's checked in `_frozen`, after `lock_for_admission` and before the version is read for anything else. When it's
  given and isn't the workflow's active version, nothing is admitted: `409` with
  `{"error": "version_changed", "active_version_id", "active_version_number"}`.
- Exact retries are resolved by their key first (`_by_key` → `_retry`), so they return their request whatever is
  active now.
- The request digest stores no format version, so `canonical()` adds `expected_version_id` as a fifth key only when
  it's given. Every existing digest, and every request without it, keeps its exact bytes, as a CSV start's `csv`
  already does. With it, the same key and another version is `idempotency_conflict`.
- A request without it behaves as today.

### 4.2 The start form names its version

`GET /t/{tid}/workflows/{wid}/start-form` gains `version_number`, `published_at` and `published_by` (the publisher's
email, or null when the user is gone), so the form can say "Version 7 · published today 09:12 by Nadia Martin" in one
read. The builder may instead read the version the run's page already reads; either way, one read.

### 4.3 A file checked again under other columns (B11)

`POST /t/{tid}/workflows/{wid}/csv-uploads/{upload_id}/preview`, body `{"mapping": {...}}`:
- `run.start`; the uploader's own staged upload only (anyone else's is `404 upload_not_found`, as at start);
- `410 upload_expired` past its hour; `409 upload_consumed` once a start used it;
- checked against the workflow's active version's declaration: `409 not_active` or `409 csv_not_declared` as the
  upload route answers;
- read inside one of the process's CSV slots, `503 csv_busy` when every slot is held, as the upload;
- the staged file is decrypted, read as at upload (`read_table`), and described under the new mapping
  (`described`): the same fields the upload answers, without `upload_id`, `expires_at`, `headers`, `row_count` and
  `default_mapping`, which don't change;
- nothing is logged or audited, as at upload.

The outline's other half of B11, reading the saved default mapping, isn't needed: the upload already proposes it
(`default_mapping`, stale or not).

The upload's answer and the preview's both gain `version_id`: the active version whose declaration they checked
against, so the form can tell when a publish came between its start form and the file (§5.3).

### 4.4 Every error counted by column and problem

The upload's answer and the preview's gain:
- `error_groups`: one entry per `(column, code)` over every error, not only the 100 listed:
  `{"column": <declared name> | null, "code", "count", "rows": [the first 5 record numbers]}`, ordered by count, then
  column, then code. `column` is null for a record as a whole (`cell_count`).
- `rows_with_errors`: how many records broke a rule (`len(Built.skipped)`).

`build_rows` counts them as it goes. What it keeps stays bounded by the columns and the codes (at most 200 columns,
10 codes), never by the records.

### 4.5 A same-rows re-run keeps its rows' record

Today a re-run that sends no `input` and no `csv` rebuilds its original's rows but writes no CSV record
(`_frozen` returns before `write_csv_record`), so its page shows nothing of its rows, and a re-run of it can't tell it
was a CSV run (the ledger's 4e-1a I1 left this to 4e-2). Admission now copies the original's CSV record (`mapping`,
`headers`, `row_count`, `skipped`, `errors`, `error_count`) to the new request when it rebuilds the original's rows:
they're the same rows. Its audit entry says so as a CSV start's does.

### 4.6 Permissions, retention, erasure

Nothing new:
- `run.start` (operator and up): the start form, an upload, a preview, a start, a re-run;
- `trigger.manage` (editor and up): saving the default mapping (`PUT …/csv-mapping`);
- a re-run's original input past retention: `410 input_not_retained`; a draft simulation's re-run: `draft_run`;
- an erasing tenant's key: `503 key_unusable`, as 4e-1 words it.

## 5. The UI (4e-2b), per the signed-off boards

### 5.1 Where it opens (board EntryPoints)

- **The Workflows list:** a "Start…" button on each row that can start: published (an active version), enabled,
  executable, for a role with `run.start`. Named "Start a run of <workflow>".
- **The Runs page:** "Start a run…" beside the heading. The form asks for the workflow first: a chooser of the
  workflows that can start, as the Runs page's Workflow filter chooses one (the same native dialog around cmdk). A set
  Workflow filter chooses it already.
- **A run's page:** "Re-run…" in the bar once the run has ended or never started, for a role with `run.start`; never
  on a draft simulation, whose bar keeps "Open in the editor", nor on a sub-run (§5.4). While a run is going, the bar
  shows Cancel instead.
- **The editor:** "Start a run…" beside Simulate, when the workflow is published. Simulate runs the draft; Start a
  run… runs the published version.

### 5.2 The form (boards Main, MoreStates)

- A modal dialog, 600 px wide, in the Simulate dialog's look (4d-1c); below 640 px it fills the screen (§5.6).
- Its heading is "Start a run", or "Re-run <first 8 of the id>"; under it, the workflow's name.
- **Version:** "7 · published today 09:12 by Nadia Martin", from the start form (§4.2).
- **The draft differs:** opened from the editor when the workflow has `unpublished_changes`, a note says "The draft
  has changes that aren't published. This run uses version 7, not the draft."
- **Mode:** Live (the default) or Simulated, as radio buttons. Live shows the orange banner ("Live. It acts for real:
  its steps call their connections, and what they change in Mist stays changed."); Simulated, the slate hatched one
  ("Simulated. Nothing is sent: actions return fixtures instead of calling out. Results don't prove the live call will
  succeed."). The submit button follows: "Start the live run" in an orange outline (D12), or "◌ Start the simulation"
  in slate.
- **Typed fields** come from the start form's `fields`, entered as the Simulate dialog enters them (`startInput`'s
  controls, Edit as JSON included). A sensitive field is a password input.
- **Start** sends the start with:
  - `expected_version_id`: the start form's `version_id`;
  - an `Idempotency-Key`: one per submitted form, reused when the same submission is sent again after a network
    failure, never across a changed form.
- **On `202`:** the dialog closes and the person lands on the new run's page, its heading focused. It says "Waiting to
  start" until the dispatcher starts it, then reads it as any running run (4e-1 §5.3).
- **Refusals** keep the form open with the server's words, nothing started:
  - `409 version_changed`: the form reads the start form again and keeps each value whose field still exists with the
    same type: "Version 13 was published while this was open. Nothing started. The form now shows version 13's
    input, with your values kept where they still fit: check them and start again."
  - `409 not_active`, `workflow_disabled`, `version_unusable`, `node_type_retired`, `cel_profile_retired`,
    `no_current_build`, `production_runs_disabled`: the code and its message, as 4e-1's vocabulary words them.
  - `422 input_invalid`: each reason beside its field where its path names one, else listed above the footer.
  - `403`, `503 key_unusable`: as 4e-1 words them.

### 5.3 A CSV file (board CsvStates, MoreStates)

For a workflow whose start form has `csv`:
- **Before a file:** "This workflow starts from a CSV file: one run, one pass of its loop per row." Then a drop zone
  with "Choose a file" (`.csv`, `text/csv`), its limits from the declaration ("Up to 10,000 rows and 5 MB · comma,
  semicolon or tab separated · UTF-8"), and "The columns it reads": each declared column's header, name, type in words
  and `required`.
- **Reading:** the file is uploaded as it is (`POST …/csv-uploads`, `text/csv`). "Reading the file…" while it goes.
  The file's name is the browser's; the server never keeps it.
- **A file that can't be read** says why, beside its code, and asks for another file:
  - `csv_encoding` "isn't UTF-8 text"; `csv_empty` "has no header or rows"; `csv_duplicate_header` "has two columns
    with the same name" (the server names no header: a file's text is never in an answer); `csv_malformed` "has a
    quote that isn't closed, or a cell split across lines"; `csv_too_many_rows` "has more than 10,000 rows, this
    workflow's limit";
  - `413 too_large` "is over 5 MB, this workflow's limit"; `503 csv_busy` "The server is busy reading other files.
    Nothing was kept. Choose the file again in a moment."
- **Columns:** a table of each declared column (its name, `required`) and a select of the file's headers ("Not used"
  for an optional column), with how it was proposed: "saved", "same name" or "left out".
  - A saved mapping that no longer fits says so ("The columns saved for this workflow no longer fit version 7: …
    The file's columns with the same names are proposed instead; check them.").
  - A required column without one is marked on its select ("Required: choose the file's column for it."), and no row
    is checked until every required column is mapped.
  - Changing a column checks every row again (§4.3): "Checking every row again with these columns…".
  - "Save these columns for this workflow's next CSV", for a role with `trigger.manage` only. It's saved when Start is
    pressed, before the start is sent; if saving fails, the form says so and nothing starts.
- **The errors at a glance:** "37 errors in 29 of 2,431 rows" (`error_count`, `rows_with_errors`, `row_count`), "The
  run can't start until every row passes. Fix the file, then choose it again.", then a table of `error_groups`:
  column, problem, and its count with its first row numbers ("21 · 7, 19, 33, 48, 52 and 16 more"). Below, "Every
  error, row by row (37)" opens the listed errors. Above 100 errors: "Above 100 errors, the first 100 are listed row
  by row; the counts above are of every error."
- **Problems in words:** `required` "Missing: a value is required"; `cell_count` "Has more or fewer cells than the
  header"; `not_integer` "Not a whole number"; `out_of_range` "Out of range"; `not_number` "Not a number";
  `not_boolean` "Not true or false (true, yes, 1; false, no, 0)"; `not_mac` "Not a MAC address"; `not_ip` "Not an IP
  address"; `not_cidr` "Not a network in CIDR form"; `not_in_enum` "Not one of the allowed values".
- **Every row passes:** "All 2,431 rows pass.", then "The file's first 5 rows, under these columns" (the preview: the
  file's cells as written, before conversion; a sensitive column is never shown, and the form says so). The columns
  fold to one line with Change.
- **A publish meanwhile:** when an upload's or a preview's `version_id` isn't the form's, the form reads the start
  form again, says so as a `409 version_changed` does (§5.2), keeps the staged file and each column's choice whose
  column still exists, and checks the file again (§4.3). After a `409 version_changed` at Start the same happens: the
  upload wasn't consumed.
- **Start** is disabled while a file is missing, a column is unmapped or any row fails, with its reason beside it
  ("Every row must pass first."). Enabled, it says how many rows ("Start the live run · 2,431 rows") and sends `csv`:
  `{upload_id, mapping}`, never `skip_invalid`; the other typed fields go in `input` beside it.
- **The upload's hour:** `410 upload_expired` at Start: "The file was kept for an hour, and that hour has passed:
  choose it again." `409 upload_consumed` (a start already used it): "This file already started a run: choose it
  again to start another."

### 5.4 Re-run (board Rerun, MoreStates)

- It reads the original's input (`GET …/runs/{id}/input`) and the active version's start form.
- **Version:** "It runs version 12, the one published now. Run 4a2b17e0 ran version 11.", or "It runs version 7, the
  same version as run 77e0b9d2." It sends `expected_version_id` as a start does.
- **Mode:** the original's, preselected.
- **Typed input, `read_back: kept`:** "The original run's input. Change what you need." Each field is prefilled from
  the original where a field of the same name exists. A field whose value read back redacted shows "Kept from the
  original run": a field marked sensitive, and any other whose value is, or holds, the read-back's `[redacted]` marker
  (a claimed value: undeclared, over 64 KiB, or a nested sensitive property).
  - Untouched, the re-run sends no `input`: the server rebuilds the original whole, its protected values included.
  - Once any field changes, the input goes whole as new: each of those fields becomes empty and required, a password
    input where it's sensitive ("Enter it again: a changed input is sent whole, and the original's protected values
    never reach this form."). Edit as JSON refuses a value that still holds the marker. The marker is never sent.
- **A CSV run** (the original has a CSV record, `RunOut.csv`, §4.5): "The same rows: 2,431 rows, as run 77e0b9d2
  read them" (no `input`, no `csv`), or "Another file", which opens §5.3's flow and sends `csv` with the other
  fields. Under "The same rows", the workflow's other fields show the original's values read-only (a redacted one as
  "Kept from the original run"), with "To change them, choose another file." (§3.1, answer 10). Under "Another file"
  they're editable, prefilled as for a typed re-run, with the same rule for redacted values.
- **The original and the active version disagree about a CSV:** when the active version declares one and the original
  has no rows, only "Another file"; when it declares none and the original had rows, the fields start empty, as for
  `absent`, and a note says "Version 12 doesn't read a CSV file: fill in its fields."
- **`read_back: absent`:** "Run 1e8a3f27's input isn't kept, so it can't be sent again. Fill in the fields to run it
  again." The fields start empty. (Retention, a refused request and a run from before 2b-2 all read back `absent`: the
  words name none of them.)
- **No Re-run on a sub-run** (`RunOut.parent` set): a sub-run has no request of its own, and a re-run would start its
  workflow at the top level. Its bar keeps the link to its parent run.
- **`read_back: unreadable`:** the 4e-1 words for `key_unusable`; Re-run stays possible with new input.
- The submit is "Re-run live" or "◌ Re-run as a simulation", with the row count for a CSV run.
- `410 input_not_retained` at submit (retention passed meanwhile) turns the form into the `absent` state.
- **On `202`:** the new run's page, its trigger "Re-run of 4a2b17e0" (4e-1 §4.3).

### 5.5 Words

Live and simulated wording, the refusals' and the CSV codes' are in §5.2–§5.4. Run statuses and refusal codes come
from 4e-1's vocabulary (`lib/runStatus.ts`), extended with `version_changed`, `upload_expired`, `upload_consumed`,
`csv_busy` and the file codes. "Start a run…" and "Re-run…" end with an ellipsis: they open a dialog.

### 5.6 Accessibility, 320 px

- WCAG 2.2 AA, light and dark, at 1280 and 320 px. Targets are at least 24 px (2.5.8).
- The dialog is a native modal `<dialog>`: focus goes to its first field, Escape and Cancel close it, focus returns to
  the button that opened it.
- Below 640 px the dialog fills the screen: its fields 44 px tall, its buttons stacked full width, Start first. The
  errors' table becomes one item per problem (Narrow boards).
- Reading, checking and the errors' count are announced through one persistent status region. A refusal is an alert.
- A disabled Start names its reason through `aria-describedby`.

## 6. Testing

- **4e-2a:**
  - B14: a start and a re-run with the active version, with another (`409 version_changed`, nothing admitted,
    nothing claimed), and without it; an exact retry after a publish returns its request; the digest's bytes unchanged
    without the field (an existing request's retry still matches); the same key with another expected version is
    `idempotency_conflict`.
  - B11: a preview under a new mapping; a required column unmapped; another user's upload; an expired and a consumed
    upload; a busy slot; a declaration changed since the upload; nothing logged or audited.
  - The error groups: every `(column, code)` counted across more than 100 errors; `column: null` for `cell_count`;
    the order; a work-unit test that what's kept stays bounded at 10,000 records × 200 columns.
  - The start form's version fields, a publisher who's gone; the upload's and the preview's `version_id`.
  - §4.5: a same-rows re-run's CSV record equals its original's, and a re-run of that re-run finds it; a re-run with
    new input or another file writes its own, as today.
  - The role × endpoint matrix for the new route and fields.
- **4e-2b:**
  - unit tests per surface, against typed fakes: each entry point and who sees it; the version note; live and
    simulated; each refusal; the key reused only on a resend; the CSV states; the groups and the listed errors; the
    disabled Start's reasons; the save checkbox's role; a publish between the start form and the file; re-run
    untouched and changed, the `[redacted]` marker never sent (a sensitive field, an undeclared value, a nested one,
    Edit as JSON), a CSV re-run, the original and the active version disagreeing about a CSV, `absent`,
    `unreadable`, a draft simulation and a sub-run without Re-run.
  - The Playwright gate (CSP, console, axe), light and dark at 1280 and 320 px, on the Compose stack: a typed start
    landing on its run's page, a CSV start with errors and then a clean file, a re-run. The seeded workflows are
    control steps only, run live (nothing leaves the stack, D24) and simulated.

## 7. Risks

- **The digest's bytes.** B14 must not change an existing request's digest: an exact retry from before the deploy would
  turn into `idempotency_conflict`. The tests pin both.
- **A big file checked again on every column change.** Each preview decrypts and reads up to 5 MB inside a CSV slot.
  The form sends one preview at a time and only the last change's.
- **A re-run's untouched input on a newer version** may no longer fit it: the server refuses it (`422`), and the
  form shows the reasons beside the fields.
- **The save checkbox saves before the start:** a start then refused leaves the columns saved. They fit the version
  (the server checks them), so a later upload proposes them.

## 8. Calls I made, for the owner to check

1. **The form is a modal dialog** in the Simulate dialog's look, 600 px wide, full screen at 320 px.
2. **The Mode choice is in the form**, Live by default; a re-run preselects the original's.
3. **Every error is counted by column and problem on the server** (§4.4), so the grouped view is right above 100
   errors. It's a small backend addition.
4. **Start… appears only where a start can go ahead:** published, enabled, executable, and the role holds `run.start`.
5. **The saved columns are written when Start is pressed, before the start**; a failed save stops the start.
6. **After a `409 version_changed`, the form keeps the values that still fit** (same name, same type) and asks again.
7. **The start form names its version** (§4.2), one read for the form's version line.
8. **"Read the saved default mapping" (B11's first half) is dropped:** the upload already proposes it.
9. **A changed re-run empties every field that read back redacted,** not only those marked sensitive (§5.4): the
   `[redacted]` marker is never sent as input.
10. **A same-rows re-run copies its original's CSV record** (§4.5): its page shows its rows, and a re-run of it knows
    them. A small backend addition.
11. **The upload and the preview say which version they checked** (§4.3); a publish meanwhile keeps the staged file
    and checks it again (§5.3).
12. **A duplicate header isn't named** ("has two columns with the same name"), and **the preview is the file's cells
    as written** ("The file's first 5 rows, under these columns"): both as the API answers today.
13. **No Re-run on a sub-run; `absent` names no reason** (§5.4).
