# Editor UI 4c-3b: Triggers, the Screens — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 6.** Nothing is built before the owner approves this plan. Nothing is pushed and no PR is opened without
the owner's OK in chat.

**What revision 2 changes.** A pasted review held revision 1 for six findings, each reproduced on the prototype and now
pinned by a test that failed on revision 1's code:
1. Text held in the panel, typed over an input that has since changed (a field added, a column removed before it, an
   undo), was written as soon as it read, over the change. Now it's never written as it's typed: it stays held and
   says so, until Apply here or Discard, as a step's held text does (ruling 4; Tasks 7, 8).
2. Saving a Mist binding unchanged could change its filter: a topic and another condition became the topic alone, and
   trigger types answering after the form opened gave it the first topic. Now a binding shows by its topic only when
   its filter is that topic alone, else by its conditions, kept as they are, and nothing shows before the endpoint's
   sender is known (ruling 10; Task 11).
3. A filter value didn't read back as itself (`" HQ "` lost its spaces, a quote at each end was dropped). Now the form
   shows each value so that reading it again gives it back exactly (ruling 10; Task 3).
4. An interval no preset says (90 seconds; 72 hours first at 51:00) opened as an empty cron or a time no field takes,
   and blocked every save. Now it opens as itself, kept as it is, and an edit sends the timing only when it changed
   (ruling 8; Tasks 2, 9).
5. A schedule's input field the simple controls can't hold (a list, an object, several types) was sent as text. Now
   it's entered as JSON, its value's type kept, and a choice keeps its value's type (ruling 8; Task 9).
6. Closing a field's editor left focus on the page. Now focus goes back to what opened each part of the input once it
   closes, by mouse or keyboard (ruling 3; Tasks 7, 8, 14).

**What revision 3 changes.** A pasted review held revision 2 for four findings, each reproduced on the prototype and now
pinned by a test that failed on revision 2's code:
1. A whole-number default held for one CSV column, its place taken by a text column (a column removed before it), was
   written there as text once typed: a text default skipped the held edit's check. Now an edit held at a control is
   never written as it's typed over what changed, whatever the column's type now (ruling 4; Task 8).
2. Trigger types that failed to load let a Mist endpoint's webhook be added with no condition: every event. Now a
   sender's endpoint waits for its types to load; when they can't, the form says so with Try again, and adds nothing
   for it (ruling 10; Task 11).
3. An input whose rules its start form's fields can't show (a required field under `allOf`, behind a root `$ref`) gave
   the schedule form no field and an empty input. Now such an input is entered whole, as JSON, and any input can be on
   request (ruling 8; Task 9).
4. Renaming a field remounted its editor: Tab went back to its name, and the first click on Done was lost. Now the
   field's row keeps its identity through a rename, so the editor stays as it is (ruling 3; Task 7).

**What revision 4 changes.** A pasted review held revision 3 for three findings in a schedule's input entered as JSON,
each reproduced on the prototype and now pinned by a test that failed on revision 3's code:
1. A field filled while the version's input was loading was lost when its rules turned the form to JSON, and a switch
   either way sent the other entry's empty input. Now nothing is taken before the version's rules are known, the JSON
   starts from the fields' values, and what's typed goes with a switch either way; JSON no field shows as written stays
   JSON (ruling 8; Task 9).
2. JSON's numbers changed in parsing (`9007199254740993` sent as `…992`, `1e400` as `null`). Now JSON a parse would
   change is refused, in the whole input and in a field, as the draft's is (`parseJson`; ruling 8; Task 9).
3. A key named `__proto__` was dropped (copied key by key, it set the object's prototype instead), and a field of that
   name broke the form. Now the input keeps every key as typed, and a field's value and problem are kept apart from the
   form's own (ruling 8; Task 9).

**What revision 5 changes.** A pasted review held revision 4 for one finding, reproduced on the prototype and now pinned
by a test that failed on revision 4's code: an empty text in the JSON (`{"site": ""}`), moved to the fields, became an
empty control, which means "not given": it was left out, or refused as required. Now an empty text stays in the JSON,
saying no field shows it as written (ruling 8; Task 9).

**What revision 6 changes.** A pasted review held revision 5 for one finding, reproduced on the prototype and now pinned
by a test that failed on revision 5's code: text with a line break in the JSON (`"HQ\nLab"`, CR, CRLF), moved to a
field, lost the break, as a one-line field drops it, and was sent so. Now a value moves to a field only when the field
holds it and reading it back gives the same value; anything else stays JSON, saying no field shows it as written. Spaces
and tabs move as they are (ruling 8; Task 9).

**Goal:** What starts a workflow, set up where it's edited: the start card opens a Triggers panel (the input as form
fields, a Mist event's shape, a CSV file or JSON; live schedules; live webhook bindings), Settings → Webhook endpoints
makes and manages endpoints, New workflow asks what starts it, and the list names each workflow's triggers.

**Architecture:**
- Pure layers first (no screen change): a schedule's timing as the form's presets (`lib/timing.ts`), the trigger
  routes' queries and the words the screens share (`lib/triggers.ts`), the input as fields and a Mist event's shape
  (`lib/input.ts`), the CSV declaration and what a save takes of it (`lib/csv.ts`), the input as JSON
  (`lib/inputJson.ts`), the Triggers panel's held edits (`lib/unapplied.ts`), and endpoints in words
  (`lib/endpoints.ts`).
- Then the screens: the start card and the Triggers panel in the editor's side column (its input, then its schedules
  and webhooks), Settings → Webhook endpoints, New workflow's "What starts it?", and the list's Trigger column.
- The input is the draft's, written through the editor's `change` (undo, saving, conflicts, the leave guard) and held
  as a step's fields are (ruling 113). Schedules, endpoints and bindings are live rows the API writes at once.
- No backend change: 4c-3a (#87, b1183473) built every route and answer this slice uses.

**Tech Stack:** React 19, TypeScript, TanStack Query and Router, Tailwind 4 with the app's tokens, Vitest and Testing
Library, Playwright with the browser gate (`e2e/gate.ts`: CSP, console, axe WCAG 2.2 AA). No new dependency.

**Spec:**
- The outline `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`: §2 "4c" (trigger setup: the manual input
  form and CSV columns, schedules, webhook endpoints and the topic filter), §5 B13, D11 (Settings), §6 (no AI tells),
  D13, D14, D18 (the server checks and classifies), D19 (the browser checks only what a save would refuse), D23 (native
  dialogs, CSP), D24 (no real Mist call).
- The ledger `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`: rulings 42, 43, 56, 68 (triggers are rows; 1b's
  "What starts it?" and 1a's Trigger column), 69 (the start card), 71 (the list's filters and columns), 74 (needs
  attention), 85 (rows don't travel in files), 96 (4c-3's scope), 113 (edits not applied), M32; "Owner, 4c-3 design and
  mockups" (the owner's choices and the open points answered) and 4c-3a's rulings 139–146.
- The D8 mockups the owner signed off: the Design canvas "4c-3 Trigger Mockups", version 21
  (https://claude.ai/artifact/TvL7JjYvqSCMgtGJSmmr3a, private), 18 boards: Main, InputFields, InputMist, InputCsv,
  InputEdit, Schedules, ScheduleForm, ScheduleWhen, Rules, Webhooks, Endpoints, EndpointNew, EndpointOther,
  NewWorkflow, WorkflowsList, ReadOnly, Narrow, NarrowForms.
- The code on `origin/main` (b1183473, with 4c-3a merged), read for this plan (`scratchpad/research-4c3/R8-frontend-
  triggers.md` for the editor, Settings and the list). Every task's code was run on a prototype first
  (`scratchpad/ui4c3/build`, local branch `proto/editor-4c3b`): the unit suite, typecheck, lint, build, and the browser
  gate.

## Global Constraints

- **CSP.** It stays exactly `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src
  'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'`. No inline
  script, no injected `<style>`, no third-party or CDN asset. The browser gate fails any screen that violates it.
- **WCAG 2.2 AA.**
  - Text 4.5:1; boundaries, focus rings and graphics 3:1 (`PAIRS` in `src/styles/tokenNames.ts`).
  - Every control has a visible label, and its hint and errors describe it; a visible label is in the control's
    accessible name (2.5.3): the start card's name starts with what it shows.
  - Everything is reachable and operable by keyboard; a pointer target is 24 px at least (2.5.8).
  - Axe checks each new screen and dialog in the browser gate; Settings → Webhook endpoints and the panel's forms
    reflow at 320 px (1.4.10).
- **No AI tells** (outline §6; the vitest guard `src/test/aiTells.ts`): no pills but data pills (topics and filter
  clauses are words), no toasts for routine success, no tinted icon tiles, no eyebrows, sentence case (1b's cards are
  "By hand", "On a schedule", "A Mist webhook", "A CSV file"). A section is set off by a hairline, never a coloured
  border.
- **Dependencies.** None new.
- **No real Mist or SaaS call, ever** (D24). Unit tests use made-up trigger types and schedules
  (`src/test/triggers.ts`); the browser flows make and bind an endpoint but never send to it, and their schedule is
  simulated and deleted.
- **No backend change**, so no migration and no OpenAPI change: `check:api` stays clean.
- **Secrets.**
  - An endpoint's token or signing secret is shown once, in the page's state, never kept, logged or written anywhere.
  - A schedule's stored input is never shown back (4c-3a): editing keeps it, or replaces it whole.
  - A sensitive field has no default and no Choice: either would be a literal written into the workflow (§3.8).
  - Logs name an exception's type only. No draft, input or secret is kept in browser storage.
- **The server decides** (D18): what an input schema means, a CSV declaration's rules (unique headers, a required
  column's default), whether a schedule's timing or input is taken, an endpoint's fields, a binding's filter, which
  schedules a draft would break. The client checks only what a save would refuse (D19) and what it needs to send a
  request.
- **Verify, don't remember.** Check every library API against the installed package, and every API path and body
  against `src/api/schema.d.ts`.
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker. Nothing is pushed and no PR is opened
  without the owner's OK in chat.

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the test named, in
the task that owns the code.

- **Text held while the input changes under it** (a field added, a column removed before it, an undo). It's never
  written over the change, as it's applied or as it's typed, until Apply here or Discard. Task 5: `never writes into a
  field or a column that went, and is stale once a removal moved the columns`; Task 7: `never writes JSON typed over an
  input that changed since, until Apply here`, and the editor's own `never writes JSON typed over an input an undo
  changed since, until Apply here`; Task 8: `never writes a header typed for a column whose place another took since,
  until Apply here or Discard`, `never writes a default typed for a column whose place a column of another type took
  since`.
- **A field renamed while its default is held.** The default lands on the renamed field, applied before the rename;
  typed for a field that's gone since, it's never written (it would make one up). Task 5: `settles with the step's
  edits, a field's default before its rename`.
- **JSON a save would refuse** (a CSV declaration out of bounds, a number past what the draft keeps). It's held with
  why, never written: the save would fail whole. Task 5: `applies JSON text as the input, or says where it breaks and
  what a save would refuse`; Task 4: `says what the save would refuse, so nothing refused is written`.
- **A schedule or a webhook saved with what its form can't show.** Only what changed is sent, and nothing is guessed: a
  stored input, a timing no preset says and a filter are kept exactly; an input whose rules its fields can't show is
  entered whole, as JSON, settled before anything is typed and carried between the two ways, every key and number as
  typed; a sender's topics wait for its types, and their failure adds nothing. Task 3: `shows every value so that
  reading it again gives it back exactly: spaces, quotes and escapes kept`; Task 9: `edits one: its stored input kept
  unless replaced whole, and only what changed sent`, `keeps a timing no preset says, $title, as it is, and sends the
  mode alone when only it changes`, `takes the whole input as JSON when the form can't show it field by field ($what)`,
  `waits for the version's input before taking any, then starts its JSON from the fields' defaults`, `carries what's
  entered between the fields and the JSON, and keeps JSON no field can show`, `keeps an empty text in the JSON, required
  or not: a field's empty control means not given`, `keeps text with a line break in the JSON, and moves spaces and tabs
  to a field as they are`, `refuses JSON whose numbers parsing would change, in the whole input and in a field`, `keeps
  a key named __proto__, typed in the JSON or as a field's name`; Task 11: `keeps every condition of a filter a topic
  can't say, and saves it unchanged as it was`, `waits for what an endpoint sends before showing its topic, so a save
  never changes it`, `says when what an endpoint sends can't be loaded, and adds nothing for it until it is`.
- **A Mist binding whose published input isn't its topic's shape.** It says the events may be refused, never that they
  don't fit (a looser input may take them), and offers the shape for the draft. Task 11: `says each one's sender and
  when it runs, and what the published input makes of its events`.

## Rulings this plan proposes

These join the ledger as rulings 147 onward once the owner accepts the plan. Each says why, and what it costs if
it's wrong.

1. **The start card opens Triggers** (Task 7).
   - A click or Enter opens the Triggers panel, for every role; the card says `aria-expanded`.
   - It sums up what starts a run: "By hand · 2 schedules · 1 webhook", "By hand, with a CSV file" (the draft's file,
     the live rows; the workflow's own counts until they're read). Its name starts with that: "Start: by hand, 2
     schedules. Open its triggers".
   - Its "+" stays the empty canvas's alone, as now, named "Add the first step" as now: the Main board's "+" under a
     card with steps would sit on the entry edge's own "+". A step beside the first ones is `A` on the card, or the
     toolbar's ＋ Add step with the card focused: its full-size form (WCAG 2.5.8), amending M32.
   - Why: the owner's design (the start card opens Triggers). Cost: the 4b flows that added a step by pressing Enter on
     the card press `A` (their browser flows change).
2. **The Triggers panel** (Tasks 7, 9, 11). A side panel, as Declassify: Input, Schedules and Webhooks in one column;
   Close and Escape give focus back to the start card. A viewer or an operator sees it all, read only, and one line
   says why (the ReadOnly board); so does a version's view, its input the version's. A new workflow opens on it
   (`?triggers`). Why: the Main board. Cost: none known.
3. **The input as form fields** (Task 7).
   - `settings.input_schema`'s own fields of a plain type (Text, Whole number, Number, Yes or no, Choice, Date and time)
     are rows a field editor changes; any other (a list, an object of fields, one with rules of its own) is a row the
     list shows read only, and Edit as JSON changes.
   - Each control writes as it changes, a control's typing one undo step (ruling 8's marks). A name is held while it's
     typed and applied when focus leaves it or Enter is pressed; the list writes identifier names only (JSON writes
     any). A number's default is held while it doesn't parse.
   - A sensitive field has no default and can't be a Choice (the server's `sensitive.default`, `sensitive.literal`): the
     editor takes the default away and says why, as the boards do.
   - Focus goes back to what opened a part once it closes (WCAG 2.4.3): to a field's or a column's Edit, to ＋ Field or
     ＋ Column once it's removed, to Edit as JSON, to "Use a Mist event…"; an editor opened takes it on its first
     control, and the JSON on its text. A rename keeps the field's editor as it is: focus where it went, a click in it
     landing.
   - Why: the InputFields board. Cost: a field with a rule the list doesn't know is edited as JSON.
4. **The panel's held text is the editor's** (Task 5): ruling 113, for workflow settings. JSON being typed, a field's
   name, a column's header or name, a number, a CSV file's limits: held under the editor's `TRIGGERS` ("triggers") at a
   pointer into the settings; counted in the toolbar, listed as "Triggers · …", "Go to it" opening the panel there,
   applied at every exit as a step's, never into a field or a column that went, and stale once a removal moved the
   columns. Typed over what has since changed (an undo, another edit, a column removed before it), it's never written
   as it's typed, whatever the type of what's now there: it stays held, said stale, until Apply here or Discard, as a
   step's does (ruling 18). Why: ruling 113
   says what counts, not where. Cost: one more kind of place in the held edits' code.
5. **Nothing a save would refuse is written** (Tasks 4, 5, 7). A draft's save parses the whole graph strictly
   (engine/graph/model.py's `CsvSettings`, `CsvColumn`), so a CSV declaration outside its bounds would fail the save
   whole: `csvProblem` holds the panel's writes to them (1 to 200 columns; a header of 1 to 200 characters and a name of
   1 to 63; a known type; at most 200 values of at most 200 characters; 1 to 10,000 rows; 1 byte to 5 MB), as
   `admission` holds a step's writes to the graph's. Every other rule (unique headers, an identifier name, a required
   column's default) is the server's to say, at its field. Why: D19. Cost: two copies of the bounds, the server's and
   this one, kept equal by hand.
6. **A Mist event's shape** (Task 8). "Use a Mist event…" copies a topic's schema from `/trigger-types` into the draft
   whole, one undo step. While the input is a topic's shape (equal, keys' order aside), it shows as that event's shape,
   read only: its own fields, then one event's, "may be missing" where not required. "Use form fields instead" gives an
   empty list. Why: the InputMist board. Cost: an input edited away from the shape by one key shows as fields.
7. **The CSV file** (Task 8). "＋ CSV file" declares one text column ("Column 1", `column_1`): a declaration has one at
   least, so its last column can't be removed (the file can). A column is edited in its row; a required column's
   default shows the server's problem with "Clear the default" and "Make it optional" (the InputEdit board). Why: the
   boards. Cost: none known.
8. **Schedules** (Task 9).
   - Each says its timing in words ("Every day at 07:00", "At 0 */6 * * 1-5"), its zone where one applies (a cron's),
     its mode, off, custom, synced; then what its sync proves (4c-3a ruling 6): failed (its previous time may still
     fire; never confirmed, it may already fire, or isn't running yet when nothing ever unpaused it), saved but not yet
     confirmed; and the firings it missed, as counted.
   - Its form's When writes a cron in the schedule's zone (Every day at, Weekdays at, Custom) or an interval counted in
     UTC (Every N minutes, Every N hours); a cron no preset says opens as Custom. An interval no preset says back
     exactly (not whole minutes, a first run past the first day) opens as itself, "Every 90 seconds, as it is", kept
     until another When is chosen; an edit sends the timing only when it changed here. The time zone is the browser's
     list (its own zone first), the server checking it. Each refusal of the timing (`schedule_invalid`'s codes) is said
     at its field, in the boards' words.
   - Its input is entered on the published version's start form, a required field checked before anything is sent: a
     field the simple controls can't hold (a list, an object, several types or none) as JSON, its value's type kept; a
     choice's value keeps its type; what isn't given is left out. An input whose rules the fields can't show (any
     keyword at its root but its properties, required and annotations: `allOf`, `$ref`, `if`…) is entered whole, as
     JSON, an object; so is any input, on request ("Enter it as JSON"). How it's entered is settled before anything is
     typed; what's typed goes with a switch either way, but a value no field shows as written (an empty text: an empty
     control is "not given"; a line break: a one-line field drops it) stays JSON; JSON a parse would change is refused;
     every key is kept as typed, `__proto__` too. Editing one keeps its stored input unless "Replace the input…"
     replaces it whole; only what changed is sent.
   - ＋ Schedule is disabled, with why, before a first publish and while the published version takes a CSV file.
   - Why: the Schedules, ScheduleForm, ScheduleWhen and Rules boards. Cost: a timing no preset says is kept, not edited
     (choosing a preset replaces it); a structured input is typed as JSON.
9. **Settings → Webhook endpoints** (Task 10).
   - A tab and a page (`/t/$tenantId/settings/webhooks`), and a palette item. Each endpoint's name, sender, proof,
     workflows, waiting events, on or off and path; at 320 px, stacked rows. Its details: the workflows it starts (with
     their topics), its path "on your Dewpoint webhook address", Copy the path, Edit, Rotate….
   - A Mist endpoint is made from its name (and optional limits); another sender's says its proof, where its events are
     and where their ids are, each fixed once made, and the form says what will be fixed before Create.
   - A token or a signing secret is shown once, in a status region; rotating asks first. Turned off, never deleted.
   - "This deployment doesn't receive webhooks yet: only development deployments do, for now." outside a development
     deployment.
   - The Workflows count reads each endpoint's bindings: one request an endpoint.
   - Why: the Endpoints, EndpointNew and EndpointOther boards. Cost: a tenant with many endpoints makes as many reads.
10. **Webhooks** (Task 11).
    - Each binding with its endpoint, its sender and when it runs (B13). A Mist binding is compared with the published
      version's input: when that isn't the topic's shape, "Version 3's input isn't device-events' shape: events it
      doesn't fit are refused", never that they don't fit (a looser input may take them); "Use device-events' shape for
      the input" changes the draft, then "In the draft: it applies once published". Another sender's: "Its events have
      no known shape: the input must fit them, or each is refused". Before a first publish: its events are refused.
    - Its form: an endpoint (one that already starts this workflow can't be picked), then a Mist topic and "Use this
      topic's shape for the input", or another sender's conditions (8 at most; a value as written: 1 a number, true a
      yes, "1" in quotes text).
    - **Editing one** isn't on a board: the same form, its endpoint fixed, with Save and "Remove the webhook…" asked
      first, as a schedule's delete is. A binding shows by its topic only when its filter is that topic alone; any other
      filter shows as its conditions, kept as they are; nothing shows before the endpoint's sender is known, and when
      that can't be loaded the form says so, with Try again, and adds nothing for that endpoint. Each value shows so
      that reading it again gives it back exactly: `" HQ "` keeps its spaces, text in quotes is JSON text.
    - Why: the Webhooks and Rules boards, and the owner's ruling (warned at the binding). Cost: editing is the boards'
      form, extrapolated.
11. **New workflow: "What starts it?"** (Task 12). By hand, On a schedule, A Mist webhook (an endpoint made for it and a
    topic; disabled, saying where one's made, while there's none), A CSV file; then Blank or Import from file; then the
    name, in the board's order, focus starting on what starts it.
    - Blank with a Mist webhook gives the input the topic's shape; with a CSV file, a file of one column; an import
      keeps the file's input (the owner's ruling), its webhook still bound. It opens on its Triggers.
    - What fails once the workflow is made (the draft's seed, the binding) is said in the dialog, with "Open <name>".
    - Why: the NewWorkflow board and the owner's choices. Cost: a workflow can be made without its webhook, said.
12. **The list's Trigger column** (Task 13): after Name, from the summary's `triggers` (4c-3a ruling 141): "Webhook",
    "2 schedules · 1 webhook", "CSV file" (the published version's), "By hand"; why a workflow needs attention, under
    its name. Ruling 71's filters and columns stay: the board's On and Off filters aren't adopted, and "Not published"
    stays the Version column's. Why: the WorkflowsList board within ruling 71. Cost: none known.

## File Structure

New (all under `frontend/`):
- `src/lib/timing.ts`: a schedule's timing as the form's When, and in words.
- `src/lib/triggers.ts`: the trigger routes' queries and writes, and the words the panel, Settings and the list share.
- `src/lib/input.ts`: the input as form fields, the settings' writer, a Mist event's shape.
- `src/lib/csv.ts`: the CSV declaration, what a save takes of it, its columns and limits.
- `src/lib/inputJson.ts`: the input as JSON, and where a settings pointer is in it.
- `src/lib/endpoints.ts`: a new endpoint's form as the API takes it, and endpoints in words.
- `src/test/triggers.ts`: made-up trigger types, a schedule, an endpoint and a binding for tests.
- `src/routes/editor/triggers/`: `context.ts` (what the panel's parts share), `parts.tsx` (a section, problems at a
  place, a checkbox, a Choice's values), `TriggersPanel.tsx`, `InputSection.tsx`, `FieldEditor.tsx`, `InputJson.tsx`,
  `MistEvent.tsx`, `CsvSection.tsx`, `SchedulesSection.tsx`, `ScheduleForm.tsx`, `WebhooksSection.tsx`,
  `WebhookForm.tsx`, and `harness.tsx` (tests only).
- `src/routes/WebhookEndpoints.tsx`, `src/routes/EndpointForm.tsx`: Settings → Webhook endpoints.
- `e2e/triggers.spec.ts`: the browser flows.
- Tests beside each: `*.test.ts(x)`.

Changed:
- `src/lib/unapplied.ts`: the Triggers panel's held edits (`TRIGGERS`).
- `src/routes/editor/StartCard.tsx`, `Canvas.tsx`, `Editor.tsx`, `LazyEditor.tsx`: the start card opens the panel; the
  panel in the side column; a new workflow opens on it.
- `src/routes/NewWorkflow.tsx`: "What starts it?". `src/routes/Workflows.tsx`: the Trigger column.
- `src/components/Field.tsx`: `TextArea`, a labelled text of several lines (a schedule's JSON input).
- `src/router.tsx`, `src/routes/Settings.tsx`, `src/components/CommandPalette.tsx`: Webhook endpoints' tab and route;
  the editor's `?triggers`.
- `src/routes/editor/Editor.test.tsx`, `src/routes/NewWorkflow.test.tsx`, `src/routes/Workflows.test.tsx`: the changes'
  tests. `e2e/workflows.spec.ts`, `playwright.config.ts`: the 4b flows follow the start card; the new flows run.
- `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`: this plan accepted, its milestones, its rulings.

## Milestones

- **Milestone 1 — the pure layers** (Tasks 1–6). No screen changes. Then the whole unit suite, typecheck and lint.
- **Milestone 2 — the Triggers panel and its input** (Tasks 7–8). **Pause:** screenshots of the start card and the
  panel (fields, a field edited, a Mist event's shape, a CSV file, JSON held), light and dark, at 1280 and 320 px,
  beside the boards, for the owner's review before the live rows are built.
- **Milestone 3 — schedules, endpoints, webhooks** (Tasks 9–11).
- **Milestone 4 — New workflow and the list** (Tasks 12–13).
- **Milestone 5 — the browser, every check, the final checkpoint** (Task 14). **Pause:** a fresh reviewer, the
  screenshots, the summary; then stop. Nothing is pushed without the owner's OK.

## How to run things

From `frontend/` (the locked packages, installed once with `npx --offline pnpm@12.6.0 install --frozen-lockfile
--offline`):
- one test file: `npx --offline pnpm@12.6.0 exec vitest run <file>`; the unit suite: `npx --offline pnpm@12.6.0 test`;
- `npx --offline pnpm@12.6.0 typecheck`, `lint`, `check:api`, `build`;
- the browser gate on the isolated Compose stack: `UI4_WT=<worktree> scratchpad/plan-4c3b/gate/e2e.sh [spec]` (a fresh
  database and rebuilt images, then Playwright at `http://localhost:18080`; with the image layers cached, the trigger
  flows alone take about 2 minutes and every flow about 4; images built from nothing take longer: asked first);
- local CodeQL: `scratchpad/codeql/scan.sh <sha>` (about 2 minutes).
The backend is untouched: its suite doesn't run.

One test older than this plan can fail under load: `Editor.test.tsx`'s "says when the latest edits aren't saved" reads
its announcement as soon as "Not saved" shows, and the effect that makes the announcement can land after it. The plan's
dry run saw it fail once, while another file's tests were failing beside it, and pass in each rerun. If it fails, rerun
the file alone; it isn't this plan's to change.

## Executing this plan

Proposed: inline, in one session, with the owner's reviews at the milestone pauses (the panel's parts build on each
other's interfaces, and a fresh context per task would re-read most of them); the owner chooses. Each task is test
first: its tests are written and seen to fail as its Step 2 says, then its code, then they pass. A block is applied
exactly: **Create** writes the file; **In** … **replace** … **with** replaces text that occurs exactly once (the blocks
of a file in the order given). Where the installed package or the code differs, the executor adapts it test first and
records the difference as a mid-slice ruling in the ledger (M80 onward). The branch is settled with the owner at the
start; proposed: `feat/editor-4c3b` from `origin/main` (b1183473 on), in its own worktree, this plan's docs branch
merged in first. A later main is merged in, never rebased.

Every block below was produced from a staged run of this plan (each task's commit typechecked, linted and its tests
passing; the last one identical to the prototype), and the plan's own text was applied once more from scratch, task by
task, by a dry run whose red and green results are each task's Expected lines.

---

# Milestone 1 — the pure layers

### Task 1: The branch and the ledger

The work's place and its record: the branch the owner settles at the start, the locked packages, and the ledger
section that says this plan is accepted, with its rulings as the owner ruled them.

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (append at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger sections later steps append to (`### 4c-3b, milestone N`), and rulings 147 onward.

- [ ] **Step 1: The branch**

The owner settles the branch at the start; proposed: a worktree on `feat/editor-4c3b` from `origin/main` (b1183473 or
newer), this plan's docs branch merged in first (its one commit, the plan). Then, from `frontend/`, the locked packages
only:

```bash
npx --offline pnpm@12.6.0 install --frozen-lockfile --offline
```

Expected: the packages the lockfile names, from the local store; nothing fetched, nothing added.

- [ ] **Step 2: The ledger**

Append to `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`:

````markdown
### 4c-3b plan accepted (<date>, in chat)

`docs/superpowers/plans/2026-10-11-editor-ui-4c3b-triggers-ui.md`, revision <N>, accepted by the owner, executed
<inline, with pauses | as the owner chose>, on `<branch>`. Its rulings join this ledger as ruled:

147. <ruling 1, "The start card opens Triggers", copied from the plan's "Rulings this plan proposes", as accepted>
…
158. <ruling 12, "The list's Trigger column", as accepted>

Mid-slice rulings, where the code base differs from a step: M80 onward.
````

Each ruling is copied whole, its "Why" and "Cost" included, with any change the owner made at acceptance. Run
`awk 'length > 120' docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md | tail -3`: the lines appended print
nothing (the ledger keeps lines within 120 characters; its tables are older).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): the 4c-3b plan accepted (rulings 147-158)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: A schedule's timing (`lib/timing.ts`)

What a schedule's form writes and reads (ruling 8): presets over the API's two kinds of timing, a cron in the schedule's
own zone (Every day at, Weekdays at, Custom) or an interval counted in UTC (Every N minutes, Every N hours); a cron no
preset says reads back as Custom, an interval no preset says back exactly as kept, as it is (the review of revision 1).
A timing's title in words, an interval's in its largest whole unit; when an interval runs (the ScheduleWhen board's
sentences), the words for each refusal the API answers by code (`schedule_invalid`), the catch-up choices within the
API's bounds, and the zones offered, the browser's first. Pure functions, no screen.

**Files:**
- Create: `frontend/src/lib/timing.test.ts`
- Create: `frontend/src/lib/timing.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `Preset` (with `"kept"`), `When { preset; every; past; first; time; cron }`, `Timing { cron; every_s;
  offset_s }`, `blankWhen(preset)`, `whenOf(timing)` (read back exactly), `timingOf(when): { timing } | { field: keyof
  When | "when"; problem }`, `timingTitle(timing)`, `intervalWords(when)`, `TIMING_WORDS` (by the API's code),
  `CATCHUP`, `MIN_INTERVAL`, `MAX_INTERVAL`, `secondsOf(time)`, `zones(browser?)`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/lib/timing.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { TIMING_WORDS, blankWhen, intervalWords, timingOf, timingTitle, whenOf, zones } from "./timing";

const cron = (c: string) => ({ cron: c, every_s: null, offset_s: 0 });
const every = (s: number, offset = 0) => ({ cron: null, every_s: s, offset_s: offset });

describe("a schedule's timing as the form's When", () => {
  it("reads a daily or weekday cron back as its preset, and any other as Custom", () => {
    expect(whenOf(cron("0 7 * * *"))).toMatchObject({ preset: "daily", time: "07:00" });
    expect(whenOf(cron("30 8 * * 1-5"))).toMatchObject({ preset: "weekdays", time: "08:30" });
    expect(whenOf(cron("0 */6 * * 1-5"))).toMatchObject({ preset: "custom", cron: "0 */6 * * 1-5" });
    expect(whenOf(cron("0 9 1 * MON"))).toMatchObject({ preset: "custom" });
  });

  it("reads an interval back as minutes or hours, with where it starts", () => {
    expect(whenOf(every(900, 300))).toMatchObject({ preset: "minutes", every: "15", past: "5" });
    expect(whenOf(every(21_600, 9000))).toMatchObject({ preset: "hours", every: "6", first: "02:30" });
    expect(whenOf(every(5400, 4500))).toMatchObject({ preset: "minutes", every: "90", past: "75" });
  });

  it("keeps an interval no preset writes back exactly, as it is", () => {
    // Not whole minutes, or a first run past the first day: the API takes both (the review of revision 1).
    for (const t of [every(90), every(3600, 30), every(72 * 3600, 51 * 3600)]) {
      expect(whenOf(t).preset).toBe("kept");
      expect(timingOf(whenOf(t))).toEqual({ field: "when", problem: "Choose when it runs." });
    }
  });

  it("gives back exactly the interval it read, for every preset it reads one as", () => {
    for (const t of [every(60), every(900, 300), every(5400, 4500), every(7200, 5400), every(21_600, 9000), every(366 * 86_400, 86_340)]) {
      const w = whenOf(t);
      expect(w.preset).not.toBe("kept");
      expect(timingOf(w)).toEqual({ timing: t });
    }
  });

  it("writes each preset as the API takes it, a cron in the zone or an interval in UTC", () => {
    expect(timingOf({ ...blankWhen("daily"), time: "07:00" })).toEqual({ timing: cron("0 7 * * *") });
    expect(timingOf({ ...blankWhen("weekdays"), time: "09:05" })).toEqual({ timing: cron("5 9 * * 1-5") });
    expect(timingOf({ ...blankWhen("minutes"), every: "15", past: "5" })).toEqual({ timing: every(900, 300) });
    expect(timingOf({ ...blankWhen("hours"), every: "6", first: "02:30" })).toEqual({ timing: every(21_600, 9000) });
    expect(timingOf({ ...blankWhen("custom"), cron: "  0 9   1 * MON " })).toEqual({ timing: cron("0 9 1 * MON") });
  });

  it("round-trips what it writes", () => {
    for (const w of [
      { ...blankWhen("daily"), time: "23:59" },
      { ...blankWhen("weekdays"), time: "00:00" },
      { ...blankWhen("minutes"), every: "20", past: "0" },
      { ...blankWhen("hours"), every: "1", first: "00:45" },
    ]) {
      const made = timingOf(w);
      expect("timing" in made && whenOf(made.timing)).toMatchObject(w);
    }
  });

  it("says which field can't be written yet, and why, before anything is sent", () => {
    expect(timingOf({ ...blankWhen("minutes"), every: "0" })).toEqual({ field: "every", problem: "A whole number of minutes, at least 1." });
    expect(timingOf({ ...blankWhen("minutes"), past: "a" })).toEqual({ field: "past", problem: "A whole number of minutes." });
    expect(timingOf({ ...blankWhen("hours"), every: "1.5" })).toEqual({ field: "every", problem: "A whole number of hours, at least 1." });
    expect(timingOf({ ...blankWhen("hours"), first: "25:00" })).toEqual({ field: "first", problem: "A time, like 02:30." });
    expect(timingOf({ ...blankWhen("daily"), time: "7" })).toEqual({ field: "time", problem: "A time, like 07:00." });
    expect(timingOf({ ...blankWhen("custom"), cron: " " })).toEqual({ field: "cron", problem: "A cron, like 0 9 * * MON." });
  });
});

describe("a timing in words", () => {
  it("titles a schedule as its preset says it, or by its cron", () => {
    expect(timingTitle(cron("0 7 * * *"))).toBe("Every day at 07:00");
    expect(timingTitle(cron("30 8 * * 1-5"))).toBe("Weekdays at 08:30");
    expect(timingTitle(every(900, 300))).toBe("Every 15 minutes");
    expect(timingTitle(every(60))).toBe("Every minute");
    expect(timingTitle(every(3600))).toBe("Every hour");
    expect(timingTitle(every(21_600))).toBe("Every 6 hours");
    expect(timingTitle(cron("0 */6 * * 1-5"))).toBe("At 0 */6 * * 1-5");
    expect(timingTitle(every(90))).toBe("Every 90 seconds");
    expect(timingTitle(every(72 * 3600, 51 * 3600))).toBe("Every 72 hours");
    expect(timingTitle(every(5400, 4500))).toBe("Every 90 minutes");
  });

  it("says when an interval runs, as the ScheduleWhen board does, and that it has no time zone", () => {
    expect(intervalWords({ ...blankWhen("minutes"), every: "15", past: "5" })).toBe(
      "Minutes, at least 1. Runs at :05, :20, :35 and :50 of every hour. An interval is the same everywhere, so it has no time zone.",
    );
    expect(intervalWords({ ...blankWhen("hours"), every: "6", first: "02:30" })).toBe(
      "Runs at 02:30, 08:30, 14:30 and 20:30 UTC, every day. At most every 366 days.",
    );
    expect(intervalWords({ ...blankWhen("hours"), every: "2", first: "03:00" })).toBe(
      "The first run must fall within the first 2 hours of the day: 03:00 is the same as 01:00.",
    );
    expect(intervalWords({ ...blankWhen("minutes"), every: "7", past: "2" })).toBe(
      "Minutes, at least 1. Every 7 minutes, counted from midnight UTC. An interval is the same everywhere, so it has no time zone.",
    );
    expect(intervalWords({ ...blankWhen("minutes"), every: "15", past: "20" })).toBe("Past the hour is less than the interval: 0 to 14.");
    expect(intervalWords({ ...blankWhen("minutes"), every: "x" })).toBeNull();
  });

  it("has words for every timing refusal the API answers", () => {
    const codes = ["cron_fields", "cron_syntax", "cron_range", "cron_day_fields", "timing_missing", "timing_both",
      "interval_too_short", "interval_too_long", "interval_offset", "time_zone_unknown", "catchup_window"];  // prettier-ignore
    expect(Object.keys(TIMING_WORDS).sort()).toEqual([...codes].sort());
    expect(TIMING_WORDS.cron_day_fields).toBe("Choose a day of the month or a day of the week, not both: put * in one of them.");
  });

  it("offers the browser's zone first, then every zone, UTC among them", () => {
    const offered = zones("Asia/Tokyo");
    expect(offered[0]).toBe("Asia/Tokyo");
    expect(offered).toContain("UTC");
    expect(offered).toContain("America/New_York");
    expect(new Set(offered).size).toBe(offered.length);
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/timing.test.ts`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  no tests`. The run can't import `./timing`: it doesn't exist yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/lib/timing.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// A schedule's timing in words, and as the form's "When" (4c-3b; the mockups' ScheduleForm and ScheduleWhen boards):
// presets over the API's two kinds, a cron in the schedule's own time zone or an interval counted in UTC
// (apps/schedules.py). Only what the form needs to write a request is checked here: the API checks the timing and
// answers each refusal as a field and a code, which `timingWords` says.

/** The form's choices for "When": each writes a cron or an interval; "kept" is an interval none of them says, kept as it
 * is until another is chosen. */
export type Preset = "minutes" | "hours" | "daily" | "weekdays" | "custom" | "kept";

/** What "When" holds, as typed: the form's own state, never sent as is. */
export interface When {
  preset: Preset;
  every: string; // minutes or hours
  past: string; // minutes past the hour, for "minutes"
  first: string; // HH:MM, in UTC, for "hours"
  time: string; // HH:MM, in the time zone, for "daily" and "weekdays"
  cron: string; // for "custom"
}

/** A timing as the API takes it: a cron or an interval, never both. */
export interface Timing {
  cron: string | null;
  every_s: number | null;
  offset_s: number;
}

export const MIN_INTERVAL = 60;
export const MAX_INTERVAL = 366 * 24 * 3600;
export const CATCHUP = [
  { value: 60, label: "1 minute" },
  { value: 600, label: "10 minutes" },
  { value: 3600, label: "1 hour" },
  { value: 21_600, label: "6 hours" },
  { value: 86_400, label: "24 hours" },
] as const;

const pad = (n: number) => String(n).padStart(2, "0");
const clock = (seconds: number) => `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor((seconds % 3600) / 60))}`;
const TIME = /^([01]\d|2[0-3]):([0-5]\d)$/;
const WHOLE = /^[1-9]\d{0,6}$/;
const DAILY = /^([0-5]?\d) ([01]?\d|2[0-3]) \* \* (\*|1-5)$/;

/** A time typed as HH:MM, as seconds into the day; null when it isn't one. */
export function secondsOf(time: string): number | null {
  const m = TIME.exec(time.trim());
  return m ? Number(m[1]) * 3600 + Number(m[2]) * 60 : null;
}

const whole = (text: string): number | null => (WHOLE.test(text.trim()) ? Number(text.trim()) : null);
const natural = (text: string): number | null => (/^\d{1,7}$/.test(text.trim()) ? Number(text.trim()) : null);

/** A blank "When" of a preset, as a new schedule starts. */
export const blankWhen = (preset: Preset = "daily"): When => ({ preset, every: "15", past: "0", first: "00:00", time: "07:00", cron: "" });

/** A schedule's timing as the form shows it, read back exactly: a cron no preset says opens as Custom; an interval no
 * preset says (not whole minutes, or a first run past the first day) opens as kept, as it is (the review of revision 1). */
export function whenOf(t: Timing): When {
  const blank = blankWhen();
  if (t.cron !== null) {
    const m = DAILY.exec(t.cron.trim());
    if (!m) return { ...blank, preset: "custom", cron: t.cron };
    return { ...blank, preset: m[3] === "*" ? "daily" : "weekdays", time: `${pad(Number(m[2]))}:${pad(Number(m[1]))}` };
  }
  const every = t.every_s ?? 0;
  if (t.offset_s % 60 !== 0) return { ...blank, preset: "kept" };
  if (every % 3600 === 0) return t.offset_s < 86_400 ? { ...blank, preset: "hours", every: String(every / 3600), first: clock(t.offset_s) } : { ...blank, preset: "kept" };
  if (every % 60 === 0) return { ...blank, preset: "minutes", every: String(every / 60), past: String(t.offset_s / 60) };
  return { ...blank, preset: "kept" };
}

/** What a "When" asks for, or why it can't be written yet: a field of its own and the words for it. */
export function timingOf(w: When): { timing: Timing } | { field: keyof When | "when"; problem: string } {
  switch (w.preset) {
    case "minutes":
    case "hours": {
      const unit = w.preset === "minutes" ? 60 : 3600;
      const n = whole(w.every);
      if (n === null) return { field: "every", problem: w.preset === "minutes" ? "A whole number of minutes, at least 1." : "A whole number of hours, at least 1." };
      if (w.preset === "minutes") {
        const past = w.past.trim() === "" ? 0 : natural(w.past);
        if (past === null) return { field: "past", problem: "A whole number of minutes." };
        return { timing: { cron: null, every_s: n * unit, offset_s: past * 60 } };
      }
      const first = secondsOf(w.first);
      if (first === null) return { field: "first", problem: "A time, like 02:30." };
      return { timing: { cron: null, every_s: n * unit, offset_s: first } };
    }
    case "daily":
    case "weekdays": {
      const at = secondsOf(w.time);
      if (at === null) return { field: "time", problem: "A time, like 07:00." };
      const days = w.preset === "daily" ? "*" : "1-5";
      return { timing: { cron: `${(at % 3600) / 60} ${Math.floor(at / 3600)} * * ${days}`, every_s: null, offset_s: 0 } };
    }
    case "custom":
      if (w.cron.trim() === "") return { field: "cron", problem: "A cron, like 0 9 * * MON." };
      return { timing: { cron: w.cron.trim().split(/\s+/).join(" "), every_s: null, offset_s: 0 } };
    case "kept": // never written: the form sends no timing while it's kept
      return { field: "when", problem: TIMING_WORDS.timing_missing! };
  }
}

/** A schedule's timing, as its title: "Every day at 07:00", "Every 15 minutes", "Every 90 seconds", or a cron no preset
 * says as itself, "At 0 9 1 * *". An interval is titled in its largest whole unit. */
export function timingTitle(t: Timing): string {
  if (t.cron === null) {
    const s = t.every_s ?? 0;
    if (s % 3600 === 0) return s === 3600 ? "Every hour" : `Every ${s / 3600} hours`;
    if (s % 60 === 0) return s === 60 ? "Every minute" : `Every ${s / 60} minutes`;
    return `Every ${s} seconds`;
  }
  const w = whenOf(t);
  if (w.preset === "daily") return `Every day at ${w.time}`;
  if (w.preset === "weekdays") return `Weekdays at ${w.time}`;
  return `At ${t.cron}`;
}

const list = (items: string[]) => (items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)!}`);

/** When an interval runs, in words, under its fields: the times it makes when they're few, else its start. An
 * interval is counted in UTC, the same everywhere: it has no time zone. Null while it can't be said. */
export function intervalWords(w: When): string | null {
  const n = whole(w.every);
  if (n === null) return null;
  if (w.preset === "minutes") {
    const past = w.past.trim() === "" ? 0 : natural(w.past);
    if (past === null) return null;
    if (past >= n) return `Past the hour is less than the interval: ${n === 1 ? "0" : `0 to ${n - 1}`}.`;
    const none = "An interval is the same everywhere, so it has no time zone.";
    if (60 % n !== 0 || 60 / n > 6) return `Minutes, at least 1. Every ${n} minutes, counted from midnight UTC. ${none}`;
    const times = Array.from({ length: 60 / n }, (_, i) => `:${pad(past + i * n)}`);
    return `Minutes, at least 1. Runs at ${list(times)} of every hour. ${none}`;
  }
  if (w.preset === "hours") {
    const first = secondsOf(w.first);
    if (first === null) return null;
    if (first >= n * 3600) {
      const same = clock(first % (n * 3600));
      return `The first run must fall within the first ${n === 1 ? "hour" : `${n} hours`} of the day: ${w.first} is the same as ${same}.`;
    }
    if (24 % n !== 0 || 24 / n > 6) return `Every ${n} hours from ${w.first} UTC, counted from midnight. At most every 366 days.`;
    const times = Array.from({ length: 24 / n }, (_, i) => clock(first + i * n * 3600));
    return `Runs at ${list(times)} UTC, every day. At most every 366 days.`;
  }
  return null;
}

/** The API's refusals of a timing (apps/schedules.py's TIMING_CODES), in words, by the field the form shows them at. */
export const TIMING_WORDS: Record<string, string> = {
  cron_fields: "Five fields: minute, hour, day of the month, month, day of the week.",
  cron_syntax: "Each field is a number, a range, a list or a step, like 5, 1-5, 1,15 or */10; months and days may be names, like JAN or MON.",
  cron_range: "A value is outside its field (minutes 0–59, hours 0–23, days 1–31, months 1–12, days of the week 0–7), a range runs backwards, or a step is 0.",
  cron_day_fields: "Choose a day of the month or a day of the week, not both: put * in one of them.",
  timing_missing: "Choose when it runs.",
  timing_both: "A schedule runs on a cron or an interval, not both.",
  interval_too_short: "At least every minute.",
  interval_too_long: "At most every 366 days.",
  interval_offset: "It must fall within the interval, from its start.",
  time_zone_unknown: "Not a time zone this server knows: choose one from the list.",
  catchup_window: "From 1 minute to 24 hours.",
};

/** The time zones offered, the browser's first; the API holds them to its own list (`time_zone_unknown`). */
export function zones(browser: string = Intl.DateTimeFormat().resolvedOptions().timeZone): string[] {
  const all = new Set(Intl.supportedValuesOf("timeZone"));
  all.add("UTC");
  return [browser, ...[...all].filter((z) => z !== browser).sort()];
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/timing.test.ts`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  11 passed (11)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/timing.test.ts \
  frontend/src/lib/timing.ts
git commit -m "feat(editor): a schedule's timing as the form's presets, and in words (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: The trigger routes and their words (`lib/triggers.ts`)

The routes 4c-3a typed (B1), as queries and writes: a workflow's schedules and its webhook bindings (B13), the tenant's
endpoints and each one's bindings, the trigger types plugins declare, the published version's start form (null while
nothing is published) and a version's graph. And the words the panel, Settings and the list share: what starts a run
(the start card's summary and name), the list's Trigger column, why a workflow needs attention, a schedule's second line
and what its sync proves (4c-3a ruling 6), the firings it missed, a binding's sender and filter, a filter value as typed
and as shown so that reading it again gives it back exactly (the review of revision 1). The tests' fixtures come with
it: made-up trigger types and rows (D24).

**Files:**
- Create: `frontend/src/lib/triggers.test.ts`
- Create: `frontend/src/lib/triggers.ts`
- Create: `frontend/src/test/triggers.ts`

**Interfaces:**
- Consumes: `timingTitle`, `whenOf` (Task 2); `client`, `ok`, `ApiError`, `Schemas` from `lib/client.ts`.
- Produces: types `Schedule`, `ScheduleIn`, `SchedulePatch`, `Endpoint`, `EndpointIn`, `EndpointPatch`,
  `EndpointBinding`, `WorkflowBinding`, `FilterClause`, `TriggerType`, `StartForm`, `StartField`, `TriggerCounts`,
  `Attention`; queries `schedulesQuery`, `workflowBindingsQuery`, `endpointsQuery`, `endpointBindingsQuery`,
  `triggerTypesQuery`, `startFormQuery`, `versionQuery`; writes `createSchedule`, `updateSchedule`, `deleteSchedule`,
  `createBinding`, `updateBinding`, `deleteBinding`, `createEndpoint`, `updateEndpoint`, `rotateSecret`; words
  `startSummary`, `startLabel`, `triggerColumn`, `attentionWords`, `scheduleMeta`, `scheduleNote`, `missesNote`,
  `scheduleTitle`, `possessive`, `senderName`, `valueWords`, `filterWords`, `topicOf`, `bindingLine`, `parseValue`,
  `valueText`; fixtures (`src/test/triggers.ts`) `envelope`, `DEVICE_EVENTS`, `MIST`, `SCHEDULE`, `ENDPOINT`, `BINDING`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/lib/triggers.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  attentionWords, bindingLine, filterWords, missesNote, parseValue, scheduleMeta, scheduleNote, startFormQuery, startLabel,
  possessive, startSummary, topicOf, triggerColumn, valueText,
} from "./triggers";  // prettier-ignore
import { MIST, SCHEDULE } from "../test/triggers";

afterEach(() => vi.restoreAllMocks());

describe("a schedule in words", () => {
  it("says its zone where one applies, its mode, off, custom and synced, as the Schedules board does", () => {
    expect(scheduleMeta(SCHEDULE)).toBe("Europe/Paris · live · synced");
    expect(scheduleMeta({ ...SCHEDULE, cron: null, every_s: 900, mode: "simulate", enabled: false })).toBe("simulated: nothing is sent · off · synced");
    expect(scheduleMeta({ ...SCHEDULE, cron: "0 */6 * * 1-5", time_zone: "UTC" })).toBe("UTC · live · custom · synced");
    expect(scheduleMeta({ ...SCHEDULE, generation: 3 })).toBe("Europe/Paris · live");
  });

  it("says what its sync proves: never that one not yet synced isn't running, unless nothing ever unpaused it", () => {
    expect(scheduleNote(SCHEDULE)).toBeNull();
    expect(scheduleNote({ ...SCHEDULE, generation: 1, synced_generation: 0 })).toBe("Saved; sync not yet confirmed: it may already fire.");
    expect(scheduleNote({ ...SCHEDULE, generation: 1, synced_generation: 0, never_unpaused: true })).toBe(
      "Saved; not running yet: the scheduler takes it on its own, usually within seconds.",
    );
    expect(scheduleNote({ ...SCHEDULE, generation: 3 })).toBe("Saved; sync not yet confirmed: until it is, the previous time or the new one may fire.");
  });

  it("says a failed sync pauses nothing: the previous time may still fire", () => {
    const failed = { ...SCHEDULE, sync_error: "invalid_spec", sync_error_at: "2026-10-11T08:01:00Z" };
    expect(scheduleNote({ ...failed, generation: 3 })).toMatch(/^Sync failed: the scheduler refused this change\. Its previous time may still fire/);
    expect(scheduleNote({ ...failed, generation: 1, synced_generation: 0 })).toMatch(/its sync was never confirmed, so it may already fire/);
    expect(scheduleNote({ ...failed, generation: 1, synced_generation: 0, never_unpaused: true })).toMatch(/so it isn't running yet/);
  });

  it("says the firings it missed, and that some may be missed still", () => {
    expect(missesNote(SCHEDULE)).toBeNull();
    const missed = { ...SCHEDULE, misses: 3, misses_read_at: "2026-10-11T14:05:00Z", accounting_complete: false };
    expect(missesNote(missed, "UTC")).toBe("3 firings missed, counted at 14:05. Some may be missed still, not yet counted.");
    expect(missesNote({ ...missed, misses: 1, accounting_complete: true }, "UTC")).toBe("1 firing missed, counted at 14:05.");
    expect(missesNote({ ...SCHEDULE, accounting_complete: false })).toBe("Some firings may be missed, not yet counted.");
  });
});

describe("what starts a workflow, in words", () => {
  it("sums it up on the start card, its name starting with what it shows", () => {
    expect(startSummary({ csv: false, schedules: 0, webhooks: 0 })).toBe("By hand");
    expect(startSummary({ csv: false, schedules: 2, webhooks: 0 })).toBe("By hand · 2 schedules");
    expect(startSummary({ csv: false, schedules: 1, webhooks: 1 })).toBe("By hand · 1 schedule · 1 webhook");
    expect(startSummary({ csv: true, schedules: 0, webhooks: 0 })).toBe("By hand, with a CSV file");
    expect(startLabel("By hand · 2 schedules")).toBe("Start: by hand, 2 schedules. Open its triggers");
  });

  it("names what else starts it in the list's Trigger column, as the WorkflowsList board does", () => {
    const t = (schedules: number, webhook_bindings: number, csv = false) => ({ schedules, schedules_enabled: schedules, webhook_bindings, csv });
    expect(triggerColumn(t(0, 1))).toBe("Webhook");
    expect(triggerColumn(t(2, 1))).toBe("2 schedules · 1 webhook");
    expect(triggerColumn(t(1, 0))).toBe("Schedule");
    expect(triggerColumn(t(0, 0, true))).toBe("CSV file");
    expect(triggerColumn(t(0, 0))).toBe("By hand");
  });

  it("says why a workflow needs attention", () => {
    expect(attentionWords([])).toBeNull();
    expect(attentionWords(["last_run_failed"])).toBe("Needs attention: its last run failed.");
    expect(attentionWords(["schedule_sync_failed"])).toBe("Needs attention: a schedule couldn't be synced.");
    expect(attentionWords(["last_run_failed", "not_executable", "schedule_sync_failed"])).toBe(
      "Needs attention: its last run failed, its active version can't run and a schedule couldn't be synced.",
    );
  });
});

describe("a webhook binding in words", () => {
  const binding = (trigger: string | null, filter: { pointer: string; value: string | number | boolean | null }[]) => ({ endpoint: { trigger }, filter });

  it("names a Mist binding's topic, and another sender's filter", () => {
    expect(bindingLine(binding("mist.webhook", [{ pointer: "/topic", value: "device-events" }]), [MIST])).toBe("Mist · topic device-events");
    expect(bindingLine(binding(null, [{ pointer: "/type", value: "incident" }, { pointer: "/priority", value: 1 }]), [MIST])).toBe(
      "Another sender · /type is incident and /priority is 1",
    );
    expect(bindingLine(binding(null, []), [MIST])).toBe("Another sender · every event");
  });

  it("says when an endpoint's trigger is no longer declared, and a Mist filter that isn't a topic", () => {
    expect(bindingLine(binding("old.hook", []), [MIST])).toBe("An unknown sender (old.hook) · every event");
    expect(bindingLine(binding("mist.webhook", [{ pointer: "/topic", value: "nope" }]), [MIST])).toBe("Mist · /topic is nope");
    expect(topicOf([{ pointer: "/topic", value: "alarms" }], MIST)).toBe("alarms");
    expect(topicOf([{ pointer: "/topic", value: "alarms" }, { pointer: "/x", value: 1 }], MIST)).toBeNull();
  });

  it("quotes text that would read as a number, a yes or no, or null", () => {
    expect(filterWords([{ pointer: "/a", value: "1" }, { pointer: "/b", value: true }, { pointer: "/c", value: null }])).toBe(
      '/a is "1" and /b is true and /c is null',
    );
  });

  it("reads a typed value as written: whole numbers, true, false and null as such, quoted text as text", () => {
    expect(parseValue("1")).toEqual({ value: 1 });
    expect(parseValue(" -42 ")).toEqual({ value: -42 });
    expect(parseValue("true")).toEqual({ value: true });
    expect(parseValue("null")).toEqual({ value: null });
    expect(parseValue('"1"')).toEqual({ value: "1" });
    expect(parseValue("1.5")).toEqual({ value: "1.5" });
    expect(parseValue("incident")).toEqual({ value: "incident" });
    expect(parseValue("9007199254740993")).toEqual({ problem: "A whole number this large can't be kept exactly: put it in quotes to match it as text." });
    expect(parseValue("x".repeat(1025))).toEqual({ problem: "At most 1,024 characters." });
    for (const v of [1, "1", true, "true", null, "incident"] as const) expect(parseValue(valueText(v))).toEqual({ value: v });
  });

  it("shows every value so that reading it again gives it back exactly: spaces, quotes and escapes kept", () => {
    // The API keeps text as sent, and matches it so (the review of revision 1).
    const values = [" HQ ", "HQ ", '"quoted"', '"', 'say "hi"', "", "x\\y", "tab\there", "line\nbreak", "-0", "1e3", 'a"b"', 42, -7, 0, true, false, null] as const;
    for (const v of values) expect(parseValue(valueText(v)), JSON.stringify(v)).toEqual({ value: v });
    expect(valueText(" HQ ")).toBe('" HQ "');
    expect(valueText('"quoted"')).toBe('"\\"quoted\\""');
    expect(valueText("HQ")).toBe("HQ");
    expect(valueText("")).toBe('""');
    expect(filterWords([{ pointer: "/site", value: " HQ " }])).toBe('/site is " HQ "');
  });

  it("reads text in quotes as JSON text, and says so when it isn't", () => {
    expect(parseValue('" HQ "')).toEqual({ value: " HQ " });
    expect(parseValue('"a\\"b"')).toEqual({ value: 'a"b' });
    expect(parseValue('"a"b"')).toEqual({ problem: 'Text in quotes is read as JSON text: write \\" for a quote inside it.' });
  });
});

it("reads the start form as null while nothing is published", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: "not_active" }), { status: 409 }));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  expect(await qc.query(startFormQuery("t1", "w1"))).toBeNull();
});

it("says a name's possessive as the boards do", () => {
  expect(possessive("device-events")).toBe("device-events'");
  expect(possessive("client-join")).toBe("client-join's");
});
````

**Create** `frontend/src/test/triggers.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// Triggers for tests, as the API serves them: a schedule, an endpoint, a binding, and a webhook trigger type keyed as
// Mist's is (`mist.webhook`, which the UI names a sender by) whose topics are made-up envelopes, never Mist's own
// schemas (D24).
import type { Endpoint, Schedule, TriggerType, WorkflowBinding } from "../lib/triggers";

const event = (fields: Record<string, unknown>, required: string[] = []) => ({ type: "object", properties: fields, required });

/** A topic's shape as a trigger type serves it: `{topic, events}`, the topic fixed, the events typed by `$defs`. */
export const envelope = (topic: string, fields: Record<string, unknown>, required: string[] = []) => ({
  type: "object",
  properties: {
    topic: { type: "string", const: topic },
    events: { type: "array", items: { $ref: "#/$defs/event" } },
  },
  required: ["events", "topic"],
  $defs: { event: event(fields, required) },
});

export const DEVICE_EVENTS = envelope(
  "device-events",
  { ap_name: { type: "string" }, device_name: { type: "string" }, ev_type: { type: "string" }, mac: { type: "string" }, timestamp: { type: "number" } },
  ["timestamp"],
);

export const MIST: TriggerType = {
  key: "mist.webhook", label: "Mist webhook", plugin: "mist",
  endpoint: { auth: "bearer", events_pointer: null, id_source: "none" },
  topic_pointer: "/topic",
  topics: {
    alarms: envelope("alarms", { type: { type: "string" } }),
    "device-events": DEVICE_EVENTS,
    "device-updowns": envelope("device-updowns", { mac: { type: "string" } }),
  },
};  // prettier-ignore

export const SCHEDULE: Schedule = {
  id: "s1", workflow_id: "w1", cron: "0 7 * * *", every_s: null, offset_s: 0, time_zone: "Europe/Paris", catchup_window_s: 600,
  mode: "live", enabled: true, generation: 2, synced_generation: 2, misses: 0, missed_while_created: 0, misses_read_at: null,
  accounting_complete: true, uncounted_intervals: [], sync_error: null, sync_error_at: null, never_unpaused: false,
  created_at: "2026-10-11T08:00:00Z", updated_at: "2026-10-11T08:00:00Z",
};  // prettier-ignore

export const ENDPOINT: Endpoint = {
  id: "e1", name: "Mist prod", enabled: true, auth: "bearer", signature_header: null, timestamp_header: null, tolerance_s: 300,
  allowlist: [], body_limit: 1_048_576, id_source: "none", id_pointer: null, id_header: null, events_pointer: null,
  path: "/hooks/e1", pending_events: 0, pending_bytes: 0, retained_events: 0, retained_bytes: 0, created_at: "2026-10-11T08:00:00Z",
  trigger: "mist.webhook",
};  // prettier-ignore

export const BINDING: WorkflowBinding = {
  id: "b1", endpoint_id: "e1", workflow_id: "w1", enabled: true, filter: [{ pointer: "/topic", value: "device-events" }],
  endpoint: { id: "e1", name: "Mist prod", enabled: true, auth: "bearer", path: "/hooks/e1", trigger: "mist.webhook" },
};  // prettier-ignore
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/triggers.test.ts`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  no tests`. The run can't import `./triggers`: it doesn't exist yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/lib/triggers.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// What starts a workflow (4c-3b): its schedules, its webhook bindings and their endpoints, the trigger types the
// plugins declare, the published version's start form; and the words the Triggers panel, the list and Settings share.
// Types from the generated schema (B1, 4c-3a's named answers), never written by hand. The API decides every write.
import { queryOptions } from "@tanstack/react-query";
import { ApiError, client, ok, type Schemas } from "./client";
import { timingTitle, whenOf } from "./timing";

export type Schedule = Schemas["ScheduleOut"];
export type ScheduleIn = Schemas["ScheduleIn"];
export type SchedulePatch = Schemas["SchedulePatch"];
export type Endpoint = Schemas["EndpointOut"];
export type EndpointIn = Schemas["EndpointIn"];
export type EndpointPatch = Schemas["EndpointPatch"];
export type EndpointBinding = Schemas["WebhookBindingOut"];
export type WorkflowBinding = Schemas["WorkflowBindingOut"];
export type FilterClause = Schemas["FilterClauseOut"];
export type TriggerType = Schemas["TriggerTypeOut"];
export type StartForm = Schemas["StartFormOut"];
export type StartField = Schemas["StartFieldOut"];
export type TriggerCounts = Schemas["TriggersOut"];
export type Attention = Schemas["WorkflowOut"]["needs_attention"][number];

const tenant = (tenantId: string) => ({ params: { path: { tenant_id: tenantId } } });
const workflow = (tenantId: string, workflowId: string) => ({ params: { path: { tenant_id: tenantId, workflow_id: workflowId } } });

export const schedulesQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["schedules", tenantId, workflowId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/schedules", workflow(tenantId, workflowId))),
  });

/** A workflow's webhook bindings, each with its endpoint (B13). */
export const workflowBindingsQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["workflow-bindings", tenantId, workflowId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/webhook-bindings", workflow(tenantId, workflowId))),
  });

export const endpointsQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["endpoints", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/webhook-endpoints", tenant(tenantId))),
  });

/** An endpoint's bindings, the workflows it starts. */
export const endpointBindingsQuery = (tenantId: string, endpointId: string) =>
  queryOptions({
    queryKey: ["endpoint-bindings", tenantId, endpointId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings", {
        params: { path: { tenant_id: tenantId, endpoint_id: endpointId } },
      })),
  });

/** The trigger types synced plugins declare: Mist's webhook, its topics and their shapes. */
export const triggerTypesQuery = queryOptions({
  queryKey: ["trigger-types"],
  queryFn: () => ok(client.GET("/api/v1/trigger-types")),
  staleTime: 5 * 60_000,
});

/** The published version's start form; null while nothing is published (`409 not_active`). */
export const startFormQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["start-form", tenantId, workflowId],
    queryFn: async () => {
      try {
        return await ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/start-form", workflow(tenantId, workflowId)));
      } catch (e) {
        if (e instanceof ApiError && e.code === "not_active") return null;
        throw e;
      }
    },
  });

/** A version's graph, read once: a published version never changes. */
export const versionQuery = (tenantId: string, workflowId: string, versionId: string) =>
  queryOptions({
    queryKey: ["version", tenantId, workflowId, versionId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}", {
        params: { path: { tenant_id: tenantId, workflow_id: workflowId, version_id: versionId } },
      })),
    staleTime: Infinity,
  });

export const createSchedule = (tenantId: string, workflowId: string, body: ScheduleIn) =>
  ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/schedules", { ...workflow(tenantId, workflowId), body }));
export const updateSchedule = (tenantId: string, scheduleId: string, body: SchedulePatch) =>
  ok(client.PATCH("/api/v1/t/{tenant_id}/schedules/{schedule_id}", { params: { path: { tenant_id: tenantId, schedule_id: scheduleId } }, body }));
export const deleteSchedule = (tenantId: string, scheduleId: string) =>
  ok(client.DELETE("/api/v1/t/{tenant_id}/schedules/{schedule_id}", { params: { path: { tenant_id: tenantId, schedule_id: scheduleId } } }));

export const createBinding = (tenantId: string, endpointId: string, body: Schemas["BindingIn"]) =>
  ok(client.POST("/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/bindings", {
    params: { path: { tenant_id: tenantId, endpoint_id: endpointId } },
    body,
  }));
export const updateBinding = (tenantId: string, bindingId: string, body: Schemas["BindingPatch"]) =>
  ok(client.PATCH("/api/v1/t/{tenant_id}/webhook-bindings/{binding_id}", { params: { path: { tenant_id: tenantId, binding_id: bindingId } }, body }));
export const deleteBinding = (tenantId: string, bindingId: string) =>
  ok(client.DELETE("/api/v1/t/{tenant_id}/webhook-bindings/{binding_id}", { params: { path: { tenant_id: tenantId, binding_id: bindingId } } }));

export const createEndpoint = (tenantId: string, body: EndpointIn) =>
  ok(client.POST("/api/v1/t/{tenant_id}/webhook-endpoints", { ...tenant(tenantId), body }));
export const updateEndpoint = (tenantId: string, endpointId: string, body: EndpointPatch) =>
  ok(client.PATCH("/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}", { params: { path: { tenant_id: tenantId, endpoint_id: endpointId } }, body }));
export const rotateSecret = (tenantId: string, endpointId: string) =>
  ok(client.POST("/api/v1/t/{tenant_id}/webhook-endpoints/{endpoint_id}/secret", { params: { path: { tenant_id: tenantId, endpoint_id: endpointId } } }));

const plural = (n: number, one: string, many: string) => (n === 1 ? one : `${n} ${many}`);

/** What starts a run, on the start card: by hand always (once published), then what else does. */
export function startSummary(t: { csv: boolean; schedules: number; webhooks: number }): string {
  const parts = [t.csv ? "By hand, with a CSV file" : "By hand"];
  if (t.schedules > 0) parts.push(t.schedules === 1 ? "1 schedule" : `${t.schedules} schedules`);
  if (t.webhooks > 0) parts.push(t.webhooks === 1 ? "1 webhook" : `${t.webhooks} webhooks`);
  return parts.join(" · ");
}

/** The start card's name: its visible words first (WCAG 2.5.3), then what it opens. */
export const startLabel = (summary: string) => `Start: ${summary.charAt(0).toLowerCase()}${summary.slice(1).replaceAll(" · ", ", ")}. Open its triggers`;

/** The list's Trigger column (ruling 68): what starts a workflow besides a person, by hand being always possible once
 * published. A workflow that takes a CSV file runs only by hand, with a file. */
export function triggerColumn(t: TriggerCounts): string {
  if (t.csv) return "CSV file";
  const [s, w] = [t.schedules, t.webhook_bindings];
  if (s > 0 && w > 0) return `${plural(s, "1 schedule", "schedules")} · ${plural(w, "1 webhook", "webhooks")}`;
  if (s > 0) return plural(s, "Schedule", "schedules");
  if (w > 0) return plural(w, "Webhook", "webhooks");
  return "By hand";
}

const ATTENTION: Record<Attention, string> = {
  last_run_failed: "its last run failed",
  not_executable: "its active version can't run",
  schedule_sync_failed: "a schedule couldn't be synced",
};

/** Why a workflow needs attention, in a sentence: null when it doesn't. */
export function attentionWords(reasons: readonly Attention[]): string | null {
  const said = reasons.map((r) => ATTENTION[r]);
  if (said.length === 0) return null;
  const joined = said.length === 1 ? said[0]! : `${said.slice(0, -1).join(", ")} and ${said.at(-1)!}`;
  return `Needs attention: ${joined}.`;
}

const TIME = (zone?: string) => new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: zone });

/** A schedule's second line: its zone where one applies (a cron's), its mode, whether it's off, a custom cron, and
 * "synced" once the scheduler holds its latest change. */
export function scheduleMeta(s: Schedule): string {
  const custom = s.cron !== null && whenOf(s).preset === "custom";
  return [
    s.cron !== null ? s.time_zone : null,
    s.mode === "simulate" ? "simulated: nothing is sent" : "live",
    s.enabled ? null : "off",
    custom ? "custom" : null,
    s.generation === s.synced_generation && s.sync_error === null ? "synced" : null,
  ].filter((p) => p !== null).join(" · ");
}

/** What a schedule's sync proves, when it isn't synced (the D8 reviews; 4c-3a ruling 6). A failed sync pauses nothing:
 * the previous time may still fire. One never synced may already fire (the unpause can land before its read-back
 * fails), unless nothing ever unpaused it: then it isn't running yet. */
export function scheduleNote(s: Schedule): string | null {
  const first = s.synced_generation === 0;
  if (s.sync_error !== null) {
    if (first && s.never_unpaused)
      return "Sync failed: the scheduler refused it, so it isn't running yet. Dewpoint tries again every minute, and the workflow shows as needing attention.";
    if (first)
      return "Sync failed: the scheduler refused it, and its sync was never confirmed, so it may already fire. Dewpoint tries again every minute, and the workflow shows as needing attention; turning it off stops new runs at once.";
    return "Sync failed: the scheduler refused this change. Its previous time may still fire, with the input and mode saved now. Dewpoint tries again every minute; turning it off stops new runs at once.";
  }
  if (s.generation === s.synced_generation) return null;
  if (first) return s.never_unpaused ? "Saved; not running yet: the scheduler takes it on its own, usually within seconds." : "Saved; sync not yet confirmed: it may already fire.";
  return "Saved; sync not yet confirmed: until it is, the previous time or the new one may fire.";
}

/** The firings a schedule missed, as counted, and whether some may be missed still. */
export function missesNote(s: Schedule, zone?: string): string | null {
  if (s.misses === 0) return s.accounting_complete ? null : "Some firings may be missed, not yet counted.";
  const at = s.misses_read_at ? `, counted at ${TIME(zone).format(new Date(s.misses_read_at))}` : "";
  const missed = `${plural(s.misses, "1 firing", "firings")} missed${at}.`;
  return s.accounting_complete ? missed : `${missed} Some may be missed still, not yet counted.`;
}

export const scheduleTitle = (s: Schedule) => timingTitle(s);

/** A name's possessive, as the boards write it: "device-events' shape", "alarm's shape". */
export const possessive = (name: string) => `${name}${name.endsWith("s") ? "'" : "'s"}`;

/** A trigger type's sender, as a person says it: "Mist" for "Mist webhook". */
export const senderName = (t: TriggerType) => t.label.replace(/ webhook$/i, "");

/** A filter value as its row says it: the form's text for it, which reads as the value and shows its spaces and quotes. */
export const valueWords = (v: FilterClause["value"]): string => valueText(v);

/** A filter in words: "/type is incident and /priority is 1"; none matches every event. */
export const filterWords = (filter: FilterClause[]) =>
  filter.length === 0 ? "every event" : filter.map((c) => `${c.pointer} is ${valueWords(c.value)}`).join(" and ");

/** The topic a filter picks for a trigger type: one clause on its topic pointer, naming one of its topics. */
export function topicOf(filter: FilterClause[], type: TriggerType | undefined): string | null {
  const [only] = filter;
  if (!type || filter.length !== 1 || only?.pointer !== type.topic_pointer || typeof only.value !== "string") return null;
  return Object.hasOwn(type.topics, only.value) ? only.value : null;
}

/** What a binding's endpoint sends and when the binding runs, in its row: "Mist · topic device-events", or "Another
 * sender · /type is incident". An endpoint made for a trigger no plugin declares any more says so. */
export function bindingLine(b: { endpoint: { trigger: string | null }; filter: FilterClause[] }, types: TriggerType[]): string {
  const key = b.endpoint.trigger;
  const type = key === null ? undefined : types.find((t) => t.key === key);
  if (key !== null && !type) return `An unknown sender (${key}) · ${filterWords(b.filter)}`;
  if (!type) return `Another sender · ${filterWords(b.filter)}`;
  const topic = topicOf(b.filter, type);
  return `${senderName(type)} · ${topic ? `topic ${topic}` : filterWords(b.filter)}`;
}

const INT = /^-?(0|[1-9]\d*)$/;

/** A filter value as typed (the binding form): a whole number, true, false or null as written; text in quotes read as
 * JSON text, its spaces, quotes and escapes kept; anything else as text, without the spaces around it. Never a float:
 * the API refuses one. */
export function parseValue(text: string): { value: FilterClause["value"] } | { problem: string } {
  const t = text.trim();
  if (INT.test(t)) {
    const n = Number(t);
    return Number.isSafeInteger(n) ? { value: n } : { problem: "A whole number this large can't be kept exactly: put it in quotes to match it as text." };
  }
  if (t === "true" || t === "false") return { value: t === "true" };
  if (t === "null") return { value: null };
  let inner = t;
  if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
    try {
      inner = JSON.parse(t) as string;
    } catch {
      return { problem: 'Text in quotes is read as JSON text: write \\" for a quote inside it.' };
    }
  }
  return inner.length > 1024 ? { problem: "At most 1,024 characters." } : { value: inner };
}

/** A filter value as the form shows it, so that reading it again gives it back exactly (the review of revision 1): text
 * as itself when that reads back as it, else as JSON text in quotes (" HQ ", "42", "" and a quote at each end). */
export function valueText(v: FilterClause["value"]): string {
  if (typeof v !== "string") return v === null ? "null" : String(v);
  const read = parseValue(v);
  return v !== "" && "value" in read && read.value === v ? v : JSON.stringify(v);
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/triggers.test.ts`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  15 passed (15)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/triggers.test.ts \
  frontend/src/lib/triggers.ts \
  frontend/src/test/triggers.ts
git commit -m "feat(editor): the trigger routes as queries, and what starts a workflow in words (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: The input as fields, and the CSV file (`lib/input.ts`, `lib/csv.ts`)

`settings.input_schema` read as fields of a plain type (Text, Whole number, Number, Yes or no, Choice, Date and time)
and the rows it can't show (ruling 3); a field changed, renamed, added and removed, the rest kept as written, key order
included; a sensitive field's default, and one its new type or values don't fit, dropped; a name the panel writes (an
identifier, not a CSV file's `rows`); the settings' writer; a topic's shape recognised and listed (ruling 6).
`settings.csv`: what a draft's save takes of it (ruling 5, `csvProblem`), its columns written through `setAt` so a list
edited in place keeps its lineage and a removal starts one of its own (ruling 4), its limits as typed (rows, MB), and a
column's rules in words.

**Files:**
- Create: `frontend/src/lib/csv.test.ts`
- Create: `frontend/src/lib/csv.ts`
- Create: `frontend/src/lib/input.test.ts`
- Create: `frontend/src/lib/input.ts`

**Interfaces:**
- Consumes: `CEL_WORDS`, `setAt` from `lib/config.ts`; `deref`, `isObject`, `Schema` from `lib/schemaForm.ts`; `Schemas`
  from `lib/client.ts`.
- Produces: in `lib/input.ts`: `FieldType`, `FIELD_TYPES`, `InputField`, `InputRow`, `RESERVED`, `inputRows`,
  `setField`, `nameProblem`, `renameField`, `addField`, `removeField`, `fieldPointer`, `inputOf`, `setSettings`,
  `sameSchema`, `topicShaped`, `ShapeRow`, `shapeRows`; in `lib/csv.ts`: `CsvColumn`, `CsvSettings`, `CsvType`,
  `CSV_TYPES`, `typeLabel`, `MAX_COLUMNS`, `MAX_ROWS`, `MAX_BYTES`, `csvProblem`, `csvOf`, `newCsv`, `addColumn`,
  `removeColumn`, `setColumn`, `setLimits`, `rulesOf`, `bytesOf`, `mbOf`, `rowsLimit`, `sizeLimit`, `textProblem`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/lib/csv.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { rootOf } from "./config";
import { addColumn, bytesOf, csvProblem, mbOf, newCsv, removeColumn, rulesOf, setColumn, setLimits, type CsvSettings } from "./csv";

const CSV: CsvSettings = {
  columns: [
    { header: "AP name", name: "ap_name", type: "string", required: true },
    { header: "Floor", name: "floor", type: "integer", required: true, default: 0 },
    { header: "Band", name: "band", type: "enum", default: "5 GHz", values: ["2.4 GHz", "5 GHz", "6 GHz"] },
  ],
};

describe("what a draft's save takes as a CSV declaration", () => {
  it("takes a declaration the strict model takes", () => {
    expect(csvProblem(CSV)).toBeNull();
    expect(csvProblem(undefined)).toBeNull();
    expect(csvProblem({ ...CSV, max_rows: 10_000, max_bytes: 5 * 1024 * 1024 })).toBeNull();
  });

  it("says what the save would refuse, so nothing refused is written", () => {
    expect(csvProblem({ columns: [] })).toBe("A CSV file has from 1 to 200 columns.");
    expect(csvProblem({ columns: CSV.columns, extra: 1 })).toMatch(/^A CSV file's declaration holds/);
    expect(csvProblem({ columns: [{ header: "", name: "a", type: "string" }] })).toBe("Column 1's header is from 1 to 200 characters.");
    expect(csvProblem({ columns: [{ header: "A", name: "a".repeat(64), type: "string" }] })).toBe("Column 1's name is from 1 to 63 characters.");
    expect(csvProblem({ columns: [{ header: "A", name: "a", type: "date" }] })).toMatch(/^Column 1's type is one of/);
    expect(csvProblem({ columns: [{ header: "A", name: "a", type: "string", note: "x" }] })).toBe("Column 1 holds something a column can't.");
    expect(csvProblem({ columns: [{ header: "A", name: "a", type: "enum", values: ["x".repeat(201)] }] })).toMatch(/at most 200 texts/);
    expect(csvProblem({ columns: [{ header: "A", name: "a", type: "string", required: "yes" }] })).toMatch(/true or false/);
    expect(csvProblem({ ...CSV, max_rows: 10_001 })).toBe("Most rows is a whole number from 1 to 10,000.");
    expect(csvProblem({ ...CSV, max_bytes: 0 })).toBe("The largest file is from 1 byte to 5 MB.");
  });
});

describe("columns", () => {
  it("starts a file with one text column, and adds one whose header and name aren't taken", () => {
    expect(newCsv()).toEqual({ columns: [{ header: "Column 1", name: "column_1", type: "string" }] });
    expect(addColumn(CSV).columns[3]).toEqual({ header: "Column 4", name: "column_4", type: "string" });
    const taken = { columns: [{ header: "Column 2", name: "x", type: "string" as const }] };
    expect(addColumn(taken).columns[1]).toEqual({ header: "Column 3", name: "column_3", type: "string" });
  });

  it("keeps the list's lineage through an edit in place and an addition, never through a removal", () => {
    const edited = setColumn(CSV, 0, { header: "AP" });
    expect(rootOf(edited.columns)).toBe(rootOf(CSV.columns));
    expect(rootOf(edited.columns[0]!)).toBe(rootOf(CSV.columns[0]!));
    expect(rootOf(addColumn(CSV).columns)).toBe(rootOf(CSV.columns));
    expect(rootOf(removeColumn(CSV, 0)!.columns)).not.toBe(rootOf(CSV.columns));
  });

  it("removes a column but never the last one: the file goes instead", () => {
    expect(removeColumn(CSV, 1)!.columns.map((c) => c.name)).toEqual(["ap_name", "band"]);
    expect(removeColumn(newCsv(), 0)).toBeNull();
  });

  it("keeps values for a Choice alone, drops a sensitive column's default and one that no longer fits", () => {
    expect(setColumn(CSV, 2, { type: "string" }).columns[2]).toEqual({ header: "Band", name: "band", type: "string", default: "5 GHz" });
    expect(setColumn(CSV, 0, { type: "enum" }).columns[0]).toEqual({ header: "AP name", name: "ap_name", type: "enum", required: true, values: [] });
    expect(setColumn(CSV, 1, { sensitive: true }).columns[1]).toEqual({ header: "Floor", name: "floor", type: "integer", required: true, sensitive: true });
    expect(setColumn(CSV, 1, { type: "boolean" }).columns[1]).not.toHaveProperty("default");
    expect(setColumn(CSV, 2, { values: ["2.4 GHz"] }).columns[2]).not.toHaveProperty("default");
    expect(setColumn(CSV, 1, { default: undefined }).columns[1]).not.toHaveProperty("default");
    // A required column's default is the server's to refuse (`csv.required_default`): written as asked.
    expect(setColumn(CSV, 0, { default: "x" }).columns[0]).toMatchObject({ required: true, default: "x" });
  });

  it("sets the limits, and leaves one to the platform's when it's cleared", () => {
    expect(setLimits(CSV, { max_rows: 500 })).toEqual({ ...CSV, max_rows: 500 });
    expect(setLimits({ ...CSV, max_rows: 500 }, { max_rows: undefined })).toEqual(CSV);
  });

  it("says a column's rules as the InputCsv board does", () => {
    expect(CSV.columns.map(rulesOf)).toEqual(["required", "required, default 0", "default 5 GHz"]);
    expect(rulesOf({ header: "Owner", name: "owner", type: "string", sensitive: true })).toBe("sensitive");
    expect(rulesOf({ header: "On", name: "on", type: "boolean", default: false })).toBe("default no");
  });

  it("reads the largest file in MB, up to the platform's 5 MB", () => {
    expect(bytesOf("5")).toBe(5 * 1024 * 1024);
    expect(bytesOf("0.5")).toBe(524_288);
    expect(bytesOf("6")).toBeNull();
    expect(bytesOf("0")).toBeNull();
    expect(bytesOf("x")).toBeNull();
    expect(mbOf(5 * 1024 * 1024)).toBe("5");
    expect(mbOf(524_288)).toBe("0.5");
  });
});
````

**Create** `frontend/src/lib/input.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { DEVICE_EVENTS, MIST } from "../test/triggers";
import {
  addField, inputOf, inputRows, nameProblem, removeField, renameField, sameSchema, setField, setSettings, shapeRows, topicShaped,
} from "./input";  // prettier-ignore
import type { GraphDoc } from "./workflows";

const SCHEMA = {
  type: "object",
  properties: {
    site: { type: "string", title: "Site" },
    token: { type: "string", title: "API token", description: "The ticketing system's token for this site.", "x-sensitive": true },
    floor: { type: "integer", default: 0 },
    band: { type: "string", enum: ["2.4 GHz", "5 GHz"], default: "5 GHz" },
    at: { type: "string", format: "date-time" },
    tags: { type: "array", items: { type: "string" } },
    code: { type: "string", minLength: 3 },
  },
  required: ["site", "token"],
};

describe("the input as form fields", () => {
  it("reads each field the list can show, in the schema's order, and what it can't", () => {
    const rows = inputRows(SCHEMA);
    expect(rows.map((r) => (r.kind === "field" ? `${r.field.name}:${r.field.type}` : `${r.name}:other`))).toEqual([
      "site:text", "token:text", "floor:whole", "band:choice", "at:datetime", "tags:other", "code:other",
    ]);  // prettier-ignore
    expect(rows[1]).toEqual({
      kind: "field",
      field: { name: "token", label: "API token", type: "text", required: true, sensitive: true, description: "The ticketing system's token for this site.", values: [] },
    });
    expect(rows[3]).toMatchObject({ kind: "field", field: { values: ["2.4 GHz", "5 GHz"], default: "5 GHz" } });
    expect(rows[5]).toEqual({ kind: "other", name: "tags", required: false, what: "a list" });
    expect(rows[6]).toEqual({ kind: "other", name: "code", required: false, what: "text with rules of its own" });
  });

  it("changes one field and keeps every other key and field as written", () => {
    const next = setField(SCHEMA, "site", { label: "Site name", required: false });
    expect(next.properties).toEqual({ ...SCHEMA.properties, site: { type: "string", title: "Site name" } });
    expect(next.required).toEqual(["token"]);
    expect(Object.keys(next.properties as object)).toEqual(Object.keys(SCHEMA.properties));
    expect(setField(SCHEMA, "floor", { required: true }).required).toEqual(["site", "token", "floor"]);
    expect(setField(SCHEMA, "tags", { label: "x" })).toBe(SCHEMA); // the list can't show it: left as it is
  });

  it("drops a default a sensitive field can't have, and one its new type or values don't fit", () => {
    expect((setField(SCHEMA, "floor", { sensitive: true }).properties as Record<string, unknown>).floor).toEqual({ type: "integer", "x-sensitive": true });
    expect((setField(SCHEMA, "floor", { type: "number" }).properties as Record<string, unknown>).floor).toEqual({ type: "number", default: 0 });
    expect((setField(SCHEMA, "floor", { type: "text" }).properties as Record<string, unknown>).floor).toEqual({ type: "string" });
    expect((setField(SCHEMA, "band", { values: ["2.4 GHz", "6 GHz"] }).properties as Record<string, unknown>).band).toEqual({
      type: "string", enum: ["2.4 GHz", "6 GHz"],
    });  // prettier-ignore
    expect((setField(SCHEMA, "band", { type: "text" }).properties as Record<string, unknown>).band).toEqual({ type: "string", default: "5 GHz" });
    expect((setField(SCHEMA, "floor", { default: undefined }).properties as Record<string, unknown>).floor).toEqual({ type: "integer" });
    expect((setField(SCHEMA, "at", { type: "datetime", default: "2026-10-11T08:00:00Z" }).properties as Record<string, unknown>).at).toEqual({
      type: "string", format: "date-time", default: "2026-10-11T08:00:00Z",
    });  // prettier-ignore
  });

  it("renames a field in its place, its requirement following, and says when a name can't be one", () => {
    const next = renameField(SCHEMA, "site", "site_name");
    expect(Object.keys(next.properties as object)[0]).toBe("site_name");
    expect(next.required).toEqual(["site_name", "token"]);
    expect(nameProblem(SCHEMA, "site", "site")).toBeNull();
    expect(nameProblem(SCHEMA, "site", "token")).toBe("Another field has this name.");
    expect(nameProblem(SCHEMA, "site", "Site")).toMatch(/^Lowercase letters/);
    expect(nameProblem(SCHEMA, "site", "true")).toMatch(/^Lowercase letters/);
    expect(nameProblem(SCHEMA, "site", "rows")).toBe("`rows` and `row_count` are a CSV file's: declare the file, and its rows arrive there.");
  });

  it("adds an optional text field with a name not taken, and removes one with its requirement", () => {
    const { schema, name } = addField({ type: "object", properties: { field_2: {} } });
    expect(name).toBe("field_3");
    expect(schema.properties).toEqual({ field_2: {}, field_3: { type: "string" } });
    expect(addField({ type: "object" }).name).toBe("field_1");
    const removed = removeField(SCHEMA, "token");
    expect(removed.required).toEqual(["site"]);
    expect(Object.keys(removed.properties as object)).not.toContain("token");
    expect(removeField({ type: "object", properties: { a: {} }, required: ["a"] }, "a")).toEqual({ type: "object", properties: {} });
  });
});

describe("the draft's settings", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [], edges: [], settings: { declassify: [], input_schema: SCHEMA } };

  it("reads the input, an empty object schema when there's none", () => {
    expect(inputOf(doc)).toBe(SCHEMA);
    expect(inputOf({ graph_format: 1 })).toEqual({ type: "object" });
  });

  it("sets and removes settings keys, keeping the others", () => {
    const next = setSettings(doc, { input_schema: { type: "object" }, csv: undefined });
    expect(next.settings).toEqual({ declassify: [], input_schema: { type: "object" } });
    expect(setSettings({ graph_format: 1 }, { csv: { columns: [] } }).settings).toEqual({ csv: { columns: [] } });
  });
});

describe("a Mist event's shape", () => {
  it("knows the input is a topic's shape whatever its keys' order, and none when it isn't", () => {
    const reordered = { required: ["events", "topic"], $defs: DEVICE_EVENTS.$defs, properties: DEVICE_EVENTS.properties, type: "object" };
    expect(sameSchema(reordered, DEVICE_EVENTS)).toBe(true);
    expect(topicShaped(reordered, MIST.topics)).toBe("device-events");
    expect(topicShaped(SCHEMA, MIST.topics)).toBeNull();
  });

  it("lists the shape's own fields, then one event's, saying what may be missing", () => {
    const { rows, more } = shapeRows(DEVICE_EVENTS, "device-events", 4);
    expect(rows).toEqual([
      { path: "trigger.topic", what: "text, always device-events", optional: false },
      { path: "trigger.events", what: "list of device events", optional: false },
      { path: "[ ].ap_name", what: "text", optional: true },
      { path: "[ ].device_name", what: "text", optional: true },
      { path: "[ ].ev_type", what: "text", optional: true },
      { path: "[ ].mac", what: "text", optional: true },
    ]);
    expect(more).toBe(true);
    expect(shapeRows(DEVICE_EVENTS, "device-events").rows.at(-1)).toEqual({ path: "[ ].timestamp", what: "number", optional: false });
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`):
`npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/input.test.ts src/lib/csv.test.ts`

Expected: FAIL: `Test Files  2 failed (2)`, `Tests  no tests`. The run can't import `./csv`, `./input`: they don't exist
yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/lib/csv.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// A workflow's CSV file (4c-3b; the mockups' InputCsv and InputEdit boards; engine 2b spec §8.1): `settings.csv`, its
// typed columns and its limits. A draft is saved only when its graph's format takes it (engine/graph/model.py's
// CsvSettings and CsvColumn, strict), so nothing here writes a declaration the save would refuse (D19): that is
// `csvProblem`. Every other rule (unique headers and names, a required column's default) is the server's to say.
// Columns are written through `setAt`, so a list edited in place keeps its lineage and a removal starts a new one: a
// held edit inside a column is applied only to the column it was typed in (ruling 113).
import type { Schemas } from "./client";
import { setAt } from "./config";
import { isObject } from "./schemaForm";
import type { GraphDoc } from "./workflows";

export type CsvColumn = Schemas["CsvColumn"];
export type CsvSettings = Schemas["CsvSettings"];
export type CsvType = CsvColumn["type"];

export const CSV_TYPES: { value: CsvType; label: string }[] = [
  { value: "string", label: "Text" },
  { value: "integer", label: "Whole number" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Yes or no" },
  { value: "mac", label: "MAC address" },
  { value: "ip", label: "IP address" },
  { value: "cidr", label: "Network (CIDR)" },
  { value: "enum", label: "Choice" },
];
export const typeLabel = (t: string) => CSV_TYPES.find((x) => x.value === t)?.label ?? t;

// engine/graph/model.py and engine/graph/csv.py: what a draft's CSV declaration may be.
export const MAX_COLUMNS = 200;
export const MAX_ROWS = 10_000;
export const MAX_BYTES = 5 * 1024 * 1024;
const MAX_HEADER = 200;
const MAX_NAME = 63;
const MAX_VALUES = 200;
const MAX_VALUE = 200;
const COLUMN_KEYS = new Set(["header", "name", "type", "required", "default", "sensitive", "values"]);
const TYPES = new Set<string>(CSV_TYPES.map((t) => t.value));

const sized = (v: unknown, max: number) => typeof v === "string" && v.length >= 1 && v.length <= max;
const count = (v: unknown, max: number) => typeof v === "number" && Number.isInteger(v) && v >= 1 && v <= max;

/** Why a draft's save would refuse this as `settings.csv`, or null: the strict model's own bounds, in words. */
export function csvProblem(csv: unknown): string | null {
  if (csv === undefined) return null;
  if (!isObject(csv) || Object.keys(csv).some((k) => !["columns", "max_rows", "max_bytes"].includes(k))) {
    return "A CSV file's declaration holds its columns and, optionally, its most rows and its largest file.";
  }
  if (!Array.isArray(csv.columns) || csv.columns.length < 1 || csv.columns.length > MAX_COLUMNS) {
    return `A CSV file has from 1 to ${MAX_COLUMNS} columns.`;
  }
  for (const [i, c] of (csv.columns as unknown[]).entries()) {
    const n = i + 1;
    if (!isObject(c) || Object.keys(c).some((k) => !COLUMN_KEYS.has(k))) return `Column ${n} holds something a column can't.`;
    if (!sized(c.header, MAX_HEADER)) return `Column ${n}'s header is from 1 to ${MAX_HEADER} characters.`;
    if (!sized(c.name, MAX_NAME)) return `Column ${n}'s name is from 1 to ${MAX_NAME} characters.`;
    if (typeof c.type !== "string" || !TYPES.has(c.type)) return `Column ${n}'s type is one of: ${CSV_TYPES.map((t) => t.value).join(", ")}.`;
    if (("required" in c && typeof c.required !== "boolean") || ("sensitive" in c && typeof c.sensitive !== "boolean")) {
      return `Column ${n}'s required and sensitive are true or false.`;
    }
    const values = c.values;
    if (values !== undefined && values !== null) {
      if (!Array.isArray(values) || values.length > MAX_VALUES || !values.every((v) => typeof v === "string" && v.length <= MAX_VALUE)) {
        return `Column ${n}'s values are at most ${MAX_VALUES} texts of at most ${MAX_VALUE} characters.`;
      }
    }
  }
  if (csv.max_rows !== undefined && !count(csv.max_rows, MAX_ROWS)) return `Most rows is a whole number from 1 to ${MAX_ROWS.toLocaleString("en-US")}.`;
  if (csv.max_bytes !== undefined && !count(csv.max_bytes, MAX_BYTES)) return "The largest file is from 1 byte to 5 MB.";
  return null;
}

export const csvOf = (doc: GraphDoc): CsvSettings | null => (isObject(doc.settings?.csv) ? (doc.settings.csv) : null);

/** A column whose header and name no other column has: "Column 3", `column_3`. */
function freshColumn(columns: CsvColumn[]): CsvColumn {
  let n = columns.length + 1;
  while (columns.some((c) => c.header === `Column ${n}` || c.name === `column_${n}`)) n++;
  return { header: `Column ${n}`, name: `column_${n}`, type: "string" };
}

/** A new CSV file of one text column: a declaration has one at least. */
export const newCsv = (): CsvSettings => ({ columns: [freshColumn([])] });

export const addColumn = (csv: CsvSettings): CsvSettings => setAt(csv, ["columns", csv.columns.length], freshColumn(csv.columns)) as CsvSettings;

/** The declaration without column `i`; null for its last one: a declaration keeps one, and the file goes instead. */
export const removeColumn = (csv: CsvSettings, i: number): CsvSettings | null =>
  csv.columns.length <= 1 ? null : (setAt(csv, ["columns", i], undefined) as CsvSettings);

/** Whether a default still fits a column after its type or values changed. */
function fits(c: CsvColumn, v: unknown): boolean {
  switch (c.type) {
    case "integer":
      return typeof v === "number" && Number.isInteger(v);
    case "number":
      return typeof v === "number";
    case "boolean":
      return typeof v === "boolean";
    case "enum":
      return typeof v === "string" && (c.values ?? []).includes(v);
    default:
      return typeof v === "string";
  }
}

/** The declaration with column `i` changed as `patch` says, each key written in place: only a Choice has values, a
 * sensitive column has no default, and a default its new type or values don't fit goes. Undefined removes a key. */
export function setColumn(csv: CsvSettings, i: number, patch: Partial<CsvColumn>): CsvSettings {
  const was = csv.columns[i];
  if (!was) return csv;
  const next: CsvColumn = { ...was, ...patch };
  const writes: [string, unknown][] = Object.entries(patch);
  if (next.type !== "enum" && "values" in was) writes.push(["values", undefined]);
  if (next.type === "enum" && !Array.isArray(next.values)) writes.push(["values", []]);
  if ("default" in next && (next.sensitive === true || !fits({ ...next, values: next.type === "enum" ? (next.values ?? []) : null }, next.default))) {
    writes.push(["default", undefined]);
  }
  let out: unknown = csv;
  for (const [key, value] of writes) out = setAt(out, ["columns", i, key], value);
  return out as CsvSettings;
}

/** The declaration with its limits: undefined leaves one to the platform's. */
export const setLimits = (csv: CsvSettings, limits: { max_rows?: number; max_bytes?: number }): CsvSettings =>
  Object.entries(limits).reduce((out: unknown, [k, v]) => setAt(out, [k], v), csv) as CsvSettings;

/** A column's rules, in its row: "required, default 0", "sensitive", "default HQ". */
export function rulesOf(c: CsvColumn): string {
  const shown = (v: unknown) => (typeof v === "boolean" ? (v ? "yes" : "no") : String(v));
  return [c.required ? "required" : null, c.sensitive ? "sensitive" : null, "default" in c ? `default ${shown(c.default)}` : null]
    .filter((p) => p !== null)
    .join(", ");
}

/** The largest file as typed, in MB, as bytes: up to the platform's 5 MB. Null when it isn't a size. */
export function bytesOf(mb: string): number | null {
  const n = Number(mb.trim());
  if (mb.trim() === "" || !Number.isFinite(n) || n <= 0) return null;
  const bytes = Math.round(n * 1024 * 1024);
  return bytes >= 1 && bytes <= MAX_BYTES ? bytes : null;
}

/** Bytes as the form shows them, in MB, without a trailing zero: 5242880 is "5". */
export const mbOf = (bytes: number) => String(Number((bytes / 1024 / 1024).toFixed(3)));

type Limit = { value: number | undefined } | { problem: string };

/** Most rows as typed: empty leaves it to the platform's 10,000. */
export function rowsLimit(text: string): Limit {
  const t = text.trim();
  if (t === "") return { value: undefined };
  const n = /^\d{1,6}$/.test(t) ? Number(t) : NaN;
  return n >= 1 && n <= MAX_ROWS ? { value: n } : { problem: `A whole number from 1 to ${MAX_ROWS.toLocaleString("en-US")}.` };
}

/** The largest file as typed, in MB: empty leaves it to the platform's 5 MB. */
export function sizeLimit(text: string): Limit {
  if (text.trim() === "") return { value: undefined };
  const bytes = bytesOf(text);
  return bytes === null ? { problem: "A size in MB, above 0 and up to 5." } : { value: bytes };
}

/** Why a column's header or name as typed wouldn't be saved, or null: from 1 to 200, and 1 to 63, characters. */
export function textProblem(key: "header" | "name", text: string): string | null {
  const max = key === "header" ? MAX_HEADER : MAX_NAME;
  return text.length >= 1 && text.length <= max ? null : `${key === "header" ? "A header" : "A name"} is from 1 to ${max} characters.`;
}
````

**Create** `frontend/src/lib/input.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// A workflow's input (4c-3b; the mockups' InputFields and InputMist boards): `settings.input_schema` read as a list of
// form fields, and written back one field at a time, or replaced by a trigger topic's shape. What the list can't show
// (a list, an object of fields, a field with rules of its own) stays as written, read only: Edit as JSON changes it.
// Every change keeps what it doesn't touch, key order included. The server checks the schema (D18).
import { CEL_WORDS } from "./config";
import { deref, isObject, type Schema } from "./schemaForm";
import type { GraphDoc } from "./workflows";

export type FieldType = "text" | "whole" | "number" | "yesno" | "choice" | "datetime";

export const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "whole", label: "Whole number" },
  { value: "number", label: "Number" },
  { value: "yesno", label: "Yes or no" },
  { value: "choice", label: "Choice" },
  { value: "datetime", label: "Date and time" },
];

export interface InputField {
  name: string;
  label: string; // its `title`; empty for none
  type: FieldType;
  required: boolean;
  sensitive: boolean; // `x-sensitive`: kept apart from run history
  description: string;
  default?: unknown; // present only when written
  values: string[]; // a Choice's
}

/** A field as the list shows it, or one it can't: then only its name, whether it's required, and what it is. */
export type InputRow = { kind: "field"; field: InputField } | { kind: "other"; name: string; required: boolean; what: string };

/** The keys a field the list shows may have: anything else is a rule of its own the list would lose. */
const PLAIN = new Set(["type", "title", "description", "default", "x-sensitive", "format", "enum"]);
const TYPE_OF: Record<string, FieldType> = { string: "text", integer: "whole", number: "number", boolean: "yesno" };
export const RESERVED = new Set(["rows", "row_count"]); // a CSV's (engine/graph/csv.py), never a field
const NAME = /^[a-z][a-z0-9_]{0,62}$/;

const propertiesOf = (schema: Schema): Schema => (isObject(schema.properties) ? schema.properties : {});
const requiredOf = (schema: Schema): string[] =>
  Array.isArray(schema.required) ? (schema.required as unknown[]).filter((r): r is string => typeof r === "string") : [];

/** What a property the list can't show is, in a few words. */
function what(s: Schema, root: Schema): string {
  const d = deref(s, root);
  if (d.type === "array") return "a list";
  if (d.type === "object" || isObject(d.properties)) return "an object of fields";
  if (typeof d.type === "string" && TYPE_OF[d.type]) return `${FIELD_TYPES.find((t) => t.value === TYPE_OF[d.type as string])!.label.toLowerCase()} with rules of its own`;
  return "a value of its own shape";
}

/** A property as a field, or null when the list can't show it as one without losing what it says. */
function fieldOf(name: string, s: unknown, required: boolean): InputField | null {
  if (!isObject(s) || Object.keys(s).some((k) => !PLAIN.has(k))) return null;
  const sensitive = s["x-sensitive"] === true;
  if ("x-sensitive" in s && typeof s["x-sensitive"] !== "boolean") return null;
  if (s.title !== undefined && typeof s.title !== "string") return null;
  if (s.description !== undefined && typeof s.description !== "string") return null;
  let type: FieldType | undefined;
  let values: string[] = [];
  if (s.enum !== undefined) {
    if (s.type !== "string" || s.format !== undefined || !Array.isArray(s.enum) || !s.enum.every((v) => typeof v === "string")) return null;
    type = "choice";
    values = s.enum;
  } else if (s.format !== undefined) {
    if (s.type !== "string" || s.format !== "date-time") return null;
    type = "datetime";
  } else if (typeof s.type === "string") type = TYPE_OF[s.type];
  if (!type) return null;
  return {
    name, label: (s.title) ?? "", type, required, sensitive, description: (s.description) ?? "",
    values, ...("default" in s ? { default: s.default } : {}),
  };  // prettier-ignore
}

/** The input's fields, in the schema's order. */
export function inputRows(schema: Schema): InputRow[] {
  const required = new Set(requiredOf(schema));
  return Object.entries(propertiesOf(schema)).map(([name, s]): InputRow => {
    const field = fieldOf(name, s, required.has(name));
    return field ? { kind: "field", field } : { kind: "other", name, required: required.has(name), what: what(isObject(s) ? s : {}, schema) };
  });
}

/** A field as the schema writes it: its keys in a fixed order, only those it has. */
function schemaOf(f: InputField): Schema {
  const out: Schema = { type: f.type === "whole" ? "integer" : f.type === "number" ? "number" : f.type === "yesno" ? "boolean" : "string" };
  if (f.label !== "") out.title = f.label;
  if (f.description !== "") out.description = f.description;
  if (f.type === "datetime") out.format = "date-time";
  if (f.type === "choice") out.enum = f.values;
  if (f.sensitive) out["x-sensitive"] = true;
  if ("default" in f) out.default = f.default;
  return out;
}

/** Whether a default still fits a field after its type or values changed: one that doesn't goes with the change. */
function fits(f: InputField, v: unknown): boolean {
  switch (f.type) {
    case "text":
    case "datetime":
      return typeof v === "string";
    case "whole":
      return typeof v === "number" && Number.isInteger(v);
    case "number":
      return typeof v === "number";
    case "yesno":
      return typeof v === "boolean";
    case "choice":
      return typeof v === "string" && f.values.includes(v);
  }
}

const withProperties = (schema: Schema, properties: Schema, required: string[]): Schema => {
  const out: Schema = { ...schema, properties };
  if (required.length > 0) out.required = required;
  else delete out.required;
  return out;
};

/** The schema with one field changed as `patch` says: a sensitive field has no default, a default that no longer fits
 * its type or values goes, and `required` follows. A field the list can't show is left as it is. */
export function setField(schema: Schema, name: string, patch: Partial<Omit<InputField, "name">>): Schema {
  const row = inputRows(schema).find((r) => r.kind === "field" && r.field.name === name);
  if (!row || row.kind !== "field") return schema;
  const next: InputField = { ...row.field, ...patch };
  if (next.type !== "choice") next.values = [];
  if (next.sensitive || ("default" in next && !fits(next, next.default)) || ("default" in patch && patch.default === undefined)) delete next.default;
  const properties = { ...propertiesOf(schema), [name]: schemaOf(next) };
  const was = requiredOf(schema);
  return withProperties(schema, properties, next.required ? (was.includes(name) ? was : [...was, name]) : was.filter((r) => r !== name));
}

/** Why a field can't take `to` as its name, or null: steps read it as `trigger.<name>`. */
export function nameProblem(schema: Schema, from: string | null, to: string): string | null {
  if (!NAME.test(to) || CEL_WORDS.has(to)) return "Lowercase letters, digits and _, starting with a letter; not in, true, false or null.";
  if (RESERVED.has(to)) return "`rows` and `row_count` are a CSV file's: declare the file, and its rows arrive there.";
  if (to !== from && Object.hasOwn(propertiesOf(schema), to)) return "Another field has this name.";
  return null;
}

/** The schema with a field renamed, in its place, its `required` entry following. */
export function renameField(schema: Schema, from: string, to: string): Schema {
  if (from === to || !Object.hasOwn(propertiesOf(schema), from)) return schema;
  const properties = Object.fromEntries(Object.entries(propertiesOf(schema)).map(([k, v]) => [k === from ? to : k, v]));
  return withProperties(schema, properties, requiredOf(schema).map((r) => (r === from ? to : r)));
}

/** The schema with a new, optional text field at the end, named `field_<n>` with the first n not taken. */
export function addField(schema: Schema): { schema: Schema; name: string } {
  let n = Object.keys(propertiesOf(schema)).length + 1;
  while (Object.hasOwn(propertiesOf(schema), `field_${n}`)) n++;
  const name = `field_${n}`;
  return { schema: withProperties(schema, { ...propertiesOf(schema), [name]: { type: "string" } }, requiredOf(schema)), name };
}

export function removeField(schema: Schema, name: string): Schema {
  const properties = Object.fromEntries(Object.entries(propertiesOf(schema)).filter(([k]) => k !== name));
  return withProperties(schema, properties, requiredOf(schema).filter((r) => r !== name));
}

/** Where a field is in the settings, as a pointer (RFC 6901): what its held edits and the server's problems name. */
export const fieldPointer = (name: string) => `/settings/input_schema/properties/${name.replaceAll("~", "~0").replaceAll("/", "~1")}`;

/** The input schema of a draft: an object schema with no fields when it has none. */
export const inputOf = (doc: GraphDoc): Schema => (isObject(doc.settings?.input_schema) ? doc.settings.input_schema : { type: "object" });

/** The draft with these settings: each key given replaced, `undefined` removing it, the rest as they were. */
export function setSettings(doc: GraphDoc, patch: Record<string, unknown>): GraphDoc {
  const settings: Record<string, unknown> = { ...(doc.settings ?? {}) };
  for (const [k, v] of Object.entries(patch)) {
    if (v === undefined) delete settings[k];
    else settings[k] = v;
  }
  return { ...doc, settings: settings };
}

const canonical = (v: unknown): string =>
  JSON.stringify(v, (_, x: unknown) => (isObject(x) ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1))) : x));

/** Whether two schemas say the same, whatever their keys' order. */
export const sameSchema = (a: unknown, b: unknown): boolean => canonical(a) === canonical(b);

/** The topic whose shape the input is, of a trigger type's: null when it's none of them. */
export function topicShaped(schema: Schema, topics: Record<string, unknown>): string | null {
  return Object.keys(topics).find((t) => sameSchema(schema, topics[t])) ?? null;
}

/** A row of an event's shape, read only: where a step reads it, what it is, and whether it may be missing. */
export interface ShapeRow {
  path: string;
  what: string;
  optional: boolean;
}

const KIND: Record<string, string> = { string: "text", integer: "whole number", number: "number", boolean: "yes or no", object: "object", array: "list" };

function kindWords(s: Schema): string {
  if (typeof s.const === "string") return `text, always ${s.const}`;
  return typeof s.type === "string" ? (KIND[s.type] ?? s.type) : "a value";
}

/** A topic's shape as rows (the InputMist board): its own fields, then one event's, at most `max` of those. */
export function shapeRows(schema: Schema, topic: string, max = 6): { rows: ShapeRow[]; more: boolean } {
  const rows: ShapeRow[] = [];
  const required = new Set(requiredOf(schema));
  let event: Schema | null = null;
  for (const [name, raw] of Object.entries(propertiesOf(schema))) {
    const s = deref(raw, schema);
    if (s.type === "array" && isObject(s.items)) {
      event = deref(s.items, schema);
      rows.push({ path: `trigger.${name}`, what: `list of ${topic.replaceAll("-", " ")}`, optional: !required.has(name) });
    } else rows.push({ path: `trigger.${name}`, what: kindWords(s), optional: !required.has(name) });
  }
  if (!event) return { rows, more: false };
  const fields = Object.entries(propertiesOf(event));
  const inEvent = new Set(requiredOf(event));
  for (const [name, raw] of fields.slice(0, max)) rows.push({ path: `[ ].${name}`, what: kindWords(deref(raw, schema)), optional: !inEvent.has(name) });
  return { rows, more: fields.length > max };
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/input.test.ts src/lib/csv.test.ts`

Expected: PASS: `Test Files  2 passed (2)`, `Tests  18 passed (18)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/csv.test.ts \
  frontend/src/lib/csv.ts \
  frontend/src/lib/input.test.ts \
  frontend/src/lib/input.ts
git commit -m "feat(editor): the input as form fields and a topic's shape, and the CSV file as a save takes it (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: The input as JSON, and the Triggers panel's held edits (`lib/inputJson.ts`, `lib/unapplied.ts`)

The input schema and the CSV file as one JSON text, read back only as a save would take it, with the line where it
breaks; a settings pointer said as a reader says it (`csv.columns[1].default`) and found in the text however it's laid
out, for the server's problems. And ruling 113 for workflow settings (ruling 4): an edit held under `TRIGGERS` at a
pointer into the settings, its base and lineage read there, applied by the same `applyAll` as a step's (JSON, a field's
name, a number, a column's header or name, a CSV file's limits), checked as a save would, and never written into a field
or a column that went.

**Files:**
- Create: `frontend/src/lib/inputJson.test.ts`
- Create: `frontend/src/lib/inputJson.ts`
- Modify: `frontend/src/lib/unapplied.test.ts`
- Modify: `frontend/src/lib/unapplied.ts`

**Interfaces:**
- Consumes: Task 4's `csvOf`, `csvProblem`, `rowsLimit`, `sizeLimit`, `textProblem`, `inputOf`, `nameProblem`,
  `renameField`, `setSettings`; `parseJson`, `setAt`, `valueAt`, `admission` from `lib/config.ts`.
- Produces: in `lib/inputJson.ts`: `InputDocument`, `inputText(doc)`, `readInput(text)`, `pointerWords(pointer)`,
  `pointerLines(text)`, `lineOf(text, pointer)`; in `lib/unapplied.ts`: `TRIGGERS`, which `baseOf`, `lineageOf` and
  `applyUnapplied` (so `applyAll`) handle.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/lib/inputJson.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import type { CsvSettings } from "./csv";
import { inputText, lineOf, pointerLines, pointerWords, readInput } from "./inputJson";
import type { GraphDoc } from "./workflows";

const SCHEMA = { type: "object", properties: { change: { type: "string", title: "Change ticket" } }, required: ["change"] };
const CSV: CsvSettings = {
  columns: [{ header: "AP name", name: "ap_name", type: "string", required: true }, { header: "Floor", name: "floor", type: "integer", required: true, default: 0 }],
};
const doc = (settings: GraphDoc["settings"]): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings });

describe("the input as JSON text", () => {
  it("shows the input schema, and the CSV file only when one is declared", () => {
    expect(JSON.parse(inputText(doc({ input_schema: SCHEMA })))).toEqual({ input_schema: SCHEMA });
    expect(JSON.parse(inputText(doc({ input_schema: SCHEMA, csv: CSV })))).toEqual({ input_schema: SCHEMA, csv: CSV });
    expect(JSON.parse(inputText({ graph_format: 1 }))).toEqual({ input_schema: { type: "object" } });
  });

  it("reads text a save takes back as the input, a null csv as none", () => {
    const text = JSON.stringify({ input_schema: SCHEMA, csv: CSV });
    expect(readInput(text)).toEqual({ value: { input_schema: SCHEMA, csv: CSV } });
    expect(readInput(JSON.stringify({ input_schema: SCHEMA, csv: null }))).toEqual({ value: { input_schema: SCHEMA } });
  });

  it("says why text isn't saved: where it breaks, what it must hold, what the save would refuse", () => {
    expect(readInput('{\n  "input_schema": {\n    "type": "object",\n  }\n}')).toEqual({ problem: "This isn't valid JSON, so it isn't saved.", line: 4 });
    expect(readInput("[]")).toEqual({ problem: "It holds `input_schema`, an object, and optionally `csv`.", line: null });
    expect(readInput('{"input_schema": {}, "vars": {}}')).toMatchObject({ line: null });
    expect(readInput('{"input_schema": {}, "csv": {"columns": []}}')).toEqual({ problem: "A CSV file has from 1 to 200 columns.", line: null });
    expect(readInput('{"input_schema": {"default": 1e400}}')).toEqual({ problem: "A number here is too large to keep, so it isn't saved.", line: null });
  });
});

describe("where a server's problem shows in the text", () => {
  const text = inputText(doc({ input_schema: SCHEMA, csv: CSV }));

  it("names a settings pointer as a reader says it", () => {
    expect(pointerWords("/settings/csv/columns/1/default")).toBe("csv.columns[1].default");
    expect(pointerWords("/settings/input_schema/properties/a~1b")).toBe("input_schema.properties.a/b");
    expect(pointerWords("/settings/input_schema")).toBe("input_schema");
  });

  it("finds the line each value starts on, and the nearest one the text has", () => {
    const lines = pointerLines(text);
    const at = (needle: string) => text.split("\n").findIndex((l) => l.includes(needle)) + 1;
    expect(lines.get("")).toBe(1);
    expect(lines.get("/input_schema/properties/change/title")).toBe(at('"Change ticket"'));
    expect(lines.get("/csv/columns/1")).toBe(at('"header": "Floor"') - 1);
    expect(lineOf(text, "/settings/csv/columns/1/default")).toBe(at('"default": 0'));
    expect(lineOf(text, "/settings/csv/columns/1/values")).toBe(at('"header": "Floor"') - 1); // not in the text: its column
    expect(lineOf(text, "/settings/vars_schema")).toBe(1);
  });

  it("reads text laid out any way, escapes and all", () => {
    const odd = '{"input_schema":{"properties":{"a/b":{"title":"q\\"x"}},"required":[]},\n"csv":{"columns":[{"header":"H","name":"h","type":"string"}]}}';
    expect(lineOf(odd, "/settings/input_schema/properties/a~1b/title")).toBe(1);
    expect(lineOf(odd, "/settings/csv/columns/0/name")).toBe(2);
  });
});
````

**In** `frontend/src/lib/unapplied.test.ts`, **replace**:

````ts
import { IF, SWITCH, TRANSFORM } from "../test/nodeTypes";
import { formula, literal, setConfig } from "./config";
import type { Path } from "./schemaForm";
import {
````

**with**:

````ts
import { IF, SWITCH, TRANSFORM } from "../test/nodeTypes";
import { formula, literal, setConfig } from "./config";
import type { CsvSettings } from "./csv";
import type { Path } from "./schemaForm";
import {
````

**In** `frontend/src/lib/unapplied.test.ts`, **replace**:

````ts
  STALE, applyAll, applyUnapplied, baseOf, isStale, lineageOf, parseNumber, unappliedFile, unappliedId, within,
  type Unapplied, type UnappliedKind,
} from "./unapplied";  // prettier-ignore
````

**with**:

````ts
  STALE, TRIGGERS, applyAll, applyUnapplied, baseOf, isStale, lineageOf, parseNumber, unappliedFile, unappliedId, within,
  type Unapplied, type UnappliedKind,
} from "./unapplied";  // prettier-ignore
````

**In** `frontend/src/lib/unapplied.test.ts`, **replace**:

````ts
    { step: "fetch", field: "When", at: "/when", text: "", why: "Write a number, like 3, -2 or 0.5.", condition },
  ]);
});
````

**with**:

````ts
    { step: "fetch", field: "When", at: "/when", text: "", why: "Write a number, like 3, -2 or 0.5.", condition },
  ]);
});

describe("the Triggers panel's held edits (4c-3b)", () => {
  const SCHEMA = { type: "object", properties: { site: { type: "string" }, floor: { type: "integer" } }, required: ["site"] };
  const CSV: CsvSettings = { columns: [{ header: "AP name", name: "ap_name", type: "string" }, { header: "Floor", name: "floor", type: "integer" }] };
  const settings = (more: Record<string, unknown> = {}): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings: { input_schema: SCHEMA, csv: CSV, ...more } });
  /** An edit held for the Triggers panel, typed over what `doc` holds there now. */
  function panel(doc: GraphDoc, kind: UnappliedKind, path: Path, text: string, more: Partial<Unapplied> = {}): Unapplied {
    const pointer = `/settings/${path.join("/")}`;
    const u: Unapplied = { id: unappliedId(TRIGGERS, kind, pointer), node: TRIGGERS, kind, pointer, path, label: pointer, text, why: null, base: "", lineage: [], ...more };
    return { ...u, base: baseOf(doc, u), lineage: lineageOf(doc, u) };
  }

  it("applies JSON text as the input, or says where it breaks and what a save would refuse", () => {
    const doc = settings();
    const text = JSON.stringify({ input_schema: { type: "object" } });
    expect(applied(applyUnapplied(doc, panel(doc, "json", [], text), undefined)).doc.settings).toEqual({ input_schema: { type: "object" } });
    expect(applyUnapplied(doc, panel(doc, "json", [], '{\n"input_schema": {,\n}'), undefined)).toEqual({ problem: "Line 2: This isn't valid JSON, so it isn't saved." });
    expect(applyUnapplied(doc, panel(doc, "json", [], '{"input_schema": {}, "csv": {"columns": []}}'), undefined)).toEqual({ problem: "A CSV file has from 1 to 200 columns." });
  });

  it("renames a field in place once its name can be one, or keeps it with why", () => {
    const doc = settings();
    const done = applied(applyUnapplied(doc, panel(doc, "name", ["input_schema", "properties"], "site_name", { from: "site" }), undefined));
    expect(Object.keys((done.doc.settings?.input_schema as { properties: object }).properties)).toEqual(["site_name", "floor"]);
    expect(applyUnapplied(doc, panel(doc, "name", ["input_schema", "properties"], "Floor", { from: "site" }), undefined)).toMatchObject({ problem: expect.stringMatching(/^Lowercase letters/) as unknown });
    expect(applyUnapplied(doc, panel(doc, "name", ["input_schema", "properties"], "floor", { from: "site" }), undefined)).toEqual({ problem: "Another field has this name." });
  });

  it("writes a default, a column's header and the file's limits within what a save takes", () => {
    const doc = settings();
    const at = (u: Unapplied) => applied(applyUnapplied(doc, u, undefined)).doc.settings;
    expect(at(panel(doc, "number", ["input_schema", "properties", "floor", "default"], "3", { whole: true }))?.input_schema).toMatchObject({ properties: { floor: { type: "integer", default: 3 } } });
    expect(at(panel(doc, "text", ["csv", "columns", 1, "header"], "Level"))?.csv).toMatchObject({ columns: [{ header: "AP name" }, { header: "Level" }] });
    expect(applyUnapplied(doc, panel(doc, "text", ["csv", "columns", 1, "header"], ""), undefined)).toEqual({ problem: "A header is from 1 to 200 characters." });
    expect(at(panel(doc, "limit", ["csv", "max_rows"], "500"))?.csv).toMatchObject({ max_rows: 500 });
    expect(at(panel(doc, "limit", ["csv", "max_bytes"], "0.5"))?.csv).toMatchObject({ max_bytes: 524_288 });
    expect(applyUnapplied(doc, panel(doc, "limit", ["csv", "max_rows"], "10001"), undefined)).toEqual({ problem: "A whole number from 1 to 10,000." });
    expect(applyUnapplied(doc, panel(doc, "limit", ["csv", "max_bytes"], "6"), undefined)).toEqual({ problem: "A size in MB, above 0 and up to 5." });
  });

  it("never writes into a field or a column that went, and is stale once a removal moved the columns", () => {
    const doc = settings();
    const typed = panel(doc, "number", ["input_schema", "properties", "floor", "default"], "3", { whole: true });
    const renamed: GraphDoc = { ...doc, settings: { ...doc.settings, input_schema: { type: "object", properties: { site: { type: "string" }, level: { type: "integer" } } } } };
    expect(applyUnapplied(renamed, typed, undefined)).toEqual({ problem: "Not applied: what it was typed in is no longer in the input." });
    const header = panel(doc, "text", ["csv", "columns", 1, "header"], "Level");
    const removed: GraphDoc = { ...doc, settings: { ...doc.settings, csv: { columns: [CSV.columns[1]!] } } };
    expect(isStale(removed, header)).toBe(true);
    expect(applyUnapplied(removed, header, undefined)).toEqual({ problem: STALE });
  });

  it("settles with the step's edits, a field's default before its rename", () => {
    const doc = settings();
    const name = panel(doc, "name", ["input_schema", "properties"], "level", { from: "floor" });
    const value = panel(doc, "number", ["input_schema", "properties", "floor", "default"], "2", { whole: true });
    const { doc: next, left } = applyAll(doc, [name, value], typeOf, () => true);
    expect(left).toEqual([]);
    expect((next.settings?.input_schema as { properties: object }).properties).toEqual({ site: { type: "string" }, level: { type: "integer", default: 2 } });
    expect(within(TRIGGERS, "/settings/input_schema/properties/floor")(value)).toBe(true);
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`):
`npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/inputJson.test.ts src/lib/unapplied.test.ts`

Expected: FAIL: `Test Files  2 failed (2)`, `Tests  5 failed | 19 passed (24)`. The run can't import `./inputJson`: it
doesn't exist yet. The failing tests are this task's new and changed ones: `applies JSON text as the input, or says
where it breaks and what a save would refuse`, `renames a field in place once its name can be one, or keeps it with
why`, `writes a default, a column's header and the file's limits within what a save takes`, `never writes into a field
or a column that went, and is stale once a removal moved the columns`, `settles with the step's edits, a field's default
before its rename`.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/lib/inputJson.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// The input as JSON (4c-3b; the InputEdit board's "Edit as JSON"): `settings.input_schema` and `settings.csv` as one
// text, saved with the draft as it's typed when it reads as JSON a save takes; text that doesn't stays held, with the
// line where it breaks (ruling 113). The server's problems name a pointer (`/settings/csv/columns/1/default`): each is
// shown at the line its value starts on.
import { parseJson } from "./config";
import { csvOf, csvProblem, type CsvSettings } from "./csv";
import { inputOf } from "./input";
import { isObject, type Schema } from "./schemaForm";
import type { GraphDoc } from "./workflows";

export interface InputDocument {
  input_schema: Schema;
  csv?: CsvSettings;
}

/** The draft's input as the JSON text shows it: its CSV file only when it declares one. */
export function inputText(doc: GraphDoc): string {
  const csv = csvOf(doc);
  const shown: InputDocument = { input_schema: inputOf(doc), ...(csv ? { csv } : {}) };
  return JSON.stringify(shown, null, 2);
}

/** The line a parse failed at, from the browser's own message: a line and column, or a position. */
function breakLine(text: string, message: string): number | null {
  const line = /line (\d+)/i.exec(message);
  if (line) return Number(line[1]);
  const at = /position (\d+)/i.exec(message);
  return at ? text.slice(0, Number(at[1])).split("\n").length : null;
}

/** The JSON text as the input it says, or why a save wouldn't take it, with its line when the text breaks. */
export function readInput(text: string): { value: InputDocument } | { problem: string; line: number | null } {
  try {
    JSON.parse(text);
  } catch (e) {
    const line = breakLine(text, e instanceof Error ? e.message : "");
    return { problem: "This isn't valid JSON, so it isn't saved.", line };
  }
  const parsed = parseJson(text);
  if ("problem" in parsed) return { problem: parsed.problem, line: null };
  const v = parsed.value;
  if (!isObject(v) || !isObject(v.input_schema) || Object.keys(v).some((k) => k !== "input_schema" && k !== "csv")) {
    return { problem: "It holds `input_schema`, an object, and optionally `csv`.", line: null };
  }
  const csv = v.csv === null ? undefined : v.csv;
  const problem = csvProblem(csv);
  if (problem) return { problem, line: null };
  return { value: { input_schema: v.input_schema, ...(csv ? { csv: csv as CsvSettings } : {}) } };
}

/** A settings pointer as a reader says it: `/settings/csv/columns/1/default` is `csv.columns[1].default`. */
export function pointerWords(pointer: string): string {
  const parts = pointer.replace(/^\/settings\//, "").split("/").map((p) => p.replaceAll("~1", "/").replaceAll("~0", "~"));
  return parts.reduce((out, p, i) => (/^(0|[1-9]\d*)$/.test(p) ? `${out}[${p}]` : i === 0 ? p : `${out}.${p}`), "");
}

const escape = (key: string) => key.replaceAll("~", "~0").replaceAll("/", "~1");

/** The line each value of valid JSON text starts on, by its pointer from the text's root ("" is the root). */
export function pointerLines(text: string): Map<string, number> {
  const lines = new Map<string, number>();
  let i = 0;
  let line = 1;
  const space = () => {
    while (i < text.length && /\s/.test(text[i]!)) {
      if (text[i] === "\n") line++;
      i++;
    }
  };
  const string = (): string => {
    const start = i;
    i++;
    while (text[i] !== '"') i += text[i] === "\\" ? 2 : 1;
    i++;
    return JSON.parse(text.slice(start, i)) as string;
  };
  const value = (at: string): void => {
    space();
    lines.set(at, line);
    const c = text[i];
    if (c === "{") {
      i++;
      space();
      if (text[i] === "}") return void i++;
      for (;;) {
        space();
        const key = string();
        space();
        i++; // the colon
        value(`${at}/${escape(key)}`);
        space();
        if (text[i++] === "}") return;
      }
    }
    if (c === "[") {
      i++;
      space();
      if (text[i] === "]") return void i++;
      for (let n = 0; ; n++) {
        value(`${at}/${n}`);
        space();
        if (text[i++] === "]") return;
      }
    }
    if (c === '"') return void string();
    while (i < text.length && !/[\s,\]}]/.test(text[i]!)) i++;
  };
  value("");
  return lines;
}

/** Where a settings problem shows in the JSON text: its line, the nearest value the text has on its way down. */
export function lineOf(text: string, pointer: string): number | null {
  const lines = pointerLines(text);
  let at = pointer.replace(/^\/settings/, "");
  for (;;) {
    const found = lines.get(at);
    if (found !== undefined) return found;
    if (at === "") return null;
    at = at.slice(0, at.lastIndexOf("/"));
  }
}
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
import {
  admission, formula, formulaProblem, keyProblem, literal, parseJson, renameEntry, renameKey, renamePort, rootOf,
  setConfig, setOptions, valueAt, type Changed,
} from "./config";  // prettier-ignore
````

**with**:

````ts
import {
  admission, formula, formulaProblem, keyProblem, literal, parseJson, renameEntry, renameKey, renamePort, rootOf,
  setAt, setConfig, setOptions, valueAt, type Changed,
} from "./config";  // prettier-ignore
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
import { findNode, idKey, portOf, sameId } from "./graph";
import { isGroup, valueProblem, write, type Condition } from "./builder";
````

**with**:

````ts
import { csvOf, csvProblem, rowsLimit, sizeLimit, textProblem } from "./csv";
import { findNode, idKey, portOf, sameId } from "./graph";
import { isGroup, valueProblem, write, type Condition } from "./builder";
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
import { valueOf, type Segments } from "./pills";
import { isObject, type Path } from "./schemaForm";
````

**with**:

````ts
import { inputOf, nameProblem, renameField, setSettings } from "./input";
import { readInput } from "./inputJson";
import { valueOf, type Segments } from "./pills";
import { isObject, type Path } from "./schemaForm";
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";

export type UnappliedKind =
````

**with**:

````ts
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";

/** The Triggers panel's edits are the editor's too (4c-3b; ruling 113): kept under this name where a step's id goes,
 * at a pointer into the draft's settings (`/settings/csv/columns/1/default`), their path the same from `settings`. */
export const TRIGGERS = "triggers";

export type UnappliedKind =
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
export interface Unapplied {
  id: string; // unappliedId(node, kind, pointer)
  node: string; // the step's id, as the draft writes it
  kind: UnappliedKind;
````

**with**:

````ts
export interface Unapplied {
  id: string; // unappliedId(node, kind, pointer)
  node: string; // the step's id, as the draft writes it; TRIGGERS for the Triggers panel's
  kind: UnappliedKind;
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
  pointer: string; // where it goes: in the step's config; "/options/<name>" for a limit; "" for the key
  path: Path; // the same as a path: a limit's is [its name]; a name's is its map's; the key's is []
  label: string; // the field's label, for the question that lists it
````

**with**:

````ts
  pointer: string; // where it goes: in the step's config; "/options/<name>" for a limit; "" for the key; "/settings/…"
  path: Path; // the same as a path: a limit's is [its name]; a name's is its map's; the key's is []
  label: string; // the field's label, for the question that lists it
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
 * and an undo can put another item there: an edit is applied only where its base still is (the review of revision 3). */
export function baseOf(doc: GraphDoc, u: Pick<Unapplied, "node" | "kind" | "path" | "from">): string {
  const node = findNode(doc, u.node);
  if (!node) return "gone";
````

**with**:

````ts
 * and an undo can put another item there: an edit is applied only where its base still is (the review of revision 3). */
export function baseOf(doc: GraphDoc, u: Pick<Unapplied, "node" | "kind" | "path" | "from">): string {
  if (u.node === TRIGGERS) {
    const at = valueAt(doc.settings ?? {}, u.path);
    if (u.kind === "name") return JSON.stringify(isObject(at) && Object.hasOwn(at, u.from ?? ""));
    if (u.kind === "json") return JSON.stringify([inputOf(doc), csvOf(doc)]);
    return JSON.stringify(at) ?? "undefined";
  }
  const node = findNode(doc, u.node);
  if (!node) return "gone";
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
 * in place beside it, which keeps them, doesn't. Maps are keyed by name, so they aren't part of it. */
export function lineageOf(doc: GraphDoc, u: Pick<Unapplied, "node" | "path">): unknown[] {
  const node = findNode(doc, u.node);
  const out: unknown[] = [];
````

**with**:

````ts
 * in place beside it, which keeps them, doesn't. Maps are keyed by name, so they aren't part of it. */
export function lineageOf(doc: GraphDoc, u: Pick<Unapplied, "node" | "path">): unknown[] {
  const out: unknown[] = [];
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
  let at: unknown = node?.config ?? {};
  for (const key of u.path) {
    if (typeof key === "number" && Array.isArray(at)) {
````

**with**:

````ts
  let at: unknown = u.node === TRIGGERS ? (doc.settings ?? {}) : (findNode(doc, u.node)?.config ?? {});
  for (const key of u.path) {
    if (typeof key === "number" && Array.isArray(at)) {
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
}

/** The draft with the edit applied, or why it can't be: its own rule, or the graph's admission (ruling 7). */
export function applyUnapplied(doc: GraphDoc, u: Unapplied, type: NodeType | undefined): Applied | { problem: string } {
````

**with**:

````ts
}

const GONE = "Not applied: what it was typed in is no longer in the input.";

/** A Triggers panel edit applied to the draft's settings, or why it can't be. What it was typed in must still be
 * there: written into a field or a column that went, it would make one up. */
function attemptSettings(doc: GraphDoc, u: Unapplied): Applied | { problem: string } {
  const settings = doc.settings ?? {};
  if (u.kind !== "json" && !isObject(valueAt(settings, u.path.slice(0, -1)))) return { problem: GONE };
  const at = (value: unknown): Applied => ({ doc: { ...doc, settings: setAt(settings, u.path, value) as GraphDoc["settings"] }, dropped: [], said: null, note: null });
  const made = (next: GraphDoc): Applied => ({ doc: next, dropped: [], said: null, note: null });
  switch (u.kind) {
    case "json": {
      const read = readInput(u.text);
      if ("problem" in read) return { problem: read.line === null ? read.problem : `Line ${read.line}: ${read.problem}` };
      return made(setSettings(doc, { input_schema: read.value.input_schema, csv: read.value.csv }));
    }
    case "name": {
      const schema = inputOf(doc);
      if (!isObject(schema.properties) || !Object.hasOwn(schema.properties, u.from ?? "")) return { problem: GONE };
      const to = u.text.trim();
      const problem = nameProblem(schema, u.from ?? null, to);
      return problem ? { problem } : made(setSettings(doc, { input_schema: renameField(schema, u.from ?? "", to) }));
    }
    case "number": {
      const parsed = parseNumber(u.text, u.whole ?? false);
      return "problem" in parsed ? parsed : at(parsed.value);
    }
    case "text": { // a CSV column's header or name
      const key = u.path.at(-1);
      if (key !== "header" && key !== "name") return { problem: GONE };
      const problem = textProblem(key, u.text);
      return problem ? { problem } : at(u.text);
    }
    case "limit": { // a CSV file's most rows, or its largest file in MB; empty leaves it to the platform's
      const read = u.path.at(-1) === "max_bytes" ? sizeLimit(u.text) : rowsLimit(u.text);
      return "problem" in read ? read : at(read.value);
    }
    default:
      return { problem: GONE };
  }
}

/** The draft with the edit applied, or why it can't be: its own rule, or the graph's admission (ruling 7). */
export function applyUnapplied(doc: GraphDoc, u: Unapplied, type: NodeType | undefined): Applied | { problem: string } {
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
  const node = findNode(doc, u.node);
  if (!node) return { problem: "Its step is no longer in the draft." };
````

**with**:

````ts
  if (u.node === TRIGGERS) {
    if (isStale(doc, u)) return { problem: STALE };
    const result = attemptSettings(doc, u);
    if ("problem" in result) return result;
    const refused = admission(result.doc) ?? csvProblem(result.doc.settings?.csv);
    return refused === null ? result : { problem: refused };
  }
  const node = findNode(doc, u.node);
  if (!node) return { problem: "Its step is no longer in the draft." };
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/inputJson.test.ts src/lib/unapplied.test.ts`

Expected: PASS: `Test Files  2 passed (2)`, `Tests  30 passed (30)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/inputJson.test.ts \
  frontend/src/lib/inputJson.ts \
  frontend/src/lib/unapplied.test.ts \
  frontend/src/lib/unapplied.ts
git commit -m "feat(editor): the input as JSON, and the Triggers panel's edits held as a step's are (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Webhook endpoints in words (`lib/endpoints.ts`)

A new endpoint's form as the API takes it: a trigger's endpoint names only its trigger, its name and its limits; another
sender's says its proof, where its events are and where their ids are (4c-3a ruling 1). An edit's changes: what the API
lets change, and only what changed. The words for each field the API refuses (`endpoint_invalid`), an endpoint's sender,
proof, events and ids, what's fixed once it's made, and how a sender uses its secret.

**Files:**
- Create: `frontend/src/lib/endpoints.test.ts`
- Create: `frontend/src/lib/endpoints.ts`

**Interfaces:**
- Consumes: `senderName` and the endpoint types (Task 3).
- Produces: `BODY_LIMITS`, `TOLERANCES`, `SIGNATURE_HEADER`, `TIMESTAMP_HEADER`, `EndpointForm`, `blankForm`,
  `allowlistOf`, `endpointBody`, `endpointPatch`, `FIELD_WORDS`, `proofWords`, `eventsWords`, `idsWords`, `senderWords`,
  `fixedWords`, `secretWords`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/lib/endpoints.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { ENDPOINT, MIST } from "../test/triggers";
import {
  allowlistOf, blankForm, endpointBody, endpointPatch, eventsWords, fixedWords, idsWords, secretWords, senderWords,
} from "./endpoints";  // prettier-ignore

describe("a new endpoint's form as the API takes it", () => {
  it("sends a trigger's endpoint its trigger, name and limits alone: the trigger decides the rest", () => {
    expect(endpointBody({ ...blankForm("mist.webhook"), name: " Mist prod ", allowlist: "203.0.113.0/24\n\n" })).toEqual({
      name: "Mist prod", allowlist: ["203.0.113.0/24"], body_limit: 1_048_576, trigger: "mist.webhook",
    });  // prettier-ignore
  });

  it("sends another sender's proof, events and ids", () => {
    const f = { ...blankForm(null), name: "Ticketing", auth: "hmac" as const, events: "at" as const, eventsAt: "/items", ids: "pointer" as const };
    expect(endpointBody(f)).toEqual({
      name: "Ticketing", allowlist: [], body_limit: 1_048_576, auth: "hmac", signature_header: "x-dewpoint-signature",
      timestamp_header: "x-dewpoint-timestamp", tolerance_s: 300, events_pointer: "/items", id_source: "pointer", id_pointer: "/id",
    });  // prettier-ignore
    expect(endpointBody({ ...blankForm(null), name: "A", events: "list", ids: "header", idHeader: "X-Request-Id" })).toMatchObject({
      auth: "bearer", events_pointer: "", id_source: "header", id_header: "x-request-id",
    });  // prettier-ignore
    expect(endpointBody({ ...blankForm(null), name: "A" })).toMatchObject({ events_pointer: null, id_source: "none" });
  });

  it("changes only what an edit may, and only what changed", () => {
    const f = { name: "Mist prod", signature: "", timestamp: "", tolerance: 300, allowlist: "", bodyLimit: 1_048_576 };
    expect(endpointPatch(ENDPOINT, f)).toEqual({});
    expect(endpointPatch(ENDPOINT, { ...f, name: "Mist", allowlist: "10.0.0.0/8", bodyLimit: 262_144, tolerance: 60 })).toEqual({
      name: "Mist", allowlist: ["10.0.0.0/8"], body_limit: 262_144,
    });  // prettier-ignore
    const hmac = { ...ENDPOINT, auth: "hmac" as const, signature_header: "x-sig", timestamp_header: "x-ts" };
    expect(endpointPatch(hmac, { ...f, signature: "x-sig", timestamp: "x-time", tolerance: 900 })).toEqual({ timestamp_header: "x-time", tolerance_s: 900 });
  });

  it("reads an allowlist one network a line", () => {
    expect(allowlistOf(" 10.0.0.0/8 \n\n2001:db8::/32\n")).toEqual(["10.0.0.0/8", "2001:db8::/32"]);
  });
});

describe("an endpoint in words", () => {
  it("names its sender, a trigger's or another's, and one no plugin declares any more", () => {
    expect(senderWords("mist.webhook", [MIST])).toBe("Mist");
    expect(senderWords(null, [MIST])).toBe("Another sender");
    expect(senderWords("old.hook", [MIST])).toBe("An unknown sender (old.hook)");
  });

  it("says where its events and their ids are", () => {
    expect(eventsWords(null)).toBe("The body is one event");
    expect(eventsWords("")).toBe("The body is a list of events");
    expect(eventsWords("/items")).toBe("The list at /items");
    expect(idsWords({ id_source: "pointer", id_pointer: "/id", id_header: null })).toBe("At /id in each event");
    expect(idsWords({ id_source: "header", id_pointer: null, id_header: "x-request-id" })).toBe("In the x-request-id header");
    expect(idsWords({ id_source: "none", id_pointer: null, id_header: null })).toBe("None");
  });

  it("says what's fixed once made, and what needs fixing first, as the EndpointOther board does", () => {
    const f = { ...blankForm(null), auth: "hmac" as const, events: "at" as const, eventsAt: "/items", ids: "pointer" as const, idPointer: "id" };
    expect(fixedWords(f)).toBe("Fixed once made: an HMAC signature; events in the list at /items; each event's id: its pointer needs fixing first.");
    expect(fixedWords(blankForm(null))).toBe("Fixed once made: a token; each delivery one event; no ids.");
  });

  it("says how a sender uses the secret shown once", () => {
    expect(secretWords({ ...ENDPOINT, auth: "hmac", signature_header: "x-dewpoint-signature", timestamp_header: "x-dewpoint-timestamp", tolerance_s: 300 }, "Another sender")).toBe(
      "The sender signs the Unix time in seconds, a dot, then the raw body, with HMAC-SHA256 under this secret. It sends the hex digest in x-dewpoint-signature (sha256= in front is fine) and the time in x-dewpoint-timestamp. A time more than 5 minutes off is refused.",
    );
    expect(secretWords(ENDPOINT, "Mist")).toBe(
      "In Mist's webhook, the sender sends it in a header: Authorization: Bearer and the token. Lost, it can't be shown again: rotate it for a new one.",
    );
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/endpoints.test.ts`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  no tests`. The run can't import `./endpoints`: it doesn't exist yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/lib/endpoints.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// Webhook endpoints in words, and the new endpoint's form as the API takes it (4c-3b; the Endpoints, EndpointNew and
// EndpointOther boards; 4c-3a ruling 1). An endpoint made for a trigger takes that trigger's settings; another
// sender's says how it proves itself, where its events are and where their ids are, all fixed once it's made. The
// API checks every field and names those it refuses (`endpoint_invalid`); the words for each are here.
import type { Endpoint, EndpointIn, EndpointPatch, TriggerType } from "./triggers";
import { senderName } from "./triggers";

export const BODY_LIMITS = [
  { value: 262_144, label: "256 KB" },
  { value: 1_048_576, label: "1 MB" },
  { value: 5_242_880, label: "5 MB" },
] as const;
export const TOLERANCES = [
  { value: 60, label: "1 minute" },
  { value: 300, label: "5 minutes" },
  { value: 900, label: "15 minutes" },
] as const;
export const SIGNATURE_HEADER = "x-dewpoint-signature";
export const TIMESTAMP_HEADER = "x-dewpoint-timestamp";

/** What the new endpoint's form holds: a trigger's key, or another sender's own settings. */
export interface EndpointForm {
  name: string;
  trigger: string | null; // a trigger type's key, or null for another sender
  auth: "bearer" | "hmac";
  signature: string;
  timestamp: string;
  tolerance: number;
  events: "body" | "list" | "at"; // the body is one event, a list of them, or holds a list at `eventsAt`
  eventsAt: string;
  ids: "none" | "pointer" | "header";
  idPointer: string;
  idHeader: string;
  allowlist: string; // one network a line
  bodyLimit: number;
}

export const blankForm = (trigger: string | null): EndpointForm => ({
  name: "", trigger, auth: "bearer", signature: SIGNATURE_HEADER, timestamp: TIMESTAMP_HEADER, tolerance: 300, events: "body",
  eventsAt: "/items", ids: "none", idPointer: "/id", idHeader: "x-request-id", allowlist: "", bodyLimit: 1_048_576,
});  // prettier-ignore

/** An allowlist as typed, one network a line, blank lines dropped. */
export const allowlistOf = (text: string): string[] => text.split("\n").map((l) => l.trim()).filter((l) => l !== "");

/** The form as the API takes it: a trigger's endpoint names only its trigger, its name and its limits. */
export function endpointBody(f: EndpointForm): EndpointIn {
  const common = { name: f.name.trim(), allowlist: allowlistOf(f.allowlist), body_limit: f.bodyLimit };
  if (f.trigger !== null) return { ...common, trigger: f.trigger };
  return {
    ...common,
    auth: f.auth,
    ...(f.auth === "hmac" ? { signature_header: f.signature.trim(), timestamp_header: f.timestamp.trim(), tolerance_s: f.tolerance } : {}),
    events_pointer: f.events === "body" ? null : f.events === "list" ? "" : f.eventsAt.trim(),
    id_source: f.ids,
    ...(f.ids === "pointer" ? { id_pointer: f.idPointer.trim() } : f.ids === "header" ? { id_header: f.idHeader.trim().toLowerCase() } : {}),
  };
}

/** What an edit changes: only the fields it may (the API's UPDATABLE), and only those changed. */
export function endpointPatch(e: Endpoint, f: Pick<EndpointForm, "name" | "signature" | "timestamp" | "tolerance" | "allowlist" | "bodyLimit">): EndpointPatch {
  const out: EndpointPatch = {};
  if (f.name.trim() !== e.name) out.name = f.name.trim();
  if (e.auth === "hmac" && f.signature.trim() !== e.signature_header) out.signature_header = f.signature.trim();
  if (e.auth === "hmac" && f.timestamp.trim() !== e.timestamp_header) out.timestamp_header = f.timestamp.trim();
  if (e.auth === "hmac" && f.tolerance !== e.tolerance_s) out.tolerance_s = f.tolerance;
  const allowlist = allowlistOf(f.allowlist);
  if (allowlist.join("\n") !== e.allowlist.join("\n")) out.allowlist = allowlist;
  if (f.bodyLimit !== e.body_limit) out.body_limit = f.bodyLimit;
  return out;
}

/** The API's refusals of an endpoint's fields (`endpoint_invalid`'s `fields`), in words, by the field they show at. */
export const FIELD_WORDS: Record<string, string> = {
  trigger: "No plugin declares this sender any more.",
  events_pointer: "A pointer into the body starts with /, like /items, at most 256 characters.",
  id_pointer: "A pointer starts with /, like /id, at most 256 characters.",
  id_header: "A header's name: lowercase letters, digits and -, not one a proxy sets, like authorization or host.",
  signature_header: "A header's name: lowercase letters, digits and -, not one a proxy sets.",
  timestamp_header: "A header's name: lowercase letters, digits and -, not one a proxy sets.",
  allowlist: "One network a line, like 203.0.113.0/24, with no host bits past its prefix; up to 32.",
  auth: "This sender decides how it proves itself.",
};

export const proofWords = (auth: string) => (auth === "hmac" ? "An HMAC signature" : "A token");

/** Where an endpoint's events are, in words. */
export function eventsWords(pointer: string | null): string {
  if (pointer === null) return "The body is one event";
  if (pointer === "") return "The body is a list of events";
  return `The list at ${pointer}`;
}

/** Where an endpoint's events' ids are, in words. */
export function idsWords(e: Pick<Endpoint, "id_source" | "id_pointer" | "id_header">): string {
  if (e.id_source === "pointer") return `At ${e.id_pointer ?? ""} in each event`;
  if (e.id_source === "header") return `In the ${e.id_header ?? ""} header`;
  return "None";
}

/** Who sends to an endpoint: its trigger's sender, another sender, or one no plugin declares any more. */
export function senderWords(trigger: string | null, types: TriggerType[]): string {
  if (trigger === null) return "Another sender";
  const type = types.find((t) => t.key === trigger);
  return type ? senderName(type) : `An unknown sender (${trigger})`;
}

/** What's fixed once another sender's endpoint is made, as the form says it before (the EndpointOther board). */
export function fixedWords(f: EndpointForm): string {
  const events = f.events === "body" ? "each delivery one event" : f.events === "list" ? "events in a list, the body" : f.eventsAt.trim().startsWith("/") ? `events in the list at ${f.eventsAt.trim()}` : "events in a list: its pointer needs fixing first";
  const ids =
    f.ids === "none" ? "no ids"
    : f.ids === "pointer" ? (f.idPointer.trim().startsWith("/") ? `each event's id at ${f.idPointer.trim()}` : "each event's id: its pointer needs fixing first")
    : f.idHeader.trim() === "" ? "each event's id: its header needs naming first" : `each event's id in the ${f.idHeader.trim().toLowerCase()} header`;  // prettier-ignore
  return `Fixed once made: ${proofWords(f.auth).replace(/^A/, "a")}; ${events}; ${ids}.`;
}

/** How a sender uses an endpoint's secret, beside the secret shown once. */
export function secretWords(e: Pick<Endpoint, "auth" | "signature_header" | "timestamp_header" | "tolerance_s">, sender: string): string {
  if (e.auth === "hmac") {
    const off = TOLERANCES.find((t) => t.value === e.tolerance_s)?.label ?? `${e.tolerance_s} seconds`;
    return `The sender signs the Unix time in seconds, a dot, then the raw body, with HMAC-SHA256 under this secret. It sends the hex digest in ${e.signature_header ?? SIGNATURE_HEADER} (sha256= in front is fine) and the time in ${e.timestamp_header ?? TIMESTAMP_HEADER}. A time more than ${off} off is refused.`;
  }
  return `${sender === "Another sender" ? "The sender" : `In ${sender}'s webhook, the sender`} sends it in a header: Authorization: Bearer and the token. Lost, it can't be shown again: rotate it for a new one.`;
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/endpoints.test.ts`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  8 passed (8)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/endpoints.test.ts \
  frontend/src/lib/endpoints.ts
git commit -m "feat(settings): a webhook endpoint's form as the API takes it, and endpoints in words (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Milestone 1's checks.** The whole unit suite, typecheck and lint; then append to the ledger
  `### 4c-3b, milestone 1 (<date>)`: Tasks 1–6's commits, the suite's count as run, and each mid-slice ruling (M80
  onward) or none. Commit it (`docs(editor-4): 4c-3b milestone 1`). No pause: Milestone 2 follows.

---

# Milestone 2 — the Triggers panel and its input

### Task 7: The start card and the Triggers panel: its input as fields and as JSON

The start card opens the panel and sums up what starts a run (ruling 1). The panel joins the editor's side column
(ruling 2): its writes go through `change`, its held text is the editor's (ruling 4), and "Go to it" in the edits not
applied opens it there. Its input is a list of fields with a field editor (ruling 3), or JSON written as it's typed
whenever a save would take it. Text typed over what has since changed is never written as it's typed, only by Apply here
(ruling 4), and focus goes back to what opened a part once it closes (the review of revision 1); a renamed field's
editor stays as it is (the review of revision 2). The panel's parts share a context; a test harness renders it over a
draft. The editor's stand-in canvas, in its tests, opens the panel from Start and adds a step from "Add the first step".

**Files:**
- Modify: `frontend/src/routes/editor/Canvas.tsx`
- Modify: `frontend/src/routes/editor/Editor.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Modify: `frontend/src/routes/editor/StartCard.tsx`
- Create: `frontend/src/routes/editor/triggers/FieldEditor.tsx`
- Create: `frontend/src/routes/editor/triggers/InputJson.tsx`
- Create: `frontend/src/routes/editor/triggers/InputSection.test.tsx`
- Create: `frontend/src/routes/editor/triggers/InputSection.tsx`
- Create: `frontend/src/routes/editor/triggers/TriggersPanel.tsx`
- Create: `frontend/src/routes/editor/triggers/context.ts`
- Create: `frontend/src/routes/editor/triggers/harness.tsx`
- Create: `frontend/src/routes/editor/triggers/parts.tsx`

**Interfaces:**
- Consumes: Tasks 3–5.
- Produces: `TriggersPanel({ value, focusAt, onClose })`; `Triggers`, `PanelActions` (with `stale`, `rebase`),
  `READ_ONLY`, `TriggersContext`, `useTriggers` (`triggers/context.ts`); `Section` (with `box`), `problemsAt`,
  `Problems`, `Check`, `Values`, `writeTyped`, `heldWhy`, `StaleEdit`, `useFocusBack` (`triggers/parts.tsx`);
  `InputSection({ focusAt })`, `FocusAt`; `FieldEditor`; `InputJson`, `JSON_AT`; the harness's `showPanel(options)`;
  `StartData`'s `summary`, `open`, `onOpen`; `CanvasProps.start`; the editor's side panel `{ kind: "triggers"; at? }`.

- [ ] **Step 1: Write the failing tests**

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
import { formula } from "../../lib/config";
import { STALE } from "../../lib/unapplied";

// Every document the stand-in canvas was handed: what was drawn, and what never was.
````

**with**:

````tsx
import { formula } from "../../lib/config";
import { STALE } from "../../lib/unapplied";
import { SCHEDULE } from "../../test/triggers";

// Every document the stand-in canvas was handed: what was drawn, and what never was.
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
          data-conditional={[...props.conditional].join(",")}
        >
          <button data-item="start" onClick={() => props.onItem({ kind: "after", from: null })}>Start</button>
          {(props.doc.nodes ?? []).map((n) => (
            <span key={n.id}>
````

**with**:

````tsx
          data-conditional={[...props.conditional].join(",")}
        >
          <button data-item="start" data-summary={props.start.summary} aria-expanded={props.start.open} onClick={props.start.onOpen}>Start</button>
          <button onClick={() => props.onItem({ kind: "after", from: null })}>Add the first step</button>
          {(props.doc.nodes ?? []).map((n) => (
            <span key={n.id}>
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
  executable: null, blocked_by: [], created_at: "", updated_at: "", unpublished_changes: true, draft_graph_hash: "h1",
  last_run: null, last_simulation: null, runs_24h: { live: 0, simulate: 0 }, needs_attention: [], draft: draftWith(),
};  // prettier-ignore
const BASE = "/api/v1/t/t1/workflows/w1";
````

**with**:

````tsx
  executable: null, blocked_by: [], created_at: "", updated_at: "", unpublished_changes: true, draft_graph_hash: "h1",
  last_run: null, last_simulation: null, runs_24h: { live: 0, simulate: 0 }, needs_attention: [], draft: draftWith(),
  triggers: { schedules: 0, schedules_enabled: 0, webhook_bindings: 0, csv: false },
};  // prettier-ignore
const BASE = "/api/v1/t/t1/workflows/w1";
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
it("adds a first step from the start card, then one after it, through the picker", async () => {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(await screen.findByRole("button", { name: "after transform" }));
````

**with**:

````tsx
it("adds a first step from the start card, then one after it, through the picker", async () => {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Add the first step" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(await screen.findByRole("button", { name: "after transform" }));
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
async function withTwoSteps() {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(await screen.findByRole("button", { name: "after transform" }));
````

**with**:

````tsx
async function withTwoSteps() {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Add the first step" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(await screen.findByRole("button", { name: "after transform" }));
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx

async function addTransform() {
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await screen.findByRole("button", { name: "transform" });
````

**with**:

````tsx

async function addTransform() {
  await userEvent.click(screen.getByRole("button", { name: "Add the first step" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await screen.findByRole("button", { name: "transform" });
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Versions" })));
});
````

**with**:

````tsx
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Versions" })));
});

describe("the Triggers panel (4c-3b)", () => {
  const settings = () => drawn.at(-1)!.doc.settings;
  beforeEach(() => {
    answers.set(`GET ${BASE}/schedules`, () => json({ schedules: [] }));
    answers.set(`GET ${BASE}/webhook-bindings`, () => json({ bindings: [] }));
    answers.set("GET /api/v1/trigger-types", () => json([]));
  });

  it("opens from the start card, its heading focused, and gives focus back to the card when it closes", async () => {
    await show();
    const start = screen.getByRole("button", { name: "Start" });
    await userEvent.click(start);
    expect(start.getAttribute("aria-expanded")).toBe("true");
    const panel = screen.getByRole("complementary", { name: "Triggers" });
    await vi.waitFor(() => expect(document.activeElement).toBe(within(panel).getByRole("heading", { name: "Triggers" })));
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(start));
    expect(start.getAttribute("aria-expanded")).toBe("false");
  });

  it("sums up what starts a run on the start card: the workflow's own counts, then the live rows", async () => {
    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, triggers: { schedules: 1, schedules_enabled: 1, webhook_bindings: 1, csv: false } }));
    answers.set(`GET ${BASE}/schedules`, () => json({ schedules: [SCHEDULE, { ...SCHEDULE, id: "s2" }] }));
    answers.set(`GET ${BASE}/webhook-bindings`, () => json({ bindings: [] }));
    await show();
    await vi.waitFor(() => expect(screen.getByRole("button", { name: "Start" }).dataset.summary).toBe("By hand · 2 schedules"));
  });

  it("writes the input to the draft through undo, a field's typing one step", async () => {
    await show();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    const panel = screen.getByRole("complementary", { name: "Triggers" });
    await userEvent.click(within(panel).getByRole("button", { name: "＋ Field" }));
    expect(settings()?.input_schema).toEqual({ type: "object", properties: { field_1: { type: "string" } } });
    await userEvent.type(within(panel).getByRole("textbox", { name: "Label" }), "Site");
    expect(settings()?.input_schema).toMatchObject({ properties: { field_1: { type: "string", title: "Site" } } });
    await userEvent.click(within(panel).getByRole("heading", { name: "Triggers" })); // focus leaves the field
    await userEvent.keyboard("{Control>}z{/Control}");
    expect(settings()?.input_schema).toEqual({ type: "object", properties: { field_1: { type: "string" } } }); // the label's typing, whole
    await userEvent.keyboard("{Control>}z{/Control}");
    expect(settings()?.input_schema).toBeUndefined();
  });

  it("keeps JSON it can't save as an edit not applied: counted, listed as Triggers', and gone to in the panel", async () => {
    await show();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    const panel = screen.getByRole("complementary", { name: "Triggers" });
    await userEvent.click(within(panel).getByRole("button", { name: "Edit as JSON" }));
    const box = within(panel).getByRole("textbox", { name: "The input's schema and CSV columns" });
    await userEvent.clear(box);
    await userEvent.type(box, "{{");
    expect(panel.textContent).toContain("This isn't valid JSON, so it isn't saved.");
    await userEvent.click(screen.getByRole("button", { name: "1 edit not applied" }));
    const list = screen.getByRole("complementary", { name: "Edits not applied" });
    expect(list.textContent).toContain("Triggers · The input as JSON");
    await userEvent.click(within(list).getByRole("button", { name: "Go to it: Triggers · The input as JSON" }));
    const back = screen.getByRole("complementary", { name: "Triggers" });
    expect(within(back).getByRole<HTMLTextAreaElement>("textbox", { name: "The input's schema and CSV columns" }).value).toBe("{");
  });

  it("never writes JSON typed over an input an undo changed since, until Apply here", async () => {
    // The review of revision 1, through the editor's own actions: its stale check, and Apply here.
    await show();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    const panel = screen.getByRole("complementary", { name: "Triggers" });
    await userEvent.click(within(panel).getByRole("button", { name: "＋ Field" }));
    await userEvent.click(within(panel).getByRole("button", { name: "Done" }));
    await userEvent.click(within(panel).getByRole("button", { name: "Edit as JSON" }));
    const box = within(panel).getByRole("textbox", { name: "The input's schema and CSV columns" });
    await userEvent.clear(box);
    await userEvent.paste("{");
    await userEvent.click(within(panel).getByRole("heading", { name: "Triggers" })); // focus leaves the text
    await userEvent.keyboard("{Control>}z{/Control}"); // the field's addition undone, under the JSON
    expect(settings()?.input_schema).toBeUndefined();
    await userEvent.click(box);
    await userEvent.paste('"input_schema": {"type": "object"}}');
    expect(settings()?.input_schema).toBeUndefined();
    expect(panel.textContent).toContain(STALE);
    await userEvent.click(within(panel).getByRole("button", { name: "Apply here: The input as JSON" }));
    expect(settings()?.input_schema).toEqual({ type: "object" });
  });

  it("shows a viewer the triggers read only, and says why", async () => {
    role = "viewer";
    await show();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    const panel = screen.getByRole("complementary", { name: "Triggers" });
    expect(panel.textContent).toContain("You can see this workflow's triggers; changing them needs the editor role.");
    expect(within(panel).queryByRole("button", { name: "＋ Field" })).toBeNull();
    expect(within(panel).queryByRole("button", { name: "＋ Schedule" })).toBeNull();
    expect(within(panel).getByRole("button", { name: "Show as JSON" })).toBeTruthy();
  });
});
````

**Create** `frontend/src/routes/editor/triggers/InputSection.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MIST } from "../../../test/triggers";
import { STALE } from "../../../lib/unapplied";
import type { Diagnostic, GraphDoc, Validation } from "../../../lib/workflows";
import { fakeApi, json } from "../drawer/harness";
import { showPanel } from "./harness";

const SCHEMA = {
  type: "object",
  properties: { site: { type: "string", title: "Site" }, tags: { type: "array", items: { type: "string" } } },
  required: ["site"],
};
const draft = (settings: GraphDoc["settings"]): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings });
const input = () => screen.getByRole("region", { name: /^Input/ });
const checked = (diagnostics: Diagnostic[]): Validation => ({
  draft_revision: 1, valid: false, diagnostics, expressions: [], taint: { sites: [], declassified: [] }, conditional_steps: [], schedule_breaks: [],
});  // prettier-ignore
const problem = (field: string, code: string, message: string): Diagnostic => ({ code, severity: "error", message, fix: null, node: null, field });

beforeEach(() => {
  fakeApi({
    "GET /api/v1/trigger-types": () => json([MIST]),
    "GET /api/v1/t/t1/workflows/w1/schedules": () => json({ schedules: [] }),
    "GET /api/v1/t/t1/workflows/w1/webhook-bindings": () => json({ bindings: [] }),
    "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ workflow_id: "w1", version_id: "v3", fields: [], csv: null }),
    "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: draft({ input_schema: SCHEMA }) }),
  });
});
afterEach(() => vi.restoreAllMocks());

describe("the input as form fields", () => {
  it("lists each field as the InputFields board does, and what the list can't show, read only", async () => {
    await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    const rows = within(input()).getAllByRole("listitem").map((li) => li.textContent);
    expect(rows[0]).toContain("site · Site · Text · required");
    expect(rows[1]).toContain("tags · a list · read only here");
    expect(within(input()).getByRole("button", { name: "Edit site" })).toBeTruthy();
    expect(within(input()).queryByRole("button", { name: "Edit tags" })).toBeNull();
    expect(input().textContent).toContain("A field the list can't show (a list, an object of fields) appears read only: Edit as JSON changes it.");
  });

  it("adds a field and edits it, each control's typing one undo step", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "＋ Field" }));
    const field = within(input()).getByRole("group", { name: "The field field_3" });
    await userEvent.type(within(field).getByRole("textbox", { name: "Label" }), "Note");
    expect(panel.settings()?.input_schema).toMatchObject({ properties: { field_3: { type: "string", title: "Note" } } });
    expect(new Set(panel.writes.slice(1).map((w) => w.mark))).toEqual(new Set(["/settings/input_schema/properties/field_3/title"]));
    await userEvent.selectOptions(within(field).getByRole("combobox", { name: "Type" }), "Yes or no");
    await userEvent.click(within(field).getByRole("checkbox", { name: "Required" }));
    expect(panel.settings()?.input_schema).toMatchObject({ properties: { field_3: { type: "boolean", title: "Note" } }, required: ["site", "field_3"] });
  });

  it("holds a name until it can be one, and applies it when focus leaves it", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    const name = within(input()).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Site");
    fireEvent.blur(name);
    expect(input().textContent).toContain("Lowercase letters, digits and _, starting with a letter; not in, true, false or null.");
    expect(Object.keys((panel.settings()?.input_schema as { properties: object }).properties)).toEqual(["site", "tags"]);
    await userEvent.clear(name);
    await userEvent.type(name, "site_name{Enter}");
    expect(Object.keys((panel.settings()?.input_schema as { properties: object }).properties)).toEqual(["site_name", "tags"]);
    expect(within(input()).getByRole("group", { name: "The field site_name" })).toBeTruthy(); // still open, on its new name
    expect(panel.held()).toEqual([]);
  });

  it("holds a number's default that doesn't parse, and writes one that does", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: { type: "object", properties: { floor: { type: "integer" } } } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit floor" }));
    const value = within(input()).getByRole("textbox", { name: "Default" });
    await userEvent.type(value, "2.5");
    expect(input().textContent).toContain("A whole number, like 42.");
    expect(panel.held()).toHaveLength(1);
    await userEvent.clear(value);
    await userEvent.type(value, "3");
    expect(panel.settings()?.input_schema).toEqual({ type: "object", properties: { floor: { type: "integer", default: 3 } } });
    expect(panel.held()).toEqual([]);
  });

  it("gives a sensitive field no default and no Choice: either would be written into the workflow", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: { type: "object", properties: { token: { type: "string", default: "x" } } } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit token" }));
    await userEvent.click(within(input()).getByRole("checkbox", { name: "Sensitive" }));
    expect(panel.settings()?.input_schema).toEqual({ type: "object", properties: { token: { type: "string", "x-sensitive": true } } });
    expect(within(input()).getByRole<HTMLInputElement>("textbox", { name: "Default" }).disabled).toBe(true);
    expect(within(input()).getByRole<HTMLOptionElement>("option", { name: "Choice" }).disabled).toBe(true);
  });

  it("gives focus back to a field's Edit once its editor closes, by Done or Escape, and to ＋ Field once it's removed", async () => {
    // The review of revision 1: Done left focus on the page's body.
    await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    const edit = () => within(input()).getByRole("button", { name: "Edit site" });
    await userEvent.click(edit());
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(edit()));
    await userEvent.click(edit());
    await userEvent.keyboard("{Escape}");
    await vi.waitFor(() => expect(document.activeElement).toBe(edit()));
    await userEvent.click(edit());
    await userEvent.click(within(input()).getByRole("button", { name: "Remove field" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "＋ Field" })));
  });

  it("keeps a renamed field's editor as it is: Tab moves on from its name, and one click on Done closes it", async () => {
    // The review of revision 2: the rename remounted the editor, Tab landed back on Name, and Done's first click was lost.
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit site" }));
    const name = () => within(input()).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name());
    await userEvent.type(name(), "where");
    await userEvent.tab();
    expect(Object.keys(panel.settings()?.input_schema?.properties as object)).toEqual(["where", "tags"]);
    expect(document.activeElement).toBe(within(input()).getByRole("textbox", { name: "Label" }));
    await userEvent.clear(name());
    await userEvent.type(name(), "place");
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    expect(Object.keys(panel.settings()?.input_schema?.properties as object)).toEqual(["place", "tags"]);
    expect(within(input()).queryByRole("group", { name: /^The field / })).toBeNull();
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Edit place" })));
  });

  it("shows the server's problems at their field", async () => {
    await showPanel({
      doc: draft({ input_schema: { type: "object", properties: { rows: { type: "string" } } } }),
      check: checked([problem("/settings/input_schema/properties/rows", "settings.reserved_name", "`rows` and `row_count` are a CSV's.")]),
    });
    expect(within(input()).getAllByRole("listitem")[0]!.textContent).toContain("`rows` and `row_count` are a CSV's.");
  });
});

describe("the input as JSON", () => {
  it("writes text that reads, holds text that doesn't with its line, and shows the server's problems at theirs", async () => {
    const csv = { columns: [{ header: "Floor", name: "floor", type: "integer" as const, required: true, default: 0 }] };
    const panel = await showPanel({
      doc: draft({ input_schema: { type: "object" }, csv }),
      check: checked([problem("/settings/csv/columns/0/default", "csv.required_default", "A required column takes no default.")]),
    });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    const box = within(input()).getByRole<HTMLTextAreaElement>("textbox", { name: "The input's schema and CSV columns" });
    const line = box.value.split("\n").findIndex((l) => l.includes('"default": 0')) + 1;
    expect(input().textContent).toContain(`Line ${line}, csv.columns[0].default: A required column takes no default.`);
    fireEvent.change(box, { target: { value: '{"input_schema": {"type": "object", "properties": {"a": {"type": "string"}}}}' } });
    expect(panel.settings()).toEqual({ input_schema: { type: "object", properties: { a: { type: "string" } } } });
    fireEvent.change(box, { target: { value: '{\n"input_schema": {,\n}' } });
    expect(input().textContent).toContain("Line 2: This isn't valid JSON, so it isn't saved.");
    expect(panel.held().map((u) => u.pointer)).toEqual(["/settings/input"]);
    await userEvent.click(within(input()).getByRole("button", { name: "Discard what isn't saved" }));
    expect(panel.held()).toEqual([]);
    expect(JSON.parse(box.value)).toEqual({ input_schema: { type: "object", properties: { a: { type: "string" } } } });
  });
});

describe("the input as JSON, typed over what changed since", () => {
  const box = () => within(input()).getByRole<HTMLTextAreaElement>("textbox", { name: "The input's schema and CSV columns" });

  it("takes focus when it opens, and gives it back to Edit as JSON when it closes", async () => {
    await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(box()));
    await userEvent.click(within(input()).getByRole("button", { name: "Back to the fields" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Edit as JSON" })));
  });

  it("never writes JSON typed over an input that changed since, until Apply here", async () => {
    // The review of revision 1: JSON held, a field added, then the JSON finished: the new field was gone.
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    fireEvent.change(box(), { target: { value: '{"input_schema": {"type": "object"' } });
    await userEvent.click(within(input()).getByRole("button", { name: "Back to the fields" }));
    await userEvent.click(within(input()).getByRole("button", { name: "＋ Field" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    expect(input().textContent).toContain(STALE);
    fireEvent.change(box(), { target: { value: '{"input_schema": {"type": "object"}}' } });
    expect(Object.keys(panel.settings()?.input_schema?.properties as object)).toEqual(["site", "tags", "field_3"]);
    expect(input().textContent).toContain(STALE);
    await userEvent.click(within(input()).getByRole("button", { name: "Apply here: The input as JSON" }));
    expect(panel.settings()?.input_schema).toEqual({ type: "object" });
    expect(panel.held()).toEqual([]);
  });

  it("discards JSON typed over an input that changed since, showing the input as it is", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit as JSON" }));
    fireEvent.change(box(), { target: { value: "{" } });
    panel.replace(draft({ input_schema: { type: "object" } })); // an undo, under it
    await userEvent.click(within(input()).getByRole("button", { name: "Discard the edit to The input as JSON" }));
    expect(panel.held()).toEqual([]);
    expect(JSON.parse(box().value)).toEqual({ input_schema: { type: "object" } });
    await vi.waitFor(() => expect(document.activeElement).toBe(box()));
  });
});

it("shows the input read only to a viewer, as JSON too", async () => {
  await showPanel({ doc: draft({ input_schema: SCHEMA }), editable: false, viewer: true });
  expect(within(input()).queryByRole("button", { name: "Edit site" })).toBeNull();
  expect(within(input()).queryByRole("button", { name: "＋ Field" })).toBeNull();
  await userEvent.click(within(input()).getByRole("button", { name: "Show as JSON" }));
  expect(within(input()).getByRole<HTMLTextAreaElement>("textbox", { name: "The input's schema and CSV columns" }).readOnly).toBe(true);
});
````

**Create** `frontend/src/routes/editor/triggers/harness.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The Triggers panel on its own, for tests (4c-3b): a draft each write changes as the editor would (the graph's
// admission, a CSV declaration a save takes), the edits held beside it (ruling 113), every write kept with its mark and
// what it said, and a router for its links. The API is faked with the drawer harness's `fakeApi`. Imported by tests
// only: the build never reaches it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { act, render, screen } from "@testing-library/react";
import { useState } from "react";
import { admission } from "../../../lib/config";
import { csvProblem } from "../../../lib/csv";
import { applyAll, applyUnapplied, baseOf, isStale, lineageOf, TRIGGERS, unappliedId, within, type Unapplied, type UnappliedKind } from "../../../lib/unapplied";
import type { GraphDoc, Validation } from "../../../lib/workflows";
import type { PanelActions, Triggers } from "./context";
import { TriggersPanel } from "./TriggersPanel";

export type Write = { mark: string | undefined; said: string | null };

interface Options {
  doc?: GraphDoc;
  editable?: boolean;
  manage?: boolean;
  viewer?: boolean;
  activeNumber?: number | null;
  activeVersionId?: string | null;
  check?: Validation | null;
  focusAt?: { pointer: string; n: number } | null;
}

interface State {
  doc: GraphDoc;
  held: ReadonlyMap<string, Unapplied>;
  refusing: string | null;
  redraw: () => void;
}

function Harness({ options, state, writes }: { options: Options; state: State; writes: Write[] }) {
  const [, setVersion] = useState(0);
  state.redraw = () => setVersion((v) => v + 1);
  const id = (kind: UnappliedKind, pointer: string) => unappliedId(TRIGGERS, kind, pointer);
  const keep = (u: Unapplied) => {
    state.held = new Map(state.held).set(u.id, u);
    state.redraw();
  };
  const drop = (ids: string[]) => {
    const next = new Map(state.held);
    for (const each of ids) next.delete(each);
    state.held = next;
    state.redraw();
  };
  const write = (next: GraphDoc, release: string[] = []): string | null => {
    if (state.refusing !== null) return state.refusing;
    const refused = admission(next) ?? csvProblem(next.settings?.csv);
    if (refused !== null) return refused;
    state.doc = next;
    drop(release);
    return null;
  };
  const actions: PanelActions = {
    update: (make, said = null, mark) => {
      const next = make(state.doc);
      if (next === state.doc) return null;
      writes.push({ mark, said });
      return write(next);
    },
    held: (kind, pointer) => state.held.get(id(kind, pointer)),
    hold: (kind, pointer, holding) => {
      const was = state.held.get(id(kind, pointer));
      const u: Unapplied = { ...holding, id: id(kind, pointer), node: TRIGGERS, kind, pointer, base: "", lineage: [] };
      keep({ ...u, base: was?.base ?? baseOf(state.doc, u), lineage: was?.lineage ?? lineageOf(state.doc, u) });
    },
    release: (kind, pointer) => drop([id(kind, pointer)]),
    apply: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      if (!u) return null;
      if (kind === "name") {
        // What's typed inside the field is applied first, or the name waits (the editor's way too).
        const { doc, applied, left } = applyAll(state.doc, state.held.values(), () => undefined, within(TRIGGERS, pointer));
        for (const l of left) keep(l);
        if (left.length > 0) return left[0]!.why;
        return write(doc, applied.map((a) => a.id));
      }
      const result = applyUnapplied(state.doc, u, undefined);
      const why = "problem" in result ? result.problem : write(result.doc, [u.id]);
      if (why !== null) keep({ ...u, why });
      return why;
    },
    discard: (pointer) => drop([...state.held.values()].filter(within(TRIGGERS, pointer)).map((u) => u.id)),
    stale: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      return u !== undefined && isStale(state.doc, u);
    },
    rebase: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      if (u) keep({ ...u, base: baseOf(state.doc, u), lineage: lineageOf(state.doc, u), why: null });
    },
  };
  const editable = options.editable ?? true;
  const value: Triggers = {
    tenantId: "t1", workflowId: "w1", name: "AP report", doc: state.doc, editable, manage: options.manage ?? editable,
    viewer: options.viewer ?? false, activeNumber: options.activeNumber === undefined ? 3 : options.activeNumber,
    activeVersionId: options.activeVersionId === undefined ? "v3" : options.activeVersionId, check: options.check ?? null, actions,
  };  // prettier-ignore
  return <TriggersPanel value={value} focusAt={options.focusAt ?? null} onClose={() => undefined} />;
}

/** The Triggers panel over a draft, once drawn. `settings()` and `held()` read what the edits made of it; `replace` changes the
 * draft from outside, as an undo does; `refuse` makes every write answer `why`, or none with null. */
export async function showPanel(options: Options = {}) {
  const writes: Write[] = [];
  const state: State = { doc: options.doc ?? { graph_format: 1, nodes: [], edges: [] }, held: new Map(), refusing: null, redraw: () => undefined };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRootRoute();
  const page = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => (
      <QueryClientProvider client={client}>
        <Harness options={options} state={state} writes={writes} />
      </QueryClientProvider>
    ),
  });
  render(<RouterProvider router={createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ["/"] }) })} />);
  await screen.findByRole("heading", { name: "Triggers" }); // the router draws it a moment later
  return {
    writes,
    client,
    settings: () => state.doc.settings,
    held: () => [...state.held.values()],
    replace: (doc: GraphDoc) => {
      state.doc = doc;
      act(() => state.redraw());
    },
    refuse: (why: string | null) => {
      state.refusing = why;
    },
  };
}
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: FAIL: `Test Files  2 failed | 22 passed (24)`, `Tests  139 failed | 184 passed (323)`. Every test in
`Editor.test.tsx` fails the same way: Step 1's stand-in canvas reads the `start` prop, which the editor passes only from
Step 3, so each one shows `Cannot read properties of undefined (reading 'summary')` where the editor should be.
`InputSection.test.tsx` can't import `./TriggersPanel` through `harness.tsx`: it doesn't exist yet. The other files
pass.

- [ ] **Step 3: Write the code**

**In** `frontend/src/routes/editor/Canvas.tsx`, **replace**:

````tsx
  overview: boolean; // the minimap: off while a side panel narrows the canvas (the owner's ruling on milestone 3)
  onPlace: (at: { x: number; y: number }) => void; // the click, in the canvas's own coordinates
}

````

**with**:

````tsx
  overview: boolean; // the minimap: off while a side panel narrows the canvas (the owner's ruling on milestone 3)
  onPlace: (at: { x: number; y: number }) => void; // the click, in the canvas's own coordinates
  start: { summary: string; open: boolean; onOpen: () => void }; // the start card: what starts a run, and its panel
}

````

**In** `frontend/src/routes/editor/Canvas.tsx`, **replace**:

````tsx
  for (const e of drawableEdges(p.doc)) used.set(idKey(e.from.node), [...(used.get(idKey(e.from.node)) ?? []), portOf(e)]);
  const keyOf = new Map(nodesOf(p.doc).map((n) => [idKey(n.id), n.key]));
  const start: StartData = { empty: nodesOf(p.doc).length === 0, focusId: p.focusId, editable: p.editable, onItem: p.onItem };
  const nodes: Node[] = [
    { id: START, type: "start", position: startPosition(p.doc), draggable: false, selectable: false, data: start, ...SIZE },
````

**with**:

````tsx
  for (const e of drawableEdges(p.doc)) used.set(idKey(e.from.node), [...(used.get(idKey(e.from.node)) ?? []), portOf(e)]);
  const keyOf = new Map(nodesOf(p.doc).map((n) => [idKey(n.id), n.key]));
  const start: StartData = { empty: nodesOf(p.doc).length === 0, focusId: p.focusId, editable: p.editable, onItem: p.onItem, ...p.start };
  const nodes: Node[] = [
    { id: START, type: "start", position: startPosition(p.doc), draggable: false, selectable: false, data: start, ...SIZE },
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
import { ApiError, client, ok } from "../../lib/client";
import { admission, declassify, setConfig, setOptions, undeclassify, unlisted, unlistedNote, valueAt, type Changed } from "../../lib/config";
import { downloadJson, fileName } from "../../lib/download";
import { ConflictError, DraftSync, type SyncState } from "../../lib/draftSync";
````

**with**:

````tsx
import { ApiError, client, ok } from "../../lib/client";
import { admission, declassify, setConfig, setOptions, undeclassify, unlisted, unlistedNote, valueAt, type Changed } from "../../lib/config";
import { csvOf, csvProblem } from "../../lib/csv";
import { downloadJson, fileName } from "../../lib/download";
import { ConflictError, DraftSync, type SyncState } from "../../lib/draftSync";
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
import type { Path } from "../../lib/schemaForm";
import { useDocumentTitle } from "../../lib/title";
import {
````

**with**:

````tsx
import type { Path } from "../../lib/schemaForm";
import { useDocumentTitle } from "../../lib/title";
import { schedulesQuery, startSummary, workflowBindingsQuery } from "../../lib/triggers";
import {
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  STALE, applyAll, applyUnapplied, baseOf, droppedWhy, isStale, lineageOf, unappliedFile, unappliedId, within,
  type Unapplied, type UnappliedKind,
} from "../../lib/unapplied";  // prettier-ignore
````

**with**:

````tsx
  STALE, TRIGGERS, applyAll, applyUnapplied, baseOf, droppedWhy, isStale, lineageOf, unappliedFile, unappliedId, within,
  type Unapplied, type UnappliedKind,
} from "../../lib/unapplied";  // prettier-ignore
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
import { type Problems } from "./StepCard";
import { StepPicker, type PickMode } from "./StepPicker";
import { UnappliedPanel } from "./UnappliedPanel";
import { VersionsPanel } from "./VersionsPanel";
````

**with**:

````tsx
import { type Problems } from "./StepCard";
import { StepPicker, type PickMode } from "./StepPicker";
import { READ_ONLY, type PanelActions } from "./triggers/context";
import { TriggersPanel } from "./triggers/TriggersPanel";
import { UnappliedPanel } from "./UnappliedPanel";
import { VersionsPanel } from "./VersionsPanel";
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
type Opened = { workflow: WorkflowDetail; types: NodeType[]; role: string | null };

/** The editor's right column: a step's panel, the problems, or the versions (Task 15). */
type Side = { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" } | { kind: "unapplied" } | { kind: "declassify" } | null;
const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds
const NO_STEPS: ReadonlySet<string> = new Set();
````

**with**:

````tsx
type Opened = { workflow: WorkflowDetail; types: NodeType[]; role: string | null };

/** The editor's right column: a step's panel, the problems, the versions, the edits not applied, Declassify, or the
 * Triggers panel (4c-3b), at a place in it when "Go to it" sent it there. */
type Side =
  | { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" }
  | { kind: "unapplied" } | { kind: "declassify" } | { kind: "triggers"; at?: { pointer: string; n: number } } | null;  // prettier-ignore
const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds
const NO_STEPS: ReadonlySet<string> = new Set();
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  const [picker, setPicker] = useState<PickMode | null>(null);
  // Steps by identity (`idKey`, `findNode`): an item names a step's canonical id, the document its authored one.
  const keyOf = (id: string) => findNode(doc, id)?.key ?? "a step";

  const portMap = useMemo(
````

**with**:

````tsx
  const [picker, setPicker] = useState<PickMode | null>(null);
  // Steps by identity (`idKey`, `findNode`): an item names a step's canonical id, the document its authored one.
  const keyOf = (id: string) => (id === TRIGGERS ? "Triggers" : (findNode(doc, id)?.key ?? "a step"));

  const portMap = useMemo(
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  const jumps = useRef(0); // each "Go to" a field, so the same one twice still focuses it
  const [landing, setLanding] = useState<{
    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel" | "declassify" | "declassify-panel";
    n: number;
  } | null>(null);
````

**with**:

````tsx
  const jumps = useRef(0); // each "Go to" a field, so the same one twice still focuses it
  const [landing, setLanding] = useState<{
    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel" | "declassify" | "declassify-panel" | "triggers-panel";
    n: number;
  } | null>(null);
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
        declassify: () => usable(declassifyButton.current) ?? usable(versionsButton.current),
        "declassify-panel": () => document.getElementById("declassify-title") ?? usable(declassifyButton.current),
      }[landing.on]();
      target?.focus();
````

**with**:

````tsx
        declassify: () => usable(declassifyButton.current) ?? usable(versionsButton.current),
        "declassify-panel": () => document.getElementById("declassify-title") ?? usable(declassifyButton.current),
        "triggers-panel": () => document.getElementById("triggers-title"),
      }[landing.on]();
      target?.focus();
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  const qc = useQueryClient();
  const versions = useQuery(versionsQuery(tenantId, workflow.id));
  // The newest version's number: what a publish expects (4b ruling 17). Unknown while the list loads or refreshes.
  const latest = versions.isSuccess && !versions.isFetching ? (versions.data[0]?.number ?? 0) : null; // newest first
````

**with**:

````tsx
  const qc = useQueryClient();
  const versions = useQuery(versionsQuery(tenantId, workflow.id));
  const schedules = useQuery(schedulesQuery(tenantId, workflow.id));
  const bindings = useQuery(workflowBindingsQuery(tenantId, workflow.id));
  const summary = startSummary({
    csv: csvOf(shownDoc) !== null,
    schedules: schedules.data?.schedules.length ?? workflow.triggers.schedules,
    webhooks: bindings.data?.bindings.length ?? workflow.triggers.webhook_bindings,
  });
  // The newest version's number: what a publish expects (4b ruling 17). Unknown while the list loads or refreshes.
  const latest = versions.isSuccess && !versions.isFetching ? (versions.data[0]?.number ?? 0) : null; // newest first
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
    return qc.invalidateQueries({ queryKey: ["versions", tenantId, workflow.id] }).catch(() => undefined);
  };
````

**with**:

````tsx
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
    void qc.invalidateQueries({ queryKey: ["start-form", tenantId, workflow.id] }); // what a schedule's input is entered on
    return qc.invalidateQueries({ queryKey: ["versions", tenantId, workflow.id] }).catch(() => undefined);
  };
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
      },
      restructure: (pointer, then) => restructureStep(nodeId, pointer, then),
    };
  }
````

**with**:

````tsx
      },
      restructure: (pointer, then) => restructureStep(nodeId, pointer, then),
    };
  }

  /** What the Triggers panel may do to the draft (4c-3b): every write through `change`, so through 4b's guards; never one
   * a save would refuse (the graph's admission, its CSV declaration); what can't be written yet is held as a step's is
   * (ruling 113). */
  function triggersActions(): PanelActions {
    if (viewing || !canEdit(role)) return READ_ONLY;
    const id = (kind: UnappliedKind, pointer: string) => unappliedId(TRIGGERS, kind, pointer);
    return {
      update: (make, said = null, mark) => {
        const now = draftNow();
        const next = make(now);
        if (next === now) return null;
        const refused = csvProblem(next.settings?.csv);
        return refused ?? writeDraft({ doc: next, dropped: [] }, { mark, said });
      },
      held: (kind, pointer) => unapplied.get(id(kind, pointer)),
      hold: (kind, pointer, holding) => {
        const was = unappliedRef.current.get(id(kind, pointer));
        const u: Unapplied = { ...holding, id: id(kind, pointer), node: TRIGGERS, kind, pointer, base: "", lineage: [] };
        keep({ ...u, base: was?.base ?? baseOf(draftNow(), u), lineage: was?.lineage ?? lineageOf(draftNow(), u) });
      },
      release: (kind, pointer) => drop([id(kind, pointer)]),
      apply: (kind, pointer) => applyEdit(id(kind, pointer)),
      discard: (pointer) => drop([...unappliedRef.current.values()].filter(within(TRIGGERS, pointer)).map((u) => u.id)),
      stale: (kind, pointer) => {
        const u = unappliedRef.current.get(id(kind, pointer));
        return u !== undefined && isStale(draftNow(), u);
      },
      rebase: (kind, pointer) => {
        const u = unappliedRef.current.get(id(kind, pointer));
        if (u) keep({ ...u, base: baseOf(draftNow(), u), lineage: lineageOf(draftNow(), u), why: null });
      },
    };
  }
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
          onPlace={place}
          overview={side === null}
          />
        </div>
````

**with**:

````tsx
          onPlace={place}
          overview={side === null}
          start={{
            summary,
            open: side?.kind === "triggers",
            onOpen: () => setSide(side?.kind === "triggers" ? null : { kind: "triggers" }),
          }}
          />
        </div>
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
          <UnappliedPanel
            edits={[...unapplied.values()]}
            keyOf={(id) => findNode(doc, id)?.key ?? null}
            reason={(u) => (isStale(draftNow(), u) ? STALE : (u.why ?? "Still being typed."))}
````

**with**:

````tsx
          <UnappliedPanel
            edits={[...unapplied.values()]}
            keyOf={(id) => (id === TRIGGERS ? "Triggers" : (findNode(doc, id)?.key ?? null))}
            reason={(u) => (isStale(draftNow(), u) ? STALE : (u.why ?? "Still being typed."))}
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
            onGo={(u) => setSide({ kind: "step", node: u.node, field: { pointer: u.pointer, kind: u.kind, n: ++jumps.current } })}
            onDiscard={(u) => {
              drop([u.id]);
````

**with**:

````tsx
            onGo={(u) =>
              setSide(
                u.node === TRIGGERS ? { kind: "triggers", at: { pointer: u.pointer, n: ++jumps.current } }
                : { kind: "step", node: u.node, field: { pointer: u.pointer, kind: u.kind, n: ++jumps.current } },
              )
            }
            onDiscard={(u) => {
              drop([u.id]);
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
              setSide(null);
              land("declassify");
            }}
          />
````

**with**:

````tsx
              setSide(null);
              land("declassify");
            }}
          />
        )}
        {side?.kind === "triggers" && (
          <TriggersPanel
            value={{
              tenantId, workflowId: workflow.id, name: workflow.name, doc: shownDoc, editable, viewer: !canEdit(role),
              manage: canEdit(role) && viewing === null,
              // The active version as the editor last knew it; when an answer was lost, as the versions say.
              activeNumber: typeof sync.activeNumber === "number" ? sync.activeNumber : (versions.data?.find((v) => v.active)?.number ?? null),
              activeVersionId: versions.data?.find((v) => v.active)?.id ?? workflow.active_version_id,
              check: viewing ? null : trusted, actions: triggersActions(),
            }}
            focusAt={side.at ?? null}
            onClose={() => {
              setSide(null);
              focus(START);
            }}
          />
````

**In** `frontend/src/routes/editor/StartCard.tsx`, **replace**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The start card (4b ruling 2): not a graph node. It stands for whatever starts a run; its edges reach every entry
// step, and, before any step exists, its "+" adds the first one.
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { START } from "../../lib/graph";
````

**with**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The start card (4b ruling 2): not a graph node. It stands for whatever starts a run; its edges reach every entry
// step. It opens the Triggers panel, which says what starts a run (4c-3b), and sums it up: "By hand · 2 schedules".
// Before any step exists, its "+" adds the first one; `A` on the card, or the toolbar's Add step with it focused, adds
// one beside the others, at full size (WCAG 2.5.8).
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { START } from "../../lib/graph";
````

**In** `frontend/src/routes/editor/StartCard.tsx`, **replace**:

````tsx
import { item, type ItemAction } from "./items";

````

**with**:

````tsx
import { startLabel } from "../../lib/triggers";
import { item, type ItemAction } from "./items";

````

**In** `frontend/src/routes/editor/StartCard.tsx`, **replace**:

````tsx
export type StartData = { empty: boolean; focusId: string; editable: boolean; onItem: (action: ItemAction) => void };

export function StartNode({ data }: NodeProps<Node<StartData, "start">>) {
````

**with**:

````tsx
export type StartData = {
  empty: boolean;
  focusId: string;
  editable: boolean;
  onItem: (action: ItemAction) => void;
  summary: string; // what starts a run, in words
  open: boolean; // the Triggers panel is open
  onOpen: () => void;
};

export function StartNode({ data }: NodeProps<Node<StartData, "start">>) {
````

**In** `frontend/src/routes/editor/StartCard.tsx`, **replace**:

````tsx
        data-item={item.start}
        tabIndex={data.focusId === item.start ? 0 : -1}
        aria-label={data.editable ? "Start, where every run begins. Add a step that runs first" : "Start, where every run begins"}
        onClick={() => data.editable && data.onItem({ kind: "after", from: null })}
        className="pointer-events-auto flex h-[64px] w-[260px] flex-col justify-center rounded-lg border border-dashed border-line-strong bg-surface px-3.5 text-left"
      >
````

**with**:

````tsx
        data-item={item.start}
        tabIndex={data.focusId === item.start ? 0 : -1}
        aria-label={startLabel(data.summary)}
        aria-expanded={data.open}
        onClick={data.onOpen}
        className="pointer-events-auto flex h-[64px] w-[260px] flex-col justify-center rounded-lg border border-dashed border-line-strong bg-surface px-3.5 text-left"
      >
````

**In** `frontend/src/routes/editor/StartCard.tsx`, **replace**:

````tsx
        <span className="truncate text-body font-semibold">Start</span>
        <span className="truncate text-small text-muted">By hand, a schedule or a webhook</span>
      </button>
      <Handle type="source" id="out" position={Position.Bottom} isConnectable={false} />
````

**with**:

````tsx
        <span className="truncate text-body font-semibold">Start</span>
        <span className="truncate text-small text-muted">{data.summary}</span>
      </button>
      <Handle type="source" id="out" position={Position.Bottom} isConnectable={false} />
````

**Create** `frontend/src/routes/editor/triggers/FieldEditor.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// A field of the input, edited in its row (4c-3b; the InputFields board): its name, label, type, description, whether
// it's required or sensitive, its default and a Choice's values. Each control writes as it changes, a control's edits
// one undo step (ruling 8). A name is held while it's typed and applied when focus leaves it or Enter is pressed; a
// default that doesn't parse is held (ruling 113), and one typed over a default that has since changed is written only
// by Apply here. A sensitive field has no default and no Choice: either would be written into the workflow, which the
// server refuses (§3.8).
import { useEffect, useRef } from "react";
import { Button } from "../../../components/Button";
import { Field, Select, controlClass } from "../../../components/Field";
import { FIELD_TYPES, fieldPointer, inputOf, removeField, setField, setSettings, type FieldType, type InputField } from "../../../lib/input";
import { parseNumber } from "../../../lib/unapplied";
import { FieldFrame } from "../drawer/FieldFrame";
import { useText } from "../drawer/scalars";
import { useTriggers } from "./context";
import { Check, Problems, StaleEdit, Values, heldWhy, problemsAt, writeTyped } from "./parts";

const SENSITIVE = "Kept apart from run history. A sensitive field has no default: it would be written into the workflow.";
const NO_CHOICE = "A sensitive field can't be a Choice: its values would be written into the workflow.";

/** A whole number's or a number's default: held while it doesn't parse, written once it does. */
function NumberDefault({ field, pointer, disabled }: { field: InputField; pointer: string; disabled: boolean }) {
  const { actions } = useTriggers();
  const at = `${pointer}/default`;
  const whole = field.type === "whole";
  const held = actions.held("number", at);
  const show = (v: unknown) => (typeof v === "number" ? String(v) : "");
  const [text, setText] = useText(
    field.default,
    show,
    (t, v) => {
      const parsed = parseNumber(t, whole);
      return "value" in parsed && parsed.value === v;
    },
    held?.text,
  );
  return (
    <div className="flex flex-col gap-1.5">
      <FieldFrame label="Default" required={false} hint={null} local={heldWhy(actions, "number", at)} problems={[]}>
        {({ id, describedBy, invalid }) => (
          <input
            id={id} type="text" inputMode="decimal" value={held?.text ?? text} disabled={disabled} spellCheck={false}
            aria-describedby={describedBy} aria-invalid={invalid}
            onChange={(e) => {
              const t = e.target.value;
              setText(t);
              const parsed = parseNumber(t, whole);
              const holding = { path: ["input_schema", "properties", field.name, "default"], label: `${field.name}'s default`, text: t, whole };
              writeTyped(actions, "number", at, holding, "problem" in parsed ? parsed.problem : null, () =>
                "problem" in parsed ? null : actions.update((d) => setSettings(d, { input_schema: setField(inputOf(d), field.name, { default: parsed.value }) }), null, at),
              );
            }}
            className={controlClass(invalid)}
          />
        )}
      </FieldFrame>
      <StaleEdit kind="number" at={at} onDiscard={() => setText(show(field.default))} />
    </div>
  );  // prettier-ignore
}

function Default({ field, pointer, disabled, set }: {
  field: InputField; pointer: string; disabled: boolean; set: (patch: Partial<InputField>, key: string) => void;
}) {  // prettier-ignore
  if (field.sensitive) return <Field label="Default" value="" disabled />;
  if (field.type === "whole" || field.type === "number") return <NumberDefault field={field} pointer={pointer} disabled={disabled} />;
  if (field.type === "yesno" || field.type === "choice") {
    const options = field.type === "yesno" ? [["true", "Yes"], ["false", "No"]] : field.values.map((v) => [JSON.stringify(v), v]);
    return (
      <Select
        label="Default" value={"default" in field ? JSON.stringify(field.default) : ""} disabled={disabled}
        onChange={(e) => set({ default: e.target.value === "" ? undefined : (JSON.parse(e.target.value) as unknown) }, "default")}
      >
        <option value="">None</option>
        {options.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </Select>
    );  // prettier-ignore
  }
  return (
    <Field
      label="Default" value={typeof field.default === "string" ? field.default : ""} disabled={disabled}
      placeholder={field.type === "datetime" ? "2026-10-11T08:00:00Z" : undefined}
      onChange={(e) => set({ default: e.target.value === "" ? undefined : e.target.value }, "default")}
    />
  );  // prettier-ignore
}

export function FieldEditor({ field, onClose, onRenamed }: { field: InputField; onClose: () => void; onRenamed: (to: string) => void }) {
  const t = useTriggers();
  const { actions } = t;
  const disabled = !t.editable;
  const pointer = fieldPointer(field.name);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.querySelector("input")?.focus(), []);
  const set = (patch: Partial<InputField>, key: string) =>
    actions.update((d) => setSettings(d, { input_schema: setField(inputOf(d), field.name, patch) }), null, `${pointer}/${key}`);
  const name = actions.held("name", pointer);
  /** The name typed, applied: whether the field may close (a refused one stays, with why). */
  const applyName = (): boolean => {
    if (!name) return true;
    const to = name.text.trim();
    if (to === field.name) {
      actions.release("name", pointer);
      return true;
    }
    if (actions.apply("name", pointer) !== null) return false;
    onRenamed(to);
    return true;
  };
  return (
    <div
      ref={box}
      role="group"
      aria-label={`The field ${field.name}`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // closes the field, not the panel
          if (applyName()) onClose();
        }
      }}
      className="flex flex-col gap-3 rounded-lg border border-line-strong p-3"
    >
      <Field
        label="Name" value={name?.text ?? field.name} disabled={disabled} spellCheck={false} autoCapitalize="off"
        hint={`Steps read it as trigger.${field.name}. Lowercase letters, digits and _.`} error={heldWhy(actions, "name", pointer) ?? undefined}
        onChange={(e) => {
          const text = e.target.value;
          if (text === field.name) actions.release("name", pointer);
          else actions.hold("name", pointer, { path: ["input_schema", "properties"], label: `${field.name}'s name`, text, why: null, from: field.name });
        }}
        onBlur={() => void applyName()}
        onKeyDown={(e) => {
          if (e.key === "Enter") applyName();
        }}
      />
      <StaleEdit
        kind="name" at={pointer}
        onApply={() => {
          actions.rebase("name", pointer);
          applyName();
        }}
      />
      <Field label="Label" value={field.label} disabled={disabled} onChange={(e) => set({ label: e.target.value }, "title")} />
      <Select
        label="Type" value={field.type} disabled={disabled} hint={field.sensitive ? NO_CHOICE : undefined}
        onChange={(e) => set({ type: e.target.value as FieldType }, "type")}
      >
        {FIELD_TYPES.map((x) => <option key={x.value} value={x.value} disabled={x.value === "choice" && field.sensitive}>{x.label}</option>)}
      </Select>
      <Field label="Description (optional)" value={field.description} disabled={disabled} onChange={(e) => set({ description: e.target.value }, "description")} />
      <Check label="Required" checked={field.required} disabled={disabled} onChange={(required) => set({ required }, "required")} />
      <Check
        label="Sensitive" checked={field.sensitive} disabled={disabled || field.type === "choice"} hint={field.type === "choice" ? NO_CHOICE : SENSITIVE}
        onChange={(sensitive) => set({ sensitive }, "x-sensitive")}
      />
      {field.type === "choice" && (
        <Values
          label={`The field ${field.name}'s values`} values={field.values} disabled={disabled}
          hint="A run's value must be one of these, as written. Up to 200."
          onChange={(values) => set({ values }, "enum")}
        />
      )}
      <Default field={field} pointer={pointer} disabled={disabled} set={set} />
      <Problems problems={problemsAt(t.check, pointer)} />
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="primary" onClick={() => applyName() && onClose()}>Done</Button>
        {!disabled && (
          <Button
            size="sm" variant="danger-outline"
            onClick={() => {
              actions.discard(pointer);
              if (actions.update((d) => setSettings(d, { input_schema: removeField(inputOf(d), field.name) }), `Removed the field ${field.name}.`) === null) onClose();
            }}
          >
            Remove field
          </Button>
        )}
      </div>
    </div>
  );  // prettier-ignore
}
````

**Create** `frontend/src/routes/editor/triggers/InputJson.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The input as JSON (4c-3b; the InputEdit board): the input schema and the CSV file as one text, saved with the draft
// as it's typed whenever it's JSON a save takes; text that isn't stays held, unsaved, with the line where it breaks
// (ruling 113), and text typed over an input that has since changed is written only by Apply here. The server's
// problems show with their lines. Undo works as elsewhere. It takes focus when it opens.
import { useEffect, useId, useMemo, useRef } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { csvOf } from "../../../lib/csv";
import { inputOf, sameSchema, setSettings } from "../../../lib/input";
import { inputText, lineOf, pointerWords, readInput } from "../../../lib/inputJson";
import { STALE } from "../../../lib/unapplied";
import { useText } from "../drawer/scalars";
import { useTriggers } from "./context";
import { StaleEdit, heldWhy, writeTyped } from "./parts";

/** Where the JSON text's held edit is kept, and what "Go to it" names. */
export const JSON_AT = "/settings/input";

export function InputJson({ onBack }: { onBack: () => void }) {
  const t = useTriggers();
  const { actions, doc } = t;
  const id = useId();
  const area = useRef<HTMLTextAreaElement>(null);
  useEffect(() => area.current?.focus(), []);
  const held = actions.held("json", JSON_AT);
  const why = heldWhy(actions, "json", JSON_AT);
  const value = useMemo(() => ({ input_schema: inputOf(doc), csv: csvOf(doc) ?? undefined }), [doc]); // a new one only when the draft changes
  const [text, setText] = useText(
    value,
    () => inputText(doc),
    (typed, v) => {
      const read = readInput(typed);
      return "value" in read && sameSchema(read.value, v);
    },
    held?.text,
  );
  const shown = held?.text ?? text;
  const problems = (t.check?.diagnostics ?? []).filter((d) => d.field !== null && /^\/settings\/(input_schema|csv)(\/|$)/.test(d.field));
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor={id} className="text-small font-semibold">The input&apos;s schema and CSV columns</label>
      <textarea
        ref={area} id={id} value={shown} readOnly={!t.editable} rows={16} spellCheck={false} aria-describedby={`${id}-notes`}
        aria-invalid={why ? true : undefined}
        onChange={(e) => {
          const typed = e.target.value;
          setText(typed);
          const read = readInput(typed);
          const problem = "problem" in read ? (read.line === null ? read.problem : `Line ${read.line}: ${read.problem}`) : null;
          writeTyped(actions, "json", JSON_AT, { path: [], label: "The input as JSON", text: typed }, problem, () =>
            "problem" in read ? null : actions.update((d) => setSettings(d, { input_schema: read.value.input_schema, csv: read.value.csv }), null, JSON_AT),
          );  // prettier-ignore
        }}
        className={`${controlClass(!!why)} min-h-64 py-2 font-mono text-small`}
      />
      <StaleEdit kind="json" at={JSON_AT} onDiscard={() => setText(inputText(doc))} />
      <div id={`${id}-notes`} className="flex flex-col gap-1">
        {why && <p className="text-small text-danger">{why}</p>}
        {!held &&
          problems.map((d, i) => {
            const line = d.field ? lineOf(shown, d.field) : null;
            return (
              <p key={`${d.code}:${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>
                {line !== null ? `Line ${line}, ` : ""}<code className="font-mono">{pointerWords(d.field ?? "")}</code>: {d.message}
              </p>
            );
          })}
        <p className="text-small text-muted">
          {t.editable
            ? "Saved with the draft as you type, when it's JSON; text that isn't stays here, unsaved, with the line where it breaks. Undo works as elsewhere."
            : "Read only."}
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={onBack}>Back to the fields</Button>
        {held && t.editable && why !== STALE && (
          <Button
            size="sm" variant="danger-outline"
            onClick={() => {
              actions.discard(JSON_AT);
              setText(inputText(doc)); // the draft's input again, as it is
            }}
          >
            Discard what isn&apos;t saved
          </Button>
        )}
      </div>
      <p className="text-small text-muted">A field the list can&apos;t show stays read only there.</p>
    </div>
  );  // prettier-ignore
}
````

**Create** `frontend/src/routes/editor/triggers/InputSection.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The input (4c-3b; the InputFields and InputEdit boards): what every trigger starts a run with, and, by hand, the
// run's form. Saved with the draft, used once published. As form fields, or as JSON (Task 8 adds a Mist event's shape
// and a CSV file). Focus goes back to what opened a part once it closes (WCAG 2.4.3).
import { useEffect, useState } from "react";
import { Button } from "../../../components/Button";
import { addField, fieldPointer, inputOf, inputRows, setSettings } from "../../../lib/input";
import { useTriggers } from "./context";
import { FieldEditor } from "./FieldEditor";
import { InputJson, JSON_AT } from "./InputJson";
import { Problems, Section, problemsAt, useFocusBack } from "./parts";

const TYPE_WORDS: Record<string, string> = { text: "Text", whole: "Whole number", number: "Number", yesno: "Yes or no", choice: "Choice", datetime: "Date and time" };

type Mode = "fields" | "json";

/** Where "Go to it" in the edits not applied lands: JSON, or a field. */
export type FocusAt = { pointer: string; n: number } | null;

export function InputSection({ focusAt }: { focusAt: FocusAt }) {
  const t = useTriggers();
  const { actions, doc } = t;
  const schema = inputOf(doc);
  const [mode, setMode] = useState<Mode>(() => (actions.held("json", JSON_AT) ? "json" : "fields"));
  const [editing, setEditing] = useState<string | null>(null);
  // The field being edited keeps its row through a rename, so its editor stays as it is: focus where it went, a click in
  // it landing (the review of revision 2).
  const [kept, setKept] = useState<{ name: string; key: string } | null>(null);
  const keyOf = (name: string) => (kept !== null && kept.name === name && editing === name ? kept.key : name);
  const { box, back } = useFocusBack<HTMLElement>();
  useEffect(() => {
    if (!focusAt) return;
    if (focusAt.pointer === JSON_AT) return setMode("json");
    const m = /^\/settings\/input_schema\/properties\/([^/]+)/.exec(focusAt.pointer);
    if (m) {
      setMode("fields");
      setEditing(m[1]!.replaceAll("~1", "/").replaceAll("~0", "~"));
    }
  }, [focusAt]);
  const rows = inputRows(schema);
  const heldJson = actions.held("json", JSON_AT);
  const add = () => {
    const made = addField(inputOf(doc));
    if (actions.update((d) => setSettings(d, { input_schema: addField(inputOf(d)).schema }), `Added the field ${made.name}.`) === null) setEditing(made.name);
  };
  return (
    <Section id="triggers-input" title="Input" note="Saved with the draft · used once published" box={box}>
      {mode !== "json" && <p className="text-small text-muted">Every trigger starts a run with this input. By hand, it&apos;s the run&apos;s form.</p>}
      <Problems problems={problemsAt(t.check, "/settings/input_schema", true)} />
      {heldJson && mode !== "json" && (
        <p className="text-small text-warn-ink">JSON typed here isn&apos;t saved yet: Edit as JSON shows it, with why.</p>
      )}
      {mode === "json" ? (
        <InputJson
          onBack={() => {
            setMode("fields");
            back("json");
          }}
        />
      ) : (
        <>
          {rows.length === 0 && <p className="text-small text-muted">No fields: a run starts with an empty input.</p>}
          <ul className="flex flex-col">
            {rows.map((r) => {
              const name = r.kind === "field" ? r.field.name : r.name;
              const pointer = fieldPointer(name);
              return (
                <li key={keyOf(name)} className="flex flex-col gap-2 border-t border-line py-2.5 first:border-t-0">
                  {r.kind === "field" && editing === name ? (
                    <FieldEditor
                      field={r.field}
                      onRenamed={(to) => {
                        setKept({ name: to, key: keyOf(name) });
                        setEditing(to);
                      }}
                      onClose={() => {
                        setEditing(null);
                        back(`field:${name}`, "add");
                      }}
                    />
                  ) : (
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="min-w-0 text-small">
                        <span className="font-mono">{name}</span>
                        {r.kind === "field" ? (
                          <>
                            {r.field.label && ` · ${r.field.label}`} · {TYPE_WORDS[r.field.type]}
                            {r.field.required ? " · required" : " · optional"}
                            {r.field.sensitive && " · sensitive"}
                          </>
                        ) : (
                          <span className="text-muted"> · {r.what}{r.required ? " · required" : ""} · read only here</span>
                        )}
                      </span>
                      {r.kind === "field" && t.editable && (
                        <Button size="sm" aria-label={`Edit ${name}`} data-back={`field:${name}`} onClick={() => setEditing(name)}>Edit</Button>
                      )}
                    </div>
                  )}
                  {editing !== name && <Problems problems={problemsAt(t.check, pointer)} />}
                  {actions.held("name", pointer) && editing !== name && (
                    <p className="text-small text-warn-ink">A new name typed for it isn&apos;t applied: Edit shows it, with why.</p>
                  )}
                </li>
              );
            })}
          </ul>
          {rows.some((r) => r.kind === "other") && (
            <p className="text-small text-muted">A field the list can&apos;t show (a list, an object of fields) appears read only: Edit as JSON changes it.</p>
          )}
          {t.editable && (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" data-back="add" onClick={add}>＋ Field</Button>
              <Button size="sm" data-back="json" onClick={() => setMode("json")}>Edit as JSON</Button>
            </div>
          )}
          {!t.editable && <Button size="sm" className="self-start" data-back="json" onClick={() => setMode("json")}>Show as JSON</Button>}
        </>
      )}
    </Section>
  );  // prettier-ignore
}
````

**Create** `frontend/src/routes/editor/triggers/TriggersPanel.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The Triggers panel (4c-3b; the mockups' Main, ReadOnly and Narrow boards): what starts the workflow, opened from the
// start card. Its input is the draft's, saved with it and used once published (Task 9 adds its live schedules, Task 11
// its webhooks). A viewer or an operator sees it all, read only.
import { useEffect, useRef } from "react";
import { Button } from "../../../components/Button";
import { SIDE } from "../side";
import { TriggersContext, type Triggers } from "./context";
import { InputSection, type FocusAt } from "./InputSection";

export function TriggersPanel({ value, focusAt, onClose }: { value: Triggers; focusAt: FocusAt; onClose: () => void }) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (!focusAt) heading.current?.focus();
  }, [focusAt]);
  return (
    <TriggersContext.Provider value={value}>
      <aside
        aria-labelledby="triggers-title"
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onClose();
          }
        }}
        className={`${SIDE} gap-6`}
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col">
            <h2 id="triggers-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold outline-none">Triggers</h2>
            <span className="truncate text-small text-muted">How {value.name} starts</span>
          </div>
          <Button size="sm" onClick={onClose}>Close</Button>
        </div>
        {value.viewer && <p className="text-small text-muted">You can see this workflow&apos;s triggers; changing them needs the editor role.</p>}
        <InputSection focusAt={focusAt} />
      </aside>
    </TriggersContext.Provider>
  );
}
````

**Create** `frontend/src/routes/editor/triggers/context.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// What the Triggers panel's parts share (4c-3b): the draft (or a version on view) and what may change. The input is the
// draft's, written through the editor's `change`, so it gets undo, saving, conflicts and the leave guard as a step's
// fields do; what's typed but can't be written yet is held by the editor (ruling 113). Schedules and webhooks are live
// rows the API writes at once, outside undo: `manage` is whether this person may (trigger.manage, editor and above).
import { createContext, useContext } from "react";
import type { Holding, Unapplied, UnappliedKind } from "../../../lib/unapplied";
import type { GraphDoc, Validation } from "../../../lib/workflows";

export interface PanelActions {
  /** Writes what `make` makes of the editor's latest draft (edits sharing a `mark` are one undo step); why it wasn't
   * written, or null. */
  update: (make: (draft: GraphDoc) => GraphDoc, said?: string | null, mark?: string) => string | null;
  held: (kind: UnappliedKind, pointer: string) => Unapplied | undefined;
  hold: (kind: UnappliedKind, pointer: string, holding: Holding) => void;
  release: (kind: UnappliedKind, pointer: string) => void;
  /** Applies what's held at `pointer` now: why it stays held, or null. */
  apply: (kind: UnappliedKind, pointer: string) => string | null;
  /** Whether what's held at `pointer` was typed over what has since changed (an undo, another edit): it's then never
   * written as it's typed, only by Apply here (ruling 18; the review of revision 1). */
  stale: (kind: UnappliedKind, pointer: string) => boolean;
  /** Takes what's at `pointer` now as what the held edit is typed over: Apply here, before it's applied. */
  rebase: (kind: UnappliedKind, pointer: string) => void;
  /** Discards what's held at `pointer` and below. */
  discard: (pointer: string) => void;
}

export interface Triggers {
  tenantId: string;
  workflowId: string;
  name: string;
  doc: GraphDoc; // the draft, or the version on view
  editable: boolean; // the draft's input can change now
  manage: boolean; // schedules and webhooks can change: the role may, and no version is on view
  viewer: boolean; // the role can't change triggers at all: said once, at the top
  activeNumber: number | null;
  activeVersionId: string | null;
  check: Validation | null; // the current check of the saved draft, or null: its problems show at their fields
  actions: PanelActions;
}

const CANT = "Not written: the draft can't be changed now.";

/** A version's view, or a role that can't edit: nothing is written, nothing held. */
export const READ_ONLY: PanelActions = {
  update: () => CANT,
  held: () => undefined,
  hold: () => undefined,
  release: () => undefined,
  apply: () => CANT,
  discard: () => undefined,
  stale: () => false,
  rebase: () => undefined,
};

export const TriggersContext = createContext<Triggers | null>(null);

export function useTriggers(): Triggers {
  const t = useContext(TriggersContext);
  if (!t) throw new Error("useTriggers is used outside the Triggers panel");
  return t;
}
````

**Create** `frontend/src/routes/editor/triggers/parts.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The Triggers panel's shared parts (4c-3b): a section with its heading and what it is ("Live · on version 3"), the
// current check's problems at a place in the settings, a Choice's values, text typed and held as a step's is, and focus
// given back once what held it is gone.
import { useId, useRef, type ReactNode, type Ref } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { STALE, type Holding, type UnappliedKind } from "../../../lib/unapplied";
import type { Diagnostic, Validation } from "../../../lib/workflows";
import { useTriggers, type PanelActions } from "./context";

/** A section of the panel; its heading takes focus when given a ref (where focus lands once what held it is gone), and
 * `box` is the section itself (where `useFocusBack` looks). */
export function Section({ id, title, note, heading, box, children }: {
  id: string; title: string; note: string; heading?: Ref<HTMLHeadingElement>; box?: Ref<HTMLElement>; children: ReactNode;
}) {  // prettier-ignore
  return (
    <section ref={box} aria-labelledby={id} className="flex flex-col gap-3 border-t border-line pt-4 first:border-t-0 first:pt-0">
      <div className="flex flex-col">
        <h3 id={id} ref={heading} tabIndex={heading ? -1 : undefined} className="text-body font-semibold outline-none">{title}</h3>
        <span className="text-small text-muted">{note}</span>
      </div>
      {children}
    </section>
  );
}

/** The current check's problems at `pointer` and below; `exact` for those at it alone. */
export function problemsAt(check: Validation | null, pointer: string, exact = false): Diagnostic[] {
  return (check?.diagnostics ?? []).filter((d) => d.field !== null && (d.field === pointer || (!exact && d.field.startsWith(`${pointer}/`))));
}

/** Problems shown under what they're about, in the server's words (D18). */
export function Problems({ problems }: { problems: Diagnostic[] }) {
  if (problems.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1">
      {problems.map((d, i) => (
        <li key={`${d.code}:${d.field}:${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>
          {d.message}
          {d.fix && <span className="block text-muted">{d.fix}</span>}
        </li>
      ))}
    </ul>
  );
}

/** A checkbox with its label, and a hint the box is described by. */
export function Check({ label, checked, disabled, hint, onChange }: {
  label: string; checked: boolean; disabled: boolean; hint?: string; onChange: (checked: boolean) => void;
}) {  // prettier-ignore
  const id = useId();
  return (
    <div className="flex flex-col gap-0.5">
      <label htmlFor={id} className="flex min-h-6 items-center gap-2 text-small">
        <input
          id={id} type="checkbox" checked={checked} disabled={disabled} aria-describedby={hint ? `${id}-hint` : undefined}
          onChange={(e) => onChange(e.target.checked)} className="size-[16px] accent-accent"
        />
        {label}
      </label>
      {hint && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
    </div>
  );  // prettier-ignore
}

/** A Choice's values, each its own text, removed by its ×; written as each changes. */
export function Values({ label, values, disabled, hint, onChange }: {
  label: string; values: string[]; disabled: boolean; hint: string; onChange: (values: string[]) => void;
}) {  // prettier-ignore
  return (
    <fieldset aria-label={label} className="flex min-w-0 flex-col gap-2">
      <legend className="text-small font-semibold">Values</legend>
      {values.map((v, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            aria-label={`Value ${i + 1}`} value={v} disabled={disabled} maxLength={200}
            onChange={(e) => onChange(values.map((x, j) => (j === i ? e.target.value : x)))}
            className={controlClass(false)}
          />
          <Button size="sm" aria-label={`Remove ${v === "" ? `value ${i + 1}` : v}`} disabled={disabled} onClick={() => onChange(values.filter((_, j) => j !== i))}>
            ×
          </Button>
        </div>
      ))}
      <Button size="sm" className="self-start" disabled={disabled || values.length >= 200} onClick={() => onChange([...values, ""])}>＋ Value</Button>
      <p className="text-small text-muted">{hint}</p>
    </fieldset>
  );  // prettier-ignore
}

/** Text typed in the panel, as a step's is (ruling 18): written when it can be (`write`, once it has no `problem`), held
 * with why when it can't. Typed over what has since changed (an undo, another edit), it's never written as it's typed,
 * only by Apply here: it stays held, with why (the review of revision 1). */
export function writeTyped(
  actions: PanelActions, kind: UnappliedKind, at: string, holding: Omit<Holding, "why">, problem: string | null, write: () => string | null,
): void {  // prettier-ignore
  const why = problem ?? (actions.stale(kind, at) ? STALE : write());
  if (why === null) actions.release(kind, at);
  else actions.hold(kind, at, { ...holding, why });
}

/** Why what's held at `at` isn't written, as its control says it: typed over what has since changed, or its own why. */
export function heldWhy(actions: PanelActions, kind: UnappliedKind, at: string): string | null {
  const held = actions.held(kind, at);
  return held === undefined ? null : actions.stale(kind, at) ? STALE : held.why;
}

/** A held edit typed over what has since changed: Apply here or Discard (ruling 18), then focus back on its control, the
 * first one beside it (WCAG 2.4.3). `onApply` applies it its own way; `onDiscard` puts the control's own text back. */
export function StaleEdit({ kind, at, onApply, onDiscard }: { kind: UnappliedKind; at: string; onApply?: () => void; onDiscard?: () => void }) {
  const { actions, editable } = useTriggers();
  const box = useRef<HTMLDivElement>(null);
  const held = actions.held(kind, at);
  if (!editable || held === undefined || !actions.stale(kind, at)) return null;
  const refocus = () => {
    const control = box.current?.parentElement?.querySelector<HTMLElement>("input, textarea");
    requestAnimationFrame(() => control?.focus());
  };
  return (
    <div ref={box} className="flex flex-wrap gap-2">
      <Button
        size="sm" aria-label={`Apply here: ${held.label}`}
        onClick={() => {
          if (onApply) onApply();
          else {
            actions.rebase(kind, at);
            actions.apply(kind, at);
          }
          refocus();
        }}
      >
        Apply here
      </Button>
      <Button
        size="sm" aria-label={`Discard the edit to ${held.label}`}
        onClick={() => {
          actions.release(kind, at);
          onDiscard?.();
          refocus();
        }}
      >
        Discard
      </Button>
    </div>
  );  // prettier-ignore
}

/** Gives focus back once what held it is gone (WCAG 2.4.3; the review of revision 1): after the next frame, to the first
 * element in `box` marked `data-back` with one of `keys`, tried in their order. */
export function useFocusBack<T extends HTMLElement>() {
  const box = useRef<T>(null);
  const back = (...keys: string[]) =>
    requestAnimationFrame(() => {
      const marked = [...(box.current?.querySelectorAll<HTMLElement>("[data-back]") ?? [])];
      for (const key of keys) {
        const to = marked.find((el) => el.dataset.back === key);
        if (to) return to.focus();
      }
    });
  return { box, back };
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: PASS: `Test Files  24 passed (24)`, `Tests  336 passed (336)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/Canvas.tsx \
  frontend/src/routes/editor/Editor.test.tsx \
  frontend/src/routes/editor/Editor.tsx \
  frontend/src/routes/editor/StartCard.tsx \
  frontend/src/routes/editor/triggers/FieldEditor.tsx \
  frontend/src/routes/editor/triggers/InputJson.tsx \
  frontend/src/routes/editor/triggers/InputSection.test.tsx \
  frontend/src/routes/editor/triggers/InputSection.tsx \
  frontend/src/routes/editor/triggers/TriggersPanel.tsx \
  frontend/src/routes/editor/triggers/context.ts \
  frontend/src/routes/editor/triggers/harness.tsx \
  frontend/src/routes/editor/triggers/parts.tsx
git commit -m "feat(editor): the start card opens the Triggers panel: the input as fields and as JSON (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: A Mist event's shape, and the CSV file

"Use a Mist event…" copies a topic's shape into the draft, shown read only while the input is that shape (ruling 6); "＋
CSV file" declares a file of one column, its columns edited in their rows with the file's limits, a required column's
default offering its two fixes (ruling 7). A column's text typed where the file has since changed is written only by
Apply here, whatever the column's type now, and focus goes back to what opened a part (the reviews of revisions 1 and
2).

**Files:**
- Create: `frontend/src/routes/editor/triggers/CsvSection.tsx`
- Modify: `frontend/src/routes/editor/triggers/InputSection.test.tsx`
- Modify: `frontend/src/routes/editor/triggers/InputSection.tsx`
- Create: `frontend/src/routes/editor/triggers/MistEvent.tsx`

**Interfaces:**
- Consumes: Tasks 3, 4 and 7 (`writeTyped`, `heldWhy`, `StaleEdit`, `useFocusBack`).
- Produces: `MistPicker`, `MistShape({ …, onFields })` (`triggers/MistEvent.tsx`); `CsvSection({ csv, focusAt, back })`
  (`triggers/CsvSection.tsx`).

- [ ] **Step 1: Write the failing tests**

**In** `frontend/src/routes/editor/triggers/InputSection.test.tsx`, **replace**:

````tsx
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MIST } from "../../../test/triggers";
import { STALE } from "../../../lib/unapplied";
import type { Diagnostic, GraphDoc, Validation } from "../../../lib/workflows";
````

**with**:

````tsx
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DEVICE_EVENTS, MIST } from "../../../test/triggers";
import { STALE } from "../../../lib/unapplied";
import type { Diagnostic, GraphDoc, Validation } from "../../../lib/workflows";
````

**In** `frontend/src/routes/editor/triggers/InputSection.test.tsx`, **replace**:

````tsx
});

describe("the input as JSON", () => {
  it("writes text that reads, holds text that doesn't with its line, and shows the server's problems at theirs", async () => {
````

**with**:

````tsx
});

describe("the input from a Mist event", () => {
  it("copies a topic's shape into the draft, read only, then gives it back to form fields", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    await userEvent.click(await within(input()).findByRole("button", { name: "Use a Mist event…" }));
    expect(input().textContent).toContain("This replaces the input's 2 fields with the event's shape. Undo brings them back.");
    await userEvent.type(within(input()).getByRole("searchbox", { name: "Find a topic" }), "device");
    expect(within(input()).getAllByRole("radio").map((r) => (r as HTMLInputElement).value)).toEqual(["device-events", "device-updowns"]);
    await userEvent.click(within(input()).getByRole("radio", { name: "device-events" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Use device-events" }));
    expect(panel.settings()?.input_schema).toEqual(DEVICE_EVENTS);
    expect(input().textContent).toContain("A Mist event: device-events");
    expect(within(input()).getByRole("list", { name: "The event's shape" }).textContent).toContain("[ ].ap_name");
    await userEvent.click(within(input()).getByRole("button", { name: "Use form fields instead" }));
    expect(panel.settings()?.input_schema).toEqual({ type: "object", properties: {} });
  });

  it("gives focus back to what opened the picker, and to what replaces each choice", async () => {
    await showPanel({ doc: draft({ input_schema: SCHEMA }) });
    const open = await within(input()).findByRole("button", { name: "Use a Mist event…" });
    await userEvent.click(open);
    await userEvent.click(within(input()).getByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Use a Mist event…" })));
    await userEvent.click(within(input()).getByRole("button", { name: "Use a Mist event…" }));
    await userEvent.click(within(input()).getByRole("radio", { name: "alarms" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Use alarms" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Use another event…" })));
    await userEvent.click(within(input()).getByRole("button", { name: "Use form fields instead" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "＋ Field" })));
  });
});

describe("the input's CSV file", () => {
  it("adds one of one column, holds a header a save wouldn't take, and removes it whole", async () => {
    const panel = await showPanel({ doc: draft({ input_schema: { type: "object" } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "＋ CSV file" }));
    expect(panel.settings()?.csv).toEqual({ columns: [{ header: "Column 1", name: "column_1", type: "string" }] });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit Column 1" }));
    const column = within(input()).getByRole("group", { name: "The column Column 1" });
    expect(within(column).getByRole<HTMLButtonElement>("button", { name: "Remove column" }).disabled).toBe(true);
    const header = within(column).getByRole("textbox", { name: "Header in the file" });
    await userEvent.clear(header);
    expect(column.textContent).toContain("A header is from 1 to 200 characters.");
    await userEvent.type(header, "AP name");
    expect(panel.settings()?.csv).toEqual({ columns: [{ header: "AP name", name: "column_1", type: "string" }] });
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Remove the CSV file" }));
    expect(panel.settings()?.csv).toBeUndefined();
  });

  it("offers a required column's default its two fixes, from the server's problem", async () => {
    const csv = { columns: [{ header: "Floor", name: "floor", type: "integer" as const, required: true, default: 0 }] };
    const message = "A required column takes no default: an empty cell is refused, so the default would never apply.";
    const panel = await showPanel({ doc: draft({ input_schema: { type: "object" }, csv }), check: checked([problem("/settings/csv/columns/0/default", "csv.required_default", message)]) });
    expect(input().textContent).toContain(`Floor: ${message}`);
    await userEvent.click(within(input()).getAllByRole("button", { name: "Edit Floor" })[0]!); // its row's, or its problem's: one action
    await userEvent.click(within(input()).getByRole("button", { name: "Make it optional" }));
    expect(panel.settings()?.csv).toEqual({ columns: [{ header: "Floor", name: "floor", type: "integer", required: false, default: 0 }] });
  });

  it("never writes a header typed for a column whose place another took since, until Apply here or Discard", async () => {
    // The review of revision 1: B's header held, A removed, then the text at that place finished: it renamed C.
    const columns = ["A", "B", "C"].map((h) => ({ header: h, name: h.toLowerCase(), type: "string" as const }));
    const panel = await showPanel({ doc: draft({ csv: { columns } }) });
    const header = () => within(input()).getByRole<HTMLInputElement>("textbox", { name: "Header in the file" });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit B" }));
    await userEvent.clear(header());
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit A" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Remove column" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit C" }));
    expect(input().textContent).toContain(STALE);
    await userEvent.type(header(), "X");
    expect(panel.settings()?.csv?.columns.map((c) => c.header)).toEqual(["B", "C"]);
    await userEvent.click(within(input()).getByRole("button", { name: "Discard the edit to Column 2's header" }));
    expect(panel.held()).toEqual([]);
    expect(header().value).toBe("C");
    await userEvent.type(header(), "2");
    expect(panel.settings()?.csv?.columns.map((c) => c.header)).toEqual(["B", "C2"]);
  });

  it("never writes a default typed for a column whose place a column of another type took since", async () => {
    // The review of revision 2: B's whole-number default held, A removed, then finished at that place in text column C.
    const columns = [
      { header: "A", name: "a", type: "integer" as const }, { header: "B", name: "b", type: "integer" as const }, { header: "C", name: "c", type: "string" as const },
    ];  // prettier-ignore
    const panel = await showPanel({ doc: draft({ csv: { columns } }) });
    const value = () => within(input()).getByRole<HTMLInputElement>("textbox", { name: "Default (an empty cell gets it)" });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit B" }));
    await userEvent.type(value(), "9x");
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit A" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Remove column" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit C" }));
    expect(value().value).toBe("9x");
    expect(input().textContent).toContain(STALE);
    await userEvent.clear(value());
    await userEvent.type(value(), "9");
    expect(panel.settings()?.csv?.columns[1]).toEqual({ header: "C", name: "c", type: "string" });
    await userEvent.click(within(input()).getByRole("button", { name: "Discard the edit to Column 2's default" }));
    await userEvent.type(value(), "9");
    expect(panel.settings()?.csv?.columns[1]).toEqual({ header: "C", name: "c", type: "string", default: "9" });
  });

  it("gives focus to a column's first control when it opens, back to its Edit when it closes, and to ＋ Column once it's removed", async () => {
    const columns = ["A", "B"].map((h) => ({ header: h, name: h.toLowerCase(), type: "string" as const }));
    await showPanel({ doc: draft({ csv: { columns } }) });
    await userEvent.click(within(input()).getByRole("button", { name: "Edit B" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("textbox", { name: "Header in the file" })));
    await userEvent.keyboard("{Escape}");
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Edit B" })));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit A" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Done" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "Edit A" })));
    await userEvent.click(within(input()).getByRole("button", { name: "Edit A" }));
    await userEvent.click(within(input()).getByRole("button", { name: "Remove column" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(within(input()).getByRole("button", { name: "＋ Column" })));
  });

  it("holds most rows past the platform's, and writes a lower one", async () => {
    const panel = await showPanel({ doc: draft({ csv: { columns: [{ header: "A", name: "a", type: "string" }] } }) });
    const rows = within(input()).getByRole("textbox", { name: "Most rows" });
    await userEvent.type(rows, "20000");
    expect(input().textContent).toContain("A whole number from 1 to 10,000.");
    await userEvent.clear(rows);
    await userEvent.type(rows, "500");
    expect(panel.settings()?.csv).toEqual({ columns: [{ header: "A", name: "a", type: "string" }], max_rows: 500 });
  });
});

describe("the input as JSON", () => {
  it("writes text that reads, holds text that doesn't with its line, and shows the server's problems at theirs", async () => {
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/triggers`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  8 failed | 13 passed (21)`. The failing tests are this task's new
and changed ones: `copies a topic's shape into the draft, read only, then gives it back to form fields`, `gives focus
back to what opened the picker, and to what replaces each choice`, `adds one of one column, holds a header a save
wouldn't take, and removes it whole`, `offers a required column's default its two fixes, from the server's problem`,
`never writes a header typed for a column whose place another took since, until Apply here or Discard`, `never writes a
default typed for a column whose place a column of another type took since`, `gives focus to a column's first control
when it opens, back to its Edit when it closes, and to ＋ Column once it's removed`, `holds most rows past the
platform's, and writes a lower one`.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/routes/editor/triggers/CsvSection.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The input's CSV file (4c-3b; the InputCsv and InputEdit boards): its typed columns, each edited in its row, and its
// limits. A header, a name or a limit a save wouldn't take is held with why (ruling 113), and one typed where the file
// has since changed (a column removed before it, an undo) is written only by Apply here; the server's problems show at
// their column, and a required column's default offers its two fixes. Focus goes back where it was once a column's
// editor closes (the review of revision 1).
import { useEffect, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Field, Select } from "../../../components/Field";
import { Table, Td, Th } from "../../../components/Table";
import {
  CSV_TYPES, MAX_ROWS, addColumn, csvOf, mbOf, removeColumn, rowsLimit, rulesOf, setColumn, setLimits, sizeLimit, textProblem, typeLabel,
  type CsvColumn, type CsvSettings, type CsvType,
} from "../../../lib/csv";  // prettier-ignore
import { setSettings } from "../../../lib/input";
import { parseNumber } from "../../../lib/unapplied";
import type { Diagnostic, GraphDoc } from "../../../lib/workflows";
import type { FocusAt } from "./InputSection";
import { useTriggers } from "./context";
import { Check, Problems, StaleEdit, Values, heldWhy, problemsAt, writeTyped } from "./parts";

const AT = "/settings/csv";
const columnAt = (i: number) => `${AT}/columns/${i}`;
const NO_CHOICE = "A sensitive column can't be a Choice: its values would be written into the workflow.";

/** What `make` makes of the latest draft's CSV file; the draft as it is when it has none, or `make` changes nothing. */
const onCsv = (make: (csv: CsvSettings) => CsvSettings | null | undefined) => (d: GraphDoc): GraphDoc => {
  const csv = csvOf(d);
  const next = csv ? make(csv) : null;
  return next === null || next === undefined || next === csv ? d : setSettings(d, { csv: next });
};

/** A column's header or name: written as typed while a save takes it, held with why when it wouldn't. */
function ColumnText({ i, column, k, label }: { i: number; column: CsvColumn; k: "header" | "name"; label: string }) {
  const t = useTriggers();
  const at = `${columnAt(i)}/${k}`;
  const held = t.actions.held("text", at);
  return (
    <div className="flex flex-col gap-1.5">
      <Field
        label={label} value={held?.text ?? column[k]} disabled={!t.editable} spellCheck={false} error={heldWhy(t.actions, "text", at) ?? undefined}
        onChange={(e) => {
          const text = e.target.value;
          writeTyped(t.actions, "text", at, { path: ["csv", "columns", i, k], label: `Column ${i + 1}'s ${k}`, text }, textProblem(k, text), () =>
            t.actions.update(onCsv((csv) => setColumn(csv, i, { [k]: text })), null, at),
          );
        }}
      />
      <StaleEdit kind="text" at={at} />
    </div>
  );  // prettier-ignore
}

function ColumnDefault({ i, column, set }: { i: number; column: CsvColumn; set: (patch: Partial<CsvColumn>, key: string) => void }) {
  const t = useTriggers();
  const at = `${columnAt(i)}/default`;
  const held = t.actions.held("number", at);
  const label = "Default (an empty cell gets it)";
  if (column.sensitive) return <Field label={label} value="" disabled />;
  if (column.type === "boolean" || column.type === "enum") {
    const options = column.type === "boolean" ? [["true", "Yes"], ["false", "No"]] : (column.values ?? []).map((v) => [JSON.stringify(v), v]);
    return (
      <Select
        label={label} value={"default" in column ? JSON.stringify(column.default) : ""} disabled={!t.editable}
        onChange={(e) => set({ default: e.target.value === "" ? undefined : (JSON.parse(e.target.value) as unknown) }, "default")}
      >
        <option value="">None</option>
        {options.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </Select>
    );  // prettier-ignore
  }
  const numeric = column.type === "integer" || column.type === "number";
  const shown = held?.text ?? (typeof column.default === "string" || typeof column.default === "number" ? String(column.default) : "");
  return (
    <div className="flex flex-col gap-1.5">
      <Field
        label={label} value={shown} disabled={!t.editable} spellCheck={false} error={heldWhy(t.actions, "number", at) ?? undefined}
        onChange={(e) => {
          const text = e.target.value;
          const holding = { path: ["csv", "columns", i, "default"], label: `Column ${i + 1}'s default`, text, whole: column.type === "integer" };
          if (!numeric) {
            // Text is written as typed, unless an edit is held here: typed for another column, it's never written over
            // this one unasked (the review of revision 2).
            const write = () => t.actions.update(onCsv((csv) => setColumn(csv, i, { default: text === "" ? undefined : text })), null, at);
            return held ? writeTyped(t.actions, "number", at, holding, null, write) : void write();
          }
          const parsed = parseNumber(text, column.type === "integer");
          writeTyped(t.actions, "number", at, holding, "problem" in parsed ? parsed.problem : null, () =>
            "problem" in parsed ? null : t.actions.update(onCsv((csv) => setColumn(csv, i, { default: parsed.value })), null, at),
          );
        }}
      />
      <StaleEdit kind="number" at={at} />
    </div>
  );  // prettier-ignore
}

/** The fixes a column's problem offers, where there are some (the InputEdit board). */
function Fixes({ d, set }: { d: Diagnostic; set: (patch: Partial<CsvColumn>, key: string) => void }) {
  if (d.code !== "csv.required_default") return null;
  return (
    <span className="flex flex-wrap gap-2">
      <Button size="sm" onClick={() => set({ default: undefined }, "default")}>Clear the default</Button>
      <Button size="sm" onClick={() => set({ required: false }, "required")}>Make it optional</Button>
    </span>
  );
}

function ColumnEditor({ i, column, last, onClose }: { i: number; column: CsvColumn; last: boolean; onClose: (removed?: boolean) => void }) {
  const t = useTriggers();
  const disabled = !t.editable;
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.querySelector("input")?.focus(), []);
  const set = (patch: Partial<CsvColumn>, key: string) =>
    t.actions.update(onCsv((csv) => setColumn(csv, i, patch)), null, `${columnAt(i)}/${key}`);
  const problems = problemsAt(t.check, columnAt(i));
  return (
    <div
      ref={box} role="group" aria-label={`The column ${column.header}`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="flex flex-col gap-3 rounded-lg border border-line-strong p-3"
    >
      <ColumnText i={i} column={column} k="header" label="Header in the file" />
      <ColumnText i={i} column={column} k="name" label="Name" />
      <Select label="Type" value={column.type} disabled={disabled} hint={column.sensitive ? NO_CHOICE : undefined} onChange={(e) => set({ type: e.target.value as CsvType }, "type")}>
        {CSV_TYPES.map((x) => <option key={x.value} value={x.value} disabled={x.value === "enum" && column.sensitive === true}>{x.label}</option>)}
      </Select>
      <Check label="Required" checked={column.required === true} disabled={disabled} hint="A row with this cell empty is refused." onChange={(required) => set({ required }, "required")} />
      <Check
        label="Sensitive" checked={column.sensitive === true} disabled={disabled || column.type === "enum"}
        hint={column.type === "enum" ? NO_CHOICE : "Kept apart from run history; it has no default."} onChange={(sensitive) => set({ sensitive }, "sensitive")}
      />
      {column.type === "enum" && (
        <Values
          label={`The column ${column.header}'s values`} values={column.values ?? []} disabled={disabled}
          hint={`A cell must be one of these, as written. Up to 200. ${NO_CHOICE}`} onChange={(values) => set({ values }, "values")}
        />
      )}
      <ColumnDefault i={i} column={column} set={set} />
      {problems.map((d, n) => (
        <div key={`${d.code}:${n}`} className="flex flex-col gap-2">
          <Problems problems={[d]} />
          {!disabled && <Fixes d={d} set={set} />}
        </div>
      ))}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="primary" onClick={() => onClose()}>Done</Button>
        {!disabled && (
          <Button
            size="sm" variant="danger-outline" disabled={last}
            onClick={() => {
              t.actions.discard(columnAt(i));
              const said = `Removed the column ${column.header}.`;
              if (t.actions.update(onCsv((csv) => removeColumn(csv, i)), said) === null) onClose(true);
            }}
          >
            Remove column
          </Button>
        )}
      </div>
      {last && !disabled && <p className="text-small text-muted">A CSV file keeps one column at least: remove the file instead.</p>}
    </div>
  );  // prettier-ignore
}

/** Most rows, or the largest file in MB: written while a save takes it, held with why when it wouldn't. */
function Limit({ k, label, csv }: { k: "max_rows" | "max_bytes"; label: string; csv: CsvSettings }) {
  const t = useTriggers();
  const at = `${AT}/${k}`;
  const held = t.actions.held("limit", at);
  const current = csv[k];
  const shown = held?.text ?? (current === undefined ? "" : k === "max_bytes" ? mbOf(current) : String(current));
  return (
    <div className="flex flex-col gap-1.5">
      <Field
        label={label} value={shown} disabled={!t.editable} inputMode="decimal" error={heldWhy(t.actions, "limit", at) ?? undefined}
        placeholder={k === "max_bytes" ? "5" : String(MAX_ROWS)}
        onChange={(e) => {
          const text = e.target.value;
          const read = k === "max_bytes" ? sizeLimit(text) : rowsLimit(text);
          writeTyped(t.actions, "limit", at, { path: ["csv", k], label, text }, "problem" in read ? read.problem : null, () =>
            "problem" in read ? null : t.actions.update(onCsv((csv) => setLimits(csv, { [k]: read.value })), null, at),
          );
        }}
      />
      <StaleEdit kind="limit" at={at} />
    </div>
  );  // prettier-ignore
}

export function CsvSection({ csv, focusAt, back }: { csv: CsvSettings; focusAt: FocusAt; back: (...keys: string[]) => void }) {
  const t = useTriggers();
  const [editing, setEditing] = useState<number | null>(null);
  useEffect(() => {
    const m = focusAt ? /^\/settings\/csv\/columns\/(\d+)/.exec(focusAt.pointer) : null;
    if (m) setEditing(Number(m[1]));
  }, [focusAt]);
  const columnProblems = csv.columns.flatMap((c, i) => (editing === i ? [] : problemsAt(t.check, columnAt(i)).map((d) => ({ i, c, d }))));
  return (
    <div role="group" aria-labelledby="triggers-csv" className="flex flex-col gap-3">
      <h4 id="triggers-csv" className="text-small font-semibold">CSV file</h4>
      <p className="text-small text-muted">
        Started by hand with a file: one run reads its rows as <code className="font-mono">trigger.rows</code> and their count as{" "}
        <code className="font-mono">trigger.row_count</code>.
      </p>
      <Problems problems={problemsAt(t.check, AT, true)} />
      <Table label="CSV columns">
        <thead>
          <tr><Th>Header</Th><Th>Name</Th><Th>Type</Th><Th>Rules</Th><Th><span className="sr-only">Actions</span></Th></tr>
        </thead>
        <tbody>
          {csv.columns.map((c, i) =>
            editing === i ? (
              <tr key={i}>
                <Td colSpan={5}>
                  <ColumnEditor
                    i={i} column={c} last={csv.columns.length === 1}
                    onClose={(removed) => {
                      setEditing(null);
                      back(removed ? "add-column" : `column:${i}`);
                    }}
                  />
                </Td>
              </tr>
            ) : (
              <tr key={i}>
                <Td>{c.header}</Td>
                <Td className="font-mono text-small">{c.name}</Td>
                <Td>{typeLabel(c.type)}</Td>
                <Td className="text-small text-muted">{rulesOf(c)}</Td>
                <Td className="text-right">
                  {t.editable && <Button size="sm" aria-label={`Edit ${c.header}`} data-back={`column:${i}`} onClick={() => setEditing(i)}>Edit</Button>}
                </Td>
              </tr>
            ),
          )}
        </tbody>
      </Table>
      {columnProblems.map(({ i, c, d }, n) => (
        <div key={n} className="flex flex-wrap items-center gap-2">
          <p className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>{c.header}: {d.message}</p>
          {t.editable && <Button size="sm" onClick={() => setEditing(i)}>Edit {c.header}</Button>}
        </div>
      ))}
      <p className="text-small text-muted">Types: {CSV_TYPES.map((x) => x.label).join(", ")}.</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Limit k="max_rows" label="Most rows" csv={csv} />
        <Limit k="max_bytes" label="Largest file (MB)" csv={csv} />
      </div>
      <p className="text-small text-muted">At most 10,000 rows and 5 MB, the platform&apos;s limits; lower them here if you like.</p>
      {t.editable && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" data-back="add-column" onClick={() => t.actions.update(onCsv(addColumn), "Added a column to the CSV file.")}>＋ Column</Button>
          <Button
            size="sm" variant="danger-outline"
            onClick={() => {
              t.actions.discard(AT);
              if (t.actions.update((d) => setSettings(d, { csv: undefined }), "Removed the CSV file. Undo brings it back.") === null) back("csv");
            }}
          >
            Remove the CSV file
          </Button>
        </div>
      )}
      <p className="text-small text-muted">
        A workflow that takes a CSV file runs only when started by hand with a file: a schedule, a webhook or another workflow can&apos;t give it rows.
      </p>
    </div>
  );  // prettier-ignore
}
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The input (4c-3b; the InputFields and InputEdit boards): what every trigger starts a run with, and, by hand, the
// run's form. Saved with the draft, used once published. As form fields, or as JSON (Task 8 adds a Mist event's shape
// and a CSV file). Focus goes back to what opened a part once it closes (WCAG 2.4.3).
import { useEffect, useState } from "react";
import { Button } from "../../../components/Button";
````

**with**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The input (4c-3b; the InputFields, InputMist, InputCsv and InputEdit boards): what every trigger starts a run with,
// and, by hand, the run's form. Saved with the draft, used once published. As form fields, as a Mist event's shape (read
// only, replaceable), with a CSV file, or as JSON. Focus goes back to what opened a part once it closes (WCAG 2.4.3).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button } from "../../../components/Button";
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
import { addField, fieldPointer, inputOf, inputRows, setSettings } from "../../../lib/input";
import { useTriggers } from "./context";
````

**with**:

````tsx
import { csvOf, newCsv } from "../../../lib/csv";
import { addField, fieldPointer, inputOf, inputRows, setSettings, topicShaped } from "../../../lib/input";
import { senderName, triggerTypesQuery } from "../../../lib/triggers";
import { useTriggers } from "./context";
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
import { FieldEditor } from "./FieldEditor";
import { InputJson, JSON_AT } from "./InputJson";
````

**with**:

````tsx
import { CsvSection } from "./CsvSection";
import { FieldEditor } from "./FieldEditor";
import { InputJson, JSON_AT } from "./InputJson";
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
import { Problems, Section, problemsAt, useFocusBack } from "./parts";

````

**with**:

````tsx
import { MistPicker, MistShape } from "./MistEvent";
import { Problems, Section, problemsAt, useFocusBack } from "./parts";

````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
const TYPE_WORDS: Record<string, string> = { text: "Text", whole: "Whole number", number: "Number", yesno: "Yes or no", choice: "Choice", datetime: "Date and time" };

type Mode = "fields" | "json";

````

**with**:

````tsx
const TYPE_WORDS: Record<string, string> = { text: "Text", whole: "Whole number", number: "Number", yesno: "Yes or no", choice: "Choice", datetime: "Date and time" };

type Mode = "fields" | "json" | "mist";

````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
/** Where "Go to it" in the edits not applied lands: JSON, or a field. */
export type FocusAt = { pointer: string; n: number } | null;

````

**with**:

````tsx
/** Where "Go to it" in the edits not applied lands: JSON, a field, or the CSV file. */
export type FocusAt = { pointer: string; n: number } | null;

````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
  const t = useTriggers();
  const { actions, doc } = t;
  const schema = inputOf(doc);
````

**with**:

````tsx
  const t = useTriggers();
  const { actions, doc } = t;
  const types = useQuery(triggerTypesQuery);
  const schema = inputOf(doc);
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
  const [mode, setMode] = useState<Mode>(() => (actions.held("json", JSON_AT) ? "json" : "fields"));
  const [editing, setEditing] = useState<string | null>(null);
````

**with**:

````tsx
  const csv = csvOf(doc);
  const webhook = (types.data ?? []).find((x) => Object.keys(x.topics).length > 0);
  const shaped = webhook ? topicShaped(schema, webhook.topics) : null;
  const [mode, setMode] = useState<Mode>(() => (actions.held("json", JSON_AT) ? "json" : "fields"));
  const [editing, setEditing] = useState<string | null>(null);
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
  }, [focusAt]);
  const rows = inputRows(schema);
  const heldJson = actions.held("json", JSON_AT);
  const add = () => {
````

**with**:

````tsx
  }, [focusAt]);
  const rows = inputRows(schema);
  const fields = rows.length; // every field the input has, the list can show it or not
  const heldJson = actions.held("json", JSON_AT);
  const add = () => {
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
  };
  return (
    <Section id="triggers-input" title="Input" note="Saved with the draft · used once published" box={box}>
      {mode !== "json" && <p className="text-small text-muted">Every trigger starts a run with this input. By hand, it&apos;s the run&apos;s form.</p>}
      <Problems problems={problemsAt(t.check, "/settings/input_schema", true)} />
````

**with**:

````tsx
  };
  return (
    <Section id="triggers-input" title={csv ? "Input · CSV file" : "Input"} note="Saved with the draft · used once published" box={box}>
      {mode !== "json" && <p className="text-small text-muted">Every trigger starts a run with this input. By hand, it&apos;s the run&apos;s form.</p>}
      <Problems problems={problemsAt(t.check, "/settings/input_schema", true)} />
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
          }}
        />
      ) : (
        <>
````

**with**:

````tsx
          }}
        />
      ) : mode === "mist" && webhook ? (
        <MistPicker
          type={webhook} fields={fields}
          onDone={() => {
            setMode("fields");
            back("mist");
          }}
        />
      ) : shaped && webhook ? (
        <MistShape type={webhook} topic={shaped} onAnother={() => setMode("mist")} onJson={() => setMode("json")} onFields={() => back("add")} />
      ) : (
        <>
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
            <div className="flex flex-wrap gap-2">
              <Button size="sm" data-back="add" onClick={add}>＋ Field</Button>
              <Button size="sm" data-back="json" onClick={() => setMode("json")}>Edit as JSON</Button>
            </div>
````

**with**:

````tsx
            <div className="flex flex-wrap gap-2">
              <Button size="sm" data-back="add" onClick={add}>＋ Field</Button>
              {webhook && <Button size="sm" data-back="mist" onClick={() => setMode("mist")}>Use a {senderName(webhook)} event…</Button>}
              {!csv && (
                <Button
                  size="sm" data-back="csv"
                  onClick={() => {
                    if (actions.update((d) => setSettings(d, { csv: newCsv() }), "Added a CSV file to the input.") === null) back("column:0");
                  }}
                >
                  ＋ CSV file
                </Button>
              )}
              <Button size="sm" data-back="json" onClick={() => setMode("json")}>Edit as JSON</Button>
            </div>
````

**In** `frontend/src/routes/editor/triggers/InputSection.tsx`, **replace**:

````tsx
        </>
      )}
    </Section>
  );  // prettier-ignore
````

**with**:

````tsx
        </>
      )}
      {csv && mode !== "json" && <CsvSection csv={csv} focusAt={focusAt} back={back} />}
    </Section>
  );  // prettier-ignore
````

**Create** `frontend/src/routes/editor/triggers/MistEvent.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The input from a webhook trigger's topic (4c-3b; the InputMist board): a topic picked from what the plugin declares
// (`/trigger-types`), its shape copied into the draft whole, read only here, and replaceable: another topic, form
// fields, or JSON. Undo brings back what it replaced. Its buttons are where focus comes back to (`data-back`).
import { useId, useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { inputOf, setSettings, shapeRows } from "../../../lib/input";
import { possessive, senderName, type TriggerType } from "../../../lib/triggers";
import { useTriggers } from "./context";

const SHOWN = 8; // topics listed at once: a search finds the rest

export function MistPicker({ type, fields, onDone }: { type: TriggerType; fields: number; onDone: () => void }) {
  const { actions } = useTriggers();
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const legend = useId();
  const found = Object.keys(type.topics).filter((t) => t.includes(query.trim().toLowerCase()));
  const sender = senderName(type);
  const use = () => {
    if (chosen === null) return;
    const shape = type.topics[chosen];
    if (actions.update((d) => setSettings(d, { input_schema: shape }), `The input is now ${possessive(chosen)} shape. Undo brings back what it replaced.`) === null) onDone();
  };
  return (
    <div role="group" aria-labelledby={legend} className="flex flex-col gap-3">
      <span id={legend} className="text-small font-semibold">Use a {sender} event</span>
      <input
        type="search" aria-label="Find a topic" placeholder="Find a topic, like device" value={query} autoFocus
        onChange={(e) => setQuery(e.target.value)} className={controlClass(false)}
      />
      <div role="radiogroup" aria-label="Topic" className="flex flex-col gap-1">
        {found.slice(0, SHOWN).map((t) => (
          <label key={t} className="flex min-h-6 items-center gap-2 font-mono text-small">
            <input type="radio" name="topic" value={t} checked={chosen === t} onChange={() => setChosen(t)} className="size-[16px] accent-accent" />
            {t}
          </label>
        ))}
        {found.length === 0 && <span className="text-small text-muted">No topic has that in its name.</span>}
        {found.length > SHOWN && <span className="text-small text-muted">and {found.length - SHOWN} more topics: find them by name</span>}
      </div>
      <p className="text-small text-muted">
        {fields > 0
          ? `This replaces the input's ${fields === 1 ? "field" : `${fields} fields`} with the event's shape. Undo brings ${fields === 1 ? "it" : "them"} back.`
          : "The input becomes the event's shape. Undo brings back what it replaced."}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="primary" disabled={chosen === null} onClick={use}>{chosen === null ? "Use this topic" : `Use ${chosen}`}</Button>
        <Button size="sm" onClick={onDone}>Cancel</Button>
      </div>
    </div>
  );  // prettier-ignore
}

export function MistShape({ type, topic, onAnother, onJson, onFields }: {
  type: TriggerType; topic: string; onAnother: () => void; onJson: () => void; onFields: () => void;
}) {  // prettier-ignore
  const { doc, editable, actions } = useTriggers();
  const { rows, more } = shapeRows(inputOf(doc), topic);
  const sender = senderName(type);
  const example = rows.find((r) => r.path.startsWith("[ ]."))?.path.slice(4);
  return (
    <div className="flex flex-col gap-3">
      <p className="text-small font-semibold">A {sender} event: <span className="font-mono">{topic}</span></p>
      <ul aria-label="The event's shape" className="flex flex-col rounded-lg border border-line px-3 py-1">
        {rows.map((r) => (
          <li key={r.path} className={`flex flex-wrap gap-x-2 py-1 text-small ${r.path.startsWith("[ ]") ? "pl-4" : ""}`}>
            <span className="font-mono">{r.path}</span>
            <span className="text-muted">{r.what}{r.optional && " · may be missing"}</span>
          </li>
        ))}
        {more && <li className="py-1 pl-4 text-small text-muted">and more fields</li>}
      </ul>
      <p className="text-small text-muted">
        Read only: it&apos;s {possessive(sender)} shape.
        {example && <> A step reads one event as <code className="font-mono">trigger.events[0].{example}</code>; the data tree lists them all.</>}
      </p>
      <div className="flex flex-wrap gap-2">
        {editable && <Button size="sm" data-back="mist" onClick={onAnother}>Use another event…</Button>}
        {editable && (
          <Button
            size="sm"
            onClick={() => {
              const said = "The input is form fields now, none yet. Undo brings the event's shape back.";
              if (actions.update((d) => setSettings(d, { input_schema: { type: "object", properties: {} } }), said) === null) onFields();
            }}
          >
            Use form fields instead
          </Button>
        )}
        <Button size="sm" data-back="json" onClick={onJson}>{editable ? "Edit as JSON" : "Show as JSON"}</Button>
      </div>
    </div>
  );  // prettier-ignore
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/triggers`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  21 passed (21)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/triggers/CsvSection.tsx \
  frontend/src/routes/editor/triggers/InputSection.test.tsx \
  frontend/src/routes/editor/triggers/InputSection.tsx \
  frontend/src/routes/editor/triggers/MistEvent.tsx
git commit -m "feat(editor): the input from a Mist event's shape, and with a CSV file (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Milestone 2's pause.** Screenshots of the start card and the Triggers panel (its fields, a field edited, a Mist
  event's shape, a CSV file with a column edited, JSON held), light and dark, at 1280 and 320 px, against the isolated
  stack after a reset, beside the boards (Main, InputFields, InputMist, InputCsv, InputEdit, Narrow, NarrowForms); the
  unit suite, typecheck, lint and build; then append to the ledger `### 4c-3b, milestone 2 (<date>)` (Tasks 7–8's
  commits, the checks as run, mid-slice rulings or none) and commit it. **Pause:** the owner reviews the screens before
  Task 9; Milestone 3 starts on the owner's word.

---

# Milestone 3 — schedules, endpoints, webhooks

### Task 9: Schedules

A workflow's live schedules in the panel (ruling 8): each in words, with what its sync proves and the firings it missed;
turned on or off at once; edited on its form, its stored input kept unless it's replaced whole; deleted once asked; what
the draft would break, as the server's check says (4c-3a ruling 7). The form's When, time zone, mode and catch-up; its
input on the published version's form, a list, an object or several types as JSON, and the whole input as JSON where its
rules are more than the fields show, or on request: settled before anything is typed, carried between the two, JSON a
parse would change refused, every key kept as typed, a value moving to a field only when the field reads it back exactly
(the reviews of revisions 3 to 5). A timing no preset says is kept as it is, and an edit sends the timing only when it
changed (the reviews of revisions 1 and 2). ＋ Schedule is disabled, with why, before a first publish and while the
published version takes a CSV file.

**Files:**
- Modify: `frontend/src/components/Field.tsx`
- Create: `frontend/src/routes/editor/triggers/ScheduleForm.tsx`
- Create: `frontend/src/routes/editor/triggers/SchedulesSection.test.tsx`
- Create: `frontend/src/routes/editor/triggers/SchedulesSection.tsx`
- Modify: `frontend/src/routes/editor/triggers/TriggersPanel.tsx`

**Interfaces:**
- Consumes: Tasks 2, 3 and 7.
- Produces: `SchedulesSection`, `ScheduleForm`; the panel's Schedules section; `TextArea` (`components/Field.tsx`).

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/routes/editor/triggers/SchedulesSection.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Schedule } from "../../../lib/triggers";
import type { Validation } from "../../../lib/workflows";
import { SCHEDULE } from "../../../test/triggers";
import { fakeApi, json } from "../drawer/harness";
import { showPanel } from "./harness";

const FORM = {
  workflow_id: "w1", version_id: "v3", csv: null,
  fields: [{ name: "site", type: "string", required: true, sensitive: false, title: "Site" }, { name: "note", type: "string", required: false, sensitive: false, title: "Note" }],
};  // prettier-ignore
const section = () => screen.getByRole("region", { name: "Schedules" });

function api(schedules: Schedule[], more: Record<string, () => Response | Promise<Response>> = {}) {
  return fakeApi({
    "GET /api/v1/trigger-types": () => json([]),
    "GET /api/v1/t/t1/workflows/w1/webhook-bindings": () => json({ bindings: [] }),
    "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: { graph_format: 1 } }),
    "GET /api/v1/t/t1/workflows/w1/schedules": () => json({ schedules }),
    "GET /api/v1/t/t1/workflows/w1/start-form": () => json(FORM),
    ...more,
  });
}
afterEach(() => vi.restoreAllMocks());

describe("a workflow's schedules", () => {
  it("says each one in words, and what its sync proves, as the Schedules board does", async () => {
    api([
      SCHEDULE,
      { ...SCHEDULE, id: "s2", cron: "0 6 * * 1", generation: 1, synced_generation: 0 },
      { ...SCHEDULE, id: "s3", cron: "30 8 * * 1-5", time_zone: "America/New_York", generation: 4, synced_generation: 3, sync_error: "invalid_spec", sync_error_at: "2026-10-11T08:00:00Z" },
      { ...SCHEDULE, id: "s4", cron: null, every_s: 900, mode: "simulate", enabled: false },
      { ...SCHEDULE, id: "s5", cron: "0 */6 * * 1-5", time_zone: "UTC", misses: 3, misses_read_at: "2026-10-11T14:05:00Z", accounting_complete: false },
    ]);
    await showPanel();
    const rows = (await within(section()).findAllByRole("listitem")).map((r) => r.textContent ?? "");
    const said = [
      ["Every day at 07:00", "Europe/Paris · live · synced"],
      ["At 0 6 * * 1", "Saved; sync not yet confirmed: it may already fire."], // no preset says Mondays: its cron
      ["Weekdays at 08:30", "Sync failed: the scheduler refused this change. Its previous time may still fire"],
      ["Every 15 minutes", "simulated: nothing is sent · off · synced"],
      ["At 0 */6 * * 1-5", "UTC · live · custom · synced", "3 firings missed, counted at", "Some may be missed still, not yet counted."],
    ];
    said.forEach((parts, i) => parts.forEach((part) => expect(rows[i]).toContain(part)));
    expect(within(section()).getByRole("switch", { name: "Every day at 07:00" }).getAttribute("aria-checked")).toBe("true");
  });

  it("can't add one before a first publish, nor to a workflow that takes a CSV file, and says why", async () => {
    api([]);
    await showPanel({ activeNumber: null, activeVersionId: null });
    expect(within(section()).getByRole<HTMLButtonElement>("button", { name: "＋ Schedule" }).disabled).toBe(true);
    expect(section().textContent).toContain("A schedule runs the published version: publish a first version to add one.");
  });

  it("says a workflow that takes a CSV file can't run on a schedule", async () => {
    api([], { "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, csv: { columns: [], max_rows: 10, max_bytes: 10 } }) });
    await showPanel();
    await vi.waitFor(() => expect(section().textContent).toContain("It takes a CSV file: its rows come from an upload, so it can't run on a schedule."));
    expect(within(section()).getByRole<HTMLButtonElement>("button", { name: "＋ Schedule" }).disabled).toBe(true);
  });

  it("adds one on the published version's form, checking the input before anything is sent", async () => {
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    expect(form.textContent).toContain("Input · version 3's form");
    const zone = within(form).getByRole("combobox", { name: "Time zone" });
    await userEvent.clear(zone);
    await userEvent.type(zone, "Europe/Paris");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain("Site is required.");
    expect(sent.some((r) => r.method === "POST")).toBe(false);
    await userEvent.type(within(form).getByRole("textbox", { name: "Site (required)" }), "HQ");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "POST")?.body).toEqual({
        cron: "0 7 * * *", every_s: null, offset_s: 0, time_zone: "Europe/Paris", catchup_window_s: 600, mode: "live", input: { site: "HQ" },
      }),
    );  // prettier-ignore
  });

  it("shows each refusal of its timing at the field it names", async () => {
    api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ error: "schedule_invalid", problems: [{ field: "cron", code: "cron_day_fields" }] }, 422) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "When" }), "Custom (cron)");
    await userEvent.type(within(form).getByRole("textbox", { name: "Cron" }), "0 9 1 * MON");
    await userEvent.type(within(form).getByRole("textbox", { name: "Site (required)" }), "HQ");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    const cron = within(form).getByRole("textbox", { name: "Cron" });
    await vi.waitFor(() => expect(cron.getAttribute("aria-invalid")).toBe("true"));
    expect(form.textContent).toContain("Choose a day of the month or a day of the week, not both: put * in one of them.");
  });

  it("edits one: its stored input kept unless replaced whole, and only what changed sent", async () => {
    const sent = api([SCHEDULE], { "PATCH /api/v1/t/t1/schedules/s1": () => json({ ...SCHEDULE, mode: "simulate" }) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Every day at 07:00" }));
    const form = within(section()).getByRole("form", { name: 'Editing "Every day at 07:00"' });
    expect(form.textContent).toContain("Set when it was created; not shown back.");
    await userEvent.click(within(form).getByRole("radio", { name: "Simulate" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ mode: "simulate" }));
  });

  it.each([
    { title: "Every 90 seconds", every_s: 90, offset_s: 0 },
    { title: "Every 72 hours", every_s: 72 * 3600, offset_s: 51 * 3600 },
  ])("keeps a timing no preset says, $title, as it is, and sends the mode alone when only it changes", async ({ title, every_s, offset_s }) => {
    // The review of revision 1: such a timing opened as an empty cron, or a first run at 51:00, and blocked every save.
    const kept: Schedule = { ...SCHEDULE, cron: null, every_s, offset_s, time_zone: "UTC" };
    const sent = api([kept], { "PATCH /api/v1/t/t1/schedules/s1": () => json({ ...kept, mode: "simulate" }) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: `Edit ${title}` }));
    const form = within(section()).getByRole("form", { name: `Editing "${title}"` });
    expect(within(form).getByRole<HTMLOptionElement>("option", { name: `${title}, as it is` }).selected).toBe(true);
    expect(form.textContent).toContain("Set outside this form, it's kept as it is: choosing another When replaces it.");
    await userEvent.click(within(form).getByRole("radio", { name: "Simulate" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ mode: "simulate" }));
  });

  it("takes a list, an object or a value of several types as JSON, keeps a choice's type, and leaves out what isn't given", async () => {
    // The review of revision 1: ["ap-1"] typed for a list was sent as text.
    const fields = [
      { name: "aps", type: "array", required: true, sensitive: false, title: "APs" },
      { name: "meta", type: "object", required: false, sensitive: false },
      { name: "note", type: ["string", "null"], required: false, sensitive: false },
      { name: "level", type: "integer", required: false, sensitive: false, enum: [1, 2] },
    ];
    const sent = api([], {
      "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields }),
      "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    const aps = within(form).getByRole("textbox", { name: "APs (required)" });
    expect(form.textContent).toContain('As JSON, like ["ap-1"] or {"site": "HQ"}; text in quotes.');
    await userEvent.click(aps);
    await userEvent.paste('["ap-1"');
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain("This isn't valid JSON, so it isn't saved.");
    expect(sent.some((r) => r.method === "POST")).toBe(false);
    await userEvent.clear(aps);
    await userEvent.paste('["ap-1"]');
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "level" }), "2");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ aps: ["ap-1"], level: 2 }));
  });

  it.each([
    { what: "allOf", input_schema: { type: "object", allOf: [{ properties: { site: { type: "string" } }, required: ["site"] }] } },
    { what: "a $ref", input_schema: { $ref: "#/$defs/in", $defs: { in: { type: "object", properties: { site: { type: "string" } }, required: ["site"] } } } },
  ])("takes the whole input as JSON when the form can't show it field by field ($what)", async ({ input_schema }) => {
    // The review of revision 2: the start form has no field for these, so the form sent {}.
    const sent = api([], {
      "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields: [] }),
      "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: { graph_format: 1, settings: { input_schema } } }),
      "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    const box = await within(form).findByRole("textbox", { name: "The input, as JSON" });
    expect(form.textContent).toContain("Version 3's input has rules this form can't show field by field: it's entered as JSON.");
    await userEvent.click(box);
    await userEvent.paste("[1]");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain('An object, like {"site": "HQ"}.');
    expect(sent.some((r) => r.method === "POST")).toBe(false);
    await userEvent.clear(box);
    await userEvent.paste('{"site": "HQ"}');
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "HQ" }));
  });

  it("takes the whole input as JSON on request, beside its fields", async () => {
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(within(form).getByRole("button", { name: "Enter it as JSON" }));
    await userEvent.click(within(form).getByRole("textbox", { name: "The input, as JSON" }));
    await userEvent.paste('{"site": "HQ", "extra": [1]}');
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "HQ", extra: [1] }));
  });

  it("waits for the version's input before taking any, then starts its JSON from the fields' defaults", async () => {
    // The review of revision 3: a field filled while the version loaded was lost when its rules turned the form to JSON.
    let version: ((r: Response) => void) | undefined;
    const fields = [{ name: "site", type: "string", required: true, sensitive: false, title: "Site", default: "Lab" }];
    const input_schema = { type: "object", properties: { site: { type: "string", default: "Lab" } }, allOf: [{ required: ["site"] }] };
    const sent = api([], {
      "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields }),
      "GET /api/v1/t/t1/workflows/w1/versions/v3": () => new Promise<Response>((resolve) => (version = resolve)),
      "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    expect(form.textContent).toContain("Loading version 3's input…");
    expect(within(form).queryByRole("textbox", { name: "Site (required)" })).toBeNull();
    expect(within(form).getByRole<HTMLButtonElement>("button", { name: "Add the schedule" }).disabled).toBe(true);
    await vi.waitFor(() => expect(version).toBeDefined());
    version!(json({ id: "v3", number: 3, graph: { graph_format: 1, settings: { input_schema } } }));
    const box = await within(form).findByRole<HTMLTextAreaElement>("textbox", { name: "The input, as JSON" });
    expect(JSON.parse(box.value)).toEqual({ site: "Lab" });
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "Lab" }));
  });

  it("carries what's entered between the fields and the JSON, and keeps JSON no field can show", async () => {
    // The review of revision 3: a switch either way sent the other entry's empty input.
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.type(await within(form).findByRole("textbox", { name: "Site (required)" }), "HQ");
    await userEvent.type(within(form).getByRole("textbox", { name: "Note" }), "n");
    await userEvent.click(within(form).getByRole("button", { name: "Enter it as JSON" }));
    const box = within(form).getByRole<HTMLTextAreaElement>("textbox", { name: "The input, as JSON" });
    expect(JSON.parse(box.value)).toEqual({ site: "HQ", note: "n" });
    await userEvent.clear(box);
    await userEvent.paste('{"site": "Lab", "extra": 1}');
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(form.textContent).toContain("No field here shows extra as written: it stays as JSON.");
    await userEvent.clear(box);
    await userEvent.paste('{"site": "Lab"}');
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Site (required)" }).value).toBe("Lab");
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Note" }).value).toBe("");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "Lab" }));
  });

  it("keeps an empty text in the JSON, required or not: a field's empty control means not given", async () => {
    // The review of revision 4: {"site": ""} moved to the fields was sent as {}, or refused as required.
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(await within(form).findByRole("button", { name: "Enter it as JSON" }));
    const box = within(form).getByRole("textbox", { name: "The input, as JSON" });
    await userEvent.click(box);
    await userEvent.paste('{"site": "HQ", "note": ""}');
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(form.textContent).toContain("No field here shows note as written: it stays as JSON.");
    await userEvent.clear(box);
    await userEvent.paste('{"site": ""}');
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(form.textContent).toContain("No field here shows site as written: it stays as JSON.");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: "" }));
  });

  it("keeps text with a line break in the JSON, and moves spaces and tabs to a field as they are", async () => {
    // The review of revision 5: a one-line field drops line breaks, so "HQ\nLab" was sent as "HQLab".
    const sent = api([], { "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(await within(form).findByRole("button", { name: "Enter it as JSON" }));
    const box = within(form).getByRole("textbox", { name: "The input, as JSON" });
    for (const broken of ["HQ\nLab", "HQ\rLab", "HQ\r\nLab"]) {
      await userEvent.clear(box);
      await userEvent.click(box);
      await userEvent.paste(JSON.stringify({ site: broken }));
      await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
      expect(form.textContent, JSON.stringify(broken)).toContain("No field here shows site as written: it stays as JSON.");
    }
    await userEvent.clear(box);
    await userEvent.click(box);
    await userEvent.paste(JSON.stringify({ site: " HQ\tLab " }));
    await userEvent.click(within(form).getByRole("button", { name: "Enter it field by field" }));
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Site (required)" }).value).toBe(" HQ\tLab ");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect((sent.find((r) => r.method === "POST")?.body as { input: unknown }).input).toEqual({ site: " HQ\tLab " }));
  });

  it("refuses JSON whose numbers parsing would change, in the whole input and in a field", async () => {
    // The review of revision 3: 9007199254740993 was sent as …992, and 1e400 as null.
    const fields = [{ name: "aps", type: "array", required: false, sensitive: false, title: "APs" }];
    const sent = api([], { "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields }) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(await within(form).findByRole("textbox", { name: "APs" }));
    await userEvent.paste("[9007199254740993]");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain("A whole number here is too large to keep exactly, so it isn't saved.");
    await userEvent.clear(within(form).getByRole("textbox", { name: "APs" }));
    await userEvent.click(within(form).getByRole("button", { name: "Enter it as JSON" }));
    const box = within(form).getByRole("textbox", { name: "The input, as JSON" });
    await userEvent.click(box);
    await userEvent.paste('{"meta": [1e400]}');
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    expect(form.textContent).toContain("A number here is too large to keep, so it isn't saved.");
    expect(sent.some((r) => r.method === "POST")).toBe(false);
  });

  it("keeps a key named __proto__, typed in the JSON or as a field's name", async () => {
    // The review of revision 3: copying the input set its prototype instead, and the key was gone.
    const fields = [{ name: "__proto__", type: "string", required: true, sensitive: false, title: "Proto" }];
    const sent = api([], {
      "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ ...FORM, fields }),
      "POST /api/v1/t/t1/workflows/w1/schedules": () => json({ ...SCHEDULE, id: "s9" }, 201),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const form = within(section()).getByRole("form", { name: "New schedule" });
    const proto = await within(form).findByRole<HTMLInputElement>("textbox", { name: "Proto (required)" });
    expect(proto.value).toBe("");
    await userEvent.type(proto, "HQ");
    await userEvent.click(within(form).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect(sent.filter((r) => r.method === "POST")).toHaveLength(1));
    const first = (sent.find((r) => r.method === "POST")!.body as { input: object }).input;
    expect(Object.getOwnPropertyDescriptor(first, "__proto__")?.value).toBe("HQ");
    await userEvent.click(await within(section()).findByRole("button", { name: "＋ Schedule" }));
    const again = within(section()).getByRole("form", { name: "New schedule" });
    await userEvent.click(await within(again).findByRole("button", { name: "Enter it as JSON" }));
    await userEvent.click(within(again).getByRole("textbox", { name: "The input, as JSON" }));
    await userEvent.paste('{"__proto__": "HQ", "site": "HQ"}');
    await userEvent.click(within(again).getByRole("button", { name: "Add the schedule" }));
    await vi.waitFor(() => expect(sent.filter((r) => r.method === "POST")).toHaveLength(2));
    const second = (sent.filter((r) => r.method === "POST")[1]!.body as { input: object }).input;
    expect(Object.keys(second)).toEqual(["__proto__", "site"]);
  });

  it("replaces an edited one's input whole, never showing the stored one", async () => {
    const sent = api([SCHEDULE], { "PATCH /api/v1/t/t1/schedules/s1": () => json(SCHEDULE) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Every day at 07:00" }));
    const form = within(section()).getByRole("form", { name: 'Editing "Every day at 07:00"' });
    await userEvent.click(within(form).getByRole("button", { name: "Replace the input…" }));
    expect(form.textContent).toContain("The stored input isn't shown back: what you enter here replaces it whole.");
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Site (required)" }).value).toBe("");
    await userEvent.type(within(form).getByRole("textbox", { name: "Site (required)" }), "Lab");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ input: { site: "Lab" } }));
  });

  it("turns one off at once, and deletes one after asking", async () => {
    const sent = api([SCHEDULE], {
      "PATCH /api/v1/t/t1/schedules/s1": () => json({ ...SCHEDULE, enabled: false }),
      "DELETE /api/v1/t/t1/schedules/s1": () => new Response(null, { status: 204 }),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("switch", { name: "Every day at 07:00" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ enabled: false }));
    await userEvent.click(within(section()).getByRole("button", { name: "Edit Every day at 07:00" }));
    await userEvent.click(within(section()).getByRole("button", { name: "Delete the schedule…" }));
    const ask = screen.getByRole("dialog", { name: 'Delete the schedule "Every day at 07:00"?' });
    expect(ask.textContent).toContain("Runs it started stay in the run history.");
    await userEvent.click(within(ask).getByRole("button", { name: "Delete the schedule" }));
    await vi.waitFor(() => expect(sent.some((r) => r.method === "DELETE" && r.path === "/api/v1/t/t1/schedules/s1")).toBe(true));
  });

  it("says which live schedules the draft would break, from the server's check", async () => {
    api([SCHEDULE]);
    const check: Validation = {
      draft_revision: 1, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] }, conditional_steps: [],
      schedule_breaks: [{ schedule_id: "s1", reasons: ["`site` is required now."], more: false }],
    };  // prettier-ignore
    await showPanel({ check });
    await vi.waitFor(() =>
      expect(section().textContent).toContain(
        "Publishing this draft would make it fail each time: its stored input doesn't fit the draft's input (`site` is required now). After publishing, replace its input; or change the draft's input back.",
      ),
    );
  });

  it("shows a viewer each schedule without its controls", async () => {
    api([SCHEDULE]);
    await showPanel({ editable: false, manage: false, viewer: true });
    await within(section()).findByText("Every day at 07:00");
    expect(within(section()).queryByRole("switch")).toBeNull();
    expect(within(section()).queryByRole("button", { name: "＋ Schedule" })).toBeNull();
    expect(section().textContent).toContain("On");
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/triggers`

Expected: FAIL: `Test Files  1 failed | 1 passed (2)`, `Tests  22 failed | 21 passed (43)`. The failing tests are this
task's new and changed ones: `says each one in words, and what its sync proves, as the Schedules board does`, `can't add
one before a first publish, nor to a workflow that takes a CSV file, and says why`, `says a workflow that takes a CSV
file can't run on a schedule`, `adds one on the published version's form, checking the input before anything is sent`,
`shows each refusal of its timing at the field it names`, `edits one: its stored input kept unless replaced whole, and
only what changed sent`, `keeps a timing no preset says, 'Every 90 seconds', as it is, and sends the mode alone when
only it changes`, `keeps a timing no preset says, 'Every 72 hours', as it is, and sends the mode alone when only it
changes`, `takes a list, an object or a value of several types as JSON, keeps a choice's type, and leaves out what isn't
given`, `takes the whole input as JSON when the form can't show it field by field ('allOf')`, `takes the whole input as
JSON when the form can't show it field by field ('a $ref')`, `takes the whole input as JSON on request, beside its
fields`, `waits for the version's input before taking any, then starts its JSON from the fields' defaults`, `carries
what's entered between the fields and the JSON, and keeps JSON no field can show`, `keeps an empty text in the JSON,
required or not: a field's empty control means not given`, `keeps text with a line break in the JSON, and moves spaces
and tabs to a field as they are`, `refuses JSON whose numbers parsing would change, in the whole input and in a field`,
`keeps a key named __proto__, typed in the JSON or as a field's name`, `replaces an edited one's input whole, never
showing the stored one`, `turns one off at once, and deletes one after asking`, and 2 more.

- [ ] **Step 3: Write the code**

**In** `frontend/src/components/Field.tsx`, **replace**:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";

// A control's boundary is 3:1 against its surface (line-control, WCAG 1.4.11); red when its value is refused.
````

**with**:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

// A control's boundary is 3:1 against its surface (line-control, WCAG 1.4.11); red when its value is refused.
````

**In** `frontend/src/components/Field.tsx`, **replace**:

````tsx
      </select>
    )} />
  );
}
````

**with**:

````tsx
      </select>
    )} />
  );
}

/** Text of several lines, like JSON: a fixed-width face, its height from `rows`. */
export function TextArea({ label, hint, error, ...area }: TextareaHTMLAttributes<HTMLTextAreaElement> & Labelled) {
  return (
    <Frame label={label} hint={hint} error={error} control={({ id, describedBy, className }) => (
      <textarea id={id} {...area} aria-invalid={!!error} aria-describedby={describedBy} className={`${className} py-2 font-mono text-small`} />
    )} />
  );
}
````

**Create** `frontend/src/routes/editor/triggers/ScheduleForm.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// A schedule's form (4c-3b; the ScheduleForm, ScheduleWhen and NarrowForms boards): when it runs (a preset, or a cron),
// its time zone where one applies, its mode, how late a missed firing still starts, and its input on the published
// version's form. Editing one never shows its stored input back: it's kept, or replaced whole. Its timing is sent only
// when changed here, and one no preset says is kept as it is (the review of revision 1). The input is entered whole, as
// JSON, where its rules are more than the form's fields show, or on request (the review of revision 2): how is settled
// before anything is typed, what's typed goes with it from one way to the other, JSON a parse would change is refused,
// and every key is kept as typed (the review of revision 3). Saved at once; the API checks the timing and the input
// (each refusal said at its field).
import { useMutation, useQuery } from "@tanstack/react-query";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { Field, Select, TextArea } from "../../../components/Field";
import { announce } from "../../../lib/announce";
import { ApiError } from "../../../lib/client";
import { CATCHUP, TIMING_WORDS, blankWhen, intervalWords, timingOf, whenOf, zones, type Preset, type When } from "../../../lib/timing";
import { parseJson } from "../../../lib/config";
import { asGraph } from "../../../lib/graph";
import { inputOf } from "../../../lib/input";
import { createSchedule, scheduleTitle, updateSchedule, versionQuery, type Schedule, type StartField, type StartForm } from "../../../lib/triggers";
import { isObject } from "../../../lib/schemaForm";
import { parseNumber } from "../../../lib/unapplied";
import { useTriggers } from "./context";

const PRESETS: { value: Preset; label: string }[] = [
  { value: "minutes", label: "Every N minutes" },
  { value: "hours", label: "Every N hours" },
  { value: "daily", label: "Every day at" },
  { value: "weekdays", label: "Weekdays at" },
  { value: "custom", label: "Custom (cron)" },
];
const BROWSER_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;

/** Where the API's refusal of a timing field shows in the form. */
function fieldOfProblem(field: string, preset: Preset): keyof When | "zone" | "catchup" | "when" {
  if (field === "time_zone") return "zone";
  if (field === "catchup_window_s") return "catchup";
  if (field === "every_s") return "every";
  if (field === "offset_s") return preset === "hours" ? "first" : "past";
  return preset === "custom" ? "cron" : preset === "daily" || preset === "weekdays" ? "time" : "when";
}

/** How a field of the input is entered: one of its values, as its type says, or JSON for what the simple controls can't
 * hold (a list, an object, several types or none), each value's type kept (the review of revision 1). */
type Entry = "choice" | "yesno" | "whole" | "number" | "text" | "json";

function entryOf(f: StartField): Entry {
  if (Array.isArray(f.enum) && !f.enum_masked) return "choice";
  const type: unknown = f.type;
  return type === "boolean" ? "yesno" : type === "integer" ? "whole" : type === "number" ? "number" : type === "string" ? "text" : "json";
}

const JSON_HINT = 'As JSON, like ["ap-1"] or {"site": "HQ"}; text in quotes.';

const nameOf = (f: StartField) => f.title ?? f.name;

/** What's typed for one field of the input, as the input holds it: nothing given is left out. A choice's option is its
 * value as JSON, so a number stays a number; JSON a parse would change (a number too large, a whole one past 2^53) is
 * refused, as the draft's is. */
function valueOf(f: StartField, typed: string | undefined): { value: unknown } | { problem: string } {
  if (typed === undefined || typed === "") return { value: undefined };
  const entry = entryOf(f);
  if (entry === "choice") return { value: JSON.parse(typed) as unknown };
  if (entry === "yesno") return { value: typed === "true" };
  if (entry === "whole" || entry === "number") {
    const parsed = parseNumber(typed, entry === "whole");
    return "problem" in parsed ? parsed : { value: parsed.value };
  }
  if (entry === "text") return { value: typed };
  return parseJson(typed);
}

/** A value as its field's control shows it, or null where that control can't show it as it is: a line break, which a
 * one-line control drops, or text that doesn't read back as the value (an empty text is "not given"). The reviews of
 * revisions 4 and 5. */
function shownOf(f: StartField, v: unknown): string | null {
  const shown = textOf(f, v);
  if (shown === null || /[\r\n]/.test(shown)) return null;
  const read = valueOf(f, shown);
  return "value" in read && JSON.stringify(read.value) === JSON.stringify(v) ? shown : null;
}

/** A value as its field's control would hold it, before it's read back. */
function textOf(f: StartField, v: unknown): string | null {
  switch (entryOf(f)) {
    case "choice":
      return (f.enum ?? []).some((x) => JSON.stringify(x) === JSON.stringify(v)) ? JSON.stringify(v) : null;
    case "yesno":
      return typeof v === "boolean" ? String(v) : null;
    case "whole":
      return typeof v === "number" && Number.isInteger(v) ? String(v) : null;
    case "number":
      return typeof v === "number" ? String(v) : null;
    case "text":
      return typeof v === "string" ? v : null;
    case "json":
      return JSON.stringify(v);
  }
}

/** Where a field's problem is kept among the form's: apart from its own (`when`, `input`…), whatever the field's name. */
const fieldKey = (name: string) => `field:${name}`;

/** The fields' values as one input, each by its name as a key of its own (a field may be named `__proto__`), or each
 * field's problem; `required` holds a required field to being given. */
function fromFields(form: StartForm, values: ReadonlyMap<string, string>, required: boolean): { input: Record<string, unknown> } | { problems: Record<string, string> } {
  const entries: [string, unknown][] = [];
  const problems: [string, string][] = [];
  for (const f of form.fields) {
    const read = valueOf(f, values.get(f.name));
    if ("problem" in read) problems.push([fieldKey(f.name), read.problem]);
    else if (read.value !== undefined) entries.push([f.name, read.value]);
    else if (required && f.required) problems.push([fieldKey(f.name), `${nameOf(f)} is required.`]);
  }
  return problems.length > 0 ? { problems: Object.fromEntries(problems) } : { input: Object.fromEntries(entries) };
}

const listed = (items: string[]) => (items.length < 2 ? (items[0] ?? "") : `${items.slice(0, -1).join(", ")} and ${items.at(-1)!}`);

/** One field of the published version's form: never prefilled with what a sensitive field hides. */
function InputControl({ f, value, error, onChange }: { f: StartField; value: string | undefined; error?: string; onChange: (v: string) => void }) {
  const label = `${nameOf(f)}${f.required ? " (required)" : ""}`;
  const entry = entryOf(f);
  const hint = entry === "json" ? [f.description, JSON_HINT].filter(Boolean).join(" ") : (f.description ?? undefined);
  if (entry === "yesno") {
    return (
      <Select label={label} hint={hint} error={error} value={value === undefined ? "" : String(value)} onChange={(e) => onChange(e.target.value)}>
        <option value="">Not given</option>
        <option value="true">Yes</option>
        <option value="false">No</option>
      </Select>
    );
  }
  if (entry === "choice") {
    return (
      <Select label={label} hint={hint} error={error} value={value ?? ""} onChange={(e) => onChange(e.target.value)}>
        <option value="">Not given</option>
        {(f.enum ?? []).map((v) => <option key={JSON.stringify(v)} value={JSON.stringify(v)}>{typeof v === "string" ? v : JSON.stringify(v)}</option>)}
      </Select>
    );  // prettier-ignore
  }
  if (entry === "json" && !f.sensitive) {
    return <TextArea label={label} hint={hint} error={error} value={value ?? ""} rows={3} spellCheck={false} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <Field
      label={label} hint={hint} error={error} type={f.sensitive ? "password" : "text"} autoComplete="off" spellCheck={entry === "json" ? false : undefined}
      inputMode={entry === "whole" || entry === "number" ? "decimal" : undefined} value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
    />
  );  // prettier-ignore
}

/** The published version's form, with the values it starts from: a default its control shows, where one isn't hidden. */
const startValues = (form: StartForm): ReadonlyMap<string, string> =>
  new Map(form.fields.flatMap((f) => {
    const shown = f.sensitive || f.default === undefined || f.default === null ? null : shownOf(f, f.default);
    return shown === null ? [] : [[f.name, shown] as const];
  }));  // prettier-ignore

/** What a start form's fields show of an input (apps/forms.py reads its root's properties and required): any other
 * keyword at its root (allOf, $ref, if, …) holds rules no field shows, and the input is then entered whole, as JSON. */
const SHOWN = new Set(["type", "properties", "required", "title", "description", "additionalProperties", "$schema", "$defs", "$comment", "examples"]);
const fieldsShow = (schema: Record<string, unknown>) => Object.keys(schema).every((k) => SHOWN.has(k) || k.startsWith("x-"));

/** The whole input typed as JSON: an object, its keys as parsed, or why it isn't one (JSON a parse would change, as a
 * field's); nothing typed is an empty input. */
function wholeOf(text: string): { value: Record<string, unknown> } | { problem: string } {
  const read = parseJson(text);
  if ("problem" in read) return read;
  if (read.value === undefined) return { value: {} };
  return isObject(read.value) ? { value: read.value } : { problem: 'An object, like {"site": "HQ"}.' };
}

/** Whether two "When"s say the same, field for field. */
const sameWhen = (a: When, b: When) => (Object.keys(a) as (keyof When)[]).every((k) => a[k] === b[k]);

function Group({ legend, children }: { legend: string; children: ReactNode }) {
  return (
    <fieldset className="flex min-w-0 flex-col gap-3">
      <legend className="mb-1 text-small font-semibold">{legend}</legend>
      {children}
    </fieldset>
  );
}

export function ScheduleForm({ schedule, form, activeNumber, onDone, onDelete }: {
  schedule: Schedule | null; form: StartForm; activeNumber: number; onDone: (saved?: Schedule) => void; onDelete?: () => void;
}) {  // prettier-ignore
  const t = useTriggers();
  const id = useId();
  const editing = schedule !== null;
  const [opened] = useState<When>(() => (schedule ? whenOf(schedule) : blankWhen("daily"))); // the When it opened with
  const [when, setWhen] = useState<When>(opened);
  const [zone, setZone] = useState(schedule?.time_zone ?? BROWSER_ZONE);
  const [mode, setMode] = useState<"live" | "simulate">(schedule?.mode ?? "live");
  const [catchup, setCatchup] = useState(schedule?.catchup_window_s ?? 600);
  const [replacing, setReplacing] = useState(!editing);
  const [values, setValues] = useState<ReadonlyMap<string, string>>(() => (editing ? new Map() : startValues(form)));
  const version = useQuery(versionQuery(t.tenantId, t.workflowId, form.version_id));
  const resolving = version.isPending; // the version's input decides how it's entered: nothing is taken before
  const whole = version.data !== undefined && !fieldsShow(inputOf(asGraph(version.data.graph)));
  const [asJson, setAsJson] = useState(false); // the whole input as JSON, chosen here
  const json = whole || asJson;
  const [jsonText, setJsonText] = useState<string | null>(null); // until typed, the fields' values
  const seeded = () => {
    const made = fromFields(form, values, false);
    return "input" in made && Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "";
  };
  const shownJson = jsonText ?? seeded();
  /** What's in the fields, as JSON; a field whose value doesn't read keeps the form where it is, saying why. */
  const toJson = () => {
    const made = fromFields(form, values, false);
    if ("problems" in made) return setErrors(made.problems);
    setErrors({});
    setJsonText(Object.keys(made.input).length > 0 ? JSON.stringify(made.input, null, 2) : "");
    setAsJson(true);
  };
  /** What's in the JSON, in the fields; JSON no field shows as written stays JSON, saying why. */
  const toFields = () => {
    const read = wholeOf(shownJson);
    if ("problem" in read) return setErrors({ input: read.problem });
    const byName = new Map(form.fields.map((f) => [f.name, f]));
    const shown = new Map<string, string>();
    const left: string[] = [];
    for (const [k, v] of Object.entries(read.value)) {
      const f = byName.get(k);
      const s = f ? shownOf(f, v) : null;
      if (s === null) left.push(k);
      else shown.set(k, s);
    }
    if (left.length > 0) return setErrors({ input: `No field here shows ${listed(left)} as written: it stays as JSON.` });
    setErrors({});
    setValues(shown);
    setJsonText(null);
    setAsJson(false);
  };
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refused, setRefused] = useState<string | null>(null);
  // Its timing is sent only when changed here: one the form reads but wouldn't write the same stays as it is.
  const keep = editing && (when.preset === "kept" || sameWhen(when, opened));
  const cron = when.preset === "kept" ? schedule?.cron != null : when.preset === "daily" || when.preset === "weekdays" || when.preset === "custom";
  const presets = opened.preset === "kept" && schedule ? [{ value: "kept" as const, label: `${scheduleTitle(schedule)}, as it is` }, ...PRESETS] : PRESETS;
  const offered = zones();
  const set = (patch: Partial<When>) => setWhen((w) => ({ ...w, ...patch }));

  const save = useMutation({
    mutationFn: async () => {
      setErrors({});
      setRefused(null);
      const made = keep ? null : timingOf(when);
      if (made && "problem" in made) throw new Local({ [made.field]: made.problem });
      let input: Record<string, unknown> = {};
      if (replacing && json) {
        const read = wholeOf(shownJson);
        if ("problem" in read) throw new Local({ input: read.problem });
        input = read.value; // as parsed: never copied key by key, which would drop `__proto__`
      } else if (replacing) {
        const made = fromFields(form, values, true);
        if ("problems" in made) throw new Local(made.problems);
        input = made.input;
      }
      const timing = made?.timing ?? null;
      const time_zone = (timing ? timing.cron !== null : schedule?.cron != null) ? zone.trim() : "UTC";
      if (!editing) {
        if (!timing) throw new Local({ when: TIMING_WORDS.timing_missing! });
        return createSchedule(t.tenantId, t.workflowId, { ...timing, time_zone, catchup_window_s: catchup, mode, input });
      }
      const changed = (k: keyof Schedule, v: unknown) => schedule[k] !== v;
      return updateSchedule(t.tenantId, schedule.id, {
        ...(timing && (changed("cron", timing.cron) || changed("every_s", timing.every_s) || changed("offset_s", timing.offset_s)) ? timing : {}),
        ...(changed("time_zone", time_zone) ? { time_zone } : {}),
        ...(changed("catchup_window_s", catchup) ? { catchup_window_s: catchup } : {}),
        ...(changed("mode", mode) ? { mode } : {}),
        ...(replacing ? { input } : {}),
      });
    },
    onSuccess: (saved) => {
      announce(editing ? `Saved ${scheduleTitle(saved)}` : `Added the schedule ${scheduleTitle(saved)}`);
      onDone(saved);
    },
    onError: (e) => {
      if (e instanceof Local) return setErrors(e.fields);
      if (e instanceof ApiError && e.code === "schedule_invalid") {
        const problems = (e.body as { problems?: { field: string; code: string }[] }).problems ?? [];
        return setErrors(Object.fromEntries(problems.map((p) => [fieldOfProblem(p.field, when.preset), TIMING_WORDS[p.code] ?? "The scheduler can't take this."])));
      }
      if (e instanceof ApiError && e.code === "input_invalid") {
        const messages = (e.body as { messages?: string[] }).messages ?? [];
        return setRefused(`Version ${activeNumber}'s input refuses this: ${messages.join(" ") || "it doesn't fit."}`);
      }
      if (e instanceof ApiError && e.code === "csv_required") return setRefused("It takes a CSV file: its rows come from an upload, so it can't run on a schedule.");
      if (e instanceof ApiError && e.code === "not_active") return setRefused("Nothing is published any more: publish a version to schedule it.");
      setRefused(editing ? "The schedule couldn't be saved. Try again." : "The schedule couldn't be added. Try again.");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    save.mutate();
  }

  const interval = intervalWords(when);
  return (
    <form
      onSubmit={submit} aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onDone();
        }
      }}
      className="flex flex-col gap-4 rounded-lg border border-line-strong p-3"
    >
      <h4 id={`${id}-title`} className="text-body font-semibold">{editing ? `Editing "${scheduleTitle(schedule)}"` : "New schedule"}</h4>
      <Select label="When" value={when.preset} error={errors.when} onChange={(e) => set({ preset: e.target.value as Preset })} autoFocus>
        {presets.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
      </Select>
      {when.preset === "kept" && <p className="text-small text-muted">Set outside this form, it&apos;s kept as it is: choosing another When replaces it.</p>}
      {(when.preset === "minutes" || when.preset === "hours") && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Every" inputMode="numeric" value={when.every} error={errors.every} onChange={(e) => set({ every: e.target.value })} />
          {when.preset === "minutes" ? (
            <Field label="Past the hour" inputMode="numeric" value={when.past} error={errors.past} onChange={(e) => set({ past: e.target.value })} />
          ) : (
            <Field label="First, in UTC" type="time" value={when.first} error={errors.first} onChange={(e) => set({ first: e.target.value })} />
          )}
        </div>
      )}
      {interval && <p className="text-small text-muted">{interval}</p>}
      {(when.preset === "daily" || when.preset === "weekdays") && (
        <Field
          label="Time" type="time" value={when.time} error={errors.time}
          hint={editing && schedule.cron ? `Its cron, ${schedule.cron}, read back as a preset. A cron no preset says opens as Custom.` : undefined}
          onChange={(e) => set({ time: e.target.value })}
        />
      )}
      {when.preset === "custom" && (
        <Field
          label="Cron" value={when.cron} spellCheck={false} autoCapitalize="off" error={errors.cron}
          hint="Five fields: minute, hour, day of the month, month, day of the week (0 or 7 is Sunday). Ranges, lists and steps work, like 1-5, 1,15 or */10, and names like MON or JAN."
          onChange={(e) => set({ cron: e.target.value })}
        />
      )}
      {cron && (
        <>
          <Field
            label="Time zone" list={`${id}-zones`} value={zone} error={errors.zone} spellCheck={false} autoCapitalize="off"
            hint={editing ? 'Type to search the zones, like "york" or "UTC".' : "Your browser's zone to start with. Each schedule keeps its own."}
            onChange={(e) => setZone(e.target.value)}
          />
          <datalist id={`${id}-zones`}>{offered.map((z) => <option key={z} value={z} />)}</datalist>
        </>
      )}
      <Group legend="Mode">
        {(["live", "simulate"] as const).map((m) => (
          <label key={m} className="flex min-h-6 items-center gap-2 text-small">
            <input type="radio" name={`${id}-mode`} checked={mode === m} onChange={() => setMode(m)} className="size-[16px] accent-accent" />
            {m === "live" ? "Live" : "Simulate"}
          </label>
        ))}
        <p className="text-small text-muted">Simulate: steps that change other systems send nothing.</p>
      </Group>
      <Select label="If a firing is missed, still start it within" value={String(catchup)} error={errors.catchup} onChange={(e) => setCatchup(Number(e.target.value))}>
        {CATCHUP.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
        {!CATCHUP.some((c) => c.value === catchup) && <option value={catchup}>{catchup} seconds</option>}
      </Select>
      <Group legend={replacing ? (editing ? `Input · replacing it with version ${activeNumber}'s form` : `Input · version ${activeNumber}'s form`) : "Input"}>
        {!replacing ? (
          <>
            <p className="text-small text-muted">Set when it was created; not shown back.</p>
            <Button size="sm" className="self-start" onClick={() => setReplacing(true)}>Replace the input…</Button>
          </>
        ) : (
          <>
            {resolving ? (
              <p className="text-small text-muted">Loading version {activeNumber}&apos;s input…</p>
            ) : json ? (
              <>
                {whole && <p className="text-small text-muted">Version {activeNumber}&apos;s input has rules this form can&apos;t show field by field: it&apos;s entered as JSON.</p>}
                <TextArea
                  label="The input, as JSON" hint='An object, like {"site": "HQ"}. Shown as typed, a sensitive value too.' error={errors.input}
                  value={shownJson} rows={6} spellCheck={false} onChange={(e) => setJsonText(e.target.value)}
                />
                {!whole && <Button size="sm" className="self-start" onClick={toFields}>Enter it field by field</Button>}
              </>
            ) : (
              <>
                {version.isError && <p className="text-small text-muted">Version {activeNumber}&apos;s input couldn&apos;t be loaded: its fields are shown, and Enter it as JSON takes any rule they don&apos;t.</p>}
                {form.fields.length === 0 && <p className="text-small text-muted">Version {activeNumber} takes no input.</p>}
                {form.fields.map((f) => (
                  <InputControl
                    key={f.name} f={f} value={values.get(f.name)} error={errors[fieldKey(f.name)]}
                    onChange={(v) => setValues((m) => new Map(m).set(f.name, v))}
                  />
                ))}
                <Button size="sm" className="self-start" onClick={toJson}>Enter it as JSON</Button>
              </>
            )}
            <p className="text-small text-muted">
              {editing
                ? "The stored input isn't shown back: what you enter here replaces it whole."
                : "Kept with the schedule and checked against the published version's input each time it fires. It isn't shown back afterwards."}
            </p>
            {editing && <Button size="sm" className="self-start" onClick={() => setReplacing(false)}>Keep the stored input</Button>}
          </>
        )}
      </Group>
      {refused && <p role="alert" className="text-small text-danger">{refused}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" variant="primary" disabled={save.isPending || (replacing && resolving)}>{editing ? "Save" : "Add the schedule"}</Button>
        <Button size="sm" onClick={() => onDone()}>Cancel</Button>
        {editing && onDelete && <Button size="sm" variant="danger-outline" onClick={onDelete}>Delete the schedule…</Button>}
      </div>
      {editing && (
        <p className="text-small text-muted">
          Saved at once: the mode and input apply from its next firing. The scheduler takes a new time on its own; until that&apos;s confirmed, the previous time may still fire.
        </p>
      )}
    </form>
  );  // prettier-ignore
}

/** What the browser finds before anything is sent, by field. */
class Local extends Error {
  constructor(public fields: Record<string, string>) {
    super("not sent");
  }
}
````

**Create** `frontend/src/routes/editor/triggers/SchedulesSection.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// A workflow's schedules (4c-3b; the Schedules and Rules boards): live rows on the published version, saved at once,
// outside undo. Each says its timing in words, its zone where one applies, its mode, and what its sync proves; turning
// one off or deleting it stops new runs at once. One can't be added before a first publish, nor to a workflow that
// takes a CSV file (`409 csv_required`). What the draft would break, the server's check says (4c-3a ruling 7).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { LoadError } from "../../../components/LoadError";
import { Switch } from "../../../components/Switch";
import { announce } from "../../../lib/announce";
import {
  deleteSchedule, missesNote, scheduleMeta, scheduleNote, schedulesQuery, scheduleTitle, startFormQuery, updateSchedule,
  type Schedule,
} from "../../../lib/triggers";  // prettier-ignore
import { useTriggers } from "./context";
import { Section } from "./parts";
import { ScheduleForm } from "./ScheduleForm";

const LIVE =
  "A change is saved at once. Turning a schedule off, or deleting it, stops new runs at once; turning it on lets its firings through at once. Its mode and input apply from its next firing. The scheduler's timer follows on its own, usually within seconds: until that's confirmed, the previous time may still fire, and a new schedule may already fire.";

/** What validate found a schedule's stored input wouldn't fit in the draft (4c-3a ruling 7), in a sentence. */
function breakWords(reasons: string[], more: boolean): string {
  const said = reasons.map((r) => r.replace(/\.$/, "")).join("; ");
  return `Publishing this draft would make it fail each time: its stored input doesn't fit the draft's input (${said}${more ? "; and more" : ""}). After publishing, replace its input; or change the draft's input back.`;
}

export function SchedulesSection() {
  const t = useTriggers();
  const qc = useQueryClient();
  const schedules = useQuery(schedulesQuery(t.tenantId, t.workflowId));
  // The published version's form: what a schedule's input is entered on, and whether it takes a CSV file.
  const form = useQuery({ ...startFormQuery(t.tenantId, t.workflowId), enabled: t.manage && t.activeNumber !== null });
  const [open, setOpen] = useState<string | null>(null); // "new", or the id of the one being edited (a UUID)
  const [deleting, setDeleting] = useState<Schedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const adder = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["workflows", t.tenantId] });
    return qc.invalidateQueries({ queryKey: ["schedules", t.tenantId, t.workflowId] });
  };
  const toggle = useMutation({
    mutationFn: (s: { id: string; title: string; enabled: boolean }) => updateSchedule(t.tenantId, s.id, { enabled: s.enabled }),
    onMutate: () => setError(null),
    onSuccess: (_, s) => announce(`${s.title}: ${s.enabled ? "on: its firings start runs again" : "off: it starts no new runs"}`),
    onError: (_, s) => setError(`${s.title} couldn't be switched ${s.enabled ? "on" : "off"}. Try again.`),
    onSettled: refresh,
  });
  const remove = useMutation({
    mutationFn: (s: Schedule) => deleteSchedule(t.tenantId, s.id),
    onMutate: () => setError(null),
    onSuccess: async (_, s) => {
      setDeleting(null);
      setOpen(null);
      announce(`Deleted the schedule ${scheduleTitle(s)}`);
      await refresh();
      requestAnimationFrame(() => heading.current?.focus());
    },
    onError: (_, s) => {
      setDeleting(null);
      setError(`${scheduleTitle(s)} couldn't be deleted. Try again.`);
    },
  });
  const published = t.activeNumber !== null;
  const csv = form.data?.csv != null;
  const why = !published
    ? "A schedule runs the published version: publish a first version to add one."
    : csv ? "It takes a CSV file: its rows come from an upload, so it can't run on a schedule." : null;  // prettier-ignore
  const list = schedules.data?.schedules ?? [];
  const breaks = new Map((t.check?.schedule_breaks ?? []).map((b) => [b.schedule_id, b]));
  const close = (focusAdd = true) => {
    setOpen(null);
    if (focusAdd) requestAnimationFrame(() => adder.current?.focus());
  };
  return (
    <Section id="triggers-schedules" title="Schedules" heading={heading} note={published ? `Live · on version ${t.activeNumber}` : "Live"}>
      {list.length > 0 && <p className="text-small text-muted">{LIVE}</p>}
      {error && <p role="alert" className="text-small text-danger">{error}</p>}
      {schedules.isError && <LoadError what="The schedules" />}
      {schedules.isSuccess && list.length === 0 && <p className="text-small text-muted">No schedule starts this workflow.</p>}
      <ul className="flex flex-col">
        {list.map((s) => {
          const title = scheduleTitle(s);
          const note = scheduleNote(s);
          const missed = missesNote(s);
          const broken = breaks.get(s.id);
          return (
            <li key={s.id} className="flex flex-col gap-1.5 border-t border-line py-2.5 first:border-t-0">
              {open === s.id && form.data ? (
                <ScheduleForm
                  schedule={s} form={form.data} activeNumber={t.activeNumber!}
                  onDone={(saved) => {
                    close(false);
                    if (saved) void refresh();
                  }}
                  onDelete={() => setDeleting(s)}
                />
              ) : (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 text-body font-medium">{title}</span>
                    <span className="flex items-center gap-2">
                      {t.manage ? (
                        <>
                          <Switch checked={s.enabled} label={title} disabled={toggle.isPending} onCheckedChange={(enabled) => toggle.mutate({ id: s.id, title, enabled })} />
                          <Button size="sm" aria-label={`Edit ${title}`} disabled={!form.data} onClick={() => setOpen(s.id)}>Edit</Button>
                        </>
                      ) : (
                        <span className="text-small">{s.enabled ? "On" : "Off"}</span>
                      )}
                    </span>
                  </div>
                  <span className="text-small text-muted">{scheduleMeta(s)}</span>
                  {note && <span className={`text-small ${s.sync_error ? "text-danger" : "text-ink"}`}>{note}</span>}
                  {missed && <span className="text-small text-warn-ink">{missed}</span>}
                  {broken && (
                    <span className="text-small text-warn-ink">
                      {breakWords(broken.reasons, broken.more)} The check is the server&apos;s: it reads the schedule&apos;s stored input, which nobody sees.
                    </span>
                  )}
                </>
              )}
            </li>
          );
        })}
      </ul>
      {open === "new" && form.data ? (
        <ScheduleForm schedule={null} form={form.data} activeNumber={t.activeNumber!} onDone={(saved) => {
          close();
          if (saved) void refresh();
        }} />
      ) : t.manage ? (
        <div className="flex flex-col gap-1">
          <Button ref={adder} size="sm" className="self-start" disabled={why !== null || !form.data} aria-describedby={why ? "triggers-no-schedule" : undefined} onClick={() => setOpen("new")}>
            ＋ Schedule
          </Button>
          {why && <p id="triggers-no-schedule" className="text-small text-muted">{why}</p>}
          {published && form.isError && <p className="text-small text-danger">The published version&apos;s form couldn&apos;t be read, so a schedule can&apos;t be added now.</p>}
        </div>
      ) : null}
      <ConfirmDialog
        open={deleting !== null} title={deleting ? `Delete the schedule "${scheduleTitle(deleting)}"?` : ""} confirmLabel="Delete the schedule"
        busy={remove.isPending} onConfirm={() => deleting && remove.mutate(deleting)} onCancel={() => setDeleting(null)}
      >
        The runs it would start won&apos;t be, from now on. Runs it started stay in the run history.
      </ConfirmDialog>
    </Section>
  );  // prettier-ignore
}
````

**In** `frontend/src/routes/editor/triggers/TriggersPanel.tsx`, **replace**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The Triggers panel (4c-3b; the mockups' Main, ReadOnly and Narrow boards): what starts the workflow, opened from the
// start card. Its input is the draft's, saved with it and used once published (Task 9 adds its live schedules, Task 11
// its webhooks). A viewer or an operator sees it all, read only.
import { useEffect, useRef } from "react";
import { Button } from "../../../components/Button";
````

**with**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The Triggers panel (4c-3b; the mockups' Main, ReadOnly and Narrow boards): what starts the workflow, opened from the
// start card. Its input is the draft's, saved with it and used once published; its schedules are live, saved at once
// on the published version, outside undo (Task 11 adds its webhooks). A viewer or an operator sees it all, read only.
import { useEffect, useRef } from "react";
import { Button } from "../../../components/Button";
````

**In** `frontend/src/routes/editor/triggers/TriggersPanel.tsx`, **replace**:

````tsx
import { TriggersContext, type Triggers } from "./context";
import { InputSection, type FocusAt } from "./InputSection";

export function TriggersPanel({ value, focusAt, onClose }: { value: Triggers; focusAt: FocusAt; onClose: () => void }) {
````

**with**:

````tsx
import { TriggersContext, type Triggers } from "./context";
import { InputSection, type FocusAt } from "./InputSection";
import { SchedulesSection } from "./SchedulesSection";

export function TriggersPanel({ value, focusAt, onClose }: { value: Triggers; focusAt: FocusAt; onClose: () => void }) {
````

**In** `frontend/src/routes/editor/triggers/TriggersPanel.tsx`, **replace**:

````tsx
        {value.viewer && <p className="text-small text-muted">You can see this workflow&apos;s triggers; changing them needs the editor role.</p>}
        <InputSection focusAt={focusAt} />
      </aside>
    </TriggersContext.Provider>
````

**with**:

````tsx
        {value.viewer && <p className="text-small text-muted">You can see this workflow&apos;s triggers; changing them needs the editor role.</p>}
        <InputSection focusAt={focusAt} />
        <SchedulesSection />
      </aside>
    </TriggersContext.Provider>
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/triggers`

Expected: PASS: `Test Files  2 passed (2)`, `Tests  43 passed (43)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Field.tsx \
  frontend/src/routes/editor/triggers/ScheduleForm.tsx \
  frontend/src/routes/editor/triggers/SchedulesSection.test.tsx \
  frontend/src/routes/editor/triggers/SchedulesSection.tsx \
  frontend/src/routes/editor/triggers/TriggersPanel.tsx
git commit -m "feat(editor): a workflow's live schedules, in words, and their form (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Settings → Webhook endpoints

The tenant's endpoints (ruling 9): a tab, a page and a palette item; each endpoint's sender, proof, workflows, waiting
events, state and path, with its details; made (a Mist endpoint from its name; another sender's with its proof, events
and ids, fixed once made), its secret shown once; edited, turned off, rotated once asked. A viewer reads it all.

**Files:**
- Modify: `frontend/src/components/CommandPalette.test.tsx`
- Modify: `frontend/src/components/CommandPalette.tsx`
- Modify: `frontend/src/router.test.tsx`
- Modify: `frontend/src/router.tsx`
- Create: `frontend/src/routes/EndpointForm.tsx`
- Modify: `frontend/src/routes/Settings.tsx`
- Create: `frontend/src/routes/WebhookEndpoints.test.tsx`
- Create: `frontend/src/routes/WebhookEndpoints.tsx`

**Interfaces:**
- Consumes: Tasks 3 and 6.
- Produces: `WebhookEndpointsPage({ tenantId })`, `NewEndpoint`, `EditEndpoint`; the route
  `/t/$tenantId/settings/webhooks`, its tab and its palette item.

- [ ] **Step 1: Write the failing tests**

**In** `frontend/src/components/CommandPalette.test.tsx`, **replace**:

````tsx
  expect(router.state.location.pathname).toBe("/t/t2/workflows");
});
````

**with**:

````tsx
  expect(router.state.location.pathname).toBe("/t/t2/workflows");
});

it("goes to a tenant's webhook endpoints (4c-3b)", async () => {
  const router = await renderAt("/t/t1/connections");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await userEvent.click(await screen.findByRole("option", { name: "Webhook endpoints" }));
  expect(router.state.location.pathname).toBe("/t/t1/settings/webhooks");
});
````

**In** `frontend/src/router.test.tsx`, **replace**:

````tsx
    if (/^GET \/api\/v1\/t\/t[12]\/(?:connections|members)$/.test(key)) return json([]);
    if (/^GET \/api\/v1\/t\/t[12]\/workflows$/.test(key)) return json([]);
    if (key === "GET /api/v1/node-types") return json([]);
    const tenant = TENANTS.find((t) => key === `GET /api/v1/t/${t.id}`);
````

**with**:

````tsx
    if (/^GET \/api\/v1\/t\/t[12]\/(?:connections|members)$/.test(key)) return json([]);
    if (/^GET \/api\/v1\/t\/t[12]\/workflows$/.test(key)) return json([]);
    if (/^GET \/api\/v1\/t\/t[12]\/webhook-endpoints$/.test(key)) return json({ endpoints: [] });
    if (key === "GET /api/v1/trigger-types") return json([]);
    if (key === "GET /api/v1/node-types") return json([]);
    const tenant = TENANTS.find((t) => key === `GET /api/v1/t/${t.id}`);
````

**In** `frontend/src/router.test.tsx`, **replace**:

````tsx
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/login"));
});
````

**with**:

````tsx
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/login"));
});

it("opens Settings → Webhook endpoints from its tab (4c-3b)", async () => {
  const router = showApp("/t/t1/settings/members");
  await userEvent.click(await screen.findByRole("link", { name: "Webhook endpoints" }));
  expect(await screen.findByRole("heading", { name: "Webhook endpoints" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/t/t1/settings/webhooks");
});
````

**Create** `frontend/src/routes/WebhookEndpoints.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Endpoint, EndpointBinding } from "../lib/triggers";
import { ENDPOINT, MIST } from "../test/triggers";
import { fakeApi, json } from "./editor/drawer/harness";
import { WebhookEndpointsPage } from "./WebhookEndpoints";

const TICKETING: Endpoint = {
  ...ENDPOINT, id: "e2", name: "Ticketing", auth: "hmac", trigger: null, signature_header: "x-dewpoint-signature",
  timestamp_header: "x-dewpoint-timestamp", events_pointer: "/items", id_source: "pointer", id_pointer: "/id", pending_events: 2, path: "/hooks/e2",
};  // prettier-ignore
const LAB: Endpoint = { ...ENDPOINT, id: "e3", name: "Mist lab", enabled: false, path: "/hooks/e3" };
const bound = (id: string, workflow: string, topic: string | null): EndpointBinding => ({
  id, endpoint_id: "e1", workflow_id: workflow, enabled: true, filter: topic ? [{ pointer: "/topic", value: topic }] : [],
});  // prettier-ignore

function api(role: string, environment: string | null = "production", more: Record<string, () => Response | Promise<Response>> = {}) {
  return fakeApi({
    "GET /api/v1/t/t1": () => json({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }),
    "GET /api/v1/platform/status": () => json({ environment, production_runs: false }),
    "GET /api/v1/trigger-types": () => json([MIST]),
    "GET /api/v1/t/t1/workflows": () => json([{ id: "w1", name: "AP report" }, { id: "w2", name: "Site audit" }]),
    "GET /api/v1/t/t1/webhook-endpoints": () => json({ endpoints: [ENDPOINT, TICKETING, LAB] }),
    "GET /api/v1/t/t1/webhook-endpoints/e1/bindings": () => json({ bindings: [bound("b1", "w1", "device-events"), bound("b2", "w2", "alarms")] }),
    "GET /api/v1/t/t1/webhook-endpoints/e2/bindings": () => json({ bindings: [] }),
    "GET /api/v1/t/t1/webhook-endpoints/e3/bindings": () => json({ bindings: [] }),
    ...more,
  });
}

async function show() {
  const root = createRootRoute();
  const page = createRoute({
    getParentRoute: () => root,
    path: "/",
    component: () => (
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <WebhookEndpointsPage tenantId="t1" />
      </QueryClientProvider>
    ),
  });
  render(<RouterProvider router={createRouter({ routeTree: root.addChildren([page]), history: createMemoryHistory({ initialEntries: ["/"] }) })} />);
  await screen.findByRole("heading", { name: "Webhook endpoints" });
}
const table = () => screen.getByRole("region", { name: "Webhook endpoints" });
afterEach(() => vi.restoreAllMocks());

describe("Settings → Webhook endpoints", () => {
  it("lists each endpoint's sender, proof, workflows, waiting events, state and path, as the Endpoints board does", async () => {
    api("editor");
    await show();
    await vi.waitFor(() => expect(within(table()).getAllByRole("row")[1]!.textContent).toBe("Mist prodMistA token20/hooks/e1Details"));
    const rows = within(table()).getAllByRole("row").map((r) => r.textContent);
    expect(rows[2]).toBe("TicketingAnother senderAn HMAC signature02/hooks/e2Details");
    expect(within(table()).getByRole("switch", { name: "Mist lab" }).getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText(/An endpoint is turned off rather than deleted/)).toBeTruthy();
  });

  it("says a deployment receives no webhooks yet outside development, and nothing in development", async () => {
    api("editor", "production");
    await show();
    expect(await screen.findByText("This deployment doesn't receive webhooks yet: only development deployments do, for now.")).toBeTruthy();
  });

  it("says nothing of it in a development deployment", async () => {
    api("editor", "development");
    await show();
    await within(table()).findByText("Mist prod");
    expect(screen.queryByText(/doesn't receive webhooks yet/)).toBeNull();
  });

  it("shows an endpoint's details: the workflows it starts, with their topics, and its path", async () => {
    api("editor");
    await show();
    await userEvent.click(await within(table()).findByRole("button", { name: "Mist prod, details" }));
    const details = within(table()).getAllByRole("row")[2]!;
    expect(details.textContent).toContain("Path /hooks/e1, on your Dewpoint webhook address.");
    expect(within(details).getByRole("link", { name: "AP report · device-events" })).toBeTruthy();
    expect(within(details).getByRole("link", { name: "Site audit · alarms" })).toBeTruthy();
  });

  it("makes a Mist endpoint from its name alone, and shows its token once", async () => {
    const sent = api("editor", "development", { "POST /api/v1/t/t1/webhook-endpoints": () => json({ ...ENDPOINT, id: "e9", secret: "tok-123" }, 201) });
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "＋ Endpoint" })); // once the role is known
    const form = screen.getByRole("form", { name: "New endpoint" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Mist prod");
    expect(within(form).getByRole<HTMLInputElement>("radio", { name: "Mist" }).checked).toBe(true);
    await userEvent.click(within(form).getByRole("button", { name: "Create the endpoint" }));
    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "POST")?.body).toEqual({ name: "Mist prod", allowlist: [], body_limit: 1_048_576, trigger: "mist.webhook" }),
    );
    const shown = await screen.findByRole("status");
    expect(shown.textContent).toContain("Mist prod is ready");
    expect(shown.textContent).toContain("tok-123");
    await userEvent.click(within(shown).getByRole("button", { name: "I've copied it" }));
    expect(screen.queryByText("tok-123")).toBeNull();
  });

  it("makes another sender's endpoint, its proof, events and ids fixed, and says a refused field at its field", async () => {
    const sent = api("editor", "development", {
      "POST /api/v1/t/t1/webhook-endpoints": () => json({ error: "endpoint_invalid", fields: ["id_pointer"] }, 422),
    });
    await show();
    await userEvent.click(await screen.findByRole("button", { name: "＋ Endpoint" })); // once the role is known
    const form = screen.getByRole("form", { name: "New endpoint" });
    await userEvent.type(within(form).getByRole("textbox", { name: "Name" }), "Ticketing");
    await userEvent.click(within(form).getByRole("radio", { name: "Another sender" }));
    await userEvent.click(within(form).getByRole("radio", { name: "An HMAC signature" }));
    await userEvent.click(within(form).getByRole("radio", { name: /^A list in the body, at/ }));
    await userEvent.click(within(form).getByRole("radio", { name: /^In each event, at/ }));
    const id = within(form).getByRole("textbox", { name: "The id's pointer" });
    await userEvent.clear(id);
    await userEvent.type(id, "id");
    expect(form.textContent).toContain("Fixed once made: an HMAC signature; events in the list at /items; each event's id: its pointer needs fixing first.");
    await userEvent.click(within(form).getByRole("button", { name: "Create the endpoint" }));
    await vi.waitFor(() => expect(form.textContent).toContain("A pointer starts with /, like /id, at most 256 characters."));
    expect(sent.find((r) => r.method === "POST")?.body).toMatchObject({ auth: "hmac", events_pointer: "/items", id_source: "pointer", id_pointer: "id" });
  });

  it("rotates a token after asking, and shows the new one once", async () => {
    const sent = api("editor", "development", { "POST /api/v1/t/t1/webhook-endpoints/e1/secret": () => json({ id: "e1", secret: "tok-new" }) });
    await show();
    await userEvent.click(await within(table()).findByRole("button", { name: "Mist prod, details" }));
    await userEvent.click(within(table()).getByRole("button", { name: "Rotate the token…" }));
    const ask = screen.getByRole("dialog", { name: "Rotate Mist prod's token?" });
    expect(ask.textContent).toContain("The old token stops working now: Mist's events are refused until it sends the new one.");
    await userEvent.click(within(ask).getByRole("button", { name: "Rotate the token" }));
    expect((await screen.findByRole("status")).textContent).toContain("tok-new");
    expect(sent.some((r) => r.method === "POST" && r.path.endsWith("/secret"))).toBe(true);
  });

  it("edits what may change, beside what was fixed when it was made", async () => {
    const sent = api("editor", "development", { "PATCH /api/v1/t/t1/webhook-endpoints/e2": () => json({ ...TICKETING, name: "Tickets" }) });
    await show();
    await userEvent.click(await within(table()).findByRole("button", { name: "Ticketing, details" }));
    await userEvent.click(within(table()).getByRole("button", { name: "Edit" }));
    const form = screen.getByRole("form", { name: "Editing Ticketing" });
    expect(form.textContent).toContain("ProofAn HMAC signature");
    expect(form.textContent).toContain("EventsThe list at /items");
    expect(form.textContent).toContain("IdsAt /id in each event");
    const name = within(form).getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Tickets");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ name: "Tickets" }));
  });

  it("turns an endpoint off at once", async () => {
    const sent = api("editor", "development", { "PATCH /api/v1/t/t1/webhook-endpoints/e1": () => json({ ...ENDPOINT, enabled: false }) });
    await show();
    await userEvent.click(await within(table()).findByRole("switch", { name: "Mist prod" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ enabled: false }));
  });

  it("shows a viewer every endpoint, read only, and says why", async () => {
    api("viewer", "development");
    await show();
    expect(await screen.findByText(/Making and changing endpoints needs the editor role./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "＋ Endpoint" })).toBeNull();
    expect(within(table()).queryByRole("switch")).toBeNull();
    await userEvent.click(within(table()).getByRole("button", { name: "Mist prod, details" }));
    expect(within(table()).queryByRole("button", { name: "Rotate the token…" })).toBeNull();
    expect(within(table()).getByRole("button", { name: "Copy the path" })).toBeTruthy();
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`):
`npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/WebhookEndpoints.test.tsx src/router.test.tsx src/components/CommandPalette.test.tsx`

Expected: FAIL: `Test Files  3 failed (3)`, `Tests  2 failed | 18 passed (20)`. The run can't import
`./WebhookEndpoints`: it doesn't exist yet. The failing tests are this task's new and changed ones: `opens Settings →
Webhook endpoints from its tab (4c-3b)`, `goes to a tenant's webhook endpoints (4c-3b)`.

- [ ] **Step 3: Write the code**

**In** `frontend/src/components/CommandPalette.tsx`, **replace**:

````tsx
                  </Command.Item>
                )}
                <Command.Item value="Security" className={PALETTE_ITEM} onSelect={() => go(() => navigate({ to: "/account/security" }))}>
                  Security
````

**with**:

````tsx
                  </Command.Item>
                )}
                {params.tenantId && (
                  <Command.Item
                    value="Webhook endpoints"
                    className={PALETTE_ITEM}
                    onSelect={() =>
                      go(() => navigate({ to: "/t/$tenantId/settings/webhooks", params: { tenantId: params.tenantId! } }))
                    }
                  >
                    Webhook endpoints
                  </Command.Item>
                )}
                <Command.Item value="Security" className={PALETTE_ITEM} onSelect={() => go(() => navigate({ to: "/account/security" }))}>
                  Security
````

**In** `frontend/src/router.tsx`, **replace**:

````tsx
import { SettingsLayout } from "./routes/Settings";
import { TenantsPage } from "./routes/Tenants";
import { WorkflowsPage } from "./routes/Workflows";

````

**with**:

````tsx
import { SettingsLayout } from "./routes/Settings";
import { TenantsPage } from "./routes/Tenants";
import { WebhookEndpointsPage } from "./routes/WebhookEndpoints";
import { WorkflowsPage } from "./routes/Workflows";

````

**In** `frontend/src/router.tsx`, **replace**:

````tsx
}

const rootRoute = createRootRoute({ component: Outlet });
const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: Login });
````

**with**:

````tsx
}

function WebhookEndpoints() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/settings/webhooks" });
  return <WebhookEndpointsPage key={tenantId} tenantId={tenantId} />;
}

const rootRoute = createRootRoute({ component: Outlet });
const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: Login });
````

**In** `frontend/src/router.tsx`, **replace**:

````tsx
const settingsIndexRoute = createRoute({ getParentRoute: () => settingsRoute, path: "/", component: SettingsIndex });
const membersRoute = createRoute({ getParentRoute: () => settingsRoute, path: "members", component: Members });

/** The app's routes; the router below serves them from the browser's history (tests serve them from memory). */
````

**with**:

````tsx
const settingsIndexRoute = createRoute({ getParentRoute: () => settingsRoute, path: "/", component: SettingsIndex });
const membersRoute = createRoute({ getParentRoute: () => settingsRoute, path: "members", component: Members });
const webhooksRoute = createRoute({ getParentRoute: () => settingsRoute, path: "webhooks", component: WebhookEndpoints });

/** The app's routes; the router below serves them from the browser's history (tests serve them from memory). */
````

**In** `frontend/src/router.tsx`, **replace**:

````tsx
    editorRoute,
    connectionsRoute,
    settingsRoute.addChildren([settingsIndexRoute, membersRoute]),
  ]),
]);
````

**with**:

````tsx
    editorRoute,
    connectionsRoute,
    settingsRoute.addChildren([settingsIndexRoute, membersRoute, webhooksRoute]),
  ]),
]);
````

**Create** `frontend/src/routes/EndpointForm.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// A webhook endpoint's form (4c-3b; the EndpointNew, EndpointOther and NarrowForms boards). New: its name, who sends to
// it (a webhook trigger a plugin declares, Mist's, or another sender), and for another sender how it proves itself,
// where its events are and where their ids are, each fixed once it's made; then where deliveries may come from and how
// large one may be. Editing: what the API lets change, beside what was fixed when it was made.
import { useMutation } from "@tanstack/react-query";
import { useId, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "../components/Button";
import { Field, Select, controlClass } from "../components/Field";
import { ApiError } from "../lib/client";
import {
  BODY_LIMITS, FIELD_WORDS, TOLERANCES, blankForm, endpointBody, endpointPatch, eventsWords, fixedWords, idsWords, proofWords, senderWords,
  type EndpointForm as Form,
} from "../lib/endpoints";  // prettier-ignore
import { createEndpoint, senderName, updateEndpoint, type Endpoint, type TriggerType } from "../lib/triggers";

type Created = Endpoint & { secret: string };

function Radio({ name, checked, label, hint, onChange, children }: {
  name: string; checked: boolean; label: string; hint?: string; onChange: () => void; children?: ReactNode;
}) {  // prettier-ignore
  return (
    <div className="flex flex-col gap-0.5">
      <label className="flex min-h-6 flex-wrap items-center gap-2 text-small">
        <input type="radio" name={name} checked={checked} onChange={onChange} className="size-[16px] accent-accent" />
        {label}
        {children}
      </label>
      {hint && <p className="pl-6 text-small text-muted">{hint}</p>}
    </div>
  );
}

function Limits({ form, set, errors }: { form: Pick<Form, "allowlist" | "bodyLimit">; set: (p: Partial<Form>) => void; errors: Record<string, string> }) {
  const id = useId();
  return (
    <>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={id} className="text-small font-semibold">Allowed networks</label>
        <textarea
          id={id} rows={3} value={form.allowlist} spellCheck={false} aria-describedby={`${id}-hint`} aria-invalid={!!errors.allowlist}
          onChange={(e) => set({ allowlist: e.target.value })} className={`${controlClass(!!errors.allowlist)} py-2 font-mono text-small`}
        />
        <p id={`${id}-hint`} className="text-small text-muted">One a line, up to 32. Empty: any address.</p>
        {errors.allowlist && <p className="text-small text-danger">{errors.allowlist}</p>}
      </div>
      <Select label="Largest delivery" value={String(form.bodyLimit)} onChange={(e) => set({ bodyLimit: Number(e.target.value) })}>
        {BODY_LIMITS.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
        {!BODY_LIMITS.some((b) => b.value === form.bodyLimit) && <option value={form.bodyLimit}>{form.bodyLimit.toLocaleString("en-US")} bytes</option>}
      </Select>
    </>
  );  // prettier-ignore
}

/** Each field the API refused, in words; anything else in one sentence. */
function refusal(e: unknown): { fields: Record<string, string>; text: string | null } {
  if (e instanceof ApiError && e.code === "endpoint_invalid") {
    const named = ((e.body as { fields?: string[] }).fields ?? []).filter((f) => FIELD_WORDS[f]);
    return { fields: Object.fromEntries(named.map((f) => [f, FIELD_WORDS[f]!])), text: named.length > 0 ? null : "The endpoint was refused: check its fields." };
  }
  return { fields: {}, text: "The endpoint couldn't be saved. Try again." };
}

export function NewEndpoint({ tenantId, types, onCreated, onCancel }: {
  tenantId: string; types: TriggerType[]; onCreated: (made: Created) => void; onCancel: () => void;
}) {  // prettier-ignore
  const id = useId();
  const webhook = types.find((t) => Object.keys(t.topics).length > 0);
  const [form, setForm] = useState<Form>(() => blankForm(webhook?.key ?? null));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refused, setRefused] = useState<string | null>(null);
  const set = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));
  const create = useMutation({
    mutationFn: () => createEndpoint(tenantId, endpointBody(form)),
    onMutate: () => {
      setErrors({});
      setRefused(null);
    },
    onSuccess: (made) => onCreated(made),
    onError: (e) => {
      const r = refusal(e);
      setErrors(r.fields);
      setRefused(r.text);
    },
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    if (form.name.trim() === "") return setErrors({ name: "A name, so its workflows can pick it." });
    create.mutate();
  }
  const other = form.trigger === null;
  const sender = webhook ? senderName(webhook) : null;
  return (
    <form onSubmit={submit} aria-labelledby={`${id}-title`} className="flex max-w-2xl flex-col gap-4 rounded-lg border border-line bg-surface p-4">
      <h3 id={`${id}-title`} className="text-body-lg font-semibold">New endpoint</h3>
      <Field label="Name" value={form.name} maxLength={120} error={errors.name} autoFocus onChange={(e) => set({ name: e.target.value })} />
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-small font-semibold">For</legend>
        {webhook && sender && (
          <Radio
            name={`${id}-for`} checked={!other} label={sender} onChange={() => set({ trigger: webhook.key })}
            hint={`${sender} sends a token with each event; a workflow picks one of ${sender}'s topics.`}
          />
        )}
        <Radio
          name={`${id}-for`} checked={other} label="Another sender" onChange={() => set({ trigger: null })}
          hint="You choose how it signs its events, and where a list of events and an id are."
        />
      </fieldset>
      {other && (
        <>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-small font-semibold">How it proves it&apos;s the sender · fixed once made</legend>
            <Radio name={`${id}-auth`} checked={form.auth === "bearer"} label="A token" hint="Sent in an Authorization: Bearer header." onChange={() => set({ auth: "bearer" })} />
            <Radio name={`${id}-auth`} checked={form.auth === "hmac"} label="An HMAC signature" hint="Each delivery signed with a shared secret, and timed." onChange={() => set({ auth: "hmac" })} />
            {form.auth === "hmac" && (
              <div className="flex flex-col gap-3 pl-6">
                <Field label="Signature header" value={form.signature} spellCheck={false} error={errors.signature_header} onChange={(e) => set({ signature: e.target.value })} />
                <Field label="Timestamp header" value={form.timestamp} spellCheck={false} error={errors.timestamp_header} onChange={(e) => set({ timestamp: e.target.value })} />
                <Select label="Clock difference allowed" value={String(form.tolerance)} onChange={(e) => set({ tolerance: Number(e.target.value) })}>
                  {TOLERANCES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
                </Select>
                <p className="text-small text-muted">The headers and the clock difference can change later; the kind of proof can&apos;t.</p>
              </div>
            )}
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-small font-semibold">Where the events are · fixed once made</legend>
            <Radio name={`${id}-events`} checked={form.events === "body"} label="The body is one event" onChange={() => set({ events: "body" })} />
            <Radio name={`${id}-events`} checked={form.events === "list"} label="The body is a list of events" onChange={() => set({ events: "list" })} />
            <Radio name={`${id}-events`} checked={form.events === "at"} label="A list in the body, at" onChange={() => set({ events: "at" })}>
              <input
                aria-label="The list's pointer" value={form.eventsAt} spellCheck={false} aria-invalid={!!errors.events_pointer}
                onFocus={() => set({ events: "at" })} onChange={(e) => set({ eventsAt: e.target.value })} className={`${controlClass(!!errors.events_pointer)} w-40`}
              />
            </Radio>
            <p className="text-small text-muted">A pointer into the body, like /items. At most 500 events a delivery, each matched to the workflows on its own.</p>
            {errors.events_pointer && <p className="text-small text-danger">{errors.events_pointer}</p>}
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-small font-semibold">Each event&apos;s id · fixed once made</legend>
            <Radio name={`${id}-ids`} checked={form.ids === "none"} label="None" hint="A delivery the sender repeats runs again." onChange={() => set({ ids: "none" })} />
            <Radio name={`${id}-ids`} checked={form.ids === "pointer"} label="In each event, at" onChange={() => set({ ids: "pointer" })}>
              <input
                aria-label="The id's pointer" value={form.idPointer} spellCheck={false} aria-invalid={!!errors.id_pointer}
                onFocus={() => set({ ids: "pointer" })} onChange={(e) => set({ idPointer: e.target.value })} className={`${controlClass(!!errors.id_pointer)} w-40`}
              />
            </Radio>
            <Radio name={`${id}-ids`} checked={form.ids === "header"} label="In a header" onChange={() => set({ ids: "header" })}>
              <input
                aria-label="The id's header" value={form.idHeader} spellCheck={false} aria-invalid={!!errors.id_header}
                onFocus={() => set({ ids: "header" })} onChange={(e) => set({ idHeader: e.target.value })} className={`${controlClass(!!errors.id_header)} w-40`}
              />
            </Radio>
            <p className="text-small text-muted">With an id, a delivery the sender repeats is recognized, and doesn&apos;t run twice. A pointer starts with /, like /id.</p>
            {(errors.id_pointer ?? errors.id_header) && <p className="text-small text-danger">{errors.id_pointer ?? errors.id_header}</p>}
          </fieldset>
        </>
      )}
      {other ? (
        <fieldset className="flex flex-col gap-3">
          <legend className="mb-1 text-small font-semibold">Allowed addresses and the largest delivery (can change later)</legend>
          <Limits form={form} set={set} errors={errors} />
        </fieldset>
      ) : (
        <details>
          <summary className="min-h-6 cursor-pointer text-small font-semibold">Allowed addresses and the largest event</summary>
          <p className="text-small text-muted">Optional: up to 32 networks, like 203.0.113.0/24, and a size limit.</p>
          <div className="mt-3 flex flex-col gap-3">
            <Limits form={form} set={set} errors={errors} />
          </div>
        </details>
      )}
      <p className="text-small text-muted">{other ? fixedWords(form) : "How it's signed is fixed once it's made."}</p>
      {refused && <p role="alert" className="text-small text-danger">{refused}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={create.isPending}>Create the endpoint</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );  // prettier-ignore
}

export function EditEndpoint({ tenantId, endpoint, types, onSaved, onCancel }: {
  tenantId: string; endpoint: Endpoint; types: TriggerType[]; onSaved: () => void; onCancel: () => void;
}) {  // prettier-ignore
  const id = useId();
  const [form, setForm] = useState(() => ({
    name: endpoint.name, signature: endpoint.signature_header ?? "", timestamp: endpoint.timestamp_header ?? "", tolerance: endpoint.tolerance_s,
    allowlist: endpoint.allowlist.join("\n"), bodyLimit: endpoint.body_limit,
  }));  // prettier-ignore
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [refused, setRefused] = useState<string | null>(null);
  const set = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));
  const save = useMutation({
    mutationFn: () => updateEndpoint(tenantId, endpoint.id, endpointPatch(endpoint, form)),
    onMutate: () => {
      setErrors({});
      setRefused(null);
    },
    onSuccess: onSaved,
    onError: (e) => {
      const r = refusal(e);
      setErrors(r.fields);
      setRefused(r.text);
    },
  });
  const hmac = endpoint.auth === "hmac";
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (form.name.trim() === "") return setErrors({ name: "A name, so its workflows can pick it." });
        save.mutate();
      }}
      aria-labelledby={`${id}-title`} className="flex max-w-2xl flex-col gap-4 rounded-lg border border-line bg-surface p-4"
    >
      <h3 id={`${id}-title`} className="text-body-lg font-semibold">Editing {endpoint.name}</h3>
      <Field label="Name" value={form.name} maxLength={120} error={errors.name} autoFocus onChange={(e) => set({ name: e.target.value })} />
      {hmac && (
        <>
          <Field label="Signature header" value={form.signature} spellCheck={false} error={errors.signature_header} onChange={(e) => set({ signature: e.target.value })} />
          <Field label="Timestamp header" value={form.timestamp} spellCheck={false} error={errors.timestamp_header} onChange={(e) => set({ timestamp: e.target.value })} />
          <Select label="Clock difference allowed" value={String(form.tolerance)} onChange={(e) => set({ tolerance: Number(e.target.value) })}>
            {TOLERANCES.map((x) => <option key={x.value} value={x.value}>{x.label}</option>)}
            {!TOLERANCES.some((x) => x.value === form.tolerance) && <option value={form.tolerance}>{form.tolerance} seconds</option>}
          </Select>
        </>
      )}
      <Limits form={form} set={set} errors={errors} />
      <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 rounded-lg border border-line p-3 text-small">
        <dt className="col-span-2 font-semibold">Fixed when it was made</dt>
        <dt className="text-muted">Sender</dt><dd>{senderWords(endpoint.trigger, types)}</dd>
        <dt className="text-muted">Proof</dt><dd>{proofWords(endpoint.auth)}</dd>
        <dt className="text-muted">Events</dt><dd>{eventsWords(endpoint.events_pointer)}</dd>
        <dt className="text-muted">Ids</dt><dd>{idsWords(endpoint)}</dd>
      </dl>
      <p className="text-small text-muted">To change these, make a new endpoint and move the workflows&apos; webhooks to it.</p>
      {refused && <p role="alert" className="text-small text-danger">{refused}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={save.isPending}>Save</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </form>
  );  // prettier-ignore
}
````

**In** `frontend/src/routes/Settings.tsx`, **replace**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// Settings, as in screen 1i: the tenant's name, then its tabs as links (each tab is its own page). In 4a: Members &
// roles; Webhook endpoints arrives with 4c, Notification channels with sub-project 3, Service grants with 5 (D11).
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "@tanstack/react-router";
````

**with**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// Settings, as in screen 1i: the tenant's name, then its tabs as links (each tab is its own page): Members & roles (4a)
// and Webhook endpoints (4c-3b); Notification channels arrive with sub-project 3, Service grants with 5 (D11).
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "@tanstack/react-router";
````

**In** `frontend/src/routes/Settings.tsx`, **replace**:

````tsx
          Members &amp; roles
        </Link>
      </nav>
      <Outlet />
````

**with**:

````tsx
          Members &amp; roles
        </Link>
        <Link
          to="/t/$tenantId/settings/webhooks"
          params={{ tenantId }}
          className={TAB}
          activeProps={{ className: "border-accent font-semibold text-ink" }}
          inactiveProps={{ className: "border-transparent text-muted hover:text-ink" }}
        >
          Webhook endpoints
        </Link>
      </nav>
      <Outlet />
````

**Create** `frontend/src/routes/WebhookEndpoints.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// Settings → Webhook endpoints (D11; 4c-3b; the Endpoints, EndpointNew, EndpointOther, ReadOnly and NarrowForms
// boards): where other systems send events, each with its sender, how it proves itself, the workflows it starts, its
// waiting events and its path. Every member reads; editors and above make, change, turn off and rotate (trigger.manage),
// and the API decides every write. An endpoint is turned off, never deleted. A secret is shown once, when it's made or
// rotated, and never kept by the page.
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Fragment, useRef, useState } from "react";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { LoadError } from "../components/LoadError";
import { Switch } from "../components/Switch";
import { Table, Td, Th } from "../components/Table";
import { announce } from "../lib/announce";
import { proofWords, secretWords, senderWords } from "../lib/endpoints";
import { usePlatformStatus } from "../lib/platform";
import { useDocumentTitle } from "../lib/title";
import {
  endpointBindingsQuery, endpointsQuery, rotateSecret, topicOf, triggerTypesQuery, updateEndpoint, type Endpoint, type EndpointBinding,
} from "../lib/triggers";  // prettier-ignore
import { canEdit, tenantQuery, workflowsQuery } from "../lib/workflows";
import { EditEndpoint, NewEndpoint } from "./EndpointForm";

type Shown = { name: string; secret: string; endpoint: Endpoint; rotated: boolean };

const short = (path: string) => (path.length > 18 ? `${path.slice(0, 16)}…` : path);

/** Copies the path, and says so: a refused clipboard says where to read it instead. */
async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    announce("Copied the path");
  } catch {
    announce("The clipboard refused it: the path is in the details, to copy by hand");
  }
}

export function WebhookEndpointsPage({ tenantId }: { tenantId: string }) {
  useDocumentTitle("Webhook endpoints");
  const qc = useQueryClient();
  const tenant = useQuery(tenantQuery(tenantId));
  const manage = canEdit(tenant.data?.role);
  const endpoints = useQuery(endpointsQuery(tenantId));
  const types = useQuery(triggerTypesQuery);
  const platform = usePlatformStatus();
  const workflows = useQuery(workflowsQuery(tenantId));
  const list = endpoints.data?.endpoints ?? [];
  const bindings = useQueries({ queries: list.map((e) => endpointBindingsQuery(tenantId, e.id)) });
  const bound = new Map(list.map((e, i) => [e.id, bindings[i]?.data?.bindings ?? null]));
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [shown, setShown] = useState<Shown | null>(null);
  const [rotating, setRotating] = useState<Endpoint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["endpoints", tenantId] });
  const named = (id: string) => workflows.data?.find((w) => w.id === id)?.name ?? "a workflow";
  const typeOf = (e: Endpoint) => (types.data ?? []).find((t) => t.key === e.trigger);

  const toggle = useMutation({
    mutationFn: (e: { id: string; name: string; enabled: boolean }) => updateEndpoint(tenantId, e.id, { enabled: e.enabled }),
    onMutate: () => setError(null),
    onSuccess: (_, e) => announce(`${e.name} turned ${e.enabled ? "on" : "off: events sent to it are refused"}`),
    onError: (_, e) => setError(`${e.name} couldn't be turned ${e.enabled ? "on" : "off"}. Try again.`),
    onSettled: refresh,
  });
  const rotate = useMutation({
    mutationFn: (e: Endpoint) => rotateSecret(tenantId, e.id),
    onSuccess: (out, e) => {
      setRotating(null);
      setShown({ name: e.name, secret: out.secret, endpoint: e, rotated: true });
    },
    onError: (_, e) => {
      setRotating(null);
      setError(`${e.name}'s ${e.auth === "hmac" ? "secret" : "token"} wasn't rotated. Try again.`);
    },
  });

  /** What the endpoint starts, as links to its workflows, with each one's topic where it has one. */
  function starts(e: Endpoint, rows: EndpointBinding[] | null) {
    if (rows === null) return <span className="text-muted">The workflows it starts couldn&apos;t be read.</span>;
    if (rows.length === 0) return <span className="text-muted">It starts no workflow yet: a workflow picks it in its Triggers.</span>;
    return (
      <span>
        Starts{" "}
        {rows.map((b, i) => {
          const topic = topicOf(b.filter, typeOf(e));
          return (
            <Fragment key={b.id}>
              {i > 0 && ", "}
              <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: b.workflow_id }} className="text-accent-ink underline">
                {named(b.workflow_id)}{topic ? ` · ${topic}` : ""}
              </Link>
              {!b.enabled && " (off)"}
            </Fragment>
          );
        })}
      </span>
    );  // prettier-ignore
  }

  function details(e: Endpoint) {
    const sender = senderWords(e.trigger, types.data ?? []);
    const rows = bound.get(e.id) ?? null;
    return (
      <div className="flex flex-col gap-2 text-small">
        <p>
          Path <code className="break-all font-mono">{e.path}</code>, on your Dewpoint webhook address.{" "}
          {e.auth === "hmac" ? "Each delivery is signed with its secret, and timed." : `${sender === "Another sender" ? "The sender" : sender} sends its token in an Authorization: Bearer header.`}
        </p>
        <p>{starts(e, rows)}</p>
        {e.pending_events > 0 && <p className="text-muted">{e.pending_events === 1 ? "1 event is" : `${e.pending_events} events are`} waiting to be matched.</p>}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => void copy(e.path)}>Copy the path</Button>
          {manage && <Button size="sm" onClick={() => setEditing(e.id)}>Edit</Button>}
          {manage && <Button size="sm" variant="danger-outline" onClick={() => setRotating(e)}>{e.auth === "hmac" ? "Rotate the secret…" : "Rotate the token…"}</Button>}
        </div>
      </div>
    );  // prettier-ignore
  }

  const onSwitch = (e: Endpoint) =>
    manage ? (
      <Switch checked={e.enabled} label={e.name} disabled={toggle.isPending} onCheckedChange={(enabled) => toggle.mutate({ id: e.id, name: e.name, enabled })} />
    ) : (
      <span>{e.enabled ? "On" : "Off"}</span>
    );  // prettier-ignore
  const workflowsOf = (e: Endpoint) => (bound.get(e.id) ?? null)?.length ?? "–";
  const detailsButton = (e: Endpoint) => (
    <Button size="sm" aria-label={`${e.name}, details`} aria-expanded={open === e.id} onClick={() => setOpen(open === e.id ? null : e.id)}>Details</Button>
  );
  const editingOne = list.find((e) => e.id === editing);
  return (
    <div className="flex flex-col gap-3">
      <div>
        <h2 ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Webhook endpoints</h2>
        <p className="mt-0.5 text-small text-muted">
          Where other systems send events. {manage ? "A workflow picks an endpoint in its Triggers." : "Making and changing endpoints needs the editor role."}
        </p>
      </div>
      {platform.isSuccess && platform.data.environment !== "development" && (
        <p className="text-small text-warn-ink">This deployment doesn&apos;t receive webhooks yet: only development deployments do, for now.</p>
      )}
      {error && <p role="alert" className="text-body text-danger">{error}</p>}
      {shown && (
        <div role="status" className="flex max-w-2xl flex-col gap-2 rounded-lg border border-line-strong bg-surface p-4">
          <h3 className="text-body-lg font-semibold">{shown.rotated ? `${shown.name}'s new ${shown.endpoint.auth === "hmac" ? "secret" : "token"}` : `${shown.name} is ready`}</h3>
          <p className="text-small">{shown.endpoint.auth === "hmac" ? "Its signing secret" : "Its token"}, shown this once:</p>
          <code className="break-all rounded-lg border border-line px-3 py-2 font-mono text-small">{shown.secret}</code>
          <p className="text-small text-muted">{secretWords(shown.endpoint, senderWords(shown.endpoint.trigger, types.data ?? []))}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={() => {
                void navigator.clipboard.writeText(shown.secret).then(() => announce("Copied"), () => announce("The clipboard refused it: select it to copy by hand"));
              }}
            >
              Copy
            </Button>
            <Button
              size="sm" variant="primary"
              onClick={() => {
                setShown(null);
                requestAnimationFrame(() => heading.current?.focus());
              }}
            >
              I&apos;ve copied it
            </Button>
          </div>
        </div>
      )}
      {manage && !adding && !editingOne && (
        <Button variant="primary" size="md" className="self-start" onClick={() => setAdding(true)}>＋ Endpoint</Button>
      )}
      {adding && (
        <NewEndpoint
          tenantId={tenantId} types={types.data ?? []}
          onCreated={(made) => {
            setAdding(false);
            setShown({ name: made.name, secret: made.secret, endpoint: made, rotated: false });
            announce(`Created ${made.name}`);
            void refresh();
          }}
          onCancel={() => {
            setAdding(false);
            requestAnimationFrame(() => heading.current?.focus());
          }}
        />
      )}
      {editingOne && (
        <EditEndpoint
          tenantId={tenantId} endpoint={editingOne} types={types.data ?? []}
          onSaved={() => {
            setEditing(null);
            announce(`Saved ${editingOne.name}`);
            void refresh();
          }}
          onCancel={() => setEditing(null)}
        />
      )}
      {endpoints.isError ? (
        <LoadError what="The webhook endpoints" />
      ) : endpoints.isSuccess && list.length === 0 ? (
        <p className="text-small text-muted">No endpoint yet.</p>
      ) : (
        <>
          <Table label="Webhook endpoints" className="hidden sm:block">
            <thead>
              <tr>
                <Th>Name</Th><Th>Sender</Th><Th>Signed with</Th><Th>Workflows</Th><Th>Waiting</Th><Th>On</Th><Th>Path</Th>
                <Th><span className="sr-only">Actions</span></Th>
              </tr>
            </thead>
            <tbody>
              {list.map((e) => (
                <Fragment key={e.id}>
                  <tr>
                    <Td className="font-medium">{e.name}</Td>
                    <Td>{senderWords(e.trigger, types.data ?? [])}</Td>
                    <Td>{proofWords(e.auth)}</Td>
                    <Td className="font-mono text-small">{workflowsOf(e)}</Td>
                    <Td className="font-mono text-small">{e.pending_events}</Td>
                    <Td>{onSwitch(e)}</Td>
                    <Td className="font-mono text-small">{short(e.path)}</Td>
                    <Td className="text-right">{detailsButton(e)}</Td>
                  </tr>
                  {open === e.id && (
                    <tr>
                      <Td colSpan={8}>{details(e)}</Td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </Table>
          <ul aria-label="Webhook endpoints" className="flex flex-col gap-3 sm:hidden">
            {list.map((e) => (
              <li key={e.id} className="flex flex-col gap-2 rounded-lg border border-line bg-surface p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{e.name}</span>
                  {onSwitch(e)}
                </div>
                <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-small">
                  <dt className="text-muted">Sender</dt><dd>{senderWords(e.trigger, types.data ?? [])}</dd>
                  <dt className="text-muted">Signed with</dt><dd>{proofWords(e.auth)}</dd>
                  <dt className="text-muted">Workflows</dt><dd className="font-mono">{workflowsOf(e)}</dd>
                  <dt className="text-muted">Waiting</dt><dd className="font-mono">{e.pending_events}</dd>
                  <dt className="text-muted">Path</dt><dd className="break-all font-mono">{e.path}</dd>
                </dl>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => void copy(e.path)}>Copy the path</Button>
                  {detailsButton(e)}
                </div>
                {open === e.id && details(e)}
              </li>
            ))}
          </ul>
        </>
      )}
      <p className="text-small text-muted">An endpoint is turned off rather than deleted: events sent to it are refused, and its workflows keep their bindings.</p>
      <ConfirmDialog
        open={rotating !== null}
        title={rotating ? `Rotate ${rotating.name}'s ${rotating.auth === "hmac" ? "secret" : "token"}?` : ""}
        confirmLabel={rotating?.auth === "hmac" ? "Rotate the secret" : "Rotate the token"}
        busy={rotate.isPending}
        onConfirm={() => rotating && rotate.mutate(rotating)}
        onCancel={() => setRotating(null)}
      >
        {rotating &&
          `The old ${rotating.auth === "hmac" ? "secret" : "token"} stops working now: ${senderWords(rotating.trigger, types.data ?? []) === "Another sender" ? "the sender's" : `${senderWords(rotating.trigger, types.data ?? [])}'s`} events are refused until it sends the new one.`}
      </ConfirmDialog>
    </div>
  );  // prettier-ignore
}
````

- [ ] **Step 4: Run them to see them pass**

Run:
`npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/WebhookEndpoints.test.tsx src/router.test.tsx src/components/CommandPalette.test.tsx`

Expected: PASS: `Test Files  3 passed (3)`, `Tests  30 passed (30)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/CommandPalette.test.tsx \
  frontend/src/components/CommandPalette.tsx \
  frontend/src/router.test.tsx \
  frontend/src/router.tsx \
  frontend/src/routes/EndpointForm.tsx \
  frontend/src/routes/Settings.tsx \
  frontend/src/routes/WebhookEndpoints.test.tsx \
  frontend/src/routes/WebhookEndpoints.tsx
git commit -m "feat(settings): webhook endpoints: made, shown, turned off, rotated (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: Webhooks

A workflow's webhook bindings in the panel (ruling 10): each with its endpoint and when it runs, a Mist binding compared
with the published version's input and offering the topic's shape for the draft; turned on or off at once; added (an
endpoint, then a topic or conditions), edited, removed once asked. A binding shows by its topic only when its filter is
that topic alone, else by its conditions, kept as they are; nothing shows before the endpoint's sender is known, and
when that can't be loaded, the form says so with Try again and adds nothing for it (the reviews of revisions 1 and 2).

**Files:**
- Modify: `frontend/src/routes/editor/triggers/TriggersPanel.tsx`
- Create: `frontend/src/routes/editor/triggers/WebhookForm.tsx`
- Create: `frontend/src/routes/editor/triggers/WebhooksSection.test.tsx`
- Create: `frontend/src/routes/editor/triggers/WebhooksSection.tsx`

**Interfaces:**
- Consumes: Tasks 3, 4, 7 and 10.
- Produces: `WebhooksSection`, `WebhookForm`; the panel's Webhooks section.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/routes/editor/triggers/WebhooksSection.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../../lib/workflows";
import type { WorkflowBinding } from "../../../lib/triggers";
import { BINDING, DEVICE_EVENTS, ENDPOINT, MIST } from "../../../test/triggers";
import { fakeApi, json } from "../drawer/harness";
import { showPanel } from "./harness";

const FORM_FIELDS = { type: "object", properties: { site: { type: "string" }, note: { type: "string" } } };
const OTHER: WorkflowBinding = {
  id: "b2", endpoint_id: "e2", workflow_id: "w1", enabled: true,
  filter: [{ pointer: "/type", value: "incident" }, { pointer: "/priority", value: 1 }],
  endpoint: { id: "e2", name: "Ticketing", enabled: true, auth: "hmac", path: "/hooks/e2", trigger: null },
};  // prettier-ignore
const draft = (input_schema: Record<string, unknown>): GraphDoc => ({ graph_format: 1, nodes: [], edges: [], settings: { input_schema } });
const section = () => screen.getByRole("region", { name: "Webhooks" });

function api(bindings: WorkflowBinding[], more: Record<string, () => Response | Promise<Response>> = {}) {
  return fakeApi({
    "GET /api/v1/trigger-types": () => json([MIST]),
    "GET /api/v1/t/t1/workflows/w1/schedules": () => json({ schedules: [] }),
    "GET /api/v1/t/t1/workflows/w1/start-form": () => json({ workflow_id: "w1", version_id: "v3", fields: [], csv: null }),
    "GET /api/v1/t/t1/workflows/w1/versions/v3": () => json({ id: "v3", number: 3, graph: draft(FORM_FIELDS) }),
    "GET /api/v1/t/t1/workflows/w1/webhook-bindings": () => json({ bindings }),
    "GET /api/v1/t/t1/webhook-endpoints": () =>
      json({ endpoints: [ENDPOINT, { ...ENDPOINT, id: "e2", name: "Ticketing", trigger: null, auth: "hmac" }, { ...ENDPOINT, id: "e3", name: "Mist lab" }] }),
    ...more,
  });
}
afterEach(() => vi.restoreAllMocks());

describe("a workflow's webhooks", () => {
  it("says each one's sender and when it runs, and what the published input makes of its events", async () => {
    api([BINDING, OTHER]);
    await showPanel({ doc: draft(FORM_FIELDS) });
    const rows = (await within(section()).findAllByRole("listitem")).map((r) => r.textContent ?? "");
    expect(rows[0]).toContain("Mist · topic device-events");
    await vi.waitFor(() => expect(section().textContent).toContain("Version 3's input isn't device-events' shape (it has 2 form fields): events it doesn't fit are refused."));
    expect(rows[1]).toContain("Another sender · /type is incident and /priority is 1");
    expect(rows[1]).toContain("Its events have no known shape: the input must fit them, or each is refused.");
  });

  it("gives the draft the topic's shape, then says it applies once published", async () => {
    api([BINDING]);
    const panel = await showPanel({ doc: draft(FORM_FIELDS) });
    await userEvent.click(await within(section()).findByRole("button", { name: "Use device-events' shape for the input" }));
    expect(panel.settings()?.input_schema).toEqual(DEVICE_EVENTS);
    expect(section().textContent).toContain("In the draft: it applies once published.");
  });

  it("says a binding's events are refused before a first publish", async () => {
    api([BINDING]);
    await showPanel({ doc: draft(FORM_FIELDS), activeNumber: null, activeVersionId: null });
    await vi.waitFor(() => expect(section().textContent).toContain("Events are refused until a version is published, and listed as refused in the endpoint's events."));
  });

  it("adds a Mist webhook for a topic, giving the input its shape in the draft", async () => {
    const sent = api([OTHER], { "POST /api/v1/t/t1/webhook-endpoints/e1/bindings": () => json({ ...BINDING, endpoint: undefined }, 201) });
    const panel = await showPanel({ doc: draft(FORM_FIELDS) });
    await userEvent.click(within(section()).getByRole("button", { name: "＋ Webhook" }));
    const form = within(section()).getByRole("form", { name: "New webhook" });
    expect(form.querySelector("dialog")).toBeNull(); // nothing to remove yet: no question waits in it, closed or not
    const endpoint = within(form).getByRole("combobox", { name: "Endpoint" });
    await vi.waitFor(() => expect(within(endpoint).getByRole<HTMLOptionElement>("option", { name: "Ticketing · already starts this workflow" }).disabled).toBe(true));
    await userEvent.selectOptions(endpoint, "e1");
    expect(form.textContent).toContain("Mist sends every topic you subscribe to one URL; this workflow runs for this one.");
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Topic" }), "device-events");
    expect(form.textContent).toContain("Replaces the input's 2 fields, in the draft: Undo brings them back.");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "POST")?.body).toEqual({ workflow_id: "w1", filter: [{ pointer: "/topic", value: "device-events" }] }),
    );
    await vi.waitFor(() => expect(panel.settings()?.input_schema).toEqual(DEVICE_EVENTS));
  });

  it("adds another sender's webhook with typed conditions, checked before anything is sent", async () => {
    const sent = api([], { "POST /api/v1/t/t1/webhook-endpoints/e2/bindings": () => json({ ...OTHER, endpoint: undefined }, 201) });
    await showPanel();
    await userEvent.click(within(section()).getByRole("button", { name: "＋ Webhook" }));
    const form = within(section()).getByRole("form", { name: "New webhook" });
    await vi.waitFor(() => expect(within(form).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e2");
    await userEvent.click(within(form).getByRole("button", { name: "＋ Condition" }));
    await userEvent.type(within(form).getByRole("textbox", { name: "Field 1" }), "type");
    await userEvent.type(within(form).getByRole("textbox", { name: "Value 1" }), "incident");
    await userEvent.click(within(form).getByRole("button", { name: "＋ Condition" }));
    await userEvent.type(within(form).getByRole("textbox", { name: "Field 2" }), "/priority");
    await userEvent.type(within(form).getByRole("textbox", { name: "Value 2" }), "1");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    expect(form.textContent).toContain("A field is a pointer into the event, starting with /, like /type.");
    expect(sent.some((r) => r.method === "POST")).toBe(false);
    await userEvent.type(within(form).getByRole("textbox", { name: "Field 1" }), "{Home}/");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    await vi.waitFor(() =>
      expect(sent.find((r) => r.method === "POST")?.body).toEqual({ workflow_id: "w1", filter: [{ pointer: "/type", value: "incident" }, { pointer: "/priority", value: 1 }] }),
    );
  });

  it("says the API's refusal in words", async () => {
    api([], { "POST /api/v1/t/t1/webhook-endpoints/e3/bindings": () => json({ error: "binding_cap" }, 409) });
    await showPanel();
    await userEvent.click(within(section()).getByRole("button", { name: "＋ Webhook" }));
    const form = within(section()).getByRole("form", { name: "New webhook" });
    await vi.waitFor(() => expect(within(form).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e3");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    expect(await within(form).findByRole("alert")).toHaveProperty("textContent", "This endpoint starts 20 workflows, its most: remove one there first.");
  });

  it("keeps every condition of a filter a topic can't say, and saves it unchanged as it was", async () => {
    // The review of revision 1: a topic and a site, saved unchanged, lost the site, and the first topic won.
    const both: WorkflowBinding = { ...BINDING, filter: [{ pointer: "/topic", value: "device-events" }, { pointer: "/site", value: " HQ " }] };
    const sent = api([both], { "PATCH /api/v1/t/t1/webhook-bindings/b1": () => json(both) });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Mist prod" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Mist prod" });
    expect(within(form).queryByRole("combobox", { name: "Topic" })).toBeNull();
    expect(form.textContent).toContain("Its conditions aren't a topic alone: they're kept as they are, and change here.");
    expect(within(form).getByRole<HTMLInputElement>("textbox", { name: "Value 2" }).value).toBe('" HQ "');
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ filter: both.filter }));
  });

  it("waits for what an endpoint sends before showing its topic, so a save never changes it", async () => {
    // The review of revision 1: the trigger types answering after the form opened gave it the first topic.
    let types: ((r: Response) => void) | undefined;
    const sent = api([BINDING], {
      "GET /api/v1/trigger-types": () => new Promise<Response>((resolve) => (types = resolve)),
      "PATCH /api/v1/t/t1/webhook-bindings/b1": () => json(BINDING),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("button", { name: "Edit Mist prod" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Mist prod" });
    expect(within(form).getByRole<HTMLButtonElement>("button", { name: "Save" }).disabled).toBe(true);
    await vi.waitFor(() => expect(types).toBeDefined());
    types!(json([MIST]));
    const topic = await within(form).findByRole<HTMLSelectElement>("combobox", { name: "Topic" });
    expect(topic.value).toBe("device-events");
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ filter: BINDING.filter }));
  });

  it("says when what an endpoint sends can't be loaded, and adds nothing for it until it is", async () => {
    // The review of revision 2: trigger types failing left a Mist endpoint without a topic: Add bound it to every event.
    let failing = true;
    const sent = api([], {
      "GET /api/v1/trigger-types": () => (failing ? json({ error: "unavailable" }, 503) : json([MIST])),
      "POST /api/v1/t/t1/webhook-endpoints/e1/bindings": () => json({ ...BINDING, endpoint: undefined }, 201),
    });
    await showPanel();
    await userEvent.click(within(section()).getByRole("button", { name: "＋ Webhook" }));
    const form = within(section()).getByRole("form", { name: "New webhook" });
    await vi.waitFor(() => expect(within(form).getAllByRole("option").length).toBeGreaterThan(1));
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e1");
    expect(await within(form).findByText("What this endpoint sends couldn't be loaded, so its topics can't be shown.")).toBeTruthy();
    expect(within(form).getByRole<HTMLButtonElement>("button", { name: "Add the webhook" }).disabled).toBe(true);
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e2"); // another sender's needs none
    expect(within(form).getByRole("button", { name: "＋ Condition" })).toBeTruthy();
    await userEvent.selectOptions(within(form).getByRole("combobox", { name: "Endpoint" }), "e1");
    failing = false;
    await userEvent.click(within(form).getByRole("button", { name: "Try again" }));
    await userEvent.selectOptions(await within(form).findByRole("combobox", { name: "Topic" }), "alarms");
    await userEvent.click(within(form).getByRole("button", { name: "Add the webhook" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "POST")?.body).toEqual({ workflow_id: "w1", filter: [{ pointer: "/topic", value: "alarms" }] }));
  });

  it("changes one's conditions, turns one off at once, and removes one after asking", async () => {
    const sent = api([OTHER], {
      "PATCH /api/v1/t/t1/webhook-bindings/b2": () => json(OTHER),
      "DELETE /api/v1/t/t1/webhook-bindings/b2": () => new Response(null, { status: 204 }),
    });
    await showPanel();
    await userEvent.click(await within(section()).findByRole("switch", { name: "Ticketing" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PATCH")?.body).toEqual({ enabled: false }));
    await userEvent.click(within(section()).getByRole("button", { name: "Edit Ticketing" }));
    const form = within(section()).getByRole("form", { name: "The webhook from Ticketing" });
    await userEvent.click(within(form).getByRole("button", { name: "Remove condition 2" }));
    await userEvent.click(within(form).getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(sent.filter((r) => r.method === "PATCH").at(-1)?.body).toEqual({ filter: [{ pointer: "/type", value: "incident" }] }));
    await userEvent.click(within(section()).getByRole("button", { name: "Edit Ticketing" }));
    await userEvent.click(within(section()).getByRole("button", { name: "Remove the webhook…" }));
    const ask = screen.getByRole("dialog", { name: "Remove the webhook from Ticketing?" });
    await userEvent.click(within(ask).getByRole("button", { name: "Remove the webhook" }));
    await vi.waitFor(() => expect(sent.some((r) => r.method === "DELETE")).toBe(true));
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/triggers`

Expected: FAIL: `Test Files  1 failed | 2 passed (3)`, `Tests  10 failed | 43 passed (53)`. The failing tests are this
task's new and changed ones: `says each one's sender and when it runs, and what the published input makes of its
events`, `gives the draft the topic's shape, then says it applies once published`, `says a binding's events are refused
before a first publish`, `adds a Mist webhook for a topic, giving the input its shape in the draft`, `adds another
sender's webhook with typed conditions, checked before anything is sent`, `says the API's refusal in words`, `keeps
every condition of a filter a topic can't say, and saves it unchanged as it was`, `waits for what an endpoint sends
before showing its topic, so a save never changes it`, `says when what an endpoint sends can't be loaded, and adds
nothing for it until it is`, `changes one's conditions, turns one off at once, and removes one after asking`.

- [ ] **Step 3: Write the code**

**In** `frontend/src/routes/editor/triggers/TriggersPanel.tsx`, **replace**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The Triggers panel (4c-3b; the mockups' Main, ReadOnly and Narrow boards): what starts the workflow, opened from the
// start card. Its input is the draft's, saved with it and used once published; its schedules are live, saved at once
// on the published version, outside undo (Task 11 adds its webhooks). A viewer or an operator sees it all, read only.
import { useEffect, useRef } from "react";
import { Button } from "../../../components/Button";
````

**with**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The Triggers panel (4c-3b; the mockups' Main, ReadOnly and Narrow boards): what starts the workflow, opened from the
// start card. Its input is the draft's, saved with it and used once published; its schedules and webhooks are live,
// saved at once on the published version, outside undo. A viewer or an operator sees it all, read only.
import { useEffect, useRef } from "react";
import { Button } from "../../../components/Button";
````

**In** `frontend/src/routes/editor/triggers/TriggersPanel.tsx`, **replace**:

````tsx
import { InputSection, type FocusAt } from "./InputSection";
import { SchedulesSection } from "./SchedulesSection";

export function TriggersPanel({ value, focusAt, onClose }: { value: Triggers; focusAt: FocusAt; onClose: () => void }) {
````

**with**:

````tsx
import { InputSection, type FocusAt } from "./InputSection";
import { SchedulesSection } from "./SchedulesSection";
import { WebhooksSection } from "./WebhooksSection";

export function TriggersPanel({ value, focusAt, onClose }: { value: Triggers; focusAt: FocusAt; onClose: () => void }) {
````

**In** `frontend/src/routes/editor/triggers/TriggersPanel.tsx`, **replace**:

````tsx
        <InputSection focusAt={focusAt} />
        <SchedulesSection />
      </aside>
    </TriggersContext.Provider>
````

**with**:

````tsx
        <InputSection focusAt={focusAt} />
        <SchedulesSection />
        <WebhooksSection />
      </aside>
    </TriggersContext.Provider>
````

**Create** `frontend/src/routes/editor/triggers/WebhookForm.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// A webhook's form (4c-3b; the Webhooks and NarrowForms boards): an endpoint, and when this workflow runs for its
// events. A webhook trigger's endpoint picks one of its topics, and may give the input the topic's shape, in the draft;
// another sender's runs for events where up to 8 conditions hold. Saved at once. Editing one changes its conditions,
// or removes it, asked first (the binding's form, extrapolated from the boards: ruling proposed). A binding is shown
// as it is: by its topic only when its filter is that topic alone, else by its conditions, each value as typed back
// exactly; nothing shows before the endpoint's sender is known (the review of revision 1), and when that can't be
// loaded, it says so and offers to try again, never conditions in its topic's place (the review of revision 2).
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState, type FormEvent } from "react";
import { Button } from "../../../components/Button";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { Select, controlClass } from "../../../components/Field";
import { announce } from "../../../lib/announce";
import { ApiError } from "../../../lib/client";
import { inputOf, inputRows, sameSchema, setSettings } from "../../../lib/input";
import {
  createBinding, deleteBinding, endpointsQuery, parseValue, possessive, senderName, topicOf, triggerTypesQuery, updateBinding, valueText,
  workflowBindingsQuery, type FilterClause, type WorkflowBinding,
} from "../../../lib/triggers";  // prettier-ignore
import { useTriggers } from "./context";
import { Check } from "./parts";

const MAX_CLAUSES = 8;

const REFUSALS: Record<string, string> = {
  binding_exists: "This endpoint already starts this workflow.",
  binding_cap: "This endpoint starts 20 workflows, its most: remove one there first.",
  filter_invalid: "The endpoint refuses these conditions: each field is a pointer starting with /, each value a text of at most 1,024 characters, a whole number, true, false or null.",
  not_found: "This endpoint is gone: choose another.",
};

type Clause = { pointer: string; value: string };

export function WebhookForm({ binding, onDone }: { binding: WorkflowBinding | null; onDone: (saved: boolean) => void }) {
  const t = useTriggers();
  const id = useId();
  const editing = binding !== null;
  const types = useQuery(triggerTypesQuery);
  const endpoints = useQuery({ ...endpointsQuery(t.tenantId), enabled: !editing });
  const bound = useQuery(workflowBindingsQuery(t.tenantId, t.workflowId));
  const taken = new Set((bound.data?.bindings ?? []).map((b) => b.endpoint_id));
  const choices = endpoints.data?.endpoints ?? [];
  const [endpointId, setEndpointId] = useState<string | null>(binding?.endpoint_id ?? null);
  const chosen = editing ? binding.endpoint : (choices.find((e) => e.id === endpointId) ?? null);
  const type = chosen ? (types.data ?? []).find((x) => x.key === chosen.trigger) : undefined;
  const topics = type ? Object.keys(type.topics) : [];
  // What the endpoint sends decides how the form shows its filter: a sender's endpoint waits for it to load.
  const needsTypes = chosen !== null && chosen.trigger !== null;
  const ready = !needsTypes || types.isSuccess;
  // By its topic: a new one for a sender with topics, or one whose filter is a topic alone; else by its conditions.
  const byTopic = !!type && topics.length > 0 && (!editing || topicOf(binding.filter, type) !== null);
  const [topic, setTopic] = useState<string | null>(null); // chosen here; until then, the binding's or the first
  const shownTopic = !byTopic ? null : topic !== null && topics.includes(topic) ? topic : editing ? topicOf(binding.filter, type) : (topics[0] ?? null);
  const [useShape, setUseShape] = useState(true);
  const [clauses, setClauses] = useState<Clause[]>(() => (binding?.filter ?? []).map((c) => ({ pointer: c.pointer, value: valueText(c.value) })));
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [refused, setRefused] = useState<string | null>(null);
  const [removing, setRemoving] = useState(false);
  const fields = inputRows(inputOf(t.doc)).length;
  const shaped = byTopic && type && shownTopic ? sameSchema(inputOf(t.doc), type.topics[shownTopic]) : false;
  const offerShape = byTopic && !!shownTopic && t.editable && !shaped;

  /** The conditions as the API takes them, or each one's problem. */
  function filter(): FilterClause[] | null {
    if (byTopic && type && shownTopic) return [{ pointer: type.topic_pointer, value: shownTopic }];
    const found: Record<number, string> = {};
    const out: FilterClause[] = [];
    clauses.forEach((c, i) => {
      const read = parseValue(c.value);
      if (!c.pointer.startsWith("/") || c.pointer.length > 256) found[i] = "A field is a pointer into the event, starting with /, like /type.";
      else if ("problem" in read) found[i] = read.problem;
      else out.push({ pointer: c.pointer, value: read.value });
    });
    setErrors(found);
    return Object.keys(found).length > 0 ? null : out;
  }

  const save = useMutation({
    mutationFn: (f: FilterClause[]) =>
      editing
        ? updateBinding(t.tenantId, binding.id, { filter: f })
        : createBinding(t.tenantId, chosen!.id, { workflow_id: t.workflowId, filter: f }),
    onMutate: () => setRefused(null),
    onSuccess: () => {
      if (!editing && offerShape && useShape && type && shownTopic) {
        const shape = type.topics[shownTopic];
        t.actions.update((d) => setSettings(d, { input_schema: shape }), `The input is now ${possessive(shownTopic)} shape, in the draft. Undo brings back what it replaced.`);
      }
      announce(editing ? `Saved the webhook from ${chosen?.name ?? "its endpoint"}` : `Added the webhook from ${chosen?.name ?? "the endpoint"}`);
      onDone(true);
    },
    onError: (e) => setRefused((e instanceof ApiError && REFUSALS[e.code]) || "The webhook couldn't be saved. Try again."),
  });
  const remove = useMutation({
    mutationFn: () => deleteBinding(t.tenantId, binding!.id),
    onSuccess: () => {
      setRemoving(false);
      announce(`Removed the webhook from ${binding?.endpoint.name ?? "its endpoint"}`);
      onDone(true);
    },
    onError: () => {
      setRemoving(false);
      setRefused("The webhook couldn't be removed. Try again.");
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!chosen) return setRefused("Choose an endpoint.");
    const f = filter();
    if (f) save.mutate(f);
  }

  const senderOf = (trigger: string | null) => {
    const x = (types.data ?? []).find((y) => y.key === trigger);
    return x ? senderName(x) : trigger ? "an unknown sender" : "another sender";
  };
  return (
    <form
      onSubmit={submit} aria-labelledby={`${id}-title`}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onDone(false);
        }
      }}
      className="flex flex-col gap-4 rounded-lg border border-line-strong p-3"
    >
      <h4 id={`${id}-title`} className="text-body font-semibold">{editing ? `The webhook from ${binding.endpoint.name}` : "New webhook"}</h4>
      {editing ? (
        <p className="text-small"><span className="font-semibold">Endpoint</span> {binding.endpoint.name} · {senderOf(binding.endpoint.trigger)}</p>
      ) : (
        <Select label="Endpoint" value={endpointId ?? ""} onChange={(e) => setEndpointId(e.target.value || null)} autoFocus>
          <option value="">Choose an endpoint</option>
          {choices.map((e) => (
            <option key={e.id} value={e.id} disabled={taken.has(e.id)}>
              {e.name} · {taken.has(e.id) ? "already starts this workflow" : `${senderOf(e.trigger)}${e.enabled ? "" : ", off"}`}
            </option>
          ))}
        </Select>
      )}
      {!editing && endpoints.isError && <p className="text-small text-danger">The endpoints couldn&apos;t be loaded. Try again.</p>}
      {chosen && !ready && !types.isError && <p className="text-small text-muted">Loading what this endpoint sends…</p>}
      {chosen && !ready && types.isError && (
        <div className="flex flex-wrap items-center gap-2">
          <p role="alert" className="text-small text-danger">What this endpoint sends couldn&apos;t be loaded, so its topics can&apos;t be shown.</p>
          <Button size="sm" disabled={types.isFetching} onClick={() => void types.refetch()}>Try again</Button>
        </div>
      )}
      {chosen && ready && byTopic && type && (
        <>
          <Select label="Topic" value={shownTopic ?? ""} onChange={(e) => setTopic(e.target.value)}>
            {topics.map((x) => <option key={x} value={x}>{x}</option>)}
          </Select>
          <p className="text-small text-muted">{senderName(type)} sends every topic you subscribe to one URL; this workflow runs for this one.</p>
          {!editing && offerShape && (
            <Check
              label="Use this topic's shape for the input" checked={useShape} disabled={false} onChange={setUseShape}
              hint={fields > 0 ? `Replaces the input's ${fields === 1 ? "field" : `${fields} fields`}, in the draft: Undo brings ${fields === 1 ? "it" : "them"} back.` : "In the draft: Undo brings back what it replaced."}
            />
          )}
        </>
      )}
      {chosen && ready && !byTopic && (
        <fieldset className="flex min-w-0 flex-col gap-2">
          <legend className="mb-1 text-small font-semibold">Runs for events where</legend>
          {type && topics.length > 0 && <p className="text-small text-muted">Its conditions aren&apos;t a topic alone: they&apos;re kept as they are, and change here.</p>}
          {clauses.map((c, i) => (
            <div key={i} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <input
                  aria-label={`Field ${i + 1}`} value={c.pointer} placeholder="/type" spellCheck={false} aria-invalid={!!errors[i]}
                  onChange={(e) => setClauses((x) => x.map((y, j) => (j === i ? { ...y, pointer: e.target.value } : y)))}
                  className={`${controlClass(!!errors[i])} w-auto min-w-0 flex-1 basis-32`}
                />
                <span className="text-small">is</span>
                <input
                  aria-label={`Value ${i + 1}`} value={c.value} spellCheck={false} aria-invalid={!!errors[i]}
                  onChange={(e) => setClauses((x) => x.map((y, j) => (j === i ? { ...y, value: e.target.value } : y)))}
                  className={`${controlClass(!!errors[i])} w-auto min-w-0 flex-1 basis-32`}
                />
                <Button size="sm" aria-label={`Remove condition ${i + 1}`} onClick={() => setClauses((x) => x.filter((_, j) => j !== i))}>×</Button>
              </div>
              {errors[i] && <p className="text-small text-danger">{errors[i]}</p>}
            </div>
          ))}
          <Button size="sm" className="self-start" disabled={clauses.length >= MAX_CLAUSES} onClick={() => setClauses((x) => [...x, { pointer: "", value: "" }])}>
            ＋ Condition
          </Button>
          <p className="text-small text-muted">
            All must hold, 8 at most. A field is a pointer into the event, like /type; 1 is a number and true a yes, as written, and &quot;1&quot; in quotes
            is text. No condition: every event.
          </p>
        </fieldset>
      )}
      {refused && <p role="alert" className="text-small text-danger">{refused}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" variant="primary" disabled={save.isPending || !chosen || !ready}>{editing ? "Save" : "Add the webhook"}</Button>
        <Button size="sm" onClick={() => onDone(false)}>Cancel</Button>
        {editing && <Button size="sm" variant="danger-outline" onClick={() => setRemoving(true)}>Remove the webhook…</Button>}
      </div>
      {!editing && (
        <p className="text-small text-muted">
          No endpoint yet?{" "}
          <Link to="/t/$tenantId/settings/webhooks" params={{ tenantId: t.tenantId }} className="text-accent-ink underline">Settings › Webhook endpoints</Link>{" "}
          makes one.
        </p>
      )}
      {editing && (
        <ConfirmDialog
          open={removing} title={`Remove the webhook from ${binding.endpoint.name}?`} confirmLabel="Remove the webhook"
          busy={remove.isPending} onConfirm={() => remove.mutate()} onCancel={() => setRemoving(false)}
        >
          Its events stop starting this workflow at once. The endpoint stays, for its other workflows.
        </ConfirmDialog>
      )}
    </form>
  );  // prettier-ignore
}
````

**Create** `frontend/src/routes/editor/triggers/WebhooksSection.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// A workflow's webhooks (4c-3b; the Webhooks and Rules boards; B13): each binding of an endpoint to this workflow, live
// and saved at once, its events running the published version. A webhook trigger's binding names its topic, and is
// compared with the published version's input: when that isn't the topic's shape, its events may be refused, and the
// topic's shape is offered for the draft (the owner's ruling: warned at the binding, in the editor). Another sender's
// events have no known shape: the input must fit them.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { LoadError } from "../../../components/LoadError";
import { Switch } from "../../../components/Switch";
import { announce } from "../../../lib/announce";
import { asGraph } from "../../../lib/graph";
import { inputOf, inputRows, sameSchema, setSettings } from "../../../lib/input";
import { bindingLine, possessive, topicOf, triggerTypesQuery, updateBinding, versionQuery, workflowBindingsQuery, type WorkflowBinding } from "../../../lib/triggers";
import { useTriggers } from "./context";
import { Section } from "./parts";
import { WebhookForm } from "./WebhookForm";

export function WebhooksSection() {
  const t = useTriggers();
  const qc = useQueryClient();
  const bindings = useQuery(workflowBindingsQuery(t.tenantId, t.workflowId));
  const types = useQuery(triggerTypesQuery);
  const active = useQuery({ ...versionQuery(t.tenantId, t.workflowId, t.activeVersionId ?? ""), enabled: t.activeVersionId !== null });
  const [open, setOpen] = useState<string | null>(null); // "new", or the id of the one being edited (a UUID)
  const [error, setError] = useState<string | null>(null);
  const adder = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["workflows", t.tenantId] });
    void qc.invalidateQueries({ queryKey: ["endpoint-bindings", t.tenantId] });
    return qc.invalidateQueries({ queryKey: ["workflow-bindings", t.tenantId, t.workflowId] });
  };
  const toggle = useMutation({
    mutationFn: (b: { id: string; name: string; enabled: boolean }) => updateBinding(t.tenantId, b.id, { enabled: b.enabled }),
    onMutate: () => setError(null),
    onSuccess: (_, b) => announce(`${b.name}: ${b.enabled ? "on: its events start runs" : "off: its events start no runs"}`),
    onError: (_, b) => setError(`${b.name} couldn't be switched ${b.enabled ? "on" : "off"}. Try again.`),
    onSettled: refresh,
  });
  const published = t.activeNumber !== null;
  const list = bindings.data?.bindings ?? [];
  const typeOf = (b: WorkflowBinding) => (types.data ?? []).find((x) => x.key === b.endpoint.trigger);
  const activeInput = active.data ? inputOf(asGraph(active.data.graph)) : null;

  /** What a binding's events meet: nothing before a publish, a known shape the published input may not be, or an
   * unknown one the input must fit. */
  function fit(b: WorkflowBinding) {
    if (!published) return <span className="text-small text-warn-ink">Events are refused until a version is published, and listed as refused in the endpoint&apos;s events.</span>;
    const type = typeOf(b);
    const topic = topicOf(b.filter, type);
    if (!type || !topic) return <span className="text-small text-muted">Its events have no known shape: the input must fit them, or each is refused.</span>;
    const shape = type.topics[topic];
    if (activeInput === null || sameSchema(activeInput, shape)) return null;
    const fields = inputRows(activeInput).length;
    const inDraft = sameSchema(inputOf(t.doc), shape);
    return (
      <div className="flex flex-col gap-1.5">
        <span className="text-small text-warn-ink">
          Version {t.activeNumber}&apos;s input isn&apos;t {possessive(topic)} shape{fields > 0 ? ` (it has ${fields === 1 ? "1 form field" : `${fields} form fields`})` : ""}: events it doesn&apos;t fit are refused.
        </span>
        {inDraft ? (
          <span className="text-small text-muted">In the draft: it applies once published.</span>
        ) : t.editable ? (
          <Button
            size="sm" className="self-start"
            onClick={() => t.actions.update((d) => setSettings(d, { input_schema: shape }), `The input is now ${possessive(topic)} shape, in the draft: it applies once published. Undo brings back what it replaced.`)}
          >
            Use {possessive(topic)} shape for the input
          </Button>
        ) : null}
      </div>
    );  // prettier-ignore
  }

  const close = (saved: boolean) => {
    setOpen(null);
    if (saved) void refresh();
    requestAnimationFrame(() => (adder.current ?? heading.current)?.focus());
  };
  return (
    <Section id="triggers-webhooks" title="Webhooks" heading={heading} note={published ? `Live · events run version ${t.activeNumber}` : "Live"}>
      {error && <p role="alert" className="text-small text-danger">{error}</p>}
      {bindings.isError && <LoadError what="The webhooks" />}
      {bindings.isSuccess && list.length === 0 && open !== "new" && <p className="text-small text-muted">No webhook starts this workflow.</p>}
      <ul className="flex flex-col">
        {list.map((b) => (
          <li key={b.id} className="flex flex-col gap-1.5 border-t border-line py-2.5 first:border-t-0">
            {open === b.id ? (
              <WebhookForm binding={b} onDone={close} />
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="min-w-0 text-body font-medium">{b.endpoint.name}</span>
                  <span className="flex items-center gap-2">
                    {t.manage ? (
                      <>
                        <Switch checked={b.enabled} label={b.endpoint.name} disabled={toggle.isPending} onCheckedChange={(enabled) => toggle.mutate({ id: b.id, name: b.endpoint.name, enabled })} />
                        <Button size="sm" aria-label={`Edit ${b.endpoint.name}`} onClick={() => setOpen(b.id)}>Edit</Button>
                      </>
                    ) : (
                      <span className="text-small">{b.enabled ? "On" : "Off"}</span>
                    )}
                  </span>
                </div>
                <span className="text-small text-muted">{bindingLine(b, types.data ?? [])}</span>
                {!b.endpoint.enabled && <span className="text-small text-warn-ink">Its endpoint is off: events sent to it are refused.</span>}
                {fit(b)}
              </>
            )}
          </li>
        ))}
      </ul>
      {open === "new" ? (
        <WebhookForm binding={null} onDone={close} />
      ) : t.manage ? (
        <Button ref={adder} size="sm" className="self-start" onClick={() => setOpen("new")}>＋ Webhook</Button>
      ) : null}
    </Section>
  );  // prettier-ignore
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/triggers`

Expected: PASS: `Test Files  3 passed (3)`, `Tests  53 passed (53)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/triggers/TriggersPanel.tsx \
  frontend/src/routes/editor/triggers/WebhookForm.tsx \
  frontend/src/routes/editor/triggers/WebhooksSection.test.tsx \
  frontend/src/routes/editor/triggers/WebhooksSection.tsx
git commit -m "feat(editor): a workflow's webhooks, and their form (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Milestone 3's checks.** The whole unit suite, typecheck and lint; append `### 4c-3b, milestone 3 (<date>)` to
  the ledger and commit it. No pause.

---

# Milestone 4 — New workflow and the list

### Task 12: New workflow: what starts it

1b's "What starts it?" (ruling 11): By hand, On a schedule, A Mist webhook (an endpoint and a topic), A CSV file; then
Blank or Import from file; then the name. It seeds the draft, binds the webhook at once, and opens the new workflow on
its Triggers (`?triggers`); what fails once the workflow is made is said, with the way to open it.

**Files:**
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/routes/NewWorkflow.test.tsx`
- Modify: `frontend/src/routes/NewWorkflow.tsx`
- Modify: `frontend/src/routes/editor/Editor.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Modify: `frontend/src/routes/editor/LazyEditor.tsx`

**Interfaces:**
- Consumes: Tasks 3, 4 and 7.
- Produces: the editor route's search `{ triggers?: true }`; `EditorPage`'s and `LazyEditor`'s `openTriggers`.

- [ ] **Step 1: Write the failing tests**

**In** `frontend/src/routes/NewWorkflow.test.tsx`, **replace**:

````tsx
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { onAnnounce } from "../lib/announce";
````

**with**:

````tsx
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { onAnnounce } from "../lib/announce";
````

**In** `frontend/src/routes/NewWorkflow.test.tsx`, **replace**:

````tsx
import { NewWorkflow, parseDocument } from "./NewWorkflow";

````

**with**:

````tsx
import { DEVICE_EVENTS, MIST } from "../test/triggers";
import { fakeApi, json } from "./editor/drawer/harness";
import { NewWorkflow, parseDocument } from "./NewWorkflow";

````

**In** `frontend/src/routes/NewWorkflow.test.tsx`, **replace**:

````tsx
it("starts blank from a name, and opens the editor", async () => {
  const router = await show();
  expect(document.activeElement).toBe(screen.getByLabelText("Name"));
  await userEvent.type(screen.getByLabelText("Name"), "Nightly report");
  await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
````

**with**:

````tsx
it("starts blank from a name, and opens the editor", async () => {
  const router = await show();
  expect(document.activeElement).toBe(screen.getByRole("radio", { name: /^By hand/ })); // what starts it comes first
  await userEvent.type(screen.getByLabelText("Name"), "Nightly report");
  await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
````

**In** `frontend/src/routes/NewWorkflow.test.tsx`, **replace**:

````tsx
  expect(screen.getByDisplayValue("My own name")).toBeTruthy();
});
````

**with**:

````tsx
  expect(screen.getByDisplayValue("My own name")).toBeTruthy();
});

describe("what starts it (4c-3b)", () => {
  const ENDPOINT = { id: "e1", name: "Mist prod", enabled: true, auth: "bearer", trigger: "mist.webhook", path: "/hooks/e1" };
  const CREATED = { id: "w9", name: "AP offline report", draft_revision: 1, draft: { graph_format: 1, nodes: [], edges: [] } };

  function api(more: Record<string, () => Response | Promise<Response>> = {}) {
    vi.restoreAllMocks();
    return fakeApi({
      "GET /api/v1/trigger-types": () => json([MIST]),
      "GET /api/v1/t/t1/webhook-endpoints": () => json({ endpoints: [ENDPOINT] }),
      "GET /api/v1/t/t1/connections": () => json([]),
      "POST /api/v1/t/t1/workflows": () => json(CREATED, 201),
      "PUT /api/v1/t/t1/workflows/w9/draft": () => json({ draft_revision: 2, unpublished_changes: true, graph_hash: "h", active_version_id: null, active_version_number: null }),
      "POST /api/v1/t/t1/webhook-endpoints/e1/bindings": () => json({ id: "b1" }, 201),
      ...more,
    });
  }

  it("seeds a Mist webhook's topic shape, binds its endpoint at once, and opens the workflow on its Triggers", async () => {
    const sent = api();
    const router = await show();
    await userEvent.click(await screen.findByRole("radio", { name: /^A Mist webhook/ }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Topic" }), "device-events");
    await userEvent.type(screen.getByLabelText("Name"), "AP offline report");
    expect(screen.getByRole("dialog").textContent).toContain("It opens on its Triggers: the input is device-events' shape, and the webhook is bound to Mist prod.");
    await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w9"));
    expect(router.state.location.search).toEqual({ triggers: true });
    const put = sent.find((r) => r.method === "PUT");
    expect((put?.body as { settings: unknown }).settings).toEqual({ input_schema: DEVICE_EVENTS });
    expect(sent.find((r) => r.path.endsWith("/bindings"))?.body).toEqual({ workflow_id: "w9", filter: [{ pointer: "/topic", value: "device-events" }] });
  });

  it("seeds a CSV file of one column", async () => {
    const sent = api();
    await show();
    await userEvent.click(screen.getByRole("radio", { name: /^A CSV file/ }));
    await userEvent.type(screen.getByLabelText("Name"), "Bulk rename");
    await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
    await vi.waitFor(() => expect(sent.find((r) => r.method === "PUT")).toBeTruthy());
    expect((sent.find((r) => r.method === "PUT")?.body as { settings: unknown }).settings).toEqual({ csv: { columns: [{ header: "Column 1", name: "column_1", type: "string" }] } });
  });

  it("keeps an imported file's input, and still binds its webhook", async () => {
    const sent = api({ "POST /api/v1/t/t1/workflows/import": () => json(CREATED, 201) });
    await show();
    await userEvent.click(await screen.findByRole("radio", { name: /^A Mist webhook/ }));
    await userEvent.click(screen.getByRole("radio", { name: /^Import from file/ }));
    expect(screen.getByRole("dialog").textContent).toContain("An imported workflow keeps its own input; its Triggers say if the webhook's events don't fit it.");
    const file = new File([JSON.stringify({ ...DOC, bindings: [] })], "flow.dewpoint.json", { type: "application/json" });
    await userEvent.upload(screen.getByLabelText("Workflow file"), file);
    await userEvent.click(await screen.findByRole("button", { name: "Import and open" }));
    await vi.waitFor(() => expect(sent.some((r) => r.path.endsWith("/bindings"))).toBe(true));
    expect(sent.some((r) => r.method === "PUT")).toBe(false);
  });

  it("says what was made and what wasn't when its webhook isn't bound, with the way to open it", async () => {
    api({ "POST /api/v1/t/t1/webhook-endpoints/e1/bindings": () => json({ error: "binding_cap" }, 409) });
    const router = await show();
    await userEvent.click(await screen.findByRole("radio", { name: /^A Mist webhook/ }));
    await userEvent.type(screen.getByLabelText("Name"), "AP offline report");
    await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
    const said = await screen.findByRole("alert");
    expect(said.textContent).toContain("Created AP offline report, but its webhook from Mist prod wasn't added: open it, and add it in its Triggers.");
    await userEvent.click(screen.getByRole("button", { name: "Open AP offline report" }));
    await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w9"));
  });

  it("offers a Mist webhook only once there's an endpoint for it, and says where one is made", async () => {
    api({ "GET /api/v1/t/t1/webhook-endpoints": () => json({ endpoints: [] }) });
    await show();
    await vi.waitFor(() => expect(screen.getByRole<HTMLInputElement>("radio", { name: /^A Mist webhook/ }).disabled).toBe(true));
    expect(screen.getByRole("dialog").textContent).toContain("No endpoint for it yet: Settings › Webhook endpoints makes one.");
  });
});
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
  it.each([
    { what: "a hash", to: { hash: "notes" } },
    { what: "a query", to: { search: { panel: "versions" } } },
  ])("leave it editable when only $what changes", async ({ to }) => {
    const { router } = await show();
````

**with**:

````tsx
  it.each([
    { what: "a hash", to: { hash: "notes" } },
    { what: "a query", to: { search: { triggers: true as const } } },
  ])("leave it editable when only $what changes", async ({ to }) => {
    const { router } = await show();
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`):
`npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/NewWorkflow.test.tsx src/routes/editor/Editor.test.tsx src/router.test.tsx`

Expected: FAIL: `Test Files  1 failed | 2 passed (3)`, `Tests  6 failed | 178 passed (184)`. The failing tests are this
task's new and changed ones: `starts blank from a name, and opens the editor`, `seeds a Mist webhook's topic shape,
binds its endpoint at once, and opens the workflow on its Triggers`, `seeds a CSV file of one column`, `keeps an
imported file's input, and still binds its webhook`, `says what was made and what wasn't when its webhook isn't bound,
with the way to open it`, `offers a Mist webhook only once there's an endpoint for it, and says where one is made`.

- [ ] **Step 3: Write the code**

**In** `frontend/src/router.tsx`, **replace**:

````tsx
function Editor() {
  const { tenantId, workflowId } = useParams({ from: "/app/t/$tenantId/workflows/$workflowId" });
  return <LazyEditor key={`${tenantId}:${workflowId}`} tenantId={tenantId} workflowId={workflowId} />;
}

````

**with**:

````tsx
function Editor() {
  const { tenantId, workflowId } = useParams({ from: "/app/t/$tenantId/workflows/$workflowId" });
  const search = editorRoute.useSearch();
  return <LazyEditor key={`${tenantId}:${workflowId}`} tenantId={tenantId} workflowId={workflowId} openTriggers={search.triggers === true} />;
}

````

**In** `frontend/src/router.tsx`, **replace**:

````tsx
  component: Editor,
  staticData: { compactRail: true },
});
const connectionsRoute = createRoute({
````

**with**:

````tsx
  component: Editor,
  staticData: { compactRail: true },
  // A new workflow opens on its Triggers (4c-3b, 1b's "What starts it?").
  validateSearch: (search: Record<string, unknown>): { triggers?: true } =>
    search.triggers === true || search.triggers === "true" ? { triggers: true } : {},
});
const connectionsRoute = createRoute({
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// "New workflow" (screen 1b; 4b ruling 1): a name, then Blank or Import from file. The trigger step ("What starts
// it?") comes with 4c's trigger setup, "Describe it" with sub-project 5; "From template" waits for curated templates
// (D9). A native modal dialog (D23): focus moves in and back, Escape closes.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "../components/Button";
````

**with**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// "New workflow" (screen 1b; 4b ruling 1; 4c-3b's "What starts it?", the NewWorkflow board): what starts it, then
// Blank or Import from file, then a name. What starts it seeds the draft and opens the new workflow on its Triggers: a
// Mist webhook gives the input its topic's shape and binds the endpoint at once; a CSV file declares one column to
// define; a schedule waits for a first version. An imported file keeps its own input (the owner's ruling), its webhook
// still bound. "Describe it" comes with sub-project 5; "From template" waits for curated templates (D9). A native modal
// dialog (D23): focus moves in and back, Escape closes.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Button } from "../components/Button";
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
import { Field } from "../components/Field";
import { announce } from "../lib/announce";
import { ApiError, client, ok } from "../lib/client";
````

**with**:

````tsx
import { Field, Select } from "../components/Field";
import { announce } from "../lib/announce";
import { ApiError, client, ok } from "../lib/client";
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
import type { WorkflowDocument } from "../lib/workflows";
import { ImportBindings, UNBOUND, useBindingChoices, type Chosen } from "./ImportBindings";

````

**with**:

````tsx
import { newCsv } from "../lib/csv";
import { asGraph } from "../lib/graph";
import { setSettings } from "../lib/input";
import { createBinding, endpointsQuery, possessive, senderName, triggerTypesQuery } from "../lib/triggers";
import type { WorkflowDetail, WorkflowDocument } from "../lib/workflows";
import { ImportBindings, UNBOUND, useBindingChoices, type Chosen } from "./ImportBindings";

````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
type Start = "blank" | "import";

// The API's `WorkflowDocument`, `Binding` and `BindingSite` (Task 5), mirrored: a file that passes here passes the
````

**with**:

````tsx
type Start = "blank" | "import";
type Trigger = "hand" | "schedule" | "webhook" | "csv";

// The API's `WorkflowDocument`, `Binding` and `BindingSite` (Task 5), mirrored: a file that passes here passes the
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
  Object.fromEntries(Object.entries(chosen).filter(([, value]) => value !== UNBOUND));

const CHOICE = "flex cursor-pointer flex-col gap-1 rounded-lg border border-line-strong bg-surface p-4 has-[:checked]:border-accent has-[:checked]:bg-accent-soft";

export function NewWorkflow({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
````

**with**:

````tsx
  Object.fromEntries(Object.entries(chosen).filter(([, value]) => value !== UNBOUND));

const CHOICE = "flex cursor-pointer flex-col gap-1 rounded-lg border border-line-strong bg-surface p-4 has-[:checked]:border-accent has-[:checked]:bg-accent-soft has-[:disabled]:cursor-not-allowed";

/** A workflow made, and what of its triggers wasn't: the dialog stays to say so, with the way to open it. */
type Partly = { wf: WorkflowDetail; missed: string };

export function NewWorkflow({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [start, setStart] = useState<Start>("blank");
  const [doc, setDoc] = useState<WorkflowDocument | null>(null);
````

**with**:

````tsx
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState<Trigger>("hand");
  const [start, setStart] = useState<Start>("blank");
  const [doc, setDoc] = useState<WorkflowDocument | null>(null);
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
  const [chosen, setChosen] = useState<Chosen>({});
  const [error, setError] = useState<string | null>(null);
  const choices = useBindingChoices(tenantId, doc?.bindings ?? []);
  const [reading, setReading] = useState(false);
````

**with**:

````tsx
  const [chosen, setChosen] = useState<Chosen>({});
  const [error, setError] = useState<string | null>(null);
  const [partly, setPartly] = useState<Partly | null>(null);
  const choices = useBindingChoices(tenantId, doc?.bindings ?? []);
  const [reading, setReading] = useState(false);
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
  const selection = useRef(0); // the latest file chosen: an earlier one's read, answering late, changes nothing
  // Whether this dialog still speaks for the screen. Once it's dismissed, or gone with its tenant's screen, a creation
  // that answers late refreshes that tenant's list but neither opens the workflow nor announces it. Dismissing never
````

**with**:

````tsx
  const selection = useRef(0); // the latest file chosen: an earlier one's read, answering late, changes nothing
  // The webhook trigger plugins declare (Mist's), and this tenant's endpoints made for it.
  const types = useQuery(triggerTypesQuery);
  const endpoints = useQuery(endpointsQuery(tenantId));
  const webhook = (types.data ?? []).find((t) => Object.keys(t.topics).length > 0);
  const senders = (endpoints.data?.endpoints ?? []).filter((e) => webhook && e.trigger === webhook.key);
  const [endpointId, setEndpointId] = useState<string | null>(null);
  const [topic, setTopic] = useState<string | null>(null);
  const endpoint = senders.find((e) => e.id === endpointId) ?? senders[0] ?? null;
  const topics = webhook ? Object.keys(webhook.topics) : [];
  const shownTopic = topic ?? topics[0] ?? null;
  // Whether this dialog still speaks for the screen. Once it's dismissed, or gone with its tenant's screen, a creation
  // that answers late refreshes that tenant's list but neither opens the workflow nor announces it. Dismissing never
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLInputElement>("input[name='name']")?.focus();
    }
  }, []);
````

**with**:

````tsx
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLInputElement>("input[name='trigger']:checked")?.focus();
    }
  }, []);
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx

  const create = useMutation({
````

**with**:

````tsx

  const open = (wf: WorkflowDetail) =>
    navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: wf.id }, search: { triggers: true } });

  /** The new draft seeded with what starts it: a webhook topic's shape, or a CSV file of one column. An import keeps
   * its own input. */
  async function seed(wf: WorkflowDetail) {
    if (start !== "blank" || (trigger !== "webhook" && trigger !== "csv")) return;
    const draft = asGraph(wf.draft);
    const next = trigger === "csv" ? setSettings(draft, { csv: newCsv() }) : setSettings(draft, { input_schema: webhook!.topics[shownTopic!] });
    await ok(
      client.PUT("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft", {
        params: { path: { tenant_id: tenantId, workflow_id: wf.id }, header: { "If-Match": String(wf.draft_revision) } },
        body: next,
      }),
    );
  }

  const create = useMutation({
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
    mutationFn: () => {
      const path = { params: { path: { tenant_id: tenantId } } };
````

**with**:

````tsx
    mutationFn: async () => {
      const path = { params: { path: { tenant_id: tenantId } } };
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
      return start === "blank"
        ? ok(client.POST("/api/v1/t/{tenant_id}/workflows", { ...path, body: { name: name.trim() } }))
        : ok(client.POST("/api/v1/t/{tenant_id}/workflows/import", { ...path, body: { name: name.trim(), document: doc!, bind: bound(chosen) } }));
    },
    onMutate: () => setError(null),
````

**with**:

````tsx
      const wf = start === "blank"
        ? await ok(client.POST("/api/v1/t/{tenant_id}/workflows", { ...path, body: { name: name.trim() } }))
        : await ok(client.POST("/api/v1/t/{tenant_id}/workflows/import", { ...path, body: { name: name.trim(), document: doc!, bind: bound(chosen) } }));  // prettier-ignore
      // Made: what follows can fail without unmaking it, and says so (the dialog stays, with the way to open it).
      try {
        await seed(wf);
      } catch {
        return { wf, missed: trigger === "csv" ? "its CSV file wasn't added" : `its input wasn't given ${possessive(shownTopic ?? "the topic")} shape` };
      }
      if (trigger === "webhook" && endpoint && webhook && shownTopic) {
        try {
          await createBinding(tenantId, endpoint.id, { workflow_id: wf.id, filter: [{ pointer: webhook.topic_pointer, value: shownTopic }] });
        } catch {
          return { wf, missed: `its webhook from ${endpoint.name} wasn't added` };
        }
      }
      return { wf, missed: null };
    },
    onMutate: () => setError(null),
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
    onSuccess: async (wf) => {
      await qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
      if (!live.current) return;
````

**with**:

````tsx
    onSuccess: async ({ wf, missed }) => {
      await qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
      if (!live.current) return;
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
      announce(`Created ${wf.name}`);
      dialog.current?.close();
````

**with**:

````tsx
      if (missed) {
        setPartly({ wf, missed });
        announce(`Created ${wf.name}, but ${missed}`);
        return;
      }
      announce(`Created ${wf.name}`);
      dialog.current?.close();
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
      await navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: wf.id } });
    },
    onError: (e) => setError(explain(e, doc)),
````

**with**:

````tsx
      await open(wf);
    },
    onError: (e) => setError(explain(e, doc)),
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx

  // An import waits for what its bindings are chosen from, and for a choice for each: unbound is chosen, never the
  // default, nor a lookup that failed (ruling 28).
  const chosenAll = doc !== null && doc.bindings.every((b) => chosen[b.id] !== undefined);
````

**with**:

````tsx

  // An import waits for what its bindings are chosen from, and for a choice for each: unbound is chosen, never the
  // default, nor a lookup that failed (ruling 28). A webhook waits for its endpoint and topic.
  const chosenAll = doc !== null && doc.bindings.every((b) => chosen[b.id] !== undefined);
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
  const ready = name.trim().length > 0 && (start === "blank" || (chosenAll && choices.state === "ready"));

  return (
````

**with**:

````tsx
  const webhookReady = trigger !== "webhook" || (endpoint !== null && shownTopic !== null);
  const ready = name.trim().length > 0 && webhookReady && (start === "blank" || (chosenAll && choices.state === "ready"));
  const sender = webhook ? senderName(webhook) : null;
  const opens =
    trigger === "webhook" && endpoint && shownTopic
      ? start === "blank"
        ? `It opens on its Triggers: the input is ${possessive(shownTopic)} shape, and the webhook is bound to ${endpoint.name}.`
        : `It opens on its Triggers, its webhook bound to ${endpoint.name}; the file's input stays as it is.`
      : trigger === "csv" ? "It opens on its Triggers, with a CSV file of one column to define."
      : trigger === "schedule" ? "It opens on its Triggers: a schedule can be added once a first version is published."
      : "It opens on its Triggers: by hand, its input is the run's form.";  // prettier-ignore

  const radio = (value: Trigger, label: string, hint: string, disabled = false, extra?: ReactNode) => (
    <label className={CHOICE}>
      <span className="flex items-center gap-2">
        <input type="radio" name="trigger" value={value} checked={trigger === value} disabled={disabled} onChange={() => setTrigger(value)} />
        <span className="font-semibold">{label}</span>
      </span>
      <span className="text-small text-muted">{hint}</span>
      {extra}
    </label>
  );  // prettier-ignore

  return (
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
      <form onSubmit={submit} className="flex flex-col gap-5">
        <h2 id="new-workflow-title" className="text-h3 font-semibold">New workflow</h2>
        <Field label="Name" name="name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <fieldset className="flex flex-col gap-2">
````

**with**:

````tsx
      <form onSubmit={submit} className="flex flex-col gap-5">
        <h2 id="new-workflow-title" className="text-h3 font-semibold">New workflow</h2>
        <fieldset className="flex flex-col gap-2">
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
          <legend className="mb-1 text-small font-semibold">How do you want to start?</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className={CHOICE}>
````

**with**:

````tsx
          <legend className="mb-1 text-small font-semibold">What starts it?</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {radio("hand", "By hand", "Someone starts it, filling in a form.")}
            {radio("schedule", "On a schedule", "Set once a first version is published.")}
            {radio(
              "webhook", sender ? `A ${sender} webhook` : "A webhook",
              senders.length > 0 ? `Runs for each event of a topic ${sender ?? "it"} sends.` : "No endpoint for it yet: Settings › Webhook endpoints makes one.",
              senders.length === 0,
              trigger === "webhook" && senders.length > 0 && (
                <span className="flex flex-col gap-2 pt-1">
                  <Select label="Endpoint" value={endpoint?.id ?? ""} onChange={(e) => setEndpointId(e.target.value)}>
                    {senders.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                  </Select>
                  <Select label="Topic" value={shownTopic ?? ""} onChange={(e) => setTopic(e.target.value)}>
                    {topics.map((t) => <option key={t} value={t}>{t}</option>)}
                  </Select>
                </span>
              ),
            )}
            {radio("csv", "A CSV file", "Someone starts it with a file: one run reads its rows.")}
          </div>
        </fieldset>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-small font-semibold">Then</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className={CHOICE}>
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
                <span className="font-semibold">Import from file</span>
              </span>
              <span className="text-small text-muted">A workflow exported from Dewpoint. Its connections are bound to yours.</span>
            </label>
          </div>
````

**with**:

````tsx
                <span className="font-semibold">Import from file</span>
              </span>
              <span className="text-small text-muted">
                A workflow exported from Dewpoint. Its connections are bound to yours.
                {trigger === "webhook" && " An imported workflow keeps its own input; its Triggers say if the webhook's events don't fit it."}
              </span>
            </label>
          </div>
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
          </div>
        )}
        {error && <p role="alert" className="text-body text-danger">{error}</p>}
````

**with**:

````tsx
          </div>
        )}
        <Field label="Name" name="name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <p className="text-small text-muted">{opens}</p>
        {trigger === "webhook" && senders.length === 0 && (
          <p className="text-small">
            <Link to="/t/$tenantId/settings/webhooks" params={{ tenantId }} className="text-accent-ink underline">Settings › Webhook endpoints</Link> makes one.
          </p>
        )}
        {error && <p role="alert" className="text-body text-danger">{error}</p>}
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
        <div className="flex justify-end gap-2">
          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
````

**with**:

````tsx
        {partly && (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-body text-danger">
            <span>Created {partly.wf.name}, but {partly.missed}: open it, and add it in its Triggers.</span>
            <Button size="sm" onClick={() => {
              dialog.current?.close();
              void open(partly.wf);
            }}>
              Open {partly.wf.name}
            </Button>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
          <Button variant="primary" type="submit" disabled={!ready || create.isPending}>
            {start === "blank" ? "Create and open" : "Import and open"}
          </Button>
````

**with**:

````tsx
          <Button variant="primary" type="submit" disabled={!ready || create.isPending || partly !== null}>
            {start === "blank" ? "Create and open" : "Import and open"}
          </Button>
````

**In** `frontend/src/routes/NewWorkflow.tsx`, **replace**:

````tsx
      </form>
    </dialog>
  );
}
````

**with**:

````tsx
      </form>
    </dialog>
  );  // prettier-ignore
}
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
};

export function EditorPage({ tenantId, workflowId }: { tenantId: string; workflowId: string }) {
  const qc = useQueryClient();
  // A draft cached from an earlier visit would conflict on the first edit (4b ruling 23): the editor waits for the read
````

**with**:

````tsx
};

export function EditorPage({ tenantId, workflowId, openTriggers = false }: { tenantId: string; workflowId: string; openTriggers?: boolean }) {
  const qc = useQueryClient();
  // A draft cached from an earlier visit would conflict on the first edit (4b ruling 23): the editor waits for the read
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
      role={opened.role}
      trouble={trouble}
      onReload={() => void reload()}
    />
````

**with**:

````tsx
      role={opened.role}
      trouble={trouble}
      openTriggers={openTriggers && loads === 0}
      onReload={() => void reload()}
    />
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx

function Editor({
  tenantId, workflow, types, role, trouble, onReload,
}: {
  tenantId: string; workflow: WorkflowDetail; types: NodeType[]; role: string | null; trouble: string | null;
````

**with**:

````tsx

function Editor({
  tenantId, workflow, types, role, trouble, openTriggers, onReload,
}: {
  tenantId: string; workflow: WorkflowDetail; types: NodeType[]; role: string | null; trouble: string | null;
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  onReload: () => void;
}) {  // prettier-ignore
  const typeMap = useMemo(() => new Map(types.map((t) => [t.ref, t])), [types]);
````

**with**:

````tsx
  openTriggers: boolean; onReload: () => void;
}) {  // prettier-ignore
  const typeMap = useMemo(() => new Map(types.map((t) => [t.ref, t])), [types]);
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  };
  const typeOf = (n: GraphNode) => typeMap.get(n.type);
  const [side, setSide] = useState<Side>(null); // the right column's one panel
  // Where focus lands when what held it goes: a panel's Close, or a confirmation whose button an action removed or
  // disabled (the final checkpoint's review, WCAG 2.4.3). A native dialog returns focus to its opener only while that
````

**with**:

````tsx
  };
  const typeOf = (n: GraphNode) => typeMap.get(n.type);
  const [side, setSide] = useState<Side>(() => (openTriggers ? { kind: "triggers" } : null)); // the right column's one panel
  // Where focus lands when what held it goes: a panel's Close, or a confirmation whose button an action removed or
  // disabled (the final checkpoint's review, WCAG 2.4.3). A native dialog returns focus to its opener only while that
````

**In** `frontend/src/routes/editor/LazyEditor.tsx`, **replace**:

````tsx
import { Button } from "../../components/Button";

type Props = { tenantId: string; workflowId: string };
export type EditorModule = { EditorPage: ComponentType<Props> };

````

**with**:

````tsx
import { Button } from "../../components/Button";

type Props = { tenantId: string; workflowId: string; openTriggers?: boolean };
export type EditorModule = { EditorPage: ComponentType<Props> };

````

- [ ] **Step 4: Run them to see them pass**

Run:
`npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/NewWorkflow.test.tsx src/routes/editor/Editor.test.tsx src/router.test.tsx`

Expected: PASS: `Test Files  3 passed (3)`, `Tests  184 passed (184)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/router.tsx \
  frontend/src/routes/NewWorkflow.test.tsx \
  frontend/src/routes/NewWorkflow.tsx \
  frontend/src/routes/editor/Editor.test.tsx \
  frontend/src/routes/editor/Editor.tsx \
  frontend/src/routes/editor/LazyEditor.tsx
git commit -m "feat(workflows): New workflow asks what starts it, and opens on its Triggers (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 13: The list's Trigger column

The list names what starts each workflow besides a person, and why one needs attention, under its name (ruling 12).

**Files:**
- Modify: `frontend/src/routes/Workflows.test.tsx`
- Modify: `frontend/src/routes/Workflows.tsx`

**Interfaces:**
- Consumes: `triggerColumn`, `attentionWords` (Task 3).
- Produces: nothing new.

- [ ] **Step 1: Write the failing tests**

**In** `frontend/src/routes/Workflows.test.tsx`, **replace**:

````tsx
  executable: true, blocked_by: [], created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-06T10:00:00Z",
  unpublished_changes: false, last_run: { status: "succeeded", at: "2026-10-06T11:48:00Z" }, last_simulation: null,
  runs_24h: { live: 4, simulate: 0 }, needs_attention: [], ...over,
});  // prettier-ignore
const ROWS = [
````

**with**:

````tsx
  executable: true, blocked_by: [], created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-06T10:00:00Z",
  unpublished_changes: false, last_run: { status: "succeeded", at: "2026-10-06T11:48:00Z" }, last_simulation: null,
  runs_24h: { live: 4, simulate: 0 }, needs_attention: [], triggers: { schedules: 0, schedules_enabled: 0, webhook_bindings: 0, csv: false }, ...over,
});  // prettier-ignore
const ROWS = [
````

**In** `frontend/src/routes/Workflows.test.tsx`, **replace**:

````tsx
    if (request.method === "PATCH") return patchAnswer ?? new Response(JSON.stringify({ ...ROWS[0], enabled: false, warnings: [] }));
    if (path === "/api/v1/t/t1") return new Response(JSON.stringify({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }));
    if (path === "/api/v1/t/t1/workflows/w2/export") return exportAnswer ?? new Response(JSON.stringify({ format: "dewpoint.workflow", format_version: 1, name: "Triage", graph: {}, bindings: [] }));
    return new Response(JSON.stringify(ROWS));
````

**with**:

````tsx
    if (request.method === "PATCH") return patchAnswer ?? new Response(JSON.stringify({ ...ROWS[0], enabled: false, warnings: [] }));
    if (path === "/api/v1/t/t1") return new Response(JSON.stringify({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }));
    if (path === "/api/v1/trigger-types") return new Response("[]"); // what New workflow offers to start it
    if (path === "/api/v1/t/t1/webhook-endpoints") return new Response(JSON.stringify({ endpoints: [] }));
    if (path === "/api/v1/t/t1/workflows/w2/export") return exportAnswer ?? new Response(JSON.stringify({ format: "dewpoint.workflow", format_version: 1, name: "Triage", graph: {}, bindings: [] }));
    return new Response(JSON.stringify(ROWS));
````

**In** `frontend/src/routes/Workflows.test.tsx`, **replace**:

````tsx
  expect(screen.queryByRole("button", { name: "New workflow" })).toBeNull();
});
````

**with**:

````tsx
  expect(screen.queryByRole("button", { name: "New workflow" })).toBeNull();
});

it("names what starts each workflow besides a person, and says why one needs attention, as the WorkflowsList board does", async () => {
  vi.mocked(globalThis.fetch).mockImplementation((input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    if (path === "/api/v1/t/t1") return Promise.resolve(new Response(JSON.stringify({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role })));
    return Promise.resolve(new Response(JSON.stringify([
      row({ triggers: { schedules: 0, schedules_enabled: 0, webhook_bindings: 1, csv: false } }),
      row({ id: "w2", name: "Triage", needs_attention: ["last_run_failed"], triggers: { schedules: 2, schedules_enabled: 2, webhook_bindings: 1, csv: false } }),
      row({ id: "w3", name: "Audit", needs_attention: ["schedule_sync_failed"], triggers: { schedules: 1, schedules_enabled: 1, webhook_bindings: 0, csv: false } }),
      row({ id: "w4", name: "Rename", triggers: { schedules: 0, schedules_enabled: 0, webhook_bindings: 0, csv: true } }),
    ])));
  });
  await show();
  expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Name", "Trigger", "Version", "Last run", "Last 24 h", "Enabled", "Actions"]);
  expect(rowOf("Nightly").cells[1]!.textContent).toBe("Webhook");
  expect(rowOf("Triage").cells[1]!.textContent).toBe("2 schedules · 1 webhook");
  expect(rowOf("Triage").cells[0]!.textContent).toContain("Needs attention: its last run failed.");
  expect(rowOf("Audit").cells[0]!.textContent).toContain("Needs attention: a schedule couldn't be synced.");
  expect(rowOf("Rename").cells[1]!.textContent).toBe("CSV file");
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/Workflows.test.tsx`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  1 failed | 9 passed (10)`. The failing tests are this task's new and
changed ones: `names what starts each workflow besides a person, and says why one needs attention, as the WorkflowsList
board does`.

- [ ] **Step 3: Write the code**

**In** `frontend/src/routes/Workflows.tsx`, **replace**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The workflows list (screen 1a; 4b rulings 4-7): each workflow's state at a glance, filters, the enable switch for
// publishers, and export. No delete: no route deletes a workflow.
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
````

**with**:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The workflows list (screen 1a; 4b rulings 4-7): each workflow's state at a glance, filters, the enable switch for
// publishers, and export. No delete: no route deletes a workflow. 4c-3b adds the Trigger column (ruling 68: what starts
// it besides a person) and, under a workflow's name, why it needs attention.
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
````

**In** `frontend/src/routes/Workflows.tsx`, **replace**:

````tsx
import { downloadJson, fileName } from "../lib/download";
import { useDocumentTitle } from "../lib/title";
import { canEdit, canPublish, notPortable, since, tenantQuery, workflowsQuery, type PortableProblem, type WorkflowRow } from "../lib/workflows";
import { NewWorkflow } from "./NewWorkflow";
````

**with**:

````tsx
import { downloadJson, fileName } from "../lib/download";
import { useDocumentTitle } from "../lib/title";
import { attentionWords, triggerColumn } from "../lib/triggers";
import { canEdit, canPublish, notPortable, since, tenantQuery, workflowsQuery, type PortableProblem, type WorkflowRow } from "../lib/workflows";
import { NewWorkflow } from "./NewWorkflow";
````

**In** `frontend/src/routes/Workflows.tsx`, **replace**:

````tsx
          <thead>
            <tr>
              <Th>Name</Th><Th>Version</Th><Th>Last run</Th><Th>Last 24 h</Th><Th>Enabled</Th>
              <Th><span className="sr-only">Actions</span></Th>
            </tr>
````

**with**:

````tsx
          <thead>
            <tr>
              <Th>Name</Th><Th>Trigger</Th><Th>Version</Th><Th>Last run</Th><Th>Last 24 h</Th><Th>Enabled</Th>
              <Th><span className="sr-only">Actions</span></Th>
            </tr>
````

**In** `frontend/src/routes/Workflows.tsx`, **replace**:

````tsx
              <tr key={w.id}>
                <Td>
                  <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: w.id }} className="font-medium text-accent-ink">
                    {w.name}
                  </Link>
                </Td>
````

**with**:

````tsx
              <tr key={w.id}>
                <Td>
                  <span className="flex flex-col gap-0.5">
                    <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: w.id }} className="font-medium text-accent-ink">
                      {w.name}
                    </Link>
                    {attentionWords(w.needs_attention) && <span className="text-small text-danger">{attentionWords(w.needs_attention)}</span>}
                  </span>
                </Td>
````

**In** `frontend/src/routes/Workflows.tsx`, **replace**:

````tsx
                <Td><Version w={w} /></Td>
                <Td><LastRun w={w} /></Td>
````

**with**:

````tsx
                <Td className="text-small">{triggerColumn(w.triggers)}</Td>
                <Td><Version w={w} /></Td>
                <Td><LastRun w={w} /></Td>
````

**In** `frontend/src/routes/Workflows.tsx`, **replace**:

````tsx
            {list.data && shown.length === 0 && (
              <tr>
                <Td colSpan={6} className="text-muted">{rows.length === 0 ? "No workflows yet." : "No workflow matches."}</Td>
              </tr>
            )}
````

**with**:

````tsx
            {list.data && shown.length === 0 && (
              <tr>
                <Td colSpan={7} className="text-muted">{rows.length === 0 ? "No workflows yet." : "No workflow matches."}</Td>
              </tr>
            )}
````

**In** `frontend/src/routes/Workflows.tsx`, **replace**:

````tsx
        </Table>
      )}
      <p className="text-small text-muted">A disabled workflow keeps its versions and its history; nothing starts it.</p>
      {/* Asked for by the address (?new) too: opened only once the role is known to create one. */}
      {creating && canEdit(tenant.data?.role) && <NewWorkflow tenantId={tenantId} onClose={closeNew} />}
````

**with**:

````tsx
        </Table>
      )}
      <p className="text-small text-muted">
        By hand is always possible once published; the Trigger column names what else starts it. A disabled workflow keeps its versions and its
        history; nothing starts it.
      </p>
      {/* Asked for by the address (?new) too: opened only once the role is known to create one. */}
      {creating && canEdit(tenant.data?.role) && <NewWorkflow tenantId={tenantId} onClose={closeNew} />}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx --offline pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/Workflows.test.tsx`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  10 passed (10)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx --offline pnpm@12.6.0 typecheck` and `npx --offline pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/Workflows.test.tsx \
  frontend/src/routes/Workflows.tsx
git commit -m "feat(workflows): the list's Trigger column, and why a workflow needs attention (4c-3b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Milestone 4's checks.** The whole unit suite, typecheck and lint; append `### 4c-3b, milestone 4 (<date>)` to
  the ledger and commit it. No pause.

---

# Milestone 5 — the browser, every check, the final checkpoint

### Task 14: The browser, every check, the final checkpoint

The slice in the browser, behind nginx, under the served CSP, with axe: Settings → Webhook endpoints, the Triggers
panel's input (focus coming back to what opened each part of it), a published workflow's schedule and webhook, New
workflow's Mist webhook, the list's Trigger column, and the forms at 320 px. Nothing leaves the stack (D24): an endpoint
is made and bound, never sent to; the schedule is simulated, then deleted. The 4b flows follow the start card: Enter
opens Triggers, `A` adds a first step, and a new workflow opens on its Triggers, which they close first.

**Files:**
- Create: `frontend/e2e/triggers.spec.ts`
- Modify: `frontend/e2e/workflows.spec.ts`, `frontend/playwright.config.ts`
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`

**Interfaces:**
- Consumes: Tasks 7–13.
- Produces: nothing new.

- [ ] **Step 1: The browser flows**

**Create** `frontend/e2e/triggers.spec.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// Slice 4c-3b in the browser: Settings → Webhook endpoints, the Triggers panel (the input, schedules, webhooks), New
// workflow's "What starts it?" and the list's Trigger column, behind nginx, under the served CSP, with axe. Nothing
// leaves the stack (D24): an endpoint is made and bound, never sent to; a schedule is simulated, and deleted.
import type { Locator, Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

/** New workflow, as `choose` sets it up; it opens on its Triggers. */
async function create(page: Page, name: string, choose: (dialog: Locator) => Promise<void> = () => Promise.resolve()): Promise<Locator> {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await choose(dialog);
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("button", { name: /^(Create|Import) and open$/ }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
  const panel = page.getByRole("complementary", { name: "Triggers" });
  await expect(panel.getByRole("heading", { name: "Triggers" })).toBeFocused();
  return panel;
}

const importing = (file: string) => async (dialog: Locator) => {
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles(file);
  await expect(dialog.getByText("The file names no connection or workflow.")).toBeVisible();
};

test("Settings → Webhook endpoints: a Mist endpoint shows its token once; rotating asks first", async ({ page }) => {
  await page.goto(`/t/${await tenantId(page)}/settings/webhooks`);
  await expect(page.getByRole("heading", { name: "Webhook endpoints" })).toBeVisible();
  await expect(page.getByText("No endpoint yet.")).toBeVisible();
  await expectAccessible(page, "settings: webhook endpoints, none yet");
  await page.getByRole("button", { name: "＋ Endpoint" }).click();
  const form = page.getByRole("form", { name: "New endpoint" });
  await form.getByLabel("Name").fill("Mist prod");
  await expectAccessible(page, "settings: a new Mist endpoint");
  await form.getByRole("radio", { name: "Another sender" }).check();
  await form.getByRole("radio", { name: "An HMAC signature" }).check();
  await form.getByRole("radio", { name: /^A list in the body, at/ }).check();
  await expect(form.getByText(/^Fixed once made: an HMAC signature; events in the list at \/items; no ids\.$/)).toBeVisible();
  await expectAccessible(page, "settings: another sender's endpoint");
  await form.getByRole("radio", { name: "Mist" }).check();
  await form.getByRole("button", { name: "Create the endpoint" }).click();
  const shown = page.getByRole("status").filter({ hasText: "Mist prod is ready" });
  await expect(shown).toBeVisible();
  await expectAccessible(page, "settings: a token shown once");
  await shown.getByRole("button", { name: "I've copied it" }).click();
  await expect(page.getByText("Mist prod is ready")).toHaveCount(0);
  const table = page.getByRole("region", { name: "Webhook endpoints" });
  await table.getByRole("button", { name: "Mist prod, details" }).click();
  await expect(table.getByText(/^Path \/hooks\/[0-9a-f-]{36}, on your Dewpoint webhook address\./)).toBeVisible();
  await table.getByRole("button", { name: "Rotate the token…" }).click();
  const ask = page.getByRole("dialog", { name: "Rotate Mist prod's token?" });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expectAccessible(page, "settings: rotating a token");
  await page.keyboard.press("Escape");
  await expect(ask).toBeHidden();
});

test("the Triggers panel's input: form fields, a Mist event's shape, a CSV file, JSON held while it can't be saved", async ({ page }) => {
  const panel = await create(page, "Input flow");
  await expectAccessible(page, "editor: triggers, a new workflow");
  await panel.getByRole("button", { name: "＋ Field" }).click();
  const field = panel.getByRole("group", { name: "The field field_1" });
  await field.getByLabel("Label").fill("Site");
  await field.getByLabel("Required").check();
  await expectAccessible(page, "editor: triggers, a field");
  await field.getByRole("button", { name: "Done" }).click();
  await expect(panel.getByText("field_1 · Site · Text · required")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Edit field_1" })).toBeFocused(); // the review of revision 1
  await panel.getByRole("button", { name: "Use a Mist event…" }).click();
  await panel.getByRole("searchbox", { name: "Find a topic" }).fill("device-events");
  await panel.getByRole("radio", { name: "device-events" }).check();
  await panel.getByRole("button", { name: "Use device-events" }).click();
  await expect(panel.getByText("A Mist event: device-events")).toBeVisible();
  await expectAccessible(page, "editor: triggers, a Mist event's shape");
  await panel.getByRole("button", { name: "Use form fields instead" }).click();
  await panel.getByRole("button", { name: "＋ CSV file" }).click();
  await expect(panel.getByRole("button", { name: "Edit Column 1" })).toBeFocused();
  await panel.getByRole("button", { name: "Edit Column 1" }).click();
  await panel.getByRole("group", { name: "The column Column 1" }).getByLabel("Header in the file").fill("AP name");
  await expectAccessible(page, "editor: triggers, a CSV column");
  await panel.getByRole("button", { name: "Done" }).click();
  await expect(panel.getByRole("button", { name: "Edit AP name" })).toBeFocused();
  await panel.getByRole("button", { name: "Edit as JSON" }).click();
  await panel.getByRole("textbox", { name: "The input's schema and CSV columns" }).fill("{");
  await expect(panel.getByText("Line 1: This isn't valid JSON, so it isn't saved.")).toBeVisible();
  await expect(page.getByRole("button", { name: "1 edit not applied" })).toBeVisible();
  await expectAccessible(page, "editor: triggers, JSON held");
  await panel.getByRole("button", { name: "Discard what isn't saved" }).click();
  await expect(page.getByRole("button", { name: "1 edit not applied" })).toHaveCount(0);
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
});

test("a published workflow's schedule and webhook are live at once, said in words, and summed up on its start card", async ({ page }) => {
  const panel = await create(page, "Report T", importing("e2e/fixtures/report.dewpoint.json"));
  const schedules = panel.getByRole("region", { name: "Schedules" });
  await expect(schedules.getByRole("button", { name: "＋ Schedule" })).toBeDisabled();
  await expect(schedules.getByText("A schedule runs the published version: publish a first version to add one.")).toBeVisible();
  await expect(page.getByRole("button", { name: "No problems" })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Publish v1" }).click();
  await page.getByRole("dialog", { name: "Publish version 1" }).getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Saved · published as v1")).toBeVisible({ timeout: 10_000 });
  await expect(schedules.getByText("Live · on version 1")).toBeVisible();
  await schedules.getByRole("button", { name: "＋ Schedule" }).click();
  const form = schedules.getByRole("form", { name: "New schedule" });
  await form.getByLabel("Time zone").fill("Europe/Paris");
  await form.getByRole("radio", { name: "Simulate" }).check();
  await expect(form.getByText("Version 1 takes no input.")).toBeVisible();
  await expectAccessible(page, "editor: triggers, a new schedule");
  await form.getByRole("button", { name: "Add the schedule" }).click();
  await expect(schedules.getByText("Every day at 07:00")).toBeVisible();
  await expect(schedules.getByText(/^Europe\/Paris · simulated: nothing is sent/)).toBeVisible();
  const webhooks = panel.getByRole("region", { name: "Webhooks" });
  await webhooks.getByRole("button", { name: "＋ Webhook" }).click();
  const bind = webhooks.getByRole("form", { name: "New webhook" });
  await bind.getByLabel("Endpoint", { exact: true }).selectOption({ label: "Mist prod · Mist" });
  await bind.getByLabel("Topic", { exact: true }).selectOption("device-events");
  await expectAccessible(page, "editor: triggers, a new webhook");
  await bind.getByRole("button", { name: "Add the webhook" }).click();
  await expect(webhooks.getByText("Mist · topic device-events")).toBeVisible();
  await expect(webhooks.getByText("Version 1's input isn't device-events' shape: events it doesn't fit are refused.")).toBeVisible();
  await expect(webhooks.getByText("In the draft: it applies once published.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start: by hand, 1 schedule, 1 webhook. Open its triggers" })).toBeVisible();
  await expectAccessible(page, "editor: triggers, a schedule and a webhook");
  await schedules.getByRole("button", { name: "Edit Every day at 07:00" }).click();
  await schedules.getByRole("button", { name: "Delete the schedule…" }).click();
  const ask = page.getByRole("dialog", { name: 'Delete the schedule "Every day at 07:00"?' });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expectAccessible(page, "editor: triggers, deleting a schedule");
  await ask.getByRole("button", { name: "Delete the schedule" }).click();
  await expect(schedules.getByText("No schedule starts this workflow.")).toBeVisible();
});

test("New workflow: a Mist webhook gives the input its topic's shape, is bound at once, and opens on Triggers", async ({ page }) => {
  const panel = await create(page, "AP alarms", async (dialog) => {
    await dialog.getByRole("radio", { name: /^A Mist webhook/ }).check();
    await dialog.getByLabel("Endpoint", { exact: true }).selectOption({ label: "Mist prod" });
    await dialog.getByLabel("Topic", { exact: true }).selectOption("alarms");
    await expect(dialog.getByText("It opens on its Triggers: the input is alarms' shape, and the webhook is bound to Mist prod.")).toBeVisible();
    await expectAccessible(page, "new workflow: a Mist webhook");
  });
  await expect(panel.getByText("A Mist event: alarms")).toBeVisible();
  await expect(panel.getByRole("region", { name: "Webhooks" }).getByText("Mist · topic alarms")).toBeVisible();
});

test("the list names what starts each workflow besides a person", async ({ page }) => {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  const row = (name: string) => page.getByRole("link", { name, exact: true }).locator("xpath=ancestor::tr");
  await expect(row("AP alarms").getByRole("cell").nth(1)).toHaveText("Webhook");
  await expect(row("Report T").getByRole("cell").nth(1)).toHaveText("Webhook");
  await expect(row("Input flow").getByRole("cell").nth(1)).toHaveText("By hand"); // its CSV file is the draft's: never published
  await expectAccessible(page, "workflows: the Trigger column");
});

test("Settings → Webhook endpoints and the Triggers panel's forms reflow at 320 px and stay AA (WCAG 1.4.10)", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  await page.goto(`/t/${await tenantId(page)}/settings/webhooks`);
  await expect(page.getByRole("list", { name: "Webhook endpoints" }).getByText("Mist prod")).toBeVisible();
  expect(await overflow(), "Settings → Webhook endpoints scrolls sideways at 320 px").toBeLessThanOrEqual(0);
  await expectAccessible(page, "settings: webhook endpoints at 320 px");
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByRole("link", { name: "Report T", exact: true }).click();
  await page.getByRole("button", { name: /^Start: by hand/ }).click();
  const panel = page.getByRole("complementary", { name: "Triggers" });
  await panel.getByRole("button", { name: "＋ Schedule" }).click();
  await expect(panel.getByRole("form", { name: "New schedule" })).toBeVisible();
  expect(await overflow(), "the schedule's form scrolls sideways at 320 px").toBeLessThanOrEqual(0);
  await expectAccessible(page, "editor: triggers, a schedule's form at 320 px");
  await page.setViewportSize({ width: 1280, height: 720 });
});
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await expect(dialog.getByLabel("Name")).toBeFocused();
  await expectAccessible(page, "new workflow");
  await dialog.getByLabel("Name").fill(name);
````

**with**:

````ts
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await expect(dialog.getByRole("radio", { name: /^By hand/ })).toBeFocused(); // what starts it comes first (4c-3b)
  await expectAccessible(page, "new workflow");
  await dialog.getByLabel("Name").fill(name);
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  await dialog.getByRole("button", { name: "Create and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}$/);
}

````

**with**:

````ts
  await dialog.getByRole("button", { name: "Create and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
  await openPlain(page);
}

/** A new workflow opens on its Triggers (4c-3b): these flows start from its canvas alone, fitted to the editor's whole
 * width, as an existing workflow opens from its address. */
async function openPlain(page: Page): Promise<void> {
  await page.goto(new URL(page.url()).pathname);
  await expect(page.getByRole("button", { name: /^Start: by hand/ })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Triggers" })).toHaveCount(0);
}

````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  await expectAccessible(page, "workflows");
  await newWorkflow(page, "Pointer flow");
  await expect(page.getByRole("button", { name: /^Start, where every run begins/ })).toBeVisible();
  await expectAccessible(page, "editor: blank");
  await page.getByRole("button", { name: "Add the first step" }).click();
````

**with**:

````ts
  await expectAccessible(page, "workflows");
  await newWorkflow(page, "Pointer flow");
  await expect(page.getByRole("button", { name: /^Start: by hand/ })).toBeVisible();
  await expectAccessible(page, "editor: blank");
  await page.getByRole("button", { name: "Add the first step" }).click();
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
test("a workflow built with the keyboard alone: Tab in, arrows along the edges, A, Delete, undo", async ({ page }) => {
  await newWorkflow(page, "Keyboard flow");
  const start = page.getByRole("button", { name: /^Start, where every run begins/ });
  await start.focus();
````

**with**:

````ts
test("a workflow built with the keyboard alone: Tab in, arrows along the edges, A, Delete, undo", async ({ page }) => {
  await newWorkflow(page, "Keyboard flow");
  const start = page.getByRole("button", { name: /^Start: by hand/ });
  await start.focus();
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  await page.keyboard.press("Enter");
  await page.keyboard.type("transform");
  await page.keyboard.press("Enter");
  const transform = page.getByRole("button", { name: /^transform, Transform/ });
  await expect(transform).toBeFocused();
  await page.keyboard.press("a");
````

**with**:

````ts
  await page.keyboard.press("a"); // A adds a first step; Enter opens the start card's Triggers (4c-3b)
  await page.keyboard.type("transform");
  await page.keyboard.press("Enter");
  const transform = page.getByRole("button", { name: /^transform, Transform/ });
  await expect(transform).toBeFocused();
  await page.keyboard.press("a");
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  await expectAccessible(page, "new workflow: import");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}$/);
}

````

**with**:

````ts
  await expectAccessible(page, "new workflow: import");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
  await openPlain(page);
}

````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
test("the keys reach every step of an imported cycle no entry leads into", async ({ page }) => {
  await importFile(page, "Cycle", "e2e/fixtures/cycle.dewpoint.json");
  const start = page.getByRole("button", { name: /^Start, where every run begins/ });
  await start.focus();
  await page.keyboard.press("ArrowDown");
````

**with**:

````ts
test("the keys reach every step of an imported cycle no entry leads into", async ({ page }) => {
  await importFile(page, "Cycle", "e2e/fixtures/cycle.dewpoint.json");
  const start = page.getByRole("button", { name: /^Start: by hand/ });
  await start.focus();
  await page.keyboard.press("ArrowDown");
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
test("undo and redo from the keyboard keep focus in the editor, never repaired by hand", async ({ page }) => {
  await newWorkflow(page, "Undo flow");
  const start = page.getByRole("button", { name: /^Start, where every run begins/ });
  await start.focus();
````

**with**:

````ts
test("undo and redo from the keyboard keep focus in the editor, never repaired by hand", async ({ page }) => {
  await newWorkflow(page, "Undo flow");
  const start = page.getByRole("button", { name: /^Start: by hand/ });
  await start.focus();
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  await page.keyboard.press("Enter");
  await page.keyboard.type("transform");
  await page.keyboard.press("Enter");
````

**with**:

````ts
  await page.keyboard.press("a"); // A adds a first step; Enter opens the start card's Triggers (4c-3b)
  await page.keyboard.type("transform");
  await page.keyboard.press("Enter");
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  const opened = await assetsFetched(page, async () => {
    await page.getByRole("link", { name: "Cycle" }).click();
    await expect(page.getByRole("button", { name: /^Start, where every run begins/ })).toBeVisible();
  });
  expect([...opened.keys()].filter((p) => EDITOR_CHUNK.test(p)).length).toBe(2); // its script and its stylesheet
````

**with**:

````ts
  const opened = await assetsFetched(page, async () => {
    await page.getByRole("link", { name: "Cycle" }).click();
    await expect(page.getByRole("button", { name: /^Start: by hand/ })).toBeVisible();
  });
  expect([...opened.keys()].filter((p) => EDITOR_CHUNK.test(p)).length).toBe(2); // its script and its stylesheet
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  await expect(minimap).toBeVisible();
  expect(overlaps((await far.boundingBox())!, (await minimap.boundingBox())!), "the fixture puts far under the minimap").toBe(true);
  await page.getByRole("button", { name: /^Start, where every run begins/ }).focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
````

**with**:

````ts
  await expect(minimap).toBeVisible();
  expect(overlaps((await far.boundingBox())!, (await minimap.boundingBox())!), "the fixture puts far under the minimap").toBe(true);
  await page.getByRole("button", { name: /^Start: by hand/ }).focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowRight");
````

**In** `frontend/playwright.config.ts`, **replace**:

````ts
    {
      name: "workflows",
      testMatch: /workflows\.spec\.ts/,
      dependencies: ["foundations"],
      use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
````

**with**:

````ts
    {
      name: "workflows",
      testMatch: /(workflows|triggers)\.spec\.ts/,
      dependencies: ["foundations"],
      use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
````


- [ ] **Step 2: The browser gate**

Run: `UI4_WT=<worktree> scratchpad/plan-4c3b/gate/e2e.sh` (a fresh database and rebuilt images, then every flow;
about 3 minutes).

Expected: `43 passed (1.7m)`, the whole run 208 s: the 6 trigger flows (focus coming back checked in Chromium), the 29
workflow flows, and the foundations' 2 and the gate's 6 (the CSP, the console, axe). Measured on the prototype's last
commit, whose tree the staged tasks reproduce file for file.

- [ ] **Step 3: Every check**

From `frontend/`: the unit suite (`npx --offline pnpm@12.6.0 test`), `typecheck`, `lint`, `check:api` (clean: no
OpenAPI change) and `build`; then local CodeQL on the branch's head (`scratchpad/codeql/scan.sh <sha>`): no finding in
either language. Expected: unit `Test Files  72 passed (72)`, `Tests  968 passed (968)`; every other check clean.

- [ ] **Step 4: The screens**

Screenshots against the isolated stack after a reset, light and dark, at 1280 and 320 px, beside the boards in the
session's checkpoint page: the Triggers panel's schedules (each state the Schedules board shows, made through the API on
the isolated stack), a schedule's form, the webhooks (a Mist binding with its warning, another sender's), Settings →
Webhook endpoints (the table, the details, a new endpoint of each kind, a secret shown once), New workflow, and the
list.

- [ ] **Step 5: The ledger**

Append `### 4c-3b, milestone 5 and the final checkpoint (<date>)`: Tasks 9–14's commits, each check's result as run
(the unit suite's counts, the browser gate's, CodeQL's), every mid-slice ruling, anything deferred. Commit
(`docs(editor-4): 4c-3b final checkpoint`).

- [ ] **Step 6: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch against this plan (its Review Focus first), the
outline's 4c rows, the ledger's rulings 68, 69, 71, 74, 96, 113 and 147–158, and the boards. Critical and important
findings are fixed test first, once; minor ones are listed. Then **stop**: the summary to the owner names what's built,
the checks as run, the screens, the rulings proposed and made, and asks for the owner's word on push and a PR (nothing
is
pushed before it). CI on the PR runs the backend (about 12 minutes), the frontend, CodeQL and the Compose e2e: say so
before pushing.

## Self-review

**Spec coverage.** Each part of 4c-3's scope (ruling 96) and the owner's design, and the task that builds it:
- the start card opens a Triggers panel, its "+" adding a first step: Task 7 (ruling 1);
- the input as a field list (name, label, type, required, sensitive, description, default), "Use a Mist event…"
  (read only, replaceable), an optional CSV file of typed columns, "Edit as JSON": Tasks 4, 5, 7, 8 (rulings 3–7);
- schedules and webhooks live and said so, ＋ Schedule disabled before a first publish with why: Tasks 9, 11
  (rulings 8, 10);
- a schedule's timing, zone, mode and on or off editable, its input replaced whole, never shown back: Task 9;
- an endpoint's sender, set when it's made, fixed: Task 10 (ruling 9; 4c-3a ruling 1);
- 1b's "What starts it?" seeding the draft, binding at once, opening on Triggers; an import keeping its input: Task 12
  (ruling 11);
- 1a's Trigger column, and why a workflow needs attention (`schedule_sync_failed` included): Task 13 (ruling 12);
- Settings → Webhook endpoints, the path shown and copied, the note outside development: Task 10 (ruling 9);
- a binding whose events may not fit, warned at the binding, the topic's shape offered: Task 11 (ruling 10);
- what the draft would break among live schedules, as the server's check says: Task 9.
Out of scope, as the owner ruled: the run form and CSV upload (4e), the webhook events inbox.

**Placeholders.** None but Task 1's ledger section, whose `<date>`, revision, branch and the rulings' text as accepted
are filled in at acceptance.

**Types.** Every task's code was committed in a staged run, each commit typechecked and linted, its tests passing; the
interfaces each task lists are the ones the next ones import.

**Review Focus.** Each line is pinned by the test it names, in the task that owns the code.

**The dry run.** A script applied this plan's text task by task from `origin/main` b1183473, in a worktree with the
locked packages: each task's Step 1, its Step 2 run (red, as its Expected line says), its Step 3, its Step 4 run
(green), a commit. The last commit's `frontend/` is the staged tasks' file for file, and the unit suite went from
`Tests  828 passed (828)` to `Test Files  72 passed (72)`, `Tests  968 passed (968)`. Typecheck and lint ran on each
staged task's commit.
