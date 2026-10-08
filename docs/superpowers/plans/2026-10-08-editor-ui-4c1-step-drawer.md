# Editor UI 4c-1: the Step Drawer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 1 (2026-10-09).** For the owner's review. Nothing is built before the owner approves this plan. Nothing is
pushed and no PR is opened without the owner's OK in chat.

**Goal:** A person who may edit a workflow opens a step and sets it up in a drawer generated from its type's schema:
the required fields on Setup, the rest on Options, and its error handling in a chip. They choose connections,
workflows and live options, write formulas where the engine takes them, and rename the step. Every edit is saved like
any other and undone one field at a time, and every problem the server finds shows at its field.

**Architecture:**
- **Pure layers first (milestone 1).**
  - `lib/schemaForm.ts` reads a type's config schema as a form. It gives each field's place (Setup or Options), label,
    widget and allowed kinds of value, by the engine's own markers.
  - `lib/config.ts` changes a step's config, options and key as documents. A port a change removes takes its edges
    with it. A renamed key carries every structured reference along.
  - `lib/history.ts` coalesces one field's typing into one undo step.
- **One field, then the drawer (milestone 2).**
  - A field is a frame (label, control, hint, problems) around a control chosen by its widget, fixed or a formula.
  - The drawer replaces 4b's read-only step panel in the side column:
    - a header with the step's key, its type and the error-handling chip;
    - Setup and Options tabs (Radix Tabs, outline §4);
    - the 4b actions kept below.
  - Lists and maps come last.
- **References and behaviour (milestone 3).**
  - Connection, workflow and live-options pickers.
  - The error-handling chip and its error port.
  - Key rename.
  - A problem's "Go to" focuses its field.
- **The slice end to end (milestone 4).** Browser flows, every check, the ledger and the checkpoint.
- No backend change: every API the drawer reads exists on `main` (connections, workflows, node types with their
  schemas, the options call, validate).

**Tech Stack:**
- Frontend: React 19, Vite 6, TypeScript, TanStack Router and Query, Tailwind 4.3.3, openapi-fetch 0.17.0 over
  openapi-typescript 7.13.0 types, Radix. New: `@radix-ui/react-tabs` 1.1.21, approved in the outline's §4 at exactly
  that version.
- Tests: vitest (jsdom) and Testing Library; Playwright 1.63.0 with Chromium 1243 and @axe-core/playwright 4.13.0,
  through the browser gate (`e2e/gate.ts`), against the isolated Compose stack (`dewpoint-ui4a`).
- pnpm 12.6.0 runs as `npx -y pnpm@12.6.0`.

**Spec:**
- `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` (revision 4, ruled 2026-10-05): §2's slice 4c, decisions
  D8, D16, D17, D19, D21–D24, §4 (npm) and §6 (no AI tells).
- The architecture spec's §3.3 (the widget contract) and §10.3 (the step drawer).
- The ledger `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`: rulings 1–95, mid-slice rulings M1–M40, and
  the owner's 2026-10-08 decisions:
  - 4c is planned and built as three plans in sequence;
  - D8's undesigned surfaces get mockups first (4c-2);
  - `[skip ci]` is dropped.
- Design frame 1c of `docs/design/2026-10-05-dewpoint-ui.dc.html` (its drawer: lines 165–204), as data.
- The engine's own rules, read on `main` (0838e4f) for this plan:
  - `backend/src/dewpoint/sdk/fields.py`: the markers;
  - `engine/graph/schemas.py`: `literal_on_path`, `allowed_kinds`, `contains_literal`;
  - `engine/graph/values.py`: envelopes and reference paths;
  - `engine/graph/model.py`: the graph format a save checks;
  - `engine/graph/validate.py`: where a node's problems point.

## Global Constraints

- **CSP.** It stays exactly `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src
  'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'`. No inline
  script, no injected `<style>`, no third-party or CDN asset: every library is bundled. The browser gate fails any
  screen that violates it. A violation by `@radix-ui/react-tabs` stops the work at once, and the owner chooses (D23).
- **WCAG 2.2 AA.**
  - Text 4.5:1; boundaries, focus rings and graphics 3:1 (`PAIRS` in `src/styles/tokenNames.ts`).
  - Every control has a visible label, and its hint and errors are described by it.
  - A visible label is in the control's accessible name (2.5.3).
  - Every field is reachable and operable by keyboard.
  - Axe checks each drawer state in the browser gate.
- **No AI tells** (outline §6). The vitest guard (`src/test/aiTells.ts`) scans `src/`, and the checkpoint reviewer
  checks the screens. 1c's own tells are stripped:
  - its pills' rounded-full shape (data pills come with 4c-2);
  - its tinted "verified" badge (a status in words instead);
  - its accent halo on the open step (4b's 2 px border stays).
  The active tab's 2 px bottom rule is the one coloured rule allowed. Nested fields are indented, never marked with a
  left border.
- **Dependencies.** One new dependency, `@radix-ui/react-tabs` 1.1.21, pinned exactly. It must pass
  `scripts/licence-check.mjs` (D22) with no new exception and appear in the build's third-party notices (ledger
  ruling 65).
- **No real Mist or SaaS call, ever** (D24).
  - Unit tests use made-up types (`src/test/nodeTypes.ts`).
  - The browser flows drive the flow plugin's steps, and a Mist step only to choose a connection.
  - Live options load only when asked, never in the browser flows.
- **No backend change** in 4c-1, and so no migration and no OpenAPI change: `check:api` stays clean.
- **Secrets.**
  - A sensitive field's fixed value is never shown, nor its default, nor any value holding a sensitive part as JSON
    (ledger M25).
  - Logs name an exception's type only.
  - No secret in a URL, a log or browser storage. The client keeps no draft and no sample in browser storage.
- **The API decides every write.**
  - The client hides what a role can't do, but never relies on hiding it.
  - The browser checks only required fields and types (D19), plus the graph format rules a save would refuse: a key,
    a port's name, the attempts and timeout bounds. A draft breaking those isn't saved at all (4b ruling 9).
  - Every other rule is the server's.
- **Verify, don't remember.** Check every library API against the installed package before relying on it (Radix
  Tabs' parts and props in `node_modules/@radix-ui/react-tabs/dist/index.d.ts`), and every API path and body against
  `src/api/schema.d.ts`.
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker (the owner, 2026-10-08), so CI and
  CodeQL run on every push of a PR branch. Nothing is pushed and no PR is opened without the owner's OK in chat.

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the tests named, in
the task that owns it.

- **A value the drawer can't edit.**
  - The cases: a reference or a template written elsewhere (an import, the API); a type this server doesn't know; a
    fixed value in a sensitive field; an envelope the engine can't read.
  - Each is kept byte for byte until the person replaces it on purpose. The sensitive value is never shown.
  - Tests:
    - Task 2: `keeps what it doesn't touch`;
    - Task 5: `shows a reference read only, and keeps it until it's replaced`, `never shows a sensitive field's fixed
      value`;
    - Task 6: `keeps an unknown type's settings as they are`.
- **Typing fast, across fields, then undo.**
  - One undo step per field per focus, never per keystroke. Saves coalesce as in 4b.
  - Undo outside a field undoes the whole field's edit; inside a text control, the browser's own text undo stays.
  - Tests:
    - Task 3: `makes one step of a field's edits while it keeps its mark`, `starts a new step for another mark, an
      unmarked change, or after an undo`;
    - Task 5: `makes one mark of a field's typing while it keeps focus`;
    - Task 6: `makes a field's typing one undo step`.
- **An edit that removes a port with edges** (a switch case removed, errors no longer routed to a port, a JSON edit).
  - It asks first, deletes exactly those edges, and one undo restores both the setting and the edges.
  - A case's port renamed in place keeps its edges.
  - Tests:
    - Task 2: `drops only the lost ports' edges`, `keeps a renamed case's edges`;
    - Task 6: `asks before an edit takes a port with edges away`, `undoes the edit and its edges together`;
    - Task 7: `renames a case's port in place, its edges following`, `asks before removing a case with edges`;
    - Task 10: `asks before errors stop going to a port`.
- **Renaming a key that other steps read.**
  - Every reference and template part follows, in every step and in the workflow's outputs.
  - Formulas aren't rewritten: the drawer says how many still name the old key, and the server flags each.
  - Tests:
    - Task 2: `renames every structured reference`, `counts the formulas that still name it`;
    - Task 11: `says how many formulas still name the old key`.
- **Live options that can't load, or need a connection first.**
  - No request without the step's connection when its type takes one, and never a request on render.
  - Each failure is said in words; a value the person typed is kept as typed.
  - Tests, all in Task 9: `never loads on render`, `asks for a connection before loading`, `says why choices couldn't
    load, keeping a typed value`.

## Rulings this plan proposes

These join the ledger as rulings 96 onward when the slice is approved.

1. **4c in three plans.** 4c-1 is the drawer; 4c-2 is data; 4c-3 is triggers (the owner, 2026-10-08).
   - **4c-2, data:** B6's scope API; pills with the upstream tree; the condition builder; the "conditional" step
     badge (ruling 70); the declassify list; B7's samples with the per-attempt connection record in slot 0045 (which
     sub-project 3 didn't build). D8's surfaces come as static mockups first.
   - **4c-3, triggers:** B13; the manual input form and CSV columns; schedules; webhook bindings and Settings →
     Webhook endpoints; 1b's "What starts it?" and 1a's Trigger column (ruling 68); schedule sync errors raising
     "needs attention" (ruling 71).
   - Why: each is a 4b-sized piece with its own review. The cost: three plan reviews instead of one.
2. **The drawer replaces the step panel in the side column.**
   - Its header holds:
     - the key, renamable (Task 11);
     - the type's title and reference, and how the step runs;
     - the error-handling chip (Task 10).
   - Then come the problems that belong to no field, then the Setup and Options tabs.
   - Below the tabs:
     - how the step's formulas run (4b's list, kept);
     - the 4b actions: its "Add a step" twins (M32), Place and nudges, Connect, Delete.
   - Viewers, a version view, a conflict and a publication in progress see the drawer read only, its controls
     disabled.
   - There's no Test tab until 4d: 1c's third tab, and its footer's Run and Simulate buttons, wait without a teaser
     (D12's rule).
   - Why: 1c, and §10.3. The cost: the drawer is long for a step with many fields.
3. **Setup holds the schema's required top-level fields; Options holds the rest, in the schema's order.**
   - There's no `x-group`: no manifest uses it, and the plugins-3 ledger rules it out for flow steps.
   - A step with nothing required opens on Options. A step with no fields says so, without tabs.
   - A tab's label counts the problems in its fields ("Options · 2 problems").
   - Why: §10.3's "required fields only". The cost: a plugin can't order fields except through its schema.
4. **A field's label is its schema `title`, or its name when there's none.**
   - The flow plugin's generated titles ("Duration S", "Workflow Id") stay as they are: a title is part of a type's
     contract hash (`engine/registry/catalog.py`), so changing one means a new type version, not a UI change.
   - Why: plugins own their wording. The cost: some labels read stiffly until their plugin versions them.
5. **The widget comes from `x-widget`, then the engine's markers, then the field's type.**
   - From `x-widget`: `cel` gives a formula; `pill-text` gives text in 4c-1 and pills in 4c-2; `connection` gives the
     connection picker.
   - From the markers:
     - `x-dewpoint-connection` gives the connection picker;
     - a field the type lists in its `options` (`x-dewpoint-options`) gives the live options;
     - `flow.run_workflow`'s top-level `workflow_id` gives a workflow picker.
   - From the type:
     - a string enum is a select;
     - a `date-time` string is a text field with an ISO 8601 hint;
     - strings, numbers and booleans get their own inputs;
     - an object with properties is a group of fields;
     - an open object is a map of names to values;
     - an array of one item schema is a list;
     - anything else, an untyped field or a union, is JSON.
   - A plugin widget the drawer doesn't have (`mist.api-operation`, `message-blocks`, `nested-update`: 4f) falls back
     to its type's widget.
   - Why: §3.3; D24. The cost: none for today's manifests (only `cel` is in use).
6. **A value is fixed, or a formula, where the engine takes it.** These are the engine's own rules (`allowed_kinds`,
   `literal_on_path`, `contains_literal`, `sensitive.literal`):
   - A field whose path carries `x-dewpoint-literal` takes a fixed value only, and so does a whole that holds such a
     part (a switch's cases).
   - A field whose `x-dewpoint-kinds` lacks `literal` takes no fixed value; one whose kinds lack `cel` takes no
     formula.
   - A field marked `x-sensitive` takes no fixed value.
   - Where both are allowed, a "Fixed / Formula" choice switches between them. A formula field, an untyped one or a
     JSON one starts as a formula.
   - A formula is the CEL formula mode of D19: a monospace text area, with the server's diagnostics and how it runs
     (inline, or as a separate step with the reason).
   - A reference or a template already in the draft shows read only, with "Replace with a fixed value" or "Replace
     with a formula": editing those is 4c-2's pills.
   - A sensitive field holding a fixed value says so, never shows it, and offers to clear it or replace it with a
     formula (M25).
   - Why: D19. The cost: until 4c-2, references are typed as formulas.
7. **The browser checks only required fields, types, and what a save would refuse.**
   - A required field the person empties says "Required".
   - A number that doesn't parse says so and isn't saved, and so does JSON that doesn't parse.
   - A key, a port's name, and the attempts and timeout bounds are checked before saving: the graph's format refuses
     a draft that breaks them, so it wouldn't be saved at all (4b ruling 9).
   - Emptying a field removes it from the config, so its default applies. An optional field with a value offers
     "Clear".
   - Everything else is the server's diagnostics, shown at the field whose pointer they name.
   - Why: D19; ruling 81 (the server's own messages). The cost: none.
8. **One undo step per field per focus.**
   - A field's typing while it keeps focus coalesces into one history entry. Leaving the field, or any other edit,
     starts a new entry.
   - A discrete choice is one entry each: a select, a checkbox, Fixed or Formula, Add, Remove, Move.
   - Field edits aren't announced: the control says what it holds, and the toolbar says whether it's saved.
   - Saves follow D17 unchanged.
   - Why: undo by keystroke would make undo useless. The cost: none.
9. **Ports come and go with settings.**
   - An edit that takes ports away deletes the edges that left them, after asking, as deleting a step does (ruling
     79). The edits that can: removing a switch case, no longer routing errors to a port, a JSON edit of the cases.
     One undo restores the setting and the edges.
   - A case's port renamed in place keeps its edges. Its name applies when focus leaves or on Enter.
   - A port name the graph's format refuses, or one another port of the step has, is refused there: edges hang on
     port names.
   - A new case gets the first free port name `case_N`.
   - Why: a port's edges mean nothing without the port. The cost: none.
10. **The error-handling chip.**
    - It says, in words, what a failure does ("On error: fail the run"), plus the attempts and timeout when they
      differ from the type's.
    - It opens a section with three settings:
      - what a failure does: Fail the run, Continue with the next step, or Route to an error port;
      - the attempts (1–20);
      - the timeout (above 0, up to 86,400 s).
    - Each setting left empty takes the type's default, named in its hint. "Fail the run" is the default, so it
      isn't written.
    - Why: §10.3's chip, and the graph's `Options` bounds. The cost: none.
11. **Key rename.**
    - In the header. A key starts with a lowercase letter, then lowercase letters, digits or `_` (up to 63
      characters). It isn't one of CEL's words (`in`, `true`, `false`, `null`), and it's unique.
    - Every reference and template part reading `steps.<key>` or `loops.<key>` follows: in every step's config and in
      the workflow's outputs.
    - Formulas aren't rewritten (CEL text isn't parsed here): the drawer says how many still name the old key, and
      the server flags each.
    - It's one undo step.
    - Why: keys are how steps read each other. The cost: a formula needs its own fix.
12. **The connection picker.**
    - It lists this tenant's connections of the field's type (every role may read them), named, with their status in
      words.
    - With none of that type, it says so: Mist links to Connections (D1); other types are added by an admin (4g's
      forms come later).
    - A value naming no listed connection shows as "A connection that isn't in this tenant" until it's changed.
    - Why: §3.3. The cost: none.
13. **The workflow picker** (`flow.run_workflow`'s `workflow_id`).
    - It lists this tenant's workflows other than this one.
    - A value naming none shows as "A workflow that isn't in this tenant".
    - Why: typing a UUID is no way to choose. The cost: none.
14. **Live options load on request, never on render.**
    - A "Show choices" button loads them through `POST …/node-types/{ref}/options`, with the step's connection and the
      text typed.
    - When the type takes a connection and the step has none, the field asks for one first and sends nothing.
    - Each failure is said in words, and a typed value is kept as typed: the list helps, it doesn't gate.
    - Why: an options call reaches the plugin's service (for Mist, Mist itself), so it is the person's act, never a
      side effect of opening a drawer (D24). The cost: one click.
15. **JSON is the value as the engine reads it.**
    - A `{"$value": …}` object in it is computed, as in an imported file, and its hint says so.
    - It applies when focus leaves.
    - "Edit as JSON" is offered on groups, lists and maps without a sensitive part. Untyped fields and unions are JSON
      always.
    - A map's entry can't be named `$value`: the engine would read the whole map as computed.
    - Why: D19; one reading of `$value` everywhere. The cost: none.
16. **A problem focuses its field** (ruling 83, the part that waited for 4c).
    - "Go to" on a problem whose field is inside the step opens the step's drawer on that field's tab and focuses the
      field: the closest one shown, for a pointer inside a list, a map or a JSON value.
    - A pointer no field shows lands on "Problems with this step", which lists it.
    - A problem about the step as a whole (no field, or its whole config) focuses the step, as in 4b.
    - Why: ruling 83. The cost: none.
17. **One new dependency, `@radix-ui/react-tabs` 1.1.21**, for the drawer's tabs, on the outline's approved list.
    - Its first browser check is at the end of Task 6, before lists, maps and pickers are built.
    - A CSP violation stops the work for the owner.
    - Why: D23. The cost: none.

## File Structure

New, in `frontend/src/`:
- `lib/schemaForm.ts`: a config schema read as a form: fields, widgets, kinds, pointers, tabs.
- `lib/config.ts`: values and envelopes; a step's config, options and key changed as documents.
- `components/Tabs.tsx`: the token-styled Radix Tabs.
- `routes/editor/drawer/context.ts`: what a drawer's fields share; a field's problems; focus sessions.
- `routes/editor/drawer/FieldFrame.tsx`: a field's label, control, hint and problems; a group's fieldset.
- `routes/editor/drawer/scalars.tsx`: the controls for text, numbers, booleans, enums and JSON.
- `routes/editor/drawer/Formula.tsx`: the formula, the Fixed/Formula choice, a reference and a hidden sensitive
  value.
- `routes/editor/drawer/FieldView.tsx`: one field: its mode, its control, its problems.
- `routes/editor/drawer/structured.tsx`: groups, lists, maps, and a dynamic port's name.
- `routes/editor/drawer/StepDrawer.tsx`: the drawer.
- `routes/editor/drawer/ErrorHandling.tsx`: the chip and its section.
- `routes/editor/drawer/pickers.tsx`: the connection and workflow pickers.
- `routes/editor/drawer/LiveOptions.tsx`: options on request.
- `routes/editor/drawer/KeyField.tsx`: the header's rename.
- `routes/editor/drawer/harness.tsx`: fields on their own, for tests only.
- `test/nodeTypes.ts`: node types for tests: the flow plugin's schemas and a made-up service's.
- Tests beside each: `*.test.ts(x)`.

New, in `frontend/e2e/fixtures/`: `references.dewpoint.json`.

Changed:
- `lib/history.ts`: `record` with a coalescing mark.
- `components/Field.tsx`: `controlClass` exported.
- `routes/editor/Editor.tsx`:
  - `change` with a mark, and silent;
  - the drawer in place of `StepPanel`;
  - edits that drop edges ask first;
  - a problem's field.
- `routes/editor/ProblemsPanel.tsx`: "Go to" passes the field.
- `routes/editor/StepPanel.tsx`: removed, its parts moved into the drawer.
- Tests: `routes/editor/Editor.test.tsx`, `routes/editor/ProblemsPanel.test.tsx`.
- Browser flows: `e2e/workflows.spec.ts`, and `e2e/gate.spec.ts` (the notices list Radix Tabs).
- `package.json` and `pnpm-lock.yaml`.
- `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`.

## Milestones

- **Milestone 1 (Tasks 1–3): the pure layers.** No screen changes.
- **Milestone 2 (Tasks 4–7): Tabs, one field, the drawer, lists and maps.** **Pause:** screenshots of the drawer
  beside 1c, light and dark, at 1280 and 320 px, for the owner's review before references and behaviour are built.
- **Milestone 3 (Tasks 8–12): pickers, live options, error handling, key rename, a problem's field.**
- **Milestone 4 (Task 13): end to end, every check, the ledger, the final checkpoint.** **Pause:** a fresh reviewer,
  screenshots, the summary; then stop.

## How to run things

- Frontend, from `frontend/`:
  - one file: `npx -y pnpm@12.6.0 exec vitest run <file>`;
  - all tests: `npx -y pnpm@12.6.0 test`;
  - checks: `npx -y pnpm@12.6.0 lint`, `typecheck`, `check:api`, `build`;
  - licences: `node scripts/licence-check.mjs --self-test`, then
    `npx -y pnpm@12.6.0 licenses list --json [--prod] | node scripts/licence-check.mjs prod|all`.
- The browser gate: the session's `compose-ui4a/e2e.sh` resets the isolated stack (`dewpoint-ui4a`, plugins synced)
  and runs `E2E_BASE_URL=http://localhost:18080 npx -y pnpm@12.6.0 exec playwright test`: about 6 minutes.
- Local CodeQL: the session's `codeql/scan.sh <sha>` (CLI 2.27.1, the CI's query packs): about 40 seconds.
- The backend is untouched: its suite doesn't run for this slice (only what the change touches runs).

## Executing this plan

- Inline, in one session, with the owner's reviews at the milestones (the owner's practice since 4b). The work is
  test-first: each task's tests are written and seen failing for the stated reason before its code.
- The code below is the target. Where the installed package or the code base differs, the executor adapts it
  test-first and records the difference as a mid-slice ruling in the ledger (M41 onward).
- Branch `feat/editor-4c1`, cut from `origin/main` when execution starts (0838e4f at this revision), in a worktree of
  its own (`scratchpad/ui4/4c1`). The local `main` checkout is left alone. A later `main` is merged in, never rebased.

---

# Milestone 1: the pure layers

### Task 1: The schema read as a form

**Files:**
- Create: `frontend/src/test/nodeTypes.ts`
- Create: `frontend/src/lib/schemaForm.ts`
- Test: `frontend/src/lib/schemaForm.test.ts`

**Interfaces:**
- Consumes: `NodeType` from `lib/workflows.ts` (`config_schema`, `options: string[]`, `dynamic_ports: string | null`,
  `type`, `ref`).
- Produces, from `lib/schemaForm.ts`:
  - `type Schema = Record<string, unknown>`, `type Kind = "literal" | "ref" | "template" | "cel"`,
    `type Path = (string | number)[]`.
  - `type Widget = "formula" | "connection" | "workflow" | "options" | "enum" | "text" | "datetime" | "number" |
    "integer" | "boolean" | "group" | "list" | "map" | "json"`.
  - `interface FieldSpec { name; path: Path; pointer: string; schema: Schema; root: Schema; type: NodeType; label;
    hint: string | null; required; entry; widget: Widget; base: Widget; literalOnly; holdsLiteral; holdsSensitive;
    kinds: Kind[] | null; sensitive; untyped; port }` (booleans unless typed).
  - `isObject(v: unknown): v is Schema`, `pointerOf(path: Path): string`, `deref(schema: unknown, root: Schema):
    Schema`.
  - `fieldsOf(type: NodeType): FieldSpec[]`, `propertiesOf(f: FieldSpec): FieldSpec[]`, `itemOf(f: FieldSpec, index:
    number): FieldSpec`, `entryOf(f: FieldSpec, name: string): FieldSpec`.
  - `tabsOf(fields: FieldSpec[]): { setup: FieldSpec[]; options: FieldSpec[] }`.
  - `canFixed(f): boolean`, `canFormula(f): boolean`, `startsAsFormula(f): boolean`, `emptyOf(f): unknown`.
- Produces, from `test/nodeTypes.ts` (tests only): `typeWith(config_schema, more?)`, and the types `IF`, `SWITCH`,
  `LOOP`, `FILTER`, `DELAY`, `TRANSFORM`, `RUN_WORKFLOW`, `REMOTE`.

- [ ] **Step 1: Write the node types tests use**

The flow plugin's config schemas exactly as its catalog prints them (dumped from `main` 0838e4f on 2026-10-08), and a
made-up service step for the markers the flow plugin doesn't use. Create `frontend/src/test/nodeTypes.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// Node types for tests, as GET /api/v1/node-types serves them: the flow plugin's config schemas as its catalog prints
// them (main 0838e4f), and a made-up service's step that takes a connection, live options and a secret (D24: never
// Mist's own).
import type { NodeType } from "../lib/workflows";

const RETRY = { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] };

