# Editor UI 4b: Workflows and Canvas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A tenant member can list workflows with their state at a glance, create one (blank or imported from a file),
build its graph on a canvas with a pointer or the keyboard alone, have every edit saved without ever overwriting
someone else's, see its problems on the steps they concern, and publish it with a confirmation that names the version.

**Architecture:**
- **The API answers what the editor needs (milestone 1).** Node types also report how each step runs: side effect,
  credentials, capabilities, retry and timeout defaults (B5). Every workflow route answers a named model, and the draft
  PUT documents its body as `Graph` (ledger ruling 47). The list and a workflow's summary gain the last run, the runs of
  the last 24 hours, whether the draft differs from the active version, and why it needs attention (B3). A version can
  be read whole, graph included, with its `engine_abi` (B4a). A workflow exports to a JSON document whose connections
  and workflow references are typed placeholders, and imports with each placeholder re-bound (B12). No migration.
- **The list and the chooser (milestone 2).** Workflows joins the rail and becomes a tenant's landing screen. The list
  (1a) filters by state and name, toggles a workflow on or off, and exports it. "New workflow" (1b) starts blank or
  from an imported file, asking for each binding.
- **The canvas (milestone 3).** The draft is a document the editor changes only through pure operations, with local
  undo and redo. React Flow draws it; dagre lays it out on demand. A start card heads the graph; "+" sits on every edge
  and every free port; `A` opens the node-type picker. One roving tab stop covers the canvas: arrows follow the edges,
  and every action a pointer has, the keyboard has (D16).
- **Saving, problems and publishing (milestone 4).** At most one save in flight, edits coalesced, `If-Match` the
  revision the last save returned; a conflict turns the editor read-only (D17). Validation runs on the saved revision
  and drops an answer for an older one. Problems sit in a panel and on the steps; a problem focuses its step. Publish
  flushes the save, confirms with the version number, and shows what only publish checks. A versions panel views any
  version read-only and makes one active.

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

The input classes and conditions most likely to bite a person using this, which the tasks below now pin with a test
(each named where it lives):
- **Two people edit one workflow.** The second save's `If-Match` is stale: the editor must turn read-only and keep the
  local work downloadable, never retry over the other's draft (Task 13: `a 409 stops every save and keeps the
  document`).
- **Edits faster than saves.** Typing or dragging while a save is in flight must never send two saves at once nor
  drop the last edit (Task 13: `edits during a save coalesce into exactly one next save`).
- **A validation answer that arrives after newer edits.** It must never paint problems on the newer draft (Task 14:
  `an answer for an older revision is dropped`).
- **A draft from elsewhere with what the editor can't model** (an unknown node type, a retired one, a port the type
  no longer has, a `settings` block, an imported file): the canvas must draw it, keep every field it doesn't touch
  byte for byte, and say what's unknown (Task 9: `operations keep what they don't touch`; Task 11's e2e of an
  imported graph with a retired type).
- **An import whose bindings point at the wrong thing** (another tenant's connection, a connection of the wrong type,
  a deleted workflow): the API refuses it by name, and nothing is created (Task 5: `a binding of the wrong type is
  refused and nothing is created`).

## Rulings this plan proposes

The outline leaves these open, or the code found differs from it. Each is the safest option; the owner rules on them
with the plan, and they join the ledger as rulings 68 onward when the plan is approved. Format: what - why - cost if
wrong.

1. **Triggers wait for 4c.** Triggers are rows (schedules, webhook bindings, CSV uploads), not graph nodes, and their
   setup is 4c's. So 4b's chooser (1b) asks only how to start (Blank, Import from file); its first step, "What starts
   it?", arrives with 4c's trigger setup. The list (1a) has no Trigger column until then. - Showing a trigger the
   editor can't set up would promise what 4b can't do. - 1b's first step and 1a's column wait one slice.
2. **A start card heads the canvas, and no end marker closes it.** The card is not a graph node: it stands for
   whatever starts a run, and its edges reach every entry step (a step with no incoming edge). Its "+" adds a first
   step. 1c's "End · run succeeds" marker is left out: a run ends when no step remains, and a drawn end would look
   like a step. - The graph has no trigger node to draw. - One cue fewer than 1c.
3. **Step badges are problems and "runs as a separate step".** 1c's "conditional" badge needs the validator's liveness
   per step, which B6 brings in 4c; "disabled" has no meaning in the graph model (`GraphNode` has no such field). -
   Neither can be shown truthfully in 4b. - Two of the outline's three badges wait or drop.
4. **The list's filters and columns.** Name, Version, Last run, Last 24 h, Enabled, and a row menu (Open, Export).
   Filters: All, Published, Unpublished changes, Needs attention, as a segmented control with counts (no pills, §6);
   the text filter matches names (no tags exist). No delete: no route deletes a workflow, and the API's database role
   has no DELETE grant on `workflows`. - What the API supports today. - No delete from the UI.
5. **The last run is read without a workflow index.** `runs` has no index on `workflow_id`; one is a migration, which
   needs a slot from the owner. B3 takes each workflow's last root run in one `DISTINCT ON` scan of the tenant's root
   runs per list request. - No migration without a slot. - A list's cost grows with a tenant's run history until
   2b-4a's retention bounds it, or an index (owner's slot) does.
6. **"Unpublished changes" compares graph hashes.** The draft's `graph_hash` (parsed and hashed on read; drafts are
   format-checked at save, so they parse) against the active version's. Never published counts as unpublished. No
   edit count (outline B3). Positions count: moving a step is an unpublished change, as the hash says. - The hash is
   what publish records. - Parsing and hashing each draft on each list read (bounded by the 1 MiB body cap).
7. **Needs attention** is the last root run failed or exceeded its deadline, or the active version can't run
   (`blocked_by`). Schedules' sync errors join with 4c. **Last 24 h** counts root runs queued in the last 24 hours,
   live and simulated apart; the list shows the live count and "+N simulated". - Live and simulated are never
   blended (D2). - None.
8. **The draft PUT's schema documents `Graph` while the route parses a plain object** (ruling 47). FastAPI ignores
   `WithJsonSchema` on a body and merges `openapi_extra` into the generated object schema (both verified against
   FastAPI 0.141.1), so `openapi.py` refines the one schema both the API and `dewpoint api openapi` emit: the draft
   PUT's body becomes exactly `{"$ref": "#/components/schemas/Graph"}`. The route keeps its own parsing, so its
   `graph.format` diagnostics and admission checks (non-finite numbers, depth, value count) stay as they are. -
   Typing the body as `Graph` would route bad drafts through `{"error":"invalid","fields":[...]}` and skip those
   checks. - The documented body and the parsed one are two declarations, held together by a test.
9. **Answers keep a draft verbatim** (`draft: object` in the schema); the client types it as `Graph` at one boundary
   (`asGraph` in `src/lib/graph.ts`). - A response model typed `Graph` would re-serialize the stored draft with
   defaults the author never wrote. - One cast, at one place.
10. **Inserting on an edge offers only steps that continue the flow:** a type with an `out` port, or `flow.loop`'s
    `done`. "+" after a port offers every type; a type with no ports (`flow.stop`, `flow.fail`) ends its branch. -
    Inserting a branching step mid-edge would have to guess which port carries the rest of the flow. - Inserting an
    `if` mid-flow takes two actions (add after, reconnect).
11. **A new step** gets a random UUID, a key from its type's last segment (`transform`, then `transform_2`), a config
    with its schema's top-level defaults (a connection field gets none), no options (the server's defaults), and a
    place below its source; inserting on an edge moves every step at or below that place down one row. - Keys must be
    unique and match `^[a-z][a-z0-9_]{0,62}$`. - None.
12. **Deleting a step asks first**, and when the step has exactly one incoming and one outgoing edge, its predecessor
    is reconnected to its successor; the dialog says so. References to the step in other steps' values stay, and the
    validator reports them (`ref.unknown_step`). Its `settings.declassify` entries go with it. - Healing a chain is
    what a person deleting a middle step expects; rewriting references isn't. - None.
13. **Moving steps.** A pointer drags; Shift+arrow keys nudge the focused step by 20 px; Auto layout arranges the
    whole graph in one click, the single-pointer alternative WCAG 2.5.7 asks for. Positions are saved in the draft. -
    Free placement by a single pointer would need a move mode nothing in the design shows. - No single-pointer free
    placement.
14. **Connecting existing steps.** A port's "Connect to…" lists the steps that may follow it (not itself, not one that
    would close a cycle, not one already connected from that port); dragging from a handle does the same with a
    pointer. An edge is removed from its "+" item with Delete, after a confirmation. - Every pointer action has a
    keyboard one (2.1.1). - None.
