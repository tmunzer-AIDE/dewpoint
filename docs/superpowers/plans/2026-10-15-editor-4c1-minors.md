# The step drawer's deferred minors (issue #73)

Branch `fix/editor-4c1-minors` from `origin/main` 4c729417, on the owner's choice of #73 (2026-10-15). A plan for the
owner's rulings; nothing is built until the owner's go, and nothing is committed without it. Executed inline: the
checkpoint is after the fresh review.

**Goal:** the eight minors the final review of 4c-1 deferred (ledger M55): no typed limit is lost or blocks an edit
when a type has a config property named `options`, a number is read only as decimal, a list's or a map's view state
stays with what it was set on, every control has its own name and a label that names it, the drawer's disabled look
is under the contrast check, Escape closes the drawer as Close does, and a Go to doesn't announce the heading first.

**Architecture:** frontend only. A held limit gets a pointer outside the config's (`lib/unapplied.ts`,
`drawer/ErrorHandling.tsx`); typed numbers pass a decimal pattern (`lib/unapplied.ts`, `lib/csv.ts`); list items and
map entries are keyed by what they are (`drawer/structured.tsx`); names, labels and a contrast pair
(`drawer/LiveOptions.tsx`, `drawer/pickers.tsx`, `styles/tokenNames.ts`); the drawer's Escape and first focus
(`drawer/StepDrawer.tsx`). No backend change, no API change, no `ENGINE_ABI` bump.

## Facts (checked 2026-10-15 at 4c729417; reproduced by a throwaway probe where marked)

