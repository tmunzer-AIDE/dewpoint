# Editor UI 4c-1: the Step Drawer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 2 (2026-10-09).** For the owner's review. It answers the review of revision 1 (02fe8a6) pasted in chat on
2026-10-09; "Changes from revision 1" below says how. Nothing is built before the owner approves this plan. Nothing is
pushed and no PR is opened without the owner's OK in chat.

**Goal:** A person who may edit a workflow opens a step and sets it up in a drawer generated from its type's schema:
the required fields on Setup, the rest on Options, and its error handling in a chip. They choose connections,
workflows and live options, write formulas where the engine takes them, and rename the step. Every edit is saved like
any other and undone one field at a time. Text typed but not yet applied is never lost in silence. Every problem the
server finds shows at its field.

**Architecture:**
- **Pure layers first (milestone 1).**
  - `lib/schemaForm.ts` reads a type's config schema as a form. It gives each field's place (Setup or Options), label,
    widget and allowed kinds of value, by the engine's own markers. A schema that repeats itself, or nests too deep,
    stops at JSON.
  - `lib/config.ts` changes a step's config, options and key as documents, and checks a document against the graph's
    admission rules. A port a change removes takes its edges with it. A renamed key carries every structured
    reference along.
  - `lib/unapplied.ts` models text typed but not in the draft (JSON, a name, a number that doesn't parse), and
    applies it when it can.
  - `lib/history.ts` coalesces one field's typing into one undo step.
- **One field, the drawer, then what isn't applied (milestone 2).**
  - A field is a frame (label, control, hint, problems) around a control chosen by its widget, fixed or a formula.
  - The drawer replaces 4b's read-only step panel in the side column:
    - a header with the step's key, its type and the error-handling chip;
    - Setup and Options tabs (Radix Tabs, outline §4);
    - the 4b actions kept below.
  - The editor owns unapplied text. Its save state counts it. Its exits, publication, export and version view apply
    what they can, and ask about the rest.
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
  - `engine/graph/model.py`: the graph format a save checks, and `_admission_problems`;
  - `engine/graph/validate.py`: where a node's problems point;
  - `engine/registry/catalog.py`: `_schema_contract`, which keeps titles out of a type's contract.

## Changes from revision 1

Revision 2 answers each correction in the review pasted on 2026-10-09:
1. **Sensitive containers.**
   - A whole holding a sensitive part shows no default hint.
   - It is never offered as JSON.
   - Switching it to a formula starts the formula empty: a hidden value is never copied into one (rulings 6 and 15;
     Tasks 1 and 6).
2. **Unapplied edits.** These are text a control holds that isn't in the draft. A new ruling, 18, gives them an owner
   and a lifetime:
   - the editor keeps them, never the control;
   - its save state counts them;
   - tabs, toggles and a closed drawer keep them;
   - leaving, signing out, publishing, exporting and viewing a version apply what they can and ask about the rest;
   - a list's move or removal, a mode switch and a JSON toggle apply the edits beneath them first, or wait;
   - a canceled port question leaves its edit unapplied, said at its control.
   Tasks 3, 6, 7 and 8 carry it, and Tasks 9, 12 and 13 use it.
3. **Literal envelopes.** A `literal` envelope is edited as its payload and saved as a literal again: its kind changes
   only through Fixed/Formula, Replace or Clear (ruling 15; Tasks 3 and 6).
4. **Numbers and admission.**
   - JSON that parses to a number which isn't finite, or to a whole number past 2^53, is refused before it reaches
     the draft.
   - Every drawer write is checked against the graph's admission rules: nesting at most 64 deep, and at most 2,000
     references, templates and formulas (rulings 7 and 15; Tasks 2, 3 and 6).
5. **Bounded schemas and the unsupported mode.**
   - A schema that repeats itself, or a field more than 8 parts deep, is shown as JSON, or as a notice when it holds
     a sensitive part (ruling 5; Task 1).
   - A field taking only references or templates offers neither a fixed value nor a formula. It says it can't be set
     in this drawer (ruling 6; Task 6).
6. **Live choices.** Shown choices belong to their scope: tenant, type, field, and the connection's id and revision. A
   changed scope drops them, and an answer for an older scope is ignored. Another click is needed (ruling 14; Task 11).
7. **Rename.**
   - An open rename is disabled when the draft can't change.
   - A rename refused by the editor says so, and never succeeds by its shape.
   - The drawer no longer counts formulas "that name the old key". It says how many formulas *mention* the old key as
     a word, and only until the next edit (ruling 11; Tasks 2 and 13).
8. **Titles.** Ruling 4's versioning justification is withdrawn: `_schema_contract` drops titles from a type's contract
   (Spec, above). The drawer uses the titles as they are.

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
  - A sensitive field's fixed value is never shown. Nor is a default holding a sensitive part, nor a value holding
    one as JSON or as a formula made from it (ledger M25).
  - Logs name an exception's type only.
  - No secret in a URL, a log or browser storage. The client keeps no draft, no unapplied text and no sample in
    browser storage.
- **The API decides every write.**
  - The client hides what a role can't do, but never relies on hiding it.
  - The browser checks only required fields and types (D19), plus the graph format rules a save would refuse.
  - Every other rule is the server's.
- **Verify, don't remember.** Check every library API against the installed package before relying on it (Radix
  Tabs' parts and props in `node_modules/@radix-ui/react-tabs/dist/index.d.ts`), and every API path and body against
  `src/api/schema.d.ts`.
- **CI.** Every check runs locally first. Commits and PRs carry no skip marker (the owner, 2026-10-08), so CI and
  CodeQL run on every push of a PR branch. Nothing is pushed and no PR is opened without the owner's OK in chat.

## Review Focus

These are the inputs and conditions most likely to bite a person using this. Each is pinned by the tests named, in
the task that owns it.

- **A value the drawer can't edit, or mustn't show.**
  - The cases:
    - a reference or a template written elsewhere;
    - a type this server doesn't know;
    - a sensitive field's fixed value, or a whole holding a sensitive part;
    - a `literal` envelope, which holds data;
    - a field taking only references;
    - a schema that repeats itself.
  - Each is kept byte for byte until the person changes it on purpose, never changes kind on its own, and a sensitive
    value never shows.
  - Tests:
    - Task 1: `shows a schema that repeats itself, or one nested too deep, as JSON`, `hints no default that holds a
      sensitive part`;
    - Task 2: `keeps what it doesn't touch`;
    - Task 6: `shows a reference read only, and keeps it until it's replaced`, `never shows a sensitive field's fixed
      value`, `never shows a sensitive part as JSON, a default or a formula`, `edits a literal as its payload, and
      keeps it a literal`, `offers neither a fixed value nor a formula where the engine takes only references`;
    - Task 7: `keeps an unknown type's settings as they are`.
- **Text typed, then the person moves on.**
  - The cases:
    - a fast typist's undo;
    - a tab change, a JSON toggle, a closed drawer;
    - a list reordered under an unapplied edit;
    - a canceled port question;
    - leaving, signing out, publishing, exporting, viewing a version.
  - One undo step per field per focus. Nothing typed disappears without the person discarding it.
  - Tests:
    - Task 3: `keeps an edit that takes ports away for its question`;
    - Task 4: `makes one step of a field's edits while it keeps its mark`;
    - Task 6: `makes one mark of a field's typing while it keeps focus`, `keeps unapplied JSON through a change of
      view, applying what's valid first`;
    - Task 7: `makes a field's typing one undo step`, `keeps an unapplied edit when the tab changes or the drawer
      closes`;
    - Task 8: `applies what it can before publishing, and asks about the rest`, `asks before leaving with an edit it
      can't apply`;
    - Task 9: `moves an item only once the edits inside it are applied`.
- **Numbers and nesting the server would refuse or change.**
  - The cases: `1e400`, `9007199254740993`, nesting past 64 levels, more than 2,000 computed values.
  - Each is refused in the browser with its reason, before it can make a save fail or a value change.
  - Tests:
    - Task 2: `refuses a number JSON.parse would change`, `finds what the graph's format refuses`;
    - Task 6: `says a JSON number too large to keep, and keeps it out of the draft`.
- **An edit that removes a port with edges.**
  - The cases: a switch case removed, errors no longer routed to a port, a JSON edit.
  - It asks first, deletes exactly those edges, and one undo restores both. A case's port renamed in place keeps its
    edges.
  - Tests:
    - Task 2: `drops only the lost ports' edges`, `keeps a renamed case's edges`;
    - Task 7: `asks before an edit takes a port with edges away`, `undoes the edit and its edges together`;
    - Task 9: `renames a case's port in place, its edges following`, `asks before removing a case with edges`;
    - Task 12: `asks before errors stop going to a port`.
- **What changes under an open control.**
  - The cases:
    - the connection under shown choices;
    - the editor turning read only under an open rename;
    - formulas that mention a renamed key.
  - Choices from another scope never show; a refused rename never looks done; a word about formulas is said only
    while it's true.
  - Tests:
    - Task 2: `counts the formulas that mention it`;
    - Task 11: `never loads on render`, `asks for a connection before loading`, `drops choices when their connection
      changes, and ignores an answer for the old one`;
    - Task 13: `disables an open rename when the draft can't change, and never says it renamed`, `says which formulas
      mention the old key, until the next edit`.

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
     - the key, renamable (Task 13);
     - the type's title and reference, and how the step runs;
     - the error-handling chip (Task 12).
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
   - Titles are display annotations: `_schema_contract` keeps them out of a type's contract hash, so a plugin may
     improve one within a version.
   - The drawer shows the titles as the plugins write them ("Duration S").
   - Why: plugins own their wording. The cost: some labels read stiffly until their plugin improves them.
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
   - **The form is bounded.** A field whose `$ref` repeats one above it, or one more than 8 parts deep, is shown as
     JSON. One that holds a sensitive part shows a notice instead. A schema can't make the drawer expand forever.
   - Why: §3.3; D24. The cost: a deep or recursive value is edited as JSON.
6. **A value is fixed, or a formula, where the engine takes it.** These are the engine's own rules (`allowed_kinds`,
   `literal_on_path`, `contains_literal`, `sensitive.literal`):
   - A field whose path carries `x-dewpoint-literal` takes a fixed value only, and so does a whole that holds such a
     part (a switch's cases).
   - A field whose `x-dewpoint-kinds` lacks `literal` takes no fixed value; one whose kinds lack `cel` takes no
     formula.
   - A field marked `x-sensitive` takes no fixed value.
   - **A field that takes neither** (its kinds are only `ref` or `template`) offers neither. It shows its value read
     only and says it can't be set in this drawer.
   - Where both are allowed, a "Fixed / Formula" choice switches between them. A formula field, an untyped one or a
     JSON one starts as a formula.
   - Switching a fixed value to a formula writes the formula that gives it. When the value holds a sensitive part, the
     formula starts empty: a hidden value is never copied into visible text (M25).
   - A formula is the CEL formula mode of D19: a monospace text area, with the server's diagnostics and how it runs
     (inline, or as a separate step with the reason).
   - A reference or a template already in the draft shows read only, with "Replace with a fixed value" or "Replace
     with a formula", each offered only where its kind is allowed: editing those is 4c-2's pills.
   - A sensitive field holding a fixed value says so, never shows it, and offers to clear it or replace it with a
     formula (M25).
   - Why: D19. The cost: until 4c-2, references are typed as formulas.
7. **The browser checks only required fields, types, and what a save would refuse.**
   - A required field the person empties says "Required".
   - A number that doesn't parse says so and isn't saved, and so does JSON that doesn't parse. So does a number
     JSON.parse would change: one too large to be finite, or a whole number past 2^53.
   - These are checked before any write, since the graph's format refuses a draft that breaks them and it wouldn't be
     saved at all (4b ruling 9; `_admission_problems`):
     - a key, a port's name, and the attempts and timeout bounds;
     - finite numbers, nesting at most 64 levels, at most 2,000 references, templates and formulas.
   - The API's request size cap (`max_request_body_bytes`) is a deployment setting the browser doesn't know. A save
     it refuses shows in the toolbar as an unsaved edit, as in 4b.
   - Emptying a field removes it from the config, so its default applies. An optional field with a value offers
     "Clear", which also discards any unapplied text in it.
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
   - A canceled question leaves a JSON edit unapplied, its reason at its control (ruling 18).
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
    - Formulas aren't rewritten (CEL text isn't parsed here). After a rename, the drawer says how many formulas
      mention the old key as a word ("1 formula mentions fetch and keeps its text: check it"), until the next edit to
      the draft. It doesn't claim each is a reference, nor that the server flags each.
    - An open rename's controls are disabled while the draft can't change. A rename the editor refuses says so,
      never as if it had worked.
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
    - **Choices belong to their scope**: the tenant, the step's type, the field, and the connection's id and revision.
      When the scope changes, the shown choices go, an answer still on its way for the old scope is ignored, and
      another click is needed.
    - Why: an options call reaches the plugin's service (for Mist, Mist itself), so it is the person's act, never a
      side effect of opening a drawer (D24). The cost: one click, again after a change of connection.
15. **JSON is the value as the engine reads it.**
    - A `{"$value": …}` object in it is computed, as in an imported file, and its hint says so.
    - It applies when focus leaves.
    - "Edit as JSON" is offered on groups, lists and maps without a sensitive part. Untyped fields and unions are JSON
      always.
    - A map's entry can't be named `$value`: the engine would read the whole map as computed.
    - **A `literal` envelope stays a literal.** It's edited as its payload, its hint saying it's kept as data, and
      saved wrapped again. Its kind changes only through Fixed/Formula, Replace or Clear.
    - Why: D19; one reading of `$value` everywhere. The cost: none.
16. **A problem focuses its field** (ruling 83, the part that waited for 4c).
    - "Go to" on a problem whose field is inside the step opens the step's drawer on that field's tab and focuses the
      field: the closest one shown, for a pointer inside a list, a map or a JSON value.
    - A pointer no field shows lands on "Problems with this step", which lists it.
    - A problem about the step as a whole (no field, or its whole config) focuses the step, as in 4b.
    - Why: ruling 83. The cost: none.
17. **One new dependency, `@radix-ui/react-tabs` 1.1.21**, for the drawer's tabs, on the outline's approved list.
    - Its first browser check is at the end of Task 7, before lists, maps and pickers are built.
    - A CSP violation stops the work for the owner.
    - Why: D23. The cost: none.
18. **Unapplied edits are the editor's, never lost in silence.**
    - What counts: text a control holds that isn't in the draft. That is JSON being typed or refused; a map entry's
      name, a port's name or a key being typed or refused; a number or a limit that doesn't parse; a formula the
      graph's format refuses.
    - The editor keeps each, by its step, its field and its kind, never the control. A tab change, a JSON toggle, a
      closed and reopened drawer, or an undo keeps it. It shows at its control, with its reason and a "Discard".
    - The toolbar's save state counts them ("1 edit not applied") beside the draft's own state.
    - Leaving the editor (the router, sign-out, an ended session), publishing, exporting and viewing a version first
      apply every one that can be applied, as one undo step. Those that can't (refused, or taking ports away) are
      listed in a question: "Discard them and …" or "Go back to them". Leaving folds them into 4b's leave question.
    - A change to what holds an unapplied edit first applies the edits beneath it, as one step with the change: a
      list item's move or removal, a map entry's removal, Fixed/Formula, a JSON toggle. When one can't be applied,
      the change waits, and the edit's control says why.
    - Clear and deleting a step discard the unapplied edits beneath them, on purpose. The delete question says so.
    - Why: the review of revision 1; nothing a person typed disappears without their decision. The cost: one more
      state in the editor, and one more question at its exits.

## File Structure

New, in `frontend/src/`:
- `lib/schemaForm.ts`: a config schema read as a form: fields, widgets, kinds, pointers, tabs; bounded.
- `lib/config.ts`: values and envelopes; JSON text; admission; a step's config, options, ports and key changed as
  documents.
- `lib/unapplied.ts`: unapplied edits: what each is, and applying them.
- `components/Tabs.tsx`: the token-styled Radix Tabs.
- `routes/editor/drawer/context.ts`: what a drawer's fields share and may do; a field's problems; focus sessions.
- `routes/editor/drawer/FieldFrame.tsx`: a field's label, control, hint and problems; a group's fieldset.
- `routes/editor/drawer/scalars.tsx`: the controls for text, numbers, booleans, enums and JSON.
- `routes/editor/drawer/Formula.tsx`: the formula, the Fixed/Formula choice, a reference, a hidden sensitive value.
- `routes/editor/drawer/FieldView.tsx`: one field: its mode, its control, its problems, its unapplied edit.
- `routes/editor/drawer/structured.tsx`: groups, lists, maps, and a dynamic port's name.
- `routes/editor/drawer/StepDrawer.tsx`: the drawer.
- `routes/editor/drawer/ErrorHandling.tsx`: the chip's words and its section.
- `routes/editor/drawer/pickers.tsx`: the connection and workflow pickers.
- `routes/editor/drawer/LiveOptions.tsx`: options on request, in their scope.
- `routes/editor/drawer/KeyField.tsx`: the header's rename.
- `routes/editor/drawer/harness.tsx`: fields on their own, for tests only.
- `test/nodeTypes.ts`: node types for tests: the flow plugin's schemas and a made-up service's.
- Tests beside each: `*.test.ts(x)`.

New, in `frontend/e2e/fixtures/`: `references.dewpoint.json`.

Changed:
- `lib/history.ts`: `record` with a coalescing mark.
- `components/Field.tsx`: `controlClass` exported.
- `routes/editor/Editor.tsx`:
  - `change` with a mark, silent, saying whether it landed;
  - the drawer in place of `StepPanel`, with its actions;
  - unapplied edits, through its exits, publication, export and version view;
  - edits that drop edges ask first;
  - a problem's field.
- `routes/editor/SaveState.tsx`: the count of unapplied edits.
- `routes/editor/ProblemsPanel.tsx`: "Go to" passes the field.
- `routes/editor/StepPanel.tsx`: removed, its parts moved into the drawer.
- Tests: `routes/editor/Editor.test.tsx`, `routes/editor/ProblemsPanel.test.tsx`.
- Browser flows: `e2e/workflows.spec.ts`, and `e2e/gate.spec.ts` (the notices list Radix Tabs).
- `package.json` and `pnpm-lock.yaml`.
- `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md`.

## Milestones