export const typeWith = (config_schema: Record<string, unknown>, more: Partial<NodeType> = {}): NodeType => ({
  ref: "test.step@1", type: "test.step", version: 1, kind: "action", state: "active", title: "Test step",
  description: "", icon: null, ports: ["out"], dynamic_ports: null, options: [], config_schema, output_schema: {},
  side_effect: "none", credentials: [], capabilities: [], retry: RETRY, timeout_s: 60, ...more,
});  // prettier-ignore

const flow = (name: string, title: string, ports: string[], schema: Record<string, unknown>, more: Partial<NodeType> = {}) =>
  typeWith(schema, { ref: `flow.${name}@1`, type: `flow.${name}`, kind: "control", title, ports, ...more });

export const IF = flow("if", "If", ["true", "false"], {
  additionalProperties: false, properties: { condition: { title: "Condition", type: "boolean", "x-widget": "cel" } },
  required: ["condition"], title: "IfConfig", type: "object",
});  // prettier-ignore

export const SWITCH = flow("switch", "Switch", ["default"], {
  $defs: {
    SwitchCase: {
      additionalProperties: false,
      properties: {
        port: { pattern: "^[a-z][a-z0-9_]{0,30}$", title: "Port", type: "string", "x-dewpoint-literal": true },
        when: { title: "When", type: "boolean", "x-widget": "cel" },
      },
      required: ["port", "when"], title: "SwitchCase", type: "object",
    },
  },
  additionalProperties: false,
  properties: { cases: { items: { $ref: "#/$defs/SwitchCase" }, maxItems: 20, minItems: 1, title: "Cases", type: "array" } },
  required: ["cases"], title: "SwitchConfig", type: "object",
}, { dynamic_ports: "cases" });  // prettier-ignore

export const LOOP = flow("loop", "Loop", ["body", "done"], {
  additionalProperties: false,
  properties: {
    items: { items: {}, title: "Items", type: "array" },
    concurrency: { default: 1, maximum: 10, minimum: 1, title: "Concurrency", type: "integer", "x-dewpoint-literal": true },
    item_cap: { default: 10000, maximum: 10000, minimum: 1, title: "Item Cap", type: "integer", "x-dewpoint-literal": true },
    on_item_error: { default: "stop", enum: ["stop", "continue"], title: "On Item Error", type: "string", "x-dewpoint-literal": true },
    collect: { default: null, title: "Collect" },
  },
  required: ["items"], title: "LoopConfig", type: "object",
});  // prettier-ignore

export const FILTER = flow("filter", "Filter", ["out"], {
  additionalProperties: false,
  properties: {
    items: { items: {}, title: "Items", type: "array" },
    predicate: { title: "Predicate", type: "boolean", "x-dewpoint-kinds": ["cel"], "x-widget": "cel" },
  },
  required: ["items", "predicate"], title: "FilterConfig", type: "object",
});  // prettier-ignore

export const DELAY = flow("delay", "Delay", ["out"], {
  additionalProperties: false,
  properties: { duration_s: { maximum: 2592000, minimum: 0, title: "Duration S", type: "integer" } },
  required: ["duration_s"], title: "DelayConfig", type: "object",
});  // prettier-ignore

export const TRANSFORM = flow("transform", "Transform", ["out"], {
  additionalProperties: false,
  properties: { fields: { additionalProperties: true, maxProperties: 100, minProperties: 1, title: "Fields", type: "object" } },
  required: ["fields"], title: "TransformConfig", type: "object",
});  // prettier-ignore

export const RUN_WORKFLOW = flow("run_workflow", "Run workflow", ["out"], {
  additionalProperties: false,
  properties: {
    workflow_id: { format: "uuid", title: "Workflow Id", type: "string", "x-dewpoint-literal": true },
    input: { additionalProperties: true, title: "Input", type: "object" },
  },
  required: ["workflow_id"], title: "RunWorkflowConfig", type: "object",
});  // prettier-ignore

/** A made-up service's step: a connection, a site among live choices, a secret, and the other shapes a schema takes. */
export const REMOTE = typeWith({
  type: "object", additionalProperties: false, required: ["connection", "site_id"],
  properties: {
    connection: { type: "string", format: "uuid", title: "Connection", "x-dewpoint-literal": true, "x-dewpoint-connection": "acme" },
    site_id: { type: "string", title: "Site", "x-dewpoint-options": true },
    token: { type: "string", title: "Token", "x-sensitive": true },
    query: {
      type: "object", title: "Query", additionalProperties: false,
      properties: { limit: { type: "integer", title: "Limit", default: 100, description: "How many to list." } },
    },
    mode: { type: "string", enum: ["fast", "safe"], title: "Mode" },
    when: { type: "string", format: "date-time", title: "When" },
    tags: { type: "array", title: "Tags", items: { type: "string" } },
    note: { anyOf: [{ type: "string" }, { type: "null" }], default: null, title: "Note" },
  },
}, { ref: "acme.sites@1", type: "acme.sites", title: "Sites", options: ["site_id"], credentials: ["acme"] });  // prettier-ignore
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/lib/schemaForm.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { DELAY, FILTER, IF, LOOP, REMOTE, RUN_WORKFLOW, SWITCH, TRANSFORM, typeWith } from "../test/nodeTypes";
import {
  canFixed, canFormula, emptyOf, entryOf, fieldsOf, itemOf, pointerOf, propertiesOf, startsAsFormula, tabsOf,
} from "./schemaForm";  // prettier-ignore

const field = (type: Parameters<typeof fieldsOf>[0], name: string) => fieldsOf(type).find((f) => f.name === name)!;

describe("fieldsOf", () => {
  it("reads each top-level property as a field, in the schema's order, labelled by its title", () => {
    expect(fieldsOf(REMOTE).map((f) => [f.name, f.label, f.widget, f.required])).toEqual([
      ["connection", "Connection", "connection", true],
      ["site_id", "Site", "options", true],
      ["token", "Token", "text", false],
      ["query", "Query", "group", false],
      ["mode", "Mode", "enum", false],
      ["when", "When", "datetime", false],
      ["tags", "Tags", "list", false],
      ["note", "Note", "text", false],
    ]);
  });

  it("chooses a formula for x-widget cel, a workflow picker for run_workflow, and a map for an open object", () => {
    expect(field(IF, "condition").widget).toBe("formula");
    expect(field(IF, "condition").base).toBe("boolean"); // the control for a fixed value
    expect(fieldsOf(RUN_WORKFLOW).map((f) => f.widget)).toEqual(["workflow", "map"]);
    expect(field(TRANSFORM, "fields").widget).toBe("map");
    expect(field(DELAY, "duration_s").widget).toBe("integer");
    expect(field(LOOP, "collect").widget).toBe("json"); // untyped
  });

  it("falls back to the type's widget for a plugin widget it doesn't have", () => {
    const blocks = typeWith({
      type: "object",
      properties: { blocks: { type: "array", items: { type: "object", properties: { text: { type: "string" } } }, "x-widget": "message-blocks" } },
    });  // prettier-ignore
    expect(fieldsOf(blocks)[0]!.widget).toBe("list");
  });

  it("follows $ref, drops a null branch, and labels a list's item by its place", () => {
    const item = itemOf(field(SWITCH, "cases"), 0);
    expect([item.widget, item.label, item.pointer]).toEqual(["group", "Cases, item 1", "/cases/0"]);
    expect(propertiesOf(item).map((f) => [f.name, f.widget, f.port, f.literalOnly])).toEqual([
      ["port", "text", true, true],
      ["when", "formula", false, false],
    ]);
    expect(field(REMOTE, "note").schema.type).toBe("string");
  });

  it("names each field by the JSON pointer the server's problems use", () => {
    expect(pointerOf(["fields", "a/b~c", 0])).toBe("/fields/a~1b~0c/0");
    expect(propertiesOf(field(REMOTE, "query"))[0]!.pointer).toBe("/query/limit");
    expect(entryOf(field(TRANSFORM, "fields"), "total").pointer).toBe("/fields/total");
  });

  it("hints a field's description, its default and a date's format, never a sensitive default", () => {
    expect(propertiesOf(field(REMOTE, "query"))[0]!.hint).toBe("How many to list. If empty: 100.");
    expect(field(REMOTE, "when").hint).toBe("A date and time in ISO 8601, like 2026-10-08T09:00:00Z.");
    const secret = typeWith({ type: "object", properties: { key: { type: "string", default: "s3cr3t", "x-sensitive": true } } });
    expect(fieldsOf(secret)[0]!.hint).toBeNull();
  });
});

it("puts the required fields on Setup and the rest on Options", () => {
  const { setup, options } = tabsOf(fieldsOf(LOOP));
  expect(setup.map((f) => f.name)).toEqual(["items"]);
  expect(options.map((f) => f.name)).toEqual(["concurrency", "item_cap", "on_item_error", "collect"]);
});

describe("the kinds of value a field takes", () => {
  it("takes a fixed value only where x-dewpoint-literal is on the path", () => {
    const concurrency = field(LOOP, "concurrency");
    expect([canFixed(concurrency), canFormula(concurrency)]).toEqual([true, false]);
    expect(canFormula(propertiesOf(itemOf(field(SWITCH, "cases"), 0))[0]!)).toBe(false);
  });

  it("takes no formula for a whole that holds a literal-only part", () => {
    expect(canFormula(field(SWITCH, "cases"))).toBe(false);
    expect(canFormula(itemOf(field(SWITCH, "cases"), 0))).toBe(false);
  });

  it("follows x-dewpoint-kinds: a predicate takes only a formula", () => {
    const predicate = field(FILTER, "predicate");
    expect([canFixed(predicate), canFormula(predicate), startsAsFormula(predicate)]).toEqual([false, true, true]);
  });

  it("takes no fixed value in a sensitive field, and knows a whole that holds one", () => {
    const token = field(REMOTE, "token");
    expect([canFixed(token), canFormula(token)]).toEqual([false, true]);
    const holder = typeWith({ type: "object", properties: { auth: { type: "object", properties: { key: { type: "string", "x-sensitive": true } } } } });
    expect(fieldsOf(holder)[0]!.holdsSensitive).toBe(true);
    expect(field(REMOTE, "query").holdsSensitive).toBe(false);
  });

  it("starts a condition, an untyped value and JSON as a formula, and a text as a fixed value", () => {
    expect(startsAsFormula(field(IF, "condition"))).toBe(true);
    expect(startsAsFormula(entryOf(field(TRANSFORM, "fields"), "x"))).toBe(true);
    expect(startsAsFormula(field(LOOP, "items"))).toBe(true);
    expect(startsAsFormula(field(REMOTE, "site_id"))).toBe(false);
  });
});

it("empties a property by removing it, and a list's item or a map's entry by blanking it", () => {
  expect(emptyOf(field(REMOTE, "tags"))).toBeUndefined();
  expect(emptyOf(itemOf(field(REMOTE, "tags"), 0))).toBe("");
  expect(emptyOf(entryOf(field(TRANSFORM, "fields"), "x"))).toBeNull();
});
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/schemaForm.test.ts`
Expected: FAIL. The module `./schemaForm` doesn't exist.

- [ ] **Step 4: Write the module**

Create `frontend/src/lib/schemaForm.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// A step type's config schema read as a form (4c-1): each field's place, label and widget, and the kinds of value it
// takes, by the engine's own markers (sdk/fields.py; engine/graph/schemas.py's literal_on_path, allowed_kinds and
// contains_literal) and the widget contract (§3.3). Nothing here validates: the server does (D19).
import type { NodeType } from "./workflows";

export type Schema = Record<string, unknown>;
export type Kind = "literal" | "ref" | "template" | "cel";
export type Path = (string | number)[];
export type Widget =
  | "formula" | "connection" | "workflow" | "options" | "enum" | "text" | "datetime" | "number" | "integer"
  | "boolean" | "group" | "list" | "map" | "json";  // prettier-ignore

export interface FieldSpec {
  name: string; // the property's or the entry's name, or a list item's index
  path: Path; // where its value sits in the step's config
  pointer: string; // the same, as the JSON pointer the server's problems name
  schema: Schema; // its schema, references followed and a null branch dropped
  root: Schema; // the type's config schema: what references resolve against
  type: NodeType;
  label: string;
  hint: string | null; // its description, its default, a date's format
  required: boolean;
  entry: boolean; // a list's item or a map's entry: emptied, it keeps its place, blank
  widget: Widget; // what edits it (ruling 5)
  base: Widget; // what edits a fixed value of it: its type's widget
  literalOnly: boolean; // `x-dewpoint-literal` here or above: written, never computed
  holdsLiteral: boolean; // it or a part must be written: the whole can't be computed
  holdsSensitive: boolean; // it or a part is sensitive: never shown as JSON
  kinds: Kind[] | null; // `x-dewpoint-kinds` here, or null for any
  sensitive: boolean; // `x-sensitive`: never a fixed value, never shown
  untyped: boolean; // any JSON
  port: boolean; // a dynamic port's name (a switch case's `port`): edges hang on it
}

const KINDS: ReadonlySet<string> = new Set(["literal", "ref", "template", "cel"]);
const BLANK_IS_TEXT: ReadonlySet<Widget> = new Set(["text", "datetime", "enum", "options"]);
const DATE_TIME = "A date and time in ISO 8601, like 2026-10-08T09:00:00Z.";

export const isObject = (v: unknown): v is Schema => typeof v === "object" && v !== null && !Array.isArray(v);
const without = (s: Schema, key: string): Schema => Object.fromEntries(Object.entries(s).filter(([k]) => k !== key));

export const pointerOf = (path: Path): string =>
  path.map((p) => `/${String(p).replace(/~/g, "~0").replace(/\//g, "~1")}`).join("");

function target(ref: string, root: Schema): Schema {
  if (!ref.startsWith("#/")) return {};
  const found = ref
    .slice(2)
    .split("/")
    .reduce<unknown>((at, k) => (isObject(at) ? at[k.replace(/~1/g, "/").replace(/~0/g, "~")] : undefined), root);
  return isObject(found) ? found : {};
}

/** A schema with its local `$ref` followed, and a `null` branch dropped (`anyOf: [X, {type: "null"}]`, `type: [X,
 * "null"]`): the shape its value has when it's set. Its own keywords win over the target's. */
export function deref(schema: unknown, root: Schema): Schema {
  let s: Schema = isObject(schema) ? schema : {};
  for (let depth = 0; depth < 32 && typeof s.$ref === "string"; depth++) s = { ...target(s.$ref, root), ...without(s, "$ref") };
  for (const key of ["anyOf", "oneOf"]) {
    const branches = s[key];
    if (!Array.isArray(branches)) continue;
    const real = (branches as unknown[]).filter((b) => !(isObject(b) && b.type === "null"));
    if (real.length === 1 && real.length < branches.length) return deref({ ...(isObject(real[0]) ? real[0] : {}), ...without(s, key) }, root);
  }
  if (Array.isArray(s.type)) {
    const real = (s.type as unknown[]).filter((t) => t !== "null");
    if (real.length === 1) return { ...s, type: real[0] };
  }
  return s;
}

/** Whether the schema, or a part of it, carries the marker: engine/graph/schemas.py's contains_literal, for any marker. */
function holds(marker: string, schema: unknown, root: Schema, seen: ReadonlySet<string> = new Set()): boolean {
  if (!isObject(schema)) return false;
  if (schema[marker] === true) return true;
  const ref = schema.$ref;
  if (typeof ref === "string" && !seen.has(ref) && holds(marker, target(ref, root), root, new Set([...seen, ref]))) return true;
  const children: unknown[] = [
    ...(isObject(schema.properties) ? Object.values(schema.properties) : []),
    schema.items,
    schema.additionalProperties,
    ...["anyOf", "oneOf", "allOf", "prefixItems"].flatMap((k) => (Array.isArray(schema[k]) ? (schema[k] as unknown[]) : [])),
  ];
  return children.some((child) => holds(marker, child, root, seen));
}

/** The widget a value of this schema takes by its type alone. */
function byType(s: Schema): Widget {
  if (Array.isArray(s.enum) && s.enum.length > 0 && (s.enum as unknown[]).every((v) => typeof v === "string")) return "enum";
  switch (s.type) {
    case "string":
      return s.format === "date-time" ? "datetime" : "text";
    case "integer":
      return "integer";
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "object":
      if (isObject(s.properties) && Object.keys(s.properties).length > 0) return "group";
      return s.additionalProperties === false ? "json" : "map";
    case "array":
      return isObject(s.items) && Object.keys(s.items).length > 0 ? "list" : "json";
    default:
      return "json";
  }
}

/** Ruling 5: `x-widget`, then the engine's markers (top-level only), then the type. */
function widgetOf(s: Schema, name: string, top: boolean, type: NodeType): Widget {
  if (s["x-widget"] === "cel") return "formula";
  if (s["x-widget"] === "connection" || typeof s["x-dewpoint-connection"] === "string") return "connection";
  if (top && type.type === "flow.run_workflow" && name === "workflow_id") return "workflow";
  if (top && type.options.includes(name)) return "options";
  return byType(s);
}

function hintOf(s: Schema, widget: Widget, sensitive: boolean): string | null {
  const parts: string[] = [];
  if (typeof s.description === "string" && s.description.trim() !== "") parts.push(s.description.trim());
  if (widget === "datetime") parts.push(DATE_TIME);
  // A default is said, unless it's a sensitive one (ledger M25: a secret is never repeated).
  if (!sensitive && s.default !== undefined && s.default !== null) {
    parts.push(`If empty: ${typeof s.default === "string" ? s.default : JSON.stringify(s.default)}.`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}

function make(type: NodeType, root: Schema, name: string, path: Path, raw: unknown, required: boolean, entry: boolean, literalAbove: boolean): FieldSpec {
  const own = isObject(raw) ? raw : {};
  const schema = deref(own, root);
  const widget = widgetOf(schema, name, path.length === 1, type);
  const sensitive = own["x-sensitive"] === true || schema["x-sensitive"] === true;
  const kinds = own["x-dewpoint-kinds"] ?? schema["x-dewpoint-kinds"];
  return {
    name, path, pointer: pointerOf(path), schema, root, type,
    label: typeof schema.title === "string" && schema.title.trim() !== "" ? schema.title : name,
    hint: hintOf(schema, widget, sensitive),
    required, entry, widget, base: byType(schema),
    literalOnly: literalAbove || own["x-dewpoint-literal"] === true || schema["x-dewpoint-literal"] === true,
    holdsLiteral: holds("x-dewpoint-literal", own, root),
    holdsSensitive: holds("x-sensitive", own, root),
    kinds: Array.isArray(kinds) ? (kinds as unknown[]).filter((k): k is Kind => typeof k === "string" && KINDS.has(k)) : null,
    sensitive,
    untyped: !["type", "enum", "const", "properties", "items"].some((k) => k in schema),
    port: type.dynamic_ports !== null && path.length === 3 && path[0] === type.dynamic_ports && typeof path[1] === "number" && path[2] === "port",
  };  // prettier-ignore
}

function propertiesIn(type: NodeType, root: Schema, schema: Schema, base: Path, literalAbove: boolean): FieldSpec[] {
  const props = isObject(schema.properties) ? schema.properties : {};
  const required = Array.isArray(schema.required) ? (schema.required as unknown[]) : [];
  return Object.entries(props).map(([name, raw]) =>
    make(type, root, name, [...base, name], raw, required.includes(name), false, literalAbove),
  );
}

/** A type's settings: its config schema's top-level properties, in the schema's order. */
export function fieldsOf(type: NodeType): FieldSpec[] {
  const root = isObject(type.config_schema) ? type.config_schema : {};
  return propertiesIn(type, root, deref(root, root), [], false);
}

/** A group's parts: its properties. */
export const propertiesOf = (f: FieldSpec): FieldSpec[] => propertiesIn(f.type, f.root, f.schema, f.path, f.literalOnly);

/** A list's item, labelled by its place ("Cases, item 1"). */
export const itemOf = (f: FieldSpec, index: number): FieldSpec => ({
  ...make(f.type, f.root, String(index), [...f.path, index], f.schema.items, true, true, f.literalOnly),
  label: `${f.label}, item ${index + 1}`,
});

/** A map's entry: its value takes the map's `additionalProperties`, or any JSON. */
export const entryOf = (f: FieldSpec, name: string): FieldSpec =>
  make(f.type, f.root, name, [...f.path, name], isObject(f.schema.additionalProperties) ? f.schema.additionalProperties : {}, true, true, f.literalOnly);  // prettier-ignore

/** Setup holds the required top-level fields, Options the rest, each in the schema's order (ruling 3). */
export const tabsOf = (fields: FieldSpec[]) => ({
  setup: fields.filter((f) => f.required),
  options: fields.filter((f) => !f.required),
});

/** Where the engine takes a fixed value: not in a sensitive field (sensitive.literal), and `literal` among its kinds. */
export const canFixed = (f: FieldSpec): boolean => !f.sensitive && (f.kinds === null || f.kinds.includes("literal"));

/** Where it takes a formula: no literal-only marker on the path or inside (value.literal_only), `cel` among its kinds. */
export const canFormula = (f: FieldSpec): boolean =>
  !f.literalOnly && !f.holdsLiteral && (f.kinds === null || f.kinds.includes("cel"));

/** A field empty so far starts as a formula when its widget is one, when it's any JSON, or when it takes nothing else. */
export const startsAsFormula = (f: FieldSpec): boolean =>
  canFormula(f) && (f.widget === "formula" || f.widget === "json" || !canFixed(f));

/** What emptying a field writes: nothing (it's removed, so its default applies), or, for a list's item or a map's
 * entry, a blank that keeps its place. */
export const emptyOf = (f: FieldSpec): unknown => (f.entry ? (BLANK_IS_TEXT.has(f.widget) ? "" : null) : undefined);
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/schemaForm.test.ts`
Expected: PASS, 13 tests.

- [ ] **Step 6: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/schemaForm.ts frontend/src/lib/schemaForm.test.ts frontend/src/test/nodeTypes.ts
git commit -m "feat(editor): read a step type's config schema as a form (4c-1)"
```

### Task 2: A step's values, config, options and key as documents

**Files:**
- Create: `frontend/src/lib/config.ts`
- Test: `frontend/src/lib/config.test.ts`

**Interfaces:**
- Consumes:
  - from Task 1: `Path`, `isObject`;
  - from `lib/graph.ts`: `edgesOf`, `findNode`, `nodesOf`, `portOf`, `portsOf`, `sameId`.
- Produces, from `lib/config.ts`:
  - Values:
    - `ENVELOPE = "$value"`, `MAX_FORMULA = 16_384`, `CEL_WORDS: ReadonlySet<string>`;
    - `type ValueKind = "literal" | "ref" | "template" | "cel"`;
    - `kindOf(value): ValueKind | "unknown" | null`;
    - `formula(expr: string)`, `formulaOf(value): string`, `fixedOf(value): unknown`, `referenceText(value): string`,
      `isPlainRef(value): boolean`.
  - Paths: `valueAt(root, path: Path): unknown`, `setAt(root, path: Path, value): unknown`. An undefined value
    removes a property or splices a list's item.
  - Changes:
    - `interface Changed { doc: GraphDoc; dropped: GraphEdge[] }`;
    - `type StepOptions = NonNullable<GraphNode["options"]>`;
    - `setConfig(doc, nodeId, path, value, type: NodeType | undefined): Changed`;
    - `setOptions(doc, nodeId, options: StepOptions, type: NodeType | undefined): Changed`;
    - `renamePort(doc, nodeId, index: number, name: string, type: NodeType): { doc: GraphDoc } | { problem: string }`;
    - `freePort(node: GraphNode, type: NodeType): string`.
  - Keys: `keyProblem(doc, nodeId, key): string | null`, `renameKey(doc, nodeId, key): { doc: GraphDoc; formulas:
    number }`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/config.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { IF, SWITCH } from "../test/nodeTypes";
import {
  CEL_WORDS, fixedOf, formula, formulaOf, freePort, isPlainRef, keyProblem, kindOf, referenceText, renameKey,
  renamePort, setAt, setConfig, setOptions, valueAt,
} from "./config";  // prettier-ignore
import type { GraphDoc } from "./workflows";

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const C = "00000000-0000-4000-8000-00000000000c";

/** A switch `pick` whose cases a and b lead to `left` and `right`, and whose default port leads to `right` too. */
const switchDoc = (): GraphDoc => ({
  graph_format: 1,
  nodes: [
    { id: A, key: "pick", type: "flow.switch@1", config: { cases: [{ port: "a", when: formula("true") }, { port: "b", when: formula("false") }] } },
    { id: B, key: "left", type: "flow.transform@1", config: { fields: { x: { $value: { kind: "ref", path: "steps.pick.output.n" } } } } },
    { id: C, key: "right", type: "flow.transform@1", config: {} },
  ],
  edges: [
    { from: { node: A, port: "a" }, to: { node: B } },
    { from: { node: A, port: "b" }, to: { node: C } },
    { from: { node: A, port: "default" }, to: { node: C } },
  ],
});  // prettier-ignore

describe("values", () => {
  it("tells a fixed value from a computed one", () => {
    expect(kindOf("text")).toBeNull();
    expect(kindOf({ $value: { kind: "cel", expr: "1" } })).toBe("cel");
    expect(kindOf({ $value: { kind: "nope" } })).toBe("unknown");
    expect(fixedOf({ $value: { kind: "literal", value: { $value: 1 } } })).toEqual({ $value: 1 });
    expect(formulaOf(formula("a + 1"))).toBe("a + 1");
  });

  it("reads a reference or a template as text", () => {
    expect(referenceText({ $value: { kind: "ref", path: "steps.a.output" } })).toBe("steps.a.output");
    expect(referenceText({ $value: { kind: "template", parts: [{ text: "Hi " }, { ref: "trigger.name" }] } })).toBe("Hi {trigger.name}");
    expect(isPlainRef({ $value: { kind: "ref", path: "steps.a.output" } })).toBe(true);
    expect(isPlainRef({ $value: { kind: "ref", path: "steps.a.output", default: 0 } })).toBe(false);
  });
});

describe("paths", () => {
  it("copies only along the path, and keeps what it doesn't touch", () => {
    const config = { a: { b: 1 }, keep: { deep: [1, 2] } };
    const next = setAt(config, ["a", "b"], 2) as typeof config;
    expect(next).toEqual({ a: { b: 2 }, keep: { deep: [1, 2] } });
    expect(next.keep).toBe(config.keep);
    expect(config.a.b).toBe(1);
  });

  it("removes a property, and splices a list's item, for undefined", () => {
    expect(setAt({ a: 1, b: 2 }, ["a"], undefined)).toEqual({ b: 2 });
    expect(setAt({ l: [1, 2, 3] }, ["l", 1], undefined)).toEqual({ l: [1, 3] });
    expect(valueAt({ l: [{ x: 5 }] }, ["l", 0, "x"])).toBe(5);
    expect(valueAt({ l: 1 }, ["l", "x"])).toBeUndefined();
  });
});

describe("setConfig", () => {
  it("drops only the lost ports' edges", () => {
    const doc = switchDoc();
    const { doc: next, dropped } = setConfig(doc, A, ["cases", 1], undefined, SWITCH);
    expect(dropped).toEqual([doc.edges![1]]);
    expect(next.edges).toEqual([doc.edges![0], doc.edges![2]]);
  });

  it("keeps every edge when a change takes no port away", () => {
    const doc = switchDoc();
    const { doc: next, dropped } = setConfig(doc, A, ["cases", 0, "when"], formula("1 > 0"), SWITCH);
    expect(dropped).toEqual([]);
    expect(next.edges).toBe(doc.edges);
  });

  it("keeps what it doesn't touch", () => {
    const doc = switchDoc();
    const { doc: next } = setConfig(doc, A, ["cases", 0, "when"], formula("1 > 0"), SWITCH);
    expect(next.nodes![1]).toBe(doc.nodes![1]);
    expect((next.nodes![0]!.config!.cases as unknown[])[1]).toBe((doc.nodes![0]!.config!.cases as unknown[])[1]);
  });
});

describe("ports", () => {
  it("keeps a renamed case's edges", () => {
    const result = renamePort(switchDoc(), A, 0, "big", SWITCH);
    if ("problem" in result) throw new Error(result.problem);
    expect(result.doc.edges![0]!.from).toEqual({ node: A, port: "big" });
    expect((result.doc.nodes![0]!.config!.cases as { port: string }[])[0]!.port).toBe("big");
  });

  it("refuses a name the graph's format refuses, or one another port has", () => {
    expect(renamePort(switchDoc(), A, 0, "Big", SWITCH)).toEqual({
      problem: "A port's name starts with a lowercase letter, then lowercase letters, digits or _, up to 31 characters.",
    });
    expect(renamePort(switchDoc(), A, 0, "default", SWITCH)).toEqual({ problem: "Another port of this step is already called default." });
  });

  it("names a new case's port after the first free case_N", () => {
    expect(freePort(switchDoc().nodes![0]!, SWITCH)).toBe("case_1");
  });

  it("drops the error port's edges when errors no longer go there", () => {
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [{ id: A, key: "check", type: "flow.if@1", options: { on_error: "port" } }, { id: B, key: "alarm", type: "flow.transform@1" }],
      edges: [{ from: { node: A, port: "error" }, to: { node: B } }],
    };  // prettier-ignore
    const { doc: next, dropped } = setOptions(doc, A, { on_error: "fail" }, IF);
    expect(dropped).toHaveLength(1);
    expect(next.nodes![0]).not.toHaveProperty("options");
    expect(next.edges).toEqual([]);
  });

  it("writes only the options the step sets, and never the default failure", () => {
    const { doc: next } = setOptions(switchDoc(), A, { on_error: "continue", max_attempts: 5, timeout_s: null }, SWITCH);
    expect(next.nodes![0]!.options).toEqual({ on_error: "continue", max_attempts: 5 });
  });
});

describe("keys", () => {
  it("says what's wrong with a key, or nothing", () => {
    const doc = switchDoc();
    expect(keyProblem(doc, A, "pick_2")).toBeNull();
    expect(keyProblem(doc, A, "pick")).toBeNull(); // its own
    expect(keyProblem(doc, A, "Left")).toBe("A key starts with a lowercase letter, then lowercase letters, digits or _, up to 63 characters.");
    expect(keyProblem(doc, A, "left")).toBe("Another step is already called left.");
    for (const word of CEL_WORDS) expect(keyProblem(doc, A, word)).toBe(`${word} can't be a key: formulas couldn't name the step.`);
  });

  it("renames every structured reference", () => {
    const doc: GraphDoc = {
      ...switchDoc(),
      settings: { outputs: { n: { $value: { kind: "template", parts: [{ text: "n=" }, { ref: "steps.pick.output.n" }] } } } },
    };
    const { doc: next } = renameKey(doc, A, "route");
    expect(next.nodes![0]!.key).toBe("route");
    expect(next.nodes![1]!.config).toEqual({ fields: { x: { $value: { kind: "ref", path: "steps.route.output.n" } } } });
    expect(next.settings!.outputs).toEqual({ n: { $value: { kind: "template", parts: [{ text: "n=" }, { ref: "steps.route.output.n" }] } } });
    expect(next.nodes![2]).toBe(doc.nodes![2]);
  });

  it("leaves a reference to a longer key alone, and a fixed value's data", () => {
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [
        { id: A, key: "pick", type: "flow.if@1" },
        {
          id: B, key: "x", type: "flow.transform@1",
          config: { fields: {
            a: { $value: { kind: "ref", path: "steps.picker.output" } },
            b: { $value: { kind: "literal", value: { $value: { kind: "ref", path: "steps.pick.output" } } } },
          } },
        },
      ],
    };  // prettier-ignore
    expect(renameKey(doc, A, "route").doc.nodes![1]).toBe(doc.nodes![1]);
  });

  it("counts the formulas that still name it", () => {
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [
        { id: A, key: "pick", type: "flow.if@1" },
        { id: B, key: "x", type: "flow.if@1", config: { condition: formula("steps.pick.output.n > 1 && loops.pick.index == 0") } },
        { id: C, key: "y", type: "flow.if@1", config: { condition: formula("steps.picker.output") } },
      ],
    };  // prettier-ignore
    expect(renameKey(doc, A, "route").formulas).toBe(1);
  });
});
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/config.test.ts`
Expected: FAIL. The module `./config` doesn't exist.

- [ ] **Step 3: Write the module**

Create `frontend/src/lib/config.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// A step's values, and the drawer's changes to a draft, as pure functions (4c-1). A value is fixed (any JSON) or
// computed: `{"$value": {kind, ...}}` (engine/graph/values.py), a formula (`cel`), a reference (`ref`) or text with
// references (`template`); a `literal` envelope is a fixed value written the long way. Each change returns a new
// document and keeps what it doesn't touch as it was, byte for byte.
import { edgesOf, findNode, nodesOf, portOf, portsOf, sameId } from "./graph";
import { isObject, type Path } from "./schemaForm";
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";