- **Held edits** are keyed by step, kind and pointer (`unappliedId`); a config edit's pointer is a JSON pointer into the
  step's config, a limit's is `/options/<name>` (`drawer/ErrorHandling.tsx:30`), the key's is `""`. `within(node,
  pointer)` (`lib/unapplied.ts:57`) picks the edits at a pointer and below by prefix, whatever their kind. It serves a
  field's Clear (`discard`, `FieldView.tsx:200`; "Clear drops what's typed in it too, on purpose") and every
  restructure (`restructureStep`, `Editor.tsx:790`: the edits inside are applied first, and one that can't be stops
  it).
- **Probe:** on a type whose config has a list named `options`, "25" typed in Attempts is held (`limit
  /options/max_attempts`); Clear on `options` drops it, typed text gone without asking; Add to `options` is refused
  with the limit's reason ("A whole number from 1 to 20."), the list unchanged. Today 319 installed node types have
  87 distinct top-level config properties, none named `options`; a plugin installed later may declare one (the
  manifest allows any name). The recovery file (`unappliedFile`) writes a limit's pointer as its `at`, so a limit and
  a config field named `options` read alike there; nothing reads the file back.
- **Probe:** `parseNumber` (`lib/unapplied.ts:104`, every typed number in the drawer, the Triggers panel's fields,
  CSV defaults, schedule forms) reads `0x10` as 16, `0b11` as 3 and `0o7` as 7, through `Number()`; `1_000` is
  refused; `Infinity` is refused as "too large". `bytesOf` (`lib/csv.ts:137`, a CSV file's largest size in MB) calls
  `Number()` the same way. The condition builder already reads only JSON numbers (`builder.ts` `JSON_NUMBER`).
- **Probe:** list items and map entries are keyed by index (`structured.tsx:64`, `:156`). With three object items and
  the second shown as JSON, removing the first leaves the JSON view at the second place, now the third item.
  `FieldView` keeps `asJson`, `touched` (a required field's "Required"), `generation` and the mode chosen for an empty
  value in state; it resets only `local` and the mode when the value at its pointer changes. A held edit is safe
  already: it's keyed by pointer and applied only where its lineage still is (ruling 18).
- **Lineage** (`config.ts` `rootOf`): an edit in place keeps a list's root; a move, a removal, a JSON edit or an import
  gives the list a new one; an undo brings back the old list, with its old root. A map entry's rename keeps its place
  (`renameEntry`) and writes a new map.
- **"Show choices"** (`LiveOptions.tsx:110`) is the visible text and the whole name of every live-options button: a
  screen reader's list of buttons shows several alike.
- **Pickers** (`pickers.tsx`): while loading, when the list failed, and with nothing to choose, `ConnectionControl`
  and `WorkflowControl` render a `<p>` (or `Failed`'s), so the field's `<label for>` names no element; with the
  `x-dewpoint-connection` marker missing (a field marked `x-widget: connection` only, `schemaForm.ts:121`), it says
  "No  connection yet: an admin adds one." (two spaces, no kind). The drawer shows a value it doesn't edit as an
  `<output id>`, which a label names and Go to skips (`Formula.tsx:77`, `FieldView.tsx:339`, `StepDrawer.tsx` `locate`).
- **Contrast:** the drawer draws disabled controls, and the Formula and builder mode toggles, as `muted` on
  `disabled-bg` (`StepDrawer.tsx:41`, `Formula.tsx:63`, `ConditionBuilder.tsx:49`): a viewer reads a step there. The
  review measured 6.0:1 light and 6.7:1 dark. `PAIRS` (`styles/tokenNames.ts:63`, checked by `tokens.test.ts` and
  drawn by the specimen) lacks the pair.
- **Escape vs Close:** both call the same `onClose` (`StepDrawer.tsx:171`, `:199`). JSON, a port's name and a map
  entry's name apply when focus leaves their region (`FieldView.tsx:401`, `structured.tsx:103`). A click on Close
  moves focus first, so the region's blur applies the edit; Escape unmounts the drawer with focus still inside, and
  React fires no blur on unmount, so the edit stays held (counted, applied at the next exit). Two #77 tests rely on
  that (`holdChangedCase`, `Editor.test.tsx:1428`). The Triggers panel writes its JSON as it's typed, and its field
  editor applies a name on Escape itself (`FieldEditor.tsx:119`).
- **First focus:** the drawer focuses its heading when it mounts (`StepDrawer.tsx:93`); a Go to (Problems,
  Declassify, the edits not applied) mounts it with `focusField` and lands on the field a frame later, so the heading
  is announced, then the field. The Triggers panel skips its heading while a Go to is pending
  (`TriggersPanel.tsx:16`). A field still loading (a picker's list) is waited for (`locate` answers "loading").

## Proposed rulings

- Ruling 1 (a limit's pointer), recommended option A: a held limit's pointer is `#/options/<name>`, outside the
  config's pointers (which start with `/`), so no config pointer's Clear or restructure covers it; the whole step's
  (`""`: a delete, the step's own discard) still does; the recovery file's `at` says the same, so a limit no longer
  reads as a config field. Built from one helper (`limitPointer`) - cost if wrong: none (held edits live in memory
  only; the file is never read back).
  Option B, for comparison: the pointer stays, and `within` skips a step's limits at any pointer but `""`: the same
  effect, the file still ambiguous, and a rule by kind that must except the Triggers panel's limits, which live in
  settings at real pointers.
- Ruling 2 (numbers): a typed number is decimal only: an optional sign, digits with an optional fraction, an optional
  exponent (`12`, `-3`, `2.5`, `.5`, `1e3`); `0x10`, `0b11`, `0o7`, `Infinity` and `1_000` get the field's message as
  any other text that isn't a number ("A number, like 42 or 2.5." / "A whole number, like 42."), and stay held. The
  same for the CSV size (`bytesOf`). Leading zeros read as today (`007` is 7) - cost if wrong: none (no notation but
  decimal was ever meant).
- Ruling 3 (a list's items, a map's entries): what a field shows of itself (as JSON, "Required" once left, the mode
  chosen for an empty value) stays with what it was set on, never with the place:
  - A list's items start afresh when the list is rebuilt (a move, a removal, an addition, a JSON edit, an undo to
    another list), keyed by the list's lineage; an edit in place keeps them. Their Move and Remove buttons stay where
    they are, so focus after a move is unchanged. An undo that draws afresh the part focus was in gives focus to the
    drawer's heading, never the page (the review).
  - A map's entries are keyed by name, and a rename made in the entry's name field carries its key, so the entry
    keeps its view and focus through it (Enter, or Tab into its own controls); a removal passes nothing to the next
    entry. Its own name typed again (spaces aside) is let go, never applied as a rename (the review).
  - Cost if wrong: after a move or a removal, a list's other items lose a JSON view they had open (a click to reopen).
- Ruling 4 (live options): each "Show choices" button is named "Show choices: <field label>", its visible text first
  (WCAG 2.5.3) - cost if wrong: none.
- Ruling 5 (pickers): while loading, after a failure and with nothing to choose, the picker's message is an
  `<output>` with the field's control id, so the label names it (loading keeps `data-loading`, so a Go to still waits;
  a failure keeps its Try again inside). A field without the connection marker says "This field doesn't say which kind
  of connection it takes." - cost if wrong: none.