- **Milestone 1 (Tasks 1–4): the pure layers.** No screen changes.
- **Milestone 2 (Tasks 5–9): Tabs, one field, the drawer, unapplied edits, lists and maps.** **Pause:** screenshots
  of the drawer beside 1c, light and dark, at 1280 and 320 px, for the owner's review before references and behaviour
  are built.
- **Milestone 3 (Tasks 10–14): pickers, live options, error handling, key rename, a problem's field.**
- **Milestone 4 (Task 15): end to end, every check, the ledger, the final checkpoint.** **Pause:** a fresh reviewer,
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
    kinds: Kind[] | null; sensitive; untyped; port; cut; refs: string[] }` (booleans unless typed). `cut`: shown as
    JSON, its schema repeating itself or nested more than 8 parts deep (ruling 5).
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

  it("hints no default that holds a sensitive part", () => {
    const holder = typeWith({
      type: "object",
      properties: { auth: { type: "object", default: { key: "s3cr3t" }, properties: { key: { type: "string", "x-sensitive": true } } } },
    });  // prettier-ignore
    expect(fieldsOf(holder)[0]!.hint).toBeNull();
  });

  it("shows a schema that repeats itself, or one nested too deep, as JSON", () => {
    const tree = typeWith({
      $defs: { Node: { type: "object", properties: { name: { type: "string" }, child: { $ref: "#/$defs/Node" } } } },
      type: "object", properties: { root: { $ref: "#/$defs/Node" } },
    });  // prettier-ignore
    const root = fieldsOf(tree)[0]!;
    expect([root.widget, root.cut]).toEqual(["group", false]);
    const child = propertiesOf(root).find((f) => f.name === "child")!;
    expect([child.widget, child.base, child.cut]).toEqual(["json", "json", true]); // never a group within a group within…
    const nest = (n: number): Record<string, unknown> => (n === 0 ? { type: "string" } : { type: "object", properties: { x: nest(n - 1) } });
    let deep = fieldsOf(typeWith({ type: "object", properties: { a: nest(9) } }))[0]!;
    for (let i = 0; i < 7; i++) deep = propertiesOf(deep)[0]!;
    expect([deep.path.length, deep.cut]).toEqual([8, false]);
    expect(propertiesOf(deep)[0]!.cut).toBe(true); // the 9th part down
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

  it("takes neither a fixed value nor a formula where the engine takes only references", () => {
    const source = fieldsOf(typeWith({ type: "object", properties: { source: { type: "string", "x-dewpoint-kinds": ["ref", "template"] } } }))[0]!;
    expect([canFixed(source), canFormula(source)]).toEqual([false, false]);
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
  cut: boolean; // shown as JSON: its `$ref` repeats one above it, or it's more than 8 parts deep (ruling 5)
  refs: string[]; // the `$ref`s followed down to it: what makes a repetition visible
}

const KINDS: ReadonlySet<string> = new Set(["literal", "ref", "template", "cel"]);
const BLANK_IS_TEXT: ReadonlySet<Widget> = new Set(["text", "datetime", "enum", "options"]);
const DATE_TIME = "A date and time in ISO 8601, like 2026-10-08T09:00:00Z.";
const MAX_FORM_DEPTH = 8; // a field further down is shown as JSON: no schema can make the form expand forever

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

function hintOf(s: Schema, widget: Widget, holdsSensitive: boolean): string | null {
  const parts: string[] = [];
  if (typeof s.description === "string" && s.description.trim() !== "") parts.push(s.description.trim());
  if (widget === "datetime") parts.push(DATE_TIME);
  // A default is said, unless it is or holds a sensitive value (ledger M25: a secret is never repeated).
  if (!holdsSensitive && s.default !== undefined && s.default !== null) {
    parts.push(`If empty: ${typeof s.default === "string" ? s.default : JSON.stringify(s.default)}.`);
  }
  return parts.length > 0 ? parts.join(" ") : null;
}

function make(
  type: NodeType, root: Schema, name: string, path: Path, raw: unknown, required: boolean, entry: boolean,
  literalAbove: boolean, refsAbove: string[],
): FieldSpec {  // prettier-ignore
  const own = isObject(raw) ? raw : {};
  const ref = typeof own.$ref === "string" ? own.$ref : null;
  const cut = (ref !== null && refsAbove.includes(ref)) || path.length > MAX_FORM_DEPTH;
  const schema = deref(own, root);
  const widget = cut ? "json" : widgetOf(schema, name, path.length === 1, type);
  const sensitive = own["x-sensitive"] === true || schema["x-sensitive"] === true;
  const holdsSensitive = holds("x-sensitive", own, root);
  const kinds = own["x-dewpoint-kinds"] ?? schema["x-dewpoint-kinds"];
  return {
    name, path, pointer: pointerOf(path), schema, root, type,
    label: typeof schema.title === "string" && schema.title.trim() !== "" ? schema.title : name,
    hint: hintOf(schema, widget, holdsSensitive),
    required, entry, widget, base: cut ? "json" : byType(schema),
    literalOnly: literalAbove || own["x-dewpoint-literal"] === true || schema["x-dewpoint-literal"] === true,
    holdsLiteral: holds("x-dewpoint-literal", own, root),
    holdsSensitive,
    kinds: Array.isArray(kinds) ? (kinds as unknown[]).filter((k): k is Kind => typeof k === "string" && KINDS.has(k)) : null,
    sensitive,
    untyped: !["type", "enum", "const", "properties", "items"].some((k) => k in schema),
    port: type.dynamic_ports !== null && path.length === 3 && path[0] === type.dynamic_ports && typeof path[1] === "number" && path[2] === "port",
    cut,
    refs: ref === null ? refsAbove : [...refsAbove, ref],
  };  // prettier-ignore
}

function propertiesIn(type: NodeType, root: Schema, schema: Schema, base: Path, literalAbove: boolean, refs: string[]): FieldSpec[] {
  const props = isObject(schema.properties) ? schema.properties : {};
  const required = Array.isArray(schema.required) ? (schema.required as unknown[]) : [];
  return Object.entries(props).map(([name, raw]) =>
    make(type, root, name, [...base, name], raw, required.includes(name), false, literalAbove, refs),
  );
}

/** A type's settings: its config schema's top-level properties, in the schema's order. */
export function fieldsOf(type: NodeType): FieldSpec[] {
  const root = isObject(type.config_schema) ? type.config_schema : {};
  return propertiesIn(type, root, deref(root, root), [], false, []);
}

/** A group's parts: its properties. */
export const propertiesOf = (f: FieldSpec): FieldSpec[] =>
  f.cut ? [] : propertiesIn(f.type, f.root, f.schema, f.path, f.literalOnly, f.refs);

/** A list's item, labelled by its place ("Cases, item 1"). */
export const itemOf = (f: FieldSpec, index: number): FieldSpec => ({
  ...make(f.type, f.root, String(index), [...f.path, index], f.schema.items, true, true, f.literalOnly, f.refs),
  label: `${f.label}, item ${index + 1}`,
});

/** A map's entry: its value takes the map's `additionalProperties`, or any JSON. */
export const entryOf = (f: FieldSpec, name: string): FieldSpec =>
  make(f.type, f.root, name, [...f.path, name], isObject(f.schema.additionalProperties) ? f.schema.additionalProperties : {}, true, true, f.literalOnly, f.refs);  // prettier-ignore

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
Expected: PASS, 16 tests.

- [ ] **Step 6: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/schemaForm.ts frontend/src/lib/schemaForm.test.ts frontend/src/test/nodeTypes.ts
git commit -m "feat(editor): read a step type's config schema as a form (4c-1)"
```

### Task 2: A step's values, JSON text, admission, config, options and key as documents

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
    - `formula(expr: string)`, `literal(value)`, `formulaOf(value): string`, `fixedOf(value): unknown`,
      `referenceText(value): string`, `isPlainRef(value): boolean`.
  - JSON text and admission (ruling 7):
    - `parseJson(text): { value: unknown } | { problem: string }`: empty text is `{ value: undefined }`;
    - `MAX_DEPTH = 64`, `MAX_VALUES = 2_000`, `admission(doc: GraphDoc): string | null`, the server's
      `_admission_problems` mirrored.
  - Paths: `valueAt(root, path: Path): unknown`, `setAt(root, path: Path, value): unknown`. An undefined value
    removes a property or splices a list's item.
  - Changes:
    - `interface Changed { doc: GraphDoc; dropped: GraphEdge[] }`;
    - `type StepOptions = NonNullable<GraphNode["options"]>`;
    - `setConfig(doc, nodeId, path, value, type: NodeType | undefined): Changed`;
    - `setOptions(doc, nodeId, options: StepOptions, type: NodeType | undefined): Changed`;
    - `renamePort(doc, nodeId, index: number, name: string, type: NodeType): { doc: GraphDoc } | { problem: string }`;
    - `renameEntry(doc, nodeId, path: Path, from: string, to: string): { doc: GraphDoc } | { problem: string }`;
    - `freePort(node: GraphNode, type: NodeType): string`.
  - Keys: `keyProblem(doc, nodeId, key): string | null`, `renameKey(doc, nodeId, key): { doc: GraphDoc; mentions:
    number }`: `mentions` counts the formulas whose text mentions the old key as a word (ruling 11).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/config.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { IF, SWITCH } from "../test/nodeTypes";