export const ENVELOPE = "$value";
export const MAX_FORMULA = 16_384; // engine/graph/values.py's MAX_CEL
export const CEL_WORDS: ReadonlySet<string> = new Set(["in", "true", "false", "null"]); // CEL can't select them
const KEY = /^[a-z][a-z0-9_]{0,62}$/; // engine/graph/model.py's KEY_PATTERN: a draft breaking it isn't saved
const PORT = /^[a-z][a-z0-9_]{0,30}$/; // and its PORT_PATTERN, which every edge's port must match

export type ValueKind = "literal" | "ref" | "template" | "cel";
export type StepOptions = NonNullable<GraphNode["options"]>;
export interface Changed {
  doc: GraphDoc;
  dropped: GraphEdge[]; // the edges that left a port the change took away
}

const bodyOf = (value: unknown): Record<string, unknown> =>
  isObject(value) && isObject(value[ENVELOPE]) ? value[ENVELOPE] : {};

/** A computed value's kind; "unknown" for an object with `$value` the engine can't read; null for a fixed value. */
export function kindOf(value: unknown): ValueKind | "unknown" | null {
  if (!isObject(value) || !(ENVELOPE in value)) return null;
  const kind = bodyOf(value).kind;
  return kind === "literal" || kind === "ref" || kind === "template" || kind === "cel" ? kind : "unknown";
}

export const formula = (expr: string) => ({ [ENVELOPE]: { kind: "cel", expr } });

export function formulaOf(value: unknown): string {
  const expr = bodyOf(value).expr;
  return kindOf(value) === "cel" && typeof expr === "string" ? expr : "";
}

/** A fixed value as written: a `literal` envelope's own value, or the value itself. */
export const fixedOf = (value: unknown): unknown => (kindOf(value) === "literal" ? bodyOf(value).value : value);

/** A reference as its path, or a template as its parts, each reference in braces. */
export function referenceText(value: unknown): string {
  const body = bodyOf(value);
  if (body.kind === "ref") return typeof body.path === "string" ? body.path : "";
  if (body.kind !== "template" || !Array.isArray(body.parts)) return "";
  return (body.parts as unknown[])
    .map((p) => (!isObject(p) ? "" : typeof p.ref === "string" ? `{${p.ref}}` : typeof p.text === "string" ? p.text : ""))
    .join("");
}

/** A reference with no default: the same path reads the same value as a formula. */
export const isPlainRef = (value: unknown): boolean => kindOf(value) === "ref" && !("default" in bodyOf(value));

export function valueAt(root: unknown, path: Path): unknown {
  let at = root;
  for (const key of path) {
    if (typeof key === "number" && Array.isArray(at)) at = (at as unknown[])[key];
    else if (typeof key === "string" && isObject(at)) at = at[key];
    else return undefined;
  }
  return at;
}

/** `root` with `value` at `path`, copied along the path only. Undefined removes a property, or splices a list's item. */
export function setAt(root: unknown, path: Path, value: unknown): unknown {
  const [key, ...rest] = path;
  if (key === undefined) return value;
  if (typeof key === "number") {
    const list = Array.isArray(root) ? [...(root as unknown[])] : [];
    if (rest.length === 0 && value === undefined) list.splice(key, 1);
    else list[key] = setAt(list[key], rest, value);
    return list;
  }
  const object = isObject(root) ? root : {};
  if (rest.length === 0 && value === undefined) return Object.fromEntries(Object.entries(object).filter(([k]) => k !== key));
  return { ...object, [key]: setAt(object[key], rest, value) };
}

function withNode(doc: GraphDoc, nodeId: string, node: GraphNode): GraphDoc {
  return { ...doc, nodes: nodesOf(doc).map((n) => (sameId(n.id, nodeId) ? node : n)) };
}

/** The document without the edges that left a port `before` had and `after` hasn't; edges from a port the step never
 * had (an import's) stay: the validator reports them. */
function dropLost(doc: GraphDoc, before: GraphNode, after: GraphNode, type: NodeType | undefined): Changed {
  const kept = new Set(portsOf(after, type));
  const lost = portsOf(before, type).filter((p) => !kept.has(p));
  const dropped = edgesOf(doc).filter((e) => sameId(e.from.node, before.id) && lost.includes(portOf(e)));
  if (dropped.length === 0) return { doc, dropped };
  return { doc: { ...doc, edges: edgesOf(doc).filter((e) => !dropped.includes(e)) }, dropped };
}

export function setConfig(doc: GraphDoc, nodeId: string, path: Path, value: unknown, type: NodeType | undefined): Changed {
  const before = findNode(doc, nodeId);
  if (!before) return { doc, dropped: [] };
  const after = { ...before, config: setAt(before.config ?? {}, path, value) as Record<string, unknown> };
  return dropLost(withNode(doc, nodeId, after), before, after, type);
}

/** What a step sets for itself; what it leaves out takes the type's defaults, and a failure fails the run by default,
 * so "fail" isn't written. */
export function setOptions(doc: GraphDoc, nodeId: string, options: StepOptions, type: NodeType | undefined): Changed {
  const before = findNode(doc, nodeId);
  if (!before) return { doc, dropped: [] };
  const own = Object.fromEntries(
    Object.entries(options).filter(([k, v]) => v !== undefined && v !== null && !(k === "on_error" && v === "fail")),
  ) as StepOptions;
  const after: GraphNode = Object.keys(own).length > 0
    ? { ...before, options: own }
    : (Object.fromEntries(Object.entries(before).filter(([k]) => k !== "options")) as GraphNode);  // prettier-ignore
  return dropLost(withNode(doc, nodeId, after), before, after, type);
}

/** A dynamic port renamed where its entry sits (a switch case's `port`): its edges follow it. Refused, with the reason,
 * for a name the graph's format refuses or one another port of the step has: edges hang on port names (ruling 9). */
export function renamePort(doc: GraphDoc, nodeId: string, index: number, name: string, type: NodeType): { doc: GraphDoc } | { problem: string } {
  const node = findNode(doc, nodeId);
  const field = type.dynamic_ports;
  if (!node || field === null) return { doc };
  const old = valueAt(node.config ?? {}, [field, index, "port"]);
  if (old === name) return { doc };
  if (!PORT.test(name)) {
    return { problem: "A port's name starts with a lowercase letter, then lowercase letters, digits or _, up to 31 characters." };
  }
  if (portsOf(node, type).includes(name)) return { problem: `Another port of this step is already called ${name}.` };
  const after = { ...node, config: setAt(node.config ?? {}, [field, index, "port"], name) as Record<string, unknown> };
  const next = withNode(doc, nodeId, after);
  // Another entry may still declare the old name (a duplicate): its edges are that entry's then.
  if (typeof old !== "string" || portsOf(after, type).includes(old)) return { doc: next };
  return {
    doc: {
      ...next,
      edges: edgesOf(next).map((e) => (sameId(e.from.node, nodeId) && portOf(e) === old ? { ...e, from: { ...e.from, port: name } } : e)),
    },
  };
}

/** The first `case_N` no port of the step has: a new case's port. */
export function freePort(node: GraphNode, type: NodeType): string {
  const taken = new Set(portsOf(node, type));
  for (let n = 1; ; n++) if (!taken.has(`case_${n}`)) return `case_${n}`;
}

/** Why a step can't take this key, or null (ruling 11). The pattern is the graph's format; the rest the validator's. */
export function keyProblem(doc: GraphDoc, nodeId: string, key: string): string | null {
  if (!KEY.test(key)) return "A key starts with a lowercase letter, then lowercase letters, digits or _, up to 63 characters.";
  if (CEL_WORDS.has(key)) return `${key} can't be a key: formulas couldn't name the step.`;
  if (nodesOf(doc).some((n) => n.key === key && !sameId(n.id, nodeId))) return `Another step is already called ${key}.`;
  return null;
}

/** A step's key changed, with every structured reference to it (`steps.<key>`, `loops.<key>`) in every step's config
 * and the workflow's outputs. Formulas aren't parsed here: they keep the old key, and `formulas` counts the ones that
 * name it. A fixed value's data is data, never rewritten. */
export function renameKey(doc: GraphDoc, nodeId: string, key: string): { doc: GraphDoc; formulas: number } {
  const node = findNode(doc, nodeId);
  if (!node || node.key === key) return { doc, formulas: 0 };
  const old = node.key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const path = new RegExp(`^((?:steps|loops)\\.)${old}(?=$|[.[])`);
  const named = new RegExp(`(?<![\\w.])(?:steps|loops)\\.${old}(?!\\w)`);
  let formulas = 0;
  const rename = (p: unknown) => (typeof p === "string" && path.test(p) ? p.replace(path, `$1${key}`) : p);
  const walk = (v: unknown): unknown => {
    if (Array.isArray(v)) {
      const out = (v as unknown[]).map(walk);
      return out.every((x, i) => x === (v as unknown[])[i]) ? v : out;
    }
    if (!isObject(v)) return v;
    const kind = kindOf(v);
    const body = bodyOf(v);
    if (kind === "ref") {
      const next = rename(body.path);
      return next === body.path ? v : { [ENVELOPE]: { ...body, path: next } };
    }
    if (kind === "template" && Array.isArray(body.parts)) {
      const before = body.parts as unknown[];
      const parts = before.map((p) => {
        if (!isObject(p)) return p;
        const ref = rename(p.ref);
        return ref === p.ref ? p : { ...p, ref };
      });
      return parts.every((p, i) => p === before[i]) ? v : { [ENVELOPE]: { ...body, parts } };
    }
    if (kind === "cel") {
      if (typeof body.expr === "string" && named.test(body.expr)) formulas++;
      return v;
    }
    if (kind !== null) return v; // a literal's value, or an envelope the engine can't read: kept as written
    const entries = Object.entries(v).map(([k, x]) => [k, walk(x)] as const);
    return entries.every(([k, x]) => x === v[k]) ? v : Object.fromEntries(entries);
  };
  const nodes = nodesOf(doc).map((n) => {
    const config = n.config === undefined ? undefined : (walk(n.config) as Record<string, unknown>);
    const renamed = sameId(n.id, nodeId) ? { ...n, key } : n;
    return config === n.config ? renamed : { ...renamed, config };
  });
  const outputs = doc.settings?.outputs === undefined ? undefined : (walk(doc.settings.outputs) as Record<string, unknown>);
  const settings = doc.settings && outputs !== doc.settings.outputs ? { ...doc.settings, outputs } : doc.settings;
  return { doc: { ...doc, nodes, ...(settings ? { settings } : {}) }, formulas };
}
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/config.test.ts`
Expected: PASS, 16 tests.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/config.ts frontend/src/lib/config.test.ts
git commit -m "feat(editor): change a step's config, options and key as documents, its edges and references following (4c-1)"
```

### Task 3: One undo step per field

**Files:**
- Modify: `frontend/src/lib/history.ts`
- Test: `frontend/src/lib/history.test.ts`

**Interfaces:**
- Produces: `interface History<T> { past: T[]; present: T; future: T[]; mark?: string }`, and `record<T>(h:
  History<T>, next: T, mark?: string): History<T>`. Undo and redo drop the mark.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/history.test.ts`:

```ts
it("makes one step of a field's edits while it keeps its mark", () => {
  let h = record(begin("a"), "ab", "f#1");
  h = record(h, "abc", "f#1");
  expect([h.past, h.present]).toEqual([["a"], "abc"]);
  expect(undo(h).present).toBe("a");
});

it("starts a new step for another mark, an unmarked change, or after an undo", () => {
  let h = record(record(begin(0), 1, "x#1"), 2, "y#1");
  expect(h.past).toEqual([0, 1]);
  h = record(record(h, 3), 4);
  expect(h.past).toEqual([0, 1, 2, 3]);
  h = record(undo(record(h, 5, "z#1")), 6, "z#1");
  expect([h.past, h.present]).toEqual([[0, 1, 2, 3, 4], 6]);
});
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/history.test.ts`
Expected: FAIL. `makes one step…` sees `past` `["a", "ab"]`: `record` ignores the mark.

- [ ] **Step 3: Coalesce by mark**

In `frontend/src/lib/history.ts`, replace the interface and `record`:

```ts
export interface History<T> {
  past: T[];
  present: T;
  future: T[];
  mark?: string; // what made the present: a field's focus session, whose next edit replaces it (4c-1 ruling 8)
}
```

```ts
/** `next` as the present. An edit with the mark that made the present replaces it: one field's typing while it keeps
 * focus is one step (4c-1 ruling 8). Any other edit is a step of its own. */
export function record<T>(h: History<T>, next: T, mark?: string): History<T> {
  if (next === h.present) return h;
  if (mark !== undefined && h.mark === mark) return { past: h.past, present: next, future: [], mark };
  return { past: [...h.past, h.present].slice(-LIMIT), present: next, future: [], mark };
}
```

`undo` and `redo` build new objects without `mark`, so typing after an undo starts a new step: they stay as they are.

- [ ] **Step 4: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/history.test.ts`
Expected: PASS, 4 tests.

- [ ] **Step 5: Run the editor's tests**

`Editor.tsx` calls `record(h, next)`; the mark is optional, so nothing else changes.
Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/history.ts frontend/src/lib/history.test.ts
git commit -m "feat(editor): coalesce one field's typing into one undo step (4c-1)"
```

# Milestone 2: Tabs, one field, the drawer, lists and maps

### Task 4: Radix Tabs

**Files:**
- Modify: `frontend/package.json`, `frontend/pnpm-lock.yaml`
- Create: `frontend/src/components/Tabs.tsx`
- Test: `frontend/src/components/Tabs.test.tsx`
- Modify: `frontend/e2e/gate.spec.ts` (the notices test)

**Interfaces:**
- Produces: `Tabs<T extends string>({ label, value, onChange, tabs }: { label: string; value: T; onChange: (value: T)
  => void; tabs: { value: T; label: string; content: ReactNode }[] })`.

- [ ] **Step 1: Add the dependency, pinned**

From `frontend/`: `npx -y pnpm@12.6.0 add --save-exact @radix-ui/react-tabs@1.1.21`
Expected: `package.json` gains `"@radix-ui/react-tabs": "1.1.21"` under `dependencies`; the lock file changes.

- [ ] **Step 2: Read its API in the installed package**

Run: `grep -n "Root\|List\|Trigger\|Content\|onValueChange\|activationMode\|forceMount" node_modules/@radix-ui/react-tabs/dist/index.d.ts`
Expected:
- `Root`, `List`, `Trigger` and `Content` are exported;
- `Root` takes `value` and `onValueChange(value: string)`;
- `Trigger` and `Content` take `value`.

If they differ, adapt Step 5's code to the package and record a mid-slice ruling.

- [ ] **Step 3: Check the licences**

Run:
- `node scripts/licence-check.mjs --self-test`
- `npx -y pnpm@12.6.0 licenses list --json --prod | node scripts/licence-check.mjs prod`
- `npx -y pnpm@12.6.0 licenses list --json | node scripts/licence-check.mjs all`

Expected: all three pass with no new exception (Radix and its dependencies are MIT). A failure stops the work: the
owner rules (D22).

- [ ] **Step 4: Write the failing tests**

Create `frontend/src/components/Tabs.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it } from "vitest";
import { Tabs } from "./Tabs";

function Two() {
  const [tab, setTab] = useState<"setup" | "options">("setup");
  return (
    <Tabs
      label="Settings"
      value={tab}
      onChange={setTab}
      tabs={[
        { value: "setup", label: "Setup", content: <p>required</p> },
        { value: "options", label: "Options · 1 problem", content: <p>the rest</p> },
      ]}
    />
  );
}

it("moves between tabs with the arrow keys, each panel named by its tab", async () => {
  render(<Two />);
  expect(screen.getByRole("tablist", { name: "Settings" })).toBeTruthy();
  screen.getByRole("tab", { name: "Setup" }).focus();
  await userEvent.keyboard("{ArrowRight}");
  const options = screen.getByRole("tab", { name: "Options · 1 problem" });
  expect(document.activeElement).toBe(options);
  expect(options.getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("tabpanel", { name: "Options · 1 problem" }).textContent).toBe("the rest");
  expect(screen.queryByText("required")).toBeNull(); // one panel at a time
});

it("says the chosen tab by its weight and its rule, never by colour alone", () => {
  render(<Two />);
  const chosen = screen.getByRole("tab", { name: "Setup" });
  expect(chosen.className).toContain("data-[state=active]:font-semibold");
  expect(chosen.className).toContain("data-[state=active]:border-accent");
});
```

- [ ] **Step 5: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/components/Tabs.test.tsx`
Expected: FAIL. The module `./Tabs` doesn't exist.

- [ ] **Step 6: Write the component**

