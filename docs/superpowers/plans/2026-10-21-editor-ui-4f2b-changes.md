# Editor UI 4f-2b: an update's changes, a create's settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1, 2026-10-21.** Nothing is built before the owner accepts this plan. Nothing is pushed and no PR is
opened without the owner's OK in chat.

**Goal:** The second half of the Mist step design: an update's body drawn as **Changes** (how they're sent, a row per
setting it sets or clears, Find a setting, only the parts given), a create's as **Settings** (its required settings
first), a device's body asking for its kind first, at 1280 and 320 px.

**Architecture:**
- **Where:** `settingsOf` finds a config whose root says `x-widget: "update"` (with `body`, `mode` taking merge and
  replace, `clear` a list) or `"create"` (with `body`), and puts those parts on Setup (ruling 98 amended for them);
  else the generic form. `schemaForm.ts` gains a union's branches, its title, its kind and what's offered (not what
  Mist sets, not the kind).
- **The widget is the drawer's own fields:** `Changes.tsx` draws one `FieldView` of the body ("Changes" or
  "Settings", List | Formula) whose parts are rows, each row's setting a `FieldView` too, told by new `Drawn` options
  how to draw (`group`, `startFixed`, `fixedName`, `shown`, `name`, `actions`, `hideClear`, `switchLabel`). What's
  typed, held, refused or computed behaves as everywhere in the drawer, and what the widget can't draw shows today's
  control (ledger 102).
- **One write each:** Set, Clear and Keep change `body` and `clear` in one `restructure` of the whole config
  (`lib/changes.ts`), one step of Undo; `setConfig` prunes the objects a write empties in such a body, so an empty
  object is never sent (with replace, one would reset its setting).
- **Memory above the tabs:** what the changes remember until the drawer closes (a value set before it was cleared, a
  setting or part added with nothing given, an update's kind, a map's new entry) lives in `StepDrawer`, which the tabs
  don't unmount.
- **Find a setting** (`lib/settingsIndex.ts`, `FindSetting.tsx`): every setting a body offers, through its objects, a
  map's entries and a list's items, built once per body and kind; **given parts** (`GivenParts.tsx`): an object's,
  a map entry's or a list item's parts given, "＋ Another setting of …".

**Tech Stack:** React 19, TanStack Query 5, Tailwind v4 tokens; Vitest and Testing Library (no jest-dom); Playwright
against the Compose stack, with axe. Frontend only: the plugin's metadata (titles, `x-widget`, union titles) is on
main since 4f-2a.

**Spec:** `docs/superpowers/specs/2026-10-21-editor-4f2-mist-step-design.md` (on main since #137): §3 (the
corrections), §5.3–§5.11, §6, §8 (calls 5–19). The boards: "4f-2 Mist Step Mockups" v8 (Main, FindSetting,
CreateDevice, States, MainDark, MoreStates, Narrow320Light, Narrow320Dark), signed off at v7. Facts: R6
(`~/4_dev/mist_dewpoint-4f-notes/R6-changes-widget-facts.md`).

## How this plan was checked

The plan's code was checked before review on a scratch checkout of main at a4b677ab, never on a branch. Each
task's diffs were applied as written, in order:
- the test diff alone, then the task's tests: they failed as its "Run them" step says;
- then the implementation diff and the same tests: they passed;
- after every task, the frontend's static checks (`tsc -b --noEmit`, ESLint): silent;
- after the last, the tree matched the prototype the diffs were cut from, file for file (tree 54e9fc38);
- the 18 diff blocks, taken from this file's own text, are the diffs applied, byte for byte, in order;
- on the final tree: the whole frontend suite (1577 passed, 114 files; main has 1518 in 110), ESLint, the build and
  `check:api` (as their scripts' own commands: the scratch checkout borrows its packages through a link, which pnpm
  refuses to run scripts from); and CodeQL (CLI 2.27.2, CI's filter; python-queries 1.8.13, javascript-queries
  2.4.8): no finding.

The e2e spec (Task 10) was type-checked and linted, not run: it needs the Compose stack, which Task 10 asks the owner
about. The executor still runs every step: the check is evidence, not a substitute.

## Global Constraints

- **No backend change.** No route, migration, ABI change or step version; the plugin's metadata is 4f-2a's.
- **No new dependency.** No npm package is added; no third-party JavaScript or CDN asset: everything is bundled, under
  the strict CSP, with no inline script or style.
- **No real Mist call, no real data (D24).** The unit tests use made-up `acme.*` types shaped as Mist's (`UPDATE`,
  `CREATE`, `DEVICE_UPDATE`, `DEVICE_CREATE`); the browser spec writes real Mist steps without a connection.
- **Opening the drawer never rewrites a draft** (ledger 102): nothing is written on render; what's added and not given
  is remembered, never written (a list's new item excepted: its place is the person's).
- **One step of Undo per change**; a typed edit held under a row is dropped by Clear and Keep, applied first by Set.
- **Words first, the boards' copy as the spec corrects it** (§3, §5.5). Where neither has words, the rulings give them.
- **No AI tells** (`src/test/aiTells.test.ts`): matched words bold and underlined, never coloured.
- **WCAG 2.2 AA**, light and dark, at 1280 and 320 px: the changes a fieldset; how they're sent and a device's kind
  radio groups; Set | Clear a group of two pressed buttons; Find a combobox with a listbox and an active descendant;
  targets at least 24 px, 44 px below 640 px (in pixels: a rem is 14 px here).
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker. Nothing is pushed and no PR is opened
  without the owner's OK in chat. Ask before any local run expected over 10 minutes (the e2e spec on a local Compose
  stack).

## Review Focus

The inputs and conditions most likely to bite a person using this that the design implies but its own lists don't
name. Each is pinned by the test named, in the task that owns the code.

1. **Removing the last part of an object.** The object isn't sent empty (with replace it would reset the setting); its
   row stays, saying nothing is given. Task 3: `removes each object a write empties, up to the body's setting`; Task
   8: `takes a part off with Remove, never Clear; a setting emptied keeps its row, nothing given`.
2. **A draft the list can't draw** (a `clear` naming what isn't offered, `mode` or the body held as a formula). Never
   rewritten; today's control. Task 6: `leaves a \`clear\` naming what the list doesn't offer to today's control,
   unchanged`, `leaves how they're sent, held as a formula, to its formula, its switch named for it`, `draws a body a
   formula gives as a formula, its cleared settings still listed`.
3. **A problem at a setting the list doesn't draw** (a read-only `id` written through the API). Shown on the changes,
   never lost. Task 6: `keeps a problem at a setting the list doesn't draw on the changes`.
4. **A device's kind changed with changes the new kind lacks.** They're dropped and named; an update's kind isn't
   sent. Task 9: `reads an update's kind from its settings, offers that kind's, and says what a change of kind keeps
   and drops`.
5. **A map entry's key empty or taken.** Refused with why; nothing written. Task 8: `draws a map's entries by key, a
   new one's key first, a setting found in one too`.

## Rulings (proposed; they join the ledger as 341 onward when the owner accepts the plan)

Each says what was decided, why, and what it costs if wrong. Found while building the prototype the diffs come from.

1. **Milestone pauses** after Task 4 (the form's foundations), Task 7 (the changes' list and Find) and Task 9 (parts,
   kind, Settings); then Tasks 10–11 and a fresh reviewer. Cost: none.
2. **Where the changes draw** (§5.3, §5.6): `settingsOf` returns `changes` when the root says `update` and the config
   has `body`, `mode` (enum with merge and replace) and `clear` (a list), or says `create` and has `body`; those leave
   Setup's and Options' lists, Setup draws them after its required fields (each "(required)"), `onSetup` holds them (Go
   to, counts), Options says "The changes are on Setup." or "The settings are on Setup.". Else the generic form
   (ruling 100). Cost: none.
3. **A union, its kind, what's offered** (§5.7): `branchesOf` (an `anyOf`/`oneOf` of two or more, each at the union's
   place, labelled by its own title), `unionTitle` (its `$ref` target's: the entry's "Body" hides it), `kindOf` (the
   setting every branch allows one distinct string in: `type`), `offeredOf` (a group's properties without `readOnly`
   ones and the kind's), `isReadOnly`. Cost: a union of objects without such a setting keeps the generic form.
4. **No empty object sent** (§5.3; call 8): `setConfig` prunes, for an `update` or `create` type and a path under
   `body`, each object the write emptied, from where it landed up to the top-level setting; a list's item stays (its
   place is the person's), the body stays. It catches held edits too (applied through `setConfig`). Never on render.
   Cost: an object emptied by hand in such a body goes with it.
5. **What the drawer's own fields are told** (`Drawn`): `group` (a union drawn as a group of `parts`), `startFixed`
   (empty, in Fixed: a union is Set as JSON), `fixedName` ("List"), `shown` (the parts drawn: a problem at another stays
   on the group), `name` (the setting's raw name under its label, in the code face, on rows only: §5.10, call 19),
   `actions`, `hideClear`, `switchLabel`; a group's frame takes `warn` and `below`; a formula's frame keeps `below`.
   Cost: eight optional props.
6. **Rows and one write each** (`lib/changes.ts`): a row per setting in a plain `body`, named in a plain `clear` or
   added (`pending`), the ones the schema describes; `set`, `clear`, `pending` or `both`; required ones first (a
   create's), then by title (stored JSON keeps no key order). Set, Clear and Keep: one `restructure` of the whole config
   (`path: []`), `clear` removed when emptied; Clear and Keep drop what's typed under the row first. Cost: a key the
   schema doesn't describe isn't drawn (its problem shows on the changes).
7. **Memory above the tabs**: `StepDrawer` holds `Memory` (values cleared, settings added, parts and entries opened,
   an update's kind, the list open, a map's new entry), merged by functional update (two in one action both land);
   it lasts until the drawer closes or another step opens. Cost: reopening forgets a pick not given a value.
8. **The body is its own field** (§5.8): "Changes" (or "Settings") is the body's `FieldView`, List | Formula; a body
   held as a formula, a reference or a literal stays one; with a formula, how they're sent and the cleared settings stay
   listed under it, with "Computed when the step runs: …". Cost: none.
9. **How they're sent** (§5.5): a radio pair, "Merge with the current settings" (checked when unset; nothing written
   until chosen) and "Replace them", stacked below 640 px; merge's words muted, replace's in warn ink; its own Fixed |
   Formula switch named "How the way they're sent is set". Cost: copy.
10. **A row's controls and words** (§5.3, §5.6): Set | Clear a group of two pressed buttons, "What happens to Rogue";
    "Keep Rogue as it is"; a create's "Remove Enabled", none on a required setting; a cleared row "Sent empty: Mist
    removes this setting."; added, nothing given, "Nothing given yet: it isn't sent." (not on a create's required ones);
    both set and cleared, the spec's words, Set or Clear settling it. Cost: copy.
11. **How many; nothing to change** (§5.3, §5.9): "3 of 93 settings change; the others stay as they are." (a create:
    "… settings given; Mist uses its defaults for the others."), counting the settings sent or cleared of those offered;
    "Nothing to change yet: …" in warn ink on the changes when an update's plain body sets and clears nothing. Cost:
    copy.
12. **Find a setting** (§5.4; call 10): the index per body and kind (cached by type) leaves out what Mist sets, the
    kind, and the inside of a secret or a cut setting; through a map "an entry" (`port_usages.*.mode`), a list "an
    item" (`networks[].name`); every word typed in the titles, raw path or description; a title or raw match before a
    description-only one, top-level first, then by titles; at most 50; nothing typed: the top-level settings. A
    combobox ("Find a setting by its name or what it does"), Up, Down, Enter, Escape; "· In Changes" (or Settings).
    Added: Set with nothing given (remembered), each object on its way opened, focus to it. Cost: a word must appear
    whole in order inside a field's words.
13. **An object's given parts** (§5.3; calls 9, 17): the parts given and those added, by title, each with "Remove …"
    (never Clear); "＋ Another setting of Rogue" opens Find over its own (focused); an object picked there opens its
    own; a Remove that empties the setting keeps its row (nothing given). Under an object row, merge's or replace's
    words. Cost: none.
14. **A map's entries** (§5.3; call 16): by key ("Port usages › trunk"), each by its given parts, "Remove Port usages
    › trunk"; "＋ Add an entry" asks "Name of the new entry" first, refused empty or taken ("Port usages has an entry
    named trunk already."), remembered until a part is given; a Find hit through a map asks the key, then opens the
  part.
    Cost: an entry opened and left empty is forgotten on close.
15. **A list's items** (§5.3; call 16): by number ("Networks › item 2"), each by its given parts, Move up, Move down,
    Remove; "＋ Add an item" writes `{}` (its place is the person's); "A list is sent whole: …" under it. Cost: an empty
    item is sent until removed.
16. **A secret, a union** (§5.8): a setting that is itself `x-sensitive` stays one field (formula only); a union starts
    in Fixed as JSON in its row, "As JSON: Mist takes it in more than one shape.". Cost: none.
17. **A device's kind** (§5.7; call 18): "Kind of device" (the union's title), a radio group of the branches' titles;
    an update's from its `type` held in the draft, else the kind chosen here, else the first that has every setting
    listed, else the first; a create's only from its `type` ("Choose the kind first: its settings follow.", nothing
    else until picked). A change keeps the changes the new kind has, drops the others, writes `type` where it's held (a
    create, a draft that has it), and says it: "Kind changed to Switch: Name is kept; Height is dropped, as a Switch
    doesn't have it.". Cost: an update's kind isn't saved (read back from its rows).
18. **A create's required settings** (§5.6): first, in the schema's order, given or not, no Remove, no "isn't sent".
    The kind's required `type` is the kind's to write. Cost: none.
19. **Read only** (§5.9): "Merge with the current settings · 3 changes" (a create: "3 settings given"), then a line
    per row: "set: Enabled yes, Min rogue RSSI -80", "cleared"; a secret "a sensitive value", a reference its text, a
    nested object "Custom versions 1 setting". Cost: none.
20. **A `clear` the list can't draw** (§5.8): one naming a setting the list doesn't offer (or not a plain list) is
    today's control, unchanged; the rows then come from the body only. When the rows draw it, their region carries
    `/clear` (a Go to or a problem there lands on them, the problem said there). Cost: none.
21. **The checks:** each task's tests red, then green, with its static checks; on the final tree the frontend suite,
    the build, `check:api` and CodeQL. The browser spec runs in CI's e2e job, or locally on the owner's word. Cost:
    none.

Mid-slice rulings start at M114.

## File structure

| File | Responsibility |
|---|---|
| `frontend/src/lib/schemaForm.ts` | the changes' parts on Setup; a union's branches, title and kind; what's offered (Task 2) |
| `frontend/src/lib/config.ts` | a body never sends an empty object (Task 3) |
| `frontend/src/routes/editor/drawer/FieldView.tsx`, `FieldFrame.tsx` | what the drawer's own fields are told (Task 4) |
| `frontend/src/lib/changes.ts` | rows, one write each, the kind, the words, the read-only summary (Tasks 5, 8, 9) |
| `frontend/src/routes/editor/drawer/Changes.tsx` | the Changes and Settings widget (Tasks 6–9) |
| `frontend/src/routes/editor/drawer/StepDrawer.tsx` | the changes on Setup, Options' line, the memory above the tabs (Tasks 2, 6) |
| `frontend/src/lib/settingsIndex.ts`, `frontend/src/routes/editor/drawer/FindSetting.tsx` | Find a setting (Task 7) |
| `frontend/src/routes/editor/drawer/GivenParts.tsx` | only the parts given: objects, map entries, list items (Task 8) |
| `frontend/src/test/nodeTypes.ts` | `UPDATE`, `CREATE`, `DEVICE_UPDATE`, `DEVICE_CREATE`: made up, shaped as Mist's (Task 2) |
| `frontend/e2e/changes.spec.ts`, `frontend/e2e/fixtures/changes.dewpoint.json`, `frontend/playwright.config.ts` | the browser spec (Task 10) |
| `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` | the plan's acceptance, each milestone, the final checkpoint (Tasks 1, 4, 7, 9, 11) |

## Milestones

1. **Tasks 1–4:** the ledger; the changes on Setup and the union helpers; no empty object; the fields' new options.
   Pause for the owner's review.
2. **Tasks 5–7:** the rows' model; the Changes widget; Find a setting. Pause for the owner's review.
3. **Tasks 8–9:** given parts (objects, maps, lists); a create's required settings and a device's kind. Pause for the
   owner's review.
4. **Tasks 10–11:** the browser spec, every check, the final checkpoint. Then the final review.

## How to run things

Every command runs from the plan's worktree. `$WT` is that worktree's root.

- **The frontend's locked packages.** From `$WT/frontend`, `npx --offline pnpm@12.6.0 install --frozen-lockfile
  --offline` restores them from the local store, the lockfile untouched. It installs packages, so the owner's OK is
  asked at the start.
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

# Milestone 1 — The ledger, and the form's foundations

### Task 1: The ledger: 4f-2a merged, this plan accepted

**Files:**
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (appended at the end)

**Interfaces:**
- Consumes: nothing.
- Produces: the ledger section later tasks append to (`### 4f-2b, milestone N`).

- [ ] **Step 1: Write the plan's status**

Run this task only once the owner has accepted the plan. Apply:

```diff
diff --git a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
index 73b7279a..6d3cd41f 100644
--- a/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
+++ b/docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
@@ -3864,3 +3864,39 @@ line (the boards'); the catalogue's growth (spec §4.2); a step's middle words (
 331); the hints without a drawer yet (4f-2b); the e2e left to CI (ruling 340); the key before the label loads (ruling
 335); the choices' hint for a viewer whose button is disabled (as before); "a Email"-style articles (4f-1's); hover not
 moving the list's active row.
+
+### 4f-2a merged; the 4f-2b plan accepted (2026-10-21)
+
+The owner merged 4f-2a as #137 (squash a4b677ab), every check green, the browser spec included ("green and merged");
+its eight deferred minors are issue #138. Two CI fixes went in with it: the workflows spec picks a Mist step by its ref
+(Mist's steps sit behind their resources now), and the data tree's quick-search test waits for its request (a race on a
+slow runner, reproduced with a slowed fake server).
+
+`docs/superpowers/plans/2026-10-21-editor-ui-4f2b-changes.md`, revision 1, with milestone pauses: the second half of
+the Mist step design (§5.3–§5.11). The owner accepted it: its rulings 1–21 join this ledger as 341–361. It amends ruling
+98 for an update's and a create's body (on Setup, optional or not). No route, migration, ABI change or step version.
+The design's §5.4 figures for settings reached through maps and lists (1,746 and 568) don't hold: by the drawer's own
+rules they're 1,678 (site settings) and 538 (gateway templates); through objects only, 656 and 97 (R6 §9). Mid-slice
+rulings start at M114.
+
+341. **Accepted. Milestone pauses after the form's foundations, the changes' list and its parts** (plan ruling 1).
+342. **Accepted. An update's or a create's body on Setup, when the config has what it needs** (plan ruling 2).
+343. **Accepted. A union's branches, its own title, its kind; what's offered** (plan ruling 3).
+344. **Accepted. A body never sends an empty object: pruned where writes land** (plan ruling 4).
+345. **Accepted. What the drawer's own fields are told: a group of parts, a name beside, own actions** (plan ruling 5).
+346. **Accepted. Rows, and Set, Clear and Keep as one write** (plan ruling 6).
+347. **Accepted. What the changes remember until the drawer closes, above the tabs** (plan ruling 7).
+348. **Accepted. The changes are the body's own field: List or Formula** (plan ruling 8).
+349. **Accepted. How they're sent: two choices, their words** (plan ruling 9).
+350. **Accepted. A row's controls and words** (plan ruling 10).
+351. **Accepted. How many change; nothing to change, a warning** (plan ruling 11).
+352. **Accepted. Find a setting** (plan ruling 12).
+353. **Accepted. An object's parts given, and another found** (plan ruling 13).
+354. **Accepted. A map's entries by key, a new one's key first** (plan ruling 14).
+355. **Accepted. A list's items by number, an item added written empty** (plan ruling 15).
+356. **Accepted. A secret one field; a union as JSON in its row** (plan ruling 16).
+357. **Accepted. A device's kind** (plan ruling 17).
+358. **Accepted. A create's required settings first** (plan ruling 18).
+359. **Accepted. Read only: the changes summed up** (plan ruling 19).
+360. **Accepted. A `clear` the list can't draw: today's control** (plan ruling 20).
+361. **Accepted. The checks; the browser spec in CI, or locally on the owner's word** (plan ruling 21).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "docs(editor-4): 4f-2a merged, the 4f-2b plan accepted

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The changes on Setup; a union's branches, its kind, what's offered

**Spec:** §5.3, §5.6, §5.7, §5.9 (Options); rulings 2, 3.

**Files:**
- Modify: `frontend/src/lib/schemaForm.ts`, `frontend/src/routes/editor/drawer/StepDrawer.tsx`
- Test: `frontend/src/lib/schemaForm.test.ts`, `frontend/src/routes/editor/drawer/StepDrawer.test.tsx`,
  `frontend/src/test/nodeTypes.ts` (`UPDATE`, `CREATE`, `DEVICE_UPDATE`, `DEVICE_CREATE`: made up, shaped as Mist's)

**Interfaces:**
- Consumes: `fieldsOf`, `propertiesOf`, `tabsOf`, the private `make` and `target` (`lib/schemaForm.ts`).
- Produces (`lib/schemaForm.ts`):
  - `type Changes = { widget: "update" | "create"; body: FieldSpec; mode: FieldSpec | null; clear: FieldSpec | null }`;
    `changeParts(c: Changes): FieldSpec[]` (body, mode, clear);
  - `settingsOf(type, fields)` returns `{ setup, message, changes: Changes | null, options }`;
  - `isReadOnly(f: FieldSpec): boolean`; `branchesOf(f: FieldSpec): FieldSpec[]`; `unionTitle(f: FieldSpec): string |
    null`; `kindOf(branches: FieldSpec[]): { name: string; values: string[] } | null`; `offeredOf(f: FieldSpec, kind:
    string | null = null): FieldSpec[]`;
  - the fixtures; `StepDrawer` draws the changes' parts on Setup (as today's fields until Task 6) and says where they
    are on Options.

- [ ] **Step 1: Write the failing tests, and the fixtures**

Apply:

```diff
diff --git a/frontend/src/lib/schemaForm.test.ts b/frontend/src/lib/schemaForm.test.ts
index d04c306a..d159d82f 100644
--- a/frontend/src/lib/schemaForm.test.ts
+++ b/frontend/src/lib/schemaForm.test.ts
@@ -1,9 +1,9 @@
 // SPDX-License-Identifier: Apache-2.0
 import { describe, expect, it } from "vitest";
-import { DELAY, FILTER, IF, LOOP, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith } from "../test/nodeTypes";
+import { CREATE, DELAY, DEVICE_UPDATE, FILTER, IF, LOOP, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith, UPDATE } from "../test/nodeTypes";
 import {
-  canFixed, canFormula, emptyOf, entryOf, fieldLabel, fieldsOf, itemOf, pointerOf, propertiesOf, startsAsFormula, tabsOf,
-  takesPills,
+  branchesOf, canFixed, canFormula, changeParts, emptyOf, entryOf, fieldLabel, fieldsOf, isReadOnly, itemOf, kindOf, offeredOf,
+  pointerOf, propertiesOf, settingsOf, startsAsFormula, tabsOf, takesPills, unionTitle,
 } from "./schemaForm";  // prettier-ignore
 
 const field = (type: Parameters<typeof fieldsOf>[0], name: string) => fieldsOf(type).find((f) => f.name === name)!;
@@ -172,3 +172,44 @@ describe("4c-2b's field kinds", () => {
     expect(fieldLabel(IF, "/nope")).toBe("/nope");
   });
 });