import {
  CEL_WORDS, admission, fixedOf, formula, formulaOf, freePort, isPlainRef, keyProblem, kindOf, parseJson, referenceText,
  renameEntry, renameKey, renamePort, setAt, setConfig, setOptions, valueAt,
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

describe("JSON text", () => {
  it("refuses a number JSON.parse would change", () => {
    expect(parseJson('{"n": 1e400}')).toEqual({ problem: "A number here is too large to keep, so it isn't saved." });
    expect(parseJson("[9007199254740993]")).toEqual({
      problem: "A whole number here is too large to keep exactly, so it isn't saved.",
    });
    // A string's digits, the largest safe whole number and an exponent are kept as they are.
    expect(parseJson('{"id": "9007199254740993", "n": 9007199254740991, "x": 1.5e3}')).toEqual({
      value: { id: "9007199254740993", n: 9007199254740991, x: 1500 },
    });
    expect(parseJson("{")).toEqual({ problem: "This isn't valid JSON, so it isn't saved." });
    expect(parseJson("  ")).toEqual({ value: undefined });
  });

  it("finds what the graph's format refuses", () => { // nesting past 64 levels, more than 2,000 computed values
    const nested = (n: number): unknown => (n === 0 ? 1 : [nested(n - 1)]);
    const holding = (value: unknown): GraphDoc => ({
      graph_format: 1,
      nodes: [{ id: A, key: "a", type: "flow.transform@1", config: { fields: { x: value } } }],
    });
    // The graph is level 1, its nodes 2, a node 3, its config 4, `fields` 5: `x`'s arrays start at 6.
    expect(admission(holding(nested(59)))).toBeNull();
    expect(admission(holding(nested(60)))).toBe("Values can be nested at most 64 levels deep.");
    const many = Object.fromEntries(Array.from({ length: 2001 }, (_, i) => [`f${i}`, formula("1")]));
    expect(admission(holding(many))).toBe("A workflow can hold at most 2,000 references, templates and formulas.");
    expect(admission(holding(Number.POSITIVE_INFINITY))).toBe("A number in the draft isn't finite, so it couldn't be saved.");
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

  it("renames a map's entry in place, never to $value, an empty name or a taken one", () => {
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [{ id: A, key: "t", type: "flow.transform@1", config: { fields: { x: 1, y: 2 } } }],
    };
    const renamed = renameEntry(doc, A, ["fields"], "x", "constructor"); // a name, not Object's own
    if ("problem" in renamed) throw new Error(renamed.problem);
    expect(Object.entries(renamed.doc.nodes![0]!.config!.fields as object)).toEqual([["constructor", 1], ["y", 2]]);
    expect(renameEntry(doc, A, ["fields"], "x", "$value")).toEqual({
      problem: "A name can't be $value: the engine would read the whole value as computed.",
    });
    expect(renameEntry(doc, A, ["fields"], "x", "")).toEqual({ problem: "A name can't be empty." });
    expect(renameEntry(doc, A, ["fields"], "x", "y")).toEqual({ problem: "There's already one called y." });
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

  it("counts the formulas that mention it", () => {
    // A mention, not a reference: CEL isn't parsed here, so `steps["pick"]` and the text "pick" count, `picker` doesn't.
    const doc: GraphDoc = {
      graph_format: 1,
      nodes: [
        { id: A, key: "pick", type: "flow.if@1" },
        { id: B, key: "x", type: "flow.if@1", config: { condition: formula("steps.pick.output.n > 1 && loops.pick.index == 0") } },
        { id: C, key: "y", type: "flow.if@1", config: { condition: formula('steps["pick"].output == "pick"') } },
        { id: "00000000-0000-4000-8000-00000000000d", key: "z", type: "flow.if@1", config: { condition: formula("steps.picker.output") } },
      ],
    };  // prettier-ignore
    expect(renameKey(doc, A, "route").mentions).toBe(2);
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
/** A fixed value written the long way: data, whatever it holds, `$value` included (ruling 15). */
export const literal = (value: unknown) => ({ [ENVELOPE]: { kind: "literal", value } });

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

/** Whole numbers past 2^53 in JSON text, outside strings: JSON.parse rounds them, so what's saved would differ from
 * what was typed. */
function roundsAWholeNumber(text: string): boolean {
  const number = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!;
    if (c === '"') {
      for (i++; i < text.length && text[i] !== '"'; i++) if (text[i] === "\\") i++;
    } else if (c === "-" || (c >= "0" && c <= "9")) {
      number.lastIndex = i;
      const token = number.exec(text)?.[0];
      if (!token) continue;
      if (!/[.eE]/.test(token) && !Number.isSafeInteger(Number(token))) return true;
      i += token.length - 1;
    }
  }
  return false;
}

/** Whether a value holds a number that isn't finite: what JSON.parse makes of `1e400`. */
function holdsNonFinite(value: unknown): boolean {
  const stack = [value];
  while (stack.length > 0) {
    const at = stack.pop();
    if (typeof at === "number" && !Number.isFinite(at)) return true;
    if (Array.isArray(at)) stack.push(...(at as unknown[]));
    else if (isObject(at)) stack.push(...Object.values(at));
  }
  return false;
}

/** JSON text as a value the draft can keep (rulings 7 and 15): refused when it doesn't parse, or when parsing would
 * change a number, as the server stores numbers exactly. Empty text is no value. */
export function parseJson(text: string): { value: unknown } | { problem: string } {
  if (text.trim() === "") return { value: undefined };
  let value: unknown;
  try {
    value = JSON.parse(text) as unknown;
  } catch {
    return { problem: "This isn't valid JSON, so it isn't saved." };
  }
  if (holdsNonFinite(value)) return { problem: "A number here is too large to keep, so it isn't saved." };
  if (roundsAWholeNumber(text)) return { problem: "A whole number here is too large to keep exactly, so it isn't saved." };
  return { value };
}

export const MAX_DEPTH = 64; // engine/graph/model.py: containers nested from the graph down, the graph being level 1
export const MAX_VALUES = 2_000; // and its envelopes: references, templates, formulas, literals

/** Why the graph's format would refuse the document (engine/graph/model.py's `_admission_problems`), or null: a
 * number that isn't finite, a container nested past 64 levels, more than 2,000 envelopes. The save would fail whole,
 * so the drawer writes nothing that breaks them (ruling 7). */
export function admission(doc: GraphDoc): string | null {
  let values = 0;
  const stack: [unknown, number][] = [[doc, 1]];
  while (stack.length > 0) {
    const [value, depth] = stack.pop()!;
    if (typeof value === "number" && !Number.isFinite(value)) return "A number in the draft isn't finite, so it couldn't be saved.";
    if (typeof value !== "object" || value === null) continue;
    if (depth > MAX_DEPTH) return `Values can be nested at most ${MAX_DEPTH} levels deep.`;
    if (Array.isArray(value)) {
      for (const item of value as unknown[]) stack.push([item, depth + 1]);
    } else {
      if (ENVELOPE in value) values++;
      for (const item of Object.values(value)) stack.push([item, depth + 1]);
    }
  }
  return values > MAX_VALUES ? "A workflow can hold at most 2,000 references, templates and formulas." : null;
}

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

/** A map's entry renamed in place, keeping its order; refused, with the reason, when the name is empty, `$value`
 * (ruling 15) or another entry's. */
export function renameEntry(doc: GraphDoc, nodeId: string, path: Path, from: string, to: string): { doc: GraphDoc } | { problem: string } {
  const node = findNode(doc, nodeId);
  const map = node ? valueAt(node.config ?? {}, path) : undefined;
  if (!node || !isObject(map) || from === to) return { doc };
  if (to === "") return { problem: "A name can't be empty." };
  if (to === ENVELOPE) return { problem: "A name can't be $value: the engine would read the whole value as computed." };
  if (Object.hasOwn(map, to)) return { problem: `There's already one called ${to}.` };
  const renamed = Object.fromEntries(Object.entries(map).map(([k, v]) => [k === from ? to : k, v]));
  return { doc: withNode(doc, nodeId, { ...node, config: setAt(node.config ?? {}, path, renamed) as Record<string, unknown> }) };
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
 * and the workflow's outputs. Formulas aren't parsed here: they keep their text, and `mentions` counts those whose
 * text mentions the old key as a word, a reference or not (ruling 11). A fixed value's data is data, never
 * rewritten. */
export function renameKey(doc: GraphDoc, nodeId: string, key: string): { doc: GraphDoc; mentions: number } {
  const node = findNode(doc, nodeId);
  if (!node || node.key === key) return { doc, mentions: 0 };
  const old = node.key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const path = new RegExp(`^((?:steps|loops)\\.)${old}(?=$|[.[])`);
  const mentioned = new RegExp(`(?<![\\w$])${old}(?![\\w$])`);
  let mentions = 0;
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
      if (typeof body.expr === "string" && mentioned.test(body.expr)) mentions++;
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
  return { doc: { ...doc, nodes, ...(settings ? { settings } : {}) }, mentions };
}
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/config.test.ts`
Expected: PASS, 19 tests.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/config.ts frontend/src/lib/config.test.ts
git commit -m "feat(editor): a step's config, options and key as documents, checked against the graph's admission (4c-1)"
```

### Task 3: Edits not applied yet, as data

**Files:**
- Create: `frontend/src/lib/unapplied.ts`
- Test: `frontend/src/lib/unapplied.test.ts`

**Interfaces:**
- Consumes:
  - from Task 1: `Path`;
  - from Task 2: `admission`, `formula`, `literal`, `parseJson`, `keyProblem`, `renameKey`, `renamePort`, `renameEntry`,
    `setConfig`, `setOptions`, `Changed`;
  - from `lib/graph.ts`: `findNode`, `idKey`, `portOf`, `sameId`.
- Produces, from `lib/unapplied.ts` (ruling 18):
  - Types:
    - `type UnappliedKind = "json" | "number" | "formula" | "port" | "name" | "key" | "limit"`;
    - `interface Unapplied { id; node; kind; pointer; path: Path; label; text; why: string | null; entry?; literal?;
      whole?; from? }`;
    - `type Holding = Omit<Unapplied, "id" | "node" | "kind" | "pointer">`: what a control supplies;
    - `interface Applied extends Changed { said: string | null; note: string | null }`;
    - `type Limit = "max_attempts" | "timeout_s"`.
  - Functions:
    - `unappliedId(node, kind, pointer): string`;
    - `within(node, pointer): (u: Unapplied) => boolean`: a part and what's below it; `""` is the whole step;
    - `parseNumber(text, whole): { value: number | undefined } | { problem: string }`;
    - `limitProblem(name: Limit, text: string): string | null`: empty text is the type's default, so null;
    - `applyUnapplied(doc, u, type): Applied | { problem: string }`;
    - `applyAll(doc, held: Iterable<Unapplied>, typeOf: (node: GraphNode) => NodeType | undefined, take: (u) =>
      boolean): { doc; applied: Unapplied[]; left: Unapplied[]; note: string | null }`;
    - `droppedWhy(dropped: GraphEdge[], doc): string`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/lib/unapplied.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { IF, SWITCH, TRANSFORM } from "../test/nodeTypes";
import { formula, literal } from "./config";
import type { Path } from "./schemaForm";
import {
  applyAll, applyUnapplied, parseNumber, unappliedId, within, type Unapplied, type UnappliedKind,
} from "./unapplied";  // prettier-ignore
import type { GraphDoc, GraphNode, NodeType } from "./workflows";

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const TYPES: Record<string, NodeType> = { "flow.switch@1": SWITCH, "flow.if@1": IF, "flow.transform@1": TRANSFORM };
const typeOf = (n: GraphNode) => TYPES[n.type];

/** An edit held for step A. */
const held = (kind: UnappliedKind, pointer: string, path: Path, text: string, more: Partial<Unapplied> = {}): Unapplied => ({
  id: unappliedId(A, kind, pointer), node: A, kind, pointer, path, label: pointer, text, why: null, ...more,
});  // prettier-ignore
/** Step A, `fetch`, a transform with this config. */
const fetch = (config: Record<string, unknown>): GraphDoc => ({
  graph_format: 1,
  nodes: [{ id: A, key: "fetch", type: "flow.transform@1", config }],
});

const applied = (result: ReturnType<typeof applyUnapplied>) => {
  if ("problem" in result) throw new Error(result.problem);
  return result;
};

it("keeps a number exactly as typed, or says why not", () => {
  expect(parseNumber("2.", false)).toEqual({ value: 2 });
  expect(parseNumber(" ", false)).toEqual({ value: undefined });
  expect(parseNumber("2.5", true)).toEqual({ problem: "A whole number, like 42." });
  expect(parseNumber("1x", false)).toEqual({ problem: "A number, like 42 or 2.5." });
  expect(parseNumber("1e400", false)).toEqual({ problem: "A number this large can't be kept." });
  expect(parseNumber("9007199254740993", true)).toEqual({ problem: "A whole number this large can't be kept exactly." });
});

it("applies JSON, and keeps a literal envelope a literal", () => {
  const text = '{"x": {"$value": {"kind": "ref", "path": "trigger.x"}}}';
  const result = applied(applyUnapplied(fetch({}), held("json", "/fields", ["fields"], text, { literal: true }), TRANSFORM));
  expect(result.doc.nodes![0]!.config).toEqual({ fields: literal({ x: { $value: { kind: "ref", path: "trigger.x" } } }) });
  expect(result.said).toBeNull(); // a field's own edit is never announced (ruling 8)
});

it("refuses what the graph's format would, with its reason", () => {
  expect(applyUnapplied(fetch({}), held("json", "/fields", ["fields"], '{"n": 1e400}'), TRANSFORM)).toEqual({
    problem: "A number here is too large to keep, so it isn't saved.",
  });
  const crowded = fetch({ fields: Object.fromEntries(Array.from({ length: 2000 }, (_, i) => [`f${i}`, formula("1")])) });
  expect(applyUnapplied(crowded, held("formula", "/fields/more", ["fields", "more"], "2"), TRANSFORM)).toEqual({
    problem: "A workflow can hold at most 2,000 references, templates and formulas.",
  });
  expect(applyUnapplied(fetch({}), held("limit", "/options/max_attempts", ["max_attempts"], "25"), TRANSFORM)).toEqual({
    problem: "A whole number from 1 to 20.",
  });
});

it("renames a key, saying which formulas mention the old one", () => {
  const doc: GraphDoc = {
    graph_format: 1,
    nodes: [
      { id: A, key: "fetch", type: "flow.transform@1" },
      { id: B, key: "use", type: "flow.if@1", config: { condition: formula("steps.fetch.output.n > 1") } },
    ],
  };  // prettier-ignore
  const result = applied(applyUnapplied(doc, held("key", "", [], "load"), TRANSFORM));
  expect(result.doc.nodes![0]!.key).toBe("load");
  expect(result.note).toBe("1 formula mentions fetch and keeps its text: check it.");
  expect(result.said).toBe("Renamed fetch to load. 1 formula mentions fetch and keeps its text: check it.");
  expect(applyUnapplied(doc, held("key", "", [], "use"), TRANSFORM)).toEqual({ problem: "Another step is already called use." });
});

it("keeps an edit that takes ports away for its question", () => {
  const doc: GraphDoc = {
    graph_format: 1,
    nodes: [
      { id: A, key: "pick", type: "flow.switch@1", config: { cases: [{ port: "a", when: formula("true") }, { port: "b", when: formula("false") }] } },
      { id: B, key: "right", type: "flow.transform@1" },
    ],
    edges: [{ from: { node: A, port: "b" }, to: { node: B } }],
  };  // prettier-ignore
  const cut = held("json", "/cases", ["cases"], '[{"port": "a", "when": {"$value": {"kind": "cel", "expr": "true"}}}]');
  const { doc: next, applied: done, left } = applyAll(doc, [cut], typeOf, () => true);
  expect(next).toBe(doc);
  expect(done).toEqual([]);
  expect(left.map((u) => u.why)).toEqual(["Not applied: it removes the port b and its edge to right."]);
});

it("applies each held edit in turn, as one document, and keeps those it can't", () => {
  const edits = [
    held("number", "/n", ["n"], "12", { whole: true }),
    held("number", "/m", ["m"], "1x"),
    held("limit", "/options/max_attempts", ["max_attempts"], "5"),
  ];
  const { doc: next, applied: done, left } = applyAll(fetch({}), edits, typeOf, () => true);
  expect(next.nodes![0]).toMatchObject({ config: { n: 12 }, options: { max_attempts: 5 } });
  expect(done.map((u) => u.pointer)).toEqual(["/n", "/options/max_attempts"]);
  expect(left.map((u) => [u.pointer, u.why])).toEqual([["/m", "A number, like 42 or 2.5."]]);
});

describe("which edits a change covers", () => {
  it("covers a part and what's below it, never a sibling that shares its prefix", () => {
    const at = (pointer: string) => held("json", pointer, [], "");
    expect([at("/fields"), at("/fields/x"), at("/fieldsx")].map(within(A, "/fields"))).toEqual([true, true, false]);
    expect(within(B, "/fields")(at("/fields"))).toBe(false);
    expect(within(A, "")(held("key", "", [], "load"))).toBe(true); // the whole step: a deletion's
  });

  it("says when an edit's step is gone", () => {
    expect(applyUnapplied(fetch({}), { ...held("json", "/x", ["x"], "1"), node: B }, TRANSFORM)).toEqual({
      problem: "Its step is no longer in the draft.",
    });
  });
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/unapplied.test.ts`
Expected: FAIL. The module `./unapplied` doesn't exist.

- [ ] **Step 3: Write the module**

Create `frontend/src/lib/unapplied.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// Edits typed but not yet in the draft (4c-1, ruling 18): JSON being typed or refused; a map entry's, a port's or the
// key's name; a number or a limit that doesn't parse; a formula the graph's format refuses. The editor keeps them,
// never the control, so a tab, a toggle or a closed drawer can't lose them. Each is applied when it can be, and said,
// with its reason, while it can't.
import {
  admission, formula, keyProblem, literal, parseJson, renameEntry, renameKey, renamePort, setConfig, setOptions,
  type Changed,
} from "./config";  // prettier-ignore
import { findNode, idKey, portOf, sameId } from "./graph";
import type { Path } from "./schemaForm";
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";

export type UnappliedKind = "json" | "number" | "formula" | "port" | "name" | "key" | "limit";

export interface Unapplied {
  id: string; // unappliedId(node, kind, pointer)
  node: string; // the step's id, as the draft writes it
  kind: UnappliedKind;
  pointer: string; // where it goes: in the step's config; "/options/<name>" for a limit; "" for the key
  path: Path; // the same as a path: a limit's is [its name]; a name's is its map's; the key's is []
  label: string; // the field's label, for the question that lists it
  text: string;
  why: string | null; // why it isn't in the draft; null while it's being typed
  entry?: boolean; // emptied, a list's item or a map's entry blanks to null rather than going
  literal?: boolean; // its value is a `literal` envelope's payload, written back as one (ruling 15)
  whole?: boolean; // a number: whole
  from?: string; // a map entry's name in the draft
}

/** What a control supplies; the editor adds its step, its kind and where it goes. */
export type Holding = Omit<Unapplied, "id" | "node" | "kind" | "pointer">;

export interface Applied extends Changed {
  said: string | null; // what to announce: a field's own edit says nothing (ruling 8)
  note: string | null; // what the drawer says after it, until the next edit: a rename's formulas (ruling 11)
}

export const unappliedId = (node: string, kind: UnappliedKind, pointer: string): string => `${idKey(node)}|${kind}|${pointer}`;

/** The edits of a step at a part and below it: what a change to that part applies first. "" is the whole step. */
export const within = (node: string, pointer: string) => (u: Unapplied): boolean =>
  sameId(u.node, node) && (pointer === "" || u.pointer === pointer || u.pointer.startsWith(`${pointer}/`));

/** A number typed (rulings 7 and 18). What the draft keeps must be what was typed: never an infinity, never a whole
 * number rounded past 2^53. Empty text is no value. */
export function parseNumber(text: string, whole: boolean): { value: number | undefined } | { problem: string } {
  const t = text.trim();
  if (t === "") return { value: undefined };
  const n = Number(t);
  if (Number.isNaN(n) || (whole && Number.isFinite(n) && !Number.isInteger(n))) {
    return { problem: whole ? "A whole number, like 42." : "A number, like 42 or 2.5." };
  }
  if (!Number.isFinite(n)) return { problem: "A number this large can't be kept." };
  if (/^-?\d+$/.test(t) && !Number.isSafeInteger(n)) return { problem: "A whole number this large can't be kept exactly." };
  return { value: n };
}

/** The graph's bounds on a step's own limits (engine/graph/model.py's Options): a draft breaking one isn't saved. */
const LIMITS = {
  max_attempts: { ok: (n: number) => Number.isInteger(n) && n >= 1 && n <= 20, problem: "A whole number from 1 to 20." },
  timeout_s: { ok: (n: number) => n > 0 && n <= 86_400, problem: "A number of seconds above 0, up to 86,400." },
} as const;
export type Limit = keyof typeof LIMITS;

/** Why a limit's text isn't one the graph takes, or null: empty text leaves it to the type's default. */
export function limitProblem(name: Limit, text: string): string | null {
  const parsed = parseNumber(text, false);
  if ("problem" in parsed) return LIMITS[name].problem;
  return parsed.value === undefined || LIMITS[name].ok(parsed.value) ? null : LIMITS[name].problem;
}

/** A typed value as the draft writes it: emptied, it goes, or blanks in a list or a map; a literal's payload is wrapped
 * again (ruling 15). */
function written(value: unknown, u: Unapplied): unknown {
  if (value === undefined) return u.entry ? null : undefined;
  return u.literal ? literal(value) : value;
}

const quiet = (changed: Changed | { problem: string }): Applied | { problem: string } =>
  "problem" in changed ? changed : { ...changed, said: null, note: null };

function attempt(doc: GraphDoc, node: GraphNode, u: Unapplied, type: NodeType | undefined): Applied | { problem: string } {
  switch (u.kind) {
    case "json": {
      const parsed = parseJson(u.text);
      return "problem" in parsed ? parsed : quiet(setConfig(doc, u.node, u.path, written(parsed.value, u), type));
    }
    case "number": {
      const parsed = parseNumber(u.text, u.whole ?? false);
      return "problem" in parsed ? parsed : quiet(setConfig(doc, u.node, u.path, written(parsed.value, u), type));
    }
    case "formula":
      return quiet(setConfig(doc, u.node, u.path, u.text.trim() === "" ? written(undefined, u) : formula(u.text), type));
    case "port": {
      if (!type) return { problem: "This step's type isn't on this server." };
      const name = u.text.trim();
      const renamed = renamePort(doc, u.node, u.path[1] as number, name, type);
      if ("problem" in renamed) return renamed;
      return { doc: renamed.doc, dropped: [], said: `The port is now ${name}; its edges follow it.`, note: null };
    }
    case "name": {
      const renamed = renameEntry(doc, u.node, u.path, u.from ?? "", u.text.trim());
      return "problem" in renamed ? renamed : { doc: renamed.doc, dropped: [], said: null, note: null };
    }
    case "key": {
      const key = u.text.trim();
      const problem = keyProblem(doc, u.node, key);
      if (problem) return { problem };
      const { doc: next, mentions } = renameKey(doc, u.node, key);
      // A mention, not a reference: CEL isn't parsed here (ruling 11).
      const note =
        mentions === 0 ? null
        : mentions === 1 ? `1 formula mentions ${node.key} and keeps its text: check it.`
        : `${mentions} formulas mention ${node.key} and keep their text: check them.`;  // prettier-ignore
      return { doc: next, dropped: [], said: `Renamed ${node.key} to ${key}.${note ? ` ${note}` : ""}`, note };
    }
    case "limit": {
      const name = u.path[0] as Limit;
      const problem = limitProblem(name, u.text);
      if (problem !== null) return { problem };
      const value = u.text.trim() === "" ? undefined : Number(u.text.trim());
      return quiet(setOptions(doc, u.node, { ...(node.options ?? {}), [name]: value }, type));
    }
  }
}

/** The draft with the edit applied, or why it can't be: its own rule, or the graph's admission (ruling 7). */
export function applyUnapplied(doc: GraphDoc, u: Unapplied, type: NodeType | undefined): Applied | { problem: string } {
  const node = findNode(doc, u.node);
  if (!node) return { problem: "Its step is no longer in the draft." };
  const result = attempt(doc, node, u, type);
  if ("problem" in result) return result;
  const refused = admission(result.doc);
  return refused === null ? result : { problem: refused };
}

/** Why an edit that takes ports away waits for its question (ruling 9). */
export function droppedWhy(dropped: GraphEdge[], doc: GraphDoc): string {
  const ports = [...new Set(dropped.map(portOf))];
  const targets = [...new Set(dropped.map((e) => findNode(doc, e.to.node)?.key ?? "a step"))];
  return `Not applied: it removes ${ports.length === 1 ? "the port" : "the ports"} ${ports.join(", ")} and ${
    dropped.length === 1 ? "its edge" : "their edges"} to ${targets.join(", ")}.`;  // prettier-ignore
}

/** Each held edit `take` covers, applied in turn to one document: what they make, those applied, and those that stay
 * with their reasons. One that takes ports away stays: that is asked one edit at a time (ruling 9). */
export function applyAll(
  doc: GraphDoc, held: Iterable<Unapplied>, typeOf: (node: GraphNode) => NodeType | undefined, take: (u: Unapplied) => boolean,
): { doc: GraphDoc; applied: Unapplied[]; left: Unapplied[]; note: string | null } {  // prettier-ignore
  let next = doc;
  let note: string | null = null;
  const applied: Unapplied[] = [];
  const left: Unapplied[] = [];
  for (const u of held) {
    if (!take(u)) continue;
    const node = findNode(next, u.node);
    const result = applyUnapplied(next, u, node ? typeOf(node) : undefined);
    if ("problem" in result) left.push({ ...u, why: result.problem });
    else if (result.dropped.length > 0) left.push({ ...u, why: droppedWhy(result.dropped, next) });
    else {
      next = result.doc;
      note = result.note ?? note;
      applied.push(u);
    }
  }
  return { doc: next, applied, left, note };
}
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/lib/unapplied.test.ts`
Expected: PASS, 8 tests.

- [ ] **Step 5: Typecheck and lint**

Run: `npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: no errors. The `switch` over `UnappliedKind` covers every kind, so `attempt` needs no default.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/unapplied.ts frontend/src/lib/unapplied.test.ts
git commit -m "feat(editor): edits typed but not applied, as data, applied when they can be (4c-1)"
```

### Task 4: One undo step per field

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

# Milestone 2: Tabs, one field, the drawer, unapplied edits, lists and maps

### Task 5: Radix Tabs

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
end of Task 7.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/components/Tabs.tsx frontend/src/components/Tabs.test.tsx frontend/e2e/gate.spec.ts
git commit -m "feat(ui): token-styled Radix Tabs 1.1.21, pinned, in the notices (4c-1)"
```

### Task 6: One field

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
  - from Task 2: `valueAt`, `setConfig`, `setOptions`, `admission`, `kindOf`, `fixedOf`, `formula`, `literal`,
    `formulaOf`, `isPlainRef`, `referenceText`, `MAX_FORMULA`, `Changed`, `StepOptions`;
  - from Task 3: `Unapplied`, `UnappliedKind`, `Holding`, `unappliedId`, `within`, `applyUnapplied`, `applyAll`,
    `droppedWhy`, `parseNumber`.
- Produces:
  - `controlClass(invalid: boolean): string` (`components/Field.tsx`).
  - From `context.ts`:
    - `interface DrawerActions`, each answering why nothing was written, or null:
      - `set(path, value, mark?)`;
      - `options(options: StepOptions, mark?)`;
      - `held(kind, pointer): Unapplied | undefined`, `hold(kind, pointer, holding: Holding)`, `release(kind,
        pointer)`, `discard(pointer)`, `apply(kind, pointer)`;
      - `restructure(pointer, change?: { path: Path; make: (current: unknown) => unknown })`.
    - `interface Drawer extends DrawerActions { node: GraphNode; type: NodeType | undefined; editable: boolean;
      tenantId: string; workflowId: string; problems: Diagnostic[]; expressions: Expression[] }`;
    - `DrawerContext`, `useDrawer(): Drawer`;
    - `segment(name): string`, `problemsAt(all, pointer, shown: ReadonlySet<string> | null): Diagnostic[]`;
    - `useSession(prefix): { mark: () => string; onFocus: (e) => void }`.
  - From `FieldFrame.tsx`: `interface Described { id; describedBy; invalid }`, `FieldFrame`, `GroupFrame`.
  - From `scalars.tsx`:
    - `interface ControlProps extends Described { spec; value; literal: boolean; disabled; onChange: (value:
      unknown, typed: boolean) => string | null }`;
    - `useText(value, show, means, held?)`;
    - `TextControl`, `NumberControl`, `BooleanControl`, `EnumControl`, `JsonControl`;
    - `JSON_NOTE`, `LITERAL_NOTE`, `CUT_NOTE`.
  - From `Formula.tsx`: `type Mode = "fixed" | "formula"`, `FormulaControl`, `ModeSwitch`, `ReferenceView`,
    `SensitiveView`, `runsText(x: Expression | undefined): string | null`.
  - From `structured.tsx`: `isContainer(widget): boolean`, `partNames(spec): string[]`, `ContainerParts({ spec })`.
  - From `FieldView.tsx`: `FieldView({ spec }: { spec: FieldSpec })`.
  - From `harness.tsx` (tests only):
    - `NODE_ID`, `type Edit`;
    - `showFields(type, options?, children?)`, which returns `{ edits, config(), node(), held() }`;
    - `problem(field, message): Diagnostic`.

- [ ] **Step 1: Export the control's classes**

In `frontend/src/components/Field.tsx`, after `const CONTROL = …`, add:

```ts
/** A control's classes: its boundary 3:1 against its surface (line-control), red when its value is refused. */
export const controlClass = (invalid: boolean): string => `${CONTROL} ${invalid ? "border-danger" : "border-line-control"}`;
```

and in `Frame`, replace `` className: `${CONTROL} ${error ? "border-danger" : "border-line-control"}` `` with
`className: controlClass(!!error)`.

- [ ] **Step 2: Write the harness the tests drive**

Create `frontend/src/routes/editor/drawer/harness.tsx`. It's a one-step draft that each write changes as the editor
would: checked against the graph's admission, unapplied edits held beside it.

```tsx
// SPDX-License-Identifier: Apache-2.0
// A step's fields on their own, for tests (4c-1): a one-step draft each write changes as the editor would, checked
// against the graph's admission (ruling 7), with the edits typed but not applied held beside it (ruling 18), and
// every write kept with its mark. An edit that takes ports away is refused here: the editor asks (Task 7). Imported
// by tests only: the build never reaches it.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { admission, setConfig, setOptions, valueAt, type Changed, type StepOptions } from "../../../lib/config";
import { fieldsOf, type Path } from "../../../lib/schemaForm";
import { applyAll, applyUnapplied, droppedWhy, unappliedId, within, type Unapplied, type UnappliedKind } from "../../../lib/unapplied";
import type { Diagnostic, Expression, GraphDoc, NodeType } from "../../../lib/workflows";
import { DrawerContext, type Drawer } from "./context";
import { FieldView } from "./FieldView";

export const NODE_ID = "00000000-0000-4000-8000-000000000001";
export type Edit = { path: Path; value: unknown; mark: string | undefined };

interface Options {
  config?: Record<string, unknown>;
  options?: StepOptions;
  problems?: Diagnostic[];
  expressions?: Expression[];
  editable?: boolean;
}

interface State {
  doc: GraphDoc;
  held: ReadonlyMap<string, Unapplied>;
}

function Harness({ type, options, edits, state, children }: {
  type: NodeType; options: Options; edits: Edit[]; state: State; children: ReactNode;
}) {  // prettier-ignore
  const [, setVersion] = useState(0); // the draft and what's held live in `state`, which tests read; this redraws
  const redraw = () => setVersion((v) => v + 1);
  const id = (kind: UnappliedKind, pointer: string) => unappliedId(NODE_ID, kind, pointer);
  const keep = (u: Unapplied) => {
    state.held = new Map(state.held).set(u.id, u);
    redraw();
  };
  const drop = (ids: string[]) => {
    const next = new Map(state.held);
    for (const each of ids) next.delete(each);
    state.held = next;
    redraw();
  };
  const write = ({ doc, dropped }: Changed, release: string[] = []): string | null => {
    const refused = admission(doc);
    if (refused !== null) return refused;
    if (dropped.length > 0) return droppedWhy(dropped, doc);
    state.doc = doc;
    drop(release);
    return null;
  };
  const drawer: Drawer = {
    node: state.doc.nodes![0]!,
    type,
    editable: options.editable ?? true,
    tenantId: "t1",
    workflowId: "w1",
    problems: options.problems ?? [],
    expressions: options.expressions ?? [],
    set: (path, value, mark) => {
      edits.push({ path, value, mark });
      return write(setConfig(state.doc, NODE_ID, path, value, type));
    },
    options: (next) => write(setOptions(state.doc, NODE_ID, next, type)),
    held: (kind, pointer) => state.held.get(id(kind, pointer)),
    hold: (kind, pointer, holding) => keep({ ...holding, id: id(kind, pointer), node: NODE_ID, kind, pointer }),
    release: (kind, pointer) => drop([id(kind, pointer)]),
    discard: (pointer) => drop([...state.held.values()].filter(within(NODE_ID, pointer)).map((u) => u.id)),
    apply: (kind, pointer) => {
      const u = state.held.get(id(kind, pointer));
      if (!u) return null;
      const result = applyUnapplied(state.doc, u, type);
      const why = "problem" in result ? result.problem : write(result, [u.id]);
      if (why !== null) keep({ ...u, why });
      return why;
    },
    restructure: (pointer, change) => {
      const { doc, applied, left } = applyAll(state.doc, state.held.values(), () => type, within(NODE_ID, pointer));
      for (const u of left) keep(u);
      if (left.length > 0) return left[0]!.why;
      let changed: Changed = { doc, dropped: [] };
      if (change) {
        const current = valueAt(doc.nodes![0]!.config ?? {}, change.path);
        const made = change.make(current);
        if (made !== current) changed = setConfig(doc, NODE_ID, change.path, made, type);
      }
      return changed.doc === state.doc ? null : write(changed, applied.map((u) => u.id));
    },
  };
  return <DrawerContext.Provider value={drawer}>{children}</DrawerContext.Provider>;
}

/** The type's fields, or `children`, in a drawer of one step. `config()`, `node()` and `held()` read what the edits
 * made of it. */
export function showFields(type: NodeType, options: Options = {}, children?: ReactNode) {
  const edits: Edit[] = [];
  const state: State = {
    doc: {
      graph_format: 1,
      nodes: [{ id: NODE_ID, key: "step", type: type.ref, config: options.config ?? {}, ...(options.options ? { options: options.options } : {}) }],
    },
    held: new Map(),
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness type={type} options={options} edits={edits} state={state}>
        {children ?? fieldsOf(type).map((f) => <FieldView key={f.pointer} spec={f} />)}
      </Harness>
    </QueryClientProvider>,
  );
  return {
    edits,
    config: () => state.doc.nodes![0]!.config ?? {},
    node: () => state.doc.nodes![0]!,
    held: () => [...state.held.values()],
  };
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
import { formula, literal } from "../../../lib/config";
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

/** A group holding a secret, with a default that holds one too. */
const HOLDER = typeWith({
  type: "object",
  properties: {
    auth: {
      type: "object", title: "Auth", default: { key: "d3fault-s3cr3t" },
      properties: { key: { type: "string", title: "Key", "x-sensitive": true } },
    },
  },
});  // prettier-ignore

const typedValues = () => [...document.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>("input, textarea")].map((f) => f.value);

it("labels a field by its title, its hint and the server's problems described by it", () => {
  showFields(PLAIN, { problems: [problem("/name", "Too short.")] });
  const name = screen.getByLabelText("Name");
  const described = name.getAttribute("aria-describedby")!.split(" ").map((id) => document.getElementById(id)!.textContent);
  expect(described).toEqual(["Shown to people.", "Too short."]);
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(name.getAttribute("aria-required")).toBe("true");
});

it("writes a number as typed, and holds what isn't one, with why", async () => {
  const { config, held } = showFields(PLAIN);
  await userEvent.type(screen.getByLabelText("Count"), "12");
  expect(config()).toEqual({ count: 12 });
  await userEvent.type(screen.getByLabelText("Count"), ".5");
  expect(screen.getByText("A whole number, like 42.")).toBeTruthy();
  expect(config()).toEqual({ count: 12 });
  expect(held().map((u) => [u.kind, u.text])).toEqual([["number", "12.5"]]);
  await userEvent.type(screen.getByLabelText("Ratio"), "2.");
  expect(screen.getByLabelText<HTMLInputElement>("Ratio").value).toBe("2."); // as typed, while it means 2
  expect(config()).toEqual({ count: 12, ratio: 2 });
});

it("discards an edit not applied, on purpose", async () => {
  const { held } = showFields(PLAIN, { config: { count: 4 } });
  await userEvent.type(screen.getByLabelText("Count"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Discard the edit to Count" }));
  expect(screen.getByLabelText<HTMLInputElement>("Count").value).toBe("4");
  expect(held()).toEqual([]);
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

it("edits a group as JSON, the engine's reading, applied when focus leaves", async () => {
  const { config, held } = showFields(PLAIN, { config: { query: { limit: 5 } } });
  await userEvent.click(screen.getByRole("button", { name: "Edit as JSON" }));
  const json = screen.getByLabelText<HTMLTextAreaElement>("Query");
  expect(JSON.parse(json.value)).toEqual({ limit: 5 });
  await userEvent.clear(json);
  await userEvent.paste('{"limit": {"$value": {"kind": "ref", "path": "trigger.n"}}}');
  expect(config()).toEqual({ query: { limit: 5 } }); // held while it's typed
  expect(held()).toHaveLength(1);
  await userEvent.tab();
  expect(config()).toEqual({ query: { limit: { $value: { kind: "ref", path: "trigger.n" } } } }); // never wrapped
  expect(held()).toEqual([]);
});

it("keeps unapplied JSON through a change of view, applying what's valid first", async () => {
  const { config, held } = showFields(PLAIN, { config: { query: { limit: 5 } } });
  const toggle = () => screen.getByRole("button", { name: "Edit as JSON" });
  await userEvent.click(toggle());
  await userEvent.clear(screen.getByLabelText("Query"));
  await userEvent.paste('{"limit": ');
  await userEvent.click(toggle()); // focus leaves (applied: refused), then the toggle waits for it
  expect(screen.getByText("This isn't valid JSON, so it isn't saved.")).toBeTruthy();
  expect(screen.getByLabelText<HTMLTextAreaElement>("Query").value).toBe('{"limit": '); // kept, still shown
  expect(held()).toHaveLength(1);
  await userEvent.click(screen.getByLabelText("Query"));
  await userEvent.paste("7}");
  await userEvent.click(toggle()); // valid now: applied, then the form
  expect(config()).toEqual({ query: { limit: 7 } });
  expect(within(screen.getByRole("group", { name: "Query" })).getByLabelText<HTMLInputElement>("Limit").value).toBe("7");
  expect(held()).toEqual([]);
});

it("says a JSON number too large to keep, and keeps it out of the draft", async () => {
  const { config } = showFields(PLAIN);
  await userEvent.click(within(screen.getByRole("group", { name: "How Extra is set" })).getByRole("button", { name: "Fixed" }));
  await userEvent.click(screen.getByLabelText("Extra"));
  await userEvent.paste("[1e400]");
  await userEvent.tab();
  expect(screen.getByText("A number here is too large to keep, so it isn't saved.")).toBeTruthy();
  expect(config()).toEqual({});
});

it("edits a literal as its payload, and keeps it a literal", async () => {
  const data = { limit: { $value: { kind: "ref", path: "trigger.n" } } }; // data, not a reference
  const { config } = showFields(PLAIN, { config: { name: literal("hi"), query: literal(data) } });
  await userEvent.type(screen.getByLabelText("Name"), "!");
  const json = screen.getByLabelText<HTMLTextAreaElement>("Query"); // a literal's parts are its payload's: JSON
  expect(JSON.parse(json.value)).toEqual(data);
  expect(screen.getAllByText(/Written as a literal: kept as data/)).toHaveLength(2); // the name's hint and the JSON's
  await userEvent.clear(json);
  await userEvent.paste('{"limit": {"$value": {"kind": "ref", "path": "trigger.m"}}}');
  await userEvent.tab();
  expect(config()).toEqual({
    name: literal("hi!"),
    query: literal({ limit: { $value: { kind: "ref", path: "trigger.m" } } }),
  });
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

it("offers neither a fixed value nor a formula where the engine takes only references", () => {
  const refs = typeWith({ type: "object", properties: { source: { type: "string", title: "Source", "x-dewpoint-kinds": ["ref"] } } });
  showFields(refs, { config: { source: { $value: { kind: "ref", path: "trigger.site" } } } });
  expect(screen.getByLabelText("Source").textContent).toBe("trigger.site");
  expect(screen.getByText(/takes only references or text with references, which can't be set in this drawer/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: /Fixed|Formula|Replace/ })).toBeNull();
  expect(screen.queryByRole("textbox")).toBeNull();
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
  expect(document.body.textContent).not.toContain("s3cr3t");
  expect(typedValues().some((v) => v.includes("s3cr3t"))).toBe(false);
  expect(screen.getByLabelText("Token").textContent).toBe("A fixed value is written here, which a sensitive field can't keep.");
  await userEvent.click(screen.getByRole("button", { name: "Replace with a formula" }));
  expect(config()).toEqual({});
  expect(screen.getByLabelText("Token").tagName).toBe("TEXTAREA");
});

it("never shows a sensitive part as JSON, a default or a formula", async () => {
  const { config } = showFields(HOLDER, { config: { auth: { key: "s3cr3t-value" } } });
  expect(screen.getByRole("group", { name: "Auth" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Edit as JSON" })).toBeNull();
  await userEvent.click(within(screen.getByRole("group", { name: "How Auth is set" })).getByRole("button", { name: "Formula" }));
  expect(config()).toEqual({}); // the formula starts empty: nothing copied out of the hidden value
  expect(screen.getByLabelText<HTMLTextAreaElement>("Auth").value).toBe("");
  expect(document.body.textContent).not.toMatch(/s3cr3t/);
  expect(typedValues().some((v) => v.includes("s3cr3t"))).toBe(false);
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

- [ ] **Step 5: Write what a drawer's fields share and may do**

Create `frontend/src/routes/editor/drawer/context.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// What a step drawer's fields share (4c-1): the step, its type, whether it may be edited, the server's problems and
// formulas for it; what they may do to the draft, through the editor, which owns the document and the edits typed but
// not applied (ruling 18); which problems a field shows (D19); and focus sessions (ruling 8).
import { createContext, useContext, useRef, type FocusEvent } from "react";
import type { StepOptions } from "../../../lib/config";
import { pointerOf, type Path } from "../../../lib/schemaForm";
import type { Holding, Unapplied, UnappliedKind } from "../../../lib/unapplied";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";

/** What a drawer may do to its step. Each write answers why nothing was written, or null. */
export interface DrawerActions {
  /** Writes `value` at `path` in the step's config (undefined removes it); edits sharing a mark are one undo step. */
  set: (path: Path, value: unknown, mark?: string) => string | null;
  /** Writes the step's options: what a failure does, its attempts and its timeout. */
  options: (options: StepOptions, mark?: string) => string | null;
  /** What's typed for a field but not in the draft (ruling 18), by its kind and pointer. */
  held: (kind: UnappliedKind, pointer: string) => Unapplied | undefined;
  hold: (kind: UnappliedKind, pointer: string, holding: Holding) => void;
  release: (kind: UnappliedKind, pointer: string) => void;
  /** Drops every unapplied edit at `pointer` and below, on purpose: what Clear does. */
  discard: (pointer: string) => void;
  /** Applies what's typed for a field now: when focus leaves it, on Enter. */
  apply: (kind: UnappliedKind, pointer: string) => string | null;
  /** Applies every unapplied edit at `pointer` and below; then, with `change`, writes what `make` makes of the value
   * at `path`, as one undo step. An edit that can't be applied stops it, its control saying why. */
  restructure: (pointer: string, change?: { path: Path; make: (current: unknown) => unknown }) => string | null;
}

export interface Drawer extends DrawerActions {
  node: GraphNode;
  type: NodeType | undefined;
  editable: boolean;
  tenantId: string;
  workflowId: string;
  problems: Diagnostic[]; // the step's, from a current check
  expressions: Expression[]; // how its formulas run
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
// reads it (ruling 15). Each writes through its field. What it can't write yet (a number that doesn't parse, JSON
// still being typed) the editor holds (ruling 18): nothing unsaved looks saved (D19), and nothing typed is lost to a
// tab or a toggle.
import { useState } from "react";
import { controlClass } from "../../../components/Field";
import type { FieldSpec } from "../../../lib/schemaForm";
import { parseNumber } from "../../../lib/unapplied";
import { useDrawer } from "./context";
import type { Described } from "./FieldFrame";

export interface ControlProps extends Described {
  spec: FieldSpec;
  value: unknown; // a `literal` envelope's payload, or the value as written
  literal: boolean; // the value is a literal's payload: written back as one (ruling 15)
  disabled: boolean;
  /** Writes a new value (undefined: emptied); `typed` makes it part of the field's typing (ruling 8). Why it wasn't
   * written, or null. */
  onChange: (value: unknown, typed: boolean) => string | null;
}

export const JSON_NOTE = 'As the engine reads it: an object with a "$value" key is computed.';
export const LITERAL_NOTE = 'Written as a literal: kept as data, "$value" included.';
export const CUT_NOTE = "Shown as JSON: its schema repeats itself, or nests too deep for a form.";

/** A control's own text, kept while it still means the value it shows ("2." while 2.5 is typed), and replaced when
 * the value changes elsewhere (an undo, a replace). It starts from what the editor holds for it, if anything. */
export function useText(value: unknown, show: (v: unknown) => string, means: (text: string, v: unknown) => boolean, held?: string) {
  const [text, setText] = useState(() => held ?? show(value));
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

export function NumberControl({ spec, value, literal, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const drawer = useDrawer();
  const whole = spec.base === "integer";
  const [text, setText] = useText(
    value,
    asText,
    (t, v) => {
      const parsed = parseNumber(t, whole);
      return "value" in parsed && (parsed.value === undefined ? v === undefined || v === null : parsed.value === v);
    },
    drawer.held("number", spec.pointer)?.text,
  );
  return (
    <input
      id={id} type="text" value={text} disabled={disabled} spellCheck={false}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required={spec.required}
      onChange={(e) => {
        setText(e.target.value);
        const parsed = parseNumber(e.target.value, whole);
        if ("problem" in parsed) {
          const holding = { path: spec.path, label: spec.label, text: e.target.value, why: parsed.problem, whole, literal, entry: spec.entry };
          drawer.hold("number", spec.pointer, holding);
          return;
        }
        drawer.release("number", spec.pointer);
        onChange(parsed.value, true);
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

/** JSON as the engine reads it (ruling 15). What's typed is the editor's until focus leaves, then applied (ruling
 * 18): a half-typed edit never saves, one that takes ports away asks once (ruling 9), and a tab or a toggle keeps it. */
export function JsonControl({ spec, value, literal, id, describedBy, invalid, disabled }: ControlProps) {
  const drawer = useDrawer();
  const held = drawer.held("json", spec.pointer);
  const shown = value === undefined ? "" : JSON.stringify(value, null, 2);
  const text = held?.text ?? shown;
  return (
    <textarea
      id={id} value={text} disabled={disabled} spellCheck={false} autoCapitalize="off"
      rows={Math.min(12, Math.max(3, text.split("\n").length))}
      aria-describedby={describedBy} aria-invalid={invalid}
      onChange={(e) => {
        if (e.target.value === shown) drawer.release("json", spec.pointer);
        else drawer.hold("json", spec.pointer, { path: spec.path, label: spec.label, text: e.target.value, why: null, literal, entry: spec.entry });
      }}
      onBlur={() => {
        if (held) drawer.apply("json", spec.pointer);
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
// never shown (M25). A formula the graph's format refuses is held by the editor, with why (ruling 18).
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { MAX_FORMULA, formula, formulaOf, kindOf, referenceText } from "../../../lib/config";
import type { Expression } from "../../../lib/workflows";
import { useDrawer } from "./context";
import type { Described } from "./FieldFrame";
import { useText, type ControlProps } from "./scalars";

export type Mode = "fixed" | "formula";

export function FormulaControl({ spec, value, id, describedBy, invalid, disabled, onChange }: ControlProps) {
  const drawer = useDrawer();
  const [text, setText] = useText(
    value,
    formulaOf,
    (t, v) => (t.trim() === "" ? kindOf(v) !== "cel" : formulaOf(v) === t),
    drawer.held("formula", spec.pointer)?.text,
  );
  return (
    <textarea
      id={id} value={text} rows={3} maxLength={MAX_FORMULA} spellCheck={false} autoCapitalize="off" disabled={disabled}
      aria-describedby={describedBy} aria-invalid={invalid}
      onChange={(e) => {
        setText(e.target.value);
        const why = onChange(e.target.value.trim() === "" ? undefined : formula(e.target.value), true);
        if (why === null) drawer.release("formula", spec.pointer);
        else drawer.hold("formula", spec.pointer, { path: spec.path, label: spec.label, text: e.target.value, why, entry: spec.entry });
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
// it, or neither (ruling 6); its control, chosen by its widget (ruling 5); the server's problems at it, with how a
// formula runs (D19); and what's typed in it but not applied, with its reason and a Discard (ruling 18). Its typing
// while it keeps focus is one undo step (ruling 8).
import { useState, type ReactNode } from "react";
import { Button } from "../../../components/Button";
import { fixedOf, formula, isPlainRef, kindOf, literal, referenceText, valueAt } from "../../../lib/config";
import { canFixed, canFormula, emptyOf, startsAsFormula, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import type { UnappliedKind } from "../../../lib/unapplied";
import { problemsAt, useDrawer, useSession } from "./context";
import { FieldFrame, GroupFrame, type Described } from "./FieldFrame";
import { FormulaControl, ModeSwitch, ReferenceView, SensitiveView, runsText, type Mode } from "./Formula";
import {
  BooleanControl, CUT_NOTE, EnumControl, JSON_NOTE, JsonControl, LITERAL_NOTE, NumberControl, TextControl,
  type ControlProps,
} from "./scalars";  // prettier-ignore
import { ContainerParts, isContainer, partNames } from "./structured";

type Control = (props: ControlProps) => ReactNode;
const OWN: UnappliedKind[] = ["json", "number", "formula", "port"]; // what a field's own control may hold
const NEITHER = "This field takes only references or text with references, which can't be set in this drawer.";

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

const joined = (...parts: (string | null)[]): string | null => parts.filter((p) => p !== null).join(" ") || null;

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
  const [local, setLocal] = useState<string | null>(null); // why the last write didn't happen
  const [touched, setTouched] = useState(false);
  const [asJson, setAsJson] = useState(false);
  const [generation, setGeneration] = useState(0); // a Discard starts the control afresh, from the draft
  const [seen, setSeen] = useState(value);
  if (!Object.is(seen, value)) {
    // Set elsewhere (an undo, a replace): a formula or a fixed value decides the mode; emptied, the field keeps its own.
    setSeen(value);
    setLocal(null);
    if (kind === "cel") setChosen("formula");
    else if (!empty) setChosen("fixed");
  }
  const { mark, onFocus } = useSession(`${drawer.node.id}${spec.pointer}`);
  const held = OWN.map((k) => drawer.held(k, spec.pointer)).find((u) => u !== undefined);
  const disabled = !drawer.editable;
  const fixedOk = canFixed(spec);
  const formulaOk = canFormula(spec);
  const mode: Mode = fixedOk && formulaOk ? chosen : fixedOk ? "fixed" : "formula"; // the engine decides (ruling 6)
  const write = (next: unknown, typed: boolean): string | null => {
    setTouched(true);
    const why = drawer.set(spec.path, next === undefined ? emptyOf(spec) : next, typed ? mark() : undefined);
    setLocal(why);
    return why;
  };
  // A literal's payload is written back as a literal: its kind changes only on purpose (ruling 15).
  const writeFixed = (next: unknown, typed: boolean) => write(next !== undefined && kind === "literal" ? literal(next) : next, typed);
  /** A change to the whole value: what's typed beneath it is applied first, or the change waits (ruling 18). */
  const reshape = (make: (current: unknown) => unknown, then: () => void) => {
    const why = drawer.restructure(spec.pointer, { path: spec.path, make });
    setLocal(why);
    if (why === null) then();
  };
  const computed = kind === "ref" || kind === "template";
  const hidden = spec.sensitive && !empty && kind !== "cel"; // a fixed value in a sensitive field: never shown (M25)
  const fixed = fixedOf(value);
  // A literal's or an unreadable envelope's parts aren't where a form writes them: shown as JSON.
  const json = asJson || kind === "unknown" || (kind === "literal" && isContainer(spec.base));
  const container = mode === "fixed" && fixedOk && !computed && !hidden && !json && isContainer(spec.base);
  const problems = problemsAt(drawer.problems, spec.pointer, container ? new Set(partNames(spec)) : null);
  const required = spec.required && !spec.entry && spec.path.length > 1;
  const missing = spec.required && touched && (empty || value === "") ? "Required" : null;
  const switchTo = (next: Mode) =>
    reshape(
      (current) => {
        if (next === "fixed") return kindOf(current) === "cel" ? emptyOf(spec) : current;
        const was = fixedOf(current);
        // A fixed value becomes the formula that gives it, unless it holds a sensitive part: never copied into visible
        // text (M25), the formula starts empty.
        return was === undefined || was === null || spec.holdsSensitive ? emptyOf(spec) : formula(JSON.stringify(was));
      },
      () => setChosen(next),
    );
  const toggleJson = () => {
    const why = drawer.restructure(spec.pointer); // what's typed in one view is applied before the other shows
    setLocal(why);
    if (why === null) setAsJson(!asJson);
  };
  const clear = () => {
    drawer.discard(spec.pointer); // Clear drops what's typed in it too, on purpose (ruling 18)
    setGeneration((g) => g + 1);
    write(undefined, false);
  };
  const actions = (
    <>
      {fixedOk && formulaOk && !computed && !hidden && (
        <ModeSwitch label={spec.label} mode={mode} disabled={disabled} onChange={switchTo} />
      )}
      {mode === "fixed" && fixedOk && !computed && !hidden && kind === null && isContainer(spec.base) && !spec.holdsSensitive && (
        <Button size="sm" aria-pressed={asJson} onClick={toggleJson}>Edit as JSON</Button>
      )}
      {!disabled && held && (
        <Button
          size="sm"
          aria-label={`Discard the edit to ${spec.label}`}
          onClick={() => {
            drawer.release(held.kind, spec.pointer);
            setGeneration((g) => g + 1);
            setLocal(null);
          }}
        >
          Discard
        </Button>
      )}
      {!disabled && !spec.required && !spec.entry && value !== undefined && (
        <Button size="sm" aria-label={`Clear ${spec.label}`} onClick={clear}>Clear</Button>
      )}
    </>
  );
  const frame = (control: (c: Described) => ReactNode, hint: string | null = spec.hint, below?: ReactNode) => (
    <FieldFrame label={spec.label} required={required} hint={hint} local={held?.why ?? local ?? missing} problems={problems} actions={actions} below={below}>
      {control}
    </FieldFrame>
  );
  const Control: Control = json ? JsonControl : (controlFor(spec.widget === "formula" ? spec.base : spec.widget) ?? controlFor(spec.base) ?? JsonControl);
  let body: ReactNode;
  if (hidden) {
    body = frame((c) => (
      <SensitiveView
        {...c} toFormula={formulaOk} disabled={disabled}
        onClear={clear}
        onFormula={() => reshape(() => emptyOf(spec), () => setChosen("formula"))}
      />
    ));  // prettier-ignore
  } else if (!fixedOk && !formulaOk) {
    // Only references or templates (4c-2's pills): what's there is shown, nothing is offered (ruling 6).
    body = frame(
      (c) => (
        <output id={c.id} aria-describedby={c.describedBy} className="block break-all font-mono text-small">
          {computed ? referenceText(value) : empty ? "Not set" : "A value this field doesn't take"}
        </output>
      ),
      joined(spec.hint, NEITHER),
    );
  } else if (computed) {
    body = frame((c) => (
      <ReferenceView
        {...c} value={value} fixed={fixedOk} toFormula={formulaOk} disabled={disabled}
        onFixed={() => reshape(() => emptyOf(spec), () => setChosen("fixed"))}
        onFormula={() => reshape(() => (isPlainRef(value) ? formula(referenceText(value)) : emptyOf(spec)), () => setChosen("formula"))}
      />
    ));  // prettier-ignore
  } else if (mode === "formula") {
    const runs = runsText(drawer.expressions.find((x) => x.field === spec.pointer));
    body = frame(
      (c) => <FormulaControl key={generation} {...c} spec={spec} value={value} literal={false} disabled={disabled} onChange={write} />,
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
    const note = kind === "literal" ? LITERAL_NOTE : Control === JsonControl ? (spec.cut ? `${CUT_NOTE} ${JSON_NOTE}` : JSON_NOTE) : null;
    body = frame(
      (c) => (
        <Control key={generation} {...c} spec={spec} value={fixed} literal={kind === "literal"} disabled={disabled} onChange={writeFixed} />
      ),
      joined(spec.hint, note),
    );
  }
  return (
    <div data-pointer={spec.pointer} onFocus={onFocus}>
      {body}
    </div>
  );
}
```

`Control` names both a type and a value: TypeScript keeps them apart, and JSX takes the value.

- [ ] **Step 11: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/drawer/FieldView.test.tsx`
Expected: PASS, 18 tests.

- [ ] **Step 12: Run every frontend test, then typecheck and lint**

The AI-tells guard (`src/test/aiTells.ts`) runs with the suite and scans the new files.
Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 13: Commit**

```bash
git add frontend/src/components/Field.tsx frontend/src/routes/editor/drawer
git commit -m "feat(editor): a step's field, fixed or a formula, its unapplied text held; references, literals and secrets kept (4c-1)"
```

### Task 7: The drawer, and the editor's side of its writes

**Files:**
- Create: `frontend/src/routes/editor/drawer/StepDrawer.tsx`
- Create: `frontend/src/routes/editor/drawer/ErrorHandling.tsx` (`chipText` only; Task 12 adds the section)
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Delete: `frontend/src/routes/editor/StepPanel.tsx`
- Test: `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 2: `setConfig`, `setOptions`, `admission`, `valueAt`, `Changed`;
  - from Task 3: `Unapplied`, `UnappliedKind`, `unappliedId`, `within`, `applyUnapplied`, `applyAll`, `droppedWhy`;
  - from Task 4: `record(h, next, mark)`;
  - from Task 5: `Tabs`;
  - from Task 6: `FieldView`, `DrawerContext`, `DrawerActions`, `problemsAt`, `segment`.
- Produces:
  - `StepDrawer` props: `{ node; type: NodeType | undefined; tenantId; workflowId; ports: string[]; problems:
    Diagnostic[] | null; expressions: Expression[]; editable; adds; actions: DrawerActions; onAdd; onDelete;
    onConnectPort; onPlace; onNudge; onClose }`. Later tasks add props.
  - `type Nudge` (moved from `StepPanel.tsx`).
  - `chipText(node: GraphNode, type: NodeType | undefined): string`.
  - In `Editor.tsx`:
    - `change(next, message: string | null, then?, mark?): boolean`: whether it landed;
    - the unapplied edits: `unapplied` (state), `unappliedRef`, `keep(u)`, `drop(ids)`;
    - `writeDraft(changed, how?: { mark?; release?: string[]; said?: string | null }): string | null`;
    - `applyEdit(id): string | null`;
    - `restructureStep(nodeId, pointer, then?)`;
    - `actionsFor(nodeId): DrawerActions`;
    - the `{ kind: "ports" }` question, which carries the unapplied edits it applies;
    - the heading's id, `step-drawer-title`.

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
  // Canceled, the edit stays the person's: unapplied, its reason at its control (ruling 18).
  expect(JSON.parse(screen.getByLabelText<HTMLTextAreaElement>("Routes").value)).toEqual([{ port: "a" }]);
  expect(screen.getByText("Not applied: it removes the port b and its edge to transform.")).toBeTruthy();
});

it("keeps an unapplied edit when the tab changes or the drawer closes", async () => {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, DELAY]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: oneStep("flow.delay@1", {}) }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "wait" }));
  await userEvent.type(screen.getByLabelText("Duration S"), "1x");
  await userEvent.click(screen.getByRole("tab", { name: "Options" }));
  await userEvent.click(screen.getByRole("tab", { name: "Setup" }));
  expect(screen.getByLabelText<HTMLInputElement>("Duration S").value).toBe("1x");
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  await userEvent.click(screen.getByRole("button", { name: "wait" }));
  expect(screen.getByLabelText<HTMLInputElement>("Duration S").value).toBe("1x");
  expect(screen.getByText("A whole number, like 42.")).toBeTruthy();
  expect(stepConfig("wait")).toEqual({ duration_s: 1 }); // "1" was a number; "1x" never reached the draft
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
"Options", no dialog "Remove a port". The 4b tests still pass.

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
// back to the step. What its fields do to the draft goes through `actions`, the editor's (ruling 18).
import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Tabs } from "../../../components/Tabs";
import { fieldsOf, tabsOf, type FieldSpec } from "../../../lib/schemaForm";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../../lib/workflows";
import type { ItemAction } from "../items";
import { SIDE } from "../side";
import { DrawerContext, problemsAt, segment, type DrawerActions } from "./context";
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
  node, type, tenantId, workflowId, ports, problems, expressions, editable, adds, actions,
  onAdd, onDelete, onConnectPort, onPlace, onNudge, onClose,
}: {
  node: GraphNode; type: NodeType | undefined; tenantId: string; workflowId: string; ports: string[];
  problems: Diagnostic[] | null; expressions: Expression[]; editable: boolean; adds: { label: string; action: ItemAction }[];
  actions: DrawerActions; onAdd: (action: ItemAction) => void; onDelete: () => void; onConnectPort: (port: string) => void;
  onPlace: () => void; onNudge: (key: Nudge) => void; onClose: () => void;
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
  const drawer = { ...actions, node, type, editable, tenantId, workflowId, problems: mine, expressions };
  return (
    <DrawerContext.Provider value={drawer}>
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
    </DrawerContext.Provider>
  );
}
```


- [ ] **Step 5: Wire the drawer into the editor**

In `frontend/src/routes/editor/Editor.tsx`:

(a) Imports:
- Replace `import { StepPanel } from "./StepPanel";` with `import { StepDrawer } from "./drawer/StepDrawer";`.
- Add:

```ts
import { admission, setConfig, setOptions, valueAt, type Changed } from "../../lib/config";
import type { Path } from "../../lib/schemaForm";
import {
  applyAll, applyUnapplied, droppedWhy, unappliedId, within, type Unapplied, type UnappliedKind,
} from "../../lib/unapplied";  // prettier-ignore
import type { DrawerActions } from "./drawer/context";
```

- Add `portOf` to the `../../lib/graph` import, and `type GraphNode` to the `../../lib/workflows` import.

(b) Above `export function EditorPage`, add:

```ts
/** What the editor asks before doing: deleting a step or an edge, or a settings change that takes ports away, with the
 * document it makes and the unapplied edits it applies (rulings 9 and 18). */
type Asking =
  | { kind: "node"; id: string }
  | { kind: "edge"; edge: GraphEdge }
  | { kind: "ports"; next: GraphDoc; dropped: GraphEdge[]; release: string[] };

/** Which ports a change takes away, and where their edges led (ruling 9). */
function portsQuestion(dropped: GraphEdge[], keyOf: (id: string) => string): string {
  const ports = [...new Set(dropped.map(portOf))];
  const targets = [...new Set(dropped.map((e) => keyOf(e.to.node)))];
  const one = ports.length === 1;
  return `${one ? "The port" : "The ports"} ${ports.join(", ")} ${one ? "goes" : "go"} with this change, and ${
    dropped.length === 1 ? "its edge" : "their edges"} to ${targets.join(", ")} ${dropped.length === 1 ? "is" : "are"} deleted.`;
}

const CANT = "Not written: the draft can't be changed now."; // a conflict, an exit agreed to, a version view
```

and change the `asking` state to `useState<Asking | null>(null)`.

(c) After the `asking` state, add the unapplied edits:

```ts
  // What's typed in the drawer but not in the draft (ruling 18): the editor's, never a control's, so a tab, a toggle
  // or a closed drawer keeps it. The ref serves decisions made after a render (an exit's, Task 8).
  const [unapplied, setUnapplied] = useState<ReadonlyMap<string, Unapplied>>(new Map());
  const unappliedRef = useRef(unapplied);
  unappliedRef.current = unapplied;
  const keep = (u: Unapplied) => setUnapplied((m) => new Map(m).set(u.id, u));
  const drop = (ids: string[]) =>
    setUnapplied((m) => {
      if (!ids.some((id) => m.has(id))) return m;
      const next = new Map(m);
      for (const id of ids) next.delete(id);
      return next;
    });
  const typeOf = (n: GraphNode) => typeMap.get(n.type);
```

(d) Replace `change`, and add the drawer's writes after it:

```ts
  /** One edit: recorded (edits sharing a field's mark are one undo step, ruling 8), saved, and said, unless `message`
   * is null: a field's edits aren't announced, its control says what it holds. Whether it landed. */
  function change(next: GraphDoc, message: string | null, then?: string, mark?: string): boolean {
    if (!mayEdit()) return false; // read only now: a conflict, an exit agreed to, a version view, a publication
    setHistory((h) => record(h, next, mark));
    saver.current?.change(next);
    if (message !== null) announce(message);
    if (then) focus(then);
    return true;
  }

  /** A drawer's change to the draft. Refused when the graph's format would refuse it (ruling 7); asked first when it
   * takes ports away (ruling 9); else recorded, and the unapplied edits it carries released. Why it wasn't made, or
   * null (made, or asked). */
  function writeDraft(changed: Changed, how: { mark?: string; release?: string[]; said?: string | null } = {}): string | null {
    const refused = admission(changed.doc);
    if (refused !== null) return refused;
    if (changed.dropped.length > 0) {
      setAsking({ kind: "ports", next: changed.doc, dropped: changed.dropped, release: how.release ?? [] });
      return null;
    }
    if (!change(changed.doc, how.said ?? null, undefined, how.mark)) return CANT;
    drop(how.release ?? []);
    return null;
  }

  /** One unapplied edit applied now (focus left its control, Enter): why it stays unapplied, or null. */
  function applyEdit(id: string): string | null {
    const u = unappliedRef.current.get(id);
    if (!u) return null;
    const node = findNode(doc, u.node);
    const result = applyUnapplied(doc, u, node ? typeOf(node) : undefined);
    // Asked before it takes ports away: until the answer, and after a Cancel, its control says why (ruling 9).
    const why =
      "problem" in result ? result.problem
      : result.dropped.length > 0 ? (writeDraft(result, { release: [id] }) ?? droppedWhy(result.dropped, result.doc))
      : writeDraft(result, { release: [id], said: result.said });  // prettier-ignore
    if (why !== null) keep({ ...u, why });
    return why;
  }

  /** The unapplied edits at `pointer` and below in a step applied; then, with `then`, what `make` makes of the value
   * at `path` written: one undo step (ruling 18). An edit that can't be applied stops it, said at its control. */
  function restructureStep(nodeId: string, pointer: string, then?: { path: Path; make: (current: unknown) => unknown }): string | null {
    const { doc: settled, applied, left } = applyAll(doc, unappliedRef.current.values(), typeOf, within(nodeId, pointer));
    for (const u of left) keep(u);
    if (left.length > 0) return left[0]!.why;
    let changed: Changed = { doc: settled, dropped: [] };
    const node = findNode(settled, nodeId);
    if (then && node) {
      const current = valueAt(node.config ?? {}, then.path);
      const made = then.make(current);
      if (made !== current) changed = setConfig(settled, nodeId, then.path, made, typeOf(node));
    }
    if (changed.doc === doc) return null;
    return writeDraft(changed, { release: applied.map((u) => u.id) });
  }

  /** What the open step's drawer may do. Every write goes through `change`, so through 4b's guards (`mayEdit`). */
  function actionsFor(nodeId: string): DrawerActions {
    const id = (kind: UnappliedKind, pointer: string) => unappliedId(nodeId, kind, pointer);
    const stepType = () => {
      const node = findNode(doc, nodeId);
      return node ? typeOf(node) : undefined;
    };
    return {
      set: (path, value, mark) => writeDraft(setConfig(doc, nodeId, path, value, stepType()), { mark }),
      options: (options, mark) => writeDraft(setOptions(doc, nodeId, options, stepType()), { mark }),
      held: (kind, pointer) => unapplied.get(id(kind, pointer)),
      hold: (kind, pointer, holding) => keep({ ...holding, id: id(kind, pointer), node: nodeId, kind, pointer }),
      release: (kind, pointer) => drop([id(kind, pointer)]),
      discard: (pointer) => drop([...unappliedRef.current.values()].filter(within(nodeId, pointer)).map((u) => u.id)),
      apply: (kind, pointer) => applyEdit(id(kind, pointer)),
      restructure: (pointer, then) => restructureStep(nodeId, pointer, then),
    };
  }
```

(e) In `confirmDelete`, before the `if (asking.kind === "node")` branch, add:

```ts
    if (asking.kind === "ports") {
      const ports = [...new Set(asking.dropped.map(portOf))].join(", ");
      const edges = asking.dropped.length === 1 ? "its edge" : `${asking.dropped.length} edges`;
      if (change(asking.next, `Removed ${ports} and ${edges}`)) drop(asking.release);
      setAsking(null);
      // What asked is gone with its port (a Remove, a JSON edit): focus lands on the drawer, after the dialog has
      // given it back (WCAG 2.4.3).
      requestAnimationFrame(() => document.getElementById("step-drawer-title")?.focus());
      return;
    }
```

(f) Replace the `<StepPanel … />` element with:

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
            actions={actionsFor(open.id)}
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
          />
```

(g) In the delete `ConfirmDialog`:
- `title={asking?.kind === "edge" ? "Delete an edge" : asking?.kind === "ports" ? "Remove a port" : "Delete a step"}`;
- `confirmLabel={asking?.kind === "ports" ? "Remove" : "Delete"}`;
- as its last child, `{asking?.kind === "ports" && portsQuestion(asking.dropped, keyOf)}`.

(h) Delete `frontend/src/routes/editor/StepPanel.tsx`: `git rm frontend/src/routes/editor/StepPanel.tsx`.

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
git commit -m "feat(editor): the step drawer: settings on Setup and Options, unapplied text kept by the editor, port losses asked first (4c-1)"
```

### Task 8: Unapplied edits at the editor's exits

**Files:**
- Modify: `frontend/src/routes/editor/SaveState.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`
- Test: `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 3: `applyAll`, `within`, `Unapplied`;
  - from Task 7: `unapplied`, `unappliedRef`, `keep`, `drop`, `change(): boolean`, `typeOf`, the `Asking` union,
    `confirmDelete`.
- Produces (ruling 18):
  - `SaveState({ state, unapplied? })`: the count beside the draft's state;
  - in `Editor.tsx`:
    - `settleAll(): Unapplied[]`: every edit that can be applied, as one undo step; the rest returned;
    - `whenSettled(action: string, then: () => void)`;
    - the `{ kind: "unapplied"; action; left: Unapplied[]; then }` question;
    - `goBack(u: Unapplied)`: Task 14 makes it focus the field;
  - the leave decision, `guardLeaving` and the page's `beforeunload` count unapplied edits as unsaved work.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/routes/editor/Editor.test.tsx`:

```tsx
/** The `wait` step's drawer, its duration holding text that isn't a number: an edit that can't be applied. */
async function unappliedDuration() {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, DELAY]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: oneStep("flow.delay@1", { duration_s: 5 }) }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "wait" }));
  await userEvent.type(screen.getByLabelText("Duration S"), "x");
}

it("counts the edits not applied beside the save state", async () => {
  await unappliedDuration();
  expect(screen.getByText(/· 1 edit not applied/)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "Discard the edit to Duration S" }));
  expect(screen.queryByText(/edit not applied/)).toBeNull();
});

it("applies what it can before publishing, and asks about the rest", async () => {
  await unappliedDuration();
  await userEvent.click(await screen.findByRole("button", { name: "Publish v1" }));
  const ask = screen.getByRole("dialog", { name: "Edits not applied" });
  expect(ask.textContent).toContain("wait · Duration S: A whole number, like 42.");
  await userEvent.click(within(ask).getByRole("button", { name: "Discard and publish" }));
  expect(screen.getByRole("dialog", { name: "Publish version 1" })).toBeTruthy();
  expect(screen.queryByText(/edit not applied/)).toBeNull();
  expect(stepConfig("wait")).toEqual({ duration_s: 5 });
});

it("applies a JSON edit still being typed when the person leaves", async () => {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, ROUTER]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: oneStep("acme.router@1", { routes: [{ port: "a" }] }, "route") }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "route" }));
  await userEvent.clear(screen.getByLabelText("Routes"));
  await userEvent.paste('[{"port": "a"}, {"port": "c"}]'); // focus stays: nothing has applied it yet
  await act(async () => {
    expect(await mayLeave()).toBe(true); // what the shell's Sign out asks
  });
  expect(stepConfig("route")).toEqual({ routes: [{ port: "a" }, { port: "c" }] });
  act(() => cancelLeaving());
});

it("asks before leaving with an edit it can't apply", async () => {
  await unappliedDuration();
  const decision = mayLeave();
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  expect(ask.textContent).toContain("wait · Duration S: A whole number, like 42.");
  await userEvent.click(within(ask).getByRole("button", { name: "Stay" }));
  expect(await decision).toBe(false);
  expect(screen.getByLabelText<HTMLInputElement>("Duration S").value).toBe("5x"); // still there to fix
});

it("goes back to an edit not applied, in its step's drawer", async () => {
  await unappliedDuration();
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  await userEvent.click(screen.getByRole("button", { name: "Export" }));
  await userEvent.click(within(screen.getByRole("dialog", { name: "Edits not applied" })).getByRole("button", { name: "Go back to them" }));
  expect(within(screen.getByRole("complementary", { name: "wait" })).getByLabelText<HTMLInputElement>("Duration S").value).toBe("5x");
  expect(downloads).toEqual([]);
});

it("discards a deleted step's edits not applied, and says so", async () => {
  await unappliedDuration();
  await userEvent.click(screen.getByRole("button", { name: "Delete step" }));
  const ask = screen.getByRole("dialog", { name: "Delete a step" });
  expect(ask.textContent).toContain("Its edits not applied yet are discarded too.");
  await userEvent.click(within(ask).getByRole("button", { name: "Delete" }));
  expect(screen.queryByText(/edit not applied/)).toBeNull();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/Editor.test.tsx`
Expected: FAIL:
- the save state says nothing of the unapplied edit;
- Publish opens its own question at once;
- leaving goes on, or asks without naming the edit;
- the delete question says nothing of it.

- [ ] **Step 3: Count them in the save state**

In `frontend/src/routes/editor/SaveState.tsx`, change the signature and the returned element:

```tsx
export function SaveState({ state, unapplied = 0 }: { state: SyncState; unapplied?: number }) {
```

```tsx
  // What's typed but not applied isn't saved either (ruling 18): said beside the draft's own state, never hidden by it.
  return (
    <span className={`text-small ${tone}`}>
      {text}
      {unapplied > 0 && (
        <span className="text-warn-ink"> · {unapplied === 1 ? "1 edit not applied" : `${unapplied} edits not applied`}</span>
      )}
    </span>
  );
```

- [ ] **Step 4: Settle them at every exit**

In `frontend/src/routes/editor/Editor.tsx`:

(a) Add to `Asking`:

```ts
  // edits that can't be applied, before what needs the draft settled: an export, a publication, a version view
  | { kind: "unapplied"; action: string; left: Unapplied[]; then: () => void };
```

(b) After `actionsFor`, add:

```ts
  /** Every unapplied edit that can be applied, applied as one undo step; those that can't, returned with their reasons
   * (ruling 18). */
  function settleAll(): Unapplied[] {
    const all = [...unappliedRef.current.values()];
    const { doc: next, applied, left } = applyAll(doc, all, typeOf, () => true);
    for (const u of left) keep(u);
    if (applied.length === 0) return left;
    if (!change(next, applied.length === 1 ? "Applied an edit" : `Applied ${applied.length} edits`)) return all;
    drop(applied.map((u) => u.id));
    return left;
  }

  /** `then`, once every unapplied edit is in the draft; when one can't be, the person decides first (ruling 18). */
  function whenSettled(action: string, then: () => void) {
    const left = settleAll();
    if (left.length === 0) then();
    else setAsking({ kind: "unapplied", action, left, then });
  }

  /** Back to an unapplied edit: its step's drawer. */
  function goBack(u: Unapplied) {
    setSide({ kind: "step", node: u.node });
  }

  const describe = (u: Unapplied) => `${keyOf(u.node)} · ${u.label}: ${u.why ?? "still being typed"}`;
```

(c) In `decide.current`'s `run`, replace the body before `.then(` with:

```ts
    const run = (async () => {
      if (agreed.current) return true;
      // What's typed but not applied goes in first, where it can (ruling 18); what can't makes leaving a question.
      const left = settleAll();
      const s = saver.current;
      if (left.length === 0 && !s?.unsaved) return true;
      if (left.length === 0 && s && (await s.flush().then(() => true, () => false))) return true;
      return new Promise<boolean>((resolve) => setLeaveQuestion(() => resolve));
    })().then((leave) => {
```

(d) Unsaved work counts unapplied edits, for sign-out and for the page itself:
- in `guardLeaving({ … })`, `unsaved: () => (saver.current?.unsaved ?? false) || unappliedRef.current.size > 0,`;
- in `useBlocker({ … })`, `enableBeforeUnload: () => (saver.current?.unsaved ?? false) || unappliedRef.current.size > 0,`.

(e) The actions that need the draft settled go through `whenSettled`:
- the toolbar's Export: `onClick={() => whenSettled("export", () => void exportFile())}`;
- the toolbar's Publish:
  `onClick={() => { if (latest !== null) whenSettled("publish", () => setConfirm({ kind: "publish", expected: latest })); }}`;
- `VersionsPanel`'s `onView`: `onView={(v) => whenSettled("view the version", () => void view(v))}`.

(f) In `confirmDelete`:
- first, before the `ports` branch:

```ts
    if (asking.kind === "unapplied") {
      drop(asking.left.map((u) => u.id)); // discarded, on purpose
      setAsking(null);
      asking.then();
      return;
    }
```

- in the `node` branch, before `change(…)`, discard the step's own:
  `drop([...unappliedRef.current.values()].filter(within(asking.id, "")).map((u) => u.id));`.

(g) The delete `ConfirmDialog`:
- `title`: `"Edits not applied"` for `unapplied`, before the other kinds;
- `confirmLabel`: `` `Discard and ${asking.action}` `` for `unapplied`;
- `cancelLabel={asking?.kind === "unapplied" ? "Go back to them" : "Cancel"}`;
- `onCancel`:

```tsx
        onCancel={() => {
          if (asking?.kind === "unapplied") goBack(asking.left[0]!);
          setAsking(null);
        }}
```

- its children add:

```tsx
        {asking?.kind === "unapplied" &&
          `${asking.left.length === 1 ? "This edit isn't applied, so it would be left out" : "These edits aren't applied, so they would be left out"}: ${asking.left.map(describe).join("; ")}.`}
```

- in the `node` case's text, after "Other steps that read its output will show a problem.", add:
  `{[...unapplied.values()].some(within(asking.id, "")) && " Its edits not applied yet are discarded too."}`.

(h) The leave question's body names the unapplied edits:

```tsx
        {sync.status === "conflict"
          ? "This draft was changed elsewhere, so your changes since then can't be saved here. "
          : sync.status !== "saved" ? "They couldn't be saved. Stay to try again, or keep a copy before you leave. " : ""}
        {unapplied.size > 0 &&
          `${unapplied.size === 1 ? "An edit isn't applied" : "Some edits aren't applied"}: ${[...unapplied.values()].map(describe).join("; ")}. Stay to fix ${unapplied.size === 1 ? "it" : "them"}. `}
        <Button size="sm" onClick={downloadMine}>Download my version</Button>
```

(i) Pass the count to the save state: `<SaveState state={sync} unapplied={unapplied.size} />`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test. 4b's leave, sign-out and publish tests keep passing: with nothing unapplied, `settleAll`
returns at once and changes nothing.

- [ ] **Step 6: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): unapplied edits applied or asked about before leaving, publishing, exporting or viewing a version (4c-1)"
```

### Task 9: Lists, maps and a case's port

**Files:**
- Modify: `frontend/src/routes/editor/drawer/structured.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx` (two call sites, and the port's control)
- Test: `frontend/src/routes/editor/drawer/FieldView.test.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 1: `itemOf`, `entryOf`, `isObject`, `emptyOf`;
  - from Task 2: `freePort`;
  - from Task 6: `DrawerActions.restructure`, `hold`, `release`, `apply`, `held`.
- Produces: `isContainer` (group, list, map), `partNames(spec, value)`, `ContainerParts({ spec, value })`,
  `PortControl`. Every change to a list's or a map's shape goes through `restructure`, so the edits typed inside are
  applied first (ruling 18). A port's and an entry's name are held while typed, and applied when focus leaves or on
  Enter.

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

it("moves an item only once the edits inside it are applied", async () => {
  const sizes = typeWith({ type: "object", properties: { sizes: { type: "array", title: "Sizes", items: { type: "integer" } } } });
  const { config } = showFields(sizes, { config: { sizes: [1, 2] } });
  await userEvent.type(screen.getByLabelText("Sizes, item 2"), "x");
  await userEvent.click(screen.getByRole("button", { name: "Move up: Sizes, item 2" }));
  expect(config()).toEqual({ sizes: [1, 2] }); // it waits: "2x" can't be applied
  expect(screen.getByText("A whole number, like 42.")).toBeTruthy();
  await userEvent.clear(screen.getByLabelText("Sizes, item 2"));
  await userEvent.type(screen.getByLabelText("Sizes, item 2"), "5");
  await userEvent.click(screen.getByRole("button", { name: "Move up: Sizes, item 2" }));
  expect(config()).toEqual({ sizes: [5, 1] });
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
  const { config, held } = showFields(TRANSFORM);
  await userEvent.click(screen.getByRole("button", { name: "Add to Fields" }));
  await userEvent.type(screen.getByLabelText("field_1"), "1 + 1"); // an entry starts as a formula
  const name = screen.getByLabelText("Name: field_1");
  await userEvent.clear(name);
  await userEvent.type(name, "total");
  expect(held().map((u) => [u.kind, u.text])).toEqual([["name", "total"]]); // held while it's typed
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
Expected: FAIL. A list and a map show as JSON, so there's no "Add to Tags", no "Cases, item 2" group and no "Add to
Fields".

- [ ] **Step 3: Write lists, maps and the port's control**

Replace `frontend/src/routes/editor/drawer/structured.tsx` with:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A value made of parts (4c-1, ruling 5): a group's properties, a list's items, a map's entries, each a field of its
// own; and a dynamic port's name, which edges hang on (ruling 9). A change to a list's or a map's shape applies the
// edits typed inside it first, or waits for them (ruling 18). A name is held while typed, applied when focus leaves or
// on Enter.
import { useId, useRef } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { freePort } from "../../../lib/config";
import { emptyOf, entryOf, isObject, itemOf, pointerOf, propertiesOf, type FieldSpec, type Widget } from "../../../lib/schemaForm";
import type { GraphNode } from "../../../lib/workflows";
import { segment, useDrawer } from "./context";
import { FieldView } from "./FieldView";
import type { ControlProps } from "./scalars";

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

const asList = (v: unknown): unknown[] => (Array.isArray(v) ? [...(v as unknown[])] : []);

function ListItems({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const add = useRef<HTMLButtonElement>(null);
  const items = asList(value);
  // Each changes the list's shape: the edits typed inside are applied first, or it waits (ruling 18).
  const move = (from: number, to: number) =>
    drawer.restructure(spec.pointer, {
      path: spec.path,
      make: (list) => {
        const next = asList(list);
        next.splice(to, 0, ...next.splice(from, 1));
        return next;
      },
    });
  const remove = (index: number) => {
    if (drawer.restructure(spec.pointer, { path: [...spec.path, index], make: () => undefined }) !== null) return;
    // Its controls are gone: focus goes to Add. A removal that asks first lands on the drawer's heading instead.
    requestAnimationFrame(() => add.current?.focus());
  };
  const append = () =>
    drawer.restructure(spec.pointer, { path: spec.path, make: (list) => [...asList(list), newItem(itemOf(spec, asList(list).length), drawer.node)] });
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
        <Button ref={add} size="sm" className="self-start" onClick={append}>Add to {spec.label}</Button>
      )}
    </>
  );
}

/** A map entry's name: held while typed, applied when focus leaves or on Enter; refused when empty, `$value` (ruling
 * 15) or another entry's, said here. */
function NameField({ map, name }: { map: FieldSpec; name: string }) {
  const drawer = useDrawer();
  const id = useId();
  const pointer = pointerOf([...map.path, name]);
  const held = drawer.held("name", pointer);
  const why = held?.why ?? null;
  const commit = () => {
    if (held) drawer.apply("name", pointer);
  };
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <label htmlFor={id} className="text-small font-semibold">Name</label>
      <input
        id={id} type="text" value={held?.text ?? name} disabled={!drawer.editable} spellCheck={false} aria-label={`Name: ${name}`}
        aria-invalid={why !== null} aria-describedby={why !== null ? `${id}-p` : undefined}
        onChange={(e) => {
          if (e.target.value === name) drawer.release("name", pointer);
          else drawer.hold("name", pointer, { path: map.path, label: `${map.label}, the name ${name}`, text: e.target.value, why: null, from: name });
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        className={`${controlClass(why !== null)} font-mono`}
      />
      {why !== null && <p id={`${id}-p`} className="text-small text-danger">{why}</p>}
    </div>
  );  // prettier-ignore
}

function MapEntries({ spec, value }: { spec: FieldSpec; value: unknown }) {
  const drawer = useDrawer();
  const add = useRef<HTMLButtonElement>(null);
  const entries = isObject(value) ? Object.entries(value) : [];
  const append = () =>
    drawer.restructure(spec.pointer, {
      path: spec.path,
      make: (map) => {
        const own = isObject(map) ? map : {};
        let n = 1;
        while (Object.hasOwn(own, `field_${n}`)) n++;
        return { ...own, [`field_${n}`]: null };
      },
    });
  return (
    <>
      {entries.length === 0 && <p className="text-small text-muted">None yet.</p>}
      {entries.map(([name], i) => {
        const entry = entryOf(spec, name);
        return (
          <div key={i} className="flex min-w-0 flex-col gap-2">
            <NameField map={spec} name={name} />
            <FieldView spec={entry} />
            {drawer.editable && (
              <Button
                size="sm" variant="danger-outline" className="self-start" aria-label={`Remove: ${name}`}
                onClick={() => {
                  if (drawer.restructure(spec.pointer, { path: entry.path, make: () => undefined }) === null) {
                    requestAnimationFrame(() => add.current?.focus());
                  }
                }}
              >
                Remove
              </Button>
            )}
          </div>
        );  // prettier-ignore
      })}
      {drawer.editable && (
        <Button ref={add} size="sm" className="self-start" onClick={append}>Add to {spec.label}</Button>
      )}
    </>
  );
}

export function ContainerParts({ spec, value }: { spec: FieldSpec; value: unknown }) {
  if (spec.base === "list") return <ListItems spec={spec} value={value} />;
  if (spec.base === "map") return <MapEntries spec={spec} value={value} />;
  return propertiesOf(spec).map((part) => <FieldView key={part.pointer} spec={part} />);
}

/** A dynamic port's name (a switch case's `port`): edges hang on it, so it's held while typed and applied when focus
 * leaves or on Enter, its edges following; a name the graph's format refuses, or another port's, is refused there
 * (ruling 9). */
export function PortControl({ spec, value, id, describedBy, invalid, disabled }: ControlProps) {
  const drawer = useDrawer();
  const held = drawer.held("port", spec.pointer);
  const now = typeof value === "string" ? value : "";
  const commit = () => {
    if (held) drawer.apply("port", spec.pointer);
  };
  return (
    <input
      id={id} type="text" value={held?.text ?? now} disabled={disabled} spellCheck={false}
      aria-describedby={describedBy} aria-invalid={invalid} aria-required
      onChange={(e) => {
        if (e.target.value === now) drawer.release("port", spec.pointer);
        else drawer.hold("port", spec.pointer, { path: spec.path, label: spec.label, text: e.target.value, why: null });
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
      className={`${controlClass(invalid)} font-mono`}
    />
  );  // prettier-ignore
}
```

- [ ] **Step 4: Use them in the field**

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

- [ ] **Step 5: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test. Task 7's JSON tests keep passing: the router's `routes` field is untyped, so it's still
JSON.

- [ ] **Step 6: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): lists, maps and a switch case's port in the step drawer, their edits applied before a move (4c-1)"
```

- [ ] **Step 8: Milestone 2 pause (the owner's review)**

Take screenshots with the session's `compose-shots.mjs`, against the isolated stack after a reset, of these drawers:
- an `if` step's Setup with a formula;
- a loop's Options;
- a switch with two cases;
- a transform's map with a formula entry;
- a group as JSON;
- a field with an edit not applied, and the save state counting it;
- the same drawer read only, for a viewer.

Take each in light and dark, at 1280 and 320 px. Put them beside frame 1c's drawer in the session's checkpoint page
(as `checkpoint-4b.html` did). Stop, and give the owner the page and a short summary. Milestone 3 starts on the
owner's word.

# Milestone 3: references and behaviour

### Task 10: The connection and workflow pickers

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
  - from Task 6: `ControlProps`, `useDrawer`, `controlClass`.
- Produces:
  - `connectionsQuery(tenantId)` (key `["connections", tenantId]`, the Connections page's own);
  - `ConnectionControl`, `WorkflowControl`;
  - harness: `fakeApi(answers: Record<string, () => Response | Promise<Response>>): { method; path; body }[]`,
    `json(body, status?)`, and `showFields(type, { routed: true })` inside a router.

- [ ] **Step 1: Read the API's shapes**

Run: `grep -n '"/api/v1/t/{tenant_id}/connections": {\|"/api/v1/t/{tenant_id}/workflows": {' -A 14 src/api/schema.d.ts`
Expected: each `get` answers a list: `ConnectionOut[]` and `WorkflowOut[]`. The connection's `status` is `"unverified"
| "ok" | "error"`. If either differs, adapt Step 4's code and record a mid-slice ruling.

- [ ] **Step 2: Let tests answer the API and render inside a router**

In `frontend/src/routes/editor/drawer/harness.tsx`:
- add the imports `import { RouterProvider, createMemoryHistory, createRootRoute, createRouter } from
  "@tanstack/react-router";` and `import { vi } from "vitest";`;
- add `routed?: boolean; // inside a router: a link to another page needs one` to `Options`;
- in `showFields`, replace the `render(…)` call with:

```tsx
  const fields = (
    <QueryClientProvider client={client}>
      <Harness type={type} options={options} edits={edits} state={state}>
        {children ?? fieldsOf(type).map((f) => <FieldView key={f.pointer} spec={f} />)}
      </Harness>
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

/** The API's answers, by "METHOD /path" (the path decoded); anything else is a 404, never the network. An answer may
 * be a promise the test settles. Each request is kept. */
export function fakeApi(answers: Record<string, () => Response | Promise<Response>>) {
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
- add `afterEach` and `beforeEach` to the vitest import (it has `vi` since Task 9), and `fakeApi` to the harness import;
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

### Task 11: Live options, on request, in their scope

**Files:**
- Create: `frontend/src/routes/editor/drawer/LiveOptions.tsx`
- Modify: `frontend/src/routes/editor/drawer/FieldView.tsx` (`controlFor`)
- Test: `frontend/src/routes/editor/drawer/LiveOptions.test.tsx`

**Interfaces:**
- Consumes:
  - `ApiError`, `client`, `ok`, `Schemas` (`lib/client.ts`), and `idKey`, `sameId` (`lib/graph.ts`);
  - from Task 1: `fieldsOf`;
  - from Task 2: `valueAt`;
  - from Task 10: `connectionsQuery`, `fakeApi`, `json`.
- Produces: `OptionsControl`. Its choices belong to a scope: tenant, type, field, and the connection's id and
  revision (ruling 14).

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
const C2 = "00000000-0000-4000-8000-0000000000c2";
const CONNECTIONS = "GET /api/v1/t/t1/connections";
const OPTIONS = "POST /api/v1/t/t1/node-types/acme.sites@1/options";
const connection = (id: string, name: string) => ({
  id, name, type: "acme", status: "ok", revision: 1, config: {}, secret_set: true, status_detail: "", privilege: null, last_verified_at: null,
});  // prettier-ignore
const both = () => json([connection(C1, "Prod"), connection(C2, "Lab")]);

it("never loads on render", async () => {
  const sent = fakeApi({ [CONNECTIONS]: both });
  showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" }); // what loads by itself has loaded
  expect(sent.map((r) => `${r.method} ${r.path}`)).toEqual([CONNECTIONS]);
});

it("asks for a connection before loading", () => {
  fakeApi({ [CONNECTIONS]: both });
  showFields(REMOTE);
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices" }).disabled).toBe(true);
  expect(screen.getByText("Choose the step's connection first: the choices come from it.")).toBeTruthy();
});

it("loads the choices on request, with the connection and the text typed, and sets the one chosen", async () => {
  const sent = fakeApi({
    [CONNECTIONS]: both,
    [OPTIONS]: () => json({ options: [{ value: "s1", label: "HQ" }, { value: "s2", label: "Lab" }] }),
  });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" }); // its revision known: the scope is settled
  await userEvent.type(screen.getByLabelText("Site"), "h");
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
  const choices = await screen.findByLabelText<HTMLSelectElement>("Choices for Site");
  expect(sent.find((r) => r.path.endsWith("/options"))!.body).toEqual({ field: "site_id", connection_id: C1, query: "h" });
  await userEvent.selectOptions(choices, "HQ (s1)");
  expect(config().site_id).toBe("s1");
});

it("says why choices couldn't load, keeping a typed value", async () => {
  fakeApi({ [CONNECTIONS]: both, [OPTIONS]: () => json({ error: "plugin_calls_busy" }, 503) });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.type(screen.getByLabelText("Site"), "hq-1");
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
  expect(await screen.findByText("Too many requests right now. Try again in a moment.")).toBeTruthy();
  expect(config().site_id).toBe("hq-1");
});

it("drops choices when their connection changes, and ignores an answer for the old one", async () => {
  let settle: (answer: Response) => void = () => undefined;
  let calls = 0;
  const sent = fakeApi({
    [CONNECTIONS]: both,
    [OPTIONS]: () => (++calls === 1 ? json({ options: [{ value: "s1", label: "HQ" }] }) : new Promise<Response>((resolve) => (settle = resolve))),
  });
  const { config } = showFields(REMOTE, { config: { connection: C1 } });
  await screen.findByRole("option", { name: "Prod · verified" });
  await userEvent.click(screen.getByRole("button", { name: "Show choices" }));
  await screen.findByLabelText("Choices for Site"); // Prod's
  await userEvent.selectOptions(await screen.findByLabelText("Connection"), "Lab · verified");
  expect(screen.queryByLabelText("Choices for Site")).toBeNull(); // Prod's choices went with Prod
  await userEvent.click(screen.getByRole("button", { name: "Show choices" })); // Lab's, still on their way
  await userEvent.selectOptions(screen.getByLabelText("Connection"), "Prod · verified");
  settle(json({ options: [{ value: "s9", label: "Lab only" }] }));
  await vi.waitFor(() => expect(screen.getByRole<HTMLButtonElement>("button", { name: "Show choices" }).disabled).toBe(false));
  expect(screen.queryByLabelText("Choices for Site")).toBeNull(); // Lab's answer never shows under Prod
  expect(sent.filter((r) => r.path.endsWith("/options")).map((r) => (r.body as { connection_id: string }).connection_id)).toEqual([C1, C2]);
  expect(config().connection).toBe(C1);
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
// service, so it's never a side effect of opening a drawer (D24). Choices belong to their scope (tenant, type, field,
// the connection's id and revision): a new scope drops them, and an answer for an older one is ignored. They help;
// they never gate what's typed.
import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { controlClass } from "../../../components/Field";
import { ApiError, client, ok, type Schemas } from "../../../lib/client";
import { valueAt } from "../../../lib/config";
import { idKey, sameId } from "../../../lib/graph";
import { fieldsOf } from "../../../lib/schemaForm";
import { useDrawer } from "./context";
import { connectionsQuery } from "./pickers";
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
  const type = spec.type;
  const takes = type.credentials.length > 0;
  const field = fieldsOf(type).find((f) => f.widget === "connection");
  const connection = field ? valueAt(drawer.node.config ?? {}, field.path) : undefined;
  const chosen = typeof connection === "string" ? connection : null;
  // The connection's revision: a connection changed elsewhere is another scope. Read from the tenant's list, which
  // the connection picker loads too: a local read, never the service.
  const listed = useQuery({ ...connectionsQuery(drawer.tenantId), enabled: takes && chosen !== null });
  const revision = chosen === null ? null : (listed.data?.find((c) => sameId(c.id, chosen))?.revision ?? null);
  const scope = JSON.stringify([drawer.tenantId, type.ref, spec.name, chosen === null ? null : idKey(chosen), revision]);
  const current = useRef(scope);
  current.current = scope;
  const [choices, setChoices] = useState<{ scope: string; state: Choices }>({ scope, state: { status: "idle" } });
  const shown: Choices = choices.scope === scope ? choices.state : { status: "idle" };
  const blocked = takes && chosen === null;
  const unsettled = takes && chosen !== null && listed.isPending; // the scope isn't known until its revision is
  const text = typeof value === "string" ? value : "";
  async function load() {
    const asked = scope;
    setChoices({ scope: asked, state: { status: "loading" } });
    try {
      const answer = await ok(
        client.POST("/api/v1/t/{tenant_id}/node-types/{ref}/options", {
          params: { path: { tenant_id: drawer.tenantId, ref: type.ref } },
          body: { field: spec.name, connection_id: chosen, query: text.slice(0, 200) },
        }),
      );
      if (current.current === asked) setChoices({ scope: asked, state: { status: "done", options: answer.options } });
    } catch (e) {
      const why = (e instanceof ApiError && WHY[e.code]) || "The choices couldn't load.";
      if (current.current === asked) setChoices({ scope: asked, state: { status: "failed", why } });
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
        <Button className="shrink-0" disabled={disabled || blocked || unsettled || shown.status === "loading"} onClick={() => void load()}>
          Show choices
        </Button>
      </div>
      {blocked && <p className="text-small text-muted">Choose the step&apos;s connection first: the choices come from it.</p>}
      <p role="status" className={`text-small ${shown.status === "failed" ? "text-danger" : "text-muted"}`}>{said(shown)}</p>
      {shown.status === "done" && shown.options.length > 0 && (
        <select
          aria-label={`Choices for ${spec.label}`} value="" disabled={disabled} className={controlClass(false)}
          onChange={(e) => {
            onChange(e.target.value, false);
            document.getElementById(id)?.focus();
          }}
        >
          <option value="">{shown.options.length === 1 ? "1 choice" : `${shown.options.length} choices`}</option>
          {shown.options.map((o, i) => (
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
git commit -m "feat(editor): live options load only when asked, through the step's connection, kept to their scope (4c-1)"
```

### Task 12: The error-handling chip and its error port

**Files:**
- Modify: `frontend/src/routes/editor/drawer/ErrorHandling.tsx` (the section)
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (the chip opens it)
- Test: `frontend/src/routes/editor/drawer/ErrorHandling.test.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 3: `limitProblem`, `Limit`;
  - from Task 6: `useDrawer` (`options`, `held`, `hold`, `release`), `useSession`, `useText`;
  - from Task 7: the editor's `options` action, through `writeDraft`, which asks before ports go.
- Produces: `ErrorHandling()`, rendered inside the drawer's context.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/routes/editor/drawer/ErrorHandling.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { StepOptions } from "../../../lib/config";
import type { GraphNode } from "../../../lib/workflows";
import { DELAY } from "../../../test/nodeTypes";
import { ErrorHandling, chipText } from "./ErrorHandling";
import { fakeApi, showFields } from "./harness";

beforeEach(() => {
  fakeApi({});
});
afterEach(() => {
  vi.restoreAllMocks();
});

const node = (options?: StepOptions): GraphNode => ({ id: "n1", key: "wait", type: "flow.delay@1", ...(options ? { options } : {}) });

it("says what a failure does in words, and the limits the step sets", () => {
  expect(chipText(node(), DELAY)).toBe("On error: fail the run");
  expect(chipText(node({ on_error: "port", max_attempts: 5, timeout_s: 60 }), DELAY)).toBe("On error: route to the error port · 5 attempts");
  expect(chipText(node({ on_error: "continue", max_attempts: 1, timeout_s: 30 }), DELAY)).toBe("On error: continue · 1 attempt · 30 s");
});

it("sets what a failure does, and leaves an emptied limit to the type", async () => {
  const { node: step } = showFields(DELAY, { options: { max_attempts: 5 } }, <ErrorHandling />);
  await userEvent.selectOptions(screen.getByLabelText("When it fails"), "Continue with the next step");
  expect(step().options).toEqual({ max_attempts: 5, on_error: "continue" });
  expect(screen.getByText("If empty: 3.")).toBeTruthy();
  await userEvent.clear(screen.getByLabelText("Attempts"));
  expect(step().options).toEqual({ on_error: "continue" });
});

it("holds attempts and a timeout the graph's format refuses, writing neither", async () => {
  const { node: step, held } = showFields(DELAY, {}, <ErrorHandling />);
  await userEvent.type(screen.getByLabelText("Attempts"), "25");
  expect(screen.getByText("A whole number from 1 to 20.")).toBeTruthy();
  await userEvent.type(screen.getByLabelText("Timeout (seconds)"), "0");
  expect(screen.getByText("A number of seconds above 0, up to 86,400.")).toBeTruthy();
  expect(step().options).toEqual({ max_attempts: 2 }); // "2", before the "5"
  expect(held().map((u) => [u.kind, u.text])).toEqual([["limit", "25"], ["limit", "0"]]);
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
import { Field, Select } from "../../../components/Field";
import type { StepOptions } from "../../../lib/config";
import { limitProblem, type Limit } from "../../../lib/unapplied";
import { useDrawer, useSession } from "./context";
import { useText } from "./scalars";
```

```tsx
/** A limit the step sets for itself: empty takes the type's. The graph's bounds are checked here, since a draft
 * breaking them isn't saved at all (ruling 7); text they refuse is held, with why (ruling 18). */
function LimitField({ name, label, fallback }: { name: Limit; label: string; fallback: string }) {
  const drawer = useDrawer();
  const own = drawer.node.options ?? {};
  const pointer = `/options/${name}`;
  const held = drawer.held("limit", pointer);
  const { mark, onFocus } = useSession(`${drawer.node.id}${pointer}`);
  const [text, setText] = useText(
    own[name] ?? undefined,
    (v) => (typeof v === "number" ? String(v) : ""),
    (t, v) => (t.trim() === "" ? v === undefined : Number(t) === v),
    held?.text,
  );
  return (
    <div onFocus={onFocus}>
      <Field
        label={label} hint={`If empty: ${fallback}.`} error={held?.why ?? undefined} value={text} disabled={!drawer.editable}
        onChange={(e) => {
          setText(e.target.value);
          const why = limitProblem(name, e.target.value);
          if (why !== null) return drawer.hold("limit", pointer, { path: [name], label, text: e.target.value, why });
          drawer.release("limit", pointer);
          const t = e.target.value.trim();
          drawer.options({ ...own, [name]: t === "" ? undefined : Number(t) }, mark());
        }}
      />
    </div>
  );  // prettier-ignore
}

/** The chip's section (ruling 10): what a failure does, then the attempts and the timeout. */
export function ErrorHandling() {
  const drawer = useDrawer();
  const type = drawer.type;
  if (!type) return null; // a type this server doesn't know: its options are kept, not shown
  const own = drawer.node.options ?? {};
  return (
    <section id="error-handling" aria-label="Error handling" className="flex flex-col gap-4">
      <Select
        label="When it fails" value={own.on_error ?? "fail"} disabled={!drawer.editable}
        onChange={(e) => drawer.options({ ...own, on_error: e.target.value as StepOptions["on_error"] })}
      >
        <option value="fail">Fail the run</option>
        <option value="continue">Continue with the next step</option>
        <option value="port">Route to an error port</option>
      </Select>
      <LimitField name="max_attempts" label="Attempts" fallback={String(type.retry.max_attempts)} />
      <LimitField name="timeout_s" label="Timeout (seconds)" fallback={`${type.timeout_s} s`} />
    </section>
  );  // prettier-ignore
}
```

- [ ] **Step 4: Make the chip open it**

In `frontend/src/routes/editor/drawer/StepDrawer.tsx`:
- import `ErrorHandling` beside `chipText`;
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

- after the header's closing `</div>`, add `{handling && <ErrorHandling />}`.

The editor needs nothing new: its `options` action (Task 7) writes through `writeDraft`, which asks before the error
port's edges go.

- [ ] **Step 5: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test. The 4b version test still finds "30 s", now in the chip's button.

- [ ] **Step 6: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): a step's error handling in a chip, limits checked, the error port's edges asked before they go (4c-1)"
```

### Task 13: Key rename

**Files:**
- Create: `frontend/src/routes/editor/drawer/KeyField.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (the rename, and its note)
- Modify: `frontend/src/routes/editor/Editor.tsx` (the note, until the next edit)
- Test: `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes:
  - from Task 3: the `key` kind of unapplied edit (`applyUnapplied` renames, and answers `said` and `note`);
  - from Task 7: `applyEdit`, which announces `said`.
- Produces:
  - `KeyField({ onRenamed }: { onRenamed: () => void })`: the rename held as an unapplied edit of kind `key` at
    pointer `""`;
  - StepDrawer prop `note: string | null`;
  - in `Editor.tsx`, `renamed: { doc: GraphDoc; text: string } | null`, said only while `doc` is the draft.

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

async function openFetch() {
  answers.set("GET /api/v1/node-types", () => json([...TYPES, IF]));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: readers() }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "fetch" }));
  await userEvent.click(screen.getByRole("button", { name: "Rename" }));
}

async function renameTo(key: string) {
  const field = screen.getByLabelText("Key");
  await userEvent.clear(field);
  await userEvent.type(field, `${key}{Enter}`);
}

it("says which formulas mention the old key, until the next edit", async () => {
  await openFetch();
  await renameTo("load");
  const heading = screen.getByRole("heading", { name: "load" });
  await vi.waitFor(() => expect(document.activeElement).toBe(heading));
  expect(screen.getByText("1 formula mentions fetch and keeps its text: check it.")).toBeTruthy();
  expect(stepConfig("copy")).toEqual({ fields: { x: { $value: { kind: "ref", path: "steps.load.output" } } } });
  await userEvent.keyboard("{Control>}z{/Control}"); // one step: the key and its references
  expect(stepConfig("copy")).toEqual({ fields: { x: { $value: { kind: "ref", path: "steps.fetch.output" } } } });
  expect(screen.getByRole("heading", { name: "fetch" })).toBeTruthy();
  expect(screen.queryByText(/mentions fetch/)).toBeNull(); // said only while it's true of the draft
});

it("refuses a key another step has, and keeps its own", async () => {
  await openFetch();
  await renameTo("use");
  expect(screen.getByText("Another step is already called use.")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "fetch" })).toBeTruthy();
});

it("disables an open rename when the draft can't change, and never says it renamed", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "draft_conflict" }, 409));
  await openFetch();
  await userEvent.type(screen.getByLabelText("Key"), "_v2"); // typed, not applied
  await userEvent.click(screen.getByRole("button", { name: "Move fetch right" })); // an edit, whose save conflicts
  await vi.waitFor(() => expect(screen.getByLabelText<HTMLInputElement>("Key").disabled).toBe(true), { timeout: 3000 });
  expect(screen.getByRole<HTMLButtonElement>("button", { name: "Rename" }).disabled).toBe(true);
  expect(screen.getByLabelText<HTMLInputElement>("Key").value).toBe("fetch_v2"); // kept, never lost
  expect(screen.getByRole("heading", { name: "fetch" })).toBeTruthy();
  expect(screen.queryByText(/^Renamed/)).toBeNull();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor/Editor.test.tsx`
Expected: FAIL. There's no "Rename" button.

- [ ] **Step 3: Write the rename**

Create `frontend/src/routes/editor/drawer/KeyField.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A step's key renamed from its drawer (4c-1, ruling 11). It's checked before it's written: a key the graph's format
// refuses isn't saved, and a CEL word or another step's key never reads. Every structured reference follows. What's
// typed is an unapplied edit (ruling 18): kept while the drawer closes, disabled while the draft can't change, and
// said, never as if it had worked, when it's refused.
import { useEffect, useRef, useState } from "react";
import { Button } from "../../../components/Button";
import { Field } from "../../../components/Field";
import { useDrawer } from "./context";

export function KeyField({ onRenamed }: { onRenamed: () => void }) {
  const drawer = useDrawer();
  const held = drawer.held("key", "");
  const [open, setOpen] = useState(held !== undefined); // a rename typed before the drawer closed is still open
  const box = useRef<HTMLDivElement>(null); // Field makes its own input: focus finds it here
  const opener = useRef<HTMLButtonElement>(null);
  const current = drawer.node.key;
  const disabled = !drawer.editable;
  useEffect(() => {
    if (open) box.current?.querySelector("input")?.focus();
  }, [open]);
  const close = () => {
    drawer.release("key", ""); // Cancel, Escape: dropped, on purpose
    setOpen(false);
    requestAnimationFrame(() => opener.current?.focus());
  };
  const apply = () => {
    if (disabled) return;
    if (!held || held.text.trim() === current) return close();
    if (drawer.apply("key", "") !== null) return; // refused: its reason shows at the field, never as done
    setOpen(false);
    onRenamed();
  };
  if (!open) {
    return drawer.editable ? (
      <Button ref={opener} size="sm" className="self-start" onClick={() => setOpen(true)}>Rename</Button>
    ) : null;
  }
  return (
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
        label="Key" value={held?.text ?? current} disabled={disabled} spellCheck={false} autoCapitalize="off"
        error={held?.why ?? undefined}
        onChange={(e) => {
          if (e.target.value === current) drawer.release("key", "");
          else drawer.hold("key", "", { path: [], label: "Key", text: e.target.value, why: null });
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") apply();
        }}
      />
      <div className="flex gap-2">
        <Button size="sm" variant="primary" disabled={disabled} onClick={apply}>Rename</Button>
        <Button size="sm" disabled={disabled} onClick={close}>Cancel</Button>
      </div>
    </div>
  );  // prettier-ignore
}
```

- [ ] **Step 4: Put it under the drawer's heading, with its note**

In `frontend/src/routes/editor/drawer/StepDrawer.tsx`:
- import `KeyField` from `./KeyField`;
- add the prop `note: string | null`;
- after the `<h2>`, add:

```tsx
            <KeyField onRenamed={() => requestAnimationFrame(() => heading.current?.focus())} />
            {note !== null && <p role="status" className="text-small">{note}</p>}
```

- [ ] **Step 5: Keep the note only while it's true**

In `frontend/src/routes/editor/Editor.tsx`:
- add, beside the unapplied edits, `const [renamed, setRenamed] = useState<{ doc: GraphDoc; text: string } | null>(null);
  // a rename's word on formulas, true of the draft it made (ruling 11)`;
- in `applyEdit`, after a write that succeeded, keep the note with the document it describes: replace its last
  lines with:

```ts
    if (why !== null) keep({ ...u, why });
    else if (!("problem" in result) && result.note !== null) setRenamed({ doc: result.doc, text: result.note });
    return why;
```

- pass `note={renamed !== null && renamed.doc === doc ? renamed.text : null}` to `StepDrawer`. The next edit, an undo
  among them, makes another document, and the note goes.

- [ ] **Step 6: Run the tests to see them pass**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: PASS, every test.

- [ ] **Step 7: Run every check**

Run: `npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 lint`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(editor): rename a step, its references following, the formulas that mention it said until the next edit (4c-1)"
```

### Task 14: A problem's "Go to", and "Go back to them", focus the field

**Files:**
- Modify: `frontend/src/routes/editor/ProblemsPanel.tsx`
- Modify: `frontend/src/routes/editor/drawer/StepDrawer.tsx` (`focusField`)
- Modify: `frontend/src/routes/editor/Editor.tsx` (`Side`'s field, `onJump`)
- Test: `frontend/src/routes/editor/ProblemsPanel.test.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: from Task 8, `goBack(u)`.
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

it("goes back to an edit not applied, at its field", async () => {
  await unappliedDuration();
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  await userEvent.click(screen.getByRole("button", { name: "Export" }));
  await userEvent.click(within(screen.getByRole("dialog", { name: "Edits not applied" })).getByRole("button", { name: "Go back to them" }));
  await vi.waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Duration S")));
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL:
- `onJump` is called with `"n1"` alone;
- in the editor, "Go to each" focuses the step, never the drawer;
- "Go back to them" opens the drawer at its heading, not the field.

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

- pass `focusField={side?.kind === "step" ? (side.field ?? null) : null}` to `StepDrawer`;
- `goBack` (Task 8) lands on the edit's field the same way:

```ts
  /** Back to an unapplied edit: its step's drawer, at its field (ruling 16's way). */
  function goBack(u: Unapplied) {
    setSide({ kind: "step", node: u.node, field: { pointer: u.pointer, n: ++jumps.current } });
  }
```

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
git commit -m "feat(editor): a problem's Go to, and an unapplied edit's Go back, open the drawer at the field (4c-1, ruling 83)"
```

# Milestone 4: end to end

### Task 15: The browser flows, every check, the ledger and the checkpoint

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

test("a renamed step keeps the references to it, and says which formulas mention it", async ({ page }) => {
  await importFile(page, "References", "e2e/fixtures/references.dewpoint.json");
  await page.getByRole("button", { name: /^fetch, Transform/ }).click();
  const fetch = page.getByRole("complementary", { name: "fetch" });
  await fetch.getByRole("button", { name: "Rename" }).click();
  await fetch.getByLabel("Key").fill("load");
  await fetch.getByLabel("Key").press("Enter");
  const load = page.getByRole("complementary", { name: "load" });
  await expect(load.getByRole("heading", { name: "load" })).toBeFocused();
  await expect(load.getByText("1 formula mentions fetch and keeps its text: check it.")).toBeVisible();
  await page.getByRole("button", { name: /^use, Transform/ }).click();
  const use = page.getByRole("complementary", { name: "use" });
  await expect(use.locator('[data-pointer="/fields/copy"] output')).toHaveText("steps.load.output.n");
  await expectAccessible(page, "editor: drawer, a reference and a map");
});

test("an edit not applied is kept through tabs, and asked about before an export", async ({ page }) => {
  await newWorkflow(page, "Unapplied flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.delay@1/ }).click();
  await page.getByRole("button", { name: /^delay, Delay/ }).click();
  const drawer = page.getByRole("complementary", { name: "delay" });
  await drawer.getByLabel("Duration S").fill("1x");
  await expect(page.getByText(/· 1 edit not applied/)).toBeVisible();
  await drawer.getByRole("tab", { name: "Options" }).click();
  await drawer.getByRole("tab", { name: "Setup" }).click();
  await expect(drawer.getByLabel("Duration S")).toHaveValue("1x");
  await page.getByRole("button", { name: "Export" }).click();
  const ask = page.getByRole("dialog", { name: "Edits not applied" });
  await expect(ask).toContainText("delay · Duration S: A whole number, like 42.");
  await expectAccessible(page, "editor: edits not applied");
  await ask.getByRole("button", { name: "Go back to them" }).click();
  await expect(drawer.getByLabel("Duration S")).toBeFocused();
  await drawer.getByLabel("Duration S").fill("30");
  await expect(page.getByText(/edit not applied/)).toHaveCount(0);
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

This plan's rulings join the numbered list as 96 to 113 only when the owner accepts the slice, as 68 to 95 did.

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

---

## Self-review

- **Spec coverage.**
  - Outline §2's 4c, for the drawer:
    - rulings 2–6 (Tasks 6, 7 and 9);
    - the pickers (Tasks 10 and 11);
    - error handling (Task 12);
    - rename (Task 13);
    - a problem's field (Task 14).
  - D17 (saves and undo): Tasks 4, 7 and 8.
  - D19 (formula mode, hints): Tasks 6 and 9.
  - D21–D24:
    - Tabs pinned and checked: Task 5;
    - the CSP in the browser: Tasks 7 and 15;
    - no Mist calls: Tasks 11 and 15;
    - AI tells: the guard in every task's suite run, and the checkpoint.
  - Data pills, the condition builder, samples, triggers and the Test tab are 4c-2, 4c-3 and 4d (ruling 1).
- **The review of revision 1.** Each correction maps to a ruling and its tasks in "Changes from revision 1". Its
  tests sit in the Review Focus lines.
- **Placeholders.** None: every code step has its code. Where the running app decides a label (Task 15's "+" names and
  the Mist step's key), the step says how to check it and record the difference.
- **Names across tasks.**
  - `setConfig`, `setOptions`, `renamePort`, `renameEntry`, `freePort`, `keyProblem`, `renameKey`, `parseJson` and
    `admission` (Task 2) are the names Tasks 3, 6, 7 and 9 call.
  - `Unapplied`, `Holding`, `applyUnapplied`, `applyAll`, `within`, `droppedWhy`, `parseNumber` and `limitProblem`
    (Task 3) are what the harness, the editor and the controls use (Tasks 6, 7, 8, 12).
  - `record(h, next, mark)` (Task 4) is what `change` calls (Task 7).
  - `DrawerActions` (Task 6) is what the harness and `actionsFor` (Task 7) both implement. Its members keep their
    signatures through Tasks 9–13.
  - `ControlProps` (Task 6) is what every control takes (Tasks 9–11).
  - `StepDrawer` gains props in Task 12 (none: the chip's state is its own), Task 13 (`note`) and Task 14
    (`focusField`), and the editor passes each.
- **Review Focus.** Each line names the tests that pin it, in their owning tasks: Tasks 1, 2, 3, 4, 6, 7, 8, 9, 11,
  12 and 13.
