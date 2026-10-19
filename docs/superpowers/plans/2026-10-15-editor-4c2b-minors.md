# The step drawer's data: deferred minors (issue #85)

Branch `fix/editor-4c2b-minors` from `origin/main` c5b63da5, on the owner's choice of #85 (2026-10-15). A plan for the
owner's rulings; nothing is built until the owner's go, and nothing is committed without it. Executed inline: the
checkpoint is after the fresh review.

**Goal:** the seven minors the final review of 4c-2b deferred: the condition builder compares a value of no known type
with a number when the person means one, its pill opens what a pill opens elsewhere, the Declassify panel closes on
Escape, the pills note is shown only where its controls are, ← in the data tree reaches a value's group, the tree's
search waits for the person to stop typing, and "/" is seen working in a real browser.

**Architecture:** frontend only. The builder (`lib/builder.ts`, `drawer/ConditionBuilder.tsx`), the Declassify panel
(`DeclassifyPanel.tsx`), a field's note (`drawer/FieldView.tsx`), the data tree (`drawer/DataTree.tsx`), and one browser
flow (`e2e/workflows.spec.ts`). No backend change, no API change, no `ENGINE_ABI` bump.

## Facts (checked 2026-10-15 at c5b63da5)

- **The builder's "is" on a value of no known type** (`ConditionBuilder.tsx:74`, `rowFor` at `:99`): a comparison's
  value is a `Literal` of kind `number` or `text`, written `p == 3` or `p == "3"` (`builder.ts` `literalCel`) and read
  back with its kind (`literalOf`). The kind comes from the value's types: `numeric(types)` (`builder.ts:72`) is true
  only when every type is a number. The scope gives no type (`types: ()`, "any value": a schema without one, such as a
  step's output field the step doesn't describe) or several (`["integer", "string"]`); `numeric` is then false, so "is"
  and "is not" write text, and no control chooses otherwise: `count is 3` writes `count == "3"`.
- **The runtime** (installed cel-expr-python, checked with `engine/cel/runtime.py`): `x == 3` is false for `"3"`,
  `null` or `true`, never an error, and true for `3.0`; `x == "3"` is false for `3`; `!=` is the negation. So either
  kind is safe to write: the wrong one silently never matches.
- **The builder's pill** (`ConditionBuilder.tsx:68`) is a `PillButton` with `onOpen={() => undefined}`: it says "has
  popup dialog" (`Pill.tsx:61`, `aria-haspopup="dialog"`) and opens nothing. In text, a pill opens `PillDetails` (type,
  when it runs, a past run's sample, a default, Replace…, Remove); `defaults={false}` leaves the default out.
- **Declassify** (`DeclassifyPanel.tsx:72`) has no Escape; Problems, Versions, the edits not applied and the drawer
  close on it (`ProblemsPanel.tsx:56`: `onKeyDown` Escape, `stopPropagation`, `onClose`). Its Close lands focus with
  `land("declassify")` (`Editor.tsx`).
- **The pills note** (`FieldView.tsx:28`, shown at `:311`): "Press / or ＋ Data to insert data from earlier steps. A
  dashed pill may be missing when this runs: give it a default." "＋ Data" shows only when the field is editable and the
  drawer isn't a version's (`:222`, `!disabled && drawer.revision !== null`; a draft always has a revision), and "/"
  opens the tree only when editable (`TextPills.tsx:77`); a viewer and a version's view see the note anyway.
- **← in the data tree** (`DataTree.tsx:256`): it closes an open item, else moves to the item's parent when that is
  shown. A root whose fields show directly under its group (a step's output, the trigger's input) isn't shown, so ← on
  one of those fields does nothing; ↑ reaches the group. The ARIA tree pattern's ← moves to the parent item.
- **The tree's search** (`DataTree.tsx:170`): each keystroke is a new query key, so a request per character (answers
  are cached per revision: the cost is bounded). Nothing in the frontend debounces yet; `draftSync.ts` times its saves
  with `setTimeout`.
- **"/"** (`TextPills.tsx:80`): keydown "/" opens the tree in a microtask, so the browser types the "/" into the field
  first; a pick replaces it, Escape keeps it. Unit tests (`TextPills.test.tsx:74`) type it through jsdom; the browser
  flows use "＋ Data" (`e2e/workflows.spec.ts:674`). Whether a real browser types the "/" before the tree takes focus
  hasn't been observed.