Create `frontend/src/components/Tabs.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import * as TabsPrimitive from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

/** Tabs (Radix: a tablist the arrow keys move along, each panel named by its tab; outline §4, D23). The chosen tab says
 * so by its weight and a 2 px rule in the accent, its one coloured line (outline §6), never by colour alone. */
export function Tabs<T extends string>({ label, value, onChange, tabs }: {
  label: string;
  value: T;
  onChange: (value: T) => void;
  tabs: { value: T; label: string; content: ReactNode }[];
}) {  // prettier-ignore
  return (
    <TabsPrimitive.Root value={value} onValueChange={(v) => onChange(v as T)} className="flex min-w-0 flex-col gap-4">
      <TabsPrimitive.List aria-label={label} className="flex gap-1 border-b border-line">
        {tabs.map((t) => (
          <TabsPrimitive.Trigger
            key={t.value}
            value={t.value}
            className="-mb-px min-h-11 border-b-2 border-transparent px-3 text-body text-muted hover:text-ink data-[state=active]:border-accent data-[state=active]:font-semibold data-[state=active]:text-ink"
          >
            {t.label}
          </TabsPrimitive.Trigger>
        ))}
      </TabsPrimitive.List>
      {tabs.map((t) => (
        <TabsPrimitive.Content key={t.value} value={t.value} className="flex min-w-0 flex-col gap-5">
          {t.content}
        </TabsPrimitive.Content>
      ))}
    </TabsPrimitive.Root>
  );
}
```

- [ ] **Step 7: Run them to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/components/Tabs.test.tsx`
Expected: PASS, 2 tests.

- [ ] **Step 8: Name the package in the notices check**

In `frontend/e2e/gate.spec.ts`, in the test "the served app carries its third-party notices…", after the line that
pushes the canvas's packages, add:

```ts
  // The step drawer's tabs (4c-1): bundled in the editor's chunk, and in the notices.
  entries.push(/^@radix-ui\/react-tabs \d/m);
```

Then build and read the notices the build writes:
- `npx -y pnpm@12.6.0 build`
- `grep -n "^@radix-ui/react-tabs" dist/third-party-notices.txt`

Expected: the build succeeds, and the grep prints `@radix-ui/react-tabs 1.1.21`. The browser runs this check at the
end of Task 6.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/components/Tabs.tsx frontend/src/components/Tabs.test.tsx frontend/e2e/gate.spec.ts
git commit -m "feat(ui): token-styled Radix Tabs 1.1.21, pinned, in the notices (4c-1)"
```

### Task 5: One field

**Files:**
- Modify: `frontend/src/components/Field.tsx` (export `controlClass`)
- Create: `frontend/src/routes/editor/drawer/context.ts`
- Create: `frontend/src/routes/editor/drawer/FieldFrame.tsx`
- Create: `frontend/src/routes/editor/drawer/scalars.tsx`
- Create: `frontend/src/routes/editor/drawer/Formula.tsx`
- Create: `frontend/src/routes/editor/drawer/structured.tsx`
- Create: `frontend/src/routes/editor/drawer/FieldView.tsx`
- Create: `frontend/src/routes/editor/drawer/harness.tsx` (tests only)
- Test: `frontend/src/routes/editor/drawer/FieldView.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 1: `FieldSpec`, `Path`, `Widget`, `canFixed`, `canFormula`, `emptyOf`, `startsAsFormula`,
    `propertiesOf`, `pointerOf`;
  - from Task 2: `valueAt`, `setAt`, `kindOf`, `fixedOf`, `formula`, `formulaOf`, `isPlainRef`, `referenceText`,
    `MAX_FORMULA`.
- Produces:
  - `controlClass(invalid: boolean): string` (`components/Field.tsx`).
  - From `context.ts`:
    - `interface Drawer { node: GraphNode; type: NodeType; editable: boolean; tenantId: string; workflowId:
      string; problems: Diagnostic[]; expressions: Expression[]; set: (path: Path, value: unknown, mark?: string) =>
      void }`;
    - `DrawerContext`, `useDrawer(): Drawer`;
    - `segment(name): string`, `problemsAt(all: Diagnostic[], pointer: string, shown: ReadonlySet<string> | null):
      Diagnostic[]`;
    - `useSession(prefix: string): { mark: () => string; onFocus: (e) => void }`.
  - From `FieldFrame.tsx`: `interface Described { id; describedBy; invalid }`, `FieldFrame`, `GroupFrame`.
  - From `scalars.tsx`: `interface ControlProps extends Described { spec; value; disabled; onChange: (value: unknown,
    typed: boolean) => void; onLocal: (problem: string | null) => void }`, `useText`, `TextControl`,
    `NumberControl`, `BooleanControl`, `EnumControl`, `JsonControl`, `JSON_NOTE`.
  - From `Formula.tsx`: `type Mode = "fixed" | "formula"`, `FormulaControl`, `ModeSwitch`, `ReferenceView`,
    `SensitiveView`, `runsText(x: Expression | undefined): string | null`.
  - From `structured.tsx`: `isContainer(widget): boolean`, `partNames(spec): string[]`, `ContainerParts({ spec })`.
  - From `FieldView.tsx`: `FieldView({ spec }: { spec: FieldSpec })`.
  - From `harness.tsx` (tests only): `NODE_ID`, `type Edit`, `showFields(type, options?) → { edits, config() }`,
    `problem(field, message): Diagnostic`.

- [ ] **Step 1: Export the control's classes**

In `frontend/src/components/Field.tsx`, after `const CONTROL = …`, add:

```ts
/** A control's classes: its boundary 3:1 against its surface (line-control), red when its value is refused. */
export const controlClass = (invalid: boolean): string => `${CONTROL} ${invalid ? "border-danger" : "border-line-control"}`;
```

and in `Frame`, replace `` className: `${CONTROL} ${error ? "border-danger" : "border-line-control"}` `` with
`className: controlClass(!!error)`.

- [ ] **Step 2: Write the harness the tests drive**

Create `frontend/src/routes/editor/drawer/harness.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A step's fields on their own, for tests (4c-1): each edit changes the step's config as the editor would, and is kept
// with its mark. Imported by tests only: the build never reaches it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { useState } from "react";
import { setAt } from "../../../lib/config";
import { fieldsOf, type Path } from "../../../lib/schemaForm";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";
import { DrawerContext } from "./context";
import { FieldView } from "./FieldView";

export const NODE_ID = "00000000-0000-4000-8000-000000000001";
export type Edit = { path: Path; value: unknown; mark: string | undefined };

interface Options {
  config?: Record<string, unknown>;
  problems?: Diagnostic[];
  expressions?: Expression[];
  editable?: boolean;
}

function Fields({ type, options, edits, state }: {
  type: NodeType; options: Options; edits: Edit[]; state: { config: Record<string, unknown> };
}) {  // prettier-ignore
  const [node, setNode] = useState<GraphNode>({ id: NODE_ID, key: "step", type: type.ref, config: state.config });
  const set = (path: Path, value: unknown, mark?: string) => {
    edits.push({ path, value, mark });
    state.config = setAt(state.config, path, value) as Record<string, unknown>;
    setNode((n) => ({ ...n, config: state.config }));
  };
  const drawer = {
    node, type, editable: options.editable ?? true, tenantId: "t1", workflowId: "w1",
    problems: options.problems ?? [], expressions: options.expressions ?? [], set,
  };  // prettier-ignore
  return (
    <DrawerContext.Provider value={drawer}>
      {fieldsOf(type).map((f) => <FieldView key={f.pointer} spec={f} />)}
    </DrawerContext.Provider>
  );
}

/** The type's fields, shown; `config()` is the step's config after the edits so far. */
export function showFields(type: NodeType, options: Options = {}) {
  const edits: Edit[] = [];
  const state = { config: options.config ?? {} };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Fields type={type} options={options} edits={edits} state={state} />
    </QueryClientProvider>,
  );
  return { edits, config: () => state.config };
}

/** A problem the server found at a field of the step. */
export const problem = (field: string, message: string): Diagnostic => ({
  code: "config.invalid", severity: "error", message, fix: null, node: NODE_ID, field,
});  // prettier-ignore
```

- [ ] **Step 3: Write the failing tests**

Create `frontend/src/routes/editor/drawer/FieldView.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { formula } from "../../../lib/config";
import { FILTER, IF, REMOTE, typeWith } from "../../../test/nodeTypes";
import { NODE_ID, problem, showFields } from "./harness";

/** A step of every plain shape: a required text, numbers, a choice, a yes or no, JSON and a group. */
const PLAIN = typeWith({
  type: "object", required: ["name"],
  properties: {
    name: { type: "string", title: "Name", description: "Shown to people." },
    count: { type: "integer", title: "Count", default: 3 },
    ratio: { type: "number", title: "Ratio" },
    mode: { type: "string", enum: ["fast", "safe"], title: "Mode" },
    on: { type: "boolean", title: "On" },
    extra: { type: "array", items: {}, title: "Extra" },
    query: { type: "object", title: "Query", properties: { limit: { type: "integer", title: "Limit" } } },
  },
});  // prettier-ignore

it("labels a field by its title, its hint and the server's problems described by it", () => {
  showFields(PLAIN, { problems: [problem("/name", "Too short.")] });
  const name = screen.getByLabelText("Name");
  const described = name.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent);
  expect(described).toEqual(["Shown to people.", "Too short."]);
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(name.getAttribute("aria-required")).toBe("true");
});

it("writes a number as typed, and says when the text isn't one", async () => {
  const { config } = showFields(PLAIN);
  await userEvent.type(screen.getByLabelText("Count"), "12");
  expect(config()).toEqual({ count: 12 });
  await userEvent.type(screen.getByLabelText("Count"), ".5");
  expect(screen.getByText("A whole number, like 42.")).toBeTruthy();
  expect(config()).toEqual({ count: 12 });
  await userEvent.type(screen.getByLabelText("Ratio"), "2.");
  expect(screen.getByLabelText<HTMLInputElement>("Ratio").value).toBe("2."); // as typed, while it means 2
  expect(config()).toEqual({ count: 12, ratio: 2 });
});

it("removes an emptied field, so its default applies, and says a required one is needed", async () => {
  const { config } = showFields(PLAIN, { config: { name: "a", count: 5 } });
  await userEvent.clear(screen.getByLabelText("Count"));
  await userEvent.clear(screen.getByLabelText("Name"));
  expect(config()).toEqual({});
  expect(screen.getByText("Required")).toBeTruthy();
});

it("makes one mark of a field's typing while it keeps focus", async () => {
  const { edits } = showFields(PLAIN);
  await userEvent.type(screen.getByLabelText("Name"), "ab");
  await userEvent.tab();
  await userEvent.type(screen.getByLabelText("Name"), "c");
  const marks = edits.map((e) => e.mark);
  expect(marks).toHaveLength(3);
  expect(marks[1]).toBe(marks[0]);
  expect(marks[2]).not.toBe(marks[1]);
  expect(marks[0]).toMatch(new RegExp(`^${NODE_ID}/name#\\d+$`));
});

it("makes each choice of a select or a checkbox an undo step of its own", async () => {
  const { config, edits } = showFields(PLAIN);
  await userEvent.selectOptions(screen.getByLabelText("Mode"), "fast");
  await userEvent.click(screen.getByLabelText("On"));
  expect(config()).toEqual({ mode: "fast", on: true });
  expect(edits.map((e) => e.mark)).toEqual([undefined, undefined]);
  await userEvent.selectOptions(screen.getByLabelText("Mode"), "Not set");
  expect(config()).toEqual({ on: true });
});

it("shows a group's parts, and a problem in a part it doesn't show at the group", () => {
  showFields(PLAIN, { config: { query: { limit: 5, other: 1 } }, problems: [problem("/query/other", "Not one of its fields.")] });
  const group = screen.getByRole("group", { name: "Query" });
  expect(within(group).getByLabelText<HTMLInputElement>("Limit").value).toBe("5");
  expect(within(group).getByText("Not one of its fields.")).toBeTruthy();
});

it("edits a group as JSON, the engine's reading, saved when focus leaves", async () => {
  const { config, edits } = showFields(PLAIN, { config: { query: { limit: 5 } } });
  await userEvent.click(screen.getByRole("button", { name: "Edit as JSON" }));
  const json = screen.getByLabelText<HTMLTextAreaElement>("Query");
  expect(JSON.parse(json.value)).toEqual({ limit: 5 });
  await userEvent.clear(json);
  await userEvent.paste('{"limit": {"$value": {"kind": "ref", "path": "trigger.n"}}}');
  expect(edits).toEqual([]); // nothing while typing
  await userEvent.tab();
  expect(config()).toEqual({ query: { limit: { $value: { kind: "ref", path: "trigger.n" } } } }); // never wrapped
  await userEvent.click(json);
  await userEvent.paste("}");
  await userEvent.tab();
  expect(screen.getByText("This isn't valid JSON, so it isn't saved.")).toBeTruthy();
  expect(edits).toHaveLength(1);
});

it("keeps a formula, says how it runs, and turns a fixed value into the formula that gives it", async () => {
  const { config } = showFields(IF, {
    config: { condition: formula("trigger.n > 1") },
    expressions: [{ node: NODE_ID, field: "/condition", mode: "activity", reason: "it reads a large value" }],
  });
  expect(screen.getByLabelText<HTMLTextAreaElement>("Condition").value).toBe("trigger.n > 1");
  expect(screen.getByText("Runs as a separate step: it reads a large value")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Fixed" }));
  expect(config()).toEqual({});
  await userEvent.click(screen.getByLabelText("Condition")); // a checkbox now
  await userEvent.click(screen.getByRole("button", { name: "Formula" }));
  expect(config()).toEqual({ condition: formula("true") });
});

it("offers no fixed value where the engine takes only a formula", () => {
  showFields(FILTER);
  expect(screen.queryByRole("group", { name: "How Predicate is set" })).toBeNull();
  expect(screen.getByLabelText("Predicate").tagName).toBe("TEXTAREA");
});

it("shows a reference read only, and keeps it until it's replaced", async () => {
  const ref = { $value: { kind: "ref", path: "steps.fetch.output.name" } };
  const { config, edits } = showFields(PLAIN, { config: { name: ref } });
  expect(screen.getByLabelText("Name").textContent).toBe("steps.fetch.output.name");
  expect(edits).toEqual([]);
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
  expect(config()).toEqual({ name: formula("steps.fetch.output.name") });
});

it("never shows a sensitive field's fixed value", async () => {
  const { config } = showFields(REMOTE, { config: { token: "s3cr3t-value" } });
  const shown = () => [...document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea")].map((f) => f.value);
  expect(document.body.textContent).not.toContain("s3cr3t");
  expect(shown().some((v) => v.includes("s3cr3t"))).toBe(false);
  expect(screen.getByLabelText("Token").textContent).toBe("A fixed value is written here, which a sensitive field can't keep.");
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
  expect(config()).toEqual({});
  expect(screen.getByLabelText("Token").tagName).toBe("TEXTAREA");
});

it("never offers a value with a sensitive part as JSON", () => {
  const holder = typeWith({
    type: "object",
    properties: { auth: { type: "object", title: "Auth", properties: { key: { type: "string", title: "Key", "x-sensitive": true } } } },
  });  // prettier-ignore
  showFields(holder, { config: { auth: {} } });
  expect(screen.getByRole("group", { name: "Auth" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Edit as JSON" })).toBeNull();
});

it("disables every control for a person who can't edit", () => {
  showFields(PLAIN, { config: { name: "a", count: 2 }, editable: false });
  expect(screen.getByLabelText<HTMLInputElement>("Name").disabled).toBe(true);
  expect(screen.getByLabelText<HTMLSelectElement>("Mode").disabled).toBe(true);
  expect(screen.queryByRole("button", { name: /^Clear/ })).toBeNull();
});
```

- [ ] **Step 4: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/drawer/FieldView.test.tsx`
Expected: FAIL. The harness can't import `./context` and `./FieldView`.

- [ ] **Step 5: Write what a drawer's fields share**

Create `frontend/src/routes/editor/drawer/context.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// What a step drawer's fields share (4c-1): the step, its type, whether it may be edited, the server's problems and
// formulas for it, and how a value is written; which problems a field shows (D19); and focus sessions (ruling 8).
import { createContext, useContext, useRef, type FocusEvent } from "react";
import { pointerOf, type Path } from "../../../lib/schemaForm";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";

export interface Drawer {
  node: GraphNode;
  type: NodeType;
  editable: boolean;
  tenantId: string;
  workflowId: string;
  problems: Diagnostic[]; // the step's, from a current check
  expressions: Expression[]; // how its formulas run
  /** Write `value` at `path` in the step's config (undefined removes it); edits sharing a mark are one undo step. */
  set: (path: Path, value: unknown, mark?: string) => void;
}

export const DrawerContext = createContext<Drawer | null>(null);

export function useDrawer(): Drawer {
  const drawer = useContext(DrawerContext);
  if (!drawer) throw new Error("A step's field is shown only in its drawer");
  return drawer;
}

/** A name as one segment of a JSON pointer. */
export const segment = (name: string): string => pointerOf([name]).slice(1);

/** The problems a field shows: those at its pointer; those below it, when it shows nothing below (a scalar, a formula,
 * JSON: `shown` is null); or, for a group, a list or a map showing its parts, those below it in a part it doesn't
 * show. */
export function problemsAt(all: Diagnostic[], pointer: string, shown: ReadonlySet<string> | null): Diagnostic[] {
  return all.filter((d) => {
    if (d.field === null) return false;
    if (d.field === pointer) return true;
    if (!d.field.startsWith(`${pointer}/`)) return false;
    return shown === null || !shown.has(d.field.slice(pointer.length + 1).split("/")[0]!);
  });
}

let sessions = 0;

/** Focus entering an element starts a session: what's typed in it until focus leaves is one undo step (ruling 8). */
export function useSession(prefix: string): { mark: () => string; onFocus: (e: FocusEvent<HTMLElement>) => void } {
  const session = useRef(0);
  return {
    mark: () => `${prefix}#${session.current}`,
    onFocus: (e) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) session.current = ++sessions;
    },
  };
}
```

- [ ] **Step 6: Write the frames**

Create `frontend/src/routes/editor/drawer/FieldFrame.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A field's frame (4c-1): its label and the actions on it, then its control (given its id and the ids that describe
// it), its hint, a type hint from the browser (D19) and the server's problems at it, each described by the control
// (WCAG 1.3.1, 3.3.1). "(required)" sits beside the label, outside it: the control says it (aria-required). A group, a
// list or a map is a fieldset its legend names, its parts indented, never marked with a left rule (outline §6).
import { useId, type ReactNode } from "react";
import type { Diagnostic } from "../../../lib/workflows";

export interface Described {
  id: string;
  describedBy: string | undefined;
  invalid: boolean;
}

interface Frame {
  label: string;
  required: boolean; // said below the top level: Setup says it once for its own fields
  hint: string | null;
  local: string | null; // what the browser found: the control's text isn't saved
  problems: Diagnostic[];
  actions?: ReactNode;
}

const describing = (id: string, { hint, local, problems }: Pick<Frame, "hint" | "local" | "problems">) =>
  [hint !== null ? `${id}-hint` : null, local !== null ? `${id}-local` : null, ...problems.map((_, i) => `${id}-p${i}`)]
    .filter((x): x is string => x !== null)
    .join(" ") || undefined;

function Notes({ id, hint, local, problems }: { id: string } & Pick<Frame, "hint" | "local" | "problems">) {
  return (
    <>
      {hint !== null && <p id={`${id}-hint`} className="text-small text-muted">{hint}</p>}
      {local !== null && <p id={`${id}-local`} className="text-small text-danger">{local}</p>}
      {problems.map((d, i) => (
        <p key={`${d.code}:${i}`} id={`${id}-p${i}`} className={`text-small ${d.severity === "error" ? "text-danger" : "text-warn-ink"}`}>
          {d.message}
          {d.fix && <span className="block text-muted">{d.fix}</span>}
        </p>
      ))}
    </>
  );
}

const Required = () => <span className="text-small text-muted">(required)</span>;

export function FieldFrame({ label, required, hint, local, problems, actions, below, children }: Frame & {
  below?: ReactNode;
  children: (control: Described) => ReactNode;
}) {  // prettier-ignore
  const id = useId();
  const invalid = local !== null || problems.some((d) => d.severity === "error");
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-baseline gap-1">
          <label htmlFor={id} className="text-small font-semibold">{label}</label>
          {required && <Required />}
        </span>
        {actions}
      </div>
      {children({ id, describedBy: describing(id, { hint, local, problems }), invalid })}
      <Notes id={id} hint={hint} local={local} problems={problems} />
      {below}
    </div>
  );
}

export function GroupFrame({ label, required, hint, local, problems, actions, children }: Frame & { children: ReactNode }) {
  const id = useId();
  return (
    <fieldset aria-describedby={describing(id, { hint, local, problems })} className="flex min-w-0 flex-col gap-3">
      <legend className="text-small font-semibold">{label}</legend>
      {required && <Required />}
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      <Notes id={id} hint={hint} local={local} problems={problems} />
      <div className="flex min-w-0 flex-col gap-4 pl-3">{children}</div>
    </fieldset>
  );
}
```

- [ ] **Step 7: Write the controls for fixed values**

Create `frontend/src/routes/editor/drawer/scalars.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The controls for a fixed value (4c-1, ruling 5): text, a number, a yes or no, one of a list, and JSON as the engine
// reads it (ruling 15). Each reports a new value, `undefined` when emptied. One whose text doesn't parse says why and
// reports nothing, so nothing unsaved looks saved (D19).
import { useState } from "react";
import { controlClass } from "../../../components/Field";
import type { FieldSpec } from "../../../lib/schemaForm";
import type { Described } from "./FieldFrame";

export interface ControlProps extends Described {
  spec: FieldSpec;
  value: unknown; // a `literal` envelope's own value, or the value as written
  disabled: boolean;
  onChange: (value: unknown, typed: boolean) => void; // `typed`: part of the field's typing (ruling 8)
  onLocal: (problem: string | null) => void;
}

export const JSON_NOTE = 'As the engine reads it: an object with a "$value" key is computed.';

/** A control's own text, kept while it still means the value it shows ("2." while 2.5 is typed), and replaced when
 * the value changes elsewhere (an undo, a replace). */
export function useText(value: unknown, show: (v: unknown) => string, means: (text: string, v: unknown) => boolean) {
  const [text, setText] = useState(() => show(value));
  const [seen, setSeen] = useState(value);
  if (!Object.is(seen, value)) {
    setSeen(value);
    if (!means(text, value)) setText(show(value));
  }
  return [text, setText] as const;
}

const asText = (v: unknown): string => (typeof v === "string" ? v : v === undefined || v === null ? "" : JSON.stringify(v));

export function TextControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  return (
    <input
      id={id} type="text" value={asText(value)} disabled={disabled} spellCheck={false}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, true)}
      className={controlClass(invalid)}
    />
  );  // prettier-ignore
}

function parseNumber(text: string, whole: boolean): { value: number | undefined } | { problem: string } {
  const t = text.trim();
  if (t === "") return { value: undefined };
  const n = Number(t);
  if (!Number.isFinite(n) || (whole && !Number.isInteger(n))) {
    return { problem: whole ? "A whole number, like 42." : "A number, like 42 or 2.5." };
  }
  return { value: n };
}

export function NumberControl({ spec, value, id, describedBy, invalid, disabled, onChange, onLocal }: ControlProps) {
  const whole = spec.base === "integer";
  const [text, setText] = useText(value, asText, (t, v) => {
    const parsed = parseNumber(t, whole);
    return "value" in parsed && (parsed.value === undefined ? v === undefined || v === null : parsed.value === v);
  });
  return (
    <input
      id={id} type="text" value={text} disabled={disabled} spellCheck={false}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
      onChange={(e) => {
        setText(e.target.value);
        const parsed = parseNumber(e.target.value, whole);
        onLocal("problem" in parsed ? parsed.problem : null);
        if ("value" in parsed) onChange(parsed.value, true);
      }}
      className={controlClass(invalid)}
    />
  );  // prettier-ignore
}

export function BooleanControl({ value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  return (
    // 20 px, alone on its row: its 24 px target spacing holds (WCAG 2.5.8).
    <input
      id={id} type="checkbox" checked={value === true} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid}
      onChange={(e) => onChange(e.target.checked, false)}
      className="size-[20px] self-start accent-accent"
    />
  );  // prettier-ignore
}

export function EnumControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const choices = (spec.schema.enum as unknown[]).filter((v): v is string => typeof v === "string");
  const current = typeof value === "string" ? value : "";
  return (
    <select
      id={id} value={current} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, false)}
      className={controlClass(invalid)}
    >
      <option value="">{spec.required ? "Choose…" : "Not set"}</option>
      {current !== "" && !choices.includes(current) && <option value={current}>{current} (not one of its choices)</option>}
      {choices.map((c) => (
        <option key={c} value={c}>{c}</option>
      ))}
    </select>
  );  // prettier-ignore
}

