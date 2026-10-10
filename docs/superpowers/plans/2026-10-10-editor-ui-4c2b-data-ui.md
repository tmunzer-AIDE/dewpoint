# Editor UI 4c-2b: the step drawer's data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 3.** Nothing is built before the owner approves this plan. Nothing is pushed and no PR is opened without
the owner's OK in chat.

**Goal:** Data in the step drawer: text with data pills inserted from the upstream data tree, a pill's details with a
past run's sample, the condition builder that writes a formula, the Declassify list, and the "may not run" step badge.

**Architecture:**
- Pure layers first (no screen change): text and pills as segments (`lib/pills.ts`), the scope and samples client and
  their words (`lib/data.ts`), the condition builder's formulas, written and read back (`lib/builder.ts`), two new
  kinds of edit held while it can't be written (`template`, `condition`), the settings writers for Declassify, and the
  drawer's new context (the saved draft's revision, the draft's steps).
- Then the screens, each in the drawer's flow under its field: the data tree, a pill's details, the text and pill
  editor (a text field's fixed mode, "Text"), the condition builder (a condition's fixed mode, "Builder"), the
  Declassify side panel, and the badge on a card.
- No backend change. It builds on main after 4c-2a (#82) and the type-name fix (#84, the builder's guards test a
  value's type: `type(x) == type({})`, ledger M65).

**Tech Stack:** React 19, TypeScript, TanStack Query and Router, Tailwind 4 with the app's tokens, Vitest and Testing
Library, Playwright with the browser gate (`e2e/gate.ts`: CSP, console, axe WCAG 2.2 AA). No new dependency.

**Spec:**
- The outline `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`: §2 "4c — step drawer" (pills, the upstream
  tree, pill details, the condition builder, the declassify list), §5 rows B6 and B7, §6 (no AI tells), D17 (answers
  carry their revision), D18 (the server alone checks and classifies), D19 (the browser checks only what a save would
  refuse), D20 (redacted values), D23 (native dialogs, non-modal menus, CSP).
- The ledger `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`: ruling 70 (the conditional badge), ruling 96
  (4c-2 is data), "Owner, 4c-2 mockups and plan shape" (D8 signed off on the Design canvas "4c-2 Data Mockups",
  version 10, and the ten adopted recommendations), rulings 113 (edits not applied), 114–124 (4c-2a: the merge, the
  scope, guards as data, samples), M62–M65.
- The mockups (version 10): https://claude.ai/artifact/3kNdDH6rykyQ5eBeFACZkN — Text with data pills; The data tree
  (untyped and declared trigger); A pill's details; The condition builder; Declassify; Sample states; A formula the
  builder didn't make; 320 px.
- The engine facts this plan relies on, each run against main: `scratchpad/research-4c2/R6-engine-for-4c2b.md`
  (envelopes, reference grammar, diagnostics, the builder's CEL per type and operator, run modes, taint, defaults,
  previews); and the builder's own formulas, validated and run through the run's binding by Task 1's check: clean on
  #84's code, while on main before #84 the object test of a declared field fails validation.
- The code on `origin/main` (6f4ddec7, with #84 merged), read for this plan
  (`scratchpad/research-4c2/R3-frontend.md` for the drawer, its held edits and its tests). Every task's code was run
  on a prototype first (`scratchpad/ui4/4c2b-proto`, local branch `proto/editor-4c2b`): the unit suite (813 tests),
  typecheck, lint, build, and the browser gate (37 flows).

## Changes from revision 2

A pasted review of revision 2 (7ee93fe9) found the other five fixes of revision 1's review right, and held it for two
defects, both reproduced. Both are fixed here, each with a test that fails on revision 2's code (its name ends "(the
review of revision 2)"):

1. **A list's first item being there read back as the list not being empty** (Task 4, P2). For an item whose guards are
   its list's type and size, "is there" wrote the same text as "is not empty" for the list, `(type(x) == type([]) &&
   size(x) > 0)`, and the reader took the second: reopened, the comparison moved to the list, and a later edit compared
   the list (`(x == "alpha")`). Now "is not empty" is written `size(x) != 0`, so `size(x) > n` ends only an item's
   presence, and neither reads as the other (ruling 10). A sweep writes every operator over each shape of guards the
   scope gives, and reads each back as the value, operator and literal it was written for. Task 1's engine check runs
   the new form. Tests: Task 4 `tells a list's first item being there from the list not being empty, each read back as
   itself`, `reads every comparison back as the value, operator and literal it was written for`; Task 9 `reopens "is
   there" for a list's first item as that item, so a later edit compares it` (the review's case, through the field).
2. **An opened value's answer about a newer revision showed an empty list** (Task 6, P3). The tree said why only at its
   top. Now an opened value says it too, and its other errors (ruling 6). Test: Task 6 `says so when an opened value's
   answer is about a newer revision, and shows none of it`.

The per-task commits were built again, and the plan's text applied again from scratch by the dry run; the browser gate
and Task 1's engine check were run again (see the self-review).

## Changes from revision 1

A pasted review held revision 1 (f8e2fa80) for six P2 defects, each reproduced by it. All six are fixed here, each with
a test that fails on revision 1's code (each test's name ends "(the review of revision 1)"):

1. **An answer about another revision was shown as the one asked of** (Task 3). The API answers for the saved draft as
   it is, so a draft saved again while it asked gave the newer answer under the older revision's key. Now both queries
   refuse it (`DraftMoved`, never shown as the asked revision's), and the tree, a pill and its details say the draft was
   saved again (Tasks 6 and 7; ruling 6). Tests: Task 3 `takes no answer about another revision than the one it asked
   of`; Task 6 `says so when the draft was saved again while its data was asked for, and shows none of it`.
2. **A formula holding text JSON doesn't read broke its field** (Task 4). `(trigger.name == "\x41")` validates and runs,
   and reading it back threw from `JSON.parse` as the field rendered. Now such text isn't the builder's, and the formula
   stays a formula (ruling 11). Tests: Task 4 `keeps a formula with text JSON doesn't read a formula, and never fails on
   it`; Task 9 `keeps a formula holding text JSON doesn't read a formula, and still shows the field` (each throws on
   revision 1).
3. **"is there" and "is missing" lost the value they test** (Task 4). Where only an ancestor's guards decide it (an
   item's field that's always there), the formula didn't name the value, so reading it back moved the comparison to the
   list; and an object that's always there wrote `(true)`, which doesn't read back. Now presence ends with a test of the
   value itself (ruling 10), "is there" is offered only where something may be missing, and an object that's always
   there isn't picked in a condition: it opens (ruling 8). Task 1's engine check runs the new forms over an optional and
   a required list, with the scope's own guards. Tests: Task 4 `names the value it tests in "is there" and "is missing",
   and reads that value back`, `offers "is there" and "is missing" only for a value that may be missing`; Task 6 `opens
   an object that's always there in a condition, but never picks it`.
4. **Held text was applied as a value the field refuses** (Task 5). Text alone typed in a field that takes no fixed
   value (`["template", "cel"]`) and held after a refused write was applied as `"hello"`, not as a template of one text
   part. Now the held edit keeps `literalOk`, and is applied as the write would have been (ruling 4). Tests: Task 5
   `applies held text as it would have been written: alone, a template where the field takes no fixed value`; Task 8
   `holds text where the field takes no fixed value as it would write it: a template`.
5. **The recovery file lost a pill's default** (Task 5). It kept the text in braces only. Now each edit carries its text
   and pills (`segments`, defaults included) or its condition as built, beside its text (ruling 4). Test: Task 5 `writes
   held text and pills, and a condition being built, whole into the recovery file`.
6. **A sample stayed as first seen** (Task 3). Kept for the draft's revision, it said "no finished run" after a run had
   ended, and missed a changed connection or expired history. Now a sample is asked for each time the details open
   (ruling 9). Test: Task 7 `asks for a step's sample again each time its details open: a run may have ended since`.

The per-task commits were built again from the fixed prototype, and the plan's text was applied again from scratch by
the dry run; the browser gate and Task 1's engine check were run again (see the self-review).

## Global Constraints

- **CSP.** It stays exactly `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src
  'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'`. No inline
  script, no injected `<style>`, no third-party or CDN asset. A position set in code goes through React's `style` prop
  (the CSSOM, which the CSP allows), never a `style` attribute in markup. The browser gate fails any screen that
  violates it.
- **WCAG 2.2 AA.**
  - Text 4.5:1; boundaries, focus rings and graphics 3:1 (`PAIRS` in `src/styles/tokenNames.ts`).
  - Every control has a visible label, and its hint and errors describe it; a visible label is in the control's
    accessible name (2.5.3): a pill's name starts with its visible text.
  - Everything is reachable and operable by keyboard: the tree is an ARIA tree (one tab stop, arrows), a pill a button
    (Enter opens its details, Backspace removes it, ← → move past it).
  - A pointer target is 24 px at least (2.5.8), an empty text between pills included.
  - Axe checks each new state in the browser gate: the tree, a pill's details, the builder, Declassify, the badge.
- **No AI tells** (outline §6; the vitest guard `src/test/aiTells.ts`). Data pills are the one use of `rounded-pill`
  (`--radius-pill`, "data pills only"). The tree and a pill's details are bordered panels in the drawer's flow, with no
  shadow; a group of comparisons is indented, never marked with a coloured border; tags are words in a thin border.
- **Dependencies.** None new. The outline's pre-approved `@radix-ui/react-popover` stays unused (ruling 2).
- **No real Mist or SaaS call, ever** (D24). Unit tests use made-up types and fake API answers; the browser flows use
  the flow plugin's steps and a declared trigger input; no run is started.
- **No backend change**, so no migration and no OpenAPI change: `check:api` stays clean. The branch starts from main
  with #84 (6f4ddec7 on): the builder writes the object test as `type(x) == type({})`, which validation accepts as the
  shape guard only from #84 on (ledger M65).
- **Secrets.**
  - A sensitive field never takes text with pills: its fixed text would be a secret written into the workflow
    (`sensitive.literal`). It keeps 4c-1's formula and read-only reference.
  - A sample shows what its preview kept: `[redacted]` and `[truncated]` as chips, a value kept apart from the run's
    history (`{"$claim": …}`) as words, never the value (D20).
  - Logs name an exception's type only. No draft, text, pill, condition or sample is kept in browser storage.
- **The server decides** (D18): a value's types, whether it may be missing or null, its guards, whether it's sensitive,
  how a formula runs, and what a decision reveals all come from the API. The client only spells guards as CEL, and
  every other rule is the server's.
- **Verify, don't remember.** Check every library API against the installed package, and every API path and body
  against `src/api/schema.d.ts`.
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker. Nothing is pushed and no PR is opened
  without the owner's OK in chat.

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the tests named, in
the task that owns it.

- **Text with pills, typed, and then the person moves on.**
  - The cases: a write refused as the editor turns read only; a closed drawer, a remount, an undo under held text; a
    number half typed in the builder; a "/" typed and the tree closed; a version's view.
  - Nothing typed disappears: what can't be written is held whole (text and pills as a `template`, a condition as a
    `condition`), shown, counted and in the recovery file, until it's applied or discarded.
  - Tests: Task 5 `applies held text as it would have been written: alone, a template where the field takes no fixed
    value (the review of revision 1)`, `writes held text and pills, and a condition being built, whole into the recovery
    file (the review of revision 1)`, `applies held text and pills as a template, and a literal's text as a literal
    (4c-2b)`, `applies a held condition once each comparison can be written (4c-2b)`; Task 8 `holds text and pills a
    write refused, whole, said in braces, and shows them still`, `keeps the / when the tree is closed with Escape, and
    puts focus back after it`, `shows pills in a version's view without asking for data, and offers no ＋ Data`; Task 9
    `offers the operators a value's type takes, and a number only as one`.
- **A formula the builder didn't write, or one changed by hand after.**
  - The cases: a formula typed in Formula mode; a builder formula edited by hand; a type's name; text joined on one
    line; a group of one comparison; text CEL reads and JSON doesn't (`"\x41"`).
  - The builder opens only the exact text it would write; anything else stays a formula, and says why.
  - Tests: Task 4 `reads back what it wrote, and only that`, `keeps a formula with text JSON doesn't read a formula, and
    never fails on it (the review of revision 1)`, `names the value it tests in "is there" and "is missing", and reads
    that value back (the review of revision 1)`, `tells a list's first item being there from the list not being empty,
    each read back as itself (the review of revision 2)`, `reads every comparison back as the value, operator and
    literal it was written for (the review of revision 2)`; Task 9 `keeps a formula holding text JSON doesn't read a
    formula, and still shows the field (the review of revision 1)`, `reopens "is there" for a list's first item as that
    item, so a later edit compares it (the review of revision 2)`, `keeps a formula it didn't write a formula, and says
    why`, `opens a formula it wrote as comparisons, and shows the same formula in Formula mode`, `groups comparisons one
    level deep, each group matching all or any`.
- **Data of every shape its schema allows, and any data where it declares nothing.**
  - The cases: a path missing at any level, null at any level, another shape (a string where a list is), an empty list,
    any value where nothing is declared.
  - A comparison is false, never an error; "is missing" is true.
  - Tests: Task 4 `writes each comparison as its guards, its null test, a type test where the operator needs one, and
    the test`, `names no type: every type test compares with a value's type`; Task 1's engine check of the builder's
    formulas (23 formulas over 20 shapes of trigger data, through the run's binding); Task 12 `the builder writes a
    condition the server checks clean, and opens it again`.
- **An answer that's out of date, or can't be given.**
  - The cases: a step not yet saved; a draft that doesn't parse or can't be analysed; a revision saved since the tree
    opened, or while it asked (the API answers for the draft as it is); a run that ended since a pill's details last
    opened; a version's view.
  - Data is asked of the saved draft by revision, an answer about another revision is never shown as the one asked of, a
    newer revision asks again, a sample is asked for each time it's shown, and the server's reason is shown.
  - Tests: Task 3 `asks each saved revision apart, so a newer revision asks again and never shows an older answer
    (D17)`, `takes no answer about another revision than the one it asked of (the review of revision 1)`; Task 6 `says
    so when the draft was saved again while its data was asked for, and shows none of it (the review of revision 1)`,
    `says so when an opened value's answer is about a newer revision, and shows none of it (the review of revision 2)`;
    Task 7 `asks for a step's sample again each time its details open: a run may have ended since (the review of
    revision 1)`; Task 6 `says why there's no data when the saved draft can't give any`; Task 8 `shows pills in a
    version's view without asking for data, and offers no ＋ Data`.
- **Sensitive data.**
  - The cases: a pill to a sensitive value; a redacted, truncated or claimed sample; a decision on sensitive data; a
    sensitive field.
  - A sensitive value is never shown; a decision is declassified only once the person confirms what it reveals.
  - Tests: Task 5 `takes text with data pills in a text field the engine lets template, never a secret, a choice or a
    formula`; Task 3 `follows a path, and stops where the preview kept no value: redacted, truncated, kept apart, or
    absent`; Task 7 `shows a redacted value as a chip, never the value`; Task 10 `says what a decision reveals, as the
    server does, and declassifies it only once that's confirmed`; Task 12 `a decision on sensitive data is declassified
    from its field, once confirmed`.

## Rulings this plan proposes

These join the ledger as rulings 125 onward when the owner accepts the plan (Task 1 copies them).

1. **One editor of inputs and pills.** Text with pills is a row of text inputs with a pill button between each two, in
   one box: text is typed as in any text field, and a pill is a whole that's moved past, opened or removed. No
   `contenteditable`, no rich-text library, no new dependency. Each input sizes to its text (`field-sizing: content`,
   with `size` as the fallback), 24 px at least. Why: a contenteditable can't be tested in jsdom and fights React and
   the editor's undo; inputs keep 4c-1's typing, held edits and undo as they are. The cost: a text longer than the box
   scrolls within its line, as a text field does today, and a newline isn't typed (4c-1's text field takes none
   either).
2. **The tree and a pill's details open in the drawer's flow, under their field**, at every width (the mockups' panels
   are full width in the flow; the 320 px board: "under its field, never over the canvas"). No popover, no portal: the
   outline's pre-approved `@radix-ui/react-popover` stays unused. Why: a portal would sit outside the field's focus
   region (its blur applies held edits, its undo session starts on focus) and its Escape would reach the drawer. The
   cost: the drawer scrolls to show them.
3. **Where pills are written.** A text field (`string`, a date and time too) whose kinds take a template, or any value,
   gets "Text" as its fixed mode, with "＋ Data" beside the switch (`takesPills`). Not a sensitive field, a choice
   (`enum`), live options, a port's name or a literal-only field. A reference in any other field shows read only, as
   in 4c-1, with Replace. "＋ Data" is offered in Text mode and in the builder, not in Formula mode. Why: the owner's
   ruling (one text and pill editor as a text field's fixed mode); a template is text only (`template.not_string`).
4. **A lone pill is a template.** Inserting a pill writes a template, a lone one too (the owner's ruling), so the field
   gets text whatever the value's type. A plain reference already in the draft is shown as a pill and kept as it is
   until the text changes. Text where the field takes no fixed value is written as a template of one text part.
   Switching to Formula turns a lone plain reference into its path, and text with pills into an empty formula (Undo
   brings it back): text around references isn't a formula. Text held because a write was refused is applied later as
   the write would have been (a template of one text part where the field takes no fixed value), and the recovery file
   keeps it whole: its text and pills, each default included, beside the text in braces.
5. **"/" asks for data at a text's start or after a space**, never inside a word or a URL. The "/" stays as typed until
   a pick replaces it; Escape keeps it. Why: the mockup's "/" without eating the slashes of a path or a URL.
6. **A pill knows its value from the saved draft's scope**, one `at` question per pill and per saved revision, kept
   while the revision is (D17): dashed and "?" when it may be missing. The API answers for the saved draft as it is,
   so an answer about another revision than the one asked of is never shown as it: the drawer says the draft was saved
   again, and the next revision asks again. A version's view asks nothing: its pills show
   as written, with no tree and no data in their details. Why: B6 answers per field and path; the cost is one analysis
   per pill per revision on the server, cached in the client.
7. **A pill's accessible name starts with its visible text** (WCAG 2.5.3), then its path, and what may happen to its
   value and its default: "get_site › timezone ?, steps.get_site.output.timezone, may be missing, no default". The
   mockups' names gave the path alone.
8. **The tree.** An ARIA tree: each source (the trigger, a step, the run…) a top-level item holding its values, a
   value with children opened by → and loaded then (`under`). A root's own name is the last part of its path. The
   search asks the server (`find`). What can't be inserted shows, disabled, with why: a key a reference can't name, a
   value validation refuses here, in text an object or a list (`template.part_not_scalar`), in a condition a value a
   formula can't read or an object that's always there (it has nothing to compare: it opens, to pick one of its
   values). A trigger whose input isn't declared offers the typed path, which the server checks (`at`)
   before it's inserted (the owner's ruling). Opened, focus goes to its search; Escape closes it and gives focus back.
9. **A pill's details.** Its type, and why it may be missing, in words from its guards (a step that may not run, an
   optional field, a shorter list, a null). A default only for a pill in text: text, which replaces a missing or null
   value ("Add a default…" starts one, empty text a value too). A sample only for a step's output (B7), with its run,
   attempt, connection and whether it still matches; `[redacted]` and `[truncated]` as chips; a value kept apart from
   the run's history said so. A sample is asked for each time the details open: runs end, connections change and
   history expires whatever the draft's revision. The run's id is text: there's no run page before 4e.
10. **The builder's formulas.** Each comparison is "(guards && null test && type test && comparison)": the scope's
    guards as data, spelled with a value's type (`type(x) == type({})`, never a type's name: ledger M65); the null test
    where the scope says; a type test before an operator that would fail on another type. "is there" is the guards and
    the null test, ending with a test of the value itself (`has()` of a field, the size that holds an item, or its null
    test), so the formula names the value even where only an ancestor's guards decide it, and "is not empty" is
    written `size(x) != 0`, so no comparison reads back as another; "is missing" its negation.
    Operators by type; a date and time is compared as written, never ordered; "is there" only where something may be
    missing. A number is written as typed, JSON's way. Why: R6 §4: false on any
    data, never an error, and every form validates clean; checked through the run's own binding.
11. **The builder's own behaviour.** "Builder" replaces "Fixed" for a condition (the owner's ruling); a formula it
    didn't write stays a formula, Builder disabled with why. It reads back only the text it would write, and never
    fails on another: text CEL reads and JSON doesn't (`"\x41"`) isn't its own. "＋ Group"
    picks the group's first comparison; all/any is chosen once there are two. A fixed true or false says "Always
    true." / "Always false.". What can't be written yet (a number half typed, a write refused) is held whole as a
    `condition`.