## Proposed rulings

- Ruling 1 (a value of no known type), recommended option A: where a value's type isn't one (none, or several of which
  one is a number), "is" and "is not" show a choice beside the value, "as text / as number" (pressed as the builder's
  "all of these / any of these" is). It follows what's typed (a number as JSON writes it, like `3`, `-2` or `0.5`, is a
  number; anything else is text) until the person picks one; then it stays. A comparison read back from its formula
  keeps the kind written (picked). The formula's shape doesn't change. A value of one type behaves as today - cost if
  wrong: none for typed values; an untyped "is 007" stays text, as JSON has no such number.
  As built (the review): the builder remembers which comparisons it made, by place (a removal moves the places after
  it); a condition changed from elsewhere (an undo, Formula) forgets them, so every comparison then keeps its kind. The
  previous revision's facts stand in while a save's are asked, so the choice stays on screen and what's typed follows.
  Every space typed is kept: "3 " is text.
  Option B, for comparison: no choice; a number-like value on an untyped "is" writes both, `(p == 3 || p == "3")`
  ("is not": `p != 3 && p != "3"`): it matches either without asking, the formula grows, and reading it back needs a
  new pattern.
- Ruling 2 (the builder's pill), recommended option A: it opens its details, as in text, without the default (the
  comparison's own guards decide missing data): the type, when it runs, a past run's sample; Replace… opens the tree
  and puts the picked value in this comparison (its operator and value kept when the new value takes that operator,
  else its first operator, as a new comparison starts); Remove removes the comparison, as its ×. Option B: a pill that
  isn't a button - cost if wrong: none.
- Ruling 3 (Declassify): Escape closes it, as the other panels; focus goes where its Close sends it. As built (the
  review): its heading takes focus as it opens, as the other panels' do, so Escape works at once - cost if wrong: none.
- Ruling 4 (the pills note): "Press / or ＋ Data to insert data from earlier steps." shows only where they work (an
  editable draft); "A dashed pill may be missing when this runs: give it a default." there too; in a version's view and
  for a viewer: "A dashed pill may be missing when this runs." - cost if wrong: none.
- Ruling 5 (← in the data tree): ← on a value shown directly under its group (a root's field, a root shown itself, a
  search's result) moves to the group, as the tree pattern's parent - cost if wrong: none.
- Ruling 6 (the search): the tree asks 250 ms after the last keystroke; an emptied search asks at once; the list shown
  meanwhile is the last answer - cost if wrong: a quarter second before results. As built: moving into the tree drops
  a search still waiting (else its "Loading" would replace the list under the focus); back in the search box, what it
  holds is asked (the review).
- Ruling 7 ("/" in a browser): a browser flow types "/" in a text field: the tree opens with an empty search, a pick
  replaces the "/" with the pill, Escape keeps the "/". It runs in CI's e2e job, as the other flows do (locally only if
  the owner asks for the Compose stack). It checks behavior that exists, so it can't be watched failing first: if CI
  fails it, that's the bug the review suspected, fixed test-first then - cost if wrong: none.

## Not in scope

- An untyped value's ordering operators (`is more than`…) are numbers already (`NUMBER_TEST` guards them).
- The data tree's search box itself (its placeholder, its `maxLength`).
- 4d-1's ten minors (unfiled) and #81/#89.

## Global constraints

- Test-first, each test watched failing; each protection mutation-checked. Frontend: `lint`, `typecheck`, `check:api`,
  the whole test suite, `build`, run as `./node_modules/.bin/{eslint,tsc,vitest,vite}` (no pnpm on this machine;
  `node_modules` is an APFS clone of a lock-matched one, nothing installed).
- No backend file changes: the backend suite isn't run. The browser flows run in CI's e2e job.
- The UI's wording rules: no AI tells; messages say what happened and what to do.

## Review focus (inputs no rule above names; each pinned by a test in the task that owns it)

1. A value of several types, one a number (`["integer", "string"]`): the choice shows; of one type (`["string"]`,
   `["integer", "null"]`): it doesn't, as today - Task 1.
2. A condition written before (`x == "3"` on an untyped value) reopened: it shows "as text", and typing more never flips
   it - Task 1.
3. "is" changed to "contains" and back on an untyped value: text for "contains"; back on "is", the kind follows the text
   again unless the person picked one - Task 1.
4. Replace on a comparison inside a group: it stays in its group, at its place, and focus lands on its operator - Task 2.
5. ↓ pressed in the search before the next answer: it moves into the list shown (the last answer), and Enter picks what's
   shown, never an error - Task 4.

## Tasks

### Task 1: a value of no known type (ruling 1)

**Files:** modify `frontend/src/lib/builder.ts` (`Row.auto`, a `kindFor(types, text, auto)` helper),
`frontend/src/routes/editor/drawer/ConditionBuilder.tsx` (`RowView`'s choice, `rowFor`, the operator change); tests
`frontend/src/lib/builder.test.ts`, `frontend/src/routes/editor/drawer/ConditionBuilder.test.tsx`.

- [ ] Tests: on an untyped value, "is" with `3` typed writes `x == 3` and shows "as number" pressed; with `HQ`, `x ==
  "HQ"` and "as text"; picking "as text" with `3` writes `x == "3"` and typing `4` keeps text; a reopened `x == "3"` stays
  text when edited; "is not" the same; review focus 1 and 3; a typed value shows no choice and writes as today. Watch
  them fail.
- [ ] Code: `Row.auto?: boolean` (UI only, never written: `write(read(f))` is still `f`), set by `rowFor` for an untyped
  value; while set, the kind follows the text (`JSON_NUMBER`); the choice clears it.
- [ ] Mutation-check: the choice's condition; the follow; the pin.

### Task 2: the builder's pill opens its details (ruling 2)

**Files:** modify `ConditionBuilder.tsx` (an opened-details state per row; `PillDetails` with `defaults={false}`;
Replace through the tree); test `ConditionBuilder.test.tsx`.

- [ ] Tests: the pill opens its details (type, when it runs), Escape and Close give focus back to the pill; Replace…
  picks another value, keeping the operator and the value when the new value takes it, else its first operator, and
  focus lands on its operator; Remove removes the comparison and focus goes where × sends it; review focus 4; a viewer
  sees the details without Replace or Remove. Watch them fail.
- [ ] Code, then a mutation check: the details not opened; Replace not keeping the operator.

### Task 3: Escape in Declassify, and the pills note (rulings 3, 4)

**Files:** modify `frontend/src/routes/editor/DeclassifyPanel.tsx`, `drawer/FieldView.tsx` (`PILLS_NOTE` split);
tests `DeclassifyPanel.test.tsx`, `frontend/src/routes/editor/Editor.test.tsx` (focus after Escape), `drawer/FieldView.test.tsx`.

- [ ] Tests: Escape closes Declassify and focus goes where Close sends it; an editable draft's text field says the whole
  note; a viewer's and a version's say only "A dashed pill may be missing when this runs.". Watch them fail.
- [ ] Code, then a mutation check: the Escape handler; the note's condition.

### Task 4: the data tree (rulings 5, 6)

**Files:** modify `frontend/src/routes/editor/drawer/DataTree.tsx`; test `drawer/DataTree.test.tsx`.

- [ ] Tests: ← on a field shown under its group moves to the group; on a nested field, to its parent as today; on a
  search's result, to its group. With fake timers: typing `time` quickly asks once, 250 ms after the last key; an
  emptied search asks at once; review focus 5. Watch them fail.
- [ ] Code: ← falls back to the row's group; the query reads a debounced copy of the search (`setTimeout`, cleared on
  each change and on unmount).
- [ ] Mutation-check: the group fallback; the delay; the emptied search's immediacy.

### Task 5: "/" in a browser (ruling 7)

**Files:** modify `frontend/e2e/workflows.spec.ts` (a flow beside "a text field takes a data pill from the tree").

- [ ] The flow: in the fixture's `stop_it` step's Message, type " /": the tree opens with focus in an empty search;
  pick `site`: the field holds the pill where the "/" was, no "/" left; type " /" again and press Escape: the "/" stays.
  Lint and typecheck it; it runs in CI's e2e job.

### Task 6: the record

- [ ] The ledger (`2026-10-05-editor-ui-4-ledger.md`): "4c-2b's deferred minors, fixed (#85)", pointing here. This plan's
  record: the build, the runs, the review, the checkpoint.

Then a fresh-context review hunting a condition that writes another comparison than the one shown, focus lost or
announced twice, and a search or a pick landing on the wrong value; fixes test-first; the frontend's whole run (lint,
typecheck, `check:api`, all tests, build); gitleaks; local CodeQL (JavaScript); a checkpoint. Commits, push and the PR
each on the owner's go.