function parseJson(text: string): { value: unknown } | { problem: string } {
  if (text.trim() === "") return { value: undefined };
  try {
    return { value: JSON.parse(text) as unknown };
  } catch {
    return { problem: "This isn't valid JSON, so it isn't saved." };
  }
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** JSON as the engine reads it (ruling 15): a `{"$value": …}` in it is computed. It applies when focus leaves: a
 * half-typed edit never saves, and one that takes ports away asks once (ruling 9). */
export function JsonControl({ value, id, describedBy, invalid, disabled, onChange, onLocal }: ControlProps) {
  const show = (v: unknown) => (v === undefined ? "" : JSON.stringify(v, null, 2));
  const [text, setText] = useText(value, show, (t, v) => {
    const parsed = parseJson(t);
    return "value" in parsed && same(parsed.value, v);
  });
  return (
    <textarea
      id={id} value={text} disabled={disabled} spellCheck={false} autoCapitalize="off"
      rows={Math.min(12, Math.max(3, text.split("\n").length))}
      aria-describedby={describedBy} aria-invalid={invalid}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        const parsed = parseJson(text);
        onLocal("problem" in parsed ? parsed.problem : null);
        if ("value" in parsed && !same(parsed.value, value)) onChange(parsed.value, false);
      }}
      className={`${controlClass(invalid)} py-2 font-mono text-small`}
    />
  );  // prettier-ignore
}
```

- [ ] **Step 8: Write formulas, references and the hidden sensitive value**

Create `frontend/src/routes/editor/drawer/Formula.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A value computed when the step runs (4c-1, ruling 6; D19's formula mode): CEL in a monospace area, and how the
// server says it runs; the choice between a fixed value and a formula; a reference or text with references written
// elsewhere, shown as it is until it's replaced (pills come with 4c-2); and a sensitive field's fixed value, which is
// never shown (M25).
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { MAX_FORMULA, formula, formulaOf, kindOf, referenceText } from "../../../lib/config";
import type { Expression } from "../../../lib/workflows";
import type { Described } from "./FieldFrame";
import { useText, type ControlProps } from "./scalars";

export type Mode = "fixed" | "formula";

export function FormulaControl({ value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const [text, setText] = useText(value, formulaOf, (t, v) => (t.trim() === "" ? kindOf(v) !== "cel" : formulaOf(v) === t));
  return (
    <textarea
      id={id} value={text} rows={3} maxLength={MAX_FORMULA} spellCheck={false} autoCapitalize="off" disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid}
      onChange={(e) => {
        setText(e.target.value);
        onChange(e.target.value.trim() === "" ? undefined : formula(e.target.value), true);
      }}
      className={`${controlClass(invalid)} py-2 font-mono text-small`}
    />
  );  // prettier-ignore
}

/** How the server says a formula runs (engine-core §5.10), in 4b's words. */
export const runsText = (x: Expression | undefined): string | null =>
  !x ? null : x.mode === "local" ? "Runs inline" : `Runs as a separate step: ${x.reason ?? "no reason given"}`;

export function ModeSwitch({ label, mode, disabled, onChange }: {
  label: string; mode: Mode; disabled: boolean; onChange: (mode: Mode) => void;
}) {  // prettier-ignore
  return (
    // 1c's segmented look, never pills (outline §6): the chosen one pressed, by weight and fill.
    <div role="group" aria-label={`How ${label} is set`} className="inline-flex gap-px overflow-hidden rounded-lg border border-line-strong bg-line-strong">
      {(["fixed", "formula"] as const).map((m) => (
        <button
          key={m}
          type="button"
          aria-pressed={mode === m}
          disabled={disabled}
          onClick={() => {
            if (mode !== m) onChange(m);
          }}
          className={`min-h-8 px-3 text-small ${mode === m ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink enabled:hover:bg-surface-hover"}`}
        >
          {m === "fixed" ? "Fixed" : "Formula"}
        </button>
      ))}
    </div>
  );
}

export function ReferenceView({ value, id, describedBy, fixed, toFormula, disabled, onFixed, onFormula }: Described & {
  value: unknown; fixed: boolean; toFormula: boolean; disabled: boolean; onFixed: () => void; onFormula: () => void;
}) {  // prettier-ignore
  return (
    <div className="flex flex-col gap-2">
      <output id={id} aria-describedby={describedBy} className="block break-all rounded-lg border border-line px-3 py-2 font-mono text-small">
        {referenceText(value)}
      </output>
      <p className="text-small text-muted">
        {kindOf(value) === "ref" ? "A reference to another value." : "Text with references."} Replace it to change it here.
      </p>
      {!disabled && (fixed || toFormula) && (
        <div className="flex flex-wrap gap-2">
          {fixed && <Button size="sm" onClick={onFixed}>Replace with a fixed value</Button>}
          {toFormula && <Button size="sm" onClick={onFormula}>Replace with a formula</Button>}
        </div>
      )}
    </div>
  );
}

export function SensitiveView({ id, describedBy, toFormula, disabled, onClear, onFormula }: Described & {
  toFormula: boolean; disabled: boolean; onClear: () => void; onFormula: () => void;
}) {  // prettier-ignore
  return (
    <div className="flex flex-col gap-2">
      <output id={id} aria-describedby={describedBy} className="block text-small">
        A fixed value is written here, which a sensitive field can&apos;t keep.
      </output>
      {!disabled && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={onClear}>Clear it</Button>
          {toFormula && <Button size="sm" onClick={onFormula}>Replace with a formula</Button>}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 9: Write a group's parts**

Create `frontend/src/routes/editor/drawer/structured.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A value made of parts (4c-1, ruling 5): a group's properties, each a field of its own.
import { propertiesOf, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import { segment } from "./context";
import { FieldView } from "./FieldView";

/** The widgets shown as their parts rather than as one control. */
export const isContainer = (widget: Widget): boolean => widget === "group";

/** The pointer segments of the parts a container shows: a problem below it in any other part is its own. */
export const partNames = (spec: FieldSpec): string[] => propertiesOf(spec).map((p) => segment(p.name));

export function ContainerParts({ spec }: { spec: FieldSpec }) {
  return propertiesOf(spec).map((part) => <FieldView key={part.pointer} spec={part} />);
}
```

- [ ] **Step 10: Write the field**

Create `frontend/src/routes/editor/drawer/FieldView.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// One field of a step's settings (4c-1): its label; how its value is set, fixed or by a formula where the engine takes
// both (ruling 6); its control, chosen by its widget (ruling 5); and the server's problems at it, with how a formula
// runs (D19). Its typing while it keeps focus is one undo step (ruling 8).
import { useState, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { fixedOf, formula, isPlainRef, kindOf, referenceText, valueAt } from "../../../lib/config";
import { canFixed, canFormula, emptyOf, startsAsFormula, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import { problemsAt, useDrawer, useSession } from "./context";
import { FieldFrame, GroupFrame, type Described } from "./FieldFrame";
import { FormulaControl, ModeSwitch, ReferenceView, SensitiveView, runsText, type Mode } from "./Formula";
import {
  BooleanControl, EnumControl, JSON_NOTE, JsonControl, NumberControl, TextControl, type ControlProps,
} from "./scalars";  // prettier-ignore
import { ContainerParts, isContainer, partNames } from "./structured";

type Control = (props: ControlProps) => ReactNode;

/** The control for a fixed value of this widget, or null when the drawer has none: its type's is used then. */
function controlFor(widget: Widget): Control | null {
  switch (widget) {
    case "text":
    case "datetime":
      return TextControl;
    case "number":
    case "integer":
      return NumberControl;
    case "boolean":
      return BooleanControl;
    case "enum":
      return EnumControl;
    case "json":
      return JsonControl;
    default:
      return null;
  }
}

const startMode = (spec: FieldSpec, value: unknown): Mode =>
  kindOf(value) === "cel" ? "formula"
  : value !== undefined && value !== null ? "fixed"
  : startsAsFormula(spec) ? "formula" : "fixed";  // prettier-ignore

export function FieldView({ spec }: { spec: FieldSpec }) {
  const drawer = useDrawer();
  const value = valueAt(drawer.node.config ?? {}, spec.path);
  const kind = kindOf(value);
  const empty = value === undefined || value === null;
  const [chosen, setChosen] = useState<Mode>(() => startMode(spec, value));
  const [local, setLocal] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [asJson, setAsJson] = useState(false);
  const [seen, setSeen] = useState(value);
  if (!Object.is(seen, value)) {
    // Set elsewhere (an undo, a replace): a formula or a fixed value decides the mode; emptied, the field keeps its own.
    setSeen(value);
    setLocal(null);
    if (kind === "cel") setChosen("formula");
    else if (!empty) setChosen("fixed");
  }
  const { mark, onFocus } = useSession(`${drawer.node.id}${spec.pointer}`);
  const disabled = !drawer.editable;
  const fixedOk = canFixed(spec);
  const formulaOk = canFormula(spec);
  const mode: Mode = fixedOk && formulaOk ? chosen : fixedOk ? "fixed" : "formula"; // the engine decides (ruling 6)
  const set = (next: unknown, typed: boolean) => {
    setTouched(true);
    drawer.set(spec.path, next === undefined ? emptyOf(spec) : next, typed ? mark() : undefined);
  };
  const computed = kind === "ref" || kind === "template";
  const hidden = spec.sensitive && !empty && kind !== "cel"; // a fixed value in a sensitive field: never shown (M25)
  const fixed = fixedOf(value);
  // A literal envelope or one the engine can't read is shown as JSON: its parts aren't where a form writes them.
  const json = asJson || kind === "unknown" || (kind === "literal" && isContainer(spec.base));
  const container = mode === "fixed" && !computed && !hidden && !json && isContainer(spec.base);
  const problems = problemsAt(drawer.problems, spec.pointer, container ? new Set(partNames(spec)) : null);
  const required = spec.required && !spec.entry && spec.path.length > 1;
  const missing = spec.required && touched && (empty || value === "") ? "Required" : null;
  const switchTo = (next: Mode) => {
    setChosen(next);
    setLocal(null);
    // A fixed value becomes the formula that gives it; a formula leaves an empty fixed value.
    if (next === "formula" && !empty) set(formula(JSON.stringify(fixed)), false);
    if (next === "fixed" && kind === "cel") set(undefined, false);
  };
  const actions = (
    <>
      {fixedOk && formulaOk && !computed && !hidden && (
        <ModeSwitch label={spec.label} mode={mode} disabled={disabled} onChange={switchTo} />
      )}
      {mode === "fixed" && !computed && !hidden && isContainer(spec.base) && !spec.holdsSensitive && kind !== "unknown" && kind !== "literal" && (
        <Button size="sm" aria-pressed={asJson} onClick={() => setAsJson(!asJson)}>Edit as JSON</Button>
      )}
      {!disabled && !spec.required && !spec.entry && value !== undefined && (
        <Button size="sm" aria-label={`Clear ${spec.label}`} onClick={() => set(undefined, false)}>Clear</Button>
      )}
    </>
  );
  const frame = (control: (c: Described) => ReactNode, hint: string | null = spec.hint, below?: ReactNode) => (
    <FieldFrame label={spec.label} required={required} hint={hint} local={local ?? missing} problems={problems} actions={actions} below={below}>
      {control}
    </FieldFrame>
  );
  const Control: Control = json
    ? JsonControl
    : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
  let body: ReactNode;
  if (hidden) {
    body = frame((c) => (
      <SensitiveView
        {...c} toFormula={formulaOk} disabled={disabled}
        onClear={() => set(undefined, false)}
        onFormula={() => {
          setChosen("formula");
          set(undefined, false);
        }}
      />
    ));  // prettier-ignore
  } else if (computed) {
    body = frame((c) => (
      <ReferenceView
        {...c} value={value} fixed={fixedOk} toFormula={formulaOk} disabled={disabled}
        onFixed={() => {
          setChosen("fixed");
          set(undefined, false);
        }}
        onFormula={() => {
          setChosen("formula");
          set(isPlainRef(value) ? formula(referenceText(value)) : undefined, false);
        }}
      />
    ));  // prettier-ignore
  } else if (mode === "formula") {
    const runs = runsText(drawer.expressions.find((x) => x.field === spec.pointer));
    body = frame(
      (c) => <FormulaControl {...c} spec={spec} value={value} disabled={disabled} onChange={set} onLocal={setLocal} />,
      spec.hint,
      runs && <p className="text-small text-muted">{runs}</p>,
    );
  } else if (container) {
    body = (
      <GroupFrame label={spec.label} required={required} hint={spec.hint} local={local ?? missing} problems={problems} actions={actions}>
        <ContainerParts spec={spec} />
      </GroupFrame>
    );
  } else if (spec.holdsSensitive && Control === JsonControl) {
    body = frame((c) => (
      <output id={c.id} aria-describedby={c.describedBy} className="block text-small">
        It holds a sensitive part, so it isn&apos;t shown as JSON.
      </output>
    ));
  } else {
    const hint = Control === JsonControl ? [spec.hint, JSON_NOTE].filter(Boolean).join(" ") : spec.hint;
    body = frame((c) => <Control {...c} spec={spec} value={fixed} disabled={disabled} onChange={set} onLocal={setLocal} />, hint);
  }
  return (
    <div data-pointer={spec.pointer} onFocus={onFocus}>
      {body}
    </div>
  );
}
```

- [ ] **Step 11: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/drawer/FieldView.test.tsx`
Expected: PASS, 13 tests.

- [ ] **Step 12: Run every frontend test, then typecheck and lint**

The AI-tells guard (`src/test/aiTells.ts`) runs with the suite and scans the new files.
Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/components/Field.tsx frontend/src/routes/editor/drawer
git commit -m "feat(editor): a step's field, fixed or a formula, with its problems; references and sensitive values kept (4c-1)"
```

### Task 6: The drawer

**Files:**
- Create: `frontend/src/routes/editor/drawer/StepDrawer.tsx`
- Create: `frontend/src/routes/editor/drawer/ErrorHandling.tsx` (`chipText` only; Task 10 adds the section)
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Delete: `frontend/src/routes/editor/StepPanel.tsx`
- Test: `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 2: `setConfig`, `Changed`;
  - from Task 3: `record(h, next, mark)`;
  - from Task 4: `Tabs`;
  - from Task 5: `FieldView`, `DrawerContext`, `problemsAt`, `segment`.
- Produces:
  - `StepDrawer` props: `{ node; type: NodeType | undefined; tenantId; workflowId; ports: string[]; problems:
    Diagnostic[] | null; expressions: Expression[]; editable; adds; onAdd; onDelete; onConnectPort; onPlace; onNudge;
    onClose; onConfig: (path: Path, value: unknown, mark?: string) => void }`. Later tasks add props.
  - `type Nudge` (moved from `StepPanel.tsx`).
  - `chipText(node: GraphNode, type: NodeType | undefined): string`.
  - In `Editor.tsx`:
    - `change(next, message: string | null, then?, mark?)`;
    - `settle(next, dropped, mark?)`, which asks before an edit drops edges;
    - the `{ kind: "ports" }` question;
    - the heading's id `step-drawer-title`.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/routes/editor/Editor.test.tsx`, add to the imports:

```ts
import { DELAY, typeWith } from "../../test/nodeTypes";
```

and add these tests after "leaves focus in a step's panel when undo keeps its step":

```tsx
/** A draft of one step of `type`, with this config, and a transform after it. */
const oneStep = (type: string, config: Record<string, unknown>, key = "wait") => ({
  graph_format: 1,
  nodes: [
    { id: `id-${key}`, key, type, config, position: { x: 0, y: 140 } },
    { id: "id-transform", key: "transform", type: "flow.transform@1", position: { x: 0, y: 280 } },
  ],
  edges: [],
});  // prettier-ignore
const stepConfig = (key: string) => drawn.at(-1)!.doc.nodes!.find((n) => n.key === key)!.config;

it("makes a field's typing one undo step", async () => {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, DELAY]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: oneStep("flow.delay@1", {}) }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "wait" }));
  const drawer = screen.getByRole("complementary", { name: "wait" });
  expect(within(drawer).getByRole("tab", { name: "Setup" }).getAttribute("aria-selected")).toBe("true");
  await userEvent.type(within(drawer).getByLabelText("Duration S"), "120");
  expect(stepConfig("wait")).toEqual({ duration_s: 120 });
  await userEvent.click(within(drawer).getByRole("heading", { name: "wait" })); // focus leaves the field
  await userEvent.keyboard("{Control>}z{/Control}");
  expect(stepConfig("wait")).toEqual({}); // the whole field's typing, in one step
});

it("keeps an unknown type's settings as they are", async () => {
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: oneStep("acme.thing@1", { secret: "s3cr3t" }, "x") }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "x" }));
  const drawer = screen.getByRole("complementary", { name: "x" });
  expect(drawer.textContent).toContain("This server doesn't know this step's type, so its settings can't be shown. They're kept as they are.");
  expect(drawer.textContent).not.toContain("s3cr3t");
  expect(stepConfig("x")).toEqual({ secret: "s3cr3t" });
});

it("shows a step's settings read only to a viewer", async () => {
  role = "viewer";
  answers.set("GET /api/v1/node-types", () => json([...TYPES, DELAY]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: oneStep("flow.delay@1", { duration_s: 5 }) }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "wait" }));
  expect(screen.getByLabelText<HTMLInputElement>("Duration S").disabled).toBe(true);
});

it("opens on Options when the type requires nothing", async () => {
  const note = typeWith({ type: "object", properties: { note: { type: "string", title: "Note" } } }, { ref: "acme.note@1", type: "acme.note", title: "Note" });
  answers.set("GET /api/v1/node-types", () => json([...TYPES, note]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: oneStep("acme.note@1", {}, "n") }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "n" }));
  expect(screen.getByRole("tab", { name: "Options" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getByLabelText("Note")).toBeTruthy();
});

/** A step whose `routes` declare its ports, as a switch's cases do, held as JSON: route b leads to the transform. */
const ROUTER = typeWith(
  { type: "object", properties: { routes: { title: "Routes" } } },
  { ref: "acme.router@1", type: "acme.router", title: "Router", ports: ["other"], dynamic_ports: "routes" },
);
const routed = () => {
  const draft = oneStep("acme.router@1", { routes: [{ port: "a" }, { port: "b" }] }, "route");
  return { ...draft, edges: [{ from: { node: "id-route", port: "b" }, to: { node: "id-transform" } }] };
};

async function dropRouteB() {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, ROUTER]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: routed() }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "route" }));
  const routes = screen.getByLabelText("Routes");
  await userEvent.clear(routes);
  await userEvent.paste('[{"port": "a"}]');
  await userEvent.tab(); // JSON applies when focus leaves
  return screen.getByRole("dialog", { name: "Remove a port" });
}

it("asks before an edit takes a port with edges away", async () => {
  const dialog = await dropRouteB();
  expect(dialog.textContent).toContain("The port b goes with this change, and its edge to transform is deleted.");
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(drawn.at(-1)!.doc.edges).toHaveLength(1);
  expect(stepConfig("route")).toEqual({ routes: [{ port: "a" }, { port: "b" }] });
});

it("undoes the edit and its edges together", async () => {
  const dialog = await dropRouteB();
  await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
  expect(drawn.at(-1)!.doc.edges).toEqual([]);
  expect(stepConfig("route")).toEqual({ routes: [{ port: "a" }] });
  await vi.waitFor(() => expect(document.activeElement?.id).toBe("step-drawer-title"));
  await userEvent.keyboard("{Control>}z{/Control}");
  expect(drawn.at(-1)!.doc.edges).toHaveLength(1);
  expect(stepConfig("route")).toEqual({ routes: [{ port: "a" }, { port: "b" }] });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/Editor.test.tsx`
Expected: FAIL. The 4b panel has no tabs and no fields: "Unable to find a label with the text of: Duration S", no tab
"Options", and no dialog "Remove a port". The 4b tests still pass.

- [ ] **Step 3: Write the chip's words**

Create `frontend/src/routes/editor/drawer/ErrorHandling.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// What a step's failure does, in words (4c-1, ruling 10; §10.3's chip), with the attempts and timeout the step sets
// when they differ from its type's.
import type { GraphNode, NodeType } from "../../../lib/workflows";

const CHIP = { fail: "fail the run", continue: "continue", port: "route to the error port" } as const;

export function chipText(node: GraphNode, type: NodeType | undefined): string {
  const own = node.options ?? {};
  const parts = [`On error: ${CHIP[own.on_error ?? "fail"]}`];
  if (own.max_attempts != null && own.max_attempts !== type?.retry.max_attempts) {
    parts.push(`${own.max_attempts} ${own.max_attempts === 1 ? "attempt" : "attempts"}`);
  }
  if (own.timeout_s != null && own.timeout_s !== type?.timeout_s) parts.push(`${own.timeout_s} s`);
  return parts.join(" · ");
}
```

- [ ] **Step 4: Write the drawer**

Create `frontend/src/routes/editor/drawer/StepDrawer.tsx`. `EFFECTS`, `Nudge`, `NUDGES` and the 4b actions move
here from `StepPanel.tsx` unchanged:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A step's drawer (4c-1, §10.3; it replaces 4b's panel, ruling 2). At the top: its key, its type, how it runs and what
// a failure does. Then the problems that belong to no field. Then its settings on two tabs, generated from its type's
// schema, the required ones on Setup and the rest on Options (ruling 3). Then how its formulas run, and, for an
// editor, 4b's actions: its "+" twins (WCAG 2.5.8), where it sits (2.5.7), its edges. Escape closes it and gives focus
// back to the step.
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Tabs } from "../../../components/Tabs";
import { fieldsOf, tabsOf, type FieldSpec, type Path } from "../../../lib/schemaForm";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";
import type { ItemAction } from "../items";
import { SIDE } from "../side";
import { DrawerContext, problemsAt, segment } from "./context";
import { chipText } from "./ErrorHandling";
import { FieldView } from "./FieldView";

const EFFECTS: Record<NodeType["side_effect"], string> = {
  none: "Changes nothing",
  idempotent: "Changes things; safe to repeat",
  keyed: "Changes things once per key",
  reconcilable: "Changes things; checked before a retry",
  ambiguous: "Changes things; a retry may repeat it",
};

export type Nudge = "ArrowLeft" | "ArrowUp" | "ArrowDown" | "ArrowRight";
const NUDGES: { key: Nudge; glyph: string; word: string }[] = [
  { key: "ArrowLeft", glyph: "←", word: "left" },
  { key: "ArrowUp", glyph: "↑", word: "up" },
  { key: "ArrowDown", glyph: "↓", word: "down" },
  { key: "ArrowRight", glyph: "→", word: "right" },
];

type Tab = "setup" | "options";

/** How many of the problems fall in these fields: a tab's count (ruling 3). */
const counted = (problems: Diagnostic[], fields: FieldSpec[]) =>
  problems.filter((d) => {
    const field = d.field;
    return field !== null && fields.some((f) => field === f.pointer || field.startsWith(`${f.pointer}/`));
  }).length;
const tabLabel = (label: string, n: number) => (n === 0 ? label : `${label} · ${n} ${n === 1 ? "problem" : "problems"}`);

export function StepDrawer({
  node, type, tenantId, workflowId, ports, problems, expressions, editable, adds,
  onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose, onConfig,
}: {
  node: GraphNode; type: NodeType | undefined; tenantId: string; workflowId: string; ports: string[];
  problems: Diagnostic[] | null; expressions: Expression[]; editable: boolean; adds: { label: string; action: ItemAction }[];
  onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void; onPlace: () => void;
  onNudge: (key: Nudge) => void; onClose: () => void; onConfig: (path: Path, value: unknown, mark?: string) => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [node.id]);
  const fields = useMemo(() => (type ? fieldsOf(type) : []), [type]);
  const { setup, options } = tabsOf(fields);
  const [tab, setTab] = useState<Tab>(setup.length > 0 ? "setup" : "options");
  const mine = problems ?? [];
  const top = new Set(fields.map((f) => segment(f.name)));
  // A problem no field shows: about the step as a whole, or a part its schema doesn't name (ruling 16).
  const general = mine.filter((d) => d.field === null || problemsAt([d], "", top).length > 0);
  return (
    <aside
      aria-labelledby="step-drawer-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className={`${SIDE} gap-5`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <h2 id="step-drawer-title" ref={heading} tabIndex={-1} className="truncate font-mono text-body-lg font-semibold">
            {node.key}
          </h2>
          <p className="text-small text-muted">{type ? `${type.title} · ${type.ref}` : `Unknown step type ${node.type}`}</p>
          {type && (
            <p className="text-small text-muted">
              {type.kind === "control" ? "Runs in the engine" : `Runs as its own step · ${EFFECTS[type.side_effect]}`}
            </p>
          )}
          <p className="text-small">{chipText(node, type)}</p>
        </div>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {problems === null ? (
        <p className="text-small text-muted">Not checked for what&apos;s on the screen.</p>
      ) : (
        general.length > 0 && (
          <section aria-labelledby="step-problems" className="flex flex-col gap-1.5">
            <h3 id="step-problems" tabIndex={-1} className="text-small font-semibold">Problems with this step</h3>
            <ul className="flex flex-col gap-1.5">
              {general.map((d, i) => (
                <li key={`${d.code}:${d.field}:${i}`} className="text-small">
                  <span className={d.severity === "error" ? "text-danger" : "text-warn-ink"}>{d.message}</span>
                  {d.fix && <span className="block text-muted">{d.fix}</span>}
                </li>
              ))}
            </ul>
          </section>
        )
      )}
      {!type ? (
        <p className="text-small">
          This server doesn&apos;t know this step&apos;s type, so its settings can&apos;t be shown. They&apos;re kept as they are.
        </p>
      ) : fields.length === 0 ? (
        <p className="text-small text-muted">This step has nothing to set up.</p>
      ) : (
        <DrawerContext.Provider value={{ node, type, editable, tenantId, workflowId, problems: mine, expressions, set: onConfig }}>
          <Tabs
            label="Settings"
            value={tab}
            onChange={setTab}
            tabs={[
              {
                value: "setup",
                label: tabLabel("Setup", counted(mine, setup)),
                content: setup.length > 0 ? (
                  <>
                    <p className="text-small text-muted">Each of these is required.</p>
                    {setup.map((f) => <FieldView key={f.pointer} spec={f} />)}
                  </>
                ) : (
                  <p className="text-small text-muted">Nothing here is required.</p>
                ),
              },
              {
                value: "options",
                label: tabLabel("Options", counted(mine, options)),
                content: options.length > 0
                  ? options.map((f) => <FieldView key={f.pointer} spec={f} />)
                  : <p className="text-small text-muted">Nothing else to set.</p>,
              },
            ]}
          />
        </DrawerContext.Provider>
      )}
      {expressions.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-small font-semibold">How its formulas run</h3>
          <ul className="flex flex-col gap-1.5 text-small">
            {expressions.map((x) => (
              <li key={x.field}>
                <span className="font-mono text-meta">{x.field}</span>{" "}
                {x.mode === "local" ? "Runs inline" : `Runs as a separate step: ${x.reason ?? "no reason given"}`}
              </li>
            ))}
          </ul>
        </section>
      )}
      {editable && adds.length > 0 && (
        // Each "+" this step has on the canvas, at full size whatever the zoom (WCAG 2.5.8: their equivalents).
        <div role="group" aria-label="Add a step" className="flex flex-col items-start gap-2">
          {adds.map((a) => (
            <Button key={a.label} size="sm" onClick={() => onAdd(a.action)}>{a.label}</Button>
          ))}
        </div>
      )}
      {editable && (
        <div role="group" aria-label={`Where ${node.key} sits`} className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={onPlace}>Place on the canvas…</Button>
          {NUDGES.map((n) => (
            <Button key={n.key} size="sm" aria-label={`Move ${node.key} ${n.word}`} onClick={() => onNudge(n.key)}>
              {n.glyph}
            </Button>
          ))}
        </div>
      )}
      {editable && (
        <div className="flex flex-wrap gap-2">
          {ports.map((port) => (
            <Button key={port} size="sm" onClick={() => onConnectPort(port)}>
              Connect {port === "out" ? "" : `${port} `}to…
            </Button>
          ))}
          <Button size="sm" variant="danger-outline" onClick={onDelete}>Delete step</Button>
        </div>
      )}
    </aside>
  );
}
```

- [ ] **Step 5: Wire the drawer into the editor**

In `frontend/src/routes/editor/Editor.tsx`:

(a) Imports:
- Replace `import { StepPanel } from "./StepPanel";` with `import { StepDrawer } from "./drawer/StepDrawer";`.
- Add `import { setConfig } from "../../lib/config";` and `import type { Path } from "../../lib/schemaForm";`.
- Add `portOf` to the `../../lib/graph` import.

(b) Above `export function EditorPage`, add:

```ts
/** What the editor asks before doing: deleting a step or an edge, or a settings change that takes ports away, with the
 * document it makes (ruling 9). */
type Asking =
  | { kind: "node"; id: string }
  | { kind: "edge"; edge: GraphEdge }
  | { kind: "ports"; next: GraphDoc; dropped: GraphEdge[] };

/** Which ports a change takes away, and where their edges led (ruling 9). */
function portsQuestion(dropped: GraphEdge[], keyOf: (id: string) => string): string {
  const ports = [...new Set(dropped.map(portOf))];
  const targets = [...new Set(dropped.map((e) => keyOf(e.to.node)))];
  const one = ports.length === 1;
  return `${one ? "The port" : "The ports"} ${ports.join(", ")} ${one ? "goes" : "go"} with this change, and ${
    dropped.length === 1 ? "its edge" : "their edges"} to ${targets.join(", ")} ${dropped.length === 1 ? "is" : "are"} deleted.`;
}
```

and change the `asking` state to `useState<Asking | null>(null)`.

(c) Replace `change`:

```ts
  /** One edit: recorded (edits sharing a field's mark are one undo step, ruling 8), saved, and said, unless `message`
   * is null: a field's edits aren't announced, its control says what it holds. */
  function change(next: GraphDoc, message: string | null, then?: string, mark?: string) {
    if (!mayEdit()) return; // read only now: a conflict, an exit agreed to, a version view, a publication
    setHistory((h) => record(h, next, mark));
    saver.current?.change(next);
    if (message !== null) announce(message);
    if (then) focus(then);
  }

  /** A change to a step's settings. One that takes ports away asks first, as deleting a step does (ruling 9). */
  function settle(next: GraphDoc, dropped: GraphEdge[], mark?: string) {
    if (dropped.length > 0) setAsking({ kind: "ports", next, dropped });
    else change(next, null, undefined, mark);
  }

  function onConfig(nodeId: string, path: Path, value: unknown, mark?: string) {
    const node = findNode(doc, nodeId);
    if (!node) return;
    const { doc: next, dropped } = setConfig(doc, nodeId, path, value, typeMap.get(node.type));
    settle(next, dropped, mark);
  }
```

(d) In `confirmDelete`, before the `if (asking.kind === "node")` branch, add:

```ts
    if (asking.kind === "ports") {
      const ports = [...new Set(asking.dropped.map(portOf))].join(", ");
      change(asking.next, `Removed ${ports} and ${asking.dropped.length === 1 ? "its edge" : `${asking.dropped.length} edges`}`);
      setAsking(null);
      // What asked is gone with its port (a Remove, a JSON edit): focus lands on the drawer, after the dialog has
      // given it back (WCAG 2.4.3).
      requestAnimationFrame(() => document.getElementById("step-drawer-title")?.focus());
      return;
    }
```

(e) Replace the `<StepPanel … />` element with:

```tsx
          <StepDrawer
            key={idKey(open.id)}
            node={open}
            type={typeMap.get(open.type)}
            tenantId={tenantId}
            workflowId={workflow.id}
            ports={portMap.get(idKey(open.id)) ?? []}
            problems={
              viewing || !trusted ? null : [...trusted.diagnostics, ...published].filter((d) => d.node !== null && sameId(d.node, open.id))
            }
            expressions={(viewing ? viewing.expressions : (trusted?.expressions ?? [])).filter((x) => x.node !== null && sameId(x.node, open.id))}
            editable={editable}
            adds={editable ? addsOf(doc, open, portMap.get(idKey(open.id)) ?? []) : []}
            onAdd={onItem}
            onDelete={() => setAsking({ kind: "node", id: open.id })}
            onConnectPort={(port) => setConnecting({ node: open.id, port })}
            onPlace={() => {
              setPlacing(open.id);
              announce(`Click an empty place on the canvas to put ${open.key} there`);
            }}
            onNudge={(key) => nudge(open.id, key)}
            onClose={() => {
              setSide(null);
              focus(item.node(open.id));
            }}
            onConfig={(path, value, mark) => onConfig(open.id, path, value, mark)}
          />
```

(f) In the delete `ConfirmDialog`:
- `title={asking?.kind === "edge" ? "Delete an edge" : asking?.kind === "ports" ? "Remove a port" : "Delete a step"}`;
- `confirmLabel={asking?.kind === "ports" ? "Remove" : "Delete"}`;
- as its last child, `{asking?.kind === "ports" && portsQuestion(asking.dropped, keyOf)}`.

(g) Delete `frontend/src/routes/editor/StepPanel.tsx`: `git rm frontend/src/routes/editor/StepPanel.tsx`.

- [ ] **Step 6: Run the editor's tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, the new tests and every 4b test. The 4b tests read the drawer as they read the panel:
- its name is the step's key;
- "Transform · flow.transform@1";
- "30 s" in the chip;
- "Runs as a separate step: builds a message" in "How its formulas run";
- "Not checked for what's on the screen.";
- a problem at "/fields" listed under "Problems with this step", since the test type's schema names no fields.

- [ ] **Step 7: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 build`
Expected: all pass.

- [ ] **Step 8: The first browser check of Radix Tabs (ruling 17)**

Run the browser gate: the session's `compose-ui4a/e2e.sh` (about 6 minutes).
Expected:
- the 4b flows pass: their step panels are now the drawer, with its tabs;
- the notices test finds `@radix-ui/react-tabs`;
- no CSP violation and no axe violation on any screen.

A CSP violation from the tabs stops the work: report it to the owner, who chooses (D23).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): the step drawer: a step's settings on Setup and Options, edits that take ports away asked first (4c-1)"
```

### Task 7: Lists, maps and a case's port

**Files:**
- Modify: `frontend/src/routes/editor/drawer/structured.tsx`
- Modify: `frontend/src/routes/editor/drawer/context.ts` (`renamePort` on `Drawer`)
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx` (two call sites, and the port's control)
- Modify: `frontend/src/routes/editor/drawer/harness.tsx` (`renamePort`)
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (`onRenamePort`)
- Modify: `frontend/src/routes/editor/Editor.tsx` (`onRenamePort`)
- Test: `frontend/src/routes/editor/drawer/FieldView.test.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 1: `itemOf`, `entryOf`, `isObject`, `emptyOf`;
  - from Task 2: `ENVELOPE`, `freePort`, `renamePort`.
- Produces:
  - `Drawer.renamePort: (index: number, name: string) => string | null`: the reason a name is refused, or null;
  - `isContainer` (group, list, map), `partNames(spec, value)`, `ContainerParts({ spec, value })`, `PortControl`;
  - StepDrawer prop `onRenamePort: (index: number, name: string) => string | null`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/routes/editor/drawer/FieldView.test.tsx` (add `vi` to the vitest import, and `SWITCH`,
`TRANSFORM` to the node types import):

```tsx
it("adds, moves and removes a list's items", async () => {
  const { config } = showFields(REMOTE);
  await userEvent.click(screen.getByRole("button", { name: "Add to Tags" }));
  await userEvent.type(screen.getByLabelText("Tags, item 1"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Add to Tags" }));
  await userEvent.type(screen.getByLabelText("Tags, item 2"), "y");
  expect(config().tags).toEqual(["x", "y"]);
  await userEvent.click(screen.getByRole("button", { name: "Move up: Tags, item 2" }));
  expect(config().tags).toEqual(["y", "x"]);
  await userEvent.click(screen.getByRole("button", { name: "Remove: Tags, item 1" }));
  expect(config().tags).toEqual(["x"]);
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add to Tags" })));
});

it("adds a case with the first free port name", async () => {
  const { config } = showFields(SWITCH);
  await userEvent.click(screen.getByRole("button", { name: "Add to Cases" }));
  expect(config()).toEqual({ cases: [{ port: "case_1" }] });
  const item = screen.getByRole("group", { name: "Cases, item 1" });
  expect(within(item).getByLabelText<HTMLInputElement>("Port").value).toBe("case_1");
  expect(within(item).getByLabelText("When").tagName).toBe("TEXTAREA");
});

it("sets a map's entries, renamed in place, never as $value", async () => {
  const { config } = showFields(TRANSFORM);
  await userEvent.click(screen.getByRole("button", { name: "Add to Fields" }));
  await userEvent.type(screen.getByLabelText("field_1"), "1 + 1"); // an entry starts as a formula
  const name = screen.getByLabelText("Name: field_1");
  await userEvent.clear(name);
  await userEvent.type(name, "total");
  await userEvent.tab();
  expect(config()).toEqual({ fields: { total: formula("1 + 1") } });
  const renamed = screen.getByLabelText("Name: total");
  await userEvent.clear(renamed);
  await userEvent.type(renamed, "$value");
  await userEvent.tab();
  expect(screen.getByText("A name can't be $value: the engine would read the whole value as computed.")).toBeTruthy();
  expect(config()).toEqual({ fields: { total: formula("1 + 1") } });
});
```

Append to `frontend/src/routes/editor/Editor.test.tsx` (add `formula` from `../../lib/config` and `SWITCH` to the
imports):

```tsx
/** A switch whose case b leads to a transform. */
const switched = () => ({
  graph_format: 1,
  nodes: [
    { id: "id-pick", key: "pick", type: "flow.switch@1", config: { cases: [{ port: "a", when: formula("true") }, { port: "b", when: formula("false") }] }, position: { x: 0, y: 140 } },
    { id: "id-transform", key: "transform", type: "flow.transform@1", position: { x: 0, y: 280 } },
  ],
  edges: [{ from: { node: "id-pick", port: "b" }, to: { node: "id-transform" } }],
});  // prettier-ignore

async function openSwitch() {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, SWITCH]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: switched() }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "pick" }));
}

it("renames a case's port in place, its edges following", async () => {
  await openSwitch();
  const port = within(screen.getByRole("group", { name: "Cases, item 2" })).getByLabelText("Port");
  await userEvent.clear(port);
  await userEvent.type(port, "big{Enter}"); // applies on Enter, or when focus leaves
  expect(drawn.at(-1)!.doc.edges).toEqual([{ from: { node: "id-pick", port: "big" }, to: { node: "id-transform" } }]);
});

it("asks before removing a case with edges", async () => {
  await openSwitch();
  await userEvent.click(screen.getByRole("button", { name: "Remove: Cases, item 2" }));
  const dialog = screen.getByRole("dialog", { name: "Remove a port" });
  expect(dialog.textContent).toContain("The port b goes with this change, and its edge to transform is deleted.");
  await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
  expect(drawn.at(-1)!.doc.edges).toEqual([]);
  expect(stepConfig("pick")).toEqual({ cases: [{ port: "a", when: formula("true") }] });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL. A list and a map show as JSON, so there is no "Add to Tags" button, no "Cases, item 2" group, and no
"Add to Fields" button.

- [ ] **Step 3: Let a field rename its port**

In `frontend/src/routes/editor/drawer/context.ts`, add to `Drawer`:

```ts
  /** A dynamic port renamed (a switch case's `port`), its edges following; the reason it's refused, or null. */
  renamePort: (index: number, name: string) => string | null;
```

In `frontend/src/routes/editor/drawer/harness.tsx`, add to the `drawer` object:

```ts
    // As the editor does, without edges: the name is written where the case sits.
    renamePort: (index: number, name: string) => {
      set([type.dynamic_ports ?? "", index, "port"], name);
      return null;
    },
```

In `frontend/src/routes/editor/drawer/StepDrawer.tsx`:
- add the prop `onRenamePort: (index: number, name: string) => string | null` to the destructuring and its type;
- add `renamePort: onRenamePort` to the `DrawerContext.Provider`'s value.

- [ ] **Step 4: Write lists, maps and the port's control**

Replace `frontend/src/routes/editor/drawer/structured.tsx` with:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A value made of parts (4c-1, ruling 5): a group's properties, a list's items, a map's entries, each a field of its
// own; and a dynamic port's name, which edges hang on (ruling 9).
import { useRef, useState, useId } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { ENVELOPE, freePort } from "../../../lib/config";
import { emptyOf, entryOf, isObject, itemOf, propertiesOf, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import type { GraphNode } from "../../../lib/workflows";
import { segment, useDrawer } from "./context";
import { FieldView } from "./FieldView";
import { useText, type ControlProps } from "./scalars";

/** The widgets shown as their parts rather than as one control. */
export const isContainer = (widget: Widget): boolean => widget === "group" || widget === "list" || widget === "map";

/** The pointer segments of the parts a container shows: a problem below it in any other part is its own. */
export function partNames(spec: FieldSpec, value: unknown): string[] {
  if (spec.base === "list") return Array.isArray(value) ? (value as unknown[]).map((_, i) => String(i)) : [];
  if (spec.base === "map") return isObject(value) ? Object.keys(value).map(segment) : [];
  return propertiesOf(spec).map((p) => segment(p.name));
}

/** A new item: a case with the first free port name (ruling 9), else its schema's default, else an empty part. */
function newItem(item: FieldSpec, node: GraphNode): unknown {
  if (item.type.dynamic_ports !== null && item.path.length === 2 && item.path[0] === item.type.dynamic_ports) {
    return { port: freePort(node, item.type) };
  }
  if (item.schema.default !== undefined) return structuredClone(item.schema.default);
  return item.base === "group" || item.base === "map" ? {} : item.base === "list" ? [] : emptyOf(item);
}

function ListItems({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const add = useRef<HTMLButtonElement>(null);
  const items = Array.isArray(value) ? (value as unknown[]) : [];
  const move = (from: number, to: number) => {
    const next = [...items];
    next.splice(to, 0, ...next.splice(from, 1));
    drawer.set(spec.path, next);
  };
  const remove = (index: number) => {
    drawer.set([...spec.path, index], undefined);
    // Its controls are gone: focus goes to Add. A removal that asks first lands on the drawer's heading instead.
    requestAnimationFrame(() => add.current?.focus());
  };
  return (
    <>
      {items.length === 0 && <p className="text-small text-muted">None yet.</p>}
      {items.map((_, i) => {
        const item = itemOf(spec, i);
        return (
          <div key={i} className="flex min-w-0 flex-col gap-2">
            <FieldView spec={item} />
            {drawer.editable && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" aria-label={`Move up: ${item.label}`} disabled={i === 0} onClick={() => move(i, i - 1)}>Move up</Button>
                <Button size="sm" aria-label={`Move down: ${item.label}`} disabled={i === items.length - 1} onClick={() => move(i, i + 1)}>
                  Move down
                </Button>
                <Button size="sm" variant="danger-outline" aria-label={`Remove: ${item.label}`} onClick={() => remove(i)}>Remove</Button>
              </div>
            )}
          </div>
        );
      })}
      {drawer.editable && (
        <Button ref={add} size="sm" className="self-start" onClick={() => drawer.set([...spec.path, items.length], newItem(itemOf(spec, items.length), drawer.node))}>
          Add to {spec.label}
        </Button>
      )}
    </>
  );
}

/** A map entry's name: it applies when focus leaves or on Enter, refused when empty, `$value` (ruling 15) or taken. */
function NameField({ name, disabled, onRename }: { name: string; disabled: boolean; onRename: (to: string) => string | null }) {
  const id = useId();
  const [text, setText] = useText(name, (v) => String(v), (t, v) => t === v);
  const [problem, setProblem] = useState<string | null>(null);
  const commit = () => setProblem(onRename(text.trim()));
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-small font-semibold">Name</label>
      <input
        id={id} type="text" value={text} disabled={disabled} spellCheck={false} aria-label={`Name: ${name}`}
        aria-invalid={problem !== null} aria-describedby={problem !== null ? `${id}-p` : undefined}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        className={`${controlClass(problem !== null)} font-mono`}
      />
      {problem !== null && <p id={`${id}-p`} className="text-small text-danger">{problem}</p>}
    </div>
  );  // prettier-ignore
}

function MapEntries({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const add = useRef<HTMLButtonElement>(null);
  const entries = isObject(value) ? Object.entries(value) : [];
  const rename = (from: string, to: string): string | null => {
    if (to === from) return null;
    if (to === "") return "A name can't be empty.";
    if (to === ENVELOPE) return "A name can't be $value: the engine would read the whole value as computed.";
    if (entries.some(([k]) => k === to)) return `There's already one called ${to}.`;
    drawer.set(spec.path, Object.fromEntries(entries.map(([k, v]) => [k === from ? to : k, v]))); // in place
    return null;
  };
  const addOne = () => {
    const taken = new Set(entries.map(([k]) => k));
    let n = 1;
    while (taken.has(`field_${n}`)) n++;
    drawer.set([...spec.path, `field_${n}`], null);
  };
  return (
    <>
      {entries.length === 0 && <p className="text-small text-muted">None yet.</p>}
      {entries.map(([name], i) => {
        const entry = entryOf(spec, name);
        return (
          <div key={i} className="flex min-w-0 flex-col gap-2">
            <NameField name={name} disabled={!drawer.editable} onRename={(to) => rename(name, to)} />
            <FieldView spec={entry} />
            {drawer.editable && (
              <Button
                size="sm" variant="danger-outline" className="self-start" aria-label={`Remove: ${name}`}
                onClick={() => {
                  drawer.set(entry.path, undefined);
                  requestAnimationFrame(() => add.current?.focus());
                }}
              >
                Remove
              </Button>
            )}
          </div>
        );  // prettier-ignore
      })}
      {drawer.editable && (
        <Button ref={add} size="sm" className="self-start" onClick={addOne}>Add to {spec.label}</Button>
      )}
    </>
  );
}