12. **Declassify.** A side panel, opened from the toolbar (while there's a decision to make or an entry) and from
    "Review in Declassify…" under a field the server says reads sensitive data. A decision to make shows the server's
    own words for what it reveals (`taint.undeclassified`'s message: no table of reveals in the client, D18), and is
    declassified only once the person ticks that it may be visible in run history. An entry shows what it reveals
    (`taint.declassified`) or why it declassifies nothing (`taint.stale_declassify`), and can be removed. Each change is
    one undo step. A viewer gets no button: validate is the editors'.
13. **The badge.** "may not run", dashed, on a card the current check lists in `conditional_steps` (ruling 116), and in
    its accessible name. None in a version's view, and none for a viewer, who has no check.
14. **4c-1's tests that change on purpose**: a text field's hint gains the pills note; text a write refused is held as
    a `template`; a reference in a text field is a pill (the read-only view tests move to a number field); the If and
    the Filter conditions open in the builder; the browser flows that type a condition press Formula first.

## File Structure

All under `frontend/` unless named. No backend file changes.

New:
- `src/lib/pills.ts`: text and pills as segments, read from and written to what the draft holds; a reference's path
  parsed and named as a pill.
- `src/lib/data.ts`: the scope and samples queries (keyed by the saved revision), and what the drawer says of an
  entry: its type, tags, group, why it may be missing, what a sample's preview kept at a path.
- `src/lib/builder.ts`: the condition builder's model, the operators a type takes, its formulas written and read back.
- `src/routes/editor/drawer/DataTree.tsx`: the data tree (an ARIA tree), with its search and the typed path.
- `src/routes/editor/drawer/Pill.tsx`: a pill's button and its scope question (shared by text and the builder).
- `src/routes/editor/drawer/PillDetails.tsx`: a pill's details, its default and a step's sample.
- `src/routes/editor/drawer/TextPills.tsx`: the editor of text and pills, a text field's "Text" mode.
- `src/routes/editor/drawer/ConditionBuilder.tsx`: the builder, a condition's "Builder" mode.
- `src/routes/editor/DeclassifyPanel.tsx`: the Declassify side panel.
- `e2e/fixtures/data.dewpoint.json`: the browser flows' workflow (a declared trigger input, an If, a sensitive value).
- A test file beside each new module: `src/lib/{pills,data,builder}.test.ts`,
  `src/routes/editor/drawer/{DataTree,PillDetails,TextPills,ConditionBuilder}.test.tsx`,
  `src/routes/editor/DeclassifyPanel.test.tsx`.

Changed:
- `src/lib/config.ts`: `declassify`, `undeclassify`.
- `src/lib/schemaForm.ts`: `takesPills`, `fieldLabel`.
- `src/lib/unapplied.ts`: held kinds `template` and `condition`, how each is written.
- `src/routes/editor/drawer/context.ts`, `StepDrawer.tsx`: the drawer's saved revision, the draft's steps,
  `openDeclassify`.
- `src/routes/editor/drawer/Formula.tsx`: `ModeSwitch`'s fixed mode's name and why it's off.
- `src/routes/editor/drawer/FieldFrame.tsx`: `GroupFrame`'s `below`.
- `src/routes/editor/drawer/FieldView.tsx`: the Text and Builder modes, "＋ Data", the pills note, "Review in
  Declassify…".
- `src/routes/editor/drawer/harness.tsx`: `revision`, `steps`, the fake API's query.
- `src/routes/editor/Editor.tsx`: the drawer's revision and steps, the Declassify panel and its writes, the badge's
  set.
- `src/routes/editor/StepCard.tsx`, `Canvas.tsx`: the "may not run" badge.
- `e2e/workflows.spec.ts`: four flows; two 4c-1 flows press Formula before typing a condition.
- Tests changed beside them: `config`, `schemaForm`, `unapplied`, `FieldView`, `StepCard`, `Editor`.
- `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`: the plan's acceptance and rulings, the milestones, the
  final checkpoint.
- `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`: §2's pills line (ruling 2); §5's B6 and B7 rows say
  where their screens were built.

## Milestones

- **Milestone 1 — the pure layers** (Tasks 1–5). No screen changes. Then the whole unit suite, typecheck and lint.
- **Milestone 2 — pills, the tree, a pill's details** (Tasks 6–8). **Pause:** screenshots of a text field with
  pills, the tree and a pill's details, light and dark, at 1280 and 320 px, beside the mockups, for the owner's review
  before the builder is built.
- **Milestone 3 — the builder, Declassify, the badge** (Tasks 9–11).
- **Milestone 4 — the browser, every check, the final checkpoint** (Task 12). **Pause:** a fresh reviewer, the
  screenshots, the summary; then stop. Nothing is pushed without the owner's OK.

## How to run things

From `frontend/`:
- one test file: `npx -y pnpm@12.6.0 exec vitest run <file>`; the unit suite: `npx -y pnpm@12.6.0 test`;
- `npx -y pnpm@12.6.0 typecheck`, `lint`, `check:api`, `build`;
- the browser gate on the isolated Compose stack: `UI4_WT=<worktree> scratchpad/compose-ui4a/e2e.sh` (about 4 minutes:
  a fresh database, rebuilt images, then Playwright at `http://localhost:18080`);
- local CodeQL: `scratchpad/codeql/scan.sh <sha>` (about 40 s).
The backend is untouched: its suite doesn't run.

## Executing this plan

Proposed: inline, in one session, with the owner's reviews at the milestone pauses (these tasks build on each other's
interfaces, so a fresh context per task would re-read most of them); the owner chooses. Each task is test first: its
tests are written and seen to fail as its Step 2 says, then its code, then they pass. A block is applied exactly:
**Create** writes the file;
**In** … **replace** … **with** replaces text that occurs exactly once (the blocks of a file in the order given). Where
the installed package or the code differs, the executor adapts it test first and records the difference as a mid-slice
ruling in the ledger (M66 onward). The branch is settled with the owner at the start; proposed: `feat/editor-4c2b`
from `origin/main` (6f4ddec7 on, with #84), in its own worktree, this plan's docs branch merged in first. A later main
is merged in,
never rebased.

Every block below was produced from a staged run of this plan (each task's commit typechecked, linted and its tests
passing; the last one identical to the prototype), and the plan's own text was applied once more from scratch, task by
task, by a dry run whose red and green results are each task's Expected lines.

---

# Milestone 1 — the pure layers

### Task 1: The branch, the ledger, and the engine's word on the builder's formulas

The branch starts where the builder's formulas validate and run: main with #84. Before any code, the engine at that
base checks the formulas Task 4 writes, through the run's own binding; and the ledger records the owner's acceptance
and this plan's rulings.

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (append at the end)
- Scratch, never committed: `builder_check.py` and `builder-formulas.json` in the session's scratchpad

**Interfaces:**
- Consumes: main with #84 (`cel.type_name`; `guards.shape` recognises `type(x) == type({})`).
- Produces: the ledger sections later tasks append to (`### 4c-2b, milestone N`); rulings 125–138.

- [ ] **Step 1: The base**

From the repository, with the network (`git fetch` needs it):

```bash
git fetch origin
git log origin/main --oneline | grep -m1 "(#84)"
git worktree add -b feat/editor-4c2b <scratchpad>/ui4/4c2b origin/main
git -C <scratchpad>/ui4/4c2b merge --no-edit docs/editor-ui-4c2b-plan
```

Expected: the `grep` prints #84's squash commit, and the merge brings in this plan (the branch and its base are the
owner's to settle; these are the proposed ones). If the `grep` prints nothing, #84 isn't merged: stop, and tell the
owner (the builder's object test only validates from #84 on, ledger M65). In the new worktree, from `frontend/`:

```bash
npx -y pnpm@12.6.0 install --frozen-lockfile
npx -y pnpm@12.6.0 test
npx -y pnpm@12.6.0 typecheck
```

Expected: the locked packages only (no change to `pnpm-lock.yaml`); unit `Test Files  54 passed (54)`,
`Tests  732 passed (732)`; typecheck clean.

- [ ] **Step 2: The engine checks the builder's formulas**

The builder writes each comparison as its guards, its null test, a type test where its operator needs one, and the
test (ruling 10). These are its formulas for every operator over undeclared trigger data (`trigger.events[0].ev_type`,
with every guard kind, and the list `trigger.tags`), one over a declared field that may be a string
(`trigger.device.name`, whose object test validates only from #84 on), "is there" and "is missing" for an item's
field that's always there, in an optional and in a required list (named by `has()` though their guards stop at the
list), and one combined condition with a group and "is missing". Each is validated as an If's condition, then bound and
evaluated as a run would, over 20 shapes of trigger data: absent, null, another type, an empty list, a list of null, a
device that's a string, and so on. The script also asks the scope for these values, so their guards are the server's,
as the builder gets them.

Write, in the session's scratchpad (not the worktree), `builder-formulas.json`:

````json
{
 "rows": [
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type == \"AP\")",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type != \"AP\")",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && type(trigger.events[0].ev_type) == type(\"\") && trigger.events[0].ev_type.contains(\"AP\"))",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && type(trigger.events[0].ev_type) == type(\"\") && trigger.events[0].ev_type.startsWith(\"AP\"))",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && type(trigger.events[0].ev_type) == type(\"\") && trigger.events[0].ev_type.endsWith(\"AP\"))",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && (type(trigger.events[0].ev_type) == type(0) || type(trigger.events[0].ev_type) == type(0.0)) && trigger.events[0].ev_type > 3)",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && (type(trigger.events[0].ev_type) == type(0) || type(trigger.events[0].ev_type) == type(0.0)) && trigger.events[0].ev_type < 3)",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && (type(trigger.events[0].ev_type) == type(0) || type(trigger.events[0].ev_type) == type(0.0)) && trigger.events[0].ev_type >= 3)",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && (type(trigger.events[0].ev_type) == type(0) || type(trigger.events[0].ev_type) == type(0.0)) && trigger.events[0].ev_type <= 3)",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type == 3)",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type != 3)",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type == true)",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type == false)",
  "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null)",
  "!(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null)",
  "(has(trigger.tags) && trigger.tags != null && type(trigger.tags) == type([]) && size(trigger.tags) == 0)",
  "(has(trigger.tags) && trigger.tags != null && type(trigger.tags) == type([]) && size(trigger.tags) != 0)",
  "(has(trigger.device) && type(trigger.device) == type({}) && has(trigger.device.name) && trigger.device.name == \"AP\")",
  "(has(trigger.olist) && size(trigger.olist) > 0 && has(trigger.olist[0].name))",
  "!(has(trigger.olist) && size(trigger.olist) > 0 && has(trigger.olist[0].name))",
  "(size(trigger.rlist) > 0 && has(trigger.rlist[0].name))",
  "!(size(trigger.rlist) > 0)"
 ],
 "combined": "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type == \"AP\")\n&& ((has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && type(trigger.events[0].ev_type) == type(\"\") && trigger.events[0].ev_type.contains(\"AP\")) || (has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && (type(trigger.events[0].ev_type) == type(0) || type(trigger.events[0].ev_type) == type(0.0)) && trigger.events[0].ev_type > 3))\n&& !(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null)"
}
````

and `builder_check.py`:

````python
"""Scratch (4c-2b, Task 1): the builder's formulas, validated as an If's condition, then bound and run as a run
would, over trigger data of every shape. Run from backend/ with PYTHONPATH=src:. so tests.support is importable."""

import json
import sys

from dewpoint.engine.cel.bind import ScopeView
from dewpoint.engine.cel.evaluate import evaluate_local
from dewpoint.engine.graph.scope import scope
from dewpoint.engine.graph.validate import ValidationContext, validate
from dewpoint.engine.registry.catalog import Catalog, spec_from_manifest
from dewpoint.engine.runtime import resolve
from dewpoint.plugins.flow.nodes import NODES as FLOW
from dewpoint.sdk import node_manifest
from tests.support.graphs import G, nid

CTX = ValidationContext(catalog=Catalog([spec_from_manifest(node_manifest(n)) for n in FLOW]))
RUN = {"id": "00000000-0000-4000-8000-0000000000aa", "started_at": "2026-10-10T00:00:00Z", "now": "2026-10-10T00:00:01Z"}
# The trigger declares a device that may be a string: reading its name needs the object test, which validation
# accepts as `type(x) == type({})` from #84 on. And two lists of items whose name is always there, one optional and one
# required: "is there" for an item's name names it with `has()`, though its guards stop at the list. Its other fields
# are undeclared: any value at all.
ITEM = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
INPUT = {
    "type": "object",
    "properties": {
        "device": {"anyOf": [ITEM, {"type": "string"}]},
        "olist": {"type": "array", "items": ITEM},
        "rlist": {"type": "array", "items": ITEM},
    },
    "required": ["rlist"],
}
SHAPES = [
    {}, {"events": None}, {"events": "s"}, {"events": {}}, {"events": []}, {"events": [None]}, {"events": ["s"]},
    {"events": [{}]}, {"events": [{"ev_type": None}]}, {"events": [{"ev_type": "AP"}]}, {"events": [{"ev_type": 3}]},
    {"events": [{"ev_type": True}], "tags": ["a"]}, {"tags": []}, {"tags": "x"},
    {"device": "s"}, {"device": {"name": "AP"}}, {"device": {"name": "x"}},
    {"olist": []}, {"olist": [{"name": "b"}]}, {"rlist": [{"name": "a"}]},
]
SHAPES = [{"rlist": [], **shape} for shape in SHAPES]  # the required list is always there, as admission makes it

formulas = json.load(open(sys.argv[1]))
# What the builder spells for the device's name: the scope's guards, as data (ledger 119; this plan's ruling 10).
asked = G().node("check", "flow.if@1", {})
asked.settings["input_schema"] = INPUT
for at in ("trigger.device.name", "trigger.olist[0].name", "trigger.rlist[0]"):
    entry = scope(asked.build(), CTX, nid("check"), "/condition", at=at).entries[0]
    print(at, "guards:", [(g.kind, g.path, g.size) for g in entry.formula.guards], "null test:", entry.formula.null_test)
problems = 0
for expr in [*formulas["rows"], formulas["combined"]]:
    g = G().node("check", "flow.if@1", {"condition": {"$value": {"kind": "cel", "expr": expr}}})
    g.settings["declassify"] = [{"node": str(nid("check")), "field": "/condition"}]
    g.settings["input_schema"] = INPUT
    result = validate(g.build(), CTX)
    diags = [d.code for d in result.diagnostics]
    record = next((x for x in result.expressions if x.node == str(nid("check"))), None)
    values: list[object] = []
    for trigger in SHAPES if record is not None else []:
        view = ScopeView(trigger=trigger, steps={}, vars={}, loops={}, run=RUN)
        try:
            resolve.bind_view(record, view)
            out = evaluate_local(record, view)
            values.append(out.value if out.ok else f"ERR {out.error}")
        except resolve.ValueFailure as e:
            values.append(f"FAIL {e.failure.code}")
    bad = bool(diags) or record is None or any(not isinstance(v, bool) for v in values)
    problems += bad
    print(f"{'BAD' if bad else 'OK '} diags={diags} values={values} :: {expr[:80]}")
print("problems:", problems)
````

Run it from the worktree's `backend/`, with a backend environment made from the lock (the worktree's own
`uv sync --frozen`, with the owner's OK as in 4c-2a, or the owner's choice of an existing one at the same `uv.lock`):

```bash
PYTHONPATH=src:. <python> <scratchpad>/builder_check.py <scratchpad>/builder-formulas.json
```

Expected: first the scope's guards, as the builder spells them:

```
trigger.device.name guards: [('present', 'trigger.device', None), ('is_map', 'trigger.device', None), ('present', 'trigger.device.name', None)] null test: False
trigger.olist[0].name guards: [('present', 'trigger.olist', None), ('min_size', 'trigger.olist', 0)] null test: False
trigger.rlist[0] guards: [('min_size', 'trigger.rlist', 0)] null test: False
```

then 23 lines starting `OK `, each with `diags=[]` and only `True` or `False` values (never `ERR` or `FAIL`); then
`problems: 0`. (On main before #84, the device's line is `BAD
diags=['cel.conditional_ref']`: that's what the base check is for.) A line starting `BAD` stops the plan: the builder's
formulas would fail where it promises they don't. Tell the owner.

- [ ] **Step 3: The ledger**

Append, after the ledger's last section, with the date and the owner's choices as given in chat:

```markdown
### 4c-2b plan accepted (<date>, in chat)

`docs/superpowers/plans/2026-10-10-editor-ui-4c2b-data-ui.md`. The owner, asked in chat, accepted revision <N> and
adopted its rulings 1–14, which join this ledger as 125–138, copied as ruled; chose <the execution method> with the
milestone pauses (the screens of text, pills, the tree and a pill's details after Milestone 2; a fresh review at the
end); and the branch `feat/editor-4c2b` from origin/main (<sha>, with #84). Push and a PR stay the owner's decisions.

The builder's formulas, checked on that base (`builder_check.py`, the plan's Task 1): 23 formulas validate clean as an
If's condition and, bound and evaluated as a run would, give true or false, never an error, over 20 shapes of trigger
data; the scope's guards for a declared field that may be a string, and for an item's field in an optional and a
required list, are the ones the builder spells.
```

Then the rulings, numbered 125 to 138, each the plan's ruling of the same order (1 is 125, 14 is 138), its text
copied whole after **Accepted.**, as 114–124 were:

```markdown
125. **Accepted. One editor of inputs and pills.** Text with pills is a row of text inputs with a pill button between
     each two, in one box: …
```

Each amendment the owner made in accepting is written in the ruling it changes, in the owner's words. Mid-slice rulings
are numbered from M66.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): the 4c-2b plan accepted, its rulings, and the builder's formulas checked

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Text and pills, and a reference's path (`lib/pills.ts`)

A text field's value as text and pills: n pills between n + 1 texts. What the draft holds is read into it (a string, a
literal's text, a template, a plain reference) and written back from it (text, a literal, a template; ruling 4). A
reference's path is parsed by the engine's grammar (R6 §2) and named as a pill: `get_site › name`. Pure functions, no
screen.

**Files:**
- Create: `frontend/src/lib/pills.test.ts`
- Create: `frontend/src/lib/pills.ts`

**Interfaces:**
- Consumes: `ENVELOPE`, `fixedOf`, `kindOf`, `literal` from `lib/config.ts`; `isObject` from `lib/schemaForm.ts`.
- Produces: `Pill { ref; default?: string | null }`, `Segments { texts; pills }`, `Caret { segment; offset }`,
  `segmentsOf(value): Segments | null`, `valueOf(s, asLiteral, literalOk = true)`, `sameSegments`, `insertPill(s, at,
  pill)`, `removePill(s, index): { segments; caret }`, `withDefault(s, index, def)`, `replacePill(s, index, ref)`,
  `withText(s, segment, text)`, `segmentsText(s)` (braces), `PathPart`, `parsePath(path)`, `headOf(path): { head; rest
  }`, `pillText(path)`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/lib/pills.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { formula, literal } from "./config";
import {
  headOf, insertPill, parsePath, pillText, removePill, replacePill, sameSegments, segmentsOf, segmentsText, valueOf,
  withDefault, withText, type Segments,
} from "./pills";  // prettier-ignore

const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });
const ref = (path: string, extra: object = {}) => ({ $value: { kind: "ref", path, ...extra } });

describe("text and pills", () => {
  it("reads text, a literal's text, a reference and a template as text and pills", () => {
    expect(segmentsOf(undefined)).toEqual({ texts: [""], pills: [] });
    expect(segmentsOf("AP down")).toEqual({ texts: ["AP down"], pills: [] });
    expect(segmentsOf(literal("$value"))).toEqual({ texts: ["$value"], pills: [] });
    expect(segmentsOf(ref("steps.a.output.name"))).toEqual({ texts: ["", ""], pills: [{ ref: "steps.a.output.name" }] });
    const value = template({ text: "AP " }, { ref: "trigger.ap", default: "AP" }, { text: " at " }, { ref: "run.now" });
    expect(segmentsOf(value)).toEqual({
      texts: ["AP ", " at ", ""],
      pills: [{ ref: "trigger.ap", default: "AP" }, { ref: "run.now" }],
    });
  });

  it("joins texts written in several parts, and puts empty text between pills side by side", () => {
    const value = template({ text: "a" }, { text: "b" }, { ref: "run.id" }, { ref: "run.now" });
    expect(segmentsOf(value)).toEqual({ texts: ["ab", "", ""], pills: [{ ref: "run.id" }, { ref: "run.now" }] });
  });

  it("reads nothing it can't write back the same: a formula, a number, an object, a default that isn't text", () => {
    expect(segmentsOf(formula("1 + 1"))).toBeNull();
    expect(segmentsOf(3)).toBeNull();
    expect(segmentsOf({ a: 1 })).toBeNull();
    expect(segmentsOf(literal(3))).toBeNull();
    expect(segmentsOf(template({ ref: "run.id", default: 3 }))).toBeNull();
    expect(segmentsOf(template({ ref: "run.id", text: "x" }))).toBeNull();
    expect(segmentsOf({ $value: { kind: "template", parts: "nope" } })).toBeNull();
  });

  it("writes text as text, a literal's as a literal, and pills as a template without its empty texts", () => {
    expect(valueOf({ texts: [""], pills: [] }, false)).toBeUndefined();
    expect(valueOf({ texts: ["hi"], pills: [] }, false)).toBe("hi");
    expect(valueOf({ texts: ["hi"], pills: [] }, true)).toEqual(literal("hi"));
    expect(valueOf({ texts: ["", ""], pills: [{ ref: "run.now" }] }, false)).toEqual(template({ ref: "run.now" }));
    expect(valueOf({ texts: ["a ", "", " b"], pills: [{ ref: "x.y", default: null }, { ref: "run.id" }] }, false)).toEqual(
      template({ text: "a " }, { ref: "x.y", default: null }, { ref: "run.id" }, { text: " b" }),
    );
  });

  it("reads back what it writes", () => {
    const s: Segments = { texts: ["AP ", " at ", ""], pills: [{ ref: "trigger.ap", default: "AP" }, { ref: "run.now" }] };
    expect(sameSegments(segmentsOf(valueOf(s, false))!, s)).toBe(true);
  });

  it("puts a pill at the caret, splitting its text, and takes one away joining the texts either side", () => {
    const s: Segments = { texts: ["AP went offline"], pills: [] };
    const put = insertPill(s, { segment: 0, offset: 3 }, { ref: "trigger.ap" });
    expect(put).toEqual({ texts: ["AP ", "went offline"], pills: [{ ref: "trigger.ap" }] });
    expect(removePill(put, 0)).toEqual({ segments: s, caret: { segment: 0, offset: 3 } });
    expect(insertPill(s, { segment: 0, offset: 99 }, { ref: "run.id" }).texts).toEqual(["AP went offline", ""]);
  });

  it("gives a pill a default, changes it, and takes it away", () => {
    const s: Segments = { texts: ["", ""], pills: [{ ref: "trigger.ap" }] };
    const given = withDefault(s, 0, "AP");
    expect(given.pills[0]).toEqual({ ref: "trigger.ap", default: "AP" });
    expect(withDefault(given, 0, null).pills[0]).toEqual({ ref: "trigger.ap", default: null });
    expect(withDefault(given, 0, undefined).pills[0]).toEqual({ ref: "trigger.ap" });
    expect(replacePill(given, 0, "trigger.site").pills[0]).toEqual({ ref: "trigger.site", default: "AP" });
    expect(withText(given, 1, "!").texts).toEqual(["", "!"]);
  });

  it("says text and pills as braces", () => {
    expect(segmentsText({ texts: ["AP ", " down"], pills: [{ ref: "trigger.ap" }] })).toBe("AP {trigger.ap} down");
  });
});

describe("a reference's path", () => {
  it("parses roots, fields and indexes, and refuses what isn't a path", () => {
    expect(parsePath("steps.list.output.results[0].name")).toEqual([
      { field: "steps" }, { field: "list" }, { field: "output" }, { field: "results" }, { index: 0 }, { field: "name" },
    ]);  // prettier-ignore
    for (const bad of ["", "[0]", "a..b", "a.", "a[01]", "a[-1]", "a.b-c", "a b", "a.[0]"]) expect(parsePath(bad)).toBeNull();
  });

  it("names a pill by its step, a loop or its root, then what it reads", () => {
    expect(pillText("steps.get_site.output.name")).toBe("get_site › name");
    expect(pillText("steps.get_site.output")).toBe("get_site");
    expect(pillText("steps.call.error.message")).toBe("call › error.message");
    expect(pillText("trigger.events[0].ap_name")).toBe("trigger › events[0].ap_name");
    expect(pillText("trigger")).toBe("trigger");
    expect(pillText("run.now")).toBe("run › now");
    expect(pillText("loops.each.item.mac")).toBe("each › item.mac");
    expect(pillText("vars.limit")).toBe("vars › limit");
    expect(pillText("item")).toBe("item");
    expect(headOf("steps.list.output[0].x")).toEqual({ head: "list", rest: "[0].x" });
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/pills.test.ts`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  no tests`. The run can't import `./pills`: it doesn't exist yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/lib/pills.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// Text with data pills (4c-2b): a text field's value as the editor shows it, its text and the references between it
// (engine/graph/values.py's `template`), and a reference's path as a pill names it. Pure functions: the drawer's
// controls draw them, the editor writes what they make.
import { ENVELOPE, fixedOf, kindOf, literal } from "./config";
import { isObject } from "./schemaForm";

/** A reference written in text: its path, and the text it reads as when its value is missing or null. */
export interface Pill {
  ref: string;
  default?: string | null; // a template part's `default`: absent, there's none
}

/** A text field's value as text and pills: n pills between n + 1 texts, each possibly empty. */
export interface Segments {
  texts: string[];
  pills: Pill[];
}

/** Where the caret is: in which text, and how far into it. */
export interface Caret {
  segment: number;
  offset: number;
}

const EMPTY: Segments = { texts: [""], pills: [] };

const bodyOf = (value: unknown): Record<string, unknown> =>
  isObject(value) && isObject(value[ENVELOPE]) ? value[ENVELOPE] : {};

/** A part's `default` as a pill keeps it: text or null; any other value isn't one this editor writes. */
const defaultOf = (part: Record<string, unknown>): Pick<Pill, "default"> | null => {
  if (!("default" in part)) return {};
  const d = part.default;
  return typeof d === "string" || d === null ? { default: d } : null;
};

/** The value as text and pills, or null when it's neither (a formula, a number, an object, an envelope the editor
 * can't read, a template part it doesn't know): the field then shows it some other way. */
export function segmentsOf(value: unknown): Segments | null {
  if (value === undefined || value === null) return EMPTY;
  const kind = kindOf(value);
  if (kind === null || kind === "literal") {
    const fixed = fixedOf(value);
    return typeof fixed === "string" ? { texts: [fixed], pills: [] } : null;
  }
  const body = bodyOf(value);
  if (kind === "ref") {
    const ref = body.path;
    const d = defaultOf(body);
    return typeof ref === "string" && d !== null ? { texts: ["", ""], pills: [{ ref, ...d }] } : null;
  }
  if (kind !== "template" || !Array.isArray(body.parts)) return null;
  const texts = [""];
  const pills: Pill[] = [];
  for (const part of body.parts as unknown[]) {
    if (!isObject(part)) return null;
    if (typeof part.text === "string" && !("ref" in part)) {
      texts[texts.length - 1] += part.text;
      continue;
    }
    const d = defaultOf(part);
    if (typeof part.ref !== "string" || d === null || "text" in part) return null;
    pills.push({ ref: part.ref, ...d });
    texts.push("");
  }
  return { texts, pills };
}

/** What the draft holds for text and pills: nothing, when it's empty; the text, when there are no pills (a literal's
 * payload written back as one); else a template, its empty texts left out. A lone pill is a template too: text, as
 * the field takes it, never the value it reads (which may not be text). */
export function valueOf(s: Segments, asLiteral: boolean, literalOk = true): unknown {
  if (s.pills.length === 0) {
    const text = s.texts.join("");
    if (text === "") return undefined;
    // Where the engine takes no fixed value, text alone is a template of one text part (x-dewpoint-kinds).
    if (!literalOk) return { [ENVELOPE]: { kind: "template", parts: [{ text }] } };
    return asLiteral ? literal(text) : text;
  }
  const parts: Record<string, unknown>[] = [];
  s.texts.forEach((text, i) => {
    if (text !== "") parts.push({ text });
    const pill = s.pills[i];
    if (pill) parts.push("default" in pill ? { ref: pill.ref, default: pill.default } : { ref: pill.ref });
  });
  return { [ENVELOPE]: { kind: "template", parts } };
}

/** Whether two values show the same text and pills: what's written only when a person changes it. */
export function sameSegments(a: Segments, b: Segments): boolean {
  return (
    a.texts.length === b.texts.length &&
    a.texts.every((t, i) => t === b.texts[i]) &&
    a.pills.every((p, i) => {
      const q = b.pills[i]!;
      return p.ref === q.ref && "default" in p === "default" in q && p.default === q.default;
    })
  );
}

/** The text with a pill put at the caret: its text split there. */
export function insertPill(s: Segments, at: Caret, pill: Pill): Segments {
  const text = s.texts[at.segment] ?? "";
  const offset = Math.max(0, Math.min(at.offset, text.length));
  return {
    texts: [...s.texts.slice(0, at.segment), text.slice(0, offset), text.slice(offset), ...s.texts.slice(at.segment + 1)],
    pills: [...s.pills.slice(0, at.segment), pill, ...s.pills.slice(at.segment)],
  };
}

/** The text without its `index`th pill, the texts either side joined, and where the caret goes: where it was. */
export function removePill(s: Segments, index: number): { segments: Segments; caret: Caret } {
  const before = s.texts[index] ?? "";
  const after = s.texts[index + 1] ?? "";
  return {
    segments: {
      texts: [...s.texts.slice(0, index), before + after, ...s.texts.slice(index + 2)],
      pills: [...s.pills.slice(0, index), ...s.pills.slice(index + 1)],
    },
    caret: { segment: index, offset: before.length },
  };
}

/** The pill `index` reading `def` when its value is missing or null; undefined takes its default away. */
export function withDefault(s: Segments, index: number, def: string | null | undefined): Segments {
  const pills = s.pills.map((p, i) => {
    if (i !== index) return p;
    return def === undefined ? { ref: p.ref } : { ref: p.ref, default: def };
  });
  return { texts: s.texts, pills };
}

/** The pill `index` reading another path: its default kept, as what to say when that one is missing. */
export const replacePill = (s: Segments, index: number, ref: string): Segments => ({
  texts: s.texts,
  pills: s.pills.map((p, i) => (i === index ? { ...p, ref } : p)),
});

/** The text with a text changed. */
export const withText = (s: Segments, segment: number, text: string): Segments => ({
  texts: s.texts.map((t, i) => (i === segment ? text : t)),
  pills: s.pills,
});

/** Text and pills as a person reads them back (the recovery file, the list of edits not applied): each pill in braces,
 * as the read-only view writes a template (config.ts's referenceText). */
export const segmentsText = (s: Segments): string =>
  s.texts.map((t, i) => (s.pills[i] ? `${t}{${s.pills[i].ref}}` : t)).join("");

// A reference's path: a root, then fields and indexes (engine/graph/values.py's reference grammar: a field is a name,
// `[A-Za-z_][A-Za-z0-9_]*`; an index is `[n]`).
export type PathPart = { field: string } | { index: number };

const NAME = /^[A-Za-z_][A-Za-z0-9_]*/;

/** The parts of a path (its root first, as a field), or null when it isn't one. */
export function parsePath(path: string): PathPart[] | null {
  const parts: PathPart[] = [];
  let rest = path;
  let first = true;
  while (rest !== "") {
    if (rest.startsWith("[")) {
      const m = /^\[(0|[1-9][0-9]*)\]/.exec(rest);
      if (!m || first) return null;
      parts.push({ index: Number(m[1]) });
      rest = rest.slice(m[0].length);
    } else {
      if (!first) {
        if (!rest.startsWith(".")) return null;
        rest = rest.slice(1);
      }
      const m = NAME.exec(rest);
      if (!m) return null;
      parts.push({ field: m[0] });
      rest = rest.slice(m[0].length);
    }
    first = false;
  }
  return parts.length > 0 ? parts : null;
}

const partText = (parts: PathPart[]): string =>
  parts.map((p, i) => ("index" in p ? `[${p.index}]` : i === 0 ? p.field : `.${p.field}`)).join("");

/** Where a path starts, as a pill says it, and what it reads below: `steps.get_site.output.name` is get_site's name;
 * a loop's `item` or `index` is its loop's; every other root (trigger, vars, item, index, run) is its own. */
export function headOf(path: string): { head: string; rest: string } {
  const parts = parsePath(path);
  if (!parts) return { head: path, rest: "" };
  const field = (i: number) => {
    const p = parts[i];
    return p && "field" in p ? p.field : null;
  };
  let used = 1;
  let head = field(0) ?? path;
  if (head === "steps" && field(1) !== null) {
    head = field(1)!;
    used = field(2) === "output" ? 3 : 2; // a step's output is what it gives: its error is said
  } else if (head === "loops" && field(1) !== null) {
    head = field(1)!;
    used = 2;
  }
  const rest = parts.slice(used);
  return { head, rest: partText(rest) };
}

/** A pill's visible text: `get_site › name`, `trigger › events[0].ap_name`, `run › now`; a root alone is its name. */
export function pillText(path: string): string {
  const { head, rest } = headOf(path);
  return rest === "" ? head : `${head} › ${rest}`;
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/pills.test.ts`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  10 passed (10)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/pills.test.ts frontend/src/lib/pills.ts
git commit -m "feat(editor): text and data pills as segments, and a reference's path as a pill names it (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: The scope and samples client, and their words (`lib/data.ts`)

The two 4c-2a routes as queries, keyed by the saved draft's revision, so a newer revision asks again and an answer about
another revision is never taken for the one asked of (D17; ruling 6); a sample asked for each time it's shown (ruling
9); and what the drawer says of an entry: its type in words, its tags, its group, why it may be missing (from its
guards, never re-derived: ruling 119), and what a sample's preview kept at a path (`[redacted]`, `[truncated]`, a value
kept apart: R6 §8).

**Files:**
- Create: `frontend/src/lib/data.test.ts`
- Create: `frontend/src/lib/data.ts`

**Interfaces:**
- Consumes: `client`, `ok`, `Schemas` from `lib/client.ts`; `headOf` (Task 2).
- Produces: types `ScopeAnswer`, `ScopeEntry`, `Guard`, `SamplesAnswer`, `Sample`, `SampleConnection`; `Ask`; `Where {
  tenantId; workflowId; revision; node; field }`; `DraftMoved` (an `Error` with the `revision` answered; its message is
  what the drawer says); `scopeQuery(where, ask)`; `samplesQuery(where without field, iteration?)`; `typeWords(entry)`;
  `Tag`; `tagsOf(entry)`; `groupOf(entry, titleOf)`; `whyMissing(entry)`; `previewAt(output, path)`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/lib/data.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DraftMoved, groupOf, previewAt, samplesQuery, scopeQuery, tagsOf, typeWords, whyMissing, type ScopeEntry } from "./data";

const entry = (over: Partial<ScopeEntry>): ScopeEntry => ({
  children: false, format: null, formula: { guards: [], null_test: false, sensitive: false }, missing: false,
  name: "name", nameable: true, nullable: false, parent: null, path: "steps.get_site.output.name", problem: null,
  root: "steps", sensitive: false, step: "00000000-0000-4000-8000-000000000002", types: ["string"], ...over,
});  // prettier-ignore

describe("the words for data", () => {
  it("says a type as the tree does", () => {
    expect(typeWords(entry({ types: ["string"] }))).toBe("text");
    expect(typeWords(entry({ types: ["string"], format: "date-time" }))).toBe("date and time");
    expect(typeWords(entry({ types: ["integer", "null"] }))).toBe("whole number");
    expect(typeWords(entry({ types: ["boolean"] }))).toBe("yes or no");
    expect(typeWords(entry({ types: ["array"] }))).toBe("list");
    expect(typeWords(entry({ types: [] }))).toBe("any value");
    expect(typeWords(entry({ types: ["null"] }))).toBe("always null");
    expect(typeWords(entry({ types: ["string", "integer"] }))).toBe("text or whole number");
  });

  it("tags what may be missing (dashed), what may be null and what's sensitive", () => {
    expect(tagsOf(entry({ missing: true, nullable: true, sensitive: true }))).toEqual([
      { text: "may be missing", conditional: true },
      { text: "may be null", conditional: false },
      { text: "sensitive", conditional: false },
    ]);
    expect(tagsOf(entry({}))).toEqual([]);
  });

  it("groups a step's data under its key and its type's title, and the rest by what they are", () => {
    const title = (k: string) => (k === "get_site" ? "Get a site" : null);
    expect(groupOf(entry({}), title)).toEqual({ key: "steps.get_site", title: "get_site", detail: "Get a site" });
    expect(groupOf(entry({ root: "trigger", path: "trigger.a" }), title).title).toBe("Trigger");
    expect(groupOf(entry({ root: "run", path: "run.now" }), title).title).toBe("This run");
    expect(groupOf(entry({ root: "loops", path: "loops.each.item" }), title)).toMatchObject({ key: "loops.each", title: "each" });
  });

  it("says why a value may be missing from its guards", () => {
    const e = entry({
      path: "steps.list.output.results[0].name",
      missing: true,
      formula: {
        guards: [
          { kind: "present", path: "steps.list.output", size: null },
          { kind: "min_size", path: "steps.list.output.results", size: 0 },
          { kind: "is_map", path: "steps.list.output.results[0]", size: null },
          { kind: "present", path: "steps.list.output.results[0].name", size: null },
        ],
        null_test: false,
        sensitive: false,
      },
    });
    expect(whyMissing(e)).toEqual([
      "list may not run",
      "steps.list.output.results may have fewer items",
      "steps.list.output.results[0] may be another kind of value",
      "it's optional in its data",
    ]);
    expect(whyMissing(entry({ root: "trigger", path: "trigger", types: [], missing: true, formula: null }))).toEqual([
      "the trigger's input isn't declared",
    ]);
  });
});

describe("a value in a sample's preview", () => {
  it("follows a path, and stops where the preview kept no value: redacted, truncated, kept apart, or absent", () => {
    const out = { results: [{ name: "ap-1" }, { $claim: "u1" }], token: "[redacted]", big: { $claim: "u2", pointer: "/x" } };
    expect(previewAt(out, ["results", 0, "name"])).toEqual({ value: "ap-1" });
    expect(previewAt(out, ["results", 1, "name"])).toEqual({ marker: "claimed" });
    expect(previewAt(out, ["big"])).toEqual({ marker: "claimed" });
    expect(previewAt(out, ["token"])).toEqual({ marker: "redacted" });
    expect(previewAt("[truncated]", ["results"])).toEqual({ marker: "truncated" });
    expect(previewAt(out, ["results", 5])).toEqual({ marker: "absent" });
    expect(previewAt(out, ["nope"])).toEqual({ marker: "absent" });
  });
});

describe("the questions asked of the saved draft", () => {
  it("asks each saved revision apart, so a newer revision asks again and never shows an older answer (D17)", () => {
    const where = { tenantId: "t", workflowId: "w", revision: 3, node: "n", field: "/message" };
    const top = scopeQuery(where, { kind: "top" }).queryKey;
    expect(scopeQuery({ ...where }, { kind: "top" }).queryKey).toEqual(top);
    expect(scopeQuery({ ...where, revision: 4 }, { kind: "top" }).queryKey).not.toEqual(top);
    expect(scopeQuery({ ...where, field: "/subject" }, { kind: "top" }).queryKey).not.toEqual(top);
    expect(scopeQuery(where, { kind: "at", path: "trigger.site" }).queryKey).not.toEqual(top);
    const step = { tenantId: "t", workflowId: "w", revision: 3, node: "n" };
    expect(samplesQuery({ ...step, revision: 4 }).queryKey).not.toEqual(samplesQuery(step).queryKey);
    expect(samplesQuery(step, "2").queryKey).not.toEqual(samplesQuery(step).queryKey);
  });
});

describe("the answers of the saved draft", () => {
  afterEach(() => vi.restoreAllMocks());
  const answering = (body: unknown) => vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(new Response(JSON.stringify(body))));
  const where = { tenantId: "t", workflowId: "w", revision: 1, node: "n", field: "/message" };
  const step = { tenantId: "t", workflowId: "w", revision: 1, node: "n" };

  it("takes no answer about another revision than the one it asked of (the review of revision 1)", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const scope = { node: "n", field: "/message", state: "ok", reason: null, entries: [], more: false, problem: null };
    answering({ draft_revision: 2, ...scope });
    await expect(client.fetchQuery(scopeQuery(where, { kind: "top" }))).rejects.toBeInstanceOf(DraftMoved);
    answering({ draft_revision: 2, node: "n", sample: null, searched_runs: 0, search_limit: 200 });
    await expect(client.fetchQuery(samplesQuery(step))).rejects.toBeInstanceOf(DraftMoved);
    answering({ draft_revision: 1, ...scope });
    await expect(client.fetchQuery(scopeQuery(where, { kind: "top" }))).resolves.toMatchObject({ draft_revision: 1 });
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/data.test.ts`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  no tests`. The run can't import `./data`: it doesn't exist yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/lib/data.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// The data a step's field can read, and a step's newest sample (4c-2b): the scope (B6, ledger rulings 117–120) and the
// samples (B7, rulings 122–123) of the saved draft, asked per revision, and how the drawer says them. The server
// decides every type, guard and sensitivity (D18): this only names them.
import { queryOptions } from "@tanstack/react-query";
import { client, ok, type Schemas } from "./client";
import { headOf } from "./pills";

export type ScopeAnswer = Schemas["ScopeOut"];
export type ScopeEntry = Schemas["ScopeEntryOut"];
export type Guard = Schemas["GuardOut"];
export type SamplesAnswer = Schemas["SamplesOut"];
export type Sample = Schemas["SampleOut"];
export type SampleConnection = Schemas["SampleConnectionOut"];

/** What a field asks of its scope: the top of each root, one path's children, one path, or names containing text. */
export type Ask = { kind: "top" } | { kind: "under"; path: string } | { kind: "at"; path: string } | { kind: "find"; text: string };

/** Which field of which saved draft: an answer is for one revision, and a newer one asks again (D17). */
export interface Where {
  tenantId: string;
  workflowId: string;
  revision: number;
  node: string;
  field: string;
}

/** An answer about another revision than the one asked of: the API answers for the saved draft as it is, and it was
 * saved again meanwhile (D17). It's never shown as the asked revision's (the review of revision 1). */
export class DraftMoved extends Error {
  constructor(readonly revision: number) {
    super("The draft was saved again while its data was asked for. Close this and open it again.");
    this.name = "DraftMoved";
  }
}

const ofRevision =
  (revision: number) =>
  <T extends { draft_revision: number }>(answer: T): T => {
    if (answer.draft_revision !== revision) throw new DraftMoved(answer.draft_revision);
    return answer;
  };

const askQuery = (ask: Ask) =>
  ask.kind === "under" ? { under: ask.path } : ask.kind === "at" ? { at: ask.path } : ask.kind === "find" ? { find: ask.text } : {};

export const scopeQuery = (where: Where, ask: Ask) =>
  queryOptions({
    queryKey: ["scope", where.tenantId, where.workflowId, where.revision, where.node, where.field, ask],
    queryFn: () =>
      ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/scope", {
          params: {
            path: { tenant_id: where.tenantId, workflow_id: where.workflowId },
            query: { node: where.node, field: where.field, ...askQuery(ask) },
          },
        }),
      ).then(ofRevision(where.revision)),
    staleTime: Infinity, // a revision's answer doesn't change: the next revision asks again
  });

/** A step's newest sample, against the saved draft (B7). Asked for again each time it's shown: runs end, connections
 * change and history expires whatever the draft's revision (the review of revision 1). */
export const samplesQuery = (where: Omit<Where, "field">, iteration?: string) =>
  queryOptions({
    queryKey: ["samples", where.tenantId, where.workflowId, where.revision, where.node, iteration ?? null],
    queryFn: () =>
      ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft/samples", {
          params: {
            path: { tenant_id: where.tenantId, workflow_id: where.workflowId },
            query: { node: where.node, ...(iteration === undefined ? {} : { iteration }) },
          },
        }),
      ).then(ofRevision(where.revision)),
    staleTime: 0,
  });

const WORDS: Record<string, string> = {
  string: "text",
  integer: "whole number",
  number: "number",
  boolean: "yes or no",
  array: "list",
  object: "object",
};

/** A value's type in words: what the tree and a pill's details say. */
export function typeWords(entry: Pick<ScopeEntry, "types" | "format">): string {
  const types = entry.types.filter((t) => t !== "null");
  if (entry.types.length === 0) return "any value";
  if (types.length === 0) return "always null";
  return types
    .map((t) => (t === "string" && entry.format === "date-time" ? "date and time" : (WORDS[t] ?? t)))
    .join(" or ");
}

export interface Tag {
  text: string;
  conditional: boolean; // drawn dashed, as a conditional pill is
}

/** What a value may do when the step runs, and whether a reference to it holds sensitive data. */
export function tagsOf(entry: Pick<ScopeEntry, "missing" | "nullable" | "sensitive">): Tag[] {
  return [
    entry.missing ? { text: "may be missing", conditional: true } : null,
    entry.nullable ? { text: "may be null", conditional: false } : null,
    entry.sensitive ? { text: "sensitive", conditional: false } : null,
  ].filter((t): t is Tag => t !== null);
}

/** The group a root's entries show under: a step by its key and its type's title, the others by what they are. */
export function groupOf(entry: Pick<ScopeEntry, "root" | "path">, titleOf: (key: string) => string | null): { key: string; title: string; detail: string | null } {
  const { head } = headOf(entry.path);
  switch (entry.root) {
    case "steps":
      return { key: `steps.${head}`, title: head, detail: titleOf(head) };
    case "loops":
      return { key: `loops.${head}`, title: head, detail: "its loop's item" };
    case "trigger":
      return { key: "trigger", title: "Trigger", detail: null };
    case "vars":
      return { key: "vars", title: "Variables", detail: null };
    case "run":
      return { key: "run", title: "This run", detail: null };
    default:
      return { key: entry.root, title: "This item", detail: null }; // item and index
  }
}

/** Why a value may be missing or null, from the guards a formula needs to read it (ruling 119): the server's own
 * reasons, in words. Empty when it's always there. */
export function whyMissing(entry: Pick<ScopeEntry, "formula" | "missing" | "nullable" | "path" | "types" | "root">): string[] {
  const guards = entry.formula?.guards ?? [];
  const reasons: string[] = [];
  for (const g of guards) {
    const step = /^steps\.([A-Za-z_][A-Za-z0-9_]*)\.(output|error)$/.exec(g.path);
    if (g.kind === "present" && step) reasons.push(`${step[1]} may not run`);
    else if (g.kind === "present") reasons.push(g.path === entry.path ? "it's optional in its data" : `${g.path} is optional`);
    else if (g.kind === "not_null" && g.path !== entry.path) reasons.push(`${g.path} may be null`);
    else if (g.kind === "min_size") reasons.push(`${g.path} may have fewer items`);
    else if (g.kind === "is_map" || g.kind === "is_list") reasons.push(`${g.path} may be another kind of value`);
  }
  if (entry.root === "trigger" && entry.types.length === 0) reasons.push("the trigger's input isn't declared");
  if (entry.nullable) reasons.push("it may be null");
  return [...new Set(reasons)];
}

/** A value the run kept apart from its history (engine/handles.py: `{"$claim": id}`, a pointer maybe): not in a
 * preview (R6 §8). */
const claimed = (v: unknown): boolean =>
  typeof v === "object" && v !== null && !Array.isArray(v) && "$claim" in v && Object.keys(v).every((k) => k === "$claim" || k === "pointer");

/** What a preview kept at a path below a step's output: the value; a marker where the preview stopped (a `[redacted]`
 * or `[truncated]` that stands for the whole value, D20, or a value kept apart); or nothing, when that run's output
 * didn't hold it. */