## Build (2026-10-15, on the owner's "go, build it with option A for both"; uncommitted until the owner's go)

Tasks 1 to 5 built test-first at c5b63da5, each new test watched failing for its reason (a few that pin what a change
must keep pass first, each killed by a mutant). Mutation checks over the build and the review's fixes: 32 mutants, all
killed; five survived on the way, each then pinned by a test (the details' default, the list during the wait, the
quarter second) or its code made simpler (a redundant branch, a redundant clause).
- Task 1 (ruling 1): `eitherKind`, `kindOfText` (`builder.ts`); `CompareAs`, the following places (`ConditionBuilder.tsx`).
- Task 2 (ruling 2): the builder's pill opens `PillDetails` (`defaults={false}`); Replace… through a tree in the row,
  `replaced` keeping the operator and the value when the new value takes the operator.
- Task 3 (rulings 3, 4): Declassify's Escape and first focus; `PILLS_SEEN` for a viewer and a version's view.
- Task 4 (rulings 5, 6): ← to the group; the search's quarter second.
- Task 5 (ruling 7): the "/" browser flow, beside the "＋ Data" one. Not run here: it runs in CI's e2e job.

## Review (2026-10-15, a fresh-context reviewer, probes deleted)

Three High, three Medium and three Low findings, all fixed test-first:
- High: a comparison's open details or Replace tree stayed with the row's index: removed, the next comparison
  inherited it, and a Replace pick could rewrite a comparison never chosen. The builder now keeps one open panel, by
  place, closed by any removal and by ＋ Condition (which also ends two trees open at once, a Low).