export function ContainerParts({ spec, value }: { spec: FieldSpec; value: unknown }) {
  if (spec.base === "list") return <ListItems spec={spec} value={value} />;
  if (spec.base === "map") return <MapEntries spec={spec} value={value} />;
  return propertiesOf(spec).map((part) => <FieldView key={part.pointer} spec={part} />);
}

/** A dynamic port's name (a switch case's `port`): edges hang on it, so it applies when focus leaves or on Enter, and
 * its edges follow it; a name the graph's format refuses, or another port's, is refused there (ruling 9). */
export function PortControl({ spec, value, id, describedBy, invalid, disabled, onLocal }: ControlProps) {
  const drawer = useDrawer();
  const [text, setText] = useText(value, (v) => (typeof v === "string" ? v : ""), (t, v) => t === v);
  const commit = () => {
    if (text.trim() !== value) onLocal(drawer.renamePort(spec.path[1] as number, text.trim()));
  };
  return (
    <input
      id={id} type="text" value={text} disabled={disabled} spellCheck={false}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required
      onChange={(e) => setText(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
      className={`${controlClass(invalid)} font-mono`}
    />
  );  // prettier-ignore
}
```

- [ ] **Step 5: Use them in the field**

In `frontend/src/routes/editor/drawer/FieldView.tsx`:
- import `PortControl` from `./structured`;
- `partNames(spec)` becomes `partNames(spec, fixed)`;
- `<ContainerParts spec={spec} />` becomes `<ContainerParts spec={spec} value={fixed} />`;
- the control is chosen with the port first:

```tsx
  const Control: Control = json
    ? JsonControl
    : spec.port
      ? PortControl
      : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
```

- [ ] **Step 6: Rename a port in the editor**

In `frontend/src/routes/editor/Editor.tsx`:
- add `renamePort` to the `../../lib/config` import;
- add, after `onConfig`:

```ts
  /** A case's port renamed in place: its edges follow (ruling 9). The reason a name is refused, or null. */
  function onRenamePort(nodeId: string, index: number, name: string): string | null {
    const node = findNode(doc, nodeId);
    const type = node ? typeMap.get(node.type) : undefined;
    if (!node || !type) return null;
    const result = renamePort(doc, nodeId, index, name, type);
    if ("problem" in result) return result.problem;
    if (result.doc !== doc) change(result.doc, `The port is now ${name}; its edges follow it`);
    return null;
  }
```

- pass `onRenamePort={(index, name) => onRenamePort(open.id, index, name)}` to `StepDrawer`.

- [ ] **Step 7: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test. Task 6's JSON test keeps passing: its `routes` field is untyped, so it's still JSON.

- [ ] **Step 8: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): lists, maps and a switch case's port in the step drawer, its edges following (4c-1)"
```

- [ ] **Step 10: Milestone 2 pause (the owner's review)**

Take screenshots with the session's `compose-shots.mjs`, against the isolated stack after a reset, of these drawers:
- an `if` step's Setup with a formula;
- a loop's Options;
- a switch with two cases;
- a transform's map with a formula entry;
- a group as JSON;
- the same drawer read only, for a viewer.

Take each in light and dark, at 1280 and 320 px. Put them beside frame 1c's drawer in the session's checkpoint page
(as `checkpoint-4b.html` did). Stop, and give the owner the page and a short summary. Milestone 3 starts on the
owner's word.

# Milestone 3: references and behaviour

### Task 8: The connection and workflow pickers

**Files:**
- Create: `frontend/src/routes/editor/drawer/pickers.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx` (`controlFor`)
- Modify: `frontend/src/routes/editor/drawer/harness.tsx` (`fakeApi`, `json`, `routed`)
- Test: `frontend/src/routes/editor/drawer/pickers.test.tsx`; `FieldView.test.tsx` (its API answered locally)

**Interfaces:**
- Consumes:
  - `client`, `ok`, `Schemas` (`lib/client.ts`);
  - `workflowsQuery` (`lib/workflows.ts`);
  - `sameId` (`lib/graph.ts`);
  - from Task 5: `ControlProps`, `useDrawer`, `controlClass`.
- Produces:
  - `connectionsQuery(tenantId)` (key `["connections", tenantId]`, the Connections page's own);
  - `ConnectionControl`, `WorkflowControl`;
  - harness: `fakeApi(answers: Record<string, () => Response>): { method; path; body }[]`, `json(body, status?)`, and
    `showFields(type, { routed: true })` inside a router.

- [ ] **Step 1: Read the API's shapes**

Run: `grep -n '"/api/v1/t/{tenant_id}/connections": {\|"/api/v1/t/{tenant_id}/workflows": {' -A 14 src/api/schema.d.ts`
Expected: each `get` answers a list: `ConnectionOut[]` and `WorkflowOut[]`. The connection's `status` is `"unverified"
| "ok" | "error"`. If either differs, adapt Step 4's code and record a mid-slice ruling.

- [ ] **Step 2: Let tests answer the API and render inside a router**

In `frontend/src/routes/editor/drawer/harness.tsx`:
- add the imports `import { RouterProvider, createMemoryHistory, createRootRoute, createRouter } from
  "@tanstack/react-router";` and `import { vi } from "vitest";`;
- add `routed?: boolean; // inside a router: a link to another page needs one` to `Options`;
- replace the `render(…)` in `showFields` with:

```tsx
  const fields = (
    <QueryClientProvider client={client}>
      <Fields type={type} options={options} edits={edits} state={state} />
    </QueryClientProvider>
  );
  if (!options.routed) render(fields);
  else {
    const root = createRootRoute({ component: () => fields });
    render(<RouterProvider router={createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ["/"] }) })} />);
  }
```

and add at the end:

```tsx
export const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

/** The API's answers, by "METHOD /path" (the path decoded); anything else is a 404, never the network. Each request is
 * kept. */
export function fakeApi(answers: Record<string, () => Response>) {
  const sent: { method: string; path: string; body: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = decodeURIComponent(new URL(request.url).pathname);
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? (JSON.parse(text) as unknown) : null });
    const answer = answers[`${request.method} ${path}`];
    return answer ? answer() : json({ error: "not_found" }, 404);
  });
  return sent;
}
```

In `frontend/src/routes/editor/drawer/FieldView.test.tsx`, so its pickers never reach the network:
- add `afterEach` and `beforeEach` to the vitest import, and `fakeApi` to the harness import;
- add, after the imports:

```tsx
beforeEach(() => {
  fakeApi({}); // a picker's list answers 404 here, never the network
});
afterEach(() => {
  vi.restoreAllMocks();
});
```

- [ ] **Step 3: Write the failing tests**

Create `frontend/src/routes/editor/drawer/pickers.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { REMOTE, RUN_WORKFLOW, typeWith } from "../../../test/nodeTypes";
import { fakeApi, json, showFields } from "./harness";

afterEach(() => {
  vi.restoreAllMocks();
});

const C1 = "00000000-0000-4000-8000-0000000000c1";
const C2 = "00000000-0000-4000-8000-0000000000c2";
const CONNECTIONS = "GET /api/v1/t/t1/connections";
const connection = (id: string, name: string, type: string, status: "ok" | "unverified" | "error") => ({
  id, name, type, status, revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null,
});  // prettier-ignore

it("lists the tenant's connections of the field's type, with their status in words", async () => {
  fakeApi({
    [CONNECTIONS]: () => json([connection(C1, "Prod", "acme", "ok"), connection(C2, "Lab", "acme", "unverified"), connection("c3", "Chat", "slack", "ok")]),
  });
  const { config } = showFields(REMOTE);
  const select = await screen.findByLabelText<HTMLSelectElement>("Connection");
  expect([...select.options].map((o) => o.textContent)).toEqual(["Choose a connection", "Prod · verified", "Lab · not verified yet"]);
  await userEvent.selectOptions(select, "Lab · not verified yet");
  expect(config().connection).toBe(C2);
});

it("links to Connections when there's no Mist connection yet", async () => {
  fakeApi({ [CONNECTIONS]: () => json([]) });
  const mist = typeWith({
    type: "object", required: ["connection"],
    properties: { connection: { type: "string", format: "uuid", title: "Connection", "x-dewpoint-literal": true, "x-dewpoint-connection": "mist" } },
  });  // prettier-ignore
  showFields(mist, { routed: true });
  const link = await screen.findByRole("link", { name: "Add one in Connections" });
  expect(link.getAttribute("href")).toBe("/t/t1/connections");
});

it("says an admin adds a connection of any other type", async () => {
  fakeApi({ [CONNECTIONS]: () => json([]) });
  showFields(REMOTE);
  expect(await screen.findByText("No acme connection yet: an admin adds one.")).toBeTruthy();
});

it("shows a connection that isn't in this tenant until it's changed", async () => {
  fakeApi({ [CONNECTIONS]: () => json([connection(C1, "Prod", "acme", "ok")]) });
  showFields(REMOTE, { config: { connection: "00000000-0000-4000-8000-0000000000ff" } });
  const select = await screen.findByLabelText<HTMLSelectElement>("Connection");
  expect(select.selectedOptions[0]!.textContent).toBe("A connection that isn't in this tenant");
});

it("lists this tenant's other workflows", async () => {
  fakeApi({ "GET /api/v1/t/t1/workflows": () => json([{ id: "w1", name: "This one" }, { id: "w2", name: "Nightly" }]) });
  const { config } = showFields(RUN_WORKFLOW);
  const select = await screen.findByLabelText<HTMLSelectElement>("Workflow Id");
  expect([...select.options].map((o) => o.textContent)).toEqual(["Choose a workflow", "Nightly"]);
  await userEvent.selectOptions(select, "Nightly");
  expect(config().workflow_id).toBe("w2");
});
```

- [ ] **Step 4: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/drawer/pickers.test.tsx`
Expected: FAIL. "Connection" is a text input and "Workflow Id" a text input, so there are no options and no link.

- [ ] **Step 5: Write the pickers**

Create `frontend/src/routes/editor/drawer/pickers.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// Choosing what a step uses from the tenant's own (4c-1, rulings 12 and 13): a connection of the field's type, its
// status in words, or another workflow. A value naming nothing here is said to, until it's changed.
import { queryOptions, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { client, ok, type Schemas } from "../../../lib/client";
import { sameId } from "../../../lib/graph";
import { workflowsQuery } from "../../../lib/workflows";
import { useDrawer } from "./context";
import type { ControlProps } from "./scalars";

type Connection = Schemas["ConnectionOut"];
const STATUS: Record<Connection["status"], string> = {
  ok: "verified",
  unverified: "not verified yet",
  error: "failed its last check",
};

/** The tenant's connections, under Connections' own key: each page sees the other's changes. */
export const connectionsQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["connections", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path: { tenant_id: tenantId } } })),
  });