export function previewAt(output: unknown, path: (string | number)[]): { value: unknown } | { marker: "redacted" | "truncated" | "claimed" | "absent" } {
  let at = output;
  for (const key of path) {
    if (at === "[redacted]") return { marker: "redacted" };
    if (at === "[truncated]") return { marker: "truncated" };
    if (claimed(at)) return { marker: "claimed" };
    if (typeof key === "number" && Array.isArray(at) && key < at.length) at = (at as unknown[])[key];
    else if (typeof key === "string" && typeof at === "object" && at !== null && !Array.isArray(at) && Object.hasOwn(at, key)) at = (at as Record<string, unknown>)[key];
    else return { marker: "absent" };
  }
  if (at === "[redacted]") return { marker: "redacted" };
  if (at === "[truncated]") return { marker: "truncated" };
  if (claimed(at)) return { marker: "claimed" };
  return { value: at };
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/data.test.ts`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  7 passed (7)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/data.test.ts frontend/src/lib/data.ts
git commit -m "feat(editor): the scope and samples of the saved draft, and how the drawer says them (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: The condition builder's formulas (`lib/builder.ts`)

Comparisons joined by all or any, one level of groups, written as CEL that is false, never an error, on any data (ruling
10, R6 §4–5), and read back only when it's the exact text the builder writes (ruling 11), never failing on another's
text. "is there" and "is missing" end with a test of the value itself, so the formula names it, and are offered only
where something may be missing; "is not empty" is `size(x) != 0`, so every comparison reads back as itself. The guards
come from the scope as data; the builder only spells them, never with a type's name (ledger M65). Task 1's check has the
engine validate these forms and run them through the run's own binding, at the branch's base.

**Files:**
- Create: `frontend/src/lib/builder.test.ts`
- Create: `frontend/src/lib/builder.ts`

**Interfaces:**
- Consumes: `Guard` (Task 3).
- Produces: `Op`, `OP_WORDS`, `Literal`, `Row { path; op; value; guards; nullTest }`, `Group { match; rows }`,
  `Condition { match; items }`, `isGroup`, `NO_VALUE`, `opsFor(types, format, mayBeMissing)`, `numeric(types)`,
  `valueProblem(value, path)`, `guardCel(g)`, `thereOf(row)`, `rowCel(row)`, `write(condition)`, `read(formula)`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/lib/builder.test.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { NO_VALUE, OP_WORDS, opsFor, read, rowCel, valueProblem, write, type Condition, type Op, type Row } from "./builder";
import type { Guard } from "./data";

const g = (kind: Guard["kind"], path: string, size: number | null = null): Guard => ({ kind, path, size });
const EV = "trigger.events[0].ev_type";
const EVENT_GUARDS = [
  g("present", "trigger.events"), g("is_list", "trigger.events"), g("min_size", "trigger.events", 0),
  g("is_map", "trigger.events[0]"), g("present", EV),
];  // prettier-ignore
const row = (over: Partial<Row>): Row => ({ path: "steps.s.output.name", op: "is", value: { kind: "text", text: "x" }, guards: [], nullTest: false, ...over });

describe("the condition builder's formulas", () => {
  it("writes each comparison as its guards, its null test, a type test where the operator needs one, and the test", () => {
    expect(rowCel(row({ path: EV, guards: EVENT_GUARDS, nullTest: true, value: { kind: "text", text: "AP_DISCONNECTED" } }))).toBe(
      '(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].ev_type) && trigger.events[0].ev_type != null && trigger.events[0].ev_type == "AP_DISCONNECTED")',
    );
    expect(rowCel(row({ path: "steps.l.output.total", op: "more", value: { kind: "number", text: "0" }, nullTest: true }))).toBe(
      "(steps.l.output.total != null && (type(steps.l.output.total) == type(0) || type(steps.l.output.total) == type(0.0)) && steps.l.output.total > 0)",
    );
    expect(rowCel(row({ op: "starts_with", value: { kind: "text", text: "HQ-" } }))).toBe(
      '(type(steps.s.output.name) == type("") && steps.s.output.name.startsWith("HQ-"))',
    );
    expect(rowCel(row({ op: "is_missing", guards: [g("present", "steps.s.output.tz")], path: "steps.s.output.tz", value: null }))).toBe(
      "!(has(steps.s.output.tz))",
    );
  });

  it("names no type: every type test compares with a value's type", () => {
    const all = rowCel(row({ path: EV, guards: EVENT_GUARDS, op: "contains" }));
    expect(all).not.toMatch(/==\s*(map|list|string|int|double|bool)\b/);
  });

  it("joins comparisons by all or any, a group in parentheses, each item on its line", () => {
    const c: Condition = {
      match: "all",
      items: [
        row({ path: "steps.a.output.n", op: "is", value: { kind: "number", text: "5" } }),
        { match: "any", rows: [row({ op: "starts_with", value: { kind: "text", text: "HQ-" } }), row({ op: "is_true", value: null, path: "steps.a.output.up" })] },
      ],
    };
    expect(write(c)).toBe(
      '(steps.a.output.n == 5)\n&& ((type(steps.s.output.name) == type("") && steps.s.output.name.startsWith("HQ-")) || (steps.a.output.up == true))',
    );
    expect(write({ match: "any", items: [] })).toBeUndefined();
  });

  it("reads back what it wrote, and only that", () => {
    const c: Condition = {
      match: "any",
      items: [
        row({ path: EV, guards: EVENT_GUARDS, nullTest: true, value: { kind: "text", text: 'a "quoted" \\ value\n' } }),
        row({ path: "steps.l.output.total", op: "at_most", value: { kind: "number", text: "-2.5e3" }, nullTest: true }),
        { match: "all", rows: [row({ op: "is_not" }), row({ op: "is_missing", value: null, path: "steps.s.output.tz", guards: [g("present", "steps.s.output.tz")] })] },
        row({ path: "steps.l.output.results", op: "is_empty", value: null }),
        row({ path: "steps.s.output.tz", op: "is_there", value: null, guards: [g("present", "steps.s.output.tz")], nullTest: true }),
      ],
    };
    const text = write(c)!;
    expect(read(text)).toEqual(c);
    for (const foreign of [
      'size(steps.list_devices.output.results.filter(d, d.status == "disconnected")) > 2',
      "steps.s.output.name == \"x\"", // no parentheses: not the builder's
      "(type(steps.s.output.name) == string && steps.s.output.name.contains(\"x\"))", // a type's name
      `${text} `,
      "(steps.a.output.n == 5) && (steps.a.output.m == 6)", // joined on one line
    ]) {
      expect(read(foreign)).toBeNull();
    }
  });

  it("keeps a formula with text JSON doesn't read a formula, and never fails on it (the review of revision 1)", () => {
    for (const foreign of [
      '(trigger.name == "\\x41")', // CEL's hexadecimal escape: a formula that runs, but not text the builder writes
      '(trigger.name == "\\101")',
      '(type(trigger.name) == type("") && trigger.name.startsWith("\\x41"))',
    ]) {
      expect(() => read(foreign)).not.toThrow();
      expect(read(foreign)).toBeNull();
    }
  });

  it("names the value it tests in \"is there\" and \"is missing\", and reads that value back (the review of revision 1)", () => {
    const events = [g("present", "trigger.events"), g("is_list", "trigger.events"), g("min_size", "trigger.events", 0)];
    const cases: [Row, string][] = [
      // A field always there in each item: the list's guards say only that an item is there, so the field is named.
      [
        row({ path: "trigger.events[0].name", op: "is_there", value: null, guards: [...events, g("is_map", "trigger.events[0]")] }),
        "(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0 && type(trigger.events[0]) == type({}) && has(trigger.events[0].name))",
      ],
      // The same, with the guards the scope gives a declared list's item's required field (Task 1 runs this formula).
      [
        row({ path: "trigger.olist[0].name", op: "is_there", value: null, guards: [g("present", "trigger.olist"), g("min_size", "trigger.olist", 0)] }),
        "(has(trigger.olist) && size(trigger.olist) > 0 && has(trigger.olist[0].name))",
      ],
      // An item: the size its guards test names it.
      [
        row({ path: "trigger.events[0]", op: "is_missing", value: null, guards: events }),
        "!(has(trigger.events) && type(trigger.events) == type([]) && size(trigger.events) > 0)",
      ],
      // A value its own guard names already.
      [row({ path: "trigger.events", op: "is_there", value: null, guards: [g("present", "trigger.events")] }), "(has(trigger.events))"],
      // A value that may be null, and is always there otherwise: its null test names it.
      [row({ path: "steps.l.output.total", op: "is_there", value: null, nullTest: true }), "(steps.l.output.total != null)"],
    ];
    for (const [r, cel] of cases) {
      expect(rowCel(r)).toBe(cel);
      const back = read(cel);
      expect(back?.items[0]).toMatchObject({ path: r.path, op: r.op });
      expect(write(back!)).toBe(cel);
    }
  });

  it("tells a list's first item being there from the list not being empty, each read back as itself (the review of revision 2)", () => {
    const item = row({ path: "trigger.labels[0]", op: "is_there", value: null, guards: [g("is_list", "trigger.labels"), g("min_size", "trigger.labels", 0)] });
    const list = row({ path: "trigger.labels", op: "is_not_empty", value: null });
    expect(rowCel(list)).toBe("(type(trigger.labels) == type([]) && size(trigger.labels) != 0)");
    expect(rowCel(item)).toBe("(type(trigger.labels) == type([]) && size(trigger.labels) > 0)");
    expect(read(rowCel(item))?.items[0]).toMatchObject({ path: "trigger.labels[0]", op: "is_there" });
    expect(read(rowCel(list))?.items[0]).toMatchObject({ path: "trigger.labels", op: "is_not_empty" });
  });

  it("reads every comparison back as the value, operator and literal it was written for (the review of revision 2)", () => {
    // The shapes of guards the scope gives: none, a field's own, a list's and its item's, an item's field below them.
    const X = "trigger.xs";
    const shapes: [string, Guard[]][] = [
      ["trigger.a", []],
      ["trigger.a", [g("present", "trigger.a")]],
      [X, []],
      [X, [g("present", X)]],
      [`${X}[0]`, [g("min_size", X, 0)]],
      [`${X}[0]`, [g("is_list", X), g("min_size", X, 0)]],
      [`${X}[2]`, [g("present", X), g("is_list", X), g("min_size", X, 2)]],
      [`${X}[0].f`, [g("is_list", X), g("min_size", X, 0)]],
      [`${X}[0].f`, [g("present", X), g("min_size", X, 0), g("is_map", `${X}[0]`)]],
      [`${X}[0].f`, [g("is_list", X), g("min_size", X, 0), g("is_map", `${X}[0]`), g("present", `${X}[0].f`)]],
    ];
    const ops = Object.keys(OP_WORDS) as Op[];
    const seen = new Map<string, string>();
    for (const [path, guards] of shapes) {
      for (const nullTest of [false, true]) {
        for (const op of ops) {
          for (const value of NO_VALUE.has(op) ? [null] : [{ kind: "text", text: "a" } as const, { kind: "number", text: "3" } as const]) {
            const cel = rowCel({ path, op, value, guards, nullTest });
            const said = `${path} ${op} ${JSON.stringify(value)}`;
            expect(read(cel)?.items[0], `${said} wrote ${cel}`).toMatchObject({ path, op, value });
            if (seen.has(cel) && seen.get(cel)!.split(" ").slice(0, 2).join(" ") !== `${path} ${op}`) throw new Error(`${said} and ${seen.get(cel)} both write ${cel}`);
            seen.set(cel, said);
          }
        }
      }
    }
  });

  it("offers \"is there\" and \"is missing\" only for a value that may be missing (the review of revision 1)", () => {
    expect(opsFor(["object"], null, false)).toEqual([]);
    expect(opsFor([], null, false)).not.toContain("is_there");
    expect(opsFor(["string", "integer"], null, false)).not.toContain("is_missing");
    expect(opsFor(["string", "integer"], null, true)).toContain("is_there");
  });

  it("offers the operators a value's type takes, never ordering a date and time", () => {
    expect(opsFor(["string"], null, false)).toEqual(["is", "is_not", "contains", "starts_with", "ends_with"]);
    expect(opsFor(["string"], "date-time", true)).toEqual(["is", "is_not", "is_there", "is_missing"]);
    expect(opsFor(["integer", "null"], null, true)).toEqual(["is", "is_not", "more", "less", "at_least", "at_most", "is_there", "is_missing"]);
    expect(opsFor(["boolean"], null, false)).toEqual(["is_true", "is_false"]);
    expect(opsFor(["array"], null, false)).toEqual(["is_empty", "is_not_empty"]);
    expect(opsFor(["object"], null, true)).toEqual(["is_there", "is_missing"]);
    expect(opsFor([], null, true)).toContain("more");
  });

  it("takes a number only as JSON writes one, finite, and whole within CEL's int; the loop's position whole", () => {
    expect(valueProblem({ kind: "number", text: "3" }, "steps.a.output.n")).toBeNull();
    expect(valueProblem({ kind: "number", text: "-0.5e3" }, "steps.a.output.n")).toBeNull();
    for (const bad of ["05", "5.", ".5", "1_000", "0x10", "abc", ""]) expect(valueProblem({ kind: "number", text: bad }, "x")).not.toBeNull();
    expect(valueProblem({ kind: "number", text: "1e400" }, "x")).toBe("This number is too large.");
    expect(valueProblem({ kind: "number", text: "9223372036854775808" }, "x")).toBe("This whole number is too large.");
    expect(valueProblem({ kind: "number", text: "1.5" }, "index")).toBe("The loop's position is a whole number.");
    expect(valueProblem({ kind: "text", text: "a\ud800b" }, "x")).not.toBeNull();
    expect(valueProblem({ kind: "text", text: "emoji 😀" }, "x")).toBeNull();
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/builder.test.ts`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  no tests`. The run can't import `./builder`: it doesn't exist yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/lib/builder.ts`:

````ts
// SPDX-License-Identifier: Apache-2.0
// The condition builder's formulas (4c-2b; the owner's rulings: per-comparison guards, "is there" and "is missing"
// defined, one level of groups; ledger rulings 119 and M65). A condition is comparisons, each a path the scope gives
// with the guards it needs (as data), joined by all or any, with groups one level deep. Written as CEL that is false,
// never an error, on any data: each comparison is its guards, its null test, a test of its value's type where the
// operator would fail on another, and the comparison. Read back only when it's what the builder wrote: the formula
// written again from what's read is the same text, or it stays a formula ("the builder opens only what it wrote").
import type { Guard } from "./data";

export type Op =
  | "is" | "is_not" | "contains" | "starts_with" | "ends_with" | "more" | "less" | "at_least" | "at_most"
  | "is_true" | "is_false" | "is_empty" | "is_not_empty" | "is_there" | "is_missing";  // prettier-ignore

export const OP_WORDS: Record<Op, string> = {
  is: "is", is_not: "is not", contains: "contains", starts_with: "starts with", ends_with: "ends with",
  more: "is more than", less: "is less than", at_least: "is at least", at_most: "is at most", is_true: "is true",
  is_false: "is false", is_empty: "is empty", is_not_empty: "is not empty", is_there: "is there", is_missing: "is missing",
};  // prettier-ignore

/** A value compared with: text, or a number as typed (checked: valueProblem). */
export type Literal = { kind: "text"; text: string } | { kind: "number"; text: string };

export interface Row {
  path: string;
  op: Op;
  value: Literal | null; // null for operators that take none
  guards: Guard[];
  nullTest: boolean; // "is there" includes `path != null` (the scope's null_test)
}

export interface Group {
  match: "all" | "any";
  rows: Row[];
}

export interface Condition {
  match: "all" | "any";
  items: (Row | Group)[];
}

export const isGroup = (x: Row | Group): x is Group => "rows" in x;

const TEXT_OPS: Op[] = ["contains", "starts_with", "ends_with"];
const NUMBER_OPS: Op[] = ["more", "less", "at_least", "at_most"];
export const NO_VALUE: ReadonlySet<Op> = new Set(["is_true", "is_false", "is_empty", "is_not_empty", "is_there", "is_missing"]);

/** The operators a value of these types takes (R6 §4.3): a date and time is compared as written, never ordered (its
 * text can't be ordered, and its parse fails on many values); "is there" only where something may be missing, so an
 * object that's always there takes none (the review of revision 1). */
export function opsFor(types: readonly string[], format: string | null, mayBeMissing: boolean): Op[] {
  const t = types.filter((x) => x !== "null");
  const presence: Op[] = mayBeMissing ? ["is_there", "is_missing"] : [];
  if (types.length === 0 || t.length > 1) {
    return ["is", "is_not", ...TEXT_OPS, ...NUMBER_OPS, "is_true", "is_false", ...presence];
  }
  switch (t[0]) {
    case "string":
      return format === "date-time" ? ["is", "is_not", ...presence] : ["is", "is_not", ...TEXT_OPS, ...presence];
    case "integer":
    case "number":
      return ["is", "is_not", ...NUMBER_OPS, ...presence];
    case "boolean":
      return ["is_true", "is_false", ...presence];
    case "array":
      return ["is_empty", "is_not_empty", ...presence];
    default:
      return presence; // an object, or what's only null
  }
}

/** Whether "is" and "is not" compare with a number: the value is only ever one. */
export const numeric = (types: readonly string[]): boolean => {
  const t = types.filter((x) => x !== "null");
  return t.length > 0 && t.every((x) => x === "integer" || x === "number");
};

const JSON_NUMBER = /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$/;
const INT64 = { min: -(2n ** 63n), max: 2n ** 63n - 1n };
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

/** Why a value can't be compared with, or null. A number is written as typed, JSON's way, finite and, whole, within
 * CEL's int; the loop's `index` takes whole numbers only (CEL types it int). Text with a lone surrogate isn't text CEL
 * reads. */
export function valueProblem(value: Literal, path: string): string | null {
  if (value.kind === "text") return LONE_SURROGATE.test(value.text) ? "This text holds a character that can't be written." : null;
  const t = value.text.trim();
  if (!JSON_NUMBER.test(t)) return "Write a number, like 3, -2 or 0.5.";
  if (!Number.isFinite(Number(t))) return "This number is too large.";
  const whole = !/[.eE]/.test(t);
  if (whole && (BigInt(t) < INT64.min || BigInt(t) > INT64.max)) return "This whole number is too large.";
  if (path === "index" && !whole) return "The loop's position is a whole number.";
  return null;
}

const literalCel = (v: Literal): string => (v.kind === "text" ? JSON.stringify(v.text) : v.text.trim());

/** A guard as CEL, a type tested by a value's type: a type's name fails every run (ledger M65). */
export function guardCel(g: Guard): string {
  switch (g.kind) {
    case "present":
      return `has(${g.path})`;
    case "not_null":
      return `${g.path} != null`;
    case "is_map":
      return `type(${g.path}) == type({})`;
    case "is_list":
      return `type(${g.path}) == type([])`;
    default:
      return `size(${g.path}) > ${g.size ?? 0}`;
  }
}

/** "is there" (ruling 119): its guards, and not null where the scope says. Empty when it always is. */
export const thereOf = (r: Pick<Row, "path" | "guards" | "nullTest">): string[] => [
  ...r.guards.map(guardCel),
  ...(r.nullTest ? [`${r.path} != null`] : []),
];

/** The test of a value's own presence: `has()` of a field, the size that holds an item; null for a root. */
function presenceOf(path: string): string | null {
  const item = /^(.*)\[(0|[1-9][0-9]*)\]$/.exec(path);
  if (item) return `size(${item[1]}) > ${item[2]}`;
  return path.includes(".") ? `has(${path})` : null;
}

/** "is there" as written: its tests end with one of the value itself, so the formula names the value it tests, even
 * where only an ancestor's guards decide it (an item's field that's always there; the review of revision 1). */
function presenceCel(r: Row): string {
  const there = thereOf(r);
  const own = r.nullTest ? `${r.path} != null` : presenceOf(r.path);
  return (own === null || there.at(-1) === own ? there : [...there, own]).join(" && ") || "true";
}

const NUMBER_TEST = (p: string) => `(type(${p}) == type(0) || type(${p}) == type(0.0))`;
const ORDER: Partial<Record<Op, string>> = { more: ">", less: "<", at_least: ">=", at_most: "<=" };
const METHOD: Partial<Record<Op, string>> = { contains: "contains", starts_with: "startsWith", ends_with: "endsWith" };

/** The comparison's own tests, after "is there". */
function testOf(r: Row): string[] {
  const p = r.path;
  const v = r.value ? literalCel(r.value) : "";
  switch (r.op) {
    case "is":
      return [`${p} == ${v}`];
    case "is_not":
      return [`${p} != ${v}`];
    case "contains":
    case "starts_with":
    case "ends_with":
      return [`type(${p}) == type("")`, `${p}.${METHOD[r.op]}(${v})`];
    case "more":
    case "less":
    case "at_least":
    case "at_most":
      return [NUMBER_TEST(p), `${p} ${ORDER[r.op]} ${v}`];
    case "is_true":
      return [`${p} == true`];
    case "is_false":
      return [`${p} == false`];
    case "is_empty":
      return [`type(${p}) == type([])`, `size(${p}) == 0`];
    case "is_not_empty": // `!= 0`: `size(x) > n` is an item being there, its presence's own test (the review of revision 2)
      return [`type(${p}) == type([])`, `size(${p}) != 0`];
    default:
      return [];
  }
}

/** One comparison as CEL, in parentheses: false whenever its data is missing, null or another shape. */
export function rowCel(r: Row): string {
  if (r.op === "is_missing") return `!(${presenceCel(r)})`;
  if (r.op === "is_there") return `(${presenceCel(r)})`;
  return `(${[...thereOf(r), ...testOf(r)].join(" && ")})`;
}

const JOIN = { all: "&&", any: "||" } as const;

/** The formula a condition writes, or undefined when it has no comparison. Each item on its own line. */
export function write(c: Condition): string | undefined {
  const items = c.items.filter((x) => !isGroup(x) || x.rows.length > 0);
  if (items.length === 0) return undefined;
  const text = (x: Row | Group) => (isGroup(x) ? `(${x.rows.map(rowCel).join(` ${JOIN[x.match]} `)})` : rowCel(x));
  return items.map(text).join(`\n${JOIN[c.match]} `);
}

// Reading back. A formula is split where the builder joins (outside parentheses and text), each comparison into its
// tests; what's read must be written again as the same text, or it isn't the builder's.

/** Splits `s` at each top-level `sep`, outside parentheses, brackets, braces and strings. */
function split(s: string, sep: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let start = 0;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]!;
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if ("([{".includes(ch)) depth++;
    else if (")]}".includes(ch)) depth--;
    else if (depth === 0 && s.startsWith(sep, i)) {
      out.push(s.slice(start, i));
      start = i + sep.length;
      i += sep.length - 1;
    }
  }
  out.push(s.slice(start));
  return out;
}

/** The text inside one pair of outer parentheses, or null. */
function inner(s: string, open = "("): string | null {
  if (!s.startsWith(open) || !s.endsWith(")")) return null;
  const body = s.slice(open.length, -1);
  return balanced(body) ? body : null;
}

function balanced(s: string): boolean {
  let depth = 0;
  let quote: string | null = null;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]!;
    if (quote) {
      if (ch === "\\") i++;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") quote = ch;
    else if (ch === "(") depth++;
    else if (ch === ")" && --depth < 0) return false;
  }
  return depth === 0;
}

const PATH = "([A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*|\\[(?:0|[1-9][0-9]*)\\])*)";
const GUARDS: [RegExp, (m: RegExpExecArray) => Guard][] = [
  [new RegExp(`^has\\(${PATH}\\)$`), (m) => ({ kind: "present", path: m[1]!, size: null })],
  [new RegExp(`^${PATH} != null$`), (m) => ({ kind: "not_null", path: m[1]!, size: null })],
  [new RegExp(`^type\\(${PATH}\\) == type\\(\\{\\}\\)$`), (m) => ({ kind: "is_map", path: m[1]!, size: null })],
  [new RegExp(`^type\\(${PATH}\\) == type\\(\\[\\]\\)$`), (m) => ({ kind: "is_list", path: m[1]!, size: null })],
  [new RegExp(`^size\\(${PATH}\\) > (0|[1-9][0-9]*)$`), (m) => ({ kind: "min_size", path: m[1]!, size: Number(m[2]) })],
];

const LIT = '("(?:[^"\\\\]|\\\\.)*"|-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?)';
/** A value as the builder writes it, or null: text CEL reads and JSON doesn't (`"\x41"`) isn't the builder's, and a
 * formula holding it stays a formula, never an error (the review of revision 1). */
function literalOf(text: string): Literal | null {
  if (!text.startsWith('"')) return { kind: "number", text };
  try {
    return { kind: "text", text: JSON.parse(text) as string };
  } catch {
    return null;
  }
}

/** The comparison a row's last tests make: its operator, path and value, and how many tests it took. */
function testFrom(tests: string[]): { op: Op; path: string; value: Literal | null; used: number } | null {
  const last = tests.at(-1) ?? "";
  const prev = tests.at(-2) ?? "";
  let m: RegExpExecArray | null;
  if ((m = new RegExp(`^${PATH} == (true|false)$`).exec(last))) return { op: m[2] === "true" ? "is_true" : "is_false", path: m[1]!, value: null, used: 1 };
  if ((m = new RegExp(`^${PATH} (==|!=) ${LIT}$`).exec(last))) {
    const value = literalOf(m[3]!);
    return value && { op: m[2] === "==" ? "is" : "is_not", path: m[1]!, value, used: 1 };
  }
  if ((m = new RegExp(`^${PATH}\\.(contains|startsWith|endsWith)\\(${LIT}\\)$`).exec(last)) && prev === `type(${m[1]}) == type("")`) {
    const op = m[2] === "contains" ? "contains" : m[2] === "startsWith" ? "starts_with" : "ends_with";
    const value = literalOf(m[3]!);
    return value && { op, path: m[1]!, value, used: 2 };
  }
  if ((m = new RegExp(`^${PATH} (>|<|>=|<=) ${LIT}$`).exec(last)) && prev === NUMBER_TEST(m[1]!)) {
    const op = (Object.entries(ORDER).find(([, s]) => s === m![2])?.[0] ?? "more") as Op;
    const value = literalOf(m[3]!);
    return value && { op, path: m[1]!, value, used: 2 };
  }
  if ((m = new RegExp(`^size\\(${PATH}\\) (==|!=) 0$`).exec(last)) && prev === `type(${m[1]}) == type([])`) {
    return { op: m[2] === "==" ? "is_empty" : "is_not_empty", path: m[1]!, value: null, used: 2 };
  }
  return null;
}

/** A row from its tests, the guards first: null when they aren't the builder's. */
function rowFrom(tests: string[], presence: "is_there" | "is_missing" | null): Row | null {
  let path: string | null = null;
  let op: Op;
  let value: Literal | null = null;
  let rest = tests;
  if (presence) {
    op = presence;
  } else {
    const t = testFrom(tests);
    if (!t) return null;
    ({ op, path, value } = t);
    rest = tests.slice(0, tests.length - t.used);
  }
  const guards: Guard[] = [];
  let nullTest = false;
  for (const text of rest) {
    const hit = GUARDS.map(([re, make]) => {
      const m = re.exec(text);
      return m ? make(m) : null;
    }).find((g) => g !== null);
    if (!hit) return null;
    // The last `path != null` is the null test of its own path, when it reads that path.
    if (hit.kind === "not_null" && (path === null ? text === rest.at(-1) : hit.path === path)) {
      nullTest = true;
      path ??= hit.path;
    } else guards.push(hit);
  }
  if (path === null) {
    // "is there" with no null test: the value its last test names, a field's `has()` or an item's size.
    const last = guards.at(-1);
    path = last?.kind === "present" ? last.path : last?.kind === "min_size" ? `${last.path}[${last.size}]` : null;
  }
  return path === null ? null : { path, op, value, guards, nullTest };
}

function itemFrom(text: string): Row | Group | null {
  if (text.startsWith("!(")) {
    const body = inner(text, "!(");
    return body === null ? null : rowFrom(body === "true" ? [] : split(body, " && "), "is_missing");
  }
  const body = inner(text);
  if (body === null) return null;
  const ors = split(body, " || ");
  const ands = split(body, " && ");
  // A group of one: its comparison, in parentheses of its own. Its match says nothing until a second one joins.
  if (ors.length === 1 && ands.length === 1 && (body.startsWith("(") || body.startsWith("!("))) {
    const only = itemFrom(body);
    if (only !== null && !isGroup(only)) return { match: "any", rows: [only] };
  }
  // A group is comparisons in parentheses, each itself in parentheses.
  for (const [parts, match] of [[ors, "any"], [ands, "all"]] as const) {
    if (parts.length > 1 && parts.every((p) => p.startsWith("(") || p.startsWith("!("))) {
      const rows = parts.map((p) => itemFrom(p));
      if (rows.every((r): r is Row => r !== null && !isGroup(r))) return { match, rows };
    }
  }
  return rowFrom(ands, null) ?? rowFrom(ands, "is_there");
}

/** The condition a formula is, when the builder wrote it (written again, it's the same text); null otherwise. */
export function read(formula: string): Condition | null {
  for (const match of ["all", "any"] as const) {
    const parts = split(formula, `\n${JOIN[match]} `);
    const items = parts.map(itemFrom);
    if (items.some((x) => x === null)) continue;
    const c: Condition = { match, items: items as (Row | Group)[] };
    if (write(c) === formula) return c;
  }
  return null;
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib/builder.test.ts`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  11 passed (11)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/builder.test.ts frontend/src/lib/builder.ts
git commit -m "feat(editor): the condition builder's formulas, written and read back (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Held text and conditions, Declassify's writers, the drawer's revision and steps

What the screens rest on, with no screen change: two kinds of edit the editor holds while they can't be written
(`template`: text and pills; `condition`: a condition being built; ruling 113), the writers of `settings.declassify`,
which fields take pills (`takesPills`, ruling 3) and a field's label by its pointer (`fieldLabel`), the mode switch's
names ("Text", "Builder") and a reason it can't switch, a group frame's `below`, and the drawer's saved revision and
steps (null in a version's view). The test harness gains them, and its fake API answers by query.

**Files:**
- Modify: `frontend/src/lib/config.test.ts`
- Modify: `frontend/src/lib/config.ts`
- Modify: `frontend/src/lib/schemaForm.test.ts`
- Modify: `frontend/src/lib/schemaForm.ts`
- Modify: `frontend/src/lib/unapplied.test.ts`
- Modify: `frontend/src/lib/unapplied.ts`
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldFrame.tsx`
- Modify: `frontend/src/routes/editor/drawer/Formula.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx`
- Modify: `frontend/src/routes/editor/drawer/context.ts`
- Modify: `frontend/src/routes/editor/drawer/harness.tsx`

**Interfaces:**
- Consumes: `Segments`, `valueOf` (Task 2); `Condition`, `isGroup`, `valueProblem`, `write` (Task 4).
- Produces: `UnappliedKind` adds `"template"` and `"condition"`; `Unapplied.segments?`, `Unapplied.condition?`,
  `Unapplied.literalOk?` (false: text alone is written as a template); `unappliedFile` writes each edit's `segments` or
  `condition` beside its text; `declassify(doc, site)`, `undeclassify(doc, index)` in `lib/config.ts`; `takesPills(f)`,
  `fieldLabel(type, pointer)` in `lib/schemaForm.ts`; `Drawer.revision: number | null`, `Drawer.steps: { id; key; title
  }[]`, `Drawer.openDeclassify?: () => void`; `ModeSwitch`'s `fixedName` and `fixedWhyNot`; `GroupFrame`'s `below`;
  `showFields` options `revision` and `steps`; `fakeApi` answers given the request's `URLSearchParams`.

- [ ] **Step 1: Write the failing tests**

**In** `frontend/src/lib/config.test.ts`, **replace**:

````ts
import { IF, SWITCH } from "../test/nodeTypes";
import {
  CEL_WORDS, admission, fixedOf, formula, formulaOf, freePort, isPlainRef, keyProblem, kindOf, parseJson, referenceText,
  renameEntry, renameKey, renamePort, rootOf, setAt, setConfig, setOptions, valueAt,
} from "./config";  // prettier-ignore
import type { GraphDoc } from "./workflows";
````

**with**:

````ts
import { IF, SWITCH } from "../test/nodeTypes";
import {
  CEL_WORDS, admission, declassify, fixedOf, formula, formulaOf, freePort, isPlainRef, keyProblem, kindOf, parseJson, referenceText,
  renameEntry, renameKey, renamePort, rootOf, setAt, setConfig, setOptions, undeclassify, valueAt,
} from "./config";  // prettier-ignore
import type { GraphDoc } from "./workflows";
````

**In** `frontend/src/lib/config.test.ts`, **replace**:

````ts
    expect(renameKey(doc, A, "route").mentions).toBe(2);
  });
});
````

**with**:

````ts
    expect(renameKey(doc, A, "route").mentions).toBe(2);
  });
});

describe("declassify entries (4c-2b)", () => {
  const doc = (declassify?: { node: string; field: string }[]) =>
    ({ graph_format: 1, nodes: [], settings: { input_schema: { type: "object" }, ...(declassify ? { declassify } : {}) } }) as GraphDoc;
  it("adds a decision once, and keeps the other settings", () => {
    const site = { node: "00000000-0000-4000-8000-000000000001", field: "/condition" };
    const once = declassify(doc(), site);
    expect(once.settings).toEqual({ input_schema: { type: "object" }, declassify: [site] });
    expect(declassify(once, { ...site, node: site.node.toUpperCase() })).toBe(once); // the same step, however spelt
  });
  it("removes an entry, and the list with its last", () => {
    const a = { node: "a", field: "/condition" };
    const b = { node: "b", field: "/items" };
    expect(undeclassify(doc([a, b]), 0).settings).toEqual({ input_schema: { type: "object" }, declassify: [b] });
    expect(undeclassify(doc([a]), 0).settings).toEqual({ input_schema: { type: "object" } });
    expect(undeclassify(doc([a]), 3)).toEqual(doc([a]));
  });
});
````

**In** `frontend/src/lib/schemaForm.test.ts`, **replace**:

````ts
import { DELAY, FILTER, IF, LOOP, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith } from "../test/nodeTypes";
import {
  canFixed, canFormula, emptyOf, entryOf, fieldsOf, itemOf, pointerOf, propertiesOf, startsAsFormula, tabsOf,
} from "./schemaForm";  // prettier-ignore

````

**with**:

````ts
import { DELAY, FILTER, IF, LOOP, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith } from "../test/nodeTypes";
import {
  canFixed, canFormula, emptyOf, entryOf, fieldLabel, fieldsOf, itemOf, pointerOf, propertiesOf, startsAsFormula, tabsOf,
  takesPills,
} from "./schemaForm";  // prettier-ignore

````

**In** `frontend/src/lib/schemaForm.test.ts`, **replace**:

````ts
  expect(marked({ patternProperties: { "^x-": { type: "string" } } }).holdsSensitive).toBe(false);
});
````

**with**:

````ts
  expect(marked({ patternProperties: { "^x-": { type: "string" } } }).holdsSensitive).toBe(false);
});

describe("4c-2b's field kinds", () => {
  const fields = (schema: Record<string, unknown>) => fieldsOf(typeWith({ type: "object", properties: schema }));
  it("takes text with data pills in a text field the engine lets template, never a secret, a choice or a formula", () => {
    const [text, secret, choice, cel, refs, plain] = fields({
      text: { type: "string" },
      secret: { type: "string", "x-sensitive": true },
      choice: { type: "string", enum: ["a", "b"] },
      cel: { type: "boolean", "x-widget": "cel" },
      refs: { type: "string", "x-dewpoint-kinds": ["ref", "template"] },
      plain: { type: "string", "x-dewpoint-kinds": ["literal"] },
    });
    expect([text, secret, choice, cel, refs, plain].map((f) => takesPills(f!))).toEqual([true, false, false, false, true, false]);
  });
  it("labels a field by its parts' labels", () => {
    expect(fieldLabel(SWITCH, "/cases/1/when")).toBe("Cases, item 2 › Condition");
    expect(fieldLabel(IF, "/condition")).toBe("Condition");
    expect(fieldLabel(IF, "/nope")).toBe("/nope");
  });
});
````

**In** `frontend/src/lib/unapplied.test.ts`, **replace**:

````ts
  expect(result).toEqual({ problem: "A formula can be at most 16,384 characters: this one has 16,392, so it isn't saved." });
});
````

**with**:

````ts
  expect(result).toEqual({ problem: "A formula can be at most 16,384 characters: this one has 16,392, so it isn't saved." });
});

it("applies held text and pills as a template, and a literal's text as a literal (4c-2b)", () => {
  const doc = fetch({ name: literal("hi") });
  const segments = { texts: ["AP ", ""], pills: [{ ref: "run.now" }] };
  const u = held(doc, "template", "/name", ["name"], "AP {run.now}", { segments, literal: true });
  expect(applied(applyUnapplied(doc, u, TRANSFORM)).doc.nodes![0]!.config).toEqual({
    name: { $value: { kind: "template", parts: [{ text: "AP " }, { ref: "run.now" }] } },
  });
  const plain = held(doc, "template", "/name", ["name"], "hey", { segments: { texts: ["hey"], pills: [] }, literal: true });
  expect(applied(applyUnapplied(doc, plain, TRANSFORM)).doc.nodes![0]!.config).toEqual({ name: literal("hey") });
});

it("applies a held condition once each comparison can be written (4c-2b)", () => {
  const doc = fetch({});
  const row = { path: "steps.a.output.n", op: "more" as const, value: { kind: "number" as const, text: "3x" }, guards: [], nullTest: false };
  const half = held(doc, "condition", "/when", ["when"], "", { condition: { match: "all", items: [row] } });
  expect(applyUnapplied(doc, half, TRANSFORM)).toEqual({ problem: "Write a number, like 3, -2 or 0.5." });
  const done = held(doc, "condition", "/when", ["when"], "", { condition: { match: "all", items: [{ ...row, value: { kind: "number", text: "3" } }] } });
  const n = "steps.a.output.n";
  expect(applied(applyUnapplied(doc, done, TRANSFORM)).doc.nodes![0]!.config).toEqual({
    when: formula(`((type(${n}) == type(0) || type(${n}) == type(0.0)) && ${n} > 3)`),
  });
});

it("applies held text as it would have been written: alone, a template where the field takes no fixed value (the review of revision 1)", () => {
  const doc = fetch({});
  const u = held(doc, "template", "/name", ["name"], "hello", { segments: { texts: ["hello"], pills: [] }, literalOk: false });
  expect(applied(applyUnapplied(doc, u, TRANSFORM)).doc.nodes![0]!.config).toEqual({
    name: { $value: { kind: "template", parts: [{ text: "hello" }] } },
  });
});