15. **The keyboard model (D16), exactly.** The canvas is one tab stop. Its items are the start card, each step, each
    edge (its "+"), and each free port (its "+"). Down goes to the first item below, Up to the first above, Left and
    Right to the previous or next item sharing the same one above; Home goes to the start card. Enter on a step opens
    its panel (read-only in 4b; 4c's drawer replaces it), on an edge or a free port the picker; `A` opens the picker
    after the focused step's first port; Delete asks; Escape closes the picker or panel and returns focus; Ctrl or
    Cmd+Z undoes, Shift+Ctrl or Cmd+Z redoes. A polite live region announces what changed. React Flow's own
    keyboard handling (arrow keys moving nodes, Delete removing them, Tab through every node) is off. - D16. - None.
16. **A problem focuses its step** on the canvas (brought into view); the field itself waits for 4c's drawer. -
    4b has no field to focus. - None.
17. **Publish needs `workflow.publish`;** an editor without it validates but doesn't see Publish, the enable switch,
    or Make active. The confirmation names the next number ("Publish version 3"), from the versions list, and says it
    becomes the active version that triggers start. A publish refused for a check only publish runs (`connection.*`,
    `subflow.*`, `declassify.forbidden`, `lifecycle.*`, `version.unbounded`) shows those in the problems panel, marked
    "found at publish". - Validate can say valid while publish answers 422: the panel must say which. - None.
18. **Export and import (B12).** Export is the saved draft (never unsaved local edits), as `{"format":
    "dewpoint.workflow", "format_version": 1, "name", "graph", "bindings"}`. `graph` is the draft with every bindable
    value removed: each connection field (a config property marked `x-dewpoint-connection`), each `flow.run_workflow`'s
    `workflow_id`, and `settings.failure_handler`. Each binding has an id, a kind (`connection` or `workflow`), the
    connection type, a label (the connection's or workflow's name), and its sites (node id and pointer). Import names
    the new workflow and binds each id to one of the tenant's connections of that type or one of its workflows, or
    leaves it unbound (its sites stay empty, and validation says so). Schedules, webhook bindings and CSV mappings are
    rows, not graph, and don't travel. - Never carry one tenant's ids into another's. - A file round-trips the graph
    only.
19. **Workflows lands a tenant.** Workflows joins the rail first; choosing a tenant (the switcher, the palette) opens
    its workflows (D10); the palette lists the current tenant's workflows and "New workflow". The editor uses the
    60 px icon rail at every width, and keeps the shell's header (tenant, ⌘K, Security, Sign out); its own toolbar sits
    below it with the breadcrumb, save state and actions. - One header everywhere. - 1c's single header row becomes
    two.
20. **React Flow's attribution link is hidden** (`proOptions.hideAttribution`), which its MIT licence allows; the
    third-party notices carry its licence. Only its structural `base.css` is imported: colours, borders and shadows
    come from our tokens. - An external link in the canvas, and a second visual language. - None.
21. **Undo and redo stay local** (D17): a history of up to 100 documents in memory, cleared when the editor closes.
    Undo after a conflict is off (the editor is read-only). - D17. - None.

## File structure

Backend, modified:
- `backend/src/dewpoint/apps/api/responses.py`: the 4b answers (node types, workflows, drafts, validation, versions,
  export and import).
- `backend/src/dewpoint/apps/api/routes/node_types.py` (B5), `routes/workflows.py` (models, B3, B4a, B12 routes).
- `backend/src/dewpoint/apps/api/openapi.py`: `refine()`, applied to the served and the printed schema.
- `backend/src/dewpoint/apps/api/main.py`: serves the refined schema.
- `backend/src/dewpoint/core/workflows/service.py`: `create_workflow(..., source=...)` for the import's audit entry.

Backend, new:
- `backend/src/dewpoint/core/workflows/summary.py`: run statistics and unpublished changes per workflow (B3).
- `backend/src/dewpoint/core/workflows/portable.py`: export's placeholders and import's bindings (B12).
- Tests: `backend/tests/apps/api/test_node_types.py`, `test_workflow_summary.py`, `test_workflow_versions.py`,
  `test_workflow_portable.py`; `backend/tests/core/workflows/test_portable.py`; additions to `test_openapi.py`.

Frontend, new:
- `src/lib/workflows.ts`: the workflow API's types and queries. `src/lib/graph.ts`: the document and its operations.
  `src/lib/layout.ts`: dagre. `src/lib/canvasNav.ts`: the keyboard model. `src/lib/draftSync.ts`: saving (D17).
  `src/lib/history.ts`: undo and redo. `src/lib/announce.ts`: the live region's store. `src/lib/download.ts`.
- `src/components/Switch.tsx`, `src/components/Announcer.tsx`, `src/components/Segmented.tsx`.
- `src/routes/Workflows.tsx` (1a), `src/routes/NewWorkflow.tsx` (1b), `src/routes/ImportBindings.tsx`.
- `src/routes/editor/`: `Editor.tsx`, `Toolbar.tsx`, `Canvas.tsx`, `StepCard.tsx`, `StartCard.tsx`, `FlowEdge.tsx`,
  `StepPicker.tsx`, `ConnectDialog.tsx`, `StepPanel.tsx`, `ProblemsPanel.tsx`, `VersionsPanel.tsx`, `canvas.css`.
- Tests beside each (`*.test.ts(x)`), and `e2e/workflows.spec.ts`.

Frontend, modified: `package.json` and `pnpm-lock.yaml` (three packages), `src/router.tsx`, `src/components/Shell.tsx`,
`src/components/TenantSwitcher.tsx`, `src/components/CommandPalette.tsx`, `src/components/icons.tsx`,
`src/styles/theme.css`, `src/api/openapi.json`, `src/api/schema.d.ts`.

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

Inline, in one session (the owner's standing preference for coupled tasks), test-first: each task's tests are written
and seen failing for the stated reason before its code. The code below is the target; where the installed package or
the code base differs, the executor adapts it test-first and records the difference as a mid-slice ruling in the
ledger (4a's practice). Branch `feat/editor-4b`, cut from `feat/editor-4a` (stacked: #42 is open) when the owner settles
the branch point; once #42 merges, `origin/main` is merged in, never rebased (owner, 2026-10-06).

Checkpoints: the owner's at the end of the slice (one per slice, outline §2), preceded by a fresh-context review of the
whole branch against the brief's six hunts (a sensitive value reaching the DOM or a log, a live call, a write that
skips the server's checks, a CSP violation, keyboard traps and WCAG 2.2 AA failures, visible drift from the design),
and the one-page summary with screenshots beside frames 1a, 1b and 1c. At each milestone's end the executor runs that
milestone's focused tests and stops only on a failure; the owner may name milestone pauses when approving the plan.

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
    """The saved draft's diagnostics, at the revision they were computed for: an editor drops an answer for an
    older revision (D17)."""

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

### Task 3: A workflow's summary says how its runs went and whether its draft is published (B3)

**Files:**
- Create: `backend/src/dewpoint/core/workflows/summary.py`
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`LastRunOut`, `RunCountOut`; `WorkflowOut` and `DraftSavedOut`
  gain fields)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`_summaries`, `_summary`, `put_draft`)
- Create: `backend/tests/apps/api/test_workflow_summary.py`
- Modify: `backend/tests/apps/api/test_workflows.py:32` (the draft PUT's answer gains `unpublished_changes`)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: `runs` (`backend/src/dewpoint/core/models/runs.py:16-39`: `workflow_id`, `mode` live|simulate, `status`
  running|succeeded|failed|cancelled|deadline_exceeded, `queued_at`, `started_at`, `ended_at`, `kind` run|subflow|
  failure_handler); `graph_hash`, `parse_graph` (`backend/src/dewpoint/engine/graph/model.py`); the active version's
  `graph_hash`.
- Produces: `summary.run_stats(s, tenant_id, workflow_ids) -> dict[uuid.UUID, RunStats]`,
  `summary.unpublished(draft, active_graph_hash) -> bool`, `summary.ATTENTION_STATUSES`; `WorkflowOut` gains
  `unpublished_changes: bool`, `last_run: LastRunOut | None` (`status`, `mode`, `at`), `runs_24h: RunCountOut`
  (`live`, `simulate`), `needs_attention: list["last_run_failed" | "not_executable"]`; `DraftSavedOut` gains
  `unpublished_changes`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/apps/api/test_workflow_summary.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What the workflows list shows of each (sub-project 4, B3): its last root run, its root runs in the last 24 hours,
live and simulated apart, whether its draft differs from its active version, and why it needs attention."""

import uuid

import pytest
from sqlalchemy import text

from tests.apps.api.helpers import session_client
from tests.support.graphs import G
from tests.support.registry import sync_test_plugins

GRAPH = G().node("a", "testkit.echo@1", {"value": 1}).data()


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
        await add_run(owner_sessionmaker, tid, wid, vid, status="succeeded", mode="simulate", hours_ago=1.5)
        await add_run(owner_sessionmaker, tid, wid, vid, status="failed", hours_ago=0.5)  # the last root run
        await add_run(owner_sessionmaker, tid, wid, vid, status="running", hours_ago=0.1, parent=root)  # a sub-run
        quiet, _ = await published(c, tid)
        rows = {w["id"]: w for w in (await c.get(f"/api/v1/t/{tid}/workflows")).json()}
    busy = rows[wid]
    assert busy["last_run"]["status"] == "failed" and busy["last_run"]["mode"] == "live"
    assert busy["runs_24h"] == {"live": 2, "simulate": 1}
    assert busy["needs_attention"] == ["last_run_failed"]
    assert busy["unpublished_changes"] is False
    assert rows[quiet]["last_run"] is None and rows[quiet]["runs_24h"] == {"live": 0, "simulate": 0}
    assert rows[quiet]["needs_attention"] == []


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
        assert new["unpublished_changes"] is True and new["active_version_number"] is None
        wid, _ = await published(c, tid)
        base = f"/api/v1/t/{tid}/workflows/{wid}"
        same = await c.put(f"{base}/draft", json=GRAPH, headers={"If-Match": "1"})
        assert same.json() == {"draft_revision": 2, "unpublished_changes": False}
        moved = G().node("a", "testkit.echo@1", {"value": 1}).data()
        moved["nodes"][0]["position"] = {"x": 40, "y": 0}
        saved = await c.put(f"{base}/draft", json=moved, headers={"If-Match": "2"})
        assert saved.json() == {"draft_revision": 3, "unpublished_changes": True}
        assert (await c.get(base)).json()["unpublished_changes"] is True


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
```

The last test retires the node type the way `test_workflows.py:116-119` does: a type in use by an enabled workflow
isn't retired, so the workflow is disabled first.

In `backend/tests/apps/api/test_workflows.py:32`, the draft PUT's answer gains the new field:

```python
        assert saved.status_code == 200 and saved.json() == {"draft_revision": 2, "unpublished_changes": True}
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_workflow_summary.py tests/apps/api/test_workflows.py`
Expected: FAIL: `KeyError: 'last_run'` (and `'unpublished_changes'`), and the draft PUT's answer lacks
`unpublished_changes`.

- [ ] **Step 3: Implement the statistics**

`backend/src/dewpoint/core/workflows/summary.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""What the workflows list shows of each workflow beyond its row (sub-project 4, B3): its last root run, its root
runs in the last 24 hours, live and simulated apart, and whether its draft differs from its active version."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from dewpoint.core.models.runs import Run
from dewpoint.engine.graph.model import GraphFormatError, graph_hash, parse_graph

ATTENTION_STATUSES = ("failed", "deadline_exceeded")


@dataclass(frozen=True)
class LastRun:
    status: str
    mode: str
    at: datetime  # when it ended, else started, else was queued


@dataclass(frozen=True)
class RunStats:
    last: LastRun | None
    live_24h: int
    simulated_24h: int


async def run_stats(
    s: AsyncSession, tenant_id: uuid.UUID, workflow_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, RunStats]:
    """Each workflow's root runs: a sub-flow's or failure handler's run counts toward its parent's. `runs` has no
    index on `workflow_id` (4b ruling 5): the last runs are one ordered scan of the tenant's root runs, the counts a
    range of `runs_tenant_queued`. The 24 hours are the database's: its clock, not this process's, wrote the rows."""
    ids = sorted(set(workflow_ids), key=str)
    if not ids:
        return {}
    root = (Run.tenant_id == tenant_id, Run.kind == "run", Run.workflow_id.in_(ids))
    at = func.coalesce(Run.ended_at, Run.started_at, Run.queued_at).label("at")
    last_rows = await s.execute(
        select(Run.workflow_id, Run.status, Run.mode, at)
        .where(*root)
        .distinct(Run.workflow_id)
        .order_by(Run.workflow_id, Run.queued_at.desc(), Run.id.desc())
    )
    last = {r.workflow_id: LastRun(status=r.status, mode=r.mode, at=r.at) for r in last_rows}
    count_rows = await s.execute(
        select(
            Run.workflow_id,
            func.count().filter(Run.mode == "live").label("live"),
            func.count().filter(Run.mode == "simulate").label("simulated"),
        )
        .where(*root, Run.queued_at >= func.now() - timedelta(hours=24))
        .group_by(Run.workflow_id)
    )
    counts = {r.workflow_id: (int(r.live), int(r.simulated)) for r in count_rows}
    return {
        wid: RunStats(last=last.get(wid), live_24h=counts.get(wid, (0, 0))[0], simulated_24h=counts.get(wid, (0, 0))[1])
        for wid in ids
    }


def unpublished(draft: dict[str, Any], active_graph_hash: str | None) -> bool:
    """Whether the draft differs from the active version's graph as publish hashes it (positions included); a
    workflow never published counts as unpublished."""
    if active_graph_hash is None:
        return True
    try:
        return graph_hash(parse_graph(draft)) != active_graph_hash
    except GraphFormatError:  # every draft is format-checked when saved; one that isn't differs
        return True
```

- [ ] **Step 4: Implement the answers**

In `backend/src/dewpoint/apps/api/responses.py`, before `WorkflowOut`:

```python
class LastRunOut(_Answer):
    status: Literal["running", "succeeded", "failed", "cancelled", "deadline_exceeded"]
    mode: Literal["live", "simulate"]
    at: str  # when it ended, else started, else was queued


class RunCountOut(_Answer):
    live: int
    simulate: int
```

and add to `WorkflowOut`, after `updated_at` (B3):

```python
    unpublished_changes: bool  # the draft differs from the active version (true when nothing is published)
    last_run: LastRunOut | None  # its last root run, of either mode
    runs_24h: RunCountOut  # its root runs queued in the last 24 hours, live and simulated apart
    needs_attention: list[Literal["last_run_failed", "not_executable"]]
```

and to `DraftSavedOut`:

```python
    unpublished_changes: bool
```

In `backend/src/dewpoint/apps/api/routes/workflows.py`, import `summary` (`from dewpoint.core.workflows import service,
summary`), and replace `_summary` with:

```python
async def _summaries(db: AsyncSession, tenant_id: uuid.UUID, wfs: list[Workflow]) -> list[dict[str, object]]:
    stats = await summary.run_stats(db, tenant_id, [wf.id for wf in wfs])
    out: list[dict[str, object]] = []
    for wf in wfs:
        await db.refresh(wf)
        active = await service.get_version(db, wf.id, wf.active_version_id) if wf.active_version_id else None
        blocked = await service.blocked_by(db, active) if active else []
        runs = stats[wf.id]
        needs: list[str] = []
        if runs.last is not None and runs.last.status in summary.ATTENTION_STATUSES:
            needs.append("last_run_failed")
        if active is not None and blocked:
            needs.append("not_executable")
        out.append(
            {
                "id": str(wf.id),
                "name": wf.name,
                "enabled": wf.enabled,
                "draft_revision": wf.draft_revision,
                "active_version_id": str(active.id) if active else None,
                "active_version_number": active.number if active else None,
                "executable": (not blocked) if active else None,
                "blocked_by": blocked,
                "created_at": wf.created_at.isoformat(),
                "updated_at": wf.updated_at.isoformat(),
                "unpublished_changes": summary.unpublished(wf.draft, active.graph_hash if active else None),
                "last_run": None
                if runs.last is None
                else {"status": runs.last.status, "mode": runs.last.mode, "at": runs.last.at.isoformat()},
                "runs_24h": {"live": runs.live_24h, "simulate": runs.simulated_24h},
                "needs_attention": needs,
            }
        )
    return out


async def _summary(db: AsyncSession, wf: Workflow) -> dict[str, object]:
    return (await _summaries(db, wf.tenant_id, [wf]))[0]
```

`list_workflows` becomes `return await _summaries(db, ctx.tenant_id, await service.list_workflows(db, ctx.tenant_id))`.
`put_draft` answers the comparison too:

```python
    try:
        revision = await service.save_draft(db, wf, expected_revision=expected, draft=draft)
    except service.DraftConflictError as e:
        raise HTTPException(409, detail={"error": "draft_conflict", "draft_revision": e.current_revision}) from None
    active = await service.get_version(db, wf.id, wf.active_version_id) if wf.active_version_id else None
    return {"draft_revision": revision, "unpublished_changes": summary.unpublished(draft, active.graph_hash if active else None)}
```

- [ ] **Step 5: Run the tests to see them pass, then the workflow suites**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_workflow_summary.py tests/apps/api/test_workflows.py tests/apps/api/test_openapi.py tests/core/workflows`
Expected: PASS. If the raw `runs` insert of Step 1 trips a CHECK this plan doesn't name (a sub-run's columns), adapt
the helper to the constraint the error names, never the code under test.

- [ ] **Step 6: Regenerate the client's schema and check it.** Expected: `WorkflowOut` gains the four fields.

- [ ] **Step 7: Commit**

```bash
git add backend/src/dewpoint/core/workflows/summary.py backend/src/dewpoint/apps/api \
  backend/tests/apps/api/test_workflow_summary.py backend/tests/apps/api/test_workflows.py frontend/src/api
git commit -m "feat(api): a workflow's summary says how its runs went and whether its draft is published (B3, 4b)"
```

### Task 4: A version can be read whole, with its graph and its `engine_abi` (B4a)

**Files:**
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`VersionOut.engine_abi`; `VersionDetailOut`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`_version_out`; `GET …/versions/{version_id}`)
- Modify: `backend/src/dewpoint/apps/api/openapi.py` (`GRAPH_PROPERTIES` gains `("VersionDetailOut", "graph")`)
- Create: `backend/tests/apps/api/test_workflow_versions.py`
- Modify: `backend/tests/apps/api/test_openapi.py` (`SLICE_4B` gains the route)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: `WorkflowVersion.graph`, `.engine_abi`, `.expressions` (each `ExpressionRecord.to_json()`, with `node`,
  `field`, `mode`, `reason` among its keys: `backend/src/dewpoint/engine/cel/record.py:21-40`).
- Produces: `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}` → `VersionDetailOut` (every
  `VersionOut` field, plus `graph` (verbatim, documented as `Graph`) and `expressions: ExpressionOut[]`); `VersionOut`
  gains `engine_abi: int` (B4b's "not recorded" rule reads it). Permission `workflow.view`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/apps/api/test_workflow_versions.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A published version read whole (sub-project 4, B4a): its graph, how its expressions run, and its engine ABI."""

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
```

The `/value` pointer and the `local` mode assume `testkit.echo`'s config property is `value` and `1 + 1` runs inline;
if the echo node names its field otherwise, use the pointer `test_workflows.py`'s expression-class test asserts.

In `backend/tests/apps/api/test_openapi.py`, add `("get", "/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}")`
to `SLICE_4B`, and:

```python
def test_a_versions_graph_is_documented_as_a_graph() -> None:
    assert schema()["components"]["schemas"]["VersionDetailOut"]["properties"]["graph"] == GRAPH
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_workflow_versions.py tests/apps/api/test_openapi.py`
Expected: FAIL: `KeyError: 'engine_abi'`, a 404 or 405 for the version route, and `KeyError: 'VersionDetailOut'`.

- [ ] **Step 3: Implement**

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

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/apps/api/test_workflow_versions.py tests/apps/api/test_openapi.py tests/apps/api/test_workflows.py`
Expected: PASS.

- [ ] **Step 5: Regenerate the client's schema and check it.**

- [ ] **Step 6: Commit**

```bash
git add backend/src/dewpoint/apps/api backend/tests/apps/api/test_workflow_versions.py \
  backend/tests/apps/api/test_openapi.py frontend/src/api
git commit -m "feat(api): a version read whole, with its graph, expressions and engine ABI (B4a, 4b)"
```

### Task 5: A workflow exports to a file with typed placeholders and imports with each re-bound (B12)

**Files:**
- Create: `backend/src/dewpoint/core/workflows/portable.py`
- Modify: `backend/src/dewpoint/core/workflows/service.py` (`create_workflow(..., source=None)`)
- Modify: `backend/src/dewpoint/apps/api/responses.py` (`BindingSite`, `Binding`, `WorkflowDocument`)
- Modify: `backend/src/dewpoint/apps/api/routes/workflows.py` (`WorkflowImportIn`; `GET …/{workflow_id}/export`,
  `POST /t/{tenant_id}/workflows/import`)
- Modify: `backend/src/dewpoint/apps/api/openapi.py` (`GRAPH_PROPERTIES` gains `("WorkflowDocument", "graph")`)
- Create: `backend/tests/core/workflows/test_portable.py`, `backend/tests/apps/api/test_workflow_portable.py`
- Modify: `backend/tests/apps/api/test_openapi.py` (`SLICE_4B` gains both routes)
- Regenerate: `frontend/src/api/openapi.json`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Consumes: the connection marker `x-dewpoint-connection: <type key>` on a node type's top-level config property
  (`backend/src/dewpoint/sdk/fields.py:9-34`); `flow.run_workflow@1`'s literal `workflow_id`
  (`backend/src/dewpoint/plugins/flow/nodes.py:163`); `settings.failure_handler`; `registry.list_node_types(db,
  states)`; `Connection.type`, `.name` (`backend/src/dewpoint/core/models/connections.py:13-21`).
- Produces: `portable.Site(kind, type, node, field)`, `portable.sites(draft, config_schemas) -> list[Site]`,
  `portable.value_at(draft, site)`, `portable.export_document(name, draft, config_schemas, labels) -> dict`,
  `portable.apply(graph, bindings, chosen) -> dict`, `portable.SiteError(binding)`; the routes
  `GET /api/v1/t/{tenant_id}/workflows/{workflow_id}/export` → `WorkflowDocument` (`workflow.view`) and
  `POST /api/v1/t/{tenant_id}/workflows/import` (`{name, document, bind: {binding id: uuid}}`) → 201
  `WorkflowDetailOut` (`workflow.edit`); refusals `422 {"error":"bad_binding","binding":id,"reason":"unexpected"|
  "unknown"|"wrong_type"|"site"}`, `422 {"error":"invalid","diagnostics"}` (format), `409 name_taken`.

- [ ] **Step 1: Write the failing unit tests**

`backend/tests/core/workflows/test_portable.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A workflow as a file (sub-project 4, B12): no tenant's id travels in it."""

import uuid

import pytest

from dewpoint.core.workflows import portable

CALL, SUB, ODD = (str(uuid.uuid4()) for _ in range(3))
C1, W1 = str(uuid.uuid4()), str(uuid.uuid4())
SCHEMAS = {
    "testkit.http_call@1": {
        "properties": {"connection": {"type": "string", "x-dewpoint-connection": "testkit"}, "path": {"type": "string"}}
    }
}


def draft(conn: str, sub: str) -> dict:
    return {
        "graph_format": 1,
        "nodes": [
            {"id": CALL, "key": "call", "type": "testkit.http_call@1", "config": {"connection": conn, "path": "/x"}},
            {"id": SUB, "key": "sub", "type": "flow.run_workflow@1", "config": {"workflow_id": sub, "input": {}}},
            {"id": ODD, "key": "odd", "type": "vendor.unknown@1", "config": {"connection": "kept as it is"}},
        ],
        "edges": [],
        "settings": {"failure_handler": sub},
    }


LABELS = {("connection", C1): "Acme Prod", ("workflow", W1): "Cleanup"}


def test_export_replaces_each_tenant_id_with_a_typed_placeholder() -> None:
    doc = portable.export_document("Nightly", draft(C1, W1), SCHEMAS, LABELS)
    assert (doc["format"], doc["format_version"], doc["name"]) == ("dewpoint.workflow", 1, "Nightly")
    assert doc["bindings"] == [
        {"id": "b1", "kind": "connection", "type": "testkit", "label": "Acme Prod",
         "sites": [{"node": CALL, "field": "/connection"}]},
        {"id": "b2", "kind": "workflow", "type": None, "label": "Cleanup",
         "sites": [{"node": SUB, "field": "/workflow_id"}, {"node": None, "field": "/settings/failure_handler"}]},
    ]  # fmt: skip
    nodes = {n["key"]: n for n in doc["graph"]["nodes"]}
    assert nodes["call"]["config"] == {"path": "/x"}
    assert nodes["sub"]["config"] == {"input": {}}
    assert "failure_handler" not in doc["graph"]["settings"]
    assert nodes["odd"]["config"] == {"connection": "kept as it is"}  # an unknown type holds no known site


def test_an_id_the_tenant_doesnt_name_is_labelled_unknown() -> None:
    doc = portable.export_document("Nightly", draft(C1, W1), SCHEMAS, {})
    assert [b["label"] for b in doc["bindings"]] == ["Unknown connection", "Unknown workflow"]


def test_import_binds_each_placeholder_and_round_trips() -> None:
    doc = portable.export_document("Nightly", draft(C1, W1), SCHEMAS, LABELS)
    assert portable.apply(doc["graph"], doc["bindings"], {"b1": C1, "b2": W1}) == draft(C1, W1)


def test_an_unbound_placeholder_leaves_its_sites_empty() -> None:
    doc = portable.export_document("Nightly", draft(C1, W1), SCHEMAS, LABELS)
    back = portable.apply(doc["graph"], doc["bindings"], {"b1": C1})
    nodes = {n["key"]: n for n in back["nodes"]}
    assert nodes["call"]["config"]["connection"] == C1
    assert "workflow_id" not in nodes["sub"]["config"] and "failure_handler" not in back["settings"]


@pytest.mark.parametrize(
    "site",
    [
        {"node": str(uuid.uuid4()), "field": "/connection"},  # no such node
        {"node": CALL, "field": "/nested/connection"},  # not a top-level property
        {"node": None, "field": "/settings/outputs"},  # not the failure handler
    ],
)
def test_a_site_outside_what_bindings_may_write_is_refused(site: dict) -> None:
    binding = {"id": "b7", "kind": "connection", "type": "testkit", "label": "x", "sites": [site]}
    with pytest.raises(portable.SiteError) as e:
        portable.apply(draft(C1, W1), [binding], {"b7": C1})
    assert e.value.binding == "b7"
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/core/workflows/test_portable.py`
Expected: FAIL: `ImportError: cannot import name 'portable'`.

- [ ] **Step 3: Implement `portable.py`**

`backend/src/dewpoint/core/workflows/portable.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""A workflow as a file (sub-project 4, B12). Exported, every id of the tenant's a draft holds (a connection, a
workflow) is replaced by a typed placeholder; imported, each placeholder is bound to one of the importing tenant's
connections or workflows, or left unbound, its sites empty. Schedules, webhook bindings and CSV mappings are rows,
not graph: they don't travel."""

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

FORMAT = "dewpoint.workflow"
FORMAT_VERSION = 1
RUN_WORKFLOW = "flow.run_workflow@1"
CONNECTION_MARKER = "x-dewpoint-connection"
FAILURE_HANDLER = "/settings/failure_handler"
UNKNOWN = {"connection": "Unknown connection", "workflow": "Unknown workflow"}

Kind = Literal["connection", "workflow"]


@dataclass(frozen=True)
class Site:
    kind: Kind
    type: str | None  # the connection type a connection site takes; None for a workflow
    node: str | None  # a node's id; None for the workflow's settings
    field: str  # a top-level config property (`/connection`), or FAILURE_HANDLER


class SiteError(ValueError):
    """A binding names a site outside what an import may write: no such node, a nested pointer, other settings."""

    def __init__(self, binding: str) -> None:
        super().__init__(f"binding {binding} names a site an import can't write")
        self.binding = binding


def sites(draft: Mapping[str, Any], config_schemas: Mapping[str, Mapping[str, Any]]) -> list[Site]:
    """Where a draft may hold an id of the tenant's: each top-level config property its node's type marks as a
    connection, each `flow.run_workflow`'s `workflow_id`, and the failure handler. A node of a type
    `config_schemas` (keyed by type ref) lacks holds no known site: its config is kept as it is."""
    out: list[Site] = []
    for node in draft.get("nodes", []):
        ref, node_id = node.get("type"), str(node.get("id"))
        properties = config_schemas.get(ref, {}).get("properties", {})
        for prop, spec in properties.items():
            if isinstance(spec, Mapping) and spec.get(CONNECTION_MARKER):
                out.append(Site("connection", str(spec[CONNECTION_MARKER]), node_id, f"/{prop}"))
        if ref == RUN_WORKFLOW:
            out.append(Site("workflow", None, node_id, "/workflow_id"))
    out.append(Site("workflow", None, None, FAILURE_HANDLER))
    return out


def _node(graph: Mapping[str, Any], node_id: str) -> Any:
    return next((n for n in graph.get("nodes", []) if str(n.get("id")) == node_id), None)


def value_at(draft: Mapping[str, Any], site: Site) -> Any:
    if site.node is None:
        return (draft.get("settings") or {}).get("failure_handler")
    node = _node(draft, site.node)
    return None if node is None else (node.get("config") or {}).get(site.field[1:])


def _remove(graph: dict[str, Any], site: Site) -> None:
    if site.node is None:
        (graph.get("settings") or {}).pop("failure_handler", None)
        return
    node = _node(graph, site.node)
    if node is not None:
        (node.get("config") or {}).pop(site.field[1:], None)


def export_document(
    name: str,
    draft: Mapping[str, Any],
    config_schemas: Mapping[str, Mapping[str, Any]],
    labels: Mapping[tuple[str, str], str],
) -> dict[str, Any]:
    """The file: the draft without its ids, and one binding per distinct id, in the order first met, each with every
    site it filled. `labels` maps (kind, id as the draft holds it) to its name in the tenant."""
    graph = copy.deepcopy(dict(draft))
    bindings: dict[tuple[str, str], dict[str, Any]] = {}
    for site in sites(draft, config_schemas):
        value = value_at(draft, site)
        if not isinstance(value, str) or not value:
            continue
        key = (site.kind, value)
        if key not in bindings:
            bindings[key] = {
                "id": f"b{len(bindings) + 1}",
                "kind": site.kind,
                "type": site.type,
                "label": labels.get(key, UNKNOWN[site.kind]),
                "sites": [],
            }
        bindings[key]["sites"].append({"node": site.node, "field": site.field})
        _remove(graph, site)
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "name": name,
        "graph": graph,
        "bindings": list(bindings.values()),
    }


def apply(graph: Mapping[str, Any], bindings: Sequence[Mapping[str, Any]], chosen: Mapping[str, str]) -> dict[str, Any]:
    """The graph with each chosen binding's id written at each of its sites; an unbound binding's sites stay empty.
    A site may only be a listed node's top-level config property, or the failure handler."""
    out = copy.deepcopy(dict(graph))
    for binding in bindings:
        value = chosen.get(binding["id"])
        if value is None:
            continue
        for site in binding["sites"]:
            field, node_id = str(site["field"]), site["node"]
            if node_id is None:
                if field != FAILURE_HANDLER:
                    raise SiteError(binding["id"])
                out.setdefault("settings", {})["failure_handler"] = value
                continue
            node = _node(out, str(node_id))
            if node is None or not field.startswith("/") or "/" in field[1:] or not field[1:]:
                raise SiteError(binding["id"])
            node.setdefault("config", {})[field[1:]] = value
    return out
```

- [ ] **Step 4: Run the unit tests to see them pass**

Run: `cd backend && uv run pytest -q -p no:cacheprovider tests/core/workflows/test_portable.py`
Expected: PASS.

- [ ] **Step 5: Write the failing API tests**

`backend/tests/apps/api/test_workflow_portable.py`:

```python
# SPDX-License-Identifier: Apache-2.0
"""Exporting a workflow and importing it into another tenant (sub-project 4, B12)."""

import uuid

import pytest

from tests.apps.api.helpers import member_client, session_client
from tests.support.connections import add_connection
from tests.support.registry import sync_test_plugins

CALL, SUB = str(uuid.uuid4()), str(uuid.uuid4())


@pytest.fixture(autouse=True)
async def synced(admin_sessionmaker) -> None:
    await sync_test_plugins(admin_sessionmaker)


def draft(conn: str, sub: str) -> dict:
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
    c, tid = await session_client(app, owner_sessionmaker, api_settings, "editor")
    async with c:
        r = await c.post(f"/api/v1/t/{tid}/workflows/import", json={"name": "Imported", "document": doc})
    assert r.status_code == 201, r.text
    assert r.json()["draft"]["nodes"][0]["config"] == {"path": "/x"}


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

In `backend/src/dewpoint/apps/api/responses.py`, after `VersionDetailOut`:

```python
class BindingSite(_Answer):
    node: str | None  # a node's id; null for the workflow's settings
    field: str  # a top-level config property (`/connection`), or `/settings/failure_handler`


class Binding(_Answer):
    """One id of the exporting tenant's (a connection, a workflow), as a placeholder an import binds or leaves."""

    id: str
    kind: Literal["connection", "workflow"]
    type: str | None  # the connection type it takes; null for a workflow
    label: str
    sites: list[BindingSite]


class WorkflowDocument(_Answer):
    """A workflow as a file (B12): its graph without the tenant's ids (documented as a Graph), and their bindings."""

    format: Literal["dewpoint.workflow"]
    format_version: Literal[1]
    name: str
    graph: dict[str, Any]
    bindings: list[Binding]
```

In `backend/src/dewpoint/core/workflows/service.py`, `create_workflow` records where a workflow came from when it
wasn't typed in:

```python
async def create_workflow(
    s: AsyncSession, ctx: TenantContext, *, name: str, draft: dict[str, Any], source: str | None = None
) -> Workflow:
```

and its audit call's details become `{"name": name, **({"source": source} if source else {})}`.

In `backend/src/dewpoint/apps/api/routes/workflows.py`, import `portable`, `registry`, the `Connection` model,
`select`, `Binding` is not needed by name, and add:

```python
class WorkflowImportIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    document: WorkflowDocument
    bind: dict[str, uuid.UUID] = Field(default_factory=dict)  # binding id -> one of this tenant's; absent: unbound


def _bad_binding(binding: str, reason: str) -> HTTPException:
    return HTTPException(422, detail={"error": "bad_binding", "binding": binding, "reason": reason})


async def _config_schemas(db: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = await registry.list_node_types(db, states=("active", "deprecated", "retired"))
    return {row.ref: row.manifest.get("config_schema") or {} for row in rows}


async def _labels(db: AsyncSession, tenant_id: uuid.UUID, draft: dict[str, Any], found: list[portable.Site]) -> dict[tuple[str, str], str]:
    """Each id the draft holds at a site, as the draft holds it, to its name in this tenant."""
    raw: dict[str, dict[uuid.UUID, str]] = {"connection": {}, "workflow": {}}
    for site in found:
        value = portable.value_at(draft, site)
        if isinstance(value, str):
            try:
                raw[site.kind][uuid.UUID(value)] = value
            except ValueError:
                continue
    labels: dict[tuple[str, str], str] = {}
    for model, kind in ((Connection, "connection"), (Workflow, "workflow")):
        if raw[kind]:
            rows = await db.execute(
                select(model.id, model.name).where(model.tenant_id == tenant_id, model.id.in_(list(raw[kind])))
            )
            labels.update({(kind, raw[kind][row.id]): row.name for row in rows})
    return labels


@router.get("/t/{tenant_id}/workflows/{workflow_id}/export", response_model=WorkflowDocument)
async def export(
    workflow_id: uuid.UUID,
    ctx: TenantContext = Depends(require(P.WORKFLOW_VIEW)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """The saved draft as a file, every id of this tenant's replaced by a typed placeholder (B12)."""
    wf = await _get(db, ctx, workflow_id)
    schemas = await _config_schemas(db)
    labels = await _labels(db, ctx.tenant_id, wf.draft, portable.sites(wf.draft, schemas))
    return portable.export_document(wf.name, wf.draft, schemas, labels)


@router.post("/t/{tenant_id}/workflows/import", status_code=201, response_model=WorkflowDetailOut)
async def import_workflow(
    body: WorkflowImportIn,
    ctx: TenantContext = Depends(require(P.WORKFLOW_EDIT)),
    db: AsyncSession = Depends(get_db, scope="function"),
) -> dict[str, object]:
    """A new workflow from a file, each binding bound to one of this tenant's connections (of its type) or workflows,
    or left unbound. Every binding is checked before anything is written."""
    bindings = {b.id: b for b in body.document.bindings}
    for key, chosen in body.bind.items():
        binding = bindings.get(key)
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
    try:
        draft = portable.apply(
            body.document.graph,
            [b.model_dump() for b in body.document.bindings],
            {key: str(value) for key, value in body.bind.items()},
        )
    except portable.SiteError as e:
        raise _bad_binding(e.binding, "site") from None
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
  `BindingSite` and `WorkflowImportIn` appear; `WorkflowDocument["graph"]` is a `Graph`.

- [ ] **Step 10: Commit**

```bash
git add backend/src/dewpoint/core/workflows backend/src/dewpoint/apps/api backend/tests/core/workflows/test_portable.py \
  backend/tests/apps/api/test_workflow_portable.py backend/tests/apps/api/test_openapi.py frontend/src/api
git commit -m "feat(api): a workflow exports with typed placeholders and imports with each re-bound (B12, 4b)"
```

**Milestone 1's check:** `cd backend && uv run pytest -q -n 12 -p no:cacheprovider tests/apps/api tests/apps/test_workflow_ops.py tests/core/workflows`, then the static checks. All pass.

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
    staleTime: Infinity, // the editor owns the draft once loaded: a refetch never replaces what's being edited
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
- Modify: `frontend/src/routes/Workflows.tsx`
- Create: `frontend/src/routes/Workflows.test.tsx`, `frontend/src/components/Switch.test.tsx`,
  `frontend/src/components/Segmented.test.tsx`
- Modify: `frontend/src/styles/tokenNames.ts` only if a new colour pair renders (none expected: the switch uses
  `line-control` on `surface-2` and `on-accent` on `accent`, both in PAIRS)

**Interfaces:**
- Consumes: `WorkflowRow` (B3's `unpublished_changes`, `last_run`, `runs_24h`, `needs_attention`),
  `canPublish(role)`, `tenantQuery`, `since`, `announce`, `PATCH …/{workflow_id}` (`{enabled}`; `422 not_enableable`
  with diagnostics), `GET …/{workflow_id}/export`.
- Produces: `<Switch checked onCheckedChange label disabled? />`, `<Segmented label options value onChange />`
  (`options: {value, label, count}[]`), `downloadJson(name, data)`, `fileName(name, suffix)`. Task 8 adds the
  "New workflow" button and its dialog to this page.

- [ ] **Step 1: Write the failing tests**

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
  unpublished_changes: false, last_run: { status: "succeeded", mode: "live", at: "2026-10-06T11:48:00Z" },
  runs_24h: { live: 4, simulate: 0 }, needs_attention: [], ...over,
});  // prettier-ignore
const ROWS = [
  row({}),
  row({ id: "w2", name: "Triage", enabled: false, unpublished_changes: true, runs_24h: { live: 1, simulate: 2 },
        last_run: { status: "failed", mode: "live", at: "2026-10-06T11:00:00Z" }, needs_attention: ["last_run_failed"] }),
  row({ id: "w3", name: "Sketch", active_version_id: null, active_version_number: null, executable: null,
        unpublished_changes: true, last_run: null, runs_24h: { live: 0, simulate: 0 } }),
];  // prettier-ignore

let role = "editor";
let sent: { method: string; path: string; body: unknown }[];
let patchAnswer: Response | null;

beforeEach(() => {
  role = "editor";
  sent = [];
  patchAnswer = null;
  vi.spyOn(Date, "now").mockReturnValue(NOW);
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
    if (request.method === "PATCH") return patchAnswer ?? new Response(JSON.stringify({ ...ROWS[0], enabled: false, warnings: [] }));
    if (path === "/api/v1/t/t1") return new Response(JSON.stringify({ id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }));
    if (path === "/api/v1/t/t1/workflows/w2/export") return new Response(JSON.stringify({ format: "dewpoint.workflow", format_version: 1, name: "Triage", graph: {}, bindings: [] }));
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
  expect(rowOf("Triage").textContent).toContain("1 +2 simulated");
  expect(rowOf("Sketch").textContent).toContain("Not published");
  expect(rowOf("Sketch").textContent).toContain("No runs yet");
});

it("filters by state, with counts, and by name", async () => {
  await show();
  const filters = screen.getByRole("group", { name: "Show" });
  expect(within(filters).getAllByRole("button").map((b) => b.textContent)).toEqual([
    "All 3", "Published 2", "Unpublished changes 1", "Needs attention 1",
  ]);  // prettier-ignore
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
import { canPublish, since, tenantQuery, workflowsQuery, type WorkflowRow } from "../lib/workflows";

type Filter = "all" | "published" | "unpublished" | "attention";

const FILTERS: { value: Filter; label: string; keep: (w: WorkflowRow) => boolean }[] = [
  { value: "all", label: "All", keep: () => true },
  { value: "published", label: "Published", keep: (w) => w.active_version_id !== null },
  { value: "unpublished", label: "Unpublished changes", keep: (w) => w.active_version_id !== null && w.unpublished_changes },
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

function LastRun({ w }: { w: WorkflowRow }) {
  if (!w.last_run) return <span className="text-muted">No runs yet</span>;
  const s = STATUS[w.last_run.status];
  return (
    <span className="inline-flex items-center gap-2 text-small">
      <span aria-hidden="true" className={`size-2 rounded-sm ${s.dot}`} />
      {s.text}
      {w.last_run.mode === "simulate" && <span className="text-sim"> (simulated)</span>} · {since(w.last_run.at)}
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
    } catch {
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
  WorkflowDocument | null`, `<ImportBindings tenantId bindings chosen onChange />`, `type Chosen = Record<string,
  string>`.

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

beforeEach(() => {
  sent = [];
  answer = { status: 201, body: { id: "w9", name: "Nightly report" } };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const request = input as Request;
    const path = new URL(request.url).pathname;
    const text = await request.text();
    sent.push({ method: request.method, path, body: text ? JSON.parse(text) : null });
    if (request.method === "POST") return new Response(JSON.stringify(answer.body), { status: answer.status });
    if (path.endsWith("/connections")) return new Response(JSON.stringify(CONNECTIONS));
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
// ruling 18). A connection binding offers only connections of its type.
import { useQuery } from "@tanstack/react-query";
import { Select } from "../components/Field";
import { client, ok } from "../lib/client";
import { workflowsQuery, type WorkflowDocument } from "../lib/workflows";

export type Chosen = Record<string, string>;

export function ImportBindings({
  tenantId,
  bindings,
  chosen,
  onChange,
}: {
  tenantId: string;
  bindings: WorkflowDocument["bindings"];
  chosen: Chosen;
  onChange: (chosen: Chosen) => void;
}) {
  const connections = useQuery({
    queryKey: ["connections", tenantId],
    queryFn: () => ok(client.GET("/api/v1/t/{tenant_id}/connections", { params: { path: { tenant_id: tenantId } } })),
    enabled: bindings.some((b) => b.kind === "connection"),
  });
  const workflows = useQuery({ ...workflowsQuery(tenantId), enabled: bindings.some((b) => b.kind === "workflow") });
  if (bindings.length === 0) return <p className="text-small text-muted">The file names no connection or workflow.</p>;
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-1 text-small font-semibold">What the file names, bound to this tenant&apos;s</legend>
      {bindings.map((b) => {
        const options =
          b.kind === "connection"
            ? (connections.data ?? []).filter((c) => c.type === b.type).map((c) => ({ id: c.id, name: c.name }))
            : (workflows.data ?? []).map((w) => ({ id: w.id, name: w.name }));
        const places = `${b.sites.length} place${b.sites.length === 1 ? "" : "s"} in the graph`;
        return (
          <Select
            key={b.id}
            label={`${b.label} (${b.kind === "connection" ? `${b.type} connection` : "workflow"})`}
            hint={places}
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
import { ImportBindings, type Chosen } from "./ImportBindings";

type Start = "blank" | "import";

/** A workflow file, or null: only its format, version and shape are checked here; the API checks the graph. */
export function parseDocument(text: string): WorkflowDocument | null {
  try {
    const doc = JSON.parse(text) as Partial<WorkflowDocument> | null;
    if (!doc || doc.format !== "dewpoint.workflow" || doc.format_version !== 1) return null;
    if (typeof doc.name !== "string" || typeof doc.graph !== "object" || !Array.isArray(doc.bindings)) return null;
    return doc as WorkflowDocument;
  } catch {
    return null;
  }
}

const REASONS: Record<string, string> = {
  unknown: "isn't one of this tenant's",
  wrong_type: "is of another type",
  unexpected: "isn't in the file",
  site: "names a place an import can't write",
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
  if (e.code === "invalid") {
    const first = (e.body as { diagnostics?: { message: string }[] }).diagnostics?.[0]?.message;
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

  const ready = name.trim().length > 0 && (start === "blank" || doc !== null);

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
            {doc && <ImportBindings tenantId={tenantId} bindings={doc.bindings} chosen={chosen} onChange={setChosen} />}
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
  -> GraphDoc | null`, `moveNodes(doc, positions: Map<string, {x, y}>)`. (`history.ts`): `type History<T>`,
  `LIMIT = 100`, `begin(present)`, `record(h, next)`, `undo(h)`, `redo(h)`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/graph.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import {
  ROW, addAfter, canConnect, connect, continuationPort, defaultConfig, deleteEdge, deleteNode, edgeId, entries,
  insertBeforeEntry, insertOnEdge, keyFor, moveNodes, portsOf, startPosition,
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
the editor hands it, each step with a button that opens it and one that adds after it, honours focus requests and
passes keys through, so the editor's own logic runs in jsdom; Task 12 adds tests to it):

```tsx
// SPDX-License-Identifier: Apache-2.0
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { CanvasProps } from "./Canvas";
import { EditorPage } from "./Editor";

vi.mock("./Canvas", async () => {
  const { useEffect } = await import("react");
  return {
    Canvas: (props: CanvasProps) => {
      useEffect(() => {
        if (props.focusRequest) document.querySelector<HTMLElement>(`[data-item="${props.focusRequest.id}"]`)?.focus();
      }, [props.focusRequest]);
      return (
        <div role="group" aria-label="Workflow steps" onKeyDown={props.onKeyDown}>
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
const WORKFLOW = {
  id: "w1", name: "Nightly", enabled: true, draft_revision: 1, active_version_id: null, active_version_number: null,
  executable: null, blocked_by: [], created_at: "", updated_at: "", unpublished_changes: true, last_run: null,
  runs_24h: { live: 0, simulate: 0 }, needs_attention: [], draft: { graph_format: 1, nodes: [], edges: [] },
};  // prettier-ignore
let role = "editor";

beforeEach(() => {
  role = "editor";
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const path = new URL((input as Request).url).pathname;
    const body = path === "/api/v1/node-types" ? TYPES
      : path === "/api/v1/t/t1" ? { id: "t1", name: "Acme", slug: "acme", require_passkey: false, role }
      : path.endsWith("/validate") ? { draft_revision: 1, valid: true, diagnostics: [], expressions: [], taint: { sites: [], declassified: [] } }
      : WORKFLOW;  // prettier-ignore
    return Promise.resolve(new Response(JSON.stringify(body)));
  });
});

async function show() {
  const root = createRootRoute({ component: () => <EditorPage tenantId="t1" workflowId="w1" /> });
  const list = createRoute({ getParentRoute: () => root, path: "/t/$tenantId/workflows", component: () => <p>list</p> });
  const router = createRouter({ routeTree: root.addChildren([list]), history: createMemoryHistory({ initialEntries: ["/"] }) });
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  await screen.findByRole("group", { name: "Workflow steps" });
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
  await screen.findByRole("heading", { level: 1, name: "Nightly" });
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
import { START, edgesOf, entries, nodesOf, portOf, portsOf, pos, startPosition, type PortRef } from "../../lib/graph";
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

function build(p: CanvasProps): { nodes: Node[]; edges: Edge[] } {
  const used = new Map<string, string[]>();
  for (const e of edgesOf(p.doc)) used.set(e.from.node, [...(used.get(e.from.node) ?? []), portOf(e)]);
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
    ...edgesOf(p.doc).map((e): Edge => ({
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
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`
- Modify: `frontend/e2e/workflows.spec.ts`

**Interfaces:**
- Consumes: `item`, `ItemAction` (Task 11); `deleteNode`, `deleteEdge`, `canConnect`, `connect`, `moveNodes`,
  `portsOf` (Task 9); `undo`, `redo` (Task 9); `ConfirmDialog` (`frontend/src/components/ConfirmDialog.tsx`).
- Produces: `type NavKey`; `navModel(doc, portsOf, editable) -> Nav` (`children`, `parent`, `order`, `edges`);
  `move(nav, from, key) -> string`; `<ConnectDialog doc types from onConnect onClose />`; `<StepPanel node type
  ports problems expressions editable onDelete onConnectPort onClose />` (Task 14 fills `problems` and
  `expressions`).

- [ ] **Step 1: Write the failing tests**

`frontend/src/routes/editor/canvasNav.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import type { GraphDoc } from "../../lib/workflows";
import { move, navModel } from "./canvasNav";

const node = (id: string, x = 0) => ({ id, key: id, type: "flow.transform@1", position: { x, y: 0 } });
const edge = (from: string, to: string, port = "out") => ({ from: { node: from, port }, to: { node: to } });
const ports = (map: Record<string, string[]>) => (id: string) => map[id] ?? ["out"];

it("walks a chain down and back up, through its edges and its last free port", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b")] };
  const nav = navModel(doc, ports({}), true);
  const path = ["start"];
  for (let i = 0; i < 5; i++) path.push(move(nav, path.at(-1)!, "ArrowDown"));
  expect(path).toEqual(["start", "entry:a", "node:a", "edge:a:out->b", "node:b", "port:b:out"]);
  expect(move(nav, "node:b", "ArrowUp")).toBe("edge:a:out->b");
  expect(move(nav, "port:b:out", "ArrowDown")).toBe("port:b:out");
  expect(move(nav, "node:b", "Home")).toBe("start");
});

it("moves across a branch's ports, left to right, an empty port included", () => {
  const doc: GraphDoc = { graph_format: 1, nodes: [node("if"), node("yes")], edges: [edge("if", "yes", "true")] };
  const nav = navModel(doc, ports({ if: ["true", "false"] }), true);
  expect(nav.children.get("node:if")).toEqual(["edge:if:true->yes", "port:if:false"]);
  expect(move(nav, "edge:if:true->yes", "ArrowRight")).toBe("port:if:false");
  expect(move(nav, "port:if:false", "ArrowRight")).toBe("port:if:false");
  expect(move(nav, "port:if:false", "ArrowLeft")).toBe("edge:if:true->yes");
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

it("offers the start card's own '+' before any step, and still reaches steps a cycle hides", () => {
  expect(navModel({ graph_format: 1, nodes: [], edges: [] }, ports({}), true).order).toEqual(["start", "port:start:out"]);
  const loop: GraphDoc = { graph_format: 1, nodes: [node("a"), node("b")], edges: [edge("a", "b"), edge("b", "a")] };
  expect(navModel(loop, ports({}), false).order).toEqual(["start", "node:a", "node:b"]);
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
```

(add `within` to the Testing Library import).

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL: `canvasNav.ts` doesn't exist; the editor ignores Delete, `a` and Ctrl+Z.

- [ ] **Step 3: Implement the model**

`frontend/src/routes/editor/canvasNav.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// The canvas's keyboard model (D16; 4b ruling 15). Its items form a tree from the start card down: the start card,
// its edges to the entry steps, each step, each edge leaving it (by port, then left to right), each free port. Down
// goes to an item's first child, Up to its parent, Left and Right among its siblings, Home to the start card. A
// read-only canvas (a viewer, a conflict, an old version) holds the start card and the steps only.
import { START, edgesOf, entries, nodesOf, portOf, pos } from "../../lib/graph";
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
  const x = new Map(nodes.map((n) => [n.id, pos(n).x]));
  const byPlace = (a: GraphEdge, b: GraphEdge) =>
    (x.get(a.to.node) ?? 0) - (x.get(b.to.node) ?? 0) || a.to.node.localeCompare(b.to.node);
  const first = [...entries(doc)].sort((a, b) => pos(a).x - pos(b).x || a.id.localeCompare(b.id));
  if (editable) {
    children.set(item.start, first.length ? first.map((n) => item.entry(n.id)) : nodes.length ? [] : [item.port(START, "out")]);
    for (const n of first) children.set(item.entry(n.id), [item.node(n.id)]);
  } else {
    children.set(item.start, first.map((n) => item.node(n.id)));
  }
  for (const n of nodes) {
    const leaving = edgesOf(doc).filter((e) => e.from.node === n.id);
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
  const seen = new Set<string>();
  const walk = (root: string, from?: string) => {
    if (seen.has(root)) return;
    seen.add(root);
    if (from) parent.set(root, from);
    const queue = [root];
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
  walk(item.start);
  for (const n of nodes) walk(item.node(n.id), item.start); // steps a cycle hides from the start card
  return { children, parent, order, edges };
}

export function move(nav: Nav, from: string, key: NavKey): string {
  if (key === "Home") return item.start;
  if (key === "ArrowDown") return nav.children.get(from)?.[0] ?? from;
  if (key === "ArrowUp") return nav.parent.get(from) ?? from;
  const up = nav.parent.get(from);
  const siblings = up === undefined ? [from] : (nav.children.get(up) ?? [from]);
  const i = siblings.indexOf(from);
  return siblings[key === "ArrowLeft" ? i - 1 : i + 1] ?? from;
}
```

- [ ] **Step 4: Implement the dialog and the panel**

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
// expressions. Read-only in 4b: 4c's drawer replaces it with Setup and Options. Escape closes it and gives focus
// back to the step.
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

export function StepPanel({
  node, type, ports, problems, expressions, editable, onDelete, onConnectPort, onClose,
}: {
  node: GraphNode; type: NodeType | undefined; ports: string[]; problems: Diagnostic[]; expressions: Expression[];
  editable: boolean; onDelete: () => void; onConnectPort: (port: string) => void; onClose: () => void;
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
        {problems.length === 0 ? (
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

- [ ] **Step 5: Wire the keyboard into the editor**

In `frontend/src/routes/editor/Editor.tsx`, add the imports (`type KeyboardEvent`, `ConfirmDialog`, `deleteEdge`,
`deleteNode`, `edgesOf`, `portsOf`, `undo`, `redo`, `NAV_KEYS`, `move`, `navModel`, `type NavKey`, `type GraphEdge`,
`ConnectDialog`, `StepPanel`), and in `Editor`:

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

  function onCanvasKey(e: KeyboardEvent<HTMLDivElement>) {
    const id = (e.target as HTMLElement).dataset.item;
    if (!id || e.altKey) return;
    const plain = !e.ctrlKey && !e.metaKey;
    if (NAV_KEYS.includes(e.key) && plain) {
      e.preventDefault();
      if (e.shiftKey && editable && id.startsWith("node:")) return nudge(id.slice(5), e.key as NavKey);
      const to = move(nav, id, e.key as NavKey);
      if (to !== id) focus(to);
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

The toolbar's Add step calls `addFrom(shown)`; the root `div` takes `onKeyDown={onEditorKey}`; the canvas takes
`focusId={shown}`, `current={panel}` and `onKeyDown={onCanvasKey}`; the picker takes
`onConnect={picker.kind === "after" && picker.from ? () => setConnecting(picker.from) : undefined}`; and after the
canvas, inside the row:

```tsx
        {panel && nodesOf(doc).some((n) => n.id === panel) && (
          <StepPanel
            node={nodesOf(doc).find((n) => n.id === panel)!}
            type={typeMap.get(nodesOf(doc).find((n) => n.id === panel)!.type)}
            ports={portMap.get(panel) ?? []}
            problems={[]}
            expressions={[]}
            editable={editable}
            onDelete={() => setAsking({ kind: "node", id: panel })}
            onConnectPort={(port) => setConnecting({ node: panel, port })}
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

- [ ] **Step 6: The keyboard-only flow in the browser**

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

The step picker's search field filters by title and ref: typing `transform`, `flow.if` and `stop` picks those types
with Enter (cmdk selects the first match).

- [ ] **Step 7: Run the tests to see them pass, then the gate**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`,
then the browser gate after a reset. Expected: PASS; `workflows` 2 passed.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/editor frontend/e2e/workflows.spec.ts
git commit -m "feat(web): the canvas's keyboard: one tab stop, arrows along the edges, A, Delete, connect, undo (D16, 4b)"
```

**Milestone 3's check:** the frontend suite, lint, types and build, then the browser gate after a reset. All pass.

## Milestone 4 — Saving, problems and publishing

### Task 13: Saving (D17): one save in flight, edits coalesced, `If-Match`; a conflict never overwrites

**Files:**
- Create: `frontend/src/lib/draftSync.ts`, `frontend/src/lib/draftSync.test.ts`
- Create: `frontend/src/routes/editor/SaveState.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `PUT /api/v1/t/{tenant_id}/workflows/{workflow_id}/draft` (`If-Match: <revision>`, body `Graph`) →
  `DraftSavedOut` (`draft_revision`, `unpublished_changes`), `409 draft_conflict`; `downloadJson`, `fileName`.
- Produces: `class DraftSync` (`new DraftSync({ revision, unpublished, save, onChange, onSettled?, delayMs? })`;
  `change(doc)`, `flush(): Promise<number>`, `retry()`, `conflict()`, `dispose()`, `current: SyncState`); `type
  SyncState = { status: "saved" | "pending" | "saving" | "conflict" | "error"; revision: number; unpublished: boolean
  }`; `class ConflictError`; `<SaveState state activeNumber />`. Task 14 hooks `onSettled`; Task 15 calls `flush()`
  before publishing and exporting.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/draftSync.test.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConflictError, DraftSync, type SyncState } from "./draftSync";
import type { GraphDoc } from "./workflows";

const doc = (n: number): GraphDoc => ({ graph_format: 1, nodes: [{ id: `n${n}`, key: `k${n}`, type: "flow.transform@1" }], edges: [] });

let calls: { doc: GraphDoc; revision: number }[];
let inFlight: number;
let maxInFlight: number;
let answers: (() => Promise<{ draft_revision: number; unpublished_changes: boolean }>)[];
let states: SyncState["status"][];
let settled: number[];

function make() {
  return new DraftSync({
    revision: 1,
    unpublished: true,
    delayMs: 1000,
    save: async (d, revision) => {
      calls.push({ doc: d, revision });
      inFlight++;
      maxInFlight = Math.max(maxInFlight, inFlight);
      try {
        return await (answers.shift() ?? (() => Promise.resolve({ draft_revision: revision + 1, unpublished_changes: true })))();
      } finally {
        inFlight--;
      }
    },
    onChange: (s) => states.push(s.status),
    onSettled: (r) => settled.push(r),
  });
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
  expect(sync.current).toEqual({ status: "saved", revision: 2, unpublished: true });
  expect(settled).toEqual([2]);
});

it("edits during a save coalesce into exactly one next save, never two at once", async () => {
  let release!: () => void;
  answers.push(() => new Promise((r) => (release = () => r({ draft_revision: 2, unpublished_changes: true }))));
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

it("a 409 stops every save and keeps the document", async () => {
  answers.push(() => Promise.reject(new ConflictError()));
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  expect(sync.current.status).toBe("conflict");
  sync.change(doc(2));
  await vi.advanceTimersByTimeAsync(5000);
  expect(calls.length).toBe(1);
  await expect(sync.flush()).rejects.toBeInstanceOf(ConflictError);
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
```

In `frontend/src/routes/editor/Editor.test.tsx`, the fetch mock records requests and answers a draft PUT from a
variable (`let putAnswer: () => Response`, defaulting to `new Response(JSON.stringify({ draft_revision: 2,
unpublished_changes: true }))`), and:

```tsx
it("saves an edit with the revision it was loaded at, and says so", async () => {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  expect(screen.getByText("Unsaved changes")).toBeTruthy();
  await vi.waitFor(() => expect(sent.find((r) => r.method === "PUT")).toBeTruthy(), { timeout: 3000 });
  const put = sent.find((r) => r.method === "PUT")!;
  expect(put.headers.get("If-Match")).toBe("1");
  expect((put.body as { nodes: { key: string }[] }).nodes.map((n) => n.key)).toEqual(["transform"]);
  await screen.findByText("Saved · not published");
});

it("turns read-only on a conflict, keeping the work downloadable", async () => {
  putAnswer = () => new Response(JSON.stringify({ error: "draft_conflict", draft_revision: 5 }), { status: 409 });
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  const alert = await screen.findByRole("alert", {}, { timeout: 3000 });
  expect(alert.textContent).toContain("changed elsewhere");
  expect(screen.queryByRole("button", { name: /Add step/ })).toBeNull();
  expect(screen.getByRole("button", { name: "Download my version" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
});
```

(the mock keeps each request's method, path, headers and body: `sent.push({ method, path, headers: request.headers,
body })`).

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib/draftSync.test.ts src/routes/editor/Editor.test.tsx`
Expected: FAIL: `draftSync.ts` doesn't exist; the editor never saves.

- [ ] **Step 3: Implement the saver**

`frontend/src/lib/draftSync.ts`:

```ts
// SPDX-License-Identifier: Apache-2.0
// Saving the draft (D17). At most one save in flight; edits made meanwhile coalesce into the next save, sent a
// second after the last change, with `If-Match` the revision the previous save returned, so the editor never
// conflicts with itself. A 409 means someone else saved: every save stops and the document stays with the person
// (read-only, downloadable), never sent over theirs. A failed save keeps the document for the next try.
import type { GraphDoc } from "./workflows";

export type SyncStatus = "saved" | "pending" | "saving" | "conflict" | "error";
export interface SyncState {
  status: SyncStatus;
  revision: number; // the revision the server holds of what was last saved
  unpublished: boolean; // that draft differs from the active version (the server's answer)
}
export interface Saved {
  draft_revision: number;
  unpublished_changes: boolean;
}

export class ConflictError extends Error {
  constructor() {
    super("the draft changed elsewhere");
  }
}

export class DraftSync {
  private state: SyncState;
  private latest: GraphDoc | null = null; // the newest document not yet sent
  private timer: ReturnType<typeof setTimeout> | null = null;
  private inflight: Promise<void> | null = null;

  constructor(
    private readonly opts: {
      revision: number;
      unpublished: boolean;
      save: (doc: GraphDoc, revision: number) => Promise<Saved>;
      onChange: (state: SyncState) => void;
      onSettled?: (revision: number) => void;
      delayMs?: number;
    },
  ) {
    this.state = { status: "saved", revision: opts.revision, unpublished: opts.unpublished };
  }

  get current(): SyncState {
    return this.state;
  }

  private set(patch: Partial<SyncState>) {
    this.state = { ...this.state, ...patch };
    this.opts.onChange(this.state);
  }

  private schedule(ms = this.opts.delayMs ?? 1000) {
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      void this.run();
    }, ms);
  }

  change(doc: GraphDoc): void {
    if (this.state.status === "conflict") return;
    this.latest = doc;
    if (!this.inflight) this.set({ status: "pending" });
    this.schedule();
  }

  /** Try again now after a failed save. */
  retry(): void {
    if (this.state.status === "error" && this.latest) this.schedule(0);
  }

  /** Someone else saved (a publish's 409 says so too): stop saving. */
  conflict(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.set({ status: "conflict" });
  }

  private run(): Promise<void> {
    if (this.inflight || this.latest === null || this.state.status === "conflict") return this.inflight ?? Promise.resolve();
    const doc = this.latest;
    this.latest = null;
    this.set({ status: "saving" });
    this.inflight = (async () => {
      try {
        const saved = await this.opts.save(doc, this.state.revision);
        this.state = { ...this.state, revision: saved.draft_revision, unpublished: saved.unpublished_changes };
      } catch (e) {
        if (e instanceof ConflictError) {
          this.set({ status: "conflict" });
          return;
        }
        this.latest ??= doc;
        this.set({ status: "error" });
        return;
      } finally {
        this.inflight = null;
      }
      if (this.latest !== null) {
        this.set({ status: "pending" });
        this.schedule();
      } else {
        this.set({ status: "saved" });
        this.opts.onSettled?.(this.state.revision);
      }
    })();
    return this.inflight;
  }

  /** Save now whatever is pending; answer the revision saved (publish's `If-Match`). Rejects on a conflict or a
   * failed save: nothing is published over what isn't saved. */
  async flush(): Promise<number> {
    for (;;) {
      if (this.state.status === "conflict") throw new ConflictError();
      if (this.timer) {
        clearTimeout(this.timer);
        this.timer = null;
      }
      if (this.inflight) await this.inflight;
      else if (this.latest !== null) {
        const before = this.state.status;
        await this.run();
        if (before === "error" && this.state.status === "error") throw new Error("the draft isn't saved");
      } else break;
      if (this.state.status === "error") throw new Error("the draft isn't saved");
    }
    return this.state.revision;
  }

  dispose(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
  }
}
```

`frontend/src/routes/editor/SaveState.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The draft's state, in words, beside the workflow's name (1c's "Saved"): never a colour alone.
import type { SyncState } from "../../lib/draftSync";

export function SaveState({ state, activeNumber }: { state: SyncState; activeNumber: number | null }) {
  const text =
    state.status === "pending" ? "Unsaved changes"
    : state.status === "saving" ? "Saving…"
    : state.status === "error" ? "Not saved"
    : state.status === "conflict" ? "Changed elsewhere"
    : activeNumber === null ? "Saved · not published"
    : state.unpublished ? `Saved · unpublished changes since v${activeNumber}`
    : `Saved · published as v${activeNumber}`;  // prettier-ignore
  const tone = state.status === "error" || state.status === "conflict" ? "text-danger" : state.status === "saved" ? "text-ok" : "text-muted";
  return <span className={`text-small ${tone}`}>{text}</span>;
}
```

- [ ] **Step 4: Wire it into the editor**

In `frontend/src/routes/editor/Editor.tsx`, import `useEffect`, `useRef`, `ApiError`, `client`, `ok`,
`ConflictError`, `DraftSync`, `type SyncState`, `downloadJson`, `fileName`, `useQueryClient`, `SaveState`. In
`EditorPage`, key the editor by a reload count, so Reload mounts it afresh from the server's draft:

```tsx
  const qc = useQueryClient();
  const [loads, setLoads] = useState(0);
  const reload = async () => {
    await qc.invalidateQueries({ queryKey: ["workflow", tenantId, workflowId] });
    setLoads((n) => n + 1);
  };
  ...
  return <Editor key={loads} tenantId={tenantId} workflow={workflow.data} types={types.data} role={tenant.data.role ?? null} onReload={() => void reload()} />;
```

In `Editor` (which takes `onReload`):

```tsx
  const [sync, setSyncState] = useState<SyncState>({ status: "saved", revision: workflow.draft_revision, unpublished: workflow.unpublished_changes });
  const saver = useRef<DraftSync | null>(null);
  if (saver.current === null) {
    saver.current = new DraftSync({
      revision: workflow.draft_revision,
      unpublished: workflow.unpublished_changes,
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
  }
  useEffect(() => () => saver.current?.dispose(), []);
  // Leaving with unsaved work asks first (the browser's own prompt).
  useEffect(() => {
    if (sync.status !== "pending" && sync.status !== "saving" && sync.status !== "error") return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [sync.status]);
  const editable = canEdit(role) && sync.status !== "conflict";
```

`change` and undo/redo hand each new document to the saver:

```tsx
  function change(next: GraphDoc, message: string, then?: string) {
    setHistory((h) => record(h, next));
    saver.current!.change(next);
    announce(message);
    if (then) focus(then);
  }
```

```tsx
    const next = e.shiftKey ? redo(history) : undo(history);
    if (next === history) return;
    setHistory(next);
    saver.current!.change(next.present);
    announce(e.shiftKey ? "Redone" : "Undone");
```

The toolbar shows `<SaveState state={sync} activeNumber={workflow.active_version_number} />` first, and a Retry
button when `sync.status === "error"` (`onClick={() => saver.current!.retry()}`). Its "Read only" note now depends
on the role alone (a conflict has its own banner): `{editable ? <AddStep /> : !canEdit(role) ? <span …>Read only:
your role can't edit workflows</span> : null}`. Below the toolbar, on a conflict:

```tsx
      {sync.status === "conflict" && (
        <div role="alert" className="flex flex-wrap items-center gap-3 border-b border-danger bg-danger-bg px-5 py-2.5 text-small text-ink">
          <span className="grow">
            This draft was changed elsewhere, so your changes since then aren&apos;t saved. Reload to see the saved draft, or
            download your version to keep it.
          </span>
          <Button size="sm" onClick={() => downloadJson(fileName(workflow.name, ".draft.json"), doc)}>Download my version</Button>
          <Button size="sm" variant="primary" onClick={onReload}>Reload</Button>
        </div>
      )}
```

The banner's border is a full 1 px bottom rule, not a side stripe (outline §6); `ink` on `danger-bg` is in PAIRS.

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/lib/draftSync.test.ts src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/draftSync.ts frontend/src/lib/draftSync.test.ts frontend/src/routes/editor
git commit -m "feat(web): the draft saves itself: one save in flight, edits coalesced, If-Match; a conflict never overwrites (D17, 4b)"
```

### Task 14: Problems: validated on the saved revision, shown on the steps and in a panel, a problem focusing its step

**Files:**
- Create: `frontend/src/routes/editor/ProblemsPanel.tsx`, `frontend/src/routes/editor/ProblemsPanel.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `POST …/validate` → `ValidationOut` (`draft_revision`, `valid`, `diagnostics`, `expressions`); the saver's
  `onSettled(revision)` and `current.revision` (Task 13); `StepPanel`'s `problems` and `expressions` (Task 12).
- Produces: `<ProblemsPanel validation publishProblems revision keyOf onJump onClose />`, `type PublishProblems = {
  revision: number; diagnostics: Diagnostic[] }` (Task 15 sets it); the editor's right column holds one panel at a
  time: `type Side = { kind: "step"; node: string } | { kind: "problems" } | { kind: "versions" } | null`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/routes/editor/ProblemsPanel.test.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
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
const keyOf = (id: string) => ({ n1: "transform" })[id] ?? id;

it("lists errors before warnings, each with its fix and code, a step's going to the step", async () => {
  const onJump = vi.fn();
  render(<ProblemsPanel validation={VALIDATION} publishProblems={null} revision={4} keyOf={keyOf} onJump={onJump} onClose={vi.fn()} />);
  const panel = screen.getByRole("complementary", { name: "Problems" });
  const items = within(panel).getAllByRole("listitem");
  expect(items[0]!.textContent).toContain("fields needs at least one entry");
  expect(items[0]!.textContent).toContain("fix config.invalid");
  expect(items[1]!.textContent).toContain("vars.unassigned");
  await userEvent.click(within(items[0]!).getByRole("button", { name: "Go to transform" }));
  expect(onJump).toHaveBeenCalledWith("n1");
});

it("says how each expression runs (engine-core §5.10)", () => {
  render(<ProblemsPanel validation={VALIDATION} publishProblems={null} revision={4} keyOf={keyOf} onJump={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByText(/Runs as a separate step: builds a message/)).toBeTruthy();
  expect(screen.getByText("1 expression runs inline.")).toBeTruthy();
});

it("shows what only publish checks apart, and says when edits came since", () => {
  const found = { revision: 3, diagnostics: [d("connection.unknown", "n1", "error", "That connection doesn't exist.")] };
  render(<ProblemsPanel validation={VALIDATION} publishProblems={found} revision={4} keyOf={keyOf} onJump={vi.fn()} onClose={vi.fn()} />);
  const section = screen.getByRole("region", { name: "Found at publish" });
  expect(section.textContent).toContain("That connection doesn't exist.");
  expect(section.textContent).toContain("before your latest edits");
});
```

In `frontend/src/routes/editor/Editor.test.tsx`, the fetch mock answers validate from a variable
(`let validateAnswer: () => object`, defaulting to the valid answer at revision 1), and:

```tsx
it("validates the saved revision once a save settles, and counts its problems", async () => {
  validateAnswer = () => ({
    draft_revision: 2, valid: false, taint: { sites: [], declassified: [] }, expressions: [],
    diagnostics: [{ code: "config.invalid", message: "fields needs at least one entry", node: "x", field: "/fields", fix: null, severity: "error" }],
  });  // prettier-ignore
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  expect(await screen.findByRole("button", { name: "Problems · 1" }, { timeout: 3000 })).toBeTruthy();
});

it("drops an answer for an older revision (D17)", async () => {
  let validations = 0;
  validateAnswer = () =>
    ++validations === 1
      ? { draft_revision: 1, valid: true, taint: { sites: [], declassified: [] }, expressions: [], diagnostics: [] }
      : { draft_revision: 1, valid: false, taint: { sites: [], declassified: [] }, expressions: [],
          diagnostics: [{ code: "config.invalid", message: "stale", node: null, field: null, fix: null, severity: "error" }] };  // prettier-ignore
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await screen.findByText("Saved · not published", {}, { timeout: 3000 });
  await vi.waitFor(() => expect(validations).toBe(2)); // on load, and after the save
  expect(screen.getByRole("button", { name: "No problems" })).toBeTruthy();
});
```

The answer on load is for revision 1, the editor's revision then: kept, and clean. The answer after the save made the
revision 2 still says revision 1: it's dropped, never painted on the newer draft, so the toolbar still says "No
problems".

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor`
Expected: FAIL: no panel; the editor never validates.

- [ ] **Step 3: Implement the panel**

`frontend/src/routes/editor/ProblemsPanel.tsx`:

```tsx
// SPDX-License-Identifier: Apache-2.0
// The draft's problems (outline §2's validate and publish; engine-core §5.10). The server's messages and fixes, as
// it wrote them: there's no catalogue in the client. A step's problem goes to the step (4b ruling 16). What only
// publish checks shows apart, marked, and dated against the edits since (4b ruling 17).
import { useEffect, useRef } from "react";
import { Button } from "../../components/Button";
import type { Diagnostic, Validation } from "../../lib/workflows";

export type PublishProblems = { revision: number; diagnostics: Diagnostic[] };

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

export function ProblemsPanel({
  validation, publishProblems, revision, keyOf, onJump, onClose,
}: {
  validation: Validation | null; publishProblems: PublishProblems | null; revision: number; keyOf: (id: string) => string;
  onJump: (nodeId: string) => void; onClose: () => void;
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
      {validation === null ? (
        <p className="text-small text-muted">Not checked yet.</p>
      ) : validation.diagnostics.length === 0 ? (
        <p className="text-small text-muted">None found in the saved draft. Publishing checks a few more things.</p>
      ) : (
        <ul>{ordered(validation.diagnostics).map((d, i) => <Problem key={`${d.code}:${d.node}:${d.field}:${i}`} d={d} keyOf={keyOf} onJump={onJump} />)}</ul>
      )}
      {publishProblems && (
        <section aria-labelledby="publish-problems" className="flex flex-col gap-1">
          <h3 id="publish-problems" className="text-small font-semibold">Found at publish</h3>
          <p className="text-small text-muted">
            {publishProblems.revision === revision
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

- [ ] **Step 4: Validate on the saved revision, and show the problems**

In `frontend/src/routes/editor/Editor.tsx`, the right column holds one panel at a time. Above `Editor`:

```tsx
/** The editor's right column: a step's panel, the problems, or the versions (Task 15). */
type Side = { kind: "step"; node: string } | { kind: "problems" } | { kind: "versions" } | null;
```

and it replaces Task 12's `panel` state: `setPanel(id)` becomes `setSide({ kind: "step", node: id })`, `setPanel(null)`
becomes `setSide(null)`, and `panel === x` becomes `side?.kind === "step" && side.node === x` (in `confirmDelete`,
the canvas's `current`, and the step panel's rendering and `onClose`). In `Editor`:

```tsx
  const [validation, setValidation] = useState<Validation | null>(null);
  const [publishProblems, setPublishProblems] = useState<PublishProblems | null>(null);
  const [side, setSide] = useState<Side>(null);

  /** Validate the saved draft; keep the answer only if it's for the revision saved now (D17). */
  const validate = useRef(async () => {});
  validate.current = async () => {
    if (!canEdit(role)) return; // validate needs workflow.edit
    try {
      const answer = await ok(
        client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/validate", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id } },
        }),
      );
      if (answer.draft_revision === saver.current!.current.revision) setValidation(answer);
    } catch {
      // A failed check changes nothing shown: the next save checks again.
    }
  };
  useEffect(() => void validate.current(), []);
```

The saver's options gain `onSettled: () => void validate.current()`. From the answer:

```tsx
  const problems = useMemo(() => {
    const counts = new Map<string, Problems>();
    for (const d of validation?.diagnostics ?? []) {
      if (!d.node) continue;
      const c = counts.get(d.node) ?? { errors: 0, warnings: 0 };
      counts.set(d.node, d.severity === "error" ? { ...c, errors: c.errors + 1 } : { ...c, warnings: c.warnings + 1 });
    }
    return counts;
  }, [validation]);
  const separate = useMemo(() => {
    const counts = new Map<string, number>();
    for (const x of validation?.expressions ?? []) if (x.node && x.mode === "activity") counts.set(x.node, (counts.get(x.node) ?? 0) + 1);
    return counts;
  }, [validation]);
  const count = (validation?.diagnostics.length ?? 0) + (publishProblems?.diagnostics.length ?? 0);
```

The canvas takes `problems={problems}`, `separate={separate}` and `current={side?.kind === "step" ? side.node : null}`;
`onItem`'s `open` becomes `setSide({ kind: "step", node: action.node })`; the step panel's `problems` are
`[...(validation?.diagnostics ?? []), ...(publishProblems?.diagnostics ?? [])].filter((d) => d.node === side.node)`
and its `expressions` `validation?.expressions.filter((x) => x.node === side.node) ?? []`. The toolbar gains, after the
save state:

```tsx
        <Button
          size="md"
          aria-expanded={side?.kind === "problems"}
          onClick={() => setSide(side?.kind === "problems" ? null : { kind: "problems" })}
        >
          {count === 0 ? "No problems" : `Problems · ${count}`}
        </Button>
```

and the right column shows, for `side?.kind === "problems"`:

```tsx
          <ProblemsPanel
            validation={validation}
            publishProblems={publishProblems}
            revision={sync.revision}
            keyOf={keyOf}
            onJump={(nodeId) => focus(item.node(nodeId))}
            onClose={() => setSide(null)}
          />
```

`Problems` is imported from `./StepCard`; `Validation` and `Diagnostic` from `../../lib/workflows`; `ProblemsPanel`
and `type PublishProblems` from `./ProblemsPanel`.

- [ ] **Step 5: Run the tests to see them pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/editor
git commit -m "feat(web): problems on the saved revision, on the steps and in a panel; a problem focuses its step (4b)"
```

### Task 15: Publishing with a confirmation that names the version; versions viewed and made active; export from the editor

**Files:**
- Modify: `frontend/src/components/ConfirmDialog.tsx`, `frontend/src/components/ConfirmDialog.test.tsx` (`tone`)
- Modify: `frontend/src/lib/draftSync.ts`, `frontend/src/lib/draftSync.test.ts` (`setUnpublished()`)
- Create: `frontend/src/routes/editor/VersionsPanel.tsx`, `frontend/src/routes/editor/VersionsPanel.test.tsx`
- Modify: `frontend/src/routes/editor/Editor.tsx`, `frontend/src/routes/editor/Editor.test.tsx`

**Interfaces:**
- Consumes: `POST …/publish` (`If-Match`) → `PublishedOut` (`number`), `422 invalid` (diagnostics, publish-only codes
  included), `409 draft_conflict`; `versionsQuery`; `GET …/versions/{version_id}` → `VersionDetailOut`; `POST
  …/activate` (`{version_id}`) → `ActivatedOut`, `422 not_activatable`; `GET …/export`; `flush()` (Task 13).
- Produces: `ConfirmDialog`'s `tone?: "danger" | "primary"` (default `"danger"`); `DraftSync.setUnpublished(value)`;
  `<VersionsPanel versions activeId publisher onView onActivate onClose />`.

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
```

In `frontend/src/lib/draftSync.test.ts`:

```ts
it("takes the server's word on whether the saved draft differs from the active version", async () => {
  const sync = make();
  sync.change(doc(1));
  await vi.advanceTimersByTimeAsync(1000);
  expect(sync.current.unpublished).toBe(true);
  sync.setUnpublished(false); // just published
  expect(sync.current.unpublished).toBe(false);
  sync.setUnpublished(true); // another version made active
  expect(sync.current.unpublished).toBe(true);
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

In `frontend/src/routes/editor/Editor.test.tsx`, the fetch mock answers `GET …/versions` with `[]` and `POST
…/publish` from a variable (`let publishAnswer: () => Response`, defaulting to `new Response(JSON.stringify({
version_id: "v1", number: 1, warnings: [] }), { status: 201 })`), and:

```tsx
it("publishes after saving, with a confirmation that names the version, and says so", async () => {
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Start" }));
  await userEvent.click(await screen.findByRole("option", { name: /flow\.transform@1/ }));
  await userEvent.click(screen.getByRole("button", { name: "Publish v1" }));
  const ask = screen.getByRole("dialog", { name: "Publish version 1" });
  expect(ask.textContent).toContain("becomes the active version");
  await userEvent.click(within(ask).getByRole("button", { name: "Publish" }));
  await screen.findByText("Saved · published as v1", {}, { timeout: 3000 });
  const put = sent.findIndex((r) => r.method === "PUT");
  const publish = sent.findIndex((r) => r.path.endsWith("/publish"));
  expect(put).toBeGreaterThanOrEqual(0);
  expect(publish).toBeGreaterThan(put); // flushed first
  expect(sent[publish]!.headers.get("If-Match")).toBe("2");
});

it("shows what only publish checks, in the problems panel, marked", async () => {
  publishAnswer = () =>
    new Response(JSON.stringify({ error: "invalid", diagnostics: [{ code: "connection.unknown", message: "That connection doesn't exist.", node: null, field: null, fix: null, severity: "error" }] }), { status: 422 });
  await show();
  await userEvent.click(screen.getByRole("button", { name: "Publish v1" }));
  await userEvent.click(within(screen.getByRole("dialog", { name: "Publish version 1" })).getByRole("button", { name: "Publish" }));
  const panel = await screen.findByRole("complementary", { name: "Problems" });
  expect(within(panel).getByRole("region", { name: "Found at publish" }).textContent).toContain("That connection doesn't exist.");
});

it("offers no Publish to a viewer", async () => {
  role = "viewer";
  await show();
  await screen.findByRole("heading", { level: 1, name: "Nightly" });
  expect(screen.queryByRole("button", { name: /^Publish/ })).toBeNull();
});
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/components/ConfirmDialog.test.tsx src/lib/draftSync.test.ts src/routes/editor`
Expected: FAIL: no `tone`, no `setUnpublished()`, no versions panel, no Publish.

- [ ] **Step 3: Implement the dialog's tone and the saver's `setUnpublished()`**

In `frontend/src/components/ConfirmDialog.tsx`, the props gain `tone = "danger"` (`tone?: "danger" | "primary"`), and
the confirm button becomes `<Button variant={tone} onClick={onConfirm} disabled={busy}>{confirmLabel}</Button>`; the
header comment adds: "A constructive action (publish, make active) confirms in the primary colour; focus still starts
on Cancel."

In `frontend/src/lib/draftSync.ts`:

```ts
  /** The server's word on whether the saved draft differs from the active version: false once it's published, and
   * whatever a fresh summary says once another version is made active. */
  setUnpublished(unpublished: boolean): void {
    this.set({ unpublished });
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

In `frontend/src/routes/editor/Editor.tsx` (imports: `useQueryClient`, `versionsQuery`, `canPublish`, `type
VersionDetail`, `type VersionRow`, `VersionsPanel`, `downloadJson`, `fileName`):

```tsx
  const qc = useQueryClient();
  const versions = useQuery(versionsQuery(tenantId, workflow.id));
  const next = (versions.data?.[0]?.number ?? 0) + 1; // the list is newest first
  const [activeNumber, setActiveNumber] = useState(workflow.active_version_number);
  const [viewing, setViewing] = useState<VersionDetail | null>(null);
  const [confirm, setConfirm] = useState<{ kind: "publish" } | { kind: "activate"; version: VersionRow } | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const publisher = canPublish(role) && sync.status !== "conflict";
  const editable = canEdit(role) && sync.status !== "conflict" && viewing === null;
  const shownDoc = viewing ? asGraph(viewing.graph) : doc;

  const refresh = async () => {
    await qc.invalidateQueries({ queryKey: ["versions", tenantId, workflow.id] });
    await qc.invalidateQueries({ queryKey: ["workflows", tenantId] });
  };

  async function publish() {
    setBusy(true);
    setNotice(null);
    let revision = sync.revision;
    try {
      revision = await saver.current!.flush();
      const done = await ok(
        client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/publish", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id }, header: { "If-Match": String(revision) } },
        }),
      );
      saver.current!.setUnpublished(false);
      setActiveNumber(done.number);
      setPublishProblems(null);
      announce(`Published version ${done.number}`);
      await refresh();
    } catch (e) {
      if (e instanceof ConflictError) return; // the saver says so: read-only, with the banner
      if (e instanceof ApiError && e.status === 409) return saver.current!.conflict();
      if (e instanceof ApiError && e.code === "invalid") {
        const diagnostics = (e.body as { diagnostics: Diagnostic[] }).diagnostics;
        setPublishProblems({ revision, diagnostics });
        setSide({ kind: "problems" });
        announce(`Not published: ${diagnostics.filter((d) => d.severity === "error").length} problems`);
        return;
      }
      setNotice("Not published. Check your connection and try again.");
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  async function view(version: VersionRow) {
    try {
      const detail = await ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/versions/{version_id}", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id, version_id: version.id } },
        }),
      );
      setViewing(detail);
      setSide(null);
      focus(START);
      announce(`Viewing version ${detail.number}, read only`);
    } catch {
      setNotice(`Version ${version.number} couldn't be opened. Try again.`);
    }
  }

  async function activate(version: VersionRow) {
    setBusy(true);
    try {
      await ok(
        client.POST("/api/v1/t/{tenant_id}/workflows/{workflow_id}/activate", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id } },
          body: { version_id: version.id },
        }),
      );
      setActiveNumber(version.number);
      // Only the server can say whether the draft now differs from the active version: ask it.
      const fresh = await ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id } },
        }),
      );
      saver.current!.setUnpublished(fresh.unpublished_changes);
      announce(`Version ${version.number} is active`);
      await refresh();
    } catch (e) {
      const first = e instanceof ApiError && e.code === "not_activatable"
        ? (e.body as { diagnostics?: Diagnostic[] }).diagnostics?.[0]?.message
        : undefined;  // prettier-ignore
      setNotice(first ? `Version ${version.number} can't be made active: ${first}` : `Version ${version.number} wasn't made active. Try again.`);
    } finally {
      setBusy(false);
      setConfirm(null);
    }
  }

  /** The saved draft as a file (B12; 4b ruling 18): what's pending is saved first. */
  async function exportFile() {
    try {
      await saver.current!.flush();
    } catch {
      // A conflict or a failed save: the file is what the server holds.
    }
    try {
      const file = await ok(
        client.GET("/api/v1/t/{tenant_id}/workflows/{workflow_id}/export", {
          params: { path: { tenant_id: tenantId, workflow_id: workflow.id } },
        }),
      );
      downloadJson(fileName(workflow.name, ".dewpoint.json"), file);
    } catch {
      setNotice("The workflow couldn't be exported. Try again.");
    }
  }
```

The canvas draws `shownDoc` with `editable={editable}`; `navModel` reads `shownDoc` and `editable`; `SaveState` takes
`activeNumber={activeNumber}`. The toolbar's actions, after Problems:

```tsx
        <Button size="md" aria-expanded={side?.kind === "versions"} onClick={() => setSide(side?.kind === "versions" ? null : { kind: "versions" })}>
          Versions
        </Button>
        <Button size="md" onClick={() => void exportFile()}>Export</Button>
        {publisher && viewing === null && (
          <Button variant="primary" size="md" disabled={busy} onClick={() => setConfirm({ kind: "publish" })}>
            Publish v{next}
          </Button>
        )}
```

Below the toolbar, when viewing a version, and for a notice:

```tsx
      {viewing && (
        <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface-2 px-5 py-2.5 text-small">
          <span className="grow">Viewing version {viewing.number}, read only. The draft is unchanged.</span>
          <Button size="sm" onClick={() => { setViewing(null); focus(START); }}>Back to the draft</Button>
        </div>
      )}
      {notice && <p role="alert" className="border-b border-line bg-surface px-5 py-2.5 text-small text-danger">{notice}</p>}
```

The right column shows, for `side?.kind === "versions"`:

```tsx
          <VersionsPanel
            versions={versions.data ?? []}
            publisher={publisher}
            onView={(v) => void view(v)}
            onActivate={(version) => setConfirm({ kind: "activate", version })}
            onClose={() => setSide(null)}
          />
```

and the confirmations:

```tsx
      <ConfirmDialog
        open={confirm !== null}
        tone="primary"
        busy={busy}
        title={confirm?.kind === "activate" ? `Make version ${confirm.version.number} active` : `Publish version ${next}`}
        confirmLabel={confirm?.kind === "activate" ? "Make active" : "Publish"}
        onConfirm={() => void (confirm?.kind === "activate" ? activate(confirm.version) : publish())}
        onCancel={() => setConfirm(null)}
      >
        {confirm?.kind === "activate"
          ? `Runs start on version ${confirm.version.number} from now on. The draft doesn't change.`
          : `Your latest edits are saved first. Version ${next} of ${workflow.name} becomes the active version${workflow.enabled ? ": its triggers start runs on it" : ""}.`}
      </ConfirmDialog>
```

`ConflictError`, `Diagnostic` and `VersionDetail` join the imports.

- [ ] **Step 6: Run the tests to see them pass**

Run: `cd frontend && npx -y pnpm@12.6.0 exec vitest run src/components/ConfirmDialog.test.tsx src/lib src/routes/editor && npx -y pnpm@12.6.0 test && npx -y pnpm@12.6.0 lint && npx -y pnpm@12.6.0 typecheck`
Expected: PASS and clean (Members' removal dialog keeps `tone="danger"` by default).

- [ ] **Step 7: Commit**

```bash
git add frontend/src
git commit -m "feat(web): publish with a confirmation naming the version; versions viewed and made active; export (4b)"
```

### Task 16: The slice end to end behind nginx: saved, problems, published, versions, a conflict, a file round trip, reflow; then every check

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
async function importReport(page: Page, name: string): Promise<void> {
  await page.goto(`/t/${await tenantId(page)}/workflows`);
  await page.getByTestId("workflow-new").click();
  const dialog = page.getByRole("dialog", { name: "New workflow" });
  await dialog.getByLabel("Name").fill(name);
  await dialog.getByRole("radio", { name: /Import from file/ }).check();
  await dialog.getByLabel("Workflow file").setInputFiles("e2e/fixtures/report.dewpoint.json");
  await expect(dialog.getByText("The file names no connection or workflow.")).toBeVisible();
  await expectAccessible(page, "new workflow: import");
  await dialog.getByRole("button", { name: "Import and open" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}$/);
}

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
  await alert.getByRole("button", { name: "Reload" }).click();
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
Expected: `foundations` 8 passed (4a's two flows, the five gate self-tests and the notices check), `workflows` 7
passed. A failure is a finding: fix
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
1–21 as ledger rulings 68–88 (amended as the owner rules), and each mid-slice ruling the execution made, with its why
and its cost if wrong. Then:

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

Run against the outline's slice 4b, its decisions and its backend items, with the plan in hand:

1. **Spec coverage.**
   - 1a, its filters and the enable toggle (B3): Tasks 3, 6, 7.
   - 1b, Blank and Import from file (D9, B12): Tasks 5, 8.
   - The canvas: React Flow (Task 11), dagre on demand (Task 10), zoom (Task 11), minimap (Task 11).
   - Badges on the step cards: problems (Task 14). "Conditional" and "disabled" are ruled out of 4b (ruling 3).
   - "+" on edges and ports, and `A` with the type picker (B5): Tasks 1, 11, 12.
   - The keyboard (D16): Task 12.
   - Autosave with `If-Match`, where a 409 never overwrites (D17): Task 13.
   - Validate: the panel, per-step badges, focus jumping to the step (the field waits for 4c, ruling 16), and CEL
     classes with their reasons: Task 14.
   - The §5.10 messages: the server's own text, Task 14.
   - Publish, its confirmation naming the version, and the publish-only checks: Task 15.
   - B4a: Task 4, used by Task 15.
   - Ruling 47's `Graph` on the draft PUT: Task 2.
   - Workflows in the rail, the landing page and the palette (D10, outline §2): Task 6.
   - New packages, licences and notices (D22, ruling 65): Tasks 6 and 16.
   - The browser gate's CSP, console and axe checks on each new screen (D21, D23): Tasks 11, 12 and 16.
   - No AI tells (§6): stated in each component, and enforced by the guard and the reviewer.
2. **Placeholders.** None: every step that changes code shows the code, and every test shows its assertions. Where
   the installed package decides a detail (dagre's export shape, React Flow's class names, a CHECK on `runs`), the
   step says to read the package first and how to adapt it. That's the owner's standing rule, not a gap.
3. **Type consistency.**
   - `PortRef`, `ItemAction` and `PickMode` keep one shape across Tasks 9–15.
   - `item.*` ids are built only in `items.ts` and read by `canvasNav.ts` and the components.
   - `SyncState` and `DraftSync` methods: `change`, `flush`, `retry`, `conflict`, `setUnpublished` and `dispose`
     (Tasks 13 and 15).
   - `Problems` is `{errors, warnings}`, from Tasks 11 and 14.
   - `Side` replaces Task 12's `panel` in Task 14, and Task 14 says so.
   - The schema names come from Tasks 1–5: `NodeTypeOut`, `WorkflowOut`, `WorkflowDetailOut`, `DraftSavedOut`,
     `ValidationOut`, `DiagnosticOut`, `ExpressionOut`, `VersionOut`, `VersionDetailOut`, `WorkflowDocument`, and
     `Graph` (refined).
4. **Review Focus.** Each of its five lines has a test in the task that owns the code:
   - Task 13: `a 409 stops every save and keeps the document`, and `edits during a save coalesce into exactly one next
     save`.
   - Task 14: `drops an answer for an older revision`.
   - Task 9: `keeps what it doesn't touch, byte for byte`, plus Task 11's unknown-type card. Task 16's import of a
     graph with a `settings` block covers this through the browser.
   - Task 5: `a binding of the wrong kind is refused and nothing is created`.