function Failed({ what, retry }: { what: string; retry: () => void }) {
  return (
    <p className="flex flex-wrap items-center gap-2 text-small text-danger">
      {what} couldn&apos;t load.
      <Button size="sm" onClick={retry}>Try again</Button>
    </p>
  );
}

export function ConnectionControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const { tenantId } = useDrawer();
  const marker = spec.schema["x-dewpoint-connection"];
  const kind = typeof marker === "string" ? marker : "";
  const list = useQuery(connectionsQuery(tenantId));
  if (list.isPending) return <p className="text-small text-muted">Loading connections…</p>;
  if (list.isError) return <Failed what="Connections" retry={() => void list.refetch()} />;
  const mine = list.data.filter((c) => c.type === kind);
  const current = typeof value === "string" ? value : "";
  const known = current !== "" && mine.some((c) => sameId(c.id, current));
  if (mine.length === 0 && current === "") {
    return kind === "mist" ? (
      <p className="text-small">
        No Mist connection yet.{" "}
        <Link to="/t/$tenantId/connections" params={{ tenantId }} className="font-semibold underline">
          Add one in Connections
        </Link>
        .
      </p>
    ) : (
      <p className="text-small">No {kind} connection yet: an admin adds one.</p>
    );
  }
  return (
    <select
      id={id} value={current} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, false)}
      className={controlClass(invalid)}
    >
      <option value="">Choose a connection</option>
      {current !== "" && !known && <option value={current}>A connection that isn&apos;t in this tenant</option>}
      {mine.map((c) => (
        // The id as the step writes it, whatever its spelling, so the step's own stays chosen.
        <option key={c.id} value={known && sameId(c.id, current) ? current : c.id}>
          {c.name} · {STATUS[c.status]}
        </option>
      ))}
    </select>
  );  // prettier-ignore
}

export function WorkflowControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const { tenantId, workflowId } = useDrawer();
  const list = useQuery(workflowsQuery(tenantId));
  if (list.isPending) return <p className="text-small text-muted">Loading workflows…</p>;
  if (list.isError) return <Failed what="Workflows" retry={() => void list.refetch()} />;
  const others = list.data.filter((w) => !sameId(w.id, workflowId));
  const current = typeof value === "string" ? value : "";
  const known = current !== "" && others.some((w) => sameId(w.id, current));
  if (others.length === 0 && current === "") return <p className="text-small">No other workflow yet.</p>;
  return (
    <select
      id={id} value={current} disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, false)}
      className={controlClass(invalid)}
    >
      <option value="">Choose a workflow</option>
      {current !== "" && !known && <option value={current}>A workflow that isn&apos;t in this tenant</option>}
      {others.map((w) => (
        <option key={w.id} value={known && sameId(w.id, current) ? current : w.id}>{w.name}</option>
      ))}
    </select>
  );  // prettier-ignore
}
```

- [ ] **Step 6: Use them in the field**

In `frontend/src/routes/editor/drawer/FieldView.tsx`:
- import `ConnectionControl` and `WorkflowControl` from `./pickers`;
- add to `controlFor`'s switch, before `default`:

```tsx
    case "connection":
      return ConnectionControl;
    case "workflow":
      return WorkflowControl;
```

- [ ] **Step 7: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test.

- [ ] **Step 8: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/routes/editor/drawer
git commit -m "feat(editor): choose a step's connection and sub-workflow from the tenant's own (4c-1)"
```

### Task 9: Live options, on request

**Files:**
- Create: `frontend/src/routes/editor/drawer/LiveOptions.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx` (`controlFor`)
- Test: `frontend/src/routes/editor/drawer/LiveOptions.test.tsx`

**Interfaces:**
- Consumes:
  - `ApiError`, `client`, `ok`, `Schemas` (`lib/client.ts`);
  - from Task 1: `fieldsOf`;
  - from Task 2: `valueAt`;
  - from Task 8: `fakeApi`, `json`.
- Produces: `OptionsControl`.

- [ ] **Step 1: Read the API's shape**

Run: `grep -n '"/api/v1/t/{tenant_id}/node-types/{ref}/options": {' -A 24 src/api/schema.d.ts`
Expected:
- path parameters `tenant_id` and `ref`;
- the body is `OptionsIn` (`field`, `connection_id?`, `query?`);
- the answer is `OptionsOut` (`options: { value, label }[]`).

If any differs, adapt Step 4's code and record a mid-slice ruling.

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/routes/editor/drawer/LiveOptions.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { REMOTE } from "../../../test/nodeTypes";
import { fakeApi, json, showFields } from "./harness";

afterEach(() => {
  vi.restoreAllMocks();
});

const C1 = "00000000-0000-4000-8000-0000000000c1";
const CONNECTIONS = "GET /api/v1/t/t1/connections";
const OPTIONS = "POST /api/v1/t/t1/node-types/acme.sites@1/options";
const prod = () =>
  json([{ id: C1, name: "Prod", type: "acme", status: "ok", revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null }]);

it("never loads on render", async () => {
  const sent = fakeApi({ [CONNECTIONS]: prod });
  showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" }); // what loads by itself has loaded
  expect(sent.map((r) => `${r.method} ${r.path}`)).toEqual([CONNECTIONS]);
});

it("asks for a connection before loading", () => {
  fakeApi({ [CONNECTIONS]: prod });
  showFields(REMOTE);
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices" }).disabled).toBe(true);
  expect(screen.getByText("Choose the step's connection first: the choices come from it.")).toBeTruthy();
});

it("loads the choices on request, with the connection and the text typed, and sets the one chosen", async () => {
  const sent = fakeApi({
    [CONNECTIONS]: prod,
    [OPTIONS]: () => json({ options: [{ value: "s1", label: "HQ" }, { value: "s2", label: "Lab" }] }),
  });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await userEvent.type(screen.getByLabelText("Site"), "h");
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
  const choices = await screen.findByLabelText<HTMLSelectElement>("Choices for Site");
  expect(sent.find((r) => r.path.endsWith("/options"))!.body).toEqual({ field: "site_id", connection_id: C1, query: "h" });
  await userEvent.selectOptions(choices, "HQ (s1)");
  expect(config().site_id).toBe("s1");
});

it("says why choices couldn't load, keeping a typed value", async () => {
  fakeApi({ [CONNECTIONS]: prod, [OPTIONS]: () => json({ error: "plugin_calls_busy" }, 503) });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await userEvent.type(screen.getByLabelText("Site"), "hq-1");
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
  expect(await screen.findByText("Too many requests right now. Try again in a moment.")).toBeTruthy();
  expect(config().site_id).toBe("hq-1");
});
```

- [ ] **Step 3: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/drawer/LiveOptions.test.tsx`
Expected: FAIL. There's no "Show choices" button: "Site" is a plain text input.

- [ ] **Step 4: Write the control**

Create `frontend/src/routes/editor/drawer/LiveOptions.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A field whose choices the step's type lists (4c-1, ruling 14; plugins-3 D3). The value is typed freely, and its
// choices load only when the person asks, through the step's connection: an options call reaches the plugin's
// service, so it's never a side effect of opening a drawer (D24). The choices help; they never gate what's typed.
import { useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { ApiError, client, ok, type Schemas } from "../../../lib/client";
import { valueAt } from "../../../lib/config";
import { fieldsOf } from "../../../lib/schemaForm";
import { useDrawer } from "./context";
import type { ControlProps } from "./scalars";

type Option = Schemas["OptionOut"];
type Choices =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "done"; options: Option[] }
  | { status: "failed"; why: string };

/** Why the choices didn't load, by the API's code (`POST …/node-types/{ref}/options`). */
const WHY: Record<string, string> = {
  connection_unavailable: "The step's connection can't be used: choose another.",
  connection_changed: "The connection changed while the choices loaded. Try again.",
  forbidden: "Your role can't use this connection.",
  plugin_call_timeout: "The choices took too long to load. Try again.",
  plugin_calls_busy: "Too many requests right now. Try again in a moment.",
  too_many_plugin_calls: "Too many requests right now. Try again in a moment.",
  invalid_result: "The service answered with something that isn't a list of choices.",
  plugin_failed: "The service couldn't list the choices.",
  not_an_options_field: "This field has no choices to list.",
  unknown_node_type: "This step's type isn't on this server.",
  tenant_erasing: "This tenant is being erased.",
};

function said(choices: Choices): string {
  if (choices.status === "loading") return "Loading choices…";
  if (choices.status === "failed") return choices.why;
  if (choices.status === "done" && choices.options.length === 0) return "No choices match.";
  return "";
}

export function OptionsControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const drawer = useDrawer();
  const [choices, setChoices] = useState<Choices>({ status: "idle" });
  const asked = useRef(0); // the newest request: an older one's answer says nothing
  const field = fieldsOf(drawer.type).find((f) => f.widget === "connection");
  const connection = field ? valueAt(drawer.node.config ?? {}, field.path) : undefined;
  const blocked = drawer.type.credentials.length > 0 && typeof connection !== "string";
  const text = typeof value === "string" ? value : "";
  async function load() {
    const n = ++asked.current;
    setChoices({ status: "loading" });
    try {
      const answer = await ok(
        client.POST("/api/v1/t/{tenant_id}/node-types/{ref}/options", {
          params: { path: { tenant_id: drawer.tenantId, ref: drawer.type.ref } },
          body: { field: spec.name, connection_id: typeof connection === "string" ? connection : null, query: text.slice(0, 200) },
        }),
      );
      if (n === asked.current) setChoices({ status: "done", options: answer.options });
    } catch (e) {
      if (n === asked.current) setChoices({ status: "failed", why: (e instanceof ApiError && WHY[e.code]) || "The choices couldn't load." });
    }
  }
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex min-w-0 gap-2">
        <input
          id={id} type="text" value={text} disabled={disabled} spellCheck={false}
          aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
          onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value, true)}
          className={controlClass(invalid)}
        />
        <Button className="shrink-0" disabled={disabled || blocked || choices.status === "loading"} onClick={() => void load()}>
          Show choices
        </Button>
      </div>
      {blocked && <p className="text-small text-muted">Choose the step&apos;s connection first: the choices come from it.</p>}
      <p role="status" className={`text-small ${choices.status === "failed" ? "text-danger" : "text-muted"}`}>{said(choices)}</p>
      {choices.status === "done" && choices.options.length > 0 && (
        <select
          aria-label={`Choices for ${spec.label}`} value="" disabled={disabled} className={controlClass(false)}
          onChange={(e) => {
            onChange(e.target.value, false);
            document.getElementById(id)?.focus();
          }}
        >
          <option value="">{choices.options.length === 1 ? "1 choice" : `${choices.options.length} choices`}</option>
          {choices.options.map((o, i) => (
            <option key={`${i}:${o.value}`} value={o.value}>{o.label === o.value ? o.label : `${o.label} (${o.value})`}</option>
          ))}
        </select>
      )}
    </div>
  );  // prettier-ignore
}
```

- [ ] **Step 5: Use it in the field**

In `frontend/src/routes/editor/drawer/FieldView.tsx`, import `OptionsControl` from `./LiveOptions` and add to
`controlFor`'s switch, before `default`:

```tsx
    case "options":
      return OptionsControl;
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test.

- [ ] **Step 7: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/editor/drawer
git commit -m "feat(editor): live options load only when asked, through the step's connection (4c-1)"
```

### Task 10: The error-handling chip and its error port

**Files:**
- Modify: `frontend/src/routes/editor/drawer/ErrorHandling.tsx` (the section)
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (the chip, the section, `onOptions`)
- Modify: `frontend/src/routes/editor/Editor.tsx` (`onOptions`)
- Test: `frontend/src/routes/editor/drawer/ErrorHandling.test.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 2: `setOptions`, `StepOptions`;
  - from Task 5: `useSession`, `useText`;
  - from Task 6: `settle`.
- Produces:
  - `ErrorHandling({ node, type, editable, onOptions: (options: StepOptions, mark?: string) => void })`;
  - StepDrawer prop `onOptions`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/routes/editor/drawer/ErrorHandling.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { StepOptions } from "../../../lib/config";
import type { GraphNode } from "../../../lib/workflows";
import { DELAY } from "../../../test/nodeTypes";
import { ErrorHandling, chipText } from "./ErrorHandling";

const node = (options?: StepOptions): GraphNode => ({ id: "n1", key: "wait", type: "flow.delay@1", ...(options ? { options } : {}) });

it("says what a failure does in words, and the limits the step sets", () => {
  expect(chipText(node(), DELAY)).toBe("On error: fail the run");
  expect(chipText(node({ on_error: "port", max_attempts: 5, timeout_s: 60 }), DELAY)).toBe("On error: route to the error port · 5 attempts");
  expect(chipText(node({ on_error: "continue", max_attempts: 1, timeout_s: 30 }), DELAY)).toBe("On error: continue · 1 attempt · 30 s");
});

it("sets what a failure does, and leaves an emptied limit to the type", async () => {
  const onOptions = vi.fn<(options: StepOptions, mark?: string) => void>();
  render(<ErrorHandling node={node({ max_attempts: 5 })} type={DELAY} editable onOptions={onOptions} />);
  await userEvent.selectOptions(screen.getByLabelText("When it fails"), "Continue with the next step");
  expect(onOptions).toHaveBeenLastCalledWith({ max_attempts: 5, on_error: "continue" });
  expect(screen.getByText("If empty: 3.")).toBeTruthy();
  await userEvent.clear(screen.getByLabelText("Attempts"));
  expect(onOptions).toHaveBeenLastCalledWith({ max_attempts: undefined }, expect.stringMatching(/^n1\/options\/max_attempts#\d+$/));
});

it("refuses attempts and a timeout the graph's format refuses, saving neither", async () => {
  const onOptions = vi.fn<(options: StepOptions, mark?: string) => void>();
  render(<ErrorHandling node={node()} type={DELAY} editable onOptions={onOptions} />);
  await userEvent.type(screen.getByLabelText("Attempts"), "25");
  expect(screen.getByText("A whole number from 1 to 20.")).toBeTruthy();
  await userEvent.type(screen.getByLabelText("Timeout (seconds)"), "0");
  expect(screen.getByText("A number of seconds above 0, up to 86,400.")).toBeTruthy();
  expect(onOptions.mock.calls.map(([options]) => options)).toEqual([{ max_attempts: 2 }]); // "2", before the "5"
});
```

Append to `frontend/src/routes/editor/Editor.test.tsx` (add `IF` to the node types import):

```tsx
it("asks before errors stop going to a port", async () => {
  const draft = {
    graph_format: 1,
    nodes: [
      { id: "id-check", key: "check", type: "flow.if@1", options: { on_error: "port" }, position: { x: 0, y: 140 } },
      { id: "id-transform", key: "transform", type: "flow.transform@1", position: { x: 0, y: 280 } },
    ],
    edges: [{ from: { node: "id-check", port: "error" }, to: { node: "id-transform" } }],
  };  // prettier-ignore
  answers.set("GET /api/v1/node-types", () => json([...TYPES, IF]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "check" }));
  const chip = screen.getByRole("button", { name: "On error: route to the error port" });
  await userEvent.click(chip);
  expect(chip.getAttribute("aria-expanded")).toBe("true");
  await userEvent.selectOptions(screen.getByLabelText("When it fails"), "Fail the run");
  const dialog = screen.getByRole("dialog", { name: "Remove a port" });
  expect(dialog.textContent).toContain("The port error goes with this change, and its edge to transform is deleted.");
  await userEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
  expect(drawn.at(-1)!.doc.edges).toEqual([]);
  expect(drawn.at(-1)!.doc.nodes![0]).not.toHaveProperty("options");
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL. `ErrorHandling` isn't exported, and the chip is text, not a button.

- [ ] **Step 3: Write the section**

Append to `frontend/src/routes/editor/drawer/ErrorHandling.tsx`, adding the imports at its top:

```tsx
import { useState } from "react";
import { Field, Select } from "../../../components/Field";
import type { StepOptions } from "../../../lib/config";
import { useSession } from "./context";
import { useText } from "./scalars";
```

```tsx
/** A limit the step sets for itself: empty takes the type's. The graph's bounds are checked here, since a draft
 * breaking them isn't saved at all (ruling 7). */
function Limit({ label, value, fallback, disabled, check, onChange }: {
  label: string; value: number | null | undefined; fallback: string; disabled: boolean;
  check: (n: number) => string | null; onChange: (value: number | undefined) => void;
}) {  // prettier-ignore
  const [text, setText] = useText(
    value ?? undefined,
    (v) => (typeof v === "number" ? String(v) : ""),
    (t, v) => (t.trim() === "" ? v === undefined : Number(t) === v),
  );
  const [problem, setProblem] = useState<string | null>(null);
  return (
    <Field
      label={label} hint={`If empty: ${fallback}.`} error={problem ?? undefined} value={text} disabled={disabled}
      onChange={(e) => {
        setText(e.target.value);
        const t = e.target.value.trim();
        const why = t === "" ? null : check(Number(t));
        setProblem(why);
        if (why === null) onChange(t === "" ? undefined : Number(t));
      }}
    />
  );  // prettier-ignore
}

/** The chip's section (ruling 10): what a failure does, then the attempts and the timeout. */
export function ErrorHandling({ node, type, editable, onOptions }: {
  node: GraphNode; type: NodeType; editable: boolean; onOptions: (options: StepOptions, mark?: string) => void;
}) {  // prettier-ignore
  const own = node.options ?? {};
  const attempts = useSession(`${node.id}/options/max_attempts`);
  const timeout = useSession(`${node.id}/options/timeout_s`);
  return (
    <section id="error-handling" aria-label="Error handling" className="flex flex-col gap-4">
      <Select
        label="When it fails" value={own.on_error ?? "fail"} disabled={!editable}
        onChange={(e) => onOptions({ ...own, on_error: e.target.value as StepOptions["on_error"] })}
      >
        <option value="fail">Fail the run</option>
        <option value="continue">Continue with the next step</option>
        <option value="port">Route to an error port</option>
      </Select>
      <div onFocus={attempts.onFocus}>
        <Limit
          label="Attempts" value={own.max_attempts} fallback={String(type.retry.max_attempts)} disabled={!editable}
          check={(n) => (Number.isInteger(n) && n >= 1 && n <= 20 ? null : "A whole number from 1 to 20.")}
          onChange={(v) => onOptions({ ...own, max_attempts: v }, attempts.mark())}
        />
      </div>
      <div onFocus={timeout.onFocus}>
        <Limit
          label="Timeout (seconds)" value={own.timeout_s} fallback={`${type.timeout_s} s`} disabled={!editable}
          check={(n) => (n > 0 && n <= 86_400 ? null : "A number of seconds above 0, up to 86,400.")}
          onChange={(v) => onOptions({ ...own, timeout_s: v }, timeout.mark())}
        />
      </div>
    </section>
  );  // prettier-ignore
}
```

- [ ] **Step 4: Make the chip open it**

In `frontend/src/routes/editor/drawer/StepDrawer.tsx`:
- import `ErrorHandling` beside `chipText`, and `type StepOptions` from `../../../lib/config`;
- add the prop `onOptions: (options: StepOptions, mark?: string) => void`;
- add the state `const [handling, setHandling] = useState(false);`;
- replace `<p className="text-small">{chipText(node, type)}</p>` with:

```tsx
          {type ? (
            <Button size="sm" className="self-start" aria-expanded={handling} aria-controls="error-handling" onClick={() => setHandling(!handling)}>
              {chipText(node, type)}
            </Button>
          ) : (
            <p className="text-small">{chipText(node, type)}</p>
          )}