it("writes held text and pills, and a condition being built, whole into the recovery file (the review of revision 1)", () => {
  const doc = fetch({});
  const segments = { texts: ["at ", ""], pills: [{ ref: "trigger.site", default: "HQ" }] };
  const text = held(doc, "template", "/name", ["name"], "at {trigger.site}", { label: "Name", why: "Not written.", segments });
  const row = { path: "steps.a.output.n", op: "more" as const, value: { kind: "number" as const, text: "3x" }, guards: [], nullTest: false };
  const condition = { match: "all" as const, items: [row] };
  const built = held(doc, "condition", "/when", ["when"], "", { label: "When", why: "Write a number, like 3, -2 or 0.5.", condition });
  expect(unappliedFile([text, built], () => "fetch").edits).toEqual([
    { step: "fetch", field: "Name", at: "/name", text: "at {trigger.site}", why: "Not written.", segments },
    { step: "fetch", field: "When", at: "/when", text: "", why: "Write a number, like 3, -2 or 0.5.", condition },
  ]);
});
````

**In** `frontend/src/routes/editor/drawer/harness.tsx`, **replace**:

````tsx
  editable?: boolean;
  routed?: boolean; // inside a router: a link to another page needs one
}

````

**with**:

````tsx
  editable?: boolean;
  routed?: boolean; // inside a router: a link to another page needs one
  revision?: number | null; // the saved draft's revision: data is asked of it
  steps?: { id: string; key: string; title: string | null }[]; // the draft's steps, for the data tree's groups
}

````

**In** `frontend/src/routes/editor/drawer/harness.tsx`, **replace**:

````tsx
    problems: options.problems ?? [],
    expressions: options.expressions ?? [],
    set: (path, value, mark) => {
      edits.push({ path, value, mark });
````

**with**:

````tsx
    problems: options.problems ?? [],
    expressions: options.expressions ?? [],
    revision: options.revision === undefined ? 1 : options.revision,
    steps: options.steps ?? [{ id: NODE_ID, key: "step", title: type.title }],
    set: (path, value, mark) => {
      edits.push({ path, value, mark });
````

**In** `frontend/src/routes/editor/drawer/harness.tsx`, **replace**:

````tsx
/** The API's answers, by "METHOD /path" (the path decoded); anything else is a 404, never the network. An answer may
 * be a promise the test settles. Each request is kept. */
export function fakeApi(answers: Record<string, () => Response | Promise<Response>>) {
  const sent: { method: string; path: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
````

**with**:

````tsx
/** The API's answers, by "METHOD /path" (the path decoded); anything else is a 404, never the network. An answer may
 * be a promise the test settles. Each request is kept. */
export function fakeApi(answers: Record<string, (query: URLSearchParams) => Response | Promise<Response>>) {
  const sent: { method: string; path: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
````

**In** `frontend/src/routes/editor/drawer/harness.tsx`, **replace**:

````tsx
    sent.push({ method: request.method, path, body: text ? (JSON.parse(text) as unknown) : null });
    const answer = answers[`${request.method} ${path}`];
    return answer ? answer() : json({ error: "not_found" }, 404);
  });
  return sent;
````

**with**:

````tsx
    sent.push({ method: request.method, path, body: text ? (JSON.parse(text) as unknown) : null });
    const answer = answers[`${request.method} ${path}`];
    return answer ? answer(new URL(request.url).searchParams) : json({ error: "not_found" }, 404);
  });
  return sent;
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib src/routes/editor`

Expected: FAIL: `Test Files  3 failed | 30 passed (33)`, `Tests  8 failed | 417 passed (425)`. The failing tests are
this task's new and changed ones: `adds a decision once, and keeps the other settings`, `removes an entry, and the list
with its last`, `takes text with data pills in a text field the engine lets template, never a secret, a choice or a
formula`, `labels a field by its parts' labels`, `applies held text and pills as a template, and a literal's text as a
literal (4c-2b)`, `applies a held condition once each comparison can be written (4c-2b)`, `applies held text as it would
have been written: alone, a template where the field takes no fixed value (the review of revision 1)`, `writes held text
and pills, and a condition being built, whole into the recovery file (the review of revision 1)`.

- [ ] **Step 3: Write the code**

**In** `frontend/src/lib/config.ts`, **replace**:

````ts
  return { doc: { ...doc, nodes, ...(settings ? { settings } : {}) }, mentions };
}
````

**with**:

````ts
  return { doc: { ...doc, nodes, ...(settings ? { settings } : {}) }, mentions };
}

/** The draft with a decision declassified (4c-2b): its entry added to `settings.declassify`, once. */
export function declassify(doc: GraphDoc, site: { node: string; field: string }): GraphDoc {
  const entries = doc.settings?.declassify ?? [];
  if (entries.some((e) => sameId(e.node, site.node) && e.field === site.field)) return doc;
  return { ...doc, settings: { ...doc.settings, declassify: [...entries, { node: site.node, field: site.field }] } };
}

/** The draft without its `index`th declassify entry; with none left, without the list. */
export function undeclassify(doc: GraphDoc, index: number): GraphDoc {
  const entries = doc.settings?.declassify ?? [];
  if (index < 0 || index >= entries.length) return doc;
  const kept = entries.filter((_, i) => i !== index);
  const rest = Object.fromEntries(Object.entries(doc.settings ?? {}).filter(([k]) => k !== "declassify"));
  return { ...doc, settings: kept.length > 0 ? { ...rest, declassify: kept } : rest };
}
````

**In** `frontend/src/lib/schemaForm.ts`, **replace**:

````ts
export const canFixed = (f: FieldSpec): boolean => !f.sensitive && (f.kinds === null || f.kinds.includes("literal"));

/** Where it takes a formula: no literal-only marker on the path or inside (value.literal_only), `cel` among its kinds. */
export const canFormula = (f: FieldSpec): boolean =>
````

**with**:

````ts
export const canFixed = (f: FieldSpec): boolean => !f.sensitive && (f.kinds === null || f.kinds.includes("literal"));

/** Where text with data pills is its fixed value (4c-2b): text the engine takes as a template, never a sensitive
 * field's (a secret is never typed, M25), a port's name or one written only as a literal. */
export const takesPills = (f: FieldSpec): boolean =>
  (f.widget === "text" || f.widget === "datetime") && !f.sensitive && !f.port && !f.literalOnly &&
  !f.holdsLiteral && (f.kinds === null || f.kinds.includes("template"));

/** Where it takes a formula: no literal-only marker on the path or inside (value.literal_only), `cel` among its kinds. */
export const canFormula = (f: FieldSpec): boolean =>
````

**In** `frontend/src/lib/schemaForm.ts`, **replace**:

````ts
 * entry, a blank that keeps its place. */
export const emptyOf = (f: FieldSpec): unknown => (f.entry ? (BLANK_IS_TEXT.has(f.widget) ? "" : null) : undefined);
````

**with**:

````ts
 * entry, a blank that keeps its place. */
export const emptyOf = (f: FieldSpec): unknown => (f.entry ? (BLANK_IS_TEXT.has(f.widget) ? "" : null) : undefined);

/** A field's label by its pointer in the type's config, its parts' labels joined: "Cases, item 2 › Condition". The
 * pointer itself when the schema doesn't hold it. */
export function fieldLabel(type: NodeType, pointer: string): string {
  const parts = pointer.split("/").slice(1).map((s) => s.replace(/~1/g, "/").replace(/~0/g, "~"));
  let fields = fieldsOf(type);
  let spec: FieldSpec | undefined;
  const labels: string[] = [];
  for (const name of parts) {
    if (spec?.base === "list" && /^(0|[1-9][0-9]*)$/.test(name)) {
      spec = itemOf(spec, Number(name));
      labels[labels.length - 1] = spec.label; // "Cases, item 2"
    } else {
      spec = fields.find((f) => f.name === name) ?? (spec?.base === "map" ? entryOf(spec, name) : undefined);
      if (!spec) return pointer;
      labels.push(spec.label);
    }
    fields = propertiesOf(spec);
  }
  return labels.length > 0 ? labels.join(" › ") : pointer;
}
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
} from "./config";  // prettier-ignore
import { findNode, idKey, portOf, sameId } from "./graph";
import { isObject, type Path } from "./schemaForm";
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";
````

**with**:

````ts
} from "./config";  // prettier-ignore
import { findNode, idKey, portOf, sameId } from "./graph";
import { isGroup, valueProblem, write, type Condition } from "./builder";
import { valueOf, type Segments } from "./pills";
import { isObject, type Path } from "./schemaForm";
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts

export type UnappliedKind = "text" | "json" | "number" | "formula" | "port" | "name" | "key" | "limit";

export interface Unapplied {
````

**with**:

````ts

export type UnappliedKind =
  | "text" | "template" | "condition" | "json" | "number" | "formula" | "port" | "name" | "key" | "limit";  // prettier-ignore

export interface Unapplied {
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
  entry?: boolean; // emptied, a list's item or a map's entry blanks to null rather than going
  literal?: boolean; // its value is a `literal` envelope's payload, written back as one (ruling 15)
  whole?: boolean; // a number: whole
  from?: string; // a map entry's name in the draft
````

**with**:

````ts
  entry?: boolean; // emptied, a list's item or a map's entry blanks to null rather than going
  literal?: boolean; // its value is a `literal` envelope's payload, written back as one (ruling 15)
  literalOk?: boolean; // false: text alone is a template of one text part, where the field takes no fixed value (4c-2b)
  whole?: boolean; // a number: whole
  from?: string; // a map entry's name in the draft
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
}

/** What a control supplies; the editor adds its step, its kind, where it goes and what it was typed over. */
````

**with**:

````ts
  segments?: Segments; // text and pills as typed: `text` says them in braces (4c-2b)
  condition?: Condition; // a condition as built: `text` is the formula it writes so far (4c-2b)
}

/** What a control supplies; the editor adds its step, its kind, where it goes and what it was typed over. */
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
    case "text": // emptied, a property goes, and a list's or a map's text blanks to ""
      return quiet(setConfig(doc, u.node, u.path, u.text === "" ? (u.entry ? "" : undefined) : written(u.text, u), type));
    case "json": {
      const parsed = parseJson(u.text);
````

**with**:

````ts
    case "text": // emptied, a property goes, and a list's or a map's text blanks to ""
      return quiet(setConfig(doc, u.node, u.path, u.text === "" ? (u.entry ? "" : undefined) : written(u.text, u), type));
    case "template": // text and pills, as typed: a literal's text written back as one
      return quiet(setConfig(doc, u.node, u.path, u.segments ? (valueOf(u.segments, u.literal ?? false, u.literalOk ?? true) ?? (u.entry ? "" : undefined)) : undefined, type));
    case "condition": {
      // Written only once each comparison can be: a number half typed stays held, with why.
      if (!u.condition) return { problem: "Nothing was built." };
      const rows = u.condition.items.flatMap((x) => (isGroup(x) ? x.rows : [x]));
      const problem = rows.map((r) => (r.value === null ? null : valueProblem(r.value, r.path))).find((p) => p !== null);
      if (problem) return { problem };
      const text = write(u.condition);
      return quiet(setConfig(doc, u.node, u.path, text === undefined ? written(undefined, u) : formula(text), type));
    }
    case "json": {
      const parsed = parseJson(u.text);
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
}

/** Edits not applied, as a recovery file of their own (ruling 18): what was typed, and where. Never written into the
 * graph to keep it: the graph is what runs. */
export function unappliedFile(edits: Unapplied[], keyOf: (node: string) => string) {
  return {
````

**with**:

````ts
}

/** Edits not applied, as a recovery file of their own (ruling 18): what was typed, and where, whole: text and pills
 * with their defaults, and a condition as built, beside the text that says them (the review of revision 1). Never
 * written into the graph to keep it: the graph is what runs. */
export function unappliedFile(edits: Unapplied[], keyOf: (node: string) => string) {
  return {
````

**In** `frontend/src/lib/unapplied.ts`, **replace**:

````ts
    format: "dewpoint.unapplied-edits",
    edits: edits.map((u) => ({ step: keyOf(u.node), field: u.label, at: u.pointer, text: u.text, why: u.why })),
  };
}
````

**with**:

````ts
    format: "dewpoint.unapplied-edits",
    edits: edits.map((u) => ({
      step: keyOf(u.node), field: u.label, at: u.pointer, text: u.text, why: u.why,
      ...(u.segments ? { segments: u.segments } : {}),
      ...(u.condition ? { condition: u.condition } : {}),
    })),
  };  // prettier-ignore
}
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
            tenantId={tenantId}
            workflowId={workflow.id}
            ports={portMap.get(idKey(open.id)) ?? []}
            problems={
````

**with**:

````tsx
            tenantId={tenantId}
            workflowId={workflow.id}
            revision={viewing ? null : sync.revision}
            steps={nodesOf(shownDoc).map((n) => ({ id: n.id, key: n.key, title: typeMap.get(n.type)?.title ?? null }))}
            ports={portMap.get(idKey(open.id)) ?? []}
            problems={
````

**In** `frontend/src/routes/editor/drawer/FieldFrame.tsx`, **replace**:

````tsx
}

export function GroupFrame({ label, required, hint, local, problems, actions, children }: Frame & { children: ReactNode }) {
  const id = useId();
  return (
````

**with**:

````tsx
}

export function GroupFrame({ label, required, hint, local, problems, actions, below, children }: Frame & {
  below?: ReactNode;
  children: ReactNode;
}) {  // prettier-ignore
  const id = useId();
  return (
````

**In** `frontend/src/routes/editor/drawer/FieldFrame.tsx`, **replace**:

````tsx
      <Notes id={id} hint={hint} local={local} problems={problems} />
      <div className="flex min-w-0 flex-col gap-4 pl-3">{children}</div>
    </fieldset>
  );
````

**with**:

````tsx
      <Notes id={id} hint={hint} local={local} problems={problems} />
      <div className="flex min-w-0 flex-col gap-4 pl-3">{children}</div>
      {below}
    </fieldset>
  );
````

**In** `frontend/src/routes/editor/drawer/Formula.tsx`, **replace**:

````tsx
  !x ? null : x.mode === "local" ? "Runs inline" : `Runs as a separate step: ${x.reason ?? "no reason given"}`;

export function ModeSwitch({ label, mode, disabled, onChange }: {
  label: string; mode: Mode; disabled: boolean; onChange: (mode: Mode) => void;
}) {  // prettier-ignore
  return (
````

**with**:

````tsx
  !x ? null : x.mode === "local" ? "Runs inline" : `Runs as a separate step: ${x.reason ?? "no reason given"}`;

export function ModeSwitch({ label, mode, disabled, onChange, fixedName = "Fixed", fixedWhyNot }: {
  label: string; mode: Mode; disabled: boolean; onChange: (mode: Mode) => void; fixedName?: string;
  fixedWhyNot?: { id: string } | null; // the fixed mode can't take this value: its button says why, described by it
}) {  // prettier-ignore
  return (
````

**In** `frontend/src/routes/editor/drawer/Formula.tsx`, **replace**:

````tsx
          type="button"
          aria-pressed={mode === m}
          disabled={disabled}
          onClick={() => {
            if (mode !== m) onChange(m);
````

**with**:

````tsx
          type="button"
          aria-pressed={mode === m}
          disabled={disabled || (m === "fixed" && !!fixedWhyNot)}
          aria-describedby={m === "fixed" && fixedWhyNot ? fixedWhyNot.id : undefined}
          onClick={() => {
            if (mode !== m) onChange(m);
````

**In** `frontend/src/routes/editor/drawer/Formula.tsx`, **replace**:

````tsx
          className={`min-h-8 px-3 text-small disabled:bg-disabled-bg disabled:text-muted ${mode === m ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink enabled:hover:bg-surface-hover"}`}
        >
          {m === "fixed" ? "Fixed" : "Formula"}
        </button>
      ))}
````

**with**:

````tsx
          className={`min-h-8 px-3 text-small disabled:bg-disabled-bg disabled:text-muted ${mode === m ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink enabled:hover:bg-surface-hover"}`}
        >
          {m === "fixed" ? fixedName : "Formula"}
        </button>
      ))}
````

**In** `frontend/src/routes/editor/drawer/StepDrawer.tsx`, **replace**:

````tsx

export function StepDrawer({
  node, type, tenantId, workflowId, ports, problems, expressions, editable, adds, actions, note, focusField,
  onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
}: {
````

**with**:

````tsx

export function StepDrawer({
  node, type, tenantId, workflowId, revision, steps, openDeclassify, ports, problems, expressions, editable, adds, actions, note, focusField,
  onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
}: {
````

**In** `frontend/src/routes/editor/drawer/StepDrawer.tsx`, **replace**:

````tsx
  node: GraphNode; type: NodeType | undefined; tenantId: string; workflowId: string; ports: string[];
  problems: Diagnostic[] | null; expressions: Expression[]; editable: boolean; adds: { label: string; action: ItemAction }[];
  actions: DrawerActions; note: string | null; focusField: { pointer: string; kind?: UnappliedKind; n: number } | null; onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void;
````

**with**:

````tsx
  node: GraphNode; type: NodeType | undefined; tenantId: string; workflowId: string; revision: number | null;
  steps: { id: string; key: string; title: string | null }[]; openDeclassify?: () => void; ports: string[];
  problems: Diagnostic[] | null; expressions: Expression[]; editable: boolean; adds: { label: string; action: ItemAction }[];
  actions: DrawerActions; note: string | null; focusField: { pointer: string; kind?: UnappliedKind; n: number } | null; onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void;
````

**In** `frontend/src/routes/editor/drawer/StepDrawer.tsx`, **replace**:

````tsx
  }, []);
  const unexplained = expressions.filter((x) => !explained.has(x.field));
  const drawer = { ...actions, node, type, editable, tenantId, workflowId, problems: mine, expressions, explains };
  return (
    <DrawerContext.Provider value={drawer}>
````

**with**:

````tsx
  }, []);
  const unexplained = expressions.filter((x) => !explained.has(x.field));
  const drawer = { ...actions, node, type, editable, tenantId, workflowId, revision, steps, openDeclassify, problems: mine, expressions, explains };
  return (
    <DrawerContext.Provider value={drawer}>
````

**In** `frontend/src/routes/editor/drawer/context.ts`, **replace**:

````ts
  workflowId: string;
  problems: Diagnostic[]; // the step's, from a current check
  expressions: Expression[]; // how its formulas run
  /** A field that says how its formula runs, while it's shown: the drawer's own list leaves it out (the owner's
````

**with**:

````ts
  workflowId: string;
  problems: Diagnostic[]; // the step's, from a current check
  /** The saved draft's revision, which the data a field reads is asked of; null in a version's view, which has none
   * (4c-2b). */
  revision: number | null;
  /** The draft's steps, by key, with their type's title: what the data a field reads is grouped by (4c-2b). */
  steps: { id: string; key: string; title: string | null }[];
  /** Opens the workflow's Declassify list (4c-2b); absent where it can't be (a version's view). */
  openDeclassify?: () => void;
  expressions: Expression[]; // how its formulas run
  /** A field that says how its formula runs, while it's shown: the drawer's own list leaves it out (the owner's
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/lib src/routes/editor`

Expected: PASS: `Test Files  33 passed (33)`, `Tests  425 passed (425)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/config.test.ts frontend/src/lib/config.ts frontend/src/lib/schemaForm.test.ts frontend/src/lib/schemaForm.ts frontend/src/lib/unapplied.test.ts frontend/src/lib/unapplied.ts frontend/src/routes/editor/Editor.tsx frontend/src/routes/editor/drawer/FieldFrame.tsx frontend/src/routes/editor/drawer/Formula.tsx frontend/src/routes/editor/drawer/StepDrawer.tsx frontend/src/routes/editor/drawer/context.ts frontend/src/routes/editor/drawer/harness.tsx
git commit -m "feat(editor): held text and conditions, Declassify's writers, the drawer's saved revision (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Milestone 1's checks.** The whole unit suite, typecheck and lint; then append to the ledger
  `### 4c-2b, milestone 1 (<date>)`: Tasks 1–5's commits, the suite's count as run, and each mid-slice ruling (M66
  onward) or none. Commit it (`docs(editor-4): 4c-2b milestone 1`). No pause: Milestone 2 follows.

---

# Milestone 2 — pills, the tree, a pill's details

### Task 6: The data tree (`drawer/DataTree.tsx`)

The data a field can read, to insert (ruling 8): an ARIA tree in the drawer's flow (ruling 2), grouped by source, each
value with its tags and type, children loaded when opened, a search, the typed path for a trigger whose input isn't
declared, and what can't be inserted shown disabled with why (in a condition, an object that's always there opens
instead). An answer about a newer revision isn't shown, at the top or under an opened value: the tree says why.

**Files:**
- Create: `frontend/src/routes/editor/drawer/DataTree.test.tsx`
- Create: `frontend/src/routes/editor/drawer/DataTree.tsx`

**Interfaces:**
- Consumes: `scopeQuery`, `groupOf`, `tagsOf`, `typeWords`, `ScopeEntry`, `Where`, `DraftMoved` (Task 3); `opsFor` (Task
  4); `parsePath` (Task 2); `Drawer.revision`, `Drawer.steps` (Task 5).
- Produces: `Purpose = "text" | "condition"`; `refusal(entry, purpose)`; `DataTree({ field, purpose, onPick, onClose
  })`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/routes/editor/drawer/DataTree.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ScopeEntry } from "../../../lib/data";
import { typeWith } from "../../../test/nodeTypes";
import { DataTree } from "./DataTree";
import { fakeApi, json, NODE_ID, showFields } from "./harness";

const NOTE = typeWith({ type: "object", properties: { message: { type: "string" } } }, { ref: "acme.note@1", type: "acme.note", title: "Post a note" });
const SITE = "00000000-0000-4000-8000-000000000002";
const steps = [
  { id: NODE_ID, key: "step", title: "Post a note" },
  { id: SITE, key: "list", title: "List devices" },
];

const entry = (path: string, over: Partial<ScopeEntry> = {}): ScopeEntry => ({
  children: false, format: null, formula: { guards: [], null_test: false, sensitive: false }, missing: false,
  name: path.split(".").at(-1)!, nameable: true, nullable: false, parent: null, path, problem: null, root: "steps",
  sensitive: false, step: SITE, types: ["string"], ...over,
});  // prettier-ignore

const OUT = "steps.list.output";
const ENTRIES = [
  entry("trigger", { root: "trigger", step: null, types: ["object"], sensitive: true }), // undeclared: nothing to browse
  entry(OUT, { name: "output", types: ["object"], children: true }),
  entry(`${OUT}.results`, { parent: OUT, types: ["array"], children: true }),
  entry(`${OUT}.results[0]`, { parent: `${OUT}.results`, name: "[0]", types: ["string"], missing: true }), // text: an object can't go into text
  entry(`${OUT}.total`, { parent: OUT, types: ["integer", "null"], nullable: true }),
  entry(`${OUT}.dash-key`, { parent: OUT, nameable: false }),
  entry("run.now", { root: "run", step: null, name: "now", format: "date-time" }),
];

function answer(entries: ScopeEntry[], more = false) {
  return json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries, more, problem: null });
}

function serve(over: Record<string, (q: URLSearchParams) => Response> = {}) {
  return fakeApi({
    "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
      const under = q.get("under");
      const find = q.get("find");
      const at = q.get("at");
      if (at !== null) {
        return at === "trigger.events[0].ap"
          ? answer([entry(at, { root: "trigger", step: null, types: [], missing: true, sensitive: true })])
          : json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: [], more: false, problem: { code: "ref.unknown_field", severity: "error", message: "No such field.", fix: null, node: NODE_ID, field: "/message" } });
      }
      if (under !== null) return answer(ENTRIES.filter((e) => e.parent === under));
      if (find !== null) return answer(ENTRIES.filter((e) => e.name.includes(find)));
      return answer(ENTRIES.filter((e) => e.parent === null || e.parent === OUT));
    },
    ...over,
  });
}

afterEach(() => vi.restoreAllMocks());

function tree(onPick = vi.fn(), onClose = vi.fn(), purpose: "text" | "condition" = "text") {
  showFields(NOTE, { steps }, <DataTree field="/message" purpose={purpose} onPick={onPick} onClose={onClose} />);
  return { onPick, onClose };
}

describe("the data tree", () => {
  it("groups the data by where it comes from, each value with its tags and type", async () => {
    serve();
    tree();
    const t = await screen.findByRole("tree", { name: "Data available here" });
    const groups = within(t).getAllByRole("treeitem").filter((g) => g.getAttribute("aria-level") === "1");
    expect(groups.map((g) => g.firstChild?.textContent)).toEqual(["Trigger", "list · List devices", "This run"]);
    expect(within(t).getByText("total").closest("li")?.textContent).toContain("may be null");
    expect(within(t).getByText("total").closest("li")?.textContent).toContain("whole number");
  });

  it("moves with the arrows, opens a value's children with →, and inserts with Enter", async () => {
    serve();
    const { onPick } = tree();
    await screen.findByRole("tree");
    await userEvent.keyboard("{ArrowDown}"); // from the search, into the tree
    expect(document.activeElement?.textContent?.startsWith("Trigger")).toBe(true);
    await userEvent.keyboard("{ArrowDown}{ArrowDown}{ArrowDown}"); // the trigger's path, list, results
    expect((document.activeElement as HTMLElement).dataset.path).toBe(`${OUT}.results`);
    await userEvent.keyboard("{ArrowRight}");
    await screen.findByText("[0]");
    await userEvent.keyboard("{ArrowRight}");
    expect((document.activeElement as HTMLElement).dataset.path).toBe(`${OUT}.results[0]`);
    await userEvent.keyboard("{Enter}");
    expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ path: `${OUT}.results[0]` }));
  });

  it("opens an object that's always there in a condition, but never picks it: it has nothing to compare (the review of revision 1)", async () => {
    const SITE_OBJ = `${OUT}.site`;
    serve({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) =>
        q.get("under") === SITE_OBJ
          ? answer([entry(`${SITE_OBJ}.name`, { parent: SITE_OBJ })])
          : answer([entry(OUT, { name: "output", types: ["object"], children: true }), entry(SITE_OBJ, { parent: OUT, types: ["object"], children: true })]),
    });
    const { onPick } = tree(vi.fn(), vi.fn(), "condition");
    const row = (await screen.findByText("site")).closest("li")!;
    expect(row.getAttribute("aria-disabled")).toBe("true");
    expect(row.textContent).toContain("It's always there, so there's nothing to compare: open it and pick one of its values.");
    await userEvent.click(row);
    expect(onPick).not.toHaveBeenCalled();
    expect(row.getAttribute("aria-expanded")).toBe("true");
  });

  it("says so when the draft was saved again while its data was asked for, and shows none of it (the review of revision 1)", async () => {
    serve({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
        json({ draft_revision: 2, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: ENTRIES, more: false, problem: null }),
    });
    tree();
    expect(await screen.findByText("The draft was saved again while its data was asked for. Close this and open it again.")).toBeTruthy();
    expect(screen.queryByText("total")).toBeNull();
  });

  it("says so when an opened value's answer is about a newer revision, and shows none of it (the review of revision 2)", async () => {
    serve({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
        const under = q.get("under");
        if (under === null) return answer(ENTRIES.filter((e) => e.parent === null || e.parent === OUT));
        return json({ draft_revision: 2, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: ENTRIES.filter((e) => e.parent === under), more: false, problem: null });
      },
    });
    tree();
    const results = (await screen.findByText("results")).closest("li")!;
    await userEvent.click(results); // a list can't go into text: it opens
    expect(await within(results).findByText("The draft was saved again while its data was asked for. Close this and open it again.")).toBeTruthy();
    expect(within(results).queryByText("[0]")).toBeNull();
  });

  it("shows a key a reference can't name, disabled, and never inserts it", async () => {
    serve();
    const { onPick } = tree();
    const row = (await screen.findByText("dash-key")).closest("li")!;
    expect(row.getAttribute("aria-disabled")).toBe("true");
    expect(row.textContent).toContain("A reference can't name this key.");
    await userEvent.click(row);
    expect(onPick).not.toHaveBeenCalled();
  });

  it("finds values by name", async () => {
    const sent = serve();
    tree();
    await userEvent.type(await screen.findByRole("searchbox", { name: "Find data" }), "tot");
    await waitFor(() => expect(screen.queryByText("run")).toBeNull());
    expect(screen.getByText("total")).toBeTruthy();
    expect(sent.some((r) => r.path.endsWith("/draft/scope"))).toBe(true);
  });

  it("takes a typed path in a trigger whose input isn't declared, once the server finds it", async () => {
    serve();
    const { onPick } = tree();
    const path = await screen.findByRole("textbox", { name: "A path in the trigger" });
    await userEvent.clear(path);
    await userEvent.type(path, "trigger.nope");
    await userEvent.click(screen.getByRole("button", { name: "Insert" }));
    expect(await screen.findByText("No such field.")).toBeTruthy();
    await userEvent.clear(path);
    await userEvent.type(path, "trigger.events[[0].ap"); // "[[" types "[" (user-event's keys)
    await userEvent.click(screen.getByRole("button", { name: "Insert" }));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(expect.objectContaining({ path: "trigger.events[0].ap" })));
  });

  it("says why there's no data when the saved draft can't give any", async () => {
    serve({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
        json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "unavailable", reason: "This step isn't in the saved draft yet.", entries: [], more: false, problem: null }),
    });
    tree();
    expect(await screen.findByText("This step isn't in the saved draft yet.")).toBeTruthy();
  });

  it("closes with Escape without closing the drawer", async () => {
    serve();
    const { onClose } = tree();
    const outer = vi.fn();
    document.addEventListener("keydown", outer);
    await screen.findByRole("tree");
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
    expect(outer).not.toHaveBeenCalled();
    document.removeEventListener("keydown", outer);
  });

  it("shows a root's fields in its group, and a root without any by the last part of its path (as the API names them)", async () => {
    const roots = [
      entry("trigger", { root: "trigger", step: null, name: "trigger", types: ["object"], sensitive: true, children: true }),
      entry("trigger.site", { root: "trigger", step: null, name: "site", parent: "trigger" }),
      entry("run.now", { root: "run", step: null, name: "run.now", format: "date-time" }),
    ];
    serve({ "GET /api/v1/t/t1/workflows/w1/draft/scope": () => answer(roots) });
    tree();
    const t = await screen.findByRole("tree");
    const rows = within(t).getAllByRole("treeitem").filter((r) => r.getAttribute("aria-level") === "2");
    expect(rows.map((r) => r.querySelector(".font-mono")?.textContent)).toEqual(["site", "now"]);
    expect(screen.queryByRole("textbox", { name: "A path in the trigger" })).toBeNull(); // declared: browsed, not typed
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`):
`npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/drawer/DataTree.test.tsx`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  no tests`. The run can't import `./DataTree`: it doesn't exist yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/routes/editor/drawer/DataTree.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The data a field can read, to insert as a pill (4c-2b, the mockups' tree boards): the saved draft's scope (B6) by
// where it comes from, each value with its type, whether it may be missing or null, and whether it's sensitive. In the
// drawer, under its field, never over the canvas (the 320 px board). An ARIA tree: one tab stop, arrows to move, → to
// open, ← to close or go up, Enter to insert, Escape to close. A key a reference can't name, or a value validation
// refuses here, is shown and can't be chosen (ruling 118).
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { opsFor } from "../../../lib/builder";
import { DraftMoved, groupOf, scopeQuery, tagsOf, typeWords, type ScopeEntry, type Where } from "../../../lib/data";
import { parsePath } from "../../../lib/pills";
import { useDrawer } from "./context";

/** What a pick is for: text takes any value a reference can name; a condition, one a formula can read. */
export type Purpose = "text" | "condition";

/** Why an entry can't be chosen here, or null. */
export function refusal(entry: ScopeEntry, purpose: Purpose): string | null {
  if (entry.problem) return entry.problem.message;
  if (!entry.nameable) return "A reference can't name this key.";
  if (purpose === "condition" && entry.formula === null) return "A formula can't read this key.";
  // A comparison needs an operator: an object that's always there takes none (the review of revision 1).
  if (purpose === "condition" && opsFor(entry.types, entry.format, entry.missing || entry.nullable).length === 0) {
    return "It's always there, so there's nothing to compare: open it and pick one of its values.";
  }
  // A template's part is text, a number or a yes or no (template.part_not_scalar).
  if (purpose === "text" && entry.types.some((t) => t === "object" || t === "array")) return "Only text, numbers and yes-or-no values go into text.";
  return null;
}

interface Row {
  entry: ScopeEntry;
  level: number;
}

function useWhere(field: string): Where | null {
  const drawer = useDrawer();
  return drawer.revision === null
    ? null
    : { tenantId: drawer.tenantId, workflowId: drawer.workflowId, revision: drawer.revision, node: drawer.node.id, field };
}

/** One value: its name, its tags, its type; its children once opened. */
function Item({ row, where, purpose, open, active, setActive, toggle, pick, register, rows }: {
  row: Row; where: Where; purpose: Purpose; open: ReadonlySet<string>; active: string | null; setActive: (path: string) => void;
  toggle: (path: string) => void; pick: (entry: ScopeEntry) => void; register: (path: string, el: HTMLLIElement | null) => void;
  rows: (path: string, entries: ScopeEntry[] | null) => void;
}) {  // prettier-ignore
  const { entry, level } = row;
  const expanded = entry.children && open.has(entry.path);
  const children = useQuery({ ...scopeQuery(where, { kind: "under", path: entry.path }), enabled: expanded });
  // The same array while the answer is: the tree learns what's shown below each value only when it changes.
  const kids = useMemo(
    () => (expanded && children.data?.state === "ok" ? children.data.entries.filter((e) => e.parent === entry.path) : null),
    [expanded, children.data, entry.path],
  );
  useEffect(() => rows(entry.path, kids), [entry.path, kids, rows]);
  const why = refusal(entry, purpose);
  return (
    <li
      ref={(el) => register(entry.path, el)}
      role="treeitem" aria-level={level} aria-expanded={entry.children ? expanded : undefined}
      aria-selected={active === entry.path} aria-disabled={why !== null || undefined}
      tabIndex={active === entry.path ? 0 : -1} data-path={entry.path}
      onFocus={(e) => {
        if (e.target === e.currentTarget) setActive(entry.path);
      }}
      onClick={(e) => {
        e.stopPropagation();
        setActive(entry.path);
        if (why === null) pick(entry);
        else if (entry.children) toggle(entry.path);
      }}
      className="outline-none"
    >
      <div
        className={`flex min-h-8 items-center gap-2 px-3 py-1 text-body ${active === entry.path ? "bg-accent-soft outline outline-2 -outline-offset-2 outline-focus" : ""} ${why ? "text-muted" : ""}`}
        style={{ paddingLeft: `${12 + (level - 2) * 16}px` }}
      >
        <span aria-hidden="true" className="w-3 text-muted">{entry.children ? (expanded ? "▾" : "▸") : ""}</span>
        {/* A root is named by its path (`run.now`): in its group, its last part says it. */}
        <span className="font-mono text-small">{entry.parent === null ? (entry.path.split(".").at(-1) ?? entry.name) : entry.name}</span>
        {tagsOf(entry).map((t) => (
          <span key={t.text} className={`rounded-sm border px-1.5 text-meta ${t.conditional ? "border-dashed border-warn-line bg-warn-bg text-warn-ink" : "border-line-strong text-muted"}`}>
            {t.text}
          </span>
        ))}
        <span className="ml-auto text-meta text-muted">{typeWords(entry)}</span>
      </div>
      {why !== null && <p className="px-3 pb-1 text-meta text-muted" style={{ paddingLeft: `${28 + (level - 2) * 16}px` }}>{why}</p>}
      {expanded && children.isPending && <p className="px-3 py-1 text-small text-muted">Loading…</p>}
      {expanded && children.isError && (
        <p className="px-3 py-1 text-small text-danger">
          {children.error instanceof DraftMoved ? children.error.message : "Its values couldn't be loaded. Close and try again."}
        </p>
      )}
      {expanded && (
        <ul role="group">
          {(kids ?? []).map((k) => (
            <Item
              key={k.path} row={{ entry: k, level: level + 1 }} where={where} purpose={purpose} open={open} active={active}
              setActive={setActive} toggle={toggle} pick={pick} register={register} rows={rows}
            />
          ))}
        </ul>
      )}
      {expanded && children.data?.more && <p className="px-3 py-1 text-small text-muted">Showing the first 500.</p>}
    </li>
  );  // prettier-ignore
}

/** The trigger's own input isn't declared: its fields aren't known, so a path is typed (the owner's ruling: the
 * untyped trigger keeps its fallback). It's checked by the server before it's inserted. */
function TypedPath({ where, pick }: { where: Where; pick: (entry: ScopeEntry) => void }) {
  const [text, setText] = useState("trigger.");
  const [asked, setAsked] = useState<string | null>(null);
  const answer = useQuery({ ...scopeQuery(where, { kind: "at", path: asked ?? "" }), enabled: asked !== null });
  const id = useId();
  const entry = answer.data?.state === "ok" ? (answer.data.entries[0] ?? null) : null;
  const why =
    asked === null || answer.isPending ? null
    : answer.error instanceof DraftMoved ? answer.error.message
    : (answer.data?.problem?.message ?? answer.data?.reason ?? (entry ? refusal(entry, "text") : "Nothing is there."));  // prettier-ignore
  useEffect(() => {
    if (entry && asked !== null && why === null) {
      pick(entry);
      setAsked(null);
    }
  }, [entry, asked, why, pick]);
  const valid = parsePath(text)?.[0];
  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <p className="text-small text-muted">
        This workflow doesn&apos;t declare its trigger&apos;s input, so its fields aren&apos;t known: each is any value, may be
        missing and counts as sensitive. Type a path to use one:
      </p>
      <div className="flex flex-wrap gap-2">
        <input
          id={id} type="text" value={text} spellCheck={false} aria-label="A path in the trigger"
          aria-describedby={why ? `${id}-why` : undefined} aria-invalid={why !== null}
          onChange={(e) => {
            setText(e.target.value);
            setAsked(null);
          }}
          className={`${controlClass(why !== null)} min-w-0 flex-1 font-mono text-small`}
        />
        <Button size="md" disabled={!valid || !("field" in valid) || valid.field !== "trigger"} onClick={() => setAsked(text)}>Insert</Button>
      </div>
      {why && <p id={`${id}-why`} className="text-small text-danger">{why}</p>}
    </div>
  );  // prettier-ignore
}

export function DataTree({ field, purpose, onPick, onClose }: {
  field: string; purpose: Purpose; onPick: (entry: ScopeEntry) => void; onClose: () => void;
}) {  // prettier-ignore
  const drawer = useDrawer();
  const where = useWhere(field);
  const [find, setFind] = useState("");
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const [active, setActive] = useState<string | null>(null);
  const items = useRef(new Map<string, HTMLLIElement>());
  const loaded = useRef(new Map<string, ScopeEntry[] | null>());
  const [, redraw] = useState(0);
  const findId = useId();
  // Opened, by "/" or "＋ Data", focus goes to its search: typing finds, ↓ enters the tree, Escape gives focus back.
  useEffect(() => document.getElementById(findId)?.focus(), [findId]);
  const top = useQuery({ ...scopeQuery(where ?? ({} as Where), find.trim() === "" ? { kind: "top" } : { kind: "find", text: find.trim() }), enabled: where !== null });
  const titleOf = (key: string) => {
    const node = drawer.steps.find((s) => s.key === key);
    return node?.title ?? null;
  };

  // The groups, each a step, the trigger, the run…, holding its roots' children; a root with none shows itself.
  const groups = (() => {
    const entries = top.data?.state === "ok" ? top.data.entries : [];
    const roots = entries.filter((e) => e.parent === null);
    const found = find.trim() !== "";
    const byGroup = new Map<string, { title: string; detail: string | null; rows: ScopeEntry[] }>();
    for (const e of found ? entries : roots) {
      const g = groupOf(e, titleOf);
      const group = byGroup.get(g.key) ?? { title: g.title, detail: g.detail, rows: [] };
      const kids = found ? [] : entries.filter((c) => c.parent === e.path);
      // A root's fields show under its group (a step's output, the trigger's input…); a root with none shows itself.
      group.rows.push(...(kids.length > 0 ? kids : [e]));
      byGroup.set(g.key, group);
    }
    return [...byGroup.entries()];
  })();

  /** The items shown, in order: what arrows move through. */
  const order = (): string[] => {
    const out: string[] = [];
    const walk = (rows: ScopeEntry[]) => {
      for (const e of rows) {
        out.push(e.path);
        if (open.has(e.path)) walk(loaded.current.get(e.path) ?? []);
      }
    };
    for (const [key, g] of groups) {
      out.push(`group:${key}`);
      walk(g.rows);
    }
    return out;
  };
  const entryAt = (path: string): ScopeEntry | null => {
    for (const [, g] of groups) {
      const hit = g.rows.find((r) => r.path === path);
      if (hit) return hit;
    }
    for (const list of loaded.current.values()) {
      const hit = list?.find((r) => r.path === path);
      if (hit) return hit;
    }
    return null;
  };
  const move = (path: string | undefined) => {
    if (!path) return;
    setActive(path);
    items.current.get(path)?.focus();
  };
  const toggle = (path: string) => setOpen((o) => {
    const next = new Set(o);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    return next;
  });  // prettier-ignore
  const pick = (entry: ScopeEntry) => {
    if (refusal(entry, purpose) === null) onPick(entry);
  };

  const onKey = (e: KeyboardEvent<HTMLUListElement>) => {
    const list = order();
    const at = active === null ? -1 : list.indexOf(active);
    const entry = active === null ? null : entryAt(active);
    switch (e.key) {
      case "ArrowDown":
        move(list[Math.min(list.length - 1, at + 1)]);
        break;
      case "ArrowUp":
        move(list[Math.max(0, at - 1)]);
        break;
      case "Home":
        move(list[0]);
        break;
      case "End":
        move(list[list.length - 1]);
        break;
      case "ArrowRight":
        if (entry?.children && !open.has(entry.path)) toggle(entry.path);
        else if (entry?.children) move(loaded.current.get(entry.path)?.[0]?.path);
        else return;
        break;
      case "ArrowLeft":
        if (entry && open.has(entry.path)) toggle(entry.path);
        else if (entry?.parent && items.current.has(entry.parent)) move(entry.parent);
        else return;
        break;
      case "Enter":
        if (entry) pick(entry);
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  const register = (path: string, el: HTMLLIElement | null) => {
    if (el) items.current.set(path, el);
    else items.current.delete(path);
  };
  const rows = useCallback((path: string, entries: ScopeEntry[] | null) => {
    if (loaded.current.get(path) !== entries) {
      loaded.current.set(path, entries);
      redraw((n) => n + 1);
    }
  }, []);
  const first = order()[0] ?? null;
  // The trigger's input isn't declared: nothing below it to browse, so a path is typed (the untyped trigger's fallback).
  const untyped = top.data?.state === "ok" && top.data.entries.some((e) => e.root === "trigger" && e.parent === null && !e.children);
  const current = active ?? first;

  return (
    <div
      role="dialog" aria-label="Insert data"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // closes the tree, not the drawer
          onClose();
        }
      }}
      className="flex flex-col gap-2 rounded-lg border border-line-strong bg-surface py-2"
    >
      <div className="flex items-center justify-between gap-2 px-3">
        <label htmlFor={findId} className="text-small font-semibold">Find data</label>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      <div className="px-3">
        <input
          id={findId} type="search" value={find} maxLength={100} placeholder="A field's name, like timezone"
          onChange={(e) => {
            setFind(e.target.value);
            setActive(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              move(order()[0]);
            }
          }}
          className={controlClass(false)}
        />
      </div>
      {where === null ? (
        <p className="px-3 text-small text-muted">A version&apos;s data isn&apos;t shown: open the draft to insert data.</p>
      ) : top.isPending ? (
        <p className="px-3 text-small text-muted">Loading the data available here…</p>
      ) : top.isError ? (
        <p className="px-3 text-small text-danger">
          {top.error instanceof DraftMoved ? top.error.message : "The data available here couldn't be loaded. Close and try again."}
        </p>
      ) : top.data.state === "unavailable" ? (
        <p className="px-3 text-small text-muted">{top.data.reason}</p>
      ) : groups.length === 0 ? (
        <p className="px-3 text-small text-muted">{find.trim() === "" ? "No data is available here yet." : "Nothing matches."}</p>
      ) : (
        <>
        {untyped && purpose === "text" && <TypedPath where={where} pick={pick} />}
        <ul role="tree" aria-label="Data available here" onKeyDown={onKey} className="max-h-96 overflow-y-auto">
          {groups.map(([key, g]) => (
            <li
              key={key} role="treeitem" aria-level={1} aria-expanded={true} aria-selected={current === `group:${key}`}
              tabIndex={current === `group:${key}` ? 0 : -1} ref={(el) => register(`group:${key}`, el)}
              onFocus={(e) => {
                if (e.target === e.currentTarget) setActive(`group:${key}`);
              }}
              className={`outline-none ${current === `group:${key}` ? "outline outline-2 -outline-offset-2 outline-focus" : ""}`}
            >
              <span className="block px-3 pt-2.5 pb-1 text-small font-semibold">
                {g.title}{g.detail && <span className="font-normal text-muted"> · {g.detail}</span>}
              </span>
              <ul role="group">
                {g.rows.map((e) => (
                  <Item
                    key={e.path} row={{ entry: e, level: 2 }} where={where} purpose={purpose} open={open} active={current}
                    setActive={setActive} toggle={toggle} pick={pick} register={register} rows={rows}
                  />
                ))}
              </ul>
            </li>
          ))}
        </ul>
        </>
      )}
      {top.data?.state === "ok" && top.data.more && <p className="px-3 text-small text-muted">More data matches: type more of its name.</p>}
      <p className="px-3 text-meta text-muted">↑ ↓ move · → open · Enter insert · Esc close</p>
    </div>
  );  // prettier-ignore
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/drawer/DataTree.test.tsx`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  11 passed (11)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/drawer/DataTree.test.tsx frontend/src/routes/editor/drawer/DataTree.tsx
git commit -m "feat(editor): the data tree a field can insert from (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: A pill, and its details (`drawer/Pill.tsx`, `drawer/PillDetails.tsx`)

A pill as a button whose name starts with its text (ruling 7), dashed when its value may be missing, its state asked of
the saved draft per pill (ruling 6); and its details (ruling 9): type, why it may be missing, a default when it's in
text, and a step's newest sample, asked for each time they open, with its run, attempt and connection, `[redacted]` and
`[truncated]` as chips.

**Files:**
- Create: `frontend/src/routes/editor/drawer/Pill.tsx`
- Create: `frontend/src/routes/editor/drawer/PillDetails.test.tsx`
- Create: `frontend/src/routes/editor/drawer/PillDetails.tsx`

**Interfaces:**
- Consumes: `scopeQuery`, `samplesQuery`, `previewAt`, `tagsOf`, `typeWords`, `whyMissing`, `Sample`, `DraftMoved` (Task
  3); `headOf`, `parsePath`, `pillText`, `Pill` (Task 2); `Drawer.revision`, `Drawer.steps` (Task 5).
- Produces: `usePillEntry(path, field): { entry; problem }`, `PillButton({ pill, entry, index, onKeyDown?, onOpen,
  buttonRef?, disabled? })`; `PreviewValue({ value })`; `PillDetails({ field, pill, defaults, onDefault, onReplace,
  onRemove, onClose })`.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/routes/editor/drawer/PillDetails.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Sample, ScopeEntry } from "../../../lib/data";
import { typeWith } from "../../../test/nodeTypes";
import { fakeApi, json, NODE_ID, showFields } from "./harness";
import { PillDetails } from "./PillDetails";

const NOTE = typeWith({ type: "object", properties: { message: { type: "string" } } }, { ref: "acme.note@1", type: "acme.note", title: "Post a note" });
const SITE = "00000000-0000-4000-8000-000000000002";
const steps = [
  { id: NODE_ID, key: "step", title: "Post a note" },
  { id: SITE, key: "get_site", title: "Get a site" },
];
const PATH = "steps.get_site.output.timezone";
const ENTRY: ScopeEntry = {
  children: false, format: null, missing: true, name: "timezone", nameable: true, nullable: false, parent: null, path: PATH,
  problem: null, root: "steps", sensitive: false, step: SITE, types: ["string"],
  formula: { guards: [{ kind: "present", path: PATH, size: null }], null_test: false, sensitive: false },
};  // prettier-ignore

const sample = (over: Partial<Sample> = {}): Sample => ({
  attempt: 1, captured_at: "2026-10-10T14:02:00Z", iteration_key: "", mode: "live", run_id: "4f2c19e1-0000-4000-8000-000000000000",
  run_kind: "run", same_config: true, same_type: true, stale: false, type: "mist.site.get@1", version_id: "v", version_number: 3,
  output: { name: "HQ", timezone: "America/Los_Angeles" },
  connections: { state: "recorded", items: [{ connection_id: "c1", context: {}, current_revision: 1, name: "Acme Prod", revision: 1, state: "unchanged", type: "mist" }] },
  ...over,
});  // prettier-ignore

function show(answer: { sample: Sample | null; searched_runs?: number }) {
  fakeApi({
    "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
      json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: [ENTRY], more: false, problem: null }),
    "GET /api/v1/t/t1/workflows/w1/draft/samples": (q) =>
      q.get("node") === SITE
        ? json({ draft_revision: 1, node: SITE, sample: answer.sample, searched_runs: answer.searched_runs ?? 1, search_limit: 200 })
        : json({ error: "not_found" }, 404),
  });
  showFields(NOTE, { steps }, <PillDetails field="/message" pill={{ ref: PATH }} defaults onDefault={vi.fn()} onReplace={vi.fn()} onRemove={vi.fn()} onClose={vi.fn()} />);
}

afterEach(() => vi.restoreAllMocks());

describe("a pill's details", () => {
  it("says its type, why it may be missing, and the value a past run gave, with that run", async () => {
    show({ sample: sample() });
    expect(await screen.findByText("text")).toBeTruthy();
    expect(screen.getByText(/it's optional in its data/)).toBeTruthy();
    expect((await screen.findByText(/America\/Los_Angeles/)).textContent).toBe('"America/Los_Angeles"');
    expect(screen.getByText(/4f2c19e1 · version 3 · live · succeeded/)).toBeTruthy();
    expect(screen.getByText("Acme Prod (mist) · unchanged since")).toBeTruthy();
  });

  it("asks for a step's sample again each time its details open: a run may have ended since (the review of revision 1)", async () => {
    let current: Sample | null = null;
    fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": () =>
        json({ draft_revision: 1, node: NODE_ID, field: "/message", state: "ok", reason: null, entries: [ENTRY], more: false, problem: null }),
      "GET /api/v1/t/t1/workflows/w1/draft/samples": () =>
        json({ draft_revision: 1, node: SITE, sample: current, searched_runs: current ? 1 : 0, search_limit: 200 }),
    });
    const f = showFields(NOTE, { steps }, <PillDetails field="/message" pill={{ ref: PATH }} defaults onDefault={vi.fn()} onReplace={vi.fn()} onRemove={vi.fn()} onClose={vi.fn()} />);
    expect(await screen.findByText(/hasn't finished a run yet/)).toBeTruthy();
    current = sample();
    f.remount();
    expect(await screen.findByText(/America\/Los_Angeles/)).toBeTruthy();
  });

  it("shows a redacted value as a chip, never the value", async () => {
    show({ sample: sample({ output: { timezone: "Bearer [redacted]" } }) });
    const chip = await screen.findByText("redacted");
    expect(chip.parentElement?.textContent).toBe('"Bearer redacted"');
  });

  it("says a preview too large to keep, and what the step's settings or connection changed", async () => {
    show({ sample: sample({ output: "[truncated]", same_config: false }) });
    expect(await screen.findByText("truncated")).toBeTruthy();
    expect(screen.getByText(/over 8 KiB/)).toBeTruthy();
    expect(screen.getByText(/get_site's settings have changed since this run/)).toBeTruthy();
  });

  it("says a run's connection changed since, or isn't known, or wasn't used", async () => {
    show({ sample: sample({ stale: true, connections: { state: "recorded", items: [{ connection_id: "c1", context: {}, current_revision: 5, name: "Acme Prod", revision: 3, state: "changed", type: "mist" }] } }) });
    expect(await screen.findByText("Acme Prod (mist) · revision 3 then, 5 now")).toBeTruthy();
    expect(screen.getByText(/Its connection has changed since this run/)).toBeTruthy();
  });

  it("says when no run gave a sample: none finished, none succeeded, or none in the newest 200", async () => {
    show({ sample: null, searched_runs: 0 });
    expect(await screen.findByText(/hasn't finished a run yet/)).toBeTruthy();
  });

  it("says no sample was found in the newest runs searched", async () => {
    show({ sample: null, searched_runs: 200 });
    expect(await screen.findByText("get_site hasn't succeeded in the newest 200 finished runs of this workflow.")).toBeTruthy();
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`):
`npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/drawer/PillDetails.test.tsx`