+
+describe("4f-2b's changes", () => {
+  const names = (fs: { name: string }[]) => fs.map((f) => f.name);
+  it("draws an update's body, mode and clear together on Setup, after its required fields", () => {
+    const { setup, changes, options } = settingsOf(UPDATE, fieldsOf(UPDATE));
+    expect(names(setup)).toEqual(["connection", "thing_id"]);
+    expect(changes?.widget).toBe("update");
+    expect(names(changeParts(changes!))).toEqual(["body", "mode", "clear"]);
+    expect(options).toEqual([]);
+  });
+  it("draws a create's body as its settings", () => {
+    const { setup, changes } = settingsOf(CREATE, fieldsOf(CREATE));
+    expect(names(setup)).toEqual(["connection"]);
+    expect([changes?.widget, changes?.mode, changes?.clear]).toEqual(["create", null, null]);
+    expect(names(changeParts(changes!))).toEqual(["body"]);
+  });
+  it("leaves an update without what the changes need to the generic form", () => {
+    const schema = UPDATE.config_schema as Record<string, Record<string, unknown>>;
+    const properties = Object.fromEntries(Object.entries(schema.properties!).filter(([name]) => name !== "clear"));
+    const odd = typeWith({ ...schema, properties });
+    const { changes, options } = settingsOf(odd, fieldsOf(odd));
+    expect(changes).toBeNull();
+    expect(names(options)).toEqual(["body", "mode"]);
+  });
+  it("offers a group's settings without the ones Mist sets", () => {
+    const body = fieldsOf(UPDATE).find((f) => f.name === "body")!;
+    expect(names(offeredOf(body))).toEqual(["name", "enabled", "rogue", "auto_upgrade", "port_usages", "networks", "tags", "vlan_id", "api_secret", "radius"]);
+    expect(isReadOnly(propertiesOf(body).find((p) => p.name === "id")!)).toBe(true);
+    expect(branchesOf(body)).toEqual([]);
+  });
+  it("reads a union body's branches, their kind and the union's own title", () => {
+    const body = fieldsOf(DEVICE_UPDATE).find((f) => f.name === "body")!;
+    const branches = branchesOf(body);
+    expect(branches.map((b) => [b.label, b.pointer])).toEqual([["Camera", "/body"], ["Sensor", "/body"]]);
+    expect(body.label).toBe("Body");
+    expect(unionTitle(body)).toBe("Device");
+    expect(kindOf(branches)).toEqual({ name: "type", values: ["camera", "sensor"] });
+    expect(names(offeredOf(branches[0]!, "type"))).toEqual(["name", "notes", "zoom"]);
+    expect(propertiesOf(branches[1]!).map((p) => p.pointer)).toEqual(["/body/type", "/body/name", "/body/notes", "/body/range"]);
+  });
+});
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.test.tsx b/frontend/src/routes/editor/drawer/StepDrawer.test.tsx
index 23456f30..7e8a2ce2 100644
--- a/frontend/src/routes/editor/drawer/StepDrawer.test.tsx
+++ b/frontend/src/routes/editor/drawer/StepDrawer.test.tsx
@@ -1,7 +1,8 @@
 // SPDX-License-Identifier: Apache-2.0
 import { screen } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
 import { expect, it } from "vitest";
-import { GROUPED, REMOTE } from "../../../test/nodeTypes";
+import { CREATE, GROUPED, REMOTE, UPDATE } from "../../../test/nodeTypes";
 import { fakeApi, showDrawer } from "./harness";
 
 it("names a step's group under its title", () => {
@@ -17,3 +18,22 @@ it("names none for a step outside a group", () => {
   expect(screen.getByText("Sites · acme.sites@1")).toBeTruthy();
   expect(screen.queryByText(/^Acme · /)).toBeNull();
 });
+
+const CONNECTIONS = { "GET /api/v1/t/t1/connections": () => new Response("[]", { headers: { "content-type": "application/json" } }) };
+
+it("draws an update's changes on Setup, and says so on Options (4f-2b)", async () => {
+  fakeApi(CONNECTIONS);
+  showDrawer(UPDATE);
+  const setup = screen.getByRole("tabpanel", { name: /Setup/ });
+  expect(["/connection", "/thing_id", "/body", "/mode", "/clear"].map((p) => setup.querySelector(`[data-pointer="${p}"]`) !== null)).toEqual([true, true, true, true, true]);
+  await userEvent.click(screen.getByRole("tab", { name: /Options/ }));
+  expect(screen.getByText("The changes are on Setup.")).toBeTruthy();
+});
+
+it("draws a create's settings on Setup, and says so on Options (4f-2b)", async () => {
+  fakeApi(CONNECTIONS);
+  showDrawer(CREATE);
+  expect(screen.getByRole("tabpanel", { name: /Setup/ }).querySelector('[data-pointer="/body"]')).not.toBeNull();
+  await userEvent.click(screen.getByRole("tab", { name: /Options/ }));
+  expect(screen.getByText("The settings are on Setup.")).toBeTruthy();
+});
diff --git a/frontend/src/test/nodeTypes.ts b/frontend/src/test/nodeTypes.ts
index b4365402..9a4bc692 100644
--- a/frontend/src/test/nodeTypes.ts
+++ b/frontend/src/test/nodeTypes.ts
@@ -138,3 +138,137 @@ export const messageStep = (type: string, more: Record<string, unknown> = {}, re
       ...more,
     },
   }, { ref: `${type}@1`, type, title: "Send a message", credentials: [type.split(".")[0]!] });  // prettier-ignore