```

- after the header's closing `</div>`, add
  `{type && handling && <ErrorHandling node={node} type={type} editable={editable} onOptions={onOptions} />}`.

- [ ] **Step 5: Set options in the editor**

In `frontend/src/routes/editor/Editor.tsx`:
- add `setOptions` and `type StepOptions` to the `../../lib/config` import;
- add, after `onConfig`:

```ts
  function onOptions(nodeId: string, options: StepOptions, mark?: string) {
    const node = findNode(doc, nodeId);
    if (!node) return;
    const { doc: next, dropped } = setOptions(doc, nodeId, options, typeMap.get(node.type));
    settle(next, dropped, mark);
  }
```

- pass `onOptions={(options, mark) => onOptions(open.id, options, mark)}` to `StepDrawer`.

- [ ] **Step 6: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test. The 4b version test still finds "30 s", now in the chip's button.

- [ ] **Step 7: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): a step's error handling in a chip, its error port's edges asked before they go (4c-1)"
```

### Task 11: Key rename

**Files:**
- Create: `frontend/src/routes/editor/drawer/KeyField.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (`onRename`)
- Modify: `frontend/src/routes/editor/Editor.tsx` (`onRename`)
- Test: `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: from Task 2, `keyProblem` and `renameKey`.
- Produces:
  - `type Renamed = { problem: string } | { formulas: number }`;
  - `KeyField({ current, editable, onRename: (key: string) => Renamed, onRenamed: () => void })`;
  - StepDrawer prop `onRename: (key: string) => Renamed`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/routes/editor/Editor.test.tsx`:

```tsx
/** `fetch`, read by a formula in `use` and a reference in `copy`. */
const readers = () => ({
  graph_format: 1,
  nodes: [
    { id: "id-fetch", key: "fetch", type: "flow.transform@1", position: { x: 0, y: 140 } },
    { id: "id-use", key: "use", type: "flow.if@1", config: { condition: formula("steps.fetch.output.n > 1") }, position: { x: 0, y: 280 } },
    { id: "id-copy", key: "copy", type: "flow.transform@1", config: { fields: { x: { $value: { kind: "ref", path: "steps.fetch.output" } } } }, position: { x: 0, y: 420 } },
  ],
  edges: [],
});  // prettier-ignore

async function renameFetch(to: string) {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, IF]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: readers() }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "fetch" }));
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
  const key = screen.getByLabelText("Key");
  await userEvent.clear(key);
  await userEvent.type(key, `${to}{Enter}`);
}

it("says how many formulas still name the old key", async () => {
  await renameFetch("load");
  const heading = screen.getByRole("heading", { name: "load" });
  await vi.waitFor(() => expect(document.activeElement).toBe(heading));
  expect(screen.getByText("1 formula still names fetch: the problems show where.")).toBeTruthy();
  expect(stepConfig("copy")).toEqual({ fields: { x: { $value: { kind: "ref", path: "steps.load.output" } } } });
  await userEvent.keyboard("{Control>}z{/Control}"); // one step: the key and its references
  expect(stepConfig("copy")).toEqual({ fields: { x: { $value: { kind: "ref", path: "steps.fetch.output" } } } });
  expect(screen.getByRole("heading", { name: "fetch" })).toBeTruthy();
  expect(screen.queryByText(/still names fetch/)).toBeNull(); // said only while it's true
});

it("refuses a key another step has, and keeps its own", async () => {
  await renameFetch("use");
  expect(screen.getByText("Another step is already called use.")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "fetch" })).toBeTruthy();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/Editor.test.tsx`
Expected: FAIL. There's no "Rename" button.

- [ ] **Step 3: Write the rename**

Create `frontend/src/routes/editor/drawer/KeyField.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A step's key renamed from its drawer (4c-1, ruling 11). It's checked here: a key the graph's format refuses isn't
// saved, and a CEL word or another step's key never reads. Every structured reference follows. The formulas that
// still name the old key are counted: they aren't parsed here.
import { useEffect, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Field } from "../../../components/Field";

export type Renamed = { problem: string } | { formulas: number };

export function KeyField({ current, editable, onRename, onRenamed }: {
  current: string; editable: boolean; onRename: (key: string) => Renamed; onRenamed: () => void;
}) {  // prettier-ignore
  const [open, setOpen] = useState(false);
  const [text, setText] = useState(current);
  const [problem, setProblem] = useState<string | null>(null);
  // The formulas left naming the old key, said until the key changes again (an undo, another rename).
  const [left, setLeft] = useState<{ old: string; key: string; formulas: number } | null>(null);
  if (left !== null && left.key !== current) setLeft(null);
  const box = useRef<HTMLDivElement>(null); // Field makes its own input: focus finds it here
  const opener = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) box.current?.querySelector("input")?.focus();
  }, [open]);
  const close = () => {
    setOpen(false);
    setProblem(null);
    requestAnimationFrame(() => opener.current?.focus());
  };
  const apply = () => {
    const key = text.trim();
    if (key === current) return close();
    const result = onRename(key);
    if ("problem" in result) return setProblem(result.problem);
    setOpen(false);
    setProblem(null);
    setLeft(result.formulas > 0 ? { old: current, key, formulas: result.formulas } : null);
    onRenamed();
  };
  return (
    <div className="flex flex-col gap-2">
      {editable && !open && (
        <Button
          ref={opener} size="sm" className="self-start"
          onClick={() => {
            setText(current);
            setOpen(true);
          }}
        >
          Rename
        </Button>
      )}
      {open && (
        <div
          ref={box}
          className="flex flex-col gap-2"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation(); // closes the rename, not the drawer
              close();
            }
          }}
        >
          <Field
            label="Key" value={text} spellCheck={false} autoCapitalize="off" error={problem ?? undefined}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") apply();
            }}
          />
          <div className="flex gap-2">
            <Button size="sm" variant="primary" onClick={apply}>Rename</Button>
            <Button size="sm" onClick={close}>Cancel</Button>
          </div>
        </div>
      )}
      {left && (
        <p role="status" className="text-small">
          {left.formulas === 1 ? "1 formula still names" : `${left.formulas} formulas still name`} {left.old}: the problems show where.
        </p>
      )}
    </div>
  );  // prettier-ignore
}
```

- [ ] **Step 4: Put it under the drawer's heading**

In `frontend/src/routes/editor/drawer/StepDrawer.tsx`:
- import `KeyField` and `type Renamed` from `./KeyField`;
- add the prop `onRename: (key: string) => Renamed`;
- after the `<h2>`, add:

```tsx
          <KeyField
            current={node.key}
            editable={editable}
            onRename={onRename}
            onRenamed={() => requestAnimationFrame(() => heading.current?.focus())}
          />
```

- [ ] **Step 5: Rename in the editor**

In `frontend/src/routes/editor/Editor.tsx`:
- add `keyProblem` and `renameKey` to the `../../lib/config` import, and `type Renamed` from `./drawer/KeyField`;
- add, after `onOptions`:

```ts
  /** A step's key, with every structured reference to it (ruling 11), in one undo step. */
  function onRename(nodeId: string, key: string): Renamed {
    const problem = keyProblem(doc, nodeId, key);
    if (problem) return { problem };
    const old = keyOf(nodeId);
    const { doc: next, formulas } = renameKey(doc, nodeId, key);
    const still = formulas === 0 ? "" : `; ${formulas === 1 ? "1 formula still names" : `${formulas} formulas still name`} ${old}`;
    change(next, `Renamed ${old} to ${key}${still}`);
    return { formulas };
  }
```

- pass `onRename={(key) => onRename(open.id, key)}` to `StepDrawer`.

- [ ] **Step 6: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test.

- [ ] **Step 7: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): rename a step, its references following, the formulas that still name it counted (4c-1)"
```

### Task 12: A problem's "Go to" focuses its field

**Files:**
- Modify: `frontend/src/routes/editor/ProblemsPanel.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (`focusField`)
- Modify: `frontend/src/routes/editor/Editor.tsx` (`Side`'s field, `onJump`)
- Test: `frontend/src/routes/editor/ProblemsPanel.test.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Produces:
  - `ProblemsPanel`'s `onJump: (nodeId: string, field: string | null) => void`;
  - `Side`'s step kind: `{ kind: "step"; node: string; field?: { pointer: string; n: number } }`;
  - StepDrawer prop `focusField: { pointer: string; n: number } | null`.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/routes/editor/ProblemsPanel.test.tsx`, change the first test's last line to:

```tsx
  expect(onJump).toHaveBeenCalledWith("n1", "/fields");
```

Append to `frontend/src/routes/editor/Editor.test.tsx` (add `LOOP` to the node types import):

```tsx
/** A check that found these problems. */
const found = (...diagnostics: { message: string; field: string }[]) => ({
  draft_revision: 1, valid: false, expressions: [], taint: { sites: [], declassified: [] },
  diagnostics: diagnostics.map((d) => ({ code: "config.invalid", node: "id-each", fix: null, severity: "error", ...d })),
});  // prettier-ignore

async function goTo(field: string) {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, LOOP]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: oneStep("flow.loop@1", { items: formula("trigger.list") }, "each") }));
  answers.set(`POST ${BASE}/validate`, () => json(found({ message: "Must be at most 10.", field })));
  await show();
  await userEvent.click(await screen.findByRole("button", { name: "Problems · 1" }));
  await userEvent.click(within(screen.getByRole("complementary", { name: "Problems" })).getByRole("button", { name: "Go to each" }));
}

it("goes to a problem's field: the drawer opens on its tab, the field focused (ruling 83)", async () => {
  await goTo("/concurrency");
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Concurrency")));
  expect(screen.getByRole("tab", { name: "Options · 1 problem" }).getAttribute("aria-selected")).toBe("true");
});

it("goes to the step's own problems when no field shows the one named", async () => {
  await goTo("/nope");
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Problems with this step" })));
});

it("goes to the step itself for a problem about it as a whole, as in 4b", async () => {
  await goTo("");
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "each" })));
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL:
- `onJump` is called with `"n1"` alone;
- in the editor, "Go to each" focuses the step, never the drawer.

- [ ] **Step 3: Pass the field from the problems panel**

In `frontend/src/routes/editor/ProblemsPanel.tsx`:
- in `Problem`'s props and in `ProblemsPanel`'s, `onJump: (id: string) => void` becomes
  `onJump: (nodeId: string, field: string | null) => void`;
- the button's handler becomes `onClick={() => onJump(d.node!, d.field)}`.

- [ ] **Step 4: Open the drawer at the field**

In `frontend/src/routes/editor/Editor.tsx`:
- `Side`'s step kind becomes `{ kind: "step"; node: string; field?: { pointer: string; n: number } }`;
- add `const jumps = useRef(0); // each "Go to" a field, so the same one twice still focuses it` beside the other
  refs;
- `ProblemsPanel`'s `onJump` becomes:

```tsx
            onJump={(nodeId, field) => {
              // A field inside the step opens its drawer there (ruling 16); the step as a whole is focused, as in 4b.
              if (field === null || field === "") focus(item.node(nodeId));
              else setSide({ kind: "step", node: nodeId, field: { pointer: field, n: ++jumps.current } });
            }}
```

- pass `focusField={side?.kind === "step" ? (side.field ?? null) : null}` to `StepDrawer`.

In `frontend/src/routes/editor/drawer/StepDrawer.tsx`:
- add the prop `focusField: { pointer: string; n: number } | null`;
- add, after the `tab` state:

```tsx
  // "Go to" a field (ruling 16): its tab first; then, once that has rendered, the control of the closest field shown.
  // A pointer no field shows lands on "Problems with this step", which lists it.
  const pending = useRef<string | null>(null);
  useEffect(() => {
    if (!focusField) return;
    const first = focusField.pointer.split("/")[1] ?? "";
    if (setup.some((f) => segment(f.name) === first)) setTab("setup");
    else if (options.some((f) => segment(f.name) === first)) setTab("options");
    pending.current = focusField.pointer;
  }, [focusField?.n]);
  useEffect(() => {
    const pointer = pending.current;
    if (pointer === null) return;
    const frame = requestAnimationFrame(() => {
      pending.current = null;
      const holders = [...(aside.current?.querySelectorAll<HTMLElement>("[data-pointer]") ?? [])];
      const parts = pointer.split("/");
      for (let n = parts.length; n > 1; n--) {
        const holder = holders.find((el) => el.dataset.pointer === parts.slice(0, n).join("/"));
        const label = holder?.querySelector<HTMLLabelElement>("label[for]");
        const control = label ? document.getElementById(label.htmlFor) : null;
        const target =
          control && control.tagName !== "OUTPUT" && !(control as HTMLInputElement).disabled
            ? control
            : holder?.querySelector<HTMLElement>("button:not([disabled])");  // prettier-ignore
        if (target) return target.focus();
      }
      (document.getElementById("step-problems") ?? heading.current)?.focus();
    });
    return () => cancelAnimationFrame(frame);
  });
```

- add `const aside = useRef<HTMLElement>(null);` beside `heading`, and `ref={aside}` on the `<aside>`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test. 4b's "Go to" tests keep passing:
- the editor test only reads the button;
- the browser flows' transform problem names the whole config (`""`), so it still focuses the step.

- [ ] **Step 6: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): a problem's Go to opens its step's drawer at the field (4c-1, ruling 83)"
```

# Milestone 4: end to end

### Task 13: The browser flows, every check, the ledger and the checkpoint

**Files:**
- Create: `frontend/e2e/fixtures/references.dewpoint.json`
- Modify: `frontend/e2e/workflows.spec.ts`
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`

**Interfaces:**
- Consumes: the e2e helpers in `workflows.spec.ts` (`newWorkflow`, `importFile`, `tenantId`), `expectAccessible`
  from `e2e/gate.ts`, and the Mist connection "Acme Prod" that `foundations.spec.ts` creates (the `workflows`
  project depends on `foundations`; the connection is never verified, so nothing reaches Mist).

- [ ] **Step 1: Write the fixture**

Create `frontend/e2e/fixtures/references.dewpoint.json`:

```json
{
  "format": "dewpoint.workflow",
  "format_version": 1,
  "name": "References",
  "graph": {
    "graph_format": 1,
    "nodes": [
      {
        "id": "7a1d2c3e-0f4b-4c5d-8e6f-7a8b9c0d1e2f",
        "key": "fetch",
        "type": "flow.transform@1",
        "config": { "fields": { "n": { "$value": { "kind": "cel", "expr": "1" } } } },
        "position": { "x": 0, "y": 140 }
      },
      {
        "id": "8b2e3d4f-1a5c-4d6e-9f70-8b9c0d1e2f30",
        "key": "use",
        "type": "flow.transform@1",
        "config": {
          "fields": {
            "copy": { "$value": { "kind": "ref", "path": "steps.fetch.output.n" } },
            "twice": { "$value": { "kind": "cel", "expr": "steps.fetch.output.n * 2" } }
          }
        },
        "position": { "x": 0, "y": 280 }
      }
    ],
    "edges": [
      { "from": { "node": "7a1d2c3e-0f4b-4c5d-8e6f-7a8b9c0d1e2f", "port": "out" }, "to": { "node": "8b2e3d4f-1a5c-4d6e-9f70-8b9c0d1e2f30" } }
    ],
    "settings": { "input_schema": { "type": "object" } }
  },
  "bindings": []
}
```

- [ ] **Step 2: Write the browser flows**

Append to `frontend/e2e/workflows.spec.ts`:

```ts
test("a step is set up in its drawer: a formula, error handling, one undo step per field, under the CSP", async ({ page }) => {
  await newWorkflow(page, "Drawer flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.if@1/ }).click();
  await page.getByRole("button", { name: /^if, If/ }).click();
  const drawer = page.getByRole("complementary", { name: "if" });
  await expect(drawer.getByRole("tab", { name: "Setup" })).toHaveAttribute("aria-selected", "true");
  await drawer.getByLabel("Condition").fill("trigger.count > 2");
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  await expectAccessible(page, "editor: drawer, setup");
  await drawer.getByRole("button", { name: "On error: fail the run" }).click();
  await drawer.getByLabel("When it fails").selectOption("port");
  await expect(drawer.getByRole("button", { name: "Connect error to…" })).toBeVisible();
  await expectAccessible(page, "editor: drawer, error handling");
  await drawer.getByRole("heading", { name: "if" }).click(); // focus leaves the fields
  await page.keyboard.press("Control+z");
  await expect(drawer.getByRole("button", { name: "On error: fail the run" })).toBeVisible();
  await page.keyboard.press("Control+z");
  await expect(drawer.getByLabel("Condition")).toHaveValue(""); // the whole formula, one step
});

test("a switch's case keeps its edges when its port is renamed, and removing it asks first", async ({ page }) => {
  await newWorkflow(page, "Switch flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.switch@1/ }).click();
  await page.getByRole("button", { name: /^switch, Switch/ }).click();
  const drawer = page.getByRole("complementary", { name: "switch" });
  await drawer.getByRole("button", { name: "Add to Cases" }).click();
  const first = drawer.getByRole("group", { name: "Cases, item 1" });
  await first.getByLabel("When").fill("true");
  await page.getByRole("button", { name: "Add a step after switch (case_1)" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  await page.getByRole("button", { name: /^switch, Switch/ }).click();
  await first.getByLabel("Port").fill("big");
  await first.getByLabel("Port").press("Enter");
  await expect(page.getByRole("button", { name: "Insert a step between switch (big) and transform" })).toHaveCount(1);
  await expectAccessible(page, "editor: drawer, a switch's cases");
  await drawer.getByRole("button", { name: "Remove: Cases, item 1" }).click();
  const dialog = page.getByRole("dialog", { name: "Remove a port" });
  await expect(dialog).toContainText("The port big goes with this change, and its edge to transform is deleted.");
  await expectAccessible(page, "editor: removing a port");
  await dialog.getByRole("button", { name: "Remove" }).click();
  await expect(page.getByRole("button", { name: "Insert a step between switch (big) and transform" })).toHaveCount(0);
});

test("a renamed step keeps the references to it, and says which formulas still name it", async ({ page }) => {
  await importFile(page, "References", "e2e/fixtures/references.dewpoint.json");
  await page.getByRole("button", { name: /^fetch, Transform/ }).click();
  const fetch = page.getByRole("complementary", { name: "fetch" });
  await fetch.getByRole("button", { name: "Rename" }).click();
  await fetch.getByLabel("Key").fill("load");
  await fetch.getByLabel("Key").press("Enter");
  const load = page.getByRole("complementary", { name: "load" });
  await expect(load.getByRole("heading", { name: "load" })).toBeFocused();
  await expect(load.getByText("1 formula still names fetch: the problems show where.")).toBeVisible();
  await page.getByRole("button", { name: /^use, Transform/ }).click();
  const use = page.getByRole("complementary", { name: "use" });
  await expect(use.locator('[data-pointer="/fields/copy"] output')).toHaveText("steps.load.output.n");
  await expectAccessible(page, "editor: drawer, a reference and a map");
});

test("a problem's Go to opens its step's drawer on the field", async ({ page }) => {
  await newWorkflow(page, "Problem flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.delay@1/ }).click();
  await page.getByRole("button", { name: /^delay, Delay/ }).click();
  await page.getByRole("complementary", { name: "delay" }).getByLabel("Duration S").fill("-5");
  await expect(page.getByRole("button", { name: /^delay, Delay, 1 problem/ })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: /^Problems · 1$/ }).click();
  await page.getByRole("complementary", { name: "Problems" }).getByRole("button", { name: "Go to delay" }).click();
  await expect(page.getByRole("complementary", { name: "delay" }).getByLabel("Duration S")).toBeFocused();
});

test("a Mist step's connection is chosen from the tenant's, and its choices never load by themselves", async ({ page }) => {
  const options: string[] = [];
  page.on("request", (r) => {
    if (r.url().endsWith("/options")) options.push(r.url());
  });
  await newWorkflow(page, "Mist flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /mist\.site_devices\.list@1/ }).click();
  await page.getByRole("button", { name: /^list, / }).click();
  const drawer = page.getByRole("complementary", { name: "list" });
  await drawer.getByLabel("Connection").selectOption({ label: "Acme Prod · not verified yet" });
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  await expectAccessible(page, "editor: drawer, a connection");
  expect(options).toEqual([]);
});
```

- [ ] **Step 3: Run the browser gate**

Run the session's `compose-ui4a/e2e.sh` (about 6 minutes: it resets the isolated stack, plugins synced, and runs every
flow).
Expected:
- the new flows and every earlier one pass;
- no CSP violation and no axe violation;
- the notices list `@radix-ui/react-tabs`.

Where a label differs from this plan's, check it against the running app, fix the flow test-first, and record a
mid-slice ruling. These labels come from the app, not from this plan:
- the canvas's "+" names;
- the Mist step's key and title.

- [ ] **Step 4: Run every check**

From `frontend/`:
- `npx -y pnpm@12.6.0 test`
- `npx -y pnpm@12.6.0 lint`
- `npx -y pnpm@12.6.0 typecheck`
- `npx -y pnpm@12.6.0 check:api`
- `npx -y pnpm@12.6.0 build`
- `node scripts/licence-check.mjs --self-test`
- `npx -y pnpm@12.6.0 licenses list --json --prod | node scripts/licence-check.mjs prod`
- `npx -y pnpm@12.6.0 licenses list --json | node scripts/licence-check.mjs all`

Then local CodeQL on the branch's head: the session's `codeql/scan.sh <sha>` (about 40 seconds).
Expected: all pass, `check:api` reports no change, and CodeQL finds nothing new.

The backend is untouched, so its suite doesn't run (`git diff --stat origin/main -- backend` prints nothing).

- [ ] **Step 5: Bring the ledger up to date**

In `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`, after the last section:
- **`### Owner, 4c-1 plan (<date>, in chat)`**: the approval, with any amendments in the owner's words.
- **One section per milestone, `### 4c-1, milestone N (<date>)`**: each difference from this plan as a mid-slice
  ruling, `M41.` onward, in 4b's form: a bold statement, then why, then the test that pins it.
- **`### 4c-1, the final checkpoint (<date>)`**: the reviewer's findings and what was done with each.

This plan's rulings join the numbered list as 96 to 112 only when the owner accepts the slice, as 68 to 95 did.

- [ ] **Step 6: Commit**

```bash
git add frontend/e2e docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "test(e2e): the step drawer in the browser, under the CSP and axe; the ledger (4c-1)"
```

- [ ] **Step 7: The final checkpoint**

1. Dispatch a fresh reviewer on the most capable model with:
   - this plan;
   - the outline's §6;
   - the diff from `origin/main`;
   - its own scratch directory, and the rule that it deletes only its own files.
   It reviews:
   - the code against the plan;
   - the screens against 1c, with no AI tells;
   - accessibility;
   - the Review Focus list.
2. Fix what it finds, test-first, each as a mid-slice ruling.
3. Take the screenshots as at the milestone 2 pause, adding:
   - error handling;
   - the pickers;
   - a problem's field;
   - the rename.
   Put them in the session's checkpoint page.
4. Stop. Give the owner:
   - the summary;
   - the page;
   - the branch's head;
   - the checks' results, as they came out.

Nothing is pushed and no PR is opened without the owner's OK.

---

## Self-review

- **Spec coverage.**
  - Outline §2's 4c, for the drawer: rulings 2–6 (Tasks 5–7), the pickers (Tasks 8, 9), error handling (Task 10),
    rename (Task 11), a problem's field (Task 12).
  - D17 (saves and undo): Tasks 3 and 6.
  - D19 (formula mode, hints): Tasks 5 and 7.
  - D21–D24:
    - Tabs pinned and checked: Task 4;
    - the CSP in the browser: Tasks 6 and 13;
    - no Mist calls: Tasks 9 and 13;
    - AI tells: the guard in every task's suite run, and the checkpoint.
  - Data pills, the condition builder, samples, triggers and the Test tab are 4c-2, 4c-3 and 4d (ruling 1).
- **Placeholders.** None: every code step has its code. Where the running app decides a label (Task 13's "+" names
  and the Mist step's key), the step says how to check it and record the difference.
- **Names across tasks.**
  - `setConfig`, `setOptions`, `renamePort`, `freePort`, `keyProblem` and `renameKey` (Task 2) are the names Tasks 6,
    7, 10 and 11 call.
  - `record(h, next, mark)` (Task 3) is what `change` calls (Task 6).
  - `Drawer`, `useDrawer`, `useSession`, `problemsAt` and `segment` (Task 5) keep their signatures; Task 7 adds
    `renamePort`.
  - `ControlProps` (Task 5) is what every control takes (Tasks 7–9).
  - `StepDrawer` gains one prop per task (`onRenamePort` 7, `onOptions` 10, `onRename` 11, `focusField` 12), and the
    editor passes each.
- **Review Focus.** Each line names the tests that pin it, in their owning tasks: Tasks 2, 3, 5, 6, 7, 9, 10 and 11.