Expected: FAIL: `Test Files  1 failed (1)`, `Tests  no tests`. The run can't import `./PillDetails`: it doesn't exist
yet.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/routes/editor/drawer/Pill.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// A data pill (4c-2b; 1c's pill grammar, the 4c-2 mockups): what a reference reads, as a round mono button, dashed when
// its value may be missing (ruling 115), and what the saved draft's scope says of it (B6). Text with pills, a pill's
// details and the condition builder draw it.
import { useQuery } from "@tanstack/react-query";
import type { KeyboardEvent } from "react";
import { DraftMoved, scopeQuery, type ScopeEntry } from "../../../lib/data";
import { pillText, type Pill } from "../../../lib/pills";
import { useDrawer } from "./context";

/** What a pill knows of its value from the saved draft's scope: nothing yet, an entry, or the problem reading it. */
export function usePillEntry(path: string, field: string): { entry: ScopeEntry | null; problem: string | null } {
  const drawer = useDrawer();
  const live = drawer.revision !== null;
  const answer = useQuery({
    ...scopeQuery(
      { tenantId: drawer.tenantId, workflowId: drawer.workflowId, revision: drawer.revision ?? -1, node: drawer.node.id, field },
      { kind: "at", path },
    ),
    enabled: live,
  });  // prettier-ignore
  const data = answer.data;
  if (answer.error instanceof DraftMoved) return { entry: null, problem: answer.error.message };
  if (!data || data.state !== "ok") return { entry: null, problem: data?.reason ?? null };
  return { entry: data.entries[0] ?? null, problem: data.problem?.message ?? null };
}

/** A pill: its visible text first in its name (WCAG 2.5.3), then its path and what may happen to its value. */
export function PillButton({ pill, entry, index, onKeyDown, onOpen, buttonRef, disabled }: {
  pill: Pill; entry: ScopeEntry | null; index: number; onKeyDown?: (e: KeyboardEvent<HTMLButtonElement>) => void;
  onOpen: () => void; buttonRef?: (el: HTMLButtonElement | null) => void; disabled?: boolean;
}) {  // prettier-ignore
  const missing = entry?.missing === true;
  const text = pillText(pill.ref);
  const said = [
    `${text}${missing ? " ?" : ""}`,
    pill.ref,
    missing ? "may be missing" : null,
    entry?.nullable ? "may be null" : null,
    missing || entry?.nullable ? ("default" in pill ? `if so: ${pill.default === null ? "null" : `"${pill.default}"`}` : "no default") : null,
  ].filter((s) => s !== null);
  return (
    <button
      ref={buttonRef} type="button" data-pill={index} aria-label={said.join(", ")} aria-haspopup="dialog"
      aria-disabled={disabled || undefined} onClick={onOpen} onKeyDown={onKeyDown}
      className={`inline-flex max-w-full items-center rounded-pill border px-2 font-mono text-small ${
        missing ? "border-dashed border-warn-line bg-warn-bg text-warn-ink" : "border-accent bg-accent-soft text-accent-ink"}`}
    >
      <span className="truncate">{text}</span>
      {missing && <span aria-hidden="true">&nbsp;?</span>}
    </button>
  );  // prettier-ignore
}
````

**Create** `frontend/src/routes/editor/drawer/PillDetails.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// A pill's details (4c-2b, the mockups' details and sample boards): opened from a focused pill with Enter, never on
// hover. What it reads, its type, why it may be missing; a default when it's in text (a template part's); and, from
// the newest run that gave it (B7), the value as the run's preview kept it, with that run, its attempt, its connection
// and whether the step still matches. In the drawer, under its field. Samples show only here (the owner's ruling).
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { DraftMoved, previewAt, samplesQuery, tagsOf, typeWords, whyMissing, type Sample } from "../../../lib/data";
import { headOf, parsePath, type Pill } from "../../../lib/pills";
import { useDrawer } from "./context";
import { usePillEntry } from "./Pill";

/** A preview's marker, as a chip: never the value it stands for (D20). */
const Chip = ({ children }: { children: ReactNode }) => (
  <span className="rounded-sm border border-line-strong px-1.5 font-mono text-meta text-muted">{children}</span>
);

/** A JSON value as the preview kept it, each `[redacted]` and `[truncated]` a chip where it was. */
export function PreviewValue({ value }: { value: unknown }): ReactNode {
  if (typeof value === "string") {
    const parts = value.split(/(\[redacted\]|\[truncated\])/);
    return (
      <>
        &quot;
        {parts.map((p, i) => (p === "[redacted]" ? <Chip key={i}>redacted</Chip> : p === "[truncated]" ? <Chip key={i}>truncated</Chip> : p))}
        &quot;
      </>
    );
  }
  if (Array.isArray(value)) {
    return (
      <>
        [
        {(value as unknown[]).map((v, i) => (
          <span key={i}>
            {i > 0 && ", "}
            <PreviewValue value={v} />
          </span>
        ))}
        ]
      </>
    );
  }
  if (typeof value === "object" && value !== null) {
    return (
      <>
        {"{ "}
        {Object.entries(value as Record<string, unknown>).map(([k, v], i) => (
          <span key={k}>
            {i > 0 && ", "}&quot;{k}&quot;: <PreviewValue value={v} />
          </span>
        ))}
        {" }"}
      </>
    );
  }
  return <>{JSON.stringify(value)}</>;
}

const when = (iso: string | null): string => {
  if (iso === null) return "time not recorded";
  const at = new Date(iso);
  return at.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
};

function SampleView({ sample, rest, stepKey, searched, limit }: {
  sample: Sample | null; rest: (string | number)[]; stepKey: string; searched: number; limit: number;
}) {  // prettier-ignore
  if (sample === null) {
    return (
      <p className="text-small text-muted">
        {searched === 0
          ? `This workflow hasn't finished a run yet, so ${stepKey} has no sample.`
          : searched < limit
            ? `${stepKey} hasn't succeeded in a run of this workflow yet. Its type, and whether it may be missing, come from its schema.`
            : `${stepKey} hasn't succeeded in the newest ${limit} finished runs of this workflow.`}
      </p>
    );
  }
  const found = previewAt(sample.output, rest);
  const c = sample.connections;
  return (
    <div className="flex flex-col gap-2">
      <div className="break-all rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-small">
        {"value" in found ? <PreviewValue value={found.value} />
          : found.marker === "absent" ? "Not in this run's output."
          : found.marker === "claimed" ? "Kept apart from the run's history, so not in its preview."
          : <Chip>{found.marker}</Chip>}
      </div>
      {"marker" in found && found.marker === "truncated" && (
        <p className="text-small text-muted">This step&apos;s output was over 8 KiB, so no preview of it was kept. The output itself went on to the next steps as usual.</p>
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-small">
        <dt className="text-muted">Run</dt>
        <dd className="font-mono">
          {sample.run_id.slice(0, 8)} · version {sample.version_number} · {sample.mode === "simulate" ? "simulated" : "live"}
          {sample.run_kind === "subflow" ? " · as a sub-flow" : sample.run_kind === "failure_handler" ? " · as a failure handler" : ""} · succeeded
        </dd>
        <dt className="text-muted">Attempt</dt>
        <dd>{sample.attempt} · {when(sample.captured_at)}{sample.iteration_key !== "" ? ` · iteration ${sample.iteration_key}` : ""}</dd>
        {c.state !== "none" && (
          <>
            <dt className="text-muted">Connection</dt>
            <dd>
              {c.state === "simulated"
                ? "None: a simulation sends nothing."
                : c.state === "unknown"
                  ? "Unknown: this run is from before connections were recorded."
                  : c.items.map((x) => (
                      <span key={`${x.connection_id}:${x.revision}`} className="block">
                        {x.name} ({x.type}) ·{" "}
                        {x.state === "unchanged"
                          ? "unchanged since"
                          : x.state === "deleted"
                            ? "deleted since"
                            : `revision ${x.revision} then, ${x.current_revision} now`}
                      </span>
                    ))}
            </dd>
          </>
        )}
      </dl>
      {!sample.same_type ? (
        <p className="text-small text-ink">{stepKey} is another type of step now, so this sample may not match what it gives.</p>
      ) : !sample.same_config ? (
        <p className="text-small text-ink">{stepKey}&apos;s settings have changed since this run, so this sample may not match what it gives now.</p>
      ) : sample.stale ? (
        <p className="text-small text-ink">Its connection has changed since this run, so this sample may not match what it gives now.</p>
      ) : null}
    </div>
  );  // prettier-ignore
}

export function PillDetails({ field, pill, defaults, onDefault, onReplace, onRemove, onClose }: {
  field: string; pill: Pill; defaults: boolean; onDefault: (value: string | null | undefined) => void;
  onReplace: () => void; onRemove: () => void; onClose: () => void;
}) {  // prettier-ignore
  const drawer = useDrawer();
  const { entry, problem } = usePillEntry(pill.ref, field);
  const heading = useId();
  const defaultId = useId();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => box.current?.querySelector<HTMLElement>("h3")?.focus(), []);
  const parts = parsePath(pill.ref) ?? [];
  const head = headOf(pill.ref).head;
  const isStep = parts.length >= 3 && "field" in parts[0]! && parts[0].field === "steps" && "field" in parts[2]! && parts[2].field === "output";
  const step = isStep ? drawer.steps.find((s) => s.key === head) : undefined;
  const rest = parts.slice(3).map((p) => ("field" in p ? p.field : p.index));
  const samples = useQuery({
    ...samplesQuery({ tenantId: drawer.tenantId, workflowId: drawer.workflowId, revision: drawer.revision ?? -1, node: step?.id ?? "" }),
    enabled: drawer.revision !== null && step !== undefined,
  });  // prettier-ignore
  const reasons = entry ? whyMissing(entry) : [];
  const editable = drawer.editable;
  return (
    <div
      ref={box} role="dialog" aria-labelledby={heading}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation(); // closes the details, not the drawer
          onClose();
        }
      }}
      className="flex flex-col gap-3 rounded-lg border border-line-strong bg-surface p-3.5"
    >
      <div className="flex items-start justify-between gap-2">
        <h3 id={heading} tabIndex={-1} className="break-all font-mono text-small font-semibold outline-none">{pill.ref}</h3>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {problem && <p className="text-small text-danger">{problem}</p>}
      {entry && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-small">
          <dt className="text-muted">Type</dt>
          <dd>{typeWords(entry)}</dd>
          <dt className="text-muted">When it runs</dt>
          <dd className="flex flex-wrap items-center gap-1.5">
            {tagsOf(entry).map((t) => (
              <span key={t.text} className={`rounded-sm border px-1.5 text-meta ${t.conditional ? "border-dashed border-warn-line bg-warn-bg text-warn-ink" : "border-line-strong text-muted"}`}>{t.text}</span>
            ))}
            {reasons.length > 0 ? reasons.join("; ") : "always there"}
          </dd>
        </dl>
      )}
      {defaults && entry && (entry.missing || entry.nullable) && (
        <div className="flex flex-col gap-1.5">
          {"default" in pill ? (
            <>
              <label htmlFor={defaultId} className="text-small font-semibold">If it&apos;s missing or null</label>
              <input
                id={defaultId} type="text" value={pill.default ?? ""} disabled={!editable} aria-describedby={`${defaultId}-note`}
                onChange={(e) => onDefault(e.target.value)} className={controlClass(false)}
              />
              <p id={`${defaultId}-note`} className="text-small text-muted">
                Used when the value is missing or null. Empty text, 0, false and empty lists are values, so they&apos;re kept. A
                default doesn&apos;t change what&apos;s sensitive: if the value is, the result still is.
              </p>
              {editable && <div><Button size="sm" onClick={() => onDefault(undefined)}>Remove the default</Button></div>}
            </>
          ) : editable ? (
            <div><Button size="sm" onClick={() => onDefault("")}>Add a default…</Button></div>
          ) : (
            <p className="text-small text-muted">No default: when it&apos;s missing, the text has nothing there.</p>
          )}
        </div>
      )}
      {isStep && (
        <section aria-label="From a past run" className="flex flex-col gap-2">
          <h4 className="text-small font-semibold">From a past run</h4>
          {samples.isPending ? (
            <p className="text-small text-muted">Looking for a sample…</p>
          ) : samples.isError ? (
            <p className="text-small text-muted">{samples.error instanceof DraftMoved ? samples.error.message : "The sample couldn't be loaded."}</p>
          ) : (
            <SampleView sample={samples.data.sample} rest={rest} stepKey={head} searched={samples.data.searched_runs} limit={samples.data.search_limit} />
          )}
        </section>
      )}
      {editable && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={onReplace}>Replace…</Button>
          <Button size="sm" variant="danger" onClick={onRemove}>Remove</Button>
        </div>
      )}
    </div>
  );  // prettier-ignore
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor/drawer/PillDetails.test.tsx`

Expected: PASS: `Test Files  1 passed (1)`, `Tests  7 passed (7)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/drawer/Pill.tsx frontend/src/routes/editor/drawer/PillDetails.test.tsx frontend/src/routes/editor/drawer/PillDetails.tsx
git commit -m "feat(editor): a data pill, and its details with a past run's sample (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Text with data pills: a text field's Text mode (`drawer/TextPills.tsx`)

One editor of inputs and pills (ruling 1) as a text field's fixed mode, "Text" (ruling 3): "＋ Data" and "/" (ruling 5)
open the tree at the caret, Enter on a pill its details, Backspace removes it, the arrows move past it. A write refused
is held whole as a `template`. A reference or a template in a text field shows here, as pills. Four of 4c-1's field
tests change on purpose (ruling 14).

**Files:**
- Modify: `frontend/src/routes/editor/drawer/FieldView.test.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx`
- Create: `frontend/src/routes/editor/drawer/TextPills.test.tsx`
- Create: `frontend/src/routes/editor/drawer/TextPills.tsx`

**Interfaces:**
- Consumes: `segmentsOf`, `valueOf`, `insertPill`, `removePill`, `replacePill`, `withDefault`, `withText`,
  `segmentsText`, `pillText`, `Caret`, `Pill`, `Segments` (Task 2); `takesPills`, the held `template` and its
  `literalOk`, `ModeSwitch`'s `fixedName` (Task 5); `DataTree` (Task 6); `PillButton`, `usePillEntry`, `PillDetails`
  (Task 7); `ControlProps` (`drawer/scalars.tsx`).
- Produces: `asksForData(text, offset)`, `Opened`, `PillsPanel`, `TextPills(props & { panel })`, `withPill(segments, at,
  ref, slash)`; `PILLS_NOTE` exported by `FieldView.tsx`.

- [ ] **Step 1: Write the failing tests**

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
import { FILTER, IF, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith } from "../../../test/nodeTypes";
import { STALE } from "../../../lib/unapplied";
import { NODE_ID, fakeApi, problem, showFields } from "./harness";

````

**with**:

````tsx
import { FILTER, IF, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith } from "../../../test/nodeTypes";
import { STALE } from "../../../lib/unapplied";
import { PILLS_NOTE } from "./FieldView";
import { NODE_ID, fakeApi, problem, showFields } from "./harness";

````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
  const name = screen.getByLabelText("Name");
  const described = name.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent);
  expect(described).toEqual(["Shown to people.", "Too short."]);
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(name.getAttribute("aria-required")).toBe("true");
````

**with**:

````tsx
  const name = screen.getByLabelText("Name");
  const described = name.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent);
  expect(described).toEqual([`Shown to people. ${PILLS_NOTE}`, "Too short."]); // a text field takes data pills (4c-2b)
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(name.getAttribute("aria-required")).toBe("true");
````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("7");
  expect(config()).toEqual({ count: 5 });
  expect(held().map((u) => [u.kind, u.text])).toEqual([["text", "ab"], ["number", "7"]]);
  expect(screen.getAllByText("Not written: the draft can't be changed now.")).toHaveLength(2);
});
````

**with**:

````tsx
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("7");
  expect(config()).toEqual({ count: 5 });
  expect(held().map((u) => [u.kind, u.text])).toEqual([["template", "ab"], ["number", "7"]]); // text and pills (4c-2b)
  expect(screen.getAllByText("Not written: the draft can't be changed now.")).toHaveLength(2);
});
````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
});

it("shows a reference read only, and keeps it until it's replaced", async () => {
  const ref = { $value: { kind: "ref", path: "steps.fetch.output.name" } };
  const { config, edits } = showFields(PLAIN, { config: { name: ref } });
````

**with**:

````tsx
});

it("shows a reference read only where it isn't text, and keeps it until it's replaced", async () => {
  const ref = { $value: { kind: "ref", path: "steps.fetch.output.n" } };
  const { config, edits } = showFields(PLAIN, { config: { count: ref } });
  expect(screen.getByLabelText("Count").textContent).toBe("steps.fetch.output.n");
  expect(edits).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
  expect(config()).toEqual({ count: formula("steps.fetch.output.n") });
});

it("shows a reference in a text field as a pill, and switches it to the formula that reads it", async () => {
  const ref = { $value: { kind: "ref", path: "steps.fetch.output.name" } };
  const { config, edits } = showFields(PLAIN, { config: { name: ref } });
````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
  expect(screen.getByLabelText("Name").textContent).toBe("steps.fetch.output.name");
  expect(edits).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
  expect(config()).toEqual({ name: formula("steps.fetch.output.name") });
});
````

**with**:

````tsx
  expect(screen.getByRole("button", { name: /^fetch › name, steps\.fetch\.output\.name/ })).toBeTruthy();
  expect(edits).toEqual([]); // shown, never rewritten
  await userEvent.click(within(screen.getByRole("group", { name: "How Name is set" })).getByRole("button", { name: "Formula" }));
  expect(config()).toEqual({ name: formula("steps.fetch.output.name") });
});
````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx

it("gives focus to the new control after a reference is replaced", async () => {
  showFields(PLAIN, { config: { name: { $value: { kind: "ref", path: "steps.fetch.output.name" } } } });
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
````

**with**:

````tsx

it("gives focus to the new control after a reference is replaced", async () => {
  showFields(PLAIN, { config: { count: { $value: { kind: "ref", path: "steps.fetch.output.n" } } } });
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Name")));
  expect(document.activeElement?.tagName).toBe("TEXTAREA");
});
````

**with**:

````tsx
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Count")));
  expect(document.activeElement?.tagName).toBe("TEXTAREA");
});
````

