# Editor UI 4b: Workflows and Canvas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Revision 3 (2026-10-06).** The owner reviewed revision 1 (325fc14: seven corrections) and revision 2 (089c004:
five corrections and one smaller); "Revision 2" and "Revision 3" below list what changed and where. Execution waits
for the owner's approval.

**Goal:** A tenant member can list workflows with their state at a glance, create one (blank or imported from a file),
build its graph on a canvas with a pointer or the keyboard alone, have every edit saved without ever overwriting
someone else's, see its problems on the steps they concern, and publish it with a confirmation that names the version.

**Architecture:**
- **The API answers what the editor needs (milestone 1).** Node types also report how each step runs: side effect,
  credentials, capabilities, retry and timeout defaults (B5). Every workflow route answers a named model, and the draft
  PUT documents its body as `Graph` (ledger ruling 47). The list and a workflow's summary gain the last live run and,
  apart, the last simulated one, the runs of the last 24 hours, whether the draft differs from the active version, and
  why it needs attention, from live runs only (B3); the list reads a fixed number of times whatever its length, and a
  probe measures its run-history read for the owner's ruling on an index. A version can be read whole, graph included,
  with its `engine_abi` (B4a); publish can name the newest version it expects, checked under the lock that numbers
  the new one. A workflow exports to a JSON document whose connections and workflow references are typed
  placeholders, and imports with each re-bound (B12), both fail-closed: what can't be done for certain is refused. No
  migration.
- **The list and the chooser (milestone 2).** Workflows joins the rail and becomes a tenant's landing screen. The list
  (1a) filters by state and name, toggles a workflow on or off, and exports it. "New workflow" (1b) starts blank or
  from an imported file, asking for each binding.
- **The canvas (milestone 3).** The draft is a document the editor changes only through pure operations, with local
  undo and redo. React Flow draws it; dagre lays it out on demand. A start card heads the graph; "+" sits on every edge
  and every free port; `A` opens the node-type picker. One roving tab stop covers the canvas: arrows follow the edges
  and reach every item drawn, cycles and malformed imports included, and every action a pointer has, the keyboard has
  (D16). A step is placed with a click as well as a drag (WCAG 2.5.7).
- **Saving, problems and publishing (milestone 4).** At most one save in flight, edits coalesced, `If-Match` the
  revision the last save returned; a conflict turns the editor read-only (D17). The editor opens on a fresh snapshot,
  and leaving it saves first or asks. A check is of one saved revision and is called current only while it's what's
  on the screen; problems sit in a panel and, when current, on the steps; a problem focuses its step. Publish flushes
  the save, confirms with the version number, and binds that number at the server; outcomes are read back when an
  answer is lost, never assumed. A versions panel views any version read-only and makes one active.

**Tech Stack:** Backend: Python 3.12, FastAPI 0.141.1, pydantic 2.13.5, SQLAlchemy async (asyncpg), PostgreSQL 16 via
testcontainers (`postgres:16-alpine`), pytest with pytest-xdist, ruff, mypy strict, import-linter, `uv`. Frontend: React
19, Vite 6, TypeScript, TanStack Router and Query, Tailwind 4.3.3, openapi-fetch 0.17.0 over openapi-typescript 7.13.0
types, cmdk 1.1.1, Radix; new: `@xyflow/react` 12.12.0, `@dagrejs/dagre` 3.1.1, `@radix-ui/react-switch` 1.3.7 (approved
in the outline's §4, at exactly these versions). Tests: vitest (jsdom) and Testing Library; Playwright 1.63.0 with
Chromium 1243 and @axe-core/playwright 4.13.0, through the browser gate (`e2e/gate.ts`), against the isolated Compose
stack (`dewpoint-ui4a`, ledger ruling 24). pnpm 12.6.0 runs as `npx -y pnpm@12.6.0`.

**Spec:** `docs/superpowers/plans/2026-10-05-editor-ui-4-outline.md` (revision 4, ruled 2026-10-05): §2's slice 4b,
decisions D8, D9, D16, D17, D19, D21–D24 and D26, backend items B3, B4a, B5 and B12, §6 (no AI tells). The ledger
`docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` holds the owner's rulings and the mid-slice rulings 1–67
that 4a settled; 4b's own go into it as it runs. Design frames 1a, 1b and 1c of
`docs/design/2026-10-05-dewpoint-ui.dc.html` (lines 32–209), as data.

## Global Constraints

- The CSP stays exactly `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self';
  connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'`. No inline
  script, no injected `<style>`, no third-party or CDN asset: every library is bundled. The browser gate fails any
  screen that violates it.
- WCAG 2.2 AA: text 4.5:1, boundaries, focus rings and graphics 3:1 (PAIRS in `src/styles/tokenNames.ts`); reflow at
  320 px for the list; every canvas action reachable without a pointer (2.1.1), and a single-pointer alternative to
  every drag (2.5.7). Axe checks each screen in the browser gate.
- No AI tells (outline §6, owner 2026-10-05): no coloured side borders, gradients, glows, halos, blur, tinted icon
  tiles, emoji, eyebrow labels, pill shapes off data pills, heavy shadows, radii over 8 px (dialogs 12 px), decorative
  motion, raw colours outside `tokens.css`, marketing copy or "!". The vitest guard (`src/test/aiTells.ts`) scans
  `src/`; the checkpoint reviewer checks the screens. The design's own tells are stripped: the dot grid's CSS gradient
  (React Flow draws dots as SVG), the tinted icon tiles on steps (the mono type code instead), the 4 px halo on the
  selected step (a 2 px outline), circular "+" buttons (4 px radius squares).
- No new dependency beyond the three named above, each at its recorded version, each passing `scripts/licence-check.mjs`
  (D22) with no new exception, and each listed by the build's third-party notices (ledger ruling 65).
- No real Mist or SaaS call, ever: unit tests use fixtures; e2e drives only the flow plugin's nodes (D24).
- Logs name an exception's type only. No secret in a URL, a log or browser storage; the client keeps no draft in
  browser storage (D20's spirit: the server holds the draft).
- The API decides every write: the client hides what a role can't do, never relies on hiding it.
- No migration (none of B3, B4a, B5, B12 needs one). No Alembic autogenerate.
- Verify every library API against the installed package before relying on it (React Flow's class names and props,
  dagre's, FastAPI's schema output), never from memory.
- Every route the web client calls answers a named model that forbids extra keys (B1); `frontend/src/api/openapi.json`
  and `schema.d.ts` are regenerated in the same commit as any API change (`uv run dewpoint api openapi >
  ../frontend/src/api/openapi.json`, then `npx -y pnpm@12.6.0 gen:api`), and CI's drift checks hold them.
- GitHub Actions minutes are spent: every check runs locally; a commit that will head a push carries `[skip ci]`
  (owner, 2026-10-06). Nothing is pushed and no PR opened without the owner's OK in chat.

## Review Focus

The input classes and conditions most likely to bite a person using this, which the tasks below pin with a test
(each named where it lives):
- **Two people at one workflow.** A second save's `If-Match` is stale: the editor turns read-only and keeps the local
  work downloadable, never retrying over the other's draft (Task 13: `a 409 stops every save and keeps the
  document`). A second publisher lands first: the confirmation's number is refused at the server and asked again,
  never silently published as the next one (Task 4: `two publishers naming one version publish it once`; Task 15:
  `asks again, with the new number`; Task 16's two-page flow). An activation lands between a save's read and its
  swap: the answer compares with the version active when it landed (Task 3: `a save compares with the version
  active when it lands`). A lost answer is read back, and another's publication is never taken for this draft's
  (Task 15: `never takes another's publication for this draft's`, `takes the active version from the read`).
- **Edits faster than saves, and leaving before the save.** Typing or dragging during a save never sends two saves at
  once nor drops the last edit (Task 13: `edits during a save coalesce into exactly one next save`); the breadcrumb,
  the rail, the palette, the tenant switcher, sign-out and an ended session all wait for the save, and ask when it
  can't be made, before anything is revoked or cleared; a background failure never closes the editor (Task 13:
  `saves before leaving through a link`, `asks before leaving work it couldn't save`, `answers sign-out's question`,
  `stays open … when the step types fail to refresh or the cache is cleared`; Shell: `signs out only once every
  open editor has had its say`; router: `leaves unsaved editor work on screen when the session ends`; Task 16).
- **A check that doesn't describe what's on the screen.** An answer for an older revision, edits since, or a failed
  request: never "No problems", never badges on the steps (Task 14: `calls an answer for an older revision stale`,
  `says it's checking before the first answer`, `says when a check failed`); an older draft's publish findings never
  count as current (Task 15: `keeps an older draft's publish findings out of the current problems`).
- **A draft from elsewhere with what the editor can't model** (an unknown or retired type, a port the type no longer
  has, a cycle no entry reaches, an edge to a step that isn't there, a `settings` block): the canvas draws it, keeps
  every field it doesn't touch byte for byte, reaches every item with the keys (at a join, along the branch taken),
  and export refuses what it can't make portable for certain (Task 9: `keeps what it doesn't touch`; Task 12:
  `reaches every item … with the keys alone`, `keeps to the branch it came by at a join`; Task 15: the join read only
  for a viewer, a conflict and a viewed version; Task 5: `a draft that can't be made portable isn't exported`; Task
  12's imported cycle in the browser).
- **An import that would carry or write the wrong thing** (an id kept in the file, a site its step's schema doesn't
  mark, another tenant's connection, one of the wrong type, a malformed envelope, or a lookup that failed): refused
  by name, nothing created, and never "unbound" by default (Task 5: `a file embedding an id is refused`, `a binding of
  the wrong kind is refused`, `a malformed file is refused`; Task 8: `refuses %s`, `offers no choice until this
  tenant's connections are read`).

## Rulings this plan proposes

The outline leaves these open, or the code found differs from it. Each is the safest option; they join the ledger as
rulings 68 onward when the plan is approved. Format: what - why - cost if wrong. The owner ruled on 1–21 with
revision 1 and on 22–26 with revision 2 (both 2026-10-06); each carries its status, and the amended ones read as
amended. 27–28 are new in revision 3.

1. **Accepted. Triggers wait for 4c.** Triggers are rows (schedules, webhook bindings, CSV uploads), not graph nodes,
   and their setup is 4c's. So 4b's chooser (1b) asks only how to start (Blank, Import from file); its first step,
   "What starts it?", arrives with 4c's trigger setup. The list (1a) has no Trigger column until then. - Showing a
   trigger the editor can't set up would promise what 4b can't do. - 1b's first step and 1a's column wait one slice.
2. **Accepted. A start card heads the canvas, and no end marker closes it.** The card is not a graph node: it stands
   for whatever starts a run, and its edges reach every entry step (a step with no incoming edge). Its "+" adds a
   first step. 1c's "End · run succeeds" marker is left out: a run ends when no step remains, and a drawn end would
   look like a step. - The graph has no trigger node to draw. - One cue fewer than 1c.
3. **Accepted. Step badges are problems and "runs as a separate step".** 1c's "conditional" badge needs the
   validator's liveness per step, which B6 brings in 4c; "disabled" has no meaning in the graph model (`GraphNode`
   has no such field). - Neither can be shown truthfully in 4b. - Two of the outline's three badges wait or drop.
4. **Accepted, with the filter correction. The list's filters and columns.** Name, Version, Last run (live; the last
   simulation beneath it, apart), Last 24 h, Enabled, and a row menu (Open, Export). Filters: All, Published,
   Unpublished changes (a workflow never published included: ruling 6), Needs attention, as a segmented control with
   counts (no pills, §6); the text filter matches names (no tags exist). No delete: no route deletes a workflow, and
   the API's database role has no DELETE grant on `workflows`. - What the API supports today. - No delete from the UI.
5. **Held (owner, 2026-10-06) until the batching and query-plan evidence exist. The last run without a workflow
   index.** `runs` has no index on `workflow_id`; one is a migration, which needs a slot from the owner. Task 3 reads
   every workflow's last root runs in one `DISTINCT ON` statement over the tenant's root runs, and its probe (Task 3,
   Step 9) explains it at 10k, 100k and 1M root runs beside another tenant's, with and without the candidate index
   `runs (workflow_id, mode, queued_at DESC, id DESC) WHERE kind = 'run'` (and the per-workflow read it would allow).
   The owner decides at the milestone 1 pause: accept on the numbers, or assign a slot (then a plan addendum). -
   Retention alone isn't a demonstrated bound. - Until ruled, the list's cost grows with a tenant's run history.
6. **Accepted, with the filter correction. "Unpublished changes" compares graph hashes.** The draft's `graph_hash`
   (parsed and hashed on read, once per draft revision and off the event loop) against the active version's. Never
   published counts as unpublished, in the summary and in the list's filter. No edit count (outline B3). Positions
   count: moving a step is an unpublished change, as the hash says. - The hash is what publish records. - A list's
   first read after a restart parses each draft once (bounded by the 1 MiB body cap; the probe measures it).
7. **Amended (owner): live failures drive attention; simulations stay separately identified.** Needs attention is the
   last *live* root run failed or exceeded its deadline, or the active version can't run (`blocked_by`). The last
   simulated run is its own field (`last_simulation`) and shows apart in the simulation colour; a later successful
   simulation never clears a live failure, and a failed one never raises attention. Schedules' sync errors join with
   4c. **Last 24 h** counts root runs queued in the last 24 hours, live and simulated apart; the list shows the live
   count and "+N simulated". - Live and simulated are never blended (D2). - None.
8. **Accepted. The draft PUT's schema documents `Graph` while the route parses a plain object** (ruling 47). FastAPI
   ignores `WithJsonSchema` on a body and merges `openapi_extra` into the generated object schema (both verified
   against FastAPI 0.141.1), so `openapi.py` refines the one schema both the API and `dewpoint api openapi` emit: the
   draft PUT's body becomes exactly `{"$ref": "#/components/schemas/Graph"}`. The route keeps its own parsing, so its
   `graph.format` diagnostics and admission checks (non-finite numbers, depth, value count) stay as they are. -
   Typing the body as `Graph` would route bad drafts through `{"error":"invalid","fields":[...]}` and skip those
   checks. - The documented body and the parsed one are two declarations, held together by a test.
9. **Accepted. Answers keep a draft verbatim** (`draft: object` in the schema); the client types it as `Graph` at one
   boundary (`asGraph` in `src/lib/graph.ts`). - A response model typed `Graph` would re-serialize the stored draft
   with defaults the author never wrote. - One cast, at one place.
10. **Accepted. Inserting on an edge offers only steps that continue the flow:** a type with an `out` port, or
    `flow.loop`'s `done`. "+" after a port offers every type; a type with no ports (`flow.stop`, `flow.fail`) ends its
    branch. - Inserting a branching step mid-edge would have to guess which port carries the rest of the flow. -
    Inserting an `if` mid-flow takes two actions (add after, reconnect).
11. **Accepted. A new step** gets a random UUID, a key from its type's last segment (`transform`, then `transform_2`),
    a config with its schema's top-level defaults (a connection field gets none), no options (the server's defaults),
    and a place below its source; inserting on an edge moves every step at or below that place down one row. - Keys
    must be unique and match `^[a-z][a-z0-9_]{0,62}$`. - None.
12. **Accepted. Deleting a step asks first**, and when the step has exactly one incoming and one outgoing edge, its
    predecessor is reconnected to its successor; the dialog says so. References to the step in other steps' values
    stay, and the validator reports them (`ref.unknown_step`). Its `settings.declassify` entries go with it. - Healing
    a chain is what a person deleting a middle step expects; rewriting references isn't. - None.
13. **Amended (owner): single-pointer movement equivalent to a drag. Moving steps.** A pointer drags; a step's panel
    also has "Place on the canvas…" (the next click on an empty place puts the step there, centred on it; Escape or
    Cancel stops it) and four buttons that move it 20 px a click; Shift+arrow keys nudge the focused step by 20 px;
    Auto layout arranges the whole graph. Positions are saved in the draft. - WCAG 2.5.7: auto layout doesn't put a
    step where a person wants it, and keyboard nudging alone isn't a pointer's alternative. - A placing mode the
    design doesn't show (a bar above the canvas says what the next click does).
14. **Accepted. Connecting existing steps.** A port's "Connect to…" lists the steps that may follow it (not itself,
    not one that would close a cycle, not one already connected from that port); dragging from a handle does the
    same with a pointer. An edge is removed from its "+" item with Delete, after a confirmation. - Every pointer
    action has a keyboard one (2.1.1). - None.
15. **Amended (owner): demonstrably complete keyboard navigation. The keyboard model (D16), exactly.** The canvas is one
    tab stop. Its items are the start card, each step, each edge (its "+"), and each free port (its "+"); each lists its
    children from the start card down, and a step no entry reaches (a cycle no entry leads into, a step whose only edges
    in come from steps that aren't there) joins the start card's children, topmost first, so every item drawn is
    reached. A step joined from two places is a child of both, so the keys carry the path they came by (revision 3, the
    owner's correction 3): Down goes to the first child, Up back the way the keys came, Left and Right among the
    children of the item they came from (at a join, the branch taken); a click, Tab or a change starts the path afresh
    from the walk's own. Home goes to the start card. Enter on a step opens its panel (read-only in 4b; 4c's drawer
    replaces it), on an edge or a free port the picker; `A` opens the picker after the focused step's first port; `C`
    connects from it; Delete asks; Escape closes the picker or panel and returns focus; Ctrl or Cmd+Z undoes, Shift+Ctrl
    or Cmd+Z redoes. A polite live region announces what changed. React Flow's own keyboard handling is off. Tests press
    every key from every path reached, over chains, branches, joins (one a second branch also reaches), cycles, separate
    components and an imported draft's dangling, repeated and self edges, editable and read only (a viewer, a conflict,
    a viewed version); the editor's own wiring is tested at that join for all three read-only cases, and the browser
    walks an imported cycle. - D16. - None.
16. **Accepted. A problem focuses its step** on the canvas (brought into view); the field itself waits for 4c's
    drawer. - 4b has no field to focus. - None.
17. **Amended (owner): server-bound publish confirmation.** Publish needs `workflow.publish`; an editor without it
    doesn't see Publish, the enable switch, or Make active. The confirmation names the next number from the versions
    list ("Publish version 3"), and publish sends that list's newest number as `expected_latest_version`, which the
    API checks under the lock that numbers the new version (Task 4); a mismatch is `409 version_changed`, and the
    editor refreshes the list and asks again with the new number. Publish names no number while the list loads,
    refreshes or can't be read. Callers that send no expectation (the CLI, the tests) publish as before. A publish
    refused for a check only publish runs (`connection.*`, `subflow.*`, `declassify.forbidden`, `lifecycle.*`,
    `version.unbounded`) shows those in the problems panel, marked "found at publish". - A dialog that names a
    number the server may not use isn't a confirmation. - One more 409 the editor handles.
18. **Amended (owner): validated, fail-closed portable files. Export and import (B12).** Export is the saved draft
    (never unsaved local edits: an export that would miss them stops and says so, offering the last saved draft by
    name), as `{"format": "dewpoint.workflow", "format_version": 1, "name", "graph", "bindings"}`. `graph` is the
    draft with every site emptied: each connection field (a top-level config property its type marks
    `x-dewpoint-connection`, the only place the SDK allows the marker), each `flow.run_workflow`'s `workflow_id`, and
    `settings.failure_handler`. Each binding has an id, a kind, the connection type, a label and its sites. Export
    refuses (`422 not_portable`) a step of a type the server doesn't know, two steps sharing an id, and a site holding
    anything but an id. Import checks the whole file first: the envelope (the model, extra keys refused), the graph's
    format, every step's type known, no id embedded at a site (so "leave unbound" can't keep one), binding ids used
    once, sites listed once, and each site one the server's schemas mark for that binding's kind and connection type
    (`422 bad_document`); then each chosen id against the tenant's own (`422 bad_binding`). Schedules, webhook
    bindings and CSV mappings are rows, not graph, and don't travel. - Never carry one tenant's ids into another's,
    never write where nothing checked. - A workflow with a step whose plugin isn't installed here can't be exported
    portably, or imported, until it is.
19. **Accepted. Workflows lands a tenant.** Workflows joins the rail first; choosing a tenant (the switcher, the
    palette) opens its workflows (D10); the palette lists the current tenant's workflows and "New workflow". The editor
    uses the 60 px icon rail at every width, and keeps the shell's header (tenant, ⌘K, Security, Sign out); its own
    toolbar sits below it with the breadcrumb, save state and actions. - One header everywhere. - 1c's single header
    row becomes two.
20. **Accepted. React Flow's attribution link is hidden** (`proOptions.hideAttribution`), which its MIT licence allows;
    the third-party notices carry its licence. Only its structural `base.css` is imported: colours, borders and shadows
    come from our tokens. - An external link in the canvas, and a second visual language. - None.
21. **Accepted, extended by correction 4. Undo and redo stay local** (D17): a history of up to 100 documents in
    memory, cleared when the editor closes. Undo is off after a conflict (the editor is read-only), and while a
    publication or an activation runs. - D17. - None.
22. **Accepted (owner, with revision 2); extended in revision 3. Leaving the editor saves first.** One decision, the
    editor's: save what's pending; when that can't be done (a failed save, a conflict), ask: stay, download my
    version, or leave without saving. It answers every way out: router navigations (the breadcrumb, the rail, the
    palette, the tenant switcher) through the router's blocker; sign-out, which asks it before revoking the session
    or clearing the query cache; and an ended session, which keeps the shell and the unsaved work on screen with a
    notice instead of swapping it for the sign-in page. Closing the tab gets the browser's prompt. Reload after a
    conflict asks before discarding the local version. The saver is disposed when the editor closes: a save still in
    flight that answers afterwards sends nothing more. - The debounce and a conflict both leave work only on the
    screen, and a revoked session or a cleared cache must not take it first. - Leaving waits as long as a save takes;
    an ended session waits for the person's choice.
23. **Accepted (owner, with revision 2); extended in revision 3. The editor opens on a fresh snapshot, and stays
    open.** It waits for the workflow read made after it mounted (never a cached copy, which would conflict on the
    first edit), and keeps what it opened with (the workflow, the step types, the role): a later read, a failed
    refresh of an auxiliary query or a cleared cache neither replaces nor closes it, and a failure shows beside it. -
    A stale draft turns the first edit into a conflict; a background failure must not discard local work. - One read,
    and a moment of "Loading…", on every entry; step types refreshed elsewhere may lag in an open editor.
24. **Accepted (owner, with revision 2); extended in revision 3. A check is current only for what's on the screen.**
    The editor says "Checking…" or "Not checked" before the first answer, "Check failed" when a request fails, "…
    before your edits" when the answer is for an older revision or edits came since; badges sit on the steps, and a
    step's panel lists its problems, only while the check is current. What only publish found carries its own
    snapshot (revision and generation) and is current on the same terms: afterwards it stays in the panel's "Found
    at publish", marked as before the latest edits, never in a step's problems or an unqualified count. Viewing a
    version shows none of the draft's. - A failed or stale check must not keep reassuring, nor a stale finding
    alarm. - Badges disappear between an edit and the next check (about a second, plus the check).
25. **Principle accepted (owner, with revision 2); proof amended in revision 3. An outcome is said only when known.**
    A publish or an activation without an answer from the API (the network, or a 5xx) is read back and reported as
    found, or as not known; never as failed, and never as published without evidence. A version holds this draft
    only if its recorded `graph_hash` is the hash the server gave for the revision submitted (the save's answer, or
    the load's `draft_graph_hash`); a version of that number with another hash is another publication, and this one
    was refused. The active version and the draft's comparison always come from the read (or the answer) itself,
    never from the number hoped for. A version made active stays made active when the read after it fails, and the
    draft's comparison with it is "not known" until read (`Saved · v1 is active`); nothing read back leaves the
    active version "not known". Only the newest "View version" answer is shown. - A version's existence and the
    draft's current revision don't say which revision the version holds (the owner reproduced both wrong
    inferences). - Two reads after a lost answer; the draft's hash travels in the save's answer and the summary.
26. **Accepted (owner, with revision 2). A draft that can't be exported portably is offered as it is, labelled.** In
    the editor, a refused export offers "Download this draft as it is (not portable)", a `.draft.json` file the
    importer refuses (it isn't a `dewpoint.workflow` file); the list says to open the workflow for it. - The owner's
    option of a separately labelled recovery download: the person keeps their work, and the label says the file
    holds this tenant's ids. - One more download path carrying the tenant's ids, as the conflict's download already
    does.
27. **New in revision 3. A save's answer names the version it compared with.** `put_draft` reads the active version
    after its compare-and-swap, under the row lock the swap took, and answers it (`active_version_id`,
    `active_version_number`) beside `unpublished_changes` and the saved draft's `graph_hash`; the editor labels the
    active version from that same answer. - The route reads the workflow without a lock, so an activation can land
    between that read and the swap (the owner's correction 5). - Two fields more on each save's answer, and one read.
28. **New in revision 3. Bindings are chosen from what was read.** While this tenant's connections and workflows are
    loading, or when they couldn't be read, the import offers no choice and can't be submitted; "Leave unbound" is a
    choice among what was read, and a binding with nothing to offer says so. - An empty list standing in for a
    failed lookup would make "unbound" look chosen. - An import waits for two lists.

## Revision 2

What changed from revision 1 (325fc14), by the owner's seven corrections and ruling statuses, and where:
1. **Draft lifetime** (Tasks 6, 11, 13; rulings 22, 23): leaving is guarded and saves first; the saver has a disposed
   state; the editor waits for a fresh read and seeds itself once (`workflowQuery` loses its infinite `staleTime`);
   a conflict's local version is guarded from leaving and from Reload.
2. **Validation freshness** (Task 14; ruling 24): `generation`/`savedGeneration` in the saver; a check's five states;
   badges only when current; nothing of the draft's on a version's canvas.
3. **Publish confirmation** (Tasks 4, 15; ruling 17): `expected_latest_version` checked under the publication's lock,
   `409 version_changed`, existing callers unchanged; the editor names no number until the list is read, and asks
   again with the new one.
4. **Truthful completion** (Task 15; rulings 21, 25): editing off during a publication or an activation;
   `published(revision)` and `compared(summary)`; uncertain outcomes read back; view answers in order; export stops on
   a failed save.
5. **Portable files** (Tasks 5, 7, 8, 15; rulings 18, 26): export refuses what it can't make portable; import checks
   the whole file against the server's schemas; the browser parser checks the whole envelope.
6. **Accessibility** (Tasks 9, 11, 12, 16; rulings 13, 15): click-to-place and position buttons; the keyboard model
   links every component and walks the edges the canvas draws; reachability tests by key presses; the browser walks
   an imported cycle and places a step by clicks.
7. **B3** (Tasks 3, 7; rulings 5, 6, 7): live attention apart from simulations; the list reads a fixed number of
   times (a statement-count test); drafts hashed once per revision off the event loop; the probe for ruling 5; the
   unpublished filter counts never-published workflows.

Found while revising, outside the seven: revision 1 put the summary module in `dewpoint.core`, which import-linter's
"core depends on neither engine nor plugins" forbids (it hashes with the engine); it lives in `dewpoint.apps` now
(`apps/workflow_summary.py`, beside `workflow_ops.py`). And `main.tsx` runs the app in StrictMode, so the saver is made
in an effect (a saver held from the first render would be disposed by StrictMode's first cleanup).

A fresh-context review of this revision found nine defects, fixed here: the probe's untyped binds (Postgres 16 refuses
`generate_series(unknown, unknown)`) and its plans explained outside row-level security (Task 3); `DraftHashes`
answering from what another read could evict, and keeping a hash from a save not yet committed (Task 3); a version's
step panel showing the draft's step and expressions, and placing a step while a version was viewed (Tasks 12, 15);
a lost publish's read-back calling a listed version unpublished, and a re-asked confirmation keeping the old focus
(Task 15); the browser parser skipping the API model's bounds (Task 8); and a miscounted test total (Task 16).

## Revision 3

What changed from revision 2 (089c004), by the owner's review of it (five corrections, one smaller), and where:
1. **Lost-answer reconciliation** (Tasks 3, 15; ruling 25's proof): a version holds this draft only if its recorded
   `graph_hash` equals the hash the server gave for the revision submitted; the save's answer and the summary carry
   that hash (`graph_hash`, `draft_graph_hash`), and the saver keeps it (`savedHash`). Another hash means another
   publication, and this one refused; the active version and the comparison come from the read itself
   (`compared`), and nothing read back leaves the active version "not known" (`lostTrack`).
2. **Destructive exits and background failures** (Task 13; rulings 22, 23): leaving is one decision the editor
   makes, awaited by the router's blocker and asked by sign-out (`mayLeave`, before the session is revoked or the
   cache cleared) and by an ended session (`RequireActive` keeps the shell and the work on screen, with a notice).
   `EditorPage` keeps what it opened with: a failed step-type refresh, or a cleared cache, shows beside the editor,
   never in its place.
3. **Keyboard reach at joins** (Tasks 12, 15; ruling 15): the keys carry the path they came by (`step`, `pathTo`,
   `isPath`), so at a join Left and Right stay in the branch taken and Up goes back that way; the reachability tests
   walk paths, and the owner's case (a → b, c; b → d, e; c → d, f) is tested in the model, editable and read only,
   and through the editor for a viewer, a conflict and a viewed version.
4. **Publish findings' snapshot** (Tasks 14, 15; ruling 24): `PublishProblems` carries the revision and the generation
   it was found in, and is current only on the same terms as a check; a stale finding stays in "Found at publish",
   marked, and never in a step's problems, the badges or an unqualified count.
5. **The save's comparison** (Tasks 3, 13; ruling 27): `put_draft` reads the active version after its swap, under the
   row lock the swap took (`service.locked_active_version`), and answers it with the comparison; the editor's
   active-version label comes from that same answer. A test interleaves an activation between the route's read and
   its swap.
6. **Binding choices** (Task 8; ruling 28): `useBindingChoices` says loading, failed (with Try again) or ready; the
   import can't be submitted until each needed list is read, and a binding with nothing to offer says so.

## File structure

Backend, modified:
- `backend/src/dewpoint/apps/api/responses.py`: the 4b answers (node types, workflows, drafts, validation, versions,
  export and import).
- `backend/src/dewpoint/apps/api/routes/node_types.py` (B5), `routes/workflows.py` (models, B3, B4a, B12 routes, the
  publish precondition).
- `backend/src/dewpoint/apps/api/openapi.py`: `refine()`, applied to the served and the printed schema.
- `backend/src/dewpoint/apps/api/main.py`: serves the refined schema.
- `backend/src/dewpoint/apps/workflow_ops.py`: `publish(..., expected_latest_version=None)`.
- `backend/src/dewpoint/core/workflows/service.py`: `create_workflow(..., source=...)` for the import's audit entry,
  `blocked_by_many`, `latest_version_number`, `VersionChangedError`.

Backend, new:
- `backend/src/dewpoint/apps/workflow_summary.py`: run statistics, attention and draft hashes per workflow (B3).
- `backend/src/dewpoint/core/workflows/portable.py`: export's placeholders and import's checks and bindings (B12).
- Tests: `backend/tests/apps/api/test_node_types.py`, `test_workflow_summary.py`, `test_workflow_versions.py`,
  `test_workflow_portable.py`; `backend/tests/apps/test_workflow_summary.py`;
  `backend/tests/core/workflows/test_portable.py`; additions to `test_openapi.py` and `test_workflows.py`.
- Probe (run by hand, never in CI): `backend/tests/probes/workflow_list.py`.

Frontend, new:
- `src/lib/workflows.ts`: the workflow API's types and queries, `notPortable`. `src/lib/graph.ts`: the document and
  its operations. `src/lib/layout.ts`: dagre. `src/lib/draftSync.ts`: saving (D17). `src/lib/leaving.ts`: leaving's
  decision, asked from outside the router. `src/lib/history.ts`: undo and redo. `src/lib/announce.ts`: the live
  region's store. `src/lib/download.ts`.
- `src/components/Switch.tsx`, `src/components/Announcer.tsx`, `src/components/Segmented.tsx`.
- `src/routes/Workflows.tsx` (1a), `src/routes/NewWorkflow.tsx` (1b), `src/routes/ImportBindings.tsx`.
- `src/routes/editor/`: `Editor.tsx`, `Toolbar.tsx`, `Canvas.tsx`, `canvasNav.ts`, `check.ts`, `items.ts`,
  `StepCard.tsx`, `StartCard.tsx`, `FlowEdge.tsx`, `StepPicker.tsx`, `ConnectDialog.tsx`, `StepPanel.tsx`,
  `ProblemsPanel.tsx`, `VersionsPanel.tsx`, `SaveState.tsx`, `canvas.css`.
- Tests beside each (`*.test.ts(x)`), `e2e/workflows.spec.ts`, `e2e/state.ts`, and the fixtures
  `e2e/fixtures/report.dewpoint.json`, `e2e/fixtures/cycle.dewpoint.json`.

Frontend, modified: `package.json` and `pnpm-lock.yaml` (three packages), `src/router.tsx`, `src/components/Shell.tsx`,
`src/components/TenantSwitcher.tsx`, `src/components/CommandPalette.tsx`, `src/components/ConfirmDialog.tsx`
(`cancelLabel`, `tone`), `src/components/icons.tsx`, `src/styles/theme.css`, `src/api/openapi.json`,
`src/api/schema.d.ts`, `playwright.config.ts`, `e2e/foundations.spec.ts`, `e2e/gate.spec.ts`.

## How to run things

- Backend tests, from `backend/`: `uv run pytest -q -p no:cacheprovider <paths>`; the whole suite in parallel:
  `uv run pytest -q -n 12 -p no:cacheprovider --ignore=tests/apps/cel_evaluator --ignore=tests/engine/cel
  --ignore=tests/engine/graph/test_validate_cel.py --ignore=tests/apps/worker/test_gate_task_cost.py` (the serial CEL
  group runs apart, in `cel-gates`' image: ledger ruling 66). Static checks: `uv run ruff check . && uv run ruff format
  --check . && uv run mypy src && uv run lint-imports`.
- Frontend, from `frontend/`: `npx -y pnpm@12.6.0 exec vitest run <file>`; all: `npx -y pnpm@12.6.0 test`; `npx -y
  pnpm@12.6.0 lint`, `typecheck`, `check:api`, `build`; licences: `node scripts/licence-check.mjs --self-test` and
  `npx -y pnpm@12.6.0 licenses list --json [--prod] | node scripts/licence-check.mjs prod|all`.
- The browser gate: reset the isolated stack (`dewpoint-ui4a`), then `E2E_BASE_URL=http://localhost:18080 npx -y
  pnpm@12.6.0 exec playwright test` (the session's `compose-ui4a/e2e.sh` does both).

## Executing this plan

Inline, in one session (the owner, 2026-10-06), test-first: each task's tests are written and seen failing for the
stated reason before its code. The code below is the target; where the installed package or the code base differs,
the executor adapts it test-first and records the difference as a mid-slice ruling in the ledger (4a's practice).

Branch `feat/editor-4b`, cut from current `main` when execution starts (66443c3 at this revision: #42 is merged as
ff1536e, and #39 since), in a worktree of its own; not stacked on 4a. A later `main` is merged in, never rebased.

Pauses (the owner's): execution stops for the owner's review
1. **after milestone 1:** the corrected API contracts (the regenerated `openapi.json`'s diff, and the refusals each
   route answers), the statement-count test, and the probe's query plans and timings (Task 3, Step 9), on which ruling
   5 is decided;
2. **after milestone 3:** the canvas under the real CSP (the browser gate's CSP, console and remote-request checks on
   every canvas flow) and the accessibility proof (axe on each canvas state, the keys reaching every item in the unit
   tests and over an imported cycle in the browser, a step placed by clicks); Task 11's stop on any CSP failure stands
   and comes first;
3. **at the final checkpoint** (Task 16, Step 5): a fresh-context review of the whole branch against the brief's six
   hunts (a sensitive value reaching the DOM or a log, a live call, a write that skips the server's checks, a CSP
   violation, keyboard traps and WCAG 2.2 AA failures, visible drift from the design), and the one-page summary with
   screenshots beside frames 1a, 1b and 1c.

Between pauses, each milestone's focused tests run at its end, and a failure stops the work. Nothing is pushed and no
PR opened (owner): the branch stays local until the owner says otherwise in chat.

---

## Milestone 1 — The API answers what the editor needs

Every task of this milestone ends by regenerating the client's schema, so CI's drift checks hold at every commit:

```bash
cd backend && uv run dewpoint api openapi > ../frontend/src/api/openapi.json
cd ../frontend && npx -y pnpm@12.6.0 gen:api && npx -y pnpm@12.6.0 check:api && npx -y pnpm@12.6.0 typecheck
```

### Task 1: Node types say how a step of each runs (B5), as a named answer

**Files:**
- Modify: `backend/src/dewpoint/apps/api/responses.py` (add `RetryOut`, `NodeTypeOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/node_types.py`
- Create: `backend/tests/apps/api/test_node_types.py`
- Modify: `backend/tests/apps/api/test_openapi.py` (start `SLICE_4B`)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: the stored manifest (`backend/src/dewpoint/sdk/manifest.py:216-244`): `side_effect`, `credentials`,
  `capabilities`, `retry` (`max_attempts`, `initial_interval_s`, `backoff`, `max_interval_s`, `non_retryable`),
  `timeout_s`, present in every manifest since the SDK's first commit (3101a3f, 2026-09-25).
- Produces: `GET /api/v1/node-types` answering `list[NodeTypeOut]`; the client type `Schemas["NodeTypeOut"]`, with
  `kind: "action" | "control"`, `ports: string[]`, `dynamic_ports: string | null` (a config field whose entries each
  declare a `port`, e.g. `flow.switch`'s `"cases"`), `config_schema`, `side_effect`, `credentials`, `capabilities`,
  `retry`, `timeout_s`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/apps/api/test_node_types.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The editor's palette of node types (sub-project 4, B5): each also says how a step of it runs."""

import pytest

from tests.apps.api.helpers import session_client
from tests.support.registry import sync_test_plugins


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def test_each_type_says_how_a_step_of_it_runs(app, owner_sessionmaker, api_settings) -> None:
    c, _ = await session_client(app, owner_sessionmaker, api_settings, "viewer")
    async with c:
        r = await c.get("/api/v1/node-types")
    assert r.status_code == 200, r.text
    by_ref = {t["ref"]: t for t in r.json()}
    loop = by_ref["flow.loop@1"]
    assert (loop["kind"], loop["ports"], loop["side_effect"]) == ("control", ["body", "done"], "none")
    assert (loop["credentials"], loop["capabilities"], loop["timeout_s"]) == ([], [], 60.0)
    assert loop["retry"] == {
        "max_attempts": 3,
        "initial_interval_s": 1.0,
        "backoff": 2.0,
        "max_interval_s": 60.0,
        "non_retryable": [],
    }
    assert by_ref["flow.switch@1"]["dynamic_ports"] == "cases"
    call = by_ref["testkit.http_call@1"]
    assert (call["kind"], call["credentials"], call["side_effect"]) == ("action", ["testkit"], "idempotent")


async def test_the_palette_needs_a_session(client) -> None:
    assert (await client.get("/api/v1/node-types")).status_code == 401
```

In `backend/tests/apps/api/test_openapi.py`, after `test_slice_4a_routes_name_their_answer`, add:

```python
# What the web client calls in slice 4b: each answers a named model.
SLICE_4B = [
    ("get", "/api/v1/node-types"),
]


@pytest.mark.parametrize("method,path", SLICE_4B)
def test_slice_4b_routes_name_their_answer(method: str, path: str) -> None:
    responses = schema()["paths"][path][method]["responses"]
    ok = next(code for code in responses if code.startswith("2"))
    body = responses[ok]["content"]["application/json"]["schema"]
    assert "$ref" in body or "$ref" in body.get("items", {}), body
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_node_types.py tests/apps/api/test_openapi.py`
Expected: FAIL: `KeyError: 'side_effect'` in the first test; `test_slice_4b_routes_name_their_answer[get-/api/v1/node-types]`
fails on an `items` schema without `$ref`. The 401 test passes already (it pins the dependency).

- [ ] **Step 3: Implement**

In `backend/src/dewpoint/apps/api/responses.py`, after `PlatformStatusOut`:

```python
SideEffect = Literal["none", "idempotent", "keyed", "reconcilable", "ambiguous"]


class RetryOut(_Answer):
    max_attempts: int
    initial_interval_s: float
    backoff: float
    max_interval_s: float
    non_retryable: list[str]


class NodeTypeOut(_Answer):
    """A node type the editor may place (active) or still draws (deprecated), and how a step of it runs (B5): what it
    may change, the connection types it takes, what it may reach, and its retry and timeout defaults."""

    ref: str
    type: str
    version: int
    kind: Literal["action", "control"]
    state: Literal["active", "deprecated"]
    title: str
    description: str
    ports: list[str]
    dynamic_ports: str | None  # a config field whose entries each declare a `port` (flow.switch's "cases")
    config_schema: dict[str, Any]
    output_schema: dict[str, Any]
    side_effect: SideEffect
    credentials: list[str]
    capabilities: list[str]
    retry: RetryOut
    timeout_s: float
```

Replace `backend/src/dewpoint/apps/api/routes/node_types.py` with:

```python
# SPDX-License-Identifier: Apache-2.0
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.apps.api.responses import NodeTypeOut
from dewpoint.core.http import active_session, get_db
from dewpoint.core.plugins import registry

router = APIRouter(prefix="/api/v1", tags=["node-types"])


@router.get("/node-types", dependencies=[Depends(active_session)], response_model=list[NodeTypeOut])
async def node_types(db: AsyncSession = Depends(get_db, scope="function")) -> list[dict[str, object]]:
    """The editor's palette: node types that new versions may use (active) or still carry (deprecated)."""
    return [
        {
            "ref": row.ref,
            "type": row.type,
            "version": row.version,
            "kind": row.kind,
            "state": row.state,
            "title": row.manifest["title"],
            "description": row.manifest.get("description", ""),
            "ports": row.manifest.get("ports", []),
            "dynamic_ports": row.manifest.get("dynamic_ports"),
            "config_schema": row.manifest.get("config_schema") or {},
            "output_schema": row.manifest.get("output_schema") or {},
            # How a step of this type runs (B5): every manifest carries these since the SDK's first commit.
            "side_effect": row.manifest["side_effect"],
            "credentials": row.manifest["credentials"],
            "capabilities": row.manifest["capabilities"],
            "retry": row.manifest["retry"],
            "timeout_s": row.manifest["timeout_s"],
        }
        for row in await registry.list_node_types(db)
    ]
```

- [ ] **Step 4: Run the tests to see them pass, then the route's neighbours**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_node_types.py tests/apps/api/test_openapi.py tests/apps/api/test_workflows.py`
Expected: PASS.

- [ ] **Step 5: Regenerate the client's schema and check it** (the milestone's commands above). Expected: `check:api`
  and `typecheck` pass; `schema.d.ts` gains `NodeTypeOut` and `RetryOut`.

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/api/responses.py backend/src/dewpoint/apps/api/routes/node_types.py \
  backend/tests/apps/api/test_node_types.py backend/tests/apps/api/test_openapi.py \
  frontend/src/api/openapi.json frontend/src/api/schema.d.ts
git commit -m "feat(api): node types say how a step of each runs (B5), as a named answer (4b)"
```

### Task 2: Every workflow route answers a named model; the draft PUT documents its body as `Graph`

**Files:**
- Modify: `backend/src/dewpoint/apps/api/responses.py` (add `DiagnosticOut`, `WorkflowOut`, `WorkflowDetailOut`,
  `WorkflowUpdatedOut`, `DraftSavedOut`, `ExpressionOut`, `TaintSiteOut`, `DeclassifiedOut`, `TaintOut`,
  `ValidationOut`, `PublishedOut`, `VersionOut`, `ActivatedOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (each route's `response_model`)
- Modify: `backend/src/dewpoint/apps/api/openapi.py` (`refine`, `serve_refined`)
- Modify: `backend/src/dewpoint/apps/api/main.py` (serve the refined schema)
- Modify: `backend/tests/apps/api/test_openapi.py`
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: `Diagnostic.to_json()` (`backend/src/dewpoint/engine/graph/diagnostics.py:20-28`): `{code, message, node,
  field, fix, severity}`; `Graph` (`backend/src/dewpoint/engine/graph/model.py:125`).
- Produces: `refine(spec) -> spec` and `serve_refined(app)` in `openapi.py`; `GRAPH_PROPERTIES`, a tuple of
  `(component, property)` documented as `Graph` (Tasks 4 and 5 append to it); client types `Schemas["Graph"]`,
  `Schemas["WorkflowOut"]`, `Schemas["WorkflowDetailOut"]` (whose `draft` is a `Graph`), `Schemas["DraftSavedOut"]`,
  `Schemas["ValidationOut"]`, `Schemas["DiagnosticOut"]`, `Schemas["ExpressionOut"]`, `Schemas["PublishedOut"]`,
  `Schemas["VersionOut"]`, `Schemas["ActivatedOut"]`, `Schemas["WorkflowUpdatedOut"]`. No behaviour changes: every
  answer's JSON stays as it was.

- [ ] **Step 1: Write the failing tests**

In `backend/tests/apps/api/test_openapi.py`, extend `SLICE_4B`:

```python
SLICE_4B = [
    ("get", "/api/v1/node-types"),
    ("get", "/api/v1/t/{tenant_id}/workflows"),
    ("post", "/api/v1/t/{tenant_id}/workflows"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}"),
    ("patch", "/api/v1/t/{tenant_id}/workflows/{workflow_id}"),
    ("put", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft"),
    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/validate"),
    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/publish"),
    ("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions"),
    ("post", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/activate"),
]
```

and add, after it:

```python
GRAPH = {"$ref": "#/components/schemas/Graph"}


def test_the_draft_put_documents_its_body_as_a_graph() -> None:
    """The route parses a plain object itself, for its `graph.format` diagnostics (ledger ruling 47, 4b ruling 8)."""
    body = schema()["paths"]["/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft"]["put"]["requestBody"]
    assert body["content"]["application/json"]["schema"] == GRAPH


def test_a_workflow_answer_documents_its_draft_as_a_graph() -> None:
    assert schema()["components"]["schemas"]["WorkflowDetailOut"]["properties"]["draft"] == GRAPH


def test_the_graph_components_are_the_models_own() -> None:
    """No other component shares a name with one of the graph's models (a clash would mix two shapes)."""
    from dewpoint.engine.graph.model import Graph

    own = Graph.model_json_schema(mode="validation", ref_template="#/components/schemas/{model}")
    components = schema()["components"]["schemas"]
    for name, sub in own.pop("$defs").items():
        assert components[name] == sub, name
    assert components["Graph"] == own
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_openapi.py`
Expected: FAIL: nine `test_slice_4b_routes_name_their_answer` cases (free-form answers), and the three new tests
(`KeyError: 'Graph'`, `KeyError: 'WorkflowDetailOut'`).

- [ ] **Step 3: Implement the answers**

In `backend/src/dewpoint/apps/api/responses.py`, after `NodeTypeOut`:

```python
class DiagnosticOut(_Answer):
    """A problem with a graph: `node` is a node's id, or null for the workflow; `field` is a JSON pointer inside the
    node's config, `/settings/...` for the workflow's, or into the whole document for `graph.format`."""

    code: str
    message: str
    node: str | None
    field: str | None
    fix: str | None
    severity: Literal["error", "warning"]


class WorkflowOut(_Answer):
    id: str
    name: str
    enabled: bool
    draft_revision: int
    active_version_id: str | None
    active_version_number: int | None
    executable: bool | None  # null when nothing is published
    blocked_by: list[str]  # the lifecycle entries that keep the active version from running
    created_at: str
    updated_at: str


class WorkflowDetailOut(WorkflowOut):
    draft: dict[str, Any]  # verbatim, as saved; the schema documents it as a Graph (openapi.refine)


class WorkflowUpdatedOut(WorkflowOut):
    warnings: list[DiagnosticOut]


class DraftSavedOut(_Answer):
    draft_revision: int


class ExpressionOut(_Answer):
    """How one CEL value runs (engine-core §5.10): "local" inline, "activity" as a separate step, with why."""

    node: str | None  # null for a workflow output
    field: str
    mode: Literal["local", "activity"]
    reason: str | None


class TaintSiteOut(_Answer):
    node: str
    field: str


class DeclassifiedOut(_Answer):
    node: str
    field: str
    reveals: str


class TaintOut(_Answer):
    sites: list[TaintSiteOut]
    declassified: list[DeclassifiedOut]


class ValidationOut(_Answer):
    """The saved draft's diagnostics, at the revision they were computed for: an editor shows an answer for an
    older revision as stale, never as current (D17; 4b ruling 24)."""

    draft_revision: int
    valid: bool
    diagnostics: list[DiagnosticOut]
    expressions: list[ExpressionOut]
    taint: TaintOut


class PublishedOut(_Answer):
    version_id: str
    number: int
    warnings: list[DiagnosticOut]


class VersionOut(_Answer):
    id: str
    number: int
    published_at: str
    published_by: str | None
    graph_hash: str
    version_hash: str
    cel_profile: str
    node_refs: list[str]
    active: bool
    executable: bool
    blocked_by: list[str]


class ActivatedOut(_Answer):
    active_version_id: str
    number: int
    warnings: list[DiagnosticOut]
```

In `backend/src/dewpoint/apps/api/routes/workflows.py`, import them and set each route's model (the bodies don't
change):

```python
from dewpoint.apps.api.responses import (
    ActivatedOut,
    DraftSavedOut,
    PublishedOut,
    ValidationOut,
    VersionOut,
    WorkflowDetailOut,
    WorkflowOut,
    WorkflowUpdatedOut,
)
```

```python
@router.get("/t/{tenant_id}/workflows", response_model=list[WorkflowOut])
@router.post("/t/{tenant_id}/workflows", status_code=201, response_model=WorkflowDetailOut)
@router.get("/t/{tenant_id}/workflows/{workflow_id}", response_model=WorkflowDetailOut)
@router.put("/t/{tenant_id}/workflows/{workflow_id}/draft", response_model=DraftSavedOut)
@router.patch("/t/{tenant_id}/workflows/{workflow_id}", response_model=WorkflowUpdatedOut)
@router.post("/t/{tenant_id}/workflows/{workflow_id}/validate", response_model=ValidationOut)
@router.post("/t/{tenant_id}/workflows/{workflow_id}/publish", status_code=201, response_model=PublishedOut)
@router.get("/t/{tenant_id}/workflows/{workflow_id}/versions", response_model=list[VersionOut])
@router.post("/t/{tenant_id}/workflows/{workflow_id}/activate", response_model=ActivatedOut)
```

(each replaces the decorator of the same route; the function signatures and bodies stay).

- [ ] **Step 4: Implement the refinement**

Replace the end of `backend/src/dewpoint/apps/api/openapi.py` (from `def schema()`) with:

```python
GRAPH_REF = "#/components/schemas/Graph"
# Bodies a route parses itself, so it can answer `graph.format` diagnostics and its admission checks (non-finite
# numbers, depth, value count) that a body model would turn into `{"error": "invalid", "fields": [...]}`.
GRAPH_BODIES: tuple[tuple[str, str], ...] = (("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft", "put"),)
# Answers that carry a graph verbatim, as saved, rather than re-serialized with defaults its author never wrote.
GRAPH_PROPERTIES: tuple[tuple[str, str], ...] = (("WorkflowDetailOut", "draft"),)


def refine(spec: dict[str, Any]) -> dict[str, Any]:
    """Document as `Graph` what travels as a plain object (ledger ruling 47; 4b ruling 8). FastAPI ignores
    `WithJsonSchema` on a body and merges `openapi_extra` into the object schema it generates, so the schema is
    refined here, once, for the API and `dewpoint api openapi` alike."""
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    graph = Graph.model_json_schema(mode="validation", ref_template="#/components/schemas/{model}")
    for name, sub in graph.pop("$defs", {}).items():
        schemas.setdefault(name, sub)
    schemas.setdefault("Graph", graph)
    for path, method in GRAPH_BODIES:
        spec["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"] = {"$ref": GRAPH_REF}
    for model, prop in GRAPH_PROPERTIES:
        schemas[model]["properties"][prop] = {"$ref": GRAPH_REF}
    return spec


def serve_refined(app: FastAPI) -> None:
    """Make `app` serve the refined schema at OPENAPI_URL."""
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = refine(generate())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]


def schema() -> dict[str, Any]:
    """The schema the API serves at OPENAPI_URL: the same title and routes, in the same order, refined alike."""
    app = FastAPI(title=TITLE, docs_url=None, redoc_url=None, openapi_url=OPENAPI_URL)
    for router in ROUTERS:
        app.include_router(router)
    serve_refined(app)
    return app.openapi()
```

and add `from dewpoint.engine.graph.model import Graph` to its imports. In `backend/src/dewpoint/apps/api/main.py`,
import `serve_refined` beside `OPENAPI_URL, ROUTERS, TITLE`, and call it after the routers are included:

```python
    for router in ROUTERS:
        app.include_router(router)
    serve_refined(app)
    return app
```

The import-linter contracts already let `apps.api` import `engine.graph` (the routes do); `uv run lint-imports`
confirms.

- [ ] **Step 5: Run the tests to see them pass, then everything that reads the schema or calls these routes**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_openapi.py tests/apps/api/test_workflows.py tests/apps/test_workflow_ops.py tests/core/workflows`
Expected: PASS. `test_the_dumped_schema_is_the_one_the_api_serves` still holds: both sides are refined.

- [ ] **Step 6: Regenerate the client's schema and check it** (the milestone's commands). Expected: `schema.d.ts`
  gains `Graph`, `GraphNode`, `Edge`, `EdgeFrom`, `EdgeTo`, `GraphSettings`, `CsvSettings`, `Position`, `Options`
  and the workflow answers; `WorkflowDetailOut["draft"]` is `components["schemas"]["Graph"]`. `typecheck` passes:
  no frontend code calls these routes yet.

- [ ] **Step 7: Commit**

```bash
git add backend/src/dewpoint/apps/api backend/tests/apps/api/test_openapi.py frontend/src/api
git commit -m "feat(api): every workflow route answers a named model; the draft PUT documents its body as a Graph (B1, 4b)"
```

### Task 3: A workflow's summary says how its live runs went, apart from its simulations, and whether its draft is published (B3)

**Files:**
- Create: `backend/src/dewpoint/apps/workflow_summary.py` (in `apps`: it hashes with the engine, and import-linter's
  "core depends on neither engine nor plugins" forbids that in `core`, where revision 1 put it)
- Modify: `backend/src/dewpoint/core/workflows/service.py` (`blocked_by_many`; `blocked_by` uses it)
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`LastRunOut`, `RunCountOut`; `WorkflowOut` and `DraftSavedOut`
  gain fields)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`_summaries`, `_summary`, `list_workflows`, `put_draft`)
- Create: `backend/tests/apps/test_workflow_summary.py`, `backend/tests/apps/api/test_workflow_summary.py`
- Create: `backend/tests/probes/workflow_list.py` (the evidence for the milestone 1 pause; run by hand, never in CI)
- Modify: `backend/tests/apps/api/test_workflows.py:32` (the draft PUT's answer gains its comparison, its graph hash and
  the active version it compared with)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: `runs` (`backend/src/dewpoint/core/models/runs.py:16-39`: `workflow_id` and `workflow_version_id` without a
  foreign key, `mode` live|simulate, `status` running|succeeded|failed|cancelled|deadline_exceeded, `queued_at`,
  `started_at`, `ended_at`, `kind` run|subflow|failure_handler); its only index a list can use,
  `runs_tenant_queued (tenant_id, queued_at DESC, id DESC)` (`migrations/versions/0017_admission.py:183`);
  `service.active_versions(s, tenant_id, workflow_ids)` (`service.py:264`, one read for many workflows);
  `lifecycle.entries_for`, `lifecycle.states` (one read for any number of entries), `lifecycle.not_executable`;
  `graph_hash`, `parse_graph`, `GraphFormatError` (`backend/src/dewpoint/engine/graph/model.py`).
- Produces:
  - in `dewpoint.apps.workflow_summary`: `LAST_RUNS`, `COUNTS_24H` (the two statements, as SQL the probe explains),
    `hash_now(draft)` (one draft's hash, kept nowhere), `run_stats(s, tenant_id, workflow_ids) -> dict[uuid.UUID,
    RunStats]` (`RunStats(last_live, last_simulated, live_24h, simulated_24h)`, `LastRun(status, at)`),
    `attention(stats, *, published, blocked) -> list[str]`, `DraftHashes(kept)` with `async of(drafts) ->
    dict[uuid.UUID, str | None]` and `len()`, the process's `HASHES`;
  - `service.blocked_by_many(s, versions) -> dict[uuid.UUID, list[str]]`; `service.locked_active_version(s,
    workflow_id) -> WorkflowVersion | None` (read after `save_draft`'s update, under the row lock it took);
  - `WorkflowOut` gains `unpublished_changes: bool`, `draft_graph_hash: str | None` (the server's hash of the draft,
    as publish would record it; null for one that doesn't parse), `last_run: LastRunOut | None` (the last live root
    run), `last_simulation: LastRunOut | None` (the last simulated one), `runs_24h: RunCountOut` (`live`,
    `simulate`), `needs_attention: list["last_run_failed" | "not_executable"]`; `LastRunOut` is `status`, `at`;
  - `DraftSavedOut` gains `unpublished_changes`, `graph_hash` (the saved draft's), and `active_version_id` and
    `active_version_number`: the version it was compared with, active when the save landed. The editor keeps the
    hash to recognise its draft in a version (Task 15, 4b ruling 25) and labels the active version from the same
    answer.

The save's comparison is with the version active when its update landed, never with the one the route read before
it (the owner's review of revision 2, correction 5): `put_draft` reads the workflow without a lock, so an activation
can commit between that read and the compare-and-swap; the swap's update takes the row lock, and the active version
read after it can't change before the answer is sent.

The list reads a fixed number of times whatever its length: the workflows, their active versions, the lifecycle states
of every entry those versions use, the last runs and the 24-hour counts, each once for all (the owner's review of
325fc14: no per-workflow refresh, version or lifecycle read). Drafts are hashed off the event loop, all at once, and
once per revision: a draft never changes at a revision (`save_draft` is a compare-and-swap that increments it), so its
hash is kept per (workflow, revision). Whether the last-run read needs an index is ruling 5's, held: the probe of Step 9
measures it against representative history, with and without a candidate index, for the milestone 1 pause.

- [ ] **Step 1: Write the failing unit tests**

`backend/tests/apps/test_workflow_summary.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""B3's pure parts: attention comes from live runs only, and a draft is hashed once per revision."""

import uuid
from datetime import UTC, datetime

import pytest

from dewpoint.apps import workflow_summary as summary
from dewpoint.engine.graph.model import graph_hash, parse_graph
from tests.support.graphs import G

GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()
AT = datetime(2026, 10, 6, tzinfo=UTC)


def stats(live: str | None, simulated: str | None) -> summary.RunStats:
    return summary.RunStats(
        last_live=summary.LastRun(live, AT) if live else None,
        last_simulated=summary.LastRun(simulated, AT) if simulated else None,
        live_24h=0,
        simulated_24h=0,
    )


@pytest.mark.parametrize(
    ("live", "simulated", "expected"),
    [
        ("failed", "succeeded", ["last_run_failed"]),  # a later good simulation never clears a live failure
        ("deadline_exceeded", None, ["last_run_failed"]),
        ("succeeded", "failed", []),  # a failed simulation never needs attention
        (None, "deadline_exceeded", []),
        ("cancelled", None, []),
        ("running", None, []),
    ],
)
def test_only_a_live_run_needs_attention(live: str | None, simulated: str | None, expected: list[str]) -> None:
    assert summary.attention(stats(live, simulated), published=True, blocked=[]) == expected


def test_a_version_that_cant_run_needs_attention() -> None:
    assert summary.attention(stats(None, None), published=True, blocked=["testkit.echo@1"]) == ["not_executable"]
    assert summary.attention(stats(None, None), published=False, blocked=[]) == []


async def test_a_draft_is_hashed_once_per_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    parsed: list[int] = []
    real = summary.parse_graph
    monkeypatch.setattr(summary, "parse_graph", lambda d: parsed.append(1) or real(d))
    hashes, wid = summary.DraftHashes(kept=8), uuid.uuid4()
    first = await hashes.of([(wid, 1, GRAPH)])
    again = await hashes.of([(wid, 1, GRAPH)])
    assert first == again == {wid: graph_hash(parse_graph(GRAPH))} and len(parsed) == 1
    await hashes.of([(wid, 2, GRAPH)])
    assert len(parsed) == 2


async def test_a_draft_that_doesnt_parse_has_no_hash() -> None:
    wid = uuid.uuid4()
    assert await summary.DraftHashes(kept=8).of([(wid, 1, {"graph_format": 9})]) == {wid: None}


async def test_the_kept_hashes_are_bounded() -> None:
    hashes = summary.DraftHashes(kept=2)
    drafts = [(uuid.uuid4(), 1, GRAPH) for _ in range(3)]
    assert len(await hashes.of(drafts)) == 3  # every draft asked for is answered
    assert len(hashes) == 2  # the oldest is forgotten


async def test_a_read_answers_what_it_found_kept_even_when_another_evicts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two lists at once, the bound passed between them: each answers every draft it asked for (never a KeyError)."""
    gates: list[asyncio.Event] = []

    async def held(fn: Any) -> Any:  # the thread's work, released when the test says
        gate = asyncio.Event()
        gates.append(gate)
        await gate.wait()
        return fn()

    hashes = summary.DraftHashes(kept=2)
    kept = (uuid.uuid4(), 1, GRAPH)
    await hashes.of([kept])  # kept, with the real thread
    monkeypatch.setattr(summary.asyncio, "to_thread", held)
    first = asyncio.create_task(hashes.of([kept, (uuid.uuid4(), 1, GRAPH)]))  # finds `kept`, computes the other
    second = asyncio.create_task(hashes.of([(uuid.uuid4(), 1, GRAPH), (uuid.uuid4(), 1, GRAPH)]))
    while len(gates) < 2:
        await asyncio.sleep(0)
    gates[1].set()  # the second ends first: its two new hashes evict `kept`
    await second
    gates[0].set()
    assert len(await first) == 2


async def test_a_draft_being_saved_is_hashed_but_never_kept() -> None:
    before = len(summary.HASHES)
    assert await summary.hash_now(GRAPH) == graph_hash(parse_graph(GRAPH))
    assert len(summary.HASHES) == before
```

(`asyncio` and `typing.Any` join the imports.)

- [ ] **Step 2: Write the failing API tests**

`backend/tests/apps/api/test_workflow_summary.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What the workflows list shows of each (sub-project 4, B3): its last live root run and, apart, its last simulated one;
its root runs in the last 24 hours, live and simulated apart; whether its draft differs from its active version; why it
needs attention, from live runs only. Its reads don't grow with its workflows."""

import uuid
from typing import Any

import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

from dewpoint.engine.graph.model import graph_hash, parse_graph
from tests.apps.api.helpers import session_client
from tests.support.graphs import G
from tests.support.registry import sync_test_plugins

GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()
WORKFLOW_TABLES = ("workflows", "workflow_versions", "runs", "node_type_versions", "cel_profiles")


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def add_run(owner, tid, wid, vid, *, status, mode="live", hours_ago=1.0, parent=None) -> uuid.UUID:
    """A run row as the dispatcher writes one: a root run, or a sub-flow's when `parent` is given."""
    rid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(
            text(
                "insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, iterations,"
                " kind, parent_run_id, parent_step_id) values (:i, :t, :w, :v, :m, :st,"
                " now() - make_interval(secs => :ago), 0, :k, :p, :ps)"
            ),
            {
                "i": rid, "t": tid, "w": wid, "v": vid, "m": mode, "st": status, "ago": hours_ago * 3600,
                "k": "subflow" if parent else "run", "p": parent, "ps": uuid.uuid4() if parent else None,
            },
        )  # fmt: skip
    return rid


async def published(c, tid) -> tuple[str, str]:
    wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": f"W {uuid.uuid4().hex[:6]}", "draft": GRAPH})).json()
    v = (await c.post(f"/api/v1/t/{tid}/workflows/{wf['id']}/publish", headers={"If-Match": "1"})).json()
    return wf["id"], v["version_id"]


async def test_the_list_says_how_each_workflows_runs_went(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, vid = await published(c, tid)
        root = await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", hours_ago=30)  # out of the 24 h
        await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", hours_ago=2)
        await add_run(owner_sessionmaker, tid, wid, vid, status="failed", hours_ago=0.5)  # the last live root run
        await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", mode="simulate", hours_ago=0.2)
        await add_run(owner_sessionmaker, tid, wid, vid, status="running", hours_ago=0.1, parent=root)  # a sub-run
        quiet, _ = await published(c, tid)
        rows = {w["id"]: w for w in (await c.get(f"/api/v1/t/{tid}/workflows")).json()}
    busy = rows[wid]
    assert busy["draft_graph_hash"] == graph_hash(parse_graph(GRAPH))
    assert busy["last_run"]["status"] == "failed" and busy["last_simulation"]["status"] == "succeeded"
    assert busy["runs_24h"] == {"live": 2, "simulate": 1}
    assert busy["needs_attention"] == ["last_run_failed"]  # the later successful simulation doesn't clear it
    assert busy["unpublished_changes"] is False
    assert rows[quiet]["last_run"] is None and rows[quiet]["last_simulation"] is None
    assert rows[quiet]["runs_24h"] == {"live": 0, "simulate": 0} and rows[quiet]["needs_attention"] == []


async def test_a_failed_simulation_never_needs_attention(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, vid = await published(c, tid)
        await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", hours_ago=2)
        await add_run(owner_sessionmaker, tid, wid, vid, status="failed", mode="simulate", hours_ago=1)
        row = (await c.get(f"/api/v1/t/{tid}/workflows/{wid}")).json()
    assert row["last_run"]["status"] == "succeeded" and row["last_simulation"]["status"] == "failed"
    assert row["needs_attention"] == []


async def test_another_tenants_runs_never_count(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    other, otid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c, other:
        wid, _ = await published(c, tid)
        owid, ovid = await published(other, otid)
        # A row claiming the first tenant's workflow id, in the other tenant: RLS and the tenant filter both drop it.
        await add_run(owner_sessionmaker, otid, wid, ovid, status="failed")
        row = (await c.get(f"/api/v1/t/{tid}/workflows/{wid}")).json()
    assert row["last_run"] is None and row["runs_24h"] == {"live": 0, "simulate": 0}


async def test_a_moved_step_is_an_unpublished_change(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        new = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Never", "draft": GRAPH})).json()
        assert new["unpublished_changes"] is True and new["active_version_number"] is None  # ruling 6
        wid, _ = await published(c, tid)
        base = f"/api/v1/t/{tid}/workflows/{wid}"
        same = (await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "1"})).json()
        assert (same["draft_revision"], same["unpublished_changes"]) == (2, False)
        assert (same["graph_hash"], same["active_version_number"]) == (graph_hash(parse_graph(GRAPH)), 1)
        moved = G().node("a", "testkit.echo@1", {"value": 1}).data()
        moved["nodes"][0]["position"] = {"x": 40, "y": 0}
        saved = (await c.put(f"{base}/draft", json=moved, headers={"If-Match": "2"})).json()
        assert (saved["draft_revision"], saved["unpublished_changes"]) == (3, True)
        row = (await c.get(base)).json()
        assert row["unpublished_changes"] is True and row["draft_graph_hash"] == graph_hash(parse_graph(moved))


async def test_a_save_compares_with_the_version_active_when_it_lands(
    app, owner_sessionmaker, api_settings, monkeypatch
) -> None:
    """An activation commits between the route's read of the workflow and its compare-and-swap: the answer names the
    version active when the save landed, and compares with that one (the owner's review of revision 2)."""
    from dewpoint.core.workflows import service

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, v1 = await published(c, tid)  # version 1 is GRAPH
        base = f"/api/v1/t/{tid}/workflows/{wid}"
        moved = G().node("a", "testkit.echo@1", {"value": 1}).data()
        moved["nodes"][0]["position"] = {"x": 40, "y": 0}
        await c.put(f"{base}/draft", json=moved, headers={"If-Match": "1"})
        v2 = (await c.post(f"{base}/publish", headers={"If-Match": "2"})).json()  # version 2 is `moved`, active
        real = service.save_draft

        async def activated_meanwhile(s, wf, **kw):  # wf was read with version 2 active
            async with owner_sessionmaker() as other, other.begin():  # as an activation of version 1 commits
                await other.execute(
                    text("update workflows set active_version_id = :v where id = :w"), {"v": uuid.UUID(v1), "w": uuid.UUID(wid)}
                )
            return await real(s, wf, **kw)

        monkeypatch.setattr(service, "save_draft", activated_meanwhile)
        saved = (await c.put(f"{base}/draft", json=moved, headers={"If-Match": "2"})).json()
    assert v2["number"] == 2
    assert (saved["active_version_id"], saved["active_version_number"]) == (v1, 1)
    assert saved["unpublished_changes"] is True  # `moved` against version 1, never against the stale version 2


async def test_a_version_that_cant_run_needs_attention(
    app, owner_sessionmaker, api_settings, admin_sessionmaker
) -> None:
    from dewpoint.core.plugins import lifecycle
    from dewpoint.core.plugins.lifecycle import Entry

    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wid, _ = await published(c, tid)
        base = f"/api/v1/t/{tid}/workflows/{wid}"
        assert (await c.patch(base, json={"enabled": False})).json()["enabled"] is False
        async with admin_sessionmaker() as s, s.begin():  # as test_workflows.py retires: its only user is disabled
            assert (await lifecycle.retire(s, Entry("node", "testkit.echo@1"))).applied
        row = (await c.get(base)).json()
    assert row["executable"] is False and row["needs_attention"] == ["not_executable"]


async def statements_listing(c, tid) -> int:
    """The statements one list request runs against a workflow's tables (the session's own reads are left out: a
    session's bookkeeping may differ from one request to the next)."""
    seen: list[str] = []

    def on(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        seen.append(statement)

    event.listen(Engine, "before_cursor_execute", on)
    try:
        assert (await c.get(f"/api/v1/t/{tid}/workflows")).status_code == 200
    finally:
        event.remove(Engine, "before_cursor_execute", on)
    return len([s for s in seen if any(t in s for t in WORKFLOW_TABLES)])


async def test_the_lists_reads_dont_grow_with_its_workflows(app, owner_sessionmaker, api_settings) -> None:
    """Counted in statements, never time (the owner's review of 325fc14): two workflows or twelve, published or not,
    with runs or without, the list reads as often."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        for _ in range(2):
            wid, vid = await published(c, tid)
            await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded")
        few = await statements_listing(c, tid)
        for n in range(10):
            if n % 2:
                await c.post(f"/api/v1/t/{tid}/workflows", json={"name": f"Draft {n}", "draft": GRAPH})
            else:
                wid, vid = await published(c, tid)
                await add_run(owner_sessionmaker, tid, wid, vid, status="failed", mode="simulate")
        many = await statements_listing(c, tid)
    assert few == many <= 6  # workflows, active versions, two lifecycle reads at most, last runs, counts
```

In `backend/tests/apps/api/test_workflows.py:32`, the draft PUT's answer gains the new fields:

```python
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert (body["draft_revision"], body["unpublished_changes"], body["active_version_id"]) == (2, True, None)
        assert body["graph_hash"] == graph_hash(parse_graph(GRAPH))
```

(`graph_hash` and `parse_graph` join that file's imports from `dewpoint.engine.graph.model`.)

- [ ] **Step 3: Run the tests to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_workflow_summary.py tests/apps/api/test_workflow_summary.py tests/apps/api/test_workflows.py`
Expected: FAIL: `ImportError: cannot import name 'workflow_summary'`, `KeyError: 'last_run'` (and
`'unpublished_changes'`), the draft PUT's answer lacks its new fields, the statement count grows with the workflows
(today's `_summary` refreshes each workflow and reads its version and lifecycle states one by one), and the save
answers no active version.

- [ ] **Step 4: Implement `workflow_summary.py`**

`backend/src/dewpoint/apps/workflow_summary.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What the workflows list shows of each workflow beyond its row (sub-project 4, B3): its last live root run and, apart,
its last simulated one; its root runs in the last 24 hours, live and simulated apart; whether its draft differs from
its active version; and why it needs attention. Live runs alone drive attention (4b ruling 7): a simulation is a
test, and a later successful one says nothing about the live failure before it."""

import asyncio
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.engine.graph.model import GraphFormatError, graph_hash, parse_graph

ATTENTION_STATUSES = ("failed", "deadline_exceeded")

# Each workflow's last root run of each mode. `runs` has no index on `workflow_id` (4b ruling 5, held on the probe's
# evidence): this is one scan of the tenant's root runs, sorted, whatever the number of workflows.
LAST_RUNS = text(
    "select distinct on (workflow_id, mode) workflow_id, mode, status, coalesce(ended_at, started_at, queued_at) as at"
    " from runs where tenant_id = :tenant and kind = 'run' and workflow_id = any(cast(:ids as uuid[]))"
    " order by workflow_id, mode, queued_at desc, id desc"
)
# Each workflow's root runs queued in the last 24 hours, by the database's clock (its clock wrote the rows): a range of
# `runs_tenant_queued`.
COUNTS_24H = text(
    "select workflow_id, count(*) filter (where mode = 'live') as live,"
    " count(*) filter (where mode = 'simulate') as simulated"
    " from runs where tenant_id = :tenant and kind = 'run' and workflow_id = any(cast(:ids as uuid[]))"
    " and queued_at >= now() - interval '24 hours' group by workflow_id"
)


@dataclass(frozen=True)
class LastRun:
    status: str
    at: datetime  # when it ended, else started, else was queued


@dataclass(frozen=True)
class RunStats:
    last_live: LastRun | None
    last_simulated: LastRun | None
    live_24h: int
    simulated_24h: int


async def run_stats(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RunStats]:
    """Each workflow's root runs, in two reads for any number of workflows: a sub-flow's or failure handler's run
    counts toward its parent's, never as the workflow's own."""
    ids = sorted(set(workflow_ids), key=str)
    if not ids:
        return {}
    params = {"tenant": tenant_id, "ids": ids}
    last = {(r.workflow_id, r.mode): LastRun(r.status, r.at) for r in await s.execute(LAST_RUNS, params)}
    counts = {r.workflow_id: (int(r.live), int(r.simulated)) for r in await s.execute(COUNTS_24H, params)}
    return {
        wid: RunStats(
            last_live=last.get((wid, "live")),
            last_simulated=last.get((wid, "simulate")),
            live_24h=counts.get(wid, (0, 0))[0],
            simulated_24h=counts.get(wid, (0, 0))[1],
        )
        for wid in ids
    }


def attention(stats: RunStats, *, published: bool, blocked: Sequence[str]) -> list[str]:
    """Why a workflow needs attention: its last live root run failed or ran out of time, or its active version can't
    run. Simulations never count (4b ruling 7)."""
    out: list[str] = []
    if stats.last_live is not None and stats.last_live.status in ATTENTION_STATUSES:
        out.append("last_run_failed")
    if published and blocked:
        out.append("not_executable")
    return out


def _hash(draft: Mapping[str, Any]) -> str | None:
    try:
        return graph_hash(parse_graph(draft))
    except GraphFormatError:  # every draft is format-checked when saved; one that isn't can't equal a version
        return None


class DraftHashes:
    """Each draft's graph hash as publish computes it (positions included), None for one that doesn't parse. A draft
    never changes at its revision, so its hash is kept per (workflow, revision), the newest `kept`; the rest are parsed
    together, off the event loop (parsing is CPU-bound, up to the 1 MiB body cap a draft)."""

    def __init__(self, kept: int) -> None:
        self._kept = kept
        self._hashes: OrderedDict[tuple[uuid.UUID, int], str | None] = OrderedDict()

    def __len__(self) -> int:
        return len(self._hashes)

    async def of(self, drafts: Sequence[tuple[uuid.UUID, int, Mapping[str, Any]]]) -> dict[uuid.UUID, str | None]:
        """Only for drafts read from committed rows: a revision's hash is kept, so it must be that revision's."""
        # What's kept is taken before the await: another read may evict it meanwhile.
        found = {(wid, rev): self._hashes[(wid, rev)] for wid, rev, _ in drafts if (wid, rev) in self._hashes}
        missing = [(wid, rev, draft) for wid, rev, draft in drafts if (wid, rev) not in found]
        if missing:
            computed = await asyncio.to_thread(lambda: [_hash(draft) for _, _, draft in missing])
            found.update({(wid, rev): h for (wid, rev, _), h in zip(missing, computed, strict=True)})
        for key, value in found.items():
            self._hashes[key] = value
            self._hashes.move_to_end(key)
        while len(self._hashes) > self._kept:
            self._hashes.popitem(last=False)
        return {wid: found[(wid, rev)] for wid, rev, _ in drafts}


async def hash_now(draft: Mapping[str, Any]) -> str | None:
    """One draft's hash, off the event loop, kept nowhere: for a draft not yet committed (a save in progress could
    still roll back, and a retry reuse its revision with another draft)."""
    return await asyncio.to_thread(_hash, draft)


HASHES = DraftHashes(kept=4096)  # about 150 bytes each: under 1 MB per API process
```

- [ ] **Step 5: Run the unit tests to see them pass**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_workflow_summary.py`
Expected: PASS.

- [ ] **Step 6: Implement the batched lifecycle read and the answers**

In `backend/src/dewpoint/core/workflows/service.py`, replace `blocked_by` with:

```python
async def blocked_by_many(s: AsyncSession, versions: Iterable[WorkflowVersion]) -> dict[uuid.UUID, list[str]]:
    """Each version's lifecycle entries that stop it from running (retired or missing), in one read of the states of
    every entry any of them uses."""
    entries = {v.id: lifecycle.entries_for(v.closure_node_refs, v.closure_cel_profiles) for v in versions}
    current = await lifecycle.states(s, {e for used in entries.values() for e in used})
    return {
        version_id: [e.key for e in lifecycle.not_executable({e: current[e] for e in used})]
        for version_id, used in entries.items()
    }


async def blocked_by(s: AsyncSession, version: WorkflowVersion) -> list[str]:
    """Lifecycle entries in the version's closure that stop it from running (retired or missing)."""
    return (await blocked_by_many(s, [version]))[version.id]
```

`lifecycle.states` answers an empty set without reading (`lifecycle.py:85-105`).

In `backend/src/dewpoint/apps/api/responses.py`, before `WorkflowOut`:

```python
class LastRunOut(_Answer):
    status: Literal["running", "succeeded", "failed", "cancelled", "deadline_exceeded"]
    at: str  # when it ended, else started, else was queued
```

```python
class RunCountOut(_Answer):
    live: int
    simulate: int
```

and add to `WorkflowOut`, after `updated_at` (B3):

```python
    unpublished_changes: bool  # the draft differs from the active version (true when nothing is published)
    draft_graph_hash: str | None  # the draft's graph hash as publish would record it; null when it doesn't parse
    last_run: LastRunOut | None  # its last live root run: what attention follows
    last_simulation: LastRunOut | None  # its last simulated root run, shown apart, never attention
    runs_24h: RunCountOut  # its root runs queued in the last 24 hours, live and simulated apart
    needs_attention: list[Literal["last_run_failed", "not_executable"]]
```

and to `DraftSavedOut`:

```python
    unpublished_changes: bool  # against `active_version_*`, the version active when the save landed
    graph_hash: str | None  # the saved draft's, as publish would record it
    active_version_id: str | None
    active_version_number: int | None
```

In `backend/src/dewpoint/apps/api/routes/workflows.py`, import it (`from dewpoint.apps import workflow_ops,
workflow_summary`), and replace `_summary` with:

```python
def _last(run: workflow_summary.LastRun | None) -> dict[str, str] | None:
    return None if run is None else {"status": run.status, "at": run.at.isoformat()}


async def _summaries(db: AsyncSession, tenant_id: uuid.UUID, wfs: list[Workflow]) -> list[dict[str, object]]:
    """Each workflow's row (B3), in a fixed number of reads whatever their number: the active versions, the lifecycle
    states of every entry they use, the last runs and the 24-hour counts, each read once for all."""
    ids = [wf.id for wf in wfs]
    actives = await service.active_versions(db, tenant_id, ids)
    blocked = await service.blocked_by_many(db, actives.values())
    stats = await workflow_summary.run_stats(db, tenant_id, ids)
    hashes = await workflow_summary.HASHES.of([(wf.id, wf.draft_revision, wf.draft) for wf in wfs])
    out: list[dict[str, object]] = []
    for wf in wfs:
        active = actives.get(wf.id)
        stops = blocked[active.id] if active else []
        runs = stats[wf.id]
        out.append(
            {
                "id": str(wf.id),
                "name": wf.name,
                "enabled": wf.enabled,
                "draft_revision": wf.draft_revision,
                "active_version_id": str(active.id) if active else None,
                "active_version_number": active.number if active else None,
                "executable": (not stops) if active else None,
                "blocked_by": stops,
                "created_at": wf.created_at.isoformat(),
                "updated_at": wf.updated_at.isoformat(),
                "unpublished_changes": active is None or hashes[wf.id] != active.graph_hash,
                "draft_graph_hash": hashes[wf.id],
                "last_run": _last(runs.last_live),
                "last_simulation": _last(runs.last_simulated),
                "runs_24h": {"live": runs.live_24h, "simulate": runs.simulated_24h},
                "needs_attention": workflow_summary.attention(runs, published=active is not None, blocked=stops),
            }
        )
    return out


async def _summary(db: AsyncSession, wf: Workflow) -> dict[str, object]:
    """One workflow just read, created or changed: its server-set columns (`updated_at`) are read back first."""
    await db.refresh(wf)
    return (await _summaries(db, wf.tenant_id, [wf]))[0]
```

`list_workflows` reads each row fresh, so it needs no refresh:

```python
    return await _summaries(db, ctx.tenant_id, await service.list_workflows(db, ctx.tenant_id))
```

In `backend/src/dewpoint/core/workflows/service.py`, after `save_draft`:

```python
async def locked_active_version(s: AsyncSession, workflow_id: uuid.UUID) -> WorkflowVersion | None:
    """The workflow's active version, read after this transaction updated its row (`save_draft`): the row lock it holds
    until commit keeps an activation from changing it before the answer is sent. A `Workflow` read before the update
    may name an older one (`save_draft` updates with `synchronize_session=False`)."""
    q = (
        select(WorkflowVersion)
        .join(Workflow, Workflow.active_version_id == WorkflowVersion.id)
        .where(Workflow.id == workflow_id)
    )
    return (await s.execute(q)).scalar_one_or_none()
```

`put_draft` answers the comparison, with the version it compared against, and the saved draft's hash. It hashes the
draft without keeping the hash: the transaction commits only after the handler returns, and a rolled-back save's
revision can come back with another draft (the next list hashes it from the committed row).

```python
    try:
        revision = await service.save_draft(db, wf, expected_revision=expected, draft=draft)
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    active = await service.locked_active_version(db, wf.id)  # never `wf.active_version_id`: it may predate the swap
    saved = await workflow_summary.hash_now(draft)
    return {
        "draft_revision": revision,
        "unpublished_changes": active is None or saved != active.graph_hash,
        "graph_hash": saved,
        "active_version_id": str(active.id) if active else None,
        "active_version_number": active.number if active else None,
    }
```

- [ ] **Step 7: Run the tests to see them pass, then the workflow suites**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/test_workflow_summary.py tests/core/workflows tests/apps/api/test_workflow_summary.py tests/apps/api/test_workflows.py tests/apps/api/test_openapi.py tests/apps/test_workflow_ops.py`
Expected: PASS. If the raw `runs` insert of Step 2 trips a CHECK this plan doesn't name (a sub-run's columns), adapt
the helper to the constraint the error names, never the code under test. If the statement count's bound of 6 is
missed by a read the middleware makes of a workflow table, name that statement in the test's docstring and keep
`few == many`, which is the property; never loosen the equality.

- [ ] **Step 8: Regenerate the client's schema and check it.** Expected: `WorkflowOut` gains its six fields and
  `DraftSavedOut` its four.

- [ ] **Step 9: Write the probe, and run it for the milestone 1 pause**

`backend/tests/probes/workflow_list.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""The workflows list's cost (sub-project 4, B3), the evidence 4b ruling 5 is held on: what its run statistics read
against a tenant's run history, without an index on `workflow_id` and with a candidate one, and what hashing its
drafts costs. Run by hand, never in CI; on a disposable Postgres 16 (testcontainers), synthetic data only. From
`backend/`:

    PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.workflow_list <part> [sizes...]

- `plans`: `workflow_summary.LAST_RUNS` and `.COUNTS_24H`, EXPLAIN (ANALYZE, BUFFERS), for a tenant of 200 workflows
  whose root runs (one in ten simulated, one in twenty failed, spread over 30 days, as many sub-runs again) number
  10k, 100k and 1M by default, beside another tenant's 1M; then the same with the candidate index `runs (workflow_id,
  mode, queued_at DESC, id DESC) WHERE kind = 'run'`, made in the disposable database only (an index in the product
  is a migration: a slot from the owner), and the per-workflow LATERAL read that index would allow;
- `hashing`: `DraftHashes.of()` for 50, 200 and 500 drafts of 30 steps: cold (each parsed), then warm (kept).

Numbers depend on the machine; record them with it."""

import asyncio
import statistics
import sys
import time
import uuid
from typing import Any

from tests.probes.ingress_load import Database, ms

WORKFLOWS = 200
SIZES = (10_000, 100_000, 1_000_000)
CANDIDATE = (
    "create index probe_runs_workflow_last on runs (workflow_id, mode, queued_at desc, id desc) where kind = 'run'"
)
LATERAL = (
    "select w.id as workflow_id, m.mode, r.status, r.at from unnest(cast(:ids as uuid[])) w(id)"
    " cross join (values ('live'), ('simulate')) m(mode) cross join lateral ("
    " select status, coalesce(ended_at, started_at, queued_at) as at from runs where tenant_id = :tenant"
    " and kind = 'run' and workflow_id = w.id and mode = m.mode order by queued_at desc, id desc limit 1) r"
)
ROOTS = (
    "with roots as (insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at,"
    " iterations, kind) select gen_random_uuid(), cast(:t as uuid),"
    " (cast(:w as uuid[]))[1 + g % cardinality(cast(:w as uuid[]))], gen_random_uuid(),"
    " case when g % 10 = 0 then 'simulate' else 'live' end,"
    " case when g % 20 = 0 then 'failed' else 'succeeded' end, now() - make_interval(secs => g % 2592000), 0, 'run'"
    " from generate_series(cast(:a as integer), cast(:b as integer)) g returning id, workflow_id, mode, queued_at)"
    " insert into runs (id, tenant_id, workflow_id, workflow_version_id, mode, status, queued_at, iterations, kind,"
    " parent_run_id, parent_step_id) select gen_random_uuid(), cast(:t as uuid), workflow_id, gen_random_uuid(), mode,"
    " 'succeeded', queued_at, 0, 'subflow', id, gen_random_uuid() from roots where cast(:subs as boolean)"
)


async def tenant(owner: Any) -> uuid.UUID:
    from sqlalchemy import text

    tid = uuid.uuid4()
    async with owner() as s, s.begin():
        await s.execute(text("insert into tenants(id,name,slug) values (:t,'T',:slug)"), {"t": tid, "slug": tid.hex[:12]})
    return tid


async def grow(owner: Any, tid: uuid.UUID, workflows: list[uuid.UUID], a: int, b: int, *, subs: bool) -> None:
    from sqlalchemy import text

    async with owner() as s, s.begin():
        await s.execute(text(ROOTS), {"t": tid, "w": workflows, "a": a, "b": b, "subs": subs})
    async with owner() as s, s.begin():
        await s.execute(text("analyze runs"))


async def explain(api: Any, tid: uuid.UUID, sql: str, params: dict[str, Any]) -> tuple[float, str]:
    """The statement's plan, executed as the list runs it: the API's role, in the tenant's scope, under row-level
    security (the owner's session would bypass it). Answers (execution time in seconds, the plan's text)."""
    from sqlalchemy import text

    from dewpoint.core.db import tenant_scope

    async with api() as s, s.begin():
        await tenant_scope(s, tid)
        rows = [r[0] for r in await s.execute(text(f"explain (analyze, buffers) {sql}"), params)]
    took = next(float(r.split(":")[1].split()[0]) for r in rows if r.startswith("Execution Time"))
    return took / 1000, "\n".join(rows)


async def plans(db: Database, sizes: tuple[int, ...] = SIZES) -> None:
    from dewpoint.apps import workflow_summary as summary

    owner, api = db.sessions(), db.sessions("dewpoint_api")
    tid, noise = await tenant(owner), await tenant(owner)
    workflows = [uuid.uuid4() for _ in range(WORKFLOWS)]
    await grow(owner, noise, [uuid.uuid4() for _ in range(WORKFLOWS)], 1, max(sizes), subs=False)
    params = {"tenant": tid, "ids": workflows}
    reads = {"last runs (DISTINCT ON)": summary.LAST_RUNS.text, "24 h counts": summary.COUNTS_24H.text}
    done = 0
    for size in sizes:
        await grow(owner, tid, workflows, done + 1, size, subs=True)
        done = size
        for label, sql in reads.items():
            took = statistics.median([(await explain(api, tid, sql, params))[0] for _ in range(5)])
            print(f"\n### {size:,} root runs, no index: {label}, median of 5: {ms(took)}")
            print((await explain(api, tid, sql, params))[1])
    from sqlalchemy import text

    async with owner() as s, s.begin():
        await s.execute(text(CANDIDATE))
        await s.execute(text("analyze runs"))
    for label, sql in {**reads, "last runs (LATERAL)": LATERAL}.items():
        took = statistics.median([(await explain(api, tid, sql, params))[0] for _ in range(5)])
        print(f"\n### {done:,} root runs, candidate index: {label}, median of 5: {ms(took)}")
        print((await explain(api, tid, sql, params))[1])


async def hashing() -> None:
    from dewpoint.apps.workflow_summary import DraftHashes
    from tests.support.graphs import G

    def draft(n: int) -> dict[str, Any]:
        g = G()
        for i in range(n):
            g.node(f"s{i}", "flow.transform@1", {"fields": {"v": i}})
            if i:
                g.edge(f"s{i - 1}", f"s{i}")
        return g.data()

    print("| drafts of 30 steps | cold | warm |\n|---|---|---|")
    for count in (50, 200, 500):
        drafts = [(uuid.uuid4(), 1, draft(30)) for _ in range(count)]
        hashes = DraftHashes(kept=4096)
        start = time.perf_counter()
        await hashes.of(drafts)
        cold = time.perf_counter() - start
        start = time.perf_counter()
        await hashes.of(drafts)
        print(f"| {count} | {ms(cold)} | {ms(time.perf_counter() - start)} |")


def run(part: str, *args: str) -> None:
    if part == "hashing":
        asyncio.run(hashing())
        return
    sizes = tuple(int(a) for a in args) or SIZES
    with Database() as db:

        async def go() -> None:
            await db.prepared()
            await plans(db, sizes)

        asyncio.run(go())


if __name__ == "__main__":
    run(*sys.argv[1:])
```

`ROOTS` makes the sub-runs in the same statement as their roots (a writable CTE; `runs.parent_run_id`'s foreign key is
checked at the statement's end). Its `where cast(:subs as boolean)` keeps the other tenant's history to root runs. Its
binds carry their types: SQLAlchemy's asyncpg dialect sends `text()` binds untyped, and Postgres 16 refuses
`generate_series(unknown, unknown)` as ambiguous (found by the revision's review, on a throwaway `postgres:16-alpine`).
The data goes in as the container's owner; the plans are explained as the API's role, in the tenant's scope, so
row-level security is in them as it is in the list.

Run it smallest first and extrapolate before the full size (the owner's rule: ask before anything over about ten
minutes):

```bash
cd backend && PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.workflow_list hashing
cd backend && PYTHONPATH=$PWD/src:$PWD .venv/bin/python -m tests.probes.workflow_list plans 10000 100000
```

If the second run's insert and analyze times put 1M (and the other tenant's 1M) past ten minutes, stop and ask the
owner with the estimate; otherwise run `plans` at its default sizes. Save each run's output, with the machine's CPU,
memory and Docker allocation, in the scratchpad's `evidence/` (never in the repo), for the pause's summary. The probe
is committed; its numbers aren't.

- [ ] **Step 10: Commit**

```bash
git add backend/src/dewpoint/apps backend/src/dewpoint/core/workflows/service.py backend/tests/apps/test_workflow_summary.py \
  backend/tests/apps/api/test_workflow_summary.py backend/tests/apps/api/test_workflows.py \
  backend/tests/probes/workflow_list.py frontend/src/api
git commit -m "feat(api): a workflow's summary: live runs drive attention, simulations apart; the list reads a fixed number of times (B3, 4b)"
```

### Task 4: A version can be read whole (B4a), and publish can be bound to the version number it names

**Files:**
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`VersionOut.engine_abi`; `VersionDetailOut`)
- Modify: `backend/src/dewpoint/core/workflows/service.py` (`VersionChangedError`, `latest_version_number`)
- Modify: `backend/src/dewpoint/apps/workflow_ops.py` (`publish(..., expected_latest_version=None)`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`_version_out`; `GET …/versions/{version_id}`;
  `PublishIn`, the publish route's optional body and its `version_changed` refusal)
- Modify: `backend/src/dewpoint/apps/api/openapi.py` (`GRAPH_PROPERTIES` gains `("VersionDetailOut", "graph")`)
- Create: `backend/tests/apps/api/test_workflow_versions.py`
- Modify: `backend/tests/apps/api/test_openapi.py` (`SLICE_4B` gains the route; the publish body)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: `WorkflowVersion.graph`, `.engine_abi`, `.expressions` (each `ExpressionRecord.to_json()`, with `node`,
  `field`, `mode`, `reason` among its keys: `backend/src/dewpoint/engine/cel/record.py:21-40`); the publish route's
  lock: `_get(..., for_update=True)` takes the workflow's admission lock and its row lock (`service.get_workflow`,
  `service.py:86-99`) and holds both until the publication commits; `insert_version` numbers the next version under
  that lock (`service.py:177-182`).
- Produces:
  - `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}` → `VersionDetailOut` (every `VersionOut`
    field, plus `graph` (verbatim, documented as `Graph`) and `expressions: ExpressionOut[]`); `VersionOut` gains
    `engine_abi: int` (B4b's "not recorded" rule reads it). Permission `workflow.view`.
  - `POST …/publish` takes an optional body `PublishIn {expected_latest_version: int | null (≥ 0)}`, extra keys
    refused: the number of the newest version the editor showed when it asked (0: none yet). Checked under the
    publication's own lock; a mismatch answers `409 {"error": "version_changed", "latest_version": n}` and publishes
    nothing. A draft conflict is checked first and keeps its answer. Without a body, or with `{}` or a null, publish
    behaves as before (every existing caller, the CLI and the tests).
  - `service.VersionChangedError(latest)`, `service.latest_version_number(s, workflow_id) -> int`;
    `workflow_ops.publish(s, ctx, wf, *, expected_revision, settings, expected_latest_version=None)`.

Why a precondition (4b ruling 17, amended): the confirmation names a number ("Publish version 3"). Without a check
under the same lock that numbers it, a second publisher between the dialog's opening and the click would make this one
version 4, so the dialog would have named a version it didn't publish. With it, the editor learns of the other
publication, refreshes, and asks again.

- [ ] **Step 1: Write the failing tests**

`backend/tests/apps/api/test_workflow_versions.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A published version read whole (sub-project 4, B4a): its graph, how its expressions run, and its engine ABI. And
publish bound to the version number the editor named (4b ruling 17)."""

import asyncio
import uuid

import pytest

from dewpoint.engine import ENGINE_ABI
from tests.apps.api.helpers import member_client, session_client
from tests.support.graphs import G, cel
from tests.support.registry import sync_test_plugins

GRAPH = G().node("a", "testkit.echo@1", {"value": cel("1 + 1")}).data()


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


async def test_a_version_is_read_whole(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W", "draft": GRAPH})).json()
        base = f"/api/v1/t/{tid}/workflows/{wf['id']}"
        v = (await c.post(f"{base}/publish", headers={"If-Match": "1"})).json()
        listed = (await c.get(f"{base}/versions")).json()
        got = await c.get(f"{base}/versions/{v['version_id']}")
    assert listed[0]["engine_abi"] == ENGINE_ABI
    assert got.status_code == 200, got.text
    body = got.json()
    assert (body["number"], body["engine_abi"], body["active"]) == (1, ENGINE_ABI, True)
    assert [n["key"] for n in body["graph"]["nodes"]] == ["a"]
    assert body["expressions"] == [{"node": GRAPH["nodes"][0]["id"], "field": "/value", "mode": "local", "reason": None}]


async def test_only_this_workflows_versions_are_read(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        a = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "A", "draft": GRAPH})).json()
        b = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "B", "draft": GRAPH})).json()
        va = (await c.post(f"/api/v1/t/{tid}/workflows/{a['id']}/publish", headers={"If-Match": "1"})).json()
        wrong = await c.get(f"/api/v1/t/{tid}/workflows/{b['id']}/versions/{va['version_id']}")
        missing = await c.get(f"/api/v1/t/{tid}/workflows/{a['id']}/versions/{uuid.uuid4()}")
    assert (wrong.status_code, wrong.json()) == (404, {"error": "not_found"})
    assert missing.status_code == 404
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, tid, "viewer")
    async with viewer:
        assert (await viewer.get(f"/api/v1/t/{tid}/workflows/{a['id']}/versions/{va['version_id']}")).status_code == 200
    stranger, other = await session_client(app, owner_sessionmaker, api_settings, "owner")
    async with stranger:
        path = f"/api/v1/t/{other}/workflows/{a['id']}/versions/{va['version_id']}"
        assert (await stranger.get(path)).status_code == 404


async def new_workflow(c, tid) -> str:
    wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": f"W {uuid.uuid4().hex[:6]}", "draft": GRAPH})).json()
    return f"/api/v1/t/{tid}/workflows/{wf['id']}"


async def test_publish_names_the_version_it_expects(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        first = await c.post(f"{base}/publish", headers={"If-Match": "1"}, json={"expected_latest_version": 0})
        assert (first.status_code, first.json()["number"]) == (201, 1)
        stale = await c.post(f"{base}/publish", headers={"If-Match": "1"}, json={"expected_latest_version": 0})
        assert (stale.status_code, stale.json()) == (409, {"error": "version_changed", "latest_version": 1})
        assert [v["number"] for v in (await c.get(f"{base}/versions")).json()] == [1]  # nothing published
        second = await c.post(f"{base}/publish", headers={"If-Match": "1"}, json={"expected_latest_version": 1})
        assert (second.status_code, second.json()["number"]) == (201, 2)


@pytest.mark.parametrize("body", [None, {}, {"expected_latest_version": None}])
async def test_publish_without_an_expectation_behaves_as_before(app, owner_sessionmaker, api_settings, body) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        await c.post(f"{base}/publish", headers={"If-Match": "1"})
        r = await c.post(f"{base}/publish", headers={"If-Match": "1"}, **({} if body is None else {"json": body}))
    assert (r.status_code, r.json()["number"]) == (201, 2)


@pytest.mark.parametrize(
    "body", [{"expected_latest_version": -1}, {"expected_latest": 1}, {"expected_latest_version": "1"}, {"expected_latest_version": True}]
)
async def test_a_malformed_expectation_is_refused(app, owner_sessionmaker, api_settings, body) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        r = await c.post(f"{base}/publish", headers={"If-Match": "1"}, json=body)
        assert (await c.get(f"{base}/versions")).json() == []
    assert r.status_code == 422 and r.json()["error"] == "invalid"


async def test_a_draft_conflict_is_answered_before_a_version_change(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        await c.post(f"{base}/publish", headers={"If-Match": "1"})
        r = await c.post(f"{base}/publish", headers={"If-Match": "7"}, json={"expected_latest_version": 0})
    assert (r.status_code, r.json()) == (409, {"error": "draft_conflict", "draft_revision": 1})


async def test_two_publishers_naming_one_version_publish_it_once(app, owner_sessionmaker, api_settings) -> None:
    """The expectation is checked under the lock that numbers the version: of two editors who both saw version 1, one
    publishes version 2 and the other is told, never silently publishing version 3."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        base = await new_workflow(c, tid)
        await c.post(f"{base}/publish", headers={"If-Match": "1"})
        both = await asyncio.gather(
            *(c.post(f"{base}/publish", headers={"If-Match": "1"}, json={"expected_latest_version": 1}) for _ in range(2))
        )
        numbers = [v["number"] for v in (await c.get(f"{base}/versions")).json()]
    assert sorted(r.status_code for r in both) == [201, 409]
    assert next(r for r in both if r.status_code == 409).json() == {"error": "version_changed", "latest_version": 2}
    assert numbers == [2, 1]
```

The `/value` pointer and the `local` mode assume `testkit.echo`'s config property is `value` and `1 + 1` runs inline;
if the echo node names its field otherwise, use the pointer `test_workflows.py`'s expression-class test asserts.

In `backend/tests/apps/api/test_openapi.py`, add `("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}")`
to `SLICE_4B`, and:

```python
def test_a_versions_graph_is_documented_as_a_graph() -> None:
    assert schema()["components"]["schemas"]["VersionDetailOut"]["properties"]["graph"] == GRAPH


def test_publishs_body_is_optional() -> None:
    """Verified against FastAPI 0.141.1: an optional body model is documented as itself or null, not required."""
    body = schema()["paths"]["/api/v1/t/{tenant_id}/workflows/{workflow_id}/publish"]["post"]["requestBody"]
    assert "required" not in body
    assert body["content"]["application/json"]["schema"]["anyOf"] == [
        {"$ref": "#/components/schemas/PublishIn"},
        {"type": "null"},
    ]
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_workflow_versions.py tests/apps/api/test_openapi.py`
Expected: FAIL: `KeyError: 'engine_abi'`, a 404 or 405 for the version route, `KeyError: 'VersionDetailOut'`, a 201
where `version_changed` is expected (the body is ignored today), the race publishing versions 2 and 3, and no
`requestBody` on publish.

- [ ] **Step 3: Implement the version read**

In `backend/src/dewpoint/apps/api/responses.py`, add `engine_abi: int` to `VersionOut` after `cel_profile`, and after
`VersionOut`:

```python
class VersionDetailOut(VersionOut):
    """One version whole (B4a): its graph, verbatim as published (documented as a Graph), and how each of its
    expressions runs."""

    graph: dict[str, Any]
    expressions: list[ExpressionOut]
```

In `backend/src/dewpoint/apps/api/routes/workflows.py`, `_version_out` gains `"engine_abi": v.engine_abi,` after
`"cel_profile"`, and a new route follows `versions`:

```python
@router.get("/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}", response_model=VersionDetailOut)
async def version(
    workflow_id: uuid.UUID,
    version_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    wf = await _get(db, ctx, workflow_id)
    v = await service.get_version(db, wf.id, version_id)
    if v is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return {
        **_version_out(v, wf.active_version_id, await service.blocked_by(db, v)),
        "graph": v.graph,
        "expressions": [
            {"node": e.get("node"), "field": e["field"], "mode": e["mode"], "reason": e.get("reason")}
            for e in v.expressions
        ],
    }
```

(import `VersionDetailOut`). In `backend/src/dewpoint/apps/api/openapi.py`:

```python
GRAPH_PROPERTIES: tuple[tuple[str, str], ...] = (("WorkflowDetailOut", "draft"), ("VersionDetailOut", "graph"))
```

- [ ] **Step 4: Implement the publish precondition**

In `backend/src/dewpoint/core/workflows/service.py`, after `DraftConflictError`:

```python
class VersionChangedError(Exception):
    """A publish named the newest version it expected, and another is newest now."""

    def __init__(self, latest: int) -> None:
        super().__init__(f"the newest version is {latest}")
        self.latest = latest
```

and after `insert_version`, with `insert_version`'s own count replaced by it:

```python
async def latest_version_number(s: AsyncSession, workflow_id: uuid.UUID) -> int:
    """The newest version's number, 0 when none: the caller holds the workflow's row lock, so it can't change."""
    latest = await s.execute(
        select(func.coalesce(func.max(WorkflowVersion.number), 0)).where(WorkflowVersion.workflow_id == workflow_id)
    )
    return int(latest.scalar_one())
```

(`insert_version` then reads `number = await latest_version_number(s, wf.id) + 1`.)

In `backend/src/dewpoint/apps/workflow_ops.py`, `publish` gains the expectation, checked after the draft's revision and
before any validation, under the lock its caller holds:

```python
async def publish(
    s: AsyncSession,
    ctx: TenantContext,
    wf: Workflow,
    *,
    expected_revision: int,
    settings: Settings,
    expected_latest_version: int | None = None,
) -> Published:
    """Validate the draft and insert it as the new active version. `wf` must be locked FOR UPDATE. With
    `expected_latest_version`, publish only if the newest version is still that one (0: none), so the number a
    confirmation named is the number published (4b ruling 17); else VersionChangedError."""
    if wf.draft_revision != expected_revision:
        raise service.DraftConflictError(wf.draft_revision)
    if expected_latest_version is not None:
        latest = await service.latest_version_number(s, wf.id)
        if latest != expected_latest_version:
            raise service.VersionChangedError(latest)
    checked = await check_draft(s, ctx.tenant_id, wf.draft, settings)
```

(the rest unchanged). In `backend/src/dewpoint/apps/api/routes/workflows.py`, beside the other bodies (import
`ConfigDict` from pydantic):

```python
class PublishIn(BaseModel):
    """What the editor showed when it asked to publish (4b ruling 17). Extra keys are refused: a misspelt expectation
    must never be dropped silently, publishing what nobody confirmed."""

    model_config = ConfigDict(extra="forbid")
    expected_latest_version: int | None = Field(default=None, ge=0, strict=True)  # 0: no version yet
```

and the publish route takes it and answers the new refusal:

```python
async def publish(
    workflow_id: uuid.UUID,
    body: PublishIn | None = None,
    if_match: str | None = Header(default=None, alias="If-Match"),
    ctx: TenantContext = Depends(require(P.WORKFLOW_PUBLISH)),
    db: AsyncSession = Depends(get_db, scope="function"),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    expected = _revision(if_match)
    wf = await _get(db, ctx, workflow_id, for_update=True)
    try:
        out = await workflow_ops.publish(
            db,
            ctx,
            wf,
            expected_revision=expected,
            settings=settings,
            expected_latest_version=body.expected_latest_version if body else None,
        )
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    except service.VersionChangedError as e:
        raise HTTPException(409, detail={"error": "version_changed", "latest_version": e.latest}) from None
```

(the rest unchanged). Verified against pydantic 2.13.5 and FastAPI 0.141.1: no body, `{}` and a null each give
`None`; `0` and `3` pass; `-1` is refused (`greater_than_equal`), `"1"`, `1.0` and `true` (`int_type`: `strict=True`, so
lax mode's string-to-int is off), and an extra key (`extra_forbidden`); the API's handler answers each as
`{"error": "invalid", ...}`. The schema is `{"anyOf": [{"$ref": "#/components/schemas/PublishIn"}, {"type": "null"}]}`
with no `required`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_workflow_versions.py tests/apps/api/test_openapi.py tests/apps/api/test_workflows.py tests/apps/test_workflow_ops.py tests/apps/test_admission.py`
Expected: PASS. `test_workflow_ops.py`'s and `test_admission.py`'s `publish` helpers pass no expectation and behave
as before.

- [ ] **Step 6: Regenerate the client's schema and check it.** Expected: `PublishIn` appears; publish's
  `requestBody` is optional; `VersionDetailOut` and `VersionOut.engine_abi` appear.

- [ ] **Step 7: Commit**

```bash
git add backend/src/dewpoint/apps backend/src/dewpoint/core/workflows/service.py \
  backend/tests/apps/api/test_workflow_versions.py backend/tests/apps/api/test_openapi.py frontend/src/api
git commit -m "feat(api): a version read whole (B4a); publish bound to the version number the editor named (4b)"
```

### Task 5: A workflow exports to a file with typed placeholders and imports with each re-bound, fail-closed (B12)

**Files:**
- Create: `backend/src/dewpoint/core/workflows/portable.py` (pure: no engine import, so it may live in `core`)
- Modify: `backend/src/dewpoint/core/workflows/service.py` (`create_workflow(..., source=None)`)
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`BindingSite`, `Binding`, `WorkflowDocument`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`WorkflowImportIn`; `GET …/{workflow_id}/export`,
  `POST /t/{tenant_id}/workflows/import`)
- Modify: `backend/src/dewpoint/apps/api/openapi.py` (`GRAPH_PROPERTIES` gains `("WorkflowDocument", "graph")`)
- Create: `backend/tests/core/workflows/test_portable.py`, `backend/tests/apps/api/test_workflow_portable.py`
- Modify: `backend/tests/apps/api/test_openapi.py` (`SLICE_4B` gains both routes)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: the connection marker `x-dewpoint-connection: <type key>` (`dewpoint.sdk.fields.CONNECTION`), which the SDK
  allows on a top-level config property only (`backend/src/dewpoint/sdk/manifest.py:162-182` refuses a plugin that
  nests it) on a literal UUID field; `flow.run_workflow@1`'s literal `workflow_id: uuid.UUID`
  (`backend/src/dewpoint/plugins/flow/nodes.py:162-173`); `GraphSettings.failure_handler: uuid.UUID | None`
  (`backend/src/dewpoint/engine/graph/model.py:113`); `registry.load_node_types(db, refs)` (every state: a retired
  type's schema still says where its ids are); `Connection.type`, `.name`; `parse_graph`, which doesn't refuse two
  steps sharing an id (`model.py:173-185`).
- Produces: in `portable`: `Site(kind, type, node, field)`, `Problem(reason, binding, node, field)` with `to_json()`,
  `sites(graph, config_schemas)`, `value_at(graph, site)`, `held(draft, config_schemas) -> list[tuple[Site, str]]`,
  `export_document(name, draft, config_schemas, labels) -> dict`, `check_document(graph, bindings, config_schemas) ->
  list[Problem]`, `apply(graph, bindings, chosen, config_schemas) -> dict`, `NotPortableError(problems)`,
  `BadDocumentError(problems)`; the routes `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/export` →
  `WorkflowDocument` (`workflow.view`) and `POST /api/v1/t/{tenant_id}/workflows/import` (`{name, document, bind:
  {binding id: uuid}}`, extra keys refused) → 201 `WorkflowDetailOut` (`workflow.edit`).
- Refusals, each writing nothing:
  - export: `422 {"error": "not_portable", "problems": [{"reason", "binding": null, "node", "field"}]}`, reasons
    `unknown_type` (a step of a type this server doesn't know: its config may hold an id no schema marks),
    `duplicate_node` (two steps share an id: a site would name either), `unexpected_value` (a site holding anything
    but an id: an expression, a number, a string that isn't a UUID);
  - import, the file: `422 {"error": "invalid", ...}` for an envelope the model refuses (format, version, a `null`
    graph or binding, extra keys, a binding id outside `^[a-z][a-z0-9_]{0,31}$`, a binding with no site); `422
    {"error": "invalid", "diagnostics"}` for a graph whose format is wrong; `422 {"error": "bad_document",
    "problems": [...]}`, reasons `unknown_type`, `duplicate_node`, `embedded_value` (an id where a binding goes:
    "leave unbound" would keep it), `duplicate_binding`, `overlapping_site` (a site listed twice), `bad_site` (not, by
    this server's schemas, a site of the binding's kind and connection type: no such step, a property its type
    doesn't mark, a nested pointer, other settings);
  - import, the choices: `422 {"error": "bad_binding", "binding", "reason": "unexpected" | "unknown" |
    "wrong_type"}`; `409 name_taken`.

4b ruling 18, amended (the owner's review of 325fc14): export refuses rather than approximates, and import checks the
whole file against this server's node types before it writes. Revision 1 kept a connection's id in the file when its
step's schema was missing, accepted any config property as a binding's site, and let "leave unbound" keep an id the
file embedded.

- [ ] **Step 1: Write the failing unit tests**

`backend/tests/core/workflows/test_portable.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A workflow as a file (sub-project 4, B12), fail-closed: no tenant's id leaves but as a typed placeholder, and an
import writes nothing it hasn't checked against this server's node types."""

import copy
import uuid

import pytest

from dewpoint.core.workflows import portable
from tests.support.graphs import cel

CALL, SUB, OTHER = (str(uuid.uuid4()) for _ in range(3))
C1, W1 = str(uuid.uuid4()), str(uuid.uuid4())
SCHEMAS = {
    "testkit.http_call@1": {
        "properties": {"connection": {"type": "string", "x-dewpoint-connection": "testkit"}, "path": {"type": "string"}}
    },
    "flow.run_workflow@1": {"properties": {"workflow_id": {"type": "string"}, "input": {"type": "object"}}},
}
LABELS = {("connection", C1): "Acme Prod", ("workflow", W1): "Cleanup"}


def draft(conn: object = C1, sub: object = W1, handler: object = W1) -> dict:
    return {
        "graph_format": 1,
        "nodes": [
            {"id": CALL, "key": "call", "type": "testkit.http_call@1", "config": {"connection": conn, "path": "/x"}},
            {"id": SUB, "key": "sub", "type": "flow.run_workflow@1", "config": {"workflow_id": sub, "input": {}}},
        ],
        "edges": [],
        "settings": {"failure_handler": handler},
    }


def exported() -> dict:
    return portable.export_document("Nightly", draft(), SCHEMAS, LABELS)


def problems(doc: dict) -> list[tuple[str, str | None, str | None, str | None]]:
    found = portable.check_document(doc["graph"], doc["bindings"], SCHEMAS)
    return [(p.reason, p.binding, p.node, p.field) for p in found]


def test_the_markers_are_the_sdks_and_the_flow_plugins() -> None:
    from dewpoint.plugins.flow.nodes import RunWorkflow
    from dewpoint.sdk.fields import CONNECTION

    assert portable.CONNECTION_MARKER == CONNECTION
    assert portable.RUN_WORKFLOW == f"{RunWorkflow.type}@{RunWorkflow.version}"


def test_export_replaces_each_tenant_id_with_a_typed_placeholder() -> None:
    doc = exported()
    assert (doc["format"], doc["format_version"], doc["name"]) == ("dewpoint.workflow", 1, "Nightly")
    assert doc["bindings"] == [
        {"id": "b1", "kind": "connection", "type": "testkit", "label": "Acme Prod",
         "sites": [{"node": CALL, "field": "/connection"}]},
        {"id": "b2", "kind": "workflow", "type": None, "label": "Cleanup",
         "sites": [{"node": SUB, "field": "/workflow_id"}, {"node": None, "field": "/settings/failure_handler"}]},
    ]  # fmt: skip
    nodes = {n["key"]: n for n in doc["graph"]["nodes"]}
    assert nodes["call"]["config"] == {"path": "/x"} and nodes["sub"]["config"] == {"input": {}}
    assert "failure_handler" not in doc["graph"]["settings"]


def test_an_id_the_tenant_doesnt_name_is_labelled_unknown() -> None:
    doc = portable.export_document("Nightly", draft(), SCHEMAS, {})
    assert [b["label"] for b in doc["bindings"]] == ["Unknown connection", "Unknown workflow"]


def test_an_empty_site_is_emptied_and_exports_no_binding() -> None:
    doc = portable.export_document("Nightly", draft(conn=None, handler=None), SCHEMAS, LABELS)
    assert [(b["id"], b["kind"]) for b in doc["bindings"]] == [("b1", "workflow")]
    assert "connection" not in doc["graph"]["nodes"][0]["config"] and doc["graph"]["settings"] == {}


def test_one_id_at_two_sites_is_one_binding() -> None:
    two = draft()
    two["nodes"].append({"id": OTHER, "key": "again", "type": "testkit.http_call@1", "config": {"connection": C1.upper()}})
    doc = portable.export_document("Nightly", two, SCHEMAS, LABELS)
    assert doc["bindings"][0]["sites"] == [{"node": CALL, "field": "/connection"}, {"node": OTHER, "field": "/connection"}]


def test_a_step_of_a_type_this_server_doesnt_know_isnt_exported() -> None:
    odd = draft()
    odd["nodes"].append({"id": OTHER, "key": "odd", "type": "vendor.unknown@1", "config": {"account": C1}})
    with pytest.raises(portable.NotPortableError) as e:
        portable.export_document("Nightly", odd, SCHEMAS, LABELS)
    assert [p.to_json() for p in e.value.problems] == [
        {"reason": "unknown_type", "binding": None, "node": OTHER, "field": None}
    ]


@pytest.mark.parametrize(
    ("changed", "where"),
    [
        (draft(conn=cel("vars.c")), (CALL, "/connection")),  # an expression where an id goes
        (draft(conn="not-a-uuid"), (CALL, "/connection")),
        (draft(sub=7), (SUB, "/workflow_id")),
        (draft(handler="nope"), (None, "/settings/failure_handler")),
    ],
)
def test_a_site_holding_anything_but_an_id_isnt_exported(changed: dict, where: tuple) -> None:
    with pytest.raises(portable.NotPortableError) as e:
        portable.export_document("Nightly", changed, SCHEMAS, LABELS)
    assert [(p.reason, p.node, p.field) for p in e.value.problems] == [("unexpected_value", *where)]


def test_two_steps_sharing_an_id_arent_exported() -> None:
    twins = draft()
    twins["nodes"].append(copy.deepcopy(twins["nodes"][0]) | {"key": "twin"})
    with pytest.raises(portable.NotPortableError) as e:
        portable.export_document("Nightly", twins, SCHEMAS, LABELS)
    assert [(p.reason, p.node) for p in e.value.problems] == [("duplicate_node", CALL)]


def test_import_binds_each_placeholder_and_round_trips() -> None:
    doc = exported()
    assert problems(doc) == []
    assert portable.apply(doc["graph"], doc["bindings"], {"b1": C1, "b2": W1}, SCHEMAS) == draft()


def test_an_unbound_placeholder_leaves_its_sites_empty() -> None:
    doc = exported()
    back = portable.apply(doc["graph"], doc["bindings"], {"b1": C1}, SCHEMAS)
    nodes = {n["key"]: n for n in back["nodes"]}
    assert nodes["call"]["config"]["connection"] == C1
    assert "workflow_id" not in nodes["sub"]["config"] and "failure_handler" not in back["settings"]


def test_an_embedded_id_is_refused() -> None:
    doc = exported()
    doc["graph"]["nodes"][0]["config"]["connection"] = C1  # left unbound, it would stay
    doc["graph"]["settings"]["failure_handler"] = W1
    assert problems(doc) == [
        ("embedded_value", None, CALL, "/connection"),
        ("embedded_value", None, None, "/settings/failure_handler"),
    ]


@pytest.mark.parametrize(
    ("site", "kind"),
    [
        ({"node": str(uuid.uuid4()), "field": "/connection"}, "connection"),  # no such step
        ({"node": CALL, "field": "/path"}, "connection"),  # a property its type doesn't mark
        ({"node": CALL, "field": "/nested/connection"}, "connection"),  # nested: the SDK marks top-level only
        ({"node": None, "field": "/settings/outputs"}, "workflow"),  # settings other than the failure handler
        ({"node": SUB, "field": "/workflow_id"}, "connection"),  # a workflow's site, bound as a connection
        ({"node": CALL, "field": "/connection"}, "workflow"),  # a connection's site, bound as a workflow
    ],
)
def test_a_site_an_import_may_not_write_is_refused(site: dict, kind: str) -> None:
    doc = exported()
    doc["bindings"] = [
        {"id": "b7", "kind": kind, "type": "testkit" if kind == "connection" else None, "label": "x", "sites": [site]}
    ]
    assert problems(doc) == [("bad_site", "b7", site["node"], site["field"])]


def test_a_connection_binding_takes_its_sites_type() -> None:
    doc = exported()
    doc["bindings"][0]["type"] = "mist"
    assert problems(doc) == [("bad_site", "b1", CALL, "/connection")]


def test_binding_ids_and_sites_are_each_used_once() -> None:
    doc = exported()
    doc["bindings"].append(copy.deepcopy(doc["bindings"][0]))
    assert problems(doc) == [("duplicate_binding", "b1", None, None), ("overlapping_site", "b1", CALL, "/connection")]


def test_a_step_of_a_type_this_server_doesnt_know_isnt_imported() -> None:
    doc = exported()
    doc["graph"]["nodes"].append({"id": OTHER, "key": "odd", "type": "vendor.unknown@1", "config": {}})
    assert problems(doc) == [("unknown_type", None, OTHER, None)]


def test_apply_refuses_whatever_the_check_refuses() -> None:
    doc = exported()
    doc["graph"]["nodes"][0]["config"]["connection"] = C1
    with pytest.raises(portable.BadDocumentError) as e:
        portable.apply(doc["graph"], doc["bindings"], {"b1": C1}, SCHEMAS)
    assert [p.reason for p in e.value.problems] == ["embedded_value"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/core/workflows/test_portable.py`
Expected: FAIL: `ImportError: cannot import name 'portable'`.

- [ ] **Step 3: Implement `portable.py`**

`backend/src/dewpoint/core/workflows/portable.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A workflow as a file (sub-project 4, B12; 4b ruling 18), fail-closed. Exported, every id of the tenant's a draft
holds where a binding goes (a connection field, a `flow.run_workflow`'s `workflow_id`, the failure handler) becomes a
typed placeholder, and a draft that can't be made portable for certain is refused, never approximated. Imported, the
file is checked whole against this server's node types before anything is written; each placeholder is then bound to
one of the importing tenant's connections or workflows, or left unbound, its sites empty. Schedules, webhook bindings
and CSV mappings are rows, not graph: they don't travel."""

import copy
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

FORMAT = "dewpoint.workflow"
FORMAT_VERSION = 1
CONNECTION_MARKER = "x-dewpoint-connection"  # dewpoint.sdk.fields.CONNECTION; the SDK allows it top-level only
RUN_WORKFLOW = "flow.run_workflow@1"  # the flow plugin's; its `workflow_id` is a literal workflow id
FAILURE_HANDLER = "/settings/failure_handler"
UNKNOWN = {"connection": "Unknown connection", "workflow": "Unknown workflow"}

Kind = Literal["connection", "workflow"]


@dataclass(frozen=True)
class Site:
    kind: Kind
    type: str | None  # the connection type a connection site takes; None for a workflow
    node: str | None  # a step's id as the graph holds it; None for the workflow's settings
    field: str  # a top-level config property (`/connection`), or FAILURE_HANDLER


@dataclass(frozen=True)
class Problem:
    reason: str
    binding: str | None = None
    node: str | None = None
    field: str | None = None

    def to_json(self) -> dict[str, str | None]:
        return {"reason": self.reason, "binding": self.binding, "node": self.node, "field": self.field}


class NotPortableError(ValueError):
    """The draft can't be exported without risking one of the tenant's ids in the file."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(", ".join(p.reason for p in problems))
        self.problems = problems


class BadDocumentError(ValueError):
    """The file can't be imported as it is."""

    def __init__(self, problems: list[Problem]) -> None:
        super().__init__(", ".join(p.reason for p in problems))
        self.problems = problems


def _nodes(graph: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [n for n in graph.get("nodes") or [] if isinstance(n, Mapping)]


def _node(graph: Mapping[str, Any], node_id: str) -> Any:
    return next((n for n in _nodes(graph) if str(n.get("id")) == node_id), None)


def _shape(graph: Mapping[str, Any], config_schemas: Mapping[str, Mapping[str, Any]]) -> list[Problem]:
    """What keeps anyone from knowing where a graph's ids are: two steps sharing an id (a site would name either), or
    a step of a type this server doesn't know (its config may hold an id no schema marks)."""
    counted = Counter(str(n.get("id")) for n in _nodes(graph))
    out = [Problem("duplicate_node", node=node_id) for node_id, seen in counted.items() if seen > 1]
    for n in _nodes(graph):
        ref = n.get("type")
        if not isinstance(ref, str) or ref not in config_schemas:
            out.append(Problem("unknown_type", node=str(n.get("id"))))
    return out


def sites(graph: Mapping[str, Any], config_schemas: Mapping[str, Mapping[str, Any]]) -> list[Site]:
    """Every place a graph may hold an id of the tenant's, by its steps' schemas: each top-level config property a type
    marks as a connection, each `flow.run_workflow`'s `workflow_id`, and the failure handler. Only for a graph in
    which `_shape` finds nothing."""
    out: list[Site] = []
    for node in _nodes(graph):
        ref, node_id = str(node.get("type")), str(node.get("id"))
        for prop, spec in (config_schemas[ref].get("properties") or {}).items():
            if isinstance(spec, Mapping) and isinstance(spec.get(CONNECTION_MARKER), str):
                out.append(Site("connection", spec[CONNECTION_MARKER], node_id, f"/{prop}"))
        if ref == RUN_WORKFLOW:
            out.append(Site("workflow", None, node_id, "/workflow_id"))
    out.append(Site("workflow", None, None, FAILURE_HANDLER))
    return out


def value_at(graph: Mapping[str, Any], site: Site) -> Any:
    """What a site holds; None when it holds nothing."""
    if site.node is None:
        settings = graph.get("settings")
        return settings.get("failure_handler") if isinstance(settings, Mapping) else None
    node = _node(graph, site.node)
    config = node.get("config") if node is not None else None
    return config.get(site.field[1:]) if isinstance(config, Mapping) else None


def _empty(graph: dict[str, Any], site: Site) -> None:
    if site.node is None:
        settings = graph.get("settings")
        if isinstance(settings, dict):
            settings.pop("failure_handler", None)
        return
    node = _node(graph, site.node)
    if node is not None and isinstance(node.get("config"), dict):
        node["config"].pop(site.field[1:], None)


def _canonical(value: Any) -> str | None:
    """The id a value names, canonical; None for anything else (an expression, a number, a string that isn't one)."""
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def held(draft: Mapping[str, Any], config_schemas: Mapping[str, Mapping[str, Any]]) -> list[tuple[Site, str]]:
    """Each site holding an id, with that id, canonical. NotPortableError when the draft can't be made portable for
    certain: what `_shape` finds, or a site holding anything but an id."""
    problems = _shape(draft, config_schemas)
    if problems:
        raise NotPortableError(problems)
    out: list[tuple[Site, str]] = []
    for site in sites(draft, config_schemas):
        value = value_at(draft, site)
        if value is None:
            continue
        canonical = _canonical(value)
        if canonical is None:
            problems.append(Problem("unexpected_value", node=site.node, field=site.field))
        else:
            out.append((site, canonical))
    if problems:
        raise NotPortableError(problems)
    return out


def export_document(
    name: str,
    draft: Mapping[str, Any],
    config_schemas: Mapping[str, Mapping[str, Any]],
    labels: Mapping[tuple[str, str], str],
) -> dict[str, Any]:
    """The file: the draft with every site emptied, and one binding per distinct (kind, connection type, id), in the
    order first met, with each site it filled. `labels` maps (kind, canonical id) to its name in the tenant."""
    found = held(draft, config_schemas)
    graph = copy.deepcopy(dict(draft))
    for site in sites(draft, config_schemas):
        _empty(graph, site)
    bindings: dict[tuple[str, str | None, str], dict[str, Any]] = {}
    for site, value in found:
        key = (site.kind, site.type, value)
        if key not in bindings:
            bindings[key] = {
                "id": f"b{len(bindings) + 1}",
                "kind": site.kind,
                "type": site.type,
                "label": labels.get((site.kind, value), UNKNOWN[site.kind]),
                "sites": [],
            }
        bindings[key]["sites"].append({"node": site.node, "field": site.field})
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "name": name,
        "graph": graph,
        "bindings": list(bindings.values()),
    }


def check_document(
    graph: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]], config_schemas: Mapping[str, Mapping[str, Any]]
) -> list[Problem]:
    """Every reason a file can't be imported as it is, all at once: what `_shape` finds; an id embedded where a binding
    goes (left unbound, it would stay); a binding id used twice; a site listed twice; a site that isn't, by this
    server's schemas, one of the binding's kind and connection type."""
    problems = _shape(graph, config_schemas)
    if problems:
        return problems
    allowed = {(s.node, s.field): s for s in sites(graph, config_schemas)}
    problems += [
        Problem("embedded_value", node=s.node, field=s.field) for s in allowed.values() if value_at(graph, s) is not None
    ]
    ids: set[str] = set()
    listed: set[tuple[str | None, str]] = set()
    for binding in bindings:
        if binding["id"] in ids:
            problems.append(Problem("duplicate_binding", binding=binding["id"]))
        ids.add(binding["id"])
        for site in binding["sites"]:
            key = (site["node"], site["field"])
            target = allowed.get(key)
            if key in listed:
                problems.append(Problem("overlapping_site", binding=binding["id"], node=key[0], field=key[1]))
            elif target is None or target.kind != binding["kind"] or target.type != binding["type"]:
                problems.append(Problem("bad_site", binding=binding["id"], node=key[0], field=key[1]))
            listed.add(key)
    return problems


def apply(
    graph: Mapping[str, Any],
    bindings: Sequence[Mapping[str, Any]],
    chosen: Mapping[str, str],
    config_schemas: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """The graph with each chosen binding's id written at each of its sites; an unbound binding's stay empty. Refuses
    (BadDocumentError) whatever `check_document` refuses, so nothing unchecked is ever written."""
    problems = check_document(graph, bindings, config_schemas)
    if problems:
        raise BadDocumentError(problems)
    out = copy.deepcopy(dict(graph))
    for binding in bindings:
        value = chosen.get(binding["id"])
        if value is None:
            continue
        for site in binding["sites"]:
            if site["node"] is None:
                out.setdefault("settings", {})["failure_handler"] = value
            else:
                _node(out, site["node"]).setdefault("config", {})[site["field"][1:]] = value
    return out
```

`apply` writes into a graph whose format the route has checked (`settings` and `config` are objects or absent), and
only at sites `check_document` found in it.

- [ ] **Step 4: Run the unit tests to see them pass**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/core/workflows/test_portable.py && uv run lint-imports`
Expected: PASS, and the contracts kept (`portable` imports nothing outside the standard library).

- [ ] **Step 5: Write the failing API tests**

`backend/tests/apps/api/test_workflow_portable.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Exporting a workflow and importing it into another tenant (sub-project 4, B12), fail-closed both ways."""

import uuid
from collections.abc import Callable

import pytest

from tests.apps.api.helpers import member_client, session_client
from tests.support.connections import add_connection
from tests.support.graphs import cel
from tests.support.registry import sync_test_plugins

CALL, SUB = str(uuid.uuid4()), str(uuid.uuid4())


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


def draft(conn: object, sub: str) -> dict:
    return {
        "graph_format": 1,
        "nodes": [
            {"id": CALL, "key": "call", "type": "testkit.http_call@1", "config": {"connection": conn, "path": "/x"}},
            {"id": SUB, "key": "sub", "type": "flow.run_workflow@1", "config": {"workflow_id": sub, "input": {}}},
        ],
        "edges": [{"from": {"node": CALL, "port": "out"}, "to": {"node": SUB}}],
        "settings": {"failure_handler": sub},
    }


async def exported(app, owner_sessionmaker, api_settings) -> dict:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    conn = await add_connection(owner_sessionmaker, tid)
    async with c:
        sub = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Cleanup"})).json()
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Nightly", "draft": draft(str(conn), sub["id"])})).json()
        r = await c.get(f"/api/v1/t/{tid}/workflows/{wf['id']}/export")
    assert r.status_code == 200, r.text
    return r.json()


async def imported(app, owner_sessionmaker, api_settings, doc: dict, bind: dict | None = None) -> tuple:
    """Import into a fresh tenant: (the answer, that tenant's workflows after it)."""
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        body = {"name": "Imported", "document": doc, **({"bind": bind} if bind else {})}
        r = await c.post(f"/api/v1/t/{tid}/workflows/import", json=body)
        listed = (await c.get(f"/api/v1/t/{tid}/workflows")).json()
    return r, listed


async def test_the_file_carries_no_tenant_id(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    assert [(b["id"], b["kind"], b["type"]) for b in doc["bindings"]] == [("b1", "connection", "testkit"),
                                                                          ("b2", "workflow", None)]  # fmt: skip
    assert doc["bindings"][1]["label"] == "Cleanup" and len(doc["bindings"][1]["sites"]) == 2
    nodes = {n["key"]: n for n in doc["graph"]["nodes"]}
    assert nodes["call"]["config"] == {"path": "/x"} and nodes["sub"]["config"] == {"input": {}}
    assert "failure_handler" not in doc["graph"]["settings"]


async def test_importing_binds_each_placeholder_to_this_tenants_own(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    conn = await add_connection(owner_sessionmaker, tid)
    async with c:
        target = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Target"})).json()
        r = await c.post(
            f"/api/v1/t/{tid}/workflows/import",
            json={"name": "Imported", "document": doc, "bind": {"b1": str(conn), "b2": target["id"]}},
        )
        assert r.status_code == 201, r.text
        audit = (await c.get(f"/api/v1/t/{tid}/audit")).json()
    assert r.json()["draft"] == draft(str(conn), target["id"])
    assert r.json()["name"] == "Imported" and r.json()["draft_revision"] == 1
    assert audit[0]["action"] == "workflow.create" and audit[0]["details"] == {"name": "Imported", "source": "import"}


@pytest.mark.parametrize("case", ["wrong_type", "unknown", "unexpected"])
async def test_a_binding_of_the_wrong_kind_is_refused_and_nothing_is_created(
    app, owner_sessionmaker, api_settings, case
) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    _, elsewhere = await session_client(app, owner_sessionmaker, api_settings, "editor")
    bind = {
        "wrong_type": {"b1": str(await add_connection(owner_sessionmaker, tid, type_key="mist"))},
        "unknown": {"b1": str(await add_connection(owner_sessionmaker, elsewhere))},  # another tenant's
        "unexpected": {"b9": str(uuid.uuid4())},
    }[case]
    async with c:
        r = await c.post(f"/api/v1/t/{tid}/workflows/import", json={"name": "Imported", "document": doc, "bind": bind})
        listed = (await c.get(f"/api/v1/t/{tid}/workflows")).json()
    assert r.status_code == 422 and r.json() == {"error": "bad_binding", "binding": next(iter(bind)), "reason": case}
    assert listed == []


async def test_an_unbound_placeholder_imports_with_its_sites_empty(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    r, _ = await imported(app, owner_sessionmaker, api_settings, doc)
    assert r.status_code == 201, r.text
    assert r.json()["draft"]["nodes"][0]["config"] == {"path": "/x"}


async def test_a_file_embedding_an_id_is_refused_and_nothing_is_created(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    doc["graph"]["nodes"][0]["config"]["connection"] = str(uuid.uuid4())  # "leave unbound" would keep it
    r, listed = await imported(app, owner_sessionmaker, api_settings, doc)
    assert (r.status_code, r.json()) == (
        422,
        {"error": "bad_document", "problems": [{"reason": "embedded_value", "binding": None, "node": CALL, "field": "/connection"}]},
    )  # fmt: skip
    assert listed == []


async def test_a_binding_naming_a_property_its_step_doesnt_mark_is_refused(app, owner_sessionmaker, api_settings) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    doc["bindings"][0]["sites"] = [{"node": CALL, "field": "/path"}]
    r, listed = await imported(app, owner_sessionmaker, api_settings, doc, {"b1": str(uuid.uuid4())})
    assert r.status_code == 422 and r.json()["problems"] == [
        {"reason": "bad_site", "binding": "b1", "node": CALL, "field": "/path"}
    ]
    assert listed == []


MALFORMED: list[Callable[[dict], None]] = [
    lambda d: d.update(graph=None),
    lambda d: d.update(bindings=[None]),
    lambda d: d.update(format="other"),
    lambda d: d.update(format_version=2),
    lambda d: d.update(extra=1),
    lambda d: d["bindings"][0].update(id="B 1"),
    lambda d: d["bindings"][0].update(sites=[]),
    lambda d: d["bindings"][0]["sites"][0].update(node=7),
    lambda d: d["bindings"][0].update(kind="secret"),
]


@pytest.mark.parametrize("change", MALFORMED)
async def test_a_malformed_file_is_refused_and_nothing_is_created(
    app, owner_sessionmaker, api_settings, change
) -> None:
    doc = await exported(app, owner_sessionmaker, api_settings)
    change(doc)
    r, listed = await imported(app, owner_sessionmaker, api_settings, doc)
    assert r.status_code == 422 and r.json()["error"] == "invalid", r.text
    assert listed == []


async def test_a_draft_that_cant_be_made_portable_isnt_exported(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    odd = str(uuid.uuid4())
    unknown = draft(str(uuid.uuid4()), str(uuid.uuid4()))
    unknown["nodes"].append({"id": odd, "key": "odd", "type": "vendor.unknown@1", "config": {"account": str(uuid.uuid4())}})
    async with c:
        a = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Odd", "draft": unknown})).json()
        b = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "Cel", "draft": draft(cel("vars.c"), str(uuid.uuid4()))})).json()
        first = await c.get(f"/api/v1/t/{tid}/workflows/{a['id']}/export")
        second = await c.get(f"/api/v1/t/{tid}/workflows/{b['id']}/export")
    assert (first.status_code, first.json()) == (
        422, {"error": "not_portable", "problems": [{"reason": "unknown_type", "binding": None, "node": odd, "field": None}]},
    )  # fmt: skip
    assert (second.status_code, second.json()) == (
        422,
        {"error": "not_portable", "problems": [{"reason": "unexpected_value", "binding": None, "node": CALL, "field": "/connection"}]},
    )  # fmt: skip


async def test_viewers_export_and_only_editors_import(app, owner_sessionmaker, api_settings) -> None:
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        wf = (await c.post(f"/api/v1/t/{tid}/workflows", json={"name": "W"})).json()
    viewer, _ = await member_client(app, owner_sessionmaker, api_settings, tid, "viewer")
    async with viewer:
        doc = await viewer.get(f"/api/v1/t/{tid}/workflows/{wf['id']}/export")
        assert doc.status_code == 200
        r = await viewer.post(f"/api/v1/t/{tid}/workflows/import", json={"name": "X", "document": doc.json()})
        assert r.status_code == 403
```

In `backend/tests/apps/api/test_openapi.py`, `SLICE_4B` gains
`("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/export")` and `("post", "/api/v1/t/{tenant_id}/workflows/import")`,
and:

```python
def test_a_files_graph_is_documented_as_a_graph() -> None:
    assert schema()["components"]["schemas"]["WorkflowDocument"]["properties"]["graph"] == GRAPH
```

- [ ] **Step 6: Run them to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_workflow_portable.py tests/apps/api/test_openapi.py`
Expected: FAIL: the export route answers 404 or 405, the import route 405 or 422, `KeyError: 'WorkflowDocument'`.

- [ ] **Step 7: Implement the models, the audit source and the routes**

In `backend/src/dewpoint/apps/api/responses.py`, after `VersionDetailOut` (the same models describe the export's answer
and the import's file; `_Answer` refuses extra keys either way):

```python
BINDING_ID = r"^[a-z][a-z0-9_]{0,31}$"
# Far above anything an export makes (500 steps, a config's top-level properties), and a bound on an import's work
# beside the 1 MiB body cap.
MAX_BINDINGS = 10_000


class BindingSite(_Answer):
    node: str | None = Field(max_length=64)  # a step's id; null for the workflow's settings
    field: str = Field(min_length=2, max_length=200)  # `/<property>`, or `/settings/failure_handler`


class Binding(_Answer):
    """One id of the exporting tenant's (a connection, a workflow), as a placeholder an import binds or leaves."""

    id: str = Field(pattern=BINDING_ID)
    kind: Literal["connection", "workflow"]
    type: str | None = Field(max_length=100)  # the connection type it takes; null for a workflow
    label: str = Field(max_length=200)
    sites: list[BindingSite] = Field(min_length=1, max_length=MAX_BINDINGS)


class WorkflowDocument(_Answer):
    """A workflow as a file (B12): its graph without the tenant's ids (documented as a Graph), and their bindings."""

    format: Literal["dewpoint.workflow"]
    format_version: Literal[1]
    name: str = Field(max_length=100)
    graph: dict[str, Any]
    bindings: list[Binding] = Field(max_length=MAX_BINDINGS)
```

(`Field` joins the pydantic import.) In `backend/src/dewpoint/core/workflows/service.py`, `create_workflow` records
where a workflow came from when it wasn't typed in:

```python
async def create_workflow(
    s: AsyncSession, ctx: TenantContext, *, name: str, draft: dict[str, Any], source: str | None = None
) -> Workflow:
```

and its audit call's details become `{"name": name, **({"source": source} if source else {})}`.

In `backend/src/dewpoint/apps/api/routes/workflows.py`, import `portable` (`from dewpoint.core.workflows import
portable, service`), `registry` (`from dewpoint.core.plugins import registry`), the `Connection` model, `select`,
`ConfigDict`, `WorkflowDocument`, and add:

```python
class WorkflowImportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a misspelt `bind` must never import with every binding left open
    name: str = Field(min_length=1, max_length=100)
    document: WorkflowDocument
    bind: dict[str, uuid.UUID] = Field(default_factory=dict)  # binding id -> one of this tenant's; absent: unbound


def _bad_binding(binding: str, reason: str) -> HTTPException:
    return HTTPException(422, detail={"error": "bad_binding", "binding": binding, "reason": reason})


async def _config_schemas(db: AsyncSession, graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The config schema of each step type the graph names that this server knows, in any state: a retired type's
    schema still says where its ids are. Called on a graph whose format is checked (each type a valid ref)."""
    refs = {n["type"] for n in graph.get("nodes") or [] if isinstance(n, dict) and isinstance(n.get("type"), str)}
    return {row.ref: row.manifest.get("config_schema") or {} for row in await registry.load_node_types(db, refs)}


async def _labels(db: AsyncSession, tenant_id: uuid.UUID, found: list[tuple[portable.Site, str]]) -> dict[tuple[str, str], str]:
    """Each (kind, canonical id) the draft holds, to its name in this tenant; an id it doesn't name gets none."""
    wanted: dict[str, set[uuid.UUID]] = {"connection": set(), "workflow": set()}
    for site, value in found:
        wanted[site.kind].add(uuid.UUID(value))
    labels: dict[tuple[str, str], str] = {}
    for model, kind in ((Connection, "connection"), (Workflow, "workflow")):
        if wanted[kind]:
            rows = await db.execute(
                select(model.id, model.name).where(model.tenant_id == tenant_id, model.id.in_(sorted(wanted[kind], key=str)))
            )
            labels.update({(kind, str(row.id)): row.name for row in rows})
    return labels


def _not_portable(e: portable.NotPortableError) -> HTTPException:
    return HTTPException(422, detail={"error": "not_portable", "problems": [p.to_json() for p in e.problems]})


@router.get("/t/{tenant_id}/workflows/{workflow_id}/export", response_model=WorkflowDocument)
async def export(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """The saved draft as a file, every id of this tenant's replaced by a typed placeholder (B12). Refused, never
    approximated, when that can't be done for certain (4b ruling 18)."""
    wf = await _get(db, ctx, workflow_id)
    schemas = await _config_schemas(db, wf.draft)
    try:
        labels = await _labels(db, ctx.tenant_id, portable.held(wf.draft, schemas))
        return portable.export_document(wf.name, wf.draft, schemas, labels)
    except portable.NotPortableError as e:
        raise _not_portable(e) from None


@router.post("/t/{tenant_id}/workflows/import", status_code=201, response_model=WorkflowDetailOut)
async def import_workflow(
    body: WorkflowImportIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A new workflow from a file (B12), checked whole before anything is written (4b ruling 18): the graph's format;
    each step's type and each binding's sites against this server's schemas, with no id embedded where a binding goes;
    then each chosen id against this tenant's own connections (of the binding's type) and workflows."""
    graph = body.document.graph
    _check_format(graph)
    schemas = await _config_schemas(db, graph)
    bindings = [b.model_dump() for b in body.document.bindings]
    problems = portable.check_document(graph, bindings, schemas)
    if problems:
        raise HTTPException(422, detail={"error": "bad_document", "problems": [p.to_json() for p in problems]})
    by_id = {b.id: b for b in body.document.bindings}
    for key, chosen in body.bind.items():
        binding = by_id.get(key)
        if binding is None:
            raise _bad_binding(key, "unexpected")
        if binding.kind == "connection":
            found = (
                await db.execute(
                    select(Connection.type).where(Connection.tenant_id == ctx.tenant_id, Connection.id == chosen)
                )
            ).scalar_one_or_none()
            if found is None:
                raise _bad_binding(key, "unknown")
            if found != binding.type:
                raise _bad_binding(key, "wrong_type")
        elif (
            await db.execute(select(Workflow.id).where(Workflow.tenant_id == ctx.tenant_id, Workflow.id == chosen))
        ).scalar_one_or_none() is None:
            raise _bad_binding(key, "unknown")
    draft = portable.apply(graph, bindings, {key: str(value) for key, value in body.bind.items()}, schemas)
    _check_format(draft)
    try:
        wf = await service.create_workflow(db, ctx, name=body.name, draft=draft, source="import")
    except IntegrityError:
        raise HTTPException(409, detail={"error": "name_taken"}) from None
    return {**await _summary(db, wf), "draft": wf.draft}
```

In `backend/src/dewpoint/apps/api/openapi.py`:

```python
GRAPH_PROPERTIES: tuple[tuple[str, str], ...] = (
    ("WorkflowDetailOut", "draft"),
    ("VersionDetailOut", "graph"),
    ("WorkflowDocument", "graph"),
)
```

The import route's path is `/t/{tenant_id}/workflows/import` with POST; no POST route takes `/workflows/{workflow_id}`
without a further segment, so it can't be shadowed. `registry` and `Connection` reach `apps.api` already through other
routes; `uv run lint-imports` confirms.

- [ ] **Step 8: Run the tests to see them pass, then the workflow suites and the static checks**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/core/workflows tests/apps/api/test_workflow_portable.py tests/apps/api/test_openapi.py tests/apps/api/test_workflows.py && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports`
Expected: PASS and clean.

- [ ] **Step 9: Regenerate the client's schema and check it.** Expected: `WorkflowDocument`, `Binding`,
  `BindingSite` and `WorkflowImportIn` appear; `WorkflowDocument["graph"]` is a `Graph`; `Binding.id` carries its
  pattern.

- [ ] **Step 10: Commit**

```bash
git add backend/src/dewpoint/core/workflows backend/src/dewpoint/apps/api backend/tests/core/workflows/test_portable.py \
  backend/tests/apps/api/test_workflow_portable.py backend/tests/apps/api/test_openapi.py frontend/src/api
git commit -m "feat(api): a workflow exports with typed placeholders and imports with each re-bound, both fail-closed (B12, 4b)"
```

**Milestone 1's check, then the owner's pause.** Run `cd backend && uv run pytest -q -n 12 -p no:cacheprovider
tests/apps/api tests/apps/test_workflow_ops.py tests/apps/test_workflow_summary.py tests/core/workflows
tests/apps/test_admission.py`, then the static checks; all pass. Then stop for the owner's review with: the API
contracts as they stand (the regenerated `openapi.json`'s diff for milestone 1, and the refusals each route answers),
the statement-count test's result, and the probe's evidence from Task 3, Step 9 (the plans and timings at each size,
with and without the candidate index, and the hashing costs, with the machine). Ruling 5 is decided there: accept the
list without an index on the measured numbers, or assign a migration slot for the index and its LATERAL read (planned
then, as an addendum to this plan). Milestone 2 waits for the owner's word.

## Milestone 2 — The list and the chooser

### Task 6: Three packages, Workflows in the rail as a tenant's landing, and the palette's workflows

**Files:**
- Modify: `frontend/package.json`, `frontend/pnpm-lock.yaml` (three packages, exact versions)
- Create: `frontend/src/lib/workflows.ts`, `frontend/src/lib/workflows.test.ts`
- Create: `frontend/src/lib/announce.ts`, `frontend/src/components/Announcer.tsx`, `frontend/src/components/Announcer.test.tsx`
- Create: `frontend/src/routes/Workflows.tsx` (the list's first cut: heading, rows, states)
- Create: `frontend/src/routes/editor/Editor.tsx` (the editor's first cut: loads the workflow and its types)
- Modify: `frontend/src/router.tsx`, `frontend/src/components/Shell.tsx`, `frontend/src/components/TenantSwitcher.tsx`,
  `frontend/src/components/CommandPalette.tsx`
- Modify: `frontend/src/router.test.tsx`, `frontend/src/components/Shell.test.tsx`,
  `frontend/src/components/CommandPalette.test.tsx`

**Interfaces:**
- Consumes: the schema's `WorkflowOut`, `WorkflowDetailOut`, `Graph`, `GraphNode`, `Edge`, `NodeTypeOut`,
  `DiagnosticOut`, `ValidationOut`, `ExpressionOut`, `VersionOut`, `VersionDetailOut`, `WorkflowDocument` (Tasks 1–5).
- Produces (`src/lib/workflows.ts`): the types `WorkflowRow`, `WorkflowDetail`, `GraphDoc`, `GraphNode`, `GraphEdge`,
  `NodeType`, `Diagnostic`, `Validation`, `Expression`, `VersionRow`, `VersionDetail`, `WorkflowDocument`; query
  options `workflowsQuery(tenantId)`, `workflowQuery(tenantId, workflowId)`, `nodeTypesQuery`,
  `versionsQuery(tenantId, workflowId)`, `tenantQuery(tenantId)` (the key `["tenant", id]` Members already uses);
  `canEdit(role)`, `canPublish(role)`; `since(iso, now)`. (`src/lib/announce.ts`): `announce(message)`,
  `onAnnounce(listener) -> unsubscribe`; `<Announcer />`, mounted once in the shell. Routes `/t/$tenantId` (→
  workflows), `/t/$tenantId/workflows` (search `{ new?: true }`), `/t/$tenantId/workflows/$workflowId` (static data
  `compactRail: true`).

- [ ] **Step 1: Install the three packages, at their recorded versions, and check their licences**

```bash
cd frontend
npx -y pnpm@12.6.0 add @xyflow/react@12.12.0 @dagrejs/dagre@3.1.1 @radix-ui/react-switch@1.3.7
node scripts/licence-check.mjs --self-test
npx -y pnpm@12.6.0 licenses list --json --prod | node scripts/licence-check.mjs prod
npx -y pnpm@12.6.0 licenses list --json | node scripts/licence-check.mjs all
```

Expected: `package.json` lists the three exactly (pnpm 12 saves exact versions, ledger ruling 13); both licence runs
end "within D22's list", the only notes the five approved exceptions and `type-fest → MIT`. A licence outside the
lists is the owner's to review: stop and report it, and add no exception (owner, 2026-10-05).

- [ ] **Step 2: Write the failing tests**

`frontend/src/lib/workflows.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { canEdit, canPublish, since } from "./workflows";

it("lets editors and above edit and publish, as the API's role sets do", () => {
  for (const role of ["owner", "admin", "editor"]) expect([canEdit(role), canPublish(role)]).toEqual([true, true]);
  for (const role of ["operator", "viewer", null, undefined]) expect([canEdit(role), canPublish(role)]).toEqual([false, false]);
});

it("says how long ago, in words, then as a date", () => {
  const now = Date.parse("2026-10-06T12:00:00Z");
  expect(since("2026-10-06T11:59:40Z", now)).toBe("just now");
  expect(since("2026-10-06T11:48:00Z", now)).toBe("12 min ago");
  expect(since("2026-10-06T09:00:00Z", now)).toBe("3 h ago");
  expect(since("2026-10-05T09:00:00Z", now)).toBe("yesterday");
  expect(since("2026-09-30T09:00:00Z", now)).toMatch(/30 Sept?/);
});
```

`frontend/src/components/Announcer.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { announce } from "../lib/announce";
import { Announcer } from "./Announcer";

it("says each change politely, even the same words twice", () => {
  vi.useFakeTimers();
  render(<Announcer />);
  const region = screen.getByRole("status");
  expect(region.getAttribute("aria-live")).toBe("polite");
  act(() => announce("Added transform after get_device"));
  act(() => vi.advanceTimersByTime(50));
  expect(region.textContent).toBe("Added transform after get_device");
  act(() => announce("Added transform after get_device"));
  expect(region.textContent).toBe(""); // cleared first, so a screen reader hears it again
  act(() => vi.advanceTimersByTime(50));
  expect(region.textContent).toBe("Added transform after get_device");
  vi.useRealTimers();
});
```

In `frontend/src/router.test.tsx`, the fetch mock also answers the workflow list and the node types (add before the
tenant lookup):

```ts
    if (/^GET \/api\/v1\/t\/t[12]\/workflows$/.test(key)) return json([]);
    if (key === "GET /api/v1/node-types") return json([]);
```

and a test:

```tsx
it("opens a tenant on its workflows", async () => {
  const router = showApp("/t/t1");
  expect(await screen.findByRole("heading", { level: 1, name: "Workflows" })).toBeTruthy();
  expect(router.state.location.pathname).toBe("/t/t1/workflows");
});
```

In `frontend/src/components/Shell.test.tsx`, `renderAt`'s routes add `"/t/$tenantId/workflows"`, and:

```tsx
it("offers Workflows first on the rail, current on its pages", async () => {
  await renderAt("/t/t1/workflows");
  const links = screen.getAllByRole("link").filter((l) => l.closest("nav"));
  expect(links.map((l) => l.textContent)).toEqual(["Workflows", "Connections", "Settings"]);
  expect(screen.getByRole("link", { name: "Workflows" }).getAttribute("aria-current")).toBe("page");
});

it("keeps the editor's rail to icons at every width (outline §2)", async () => {
  const root = createRootRoute({ component: Shell });
  const editor = createRoute({
    getParentRoute: () => root,
    path: "/t/$tenantId/workflows/$workflowId",
    component: () => <p>page</p>,
    staticData: { compactRail: true },
  });
  const router = createRouter({ routeTree: root.addChildren([editor]), history: createMemoryHistory({ initialEntries: ["/t/t1/workflows/w1"] }) });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByText("page");
  const label = screen.getByRole("link", { name: "Workflows" }).querySelector("span")!;
  expect(label.className).toMatch(/(?:^|\s)sr-only(?:\s|$)/);
  expect(label.className).not.toMatch(/lg:not-sr-only/);
});
```

In `frontend/src/components/CommandPalette.test.tsx`, `renderAt` gains the routes
`createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows", component: page("workflows page"), validateSearch: (s: Record<string, unknown>) => (s.new === true || s.new === "true" ? { new: true } : {}) })`
and `createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId", component: page("editor page") })`,
and:

```tsx
it("lists the tenant's workflows, opens one, and starts a new one", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    const body = path === "/api/v1/t/t1/workflows" ? [{ id: "w1", name: "Nightly report" }] : TENANTS;
    return Promise.resolve(new Response(JSON.stringify(body)));
  });
  const router = await renderAt("/t/t1/connections");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await userEvent.click(await screen.findByRole("option", { name: "Nightly report" }));
  expect(router.state.location.pathname).toBe("/t/t1/workflows/w1");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await userEvent.click(await screen.findByRole("option", { name: "New workflow" }));
  expect(router.state.location.pathname).toBe("/t/t1/workflows");
  expect(router.state.location.search).toEqual({ new: true });
});

it("opens a tenant on its workflows", async () => {
  const router = await renderAt("/account/security");
  fireEvent.keyDown(document, { key: "k", metaKey: true });
  await userEvent.click(await screen.findByRole("option", { name: /Acme Lab/ }));
  expect(router.state.location.pathname).toBe("/t/t2/workflows");
});
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib/workflows.test.ts src/components/Announcer.test.tsx src/router.test.tsx src/components/Shell.test.tsx src/components/CommandPalette.test.tsx`
Expected: FAIL: the two new modules don't exist; no Workflows link, route or palette entries; `/t/t1` matches no route.

- [ ] **Step 4: Implement the library**

`frontend/src/lib/workflows.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// The workflow API's shapes and queries (sub-project 4, slice 4b): types from the generated schema (B1), never
// written by hand.
import { queryOptions } from "@tanstack/react-query";
import { client, ok, type Schemas } from "./client";

export type WorkflowRow = Schemas["WorkflowOut"];
export type WorkflowDetail = Schemas["WorkflowDetailOut"];
export type GraphDoc = Schemas["Graph"];
export type GraphNode = Schemas["GraphNode"];
export type GraphEdge = Schemas["Edge"];
export type NodeType = Schemas["NodeTypeOut"];
export type Diagnostic = Schemas["DiagnosticOut"];
export type Validation = Schemas["ValidationOut"];
export type Expression = Schemas["ExpressionOut"];
export type VersionRow = Schemas["VersionOut"];
export type VersionDetail = Schemas["VersionDetailOut"];
export type WorkflowDocument = Schemas["WorkflowDocument"];

const tenantPath = (tenantId: string) => ({ params: { path: { tenant_id: tenantId } } });
const workflowPath = (tenantId: string, workflowId: string) => ({
  params: { path: { tenant_id: tenantId, workflow_id: workflowId } },
});

export const workflowsQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["workflows", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/workflows", tenantPath(tenantId))),
  });

export const workflowQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["workflow", tenantId, workflowId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}", workflowPath(tenantId, workflowId))),
    // No staleTime: the editor reads it afresh on every entry and seeds itself once (Task 13, 4b ruling 23).
  });

export const versionsQuery = (tenantId: string, workflowId: string) =>
  queryOptions({
    queryKey: ["versions", tenantId, workflowId],
    queryFn: () =>
      ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions", workflowPath(tenantId, workflowId))),
  });

export const nodeTypesQuery = queryOptions({
  queryKey: ["node-types"],
  queryFn: () => ok(client.GET("/api/v1/node-types")),
  staleTime: 5 * 60_000,
});

export const tenantQuery = (tenantId: string) =>
  queryOptions({
    queryKey: ["tenant", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}", tenantPath(tenantId))),
  });

// The roles that hold workflow.edit and workflow.publish (backend/src/dewpoint/core/authz/permissions.py: editor and
// above). The UI only hides what the API would refuse: the API decides every write.
const EDITORS = new Set(["owner", "admin", "editor"]);
export const canEdit = (role?: string | null) => !!role && EDITORS.has(role);
export const canPublish = (role?: string | null) => !!role && EDITORS.has(role);

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short" });

/** How long ago `iso` was, in words, then as a date. */
export function since(iso: string, now: number = Date.now()): string {
  const minutes = Math.floor((now - Date.parse(iso)) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 24 * 60) return `${Math.floor(minutes / 60)} h ago`;
  if (minutes < 48 * 60) return "yesterday";
  return DATE.format(new Date(iso));
}
```

`frontend/src/lib/announce.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// What changed, said to assistive technology through the shell's one polite live region (D16).
type Listener = (message: string) => void;
const listeners = new Set<Listener>();

export function announce(message: string): void {
  for (const listener of listeners) listener(message);
}

export function onAnnounce(listener: Listener): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}
```

`frontend/src/components/Announcer.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { useEffect, useState } from "react";
import { onAnnounce } from "../lib/announce";

/** The shell's polite live region. It empties before each message, so the same words twice are heard twice. */
export function Announcer() {
  const [message, setMessage] = useState("");
  useEffect(
    () =>
      onAnnounce((m) => {
        setMessage("");
        window.setTimeout(() => setMessage(m), 30);
      }),
    [],
  );
  return (
    <div role="status" aria-live="polite" className="sr-only">
      {message}
    </div>
  );
}
```

- [ ] **Step 5: Implement the routes, the rail and the palette**

`frontend/src/routes/Workflows.tsx` (Task 7 completes it):

```tsx
// SPDX-License-Identifier: Apache-2.0
// The workflows list (screen 1a). Task 7 adds the filters, the enable switch and the row menu.
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { LoadError } from "../components/LoadError";
import { Table, Td, Th } from "../components/Table";
import { useDocumentTitle } from "../lib/title";
import { workflowsQuery } from "../lib/workflows";

export function WorkflowsPage({ tenantId }: { tenantId: string; startNew?: boolean }) {
  useDocumentTitle("Workflows");
  const list = useQuery(workflowsQuery(tenantId));
  return (
    <section className="flex flex-col gap-4 p-6">
      <h1 className="text-h1 font-semibold">Workflows</h1>
      {list.isError ? (
        <LoadError what="The workflows" />
      ) : (
        <Table label="Workflows">
          <thead>
            <tr><Th>Name</Th></tr>
          </thead>
          <tbody>
            {list.data?.map((w) => (
              <tr key={w.id}>
                <Td>
                  <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: w.id }} className="font-medium text-accent-ink">
                    {w.name}
                  </Link>
                </Td>
              </tr>
            ))}
            {list.data?.length === 0 && (
              <tr><Td className="text-muted">No workflows yet.</Td></tr>
            )}
          </tbody>
        </Table>
      )}
    </section>
  );
}
```

`frontend/src/routes/editor/Editor.tsx` (Task 11 builds the canvas into it):

```tsx
// SPDX-License-Identifier: Apache-2.0
// The editor (screen 1c). Task 11 adds the canvas; Tasks 13-15 saving, problems and publishing.
import { useQuery } from "@tanstack/react-query";
import { LoadError } from "../../components/LoadError";
import { useDocumentTitle } from "../../lib/title";
import { nodeTypesQuery, workflowQuery } from "../../lib/workflows";

export function EditorPage({ tenantId, workflowId }: { tenantId: string; workflowId: string }) {
  const workflow = useQuery(workflowQuery(tenantId, workflowId));
  const types = useQuery(nodeTypesQuery);
  useDocumentTitle(workflow.data?.name ?? "Workflow");
  if (workflow.isError) return <section className="p-6"><LoadError what="This workflow" /></section>;
  if (types.isError) return <section className="p-6"><LoadError what="The step types" /></section>;
  if (!workflow.data || !types.data) return <p className="p-6 text-body text-muted">Loading…</p>;
  return (
    <section className="flex flex-col gap-4 p-6">
      <h1 className="text-h1 font-semibold">{workflow.data.name}</h1>
    </section>
  );
}
```

In `frontend/src/router.tsx`, declare the static data, add three routes (each tenant screen keyed by what it shows,
ledger ruling 60), and put them in the tree:

```tsx
import { Navigate, Outlet, createRootRoute, createRoute, createRouter, useParams } from "@tanstack/react-router";
import { EditorPage } from "./routes/editor/Editor";
import { WorkflowsPage } from "./routes/Workflows";

declare module "@tanstack/react-router" {
  interface StaticDataRouteOption {
    /** The editor's 60 px icon rail at every width (outline §2): the canvas needs the room. */
    compactRail?: boolean;
  }
}

function TenantHome() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId" });
  return <Navigate to="/t/$tenantId/workflows" params={{ tenantId }} />;
}

function Workflows() {
  const { tenantId } = useParams({ from: "/app/t/$tenantId/workflows" });
  const search = workflowsRoute.useSearch();
  return <WorkflowsPage key={tenantId} tenantId={tenantId} startNew={search.new === true} />;
}

function Editor() {
  const { tenantId, workflowId } = useParams({ from: "/app/t/$tenantId/workflows/$workflowId" });
  return <EditorPage key={`${tenantId}:${workflowId}`} tenantId={tenantId} workflowId={workflowId} />;
}

const tenantHomeRoute = createRoute({ getParentRoute: () => appRoute, path: "/t/$tenantId", component: TenantHome });
const workflowsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/t/$tenantId/workflows",
  component: Workflows,
  validateSearch: (search: Record<string, unknown>): { new?: true } =>
    search.new === true || search.new === "true" ? { new: true } : {},
});
const editorRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/t/$tenantId/workflows/$workflowId",
  component: Editor,
  staticData: { compactRail: true },
});
```

with `tenantHomeRoute, workflowsRoute, editorRoute` added to `appRoute.addChildren([...])` before `connectionsRoute`.

In `frontend/src/components/Shell.tsx`, mount the announcer, put Workflows first, and keep the rail to icons on a
compact route:

```tsx
import { Link, useMatches, useNavigate, useParams } from "@tanstack/react-router";
import { Announcer } from "./Announcer";
import { ConnectionsIcon, SettingsIcon, WorkflowsIcon } from "./icons";
```

```tsx
  const compact = useMatches({ select: (matches) => matches.some((m) => m.staticData?.compactRail === true) });
  const item = compact ? ITEM_COMPACT : ITEM;
  const label = compact ? "sr-only" : "sr-only lg:not-sr-only";
```

with, beside `ITEM`:

```tsx
// On a compact route (the editor) the rail stays the 60 px icon rail at every width; the current item's fill
// carries the mark there too (rail-current, ruling 53).
const ITEM_COMPACT = "flex items-center justify-center rounded-md px-2 py-2.5 text-body text-rail-ink";
const CURRENT_COMPACT = "bg-rail-current font-semibold text-rail-ink-strong";
```

The grid's columns become `` `grid min-h-screen grid-rows-[auto_1fr] ${compact ? "grid-cols-[var(--rail-w-collapsed)_minmax(0,1fr)]" : "grid-cols-[var(--rail-w-collapsed)_minmax(0,1fr)] lg:grid-cols-[var(--rail-w)_minmax(0,1fr)]"}` ``;
the rail's wordmark becomes `{compact ? <Mark /> : <Wordmark />}`; a Workflows link precedes Connections:

```tsx
          {params.tenantId && (
            <Link
              to="/t/$tenantId/workflows"
              params={{ tenantId: params.tenantId }}
              className={item}
              activeProps={{ className: compact ? CURRENT_COMPACT : CURRENT }}
              inactiveProps={{ className: INACTIVE }}
            >
              <WorkflowsIcon />
              <span className={label}>Workflows</span>
            </Link>
          )}
```

and Connections and Settings take `item`, `label` and the same `activeProps` choice. `<Announcer />` goes last
inside the shell's grid. Import `Mark` beside `Wordmark`.

In `frontend/src/components/TenantSwitcher.tsx`, a tenant opens on its workflows (4b ruling 19):

```tsx
              onSelect={() => void navigate({ to: "/t/$tenantId/workflows", params: { tenantId: t.id } })}
```

In `frontend/src/components/CommandPalette.tsx`, read the tenant's workflows while the palette is open, and list
them with "Workflows" and "New workflow":

```tsx
import { workflowsQuery } from "../lib/workflows";
```

```tsx
  const workflows = useQuery({ ...workflowsQuery(params.tenantId ?? ""), enabled: open && !!params.tenantId });
```

In the "Go to" group, before "Connections":

```tsx
                {params.tenantId && (
                  <Command.Item
                    value="Workflows"
                    className={ITEM}
                    onSelect={() => go(() => navigate({ to: "/t/$tenantId/workflows", params: { tenantId: params.tenantId! } }))}
                  >
                    Workflows
                  </Command.Item>
                )}
                {params.tenantId && (
                  <Command.Item
                    value="New workflow"
                    className={ITEM}
                    onSelect={() =>
                      go(() =>
                        navigate({ to: "/t/$tenantId/workflows", params: { tenantId: params.tenantId! }, search: { new: true } }),
                      )
                    }
                  >
                    New workflow
                  </Command.Item>
                )}
```

After the "Go to" group:

```tsx
              {params.tenantId && !!workflows.data?.length && (
                <Command.Group heading="Workflows" className={GROUP}>
                  {workflows.data.map((w) => (
                    <Command.Item
                      key={w.id}
                      value={w.name}
                      className={ITEM}
                      onSelect={() =>
                        go(() =>
                          navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId: params.tenantId!, workflowId: w.id } }),
                        )
                      }
                    >
                      {w.name}
                    </Command.Item>
                  ))}
                </Command.Group>
              )}
```

and each tenant item navigates to `/t/$tenantId/workflows`. The input's placeholder becomes "Type a page, a workflow
or a tenant".

- [ ] **Step 6: Run the tests to see them pass, then the suite, lint and types**

Run: `cd frontend && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean. (Connections' and Members' tests still pass: their routes are unchanged.)

- [ ] **Step 7: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src
git commit -m "feat(web): Workflows in the rail as a tenant's landing; the palette's workflows; three approved packages (4b)"
```

### Task 7: The workflows list (1a): state at a glance, filters, the enable switch, export

**Files:**
- Create: `frontend/src/components/Switch.tsx`, `frontend/src/components/Segmented.tsx`, `frontend/src/lib/download.ts`
- Modify: `frontend/src/routes/Workflows.tsx`, `frontend/src/lib/workflows.ts`, `frontend/src/lib/workflows.test.ts`
  (`notPortable`)
- Create: `frontend/src/routes/Workflows.test.tsx`, `frontend/src/components/Switch.test.tsx`,
  `frontend/src/components/Segmented.test.tsx`
- Modify: `frontend/src/styles/tokenNames.ts` only if a new colour pair renders (none expected: the switch uses
  `line-control` on `surface-2` and `on-accent` on `accent`, both in PAIRS)

**Interfaces:**
- Consumes: `WorkflowRow` (B3's `unpublished_changes`, `last_run` (live), `last_simulation`, `runs_24h`,
  `needs_attention`), `canPublish(role)`, `tenantQuery`, `since`, `announce`, `PATCH …/{workflow_id}` (`{enabled}`;
  `422 not_enableable` with diagnostics), `GET …/{workflow_id}/export` and its `422 not_portable` (Task 5).
- Produces: `<Switch checked onCheckedChange label disabled? />`, `<Segmented label options value onChange />`
  (`options: {value, label, count}[]`), `downloadJson(name, data)`, `fileName(name, suffix)`; in `lib/workflows.ts`,
  `type PortableProblem` and `notPortable(problems, keyOf?)` (Task 15 uses both). Task 8 adds the "New workflow"
  button and its dialog to this page.

The filters follow 4b rulings 4 and 6 as the owner amended them: "Unpublished changes" counts a workflow never
published (revision 1 left those out), and "Needs attention" follows live runs only (ruling 7, amended); a
workflow's last simulation shows apart, never as its last run.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/lib/workflows.test.ts`:

```ts
it("says why a workflow isn't portable, naming its steps when it can", () => {
  const problems = [
    { reason: "unknown_type", binding: null, node: "n1", field: null },
    { reason: "unexpected_value", binding: null, node: "n2", field: "/connection" },
    { reason: "unexpected_value", binding: null, node: null, field: "/settings/failure_handler" },
  ];
  expect(notPortable(problems)).toBe(
    "it has steps of a type this server doesn't know, and something other than an id where a connection or workflow goes",
  );
  expect(notPortable(problems, (id) => ({ n1: "odd", n2: "call" })[id] ?? id)).toBe(
    "it has steps of a type this server doesn't know (odd), and something other than an id where a connection or workflow goes (call, the failure handler)",
  );
});
```

(`notPortable` joins the test's import.)

`frontend/src/components/Switch.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Switch } from "./Switch";

it("is a named switch that says its state, and toggles from the keyboard", async () => {
  const onCheckedChange = vi.fn();
  render(<Switch checked={false} onCheckedChange={onCheckedChange} label="Enable Nightly" />);
  const toggle = screen.getByRole("switch", { name: "Enable Nightly" });
  expect(toggle.getAttribute("aria-checked")).toBe("false");
  toggle.focus();
  await userEvent.keyboard(" ");
  expect(onCheckedChange).toHaveBeenCalledWith(true);
});

it("is a rounded rectangle, not a pill (outline §6)", () => {
  render(<Switch checked onCheckedChange={vi.fn()} label="Enable" />);
  expect(screen.getByRole("switch").className).not.toMatch(/rounded-full/);
});
```

`frontend/src/components/Segmented.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Segmented } from "./Segmented";

it("is a named group of buttons, the chosen one pressed, each with its count", async () => {
  const onChange = vi.fn();
  render(
    <Segmented
      label="Show"
      value="all"
      onChange={onChange}
      options={[{ value: "all", label: "All", count: 6 }, { value: "attention", label: "Needs attention", count: 1 }]}
    />,
  );
  expect(screen.getByRole("group", { name: "Show" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "All 6" }).getAttribute("aria-pressed")).toBe("true");
  await userEvent.click(screen.getByRole("button", { name: "Needs attention 1" }));
  expect(onChange).toHaveBeenCalledWith("attention");
});
```

`frontend/src/routes/Workflows.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { WorkflowsPage } from "./Workflows";

const NOW = Date.parse("2026-10-06T12:00:00Z");
const row = (over: Record<string, unknown>) => ({
  id: "w1", name: "Nightly", enabled: true, draft_revision: 3, active_version_id: "v2", active_version_number: 2,
  executable: true, blocked_by: [], created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-06T10:00:00Z",
  unpublished_changes: false, last_run: { status: "succeeded", at: "2026-10-06T11:48:00Z" }, last_simulation: null,
  runs_24h: { live: 4, simulate: 0 }, needs_attention: [], ...over,
});  // prettier-ignore
const ROWS = [
  row({}),
  row({ id: "w2", name: "Triage", enabled: false, unpublished_changes: true, runs_24h: { live: 1, simulate: 2 },
        last_run: { status: "failed", at: "2026-10-06T11:00:00Z" }, last_simulation: { status: "succeeded", at: "2026-10-06T11:30:00Z" },
        needs_attention: ["last_run_failed"] }),
  row({ id: "w3", name: "Sketch", active_version_id: null, active_version_number: null, executable: null,
        unpublished_changes: true, last_run: null, runs_24h: { live: 0, simulate: 0 } }),
];  // prettier-ignore

let role = "editor";
let sent: { method: string; path: string; body: unknown }[];
let patchAnswer: Response | null;
let exportAnswer: Response | null;

beforeEach(() => {
  role = "editor";
  sent = [];
  patchAnswer = null;
  exportAnswer = null;
  vi.spyOn(Date, "now").mockReturnValue(NOW);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
    if (request.method === "PATCH") return patchAnswer ?? new Response(JSON.stringify({ ...ROWS[0], enabled: false, warnings: [] }));
    if (path === "/api/v1/t/t1") return new Response(JSON.stringify({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }));
    if (path === "/api/v1/t/t1/workflows/w2/export") return exportAnswer ?? new Response(JSON.stringify({ format: "dewpoint.workflow", format_version: 1, name: "Triage", graph: {}, bindings: [] }));
    return new Response(JSON.stringify(ROWS));
  });
});

async function show() {
  const root = createRootRoute({ component: () => <WorkflowsPage tenantId="t1" /> });
  const editor = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId", component: () => <p>editor</p> });
  const router = createRouter({ routeTree: root.addChildren([editor]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("link", { name: "Nightly" });
  return router;
}

const rowOf = (name: string) => screen.getByRole("link", { name }).closest("tr")!;

it("shows each workflow's version, last run and last 24 hours in words", async () => {
  await show();
  expect(rowOf("Nightly").textContent).toContain("v2");
  expect(rowOf("Nightly").textContent).toContain("Succeeded · 12 min ago");
  expect(rowOf("Triage").textContent).toContain("v2 · unpublished changes");
  expect(rowOf("Triage").textContent).toContain("Failed · 1 h ago");
  expect(rowOf("Triage").textContent).toContain("Simulated: Succeeded · 30 min ago"); // apart, never the last run
  expect(rowOf("Triage").textContent).toContain("1 +2 simulated");
  expect(rowOf("Sketch").textContent).toContain("Not published");
  expect(rowOf("Sketch").textContent).toContain("No runs yet");
});

it("filters by state, with counts, and by name", async () => {
  await show();
  const filters = screen.getByRole("group", { name: "Show" });
  expect(within(filters).getAllByRole("button").map((b) => b.textContent)).toEqual([
    "All 3", "Published 2", "Unpublished changes 2", "Needs attention 1",
  ]);  // prettier-ignore
  await userEvent.click(within(filters).getByRole("button", { name: "Unpublished changes 2" }));
  expect(screen.getAllByRole("link").map((l) => l.textContent)).toEqual(["Triage", "Sketch"]); // never published counts
  await userEvent.click(within(filters).getByRole("button", { name: "Needs attention 1" }));
  expect(screen.queryByRole("link", { name: "Nightly" })).toBeNull();
  expect(screen.getByRole("link", { name: "Triage" })).toBeTruthy();
  await userEvent.click(within(filters).getByRole("button", { name: "All 3" }));
  await userEvent.type(screen.getByLabelText("Filter by name"), "sk");
  expect(screen.getAllByRole("link").map((l) => l.textContent)).toEqual(["Sketch"]);
});

it("lets a publisher switch a workflow off, and says why one can't be switched on", async () => {
  await show();
  await userEvent.click(await within(rowOf("Nightly")).findByRole("switch", { name: "Enable Nightly" }));
  expect(sent.find((r) => r.method === "PATCH")).toEqual({ method: "PATCH", path: "/api/v1/t/t1/workflows/w1", body: { enabled: false } });
  patchAnswer = new Response(
    JSON.stringify({ error: "not_enableable", diagnostics: [{ code: "lifecycle.retired", message: "testkit.echo@1 is retired.", node: null, field: null, fix: null, severity: "error" }] }),
    { status: 422 },
  );  // prettier-ignore
  await userEvent.click(within(rowOf("Triage")).getByRole("switch", { name: "Enable Triage" }));
  expect(sent.filter((r) => r.method === "PATCH").at(-1)?.body).toEqual({ enabled: true });
  expect((await screen.findByRole("alert")).textContent).toContain("Triage can't be switched on: testkit.echo@1 is retired.");
});

it("shows a viewer the state, not the switch", async () => {
  role = "viewer";
  await show();
  await vi.waitFor(() => expect(sent.some((r) => r.path === "/api/v1/t/t1")).toBe(true)); // the role is known
  await vi.waitFor(() => expect(rowOf("Nightly").textContent).toContain("On"));
  expect(within(rowOf("Nightly")).queryByRole("switch")).toBeNull();
});

it("exports a workflow as a file named after it", async () => {
  const createObjectURL = vi.fn(() => "blob:test");
  Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  await show();
  await userEvent.click(within(rowOf("Triage")).getByRole("button", { name: "Actions for Triage" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Export" }));
  await vi.waitFor(() => expect(click).toHaveBeenCalled());
  expect((click.mock.instances[0] as unknown as HTMLAnchorElement).download).toBe("triage.dewpoint.json");
});

it("says why a workflow can't be exported as a portable file", async () => {
  exportAnswer = new Response(
    JSON.stringify({ error: "not_portable", problems: [{ reason: "unknown_type", binding: null, node: "n1", field: null }] }),
    { status: 422 },
  );  // prettier-ignore
  await show();
  await userEvent.click(within(rowOf("Triage")).getByRole("button", { name: "Actions for Triage" }));
  await userEvent.click(await screen.findByRole("menuitem", { name: "Export" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Triage can't be exported as a portable file: it has steps of a type this server doesn't know. Open it to download the draft as it is.",
  );
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/components/Switch.test.tsx src/components/Segmented.test.tsx src/routes/Workflows.test.tsx`
Expected: FAIL: the components don't exist; the list has none of these columns, filters, switch or menu.

- [ ] **Step 3: Implement the components**

`frontend/src/components/Switch.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import * as SwitchPrimitive from "@radix-ui/react-switch";

/** An on/off control (Radix: role switch, Space toggles). A rounded rectangle, not a pill (outline §6): its track's
 * edge is 3:1 off the surface (line-control), its thumb 3:1 off the track in both states (PAIRS). */
export function Switch({
  checked,
  onCheckedChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <SwitchPrimitive.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={label}
      className="inline-flex h-5 w-9 shrink-0 items-center rounded-md border border-line-control bg-surface-2 p-0.5 data-[state=checked]:border-accent data-[state=checked]:bg-accent disabled:cursor-not-allowed"
    >
      <SwitchPrimitive.Thumb className="block size-3.5 rounded-sm bg-line-control transition-transform duration-100 motion-reduce:transition-none data-[state=checked]:translate-x-4 data-[state=checked]:bg-on-accent" />
    </SwitchPrimitive.Root>
  );
}
```

`frontend/src/components/Segmented.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0

/** A choice among a few views, each with its count: buttons in a named group, the chosen one pressed (1a's filter
 * chips, as a segmented control: no pills, outline §6). */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: T; label: string; count: number }[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap overflow-hidden rounded-lg border border-line-strong">
      {options.map((o, i) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={`min-h-9 px-3 text-small ${i > 0 ? "border-l border-line-strong" : ""} ${
            o.value === value ? "bg-accent-soft font-semibold text-accent-ink" : "bg-surface text-ink hover:bg-surface-hover"
          }`}
        >
          {o.label} <span className="font-mono text-meta">{o.count}</span>
        </button>
      ))}
    </div>
  );
}
```

`frontend/src/lib/download.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0

/** A file name from a workflow's name: lowercase words joined by dashes, then `suffix`. */
export function fileName(name: string, suffix: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
  return `${slug || "workflow"}${suffix}`;
}

/** Hands the person a JSON file, saved by the browser: the data never goes into a URL (a blob's URL names it). */
export function downloadJson(name: string, data: unknown): void {
  const url = URL.createObjectURL(new Blob([`${JSON.stringify(data, null, 2)}\n`], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
```

In `frontend/src/lib/workflows.ts`:

```ts
/** One reason an export refused (B12; 4b ruling 18), as the API answers it. */
export type PortableProblem = { reason: string; binding: string | null; node: string | null; field: string | null };

/** Why a workflow can't be exported as a portable file, as a clause ("it has …"): its steps named when `keyOf`
 * knows them (the editor), not on the list, which holds no graph. */
export function notPortable(problems: PortableProblem[], keyOf?: (nodeId: string) => string): string {
  const names = (reason: string) =>
    problems.filter((p) => p.reason === reason).map((p) => (p.node === null ? "the failure handler" : keyOf ? keyOf(p.node) : p.node));
  const clause = (text: string, reason: string) => {
    const found = names(reason);
    return found.length === 0 ? null : keyOf ? `${text} (${found.join(", ")})` : text;
  };
  const why = [
    clause("steps of a type this server doesn't know", "unknown_type"),
    clause("something other than an id where a connection or workflow goes", "unexpected_value"),
    clause("two steps sharing an id", "duplicate_node"),
  ].filter((c): c is string => c !== null);
  return `it has ${why.join(", and ")}`;
}
```

- [ ] **Step 4: Implement the list**

Replace `frontend/src/routes/Workflows.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The workflows list (screen 1a; 4b rulings 4-7): each workflow's state at a glance, filters, the enable switch for
// publishers, and export. No delete: no route deletes a workflow.
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { LoadError } from "../components/LoadError";
import { Segmented } from "../components/Segmented";
import { Switch } from "../components/Switch";
import { Table, Td, Th } from "../components/Table";
import { announce } from "../lib/announce";
import { ApiError, client, ok } from "../lib/client";
import { downloadJson, fileName } from "../lib/download";
import { useDocumentTitle } from "../lib/title";
import { canPublish, notPortable, since, tenantQuery, workflowsQuery, type PortableProblem, type WorkflowRow } from "../lib/workflows";

type Filter = "all" | "published" | "unpublished" | "attention";

// Never published counts as unpublished changes (4b ruling 6): the server says so in `unpublished_changes`.
const FILTERS: { value: Filter; label: string; keep: (w: WorkflowRow) => boolean }[] = [
  { value: "all", label: "All", keep: () => true },
  { value: "published", label: "Published", keep: (w) => w.active_version_id !== null },
  { value: "unpublished", label: "Unpublished changes", keep: (w) => w.unpublished_changes },
  { value: "attention", label: "Needs attention", keep: (w) => w.needs_attention.length > 0 },
];

const STATUS: Record<NonNullable<WorkflowRow["last_run"]>["status"], { text: string; dot: string }> = {
  running: { text: "Running", dot: "bg-accent" },
  succeeded: { text: "Succeeded", dot: "bg-ok" },
  failed: { text: "Failed", dot: "bg-danger" },
  cancelled: { text: "Cancelled", dot: "bg-line-strong" },
  deadline_exceeded: { text: "Ran out of time", dot: "bg-danger" },
};

function Version({ w }: { w: WorkflowRow }) {
  if (w.active_version_number === null) return <span className="text-muted">Not published</span>;
  return (
    <span className="font-mono text-small">
      v{w.active_version_number}
      {w.unpublished_changes && <span className="font-sans text-muted"> · unpublished changes</span>}
    </span>
  );
}

/** The last live run, what attention follows; the last simulation apart, in the simulation colour (4b ruling 7). */
function LastRun({ w }: { w: WorkflowRow }) {
  const live = w.last_run;
  const simulated = w.last_simulation;
  if (!live && !simulated) return <span className="text-muted">No runs yet</span>;
  return (
    <span className="flex flex-col gap-0.5 text-small">
      {live ? (
        <span className="inline-flex items-center gap-2">
          <span aria-hidden="true" className={`size-2 rounded-sm ${STATUS[live.status].dot}`} />
          {STATUS[live.status].text} · {since(live.at)}
        </span>
      ) : (
        <span className="text-muted">No live runs yet</span>
      )}
      {simulated && <span className="text-sim">Simulated: {STATUS[simulated.status].text} · {since(simulated.at)}</span>}
    </span>
  );
}

export function WorkflowsPage({ tenantId }: { tenantId: string; startNew?: boolean }) {
  useDocumentTitle("Workflows");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const list = useQuery(workflowsQuery(tenantId));
  const tenant = useQuery(tenantQuery(tenantId));
  const [filter, setFilter] = useState<Filter>("all");
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const toggle = useMutation({
    mutationFn: (w: { id: string; name: string; enabled: boolean }) =>
      ok(
        client.PATCH("/api/v1/t/{tenant_id}/workflows/{workflow_id}", {
          params: { path: { tenant_id: tenantId, workflow_id: w.id } },
          body: { enabled: w.enabled },
        }),
      ),
    onMutate: () => setError(null),
    onSuccess: async (_, w) => {
      announce(`${w.name} switched ${w.enabled ? "on" : "off"}`);
      await qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
    },
    onError: (e, w) => {
      const first = e instanceof ApiError && e.code === "not_enableable"
        ? (e.body as { diagnostics?: { message: string }[] }).diagnostics?.[0]?.message
        : undefined;  // prettier-ignore
      setError(first ? `${w.name} can't be switched on: ${first}` : `${w.name} couldn't be switched. Try again.`);
    },
  });

  async function exportOne(w: WorkflowRow) {
    try {
      const doc = await ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/export", {
          params: { path: { tenant_id: tenantId, workflow_id: w.id } },
        }),
      );
      downloadJson(fileName(w.name, ".dewpoint.json"), doc);
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_portable") {
        const problems = (e.body as { problems: PortableProblem[] }).problems;
        setError(`${w.name} can't be exported as a portable file: ${notPortable(problems)}. Open it to download the draft as it is.`);
        return;
      }
      setError(`${w.name} couldn't be exported. Try again.`);
    }
  }

  const rows = list.data ?? [];
  const named = rows.filter((w) => w.name.toLowerCase().includes(text.trim().toLowerCase()));
  const shown = named.filter(FILTERS.find((f) => f.value === filter)!.keep);
  const publisher = canPublish(tenant.data?.role);

  return (
    <section className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-h1 font-semibold">Workflows</h1>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex min-w-0 flex-1 basis-56 flex-col gap-1 sm:max-w-80">
          <span className="sr-only">Filter by name</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Filter by name"
            className="min-h-9 w-full rounded-lg border border-line-control bg-surface px-3 text-body placeholder:text-muted"
          />
        </label>
        <Segmented
          label="Show"
          value={filter}
          onChange={setFilter}
          options={FILTERS.map((f) => ({ value: f.value, label: f.label, count: named.filter(f.keep).length }))}
        />
      </div>
      {error && <p role="alert" className="text-body text-danger">{error}</p>}
      {list.isError ? (
        <LoadError what="The workflows" />
      ) : (
        <Table label="Workflows">
          <thead>
            <tr>
              <Th>Name</Th><Th>Version</Th><Th>Last run</Th><Th>Last 24 h</Th><Th>Enabled</Th>
              <Th><span className="sr-only">Actions</span></Th>
            </tr>
          </thead>
          <tbody>
            {shown.map((w) => (
              <tr key={w.id}>
                <Td>
                  <Link to="/t/$tenantId/workflows/$workflowId" params={{ tenantId, workflowId: w.id }} className="font-medium text-accent-ink">
                    {w.name}
                  </Link>
                </Td>
                <Td><Version w={w} /></Td>
                <Td><LastRun w={w} /></Td>
                <Td className="font-mono text-small">
                  {w.runs_24h.live}
                  {w.runs_24h.simulate > 0 && <span className="font-sans text-sim"> +{w.runs_24h.simulate} simulated</span>}
                </Td>
                <Td>
                  {publisher ? (
                    <Switch
                      checked={w.enabled}
                      label={`Enable ${w.name}`}
                      disabled={toggle.isPending}
                      onCheckedChange={(enabled) => toggle.mutate({ id: w.id, name: w.name, enabled })}
                    />
                  ) : (
                    <span className="text-small">{w.enabled ? "On" : "Off"}</span>
                  )}
                </Td>
                <Td className="text-right">
                  <Dropdown.Root modal={false}>
                    <Dropdown.Trigger aria-label={`Actions for ${w.name}`} className="min-h-8 rounded-md border border-line-strong bg-surface px-2 text-small text-ink hover:bg-surface-hover">
                      ···
                    </Dropdown.Trigger>
                    <Dropdown.Portal>
                      <Dropdown.Content align="end" sideOffset={4} className="min-w-40 rounded-lg border border-line bg-surface p-1 shadow-dialog">
                        <Dropdown.Item
                          onSelect={() => void navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: w.id } })}
                          className="cursor-pointer rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
                        >
                          Open
                        </Dropdown.Item>
                        <Dropdown.Item
                          onSelect={() => void exportOne(w)}
                          className="cursor-pointer rounded-md px-3 py-2 text-body data-[highlighted]:bg-accent-soft data-[highlighted]:text-accent-ink"
                        >
                          Export
                        </Dropdown.Item>
                      </Dropdown.Content>
                    </Dropdown.Portal>
                  </Dropdown.Root>
                </Td>
              </tr>
            ))}
            {list.data && shown.length === 0 && (
              <tr>
                <Td colSpan={6} className="text-muted">{rows.length === 0 ? "No workflows yet." : "No workflow matches."}</Td>
              </tr>
            )}
          </tbody>
        </Table>
      )}
      <p className="text-small text-muted">A disabled workflow keeps its versions and its history; nothing starts it.</p>
    </section>
  );
}
```

- [ ] **Step 5: Run the tests to see them pass, then the suite, lint and types**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/components/Switch.test.tsx src/components/Segmented.test.tsx src/routes/Workflows.test.tsx && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean; the AI-tells guard passes the new files (no pill, no gradient, motion 100 ms with reduced
motion honoured).

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(web): the workflows list (1a): state at a glance, filters, the enable switch, export (4b)"
```

### Task 8: "New workflow" (1b): a name, then Blank or Import from file, each binding chosen

**Files:**
- Create: `frontend/src/routes/NewWorkflow.tsx`, `frontend/src/routes/ImportBindings.tsx`
- Create: `frontend/src/routes/NewWorkflow.test.tsx`
- Modify: `frontend/src/routes/Workflows.tsx` (the button, `startNew`), `frontend/src/routes/Workflows.test.tsx`

**Interfaces:**
- Consumes: `POST /api/v1/t/{tenant_id}/workflows` (`{name}` → `WorkflowDetailOut`), `POST …/workflows/import`
  (`{name, document, bind}`), `GET …/connections` (the key `["connections", tenantId]` Connections uses),
  `workflowsQuery`, `WorkflowDocument`, `Select` (`frontend/src/components/Field.tsx`).
- Produces: `<NewWorkflow tenantId onClose />` (a native modal dialog, D23), `parseDocument(text) ->
  WorkflowDocument | null`, `useBindingChoices(tenantId, bindings) -> Choices` (`state: "ready" | "loading" |
  "failed"`, the lists, `retry`), `<ImportBindings bindings choices chosen onChange />`, `type Chosen = Record<string,
  string>`.

`parseDocument` checks the whole envelope as the API's model does (the owner's review of 325fc14, correction 5):
exactly its five keys; a `name` of at most 100 characters; `graph` an object (never `null` or a list); at most 10,000
bindings, each an object of exactly `id` (the API's pattern, used once), `kind`, `type` (1–100 characters for a
connection, `null` for a workflow), `label` (at most 200) and 1–10,000 sites, each exactly `{node: string (at most
64) | null, field: string (2–200)}`. Revision 1 let `graph: null` through and crashed on `bindings:
[null]`. The API stays the judge: it refuses what this lets through (an embedded id, a site its schemas don't mark),
and the dialog says why.

- [ ] **Step 1: Write the failing tests**

`frontend/src/routes/NewWorkflow.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { NewWorkflow, parseDocument } from "./NewWorkflow";

const DOC = {
  format: "dewpoint.workflow", format_version: 1, name: "Nightly report", graph: { graph_format: 1, nodes: [], edges: [] },
  bindings: [{ id: "b1", kind: "connection", type: "mist", label: "Acme Prod", sites: [{ node: "n1", field: "/connection" }] }],
};  // prettier-ignore
const CONNECTIONS = [
  { id: "c1", type: "mist", name: "Lab Mist", revision: 1, config: {}, secret_set: true, status: "ok", status_detail: "", privilege: null, last_verified_at: null },
  { id: "c2", type: "slack", name: "NOC Slack", revision: 1, config: {}, secret_set: true, status: "ok", status_detail: "", privilege: null, last_verified_at: null },
];  // prettier-ignore

let sent: { method: string; path: string; body: unknown }[];
let answer: { status: number; body: unknown };
let connectionsAnswer: () => Response;

beforeEach(() => {
  sent = [];
  answer = { status: 201, body: { id: "w9", name: "Nightly report" } };
  connectionsAnswer = () => new Response(JSON.stringify(CONNECTIONS));
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
    if (request.method === "POST") return new Response(JSON.stringify(answer.body), { status: answer.status });
    if (path.endsWith("/connections")) return connectionsAnswer();
    return new Response("[]");
  });
});

async function show(onClose = vi.fn()) {
  const root = createRootRoute({ component: () => <NewWorkflow tenantId="t1" onClose={onClose} /> });
  const editor = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows/$workflowId", component: () => <p>editor</p> });
  const router = createRouter({ routeTree: root.addChildren([editor]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("dialog", { name: "New workflow" });
  return router;
}

it("starts blank from a name, and opens the editor", async () => {
  const router = await show();
  expect(document.activeElement).toBe(screen.getByLabelText("Name"));
  await userEvent.type(screen.getByLabelText("Name"), "Nightly report");
  await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
  expect(sent.find((r) => r.method === "POST")).toEqual({ method: "POST", path: "/api/v1/t/t1/workflows", body: { name: "Nightly report" } });
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w9"));
});

it("says plainly when the name is taken", async () => {
  answer = { status: 409, body: { error: "name_taken" } };
  await show();
  await userEvent.type(screen.getByLabelText("Name"), "Nightly report");
  await userEvent.click(screen.getByRole("button", { name: "Create and open" }));
  expect((await screen.findByRole("alert")).textContent).toContain("A workflow with this name exists");
});

it("imports a file, binding each placeholder to one of this tenant's of its type", async () => {
  const router = await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  const file = new File([JSON.stringify(DOC)], "nightly.dewpoint.json", { type: "application/json" });
  await userEvent.upload(screen.getByLabelText("Workflow file"), file);
  expect(await screen.findByDisplayValue("Nightly report")).toBeTruthy(); // the file's name, editable
  const binding = await screen.findByLabelText("Acme Prod (mist connection)");
  expect([...(binding as HTMLSelectElement).options].map((o) => o.text)).toEqual(["Leave unbound", "Lab Mist"]);
  await userEvent.selectOptions(binding, "c1");
  await userEvent.click(screen.getByRole("button", { name: "Import and open" }));
  expect(sent.find((r) => r.method === "POST")).toEqual({
    method: "POST", path: "/api/v1/t/t1/workflows/import",
    body: { name: "Nightly report", document: DOC, bind: { b1: "c1" } },
  });  // prettier-ignore
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/t/t1/workflows/w9"));
});

it("refuses a file that isn't a workflow, and names a refused binding", async () => {
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File(["{}"], "x.json", { type: "application/json" }));
  expect((await screen.findByText(/isn't a Dewpoint workflow/)).textContent).toBeTruthy();
  answer = { status: 422, body: { error: "bad_binding", binding: "b1", reason: "wrong_type" } };
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File([JSON.stringify(DOC)], "n.json", { type: "application/json" }));
  await userEvent.click(await screen.findByRole("button", { name: "Import and open" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Acme Prod is of another type");
});

it("closes on Cancel", async () => {
  const onClose = vi.fn();
  await show(onClose);
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(onClose).toHaveBeenCalled();
});

it("reads only a Dewpoint workflow file", () => {
  expect(parseDocument(JSON.stringify(DOC))?.name).toBe("Nightly report");
  expect(parseDocument("not json")).toBeNull();
  expect(parseDocument(JSON.stringify({ ...DOC, format_version: 2 }))).toBeNull();
});

const B = DOC.bindings[0]!;
it.each([
  ["a null graph", { ...DOC, graph: null }],
  ["a graph that's a list", { ...DOC, graph: [] }],
  ["a null binding", { ...DOC, bindings: [null] }],
  ["a binding without a site", { ...DOC, bindings: [{ ...B, sites: [] }] }],
  ["a binding id used twice", { ...DOC, bindings: [B, B] }],
  ["a binding id the API refuses", { ...DOC, bindings: [{ ...B, id: "B 1" }] }],
  ["a connection binding without a type", { ...DOC, bindings: [{ ...B, type: null }] }],
  ["a workflow binding with a type", { ...DOC, bindings: [{ ...B, kind: "workflow" }] }],
  ["a kind that isn't one", { ...DOC, bindings: [{ ...B, kind: "secret" }] }],
  ["a site without a field", { ...DOC, bindings: [{ ...B, sites: [{ node: "n1" }] }] }],
  ["a site's node that's a number", { ...DOC, bindings: [{ ...B, sites: [{ node: 7, field: "/connection" }] }] }],
  ["an extra key", { ...DOC, extra: 1 }],
  ["an extra key in a binding", { ...DOC, bindings: [{ ...B, secret: "x" }] }],
  ["a name longer than the API takes", { ...DOC, name: "n".repeat(101) }],
  ["a label longer than the API takes", { ...DOC, bindings: [{ ...B, label: "l".repeat(201) }] }],
  ["a field shorter than a pointer", { ...DOC, bindings: [{ ...B, sites: [{ node: "n1", field: "/" }] }] }],
])("refuses %s", (_, doc) => {
  expect(parseDocument(JSON.stringify(doc))).toBeNull();
});

async function importDoc(doc: object = DOC) {
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File([JSON.stringify(doc)], "n.json", { type: "application/json" }));
}

it("offers no choice until this tenant's connections are read, and says when they can't be", async () => {
  connectionsAnswer = () => new Response(JSON.stringify({ error: "http_error" }), { status: 500 });
  await show();
  await importDoc();
  expect((await screen.findByRole("alert")).textContent).toContain("couldn't be read, so nothing can be bound yet");
  expect(screen.queryByLabelText("Acme Prod (mist connection)")).toBeNull(); // never "Leave unbound" by default
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(true);
  connectionsAnswer = () => new Response(JSON.stringify(CONNECTIONS));
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByLabelText("Acme Prod (mist connection)")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(false);
});

it("says when this tenant has no connection of a binding's type", async () => {
  connectionsAnswer = () => new Response(JSON.stringify(CONNECTIONS.filter((c) => c.type !== "mist")));
  await show();
  await importDoc();
  const binding = await screen.findByLabelText("Acme Prod (mist connection)");
  expect([...(binding as HTMLSelectElement).options].map((o) => o.text)).toEqual(["Leave unbound"]);
  expect(screen.getByText("No mist connection in this tenant: it stays unbound.")).toBeTruthy();
});

it("refuses a file with a null binding without breaking the dialog", async () => {
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  const bad = new File([JSON.stringify({ ...DOC, bindings: [null] })], "x.json", { type: "application/json" });
  await userEvent.upload(screen.getByLabelText("Workflow file"), bad);
  expect(await screen.findByText(/isn't a Dewpoint workflow/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Import and open" }).hasAttribute("disabled")).toBe(true);
});

it("says why the server refused the file", async () => {
  answer = { status: 422, body: { error: "bad_document", problems: [{ reason: "embedded_value", binding: null, node: "n1", field: "/connection" }] } };
  await show();
  await userEvent.click(screen.getByRole("radio", { name: /Import from file/ }));
  await userEvent.upload(screen.getByLabelText("Workflow file"), new File([JSON.stringify(DOC)], "n.json", { type: "application/json" }));
  await userEvent.click(await screen.findByRole("button", { name: "Import and open" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The file can't be imported: it holds a connection or workflow id where a binding goes. Export it again from Dewpoint.",
  );
});
```

In `frontend/src/routes/Workflows.test.tsx`, add:

```tsx
it("offers New workflow to editors, and opens it when asked by the URL", async () => {
  await show();
  await userEvent.click(await screen.findByRole("button", { name: "New workflow" }));
  expect(screen.getByRole("dialog", { name: "New workflow" })).toBeTruthy();
});

it("offers no New workflow to a viewer", async () => {
  role = "viewer";
  await show();
  await screen.findByRole("link", { name: "Nightly" });
  expect(screen.queryByRole("button", { name: "New workflow" })).toBeNull();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/NewWorkflow.test.tsx src/routes/Workflows.test.tsx`
Expected: FAIL: `NewWorkflow` doesn't exist; the list has no "New workflow".

- [ ] **Step 3: Implement the bindings**

`frontend/src/routes/ImportBindings.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// Each id a workflow file names (a connection, a workflow) bound to one of this tenant's, or left unbound (B12; 4b
// ruling 18). A connection binding offers only connections of its type. Leaving one unbound is a choice the person
// makes from what was read (ruling 28): while this tenant's connections and workflows are loading, or when they
// couldn't be read, no choice is offered and nothing can be imported.
import { useQuery } from "@tanstack/react-query";
import { Button } from "../components/Button";
import { Select } from "../components/Field";
import { client, ok } from "../lib/client";
import { workflowsQuery, type WorkflowDocument } from "../lib/workflows";

export type Chosen = Record<string, string>;

export type Choices = {
  state: "ready" | "loading" | "failed";
  connections: { id: string; name: string; type: string }[];
  workflows: { id: string; name: string }[];
  retry: () => void;
};

/** This tenant's connections and workflows, read only when a binding needs them; "ready" only once each needed list
 * was read, never an empty list standing in for one that wasn't. */
export function useBindingChoices(tenantId: string, bindings: WorkflowDocument["bindings"]): Choices {
  const needConnections = bindings.some((b) => b.kind === "connection");
  const needWorkflows = bindings.some((b) => b.kind === "workflow");
  const connections = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path: { tenant_id: tenantId } } })),
    enabled: needConnections,
  });
  const workflows = useQuery({ ...workflowsQuery(tenantId), enabled: needWorkflows });
  const needed = [...(needConnections ? [connections] : []), ...(needWorkflows ? [workflows] : [])];
  const state = needed.some((q) => q.isError) ? "failed" : needed.every((q) => q.isSuccess) ? "ready" : "loading";
  return {
    state,
    connections: (connections.data ?? []).map((c) => ({ id: c.id, name: c.name, type: c.type })),
    workflows: (workflows.data ?? []).map((w) => ({ id: w.id, name: w.name })),
    retry: () => {
      if (connections.isError) void connections.refetch();
      if (workflows.isError) void workflows.refetch();
    },
  };
}

export function ImportBindings({
  bindings,
  choices,
  chosen,
  onChange,
}: {
  bindings: WorkflowDocument["bindings"];
  choices: Choices;
  chosen: Chosen;
  onChange: (chosen: Chosen) => void;
}) {
  if (bindings.length === 0) return <p className="text-small text-muted">The file names no connection or workflow.</p>;
  if (choices.state === "loading") {
    return <p className="text-small text-muted">Reading this tenant&apos;s connections and workflows…</p>;
  }
  if (choices.state === "failed") {
    return (
      <p role="alert" className="flex flex-wrap items-center gap-2 text-small text-danger">
        This tenant&apos;s connections or workflows couldn&apos;t be read, so nothing can be bound yet.
        <Button size="sm" onClick={choices.retry}>Try again</Button>
      </p>
    );
  }
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1 text-small font-semibold">What the file names, bound to this tenant&apos;s</legend>
      {bindings.map((b) => {
        const options =
          b.kind === "connection"
            ? choices.connections.filter((c) => c.type === b.type)
            : choices.workflows;
        const places = `${b.sites.length} place${b.sites.length === 1 ? "" : "s"} in the graph`;
        const none = b.kind === "connection" ? `No ${b.type} connection in this tenant: it stays unbound.` : "No workflow in this tenant: it stays unbound.";
        return (
          <Select
            key={b.id}
            label={`${b.label} (${b.kind === "connection" ? `${b.type} connection` : "workflow"})`}
            hint={options.length === 0 ? none : places}
            value={chosen[b.id] ?? ""}
            onChange={(e) => {
              const { [b.id]: _, ...rest } = chosen;
              onChange(e.target.value ? { ...rest, [b.id]: e.target.value } : rest);
            }}
          >
            <option value="">Leave unbound</option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>{o.name}</option>
            ))}
          </Select>
        );
      })}
    </fieldset>
  );
}
```

- [ ] **Step 4: Implement the dialog**

`frontend/src/routes/NewWorkflow.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// "New workflow" (screen 1b; 4b ruling 1): a name, then Blank or Import from file. The trigger step ("What starts
// it?") comes with 4c's trigger setup, "Describe it" with sub-project 5; "From template" waits for curated templates
// (D9). A native modal dialog (D23): focus moves in and back, Escape closes.
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Button } from "../components/Button";
import { Field } from "../components/Field";
import { announce } from "../lib/announce";
import { ApiError, client, ok } from "../lib/client";
import type { WorkflowDocument } from "../lib/workflows";
import { ImportBindings, useBindingChoices, type Chosen } from "./ImportBindings";

type Start = "blank" | "import";

// The API's `WorkflowDocument`, `Binding` and `BindingSite` (Task 5), mirrored: a file that passes here passes the
// model there, and the API's own refusals are about the graph and the bindings, not the envelope.
const BINDING_ID = /^[a-z][a-z0-9_]{0,31}$/;
const MAX_BINDINGS = 10_000; // bindings in a file, and sites in a binding

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const keysAre = (v: Record<string, unknown>, keys: string[]) =>
  Object.keys(v).length === keys.length && keys.every((k) => k in v);
const sized = (v: unknown, min: number, max: number) => typeof v === "string" && v.length >= min && v.length <= max;

function isSite(s: unknown): boolean {
  return isObject(s) && keysAre(s, ["node", "field"]) && (s.node === null || sized(s.node, 0, 64)) && sized(s.field, 2, 200);
}

function isBinding(b: unknown): boolean {
  if (!isObject(b) || !keysAre(b, ["id", "kind", "type", "label", "sites"])) return false;
  if (typeof b.id !== "string" || !BINDING_ID.test(b.id) || !sized(b.label, 0, 200)) return false;
  if (!(b.kind === "connection" ? sized(b.type, 1, 100) : b.kind === "workflow" && b.type === null)) return false;
  return Array.isArray(b.sites) && b.sites.length > 0 && b.sites.length <= MAX_BINDINGS && b.sites.every(isSite);
}

/** A workflow file, or null: the whole envelope is checked here, as the API's model checks it; the API then checks
 * the graph and the bindings against its node types (4b ruling 18). */
export function parseDocument(text: string): WorkflowDocument | null {
  let doc: unknown;
  try {
    doc = JSON.parse(text);
  } catch {
    return null;
  }
  if (!isObject(doc) || !keysAre(doc, ["format", "format_version", "name", "graph", "bindings"])) return null;
  if (doc.format !== "dewpoint.workflow" || doc.format_version !== 1 || !sized(doc.name, 0, 100)) return null;
  if (!isObject(doc.graph) || !Array.isArray(doc.bindings) || doc.bindings.length > MAX_BINDINGS) return null;
  if (!doc.bindings.every(isBinding)) return null;
  const ids = doc.bindings.map((b) => (b as { id: string }).id);
  if (new Set(ids).size !== ids.length) return null;
  return doc as unknown as WorkflowDocument;
}

const REASONS: Record<string, string> = {
  unknown: "isn't one of this tenant's",
  wrong_type: "is of another type",
  unexpected: "isn't in the file",
};

// The API's `bad_document` reasons (Task 5), the first one said.
const DOCUMENT: Record<string, string> = {
  unknown_type: "it has steps of a type this server doesn't know",
  duplicate_node: "two of its steps share an id",
  embedded_value: "it holds a connection or workflow id where a binding goes. Export it again from Dewpoint",
  duplicate_binding: "its bindings don't match its steps",
  overlapping_site: "its bindings don't match its steps",
  bad_site: "its bindings don't match its steps",
};

function explain(e: unknown, doc: WorkflowDocument | null): string {
  if (!(e instanceof ApiError)) return "The workflow couldn't be created. Try again.";
  if (e.code === "name_taken") return "A workflow with this name exists. Choose another name.";
  if (e.status === 403) return "You can't create workflows in this tenant.";
  if (e.code === "bad_binding") {
    const body = e.body as { binding?: string; reason?: string };
    const label = doc?.bindings.find((b) => b.id === body.binding)?.label ?? "A binding";
    return `${label} ${REASONS[body.reason ?? ""] ?? "can't be bound"}.`;
  }
  if (e.code === "bad_document") {
    const first = (e.body as { problems?: { reason: string }[] }).problems?.[0]?.reason ?? "";
    return `The file can't be imported: ${DOCUMENT[first] ?? "it doesn't match this server's steps"}.`;
  }
  if (e.code === "invalid") {
    const body = e.body as { diagnostics?: { message: string }[] };
    if (!body.diagnostics) return "That file isn't a Dewpoint workflow this server can read.";
    const first = body.diagnostics[0]?.message;
    return `The file's graph isn't valid${first ? `: ${first}` : ""}.`;
  }
  return "The workflow couldn't be created. Try again.";
}

const CHOICE = "flex cursor-pointer flex-col gap-1 rounded-lg border border-line-strong bg-surface p-4 has-[:checked]:border-accent has-[:checked]:bg-accent-soft";

export function NewWorkflow({ tenantId, onClose }: { tenantId: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [start, setStart] = useState<Start>("blank");
  const [doc, setDoc] = useState<WorkflowDocument | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Chosen>({});
  const [error, setError] = useState<string | null>(null);
  const choices = useBindingChoices(tenantId, doc?.bindings ?? []);

  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLInputElement>("input[name='name']")?.focus();
    }
  }, []);

  const create = useMutation({
    mutationFn: () => {
      const path = { params: { path: { tenant_id: tenantId } } };
      return start === "blank"
        ? ok(client.POST("/api/v1/t/{tenant_id}/workflows", { ...path, body: { name: name.trim() } }))
        : ok(client.POST("/api/v1/t/{tenant_id}/workflows/import", { ...path, body: { name: name.trim(), document: doc!, bind: chosen } }));
    },
    onMutate: () => setError(null),
    onSuccess: async (wf) => {
      announce(`Created ${wf.name}`);
      await qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
      dialog.current?.close();
      await navigate({ to: "/t/$tenantId/workflows/$workflowId", params: { tenantId, workflowId: wf.id } });
    },
    onError: (e) => setError(explain(e, doc)),
  });

  async function readFile(file: File | undefined) {
    setDoc(null);
    setChosen({});
    setFileError(null);
    if (!file) return;
    const parsed = parseDocument(await file.text());
    if (!parsed) {
      setFileError("That file isn't a Dewpoint workflow.");
      return;
    }
    setDoc(parsed);
    if (!name.trim()) setName(parsed.name.slice(0, 100));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  // An import waits for what its bindings are chosen from: unbound is a choice, never a lookup that failed.
  const ready = name.trim().length > 0 && (start === "blank" || (doc !== null && choices.state === "ready"));

  return (
    <dialog
      ref={dialog}
      aria-labelledby="new-workflow-title"
      onClose={onClose}
      className="mx-auto mt-16 w-[640px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <form onSubmit={submit} className="flex flex-col gap-5">
        <h2 id="new-workflow-title" className="text-h3 font-semibold">New workflow</h2>
        <Field label="Name" name="name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-small font-semibold">How do you want to start?</legend>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className={CHOICE}>
              <span className="flex items-center gap-2">
                <input type="radio" name="start" value="blank" checked={start === "blank"} onChange={() => setStart("blank")} />
                <span className="font-semibold">Blank</span>
              </span>
              <span className="text-small text-muted">
                A start card on the canvas. Add steps from ＋ or press <kbd className="rounded-sm border border-line-strong px-1 font-mono text-meta">A</kbd>.
              </span>
            </label>
            <label className={CHOICE}>
              <span className="flex items-center gap-2">
                <input type="radio" name="start" value="import" checked={start === "import"} onChange={() => setStart("import")} />
                <span className="font-semibold">Import from file</span>
              </span>
              <span className="text-small text-muted">A workflow exported from Dewpoint. Its connections are bound to yours.</span>
            </label>
          </div>
        </fieldset>
        {start === "import" && (
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-small font-semibold">Workflow file</span>
              <input type="file" accept=".json,application/json" onChange={(e) => void readFile(e.target.files?.[0])} className="text-body" />
            </label>
            {fileError && <p className="text-small text-danger">{fileError}</p>}
            {doc && <ImportBindings bindings={doc.bindings} choices={choices} chosen={chosen} onChange={setChosen} />}
          </div>
        )}
        {error && <p role="alert" className="text-body text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button onClick={() => dialog.current?.close()}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={!ready || create.isPending}>
            {start === "blank" ? "Create and open" : "Import and open"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
```

`Field` passes `name` through to its input (it spreads the input's props). The test-setup's dialog stand-in
(`src/test/setup.ts`) opens and closes the dialog; the browser gate checks the real one (Task 16).

- [ ] **Step 5: Wire it into the list**

In `frontend/src/routes/Workflows.tsx`: import `Button`, `canEdit` and `NewWorkflow`; take `startNew`:

```tsx
export function WorkflowsPage({ tenantId, startNew = false }: { tenantId: string; startNew?: boolean }) {
```

```tsx
  const [creating, setCreating] = useState(startNew);

  function closeNew() {
    setCreating(false);
    if (startNew) void navigate({ to: "/t/$tenantId/workflows", params: { tenantId }, search: {} });
  }
```

the header gains the button:

```tsx
        {canEdit(tenant.data?.role) && (
          <Button variant="primary" size="md" onClick={() => setCreating(true)} data-testid="workflow-new">
            New workflow
          </Button>
        )}
```

and the section ends with `{creating && <NewWorkflow tenantId={tenantId} onClose={closeNew} />}`.

- [ ] **Step 6: Run the tests to see them pass, then the suite, lint and types**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/NewWorkflow.test.tsx src/routes/Workflows.test.tsx && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes
git commit -m "feat(web): New workflow (1b): a name, then Blank or Import from file with each binding chosen (4b)"
```

**Milestone 2's check:** `cd frontend && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck && npx -y pnpm@12.6.0 build`. All pass.

## Milestone 3 — The canvas

### Task 9: The draft as a document: pure operations that keep what they don't touch, with undo and redo

**Files:**
- Create: `frontend/src/lib/graph.ts`, `frontend/src/lib/graph.test.ts`
- Create: `frontend/src/lib/history.ts`, `frontend/src/lib/history.test.ts`

**Interfaces:**
- Consumes: `GraphDoc`, `GraphNode`, `GraphEdge`, `NodeType` (Task 6).
- Produces (`graph.ts`): `START = "start"`, `ROW = 140`, `COLUMN = 300`; `type PortRef = { node: string; port:
  string }`; `asGraph(draft)`, `nodesOf(doc)`, `edgesOf(doc)`, `edgeId(edge)`, `pos(node)`, `portsOf(node, type)`,
  `continuationPort(type)`, `keyFor(type, taken)`, `defaultConfig(type)`, `entries(doc)`, `startPosition(doc)`,
  `addAfter(doc, from: PortRef | null, type, id?) -> { doc, node }`, `insertOnEdge(doc, edge, type, id?) -> { doc,
  node } | null`, `insertBeforeEntry(doc, entryId, type, id?) -> { doc, node } | null`, `deleteNode(doc, id) -> { doc,
  healed }`, `deleteEdge(doc, edge)`, `reaches(doc, from, to)`, `canConnect(doc, from, to)`, `connect(doc, from, to)
  -> GraphDoc | null`, `moveNodes(doc, positions: Map<string, {x, y}>)`, `drawableEdges(doc)` (the edges the canvas
  and the keyboard model use: both ends exist, each once; an imported draft may hold others). (`history.ts`): `type
  History<T>`, `LIMIT = 100`, `begin(present)`, `record(h, next)`, `undo(h)`, `redo(h)`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/graph.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import {
  ROW, addAfter, canConnect, connect, continuationPort, defaultConfig, deleteEdge, deleteNode, drawableEdges, edgeId,
  entries, insertBeforeEntry, insertOnEdge, keyFor, moveNodes, portsOf, startPosition,
} from "./graph";  // prettier-ignore
import type { GraphDoc, NodeType } from "./workflows";

const type = (ref: string, ports: string[], extra: Partial<NodeType> = {}): NodeType => ({
  ref, type: ref.split("@")[0]!, version: 1, kind: "control", state: "active", title: ref, description: "",
  ports, dynamic_ports: null, config_schema: {}, output_schema: {}, side_effect: "none", credentials: [],
  capabilities: [], retry: { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] },
  timeout_s: 60, ...extra,
});  // prettier-ignore
const TRANSFORM = type("flow.transform@1", ["out"], {
  config_schema: { properties: { fields: { type: "object", default: {} }, connection: { type: "string", "x-dewpoint-connection": "mist", default: "x" } } },
});  // prettier-ignore
const IF = type("flow.if@1", ["true", "false"]);
const LOOP = type("flow.loop@1", ["body", "done"]);
const STOP = type("flow.stop@1", []);
const SWITCH = type("flow.switch@1", ["default"], { dynamic_ports: "cases" });

// a → b, with what the editor doesn't model kept around them
const doc = (): GraphDoc => ({
  graph_format: 1,
  nodes: [
    { id: "a", key: "a", type: "flow.transform@1", config: { fields: { x: 1 } }, position: { x: 0, y: 0 }, options: { timeout_s: 30 } },
    { id: "b", key: "b", type: "vendor.unknown@3", config: { secret_looking: "kept" }, position: { x: 0, y: 140 } },
  ],
  edges: [{ from: { node: "a", port: "out" }, to: { node: "b" } }],
  settings: { input_schema: { type: "object" }, declassify: [{ node: "b", field: "/x" }] },
});  // prettier-ignore

describe("ports", () => {
  it("lists a dynamic port per config entry, then the type's own, then error when errors route there", () => {
    const node = { id: "s", key: "s", type: "flow.switch@1", config: { cases: [{ port: "eu" }, { port: "us" }] }, options: { on_error: "port" as const } };
    expect(portsOf(node, SWITCH)).toEqual(["eu", "us", "default", "error"]);
    expect(portsOf({ id: "u", key: "u", type: "vendor.unknown@3" }, undefined)).toEqual([]);
  });

  it("continues an inserted step through out, or a loop's done, and never through a branch", () => {
    expect([continuationPort(TRANSFORM), continuationPort(LOOP), continuationPort(IF), continuationPort(STOP)]).toEqual([
      "out", "done", null, null,
    ]);  // prettier-ignore
  });
});

describe("a new step", () => {
  it("takes a key from its type, numbered when taken, and its schema's defaults but never a connection", () => {
    expect(keyFor(TRANSFORM, ["a"])).toBe("transform");
    expect(keyFor(TRANSFORM, ["transform", "transform_2"])).toBe("transform_3");
    expect(defaultConfig(TRANSFORM)).toEqual({ fields: {} });
  });

  it("goes after a port, below its source, and is connected from it", () => {
    const { doc: next, node } = addAfter(doc(), { node: "b", port: "out" }, TRANSFORM, "n1");
    expect(node).toMatchObject({ id: "n1", key: "transform", type: "flow.transform@1", position: { x: 0, y: 280 } });
    expect(next.edges!.at(-1)).toEqual({ from: { node: "b", port: "out" }, to: { node: "n1" } });
  });

  it("goes first when added from the start card, beside the other entry steps", () => {
    const { doc: next, node } = addAfter(doc(), null, TRANSFORM, "n1");
    expect(node.position).toEqual({ x: 300, y: 0 });
    expect(entries(next).map((n) => n.id)).toEqual(["a", "n1"]);
  });
});

describe("inserting on an edge", () => {
  it("puts the step between the edge's ends and moves what's below down a row", () => {
    const { doc: next, node } = insertOnEdge(doc(), doc().edges![0]!, TRANSFORM, "n1")!;
    expect(node.position).toEqual({ x: 0, y: ROW });
    expect(next.nodes!.find((n) => n.id === "b")!.position).toEqual({ x: 0, y: 2 * ROW });
    expect(next.edges!.map(edgeId)).toEqual(["a:out->n1", "n1:out->b"]);
  });

  it("refuses a step that can't continue the flow", () => {
    expect(insertOnEdge(doc(), doc().edges![0]!, IF)).toBeNull();
  });

  it("puts a step before an entry step, which it now leads to", () => {
    const { doc: next } = insertBeforeEntry(doc(), "a", LOOP, "n1")!;
    expect(next.edges!.map(edgeId)).toContain("n1:done->a");
    expect(entries(next).map((n) => n.id)).toEqual(["n1"]);
  });
});

describe("deleting", () => {
  it("removes the step, its edges and its declassify entries, and heals a chain through it", () => {
    const chain: GraphDoc = { ...doc(), nodes: [...doc().nodes!, { id: "c", key: "c", type: "flow.transform@1" }],
      edges: [...doc().edges!, { from: { node: "b", port: "out" }, to: { node: "c" } }] };  // prettier-ignore
    const { doc: next, healed } = deleteNode(chain, "b");
    expect(next.nodes!.map((n) => n.id)).toEqual(["a", "c"]);
    expect(next.edges!.map(edgeId)).toEqual(["a:out->c"]);
    expect(healed && edgeId(healed)).toBe("a:out->c");
    expect(next.settings!.declassify).toEqual([]);
  });

  it("heals nothing when the step joins or forks", () => {
    const fork: GraphDoc = { ...doc(), nodes: [...doc().nodes!, { id: "c", key: "c", type: "x@1" }, { id: "d", key: "d", type: "x@1" }],
      edges: [...doc().edges!, { from: { node: "b", port: "out" }, to: { node: "c" } }, { from: { node: "b", port: "out" }, to: { node: "d" } }] };  // prettier-ignore
    expect(deleteNode(fork, "b").healed).toBeNull();
  });

  it("removes one edge", () => {
    expect(deleteEdge(doc(), doc().edges![0]!).edges).toEqual([]);
  });
});

it("draws only edges whose ends exist, each once", () => {
  const edge = (from: string, to: string) => ({ from: { node: from, port: "out" }, to: { node: to } });
  const imported: GraphDoc = { ...doc(), edges: [edge("a", "b"), edge("a", "b"), edge("a", "gone"), edge("gone", "b")] };
  expect(drawableEdges(imported).map(edgeId)).toEqual(["a:out->b"]);
});

describe("connecting", () => {
  it("refuses itself, a duplicate and a cycle", () => {
    const d = doc();
    expect(canConnect(d, { node: "a", port: "out" }, "a")).toBe(false);
    expect(canConnect(d, { node: "a", port: "out" }, "b")).toBe(false);
    expect(canConnect(d, { node: "b", port: "out" }, "a")).toBe(false);
    const both: GraphDoc = { ...d, nodes: [...d.nodes!, { id: "c", key: "c", type: "x@1" }] };
    expect(connect(both, { node: "a", port: "out" }, "c")!.edges!.map(edgeId)).toEqual(["a:out->b", "a:out->c"]);
  });
});

it("keeps what it doesn't touch, byte for byte (4b's Review Focus)", () => {
  const before = doc();
  const { doc: next } = addAfter(before, { node: "b", port: "out" }, TRANSFORM, "n1");
  expect(next.graph_format).toBe(1);
  expect(next.settings).toEqual(before.settings);
  expect(next.nodes!.slice(0, 2)).toEqual(before.nodes);
  expect(JSON.stringify(doc())).toBe(JSON.stringify(before)); // the input is never mutated
  const moved = moveNodes(before, new Map([["a", { x: 12.4, y: -3 }]]));
  expect(moved.nodes![0]).toEqual({ ...before.nodes![0], position: { x: 12, y: -3 } });
  expect(moved.nodes![1]).toBe(before.nodes![1]);
});

it("puts the start card a row above the entry steps", () => {
  expect(startPosition(doc())).toEqual({ x: 0, y: -ROW });
  expect(startPosition({ graph_format: 1, nodes: [], edges: [] })).toEqual({ x: 0, y: 0 });
});
```

`frontend/src/lib/history.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { LIMIT, begin, record, redo, undo } from "./history";

it("undoes and redoes, and a new change drops what was undone", () => {
  let h = record(record(begin(1), 2), 3);
  h = undo(h);
  expect(h.present).toBe(2);
  h = redo(h);
  expect(h.present).toBe(3);
  h = record(undo(h), 9);
  expect([h.present, h.future]).toEqual([9, []]);
});

it("keeps at most LIMIT steps back, and ignores a change to the same document", () => {
  let h = begin(0);
  for (let i = 1; i <= LIMIT + 5; i++) h = record(h, i);
  expect(h.past.length).toBe(LIMIT);
  expect(record(h, h.present)).toBe(h);
  expect(undo(begin(1))).toEqual(begin(1));
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib/graph.test.ts src/lib/history.test.ts`
Expected: FAIL: neither module exists.

- [ ] **Step 3: Implement**

`frontend/src/lib/history.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// Undo and redo stay local (D17; 4b ruling 21): documents in memory, never sent, gone when the editor closes.
export interface History<T> {
  past: T[];
  present: T;
  future: T[];
}

export const LIMIT = 100;

export const begin = <T>(present: T): History<T> => ({ past: [], present, future: [] });

export function record<T>(h: History<T>, next: T): History<T> {
  if (next === h.present) return h;
  return { past: [...h.past, h.present].slice(-LIMIT), present: next, future: [] };
}

export function undo<T>(h: History<T>): History<T> {
  if (h.past.length === 0) return h;
  return { past: h.past.slice(0, -1), present: h.past[h.past.length - 1]!, future: [h.present, ...h.future] };
}

export function redo<T>(h: History<T>): History<T> {
  if (h.future.length === 0) return h;
  return { past: [...h.past, h.present], present: h.future[0]!, future: h.future.slice(1) };
}
```

`frontend/src/lib/graph.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// The draft as a document, and every change the editor makes to it, as pure functions (4b). Each returns a new
// document and keeps what it doesn't touch as it was, byte for byte: a draft from elsewhere (an import, an unknown
// node type, a settings block) round-trips. The server checks everything; nothing here validates.
import type { GraphDoc, GraphEdge, GraphNode, NodeType } from "./workflows";

export const START = "start"; // the start card on the canvas: never a node's id (those are UUIDs)
export const ROW = 140; // from one step's top to the next one's: a 64 px card and its gap
export const COLUMN = 300; // from one sibling's left to the next one's: a 260 px card and its gap
const KEY = /^[a-z][a-z0-9_]{0,62}$/;

export interface PortRef {
  node: string;
  port: string;
}

/** A draft from the API, as a document: it was format-checked when saved (4b ruling 9). */
export const asGraph = (draft: unknown): GraphDoc => draft as GraphDoc;
export const nodesOf = (doc: GraphDoc): GraphNode[] => doc.nodes ?? [];
export const edgesOf = (doc: GraphDoc): GraphEdge[] => doc.edges ?? [];
export const portOf = (edge: GraphEdge): string => edge.from.port ?? "out";

/** An edge's identity on the canvas: the graph gives edges no id. */
export const edgeId = (edge: GraphEdge): string => `${edge.from.node}:${portOf(edge)}->${edge.to.node}`;

export const pos = (node: GraphNode): { x: number; y: number } => ({ x: node.position?.x ?? 0, y: node.position?.y ?? 0 });

/** A step's ports, in the canvas's order: one per entry of its type's dynamic field (in the config's order), then
 * the type's own, then `error` when the step routes its errors there. A type the palette doesn't know has none. */
export function portsOf(node: GraphNode, type: NodeType | undefined): string[] {
  const ports: string[] = [];
  const add = (port: unknown) => typeof port === "string" && !ports.includes(port) && ports.push(port);
  if (type?.dynamic_ports) {
    const entries = (node.config ?? {})[type.dynamic_ports];
    if (Array.isArray(entries)) for (const entry of entries) add((entry as { port?: unknown } | null)?.port);
  }
  for (const port of type?.ports ?? []) add(port);
  if (node.options?.on_error === "port") add("error");
  return ports;
}

/** The port that carries the flow on when a step goes mid-edge (4b ruling 10): `out`, or a loop's `done`. */
export function continuationPort(type: NodeType): string | null {
  if (type.ports.includes("out")) return "out";
  if (type.ports.includes("done")) return "done";
  return null;
}

/** A key from the type's last name segment (`flow.transform` → `transform`), numbered when taken. */
export function keyFor(type: NodeType, taken: Iterable<string>): string {
  const used = new Set(taken);
  let base = (type.type.split(".").pop() ?? "").toLowerCase().replace(/[^a-z0-9_]/g, "_").replace(/^[^a-z]+/, "").slice(0, 56);
  if (!KEY.test(base)) base = "step";
  if (!used.has(base)) return base;
  for (let n = 2; ; n++) if (!used.has(`${base}_${n}`)) return `${base}_${n}`;
}

/** The config's top-level defaults from the type's schema; a connection field gets none (4b ruling 11). */
export function defaultConfig(type: NodeType): Record<string, unknown> {
  const properties = (type.config_schema as { properties?: Record<string, Record<string, unknown>> }).properties ?? {};
  const config: Record<string, unknown> = {};
  for (const [name, spec] of Object.entries(properties)) {
    if ("default" in spec && !spec["x-dewpoint-connection"]) config[name] = structuredClone(spec.default);
  }
  return config;
}

function newNode(type: NodeType, doc: GraphDoc, at: { x: number; y: number }, id: string): GraphNode {
  return {
    id,
    key: keyFor(type, nodesOf(doc).map((n) => n.key)),
    type: type.ref,
    config: defaultConfig(type),
    position: { x: Math.round(at.x), y: Math.round(at.y) },
  };
}

/** Steps no edge leads to: where a run starts. */
export function entries(doc: GraphDoc): GraphNode[] {
  const targets = new Set(edgesOf(doc).map((e) => e.to.node));
  return nodesOf(doc).filter((n) => !targets.has(n.id));
}

/** The start card: a row above the entry steps (or all steps, when a cycle leaves none), at their left. */
export function startPosition(doc: GraphDoc): { x: number; y: number } {
  const first = entries(doc).length ? entries(doc) : nodesOf(doc);
  if (first.length === 0) return { x: 0, y: 0 };
  return { x: Math.min(...first.map((n) => pos(n).x)), y: Math.min(...first.map((n) => pos(n).y)) - ROW };
}

const findNode = (doc: GraphDoc, id: string) => nodesOf(doc).find((n) => n.id === id);
const newId = () => crypto.randomUUID();

/** A step after a port, below its source and right of the port's other targets; or, from the start card (`null`),
 * a new entry step beside the others. */
export function addAfter(doc: GraphDoc, from: PortRef | null, type: NodeType, id: string = newId()) {
  const source = from ? findNode(doc, from.node) : undefined;
  const base = source ? pos(source) : startPosition(doc);
  const beside = from ? edgesOf(doc).filter((e) => e.from.node === from.node).length : entries(doc).length;
  const node = newNode(type, doc, { x: base.x + beside * COLUMN, y: base.y + ROW }, id);
  const edges = from ? [...edgesOf(doc), { from: { node: from.node, port: from.port }, to: { node: node.id } }] : edgesOf(doc);
  return { doc: { ...doc, nodes: [...nodesOf(doc), node], edges }, node };
}

/** Every step at or below `y` moves down a row: room for a step inserted there. */
function makeRoom(doc: GraphDoc, y: number): GraphNode[] {
  return nodesOf(doc).map((n) => (pos(n).y >= y ? { ...n, position: { ...pos(n), y: pos(n).y + ROW } } : n));
}

/** A step mid-edge: the edge now reaches it, and its continuation port reaches the old target (4b ruling 10). */
export function insertOnEdge(doc: GraphDoc, edge: GraphEdge, type: NodeType, id: string = newId()) {
  const port = continuationPort(type);
  if (!port) return null;
  const source = findNode(doc, edge.from.node);
  const target = findNode(doc, edge.to.node);
  const y = (source ? pos(source).y : startPosition(doc).y) + ROW;
  const node = newNode(type, doc, { x: target ? pos(target).x : source ? pos(source).x : 0, y }, id);
  const edges = edgesOf(doc).filter((e) => edgeId(e) !== edgeId(edge));
  edges.push({ from: edge.from, to: { node: node.id } }, { from: { node: node.id, port }, to: edge.to });
  return { doc: { ...doc, nodes: [...makeRoom(doc, y), node], edges }, node };
}

/** A step between the start card and an entry step, which it now leads to. */
export function insertBeforeEntry(doc: GraphDoc, entryId: string, type: NodeType, id: string = newId()) {
  const port = continuationPort(type);
  const entry = findNode(doc, entryId);
  if (!port || !entry) return null;
  const at = pos(entry);
  const node = newNode(type, doc, at, id);
  return {
    doc: { ...doc, nodes: [...makeRoom(doc, at.y), node], edges: [...edgesOf(doc), { from: { node: node.id, port }, to: { node: entryId } }] },
    node,
  };
}

/** A step removed with its edges and its declassify entries; with exactly one edge in and one out, its predecessor
 * now leads to its successor (`healed`, 4b ruling 12). References to it elsewhere stay: the validator reports them. */
export function deleteNode(doc: GraphDoc, id: string): { doc: GraphDoc; healed: GraphEdge | null } {
  const inbound = edgesOf(doc).filter((e) => e.to.node === id);
  const outbound = edgesOf(doc).filter((e) => e.from.node === id);
  const edges = edgesOf(doc).filter((e) => e.to.node !== id && e.from.node !== id);
  let healed: GraphEdge | null = null;
  if (inbound.length === 1 && outbound.length === 1) {
    const candidate = { from: inbound[0]!.from, to: outbound[0]!.to };
    if (candidate.to.node !== candidate.from.node && !edges.some((e) => edgeId(e) === edgeId(candidate))) {
      healed = candidate;
      edges.push(candidate);
    }
  }
  const settings = doc.settings?.declassify
    ? { ...doc.settings, declassify: doc.settings.declassify.filter((d) => d.node !== id) }
    : doc.settings;
  return { doc: { ...doc, nodes: nodesOf(doc).filter((n) => n.id !== id), edges, ...(settings ? { settings } : {}) }, healed };
}

export function deleteEdge(doc: GraphDoc, edge: GraphEdge): GraphDoc {
  return { ...doc, edges: edgesOf(doc).filter((e) => edgeId(e) !== edgeId(edge)) };
}

/** Whether `to` is reachable from `from` along edges. */
export function reaches(doc: GraphDoc, from: string, to: string): boolean {
  const next = new Map<string, string[]>();
  for (const e of edgesOf(doc)) next.set(e.from.node, [...(next.get(e.from.node) ?? []), e.to.node]);
  const seen = new Set<string>();
  const stack = [from];
  while (stack.length) {
    const at = stack.pop()!;
    if (at === to) return true;
    if (seen.has(at)) continue;
    seen.add(at);
    stack.push(...(next.get(at) ?? []));
  }
  return false;
}

/** A new edge from a port to a step: never to itself, never twice, never closing a cycle (4b ruling 14). */
export function canConnect(doc: GraphDoc, from: PortRef, to: string): boolean {
  if (from.node === to || !findNode(doc, to)) return false;
  if (edgesOf(doc).some((e) => e.from.node === from.node && portOf(e) === from.port && e.to.node === to)) return false;
  return !reaches(doc, to, from.node);
}

export function connect(doc: GraphDoc, from: PortRef, to: string): GraphDoc | null {
  if (!canConnect(doc, from, to)) return null;
  return { ...doc, edges: [...edgesOf(doc), { from: { node: from.node, port: from.port }, to: { node: to } }] };
}

/** The edges the canvas draws and the keyboard walks: both ends exist, each once. An imported draft may hold an edge
 * to a step that isn't there, or the same edge twice; the validator reports them, and nothing draws them. */
export function drawableEdges(doc: GraphDoc): GraphEdge[] {
  const ids = new Set(nodesOf(doc).map((n) => n.id));
  const seen = new Set<string>();
  return edgesOf(doc).filter((e) => {
    const id = edgeId(e);
    if (!ids.has(e.from.node) || !ids.has(e.to.node) || seen.has(id)) return false;
    seen.add(id);
    return true;
  });
}

/** Steps moved to whole-pixel positions; every other step is the same object as before. */
export function moveNodes(doc: GraphDoc, positions: Map<string, { x: number; y: number }>): GraphDoc {
  return {
    ...doc,
    nodes: nodesOf(doc).map((n) => {
      const p = positions.get(n.id);
      return p ? { ...n, position: { x: Math.round(p.x), y: Math.round(p.y) } } : n;
    }),
  };
}
```

The generated `GraphSettings["declassify"]` is a list of `{node, field}`; if `schema.d.ts` names its item type
differently, `deleteNode` still compiles (it reads `d.node`).

- [ ] **Step 4: Run them to see them pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib/graph.test.ts src/lib/history.test.ts && npx -y pnpm@12.6.0 typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/graph.ts frontend/src/lib/graph.test.ts frontend/src/lib/history.ts frontend/src/lib/history.test.ts
git commit -m "feat(web): the draft as a document, changed only by pure operations, with local undo (4b)"
```

### Task 10: Auto layout with dagre

**Files:**
- Create: `frontend/src/lib/layout.ts`, `frontend/src/lib/layout.test.ts`

**Interfaces:**
- Consumes: `@dagrejs/dagre` 3.1.1; `START`, `ROW`, `entries`, `nodesOf`, `edgesOf` (Task 9).
- Produces: `CARD = { width: 260, height: 64 }`; `layout(doc) -> Map<nodeId, {x, y}>`: top-left positions, top to
  bottom, the start card's row at y = 0 so entry steps sit at y = `ROW`.

- [ ] **Step 1: Check dagre's API in the installed package** (owner's rule: never from memory). Open
  `frontend/node_modules/@dagrejs/dagre/package.json` (its `exports`/`module`) and its type declarations: confirm the
  default export exposes `graphlib.Graph`, `setGraph`, `setDefaultEdgeLabel`, `setNode`, `setEdge`, `hasNode`, `node`,
  and `layout(g)`, and that `node(id)` gives a centre `{x, y}`. Adjust the import below to what it exports.

- [ ] **Step 2: Write the failing test**

`frontend/src/lib/layout.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { ROW } from "./graph";
import { layout } from "./layout";
import type { GraphDoc } from "./workflows";

const n = (id: string) => ({ id, key: id, type: "flow.transform@1", position: { x: 900, y: 900 } });
const e = (from: string, to: string, port = "out") => ({ from: { node: from, port }, to: { node: to } });

it("lays a chain out top to bottom, a row apart, below the start card", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [n("a"), n("b"), n("c")], edges: [e("a", "b"), e("b", "c")] };
  const at = layout(doc);
  expect([at.get("a")!.y, at.get("b")!.y, at.get("c")!.y]).toEqual([ROW, 2 * ROW, 3 * ROW]);
  expect(new Set([at.get("a")!.x, at.get("b")!.x, at.get("c")!.x]).size).toBe(1);
});

it("puts a branch's two sides on one row, apart", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [n("if"), n("yes"), n("no")], edges: [e("if", "yes", "true"), e("if", "no", "false")] };
  const at = layout(doc);
  expect(at.get("yes")!.y).toBe(at.get("no")!.y);
  expect(Math.abs(at.get("yes")!.x - at.get("no")!.x)).toBeGreaterThanOrEqual(260);
});

it("places every step, ignores an edge to a missing one, and gives the same answer twice", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [n("a"), n("lonely")], edges: [e("a", "ghost")] };
  expect([...layout(doc).keys()].sort()).toEqual(["a", "lonely"]);
  expect([...layout(doc)]).toEqual([...layout(doc)]);
});
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib/layout.test.ts`
Expected: FAIL: `layout.ts` doesn't exist.

- [ ] **Step 4: Implement**

`frontend/src/lib/layout.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// Auto layout, on demand (outline §2): dagre, top to bottom. Every card, the start card included, is 260 by 64, and
// rows are 76 apart, so one row is ROW (140) from the next and the start card's row sits at y = 0.
import dagre from "@dagrejs/dagre";
import { START, edgesOf, entries, nodesOf } from "./graph";
import type { GraphDoc } from "./workflows";

export const CARD = { width: 260, height: 64 };

export function layout(doc: GraphDoc): Map<string, { x: number; y: number }> {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "TB", nodesep: 40, ranksep: 76, marginx: 0, marginy: 0 });
  g.setDefaultEdgeLabel(() => ({}));
  g.setNode(START, { ...CARD });
  for (const node of nodesOf(doc)) g.setNode(node.id, { ...CARD });
  for (const node of entries(doc)) g.setEdge(START, node.id);
  for (const edge of edgesOf(doc)) {
    if (g.hasNode(edge.from.node) && g.hasNode(edge.to.node)) g.setEdge(edge.from.node, edge.to.node);
  }
  dagre.layout(g);
  const start = g.node(START);
  const left = start.x - CARD.width / 2;
  const top = start.y - CARD.height / 2;
  const out = new Map<string, { x: number; y: number }>();
  for (const node of nodesOf(doc)) {
    const at = g.node(node.id);
    out.set(node.id, { x: Math.round(at.x - CARD.width / 2 - left), y: Math.round(at.y - CARD.height / 2 - top) });
  }
  return out;
}
```

- [ ] **Step 5: Run it to see it pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib/layout.test.ts && npx -y pnpm@12.6.0 typecheck`
Expected: PASS. (If dagre's `nodesep` puts two siblings closer than a card's width, raise it until the branch test
holds; record the value in a mid-slice ruling.)

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/layout.ts frontend/src/lib/layout.test.ts
git commit -m "feat(web): auto layout with dagre, top to bottom, a row per rank (4b)"
```

### Task 11: The canvas: React Flow under the CSP, a start card, steps without tinted tiles, "+" on edges and free ports, the step picker

**Files:**
- Create: `frontend/src/routes/editor/items.ts`, `frontend/src/routes/editor/StepCard.tsx`,
  `frontend/src/routes/editor/StartCard.tsx`, `frontend/src/routes/editor/FlowEdge.tsx`,
  `frontend/src/routes/editor/Canvas.tsx`, `frontend/src/routes/editor/canvas.css`,
  `frontend/src/routes/editor/StepPicker.tsx`, `frontend/src/routes/editor/Toolbar.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/components/CommandPalette.tsx` (export its item and
  group classes)
- Create: `frontend/src/routes/editor/StepCard.test.tsx`, `frontend/src/routes/editor/StepPicker.test.tsx`,
  `frontend/src/routes/editor/Editor.test.tsx`
- Create: `frontend/e2e/workflows.spec.ts`, `frontend/e2e/state.ts`
- Modify: `frontend/playwright.config.ts` (projects), `frontend/e2e/foundations.spec.ts` (saves the signed-in state)
- Modify (session scratchpad, not the repo): the isolated stack's `reset.sh` runs `dewpoint plugins sync` as the admin
  login after `admin init`, as CI's e2e job does (`.github/workflows/ci.yml:143-146`)

**Interfaces:**
- Consumes: `@xyflow/react` 12.12.0 (`ReactFlow`, `ReactFlowProvider`, `Background`, `BackgroundVariant`, `MiniMap`,
  `Handle`, `Position`, `BaseEdge`, `EdgeLabelRenderer`, `getSmoothStepPath`, `applyNodeChanges`, `useReactFlow`,
  `useViewport`, types `Node`, `Edge`, `NodeProps`, `EdgeProps`, `NodeChange`, `NodeTypes`, `EdgeTypes`); Task 9's
  operations; Task 10's `layout`.
- Produces: `item` (ids: `start`, `node:<id>`, `edge:<from>:<port>-><to>`, `entry:<id>`, `port:<node>:<port>`),
  `type ItemAction = {kind: "open", node} | {kind: "after", from: PortRef | null} | {kind: "insert", edge} | {kind:
  "before", entry}`; `<Canvas doc types problems separate editable
  current focusId focusRequest onFocusItem onItem onMove onConnect onLayout onKeyDown? />`; `<StepCardBody />`;
  `typeCode(ref)`; `<StepPicker mode types onPick onConnect? onClose />`, `type PickMode = {kind: "after", from:
  PortRef | null} | {kind: "insert", edge} | {kind: "before", entry}`; `<Toolbar tenantId name>{actions}</Toolbar>`;
  `PALETTE_ITEM`, `PALETTE_GROUP` exported from `CommandPalette.tsx`; `ADMIN_STATE` in `e2e/state.ts`.

- [ ] **Step 1: Check React Flow's API and class names in the installed package** (owner's rule). In
  `frontend/node_modules/@xyflow/react/dist/`, confirm: the exports named above; the props `nodesFocusable`,
  `edgesFocusable`, `disableKeyboardA11y`, `deleteKeyCode`, `selectionKeyCode`, `multiSelectionKeyCode`,
  `panActivationKeyCode`, `zoomActivationKeyCode`, `elementsSelectable`, `proOptions.hideAttribution`,
  `onNodeDragStop(event, node, nodes)`; `MiniMap`'s `ariaLabel` and `nodeClassName`; and, in `dist/base.css`, the
  classes `canvas.css` restyles (`react-flow__background`, `react-flow__minimap`, `react-flow__minimap-mask`,
  `react-flow__edge-path`, `react-flow__handle`). Note any difference in a mid-slice ruling and use the installed one.

- [ ] **Step 2: Write the failing unit tests**

`frontend/src/routes/editor/StepCard.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { StepCardBody, typeCode } from "./StepCard";

const node = { id: "n1", key: "get_device", type: "flow.transform@1" };
const TRANSFORM = { ref: "flow.transform@1", type: "flow.transform", title: "Transform" } as never;

it("names a step by its key, its type and its problems, its code a plain mono label (no tinted tile)", () => {
  render(<StepCardBody node={node} type={TRANSFORM} problems={{ errors: 2, warnings: 0 }} separate={1} current={false} tabIndex={0} onOpen={vi.fn()} />);
  const card = screen.getByRole("button", { name: "get_device, Transform, 2 problems, 1 expression runs as a separate step" });
  expect(card.getAttribute("data-item")).toBe("node:n1");
  expect(card.textContent).toContain("MAP");
  expect(card.innerHTML).not.toMatch(/bg-accent-soft/);
});

it("says a step's type is unknown, and draws its card dashed", () => {
  render(<StepCardBody node={{ ...node, type: "vendor.thing@3" }} type={undefined} problems={{ errors: 0, warnings: 0 }} separate={0} current={false} tabIndex={-1} onOpen={vi.fn()} />);
  const card = screen.getByRole("button", { name: "get_device, Unknown step type vendor.thing@3" });
  expect(card.className).toMatch(/border-dashed/);
});

it("marks the step whose panel is open with a 2 px outline, never a halo", () => {
  render(<StepCardBody node={node} type={TRANSFORM} problems={{ errors: 0, warnings: 0 }} separate={0} current tabIndex={0} onOpen={vi.fn()} />);
  const card = screen.getByRole("button");
  expect(card.className).toMatch(/outline-2/);
  expect(card.className).not.toMatch(/ring-[3-9]|shadow-\[/);
});

it("codes control steps by what they do and actions by their plugin", () => {
  expect([typeCode("flow.if@1"), typeCode("flow.loop@1"), typeCode("testkit.http_call@1")]).toEqual(["IF", "LOOP", "TESTKI"]);
});
```

`frontend/src/routes/editor/StepPicker.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { StepPicker } from "./StepPicker";

const t = (ref: string, kind: "control" | "action", ports: string[], extra = {}) => ({
  ref, type: ref.split("@")[0], version: 1, kind, state: "active", title: ref.split("@")[0].split(".").pop(), description: `does ${ref}`,
  ports, dynamic_ports: null, config_schema: {}, output_schema: {}, side_effect: "none", credentials: [], capabilities: [],
  retry: { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] }, timeout_s: 60, ...extra,
}) as never;  // prettier-ignore
const TYPES = [
  t("flow.transform@1", "control", ["out"]),
  t("flow.if@1", "control", ["true", "false"]),
  t("flow.old@1", "control", ["out"], { state: "deprecated" }),
  t("testkit.http_call@1", "action", ["out"], { side_effect: "idempotent", credentials: ["testkit"] }),
];
const EDGE = { from: { node: "a", port: "out" }, to: { node: "b" } };

it("offers every active type after a port, in Flow and Actions, with what an action changes and needs", async () => {
  const onPick = vi.fn();
  render(<StepPicker mode={{ kind: "after", from: { node: "a", port: "out" } }} types={TYPES} onPick={onPick} onConnect={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
  expect(screen.queryByRole("option", { name: /flow\.old@1/ })).toBeNull(); // deprecated: new versions shouldn't use it
  const call = screen.getByRole("option", { name: /testkit\.http_call@1/ });
  expect(call.textContent).toContain("Changes things; safe to repeat");
  expect(call.textContent).toContain("Uses a testkit connection");
  await userEvent.click(screen.getByRole("option", { name: /flow\.if@1/ }));
  expect(onPick).toHaveBeenCalledWith(TYPES[1]);
});

it("offers only steps that continue the flow mid-edge, and says why", () => {
  render(<StepPicker mode={{ kind: "insert", edge: EDGE }} types={TYPES} onPick={vi.fn()} onClose={vi.fn()} />);
  expect(screen.queryByRole("option", { name: /flow\.if@1/ })).toBeNull();
  expect(screen.getByRole("option", { name: /flow\.transform@1/ })).toBeTruthy();
  expect(screen.getByText("Only steps that continue the flow can go here.")).toBeTruthy();
});

it("offers to connect an existing step instead, after a port", async () => {
  const onConnect = vi.fn();
  render(<StepPicker mode={{ kind: "after", from: { node: "a", port: "out" } }} types={TYPES} onPick={vi.fn()} onConnect={onConnect} onClose={vi.fn()} />);
  await userEvent.click(screen.getByRole("option", { name: "Connect to an existing step…" }));
  expect(onConnect).toHaveBeenCalled();
});
```

`frontend/src/routes/editor/Editor.test.tsx` (the canvas itself is the browser gate's: here a stand-in draws the items
the editor hands it, each step with a button that opens it and one that adds after it, honours focus requests,
passes keys through, and records each document it was handed with whether it was editable and how many steps carried
problems, so the editor's own logic runs in jsdom. The editor sits on its route beside the list's, so leaving it is a
real navigation. Tasks 12–15 add tests, and answers to `answers`, to it):

```tsx
// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Outlet, RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import type { CanvasProps } from "./Canvas";
import { EditorPage } from "./Editor";

// Every document the stand-in canvas was handed: what was drawn, and what never was.
const { drawn } = vi.hoisted(() => ({ drawn: [] as { doc: GraphDoc; editable: boolean }[] }));

vi.mock("./Canvas", async () => {
  const { useEffect } = await import("react");
  return {
    Canvas: (props: CanvasProps) => {
      drawn.push({ doc: props.doc, editable: props.editable });
      useEffect(() => {
        if (props.focusRequest) document.querySelector<HTMLElement>(`[data-item="${props.focusRequest.id}"]`)?.focus();
      }, [props.focusRequest]);
      return (
        <div
          role="group"
          aria-label="Workflow steps"
          onKeyDown={props.onKeyDown}
          data-editable={String(props.editable)}
          data-problems={String(props.problems.size)}
        >
          <button data-item="start" onClick={() => props.onItem({ kind: "after", from: null })}>Start</button>
          {(props.doc.nodes ?? []).map((n) => (
            <span key={n.id}>
              <button data-item={`node:${n.id}`} onClick={() => props.onItem({ kind: "open", node: n.id })}>{n.key}</button>
              <button onClick={() => props.onItem({ kind: "after", from: { node: n.id, port: "out" } })}>after {n.key}</button>
            </span>
          ))}
        </div>
      );
    },
  };
});

const TYPES = [{
  ref: "flow.transform@1", type: "flow.transform", version: 1, kind: "control", state: "active", title: "Transform",
  description: "", ports: ["out"], dynamic_ports: null, config_schema: {}, output_schema: {}, side_effect: "none",
  credentials: [], capabilities: [], retry: { max_attempts: 3, initial_interval_s: 1, backoff: 2, max_interval_s: 60, non_retryable: [] }, timeout_s: 60,
}];  // prettier-ignore
/** A draft of transform steps with these keys, one under the other. */
const draftWith = (...keys: string[]): GraphDoc => ({
  graph_format: 1,
  nodes: keys.map((key, i) => ({ id: `id-${key}`, key, type: "flow.transform@1", position: { x: 0, y: 140 * (i + 1) } })),
  edges: [],
});
const WORKFLOW = {
  id: "w1", name: "Nightly", enabled: true, draft_revision: 1, active_version_id: null, active_version_number: null,
  executable: null, blocked_by: [], created_at: "", updated_at: "", unpublished_changes: true, draft_graph_hash: "h1",
  last_run: null, last_simulation: null, runs_24h: { live: 0, simulate: 0 }, needs_attention: [], draft: draftWith(),
};  // prettier-ignore
const BASE = "/api/v1/t/t1/workflows/w1";
type Answer = () => Response | Promise<Response>;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
let role = "editor";
let answers: Map<string, Answer>; // "METHOD path" → its answer: a test sets what it needs
let sent: { method: string; path: string; headers: Headers; body: unknown }[];

beforeEach(() => {
  role = "editor";
  drawn.length = 0;
  sent = [];
  answers = new Map<string, Answer>([
    ["GET /api/v1/node-types", () => json(TYPES)],
    ["GET /api/v1/t/t1", () => json({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role })],
    [`GET ${BASE}`, () => json(WORKFLOW)],
    [`POST ${BASE}/validate`, () => json({ draft_revision: 1, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] } })],
  ]);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, headers: request.headers, body: text ? JSON.parse(text) : null });
    const answer = answers.get(`${request.method} ${path}`);
    return answer ? answer() : json({ error: "not_found" }, 404);
  });
});

/** The editor on its route, beside the list's; `seed` fills the query cache first, as an earlier visit would. */
async function show({ seed }: { seed?: (qc: QueryClient) => void } = {}) {
  const root = createRootRoute({ component: Outlet });
  const list = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows", component: () => <p>list</p> });
  const editor = createRoute({
    getParentRoute: () => root,
    path: "/t/$tenantId/workflows/$workflowId",
    component: () => <EditorPage tenantId="t1" workflowId="w1" />,
  });
  const router = createRouter({
    routeTree: root.addChildren([list, editor]),
    history: createMemoryHistory({ initialEntries: ["/t/t1/workflows/w1"] }),
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seed?.(qc);
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("group", { name: "Workflow steps" });
  return { router, qc };
}

it("heads the editor with the way back and the workflow's name", async () => {
  await show();
  expect(screen.getByRole("link", { name: "Workflows" })).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1, name: "Nightly" })).toBeTruthy();
});

it("adds a first step from the start card, then one after it, through the picker", async () => {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(await screen.findByRole("button", { name: "after transform" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
});

it("offers a viewer no Add step", async () => {
  role = "viewer";
  await show();
  expect(screen.queryByRole("button", { name: /Add step/ })).toBeNull();
});
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL: the modules don't exist; the editor has no toolbar or canvas.

- [ ] **Step 4: Implement the items, the cards and the edge**

`frontend/src/routes/editor/items.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// The canvas's items: what its one roving tab stop moves among (4b ruling 15), and what each action targets.
import { START, edgeId, type PortRef } from "../../lib/graph";
import type { GraphEdge } from "../../lib/workflows";

export const item = {
  start: START,
  node: (id: string) => `node:${id}`,
  edge: (edge: GraphEdge) => `edge:${edgeId(edge)}`,
  entry: (id: string) => `entry:${id}`,
  port: (node: string, port: string) => `port:${node}:${port}`,
};

export type ItemAction =
  | { kind: "open"; node: string }
  | { kind: "after"; from: PortRef | null }
  | { kind: "insert"; edge: GraphEdge }
  | { kind: "before"; entry: string };
```

`frontend/src/routes/editor/StepCard.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A step on the canvas (1c, its tells stripped: outline §6). No tinted icon tile: the type's mono code; the step
// whose panel is open has a 2 px outline, never a halo; an unknown type draws dashed and says so.
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Fragment } from "react";
import type { PortRef } from "../../lib/graph";
import type { GraphNode, NodeType } from "../../lib/workflows";
import { item, type ItemAction } from "./items";

const CODES: Record<string, string> = {
  "flow.if": "IF", "flow.switch": "SWITCH", "flow.loop": "LOOP", "flow.filter": "FILTER", "flow.set_variables": "SET",
  "flow.delay": "DELAY", "flow.wait_until": "WAIT", "flow.stop": "STOP", "flow.fail": "FAIL", "flow.run_workflow": "FLOW",
  "flow.transform": "MAP",
};  // prettier-ignore

/** A control step's code says what it does; an action's names its plugin. */
export function typeCode(ref: string): string {
  const type = ref.split("@")[0] ?? ref;
  return CODES[type] ?? (type.split(".")[0] ?? "").toUpperCase().slice(0, 6);
}

export type Problems = { errors: number; warnings: number };
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function StepCardBody({
  node, type, problems, separate, current, tabIndex, onOpen,
}: {
  node: GraphNode; type: NodeType | undefined; problems: Problems; separate: number; current: boolean; tabIndex: number;
  onOpen: () => void;
}) {  // prettier-ignore
  const title = type ? type.title : `Unknown step type ${node.type}`;
  const said = [
    node.key,
    title,
    problems.errors ? plural(problems.errors, "problem", "problems") : null,
    !problems.errors && problems.warnings ? plural(problems.warnings, "warning", "warnings") : null,
    separate ? `${plural(separate, "expression runs", "expressions run")} as a separate step` : null,
  ].filter(Boolean);
  const border = current ? "border-accent outline-2 outline-offset-2 outline-accent" : "border-line-strong";
  return (
    <button
      type="button"
      data-item={item.node(node.id)}
      tabIndex={tabIndex}
      aria-label={said.join(", ")}
      onClick={onOpen}
      className={`flex h-16 w-[260px] items-center gap-3 rounded-lg border bg-surface px-3.5 text-left shadow-node ${border} ${type ? "" : "border-dashed"}`}
    >
      <span aria-hidden="true" className="w-12 shrink-0 truncate font-mono text-meta font-semibold text-accent-ink">{typeCode(node.type)}</span>
      <span className="min-w-0 flex-1" aria-hidden="true">
        <span className="block truncate text-body font-semibold">{node.key}</span>
        <span className={`block truncate text-small ${type ? "text-muted" : "text-warn-ink"}`}>{title}</span>
      </span>
      {(problems.errors > 0 || problems.warnings > 0) && (
        <span
          aria-hidden="true"
          className={`shrink-0 rounded-sm border px-1.5 font-mono text-meta ${problems.errors ? "border-danger text-danger" : "border-warn-line bg-warn-bg text-warn-ink"}`}
        >
          {problems.errors || problems.warnings}
        </span>
      )}
    </button>
  );
}

export type StepData = {
  node: GraphNode;
  type: NodeType | undefined;
  ports: string[];
  connected: string[];
  problems: Problems;
  separate: number;
  current: boolean;
  focusId: string;
  editable: boolean;
  onItem: (action: ItemAction) => void;
};

const PLUS = "nodrag nopan absolute top-full mt-6 grid size-6 -translate-x-1/2 place-items-center rounded-sm border border-line-strong bg-surface text-body text-muted hover:bg-surface-hover";

/** The React Flow node: the card, its input on top, a handle per port at the bottom (and one for an edge from a
 * port the type no longer has), each port named when it isn't the only `out`, and a "+" under each free port. */
export function StepNode({ data }: NodeProps<Node<StepData, "step">>) {
  const { node, ports, connected, editable } = data;
  const named = ports.length > 1 || (ports[0] !== undefined && ports[0] !== "out");
  const extra = connected.filter((p) => !ports.includes(p));
  const at = (i: number) => `${((i + 1) / (ports.length + 1)) * 100}%`;
  return (
    <div className="relative">
      <Handle type="target" position={Position.Top} isConnectable={editable} />
      <StepCardBody
        node={node}
        type={data.type}
        problems={data.problems}
        separate={data.separate}
        current={data.current}
        tabIndex={data.focusId === item.node(node.id) ? 0 : -1}
        onOpen={() => data.onItem({ kind: "open", node: node.id })}
      />
      {ports.map((port, i) => {
        const from: PortRef = { node: node.id, port };
        const id = item.port(node.id, port);
        return (
          <Fragment key={port}>
            <Handle type="source" id={port} position={Position.Bottom} isConnectable={editable} style={{ left: at(i) }} />
            {named && (
              <span aria-hidden="true" className="pointer-events-none absolute top-full mt-1 -translate-x-1/2 font-mono text-meta text-muted" style={{ left: at(i) }}>
                {port}
              </span>
            )}
            {editable && !connected.includes(port) && (
              <button
                type="button"
                data-item={id}
                tabIndex={data.focusId === id ? 0 : -1}
                aria-label={`Add a step after ${node.key}${port === "out" ? "" : ` (${port})`}`}
                onClick={() => data.onItem({ kind: "after", from })}
                className={PLUS}
                style={{ left: at(i) }}
              >
                ＋
              </button>
            )}
          </Fragment>
        );
      })}
      {extra.map((port) => (
        <Handle key={port} type="source" id={port} position={Position.Bottom} isConnectable={false} className="opacity-0" />
      ))}
    </div>
  );
}
```

`frontend/src/routes/editor/StartCard.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The start card (4b ruling 2): not a graph node. It stands for whatever starts a run; its edges reach every entry
// step, and, before any step exists, its "+" adds the first one.
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { START } from "../../lib/graph";
import { item, type ItemAction } from "./items";

export type StartData = { empty: boolean; focusId: string; editable: boolean; onItem: (action: ItemAction) => void };

export function StartNode({ data }: NodeProps<Node<StartData, "start">>) {
  const first = item.port(START, "out");
  return (
    <div className="relative">
      <button
        type="button"
        data-item={item.start}
        tabIndex={data.focusId === item.start ? 0 : -1}
        aria-label={data.editable ? "Start, where every run begins. Add a step that runs first" : "Start, where every run begins"}
        onClick={() => data.editable && data.onItem({ kind: "after", from: null })}
        className="flex h-16 w-[260px] flex-col justify-center rounded-lg border border-dashed border-line-strong bg-surface px-3.5 text-left"
      >
        <span className="text-body font-semibold">Start</span>
        <span className="text-small text-muted">By hand, on a schedule or from a webhook</span>
      </button>
      <Handle type="source" id="out" position={Position.Bottom} isConnectable={false} />
      {data.empty && data.editable && (
        <button
          type="button"
          data-item={first}
          tabIndex={data.focusId === first ? 0 : -1}
          aria-label="Add the first step"
          onClick={() => data.onItem({ kind: "after", from: null })}
          className="nodrag nopan absolute top-full left-1/2 mt-6 grid size-6 -translate-x-1/2 place-items-center rounded-sm border border-line-strong bg-surface text-body text-muted hover:bg-surface-hover"
        >
          ＋
        </button>
      )}
    </div>
  );
}
```

`frontend/src/routes/editor/FlowEdge.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// An edge: a stepped line, and, when the draft is editable, a "+" at its middle to insert a step there (a 24 px
// square with a 4 px radius: no circles, outline §6).
import { BaseEdge, EdgeLabelRenderer, getSmoothStepPath, type Edge, type EdgeProps } from "@xyflow/react";
import type { ItemAction } from "./items";

export type FlowData = { item: string; label: string; action: ItemAction; focusId: string; editable: boolean; onItem: (action: ItemAction) => void };

export function FlowEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data }: EdgeProps<Edge<FlowData, "flow">>) {
  const [path, x, y] = getSmoothStepPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, borderRadius: 6 });
  return (
    <>
      <BaseEdge id={id} path={path} />
      {data?.editable && (
        <EdgeLabelRenderer>
          <button
            type="button"
            data-item={data.item}
            tabIndex={data.focusId === data.item ? 0 : -1}
            aria-label={data.label}
            onClick={() => data.onItem(data.action)}
            className="nodrag nopan pointer-events-auto absolute grid size-6 place-items-center rounded-sm border border-line-strong bg-surface text-body text-muted hover:bg-surface-hover"
            style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }}
          >
            ＋
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
```

React sets these `style` values through the CSSOM, which `style-src 'self'` allows (a CSP refuses inline style
*attributes* and injected `<style>` elements); the browser gate proves it in Step 8.

`frontend/src/routes/editor/canvas.css`:

```css
/* React Flow's structural classes, coloured from our tokens (4b ruling 20): its default theme isn't imported.
   The dots are React Flow's SVG pattern, not a CSS gradient (outline §6). */
.react-flow__background {
  background-color: var(--ground);
}
.react-flow__background circle {
  fill: var(--line-strong);
}
.react-flow__edge-path {
  stroke: var(--line-strong);
  stroke-width: 1.5;
}
.react-flow__handle {
  width: 8px;
  height: 8px;
  border: 1px solid var(--line-control);
  border-radius: 2px;
  background-color: var(--surface);
}
.react-flow__minimap {
  border: 1px solid var(--line);
  border-radius: 6px;
  background-color: var(--surface);
}
.react-flow__minimap-mask {
  fill: var(--surface-2);
  fill-opacity: 0.6;
}
.canvas-minimap-node {
  fill: var(--line-strong);
}
```

- [ ] **Step 5: Implement the canvas**

`frontend/src/routes/editor/Canvas.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The canvas (1c): React Flow draws the document; the editor owns it. React Flow's own keyboard handling is off
// (D16; 4b ruling 15): its arrow keys move nodes, its Delete removes them, and Tab would visit every node. The
// canvas is one roving tab stop instead; Task 12 adds its keys.
import "@xyflow/react/dist/base.css";
import "./canvas.css";
import {
  Background, BackgroundVariant, MiniMap, ReactFlow, ReactFlowProvider, applyNodeChanges, useReactFlow, useViewport,
  type Edge, type EdgeTypes, type Node, type NodeChange, type NodeTypes,
} from "@xyflow/react";  // prettier-ignore
import { useCallback, useEffect, useMemo, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";
import { Button } from "../../components/Button";
import { START, drawableEdges, entries, nodesOf, portOf, portsOf, pos, startPosition, type PortRef } from "../../lib/graph";
import type { GraphDoc, NodeType } from "../../lib/workflows";
import { FlowEdge, type FlowData } from "./FlowEdge";
import { item, type ItemAction } from "./items";
import { StartNode, type StartData } from "./StartCard";
import { StepNode, type Problems, type StepData } from "./StepCard";

const nodeTypes = { step: StepNode, start: StartNode } satisfies NodeTypes;
const edgeTypes = { flow: FlowEdge } satisfies EdgeTypes;
const NONE: Problems = { errors: 0, warnings: 0 };

export interface CanvasProps {
  doc: GraphDoc;
  types: Map<string, NodeType>;
  problems: Map<string, Problems>;
  separate: Map<string, number>;
  editable: boolean;
  current: string | null; // the step whose panel is open
  focusId: string; // the roving tab stop's item
  focusRequest: { id: string; n: number } | null; // move focus there once drawn
  onFocusItem: (id: string) => void;
  onItem: (action: ItemAction) => void;
  onMove: (positions: Map<string, { x: number; y: number }>) => void;
  onConnect: (from: PortRef, to: string) => void;
  onLayout: () => void;
  onKeyDown?: (e: KeyboardEvent<HTMLDivElement>) => void;
}

/** What React Flow draws: the start card, each step, an edge from the start card to each entry step, and each edge
 * whose ends exist, once (`drawableEdges`: an imported draft may hold others, which the problems name). */
function build(p: CanvasProps): { nodes: Node[]; edges: Edge[] } {
  const used = new Map<string, string[]>();
  for (const e of drawableEdges(p.doc)) used.set(e.from.node, [...(used.get(e.from.node) ?? []), portOf(e)]);
  const keyOf = new Map(nodesOf(p.doc).map((n) => [n.id, n.key]));
  const start: StartData = { empty: nodesOf(p.doc).length === 0, focusId: p.focusId, editable: p.editable, onItem: p.onItem };
  const nodes: Node[] = [
    { id: START, type: "start", position: startPosition(p.doc), draggable: false, selectable: false, data: start },
    ...nodesOf(p.doc).map((n): Node => {
      const type = p.types.get(n.type);
      const data: StepData = {
        node: n, type, ports: portsOf(n, type), connected: used.get(n.id) ?? [], problems: p.problems.get(n.id) ?? NONE,
        separate: p.separate.get(n.id) ?? 0, current: p.current === n.id, focusId: p.focusId, editable: p.editable,
        onItem: p.onItem,
      };  // prettier-ignore
      return { id: n.id, type: "step", position: pos(n), draggable: p.editable, selectable: false, data };
    }),
  ];
  const flow = (id: string, label: string, action: ItemAction): FlowData => ({ item: id, label, action, focusId: p.focusId, editable: p.editable, onItem: p.onItem });
  const edges: Edge[] = [
    ...entries(p.doc).map((n): Edge => ({
      id: item.entry(n.id), source: START, sourceHandle: "out", target: n.id, type: "flow",
      data: flow(item.entry(n.id), `Insert a step before ${n.key}`, { kind: "before", entry: n.id }),
    })),
    ...drawableEdges(p.doc).map((e): Edge => ({
      id: item.edge(e), source: e.from.node, sourceHandle: portOf(e), target: e.to.node, type: "flow",
      data: flow(item.edge(e), `Insert a step between ${keyOf.get(e.from.node) ?? "a step"} and ${keyOf.get(e.to.node) ?? "a step"}`, { kind: "insert", edge: e }),
    })),
  ];  // prettier-ignore
  return { nodes, edges };
}

function Flow(p: CanvasProps) {
  const flow = useReactFlow();
  const { zoom } = useViewport();
  const container = useRef<HTMLDivElement>(null);
  const built = useMemo(() => build(p), [p]);
  const [nodes, setNodes] = useState(built.nodes);
  useEffect(() => setNodes(built.nodes), [built.nodes]);
  // Only drags move cards here; the document changes when a drag ends (onNodeDragStop).
  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((ns) => applyNodeChanges(changes.filter((c) => c.type === "position" || c.type === "dimensions"), ns)),
    [],
  );

  /** Brings an item into view when it's outside the canvas, keeping the zoom. */
  const reveal = useCallback(
    (el: HTMLElement) => {
      const box = container.current?.getBoundingClientRect();
      if (!box) return;
      const r = el.getBoundingClientRect();
      if (r.left >= box.left && r.right <= box.right && r.top >= box.top && r.bottom <= box.bottom) return;
      const v = flow.getViewport();
      void flow.setViewport(
        { x: v.x + (box.left + box.width / 2 - (r.left + r.width / 2)), y: v.y + (box.top + box.height / 2 - (r.top + r.height / 2)), zoom: v.zoom },
        { duration: 0 },
      );
    },
    [flow],
  );

  useEffect(() => {
    if (!p.focusRequest) return;
    const id = p.focusRequest.id;
    const frame = requestAnimationFrame(() => {
      const el = container.current?.querySelector<HTMLElement>(`[data-item="${CSS.escape(id)}"]`);
      if (!el) return;
      el.focus({ preventScroll: true });
      reveal(el);
    });
    return () => cancelAnimationFrame(frame);
  }, [p.focusRequest, reveal]);

  function onFocus(e: FocusEvent<HTMLDivElement>) {
    const id = (e.target as HTMLElement).dataset.item;
    if (!id) return;
    p.onFocusItem(id);
    reveal(e.target as HTMLElement);
  }

  return (
    <div ref={container} role="group" aria-label="Workflow steps" onKeyDown={p.onKeyDown} onFocus={onFocus} className="relative min-h-0 min-w-0 flex-1">
      <ReactFlow
        nodes={nodes}
        edges={built.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onNodeDragStop={(_, __, dragged) => p.onMove(new Map(dragged.map((n) => [n.id, n.position])))}
        onConnect={(c) => {
          if (c.source && c.source !== START && c.sourceHandle && c.target) p.onConnect({ node: c.source, port: c.sourceHandle }, c.target);
        }}
        nodesDraggable={p.editable}
        nodesConnectable={p.editable}
        elementsSelectable={false}
        nodesFocusable={false}
        edgesFocusable={false}
        disableKeyboardA11y
        deleteKeyCode={null}
        selectionKeyCode={null}
        multiSelectionKeyCode={null}
        panActivationKeyCode={null}
        zoomActivationKeyCode={null}
        zoomOnDoubleClick={false}
        minZoom={0.25}
        maxZoom={1.5}
        fitView
        fitViewOptions={{ padding: 0.2, maxZoom: 1 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} />
        <MiniMap pannable zoomable ariaLabel="Overview of the steps" nodeClassName="canvas-minimap-node" />
      </ReactFlow>
      <div className="absolute bottom-4 left-4 flex items-center gap-1.5">
        {p.editable && (
          <Button size="md" onClick={p.onLayout}>
            Auto layout
          </Button>
        )}
        <Button size="md" aria-label="Zoom in" onClick={() => void flow.zoomIn({ duration: 0 })}>＋</Button>
        <Button size="md" aria-label="Zoom out" onClick={() => void flow.zoomOut({ duration: 0 })}>−</Button>
        <Button size="md" onClick={() => void flow.fitView({ padding: 0.2, maxZoom: 1, duration: 0 })}>Fit</Button>
        <span className="ml-1.5 font-mono text-small text-muted">{Math.round(zoom * 100)}%</span>
      </div>
    </div>
  );
}

export function Canvas(props: CanvasProps) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
```

- [ ] **Step 6: Implement the picker, the toolbar and the editor**

In `frontend/src/components/CommandPalette.tsx`, rename its `ITEM` and `GROUP` constants to exported
`PALETTE_ITEM` and `PALETTE_GROUP` (every use inside it changes name only).

`frontend/src/routes/editor/StepPicker.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// Choosing a step's type (`A`, and every "+"): a native modal dialog around cmdk, as the palette (D23). Only active
// types: a deprecated one stays drawn where it's used, but new versions shouldn't add it. Mid-edge, only types that
// continue the flow (4b ruling 10).
import { Command } from "cmdk";
import { useEffect, useRef } from "react";
import { PALETTE_GROUP, PALETTE_ITEM } from "../../components/CommandPalette";
import { continuationPort, type PortRef } from "../../lib/graph";
import type { GraphEdge, NodeType } from "../../lib/workflows";

export type PickMode = { kind: "after"; from: PortRef | null } | { kind: "insert"; edge: GraphEdge } | { kind: "before"; entry: string };

const EFFECTS: Record<NodeType["side_effect"], string> = {
  none: "Changes nothing",
  idempotent: "Changes things; safe to repeat",
  keyed: "Changes things once per key",
  reconcilable: "Changes things; checked before a retry",
  ambiguous: "Changes things; a retry may repeat it",
};

function Choice({ type, onSelect }: { type: NodeType; onSelect: () => void }) {
  return (
    <Command.Item value={`${type.title} ${type.ref}`} onSelect={onSelect} className={`${PALETTE_ITEM} flex-col items-start`}>
      <span className="flex w-full items-baseline justify-between gap-3">
        <span className="font-medium">{type.title}</span>
        <span className="font-mono text-meta text-muted">{type.ref}</span>
      </span>
      {type.description && <span className="text-small text-muted">{type.description}</span>}
      {type.kind === "action" && (
        <span className="text-small text-muted">
          {EFFECTS[type.side_effect]}
          {type.credentials.map((c) => `. Uses a ${c} connection`).join("")}
        </span>
      )}
    </Command.Item>
  );
}

export function StepPicker({
  mode, types, onPick, onConnect, onClose,
}: { mode: PickMode; types: NodeType[]; onPick: (type: NodeType) => void; onConnect?: () => void; onClose: () => void }) {  // prettier-ignore
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLInputElement>("[cmdk-input]")?.focus();
    }
  }, []);
  const continuing = mode.kind !== "after";
  const offered = types.filter((t) => t.state === "active" && (!continuing || continuationPort(t) !== null));
  const pick = (type: NodeType) => {
    dialog.current?.close();
    onPick(type);
  };
  return (
    <dialog
      ref={dialog}
      aria-label="Add a step"
      onClose={onClose}
      className="mx-auto mt-20 w-[560px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-0 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <Command label="Add a step" loop>
        <Command.Input
          placeholder="Type a step's name"
          className="w-full rounded-t-dialog border-b border-line bg-transparent px-4 py-3 text-body-lg text-ink placeholder:text-muted focus-visible:-outline-offset-2"
        />
        <Command.List className="max-h-96 overflow-y-auto p-1">
          {continuing && <p className="px-3 pt-2 text-small text-muted">Only steps that continue the flow can go here.</p>}
          <Command.Empty className="px-3 py-2 text-body text-muted">No step type matches.</Command.Empty>
          {offered.some((t) => t.kind === "control") && (
            <Command.Group heading="Flow" className={PALETTE_GROUP}>
              {offered.filter((t) => t.kind === "control").map((t) => <Choice key={t.ref} type={t} onSelect={() => pick(t)} />)}
            </Command.Group>
          )}
          {offered.some((t) => t.kind === "action") && (
            <Command.Group heading="Actions" className={PALETTE_GROUP}>
              {offered.filter((t) => t.kind === "action").map((t) => <Choice key={t.ref} type={t} onSelect={() => pick(t)} />)}
            </Command.Group>
          )}
          {mode.kind === "after" && mode.from && onConnect && (
            <Command.Group heading="Or" className={PALETTE_GROUP}>
              <Command.Item
                value="Connect to an existing step…"
                className={PALETTE_ITEM}
                onSelect={() => {
                  dialog.current?.close();
                  onConnect();
                }}
              >
                Connect to an existing step…
              </Command.Item>
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </dialog>
  );
}
```

`frontend/src/routes/editor/Toolbar.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The editor's toolbar under the shell's header (4b ruling 19): the way back, the workflow's name, then its state
// and actions (Tasks 13-15 add them).
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";

export function Toolbar({ tenantId, name, children }: { tenantId: string; name: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-5 py-2.5">
      <nav aria-label="Breadcrumb">
        <Link to="/t/$tenantId/workflows" params={{ tenantId }} className="text-body text-muted hover:text-ink">
          Workflows
        </Link>
      </nav>
      <span aria-hidden="true" className="text-muted">/</span>
      <h1 className="min-w-0 truncate text-body-lg font-semibold">{name}</h1>
      <div className="grow" />
      {children}
    </div>
  );
}
```

Replace `frontend/src/routes/editor/Editor.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The editor (screen 1c): the draft, on a canvas. Task 12 adds the keyboard, Task 13 saving, Task 14 problems, Task 15
// publishing and versions.
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Button } from "../../components/Button";
import { LoadError } from "../../components/LoadError";
import { announce } from "../../lib/announce";
import {
  START, addAfter, asGraph, connect, insertBeforeEntry, insertOnEdge, moveNodes, nodesOf, type PortRef,
} from "../../lib/graph";  // prettier-ignore
import { begin, record, type History } from "../../lib/history";
import { layout } from "../../lib/layout";
import { useDocumentTitle } from "../../lib/title";
import {
  canEdit, nodeTypesQuery, tenantQuery, workflowQuery, type GraphDoc, type NodeType, type WorkflowDetail,
} from "../../lib/workflows";  // prettier-ignore
import { Canvas } from "./Canvas";
import { item, type ItemAction } from "./items";
import { StepPicker, type PickMode } from "./StepPicker";
import { Toolbar } from "./Toolbar";

export function EditorPage({ tenantId, workflowId }: { tenantId: string; workflowId: string }) {
  const workflow = useQuery(workflowQuery(tenantId, workflowId));
  const types = useQuery(nodeTypesQuery);
  const tenant = useQuery(tenantQuery(tenantId));
  useDocumentTitle(workflow.data?.name ?? "Workflow");
  if (workflow.isError) return <section className="p-6"><LoadError what="This workflow" /></section>;
  if (types.isError) return <section className="p-6"><LoadError what="The step types" /></section>;
  if (!workflow.data || !types.data || !tenant.data) return <p className="p-6 text-body text-muted">Loading…</p>;
  return <Editor tenantId={tenantId} workflow={workflow.data} types={types.data} role={tenant.data.role ?? null} />;
}

function Editor({ tenantId, workflow, types, role }: { tenantId: string; workflow: WorkflowDetail; types: NodeType[]; role: string | null }) {
  const typeMap = useMemo(() => new Map(types.map((t) => [t.ref, t])), [types]);
  const [history, setHistory] = useState<History<GraphDoc>>(() => begin(asGraph(workflow.draft)));
  const doc = history.present;
  const editable = canEdit(role);
  const [focusId, setFocusId] = useState<string>(START);
  const [focusRequest, setFocusRequest] = useState<{ id: string; n: number } | null>(null);
  const [picker, setPicker] = useState<PickMode | null>(null);
  const keyOf = (id: string) => nodesOf(doc).find((n) => n.id === id)?.key ?? "a step";

  function focus(id: string) {
    setFocusId(id);
    setFocusRequest((r) => ({ id, n: (r?.n ?? 0) + 1 }));
  }

  function change(next: GraphDoc, message: string, then?: string) {
    setHistory((h) => record(h, next));
    announce(message);
    if (then) focus(then);
  }

  function onItem(action: ItemAction) {
    if (!editable) return;
    if (action.kind === "after") setPicker({ kind: "after", from: action.from });
    if (action.kind === "insert") setPicker({ kind: "insert", edge: action.edge });
    if (action.kind === "before") setPicker({ kind: "before", entry: action.entry });
  }

  function onPick(type: NodeType) {
    if (!picker) return;
    const made =
      picker.kind === "after" ? addAfter(doc, picker.from, type)
      : picker.kind === "insert" ? insertOnEdge(doc, picker.edge, type)
      : insertBeforeEntry(doc, picker.entry, type);  // prettier-ignore
    if (!made) return;
    const where =
      picker.kind === "after" ? (picker.from ? `after ${keyOf(picker.from.node)}` : "at the start")
      : picker.kind === "insert" ? `between ${keyOf(picker.edge.from.node)} and ${keyOf(picker.edge.to.node)}`
      : `before ${keyOf(picker.entry)}`;  // prettier-ignore
    change(made.doc, `Added ${made.node.key} ${where}`, item.node(made.node.id));
  }

  function onConnect(from: PortRef, to: string) {
    const next = connect(doc, from, to);
    if (next) change(next, `Connected ${keyOf(from.node)} to ${keyOf(to)}`);
    else announce(`${keyOf(from.node)} can't lead to ${keyOf(to)}: that would repeat an edge or close a loop`);
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Toolbar tenantId={tenantId} name={workflow.name}>
        {editable ? (
          <Button size="md" aria-keyshortcuts="A" onClick={() => setPicker({ kind: "after", from: null })}>
            ＋ Add step <kbd className="rounded-sm border border-line-strong px-1 font-mono text-meta">A</kbd>
          </Button>
        ) : (
          <span className="text-small text-muted">Read only: your role can&apos;t edit workflows</span>
        )}
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <Canvas
          doc={doc}
          types={typeMap}
          problems={new Map()}
          separate={new Map()}
          editable={editable}
          current={null}
          focusId={focusId}
          focusRequest={focusRequest}
          onFocusItem={setFocusId}
          onItem={onItem}
          onMove={(positions) => change(moveNodes(doc, positions), "Moved")}
          onConnect={onConnect}
          onLayout={() => change(moveNodes(doc, layout(doc)), "Laid out the steps")}
        />
      </div>
      {picker && (
        <StepPicker mode={picker} types={types} onPick={onPick} onClose={() => setPicker(null)} />
      )}
    </div>
  );
}
```

The shell's `main` is a column flex box; the editor's root (`flex min-h-0 flex-1 flex-col`) fills it, and React Flow
fills the canvas's box (`min-h-0 flex-1`).

- [ ] **Step 7: Run the unit tests to see them pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean, the AI-tells guard included (`canvas.css` uses tokens only; no `rounded-full`; the "＋"
glyph is U+FF0B, not an emoji).

- [ ] **Step 8: The browser gate on the real canvas: CSP, console, axe, a pointer's first steps**

`frontend/e2e/state.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
/** The signed-in admin's browser state, saved by the foundations flow (which enrolls the authenticator) for the
 * projects that depend on it: a second TOTP sign-in in one step would be refused as a replay. */
export const ADMIN_STATE = "test-results/admin-state.json";
```

At the end of `frontend/e2e/foundations.spec.ts`'s first test, after the reflow loop:

```ts
    await page.context().storageState({ path: ADMIN_STATE });
```

(import `ADMIN_STATE` from `./state`). `frontend/playwright.config.ts`'s projects become:

```ts
  projects: [
    { name: "foundations", testMatch: /(foundations|gate)\.spec\.ts/, use: { ...devices["Desktop Chrome"] } },
    {
      name: "workflows",
      testMatch: /workflows\.spec\.ts/,
      dependencies: ["foundations"],
      use: { ...devices["Desktop Chrome"], storageState: "test-results/admin-state.json" },
    },
  ],
```

`frontend/e2e/workflows.spec.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// Slice 4b in the browser: the list, the chooser and the canvas, behind nginx, under the served CSP, with axe.
import type { Page } from "@playwright/test";
import { expect, expectAccessible, test } from "./gate";

test.describe.configure({ mode: "serial" });

async function tenantId(page: Page): Promise<string> {
  const tenants = (await (await page.request.get("/api/v1/tenants")).json()) as { id: string }[];
  return tenants[0]!.id;
}

async function newWorkflow(page: Page, name: string): Promise<void> {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await expect(dialog.getByLabel("Name")).toBeFocused();
  await expectAccessible(page, "new workflow");
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("button", { name: "Create and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}$/);
}

test("a blank workflow takes its first steps with a pointer, under the CSP", async ({ page }) => {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await expect(page.getByRole("heading", { level: 1, name: "Workflows" })).toBeVisible();
  await expectAccessible(page, "workflows");
  await newWorkflow(page, "Pointer flow");
  await expect(page.getByRole("button", { name: /^Start, where every run begins/ })).toBeVisible();
  await expectAccessible(page, "editor: blank");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  await expect(page.getByRole("button", { name: /^transform, Transform/ })).toBeFocused();
  await page.getByRole("button", { name: "Add a step after transform" }).click();
  await page.getByRole("option", { name: /flow\.if@1/ }).click();
  await page.getByRole("button", { name: "Add a step after if (true)" }).click();
  await page.getByRole("option", { name: /flow\.stop@1/ }).click();
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toBeVisible();
  await page.getByRole("button", { name: "Insert a step between transform and if" }).click();
  await expect(page.getByText("Only steps that continue the flow can go here.")).toBeVisible();
  await page.getByRole("option", { name: /flow\.delay@1/ }).click();
  await expect(page.getByRole("button", { name: /^delay, Delay/ })).toBeVisible();
  await page.getByRole("button", { name: "Auto layout" }).click();
  await expectAccessible(page, "editor: four steps");
});
```

The gate's fixture (`e2e/gate.ts`) fails this test on any CSP violation, console error or remote request: this is the
proof that React Flow, d3-zoom and the step picker run under `style-src 'self'` (D23's known risk). If React Flow
injects a `<style>` or an inline style attribute the CSP refuses, stop: that's D23's case, and the owner chooses
between its options (a per-request nonce from nginx, or a different approach), not this plan.

Update the session's `compose-ui4a/reset.sh` (scratchpad, never committed): after `admin init`, sync the installed
plugins as the admin login, as CI does:

```bash
( set -a; . "$DIR/.env"; set +a
  "$DIR/dc.sh" run --rm \
    -e DEWPOINT_DATABASE_URL="postgresql+asyncpg://dewpoint_admin_login:${DEWPOINT_ADMIN_DB_PASSWORD}@postgres/dewpoint" \
    api dewpoint plugins sync >/dev/null )
```

(where `DIR` is the script's folder; the `.env` is read by the shell and never printed). Then run the gate:
`E2E_BASE_URL=http://localhost:18080 npx -y pnpm@12.6.0 exec playwright test` after a reset (`compose-ui4a/e2e.sh`).
Expected: every test passes, foundations first; `workflows` 1 passed.

- [ ] **Step 9: Commit**

```bash
git add frontend/src frontend/e2e frontend/playwright.config.ts
git commit -m "feat(web): the canvas: React Flow under the CSP, a start card, steps, + on edges and ports, the step picker (4b)"
```

### Task 12: The keyboard: one tab stop, arrows that follow the edges, every pointer action, undo

**Files:**
- Create: `frontend/src/routes/editor/canvasNav.ts`, `frontend/src/routes/editor/canvasNav.test.ts`
- Create: `frontend/src/routes/editor/ConnectDialog.tsx`, `frontend/src/routes/editor/StepPanel.tsx`
- Modify: `frontend/src/routes/editor/Canvas.tsx`, `frontend/src/routes/editor/canvas.css` (placing a step)
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`
- Modify: `frontend/e2e/workflows.spec.ts`; Create: `frontend/e2e/fixtures/cycle.dewpoint.json`

**Interfaces:**
- Consumes: `item`, `ItemAction` (Task 11); `deleteNode`, `deleteEdge`, `canConnect`, `connect`, `moveNodes`,
  `portsOf` (Task 9); `undo`, `redo` (Task 9); `ConfirmDialog` (`frontend/src/components/ConfirmDialog.tsx`).
- Consumes too: `@xyflow/react` 12.12.0's `onPaneClick(event)` and `useReactFlow().screenToFlowPosition({x, y})`
  (checked in the installed package first, Step 1); `CARD` (Task 10); `drawableEdges` (Task 9).
- Produces: `type NavKey`; `navModel(doc, portsOf, editable) -> Nav` (`children`, `parent` (the walk's first parent),
  `order`, `edges`); `step(nav, path, key) -> string[]`, `pathTo(nav, id) -> string[]`, `isPath(nav, path)`;
  `<ConnectDialog doc types from onConnect onClose />`; `<StepPanel node type ports problems expressions editable
  onDelete onConnectPort onPlace onNudge onClose />` (`problems: Diagnostic[] | null`, null when no current check speaks
  for what's on the screen: Task 14 fills it); `CanvasProps` gains `placing: boolean` and `onPlace(at: {x, y})` (the
  click's point in the canvas's own coordinates).

4b rulings 13 and 15, as the owner amended them (the owner's review of 325fc14, correction 6):
- **Single-pointer movement (WCAG 2.5.7).** Auto layout arranges the graph; it doesn't put a step where a person
  wants it. A step's panel has "Place on the canvas…": the next click on an empty place puts the step there, centred
  on the click (Escape or Cancel stops it), and four buttons move it 20 px a click. Dragging stays; it's no longer
  the only way. Shift+arrows still nudge from the keyboard.
- **Complete keyboard navigation.** Revision 1 listed steps no entry reaches (a cycle no entry leads into, a step whose
  only edges in come from steps that aren't there) in `order` without linking them: the arrow keys never got there.
  Now each such step joins the start card's children, topmost first, and is walked from there, and the tests press
  the keys from every item reached, over chains, branches, joins, cycles, two components, and an imported draft's
  dangling, repeated and self edges, until every item the canvas draws is reached. The model walks `drawableEdges`,
  the edges the canvas draws.

- [ ] **Step 1: Check React Flow's pane API in the installed package** (owner's rule): in
  `frontend/node_modules/@xyflow/react/dist/`, `ReactFlowProps.onPaneClick` (a mouse event) and
  `ReactFlowInstance.screenToFlowPosition({ x, y })` (a client point to the flow's coordinates, zoom and pan
  included). A difference goes in a mid-slice ruling, and the installed API is used.

- [ ] **Step 2: Write the failing tests**

`frontend/src/routes/editor/canvasNav.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { NAV_KEYS, isPath, navModel, pathTo, step, type Nav, type NavKey } from "./canvasNav";

const node = (id: string, x = 0) => ({ id, key: id, type: "flow.transform@1", position: { x, y: 0 } });
const edge = (from: string, to: string, port = "out") => ({ from: { node: from, port }, to: { node: to } });
const ports = (map: Record<string, string[]>) => (id: string) => map[id] ?? ["out"];
/** The item a path ends on: the focused one. */
const at = (path: string[]) => path.at(-1);
/** The path after pressing `keys` from `from`. */
const press = (nav: Nav, from: string[], ...keys: NavKey[]) => keys.reduce((path, key) => step(nav, path, key), from);

it("walks a chain down and back up, through its edges and its last free port", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b")] };
  const nav = navModel(doc, ports({}), true);
  const seen: (string | undefined)[] = [];
  let path = ["start"];
  for (let i = 0; i < 5; i++) seen.push(at((path = step(nav, path, "ArrowDown"))));
  expect(seen).toEqual(["entry:a", "node:a", "edge:a:out->b", "node:b", "port:b:out"]);
  expect(at(press(nav, path, "ArrowDown"))).toBe("port:b:out");
  expect(at(press(nav, pathTo(nav, "node:b"), "ArrowUp"))).toBe("edge:a:out->b");
  expect(press(nav, path, "Home")).toEqual(["start"]);
});

it("moves across a branch's ports, left to right, an empty port included", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [node("if"), node("yes")], edges: [edge("if", "yes", "true")] };
  const nav = navModel(doc, ports({ if: ["true", "false"] }), true);
  expect(nav.children.get("node:if")).toEqual(["edge:if:true->yes", "port:if:false"]);
  const onTrue = pathTo(nav, "edge:if:true->yes");
  expect(at(press(nav, onTrue, "ArrowRight"))).toBe("port:if:false");
  expect(at(press(nav, onTrue, "ArrowRight", "ArrowRight"))).toBe("port:if:false");
  expect(at(press(nav, onTrue, "ArrowRight", "ArrowLeft"))).toBe("edge:if:true->yes");
});

it("orders a port's targets by where they sit, and keeps an edge from a port the type no longer has", () => {
  const doc: GraphDoc = {
    graph_format: 1,
    nodes: [node("a"), node("right", 300), node("left", 0), node("odd", 600)],
    edges: [edge("a", "right"), edge("a", "left"), edge("a", "odd", "gone")],
  };  // prettier-ignore
  const nav = navModel(doc, ports({}), true);
  expect(nav.children.get("node:a")).toEqual(["edge:a:out->left", "edge:a:out->right", "edge:a:gone->odd"]);
});

it("reads a read-only canvas step to step, with nothing to add", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b")] };
  const nav = navModel(doc, ports({}), false);
  expect(nav.order).toEqual(["start", "node:a", "node:b"]);
});

it("offers the start card's own '+' before any step, and links a cycle no entry reaches under it", () => {
  expect(navModel({ graph_format: 1, nodes: [], edges: [] }, ports({}), true).order).toEqual(["start", "port:start:out"]);
  const loop: GraphDoc = { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b"), edge("b", "a")] };
  const nav = navModel(loop, ports({}), false);
  expect(nav.children.get("start")).toEqual(["node:a"]);
  expect(press(nav, ["start"], "ArrowDown", "ArrowDown")).toEqual(["start", "node:a", "node:b"]);
  // Down from b follows its edge back to a: the path returns to a, never growing round the cycle.
  expect(press(nav, ["start"], "ArrowDown", "ArrowDown", "ArrowDown")).toEqual(["start", "node:a"]);
});

// a → b, c; b → d, e; c → d, f: d is reached from b and from c (the owner's review of revision 2).
const JOINS: GraphDoc = {
  graph_format: 1,
  nodes: [node("a"), node("b"), node("c", 300), node("d"), node("e", 300), node("f", 600)],
  edges: [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("b", "e"), edge("c", "d"), edge("c", "f")],
};  // prettier-ignore

it("keeps to the branch it came by at a join: from d reached through c, the sibling is f", () => {
  const readOnly = navModel(JOINS, ports({}), false); // c's children are the steps d and f
  const toD = press(readOnly, pathTo(readOnly, "node:c"), "ArrowDown");
  expect(at(toD)).toBe("node:d");
  expect(at(press(readOnly, toD, "ArrowRight"))).toBe("node:f"); // never b's e
  expect(at(press(readOnly, toD, "ArrowUp"))).toBe("node:c"); // back the way it came, never to b
  const editable = navModel(JOINS, ports({}), true); // c's children are the edges c→d and c→f
  const viaEdge = press(editable, pathTo(editable, "node:c"), "ArrowDown", "ArrowDown");
  expect(at(viaEdge)).toBe("node:d");
  expect(at(press(editable, viaEdge, "ArrowUp"))).toBe("edge:c:out->d");
  expect(at(press(editable, viaEdge, "ArrowUp", "ArrowRight", "ArrowDown"))).toBe("node:f");
});

it("takes a path only while each of its steps is a child of the one before", () => {
  const nav = navModel(JOINS, ports({}), false);
  expect(isPath(nav, ["start", "node:a", "node:c", "node:d"])).toBe(true);
  expect(isPath(nav, ["start", "node:a", "node:e"])).toBe(false);
  expect(pathTo(nav, "node:gone")).toEqual(["start"]);
});

/** Every item the canvas draws for `doc`, counted from the document itself, never from the model under test. */
function drawnItems(doc: GraphDoc, portsOf: (id: string) => string[], editable: boolean): Set<string> {
  const nodes = doc.nodes ?? [];
  const out = new Set<string>(["start", ...nodes.map((n) => `node:${n.id}`)]);
  if (!editable) return out;
  if (nodes.length === 0) out.add("port:start:out");
  const ids = new Set(nodes.map((n) => n.id));
  const targets = new Set((doc.edges ?? []).map((e) => e.to.node));
  for (const n of nodes) if (!targets.has(n.id)) out.add(`entry:${n.id}`);
  const drawn = (doc.edges ?? []).filter((e) => ids.has(e.from.node) && ids.has(e.to.node));
  for (const e of drawn) out.add(`edge:${e.from.node}:${e.from.port ?? "out"}->${e.to.node}`);
  for (const n of nodes) {
    for (const p of portsOf(n.id)) {
      if (!drawn.some((e) => e.from.node === n.id && (e.from.port ?? "out") === p)) out.add(`port:${n.id}:${p}`);
    }
  }
  return out;
}

/** Every item the keys reach from the start card: each key pressed from each path reached, the path carried along,
 * as the editor carries it. */
function reachedByKeys(nav: Nav): Set<string> {
  const reached = new Set(["start"]);
  const seen = new Set([JSON.stringify(["start"])]);
  const todo = [["start"]];
  while (todo.length) {
    const path = todo.pop()!;
    for (const key of NAV_KEYS as NavKey[]) {
      const next = step(nav, path, key);
      const id = JSON.stringify(next);
      if (seen.has(id)) continue;
      seen.add(id);
      reached.add(at(next)!);
      todo.push(next);
    }
  }
  return reached;
}

const CASES: [string, GraphDoc, Record<string, string[]>][] = [
  ["a chain", { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b")] }, {}],
  [
    "a branch and its join",
    { graph_format: 1, nodes: [node("if"), node("y"), node("n", 300), node("j")],
      edges: [edge("if", "y", "true"), edge("if", "n", "false"), edge("y", "j"), edge("n", "j")] },
    { if: ["true", "false"] },
  ],
  ["a join a second branch also reaches", JOINS, {}],
  ["a cycle no entry leads into", { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b"), edge("b", "a")] }, {}],
  ["a cycle beside an entry", { graph_format: 1, nodes: [node("e"), node("a"), node("b")], edges: [edge("a", "b"), edge("b", "a")] }, {}],
  [
    "two components, one looping back into its chain",
    { graph_format: 1, nodes: [node("a"), node("b"), node("c"), node("x"), node("y")],
      edges: [edge("a", "b"), edge("b", "c"), edge("c", "b"), edge("x", "y"), edge("y", "x")] },
    {},
  ],
  [
    "an imported draft's dangling, repeated and self edges",
    { graph_format: 1, nodes: [node("a"), node("b")],
      edges: [edge("a", "b"), edge("a", "b"), edge("gone", "b"), edge("a", "gone"), edge("b", "b")] },
    {},
  ],
  [
    "a step of an unknown type, reached from a port its source's type lacks",
    { graph_format: 1, nodes: [node("a"), node("odd")], edges: [edge("a", "odd", "gone")] },
    { odd: [] },
  ],
];  // prettier-ignore

// Read only is how a viewer, an editor after a conflict, and any viewed version see the canvas: all three hand
// `navModel` `editable: false`.
it.each(CASES)("reaches every item of %s with the keys alone, editable or read only", (_, doc, map) => {
  for (const editable of [true, false]) {
    expect(reachedByKeys(navModel(doc, ports(map), editable))).toEqual(drawnItems(doc, ports(map), editable));
  }
});
```

In `frontend/src/routes/editor/Editor.test.tsx` (its stand-in canvas from Task 11), add:

```tsx
async function withTwoSteps() {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(await screen.findByRole("button", { name: "after transform" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await screen.findByRole("button", { name: "transform_2" });
}

it("deletes the focused step with Delete, after asking, and heals the chain in words", async () => {
  await withTwoSteps();
  screen.getByRole("button", { name: "transform" }).focus();
  await userEvent.keyboard("{Delete}");
  const ask = screen.getByRole("dialog", { name: "Delete a step" });
  expect(ask.textContent).toContain("transform and its edges are deleted.");
  await userEvent.click(within(ask).getByRole("button", { name: "Delete" }));
  expect(screen.queryByRole("button", { name: "transform" })).toBeNull();
  expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
});

it("opens the picker after the focused step with A, and undoes and redoes", async () => {
  await withTwoSteps();
  screen.getByRole("button", { name: "transform_2" }).focus();
  await userEvent.keyboard("a");
  expect(screen.getByRole("dialog", { name: "Add a step" })).toBeTruthy();
  await userEvent.keyboard("{Escape}");
  screen.getByRole("button", { name: "transform_2" }).focus();
  await userEvent.keyboard("{Control>}z{/Control}");
  expect(screen.queryByRole("button", { name: "transform_2" })).toBeNull();
  screen.getByRole("button", { name: "transform" }).focus();
  await userEvent.keyboard("{Control>}{Shift>}z{/Shift}{/Control}");
  expect(screen.getByRole("button", { name: "transform_2" })).toBeTruthy();
});

it("opens a step's panel on Enter, its heading focused, and Escape gives focus back to the step", async () => {
  await withTwoSteps();
  const step = screen.getByRole("button", { name: "transform_2" });
  step.focus();
  await userEvent.keyboard("{Enter}");
  const panel = screen.getByRole("complementary", { name: "transform_2" });
  expect(document.activeElement).toBe(within(panel).getByRole("heading", { name: "transform_2" }));
  expect(panel.textContent).toContain("Transform · flow.transform@1");
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(document.activeElement).toBe(step);
});

const at = (key: string) => drawn.at(-1)!.doc.nodes!.find((n) => n.key === key)!.position;

it("places a step where a single pointer clicks, never by dragging (WCAG 2.5.7)", async () => {
  await withTwoSteps();
  await userEvent.click(screen.getByRole("button", { name: "transform" })); // its panel
  await userEvent.click(screen.getByRole("button", { name: "Place on the canvas…" }));
  expect(screen.getByText("Click an empty place on the canvas to put transform there.")).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: "place here" }));
  expect(at("transform")).toEqual({ x: 400 - 130, y: 300 - 32 }); // centred on the click
  expect(screen.queryByText(/Click an empty place/)).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "transform" }));
});

it("stops placing on Escape, leaving the step where it was", async () => {
  await withTwoSteps();
  const before = at("transform");
  await userEvent.click(screen.getByRole("button", { name: "transform" }));
  await userEvent.click(screen.getByRole("button", { name: "Place on the canvas…" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByText(/Click an empty place/)).toBeNull();
  expect(screen.queryByRole("button", { name: "place here" })).toBeNull();
  expect(at("transform")).toEqual(before);
});

it("moves a step 20 px a click from its panel", async () => {
  await withTwoSteps();
  const before = at("transform")!;
  await userEvent.click(screen.getByRole("button", { name: "transform" }));
  await userEvent.click(screen.getByRole("button", { name: "Move transform right" }));
  await userEvent.click(screen.getByRole("button", { name: "Move transform down" }));
  expect(at("transform")).toEqual({ x: before.x + 20, y: before.y + 20 });
});
```

(add `within` to the Testing Library import). The stand-in canvas of Task 11 gains, after its steps, the click a
pointer would make on an empty place while placing:

```tsx
          {props.placing && <button onClick={() => props.onPlace({ x: 400, y: 300 })}>place here</button>}
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL: `canvasNav.ts` doesn't exist; the editor ignores Delete, `a` and Ctrl+Z.

- [ ] **Step 4: Implement the model**

`frontend/src/routes/editor/canvasNav.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// The canvas's keyboard model (D16; 4b ruling 15, amended). Each item lists its children from the start card down:
// the start card, its edges to the entry steps, each step, each edge leaving it (by port, then left to right), each
// free port. A step joined from two places is a child of both, so the keys carry the path they came by (`step`): Up
// goes back that way, and Left and Right stay among the children of the item it came from. A step no entry reaches
// (a cycle no entry leads into, a step whose only edges in come from steps that aren't there) joins the start card's
// children, topmost first: every item the canvas draws is reached by the keys. Home goes to the start card. A
// read-only canvas (a viewer, a conflict, an old version) holds the start card and the steps only.
import { START, drawableEdges, entries, nodesOf, portOf, pos } from "../../lib/graph";
import type { GraphDoc, GraphEdge } from "../../lib/workflows";
import { item } from "./items";

export type NavKey = "ArrowDown" | "ArrowUp" | "ArrowLeft" | "ArrowRight" | "Home";
export const NAV_KEYS: readonly string[] = ["ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "Home"];

export interface Nav {
  children: Map<string, string[]>;
  parent: Map<string, string>;
  order: string[]; // every item, breadth first from the start card
  edges: Map<string, GraphEdge>; // an edge item's edge
}

export function navModel(doc: GraphDoc, portsOf: (nodeId: string) => string[], editable: boolean): Nav {
  const children = new Map<string, string[]>();
  const edges = new Map<string, GraphEdge>();
  const nodes = nodesOf(doc);
  const drawn = drawableEdges(doc);
  const x = new Map(nodes.map((n) => [n.id, pos(n).x]));
  const byPlace = (a: GraphEdge, b: GraphEdge) =>
    (x.get(a.to.node) ?? 0) - (x.get(b.to.node) ?? 0) || a.to.node.localeCompare(b.to.node);
  const first = [...entries(doc)].sort((a, b) => pos(a).x - pos(b).x || a.id.localeCompare(b.id));
  const top = editable ? first.map((n) => item.entry(n.id)) : first.map((n) => item.node(n.id));
  if (editable) for (const n of first) children.set(item.entry(n.id), [item.node(n.id)]);
  if (editable && nodes.length === 0) top.push(item.port(START, "out"));
  children.set(item.start, top);
  for (const n of nodes) {
    const leaving = drawn.filter((e) => e.from.node === n.id);
    const own = portsOf(n.id);
    const ports = [...own, ...new Set(leaving.map(portOf).filter((p) => !own.includes(p)))];
    const out: string[] = [];
    for (const port of ports) {
      const here = leaving.filter((e) => portOf(e) === port).sort(byPlace);
      if (!editable) {
        out.push(...here.map((e) => item.node(e.to.node)));
        continue;
      }
      for (const e of here) {
        const id = item.edge(e);
        edges.set(id, e);
        children.set(id, [item.node(e.to.node)]);
        out.push(id);
      }
      if (here.length === 0 && own.includes(port)) out.push(item.port(n.id, port));
    }
    children.set(item.node(n.id), out);
  }
  const parent = new Map<string, string>();
  const order: string[] = [];
  const seen = new Set<string>([item.start]);
  const queue = [item.start];
  const walk = () => {
    while (queue.length) {
      const at = queue.shift()!;
      order.push(at);
      for (const child of children.get(at) ?? []) {
        if (seen.has(child)) continue;
        seen.add(child);
        parent.set(child, at);
        queue.push(child);
      }
    }
  };
  walk();
  // A step the start card doesn't reach becomes one of its children (so Down, Left and Right get there), topmost
  // first, and what it reaches is walked from it; until every step is reached.
  const unreached = () =>
    nodes
      .filter((n) => !seen.has(item.node(n.id)))
      .sort((a, b) => pos(a).y - pos(b).y || pos(a).x - pos(b).x || a.id.localeCompare(b.id));
  for (let rest = unreached(); rest.length > 0; rest = unreached()) {
    const root = item.node(rest[0]!.id);
    top.push(root);
    seen.add(root);
    parent.set(root, item.start);
    queue.push(root);
    walk();
  }
  return { children, parent, order, edges };
}

/** Whether `path` runs from the start card, each item a child of the one before (still true after a change). */
export function isPath(nav: Nav, path: string[]): boolean {
  return path[0] === item.start && path.every((id, i) => i === 0 || (nav.children.get(path[i - 1]!) ?? []).includes(id));
}

/** The walk's own path to an item (its first parent at each step): where a click, Tab or a change leaves the keys. */
export function pathTo(nav: Nav, id: string): string[] {
  if (!nav.order.includes(id)) return [item.start];
  const path = [id];
  for (let at = nav.parent.get(id); at !== undefined; at = nav.parent.get(at)) path.unshift(at);
  return path;
}

/** One key, from the path the keys came by: Down to the first child, Up back the way it came, Left and Right among
 * the children of the item it came from (at a join, the branch it came by: the owner's review of revision 2), Home
 * to the start card. Down onto an item already on the path goes back to it there, so a cycle never grows the path. */
export function step(nav: Nav, path: string[], key: NavKey): string[] {
  if (key === "Home") return [item.start];
  const here = path.at(-1)!;
  if (key === "ArrowDown") {
    const child = nav.children.get(here)?.[0];
    if (child === undefined) return path;
    const back = path.indexOf(child);
    return back >= 0 ? path.slice(0, back + 1) : [...path, child];
  }
  if (key === "ArrowUp") return path.length > 1 ? path.slice(0, -1) : path;
  const siblings = path.length > 1 ? (nav.children.get(path.at(-2)!) ?? [here]) : [here];
  const next = siblings[siblings.indexOf(here) + (key === "ArrowLeft" ? -1 : 1)];
  return next === undefined ? path : [...path.slice(0, -1), next];
}
```

- [ ] **Step 5: Implement the dialog and the panel**

`frontend/src/routes/editor/ConnectDialog.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// "Connect to an existing step" (4b ruling 14): the steps that may follow a port, never itself, a step already
// connected from it, or one that would close a loop. The keyboard's and a single pointer's way to what a drag from
// a handle does. A native modal dialog (D23).
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import { canConnect, nodesOf, type PortRef } from "../../lib/graph";
import type { GraphDoc, NodeType } from "../../lib/workflows";

export function ConnectDialog({
  doc, types, from, onConnect, onClose,
}: { doc: GraphDoc; types: Map<string, NodeType>; from: PortRef; onConnect: (to: string) => void; onClose: () => void }) {  // prettier-ignore
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) {
      d.showModal();
      d.querySelector<HTMLButtonElement>("li button")?.focus();
    }
  }, []);
  const source = nodesOf(doc).find((n) => n.id === from.node);
  const candidates = nodesOf(doc).filter((n) => canConnect(doc, from, n.id)).sort((a, b) => a.key.localeCompare(b.key));
  const name = `${source?.key ?? "a step"}${from.port === "out" ? "" : ` (${from.port})`}`;
  return (
    <dialog
      ref={dialog}
      aria-label={`Connect ${name} to`}
      onClose={onClose}
      className="mx-auto mt-20 w-[480px] max-w-[calc(100vw-32px)] rounded-dialog border border-line bg-surface p-6 text-ink shadow-dialog backdrop:bg-overlay"
    >
      <h2 className="text-h3 font-semibold">Connect {name} to</h2>
      {candidates.length === 0 ? (
        <p className="mt-3 text-body text-muted">No step can follow it: each is itself, already connected, or would close a loop.</p>
      ) : (
        <ul className="mt-3 flex max-h-80 flex-col gap-1 overflow-y-auto">
          {candidates.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => {
                  dialog.current?.close();
                  onConnect(n.id);
                }}
                className="flex w-full items-baseline justify-between gap-3 rounded-md px-3 py-2 text-left hover:bg-surface-hover"
              >
                <span className="font-medium">{n.key}</span>
                <span className="text-small text-muted">{types.get(n.type)?.title ?? n.type}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-6 flex justify-end">
        <Button onClick={() => dialog.current?.close()}>Cancel</Button>
      </div>
    </dialog>
  );
}
```

`frontend/src/routes/editor/StepPanel.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A step's panel (Enter on a step; 4b ruling 15): what the step is and how it runs, its problems and its
// expressions, and, for an editor, where it sits: placed with a click on the canvas or moved 20 px a click (WCAG
// 2.5.7, ruling 13 amended). Its config is read-only in 4b: 4c's drawer replaces it with Setup and Options. Escape
// closes it and gives focus back to the step.
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import type { Diagnostic, Expression, GraphNode, NodeType } from "../../lib/workflows";

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

export function StepPanel({
  node, type, ports, problems, expressions, editable, onDelete, onConnectPort, onPlace, onNudge, onClose,
}: {
  node: GraphNode; type: NodeType | undefined; ports: string[]; problems: Diagnostic[] | null; expressions: Expression[];
  editable: boolean; onDelete: () => void; onConnectPort: (port: string) => void; onPlace: () => void;
  onNudge: (key: Nudge) => void; onClose: () => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), [node.id]);
  return (
    <aside
      aria-labelledby="step-panel-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="flex w-full max-w-[440px] shrink-0 flex-col gap-5 overflow-y-auto border-l border-line bg-surface p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="step-panel-title" ref={heading} tabIndex={-1} className="truncate font-mono text-body-lg font-semibold">
            {node.key}
          </h2>
          <p className="text-small text-muted">{type ? `${type.title} · ${type.ref}` : `Unknown step type ${node.type}`}</p>
        </div>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {type && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-small">
          <dt className="text-muted">Runs</dt>
          <dd>{type.kind === "control" ? "In the engine" : "As its own step"}</dd>
          {type.kind === "action" && (<><dt className="text-muted">Effect</dt><dd>{EFFECTS[type.side_effect]}</dd></>)}
          <dt className="text-muted">Retries</dt>
          <dd>Up to {node.options?.max_attempts ?? type.retry.max_attempts} attempts</dd>
          <dt className="text-muted">Timeout</dt>
          <dd>{node.options?.timeout_s ?? type.timeout_s} s</dd>
        </dl>
      )}
      <section className="flex flex-col gap-2">
        <h3 className="text-small font-semibold">Problems</h3>
        {problems === null ? (
          <p className="text-small text-muted">Not checked for what&apos;s on the screen.</p>
        ) : problems.length === 0 ? (
          <p className="text-small text-muted">None found in the saved draft.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {problems.map((d, i) => (
              <li key={`${d.code}:${d.field}:${i}`} className="text-small">
                <span className={d.severity === "error" ? "text-danger" : "text-warn-ink"}>{d.message}</span>
                {d.fix && <span className="block text-muted">{d.fix}</span>}
                <span className="block font-mono text-meta text-muted">{d.code}{d.field ? ` · ${d.field}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      {expressions.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-small font-semibold">Expressions</h3>
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

In `frontend/src/routes/editor/Canvas.tsx`, `CanvasProps` gains:

```tsx
  placing: boolean; // the next click on an empty place puts a step there (WCAG 2.5.7)
  onPlace: (at: { x: number; y: number }) => void; // the click, in the canvas's own coordinates
```

and `<ReactFlow>` gains the click and the cursor that says so:

```tsx
        onPaneClick={(e) => {
          if (p.placing) p.onPlace(flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
        }}
        className={p.placing ? "canvas-placing" : undefined}
```

with, in `canvas.css`:

```css
.canvas-placing .react-flow__pane {
  cursor: crosshair;
}
```

`screenToFlowPosition` takes the zoom and the pan into account, so the step lands under the pointer at any zoom.

- [ ] **Step 6: Wire the keyboard into the editor**

In `frontend/src/routes/editor/Editor.tsx`, add the imports (`type KeyboardEvent`, `ConfirmDialog`, `deleteEdge`,
`deleteNode`, `edgesOf`, `portsOf`, `undo`, `redo`, `NAV_KEYS`, `isPath`, `navModel`, `pathTo`, `step`, `type NavKey`,
`type GraphEdge`, `ConnectDialog`, `StepPanel`). Task 11's `focus` carries the path the keys came by, and a focus that
didn't come by the keys (a click, Tab, a change) drops it:

```tsx
  const [trail, setTrail] = useState<string[] | null>(null); // the path the keys came by to the focused item

  function focus(id: string, path: string[] | null = null) {
    setFocusId(id);
    setTrail(path);
    setFocusRequest((r) => ({ id, n: (r?.n ?? 0) + 1 }));
  }
```

and the canvas's `onFocusItem` becomes `(id) => { setFocusId(id); setTrail((t) => (t?.at(-1) === id ? t : null)); }`.
Then, in `Editor`:

```tsx
  const portMap = useMemo(
    () => new Map(nodesOf(doc).map((n) => [n.id, portsOf(n, typeMap.get(n.type))])),
    [doc, typeMap],
  );
  const nav = useMemo(() => navModel(doc, (id) => portMap.get(id) ?? [], editable), [doc, portMap, editable]);
  const shown = nav.order.includes(focusId) ? focusId : START; // a deleted item's tab stop falls back to the start card
  const [connecting, setConnecting] = useState<PortRef | null>(null);
  const [asking, setAsking] = useState<{ kind: "node"; id: string } | { kind: "edge"; edge: GraphEdge } | null>(null);
  const [panel, setPanel] = useState<string | null>(null); // the step whose panel is open
  const [placing, setPlacing] = useState<string | null>(null); // the step the next click on the canvas puts there

  const firstPort = (nodeId: string): PortRef | null => {
    const port = portMap.get(nodeId)?.[0];
    return port ? { node: nodeId, port } : null;
  };

  /** `A`, the toolbar's Add step, and Enter on a "+": the picker for the focused item. */
  function addFrom(id: string) {
    if (id === START || id === item.port(START, "out")) return setPicker({ kind: "after", from: null });
    if (id.startsWith("node:")) {
      const from = firstPort(id.slice(5));
      if (from) setPicker({ kind: "after", from });
      else announce(`${keyOf(id.slice(5))} ends its branch: there's no port to add after`);
      return;
    }
    if (id.startsWith("entry:")) return setPicker({ kind: "before", entry: id.slice(6) });
    if (id.startsWith("edge:")) return setPicker({ kind: "insert", edge: nav.edges.get(id)! });
    if (id.startsWith("port:")) {
      const [, node, port] = id.split(":");
      setPicker({ kind: "after", from: { node: node!, port: port! } });
    }
  }

  function connectFrom(id: string) {
    if (id.startsWith("port:") && !id.startsWith(`port:${START}:`)) {
      const [, node, port] = id.split(":");
      return setConnecting({ node: node!, port: port! });
    }
    if (id.startsWith("edge:")) return setConnecting(nav.edges.get(id)!.from as PortRef);
    if (id.startsWith("node:")) {
      const from = firstPort(id.slice(5));
      if (from) setConnecting(from);
    }
  }

  function askDelete(id: string) {
    if (id.startsWith("node:")) setAsking({ kind: "node", id: id.slice(5) });
    if (id.startsWith("edge:")) setAsking({ kind: "edge", edge: nav.edges.get(id)! });
  }

  function confirmDelete() {
    if (!asking) return;
    if (asking.kind === "node") {
      const { doc: next, healed } = deleteNode(doc, asking.id);
      // Focus goes to the step it came after (its own items are gone with it), or to the start card.
      const inbound = edgesOf(doc).find((e) => e.to.node === asking.id);
      const back = inbound ? item.node(inbound.from.node) : START;
      if (panel === asking.id) setPanel(null);
      change(next, `Deleted ${keyOf(asking.id)}${healed ? `; ${keyOf(healed.from.node)} now leads to ${keyOf(healed.to.node)}` : ""}`, back);
    } else {
      change(deleteEdge(doc, asking.edge), `Deleted the edge from ${keyOf(asking.edge.from.node)} to ${keyOf(asking.edge.to.node)}`, item.node(asking.edge.from.node));
    }
    setAsking(null);
  }

  function nudge(nodeId: string, key: NavKey) {
    const n = nodesOf(doc).find((m) => m.id === nodeId);
    if (!n) return;
    const d = { ArrowUp: [0, -20], ArrowDown: [0, 20], ArrowLeft: [-20, 0], ArrowRight: [20, 0], Home: [0, 0] }[key];
    change(moveNodes(doc, new Map([[nodeId, { x: (n.position?.x ?? 0) + d[0]!, y: (n.position?.y ?? 0) + d[1]! }]])), `Moved ${n.key}`);
  }

  /** The click that ends "Place on the canvas…": the step, centred on it (WCAG 2.5.7). Never on a read-only canvas. */
  function place(at: { x: number; y: number }) {
    if (!placing || !editable) return;
    const id = placing;
    setPlacing(null);
    change(moveNodes(doc, new Map([[id, { x: at.x - CARD.width / 2, y: at.y - CARD.height / 2 }]])), `Placed ${keyOf(id)}`, item.node(id));
  }

  /** Escape stops placing first, before it closes a panel or a picker. */
  function onEditorKeyCapture(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Escape" || !placing) return;
    e.stopPropagation();
    e.preventDefault();
    setPlacing(null);
    announce("Not placed");
  }

  function onCanvasKey(e: KeyboardEvent<HTMLDivElement>) {
    const id = (e.target as HTMLElement).dataset.item;
    if (!id || e.altKey) return;
    const plain = !e.ctrlKey && !e.metaKey;
    if (NAV_KEYS.includes(e.key) && plain) {
      e.preventDefault();
      if (e.shiftKey && editable && id.startsWith("node:")) return nudge(id.slice(5), e.key as NavKey);
      // The path the keys came by while it still holds (at a join, the branch taken); else the walk's own path.
      const path = trail && trail.at(-1) === id && isPath(nav, trail) ? trail : pathTo(nav, id);
      const next = step(nav, path, e.key as NavKey);
      if (next.at(-1) !== id) focus(next.at(-1)!, next);
      return;
    }
    if (!editable || !plain) return;
    if (e.key === "a" || e.key === "A") {
      e.preventDefault();
      addFrom(id);
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      askDelete(id);
    } else if (e.key === "c" || e.key === "C") {
      e.preventDefault();
      connectFrom(id);
    }
  }

  /** Ctrl or Cmd+Z undoes, with Shift redoes (D17: local). Not while typing, nor behind a dialog. */
  function onEditorKey(e: KeyboardEvent<HTMLDivElement>) {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z" || !editable) return;
    const t = e.target as HTMLElement;
    if (t.closest("input, textarea, select, dialog")) return;
    e.preventDefault();
    setHistory((h) => (e.shiftKey ? redo(h) : undo(h)));
    announce(e.shiftKey ? "Redone" : "Undone");
  }
```

`onItem` opens the panel for `open`, and uses `addFrom` for the rest:

```tsx
  function onItem(action: ItemAction) {
    if (action.kind === "open") return setPanel(action.node);
    if (!editable) return;
    if (action.kind === "after") setPicker({ kind: "after", from: action.from });
    if (action.kind === "insert") setPicker({ kind: "insert", edge: action.edge });
    if (action.kind === "before") setPicker({ kind: "before", entry: action.entry });
  }
```

The toolbar's Add step calls `addFrom(shown)`; the root `div` takes `onKeyDown={onEditorKey}` and
`onKeyDownCapture={onEditorKeyCapture}`; the canvas takes `focusId={shown}`, `current={panel}`,
`onKeyDown={onCanvasKey}`, `placing={editable && placing !== null}` and `onPlace={place}` (import `CARD` from
`../../lib/layout`); while placing, a bar above the canvas says so and offers Cancel:

```tsx
      {placing && editable && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
          <span className="grow">Click an empty place on the canvas to put {keyOf(placing)} there.</span>
          <Button size="sm" onClick={() => setPlacing(null)}>Cancel</Button>
        </div>
      )}
```

The picker takes
`onConnect={picker.kind === "after" && picker.from ? () => setConnecting(picker.from) : undefined}`; and after the
canvas, inside the row:

```tsx
        {panel && nodesOf(doc).some((n) => n.id === panel) && (
          <StepPanel
            node={nodesOf(doc).find((n) => n.id === panel)!}
            type={typeMap.get(nodesOf(doc).find((n) => n.id === panel)!.type)}
            ports={portMap.get(panel) ?? []}
            problems={null}
            expressions={[]}
            editable={editable}
            onDelete={() => setAsking({ kind: "node", id: panel })}
            onConnectPort={(port) => setConnecting({ node: panel, port })}
            onPlace={() => {
              setPlacing(panel);
              announce(`Click an empty place on the canvas to put ${keyOf(panel)} there`);
            }}
            onNudge={(key) => nudge(panel, key)}
            onClose={() => {
              setPanel(null);
              focus(item.node(panel));
            }}
          />
        )}
```

and after the picker:

```tsx
      {connecting && (
        <ConnectDialog
          doc={doc}
          types={typeMap}
          from={connecting}
          onConnect={(to) => onConnect(connecting, to)}
          onClose={() => setConnecting(null)}
        />
      )}
      <ConfirmDialog
        open={asking !== null}
        title={asking?.kind === "edge" ? "Delete an edge" : "Delete a step"}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onCancel={() => setAsking(null)}
      >
        {asking?.kind === "node" && (
          <>
            {keyOf(asking.id)} and its edges are deleted.
            {healed && ` ${keyOf(healed.from.node)} will lead to ${keyOf(healed.to.node)}.`} Other steps that read its
            output will show a problem.
          </>
        )}
        {asking?.kind === "edge" && `${keyOf(asking.edge.to.node)} will no longer follow ${keyOf(asking.edge.from.node)}.`}
      </ConfirmDialog>
```

with, above the component's `return`, the healing the dialog describes, computed once:

```tsx
  const healed = asking?.kind === "node" ? deleteNode(doc, asking.id).healed : null;
```

`onConnect` focuses the new edge's "+": `change(next, …, item.edge({ from, to: { node: to } }))`.

- [ ] **Step 7: The keyboard-only flow in the browser**

In `frontend/e2e/workflows.spec.ts`, add:

```ts
test("a workflow built with the keyboard alone: Tab in, arrows along the edges, A, Delete, undo", async ({ page }) => {
  await newWorkflow(page, "Keyboard flow");
  const start = page.getByRole("button", { name: /^Start, where every run begins/ });
  await start.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.type("transform");
  await page.keyboard.press("Enter");
  const transform = page.getByRole("button", { name: /^transform, Transform/ });
  await expect(transform).toBeFocused();
  await page.keyboard.press("a");
  await page.keyboard.type("flow.if");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /^if, If/ })).toBeFocused();
  await page.keyboard.press("ArrowDown"); // the if step's free true port
  await expect(page.getByRole("button", { name: "Add a step after if (true)" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("button", { name: "Add a step after if (false)" })).toBeFocused();
  await page.keyboard.press("Enter");
  await page.keyboard.type("stop");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toBeFocused();
  await page.keyboard.press("ArrowUp"); // the edge from if's false port
  await expect(page.getByRole("button", { name: "Insert a step between if and stop" })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(start).toBeFocused();
  // Tab leaves the canvas at once: one tab stop.
  await page.keyboard.press("Tab");
  await expect(page.locator("[data-item]:focus")).toHaveCount(0);
  await page.keyboard.press("Shift+Tab");
  await expect(start).toBeFocused();
  // Delete asks first; Escape keeps the step; undo brings back what Delete removed.
  await page.getByRole("button", { name: /^stop, Stop/ }).focus();
  await page.keyboard.press("Delete");
  const ask = page.getByRole("dialog", { name: "Delete a step" });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expectAccessible(page, "editor: delete a step");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toHaveCount(0);
  await page.keyboard.press("Control+z");
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toBeVisible();
  // Enter opens a step's panel; Escape gives focus back.
  await transform.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 2, name: "transform" })).toBeFocused();
  await expectAccessible(page, "editor: step panel");
  await page.keyboard.press("Escape");
  await expect(transform).toBeFocused();
});
```

```ts
test("a step is placed with single clicks, never a drag (WCAG 2.5.7)", async ({ page }) => {
  await newWorkflow(page, "Placed flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  const card = page.getByRole("button", { name: /^transform, Transform/ });
  await card.click(); // its panel
  await page.getByRole("button", { name: "Place on the canvas…" }).click();
  await expect(page.getByText("Click an empty place on the canvas to put transform there.")).toBeVisible();
  await expectAccessible(page, "editor: placing a step");
  // An empty place: the canvas's top right, clear of the cards (fitted to its middle), the minimap (bottom right)
  // and the zoom controls (bottom left).
  const pane = (await page.locator(".react-flow__pane").boundingBox())!;
  const target = { x: pane.x + pane.width * 0.85, y: pane.y + pane.height * 0.2 };
  await page.mouse.click(target.x, target.y);
  await expect(card).toBeFocused();
  const placed = (await card.boundingBox())!;
  expect(Math.abs(placed.x + placed.width / 2 - target.x)).toBeLessThan(4);
  expect(Math.abs(placed.y + placed.height / 2 - target.y)).toBeLessThan(4);
  // Its panel's buttons move it a step at a time.
  await card.click();
  await page.getByRole("button", { name: "Move transform left" }).click();
  await expect.poll(async () => (await card.boundingBox())!.x).toBeLessThan(placed.x);
});
```

`frontend/e2e/fixtures/cycle.dewpoint.json` (a step no edge leads to, and two steps leading to each other that no
entry reaches: what the keyboard model must still reach; the API imports it, its format being sound, and its
problems say what's wrong):

```json
{
  "format": "dewpoint.workflow",
  "format_version": 1,
  "name": "Cycle",
  "graph": {
    "graph_format": 1,
    "nodes": [
      { "id": "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e01", "key": "entry", "type": "flow.transform@1", "config": { "fields": { "v": 1 } }, "position": { "x": 0, "y": 140 } },
      { "id": "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e02", "key": "a", "type": "flow.transform@1", "config": { "fields": { "v": 2 } }, "position": { "x": 300, "y": 300 } },
      { "id": "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e03", "key": "b", "type": "flow.transform@1", "config": { "fields": { "v": 3 } }, "position": { "x": 300, "y": 440 } }
    ],
    "edges": [
      { "from": { "node": "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e02", "port": "out" }, "to": { "node": "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e03" } },
      { "from": { "node": "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e03", "port": "out" }, "to": { "node": "0b6c2f1e-1d1e-4c1e-8e1e-1e1e1e1e1e02" } }
    ]
  },
  "bindings": []
}
```

and, in `frontend/e2e/workflows.spec.ts`, a helper that imports a file through 1b (Task 8), and the walk:

```ts
async function importFile(page: Page, name: string, file: string): Promise<void> {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles(file);
  await expect(dialog.getByText("The file names no connection or workflow.")).toBeVisible();
  await expectAccessible(page, "new workflow: import");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}$/);
}

test("the keys reach every step of an imported cycle no entry leads into", async ({ page }) => {
  await importFile(page, "Cycle", "e2e/fixtures/cycle.dewpoint.json");
  const start = page.getByRole("button", { name: /^Start, where every run begins/ });
  await start.focus();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "Insert a step before entry" })).toBeFocused();
  await page.keyboard.press("ArrowRight"); // the cycle, linked under the start card
  await expect(page.getByRole("button", { name: /^a, Transform/ })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "Insert a step between a and b" })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: /^b, Transform/ })).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("button", { name: "Insert a step between b and a" })).toBeFocused();
  await page.keyboard.press("Home");
  await expect(start).toBeFocused();
  await expectAccessible(page, "editor: an imported cycle");
});
```

The step picker's search field filters by title and ref: typing `transform`, `flow.if` and `stop` picks those types
with Enter (cmdk selects the first match). The placed card's centre is compared on the screen: the card's size and
its position both scale with the zoom, so the centre lands under the click at any zoom.

- [ ] **Step 8: Run the tests to see them pass, then the gate**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`,
then the browser gate after a reset. Expected: PASS; `workflows` 4 passed.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/routes/editor frontend/e2e/workflows.spec.ts frontend/e2e/fixtures/cycle.dewpoint.json
git commit -m "feat(web): the canvas's keyboard reaches every item; steps placed by a click; A, Delete, connect, undo (D16, 4b)"
```

**Milestone 3's check, then the owner's pause.** The frontend suite, lint, types and build, then the browser gate after
a reset; all pass. Stop for the owner's review with the canvas under the real CSP and the accessibility proof (see
"Executing this plan"): the gate's results for each canvas flow, axe's for each canvas state, the reachability tests,
and screenshots of the canvas (blank, four steps, a step's panel, placing a step, an imported cycle). Milestone 4
waits for the owner's word.

## Milestone 4 — Saving, problems and publishing

### Task 13: Saving (D17): one save in flight, edits coalesced, `If-Match`; leaving saves first; a conflict never overwrites

**Files:**
- Create: `frontend/src/lib/draftSync.ts`, `frontend/src/lib/draftSync.test.ts`
- Create: `frontend/src/routes/editor/SaveState.tsx`
- Create: `frontend/src/lib/leaving.ts`, `frontend/src/lib/leaving.test.ts`
- Modify: `frontend/src/components/ConfirmDialog.tsx`, `frontend/src/components/ConfirmDialog.test.tsx` (`cancelLabel`)
- Modify: `frontend/src/components/Shell.tsx`, `frontend/src/components/Shell.test.tsx` (sign-out asks first; the
  ended-session notice)
- Modify: `frontend/src/router.tsx`, `frontend/src/router.test.tsx` (an ended session leaves unsaved work on screen)
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `PUT /api/v1/t/{tenant_id}/workflows/{workflow_id}/draft` (`If-Match: <revision>`, body `Graph`) →
  `DraftSavedOut` (`draft_revision`, `unpublished_changes`, `graph_hash`, `active_version_id`,
  `active_version_number`: Task 3), `409 draft_conflict`; `WorkflowDetailOut.draft_graph_hash`; `downloadJson`,
  `fileName`; TanStack Router 1.170.39's `useBlocker({ shouldBlockFn, enableBeforeUnload })`, whose `shouldBlockFn`
  may answer a promise, which the router awaits (verified in the installed package); TanStack Query 5.103.2's
  `refetchOnMount: "always"` and `isFetchedAfterMount` (verified).
- Produces:
  - `class DraftSync` (`new DraftSync({ revision, unpublished, savedHash, activeNumber, save, onChange, onSettled?,
    delayMs? })`; `change(doc)`, `flush(): Promise<number>`, `retry()`, `conflict()`, `dispose()`, `current:
    SyncState`, `unsaved: boolean`); `type SyncState = { status: "saved" | "pending" | "saving" | "conflict" |
    "error"; revision: number; unpublished: boolean | null; generation: number; savedGeneration: number; savedHash:
    string | null; activeNumber: number | null | "unknown" }`; `class ConflictError`, `class SaveError`;
    `onSettled(revision, generation)`.
  - `src/lib/leaving.ts`: `type LeaveGuard = { unsaved(): boolean; decide(): Promise<boolean> }`,
    `guardLeaving(guard) -> unsubscribe`, `unsavedWork()`, `mayLeave()`.
  - `ConfirmDialog`'s `cancelLabel?: string` (default "Cancel"); `Shell`'s `sessionEnded?: boolean`.
  - `<SaveState state />`: the active version's label comes from the same state as the comparison.
  - The editor opens on a snapshot read after it mounted, is seeded once, and stays open through its auxiliary
    queries' failures. Task 14 hooks `onSettled` and reads `generation`/`savedGeneration`; Task 15 calls `flush()`
    before publishing and exporting, and reads `savedHash`.

What this task guards (the owner's reviews of 325fc14, correction 1, and of revision 2, correction 2):
- **Leaving.** One decision, the editor's own (`decide`): save what's pending; when that can't be done (a failed
  save, a conflict), ask: stay, download my version, or leave without saving (4b ruling 22). It answers for every way
  out: router navigations (the breadcrumb, the rail, the palette, the tenant switcher) through the router's blocker,
  which awaits it; sign-out, which asks it (`mayLeave`) before it revokes the session or clears the query cache (a
  save after that could no longer authenticate, and the cleared cache must not unmount the editor first); and an
  ended session, which leaves the shell and its unsaved work on screen, with a notice, instead of swapping it for the
  sign-in page. `beforeunload` covers closing the tab.
- **Closing.** Once the editor closes, its saver is disposed: a save still in flight that answers afterwards sends
  nothing more and says nothing.
- **Opening, and staying open.** The editor never opens on a cached draft (it would conflict on the first edit): it
  waits for the read made after it mounted, then owns its document; a later read of the workflow neither replaces nor
  closes it. It keeps what it opened with (the workflow, the step types, the role): a failed refresh of the step
  types, or a cleared cache, shows beside it, never in its place (4b ruling 23).
- **A conflict's work.** The local version since the last save can't be saved; leaving asks, and Reload asks before
  discarding it.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/draftSync.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConflictError, DraftSync, SaveError, type Saved, type SyncState } from "./draftSync";
import type { GraphDoc } from "./workflows";

const doc = (n: number): GraphDoc => ({ graph_format: 1, nodes: [{ id: `n${n}`, key: `k${n}`, type: "flow.transform@1" }], edges: [] });
type Answer = () => Promise<Saved>;

let calls: { doc: GraphDoc; revision: number }[];
let inFlight: number;
let maxInFlight: number;
let answers: Answer[];
let states: SyncState["status"][];
let settled: number[];

/** A save's answer, as the API gives it: the next revision, its hash, and the version it was compared with. */
const saved = (revision: number, active: number | null = null): Saved => ({
  draft_revision: revision, unpublished_changes: true, graph_hash: `h${revision}`, active_version_id: active ? `v${active}` : null,
  active_version_number: active,
});  // prettier-ignore

function make() {
  return new DraftSync({
    revision: 1,
    unpublished: true,
    savedHash: "h1",
    activeNumber: null,
    delayMs: 1000,
    save: async (d, revision) => {
      calls.push({ doc: d, revision });
      inFlight++;
      maxInFlight = Math.max(maxInFlight, inFlight);
      try {
        return await (answers.shift() ?? (() => Promise.resolve(saved(revision + 1))))();
      } finally {
        inFlight--;
      }
    },
    onChange: (s) => states.push(s.status),
    onSettled: (r) => settled.push(r),
  });
}

/** A save that answers when the test says. */
function held(): () => void {
  let release!: () => void;
  answers.push(() => new Promise((r) => (release = () => r(saved(2)))));
  return () => release();
}

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  inFlight = 0;
  maxInFlight = 0;
  answers = [];
  states = [];
  settled = [];
});
afterEach(() => vi.useRealTimers());

it("saves a second after the last change, with the revision the last save returned", async () => {
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(500);
  sync.change(doc(2)); // within the second: coalesced
  await vi.advanceTimersByTimeAsync(999);
  expect(calls).toEqual([]);
  await vi.advanceTimersByTimeAsync(1);
  expect(calls).toEqual([{ doc: doc(2), revision: 1 }]);
  expect(sync.current).toEqual({
    status: "saved", revision: 2, unpublished: true, generation: 2, savedGeneration: 2, savedHash: "h2", activeNumber: null,
  });  // prettier-ignore
  expect(settled).toEqual([2]);
});

it("takes the active version and the hash from each save's answer", async () => {
  answers.push(() => Promise.resolve(saved(2, 3))); // version 3 became active elsewhere before this save landed
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  expect([sync.current.activeNumber, sync.current.savedHash]).toEqual([3, "h2"]);
});

it("edits during a save coalesce into exactly one next save, never two at once", async () => {
  const release = held();
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  sync.change(doc(2));
  sync.change(doc(3));
  await vi.advanceTimersByTimeAsync(5000);
  expect(calls.length).toBe(1); // still in flight: nothing else goes
  release();
  await vi.advanceTimersByTimeAsync(1000);
  expect(calls.map((c) => [c.doc, c.revision])).toEqual([[doc(1), 1], [doc(3), 2]]);
  expect(maxInFlight).toBe(1);
  expect(settled).toEqual([3]); // settled once, when nothing was left to save
});

it("counts each change, and says which one the server holds", async () => {
  const release = held();
  const sync = make();
  sync.change(doc(1));
  expect([sync.current.generation, sync.current.savedGeneration, sync.unsaved]).toEqual([1, 0, true]);
  await vi.advanceTimersByTimeAsync(1000); // generation 1 goes
  sync.change(doc(2));
  release();
  await vi.advanceTimersByTimeAsync(0);
  expect([sync.current.generation, sync.current.savedGeneration, sync.unsaved]).toEqual([2, 1, true]);
  await vi.advanceTimersByTimeAsync(1000);
  expect([sync.current.generation, sync.current.savedGeneration, sync.unsaved]).toEqual([2, 2, false]);
});

it("a 409 stops every save and keeps the document", async () => {
  answers.push(() => Promise.reject(new ConflictError()));
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  expect(sync.current.status).toBe("conflict");
  expect(sync.unsaved).toBe(true); // what leaving would lose
  sync.change(doc(2));
  await vi.advanceTimersByTimeAsync(5000);
  expect(calls.length).toBe(1);
  await expect(sync.flush()).rejects.toBeInstanceOf(ConflictError);
});

it("a conflict declared during a save stays a conflict when that save answers", async () => {
  const release = held();
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  sync.change(doc(2));
  sync.conflict(); // a publish's 409
  release();
  await vi.advanceTimersByTimeAsync(5000);
  expect(sync.current.status).toBe("conflict");
  expect(calls.length).toBe(1);
});

it("a failed save keeps the document for the next change or a retry, at the same revision", async () => {
  answers.push(() => Promise.reject(new Error("network")));
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  expect(sync.current.status).toBe("error");
  sync.retry();
  await vi.advanceTimersByTimeAsync(0);
  expect(calls.map((c) => [c.doc, c.revision])).toEqual([[doc(1), 1], [doc(1), 1]]);
  expect(sync.current.status).toBe("saved");
});

it("flush saves now what's pending, and answers the revision publish must name", async () => {
  const sync = make();
  sync.change(doc(1));
  const flushed = sync.flush();
  await vi.advanceTimersByTimeAsync(0);
  await expect(flushed).resolves.toBe(2);
  expect(calls.length).toBe(1);
  await expect(sync.flush()).resolves.toBe(2); // nothing pending: no save
  expect(calls.length).toBe(1);
});

it("flush says when the draft couldn't be saved, after trying once more", async () => {
  answers.push(() => Promise.reject(new Error("network")), () => Promise.reject(new Error("network")));
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  const flushed = expect(sync.flush()).rejects.toBeInstanceOf(SaveError);
  await vi.advanceTimersByTimeAsync(0);
  await flushed;
  expect(calls.length).toBe(2);
});

it("once closed, a save in flight that answers sends nothing more and says nothing", async () => {
  const release = held();
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  sync.change(doc(2)); // waits for the save in flight
  sync.dispose();
  const said = states.length;
  release();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(calls.length).toBe(1);
  expect(states.length).toBe(said);
  expect(settled).toEqual([]);
  await expect(sync.flush()).rejects.toBeInstanceOf(SaveError);
});
```

In `frontend/src/components/ConfirmDialog.test.tsx`:

```tsx
it("names its cancel when asked", () => {
  render(
    <ConfirmDialog open title="Your latest changes aren't saved" confirmLabel="Leave without saving" cancelLabel="Stay" onConfirm={vi.fn()} onCancel={vi.fn()}>
      They couldn&apos;t be saved.
    </ConfirmDialog>,
  );
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Stay" }));
});
```

`frontend/src/lib/leaving.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { expect, it, vi } from "vitest";
import { guardLeaving, mayLeave, unsavedWork } from "./leaving";

it("lets leaving go on only when every open editor agrees, asking each in turn", async () => {
  expect(await mayLeave()).toBe(true); // nothing open
  const first = vi.fn(async () => true);
  const second = vi.fn(async () => false);
  const third = vi.fn(async () => true);
  const stops = [first, second, third].map((decide) => guardLeaving({ unsaved: () => false, decide }));
  expect(await mayLeave()).toBe(false);
  expect([first, second, third].map((f) => f.mock.calls.length)).toEqual([1, 1, 0]); // stops at the first "stay"
  stops.forEach((stop) => stop());
  expect(await mayLeave()).toBe(true);
});

it("says whether any open editor holds unsaved work", () => {
  let dirty = false;
  const stop = guardLeaving({ unsaved: () => dirty, decide: async () => true });
  expect(unsavedWork()).toBe(false);
  dirty = true;
  expect(unsavedWork()).toBe(true);
  stop();
  expect(unsavedWork()).toBe(false);
});
```

In `frontend/src/components/Shell.test.tsx`:

```tsx
const loggedOut = () => vi.mocked(globalThis.fetch).mock.calls.some(([input]) => (input as Request).url.endsWith("/api/v1/auth/logout"));

it("signs out only once every open editor has had its say", async () => {
  await renderAt("/t/t1/connections");
  const stop = guardLeaving({ unsaved: () => true, decide: async () => false }); // the person chose to stay
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(loggedOut()).toBe(false);
  stop();
  const go = guardLeaving({ unsaved: () => true, decide: async () => true });
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  await vi.waitFor(() => expect(loggedOut()).toBe(true));
  go();
});
```

(`guardLeaving` from `../lib/leaving` and `userEvent` join its imports.) In `frontend/src/router.test.tsx`, `showApp`
keeps its QueryClient in a module-level `client`, the session's answer follows a flag (`let sessionGone = false`, reset
in `beforeEach`: `if (key === "GET /api/v1/auth/session") return sessionGone ? json({ error: "unauthorized" }, 401) :
json(SESSION);`), and:

```tsx
it("leaves unsaved editor work on screen when the session ends, and says so", async () => {
  const stop = guardLeaving({ unsaved: () => true, decide: async () => true });
  try {
    const router = showApp("/t/t1/connections");
    await screen.findByRole("button", { name: "Add Mist connection" });
    sessionGone = true;
    await act(() => client.invalidateQueries({ queryKey: ["session"] }));
    expect((await screen.findByRole("alert", { name: "Session ended" })).textContent).toContain("Your session has ended");
    expect(router.state.location.pathname).toBe("/t/t1/connections");
  } finally {
    stop();
  }
});

it("goes to sign-in when the session ends with nothing unsaved", async () => {
  const router = showApp("/t/t1/connections");
  await screen.findByRole("button", { name: "Add Mist connection" });
  sessionGone = true;
  await act(() => client.invalidateQueries({ queryKey: ["session"] }));
  await vi.waitFor(() => expect(router.state.location.pathname).toBe("/login"));
});
```

(`guardLeaving` from `./lib/leaving` joins its imports.)

In `frontend/src/routes/editor/Editor.test.tsx` (Task 11's helpers: `answers`, `json`, `sent`, `drawn`, `draftWith`,
`show({ seed })`), `beforeEach` gains the draft PUT's answer:

```tsx
  answers.set(`PUT ${BASE}/draft`, () =>
    json({ draft_revision: 2, unpublished_changes: true, graph_hash: "h2", active_version_id: null, active_version_number: null }),
  );
```

and:

```tsx
async function addTransform() {
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await screen.findByRole("button", { name: "transform" });
}

it("saves an edit with the revision it was loaded at, and says so", async () => {
  await show();
  await addTransform();
  expect(screen.getByText("Unsaved changes")).toBeTruthy();
  await vi.waitFor(() => expect(sent.find((r) => r.method === "PUT")).toBeTruthy(), { timeout: 3000 });
  const put = sent.find((r) => r.method === "PUT")!;
  expect(put.headers.get("If-Match")).toBe("1");
  expect((put.body as GraphDoc).nodes!.map((n) => n.key)).toEqual(["transform"]);
  await screen.findByText("Saved · not published");
});

it("opens on the server's draft, never a cached one", async () => {
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 7, draft: draftWith("fresh") }));
  await show({ seed: (qc) => qc.setQueryData(["workflow", "t1", "w1"], { ...WORKFLOW, draft: draftWith("old") }) });
  expect(screen.getByRole("button", { name: "fresh" })).toBeTruthy();
  expect(drawn.some((d) => d.doc.nodes?.some((n) => n.key === "old"))).toBe(false);
});

it("keeps its own document when the workflow is read again while it's open", async () => {
  const { qc } = await show();
  await addTransform();
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 9, draft: draftWith("other") }));
  await qc.refetchQueries({ queryKey: ["workflow", "t1", "w1"] });
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "other" })).toBeNull();
});

it("saves before leaving through a link, then leaves", async () => {
  const { router } = await show();
  await addTransform();
  expect(screen.getByText("Unsaved changes")).toBeTruthy(); // inside the debounce
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  await screen.findByText("list");
  expect(sent.filter((r) => r.method === "PUT")).toHaveLength(1);
  expect(router.state.location.pathname).toBe("/t/t1/workflows");
});

it("asks before leaving work it couldn't save; staying keeps it", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  await show();
  await addTransform();
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  expect(within(ask).getByRole("button", { name: "Download my version" })).toBeTruthy();
  await userEvent.click(within(ask).getByRole("button", { name: "Stay" }));
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  const again = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  await userEvent.click(within(again).getByRole("button", { name: "Leave without saving" }));
  await screen.findByText("list");
});

it("turns read-only on a conflict, keeping the work downloadable and leaving guarded", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "draft_conflict", draft_revision: 5 }, 409));
  await show();
  await addTransform();
  const alert = await screen.findByRole("alert", {}, { timeout: 3000 });
  expect(alert.textContent).toContain("changed elsewhere");
  expect(screen.queryByRole("button", { name: /Add step/ })).toBeNull();
  expect(within(alert).getByRole("button", { name: "Download my version" })).toBeTruthy();
  await userEvent.click(screen.getByRole("link", { name: "Workflows" }));
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  expect(ask.textContent).toContain("changed elsewhere");
  await userEvent.click(within(ask).getByRole("button", { name: "Stay" }));
});

it("answers sign-out's question with the same decision: staying keeps the work", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  await show();
  await addTransform();
  const decision = mayLeave(); // what the shell's Sign out asks before it revokes anything
  const ask = await screen.findByRole("dialog", { name: "Your latest changes aren't saved" });
  await userEvent.click(within(ask).getByRole("button", { name: "Stay" }));
  await expect(decision).resolves.toBe(false);
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
});

it("stays open, with its edits, when the step types fail to refresh or the cache is cleared", async () => {
  const { qc } = await show();
  await addTransform();
  answers.set("GET /api/v1/node-types", () => json({ error: "http_error" }, 500));
  await act(() => qc.refetchQueries({ queryKey: ["node-types"] }));
  expect(await screen.findByText(/The step types couldn't be refreshed/)).toBeTruthy();
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
  act(() => qc.clear());
  expect(screen.getByRole("button", { name: "transform" })).toBeTruthy();
  expect(screen.getByRole("group", { name: "Workflow steps" })).toBeTruthy();
});

it("asks before Reload discards the version a conflict kept", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "draft_conflict", draft_revision: 5 }, 409));
  await show();
  await addTransform();
  const alert = await screen.findByRole("alert", {}, { timeout: 3000 });
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft_revision: 5, draft: draftWith("theirs") }));
  await userEvent.click(within(alert).getByRole("button", { name: "Reload" }));
  const ask = screen.getByRole("dialog", { name: "Reload the saved draft" });
  await userEvent.click(within(ask).getByRole("button", { name: "Discard my version and reload" }));
  expect(await screen.findByRole("button", { name: "theirs" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "transform" })).toBeNull();
});
```

(`within` and `act` join the Testing Library import, `mayLeave` comes from `../../lib/leaving`; `GraphDoc` is imported
for the PUT body's type.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib/draftSync.test.ts src/lib/leaving.test.ts src/components/ConfirmDialog.test.tsx src/components/Shell.test.tsx src/router.test.tsx src/routes/editor/Editor.test.tsx`
Expected: FAIL: `draftSync.ts` and `leaving.ts` don't exist; no `cancelLabel`; sign-out doesn't ask and an ended
session drops to sign-in; the editor never saves, opens on the cached draft, leaves without saving, and closes when
the step types fail to refresh.

- [ ] **Step 3: Implement the saver**

`frontend/src/lib/draftSync.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// Saving the draft (D17). At most one save in flight; edits made meanwhile coalesce into the next save, sent a
// second after the last change, with `If-Match` the revision the previous save returned, so the editor never
// conflicts with itself. A 409 means someone else saved: every save stops and the document stays with the person
// (read-only, downloadable), never sent over theirs. A failed save keeps the document for the next try. Each change
// is counted (`generation`) and the state says which one the server holds (`savedGeneration`): what leaving would
// lose (4b ruling 22), and whether a check of the saved draft is a check of what's on the screen (ruling 24). Once
// disposed (the editor closed), nothing more is sent or said, even when a save in flight answers.
import type { GraphDoc } from "./workflows";

export type SyncStatus = "saved" | "pending" | "saving" | "conflict" | "error";
export interface SyncState {
  status: SyncStatus;
  revision: number; // the revision the server holds of what was last saved
  unpublished: boolean | null; // that draft differs from the active version (the server's word); null: not known
  generation: number; // the editor's changes so far
  savedGeneration: number; // the change `revision` holds: `generation` when nothing is unsaved
  savedHash: string | null; // the server's graph hash of the draft at `revision` (what a version holding it records)
  activeNumber: number | null | "unknown"; // the active version, from the same answer as `unpublished`; null: none
}
export type Saved = {
  draft_revision: number;
  unpublished_changes: boolean;
  graph_hash: string | null;
  active_version_id: string | null;
  active_version_number: number | null;
};

export class ConflictError extends Error {
  constructor() {
    super("the draft changed elsewhere");
  }
}

export class SaveError extends Error {
  constructor() {
    super("the draft isn't saved");
  }
}

export class DraftSync {
  private state: SyncState;
  private latest: { doc: GraphDoc; generation: number } | null = null; // the newest change not yet sent
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inflight: Promise<void> | null = null;
  private disposed = false;

  constructor(
    private readonly opts: {
      revision: number;
      unpublished: boolean | null;
      savedHash: string | null;
      activeNumber: number | null;
      save: (doc: GraphDoc, revision: number) => Promise<Saved>;
      onChange: (state: SyncState) => void;
      onSettled?: (revision: number, generation: number) => void;
      delayMs?: number;
    },
  ) {
    this.state = {
      status: "saved",
      revision: opts.revision,
      unpublished: opts.unpublished,
      generation: 0,
      savedGeneration: 0,
      savedHash: opts.savedHash,
      activeNumber: opts.activeNumber,
    };
  }

  get current(): SyncState {
    return this.state;
  }

  /** Whether a change isn't on the server: what leaving now would lose. */
  get unsaved(): boolean {
    return this.state.generation !== this.state.savedGeneration;
  }

  private set(patch: Partial<SyncState>) {
    this.state = { ...this.state, ...patch };
    if (!this.disposed) this.opts.onChange(this.state);
  }

  private stopTimer() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }

  private schedule(ms = this.opts.delayMs ?? 1000) {
    if (this.disposed) return;
    this.stopTimer();
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.run();
    }, ms);
  }

  change(doc: GraphDoc): void {
    if (this.disposed || this.state.status === "conflict") return;
    const generation = this.state.generation + 1;
    this.latest = { doc, generation };
    this.set(this.inflight ? { generation } : { generation, status: "pending" });
    this.schedule();
  }

  /** Try again now after a failed save. */
  retry(): void {
    if (this.state.status === "error" && this.latest) this.schedule(0);
  }

  /** Someone else saved (a publish's 409 says so too): stop saving. */
  conflict(): void {
    this.stopTimer();
    this.set({ status: "conflict" });
  }

  private run(): Promise<void> {
    if (this.disposed || this.inflight || this.latest === null || this.state.status === "conflict") {
      return this.inflight ?? Promise.resolve();
    }
    const sent = this.latest;
    this.latest = null;
    this.set({ status: "saving" });
    this.inflight = (async () => {
      try {
        const saved = await this.opts.save(sent.doc, this.state.revision);
        // One answer, one identity: the comparison and the version it was made against (Task 3) travel together.
        this.state = {
          ...this.state,
          revision: saved.draft_revision,
          unpublished: saved.unpublished_changes,
          savedGeneration: sent.generation,
          savedHash: saved.graph_hash,
          activeNumber: saved.active_version_number,
        };
      } catch (e) {
        if (e instanceof ConflictError) {
          this.set({ status: "conflict" });
        } else {
          this.latest ??= sent;
          this.set({ status: "error" });
        }
        return;
      } finally {
        this.inflight = null;
      }
      // Closed: no further save and no news. Declared a conflict meanwhile: it stays one.
      if (this.disposed || this.state.status === "conflict") return;
      if (this.latest !== null) {
        this.set({ status: "pending" });
        this.schedule();
      } else {
        this.set({ status: "saved" });
        this.opts.onSettled?.(this.state.revision, this.state.savedGeneration);
      }
    })();
    return this.inflight;
  }

  /** Save now whatever is pending; answer the revision saved (publish's `If-Match`). Rejects with ConflictError on a
   * conflict, and SaveError on a failed save or a closed editor: nothing is published, exported or left behind
   * over what isn't saved. */
  async flush(): Promise<number> {
    for (;;) {
      if (this.disposed) throw new SaveError();
      if (this.state.status === "conflict") throw new ConflictError();
      this.stopTimer();
      if (this.inflight) await this.inflight;
      else if (this.latest !== null) await this.run();
      else break;
      if (this.state.status === "error") throw new SaveError();
    }
    return this.state.revision;
  }

  /** The editor closed: stop, and drop whatever wasn't sent. */
  dispose(): void {
    this.disposed = true;
    this.stopTimer();
    this.latest = null;
  }
}
```

`frontend/src/routes/editor/SaveState.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The draft's state, in words, beside the workflow's name (1c's "Saved"): never a colour alone, and never a claim
// the editor can't back. The active version and the comparison come from one state, so from one answer: `unpublished`
// is null when the comparison isn't known, `activeNumber` "unknown" when the active version isn't.
import type { SyncState } from "../../lib/draftSync";

export function SaveState({ state }: { state: SyncState }) {
  const active = state.activeNumber;
  const text =
    state.status === "pending" ? "Unsaved changes"
    : state.status === "saving" ? "Saving…"
    : state.status === "error" ? "Not saved"
    : state.status === "conflict" ? "Changed elsewhere"
    : active === "unknown" ? "Saved · the active version isn't known"
    : active === null ? "Saved · not published"
    : state.unpublished === null ? `Saved · v${active} is active`
    : state.unpublished ? `Saved · unpublished changes since v${active}`
    : `Saved · published as v${active}`;  // prettier-ignore
  const tone = state.status === "error" || state.status === "conflict" ? "text-danger" : state.status === "saved" ? "text-ok" : "text-muted";
  return <span className={`text-small ${tone}`}>{text}</span>;
}
```

In `frontend/src/components/ConfirmDialog.tsx`, the props gain `cancelLabel = "Cancel"` (`cancelLabel?: string`), and
the cancel button reads `{cancelLabel}`.

- [ ] **Step 4: Ask before leaving, from anywhere**

`frontend/src/lib/leaving.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// What an open editor says before something takes the person out of it without the router (4b ruling 22): sign-out,
// an ended session. Router navigations ask the editor through its own blocker; these ask through here, before they
// revoke anything or clear any cache.
export interface LeaveGuard {
  /** Whether it holds work the server hasn't got. */
  unsaved: () => boolean;
  /** Saves what it can; when it can't, asks the person. True: leaving may go on. */
  decide: () => Promise<boolean>;
}

const guards = new Set<LeaveGuard>();

export function guardLeaving(guard: LeaveGuard): () => void {
  guards.add(guard);
  return () => void guards.delete(guard);
}

export const unsavedWork = (): boolean => [...guards].some((g) => g.unsaved());

/** Every open editor's say, in turn; the first "stay" ends it. */
export async function mayLeave(): Promise<boolean> {
  for (const g of [...guards]) if (!(await g.decide())) return false;
  return true;
}
```

In `frontend/src/components/Shell.tsx`, sign-out asks first, and an ended session has its notice (import `mayLeave`
from `../lib/leaving`; `Shell` takes `{ sessionEnded = false }: { sessionEnded?: boolean }`):

```tsx
  async function handleSignOut() {
    setSignOutError(null);
    // An open editor has its say first (4b ruling 22): it saves what's pending, or asks. Only then is the session
    // revoked and the cache cleared, which would leave a pending save unable to authenticate.
    if (!(await mayLeave())) return;
    if ((await signOut()) === "failed") {
```

(the rest unchanged), and, beside the sign-out error:

```tsx
        {sessionEnded && (
          <div role="alert" aria-label="Session ended" className="flex flex-wrap items-center gap-3 border-b border-danger bg-danger-bg px-5 py-2.5 text-small text-ink">
            <span className="grow">
              Your session has ended, and this page holds changes that aren&apos;t saved. Download them from the editor,
              then sign in again.
            </span>
            <Button size="sm" onClick={() => void navigate({ to: "/login" })}>Sign in again</Button>
          </div>
        )}
```

In `frontend/src/router.tsx`, `RequireActive` keeps the shell on screen when the session ends under unsaved work
(import `unsavedWork` from `./lib/leaving`):

```tsx
  // Work an editor couldn't save stays on screen when the session ends (4b ruling 22): never swapped for the sign-in
  // page under it. "Sign in again" is a router navigation, so the editor has its say first.
  if (!session.data) return unsavedWork() ? <Shell sessionEnded /> : <Navigate to="/login" />;
```

- [ ] **Step 5: Open on a fresh snapshot, and stay open**

In `frontend/src/routes/editor/Editor.tsx`, `EditorPage` opens the editor once, from the first read made after it
mounted, and keeps what it opened with (import `useEffect`, `useQueryClient`, `type WorkflowDetail`):

```tsx
type Opened = { workflow: WorkflowDetail; types: NodeType[]; role: string | null };

export function EditorPage({ tenantId, workflowId }: { tenantId: string; workflowId: string }) {
  const qc = useQueryClient();
  // A draft cached from an earlier visit would conflict on the first edit (4b ruling 23): the editor waits for the read
  // made after this page mounted. Once open it owns its document and keeps what it opened with: a later read, a
  // failed refresh or a cleared cache neither replaces nor closes it.
  const workflow = useQuery({
    ...workflowQuery(tenantId, workflowId),
    refetchOnMount: "always",
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  const types = useQuery(nodeTypesQuery);
  const tenant = useQuery(tenantQuery(tenantId));
  const [opened, setOpened] = useState<Opened | null>(null);
  const [loads, setLoads] = useState(0);
  useEffect(() => {
    if (opened !== null || !workflow.isFetchedAfterMount || !workflow.isSuccess || !types.data || !tenant.data) return;
    setOpened({ workflow: workflow.data, types: types.data, role: tenant.data.role ?? null });
  }, [opened, workflow.isFetchedAfterMount, workflow.isSuccess, workflow.data, types.data, tenant.data]);
  useDocumentTitle(opened?.workflow.name ?? "Workflow");

  /** After a conflict: the saved draft, read afresh, in a new editor. */
  const reload = async () => {
    await qc.invalidateQueries({ queryKey: ["workflow", tenantId, workflowId] });
    setOpened(null);
    setLoads((n) => n + 1);
  };

  if (opened === null) {
    if (workflow.isError) return <section className="p-6"><LoadError what="This workflow" /></section>;
    if (types.isError && !types.data) return <section className="p-6"><LoadError what="The step types" /></section>;
    if (tenant.isError && !tenant.data) return <section className="p-6"><LoadError what="This tenant" /></section>;
    return <p className="p-6 text-body text-muted">Loading…</p>;
  }
  const trouble = types.isError ? "The step types couldn't be refreshed: the editor keeps the ones it opened with." : null;
  return (
    <Editor
      key={loads}
      tenantId={tenantId}
      workflow={opened.workflow}
      types={types.data ?? opened.types}
      role={opened.role}
      trouble={trouble}
      onReload={() => void reload()}
    />
  );
}
```

A failed first read shows the error, never the cached copy: `isSuccess` is false after a failed fetch even when old
data is cached, and `isFetchedAfterMount` is false until the read made after mounting ends. Once open, nothing but
Reload (or leaving) closes the editor.

- [ ] **Step 6: Save, decide on leaving, and keep a conflict's work**

In `Editor` (which takes `trouble` and `onReload`; imports: `useBlocker`, `useRef`, `ApiError`, `client`, `ok`,
`ConflictError`, `DraftSync`, `type SyncState`, `downloadJson`, `fileName`, `guardLeaving`, `ConfirmDialog`,
`SaveState`):

```tsx
  const [sync, setSyncState] = useState<SyncState>({
    status: "saved", revision: workflow.draft_revision, unpublished: workflow.unpublished_changes, generation: 0,
    savedGeneration: 0, savedHash: workflow.draft_graph_hash, activeNumber: workflow.active_version_number,
  });  // prettier-ignore
  const saver = useRef<DraftSync | null>(null);
  // Made in an effect, so StrictMode's second mount (main.tsx) gets a live saver: its cleanup disposes the first.
  useEffect(() => {
    const s = new DraftSync({
      revision: workflow.draft_revision,
      unpublished: workflow.unpublished_changes,
      savedHash: workflow.draft_graph_hash,
      activeNumber: workflow.active_version_number,
      onChange: setSyncState,
      save: async (next, revision) => {
        try {
          return await ok(
            client.PUT("/api/v1/t/{tenant_id}/workflows/{workflow_id}/draft", {
              params: { path: { tenant_id: tenantId, workflow_id: workflow.id }, header: { "If-Match": String(revision) } },
              body: next,
            }),
          );
        } catch (e) {
          if (e instanceof ApiError && e.status === 409) throw new ConflictError();
          throw e;
        }
      },
    });
    saver.current = s;
    return () => s.dispose();
  }, [tenantId, workflow]);
  const editable = canEdit(role) && sync.status !== "conflict";
  const downloadMine = () => downloadJson(fileName(workflow.name, ".draft.json"), doc);

  // Leaving's one decision (4b ruling 22): save what's pending; when that can't be done (a failed save, a conflict),
  // ask the person, and answer with their choice. The router's blocker awaits it for every navigation (the
  // breadcrumb, the rail, the palette, the tenant switcher); sign-out and an ended session ask it through `leaving`.
  const [leaveQuestion, setLeaveQuestion] = useState<((leave: boolean) => void) | null>(null);
  const decide = useRef(async (): Promise<boolean> => true);
  decide.current = async () => {
    const s = saver.current;
    if (!s?.unsaved) return true;
    try {
      await s.flush();
      return true;
    } catch {
      return new Promise<boolean>((resolve) => setLeaveQuestion(() => resolve));
    }
  };
  useEffect(() => guardLeaving({ unsaved: () => saver.current?.unsaved ?? false, decide: () => decide.current() }), []);
  useBlocker({
    shouldBlockFn: async () => !(await decide.current()),
    enableBeforeUnload: () => saver.current?.unsaved ?? false,
  });
  const answer = (leave: boolean) => {
    leaveQuestion?.(leave);
    setLeaveQuestion(null);
  };
  const [reloading, setReloading] = useState(false);
```

`change` and undo/redo hand each new document to the saver:

```tsx
  function change(next: GraphDoc, message: string, then?: string) {
    setHistory((h) => record(h, next));
    saver.current?.change(next);
    announce(message);
    if (then) focus(then);
  }
```

```tsx
    const next = e.shiftKey ? redo(history) : undo(history);
    if (next === history) return;
    setHistory(next);
    saver.current?.change(next.present);
    announce(e.shiftKey ? "Redone" : "Undone");
```

The toolbar shows `<SaveState state={sync} />` first, and a Retry button when `sync.status === "error"`
(`onClick={() => saver.current?.retry()}`). Its "Read only" note now depends on the role alone (a conflict has its own
banner): `{editable ? <AddStep /> : !canEdit(role) ? <span …>Read only: your role can't edit workflows</span> :
null}`. Below the toolbar, an auxiliary failure, and a conflict:

```tsx
      {trouble && <p role="status" className="border-b border-line bg-surface px-5 py-2.5 text-small text-muted">{trouble}</p>}
      {sync.status === "conflict" && (
        <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-danger bg-danger-bg px-5 py-2.5 text-small text-ink">
          <span className="grow">
            This draft was changed elsewhere, so your changes since then aren&apos;t saved. Reload to see the saved draft, or
            download your version to keep it.
          </span>
          <Button size="sm" onClick={downloadMine}>Download my version</Button>
          <Button size="sm" variant="primary" onClick={() => setReloading(true)}>Reload</Button>
        </div>
      )}
```

and, with the other dialogs:

```tsx
      <ConfirmDialog
        open={leaveQuestion !== null}
        title="Your latest changes aren't saved"
        confirmLabel="Leave without saving"
        cancelLabel="Stay"
        onConfirm={() => answer(true)}
        onCancel={() => answer(false)}
      >
        {sync.status === "conflict"
          ? "This draft was changed elsewhere, so your changes since then can't be saved here. "
          : "They couldn't be saved. Stay to try again, or keep a copy before you leave. "}
        <Button size="sm" onClick={downloadMine}>Download my version</Button>
      </ConfirmDialog>
      <ConfirmDialog
        open={reloading}
        title="Reload the saved draft"
        confirmLabel="Discard my version and reload"
        onConfirm={() => {
          setReloading(false);
          onReload();
        }}
        onCancel={() => setReloading(false)}
      >
        Your version since the conflict is discarded. Download it first to keep it.
      </ConfirmDialog>
```

The banners' borders are full 1 px bottom rules, not side stripes (outline §6); `ink` on `danger-bg` is in PAIRS. An
editor that unmounts while its question is open (a Reload can't: the dialog is modal) leaves the promise unanswered,
and the router's navigation with it, which is the safe side: nothing leaves.

- [ ] **Step 7: Run the tests to see them pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib src/components src/router.test.tsx src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean (Members' removal dialog keeps its "Cancel").

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/draftSync.ts frontend/src/lib/draftSync.test.ts frontend/src/lib/leaving.ts frontend/src/lib/leaving.test.ts \
  frontend/src/components frontend/src/router.tsx frontend/src/router.test.tsx frontend/src/routes/editor
git commit -m "feat(web): the draft saves itself and leaving saves first; a fresh snapshot on entry; a conflict never overwrites (D17, 4b)"
```

### Task 14: Problems: a check is of one saved revision, said to be current only while it's what's on the screen

**Files:**
- Create: `frontend/src/routes/editor/check.ts`, `frontend/src/routes/editor/check.test.ts`
- Create: `frontend/src/routes/editor/ProblemsPanel.tsx`, `frontend/src/routes/editor/ProblemsPanel.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `POST …/validate` → `ValidationOut` (`draft_revision`, `valid`, `diagnostics`, `expressions`); the saver's
  `onSettled` and `SyncState`'s `revision`, `generation`, `savedGeneration` (Task 13); `StepPanel`'s `problems:
  Diagnostic[] | null` and `expressions` (Task 12).
- Produces: (`check.ts`) `type Check = {status: "unchecked"} | {status: "checking", last} | {status: "failed", last} |
  {status: "done", last}`, `type CheckState = "unchecked" | "checking" | "failed" | "stale" | "current"`,
  `checkState(check, sync)`, `lastOf(check)`, `checkLabel(state, count)`; `<ProblemsPanel state validation
  publishProblems publishCurrent keyOf onJump onCheck onClose />`, `type PublishProblems = { revision: number;
  generation: number; diagnostics: Diagnostic[] }` (Task 15 sets it: the snapshot a refused publish was for); the
  editor's right column holds one panel at a time: `type Side = { kind: "step"; node: string } | { kind: "problems" } |
  { kind: "versions" } | null`.

4b ruling 24 (the owner's review of 325fc14, correction 2): a check is of the saved revision it names, and is
**current** only while that revision is the one saved and nothing was edited since (`generation ===
savedGeneration`). Before the first answer the toolbar says "Checking…" (an editor checks on opening) or "Not
checked", never "No problems"; a failed check says "Check failed" and offers to check again, never keeping an
earlier answer's reassurance; an answer for an older revision, or one followed by edits, is **stale**: shown in the
panel as of before the edits, never as badges on the steps. What only publish found carries its own snapshot (the
revision and the generation it was for, the owner's review of revision 2): it counts, badges steps and shows in a
step's panel only while that snapshot is what's on the screen; afterwards it stays in the panel's "Found at publish",
marked as from before the latest edits. Revision 1 dropped older answers silently and kept
"No problems" through a failed request.

- [ ] **Step 1: Write the failing tests**

`frontend/src/routes/editor/check.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import type { Validation } from "../../lib/workflows";
import { checkLabel, checkState } from "./check";

const answer = (revision: number): Validation => ({
  draft_revision: revision, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] },
});  // prettier-ignore
const sync = (revision: number, generation = 0, savedGeneration = generation) => ({ revision, generation, savedGeneration });

it("says nothing reassuring before the first answer", () => {
  expect(checkLabel(checkState({ status: "unchecked" }, sync(1)), 0)).toBe("Not checked");
  expect(checkLabel(checkState({ status: "checking", last: null }, sync(1)), 0)).toBe("Checking…");
});

it("is current only for the saved revision that's on the screen", () => {
  expect(checkState({ status: "done", last: answer(2) }, sync(2, 3))).toBe("current");
  expect(checkState({ status: "done", last: answer(1) }, sync(2, 3))).toBe("stale"); // an older revision's
  expect(checkState({ status: "done", last: answer(2) }, sync(2, 4, 3))).toBe("stale"); // edited since
});

it("says a failed check failed, whatever an earlier one found", () => {
  expect(checkLabel(checkState({ status: "failed", last: answer(2) }, sync(2)), 0)).toBe("Check failed");
});

it("words a stale check by what it found then", () => {
  expect(checkLabel("stale", 0)).toBe("Not checked since your edits");
  expect(checkLabel("stale", 2)).toBe("Problems · 2, before your edits");
  expect(checkLabel("current", 0)).toBe("No problems");
  expect(checkLabel("current", 3)).toBe("Problems · 3");
});
```

`frontend/src/routes/editor/ProblemsPanel.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { CheckState } from "./check";
import { ProblemsPanel } from "./ProblemsPanel";

const d = (code: string, node: string | null, severity: "error" | "warning", message = code) =>
  ({ code, message, node, field: node ? "/fields" : null, fix: `fix ${code}`, severity });
const VALIDATION = {
  draft_revision: 4, valid: false, taint: { sites: [], declassified: [] },
  diagnostics: [d("config.invalid", "n1", "error", "fields needs at least one entry"), d("vars.unassigned", null, "warning")],
  expressions: [
    { node: "n1", field: "/fields/a", mode: "activity" as const, reason: "builds a message" },
    { node: "n1", field: "/fields/b", mode: "local" as const, reason: null },
  ],
};  // prettier-ignore
const CLEAN = { ...VALIDATION, valid: true, diagnostics: [], expressions: [] };
const keyOf = (id: string) => ({ n1: "transform" })[id] ?? id;

function panel(state: CheckState, validation: typeof VALIDATION | null, more: Partial<Parameters<typeof ProblemsPanel>[0]> = {}) {
  return render(
    <ProblemsPanel state={state} validation={validation} publishProblems={null} publishCurrent={false} keyOf={keyOf} onJump={vi.fn()} onCheck={vi.fn()} onClose={vi.fn()} {...more} />,
  );
}

it("lists errors before warnings, each with its fix and code, a step's going to the step", async () => {
  const onJump = vi.fn();
  panel("current", VALIDATION, { onJump });
  const items = within(screen.getByRole("complementary", { name: "Problems" })).getAllByRole("listitem");
  expect(items[0]!.textContent).toContain("fields needs at least one entry");
  expect(items[0]!.textContent).toContain("fix config.invalid");
  expect(items[1]!.textContent).toContain("vars.unassigned");
  await userEvent.click(within(items[0]!).getByRole("button", { name: "Go to transform" }));
  expect(onJump).toHaveBeenCalledWith("n1");
});

it("says how each expression runs (engine-core §5.10)", () => {
  panel("current", VALIDATION);
  expect(screen.getByText(/Runs as a separate step: builds a message/)).toBeTruthy();
  expect(screen.getByText("1 expression runs inline.")).toBeTruthy();
});

it("shows what only publish checks apart, and says when edits came since", () => {
  const found = { revision: 3, generation: 2, diagnostics: [d("connection.unknown", "n1", "error", "That connection doesn't exist.")] };
  panel("current", VALIDATION, { publishProblems: found, publishCurrent: false });
  const section = screen.getByRole("region", { name: "Found at publish" });
  expect(section.textContent).toContain("That connection doesn't exist.");
  expect(section.textContent).toContain("before your latest edits");
});

it("calls the saved draft clean only when the check is current", () => {
  const { unmount } = panel("current", CLEAN);
  expect(screen.getByText(/None found in the saved draft/)).toBeTruthy();
  unmount();
  panel("stale", CLEAN);
  expect(screen.queryByText(/None found/)).toBeNull();
  expect(screen.getByText(/before your latest edits/)).toBeTruthy();
});

it("says a failed check failed, and checks again when asked", async () => {
  const onCheck = vi.fn();
  panel("failed", CLEAN, { onCheck });
  expect(screen.getByText(/The check failed/)).toBeTruthy();
  expect(screen.queryByText(/None found/)).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Check again" }));
  expect(onCheck).toHaveBeenCalled();
});
```

In `frontend/src/routes/editor/Editor.test.tsx`:

```tsx
const valid = (revision: number) => ({ draft_revision: revision, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] } });
const invalid = (revision: number, node: string | null) => ({
  draft_revision: revision, valid: false, expressions: [], taint: { sites: [], declassified: [] },
  diagnostics: [{ code: "config.invalid", message: "fields needs at least one entry", node, field: "/fields", fix: null, severity: "error" }],
});  // prettier-ignore
const checks = () => sent.filter((r) => r.path.endsWith("/validate")).length;
const steps = () => screen.getByRole("group", { name: "Workflow steps" });

it("says it's checking before the first answer, never No problems", async () => {
  let answer: ((r: Response) => void) | undefined;
  answers.set(`POST ${BASE}/validate`, () => new Promise<Response>((r) => (answer = r)));
  await show();
  expect(screen.getByRole("button", { name: "Checking…" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "No problems" })).toBeNull();
  await vi.waitFor(() => expect(answer).toBeDefined());
  answer!(json(valid(1)));
  expect(await screen.findByRole("button", { name: "No problems" })).toBeTruthy();
});

it("checks the saved revision once a save settles, and counts its problems on the steps", async () => {
  answers.set(`POST ${BASE}/validate`, () => json(invalid(2, "x")));
  await show();
  await addTransform();
  expect(await screen.findByRole("button", { name: "Problems · 1" }, { timeout: 3000 })).toBeTruthy();
  expect(steps().dataset.problems).toBe("1");
});

it("calls an answer for an older revision stale, and never paints it on the steps", async () => {
  answers.set(`POST ${BASE}/validate`, () => json(invalid(1, "x"))); // even after the save made revision 2
  await show();
  await screen.findByRole("button", { name: "Problems · 1" }); // revision 1, on the screen: current
  expect(steps().dataset.problems).toBe("1");
  await addTransform();
  await screen.findByText("Saved · not published", {}, { timeout: 3000 });
  await vi.waitFor(() => expect(checks()).toBe(2));
  expect(screen.getByRole("button", { name: "Problems · 1, before your edits" })).toBeTruthy();
  expect(steps().dataset.problems).toBe("0");
});

it("says when a check failed, and checks again when asked", async () => {
  answers.set(`POST ${BASE}/validate`, () => json({ error: "http_error" }, 500));
  await show();
  await userEvent.click(await screen.findByRole("button", { name: "Check failed" }));
  answers.set(`POST ${BASE}/validate`, () => json(valid(1)));
  const panel = screen.getByRole("complementary", { name: "Problems" });
  await userEvent.click(within(panel).getByRole("button", { name: "Check again" }));
  expect(await screen.findByRole("button", { name: "No problems" })).toBeTruthy();
});

it("offers a viewer no checks", async () => {
  role = "viewer";
  await show();
  expect(screen.queryByRole("button", { name: /Problems|Check|Not checked/ })).toBeNull();
  expect(checks()).toBe(0);
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL: `check.ts` and the panel don't exist; the editor never checks.

- [ ] **Step 3: Implement the check's state**

`frontend/src/routes/editor/check.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// What the editor may say of its problems (4b ruling 24). A check is of one saved revision, and is current only while
// that revision is the saved one and nothing was edited since. Before the first answer it says nothing reassuring; a
// failed check says so; edits since a check make it stale. Steps carry badges only while it's current.
import type { SyncState } from "../../lib/draftSync";
import type { Validation } from "../../lib/workflows";

export type Check =
  | { status: "unchecked" }
  | { status: "checking"; last: Validation | null }
  | { status: "failed"; last: Validation | null }
  | { status: "done"; last: Validation };

export type CheckState = "unchecked" | "checking" | "failed" | "stale" | "current";

export function checkState(check: Check, sync: Pick<SyncState, "revision" | "generation" | "savedGeneration">): CheckState {
  if (check.status !== "done") return check.status;
  const onScreen = sync.generation === sync.savedGeneration && check.last.draft_revision === sync.revision;
  return onScreen ? "current" : "stale";
}

/** The newest answer, whatever its state. */
export const lastOf = (check: Check): Validation | null => (check.status === "unchecked" ? null : check.last);

/** The toolbar's words for a check, with the problems it found. */
export function checkLabel(state: CheckState, count: number): string {
  if (state === "unchecked") return "Not checked";
  if (state === "checking") return "Checking…";
  if (state === "failed") return "Check failed";
  if (state === "stale") return count ? `Problems · ${count}, before your edits` : "Not checked since your edits";
  return count ? `Problems · ${count}` : "No problems";
}
```

- [ ] **Step 4: Implement the panel**

`frontend/src/routes/editor/ProblemsPanel.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The draft's problems (outline §2's validate and publish; engine-core §5.10). The server's messages and fixes, as
// it wrote them: there's no catalogue in the client. A step's problem goes to the step (4b ruling 16). What the check
// says is dated (ruling 24): "none found" only for a current check. What only publish checks shows apart, marked, and
// dated against the edits since (ruling 17).
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import type { Diagnostic, Validation } from "../../lib/workflows";
import type { CheckState } from "./check";

/** What only publish found, with the snapshot it was found in: the saved revision, and the editor's generation. */
export type PublishProblems = { revision: number; generation: number; diagnostics: Diagnostic[] };

function Problem({ d, keyOf, onJump }: { d: Diagnostic; keyOf: (id: string) => string; onJump: (id: string) => void }) {
  return (
    <li className="flex flex-col gap-0.5 border-t border-line py-2.5 text-small first:border-t-0">
      <span className={d.severity === "error" ? "text-danger" : "text-warn-ink"}>
        {d.severity === "error" ? "Error" : "Warning"}: {d.message}
      </span>
      {d.fix && <span className="text-muted">{d.fix}</span>}
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-meta text-muted">{d.code}{d.field ? ` · ${d.field}` : ""}</span>
        {d.node && (
          <Button size="sm" onClick={() => onJump(d.node!)}>
            Go to {keyOf(d.node)}
          </Button>
        )}
      </span>
    </li>
  );
}

const ordered = (ds: Diagnostic[]) => [...ds.filter((d) => d.severity === "error"), ...ds.filter((d) => d.severity !== "error")];

const NOTES: Record<Exclude<CheckState, "current">, string> = {
  unchecked: "Not checked yet.",
  checking: "Checking the saved draft…",
  failed: "The check failed, so what's below may be out of date.",
  stale: "From a check made before your latest edits: they may have changed this.",
};

export function ProblemsPanel({
  state, validation, publishProblems, publishCurrent, keyOf, onJump, onCheck, onClose,
}: {
  state: CheckState; validation: Validation | null; publishProblems: PublishProblems | null; publishCurrent: boolean;
  keyOf: (id: string) => string; onJump: (nodeId: string) => void; onCheck: () => void; onClose: () => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const separate = validation?.expressions.filter((x) => x.mode === "activity") ?? [];
  const inline = (validation?.expressions.length ?? 0) - separate.length;
  return (
    <aside
      aria-labelledby="problems-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="flex w-full max-w-[440px] shrink-0 flex-col gap-5 overflow-y-auto border-l border-line bg-surface p-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="problems-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Problems</h2>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {state !== "current" && (
        <p className="flex flex-wrap items-center gap-2 text-small text-muted">
          {NOTES[state]}
          {state === "failed" && <Button size="sm" onClick={onCheck}>Check again</Button>}
        </p>
      )}
      {validation && validation.diagnostics.length > 0 && (
        <ul>{ordered(validation.diagnostics).map((d, i) => <Problem key={`${d.code}:${d.node}:${d.field}:${i}`} d={d} keyOf={keyOf} onJump={onJump} />)}</ul>
      )}
      {state === "current" && validation?.diagnostics.length === 0 && (
        <p className="text-small text-muted">None found in the saved draft. Publishing checks a few more things.</p>
      )}
      {publishProblems && (
        <section aria-labelledby="publish-problems" className="flex flex-col gap-1">
          <h3 id="publish-problems" className="text-small font-semibold">Found at publish</h3>
          <p className="text-small text-muted">
            {publishCurrent
              ? "Publishing checks connections, sub-flows and lifecycles too."
              : "From the last publish attempt, before your latest edits."}
          </p>
          <ul>{ordered(publishProblems.diagnostics).map((d, i) => <Problem key={`p:${d.code}:${d.node}:${i}`} d={d} keyOf={keyOf} onJump={onJump} />)}</ul>
        </section>
      )}
      {validation && validation.expressions.length > 0 && (
        <section aria-labelledby="expressions-title" className="flex flex-col gap-1.5">
          <h3 id="expressions-title" className="text-small font-semibold">How expressions run</h3>
          <ul className="flex flex-col gap-1.5 text-small">
            {separate.map((x) => (
              <li key={`${x.node}:${x.field}`}>
                <span className="font-mono text-meta">{x.node ? keyOf(x.node) : "outputs"} · {x.field}</span>{" "}
                Runs as a separate step: {x.reason ?? "no reason given"}
              </li>
            ))}
          </ul>
          {inline > 0 && <p className="text-small text-muted">{inline === 1 ? "1 expression runs inline." : `${inline} expressions run inline.`}</p>}
        </section>
      )}
    </aside>
  );
}
```

`role="region"` comes from a `section` with an accessible name; the test's `getByRole("region", { name: "Found at
publish" })` relies on that.

- [ ] **Step 5: Check on opening and after each save, and show what's current**

In `frontend/src/routes/editor/Editor.tsx`, the right column holds one panel at a time. Above `Editor`:

```tsx
/** The editor's right column: a step's panel, the problems, or the versions (Task 15). */
type Side = { kind: "step"; node: string } | { kind: "problems" } | { kind: "versions" } | null;
const NO_DIAGNOSTICS: Diagnostic[] = []; // one empty list, so a memo over it holds
```

and it replaces Task 12's `panel` state: `setPanel(id)` becomes `setSide({ kind: "step", node: id })`, `setPanel(null)`
becomes `setSide(null)`, and `panel === x` becomes `side?.kind === "step" && side.node === x` (in `confirmDelete`,
the canvas's `current`, and the step panel's rendering and `onClose`). In `Editor` (imports: `type Check`,
`checkLabel`, `checkState`, `lastOf`, `ProblemsPanel`, `type PublishProblems`, `type Problems`, `type Validation`,
`type Diagnostic`):

```tsx
  const [check, setCheck] = useState<Check>({ status: "unchecked" });
  const [publishProblems, setPublishProblems] = useState<PublishProblems | null>(null);
  const [side, setSide] = useState<Side>(null);
  const asked = useRef(0); // the newest check asked for: an older one's answer or failure says nothing

  /** Check the saved draft (validate needs workflow.edit). Its answer names the revision it checked. */
  const validate = useRef(async () => {});
  validate.current = async () => {
    if (!canEdit(role)) return;
    const n = ++asked.current;
    setCheck((c) => ({ status: "checking", last: lastOf(c) }));
    try {
      const answer = await ok(
        client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/validate", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id } },
        }),
      );
      if (n === asked.current) setCheck({ status: "done", last: answer });
    } catch {
      if (n === asked.current) setCheck((c) => ({ status: "failed", last: lastOf(c) }));
    }
  };
  useEffect(() => void validate.current(), []);
```

The saver's options (Task 13's effect) gain `onSettled: () => void validate.current()`. From the check:

```tsx
  const checked = checkState(check, sync);
  const last = lastOf(check);
  const trusted = checked === "current" ? last : null; // badges and the step panel's problems: current only
  // What only publish found is current only for the snapshot it was found in: the same saved revision, and no edit
  // since (a pending edit leaves the revision as it was, never the generation).
  const publishCurrent =
    publishProblems !== null && publishProblems.revision === sync.revision &&
    publishProblems.generation === sync.generation && sync.generation === sync.savedGeneration;  // prettier-ignore
  const published = publishCurrent && publishProblems ? publishProblems.diagnostics : NO_DIAGNOSTICS;
  const problems = useMemo(() => {
    const counts = new Map<string, Problems>();
    for (const d of [...(trusted?.diagnostics ?? []), ...published]) {
      if (!d.node) continue;
      const c = counts.get(d.node) ?? { errors: 0, warnings: 0 };
      counts.set(d.node, d.severity === "error" ? { ...c, errors: c.errors + 1 } : { ...c, warnings: c.warnings + 1 });
    }
    return counts;
  }, [trusted, published]);
  const separate = useMemo(() => {
    const counts = new Map<string, number>();
    for (const x of trusted?.expressions ?? []) if (x.node && x.mode === "activity") counts.set(x.node, (counts.get(x.node) ?? 0) + 1);
    return counts;
  }, [trusted]);
  const count = (last?.diagnostics.length ?? 0) + published.length; // a stale publish finding never counts
```

The canvas takes `problems={problems}`, `separate={separate}` and `current={side?.kind === "step" ? side.node :
null}`; `onItem`'s `open` becomes `setSide({ kind: "step", node: action.node })`; the step panel's `problems` are
`trusted ? [...trusted.diagnostics, ...published].filter((d) => d.node === side.node) : null`
and its `expressions` `trusted?.expressions.filter((x) => x.node === side.node) ?? []`. The toolbar gains, after the
save state, for an editor only:

```tsx
        {canEdit(role) && (
          <Button
            size="md"
            aria-expanded={side?.kind === "problems"}
            onClick={() => setSide(side?.kind === "problems" ? null : { kind: "problems" })}
          >
            {checkLabel(checked, count)}
          </Button>
        )}
```

and the right column shows, for `side?.kind === "problems"`:

```tsx
          <ProblemsPanel
            state={checked}
            validation={last}
            publishProblems={publishProblems}
            publishCurrent={publishCurrent}
            keyOf={keyOf}
            onJump={(nodeId) => focus(item.node(nodeId))}
            onCheck={() => void validate.current()}
            onClose={() => setSide(null)}
          />
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(web): problems of the saved revision, said to be current only while it's on the screen (4b)"
```

### Task 15: Publishing bound to the version it names; versions viewed and made active; outcomes said truthfully; export

**Files:**
- Modify: `frontend/src/components/ConfirmDialog.tsx`, `frontend/src/components/ConfirmDialog.test.tsx` (`tone`)
- Modify: `frontend/src/lib/draftSync.ts`, `frontend/src/lib/draftSync.test.ts` (`published()`, `activated()`,
  `compared()`, `lostTrack()`)
- Create: `frontend/src/routes/editor/VersionsPanel.tsx`, `frontend/src/routes/editor/VersionsPanel.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `POST …/publish` (`If-Match`, body `{expected_latest_version}`) → `PublishedOut` (`number`), `422 invalid`
  (diagnostics, publish-only codes included), `409 draft_conflict`, `409 version_changed` (`latest_version`: Task 4);
  `versionsQuery`; `GET …/versions/{version_id}` → `VersionDetailOut`; `POST …/activate` (`{version_id}`) →
  `ActivatedOut`, `422 not_activatable`; `GET …/{workflow_id}` (`draft_revision`, `unpublished_changes`,
  `active_version_id`, `active_version_number`); `VersionOut.graph_hash`; `GET …/export` and its `422 not_portable`;
  `notPortable(problems, keyOf)` (Task 7); `flush()`, `ConflictError`, `SyncState.savedHash` (Task 13).
- Produces: `ConfirmDialog`'s `tone?: "danger" | "primary"` (default `"danger"`); `DraftSync.published(revision,
  number)`, `activated(number)`, `compared(summary)`, `lostTrack()`; `<VersionsPanel versions publisher onView
  onActivate onClose />`; `uncertain(e)` in `Editor.tsx`.

What this task guards (the owner's review of 325fc14, corrections 3 and 4; 4b rulings 17 and 25):
- **The number named is the number published.** The confirmation names `latest + 1` from the versions list, and
  publish sends `expected_latest_version: latest`, which the API checks under the lock that numbers the version.
  While the list is loading, refreshing or unreadable, Publish is off and names no number. A `version_changed`
  refreshes the list and asks again with the new number; it is never a draft conflict.
- **Nothing changes under a publication or an activation.** Editing (and undo) is off while either runs.
- **Success is snapshot-aware.** Publish marks the draft published only if the revision it published is still the
  saved one (`published(revision, number)`); activation's comparison comes from the server, taken only for the
  revision it read, and is "not known" (`null`) until then. The active version's label and the comparison always come
  from the same answer (a save's, a publish's, or a read).
- **An outcome is said only when known.** A request that got no answer from the API (the network, or a gateway's or
  a server error's 5xx) is uncertain: the editor reads what happened and says that, or says it isn't known; it never
  says "failed" without an answer saying so, nor "published" without evidence (the owner's review of revision 2,
  correction 1). The evidence is the version's own record: version N holds this draft only if its `graph_hash` is
  the hash the server gave for the revision submitted (`savedHash`, from the save or the load that produced it). A
  version N with another hash is someone else's publication, and this one was refused; no version N leaves it
  open, said as such; no read leaves it unknown. The active version and the draft's comparison come from the read
  itself (`compared`), never from the version number the editor hoped for. A made-active version stays made active
  when the follow-up read fails.
- **Views arrive in order.** Only the newest "View version" answer is shown; "Back to the draft" drops any still on
  its way.
- **Export never hides a failed save.** When the latest edits aren't saved, export stops and says so, and offers the
  last saved draft by name; a draft that can't be made portable offers this draft as it is, labelled not portable.
- **A version's canvas carries no draft diagnostics.** Viewing a version hides the draft's badges and Problems.

- [ ] **Step 1: Write the failing tests**

In `frontend/src/components/ConfirmDialog.test.tsx`:

```tsx
it("confirms a constructive action in the primary colour", () => {
  render(
    <ConfirmDialog open tone="primary" title="Publish version 3" confirmLabel="Publish" onConfirm={vi.fn()} onCancel={vi.fn()}>
      Version 3 becomes active.
    </ConfirmDialog>,
  );
  expect(screen.getByRole("button", { name: "Publish" }).className).toMatch(/\bbg-accent\b/);
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" })); // the safe choice first still
});

it("asks afresh when its question changes while open: focus goes back to Cancel", () => {
  const ask = (title: string) => (
    <ConfirmDialog open tone="primary" title={title} confirmLabel="Publish" onConfirm={vi.fn()} onCancel={vi.fn()}>
      It becomes active.
    </ConfirmDialog>
  );
  const { rerender } = render(ask("Publish version 1"));
  screen.getByRole("button", { name: "Publish" }).focus();
  rerender(ask("Publish version 2"));
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel" }));
});
```

In `frontend/src/lib/draftSync.test.ts`:

```ts
it("takes publish's word only for the revision it published", async () => {
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000); // revision 2
  sync.published(1, 4); // not the revision saved now: version 4 is active, the comparison isn't known
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([4, null]);
  sync.published(2, 5);
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([5, false]);
});

it("takes a read's active version, and its comparison only for the revision it read", () => {
  const sync = make();
  sync.compared({ draft_revision: 1, unpublished_changes: false, active_version_number: 2 });
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([2, false]);
  sync.compared({ draft_revision: 9, unpublished_changes: false, active_version_number: 3 }); // another revision's
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([3, null]);
});

it("says what it doesn't know after an activation or a lost answer", () => {
  const sync = make();
  sync.activated(2);
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual([2, null]);
  sync.lostTrack();
  expect([sync.current.activeNumber, sync.current.unpublished]).toEqual(["unknown", null]);
});
```

`frontend/src/routes/editor/VersionsPanel.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { VersionsPanel } from "./VersionsPanel";

const v = (number: number, active: boolean, blocked: string[] = []) => ({
  id: `v${number}`, number, published_at: "2026-10-06T10:00:00Z", published_by: null, graph_hash: "h", version_hash: "h",
  cel_profile: "p", engine_abi: 6, node_refs: [], active, executable: blocked.length === 0, blocked_by: blocked,
});  // prettier-ignore

it("lists each version, the active one marked, what blocks one, and offers View and Make active", async () => {
  const onView = vi.fn();
  const onActivate = vi.fn();
  render(<VersionsPanel versions={[v(2, true), v(1, false, ["node:testkit.echo@1"])]} publisher onView={onView} onActivate={onActivate} onClose={vi.fn()} />);
  const items = screen.getAllByRole("listitem");
  expect(items[0]!.textContent).toContain("Version 2");
  expect(items[0]!.textContent).toContain("Active");
  expect(within(items[0]!).queryByRole("button", { name: "Make version 2 active" })).toBeNull();
  expect(items[1]!.textContent).toContain("Can't run: node:testkit.echo@1");
  await userEvent.click(within(items[1]!).getByRole("button", { name: "View version 1" }));
  expect(onView).toHaveBeenCalledWith(expect.objectContaining({ number: 1 }));
  await userEvent.click(within(items[1]!).getByRole("button", { name: "Make version 1 active" }));
  expect(onActivate).toHaveBeenCalledWith(expect.objectContaining({ number: 1 }));
});

it("offers a non-publisher only View", () => {
  render(<VersionsPanel versions={[v(2, true), v(1, false)]} publisher={false} onView={vi.fn()} onActivate={vi.fn()} onClose={vi.fn()} />);
  expect(screen.queryByRole("button", { name: /Make version/ })).toBeNull();
});
```

In `frontend/src/routes/editor/Editor.test.tsx`, `beforeEach` gains:

```tsx
  answers.set(`GET ${BASE}/versions`, () => json([]));
  answers.set(`POST ${BASE}/publish`, () => json({ version_id: "v1", number: 1, warnings: [] }, 201));
  downloads = [];
  Object.assign(URL, { createObjectURL: vi.fn(() => "blob:test"), revokeObjectURL: vi.fn() });
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    downloads.push(this.download);
  });
```

with, at the top level, `let downloads: string[];` and these helpers and tests:

```tsx
/** A version as the list answers it; `hash` is its graph's, which says which draft it holds. */
const version = (number: number, active: boolean, hash = "h") => ({
  id: `v${number}`, number, published_at: "2026-10-06T10:00:00Z", published_by: null, graph_hash: hash, version_hash: "h",
  cel_profile: "p", engine_abi: 6, node_refs: [], active, executable: true, blocked_by: [],
});  // prettier-ignore
const detail = (number: number, key: string) => ({ ...version(number, false), graph: draftWith(key), expressions: [] });
const publishes = () => sent.filter((r) => r.path.endsWith("/publish"));

async function confirmPublish(number: number) {
  await userEvent.click(await screen.findByRole("button", { name: `Publish v${number}` }));
  const ask = screen.getByRole("dialog", { name: `Publish version ${number}` });
  await userEvent.click(within(ask).getByRole("button", { name: "Publish" }));
  return ask;
}

it("publishes after saving, naming the version it confirms", async () => {
  await show();
  await addTransform();
  await confirmPublish(1);
  await screen.findByText("Saved · published as v1", {}, { timeout: 3000 });
  const put = sent.findIndex((r) => r.method === "PUT");
  const publish = sent.findIndex((r) => r.path.endsWith("/publish"));
  expect(put).toBeGreaterThanOrEqual(0);
  expect(publish).toBeGreaterThan(put); // flushed first
  expect(sent[publish]!.headers.get("If-Match")).toBe("2");
  expect(sent[publish]!.body).toEqual({ expected_latest_version: 0 });
});

it("names no number until the versions are read, and says when they can't be", async () => {
  let list: ((r: Response) => void) | undefined;
  answers.set(`GET ${BASE}/versions`, () => new Promise<Response>((r) => (list = r)));
  await show();
  expect(screen.getByRole("button", { name: "Publish" }).hasAttribute("disabled")).toBe(true);
  await vi.waitFor(() => expect(list).toBeDefined());
  list!(json({ error: "http_error" }, 500));
  expect(await screen.findByText("The versions couldn't be read, so publishing waits.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Publish" }).hasAttribute("disabled")).toBe(true);
  answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
  await userEvent.click(screen.getByRole("button", { name: "Read them again" }));
  expect(await screen.findByRole("button", { name: "Publish v2" })).toBeTruthy();
});

it("asks again, with the new number, when another version was published meanwhile", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
    answers.set(`POST ${BASE}/publish`, () => json({ version_id: "v2", number: 2, warnings: [] }, 201));
    return json({ error: "version_changed", latest_version: 1 }, 409);
  });
  await show();
  await confirmPublish(1);
  const again = await screen.findByRole("dialog", { name: "Publish version 2" });
  expect(again.textContent).toContain("Version 1 was published since you opened this");
  await vi.waitFor(() => expect(document.activeElement).toBe(within(again).getByRole("button", { name: "Cancel" })));
  expect(screen.queryByText(/changed elsewhere/)).toBeNull(); // never a draft conflict
  await userEvent.click(within(again).getByRole("button", { name: "Publish" }));
  await vi.waitFor(() => expect(publishes()).toHaveLength(2));
  expect(publishes()[1]!.body).toEqual({ expected_latest_version: 1 });
});

it("keeps the draft still while it's being published", async () => {
  let done: ((r: Response) => void) | undefined;
  answers.set(`POST ${BASE}/publish`, () => new Promise<Response>((r) => (done = r)));
  await show();
  await confirmPublish(1);
  await vi.waitFor(() => expect(done).toBeDefined());
  expect(steps().dataset.editable).toBe("false");
  done!(json({ version_id: "v1", number: 1, warnings: [] }, 201));
  await vi.waitFor(() => expect(steps().dataset.editable).toBe("true"));
});

it("reads what happened when a publish's answer is lost, and says it was published when the version holds this draft", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(1, true, "h1")])); // "h1": the draft as loaded
    answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, active_version_id: "v1", active_version_number: 1, unpublished_changes: false }));
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  await show();
  await confirmPublish(1);
  expect((await screen.findByRole("status", { name: "Notice" })).textContent).toContain("Version 1 was published from your draft");
  expect(screen.getByText("Saved · published as v1")).toBeTruthy();
  expect(screen.queryByText(/wasn't published|Not published/)).toBeNull();
});

it("never takes another's publication for this draft's when an answer is lost", async () => {
  // Someone published version 1 from an earlier draft; this editor saved revision 2 ("h2"); its publish was refused,
  // and the refusal lost. Version 1 exists and the draft is still at revision 2: neither says this draft is in it.
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(1, true, "h-theirs")]));
    answers.set(`GET ${BASE}`, () =>
      json({ ...WORKFLOW, draft_revision: 2, active_version_id: "v1", active_version_number: 1, unpublished_changes: true }));
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  await show();
  await addTransform();
  await confirmPublish(1);
  expect((await screen.findByRole("alert")).textContent).toContain("Version 1 holds another draft: yours wasn't published");
  expect(screen.getByText("Saved · unpublished changes since v1")).toBeTruthy();
  expect(screen.queryByText(/published as v1|was published from your draft/)).toBeNull();
});

it("takes the active version from the read, never from the number it hoped for", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json([version(2, true, "h-later"), version(1, false, "h1")]));
    answers.set(`GET ${BASE}`, () =>
      json({ ...WORKFLOW, active_version_id: "v2", active_version_number: 2, unpublished_changes: true }));
    return Promise.reject(new TypeError("Failed to fetch"));
  });
  await show();
  await confirmPublish(1);
  expect((await screen.findByRole("status", { name: "Notice" })).textContent).toContain("Version 1 was published from your draft");
  expect(screen.getByText("Saved · unpublished changes since v2")).toBeTruthy(); // version 2 came after, and is active
});

it("never calls a lost publish a failure when what happened can't be read", async () => {
  answers.set(`POST ${BASE}/publish`, () => {
    answers.set(`GET ${BASE}/versions`, () => json({ error: "http_error" }, 502));
    return json({ error: "http_error" }, 504);
  });
  await show();
  await confirmPublish(1);
  expect((await screen.findByRole("alert")).textContent).toContain("It isn't known whether version 1 was published");
  expect(screen.getByText("Saved · the active version isn't known")).toBeTruthy();
});

it("keeps an activation made when the read after it fails", async () => {
  answers.set(`GET ${BASE}/versions`, () => json([version(2, true), version(1, false)]));
  answers.set(`POST ${BASE}/activate`, () => {
    answers.set(`GET ${BASE}`, () => json({ error: "http_error" }, 500));
    return json({ active_version_id: "v1", number: 1, warnings: [] });
  });
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Versions" }));
  await userEvent.click(await screen.findByRole("button", { name: "Make version 1 active" }));
  await userEvent.click(within(screen.getByRole("dialog", { name: "Make version 1 active" })).getByRole("button", { name: "Make active" }));
  expect((await screen.findByRole("status", { name: "Notice" })).textContent).toContain("Version 1 is active.");
  expect(screen.getByText("Saved · v1 is active")).toBeTruthy(); // the comparison isn't known: nothing claimed
  expect(screen.queryByText(/wasn't made active/)).toBeNull();
});

it("shows the newest version asked for, whatever order the answers come in", async () => {
  let first: ((r: Response) => void) | undefined;
  answers.set(`GET ${BASE}/versions`, () => json([version(2, true), version(1, false)]));
  answers.set(`GET ${BASE}/versions/v1`, () => new Promise<Response>((r) => (first = r)));
  answers.set(`GET ${BASE}/versions/v2`, () => json(detail(2, "two")));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Versions" }));
  await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
  await userEvent.click(screen.getByRole("button", { name: "View version 2" }));
  expect(await screen.findByRole("button", { name: "two" })).toBeTruthy();
  first!(json(detail(1, "one")));
  await new Promise((r) => setTimeout(r, 20)); // the late answer has landed
  expect(screen.queryByRole("button", { name: "one" })).toBeNull();
  expect(screen.getByText("Viewing version 2, read only. The draft is unchanged.")).toBeTruthy();
});

it("carries no draft diagnostics onto a version's canvas", async () => {
  answers.set(`POST ${BASE}/validate`, () => json(invalid(1, "x")));
  answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
  answers.set(`GET ${BASE}/versions/v1`, () => json(detail(1, "one")));
  await show();
  await screen.findByRole("button", { name: "Problems · 1" });
  await userEvent.click(screen.getByRole("button", { name: "Versions" }));
  await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
  await screen.findByRole("button", { name: "one" });
  expect(steps().dataset.problems).toBe("0");
  expect(screen.queryByRole("button", { name: /Problems/ })).toBeNull();
});

it("shows a version's own step in the step panel, never the draft's", async () => {
  const theirs = draftWith("one");
  theirs.nodes![0]!.options = { timeout_s: 30 }; // the draft's "one" keeps the type's 60 s
  const expressions = [{ node: "id-one", field: "/fields/a", mode: "activity", reason: "builds a message" }];
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("one") }));
  answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
  answers.set(`GET ${BASE}/versions/v1`, () => json({ ...version(1, true), graph: theirs, expressions }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Versions" }));
  await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
  await screen.findByText("Viewing version 1, read only. The draft is unchanged.");
  await userEvent.click(screen.getByRole("button", { name: "one" }));
  const panel = screen.getByRole("complementary", { name: "one" });
  expect(panel.textContent).toContain("30 s");
  expect(panel.textContent).toContain("Runs as a separate step: builds a message");
  expect(panel.textContent).toContain("Not checked for what's on the screen.");
});

it("stops an export when the latest edits aren't saved, and offers the saved draft by name", async () => {
  answers.set(`PUT ${BASE}/draft`, () => json({ error: "http_error" }, 500));
  answers.set(`GET ${BASE}/export`, () => json({ format: "dewpoint.workflow", format_version: 1, name: "Nightly", graph: {}, bindings: [] }));
  await show();
  await addTransform();
  await userEvent.click(screen.getByRole("button", { name: "Export" }));
  const stop = await screen.findByRole("alert");
  expect(stop.textContent).toContain("Not exported: your latest edits aren't saved");
  expect(sent.some((r) => r.path.endsWith("/export"))).toBe(false);
  await userEvent.click(within(stop).getByRole("button", { name: "Export the last saved draft" }));
  await vi.waitFor(() => expect(downloads).toEqual(["nightly.dewpoint.json"]));
});

it("offers a draft that can't be made portable as it is, labelled", async () => {
  answers.set(`GET ${BASE}/export`, () =>
    json({ error: "not_portable", problems: [{ reason: "unknown_type", binding: null, node: "id-odd", field: null }] }, 422));
  answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: draftWith("odd") }));
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Export" }));
  const stop = await screen.findByRole("alert");
  expect(stop.textContent).toContain("can't be exported as a portable file");
  expect(stop.textContent).toContain("odd");
  await userEvent.click(within(stop).getByRole("button", { name: "Download this draft as it is (not portable)" }));
  expect(downloads).toEqual(["nightly.draft.json"]);
});

it("shows what only publish checks, in the problems panel, marked", async () => {
  answers.set(`POST ${BASE}/publish`, () =>
    json({ error: "invalid", diagnostics: [{ code: "connection.unknown", message: "That connection doesn't exist.", node: null, field: null, fix: null, severity: "error" }] }, 422));
  await show();
  await confirmPublish(1);
  const panel = await screen.findByRole("complementary", { name: "Problems" });
  expect(within(panel).getByRole("region", { name: "Found at publish" }).textContent).toContain("That connection doesn't exist.");
});

it("keeps an older draft's publish findings out of the current problems", async () => {
  // The owner's case: a clean check of revision 2 must not show revision 1's publish errors as current.
  answers.set(`POST ${BASE}/publish`, () =>
    json({ error: "invalid", diagnostics: [{ code: "connection.unknown", message: "That connection doesn't exist.", node: "x", field: null, fix: null, severity: "error" }] }, 422));
  await show();
  await confirmPublish(1);
  expect(await screen.findByRole("button", { name: "Problems · 1" })).toBeTruthy(); // current: revision 1, no edits
  expect(steps().dataset.problems).toBe("1");
  answers.set(`POST ${BASE}/validate`, () => json(valid(2)));
  await addTransform();
  expect(screen.getByRole("button", { name: "Not checked since your edits" })).toBeTruthy(); // pending: revision 1 still
  expect(steps().dataset.problems).toBe("0");
  expect(await screen.findByRole("button", { name: "No problems" }, { timeout: 3000 })).toBeTruthy();
  const panel = screen.getByRole("complementary", { name: "Problems" });
  expect(within(panel).getByRole("region", { name: "Found at publish" }).textContent).toContain("before your latest edits");
});

it("offers no Publish to a viewer", async () => {
  role = "viewer";
  await show();
  expect(screen.queryByRole("button", { name: /^Publish/ })).toBeNull();
});

/** a → b, c; b → d, e; c → d, f (the owner's review of revision 2): d is joined from b and from c. */
function joins(): GraphDoc {
  const at = { a: [0, 0], b: [0, 140], c: [300, 140], d: [0, 280], e: [300, 280], f: [600, 280] } as const;
  const keys = Object.keys(at) as (keyof typeof at)[];
  const link = (from: string, to: string) => ({ from: { node: `id-${from}`, port: "out" }, to: { node: `id-${to}` } });
  return {
    graph_format: 1,
    nodes: keys.map((key) => ({ id: `id-${key}`, key, type: "flow.transform@1", position: { x: at[key][0], y: at[key][1] } })),
    edges: [link("a", "b"), link("a", "c"), link("b", "d"), link("b", "e"), link("c", "d"), link("c", "f")],
  };
}

it.each(["a viewer", "an editor after a conflict", "a viewed version"])(
  "keeps to the branch the keys came by at a join, read only for %s",
  async (who) => {
    if (who === "a viewer") role = "viewer";
    if (who === "a viewed version") {
      answers.set(`GET ${BASE}/versions`, () => json([version(1, true)]));
      answers.set(`GET ${BASE}/versions/v1`, () => json({ ...version(1, true), graph: joins(), expressions: [] }));
    } else {
      answers.set(`GET ${BASE}`, () => json({ ...WORKFLOW, draft: joins() }));
    }
    if (who === "an editor after a conflict") answers.set(`PUT ${BASE}/draft`, () => json({ error: "draft_conflict", draft_revision: 5 }, 409));
    await show();
    if (who === "an editor after a conflict") {
      await userEvent.click(screen.getByRole("button", { name: "after f" }));
      await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
      await screen.findByRole("alert", {}, { timeout: 3000 }); // changed elsewhere: read only now
    }
    if (who === "a viewed version") {
      await userEvent.click(screen.getByRole("button", { name: "Versions" }));
      await userEvent.click(await screen.findByRole("button", { name: "View version 1" }));
      await screen.findByRole("button", { name: "c" });
    }
    expect(steps().dataset.editable).toBe("false");
    screen.getByRole("button", { name: "c" }).focus();
    await userEvent.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "d" }));
    await userEvent.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "f" })); // never b's e
    await userEvent.keyboard("{ArrowLeft}{ArrowUp}");
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "c" }));
  },
);
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/components/ConfirmDialog.test.tsx src/lib/draftSync.test.ts src/routes/editor`
Expected: FAIL: no `tone`, no `published()` or `compared()`, no versions panel, no Publish.

- [ ] **Step 3: Implement the dialog's tone and the saver's word on publication**

In `frontend/src/components/ConfirmDialog.tsx`, the props gain `tone = "danger"` (`tone?: "danger" | "primary"`), and
the confirm button becomes `<Button variant={tone} onClick={onConfirm} disabled={busy}>{confirmLabel}</Button>`; a
question that changes while the dialog is open is asked afresh, focus back on Cancel (a re-ask after
`version_changed` must never be confirmed by a key press meant for the old one):

```tsx
  useEffect(() => {
    if (open) cancel.current?.focus();
  }, [open, title]);
```

beside the effect that opens it. The header comment adds: "A constructive action (publish, make active) confirms in
the primary colour; focus still starts on Cancel, and goes back there when the question changes."

In `frontend/src/lib/draftSync.ts`:

```ts
  /** Publish answered: version `number` is active and holds the draft at `revision`. It no longer differs, if that's
   * still the saved revision; otherwise how the newer draft compares isn't known. */
  published(revision: number, number: number): void {
    this.set({ activeNumber: number, unpublished: this.state.revision === revision ? false : null });
  }

  /** A version was made active here; how the draft compares with it isn't known until read. */
  activated(number: number): void {
    this.set({ activeNumber: number, unpublished: null });
  }

  /** What a read of the workflow says: its active version, and the draft's comparison with it, taken only for the
   * revision it read (else not known). */
  compared(summary: { draft_revision: number; unpublished_changes: boolean; active_version_number: number | null }): void {
    this.set({
      activeNumber: summary.active_version_number,
      unpublished: summary.draft_revision === this.state.revision ? summary.unpublished_changes : null,
    });
  }

  /** An answer lost and nothing read back: which version is active isn't known, nor how the draft compares. */
  lostTrack(): void {
    this.set({ activeNumber: "unknown", unpublished: null });
  }
```

- [ ] **Step 4: Implement the versions panel**

`frontend/src/routes/editor/VersionsPanel.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// A workflow's versions (B4a; 4b ruling 17): each viewable read-only, and, for a publisher, made active. The active
// one is marked in words; a version that can't run says what blocks it.
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import { since, type VersionRow } from "../../lib/workflows";

export function VersionsPanel({
  versions, publisher, onView, onActivate, onClose,
}: {
  versions: VersionRow[]; publisher: boolean; onView: (v: VersionRow) => void; onActivate: (v: VersionRow) => void;
  onClose: () => void;
}) {  // prettier-ignore
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => heading.current?.focus(), []);
  return (
    <aside
      aria-labelledby="versions-title"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="flex w-full max-w-[440px] shrink-0 flex-col gap-4 overflow-y-auto border-l border-line bg-surface p-5"
    >
      <div className="flex items-center justify-between gap-3">
        <h2 id="versions-title" ref={heading} tabIndex={-1} className="text-body-lg font-semibold">Versions</h2>
        <Button size="sm" onClick={onClose}>Close</Button>
      </div>
      {versions.length === 0 ? (
        <p className="text-small text-muted">Nothing is published yet.</p>
      ) : (
        <ul className="flex flex-col">
          {versions.map((v) => (
            <li key={v.id} className="flex flex-col gap-1.5 border-t border-line py-3 first:border-t-0">
              <span className="flex flex-wrap items-baseline gap-2">
                <span className="font-semibold">Version {v.number}</span>
                {v.active && <span className="rounded-sm border border-accent px-1.5 text-meta text-accent-ink">Active</span>}
                <span className="text-small text-muted">published {since(v.published_at)}</span>
              </span>
              {!v.executable && <span className="text-small text-danger">Can&apos;t run: {v.blocked_by.join(", ")}</span>}
              <span className="flex flex-wrap gap-2">
                <Button size="sm" aria-label={`View version ${v.number}`} onClick={() => onView(v)}>View</Button>
                {publisher && !v.active && (
                  <Button size="sm" aria-label={`Make version ${v.number} active`} onClick={() => onActivate(v)}>
                    Make active
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
```

- [ ] **Step 5: Publish, view, activate and export from the editor**

In `frontend/src/routes/editor/Editor.tsx` (imports: `useQueryClient`, `versionsQuery`, `canPublish`, `notPortable`,
`type PortableProblem`, `type VersionDetail`, `type VersionRow`, `VersionsPanel`, `type Diagnostic`), above `Editor`:

```tsx
/** Whether a request's outcome is unknown: no answer reached the editor (the network), or a 5xx came in the API's
 * place or after its commit. Such an outcome is read back, never assumed (4b ruling 25). */
const uncertain = (e: unknown) => !(e instanceof ApiError) || e.status >= 500;

type Notice = { tone: "danger" | "info"; text: string; action?: { label: string; run: () => void } };
type Confirm = { kind: "publish"; expected: number; elsewhere?: boolean } | { kind: "activate"; version: VersionRow };
```

In `Editor`:

```tsx
  const qc = useQueryClient();
  const versions = useQuery(versionsQuery(tenantId, workflow.id));
  // The newest version's number: what a publish expects (4b ruling 17). Unknown while the list loads or refreshes.
  const latest = versions.isSuccess && !versions.isFetching ? (versions.data[0]?.number ?? 0) : null; // newest first
  const [viewing, setViewing] = useState<VersionDetail | null>(null);
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [busy, setBusy] = useState<"publishing" | "activating" | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const viewAsked = useRef(0); // the newest version view asked for
  const publisher = canPublish(role) && sync.status !== "conflict";
  // Replaces Task 13's `editable`: nothing changes under a version view, a publication or an activation.
  const editable = canEdit(role) && sync.status !== "conflict" && viewing === null && busy === null;
  useEffect(() => {
    if (!editable) setPlacing(null); // a click on a read-only canvas places nothing, even one placing began on
  }, [editable]);
  const shownDoc = viewing ? asGraph(viewing.graph) : doc;
  const path = { params: { path: { tenant_id: tenantId, workflow_id: workflow.id } } };
  const readWorkflow = () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}", path));
  const readVersions = () => ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions", path));

  /** The lists that show versions: refreshed after a change, their failure changing no outcome. */
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["versions", tenantId, workflow.id] });
    void qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
  };

  function publishedAs(number: number, revision: number) {
    saver.current?.published(revision, number);
    setPublishProblems(null);
    announce(`Published version ${number}`);
    refresh();
  }

  async function publish(expected: number) {
    setBusy("publishing");
    setNotice(null);
    let revision: number;
    let hash: string | null; // the server's hash of the draft submitted: how a version is known to hold it
    let generation: number;
    try {
      revision = await saver.current!.flush();
      ({ savedHash: hash, savedGeneration: generation } = saver.current!.current);
    } catch (e) {
      setBusy(null);
      setConfirm(null);
      if (!(e instanceof ConflictError)) setNotice({ tone: "danger", text: "Not published: your latest edits aren't saved. Retry the save, then publish." });
      return; // a conflict has its own banner
    }
    let next: Confirm | null = null;
    try {
      const done = await ok(
        client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/publish", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id }, header: { "If-Match": String(revision) } },
          body: { expected_latest_version: expected },
        }),
      );
      publishedAs(done.number, revision);
    } catch (e) {
      if (e instanceof ApiError && e.code === "version_changed") {
        // Someone (or an attempt whose answer was lost) published meanwhile: ask again, naming the new number.
        await qc.invalidateQueries({ queryKey: ["versions", tenantId, workflow.id] });
        const latestNow = (e.body as { latest_version: number }).latest_version;
        next = { kind: "publish", expected: latestNow, elsewhere: true };
        announce(`Version ${latestNow} was published meanwhile. Confirm to publish version ${latestNow + 1}`);
      } else if (e instanceof ApiError && e.code === "draft_conflict") {
        saver.current?.conflict();
      } else if (e instanceof ApiError && e.code === "invalid") {
        const diagnostics = (e.body as { diagnostics: Diagnostic[] }).diagnostics;
        setPublishProblems({ revision, generation, diagnostics }); // the snapshot they were found in
        setSide({ kind: "problems" });
        announce(`Not published: ${diagnostics.filter((d) => d.severity === "error").length} problems`);
      } else if (uncertain(e)) {
        await reconcilePublish(expected + 1, hash);
      } else {
        setNotice({ tone: "danger", text: "Not published: the server refused it. Try again." });
      }
    } finally {
      setBusy(null);
      setConfirm(next);
    }
  }

  /** A publish without an answer (4b ruling 25, its proof amended by the owner's review of revision 2). Only a
   * publish expecting the version before could have made version `number`, and a version records its graph's hash:
   * it holds this draft only if that hash is the one the server gave for the draft submitted. The active version and
   * the draft's comparison come from the read, never from the number hoped for. */
  async function reconcilePublish(number: number, hash: string | null) {
    try {
      const [listed, now] = await Promise.all([readVersions(), readWorkflow()]);
      saver.current?.compared(now);
      const made = listed.find((v) => v.number === number);
      if (made && hash !== null && made.graph_hash === hash) {
        setPublishProblems(null);
        announce(`Version ${number} holds your draft`);
        setNotice({ tone: "info", text: `Version ${number} was published from your draft; its answer was lost on the way.` });
      } else if (made) {
        // Someone else's publication made version `number`: this one, expecting the one before, was refused.
        setNotice({ tone: "danger", text: `Version ${number} holds another draft: yours wasn't published. Open Versions before publishing again.` });
      } else {
        setNotice({
          tone: "danger",
          text: `Version ${number} isn't published, as far as the server can tell now. If the first attempt is still finishing it may appear: open Versions before publishing again.`,
        });
      }
    } catch {
      saver.current?.lostTrack();
      setNotice({ tone: "danger", text: `It isn't known whether version ${number} was published: its answer was lost. Open Versions to see before publishing again.` });
    }
    refresh();
  }

  /** Made active: so it stays, whatever a read after it fails to say. The draft's comparison with it is the server's,
   * from `now` when a read already has it, else read here, and not claimed until then. */
  async function activatedAs(version: VersionRow, now?: WorkflowDetail) {
    saver.current?.activated(version.number);
    announce(`Version ${version.number} is active`);
    refresh();
    try {
      saver.current?.compared(now ?? (await readWorkflow()));
    } catch {
      setNotice({ tone: "info", text: `Version ${version.number} is active. Whether your draft differs from it couldn't be checked: reload the page to see.` });
    }
  }

  async function activate(version: VersionRow) {
    setBusy("activating");
    setNotice(null);
    try {
      await ok(client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/activate", { ...path, body: { version_id: version.id } }));
      await activatedAs(version);
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_activatable") {
        const first = (e.body as { diagnostics?: Diagnostic[] }).diagnostics?.[0]?.message;
        setNotice({ tone: "danger", text: `Version ${version.number} can't be made active${first ? `: ${first}` : "."}` });
      } else if (uncertain(e)) {
        await reconcileActivate(version);
      } else {
        setNotice({ tone: "danger", text: `Version ${version.number} wasn't made active: the server refused it.` });
      }
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  }

  async function reconcileActivate(version: VersionRow) {
    try {
      const now = await readWorkflow();
      if (now.active_version_id === version.id) return await activatedAs(version, now);
      saver.current?.compared(now);
      setNotice({ tone: "danger", text: `Version ${version.number} isn't active, as far as the server can tell now. Open Versions before trying again.` });
    } catch {
      saver.current?.lostTrack();
      setNotice({ tone: "danger", text: `It isn't known whether version ${version.number} was made active: its answer was lost. Open Versions to see.` });
    }
    refresh();
  }

  async function view(version: VersionRow) {
    const asked = ++viewAsked.current;
    try {
      const opened = await ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id, version_id: version.id } },
        }),
      );
      if (asked !== viewAsked.current) return; // a newer view, or Back to the draft, came since
      setViewing(opened);
      setSide(null);
      setPlacing(null);
      focus(START);
      announce(`Viewing version ${opened.number}, read only`);
    } catch {
      if (asked === viewAsked.current) setNotice({ tone: "danger", text: `Version ${version.number} couldn't be opened. Try again.` });
    }
  }

  function backToDraft() {
    viewAsked.current++;
    setViewing(null);
    focus(START);
  }

  /** The saved draft as a file (B12; 4b ruling 18). Unsaved edits stop it: the file would miss them. */
  async function exportFile(savedOnly = false) {
    setNotice(null);
    if (!savedOnly) {
      try {
        await saver.current!.flush();
      } catch {
        setNotice({
          tone: "danger",
          text: "Not exported: your latest edits aren't saved, so the file would miss them.",
          action: { label: "Export the last saved draft", run: () => void exportFile(true) },
        });
        return;
      }
    }
    try {
      downloadJson(fileName(workflow.name, ".dewpoint.json"), await ok(client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/export", path)));
    } catch (e) {
      if (e instanceof ApiError && e.code === "not_portable") {
        setNotice({
          tone: "danger",
          text: `Not exported: ${notPortable((e.body as { problems: PortableProblem[] }).problems, keyOf)}, so it can't be exported as a portable file.`,
          action: { label: "Download this draft as it is (not portable)", run: () => downloadJson(fileName(workflow.name, ".draft.json"), doc) },
        });
        return;
      }
      setNotice({ tone: "danger", text: "The workflow couldn't be exported. Try again." });
    }
  }
```

The canvas draws `shownDoc` with `editable={editable}`; while `viewing`, it takes empty `problems` and `separate`
(`viewing ? new Map() : problems`). Task 12's `portMap` and `nav` memos read `shownDoc` in place of `doc`. The step
panel shows the step of what's on the screen, never the draft's while a version is viewed (found by the revision's
review): it renders when `nodesOf(shownDoc)` holds the step, takes its node and type from there and its ports from
`portMap`, and, while viewing, the version's own expressions (`viewing.expressions.filter((x) => x.node ===
side.node)`, B4a's) and `problems={null}`. `SaveState` reads the active version from the saver's state, which every
outcome above updates from its own answer or read; the Problems button shows only when `viewing === null`.
The toolbar's actions, after Problems:

```tsx
        <Button size="md" aria-expanded={side?.kind === "versions"} onClick={() => setSide(side?.kind === "versions" ? null : { kind: "versions" })}>
          Versions
        </Button>
        <Button size="md" onClick={() => void exportFile()}>Export</Button>
        {publisher && viewing === null && (
          <Button
            variant="primary"
            size="md"
            disabled={busy !== null || latest === null}
            onClick={() => latest !== null && setConfirm({ kind: "publish", expected: latest })}
          >
            {latest === null ? "Publish" : `Publish v${latest + 1}`}
          </Button>
        )}
```

Below the toolbar, when viewing a version, when the versions can't be read, and for a notice:

```tsx
      {viewing && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
          <span className="grow">Viewing version {viewing.number}, read only. The draft is unchanged.</span>
          <Button size="sm" onClick={backToDraft}>Back to the draft</Button>
        </div>
      )}
      {publisher && versions.isError && (
        <p className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-5 py-2.5 text-small text-danger">
          The versions couldn&apos;t be read, so publishing waits.
          <Button size="sm" onClick={() => void versions.refetch()}>Read them again</Button>
        </p>
      )}
      {notice && (
        <div
          role={notice.tone === "danger" ? "alert" : "status"}
          aria-label={notice.tone === "danger" ? undefined : "Notice"}
          className={`flex flex-wrap items-center gap-3 border-b border-line bg-surface px-5 py-2.5 text-small ${notice.tone === "danger" ? "text-danger" : "text-ink"}`}
        >
          <span className="grow">{notice.text}</span>
          {notice.action && <Button size="sm" onClick={notice.action.run}>{notice.action.label}</Button>}
        </div>
      )}
```

The right column shows, for `side?.kind === "versions"`:

```tsx
          <VersionsPanel
            versions={versions.data ?? []}
            publisher={publisher && busy === null}
            onView={(v) => void view(v)}
            onActivate={(version) => setConfirm({ kind: "activate", version })}
            onClose={() => setSide(null)}
          />
```

and the confirmation (it stays open, busy, while its action runs; a `version_changed` turns it into the next ask):

```tsx
      <ConfirmDialog
        open={confirm !== null}
        tone="primary"
        busy={busy !== null}
        title={confirm?.kind === "activate" ? `Make version ${confirm.version.number} active` : confirm ? `Publish version ${confirm.expected + 1}` : ""}
        confirmLabel={confirm?.kind === "activate" ? "Make active" : "Publish"}
        onConfirm={() => {
          if (confirm?.kind === "activate") void activate(confirm.version);
          else if (confirm) void publish(confirm.expected);
        }}
        onCancel={() => setConfirm(null)}
      >
        {confirm?.kind === "activate" && `Runs start on version ${confirm.version.number} from now on. The draft doesn't change.`}
        {confirm?.kind === "publish" && (
          <>
            {confirm.elsewhere &&
              `Version ${confirm.expected} was published since you opened this, by someone else or by an attempt whose answer was lost. `}
            {`Your latest edits are saved first. Version ${confirm.expected + 1} of ${workflow.name} becomes the active version${workflow.enabled ? ": its triggers start runs on it" : ""}.`}
          </>
        )}
      </ConfirmDialog>
```

`ConflictError`, `Diagnostic` and `VersionDetail` join the imports.

- [ ] **Step 6: Run the tests to see them pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/components/ConfirmDialog.test.tsx src/lib src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean (Members' removal dialog keeps `tone="danger"` by default).

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(web): publish bound to the version it names; versions viewed and made active; outcomes read back, never assumed (4b)"
```

### Task 16: The slice end to end behind nginx: saved, left, problems, published (and raced), versions, a conflict, a file round trip, reflow; then every check

**Files:**
- Create: `frontend/e2e/fixtures/report.dewpoint.json`
- Modify: `frontend/e2e/workflows.spec.ts`, `frontend/e2e/gate.spec.ts` (the notices list the canvas's packages)
- Modify: `docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md` (this plan's rulings, once the owner approves them,
  as 68 onward; each mid-slice ruling the execution made)

**Interfaces:**
- Consumes: everything above, through the browser; `ADMIN_STATE` (Task 11).
- Produces: the slice's proofs; the ledger's record.

- [ ] **Step 1: Write the fixture and the flows**

`frontend/e2e/fixtures/report.dewpoint.json` (CI's own seed graph, `deploy/compose/ci/seed-workflow.py:26-40`, which
validates and publishes there):

```json
{
  "format": "dewpoint.workflow",
  "format_version": 1,
  "name": "Report",
  "graph": {
    "graph_format": 1,
    "nodes": [
      {
        "id": "5f0c6e2a-2b2b-4e2b-9c2b-2b2b2b2b2b2b",
        "key": "t",
        "type": "flow.transform@1",
        "config": { "fields": { "answer": { "$value": { "kind": "cel", "expr": "1 + 1" } } } },
        "options": { "on_error": "fail" },
        "position": { "x": 0, "y": 140 }
      }
    ],
    "edges": [],
    "settings": {
      "input_schema": { "type": "object" },
      "outputs": { "answer": { "$value": { "kind": "cel", "expr": "steps.t.output.answer" } } }
    }
  },
  "bindings": []
}
```

In `frontend/e2e/workflows.spec.ts`, add:

```ts
const importReport = (page: Page, name: string) => importFile(page, name, "e2e/fixtures/report.dewpoint.json");

test("edits save themselves and survive a reload; a step's problems show on it, and a problem focuses it", async ({ page }) => {
  await newWorkflow(page, "Saved flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  const problems = page.getByRole("button", { name: /^Problems · \d+$/ });
  await expect(problems).toBeVisible({ timeout: 10_000 });
  const step = page.getByRole("button", { name: /^transform, Transform, \d+ problems?/ });
  await expect(step).toBeVisible();
  await page.reload();
  await expect(step).toBeVisible(); // the server kept it
  await problems.click();
  const panel = page.getByRole("complementary", { name: "Problems" });
  await expect(panel.getByRole("heading", { name: "Problems" })).toBeFocused();
  await expectAccessible(page, "editor: problems");
  await panel.getByRole("button", { name: "Go to transform" }).first().click();
  await expect(step).toBeFocused();
});

test("publishing names the version; a version is viewed read only and made active", async ({ page }) => {
  await importReport(page, "Report A");
  await expect(page.getByRole("button", { name: "No problems" })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Publish v1" }).click();
  const ask = page.getByRole("dialog", { name: "Publish version 1" });
  await expect(ask.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expectAccessible(page, "editor: publish");
  await ask.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Saved · published as v1")).toBeVisible({ timeout: 10_000 });
  // A change makes it unpublished; publishing again makes version 2.
  await page.getByRole("button", { name: "Add a step after t" }).click();
  await page.getByRole("option", { name: /flow\.stop@1/ }).click();
  await expect(page.getByText("Saved · unpublished changes since v1")).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: "Publish v2" }).click();
  await page.getByRole("dialog", { name: "Publish version 2" }).getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Saved · published as v2")).toBeVisible({ timeout: 10_000 });
  // Version 1, read only: no stop step, nothing to add; then back, and version 1 made active.
  await page.getByRole("button", { name: "Versions" }).click();
  await expectAccessible(page, "editor: versions");
  await page.getByRole("button", { name: "View version 1" }).click();
  await expect(page.getByText("Viewing version 1, read only. The draft is unchanged.")).toBeVisible();
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Insert a step/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Back to the draft" }).click();
  await expect(page.getByRole("button", { name: /^stop, Stop/ })).toBeVisible();
  await page.getByRole("button", { name: "Versions" }).click();
  await page.getByRole("button", { name: "Make version 1 active" }).click();
  await page.getByRole("dialog", { name: "Make version 1 active" }).getByRole("button", { name: "Make active" }).click();
  await expect(page.getByText("Saved · unpublished changes since v1")).toBeVisible({ timeout: 10_000 });
  // The list agrees.
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  const row = page.getByRole("link", { name: "Report A" }).locator("xpath=ancestor::tr");
  await expect(row).toContainText("v1 · unpublished changes");
  await expect(row.getByRole("switch", { name: "Enable Report A" })).toBeVisible();
});

test("a draft changed elsewhere turns this editor read only, its work downloadable", async ({ page, context }) => {
  await importReport(page, "Report B");
  const other = await context.newPage();
  await other.goto(page.url());
  await expect(other.getByRole("button", { name: /^t, Transform/ })).toBeVisible();
  // This editor saves first: revision 2.
  await page.getByRole("button", { name: "Add a step after t" }).click();
  await page.getByRole("option", { name: /flow\.stop@1/ }).click();
  await expect(page.getByText("Saved · not published")).toBeVisible({ timeout: 10_000 });
  // The other, still at revision 1, is refused, and stops.
  await other.getByRole("button", { name: "Add a step after t" }).click();
  await other.getByRole("option", { name: /flow\.delay@1/ }).click();
  const alert = other.getByRole("alert");
  await expect(alert).toContainText("changed elsewhere", { timeout: 10_000 });
  await expect(other.getByRole("button", { name: /Add step/ })).toHaveCount(0);
  const download = other.waitForEvent("download");
  await alert.getByRole("button", { name: "Download my version" }).click();
  expect((await download).suggestedFilename()).toBe("report-b.draft.json");
  // Its unsaved version is guarded: leaving asks, and Reload asks before discarding it.
  await other.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Workflows" }).click();
  const leave = other.getByRole("dialog", { name: "Your latest changes aren't saved" });
  await expect(leave).toContainText("changed elsewhere");
  await expectAccessible(other, "editor: leaving unsaved work");
  await leave.getByRole("button", { name: "Stay" }).click();
  await alert.getByRole("button", { name: "Reload" }).click();
  await other.getByRole("dialog", { name: "Reload the saved draft" }).getByRole("button", { name: "Discard my version and reload" }).click();
  await expect(other.getByRole("button", { name: /^stop, Stop/ })).toBeVisible();
  await expect(other.getByRole("button", { name: /^delay, Delay/ })).toHaveCount(0);
  await other.close();
});

test("a workflow exports to a file and imports back as a new one", async ({ page }, info) => {
  await importReport(page, "Report C");
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByRole("button", { name: "Actions for Report C" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Export" }).click();
  const file = info.outputPath("report-c.dewpoint.json");
  await (await download).saveAs(file);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill("Report C copy");
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles(file);
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Report C copy" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^t, Transform/ })).toBeVisible();
});

test("leaving through the breadcrumb saves the last edit first", async ({ page }) => {
  await newWorkflow(page, "Leaving flow");
  await page.getByRole("button", { name: "Add the first step" }).click();
  await page.getByRole("option", { name: /flow\.transform@1/ }).click();
  await expect(page.getByText("Unsaved changes")).toBeVisible(); // inside the second before it would save
  await page.getByRole("navigation", { name: "Breadcrumb" }).getByRole("link", { name: "Workflows" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Workflows" })).toBeVisible();
  await page.getByRole("link", { name: "Leaving flow" }).click();
  await expect(page.getByRole("button", { name: /^transform, Transform/ })).toBeVisible(); // the server kept it
});

test("a publish names the version it makes, even when another lands first", async ({ page, context }) => {
  await importReport(page, "Report D");
  const other = await context.newPage();
  await other.goto(page.url());
  const publish = page.getByRole("button", { name: "Publish v1" });
  await expect(publish).toBeEnabled({ timeout: 10_000 });
  await publish.click();
  const ask = page.getByRole("dialog", { name: "Publish version 1" });
  await expect(ask).toBeVisible();
  // Meanwhile, the other editor publishes version 1.
  await other.getByRole("button", { name: "Publish v1" }).click();
  await other.getByRole("dialog", { name: "Publish version 1" }).getByRole("button", { name: "Publish" }).click();
  await expect(other.getByText("Saved · published as v1")).toBeVisible({ timeout: 10_000 });
  await other.close();
  // This one still names version 1: the server refuses it, and the editor asks again with the new number.
  await ask.getByRole("button", { name: "Publish" }).click();
  const again = page.getByRole("dialog", { name: "Publish version 2" });
  await expect(again).toContainText("Version 1 was published since you opened this", { timeout: 10_000 });
  await again.getByRole("button", { name: "Publish" }).click();
  await expect(page.getByText("Saved · published as v2")).toBeVisible({ timeout: 10_000 });
});

test("the list reflows at 320 px and stays AA (WCAG 1.4.10)", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await expect(page.getByRole("link", { name: "Report A" })).toBeVisible();
  await expect(page.getByRole("note", { name: "Deployment" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "the workflows list scrolls sideways at 320 px").toBeLessThanOrEqual(0);
  await expectAccessible(page, "workflows at 320 px");
});
```

In `frontend/e2e/gate.spec.ts`'s notices test, the entries list gains `/^@xyflow\/react \d/m` and `/^@dagrejs\/dagre \d/m`.

- [ ] **Step 2: Run the gate**

Reset the isolated stack (`compose-ui4a/reset.sh`, which now syncs the plugins), then
`E2E_BASE_URL=http://localhost:18080 npx -y pnpm@12.6.0 exec playwright test`.
Expected: `foundations` 8 passed (4a's two flows, the five gate self-tests and the notices check), `workflows` 11
passed (Task 11's one, Task 12's three, and these seven). A failure is a finding: fix
it test-first in the task that owns the code, and record what changed in the ledger.

- [ ] **Step 3: Every check, locally** (the Actions minutes are spent)

```bash
cd frontend && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck \
  && npx -y pnpm@12.6.0 check:api && npx -y pnpm@12.6.0 build \
  && node scripts/licence-check.mjs --self-test && node scripts/third-party-notices.mjs --self-test \
  && npx -y pnpm@12.6.0 licenses list --json --prod | node scripts/licence-check.mjs prod \
  && npx -y pnpm@12.6.0 licenses list --json | node scripts/licence-check.mjs all
cd ../backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run lint-imports \
  && uv run pip-licenses --fail-on="GPL;AGPL;LGPL;SSPL;BUSL" --partial-match \
  && uv run dewpoint api openapi | diff -u ../frontend/src/api/openapi.json - \
  && uv run pytest -q -n 12 -p no:cacheprovider --ignore=tests/apps/cel_evaluator --ignore=tests/engine/cel \
       --ignore=tests/engine/graph/test_validate_cel.py --ignore=tests/apps/worker/test_gate_task_cost.py \
  && uv run python -m tests.engine.replay.gate --event pull_request --ref refs/pull/0/merge --pr-base "$(git merge-base HEAD origin/main)" --before ""
```

Expected: all pass. The build's `third-party-notices.txt` lists `@xyflow/react`, `@xyflow/system`, `@dagrejs/dagre`,
`@dagrejs/graphlib`, `@radix-ui/react-switch` and their shipped dependencies (d3's, zustand, classcat), each with its
licence text; a package without one fails the build (ruling 65): that's a finding for the owner, never an exception
added here. The serial CEL group is untouched by this slice; it runs in `cel-gates`' image only if the owner asks
(ledger ruling 66's procedure, about 2 minutes). Report every number as it came out, failures included.

- [ ] **Step 4: Record the rulings, then commit**

Add a section to the ledger, "4b plan (2026-10-06)": the owner's approval of this plan (quoted as given), its rulings
1–26 as ledger rulings 68–93 (with the statuses and amendments the owner rules), and each mid-slice ruling the
execution made, with its why and its cost if wrong. Then:

```bash
git add frontend/e2e docs/superpowers/plans/2026-10-05-editor-ui-4-ledger.md
git commit -m "test(web): 4b end to end behind nginx: saved, problems, publish, versions, a conflict, a file, reflow [skip ci]"
```

(`[skip ci]` on this commit: it heads the branch when the owner says to push, and the Actions minutes are spent.)

- [ ] **Step 5: The checkpoint**

1. A fresh-context reviewer (a subagent, read-only, deleting only its own files) reviews the whole branch against the
   brief's six hunts: a sensitive value reaching a sample, a preview, the DOM or a log; a live call; a write that skips
   the server's checks; a CSP violation; keyboard traps and WCAG 2.2 AA failures; visible drift from frames 1a, 1b, 1c.
2. Each finding is fixed test-first, or ruled with its why and cost, in the ledger.
3. Screenshots (light, dark, 320 px for the list) of the list, the chooser, the editor with problems, the publish
   confirmation and the versions panel, beside design frames 1a, 1b and 1c, and the one-page summary for the owner,
   with the tests, the rulings and the open questions.
4. Stop. Nothing is pushed and no PR is opened without the owner's OK in chat.

---

## Self-review

Run against the outline's slice 4b, its decisions and its backend items, and against the owner's seven corrections,
with the plan in hand:

1. **Spec coverage.**
   - 1a, its filters and the enable toggle (B3): Tasks 3, 6, 7.
   - 1b, Blank and Import from file (D9, B12): Tasks 5, 8.
   - The canvas: React Flow (Task 11), dagre on demand (Task 10), zoom and minimap (Task 11).
   - Badges on the step cards: problems, when the check is current (Task 14). "Conditional" and "disabled" are ruled
     out of 4b (ruling 3).
   - "+" on edges and ports, and `A` with the type picker (B5): Tasks 1, 11, 12.
   - The keyboard (D16) and single-pointer movement (WCAG 2.5.7): Task 12, in the browser in Tasks 12 and 16.
   - Autosave with `If-Match`, where a 409 never overwrites (D17), leaving that saves first, and a fresh snapshot on
     entry: Task 13.
   - Validate: the panel, per-step badges, focus jumping to the step (the field waits for 4c, ruling 16), CEL classes
     with their reasons, and the check's five states: Task 14.
   - The §5.10 messages: the server's own text, Task 14.
   - Publish, its confirmation naming the version and binding it at the server, and the publish-only checks: Tasks 4
     and 15.
   - B4a: Task 4, used by Task 15.
   - Ruling 47's `Graph` on the draft PUT: Task 2.
   - Workflows in the rail, the landing page and the palette (D10, outline §2): Task 6.
   - New packages, licences and notices (D22, ruling 65): Tasks 6 and 16.
   - The browser gate's CSP, console and axe checks on each new screen (D21, D23): Tasks 11, 12 and 16.
   - No AI tells (§6): stated in each component, and enforced by the guard and the reviewer.
   - The owner's corrections 1–7: "Revision 2" maps each to its tasks and rulings.
2. **Placeholders.** None: every step that changes code shows the code, and every test shows its assertions. Where
   the installed package decides a detail (dagre's export shape, React Flow's class names and pane API, a CHECK on
   `runs`), the step says to read the package first and how to adapt it. That's the owner's standing rule, not a gap.
   Ruling 5's outcome is the owner's at the milestone 1 pause; an index, if ruled, is planned then, with its slot.
3. **Type consistency.**
   - `PortRef`, `ItemAction` and `PickMode` keep one shape across Tasks 9–15.
   - `item.*` ids are built only in `items.ts` and read by `canvasNav.ts` and the components; the canvas and the
     keyboard model both use `drawableEdges` (Task 9).
   - `SyncState` (`status`, `revision`, `unpublished: boolean | null`, `generation`, `savedGeneration`, `savedHash`,
     `activeNumber: number | null | "unknown"`) and `DraftSync`'s `change`, `flush`, `retry`, `conflict`, `dispose`,
     `unsaved` (Task 13), `published(revision, number)`, `activated`, `compared(summary)`, `lostTrack` (Task 15);
     `Saved` matches `DraftSavedOut` (Task 3); `ConflictError` and `SaveError` (Task 13); `<SaveState state />` reads
     the active version from the state.
   - `LeaveGuard`, `guardLeaving`, `unsavedWork`, `mayLeave` (Task 13), used by the editor, `Shell` and
     `RequireActive`.
   - `step`, `pathTo`, `isPath` replace revision 2's `move` (Task 12); the editor keeps `trail` beside `focusId`.
   - `PublishProblems` is `{revision, generation, diagnostics}`; `ProblemsPanel` takes `publishCurrent` (Task 14).
   - `useBindingChoices` and `ImportBindings`' `choices` (Task 8).
   - `Check`, `CheckState`, `checkState`, `lastOf`, `checkLabel` (Task 14), read by Task 15 only through the editor.
   - `StepPanel`'s `problems: Diagnostic[] | null`, `onPlace`, `onNudge` (Task 12), filled by Task 14 and emptied
     while viewing a version (Task 15).
   - `CanvasProps` gains `placing` and `onPlace` in Task 12; Task 11's stand-in canvas gains the matching button there.
   - `Problems` is `{errors, warnings}`, from Tasks 11 and 14. `Side` replaces Task 12's `panel` in Task 14, and Task
     14 says so.
   - `notPortable` and `PortableProblem` (Task 7), used by Task 15; the API's `not_portable` and `bad_document`
     problem shape `{reason, binding, node, field}` (Task 5), read by Tasks 7, 8 and 15.
   - The schema names come from Tasks 1–5: `NodeTypeOut`, `WorkflowOut` (with `last_run`, `last_simulation`,
     `draft_graph_hash`), `WorkflowDetailOut`, `DraftSavedOut` (with `graph_hash`, `active_version_id`,
     `active_version_number`), `ValidationOut`, `DiagnosticOut`, `ExpressionOut`, `VersionOut`,
     `VersionDetailOut`, `PublishIn`, `WorkflowDocument`, `Binding`, `BindingSite`, and `Graph` (refined).
   - The summary module is `dewpoint.apps.workflow_summary` everywhere (Task 3, its tests, its probe).
4. **Review Focus.** Each of its five lines has its tests in the task that owns the code, named in the line.
