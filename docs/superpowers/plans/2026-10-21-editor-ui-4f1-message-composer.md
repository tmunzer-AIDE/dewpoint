# Editor UI 4f-1: the message composer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1, 2026-10-21.** Nothing is built before the owner accepts this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat.

**Goal:** The message composer of the message composer design §5, against the signed-off D8 boards: the eight steps
built on the SDK's message written in one place on Setup (severity, title, text on several lines, fields, links), with
values from earlier steps, a preview of how Slack, Teams or Google Chat will lay it out, what each would cut said
before the step runs, at 1280 and 320 px.

**Architecture:**
- **The plugins say which steps get the composer:** the SDK's `Message` carries `x-widget: "message"` at its schema's
  root, a display annotation outside the contract hash (§4.1).
- **The previews are rendered in the browser:** `lib/messages.ts` mirrors the Slack, Teams and Google Chat renderers
  and the SDK's `cut`, held to the plugins' own output by shared cases (`src/test/messageCases.json`), which a backend
  command writes and a backend test checks (§4.2).
- **The composer is the drawer's own fields:** `MessageComposer` lays the message's parts out in a "Message"
  fieldset, each a `FieldView` told how to draw it (`drawn`: the severity's four choices, the text on several lines,
  the fields' and links' rows, the link check, the warnings); what's typed, held, refused or computed by a formula
  behaves as everywhere in the drawer. `StepDrawer` puts it on Setup (`settingsOf`).
- **What a preview knows** lives in `lib/composer.ts`: the target a step sends to, the message with a placeholder for
  each value (`draftOf`), what the target would cut (`cutWords`, `slackCount`), a simulated step's cut in words.
- **Text on several lines** is the pill editor's rows (`linesOf`), never `contenteditable`; the shared writer
  (`valueOf`) splits a run of text longer than the engine's 4,096 characters.

**Tech Stack:** Python 3.12, pydantic 2.13.5, Typer (the backend's two tasks); React 19, TanStack Query 5, Tailwind v4
tokens; Vitest and Testing Library (no jest-dom); Playwright against the Compose stack, with axe.

**Spec:** `docs/superpowers/specs/2026-10-20-editor-4f1-message-composer-design.md` (committed d5dc43e8 on
`docs/editor-ui-4f1-spec`): §4 (the backend), §5 (the UI), §6 (the tests), §7 (the risks), §8 (the calls). The boards:
"4f-1 Message Composer Mockups" v9 (Main, Previews, States, OtherSteps, MainDark, MoreStates, Narrow320Light,
Narrow320Dark), signed off.

## How this plan was checked

The plan's code was checked before review on a scratch checkout of main at b9549821, never on a branch. Each
task's diffs were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff (and, in Task 3, the cases file its command writes) and the same tests: they passed;
- after every task, its side's static checks: the type check (`tsc -b --noEmit`) and ESLint, or ruff, the format
  check and mypy: silent;
- after the last, the tree matched the prototype the diffs were cut from, file for file (tree f8c1da4f), the cases
  file the command wrote included;
- the 19 diff blocks, taken from this file's own text, are the diffs applied, byte for byte, in order;
- on the final tree: the whole frontend suite (1496 passed, 108 files; main has 1415 in 104), the build, `check:api`;
  the backend's `tests/plugins`, `tests/engine/graph` and `tests/sdk` (1953 passed); and CodeQL (CLI 2.27.2, CI's
  filter; python-queries 1.8.13, javascript-queries 2.4.8): no finding.

The e2e spec (Task 10) was type-checked and linted, not run: it needs the Compose stack, which Task 10 asks the
owner about. The executor still runs every step: the check is evidence, not a substitute.

## Global Constraints

- **No step changes version.** The hint is a display annotation: the eight contract hashes stay as they are on main
  (pinned in Task 2's test). No route, no migration, no ABI change (§4.3).
- **No new dependency.** No npm or Python package is added; no third-party JavaScript or CDN asset: everything is
  bundled, under the strict CSP, with no inline script or style.
- **No real Mist or SaaS call, no real data (D24).** The shared cases are made-up messages; the unit tests stub
  `fetch`; the browser spec writes a Slack step without a connection and publishes nothing.
- **A warning, never an error.** What a target would cut never blocks: the step publishes, the target shows the start.
- **Words first, the boards' copy.** Where the boards have no words, the rulings below give them.
- **No AI tells.** No left-border accents, halos, tinted icon tiles or eyebrows; the previews use the app's tokens,
  never a target's colours or emoji (`src/test/aiTells.test.ts`).
- **WCAG 2.2 AA**, light and dark, at 1280 and 320 px: the message a fieldset; the severity a radio group; each row's
  controls named by their row; warnings and the link check linked to their control (`aria-describedby`); targets at
  least 24 px, 44 px below 640 px for the composer's own buttons and choices.
- **Verify, don't remember.** Checked in the installed packages: pydantic 2.13.5 puts a model's `json_schema_extra`
  at a subclass's schema root; the registry stores a display-only change in place (`registry.py`); the engine takes
  template text parts in a row (`engine/graph/values.py`, pinned in Task 5); Python's `json.dumps(ensure_ascii=False)`
  and JavaScript's `JSON.stringify` escape the same characters (the byte counts in Task 4's cases).
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker. Nothing is pushed and no PR is opened
  without the owner's OK in chat. Ask before any local run expected over 10 minutes (the e2e spec on a local Compose
  stack).

## Review Focus

The inputs and conditions most likely to bite a person using this that the design implies but its own lists don't
name. Each is pinned by the test named, in the task that owns the code.

1. **A pasted text past 4,096 characters, with a value in it** (a log, a report). Saved as parts the engine takes,
   read back as one text. Task 5: `writes a long text as parts of the engine's 4,096 characters, counted as Python
   counts, read back as one` and `test_a_template_takes_written_parts_in_a_row`.