**Create** `frontend/src/routes/editor/drawer/TextPills.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ScopeEntry } from "../../../lib/data";
import { typeWith } from "../../../test/nodeTypes";
import { fakeApi, json, NODE_ID, showFields } from "./harness";

const NOTE = typeWith(
  { type: "object", properties: { message: { type: "string", title: "Message" } }, required: ["message"] },
  { ref: "acme.note@1", type: "acme.note", title: "Post a note" },
);
const SITE = "00000000-0000-4000-8000-000000000002";
const template = (...parts: unknown[]) => ({ $value: { kind: "template", parts } });

const entry = (path: string, over: Partial<ScopeEntry> = {}): ScopeEntry => ({
  children: false, format: null, formula: { guards: [], null_test: false, sensitive: false }, missing: false,
  name: path.split(".").at(-1)!, nameable: true, nullable: false, parent: null, path, problem: null, root: "steps",
  sensitive: false, step: SITE, types: ["string"], ...over,
});  // prettier-ignore

const ENTRIES: ScopeEntry[] = [
  entry("steps.get_site.output", { name: "output", types: ["object"], children: true }),
  entry("steps.get_site.output.name", { parent: "steps.get_site.output" }),
  entry("steps.get_site.output.timezone", { parent: "steps.get_site.output", missing: true }),
  entry("run.now", { root: "run", step: null, name: "now", format: "date-time" }),
];

const scope = (q: URLSearchParams) => {
  const at = q.get("at");
  const answer = (entries: ScopeEntry[]) =>
    json({ draft_revision: 1, node: NODE_ID, field: q.get("field"), state: "ok", reason: null, entries, more: false, problem: null });
  if (at !== null) return answer(ENTRIES.filter((e) => e.path === at));
  const under = q.get("under");
  if (under !== null) return answer(ENTRIES.filter((e) => e.parent === under));
  return answer(ENTRIES);
};

beforeEach(() => {
  fakeApi({ "GET /api/v1/t/t1/workflows/w1/draft/scope": scope });
});
afterEach(() => vi.restoreAllMocks());

const steps = [
  { id: NODE_ID, key: "step", title: "Post a note" },
  { id: SITE, key: "get_site", title: "Get a site" },
];

describe("text with data pills", () => {
  it("writes typed text as text, and the field's mode is Text", async () => {
    const f = showFields(NOTE, { steps });
    expect(screen.getByRole("button", { name: "Text" }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.type(screen.getByLabelText("Message"), "AP down");
    expect(f.config()).toEqual({ message: "AP down" });
  });

  it("inserts a pill from the tree at the caret, and writes a template", async () => {
    const f = showFields(NOTE, { steps, config: { message: "AP  went offline" } });
    const text = screen.getByLabelText("Message");
    await userEvent.click(text);
    (text as HTMLInputElement).setSelectionRange(3, 3);
    fireEvent.select(text);
    await userEvent.click(screen.getByRole("button", { name: "＋ Data" }));
    const tree = await screen.findByRole("tree", { name: "Data available here" });
    await userEvent.click(within(tree).getByText("name"));
    expect(f.config()).toEqual({ message: template({ text: "AP " }, { ref: "steps.get_site.output.name" }, { text: " went offline" }) });
    expect(screen.queryByRole("tree")).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("textbox", { name: "Message, text after get_site › name" })));
  });

  it("opens the tree with / at a text's start or after a space, never inside a word or a URL", async () => {
    showFields(NOTE, { steps, config: { message: "https:" } });
    const text = screen.getByLabelText("Message");
    await userEvent.type(text, "/");
    expect(screen.queryByRole("dialog", { name: "Insert data" })).toBeNull();
    await userEvent.type(text, " /");
    expect(await screen.findByRole("dialog", { name: "Insert data" })).toBeTruthy();
  });

  it("replaces the / typed to ask for data with the pill picked", async () => {
    const f = showFields(NOTE, { steps });
    await userEvent.type(screen.getByLabelText("Message"), "at /");
    const tree = await screen.findByRole("tree");
    await userEvent.click(within(tree).getByText("now"));
    expect(f.config()).toEqual({ message: template({ text: "at " }, { ref: "run.now" }) });
  });

  it("keeps the / when the tree is closed with Escape, and puts focus back after it", async () => {
    const f = showFields(NOTE, { steps });
    await userEvent.type(screen.getByLabelText("Message"), "a /");
    await screen.findByRole("tree");
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("tree")).toBeNull();
    expect(f.config()).toEqual({ message: "a /" });
    await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Message")));
  });

  it("moves past a pill with the arrows, and removes it with Backspace, joining the texts either side", async () => {
    const f = showFields(NOTE, { steps, config: { message: template({ text: "AP " }, { ref: "run.now" }, { text: " down" }) } });
    const after = screen.getByRole("textbox", { name: "Message, text after run › now" });
    await userEvent.click(after);
    (after as HTMLInputElement).setSelectionRange(0, 0);
    await userEvent.keyboard("{ArrowLeft}");
    const pill = screen.getByRole("button", { name: /^run › now, run\.now/ });
    expect(document.activeElement).toBe(pill);
    await userEvent.keyboard("{Backspace}");
    expect(f.config()).toEqual({ message: "AP  down" });
    await waitFor(() => expect((document.activeElement as HTMLInputElement).selectionStart).toBe(3));
  });

  it("draws a pill whose value may be missing dashed, and says so in its name", async () => {
    showFields(NOTE, { steps, config: { message: template({ ref: "steps.get_site.output.timezone" }) } });
    const pill = await screen.findByRole("button", { name: /^get_site › timezone \?, steps\.get_site\.output\.timezone, may be missing, no default$/ });
    expect(pill.className).toContain("border-dashed");
  });

  it("opens a pill's details with Enter, and writes the default typed there into its part", async () => {
    const f = showFields(NOTE, { steps, config: { message: template({ ref: "steps.get_site.output.timezone" }) } });
    const pill = await screen.findByRole("button", { name: /^get_site › timezone/ });
    pill.focus();
    await userEvent.keyboard("{Enter}");
    const details = await screen.findByRole("dialog", { name: "steps.get_site.output.timezone" });
    await userEvent.click(within(details).getByRole("button", { name: "Add a default…" }));
    await userEvent.type(within(details).getByLabelText("If it's missing or null"), "UTC");
    expect(f.config()).toEqual({ message: template({ ref: "steps.get_site.output.timezone", default: "UTC" }) });
  });

  it("holds text and pills a write refused, whole, said in braces, and shows them still", async () => {
    const f = showFields(NOTE, { steps, config: { message: template({ text: "AP " }, { ref: "run.now" }) } });
    f.refuse("Not written: the draft can't be changed now.");
    await userEvent.type(screen.getByRole("textbox", { name: "Message, text after run › now" }), "!");
    expect(f.held()).toMatchObject([{ kind: "template", text: "AP {run.now}!", why: "Not written: the draft can't be changed now." }]);
    act(() => f.remount());
    expect(screen.getByRole<HTMLInputElement>("textbox", { name: "Message, text after run › now" }).value).toBe("!");
  });

  it("holds text where the field takes no fixed value as it would write it: a template (the review of revision 1)", async () => {
    const TEMPLATED = typeWith(
      { type: "object", properties: { message: { type: "string", title: "Message", "x-dewpoint-kinds": ["template", "cel"] } } },
      { ref: "acme.note@1", type: "acme.note", title: "Post a note" },
    );
    const f = showFields(TEMPLATED, { steps });
    await userEvent.click(screen.getByRole("button", { name: "Text" })); // it opens as a formula: it takes no fixed value
    f.refuse("Not written: the draft can't be changed now.");
    await userEvent.type(screen.getByRole("textbox", { name: "Message" }), "hi");
    expect(f.held()).toMatchObject([{ kind: "template", text: "hi", literalOk: false }]);
  });

  it("shows pills in a version's view without asking for data, and offers no ＋ Data", () => {
    showFields(NOTE, { steps, revision: null, editable: false, config: { message: template({ ref: "run.now" }) } });
    expect(screen.getByRole("button", { name: /^run › now/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "＋ Data" })).toBeNull();
  });
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: FAIL: `Test Files  2 failed | 19 passed (21)`, `Tests  14 failed | 273 passed (287)`. The failing tests are
this task's new and changed ones: `labels a field by its title, its hint and the server's problems described by it`,
`keeps what a refused write turned away, with its reason`, `shows a reference in a text field as a pill, and switches it
to the formula that reads it`, `writes typed text as text, and the field's mode is Text`, `inserts a pill from the tree
at the caret, and writes a template`, `opens the tree with / at a text's start or after a space, never inside a word or
a URL`, `replaces the / typed to ask for data with the pill picked`, `keeps the / when the tree is closed with Escape,
and puts focus back after it`, `moves past a pill with the arrows, and removes it with Backspace, joining the texts
either side`, `draws a pill whose value may be missing dashed, and says so in its name`, `opens a pill's details with
Enter, and writes the default typed there into its part`, `holds text and pills a write refused, whole, said in braces,
and shows them still`, `holds text where the field takes no fixed value as it would write it: a template (the review of
revision 1)`, `shows pills in a version's view without asking for data, and offers no ＋ Data`.

- [ ] **Step 3: Write the code**

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
import { Button } from "../../../components/Button";
import { fixedOf, formula, isPlainRef, kindOf, literal, referenceText, valueAt } from "../../../lib/config";
import { canFixed, canFormula, emptyOf, startsAsFormula, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import { STALE, type UnappliedKind } from "../../../lib/unapplied";
import { problemsAt, useDrawer, useSession } from "./context";
````

**with**:

````tsx
import { Button } from "../../../components/Button";
import { fixedOf, formula, isPlainRef, kindOf, literal, referenceText, valueAt } from "../../../lib/config";
import { segmentsOf, type Caret } from "../../../lib/pills";
import { canFixed, canFormula, emptyOf, startsAsFormula, takesPills, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import { STALE, type UnappliedKind } from "../../../lib/unapplied";
import { problemsAt, useDrawer, useSession } from "./context";
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
} from "./scalars";  // prettier-ignore
import { ContainerParts, PortControl, isContainer, partNames } from "./structured";

type Control = (props: ControlProps) => ReactNode;
````

**with**:

````tsx
} from "./scalars";  // prettier-ignore
import { ContainerParts, PortControl, isContainer, partNames } from "./structured";
import { TextPills, type Opened } from "./TextPills";

type Control = (props: ControlProps) => ReactNode;
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
const OWN: UnappliedKind[] = ["text", "json", "number", "formula", "port"]; // what a field's own control may hold
const NEITHER = "This field takes only references or text with references, which can't be set in this drawer.";
````

**with**:

````tsx
const OWN: UnappliedKind[] = ["text", "template", "json", "number", "formula", "port"]; // what a field's own control may hold
const NEITHER = "This field takes only references or text with references, which can't be set in this drawer.";
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx

/** The control for what's held, of this kind: it shows first, whatever the value under it has become (ruling 18). A
````

**with**:

````tsx
export const PILLS_NOTE = "Press / or ＋ Data to insert data from earlier steps. A dashed pill may be missing when this runs: give it a default.";

/** The control for what's held, of this kind: it shows first, whatever the value under it has become (ruling 18). A
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
const startMode = (spec: FieldSpec, value: unknown): Mode =>
  kindOf(value) === "cel" ? "formula"
  : value !== undefined && value !== null ? "fixed"
  : startsAsFormula(spec) ? "formula" : "fixed";  // prettier-ignore
````

**with**:

````tsx
const startMode = (spec: FieldSpec, value: unknown): Mode =>
  kindOf(value) === "cel" ? "formula"
  : takesPills(spec) && segmentsOf(value) !== null && value !== undefined && value !== null ? "fixed"
  : value !== undefined && value !== null ? "fixed"
  : startsAsFormula(spec) ? "formula" : "fixed";  // prettier-ignore
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
  const held = OWN.map((k) => drawer.held(k, spec.pointer)).find((u) => u !== undefined);
  const disabled = !drawer.editable;
  const fixedOk = canFixed(spec);
  const formulaOk = canFormula(spec);
  // What's held decides how the field shows, so a remount, an undo or a closed drawer never hides it (ruling 18).
````

**with**:

````tsx
  const held = OWN.map((k) => drawer.held(k, spec.pointer)).find((u) => u !== undefined);
  const disabled = !drawer.editable;
  // Text with data pills: its fixed mode where the engine takes a template (4c-2b), whatever its kinds say of literals.
  const pills = takesPills(spec);
  const asText = pills && segmentsOf(value) !== null;
  const [opened, setOpened] = useState<Opened | null>(null);
  const caret = useRef<Caret | null>(null);
  const focusNext = useRef<{ segment: number; offset: number } | { pill: number } | null>(null);
  const fixedOk = canFixed(spec) || pills;
  const formulaOk = canFormula(spec);
  // What's held decides how the field shows, so a remount, an undo or a closed drawer never hides it (ruling 18).
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
    if (why === null) then();
  };
  const computed = kind === "ref" || kind === "template";
  // A fixed value in a sensitive field: never shown (M25). A reference or a template there is how a secret is passed,
  // and shows as one (the final review).
````

**with**:

````tsx
    if (why === null) then();
  };
  const computed = (kind === "ref" || kind === "template") && !asText;
  // A fixed value in a sensitive field: never shown (M25). A reference or a template there is how a secret is passed,
  // and shows as one (the final review).
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
      (current) => {
        if (next === "fixed") return kindOf(current) === "cel" ? emptyOf(spec) : current;
        const was = fixedOf(current);
        // A fixed value becomes the formula that gives it, unless it holds a sensitive part: never copied into visible
````

**with**:

````tsx
      (current) => {
        if (next === "fixed") return kindOf(current) === "cel" ? emptyOf(spec) : current;
        // A lone reference becomes its path; text with pills starts an empty formula (Undo brings it back): text
        // around references isn't a formula (4c-2b).
        if (isPlainRef(current)) return formula(referenceText(current));
        if (kindOf(current) === "ref" || kindOf(current) === "template") return emptyOf(spec);
        const was = fixedOf(current);
        // A fixed value becomes the formula that gives it, unless it holds a sensitive part: never copied into visible
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
    <>
      {fixedOk && formulaOk && !computed && !hidden && (
        <ModeSwitch label={spec.label} mode={mode} disabled={disabled} onChange={switchTo} />
      )}
      {mode === "fixed" && fixedOk && !computed && !hidden && kind === null && isContainer(spec.base) && !spec.holdsSensitive && (
````

**with**:

````tsx
    <>
      {fixedOk && formulaOk && !computed && !hidden && (
        <ModeSwitch label={spec.label} mode={mode} disabled={disabled} onChange={switchTo} fixedName={pills ? "Text" : "Fixed"} />
      )}
      {pills && mode === "fixed" && !disabled && drawer.revision !== null && (
        <Button
          size="sm" aria-haspopup="dialog" aria-expanded={opened?.kind === "tree"}
          onClick={() => setOpened(opened?.kind === "tree" ? null : { kind: "tree", at: caret.current ?? { segment: Infinity, offset: Infinity }, slash: false })}
        >
          ＋ Data
        </Button>
      )}
      {mode === "fixed" && fixedOk && !computed && !hidden && kind === null && isContainer(spec.base) && !spec.holdsSensitive && (
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
      ? PortControl
      : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
  const Held = held ? heldControl(held.kind, spec) : null;
  let body: ReactNode;
  let says = false; // how its formula runs, said under it
````

**with**:

````tsx
      ? PortControl
      : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
  const Held = held && held.kind !== "template" ? heldControl(held.kind, spec) : null;
  const panel = { opened, open: setOpened, caret, focus: focusNext };
  const textPills = (c: Described) => (
    <TextPills
      key={generation} {...c} spec={spec} value={hidden ? undefined : fixed} literal={held?.literal ?? kind === "literal"}
      disabled={disabled} onChange={write} panel={panel} // it writes a literal back as one itself, never a template as data
    />
  );  // prettier-ignore
  let body: ReactNode;
  let says = false; // how its formula runs, said under it
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
  if (held && Held) {
    // What's held shows first, before what the value under it has become (a reference, a hidden secret, another
    // mode): it stays visible, and recoverable, until it's applied or discarded (the review of revision 3).
````

**with**:

````tsx
  if (held?.kind === "template" || (mode === "fixed" && asText && !hidden && !(held && Held))) {
    // Text with data pills: what's held, or the value, as text and pills (4c-2b).
    body = frame(textPills, joined(spec.hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, PILLS_NOTE));
  } else if (held && Held) {
    // What's held shows first, before what the value under it has become (a reference, a hidden secret, another
    // mode): it stays visible, and recoverable, until it's applied or discarded (the review of revision 3).
````

**Create** `frontend/src/routes/editor/drawer/TextPills.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// Text with data pills (4c-2b, the 4c-2 mockups' first board): a text field's fixed mode, one editor for its text and
// the references between it (the owner's ruling: one text and pill editor). Its texts are inputs, each pill a button
// between them, in one box: the text is typed as any text field's is, and a pill is a whole that's moved past, opened
// or removed, never half edited. A pill says what it reads, and is dashed when its value may be missing (ruling 115).
import { useEffect, useRef, type KeyboardEvent } from "react";
import { DataTree } from "./DataTree";
import { PillButton, usePillEntry } from "./Pill";
import { PillDetails } from "./PillDetails";
import {
  insertPill, pillText, removePill, replacePill, segmentsOf, segmentsText, valueOf, withDefault, withText, type Caret, type Pill,
  type Segments,
} from "../../../lib/pills";  // prettier-ignore
import { useDrawer } from "./context";
import type { ControlProps } from "./scalars";

function Pills({ pill, field, index, onKeyDown, onOpen, buttonRef }: {
  pill: Pill; field: string; index: number; onKeyDown: (e: KeyboardEvent<HTMLButtonElement>) => void; onOpen: () => void;
  buttonRef: (el: HTMLButtonElement | null) => void;
}) {  // prettier-ignore
  const { entry } = usePillEntry(pill.ref, field);
  return <PillButton pill={pill} entry={entry} index={index} onKeyDown={onKeyDown} onOpen={onOpen} buttonRef={buttonRef} />;
}

/** Whether a "/" typed at this place asks for data: at a text's start or after a space, so a URL's or a path's own
 * slashes stay text. */
export const asksForData = (text: string, offset: number): boolean => offset === 0 || /\s/.test(text[offset - 1] ?? "");

/** What's open under the editor: the tree, to insert at a caret (or to replace a pill), or a pill's details. */
export type Opened = { kind: "tree"; at: Caret; slash: boolean; replace?: number } | { kind: "details"; index: number };

export interface PillsPanel {
  opened: Opened | null;
  open: (opened: Opened | null) => void;
  /** Where the caret was last in this editor: where "+ Data" inserts. */
  caret: { current: Caret | null };
  /** Focus to give once the next render is drawn: a text at an offset, or a pill. */
  focus: { current: { segment: number; offset: number } | { pill: number } | null };
}

export function TextPills({ spec, value, literal, id, describedBy, invalid, disabled, onChange, panel }: ControlProps & { panel: PillsPanel }) {
  const drawer = useDrawer();
  const held = drawer.held("template", spec.pointer);
  const segments: Segments = held?.segments ?? segmentsOf(value) ?? { texts: [""], pills: [] };
  const literalOk = spec.kinds === null || spec.kinds.includes("literal");
  const inputs = useRef<(HTMLInputElement | null)[]>([]);
  const pills = useRef<(HTMLButtonElement | null)[]>([]);
  const asLiteral = held?.literal ?? literal;

  useEffect(() => {
    const want = panel.focus.current;
    if (!want) return;
    panel.focus.current = null;
    if ("pill" in want) pills.current[want.pill]?.focus();
    else {
      const input = inputs.current[want.segment];
      input?.focus();
      input?.setSelectionRange(want.offset, want.offset);
    }
  });

  /** Writes text and pills as one change; refused, it's held with why, whole (ruling 18). */
  const write = (next: Segments, typed: boolean) => {
    const why = onChange(valueOf(next, asLiteral, literalOk), typed);
    if (why === null) drawer.release("template", spec.pointer);
    else drawer.hold("template", spec.pointer, { path: spec.path, label: spec.label, text: segmentsText(next), segments: next, why, literal: asLiteral, literalOk, entry: spec.entry });
  };  // prettier-ignore

  const caretOf = (segment: number, input: HTMLInputElement): Caret => ({ segment, offset: input.selectionStart ?? input.value.length });

  const onTextKey = (segment: number) => (e: KeyboardEvent<HTMLInputElement>) => {
    const input = e.currentTarget;
    const at = input.selectionStart ?? 0;
    const collapsed = at === (input.selectionEnd ?? at);
    if (e.key === "/" && collapsed && asksForData(input.value, at) && !disabled) {
      // The "/" is typed as text: the tree opens over it, and a pick replaces it (Escape keeps it, as typed).
      panel.caret.current = { segment, offset: at + 1 };
      queueMicrotask(() => panel.open({ kind: "tree", at: { segment, offset: at + 1 }, slash: true }));
    } else if (e.key === "ArrowLeft" && collapsed && at === 0 && segment > 0) {
      e.preventDefault();
      pills.current[segment - 1]?.focus();
    } else if (e.key === "ArrowRight" && collapsed && at === input.value.length && segment < segments.pills.length) {
      e.preventDefault();
      pills.current[segment]?.focus();
    } else if (e.key === "Backspace" && collapsed && at === 0 && segment > 0) {
      e.preventDefault(); // the pill before is focused first: a second Backspace removes it
      pills.current[segment - 1]?.focus();
    }
  };

  const onPillKey = (index: number) => (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      panel.focus.current = { segment: index, offset: segments.texts[index]!.length };
      inputs.current[index]?.focus();
      inputs.current[index]?.setSelectionRange(segments.texts[index]!.length, segments.texts[index]!.length);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      inputs.current[index + 1]?.focus();
      inputs.current[index + 1]?.setSelectionRange(0, 0);
    } else if ((e.key === "Backspace" || e.key === "Delete") && !disabled) {
      e.preventDefault();
      const { segments: next, caret } = removePill(segments, index);
      panel.focus.current = caret;
      write(next, false);
    } else if (e.key === "Enter") {
      e.preventDefault();
      panel.open({ kind: "details", index });
    }
  };

  const labelled = (segment: number) => (segment === 0 ? undefined : `${spec.label}, text after ${pillText(segments.pills[segment - 1]!.ref)}`);

  const opened = panel.opened;
  const box = (
    <div
      className={`flex min-h-11 w-full flex-wrap items-center gap-x-1 gap-y-1.5 rounded-lg border bg-surface px-3 py-2 text-body-lg ${
        invalid ? "border-danger" : "border-line-control"} focus-within:outline focus-within:outline-2 focus-within:outline-focus`}
    >
      {segments.texts.map((text, segment) => (
        <span key={`t${segment}`} className="contents">
          <input
            ref={(el) => void (inputs.current[segment] = el)}
            id={segment === 0 ? id : undefined}
            type="text" value={text} disabled={disabled} spellCheck={false}
            aria-label={labelled(segment)} aria-describedby={segment === 0 ? describedBy : undefined}
            aria-invalid={invalid} aria-required={segment === 0 ? spec.required && !spec.entry : undefined}
            size={Math.max(1, text.length)}
            onKeyDown={onTextKey(segment)}
            onSelect={(e) => void (panel.caret.current = caretOf(segment, e.currentTarget))}
            onChange={(e) => {
              panel.caret.current = caretOf(segment, e.currentTarget);
              write(withText(segments, segment, e.target.value), true);
            }}
            // 24 px at least, empty too: a target a pointer can take (WCAG 2.5.8; the gate found an empty one at 1 ch)
            className={`min-h-[24px] min-w-[24px] max-w-full bg-transparent outline-none [field-sizing:content] ${segments.pills.length === 0 ? "flex-1" : ""}`}
          />
          {segments.pills[segment] && (
            <Pills
              pill={segments.pills[segment]} field={spec.pointer} index={segment} onKeyDown={onPillKey(segment)}
              onOpen={() => panel.open({ kind: "details", index: segment })} buttonRef={(el) => void (pills.current[segment] = el)}
            />
          )}
        </span>
      ))}
    </div>
  );
  const after = (focus: { segment: number; offset: number } | { pill: number }) => {
    panel.focus.current = focus;
    panel.open(null);
  };
  return (
    <div className="flex flex-col gap-2">
      {box}
      {opened?.kind === "tree" && (
        <DataTree
          field={spec.pointer} purpose="text"
          onPick={(entry) => {
            if (opened.replace !== undefined) {
              write(replacePill(segments, opened.replace, entry.path), false);
              after({ pill: opened.replace });
            } else {
              const { next, focus } = withPill(segments, opened.at, entry.path, opened.slash);
              write(next, false);
              after(focus);
            }
          }}
          onClose={() => after(opened.replace !== undefined ? { pill: opened.replace } : opened.at)}
        />
      )}
      {opened?.kind === "details" && segments.pills[opened.index] && (
        <PillDetails
          field={spec.pointer} pill={segments.pills[opened.index]!} defaults
          onDefault={(d) => write(withDefault(segments, opened.index, d), true)}
          onReplace={() => panel.open({ kind: "tree", at: { segment: opened.index + 1, offset: 0 }, slash: false, replace: opened.index })}
          onRemove={() => {
            const { segments: next, caret } = removePill(segments, opened.index);
            write(next, false);
            after(caret);
          }}
          onClose={() => after({ pill: opened.index })}
        />
      )}
    </div>
  );  // prettier-ignore
}

/** Text and pills with a pill put at the caret, and where focus goes then: just after it. */
export function withPill(segments: Segments, where: Caret, ref: string, slash: boolean): { next: Segments; focus: Caret } {
  // A caret past the end (none yet: "+ Data" before any typing) is the end of the last text.
  const last = segments.texts.length - 1;
  const at = where.segment > last ? { segment: last, offset: segments.texts[last]!.length } : where;
  // A "/" typed to ask for it is replaced by the pill (asksForData).
  const text = segments.texts[at.segment] ?? "";
  const dropped = slash && text[at.offset - 1] === "/" ? withText(segments, at.segment, text.slice(0, at.offset - 1) + text.slice(at.offset)) : segments;
  const offset = slash && text[at.offset - 1] === "/" ? at.offset - 1 : at.offset;
  return { next: insertPill(dropped, { segment: at.segment, offset }, { ref }), focus: { segment: at.segment + 1, offset: 0 } };
}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: PASS: `Test Files  21 passed (21)`, `Tests  287 passed (287)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/drawer/FieldView.test.tsx frontend/src/routes/editor/drawer/FieldView.tsx frontend/src/routes/editor/drawer/TextPills.test.tsx frontend/src/routes/editor/drawer/TextPills.tsx
git commit -m "feat(editor): text with data pills, inserted from the tree, as a text field's Text mode (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Milestone 2's pause.** Screenshots of a text field with pills, the tree and a pill's details, light and dark, at
  1280 and 320 px, against the isolated stack after a reset, beside the mockups' boards in the session's checkpoint
  page; the unit suite, typecheck, lint and build; then append to the ledger `### 4c-2b, milestone 2 (<date>)` (Tasks
  6–8's commits, the checks as run, mid-slice rulings or none) and commit it. **Pause:** the owner reviews the screens
  before Task 9; Milestone 3 starts on the owner's word.

---

# Milestone 3 — the builder, Declassify, the badge

### Task 9: The condition builder (`drawer/ConditionBuilder.tsx`)

"Builder" replaces "Fixed" for a condition (ruling 11): comparisons picked from the tree, the operators a value's type
takes, groups one level deep, the definitions of "is there" and "is missing", and the formula it writes. A formula it
didn't write stays a formula, and says why. What can't be written yet is held as a `condition`. 4c-1's tests and two
browser flows that set a condition change on purpose (ruling 14).

**Files:**
- Modify: `frontend/e2e/workflows.spec.ts`
- Create: `frontend/src/routes/editor/drawer/ConditionBuilder.test.tsx`
- Create: `frontend/src/routes/editor/drawer/ConditionBuilder.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldView.test.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx`

**Interfaces:**
- Consumes: `ScopeEntry` (Task 3); `Condition`, `Row`, `Group`, `opsFor`, `numeric`, `valueProblem`, `write`, `read`,
  `OP_WORDS`, `NO_VALUE`, `isGroup` (Task 4); the held `condition` and `fixedWhyNot` (Task 5); `DataTree` (Task 6);
  `PillButton`, `usePillEntry` (Task 7); `formula`, `formulaOf`, `kindOf` (`lib/config.ts`).
- Produces: `conditionOf(value): Condition | null`, `ConditionBuilder({ spec, value, disabled, onChange })`.

- [ ] **Step 1: Write the failing tests**

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  const drawer = page.getByRole("complementary", { name: "if" });
  await expect(drawer.getByRole("tab", { name: "Setup" })).toHaveAttribute("aria-selected", "true");
  await drawer.getByRole("textbox", { name: "Condition" }).fill("trigger.count > 2");
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
````

**with**:

````ts
  const drawer = page.getByRole("complementary", { name: "if" });
  await expect(drawer.getByRole("tab", { name: "Setup" })).toHaveAttribute("aria-selected", "true");
  // A condition opens in the builder (4c-2b): a formula is written in Formula mode, and choosing it changes nothing.
  await drawer.getByRole("group", { name: "How Condition is set" }).getByRole("button", { name: "Formula" }).click();
  await drawer.getByRole("textbox", { name: "Condition" }).fill("trigger.count > 2");
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  await drawer.getByRole("button", { name: "Add to Cases" }).click();
  const first = drawer.getByRole("group", { name: "Cases, item 1" });
  await first.getByRole("textbox", { name: "Condition" }).fill("true");
  await drawer.getByRole("button", { name: "Add a step after switch (case_1)" }).click(); // the drawer's twin of the canvas's "+"
````

**with**:

````ts
  await drawer.getByRole("button", { name: "Add to Cases" }).click();
  const first = drawer.getByRole("group", { name: "Cases, item 1" });
  await first.getByRole("group", { name: "How Condition is set" }).getByRole("button", { name: "Formula" }).click(); // 4c-2b
  await first.getByRole("textbox", { name: "Condition" }).fill("true");
  await drawer.getByRole("button", { name: "Add a step after switch (case_1)" }).click(); // the drawer's twin of the canvas's "+"
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  expect(options).toEqual([]);
});
````

**with**:

````ts
  expect(options).toEqual([]);
});

````