+
+/** A made-up service's update and create steps (4f-2b), shaped as Mist's are: the body a `$defs` component, settings
+ * titled on their own entries, a read-only one, objects, a map and a list of objects, a union, sensitive parts; an
+ * update's `mode` and `clear` (D24: never Mist's own). */
+const SETTING_DEFS = {
+  thing: {
+    type: "object",
+    properties: {
+      id: { $ref: "#/$defs/id", title: "ID", description: "Unique ID of the object" },
+      name: { type: "string", title: "Name", description: "The thing's name" },
+      enabled: { type: "boolean", title: "Enabled", description: "Whether the thing runs" },
+      rogue: { $ref: "#/$defs/rogue", title: "Rogue", description: "AP threat detection settings for the site" },
+      auto_upgrade: { $ref: "#/$defs/auto_upgrade", title: "Auto upgrade", description: "Automatic upgrade settings" },
+      port_usages: { type: "object", title: "Port usages", description: "Port profiles by name", additionalProperties: { $ref: "#/$defs/port_usage" } },
+      networks: { type: "array", title: "Networks", description: "The networks served", items: { $ref: "#/$defs/network" } },
+      tags: { type: "array", title: "Tags", description: "Free tags", items: { type: "string" } },
+      vlan_id: { anyOf: [{ type: "integer", minimum: 1, maximum: 4094 }, { type: "string" }], title: "VLAN ID", description: "A number or a variable" },
+      api_secret: { type: "string", title: "API secret", description: "The service's secret", "x-sensitive": true },
+      radius: { $ref: "#/$defs/radius", title: "RADIUS", description: "The RADIUS server" },
+    },
+  },
+  id: { type: "string", format: "uuid", readOnly: true },
+  rogue: {
+    type: "object",
+    description: "Rogue AP detection settings for a site",
+    properties: {
+      enabled: { type: "boolean", title: "Enabled", description: "Whether rogue detection is enabled" },
+      min_rogue_rssi: { type: "integer", minimum: -85, title: "Min rogue RSSI", description: "Minimum RSSI for an AP to be considered rogue" },
+      whitelisted_ssids: { type: "array", items: { type: "string" }, title: "Whitelisted SSIDs", description: "SSID names excluded from rogue detection" },
+    },
+  },
+  auto_upgrade: {
+    type: "object",
+    properties: {
+      enabled: { type: "boolean", title: "Enabled", description: "Whether auto upgrade should happen" },
+      version: { type: "string", enum: ["beta", "custom", "stable"], title: "Version", description: "Desired version" },
+      time_of_day: { type: "string", title: "Time of day", description: "HH:MM, 24-hour" },
+      custom: { type: "object", title: "Custom versions", description: "A version per model", properties: { ap41: { type: "string", title: "AP41", description: "The AP41's version" } } },
+    },
+  },
+  port_usage: {
+    type: "object",
+    properties: {
+      mode: { type: "string", enum: ["access", "trunk"], title: "Mode", description: "How the port is used" },
+      port_vlan: { type: "integer", title: "Port VLAN", description: "The port's native VLAN" },
+    },
+  },
+  network: {
+    type: "object",
+    properties: {
+      name: { type: "string", title: "Name", description: "The network's name" },
+      subnet: { type: "string", title: "Subnet", description: "The network's subnet" },
+    },
+  },
+  radius: {
+    type: "object",
+    properties: {
+      host: { type: "string", title: "Host", description: "The server's host" },
+      secret: { type: "string", title: "Secret", description: "The shared secret", "x-sensitive": true },
+    },
+  },
+};
+const CONNECTION = { type: "string", format: "uuid", title: "Connection", "x-dewpoint-literal": true, "x-dewpoint-connection": "acme" };
+const THING_ID = { title: "Thing ID", type: "string", format: "uuid", "x-dewpoint-options": true };
+const NAMES = ["api_secret", "auto_upgrade", "enabled", "id", "name", "networks", "port_usages", "radius", "rogue", "tags", "vlan_id"];
+
+/** An update: its body, merge or replace, and the settings to clear (`x-widget: "update"`). */
+export const UPDATE = typeWith({
+  type: "object", additionalProperties: false, required: ["connection", "thing_id"], "x-widget": "update",
+  "x-group": { plugin: "Acme", title: "Things" },
+  properties: {
+    connection: CONNECTION,
+    thing_id: THING_ID,
+    body: { title: "Body", $ref: "#/$defs/thing" },
+    mode: { enum: ["merge", "replace"], default: "merge", title: "Mode" },
+    clear: { type: "array", title: "Fields to clear", uniqueItems: true, items: { enum: NAMES } },
+  },
+  $defs: SETTING_DEFS,
+}, { ref: "acme.things.update@1", type: "acme.things.update", title: "Update thing", options: ["thing_id"], credentials: ["acme"], side_effect: "idempotent" });  // prettier-ignore
+
+/** A create: its body, its name required (`x-widget: "create"`). */
+export const CREATE = typeWith({
+  type: "object", additionalProperties: false, required: ["connection", "body"], "x-widget": "create",
+  "x-group": { plugin: "Acme", title: "Things" },
+  properties: { connection: CONNECTION, body: { title: "Body", $ref: "#/$defs/new_thing" } },
+  $defs: { ...SETTING_DEFS, new_thing: { ...SETTING_DEFS.thing, required: ["name"] } },
+}, { ref: "acme.things.create@1", type: "acme.things.create", title: "Create thing", credentials: ["acme"], side_effect: "ambiguous" });  // prettier-ignore
+
+const KIND_DEFS = {
+  device: { description: "A device: a camera or a sensor", anyOf: [{ $ref: "#/$defs/camera", title: "Camera" }, { $ref: "#/$defs/sensor", title: "Sensor" }], title: "Device" },
+  camera: {
+    type: "object",
+    properties: {
+      type: { $ref: "#/$defs/kind_camera", title: "Type" },
+      name: { type: "string", title: "Name", description: "The device's name" },
+      notes: { type: "string", title: "Notes", description: "Any notes" },
+      zoom: { type: "integer", title: "Zoom", description: "The camera's zoom" },
+    },
+  },
+  sensor: {
+    type: "object",
+    properties: {
+      type: { $ref: "#/$defs/kind_sensor", title: "Type" },
+      name: { type: "string", title: "Name", description: "The device's name" },
+      notes: { type: "string", title: "Notes", description: "Any notes" },
+      range: { type: "integer", title: "Range", description: "The sensor's range" },
+    },
+  },
+};
+
+/** A device update whose body is a union of kinds, each allowing one `type`, read only (as Mist's devices). */
+export const DEVICE_UPDATE = typeWith({
+  type: "object", additionalProperties: false, required: ["connection"], "x-widget": "update",
+  properties: {
+    connection: CONNECTION,
+    body: { title: "Body", $ref: "#/$defs/device" },
+    mode: { enum: ["merge", "replace"], default: "merge", title: "Mode" },
+    clear: { type: "array", title: "Fields to clear", uniqueItems: true, items: { enum: ["name", "notes", "range", "type", "zoom"] } },
+  },
+  $defs: { ...KIND_DEFS, kind_camera: { enum: ["camera"], type: "string", readOnly: true }, kind_sensor: { enum: ["sensor"], type: "string", readOnly: true } },
+}, { ref: "acme.devices.update@1", type: "acme.devices.update", title: "Update device", credentials: ["acme"], side_effect: "idempotent" });  // prettier-ignore
+
+/** A device create: the kind's `type` required (as Mist's device profiles). */
+export const DEVICE_CREATE = typeWith({
+  type: "object", additionalProperties: false, required: ["connection", "body"], "x-widget": "create",
+  properties: { connection: CONNECTION, body: { title: "Body", $ref: "#/$defs/device" } },
+  $defs: {
+    ...KIND_DEFS,
+    camera: { ...KIND_DEFS.camera, required: ["type"] },
+    sensor: { ...KIND_DEFS.sensor, required: ["type", "name"] },
+    kind_camera: { enum: ["camera"], type: "string" },
+    kind_sensor: { enum: ["sensor"], type: "string", readOnly: true },
+  },
+}, { ref: "acme.devices.create@1", type: "acme.devices.create", title: "Create device", credentials: ["acme"], side_effect: "ambiguous" });  // prettier-ignore
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/schemaForm.test.ts src/routes/editor/drawer/StepDrawer.test.tsx`
Expected: FAIL, 7 failed and 22 passed: the helpers don't exist (`(0 , branchesOf) is not a function`, `(0 , offeredOf)
is not a function`), `settingsOf` gives no changes (`expected undefined to be null`), and Options says nothing of them
(`Unable to find an element with the text: The settings are on Setup.`).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/schemaForm.ts b/frontend/src/lib/schemaForm.ts
index 6cb2c407..1f6f3fd0 100644
--- a/frontend/src/lib/schemaForm.ts
+++ b/frontend/src/lib/schemaForm.ts
@@ -201,17 +201,82 @@ export const tabsOf = (fields: FieldSpec[]) => ({
 /** The message's parts, in the composer's order (4f-1, the message composer design §5.1). */
 export const MESSAGE_PARTS = ["severity", "title", "text", "fields", "links"];
 
+/** An update's or a create's body, drawn as one list of its settings (4f-2, the Mist step design §5.3, §5.6): an
+ * update's with how it's sent (`mode`) and what it clears (`clear`). */
+export type Changes = { widget: "update" | "create"; body: FieldSpec; mode: FieldSpec | null; clear: FieldSpec | null };
+
+/** The changes a config's root asks for (`x-widget: "update"` or `"create"`), when it has the parts they need: a
+ * `body`; for an update, `mode` taking merge and replace, and `clear` a list. Else none: the generic form. */
+function changesOf(type: NodeType, fields: FieldSpec[]): Changes | null {
+  const widget = type.config_schema["x-widget"];
+  const body = fields.find((f) => f.name === "body");
+  if (body === undefined || (widget !== "update" && widget !== "create")) return null;
+  if (widget === "create") return { widget, body, mode: null, clear: null };
+  const mode = fields.find((f) => f.name === "mode");
+  const clear = fields.find((f) => f.name === "clear");
+  const modes = mode?.schema.enum;
+  const takes = Array.isArray(modes) && modes.includes("merge") && modes.includes("replace");
+  return mode && clear && takes && clear.base === "list" ? { widget, body, mode, clear } : null;
+}
+
+/** The parts the changes draw: body, then mode and clear. */
+export const changeParts = (c: Changes): FieldSpec[] => [c.body, ...(c.mode ? [c.mode] : []), ...(c.clear ? [c.clear] : [])];
+
 /** A step's settings on their tabs. With the composer's hint at its config's root (`x-widget: "message"`) and the
  * message's text, the message's parts are drawn together on Setup, after its required fields, optional ones included
- * (ruling 98, amended for a message); without its text, the generic form (ruling 100). */
-export function settingsOf(type: NodeType, fields: FieldSpec[]): { setup: FieldSpec[]; message: FieldSpec[] | null; options: FieldSpec[] } {
+ * (ruling 98, amended for a message); without its text, the generic form (ruling 100). An update's or a create's
+ * changes are drawn on Setup too (4f-2b; ruling 98 amended for them). */
+export function settingsOf(
+  type: NodeType, fields: FieldSpec[],
+): { setup: FieldSpec[]; message: FieldSpec[] | null; changes: Changes | null; options: FieldSpec[] } {  // prettier-ignore
   const message =
     type.config_schema["x-widget"] === "message" && fields.some((f) => f.name === "text")
       ? MESSAGE_PARTS.flatMap((name) => fields.filter((f) => f.name === name))
       : null;
-  return { ...tabsOf(message ? fields.filter((f) => !message.includes(f)) : fields), message };
+  const changes = message ? null : changesOf(type, fields);
+  const drawn = [...(message ?? []), ...(changes ? changeParts(changes) : [])];
+  return { ...tabsOf(fields.filter((f) => !drawn.includes(f))), message, changes };
+}
+
+/** A setting Mist sets itself (`readOnly`): never offered (4f-2b). */
+export const isReadOnly = (f: FieldSpec): boolean => f.schema.readOnly === true;
+
+/** A union's branches (`anyOf`, `oneOf`), each a group at the union's place, labelled by its own title: a device's
+ * "AP", "Switch", "Gateway". None when it isn't a union of two or more. */
+export function branchesOf(f: FieldSpec): FieldSpec[] {
+  const list = Array.isArray(f.schema.anyOf) ? f.schema.anyOf : Array.isArray(f.schema.oneOf) ? f.schema.oneOf : [];
+  if (f.cut || list.length < 2) return [];
+  return (list as unknown[]).map((raw, i) => ({
+    ...make(f.type, f.root, f.name, f.path, raw, f.required, f.entry, f.literalOnly, f.refs),
+    label: isObject(raw) && typeof raw.title === "string" ? raw.title : `Kind ${i + 1}`,
+  }));
 }
 
+/** The union's own title, which its entry's ("Body") hides: "Device". */
+export function unionTitle(f: FieldSpec): string | null {
+  const ref = f.refs[f.refs.length - 1];
+  const title = ref === undefined ? undefined : target(ref, f.root).title;
+  return typeof title === "string" && title.trim() !== "" ? title : null;
+}
+
+/** The setting every branch has and allows one value in: the kind (`type`), and each branch's value. */
+export function kindOf(branches: FieldSpec[]): { name: string; values: string[] } | null {
+  if (branches.length < 2) return null;
+  const one = (b: FieldSpec, name: string): string | null => {
+    const values = propertiesOf(b).find((p) => p.name === name)?.schema.enum;
+    return Array.isArray(values) && values.length === 1 && typeof values[0] === "string" ? values[0] : null;
+  };
+  for (const p of propertiesOf(branches[0]!)) {
+    const values = branches.map((b) => one(b, p.name));
+    if (values.every((v): v is string => v !== null) && new Set(values).size === values.length) return { name: p.name, values };
+  }
+  return null;
+}
+
+/** A group's settings a person may give: its properties, without the ones Mist sets and the kind's. */
+export const offeredOf = (f: FieldSpec, kind: string | null = null): FieldSpec[] =>
+  propertiesOf(f).filter((p) => !isReadOnly(p) && p.name !== kind);
+
 /** Where the engine takes a fixed value: not in a sensitive field (sensitive.literal), and `literal` among its kinds. */
 export const canFixed = (f: FieldSpec): boolean => !f.sensitive && (f.kinds === null || f.kinds.includes("literal"));
 
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.tsx b/frontend/src/routes/editor/drawer/StepDrawer.tsx
index e6594f81..8f5dea76 100644
--- a/frontend/src/routes/editor/drawer/StepDrawer.tsx
+++ b/frontend/src/routes/editor/drawer/StepDrawer.tsx
@@ -9,7 +9,7 @@ import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } fro
 import { Button } from "../../../components/Button";
 import { Tabs } from "../../../components/Tabs";
 import { optionsLine, targetOf } from "../../../lib/composer";
-import { fieldsOf, settingsOf, type FieldSpec } from "../../../lib/schemaForm";
+import { changeParts, fieldsOf, settingsOf, type FieldSpec } from "../../../lib/schemaForm";
 import { groupOf } from "../../../lib/stepGroups";
 import type { UnappliedKind } from "../../../lib/unapplied";
 import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";
@@ -113,8 +113,9 @@ export function StepDrawer({
   }, [node.id]);
   const fields = useMemo(() => (type ? fieldsOf(type) : []), [type]);
   const group = type ? groupOf(type) : null; // its plugin's group: "Mist · Site settings" (4f-2)
-  const { setup, message, options } = type ? settingsOf(type, fields) : { setup: [], message: null, options: [] };
-  const onSetup = [...setup, ...(message ?? [])]; // what Setup shows: a message's parts too
+  const { setup, message, changes, options } = type ? settingsOf(type, fields) : { setup: [], message: null, changes: null, options: [] };
+  const changing = changes ? changeParts(changes) : [];
+  const onSetup = [...setup, ...(message ?? []), ...changing]; // what Setup shows: a message's parts, an update's changes
   const [tab, setTab] = useState<Tab>(result ? "result" : test && testAt ? "test" : onSetup.length > 0 ? "setup" : "options");
   useEffect(() => {
     if (test && testAt) setTab("test");
@@ -263,6 +264,7 @@ export function StepDrawer({
                   <>
                     {setup.map((f) => <FieldView key={f.pointer} spec={f} />)}
                     {message && <MessageComposer parts={message} />}
+                    {changing.map((f) => <FieldView key={f.pointer} spec={f} />)}
                     {options.map((f) => <FieldView key={f.pointer} spec={f} />)}
                   </>
                 ) : (
@@ -290,6 +292,12 @@ export function StepDrawer({
                     {setup.map((f) => <FieldView key={f.pointer} spec={f} drawn={{ marked: true }} />)}
                     <MessageComposer parts={message} />
                   </>
+                ) : changes ? (
+                  // An update's changes or a create's settings follow its required fields, optional or not (4f-2b).
+                  <>
+                    {setup.map((f) => <FieldView key={f.pointer} spec={f} drawn={{ marked: true }} />)}
+                    {changing.map((f) => <FieldView key={f.pointer} spec={f} />)}
+                  </>
                 ) : setup.length > 0 ? (
                   <>
                     <p className="text-small text-muted">Each of these is required.</p>
@@ -305,6 +313,9 @@ export function StepDrawer({
                 content: (
                   <>
                     {message && <p className="text-small text-muted">{optionsLine(targetOf(type))}</p>}
+                    {changes && (
+                      <p className="text-small text-muted">{changes.widget === "update" ? "The changes are on Setup." : "The settings are on Setup."}</p>
+                    )}
                     {options.length > 0
                       ? options.map((f) => <FieldView key={f.pointer} spec={f} />)
                       : <p className="text-small text-muted">Nothing else to set.</p>}
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 29 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/schemaForm.ts frontend/src/lib/schemaForm.test.ts frontend/src/routes/editor/drawer/StepDrawer.tsx frontend/src/routes/editor/drawer/StepDrawer.test.tsx frontend/src/test/nodeTypes.ts
git commit -m "feat(editor): an update's changes and a create's settings on Setup; a union's kind (4f-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: A body never sends an empty object

**Spec:** §5.3 ("A setting given nothing isn't sent"); ruling 4.

**Files:**
- Modify: `frontend/src/lib/config.ts` (`pruned`; `setConfig` prunes)
- Test: `frontend/src/lib/config.test.ts`

**Interfaces:**
- Consumes: `setAt`, `valueAt`, `isObject` (`lib/config.ts`); `UPDATE`, `REMOTE` (Task 2's fixtures).
- Produces: `pruned(config: Record<string, unknown>, path: Path): Record<string, unknown>`; `setConfig` applies it for
  a type whose root says `update` or `create` and a path under `body` (held edits included: they're applied through it).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/config.test.ts b/frontend/src/lib/config.test.ts
index 756fd0a5..3837f157 100644
--- a/frontend/src/lib/config.test.ts
+++ b/frontend/src/lib/config.test.ts
@@ -1,9 +1,9 @@
 // SPDX-License-Identifier: Apache-2.0
 import { describe, expect, it } from "vitest";
-import { IF, SWITCH } from "../test/nodeTypes";
+import { IF, REMOTE, SWITCH, UPDATE } from "../test/nodeTypes";
 import {
   CEL_WORDS, admission, declassify, fixedOf, formula, formulaOf, freePort, isPlainRef, keyProblem, kindOf, parseJson, referenceText,
-  renameEntry, renameKey, renamePort, rootOf, setAt, setConfig, setOptions, undeclassify, valueAt,
+  pruned, renameEntry, renameKey, renamePort, rootOf, setAt, setConfig, setOptions, undeclassify, valueAt,
 } from "./config";  // prettier-ignore
 import type { GraphDoc } from "./workflows";
 
@@ -420,3 +420,29 @@ describe("declassify entries (4c-2b)", () => {
     expect(undeclassify(doc([a]), 3)).toEqual(doc([a]));
   });
 });
+
+describe("an update's body sends no empty object (4f-2b)", () => {
+  const doc = (config: Record<string, unknown>): GraphDoc => ({ graph_format: 1, nodes: [{ id: A, key: "update", type: "acme.things.update@1", config }], edges: [] });
+  const after = (d: GraphDoc) => d.nodes![0]!.config;
+
+  it("removes each object a write empties, up to the body's setting", () => {
+    const start = doc({ body: { auto_upgrade: { custom: { ap41: "1.2" }, enabled: true } } });
+    const once = setConfig(start, A, ["body", "auto_upgrade", "custom", "ap41"], undefined, UPDATE).doc;
+    expect(after(once)).toEqual({ body: { auto_upgrade: { enabled: true } } });
+    const twice = setConfig(once, A, ["body", "auto_upgrade", "enabled"], undefined, UPDATE).doc;
+    expect(after(twice)).toEqual({ body: {} });
+    expect(after(setConfig(start, A, ["body", "auto_upgrade"], {}, UPDATE).doc)).toEqual({ body: {} });
+  });
+
+  it("keeps an object still holding a part, a list's item, and anything outside a body or another type's", () => {
+    const start = doc({ body: { rogue: { enabled: true, min_rogue_rssi: -80 }, networks: [{ name: "a" }] } });
+    expect(after(setConfig(start, A, ["body", "rogue", "enabled"], undefined, UPDATE).doc)).toEqual({ body: { rogue: { min_rogue_rssi: -80 }, networks: [{ name: "a" }] } });
+    expect(after(setConfig(start, A, ["body", "networks", 0, "name"], undefined, UPDATE).doc)).toEqual({ body: { rogue: { enabled: true, min_rogue_rssi: -80 }, networks: [{}] } });
+    expect(after(setConfig(doc({ query: { limit: 5 } }), A, ["query", "limit"], undefined, UPDATE).doc)).toEqual({ query: {} });
+    expect(after(setConfig(doc({ body: { x: { y: 1 } } }), A, ["body", "x", "y"], undefined, REMOTE).doc)).toEqual({ body: { x: {} } });
+  });
+
+  it("stops at a value that isn't an empty object", () => {
+    expect(pruned({ body: { a: { b: { $value: { kind: "cel", expr: "{}" } } } } }, ["body", "a", "b"])).toEqual({ body: { a: { b: { $value: { kind: "cel", expr: "{}" } } } } });
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/config.test.ts`
Expected: FAIL, 2 failed and 41 passed: an emptied object stays (`expected { body: { auto_upgrade: { …(2) } } } to
deeply equal { body: { auto_upgrade: { …(1) } } }`) and `pruned` doesn't exist. "keeps an object still holding a part, a
list's item, and anything outside a body or another type's" passes at once: it pins what stays.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/config.ts b/frontend/src/lib/config.ts
index 4c31a4db..2aded6a1 100644
--- a/frontend/src/lib/config.ts
+++ b/frontend/src/lib/config.ts
@@ -307,11 +307,30 @@ function dropLost(doc: GraphDoc, before: GraphNode, after: GraphNode, type: Node
 export function setConfig(doc: GraphDoc, nodeId: string, path: Path, value: unknown, type: NodeType | undefined): Changed {
   const before = findNode(doc, nodeId);
   if (!before) return { doc, dropped: [] };
-  const after = { ...before, config: setAt(before.config ?? {}, path, value) as Record<string, unknown> };
+  const written = setAt(before.config ?? {}, path, value) as Record<string, unknown>;
+  const widget = type?.config_schema["x-widget"];
+  const bodied = (widget === "update" || widget === "create") && path[0] === "body";
+  const after = { ...before, config: bodied ? pruned(written, path) : written };
   const next = followEntries(withNode(doc, nodeId, after), nodeId, before.config ?? {}, after.config, path, value);
   return dropLost(next, before, after, type);
 }
 
+/** An update's or a create's body never sends an empty object (4f-2b, the Mist step design §5.3: with replace, one
+ * would reset the setting): after a write at `path`, each object it emptied, from there up to the body's top-level
+ * setting, is removed. A list's item stays: its place is the person's. The body itself stays, empty or not. */
+export function pruned(config: Record<string, unknown>, path: Path): Record<string, unknown> {
+  let out: unknown = config;
+  for (let end = path.length; end >= 2; end--) {
+    const at = path.slice(0, end);
+    if (typeof at[at.length - 1] === "number") break;
+    const node = valueAt(out, at);
+    if (node === undefined) continue; // removed by the write itself
+    if (!(isObject(node) && Object.keys(node).length === 0)) break;
+    out = setAt(out, at, undefined);
+  }
+  return out as Record<string, unknown>;
+}
+
 /** What a step sets for itself; what it leaves out takes the type's defaults, and a failure fails the run by default,
  * so "fail" isn't written. */
 export function setOptions(doc: GraphDoc, nodeId: string, options: StepOptions, type: NodeType | undefined): Changed {
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 43 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/config.ts frontend/src/lib/config.test.ts
git commit -m "feat(editor): an update's or a create's body never sends an empty object (4f-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: What the drawer's own fields are told

**Spec:** §5.3, §5.8, §5.10; ruling 5.

**Files:**
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx` (`Drawn`),
  `frontend/src/routes/editor/drawer/FieldFrame.tsx`
  (`name`; a group's `warn` and `below`)
- Test: `frontend/src/routes/editor/drawer/FieldView.test.tsx`

**Interfaces:**
- Consumes: Task 2's `UPDATE`, `DEVICE_UPDATE`; `fieldsOf`, `propertiesOf`.
- Produces: `Drawn` gains `group?: boolean`, `startFixed?: boolean`, `fixedName?: string`, `shown?: string[]`, `name?:
  string`, `actions?: ReactNode`, `hideClear?: boolean`, `switchLabel?: string`; `FieldFrame` and `GroupFrame` take
  `name?: string`; `GroupFrame` takes `warn`; FieldView passes a group `below` and `warn`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/drawer/FieldView.test.tsx b/frontend/src/routes/editor/drawer/FieldView.test.tsx
index 35910785..f8b0b963 100644
--- a/frontend/src/routes/editor/drawer/FieldView.test.tsx
+++ b/frontend/src/routes/editor/drawer/FieldView.test.tsx
@@ -3,9 +3,10 @@ import { cleanup, screen, within } from "@testing-library/react";
 import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, expect, it, vi } from "vitest";
 import { formula, literal } from "../../../lib/config";
-import { FILTER, IF, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith } from "../../../test/nodeTypes";
+import { DEVICE_UPDATE, FILTER, IF, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith, UPDATE } from "../../../test/nodeTypes";
+import { fieldsOf, propertiesOf } from "../../../lib/schemaForm";
 import { STALE } from "../../../lib/unapplied";
-import { PILLS_NOTE } from "./FieldView";
+import { FieldView, PILLS_NOTE } from "./FieldView";
 import { NODE_ID, fakeApi, problem, showFields } from "./harness";
 
 beforeEach(() => {
@@ -583,3 +584,34 @@ it("lands on Add after a list is cleared", async () => {
   await userEvent.click(screen.getByRole("button", { name: "Clear Tags" }));
   await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add to Tags" })));
 });
+
+// 4f-2b: how an update's changes draw the drawer's own fields.
+const bodyOf = (type: typeof UPDATE) => fieldsOf(type).find((f) => f.name === "body")!;
+
+it("draws a union as a group of the parts it's given, in Fixed when empty, its fixed side named (4f-2b)", () => {
+  const body = bodyOf(DEVICE_UPDATE);
+  showFields(DEVICE_UPDATE, {}, <FieldView spec={body} drawn={{ group: true, startFixed: true, fixedName: "List", parts: () => <p>the rows</p> }} />);
+  expect(screen.getByText("the rows")).toBeTruthy();
+  expect(screen.getByRole("button", { name: "List" }).getAttribute("aria-pressed")).toBe("true");
+});
+
+it("names a setting beside its label, adds its own actions and hides its Clear (4f-2b)", () => {
+  const name = propertiesOf(bodyOf(UPDATE)).find((p) => p.name === "name")!;
+  showFields(UPDATE, { config: { body: { name: "hq" } } }, <FieldView spec={name} drawn={{ name: "name", hideClear: true, actions: <button type="button">Keep Name as it is</button> }} />);
+  const field = document.querySelector<HTMLElement>('[data-pointer="/body/name"]')!;
+  expect(within(field).getByText("name").className).toContain("font-mono");
+  expect(within(field).getByRole("button", { name: "Keep Name as it is" })).toBeTruthy();
+  expect(within(field).queryByRole("button", { name: "Clear Name" })).toBeNull();
+});
+
+it("keeps a problem at a part it doesn't draw on the group, says its warning and what's under it (4f-2b)", () => {
+  const body = bodyOf(UPDATE);
+  const problems = [problem("/body/rogue/enabled", "Not a yes or no."), problem("/body/name", "Too long.")];
+  showFields(UPDATE, { config: { body: { name: "x", rogue: { enabled: 3 } } }, problems },
+    <FieldView spec={body} drawn={{ shown: ["name"], warn: "Replace resets the parts not given.", below: <p>the count</p>, parts: () => <p>the rows</p> }} />);  // prettier-ignore
+  const group = screen.getByRole("group", { name: "Body" });
+  expect(within(group).getByText("Not a yes or no.")).toBeTruthy(); // at a part not drawn: on the group
+  expect(within(group).queryByText("Too long.")).toBeNull(); // at a part drawn: its own
+  expect(within(group).getByText("Replace resets the parts not given.")).toBeTruthy();
+  expect(within(group).getByText("the count")).toBeTruthy();
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/drawer/FieldView.test.tsx`
Expected: FAIL, 3 failed and 50 passed: a union isn't drawn as a group (`Unable to find an element with the text: the
rows`), no name beside the label (`… text: name`), a problem at an undrawn part is lost (`… text: Not a yes or no.`).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/drawer/FieldFrame.tsx b/frontend/src/routes/editor/drawer/FieldFrame.tsx
index 06a9c464..3440acc3 100644
--- a/frontend/src/routes/editor/drawer/FieldFrame.tsx
+++ b/frontend/src/routes/editor/drawer/FieldFrame.tsx
@@ -20,8 +20,11 @@ interface Frame {
   local: string | null; // what the browser found: the control's text isn't saved
   problems: Diagnostic[];
   actions?: ReactNode;
+  name?: string; // the setting's own name, beside its label (4f-2b: a row of an update's changes)
 }
 
+const Name = ({ name }: { name: string | undefined }) => (name ? <span className="block font-mono text-meta text-muted">{name}</span> : null);
+
 const describing = (id: string, { hint, warn, local, problems }: Pick<Frame, "hint" | "warn" | "local" | "problems">) =>
   [hint !== null ? `${id}-hint` : null, warn ? `${id}-warn` : null, local !== null ? `${id}-local` : null, ...problems.map((_, i) => `${id}-p${i}`)]
     .filter((x): x is string => x !== null)
@@ -45,7 +48,7 @@ function Notes({ id, hint, warn, local, problems }: { id: string } & Pick<Frame,
 
 const Required = () => <span className="text-small text-muted">(required)</span>;
 
-export function FieldFrame({ label, required, hint, warn = null, local, problems, actions, below, children }: Frame & {
+export function FieldFrame({ label, name, required, hint, warn = null, local, problems, actions, below, children }: Frame & {
   below?: ReactNode;
   children: (control: Described) => ReactNode;
 }) {  // prettier-ignore
@@ -54,9 +57,10 @@ export function FieldFrame({ label, required, hint, warn = null, local, problems
   return (
     <div className="flex min-w-0 flex-col gap-1.5">
       <div className="flex flex-wrap items-center justify-between gap-2">
-        <span className="flex items-baseline gap-1">
+        <span className="flex flex-wrap items-baseline gap-x-1">
           <label htmlFor={id} className="text-small font-semibold">{label}</label>
           {required && <Required />}
+          {name && <span className="w-full"><Name name={name} /></span>}
         </span>
         {actions}
       </div>
@@ -67,17 +71,18 @@ export function FieldFrame({ label, required, hint, warn = null, local, problems
   );
 }
 
-export function GroupFrame({ label, required, hint, local, problems, actions, below, children }: Frame & {
+export function GroupFrame({ label, name, required, hint, warn = null, local, problems, actions, below, children }: Frame & {
   below?: ReactNode;
   children: ReactNode;
 }) {  // prettier-ignore
   const id = useId();
   return (
-    <fieldset aria-describedby={describing(id, { hint, local, problems })} className="flex min-w-0 flex-col gap-3">
+    <fieldset aria-describedby={describing(id, { hint, warn, local, problems })} className="flex min-w-0 flex-col gap-3">
       <legend className="text-small font-semibold">{label}</legend>
+      <Name name={name} />
       {required && <Required />}
       {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
-      <Notes id={id} hint={hint} local={local} problems={problems} />
+      <Notes id={id} hint={hint} warn={warn} local={local} problems={problems} />
       <div className="flex min-w-0 flex-col gap-4 pl-3">{children}</div>
       {below}
     </fieldset>
diff --git a/frontend/src/routes/editor/drawer/FieldView.tsx b/frontend/src/routes/editor/drawer/FieldView.tsx
index 2fb2cb24..8dffcc3f 100644
--- a/frontend/src/routes/editor/drawer/FieldView.tsx
+++ b/frontend/src/routes/editor/drawer/FieldView.tsx
@@ -87,12 +87,12 @@ const keepFocus = (e: MouseEvent) => e.preventDefault();
 /** A condition the builder writes (4c-2b): a formula field that gives true or false. */
 const builds = (spec: FieldSpec): boolean => spec.widget === "formula" && spec.base === "boolean" && canFormula(spec);
 
-const startMode = (spec: FieldSpec, value: unknown): Mode =>
+const startMode = (spec: FieldSpec, value: unknown, fixed = false): Mode =>
   builds(spec) ? (conditionOf(value) !== null || typeof value === "boolean" ? "fixed" : "formula")
   : kindOf(value) === "cel" ? "formula"
   : takesPills(spec) && segmentsOf(value) !== null && value !== undefined && value !== null ? "fixed"
   : value !== undefined && value !== null ? "fixed"
-  : startsAsFormula(spec) ? "formula" : "fixed";  // prettier-ignore
+  : startsAsFormula(spec) && !fixed ? "formula" : "fixed";  // prettier-ignore
 
 /** How the message composer draws one of its parts (4f-1, the message composer design §5): its own control (the
  * severity's choices) or its own rows (the fields', the links'), the text on several lines, a check said as it's typed
@@ -109,6 +109,17 @@ export interface Drawn {
   missing?: string; // said in place of "Required"
   warn?: string | null;
   below?: ReactNode;
+  // An update's changes and a create's settings (4f-2b): drawn as a group of `parts` even when it's a union (`group`),
+  // empty in Fixed (`startFixed`: a union is Set as JSON), its fixed side named ("List"), the parts it draws (`shown`:
+  // a problem at another stays on the group), its setting's name beside its label, its own actions, no Clear.
+  group?: boolean;
+  startFixed?: boolean;
+  fixedName?: string;
+  shown?: string[];
+  name?: string;
+  actions?: ReactNode;
+  hideClear?: boolean;
+  switchLabel?: string; // what its Fixed | Formula switch says it sets, when its label doesn't read well there
 }
 
 export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn }) {
@@ -116,7 +127,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
   const value = valueAt(drawer.node.config ?? {}, spec.path);
   const kind = kindOf(value);
   const empty = value === undefined || value === null;
-  const [chosen, setChosen] = useState<Mode>(() => startMode(spec, value));
+  const [chosen, setChosen] = useState<Mode>(() => startMode(spec, value, drawn.startFixed));
   const [local, setLocal] = useState<string | null>(null); // why the last write didn't happen
   const [touched, setTouched] = useState(false);
   const [asJson, setAsJson] = useState(false);
@@ -192,8 +203,8 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
   const fixed = fixedOf(value);
   // A literal's or an unreadable envelope's parts aren't where a form writes them: shown as JSON.
   const json = asJson || held?.kind === "json" || kind === "unknown" || (kind === "literal" && isContainer(spec.base));
-  const container = mode === "fixed" && fixedOk && !computed && !hidden && !json && isContainer(spec.base);
-  const problems = problemsAt(drawer.problems, spec.pointer, container ? new Set(partNames(spec, fixed)) : null);
+  const container = mode === "fixed" && fixedOk && !computed && !hidden && !json && (isContainer(spec.base) || drawn.group === true);
+  const problems = problemsAt(drawer.problems, spec.pointer, container ? new Set(drawn.shown ?? partNames(spec, fixed)) : null);
   const required = spec.required && !spec.entry && (spec.path.length > 1 || drawn.marked === true);
   const hint = drawn.hint !== undefined ? drawn.hint : spec.hint;
   const checked = drawn.check?.(value) ?? null; // said where a refusal would be, after it
@@ -234,7 +245,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
     <>
       {fixedOk && formulaOk && !computed && !hidden && (
         <ModeSwitch
-          label={spec.label} mode={mode} disabled={disabled} onChange={switchTo} fixedName={pills ? "Text" : builder ? "Builder" : "Fixed"}
+          label={drawn.switchLabel ?? spec.label} mode={mode} disabled={disabled} onChange={switchTo} fixedName={drawn.fixedName ?? (pills ? "Text" : builder ? "Builder" : "Fixed")}
           fixedWhyNot={builder && !buildable && held?.kind !== "condition" ? { id: whyNotId } : null}
         />
       )}
@@ -289,13 +300,14 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
           Discard
         </Button>
       )}
-      {!disabled && !spec.required && !spec.entry && value !== undefined && (
+      {!disabled && !spec.required && !spec.entry && value !== undefined && drawn.hideClear !== true && (
         <Button size="sm" aria-label={`Clear ${spec.label}`} onMouseDown={keepFocus} onClick={clear}>Clear</Button>
       )}
+      {drawn.actions}
     </>
   );
   const frame = (control: (c: Described) => ReactNode, said: string | null = hint, below: ReactNode = drawn.below) => (
-    <FieldFrame label={spec.label} required={required} hint={said} warn={drawn.warn} local={stale ? STALE : (held?.why ?? local ?? missing ?? checked)} problems={problems} actions={actions} below={below}>
+    <FieldFrame label={spec.label} name={drawn.name} required={required} hint={said} warn={drawn.warn} local={stale ? STALE : (held?.why ?? local ?? missing ?? checked)} problems={problems} actions={actions} below={below}>
       {control}
     </FieldFrame>
   );
@@ -417,7 +429,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
     );
   } else if (container) {
     body = (
-      <GroupFrame label={spec.label} required={required} hint={hint} local={local ?? missing} problems={problems} actions={actions}>
+      <GroupFrame label={spec.label} name={drawn.name} required={required} hint={hint} warn={drawn.warn} local={local ?? missing} problems={problems} actions={actions} below={drawn.below}>
         {drawn.parts ? drawn.parts(spec, fixed) : <ContainerParts spec={spec} value={fixed} />}
       </GroupFrame>
     );
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 53 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/editor/drawer/FieldView.tsx frontend/src/routes/editor/drawer/FieldFrame.tsx frontend/src/routes/editor/drawer/FieldView.test.tsx
git commit -m "feat(editor): a field drawn as a group of chosen parts, with its name and its own actions (4f-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Milestone 1 ends here: append `### 4f-2b, milestone 1 (<date>)` to the ledger (each task's commit, its red and green
as run, the static checks, mid-slice rulings, nothing pushed), commit it, and pause for the owner's review.

# Milestone 2 — The changes' list

### Task 5: The rows' model

**Spec:** §5.3, §5.5, §5.7, §5.9; rulings 6, 10, 11, 17, 19.

**Files:**
- Create: `frontend/src/lib/changes.ts`, `frontend/src/lib/changes.test.ts`

**Interfaces:**
- Consumes: `fixedOf`, `kindOf` (as `envelopeOf`), `referenceText` (`lib/config.ts`); `isObject`, `FieldSpec`.
- Produces (`lib/changes.ts`): `type RowState = "set" | "clear" | "pending" | "both"`; `interface Row { name; spec;
  state }`; `interface Memory { cleared; pending; shown; entries; kind }` and `NO_MEMORY`; `bodyObject(config)`,
  `clearNames(config)`; `rowsOf(specs, body, clear, pending)`; `setIn(config, name, value)`, `clearIn(config, name)`,
  `keepIn(config, name)`; `changedCount(rows)`; `kindIndex(widget, body, listed, kind, offered, chosen)`,
  `kindIn(config, kind, to, offered, write)`; `WORDS` (every sentence of §5.3–§5.9, `count(widget, n, of)`,
  `kindChanged(title, kept, dropped)`); `brief(spec, value)`; `summaryOf(widget, rows, body, mode, partsOf)`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/changes.test.ts b/frontend/src/lib/changes.test.ts
new file mode 100644
index 00000000..7cb69033
--- /dev/null
+++ b/frontend/src/lib/changes.test.ts
@@ -0,0 +1,96 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import { DEVICE_UPDATE, UPDATE } from "../test/nodeTypes";
+import {
+  WORDS, bodyObject, brief, changedCount, clearIn, clearNames, keepIn, kindIn, kindIndex, rowsOf, setIn, summaryOf,
+} from "./changes";  // prettier-ignore
+import { formula } from "./config";
+import { branchesOf, fieldsOf, kindOf, offeredOf, propertiesOf } from "./schemaForm";
+
+const body = fieldsOf(UPDATE).find((f) => f.name === "body")!;
+const offered = offeredOf(body);
+
+describe("rows", () => {
+  it("lists each setting set, cleared or added, by title, with what it does", () => {
+    const rows = rowsOf(offered, { rogue: { enabled: true }, name: "hq" }, ["tags"], ["vlan_id"]);
+    expect(rows.map((r) => [r.spec.label, r.state])).toEqual([["Name", "set"], ["Rogue", "set"], ["Tags", "clear"], ["VLAN ID", "pending"]]);
+    expect(changedCount(rows)).toBe(3);
+  });
+  it("says a setting both set and cleared, and leaves out what the schema doesn't describe or Mist sets", () => {
+    const rows = rowsOf(offered, { name: "hq", id: "x", nope: 1 }, ["name"], []);
+    expect(rows.map((r) => [r.name, r.state])).toEqual([["name", "both"]]);
+  });
+  it("reads only a plain body and a plain list of names", () => {
+    expect(bodyObject({})).toEqual({});
+    expect(bodyObject({ body: formula("steps.x.output") })).toBeNull();
+    expect(clearNames({ clear: ["a"] })).toEqual(["a"]);
+    expect(clearNames({ clear: formula("[]") })).toBeNull();
+  });
+});
+
+describe("one write each", () => {
+  it("sets, clears and keeps a setting in the body and `clear` together", () => {
+    const start = { mode: "merge", body: { name: "hq", rogue: { enabled: true } } };
+    const cleared = clearIn(start, "rogue");
+    expect(cleared).toEqual({ mode: "merge", body: { name: "hq" }, clear: ["rogue"] });
+    expect(setIn(cleared, "rogue", { enabled: true })).toEqual(start);
+    expect(setIn(cleared, "rogue", undefined)).toEqual({ mode: "merge", body: { name: "hq" } }); // Set, nothing given yet
+    expect(keepIn(cleared, "rogue")).toEqual({ mode: "merge", body: { name: "hq" } });
+    expect(keepIn(start, "name")).toEqual({ mode: "merge", body: { rogue: { enabled: true } } });
+  });
+  it("never writes into a body a formula gives", () => {
+    const start = { body: formula("steps.x.output"), clear: ["tags"] };
+    expect(clearIn(start, "name")).toEqual({ body: formula("steps.x.output"), clear: ["tags", "name"] });
+    expect(keepIn(start, "tags")).toEqual({ body: formula("steps.x.output") });
+  });
+});
+
+describe("a device's kind", () => {
+  const device = fieldsOf(DEVICE_UPDATE).find((f) => f.name === "body")!;
+  const branches = branchesOf(device);
+  const kind = kindOf(branches)!;
+  const names = branches.map((b) => offeredOf(b, kind.name).map((p) => p.name));
+
+  it("reads an update's kind from its value, the one chosen, the settings listed, else the first", () => {
+    expect(kindIndex("update", { type: "sensor" }, [], kind, names, "camera")).toBe(1);
+    expect(kindIndex("update", {}, ["name"], kind, names, "sensor")).toBe(1);
+    expect(kindIndex("update", { range: 3 }, ["range"], kind, names, null)).toBe(1);
+    expect(kindIndex("update", { name: "a" }, ["name"], kind, names, null)).toBe(0);
+    expect(kindIndex("create", { name: "a" }, ["name"], kind, names, "sensor")).toBeNull();
+  });
+  it("keeps the changes the new kind has, drops the others, and writes its value where it's held", () => {
+    const start = { body: { name: "a", zoom: 2 }, clear: ["notes"] };
+    expect(kindIn(start, kind, 1, names[1]!, false)).toEqual({ config: { body: { name: "a" }, clear: ["notes"] }, kept: ["name", "notes"], dropped: ["zoom"] });
+    expect(kindIn({ body: { type: "camera", zoom: 2 } }, kind, 1, names[1]!, true).config).toEqual({ body: { type: "sensor" } });
+  });
+  it("says what a change of kind kept and dropped", () => {
+    expect(WORDS.kindChanged("Sensor", ["Name", "Notes"], ["Zoom"])).toBe("Kind changed to Sensor: Name and Notes are kept; Zoom is dropped, as a Sensor doesn't have it.");
+    expect(WORDS.kindChanged("Sensor", [], ["Zoom", "Mode"])).toBe("Kind changed to Sensor: Zoom and Mode are dropped, as a Sensor doesn't have them.");
+    expect(WORDS.kindChanged("Sensor", ["Name"], [])).toBe("Kind changed to Sensor: every change is kept.");
+  });
+});
+
+describe("words", () => {
+  it("counts an update's changes and a create's settings", () => {
+    expect(WORDS.count("update", 3, 93)).toBe("3 of 93 settings change; the others stay as they are.");
+    expect(WORDS.count("create", 3, 95)).toBe("3 of 95 settings given; Mist uses its defaults for the others.");
+  });
+  it("sums up the changes for a read-only view", () => {
+    const config = { body: { name: "hq", auto_upgrade: { enabled: true, version: "stable", custom: { ap41: "1.2" } }, api_secret: "x" }, clear: ["tags"] };
+    const rows = rowsOf(offered, config.body, config.clear, []);
+    expect(summaryOf("update", rows, config.body, "replace", propertiesOf)).toEqual({
+      head: "Replace them · 4 changes",
+      lines: [
+        { name: "api_secret", label: "API secret", text: "set: a sensitive value" },
+        { name: "auto_upgrade", label: "Auto upgrade", text: "set: Enabled yes, Version stable, Custom versions 1 setting" },
+        { name: "name", label: "Name", text: "set: hq" },
+        { name: "tags", label: "Tags", text: "cleared" },
+      ],
+    });
+    expect(summaryOf("create", rows.slice(2, 3), config.body, undefined, propertiesOf).head).toBe("1 setting given");
+  });
+  it("says a value in a few words", () => {
+    expect(brief(undefined, { $value: { kind: "ref", path: "steps.get_site.output.id" } })).toBe("steps.get_site.output.id");
+    expect([brief(undefined, false), brief(undefined, [1, 2]), brief(undefined, formula("1"))]).toEqual(["no", "2 items", "computed when the step runs"]);
+  });
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/changes.test.ts`
Expected: FAIL: the test can't import its module (`Failed to resolve import "./changes"`; no test runs).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/changes.ts b/frontend/src/lib/changes.ts
new file mode 100644
index 00000000..351cad45
--- /dev/null
+++ b/frontend/src/lib/changes.ts
@@ -0,0 +1,193 @@
+// SPDX-License-Identifier: Apache-2.0
+// An update's changes and a create's settings, as rows (4f-2, the Mist step design §5.3–§5.9): what the config says
+// (its `body`'s settings, the names in its `clear`) and what the drawer remembers until it closes (a setting added with
+// nothing given yet, a value set before it was cleared, an update's kind). Each change is one write of the whole
+// config: one step of Undo, `body` and `clear` together. Nothing here draws.
+import { fixedOf, kindOf as envelopeOf, referenceText } from "./config";
+import { isObject, type FieldSpec } from "./schemaForm";
+
+/** What a setting's row does: Set (in the body), Clear (named in `clear`), Set with nothing given yet (remembered
+ * only), or both set and cleared (a draft from elsewhere: Mist refuses it). */
+export type RowState = "set" | "clear" | "pending" | "both";
+export interface Row {
+  name: string;
+  spec: FieldSpec;
+  state: RowState;
+}
+
+/** What the drawer remembers of the changes until it closes (the tabs unmount what they hide). */
+export interface Memory {
+  cleared: Record<string, unknown>; // a value set before its setting was cleared: Set brings it back
+  pending: string[]; // settings added, nothing given yet
+  shown: Record<string, string[]>; // an object's parts added, nothing given yet, by the object's pointer
+  entries: Record<string, string[]>; // a map's entries opened, nothing given yet, by the map's pointer
+  kind: string | null; // an update's kind, chosen here
+}
+export const NO_MEMORY: Memory = { cleared: {}, pending: [], shown: {}, entries: {}, kind: null };
+
+type Config = Record<string, unknown>;
+
+/** The body's settings, when it's a plain object the list can draw (not a formula, a reference or a literal). */
+export function bodyObject(config: Config): Record<string, unknown> | null {
+  const body = config.body;
+  if (body === undefined) return {};
+  return isObject(body) && envelopeOf(body) === null ? body : null;
+}
+
+/** The names `clear` holds, when it's a plain list of names. */
+export function clearNames(config: Config): string[] | null {
+  const clear = config.clear;
+  if (clear === undefined) return [];
+  return Array.isArray(clear) && clear.every((n): n is string => typeof n === "string") ? clear : null;
+}
+
+/** A row per setting given, cleared or added, of the ones the schema describes; by title. */
+export function rowsOf(specs: FieldSpec[], body: Record<string, unknown>, clear: string[], pending: string[]): Row[] {
+  const names = new Set([...Object.keys(body), ...clear, ...pending]);
+  return specs
+    .filter((s) => names.has(s.name))
+    .map((spec): Row => {
+      const set = spec.name in body;
+      const cleared = clear.includes(spec.name);
+      return { name: spec.name, spec, state: set && cleared ? "both" : set ? "set" : cleared ? "clear" : "pending" };
+    })
+    .sort((a, b) => a.spec.label.localeCompare(b.spec.label) || a.name.localeCompare(b.name));
+}
+
+const withClear = (config: Config, names: string[]): Config => {
+  const rest = Object.fromEntries(Object.entries(config).filter(([k]) => k !== "clear"));
+  return names.length > 0 ? { ...rest, clear: names } : rest;
+};
+const withBody = (config: Config, body: Record<string, unknown>): Config => ({ ...config, body });
+const without = (body: Record<string, unknown>, name: string) => Object.fromEntries(Object.entries(body).filter(([k]) => k !== name));
+
+/** Set: in the body (with `value`, when one is given), out of `clear`. */
+export function setIn(config: Config, name: string, value: unknown): Config {
+  const body = bodyObject(config) ?? {};
+  const next = value === undefined ? body : { ...body, [name]: value };
+  return withClear(withBody(config, next), (clearNames(config) ?? []).filter((n) => n !== name));
+}
+
+/** Clear: out of the body, named in `clear`. */
+export function clearIn(config: Config, name: string): Config {
+  const names = clearNames(config) ?? [];
+  const body = bodyObject(config);
+  const next = body === null ? config : withBody(config, without(body, name));
+  return withClear(next, names.includes(name) ? names : [...names, name]);
+}
+
+/** Keep: neither set nor cleared. */
+export function keepIn(config: Config, name: string): Config {
+  const body = bodyObject(config);
+  const next = body === null ? config : withBody(config, without(body, name));
+  return withClear(next, (clearNames(config) ?? []).filter((n) => n !== name));
+}
+
+/** How many settings change: set with a value, or cleared. */
+export const changedCount = (rows: Row[]): number => rows.filter((r) => r.state !== "pending").length;
+
+/** The branch an update's body is, by its kind's value when the draft holds it, else the one chosen here, else the
+ * first that has every setting listed, else the first. A create's, only by its kind's value. */
+export function kindIndex(
+  widget: "update" | "create", body: Record<string, unknown>, listed: string[], kind: { name: string; values: string[] },
+  offered: string[][], chosen: string | null,
+): number | null {  // prettier-ignore
+  const held = kind.values.indexOf(String(fixedOf(body[kind.name])));
+  if (held >= 0) return held;
+  if (widget === "create") return null;
+  const picked = chosen === null ? -1 : kind.values.indexOf(chosen);
+  if (picked >= 0) return picked;
+  const fits = offered.findIndex((names) => listed.every((n) => names.includes(n)));
+  return fits >= 0 ? fits : 0;
+}
+
+/** Another kind: the changes it has too are kept, the others dropped; the kind's value written where it's held (a
+ * draft that has it, a create's). */
+export function kindIn(
+  config: Config, kind: { name: string; values: string[] }, to: number, offered: string[], write: boolean,
+): { config: Config; kept: string[]; dropped: string[] } {  // prettier-ignore
+  const body = bodyObject(config) ?? {};
+  const clear = clearNames(config) ?? [];
+  const listed = [...new Set([...Object.keys(body).filter((n) => n !== kind.name), ...clear])];
+  const kept = listed.filter((n) => offered.includes(n));
+  const dropped = listed.filter((n) => !offered.includes(n));
+  const nextBody = Object.fromEntries(Object.entries(body).filter(([k]) => k === kind.name || offered.includes(k)));
+  const written = write ? { ...nextBody, [kind.name]: kind.values[to] } : nextBody;
+  return { config: withClear(withBody(config, written), clear.filter((n) => offered.includes(n))), kept, dropped };
+}
+
+const joinedWords = (words: string[]): string =>
+  words.length <= 1 ? (words[0] ?? "") : `${words.slice(0, -1).join(", ")} and ${words[words.length - 1]}`;
+
+/** The changes' words (§5.3–§5.9). */
+export const WORDS = {
+  merge: "Merge with the current settings",
+  replace: "Replace them",
+  mergeSays: "Merge reads the current settings when the step runs and keeps the parts of each setting below that you don't give. A change made in Mist in between may be overwritten.",
+  replaceSays: "Replace sends each setting below as written: the parts you don't give go back to Mist's defaults. Settings not listed stay as they are.",
+  partsMerge: "Its parts left empty stay as they are: merge changes only those given.",
+  partsReplace: "Its parts left empty go back to Mist's defaults: replace sends it as written.",
+  wholeList: "A list is sent whole: it replaces the current one, and an item's parts left empty go back to Mist's defaults.",
+  cleared: "Sent empty: Mist removes this setting.",
+  pending: "Nothing given yet: it isn't sent.",
+  both: "Both set and cleared: Mist refuses this when it runs. Choose Set or Clear.",
+  nothing: "Nothing to change yet: add a setting to set, or one to clear. An update that changes nothing fails when it runs.",
+  json: "As JSON: Mist takes it in more than one shape.",
+  changesOnSetup: "The changes are on Setup.",
+  settingsOnSetup: "The settings are on Setup.",
+  formulaUpdate: "Computed when the step runs: the settings it gives are set; with merge, the parts it leaves out stay as they are.",
+  formulaCreate: "Computed when the step runs: the settings it gives are sent; Mist uses its defaults for the others.",
+  chooseKind: "Choose the kind first: its settings follow.",
+  count: (widget: "update" | "create", n: number, of: number) =>
+    widget === "update"
+      ? `${n} of ${of} settings change; the others stay as they are.`
+      : `${n} of ${of} settings given; Mist uses its defaults for the others.`,
+  kindChanged: (title: string, kept: string[], dropped: string[]) =>
+    dropped.length === 0
+      ? `Kind changed to ${title}: every change is kept.`
+      : kept.length === 0
+        ? `Kind changed to ${title}: ${joinedWords(dropped)} ${dropped.length === 1 ? "is" : "are"} dropped, as a ${title} doesn't have ${dropped.length === 1 ? "it" : "them"}.`
+        : `Kind changed to ${title}: ${joinedWords(kept)} ${kept.length === 1 ? "is" : "are"} kept; ${joinedWords(dropped)} ${dropped.length === 1 ? "is" : "are"} dropped, as a ${title} doesn't have ${dropped.length === 1 ? "it" : "them"}.`,
+};
+
+/** A value in a few words, for a read-only summary: yes or no, the text, a value's source, a part's count. */
+export function brief(spec: FieldSpec | undefined, value: unknown): string {
+  if (spec?.sensitive) return "a sensitive value";
+  const kind = envelopeOf(value);
+  if (kind === "ref" || kind === "template") return referenceText(value);
+  if (kind === "cel") return "computed when the step runs";
+  const fixed = fixedOf(value);
+  if (typeof fixed === "boolean") return fixed ? "yes" : "no";
+  if (typeof fixed === "string" || typeof fixed === "number") return String(fixed);
+  if (Array.isArray(fixed)) return fixed.length === 1 ? "1 item" : `${fixed.length} items`;
+  if (isObject(fixed)) return Object.keys(fixed).length === 1 ? "1 setting" : `${Object.keys(fixed).length} settings`;
+  return "empty";
+}
+
+/** What a read-only view says of the changes (§5.9): how they're sent and how many, then a line per setting. */
+export function summaryOf(
+  widget: "update" | "create", rows: Row[], body: Record<string, unknown>, mode: unknown, partsOf: (spec: FieldSpec) => FieldSpec[],
+): { head: string; lines: { name: string; label: string; text: string }[] } {  // prettier-ignore
+  const n = changedCount(rows);
+  const head =
+    widget === "update"
+      ? `${fixedOf(mode) === "replace" ? WORDS.replace : WORDS.merge} · ${n === 1 ? "1 change" : `${n} changes`}`
+      : `${n === 1 ? "1 setting" : `${n} settings`} given`;
+  const lines = rows
+    .filter((r) => r.state !== "pending")
+    .map((r) => {
+      if (r.state === "clear") return { name: r.name, label: r.spec.label, text: "cleared" };
+      const value = fixedOf(body[r.name]);
+      const parts = r.spec.base === "group" && isObject(value) && envelopeOf(value) === null ? partsOf(r.spec) : null;
+      const said = parts
+        ? Object.entries(value as Record<string, unknown>)
+            .map(([k, v]) => {
+              const part = parts.find((p) => p.name === k);
+              return `${part?.label ?? k} ${brief(part, v)}`;
+            })
+            .join(", ")
+        : brief(r.spec, body[r.name]);
+      return { name: r.name, label: r.spec.label, text: `${r.state === "both" ? "set and cleared" : "set"}: ${said}` };
+    });
+  return { head, lines };
+}
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 11 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/changes.ts frontend/src/lib/changes.test.ts
git commit -m "feat(editor): an update's changes as rows, each change one write of the whole config (4f-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The Changes widget

**Spec:** §5.3, §5.5, §5.8, §5.9, §5.10; rulings 7–11, 16, 19, 20.

**Files:**
- Create: `frontend/src/routes/editor/drawer/Changes.tsx`, `frontend/src/routes/editor/drawer/Changes.test.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (the memory; `<Changes>` on Setup and on a run's page),
  `frontend/src/routes/editor/drawer/FieldView.tsx` (a formula's frame keeps `drawn.below`)

**Interfaces:**
- Consumes: Task 2's `Changes` parts, `offeredOf`; Task 4's `Drawn`; Task 5's rows, transforms, `WORDS`,
  `summaryOf`, `Memory`, `NO_MEMORY`; `problemsAt`, `useDrawer` (`drawer/context.ts`).
- Produces: `Changes({ parts, memory, onMemory })`, `onMemory: (next: Memory) => void` here (Task 8 makes it an
  updater); the rows' region carries `data-pointer="/clear"`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/drawer/Changes.test.tsx b/frontend/src/routes/editor/drawer/Changes.test.tsx
new file mode 100644
index 00000000..80d90b1f
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/Changes.test.tsx
@@ -0,0 +1,130 @@
+// SPDX-License-Identifier: Apache-2.0
+import { screen, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, expect, it, vi } from "vitest";
+import { WORDS } from "../../../lib/changes";
+import { formula } from "../../../lib/config";
+import { CREATE, UPDATE } from "../../../test/nodeTypes";
+import { fakeApi, json, problem, showDrawer } from "./harness";
+
+beforeEach(() => {
+  fakeApi({ "GET /api/v1/t/t1/connections": () => json([]), "GET /api/v1/connection-types": () => json([]) });
+});
+afterEach(() => {
+  vi.restoreAllMocks();
+});
+
+const changes = () => screen.getByRole("group", { name: "Changes" });
+/** The rows, in order: each one's pointer under the body. */
+const rows = (group: HTMLElement) =>
+  [...group.querySelectorAll<HTMLElement>("[data-pointer^='/body/']")].map((e) => e.dataset.pointer!).filter((p) => p.split("/").length === 3);
+
+it("draws an update's changes: how they're sent, a row per setting set or cleared, by title, and how many change", () => {
+  showDrawer(UPDATE, { config: { mode: "merge", body: { rogue: { enabled: true }, name: "hq" }, clear: ["tags"] } });
+  const group = changes();
+  expect(within(group).getByRole("radio", { name: WORDS.merge })).toHaveProperty("checked", true);
+  expect(within(group).getByText(WORDS.mergeSays)).toBeTruthy();
+  expect(rows(group)).toEqual(["/body/name", "/body/rogue", "/body/tags"]);
+  const name = group.querySelector<HTMLElement>('[data-pointer="/body/name"]')!;
+  expect(within(name).getByText("name").className).toContain("font-mono");
+  expect(within(name).getByRole("group", { name: "What happens to Name" })).toBeTruthy();
+  expect(within(group.querySelector<HTMLElement>('[data-pointer="/body/tags"]')!).getByText(WORDS.cleared)).toBeTruthy();
+  expect(within(group).getByText("3 of 10 settings change; the others stay as they are.")).toBeTruthy();
+});
+
+it("says replace's warning when replace is chosen", async () => {
+  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq" } } });
+  await userEvent.click(within(changes()).getByRole("radio", { name: WORDS.replace }));
+  expect(config().mode).toBe("replace");
+  expect(within(changes()).getByText(WORDS.replaceSays)).toBeTruthy();
+  expect(within(changes()).queryByText(WORDS.mergeSays)).toBeNull();
+});
+
+it("clears a setting and sets it back with the value it had, body and clear together", async () => {
+  const { config } = showDrawer(UPDATE, { config: { mode: "merge", body: { name: "hq", enabled: true } } });
+  const name = () => within(changes()).getByRole("group", { name: "What happens to Name" });
+  await userEvent.click(within(name()).getByRole("button", { name: "Clear" }));
+  expect(config()).toEqual({ mode: "merge", body: { enabled: true }, clear: ["name"] });
+  expect(within(name()).getByRole("button", { name: "Clear" }).getAttribute("aria-pressed")).toBe("true");
+  await userEvent.click(within(name()).getByRole("button", { name: "Set" }));
+  expect(config()).toEqual({ mode: "merge", body: { enabled: true, name: "hq" } });
+});
+
+it("keeps a setting as it is: its row goes, and the count with it", async () => {
+  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq", rogue: { enabled: true } }, clear: ["tags"] } });
+  await userEvent.click(within(changes()).getByRole("button", { name: "Keep Rogue as it is" }));
+  await userEvent.click(within(changes()).getByRole("button", { name: "Keep Tags as it is" }));
+  expect(config()).toEqual({ body: { name: "hq" } });
+  expect(rows(changes())).toEqual(["/body/name"]);
+  expect(within(changes()).getByText("1 of 10 settings change; the others stay as they are.")).toBeTruthy();
+});
+
+it("says there's nothing to change, as a warning, when nothing is set or cleared", () => {
+  showDrawer(UPDATE, { config: { mode: "merge" } });
+  expect(within(changes()).getByText(WORDS.nothing).className).toContain("text-warn-ink");
+  expect(within(changes()).getByText("0 of 10 settings change; the others stay as they are.")).toBeTruthy();
+});
+
+it("says a setting both set and cleared, and settles it with Set or Clear", async () => {
+  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq" }, clear: ["name"] } });
+  expect(within(changes()).getByText(WORDS.both)).toBeTruthy();
+  await userEvent.click(within(within(changes()).getByRole("group", { name: "What happens to Name" })).getByRole("button", { name: "Set" }));
+  expect(config()).toEqual({ body: { name: "hq" } });
+});
+
+it("draws a body a formula gives as a formula, its cleared settings still listed", () => {
+  showDrawer(UPDATE, { config: { body: formula("steps.build.output"), clear: ["tags"] } });
+  expect(within(screen.getByRole("group", { name: "How Changes is set" })).getByRole("button", { name: "Formula" }).getAttribute("aria-pressed")).toBe("true");
+  expect(screen.getByText(WORDS.formulaUpdate)).toBeTruthy();
+  expect(screen.getByText(WORDS.cleared)).toBeTruthy();
+  expect(screen.getByRole("radiogroup", { name: "How the changes are sent" })).toBeTruthy();
+});
+
+it("leaves a `clear` naming what the list doesn't offer to today's control, unchanged", () => {
+  const { config } = showDrawer(UPDATE, { config: { body: { name: "hq" }, clear: ["id"] } });
+  expect(screen.getByRole("group", { name: "Fields to clear" })).toBeTruthy();
+  expect(rows(changes())).toEqual(["/body/name"]);
+  expect(config().clear).toEqual(["id"]); // opening never rewrites (ledger 102)
+});
+
+it("sets a setting of several shapes as JSON in its row", () => {
+  showDrawer(UPDATE, { config: { body: { vlan_id: 10 } } });
+  const row = changes().querySelector<HTMLElement>('[data-pointer="/body/vlan_id"]')!;
+  expect(within(row).getByRole("textbox", { name: "VLAN ID" })).toHaveProperty("value", "10");
+  expect(within(row).getByText(/As JSON: Mist takes it in more than one shape\./)).toBeTruthy(); // before the JSON field's own note
+});
+
+it("leaves how they're sent, held as a formula, to its formula, its switch named for it", () => {
+  showDrawer(UPDATE, { config: { mode: formula('"replace"'), body: { name: "hq" } } });
+  const switcher = screen.getByRole("group", { name: "How the way they're sent is set" });
+  expect(within(switcher).getByRole("button", { name: "Formula" }).getAttribute("aria-pressed")).toBe("true");
+});
+
+it("keeps a problem at a setting the list doesn't draw on the changes", () => {
+  showDrawer(UPDATE, { config: { body: { id: "x", name: "hq" } }, problems: [problem("/body/id", "Mist sets it.")] });
+  expect(within(changes()).getByText("Mist sets it.")).toBeTruthy();
+});
+
+it("sums up the changes in a read-only view, with nothing to press", () => {
+  showDrawer(UPDATE, { editable: false, config: { mode: "merge", body: { name: "hq", rogue: { enabled: true, min_rogue_rssi: -80 } }, clear: ["tags"] } });
+  const group = changes();
+  expect(within(group).getByText("Merge with the current settings · 3 changes")).toBeTruthy();
+  expect(within(group).getByText("set: Enabled yes, Min rogue RSSI -80")).toBeTruthy();
+  expect(within(group).getByText("cleared")).toBeTruthy();
+  expect(within(group).queryByRole("button", { name: /^Keep/ })).toBeNull();
+});
+
+it("draws a create's settings: a row per setting given, Remove unless it's required, how many are given", async () => {
+  const { config } = showDrawer(CREATE, { config: { body: { name: "n", enabled: true } } });
+  const group = screen.getByRole("group", { name: "Settings" });
+  expect(within(group).queryByRole("group", { name: /^What happens to/ })).toBeNull();
+  expect(within(group).queryByRole("button", { name: "Remove Name" })).toBeNull(); // required
+  expect(within(group).getByText("2 of 10 settings given; Mist uses its defaults for the others.")).toBeTruthy();
+  await userEvent.click(within(group).getByRole("button", { name: "Remove Enabled" }));
+  expect(config()).toEqual({ body: { name: "n" } });
+});
+
+it("shows a problem at `clear` with the rows that hold it", () => {
+  showDrawer(UPDATE, { config: { clear: ["name"] }, problems: [problem("/clear", "Not a list of names.")] });
+  expect(within(changes().querySelector<HTMLElement>('[data-pointer="/clear"]')!).getByText("Not a list of names.")).toBeTruthy();
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/drawer/Changes.test.tsx
src/routes/editor/drawer/StepDrawer.test.tsx`
Expected: FAIL, 14 failed and 4 passed: there's no "Changes" group (`Unable to find an accessible element with the role
"group" and name "Changes"`, eleven tests), no "Settings" group, no switch for the body or for how they're sent.
`StepDrawer.test.tsx`'s four pass: Task 2's placement holds.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/routes/editor/drawer/Changes.tsx b/frontend/src/routes/editor/drawer/Changes.tsx
new file mode 100644
index 00000000..7a6aa685
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/Changes.tsx
@@ -0,0 +1,197 @@
+// SPDX-License-Identifier: Apache-2.0
+// An update's changes and a create's settings (4f-2, the Mist step design §5.3–§5.9): one fieldset on Setup, the body
+// drawn as a row per setting it sets or clears, by title, never all its settings at once. The body is the drawer's own
+// field: List or Formula, what's typed, held or computed behaves as everywhere, and a body it can't draw as a list shows
+// today's control (ledger 102). Each row's setting is the drawer's own field too, its name beside its title; Set, Clear
+// and Keep change `body` and `clear` together, one step of Undo. What it remembers until the drawer closes (a value set
+// before it was cleared, a setting added with nothing given) lives above the tabs, which unmount what they hide.
+import { type ReactNode } from "react";
+import { Button } from "../../../components/Button";
+import {
+  WORDS, bodyObject, changedCount, clearIn, clearNames, keepIn, rowsOf, setIn, summaryOf, type Memory, type Row,
+} from "../../../lib/changes";  // prettier-ignore
+import { fixedOf, valueAt } from "../../../lib/config";
+import { isObject, offeredOf, propertiesOf, type Changes as Parts, type FieldSpec } from "../../../lib/schemaForm";
+import { problemsAt, useDrawer } from "./context";
+import { FieldView } from "./FieldView";
+import type { ControlProps } from "./scalars";
+
+const NARROW = "max-sm:min-h-[44px]"; // 44 px targets at 320 (§5.11), in pixels: a rem is 14 px here
+
+/** How they're sent: merge or replace, a radio pair, merge when unset (`mode`'s default); stacked at 320 px. */
+function ModeControl({ value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
+  const current = value === "replace" ? "replace" : "merge";
+  return (
+    <div
+      id={id} role="radiogroup" aria-label="How the changes are sent" aria-describedby={describedBy} aria-invalid={invalid} tabIndex={-1}
+      className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap"
+    >
+      {(["merge", "replace"] as const).map((choice) => (
+        <label key={choice} className={`flex min-h-[24px] items-center gap-2 rounded-lg border border-line-control px-3 text-body ${NARROW}`}>
+          <input type="radio" name={id} value={choice} checked={current === choice} disabled={disabled} onChange={() => onChange(choice, false)} />
+          {choice === "merge" ? WORDS.merge : WORDS.replace}
+        </label>
+      ))}
+    </div>
+  );  // prettier-ignore
+}
+
+/** A row's Set | Clear and Keep (an update's), or Remove (a create's, unless the setting is required). */
+function RowActions({ row, update, onSet, onClear, onKeep }: {
+  row: Row; update: boolean; onSet: () => void; onClear: () => void; onKeep: () => void;
+}) {  // prettier-ignore
+  const drawer = useDrawer();
+  if (!drawer.editable) return null;
+  if (!update) {
+    return row.spec.required ? null : (
+      <Button size="sm" aria-label={`Remove ${row.spec.label}`} className={NARROW} onClick={onKeep}>Remove</Button>
+    );
+  }
+  const choice = "min-h-[28px] px-2.5 text-small aria-pressed:bg-accent-soft aria-pressed:font-semibold aria-pressed:text-accent-ink " + NARROW;
+  return (
+    <span className="flex flex-wrap items-center gap-2">
+      <span role="group" aria-label={`What happens to ${row.spec.label}`} className="inline-flex overflow-hidden rounded-md border border-line-strong">
+        <button type="button" aria-pressed={row.state === "set" || row.state === "pending"} className={choice} onClick={onSet}>Set</button>
+        <button type="button" aria-pressed={row.state === "clear"} className={`${choice} border-l border-line-strong`} onClick={onClear}>Clear</button>
+      </span>
+      <Button size="sm" aria-label={`Keep ${row.spec.label} as it is`} className={NARROW} onClick={onKeep}>Keep</Button>
+    </span>
+  );  // prettier-ignore
+}
+
+/** A row that draws no value: cleared, or both set and cleared. */
+function SaidRow({ row, actions, said }: { row: Row; actions: ReactNode; said: string }) {
+  return (
+    <div data-pointer={row.spec.pointer} className="flex min-w-0 flex-col gap-1.5">
+      <div className="flex flex-wrap items-start justify-between gap-2">
+        <span className="flex flex-col">
+          <span className="text-small font-semibold">{row.spec.label}</span>
+          <span className="font-mono text-meta text-muted">{row.name}</span>
+        </span>
+        {actions}
+      </div>
+      <p className="text-small">{said}</p>
+    </div>
+  );
+}
+
+export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Memory; onMemory: (next: Memory) => void }) {
+  const drawer = useDrawer();
+  const config = drawer.node.config ?? {};
+  const update = parts.widget === "update";
+  const label = update ? "Changes" : "Settings";
+  const body = bodyObject(config);
+  const names = clearNames(config);
+  const offered = offeredOf(parts.body);
+  // A `clear` naming what the list doesn't offer is a draft from elsewhere: today's control, unchanged (§5.8).
+  const clearDrawn = parts.clear !== null && names !== null && names.every((n) => offered.some((s) => s.name === n));
+  const rows = rowsOf(offered, body ?? {}, clearDrawn ? names : [], memory.pending);
+  const replace = fixedOf(valueAt(config, ["mode"])) === "replace";
+  const nothing = update && body !== null && rows.every((r) => r.state === "pending");
+
+  // One write of the whole config: `body` and `clear` together, one step of Undo. What's typed under the row is
+  // dropped first by Clear and Keep (what it would write goes with the row), applied first by Set.
+  const change = (row: Row, make: (cfg: Record<string, unknown>) => Record<string, unknown>, drop: boolean) => {
+    if (drop) drawer.discard(row.spec.pointer);
+    return drawer.restructure(row.spec.pointer, { path: [], make: (cfg) => make(isObject(cfg) ? cfg : {}) });
+  };
+  const remember = (next: Partial<Memory>) => onMemory({ ...memory, ...next });
+  const set = (row: Row) => {
+    if (row.state === "set") return;
+    const value = row.state === "both" ? (body ?? {})[row.name] : memory.cleared[row.name];
+    if (change(row, (cfg) => setIn(cfg, row.name, value), false) === null && value === undefined) {
+      remember({ pending: [...memory.pending.filter((n) => n !== row.name), row.name] });
+    }
+  };
+  const clear = (row: Row) => {
+    if (row.state === "clear") return;
+    const value = (body ?? {})[row.name];
+    if (change(row, (cfg) => clearIn(cfg, row.name), true) === null) {
+      remember({ cleared: value === undefined ? memory.cleared : { ...memory.cleared, [row.name]: value }, pending: memory.pending.filter((n) => n !== row.name) });
+    }
+  };
+  const keep = (row: Row) => {
+    if (change(row, (cfg) => keepIn(cfg, row.name), true) === null) {
+      const cleared = Object.fromEntries(Object.entries(memory.cleared).filter(([n]) => n !== row.name));
+      remember({ cleared, pending: memory.pending.filter((n) => n !== row.name) });
+    }
+  };
+
+  const rowView = (row: Row) => {
+    const actions = <RowActions row={row} update={update} onSet={() => set(row)} onClear={() => clear(row)} onKeep={() => keep(row)} />;
+    if (row.state === "clear") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.cleared} />;
+    if (row.state === "both") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.both} />;
+    const json = row.spec.widget === "json" && !row.spec.holdsSensitive;
+    return (
+      <FieldView
+        key={row.name} spec={row.spec}
+        drawn={{
+          name: row.name, hideClear: true, actions, startFixed: json, hint: json ? WORDS.json : undefined,
+          below: row.state === "pending" && drawer.editable ? <p className="text-small text-muted">{WORDS.pending}</p> : undefined,
+        }}
+      />
+    );  // prettier-ignore
+  };
+
+  const mode = parts.mode && (
+    <FieldView
+      spec={{ ...parts.mode, label: "How they're sent" }}
+      drawn={{ control: ModeControl, hideClear: true, switchLabel: "the way they're sent", hint: replace ? null : WORDS.mergeSays, warn: replace ? WORDS.replaceSays : null }}
+    />
+  );
+  const clearControl = parts.clear && !clearDrawn && <FieldView spec={parts.clear} />;
+
+  const list = () => {
+    if (!drawer.editable) {
+      const summary = summaryOf(parts.widget, rows, body ?? {}, valueAt(config, ["mode"]), propertiesOf);
+      return (
+        <>
+          <p className="text-small">{summary.head}</p>
+          <dl className="grid grid-cols-1 gap-x-3 gap-y-1 text-small sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)]">
+            {summary.lines.map((l) => (
+              <div key={l.name} className="contents">
+                <dt className="text-muted">{l.label}</dt>
+                <dd className="m-0">{l.text}</dd>
+              </div>
+            ))}
+          </dl>
+        </>
+      );
+    }
+    // The rows hold `clear` too: a Go to or a problem there lands on them.
+    const atClear = parts.clear && clearDrawn ? problemsAt(drawer.problems, parts.clear.pointer, null) : [];
+    return (
+      <>
+        {mode}
+        <div data-pointer={parts.clear && clearDrawn ? parts.clear.pointer : undefined} className="flex min-w-0 flex-col gap-4">
+          {rows.map(rowView)}
+          {atClear.map((d, i) => (
+            <p key={`${d.code}:${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>{d.message}</p>
+          ))}
+        </div>
+        {clearControl}
+        <p className="text-small text-muted">{WORDS.count(parts.widget, changedCount(rows), offered.length)}</p>
+      </>
+    );
+  };
+
+  // A body a formula gives: its cleared settings stay listed, how they're sent with them (§5.8).
+  const computed = body === null && (
+    <div className="flex min-w-0 flex-col gap-4">
+      <p className="text-small text-muted">{update ? WORDS.formulaUpdate : WORDS.formulaCreate}</p>
+      {mode}
+      {rowsOf(offered, {}, clearDrawn ? names : [], []).map(rowView)}
+      {clearControl}
+    </div>
+  );
+
+  return (
+    <FieldView
+      spec={{ ...parts.body, label } satisfies FieldSpec}
+      drawn={{
+        group: true, startFixed: true, fixedName: "List", hideClear: true, hint: null,
+        shown: rows.map((r) => r.name), warn: nothing ? WORDS.nothing : null, parts: list, below: computed || undefined,
+      }}
+    />
+  );  // prettier-ignore
+}
diff --git a/frontend/src/routes/editor/drawer/FieldView.tsx b/frontend/src/routes/editor/drawer/FieldView.tsx
index 8dffcc3f..65a70cba 100644
--- a/frontend/src/routes/editor/drawer/FieldView.tsx
+++ b/frontend/src/routes/editor/drawer/FieldView.tsx
@@ -425,6 +425,7 @@ export function FieldView({ spec, drawn = {} }: { spec: FieldSpec; drawn?: Drawn
       <>
         {runs && <p className="text-small text-muted">{runs}</p>}
         {declassifiable}
+        {drawn.below}
       </>,
     );
   } else if (container) {
diff --git a/frontend/src/routes/editor/drawer/StepDrawer.tsx b/frontend/src/routes/editor/drawer/StepDrawer.tsx
index 8f5dea76..3a0ab52a 100644
--- a/frontend/src/routes/editor/drawer/StepDrawer.tsx
+++ b/frontend/src/routes/editor/drawer/StepDrawer.tsx
@@ -8,6 +8,7 @@
 import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import { Tabs } from "../../../components/Tabs";
+import { NO_MEMORY, type Memory } from "../../../lib/changes";
 import { optionsLine, targetOf } from "../../../lib/composer";
 import { changeParts, fieldsOf, settingsOf, type FieldSpec } from "../../../lib/schemaForm";
 import { groupOf } from "../../../lib/stepGroups";
@@ -19,6 +20,7 @@ import { DrawerContext, problemsAt, segment, type DrawerActions } from "./contex
 import { ErrorHandling, chipText } from "./ErrorHandling";
 import { FieldView } from "./FieldView";
 import { KeyField } from "./KeyField";
+import { Changes } from "./Changes";
 import { MessageComposer } from "./MessageComposer";
 
 const EFFECTS: Record<NodeType["side_effect"], string> = {
@@ -116,6 +118,8 @@ export function StepDrawer({
   const { setup, message, changes, options } = type ? settingsOf(type, fields) : { setup: [], message: null, changes: null, options: [] };
   const changing = changes ? changeParts(changes) : [];
   const onSetup = [...setup, ...(message ?? []), ...changing]; // what Setup shows: a message's parts, an update's changes
+  // What the changes remember until the drawer closes: the tabs unmount what they hide (4f-2b).
+  const [memory, setMemory] = useState<Memory>(NO_MEMORY);
   const [tab, setTab] = useState<Tab>(result ? "result" : test && testAt ? "test" : onSetup.length > 0 ? "setup" : "options");
   useEffect(() => {
     if (test && testAt) setTab("test");
@@ -264,7 +268,7 @@ export function StepDrawer({
                   <>
                     {setup.map((f) => <FieldView key={f.pointer} spec={f} />)}
                     {message && <MessageComposer parts={message} />}
-                    {changing.map((f) => <FieldView key={f.pointer} spec={f} />)}
+                    {changes && <Changes parts={changes} memory={memory} onMemory={setMemory} />}
                     {options.map((f) => <FieldView key={f.pointer} spec={f} />)}
                   </>
                 ) : (
@@ -296,7 +300,7 @@ export function StepDrawer({
                   // An update's changes or a create's settings follow its required fields, optional or not (4f-2b).
                   <>
                     {setup.map((f) => <FieldView key={f.pointer} spec={f} drawn={{ marked: true }} />)}
-                    {changing.map((f) => <FieldView key={f.pointer} spec={f} />)}
+                    <Changes parts={changes} memory={memory} onMemory={setMemory} />
                   </>
                 ) : setup.length > 0 ? (
                   <>
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 18 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/editor/drawer/Changes.tsx frontend/src/routes/editor/drawer/Changes.test.tsx frontend/src/routes/editor/drawer/StepDrawer.tsx frontend/src/routes/editor/drawer/FieldView.tsx
git commit -m "feat(editor): an update's changes and a create's settings, a row per setting, Set, Clear and Keep (4f-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Find a setting

**Spec:** §5.4; ruling 12.

**Files:**
- Create: `frontend/src/lib/settingsIndex.ts`, `frontend/src/lib/settingsIndex.test.ts`,
  `frontend/src/routes/editor/drawer/FindSetting.tsx`
- Modify: `frontend/src/routes/editor/drawer/Changes.tsx` (the box, "＋ Add a setting", adding),
  `frontend/src/routes/editor/drawer/Changes.test.tsx`

**Interfaces:**
- Consumes: `entryOf`, `itemOf`, `offeredOf`, `pointerOf`; `controlClass` (`components/Field`).
- Produces: `lib/settingsIndex.ts`: `type Step = { kind: "setting" | "entry" | "item"; name: string }`, `interface
  Setting { steps; spec; titles; raw; description }`, `MAX_SHOWN`, `settingsOf(body, kind?)`, `wordsOf(query)`,
  `findSettings(all, query): { shown; total }`, `findWords(query, shown, total)`; `FindSetting` (forwardRef to its
  input; props `settings`, `listed`, `where: "Changes" | "Settings"`, `label?`, `onAdd`).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/settingsIndex.test.ts b/frontend/src/lib/settingsIndex.test.ts
new file mode 100644
index 00000000..99704f09
--- /dev/null
+++ b/frontend/src/lib/settingsIndex.test.ts
@@ -0,0 +1,42 @@
+// SPDX-License-Identifier: Apache-2.0
+import { describe, expect, it } from "vitest";
+import { UPDATE } from "../test/nodeTypes";
+import { fieldsOf } from "./schemaForm";
+import { findSettings, findWords, settingsOf, type Setting } from "./settingsIndex";
+
+const body = fieldsOf(UPDATE).find((f) => f.name === "body")!;
+const all = settingsOf(body);
+const raws = (list: Setting[]) => list.map((s) => s.raw);
+
+describe("settingsOf", () => {
+  it("lists every setting a body offers, through its objects, a map's entries and a list's items", () => {
+    const listed = raws(all);
+    expect(listed).toEqual(expect.arrayContaining(["name", "rogue", "rogue.min_rogue_rssi", "auto_upgrade.custom.ap41", "port_usages.*.mode", "networks[].name", "radius.secret"]));
+    expect(listed).not.toContain("id"); // Mist sets it
+    expect(all.find((s) => s.raw === "port_usages.*.mode")!.titles).toEqual(["Port usages", "an entry", "Mode"]);
+    expect(all.find((s) => s.raw === "networks[].name")!.titles).toEqual(["Networks", "an item", "Name"]);
+  });
+  it("is built once per body", () => {
+    expect(settingsOf(body)).toBe(all);
+  });
+});
+
+describe("findSettings", () => {
+  it("finds by every word typed, a title or name before a description, top-level first", () => {
+    expect(raws(findSettings(all, "rogue").shown)).toEqual(["rogue", "rogue.enabled", "rogue.min_rogue_rssi", "rogue.whitelisted_ssids"]);
+    expect(raws(findSettings(all, "rogue  SSID").shown)).toEqual(["rogue.whitelisted_ssids"]);
+    expect(raws(findSettings(all, "threat").shown)).toEqual(["rogue"]); // in its description only
+    expect(raws(findSettings(all, "port_usages").shown)).toEqual(["port_usages", "port_usages.*.mode", "port_usages.*.port_vlan"]);
+  });
+  it("lists the top-level settings by title when nothing is typed", () => {
+    expect(findSettings(all, " ").shown.map((s) => s.titles[0])).toEqual(["API secret", "Auto upgrade", "Enabled", "Name", "Networks", "Port usages", "RADIUS", "Rogue", "Tags", "VLAN ID"]);
+  });
+  it("shows at most 50, and says how many it left out", () => {
+    const many = Array.from({ length: 60 }, (_, i): Setting => ({ steps: [{ kind: "setting", name: `s${i}` }], spec: body, titles: [`Item ${i}`], raw: `s${i}`, description: "" }));
+    const { shown, total } = findSettings(many, "item");
+    expect([shown.length, total]).toEqual([50, 60]);
+    expect(findWords("item", 50, 60)).toBe("50 of 60 shown: type more to narrow.");
+    expect(findWords("firewall", 0, 0)).toBe('No setting matches "firewall", by name or description.');
+    expect(findWords("", 10, 10)).toBe("10 settings; the list scrolls.");
+  });
+});
diff --git a/frontend/src/routes/editor/drawer/Changes.test.tsx b/frontend/src/routes/editor/drawer/Changes.test.tsx
index 80d90b1f..c39f1b76 100644
--- a/frontend/src/routes/editor/drawer/Changes.test.tsx
+++ b/frontend/src/routes/editor/drawer/Changes.test.tsx
@@ -128,3 +128,37 @@ it("shows a problem at `clear` with the rows that hold it", () => {
   showDrawer(UPDATE, { config: { clear: ["name"] }, problems: [problem("/clear", "Not a list of names.")] });
   expect(within(changes().querySelector<HTMLElement>('[data-pointer="/clear"]')!).getByText("Not a list of names.")).toBeTruthy();
 });
+
+// Find a setting (§5.4).
+const finder = () => within(changes()).getByRole("combobox", { name: "Find a setting" });
+
+it("finds a setting and adds it, Set with nothing given until a value is, focus on it", async () => {
+  const { config } = showDrawer(UPDATE, { config: { mode: "merge" } });
+  await userEvent.type(finder(), "name");
+  await userEvent.click(within(changes()).getByRole("option", { name: /^Name/ }));
+  const row = changes().querySelector<HTMLElement>('[data-pointer="/body/name"]')!;
+  expect(within(row).getByText(WORDS.pending)).toBeTruthy();
+  expect(config()).toEqual({ mode: "merge" }); // nothing given, nothing sent
+  await vi.waitFor(() => expect(document.activeElement).toBe(within(row).getByLabelText("Name")));
+  await userEvent.type(within(row).getByLabelText("Name"), "hq");
+  expect(config()).toEqual({ mode: "merge", body: { name: "hq" } });
+  expect(within(row).queryByText(WORDS.pending)).toBeNull();
+});
+
+it("marks a setting already listed, and says when nothing matches", async () => {
+  showDrawer(UPDATE, { config: { body: { name: "hq" } } });
+  await userEvent.type(finder(), "name");
+  expect(within(changes()).getByRole("option", { name: /^Name/ }).textContent).toContain("· In Changes");
+  await userEvent.clear(finder());
+  await userEvent.type(finder(), "firewall");
+  expect(within(changes()).getByText('No setting matches "firewall", by name or description.')).toBeTruthy();
+});
+
+it("lists the top-level settings from ＋ Add a setting, and adds the one Enter picks", async () => {
+  showDrawer(UPDATE, { config: {} });
+  await userEvent.click(within(changes()).getByRole("button", { name: "＋ Add a setting" }));
+  expect(within(changes()).getByText("10 settings; the list scrolls.")).toBeTruthy();
+  expect(within(changes()).getAllByRole("option")).toHaveLength(10);
+  await userEvent.keyboard("{ArrowDown}{Enter}"); // the second: Auto upgrade
+  expect(changes().querySelector('[data-pointer="/body/auto_upgrade"]')).not.toBeNull();
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/settingsIndex.test.ts src/routes/editor/drawer/Changes.test.tsx`
Expected: FAIL, 3 failed and 14 passed: `settingsIndex.test.ts` can't import its module (`Failed to resolve import
"./settingsIndex"`), and the changes have no search (`… role "combobox" and name "Find a setting"`, two tests) nor "＋
Add a setting".

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/settingsIndex.ts b/frontend/src/lib/settingsIndex.ts
new file mode 100644
index 00000000..c33ec862
--- /dev/null
+++ b/frontend/src/lib/settingsIndex.ts
@@ -0,0 +1,80 @@
+// SPDX-License-Identifier: Apache-2.0
+// Find a setting (4f-2, the Mist step design §5.4): every setting a body offers, top-level and nested, through its
+// objects, a map's entries and a list's items, each with its path of titles, its raw path and its description, found
+// by every word typed. Built once per body and kind: site settings has some 1,700 (R6 §9).
+import { entryOf, itemOf, offeredOf, type FieldSpec } from "./schemaForm";
+
+/** One step down from the body: a setting, a map's entry or a list's item. */
+export type Step = { kind: "setting" | "entry" | "item"; name: string };
+export interface Setting {
+  steps: Step[]; // from the body down; an entry or an item is any one
+  spec: FieldSpec; // at an example place (an entry named "*", the first item)
+  titles: string[]; // "Rogue", "Min rogue RSSI"; through a map "Port usages", "an entry", "Mode"
+  raw: string; // "rogue.min_rogue_rssi"; through a map "port_usages.*.mode", a list "networks[].name"
+  description: string;
+}
+
+export const MAX_SHOWN = 50;
+
+const cache = new WeakMap<object, Map<string, Setting[]>>();
+
+/** Every setting `body` (or a branch of it) offers, the kind's left out, top-level first in the schema's order. */
+export function settingsOf(body: FieldSpec, kind: string | null = null): Setting[] {
+  const key = `${body.pointer}|${body.label}|${kind ?? ""}`;
+  const known = cache.get(body.type)?.get(key);
+  if (known) return known;
+  const out: Setting[] = [];
+  const walk = (specs: FieldSpec[], steps: Step[], titles: string[], raw: string) => {
+    for (const spec of specs) {
+      const here = { steps: [...steps, { kind: "setting" as const, name: spec.name }], titles: [...titles, spec.label], raw: raw === "" ? spec.name : `${raw}.${spec.name}` };
+      out.push({ ...here, spec, description: typeof spec.schema.description === "string" ? spec.schema.description : "" });
+      if (spec.sensitive || spec.cut) continue; // a secret is one field; past the bound, JSON
+      if (spec.base === "group") walk(offeredOf(spec), here.steps, here.titles, here.raw);
+      else if (spec.base === "map") {
+        const entry = entryOf(spec, "*");
+        if (entry.base === "group") walk(offeredOf(entry), [...here.steps, { kind: "entry", name: "*" }], [...here.titles, "an entry"], `${here.raw}.*`);
+      } else if (spec.base === "list") {
+        const item = itemOf(spec, 0);
+        if (item.base === "group") walk(offeredOf(item), [...here.steps, { kind: "item", name: "0" }], [...here.titles, "an item"], `${here.raw}[]`);
+      }
+    }
+  };
+  walk(offeredOf(body, kind), [], [], "");
+  const byType = cache.get(body.type) ?? new Map<string, Setting[]>();
+  byType.set(key, out);
+  cache.set(body.type, byType);
+  return out;
+}
+
+const normal = (text: string) => text.trim().toLowerCase().replace(/\s+/g, " ");
+export const wordsOf = (query: string): string[] => normal(query).split(" ").filter((w) => w !== "");
+
+/** The settings every word typed is in (titles, raw path or description), a match in a title or the raw path before
+ * one only in the description, top-level before nested, then by title; at most 50 shown. Nothing typed: the
+ * top-level settings, by title. */
+export function findSettings(all: Setting[], query: string): { shown: Setting[]; total: number } {
+  const words = wordsOf(query);
+  const byTitle = (a: Setting, b: Setting) => a.titles.join(" ").localeCompare(b.titles.join(" "));
+  if (words.length === 0) {
+    const top = all.filter((s) => s.steps.length === 1).sort(byTitle);
+    return { shown: top, total: top.length };
+  }
+  const hits = all
+    .map((s) => {
+      const named = normal(`${s.titles.join(" ")} ${s.raw}`);
+      const told = normal(s.description);
+      const found = words.every((w) => named.includes(w) || told.includes(w));
+      return found ? { s, rank: words.every((w) => named.includes(w)) ? 0 : 1 } : null;
+    })
+    .filter((x): x is { s: Setting; rank: number } => x !== null)
+    .sort((a, b) => a.rank - b.rank || a.s.steps.length - b.s.steps.length || byTitle(a.s, b.s))
+    .map((x) => x.s);
+  return { shown: hits.slice(0, MAX_SHOWN), total: hits.length };
+}
+
+/** What the list says under it: how many are shown, or that none matches. */
+export function findWords(query: string, shown: number, total: number): string {
+  if (wordsOf(query).length === 0) return `${total} settings; the list scrolls.`;
+  if (total === 0) return `No setting matches "${query.trim()}", by name or description.`;
+  return total > shown ? `${shown} of ${total} shown: type more to narrow.` : total === 1 ? "1 setting matches." : `${total} settings match.`;
+}
diff --git a/frontend/src/routes/editor/drawer/Changes.tsx b/frontend/src/routes/editor/drawer/Changes.tsx
index 7a6aa685..01a3d06b 100644
--- a/frontend/src/routes/editor/drawer/Changes.tsx
+++ b/frontend/src/routes/editor/drawer/Changes.tsx
@@ -5,19 +5,35 @@
 // today's control (ledger 102). Each row's setting is the drawer's own field too, its name beside its title; Set, Clear
 // and Keep change `body` and `clear` together, one step of Undo. What it remembers until the drawer closes (a value set
 // before it was cleared, a setting added with nothing given) lives above the tabs, which unmount what they hide.
-import { type ReactNode } from "react";
+import { useRef, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import {
   WORDS, bodyObject, changedCount, clearIn, clearNames, keepIn, rowsOf, setIn, summaryOf, type Memory, type Row,
 } from "../../../lib/changes";  // prettier-ignore
 import { fixedOf, valueAt } from "../../../lib/config";
-import { isObject, offeredOf, propertiesOf, type Changes as Parts, type FieldSpec } from "../../../lib/schemaForm";
+import { isObject, offeredOf, pointerOf, propertiesOf, type Changes as Parts, type FieldSpec } from "../../../lib/schemaForm";
+import { settingsOf, type Setting } from "../../../lib/settingsIndex";
 import { problemsAt, useDrawer } from "./context";
+import { FindSetting } from "./FindSetting";
 import { FieldView } from "./FieldView";
 import type { ControlProps } from "./scalars";
 
 const NARROW = "max-sm:min-h-[44px]"; // 44 px targets at 320 (§5.11), in pixels: a rem is 14 px here
 
+/** Focus, once drawn, the control at `pointer`, else its nearest drawn holder's first: a setting just added. */
+function focusAt(pointer: string) {
+  requestAnimationFrame(() => {
+    for (let at = pointer; at !== ""; at = at.slice(0, at.lastIndexOf("/"))) {
+      const holder = [...document.querySelectorAll<HTMLElement>("[data-pointer]")].find((e) => e.dataset.pointer === at);
+      if (!holder) continue;
+      const label = holder.querySelector<HTMLLabelElement>("label[for]");
+      const control = (label && document.getElementById(label.htmlFor)) ?? holder.querySelector<HTMLElement>("input, select, textarea, button");
+      control?.focus();
+      return;
+    }
+  });
+}
+
 /** How they're sent: merge or replace, a radio pair, merge when unset (`mode`'s default); stacked at 320 px. */
 function ModeControl({ value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
   const current = value === "replace" ? "replace" : "merge";
@@ -88,6 +104,8 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
   const rows = rowsOf(offered, body ?? {}, clearDrawn ? names : [], memory.pending);
   const replace = fixedOf(valueAt(config, ["mode"])) === "replace";
   const nothing = update && body !== null && rows.every((r) => r.state === "pending");
+  const settings = settingsOf(parts.body);
+  const find = useRef<HTMLInputElement>(null);
 
   // One write of the whole config: `body` and `clear` together, one step of Undo. What's typed under the row is
   // dropped first by Clear and Keep (what it would write goes with the row), applied first by Set.
@@ -117,6 +135,13 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
     }
   };
 
+  // Added from Find: a setting not listed yet is Set, nothing given until a value is (§5.4); focus goes to it.
+  const add = (s: Setting) => {
+    const top = s.steps[0]!.name;
+    if (!rows.some((r) => r.name === top)) remember({ pending: [...memory.pending, top] });
+    focusAt(pointerOf([...parts.body.path, ...s.steps.map((step) => step.name)]));
+  };
+
   const rowView = (row: Row) => {
     const actions = <RowActions row={row} update={update} onSet={() => set(row)} onClear={() => clear(row)} onKeep={() => keep(row)} />;
     if (row.state === "clear") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.cleared} />;
@@ -163,6 +188,7 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
     return (
       <>
         {mode}
+        <FindSetting ref={find} settings={settings} listed={new Set(rows.map((r) => r.name))} where={label} onAdd={add} />
         <div data-pointer={parts.clear && clearDrawn ? parts.clear.pointer : undefined} className="flex min-w-0 flex-col gap-4">
           {rows.map(rowView)}
           {atClear.map((d, i) => (
@@ -170,6 +196,9 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
           ))}
         </div>
         {clearControl}
+        <button type="button" className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => find.current?.focus()}>
+          ＋ Add a setting
+        </button>
         <p className="text-small text-muted">{WORDS.count(parts.widget, changedCount(rows), offered.length)}</p>
       </>
     );
diff --git a/frontend/src/routes/editor/drawer/FindSetting.tsx b/frontend/src/routes/editor/drawer/FindSetting.tsx
new file mode 100644
index 00000000..db1ce75b
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/FindSetting.tsx
@@ -0,0 +1,86 @@
+// SPDX-License-Identifier: Apache-2.0
+// Find a setting (4f-2, the Mist step design §5.4): a combobox over a body's settings, top-level and nested, found by
+// every word typed in a title, the raw path or the description. Its hits a listbox under it, Up and Down to move,
+// Enter to add, Escape to close; each hit its path of titles, its raw path in the code face, its description on one
+// line, the words matched bold and underlined (never coloured); one already listed says "· In Changes".
+import { forwardRef, useId, useState, type KeyboardEvent, type ReactNode } from "react";
+import { controlClass } from "../../../components/Field";
+import { MAX_SHOWN, findSettings, findWords, wordsOf, type Setting } from "../../../lib/settingsIndex";
+
+/** `text` with each word found in it bold and underlined. */
+function marked(text: string, words: string[]): ReactNode {
+  if (words.length === 0) return text;
+  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
+  return text.split(pattern).map((part, i) =>
+    i % 2 === 1 ? <mark key={i} className="bg-transparent font-semibold text-ink underline underline-offset-2">{part}</mark> : part,
+  );
+}
+
+export const FindSetting = forwardRef<HTMLInputElement, {
+  settings: Setting[]; listed: ReadonlySet<string>; where: "Changes" | "Settings"; label?: string; onAdd: (setting: Setting) => void;
+}>(function FindSetting({ settings, listed, where, label = "Find a setting", onAdd }, input) {  // prettier-ignore
+  const id = useId();
+  const [query, setQuery] = useState("");
+  const [open, setOpen] = useState(false);
+  const [active, setActive] = useState(0);
+  const { shown, total } = open ? findSettings(settings, query) : { shown: [], total: 0 };
+  const words = wordsOf(query);
+  const pick = (s: Setting | undefined) => {
+    if (s === undefined) return;
+    setOpen(false);
+    setQuery("");
+    onAdd(s);
+  };
+  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
+    const move = { ArrowDown: active + 1, ArrowUp: active - 1 }[e.key];
+    if (move !== undefined) {
+      setOpen(true);
+      setActive(Math.max(0, Math.min(shown.length - 1, move)));
+    } else if (e.key === "Enter" && open) pick(shown[active]);
+    else if (e.key === "Escape" && open) setOpen(false);
+    else return;
+    e.preventDefault();
+    e.stopPropagation(); // Escape closes the list, not the drawer
+  };
+  return (
+    <div className="flex min-w-0 flex-col gap-2">
+      <input
+        ref={input} type="search" role="combobox" aria-label={label} aria-expanded={open} aria-controls={open && shown.length > 0 ? `${id}-hits` : undefined}
+        aria-activedescendant={open && shown.length > 0 ? `${id}-${active}` : undefined} aria-autocomplete="list"
+        placeholder="Find a setting by its name or what it does" value={query} spellCheck={false}
+        onChange={(e) => {
+          setQuery(e.target.value);
+          setActive(0);
+          setOpen(true);
+        }}
+        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={onKeyDown}
+        className={controlClass(false)}
+      />
+      {open && (
+        <>
+          {shown.length > 0 && (
+            <ul id={`${id}-hits`} role="listbox" aria-label={`${label}: settings found`} className="max-h-[320px] overflow-y-auto rounded-control border border-line p-1">
+              {shown.slice(0, MAX_SHOWN).map((s, i) => (
+                <li
+                  key={s.raw} id={`${id}-${i}`} role="option" aria-selected={i === active}
+                  onMouseDown={(e) => e.preventDefault()} onClick={() => pick(s)}
+                  className="flex cursor-pointer flex-col gap-0.5 rounded-control px-2.5 py-1.5 aria-selected:bg-accent-soft"
+                >
+                  <span className="flex flex-wrap items-baseline justify-between gap-x-3">
+                    <span className="text-body">
+                      {marked(s.titles.join(" › "), words)}
+                      {listed.has(s.steps[0]!.name) && <span className="text-small font-semibold text-accent-ink"> · In {where}</span>}
+                    </span>
+                    <span className="font-mono text-meta text-muted">{s.raw}</span>
+                  </span>
+                  {s.description && <span className="truncate text-small text-muted">{marked(s.description, words)}</span>}
+                </li>
+              ))}
+            </ul>
+          )}
+          <p role="status" className="text-small text-muted">{findWords(query, shown.length, total)}</p>
+        </>
+      )}
+    </div>
+  );  // prettier-ignore
+});
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 22 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/settingsIndex.ts frontend/src/lib/settingsIndex.test.ts frontend/src/routes/editor/drawer/FindSetting.tsx frontend/src/routes/editor/drawer/Changes.tsx frontend/src/routes/editor/drawer/Changes.test.tsx
git commit -m "feat(editor): find a setting by its name or what it does, nested ones too (4f-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Milestone 2 ends here: append `### 4f-2b, milestone 2 (<date>)` to the ledger, commit it, and pause for the owner's
review.

# Milestone 3 — Parts, kinds and Settings

### Task 8: Only the parts given: objects, a map's entries, a list's items

**Spec:** §5.3, §5.4 (nested adds), §5.5 (the parts' words); rulings 13–15.

**Files:**
- Create: `frontend/src/routes/editor/drawer/GivenParts.tsx`, `frontend/src/routes/editor/drawer/GivenParts.test.tsx`
- Modify: `frontend/src/lib/changes.ts` (`Memory`'s `open` and `adding`; `showing`),
  `frontend/src/routes/editor/drawer/Changes.tsx` (the parts' context; adding through objects, maps and lists; the
  memory merged by updater)

**Interfaces:**
- Consumes: Task 7's `FindSetting`, `settingsOf`, `Setting`; Task 5's `Memory`, `WORDS`.
- Produces: `GivenParts.tsx`: `PartsContext`, `partsOf(spec): Drawn["parts"] | undefined`, `GivenParts`,
  `opening(memory,
  spec, setting): Partial<Memory>`, `focusLater(pointer)`; `Memory` gains `open: string | null` and `adding: { pointer;
  parts } | null`; `showing(shown, pointer, names)`; `Changes`' `onMemory` becomes `(update: (memory: Memory) =>
  Memory) => void` (StepDrawer's `setMemory`).

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/routes/editor/drawer/GivenParts.test.tsx b/frontend/src/routes/editor/drawer/GivenParts.test.tsx
new file mode 100644
index 00000000..b4faad3a
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/GivenParts.test.tsx
@@ -0,0 +1,91 @@
+// SPDX-License-Identifier: Apache-2.0
+import { screen, within } from "@testing-library/react";
+import userEvent from "@testing-library/user-event";
+import { afterEach, beforeEach, expect, it, vi } from "vitest";
+import { WORDS } from "../../../lib/changes";
+import { UPDATE } from "../../../test/nodeTypes";
+import { fakeApi, json, showDrawer } from "./harness";
+
+beforeEach(() => {
+  fakeApi({ "GET /api/v1/t/t1/connections": () => json([]), "GET /api/v1/connection-types": () => json([]) });
+});
+afterEach(() => {
+  vi.restoreAllMocks();
+});
+
+const at = (pointer: string) => [...document.querySelectorAll<HTMLElement>("[data-pointer]")].find((e) => e.dataset.pointer === pointer)!;
+
+it("shows an object's parts given, and finds the others; one added is written only once given", async () => {
+  const { config } = showDrawer(UPDATE, { config: { body: { rogue: { enabled: true } } } });
+  const rogue = () => at("/body/rogue");
+  expect(within(rogue()).getByLabelText("Enabled")).toBeTruthy();
+  expect(within(rogue()).queryByLabelText("Min rogue RSSI")).toBeNull();
+  await userEvent.click(within(rogue()).getByRole("button", { name: "＋ Another setting of Rogue" }));
+  const find = within(rogue()).getByRole("combobox", { name: "Find a setting of Rogue" });
+  expect(document.activeElement).toBe(find);
+  await userEvent.type(find, "rssi");
+  await userEvent.click(within(rogue()).getByRole("option", { name: /Min rogue RSSI/ }));
+  expect(config()).toEqual({ body: { rogue: { enabled: true } } });
+  await userEvent.type(within(rogue()).getByLabelText("Min rogue RSSI"), "-80");
+  expect(config()).toEqual({ body: { rogue: { enabled: true, min_rogue_rssi: -80 } } });
+});
+
+it("takes a part off with Remove, never Clear; a setting emptied keeps its row, nothing given", async () => {
+  const { config } = showDrawer(UPDATE, { config: { body: { rogue: { enabled: true } } } });
+  expect(within(at("/body/rogue")).queryByRole("button", { name: "Clear Enabled" })).toBeNull();
+  await userEvent.click(within(at("/body/rogue")).getByRole("button", { name: "Remove Enabled" }));
+  expect(config()).toEqual({ body: {} });
+  expect(within(at("/body/rogue")).getByText(WORDS.pending)).toBeTruthy();
+});
+
+it("says how merge and replace treat the parts not given", async () => {
+  showDrawer(UPDATE, { config: { body: { rogue: { enabled: true } } } });
+  expect(within(at("/body/rogue")).getByText(WORDS.partsMerge)).toBeTruthy();
+  await userEvent.click(screen.getByRole("radio", { name: WORDS.replace }));
+  expect(within(at("/body/rogue")).getByText(WORDS.partsReplace)).toBeTruthy();
+});
+
+it("adds a nested setting from Find, each object on its way opened, focus on it", async () => {
+  const { config } = showDrawer(UPDATE, { config: {} });
+  await userEvent.type(screen.getByRole("combobox", { name: "Find a setting" }), "ap41");
+  await userEvent.click(screen.getByRole("option", { name: /AP41/ }));
+  const ap41 = within(at("/body/auto_upgrade/custom")).getByLabelText("AP41");
+  await vi.waitFor(() => expect(document.activeElement).toBe(ap41));
+  expect(config()).toEqual({});
+  await userEvent.type(ap41, "1.2");
+  expect(config()).toEqual({ body: { auto_upgrade: { custom: { ap41: "1.2" } } } });
+});
+
+it("draws a map's entries by key, a new one's key first, a setting found in one too", async () => {
+  const { config } = showDrawer(UPDATE, { config: { body: { port_usages: { trunk: { mode: "trunk" } } } } });
+  expect(within(at("/body/port_usages/trunk")).getByLabelText("Mode")).toBeTruthy();
+  await userEvent.click(screen.getByRole("button", { name: "＋ Add an entry" }));
+  await userEvent.type(screen.getByLabelText("Name of the new entry"), "trunk{Enter}");
+  expect(screen.getByText("Port usages has an entry named trunk already.")).toBeTruthy();
+  await userEvent.clear(screen.getByLabelText("Name of the new entry"));
+  await userEvent.type(screen.getByLabelText("Name of the new entry"), "uplink{Enter}");
+  const own = within(at("/body/port_usages/uplink")).getByRole("combobox", { name: "Find a setting of Port usages › uplink" });
+  await vi.waitFor(() => expect(document.activeElement).toBe(own)); // its own list, focused
+  expect(config()).toEqual({ body: { port_usages: { trunk: { mode: "trunk" } } } });
+  await userEvent.type(screen.getByRole("combobox", { name: "Find a setting" }), "port vlan");
+  await userEvent.click(screen.getByRole("option", { name: /Port usages › an entry › Port VLAN/ }));
+  await userEvent.type(screen.getByLabelText("Name of the new entry"), "access{Enter}");
+  await userEvent.type(within(at("/body/port_usages/access")).getByLabelText("Port VLAN"), "10");
+  expect(config()).toEqual({ body: { port_usages: { trunk: { mode: "trunk" }, access: { port_vlan: 10 } } } });
+});
+
+it("draws a list's items by number, an item added written empty, and says a list is sent whole", async () => {
+  const { config } = showDrawer(UPDATE, { config: { body: { networks: [{ name: "a" }] } } });
+  expect(within(at("/body/networks/0")).getByLabelText("Name")).toBeTruthy();
+  expect(within(at("/body/networks")).getByText(WORDS.wholeList)).toBeTruthy();
+  await userEvent.click(screen.getByRole("button", { name: "＋ Add an item" }));
+  expect(config()).toEqual({ body: { networks: [{ name: "a" }, {}] } });
+  await userEvent.click(screen.getByRole("button", { name: "Move down: item 1" }));
+  expect(config()).toEqual({ body: { networks: [{}, { name: "a" }] } });
+});
+
+it("keeps a secret one field, never its parts", () => {
+  showDrawer(UPDATE, { config: { body: { api_secret: "x", radius: { host: "h" } } } });
+  expect(within(at("/body/api_secret")).queryByRole("button", { name: /Another setting/ })).toBeNull();
+  expect(within(at("/body/radius")).getByLabelText("Host")).toBeTruthy(); // a part is a secret, not the whole
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/routes/editor/drawer/GivenParts.test.tsx`
Expected: FAIL, 5 failed and 2 passed: every part is drawn (`expected <input …> to be null`), no merge words under an
object (`… text: Its parts left empty stay as they are: …`), no "＋ Add an entry", no list's words. "adds a nested
setting from Find, each object on its way opened, focus on it" and "keeps a secret one field, never its parts" pass at
once: Task 7 already adds and focuses; a secret was already one field.

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/changes.ts b/frontend/src/lib/changes.ts
index 351cad45..d708ec59 100644
--- a/frontend/src/lib/changes.ts
+++ b/frontend/src/lib/changes.ts
@@ -22,8 +22,16 @@ export interface Memory {
   shown: Record<string, string[]>; // an object's parts added, nothing given yet, by the object's pointer
   entries: Record<string, string[]>; // a map's entries opened, nothing given yet, by the map's pointer
   kind: string | null; // an update's kind, chosen here
+  open: string | null; // the object whose own settings' list is open ("＋ Another setting of …")
+  adding: { pointer: string; parts: string[] } | null; // a map's new entry: its key first, then these parts
 }
-export const NO_MEMORY: Memory = { cleared: {}, pending: [], shown: {}, entries: {}, kind: null };
+export const NO_MEMORY: Memory = { cleared: {}, pending: [], shown: {}, entries: {}, kind: null, open: null, adding: null };
+
+/** `names` added to what `pointer`'s object shows, each once. */
+export const showing = (shown: Memory["shown"], pointer: string, names: string[]): Memory["shown"] => ({
+  ...shown,
+  [pointer]: [...new Set([...(shown[pointer] ?? []), ...names])],
+});
 
 type Config = Record<string, unknown>;
 
diff --git a/frontend/src/routes/editor/drawer/Changes.tsx b/frontend/src/routes/editor/drawer/Changes.tsx
index 01a3d06b..0e22c52d 100644
--- a/frontend/src/routes/editor/drawer/Changes.tsx
+++ b/frontend/src/routes/editor/drawer/Changes.tsx
@@ -8,31 +8,19 @@
 import { useRef, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import {
-  WORDS, bodyObject, changedCount, clearIn, clearNames, keepIn, rowsOf, setIn, summaryOf, type Memory, type Row,
+  WORDS, bodyObject, changedCount, clearIn, clearNames, keepIn, rowsOf, setIn, showing, summaryOf, type Memory, type Row,
 } from "../../../lib/changes";  // prettier-ignore
 import { fixedOf, valueAt } from "../../../lib/config";
 import { isObject, offeredOf, pointerOf, propertiesOf, type Changes as Parts, type FieldSpec } from "../../../lib/schemaForm";
 import { settingsOf, type Setting } from "../../../lib/settingsIndex";
 import { problemsAt, useDrawer } from "./context";
 import { FindSetting } from "./FindSetting";
+import { PartsContext, focusLater, opening, partsOf } from "./GivenParts";
 import { FieldView } from "./FieldView";
 import type { ControlProps } from "./scalars";
 
 const NARROW = "max-sm:min-h-[44px]"; // 44 px targets at 320 (§5.11), in pixels: a rem is 14 px here
 
-/** Focus, once drawn, the control at `pointer`, else its nearest drawn holder's first: a setting just added. */
-function focusAt(pointer: string) {
-  requestAnimationFrame(() => {
-    for (let at = pointer; at !== ""; at = at.slice(0, at.lastIndexOf("/"))) {
-      const holder = [...document.querySelectorAll<HTMLElement>("[data-pointer]")].find((e) => e.dataset.pointer === at);
-      if (!holder) continue;
-      const label = holder.querySelector<HTMLLabelElement>("label[for]");
-      const control = (label && document.getElementById(label.htmlFor)) ?? holder.querySelector<HTMLElement>("input, select, textarea, button");
-      control?.focus();
-      return;
-    }
-  });
-}
 
 /** How they're sent: merge or replace, a radio pair, merge when unset (`mode`'s default); stacked at 320 px. */
 function ModeControl({ value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
@@ -91,7 +79,7 @@ function SaidRow({ row, actions, said }: { row: Row; actions: ReactNode; said: s
   );
 }
 
-export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Memory; onMemory: (next: Memory) => void }) {
+export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Memory; onMemory: (update: (memory: Memory) => Memory) => void }) {
   const drawer = useDrawer();
   const config = drawer.node.config ?? {};
   const update = parts.widget === "update";
@@ -113,7 +101,8 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
     if (drop) drawer.discard(row.spec.pointer);
     return drawer.restructure(row.spec.pointer, { path: [], make: (cfg) => make(isObject(cfg) ? cfg : {}) });
   };
-  const remember = (next: Partial<Memory>) => onMemory({ ...memory, ...next });
+  // Merged into the memory as it is then: two in one handler both land.
+  const remember = (next: Partial<Memory>) => onMemory((now) => ({ ...now, ...next }));
   const set = (row: Row) => {
     if (row.state === "set") return;
     const value = row.state === "both" ? (body ?? {})[row.name] : memory.cleared[row.name];
@@ -135,11 +124,32 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
     }
   };
 
-  // Added from Find: a setting not listed yet is Set, nothing given until a value is (§5.4); focus goes to it.
+  // Added from Find (§5.4): a setting not listed yet is Set, nothing given until a value is; a nested one opens each
+  // object on its way, a map's new entry asks its key first, a list gets a new item (written: its place is the
+  // person's); focus goes to it.
   const add = (s: Setting) => {
     const top = s.steps[0]!.name;
-    if (!rows.some((r) => r.name === top)) remember({ pending: [...memory.pending, top] });
-    focusAt(pointerOf([...parts.body.path, ...s.steps.map((step) => step.name)]));
+    const next: Partial<Memory> = opening(memory, parts.body, s);
+    if (!rows.some((r) => r.name === top)) next.pending = [...memory.pending, top];
+    const at = s.steps.findIndex((step) => step.kind === "item");
+    let names: (string | number)[] = s.steps.map((step) => step.name);
+    if (at >= 0) {
+      const list = [...parts.body.path, ...names.slice(0, at)];
+      const held = valueAt(config, list);
+      const index = Array.isArray(held) ? held.length : 0;
+      if (drawer.restructure(pointerOf(list), { path: list, make: (l) => [...(Array.isArray(l) ? (l as unknown[]) : []), {}] }) !== null) return;
+      names = [...names.slice(0, at), index, ...names.slice(at + 1)];
+      const part = s.steps[at + 1]?.name;
+      if (part !== undefined) next.shown = showing(next.shown ?? memory.shown, pointerOf([...list, index]), [part]);
+    }
+    if (s.spec.base === "group" && at < 0 && next.adding == null) next.open = pointerOf([...parts.body.path, ...names]);
+    remember(next);
+    if (next.adding == null) focusLater(pointerOf([...parts.body.path, ...names]));
+  };
+  // A setting emptied by a Remove inside it keeps its row, nothing given yet.
+  const top = (pointer: string) => {
+    const name = pointer.split("/")[parts.body.path.length + 1];
+    if (name !== undefined && !memory.pending.includes(name)) remember({ pending: [...memory.pending, name] });
   };
 
   const rowView = (row: Row) => {
@@ -147,11 +157,13 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
     if (row.state === "clear") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.cleared} />;
     if (row.state === "both") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.both} />;
     const json = row.spec.widget === "json" && !row.spec.holdsSensitive;
+    const drawnParts = partsOf(row.spec);
+    const said = json ? WORDS.json : drawnParts && update && row.spec.base !== "list" ? (replace ? WORDS.partsReplace : WORDS.partsMerge) : undefined;
     return (
       <FieldView
         key={row.name} spec={row.spec}
         drawn={{
-          name: row.name, hideClear: true, actions, startFixed: json, hint: json ? WORDS.json : undefined,
+          name: row.name, hideClear: true, actions, startFixed: json, hint: said, parts: drawnParts,
           below: row.state === "pending" && drawer.editable ? <p className="text-small text-muted">{WORDS.pending}</p> : undefined,
         }}
       />
@@ -215,6 +227,7 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
   );
 
   return (
+    <PartsContext.Provider value={{ memory, remember, top, where: label }}>
     <FieldView
       spec={{ ...parts.body, label } satisfies FieldSpec}
       drawn={{
@@ -222,5 +235,6 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
         shown: rows.map((r) => r.name), warn: nothing ? WORDS.nothing : null, parts: list, below: computed || undefined,
       }}
     />
+    </PartsContext.Provider>
   );  // prettier-ignore
 }
diff --git a/frontend/src/routes/editor/drawer/GivenParts.tsx b/frontend/src/routes/editor/drawer/GivenParts.tsx
new file mode 100644
index 00000000..1240e47d
--- /dev/null
+++ b/frontend/src/routes/editor/drawer/GivenParts.tsx
@@ -0,0 +1,230 @@
+// SPDX-License-Identifier: Apache-2.0
+// A setting's parts, as an update's changes and a create's settings draw them (4f-2, the Mist step design §5.3): only
+// the parts given (and those added, nothing given yet), each the drawer's own field, taken off with Remove (never
+// Clear: only a top-level setting is cleared); "＋ Another setting of …" finds the rest. The same for each entry of a
+// map (by key; a new one's key first) and each item of a list of objects (by number). A plain list or map, a union, a
+// secret: the drawer's own control, whole. What's added and not given yet is remembered, never written.
+import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
+import { Button } from "../../../components/Button";
+import { controlClass } from "../../../components/Field";
+import { WORDS, showing, type Memory } from "../../../lib/changes";
+import { isObject, offeredOf, entryOf, itemOf, pointerOf, type FieldSpec } from "../../../lib/schemaForm";
+import { settingsOf, type Setting } from "../../../lib/settingsIndex";
+import { useDrawer } from "./context";
+import { FieldView, type Drawn } from "./FieldView";
+import { FindSetting } from "./FindSetting";
+
+const NARROW = "max-sm:min-h-[44px]";
+
+/** What the parts share: the changes' memory, and how they're sent. */
+export const PartsContext = createContext<{ memory: Memory; remember: (next: Partial<Memory>) => void; top: (pointer: string) => void; where: "Changes" | "Settings" } | null>(null);
+const useParts = () => {
+  const parts = useContext(PartsContext);
+  if (parts === null) throw new Error("GivenParts outside the changes");
+  return parts;
+};
+
+/** How a setting's value is drawn: an object, an entry or an item by its given parts, else the drawer's own control. */
+export function partsOf(spec: FieldSpec): Drawn["parts"] | undefined {
+  if (spec.sensitive || spec.cut) return undefined;
+  if (spec.base === "group") return (s, value) => <GivenParts spec={s} value={value} />;
+  if (spec.base === "map" && entryOf(spec, "*").base === "group") return (s, value) => <Entries spec={s} value={value} />;
+  if (spec.base === "list" && itemOf(spec, 0).base === "group") return (s, value) => <Items spec={s} value={value} />;
+  return undefined;
+}
+
+/** Its parts given, those added and not given yet, and the rest a search away. */
+export function GivenParts({ spec, value }: { spec: FieldSpec; value: unknown }) {
+  const drawer = useDrawer();
+  const { memory, remember, top, where } = useParts();
+  const given = isObject(value) ? value : {};
+  const shown = memory.shown[spec.pointer] ?? [];
+  const offered = offeredOf(spec);
+  const parts = offered.filter((p) => p.name in given || shown.includes(p.name));
+  const open = memory.open === spec.pointer;
+  const find = useRef<HTMLInputElement>(null);
+  useEffect(() => {
+    if (open) find.current?.focus();
+  }, [open]);
+  const remove = (part: FieldSpec) => {
+    drawer.discard(part.pointer);
+    const why = drawer.restructure(part.pointer, { path: spec.path, make: (obj) => (isObject(obj) ? Object.fromEntries(Object.entries(obj).filter(([k]) => k !== part.name)) : obj) });
+    if (why === null) {
+      top(spec.pointer); // emptied, the setting's row stays, nothing given yet
+      remember({ shown: { ...memory.shown, [spec.pointer]: shown.filter((n) => n !== part.name) } });
+    }
+  };
+  const add = (s: Setting) => {
+    const leaf = pointerOf([...spec.path, ...s.steps.map((step) => step.name)]);
+    const next = opening(memory, spec, s);
+    remember({ ...next, open: s.spec.base === "group" && next.adding == null ? leaf : null });
+    if (next.adding == null) focusLater(leaf);
+  };
+  return (
+    <div className="flex min-w-0 flex-col gap-3">
+      {parts.map((part) => (
+        <FieldView
+          key={part.name} spec={part}
+          drawn={{
+            hideClear: true, parts: partsOf(part),
+            actions: drawer.editable && !(part.required && where === "Settings") ? (
+              <Button size="sm" aria-label={`Remove ${part.label}`} className={NARROW} onMouseDown={(e) => e.preventDefault()} onClick={() => remove(part)}>Remove</Button>
+            ) : undefined,
+          }}
+        />
+      ))}
+      {drawer.editable && offered.length > parts.length && (open ? (
+        <FindSetting ref={find} settings={settingsOf(spec)} listed={new Set(parts.map((p) => p.name))} where={where} label={`Find a setting of ${spec.label}`} onAdd={add} />
+      ) : (
+        <button type="button" className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => remember({ open: spec.pointer })}>
+          ＋ Another setting of {spec.label}
+        </button>
+      ))}
+    </div>
+  );  // prettier-ignore
+}
+
+/** What remembering `s`, found under `spec`, shows: each object on its way, a map's new entry (key first), a list's
+ * new item is written by the caller. */
+export function opening(memory: Memory, spec: FieldSpec, s: Setting): Partial<Memory> {
+  let shown = memory.shown;
+  let path = spec.path;
+  for (let i = 0; i < s.steps.length; i++) {
+    const step = s.steps[i]!;
+    if (step.kind === "entry") {
+      const rest = s.steps.slice(i + 1).filter((x) => x.kind === "setting").map((x) => x.name);
+      return { shown, adding: { pointer: pointerOf(path), parts: rest.slice(0, 1) } };
+    }
+    if (step.kind === "item") return { shown };
+    if (i < s.steps.length - 1 && s.steps[i + 1]!.kind === "setting") shown = showing(shown, pointerOf([...path, step.name]), [s.steps[i + 1]!.name]);
+    path = [...path, step.name];
+  }
+  return { shown: showing(shown, pointerOf(spec.path), [s.steps[0]!.name]) };
+}
+
+/** Focus, once drawn, the control at `pointer`, else its nearest drawn holder's first. */
+export function focusLater(pointer: string) {
+  requestAnimationFrame(() => {
+    for (let at = pointer; at !== ""; at = at.slice(0, at.lastIndexOf("/"))) {
+      const holder = [...document.querySelectorAll<HTMLElement>("[data-pointer]")].find((e) => e.dataset.pointer === at);
+      if (!holder) continue;
+      const label = holder.querySelector<HTMLLabelElement>("label[for]");
+      const control = (label && document.getElementById(label.htmlFor)) ?? holder.querySelector<HTMLElement>("input, select, textarea, button");
+      control?.focus();
+      return;
+    }
+  });
+}
+
+/** A map's entries by key, each by its given parts; a new one's key first. */
+function Entries({ spec, value }: { spec: FieldSpec; value: unknown }) {
+  const drawer = useDrawer();
+  const { memory, remember, top } = useParts();
+  const given = isObject(value) ? Object.keys(value) : [];
+  const opened = memory.entries[spec.pointer] ?? [];
+  const keys = [...given, ...opened.filter((k) => !given.includes(k))];
+  const adding = memory.adding?.pointer === spec.pointer;
+  const [key, setKey] = useState("");
+  const [why, setWhy] = useState<string | null>(null);
+  const remove = (name: string) => {
+    const pointer = pointerOf([...spec.path, name]);
+    drawer.discard(pointer);
+    const done = drawer.restructure(pointer, { path: spec.path, make: (map) => (isObject(map) ? Object.fromEntries(Object.entries(map).filter(([k]) => k !== name)) : map) });
+    if (done === null) {
+      top(spec.pointer);
+      remember({ entries: { ...memory.entries, [spec.pointer]: opened.filter((k) => k !== name) } });
+    }
+  };
+  const open = () => {
+    const name = key.trim();
+    if (name === "") return setWhy("Give the entry a name.");
+    if (keys.includes(name)) return setWhy(`${spec.label} has an entry named ${name} already.`);
+    const entry = pointerOf([...spec.path, name]);
+    const parts = memory.adding?.parts ?? [];
+    remember({
+      adding: null, entries: { ...memory.entries, [spec.pointer]: [...opened, name] },
+      shown: parts.length > 0 ? showing(memory.shown, entry, parts) : memory.shown, open: parts.length > 0 ? null : entry,
+    });  // prettier-ignore
+    setKey("");
+    setWhy(null);
+    if (parts.length > 0) focusLater(`${entry}/${parts[0]}`); // else its own list opens, focused (GivenParts)
+  };
+  return (
+    <div className="flex min-w-0 flex-col gap-3">
+      {keys.map((name) => {
+        const entry = { ...entryOf(spec, name), label: `${spec.label} › ${name}` };
+        return (
+          <FieldView
+            key={name} spec={entry}
+            drawn={{
+              hideClear: true, parts: (s, v) => <GivenParts spec={s} value={v} />,
+              actions: drawer.editable ? <Button size="sm" aria-label={`Remove ${entry.label}`} className={NARROW} onClick={() => remove(name)}>Remove</Button> : undefined,
+            }}
+          />
+        );  // prettier-ignore
+      })}
+      {drawer.editable && (adding ? (
+        <div className="flex min-w-0 flex-col gap-1.5">
+          <label htmlFor={`${spec.pointer}-key`} className="text-small font-semibold">Name of the new entry</label>
+          <input
+            id={`${spec.pointer}-key`} autoFocus value={key} spellCheck={false} aria-invalid={why !== null} className={controlClass(why !== null)}
+            onChange={(e) => setKey(e.target.value)}
+            onKeyDown={(e) => {
+              if (e.key === "Enter") {
+                e.preventDefault();
+                open();
+              } else if (e.key === "Escape") {
+                e.stopPropagation();
+                remember({ adding: null });
+              }
+            }}
+          />
+          {why && <p className="text-small text-danger">{why}</p>}
+        </div>
+      ) : (
+        <button type="button" className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => remember({ adding: { pointer: spec.pointer, parts: [] } })}>
+          ＋ Add an entry
+        </button>
+      ))}
+    </div>
+  );  // prettier-ignore
+}
+
+/** A list's items by number, each by its given parts; an item added is written, empty: its place is the person's. */
+function Items({ spec, value }: { spec: FieldSpec; value: unknown }) {
+  const drawer = useDrawer();
+  const items = Array.isArray(value) ? (value as unknown[]) : [];
+  const reshape = (make: (list: unknown[]) => unknown[]) =>
+    drawer.restructure(spec.pointer, { path: spec.path, make: (list) => make(Array.isArray(list) ? [...(list as unknown[])] : []) });
+  const button = (label: string, onClick: () => void, disabled = false): ReactNode => (
+    <Button size="sm" aria-label={label} className={NARROW} disabled={disabled} onClick={onClick}>{label.split(":")[0]}</Button>
+  );
+  return (
+    <div className="flex min-w-0 flex-col gap-3">
+      {items.map((_, i) => {
+        const item = { ...itemOf(spec, i), label: `${spec.label} › item ${i + 1}` };
+        return (
+          <FieldView
+            key={i} spec={item}
+            drawn={{
+              hideClear: true, parts: (s, v) => <GivenParts spec={s} value={v} />,
+              actions: drawer.editable ? (
+                <>
+                  {button(`Move up: item ${i + 1}`, () => reshape((l) => [...l.slice(0, i - 1), l[i], l[i - 1], ...l.slice(i + 1)]), i === 0)}
+                  {button(`Move down: item ${i + 1}`, () => reshape((l) => [...l.slice(0, i), l[i + 1], l[i], ...l.slice(i + 2)]), i === items.length - 1)}
+                  {button(`Remove: item ${i + 1}`, () => reshape((l) => l.filter((__, j) => j !== i)))}
+                </>
+              ) : undefined,
+            }}
+          />
+        );  // prettier-ignore
+      })}
+      {drawer.editable && (
+        <button type="button" className={`self-start text-small font-semibold text-accent-ink ${NARROW}`} onClick={() => reshape((l) => [...l, {}])}>
+          ＋ Add an item
+        </button>
+      )}
+      <p className="text-small text-muted">{WORDS.wholeList}</p>
+    </div>
+  );  // prettier-ignore
+}
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 7 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/editor/drawer/GivenParts.tsx frontend/src/routes/editor/drawer/GivenParts.test.tsx frontend/src/lib/changes.ts frontend/src/routes/editor/drawer/Changes.tsx
git commit -m "feat(editor): a setting's parts given only, a map's entries by key, a list's items by number (4f-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: A create's required settings first; a device's kind

**Spec:** §5.6, §5.7; rulings 17, 18.

**Files:**
- Modify: `frontend/src/lib/changes.ts` (`rowsOf`'s `first`), `frontend/src/routes/editor/drawer/Changes.tsx` (the kind)
- Test: `frontend/src/lib/changes.test.ts`, `frontend/src/routes/editor/drawer/Changes.test.tsx`

**Interfaces:**
- Consumes: Task 2's `branchesOf`, `kindOf`, `unionTitle`, `offeredOf`; Task 5's `kindIndex`, `kindIn`, `WORDS`;
  `DEVICE_UPDATE`, `DEVICE_CREATE`, `CREATE`.
- Produces: `rowsOf(specs, body, clear, pending, first: string[] = [])`.

- [ ] **Step 1: Write the failing tests**

Apply:

```diff
diff --git a/frontend/src/lib/changes.test.ts b/frontend/src/lib/changes.test.ts
index 7cb69033..36a59f83 100644
--- a/frontend/src/lib/changes.test.ts
+++ b/frontend/src/lib/changes.test.ts
@@ -16,6 +16,10 @@ describe("rows", () => {
     expect(rows.map((r) => [r.spec.label, r.state])).toEqual([["Name", "set"], ["Rogue", "set"], ["Tags", "clear"], ["VLAN ID", "pending"]]);
     expect(changedCount(rows)).toBe(3);
   });
+  it("puts a create's required settings first, given or not, in their order", () => {
+    const rows = rowsOf(offered, { enabled: true, tags: [] }, [], [], ["vlan_id", "name"]);
+    expect(rows.map((r) => [r.name, r.state])).toEqual([["vlan_id", "pending"], ["name", "pending"], ["enabled", "set"], ["tags", "set"]]);
+  });
   it("says a setting both set and cleared, and leaves out what the schema doesn't describe or Mist sets", () => {
     const rows = rowsOf(offered, { name: "hq", id: "x", nope: 1 }, ["name"], []);
     expect(rows.map((r) => [r.name, r.state])).toEqual([["name", "both"]]);
diff --git a/frontend/src/routes/editor/drawer/Changes.test.tsx b/frontend/src/routes/editor/drawer/Changes.test.tsx
index c39f1b76..1d3fdd54 100644
--- a/frontend/src/routes/editor/drawer/Changes.test.tsx
+++ b/frontend/src/routes/editor/drawer/Changes.test.tsx
@@ -4,7 +4,7 @@ import userEvent from "@testing-library/user-event";
 import { afterEach, beforeEach, expect, it, vi } from "vitest";
 import { WORDS } from "../../../lib/changes";
 import { formula } from "../../../lib/config";
-import { CREATE, UPDATE } from "../../../test/nodeTypes";
+import { CREATE, DEVICE_CREATE, DEVICE_UPDATE, UPDATE } from "../../../test/nodeTypes";
 import { fakeApi, json, problem, showDrawer } from "./harness";
 
 beforeEach(() => {
@@ -162,3 +162,43 @@ it("lists the top-level settings from ＋ Add a setting, and adds the one Enter
   await userEvent.keyboard("{ArrowDown}{Enter}"); // the second: Auto upgrade
   expect(changes().querySelector('[data-pointer="/body/auto_upgrade"]')).not.toBeNull();
 });
+
+// A device's kind (§5.7), a create's required settings (§5.6).
+const kindOfDevice = () => screen.getByRole("radiogroup", { name: "Kind of device" });
+
+it("reads an update's kind from its settings, offers that kind's, and says what a change of kind keeps and drops", async () => {
+  const { config } = showDrawer(DEVICE_UPDATE, { config: { body: { name: "cam", zoom: 2 }, clear: ["notes"] } });
+  expect(within(kindOfDevice()).getByRole("radio", { name: "Camera" })).toHaveProperty("checked", true);
+  expect(screen.getByText("Its settings are the Camera's.")).toBeTruthy();
+  expect(rows(changes())).toEqual(["/body/name", "/body/notes", "/body/zoom"]);
+  await userEvent.click(within(kindOfDevice()).getByRole("radio", { name: "Sensor" }));
+  expect(screen.getByRole("status", { name: "" }).textContent).toBe("Kind changed to Sensor: Name and Notes are kept; Zoom is dropped, as a Sensor doesn't have it.");
+  expect(config()).toEqual({ body: { name: "cam" }, clear: ["notes"] }); // its kind isn't sent: Mist knows it
+  expect(within(kindOfDevice()).getByRole("radio", { name: "Sensor" })).toHaveProperty("checked", true);
+  await userEvent.type(within(changes()).getByRole("combobox", { name: "Find a setting" }), "zoom");
+  expect(within(changes()).getByText('No setting matches "zoom", by name or description.')).toBeTruthy();
+});
+
+it("reads an update's kind from its value when the draft holds it, and writes the new one", async () => {
+  const { config } = showDrawer(DEVICE_UPDATE, { config: { body: { type: "sensor", range: 3 } } });
+  expect(within(kindOfDevice()).getByRole("radio", { name: "Sensor" })).toHaveProperty("checked", true);
+  await userEvent.click(within(kindOfDevice()).getByRole("radio", { name: "Camera" }));
+  expect(config()).toEqual({ body: { type: "camera" } });
+});
+
+it("asks a create for its kind first, then writes it, its required settings first", async () => {
+  const { config } = showDrawer(DEVICE_CREATE, { config: {} });
+  expect(screen.getByText(WORDS.chooseKind)).toBeTruthy();
+  expect(screen.queryByRole("combobox", { name: "Find a setting" })).toBeNull();
+  await userEvent.click(within(kindOfDevice()).getByRole("radio", { name: "Sensor" }));
+  expect(config()).toEqual({ body: { type: "sensor" } });
+  const group = screen.getByRole("group", { name: "Settings" });
+  expect(rows(group)).toEqual(["/body/name"]);
+  expect(within(group).queryByRole("button", { name: "Remove Name" })).toBeNull();
+  expect(within(group).queryByText(WORDS.pending)).toBeNull(); // required: not "isn't sent"
+});
+
+it("lists a create's required settings first, given or not", () => {
+  showDrawer(CREATE, { config: { body: { enabled: true } } });
+  expect(rows(screen.getByRole("group", { name: "Settings" }))).toEqual(["/body/name", "/body/enabled"]);
+});
```

- [ ] **Step 2: Run them**

Run: `npx --offline pnpm@12.6.0 exec vitest run src/lib/changes.test.ts src/routes/editor/drawer/Changes.test.tsx`
Expected: FAIL, 5 failed and 28 passed: no "Kind of device" (`… role "radiogroup" and name "Kind of device"`, two
tests), no "Choose the kind first: …", a create's required settings not first (`expected [ '/body/enabled' ] to deeply
equal [ '/body/name', '/body/enabled' ]`; `rowsOf` takes no `first`).

- [ ] **Step 3: Implement**

Apply:

```diff
diff --git a/frontend/src/lib/changes.ts b/frontend/src/lib/changes.ts
index d708ec59..3c09afcc 100644
--- a/frontend/src/lib/changes.ts
+++ b/frontend/src/lib/changes.ts
@@ -49,9 +49,11 @@ export function clearNames(config: Config): string[] | null {
   return Array.isArray(clear) && clear.every((n): n is string => typeof n === "string") ? clear : null;
 }
 
-/** A row per setting given, cleared or added, of the ones the schema describes; by title. */
-export function rowsOf(specs: FieldSpec[], body: Record<string, unknown>, clear: string[], pending: string[]): Row[] {
-  const names = new Set([...Object.keys(body), ...clear, ...pending]);
+/** A row per setting given, cleared or added, of the ones the schema describes; `first` (a create's required
+ * settings, given or not) in their order, then the others by title. */
+export function rowsOf(specs: FieldSpec[], body: Record<string, unknown>, clear: string[], pending: string[], first: string[] = []): Row[] {
+  const names = new Set([...Object.keys(body), ...clear, ...pending, ...first]);
+  const rank = (name: string) => (first.includes(name) ? first.indexOf(name) : first.length);
   return specs
     .filter((s) => names.has(s.name))
     .map((spec): Row => {
@@ -59,7 +61,7 @@ export function rowsOf(specs: FieldSpec[], body: Record<string, unknown>, clear:
       const cleared = clear.includes(spec.name);
       return { name: spec.name, spec, state: set && cleared ? "both" : set ? "set" : cleared ? "clear" : "pending" };
     })
-    .sort((a, b) => a.spec.label.localeCompare(b.spec.label) || a.name.localeCompare(b.name));
+    .sort((a, b) => rank(a.name) - rank(b.name) || a.spec.label.localeCompare(b.spec.label) || a.name.localeCompare(b.name));
 }
 
 const withClear = (config: Config, names: string[]): Config => {
diff --git a/frontend/src/routes/editor/drawer/Changes.tsx b/frontend/src/routes/editor/drawer/Changes.tsx
index 0e22c52d..1a31cb49 100644
--- a/frontend/src/routes/editor/drawer/Changes.tsx
+++ b/frontend/src/routes/editor/drawer/Changes.tsx
@@ -5,13 +5,15 @@
 // today's control (ledger 102). Each row's setting is the drawer's own field too, its name beside its title; Set, Clear
 // and Keep change `body` and `clear` together, one step of Undo. What it remembers until the drawer closes (a value set
 // before it was cleared, a setting added with nothing given) lives above the tabs, which unmount what they hide.
-import { useRef, type ReactNode } from "react";
+import { useId, useRef, useState, type ReactNode } from "react";
 import { Button } from "../../../components/Button";
 import {
-  WORDS, bodyObject, changedCount, clearIn, clearNames, keepIn, rowsOf, setIn, showing, summaryOf, type Memory, type Row,
+  WORDS, bodyObject, changedCount, clearIn, clearNames, keepIn, kindIn, kindIndex, rowsOf, setIn, showing, summaryOf, type Memory, type Row,
 } from "../../../lib/changes";  // prettier-ignore
 import { fixedOf, valueAt } from "../../../lib/config";
-import { isObject, offeredOf, pointerOf, propertiesOf, type Changes as Parts, type FieldSpec } from "../../../lib/schemaForm";
+import {
+  branchesOf, isObject, kindOf, offeredOf, pointerOf, propertiesOf, unionTitle, type Changes as Parts, type FieldSpec,
+} from "../../../lib/schemaForm";  // prettier-ignore
 import { settingsOf, type Setting } from "../../../lib/settingsIndex";
 import { problemsAt, useDrawer } from "./context";
 import { FindSetting } from "./FindSetting";
@@ -86,13 +88,25 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
   const label = update ? "Changes" : "Settings";
   const body = bodyObject(config);
   const names = clearNames(config);
-  const offered = offeredOf(parts.body);
+  // A union of kinds (a device's): its kind first, the settings offered the chosen kind's (§5.7); an update's read
+  // from its value, the one chosen here, or the settings listed; a create's only from its value, written when picked.
+  const branches = branchesOf(parts.body);
+  const kind = kindOf(branches);
+  const kindNames = kind ? branches.map((b) => offeredOf(b, kind.name).map((p) => p.name)) : [];
+  const listed = [...Object.keys(body ?? {}), ...(names ?? [])].filter((n) => n !== kind?.name);
+  const index = kind ? kindIndex(parts.widget, body ?? {}, listed, kind, kindNames, memory.kind) : null;
+  const scope = kind ? (index === null ? null : branches[index]!) : parts.body;
+  const offered = scope ? offeredOf(scope, kind?.name ?? null) : [];
+  const required = update || scope === null || !Array.isArray(scope.schema.required) ? [] :
+    (scope.schema.required as unknown[]).filter((n): n is string => typeof n === "string" && offered.some((o) => o.name === n));  // prettier-ignore
+  const kindId = useId();
+  const [said, setSaid] = useState<string | null>(null);
   // A `clear` naming what the list doesn't offer is a draft from elsewhere: today's control, unchanged (§5.8).
   const clearDrawn = parts.clear !== null && names !== null && names.every((n) => offered.some((s) => s.name === n));
-  const rows = rowsOf(offered, body ?? {}, clearDrawn ? names : [], memory.pending);
+  const rows = rowsOf(offered, body ?? {}, clearDrawn ? names : [], memory.pending, required);
   const replace = fixedOf(valueAt(config, ["mode"])) === "replace";
   const nothing = update && body !== null && rows.every((r) => r.state === "pending");
-  const settings = settingsOf(parts.body);
+  const settings = scope ? settingsOf(scope, kind?.name ?? null) : [];
   const find = useRef<HTMLInputElement>(null);
 
   // One write of the whole config: `body` and `clear` together, one step of Undo. What's typed under the row is
@@ -146,6 +160,36 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
     remember(next);
     if (next.adding == null) focusLater(pointerOf([...parts.body.path, ...names]));
   };
+  // Another kind: the changes it has too are kept, the others dropped, said; its value written where it's held.
+  const toKind = (to: number) => {
+    if (!kind || to === index) return;
+    const target = branches[to]!;
+    const names = kindNames[to]!;
+    const out: { done?: ReturnType<typeof kindIn> } = {};
+    const write = !update || (body ?? {})[kind.name] !== undefined;
+    const why = drawer.restructure(parts.body.pointer, { path: [], make: (cfg) => (out.done = kindIn(isObject(cfg) ? cfg : {}, kind, to, names, write)).config });
+    if (why !== null || out.done === undefined) return;
+    const { kept, dropped } = out.done;
+    const titled = (n: string) => branches.flatMap((b) => propertiesOf(b)).find((p) => p.name === n)?.label ?? n;
+    remember({ kind: kind.values[to]!, pending: memory.pending.filter((n) => names.includes(n)) });
+    setSaid(kept.length + dropped.length > 0 ? WORDS.kindChanged(target.label, kept.map(titled), dropped.map(titled)) : null);
+  };
+  const kindControl = kind && (
+    <div className="flex min-w-0 flex-col gap-1.5">
+      <span id={kindId} className="text-small font-semibold">Kind of {(unionTitle(parts.body) ?? "it").replace(/^./, (c) => c.toLowerCase())}</span>
+      <div role="radiogroup" aria-labelledby={kindId} className="grid grid-cols-1 gap-2 sm:flex sm:flex-wrap">
+        {branches.map((b, i) => (
+          <label key={b.label} className={`flex min-h-[24px] items-center gap-2 rounded-lg border border-line-control px-3 text-body ${NARROW}`}>
+            <input type="radio" name={kindId} checked={index === i} disabled={!drawer.editable} onChange={() => toKind(i)} />
+            {b.label}
+          </label>
+        ))}
+      </div>
+      <p className="text-small text-muted">{index === null ? WORDS.chooseKind : `Its settings are the ${branches[index]!.label}'s.`}</p>
+      {said && <p role="status" className="text-small">{said}</p>}
+    </div>
+  );  // prettier-ignore
+
   // A setting emptied by a Remove inside it keeps its row, nothing given yet.
   const top = (pointer: string) => {
     const name = pointer.split("/")[parts.body.path.length + 1];
@@ -158,13 +202,14 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
     if (row.state === "both") return <SaidRow key={row.name} row={row} actions={actions} said={WORDS.both} />;
     const json = row.spec.widget === "json" && !row.spec.holdsSensitive;
     const drawnParts = partsOf(row.spec);
+    const pendingSaid = row.state === "pending" && drawer.editable && !required.includes(row.name);
     const said = json ? WORDS.json : drawnParts && update && row.spec.base !== "list" ? (replace ? WORDS.partsReplace : WORDS.partsMerge) : undefined;
     return (
       <FieldView
         key={row.name} spec={row.spec}
         drawn={{
           name: row.name, hideClear: true, actions, startFixed: json, hint: said, parts: drawnParts,
-          below: row.state === "pending" && drawer.editable ? <p className="text-small text-muted">{WORDS.pending}</p> : undefined,
+          below: pendingSaid ? <p className="text-small text-muted">{WORDS.pending}</p> : undefined,
         }}
       />
     );  // prettier-ignore
@@ -197,8 +242,10 @@ export function Changes({ parts, memory, onMemory }: { parts: Parts; memory: Mem
     }
     // The rows hold `clear` too: a Go to or a problem there lands on them.
     const atClear = parts.clear && clearDrawn ? problemsAt(drawer.problems, parts.clear.pointer, null) : [];
+    if (scope === null) return kindControl; // a create's kind not chosen yet: nothing else to give
     return (
       <>
+        {kindControl}
         {mode}
         <FindSetting ref={find} settings={settings} listed={new Set(rows.map((r) => r.name))} where={label} onAdd={add} />
         <div data-pointer={parts.clear && clearDrawn ? parts.clear.pointer : undefined} className="flex min-w-0 flex-col gap-4">
```

- [ ] **Step 4: Run them again, and the static checks**

Run: the same tests. Expected: PASS, 33 passed. Then the frontend's static checks: no output.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/changes.ts frontend/src/lib/changes.test.ts frontend/src/routes/editor/drawer/Changes.tsx frontend/src/routes/editor/drawer/Changes.test.tsx
git commit -m "feat(editor): a create's required settings first; a device's kind, then its settings (4f-2b)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Milestone 3 ends here: append `### 4f-2b, milestone 3 (<date>)` to the ledger, commit it, and pause for the owner's
review.

# Milestone 4 — Close

### Task 10: In the browser

**Spec:** §6 (the e2e: no Mist call; real Mist steps without a connection); §5.11.

**Files:**
- Create: `frontend/e2e/changes.spec.ts`, `frontend/e2e/fixtures/changes.dewpoint.json`
- Modify: `frontend/playwright.config.ts` (the workflows project runs `changes.spec.ts`)

**Interfaces:**
- Consumes: `test`, `expect`, `expectAccessible` (`e2e/gate.ts`); the server's own `mist.site_settings.update@1`,
  `mist.org_wlans.create@1`, `mist.site_devices.update@1`, with 4f-2a's metadata.
- Produces: nothing later tasks use.

"Changes" holds three Mist steps without a connection: `update_settings` (merge, Rogue enabled), `create_wlan` (empty)
and `rename_ap` (a name and a height). The specs, at 1280 px: the changes, merge checked, "1 of 93 settings change", a
part of Rogue found among its own and given, Remote syslog found and cleared, replace's words, the draft saved; the
WLAN's settings with SSID first, VLAN ID as JSON; the device's kind read as AP, changed to Switch with its words; at
320 px: merge and replace stacked, Set, Keep and "＋ Add a setting" 44 px. Both light and dark with axe. Nothing is
published and Mist is never called.

- [ ] **Step 1: Write the specs**

Apply:

```diff
diff --git a/frontend/e2e/changes.spec.ts b/frontend/e2e/changes.spec.ts
new file mode 100644
index 00000000..697e5bc4
--- /dev/null
+++ b/frontend/e2e/changes.spec.ts
@@ -0,0 +1,97 @@
+// SPDX-License-Identifier: Apache-2.0
+// Editor 4f-2b in the browser: a Mist update's changes, a create's settings and a device's kind, in a step's drawer,
+// behind nginx, under the served CSP, with axe, light and dark, at 1280 and 320 px. Nothing is published and Mist is
+// never called (D24): the steps have no connection.
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
+/** The changes fixture imported as a new workflow and opened on its canvas. */
+async function openChanges(page: Page, name: string) {
+  await page.goto(`/t/${await tenantId(page)}/workflows`);
+  await page.getByTestId("workflow-new").click();
+  const dialog = page.getByRole("dialog", { name: "New workflow" });
+  await dialog.getByLabel("Name").fill(name);
+  await dialog.getByRole("radio", { name: /Import from file/ }).check();
+  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/changes.dewpoint.json");
+  await dialog.getByRole("button", { name: "Import and open" }).click();
+  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}\?triggers=true$/);
+  await page.goto(new URL(page.url()).pathname);
+}
+
+async function drawerOf(page: Page, key: string) {
+  await page.getByRole("button", { name: new RegExp(`^${key}, `) }).click();
+  return page.getByRole("complementary", { name: key });
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
+test("an update's changes: found, set, cleared, sent by merge or replace", async ({ page }) => {
+  await openChanges(page, "Changes");
+  const drawer = await drawerOf(page, "update_settings");
+  const changes = drawer.getByRole("group", { name: "Changes" });
+  await expect(changes.getByRole("radio", { name: "Merge with the current settings" })).toBeChecked();
+  await expect(changes.getByText("1 of 93 settings change; the others stay as they are.")).toBeVisible();
+  // A part of Rogue, found among its own.
+  await changes.getByRole("button", { name: "＋ Another setting of Rogue" }).click();
+  await changes.getByRole("combobox", { name: "Find a setting of Rogue" }).fill("rssi");
+  await changes.getByRole("option", { name: /Min rogue RSSI/ }).click();
+  await changes.getByLabel("Min rogue RSSI").fill("-80");
+  // Remote syslog, found by its name, then cleared.
+  await changes.getByRole("combobox", { name: "Find a setting" }).fill("remote syslog");
+  await changes.getByRole("option", { name: /^Remote syslog/ }).first().click(); // the setting itself: top-level first
+  await changes.getByRole("group", { name: "What happens to Remote syslog" }).getByRole("button", { name: "Clear" }).click();
+  await expect(changes.getByText("Sent empty: Mist removes this setting.")).toBeVisible();
+  await expect(changes.getByText("2 of 93 settings change; the others stay as they are.")).toBeVisible();
+  await changes.getByRole("radio", { name: "Replace them" }).click();
+  await expect(changes.getByText(/^Replace sends each setting below as written/)).toBeVisible();
+  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
+  await accessibleBothWays(page, "drawer: an update's changes");
+});
+
+test("a create's settings, a union setting as JSON, a device's kind", async ({ page }) => {
+  await openChanges(page, "Settings");
+  const create = await drawerOf(page, "create_wlan");
+  const settings = create.getByRole("group", { name: "Settings" });
+  await expect(settings.getByLabel("SSID")).toBeVisible(); // required: first, given or not
+  await expect(settings.getByRole("button", { name: "Remove SSID" })).toHaveCount(0);
+  await settings.getByRole("combobox", { name: "Find a setting" }).fill("vlan id");
+  await settings.getByRole("option", { name: /^VLAN ID/ }).first().click();
+  await expect(settings.getByText(/As JSON: Mist takes it in more than one shape\./)).toBeVisible();
+  await accessibleBothWays(page, "drawer: a create's settings");
+  const device = await drawerOf(page, "rename_ap");
+  const kind = device.getByRole("radiogroup", { name: "Kind of device" });
+  await expect(kind.getByRole("radio", { name: "AP" })).toBeChecked(); // its height: only an AP has one
+  await kind.getByRole("radio", { name: "Switch" }).click();
+  await expect(device.getByText("Kind changed to Switch: Name is kept; Height is dropped, as a Switch doesn't have it.")).toBeVisible();
+  await accessibleBothWays(page, "drawer: a device's kind");
+});
+
+test("at 320 px the changes stack, their targets 44 px, and stay AA", async ({ page }) => {
+  await page.setViewportSize({ width: 320, height: 720 });
+  await openChanges(page, "Changes narrow");
+  const drawer = await drawerOf(page, "update_settings");
+  const changes = drawer.getByRole("group", { name: "Changes" });
+  const [merge, replace] = [
+    (await changes.getByText("Merge with the current settings", { exact: true }).boundingBox())!,
+    (await changes.getByText("Replace them", { exact: true }).boundingBox())!,
+  ];
+  expect(replace.y).toBeGreaterThan(merge.y); // stacked
+  const rogue = changes.getByRole("group", { name: "What happens to Rogue" });
+  for (const target of [rogue.getByRole("button", { name: "Set" }), changes.getByRole("button", { name: "Keep Rogue as it is" }), changes.getByRole("button", { name: "＋ Add a setting" })]) {
+    expect((await target.boundingBox())!.height).toBeGreaterThanOrEqual(44);
+  }
+  await accessibleBothWays(page, "drawer: changes at 320 px");
+});
diff --git a/frontend/e2e/fixtures/changes.dewpoint.json b/frontend/e2e/fixtures/changes.dewpoint.json
new file mode 100644
index 00000000..17d746e5
--- /dev/null
+++ b/frontend/e2e/fixtures/changes.dewpoint.json
@@ -0,0 +1,34 @@
+{
+  "format": "dewpoint.workflow",
+  "format_version": 1,
+  "name": "Changes",
+  "graph": {
+    "graph_format": 1,
+    "nodes": [
+      {
+        "id": "4f2b0001-0000-4000-8000-000000000001",
+        "key": "update_settings",
+        "type": "mist.site_settings.update@1",
+        "config": { "mode": "merge", "body": { "rogue": { "enabled": true } } },
+        "position": { "x": 0, "y": 140 }
+      },
+      {
+        "id": "4f2b0001-0000-4000-8000-000000000002",
+        "key": "create_wlan",
+        "type": "mist.org_wlans.create@1",
+        "config": {},
+        "position": { "x": 0, "y": 280 }
+      },
+      {
+        "id": "4f2b0001-0000-4000-8000-000000000003",
+        "key": "rename_ap",
+        "type": "mist.site_devices.update@1",
+        "config": { "mode": "merge", "body": { "name": "ap-1", "height": 3 } },
+        "position": { "x": 0, "y": 420 }
+      }
+    ],
+    "edges": [],
+    "settings": { "input_schema": { "type": "object", "properties": {}, "additionalProperties": false } }
+  },
+  "bindings": []
+}
diff --git a/frontend/playwright.config.ts b/frontend/playwright.config.ts
index d5da68fe..3e56035a 100644
--- a/frontend/playwright.config.ts
+++ b/frontend/playwright.config.ts
@@ -7,7 +7,7 @@ export default defineConfig({
     { name: "foundations", testMatch: /(foundations|gate)\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
     {
       name: "workflows",
-      testMatch: /(workflows|triggers|simulation|runs|runForm|composer|mist)\.spec\.ts/,
+      testMatch: /(workflows|triggers|simulation|runs|runForm|composer|mist|changes)\.spec\.ts/,
       dependencies: ["foundations"],
       use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
     },
```

- [ ] **Step 2: Type check and lint them**

Run: the frontend's static checks. Expected: no output (the type check covers `e2e/`, and ESLint lints it).

- [ ] **Step 3: Run them in the browser**

They need the Compose stack, as CI's e2e job brings it up (`deploy/compose`, the development override, a generated
`.env` that's never printed, `dewpoint admin init`). Locally, building it takes long: ask the owner first. Then, from
`$WT/frontend`: `npx --offline pnpm@12.6.0 exec playwright test`. Expected: every spec passes, the three of
`changes.spec.ts` among them. A failure is read and fixed test-first. If the owner prefers, the specs run in CI's e2e
job on the PR instead, and the summary says they weren't run locally.

- [ ] **Step 4: Commit**

```bash
git add frontend/e2e frontend/playwright.config.ts
git commit -m "test(e2e): an update's changes, a create's settings and a device's kind in the browser (4f-2b)

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

Then local CodeQL on the head: CI's python and javascript-typescript analyses on a `git archive` of it.

Expected, as on the plan's own check (at the top): the frontend suite, 1577 passed in 114 files (main has 1518 in 110);
ESLint silent; the build done (the entry 651.7 kB, main 650.0; the editor's script 149.2 kB); `check:api` passes;
CodeQL, no finding in either language.

A failure is read and fixed test-first, or reported as it is: never a claim that every check passes when one didn't.

- [ ] **Step 2: The ledger**

Append `### 4f-2b, milestone 4 and the final checkpoint (<date>)`: the tasks' commits, each check's result as run,
whether the e2e spec ran locally or waits for CI, every mid-slice ruling, anything deferred. Commit it (`docs(editor-4):
4f-2b final checkpoint`), with the trailer.

- [ ] **Step 3: The final review and the pause**

A fresh reviewer, on the most capable model, reviews the whole branch:
- against this plan (its Review Focus first) and the spec's §3, §5.3–§5.11 and §6, with the boards;
- with the ledger's rulings in view.

Critical and important findings are fixed test-first, once; minor ones are listed. Then **stop**. The summary to the
owner lists the commits, the checks as run, the rulings made mid-slice, the review's findings and what was deferred.
Nothing is pushed and no PR is opened without the owner's word.