2. **Characters outside the BMP** (an emoji in a title, a link's label). Counted as Python counts them, never as
   JavaScript's UTF-16 units. Task 4: `counts characters as Python does, a character outside the BMP as one`, and the
   cases' 75-character label.
3. **A list or the severity written by a formula, or as a literal, through the API.** The composer never rewrites it:
   a formula stays one, a literal shows as today's JSON. Task 7: `keeps a list a formula computes as a formula, and
   one it can't draw as today's control`; Task 8: `shows a part a formula computes as computed when the step runs`.
4. **A newline already in a one-line field's value** (written through the API or an import). Shown on its own row and
   kept when typed beside, never stripped by the input. Task 6: `shows a newline already in a one-line field's value
   on its own row, and keeps it`.
5. **The connection types can't be read** (a 500) while the step has no connection. The type is never named by its
   key. Task 9: `never names a connection's type by its key, even when its label can't be read`.

## Rulings (proposed; they join the ledger as 303 onward when the owner accepts the plan)

Each says what was decided, why, and what it costs if wrong. Found while building the prototype the diffs come from.

1. **One plan with milestone pauses** (spec §8, call 7): after Task 3 (the backend), Task 6 (the mirror and the text's
   writing) and Task 9 (the composer, its previews and states); then Tasks 10–11 and a fresh reviewer. Cost: none.
2. **The shared cases** (§4.2): eleven made-up messages, each with Slack's, Teams' and Google Chat's body and cuts;
   one holds a link label of 75 characters outside the BMP, which JavaScript's `length` would count as 150. The
   webhook's body isn't in the file: it posts the model as JSON, there's no renderer to mirror (the file stays at
   251 kB). Written by `dewpoint plugins message-cases`; held by a backend test and a frontend test. Cost: none.
3. **The mirror** (`lib/messages.ts`) returns what the renderer returns, plus, for Teams and Google Chat, the uncut
   body's size in bytes (`size`), which the words need. Characters are counted in code points. Cost: none.
4. **The split at 4,096** (§5.2, call 9) counts code points, as Python does, in the shared writer's template branch
   only: a fixed text without values stays one string, which the engine takes whole. Cost: none.
5. **Every pill editor lays its text out in lines** (`linesOf`): a newline in a one-line field's value shows on its
   own row instead of being stripped by the input; Enter adds a line only where the composer asks (`lines`).
   Backspace at a line's start joins it to the line above; ↑ and ↓ go to the line above or below, as far into its
   first text as the caret was; Home and End to the line's ends, past its pills; ← and → cross a line's end. A later
   line's input is named "Text, line 2". Cost: a one-line field holding a newline shows two rows.
6. **The composer is the drawer's fields** (`FieldView`'s `drawn`): its own control (the severity), its own rows (the
   fields, the links), lines, a check, its hint, no pill note (`quiet`), "(required)" at the top level (`marked`),
   the required words (`missing`), a warning (`warn`), what's under it (`below`). The field frame gains a warning
   note in the warning ink, described by its control. Cost: one optional prop on `FieldView` and `FieldFrame`.
7. **Setup with a message** (§5.1): the step's required fields, each saying "(required)" (no "Each of these is
   required.": Setup holds the message's optional parts too), then Message, then the preview. Options: "The message
   is on Setup; what only <target> takes stays here.", then its fields or "Nothing else to set.". On a run's page,
   Setup shows the composer read only between the step's other fields. A Go to finds a message part on Setup.
   Cost: none.
8. **Targets** by step type, the eight of §1; a third party's message step gets the composer, no preview and no line
   (call 2). Named Slack, Teams, Google Chat, the webhook, email, syslog, PagerDuty, ServiceNow; a third party's
   "this step". Cost: copy.
9. **The title's hint** says what it becomes where it matters: "optional · the email's subject", "optional · the
   alert's summary" (PagerDuty), "optional · the incident's short description" (ServiceNow), else "optional". The
   board drew email's. Cost: copy.
10. **The severity** is a radio group named by its label, focusable from a script (a Go to lands on it); unset, Info
    is chosen and nothing is written. Four in a row from 640 px, two rows of two below. Cost: none.
11. **Rows** (§5.3): each row's label and value (or address) are fields with visible labels, "Field 1 label", "Field
    1 value", "Link 1 label", "Link 1 address" (the board drew bare inputs: a visible label names a control); side by
    side from 640 px, stacked below; Move up, Move down and Remove under the row at every width (the drawer is
    440 px at most), named "Move up: field 1", "Remove field 1"; "2 of 25" above the rows; a new row is `{}`, as a
    list's Add writes today. Cost: copy; a taller row than the board's.
12. **The link check** (§5.3, call 6): an address whose written start isn't `http://` or `https://` says "A link's
    address starts with http:// or https://.", as it's typed (so "h" says it until "http://" is typed); one starting
    with a value, a formula or nothing isn't checked. Cost: the words show while the scheme is typed.
13. **A value in a preview is written `check.site`** (`sourceText`: the step's key, then the path under its output),
    mono, underlined with dots; the composer's pills keep `check › site`. In the webhook's JSON, `{check.site}`, as
    the read-only view writes a template; a list or severity a formula gives whole, "Computed when the step runs"
    unquoted. Cost: copy.
14. **Placeholders** are characters of Unicode's plane-15 private use area, one per value, put in the message the
    mirror renders: no renderer escapes, splits or cuts through one. The cut maths render the message with its values
    left out (§5.2). Cost: none.
15. **What's said where** (§5.5): under Slack's text its count ("118 characters, before its values. Slack shows up to
    3,000.", "before its values" only when it has some), past 3,000 the board's sentence as a warning; under the
    preview each cut with its limit ("Slack will cut field 1's value at 1,993 characters."); Teams' and Google Chat's
    "About 49,000 bytes before its values: Teams takes 24,000. The text would be shortened first, then the fields'
    values." (rounded to the thousand; the parts in the order the levels tighten them; then "3 links would be left
    out."), under the text too when the text would be shortened. A field's or a link's cut is said under the preview
    only. Cost: copy.
16. **The previews draw what the mirror sends, in the app's tokens:** no sender line or time (the board's "Dewpoint
    10:02"), nothing that links or acts (a button is drawn as a label). The boards' "What Slack takes" notes are the
    boards' own. Cost: none.
17. **The text left empty** says "Give the text: a message needs it." under it once it's been touched and emptied, as
    the drawer says "Required" today; the check's own "Needs `text`." stays in the step's problems (the server puts a
    missing property at its parent). Cost: an untouched empty text says it in the step's problems only.
18. **Read only** (a version, a viewer, a run's page): the title and the text as written, "Severity: warning · 2
    fields · 1 link" ("computed when the step runs", "no fields"), and the preview. Cost: none.
19. **No connection yet** (§5.6): today's sentence, the type named by its label from `GET /api/v1/connection-types`,
    read only then; "Loading connections…" while it's read; "No connection of its type yet: an admin adds one." when
    it can't be. The board's disabled select isn't drawn: the `<output>` the field's label names stays (#73).
    Cost: one more read when there's no connection.
20. **Simulate's words** (§5.6): in the result's banner, after "Nothing was sent.": "Slack would cut the text at 3,000
    characters and field 2's value." (a limit only where it's fixed: the text, the title, a label); "Teams would
    shorten the text and link 6 (left out) to fit its 24,000 bytes."; "ServiceNow would cut the title, the
    description and field 1's label.". The target is read from the step summary's `type`. Cost: copy.
21. **The checks:** each task's tests red, then green, with its static checks; on the final tree the frontend suite,
    the backend suites the plan touches (`tests/plugins`, `tests/engine/graph`), ruff, mypy, the build, `check:api`
    and CodeQL. The browser spec runs in CI's e2e job, or locally on the owner's word. Cost: none.

Mid-slice rulings start at M113.

## File structure

| File | Responsibility |
|---|---|
| `backend/src/dewpoint/sdk/messages.py` | the composer's hint on the SDK's message (Task 2) |
| `backend/src/dewpoint/plugins/message_cases.py`, `backend/src/dewpoint/apps/cli/main.py` | the shared cases and the command that writes them (Task 3) |
| `frontend/src/test/messageCases.json` | the shared cases, as the plugins render them (Task 3; never edited by hand) |
| `frontend/src/lib/messages.ts` | Slack's, Teams' and Google Chat's renderers and `cut`, mirrored (Task 4) |
| `frontend/src/lib/pills.ts` | the split at 4,096 (Task 5); text and pills as lines (Task 6) |
| `frontend/src/routes/editor/drawer/TextPills.tsx` | the pill editor in rows, Enter, Backspace and the caret's moves (Task 6) |
| `frontend/src/routes/editor/drawer/FieldView.tsx`, `FieldFrame.tsx` | `drawn`: how the composer draws a part (Tasks 6–9); a warning note (Task 8) |
| `frontend/src/lib/schemaForm.ts` | `settingsOf`: a message's parts together on Setup (Task 7) |
| `frontend/src/lib/composer.ts` | targets, words and the link check (Task 7); the draft, placeholders and cuts (Task 8); the summary and Simulate's words (Task 9) |
| `frontend/src/routes/editor/drawer/MessageComposer.tsx` | the composer: severity, title, text, rows (Task 7); its preview and warnings (Task 8); its states (Task 9); 44 px targets (Task 10) |
| `frontend/src/routes/editor/drawer/MessagePreview.tsx` | Slack's, Teams' and Google Chat's previews, the webhook's JSON, the no-preview lines (Task 8) |
| `frontend/src/routes/editor/drawer/StepDrawer.tsx`, `structured.tsx` | Setup and Options with a message (Task 7) |
| `frontend/src/routes/editor/drawer/pickers.tsx` | a connection's type by its label (Task 9) |
| `frontend/src/routes/editor/simulation/StepResult.tsx` | a simulated message's cut in words (Task 9) |
| `frontend/src/routes/editor/drawer/harness.tsx`, `frontend/src/test/nodeTypes.ts` | test support: the whole drawer; a made-up message step (Task 7) |
| `frontend/e2e/composer.spec.ts`, `e2e/fixtures/message.dewpoint.json`, `playwright.config.ts` | the browser spec (Task 10) |
| `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`, `2026-10-06-plugins-3-ledger.md` | the plan accepted, the 3b-1 sign-off (Task 1); the milestones and the final checkpoint |

## Milestones

1. **Tasks 1–3:** the ledger; the backend: the hint, the shared cases. Pause for the owner's review.
2. **Tasks 4–6:** the mirror held to the cases; long text split; text on several lines. Pause for the owner's review.
3. **Tasks 7–9:** the composer on Setup; its previews and what they'd cut; its other states and Simulate's words.
   Pause for the owner's review.
4. **Tasks 10–11:** the browser spec, every check, the final checkpoint. Then the final review.

## How to run things

Every command runs from the plan's worktree. `$WT` is that worktree's root.

- **The frontend's locked packages.** From `$WT/frontend`, `npx --offline pnpm@12.6.0 install --frozen-lockfile
  --offline` restores them from the local store, the lockfile untouched. It installs packages, so the owner's OK is
  asked at the start.
- **The backend's environment.** `uv sync` may be refused in a new worktree: borrow a venv whose `uv.lock` matches
  main's (`UV_PROJECT_ENVIRONMENT=<its .venv>`), with `UV_FROZEN=1 UV_NO_SYNC=1`. Nothing is installed.
- **Backend tests.** From `$WT/backend`: `UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q <files>`. None of this plan's needs
  the database.
- **Backend static checks.** From `$WT/backend`: `uv run ruff check src tests && uv run ruff format --check src tests
  && uv run mypy src`. Expected: "All checks passed!", "… files already formatted", "Success: no issues found …".
- **Frontend tests.** From `$WT/frontend`: `npx --offline pnpm@12.6.0 exec vitest run <files>`.
- **A diff.** Copy the block, between its fences, to a file in the plan's workspace. Then, from `$WT`:
  `git apply --check <file> && git apply <file>`. Expected: no output. A diff that doesn't apply means the tree
  differs from what the previous task left: stop and compare, never apply by hand.
- **Frontend static checks.** From `$WT/frontend`: `npx --offline pnpm@12.6.0 exec tsc -b --noEmit` and
  `npx --offline pnpm@12.6.0 exec eslint .`. Expected: no output from either.
- **The e2e spec** runs against the Compose stack, as CI's e2e job does. Locally, building the stack takes long: the
  owner is asked first.
- **Local CodeQL**, at the end: CI's analyses (python and javascript-typescript; CLI 2.27.2, CI's query filter) on a
  `git archive` of the head; a few minutes.

## Executing this plan

- **Inline**, by one implementing agent in one session, with the owner's reviews at the milestone pauses, and a fresh
  independent review at the end. Test-first, as each task's steps say. The owner chooses.
- **The branch** is settled with the owner at the start. The default proposed: `feat/editor-4f1` from `origin/main`
  (b9549821, or later), in its own worktree (`~/4_dev/mist_dewpoint-4f1`), with the docs branch
  `docs/editor-ui-4f1-plan` (the spec, then this plan) merged into it first. A later main is merged in, never
  rebased.
- **Where the code base differs from a step**, the executor stops at the diff that doesn't apply, adapts it test-first
  and records the difference as a mid-slice ruling in the ledger (M113 onward).
- **Task 1 runs only once the owner has accepted the plan:** it writes the rulings into the ledger as accepted.

---

# Milestone 1 — The ledger, and the backend

### Task 1: The ledger: 4e-2b merged, 4f split, this plan accepted

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (appended at the end),
  `docs/superpowers/plans/2026-10-06-plugins-3-ledger.md` (the 3b-1 sign-off, at the end of its section)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger section later tasks append to (`### 4f-1, milestone N`).

- [ ] **Step 1: Write the plan's status, and the plugins' sign-off**

Run this task only once the owner has accepted the plan. Apply:

```diff
diff --git a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
index 986e92a8..945d149f 100644
--- a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
+++ b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
@@ -3633,3 +3633,45 @@ What the reviewer set aside, each ruled as it stands: a dropped file of any type
 form's file input (its first field); the editor's leave guard when landing during a save (the editor's own); the
 list's first load carrying the landing (ruling 302's count); a run failing at once focusing its failed step (4e-1's);
 4e-2a's backend behaviours; changing a lone sensitive field through Edit as JSON (ruling 297).
+
+### 4e-2b merged; 4f split in three; the 4f-1 design and plan accepted (2026-10-21)
+
+The owner merged 4e-2b as #132 (squash b9549821), every check green ("green and merged"); its six deferred minors are
+issue #133. 4e is done.
+
+4f was researched, then proposed ("research first, then propose"; notes R1 to R3 in `~/4_dev/mist_dewpoint-4f-notes`).
+The owner's answers (2026-10-20): 4f in three slices, in this order: 4f-1 the message composer, 4f-2 the Mist step,
+4f-3 the run form's pickers; previews rendered in the browser, held to the plugins' renderers by shared cases; the
+plugins say which steps get which widget (display hints), never the editor recognising a config's shape; the plugins'
+3b-1 rulings signed off as merged (recorded in the plugins-3 ledger). The 4f-1 boards ("4f-1 Message Composer
+Mockups") were approved at round 1 and signed off at v9 (D8). The design,
+`docs/superpowers/specs/2026-10-20-editor-4f1-message-composer-design.md` (d5dc43e8), keeps the Fixed / Formula switch
+on the severity, the fields and the links ("Keep them where useful"); it amends ruling 98 for a message (its parts
+together on Setup) and ruling 125 in that the message's text takes newlines.
+
+`docs/superpowers/plans/2026-10-21-editor-ui-4f1-message-composer.md`, revision 1: one plan, the backend's two tasks
+first, with milestone pauses. The owner accepted it: its rulings 1–21 join this ledger as 303–323. No step changes
+version (the hint is a display annotation, outside the contract hash); no route, no migration, no ABI change.
+Mid-slice rulings start at M113.
+
+303. **Accepted. One plan with milestone pauses** (plan ruling 1).
+304. **Accepted. The shared cases: eleven made-up messages, the webhook's body left out** (plan ruling 2).
+305. **Accepted. The mirror counts code points, and gives Teams' and Google Chat's uncut size** (plan ruling 3).
+306. **Accepted. A long run of text split at 4,096 code points, in the template branch only** (plan ruling 4).
+307. **Accepted. Every pill editor lays its text out in lines; Enter adds one where the composer asks** (plan ruling 5).
+308. **Accepted. The composer is the drawer's fields, each told how to draw its part** (plan ruling 6).
+309. **Accepted. Setup with a message: each field says "(required)"; Options says where the message is** (plan ruling 7).
+310. **Accepted. Targets by step type; a third party's message step gets no preview** (plan ruling 8).
+311. **Accepted. The title's hint says what it becomes** (plan ruling 9).
+312. **Accepted. The severity: a radio group, Info shown and nothing written by default** (plan ruling 10).
+313. **Accepted. Rows: labelled fields, their buttons under them, "2 of 25"** (plan ruling 11).
+314. **Accepted. A link's address checked as it's typed** (plan ruling 12).
+315. **Accepted. A value in a preview is written `check.site`** (plan ruling 13).
+316. **Accepted. Placeholders from plane 15's private use area** (plan ruling 14).
+317. **Accepted. What's said where: Slack's count, each cut, Teams' and Google Chat's size** (plan ruling 15).
+318. **Accepted. The previews draw what the mirror sends, in the app's tokens** (plan ruling 16).
+319. **Accepted. The text left empty, in the composer's words, once touched** (plan ruling 17).
+320. **Accepted. Read only: the message as written, the rest summed up** (plan ruling 18).
+321. **Accepted. No connection yet: the type named by its label** (plan ruling 19).
+322. **Accepted. Simulate's words in the result's banner** (plan ruling 20).
+323. **Accepted. The checks; the browser spec in CI, or locally on the owner's word** (plan ruling 21).
diff --git a/docs/superpowers/plans/2026-10-06-plugins-3-ledger.md b/docs/superpowers/plans/2026-10-06-plugins-3-ledger.md
index 0c67e1c5..b1daf848 100644
--- a/docs/superpowers/plans/2026-10-06-plugins-3-ledger.md
+++ b/docs/superpowers/plans/2026-10-06-plugins-3-ledger.md
@@ -780,6 +780,10 @@ integers; a port usage's `reauth_interval` null.
   13 skipped as before (9 with nothing in the test org to read their id from, 4 insight reads needing a `metrics`
   query). Every curated read the probe could reach runs as shipped against this org.
 
+**Signed off** (2026-10-20, in chat, while the editor's 4f was proposed): the owner signed off this section's rulings
+as merged (#49, `bc4c840`), among them the Mist pickers for site and organisation ids only, and the update contract (a
+top-level `body`, merge or replace, `clear`). Recorded by the editor's 4f-1 plan, Task 1.
+
 ## 3b-2 Mist device utilities
 
 Branch `feat/plugins-3b2` from `origin/main` 5e79a10 (#51, after 3b-1's #49 and its follow-up #50), started 2026-10-07:
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md docs/superpowers/plans/2026-10-06-plugins-3-ledger.md
git commit -m "docs(editor-4): 4e-2b merged, 4f split, the 4f-1 plan accepted; plugins 3b-1 signed off

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The message composer's hint

**Spec:** §4.1; §6 (the eight manifests carry the hint, their contract hashes unchanged).

**Files:**
- Modify: `backend/src/dewpoint/sdk/messages.py` (`Message`'s `model_config`)
- Create: `backend/tests/plugins/test_message_widget.py`

**Interfaces:**
- Consumes: `contract_hash` (`engine/registry/catalog.py`); each plugin's `PLUGIN.manifest()`.
- Produces: every config schema built on `Message` carries `"x-widget": "message"` at its root (Task 7 reads it).

The hint is `json_schema_extra` on the SDK's model, so every `class SendConfig(Message)` has it at its schema's root,
and so does a third party's config built on it. `x-widget` is a display annotation: the contract hash drops it from
every schema object, the root included, so the test pins the eight hashes as main computes them (b9549821) and finds
the eight steps by their config's five message properties.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/plugins/test_message_widget.py b/backend/tests/plugins/test_message_widget.py
new file mode 100644
index 00000000..0a7423ff
--- /dev/null
+++ b/backend/tests/plugins/test_message_widget.py
@@ -0,0 +1,51 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The message composer's hint (editor 4f-1; the message composer design §4.1): every step whose config is the SDK's
+message carries `x-widget: "message"` at its config's root. It's a display annotation, so no contract hash moves: the
+values were computed on origin/main b9549821, before the hint."""
+
+import importlib
+from typing import Any
+
+from dewpoint.engine.registry.catalog import contract_hash
+from dewpoint.sdk.messages import Message
+
+PINNED = {
+    "slack.send_message@1": "66a842a5c32312e78d4f123b338aa4a44d6e0ab26b046684369e2e188e05ccd6",
+    "teams.send_message@1": "0f4f484edd9c0b87e082eadbbbbca69eead00c3dd70694067bc8a67c12c8cc7e",
+    "google_chat.send_message@1": "4024fcb7b75923c98611211a48e2cce09a3deb6864afe215d676fd3abde9ff57",
+    "webhook.send_message@1": "7d1c73c599237c7c84434830b387d916fac57de1f1ac502eb683b3cdfc72ba9e",
+    "email.send_message@1": "7617c7f8bea98effea3168a6e2642a93389fabe44e4d3ebb5c1231529c0bf1cd",
+    "syslog.send_message@1": "28a01dc562d1e8b3b0899f287e328b03e82f94754a9cb8ca4a92648159874720",
+    "pagerduty.trigger_alert@1": "58564ce79266bdb0d5a9f00266d55ae8f161a3cc223c6f157c51b02211cf73a7",
+    "servicenow.create_incident@1": "4381278a184282b832f190c8759fc637ac227c331e94c5316ba1bc4eee61d00c",
+}
+PLUGINS = ("slack", "teams", "google_chat", "webhook", "email", "syslog", "pagerduty", "servicenow")
+
+
+def _message_nodes() -> dict[str, dict[str, Any]]:
+    """Each node whose config holds the message's five properties."""
+    nodes: dict[str, dict[str, Any]] = {}
+    for name in PLUGINS:
+        for node in importlib.import_module(f"dewpoint.plugins.{name}").PLUGIN.manifest()["nodes"]:
+            if {"title", "text", "fields", "links", "severity"} <= set(node["config_schema"].get("properties", {})):
+                nodes[f"{node['type']}@{node['version']}"] = node
+    return nodes
+
+
+def test_every_message_step_shows_the_composer() -> None:
+    nodes = _message_nodes()
+    assert set(nodes) == set(PINNED)
+    assert {ref: n["config_schema"].get("x-widget") for ref, n in nodes.items()} == dict.fromkeys(PINNED, "message")
+
+
+def test_the_hint_moves_no_contract_hash() -> None:
+    assert {ref: contract_hash(n) for ref, n in _message_nodes().items()} == PINNED
+
+
+def test_a_config_built_on_the_message_carries_the_hint() -> None:
+    """A third-party plugin's config on the SDK's message gets the composer too (built-in widgets only, arch §101)."""
+
+    class Theirs(Message):
+        channel: str
+
+    assert Theirs.model_json_schema()["x-widget"] == "message"
```

- [ ] **Step 2: Run them**

Run: `UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q tests/plugins/test_message_widget.py`

Expected: FAIL, 2 failed and 1 passed: no step's config carries the hint (`assert {'slack.send_...1': None, ...} ==
{'slack.send_...message', ...}`), nor a config built on the message (`KeyError: 'x-widget'`). The hashes' test passes at
once: it pins them, before the hint and after.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/sdk/messages.py b/backend/src/dewpoint/sdk/messages.py
index a8f9c83c..2eac90ff 100644
--- a/backend/src/dewpoint/sdk/messages.py
+++ b/backend/src/dewpoint/sdk/messages.py
@@ -42,7 +42,9 @@ class Link(BaseModel):
 
 
 class Message(BaseModel):
-    model_config = ConfigDict(extra="forbid")
+    # Display only (editor 4f-1, the message composer design §4.1): every config built on the message is shown as one
+    # composer. An annotation, outside the contract hash: no step needs a new version.
+    model_config = ConfigDict(extra="forbid", json_schema_extra={"x-widget": "message"})
     title: str | None = Field(default=None, max_length=1000)
     text: str = Field(min_length=1, max_length=40_000)
     fields: list[MessageField] = Field(default_factory=list, max_length=25)
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 3 passed.

- [ ] **Step 5: Static checks**

Run: the backend's static checks of "How to run things". Expected: as there.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/sdk/messages.py backend/tests/plugins/test_message_widget.py
git commit -m "feat(sdk): the message composer's hint on the SDK's message (4f-1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The renderers' shared cases

**Spec:** §4.2; §6 (the shared cases file matches each renderer's output); §8, call 3.

**Files:**
- Create: `backend/src/dewpoint/plugins/message_cases.py`, `backend/tests/plugins/test_message_cases.py`,
  `frontend/src/test/messageCases.json` (written by the command, Step 4)
- Modify: `backend/src/dewpoint/apps/cli/main.py` (`dewpoint plugins message-cases`)

**Interfaces:**
- Consumes: `render(message)` of `dewpoint.plugins.slack`, `.teams` and `.google_chat`; `Message`.
- Produces:
  - `message_cases.CASES: tuple[tuple[str, dict], ...]`, `rendered(message) -> dict`, `document() -> dict`;
  - `frontend/src/test/messageCases.json`: `{"about": str, "cases": [{name, message, slack, teams, google_chat}]}`,
    each target's `{"body", "truncated"}` (Task 4 holds the mirror to it).

Eleven made-up messages (ruling 2): the text alone, an empty title, a whole message, what each target escapes, text
past Slack's 3,000 characters, an escape where Slack cuts, a field's value and a button past Slack's, characters of
several bytes (a 75-character label outside the BMP among them), control characters, 25 fields and 10 links, and one
big enough for Teams and Google Chat to shorten. The test holds the file to the renderers, the command to the file,
and the cases to the cut names and the four severities the previews word.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/plugins/test_message_cases.py b/backend/tests/plugins/test_message_cases.py
new file mode 100644
index 00000000..aebba2c9
--- /dev/null
+++ b/backend/tests/plugins/test_message_cases.py
@@ -0,0 +1,36 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The renderers' shared cases (editor 4f-1; the message composer design §4.2). The editor's previews mirror the Slack,
+Teams and Google Chat renderers in TypeScript and are held to `frontend/src/test/messageCases.json`; this test holds
+that file to the renderers. A renderer changed: write the file again with
+`uv run dewpoint plugins message-cases > ../frontend/src/test/messageCases.json`."""
+
+import json
+from pathlib import Path
+
+from typer.testing import CliRunner
+
+from dewpoint.apps.cli.main import app
+from dewpoint.plugins.message_cases import document
+
+CASES_FILE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "test" / "messageCases.json"
+
+
+def test_the_editors_cases_are_what_the_renderers_return() -> None:
+    assert json.loads(CASES_FILE.read_text()) == document()
+
+
+def test_the_command_prints_the_cases() -> None:
+    result = CliRunner().invoke(app, ["plugins", "message-cases"])
+    assert result.exit_code == 0
+    assert json.loads(result.output) == document()
+
+
+def test_the_cases_reach_what_the_previews_say() -> None:
+    """Each cut the previews word is in some case, and Teams and Google Chat each shorten at more than one level."""
+    cases = document()["cases"]
+    targets = ("slack", "teams", "google_chat")
+    cut = {target: {name for c in cases for name in c[target]["truncated"]} for target in targets}
+    assert {"text", "fields[0].value", "links[0].label"} <= cut["slack"]
+    assert {"text", "title", "fields[0].value", "links[5]"} <= cut["teams"]
+    assert {"text", "title", "fields[0].value"} <= cut["google_chat"]
+    assert {c["message"].get("severity", "info") for c in cases} == {"info", "success", "warning", "critical"}
```

- [ ] **Step 2: Run them**

Run: `UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q tests/plugins/test_message_cases.py`

Expected: FAIL: the test can't import its module (`ModuleNotFoundError: No module named
'dewpoint.plugins.message_cases'`; 1 error during collection).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/backend/src/dewpoint/apps/cli/main.py b/backend/src/dewpoint/apps/cli/main.py
index 8f3b4f16..10669093 100644
--- a/backend/src/dewpoint/apps/cli/main.py
+++ b/backend/src/dewpoint/apps/cli/main.py
@@ -927,6 +927,15 @@ def plugins_list() -> None:
         typer.echo(line)
 
 
+@plugins_cli.command("message-cases")
+def plugins_message_cases() -> None:
+    """Print the renderers' shared cases, which the editor's message previews are tested against (editor 4f-1): write
+    them to frontend/src/test/messageCases.json. No server or settings."""
+    from dewpoint.plugins.message_cases import document
+
+    typer.echo(json.dumps(document(), indent=2, sort_keys=True, ensure_ascii=False))
+
+
 def _entry(node_type: str | None, cel_profile: str | None) -> Entry:
     if bool(node_type) == bool(cel_profile):
         typer.echo("pass exactly one of --node-type or --cel-profile")
diff --git a/backend/src/dewpoint/plugins/message_cases.py b/backend/src/dewpoint/plugins/message_cases.py
new file mode 100644
index 00000000..e6e87854
--- /dev/null
+++ b/backend/src/dewpoint/plugins/message_cases.py
@@ -0,0 +1,92 @@
+# SPDX-License-Identifier: Apache-2.0
+"""The renderers' shared cases (editor 4f-1; the message composer design §4.2): made-up messages, each as Slack, Teams
+and Google Chat render it. The editor's previews mirror those renderers in TypeScript and are held to the same cases
+(`frontend/src/test/messageCases.json`, written by `dewpoint plugins message-cases`), so a renderer that changes fails
+a test until the file is written again. Nothing here is real data."""
+
+from typing import Any
+
+from dewpoint.plugins import google_chat, slack, teams
+from dewpoint.sdk.messages import Message
+
+_LINK = "https://example.test/runbook"
+
+# Each case: its name, and the message as a step's config holds it (the connection aside).
+CASES: tuple[tuple[str, dict[str, Any]], ...] = (
+    ("the text alone", {"text": "Access point AP-12 stopped reporting."}),
+    ("an empty title", {"title": "", "text": "No title is shown."}),
+    (
+        "a whole message",
+        {
+            "title": "AP offline at HQ",
+            "text": "Access point AP-12 stopped reporting.\n\nLast seen by switch SW-3, port 12.",
+            "fields": [{"label": "Site", "value": "HQ"}, {"label": "Model", "value": "AP45"}],
+            "links": [{"label": "Open in Mist", "url": "https://manage.mist.test/admin/?site_id=1"}],
+            "severity": "warning",
+        },
+    ),
+    (
+        "what each target escapes",
+        {
+            "title": "<b> & </b>",
+            "text": "a < b && c > d <@U123> <!here> *bold* _it_ [x](https://example.test)",
+            "fields": [{"label": "x<y", "value": "<users/all> & more"}],
+            "links": [{"label": "a|b", "url": "https://example.test/a|b"}],
+            "severity": "critical",
+        },
+    ),
+    ("text past Slack's 3,000 characters", {"text": "x" * 3500, "severity": "success"}),
+    ("an escape where Slack cuts", {"text": "x" * 2996 + "&&&&"}),
+    (
+        "a field's value and a button past Slack's",
+        {
+            "text": "Details below.",
+            "fields": [{"label": "Note", "value": "v" * 2500}],
+            "links": [{"label": "b" * 100, "url": _LINK}],
+        },
+    ),
+    (
+        # Counted in code points, as Python counts: 75 of these are 150 UTF-16 units, within Slack's 75 for a button.
+        "characters of several bytes",
+        {"title": "Zürich — 東京 𝄞", "text": "Ünïcödé ✓ 日本語 " * 20, "links": [{"label": "𝄞" * 75, "url": _LINK}]},
+    ),
+    ("control characters", {"text": "a tab\there, a bell\u0007 and the end"}),
+    (
+        "as many fields and links as a message takes",
+        {
+            "text": "Twenty-five fields, ten links.",
+            "fields": [{"label": f"Field {i}", "value": f"value {i}"} for i in range(25)],
+            "links": [{"label": f"Link {i}", "url": f"{_LINK}/{i}"} for i in range(10)],
+        },
+    ),
+    (
+        "big enough for Teams and Google Chat to shorten it",
+        {
+            "title": "T" * 1000,
+            "text": "é" * 10_000,
+            "fields": [{"label": f"Field {i}", "value": "v" * 1000} for i in range(25)],
+            "links": [{"label": f"Link {i}", "url": f"{_LINK}/{i}"} for i in range(10)],
+            "severity": "warning",
+        },
+    ),
+)
+
+
+def rendered(message: Message) -> dict[str, Any]:
+    """The message as each target sends it: its body, and the names of the values it cut."""
+    out: dict[str, Any] = {}
+    for name, target in (("slack", slack), ("teams", teams), ("google_chat", google_chat)):
+        body, truncated = target.render(message)
+        out[name] = {"body": body, "truncated": truncated}
+    return out
+
+
+def document() -> dict[str, Any]:
+    """Every case with what each target makes of it: the file the editor's tests read."""
+    return {
+        "about": (
+            "The renderers' shared cases (editor 4f-1). Written by `dewpoint plugins message-cases`; held to the "
+            "plugins' renderers by backend/tests/plugins/test_message_cases.py. Never edit by hand."
+        ),
+        "cases": [{"name": name, "message": raw, **rendered(Message.model_validate(raw))} for name, raw in CASES],
+    }
```

- [ ] **Step 4: Write the cases file**

Run, from `$WT/backend`: `UV_FROZEN=1 UV_NO_SYNC=1 uv run dewpoint plugins message-cases >
../frontend/src/test/messageCases.json`
Expected: no output; the file is 251,225 bytes. It holds no secret and no real data: the made-up messages above.

- [ ] **Step 5: Run them again**

Run: the command of Step 2.

Expected: PASS, 3 passed.

- [ ] **Step 6: Static checks**

Run: the backend's static checks of "How to run things". Expected: as there.

- [ ] **Step 7: Commit, and the milestone**

```bash
git add backend/src/dewpoint/plugins/message_cases.py backend/src/dewpoint/apps/cli/main.py \
  backend/tests/plugins/test_message_cases.py frontend/src/test/messageCases.json
git commit -m "feat(plugins): the renderers' shared cases, written by dewpoint plugins message-cases (4f-1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4f-1, milestone 1 (<date>)` to the ledger: each task's commit, its red and green results as run, any
mid-slice ruling. Commit it as `docs(editor-4): 4f-1 milestone 1`, with the trailer. **Pause** for the owner's review.

---

# Milestone 2 — The mirror, and the text's writing

### Task 4: The renderers mirrored, held to the cases

**Spec:** §4.2 (a frontend test holds each TypeScript renderer to the same file); §7 (the mirror drifting; JSON's
bytes in TypeScript and Python).

**Files:**
- Create: `frontend/src/lib/messages.ts`, `frontend/src/lib/messages.test.ts`

**Interfaces:**
- Consumes: Task 3's `src/test/messageCases.json`.
- Produces (`lib/messages.ts`):
  - types `Severity`, `Message { title?, text, fields?, links?, severity? }`, `Rendered { body, truncated, size? }`;
  - `MARK`, `bytesOf(text)`, `cut(text, limit, unit = "chars" | "bytes"): [string, boolean]`;
  - `SLACK` (its five limits), `fitted(raw, limit)`, `slack(message): Rendered`;
  - `TEAMS_BUDGET`, `CHAT_BUDGET`, `teams(message)`, `googleChat(message)`: `Rendered`, `size` the uncut body's bytes.

Each function mirrors its Python twin line for line (`plugins/slack`, `plugins/teams`, `plugins/google_chat`
`render()`; `sdk/messages.py`'s `cut`), counting characters in code points (ruling 3). Teams and Google Chat render
level by level until the compact JSON body fits its budget, as the plugins do; the first level's size is kept.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/messages.test.ts b/frontend/src/lib/messages.test.ts
new file mode 100644
index 00000000..b04378a0
--- /dev/null
+++ b/frontend/src/lib/messages.test.ts
@@ -0,0 +1,44 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import cases from "../test/messageCases.json";
+import { cut, googleChat, slack, teams, type Message, type Rendered } from "./messages";
+
+interface Case {
+  name: string;
+  message: Message;
+  slack: Rendered;
+  teams: Rendered;
+  google_chat: Rendered;
+}
+
+// The plugins' own renderers wrote these (backend/tests/plugins/test_message_cases.py holds the file to them).
+const CASES = cases.cases as unknown as Case[];
+
+const sent = ({ body, truncated }: Rendered): Rendered => ({ body, truncated });
+
+describe.each(CASES)("$name", (c) => {
+  it("is laid out as Slack's renderer lays it out", () => expect(sent(slack(c.message))).toEqual(c.slack));
+  it("is laid out as Teams' renderer lays it out", () => expect(sent(teams(c.message))).toEqual(c.teams));
+  it("is laid out as Google Chat's renderer lays it out", () => expect(sent(googleChat(c.message))).toEqual(c.google_chat));
+});
+
+describe("cut", () => {
+  it("counts characters as Python does, a character outside the BMP as one", () => {
+    expect(cut("𝄞".repeat(3), 3)).toEqual(["𝄞𝄞𝄞", false]);
+    expect(cut("𝄞".repeat(4), 3)).toEqual(["𝄞𝄞…", true]);
+  });
+
+  it("counts UTF-8 bytes, never cutting through a character", () => {
+    expect(cut("ééé", 6, "bytes")).toEqual(["ééé", false]);
+    expect(cut("éééé", 6, "bytes")).toEqual(["é…", true]);
+  });
+});
+
+describe("the body's size before it's shortened", () => {
+  it("is the uncut body's UTF-8 bytes, as Teams and Google Chat are sent", () => {
+    const message: Message = { text: "é".repeat(20_000) };
+    expect(teams(message).size).toBeGreaterThan(40_000);
+    expect(teams(message).truncated).toEqual(["text"]);
+    expect(googleChat(message).size).toBe(new TextEncoder().encode(JSON.stringify({ text: `${"é".repeat(20_000)}\n\nSeverity: info` })).length);
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/messages.test.ts`

Expected: FAIL: `messages.test.ts` can't import its module (`Failed to resolve import "./messages"`; no test runs).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/messages.ts b/frontend/src/lib/messages.ts
new file mode 100644
index 00000000..c14769d3
--- /dev/null
+++ b/frontend/src/lib/messages.ts
@@ -0,0 +1,177 @@
+// SPDX-License-Identifier: Apache-2.0
+// The message the chat targets send (plugins-3 D18; editor 4f-1, the message composer design §4.2), and Slack's, Teams'
+// and Google Chat's renderers mirrored from the plugins (`render()` in plugins/slack, plugins/teams and
+// plugins/google_chat; sdk/messages.py's `cut`): a preview lays a message out as its target will, and says what it would
+// cut. Held to the plugins' own output by the shared cases (src/test/messageCases.json): a renderer changed there fails
+// messages.test.ts until this follows. Characters are counted in code points, as Python counts them.
+
+export type Severity = "info" | "success" | "warning" | "critical";
+
+export interface Message {
+  title?: string | null;
+  text: string;
+  fields?: { label: string; value: string }[];
+  links?: { label: string; url: string }[];
+  severity?: Severity;
+}
+
+/** What a target is sent, the names of the values it cut, and for Teams and Google Chat the body's size in bytes before
+ * anything was shortened. */
+export interface Rendered {
+  body: Record<string, unknown>;
+  truncated: string[];
+  size?: number;
+}
+
+export const MARK = "…"; // what a cut value ends with
+
+const length = (text: string): number => [...text].length;
+const encoder = new TextEncoder();
+export const bytesOf = (text: string): number => encoder.encode(text).length;
+/** The body as the plugins send it: compact JSON, UTF-8 (httpx's `encode_json`). */
+const encodedSize = (body: unknown): number => bytesOf(JSON.stringify(body));
+
+/** `text` within `limit` characters (or UTF-8 bytes), ending with MARK when it had to be cut; whether it was. */
+export function cut(text: string, limit: number, unit: "chars" | "bytes" = "chars"): [string, boolean] {
+  const chars = [...text];
+  if (unit === "chars") return chars.length <= limit ? [text, false] : [chars.slice(0, Math.max(0, limit - 1)).join("") + MARK, true];
+  if (bytesOf(text) <= limit) return [text, false];
+  const budget = limit - bytesOf(MARK);
+  const kept: string[] = [];
+  let size = 0;
+  for (const char of chars) {
+    size += bytesOf(char);
+    if (size > budget) break;
+    kept.push(char);
+  }
+  return [kept.join("") + MARK, true];
+}
+
+/** Collects the names of the values cut, as each renderer's `kept` does. */
+function cutter() {
+  const truncated: string[] = [];
+  const kept = (name: string, [value, was]: [string, boolean]): string => {
+    if (was) truncated.push(name);
+    return value;
+  };
+  return { truncated, kept };
+}
+
+// Slack (plugins/slack): Block Kit, each value escaped and cut within Slack's limits.
+export const SLACK = { SECTION_MAX: 3000, FIELD_MAX: 2000, FIELDS_A_SECTION: 10, BUTTON_MAX: 75, LABEL_MAX: 300 };
+
+const escape = (char: string): string => (char === "&" ? "&amp;" : char === "<" ? "&lt;" : char === ">" ? "&gt;" : char);
+
+/** `raw` escaped, within `limit` characters: cut before an escape rather than through one, and marked. */
+export function fitted(raw: string, limit: number): [string, boolean] {
+  const parts = [...raw].map(escape);
+  const escaped = parts.join("");
+  if (length(escaped) <= limit) return [escaped, false];
+  const kept: string[] = [];
+  let size = 0;
+  for (const part of parts) {
+    if (size + length(part) > limit - length(MARK)) break;
+    kept.push(part);
+    size += length(part);
+  }
+  return [kept.join("") + MARK, true];
+}
+
+const mrkdwn = (text: string) => ({ type: "mrkdwn", text, verbatim: true });
+
+export function slack(message: Message): Rendered {
+  const { SECTION_MAX, FIELD_MAX, FIELDS_A_SECTION, BUTTON_MAX, LABEL_MAX } = SLACK;
+  const { truncated, kept } = cutter();
+  const blocks: Record<string, unknown>[] = [];
+  if (message.title) blocks.push({ type: "section", text: mrkdwn(`*${kept("title", fitted(message.title, SECTION_MAX - 2))}*`) });
+  blocks.push({ type: "section", text: mrkdwn(kept("text", fitted(message.text, SECTION_MAX))) });
+  const fields = (message.fields ?? []).map((f, i) => {
+    const label = kept(`fields[${i}].label`, fitted(f.label, LABEL_MAX));
+    const value = kept(`fields[${i}].value`, fitted(f.value, FIELD_MAX - length(label) - 3));
+    return mrkdwn(`*${label}*\n${value}`);
+  });
+  for (let start = 0; start < fields.length; start += FIELDS_A_SECTION) {
+    blocks.push({ type: "section", fields: fields.slice(start, start + FIELDS_A_SECTION) });
+  }
+  const links = message.links ?? [];
+  if (links.length > 0) {
+    const buttons = links.map((link, i) => ({
+      type: "button", text: { type: "plain_text", text: kept(`links[${i}].label`, cut(link.label, BUTTON_MAX)), emoji: false },
+      url: link.url, action_id: `link_${i}`,
+    }));  // prettier-ignore
+    blocks.push({ type: "actions", elements: buttons });
+  }
+  blocks.push({ type: "context", elements: [mrkdwn(`Severity: ${message.severity ?? "info"}`)] });
+  const fallback = message.title ? `${message.title}: ${message.text}` : message.text;
+  return { body: { text: fitted(fallback, SECTION_MAX)[0], blocks }, truncated };
+}
+
+// Teams and Google Chat: the whole body within a budget of bytes, each value tighter at each level until it fits.
+// A level: title characters, text bytes, field value bytes, label characters, links kept. The first cuts nothing.
+type Level = readonly [number, number, number, number, number];
+const LEVELS: readonly Level[] = [
+  [1000, 160_000, 40_000, 200, 10],
+  [1000, 16_000, 2000, 200, 10],
+  [500, 8000, 600, 100, 10],
+  [200, 4000, 200, 60, 5],
+  [100, 1000, 60, 30, 2],
+  [60, 200, 20, 20, 0],
+];
+export const TEAMS_BUDGET = 24_000;
+export const CHAT_BUDGET = 30_000;
+
+/** The first level's body that fits the budget (the last always fits), with the size of the first, uncut. */
+function withinBudget(budget: number, make: (level: Level) => Omit<Rendered, "size">): Rendered {
+  let made = make(LEVELS[0]!);
+  const size = encodedSize(made.body);
+  if (size <= budget) return { ...made, size };
+  for (const level of LEVELS.slice(1)) {
+    made = make(level);
+    if (encodedSize(made.body) <= budget) break;
+  }
+  return { ...made, size };
+}
+
+const runs = (...each: Record<string, unknown>[]) => ({ type: "RichTextBlock", inlines: each.map((run) => ({ type: "TextRun", ...run })) });
+
+function teamsCard(message: Message, [titleMax, textMax, valueMax, labelMax, linksKept]: Level): Omit<Rendered, "size"> {
+  const { truncated, kept } = cutter();
+  const body: Record<string, unknown>[] = [];
+  if (message.title) body.push(runs({ text: kept("title", cut(message.title, titleMax)), weight: "bolder", size: "medium" }));
+  body.push(runs({ text: kept("text", cut(message.text, textMax, "bytes")) }));
+  (message.fields ?? []).forEach((field, i) => {
+    const label = kept(`fields[${i}].label`, cut(field.label, labelMax));
+    const value = kept(`fields[${i}].value`, cut(field.value, valueMax, "bytes"));
+    body.push(runs({ text: label, weight: "bolder" }, { text: ": " }, { text: value }));
+  });
+  body.push(runs({ text: `Severity: ${message.severity ?? "info"}`, isSubtle: true, size: "small" }));
+  const card: Record<string, unknown> = { $schema: "http://adaptivecards.io/schemas/adaptive-card.json", type: "AdaptiveCard", version: "1.2", body };
+  const links = message.links ?? [];
+  const actions = links.slice(0, linksKept).map((link, i) => ({ type: "Action.OpenUrl", title: kept(`links[${i}].label`, cut(link.label, labelMax)), url: link.url }));
+  truncated.push(...links.slice(linksKept).map((_, i) => `links[${linksKept + i}]`));
+  if (actions.length > 0) card.actions = actions;
+  return { body: { type: "message", attachments: [{ contentType: "application/vnd.microsoft.card.adaptive", contentUrl: null, content: card }] }, truncated };
+}
+
+export const teams = (message: Message): Rendered => withinBudget(TEAMS_BUDGET, (level) => teamsCard(message, level));
+
+// Google Chat: one text message; < and > shown as ＜ ＞, so a value can't become a link or a mention.
+const neutral = (text: string): string => text.replace(/</g, "＜").replace(/>/g, "＞");
+
+function chatText(message: Message, [titleMax, textMax, valueMax, labelMax, linksKept]: Level): Omit<Rendered, "size"> {
+  const { truncated, kept } = cutter();
+  const text = kept("text", cut(neutral(message.text), textMax, "bytes"));
+  const head = message.title ? `*${kept("title", cut(neutral(message.title), titleMax))}*\n${text}` : text;
+  const fields = (message.fields ?? []).map(
+    (f, i) => `*${kept(`fields[${i}].label`, cut(neutral(f.label), labelMax))}*: ${kept(`fields[${i}].value`, cut(neutral(f.value), valueMax, "bytes"))}`,
+  );
+  const links = message.links ?? [];
+  const linked = links
+    .slice(0, linksKept)
+    .map((link, i) => `<${link.url.replace(/\|/g, "%7C")}|${kept(`links[${i}].label`, cut(neutral(link.label), labelMax))}>`);
+  truncated.push(...links.slice(linksKept).map((_, i) => `links[${linksKept + i}]`));
+  const sections = [head, ...[fields, linked].filter((part) => part.length > 0).map((part) => part.join("\n")), `Severity: ${message.severity ?? "info"}`];
+  return { body: { text: sections.join("\n\n") }, truncated };
+}
+
+export const googleChat = (message: Message): Rendered => withinBudget(CHAT_BUDGET, (level) => chatText(message, level));
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 36 passed (each of the eleven cases for each target, and three of its own).

- [ ] **Step 5: Static checks**

Run: the frontend's static checks of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/messages.ts frontend/src/lib/messages.test.ts
git commit -m "feat(editor): Slack's, Teams' and Google Chat's renderers mirrored, held to the shared cases (4f-1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: A long run of text, written in parts

**Spec:** §5.2 (a long run of written text is split when it's saved; to verify: the engine accepts adjacent written
parts); §8, call 9.

**Files:**
- Modify: `frontend/src/lib/pills.ts` (`MAX_TEXT`, `valueOf`), `frontend/src/lib/pills.test.ts`,
  `backend/tests/engine/graph/test_values.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `pills.ts`: `MAX_TEXT = 4096`; `valueOf` writes a template's text in runs of at most `MAX_TEXT` code
  points, in a row (ruling 4).

The engine takes a template's written text in parts of up to 4,096 characters (`engine/graph/values.py`), at most
100 parts, and joins them when it reads; it already takes parts in a row. The backend test pins that, and that a
longer part is refused. The split is in the shared writer, so every field that takes values gains it.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/backend/tests/engine/graph/test_values.py b/backend/tests/engine/graph/test_values.py
index c0df98d5..0f8c6a91 100644
--- a/backend/tests/engine/graph/test_values.py
+++ b/backend/tests/engine/graph/test_values.py
@@ -6,6 +6,7 @@ from hypothesis import given, settings
 from hypothesis import strategies as st
 
 from dewpoint.engine.graph.values import (
+    MAX_TEXT,
     CelValue,
     LiteralValue,
     RefSyntaxError,
@@ -100,6 +101,16 @@ def test_envelope_errors_are_reported_in_place(body: dict[str, Any]) -> None:
     assert pointer == ("f",) and isinstance(value, ValueSyntaxError)
 
 
+def test_a_template_takes_written_parts_in_a_row() -> None:
+    """The editor writes a long run of text as parts of `MAX_TEXT` each (4f-1, the message composer design §5.2)."""
+    parts = [{"text": "x" * MAX_TEXT}, {"text": "x" * MAX_TEXT}, {"ref": "vars.name"}]
+    [(_, value)] = list(iter_values({"t": {"$value": {"kind": "template", "parts": parts}}}))
+    assert isinstance(value, TemplateValue) and value.parts[:2] == ("x" * MAX_TEXT, "x" * MAX_TEXT)
+    too_long = {"$value": {"kind": "template", "parts": [{"text": "x" * (MAX_TEXT + 1)}]}}
+    [(_, longer)] = list(iter_values({"t": too_long}))
+    assert isinstance(longer, ValueSyntaxError)
+
+
 def test_strip_values_replaces_envelopes_with_null() -> None:
     stripped, pointers = strip_values({"a": 1, "b": [{"$value": {"kind": "cel", "expr": "x"}}, 2]})
     assert stripped == {"a": 1, "b": [None, 2]} and pointers == [("b", 0)]
diff --git a/frontend/src/lib/pills.test.ts b/frontend/src/lib/pills.test.ts
index 9c7fe7d8..f9725c59 100644
--- a/frontend/src/lib/pills.test.ts
+++ b/frontend/src/lib/pills.test.ts
@@ -47,6 +47,18 @@ describe("text and pills", () => {
     );
   });
 
+  it("writes a long text as parts of the engine's 4,096 characters, counted as Python counts, read back as one", () => {
+    const long = "x".repeat(4096) + "𝄞".repeat(5000);
+    const s: Segments = { texts: [long, ""], pills: [{ ref: "run.id" }] };
+    const written = valueOf(s, false);
+    expect(written).toEqual(template({ text: "x".repeat(4096) }, { text: "𝄞".repeat(4096) }, { text: "𝄞".repeat(904) }, { ref: "run.id" }));
+    expect(sameSegments(segmentsOf(written)!, s)).toBe(true);
+    // Where the engine takes no fixed value, text alone is a template too: split the same way.
+    expect(valueOf({ texts: ["y".repeat(5000)], pills: [] }, false, false)).toEqual(template({ text: "y".repeat(4096) }, { text: "y".repeat(904) }));
+    // A fixed text isn't a template: the engine takes it whole.
+    expect(valueOf({ texts: ["y".repeat(5000)], pills: [] }, false)).toBe("y".repeat(5000));
+  });
+
   it("reads back what it writes", () => {
     const s: Segments = { texts: ["AP ", " at ", ""], pills: [{ ref: "trigger.ap", default: "AP" }, { ref: "run.now" }] };
     expect(sameSegments(segmentsOf(valueOf(s, false))!, s)).toBe(true);
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/pills.test.ts`, then, from `$WT/backend`,
`UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q tests/engine/graph/test_values.py`

Expected: FAIL, 1 failed and 10 passed: the long text is written as one part (`expected { Object ($value) } to deeply
equal { Object ($value) }`). The backend's 39 pass, the new one at once: the engine already takes parts in a row; it
pins that.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/pills.ts b/frontend/src/lib/pills.ts
index b3e3061c..52622351 100644
--- a/frontend/src/lib/pills.ts
+++ b/frontend/src/lib/pills.ts
@@ -25,6 +25,18 @@ export interface Caret {
 
 const EMPTY: Segments = { texts: [""], pills: [] };
 
+/** The engine's longest written part of a template (engine/graph/values.py's MAX_TEXT), in characters as Python counts
+ * them: a longer run is written as several parts in a row, which read back as one (4f-1, the message composer design
+ * §5.2). */
+export const MAX_TEXT = 4096;
+
+const runsOf = (text: string): { text: string }[] => {
+  const chars = [...text];
+  const runs: { text: string }[] = [];
+  for (let start = 0; start < chars.length; start += MAX_TEXT) runs.push({ text: chars.slice(start, start + MAX_TEXT).join("") });
+  return runs;
+};
+
 const bodyOf = (value: unknown): Record<string, unknown> =>
   isObject(value) && isObject(value[ENVELOPE]) ? value[ENVELOPE] : {};
 
@@ -68,19 +80,19 @@ export function segmentsOf(value: unknown): Segments | null {
 }
 
 /** What the draft holds for text and pills: nothing, when it's empty; the text, when there are no pills (a literal's
- * payload written back as one); else a template, its empty texts left out. A lone pill is a template too: text, as
- * the field takes it, never the value it reads (which may not be text). */
+ * payload written back as one); else a template, its empty texts left out, a long one in runs of MAX_TEXT. A lone pill
+ * is a template too: text, as the field takes it, never the value it reads (which may not be text). */
 export function valueOf(s: Segments, asLiteral: boolean, literalOk = true): unknown {
   if (s.pills.length === 0) {
     const text = s.texts.join("");
     if (text === "") return undefined;
     // Where the engine takes no fixed value, text alone is a template of one text part (x-dewpoint-kinds).
-    if (!literalOk) return { [ENVELOPE]: { kind: "template", parts: [{ text }] } };
+    if (!literalOk) return { [ENVELOPE]: { kind: "template", parts: runsOf(text) } };
     return asLiteral ? literal(text) : text;
   }
   const parts: Record<string, unknown>[] = [];
   s.texts.forEach((text, i) => {
-    if (text !== "") parts.push({ text });
+    parts.push(...runsOf(text));
     const pill = s.pills[i];
     if (pill) parts.push("default" in pill ? { ref: pill.ref, default: pill.default } : { ref: pill.ref });
   });
```

- [ ] **Step 4: Run them again**

Run: the same two commands.

Expected: PASS, 11 passed; the backend's 39 passed.

- [ ] **Step 5: Static checks**

Run: the frontend's and the backend's static checks of "How to run things". Expected: as there.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/pills.ts frontend/src/lib/pills.test.ts backend/tests/engine/graph/test_values.py
git commit -m "feat(editor): a long run of text written in parts of the engine's 4,096 characters (4f-1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Text on several lines

**Spec:** §5.2 (the text on several lines, Enter and Backspace; no `contenteditable`, ruling 125 amended); §7 (caret
moves between lines need their own handling and tests); §8, call 4.

**Files:**
- Modify: `frontend/src/lib/pills.ts` (`Piece`, `Line`, `linesOf`), `frontend/src/lib/pills.test.ts`,
  `frontend/src/routes/editor/drawer/TextPills.tsx` (lines, `lines`), `frontend/src/routes/editor/drawer/FieldView.tsx`
  (`LINES_NOTE`, `Drawn { lines }`), `frontend/src/routes/editor/drawer/TextPills.test.tsx`

**Interfaces:**
- Consumes: `Segments`, `withText` (`lib/pills.ts`).
- Produces:
  - `pills.ts`: `interface Piece { segment; start; text }`, `type Line = { piece: Piece; pill: number | null }[]`,
    `linesOf(s: Segments): Line[]`;
  - `TextPills`'s `lines?: boolean`;
  - `FieldView`'s `drawn?: Drawn`, with `Drawn { lines?: boolean }` (Tasks 7–9 add to it), and
    `LINES_NOTE = "Press / or ＋ Data to add a value; Enter starts a new line."`.

The model stays text and pills, the newlines in the texts (ruling 5). The editor draws a row per line, an input per
piece of text between pills and newlines, its caret counted in its segment's text. Enter (where `lines`) writes a
newline at the caret; Backspace at a line's start joins it to the line above; ↑ ↓ Home End ← → move as ruling 5 says,
unmodified only. A later line's input is named "<label>, line N"; one after a pill keeps its name.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/pills.test.ts b/frontend/src/lib/pills.test.ts
index f9725c59..5ebb2ecd 100644
--- a/frontend/src/lib/pills.test.ts
+++ b/frontend/src/lib/pills.test.ts
@@ -2,7 +2,7 @@
 import { describe, expect, it } from "vitest";
 import { formula, literal } from "./config";
 import {
-  headOf, insertPill, parsePath, pillText, removePill, replacePill, sameSegments, segmentsOf, segmentsText, valueOf,
+  headOf, insertPill, linesOf, parsePath, pillText, removePill, replacePill, sameSegments, segmentsOf, segmentsText, valueOf,
   withDefault, withText, type Segments,
 } from "./pills";  // prettier-ignore
 
@@ -59,6 +59,25 @@ describe("text and pills", () => {
     expect(valueOf({ texts: ["y".repeat(5000)], pills: [] }, false)).toBe("y".repeat(5000));
   });
 
+  it("lays text and pills out as lines: each line's pieces of text, each with the pill after it on that line", () => {
+    const s: Segments = { texts: ["Access point ", " stopped.\nLast seen ", ""], pills: [{ ref: "a.name" }, { ref: "run.now" }] };
+    expect(linesOf(s)).toEqual([
+      [
+        { piece: { segment: 0, start: 0, text: "Access point " }, pill: 0 },
+        { piece: { segment: 1, start: 0, text: " stopped." }, pill: null },
+      ],
+      [
+        { piece: { segment: 1, start: 10, text: "Last seen " }, pill: 1 },
+        { piece: { segment: 2, start: 0, text: "" }, pill: null },
+      ],
+    ]);
+    expect(linesOf({ texts: ["a\n\nb"], pills: [] }).map((line) => line[0]!.piece)).toEqual([
+      { segment: 0, start: 0, text: "a" },
+      { segment: 0, start: 2, text: "" },
+      { segment: 0, start: 3, text: "b" },
+    ]);
+  });
+
   it("reads back what it writes", () => {
     const s: Segments = { texts: ["AP ", " at ", ""], pills: [{ ref: "trigger.ap", default: "AP" }, { ref: "run.now" }] };
     expect(sameSegments(segmentsOf(valueOf(s, false))!, s)).toBe(true);
diff --git a/frontend/src/routes/editor/drawer/TextPills.test.tsx b/frontend/src/routes/editor/drawer/TextPills.test.tsx
index 550766dd..b9f3f74a 100644
--- a/frontend/src/routes/editor/drawer/TextPills.test.tsx
+++ b/frontend/src/routes/editor/drawer/TextPills.test.tsx
@@ -3,7 +3,9 @@ import { act, fireEvent, screen, waitFor, within } from "@testing-library/react"
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
 import type { ScopeEntry } from "../../../lib/data";
+import { fieldsOf } from "../../../lib/schemaForm";
 import { typeWith } from "../../../test/nodeTypes";
+import { FieldView } from "./FieldView";
 import { fakeApi, json, NODE_ID, showFields } from "./harness";
 
 const NOTE = typeWith(
@@ -225,3 +227,76 @@ describe("text with data pills", () => {
     expect(screen.queryByRole("button", { name: "＋ Data" })).toBeNull();
   });
 });
+
+describe("text on several lines (4f-1, the message composer design §5.2)", () => {
+  const lines = (config: Record<string, unknown>) =>
+    showFields(NOTE, { steps, config }, <FieldView spec={fieldsOf(NOTE)[0]!} drawn={{ lines: true }} />);
+  const caretIn = (input: HTMLElement, at: number) => {
+    expect(document.activeElement).toBe(input);
+    expect((input as HTMLInputElement).selectionStart).toBe(at);
+  };
+
+  it("starts a new line with Enter at the caret, each line its own row", async () => {
+    const f = lines({ message: "AP down" });
+    const first = screen.getByLabelText<HTMLInputElement>("Message");
+    await userEvent.click(first);
+    first.setSelectionRange(2, 2);
+    await userEvent.keyboard("{Enter}");
+    expect(f.config()).toEqual({ message: "AP\n down" });
+    await waitFor(() => caretIn(screen.getByRole("textbox", { name: "Message, line 2" }), 0));
+    expect(screen.getByText("Press / or ＋ Data to add a value; Enter starts a new line.")).toBeTruthy();
+  });
+
+  it("joins a line to the one above with Backspace at its start", async () => {
+    const f = lines({ message: "AP\ndown" });
+    const second = screen.getByRole<HTMLInputElement>("textbox", { name: "Message, line 2" });
+    await userEvent.click(second);
+    second.setSelectionRange(0, 0);
+    await userEvent.keyboard("{Backspace}");
+    expect(f.config()).toEqual({ message: "APdown" });
+    await waitFor(() => caretIn(screen.getByLabelText("Message"), 2));
+  });
+
+  it("keeps the lines of a text with values, and writes what's typed on a line back into its part", async () => {
+    const value = template({ text: "Access point " }, { ref: "steps.get_site.output.name" }, { text: " stopped.\nLast seen " }, { ref: "run.now" });
+    const f = lines({ message: value });
+    expect(screen.getAllByRole("textbox").map((t) => t.getAttribute("aria-label"))).toEqual([
+      null, "Message, text after get_site › name", "Message, line 2", "Message, text after run › now",
+    ]);  // prettier-ignore
+    await userEvent.type(screen.getByRole("textbox", { name: "Message, line 2" }), "at");
+    expect(f.config()).toEqual({
+      message: template({ text: "Access point " }, { ref: "steps.get_site.output.name" }, { text: " stopped.\nLast seen at" }, { ref: "run.now" }),
+    });
+  });
+
+  it("moves between lines with ↑ and ↓, across a line's end with ← and →, and to its ends with Home and End", async () => {
+    lines({ message: "first line\nsecond" });
+    const [first, second] = [screen.getByLabelText("Message"), screen.getByRole("textbox", { name: "Message, line 2" })];
+    await userEvent.click(second);
+    (second as HTMLInputElement).setSelectionRange(3, 3);
+    await userEvent.keyboard("{ArrowUp}");
+    caretIn(first, 3);
+    await userEvent.keyboard("{ArrowDown}");
+    caretIn(second, 3);
+    await userEvent.keyboard("{End}");
+    caretIn(second, 6);
+    await userEvent.keyboard("{Home}");
+    caretIn(second, 0);
+    await userEvent.keyboard("{ArrowLeft}");
+    caretIn(first, 10);
+    await userEvent.keyboard("{ArrowRight}");
+    caretIn(second, 0);
+  });
+
+  it("shows a newline already in a one-line field's value on its own row, and keeps it", async () => {
+    const f = showFields(NOTE, { steps, config: { message: "AP\ndown" } });
+    await userEvent.type(screen.getByRole("textbox", { name: "Message, line 2" }), "!");
+    expect(f.config()).toEqual({ message: "AP\ndown!" });
+  });
+
+  it("keeps a one-line field on one line: Enter adds nothing", async () => {
+    const f = showFields(NOTE, { steps, config: { message: "AP" } });
+    await userEvent.type(screen.getByLabelText("Message"), "{Enter}");
+    expect(f.config()).toEqual({ message: "AP" });
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/pills.test.ts src/routes/editor/drawer/TextPills.test.tsx`

Expected: FAIL, 6 failed and 28 passed: `linesOf` doesn't exist (`(0 , linesOf) is not a function`); no input is named
"Message, line 2" (`Unable to find an accessible element with the role "textbox" and name "Message, line 2"`); Enter
writes nothing (`expected { message: 'AP down' } to deeply equal { message: 'AP\n down' }`); a newline already in the
value is dropped by its input. "keeps a one-line field on one line: Enter adds nothing" passes at once: it pins that
Enter stays out of one-line fields.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/pills.ts b/frontend/src/lib/pills.ts
index 52622351..80a7796b 100644
--- a/frontend/src/lib/pills.ts
+++ b/frontend/src/lib/pills.ts
@@ -155,6 +155,32 @@ export const withText = (s: Segments, segment: number, text: string): Segments =
   pills: s.pills,
 });
 
+/** A piece of a text one input shows (4f-1): its segment, where it starts in that segment's text, and its text, with
+ * no newline. */
+export interface Piece {
+  segment: number;
+  start: number;
+  text: string;
+}
+
+/** A line of text and pills: its pieces, each with the pill after it on the line (its index), or null. */
+export type Line = { piece: Piece; pill: number | null }[];
+
+/** Text and pills as lines, split at each newline in the texts: a line starts and ends with a piece, maybe empty. */
+export function linesOf(s: Segments): Line[] {
+  const lines: Line[] = [[]];
+  s.texts.forEach((text, segment) => {
+    let start = 0;
+    const parts = text.split("\n");
+    parts.forEach((part, i) => {
+      if (i > 0) lines.push([]);
+      lines.at(-1)!.push({ piece: { segment, start, text: part }, pill: i === parts.length - 1 && segment < s.pills.length ? segment : null });
+      start += part.length + 1;
+    });
+  });
+  return lines;
+}
+
 /** Text and pills as a person reads them back (the recovery file, the list of edits not applied): each pill in braces,
  * as the read-only view writes a template (config.ts's referenceText). */
 export const segmentsText = (s: Segments): string =>
diff --git a/frontend/src/routes/editor/drawer/FieldView.tsx b/frontend/src/routes/editor/drawer/FieldView.tsx
index d90d1858..2943509c 100644
--- a/frontend/src/routes/editor/drawer/FieldView.tsx
+++ b/frontend/src/routes/editor/drawer/FieldView.tsx
@@ -26,6 +26,8 @@ type Control = (props: ControlProps) => ReactNode;
 const OWN: UnappliedKind[] = ["text", "template", "condition", "json", "number", "formula", "port"]; // what a field's own control may hold
 const NEITHER = "This field takes only references or text with references, which can't be set in this drawer.";
 export const PILLS_NOTE = "Press / or ＋ Data to insert data from earlier steps. A dashed pill may be missing when this runs: give it a default.";
+/** What a text on several lines says, under the message's text (4f-1). */
+export const LINES_NOTE = "Press / or ＋ Data to add a value; Enter starts a new line.";
 /** What a viewer and a version's view are told: they can't insert data or give a default (#85). */
 export const PILLS_SEEN = "A dashed pill may be missing when this runs.";
 
@@ -90,7 +92,12 @@ const startMode = (spec: FieldSpec, value: unknown): Mode =>
   : value !== undefined && value !== null ? "fixed"
   : startsAsFormula(spec) ? "formula" : "fixed";  // prettier-ignore
 
-export function FieldView({ spec }: { spec: FieldSpec }) {
+/** How the message composer draws one of its parts (4f-1, the message composer design §5): the text on several lines. */
+export interface Drawn {
+  lines?: boolean;
+}
+
+export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn }) {
   const drawer = useDrawer();
   const value = valueAt(drawer.node.config ?? {}, spec.path);
   const kind = kindOf(value);
@@ -291,7 +298,7 @@ export function FieldView({ spec }: { spec: FieldSpec }) {
   const textPills = (c: Described) => (
     <TextPills
       key={generation} {...c} spec={spec} value={hidden ? undefined : fixed} literal={held?.literal ?? kind === "literal"}
-      disabled={disabled} onChange={write} panel={panel} // it writes a literal back as one itself, never a template as data
+      disabled={disabled} onChange={write} panel={panel} lines={drawn.lines} // it writes a literal back as one itself, never a template as data
     />
   );  // prettier-ignore
   let body: ReactNode;
@@ -311,7 +318,7 @@ export function FieldView({ spec }: { spec: FieldSpec }) {
   } else if (held?.kind === "template" || (mode === "fixed" && asText && !hidden && !(held && Held))) {
     // Text with data pills: what's held, or the value, as text and pills (4c-2b).
     // "/" and "＋ Data" work where the person may edit the draft: the note says them only there (#85).
-    const pillsNote = !disabled && drawer.revision !== null ? PILLS_NOTE : PILLS_SEEN;
+    const pillsNote = disabled || drawer.revision === null ? PILLS_SEEN : drawn.lines ? LINES_NOTE : PILLS_NOTE;
     body = frame(textPills, joined(spec.hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, pillsNote));
   } else if (held && Held) {
     // What's held shows first, before what the value under it has become (a reference, a hidden secret, another
diff --git a/frontend/src/routes/editor/drawer/TextPills.tsx b/frontend/src/routes/editor/drawer/TextPills.tsx
index 4373e7f5..5535bc75 100644
--- a/frontend/src/routes/editor/drawer/TextPills.tsx
+++ b/frontend/src/routes/editor/drawer/TextPills.tsx
@@ -3,13 +3,15 @@
 // the references between it (the owner's ruling: one text and pill editor). Its texts are inputs, each pill a button
 // between them, in one box: the text is typed as any text field's is, and a pill is a whole that's moved past, opened
 // or removed, never half edited. A pill says what it reads, and is dashed when its value may be missing (ruling 115).
+// Its text is laid out in lines, an input for each piece of text between pills and newlines; a field that takes several
+// lines (the message's text, 4f-1) starts one with Enter and joins one to the line above with Backspace at its start.
 import { useEffect, useRef, type KeyboardEvent } from "react";
 import { DataTree } from "./DataTree";
 import { PillButton, usePillEntry } from "./Pill";
 import { PillDetails } from "./PillDetails";
 import {
-  insertPill, pillText, removePill, replacePill, segmentsOf, segmentsText, valueOf, withDefault, withText, type Caret, type Pill,
-  type Segments,
+  insertPill, linesOf, pillText, removePill, replacePill, segmentsOf, segmentsText, valueOf, withDefault, withText, type Caret,
+  type Pill, type Segments,
 } from "../../../lib/pills";  // prettier-ignore
 import { useDrawer } from "./context";
 import type { ControlProps } from "./scalars";
@@ -38,27 +40,39 @@ export interface PillsPanel {
   focus: { current: { segment: number; offset: number } | { pill: number } | null };
 }
 
-export function TextPills({ spec, value, literal, id, describedBy, invalid, disabled, onChange, panel }: ControlProps & { panel: PillsPanel }) {
+/** Keys that move the caret, pressed without a modifier: a modified one is the browser's (a selection, a shortcut). */
+const plain = (e: KeyboardEvent) => !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey;
+
+export function TextPills({ spec, value, literal, id, describedBy, invalid, disabled, onChange, panel, lines = false }: ControlProps & {
+  panel: PillsPanel; lines?: boolean;
+}) {  // prettier-ignore
   const drawer = useDrawer();
   const held = drawer.held("template", spec.pointer);
   const segments: Segments = held?.segments ?? segmentsOf(value) ?? { texts: [""], pills: [] };
   const literalOk = spec.kinds === null || spec.kinds.includes("literal");
+  const rows = linesOf(segments);
+  const pieces = rows.flat().map((item) => item.piece);
   const inputs = useRef<(HTMLInputElement | null)[]>([]);
   const pills = useRef<(HTMLButtonElement | null)[]>([]);
   const asLiteral = held?.literal ?? literal;
 
+  /** Focus at a place of a segment's text: the input holding it. A place past the end ("＋ Data" pressed before the
+   * text was ever focused asks for it) is the end of the last text (the final review). */
+  const focusAt = (segment: number, offset: number) => {
+    let index = pieces.findIndex((p) => p.segment === segment && offset >= p.start && offset <= p.start + p.text.length);
+    if (index < 0) index = Math.max(0, pieces.findLastIndex((p) => p.segment === Math.min(segment, segments.texts.length - 1)));
+    const piece = pieces[index]!;
+    const at = Math.max(0, Math.min(offset - piece.start, piece.text.length));
+    inputs.current[index]?.focus();
+    inputs.current[index]?.setSelectionRange(at, at);
+  };
+
   useEffect(() => {
     const want = panel.focus.current;
     if (!want) return;
     panel.focus.current = null;
     if ("pill" in want) pills.current[want.pill]?.focus();
-    else {
-      // "＋ Data" pressed before the text was ever focused asks for the end: the last text's (the final review).
-      const input = inputs.current[Math.min(want.segment, inputs.current.length - 1)];
-      const offset = Math.min(want.offset, input?.value.length ?? 0);
-      input?.focus();
-      input?.setSelectionRange(offset, offset);
-    }
+    else focusAt(want.segment, want.offset);
   });
 
   /** Writes text and pills as one change; refused, it's held with why, whole (ruling 18). */
@@ -68,18 +82,39 @@ export function TextPills({ spec, value, literal, id, describedBy, invalid, disa
     else drawer.hold("template", spec.pointer, { path: spec.path, label: spec.label, text: segmentsText(next), segments: next, why, literal: asLiteral, literalOk, entry: spec.entry });
   };  // prettier-ignore
 
-  const caretOf = (segment: number, input: HTMLInputElement): Caret => ({ segment, offset: input.selectionStart ?? input.value.length });
+  const caretOf = (index: number, input: HTMLInputElement): Caret => ({
+    segment: pieces[index]!.segment, offset: pieces[index]!.start + (input.selectionStart ?? input.value.length),
+  });  // prettier-ignore
+  const rowOf = (index: number) => rows.findIndex((row) => row.some((item) => item.piece === pieces[index]));
 
-  const onTextKey = (segment: number) => (e: KeyboardEvent<HTMLInputElement>) => {
+  const onTextKey = (index: number) => (e: KeyboardEvent<HTMLInputElement>) => {
+    const { segment, start } = pieces[index]!;
+    const text = segments.texts[segment]!;
     const input = e.currentTarget;
     const at = input.selectionStart ?? 0;
-    const collapsed = at === (input.selectionEnd ?? at);
+    const end = input.selectionEnd ?? at;
+    const collapsed = at === end;
+    const offset = start + at; // in the segment's text, its newlines counted
     if (e.key === "/" && collapsed && asksForData(input.value, at) && !disabled) {
       // The "/" is typed as text: the tree opens over it, and a pick replaces it (Escape keeps it, as typed). It opens in
       // the next task, once the browser has typed the "/": opened in a microtask, React draws it with the keydown, and
       // the tree's search takes focus, and the "/", first (seen in a browser, #85).
-      panel.caret.current = { segment, offset: at + 1 };
-      setTimeout(() => panel.open({ kind: "tree", at: { segment, offset: at + 1 }, slash: true }), 0);
+      panel.caret.current = { segment, offset: offset + 1 };
+      setTimeout(() => panel.open({ kind: "tree", at: { segment, offset: offset + 1 }, slash: true }), 0);
+    } else if (lines && e.key === "Enter" && !e.altKey && !e.metaKey && !e.ctrlKey && !disabled) {
+      e.preventDefault(); // a new line at the caret, what's selected replaced
+      panel.focus.current = { segment, offset: offset + 1 };
+      write(withText(segments, segment, `${text.slice(0, offset)}\n${text.slice(start + end)}`), true);
+    } else if (e.key === "Backspace" && collapsed && at === 0 && start > 0 && !disabled) {
+      e.preventDefault(); // at a line's start: joined to the line above
+      panel.focus.current = { segment, offset: offset - 1 };
+      write(withText(segments, segment, text.slice(0, offset - 1) + text.slice(offset)), true);
+    } else if (e.key === "ArrowLeft" && collapsed && at === 0 && start > 0 && plain(e)) {
+      e.preventDefault();
+      focusAt(segment, offset - 1); // the end of the line above
+    } else if (e.key === "ArrowRight" && collapsed && at === input.value.length && offset < text.length && plain(e)) {
+      e.preventDefault();
+      focusAt(segment, offset + 1); // the start of the line below
     } else if (e.key === "ArrowLeft" && collapsed && at === 0 && segment > 0) {
       e.preventDefault();
       pills.current[segment - 1]?.focus();
@@ -89,18 +124,29 @@ export function TextPills({ spec, value, literal, id, describedBy, invalid, disa
     } else if (e.key === "Backspace" && collapsed && at === 0 && segment > 0) {
       e.preventDefault(); // the pill before is focused first: a second Backspace removes it
       pills.current[segment - 1]?.focus();
+    } else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && plain(e)) {
+      // To the line above or below, its first text, as far in as the caret was in this one.
+      const row = rows[rowOf(index) + (e.key === "ArrowUp" ? -1 : 1)];
+      if (!row) return;
+      e.preventDefault();
+      const first = row[0]!.piece;
+      focusAt(first.segment, first.start + Math.min(at, first.text.length));
+    } else if ((e.key === "Home" || e.key === "End") && plain(e)) {
+      // To the line's start or end, past its pills: an input's own Home stops at the pill before it.
+      const row = rows[rowOf(index)]!;
+      const piece = e.key === "Home" ? row[0]!.piece : row.at(-1)!.piece;
+      e.preventDefault();
+      focusAt(piece.segment, piece.start + (e.key === "Home" ? 0 : piece.text.length));
     }
   };
 
   const onPillKey = (index: number) => (e: KeyboardEvent<HTMLButtonElement>) => {
     if (e.key === "ArrowLeft") {
       e.preventDefault(); // focused now, as → does: a focus request left for later would move the caret back as one types
-      inputs.current[index]?.focus();
-      inputs.current[index]?.setSelectionRange(segments.texts[index]!.length, segments.texts[index]!.length);
+      focusAt(index, segments.texts[index]!.length);
     } else if (e.key === "ArrowRight") {
       e.preventDefault();
-      inputs.current[index + 1]?.focus();
-      inputs.current[index + 1]?.setSelectionRange(0, 0);
+      focusAt(index + 1, 0);
     } else if ((e.key === "Backspace" || e.key === "Delete") && !disabled) {
       e.preventDefault();
       const { segments: next, caret } = removePill(segments, index);
@@ -112,39 +158,55 @@ export function TextPills({ spec, value, literal, id, describedBy, invalid, disa
     }
   };
 
-  const labelled = (segment: number) => (segment === 0 ? undefined : `${spec.label}, text after ${pillText(segments.pills[segment - 1]!.ref)}`);
+  /** The first input is the field's, its label naming it; one after a pill says the pill, one on a later line its line. */
+  const labelled = (index: number, row: number) => {
+    const { segment, start } = pieces[index]!;
+    if (segment === 0 && start === 0) return undefined;
+    return start === 0 ? `${spec.label}, text after ${pillText(segments.pills[segment - 1]!.ref)}` : `${spec.label}, line ${row + 1}`;
+  };
 
   const opened = panel.opened;
+  let index = -1; // each piece's input, in the order they're drawn
   const box = (
     <div
-      className={`flex min-h-11 w-full flex-wrap items-center gap-x-1 gap-y-1.5 rounded-lg border bg-surface px-3 py-2 text-body-lg ${
+      className={`flex min-h-11 w-full flex-col justify-center gap-y-1.5 rounded-lg border bg-surface px-3 py-2 text-body-lg ${
         invalid ? "border-danger" : "border-line-control"} focus-within:outline focus-within:outline-2 focus-within:outline-focus`}
     >
-      {segments.texts.map((text, segment) => (
-        <span key={`t${segment}`} className="contents">
-          <input
-            ref={(el) => void (inputs.current[segment] = el)}
-            id={segment === 0 ? id : undefined}
-            type="text" value={text} disabled={disabled} spellCheck={false}
-            aria-label={labelled(segment)} aria-describedby={segment === 0 ? describedBy : undefined}
-            aria-invalid={invalid} aria-required={segment === 0 ? spec.required && !spec.entry : undefined}
-            size={Math.max(1, text.length)}
-            onKeyDown={onTextKey(segment)}
-            onSelect={(e) => void (panel.caret.current = caretOf(segment, e.currentTarget))}
-            onChange={(e) => {
-              panel.caret.current = caretOf(segment, e.currentTarget);
-              write(withText(segments, segment, e.target.value), true);
-            }}
-            // 24 px at least, empty too: a target a pointer can take (WCAG 2.5.8; the gate found an empty one at 1 ch)
-            className={`min-h-[24px] min-w-[24px] max-w-full bg-transparent outline-none [field-sizing:content] ${segments.pills.length === 0 ? "flex-1" : ""}`}
-          />
-          {segments.pills[segment] && (
-            <Pills
-              pill={segments.pills[segment]} field={spec.pointer} index={segment} onKeyDown={onPillKey(segment)}
-              onOpen={() => panel.open({ kind: "details", index: segment })} buttonRef={(el) => void (pills.current[segment] = el)}
-            />
-          )}
-        </span>
+      {rows.map((row, r) => (
+        <div key={r} className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-1.5">
+          {row.map(({ piece, pill }, k) => {
+            const i = ++index;
+            return (
+              <span key={i} className="contents">
+                <input
+                  ref={(el) => void (inputs.current[i] = el)}
+                  id={i === 0 ? id : undefined}
+                  type="text" value={piece.text} disabled={disabled} spellCheck={false}
+                  aria-label={labelled(i, r)} aria-describedby={i === 0 ? describedBy : undefined}
+                  aria-invalid={invalid} aria-required={i === 0 ? spec.required && !spec.entry : undefined}
+                  size={Math.max(1, piece.text.length)}
+                  onKeyDown={onTextKey(i)}
+                  onSelect={(e) => void (panel.caret.current = caretOf(i, e.currentTarget))}
+                  onChange={(e) => {
+                    panel.caret.current = caretOf(i, e.currentTarget);
+                    const text = segments.texts[piece.segment]!;
+                    write(withText(segments, piece.segment, text.slice(0, piece.start) + e.target.value + text.slice(piece.start + piece.text.length)), true);
+                  }}
+                  // 24 px at least, empty too: a target a pointer can take (WCAG 2.5.8; the gate found an empty one at 1 ch).
+                  // A line's last text takes the rest of the line, where several lines are typed.
+                  className={`min-h-[24px] min-w-[24px] max-w-full bg-transparent outline-none [field-sizing:content] ${
+                    (lines ? k === row.length - 1 : segments.pills.length === 0) ? "flex-1" : ""}`}
+                />
+                {pill !== null && (
+                  <Pills
+                    pill={segments.pills[pill]!} field={spec.pointer} index={pill} onKeyDown={onPillKey(pill)}
+                    onOpen={() => panel.open({ kind: "details", index: pill })} buttonRef={(el) => void (pills.current[pill] = el)}
+                  />
+                )}
+              </span>
+            );
+          })}
+        </div>
       ))}
     </div>
   );
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 34 passed.

- [ ] **Step 5: Static checks**

Run: the frontend's static checks of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/lib/pills.ts frontend/src/lib/pills.test.ts frontend/src/routes/editor/drawer/TextPills.tsx \
  frontend/src/routes/editor/drawer/TextPills.test.tsx frontend/src/routes/editor/drawer/FieldView.tsx
git commit -m "feat(editor): text with values on several lines, as rows of the pill editor (4f-1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4f-1, milestone 2 (<date>)` to the ledger, as for milestone 1, commit it as
`docs(editor-4): 4f-1 milestone 2`, and **pause** for the owner's review.

---

# Milestone 3 — The composer

### Task 7: The composer on Setup

**Spec:** §5.1 (where it shows; Setup and Options; formulas); §5.2 (the title, the text); §5.3 (fields and links; the
link check); §5.4 (the severity); §5.8 (the fieldset, the radio group, rows named by their row); the Main, States and
OtherSteps boards.

**Files:**
- Create: `frontend/src/lib/composer.ts`, `frontend/src/routes/editor/drawer/MessageComposer.tsx`,
  `frontend/src/routes/editor/drawer/MessageComposer.test.tsx`
- Modify: `frontend/src/lib/schemaForm.ts` (`MESSAGE_PARTS`, `settingsOf`),
  `frontend/src/routes/editor/drawer/FieldView.tsx` (`Drawn`), `frontend/src/routes/editor/drawer/StepDrawer.tsx`,
  `frontend/src/routes/editor/drawer/structured.tsx` (`lineageKey` exported),
  `frontend/src/routes/editor/drawer/harness.tsx` (`showDrawer`), `frontend/src/test/nodeTypes.ts` (`messageStep`)

**Interfaces:**
- Consumes: Task 2's hint; Task 6's `Drawn { lines }`; `FieldView`, `itemOf`, `propertiesOf`, `segmentsOf`.
- Produces:
  - `schemaForm.ts`: `MESSAGE_PARTS`, `settingsOf(type, fields): { setup; message: FieldSpec[] | null; options }`;
  - `composer.ts`: `type Target`, `NAMES`, `targetOf(type)`, `optionsLine(target)`, `titleHint(target)`,
    `LINK_WORDS`, `linkProblem(value)`, `capWords(noun, max)`;
  - `FieldView`'s `Drawn` gains `control`, `parts(spec, value)`, `check(value)`, `hint`, `quiet`, `marked`, `below`;
  - `MessageComposer({ parts })`;
  - test support: `showDrawer(type, options)` (the whole `StepDrawer` over the harness's draft), `messageStep(type,
    more?, required?)` (a made-up step on the SDK's message, the hint at its root).

`settingsOf` keeps the message's parts out of the tabs' split when the root has the hint and the text (ruling 100's
fallback otherwise). `StepDrawer` shows Setup's required fields marked "(required)", then the composer; Options says
where the message is (ruling 7). The composer is a "Message" fieldset of `FieldView`s, each `drawn` its way
(rulings 6, 9–12): the severity's radio group, the title's hint, the text's lines, and the fields' and links' rows
with their count, Move up, Move down, Remove, Add and its cap. A part held as a formula, or a value the composer
can't draw (a literal list), is today's control: `FieldView` decides, as for any field.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/drawer/MessageComposer.test.tsx b/frontend/src/routes/editor/drawer/MessageComposer.test.tsx
new file mode 100644
index 00000000..7dc2f3ea
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/MessageComposer.test.tsx
@@ -0,0 +1,119 @@
+// SPDX-License-Identifier: Apache-2.0
+import { screen, waitFor, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { messageStep, typeWith } from "../../../test/nodeTypes";
+import { fakeApi, json, showDrawer } from "./harness";
+
+const SLACK = messageStep("slack.send_message");
+const SERVICENOW = messageStep("servicenow.create_incident", { urgency: { type: "integer", title: "Urgency", enum: [1, 2, 3] } });
+const EMAIL = messageStep("email.send_message", { to: { type: "array", title: "To", items: { type: "string" }, minItems: 1 } }, ["to"]);
+const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });
+const formula = (expr: string) => ({ $value: { kind: "cel", expr } });
+const fields = (n: number) => Array.from({ length: n }, (_, i) => ({ label: `Field ${i}`, value: `value ${i}` }));
+
+beforeEach(() => {
+  fakeApi({ "GET /api/v1/t/t1/connections": () => json([]), "GET /api/v1/connection-types": () => json([]) });
+});
+afterEach(() => vi.restoreAllMocks());
+
+const message = () => screen.getByRole("group", { name: "Message" });
+
+describe("the message composer (4f-1, the message composer design §5)", () => {
+  it("shows the message on Setup after the step's required fields: severity, title, text, fields, links", () => {
+    showDrawer(EMAIL);
+    expect(screen.getByRole("tab", { name: "Setup" }).getAttribute("aria-selected")).toBe("true");
+    const panel = screen.getByRole("tabpanel");
+    const labels = [...panel.querySelectorAll("label, legend")].map((l) => l.textContent);
+    expect(labels.slice(0, 2)).toEqual(["Connection", "To"]);
+    expect(labels.indexOf("Message")).toBe(2);
+    const parts = [...message().querySelectorAll<HTMLElement>(":scope > [data-pointer]")].map((part) => part.dataset.pointer);
+    expect(parts).toEqual(["/severity", "/title", "/text", "/fields", "/links"]);
+    expect(within(panel).getAllByText("(required)")).toHaveLength(3); // Connection, To and the text say it themselves
+    expect(within(message()).getByText("optional · the email's subject")).toBeTruthy();
+  });
+
+  it("keeps on Options what only the target takes, with a line saying where the message is", async () => {
+    showDrawer(SERVICENOW);
+    await userEvent.click(screen.getByRole("tab", { name: "Options" }));
+    expect(screen.getByText("The message is on Setup; what only ServiceNow takes stays here.")).toBeTruthy();
+    expect(screen.getByLabelText("Urgency")).toBeTruthy();
+    expect(screen.queryByRole("group", { name: "Message" })).toBeNull();
+  });
+
+  it("says so on Options when nothing else is there", async () => {
+    showDrawer(SLACK);
+    await userEvent.click(screen.getByRole("tab", { name: "Options" }));
+    expect(screen.getByText("The message is on Setup; what only Slack takes stays here.")).toBeTruthy();
+    expect(screen.getByText("Nothing else to set.")).toBeTruthy();
+  });
+
+  it("leaves a config with the hint but no text to the generic form (ruling 100)", () => {
+    showDrawer(typeWith({ type: "object", "x-widget": "message", properties: { title: { type: "string", title: "Title" } } }));
+    expect(screen.queryByRole("group", { name: "Message" })).toBeNull();
+  });
+
+  it("sets the severity with four choices, Info by default, and keeps its Fixed and Formula switch", async () => {
+    const f = showDrawer(SLACK);
+    const severity = within(message()).getByRole("radiogroup", { name: "Severity" });
+    expect(within(severity).getAllByRole("radio").map((r) => r.closest("label")!.textContent)).toEqual(["Info", "Success", "Warning", "Critical"]);
+    expect(within(severity).getByRole<HTMLInputElement>("radio", { name: "Info" }).checked).toBe(true);
+    expect(f.config()).toEqual({}); // the default shown, nothing written
+    await userEvent.click(within(severity).getByRole("radio", { name: "Warning" }));
+    expect(f.config()).toEqual({ severity: "warning" });
+    expect(within(within(message()).getByRole("group", { name: "How Severity is set" })).getByRole("button", { name: "Formula" })).toBeTruthy();
+  });
+
+  it("writes the text on several lines", async () => {
+    const f = showDrawer(SLACK, { config: { text: "AP down" } });
+    await userEvent.type(within(message()).getByLabelText("Text"), "{Enter}at HQ");
+    expect(f.config()).toEqual({ text: "AP down\nat HQ" });
+  });
+
+  it("adds fields up to 25, each row named by its number, and says why another can't be added", async () => {
+    // 25 rows are many: found by text and attributes, as role queries over them take seconds in jsdom.
+    const f = showDrawer(SLACK, { config: { text: "x", fields: fields(24) } });
+    const addButton = () => within(message()).getByText("＋ Add a field").closest("button")!;
+    expect(within(message()).getByText("24 of 25")).toBeTruthy();
+    expect(message().querySelector('[role="group"][aria-label="Field 24"]')).not.toBeNull();
+    await userEvent.click(addButton());
+    expect((f.config().fields as unknown[]).length).toBe(25);
+    expect(within(message()).getByText("25 of 25")).toBeTruthy();
+    expect(addButton().disabled).toBe(true);
+    const cap = within(message()).getByText("A message takes up to 25 fields: remove one to add another.");
+    expect(addButton().getAttribute("aria-describedby")).toBe(cap.id);
+    expect(within(message()).getByLabelText("Field 25 label")).toBeTruthy();
+    expect(within(message()).queryByText("Edit as JSON")).toBeNull();
+  });
+
+  it("moves a link's row and removes one, each control named by its row", async () => {
+    const links = [{ label: "One", url: "https://a.test" }, { label: "Two", url: "https://b.test" }];
+    const f = showDrawer(SLACK, { config: { text: "x", links } });
+    expect(within(message()).getByText("2 of 10")).toBeTruthy();
+    await userEvent.click(within(message()).getByRole("button", { name: "Move down: link 1" }));
+    expect(f.config().links).toEqual([links[1], links[0]]);
+    await userEvent.click(within(message()).getByRole("button", { name: "Remove link 2" }));
+    expect(f.config().links).toEqual([links[1]]);
+    await waitFor(() => expect(document.activeElement).toBe(within(message()).getByRole("button", { name: "＋ Add a link" })));
+  });
+
+  it("checks a link's address as it's typed, when it starts with written text", async () => {
+    const f = showDrawer(SLACK, { config: { text: "x", links: [{ label: "Runbook", url: "" }] } });
+    const address = within(message()).getByLabelText("Link 1 address");
+    await userEvent.type(address, "ftp://x");
+    const said = within(message()).getByText("A link's address starts with http:// or https://.");
+    expect(address.getAttribute("aria-describedby")).toContain(said.id);
+    expect(address.getAttribute("aria-invalid")).toBe("true");
+    f.replace({ text: "x", links: [{ label: "Runbook", url: template({ ref: "steps.check.output.url" }, { text: "/runbook" }) }] });
+    expect(within(message()).queryByText("A link's address starts with http:// or https://.")).toBeNull();
+    f.replace({ text: "x", links: [{ label: "Runbook", url: "https://a.test" }] });
+    expect(within(message()).queryByText("A link's address starts with http:// or https://.")).toBeNull();
+  });
+
+  it("keeps a list a formula computes as a formula, and one it can't draw as today's control", () => {
+    showDrawer(SLACK, { config: { text: "x", fields: formula("steps.check.output.fields"), links: { $value: { kind: "literal", value: [] } } } });
+    expect(within(message()).getByRole("textbox", { name: "Fields" })).toBeTruthy();
+    expect(within(message()).queryByRole("button", { name: "＋ Add a field" })).toBeNull();
+    expect(within(message()).queryByRole("button", { name: "＋ Add a link" })).toBeNull();
+  });
+});
diff --git a/frontend/src/routes/editor/drawer/harness.tsx b/frontend/src/routes/editor/drawer/harness.tsx
index 451bc709..10ee1b56 100644
--- a/frontend/src/routes/editor/drawer/harness.tsx
+++ b/frontend/src/routes/editor/drawer/harness.tsx
@@ -15,8 +15,9 @@ import {
   applyAll, applyUnapplied, baseOf, droppedWhy, isStale, lineageOf, unappliedId, within, type Unapplied, type UnappliedKind,
 } from "../../../lib/unapplied";  // prettier-ignore
 import type { Diagnostic, Expression, GraphDoc, NodeType } from "../../../lib/workflows";
-import { DrawerContext, type Drawer } from "./context";
+import { DrawerContext, useDrawer, type Drawer } from "./context";
 import { FieldView } from "./FieldView";
+import { StepDrawer } from "./StepDrawer";
 
 export const NODE_ID = "00000000-0000-4000-8000-000000000001";
 export type Edit = { path: Path; value: unknown; mark: string | undefined };
@@ -182,6 +183,21 @@ export function showFields(type: NodeType, options: Options = {}, children?: Rea
   };
 }
 
+/** The step's whole drawer, its settings on their tabs, over the same one-step draft (4f-1: where the composer shows). */
+export const showDrawer = (type: NodeType, options: Options = {}) => showFields(type, options, <InDrawer />);
+
+function InDrawer() {
+  const d = useDrawer();
+  const none = () => undefined;
+  return (
+    <StepDrawer
+      node={d.node} type={d.type} tenantId={d.tenantId} workflowId={d.workflowId} revision={d.revision} steps={d.steps} ports={[]}
+      problems={d.problems} expressions={d.expressions} editable={d.editable} adds={[]} actions={d} note={null} focusField={null}
+      onAdd={none} onDelete={none} onConnectPort={none} onPlace={none} onNudge={none} onClose={none}
+    />
+  );  // prettier-ignore
+}
+
 /** A problem the server found at a field of the step. */
 export const problem = (field: string, message: string): Diagnostic => ({
   code: "config.invalid", severity: "error", message, fix: null, node: NODE_ID, field,
diff --git a/frontend/src/test/nodeTypes.ts b/frontend/src/test/nodeTypes.ts
index b5710d94..88172881 100644
--- a/frontend/src/test/nodeTypes.ts
+++ b/frontend/src/test/nodeTypes.ts
@@ -95,3 +95,31 @@ export const REMOTE = typeWith({
     note: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Note" },
   },
 }, { ref: "acme.sites@1", type: "acme.sites", title: "Sites", options: ["site_id"], credentials: ["acme"] });  // prettier-ignore
+
+const MESSAGE_DEFS = {
+  MessageField: {
+    type: "object", additionalProperties: false, title: "MessageField", required: ["label", "value"],
+    properties: { label: { type: "string", title: "Label", minLength: 1, maxLength: 200 }, value: { type: "string", title: "Value", maxLength: 10_000 } },
+  },
+  Link: {
+    type: "object", additionalProperties: false, title: "Link", required: ["label", "url"],
+    properties: { label: { type: "string", title: "Label", minLength: 1, maxLength: 200 }, url: { type: "string", title: "Url", maxLength: 2000 } },
+  },
+  Severity: { type: "string", title: "Severity", enum: ["info", "success", "warning", "critical"] },
+};  // prettier-ignore
+
+/** A step that sends a message (4f-1): its config the SDK's message as `class SendConfig(Message)` makes it, the
+ * composer's hint at its root, with a connection and `more`. Made up (D24), named as the target to preview. */
+export const messageStep = (type: string, more: Record<string, unknown> = {}, required: string[] = []): NodeType =>
+  typeWith({
+    type: "object", additionalProperties: false, "x-widget": "message", $defs: MESSAGE_DEFS, required: ["text", "connection", ...required],
+    properties: {
+      title: { anyOf: [{ type: "string", maxLength: 1000 }, { type: "null" }], default: null, title: "Title" },
+      text: { type: "string", title: "Text", minLength: 1, maxLength: 40_000 },
+      fields: { type: "array", title: "Fields", maxItems: 25, items: { $ref: "#/$defs/MessageField" } },
+      links: { type: "array", title: "Links", maxItems: 10, items: { $ref: "#/$defs/Link" } },
+      severity: { $ref: "#/$defs/Severity", default: "info" },
+      connection: { type: "string", format: "uuid", title: "Connection", "x-dewpoint-literal": true, "x-dewpoint-connection": type.split(".")[0] },
+      ...more,
+    },
+  }, { ref: `${type}@1`, type, title: "Send a message", credentials: [type.split(".")[0]!] });  // prettier-ignore
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/drawer/MessageComposer.test.tsx
src/routes/editor/drawer/FieldView.test.tsx src/routes/editor/drawer/structured.test.tsx`

Expected: FAIL, 9 failed and 62 passed: there's no "Message" group (`Unable to find an accessible element with the role
"group" and name "Message"`, six tests), Setup puts the text first (`expected [ 'Text', 'Connection' ] to deeply equal [
'Connection', 'To' ]`), and Options says nothing of the message (two tests). "leaves a config with the hint but no text
to the generic form" passes at once (ruling 100); so do `FieldView`'s and `structured`'s own tests.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/composer.ts b/frontend/src/lib/composer.ts
new file mode 100644
index 00000000..0c3bde93
--- /dev/null
+++ b/frontend/src/lib/composer.ts
@@ -0,0 +1,56 @@
+// SPDX-License-Identifier: Apache-2.0
+// What the message composer knows of the steps that send a message (4f-1, the message composer design §5): which
+// target a step sends to, its name in the composer's words, what its title becomes there, and a link's address checked
+// as it's typed. A step it doesn't know (a third party's on the SDK's message) gets the composer and nothing more (§8,
+// call 2).
+import { segmentsOf } from "./pills";
+import type { NodeType } from "./workflows";
+
+export type Target = "slack" | "teams" | "google_chat" | "webhook" | "email" | "syslog" | "pagerduty" | "servicenow";
+
+const STEPS = new Map<string, Target>([
+  ["slack.send_message", "slack"],
+  ["teams.send_message", "teams"],
+  ["google_chat.send_message", "google_chat"],
+  ["webhook.send_message", "webhook"],
+  ["email.send_message", "email"],
+  ["syslog.send_message", "syslog"],
+  ["pagerduty.trigger_alert", "pagerduty"],
+  ["servicenow.create_incident", "servicenow"],
+]);
+
+export const NAMES: Record<Target, string> = {
+  slack: "Slack", teams: "Teams", google_chat: "Google Chat", webhook: "the webhook", email: "email", syslog: "syslog",
+  pagerduty: "PagerDuty", servicenow: "ServiceNow",
+};  // prettier-ignore
+
+/** What the title becomes, where that's more than a title (§5.2). */
+const TITLES: Partial<Record<Target, string>> = {
+  email: "the email's subject",
+  pagerduty: "the alert's summary",
+  servicenow: "the incident's short description",
+};
+
+export const targetOf = (type: NodeType | undefined): Target | null => (type ? (STEPS.get(type.type) ?? null) : null);
+
+/** Options' line on a message step: the message is on Setup (§5.1). */
+export const optionsLine = (target: Target | null): string =>
+  `The message is on Setup; what only ${target ? NAMES[target] : "this step"} takes stays here.`;
+
+/** The title's hint: optional, and what it becomes where it matters (§5.2). */
+export const titleHint = (target: Target | null): string => {
+  const becomes = target ? TITLES[target] : undefined;
+  return becomes ? `optional · ${becomes}` : "optional";
+};
+
+export const LINK_WORDS = "A link's address starts with http:// or https://.";
+
+/** What's wrong with a link's address that starts with written text: the SDK's link starts with http:// or https://
+ * (sdk/messages.py's LINK_URL). One that starts with a value, or a formula, is checked when the step runs (§5.3). */
+export function linkProblem(value: unknown): string | null {
+  const start = segmentsOf(value)?.texts[0] ?? "";
+  return start !== "" && !/^https?:\/\//.test(start) ? LINK_WORDS : null;
+}
+
+/** Why another field or link can't be added (§5.3). */
+export const capWords = (noun: "field" | "link", max: number): string => `A message takes up to ${max} ${noun}s: remove one to add another.`;
diff --git a/frontend/src/lib/schemaForm.ts b/frontend/src/lib/schemaForm.ts
index 21762bd2..922212e7 100644
--- a/frontend/src/lib/schemaForm.ts
+++ b/frontend/src/lib/schemaForm.ts
@@ -198,6 +198,20 @@ export const tabsOf = (fields: FieldSpec[]) => ({
   options: fields.filter((f) => !f.required),
 });
 
+/** The message's parts, in the composer's order (4f-1, the message composer design §5.1). */
+export const MESSAGE_PARTS = ["severity", "title", "text", "fields", "links"];
+
+/** A step's settings on their tabs. With the composer's hint at its config's root (`x-widget: "message"`) and the
+ * message's text, the message's parts are drawn together on Setup, after its required fields, optional ones included
+ * (ruling 98, amended for a message); without its text, the generic form (ruling 100). */
+export function settingsOf(type: NodeType, fields: FieldSpec[]): { setup: FieldSpec[]; message: FieldSpec[] | null; options: FieldSpec[] } {
+  const message =
+    type.config_schema["x-widget"] === "message" && fields.some((f) => f.name === "text")
+      ? MESSAGE_PARTS.flatMap((name) => fields.filter((f) => f.name === name))
+      : null;
+  return { ...tabsOf(message ? fields.filter((f) => !message.includes(f)) : fields), message };
+}
+
 /** Where the engine takes a fixed value: not in a sensitive field (sensitive.literal), and `literal` among its kinds. */
 export const canFixed = (f: FieldSpec): boolean => !f.sensitive && (f.kinds === null || f.kinds.includes("literal"));
 
diff --git a/frontend/src/routes/editor/drawer/FieldView.tsx b/frontend/src/routes/editor/drawer/FieldView.tsx
index 2943509c..9dba4234 100644
--- a/frontend/src/routes/editor/drawer/FieldView.tsx
+++ b/frontend/src/routes/editor/drawer/FieldView.tsx
@@ -92,9 +92,19 @@ const startMode = (spec: FieldSpec, value: unknown): Mode =>
   : value !== undefined && value !== null ? "fixed"
   : startsAsFormula(spec) ? "formula" : "fixed";  // prettier-ignore
 
-/** How the message composer draws one of its parts (4f-1, the message composer design §5): the text on several lines. */
+/** How the message composer draws one of its parts (4f-1, the message composer design §5): its own control (the
+ * severity's choices) or its own rows (the fields', the links'), the text on several lines, a check said as it's typed
+ * (a link's address), its hint in place of the schema's, without the note on pills (`quiet`), "(required)" said at the
+ * top level (`marked`: Setup holds optional parts too), and what's said under it. */
 export interface Drawn {
+  control?: Control;
+  parts?: (spec: FieldSpec, value: unknown) => ReactNode;
   lines?: boolean;
+  check?: (value: unknown) => string | null;
+  hint?: string | null;
+  quiet?: boolean;
+  marked?: boolean;
+  below?: ReactNode;
 }
 
 export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn }) {
@@ -180,7 +190,9 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
   const json = asJson || held?.kind === "json" || kind === "unknown" || (kind === "literal" && isContainer(spec.base));
   const container = mode === "fixed" && fixedOk && !computed && !hidden && !json && isContainer(spec.base);
   const problems = problemsAt(drawer.problems, spec.pointer, container ? new Set(partNames(spec, fixed)) : null);
-  const required = spec.required && !spec.entry && spec.path.length > 1;
+  const required = spec.required && !spec.entry && (spec.path.length > 1 || drawn.marked === true);
+  const hint = drawn.hint !== undefined ? drawn.hint : spec.hint;
+  const checked = drawn.check?.(value) ?? null; // said where a refusal would be, after it
   // A list's item or a map's entry, emptied, keeps its place, blank: never missing on its own (the final review).
   const missing = spec.required && !spec.entry && touched && (empty || value === "") ? "Required" : null;
   const switchTo = (next: Mode) =>
@@ -236,7 +248,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
           ＋ Data
         </Button>
       )}
-      {mode === "fixed" && fixedOk && !computed && !hidden && kind === null && isContainer(spec.base) && !spec.holdsSensitive && (
+      {mode === "fixed" && fixedOk && !computed && !hidden && kind === null && isContainer(spec.base) && !spec.holdsSensitive && !drawn.parts && (
         // Pressed as Segmented's options are, by weight and fill from its tokens, while it's on (the owner's ruling O1).
         <Button
           size="sm" aria-pressed={json} onClick={toggleJson}
@@ -278,8 +290,8 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
       )}
     </>
   );
-  const frame = (control: (c: Described) => ReactNode, hint: string | null = spec.hint, below?: ReactNode) => (
-    <FieldFrame label={spec.label} required={required} hint={hint} local={stale ? STALE : (held?.why ?? local ?? missing)} problems={problems} actions={actions} below={below}>
+  const frame = (control: (c: Described) => ReactNode, said: string | null = hint, below: ReactNode = drawn.below) => (
+    <FieldFrame label={spec.label} required={required} hint={said} local={stale ? STALE : (held?.why ?? local ?? missing ?? checked)} problems={problems} actions={actions} below={below}>
       {control}
     </FieldFrame>
   );
@@ -287,7 +299,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
     ? JsonControl
     : spec.port
       ? PortControl
-      : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
+      : (drawn.control ?? controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
   const Held = held && held.kind !== "template" ? heldControl(held.kind, spec) : null;
   // A decision that reads sensitive data (the server's taint.undeclassified, under its field): the list where it's
   // declassified is a click away (4c-2b, the builder's and the formula's boards).
@@ -309,7 +321,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
     says = runs !== null;
     body = (
       <GroupFrame
-        label={spec.label} required={required} hint={spec.hint} local={held?.why ?? local ?? missing} problems={problems} actions={actions}
+        label={spec.label} required={required} hint={hint} local={held?.why ?? local ?? missing} problems={problems} actions={actions}
         below={<>{runs && <p className="text-small text-muted">{runs}</p>}{declassifiable}</>}
       >
         <ConditionBuilder key={generation} spec={spec} value={value} disabled={disabled} onChange={write} />
@@ -318,8 +330,8 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
   } else if (held?.kind === "template" || (mode === "fixed" && asText && !hidden && !(held && Held))) {
     // Text with data pills: what's held, or the value, as text and pills (4c-2b).
     // "/" and "＋ Data" work where the person may edit the draft: the note says them only there (#85).
-    const pillsNote = disabled || drawer.revision === null ? PILLS_SEEN : drawn.lines ? LINES_NOTE : PILLS_NOTE;
-    body = frame(textPills, joined(spec.hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, pillsNote));
+    const pillsNote = drawn.quiet ? null : disabled || drawer.revision === null ? PILLS_SEEN : drawn.lines ? LINES_NOTE : PILLS_NOTE;
+    body = frame(textPills, joined(hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, pillsNote));
   } else if (held && Held) {
     // What's held shows first, before what the value under it has become (a reference, a hidden secret, another
     // mode): it stays visible, and recoverable, until it's applied or discarded (the review of revision 3).
@@ -330,7 +342,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
           literal={held.literal ?? false} disabled={disabled} onChange={held.kind === "formula" ? write : writeFixed}
         />
       ),
-      joined(spec.hint, held.literal ? LITERAL_NOTE : held.kind === "json" ? JSON_NOTE : null),
+      joined(hint, held.literal ? LITERAL_NOTE : held.kind === "json" ? JSON_NOTE : null),
     );  // prettier-ignore
   } else if (hidden) {
     body = frame((c) => (
@@ -351,7 +363,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
           {computed ? referenceText(value) : empty ? "Not set" : "A value this field doesn't take"}
         </output>
       ),
-      joined(spec.hint, NEITHER),
+      joined(hint, NEITHER),
     );
   } else if (computed) {
     body = frame((c) => (
@@ -372,7 +384,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
     says = runs !== null;
     body = frame(
       (c) => <FormulaControl key={generation} {...c} spec={spec} value={value} literal={false} disabled={disabled} onChange={write} />,
-      spec.hint,
+      hint,
       <>
         {runs && <p className="text-small text-muted">{runs}</p>}
         {declassifiable}
@@ -380,8 +392,8 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
     );
   } else if (container) {
     body = (
-      <GroupFrame label={spec.label} required={required} hint={spec.hint} local={local ?? missing} problems={problems} actions={actions}>
-        <ContainerParts spec={spec} value={fixed} />
+      <GroupFrame label={spec.label} required={required} hint={hint} local={local ?? missing} problems={problems} actions={actions}>
+        {drawn.parts ? drawn.parts(spec, fixed) : <ContainerParts spec={spec} value={fixed} />}
       </GroupFrame>
     );
   } else if (spec.holdsSensitive && Control === JsonControl) {
@@ -396,7 +408,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
       (c) => (
         <Control key={generation} {...c} spec={spec} value={fixed} literal={kind === "literal"} disabled={disabled} onChange={writeFixed} />
       ),
-      joined(spec.hint, note),
+      joined(hint, note),
     );
   }
   // Said here, so the drawer's list of how its formulas run leaves it out (the owner's ruling O4).
diff --git a/frontend/src/routes/editor/drawer/MessageComposer.tsx b/frontend/src/routes/editor/drawer/MessageComposer.tsx
new file mode 100644
index 00000000..f5f81c4e
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/MessageComposer.tsx
@@ -0,0 +1,133 @@
+// SPDX-License-Identifier: Apache-2.0
+// The message composer (4f-1, the message composer design §5): a step built on the SDK's message has it written in one
+// place on Setup, the "Message" fieldset: its severity as four choices, its title, its text on several lines, its fields
+// and links as numbered rows. Each part is the drawer's own field (FieldView): what's typed, held, refused or computed by
+// a formula behaves as everywhere in the drawer, and a part it can't draw as its own shows today's control (ledger 102).
+import { useId, useRef, type ReactNode } from "react";
+import { Button } from "../../../components/Button";
+import { capWords, linkProblem, targetOf, titleHint } from "../../../lib/composer";
+import { itemOf, propertiesOf, type FieldSpec } from "../../../lib/schemaForm";
+import { useDrawer } from "./context";
+import { FieldView, type Drawn } from "./FieldView";
+import type { ControlProps } from "./scalars";
+import { lineageKey } from "./structured";
+
+const SEVERITIES: Record<string, string> = { info: "Info", success: "Success", warning: "Warning", critical: "Critical" };
+
+/** The severity as four choices in a row, two rows of two at 320 px (§5.4); unset, the model's default is chosen. */
+function SeverityControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
+  const choices = Array.isArray(spec.schema.enum) ? (spec.schema.enum as unknown[]).filter((c): c is string => typeof c === "string") : [];
+  const current = typeof value === "string" ? value : typeof spec.schema.default === "string" ? spec.schema.default : "";
+  return (
+    // Focusable from a script, so a Go to lands on it (StepDrawer's locate).
+    <div
+      id={id} role="radiogroup" aria-label={spec.label} aria-describedby={describedBy} aria-invalid={invalid} tabIndex={-1}
+      className="grid grid-cols-2 gap-2 sm:grid-cols-4"
+    >
+      {choices.map((choice) => (
+        <label key={choice} className="flex min-h-11 items-center gap-2 rounded-lg border border-line-control px-3 text-body sm:min-h-6">
+          <input type="radio" name={id} value={choice} checked={current === choice} disabled={disabled} onChange={() => onChange(choice, false)} />
+          {SEVERITIES[choice] ?? choice}
+        </label>
+      ))}
+    </div>
+  );  // prettier-ignore
+}
+
+const asList = (v: unknown): unknown[] => (Array.isArray(v) ? [...(v as unknown[])] : []);
+
+/** The fields' or the links' rows (§5.3): how many of the most, each row's label and value (or address) taking values,
+ * its Move up, Move down and Remove named by its number, and Add, disabled at the most with why. */
+function Rows({ spec, value, noun }: { spec: FieldSpec; value: unknown; noun: "field" | "link" }) {
+  const drawer = useDrawer();
+  const add = useRef<HTMLButtonElement>(null);
+  const capId = useId();
+  const items = asList(value);
+  const lineage = lineageKey(value);
+  const max = typeof spec.schema.maxItems === "number" ? spec.schema.maxItems : Infinity;
+  const full = items.length >= max;
+  const Noun = noun === "field" ? "Field" : "Link";
+  // Each changes the list's shape: the edits typed inside are applied first, or it waits (ruling 18).
+  const move = (from: number, to: number) =>
+    drawer.restructure(spec.pointer, {
+      path: spec.path,
+      make: (list) => {
+        const next = asList(list);
+        next.splice(to, 0, ...next.splice(from, 1));
+        return next;
+      },
+    });
+  const remove = (index: number) => {
+    if (drawer.restructure(spec.pointer, { path: [...spec.path, index], make: () => undefined }) !== null) return;
+    requestAnimationFrame(() => add.current?.focus()); // its controls are gone: focus goes to Add
+  };
+  const append = () => drawer.restructure(spec.pointer, { path: spec.path, make: (list) => [...asList(list), {}] });
+  return (
+    <>
+      {Number.isFinite(max) && <p className="text-small text-muted">{items.length} of {max}</p>}
+      {items.map((_, i) => {
+        const [label, second] = propertiesOf(itemOf(spec, i));
+        const row = `${noun} ${i + 1}`;
+        return (
+          <div key={i} role="group" aria-label={`${Noun} ${i + 1}`} className="flex min-w-0 flex-col gap-2">
+            <div className="grid min-w-0 gap-2 sm:grid-cols-2">
+              {label && <FieldView key={`${lineage}:label`} spec={{ ...label, label: `${Noun} ${i + 1} label` }} drawn={{ hint: null, quiet: true }} />}
+              {second && (
+                <FieldView
+                  key={`${lineage}:${second.name}`} spec={{ ...second, label: `${Noun} ${i + 1} ${noun === "field" ? "value" : "address"}` }}
+                  drawn={{ hint: null, quiet: true, check: noun === "link" ? linkProblem : undefined }}
+                />
+              )}
+            </div>
+            {drawer.editable && (
+              <div className="flex flex-wrap gap-2">
+                <Button size="sm" aria-label={`Move up: ${row}`} disabled={i === 0} onClick={() => move(i, i - 1)}>Move up</Button>
+                <Button size="sm" aria-label={`Move down: ${row}`} disabled={i === items.length - 1} onClick={() => move(i, i + 1)}>
+                  Move down
+                </Button>
+                <Button size="sm" variant="danger-outline" aria-label={`Remove ${row}`} onClick={() => remove(i)}>Remove</Button>
+              </div>
+            )}
+          </div>
+        );  // prettier-ignore
+      })}
+      {drawer.editable && (
+        <>
+          <Button ref={add} data-add size="sm" className="self-start" disabled={full} aria-describedby={full ? capId : undefined} onClick={append}>
+            ＋ Add a {noun}
+          </Button>
+          {full && <p id={capId} className="text-small text-muted">{capWords(noun, max)}</p>}
+        </>
+      )}
+    </>
+  );  // prettier-ignore
+}
+
+export function MessageComposer({ parts }: { parts: FieldSpec[] }) {
+  const drawer = useDrawer();
+  const target = targetOf(drawer.type);
+  const drawnFor = (name: string): Drawn => {
+    switch (name) {
+      case "severity":
+        return { control: SeverityControl, marked: true };
+      case "title":
+        return { hint: titleHint(target), quiet: true, marked: true };
+      case "text":
+        return { lines: true, marked: true };
+      case "fields":
+        return { parts: (spec, value): ReactNode => <Rows spec={spec} value={value} noun="field" />, marked: true };
+      case "links":
+        return { parts: (spec, value): ReactNode => <Rows spec={spec} value={value} noun="link" />, marked: true };
+      default:
+        return {};
+    }
+  };
+  return (
+    <fieldset className="flex min-w-0 flex-col gap-4">
+      <legend className="mb-1 text-body font-semibold">Message</legend>
+      {parts.map((part) => (
+        <FieldView key={part.pointer} spec={part} drawn={drawnFor(part.name)} />
+      ))}
+    </fieldset>
+  );
+}
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.tsx b/frontend/src/routes/editor/drawer/StepDrawer.tsx
index 58053c10..19e4f1ba 100644
--- a/frontend/src/routes/editor/drawer/StepDrawer.tsx
+++ b/frontend/src/routes/editor/drawer/StepDrawer.tsx
@@ -1,13 +1,15 @@
 // SPDX-License-Identifier: Apache-2.0
 // A step's drawer (4c-1, §10.3; it replaces 4b's panel, ruling 2). At the top: its key, its type, how it runs and what
 // a failure does. Then the problems that belong to no field. Then its settings on two tabs, generated from its type's
-// schema, the required ones on Setup and the rest on Options (ruling 3). Then how its formulas run, and, for an
+// schema, the required ones on Setup and the rest on Options (ruling 3); a message, written in the composer on Setup
+// (4f-1). Then how its formulas run, and, for an
 // editor, 4b's actions: its "+" twins (WCAG 2.5.8), where it sits (2.5.7), its edges. Escape closes it as Close does
 // and gives focus back to the step. What its fields do to the draft goes through `actions`, the editor's (ruling 18).
 import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import { Tabs } from "../../../components/Tabs";
-import { fieldsOf, tabsOf, type FieldSpec } from "../../../lib/schemaForm";
+import { optionsLine, targetOf } from "../../../lib/composer";
+import { fieldsOf, settingsOf, type FieldSpec } from "../../../lib/schemaForm";
 import type { UnappliedKind } from "../../../lib/unapplied";
 import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";
 import type { ItemAction } from "../items";
@@ -16,6 +18,7 @@ import { DrawerContext, problemsAt, segment, type DrawerActions } from "./contex
 import { ErrorHandling, chipText } from "./ErrorHandling";
 import { FieldView } from "./FieldView";
 import { KeyField } from "./KeyField";
+import { MessageComposer } from "./MessageComposer";
 
 const EFFECTS: Record<NodeType["side_effect"], string> = {
   none: "Changes nothing",
@@ -108,8 +111,9 @@ export function StepDrawer({
     if (!focusField) heading.current?.focus();
   }, [node.id]);
   const fields = useMemo(() => (type ? fieldsOf(type) : []), [type]);
-  const { setup, options } = tabsOf(fields);
-  const [tab, setTab] = useState<Tab>(result ? "result" : test && testAt ? "test" : setup.length > 0 ? "setup" : "options");
+  const { setup, message, options } = type ? settingsOf(type, fields) : { setup: [], message: null, options: [] };
+  const onSetup = [...setup, ...(message ?? [])]; // what Setup shows: a message's parts too
+  const [tab, setTab] = useState<Tab>(result ? "result" : test && testAt ? "test" : onSetup.length > 0 ? "setup" : "options");
   useEffect(() => {
     if (test && testAt) setTab("test");
   }, [testAt]);
@@ -124,7 +128,7 @@ export function StepDrawer({
     if (focusField.kind === "limit") setHandling(true);
     else if (focusField.kind !== "key") {
       const first = focusField.pointer.split("/")[1] ?? "";
-      if (setup.some((f) => segment(f.name) === first)) setTab("setup");
+      if (onSetup.some((f) => segment(f.name) === first)) setTab("setup");
       else if (options.some((f) => segment(f.name) === first)) setTab("options");
     }
     pending.current = { pointer: focusField.pointer, kind: focusField.kind };
@@ -253,7 +257,11 @@ export function StepDrawer({
                 content: !type ? (
                   UNKNOWN
                 ) : fields.length > 0 ? (
-                  [...setup, ...options].map((f) => <FieldView key={f.pointer} spec={f} />)
+                  <>
+                    {setup.map((f) => <FieldView key={f.pointer} spec={f} />)}
+                    {message && <MessageComposer parts={message} />}
+                    {options.map((f) => <FieldView key={f.pointer} spec={f} />)}
+                  </>
                 ) : (
                   <p className="text-small text-muted">This step has nothing to set up.</p>
                 ),
@@ -272,8 +280,14 @@ export function StepDrawer({
             tabs={[
               {
                 value: "setup",
-                label: tabLabel("Setup", counted(mine, setup)),
-                content: setup.length > 0 ? (
+                label: tabLabel("Setup", counted(mine, onSetup)),
+                content: message ? (
+                  // Each says whether it's required: Setup holds the message's optional parts too (4f-1).
+                  <>
+                    {setup.map((f) => <FieldView key={f.pointer} spec={f} drawn={{ marked: true }} />)}
+                    <MessageComposer parts={message} />
+                  </>
+                ) : setup.length > 0 ? (
                   <>
                     <p className="text-small text-muted">Each of these is required.</p>
                     {setup.map((f) => <FieldView key={f.pointer} spec={f} />)}
@@ -285,9 +299,14 @@ export function StepDrawer({
               {
                 value: "options",
                 label: tabLabel("Options", counted(mine, options)),
-                content: options.length > 0
-                  ? options.map((f) => <FieldView key={f.pointer} spec={f} />)
-                  : <p className="text-small text-muted">Nothing else to set.</p>,
+                content: (
+                  <>
+                    {message && <p className="text-small text-muted">{optionsLine(targetOf(type))}</p>}
+                    {options.length > 0
+                      ? options.map((f) => <FieldView key={f.pointer} spec={f} />)
+                      : <p className="text-small text-muted">Nothing else to set.</p>}
+                  </>
+                ),
               },
               ...(test ? [{ value: "test" as const, label: "Test", content: test }] : []),
             ]}
diff --git a/frontend/src/routes/editor/drawer/structured.tsx b/frontend/src/routes/editor/drawer/structured.tsx
index 9a7ad69b..bfcf39dc 100644
--- a/frontend/src/routes/editor/drawer/structured.tsx
+++ b/frontend/src/routes/editor/drawer/structured.tsx
@@ -39,7 +39,7 @@ const asList = (v: unknown): unknown[] => (Array.isArray(v) ? [...(v as unknown[
 // (as JSON, "Required", its mode) never passes to the item that takes its place (#73).
 const lineages = new WeakMap<object, number>();
 let lineageCount = 0;
-function lineageKey(list: unknown): string {
+export function lineageKey(list: unknown): string {
   if (!Array.isArray(list)) return "none";
   const root = rootOf(list);
   let n = lineages.get(root);
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 71 passed.

- [ ] **Step 5: Static checks**

Run: the frontend's static checks of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/composer.ts frontend/src/lib/schemaForm.ts frontend/src/routes/editor/drawer \
  frontend/src/test/nodeTypes.ts
git commit -m "feat(editor): the message composer on a message step's Setup (4f-1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The previews, and what a target would cut

**Spec:** §5.5 (Slack, Teams, Google Chat; the webhook's JSON; the no-preview lines; what a target would cut; never
announced); §5.2 (Slack's count under the text); §5.1 (a formula part, "Computed when the step runs"); the Previews,
States, MoreStates and OtherSteps boards.

**Files:**
- Create: `frontend/src/routes/editor/drawer/MessagePreview.tsx`,
  `frontend/src/routes/editor/drawer/MessagePreview.test.tsx`,
  `frontend/src/lib/composer.test.ts`
- Modify: `frontend/src/lib/composer.ts`, `frontend/src/routes/editor/drawer/MessageComposer.tsx`,
  `frontend/src/routes/editor/drawer/FieldView.tsx` (`Drawn { warn }`),
  `frontend/src/routes/editor/drawer/FieldFrame.tsx`
  (a warning note)

**Interfaces:**
- Consumes: Task 4's `slack`, `teams`, `googleChat`, `fitted`, `SLACK`, budgets; Task 7's `targetOf`, `NAMES`.
- Produces (`composer.ts`): `COMPUTED`, `PLACEHOLDER`, `sourceText(path)`, `interface Draft { shown; bare; says;
  computed }`, `draftOf(config): Draft`, `cutName(name)`, `cutWords(target, draft): string[]`,
  `slackCount(draft)`, `cutsText(target, draft)`; `MessagePreview({ target, draft })`; `FieldFrame`'s `warn`.

`draftOf` reads the config as the composer shows it: each value a placeholder character (ruling 14) whose words are
where it comes from (ruling 13), a part a formula gives whole one placeholder, and the message without them for the
cut maths. The preview renders the mirror's body for the placeholder message and draws it in the app's tokens
(ruling 16): Slack's sections, fields two to a row, buttons and context; Teams' runs and actions; Google Chat's bold
and linked words; the webhook's JSON. Under it, what the target would cut; under the text, Slack's count, or the
warning (ruling 15), linked to the text.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/composer.test.ts b/frontend/src/lib/composer.test.ts
new file mode 100644
index 00000000..caa35458
--- /dev/null
+++ b/frontend/src/lib/composer.test.ts
@@ -0,0 +1,101 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import { COMPUTED, cutName, cutWords, draftOf, slackCount, sourceText } from "./composer";
+
+const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });
+const ref = (path: string) => ({ $value: { kind: "ref", path } });
+const formula = (expr: string) => ({ $value: { kind: "cel", expr } });
+/** A draft's text with each placeholder written as {what it says}. */
+const said = (text: string, says: string[]) => [...text].map((c) => (c.codePointAt(0)! >= 0xf0000 ? `{${says[c.codePointAt(0)! - 0xf0000]}}` : c)).join("");
+
+describe("where a value comes from, as a preview says it", () => {
+  it("names a step's output by the step, and any other root by itself", () => {
+    expect(sourceText("steps.check.output.site")).toBe("check.site");
+    expect(sourceText("trigger.events[0].ap_name")).toBe("trigger.events[0].ap_name");
+    expect(sourceText("steps.check.output[0].name")).toBe("check[0].name");
+    expect(sourceText("run.now")).toBe("run.now");
+    expect(sourceText("vars")).toBe("vars");
+  });
+});
+
+describe("the message as a preview draws it", () => {
+  it("puts a placeholder for each value, and leaves the values out of what the cut maths count", () => {
+    const draft = draftOf({
+      title: template({ text: "AP offline at " }, { ref: "steps.check.output.site" }),
+      text: template({ text: "Access point " }, { ref: "steps.check.output.name" }, { text: " stopped." }),
+      fields: [{ label: "Site", value: ref("steps.check.output.site") }],
+      links: [{ label: "Open", url: template({ text: "https://manage.mist.test/?id=" }, { ref: "steps.check.output.id" }) }],
+      severity: "warning",
+    });
+    expect(said(draft.shown.title!, draft.says)).toBe("AP offline at {check.site}");
+    expect(said(draft.shown.text, draft.says)).toBe("Access point {check.name} stopped.");
+    expect(said(draft.shown.fields![0]!.value, draft.says)).toBe("{check.site}");
+    expect(said(draft.shown.links![0]!.url, draft.says)).toBe("https://manage.mist.test/?id={check.id}");
+    expect(draft.shown.severity).toBe("warning");
+    expect(draft.bare).toEqual({
+      title: "AP offline at ", text: "Access point  stopped.", fields: [{ label: "Site", value: "" }],
+      links: [{ label: "Open", url: "https://manage.mist.test/?id=" }], severity: "warning",
+    });  // prettier-ignore
+  });
+
+  it("shows a part a formula computes as computed when the step runs, and counts none of it", () => {
+    const draft = draftOf({ text: formula("trigger.text"), fields: formula("steps.a.output.fields"), links: ref("steps.a.output.links"), severity: formula("'critical'") });
+    expect(said(draft.shown.text, draft.says)).toBe(`{${COMPUTED}}`);
+    expect(said(draft.shown.fields![0]!.label, draft.says)).toBe(`{${COMPUTED}}`);
+    expect(said(draft.shown.links![0]!.label, draft.says)).toBe(`{${COMPUTED}}`);
+    expect(said(draft.shown.severity!, draft.says)).toBe(`{${COMPUTED}}`);
+    expect(draft.bare).toEqual({ title: null, text: "", fields: [], links: [], severity: "info" });
+    expect(draft.computed).toEqual(["text", "fields", "links", "severity"]);
+  });
+
+  it("reads a literal's text and list as written, and an empty message as one with nothing to show", () => {
+    const draft = draftOf({ text: { $value: { kind: "literal", value: "a {b}" } }, fields: { $value: { kind: "literal", value: [{ label: "x", value: "y" }] } } });
+    expect(draft.shown.text).toBe("a {b}");
+    expect(draft.shown.fields).toEqual([{ label: "x", value: "y" }]);
+    expect(draftOf({}).shown.text).toBe("");
+  });
+});
+
+describe("what a target would cut, its values left out", () => {
+  it("names each value as the composer says it", () => {
+    expect(["title", "text", "fields[2].label", "fields[2].value", "links[1].label", "links[1]", "description", "odd"].map(cutName)).toEqual([
+      "the title", "the text", "field 3's label", "field 3's value", "link 2's label", "link 2 (left out)", "the description", "odd",
+    ]);  // prettier-ignore
+  });
+
+  it("says Slack's cuts with its limits, a field's value within what its label leaves", () => {
+    const draft = draftOf({
+      text: template({ text: "x".repeat(3214) }, { ref: "trigger.org" }),
+      fields: [{ label: "Note", value: "v".repeat(2500) }],
+      links: [{ label: "b".repeat(100), url: "https://a.test" }],
+    });
+    expect(cutWords("slack", draft)).toEqual([
+      "Slack will cut the text at 3,000 characters.",
+      "Slack will cut field 1's value at 1,993 characters.",
+      "Slack will cut link 1's label at 75 characters.",
+    ]);
+    expect(slackCount(draft)).toBe('3,214 characters. Slack shows the first 3,000 and ends them with "…".');
+    expect(cutWords("slack", draftOf({ text: "AP down" }))).toEqual([]);
+  });
+
+  it("counts Slack's text as its renderer does, escapes included, before its values", () => {
+    expect(slackCount(draftOf({ text: template({ text: "a & b " }, { ref: "trigger.x" }) }))).toBe("10 characters, before its values. Slack shows up to 3,000.");
+    expect(slackCount(draftOf({ text: "AP down" }))).toBe("7 characters. Slack shows up to 3,000.");
+  });
+
+  it("says Teams' and Google Chat's size against their budget, and what would be shortened first", () => {
+    // The plugins' renderers make the uncut bodies 49,199 and 45,371 bytes.
+    const big = draftOf({
+      text: "é".repeat(10_000),
+      fields: Array.from({ length: 25 }, (_, i) => ({ label: `Field ${i}`, value: "v".repeat(1000) })),
+    });
+    expect(cutWords("teams", big)).toEqual([
+      "About 49,000 bytes before its values: Teams takes 24,000. The text would be shortened first, then the fields' values.",
+    ]);
+    expect(cutWords("google_chat", big)).toEqual([
+      "About 45,000 bytes before its values: Google Chat takes 30,000. The text would be shortened first, then the fields' values.",
+    ]);
+    expect(cutWords("teams", draftOf({ text: "AP down" }))).toEqual([]);
+    expect(cutWords("webhook", big)).toEqual([]);
+  });
+});
diff --git a/frontend/src/routes/editor/drawer/MessagePreview.test.tsx b/frontend/src/routes/editor/drawer/MessagePreview.test.tsx
new file mode 100644
index 00000000..9a86a86c
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/MessagePreview.test.tsx
@@ -0,0 +1,112 @@
+// SPDX-License-Identifier: Apache-2.0
+import { screen, within } from "@testing-library/react";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { messageStep } from "../../../test/nodeTypes";
+import { fakeApi, json, showDrawer } from "./harness";
+
+const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });
+const ref = (path: string) => ({ $value: { kind: "ref", path } });
+const formula = (expr: string) => ({ $value: { kind: "cel", expr } });
+
+const WHOLE = {
+  title: template({ text: "AP offline at " }, { ref: "steps.check.output.site" }),
+  text: template({ text: "Access point " }, { ref: "steps.check.output.name" }, { text: " stopped." }),
+  fields: [{ label: "Site", value: ref("steps.check.output.site") }, { label: "Model", value: "AP45" }],
+  links: [{ label: "Open in Mist", url: "https://manage.mist.test/admin" }],
+  severity: "warning",
+};
+
+beforeEach(() => {
+  fakeApi({ "GET /api/v1/t/t1/connections": () => json([]), "GET /api/v1/connection-types": () => json([]) });
+});
+afterEach(() => vi.restoreAllMocks());
+
+const preview = (name: string) => screen.getByRole("region", { name });
+
+describe("a message's preview (4f-1, the message composer design §5.5)", () => {
+  it("lays a Slack message out as Slack shows it, each value as where it comes from", () => {
+    showDrawer(messageStep("slack.send_message"), { config: WHOLE });
+    const region = preview("Preview in Slack");
+    expect(region.getAttribute("aria-live")).toBeNull();
+    expect(within(region).getByText("Laid out as Slack shows it. A value shows where it comes from until the step runs.")).toBeTruthy();
+    const title = within(region).getByText("AP offline at", { exact: false });
+    expect(title.className).toContain("font-semibold");
+    const site = within(title).getByText("check.site");
+    expect(site.className).toContain("font-mono");
+    expect(site.className).toContain("decoration-dotted");
+    expect(within(region).getByText("Site").tagName).toBe("DT");
+    expect(within(region).getByText("AP45").tagName).toBe("DD");
+    expect(within(region).getByText("Open in Mist")).toBeTruthy();
+    expect(within(region).getByText("Severity: warning")).toBeTruthy();
+    expect(within(region).queryByRole("link")).toBeNull(); // nothing in a preview goes anywhere
+  });
+
+  it("lays Teams' card out with each field as label: value", () => {
+    showDrawer(messageStep("teams.send_message"), { config: WHOLE });
+    const region = preview("Preview in Teams");
+    expect(within(region).getByText("Laid out as a Teams card. A value shows where it comes from until the step runs.")).toBeTruthy();
+    expect(within(region).getByText("Model").nextSibling!.textContent).toBe(": ");
+    expect(within(region).getByText("Severity: warning")).toBeTruthy();
+  });
+
+  it("shows Google Chat's < and > as ＜ ＞, and links as linked words", () => {
+    showDrawer(messageStep("google_chat.send_message"), { config: { ...WHOLE, text: "a <b> & c" } });
+    const region = preview("Preview in Google Chat");
+    expect(within(region).getByText("a ＜b＞ & c", { exact: false })).toBeTruthy();
+    expect(within(region).getByText("Open in Mist").className).toContain("underline");
+  });
+
+  it("shows what the webhook posts as JSON, as written, a value in braces", () => {
+    showDrawer(messageStep("webhook.send_message"), { config: { ...WHOLE, links: formula("steps.a.output.links") } });
+    const region = preview("What it posts");
+    expect(within(region).getByText("The message as JSON, as written: nothing is cut. A value shows where it comes from until the step runs.")).toBeTruthy();
+    const posted = region.querySelector("pre")!.textContent;
+    expect(posted).toContain('"title": "AP offline at {check.site}"');
+    expect(posted).toContain('"links": Computed when the step runs');
+    expect(posted).toContain('"severity": "warning"');
+  });
+
+  it("says how email and the others send it, with no preview", () => {
+    showDrawer(messageStep("email.send_message"), { config: WHOLE });
+    expect(screen.getByText("No preview: an email is plain text, its subject the title (or the text's first line), up to 200 characters.")).toBeTruthy();
+    expect(screen.queryByRole("region")).toBeNull();
+  });
+
+  it("says ServiceNow sends the message in its own form", () => {
+    showDrawer(messageStep("servicenow.create_incident"), { config: WHOLE });
+    expect(screen.getByText("No preview for ServiceNow: it sends the same message in its own form, and Simulate step says what it would cut.")).toBeTruthy();
+  });
+
+  it("gives a third party's message step the composer and no preview", () => {
+    showDrawer(messageStep("acme.notify"), { config: WHOLE });
+    expect(screen.getByRole("group", { name: "Message" })).toBeTruthy();
+    expect(screen.queryByRole("region")).toBeNull();
+    expect(screen.queryByText(/^No preview/)).toBeNull();
+  });
+
+  it("shows a part a formula computes as computed when the step runs", () => {
+    showDrawer(messageStep("slack.send_message"), { config: { ...WHOLE, fields: formula("steps.check.output.fields") } });
+    expect(within(preview("Preview in Slack")).getByText("Computed when the step runs")).toBeTruthy();
+  });
+
+  it("has nothing to show without the text", () => {
+    showDrawer(messageStep("slack.send_message"), { config: { title: "Hello" } });
+    expect(within(preview("Preview in Slack")).getByText("Nothing to show yet: the message has no text.")).toBeTruthy();
+  });
+
+  it("counts Slack's text under it, and past Slack's limit warns there and under the preview", () => {
+    const f = showDrawer(messageStep("slack.send_message"), { config: { text: template({ text: "Access point " }, { ref: "trigger.ap" }) } });
+    expect(screen.getByText("13 characters, before its values. Slack shows up to 3,000.")).toBeTruthy();
+    f.replace({ text: template({ text: "x".repeat(3214) }, { ref: "trigger.org" }) });
+    const warning = screen.getByText('3,214 characters. Slack shows the first 3,000 and ends them with "…".');
+    expect(warning.className).toContain("text-warn-ink");
+    expect(screen.getByLabelText("Text").getAttribute("aria-describedby")).toContain(warning.id);
+    expect(within(preview("Preview in Slack")).getByText("Slack will cut the text at 3,000 characters.")).toBeTruthy();
+  });
+
+  it("warns of Teams' size under the text and the preview", () => {
+    showDrawer(messageStep("teams.send_message"), { config: { text: "é".repeat(20_000) } });
+    const words = "About 40,000 bytes before its values: Teams takes 24,000. The text would be shortened.";
+    expect(screen.getAllByText(words)).toHaveLength(2);
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/composer.test.ts
src/routes/editor/drawer/MessagePreview.test.tsx src/routes/editor/drawer/MessageComposer.test.tsx`

Expected: FAIL, 18 failed and 11 passed: `composer.ts` has no `draftOf`, `sourceText` or `cutName` (`(0 , draftOf) is
not a function`); there's no preview region (`Unable to find an accessible element with the role "region" and name
"Preview in Slack"`, and Teams', Google Chat's, the webhook's), no line for email or ServiceNow, no count or warning
under the text. "gives a third party's message step the composer and no preview" passes at once; so do Task 7's composer
tests.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/composer.ts b/frontend/src/lib/composer.ts
index 0c3bde93..e4e8673c 100644
--- a/frontend/src/lib/composer.ts
+++ b/frontend/src/lib/composer.ts
@@ -1,9 +1,12 @@
 // SPDX-License-Identifier: Apache-2.0
 // What the message composer knows of the steps that send a message (4f-1, the message composer design §5): which
-// target a step sends to, its name in the composer's words, what its title becomes there, and a link's address checked
-// as it's typed. A step it doesn't know (a third party's on the SDK's message) gets the composer and nothing more (§8,
-// call 2).
-import { segmentsOf } from "./pills";
+// target a step sends to, its name in the composer's words, what its title becomes there, a link's address checked as
+// it's typed, and the message as a preview draws it, with what its target would cut. A step it doesn't know (a third
+// party's on the SDK's message) gets the composer and nothing more (§8, call 2).
+import { fixedOf, kindOf } from "./config";
+import { CHAT_BUDGET, fitted, googleChat, SLACK, slack, TEAMS_BUDGET, teams, type Message, type Severity } from "./messages";
+import { headOf, segmentsOf } from "./pills";
+import { isObject } from "./schemaForm";
 import type { NodeType } from "./workflows";
 
 export type Target = "slack" | "teams" | "google_chat" | "webhook" | "email" | "syslog" | "pagerduty" | "servicenow";
@@ -54,3 +57,132 @@ export function linkProblem(value: unknown): string | null {
 
 /** Why another field or link can't be added (§5.3). */
 export const capWords = (noun: "field" | "link", max: number): string => `A message takes up to ${max} ${noun}s: remove one to add another.`;
+
+export const COMPUTED = "Computed when the step runs";
+
+/** Where a value comes from, as a preview says it: `check.site` for a step's output, `trigger.events[0].ap` (§5.5). */
+export function sourceText(path: string): string {
+  const { head, rest } = headOf(path);
+  return rest === "" ? head : rest.startsWith("[") ? `${head}${rest}` : `${head}.${rest}`;
+}
+
+/** The message as a preview draws it (§5.5): `shown` holds a placeholder for each value, a character of Unicode's
+ * private use plane 15 that no renderer escapes, splits or cuts through, `says` what each one says, in order; `bare`
+ * is the message without them, which the cut maths count (§5.2). A part a formula computes is one placeholder, and
+ * none of it is counted (§5.1). */
+export interface Draft {
+  shown: Message;
+  bare: Message;
+  says: string[];
+  computed: string[]; // the parts a formula or an earlier step's value gives whole: the webhook's JSON says so
+}
+
+export const PLACEHOLDER = 0xf0000;
+
+/** A list or a severity a formula or a value from an earlier step gives: known when the step runs. */
+const isComputed = (value: unknown): boolean => kindOf(value) === "cel" || kindOf(value) === "ref" || kindOf(value) === "template";
+
+type Row = { label: string; value: string } | { label: string; url: string };
+
+export function draftOf(config: Record<string, unknown>): Draft {
+  const says: string[] = [];
+  const computed = ["text", "fields", "links", "severity"].filter((part) => isComputed(config[part]) && !(part === "text" && kindOf(config.text) !== "cel"));
+  const hold = (words: string): string => String.fromCodePoint(PLACEHOLDER + says.push(words) - 1);
+  const text = (value: unknown): { shown: string; bare: string } => {
+    if (kindOf(value) === "cel") return { shown: hold(COMPUTED), bare: "" };
+    const s = segmentsOf(value);
+    if (s === null) return { shown: "", bare: "" };
+    return { shown: s.texts.map((t, i) => (s.pills[i] ? t + hold(sourceText(s.pills[i].ref)) : t)).join(""), bare: s.texts.join("") };
+  };
+  const rows = (value: unknown, second: "value" | "url"): { shown: Row[]; bare: Row[] } => {
+    if (isComputed(value)) return { shown: [{ label: hold(COMPUTED), [second]: "" } as Row], bare: [] };
+    const items = fixedOf(value);
+    const each = (Array.isArray(items) ? (items as unknown[]) : []).map((item) => {
+      const row = isObject(item) ? item : {};
+      return { label: text(row.label), other: text(row[second]) };
+    });
+    return {
+      shown: each.map((row) => ({ label: row.label.shown, [second]: row.other.shown }) as Row),
+      bare: each.map((row) => ({ label: row.label.bare, [second]: row.other.bare }) as Row),
+    };
+  };
+  const title = config.title === undefined || config.title === null ? null : text(config.title);
+  const body = text(config.text);
+  const fields = rows(config.fields, "value");
+  const links = rows(config.links, "url");
+  const fixed = fixedOf(config.severity);
+  const severity = isComputed(config.severity) ? null : typeof fixed === "string" ? (fixed as Severity) : "info";
+  const shown: Message = {
+    title: title?.shown ?? null, text: body.shown, fields: fields.shown as Message["fields"], links: links.shown as Message["links"],
+    severity: severity ?? (hold(COMPUTED) as Severity),
+  };  // prettier-ignore
+  const bare: Message = {
+    title: title?.bare ?? null, text: body.bare, fields: fields.bare as Message["fields"], links: links.bare as Message["links"],
+    severity: severity ?? "info",
+  };  // prettier-ignore
+  return { shown, bare, says, computed };
+}
+
+/** A value cut, as the composer and Simulate step say it (§5.7). */
+export function cutName(name: string): string {
+  if (name === "title" || name === "text" || name === "description") return `the ${name}`;
+  const part = /^(fields|links)\[(\d+)\](?:\.(label|value))?$/.exec(name);
+  if (!part) return name;
+  const n = Number(part[2]) + 1;
+  const noun = part[1] === "fields" ? "field" : "link";
+  return part[3] ? `${noun} ${n}'s ${part[3]}` : `${noun} ${n} (left out)`;
+}
+
+const counted = (n: number): string => n.toLocaleString("en-US");
+
+/** Slack's limit for a value it cut, in characters: a field's value has what its label leaves (plugins/slack). */
+function slackLimit(name: string, message: Message): number {
+  const field = /^fields\[(\d+)\]\.value$/.exec(name);
+  if (field) return SLACK.FIELD_MAX - [...fitted(message.fields![Number(field[1])]!.label, SLACK.LABEL_MAX)[0]].length - 3;
+  if (name === "title") return SLACK.SECTION_MAX - 2;
+  if (name.endsWith(".label")) return name.startsWith("links") ? SLACK.BUTTON_MAX : SLACK.LABEL_MAX;
+  return SLACK.SECTION_MAX;
+}
+
+/** What Teams or Google Chat would shorten, in the order their levels tighten them, and how many links they'd leave
+ * out. */
+function shortened(truncated: string[]): string {
+  const parts = [
+    truncated.includes("text") && "the text",
+    truncated.some((n) => /^fields\[\d+\]\.value$/.test(n)) && "the fields' values",
+    truncated.includes("title") && "the title",
+    truncated.some((n) => n.endsWith(".label")) && "the labels",
+  ].filter((p): p is string => p !== false);
+  const left = truncated.filter((n) => /^links\[\d+\]$/.test(n)).length;
+  const words: string[] = [];
+  if (parts.length > 0) {
+    const first = `${parts[0]![0]!.toUpperCase()}${parts[0]!.slice(1)}`;
+    words.push(parts.length === 1 ? `${first} would be shortened.` : `${first} would be shortened first, then ${parts.slice(1).join(" and ")}.`);
+  }
+  if (left > 0) words.push(left === 1 ? "A link would be left out." : `${left} links would be left out.`);
+  return words.join(" ");
+}
+
+/** What the target would cut of the message, its values left out (§5.5): Slack each value with its limit, Teams and
+ * Google Chat the body's size against their budget. A warning, never an error. */
+export function cutWords(target: Target, draft: Draft): string[] {
+  if (target === "slack") return slack(draft.bare).truncated.map((name) => `Slack will cut ${cutName(name)} at ${counted(slackLimit(name, draft.bare))} characters.`);
+  if (target !== "teams" && target !== "google_chat") return [];
+  const { truncated, size = 0 } = target === "teams" ? teams(draft.bare) : googleChat(draft.bare);
+  if (truncated.length === 0) return [];
+  const budget = target === "teams" ? TEAMS_BUDGET : CHAT_BUDGET;
+  return [`About ${counted(Math.round(size / 1000) * 1000)} bytes before its values: ${NAMES[target]} takes ${counted(budget)}. ${shortened(truncated)}`];
+}
+
+/** Under Slack's text: its length as Slack's renderer counts it, escaped, before its values (§5.2). */
+export function slackCount(draft: Draft): string {
+  const n = [...fitted(draft.bare.text, Number.MAX_SAFE_INTEGER)[0]].length;
+  if (n > SLACK.SECTION_MAX) return `${counted(n)} characters. Slack shows the first ${counted(SLACK.SECTION_MAX)} and ends them with "…".`;
+  return `${counted(n)} characters${draft.shown.text !== draft.bare.text ? ", before its values" : ""}. Slack shows up to ${counted(SLACK.SECTION_MAX)}.`;
+}
+
+/** Whether the target would cut the text, its values left out: said under the text too (§5.5). */
+export function cutsText(target: Target, draft: Draft): boolean {
+  const render = target === "slack" ? slack : target === "teams" ? teams : target === "google_chat" ? googleChat : null;
+  return render !== null && render(draft.bare).truncated.includes("text");
+}
diff --git a/frontend/src/routes/editor/drawer/FieldFrame.tsx b/frontend/src/routes/editor/drawer/FieldFrame.tsx
index 456cb2b0..06a9c464 100644
--- a/frontend/src/routes/editor/drawer/FieldFrame.tsx
+++ b/frontend/src/routes/editor/drawer/FieldFrame.tsx
@@ -1,7 +1,7 @@
 // SPDX-License-Identifier: Apache-2.0
 // A field's frame (4c-1): its label and the actions on it, then its control (given its id and the ids that describe
 // it), its hint, a type hint from the browser (D19) and the server's problems at it, each described by the control
-// (WCAG 1.3.1, 3.3.1). "(required)" sits beside the label, outside it: the control says it (aria-required). A group, a
+// (WCAG 1.3.1, 3.3.1), and a warning, which never blocks (the message composer's, 4f-1). "(required)" sits beside the label, outside it: the control says it (aria-required). A group, a
 // list or a map is a fieldset its legend names, its parts indented, never marked with a left rule (outline §6).
 import { useId, type ReactNode } from "react";
 import type { Diagnostic } from "../../../lib/workflows";
@@ -16,20 +16,22 @@ interface Frame {
   label: string;
   required: boolean; // said below the top level: Setup says it once for its own fields
   hint: string | null;
+  warn?: string | null; // what the target would cut: said, never blocking
   local: string | null; // what the browser found: the control's text isn't saved
   problems: Diagnostic[];
   actions?: ReactNode;
 }
 
-const describing = (id: string, { hint, local, problems }: Pick<Frame, "hint" | "local" | "problems">) =>
-  [hint !== null ? `${id}-hint` : null, local !== null ? `${id}-local` : null, ...problems.map((_, i) => `${id}-p${i}`)]
+const describing = (id: string, { hint, warn, local, problems }: Pick<Frame, "hint" | "warn" | "local" | "problems">) =>
+  [hint !== null ? `${id}-hint` : null, warn ? `${id}-warn` : null, local !== null ? `${id}-local` : null, ...problems.map((_, i) => `${id}-p${i}`)]
     .filter((x): x is string => x !== null)
     .join(" ") || undefined;
 
-function Notes({ id, hint, local, problems }: { id: string } & Pick<Frame, "hint" | "local" | "problems">) {
+function Notes({ id, hint, warn, local, problems }: { id: string } & Pick<Frame, "hint" | "warn" | "local" | "problems">) {
   return (
     <>
       {hint !== null && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
+      {warn && <p id={`${id}-warn`} className="text-small text-warn-ink">{warn}</p>}
       {local !== null && <p id={`${id}-local`} className="text-small text-danger">{local}</p>}
       {problems.map((d, i) => (
         <p key={`${d.code}:${i}`} id={`${id}-p${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>
@@ -43,7 +45,7 @@ function Notes({ id, hint, local, problems }: { id: string } & Pick<Frame, "hint
 
 const Required = () => <span className="text-small text-muted">(required)</span>;
 
-export function FieldFrame({ label, required, hint, local, problems, actions, below, children }: Frame & {
+export function FieldFrame({ label, required, hint, warn = null, local, problems, actions, below, children }: Frame & {
   below?: ReactNode;
   children: (control: Described) => ReactNode;
 }) {  // prettier-ignore
@@ -58,8 +60,8 @@ export function FieldFrame({ label, required, hint, local, problems, actions, be
         </span>
         {actions}
       </div>
-      {children({ id, describedBy: describing(id, { hint, local, problems }), invalid })}
-      <Notes id={id} hint={hint} local={local} problems={problems} />
+      {children({ id, describedBy: describing(id, { hint, warn, local, problems }), invalid })}
+      <Notes id={id} hint={hint} warn={warn} local={local} problems={problems} />
       {below}
     </div>
   );
diff --git a/frontend/src/routes/editor/drawer/FieldView.tsx b/frontend/src/routes/editor/drawer/FieldView.tsx
index 9dba4234..f208c008 100644
--- a/frontend/src/routes/editor/drawer/FieldView.tsx
+++ b/frontend/src/routes/editor/drawer/FieldView.tsx
@@ -95,7 +95,7 @@ const startMode = (spec: FieldSpec, value: unknown): Mode =>
 /** How the message composer draws one of its parts (4f-1, the message composer design §5): its own control (the
  * severity's choices) or its own rows (the fields', the links'), the text on several lines, a check said as it's typed
  * (a link's address), its hint in place of the schema's, without the note on pills (`quiet`), "(required)" said at the
- * top level (`marked`: Setup holds optional parts too), and what's said under it. */
+ * top level (`marked`: Setup holds optional parts too), a warning (what its target would cut) and what's said under it. */
 export interface Drawn {
   control?: Control;
   parts?: (spec: FieldSpec, value: unknown) => ReactNode;
@@ -104,6 +104,7 @@ export interface Drawn {
   hint?: string | null;
   quiet?: boolean;
   marked?: boolean;
+  warn?: string | null;
   below?: ReactNode;
 }
 
@@ -291,7 +292,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
     </>
   );
   const frame = (control: (c: Described) => ReactNode, said: string | null = hint, below: ReactNode = drawn.below) => (
-    <FieldFrame label={spec.label} required={required} hint={said} local={stale ? STALE : (held?.why ?? local ?? missing ?? checked)} problems={problems} actions={actions} below={below}>
+    <FieldFrame label={spec.label} required={required} hint={said} warn={drawn.warn} local={stale ? STALE : (held?.why ?? local ?? missing ?? checked)} problems={problems} actions={actions} below={below}>
       {control}
     </FieldFrame>
   );
diff --git a/frontend/src/routes/editor/drawer/MessageComposer.tsx b/frontend/src/routes/editor/drawer/MessageComposer.tsx
index f5f81c4e..12f86554 100644
--- a/frontend/src/routes/editor/drawer/MessageComposer.tsx
+++ b/frontend/src/routes/editor/drawer/MessageComposer.tsx
@@ -3,13 +3,15 @@
 // place on Setup, the "Message" fieldset: its severity as four choices, its title, its text on several lines, its fields
 // and links as numbered rows. Each part is the drawer's own field (FieldView): what's typed, held, refused or computed by
 // a formula behaves as everywhere in the drawer, and a part it can't draw as its own shows today's control (ledger 102).
-import { useId, useRef, type ReactNode } from "react";
+// Then its preview, which follows every edit (§5.5).
+import { useId, useMemo, useRef, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
-import { capWords, linkProblem, targetOf, titleHint } from "../../../lib/composer";
+import { capWords, cutsText, cutWords, draftOf, linkProblem, slackCount, targetOf, titleHint } from "../../../lib/composer";
 import { itemOf, propertiesOf, type FieldSpec } from "../../../lib/schemaForm";
 import { useDrawer } from "./context";
 import { FieldView, type Drawn } from "./FieldView";
 import type { ControlProps } from "./scalars";
+import { MessagePreview } from "./MessagePreview";
 import { lineageKey } from "./structured";
 
 const SEVERITIES: Record<string, string> = { info: "Info", success: "Success", warning: "Warning", critical: "Critical" };
@@ -103,9 +105,19 @@ function Rows({ spec, value, noun }: { spec: FieldSpec; value: unknown; noun: "f
   );  // prettier-ignore
 }
 
+/** Under the text: Slack's count, or what its target would cut of it, a warning linked to it (§5.2, §5.5). */
+function textDrawn(target: ReturnType<typeof targetOf>, draft: ReturnType<typeof draftOf>): Drawn {
+  if (target === null) return {};
+  const cuts = cutsText(target, draft);
+  if (target === "slack") return cuts ? { warn: slackCount(draft) } : { below: <p className="text-small text-muted">{slackCount(draft)}</p> };
+  return cuts ? { warn: cutWords(target, draft)[0] ?? null } : {};
+}
+
 export function MessageComposer({ parts }: { parts: FieldSpec[] }) {
   const drawer = useDrawer();
   const target = targetOf(drawer.type);
+  const config = drawer.node.config;
+  const draft = useMemo(() => draftOf(config ?? {}), [config]);
   const drawnFor = (name: string): Drawn => {
     switch (name) {
       case "severity":
@@ -113,7 +125,7 @@ export function MessageComposer({ parts }: { parts: FieldSpec[] }) {
       case "title":
         return { hint: titleHint(target), quiet: true, marked: true };
       case "text":
-        return { lines: true, marked: true };
+        return { lines: true, marked: true, ...textDrawn(target, draft) };
       case "fields":
         return { parts: (spec, value): ReactNode => <Rows spec={spec} value={value} noun="field" />, marked: true };
       case "links":
@@ -123,11 +135,14 @@ export function MessageComposer({ parts }: { parts: FieldSpec[] }) {
     }
   };
   return (
-    <fieldset className="flex min-w-0 flex-col gap-4">
-      <legend className="mb-1 text-body font-semibold">Message</legend>
-      {parts.map((part) => (
-        <FieldView key={part.pointer} spec={part} drawn={drawnFor(part.name)} />
-      ))}
-    </fieldset>
+    <>
+      <fieldset className="flex min-w-0 flex-col gap-4">
+        <legend className="mb-1 text-body font-semibold">Message</legend>
+        {parts.map((part) => (
+          <FieldView key={part.pointer} spec={part} drawn={drawnFor(part.name)} />
+        ))}
+      </fieldset>
+      {target && <MessagePreview target={target} draft={draft} />}
+    </>
   );
 }
diff --git a/frontend/src/routes/editor/drawer/MessagePreview.tsx b/frontend/src/routes/editor/drawer/MessagePreview.tsx
new file mode 100644
index 00000000..f0623e1a
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/MessagePreview.tsx
@@ -0,0 +1,178 @@
+// SPDX-License-Identifier: Apache-2.0
+// A message's preview (4f-1, the message composer design §5.5): for Slack, Teams and Google Chat, what the TypeScript
+// mirror of the target's renderer makes of the message, drawn as the target lays it out, each value shown as where it
+// comes from; for the webhook, the JSON it posts; for the others, a line saying how they send it. What the target would
+// cut is said under the preview. It follows every edit, named by its heading, never announced as it changes. Drawn in
+// the app's own tokens, never a target's colours (no AI tells).
+import { useId, type ReactNode } from "react";
+import { COMPUTED, cutWords, NAMES, PLACEHOLDER, type Draft, type Target } from "../../../lib/composer";
+import { googleChat, slack, teams } from "../../../lib/messages";
+
+const NO_PREVIEW: Partial<Record<Target, string>> = {
+  email: "No preview: an email is plain text, its subject the title (or the text's first line), up to 200 characters.",
+};
+const LAID_OUT: Partial<Record<Target, string>> = {
+  slack: "Laid out as Slack shows it.",
+  teams: "Laid out as a Teams card.",
+  google_chat: "Laid out as Google Chat shows it.",
+};
+const VALUES = "A value shows where it comes from until the step runs.";
+
+/** Text with each placeholder drawn as where its value comes from, in the code face, underlined with dots; a part a
+ * formula computes as said so. In the webhook's JSON a value is in braces, as the read-only view writes one. */
+function Shown({ text, says, braces = false }: { text: string; says: string[]; braces?: boolean }) {
+  const out: ReactNode[] = [];
+  let run = "";
+  for (const char of text) {
+    const n = char.codePointAt(0)! - PLACEHOLDER;
+    if (n < 0 || n >= says.length) {
+      run += char;
+      continue;
+    }
+    if (run !== "") out.push(run);
+    run = "";
+    const words = says[n]!;
+    out.push(
+      words === COMPUTED ? (
+        <span key={out.length} className="text-muted">{words}</span>
+      ) : (
+        <span key={out.length} className="font-mono text-meta underline decoration-dotted underline-offset-2">{braces ? `{${words}}` : words}</span>
+      ),
+    );
+  }
+  if (run !== "") out.push(run);
+  return <>{out}</>;
+}
+
+const unescaped = (text: string) => text.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
+const BUTTON = "rounded-md border border-line-control px-3 py-1 text-small font-semibold";
+
+type Mrkdwn = { text: string };
+type SlackBlock =
+  | { type: "section"; text?: Mrkdwn; fields?: Mrkdwn[] }
+  | { type: "actions"; elements: { text: { text: string } }[] }
+  | { type: "context"; elements: Mrkdwn[] };
+
+/** Slack's blocks: the title in bold, the text, the fields two to a row, the links as buttons, the severity. */
+function SlackShown({ draft }: { draft: Draft }) {
+  const says = draft.says;
+  const blocks = slack(draft.shown).body.blocks as SlackBlock[];
+  return blocks.map((block, i) => {
+    if (block.type === "actions") {
+      return (
+        <div key={i} className="flex flex-wrap gap-2">
+          {block.elements.map((button, k) => <span key={k} className={BUTTON}><Shown text={button.text.text} says={says} /></span>)}
+        </div>
+      );
+    }
+    if (block.type === "context") return <p key={i} className="text-small text-muted"><Shown text={unescaped(block.elements[0]!.text)} says={says} /></p>;
+    if (block.fields) {
+      return (
+        <dl key={i} className="grid grid-cols-2 gap-x-4 gap-y-2">
+          {block.fields.map((field, k) => {
+            const text = unescaped(field.text);
+            const at = text.indexOf("\n");
+            return (
+              <div key={k} className="min-w-0">
+                <dt className="font-semibold"><Shown text={text.slice(1, at - 1)} says={says} /></dt>
+                <dd className="whitespace-pre-wrap break-words"><Shown text={text.slice(at + 1)} says={says} /></dd>
+              </div>
+            );
+          })}
+        </dl>
+      );
+    }
+    const text = unescaped(block.text?.text ?? "");
+    const title = i === 0 && Boolean(draft.shown.title); // the first section is the title's when there's one
+    return (
+      <p key={i} className={`whitespace-pre-wrap break-words ${title ? "font-semibold" : ""}`}>
+        <Shown text={title ? text.slice(1, -1) : text} says={says} />
+      </p>
+    );
+  });  // prettier-ignore
+}
+
+type Run = { text: string; weight?: string; size?: string; isSubtle?: boolean };
+type Card = { body: { inlines: Run[] }[]; actions?: { title: string }[] };
+
+/** Teams' card: its text runs, bolder where the card says, the severity subtle; its links as buttons under it. */
+function TeamsShown({ draft }: { draft: Draft }) {
+  const attachments = teams(draft.shown).body.attachments as { content: Card }[];
+  const card = attachments[0]!.content;
+  return (
+    <>
+      {card.body.map((block, i) => (
+        <p key={i} className="whitespace-pre-wrap break-words">
+          {block.inlines.map((run, k) => (
+            <span key={k} className={[run.weight === "bolder" && "font-semibold", run.size === "medium" && "text-body-lg", run.isSubtle && "text-small text-muted"].filter(Boolean).join(" ")}>
+              <Shown text={run.text} says={draft.says} />
+            </span>
+          ))}
+        </p>
+      ))}
+      {card.actions && (
+        <div className="flex flex-wrap gap-2">
+          {card.actions.map((action, k) => <span key={k} className={BUTTON}><Shown text={action.title} says={draft.says} /></span>)}
+        </div>
+      )}
+    </>
+  );  // prettier-ignore
+}
+
+const CHAT_MARKS = /\*([^*\n]+)\*|<([^|>\n]*)\|([^>\n]*)>/g;
+
+/** Google Chat's one text: what's between asterisks in bold, a link as its linked words. */
+function ChatShown({ draft }: { draft: Draft }) {
+  const text = googleChat(draft.shown).body.text as string;
+  const out: ReactNode[] = [];
+  let last = 0;
+  for (const m of text.matchAll(CHAT_MARKS)) {
+    out.push(<Shown key={out.length} text={text.slice(last, m.index)} says={draft.says} />);
+    out.push(
+      m[1] !== undefined ? (
+        <strong key={out.length} className="font-semibold"><Shown text={m[1]} says={draft.says} /></strong>
+      ) : (
+        <span key={out.length} className="text-accent-ink underline"><Shown text={m[3] ?? ""} says={draft.says} /></span>
+      ),
+    );
+    last = m.index + m[0].length;
+  }
+  out.push(<Shown key={out.length} text={text.slice(last)} says={draft.says} />);
+  return <p className="whitespace-pre-wrap break-words">{out}</p>;
+}
+
+/** The webhook's JSON, as written: a part a formula gives whole is said in its place. */
+function Posted({ draft }: { draft: Draft }) {
+  const says = [...draft.says, COMPUTED];
+  const whole = String.fromCodePoint(PLACEHOLDER + says.length - 1);
+  const { title, text, fields, links, severity } = draft.shown;
+  const message: Record<string, unknown> = { title: title ?? null, text, fields, links, severity: severity ?? "info" };
+  for (const part of draft.computed) if (part !== "text") message[part] = "\u0000";
+  const posted = JSON.stringify(message, null, 2).replaceAll('"\\u0000"', whole);
+  return <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-small"><Shown text={posted} says={says} braces /></pre>;
+}
+
+export function MessagePreview({ target, draft }: { target: Target; draft: Draft }) {
+  const heading = useId();
+  if (target !== "slack" && target !== "teams" && target !== "google_chat" && target !== "webhook") {
+    return (
+      <p className="text-small text-muted">
+        {NO_PREVIEW[target] ?? `No preview for ${NAMES[target]}: it sends the same message in its own form, and Simulate step says what it would cut.`}
+      </p>
+    );
+  }
+  const webhook = target === "webhook";
+  const shown = draft.shown.text === "" ? (
+    <p className="text-muted">Nothing to show yet: the message has no text.</p>
+  ) : webhook ? <Posted draft={draft} /> : target === "slack" ? <SlackShown draft={draft} /> : target === "teams" ? <TeamsShown draft={draft} /> : <ChatShown draft={draft} />;  // prettier-ignore
+  return (
+    <section aria-labelledby={heading} className="flex min-w-0 flex-col gap-2">
+      <h3 id={heading} className="text-small font-semibold">{webhook ? "What it posts" : `Preview in ${NAMES[target]}`}</h3>
+      <p className="text-small text-muted">{webhook ? `The message as JSON, as written: nothing is cut. ${VALUES}` : `${LAID_OUT[target]} ${VALUES}`}</p>
+      <div className="flex min-w-0 flex-col gap-2 rounded-lg border border-line bg-surface-2 p-3 text-body">{shown}</div>
+      {cutWords(target, draft).map((words) => (
+        <p key={words} className="text-small text-warn-ink">{words}</p>
+      ))}
+    </section>
+  );
+}
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 29 passed.

- [ ] **Step 5: Static checks**

Run: the frontend's static checks of "How to run things". Expected: no output.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/composer.ts frontend/src/lib/composer.test.ts frontend/src/routes/editor/drawer
git commit -m "feat(editor): the message's previews, and what its target would cut (4f-1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The other states, and Simulate's words

**Spec:** §5.6 (no connection yet; the text left empty; read only; simulated); §5.7 (the cut names in words).

**Files:**
- Modify: `frontend/src/lib/composer.ts` (`TEXT_MISSING`, `summaryOf`, `simulatedCut`),
  `frontend/src/routes/editor/drawer/FieldView.tsx` (`Drawn { missing }`),
  `frontend/src/routes/editor/drawer/MessageComposer.tsx`, `frontend/src/routes/editor/drawer/pickers.tsx`
  (`connectionTypesQuery`), `frontend/src/routes/editor/simulation/StepResult.tsx`, and their tests
  (`MessageComposer.test.tsx`, `pickers.test.tsx`, `StepResult.test.tsx`)

**Interfaces:**
- Consumes: Task 8's `cutName`; `connectionsQuery`; `field` (`simulation/results.ts`).
- Produces: `composer.ts`: `TEXT_MISSING`, `summaryOf(config)`, `simulatedCut(ref, output): string | null`;
  `pickers.tsx`: `connectionTypesQuery()` (key `["connection-types"]`, Connections' own).

The text's required words are the composer's (ruling 17). Read only, the composer draws the title and the text and
sums up the rest (ruling 18). The connection's empty state names its type by its label, read only then (ruling 19).
A simulated message step's result says what it would cut, from its output's `truncated` (ruling 20).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/drawer/MessageComposer.test.tsx b/frontend/src/routes/editor/drawer/MessageComposer.test.tsx
index 7dc2f3ea..0bc5770b 100644
--- a/frontend/src/routes/editor/drawer/MessageComposer.test.tsx
+++ b/frontend/src/routes/editor/drawer/MessageComposer.test.tsx
@@ -110,6 +110,32 @@ describe("the message composer (4f-1, the message composer design §5)", () => {
     expect(within(message()).queryByText("A link's address starts with http:// or https://.")).toBeNull();
   });
 
+  it("asks for the text in the composer's words once it's left empty", async () => {
+    showDrawer(SLACK, { config: { text: "x" } });
+    await userEvent.clear(within(message()).getByLabelText("Text"));
+    const said = within(message()).getByText("Give the text: a message needs it.");
+    expect(within(message()).getByLabelText("Text").getAttribute("aria-describedby")).toContain(said.id);
+  });
+
+  it("shows a version or a viewer the message as written, the rest summed up, and its preview", () => {
+    const config = {
+      text: template({ text: "Access point " }, { ref: "steps.check.output.name" }),
+      fields: [{ label: "Site", value: "HQ" }, { label: "Model", value: "AP45" }], links: [{ label: "Open", url: "https://a.test" }],
+      severity: "warning",
+    };  // prettier-ignore
+    showDrawer(SLACK, { editable: false, config });
+    expect(within(message()).getByText("Severity: warning · 2 fields · 1 link")).toBeTruthy();
+    expect(within(message()).getByRole("button", { name: /^check › name/ })).toBeTruthy();
+    expect(within(message()).queryByRole("radiogroup")).toBeNull();
+    expect(within(message()).queryByText("2 of 25")).toBeNull();
+    expect(screen.getByRole("region", { name: "Preview in Slack" })).toBeTruthy();
+  });
+
+  it("sums up a part a formula computes, and no fields or links", () => {
+    showDrawer(SLACK, { editable: false, config: { text: "x", severity: formula("'critical'") } });
+    expect(within(message()).getByText("Severity: computed when the step runs · no fields · no links")).toBeTruthy();
+  });
+
   it("keeps a list a formula computes as a formula, and one it can't draw as today's control", () => {
     showDrawer(SLACK, { config: { text: "x", fields: formula("steps.check.output.fields"), links: { $value: { kind: "literal", value: [] } } } });
     expect(within(message()).getByRole("textbox", { name: "Fields" })).toBeTruthy();
diff --git a/frontend/src/routes/editor/drawer/pickers.test.tsx b/frontend/src/routes/editor/drawer/pickers.test.tsx
index fb34c824..3fc83dc8 100644
--- a/frontend/src/routes/editor/drawer/pickers.test.tsx
+++ b/frontend/src/routes/editor/drawer/pickers.test.tsx
@@ -12,6 +12,8 @@ afterEach(() => {
 const C1 = "00000000-0000-4000-8000-0000000000c1";
 const C2 = "00000000-0000-4000-8000-0000000000c2";
 const CONNECTIONS = "GET /api/v1/t/t1/connections";
+const TYPES = "GET /api/v1/connection-types";
+const acmeType = { key: "acme", label: "Acme Cloud", config_schema: {}, secret_fields: [], clouds: null };
 const connection = (id: string, name: string, type: string, status: "ok" | "unverified" | "error") => ({
   id, name, type, status, revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null,
 });  // prettier-ignore
@@ -38,10 +40,16 @@ it("links to Connections when there's no Mist connection yet", async () => {
   expect(link.getAttribute("href")).toBe("/t/t1/connections");
 });
 
-it("says an admin adds a connection of any other type", async () => {
-  fakeApi({ [CONNECTIONS]: () => json([]) });
+it("says an admin adds a connection of any other type, the type named by its label (4f-1)", async () => {
+  fakeApi({ [CONNECTIONS]: () => json([]), [TYPES]: () => json([acmeType]) });
   showFields(REMOTE);
-  expect(await screen.findByText("No acme connection yet: an admin adds one.")).toBeTruthy();
+  expect(await screen.findByText("No Acme Cloud connection yet: an admin adds one.")).toBeTruthy();
+});
+
+it("never names a connection's type by its key, even when its label can't be read", async () => {
+  fakeApi({ [CONNECTIONS]: () => json([]), [TYPES]: () => json({ error: "internal" }, 500) });
+  showFields(REMOTE);
+  expect(await screen.findByText("No connection of its type yet: an admin adds one.")).toBeTruthy();
 });
 
 it("shows a connection that isn't in this tenant until it's changed", async () => {
@@ -76,10 +84,10 @@ it("names the connection field's control after its list failed, its Try again in
 });
 
 it("names the connection field's control with nothing to choose", async () => {
-  fakeApi({ [CONNECTIONS]: () => json([]) });
+  fakeApi({ [CONNECTIONS]: () => json([]), [TYPES]: () => json([acmeType]) });
   showFields(REMOTE);
-  await screen.findByText("No acme connection yet: an admin adds one.");
-  expect(screen.getByLabelText("Connection").textContent).toBe("No acme connection yet: an admin adds one.");
+  await screen.findByText("No Acme Cloud connection yet: an admin adds one.");
+  expect(screen.getByLabelText("Connection").textContent).toBe("No Acme Cloud connection yet: an admin adds one.");
 });
 
 it("names the workflow field's control while its list loads and with nothing to choose", async () => {
diff --git a/frontend/src/routes/editor/simulation/StepResult.test.tsx b/frontend/src/routes/editor/simulation/StepResult.test.tsx
index cb584108..f111fb43 100644
--- a/frontend/src/routes/editor/simulation/StepResult.test.tsx
+++ b/frontend/src/routes/editor/simulation/StepResult.test.tsx
@@ -27,6 +27,32 @@ function session(phase: SimulationSession["phase"], s: StepSummary | null, state
 }
 const show = (s: SimulationSession) => render(<StepResult session={s} stepKey="notify" attemptsOf={() => 3} />);
 
+describe("a message step's result says what it would cut (4f-1, the message composer design §5.6)", () => {
+  const banner = () => screen.getByText("Simulated.").parentElement!.textContent;
+  const sent = (type: string, truncated: string[]) =>
+    summary({ type, final: { attempt: 1, status: "succeeded", output: { sent: true, truncated }, effect: null } });
+
+  it("says Slack's cut with its limit where the output tells it", () => {
+    show(session("succeeded", sent("slack.send_message@1", ["text", "fields[1].value"])));
+    expect(banner()).toBe("Simulated. Nothing was sent. Slack would cut the text at 3,000 characters and field 2's value. Results don't prove the live call will succeed.");
+  });
+
+  it("says what Teams would shorten to fit its bytes, a link left out by its number", () => {
+    show(session("succeeded", sent("teams.send_message@1", ["text", "links[5]"])));
+    expect(banner()).toContain("Teams would shorten the text and link 6 (left out) to fit its 24,000 bytes.");
+  });
+
+  it("says what the other targets would cut, named as the composer names them", () => {
+    show(session("succeeded", sent("servicenow.create_incident@1", ["title", "description", "fields[0].label"])));
+    expect(banner()).toContain("ServiceNow would cut the title, the description and field 1's label.");
+  });
+
+  it("says nothing more when nothing was cut, or the step isn't a message's", () => {
+    show(session("succeeded", sent("slack.send_message@1", [])));
+    expect(banner()).toBe("Simulated. Nothing was sent. Results don't prove the live call will succeed.");
+  });
+});
+
 describe("a step test's result in its Test tab (§7.6; the TestResult board)", () => {
   it("says what it proves, its status and origin, its attempt, revision and run", () => {
     show(session("succeeded", summary()));
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/drawer/pickers.test.tsx
src/routes/editor/drawer/MessageComposer.test.tsx src/routes/editor/simulation/StepResult.test.tsx`

Expected: FAIL, 9 failed and 26 passed: the connection's type is named by its key (`Unable to find an element with the
text: No Acme Cloud connection yet: an admin adds one.`, three tests); the empty text says "Required" (`… Give the text:
a message needs it.`); read only, nothing sums up the rest (two tests); the result's banner says nothing of a cut
(`expected 'Simulated. Nothing was sent. Results …' to contain 'Teams would shorten the text and link…'`, three tests).
"says nothing more when nothing was cut, or the step isn't a message's" passes at once: it pins the banner as it is.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/composer.ts b/frontend/src/lib/composer.ts
index e4e8673c..dd9697f9 100644
--- a/frontend/src/lib/composer.ts
+++ b/frontend/src/lib/composer.ts
@@ -186,3 +186,39 @@ export function cutsText(target: Target, draft: Draft): boolean {
   const render = target === "slack" ? slack : target === "teams" ? teams : target === "google_chat" ? googleChat : null;
   return render !== null && render(draft.bare).truncated.includes("text");
 }
+
+/** The drawer's "Required" under the text, in the composer's words (§5.6). */
+export const TEXT_MISSING = "Give the text: a message needs it.";
+
+/** What a read-only composer says of the parts it doesn't draw: "Severity: warning · 2 fields · 1 link" (§5.6). */
+export function summaryOf(config: Record<string, unknown>): string {
+  const fixed = fixedOf(config.severity);
+  const severity = isComputed(config.severity) ? "computed when the step runs" : typeof fixed === "string" ? fixed : "info";
+  const count = (value: unknown, one: string, many: string) => {
+    if (isComputed(value)) return `${many} computed when the step runs`;
+    const items = fixedOf(value);
+    const n = Array.isArray(items) ? items.length : 0;
+    return n === 0 ? `no ${many}` : n === 1 ? `1 ${one}` : `${n} ${many}`;
+  };
+  return `Severity: ${severity} · ${count(config.fields, "field", "fields")} · ${count(config.links, "link", "links")}`;
+}
+
+const listed = (words: string[]): string => (words.length < 2 ? (words[0] ?? "") : `${words.slice(0, -1).join(", ")} and ${words.at(-1)!}`);
+
+/** A simulated message step's cut, from its output's `truncated`, in words (§5.6): the output names the values cut,
+ * never their size or the level used, so a limit is said only where it's fixed. Null for a step that isn't a message's,
+ * or when nothing was cut. */
+export function simulatedCut(ref: string, output: unknown): string | null {
+  const target = STEPS.get(ref.split("@")[0] ?? "");
+  const truncated = isObject(output) && Array.isArray(output.truncated) ? output.truncated.filter((n): n is string => typeof n === "string") : [];
+  if (!target || truncated.length === 0) return null;
+  if (target === "teams" || target === "google_chat") {
+    return `${NAMES[target]} would shorten ${listed(truncated.map(cutName))} to fit its ${counted(target === "teams" ? TEAMS_BUDGET : CHAT_BUDGET)} bytes.`;
+  }
+  if (target === "slack") {
+    const said = truncated.map((name) => (/^fields\[\d+\]\.value$/.test(name) ? cutName(name) : `${cutName(name)} at ${counted(slackLimit(name, { text: "" }))} characters`));
+    return `Slack would cut ${listed(said)}.`;
+  }
+  const name = NAMES[target];
+  return `${name[0]!.toUpperCase()}${name.slice(1)} would cut ${listed(truncated.map(cutName))}.`;
+}
diff --git a/frontend/src/routes/editor/drawer/FieldView.tsx b/frontend/src/routes/editor/drawer/FieldView.tsx
index f208c008..99324c33 100644
--- a/frontend/src/routes/editor/drawer/FieldView.tsx
+++ b/frontend/src/routes/editor/drawer/FieldView.tsx
@@ -104,6 +104,7 @@ export interface Drawn {
   hint?: string | null;
   quiet?: boolean;
   marked?: boolean;
+  missing?: string; // said in place of "Required"
   warn?: string | null;
   below?: ReactNode;
 }
@@ -195,7 +196,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
   const hint = drawn.hint !== undefined ? drawn.hint : spec.hint;
   const checked = drawn.check?.(value) ?? null; // said where a refusal would be, after it
   // A list's item or a map's entry, emptied, keeps its place, blank: never missing on its own (the final review).
-  const missing = spec.required && !spec.entry && touched && (empty || value === "") ? "Required" : null;
+  const missing = spec.required && !spec.entry && touched && (empty || value === "") ? (drawn.missing ?? "Required") : null;
   const switchTo = (next: Mode) =>
     builder
       ? reshape((current) => current, () => setChosen(next)) // the same formula, shown the other way
diff --git a/frontend/src/routes/editor/drawer/MessageComposer.tsx b/frontend/src/routes/editor/drawer/MessageComposer.tsx
index 12f86554..25c093ea 100644
--- a/frontend/src/routes/editor/drawer/MessageComposer.tsx
+++ b/frontend/src/routes/editor/drawer/MessageComposer.tsx
@@ -6,7 +6,9 @@
 // Then its preview, which follows every edit (§5.5).
 import { useId, useMemo, useRef, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
-import { capWords, cutsText, cutWords, draftOf, linkProblem, slackCount, targetOf, titleHint } from "../../../lib/composer";
+import {
+  capWords, cutsText, cutWords, draftOf, linkProblem, slackCount, summaryOf, targetOf, TEXT_MISSING, titleHint,
+} from "../../../lib/composer";  // prettier-ignore
 import { itemOf, propertiesOf, type FieldSpec } from "../../../lib/schemaForm";
 import { useDrawer } from "./context";
 import { FieldView, type Drawn } from "./FieldView";
@@ -125,7 +127,7 @@ export function MessageComposer({ parts }: { parts: FieldSpec[] }) {
       case "title":
         return { hint: titleHint(target), quiet: true, marked: true };
       case "text":
-        return { lines: true, marked: true, ...textDrawn(target, draft) };
+        return { lines: true, marked: true, missing: TEXT_MISSING, ...textDrawn(target, draft) };
       case "fields":
         return { parts: (spec, value): ReactNode => <Rows spec={spec} value={value} noun="field" />, marked: true };
       case "links":
@@ -138,9 +140,13 @@ export function MessageComposer({ parts }: { parts: FieldSpec[] }) {
     <>
       <fieldset className="flex min-w-0 flex-col gap-4">
         <legend className="mb-1 text-body font-semibold">Message</legend>
-        {parts.map((part) => (
-          <FieldView key={part.pointer} spec={part} drawn={drawnFor(part.name)} />
-        ))}
+        {/* Read only, the message as written, the rest summed up (§5.6): its preview shows them. */}
+        {parts
+          .filter((part) => drawer.editable || part.name === "title" || part.name === "text")
+          .map((part) => (
+            <FieldView key={part.pointer} spec={part} drawn={drawnFor(part.name)} />
+          ))}
+        {!drawer.editable && <p className="text-small">{summaryOf(config ?? {})}</p>}
       </fieldset>
       {target && <MessagePreview target={target} draft={draft} />}
     </>
diff --git a/frontend/src/routes/editor/drawer/pickers.tsx b/frontend/src/routes/editor/drawer/pickers.tsx
index 1fb5c6a7..bfa16beb 100644
--- a/frontend/src/routes/editor/drawer/pickers.tsx
+++ b/frontend/src/routes/editor/drawer/pickers.tsx
@@ -26,6 +26,10 @@ export const connectionsQuery = (tenantId: string) =>
     queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path: { tenant_id: tenantId } } })),
   });
 
+/** The connection types the plugins declare, under Connections' own key: a type is said by its label (4f-1). */
+export const connectionTypesQuery = () =>
+  queryOptions({ queryKey: ["connection-types"], queryFn: () => ok(client.GET("/api/v1/connection-types")) });
+
 /** What a picker says in place of its list (loading, failed, nothing to choose): an `<output>` with the field's control
  * id, so the field's label names it (#73), as the drawer shows a value it doesn't edit. A list on its way is marked, so
  * a Go to waits for it. */
@@ -55,6 +59,9 @@ export function ConnectionControl({ spec, value, id, describedBy, invalid, disab
   const list = useQuery(connectionsQuery(tenantId));
   const said = { id, describedBy };
   const current = typeof value === "string" ? value : "";
+  // Read only when there's none to choose: the words then name the type.
+  const none = list.isSuccess && current === "" && kind !== "" && kind !== "mist" && !list.data.some((c) => c.type === kind);
+  const types = useQuery({ ...connectionTypesQuery(), enabled: none });
   // Without its kind, no connection is the field's: none is listed, so none can be chosen. A value it has stays shown,
   // and can be cleared (the review).
   if (kind === "" && current === "") return <Said {...said}>This field doesn&apos;t say which kind of connection it takes.</Said>;
@@ -63,6 +70,9 @@ export function ConnectionControl({ spec, value, id, describedBy, invalid, disab
   const mine = list.data.filter((c) => c.type === kind);
   const known = current !== "" && mine.some((c) => sameId(c.id, current));
   if (mine.length === 0 && current === "") {
+    // Named by its label ("Slack", "Microsoft Teams"), never its key (4f-1, the message composer design §5.6).
+    const label = types.data?.find((t) => t.key === kind)?.label;
+    if (kind !== "mist" && types.isPending) return <Said {...said} loading className="block text-small text-muted">Loading connections…</Said>;
     return kind === "mist" ? (
       <Said {...said}>
         No Mist connection yet.{" "}
@@ -72,7 +82,7 @@ export function ConnectionControl({ spec, value, id, describedBy, invalid, disab
         .
       </Said>
     ) : (
-      <Said {...said}>No {kind} connection yet: an admin adds one.</Said>
+      <Said {...said}>{label ? `No ${label} connection yet: an admin adds one.` : "No connection of its type yet: an admin adds one."}</Said>
     );
   }
   return (
diff --git a/frontend/src/routes/editor/simulation/StepResult.tsx b/frontend/src/routes/editor/simulation/StepResult.tsx
index 6eebaab4..485c5ea0 100644
--- a/frontend/src/routes/editor/simulation/StepResult.tsx
+++ b/frontend/src/routes/editor/simulation/StepResult.tsx
@@ -2,9 +2,10 @@
 // A step test's result in its Test tab (4d-1c; the simulation design §7.6; the TestResult board): where it is while it
 // runs; once ended, what a simulation proves, its status and where its data came from, its attempt, revision and run,
 // a failure's code and message, the port a branch took or what a step set, the values used ("seeded", sensitive ones
-// redacted) and its output.
+// redacted) and its output. A message step's says what it would cut (4f-1, the message composer design §5.6).
 import type { ReactNode } from "react";
 import { Button } from "../../../components/Button";
+import { simulatedCut } from "../../../lib/composer";
 import { runId } from "../../../lib/runStatus";
 import { ENDED, type StepSummary } from "../../../lib/simulations";
 import { StatusChip } from "./chips";
@@ -55,6 +56,7 @@ export function StepResult({ session, stepKey, attemptsOf }: {
   const final = s?.final;
   const max = s ? attemptsOf(s) : null;
   const attempt = field(final, "attempt");
+  const cut = s ? simulatedCut(s.type, field(final, "output")) : null;
   const facts = state
     ? [typeof attempt === "number" && max ? `attempt ${attempt} of ${max}` : null, `revision ${state.request.draft_revision}`, `run ${runId(state.request.id)}`]
     : [];  // prettier-ignore
@@ -69,7 +71,7 @@ export function StepResult({ session, stepKey, attemptsOf }: {
       {ended && state && phase !== "refused" && phase !== "dead" && (
         <>
           <SimBanner>
-            <p><strong>Simulated.</strong> Nothing was sent. Results don&apos;t prove the live call will succeed.</p>
+            <p><strong>Simulated.</strong> Nothing was sent.{cut && ` ${cut}`} Results don&apos;t prove the live call will succeed.</p>
           </SimBanner>
           <p className="flex flex-wrap items-center gap-2">
             <StatusChip phase={phase} />
```

- [ ] **Step 4: Run them again**

Run: the same command.

Expected: PASS, 35 passed.

- [ ] **Step 5: Static checks**

Run: the frontend's static checks of "How to run things". Expected: no output.

- [ ] **Step 6: Commit, and the milestone**

```bash
git add frontend/src/lib/composer.ts frontend/src/routes/editor/drawer frontend/src/routes/editor/simulation
git commit -m "feat(editor): the composer's other states, and a simulated message's cut in words (4f-1)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Append `### 4f-1, milestone 3 (<date>)` to the ledger, as for milestone 1, commit it as
`docs(editor-4): 4f-1 milestone 3`, and **pause** for the owner's review.

---

# Milestone 4 — Close

### Task 10: In the browser

**Spec:** §6 (the e2e: no SaaS call; a draft with a message step and no connection, the composer, the preview and the
states, with axe, light and dark, at 1280 and 320 px); §5.8.

**Files:**
- Create: `frontend/e2e/composer.spec.ts`, `frontend/e2e/fixtures/message.dewpoint.json`
- Modify: `frontend/playwright.config.ts` (the workflows project runs `composer.spec.ts`),
  `frontend/src/routes/editor/drawer/MessageComposer.tsx` (44 px buttons below 640 px)

**Interfaces:**
- Consumes: `test`, `expect`, `expectAccessible` (`e2e/gate.ts`); the admin's saved state (the foundations project);
  the server's own `slack.send_message@1`.
- Produces: nothing later tasks use.

"Message" is a Slack step without a connection, its title and a field taking `trigger.site`. The specs import it,
open the step and, at 1280 px: the connection's words with Slack's label, the severity, a second line of text and ↑
back, a link checked as it's typed, the preview with its placeholder and button, the draft saved; at 320 px: the
severity in two rows, the targets 44 px, a row's label over its value, no sideways scroll. Both light and dark with
axe. Nothing is published and nothing is sent; the gate fails a request to another origin.

- [ ] **Step 1: Write the specs, and the narrow targets**

Apply:

```diff
diff --git a/frontend/e2e/composer.spec.ts b/frontend/e2e/composer.spec.ts
new file mode 100644
index 00000000..d5cd3a31
--- /dev/null
+++ b/frontend/e2e/composer.spec.ts
@@ -0,0 +1,84 @@
+// SPDX-License-Identifier: Apache-2.0
+// Editor 4f-1 in the browser: the message composer in a step's drawer, behind nginx, under the served CSP, with axe,
+// light and dark, at 1280 and 320 px. Nothing is published and no message is sent (D24): a Slack step without a
+// connection is written and previewed as a draft.
+import type { Page } from "@playwright/test";
+import { expect, expectAccessible, test } from "./gate";
+
+test.describe.configure({ mode: "serial" });
+
+async function tenantId(page: Page): Promise<string> {
+  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
+  return tenants[0]!.id;
+}
+
+/** The message fixture imported as a new workflow, opened on its canvas, its step's drawer open. */
+async function openMessage(page: Page, name: string) {
+  await page.goto(`/t/${await tenantId(page)}/workflows`);
+  await page.getByTestId("workflow-new").click();
+  const dialog = page.getByRole("dialog", { name: "New workflow" });
+  await dialog.getByLabel("Name").fill(name);
+  await dialog.getByRole("radio", { name: /Import from file/ }).check();
+  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/message.dewpoint.json");
+  await dialog.getByRole("button", { name: "Import and open" }).click();
+  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
+  await page.goto(new URL(page.url()).pathname);
+  await page.getByRole("button", { name: /^notify, / }).click();
+  const drawer = page.getByRole("complementary", { name: "notify" });
+  return { drawer, message: drawer.getByRole("group", { name: "Message" }) };
+}
+
+/** The screen meets WCAG 2.2 AA in the light theme and the dark one. */
+async function accessibleBothWays(page: Page, screen: string): Promise<void> {
+  await expectAccessible(page, `${screen}, light`);
+  await page.emulateMedia({ colorScheme: "dark" });
+  await expectAccessible(page, `${screen}, dark`);
+  await page.emulateMedia({ colorScheme: "light" });
+}
+
+test("a message is written in the composer and previewed as Slack lays it out", async ({ page }) => {
+  const { drawer, message } = await openMessage(page, "Composer");
+  await expect(drawer.getByText("No Slack connection yet: an admin adds one.")).toBeVisible({ timeout: 10_000 });
+  await expect(message.getByRole("radio", { name: "Warning" })).toBeChecked();
+  // The text on several lines: Enter starts one at the caret, ↑ goes back up.
+  const text = message.getByLabel("Text", { exact: true });
+  await text.click();
+  await text.press("End");
+  await page.keyboard.press("Enter");
+  await page.keyboard.type("Last seen by its switch.");
+  await expect(message.getByRole("textbox", { name: "Text, line 2" })).toHaveValue("Last seen by its switch.");
+  await page.keyboard.press("ArrowUp");
+  await expect(text).toBeFocused();
+  // A link's address checked as it's typed.
+  await message.getByRole("button", { name: "＋ Add a link" }).click();
+  await message.getByLabel("Link 1 label", { exact: true }).fill("Runbook");
+  const address = message.getByLabel("Link 1 address", { exact: true });
+  await address.fill("ftp://runbook");
+  await expect(message.getByText("A link's address starts with http:// or https://.")).toBeVisible();
+  await address.fill("https://runbook.example.test");
+  await expect(message.getByText("A link's address starts with http:// or https://.")).toHaveCount(0);
+  const preview = drawer.getByRole("region", { name: "Preview in Slack" });
+  await expect(preview.getByText("trigger.site").first()).toBeVisible();
+  await expect(preview.getByText("Runbook")).toBeVisible();
+  await expect(preview.getByText("Severity: warning")).toBeVisible();
+  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
+  await accessibleBothWays(page, "drawer: the message composer");
+});
+
+test("at 320 px the composer stacks a row's parts, its targets 44 px, and stays AA", async ({ page }) => {
+  await page.setViewportSize({ width: 320, height: 720 });
+  const { drawer, message } = await openMessage(page, "Composer narrow");
+  const box = async (name: string) => (await message.getByText(name, { exact: true }).boundingBox())!;
+  const [info, success, warning] = [await box("Info"), await box("Success"), await box("Warning")];
+  expect(success.y).toBe(info.y); // the severity in two rows of two
+  expect(warning.y).toBeGreaterThan(info.y);
+  expect(info.height).toBeGreaterThanOrEqual(44);
+  for (const name of ["Remove field 1", "＋ Add a field"]) {
+    expect((await message.getByRole("button", { name }).boundingBox())!.height, name).toBeGreaterThanOrEqual(44);
+  }
+  const label = (await message.getByLabel("Field 1 label", { exact: true }).boundingBox())!;
+  const value = (await message.getByLabel("Field 1 value", { exact: true }).boundingBox())!;
+  expect(value.y).toBeGreaterThan(label.y); // label over value
+  expect(await drawer.evaluate((el) => el.scrollWidth - el.clientWidth), "the drawer scrolls sideways at 320 px").toBeLessThanOrEqual(0);
+  await accessibleBothWays(page, "drawer at 320 px: the message composer");
+});
diff --git a/frontend/e2e/fixtures/message.dewpoint.json b/frontend/e2e/fixtures/message.dewpoint.json
new file mode 100644
index 00000000..489867de
--- /dev/null
+++ b/frontend/e2e/fixtures/message.dewpoint.json
@@ -0,0 +1,32 @@
+{
+  "format": "dewpoint.workflow",
+  "format_version": 1,
+  "name": "Message",
+  "graph": {
+    "graph_format": 1,
+    "nodes": [
+      {
+        "id": "4f100001-0000-4000-8000-000000000001",
+        "key": "notify",
+        "type": "slack.send_message@1",
+        "config": {
+          "title": { "$value": { "kind": "template", "parts": [{ "text": "AP offline at " }, { "ref": "trigger.site" }] } },
+          "text": "Access point stopped reporting.",
+          "fields": [{ "label": "Site", "value": { "$value": { "kind": "ref", "path": "trigger.site" } } }],
+          "severity": "warning"
+        },
+        "position": { "x": 0, "y": 140 }
+      }
+    ],
+    "edges": [],
+    "settings": {
+      "input_schema": {
+        "type": "object",
+        "properties": { "site": { "type": "string" } },
+        "required": ["site"],
+        "additionalProperties": false
+      }
+    }
+  },
+  "bindings": []
+}
diff --git a/frontend/playwright.config.ts b/frontend/playwright.config.ts
index 3f47210e..e512df15 100644
--- a/frontend/playwright.config.ts
+++ b/frontend/playwright.config.ts
@@ -7,7 +7,7 @@ export default defineConfig({
     { name: "foundations", testMatch: /(foundations|gate)\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
     {
       name: "workflows",
-      testMatch: /(workflows|triggers|simulation|runs|runForm)\.spec\.ts/,
+      testMatch: /(workflows|triggers|simulation|runs|runForm|composer)\.spec\.ts/,
       dependencies: ["foundations"],
       use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
     },
```

```diff
diff --git a/frontend/src/routes/editor/drawer/MessageComposer.tsx b/frontend/src/routes/editor/drawer/MessageComposer.tsx
index 25c093ea..b4de0c62 100644
--- a/frontend/src/routes/editor/drawer/MessageComposer.tsx
+++ b/frontend/src/routes/editor/drawer/MessageComposer.tsx
@@ -39,6 +39,7 @@ function SeverityControl({ spec, value, id, describedBy, invalid, disabled, onCh
 }
 
 const asList = (v: unknown): unknown[] => (Array.isArray(v) ? [...(v as unknown[])] : []);
+const NARROW = "max-sm:min-h-11"; // 44 px targets at 320 (§5.8)
 
 /** The fields' or the links' rows (§5.3): how many of the most, each row's label and value (or address) taking values,
  * its Move up, Move down and Remove named by its number, and Add, disabled at the most with why. */
@@ -85,11 +86,11 @@ function Rows({ spec, value, noun }: { spec: FieldSpec; value: unknown; noun: "f
             </div>
             {drawer.editable && (
               <div className="flex flex-wrap gap-2">
-                <Button size="sm" aria-label={`Move up: ${row}`} disabled={i === 0} onClick={() => move(i, i - 1)}>Move up</Button>
-                <Button size="sm" aria-label={`Move down: ${row}`} disabled={i === items.length - 1} onClick={() => move(i, i + 1)}>
+                <Button size="sm" className={NARROW} aria-label={`Move up: ${row}`} disabled={i === 0} onClick={() => move(i, i - 1)}>Move up</Button>
+                <Button size="sm" className={NARROW} aria-label={`Move down: ${row}`} disabled={i === items.length - 1} onClick={() => move(i, i + 1)}>
                   Move down
                 </Button>
-                <Button size="sm" variant="danger-outline" aria-label={`Remove ${row}`} onClick={() => remove(i)}>Remove</Button>
+                <Button size="sm" variant="danger-outline" className={NARROW} aria-label={`Remove ${row}`} onClick={() => remove(i)}>Remove</Button>
               </div>
             )}
           </div>
@@ -97,7 +98,7 @@ function Rows({ spec, value, noun }: { spec: FieldSpec; value: unknown; noun: "f
       })}
       {drawer.editable && (
         <>
-          <Button ref={add} data-add size="sm" className="self-start" disabled={full} aria-describedby={full ? capId : undefined} onClick={append}>
+          <Button ref={add} data-add size="sm" className={`self-start ${NARROW}`} disabled={full} aria-describedby={full ? capId : undefined} onClick={append}>
             ＋ Add a {noun}
           </Button>
           {full && <p id={capId} className="text-small text-muted">{capWords(noun, max)}</p>}
```

- [ ] **Step 2: Type check and lint them**

Run: the frontend's static checks of "How to run things". Expected: no output (the type check covers `e2e/`, and
ESLint lints it).

- [ ] **Step 3: Run them in the browser**

They need the Compose stack, as CI's e2e job brings it up (`deploy/compose`, the development override, a generated
`.env` that's never printed, `dewpoint admin init`). Locally, building it takes long: ask the owner first. Then, from
`$WT/frontend`: `npx --offline pnpm@12.6.0 exec playwright test` (the foundations project signs the admin in first).
Expected: every spec passes, the two of `composer.spec.ts` among them. A failure is read and fixed test-first. If the
owner prefers, the specs run in CI's e2e job on the PR instead, and the summary says they weren't run locally.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e frontend/playwright.config.ts frontend/src/routes/editor/drawer/MessageComposer.tsx
git commit -m "test(e2e): the message composer in the browser, light and dark, at 1280 and 320 px (4f-1)

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
- `npx --offline pnpm@12.6.0 check:api`: the API's schema, unchanged.

From `$WT/backend`:
- `UV_FROZEN=1 UV_NO_SYNC=1 uv run pytest -q -n 6 tests/plugins tests/engine/graph tests/sdk` (the database the
  plugins' fixtures migrate is the test setup's own, as CI's);
- the backend's static checks of "How to run things".

Then local CodeQL on the head: CI's python and javascript-typescript analyses on a `git archive` of it.

Expected, as on the plan's own check (at the top): the frontend suite, 1496 passed in 108 files (main has 1415 in 104);
ESLint and the type check silent; the build done, the entry 649.9 kB (main 649.7), the editor's shared chunk 361.9 kB
(main 341.9: the composer, its previews and the mirror), the editor's script 146.6 kB; `check:api` passes; the backend's
three suites 1953 passed; ruff, the format check and mypy clean; CodeQL, no finding in either language.

A failure is read and fixed test-first, or reported as it is: never a claim that every check passes when one didn't.

- [ ] **Step 2: The ledger**

Append `### 4f-1, milestone 4 and the final checkpoint (<date>)`: the tasks' commits, each check's result as run (the
suites' counts), whether the e2e spec ran locally or waits for CI, every mid-slice ruling, anything deferred. Commit it
(`docs(editor-4): 4f-1 final checkpoint`), with the trailer.

- [ ] **Step 3: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch:
- against this plan (its Review Focus first) and the spec's §4 to §7, with the boards;
- with the ledger's rulings in view.

Critical and important findings are fixed test-first, once; minor ones are listed. Then **stop**. The summary to the
owner lists the commits, the checks as run, the rulings made mid-slice, the review's findings and what was deferred.
Nothing is pushed and no PR is opened without the owner's word.