**Create** `frontend/src/routes/editor/drawer/ConditionBuilder.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { write, type Condition } from "../../../lib/builder";
import { formula } from "../../../lib/config";
import type { ScopeEntry } from "../../../lib/data";
import { IF } from "../../../test/nodeTypes";
import { fakeApi, json, NODE_ID, showFields } from "./harness";

const SITE = "00000000-0000-4000-8000-000000000002";
const steps = [
  { id: NODE_ID, key: "check", title: "If" },
  { id: SITE, key: "get_site", title: "Get a site" },
];
const OUT = "steps.get_site.output";
const entry = (path: string, over: Partial<ScopeEntry> = {}): ScopeEntry => ({
  children: false, format: null, formula: { guards: [], null_test: false, sensitive: false }, missing: false,
  name: path.split(".").at(-1)!, nameable: true, nullable: false, parent: OUT, path, problem: null, root: "steps",
  sensitive: false, step: SITE, types: ["string"], ...over,
});  // prettier-ignore
const ENTRIES = [
  entry(OUT, { name: "output", parent: null, types: ["object"], children: true }),
  entry(`${OUT}.name`),
  entry(`${OUT}.tz`, { missing: true, formula: { guards: [{ kind: "present", path: `${OUT}.tz`, size: null }], null_test: false, sensitive: false } }),
  entry(`${OUT}.count`, { types: ["integer", "null"], nullable: true, formula: { guards: [], null_test: true, sensitive: false } }),
];

beforeEach(() => {
  fakeApi({
    "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
      const at = q.get("at");
      const entries = at !== null ? ENTRIES.filter((e) => e.path === at) : ENTRIES;
      return json({ draft_revision: 1, node: NODE_ID, field: "/condition", state: "ok", reason: null, entries, more: false, problem: null });
    },
  });
});
afterEach(() => vi.restoreAllMocks());

async function pick(name: string) {
  const tree = await screen.findByRole("tree");
  await userEvent.click(within(tree).getByText(name));
}

describe("the condition builder", () => {
  it("builds a condition from data picked in the tree, and writes the formula", async () => {
    const f = showFields(IF, { steps });
    expect(screen.getByRole("button", { name: "Builder" }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("name");
    await userEvent.type(await screen.findByRole("textbox", { name: "Value, Condition 1" }), "HQ");
    expect(f.config()).toEqual({ condition: formula(`(${OUT}.name == "HQ")`) });
  });

  it("offers the operators a value's type takes, and a number only as one", async () => {
    const f = showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("count");
    const op = await screen.findByRole("combobox", { name: "Comparison, Condition 1" });
    expect(within(op).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "is", "is not", "is more than", "is less than", "is at least", "is at most", "is there", "is missing",
    ]);  // prettier-ignore
    await userEvent.selectOptions(op, "more");
    await userEvent.type(screen.getByRole("textbox", { name: "Value, Condition 1" }), "3x");
    expect(f.held()).toMatchObject([{ kind: "condition", why: "Write a number, like 3, -2 or 0.5." }]);
    await userEvent.type(screen.getByRole("textbox", { name: "Value, Condition 1" }), "{Backspace}");
    const c = `${OUT}.count`;
    expect(f.config()).toEqual({ condition: formula(`(${c} != null && (type(${c}) == type(0) || type(${c}) == type(0.0)) && ${c} > 3)`) });
    expect(f.held()).toEqual([]);
  });

  it("opens a formula it wrote as comparisons, and shows the same formula in Formula mode", async () => {
    const built: Condition = {
      match: "any",
      items: [
        { path: `${OUT}.name`, op: "starts_with", value: { kind: "text", text: "HQ-" }, guards: [], nullTest: false },
        { path: `${OUT}.tz`, op: "is_missing", value: null, guards: [{ kind: "present", path: `${OUT}.tz`, size: null }], nullTest: false },
      ],
    };
    const text = write(built)!;
    const f = showFields(IF, { steps, config: { condition: formula(text) } });
    expect(await screen.findByRole("group", { name: "Condition 2" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "any of these" }).getAttribute("aria-pressed")).toBe("true");
    await userEvent.click(screen.getByRole("button", { name: "Formula" }));
    expect(screen.getByLabelText<HTMLTextAreaElement>("Condition").value).toBe(text);
    await userEvent.click(screen.getByRole("button", { name: "Builder" }));
    expect(screen.getByRole("group", { name: "Condition 1" })).toBeTruthy();
    expect(f.config()).toEqual({ condition: formula(text) }); // switching never rewrote it
  });

  it("keeps a formula it didn't write a formula, and says why", () => {
    showFields(IF, { steps, config: { condition: formula("size(steps.get_site.output.name) > 2") } });
    const builder = screen.getByRole("button", { name: "Builder" });
    expect((builder as HTMLButtonElement).disabled).toBe(true);
    expect(document.getElementById(builder.getAttribute("aria-describedby")!)?.textContent).toMatch(/wasn't made with the builder/);
  });

  it("keeps a formula holding text JSON doesn't read a formula, and still shows the field (the review of revision 1)", () => {
    showFields(IF, { steps, config: { condition: formula('(steps.get_site.output.name == "\\x41")') } });
    const builder = screen.getByRole("button", { name: "Builder" });
    expect((builder as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole<HTMLTextAreaElement>("textbox", { name: "Condition" }).value).toBe('(steps.get_site.output.name == "\\x41")');
  });

  it("reopens \"is there\" for a list's first item as that item, so a later edit compares it (the review of revision 2)", async () => {
    const LABELS = `${OUT}.labels`;
    const guards: ScopeEntry["formula"] extends infer F ? (F extends { guards: infer G } ? G : never) : never = [
      { kind: "is_list", path: LABELS, size: null },
      { kind: "min_size", path: LABELS, size: 0 },
    ];
    const more = [
      entry(LABELS, { types: ["array", "string"] }),
      entry(`${LABELS}[0]`, { parent: LABELS, name: "[0]", missing: true, formula: { guards, null_test: false, sensitive: false } }),
    ];
    fakeApi({
      "GET /api/v1/t/t1/workflows/w1/draft/scope": (q) => {
        const at = q.get("at");
        const entries = [...ENTRIES, ...more].filter((e) => at === null || e.path === at);
        return json({ draft_revision: 1, node: NODE_ID, field: "/condition", state: "ok", reason: null, entries, more: false, problem: null });
      },
    });
    const there = write({ match: "all", items: [{ path: `${LABELS}[0]`, op: "is_there", value: null, guards, nullTest: false }] })!;
    const f = showFields(IF, { steps, config: { condition: formula(there) } });
    const op = await screen.findByRole("combobox", { name: "Comparison, Condition 1" });
    await within(op).findByRole("option", { name: "is" }); // once the value's type is known
    await userEvent.selectOptions(op, "is");
    await userEvent.type(await screen.findByRole("textbox", { name: "Value, Condition 1" }), "alpha");
    expect(f.config()).toEqual({ condition: formula(`(type(${LABELS}) == type([]) && size(${LABELS}) > 0 && ${LABELS}[0] == "alpha")`) });
  });

  it("groups comparisons one level deep, each group matching all or any", async () => {
    const f = showFields(IF, { steps });
    await userEvent.click(screen.getByRole("button", { name: "＋ Condition" }));
    await pick("name");
    await userEvent.type(await screen.findByRole("textbox", { name: "Value, Condition 1" }), "a");
    await userEvent.click(screen.getByRole("button", { name: "＋ Group" })); // its first comparison is picked with it
    await pick("tz");
    const group = await screen.findByRole("group", { name: "Group 2" });
    await userEvent.click(within(group).getByRole("button", { name: "＋ Condition" }));
    await pick("name");
    await waitFor(() => expect(within(screen.getByRole("group", { name: "Group 2" })).getAllByRole("group", { name: /^Condition 2\./ })).toHaveLength(2));
    expect(f.config()).toEqual({
      condition: formula(`(${OUT}.name == "a")\n&& ((has(${OUT}.tz) && ${OUT}.tz == "") || (${OUT}.name == ""))`),
    });
  });

  it("says a fixed true is always true, until a condition replaces it", () => {
    showFields(IF, { steps, config: { condition: true } });
    expect(screen.getByText(/Always true\./)).toBeTruthy();
  });
});
````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
});

it("keeps a formula, says how it runs, and turns a fixed value into the formula that gives it", async () => {
  const { config } = showFields(IF, {
    config: { condition: formula("trigger.n > 1") },
    expressions: [{ node: NODE_ID, field: "/condition", mode: "activity", reason: "it reads a large value" }],
````

**with**:

````tsx
});

it("keeps a formula, and says how it runs", () => {
  showFields(IF, {
    config: { condition: formula("trigger.n > 1") },
    expressions: [{ node: NODE_ID, field: "/condition", mode: "activity", reason: "it reads a large value" }],
````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
  expect(screen.getByLabelText<HTMLTextAreaElement>("Condition").value).toBe("trigger.n > 1");
  expect(screen.getByText("Runs as a separate step: it reads a large value")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Fixed" }));
  expect(config()).toEqual({});
  await userEvent.click(screen.getByLabelText("Condition")); // a checkbox now
  await userEvent.click(screen.getByRole("button", { name: "Formula" }));
  expect(config()).toEqual({ condition: formula("true") });
});

````

**with**:

````tsx
  expect(screen.getByLabelText<HTMLTextAreaElement>("Condition").value).toBe("trigger.n > 1");
  expect(screen.getByText("Runs as a separate step: it reads a large value")).toBeTruthy();
});

````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
it("offers no fixed value where the engine takes only a formula", () => {
  showFields(FILTER);
````

**with**:

````tsx
it("turns a fixed value into the formula that gives it", async () => {
  const { config } = showFields(PLAIN, { config: { count: 5 } });
  await userEvent.click(within(screen.getByRole("group", { name: "How Count is set" })).getByRole("button", { name: "Formula" }));
  expect(config()).toEqual({ count: formula("5") });
});

it("offers the builder and a formula, never a fixed value, where the engine takes only a formula", () => {
  showFields(FILTER);
````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
  expect(screen.queryByRole("group", { name: "How Keep an item when is set" })).toBeNull();
  expect(screen.getByLabelText("Keep an item when").tagName).toBe("TEXTAREA");
});

````

**with**:

````tsx
  const how = screen.getByRole("group", { name: "How Keep an item when is set" });
  expect(within(how).getAllByRole("button").map((b) => b.textContent)).toEqual(["Builder", "Formula"]); // 4c-2b
});

````

**In** `frontend/src/routes/editor/drawer/FieldView.test.tsx`, **replace**:

````tsx
  const item = screen.getByRole("group", { name: "Cases, item 1" });
  expect(within(item).getByLabelText<HTMLInputElement>("Port name").value).toBe("case_1");
  expect(within(item).getByLabelText("Condition").tagName).toBe("TEXTAREA");
});

````

**with**:

````tsx
  const item = screen.getByRole("group", { name: "Cases, item 1" });
  expect(within(item).getByLabelText<HTMLInputElement>("Port name").value).toBe("case_1");
  expect(within(item).getByRole("group", { name: "Condition" }).tagName).toBe("FIELDSET"); // the builder (4c-2b)
});

````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: FAIL: `Test Files  2 failed | 20 passed (22)`, `Tests  10 failed | 286 passed (296)`. The failing tests are
this task's new and changed ones: `builds a condition from data picked in the tree, and writes the formula`, `offers the
operators a value's type takes, and a number only as one`, `opens a formula it wrote as comparisons, and shows the same
formula in Formula mode`, `keeps a formula it didn't write a formula, and says why`, `keeps a formula holding text JSON
doesn't read a formula, and still shows the field (the review of revision 1)`, `reopens "is there" for a list's first
item as that item, so a later edit compares it (the review of revision 2)`, `groups comparisons one level deep, each
group matching all or any`, `says a fixed true is always true, until a condition replaces it`, `offers the builder and a
formula, never a fixed value, where the engine takes only a formula`, `adds a case with the first free port name`.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/routes/editor/drawer/ConditionBuilder.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// The condition builder (4c-2b, the mockups' builder board; the owner's rulings: the builder replaces Fixed for
// conditions, one level of groups, per-comparison guards with "is there" and "is missing" defined). It writes a
// formula (lib/builder.ts) and opens only one it wrote. Comparisons are picked from the data tree; each offers the
// operators its value's type takes. What can't be written yet (a number half typed, a write refused) is held whole,
// with why (ruling 18).
import { useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import {
  isGroup, NO_VALUE, numeric, OP_WORDS, opsFor, read, valueProblem, write, type Condition, type Group, type Literal,
  type Op, type Row,
} from "../../../lib/builder";  // prettier-ignore
import { formula, formulaOf, kindOf } from "../../../lib/config";
import type { ScopeEntry } from "../../../lib/data";
import { useDrawer } from "./context";
import { DataTree } from "./DataTree";
import { PillButton, usePillEntry } from "./Pill";

const EMPTY: Condition = { match: "all", items: [] };

/** The condition a field's value is, when the builder can show it: none yet, or a formula it wrote. */
export function conditionOf(value: unknown): Condition | null {
  if (value === undefined || value === null) return EMPTY;
  if (kindOf(value) === "cel") return read(formulaOf(value));
  return null;
}

/** Why a row's comparison can't be written, or null. */
const rowProblem = (r: Row): string | null =>
  NO_VALUE.has(r.op) || r.value === null ? null : valueProblem(r.value, r.path);

/** What's said under a comparison: what its guards make of missing data (the mockups' notes). */
function noteOf(r: Row): string | null {
  if (r.op === "is_there" || r.op === "is_missing") return null;
  if (r.guards.length > 0) return "If any part of its path is missing, null or another shape, this comparison is false.";
  if (r.nullTest) return "If it's null, this comparison is false.";
  return null;
}

function Match({ label, match, disabled, onChange }: {
  label: string; match: "all" | "any"; disabled: boolean; onChange: (m: "all" | "any") => void;
}) {  // prettier-ignore
  return (
    <div role="group" aria-label={label} className="inline-flex gap-px overflow-hidden rounded-lg border border-line-strong bg-line-strong">
      {(["all", "any"] as const).map((m) => (
        <button
          key={m} type="button" aria-pressed={match === m} disabled={disabled} onClick={() => match !== m && onChange(m)}
          className={`min-h-8 px-3 text-small disabled:bg-disabled-bg disabled:text-muted ${match === m ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink enabled:hover:bg-surface-hover"}`}
        >
          {m === "all" ? "all of these" : "any of these"}
        </button>
      ))}
    </div>
  );  // prettier-ignore
}

function RowView({ row, label, field, disabled, onChange, onRemove }: {
  row: Row; label: string; field: string; disabled: boolean; onChange: (r: Row) => void; onRemove: () => void;
}) {  // prettier-ignore
  const { entry } = usePillEntry(row.path, field);
  const ops = entry ? opsFor(entry.types, entry.format, entry.missing || entry.nullable || row.guards.length > 0) : [row.op];
  const problem = rowProblem(row);
  const note = noteOf(row);
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-1.5 border-t border-line py-2.5">
      <div><PillButton pill={{ ref: row.path }} entry={entry} index={0} onOpen={() => undefined} /></div>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={`Comparison, ${label}`} value={row.op} disabled={disabled}
          onChange={(e) => {
            const op = e.target.value as Op;
            const kind = (entry && numeric(entry.types)) || ["more", "less", "at_least", "at_most"].includes(op) ? "number" : "text";
            const value: Literal | null = NO_VALUE.has(op) ? null : { kind, text: row.value?.text ?? "" };
            onChange({ ...row, op, value });
          }}
          className={`${controlClass(false)} w-auto`}
        >
          {(ops.includes(row.op) ? ops : [row.op, ...ops]).map((op) => <option key={op} value={op}>{OP_WORDS[op]}</option>)}
        </select>
        {row.value !== null && (
          <input
            type="text" aria-label={`Value, ${label}`} value={row.value.text} disabled={disabled} spellCheck={false}
            aria-invalid={problem !== null} onChange={(e) => onChange({ ...row, value: { kind: row.value!.kind, text: e.target.value } })}
            className={`${controlClass(problem !== null)} w-auto min-w-0 flex-1`}
          />
        )}
        {!disabled && <Button size="sm" aria-label={`Remove ${label.toLowerCase()}`} onClick={onRemove}>×</Button>}
      </div>
      {problem && <p className="text-small text-danger">{problem}</p>}
      {note && <p className="text-meta text-muted">{note}</p>}
    </div>
  );  // prettier-ignore
}

/** A comparison of an entry picked from the tree, with its first operator. */
function rowFor(entry: ScopeEntry): Row {
  const f = entry.formula!;
  const op = opsFor(entry.types, entry.format, entry.missing || entry.nullable)[0]!;
  const value: Literal | null = NO_VALUE.has(op) ? null : { kind: numeric(entry.types) ? "number" : "text", text: "" };
  return { path: entry.path, op, value, guards: f.guards, nullTest: f.null_test };
}

export function ConditionBuilder({ spec, value, disabled, onChange }: {
  spec: { pointer: string; path: (string | number)[]; label: string; entry: boolean };
  value: unknown; disabled: boolean; onChange: (next: unknown, typed: boolean) => string | null;
}) {  // prettier-ignore
  const drawer = useDrawer();
  const held = drawer.held("condition", spec.pointer);
  const c: Condition = held?.condition ?? conditionOf(value) ?? EMPTY;
  // Where a picked comparison goes: the top, a new group (whose first it is: an empty group writes nothing), a group.
  const [adding, setAdding] = useState<number | "top" | "group" | null>(null);
  const fixed = typeof value === "boolean" ? value : null;

  /** Writes the condition when every comparison can be; else holds it whole, with why. */
  const put = (next: Condition, typed: boolean) => {
    const problem = next.items.flatMap((x) => (isGroup(x) ? x.rows : [x])).map(rowProblem).find((p) => p !== null) ?? null;
    const text = write(next);
    const why = problem ?? onChange(text === undefined ? undefined : formula(text), typed);
    if (why === null) drawer.release("condition", spec.pointer);
    else drawer.hold("condition", spec.pointer, { path: spec.path, label: spec.label, text: text ?? "", condition: next, why, entry: spec.entry });
  };  // prettier-ignore
  const setItem = (i: number, item: Row | Group, typed = false) =>
    put({ ...c, items: c.items.map((x, j) => (j === i ? item : x)) }, typed);
  const removeItem = (i: number) => put({ ...c, items: c.items.filter((_, j) => j !== i) }, false);
  const text = write(c);

  return (
    <div className="flex flex-col gap-2">
      {fixed !== null && c.items.length === 0 && (
        <p className="text-small text-muted">{fixed ? "Always true." : "Always false."} Add a condition to decide on data instead.</p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-small">True when</span>
        {/* With fewer than two, all and any write the same: the choice waits for a second. */}
        <Match label={`Match, ${spec.label}`} match={c.match} disabled={disabled || c.items.length < 2} onChange={(match) => put({ ...c, match }, false)} />
      </div>
      <div className="flex flex-col">
        {c.items.map((x, i) =>
          isGroup(x) ? (
            <div key={i} role="group" aria-label={`Group ${i + 1}`} className="flex flex-col gap-1.5 border-t border-line py-2.5 pl-4">
              <div className="flex flex-wrap items-center gap-2">
                <Match label={`Match in group ${i + 1}`} match={x.match} disabled={disabled || x.rows.length < 2} onChange={(match) => setItem(i, { ...x, match })} />
                {!disabled && <Button size="sm" onClick={() => removeItem(i)}>Remove group</Button>}
              </div>
              {x.rows.map((r, k) => (
                <RowView
                  key={k} row={r} label={`Condition ${i + 1}.${k + 1}`} field={spec.pointer} disabled={disabled}
                  onChange={(next) => setItem(i, { ...x, rows: x.rows.map((y, m) => (m === k ? next : y)) }, true)}
                  onRemove={() => setItem(i, { ...x, rows: x.rows.filter((_, m) => m !== k) })}
                />
              ))}
              {!disabled && <div><Button size="sm" onClick={() => setAdding(i)}>＋ Condition</Button></div>}
            </div>
          ) : (
            <RowView
              key={i} row={x} label={`Condition ${i + 1}`} field={spec.pointer} disabled={disabled}
              onChange={(next) => setItem(i, next, true)} onRemove={() => removeItem(i)}
            />
          ),
        )}
      </div>
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" aria-haspopup="dialog" onClick={() => setAdding("top")}>＋ Condition</Button>
          <Button size="sm" aria-haspopup="dialog" onClick={() => setAdding("group")}>＋ Group</Button>
        </div>
      )}
      {adding !== null && (
        <DataTree
          field={spec.pointer} purpose="condition" onClose={() => setAdding(null)}
          onPick={(entry) => {
            const row = rowFor(entry);
            const at = adding;
            setAdding(null);
            if (at === "top") put({ ...c, items: [...c.items, row] }, false);
            else if (at === "group") put({ ...c, items: [...c.items, { match: "any", rows: [row] }] }, false);
            else {
              const g = c.items[at];
              if (g && isGroup(g)) setItem(at, { ...g, rows: [...g.rows, row] });
            }
          }}
        />
      )}
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-small text-muted">
        <dt className="font-semibold text-ink">is there</dt>
        <dd>Present and not null, with every part of the path above it present too. Empty text, 0 and false are there.</dd>
        <dt className="font-semibold text-ink">is missing</dt>
        <dd>The opposite: it, or a part of the path above it, is absent or null.</dd>
        <dt className="font-semibold text-ink">other tests</dt>
        <dd>Each guards its own data and is false when that data is missing, so a missing value never decides a group for the others.</dd>
      </dl>
      {text !== undefined && (
        <details>
          <summary className="cursor-pointer text-small">The formula it writes</summary>
          <pre className="mt-1 overflow-x-auto rounded-lg border border-line bg-surface-2 px-3 py-2 font-mono text-meta">{text}</pre>
        </details>
      )}
    </div>
  );  // prettier-ignore
}
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
} from "./scalars";  // prettier-ignore
import { ContainerParts, PortControl, isContainer, partNames } from "./structured";
import { TextPills, type Opened } from "./TextPills";

````

**with**:

````tsx
} from "./scalars";  // prettier-ignore
import { ContainerParts, PortControl, isContainer, partNames } from "./structured";
import { ConditionBuilder, conditionOf } from "./ConditionBuilder";
import { TextPills, type Opened } from "./TextPills";

````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
type Control = (props: ControlProps) => ReactNode;
const OWN: UnappliedKind[] = ["text", "template", "json", "number", "formula", "port"]; // what a field's own control may hold
const NEITHER = "This field takes only references or text with references, which can't be set in this drawer.";
export const PILLS_NOTE = "Press / or ＋ Data to insert data from earlier steps. A dashed pill may be missing when this runs: give it a default.";
````

**with**:

````tsx
type Control = (props: ControlProps) => ReactNode;
const OWN: UnappliedKind[] = ["text", "template", "condition", "json", "number", "formula", "port"]; // what a field's own control may hold
const NEITHER = "This field takes only references or text with references, which can't be set in this drawer.";
export const PILLS_NOTE = "Press / or ＋ Data to insert data from earlier steps. A dashed pill may be missing when this runs: give it a default.";
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
const keepFocus = (e: MouseEvent) => e.preventDefault();

const startMode = (spec: FieldSpec, value: unknown): Mode =>
````

**with**:

````tsx
const keepFocus = (e: MouseEvent) => e.preventDefault();

/** A condition the builder writes (4c-2b): a formula field that gives true or false. */
const builds = (spec: FieldSpec): boolean => spec.widget === "formula" && spec.base === "boolean" && canFormula(spec);

const startMode = (spec: FieldSpec, value: unknown): Mode =>
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
  kindOf(value) === "cel" ? "formula"
  : takesPills(spec) && segmentsOf(value) !== null && value !== undefined && value !== null ? "fixed"
  : value !== undefined && value !== null ? "fixed"
````

**with**:

````tsx
  builds(spec) ? (conditionOf(value) !== null || typeof value === "boolean" ? "fixed" : "formula")
  : kindOf(value) === "cel" ? "formula"
  : takesPills(spec) && segmentsOf(value) !== null && value !== undefined && value !== null ? "fixed"
  : value !== undefined && value !== null ? "fixed"
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
    setSeen(value);
    setLocal(null);
    if (kind === "cel") setChosen("formula");
    else if (!empty) setChosen("fixed");
  }
````

**with**:

````tsx
    setSeen(value);
    setLocal(null);
    // A condition the builder can show stays in the builder: what it writes is a formula too (4c-2b).
    if (builds(spec)) setChosen((m) => (m === "fixed" && conditionOf(value) === null && typeof value !== "boolean" ? "formula" : m));
    else if (kind === "cel") setChosen("formula");
    else if (!empty) setChosen("fixed");
  }
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
  const caret = useRef<Caret | null>(null);
  const focusNext = useRef<{ segment: number; offset: number } | { pill: number } | null>(null);
  const fixedOk = canFixed(spec) || pills;
  const formulaOk = canFormula(spec);
  // What's held decides how the field shows, so a remount, an undo or a closed drawer never hides it (ruling 18).
````

**with**:

````tsx
  const caret = useRef<Caret | null>(null);
  const focusNext = useRef<{ segment: number; offset: number } | { pill: number } | null>(null);
  const builder = builds(spec);
  const buildable = builder && (conditionOf(value) !== null || typeof value === "boolean");
  const whyNotId = `${spec.pointer}-why-not-builder`;
  const fixedOk = canFixed(spec) || pills || builder;
  const formulaOk = canFormula(spec);
  // What's held decides how the field shows, so a remount, an undo or a closed drawer never hides it (ruling 18).
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
  const heldMode: Mode | null = held === undefined || held.kind === "port" ? null : held.kind === "formula" ? "formula" : "fixed";
  const mode: Mode = fixedOk && formulaOk ? (heldMode ?? chosen) : fixedOk ? "fixed" : "formula"; // the engine decides
  const stale = held !== undefined && drawer.stale(held.kind, spec.pointer);
````

**with**:

````tsx
  const heldMode: Mode | null = held === undefined || held.kind === "port" ? null : held.kind === "formula" ? "formula" : "fixed";
  // A formula the builder didn't write stays a formula (the mockups' formula board).
  const mode: Mode = fixedOk && formulaOk ? (heldMode ?? chosen) : fixedOk ? "fixed" : "formula"; // the engine decides
  const stale = held !== undefined && drawer.stale(held.kind, spec.pointer);
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
  const missing = spec.required && !spec.entry && touched && (empty || value === "") ? "Required" : null;
  const switchTo = (next: Mode) =>
    reshape(
      (current) => {
        if (next === "fixed") return kindOf(current) === "cel" ? emptyOf(spec) : current;
````

**with**:

````tsx
  const missing = spec.required && !spec.entry && touched && (empty || value === "") ? "Required" : null;
  const switchTo = (next: Mode) =>
    builder
      ? reshape((current) => current, () => setChosen(next)) // the same formula, shown the other way
      : reshape(
      (current) => {
        if (next === "fixed") return kindOf(current) === "cel" ? emptyOf(spec) : current;
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
    <>
      {fixedOk && formulaOk && !computed && !hidden && (
        <ModeSwitch label={spec.label} mode={mode} disabled={disabled} onChange={switchTo} fixedName={pills ? "Text" : "Fixed"} />
      )}
      {pills && mode === "fixed" && !disabled && drawer.revision !== null && (
````

**with**:

````tsx
    <>
      {fixedOk && formulaOk && !computed && !hidden && (
        <ModeSwitch
          label={spec.label} mode={mode} disabled={disabled} onChange={switchTo} fixedName={pills ? "Text" : builder ? "Builder" : "Fixed"}
          fixedWhyNot={builder && !buildable && held?.kind !== "condition" ? { id: whyNotId } : null}
        />
      )}
      {builder && !buildable && mode === "formula" && (
        <p id={whyNotId} className="w-full text-small text-muted">
          This formula wasn&apos;t made with the builder, so it stays a formula: the builder opens only what it wrote. Clear it to
          start one in the builder.
        </p>
      )}
      {pills && mode === "fixed" && !disabled && drawer.revision !== null && (
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
  let body: ReactNode;
  let says = false; // how its formula runs, said under it
  if (held?.kind === "template" || (mode === "fixed" && asText && !hidden && !(held && Held))) {
    // Text with data pills: what's held, or the value, as text and pills (4c-2b).
    body = frame(textPills, joined(spec.hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, PILLS_NOTE));
````

**with**:

````tsx
  let body: ReactNode;
  let says = false; // how its formula runs, said under it
  if (held?.kind === "condition" || (builder && mode === "fixed" && buildable && !(held && Held))) {
    // The condition builder (4c-2b): what's held, or the value, as comparisons.
    const runs = runsText(drawer.expressions.find((x) => x.field === spec.pointer));
    says = runs !== null;
    body = (
      <GroupFrame
        label={spec.label} required={required} hint={spec.hint} local={held?.why ?? local ?? missing} problems={problems} actions={actions}
        below={runs && <p className="text-small text-muted">{runs}</p>}
      >
        <ConditionBuilder key={generation} spec={spec} value={value} disabled={disabled} onChange={write} />
      </GroupFrame>
    );  // prettier-ignore
  } else if (held?.kind === "template" || (mode === "fixed" && asText && !hidden && !(held && Held))) {
    // Text with data pills: what's held, or the value, as text and pills (4c-2b).
    body = frame(textPills, joined(spec.hint, (held?.literal ?? kind === "literal") ? LITERAL_NOTE : null, PILLS_NOTE));
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: PASS: `Test Files  22 passed (22)`, `Tests  296 passed (296)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e/workflows.spec.ts frontend/src/routes/editor/drawer/ConditionBuilder.test.tsx frontend/src/routes/editor/drawer/ConditionBuilder.tsx frontend/src/routes/editor/drawer/FieldView.test.tsx frontend/src/routes/editor/drawer/FieldView.tsx
git commit -m "feat(editor): the condition builder, which writes a formula and opens only its own (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 10: Declassify (`DeclassifyPanel.tsx`)

The workflow's decisions on sensitive data and its declassify list, in a side panel (ruling 12): what each decision
reveals in the server's own words, declassified only once confirmed; each entry with what it reveals or why it
declassifies nothing, removable; opened from the toolbar and from "Review in Declassify…" under the field.

**Files:**
- Create: `frontend/src/routes/editor/DeclassifyPanel.test.tsx`
- Create: `frontend/src/routes/editor/DeclassifyPanel.tsx`
- Modify: `frontend/src/routes/editor/Editor.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx`

**Interfaces:**
- Consumes: `declassify`, `undeclassify`, `fieldLabel`, `Drawer.openDeclassify` (Task 5); `findNode`, `sameId`
  (`lib/graph.ts`); `SIDE` (`routes/editor/side.ts`); `Diagnostic`, `GraphDoc`, `NodeType`, `Validation`
  (`lib/workflows.ts`).
- Produces: `Site { node; field }`, `DeclassifyPanel({ doc, types, check, editable, onDeclassify, onRemove, onGo,
  onClose })`; the editor's `declassify` side panel.

- [ ] **Step 1: Write the failing tests**

**Create** `frontend/src/routes/editor/DeclassifyPanel.test.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { IF, SWITCH } from "../../test/nodeTypes";
import type { GraphDoc, Validation } from "../../lib/workflows";
import { DeclassifyPanel } from "./DeclassifyPanel";

const CHECK = "00000000-0000-4000-8000-00000000000c";
const ROUTE = "00000000-0000-4000-8000-00000000000d";
const types = new Map([["flow.if@1", IF], ["flow.switch@1", SWITCH]]);
const doc = (declassify: { node: string; field: string }[] = []): GraphDoc => ({
  graph_format: 1,
  nodes: [
    { id: CHECK, key: "check_status", type: "flow.if@1", config: {} },
    { id: ROUTE, key: "route", type: "flow.switch@1", config: {} },
  ],
  settings: { declassify },
});
const check = (over: Partial<Validation> = {}): Validation => ({
  valid: false, draft_revision: 1, expressions: [], conditional_steps: [], taint: { sites: [], declassified: [] },
  diagnostics: [], ...over,
});  // prettier-ignore
const undecided = {
  code: "taint.undeclassified", severity: "error" as const, node: CHECK, field: "/condition",
  message: "This decision reads sensitive data, so the branch taken becomes visible.",
  fix: "List it in the workflow's declassify settings, or decide on data that isn't sensitive.",
};  // prettier-ignore

function show(d: GraphDoc, c: Validation | null, editable = true) {
  const props = { onDeclassify: vi.fn(), onRemove: vi.fn(), onGo: vi.fn(), onClose: vi.fn() };
  render(<DeclassifyPanel doc={d} types={types} check={c} editable={editable} {...props} />);
  return props;
}

describe("Declassify", () => {
  it("says what a decision reveals, as the server does, and declassifies it only once that's confirmed", async () => {
    const p = show(doc(), check({ diagnostics: [undecided] }));
    const site = screen.getByRole("group", { name: "check_status · Condition" });
    expect(within(site).getByText(undecided.message)).toBeTruthy();
    const go = within(site).getByRole("button", { name: "Declassify this decision" });
    expect((go as HTMLButtonElement).disabled).toBe(true);
    await userEvent.click(within(site).getByLabelText(/may be visible in run history/));
    await userEvent.click(go);
    expect(p.onDeclassify).toHaveBeenCalledWith({ node: CHECK, field: "/condition" });
    await userEvent.click(within(site).getByRole("button", { name: "Go to the step" }));
    expect(p.onGo).toHaveBeenCalledWith(expect.objectContaining({ node: CHECK, field: "/condition" }));
  });

  it("lists the entries with what each reveals, or why it declassifies nothing, each removable", async () => {
    const entries = [{ node: ROUTE, field: "/cases/1/when" }, { node: CHECK, field: "/condition" }];
    const p = show(doc(entries), check({
      taint: { sites: [], declassified: [{ node: ROUTE, field: "/cases/1/when", reveals: "the port taken" }] },
      diagnostics: [{ code: "taint.stale_declassify", severity: "error", node: null, field: "/settings/declassify/1", message: "This entry declassifies nothing: it isn't a decision that reads sensitive data.", fix: "Remove it." }],
    }));  // prettier-ignore
    expect(screen.getByText("Declassified · 2")).toBeTruthy();
    expect(screen.getByText("route · Cases, item 2 › Condition")).toBeTruthy();
    expect(screen.getByText("Reveals the port taken.")).toBeTruthy();
    expect(screen.getByText(/declassifies nothing/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Remove check_status · Condition" }));
    expect(p.onRemove).toHaveBeenCalledWith(1);
  });

  it("offers no change where the draft can't be changed, and says decisions show once checked", () => {
    show(doc([{ node: CHECK, field: "/condition" }]), null, false);
    expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull();
    expect(screen.getByText(/show once the draft is checked/)).toBeTruthy();
  });
});
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
  expect(stepConfig("check")).toEqual({ condition: formula("false") });
  expect(screen.getByRole("button", { name: "1 edit not applied" })).toBeTruthy();
});
````

**with**:

````tsx
  expect(stepConfig("check")).toEqual({ condition: formula("false") });
  expect(screen.getByRole("button", { name: "1 edit not applied" })).toBeTruthy();
});

// 4c-2b: the steps a check says may not run (ledger ruling 116), and declassifying a decision from the toolbar.
it("declassifies a decision from the toolbar's Declassify, and the draft saves the entry", async () => {
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("a") }));
  answers.set(`POST ${BASE}/validate`, () =>
    json({
      // The revision checked: the saved one, 2 once the entry is saved (the PUT's answer).
      draft_revision: sent.some((r) => r.method === "PUT") ? 2 : 1,
      valid: false, expressions: [], conditional_steps: [], taint: { sites: [{ node: "id-a", field: "/x" }], declassified: [] },
      diagnostics: [{ code: "taint.undeclassified", severity: "error", node: "id-a", field: "/x", message: "This decision reads sensitive data, so the branch taken becomes visible.", fix: null }],
    }));  // prettier-ignore
  await show();
  await userEvent.click(await screen.findByRole("button", { name: "Declassify" }));
  const panel = screen.getByRole("complementary", { name: "Declassify" });
  await userEvent.click(within(panel).getByLabelText(/may be visible in run history/));
  await userEvent.click(within(panel).getByRole("button", { name: "Declassify this decision" }));
  await vi.waitFor(() => expect(sent.find((r) => r.method === "PUT")).toBeTruthy(), { timeout: 3000 });
  const put = sent.find((r) => r.method === "PUT")!;
  expect((put.body as GraphDoc).settings?.declassify).toEqual([{ node: "id-a", field: "/x" }]);
  expect(within(panel).getByText("Declassified · 1")).toBeTruthy();
  // Checked again after the save: the server still names the decision (the fake does), listed now: none to make.
  expect(await within(panel).findByText("Needs your decision · 0")).toBeTruthy();
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: FAIL: `Test Files  2 failed | 21 passed (23)`, `Tests  1 failed | 296 passed (297)`. The run can't import
`./DeclassifyPanel`: it doesn't exist yet. The failing tests are this task's new and changed ones: `declassifies a
decision from the toolbar's Declassify, and the draft saves the entry`.

- [ ] **Step 3: Write the code**

**Create** `frontend/src/routes/editor/DeclassifyPanel.tsx`:

````tsx
// SPDX-License-Identifier: Apache-2.0
// Declassify (4c-2b, the mockups' declassify board; engine 2b spec §4.1, §4.3): the workflow's decisions that read
// sensitive data, which make something visible in a run's history, and the ones listed as acceptable. Nothing is listed
// for the person: each is chosen, with what it reveals said first, as the server says it. A draft keeps its entries;
// publishing them needs `workflow.declassify` (the server answers).
import { useId, useState } from "react";
import { Button } from "../../components/Button";
import { fieldLabel } from "../../lib/schemaForm";
import type { Diagnostic, GraphDoc, NodeType, Validation } from "../../lib/workflows";
import { findNode, sameId } from "../../lib/graph";
import { SIDE } from "./side";

export interface Site {
  node: string;
  field: string;
}

/** A decision the person may declassify: what the server says it makes visible, with a confirmation first. */
function Undecided({ d, label, editable, onGo, onDeclassify }: {
  d: Diagnostic & Site; label: string; editable: boolean; onGo: () => void; onDeclassify: () => void;
}) {  // prettier-ignore
  const [agreed, setAgreed] = useState(false);
  const id = useId();
  return (
    <div role="group" aria-label={label} className="flex flex-col gap-2 rounded-lg border border-line-strong p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-small">{label}</span>
        <Button size="sm" onClick={onGo}>Go to the step</Button>
      </div>
      <p className="text-small">{d.message}</p>
      {editable && (
        <>
          <label htmlFor={id} className="flex items-start gap-2 text-small">
            <input id={id} type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-0.5 size-[16px] accent-accent" />
            What it reveals may be visible in run history, to anyone who can see this workflow&apos;s runs
          </label>
          <div>
            <Button size="sm" disabled={!agreed} onClick={onDeclassify}>Declassify this decision</Button>
          </div>
        </>
      )}
    </div>
  );  // prettier-ignore
}

export function DeclassifyPanel({ doc, types, check, editable, onDeclassify, onRemove, onGo, onClose }: {
  doc: GraphDoc; types: Map<string, NodeType>; check: Validation | null; editable: boolean;
  onDeclassify: (site: Site) => void; onRemove: (index: number) => void; onGo: (site: Site) => void; onClose: () => void;
}) {  // prettier-ignore
  const labelOf = (site: Site): string => {
    const node = findNode(doc, site.node);
    if (!node) return "A step no longer in the draft";
    const type = types.get(node.type);
    return `${node.key} · ${type ? fieldLabel(type, site.field) : site.field}`;
  };
  const undecided = (check?.diagnostics ?? []).filter(
    (d): d is Diagnostic & Site => d.code === "taint.undeclassified" && d.node !== null && d.field !== null,
  );
  const entries = doc.settings?.declassify ?? [];
  const noteOf = (site: Site, index: number): string | null => {
    if (!check) return null;
    const hit = check.taint.declassified.find((x) => sameId(x.node, site.node) && x.field === site.field);
    if (hit) return `Reveals ${hit.reveals}.`;
    return check.diagnostics.find((d) => d.code === "taint.stale_declassify" && d.field === `/settings/declassify/${index}`)?.message ?? null;
  };
  return (
    <aside aria-labelledby="declassify-title" className={`${SIDE} flex flex-col gap-4 overflow-y-auto p-5`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col">
          <h2 id="declassify-title" tabIndex={-1} className="text-body-lg font-semibold outline-none">Declassify</h2>
          <span className="text-small text-muted">Workflow settings</span>
        </div>
        <Button size="md" onClick={onClose}>Close</Button>
      </div>
      <p className="text-small text-muted">
        A decision that reads sensitive data shows something in the run&apos;s history: the branch taken, a loop&apos;s item
        count. List a decision here only when that&apos;s acceptable. Nothing is listed for you.
      </p>
      {check === null ? (
        <p className="text-small text-muted">The decisions that need one show once the draft is checked.</p>
      ) : (
        <section aria-labelledby="declassify-undecided" className="flex flex-col gap-2">
          <h3 id="declassify-undecided" className="text-body font-semibold">Needs your decision · {undecided.length}</h3>
          {undecided.length === 0 && <p className="text-small text-muted">No decision reads sensitive data without being listed.</p>}
          {undecided.map((d) => (
            <Undecided
              key={`${d.node}${d.field}`} d={d} label={labelOf(d)} editable={editable}
              onGo={() => onGo(d)} onDeclassify={() => onDeclassify({ node: d.node, field: d.field })}
            />
          ))}
        </section>
      )}
      <section aria-labelledby="declassify-listed" className="flex flex-col">
        <h3 id="declassify-listed" className="text-body font-semibold">Declassified · {entries.length}</h3>
        {entries.map((e, i) => (
          <div key={`${e.node}${e.field}${i}`} className="flex flex-col gap-1.5 border-t border-line py-2.5 first:border-t-0">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-mono text-small">{labelOf(e)}</span>
              {editable && <Button size="sm" aria-label={`Remove ${labelOf(e)}`} onClick={() => onRemove(i)}>Remove</Button>}
            </div>
            {noteOf(e, i) && <span className="text-small text-muted">{noteOf(e, i)}</span>}
          </div>
        ))}
      </section>
      <p className="text-small text-muted">
        You can save a draft with these entries. Publishing it needs the permission to declassify; without it, Publish says so
        and changes nothing.
      </p>
    </aside>
  );  // prettier-ignore
}
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
import { announce } from "../../lib/announce";
import { ApiError, client, ok } from "../../lib/client";
import { admission, setConfig, setOptions, unlisted, unlistedNote, valueAt, type Changed } from "../../lib/config";
import { downloadJson, fileName } from "../../lib/download";
import { ConflictError, DraftSync, type SyncState } from "../../lib/draftSync";
````

**with**:

````tsx
import { announce } from "../../lib/announce";
import { ApiError, client, ok } from "../../lib/client";
import { admission, declassify, setConfig, setOptions, undeclassify, unlisted, unlistedNote, valueAt, type Changed } from "../../lib/config";
import { downloadJson, fileName } from "../../lib/download";
import { ConflictError, DraftSync, type SyncState } from "../../lib/draftSync";
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
import { StepDrawer } from "./drawer/StepDrawer";
import { addsOf, item, type ItemAction } from "./items";
import { ProblemsPanel, type PublishProblems } from "./ProblemsPanel";
import { SaveState } from "./SaveState";
````

**with**:

````tsx
import { StepDrawer } from "./drawer/StepDrawer";
import { addsOf, item, type ItemAction } from "./items";
import { DeclassifyPanel } from "./DeclassifyPanel";
import { ProblemsPanel, type PublishProblems } from "./ProblemsPanel";
import { SaveState } from "./SaveState";
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx

/** The editor's right column: a step's panel, the problems, or the versions (Task 15). */
type Side = { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" } | { kind: "unapplied" } | null;
const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds

````

**with**:

````tsx

/** The editor's right column: a step's panel, the problems, or the versions (Task 15). */
type Side = { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" } | { kind: "unapplied" } | { kind: "declassify" } | null;
const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds

````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  const publishButton = useRef<HTMLButtonElement>(null);
  const unappliedButton = useRef<HTMLButtonElement>(null);
  const jumps = useRef(0); // each "Go to" a field, so the same one twice still focuses it
  const [landing, setLanding] = useState<{
````

**with**:

````tsx
  const publishButton = useRef<HTMLButtonElement>(null);
  const unappliedButton = useRef<HTMLButtonElement>(null);
  const declassifyButton = useRef<HTMLButtonElement>(null);
  const jumps = useRef(0); // each "Go to" a field, so the same one twice still focuses it
  const [landing, setLanding] = useState<{
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel";
    n: number;
  } | null>(null);
````

**with**:

````tsx
    on: "problems" | "versions" | "publish" | "problems-panel" | "versions-panel" | "unapplied" | "unapplied-panel" | "declassify" | "declassify-panel";
    n: number;
  } | null>(null);
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
        unapplied: () => usable(unappliedButton.current),
        "unapplied-panel": () => document.getElementById("unapplied-title") ?? usable(unappliedButton.current),
      }[landing.on]();
      target?.focus();
````

**with**:

````tsx
        unapplied: () => usable(unappliedButton.current),
        "unapplied-panel": () => document.getElementById("unapplied-title") ?? usable(unappliedButton.current),
        declassify: () => usable(declassifyButton.current),
        "declassify-panel": () => document.getElementById("declassify-title") ?? usable(declassifyButton.current),
      }[landing.on]();
      target?.focus();
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
  }, [trusted]);
  const count = (last?.diagnostics.length ?? 0) + published.length; // a stale publish finding never counts
  const [placing, setPlacing] = useState<string | null>(null); // the step the next click on the canvas puts there
  const qc = useQueryClient();
````

**with**:

````tsx
  }, [trusted]);
  const count = (last?.diagnostics.length ?? 0) + published.length; // a stale publish finding never counts
  // Declassify: shown once there's a decision to make or one listed (4c-2b).
  const listed = doc.settings?.declassify ?? [];
  const undecided = (trusted?.diagnostics ?? []).filter((d) => d.code === "taint.undeclassified");
  const [placing, setPlacing] = useState<string | null>(null); // the step the next click on the canvas puts there
  const qc = useQueryClient();
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
          </Button>
        )}
        <Button ref={versionsButton} size="md" aria-expanded={side?.kind === "versions"} onClick={() => setSide(side?.kind === "versions" ? null : { kind: "versions" })}>
          Versions
````

**with**:

````tsx
          </Button>
        )}
        {canEdit(role) && viewing === null && (undecided.length > 0 || listed.length > 0) && (
          <Button ref={declassifyButton} size="md" aria-expanded={side?.kind === "declassify"} onClick={() => setSide(side?.kind === "declassify" ? null : { kind: "declassify" })}>
            Declassify
          </Button>
        )}
        <Button ref={versionsButton} size="md" aria-expanded={side?.kind === "versions"} onClick={() => setSide(side?.kind === "versions" ? null : { kind: "versions" })}>
          Versions
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
            workflowId={workflow.id}
            revision={viewing ? null : sync.revision}
            steps={nodesOf(shownDoc).map((n) => ({ id: n.id, key: n.key, title: typeMap.get(n.type)?.title ?? null }))}
            ports={portMap.get(idKey(open.id)) ?? []}