- Ruling 6 (contrast): `muted` on `disabled-bg` joins `PAIRS` at 4.5:1 (text: a viewer reads a step's values there),
  so a token change can't break it unseen - cost if wrong: none.
- Ruling 7 (Escape): Escape in the drawer leaves the field it's in, as a click on Close does, then closes: what applies
  when focus leaves (JSON, a port's name, a map entry's name) applies, or stays held with why, or asks (a port taken
  away, ruling 9). The two #77 tests that used Escape to leave a valid edit held (`holdChangedCase`) now see Escape
  apply it: they check the declassify removal shown above the canvas once Escape has applied the edit and closed the
  drawer (`lostElsewhere`), and that an export or a publication after it keeps showing it. Every way out of the drawer
  then applies such an edit first, so an exit applying a valid edit typed in a closed drawer is left only for one a
  write refused at the time (a save conflict) - cost if wrong: none (it's Close's behavior).
- Ruling 8 (a Go to's first focus): a drawer opened by a Go to doesn't focus its heading; the field takes focus once it
  renders. While the field is still loading, the heading holds focus until it comes (today's order there). A drawer
  opened otherwise focuses its heading, as today. The Triggers panel's way - cost if wrong: none.

## Not in scope

- Focus after Move up/Move down stays on the pressed button's place, which then holds the other item (today's
  behavior; not in #73).
- A Go to whose field is a link (a picker's "Add one in Connections") lands on "Problems with this step", as today.
- Rejecting `options` as a config property name in plugin manifests (ruling 1 makes it harmless).

## Global constraints

- Test-first, each test watched failing; each protection mutation-checked (ruling 6's pair passes today: its
  protection is checked by a mutant token instead). Frontend: `lint`, `typecheck`, `check:api`, the whole test suite,
  `build`, run as `./node_modules/.bin/{eslint,tsc,vitest,vite}` (no pnpm on this machine; `node_modules` is an APFS
  clone of a lock-matched one, nothing installed).
- No backend file changes: the backend suite isn't run (it exercises nothing here); the owner may ask for it. The
  browser flows run in CI's e2e job.
- The UI's wording rules: no AI tells; messages say what happened and what to do.

## Review focus (inputs no rule above names; each pinned by a test in the task that owns it)

1. A type with a config map or list named `options`: Clear, Add, Remove, Move and an entry's rename there while a limit
   is held leave the limit held, never applied or dropped by them; deleting the step still discards it - Task 1.
2. `0x10` typed in a step's number field, an Attempts limit, a Triggers field, a CSV default and the CSV size: held with
   the field's message, never written as 16 - Task 2.
3. A map entry renamed with Tab into its own controls: focus stays where Tab took it, and its JSON view stays open -
   Task 3.
4. Escape with JSON that takes a port with edges away: the question opens, as Close's does; Escape with JSON that
   doesn't parse: held, with why - Task 5.
5. A Go to a field whose picker is still loading: the heading holds focus, then the field; never focus lost to the
   page - Task 5.

## Tasks

### Task 1: a limit's own pointer (ruling 1)

**Files:** modify `frontend/src/lib/unapplied.ts` (`limitPointer`, the `pointer` comment),
`frontend/src/routes/editor/drawer/ErrorHandling.tsx`; tests `frontend/src/lib/unapplied.test.ts`,
`frontend/src/routes/editor/drawer/ErrorHandling.test.tsx`.

- [ ] Tests: `within(step, "/options")` doesn't cover a held limit, `within(step, "")` does; in the drawer harness, a
  type whose config has a list `options`: "25" typed in Attempts, then Clear on `options` keeps it held (its text and
  reason), Add/Remove/Move in `options` succeed with it held and leave it so; the recovery file's `at` for a limit is
  `#/options/max_attempts`; a held limit's Go to still opens the error handling at it. Watch them fail.
- [ ] Code: `export const limitPointer = (name: Limit) => \`#/options/${name}\``; `ErrorHandling` uses it; `locate`
  keeps reading the name after the last `/`.
- [ ] Mutation-check: the old pointer back; `within` given a `#` prefix match.

### Task 2: decimal numbers only (ruling 2)

**Files:** modify `frontend/src/lib/unapplied.ts` (`parseNumber`), `frontend/src/lib/csv.ts` (`bytesOf`); tests
`unapplied.test.ts`, `frontend/src/lib/csv.test.ts`, `drawer/FieldView.test.tsx`, `drawer/ErrorHandling.test.tsx`.

- [ ] Tests: `parseNumber` refuses `0x10`, `0b11`, `0o7`, `Infinity`, `1_000`, `1e`, `.`, `+`, with the whole/any
  messages, and still reads `12`, ` 12 `, `-3`, `2.5`, `.5`, `5.`, `1e3`, `007`, and past 2^53 as before;
  `bytesOf("0x2")` is null and `bytesOf("2.5")` 2.5 MB; in the drawer, `0x10` typed in a number field and in Attempts
  is held with its message and never written. Watch them fail.
- [ ] Code: `const DECIMAL = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/`, tested before `Number()` in both.
- [ ] Mutation-check: the pattern removed; the exponent or the fraction dropped from it.

### Task 3: items and entries keyed by what they are (ruling 3)

**Files:** modify `frontend/src/routes/editor/drawer/structured.tsx`; test `drawer/FieldView.test.tsx` (or a new
`structured.test.tsx` beside it).

- [ ] Tests, lists: an object item shown as JSON, the item before it removed: no item shows as JSON; the same after a
  move, and after an undo to the list before; typing in an item keeps its JSON view (an edit in place); an object
  item's required property left empty ("Required"), the item before it removed: the item now there shows no
  "Required"; a list of text items behaves the same. Maps: an entry shown as JSON, the entry before it removed: the
  entry keeps its JSON view and the next shows none; a rename with Enter keeps focus in its name and its JSON view; a
  rename with Tab into its value keeps focus on the value's control. Watch them fail.
- [ ] Code: `ListItems` keys each item's `FieldView` by the list's lineage (`rootOf`, numbered in a module
  `WeakMap`), its row by index as now; `MapEntries` keys each entry's row by an id kept per name, and `NameField`
  carries the id to the new name when its rename is applied.
- [ ] Mutation-check: the list key back to the index; the rename's carry removed.

### Task 4: names, labels and a contrast pair (rulings 4, 5, 6)

**Files:** modify `frontend/src/routes/editor/drawer/LiveOptions.tsx`, `drawer/pickers.tsx`,
`frontend/src/styles/tokenNames.ts`; tests `drawer/LiveOptions.test.tsx`, `drawer/pickers.test.tsx`,
`styles/tokens.test.ts` (through `PAIRS`), `specimen/Specimen.test.tsx` (its count follows `PAIRS`).

- [ ] Tests: two live-options fields give two buttons, "Show choices: Site" and "Show choices: Device"; the
  connection and workflow pickers' label names a control while loading, after a failure (Try again still inside)
  and with nothing to choose; a field without the marker says its own sentence, never "No  connection". Watch them
  fail. The contrast pair: added, then a mutant `--muted` in `tokens.css` under 4.5:1 on `disabled-bg` must fail it.
- [ ] Code: `aria-label`; an `<output id={id} aria-describedby={describedBy}>` for each message state; the pair.
- [ ] Mutation-check: each label dropped; the `<output>` back to a `<p>`.

### Task 5: Escape and the first focus (rulings 7, 8)

**Files:** modify `frontend/src/routes/editor/drawer/StepDrawer.tsx`; test `frontend/src/routes/editor/Editor.test.tsx`
(the two `holdChangedCase` tests rewritten).

- [ ] Tests: Escape with valid JSON typed in a field applies it (the draft has it, nothing held) and focuses the step
  on the canvas; with JSON that doesn't parse, it's held with why and counted; with a map entry's name typed, the entry
  is renamed; with JSON taking a port with edges away, the question opens. A Go to from Problems: the heading never
  takes focus (focus events recorded), the field does; a Go to a loading picker: the heading holds focus until the
  list comes, then the field; a step opened by a click: the heading has focus, as before. The two `holdChangedCase`
  tests rewritten as ruling 7 says. Watch them fail.
- [ ] Code: Escape blurs the focused element inside the drawer before `onClose`; the heading's mount focus is skipped
  when `focusField` is set, and the Go to's first frame focuses the heading when its field is still loading.
- [ ] Mutation-check: the blur removed; the heading's skip removed; the loading hold removed.

### Task 6: the record

- [ ] The ledger (`2026-10-05-editor-ui-4-ledger.md`): "4c-1's deferred minors, fixed (#73)", pointing here. This
  plan's record: the build, the runs, the review, the checkpoint.

Then a fresh-context review hunting typed text lost, an edit applied where it wasn't typed, and focus lost or announced
twice; fixes test-first; the frontend's whole run (lint, typecheck, `check:api`, all tests, build); gitleaks; local
CodeQL (JavaScript); a checkpoint. Commits, push and the PR each on the owner's go.

## Build (2026-10-15, on the owner's "go, build it with option A"; uncommitted until the owner's go)

Tasks 1 to 5 built test-first at 4c729417, each new test watched failing for its reason; a test that pins what a change
must keep (an edit in place keeps a JSON view, a rename keeps focus, the heading holds focus while a field loads)
passes before the change and is said to be a guard, each one killed by a mutant. Mutation checks: 24 mutants, all
killed.
- Task 1 (ruling 1): `limitPointer` (`#/options/<name>`), used by `ErrorHandling`. On a type with a config list named
  `options`, Clear keeps a held "25" in Attempts, and Add, Move and Remove there work with it held.
- Task 2 (ruling 2): `DECIMAL` in `config.ts`, gating `parseNumber` and `bytesOf`; `0x10` is held with its message in
  a number field, in Attempts, in a CSV column's default and in the CSV size.
- Task 3 (ruling 3): items keyed by the list's lineage, entries by an id per name. Found while building: an id shared
  by the old and new names gave two rows one key when the old name came back beside the new one (a JSON edit), React's
  duplicate-key error; the id is moved, never shared.
- Task 4 (rulings 4 to 6): "Show choices: <label>"; the pickers' `Said` (`<output id>`); the pair. Its control: with the
  pair taken out of `PAIRS`, a darkened `disabled-bg` passes all 140 token and specimen tests; with it, it's caught.
- Task 5 (rulings 7, 8): Escape blurs first; the heading's mount focus skipped on a Go to, held while it loads. The two
  `holdChangedCase` tests became `closeOnChangedCase` (ruling 7).
- Tests adapted to the new names: the live-options tests name "Show choices: Site"; the picker tests and the e2e flow
  (`workflows.spec.ts`) wait for the combobox, since the label names the loading message too.

## Review (2026-10-15, a fresh-context reviewer, probes deleted)

One High, two Medium and four Low findings; rulings 1, 4 and 6 had none. Fixed test-first, each failing first, 5 more
mutants all killed (31 in all):
- High: an entry's own name typed again with a space, then left, deleted its id (`renameEntry` changes nothing, the
  carry took that for a rename), so its row was drawn afresh: focus lost, keys dropped. The edit is now let go (as the
  Key field does), and the id is moved by taking it first.
- Medium: an undo from a control inside a list's item (or a renamed entry's row) drew that part afresh and left focus
  on the page (the editor leaves focus in a surviving panel). A frame later, a control gone gives focus to its panel's
  heading.
- Medium: `DECIMAL`'s `\d+\.?\d*` backtracked over every split of a run of digits: 48 ms at 10,000 digits, 721 ms at
  40,000, on each keystroke. Now `\d+(\.\d*)?`, the same strings in linear time; a test reads 30,000 digits three ways
  under 250 ms (1.8 s before).
- Low: a connection field without its kind hid a value it had, and a required one couldn't be cleared: the sentence
  shows only with no value.
- Low: an addition starts a list's items afresh too: said in ruling 3 and the code, pinned by a test.
- Low: Attempts' text was matched to its value by `Number()`, so "0x10" meant 16 there after an undo: `parseNumber`.
- Low, open: a rename that re-sorts a map (names that read as integers: "5" to "10" in {1, 5, 9}) moves the row's
  element, which a real browser's focus doesn't survive (jsdom's does, so no test can fail first). Before, focus stayed
  on the wrong entry. Left for the owner: a browser check, or a refocus of the moved element a frame later.
- The Tab test's last check compared an element with itself; it now checks focus is one of the renamed entry's own
  controls (alone, it kills both of Task 3's map mutants).

## Runs (2026-10-15, uncommitted tree)

- Frontend: lint, typecheck, `check:api`, 73 files and 1,040 tests (twice), build: pass. The first whole run after the
  review's fixes failed one new Triggers test: it clicked the CSV size field before Done's focus frame landed; it now
  waits for it, as its neighbour does.
- Local CodeQL, JavaScript (CI's CLI 2.27.2 and javascript-queries 2.4.7, 89 queries): 0 findings at main and on this
  tree. gitleaks (8.30.1) on the diff and the new files: no leaks.
- Not run: the browser e2e (CI's job; one of its flows changed, above) and the backend suite (no backend change).

## Sign-off (2026-10-15)

The owner, at the checkpoint: "1. yes 2. yes 3. yes 4. yes": rulings 1 to 8 signed off, with option A for ruling 1 and
ruling 3's additions from the review; the commit; the frontend's runs above as the full suite (the backend's isn't run:
no backend file changes); push and a pull request. The open Low (a map re-sorted by a rename, in a real browser) stays
open, as the review section says.