- High: "as text / as number" left the screen at every save (this revision's facts are asked again), taking the focus
  to the page and stopping what's typed from following. The previous revision's facts stand in meanwhile.
- High: a space typed after a number was lost ("3 apples" written "3apples"): what's typed is read untrimmed.
- Medium: the pin didn't hold as ruled ("then it stays"): the build had kept it in the formula (a kind set against the
  text), which a cleared value or an operator change undid. The builder now remembers the comparisons it made; a pick
  ends following; a comparison read back keeps its kind.
- Medium: a search dropped as the tree was entered was never asked, even back in the search: it is now.
- Medium: Escape didn't close Declassify right after it opened (focus stayed on the toolbar): its heading takes focus.
- Low: the quarter second wasn't pinned (a 20 ms delay passed): a fake-timer test checks 249 and 250 ms. A dead branch
  in `replaced` removed, its test renamed. The browser flow checks the "/" in the field before the pick, and that the
  tree has focus before Escape.

## Runs (2026-10-15, uncommitted tree)

- Frontend: lint, typecheck, `check:api`, 90 files and 1,223 tests (twice at the end), build: pass. Two of the new
  search tests failed once each in a whole run: typed through user-event, a key could come more than a quarter second
  after the last under the run's load, so a search was asked (correctly) before the test expected; each now types its
  search in one change, drives the timers it needs, and waits for that search's own answer (five runs of the file
  pass).
- Local CodeQL, JavaScript (CI's CLI 2.27.2 and javascript-queries 2.4.7, 89 queries): 0 findings at main and on this
  tree. gitleaks (8.30.1) on the diff and the plan: no leaks.
- Not run: the browser e2e (CI's job; the new "/" flow and every other) and the backend suite (no backend change).

## Sign-off (2026-10-19)

The owner, at the checkpoint: "1. sign-off 2. yes 3. yes 4. yes": rulings 1 to 7 signed off, with option A for rulings
1 and 2 and the additions the review brought (rulings 1, 3 and 6, as built); the commit; the frontend's runs above as
the full suite (the backend's isn't run: no backend file changes); push and a pull request. Main had moved on since
the build (13 commits, 4e-1 among them): the branch is rebased onto it (00cbbad9; the ledger's end merged by hand)
and checked again before the push: lint, typecheck, `check:api`, 1,327 tests (twice) and the build pass.