````

**with**:

````tsx
            workflowId={workflow.id}
            revision={viewing ? null : sync.revision}
            openDeclassify={viewing || !canEdit(role) ? undefined : () => setSide({ kind: "declassify" })}
            steps={nodesOf(shownDoc).map((n) => ({ id: n.id, key: n.key, title: typeMap.get(n.type)?.title ?? null }))}
            ports={portMap.get(idKey(open.id)) ?? []}
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
              setSide(null);
              land("versions");
            }}
          />
````

**with**:

````tsx
              setSide(null);
              land("versions");
            }}
          />
        )}
        {side?.kind === "declassify" && (
          <DeclassifyPanel
            doc={doc}
            types={typeMap}
            check={trusted && {
              ...trusted,
              // A decision listed since the check isn't one to make: it shows as listed at once.
              diagnostics: trusted.diagnostics.filter((d) => d.code !== "taint.undeclassified" || !listed.some((e) => d.node !== null && sameId(e.node, d.node) && e.field === d.field)),
            }}
            editable={editable}
            onDeclassify={(site) => {
              if (change(declassify(draftNow(), site), `Declassified ${keyOf(site.node)}.`)) land("declassify-panel");
            }}
            onRemove={(i) => {
              const e = listed[i];
              if (change(undeclassify(draftNow(), i), `Removed ${e ? keyOf(e.node) : "an entry"} from Declassify.`)) land("declassify-panel");
            }}
            onGo={(site) => setSide({ kind: "step", node: site.node, field: { pointer: site.field, n: ++jumps.current } })}
            onClose={() => {
              setSide(null);
              land("declassify");
            }}
          />
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
      : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
  const Held = held && held.kind !== "template" ? heldControl(held.kind, spec) : null;
  const panel = { opened, open: setOpened, caret, focus: focusNext };
  const textPills = (c: Described) => (
````

**with**:

````tsx
      : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
  const Held = held && held.kind !== "template" ? heldControl(held.kind, spec) : null;
  // A decision that reads sensitive data (the server's taint.undeclassified, under its field): the list where it's
  // declassified is a click away (4c-2b, the builder's and the formula's boards).
  const declassifiable = drawer.openDeclassify && problems.some((d) => d.code === "taint.undeclassified") && (
    <div><Button size="sm" onClick={drawer.openDeclassify}>Review in Declassify…</Button></div>
  );
  const panel = { opened, open: setOpened, caret, focus: focusNext };
  const textPills = (c: Described) => (
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
      <GroupFrame
        label={spec.label} required={required} hint={spec.hint} local={held?.why ?? local ?? missing} problems={problems} actions={actions}
        below={runs && <p className="text-small text-muted">{runs}</p>}
      >
        <ConditionBuilder key={generation} spec={spec} value={value} disabled={disabled} onChange={write} />
````

**with**:

````tsx
      <GroupFrame
        label={spec.label} required={required} hint={spec.hint} local={held?.why ?? local ?? missing} problems={problems} actions={actions}
        below={<>{runs && <p className="text-small text-muted">{runs}</p>}{declassifiable}</>}
      >
        <ConditionBuilder key={generation} spec={spec} value={value} disabled={disabled} onChange={write} />
````

**In** `frontend/src/routes/editor/drawer/FieldView.tsx`, **replace**:

````tsx
      (c) => <FormulaControl key={generation} {...c} spec={spec} value={value} literal={false} disabled={disabled} onChange={write} />,
      spec.hint,
      runs && <p className="text-small text-muted">{runs}</p>,
    );
  } else if (container) {
````

**with**:

````tsx
      (c) => <FormulaControl key={generation} {...c} spec={spec} value={value} literal={false} disabled={disabled} onChange={write} />,
      spec.hint,
      <>
        {runs && <p className="text-small text-muted">{runs}</p>}
        {declassifiable}
      </>,
    );
  } else if (container) {
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: PASS: `Test Files  23 passed (23)`, `Tests  300 passed (300)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/DeclassifyPanel.test.tsx frontend/src/routes/editor/DeclassifyPanel.tsx frontend/src/routes/editor/Editor.test.tsx frontend/src/routes/editor/Editor.tsx frontend/src/routes/editor/drawer/FieldView.tsx
git commit -m "feat(editor): Declassify: decisions on sensitive data, each confirmed, and the list (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 11: A step that may not run (the badge)

"may not run" on a card the current check lists in `conditional_steps`, dashed, and in the card's name (ruling 13;
ledger 70, 116).

**Files:**
- Modify: `frontend/src/routes/editor/Canvas.tsx`
- Modify: `frontend/src/routes/editor/Editor.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Modify: `frontend/src/routes/editor/StepCard.test.tsx`
- Modify: `frontend/src/routes/editor/StepCard.tsx`

**Interfaces:**
- Consumes: `Validation.conditional_steps` (4c-2a).
- Produces: `StepCardBody`'s `conditional`; `StepData.conditional`; `CanvasProps.conditional: ReadonlySet<string>`.

- [ ] **Step 1: Write the failing tests**

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { onAnnounce } from "../../lib/announce";
import { cancelLeaving, mayLeave } from "../../lib/leaving";
````

**with**:

````tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { idKey } from "../../lib/graph";
import { onAnnounce } from "../../lib/announce";
import { cancelLeaving, mayLeave } from "../../lib/leaving";
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx
          data-problems={String(props.problems.size)}
          data-problem-steps={[...props.problems.keys()].join(",")}
        >
          <button data-item="start" onClick={() => props.onItem({ kind: "after", from: null })}>Start</button>
````

**with**:

````tsx
          data-problems={String(props.problems.size)}
          data-problem-steps={[...props.problems.keys()].join(",")}
          data-conditional={[...props.conditional].join(",")}
        >
          <button data-item="start" onClick={() => props.onItem({ kind: "after", from: null })}>Start</button>
````

**In** `frontend/src/routes/editor/Editor.test.tsx`, **replace**:

````tsx

// 4c-2b: the steps a check says may not run (ledger ruling 116), and declassifying a decision from the toolbar.
it("declassifies a decision from the toolbar's Declassify, and the draft saves the entry", async () => {
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("a") }));
````

**with**:

````tsx

// 4c-2b: the steps a check says may not run (ledger ruling 116), and declassifying a decision from the toolbar.
it("tells the canvas the steps the current check says may not run", async () => {
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("a", "b") }));
  answers.set(`POST ${BASE}/validate`, () =>
    json({ draft_revision: 1, valid: true, diagnostics: [], expressions: [], conditional_steps: ["id-b"], taint: { sites: [], declassified: [] } }));
  await show();
  const canvas = await screen.findByRole("group", { name: "Workflow steps" });
  await vi.waitFor(() => expect(canvas.dataset.conditional).toBe(idKey("id-b")));
});

it("declassifies a decision from the toolbar's Declassify, and the draft saves the entry", async () => {
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("a") }));
````

**In** `frontend/src/routes/editor/StepCard.test.tsx`, **replace**:

````tsx
  expect(card.className).toContain(`w-[${CARD.width}px]`);
});
````

**with**:

````tsx
  expect(card.className).toContain(`w-[${CARD.width}px]`);
});

it("says a step that may not run, in words and dashed, beside its problems (4c-2b)", () => {
  render(<StepCardBody node={node} type={TRANSFORM} problems={{ errors: 0, warnings: 0 }} separate={0} conditional current={false} tabIndex={0} onOpen={vi.fn()} />);
  const card = screen.getByRole("button", { name: "get_device, Transform, may not run" });
  const badge = Array.from(card.querySelectorAll("span")).find((s) => s.textContent?.trim() === "may not run")!;
  expect(badge.className).toContain("border-dashed");
});
````

- [ ] **Step 2: Run them to see them fail**

Run (from `frontend/`): `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: FAIL: `Test Files  2 failed | 21 passed (23)`, `Tests  133 failed | 169 passed (302)`. Every one of
`Editor.test.tsx`'s 132 tests fails on `TypeError: props.conditional is not iterable`: its canvas stub reads the set the
editor doesn't pass yet. The other failure is StepCard's new `says a step that may not run, in words and dashed, beside
its problems (4c-2b)`.

- [ ] **Step 3: Write the code**

**In** `frontend/src/routes/editor/Canvas.tsx`, **replace**:

````tsx
  problems: Map<string, Problems>; // by step id's identity (`idKey`): the server's canonical ids
  separate: Map<string, number>; // by step id's identity
  editable: boolean;
  current: string | null; // the step whose panel is open
````

**with**:

````tsx
  problems: Map<string, Problems>; // by step id's identity (`idKey`): the server's canonical ids
  separate: Map<string, number>; // by step id's identity
  conditional: ReadonlySet<string>; // the steps that may not run, by identity (ledger ruling 116)
  editable: boolean;
  current: string | null; // the step whose panel is open
````

**In** `frontend/src/routes/editor/Canvas.tsx`, **replace**:

````tsx
      const data: StepData = {
        node: n, type, ports: portsOf(n, type), connected: used.get(idKey(n.id)) ?? [], problems: p.problems.get(idKey(n.id)) ?? NONE,
        separate: p.separate.get(idKey(n.id)) ?? 0, current: p.current !== null && sameId(p.current, n.id), focusId: p.focusId,
        editable: p.editable,
        onItem: p.onItem,
````

**with**:

````tsx
      const data: StepData = {
        node: n, type, ports: portsOf(n, type), connected: used.get(idKey(n.id)) ?? [], problems: p.problems.get(idKey(n.id)) ?? NONE,
        separate: p.separate.get(idKey(n.id)) ?? 0, conditional: p.conditional.has(idKey(n.id)), current: p.current !== null && sameId(p.current, n.id), focusId: p.focusId,
        editable: p.editable,
        onItem: p.onItem,
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
type Side = { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" } | { kind: "unapplied" } | { kind: "declassify" } | null;
const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds

/** Whether a request's outcome is unknown: no answer reached the editor (the network), or a 5xx came in the API's
````

**with**:

````tsx
type Side = { kind: "step"; node: string; field?: { pointer: string; kind?: UnappliedKind; n: number } } | { kind: "problems" } | { kind: "versions" } | { kind: "unapplied" } | { kind: "declassify" } | null;
const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds
const NO_STEPS: ReadonlySet<string> = new Set();

/** Whether a request's outcome is unknown: no answer reached the editor (the network), or a 5xx came in the API's
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
    return counts;
  }, [trusted]);
  const count = (last?.diagnostics.length ?? 0) + published.length; // a stale publish finding never counts
  // Declassify: shown once there's a decision to make or one listed (4c-2b).
````

**with**:

````tsx
    return counts;
  }, [trusted]);
  // The steps that may not run, from the current check: a badge on each (ledger rulings 70, 116).
  const conditional = useMemo(() => new Set((trusted?.conditional_steps ?? []).map(idKey)), [trusted]);
  const count = (last?.diagnostics.length ?? 0) + published.length; // a stale publish finding never counts
  // Declassify: shown once there's a decision to make or one listed (4c-2b).
````

**In** `frontend/src/routes/editor/Editor.tsx`, **replace**:

````tsx
          problems={viewing ? new Map() : problems}
          separate={viewing ? new Map() : separate}
          editable={editable}
          current={panel}
````

**with**:

````tsx
          problems={viewing ? new Map() : problems}
          separate={viewing ? new Map() : separate}
          conditional={viewing ? NO_STEPS : conditional}
          editable={editable}
          current={panel}
````

**In** `frontend/src/routes/editor/StepCard.tsx`, **replace**:

````tsx

export function StepCardBody({
  node, type, problems, separate, current, tabIndex, onOpen,
}: {
````

**with**:

````tsx

export function StepCardBody({
  node, type, problems, separate, conditional = false, current, tabIndex, onOpen,
}: {
````

**In** `frontend/src/routes/editor/StepCard.tsx`, **replace**:

````tsx
  node: GraphNode; type: NodeType | undefined; problems: Problems; separate: number; current: boolean; tabIndex: number;
  onOpen: () => void;
}) {  // prettier-ignore
````

**with**:

````tsx
  node: GraphNode; type: NodeType | undefined; problems: Problems; separate: number; conditional?: boolean; current: boolean; tabIndex: number;
  onOpen: () => void;
}) {  // prettier-ignore
````

**In** `frontend/src/routes/editor/StepCard.tsx`, **replace**:

````tsx
    !problems.errors && problems.warnings ? plural(problems.warnings, "warning", "warnings") : null,
    separate ? `${plural(separate, "expression runs", "expressions run")} as a separate step` : null,
  ].filter(Boolean);
  // The open step wears a 2 px accent border all round (1c), its padding a pixel less so nothing moves; the focus ring
````

**with**:

````tsx
    !problems.errors && problems.warnings ? plural(problems.warnings, "warning", "warnings") : null,
    separate ? `${plural(separate, "expression runs", "expressions run")} as a separate step` : null,
    conditional ? "may not run" : null,
  ].filter(Boolean);
  // The open step wears a 2 px accent border all round (1c), its padding a pixel less so nothing moves; the focus ring
````

**In** `frontend/src/routes/editor/StepCard.tsx`, **replace**:

````tsx
        <span className={`block truncate text-small ${type ? "text-muted" : "text-warn-ink"}`}>{title}</span>
      </span>
      {(problems.errors > 0 || problems.warnings > 0) && (
        <span
````

**with**:

````tsx
        <span className={`block truncate text-small ${type ? "text-muted" : "text-warn-ink"}`}>{title}</span>
      </span>
      {conditional && (
        // A step a branch or a loop may skip (ledger ruling 116): said in words, dashed as data that may be missing is.
        <span aria-hidden="true" className="shrink-0 rounded-sm border border-dashed border-warn-line px-1.5 font-mono text-meta text-warn-ink">
          may not run
        </span>
      )}
      {(problems.errors > 0 || problems.warnings > 0) && (
        <span
````

**In** `frontend/src/routes/editor/StepCard.tsx`, **replace**:

````tsx
  problems: Problems;
  separate: number;
  current: boolean;
  focusId: string;
````

**with**:

````tsx
  problems: Problems;
  separate: number;
  conditional: boolean;
  current: boolean;
  focusId: string;
````

**In** `frontend/src/routes/editor/StepCard.tsx`, **replace**:

````tsx
        problems={data.problems}
        separate={data.separate}
        current={data.current}
        tabIndex={data.focusId === item.node(node.id) ? 0 : -1}
````

**with**:

````tsx
        problems={data.problems}
        separate={data.separate}
        conditional={data.conditional}
        current={data.current}
        tabIndex={data.focusId === item.node(node.id) ? 0 : -1}
````

- [ ] **Step 4: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run --testTimeout=15000 src/routes/editor`

Expected: PASS: `Test Files  23 passed (23)`, `Tests  302 passed (302)`.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck` and `npx -y pnpm@12.6.0 lint`

Expected: no error, no warning.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor/Canvas.tsx frontend/src/routes/editor/Editor.test.tsx frontend/src/routes/editor/Editor.tsx frontend/src/routes/editor/StepCard.test.tsx frontend/src/routes/editor/StepCard.tsx
git commit -m "feat(editor): a step that may not run says so on its card (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

# Milestone 4 — the browser, every check, the final checkpoint

### Task 12: The browser, every check, the final checkpoint

Four flows in the browser against the isolated stack, under the CSP, the console check and axe: a pill inserted from
the tree and its details, saved and shown again after a reload; a condition built, checked clean by the server and
opened again; a decision on sensitive data declassified from its field once confirmed; and a step a branch may skip
saying so. They prove, end to end, what Tasks 6–11's unit tests prove piece by piece, so they pass on their first run:
a failure is a defect, debugged as one (never a flow loosened to pass). Then every check, the outline's rows, the
ledger, the screenshots and a fresh review.

**Files:**
- Create: `frontend/e2e/fixtures/data.dewpoint.json` (an If on a declared trigger input, `site` and a sensitive
  `token`, whose true branch reaches a Fail step)
- Modify: `frontend/e2e/workflows.spec.ts` (four flows at the end)
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` (§2's pills line; §5's B6 and B7 rows)

**Interfaces:**
- Consumes: `importFile` and `expectAccessible` (`e2e/workflows.spec.ts`, `e2e/gate.ts`); every screen of Tasks 6–11,
  by its accessible names: the tree "Data available here", a pill `trigger › site, trigger.site, …`, the details dialog
  named by its path, "＋ Data", "＋ Condition", "Value, Condition 1", "Review in Declassify…", the panel "Declassify",
  a decision's group "check · Condition", "Declassify this decision", a card's name ending ", may not run".
- Produces: nothing later tasks use.

- [ ] **Step 1: The flows**

**Create** `frontend/e2e/fixtures/data.dewpoint.json`:

````json
{
  "format": "dewpoint.workflow",
  "format_version": 1,
  "name": "Data",
  "graph": {
    "graph_format": 1,
    "nodes": [
      {
        "id": "4c2b0001-0000-4000-8000-000000000001",
        "key": "check",
        "type": "flow.if@1",
        "config": {},
        "position": { "x": 0, "y": 140 }
      },
      {
        "id": "4c2b0001-0000-4000-8000-000000000002",
        "key": "stop_it",
        "type": "flow.fail@1",
        "config": { "message": "Stopped" },
        "position": { "x": 0, "y": 280 }
      }
    ],
    "edges": [
      { "from": { "node": "4c2b0001-0000-4000-8000-000000000001", "port": "true" }, "to": { "node": "4c2b0001-0000-4000-8000-000000000002" } }
    ],
    "settings": {
      "input_schema": {
        "type": "object",
        "properties": { "site": { "type": "string" }, "token": { "type": "string", "x-sensitive": true } },
        "required": ["site", "token"],
        "additionalProperties": false
      }
    }
  },
  "bindings": []
}
````

**In** `frontend/e2e/workflows.spec.ts`, **replace**:

````ts
  expect(options).toEqual([]);
});

````

**with**:

````ts
  expect(options).toEqual([]);
});

// 4c-2b: data pills, the data tree, a pill's details, the condition builder, Declassify, a step that may not run.
test("a text field takes a data pill from the tree, and the pill's details say what it reads", async ({ page }) => {
  await importFile(page, "Pills", "e2e/fixtures/data.dewpoint.json");
  await page.getByRole("button", { name: /^stop_it, Fail/ }).click();
  await expect(page.getByRole("group", { name: "How Message is set" }).getByRole("button", { name: "Text" })).toHaveAttribute("aria-pressed", "true");
  const text = page.getByLabel("Message", { exact: true });
  await text.click();
  await text.press("End");
  await text.pressSequentially(" at ");
  await page.getByRole("button", { name: "＋ Data" }).click();
  const tree = page.getByRole("tree", { name: "Data available here" });
  await expect(tree.getByText("site", { exact: true })).toBeVisible({ timeout: 10_000 });
  await expectAccessible(page, "drawer: the data tree");
  await tree.getByText("site", { exact: true }).click();
  const pill = page.getByRole("button", { name: /^trigger › site, trigger\.site/ });
  await expect(pill).toBeVisible();
  await pill.focus();
  await page.keyboard.press("Enter");
  const details = page.getByRole("dialog", { name: "trigger.site" });
  await expect(details.getByText("always there")).toBeVisible({ timeout: 10_000 });
  await expectAccessible(page, "drawer: a pill's details");
  await page.keyboard.press("Escape");
  await expect(details).toBeHidden();
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  await page.reload();
  await page.getByRole("button", { name: /^stop_it, Fail/ }).click();
  await expect(page.getByRole("button", { name: /^trigger › site, trigger\.site/ })).toBeVisible();
});

test("the builder writes a condition the server checks clean, and opens it again", async ({ page }) => {
  await importFile(page, "Builder", "e2e/fixtures/data.dewpoint.json");
  await page.getByRole("button", { name: /^check, If/ }).click();
  await expect(page.getByRole("group", { name: "How Condition is set" }).getByRole("button", { name: "Builder" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "＋ Condition" }).click();
  await page.getByRole("tree", { name: "Data available here" }).getByText("site", { exact: true }).click();
  await page.getByRole("textbox", { name: "Value, Condition 1" }).fill("HQ");
  await expectAccessible(page, "drawer: the condition builder");
  // The server's own check of what the builder wrote: no problem left on the step.
  await expect(page.getByRole("button", { name: "check, If", exact: true })).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("Escape"); // closes the drawer
  await page.getByRole("button", { name: "check, If", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Value, Condition 1" })).toHaveValue("HQ");
});

test("a decision on sensitive data is declassified from its field, once confirmed", async ({ page }) => {
  await importFile(page, "Declassify", "e2e/fixtures/data.dewpoint.json");
  await page.getByRole("button", { name: /^check, If/ }).click();
  await page.getByRole("button", { name: "＋ Condition" }).click();
  await page.getByRole("tree", { name: "Data available here" }).getByText("token", { exact: true }).click();
  await page.getByRole("textbox", { name: "Value, Condition 1" }).fill("x");
  await page.getByRole("button", { name: "Review in Declassify…" }).click({ timeout: 10_000 });
  const panel = page.getByRole("complementary", { name: "Declassify" });
  const site = panel.getByRole("group", { name: "check · Condition" });
  await expect(site.getByText("This decision reads sensitive data, so the branch taken becomes visible.")).toBeVisible();
  await expectAccessible(page, "editor: Declassify");
  await site.getByLabel(/may be visible in run history/).check();
  await site.getByRole("button", { name: "Declassify this decision" }).click();
  await expect(panel.getByText("Declassified · 1")).toBeVisible();
  // Checked again: a decision on sensitive data runs as a separate step, and has no problem left.
  await expect(page.getByRole("button", { name: "check, If, 1 expression runs as a separate step", exact: true })).toBeVisible({ timeout: 10_000 });
});

test("a step a branch may skip says it may not run", async ({ page }) => {
  await importFile(page, "Branches", "e2e/fixtures/data.dewpoint.json");
  await expect(page.getByRole("button", { name: /^stop_it, Fail, may not run$/ })).toBeVisible({ timeout: 10_000 });
  await expectAccessible(page, "editor: a step that may not run");
});
````


- [ ] **Step 2: The browser gate**

From the repository, on the isolated stack (a fresh database and rebuilt images, about 4 minutes):

```bash
UI4_WT=<the worktree> <scratchpad>/compose-ui4a/e2e.sh
```

Expected: `37 passed`: the 33 flows already on main and the four new ones. Every flow, the four new ones included,
passes under the CSP and the console check, and each
`expectAccessible` finds no WCAG 2.2 AA violation.

- [ ] **Step 3: Every check**

From `frontend/`: `npx -y pnpm@12.6.0 test`, `typecheck`, `lint`, `check:api`, `build`. Then
`git diff --stat origin/main -- backend` (nothing: the backend is untouched, so its suite doesn't run), and local
CodeQL on the branch's head (`<scratchpad>/codeql/scan.sh <sha>`, about 40 s).

Expected: unit `Test Files  62 passed (62)`, `Tests  813 passed (813)`; typecheck, lint and `check:api` clean; the build
succeeds; no backend change; no new CodeQL
alert. A failure is read and fixed test-first, or reported as it is: never a claim that every check passes when one
didn't.

- [ ] **Step 4: The outline**

In `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md`:
- in §2's 4c, the pills line's "(a popover, never on hover alone)" becomes "(in the drawer's flow under its field,
  never on hover alone: 4c-2b ruling 2, ledger 126)";
- §5's B6 row adds, after "and validate's `conditional_steps`": "; its screens in 4c-2b: the data tree, pills, the
  builder, the badge";
- §5's B7 row adds, after "slot 0045 `run_step_connections`": "; its screen in 4c-2b: a pill's details".

- [ ] **Step 5: The ledger**

Append `### 4c-2b, milestone 3 (<date>)` (Tasks 9–11: their commits, the unit suite's count as run, mid-slice rulings
M66 onward, or none) and `### 4c-2b, milestone 4 and the final checkpoint (<date>)` (the flows, each check's result as
run, the screenshots taken, every mid-slice ruling, anything deferred). Each mid-slice ruling in 4b's form: a bold
statement, then why, then the test that pins it.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md
git commit -m "test(e2e): data pills, the builder, Declassify and the badge in the browser; the ledger (4c-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: The final checkpoint**

1. Screenshots, against the isolated stack after a reset, light and dark, at 1280 and 320 px: Milestone 2's (a text
   field with pills, the tree, a pill's details with a sample's states), and the builder with a group, a formula the
   builder didn't write, Declassify with a decision and an entry, and a card that may not run. Put them beside the
   mockups' boards in the session's checkpoint page.
2. A fresh reviewer, on the most capable model, with this plan, the outline's §2 and §6, the ledger's rulings 113–138
   and M65 onward, the mockups, the diff from `origin/main`, and its own scratch directory (it deletes only its own
   files). It reviews the code against the plan and the Review Focus first; the screens against the mockups, with no AI
   tells; accessibility; secrets (no sensitive value shown, no draft or sample in browser storage).
3. Critical and important findings are fixed test-first, in one pass, each a mid-slice ruling; minor ones are listed.
4. **Stop.** Give the owner the summary, the checkpoint page, the branch's head, each check's result as it came out,
   the rulings made and the minors deferred. Nothing is pushed and no PR is opened without the owner's OK; CI on a PR
   runs the backend (about 16 minutes), the frontend, CodeQL and the Compose e2e: say so before pushing.

## Self-review

- **Spec coverage.**
  - Outline §2, 4c:
    - "/" and "＋ Data" open the upstream tree (B6), with types and the always/conditional markers: Tasks 6 and 8
      (rulings 5 and 8), the markers from the scope's guards (Task 3);
    - a pill's details on focus and Enter, never on hover: the redacted sample, its run, connection, time and
      staleness (B7): Tasks 7 and 8 (ruling 9), in the drawer's flow rather than a popover (ruling 2, which Task 12
      writes into the outline);
    - the condition builder to CEL (D18), formula mode behind the switch, the class badge with its reason: Tasks 4 and
      9 (rulings 10 and 11); how the formula runs, 4c-1's note, is said under the builder as under a formula;
    - the declassify list, with what each site reveals: Task 10 (ruling 12). Trigger setup stays 4c-3 (the owner's
      ruling in "Owner, 4c-2 mockups and plan shape").
  - Ledger ruling 70, the conditional badge: Task 11 (ruling 13).
  - The owner's ten adopted recommendations: one text and pill editor as a text field's fixed mode (Task 8, ruling 3);
    conditional pills dashed, with a default (Tasks 7 and 8); "Add a default…" a visible button (Task 7); the untyped
    trigger's typed path, and a declared input schema honoured (Task 6); samples only in a pill's details (Task 7);
    alternatives merged (4c-2a); the builder replaces "Fixed" (Task 9); one level of groups (Tasks 4 and 9);
    per-comparison guards, "is missing" and "is there" defined (Tasks 4 and 9); keys a reference can't name shown
    disabled (Task 6).
  - D17 (answers carry their revision): Task 3's query keys and its check of the revision answered, Tasks 6–8. D18 (the
    server decides): guards, types and
    reveals are read, never re-derived (Tasks 3, 4, 10). D19 (the browser checks only what a save would refuse): the
    builder's number and text checks (Task 4). D20 (redacted values): Tasks 3 and 7. D23 (non-modal, CSP): ruling 2,
    and the gate in Task 12. §6 (no AI tells): the guard in every suite run, and the final review.
- **Placeholders.** None in code: every code step has its code, generated from a staged run and applied again from
  this text. What the executor fills is what only execution knows: the ledger's dates, the accepted revision, the
  branch's base and head, and each check's result as it came out.
- **Names across tasks.** Each task's commit was typechecked in the staged run and again in the dry run, so every name
  a task consumes is the one an earlier task produces:
  - `segmentsOf`, `valueOf`, `insertPill`, `removePill`, `withDefault`, `replacePill`, `withText`, `segmentsText`,
    `parsePath`, `headOf`, `pillText` (Task 2) are what `unapplied.ts` (Task 5), the tree, the details and the text
    editor (Tasks 6–8) call;
  - `scopeQuery`, `samplesQuery`, `typeWords`, `tagsOf`, `groupOf`, `whyMissing`, `previewAt` (Task 3) are what the
    tree, `usePillEntry` and the details read (Tasks 6 and 7);
  - `Condition`, `isGroup`, `valueProblem`, `write`, `read`, `opsFor`, `rowCel`, `guardCel` (Task 4) are what the held
    `condition` (Task 5) and the builder (Task 9) use;
  - `Drawer.revision`, `Drawer.steps`, `Drawer.openDeclassify`, `takesPills`, `fieldLabel`, `declassify`,
    `undeclassify` (Task 5) are what Tasks 6–10 read;
  - `refusal` and `DataTree` (Task 6) are what the text editor and the builder open; `usePillEntry` and `PillButton`
    (Task 7) are what both show a pill with;
  - `conditional` (Task 11) runs from `Validation.conditional_steps` (4c-2a) through `CanvasProps` to
    `StepCardBody`.
- **Review Focus.** Each line names the tests that pin it, in their owning tasks (1, 3, 4, 5, 6, 7, 8, 9, 10 and 12);
  every name was checked against the test files.
- **What the dry run showed.** Revision 3's per-task commits were built again from the fixed prototype on origin/main
  6f4ddec7 (main with #84), each typechecked, linted and its tests passing. The plan's own text, applied from scratch to
  a detached worktree at 6f4ddec7 by a script that reads this file as an executor would, made those commits' tree
  exactly; each Step 2 failed and each Step 4 passed as their Expected lines say (those lines are its output); the whole
  unit suite then passed, 813 of 813. The browser gate passed on that tree with #84's backend, 37 of 37. Task 1's engine
  check printed the scope's guards as its Expected line says, 23 `OK` and `problems: 0` on merged main ("is not empty"
  as `size(x) != 0` among them), and the device's `BAD` line on main before #84. While revision 2 was checked, a 4b
  test, `says when the latest edits aren't saved`, failed twice at Task 10's state, then passed in every one of 28 later
  runs (at Task 10, on the final tree and on main): intermittent, cause not found, reported to the owner apart from this
  plan.
